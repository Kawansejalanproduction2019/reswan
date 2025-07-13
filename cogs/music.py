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

# Konfigurasi Genius API untuk lirik
GENIUS_API_TOKEN = os.getenv("GENIUS_API")
# Pastikan API token sudah diatur di environment variable atau langsung di sini
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
            client_secret=SPOTIFY_CLIENT_SECRET
        ))
    except Exception as e:
        print(f"Warning: Could not initialize Spotify client: {e}")
        print("Spotify features might not work.")
else:
    print("Warning: SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET not set.")
    print("Spotify features might not work without them.")

# YTDL dan FFMPEG opsi
ytdl_opts = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'cookiefile': 'cookies.txt',
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
        self.url = data.get('url')
        self.thumbnail = data.get('thumbnail')
        self.webpage_url = data.get('webpage_url')
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
        # Ambil voice client dari guild jika ada original_message
        vc = None
        if self.original_message and self.original_message.guild:
            vc = self.original_message.guild.voice_client

        # Dapatkan status antrean dan loop
        guild_id = self.original_message.guild.id if self.original_message else None
        queue_exists = bool(self.cog.get_queue(guild_id))
        is_playing = vc and vc.is_playing()
        is_paused = vc and vc.is_paused()
        loop_on = self.cog.loop_status.get(guild_id, False)

        for item in self.children:
            # Tombol Play/Pause
            if item.custom_id == "music:play_pause":
                item.disabled = not (is_playing or is_paused or queue_exists)
                if is_playing:
                    item.emoji = "⏸️"
                    item.style = discord.ButtonStyle.primary
                elif is_paused:
                    item.emoji = "▶️"
                    item.style = discord.ButtonStyle.green
                else: # Tidak ada yang diputar/dijeda, tapi mungkin ada di antrean
                    item.emoji = "▶️"
                    item.style = discord.ButtonStyle.primary

            # Tombol Skip
            elif item.custom_id == "music:skip":
                item.disabled = not (is_playing or is_paused)

            # Tombol Stop
            elif item.custom_id == "music:stop":
                item.disabled = not vc

            # Tombol Queue
            elif item.custom_id == "music:queue":
                item.disabled = not queue_exists and not (is_playing or is_paused)

            # Tombol Loop
            elif item.custom_id == "music:loop":
                item.disabled = not vc
                if loop_on:
                    item.style = discord.ButtonStyle.green
                else:
                    item.style = discord.ButtonStyle.grey

            # Tombol Lyrics
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
        
        self._update_button_states() # Perbarui status tombol setelah aksi
        await interaction.message.edit(view=self) # Edit pesan kontrol untuk update tombol

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, custom_id="music:skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_voice_channel(interaction):
            return
        
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ Skip lagu.", ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        
        self._update_button_states() # Perbarui status tombol setelah aksi
        await interaction.message.edit(view=self) # Edit pesan kontrol untuk update tombol

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
            
            await vc.disconnect()
            await interaction.followup.send("⏹️ Stop dan keluar dari voice.", ephemeral=True)
            
            # Hapus pesan kontrol musik lama setelah bot keluar
            if self.original_message:
                try:
                    await self.original_message.delete(delay=5) # Hapus setelah 5 detik
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
        
        # Meskipun bot keluar, panggil update_button_states agar state internal konsisten
        self._update_button_states()
        if self.original_message:
             # Coba edit pesan lagi, mungkin pesan sudah hilang, tapi tidak masalah karena sudah ditangani
            try:
                await self.original_message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.grey, custom_id="music:queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.cog.get_queue(interaction.guild.id)
        if queue:
            display_queue = queue[:10]
            msg = "\n".join([f"{i+1}. {q}" for i, q in enumerate(display_queue)])
            
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
        
        self._update_button_states() # Perbarui status tombol setelah aksi
        await interaction.message.edit(view=self) # Edit pesan kontrol untuk update tombol
            
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
        
        self._update_button_states() # Perbarui status tombol setelah aksi
        await interaction.message.edit(view=self) # Edit pesan kontrol untuk update tombol

    # --- Tombol Lirik Baru ---
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
            await interaction.response.defer(ephemeral=True) # Defer respons agar tidak timeout
            await self.cog._send_lyrics(interaction, song_name) # Panggil fungsi pengirim lirik di cog
        else:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
        
        self._update_button_states() # Perbarui status tombol setelah aksi
        await interaction.message.edit(view=self) # Edit pesan kontrol untuk update tombol


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {} # {guild_id: [url1, url2, ...]}
        self.loop_status = {} # {guild_id: True/False}
        self.current_music_message = {} # {guild_id: message_id} untuk pesan "Now Playing"
        self.current_music_channel = {} # {guild_id: channel_id} untuk channel tempat pesan musik berada
        self.genius = genius
        self.spotify = spotify

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
        """Fungsi internal untuk mengirim lirik, bisa dipanggil dari command atau tombol."""
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
                
                # Kirim embed pertama melalui respons interaksi atau ctx.send
                if isinstance(interaction_or_ctx, discord.Interaction):
                    if interaction_or_ctx.response.is_done():
                        message_sent = await interaction_or_ctx.followup.send(embed=embed)
                    else:
                        message_sent = await interaction_or_ctx.response.send_message(embed=embed)
                else: # commands.Context
                    message_sent = await interaction_or_ctx.send(embed=embed)

                # Kirim sisa lirik di pesan terpisah
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

    async def play_next(self, ctx):
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        
        # Dapatkan channel target untuk mengirim pesan
        target_channel_id = self.current_music_channel.get(guild_id)
        target_channel = self.bot.get_channel(target_channel_id) if target_channel_id else ctx.channel # Fallback ke ctx.channel

        if self.loop_status.get(guild_id, False) and ctx.voice_client and ctx.voice_client.source:
            current_song_url = ctx.voice_client.source.data.get('webpage_url')
            if current_song_url:
                queue.insert(0, current_song_url) # Tambahkan kembali lagu yang sedang diputar jika loop aktif

        if not queue:
            if guild_id in self.current_music_message:
                try:
                    message_id = self.current_music_message[guild_id]
                    # Coba ambil pesan dari target_channel
                    msg = await target_channel.fetch_message(message_id) 
                    view_instance = MusicControlView(self, original_message=msg)
                    view_instance._update_button_states() # Perbarui status tombol agar dinonaktifkan
                    
                    embed = msg.embeds[0] if msg.embeds else discord.Embed()
                    embed.title = "Musik Berhenti 🎶"
                    embed.description = "Antrean kosong. Bot akan keluar dari voice channel."
                    embed.set_footer(text="")
                    embed.set_thumbnail(url=discord.Embed.Empty)
                    await msg.edit(embed=embed, view=view_instance)
                    
                    # Hapus referensi pesan setelah nonaktif
                    del self.current_music_message[guild_id] 
                except discord.NotFound:
                    print(f"Pesan kontrol musik tidak ditemukan di guild {guild_id}.")
                    if guild_id in self.current_music_message:
                        del self.current_music_message[guild_id]
                except Exception as e:
                    print(f"Error updating music message on queue empty: {e}")
            
            # Kirim pesan keluar ke channel yang benar
            await target_channel.send("Antrean kosong. Keluar dari voice channel.") 
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
            
            # Hapus referensi channel saat bot keluar
            if guild_id in self.current_music_channel:
                del self.current_music_channel[guild_id]
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

            message_sent = None
            # Coba perbarui pesan yang sudah ada
            if guild_id in self.current_music_message and guild_id in self.current_music_channel:
                try:
                    old_message = await self.bot.get_channel(self.current_music_channel[guild_id]).fetch_message(self.current_music_message[guild_id])
                    view_instance = MusicControlView(self, original_message=old_message)
                    view_instance._update_button_states() # Perbarui status tombol
                    await old_message.edit(embed=embed, view=view_instance)
                    message_sent = old_message
                except (discord.NotFound, discord.HTTPException):
                    print(f"Pesan musik lama tidak ditemukan atau tidak dapat diakses di guild {guild_id}, mengirim pesan baru.")
                    message_sent = await target_channel.send(embed=embed, view=MusicControlView(self))
            else:
                # Kirim pesan baru jika tidak ada pesan yang bisa diperbarui
                message_sent = await target_channel.send(embed=embed, view=MusicControlView(self))
            
            if message_sent:
                self.current_music_message[guild_id] = message_sent.id
                self.current_music_channel[guild_id] = message_sent.channel.id # Pastikan channel ID juga diupdate
                # Setelah pesan dikirim dan ID-nya disimpan, perbarui view sekali lagi
                # agar tombol-tombolnya memiliki original_message yang benar
                view_instance = MusicControlView(self, original_message=message_sent)
                view_instance._update_button_states()
                await message_sent.edit(view=view_instance)


        except Exception as e:
            await target_channel.send(f'Gagal memutar lagu: {e}')
            asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

    async def _after_play_handler(self, ctx, error):
        if error:
            print(f"Player error: {error}")
            target_channel_id = self.current_music_channel.get(ctx.guild.id)
            target_channel = self.bot.get_channel(target_channel_id) if target_channel_id else ctx.channel
            await target_channel.send(f"Terjadi error saat memutar: {error}")
        
        # Perbarui pesan kontrol musik setelah lagu selesai atau ada error
        if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
            try:
                msg = await self.bot.get_channel(self.current_music_channel[ctx.guild.id]).fetch_message(self.current_music_message[ctx.guild.id])
                view_instance = MusicControlView(self, original_message=msg)
                view_instance._update_button_states() # Perbarui status tombol
                await msg.edit(view=view_instance)
            except (discord.NotFound, discord.HTTPException):
                pass # Pesan sudah tidak ada, tidak perlu diperbarui
            except Exception as e:
                print(f"Error updating music message in after_play_handler: {e}")

        await asyncio.sleep(1) # Beri sedikit jeda sebelum memutar lagu berikutnya
        await self.play_next(ctx)

    @commands.command(name="resjoin")
    async def join(self, ctx):
        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                return await ctx.send("Bot sudah berada di voice channel lain. Harap keluarkan dulu.")
            return
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
            await ctx.send(f"Joined **{ctx.author.voice.channel.name}**")
            # Simpan channel ID saat bot join
            self.current_music_channel[ctx.guild.id] = ctx.channel.id 
        else:
            await ctx.send("Kamu harus berada di voice channel dulu.")

    @commands.command(name="resp")
    async def play(self, ctx, *, query):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            if not ctx.voice_client:
                return await ctx.send("Gagal bergabung ke voice channel.")
        
        # Pastikan channel ID disimpan di sini juga jika play adalah command pertama
        self.current_music_channel[ctx.guild.id] = ctx.channel.id 

        await ctx.defer()

        urls = []
        is_spotify = False

        # Perbaikan deteksi link Spotify
        # Menggunakan regex akan lebih robust, tapi ini adalah perbaikan sederhana
        if spotify and ("open.spotify.com/track/" in query or "open.spotify.com/playlist/" in query or "open.spotify.com/album/" in query):
            is_spotify = True
            try:
                if "track" in query:
                    track = self.spotify.track(query)
                    search_query = f"{track['name']} {track['artists'][0]['name']}"
                    urls.append(search_query)
                elif "playlist" in query:
                    results = self.spotify.playlist_tracks(query)
                    for item in results['items']:
                        track = item['track']
                        if track:
                            search_query = f"{track['name']} {track['artists'][0]['name']}"
                            urls.append(search_query)
                elif "album" in query:
                    results = self.spotify.album_tracks(query)
                    for item in results['items']:
                        track = item
                        if track:
                            search_query = f"{track['name']} {track['artists'][0]['name']}"
                            urls.append(search_query)
                else:
                    return await ctx.send("Link Spotify tidak dikenali (hanya track, playlist, atau album).")
            except Exception as e:
                await ctx.send(f"Terjadi kesalahan saat memproses link Spotify: {e}")
                return

        else:
            urls.append(query)

        queue = self.get_queue(ctx.guild.id)
        
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused() and not queue:
            # Jika tidak ada lagu diputar/dijeda dan antrean kosong, langsung mainkan lagu pertama
            first_url = urls.pop(0)
            queue.extend(urls) # Tambahkan sisa URL ke antrean
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

                # Kirim pesan kontrol musik awal
                message_sent = await ctx.send(embed=embed, view=MusicControlView(self))
                self.current_music_message[ctx.guild.id] = message_sent.id
                self.current_music_channel[ctx.guild.id] = message_sent.channel.id # Simpan channel ID
                
                # Setelah pesan dikirim dan ID-nya disimpan, perbarui view sekali lagi
                # agar tombol-tombolnya memiliki original_message yang benar
                view_instance = MusicControlView(self, original_message=message_sent)
                view_instance._update_button_states()
                await message_sent.edit(view=view_instance)
                
            except Exception as e:
                await ctx.send(f'Gagal memutar lagu: {e}')
                return
        else:
            # Jika sudah ada lagu diputar atau antrean tidak kosong, tambahkan ke antrean
            queue.extend(urls)
            if is_spotify:
                await ctx.send(f"Ditambahkan ke antrian: **{len(urls)} lagu** dari Spotify.")
            else:
                await ctx.send(f"Ditambahkan ke antrian: **{urls[0]}**.")
            
            # Perbarui footer pesan kontrol musik yang sudah ada
            if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
                try:
                    msg = await self.bot.get_channel(self.current_music_channel[ctx.guild.id]).fetch_message(self.current_music_message[ctx.guild.id])
                    embed = msg.embeds[0]
                    embed.set_footer(text=f"Antrean: {len(queue)} lagu tersisa")
                    # Update view juga untuk memastikan tombol di-refresh
                    view_instance = MusicControlView(self, original_message=msg)
                    view_instance._update_button_states()
                    await msg.edit(embed=embed, view=view_instance)
                except (discord.NotFound, IndexError):
                    pass # Pesan tidak ditemukan, biarkan play_next membuat yang baru jika perlu

    @commands.command(name="resskip")
    async def skip_cmd(self, ctx):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            return await ctx.send("Tidak ada lagu yang sedang diputar.")
        ctx.voice_client.stop()
        await ctx.send("⏭️ Skip lagu.")

    @commands.command(name="respause")
    async def pause_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Lagu dijeda.")
            # Update tombol di pesan kontrol musik
            if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
                try:
                    msg = await self.bot.get_channel(self.current_music_channel[ctx.guild.id]).fetch_message(self.current_music_message[ctx.guild.id])
                    view_instance = MusicControlView(self, original_message=msg)
                    view_instance._update_button_states()
                    await msg.edit(view=view_instance)
                except (discord.NotFound, IndexError):
                    pass
        else:
            await ctx.send("Tidak ada lagu yang sedang diputar.")

    @commands.command(name="resresume")
    async def resume_cmd(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Lanjut lagu.")
            # Update tombol di pesan kontrol musik
            if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
                try:
                    msg = await self.bot.get_channel(self.current_music_channel[ctx.guild.id]).fetch_message(self.current_music_message[ctx.guild.id])
                    view_instance = MusicControlView(self, original_message=msg)
                    view_instance._update_button_states()
                    await msg.edit(view=view_instance)
                except (discord.NotFound, IndexError):
                    pass
        else:
            await ctx.send("Tidak ada lagu yang dijeda.")

    @commands.command(name="resstop")
    async def stop_cmd(self, ctx):
        if ctx.voice_client:
            self.queues[ctx.guild.id] = []
            self.loop_status[ctx.guild.id] = False
            
            if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
                try:
                    msg = await self.bot.get_channel(self.current_music_channel[ctx.guild.id]).fetch_message(self.current_music_message[ctx.guild.id])
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
                except (discord.NotFound, discord.HTTPException):
                    pass
            
            await ctx.voice_client.disconnect()
            await ctx.send("⏹️ Stop dan keluar dari voice.")
            
            # Hapus referensi channel saat bot keluar
            if ctx.guild.id in self.current_music_channel:
                del self.current_music_channel[ctx.guild.id]
        else:
            await ctx.send("Bot tidak ada di voice channel.")

    @commands.command(name="resqueue")
    async def queue_cmd(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            display_queue = queue[:15]
            msg = "\n".join([f"{i+1}. {q}" for i, q in enumerate(display_queue)])
            
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
        
        # Update tombol di pesan kontrol musik
        if ctx.guild.id in self.current_music_message and ctx.guild.id in self.current_music_channel:
            try:
                msg = await self.bot.get_channel(self.current_music_channel[ctx.guild.id]).fetch_message(self.current_music_message[ctx.guild.id])
                view_instance = MusicControlView(self, original_message=msg)
                view_instance._update_button_states()
                await msg.edit(view=view_instance)
            except (discord.NotFound, IndexError):
                pass


    @commands.command(name="reslyrics")
    async def lyrics(self, ctx, *, song_name=None):
        if not self.genius:
            return await ctx.send("Fitur lirik tidak aktif karena API token Genius belum diatur.")
            
        if song_name is None and ctx.voice_client and ctx.voice_client.is_playing():
            song_name = ctx.voice_client.source.title
        elif song_name is None:
            return await ctx.send("Tentukan nama lagu atau putar lagu terlebih dahulu untuk mencari liriknya.")
            
        await ctx.defer() # Defer respons untuk perintah command
        await self._send_lyrics(ctx, song_name)


async def setup(bot):
    await bot.add_cog(Music(bot))
