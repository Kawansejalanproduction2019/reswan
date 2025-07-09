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
from datetime import datetime # Import datetime untuk timestamp logging

# --- Helper Functions (Wajib ada di awal module untuk akses path root) ---
def load_json_from_root(file_path, default_value=None):
    """
    Memuat data JSON dari file yang berada di root direktori proyek bot.
    Menambahkan `default_value` yang lebih fleksibel.
    """
    try:
        # Menyesuaikan path agar selalu relatif ke root proyek jika cog berada di subfolder
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True) # Pastikan direktori ada
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[{datetime.now()}] [DEBUG HELPER] Peringatan: File {full_path} tidak ditemukan. Mengembalikan nilai default.")
        if default_value is not None:
            save_json_to_root(default_value, file_path) # Coba buat file dengan default
            return default_value
        # Default value untuk tipe data umum jika file tidak ditemukan
        if 'questions.json' in file_path:
            return {"questions": []}
        if 'scores.json' in file_path or 'level_data.json' in file_path or 'bank_data.json' in file_path:
            return {}
        return {} # Fallback
    except json.JSONDecodeError as e:
        print(f"[{datetime.now()}] [DEBUG HELPER] Peringatan: File {full_path} rusak (JSON tidak valid). Error: {e}. Mengembalikan nilai default.")
        if default_value is not None:
            save_json_to_root(default_value, file_path) # Coba buat ulang file dengan default jika rusak
            return default_value
        if 'questions.json' in file_path:
            return {"questions": []}
        if 'scores.json' in file_path or 'level_data.json' in file_path or 'bank_data.json' in file_path:
            return {}
        return {}


def save_json_to_root(data, file_path):
    """Menyimpan data ke file JSON di root direktori proyek."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    full_path = os.path.join(base_dir, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


# Konfigurasi Genius API untuk lirik
GENIUS_API_TOKEN = os.getenv("GENIUS_API")
# Pastikan API token sudah diatur di environment variable atau langsung di sini
if not GENIUS_API_TOKEN:
    print(f"[{datetime.now()}] [Music Cog] Warning: GENIUS_API_TOKEN is not set in environment variables. Lyrics feature might not work without it.")
genius = Genius(GENIUS_API_TOKEN) if GENIUS_API_TOKEN else None


# Spotify API setup
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

spotify = None
if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    try:
        spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET
        ))
        print(f"[{datetime.now()}] [Music Cog] Spotify client initialized successfully.")
    except Exception as e:
        print(f"[{datetime.now()}] [Music Cog] Warning: Could not initialize Spotify client: {e}. Spotify features might not work.")
else:
    print(f"[{datetime.now()}] [Music Cog] Warning: SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET not set. Spotify features might not work without them.")

# YTDL dan FFMPEG opsi
ytdl_opts = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'cookiefile': 'cookies.txt', # Menggunakan cookies.txt untuk menghindari batasan YouTube
    'quiet': True,
    'default_search': 'ytsearch',
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'noplaylist': True, # Pastikan ini tidak mengambil playlist penuh kecuali diinginkan
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
        self.uploader = data.get('uploader') # Tambahkan uploader/artis

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        print(f"[{datetime.now()}] [YTDLSource] Fetching info for URL: {url}")
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            if 'entries' in data: # Handle cases where ytdl might return a list of entries (e.g., if noplaylist isn't strict enough)
                data = data['entries'][0]
            filename = data['url'] if stream else ytdl.prepare_filename(data)
            print(f"[{datetime.now()}] [YTDLSource] Successfully extracted info for {data.get('title')}. Playing from: {filename}")
            return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)
        except Exception as e:
            print(f"[{datetime.now()}] [YTDLSource] Error extracting info or preparing audio for {url}: {e}")
            raise # Re-raise the exception to be caught by the caller

# --- Class untuk Tombol Kontrol Musik ---
class MusicControlView(discord.ui.View):
    def __init__(self, cog_instance, original_message=None):
        super().__init__(timeout=None) # Keep buttons active indefinitely
        self.cog = cog_instance
        self.original_message = original_message # Simpan referensi ke pesan agar bisa diedit nanti

    async def _check_voice_channel(self, interaction: discord.Interaction):
        # Memastikan bot ada di voice channel
        if not interaction.guild.voice_client:
            await interaction.response.send_message("Bot tidak ada di voice channel!", ephemeral=True)
            return False
        # Memastikan user berada di voice channel yang sama dengan bot
        if not interaction.user.voice or interaction.user.voice.channel != interaction.guild.voice_client.channel:
            await interaction.response.send_message("Kamu harus di channel suara yang sama dengan bot!", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary, custom_id="music:play_pause")
    async def play_pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            button.style = discord.ButtonStyle.green
            button.emoji = "⏸️"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("⏸️ Lagu dijeda.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Control] Play/Pause: Song paused in {interaction.guild.name}.")
        elif vc.is_paused():
            vc.resume()
            button.style = discord.ButtonStyle.primary
            button.emoji = "▶️"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("▶️ Lanjut lagu.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Control] Play/Pause: Song resumed in {interaction.guild.name}.")
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar/dijeda.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Control] Play/Pause: No song playing/paused in {interaction.guild.name}.")

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, custom_id="music:skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop() # Ini akan memicu after_play_handler yang memutar lagu berikutnya
            await interaction.response.send_message("⏭️ Skip lagu.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Control] Skip: Song skipped in {interaction.guild.name}.")
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Control] Skip: No song playing in {interaction.guild.name}.")

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music:stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return

        vc = interaction.guild.voice_client
        if vc:
            # Menonaktifkan semua tombol di view
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self) # Update view di pesan aslinya

            await vc.disconnect()
            self.cog.queues[interaction.guild.id] = [] # Bersihkan antrean
            self.cog.loop_status[interaction.guild.id] = False # Matikan loop
            
            # Batalkan timer disconnect jika ada saat bot di-stop manual
            if interaction.guild.id in self.cog.disconnect_timers and not self.cog.disconnect_timers[interaction.guild.id].done():
                self.cog.disconnect_timers[interaction.guild.id].cancel()
                del self.cog.disconnect_timers[interaction.guild.id]
                print(f"[{datetime.now()}] [Music Control] Stop: Disconnect timer dibatalkan saat stop manual.")

            await interaction.followup.send("⏹️ Stop dan keluar dari voice.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Control] Stop: Bot disconnected and queue cleared for {interaction.guild.name}.")
            
            # Hapus pesan kontrol musik setelah bot berhenti
            if self.original_message:
                try:
                    await self.original_message.delete(delay=5) # Hapus setelah 5 detik
                    print(f"[{datetime.now()}] [Music Control] Stop: Original music message deleted.")
                except discord.NotFound:
                    print(f"[{datetime.now()}] [Music Control] Stop: Original music message not found (maybe already deleted).")
                except Exception as e:
                    print(f"[{datetime.now()}] [Music Control] Stop: Error deleting original music message: {e}")

    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.grey, custom_id="music:queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.cog.get_queue(interaction.guild.id)
        if queue:
            display_queue = queue[:10] # Tampilkan 10 lagu pertama
            msg = "\n".join([f"{i+1}. {q}" for i, q in enumerate(display_queue)])
            
            embed = discord.Embed(
                title="🎶 Antrean Lagu",
                description=f"```{msg}```",
                color=discord.Color.gold()
            )
            if len(queue) > 10:
                embed.set_footer(text=f"Dan {len(queue) - 10} lagu lainnya...")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            print(f"[{datetime.now()}] [Music Control] Queue: Queue displayed for {interaction.guild.name}.")
        else:
            await interaction.response.send_message("Antrean kosong.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Control] Queue: Queue is empty for {interaction.guild.name}.")
            
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.grey, custom_id="music:loop")
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
            print(f"[{datetime.now()}] [Music Control] Loop: Loop mode ON for {interaction.guild.name}.")
        else:
            await interaction.response.send_message("🔁 Mode Loop **OFF**.", ephemeral=True)
            button.style = discord.ButtonStyle.grey
            print(f"[{datetime.now()}] [Music Control] Loop: Loop mode OFF for {interaction.guild.name}.")
        await interaction.message.edit(view=self) # Update tombol di pesan aslinya

    # --- Tombol Lirik Baru ---
    @discord.ui.button(emoji="📖", style=discord.ButtonStyle.blurple, custom_id="music:lyrics")
    async def lyrics_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.genius:
            await interaction.response.send_message("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Control] Lyrics: Genius API not configured.")
            return

        song_name = None
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            current_source = interaction.guild.voice_client.source
            song_name = current_source.title
            
        if song_name:
            # Defer respons agar bot tidak timeout, terutama jika pencarian lirik lama
            await interaction.response.defer(ephemeral=True) 
            print(f"[{datetime.now()}] [Music Control] Lyrics: Searching lyrics for '{song_name}'.")
            await self.cog._send_lyrics(interaction, song_name) # Panggil fungsi pengirim lirik di cog
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Control] Lyrics: No song playing to get lyrics from.")


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {} # {guild_id: [url1, url2, ...]}
        self.loop_status = {} # {guild_id: True/False}
        self.current_music_message = {} # {guild_id: message_id} untuk mengedit pesan now playing
        self.genius = genius # Gunakan objek genius yang sudah diinisialisasi
        self.spotify = spotify # Gunakan objek spotify yang sudah diinisialisasi
        self.disconnect_timers = {} # {guild_id: asyncio.Task} untuk timer auto-disconnect
        
        # Tambahkan view ke bot agar tetap berfungsi setelah restart
        # Penting: Saat bot restart, view lama mungkin tidak memiliki original_message yang valid.
        # Ini akan di-set ulang saat lagu baru diputar.
        self.bot.add_view(MusicControlView(self)) 
        print(f"[{datetime.now()}] [Music Cog] Music cog initialized.")

    def get_queue(self, guild_id):
        return self.queues.setdefault(guild_id, [])

    async def _send_lyrics(self, interaction_or_ctx, song_name):
        """
        Fungsi internal untuk mengirim lirik.
        Mencoba beberapa strategi pencarian untuk Genius API.
        """
        if not self.genius:
            # Mengirim pesan error melalui channel yang tepat
            if isinstance(interaction_or_ctx, discord.Interaction):
                if not interaction_or_ctx.response.is_done():
                    await interaction_or_ctx.response.send_message("Fitur lirik tidak aktif karena Genius API token belum diatur.", ephemeral=True)
                else:
                    await interaction_or_ctx.followup.send("Fitur lirik tidak aktif karena Genius API token belum diatur.", ephemeral=True)
            else: # commands.Context
                await interaction_or_ctx.send("Fitur lirik tidak aktif karena Genius API token belum diatur.")
            print(f"[{datetime.now()}] [Music Cog] Lyrics: Genius API not configured.")
            return

        base_query = song_name
        full_query = song_name
        
        # Ambil uploader/artist dari source yang sedang diputar jika ada
        current_source_info = None
        if isinstance(interaction_or_ctx, discord.Interaction) and interaction_or_ctx.guild.voice_client and interaction_or_ctx.guild.voice_client.is_playing():
            current_source_info = interaction_or_ctx.guild.voice_client.source
        elif isinstance(interaction_or_ctx, commands.Context) and interaction_or_ctx.voice_client and interaction_or_ctx.voice_client.is_playing():
            current_source_info = interaction_or_ctx.voice_client.source

        if current_source_info and current_source_info.uploader and current_source_info.uploader != "Unknown":
            full_query = f"{current_source_info.title} {current_source_info.uploader}"
        
        print(f"[{datetime.now()}] [Music Cog] Lyrics: Attempting to search for '{full_query}' (original: '{base_query}')")

        try:
            # Pastikan defer sudah dilakukan jika ini interaksi
            if isinstance(interaction_or_ctx, discord.Interaction) and not interaction_or_ctx.response.is_done():
                await interaction_or_ctx.response.defer(ephemeral=True)

            song = None
            # Prioritas 1: Coba cari dengan full query (judul + uploader)
            song = await asyncio.to_thread(self.genius.search_song, full_query)
            
            # Prioritas 2: Jika tidak ditemukan dan query berbeda, coba hanya dengan judul lagu
            if not song and base_query.lower() != full_query.lower():
                print(f"[{datetime.now()}] [Music Cog] Lyrics: Full query failed. Trying with base query: '{base_query}'")
                song = await asyncio.to_thread(self.genius.search_song, base_query)

            if song:
                embed = discord.Embed(
                    title=f"Lirik: {song.title} - {song.artist}",
                    color=discord.Color.dark_teal(),
                    url=song.url
                )
                if song.song_art_image_url:
                    embed.set_thumbnail(url=song.song_art_image_url)

                lyrics_parts = [song.lyrics[i:i+1900] for i in range(0, len(song.lyrics), 1900)]
                
                # Mengirim bagian pertama lirik
                embed.description = lyrics_parts[0]
                if isinstance(interaction_or_ctx, discord.Interaction):
                    message_sent_context = await interaction_or_ctx.followup.send(embed=embed, ephemeral=True)
                else: # commands.Context
                    message_sent_context = await interaction_or_ctx.send(embed=embed)

                # Mengirim sisa bagian lirik
                for part in lyrics_parts[1:]:
                    if isinstance(interaction_or_ctx, discord.Interaction):
                        await interaction_or_ctx.followup.send(part, ephemeral=True)
                    else:
                        await message_sent_context.channel.send(part) # Menggunakan channel dari pesan yang baru saja dikirim

                print(f"[{datetime.now()}] [Music Cog] Lyrics: Successfully sent lyrics for '{song.title}'.")
            else:
                # Menanggapi jika lirik tidak ditemukan
                if isinstance(interaction_or_ctx, discord.Interaction):
                    await interaction_or_ctx.followup.send("Lirik tidak ditemukan untuk lagu tersebut. Mungkin judulnya terlalu spesifik atau belum ada di database Genius.", ephemeral=True)
                else:
                    await interaction_or_ctx.send("Lirik tidak ditemukan untuk lagu tersebut. Mungkin judulnya terlalu spesifik atau belum ada di database Genius.")
                print(f"[{datetime.now()}] [Music Cog] Lyrics: No lyrics found for '{song_name}'.")

        except Exception as e:
            error_message = f"Gagal mengambil lirik: {e}"
            # Menanggapi error, pastikan tidak ada double response jika sudah di-defer
            if isinstance(interaction_or_ctx, discord.Interaction):
                if interaction_or_ctx.response.is_done():
                    await interaction_or_ctx.followup.send(error_message, ephemeral=True)
                else:
                    await interaction_or_ctx.response.send_message(error_message, ephemeral=True)
            else:
                await interaction_or_ctx.send(error_message)
            print(f"[{datetime.now()}] [Music Cog] Error fetching lyrics for '{song_name}': {e}")


    async def play_next(self, ctx):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)

        # Loop current song if loop mode is ON and there's a current song
        if self.loop_status.get(guild_id, False) and ctx.voice_client and ctx.voice_client.source:
            current_song_url = ctx.voice_client.source.data.get('webpage_url')
            if current_song_url:
                queue.insert(0, current_song_url) # Masukkan kembali lagu ke awal antrean

        if not queue:
            # Jika antrean kosong, update pesan musik terakhir dan disconnect
            if guild_id in self.current_music_message:
                try:
                    # Ambil ID pesan dari dictionary
                    message_id = self.current_music_message.pop(guild_id) 
                    # Fetch channel dan pesan menggunakan ID yang disimpan
                    # Asumsi ctx.channel adalah channel terakhir bot berinteraksi
                    channel_where_message_sent = ctx.bot.get_channel(ctx.channel.id) 
                    if channel_where_message_sent:
                        msg = await channel_where_message_sent.fetch_message(message_id)
                        view_instance = MusicControlView(self, original_message=msg)
                        for item in view_instance.children:
                            item.disabled = True # Menonaktifkan tombol
                        embed = msg.embeds[0] if msg.embeds else discord.Embed()
                        embed.title = "Musik Berhenti 🎶"
                        embed.description = "Antrean kosong. Bot akan keluar dari voice channel."
                        embed.set_footer(text="Semoga hari Anda tidak terlalu hampa.")
                        embed.set_thumbnail(url=discord.Embed.Empty) # Hapus thumbnail
                        await msg.edit(embed=embed, view=view_instance)
                except discord.NotFound:
                    print(f"[{datetime.now()}] [Music Cog] Pesan musik lama tidak ditemukan saat antrean kosong.")
                except Exception as e:
                    print(f"[{datetime.now()}] [Music Cog] Error updating music message on queue empty: {e}")

            await ctx.send("Antrean kosong. Keluar dari voice channel.")
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
            print(f"[{datetime.now()}] [Music Cog] Queue empty. Bot disconnected from {ctx.guild.name}.")
            return

        url = queue.pop(0) # Ambil lagu pertama dari antrean
        print(f"[{datetime.now()}] [Music Cog] Attempting to play next song from queue: {url}")
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

            message_sent = None
            if guild_id in self.current_music_message:
                try:
                    # Ambil ID pesan dari dictionary. Perlu diingat, ini hanya ID pesan.
                    # Asumsi pesan dikirim di channel yang sama dengan command terakhir.
                    old_message_id = self.current_music_message[guild_id]
                    # Fetch channel dari ctx.channel.id karena kemungkinan pesan "now playing" ada di sana
                    old_message_channel = ctx.bot.get_channel(ctx.channel.id) 
                    if old_message_channel:
                         old_message = await old_message_channel.fetch_message(old_message_id) # Fetch message by ID
                         view_instance = MusicControlView(self, original_message=old_message)
                         # Reset play/pause button state and enable all buttons
                         for item in view_instance.children:
                             if item.custom_id == "music:play_pause":
                                 item.emoji = "▶️"
                                 item.style = discord.ButtonStyle.primary
                             item.disabled = False
                         await old_message.edit(embed=embed, view=view_instance)
                         message_sent = old_message
                except (discord.NotFound, discord.HTTPException) as e:
                    print(f"[{datetime.now()}] [Music Cog] Old music message not found or failed to edit ({e}). Sending new one.")
                    message_sent = await ctx.send(embed=embed, view=MusicControlView(self))
            else:
                message_sent = await ctx.send(embed=embed, view=MusicControlView(self))
            
            if message_sent:
                self.current_music_message[guild_id] = message_sent.id # Simpan ID pesan "now playing"
                print(f"[{datetime.now()}] [Music Cog] Now playing message updated to {message_sent.id}.")

        except Exception as e:
            await ctx.send(f'Gagal memutar lagu: {e}', ephemeral=True)
            print(f"[{datetime.now()}] [Music Cog] Error playing song from queue: {e}")
            # Lanjutkan ke lagu berikutnya jika ada error pada lagu saat ini
            asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

    async def _after_play_handler(self, ctx, error):
        if error:
            print(f"[{datetime.now()}] [Music Cog] Player error in after_play_handler: {error}")
            await ctx.send(f"Terjadi error saat memutar: {error}", ephemeral=False) # Kirim error di channel umum
        
        # Beri sedikit jeda sebelum memutar lagu berikutnya
        await asyncio.sleep(1) 
        await self.play_next(ctx)

    @commands.command(name="resjoin")
    async def join(self, ctx):
        if ctx.voice_client: # Bot sudah di VC
            if ctx.voice_client.channel != ctx.author.voice.channel: # Tapi beda VC
                return await ctx.send("Bot sudah berada di voice channel lain. Harap keluarkan dulu atau gabung ke channel bot.", ephemeral=True)
            return await ctx.send("Bot sudah ada di voice channel ini.", ephemeral=True)
            
        if not ctx.author.voice: # User tidak di VC
            return await ctx.send("Kamu harus berada di voice channel dulu untuk memanggil bot.", ephemeral=True)

        try:
            await ctx.author.voice.channel.connect()
            await ctx.send(f"Joined **{ctx.author.voice.channel.name}**")
            print(f"[{datetime.now()}] [Music Cog] Bot joined VC {ctx.author.voice.channel.name} in {ctx.guild.name}.")
        except discord.Forbidden:
            await ctx.send("Aku tidak punya izin untuk bergabung ke voice channelmu.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Cog] Bot forbidden to join VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan saat bergabung ke voice channel: {e}", ephemeral=True)
            print(f"[{datetime.now()}] [Music Cog] Error joining VC: {e}.")

    @commands.command(name="resp")
    async def play(self, ctx, *, query):
        if not ctx.voice_client: # Jika bot belum di VC, panggil command join
            await ctx.invoke(self.join)
            if not ctx.voice_client: # Jika masih gagal join, berhenti
                return await ctx.send("Gagal bergabung ke voice channel untuk memutar lagu.", ephemeral=True)

        await ctx.defer() # Defer respons agar tidak timeout saat memproses query

        urls = []
        is_spotify = False

        # Cek apakah query adalah link Spotify
        if self.spotify and ("spotify.com/track/" in query or "spotify.com/playlist/" in query or "spotify.com/album/" in query):
            is_spotify = True
            try:
                if "track" in query:
                    track = self.spotify.track(query)
                    search_query = f"{track['name']} {track['artists'][0]['name']}"
                    urls.append(search_query)
                    print(f"[{datetime.now()}] [Music Cog] Spotify track '{track['name']}' added to queue.")
                elif "playlist" in query:
                    # Ambil semua track dari playlist
                    results = self.spotify.playlist_items(query, fields="items(track(name,artists(name)))")
                    for item in results['items']:
                        track = item['track']
                        if track: # Pastikan track tidak None (misal: lagu yang dihapus dari playlist)
                            search_query = f"{track['name']} {track['artists'][0]['name']}"
                            urls.append(search_query)
                    await ctx.send(f"Ditambahkan ke antrian: **{len(urls)} lagu** dari playlist Spotify.", ephemeral=False)
                    print(f"[{datetime.now()}] [Music Cog] Spotify playlist added: {len(urls)} songs.")
                elif "album" in query:
                    # Ambil semua track dari album
                    results = self.spotify.album_tracks(query)
                    for item in results['items']:
                        track = item
                        if track:
                            search_query = f"{track['name']} {track['artists'][0]['name']}"
                            urls.append(search_query)
                    await ctx.send(f"Ditambahkan ke antrian: **{len(urls)} lagu** dari album Spotify.", ephemeral=False)
                    print(f"[{datetime.now()}] [Music Cog] Spotify album added: {len(urls)} songs.")
                else:
                    return await ctx.send("Link Spotify tidak dikenali (hanya track, playlist, atau album).", ephemeral=True)
            except Exception as e:
                await ctx.send(f"Terjadi kesalahan saat memproses link Spotify: {e}", ephemeral=True)
                print(f"[{datetime.now()}] [Music Cog] Error processing Spotify link: {e}.")
                return

        else: # Bukan link Spotify, anggap query langsung ke YouTube
            urls.append(query)
            print(f"[{datetime.now()}] [Music Cog] YouTube query '{query}' added to queue.")

        queue = self.get_queue(ctx.guild.id)
        
        # Jika bot tidak sedang memutar lagu dan antrean kosong, putar lagu pertama langsung
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused() and not queue:
            first_url = urls.pop(0) # Ambil lagu pertama untuk diputar
            queue.extend(urls) # Sisa lagu masuk antrean
            print(f"[{datetime.now()}] [Music Cog] Starting playback of '{first_url}'.")
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

                # Edit atau kirim pesan "Now Playing"
                message_sent = None
                if ctx.guild.id in self.current_music_message:
                    try:
                        # Ambil ID pesan dari dictionary. Perlu diingat, ini hanya ID pesan.
                        # Asumsi pesan dikirim di channel yang sama dengan command terakhir.
                        old_message_id = self.current_music_message[ctx.guild.id]
                        # Fetch channel dari ctx.channel.id karena kemungkinan pesan "now playing" ada di sana
                        old_message_channel = ctx.bot.get_channel(ctx.channel.id) 
                        if old_message_channel:
                             old_message = await old_message_channel.fetch_message(old_message_id) # Fetch message by ID
                             view_instance = MusicControlView(self, original_message=old_message)
                             # Reset play/pause button state and enable all buttons
                             for item in view_instance.children:
                                 if item.custom_id == "music:play_pause":
                                     item.emoji = "▶️"
                                     item.style = discord.ButtonStyle.primary
                                 item.disabled = False
                             await old_message.edit(embed=embed, view=view_instance)
                             message_sent = old_message
                    except (discord.NotFound, discord.HTTPException) as e:
                        print(f"[{datetime.now()}] [Music Cog] Old music message not found or failed to edit ({e}). Sending new one.")
                        message_sent = await ctx.send(embed=embed, view=MusicControlView(self))
                else:
                    message_sent = await ctx.send(embed=embed, view=MusicControlView(self))
                
                if message_sent:
                    self.current_music_message[ctx.guild.id] = message_sent.id # Simpan ID pesan "now playing"
                    print(f"[{datetime.now()}] [Music Cog] Now playing message updated to {message_sent.id}.")

            except Exception as e:
                await ctx.send(f'Gagal memutar lagu: {e}', ephemeral=True)
                print(f"[{datetime.now()}] [Music Cog] Error playing first song: {e}")
                # Lanjutkan ke lagu berikutnya jika lagu pertama gagal
                asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)
                return
        else:
            # Jika bot sudah memutar lagu atau antrean tidak kosong, tambahkan ke antrean
            queue.extend(urls)
            if is_spotify:
                await ctx.send(f"Ditambahkan ke antrian: **{len(urls)} lagu** dari Spotify.", ephemeral=False)
            else:
                await ctx.send(f"Ditambahkan ke antrian: **{urls[0]}**.", ephemeral=False)
            
            # Update footer pesan now playing dengan jumlah antrean terbaru
            if ctx.guild.id in self.current_music_message:
                try:
                    msg_id_to_edit = self.current_music_message[ctx.guild.id]
                    msg_channel = ctx.bot.get_channel(ctx.channel.id) # Asumsi pesan ada di channel yang sama
                    if msg_channel:
                        msg = await msg_channel.fetch_message(msg_id_to_edit)
                        embed = msg.embeds[0]
                        embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")
                        await msg.edit(embed=embed)
                except (discord.NotFound, IndexError):
                    print(f"[{datetime.now()}] [Music Cog] Could not update footer for now playing message (not found).")
                    pass # Pesan mungkin sudah dihapus atau tidak ada embed

    @commands.command(name="resskip")
    async def skip_cmd(self, ctx):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            return await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        ctx.voice_client.stop() # Ini akan memicu after_play_handler untuk memutar lagu berikutnya
        await ctx.send("⏭️ Skip lagu.", ephemeral=False)
        print(f"[{datetime.now()}] [Music Cog] Skipped song in {ctx.guild.name}.")

    @commands.command(name="respause")
    async def pause_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Lagu dijeda.", ephemeral=False)
            print(f"[{datetime.now()}] [Music Cog] Paused song in {ctx.guild.name}.")
        else:
            await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)

    @commands.command(name="resresume")
    async def resume_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Lanjut lagu.", ephemeral=False)
            print(f"[{datetime.now()}] [Music Cog] Resumed song in {ctx.guild.name}.")
        else:
            await ctx.send("Tidak ada lagu yang dijeda.", ephemeral=True)

    @commands.command(name="resstop")
    async def stop_cmd(self, ctx):
        if ctx.voice_client:
            self.queues[ctx.guild.id] = [] # Hapus semua antrean
            self.loop_status[ctx.guild.id] = False # Matikan loop
            
            # Batalkan timer disconnect jika ada saat bot di-stop manual
            if ctx.guild.id in self.disconnect_timers and not self.disconnect_timers[ctx.guild.id].done():
                self.disconnect_timers[ctx.guild.id].cancel()
                del self.disconnect_timers[ctx.guild.id]
                print(f"[{datetime.now()}] [Music Cog] Stop: Disconnect timer dibatalkan saat stop manual.")

            # Coba edit pesan musik terakhir untuk menonaktifkan tombol dan ubah teks
            if ctx.guild.id in self.current_music_message:
                try:
                    message_id = self.current_music_message.pop(ctx.guild.id) # Hapus ID pesan setelah diambil
                    msg_channel = ctx.bot.get_channel(ctx.channel.id) # Asumsi pesan ada di channel yang sama
                    if msg_channel:
                        msg = await msg_channel.fetch_message(message_id)
                        view_instance = MusicControlView(self, original_message=msg)
                        for item in view_instance.children:
                            item.disabled = True # Menonaktifkan semua tombol
                        embed = msg.embeds[0] if msg.embeds else discord.Embed()
                        embed.title = "Musik Berhenti 🎶"
                        embed.description = "Antrean kosong. Bot keluar dari voice channel."
                        embed.set_footer(text="Semoga hari Anda tidak terlalu hampa.")
                        embed.set_thumbnail(url=discord.Embed.Empty)
                        await msg.edit(embed=embed, view=view_instance)
                except (discord.NotFound, discord.HTTPException):
                    print(f"[{datetime.now()}] [Music Cog] Old music message not found or failed to edit on stop.")
                    pass

            await ctx.voice_client.disconnect()
            await ctx.send("⏹️ Stop dan keluar dari voice.", ephemeral=False)
            print(f"[{datetime.now()}] [Music Cog] Bot stopped and disconnected from {ctx.guild.name}.")
        else:
            await ctx.send("Bot tidak ada di voice channel.", ephemeral=True)

    @commands.command(name="resqueue")
    async def queue_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            display_queue = queue[:15] # Tampilkan 15 lagu pertama
            msg = "\n".join([f"{i+1}. {q}" for i, q in enumerate(display_queue)])
            
            embed = discord.Embed(
                title="🎶 Antrean Lagu",
                description=f"```{msg}```",
                color=discord.Color.gold()
            )
            if len(queue) > 15:
                embed.set_footer(text=f"Dan {len(queue) - 15} lagu lainnya...")
            await ctx.send(embed=embed)
            print(f"[{datetime.now()}] [Music Cog] Queue displayed for {ctx.guild.name}.")
        else:
            await ctx.send("Antrean kosong.", ephemeral=True)
            print(f"[{datetime.now()}] [Music Cog] Queue is empty for {ctx.guild.name}.")
            
    @commands.command(name="resloop")
    async def loop_cmd(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.loop_status:
            self.loop_status[guild_id] = False
        
        self.loop_status[guild_id] = not self.loop_status[guild_id]

        if self.loop_status[guild_id]:
            await ctx.send("🔁 Mode Loop **ON** (lagu saat ini akan diulang).", ephemeral=False)
            print(f"[{datetime.now()}] [Music Cog] Loop mode ON for {ctx.guild.name}.")
        else:
            await ctx.send("🔁 Mode Loop **OFF**.", ephemeral=False)
            print(f"[{datetime.now()}] [Music Cog] Loop mode OFF for {ctx.guild.name}.")

        # Coba update tombol di pesan now playing
        if ctx.guild.id in self.current_music_message:
            try:
                msg_id = self.current_music_message[ctx.guild.id]
                msg_channel = ctx.bot.get_channel(ctx.channel.id) # Asumsi pesan di channel yang sama
                if msg_channel:
                    msg = await msg_channel.fetch_message(msg_id)
                    view_instance = MusicControlView(self, original_message=msg) # Re-instantiate view to update button style
                    for item in view_instance.children:
                        if item.custom_id == "music:loop":
                            item.style = discord.ButtonStyle.green if self.loop_status[guild_id] else discord.ButtonStyle.grey
                            break
                    await msg.edit(view=view_instance)
            except (discord.NotFound, IndexError):
                print(f"[{datetime.now()}] [Music Cog] Failed to update loop button on now playing message (not found).")
                pass

    @commands.command(name="reslyrics")
    async def lyrics(self, ctx, *, song_name=None):
        if not self.genius:
            return await ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
            
        if song_name is None and ctx.voice_client and ctx.voice_client.is_playing():
            song_name = ctx.voice_client.source.title
        elif song_name is None:
            return await ctx.send("Tentukan nama lagu atau putar lagu terlebih dahulu untuk mencari liriknya.", ephemeral=True)
            
        await ctx.defer() # Defer respons untuk perintah command agar tidak timeout
        print(f"[{datetime.now()}] [Music Cog] Lyrics command: Searching for '{song_name}'.")
        await self._send_lyrics(ctx, song_name)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Abaikan jika anggota adalah bot itu sendiri
        if member.id == self.bot.user.id:
            return

        # Abaikan jika bot tidak berada di voice channel di guild ini
        if not member.guild.voice_client:
            return
            
        voice_client = member.guild.voice_client
        
        # Cek apakah perubahan terjadi di channel tempat bot berada
        if before.channel != voice_client.channel and after.channel != voice_client.channel:
            return # Perubahan terjadi di channel lain yang tidak relevan dengan bot

        voice_channel = voice_client.channel
        guild_id = member.guild.id

        # Hitung anggota non-bot di channel bot (hanya mereka yang tidak mute/deafen diri sendiri)
        human_members_in_vc = [m for m in voice_channel.members if not m.bot and not m.voice.self_deaf and not m.voice.self_mute]

        if len(human_members_in_vc) == 0:
            # Jika tidak ada anggota manusia (yang aktif), mulai atau reset timer disconnect
            if guild_id in self.disconnect_timers and not self.disconnect_timers[guild_id].done():
                self.disconnect_timers[guild_id].cancel()
                print(f"[{datetime.now()}] [Music Cog] Disconnect timer untuk {member.guild.name} dibatalkan (user keluar/masuk cepat).")

            async def disconnect_countdown():
                await asyncio.sleep(30) # Tunggu 30 detik
                # Cek lagi apakah channel masih kosong dan bot masih di VC sebelum disconnect
                current_human_members = [m for m in voice_channel.members if not m.bot and not m.voice.self_deaf and not m.voice.self_mute]
                if len(current_human_members) == 0 and voice_client and voice_client.is_connected():
                    await voice_client.disconnect()
                    self.queues.pop(guild_id, None) # Bersihkan antrean
                    self.loop_status.pop(guild_id, None) # Matikan loop
                    
                    # Coba edit pesan musik terakhir jika ada dan masih bisa diakses
                    if guild_id in self.current_music_message:
                        try:
                            # message_id yang disimpan di self.current_music_message[guild_id] adalah ID dari object pesan, bukan object pesan itu sendiri.
                            # Kita butuh channel ID untuk fetch_message.
                            # Asumsi pesan dikirim di channel teks yang sama dengan ctx.channel
                            # Agar lebih robust, saat menyimpan self.current_music_message, simpan tuple (message.id, message.channel.id)
                            # Untuk saat ini, kita akan mencoba fetch channel dari guild text channels.
                            
                            message_id_to_pop = self.current_music_message.pop(guild_id) # Ambil dan hapus ID pesan
                            
                            # Cari channel teks tempat pesan itu dikirim
                            target_text_channel = None
                            for tc in voice_channel.guild.text_channels:
                                try:
                                    # Coba fetch pesan di setiap channel teks, ini tidak efisien tapi bisa jadi fallback
                                    # Lebih baik: simpan channel_id di self.current_music_message[guild_id] = (message.id, message.channel.id)
                                    test_msg = await tc.fetch_message(message_id_to_pop)
                                    target_text_channel = tc
                                    break
                                except discord.NotFound:
                                    continue
                                except Exception:
                                    continue # Skip channel if issue fetching
                            
                            if target_text_channel:
                                msg = await target_text_channel.fetch_message(message_id_to_pop)
                                view_instance = MusicControlView(self, original_message=msg)
                                for item in view_instance.children:
                                    item.disabled = True
                                embed = msg.embeds[0] if msg.embeds else discord.Embed()
                                embed.title = "Musik Berhenti 🎶"
                                embed.description = "Bot keluar dari voice channel karena tidak ada user di sini."
                                embed.set_footer(text="Semoga hari Anda tidak terlalu hampa.")
                                embed.set_thumbnail(url=discord.Embed.Empty)
                                await msg.edit(embed=embed, view=view_instance)
                            else:
                                print(f"[{datetime.now()}] [Music Cog] Tidak dapat menemukan channel teks untuk pesan musik ID {message_id_to_pop} saat auto-disconnect.")
                        except discord.NotFound:
                            print(f"[{datetime.now()}] [Music Cog] Pesan musik lama tidak ditemukan saat auto-disconnect.")
                        except Exception as e:
                            print(f"[{datetime.now()}] [Music Cog] Error updating music message on auto-disconnect: {e}")

                    print(f"[{datetime.now()}] [Music Cog] Bot keluar dari {voice_channel.name} karena kosong.")
                
                # Hapus timer setelah selesai, terlepas dari apakah bot disconnect atau tidak
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
