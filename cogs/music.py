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
import re # Import regex

# Konfigurasi Genius API untuk lirik
GENIUS_API_TOKEN = os.getenv("GENIUS_API")
if not GENIUS_API_TOKEN:
    print("Warning: GENIUS_API_TOKEN is not set in environment variables.")
    print("Lyrics feature might not work without it.")
genius = Genius(GENIUS_API_TOKEN) if GENIUS_API_TOKEN else None

# Spotify API setup
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

spotify = None
if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    try:
        spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIPY_CLIENT_SECRET
        ))
    except Exception as e:
        print(f"Warning: Could not initialize Spotify client: {e}")
        print("Spotify features might not work.")
else:
    print("Warning: SPOTIFY_CLIENT_ID or SPOTIPY_CLIENT_SECRET not set.")
    print("Spotify features might not work without them.")

# YTDL dan FFMPEG opsi
ytdl_opts = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'cookiefile': 'cookies.txt', # Pastikan ini disiapkan jika perlu login
    'quiet': True,
    'default_search': 'ytsearch',
    'outtmpl': 'downloads/%(title)s.%(ext)s', # Pastikan folder 'downloads' ada
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
        self.url = data.get('url') # URL yang sebenarnya untuk diputar
        self.thumbnail = data.get('thumbnail')
        self.webpage_url = data.get('webpage_url') # URL halaman web (YouTube, dll.)
        self.duration = data.get('duration')
        self.uploader = data.get('uploader')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        # Menggunakan functools.partial untuk memastikan argumen dilewatkan dengan benar
        # dan menghindari pemblokiran loop event
        data = await loop.run_in_executor(None, functools.partial(ytdl.extract_info, url, download=not stream))
        
        if 'entries' in data:
            data = data['entries'][0]
        
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

# --- Class untuk Tombol Kontrol Musik ---
class MusicControlView(discord.ui.View):
    def __init__(self, cog_instance, original_message=None):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.original_message = original_message
        self._update_button_states() # Panggil saat inisialisasi awal

    def _update_button_states(self):
        vc = None
        guild_id = None
        if self.original_message and self.original_message.guild:
            vc = self.original_message.guild.voice_client
            guild_id = self.original_message.guild.id

        queue_exists = bool(self.cog.get_queue(guild_id)) if guild_id else False
        is_playing = vc and vc.is_playing()
        is_paused = vc and vc.is_paused()
        loop_on = self.cog.loop_status.get(guild_id, False) if guild_id else False

        for item in self.children:
            if item.custom_id == "music:play_pause":
                # Tombol aktif jika ada vc ATAU ada antrean
                item.disabled = not (vc and (is_playing or is_paused)) and not queue_exists
                if is_playing:
                    item.emoji = "⏸️"
                    item.style = discord.ButtonStyle.primary
                elif is_paused:
                    item.emoji = "▶️"
                    item.style = discord.ButtonStyle.green
                else:
                    item.emoji = "▶️"
                    item.style = discord.ButtonStyle.secondary # Default secondary jika tidak ada yg play/pause

            elif item.custom_id == "music:skip":
                item.disabled = not (is_playing or is_paused)

            elif item.custom_id == "music:stop":
                item.disabled = not vc

            elif item.custom_id == "music:queue":
                # Tombol antrean selalu aktif jika ada antrean atau sedang memutar
                item.disabled = not queue_exists and not (is_playing or is_paused)

            elif item.custom_id == "music:loop":
                item.disabled = not vc
                if loop_on:
                    item.style = discord.ButtonStyle.green
                else:
                    item.style = discord.ButtonStyle.grey

            elif item.custom_id == "music:lyrics":
                item.disabled = not self.cog.genius or not (is_playing or is_paused)

    async def _check_voice_channel(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            await interaction.response.send_message("Bot tidak ada di voice channel!", ephemeral=True)
            return False
        if not interaction.user.voice or interaction.user.voice.channel != interaction.guild.voice_client.channel:
            await interaction.response.send_message("Kamu harus di channel suara yang sama dengan bot!", ephemeral=True)
            return False
        return True

    async def _refresh_message(self, interaction: discord.Interaction):
        # Memperbarui pesan kontrol musik jika memungkinkan
        if self.original_message:
            try:
                self._update_button_states()
                await self.original_message.edit(view=self)
            except (discord.NotFound, discord.HTTPException) as e:
                print(f"Error updating control message after interaction: {e}")
                # Hapus referensi jika pesan hilang
                if self.original_message.guild.id in self.cog.current_music_message:
                    del self.cog.current_music_message[self.original_message.guild.id]
                if self.original_message.guild.id in self.cog.current_music_channel:
                    del self.cog.current_music_channel[self.original_message.guild.id]
        elif interaction.message: # Fallback jika original_message belum diatur tapi ada message dari interaksi
            try:
                self._update_button_states()
                await interaction.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException) as e:
                print(f"Error updating interaction message: {e}")

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary, custom_id="music:play_pause")
    async def play_pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Lagu dijeda.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Lanjut lagu.", ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar/dijeda.", ephemeral=True)
        
        await self._refresh_message(interaction)

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, custom_id="music:skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            # Cleanup ffmpeg source before stopping
            if vc.source:
                vc.source.cleanup()
            vc.stop()
            await interaction.response.send_message("⏭️ Skip lagu.", ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        
        await self._refresh_message(interaction)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music:stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc:
            self.cog.queues[interaction.guild.id] = []
            self.cog.loop_status[interaction.guild.id] = False
            
            # Nonaktifkan semua tombol di view ini sebelum bot disconnect
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self) # Edit pesan untuk menonaktifkan tombol
            
            # Clean up ffmpeg source before disconnecting
            if vc.source:
                vc.source.cleanup()
            await vc.disconnect()
            await interaction.followup.send("⏹️ Stop dan keluar dari voice.", ephemeral=True)
            
            # Hapus pesan kontrol musik lama setelah bot keluar
            if self.original_message:
                try:
                    await self.original_message.delete(delay=5)
                    if interaction.guild.id in self.cog.current_music_message:
                        del self.cog.current_music_message[interaction.guild.id]
                    if interaction.guild.id in self.cog.current_music_channel:
                        del self.cog.current_music_channel[interaction.guild.id]
                except discord.NotFound:
                    pass
                except Exception as e:
                    print(f"Error deleting original music message: {e}")
        else:
            await interaction.response.send_message("Bot tidak ada di voice channel.", ephemeral=True)
        
        # Panggil update_button_states di MusicControlView (ini akan dipanggil lagi oleh _refresh_message)
        # Tapi tidak perlu di sini karena refresh_message akan menangani
        # await self._refresh_message(interaction)

    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.grey, custom_id="music:queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.cog.get_queue(interaction.guild.id)
        if queue:
            display_queue = queue[:10]
            msg_list = []
            for i, q in enumerate(display_queue):
                # Ambil judul dari query atau link jika memungkinkan
                # Ini hanyalah representasi, yt_dlp data asli tidak disimpan di queue
                # Jadi kita asumsikan q adalah string query/URL
                if len(q) > 50: # Pangkas jika terlalu panjang
                    msg_list.append(f"{i+1}. {q[:47]}...")
                else:
                    msg_list.append(f"{i+1}. {q}")

            msg = "\n".join(msg_list)
            
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
        
        await self._refresh_message(interaction)
            
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.grey, custom_id="music:loop")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        guild_id = interaction.guild.id
        self.cog.loop_status[guild_id] = not self.cog.loop_status.get(guild_id, False)

        if self.cog.loop_status[guild_id]:
            await interaction.response.send_message("🔁 Mode Loop **ON** (lagu saat ini akan diulang).", ephemeral=True)
        else:
            await interaction.response.send_message("🔁 Mode Loop **OFF**.", ephemeral=True)
        
        await self._refresh_message(interaction)

    @discord.ui.button(emoji="📖", style=discord.ButtonStyle.blurple, custom_id="music:lyrics")
    async def lyrics_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.genius:
            await interaction.response.send_message("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
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
        
        await self._refresh_message(interaction)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {} # {guild_id: [url1, url2, ...]}
        self.loop_status = {} # {guild_id: True/False}
        self.current_music_message = {} # {guild_id: message_id} untuk pesan "Now Playing"
        self.current_music_channel = {} # {guild_id: channel_id} untuk channel tempat pesan musik berada
        self.genius = genius
        self.spotify = spotify
        self.disconnect_timers = {} # {guild_id: asyncio.Task} untuk timer auto-disconnect

        # Tambahkan view ke bot agar tetap berfungsi setelah restart
        # Penting: Saat bot restart, original_message di view akan None, 
        # tapi itu akan diatur ulang saat lagu baru diputar.
        self.bot.add_view(MusicControlView(self))

        # Buat folder downloads jika belum ada
        if not os.path.exists('downloads'):
            os.makedirs('downloads')

    def get_queue(self, guild_id):
        return self.queues.setdefault(guild_id, [])

    async def _send_lyrics(self, interaction_or_ctx, song_name):
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
            if isinstance(interaction_or_ctx, discord.Interaction):
                if interaction_or_ctx.response.is_done():
                    await interaction_or_ctx.followup.send(error_message, ephemeral=True)
                else:
                    await interaction_or_ctx.response.send_message(error_message, ephemeral=True)
            else:
                await interaction_or_ctx.send(error_message)
            print(f"Error fetching lyrics: {e}")

    async def play_next(self, guild_id):
        # Gunakan guild_id untuk mendapatkan channel dan voice client yang benar
        guild = self.bot.get_guild(guild_id)
        if not guild:
            print(f"Guild {guild_id} tidak ditemukan di play_next.")
            return

        target_channel_id = self.current_music_channel.get(guild_id)
        target_channel = guild.get_channel(target_channel_id) if target_channel_id else None

        if not target_channel:
            # Fallback ke system channel jika channel asli tidak ada/ditemukan
            target_channel = guild.system_channel or guild.text_channels[0] if guild.text_channels else None
            if not target_channel:
                print(f"Tidak ada channel teks yang ditemukan di guild {guild_id} untuk mengirim pesan play_next.")
                return

        voice_client = guild.voice_client
        queue = self.get_queue(guild_id)

        # Clear any existing disconnect timer
        if guild_id in self.disconnect_timers and not self.disconnect_timers[guild_id].done():
            self.disconnect_timers[guild_id].cancel()
            del self.disconnect_timers[guild_id]
            print(f"[{datetime.now()}] [Music Cog] Disconnect timer untuk {guild.name} dibatalkan (lagu berikutnya akan diputar).")


        if self.loop_status.get(guild_id, False) and voice_client and voice_client.source:
            # Re-add current song if looping, but ensure it's added as a searchable query for consistency
            current_song_query = voice_client.source.title 
            if voice_client.source.uploader and voice_client.source.uploader != "Unknown":
                current_song_query = f"{voice_client.source.title} {voice_client.source.uploader}"
            
            queue.insert(0, current_song_query) # Re-add the query to the front of the queue

        if not queue:
            if guild_id in self.current_music_message:
                try:
                    message_id = self.current_music_message[guild_id]
                    msg = await target_channel.fetch_message(message_id) 
                    view_instance = MusicControlView(self, original_message=msg)
                    view_instance._update_button_states() # Update buttons to disabled state
                    
                    embed = msg.embeds[0] if msg.embeds else discord.Embed()
                    embed.title = "Musik Berhenti 🎶"
                    embed.description = "Antrean kosong. Bot akan keluar dari voice channel."
                    embed.set_footer(text="")
                    embed.set_thumbnail(url=discord.Embed.Empty)
                    await msg.edit(embed=embed, view=view_instance)
                    
                    del self.current_music_message[guild_id] 
                except discord.NotFound:
                    print(f"Pesan kontrol musik tidak ditemukan di guild {guild_id} saat antrean kosong. Tidak dapat memperbarui.")
                    if guild_id in self.current_music_message:
                        del self.current_music_message[guild_id]
                except Exception as e:
                    print(f"Error updating music message on queue empty for guild {guild_id}: {e}")
            
            await target_channel.send("Antrean kosong. Keluar dari voice channel.") 
            if voice_client:
                # Clean up ffmpeg source before disconnecting
                if voice_client.source:
                    voice_client.source.cleanup()
                await voice_client.disconnect()
            
            if guild_id in self.current_music_channel:
                del self.current_music_channel[guild_id]
            return

        url_or_query = queue.pop(0)
        try:
            source = await YTDLSource.from_url(url_or_query, loop=self.bot.loop)
            voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(guild_id, e), self.bot.loop))
            
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
            # Karena ctx tidak tersedia di sini, kita tidak bisa mencantumkan author asli
            embed.add_field(name="Diminta oleh", value="Antrean otomatis", inline=True) 
            embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")

            message_sent = None
            if guild_id in self.current_music_message and guild_id in self.current_music_channel:
                try:
                    old_message = await target_channel.fetch_message(self.current_music_message[guild_id])
                    view_instance = MusicControlView(self, original_message=old_message)
                    view_instance._update_button_states()
                    await old_message.edit(embed=embed, view=view_instance)
                    message_sent = old_message
                except (discord.NotFound, discord.HTTPException):
                    print(f"Pesan musik lama tidak ditemukan atau tidak dapat diakses di guild {guild_id}. Mengirim pesan baru.")
                    message_sent = await target_channel.send(embed=embed, view=MusicControlView(self))
            else:
                message_sent = await target_channel.send(embed=embed, view=MusicControlView(self))
            
            if message_sent:
                self.current_music_message[guild_id] = message_sent.id
                self.current_music_channel[guild_id] = message_sent.channel.id 
                view_instance = MusicControlView(self, original_message=message_sent)
                view_instance._update_button_states()
                await message_sent.edit(view=view_instance)


        except Exception as e:
            await target_channel.send(f'Gagal memutar lagu: {e}')
            print(f"Error playing next song in guild {guild_id}: {e}")
            # Lanjut ke lagu berikutnya meskipun ada error
            asyncio.run_coroutine_threadsafe(self.play_next(guild_id), self.bot.loop)

    async def _after_play_handler(self, guild_id, error):
        # Dipanggil ketika lagu selesai diputar atau error
        guild = self.bot.get_guild(guild_id)
        if not guild:
            print(f"Guild {guild_id} tidak ditemukan di _after_play_handler.")
            return

        target_channel_id = self.current_music_channel.get(guild_id)
        target_channel = guild.get_channel(target_channel_id) if target_channel_id else None

        if not target_channel:
            target_channel = guild.system_channel or guild.text_channels[0] if guild.text_channels else None
            if not target_channel:
                print(f"Tidak ada channel teks yang ditemukan di guild {guild_id} untuk mengirim pesan after_play_handler.")
                return

        if error:
            print(f"Player error in guild {guild_id}: {error}")
            await target_channel.send(f"Terjadi error saat memutar lagu: {error}")
        
        # Cleanup ffmpeg source
        voice_client = guild.voice_client
        if voice_client and voice_client.source:
            voice_client.source.cleanup()
        
        # Perbarui pesan kontrol musik setelah lagu selesai atau ada error
        if guild_id in self.current_music_message and guild_id in self.current_music_channel:
            try:
                msg = await target_channel.fetch_message(self.current_music_message[guild_id])
                view_instance = MusicControlView(self, original_message=msg)
                view_instance._update_button_states() # Perbarui status tombol
                await msg.edit(view=view_instance)
            except (discord.NotFound, discord.HTTPException):
                print(f"Pesan kontrol musik tidak ditemukan atau tidak dapat diakses di guild {guild_id} setelah lagu selesai.")
                if guild_id in self.current_music_message:
                    del self.current_music_message[guild_id]
                if guild_id in self.current_music_channel:
                    del self.current_music_channel[guild_id]
            except Exception as e:
                print(f"Error updating music message in after_play_handler for guild {guild_id}: {e}")

        await asyncio.sleep(1) # Beri sedikit jeda sebelum memutar lagu berikutnya
        await self.play_next(guild_id) # Panggil play_next dengan guild_id

    @commands.command(name="resjoin")
    async def join(self, ctx):
        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                return await ctx.send("Bot sudah berada di voice channel lain. Harap keluarkan dulu.")
            return
        if ctx.author.voice:
            # Batalkan timer disconnect jika ada saat bot bergabung kembali
            if ctx.guild.id in self.disconnect_timers and not self.disconnect_timers[ctx.guild.id].done():
                self.disconnect_timers[ctx.guild.id].cancel()
                del self.disconnect_timers[ctx.guild.id]
                print(f"[{datetime.now()}] [Music Cog] Disconnect timer untuk {ctx.guild.name} dibatalkan (join manual).")

            await ctx.author.voice.channel.connect()
            await ctx.send(f"Joined **{ctx.author.voice.channel.name}**")
            self.current_music_channel[ctx.guild.id] = ctx.channel.id 
        else:
            await ctx.send("Kamu harus berada di voice channel dulu.")

    @commands.command(name="resp")
    async def play(self, ctx, *, query):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            if not ctx.voice_client:
                return await ctx.send("Gagal bergabung ke voice channel.")
        
        # Simpan channel ID saat perintah play dipanggil
        self.current_music_channel[ctx.guild.id] = ctx.channel.id 

        await ctx.defer()

        urls = []
        is_spotify = False

        # Regex yang lebih baik untuk mendeteksi URL Spotify
        spotify_track_pattern = re.compile(r'https?://open\.spotify\.com/track/([a-zA-Z0-9]+)')
        spotify_playlist_pattern = re.compile(r'https?://open\.spotify\.com/playlist/([a-zA-Z0-9]+)')
        spotify_album_pattern = re.compile(r'https?://open\.spotify\.com/album/([a-zA-Z0-9]+)')

        if spotify:
            track_match = spotify_track_pattern.search(query)
            playlist_match = spotify_playlist_pattern.search(query)
            album_match = spotify_album_pattern.search(query)

            if track_match:
                is_spotify = True
                track_id = track_match.group(1)
                try:
                    track = self.spotify.track(track_id)
                    urls.append(f"{track['name']} {track['artists'][0]['name']}")
                except Exception as e:
                    await ctx.send(f"Terjadi kesalahan saat memproses track Spotify: {e}")
                    return
            elif playlist_match:
                is_spotify = True
                playlist_id = playlist_match.group(1)
                try:
                    results = self.spotify.playlist_tracks(playlist_id)
                    for item in results['items']:
                        track = item['track']
                        if track:
                            urls.append(f"{track['name']} {track['artists'][0]['name']}")
                except Exception as e:
                    await ctx.send(f"Terjadi kesalahan saat memproses playlist Spotify: {e}")
                    return
            elif album_match:
                is_spotify = True
                album_id = album_match.group(1)
                try:
                    results = self.spotify.album_tracks(album_id)
                    for item in results['items']:
                        track = item
                        if track:
                            urls.append(f"{track['name']} {track['artists'][0]['name']}")
                except Exception as e:
                    await ctx.send(f"Terjadi kesalahan saat memproses album Spotify: {e}")
                    return
            else:
                urls.append(query) # Jika bukan link Spotify yang dikenali, anggap sebagai query biasa
        else:
            urls.append(query) # Jika Spotify tidak diinisialisasi, selalu anggap sebagai query biasa

        queue = self.get_queue(ctx.guild.id)
        
        # Batalkan timer disconnect jika ada saat ada lagu baru yang diputar/ditambahkan
        if ctx.guild.id in self.disconnect_timers and not self.disconnect_timers[ctx.guild.id].done():
            self.disconnect_timers[ctx.guild.id].cancel()
            del self.disconnect_timers[ctx.guild.id]
            print(f"[{datetime.now()}] [Music Cog] Disconnect timer untuk {ctx.guild.name} dibatalkan (lagu ditambahkan).")


        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused() and not queue:
            first_url_or_query = urls.pop(0)
            queue.extend(urls) 
            try:
                source = await YTDLSource.from_url(first_url_or_query, loop=self.bot.loop)
                # Pass only guild_id to after_play_handler
                ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx.guild.id, e), self.bot.loop))

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

                message_sent = await ctx.send(embed=embed, view=MusicControlView(self))
                self.current_music_message[ctx.guild.id] = message_sent.id
                self.current_music_channel[ctx.guild.id] = message_sent.channel.id 
                
                view_instance = MusicControlView(self, original_message=message_sent)
                view_instance._update_button_states()
                await message_sent.edit(view=view_instance)
                
            except Exception as e:
                await ctx.send(f'Gagal memutar lagu: {e}')
                print(f"Error starting first song in guild {ctx.guild.id}: {e}")
                return
        else:
            queue.extend(urls)
            if is_spotify:
                await ctx.send(f"Ditambahkan ke antrean: **{len(urls)} lagu** dari Spotify.")
            else:
                await ctx.send(f"Ditambahkan ke antrean: **{urls[0]}**.")
            
            if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
                try:
                    msg_channel = self.bot.get_channel(self.current_music_channel[ctx.guild.id])
                    if msg_channel:
                        msg = await msg_channel.fetch_message(self.current_music_message[ctx.guild.id])
                        embed = msg.embeds[0]
                        embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")
                        view_instance = MusicControlView(self, original_message=msg)
                        view_instance._update_button_states()
                        await msg.edit(embed=embed, view=view_instance)
                    else:
                        print(f"Channel {self.current_music_channel[ctx.guild.id]} not found for updating queue message.")
                except (discord.NotFound, IndexError):
                    print(f"Pesan kontrol musik atau channel tidak ditemukan untuk guild {ctx.guild.id}. Tidak dapat memperbarui footer antrean.")
                except Exception as e:
                    print(f"Error updating queue message for guild {ctx.guild.id}: {e}")

    @commands.command(name="resskip")
    async def skip_cmd(self, ctx):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            return await ctx.send("Tidak ada lagu yang sedang diputar.")
        
        # Cleanup ffmpeg source before stopping
        if ctx.voice_client.source:
            ctx.voice_client.source.cleanup()

        ctx.voice_client.stop()
        await ctx.send("⏭️ Skip lagu.")

        if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
            try:
                msg_channel = self.bot.get_channel(self.current_music_channel[ctx.guild.id])
                if msg_channel:
                    msg = await msg_channel.fetch_message(self.current_music_message[ctx.guild.id])
                    view_instance = MusicControlView(self, original_message=msg)
                    view_instance._update_button_states()
                    await msg.edit(view=view_instance)
            except (discord.NotFound, IndexError):
                pass
            except Exception as e:
                print(f"Error updating music message after skip for guild {ctx.guild.id}: {e}")

    @commands.command(name="respause")
    async def pause_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Lagu dijeda.")
            if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
                try:
                    msg_channel = self.bot.get_channel(self.current_music_channel[ctx.guild.id])
                    if msg_channel:
                        msg = await msg_channel.fetch_message(self.current_music_message[ctx.guild.id])
                        view_instance = MusicControlView(self, original_message=msg)
                        view_instance._update_button_states()
                        await msg.edit(view=view_instance)
                except (discord.NotFound, IndexError):
                    pass
                except Exception as e:
                    print(f"Error updating music message after pause for guild {ctx.guild.id}: {e}")
        else:
            await ctx.send("Tidak ada lagu yang sedang diputar.")

    @commands.command(name="resresume")
    async def resume_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Lanjut lagu.")
            if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
                try:
                    msg_channel = self.bot.get_channel(self.current_music_channel[ctx.guild.id])
                    if msg_channel:
                        msg = await msg_channel.fetch_message(self.current_music_message[ctx.guild.id])
                        view_instance = MusicControlView(self, original_message=msg)
                        view_instance._update_button_states()
                        await msg.edit(view=view_instance)
                except (discord.NotFound, IndexError):
                    pass
                except Exception as e:
                    print(f"Error updating music message after resume for guild {ctx.guild.id}: {e}")
        else:
            await ctx.send("Tidak ada lagu yang dijeda.")

    @commands.command(name="resstop")
    async def stop_cmd(self, ctx):
        if ctx.voice_client:
            self.queues[ctx.guild.id] = []
            self.loop_status[ctx.guild.id] = False
            
            if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
                try:
                    msg_channel = self.bot.get_channel(self.current_music_channel[ctx.guild.id])
                    if msg_channel:
                        msg = await msg_channel.fetch_message(self.current_music_message[ctx.guild.id])
                        view_instance = MusicControlView(self, original_message=msg)
                        for item in view_instance.children:
                            item.disabled = True
                        
                        embed = msg.embeds[0] if msg.embeds else discord.Embed()
                        embed.title = "Musik Berhenti 🎶"
                        embed.description = "Bot telah berhenti dan keluar dari voice channel."
                        embed.set_footer(text="")
                        embed.set_thumbnail(url=discord.Embed.Empty)
                        
                        await msg.edit(embed=embed, view=view_instance)
                        del self.current_music_message[ctx.guild.id]
                    else:
                        print(f"Channel {self.current_music_channel[ctx.guild.id]} not found for updating stop message.")
                except (discord.NotFound, discord.HTTPException):
                    pass
                except Exception as e:
                    print(f"Error updating music message after stop for guild {ctx.guild.id}: {e}")
            
            # Cleanup ffmpeg source before disconnecting
            if ctx.voice_client.source:
                ctx.voice_client.source.cleanup()

            await ctx.voice_client.disconnect()
            await ctx.send("⏹️ Stop dan keluar dari voice.")
            
            # Hapus referensi channel dan batalkan timer jika ada
            if ctx.guild.id in self.current_music_channel:
                del self.current_music_channel[ctx.guild.id]
            if ctx.guild.id in self.disconnect_timers and not self.disconnect_timers[ctx.guild.id].done():
                self.disconnect_timers[ctx.guild.id].cancel()
                del self.disconnect_timers[ctx.guild.id]
                print(f"[{datetime.now()}] [Music Cog] Disconnect timer untuk {ctx.guild.name} dibatalkan (stop manual).")

        else:
            await ctx.send("Bot tidak ada di voice channel.")

    @commands.command(name="resqueue")
    async def queue_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            display_queue = queue[:15]
            msg_list = []
            for i, q in enumerate(display_queue):
                if len(q) > 50:
                    msg_list.append(f"{i+1}. {q[:47]}...")
                else:
                    msg_list.append(f"{i+1}. {q}")
            msg = "\n".join(msg_list)
            
            embed = discord.Embed(
                title="🎶 Antrean Lagu",
                description=f"```{msg}```",
                color=discord.Color.gold()
            )
            if len(queue) > 15:
                embed.set_footer(text=f"Dan {len(queue) - 15} lagu lainnya...")
            await ctx.send(embed=embed)
        else:
            await ctx.send("Antrian kosong.")
        
    @commands.command(name="resloop")
    async def loop_cmd(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.loop_status:
            self.loop_status[guild_id] = False
            
        self.loop_status[guild_id] = not self.loop_status[guild_id]

        if self.loop_status[guild_id]:
            await ctx.send("🔁 Mode Loop **ON** (lagu saat ini akan diulang).")
        else:
            await ctx.send("🔁 Mode Loop **OFF**.")
        
        if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
            try:
                msg_channel = self.bot.get_channel(self.current_music_channel[ctx.guild.id])
                if msg_channel:
                    msg = await msg_channel.fetch_message(self.current_music_message[ctx.guild.id])
                    view_instance = MusicControlView(self, original_message=msg)
                    view_instance._update_button_states()
                    await msg.edit(view=view_instance)
            except (discord.NotFound, IndexError):
                pass
            except Exception as e:
                print(f"Error updating music message after loop for guild {ctx.guild.id}: {e}")


    @commands.command(name="reslyrics")
    async def lyrics(self, ctx, *, song_name=None):
        if not self.genius:
            return await ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.")
            
        if song_name is None and ctx.voice_client and ctx.voice_client.is_playing():
            song_name = ctx.voice_client.source.title
        elif song_name is None:
            return await ctx.send("Tentukan nama lagu atau putar lagu terlebih dahulu untuk mencari liriknya.")
            
        await ctx.defer()
        await self._send_lyrics(ctx, song_name)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Abaikan jika anggota adalah bot itu sendiri
        if member.id == self.bot.user.id:
            return

        guild_id = member.guild.id
        voice_client = member.guild.voice_client

        # Abaikan jika bot tidak berada di voice channel di guild ini
        if not voice_client:
            return
            
        # Cek apakah perubahan terjadi di channel tempat bot berada
        # Jika member pindah ke channel lain ATAU tidak masuk/keluar dari channel bot
        if before.channel != voice_client.channel and after.channel != voice_client.channel:
            return

        voice_channel = voice_client.channel

        # Hitung anggota non-bot yang *tidak* self-deaf atau self-mute di channel bot
        # Ini adalah cara paling akurat untuk menentukan "anggota aktif"
        human_members_in_vc = [
            m for m in voice_channel.members 
            if not m.bot and not m.voice.self_deaf and not m.voice.self_mute
        ]

        if len(human_members_in_vc) == 0:
            # Jika tidak ada anggota manusia (yang aktif), mulai atau reset timer disconnect
            if guild_id in self.disconnect_timers and not self.disconnect_timers[guild_id].done():
                self.disconnect_timers[guild_id].cancel()
                print(f"[{datetime.now()}] [Music Cog] Disconnect timer untuk {member.guild.name} dibatalkan (user keluar/masuk cepat).")

            async def disconnect_countdown():
                try:
                    await asyncio.sleep(30) # Tunggu 30 detik
                    
                    # Cek lagi apakah channel masih kosong dan bot masih di VC sebelum disconnect
                    current_human_members = [
                        m for m in voice_channel.members 
                        if not m.bot and not m.voice.self_deaf and not m.voice.self_mute
                    ]
                    if len(current_human_members) == 0 and voice_client and voice_client.is_connected():
                        # Jangan disconnect jika bot sedang memutar musik atau ada lagu di antrean
                        if voice_client.is_playing() or voice_client.is_paused() or self.get_queue(guild_id):
                            print(f"[{datetime.now()}] [Music Cog] Bot sedang memutar/menjeda/memiliki antrean di {member.guild.name}. Melewatkan auto-disconnect.")
                            # Jika ada lagu, mulai lagi timer jika lagu berhenti atau antrean habis
                            self.disconnect_timers[guild_id] = asyncio.create_task(disconnect_countdown())
                            return 

                        await voice_client.disconnect()
                        print(f"[{datetime.now()}] [Music Cog] Bot keluar dari {voice_channel.name} karena kosong.")
                        
                        # Kirim pesan ke channel yang benar yang disimpan saat join/play
                        target_channel_id = self.current_music_channel.get(guild_id)
                        text_channel = self.bot.get_channel(target_channel_id) if target_channel_id else None

                        if text_channel:
                            try:
                                await text_channel.send("Bot keluar dari voice channel karena tidak ada user aktif di dalamnya.")
                            except discord.Forbidden:
                                print(f"[{datetime.now()}] [Music Cog] Tidak punya izin mengirim pesan ke channel {target_channel_id}.")
                        elif voice_channel.guild.system_channel: # Fallback ke system channel
                            try:
                                await voice_channel.guild.system_channel.send("Bot keluar dari voice channel karena tidak ada user aktif di dalamnya.")
                            except discord.Forbidden:
                                print(f"[{datetime.now()}] [Music Cog] Tidak punya izin mengirim pesan ke system channel di guild {guild_id}.")
                        else:
                            print(f"[{datetime.now()}] [Music Cog] Tidak ada channel teks yang valid untuk mengirim pesan auto-disconnect di guild {guild_id}.")
                        
                        # Hapus state setelah disconnect
                        if guild_id in self.current_music_message:
                            del self.current_music_message[guild_id]
                        if guild_id in self.current_music_channel:
                            del self.current_music_channel[guild_id]
                            
                except asyncio.CancelledError:
                    print(f"[{datetime.now()}] [Music Cog] Disconnect countdown task for {guild_id} was cancelled.")
                except Exception as e:
                    print(f"[{datetime.now()}] [Music Cog] Error in disconnect_countdown for {guild_id}: {e}")
                finally:
                    # Hapus timer dari dictionary setelah selesai, terlepas dari apakah bot disconnect atau tidak
                    if guild_id in self.disconnect_timers:
                        del self.disconnect_timers[guild_id]

            self.disconnect_timers[guild_id] = asyncio.create_task(disconnect_countdown())
            print(f"[{datetime.now()}] [Music Cog] Disconnect timer 30 detik dimulai untuk {member.guild.name} di {voice_channel.name}.")

        elif len(human_members_in_vc) > 0:
            # Jika ada anggota manusia, batalkan timer disconnect jika ada
            if guild_id in self.disconnect_timers and not self.disconnect_timers[guild_id].done():
                self.disconnect_timers[guild_id].cancel()
                del self.disconnect_timers[guild_id]
                print(f"[{datetime.now()}] [Music Cog] Disconnect timer untuk {member.guild.name} dibatalkan (ada user masuk).")

async def setup(bot):
    await bot.add_cog(Music(bot))
