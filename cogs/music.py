import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os
import functools
import re # Import re untuk regex
from discord import FFmpegPCMAudio
from discord.utils import get
from lyricsgenius import Genius
from datetime import datetime # Import datetime untuk timestamp logging
import spotipy
from spotipy.oauth2 import SpotifyClientClientCredentials
from collections import deque # Import deque untuk antrean lebih efisien

# --- Helper Functions (Asumsi ini diimpor dari main.py atau utils.py) ---
# Jika Anda tidak memiliki fungsi ini secara global, Anda harus menyertakan definisinya
# di bagian atas file ini atau di file utility terpisah (misal: utils.py)
# Contoh import jika di utils.py: from utils import load_json_from_root, save_json_to_root

# Untuk tujuan Music.py ini, kita akan sertakan definisi helper di sini
# untuk memastikan file ini berjalan mandiri, namun catat bahwa idealnya mereka global.
def load_json_from_root(file_path, default_value=None):
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[{datetime.now()}] [HELPER WARNING] File {full_path} not found. Returning default.")
        if default_value is not None:
            return default_value
        return {} # Default for general JSON
    except json.JSONDecodeError as e:
        print(f"[{datetime.now()}] [HELPER ERROR] File {full_path} corrupted: {e}. Returning default.")
        if default_value is not None:
            return default_value
        return {} # Fallback

def save_json_to_root(data, file_path):
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[{datetime.now()}] [HELPER ERROR] Error saving {full_path}: {e}")


# Konfigurasi Genius API untuk lirik
GENIUS_API_TOKEN = os.getenv("GENIUS_API")
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
            self.cog.queues[interaction.guild.id] = deque() # Bersihkan antrean
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
            # Pastikan item di queue adalah string atau memiliki atribut yang bisa diakses
            display_queue_items = []
            for i, item in enumerate(list(queue)[:10]):
                if isinstance(item, dict) and 'title' in item and 'original_url' in item:
                    display_queue_items.append(f"{i+1}. [{item['title']}]({item['original_url']})")
                elif isinstance(item, str): # Fallback jika item hanya string URL
                    display_queue_items.append(f"{i+1}. {item}")
                else:
                    display_queue_items.append(f"{i+1}. Unknown Song")

            msg = "\n".join(display_queue_items)
            
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
            await interaction.response.send_message("🔁 Mode Loop **ON** (lagu saat ini akan diulang).", ephemeral=False)
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
        self.queues = {} # {guild_id: deque()} for storing Player objects
        self.loop_status = {} # {guild_id: True/False}
        self.current_music_message = {} # {guild_id: message_id} untuk mengedit pesan now playing
        self.genius = genius # Gunakan objek genius yang sudah diinisialisasi
        self.spotify = spotify # Gunakan objek spotify yang sudah diinisialisasi
        self.disconnect_timers = {} # {guild_id: asyncio.Task} untuk timer auto-disconnect
        self.now_playing_info = {} # {guild_id: {"title": str, "url": str, "requester_id": int}}

        # Tambahkan view ke bot agar tetap berfungsi setelah restart
        # Penting: Saat bot restart, view lama mungkin tidak memiliki original_message yang valid.
        # Ini akan di-set ulang saat lagu baru diputar.
        self.bot.add_view(MusicControlView(self)) 
        print(f"[{datetime.now()}] [Music Cog] Music cog initialized.")
        self.load_state() # Memuat state saat inisialisasi cog

    # --- Metode untuk menyimpan dan memuat state ---
    def save_state(self):
        """Menyimpan state bot musik (antrean, info lagu saat ini) ke file JSON."""
        state_to_save = {}
        for guild_id, queue_deque in self.queues.items():
            state_to_save[str(guild_id)] = {
                "queue": list(queue_deque), # Ubah deque ke list untuk JSON serialisasi
                "loop_status": self.loop_status.get(guild_id, False),
                "now_playing_info": self.now_playing_info.get(guild_id)
                # current_music_message tidak perlu disimpan di sini, akan direkonstruksi atau diganti
            }
        save_json_to_root("data/music_state.json", state_to_save)
        print(f"[{datetime.now()}] [Music Cog] State saved.")

    def load_state(self):
        """Memuat state bot musik dari file JSON."""
        loaded_state = load_json_from_root("data/music_state.json", default_value={})
        for guild_id_str, guild_state_data in loaded_state.items():
            guild_id = int(guild_id_str)
            self.queues[guild_id] = deque(guild_state_data.get("queue", []))
            self.loop_status[guild_id] = guild_state_data.get("loop_status", False)
            self.now_playing_info[guild_id] = guild_state_data.get("now_playing_info", {})
            # current_music_message tidak dimuat di sini, akan di-set saat pesan dikirim/diperbarui
        print(f"[{datetime.now()}] [Music Cog] State loaded.")

    def get_queue(self, guild_id):
        # Menggunakan deque untuk efisiensi popleft() dan append()
        if guild_id not in self.queues:
            self.queues[guild_id] = deque()
        return self.queues[guild_id]

    async def _send_lyrics(self, interaction_or_ctx, song_name):
        """
        Fungsi internal untuk mengirim lirik.
        Mencoba beberapa strategi pencarian untuk Genius API.
        """
        if not self.genius:
            # Mengirim pesan error melalui channel yang tepat
            if isinstance(interaction_or_ctx, discord.Interaction):
                if not interaction_or_ctx.response.is_done():
                    await interaction_or_ctx.response.send_message("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
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

        # Pastikan bot masih terhubung ke voice channel sebelum mencoba memutar lagu
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            print(f"[{datetime.now()}] [Music Cog] play_next: Voice client is not connected for guild {guild_id}. Attempting cleanup.")
            # Lakukan cleanup penuh jika voice client tidak valid
            if guild_id in self.queues:
                self.queues[guild_id].clear()
            if guild_id in self.loop_status:
                self.loop_status.pop(guild_id, None)
            
            if guild_id in self.disconnect_timers and not self.disconnect_timers[guild_id].done():
                self.disconnect_timers[guild_id].cancel()
                del self.disconnect_timers[guild_id]
                print(f"[{datetime.now()}] [Music Cog] play_next: Disconnect timer dibatalkan saat voice client hilang.")

            if ctx.voice_client and ctx.voice_client.is_connected():
                await ctx.voice_client.disconnect()

            # Pastikan pesan now playing diupdate ke "berhenti"
            if guild_id in self.current_music_message:
                try:
                    message_id = self.current_music_message.pop(guild_id) 
                    target_text_channel = ctx.bot.get_channel(ctx.channel.id) 
                    if not target_text_channel: 
                        target_text_channel = ctx.guild.system_channel or ctx.guild.text_channels[0]
                    
                    if target_text_channel:
                        msg = await target_text_channel.fetch_message(message_id)
                        view_instance = MusicControlView(self, original_message=msg)
                        for item in view_instance.children:
                            item.disabled = True
                        embed = msg.embeds[0] if msg.embeds else discord.Embed()
                        embed.title = "Musik Berhenti 🎶"
                        embed.description = "Antrean kosong. Bot keluar dari voice channel karena koneksi terputus."
                        embed.set_footer(text="Semoga hari Anda tidak terlalu hampa.")
                        embed.set_thumbnail(url=discord.Embed.Empty)
                        await msg.edit(embed=embed, view=view_instance)
                except discord.NotFound:
                    print(f"[{datetime.now()}] [Music Cog] Pesan musik lama tidak ditemukan saat voice client hilang.")
                except Exception as e:
                    print(f"[{datetime.now()}] [Music Cog] Error updating music message when voice client lost: {e}")
            self.now_playing_info.pop(guild_id, None) # Clear now_playing_info
            self.save_state() # Simpan state setelah cleanup
            return # Keluar dari play_next

        # Loop current song if loop mode is ON and there's a current song
        if self.loop_status.get(guild_id, False) and ctx.voice_client and ctx.voice_client.source:
            current_song_url = ctx.voice_client.source.data.get('webpage_url')
            if current_song_url:
                # Pastikan menyimpan info lengkap untuk looping
                current_song_data = self.now_playing_info.get(guild_id) # Ambil info lagu yang sedang diputar
                if current_song_data:
                    queue.appendleft(current_song_data) # Memutar ulang, tambahkan ke depan deque
                else:
                    # Fallback jika now_playing_info tidak ada (jarang, tapi jaga-jaga)
                    queue.appendleft({'url': current_song_url, 'title': 'Unknown Title (Loop)', 'original_url': current_song_url, 'requester_id': self.bot.user.id})

        if not queue:
            # Jika antrean kosong, update pesan musik terakhir dan disconnect (ini case normal queue habis)
            if guild_id in self.current_music_message:
                try:
                    message_id = self.current_music_message.pop(guild_id) 
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
                        embed.set_thumbnail(url=discord.Embed.Empty)
                        await msg.edit(embed=embed, view=view_instance)
                except discord.NotFound:
                    print(f"[{datetime.now()}] [Music Cog] Pesan musik lama tidak ditemukan saat antrean kosong (normal end).")
                except Exception as e:
                    print(f"[{datetime.now()}] [Music Cog] Error updating music message on queue empty (normal end): {e}")

            await ctx.send("Antrean kosong. Keluar dari voice channel.")
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
            print(f"[{datetime.now()}] [Music Cog] Queue empty. Bot disconnected from {ctx.guild.name}.")
            self.now_playing_info.pop(guild_id, None) # Clear now_playing_info
            self.save_state() # Simpan state setelah cleanup
            return

        song_info = queue.popleft() # Ambil lagu pertama dari antrean
        print(f"[{datetime.now()}] [Music Cog] Attempting to play next song from queue: {song_info['title']}")
        try:
            player_source = await YTDLSource.from_url(song_info['url'], loop=self.bot.loop)
            ctx.voice_client.play(player_source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop))
            
            embed = discord.Embed(
                title="🎶 Sedang Memutar",
                description=f"**[{player_source.title}]({player_source.webpage_url})**",
                color=discord.Color.purple()
            )
            if player_source.thumbnail:
                embed.set_thumbnail(url=player_source.thumbnail)
            
            duration_str = "N/A"
            if player_source.duration:
                minutes, seconds = divmod(player_source.duration, 60)
                duration_str = f"{minutes:02}:{seconds:02}"
            embed.add_field(name="Durasi", value=duration_str, inline=True)
            
            # Mendapatkan objek requester dari ID yang disimpan
            requester_member = ctx.guild.get_member(song_info['requester_id']) 
            requester_mention = requester_member.mention if requester_member else f"Pengguna tidak dikenal (<@{song_info['requester_id']}>)"
            embed.add_field(name="Diminta oleh", value=requester_mention, inline=True)
            embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")

            message_sent = None
            # Pastikan ctx.channel ada dan valid sebelum mencoba fetch_message
            if ctx.channel and ctx.guild.id in self.current_music_message:
                try:
                    old_message_id = self.current_music_message[guild_id]
                    old_message = await ctx.channel.fetch_message(old_message_id) # Fetch message by ID
                    
                    view_instance = MusicControlView(self, original_message=old_message)
                    for item in view_instance.children:
                        if item.custom_id == "music:play_pause":
                            item.emoji = "▶️"
                            item.style = discord.ButtonStyle.primary
                        item.disabled = False
                    await old_message.edit(embed=embed, view=view_instance)
                    message_sent = old_message
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    print(f"[{datetime.now()}] [Music Cog] Error updating/fetching old music message ({e}). Sending new one if possible.")
                    try:
                        message_sent = await ctx.send(embed=embed, view=MusicControlView(self))
                    except Exception as new_e:
                        print(f"[{datetime.now()}] [Music Cog] FATAL: Also failed to send NEW music message: {new_e}")
                        pass # Biarkan saja, jangan sampai crash
            else: # Jika tidak ada pesan lama atau ctx.channel tidak valid, kirim pesan baru
                try:
                    message_sent = await ctx.send(embed=embed, view=MusicControlView(self))
                except Exception as new_e:
                    print(f"[{datetime.now()}] [Music Cog] FATAL: Could not send NEW music message: {new_e}")
                    pass # Tidak bisa mengirim pesan sama sekali

            if message_sent:
                self.current_music_message[guild_id] = message_sent.id # Simpan ID pesan "now playing"
                print(f"[{datetime.now()}] [Music Cog] Now playing message updated to {message_sent.id}.")
            else:
                print(f"[{datetime.now()}] [Music Cog] WARNING: No now playing message could be sent or updated.")

            # Update now_playing_info setelah lagu berhasil diputar
            self.now_playing_info[guild_id] = {
                'title': player_source.title,
                'url': player_source.webpage_url,
                'requester_id': song_info['requester_id']
            }
            self.save_state() # Simpan state setelah lagu berhasil diputar

        except Exception as e:
            await ctx.send(f'Gagal memutar lagu: {e}', ephemeral=True)
            print(f"[{datetime.now()}] [Music Cog] Error playing song from queue: {e}")
            # Lanjutkan ke lagu berikutnya jika ada error pada lagu saat ini
            asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop)
            return # Keluar dari play_next() setelah error

    async def _after_play_handler(self, ctx, error):
        guild_id = ctx.guild.id # Definisikan guild_id di sini
        if error:
            print(f"[{datetime.now()}] [Music Cog] Player error in after_play_handler for guild {guild_id}: {error}")
            # Coba kirim pesan error ke channel yang benar
            try:
                # Dapatkan channel tempat pesan now playing terakhir dikirim
                # Gunakan ctx.channel.id sebagai fallback jika current_music_message belum ada (misal error di lagu pertama)
                channel_id_for_error_msg, _ = self.current_music_message.get(guild_id, (ctx.channel.id, None))
                target_channel = self.bot.get_channel(channel_id_for_error_msg)
                if target_channel:
                    await target_channel.send(f"❌ Terjadi error saat memutar lagu di voice channel: {error}", ephemeral=False)
            except Exception as msg_e:
                print(f"[{datetime.now()}] [Music Cog] Could not send error message to Discord channel: {msg_e}")
            
            # Clear current song info and message references
            self.current_music_message.pop(guild_id, None)
            self.now_playing_info.pop(guild_id, None)
            
            # Jika antrean tidak kosong, pop lagu yang error agar tidak terulang
            if guild_id in self.queues and self.queues[guild_id]:
                self.queues[guild_id].popleft() 
            
            # Coba simpan state jika ada perubahan
            try:
                self.save_state()
            except Exception as e:
                print(f"[{datetime.now()}] [Music Cog] Error saving state after error: {e}")

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
            if not ctx.voice_client: # Jika join gagal
                return await ctx.send("Gagal bergabung ke voice channel untuk memutar lagu.", ephemeral=True)

        await ctx.defer() # Defer respons agar tidak timeout saat memproses query

        urls = []
        is_spotify = False

        # Perbaiki deteksi link Spotify agar lebih universal (tidak hanya googleusercontent)
        spotify_pattern = re.compile(r"(https?://open\.spotify\.com/(track|playlist|album)/[a-zA-Z0-9]+)")
        spotify_match = spotify_pattern.search(query)

        if self.spotify and spotify_match:
            is_spotify = True
            spotify_link_type = spotify_match.group(2) # 'track', 'playlist', or 'album'
            spotify_id = spotify_match.group(0) # The full link
            
            try:
                if spotify_link_type == "track":
                    track = self.spotify.track(spotify_id)
                    search_query = f"{track['name']} {track['artists'][0]['name']}"
                    urls.append(search_query)
                    print(f"[{datetime.now()}] [Music Cog] Spotify track '{track['name']}' added to queue.")
                elif spotify_link_type == "playlist":
                    results = self.spotify.playlist_items(spotify_id, fields="items(track(name,artists(name)))")
                    for item in results['items']:
                        track = item['track']
                        if track: 
                            search_query = f"{track['name']} {track['artists'][0]['name']}"
                            urls.append(search_query)
                    await ctx.send(f"Ditambahkan ke antrian: **{len(urls)} lagu** dari playlist Spotify.", ephemeral=False)
                    print(f"[{datetime.now()}] [Music Cog] Spotify playlist added: {len(urls)} songs.")
                elif spotify_link_type == "album":
                    results = self.spotify.album_tracks(spotify_id)
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
            for url_item in urls: # Pastikan menyimpan semua info yang relevan
                # Ini akan menjadi dict, bukan hanya string URL
                self.queues[ctx.guild.id].append({
                    'url': url_item,
                    'title': 'Unknown Title', # Placeholder
                    'original_url': url_item, # Placeholder
                    'requester_id': ctx.author.id
                })
            self.save_state() # Simpan state setelah menambahkan ke queue

            print(f"[{datetime.now()}] [Music Cog] Starting playback of '{first_url}'.")
            try:
                # Dapatkan info lagu lengkap untuk lagu pertama
                song_info = await YTDLSource.from_url(first_url, loop=self.bot.loop)
                ctx.voice_client.play(song_info, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop)) # Menggunakan song_info langsung
                
                self.now_playing_info[ctx.guild.id] = {
                    'title': song_info.title,
                    'url': song_info.webpage_url,
                    'requester_id': ctx.author.id
                }
                await self.update_now_playing_message(ctx, song_info.title, song_info.webpage_url, ctx.author.id)

            except Exception as e:
                await ctx.send(f'Gagal memutar lagu: {e}', ephemeral=True)
                print(f"[{datetime.now()}] [Music Cog] Error playing first song: {e}")
                # Lanjutkan ke lagu berikutnya jika lagu pertama gagal
                asyncio.run_coroutine_threadsafe(self._after_play_handler(ctx, e), self.bot.loop)
                return # Keluar dari play() setelah error

        else:
            # Jika bot sudah memutar lagu atau antrean tidak kosong, tambahkan ke antrean
            for url_item in urls:
                self.queues[ctx.guild.id].append({
                    'url': url_item,
                    'title': 'Unknown Title', # Placeholder
                    'original_url': url_item, # Placeholder
                    'requester_id': ctx.author.id
                })
            self.save_state()

            if is_spotify:
                await ctx.send(f"Ditambahkan ke antrian: **{len(urls)} lagu** dari Spotify.", ephemeral=False)
            else:
                await ctx.send(f"Ditambahkan ke antrian: **{urls[0]}**.", ephemeral=False) # ini akan menampilkan URL/query mentah
            
            # Update footer pesan now playing dengan jumlah antrean terbaru
            if ctx.guild.id in self.current_music_message:
                try:
                    msg_channel_id, msg_id = self.current_music_message[ctx.guild.id]
                    msg_channel = ctx.bot.get_channel(msg_channel_id) # Ambil channel tempat pesan dipost
                    if msg_channel:
                        msg = await msg_channel.fetch_message(msg_id)
                        view_instance = MusicControlView(self, original_message=msg)
                        for item in view_instance.children:
                            if item.custom_id == "music:play_pause":
                                item.emoji = "▶️"
                                item.style = discord.ButtonStyle.primary
                            item.disabled = False
                        await msg.edit(view=view_instance)
                except (discord.NotFound, IndexError, KeyError):
                    print(f"[{datetime.now()}] [Music Cog] Could not update footer for now playing message (not found or invalid state).")
                    pass # Pesan mungkin sudah dihapus atau tidak ada embed

    @commands.command(name="resskip")
    async def skip_cmd(self, ctx):
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            return await ctx.send("❌ Tidak ada lagu yang sedang diputar.", ephemeral=True)
        
        if not ctx.voice_client.is_playing():
            return await ctx.send("❌ Tidak ada lagu yang sedang diputar untuk dilewati.", ephemeral=True)

        ctx.voice_client.stop()
        await ctx.send("✅ Lagu dilewati.")
        print(f"[{datetime.now()}] [Music Cog] Skipped song in {ctx.guild.name}.")

    @commands.command(name="resstop")
    async def stop_cmd(self, ctx):
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            return await ctx.send("❌ Aku tidak terhubung ke voice channel.", ephemeral=True)

        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            ctx.voice_client.stop()
        
        guild_id = ctx.guild.id
        self.queues[guild_id].clear()
        self.loop_status.pop(guild_id, None)
        self.now_playing_info.pop(guild_id, None)
        self.current_music_message.pop(guild_id, None) # Clear current_music_message
        self.save_state() # Save state after clear and stop
        await ctx.send("✅ Pemutaran dihentikan dan antrean dikosongkan.")
        log.info(f"Playback stopped and queue cleared in guild {guild_id}.")

        try:
            await ctx.voice_client.disconnect()
            log.info(f"Bot disconnected from voice channel in guild {guild_id}.")
        except Exception as e:
            log.error(f"Error disconnecting from voice channel in guild {guild_id}: {e}")

    @commands.command(name="respause")
    async def pause_cmd(self, ctx):
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            return await ctx.send("❌ Aku tidak terhubung ke voice channel.", ephemeral=True)

        if ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Lagu dijeda.")
            log.info(f"Song paused in guild {ctx.guild.id}.")
        else:
            await ctx.send("❌ Tidak ada lagu yang sedang diputar untuk dijeda.", ephemeral=True)

    @commands.command(name="resresume")
    async def resume_cmd(self, ctx):
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            return await ctx.send("❌ Aku tidak terhubung ke voice channel.", ephemeral=True)

        if ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Lagu dilanjutkan.")
            log.info(f"Song resumed in guild {ctx.guild.id}.")
        else:
            await ctx.send("❌ Tidak ada lagu yang dijeda untuk dilanjutkan.", ephemeral=True)

    @commands.command(name="resqueue", aliases=["q"])
    async def queue_cmd(self, ctx):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id) # Pastikan memanggil get_queue
        if not queue: # Perbaiki pengecekan queue
            return await ctx.send("❌ Antrean kosong.", ephemeral=True)

        queue_list = list(queue) # Dapatkan list dari deque
        embed = discord.Embed(title="🎶 Antrean Musik", color=discord.Color.purple())

        current_song_info = self.now_playing_info.get(guild_id)
        if current_song_info and ctx.voice_client and ctx.voice_client.is_playing(): # Cek is_playing dari voice_client
            requester = ctx.guild.get_member(current_song_info['requester_id']) or await self.bot.fetch_user(current_song_info['requester_id'])
            requester_name = requester.display_name if requester else "Tidak dikenal"
            embed.add_field(name="Sedang Diputar:", value=f"[{current_song_info['title']}]({current_song_info['url']}) (Diminta oleh: {requester_name})", inline=False)
        
        queue_text = ""
        for i, song in enumerate(queue_list[:10]): # Tampilkan 10 lagu pertama
            requester = ctx.guild.get_member(song['requester_id']) or await self.bot.fetch_user(song['requester_id'])
            requester_name = requester.display_name if requester else "Tidak dikenal"
            queue_text += f"{i+1}. [{song['title']}]({song['original_url']}) (Diminta oleh: {requester_name})\n"
        
        if queue_text:
            embed.add_field(name="Berikutnya:", value=queue_text, inline=False)
        
        if len(queue_list) > 10:
            embed.set_footer(text=f"Dan {len(queue_list) - 10} lagu lainnya di antrean.")
        
        await ctx.send(embed=embed)
        log.info(f"Queue displayed for guild {guild_id}.")

    @commands.command(name="resloop", help="Mengaktifkan/menonaktifkan mode loop lagu saat ini.")
    async def loop_cmd(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.loop_status:
            self.loop_status[guild_id] = False
        
        self.loop_status[guild_id] = not self.loop_status[guild_id]

        if self.loop_status[guild_id]:
            await ctx.send("🔁 Mode Loop **ON** (lagu saat ini akan diulang).", ephemeral=False)
            # Update tombol di pesan now playing (jika ada dan valid)
            if ctx.guild.id in self.current_music_message:
                try:
                    msg_channel_id, msg_id = self.current_music_message[guild_id]
                    msg_channel = ctx.bot.get_channel(msg_channel_id)
                    if msg_channel:
                        msg = await msg_channel.fetch_message(msg_id)
                        # Buat ulang view untuk update tombol
                        view_instance = MusicControlView(self, original_message=msg)
                        for item in view_instance.children:
                            if item.custom_id == "music:loop":
                                item.style = discord.ButtonStyle.green
                                break
                        await msg.edit(view=view_instance)
                except (discord.NotFound, IndexError, KeyError):
                    print(f"[{datetime.now()}] [Music Cog] Could not update loop button on now playing message (not found or invalid state).")
                    pass
            print(f"[{datetime.now()}] [Music Cog] Loop mode ON for {ctx.guild.name}.")
        else:
            await ctx.send("🔁 Mode Loop **OFF**.", ephemeral=False)
            # Update tombol di pesan now playing (jika ada dan valid)
            if ctx.guild.id in self.current_music_message:
                try:
                    msg_channel_id, msg_id = self.current_music_message[guild_id]
                    msg_channel = ctx.bot.get_channel(msg_channel_id)
                    if msg_channel:
                        msg = await msg_channel.fetch_message(msg_id)
                        # Buat ulang view untuk update tombol
                        view_instance = MusicControlView(self, original_message=msg)
                        for item in view_instance.children:
                            if item.custom_id == "music:loop":
                                item.style = discord.ButtonStyle.grey
                                break
                        await msg.edit(view=view_instance)
                except (discord.NotFound, IndexError, KeyError):
                    print(f"[{datetime.now()}] [Music Cog] Could not update loop button on now playing message (not found or invalid state).")
                    pass
            print(f"[{datetime.now()}] [Music Cog] Loop mode OFF for {ctx.guild.name}.")
        self.save_state() # Save state after loop status change


    @commands.command(name="reslyrics")
    async def lyrics(self, ctx, *, song_name=None):
        if not self.genius:
            return await ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.", ephemeral=True)
            
        if song_name is None and ctx.voice_client and ctx.voice_client.is_playing():
            current_source = ctx.voice_client.source
            song_name = current_source.title
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

        # Jika bot berada di voice channel yang sama dan channel tersebut menjadi kosong
        if before.channel and self.bot.user.voice and self.bot.user.voice.channel == before.channel:
            # Hitung anggota non-bot yang masih ada di channel
            human_members_in_vc = [m for m in before.channel.members if not m.bot and not m.voice.self_deaf and not m.voice.self_mute]

            if len(human_members_in_vc) == 0:
                guild_id = member.guild.id
                # Jika tidak ada anggota manusia (yang aktif), mulai atau reset timer disconnect
                if guild_id in self.disconnect_timers and not self.disconnect_timers[guild_id].done():
                    self.disconnect_timers[guild_id].cancel()
                    print(f"[{datetime.now()}] [Music Cog] Disconnect timer untuk {member.guild.name} dibatalkan (user keluar/masuk cepat).")

                async def disconnect_countdown():
                    await asyncio.sleep(60) # Tunggu 60 detik sebelum disconnect
                    # Cek lagi setelah delay apakah channel masih kosong dan bot masih di VC
                    if self.bot.user.voice and self.bot.user.voice.channel == before.channel:
                        current_human_members = [m for m in before.channel.members if not m.bot and not m.voice.self_deaf and not m.voice.self_mute]
                        if len(current_human_members) == 0:
                            await self.bot.user.voice.channel.disconnect()
                            self.queues[guild_id].clear() # Bersihkan antrean
                            self.loop_status.pop(guild_id, None) # Matikan loop
                            self.now_playing_info.pop(guild_id, None)
                            self.current_music_message.pop(guild_id, None)
                            self.save_state()
                            print(f"[{datetime.now()}] [Music Cog] Bot disconnected from {before.channel.name} as it was empty.")
                            try:
                                # Kirim pesan ke channel teks jika channel terakhir diketahui
                                channel_id, message_id = self.current_music_message.get(guild_id, (None, None))
                                if channel_id:
                                    channel_obj = self.bot.get_channel(channel_id)
                                    if channel_obj:
                                        await channel_obj.send("Bot keluar dari voice channel karena tidak ada user aktif di dalamnya.")
                            except Exception as e:
                                print(f"[{datetime.now()}] [Music Cog] Error sending disconnect message: {e}")
                    
                    # Hapus timer setelah selesai, terlepas dari apakah bot disconnect atau tidak
                    del self.disconnect_timers[guild_id] 

                self.disconnect_timers[guild_id] = asyncio.create_task(disconnect_countdown())
                print(f"[{datetime.now()}] [Music Cog] Disconnect timer 60 detik dimulai untuk {member.guild.name} di {voice_channel.name}.")

            elif len(human_members_in_vc) > 0:
                guild_id = member.guild.id
                # Jika ada anggota manusia, batalkan timer disconnect jika ada
                if guild_id in self.disconnect_timers and not self.disconnect_timers[guild_id].done():
                    self.disconnect_timers[guild_id].cancel()
                    del self.disconnect_timers[guild_id]
                    print(f"[{datetime.now()}] [Music Cog] Disconnect timer untuk {member.guild.name} dibatalkan (ada user masuk).")

async def setup(bot):
    await bot.add_cog(Music(bot))
