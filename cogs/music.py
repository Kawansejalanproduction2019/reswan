import discord
from discord.ext import commands
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

# Konfigurasi logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Inisialisasi API dipindahkan ke dalam __init__ Music Cog ---
# Hapus bagian inisialisasi Genius dan Spotify dari sini (global scope)
# GENIUS_API_TOKEN = os.getenv("GENIUS_API")
# genius = None # Hapus ini
# ... dan seterusnya untuk Spotify

ytdl_opts = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'cookiefile': 'cookies.txt',
    'quiet': True,
    'default_search': 'ytsearch',
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'noplaylist': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
        'preferredquality': '192',
    }],
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -b:a 192k'
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

# --- Class untuk Tombol Kontrol Musik ---
class MusicControlView(discord.ui.View):
    def __init__(self, cog_instance, original_message_info=None):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.original_message_info = original_message_info
        self.is_muted = False
        
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
        if guild_id not in self.cog.current_music_message_info:
            return

        old_message_info = self.cog.current_music_message_info[guild_id]
        old_message_id = old_message_info['message_id']
        old_channel_id = old_message_info['channel_id']

        try:
            old_channel = interaction.guild.get_channel(old_channel_id) or await interaction.guild.fetch_channel(old_channel_id)
            if old_channel:
                old_message = await old_channel.fetch_message(old_message_id)
                await old_message.delete()
        except (discord.NotFound, discord.HTTPException) as e:
            logging.warning(f"Could not delete old music message {old_message_id} in channel {old_channel_id}: {e}")

        current_embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else discord.Embed(title="Musik Berhenti 🎶")
        
        for item in self.children:
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
            item.disabled = False
        
        new_message = await old_channel.send(embed=current_embed, view=MusicControlView(self.cog, {'message_id': None, 'channel_id': old_channel_id}))
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
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)

            await vc.disconnect()
            self.cog.queues[interaction.guild.id] = []
            self.cog.loop_status[interaction.guild.id] = False
            
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
                *[self.cog.get_song_title_from_url(q) for q in display_queue]
            )
            msg = "\n".join([f"{i+1}. {q}" for i, q in enumerate(display_queue_titles)])
            
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
            button.style = discord.ButtonStyle.green
        else:
            await interaction.response.send_message("🔁 Mode Loop **OFF**.", ephemeral=True)
            button.style = discord.ButtonStyle.grey
        
        await self._update_music_message(interaction)

    @discord.ui.button(emoji="📖", style=discord.ButtonStyle.blurple, custom_id="music:lyrics", row=1)
    async def lyrics_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.genius:
            await interaction.response.send_message("Fitur lirik masih beta dan akan segera dirilis nantinya.", ephemeral=True)
            return

        song_name = None
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            current_source = interaction.guild.voice_client.source
            song_name = current_source.title
            
        if song_name:
            await interaction.response.defer(ephemeral=True)
            await self.cog._send_lyrics(interaction, song_name)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)

    # --- Tombol Volume Baru ---
    @discord.ui.button(emoji="➕", style=discord.ButtonStyle.secondary, custom_id="music:volume_up", row=2)
    async def volume_up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc and vc.source:
            current_volume = vc.source.volume
            new_volume = min(current_volume + 0.1, 1.0)
            vc.source.volume = new_volume
            await interaction.response.send_message(f"Volume diatur ke: {int(new_volume * 100)}%", ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        await self._update_music_message(interaction)

    @discord.ui.button(emoji="➖", style=discord.ButtonStyle.secondary, custom_id="music:volume_down", row=2)
    async def volume_down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc and vc.source:
            current_volume = vc.source.volume
            new_volume = max(current_volume - 0.1, 0.0)
            vc.source.volume = new_volume
            await interaction.response.send_message(f"Volume diatur ke: {int(new_volume * 100)}%", ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        await self._update_music_message(interaction)

    # --- Tombol Mute/Unmute Baru ---
    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="music:mute_unmute", row=2)
    async def mute_unmute_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc and vc.source:
            if not self.is_muted:
                vc.source.volume = 0.0
                self.is_muted = True
                button.emoji = "🔇"
                await interaction.response.send_message("🔇 Volume dimatikan.", ephemeral=True)
            else:
                vc.source.volume = 0.8
                self.is_muted = False
                button.emoji = "🔊"
                await interaction.response.send_message("🔊 Volume dinyalakan.", ephemeral=True)
            
            await self._update_music_message(interaction)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)

    # --- Tombol Shuffle Baru ---
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

    # --- Tombol Clear Queue Baru ---
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

    # --- Tombol Now Playing Info Baru ---
    @discord.ui.button(emoji="ℹ️", style=discord.ButtonStyle.blurple, custom_id="music:np_info", row=0)
    async def now_playing_info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc and vc.is_playing() and vc.source:
            source = vc.source
            embed = discord.Embed(
                title="🎶 Sedang Memutar (Info)",
                description=f"**[{source.title}]({source.webpage_url})**",
                color=discord.Color.purple()
            )
            if source.thumbnail:
                embed.set_thumbnail(url=source.thumbnail)
            
            duration_str = "N/A"
            if source.duration:
                minutes, seconds = divmod(source.duration, 60)
                duration_str = f"{minutes:02}:{seconds:02}"
            embed.add_field(name="Durasi", value=duration_str, inline=True)
            embed.add_field(name="Uploader", value=source.uploader or "Tidak Diketahui", inline=True)
            
            queue = self.cog.get_queue(interaction.guild.id)
            embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.loop_status = {}
        self.current_music_message_info = {} 
        
        # --- INISIALISASI API DIPINDAHKAN KE SINI ---
        # Genius API
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

        # Spotify API
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
        # --- AKHIR INISIALISASI API ---

        self.bot.add_view(MusicControlView(self))

    def get_queue(self, guild_id):
        return self.queues.setdefault(guild_id, [])

    async def get_song_title_from_url(self, url):
        try:
            info = await asyncio.to_thread(lambda: ytdl.extract_info(url, download=False, process=False))
            return info.get('title', url)
        except Exception:
            return url

    async def _send_lyrics(self, interaction_or_ctx, song_name):
        """Fungsi internal untuk mengirim lirik, bisa dipanggil dari command atau tombol."""
        if not self.genius: # Cek lagi di dalam fungsi
            if isinstance(interaction_or_ctx, discord.Interaction):
                if not interaction_or_ctx.response.is_done():
                    await interaction_or_ctx.response.send_message("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
                else:
                    await interaction_or_ctx.followup.send("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
            else:
                await interaction_or_ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.")
            return

        try:
            search_query = song_name
            current_source = None

            if isinstance(interaction_or_ctx, discord.Interaction) and \
               interaction_or_ctx.guild.voice_client and interaction_or_ctx.guild.voice_client.is_playing():
                current_source = interaction_or_ctx.guild.voice_client.source
            elif isinstance(interaction_or_ctx, commands.Context) and \
                 interaction_or_ctx.voice_client and interaction_or_ctx.voice_client.is_playing():
                current_source = interaction_or_ctx.voice_client.source

            if current_source and current_source.uploader and current_source.uploader != "Unknown":
                search_query = f"{current_source.title} {current_source.uploader}"

            song = await asyncio.to_thread(self.genius.search_song, search_query)
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
                    await interaction_or_ctx.response.send_message(error_message, ephemeral=True)
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

        # Hapus pesan lama sebelum mengirim yang baru
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
            # Kirim pesan "Musik Berhenti" baru
            embed = discord.Embed(
                title="Musik Berhenti 🎶",
                description="Antrean kosong. Bot akan keluar dari voice channel.",
                color=discord.Color.red()
            )
            # Buat view baru dengan tombol dinonaktifkan
            view_instance = MusicControlView(self)
            for item in view_instance.children:
                item.disabled = True
            
            message_sent = await target_channel.send(embed=embed, view=view_instance)
            self.current_music_message_info[guild_id] = {
                'message_id': message_sent.id,
                'channel_id': message_sent.channel.id
            }

            await target_channel.send("Antrian kosong. Keluar dari voice channel.")
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
            return

        url = queue.pop(0)
        try:
            source = await YTDLSource.from_url(url, loop=self.bot.loop)
            ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop))
            
            embed = discord.Embed(
                title="🎶 Sedang Memutar",
                description=f"**[{source.title}]({source.webpage_url})**",
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

            # Kirim pesan baru
            view_instance = MusicControlView(self, {'message_id': None, 'channel_id': target_channel.id})
            # Pastikan tombol play/pause kembali ke play
            for item in view_instance.children:
                if item.custom_id == "music:play_pause":
                    item.emoji = "▶️"
                    item.style = discord.ButtonStyle.primary
                item.disabled = False # Aktifkan kembali semua tombol
            
            message_sent = await target_channel.send(embed=embed, view=view_instance)
            
            if message_sent:
                self.current_music_message_info[guild_id] = {
                    'message_id': message_sent.id,
                    'channel_id': message_sent.channel.id
                }

        except Exception as e:
            logging.error(f'Failed to play song for guild {guild_id}: {e}')
            await target_channel.send(f'Gagal memutar lagu: {e}')
            asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

    async def _after_play_handler(self, ctx, error):
        if error:
            logging.error(f"Player error for guild {ctx.guild.id}: {error}")
            target_channel = None
            if ctx.guild.id in self.current_music_message_info:
                channel_id = self.current_music_message_info[ctx.guild.id]['channel_id']
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
            guild_id = ctx.guild.id
            self.queues[guild_id] = []
            self.loop_status[guild_id] = False
            if guild_id in self.current_music_message_info:
                # Hapus pesan lama saat bot disconnect
                old_message_info = self.current_music_message_info[guild_id]
                try:
                    old_channel = ctx.guild.get_channel(old_message_info['channel_id']) or await ctx.guild.fetch_channel(old_message_info['channel_id'])
                    if old_channel:
                        old_message = await old_channel.fetch_message(old_message_info['message_id'])
                        await old_message.delete()
                except (discord.NotFound, discord.HTTPException) as e:
                    logging.warning(f"Could not delete old music message on auto-disconnect: {e}")
                finally:
                    del self.current_music_message_info[guild_id]
            logging.info(f"Bot disconnected from voice channel in guild {guild_id}. Queue cleared.")


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
        is_spotify = False

        # Perbaikan deteksi Spotify - gunakan domain asli (https://open.spotify.com)
        # Penting: Pastikan ini sesuai dengan format link yang user berikan!
        if self.spotify and ("open.spotify.com/track/" in query or "open.spotify.com/playlist/" in query or "open.spotify.com/album/" in query): 
            is_spotify = True
            try:
                if "open.spotify.com/track/" in query:
                    track = self.spotify.track(query)
                    search_query = f"{track['name']} {track['artists'][0]['name']}"
                    urls.append(search_query)
                elif "open.spotify.com/playlist/" in query:
                    results = self.spotify.playlist_tracks(query)
                    for item in results['items']:
                        track = item['track'] if 'track' in item else item
                        if track: 
                            search_query = f"{track['name']} {track['artists'][0]['name']}"
                            urls.append(search_query)
                elif "open.spotify.com/album/" in query:
                    results = self.spotify.album_tracks(query)
                    for item in results['items']:
                        track = item['track'] if 'track' in item else item
                        if track: 
                            search_query = f"{track['name']} {track['artists'][0]['name']}"
                            urls.append(search_query)
                else:
                    await ctx.send("Link Spotify tidak dikenali (hanya track, playlist, atau album).", ephemeral=True) # Pakai ephemeral
                    return # Penting: return setelah kirim pesan error
            except Exception as e:
                logging.error(f"Error processing Spotify link: {e}")
                await ctx.send(f"Terjadi kesalahan saat memproses link Spotify: {e}", ephemeral=True) # Pakai ephemeral
                return # Penting: return setelah kirim pesan error
        else:
            urls.append(query)

        queue = self.get_queue(ctx.guild.id)
        
        # Hapus pesan lama sebelum mengirim yang baru
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
                source = await YTDLSource.from_url(first_url, loop=self.bot.loop)
                ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop))

                embed = discord.Embed(
                    title="🎶 Sedang Memutar",
                    description=f"**[{source.title}]({source.webpage_url})**",
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

                message_sent = await ctx.send(embed=embed, view=MusicControlView(self, {'message_id': None, 'channel_id': ctx.channel.id}))
                
                if message_sent:
                    self.current_music_message_info[ctx.guild.id] = {
                        'message_id': message_sent.id,
                        'channel_id': message_sent.channel.id
                    }
                
            except Exception as e:
                logging.error(f'Failed to play song: {e}')
                await ctx.send(f'Gagal memutar lagu: {e}', ephemeral=True) # ephemeral untuk error play
                return
        else:
            await ctx.send(f"Ditambahkan ke antrian: **{len(urls)} lagu**." if is_spotify else f"Ditambahkan ke antrian: **{urls[0]}**.", ephemeral=True) # ephemeral untuk pesan antrian
            queue.extend(urls)
                
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)


    @commands.command(name="resskip")
    async def skip_cmd(self, ctx):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            return await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        ctx.voice_client.stop()
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

    # Helper baru untuk _update_music_message dari commands.Context
    async def _update_music_message_from_ctx(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.current_music_message_info:
            return

        old_message_info = self.current_music_message_info[guild_id]
        old_message_id = old_message_info['message_id']
        old_channel_id = old_message_info['channel_id']

        try:
            old_channel = ctx.guild.get_channel(old_channel_id) or await ctx.guild.fetch_channel(old_channel_id)
            if old_channel:
                old_message = await old_channel.fetch_message(old_message_id)
                await old_message.delete()
        except (discord.NotFound, discord.HTTPException) as e:
            logging.warning(f"Could not delete old music message {old_message_id} in channel {old_channel_id}: {e}")
        finally:
            del self.current_music_message_info[guild_id]

        current_embed = discord.Embed(title="Musik Berhenti 🎶")
        vc = ctx.voice_client
        if vc and vc.is_playing() and vc.source:
            source = vc.source
            current_embed = discord.Embed(
                title="🎶 Sedang Memutar",
                description=f"**[{source.title}]({source.webpage_url})**",
                color=discord.Color.purple()
            )
            if source.thumbnail:
                current_embed.set_thumbnail(url=source.thumbnail)
            duration_str = "N/A"
            if source.duration:
                minutes, seconds = divmod(source.duration, 60)
                duration_str = f"{minutes:02}:{seconds:02}"
            current_embed.add_field(name="Durasi", value=duration_str, inline=True)
            current_embed.add_field(name="Diminta oleh", value=ctx.author.mention, inline=True)
            current_embed.set_footer(text=f"Antrean: {len(self.get_queue(guild_id))} lagu tersisa")
        
        view_instance = MusicControlView(self, {'message_id': None, 'channel_id': old_channel_id})
        for item in view_instance.children:
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
                if vc and vc.source and vc.source.volume == 0.0:
                    item.emoji = "🔇"
                else:
                    item.emoji = "🔊"
            item.disabled = False
        
        new_message = await old_channel.send(embed=current_embed, view=view_instance)
        self.current_music_message_info[guild_id] = {
            'message_id': new_message.id,
            'channel_id': new_message.channel.id
        }


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

            self.queues[ctx.guild.id] = []
            self.loop_status[ctx.guild.id] = False
            
            await ctx.voice_client.disconnect()
            await ctx.send("⏹️ Stop dan keluar dari voice.", ephemeral=True)
        else:
            await ctx.send("Bot tidak ada di voice channel.", ephemeral=True)

    @commands.command(name="resqueue")
    async def queue_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            display_queue_titles = [await self.get_song_title_from_url(q) for q in queue[:15]]
            msg = "\n".join([f"{i+1}. {q}" for i, q in enumerate(display_queue_titles)])
            
            embed = discord.Embed(
                title="🎶 Antrean Lagu",
                description=f"```{msg}```",
                color=discord.Color.gold()
            )
            if len(queue) > 15:
                embed.set_footer(text=f"Dan {len(queue) - 15} lagu lainnya...")
            await ctx.send(embed=embed, ephemeral=True) # ephemeral
        else:
            await ctx.send("Antrian kosong.", ephemeral=True) # ephemeral
            
    @commands.command(name="resloop")
    async def loop_cmd(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.loop_status:
            self.loop_status[guild_id] = False
            
        self.loop_status[guild_id] = not self.loop_status[guild_id]

        status_msg = "ON" if self.loop_status[guild_id] else "OFF"
        await ctx.send(f"🔁 Mode Loop **{status_msg}** (lagu saat ini akan diulang).", ephemeral=True) # ephemeral

        if ctx.guild.id in self.current_music_message_info:
            await self._update_music_message_from_ctx(ctx)


    @commands.command(name="reslyrics")
    async def lyrics(self, ctx, *, song_name=None):
        if not self.genius:
            return await ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True) # ephemeral
            
        if song_name is None and ctx.voice_client and ctx.voice_client.is_playing():
            song_name = ctx.voice_client.source.title
        elif song_name is None:
            return await ctx.send("Tentukan nama lagu atau putar lagu terlebih dahulu untuk mencari liriknya.", ephemeral=True) # ephemeral
            
        await ctx.defer(ephemeral=True) # ephemeral defer
        await self._send_lyrics(ctx, song_name)

    # --- Command untuk Volume (Opsional, karena sudah ada tombol) ---
    @commands.command(name="resvolume")
    async def volume_cmd(self, ctx, volume: int):
        if not ctx.voice_client or not ctx.voice_client.source:
            return await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True) # ephemeral
        
        if not 0 <= volume <= 100:
            return await ctx.send("Volume harus antara 0 dan 100.", ephemeral=True) # ephemeral
            
        ctx.voice_client.source.volume = volume / 100
        await ctx.send(f"Volume diatur ke: {volume}%", ephemeral=True) # ephemeral
        if ctx.guild.id in self.current_music_message_info:
            await self._update_music_message_from_ctx(ctx)

    # --- Command untuk Shuffle (Opsional, karena sudah ada tombol) ---
    @commands.command(name="resshuffle")
    async def shuffle_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if len(queue) > 1:
            random.shuffle(queue)
            await ctx.send("🔀 Antrean lagu diacak!", ephemeral=True) # ephemeral
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)
        else:
            await ctx.send("Antrean terlalu pendek untuk diacak.", ephemeral=True) # ephemeral

    # --- Command untuk Clear Queue (Opsional, karena sudah ada tombol) ---
    @commands.command(name="resclear")
    async def clear_queue_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            self.queues[ctx.guild.id] = []
            await ctx.send("🗑️ Antrean lagu telah dikosongkan!", ephemeral=True) # ephemeral
            if ctx.guild.id in self.current_music_message_info:
                await self._update_music_message_from_ctx(ctx)
        else:
            await ctx.send("Antrean sudah kosong.", ephemeral=True) # ephemeral


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

    await bot.add_cog(Music(bot))
