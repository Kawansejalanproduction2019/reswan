import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os
import functools
from discord import FFmpegPCMAudio
from discord.utils import get
from lyricsgenius import Genius
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import logging
import json
import random
from datetime import datetime, timedelta

# Konfigurasi logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- FILE DATA UNTUK MELACAK CHANNEL SEMENTARA (Persisten antar restart bot) ---
TEMP_CHANNELS_FILE = 'data/temp_voice_channels.json'

def load_temp_channels():
    if not os.path.exists('data'):
        os.makedirs('data')
    if not os.path.exists(TEMP_CHANNELS_FILE):
        with open(TEMP_CHANNELS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=4)
        return {}
    try:
        with open(TEMP_CHANNELS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            cleaned_data = {}
            for ch_id, info in data.items():
                if "owner_id" in info:
                    info["owner_id"] = str(info["owner_id"])
                if "guild_id" in info:
                    info["guild_id"] = str(info["guild_id"])
                cleaned_data[str(ch_id)] = info
            return cleaned_data
    except json.JSONDecodeError as e:
        log.error(f"Failed to load {TEMP_CHANNELS_FILE}: {e}. File might be corrupted. Attempting to reset it.")
        with open(TEMP_CHANNELS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=4)
        return {}
    except Exception as e:
        log.error(f"An unexpected error occurred while loading {TEMP_CHANNELS_FILE}: {e}", exc_info=True)
        with open(TEMP_CHANNELS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=4)
        return {}

def save_temp_channels(data):
    os.makedirs('data', exist_ok=True)
    data_to_save = {str(k): v for k, v in data.items()}
    with open(TEMP_CHANNELS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data_to_save, f, indent=4)

# --- Updated YTDL Options for Opus and FFMPEG Options for Stability ---
ytdl_opts = {
    'format': 'bestaudio[ext=opus]/bestaudio[ext=m4a]/bestaudio/best', # Prioritaskan opus, lalu m4a
    'cookiefile': 'cookies.txt',
    'quiet': True,
    'default_search': 'ytsearch',
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'noplaylist': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus', # Coba opus sebagai preferred codec
        'preferredquality': '192',
    }],
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    # Menyesuaikan bufsize ke 1MB (1024K) yang lebih standar, dan menambahkan fflags/flags
    'options': '-vn -b:a 192k -bufsize 1024K -probesize 10M -analyzeduration 10M -fflags +discardcorrupt -flags +global_header'
}

ytdl = yt_dlp.YoutubeDL(ytdl_opts)

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

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

class MusicControlView(discord.ui.View):
    def __init__(self, cog_instance, original_message_info=None):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.original_message_info = original_message_info
        
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
        except FileNotFoundError:
            logging.error("Donation buttons file not found: reswan/data/donation_buttons.json")
        except json.JSONDecodeError:
            logging.error("Error decoding donation_buttons.json. Check JSON format.")
        except Exception as e:
            logging.error(f"An unexpected error occurred loading donation buttons: {e}")

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
        if not current_message_info:
            return

        old_message_id = current_message_info['message_id']
        old_channel_id = current_message_info['channel_id']
        
        current_embed_obj = None
        try:
            old_channel_obj = interaction.guild.get_channel(old_channel_id) or await interaction.guild.fetch_channel(old_channel_id)
            if old_channel_obj:
                old_message_obj = await old_channel_obj.fetch_message(old_message_id)
                current_embed_obj = old_message_obj.embeds[0] if old_message_obj.embeds else None
                await old_message_obj.delete()
        except (discord.NotFound, discord.HTTPException) as e:
            logging.warning(f"Could not delete old music message {old_message_id} in channel {old_channel_id}: {e}")
        finally:
            del self.cog.current_music_message_info[guild_id]

        if current_embed_obj:
            embed_to_send = current_embed_obj
        else:
            embed_to_send = discord.Embed(title="Musik Bot", description="Status musik...", color=discord.Color.light_grey())
        
        new_view_instance = MusicControlView(self.cog, {'message_id': None, 'channel_id': old_channel_id})
        
        for item in new_view_instance.children:
            if item.custom_id == "music:play_pause":
                vc = interaction.guild.voice_client
                if vc and vc.is_playing():
                    item.emoji = "▶️"
                    item.style = discord.ButtonStyle.primary
                elif vc and vc.is_paused():
                    item.emoji = "⏸️"
                    item.style = discord.ButtonStyle.green
                else:
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
        
        new_message = await old_channel_obj.send(embed=embed_to_send, view=new_view_instance)
        self.cog.current_music_message_info[guild_id] = {
            'message_id': new_message.id,
            'channel_id': new_message.channel.id
        }


    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary, custom_id="music:play_pause", row=0)
    async def play_pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            button.style = discord.ButtonStyle.green
            button.emoji = "⏸️"
            await interaction.response.send_message("⏸️ Lagu dijeda.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            button.style = discord.ButtonStyle.primary
            button.emoji = "▶️"
            await interaction.response.send_message("▶️ Lanjut lagu.", ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar/dijeda.", ephemeral=True)
        
        await self._update_music_message(interaction)


    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, custom_id="music:skip", row=0)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ Skip lagu.", ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music:stop", row=0)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc:
            # PENTING: Panggil stop() sebelum disconnect untuk menghentikan FFMPEG dengan bersih
            if vc.is_playing() or vc.is_paused():
                vc.stop() 
            await vc.disconnect()
            self.cog.queues[interaction.guild.id] = []
            self.cog.loop_status[interaction.guild.id] = False
            self.cog.is_muted[interaction.guild.id] = False
            self.cog.old_volume.pop(interaction.guild.id, None)
            self.cog.now_playing_info.pop(interaction.guild.id, None)
            self.cog.playing_tracks.pop(interaction.guild.id, None) # Hapus info trek yang sedang diputar
            
            if interaction.guild.id in self.cog.current_music_message_info:
                old_message_info = self.cog.current_music_message_info[interaction.guild.id]
                try:
                    old_channel = interaction.guild.get_channel(old_message_info['channel_id']) or await interaction.guild.fetch_channel(old_message_info['channel_id'])
                    if old_channel:
                        old_message = await old_channel.fetch_message(old_message_info['message_id'])
                        await old_message.delete()
                except (discord.NotFound, discord.HTTPException) as e:
                    logging.warning(f"Could not delete old music message on stop: {e}")
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
            if len(queue) > 10:
                embed.set_footer(text=f"Dan {len(queue) - 10} lagu lainnya...")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("Antrean kosong.", ephemeral=True)
            
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.grey, custom_id="music:loop", row=1)
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        guild_id = interaction.guild.id
        if guild_id not in self.cog.loop_status:
            self.cog.loop_status[guild_id] = False

        self.cog.loop_status[guild_id] = not self.cog.loop_status[guild_id]

        if self.cog.loop_status[guild_id]:
            await interaction.response.send_message("🔁 Mode Loop **ON** (lagu saat ini akan diulang).", ephemeral=True)
        else:
            await interaction.response.send_message("🔁 Mode Loop **OFF**.", ephemeral=True)
        
        await self._update_music_message(interaction)

    @discord.ui.button(emoji="📖", style=discord.ButtonStyle.blurple, custom_id="music:lyrics", row=1)
    async def lyrics_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.genius:
            await interaction.response.send_message("Fitur lirik masih beta dan akan segera dirilis nantinya.", ephemeral=True)
            return

        song_name = None
        
        if not interaction.guild.id in self.cog.now_playing_info:
             await interaction.response.send_message("Tidak ada lagu yang sedang diputar. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
             return

        await interaction.response.defer(ephemeral=True)
        await self.cog._send_lyrics(interaction, song_name_override=None)

    # --- Tombol Volume Baru ---
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

        vc = interaction.guild.voice_client
        guild_id = interaction.guild.id
        
        if vc and vc.source:
            if not self.cog.is_muted.get(guild_id, False):
                self.cog.old_volume[guild_id] = vc.source.volume
                vc.source.volume = 0.0
                self.cog.is_muted[guild_id] = True
                await interaction.response.send_message("🔇 Volume dimatikan.", ephemeral=True)
            else:
                vc.source.volume = self.cog.old_volume.get(guild_id, 0.8)
                self.cog.is_muted[guild_id] = False
                await interaction.response.send_message("🔊 Volume dinyalakan.", ephemeral=True)
            
            await self._update_music_message(interaction)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)

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


class ReswanBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Music Module States
        self.queues = {}
        self.loop_status = {}
        self.current_music_message_info = {} 
        self.is_muted = {}
        self.old_volume = {}
        self.now_playing_info = {}
        # Untuk trek musik yang sedang diputar (digunakan untuk penghapusan file)
        self.playing_tracks = {} # {guild_id: {'filename': 'path/to/file'}}
        
        GENIUS_API_TOKEN = os.getenv("GENIUS_API")
        self.genius = None
        if GENIUS_API_TOKEN:
            try:
                self.genius = Genius(GENIUS_API_TOKEN)
            except Exception as e:
                logging.warning(f"Failed to initialize Genius API: {e}")
                logging.warning("Lyrics feature might not work without GENIUS_API_TOKEN set correctly.")
        else:
            logging.warning("GENIUS_API_TOKEN is not set in environment variables.")
            logging.warning("Lyrics feature might not work without it.")

        # --- PERBAIKAN: Menggunakan SPOTIFY_CLIENT_ID dan SPOTIFY_CLIENT_SECRET yang benar ---
        SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
        SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
        self.spotify = None
        if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
            try:
                self.spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
                    client_id=SPOTIFY_CLIENT_ID,
                    client_secret=SPOTIFY_CLIENT_SECRET
                ))
            except Exception as e:
                logging.warning(f"Could not initialize Spotify client: {e}")
                logging.warning("Spotify features might not work.")
        else:
            logging.warning("SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET not set.")
            logging.warning("Spotify features might not work without them.")

        self.bot.add_view(MusicControlView(self))

        # TempVoice Module States
        self.TRIGGER_VOICE_CHANNEL_ID = 1382486705113927811 
        self.TARGET_CATEGORY_ID = 1255211613326278716 
        self.DEFAULT_CHANNEL_NAME_PREFIX = "Music"
        self.active_temp_channels = load_temp_channels() 
        log.info(f"ReswanBot cog loaded. Active temporary channels: {self.active_temp_channels}")
        self.cleanup_task.start()
        # Task untuk memeriksa dan mengeluarkan bot jika channel kosong
        self.idle_check_task = self.bot.loop.create_task(self._check_and_disconnect_idle_bots())

    def _save_temp_channels_state(self):
        save_temp_channels(self.active_temp_channels)
        log.debug("Temporary channel state saved.")

    def cog_unload(self):
        log.info("ReswanBot cog unloaded. Cancelling cleanup tasks.")
        self.cleanup_task.cancel()
        self.idle_check_task.cancel() # Batalkan task pengecekan idle

    @tasks.loop(seconds=10) # Cek setiap 10 detik
    async def cleanup_task(self):
        log.debug("Running TempVoice cleanup task.") 
        channels_to_remove = []
        for channel_id_str, channel_info in list(self.active_temp_channels.items()): 
            channel_id = int(channel_id_str) 
            guild_id = int(channel_info["guild_id"]) 
            guild = self.bot.get_guild(guild_id)
            
            if not guild:
                log.warning(f"Guild {guild_id} not found for channel {channel_id}. Removing from tracking.")
                channels_to_remove.append(channel_id_str)
                continue

            channel = guild.get_channel(channel_id)
            
            if not channel: 
                log.info(f"Temporary voice channel {channel_id} no longer exists in guild {guild.name}. Removing from tracking.")
                channels_to_remove.append(channel_id_str)
                continue

            # --- LOGIKA BARU UNTUK HAPUS CUSTOM CHANNEL JIKA TANPA PENGGUNA MANUSIA ---
            human_members_in_custom_channel = [
                member for member in channel.members
                if not member.bot
            ]

            if not human_members_in_custom_channel: # Jika tidak ada anggota manusia
                try:
                    await channel.delete(reason="Custom voice channel is empty of human users.")
                    log.info(f"Deleted empty (of humans) temporary voice channel: {channel.name} ({channel_id}).")
                    channels_to_remove.append(channel_id_str)
                except discord.NotFound: 
                    log.info(f"Temporary voice channel {channel_id} already deleted (from Discord). Removing from tracking.")
                    channels_to_remove.append(channel_id_str)
                except discord.Forbidden:
                    log.error(f"Bot lacks permissions to delete temporary voice channel {channel.name} ({channel_id}). Please check 'Manage Channels' permission.")
                except Exception as e:
                    log.error(f"Error deleting temporary voice channel {channel.name} ({channel_id}): {e}", exc_info=True)
            
        for ch_id in channels_to_remove:
            self.active_temp_channels.pop(ch_id, None)
        if channels_to_remove: 
            self._save_temp_channels_state() 
            log.debug(f"Temporary channel data saved after cleanup. Remaining: {len(self.active_temp_channels)}.")

    @cleanup_task.before_loop
    async def before_cleanup_task(self):
        log.info("Waiting for bot to be ready before starting TempVoice cleanup task.")
        await self.bot.wait_until_ready()
        log.info("Bot ready, TempVoice cleanup task is about to start.")

    @tasks.loop(seconds=30) # Mengubah timer dari minutes=2 menjadi seconds=30
    async def _check_and_disconnect_idle_bots(self):
        log.info("Running idle check task...")
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if vc and vc.is_connected():
                log.info(f"Checking voice channel {vc.channel.name} in guild {guild.name} (ID: {guild.id})...")
                
                # Filter anggota untuk mengecualikan bot itu sendiri
                human_members = [
                    member for member in vc.channel.members
                    if not member.bot
                ]
                
                num_human_members = len(human_members)
                is_playing_or_paused = vc.is_playing() or vc.is_paused()
                is_queue_empty = not self.queues.get(guild.id) or len(self.queues.get(guild.id)) == 0

                log.info(f"  Human members: {num_human_members}, Playing/Paused: {is_playing_or_paused}, Queue Empty: {is_queue_empty}")
                
                # --- LOG DEBUG DETAIL MEMBER ---
                log.debug(f"  Members in {vc.channel.name}:")
                for member in vc.channel.members:
                    log.debug(f"    - {member.display_name} (ID: {member.id}), is_bot: {member.bot}")

                # Jika tidak ada anggota manusia
                if num_human_members == 0:
                    log.info(f"Bot {self.bot.user.name} idle in voice channel {vc.channel.name} in guild {guild.name} (no human members). Disconnecting.")
                    
                    # Panggil stop() sebelum disconnect untuk menghentikan FFMPEG dengan bersih
                    if is_playing_or_paused:
                        vc.stop()
                    await vc.disconnect()
                    
                    # Bersihkan state guild ini
                    self.queues.pop(guild.id, None)
                    self.loop_status.pop(guild.id, None)
                    self.is_muted.pop(guild.id, None)
                    self.old_volume.pop(guild.id, None)
                    self.now_playing_info.pop(guild.id, None)
                    self.playing_tracks.pop(guild.id, None) 

                    # Hapus pesan kontrol musik terakhir jika ada
                    if guild.id in self.current_music_message_info:
                        old_message_info = self.current_music_message_info[guild.id]
                        try:
                            old_channel = guild.get_channel(old_message_info['channel_id']) or await guild.fetch_channel(old_message_info['channel_id'])
                            if old_channel:
                                old_message = await old_channel.fetch_message(old_message_info['message_id'])
                                await old_message.delete()
                                log.info(f"Deleted old music message {old_message_info['message_id']} in channel {old_message_info['channel_id']}.")
                        except (discord.NotFound, discord.HTTPException) as e:
                            logging.warning(f"Could not delete old music message on idle disconnect: {e}")
                        finally:
                            del self.current_music_message_info[guild.id]
                else:
                    log.info(f"Bot {self.bot.user.name} not idle in {vc.channel.name}. Conditions: Human Members={num_human_members}, Playing/Paused={is_playing_or_paused}, Queue Empty={is_queue_empty}.")


    @_check_and_disconnect_idle_bots.before_loop
    async def before_idle_check_task(self):
        await self.bot.wait_until_ready()
        log.info("Bot ready, idle check task is about to start.")


    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        # --- LOGIKA UNTUK PEMBUATAN CHANNEL SEMENTARA ---
        if after.channel and after.channel.id == self.TRIGGER_VOICE_CHANNEL_ID: 
            log.info(f"User {member.display_name} ({member.id}) joined trigger VC ({self.TRIGGER_VOICE_CHANNEL_ID}).")

            for ch_id_str, ch_info in list(self.active_temp_channels.items()): 
                if ch_info["owner_id"] == str(member.id) and ch_info["guild_id"] == str(member.guild.id):
                    existing_channel = member.guild.get_channel(int(ch_id_str))
                    if existing_channel:
                        log.info(f"User {member.display_name} already has active temporary VC {existing_channel.name}. Moving them there.")
                        try:
                            await member.move_to(existing_channel)
                            return 
                        except discord.Forbidden:
                            log.error(f"Bot lacks permissions to move {member.display_name} to their existing VC {existing_channel.name}.")
                            try: await member.send(f"❌ Gagal memindahkan Anda ke channel pribadi Anda: Bot tidak memiliki izin 'Move Members'. Silakan hubungi admin server.", ephemeral=True)
                            except discord.Forbidden: pass 
                            return
                        except Exception as e:
                            log.error(f"Error moving {member.display_name} to existing VC {existing_channel.name}: {e}", exc_info=True)
                            try: await member.send(f"❌ Terjadi kesalahan saat memindahkan Anda ke channel pribadi Anda: {e}. Hubungi admin server.", ephemeral=True)
                            except discord.Forbidden: pass
                            return
                    else: 
                        log.warning(f"Temporary channel {ch_id_str} in data not found on Discord. Removing from tracking.")
                        self.active_temp_channels.pop(ch_id_str)
                        self._save_temp_channels_state() 

            guild = member.guild
            category = guild.get_channel(self.TARGET_CATEGORY_ID) 
            
            if not category or not isinstance(category, discord.CategoryChannel):
                log.error(f"Target category {self.TARGET_CATEGORY_ID} not found or is not a category channel in guild {guild.name}. Skipping VC creation.")
                try: await member.send("❌ Gagal membuat channel suara pribadi: Kategori tujuan tidak ditemukan atau tidak valid. Hubungi admin server.", ephemeral=True)
                except discord.Forbidden: pass
                try: await member.move_to(None, reason="Target category invalid.")
                except: pass
                return

            current_category_channels = [ch for ch in category.voice_channels if ch.name.startswith(self.DEFAULT_CHANNEL_NAME_PREFIX)] 
            
            next_channel_number = 1
            if current_category_channels:
                max_num = 0
                for ch_obj in current_category_channels:
                    try:
                        parts = ch_obj.name.rsplit(' ', 1) 
                        if len(parts) > 1 and parts[-1].isdigit():
                            num = int(parts[-1])
                            if num > max_num:
                                max_num = num
                    except Exception as e:
                        log.debug(f"Could not parse number from channel name {ch_obj.name}: {e}")
                        continue
                next_channel_number = max_num + 1

            new_channel_name = f"{self.DEFAULT_CHANNEL_NAME_PREFIX} {next_channel_number}" 
            
            try:
                everyone_role = guild.default_role
                admin_role = discord.utils.get(guild.roles, permissions=discord.Permissions(administrator=True))
                
                overwrites = {
                    everyone_role: discord.PermissionOverwrite(connect=False, speak=False, send_messages=False, view_channel=False),
                    guild.me: discord.PermissionOverwrite(connect=True, speak=True, send_messages=True, view_channel=True, read_message_history=True)
                }
                
                if admin_role:
                    overwrites[admin_role] = discord.PermissionOverwrite(connect=True, speak=True, send_messages=True, view_channel=True)

                overwrites[member] = discord.PermissionOverwrite(
                    connect=True, speak=True, send_messages=True, view_channel=True,
                    manage_channels=True, manage_roles=True,
                    mute_members=True, deafen_members=True, move_members=True
                )
                
                max_bitrate = guild.bitrate_limit 
                
                new_vc = await guild.create_voice_channel(
                    name=new_channel_name,
                    category=category,
                    user_limit=0,
                    overwrites=overwrites,
                    bitrate=max_bitrate, 
                    reason=f"{member.display_name} created a temporary voice channel."
                )
                log.info(f"Created new temporary VC: {new_vc.name} ({new_vc.id}) by {member.display_name} with bitrate {max_bitrate}.")

                await member.move_to(new_vc)
                log.info(f"Moved {member.display_name} to new VC {new_vc.name}.")

                self.active_temp_channels[str(new_vc.id)] = {"owner_id": str(member.id), "guild_id": str(guild.id)}
                self. _save_temp_channels_state() 
                log.debug(f"Temporary VC {new_vc.id} added to tracking.")

                await new_vc.send(
                    f"🎉 Selamat datang di channel pribadimu, {member.mention}! Kamu adalah pemilik channel ini.\n"
                    f"Channel ini diset dengan kualitas suara **maksimal** yang diizinkan server ini.\n"
                    f"Gunakan perintah di bawah untuk mengelola channel-mu:\n"
                    f"`!vcsetlimit <angka>` - Atur batas user (0 untuk tak terbatas)\n"
                    f"`!vcrename <nama_baru>` - Ubah nama channel\n"
                    f"`!vclock` - Kunci channel (hanya bisa masuk via invite)\n"
                    f"`!vcunlock` - Buka kunci channel\n"
                    f"`!vckick @user` - Tendang user dari channel\n"
                    f"`!vcgrant @user` - Beri user izin masuk channel yang terkunci\n"
                    f"`!vcrevoke @user` - Cabut izin masuk channel yang terkunci\n"
                    f"`!vcowner @user` - Transfer kepemilikan channel ke user lain (hanya bisa 1 pemilik)\n"
                    f"`!vchelp` - Menampilkan panduan ini lagi."
                )

            except discord.Forbidden:
                log.error(f"Bot lacks permissions to create voice channels or move members in guild {guild.name}. Please check 'Manage Channels' and 'Move Members' permissions.", exc_info=True)
                try: await member.send(f"❌ Gagal membuat channel suara pribadi: Bot tidak memiliki izin yang cukup (Manage Channels atau Move Members). Hubungi admin server.", ephemeral=True)
                except discord.Forbidden: pass 
                try: await member.move_to(None, reason="Bot lacks permissions.")
                except: pass
            except Exception as e:
                log.error(f"Unexpected error creating or moving to new VC in guild {guild.name}: {e}", exc_info=True)
                try: await member.send(f"❌ Terjadi kesalahan saat membuat channel suara pribadi: {e}. Hubungi admin server.", ephemeral=True)
                except discord.Forbidden: pass
                try: await member.move_to(None, reason="Unexpected error.")
                except: pass

        if before.channel and str(before.channel.id) in self.active_temp_channels:
            channel_info = self.active_temp_channels[str(before.channel.id)]
            if channel_info["owner_id"] == str(member.id) and not before.channel.members:
                log.info(f"Owner {member.display_name} left temporary VC ({before.channel.name}). Triggering immediate cleanup check.")
                pass 
    
    def is_owner_vc(self, ctx):
        if not ctx.author.voice or not ctx.author.voice.channel:
            log.debug(f"is_owner_vc check failed for {ctx.author.display_name}: not in any voice channel.")
            return False
            
        channel_id_str = str(ctx.author.voice.channel.id)
        guild_id_str = str(ctx.guild.id)
        
        if channel_id_str not in self.active_temp_channels:
            log.debug(f"is_owner_vc check failed for {ctx.author.display_name}: channel {channel_id_str} not a tracked temporary VC.")
            return False 

        channel_info = self.active_temp_channels[channel_id_str]

        if channel_info.get("guild_id") != guild_id_str:
            log.warning(f"Channel {channel_id_str} tracked but linked to wrong guild {channel_info.get('guild_id')} for {guild_id_str}.")
            return False

        is_owner = channel_info.get("owner_id") == str(ctx.author.id) 
        if not is_owner:
            log.debug(f"is_owner_vc check failed for {ctx.author.display_name}: not owner of VC {channel_id_str}. Expected owner: {channel_info.get('owner_id')}.")
            
        return is_owner

    def get_queue(self, guild_id):
        return self.queues.setdefault(guild_id, [])

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
        except Exception as e:
            logging.error(f"Error getting song info from URL {url}: {e}")
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
                    await interaction_or_ctx.response.send_message("Tidak ada lagu yang sedang diputar atau nama lagu tidak diberikan. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
                else:
                    await interaction_or_ctx.followup.send("Tidak ada lagu yang sedang diputar atau nama lagu tidak diberikan. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
            else:
                await interaction_or_ctx.send("Tidak ada lagu yang sedang diputar atau nama lagu tidak diberikan. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.")
            return

        try:
            song = None
            if song_artist_for_lyrics and "Unknown Artist" not in song_artist_for_lyrics and "channel" not in song_artist_for_lyrics.lower() and "vevo" not in song_artist_for_lyrics.lower() and "topic" not in song_artist_for_lyrics.lower():
                song = await asyncio.to_thread(self.genius.search_song, song_title_for_lyrics, song_artist_for_lyrics)
                if not song: 
                    logging.info(f"Lyrics not found for '{song_title_for_lyrics}' by '{song_artist_for_lyrics}'. Trying with title only.")
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
            logging.error(f"Error fetching lyrics: {e}")
            if isinstance(interaction_or_ctx, discord.Interaction):
                if interaction_or_ctx.response.is_done():
                    await interaction_or_ctx.followup.send(error_message, ephemeral=True)
                else:
                    await interaction_or_ctx.followup.send(error_message, ephemeral=True)
            else:
                await interaction_or_ctx.send(error_message)

    async def play_next(self, ctx):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)

        target_channel = None
        if guild_id in self.current_music_message_info:
            channel_id = self.current_music_message_info[guild_id]['channel_id']
            target_channel = ctx.guild.get_channel(channel_id)
            if not target_channel:
                try:
                    target_channel = await ctx.guild.fetch_channel(channel_id)
                except discord.NotFound:
                    logging.warning(f"Target channel {channel_id} not found for guild {guild_id}. Fallback to ctx.channel.")
                    target_channel = ctx.channel
        if not target_channel:
            target_channel = ctx.channel

        # Hapus pesan kontrol musik lama sebelum memutar lagu baru
        if guild_id in self.current_music_message_info:
            old_message_info = self.current_music_message_info[guild_id]
            try:
                old_channel = ctx.guild.get_channel(old_message_info['channel_id']) or await ctx.guild.fetch_channel(old_message_info['channel_id'])
                if old_channel:
                    old_message = await old_channel.fetch_message(old_message_info['message_id'])
                    await old_message.delete()
            except (discord.NotFound, discord.HTTPException) as e:
                logging.warning(f"Could not delete old music message {old_message_info['message_id']} in channel {old_message_info['channel_id']} during play_next: {e}")
            finally:
                del self.current_music_message_info[guild_id]

        if self.loop_status.get(guild_id, False) and ctx.voice_client and ctx.voice_client.source:
            current_song_url = ctx.voice_client.source.data.get('webpage_url')
            if current_song_url:
                queue.insert(0, current_song_url)

        if not queue:
            # Mengembalikan perilaku "brutal disconnect"
            embed = discord.Embed(
                title="Musik Berhenti 🎶",
                description="Antrean kosong. Bot akan keluar dari voice channel.",
                color=discord.Color.red()
            )
            view_instance = MusicControlView(self)
            # Menonaktifkan semua tombol saat bot akan keluar
            for item in view_instance.children:
                item.disabled = True
            
            message_sent = await target_channel.send(embed=embed, view=view_instance)
            self.current_music_message_info[guild_id] = {
                'message_id': message_sent.id,
                'channel_id': message_sent.channel.id
            }
            self.now_playing_info.pop(guild_id, None)

            # Bot keluar jika antrean kosong DAN tidak ada user lain.
            # Logika ini dipindahkan ke task _check_and_disconnect_idle_bots untuk pengecekan berkala,
            # sehingga tidak perlu double check di sini kecuali untuk pesan langsung.
            await target_channel.send("Antrean kosong. Bot akan keluar dari voice channel jika tidak ada pengguna lain.", ephemeral=True)
            return

        url = queue.pop(0)
        try:
            # Dapatkan informasi lagu untuk disimpan ke playing_tracks
            song_info_from_ytdl = await self.get_song_info_from_url(url)
            # YTDLSource.from_url akan mendownload ke 'downloads/%(title)s.%(ext)s'
            # Jadi kita perlu mendapatkan nama filenya jika diperlukan untuk dihapus
            # Jika stream=True, file tidak didownload, jadi tidak perlu dihapus.
            # Kita asumsikan stream=True untuk mengurangi penggunaan disk.
            source = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            
            # Simpan info trek yang sedang diputar (jika perlu dihapus, tambahkan 'filename' ke sini)
            self.playing_tracks[guild_id] = {'webpage_url': url} # Simpan URL untuk referensi

            # Pastikan FFMPEG dihentikan jika player sebelumnya masih aktif sebelum memutar yang baru
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                ctx.voice_client.stop()

            ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop))
            
            self.now_playing_info[guild_id] = {
                'title': song_info_from_ytdl['title'],
                'artist': song_info_from_ytdl['artist'],
                'webpage_url': song_info_from_ytdl['webpage_url']
            }

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

            view_instance = MusicControlView(self, {'message_id': None, 'channel_id': target_channel.id})
            for item in view_instance.children:
                if item.custom_id == "music:play_pause":
                    item.emoji = "▶️"
                    item.style = discord.ButtonStyle.primary
                elif item.custom_id == "music:mute_unmute":
                    if self.is_muted.get(guild_id, False):
                        item.emoji = "🔇"
                    else:
                        item.emoji = "🔊"
                item.disabled = False
            
            message_sent = await target_channel.send(embed=embed, view=view_instance)
            
            if message_sent:
                self.current_music_message_info[guild_id] = {
                    'message_id': message_sent.id,
                    'channel_id': message_sent.channel.id
                }

        except Exception as e:
            logging.error(f'Failed to play song for guild {guild_id}: {e}')
            await target_channel.send(f'Gagal memutar lagu: {e}')
            # Pastikan FFMPEG dihentikan jika ada error fatal saat mencoba memutar
            if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
                ctx.voice_client.stop()
            return

    async def _after_play_handler(self, ctx, error):
        guild_id = ctx.guild.id
        if error:
            logging.error(f"Player error for guild {guild_id}: {error}")
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
                
        await asyncio.sleep(1) # Beri sedikit waktu untuk FFMPEG berhenti

        # Hapus info trek yang baru saja diputar
        self.playing_tracks.pop(guild_id, None)

        # Lanjut ke lagu berikutnya atau berhenti jika antrean kosong
        if ctx.voice_client and ctx.voice_client.is_connected():
            await self.play_next(ctx) 
        else: # Bot sudah tidak di voice channel (mungkin di-kick manual atau disconnect oleh idle_check)
            logging.info(f"Bot disconnected from voice channel in guild {guild_id} (manual disconnect or after play handler). Cleaning up.")
            # Clear state
            self.queues[guild_id] = []
            self.loop_status[guild_id] = False
            self.is_muted[guild_id] = False
            self.old_volume.pop(guild_id, None)
            self.now_playing_info.pop(guild_id, None)
            # Hapus pesan kontrol musik terakhir
            if guild_id in self.current_music_message_info:
                old_message_info = self.current_music_message_info[guild_id]
                try:
                    old_channel = ctx.guild.get_channel(old_message_info['channel_id']) or await ctx.guild.fetch_channel(old_message_info['channel_id'])
                    if old_channel:
                        old_message = await old_channel.fetch_message(old_message_info['message_id'])
                        await old_message.delete()
                except (discord.NotFound, discord.HTTPException):
                    logging.warning(f"Could not delete old music message on auto-disconnect: {old_message_info['message_id']} in channel {old_message_info['channel_id']}.")
                finally:
                    del self.current_music_message_info[guild_id]


    async def _update_music_message_from_ctx(self, ctx):
        guild_id = ctx.guild.id
        current_message_info = self.current_music_message_info.get(guild_id)
        if not current_message_info:
            return

        old_message_id = current_message_info['message_id']
        old_channel_id = current_message_info['channel_id']

        current_embed_obj = None
        try:
            old_channel_obj = ctx.guild.get_channel(old_channel_id) or await ctx.guild.fetch_channel(old_channel_id)
            if old_channel_obj:
                old_message_obj = await old_channel_obj.fetch_message(old_message_id)
                current_embed_obj = old_message_obj.embeds[0] if old_message_obj.embeds else None
                await old_message_obj.delete()
        except (discord.NotFound, discord.HTTPException) as e:
            logging.warning(f"Could not delete old music message {old_message_id} in channel {old_channel_id}: {e}")
        finally:
            del self.current_music_message_info[guild_id]

        if current_embed_obj:
            embed_to_send = current_embed_obj
        else:
            embed_to_send = discord.Embed(title="Musik Bot", description="Status musik...", color=discord.Color.light_grey())

        vc = ctx.voice_client
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
            embed_to_send.add_field(name="Diminta oleh", value=ctx.author.mention, inline=True)
            embed_to_send.set_footer(text=f"Antrean: {len(self.get_queue(guild_id))} lagu tersisa")
        
        new_view_instance = MusicControlView(self, {'message_id': None, 'channel_id': old_channel_id})
        for item in new_view_instance.children:
            if item.custom_id == "music:play_pause":
                if vc and vc.is_playing():
                    item.emoji = "▶️"
                    item.style = discord.ButtonStyle.primary
                elif vc and vc.is_paused():
                    item.emoji = "⏸️"
                    item.style = discord.ButtonStyle.green
                else:
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
        
        new_message = await old_channel_obj.send(embed=embed_to_send, view=new_view_instance)
        self.current_music_message_info[guild_id] = {
            'message_id': new_message.id,
            'channel_id': new_message.channel.id
        }

    # --- Music Commands ---
    @commands.command(name="resjoin")
    async def join(self, ctx):
        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                return await ctx.send("Bot sudah berada di voice channel lain. Harap keluarkan dulu.")
            return
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
            await ctx.send(f"Joined **{ctx.author.voice.channel.name}**")
        else:
            await ctx.send("Kamu harus berada di voice channel dulu.")

    @commands.command(name="resp")
    async def play(self, ctx, *, query):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            if not ctx.voice_client:
                return await ctx.send("Gagal bergabung ke voice channel.")

        await ctx.defer()

        urls = []
        is_spotify_link = False
        spotify_track_info = None

        # Perbaikan: Mengubah pola URL Spotify agar tidak merujuk ke googleusercontent.com
        # Asumsi: Query Spotify akan berupa URL langsung dari Spotify atau ID track/playlist/album.
        # Jika Anda menggunakan proxy/redirect sebelumnya, Anda perlu menangani URL aslinya.
        # Untuk demonstrasi ini, saya berasumsi query adalah URL Spotify yang valid.
        if self.spotify and ("https://open.spotify.com/track/" in query or "https://open.spotify.com/playlist/" in query or "https://open.spotify.com/album/" in query): 
            is_spotify_link = True
            try:
                if "https://open.spotify.com/track/" in query:
                    track_id = query.split('/')[-1].split('?')[0]
                    track = self.spotify.track(track_id)
                    spotify_track_info = {'title': track['name'], 'artist': track['artists'][0]['name'], 'webpage_url': query}
                    search_query = f"{track['name']} {track['artists'][0]['name']}"
                    urls.append(search_query)
                elif "https://open.spotify.com/playlist/" in query:
                    playlist_id = query.split('/')[-1].split('?')[0]
                    results = self.spotify.playlist_tracks(playlist_id)
                    for item in results['items']:
                        track = item['track']
                        if track: 
                            search_query = f"{track['name']} {track['artists'][0]['name']}"
                            urls.append(search_query)
                elif "https://open.spotify.com/album/" in query:
                    album_id = query.split('/')[-1].split('?')[0]
                    results = self.spotify.album_tracks(album_id)
                    for item in results['items']:
                        track = item
                        if track: 
                            search_query = f"{track['name']} {track['artists'][0]['name']}"
                            urls.append(search_query)
                else:
                    await ctx.send("Link Spotify tidak dikenali (hanya track, playlist, atau album).", ephemeral=True)
                    return
            except Exception as e:
                logging.error(f"Error processing Spotify link: {e}")
                await ctx.send(f"Terjadi kesalahan saat memproses link Spotify: {e}", ephemeral=True)
                return
        else:
            urls.append(query)

        queue = self.get_queue(ctx.guild.id)
        
        # Hapus pesan kontrol musik lama sebelum memutar lagu baru atau menambah antrean
        if ctx.guild.id in self.current_music_message_info:
            old_message_info = self.current_music_message_info[ctx.guild.id]
            try:
                old_channel = ctx.guild.get_channel(old_message_info['channel_id']) or await ctx.guild.fetch_channel(old_message_info['channel_id'])
                if old_channel:
                    old_message = await old_channel.fetch_message(old_message_info['message_id'])
                    await old_message.delete()
            except (discord.NotFound, discord.HTTPException) as e:
                logging.warning(f"Could not delete old music message {old_message_info['message_id']} in channel {old_message_info['channel_id']} during play command: {e}")
            finally:
                del self.current_music_message_info[ctx.guild.id]


        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused() and not queue:
            first_url = urls.pop(0)
            queue.extend(urls)
            try:
                source = await YTDLSource.from_url(first_url, loop=self.bot.loop, stream=True) # Pastikan stream=True
                ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop))

                if is_spotify_link and spotify_track_info:
                    self.now_playing_info[ctx.guild.id] = spotify_track_info
                    self.playing_tracks[ctx.guild.id] = {'webpage_url': spotify_track_info['webpage_url']}
                else:
                    song_info_from_ytdl = await self.get_song_info_from_url(first_url)
                    self.now_playing_info[ctx.guild.id] = {
                        'title': song_info_from_ytdl['title'],
                        'artist': song_info_from_ytdl['artist'],
                        'webpage_url': song_info_from_ytdl['webpage_url']
                    }
                    self.playing_tracks[ctx.guild.id] = {'webpage_url': song_info_from_ytdl['webpage_url']}


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

                view_instance = MusicControlView(self, {'message_id': None, 'channel_id': ctx.channel.id})
                if self.is_muted.get(ctx.guild.id, False):
                    for item in view_instance.children:
                        if item.custom_id == "music:mute_unmute":
                            item.emoji = "🔇"
                            break

                message_sent = await ctx.send(embed=embed, view=view_instance)
                
                if message_sent:
                    self.current_music_message_info[ctx.guild.id] = {
                        'message_id': message_sent.id,
                        'channel_id': message_sent.channel.id
                    }
                
            except Exception as e:
                logging.error(f'Failed to play song: {e}')
                await ctx.send(f'Gagal memutar lagu: {e}', ephemeral=True)
                # Pastikan FFMPEG dihentikan jika ada error fatal saat mencoba memutar
                if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
                    ctx.voice_client.stop()
                return
        else:
            await ctx.send(f"Ditambahkan ke antrian: **{len(urls)} lagu**." if is_spotify_link else f"Ditambahkan ke antrian: **{urls[0]}**.", ephemeral=True)
            queue.extend(urls)
                
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)

    @commands.command(name="resskip")
    async def skip_cmd(self, ctx):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            return await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        ctx.voice_client.stop() # Ini akan memicu _after_play_handler
        await ctx.send("⏭️ Skip lagu.", ephemeral=True)

    @commands.command(name="respause")
    async def pause_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Lagu dijeda.", ephemeral=True)
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)
        else:
            await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)

    @commands.command(name="resresume")
    async def resume_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Lanjut lagu.", ephemeral=True)
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)
        else:
            await ctx.send("Tidak ada lagu yang dijeda.", ephemeral=True)

    @commands.command(name="resstop")
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
                    logging.warning(f"Could not delete old music message on stop command for message {old_message_info['message_id']} in channel {old_message_info['channel_id']}.")
                finally:
                    del self.current_music_message_info[ctx.guild.id]

            # Panggil stop() sebelum disconnect untuk menghentikan FFMPEG dengan bersih
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                ctx.voice_client.stop()

            self.queues[ctx.guild.id] = []
            self.loop_status[ctx.guild.id] = False
            self.is_muted[ctx.guild.id] = False
            self.old_volume.pop(ctx.guild.id, None)
            self.now_playing_info.pop(ctx.guild.id, None)
            self.playing_tracks.pop(ctx.guild.id, None) # Hapus info trek yang sedang diputar
            
            await ctx.voice_client.disconnect()
            await ctx.send("⏹️ Stop dan keluar dari voice.", ephemeral=True)
        else:
            await ctx.send("Bot tidak ada di voice channel.", ephemeral=True)

    @commands.command(name="resqueue")
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
            await ctx.send("Antrian kosong.", ephemeral=True)
            
    @commands.command(name="resloop")
    async def loop_cmd(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.loop_status:
            self.loop_status[guild_id] = False
            
        self.loop_status[guild_id] = not self.loop_status[guild_id]

        status_msg = "ON" if self.loop_status[guild_id] else "OFF"
        await ctx.send(f"🔁 Mode Loop **{status_msg}** (lagu saat ini akan diulang).", ephemeral=True)

        if ctx.guild.id in self.current_music_message_info:
            await self._update_music_message_from_ctx(ctx)

    @commands.command(name="reslyrics")
    async def lyrics(self, ctx, *, song_name=None):
        if not self.genius:
            return await ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
            
        if song_name is None:
            if ctx.guild.id not in self.now_playing_info:
                return await ctx.send("Tentukan nama lagu atau putar lagu terlebih dahulu untuk mencari liriknya.", ephemeral=True)
            
        await ctx.defer(ephemeral=True)
        await self._send_lyrics(ctx, song_name_override=song_name)

    @commands.command(name="resvolume")
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

    @commands.command(name="resshuffle")
    async def shuffle_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if len(queue) > 1:
            random.shuffle(queue)
            await ctx.send("🔀 Antrean lagu diacak!", ephemeral=True)
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)
        else:
            await ctx.send("Antrean terlalu pendek untuk diacak.", ephemeral=True)

    @commands.command(name="resclear")
    async def clear_queue_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            self.queues[ctx.guild.id] = []
            await ctx.send("🗑️ Antrean lagu telah dikosongkan!", ephemeral=True)
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)
        else:
            await ctx.send("Antrean sudah kosong.", ephemeral=True)

    # --- TempVoice Commands ---
    @commands.command(name="setvccreator", help="[ADMIN] Set a voice channel as a temporary channel creator. Users joining it will get a new private channel.")
    @commands.has_permissions(administrator=True)
    async def set_vc_creator(self, ctx, channel: discord.VoiceChannel):
        await ctx.send("❗ Perintah ini tidak diperlukan jika TRIGGER_VOICE_CHANNEL_ID diatur secara manual di kode. Saluran pembuat tetap ditentukan oleh `TRIGGER_VOICE_CHANNEL_ID`.", ephemeral=True)
        log.warning(f"Admin {ctx.author.display_name} used setvccreator, but bot uses static TRIGGER_VOICE_CHANNEL_ID.")

    @commands.command(name="removevccreator", help="[ADMIN] Remove a voice channel from being a temporary channel creator.")
    @commands.has_permissions(administrator=True)
    async def remove_vc_creator(self, ctx, channel: discord.VoiceChannel):
        await ctx.send("❗ Perintah ini tidak diperlukan jika TRIGGER_VOICE_CHANNEL_ID diatur secara manual di kode.", ephemeral=True)
        log.warning(f"Admin {ctx.author.display_name} used removevccreator, but bot uses static TRIGGER_VOICE_CHANNEL_ID.")

    @commands.command(name="vclock", help="Kunci channel pribadimu (hanya bisa masuk via invite/grant).")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_lock(self, ctx):
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(ctx.guild.default_role, connect=False, reason=f"User {ctx.author.display_name} locked VC.")
            await ctx.send(f"✅ Channel **{vc.name}** telah dikunci. Hanya user dengan izin khusus yang bisa bergabung.", ephemeral=True)
            log.info(f"User {ctx.author.display_name} locked VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengunci channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to lock VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error locking VC {ctx.author.voice.channel.name}: {e}", exc_info=True)

    @commands.command(name="vcunlock", help="Buka kunci channel pribadimu.")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_unlock(self, ctx):
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(ctx.guild.default_role, connect=True, reason=f"User {ctx.author.display_name} unlocked VC.")
            await ctx.send(f"✅ Channel **{vc.name}** telah dibuka. Sekarang siapa pun bisa bergabung.", ephemeral=True)
            log.info(f"User {ctx.author.display_name} unlocked VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk membuka kunci channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to unlock VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error unlocking VC {ctx.author.voice.channel.name}: {e}", exc_info=True)

    @commands.command(name="vcsetlimit", help="Atur batas user di channel suara pribadimu (0 untuk tak terbatas).")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_set_limit(self, ctx, limit: int):
        if limit < 0 or limit > 99:
            return await ctx.send("❌ Batas user harus antara 0 (tak terbatas) hingga 99.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            await vc.edit(user_limit=limit, reason=f"User {ctx.author.display_name} set user limit.")
            await ctx.send(f"✅ Batas user channelmu diatur ke: **{limit if limit > 0 else 'tak terbatas'}**.", ephemeral=True)
            log.info(f"User {ctx.author.display_name} set user limit to {limit} for VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengubah batas user channel ini. Pastikan bot memiliki izin 'Manage Channels'.", ephemeral=True)
            log.error(f"Bot lacks permissions to set user limit for VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error setting user limit for VC {ctx.author.voice.channel.name}: {e}", exc_info=True)

    @commands.command(name="vcrename", help="Ubah nama channel pribadimu.")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_rename(self, ctx, *, new_name: str):
        if len(new_name) < 2 or len(new_name) > 100:
            return await ctx.send("❌ Nama channel harus antara 2 hingga 100 karakter.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            old_name = vc.name
            await vc.edit(name=new_name, reason=f"User {ctx.author.display_name} renamed VC.")
            await ctx.send(f"✅ Nama channelmu diubah dari **{old_name}** menjadi **{new_name}**.", ephemeral=True)
            log.info(f"User {ctx.author.display_name} renamed VC from {old_name} to {new_name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengubah nama channel ini. Pastikan bot memiliki izin 'Manage Channels'.", ephemeral=True)
            log.error(f"Bot lacks permissions to rename VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error renaming VC {ctx.author.voice.channel.name}: {e}", exc_info=True)

    @commands.command(name="vckick", help="Tendang user dari channel suara pribadimu.")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_kick(self, ctx, member: discord.Member):
        if member.id == ctx.author.id:
            return await ctx.send("❌ Kamu tidak bisa menendang dirimu sendiri dari channelmu!", ephemeral=True)
        if member.bot:
            return await ctx.send("❌ Kamu tidak bisa menendang bot.", ephemeral=True)
            
        vc = ctx.author.voice.channel
        if member.voice and member.voice.channel == vc:
            try:
                await member.move_to(None, reason=f"Kicked by VC owner {ctx.author.display_name}.")
                await ctx.send(f"✅ **{member.display_name}** telah ditendang dari channelmu.", ephemeral=True)
                log.info(f"VC owner {ctx.author.display_name} kicked {member.display_name} from {vc.name}.")
            except discord.Forbidden:
                await ctx.send("❌ Bot tidak memiliki izin untuk menendang pengguna ini. Pastikan bot memiliki izin 'Move Members'.", ephemeral=True)
                log.error(f"Bot lacks permissions to kick {member.display_name} from VC {vc.name}.")
            except Exception as e:
                await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
                log.error(f"Error kicking {member.display_name} from VC {vc.name}: {e}", exc_info=True)
        else:
            await ctx.send("❌ Pengguna tersebut tidak berada di channelmu.", ephemeral=True)

    @commands.command(name="vcgrant", help="Berikan user izin masuk channelmu yang terkunci.")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_grant(self, ctx, member: discord.Member):
        if member.bot:
            return await ctx.send("❌ Kamu tidak bisa memberikan izin ke bot.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(member, connect=True, reason=f"VC owner {ctx.author.display_name} granted access.")
            await ctx.send(f"✅ **{member.display_name}** sekarang memiliki izin untuk bergabung ke channelmu.", ephemeral=True)
            log.info(f"VC owner {ctx.author.display_name} granted access to {member.display_name} for VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk memberikan izin di channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to grant access for VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error granting access for VC {ctx.author.voice.channel.name}: {e}", exc_info=True)

    @commands.command(name="vcrevoke")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_revoke(self, ctx, member: discord.Member):
        if member.bot:
            return await ctx.send("❌ Kamu tidak bisa mencabut izin dari bot.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(member, connect=False, reason=f"VC owner {ctx.author.display_name} revoked access.")
            await ctx.send(f"✅ Izin **{member.display_name}** untuk bergabung ke channelmu telah dicabut.", ephemeral=True)
            log.info(f"VC owner {ctx.author.display_name} revoked access from {member.display_name} for VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mencabut izin di channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to revoke access for VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error revoking access for VC {ctx.author.voice.channel.name}: {e}", exc_info=True)

    @commands.command(name="vcowner")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_transfer_owner(self, ctx, new_owner: discord.Member):
        vc = ctx.author.voice.channel
        vc_id_str = str(vc.id)

        if new_owner.bot:
            return await ctx.send("❌ Kamu tidak bisa mentransfer kepemilikan ke bot.", ephemeral=True)
        if new_owner.id == ctx.author.id:
            return await ctx.send("❌ Kamu sudah menjadi pemilik channel ini!", ephemeral=True)

        try:
            self.active_temp_channels[vc_id_str]["owner_id"] = str(new_owner.id) 
            self._save_temp_channels_state() 
            
            old_owner_overwrites = vc.overwrites_for(ctx.author)
            old_owner_overwrites.manage_channels = None
            old_owner_overwrites.manage_roles = None
            old_owner_overwrites.mute_members = None
            old_owner_overwrites.deafen_members = None
            old_owner_overwrites.move_members = None
            await vc.set_permissions(ctx.author, overwrite=old_owner_overwrites, reason=f"Transfer ownership from {ctx.author.display_name}.")
            log.info(f"Removed old owner permissions from {ctx.author.display_name} for channel {vc.name}.")

            new_owner_overwrites = vc.overwrites_for(new_owner)
            new_owner_overwrites.manage_channels = True
            new_owner_overwrites.manage_roles = True
            new_owner_overwrites.mute_members = True
            new_owner_overwrites.deafen_members = True
            new_owner_overwrites.move_members = True
            await vc.set_permissions(new_owner, overwrite=new_owner_overwrites, reason=f"Transfer ownership to {new_owner.display_name}.")
            
            await ctx.send(f"✅ Kepemilikan channel **{vc.name}** telah ditransfer dari {ctx.author.mention} ke {new_owner.mention}!", ephemeral=True)
            log.info(f"VC ownership transferred from {ctx.author.display_name} to {new_owner.display_name} for VC {vc.name}.")

            try:
                await new_owner.send(
                    f"🎉 Selamat! Anda sekarang adalah pemilik channel suara **{vc.name}** di server **{ctx.guild.name}**!\n"
                    f"Gunakan perintah `!vchelp` untuk melihat cara mengelola channel ini."
                )
            except discord.Forbidden:
                log.warning(f"Could not send ownership transfer DM to {new_owner.display_name} (DMs closed).")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengalihkan kepemilikan channel ini. Pastikan bot memiliki izin 'Manage Permissions' dan 'Manage Channels'.", ephemeral=True)
            log.error(f"Bot lacks permissions to transfer ownership for VC {vc.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan saat mengalihkan kepemilikan: {e}", ephemeral=True)
            log.error(f"Error transferring ownership for VC {vc.name}: {e}", exc_info=True)

    @commands.command(name="adminvcowner", help="[ADMIN] Mengatur pemilik saluran suara sementara mana pun.")
    @commands.has_permissions(administrator=True)
    async def admin_vc_transfer_owner(self, ctx, channel: discord.VoiceChannel, new_owner: discord.Member):
        channel_id_str = str(channel.id)

        if channel_id_str not in self.active_temp_channels:
            await ctx.send("❌ Saluran ini bukan saluran suara sementara yang terdaftar.", ephemeral=True)
            return
        
        if new_owner.bot:
            await ctx.send("❌ Tidak bisa mengalihkan kepemilikan ke bot.", ephemeral=True)
            return

        old_owner_id = self.active_temp_channels[channel_id_str].get('owner_id')
        old_owner = ctx.guild.get_member(int(old_owner_id)) if old_owner_id else None

        try:
            self.active_temp_channels[channel_id_str]['owner_id'] = str(new_owner.id)
            self._save_temp_channels_state()

            if old_owner and old_owner.id != new_owner.id:
                old_owner_overwrites = channel.overwrites_for(old_owner)
                old_owner_overwrites.manage_channels = None
                old_owner_overwrites.manage_roles = None
                old_owner_overwrites.mute_members = None
                old_owner_overwrites.deafen_members = None
                old_owner_overwrites.move_members = None
                await channel.set_permissions(old_owner, overwrite=old_owner_overwrites, reason=f"Admin transfer ownership from {old_owner.display_name}.")
                log.info(f"Admin removed old owner permissions from {old_owner.display_name} for channel {channel.name}.")

            new_owner_overwrites = channel.overwrites_for(new_owner)
            new_owner_overwrites.manage_channels = True
            new_owner_overwrites.manage_roles = True
            new_owner_overwrites.mute_members = True
            new_owner_overwrites.deafen_members = True
            new_owner_overwrites.move_members = True
            await channel.set_permissions(new_owner, overwrite=new_owner_overwrites, reason=f"Admin transfer ownership to {new_owner.display_name}.")
            
            await ctx.send(f"✅ Kepemilikan saluran {channel.mention} telah dialihkan ke {new_owner.mention} (oleh admin).", ephemeral=True)
            log.info(f"Admin {ctx.author.display_name} transferred ownership of {channel.name} to {new_owner.display_name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengalihkan kepemilikan channel ini. Pastikan bot memiliki izin 'Manage Permissions' dan 'Manage Channels'.", ephemeral=True)
            log.error(f"Bot lacks permissions to transfer ownership for VC {channel.name} (admin command).")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan saat mengalihkan kepemilikan (admin command): {e}", ephemeral=True)
            log.error(f"Error transferring ownership for VC {channel.name} (admin command): {e}", exc_info=True)

    @commands.command(name="vchelp")
    async def vc_help(self, ctx):
        """Menampilkan daftar perintah untuk mengelola channel suara pribadi."""
        embed = discord.Embed(
            title="🎧 Panduan Channel Suara Pribadi 🎧",
            description="""
            Saat kamu bergabung ke **Channel Khusus Buat VC Baru**, bot akan otomatis membuat channel suara baru untukmu!
            Kamu akan menjadi pemilik channel tersebut dan punya kendali penuh atasnya.
            """,
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Manajemen Channel:", value="""
        `!vcsetlimit <angka>`: Atur batas jumlah user yang bisa masuk (0 untuk tak terbatas).
        `!vcrename <nama_baru>`: Ubah nama channel suaramu.
        `!vclock`: Kunci channelmu agar hanya user dengan izin yang bisa masuk (via `!vcgrant`).
        `!vcunlock`: Buka kunci channelmu agar siapa pun bisa masuk.
        """, inline=False)

        embed.add_field(name="Manajemen User:", value="""
        `!vckick @user`: Tendang user dari channelmu.
        `!vcgrant @user`: Beri user izin masuk channelmu yang terkunci.
        `!vcrevoke @user`: Cabut izin user dari channelmu yang terkunci.
        `!vcowner @user`: Transfer kepemilikan channel ke user lain.
        """, inline=False)
        
        embed.set_footer(text="Ingat, channel pribadimu akan otomatis terhapus jika kosong!")
        await ctx.send(embed=embed)
        log.info(f"Sent VC help message to {ctx.author.display_name}.")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if ctx.cog != self:
            return

        if isinstance(error, commands.CheckFailure):
            if not ctx.author.voice or not ctx.author.voice.channel:
                await ctx.send("❌ Kamu harus berada di channel suara untuk menggunakan perintah ini.", ephemeral=True)
            elif str(ctx.author.voice.channel.id) not in self.active_temp_channels:
                await ctx.send("❌ Kamu harus berada di channel suara pribadi yang kamu miliki untuk menggunakan perintah ini.", ephemeral=True)
            else:
                await ctx.send("❌ Kamu harus menjadi pemilik channel ini untuk menggunakan perintah ini.", ephemeral=True)
            log.warning(f"User {ctx.author.display_name} tried to use VC command '{ctx.command.name}' but failed check: {error}")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Argumen tidak lengkap. Contoh penggunaan: `!{ctx.command.name} {ctx.command.signature}`", ephemeral=True)
            log.warning(f"Missing argument for {ctx.command.name} from {ctx.author.display_name}. Error: {error}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Argumen tidak valid. Pastikan kamu menyebutkan user yang benar atau angka yang valid.", ephemeral=True)
            log.warning(f"Bad argument for {ctx.command.name} from {ctx.author.display_name}. Error: {error}")
        elif isinstance(error, discord.Forbidden):
            await ctx.send("❌ Bot tidak memiliki izin untuk melakukan tindakan ini. Pastikan role bot berada di atas role lain dan memiliki izin yang diperlukan (misal: 'Manage Channels', 'Move Members', 'Manage Permissions').", ephemeral=True)
            log.error(f"Bot forbidden from performing VC action in guild {ctx.guild.name}. Command: {ctx.command.name}. Error: {error}", exc_info=True)
        elif isinstance(error, commands.CommandInvokeError):
            original_error = error.original
            await ctx.send(f"❌ Terjadi kesalahan saat menjalankan perintah: {original_error}", ephemeral=True)
            log.error(f"Command '{ctx.command.name}' invoked by {ctx.author.display_name} raised an error: {original_error}", exc_info=True)
        else:
            await ctx.send(f"❌ Terjadi kesalahan yang tidak terduga: {error}", ephemeral=True)
            log.error(f"Unhandled error in VC command {ctx.command.name} by {ctx.author.display_name}: {error}", exc_info=True)


async def setup(bot):
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
        logging.info("Created 'downloads' directory.")
    
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
        logging.info("Created default donation_buttons.json file.")

    await bot.add_cog(ReswanBot(bot))
