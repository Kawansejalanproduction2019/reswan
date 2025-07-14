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
import time

# Konfigurasi logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

ytdl_opts = {
    'format': 'bestaudio/best',
    'cookiefile': 'cookies.txt',
    'quiet': True,
    'default_search': 'ytsearch',
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'noplaylist': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a', # Tetap m4a
        'preferredquality': '192', # Anda bisa ubah ini ke '128' atau '96' secara manual jika perlu
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

class MusicControlView(discord.ui.View):
    def __init__(self, cog_instance): # Tidak lagi menerima original_message_info
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

    # _update_music_message dihapus dari MusicControlView

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary, custom_id="music:play_pause", row=0)
    async def play_pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            button.style = discord.ButtonStyle.green
            button.emoji = "⏸️"
            await interaction.response.edit_message(view=self) # Edit view di pesan saat ini
        elif vc.is_paused():
            vc.resume()
            button.style = discord.ButtonStyle.primary
            button.emoji = "▶️"
            await interaction.response.edit_message(view=self) # Edit view di pesan saat ini
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar/dijeda.", ephemeral=True)

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, custom_id="music:skip", row=0)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop() # Ini akan memicu _after_play_handler dan play_next yang mengirim pesan baru
            await interaction.response.defer() # Defer karena akan ada pesan baru
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
            self.cog.queues.pop(interaction.guild.id, [])
            # loop_status tidak ada lagi
            self.cog.is_muted.pop(interaction.guild.id, None)
            self.cog.old_volume.pop(interaction.guild.id, None)
            # now_playing_info tidak ada lagi
            self.cog.lyrics_cooldowns.pop(interaction.guild.id, None)
            
            await interaction.response.defer() # Defer karena bot keluar
            
    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.grey, custom_id="music:queue", row=1)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.cog.get_queue(interaction.guild.id)
        if queue:
            # Kembali ke menampilkan URL mentah di antrean
            msg = "\n".join([f"{i+1}. {q}" for i, q in enumerate(queue[:10])]) 
            
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
            
    # @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.grey, custom_id="music:loop", row=1)
    # async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     pass # Tombol loop dihapus

    @discord.ui.button(emoji="📖", style=discord.ButtonStyle.blurple, custom_id="music:lyrics", row=1)
    async def lyrics_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.genius:
            await interaction.response.send_message("Fitur lirik masih beta dan akan segera dirilis nantinya.", ephemeral=True)
            return

        user_id = interaction.user.id
        guild_id = interaction.guild.id
        cooldown_time = 10 # Cooldown 10 detik

        self.cog.lyrics_cooldowns.setdefault(guild_id, {})
        last_request_time = self.cog.lyrics_cooldowns[guild_id].get(user_id, 0)
        time_since_last_request = time.time() - last_request_time

        if time_since_last_request < cooldown_time:
            remaining_cooldown = round(cooldown_time - time_since_last_request)
            cooldown_message_obj = await interaction.followup.send(
                f"Kamu sedang dalam cooldown! Coba lagi dalam {remaining_cooldown} detik.", 
                ephemeral=True
            )
            await asyncio.sleep(remaining_cooldown)
            try:
                await cooldown_message_obj.delete()
            except discord.NotFound:
                pass 
            except Exception as e:
                logging.error(f"Error deleting cooldown message: {e}")
            return

        self.cog.lyrics_cooldowns[guild_id][user_id] = time.time()

        song_name_for_lyrics = None
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing() and interaction.guild.voice_client.source:
            song_name_for_lyrics = interaction.guild.voice_client.source.title

        if not song_name_for_lyrics:
             await interaction.response.send_message("Tidak ada lagu yang sedang diputar. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
             return

        await interaction.response.defer(ephemeral=True)
        await self.cog._send_lyrics(interaction, song_name_override=song_name_for_lyrics) 

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
            self.cog.is_muted.setdefault(guild_id, False)
            self.cog.is_muted.update({guild_id: False})
            await interaction.response.defer() # Tidak ada pesan ephemeral konfirmasi
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)

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
            self.cog.is_muted.setdefault(guild_id, False)
            self.cog.is_muted.update({guild_id: new_volume == 0.0})
            await interaction.response.defer() # Tidak ada pesan ephemeral konfirmasi
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="music:mute_unmute", row=2)
    async def mute_unmute_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        guild_id = interaction.guild.id
        
        if vc and vc.source:
            is_currently_muted = self.cog.is_muted.get(guild_id, False)
            self.cog.is_muted.setdefault(guild_id, False)
            self.cog.old_volume.setdefault(guild_id, 0.8) # Default old volume

            if not is_currently_muted:
                self.cog.old_volume.update({guild_id: vc.source.volume})
                vc.source.volume = 0.0
                self.cog.is_muted.update({guild_id: True})
                button.emoji = "🔇"
                await interaction.response.edit_message(view=self)
            else:
                vc.source.volume = self.cog.old_volume.get(guild_id, 0.8)
                self.cog.is_muted.update({guild_id: False})
                button.emoji = "🔊"
                await interaction.response.edit_message(view=self)
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
            await interaction.response.defer() # Tidak ada pesan ephemeral konfirmasi
        else:
            await interaction.response.send_message("Antrean terlalu pendek untuk diacak.", ephemeral=True)

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="music:clear_queue", row=1)
    async def clear_queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        guild_id = interaction.guild.id
        queue = self.cog.get_queue(guild_id)
        if queue:
            self.cog.queues.pop(guild_id, [])
            await interaction.response.defer() # Tidak ada pesan ephemeral konfirmasi
        else:
            await interaction.response.send_message("Antrean sudah kosong.", ephemeral=True)

    # @discord.ui.button(emoji="ℹ️", style=discord.ButtonStyle.blurple, custom_id="music:np_info", row=0)
    # async def now_playing_info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     pass # Tombol NP Info dihapus

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        # self.loop_status dihapus
        # self.current_music_message_info dihapus
        self.is_muted = {}
        self.old_volume = {}
        # self.now_playing_info dihapus
        self.lyrics_cooldowns = {}
        
        GENIUS_API_TOKEN = os.getenv("GENIUS_API")
        self.genius = None
        if GENIUS_API_TOKEN:
            try:
                self.genius = Genius(GENIUS_API_TOKEN)
            except Exception as e:
                logging.warning(f"Failed to initialize Genius API: {e}")
        else:
            logging.warning("GENIUS_API_TOKEN not set in environment variables.")

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
        else:
            logging.warning("SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET not set.")

        self.bot.add_view(MusicControlView(self))

    def get_queue(self, guild_id):
        return self.queues.setdefault(guild_id, [])

    # get_song_info_from_url dihapus karena tidak lagi diperlukan untuk now_playing_info atau queue display

    async def _send_lyrics(self, interaction_or_ctx, song_name_override=None):
        if not self.genius:
            if isinstance(interaction_or_ctx, discord.Interaction):
                await interaction_or_ctx.response.send_message("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
            else:
                await interaction_or_ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.")
            return

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
        else: # Ambil dari lagu yang sedang diputar jika tidak ada override
            if interaction_or_ctx.guild.voice_client and interaction_or_ctx.guild.voice_client.is_playing() and interaction_or_ctx.guild.voice_client.source:
                source = interaction_or_ctx.guild.voice_client.source
                song_title_for_lyrics = source.title
                song_artist_for_lyrics = source.uploader # Ini akan sering jadi nama channel YouTube, kurang akurat
            else:
                if isinstance(interaction_or_ctx, discord.Interaction):
                    await interaction_or_ctx.response.send_message("Tidak ada lagu yang sedang diputar. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
                else:
                    await interaction_or_ctx.send("Tidak ada lagu yang sedang diputar. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.")
                return

        if not song_title_for_lyrics: # Pengecekan ulang jika tidak ditemukan
            if isinstance(interaction_or_ctx, discord.Interaction):
                await interaction_or_ctx.response.send_message("Tidak ada lagu yang sedang diputar atau nama lagu tidak diberikan. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
            else:
                await interaction_or_ctx.send("Tidak ada lagu yang sedang diputar atau nama lagu tidak diberikan. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.")
            return

        try:
            song = None
            if song_artist_for_lyrics:
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
                    await interaction_or_ctx.response.send_message("Lirik tidak ditemukan untuk lagu tersebut.", ephemeral=True)
                else:
                    await interaction_or_ctx.send("Lirik tidak ditemukan untuk lagu tersebut.")
        except Exception as e:
            error_message = f"Gagal mengambil lirik: {e}"
            logging.error(f"Error fetching lyrics: {e}")
            if isinstance(interaction_or_ctx, discord.Interaction):
                await interaction_or_ctx.followup.send(error_message, ephemeral=True)
            else:
                await interaction_or_ctx.send(error_message)

    async def play_next(self, ctx):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        target_channel = ctx.channel

        if not queue:
            # Pesan terakhir setelah semua lagu habis
            await target_channel.send("Antrian kosong. Keluar dari voice channel.")
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
            # Cleanup state
            self.queues.pop(guild_id, [])
            self.is_muted.pop(guild_id, None)
            self.old_volume.pop(guild_id, None)
            self.lyrics_cooldowns.pop(guild_id, None)
            return

        url = queue.pop(0)
        try:
            source = await YTDLSource.from_url(url, loop=self.bot.loop)
            ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop))
            
            # Embed "Now Playing" dengan thumbnail, durasi, dll.
            embed = discord.Embed(
                title=f"🎶 Sedang Memutar: **{source.title}**",
                url=source.webpage_url, # URL video
                color=discord.Color.blurple()
            )
            if source.thumbnail:
                embed.set_thumbnail(url=source.thumbnail)
            if source.duration:
                minutes = source.duration // 60
                seconds = source.duration % 60
                embed.add_field(name="Durasi", value=f"{minutes}:{seconds:02d}", inline=True)
            if source.uploader:
                embed.add_field(name="Diunggah oleh", value=source.uploader, inline=True)
            embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")

            await target_channel.send(embed=embed, view=MusicControlView(self))

        except Exception as e:
            logging.error(f'Failed to play song for guild {guild_id}: {e}')
            await target_channel.send(f'Gagal memutar lagu: {e}')
            asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

    async def _after_play_handler(self, ctx, error):
        guild_id = ctx.guild.id
        if error:
            logging.error(f"Player error for guild {guild_id}: {error}")
            await ctx.send(f"Terjadi error saat memutar: {error}")

        await asyncio.sleep(1) # Beri sedikit jeda

        if ctx.voice_client and ctx.voice_client.is_connected():
            await self.play_next(ctx) # Lanjut ke lagu berikutnya
        else: # Bot sudah tidak di voice channel
            logging.info(f"Bot disconnected from voice channel in guild {guild_id}. Cleaning up.")
            self.queues.pop(guild_id, [])
            self.is_muted.pop(guild_id, None)
            self.old_volume.pop(guild_id, None)
            self.lyrics_cooldowns.pop(guild_id, None)

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

        await ctx.defer() # Tetap defer untuk operasi yang mungkin lama

        urls = []
        is_spotify_link = False

        if self.spotify and ("https://open.spotify.com/track/" in query or "https://open.spotify.com/playlist/" in query or "https://open.spotify.com/album/" in query):
            is_spotify_link = True
            try:
                if "track" in query:
                    track = self.spotify.track(query)
                    search_query = f"{track['name']} {track['artists'][0]['name']}"
                    urls.append(search_query)
                elif "playlist" in query:
                    results = self.spotify.playlist_tracks(query)
                    for item in results['items']:
                        track = item['track']
                        search_query = f"{track['name']} {track['artists'][0]['name']}"
                        urls.append(search_query)
                elif "album" in query:
                    results = self.spotify.album_tracks(query)
                    for item in results['items']:
                        track = item['track']
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

        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused() and not queue:
            first_url = urls.pop(0)
            queue.extend(urls)
            try:
                source = await YTDLSource.from_url(first_url, loop=self.bot.loop)
                ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop))

                # Embed "Now Playing" dengan thumbnail, durasi, dll.
                embed = discord.Embed(
                    title=f"🎶 Sedang Memutar: **{source.title}**",
                    url=source.webpage_url, # URL video
                    color=discord.Color.blurple()
                )
                if source.thumbnail:
                    embed.set_thumbnail(url=source.thumbnail)
                if source.duration:
                    minutes = source.duration // 60
                    seconds = source.duration % 60
                    embed.add_field(name="Durasi", value=f"{minutes}:{seconds:02d}", inline=True)
                if source.uploader:
                    embed.add_field(name="Diunggah oleh", value=source.uploader, inline=True)
                embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")

                await ctx.send(embed=embed, view=MusicControlView(self))

            except Exception as e:
                logging.error(f'Failed to play song: {e}')
                await ctx.send(f'Gagal memutar lagu: {e}', ephemeral=True)
                return
        else:
            await ctx.send(f"Ditambahkan ke antrean: **{len(urls)} lagu**." if is_spotify_link else f"Ditambahkan ke antrean: **{urls[-1]}**.", ephemeral=True)
            queue.extend(urls)

    @commands.command(name="resskip")
    async def skip_cmd(self, ctx):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            return await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        ctx.voice_client.stop()
        await ctx.send("⏭️ Skip lagu.", ephemeral=True) # Tetap ephemeral untuk feedback cepat

    @commands.command(name="respause")
    async def pause_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            # Tidak ada pesan ephemeral konfirmasi, hanya bergantung pada visual tombol
        else:
            await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)

    @commands.command(name="resresume")
    async def resume_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            # Tidak ada pesan ephemeral konfirmasi, hanya bergantung pada visual tombol
        else:
            await ctx.send("Tidak ada lagu yang dijeda.", ephemeral=True)

    @commands.command(name="resstop")
    async def stop_cmd(self, ctx):
        if ctx.voice_client:
            self.queues.pop(ctx.guild.id, [])
            self.is_muted.pop(ctx.guild.id, None)
            self.old_volume.pop(ctx.guild.id, None)
            self.lyrics_cooldowns.pop(ctx.guild.id, None)
            await ctx.voice_client.disconnect()
            await ctx.send("⏹️ Stop dan keluar dari voice.", ephemeral=True) # Tetap ephemeral
        else:
            await ctx.send("Bot tidak ada di voice channel.", ephemeral=True)

    @commands.command(name="resqueue")
    async def queue_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            msg = "\n".join([f"{i+1}. {q}" for i, q in enumerate(queue[:15])])
            embed = discord.Embed(
                title="🎶 Antrean Lagu",
                description=f"```{msg}</code>",
                color=discord.Color.gold()
            )
            if len(queue) > 15:
                embed.set_footer(text=f"Dan {len(queue) - 15} lagu lainnya...")
            await ctx.send(embed=embed, ephemeral=True) # Tetap ephemeral untuk menjaga channel bersih
        else:
            await ctx.send("Antrian kosong.", ephemeral=True)

    @commands.command(name="reslyrics")
    async def lyrics(self, ctx, *, song_name=None):
        if not self.genius:
            return await ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)

        user_id = ctx.author.id
        guild_id = ctx.guild.id
        cooldown_time = 10

        self.lyrics_cooldowns.setdefault(guild_id, {})
        last_request_time = self.lyrics_cooldowns[guild_id].get(user_id, 0)
        time_since_last_request = time.time() - last_request_time

        if time_since_last_request < cooldown_time:
            remaining_cooldown = round(cooldown_time - time_since_last_request)
            cooldown_message = await ctx.send(
                f"Kamu sedang dalam cooldown! Coba lagi dalam {remaining_cooldown} detik.",
                ephemeral=True
            )
            await asyncio.sleep(remaining_cooldown)
            try:
                await cooldown_message.delete()
            except discord.NotFound:
                pass
            except Exception as e:
                logging.error(f"Error deleting cooldown message from command: {e}")
            return

        self.lyrics_cooldowns[guild_id][user_id] = time.time()

        song_name_for_lyrics = None
        if song_name is None:
            if ctx.voice_client and ctx.voice_client.is_playing() and ctx.voice_client.source:
                song_name_for_lyrics = ctx.voice_client.source.title
            else:
                return await ctx.send("Tentukan nama lagu atau putar lagu terlebih dahulu untuk mencari liriknya.", ephemeral=True)
            song_name_override = song_name_for_lyrics # Gunakan judul dari lagu diputar
        else:
            song_name_override = song_name # Gunakan song_name dari command

        await ctx.defer(ephemeral=True)
        await self._send_lyrics(ctx, song_name_override=song_name_override)

    @commands.command(name="resvolume")
    async def volume_cmd(self, ctx, volume: int):
        if not ctx.voice_client or not ctx.voice_client.source:
            return await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)

        if not 0 <= volume <= 100:
            return await ctx.send("Volume harus antara 0 dan 100.", ephemeral=True)

        ctx.voice_client.source.volume = volume / 100
        guild_id = ctx.guild.id
        self.is_muted.setdefault(guild_id, False)
        self.is_muted.update({guild_id: volume == 0})
        await ctx.send(f"Volume diatur ke: {volume}%", ephemeral=True) # Tetap ephemeral

    @commands.command(name="resshuffle")
    async def shuffle_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if len(queue) > 1:
            random.shuffle(queue)
            await ctx.send("🔀 Antrean lagu diacak!", ephemeral=True) # Tetap ephemeral
        else:
            await ctx.send("Antrean terlalu pendek untuk diacak.", ephemeral=True)

    @commands.command(name="resclear")
    async def clear_queue_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            self.queues.pop(ctx.guild.id, [])
            await ctx.send("🗑️ Antrean lagu telah dikosongkan!", ephemeral=True) # Tetap ephemeral
        else:
            await ctx.send("Antrean sudah kosong.", ephemeral=True)

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
                "url": "[https://bagibagi.co/Rh7155](https://bagibagi.co/Rh7155)"
            },
            {
                "label": "Donasi via Saweria!",
                "url": "[https://saweria.co/RH7155](https://saweria.co/RH7155)"
            },
            {
                "label": "Donasi via Sosiabuzz",
                "url": "[https://sociabuzz.com/abogoboga7155/tribe](https://sociabuzz.com/abogoboga7155/tribe)"
            }
        ]
        with open(donation_file_path, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, indent=4)
        logging.info("Created default donation_buttons.json file.")

    await bot.add_cog(Music(bot))
