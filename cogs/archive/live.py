import discord
import discord.opus
from discord.ext import commands, tasks, voice_recv
import yt_dlp
import asyncio
import os
import json
import uuid
import traceback
import random
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from lyricsgenius import Genius
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from google import genai
from google.genai import types

original_opus_decode = discord.opus.Decoder.decode

def patched_opus_decode(self, data, *args, **kwargs):
    try:
        return original_opus_decode(self, data, *args, **kwargs)
    except discord.opus.OpusError:
        return b'\x00' * 3840

discord.opus.Decoder.decode = patched_opus_decode

def load_json_file(file_path, default_data=None):
    if default_data is None:
        default_data = {}
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if not os.path.exists(file_path) or os.stat(file_path).st_size == 0:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=4)
            return default_data
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(default_data, dict):
                for k, v in default_data.items():
                    if k not in data:
                        data[k] = v
            return data
    except Exception:
        return default_data

def save_json_file(file_path, data):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

LISTENING_HISTORY_FILE = 'data/listening_history.json'
USER_PREFERENCES_FILE = 'data/user_preferences.json'
WEEKLY_STATS_FILE = 'data/weekly_stats.json'

youtube_cookies_raw = os.getenv("YOUTUBE_COOKIES")
if youtube_cookies_raw:
    with open('cookies.txt', 'w', encoding='utf-8') as f:
        f.write(youtube_cookies_raw)

youtube_cookies_raw = os.getenv("YOUTUBE_COOKIES")
if youtube_cookies_raw:
    with open('cookies.txt', 'w', encoding='utf-8') as f:
        f.write(youtube_cookies_raw)

ytdl_opts = {
    'format': 'ba/b',
    'cookiefile': 'cookies.txt',
    'quiet': True,
    'default_search': 'ytsearch',
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'noplaylist': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios']
        }
    },
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '128',
    }],
}


FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -b:a 128k -bufsize 1024K -probesize 10M -analyzeduration 10M -fflags +discardcorrupt -flags +global_header -af "afftdn,equalizer=f=80:width=80:g=4,equalizer=f=10000:width=2000:g=4,loudnorm"'
}

ytdl = yt_dlp.YoutubeDL(ytdl_opts)

class GeminiReceiverSink(voice_recv.AudioSink):
    def __init__(self, input_queue, bot_instance):
        super().__init__()
        self.input_queue = input_queue
        self.bot = bot_instance

    def wants_opus(self):
        return False

    def write(self, user, data):
        if user is None or user == self.bot.user:
            return
            
        if hasattr(data, 'pcm') and data.pcm:
            try:
                mono_16k_pcm = memoryview(data.pcm).cast('h')[0::6].tobytes()
                self.input_queue.put_nowait(mono_16k_pcm)
            except Exception:
                pass

    def cleanup(self):
        pass

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.8):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.thumbnail = data.get('thumbnail')
        self.webpage_url = data.get('webpage_url')
        self.duration = data.get('duration')
        self.uploader = data.get('uploader')
        self.requester = data.get('requester', 'N/A')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

class MusicControlView(discord.ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.load_donation_buttons()

    def load_donation_buttons(self):
        try:
            with open('reswan/data/donation_buttons.json', 'r', encoding='utf-8') as f:
                donation_data = json.load(f)
                for button_data in donation_data:
                    self.add_item(discord.ui.Button(
                        label=button_data['label'],
                        style=discord.ButtonStyle.url,
                        url=button_data['url'],
                        row=3
                    ))
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            pass

    async def _check_voice_channel(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            await interaction.response.send_message("Bot tidak ada di voice channel!", ephemeral=True)
            return False
        if not interaction.user.voice or interaction.user.voice.channel != interaction.guild.voice_client.channel:
            await interaction.response.send_message("Kamu harus di channel suara yang sama dengan bot!", ephemeral=True)
            return False
        return True

    async def _update_music_message(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        current_message_info = self.cog.current_music_message_info.get(guild_id)
        vc = interaction.guild.voice_client
        queue = self.cog.get_queue(guild_id)
        if vc and vc.is_playing() and vc.source and guild_id in self.cog.now_playing_info:
            info = self.cog.now_playing_info[guild_id]
            source = vc.source
            new_embed = discord.Embed(
                title="🎶 Sedang Memutar",
                description=f"**[{info['title']}]({info['webpage_url']})**",
                color=discord.Color.purple()
            )
            if source.thumbnail:
                new_embed.set_thumbnail(url=source.thumbnail)
            duration_str = "N/A"
            if source.duration:
                minutes, seconds = divmod(source.duration, 60)
                duration_str = f"{minutes:02}:{seconds:02}"
            new_embed.add_field(name="Durasi", value=duration_str, inline=True)
            new_embed.add_field(name="Diminta oleh", value=info.get('requester', 'N/A'), inline=True)
            new_embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")
        else:
            new_embed = discord.Embed(
                title="Musik Bot",
                description="Antrean kosong.",
                color=discord.Color.red()
            )
        updated_view = MusicControlView(self.cog)
        vc = interaction.guild.voice_client
        if not vc:
            for item in updated_view.children:
                item.disabled = True
        else:
            for item in updated_view.children:
                if item.custom_id == "music:play_pause":
                    if vc.is_playing():
                        item.emoji = "⏸️"
                        item.style = discord.ButtonStyle.green
                    elif vc.is_paused():
                        item.emoji = "▶️"
                        item.style = discord.ButtonStyle.primary
                elif item.custom_id == "music:mute_unmute":
                    if self.cog.is_muted.get(guild_id, False):
                        item.emoji = "🔇"
                    else:
                        item.emoji = "🔊"
                elif item.custom_id == "music:loop":
                    if self.cog.loop_status.get(guild_id, False):
                        item.style = discord.ButtonStyle.green
                    else:
                        item.style = discord.ButtonStyle.grey
                item.disabled = False
        if current_message_info:
            try:
                old_channel = interaction.guild.get_channel(current_message_info['channel_id']) or await interaction.guild.fetch_channel(current_message_info['channel_id'])
                if old_channel:
                    old_message = await old_channel.fetch_message(current_message_info['message_id'])
                    await old_message.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            finally:
                self.cog.current_music_message_info.pop(guild_id, None)
        new_message = await interaction.channel.send(embed=new_embed, view=updated_view)
        self.cog.current_music_message_info[guild_id] = {
            'message_id': new_message.id,
            'channel_id': new_message.channel.id
        }
        if vc and vc.is_playing():
            await new_message.add_reaction('👍')
            await new_message.add_reaction('👎')

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary, custom_id="music:play_pause", row=0)
    async def play_pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            await interaction.followup.send("⏸️ Lagu dijeda.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.followup.send("▶️ Lanjut lagu.", ephemeral=True)
        else:
            await interaction.followup.send("Tidak ada lagu yang sedang diputar/dijeda.", ephemeral=True)
        await self._update_music_message(interaction)

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, custom_id="music:skip", row=0)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            guild_id = interaction.guild.id
            queue = self.cog.get_queue(guild_id)
            if queue:
                queue.pop(0)
            vc.stop()
            await interaction.followup.send("⏭️ Skip lagu.", ephemeral=True)
        else:
            await interaction.followup.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        
    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music:stop", row=0)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        vc = interaction.guild.voice_client
        if vc:
            if vc.is_playing() or vc.is_paused():
                vc.stop()
            await vc.disconnect()
            self.cog.queues[interaction.guild.id] = []
            self.cog.loop_status[interaction.guild.id] = False
            self.cog.is_muted[interaction.guild.id] = False
            self.cog.old_volume.pop(interaction.guild.id, None)
            self.cog.now_playing_info.pop(interaction.guild.id, None)
            if interaction.guild.id in self.cog.active_tasks:
                self.cog.active_tasks[interaction.guild.id].cancel()
                del self.cog.active_tasks[interaction.guild.id]
            if interaction.guild.id in self.cog.current_music_message_info:
                old_message_info = self.cog.current_music_message_info[interaction.guild.id]
                try:
                    old_channel = interaction.guild.get_channel(old_message_info['channel_id']) or await interaction.guild.fetch_channel(old_message_info['channel_id'])
                    if old_channel:
                        old_message = await old_channel.fetch_message(old_message_info['message_id'])
                        await old_message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
                finally:
                    del self.cog.current_music_message_info[interaction.guild.id]
            await interaction.followup.send("⏹️ Stop dan keluar dari voice.", ephemeral=True)
            
    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.grey, custom_id="music:queue", row=1)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.cog.get_queue(interaction.guild.id)
        if queue:
            display_queue = queue[:10]
            display_queue_titles = await asyncio.gather(
                *[self.cog.get_song_info_from_url(q) for q in display_queue]
            )
            msg = "\n".join([f"{i+1}. {q['title']}" for i, q in enumerate(display_queue_titles)])
            embed = discord.Embed(
                title="🎶 Antrean Lagu",
                description=f"```{msg}```",
                color=discord.Color.gold()
            )
            if len(queue) > 15:
                embed.set_footer(text=f"Dan {len(queue) - 15} lagu lainnya...")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("Antrean kosong.", ephemeral=True)
            
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.grey, custom_id="music:loop", row=1)
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        if guild_id not in self.cog.loop_status:
            self.cog.loop_status[guild_id] = False
        self.cog.loop_status[guild_id] = not self.cog.loop_status[guild_id]
        if self.cog.loop_status[guild_id]:
            await interaction.followup.send("🔁 Mode Loop **ON** (lagu saat ini akan diulang).", ephemeral=True)
        else:
            await interaction.followup.send("🔁 Mode Loop **OFF**.", ephemeral=True)
        await self._update_music_message(interaction)

    @discord.ui.button(emoji="📖", style=discord.ButtonStyle.blurple, custom_id="music:lyrics", row=1)
    async def lyrics_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.genius:
            await interaction.response.send_message("Fitur lirik masih beta dan akan segera dirilis nantinya.", ephemeral=True)
            return
        if not interaction.guild.id in self.cog.now_playing_info:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar. Harap gunakan `!rtmlyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.cog._send_lyrics(interaction_or_ctx=interaction, song_name_override=None)

    @discord.ui.button(emoji="➕", style=discord.ButtonStyle.secondary, custom_id="music:volume_up", row=2)
    async def volume_up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        vc = interaction.guild.voice_client
        guild_id = interaction.guild.id
        if vc and vc.source:
            current_volume = vc.source.volume
            new_volume = min(current_volume + 0.1, 1.0)
            vc.source.volume = new_volume
            self.cog.is_muted[guild_id] = False
            await interaction.response.send_message(f"Volume diatur ke: {int(new_volume * 100)}%", ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        await self._update_music_message(interaction)

    @discord.ui.button(emoji="➖", style=discord.ButtonStyle.secondary, custom_id="music:volume_down", row=2)
    async def volume_down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        vc = interaction.guild.voice_client
        guild_id = interaction.guild.id
        if vc and vc.source:
            current_volume = vc.source.volume
            new_volume = max(current_volume - 0.1, 0.0)
            vc.source.volume = new_volume
            if new_volume > 0.0:
                self.cog.is_muted[guild_id] = False
            else:
                self.cog.is_muted[guild_id] = True
            await interaction.response.send_message(f"Volume diatur ke: {int(new_volume * 100)}%", ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        await self._update_music_message(interaction)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="music:mute_unmute", row=2)
    async def mute_unmute_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        vc = interaction.guild.voice_client
        guild_id = interaction.guild.id
        if vc and vc.source:
            if not self.cog.is_muted.get(guild_id, False):
                self.cog.old_volume[guild_id] = vc.source.volume
                vc.source.volume = 0.0
                self.cog.is_muted[guild_id] = True
                await interaction.followup.send("🔇 Volume dimatikan.", ephemeral=True)
            else:
                vc.source.volume = self.cog.old_volume.get(guild_id, 0.8)
                self.cog.is_muted[guild_id] = False
                await interaction.followup.send("🔊 Volume dinyalakan.", ephemeral=True)
            await self._update_music_message(interaction)
        else:
            await interaction.followup.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.grey, custom_id="music:shuffle", row=1)
    async def shuffle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        guild_id = interaction.guild.id
        queue = self.cog.get_queue(guild_id)
        if len(queue) > 1:
            random.shuffle(queue)
            await interaction.response.send_message("🔀 Antrean lagu diacak!", ephemeral=True)
        else:
            await interaction.response.send_message("Antrean terlalu pendek untuk diacak.", ephemeral=True)
        await self._update_music_message(interaction)

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="music:clear_queue", row=1)
    async def clear_queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        guild_id = interaction.guild.id
        queue = self.cog.get_queue(guild_id)
        if queue:
            self.cog.queues[guild_id] = []
            await interaction.response.send_message("🗑️ Antrean lagu telah dikosongkan!", ephemeral=True)
        else:
            await interaction.response.send_message("Antrean sudah kosong.", ephemeral=True)
        await self._update_music_message(interaction)

    @discord.ui.button(emoji="ℹ️", style=discord.ButtonStyle.blurple, custom_id="music:np_info", row=0)
    async def now_playing_info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        vc = interaction.guild.voice_client
        guild_id = interaction.guild.id
        if vc and vc.is_playing() and vc.source and guild_id in self.cog.now_playing_info:
            info = self.cog.now_playing_info[guild_id]
            source = vc.source
            embed = discord.Embed(
                title=f"🎶 Sedang Memutar: {info['title']}",
                description=f"Oleh: {info['artist']}\n[Link YouTube]({info['webpage_url']})",
                color=discord.Color.purple()
            )
            if source.thumbnail:
                embed.set_thumbnail(url=source.thumbnail)
            duration_str = "N/A"
            if source.duration:
                minutes, seconds = divmod(source.duration, 60)
                duration_str = f"{minutes:02}:{seconds:02}"
            embed.add_field(name="Durasi", value=duration_str, inline=True)
            queue = self.cog.get_queue(interaction.guild.id)
            embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)

class MusicAndLiveCog(commands.Cog, name="Jarkasih Music & Live"):
    def __init__(self, bot):
        self.bot = bot
        
        self.queues = {}
        self.loop_status = {}
        self.current_music_message_info = {}
        self.is_muted = {}
        self.old_volume = {}
        self.now_playing_info = {}
        self.listening_history = load_json_file(LISTENING_HISTORY_FILE)
        self.user_preferences = load_json_file(USER_PREFERENCES_FILE)
        self.weekly_stats = load_json_file(WEEKLY_STATS_FILE)

        GENIUS_API_TOKEN = os.getenv("GENIUS_API")
        self.genius = None
        if GENIUS_API_TOKEN:
            try:
                self.genius = Genius(GENIUS_API_TOKEN)
            except Exception:
                pass

        SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
        SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
        self.spotify = None
        if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
            try:
                self.spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
                    client_id=SPOTIFY_CLIENT_ID,
                    client_secret=SPOTIFY_CLIENT_SECRET
                ))
            except Exception:
                pass

        self.bot.add_view(MusicControlView(self))
        
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(self.send_weekly_summary, 'cron', day_of_week='mon', hour=9)
        self.scheduler.start()
        
        self.client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        self.active_tasks = {}
        self.default_persona = """
        Nama lu JARKASIH. Lu adalah AI Generalist Expert dan asisten bot RTM.
        GAYA BAHASA: Sarkas, logat Jakarta, sumbu pendek.
        
        ATURAN PENANGANAN CURHAT: Jika dari nada suara atau omongan user terdengar sedih, stres, depresi, atau putus asa, MATIKAN 100% SIFAT SARKAS LU! Berubahlah menjadi sosok psikolog atau sahabat yang sangat empati, penuh kehangatan, dan memvalidasi perasaannya secara lisan.
        
        [DATA HASIL BELAJAR MEMORI]: {learned_data}
        STATUS INTERAKSI KHUSUS SAAT INI: {interaction_status}
        """

        self.idle_check_task.start()

    def build_live_persona(self, user_id):
        learned = load_json_file('data/jarkasih_learned.json', {"summary": ""})
        auto_config = load_json_file('data/jarkasih_auto.json', {"obedient_users": {}, "sulking_users": {}})
        uid_str = str(user_id)
        interaction_status = "Kondisi Normal"
        if uid_str in auto_config.get("sulking_users", {}):
            interaction_status = "LU SEDANG NGAMBEK"
        elif uid_str in auto_config.get("obedient_users", {}):
            interaction_status = "USER INI MASTER LU"
        return self.default_persona.format(learned_data=learned.get("summary", ""), interaction_status=interaction_status)

    async def _playback_task(self, vc, queue):
        while True:
            file_path = await queue.get()
            if file_path is None:
                break
            try:
                source = discord.FFmpegPCMAudio(file_path, options="-f s16le -ar 24000 -ac 1")
                vc.play(source, after=lambda e, f=file_path: os.remove(f) if os.path.exists(f) else None)
                while vc.is_playing():
                    await asyncio.sleep(0.1)
            except Exception:
                pass

    async def _send_audio_task(self, session, input_queue):
        buffer = bytearray()
        while True:
            try:
                pcm_data = await input_queue.get()
                if pcm_data is None:
                    break
                buffer.extend(pcm_data)
                
                while not input_queue.empty():
                    extra_data = input_queue.get_nowait()
                    if extra_data is None:
                        return
                    buffer.extend(extra_data)
                
                if len(buffer) > 0:
                    await session.send(input={"mime_type": "audio/pcm;rate=16000", "data": bytes(buffer)})
                    buffer.clear()
            except Exception:
                pass

    async def _run_session(self, ctx, vc, session):
        input_queue = asyncio.Queue()
        vc.listen(GeminiReceiverSink(input_queue, self.bot))
        
        send_task = asyncio.create_task(self._send_audio_task(session, input_queue))
        playback_queue = asyncio.Queue()
        playback_task = asyncio.create_task(self._playback_task(vc, playback_queue))
        temp_audio_buffer = bytearray()

        try:
            async for response in session.receive():
                if getattr(response, "data", None) is not None:
                    temp_audio_buffer.extend(response.data)

                server_content = getattr(response, "server_content", None)
                if server_content is not None:
                    if getattr(server_content, "interrupted", False):
                        if vc.is_playing():
                            vc.stop()
                        while not playback_queue.empty():
                            try:
                                old_file = playback_queue.get_nowait()
                                if old_file and os.path.exists(old_file):
                                    os.remove(old_file)
                            except Exception:
                                pass
                        temp_audio_buffer.clear()

                    if getattr(server_content, "turn_complete", False):
                        if len(temp_audio_buffer) > 0:
                            unique_id = uuid.uuid4().hex
                            file_path = f"temp_gemini_{ctx.guild.id}_{unique_id}.pcm"
                            with open(file_path, "wb") as f:
                                f.write(temp_audio_buffer)
                            temp_audio_buffer.clear()
                            await playback_queue.put(file_path)
        finally:
            input_queue.put_nowait(None)
            await playback_queue.put(None)
            send_task.cancel()
            playback_task.cancel()


    async def live_session_manager(self, ctx, vc, persona_text):
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(parts=[types.Part.from_text(text=persona_text)])
        )
        try:
            async with self.client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as session:
                await self._run_session(ctx, vc, session)
        except Exception:
            try:
                async with self.client.aio.live.connect(model="gemini-2.5-flash-native-audio-preview-12-2025", config=config) as session:
                    await self._run_session(ctx, vc, session)
            except Exception:
                pass
        finally:
            if vc and vc.is_listening():
                vc.stop_listening()

    def cog_unload(self):
        self.idle_check_task.cancel()
        self.scheduler.shutdown()
        for task in self.active_tasks.values():
            task.cancel()

    @tasks.loop(seconds=5)
    async def idle_check_task(self):
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if vc and vc.is_connected():
                human_members = [
                    member for member in vc.channel.members
                    if not member.bot
                ]
                if len(human_members) == 0:
                    if vc.is_playing() or vc.is_paused():
                        vc.stop()
                    if guild.id in self.active_tasks:
                        self.active_tasks[guild.id].cancel()
                        del self.active_tasks[guild.id]
                    await vc.disconnect()
                    self.queues.pop(guild.id, None)
                    self.loop_status.pop(guild.id, None)
                    self.is_muted.pop(guild.id, None)
                    self.old_volume.pop(guild.id, None)
                    self.now_playing_info.pop(guild.id, None)
                    if guild.id in self.current_music_message_info:
                        old_message_info = self.current_music_message_info[guild.id]
                        try:
                            old_channel = guild.get_channel(old_message_info['channel_id']) or await guild.fetch_channel(old_message_info['channel_id'])
                            if old_channel:
                                old_message = await old_channel.fetch_message(old_message_info['message_id'])
                                await old_message.delete()
                        except (discord.NotFound, discord.HTTPException):
                            pass
                        finally:
                            del self.current_music_message_info[guild.id]

    @idle_check_task.before_loop
    async def before_idle_check_task(self):
        await self.bot.wait_until_ready()

    def get_queue(self, guild_id):
        return self.queues.setdefault(guild_id, [])

    def add_song_to_history(self, user_id, song_info):
        user_id_str = str(user_id)
        if user_id_str not in self.listening_history:
            self.listening_history[user_id_str] = []
        if not isinstance(self.listening_history[user_id_str], list):
             self.listening_history[user_id_str] = []
        song_info_copy = song_info.copy()
        song_info_copy['timestamp'] = datetime.now().isoformat()
        self.listening_history[user_id_str].insert(0, song_info_copy)
        if len(self.listening_history[user_id_str]) > 50:
            self.listening_history[user_id_str] = self.listening_history[user_id_str][:50]
        save_json_file(LISTENING_HISTORY_FILE, self.listening_history)

    def add_liked_song(self, user_id, song_info):
        user_id_str = str(user_id)
        if user_id_str not in self.user_preferences or not isinstance(self.user_preferences[user_id_str], dict):
            self.user_preferences[user_id_str] = {'liked_songs': [], 'disliked_songs': []}
        if not isinstance(self.user_preferences[user_id_str].get('disliked_songs'), list):
             self.user_preferences[user_id_str]['disliked_songs'] = []
        if not isinstance(self.user_preferences[user_id_str].get('liked_songs'), list):
             self.user_preferences[user_id_str]['liked_songs'] = []
        self.user_preferences[user_id_str]['disliked_songs'] = [
            s for s in self.user_preferences[user_id_str]['disliked_songs']
            if s['webpage_url'] != song_info['webpage_url']
        ]
        if not any(s['webpage_url'] == song_info['webpage_url'] for s in self.user_preferences[user_id_str]['liked_songs']):
            self.user_preferences[user_id_str]['liked_songs'].insert(0, song_info)
            if len(self.user_preferences[user_id_str]['liked_songs']) > 25:
                self.user_preferences[user_id_str]['liked_songs'] = self.user_preferences[user_id_str]['liked_songs'][:25]
        save_json_file(USER_PREFERENCES_FILE, self.user_preferences)

    def add_disliked_song(self, user_id, song_info):
        user_id_str = str(user_id)
        if user_id_str not in self.user_preferences or not isinstance(self.user_preferences[user_id_str], dict):
            self.user_preferences[user_id_str] = {'liked_songs': [], 'disliked_songs': []}
        if not isinstance(self.user_preferences[user_id_str].get('disliked_songs'), list):
             self.user_preferences[user_id_str]['disliked_songs'] = []
        if not isinstance(self.user_preferences[user_id_str].get('liked_songs'), list):
             self.user_preferences[user_id_str]['liked_songs'] = []
        self.user_preferences[user_id_str]['liked_songs'] = [
            s for s in self.user_preferences[user_id_str]['liked_songs']
            if s['webpage_url'] != song_info['webpage_url']
        ]
        if not any(s['webpage_url'] == song_info['webpage_url'] for s in self.user_preferences[user_id_str]['disliked_songs']):
            self.user_preferences[user_id_str]['disliked_songs'].insert(0, song_info)
            if len(self.user_preferences[user_id_str]['disliked_songs']) > 100:
                self.user_preferences[user_id_str]['disliked_songs'] = self.user_preferences[user_id_str]['disliked_songs'][:100]
        save_json_file(USER_PREFERENCES_FILE, self.user_preferences)

    async def get_song_info_from_url(self, url):
        try:
            info = await asyncio.to_thread(lambda: ytdl.extract_info(url, download=False, process=False))
            title = info.get('title', url)
            artist = info.get('artist') or info.get('uploader', 'Unknown Artist')
            if "Vevo" in artist or "Official" in artist or "Topic" in artist or "Channel" in artist:
                if ' - ' in title:
                    parts = title.split(' - ')
                    if len(parts) > 1:
                        potential_artist = parts[-1].strip()
                        if len(potential_artist) < 30 and "channel" not in potential_artist.lower() and "topic" not in potential_artist.lower():
                            artist = potential_artist
            return {'title': title, 'artist': artist, 'webpage_url': info.get('webpage_url', url)}
        except Exception:
            return {'title': url, 'artist': 'Unknown Artist', 'webpage_url': url}

    async def _send_lyrics(self, interaction_or_ctx, song_name_override=None):
        if not self.genius:
            if isinstance(interaction_or_ctx, discord.Interaction):
                if not interaction_or_ctx.response.is_done():
                    await interaction_or_ctx.response.send_message("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
                else:
                    await interaction_or_ctx.followup.send("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
            else:
                await interaction_or_ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.")
            return
        guild_id = interaction_or_ctx.guild.id if isinstance(interaction_or_ctx, discord.Interaction) else interaction_or_ctx.guild.id
        song_title_for_lyrics = None
        song_artist_for_lyrics = None
        if song_name_override:
            if ' - ' in song_name_override:
                parts = song_name_override.split(' - ', 1)
                song_title_for_lyrics = parts[0].strip()
                song_artist_for_lyrics = parts[1].strip()
            else:
                song_title_for_lyrics = song_name_override
                song_artist_for_lyrics = None
        elif guild_id in self.now_playing_info:
            info = self.now_playing_info[guild_id]
            song_title_for_lyrics = info.get('title')
            song_artist_for_lyrics = info.get('artist')
        if not song_title_for_lyrics:
            if isinstance(interaction_or_ctx, discord.Interaction):
                if not interaction_or_ctx.response.is_done():
                    await interaction_or_ctx.response.send_message("Tidak ada lagu yang sedang diputar atau nama lagu tidak diberikan. Harap gunakan `!rtmlyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
                else:
                    await interaction_or_ctx.followup.send("Tidak ada lagu yang sedang diputar atau nama lagu tidak diberikan. Harap gunakan `!rtmlyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
            else:
                await interaction_or_ctx.send("Tidak ada lagu yang sedang diputar atau nama lagu tidak diberikan. Harap gunakan `!rtmlyrics <nama lagu>` untuk mencari lirik.")
            return
        try:
            song = None
            if song_artist_for_lyrics and "Unknown Artist" not in song_artist_for_lyrics and "channel" not in song_artist_for_lyrics.lower() and "vevo" not in song_artist_for_lyrics.lower() and "topic" not in song_artist_for_lyrics.lower():
                song = await asyncio.to_thread(self.genius.search_song, song_title_for_lyrics, song_artist_for_lyrics)
                if not song:
                    song = await asyncio.to_thread(self.genius.search_song, song_title_for_lyrics)
            else:
                song = await asyncio.to_thread(self.genius.search_song, song_title_for_lyrics)
            if song:
                embed = discord.Embed(
                    title=f"Lirik: {song.title} - {song.artist}",
                    color=discord.Color.dark_teal(),
                    url=song.url
                )
                if song.song_art_image_url:
                    embed.set_thumbnail(url=song.song_art_image_url)
                lyrics_parts = [song.lyrics[i:i+1900] for i in range(0, len(song.lyrics), 1900)]
                embed.description = lyrics_parts[0]
                if isinstance(interaction_or_ctx, discord.Interaction):
                    if interaction_or_ctx.response.is_done():
                        message_sent = await interaction_or_ctx.followup.send(embed=embed)
                    else:
                        message_sent = await interaction_or_ctx.response.send_message(embed=embed)
                else:
                    message_sent = await interaction_or_ctx.send(embed=embed)
                for part in lyrics_parts[1:]:
                    if isinstance(interaction_or_ctx, discord.Interaction):
                        await interaction_or_ctx.followup.send(part)
                    else:
                        await message_sent.channel.send(part)
            else:
                if isinstance(interaction_or_ctx, discord.Interaction):
                    if interaction_or_ctx.response.is_done():
                        await interaction_or_ctx.followup.send("Lirik tidak ditemukan untuk lagu tersebut.", ephemeral=True)
                    else:
                        await interaction_or_ctx.response.send_message("Lirik tidak ditemukan untuk lagu tersebut.", ephemeral=True)
                else:
                    await interaction_or_ctx.send("Lirik tidak ditemukan untuk lagu tersebut.")
        except Exception as e:
            error_message = f"Gagal mengambil lirik: {e}"
            if isinstance(interaction_or_ctx, discord.Interaction):
                if interaction_or_ctx.response.is_done():
                    await interaction_or_ctx.followup.send(error_message, ephemeral=True)
                else:
                    await interaction_or_ctx.response.send_message(error_message, ephemeral=True)
            else:
                await interaction_or_ctx.send(error_message)

    async def play_next(self, ctx):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        if self.loop_status.get(guild_id, False) and ctx.voice_client and ctx.voice_client.source:
            current_song_url = ctx.voice_client.source.data.get('webpage_url')
            if current_song_url:
                queue.insert(0, current_song_url)
        if not queue:
            vc = ctx.voice_client
            if vc and len([member for member in vc.channel.members if not member.bot]) > 0:
                await self.refill_queue_for_random(ctx)
                queue = self.get_queue(guild_id)
        if not queue:
            vc = ctx.voice_client
            if vc and vc.is_connected():
                if guild_id in self.active_tasks:
                    await ctx.guild.change_voice_state(channel=vc.channel, self_deaf=False)
                else:
                    await vc.disconnect()
            if guild_id in self.current_music_message_info:
                message_info = self.current_music_message_info.pop(guild_id)
                try:
                    channel = ctx.guild.get_channel(message_info['channel_id']) or await ctx.guild.fetch_channel(message_info['channel_id'])
                    if channel:
                        old_message = await channel.fetch_message(message_info['message_id'])
                        await old_message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
            await ctx.send("Antrean kosong.", ephemeral=True)
            return
            
        if ctx.voice_client and not ctx.guild.me.voice.deaf:
            await ctx.guild.change_voice_state(channel=ctx.voice_client.channel, self_deaf=True)
            
        url = queue.pop(0)
        try:
            song_info_from_ytdl = await self.get_song_info_from_url(url)
            self.add_song_to_history(ctx.author.id, song_info_from_ytdl)
            song_info_from_ytdl['requester'] = ctx.author.mention
            source = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                ctx.voice_client.stop()
            ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop))
            self.now_playing_info[guild_id] = song_info_from_ytdl
            embed = discord.Embed(
                title="🎶 Sedang Memutar",
                description=f"**[{self.now_playing_info[guild_id]['title']}]({self.now_playing_info[guild_id]['webpage_url']})**",
                color=discord.Color.purple()
            )
            if source.thumbnail:
                embed.set_thumbnail(url=source.thumbnail)
            duration_str = "N/A"
            if source.duration:
                minutes, seconds = divmod(source.duration, 60)
                duration_str = f"{minutes:02}:{seconds:02}"
            embed.add_field(name="Durasi", value=duration_str, inline=True)
            embed.add_field(name="Diminta oleh", value=ctx.author.mention, inline=True)
            embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")
            view = MusicControlView(self)
            if guild_id in self.current_music_message_info:
                message_info = self.current_music_message_info.pop(guild_id)
                try:
                    channel = ctx.guild.get_channel(message_info['channel_id']) or await ctx.guild.fetch_channel(message_info['channel_id'])
                    if channel:
                        old_message = await channel.fetch_message(message_info['message_id'])
                        await old_message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
            message_sent = await ctx.send(embed=embed, view=view)
            self.current_music_message_info[guild_id] = {'message_id': message_sent.id, 'channel_id': message_sent.channel.id}
            await message_sent.add_reaction('👍')
            await message_sent.add_reaction('👎')
        except Exception as e:
            await ctx.send(f'Gagal memutar lagu: {e}', ephemeral=True)
            if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
                ctx.voice_client.stop()
            return

    async def _after_play_handler(self, ctx, error):
        guild_id = ctx.guild.id
        if error:
            target_channel = None
            if guild_id in self.current_music_message_info:
                channel_id = self.current_music_message_info[guild_id]['channel_id']
                try:
                    target_channel = ctx.guild.get_channel(channel_id) or await ctx.guild.fetch_channel(channel_id)
                except discord.NotFound:
                    pass
                if target_channel:
                    await target_channel.send(f"Terjadi error saat memutar: {error}")
                else:
                    await ctx.send(f"Terjadi error saat memutar: {error}")
        await asyncio.sleep(1)
        if ctx.voice_client and ctx.voice_client.is_connected():
            await self.play_next(ctx)
        else:
            self.queues.pop(guild_id, None)
            self.loop_status.pop(guild_id, None)
            self.is_muted.pop(guild_id, None)
            self.old_volume.pop(guild_id, None)
            self.now_playing_info.pop(guild_id, None)
            if guild_id in self.current_music_message_info:
                old_message_info = self.current_music_message_info[guild_id]
                try:
                    old_channel = ctx.guild.get_channel(old_message_info['channel_id']) or await ctx.guild.fetch_channel(old_message_info['channel_id'])
                    if old_channel:
                        old_message = await old_channel.fetch_message(old_message_info['message_id'])
                        await old_message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
                finally:
                    self.current_music_message_info.pop(guild_id, None)

    async def refill_queue_for_random(self, ctx, num_songs=10):
        user_id_str = str(ctx.author.id)
        if not isinstance(self.user_preferences, dict):
            self.user_preferences = {}
            save_json_file(USER_PREFERENCES_FILE, self.user_preferences)
        user_preferences = self.user_preferences.get(user_id_str, {'liked_songs': [], 'disliked_songs': []})
        disliked_urls = {s.get('webpage_url') for s in user_preferences.get('disliked_songs', [])}
        new_urls = []
        liked_songs = user_preferences.get('liked_songs', [])
        if liked_songs and isinstance(liked_songs, list):
            random.shuffle(liked_songs)
            liked_urls = [s['webpage_url'] for s in liked_songs if s['webpage_url'] not in disliked_urls]
            new_urls.extend(liked_urls[:num_songs])
        if len(new_urls) < num_songs:
            user_history = self.listening_history.get(user_id_str, [])
            if user_history and isinstance(user_history, list):
                filtered_history = [s['webpage_url'] for s in user_history if s['webpage_url'] not in disliked_urls]
                if filtered_history:
                    random.shuffle(filtered_history)
                    urls_from_history = filtered_history[:num_songs - len(new_urls)]
                    new_urls.extend(urls_from_history)
        if len(new_urls) < num_songs:
            search_query = "trending music"
            try:
                info = await asyncio.to_thread(lambda: ytdl.extract_info(search_query, download=False, process=True))
                if 'entries' in info and isinstance(info.get('entries'), list):
                    filtered_entries = [entry for entry in info['entries'] if entry.get('webpage_url') not in disliked_urls]
                    if filtered_entries:
                        random.shuffle(filtered_entries)
                        urls_from_search = [entry['webpage_url'] for entry in filtered_entries[:num_songs - len(new_urls)]]
                        new_urls.extend(urls_from_search)
            except Exception:
                pass
        self.get_queue(ctx.guild.id).extend(new_urls)

    async def _update_music_message_from_ctx(self, ctx):
        guild_id = ctx.guild.id
        current_message_info = self.current_music_message_info.get(guild_id)
        if not current_message_info:
            return
        vc = ctx.voice_client
        queue = self.get_queue(guild_id)
        if vc and vc.is_playing() and vc.source and guild_id in self.now_playing_info:
            info = self.now_playing_info[guild_id]
            source = vc.source
            embed_to_send = discord.Embed(
                title="🎶 Sedang Memutar",
                description=f"**[{info['title']}]({info['webpage_url']})**",
                color=discord.Color.purple()
            )
            if source.thumbnail:
                embed_to_send.set_thumbnail(url=source.thumbnail)
            duration_str = "N/A"
            if source.duration:
                minutes, seconds = divmod(source.duration, 60)
                duration_str = f"{minutes:02}:{seconds:02}"
            embed_to_send.add_field(name="Durasi", value=duration_str, inline=True)
            embed_to_send.add_field(name="Diminta oleh", value=info.get('requester', 'N/A'), inline=True)
            embed_to_send.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")
        else:
            embed_to_send = discord.Embed(title="Musik Bot", description="Status musik...", color=discord.Color.light_grey())
        updated_view = MusicControlView(self)
        if not vc:
            for item in updated_view.children:
                item.disabled = True
        else:
            for item in updated_view.children:
                if item.custom_id == "music:play_pause":
                    if vc.is_playing():
                        item.emoji = "⏸️"
                        item.style = discord.ButtonStyle.green
                    elif vc.is_paused():
                        item.emoji = "▶️"
                        item.style = discord.ButtonStyle.primary
                elif item.custom_id == "music:mute_unmute":
                    if self.is_muted.get(guild_id, False):
                        item.emoji = "🔇"
                    else:
                        item.emoji = "🔊"
                elif item.custom_id == "music:loop":
                    if self.loop_status.get(guild_id, False):
                        item.style = discord.ButtonStyle.green
                    else:
                        item.style = discord.ButtonStyle.grey
                item.disabled = False
        if guild_id in self.current_music_message_info:
            message_info = self.current_music_message_info.pop(guild_id)
            try:
                channel = ctx.guild.get_channel(message_info['channel_id']) or await ctx.guild.fetch_channel(message_info['channel_id'])
                if channel:
                    old_message = await channel.fetch_message(message_info['message_id'])
                    await old_message.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
        new_message = await ctx.send(embed=embed_to_send, view=updated_view)
        self.current_music_message_info[guild_id] = {
            'message_id': new_message.id,
            'channel_id': new_message.channel.id
        }
        if vc and vc.is_playing():
            await new_message.add_reaction('👍')
            await new_message.add_reaction('👎')

    async def send_weekly_summary(self):
        today = datetime.now()
        last_week = today - timedelta(days=7)
        for user_id_str, history in self.listening_history.items():
            user_id = int(user_id_str)
            user = self.bot.get_user(user_id)
            if not user:
                continue

            songs_in_week = [s for s in history if 'timestamp' in s and datetime.fromisoformat(s.get('timestamp')) > last_week]
            if not songs_in_week:
                continue
            
            artist_counts = {}
            for song in songs_in_week:
                artist = song.get('artist', 'Unknown Artist')
                artist_counts[artist] = artist_counts.get(artist, 0) + 1
            
            most_played_artist = max(artist_counts, key=artist_counts.get) if artist_counts else 'Tidak diketahui'
            total_songs = len(songs_in_week)
            
            embed = discord.Embed(
                title=f"🎶 Ringkasan Musik Anda Minggu Ini!",
                description=f"Halo, {user.display_name}! Berikut adalah ringkasan musik Anda dari {last_week.strftime('%d %b')} hingga {today.strftime('%d %b')}.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Jumlah Lagu Didengarkan", value=f"{total_songs} lagu", inline=False)
            embed.add_field(name="Artis Terpopuler", value=most_played_artist, inline=False)
            
            user_prefs = self.user_preferences.get(user_id_str, {})
            liked_songs = user_prefs.get('liked_songs', [])
            if liked_songs:
                rec_song = random.choice(liked_songs)
                embed.add_field(name="Rekomendasi Minggu Ini", value=f"Karena Anda menyukai **{rec_song['title']}**, coba cari lagu lain dari **{rec_song['artist']}**!", inline=False)
            
            try:
                await user.send(embed=embed)
            except discord.Forbidden:
                pass
                
    @commands.command(name="aijoin")
    async def ai_live_join(self, ctx):
        if not ctx.author.voice:
            await ctx.send("Masuk voice dulu bos!")
            return

        channel = ctx.author.voice.channel
        if ctx.voice_client:
            await ctx.voice_client.disconnect(force=True)
            await asyncio.sleep(1)

        try:
            vc = await channel.connect(cls=voice_recv.VoiceRecvClient, timeout=20.0, reconnect=False)
            await ctx.send("Gue udah standby. Sapa gue!")
        except Exception:
            return

        persona_text = self.build_live_persona(ctx.author.id)
        task = asyncio.create_task(self.live_session_manager(ctx, vc, persona_text))
        self.active_tasks[ctx.guild.id] = task

    @commands.command(name="aistop")
    async def ai_live_leave(self, ctx):
        if ctx.guild.id in self.active_tasks:
            self.active_tasks[ctx.guild.id].cancel()
            del self.active_tasks[ctx.guild.id]
        if ctx.voice_client:
            if hasattr(ctx.voice_client, 'is_listening') and ctx.voice_client.is_listening():
                ctx.voice_client.stop_listening()
            await ctx.voice_client.disconnect(force=True)
            await ctx.send("Gue cabut.")
    
    @commands.command(name="rtmjoin", aliases=["join", "j"])
    async def join(self, ctx):
        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                return await ctx.send("Bot sudah berada di voice channel lain. Harap keluarkan dulu.")
            return
        if ctx.author.voice:
            await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient, self_deaf=True)
            await ctx.send(f"Joined **{ctx.author.voice.channel.name}**")
        else:
            await ctx.send("Kamu harus berada di voice channel dulu.")

    @commands.command(name="rtmp", aliases=["p", "play"])
    async def play(self, ctx, *, query):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            if not ctx.voice_client:
                return await ctx.send("Gagal bergabung ke voice channel.")
        if ctx.voice_client and not ctx.guild.me.voice.deaf:
            await ctx.guild.change_voice_state(channel=ctx.voice_client.channel, self_deaf=True)
        await ctx.defer()
        urls = []
        is_spotify_request = False
        spotify_track_info = None
        if self.spotify and ("http" in query and ("open.spotify.com/track/" in query or "open.spotify.com/playlist/" in query or "open.spotify.com/album/" in query) or "spotify:" in query):
            is_spotify_request = True
            try:
                if "track" in query:
                    track = self.spotify.track(query)
                    spotify_track_info = {
                        'title': track['name'],
                        'artist': track['artists'][0]['name'],
                        'webpage_url': track['external_urls']['spotify'],
                        'requester': ctx.author.mention
                    }
                    urls.append(f"{track['name']} {track['artists'][0]['name']}")
                elif "playlist" in query:
                    results = self.spotify.playlist_tracks(query)
                    for item in results['items']:
                        track = item['track']
                        if track:
                            urls.append(f"{track['name']} {track['artists'][0]['name']}")
                elif "album" in query:
                    results = self.spotify.album_tracks(query)
                    for item in results['items']:
                        track = item
                        if track:
                            urls.append(f"{track['name']} {track['artists'][0]['name']}")
            except Exception as e:
                await ctx.send(f"Terjadi kesalahan saat memproses link Spotify: {e}", ephemeral=True)
                return
        if not is_spotify_request:
            urls.append(query)
        queue = self.get_queue(ctx.guild.id)
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused() and not queue:
            first_url = urls.pop(0)
            queue.extend(urls)
            try:
                source = await YTDLSource.from_url(first_url, loop=self.bot.loop, stream=True)
                ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop))
                if is_spotify_request and spotify_track_info:
                    self.now_playing_info[ctx.guild.id] = spotify_track_info
                else:
                    song_info_from_ytdl = await self.get_song_info_from_url(first_url)
                    self.now_playing_info[ctx.guild.id] = {
                        'title': song_info_from_ytdl['title'],
                        'artist': song_info_from_ytdl['artist'],
                        'webpage_url': song_info_from_ytdl['webpage_url'],
                        'requester': ctx.author.mention
                    }
                self.add_song_to_history(ctx.author.id, self.now_playing_info[ctx.guild.id])
                embed = discord.Embed(
                    title="🎶 Sedang Memutar",
                    description=f"**[{self.now_playing_info[ctx.guild.id]['title']}]({self.now_playing_info[ctx.guild.id]['webpage_url']})**",
                    color=discord.Color.purple()
                )
                if source.thumbnail:
                    embed.set_thumbnail(url=source.thumbnail)
                duration_str = "N/A"
                if source.duration:
                    minutes, seconds = divmod(source.duration, 60)
                    duration_str = f"{minutes:02}:{seconds:02}"
                embed.add_field(name="Durasi", value=duration_str, inline=True)
                embed.add_field(name="Diminta oleh", value=ctx.author.mention, inline=True)
                embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")
                view_instance = MusicControlView(self)
                if self.is_muted.get(ctx.guild.id, False):
                    for item in view_instance.children:
                        if item.custom_id == "music:mute_unmute":
                            item.emoji = "🔇"
                            break
                if ctx.guild.id in self.current_music_message_info:
                    message_info = self.current_music_message_info.pop(ctx.guild.id)
                    try:
                        old_channel = ctx.guild.get_channel(message_info['channel_id']) or await ctx.guild.fetch_channel(message_info['channel_id'])
                        if old_channel:
                            old_message = await old_channel.fetch_message(message_info['message_id'])
                            await old_message.delete()
                    except (discord.NotFound, discord.HTTPException):
                        pass
                message_sent = await ctx.send(embed=embed, view=view_instance)
                if message_sent:
                    self.current_music_message_info[ctx.guild.id] = {
                        'message_id': message_sent.id,
                        'channel_id': message_sent.channel.id
                    }
                    await message_sent.add_reaction('👍')
                    await message_sent.add_reaction('👎')
            except Exception as e:
                await ctx.send(f'Gagal memutar lagu: {e}', ephemeral=True)
                if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
                    ctx.voice_client.stop()
                return
        else:
            if is_spotify_request:
                await ctx.send(f"Ditambahkan ke antrian: **{len(urls)} lagu**.", ephemeral=True)
            else:
                song_info = await self.get_song_info_from_url(urls[0])
                await ctx.send(f"Ditambahkan ke antrean: **{song_info['title']}**.", ephemeral=True)
            queue.extend(urls)
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)

    @commands.command(name="rtmskip", aliases=["skip", "s"])
    async def skip_cmd(self, ctx):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            return await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        if queue:
            queue.pop(0)
        ctx.voice_client.stop()
        await ctx.send("⏭️ Skip lagu.", ephemeral=True)

    @commands.command(name="rtmpause", aliases=["pause"])
    async def pause_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Lagu dijeda.", ephemeral=True)
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)
        else:
            await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)

    @commands.command(name="rtmresume", aliases=["resume"])
    async def resume_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Lanjut lagu.", ephemeral=True)
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)
        else:
            await ctx.send("Tidak ada lagu yang dijeda.", ephemeral=True)

    @commands.command(name="rtmstop", aliases=["stop", "leave", "dc"])
    async def stop_cmd(self, ctx):
        if ctx.voice_client:
            if ctx.guild.id in self.current_music_message_info:
                old_message_info = self.current_music_message_info[ctx.guild.id]
                try:
                    target_channel = ctx.guild.get_channel(old_message_info['channel_id']) or await ctx.guild.fetch_channel(old_message_info['channel_id'])
                    if target_channel:
                        old_message = await target_channel.fetch_message(old_message_info['message_id'])
                        await old_message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
                finally:
                    del self.current_music_message_info[ctx.guild.id]
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                ctx.voice_client.stop()
            self.queues[ctx.guild.id] = []
            self.loop_status[ctx.guild.id] = False
            self.is_muted[ctx.guild.id] = False
            self.old_volume.pop(ctx.guild.id, None)
            self.now_playing_info.pop(ctx.guild.id, None)
            
            if ctx.guild.id in self.active_tasks:
                await ctx.guild.change_voice_state(channel=ctx.voice_client.channel, self_deaf=False)
            else:
                await ctx.voice_client.disconnect()
            await ctx.send("⏹️ Musik stop.", ephemeral=True)
        else:
            await ctx.send("Bot tidak ada di voice channel.", ephemeral=True)

    @commands.command(name="rtmqueue", aliases=["queue", "q"])
    async def queue_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            display_queue_titles = [await self.get_song_info_from_url(q) for q in queue[:15]]
            msg = "\n".join([f"{i+1}. {q['title']}" for i, q in enumerate(display_queue_titles)])
            embed = discord.Embed(
                title="🎶 Antrean Lagu",
                description=f"```{msg}```",
                color=discord.Color.gold()
            )
            if len(queue) > 15:
                embed.set_footer(text=f"Dan {len(queue) - 15} lagu lainnya...")
            await ctx.send(embed=embed, ephemeral=True)
        else:
            await ctx.send("Antrean kosong.", ephemeral=True)
            
    @commands.command(name="rtmloop", aliases=["loop", "l"])
    async def loop_cmd(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.loop_status:
            self.loop_status[guild_id] = False
        self.loop_status[guild_id] = not self.loop_status[guild_id]
        status_msg = "ON" if self.loop_status[guild_id] else "OFF"
        await ctx.send(f"🔁 Mode Loop **{status_msg}** (lagu saat ini akan diulang).", ephemeral=True)
        if ctx.guild.id in self.current_music_message_info:
            await self._update_music_message_from_ctx(ctx)

    @commands.command(name="rtmlyrics", aliases=["lyrics", "ly"])
    async def lyrics(self, ctx, *, song_name=None):
        if not self.genius:
            return await ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
        if song_name is None:
            if ctx.guild.id not in self.now_playing_info:
                return await ctx.send("Tentukan nama lagu atau putar lagu terlebih dahulu untuk mencari liriknya.", ephemeral=True)
        await ctx.defer(ephemeral=True)
        await self._send_lyrics(interaction_or_ctx=ctx, song_name_override=song_name)

    @commands.command(name="rtmvolume", aliases=["volume", "vol", "v"])
    async def volume_cmd(self, ctx, volume: int):
        if not ctx.voice_client or not ctx.voice_client.source:
            return await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        if not 0 <= volume <= 100:
            return await ctx.send("Volume harus antara 0 dan 100.", ephemeral=True)
        ctx.voice_client.source.volume = volume / 100
        guild_id = ctx.guild.id
        if volume > 0:
            self.is_muted[guild_id] = False
        else:
            self.is_muted[guild_id] = True
            self.old_volume[guild_id] = ctx.voice_client.source.volume
        await ctx.send(f"Volume diatur ke: {volume}%", ephemeral=True)
        if ctx.guild.id in self.current_music_message_info:
            await self._update_music_message_from_ctx(ctx)

    @commands.command(name="rtmshuffle", aliases=["shuffle", "sh"])
    async def shuffle_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if len(queue) > 1:
            random.shuffle(queue)
            await ctx.send("🔀 Antrean lagu diacak!", ephemeral=True)
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)
        else:
            await ctx.send("Antrean terlalu pendek untuk diacak.", ephemeral=True)

    @commands.command(name="rtmclear", aliases=["c"])
    async def clear_queue_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            self.queues[ctx.guild.id] = []
            await ctx.send("🗑️ Antrean lagu telah dikosongkan!", ephemeral=True)
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)
        else:
            await ctx.send("Antrean sudah kosong.", ephemeral=True)
    
    @commands.command(name="rtmprandom", aliases=["prandom", "pr"])
    async def personal_random(self, ctx, *urls):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            if not ctx.voice_client:
                return await ctx.send("Gagal bergabung ke voice channel.", ephemeral=True)
        if ctx.voice_client and not ctx.guild.me.voice.deaf:
            await ctx.guild.change_voice_state(channel=ctx.voice_client.channel, self_deaf=True)
        await ctx.defer()
        if not isinstance(self.user_preferences, dict):
            self.user_preferences = load_json_file(USER_PREFERENCES_FILE)
            if not isinstance(self.user_preferences, dict):
                self.user_preferences = {}
                save_json_file(USER_PREFERENCES_FILE, self.user_preferences)
        is_spotify_request = False
        if urls and self.spotify and ("open.spotify.com" in urls[0] or "spotify:" in urls[0]):
            is_spotify_request = True
            await ctx.send(f"🎧 Mengambil lagu dari {len(urls)} playlist/album Spotify...", ephemeral=True)
            search_queries = []
            for url in urls:
                try:
                    if "track" in url:
                        track = self.spotify.track(url)
                        search_queries.append(f"{track['name']} {track['artists'][0]['name']}")
                    elif "playlist" in url:
                        results = self.spotify.playlist_tracks(url)
                        for item in results['items']:
                            track = item['track']
                            if track:
                                search_queries.append(f"{track['name']} {track['artists'][0]['name']}")
                    elif "album" in url:
                        results = self.spotify.album_tracks(url)
                        for item in results['items']:
                            track = item
                            if track:
                                search_queries.append(f"{track['name']} {track['artists'][0]['name']}")
                except Exception:
                    continue
            new_urls = []
            for query in search_queries:
                try:
                    info = await asyncio.to_thread(lambda: ytdl.extract_info(query, download=False, process=True))
                    if 'entries' in info and isinstance(info.get('entries'), list):
                        new_urls.append(info['entries'][0]['webpage_url'])
                except Exception:
                    pass
            queue = self.get_queue(ctx.guild.id)
            queue.extend(new_urls)
            await ctx.send(f"🎧 Menambahkan {len(new_urls)} lagu dari Spotify ke antrean.", ephemeral=True)
            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                await self.play_next(ctx)
            else:
                await self._update_music_message_from_ctx(ctx)
            return
        await self.refill_queue_for_random(ctx, num_songs=10)
        queue = self.get_queue(ctx.guild.id)
        if not queue:
            return await ctx.send("❌ Tidak dapat menemukan lagu untuk dimainkan. Pastikan riwayat dan preferensi Anda tidak kosong, atau coba lagi nanti.", ephemeral=True)
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await ctx.send("🎧 Memulai mode acak pribadi. Menambahkan 10 lagu ke antrean.", ephemeral=True)
            await self.play_next(ctx)
        else:
            await ctx.send(f"🎧 Menambahkan 10 lagu acak ke antrean.", ephemeral=True)

    @commands.command(name="rtmpliked", aliases=["pliked", "pl"])
    async def play_liked_songs(self, ctx):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            if not ctx.voice_client:
                return await ctx.send("Gagal bergabung ke voice channel.", ephemeral=True)
        if ctx.voice_client and not ctx.guild.me.voice.deaf:
            await ctx.guild.change_voice_state(channel=ctx.voice_client.channel, self_deaf=True)
        user_id_str = str(ctx.author.id)
        if not isinstance(self.user_preferences, dict):
            self.user_preferences = load_json_file(USER_PREFERENCES_FILE)
            if not isinstance(self.user_preferences, dict):
                self.user_preferences = {}
                save_json_file(USER_PREFERENCES_FILE, self.user_preferences)
        user_preferences = self.user_preferences.get(user_id_str, {})
        liked_songs = user_preferences.get('liked_songs', [])
        if not isinstance(liked_songs, list) or not liked_songs:
            return await ctx.send("❌ Anda belum memiliki lagu yang disukai.", ephemeral=True)
        await ctx.defer()
        liked_urls = [song['webpage_url'] for song in liked_songs]
        random.shuffle(liked_urls)
        queue = self.get_queue(ctx.guild.id)
        self.queues[ctx.guild.id] = []
        self.queues[ctx.guild.id].extend(liked_urls)
        await ctx.send(f"▶️ Memulai playlist lagu kesukaan Anda dengan {len(liked_urls)} lagu.", ephemeral=True)
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await self.play_next(ctx)
        else:
            await self._update_music_message_from_ctx(ctx)
            
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        guild_id = reaction.message.guild.id
        current_message_info = self.current_music_message_info.get(guild_id)
        if not current_message_info or reaction.message.id != current_message_info['message_id']:
            return
        now_playing_info = self.now_playing_info.get(guild_id)
        if not now_playing_info:
            return
        if str(reaction.emoji) == '👍':
            self.add_liked_song(user.id, now_playing_info)
        elif str(reaction.emoji) == '👎':
            self.add_disliked_song(user.id, now_playing_info)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if ctx.cog != self:
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Argumen tidak lengkap. Contoh penggunaan: `!{ctx.command.name} {ctx.command.signature}`", ephemeral=True)
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Argumen tidak valid. Pastikan kamu menyebutkan user yang benar atau angka yang valid.", ephemeral=True)
        elif isinstance(error, discord.Forbidden):
            await ctx.send("❌ Bot tidak memiliki izin untuk melakukan tindakan ini.", ephemeral=True)
        elif isinstance(error, commands.CommandInvokeError):
            original_error = error.original
            await ctx.send(f"❌ Terjadi kesalahan saat menjalankan perintah: {original_error}", ephemeral=True)
        else:
            await ctx.send(f"❌ Terjadi kesalahan yang tidak terduga: {error}", ephemeral=True)

async def setup(bot):
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    os.makedirs('reswan/data', exist_ok=True)
    donation_file_path = 'reswan/data/donation_buttons.json'
    if not os.path.exists(donation_file_path) or os.stat(donation_file_path).st_size == 0:
        default_data = [
            {
                "label": "Dukung via Bagi-Bagi!",
                "url": "https://bagibagi.co/Rh7155"
            },
            {
                "label": "Donasi via Saweria!",
                "url": "https://saweria.co/RH7155"
            },
            {
                "label": "Donasi via Sosiabuzz",
                "url": "https://sociabuzz.com/abogoboga7155/tribe"
            }
        ]
        with open(donation_file_path, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, indent=4)
    await bot.add_cog(MusicAndLiveCog(bot))
