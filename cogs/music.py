import discord
from discord.ext import commands, tasks
import json
import os
import logging
import asyncio
import functools
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
from lyricsgenius import Genius
from datetime import datetime, timedelta

# Inisialisasi Logger untuk Cog ini
log = logging.getLogger(__name__)

# --- FILE DATA UNTUK MELACAK CHANNEL SEMENTARA (Persisten antar restart bot) ---
TEMP_CHANNELS_FILE = 'data/temp_voice_channels.json'

def load_json_from_root(file_path, default_value=None):
    """
    Memuat data JSON dari file yang berada di root direktori proyek bot.
    Menambahkan `default_value` yang lebih fleksibel.
    """
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True) # Pastikan direktori ada
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning(f"File {full_path} not found. Returning default value.")
        if default_value is not None:
            save_json_to_root(default_value, file_path)
            return default_value
        return {} # Fallback
    except json.JSONDecodeError as e:
        log.error(f"File {full_path} corrupted (invalid JSON). Error: {e}. Attempting to reset it.")
        if default_value is not None:
            save_json_to_root(default_value, file_path)
            return default_value
        return {} # Fallback
    except Exception as e:
        log.error(f"An unexpected error occurred while loading {full_path}: {e}", exc_info=True)
        if default_value is not None:
            save_json_to_root(default_value, file_path)
            return default_value
        return {} # Fallback

def save_json_to_root(data, file_path):
    """Menyimpan data ke file JSON di root direktori proyek."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    full_path = os.path.join(base_dir, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True) # Pastikan direktori ada
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def load_temp_channels():
    # Use the centralized load_json_from_root
    data = load_json_from_root(TEMP_CHANNELS_FILE, default_value={})
    cleaned_data = {}
    for ch_id, info in data.items():
        # Ensure owner_id and guild_id are string for consistency
        if "owner_id" in info:
            info["owner_id"] = str(info["owner_id"])
        if "guild_id" in info:
            info["guild_id"] = str(info["guild_id"])
        cleaned_data[str(ch_id)] = info
    return cleaned_data

def save_temp_channels(data):
    # Use the centralized save_json_to_root
    save_json_to_root(data, TEMP_CHANNELS_FILE)

# --- Class untuk Tombol Kontrol Musik ---
class MusicControlView(discord.ui.View):
    def __init__(self, cog_instance, original_message=None):
        super().__init__(timeout=None)
        self.cog = cog_instance # Cog gabungan sekarang adalah VoiceFeatures
        self.original_message = original_message
        self._update_button_states() 

    def _update_button_states(self):
        vc = None
        guild_id = None
        if self.original_message and self.original_message.guild:
            vc = self.original_message.guild.voice_client
            guild_id = self.original_message.guild.id

        queue_exists = bool(self.cog.music_queues.get(guild_id)) if guild_id else False
        is_playing = vc and vc.is_playing()
        is_paused = vc and vc.is_paused()
        loop_on = self.cog.music_loop_status.get(guild_id, False) if guild_id else False

        for item in self.children:
            if item.custom_id == "music:play_pause":
                item.disabled = not (vc and (is_playing or is_paused)) and not queue_exists
                if is_playing:
                    item.emoji = "⏸️"
                    item.style = discord.ButtonStyle.primary
                elif is_paused:
                    item.emoji = "▶️"
                    item.style = discord.ButtonStyle.green
                else:
                    item.emoji = "▶️"
                    item.style = discord.ButtonStyle.secondary 

            elif item.custom_id == "music:skip":
                item.disabled = not (is_playing or is_paused)

            elif item.custom_id == "music:stop":
                item.disabled = not vc

            elif item.custom_id == "music:queue":
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
        if self.original_message:
            try:
                self._update_button_states()
                await self.original_message.edit(view=self)
            except (discord.NotFound, discord.HTTPException) as e:
                log.error(f"Error updating control message after interaction: {e}")
                if self.original_message.guild.id in self.cog.current_music_message:
                    del self.cog.current_music_message[self.original_message.guild.id]
                if self.original_message.guild.id in self.cog.current_music_channel:
                    del self.cog.current_music_channel[self.original_message.guild.id]
        elif interaction.message: 
            try:
                self._update_button_states()
                await interaction.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException) as e:
                log.error(f"Error updating interaction message: {e}")

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
            self.cog.music_queues[interaction.guild.id] = []
            self.cog.music_loop_status[interaction.guild.id] = False
            
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self) 
            
            if vc.source:
                vc.source.cleanup()
            await vc.disconnect()
            await interaction.followup.send("⏹️ Stop dan keluar dari voice.", ephemeral=True)
            
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
                    log.error(f"Error deleting original music message: {e}")
        else:
            await interaction.response.send_message("Bot tidak ada di voice channel.", ephemeral=True)
        
    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.grey, custom_id="music:queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.cog.get_music_queue(interaction.guild.id)
        if queue:
            display_queue = queue[:10]
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
        self.cog.music_loop_status[guild_id] = not self.cog.music_loop_status.get(guild_id, False)

        if self.cog.music_loop_status[guild_id]:
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

# --- YTDL Source untuk musik ---
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
        data = await loop.run_in_executor(None, functools.partial(yt_dlp.YoutubeDL({
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
        }).extract_info, url, download=not stream))
        
        if 'entries' in data:
            data = data['entries'][0]
        
        filename = data['url'] if stream else yt_dlp.YoutubeDL().prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **{
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn -b:a 192k'
        }), data=data)


# --- MAIN COG GABUNGAN ---
class VoiceFeatures(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # --- KONFIGURASI TEMPVOLICE ---
        self.TRIGGER_VOICE_CHANNEL_ID = 1382486705113927811 # ID Channel Pemicu TempVoice
        self.TARGET_CATEGORY_ID = 1255211613326278716     # ID Kategori untuk Channel Baru
        self.DEFAULT_CHANNEL_NAME_PREFIX = "Music"
        self.active_temp_channels = load_temp_channels()
        log.info(f"TempVoice initialized. Active temporary channels: {self.active_temp_channels}")
        self.cleanup_task.start()

        # --- KONFIGURASI MUSIC ---
        self.music_queues = {} # {guild_id: [url1, url2, ...]}
        self.music_loop_status = {} # {guild_id: True/False}
        self.current_music_message = {} # {guild_id: message_id} untuk pesan "Now Playing"
        self.current_music_channel = {} # {guild_id: channel_id} untuk channel tempat pesan musik berada

        # Genius API
        GENIUS_API_TOKEN = os.getenv("GENIUS_API")
        self.genius = Genius(GENIUS_API_TOKEN) if GENIUS_API_TOKEN else None
        if not self.genius:
            log.warning(f"GENIUS_API_TOKEN is not set. Lyrics feature will not work.")

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
                log.info("Spotify client initialized successfully for Music feature.")
            except Exception as e:
                log.warning(f"Could not initialize Spotify client: {e}. Spotify features might not work.")
        else:
            log.warning("SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET not set. Spotify features might not work.")

        # Buat folder downloads jika belum ada
        if not os.path.exists('downloads'):
            os.makedirs('downloads')
            log.info("'downloads' folder created.")

        # Tambahkan view ke bot agar tetap berfungsi setelah restart
        self.bot.add_view(MusicControlView(self))

        log.info(f"VoiceFeatures cog initialized.")


    # --- Helper functions TempVoice ---
    def _save_temp_channels_state(self):
        save_temp_channels(self.active_temp_channels)
        log.debug("Temporary channel state saved.")

    def cog_unload(self):
        log.info("VoiceFeatures cog unloaded. Cancelling cleanup task.")
        self.cleanup_task.cancel()

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

            # Perubahan penting: Jangan hapus channel jika bot musik ada di dalamnya
            voice_client = guild.voice_client
            if voice_client and voice_client.is_connected() and voice_client.channel.id == channel_id:
                # Bot sedang di channel ini, dan sedang memutar musik atau ada di antrean
                if voice_client.is_playing() or voice_client.is_paused() or self.get_music_queue(guild_id):
                    log.info(f"Bot is playing/paused/queued in temporary channel {channel.name}. Skipping deletion for this cycle.")
                    continue # Jangan hapus channel jika bot aktif di dalamnya

            if not channel.members: # Jika channel kosong dari user mana pun (termasuk bot jika tidak aktif)
                try:
                    await channel.delete(reason="Temporary voice channel is empty.")
                    log.info(f"Deleted empty temporary voice channel: {channel.name} ({channel_id}).")
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

    # --- Helper functions Music ---
    def get_music_queue(self, guild_id):
        return self.music_queues.setdefault(guild_id, [])

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
            log.error(f"Error fetching lyrics: {e}")

    async def _play_next_music(self, guild_id):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            log.warning(f"Guild {guild_id} not found in _play_next_music. Aborting.")
            return

        target_channel_id = self.current_music_channel.get(guild_id)
        target_channel = guild.get_channel(target_channel_id) if target_channel_id else None

        if not target_channel:
            target_channel = guild.system_channel or guild.text_channels[0] if guild.text_channels else None
            if not target_channel:
                log.warning(f"No text channel found in guild {guild_id} for sending music messages.")
                return

        voice_client = guild.voice_client
        queue = self.get_music_queue(guild_id)

        # Jika loop aktif dan ada lagu saat ini, tambahkan kembali ke antrean
        if self.music_loop_status.get(guild_id, False) and voice_client and voice_client.is_connected() and voice_client.source:
            current_song_query = voice_client.source.title 
            if voice_client.source.uploader and voice_client.source.uploader != "Unknown":
                current_song_query = f"{voice_client.source.title} {voice_client.source.uploader}"
            
            queue.insert(0, current_song_query) 

        if not queue:
            # Antrean kosong. Bot tidak akan disconnect sendiri di sini.
            # Biarkan cleanup_task dari TempVoice yang menghapus channel jika kosong user.
            if guild_id in self.current_music_message:
                try:
                    message_id = self.current_music_message[guild_id]
                    msg = await target_channel.fetch_message(message_id) 
                    view_instance = MusicControlView(self, original_message=msg)
                    view_instance._update_button_states() 
                    
                    embed = msg.embeds[0] if msg.embeds else discord.Embed()
                    embed.title = "Musik Berhenti 🎶"
                    embed.description = "Antrean kosong." # Hapus "Bot akan keluar dari voice channel."
                    embed.set_footer(text="Bot akan tetap di channel ini selama user aktif ada.")
                    embed.set_thumbnail(url=discord.Embed.Empty)
                    await msg.edit(embed=embed, view=view_instance)
                except discord.NotFound:
                    log.warning(f"Music control message not found in guild {guild_id} when queue is empty. Cannot update.")
                except Exception as e:
                    log.error(f"Error updating music message on queue empty for guild {guild_id}: {e}")
            
            await target_channel.send("Antrean kosong. Bot akan menunggu di channel ini.") 
            # Tidak lagi memanggil disconnect di sini, biarkan TempVoice yang menghapus channel jika kosong
            return

        # Ada lagu di antrean, coba mainkan
        if not voice_client or not voice_client.is_connected():
            log.warning(f"Voice client not connected in guild {guild_id} when trying to play next song. Aborting music playback.")
            # Clear music state as bot is not connected
            if guild_id in self.current_music_channel:
                del self.current_music_channel[guild_id]
            if guild_id in self.current_music_message:
                del self.current_music_message[guild_id]
            
            # Remove the song that failed to play
            if queue:
                queue.pop(0) 
            await target_channel.send("Bot tidak terhubung ke voice channel. Silakan panggil ulang bot jika ingin memutar musik.")
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
                    log.warning(f"Music control message not found or inaccessible in guild {guild_id}. Sending new message.")
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
            log.error(f"Error playing next song in guild {guild_id}: {e}", exc_info=True)
            asyncio.run_coroutine_threadsafe(self._after_play_handler(guild_id, e), self.bot.loop)

    async def _after_play_handler(self, guild_id, error):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            log.warning(f"Guild {guild_id} not found in _after_play_handler. Aborting.")
            return

        target_channel_id = self.current_music_channel.get(guild_id)
        target_channel = guild.get_channel(target_channel_id) if target_channel_id else None

        if not target_channel:
            target_channel = guild.system_channel or guild.text_channels[0] if guild.text_channels else None
            if not target_channel:
                log.warning(f"No text channel found in guild {guild_id} for sending after_play_handler message.")
                return

        if error:
            log.error(f"Player error in guild {guild_id}: {error}")
            await target_channel.send(f"Terjadi error saat memutar lagu: {error}")
        
        voice_client = guild.voice_client
        if voice_client and voice_client.is_connected() and voice_client.source:
            voice_client.source.cleanup()
            log.info(f"FFmpeg source cleaned up for guild {guild_id}.")
        
        if guild_id in self.current_music_message and guild_id in self.current_music_channel:
            try:
                msg = await target_channel.fetch_message(self.current_music_message[guild_id])
                view_instance = MusicControlView(self, original_message=msg)
                view_instance._update_button_states() 
                await msg.edit(embed=msg.embeds[0] if msg.embeds else None, view=view_instance)
            except (discord.NotFound, discord.HTTPException):
                log.warning(f"Music control message not found or inaccessible in guild {guild_id} after song finished.")
                if guild_id in self.current_music_message:
                    del self.current_music_message[guild_id]
                if guild_id in self.current_music_channel:
                    del self.current_music_channel[guild_id]
            except Exception as e:
                log.error(f"Error updating music message in after_play_handler for guild {guild_id}: {e}")

        await asyncio.sleep(1) 
        await self._play_next_music(guild_id) 

    # --- COMMANDS ---

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        guild_id = member.guild.id
        guild = member.guild
        
        # --- LOGIC TEMPVOLICE (MEMBUAT/MEMINDAHKAN CHANNEL) ---
        if after.channel and after.channel.id == self.TRIGGER_VOICE_CHANNEL_ID:
            log.info(f"User {member.display_name} ({member.id}) joined trigger VC ({self.TRIGGER_VOICE_CHANNEL_ID}).")

            # Cek apakah user sudah punya channel temporer aktif
            for ch_id_str, ch_info in list(self.active_temp_channels.items()):
                if ch_info["owner_id"] == str(member.id) and ch_info["guild_id"] == str(member.guild.id):
                    existing_channel = member.guild.get_channel(int(ch_id_str))
                    if existing_channel:
                        log.info(f"User {member.display_name} already has active temporary VC {existing_channel.name}. Moving them there.")
                        try:
                            await member.move_to(existing_channel)
                            return # Penting: Berhenti di sini setelah memindahkan user
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
                self._save_temp_channels_state()
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
            return # Penting: Berhenti di sini setelah membuat channel baru

        # --- LOGIC MUSIC COG (SEBELUMNYA) / AUTO-DISCONNECT ---
        # Logic auto-disconnect sepenuhnya dihapus dari sini.
        # TempVoice cleanup_task sekarang bertanggung jawab untuk menghapus channel.
        # Bot musik akan mengandalkan channel dihapus oleh TempVoice jika channel kosong.
        
        # Handle bot's own voice state changes for internal cleanup if necessary
        # This part ensures that if the bot itself disconnects, its music state is cleared.
        # This is a fallback in case TempVoice deletes a channel and bot doesn't clean up
        # or if bot disconnects for other reasons (e.g., connection issues, manual stop).
        if member.id == self.bot.user.id:
            if before.channel and not after.channel: # Bot disconnected
                log.info(f"Bot disconnected from voice channel {before.channel.name} in guild {guild.name}.")
                self._clear_music_state(guild_id)
            elif after.channel and not before.channel: # Bot connected
                log.info(f"Bot connected to voice channel {after.channel.name} in guild {guild.name}.")
                # Reset music state if connecting to a new channel (optional, based on desired behavior)
                # self._clear_music_state(guild_id) # uncomment if you want to clear queue on every reconnect

    def _clear_music_state(self, guild_id):
        """Membersihkan state musik untuk guild tertentu."""
        if guild_id in self.music_queues:
            del self.music_queues[guild_id]
            log.info(f"Music queue cleared for guild {guild_id}.")
        if guild_id in self.music_loop_status:
            del self.music_loop_status[guild_id]
            log.info(f"Music loop status cleared for guild {guild_id}.")
        if guild_id in self.current_music_message:
            del self.current_music_message[guild_id]
            log.info(f"Current music message cleared for guild {guild_id}.")
        if guild_id in self.current_music_channel:
            del self.current_music_channel[guild_id]
            log.info(f"Current music channel cleared for guild {guild_id}.")

    # --- COMMANDS MUSIC ---
    @commands.command(name="resjoin")
    async def join(self, ctx):
        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                return await ctx.send("Bot sudah berada di voice channel lain. Harap keluarkan dulu.")
            return
        if ctx.author.voice:
            # Tidak ada lagi disconnect_timer logic di sini
            try:
                await ctx.author.voice.channel.connect()
                await ctx.send(f"Joined **{ctx.author.voice.channel.name}**")
                self.current_music_channel[ctx.guild.id] = ctx.channel.id 
                log.info(f"Bot joined VC {ctx.author.voice.channel.name} in {ctx.guild.name}. Storing text channel {ctx.channel.id}.")
            except discord.ClientException as e:
                await ctx.send(f"Gagal bergabung ke voice channel: {e}. Mungkin bot sudah di channel lain atau ada masalah izin.", ephemeral=True)
                log.error(f"Failed to join VC {ctx.author.voice.channel.name}: {e}")
            except discord.Forbidden:
                await ctx.send("Aku tidak punya izin untuk bergabung ke voice channelmu. Pastikan aku punya izin `Connect` dan `Speak`.", ephemeral=True)
                log.error(f"Forbidden to join VC {ctx.author.voice.channel.name}.")
        else:
            await ctx.send("Kamu harus berada di voice channel dulu.")

    @commands.command(name="resp")
    async def play(self, ctx, *, query):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            if not ctx.voice_client:
                return await ctx.send("Gagal bergabung ke voice channel.")
        
        self.current_music_channel[ctx.guild.id] = ctx.channel.id 
        log.info(f"Play command invoked. Storing text channel {ctx.channel.id} for guild {ctx.guild.id}.")

        await ctx.defer()

        urls = []
        is_spotify = False

        spotify_track_pattern = re.compile(r'https?://open\.spotify\.com/track/([a-zA-Z0-9]+)')
        spotify_playlist_pattern = re.compile(r'https?://open\.spotify\.com/playlist/([a-zA-Z0-9]+)')
        spotify_album_pattern = re.compile(r'https?://open\.spotify\.com/album/([a-zA-Z0-9]+)')

        if self.spotify:
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
                    log.error(f"Error processing Spotify track {track_id}: {e}")
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
                    log.error(f"Error processing Spotify playlist {playlist_id}: {e}")
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
                    log.error(f"Error processing Spotify album {album_id}: {e}")
                    return
            else:
                urls.append(query) 
        else:
            urls.append(query) 

        queue = self.get_music_queue(ctx.guild.id)
        
        # Tidak ada lagi disconnect_timer logic di sini

        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused() and not queue:
            first_url_or_query = urls.pop(0)
            queue.extend(urls) 
            try:
                source = await YTDLSource.from_url(first_url_or_query, loop=self.bot.loop)
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
                log.error(f"Error starting first song in guild {ctx.guild.id}: {e}")
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
                        log.warning(f"Channel {self.current_music_channel[ctx.guild.id]} not found for updating queue message.")
                except (discord.NotFound, IndexError):
                    log.warning(f"Music control message or channel not found for guild {ctx.guild.id}. Cannot update queue footer.")
                except Exception as e:
                    log.error(f"Error updating queue message for guild {ctx.guild.id}: {e}")

    @commands.command(name="resskip")
    async def skip_cmd(self, ctx):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            return await ctx.send("Tidak ada lagu yang sedang diputar.")
        
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
                log.error(f"Error updating music message after skip for guild {ctx.guild.id}: {e}")

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
                    log.error(f"Error updating music message after pause for guild {ctx.guild.id}: {e}")
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
                    log.error(f"Error updating music message after resume for guild {ctx.guild.id}: {e}")
        else:
            await ctx.send("Tidak ada lagu yang dijeda.")

    @commands.command(name="resstop")
    async def stop_cmd(self, ctx):
        if ctx.voice_client:
            self.music_queues[ctx.guild.id] = []
            self.music_loop_status[ctx.guild.id] = False
            
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
                        log.warning(f"Channel {self.current_music_channel[ctx.guild.id]} not found for updating stop message.")
                except (discord.NotFound, discord.HTTPException):
                    pass
                except Exception as e:
                    log.error(f"Error updating music message after stop for guild {ctx.guild.id}: {e}")
            
            if ctx.voice_client.source:
                ctx.voice_client.source.cleanup()

            await ctx.voice_client.disconnect()
            await ctx.send("⏹️ Stop dan keluar dari voice.")
            
            if ctx.guild.id in self.current_music_channel:
                del self.current_music_channel[ctx.guild.id]
        else:
            await ctx.send("Bot tidak ada di voice channel.")

    @commands.command(name="resqueue")
    async def queue_cmd(self, ctx):
        queue = self.get_music_queue(ctx.guild.id)
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
        if guild_id not in self.music_loop_status:
            self.music_loop_status[guild_id] = False
            
        self.music_loop_status[guild_id] = not self.music_loop_status[guild_id]

        if self.music_loop_status[guild_id]:
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
                log.error(f"Error updating music message after loop for guild {ctx.guild.id}: {e}")

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

    # --- COMMANDS TEMPVOLICE ---
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
        # Hanya tangani error dari cog ini
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
    await bot.add_cog(VoiceFeatures(bot))
