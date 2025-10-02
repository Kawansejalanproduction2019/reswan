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

# --- FILE DATA UNTUK MELACAK RIWAYAT DAN CHANNEL SEMENTARA (Persisten antar restart bot) ---
TEMP_CHANNELS_FILE = 'data/temp_voice_channels.json'
LISTENING_HISTORY_FILE = 'data/listening_history.json'
GUILD_CONFIG_FILE = 'data/guild_config.json'

# --- KONFIGURASI PENGATURAN TEMPOVICE BARU ---
ENABLE_SCHEDULED_CREATION = False
CREATION_START_TIME = (20, 0)
CREATION_END_TIME = (6, 0)

# KONSTANTA TAMBAHAN UNTUK TEMPOVICE
TARGET_REGION = 'singapore' 

def load_json_file(file_path, default_data={}):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if not os.path.exists(file_path) or os.stat(file_path).st_size == 0:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, indent=4)
        return default_data
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, (dict, list)):
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(default_data, f, indent=4)
                return data
            return data
    except json.JSONDecodeError as e:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, indent=4)
        return data
    except Exception as e:
        return default_data

def save_json_file(file_path, data):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def load_temp_channels():
    data = load_json_file(TEMP_CHANNELS_FILE)
    if not isinstance(data, dict):
        return {}
    return data

def save_temp_channels(data):
    save_json_file(TEMP_CHANNELS_FILE, {str(k): v for k, v in data.items()})

def load_listening_history():
    return load_json_file(LISTENING_HISTORY_FILE)

def save_listening_history(data):
    save_json_file(LISTENING_HISTORY_FILE, data)
    
def load_guild_config():
    return load_json_file(GUILD_CONFIG_FILE)

def save_guild_config(data):
    save_json_file(GUILD_CONFIG_FILE, data)
    
# --- Updated YTDL Options for Opus and FFMPEG Options for Stability ---
ytdl_opts = {
    'format': 'bestaudio[ext=opus]/bestaudio[ext=m4a]/bestaudio/best',
    'cookiefile': 'cookies.txt',
    'quiet': True,
    'default_search': 'ytsearch',
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'noplaylist': True,
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
        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
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
                description="Antrean kosong. Bot akan keluar dari voice channel jika tidak ada pengguna lain.",
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
            if interaction.guild.id in self.cog.current_music_message_info:
                old_message_info = self.cog.current_music_message_info[interaction.guild.id]
                try:
                    old_channel = interaction.guild.get_channel(old_message_info['channel_id']) or await interaction.guild.fetch_channel(old_message_info['channel_id'])
                    if old_channel:
                        old_message = await old_channel.fetch_message(old_message_info['message_id'])
                        await old_message.delete()
                except (discord.NotFound, discord.HTTPException) as e:
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
        song_name = None
        if not interaction.guild.id in self.cog.now_playing_info:
            await interaction.response.send_message("Tidak ada lagu yang sedang diputar. Harap gunakan `!reslyrics <nama lagu>` untuk mencari lirik.", ephemeral=True)
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

class RenameVCModal(discord.ui.Modal, title="Ganti Nama Channel Suara"):
    new_name = discord.ui.TextInput(
        label="Nama Baru",
        placeholder="Masukkan nama channel baru...",
        min_length=2,
        max_length=100
    )
    def __init__(self, cog_instance):
        super().__init__()
        self.cog = cog_instance
    async def on_submit(self, interaction: discord.Interaction):
        if not self.cog.is_owner_vc_by_interaction(interaction):
            return await interaction.response.send_message("❌ Kamu bukan pemilik channel ini!", ephemeral=True)
        vc = interaction.user.voice.channel
        new_name = self.new_name.value
        try:
            await vc.edit(name=new_name, reason=f"User {interaction.user.display_name} renamed VC via UI.")
            await interaction.response.send_message(f"✅ Nama channelmu diubah menjadi **{new_name}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot tidak memiliki izin untuk mengubah nama channel ini.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

class VCControlView(discord.ui.View):
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
                        row=4
                    ))
        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
            pass

    async def _check_owner(self, interaction: discord.Interaction):
        if not self.cog.is_owner_vc_by_interaction(interaction):
            await interaction.response.send_message("❌ Kamu bukan pemilik channel ini!", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="➕", label="Batas User +1", style=discord.ButtonStyle.secondary, custom_id="vc:limit_plus", row=0)
    async def limit_plus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        new_limit = min(vc.user_limit + 1, 99)
        try:
            await vc.edit(user_limit=new_limit, reason=f"User {interaction.user.display_name} increased user limit.")
            await interaction.response.send_message(f"✅ Batas user channel diatur ke: **{new_limit}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot tidak memiliki izin untuk mengubah batas user.", ephemeral=True)
    
    @discord.ui.button(emoji="➖", label="Batas User -1", style=discord.ButtonStyle.secondary, custom_id="vc:limit_minus", row=0)
    async def limit_minus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        new_limit = max(vc.user_limit - 1, 0)
        try:
            await vc.edit(user_limit=new_limit, reason=f"User {interaction.user.display_name} decreased user limit.")
            await interaction.response.send_message(f"✅ Batas user channel diatur ke: **{new_limit if new_limit > 0 else 'tak terbatas'}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot tidak memiliki izin untuk mengubah batas user.", ephemeral=True)

    @discord.ui.button(emoji="📝", label="Ganti Nama", style=discord.ButtonStyle.secondary, custom_id="vc:rename", row=1)
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        await interaction.response.send_modal(RenameVCModal(self.cog))

    @discord.ui.button(emoji="🔒", label="Kunci Channel", style=discord.ButtonStyle.secondary, custom_id="vc:lock", row=1)
    async def lock_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        try:
            await vc.set_permissions(interaction.guild.default_role, connect=False, reason=f"User {interaction.user.display_name} locked VC via UI.")
            button.label = "Buka Channel"
            button.emoji = "🔓"
            await interaction.response.send_message(f"✅ Channel **{vc.name}** telah dikunci.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot tidak memiliki izin untuk mengunci channel ini.", ephemeral=True)
    
    @discord.ui.button(emoji="🔓", label="Buka Channel", style=discord.ButtonStyle.secondary, custom_id="vc:unlock", row=1)
    async def unlock_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        try:
            await vc.set_permissions(interaction.guild.default_role, connect=True, reason=f"User {interaction.user.display_name} unlocked VC via UI.")
            button.label = "Kunci Channel"
            button.emoji = "🔒"
            await interaction.response.send_message(f"✅ Channel **{vc.name}** telah dibuka.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot tidak memiliki izin untuk membuka kunci channel ini.", ephemeral=True)

    @discord.ui.button(emoji="👀", label="Sembunyikan", style=discord.ButtonStyle.secondary, custom_id="vc:toggle_visibility", row=2)
    async def toggle_visibility_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        everyone_role = interaction.guild.default_role
        current_permission = vc.overwrites_for(everyone_role).view_channel
        try:
            if current_permission is True:
                await vc.set_permissions(everyone_role, view_channel=False)
                button.label = "Tampilkan Channel"
                await interaction.response.edit_message(view=self)
                await interaction.followup.send("Channel berhasil disembunyikan.", ephemeral=True)
            else:
                await vc.set_permissions(everyone_role, view_channel=True)
                button.label = "Sembunyikan Channel"
                await interaction.response.edit_message(view=self)
                await interaction.followup.send("Channel berhasil ditampilkan.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot tidak memiliki izin untuk mengubah visibilitas channel ini.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
    
    @discord.ui.button(emoji="🔗", label="Invite", style=discord.ButtonStyle.blurple, custom_id="vc:invite", row=2)
    async def invite_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        try:
            invite = await vc.create_invite(max_age=3600, max_uses=1, unique=True, reason=f"Invite created by VC owner {interaction.user.display_name} via UI.")
            await interaction.response.send_message(f"🔗 Ini link undanganmu untuk channel **{vc.name}**: {invite.url}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot tidak memiliki izin untuk membuat link undangan di channel ini.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Terjadi kesalahan saat membuat undangan: {e}", ephemeral=True)

    @discord.ui.button(emoji="🗑️", label="Hapus Channel", style=discord.ButtonStyle.danger, custom_id="vc:delete", row=2)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        vc_id_str = str(vc.id)
        if vc_id_str in self.cog.active_temp_channels:
            del self.cog.active_temp_channels[vc_id_str]
            save_temp_channels(self.cog.active_temp_channels)
        try:
            await vc.delete(reason=f"VC deleted by owner {interaction.user.display_name} via UI.")
            await interaction.response.send_message(f"✅ Channel **{vc.name}** telah dihapus.", ephemeral=True)
        except discord.NotFound:
            await interaction.response.send_message("Channel ini sudah terhapus.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot tidak memiliki izin untuk menghapus channel ini.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Terjadi kesalahan saat menghapus channel: {e}", ephemeral=True)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.loop_status = {}
        self.current_music_message_info = {}
        self.is_muted = {}
        self.old_volume = {}
        self.now_playing_info = {}
        self.listening_history = load_listening_history()
        self.guild_config = load_guild_config()

        GENIUS_API_TOKEN = os.getenv("GENIUS_API")
        self.genius = None
        if GENIUS_API_TOKEN:
            try:
                self.genius = Genius(GENIUS_API_TOKEN)
            except Exception as e:
                log.warning(f"Failed to initialize Genius API: {e}")
        else:
            log.warning("GENIUS_API_TOKEN is not set.")

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
                log.warning(f"Could not initialize Spotify client: {e}")
        else:
            log.warning("SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET not set.")

        self.bot.add_view(MusicControlView(self))
        self.bot.add_view(VCControlView(self))
        self.active_temp_channels = load_temp_channels()
        
        self.cleanup_task.start()
        self.idle_check_task.start()
        
    def cog_unload(self):
        self.cleanup_task.cancel()
        self.idle_check_task.cancel()

    @tasks.loop(seconds=10)
    async def cleanup_task(self):
        channels_to_remove = []
        for channel_id_str, channel_info in list(self.active_temp_channels.items()):
            if not isinstance(channel_info, dict):
                channels_to_remove.append(channel_id_str)
                continue
            channel_id = int(channel_id_str)
            if 'guild_id' not in channel_info or 'owner_id' not in channel_info:
                channels_to_remove.append(channel_id_str)
                continue
            guild_id = int(channel_info["guild_id"])
            guild = self.bot.get_guild(guild_id)
            if not guild:
                channels_to_remove.append(channel_id_str)
                continue
            channel = guild.get_channel(channel_id)
            if not channel:
                channels_to_remove.append(channel_id_str)
                continue
            human_members_in_custom_channel = [
                member for member in channel.members
                if not member.bot
            ]
            if not human_members_in_custom_channel:
                try:
                    await channel.delete(reason="Custom voice channel is empty of human users.")
                    channels_to_remove.append(channel_id_str)
                except discord.NotFound:
                    channels_to_remove.append(channel_id_str)
                except discord.Forbidden:
                    pass
                except Exception as e:
                    pass
        for ch_id in channels_to_remove:
            self.active_temp_channels.pop(ch_id, None)
        if channels_to_remove:
            save_temp_channels(self.active_temp_channels)

    @tasks.loop(seconds=5)
    async def idle_check_task(self):
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if vc and vc.is_connected():
                human_members = [
                    member for member in vc.channel.members
                    if not member.bot
                ]
                num_human_members = len(human_members)
                if num_human_members == 0:
                    if vc.is_playing() or vc.is_paused():
                        vc.stop()
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
                        except (discord.NotFound, discord.HTTPException) as e:
                            pass
                        finally:
                            del self.current_music_message_info[guild.id]

    @idle_check_task.before_loop
    async def before_idle_check_task(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        
        guild_id_str = str(member.guild.id)
        config = self.guild_config.get(guild_id_str, {})
        trigger_vc_id = config.get('trigger_vc_id')
        target_cat_id = config.get('target_category_id')

        if not trigger_vc_id or not target_cat_id:
            return

        if after.channel and after.channel.id == trigger_vc_id:
            if ENABLE_SCHEDULED_CREATION:
                now = datetime.now()
                start_time = now.replace(hour=CREATION_START_TIME[0], minute=CREATION_START_TIME[1], second=0, microsecond=0)
                end_time = now.replace(hour=CREATION_END_TIME[0], minute=CREATION_END_TIME[1], second=0, microsecond=0)
                if CREATION_END_TIME < CREATION_START_TIME:
                    if now < start_time and now > end_time:
                        return await self.send_scheduled_message(member, "❌ Maaf, pembuatan channel pribadi hanya tersedia pada waktu yang ditentukan.")
                elif not (start_time <= now <= end_time):
                    return await self.send_scheduled_message(member, "❌ Maaf, pembuatan channel pribadi hanya tersedia pada waktu yang ditentukan.")
            
            for ch_id_str, ch_info in list(self.active_temp_channels.items()):
                if not isinstance(ch_info, dict):
                    continue
                if ch_info.get("owner_id") == str(member.id) and ch_info.get("guild_id") == guild_id_str:
                    existing_channel = member.guild.get_channel(int(ch_id_str))
                    if existing_channel:
                        try:
                            await member.move_to(existing_channel)
                            return
                        except discord.Forbidden:
                            return
                        except Exception as e:
                            return
                    else:
                        self.active_temp_channels.pop(ch_id_str)
                        save_temp_channels(self.active_temp_channels)
            guild = member.guild
            category = guild.get_channel(target_cat_id)
            if not category or not isinstance(category, discord.CategoryChannel):
                try: await member.send("❌ Gagal membuat channel suara pribadi: Kategori tujuan tidak ditemukan atau tidak valid. Hubungi admin server.")
                except discord.Forbidden: pass
                try: await member.move_to(None, reason="Target category invalid.")
                except: pass
                return
            current_category_channels = [ch for ch in category.voice_channels if ch.name.startswith("Music ")]
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
                    except Exception:
                        continue
                next_channel_number = max_num + 1
            new_channel_name = f"Music {next_channel_number}"
            try:
                everyone_role = guild.default_role
                overwrites = {
                    everyone_role: discord.PermissionOverwrite(connect=False, speak=False, view_channel=True),
                    guild.me: discord.PermissionOverwrite(connect=True, speak=True, send_messages=True, view_channel=True, read_message_history=True),
                    member: discord.PermissionOverwrite(
                        connect=True, speak=True, send_messages=True, view_channel=True,
                        manage_channels=True, manage_roles=True,
                        mute_members=True, deafen_members=True, move_members=True
                    )
                }
                
                # --- Implementasi Bitrate Dinamis ---
                # Mengambil batas bitrate maksimum yang diizinkan oleh Level Boost Server
                dynamic_bitrate = guild.bitrate_limit
                bitrate_to_set = dynamic_bitrate
                bitrate_kbps = bitrate_to_set // 1000 
                
                new_vc = await guild.create_voice_channel(
                    name=new_channel_name,
                    category=category,
                    user_limit=0,
                    overwrites=overwrites,
                    bitrate=bitrate_to_set, 
                    rtc_region=TARGET_REGION,
                    reason=f"{member.display_name} created a temporary voice channel with max server bitrate ({bitrate_kbps}kbps) and {TARGET_REGION} region."
                )
                
                await member.move_to(new_vc)
                self.active_temp_channels[str(new_vc.id)] = {"owner_id": str(member.id), "guild_id": guild_id_str}
                save_temp_channels(self.active_temp_channels)
                
                embed = discord.Embed(
                    title="🎉 Channel Pribadimu Dibuat!",
                    description=f"Selamat datang di **{new_vc.name}**, {member.mention}! Kamu adalah pemilik channel ini.\n"
                                 f"**Bitrate diatur maksimal ({bitrate_kbps} kbps)** dan **Region diatur ke {TARGET_REGION.upper()}**.\n"
                                 f"Gunakan tombol di bawah untuk mengelola channelmu tanpa perintah teks.\n"
                                 f"Channel ini akan otomatis dihapus jika tidak ada user di dalamnya.",
                    color=discord.Color.green()
                )
                embed.add_field(name="User Limit (Batas Pengguna)", value="""
                Secara default, batas pengguna diatur ke **tak terbatas** (**0**). 
                Ini berarti siapa pun yang Anda izinkan dapat bergabung. 
                Gunakan tombol `➕` dan `➖` untuk mengubahnya, atau `!vcsetlimit <angka>` untuk mengatur batas tertentu.
                """, inline=False)
                view = VCControlView(self)
                await new_vc.send(embed=embed, view=view)
            except discord.Forbidden:
                try: await member.send(f"❌ Gagal membuat channel suara pribadi: Bot tidak memiliki izin yang cukup (Manage Channels atau Move Members). Hubungi admin server.")
                except discord.Forbidden: pass
                try: await member.move_to(None, reason="Bot lacks permissions.")
                except: pass
            except Exception as e:
                try: await member.send(f"❌ Terjadi kesalahan saat memindahkan Anda ke channel pribadi Anda: {e}. Hubungi admin server.")
                except discord.Forbidden: pass
                try: await member.move_to(None, reason="Unexpected error.")
                except: pass

        if before.channel and str(before.channel.id) in self.active_temp_channels:
            channel_info = self.active_temp_channels[str(before.channel.id)]
            if channel_info.get("owner_id") == str(member.id) and not before.channel.members:
                pass
    
    def is_owner_vc(self, ctx):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return False
        channel_id_str = str(ctx.author.voice.channel.id)
        guild_id_str = str(ctx.guild.id)
        if channel_id_str not in self.active_temp_channels:
            return False
        channel_info = self.active_temp_channels[channel_id_str]
        if channel_info.get("guild_id") != guild_id_str:
            return False
        is_owner = channel_info.get("owner_id") == str(ctx.author.id)
        return is_owner
        
    def is_owner_vc_by_interaction(self, interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return False
        channel_id_str = str(interaction.user.voice.channel.id)
        guild_id_str = str(interaction.guild.id)
        if channel_id_str not in self.active_temp_channels:
            return False
        channel_info = self.active_temp_channels[channel_id_str]
        if channel_info.get("guild_id") != guild_id_str:
            return False
        is_owner = channel_info.get("owner_id") == str(interaction.user.id)
        return is_owner

    def get_queue(self, guild_id):
        return self.queues.setdefault(guild_id, [])

    def add_song_to_history(self, user_id, song_info):
        user_id_str = str(user_id)
        if user_id_str not in self.listening_history:
            self.listening_history[user_id_str] = []
        if not isinstance(self.listening_history[user_id_str], list):
             self.listening_history[user_id_str] = []
        
        self.listening_history[user_id_str].insert(0, song_info)
        
        if len(self.listening_history[user_id_str]) > 50:
            self.listening_history[user_id_str] = self.listening_history[user_id_str][:50]
        save_listening_history(self.listening_history)

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
                await ctx.send("Antrean kosong. Bot akan keluar dari voice channel jika tidak ada pengguna lain.", ephemeral=True)
            return
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
        new_urls = []
        
        # 1. Ambil URL dari riwayat putar pengguna
        user_history = self.listening_history.get(user_id_str, [])
        
        if not isinstance(user_history, list):
            user_history = []
        
        if user_history:
            # Menggunakan set untuk menghindari duplikat dalam riwayat
            filtered_history_urls = [s['webpage_url'] for s in user_history if 'webpage_url' in s]
            
            # Acak dan ambil yang paling atas
            if filtered_history_urls:
                random.shuffle(filtered_history_urls)
                urls_from_history = filtered_history_urls[:num_songs]
                new_urls.extend(urls_from_history)

        # 2. Jika masih kurang, ambil dari trending music umum
        if len(new_urls) < num_songs:
            search_query = "trending music"
            try:
                info = await asyncio.to_thread(lambda: ytdl.extract_info(search_query, download=False, process=True))
                if 'entries' in info and isinstance(info.get('entries'), list):
                    filtered_entries_urls = [entry['webpage_url'] for entry in info['entries'] if 'webpage_url' in entry]
                    
                    if filtered_entries_urls:
                        random.shuffle(filtered_entries_urls)
                        urls_from_search = filtered_entries_urls[:num_songs - len(new_urls)]
                        new_urls.extend(urls_from_search)
            except Exception as e:
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

    async def send_scheduled_message(self, member, message_content):
        try:
            await member.move_to(None)
        except Exception:
            pass
        # Perbaikan: Menghapus 'ephemeral=True' dari member.send()
        try:
            await member.send(message_content)
        except discord.Forbidden:
            pass
    
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

    @commands.command(name="resskip")
    async def skip_cmd(self, ctx):
        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            return await ctx.send("Tidak ada lagu yang sedang diputar.", ephemeral=True)
        guild_id = ctx.guild.id
        queue = self.get_queue(guild_id)
        if queue:
            queue.pop(0)
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
            await ctx.send("Antrean kosong.", ephemeral=True)
            
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
        await self._send_lyrics(interaction_or_ctx=ctx, song_name_override=song_name)

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
    
    @commands.command(name="resprandom")
    async def personal_random(self, ctx, *urls):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            if not ctx.voice_client:
                return await ctx.send("Gagal bergabung ke voice channel.", ephemeral=True)
        await ctx.defer()
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
            return await ctx.send("❌ Tidak dapat menemukan lagu untuk dimainkan. Pastikan riwayat Anda tidak kosong, atau coba lagi nanti.", ephemeral=True)
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await ctx.send("🎧 Memulai mode acak pribadi. Menambahkan 10 lagu ke antrean.", ephemeral=True)
            await self.play_next(ctx)
        else:
            await ctx.send(f"🎧 Menambahkan 10 lagu acak ke antrean.", ephemeral=True)
            
    @commands.command(name="settriger", help="[ADMIN] Mengatur saluran suara pemicu untuk server ini.")
    @commands.has_permissions(administrator=True)
    async def set_trigger_channel(self, ctx, channel_id: int):
        try:
            channel = ctx.guild.get_channel(channel_id) or await ctx.guild.fetch_channel(channel_id)
            if not isinstance(channel, discord.VoiceChannel):
                return await ctx.send("❌ ID yang diberikan bukan saluran suara.", ephemeral=True)
            self.guild_config[str(ctx.guild.id)] = self.guild_config.get(str(ctx.guild.id), {})
            self.guild_config[str(ctx.guild.id)]['trigger_vc_id'] = channel_id
            save_guild_config(self.guild_config)
            await ctx.send(f"✅ Saluran pemicu untuk server ini telah diatur ke **{channel.name}**.", ephemeral=True)
        except (discord.NotFound, discord.Forbidden):
            await ctx.send("❌ Saluran tidak ditemukan atau bot tidak memiliki izin untuk melihatnya.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    @commands.command(name="setcat", help="[ADMIN] Mengatur kategori target untuk saluran sementara.")
    @commands.has_permissions(administrator=True)
    async def set_target_category(self, ctx, category_id: int):
        try:
            category = ctx.guild.get_channel(category_id) or await ctx.guild.fetch_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                return await ctx.send("❌ ID yang diberikan bukan kategori.", ephemeral=True)
            self.guild_config[str(ctx.guild.id)] = self.guild_config.get(str(ctx.guild.id), {})
            self.guild_config[str(ctx.guild.id)]['target_category_id'] = category_id
            save_guild_config(self.guild_config)
            await ctx.send(f"✅ Kategori target untuk saluran sementara telah diatur ke **{category.name}**.", ephemeral=True)
        except (discord.NotFound, discord.Forbidden):
            await ctx.send("❌ Kategori tidak ditemukan atau bot tidak memiliki izin untuk melihatnya.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    @commands.command(name="vclock", help="Kunci channel pribadimu (hanya bisa masuk via invite/grant).")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_lock(self, ctx):
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(ctx.guild.default_role, connect=False, reason=f"User {ctx.author.display_name} locked VC.")
            await ctx.send(f"✅ Channel **{vc.name}** telah dikunci. Hanya user dengan izin khusus yang bisa bergabung.", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengunci channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    @commands.command(name="vcunlock", help="Buka kunci channel pribadimu.")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_unlock(self, ctx):
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(ctx.guild.default_role, connect=True, reason=f"User {ctx.author.display_name} unlocked VC.")
            await ctx.send(f"✅ Channel **{vc.name}** telah dibuka. Sekarang siapa pun bisa bergabung.", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk membuka kunci channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    @commands.command(name="vcsetlimit", help="Atur batas user di channel suara pribadimu (0 untuk tak terbatas).")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_set_limit(self, ctx, limit: int):
        if limit < 0 or limit > 99:
            return await ctx.send("❌ Batas user harus antara 0 (tak terbatas) hingga 99.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            await vc.edit(user_limit=limit, reason=f"User {ctx.author.display_name} set user limit.")
            await ctx.send(f"✅ Batas user channelmu diatur ke: **{limit if limit > 0 else 'tak terbatas'}**.", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengubah batas user channel ini. Pastikan bot memiliki izin 'Manage Channels'.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

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
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengubah nama channel ini. Pastikan bot memiliki izin 'Manage Channels'.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

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
            except discord.Forbidden:
                await ctx.send("❌ Bot tidak memiliki izin untuk menendang pengguna ini. Pastikan bot memiliki izin 'Move Members'.", ephemeral=True)
            except Exception as e:
                await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
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
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk memberikan izin di channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    @commands.command(name="vcrevoke")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_revoke(self, ctx, member: discord.Member):
        if member.bot:
            return await ctx.send("❌ Kamu tidak bisa mencabut izin dari bot.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(member, connect=False, reason=f"VC owner {ctx.author.display_name} revoked access.")
            await ctx.send(f"✅ Izin **{member.display_name}** untuk bergabung ke channelmu telah dicabut.", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mencabut izin di channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

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
            if vc_id_str not in self.active_temp_channels or not isinstance(self.active_temp_channels[vc_id_str], dict):
                return await ctx.send("❌ Terjadi kesalahan internal. Data channelmu rusak.", ephemeral=True)
            self.active_temp_channels[vc_id_str]["owner_id"] = str(new_owner.id)
            save_temp_channels(self.active_temp_channels)
            old_owner_overwrites = vc.overwrites_for(ctx.author)
            old_owner_overwrites.manage_channels = None
            old_owner_overwrites.manage_roles = None
            old_owner_overwrites.mute_members = None
            old_owner_overwrites.deafen_members = None
            old_owner_overwrites.move_members = None
            await vc.set_permissions(ctx.author, overwrite=old_owner_overwrites, reason=f"Transfer ownership from {ctx.author.display_name}.")
            new_owner_overwrites = vc.overwrites_for(new_owner)
            new_owner_overwrites.manage_channels = True
            new_owner_overwrites.manage_roles = True
            new_owner_overwrites.mute_members = True
            new_owner_overwrites.deafen_members = True
            new_owner_overwrites.move_members = True
            await vc.set_permissions(new_owner, overwrite=new_owner_overwrites, reason=f"Transfer ownership to {new_owner.display_name}.")
            await ctx.send(f"✅ Kepemilikan channel **{vc.name}** telah ditransfer dari {ctx.author.mention} ke {new_owner.mention}!", ephemeral=True)
            try:
                await new_owner.send(
                    f"🎉 Selamat! Anda sekarang adalah pemilik channel suara **{vc.name}** di server **{ctx.guild.name}**!\n"
                    f"Gunakan perintah `!vchelp` untuk melihat cara mengelola channel ini."
                )
            except discord.Forbidden:
                pass
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengalihkan kepemilikan channel ini. Pastikan bot memiliki izin 'Manage Permissions' dan 'Manage Channels'.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan saat mengalihkan kepemilikan: {e}", ephemeral=True)

    @commands.command(name="adminvcowner", help="[ADMIN] Mengatur pemilik saluran suara sementara mana pun.")
    @commands.has_permissions(administrator=True)
    async def admin_vc_transfer_owner(self, ctx, channel: discord.VoiceChannel, new_owner: discord.Member):
        channel_id_str = str(channel.id)
        if channel_id_str not in self.active_temp_channels or not isinstance(self.active_temp_channels[channel_id_str], dict):
            await ctx.send("❌ Saluran ini bukan saluran suara sementara yang terdaftar atau datanya rusak.", ephemeral=True)
            return
        if new_owner.bot:
            await ctx.send("❌ Tidak bisa mengalihkan kepemilikan ke bot.", ephemeral=True)
            return
        old_owner_id = self.active_temp_channels[channel_id_str].get('owner_id')
        old_owner = ctx.guild.get_member(int(old_owner_id)) if old_owner_id else None
        try:
            self.active_temp_channels[channel_id_str]['owner_id'] = str(new_owner.id)
            save_temp_channels(self.active_temp_channels)
            if old_owner and old_owner.id != new_owner.id:
                old_owner_overwrites = channel.overwrites_for(old_owner)
                old_owner_overwrites.manage_channels = None
                old_owner_overwrites.manage_roles = None
                old_owner_overwrites.mute_members = None
                old_owner_overwrites.deafen_members = None
                old_owner_overwrites.move_members = None
                await channel.set_permissions(old_owner, overwrite=old_owner_overwrites, reason=f"Admin transfer ownership from {old_owner.display_name}.")
            new_owner_overwrites = channel.overwrites_for(new_owner)
            new_owner_overwrites.manage_channels = True
            new_owner_overwrites.manage_roles = True
            new_owner_overwrites.mute_members = True
            new_owner_overwrites.deafen_members = True
            new_owner_overwrites.move_members = True
            await channel.set_permissions(new_owner, overwrite=new_owner_overwrites, reason=f"Admin transfer ownership to {new_owner.display_name}.")
            await ctx.send(f"✅ Kepemilikan saluran {channel.mention} telah dialihkan ke {new_owner.mention} (oleh admin).", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengalihkan kepemilikan channel ini. Pastikan bot memiliki izin 'Manage Permissions' dan 'Manage Channels'.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan saat mengalihkan kepemilikan (admin command): {e}", ephemeral=True)

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
        `!vcsetlimit <angka>`: Atur batas jumlah user (0 untuk tak terbatas).
        `!vcrename <nama_baru>`: Ubah nama channel suaramu.
        `!vclock`: Kunci channel (hanya bisa masuk via invite)
        `!vcunlock`: Buka kunci channelmu
        """, inline=False)
        embed.add_field(name="Manajemen User:", value="""
        `!vckick @user`: Tendang user dari channelmu.
        `!vcgrant @user`: Beri user izin masuk channelmu yang terkunci.
        `!vcrevoke @user`: Cabut izin user dari channelmu yang terkunci.
        `!vcowner @user`: Transfer kepemilikan channel ke user lain.
        """, inline=False)
        embed.set_footer(text="Ingat, channel pribadimu akan otomatis terhapus jika kosong!")
        await ctx.send(embed=embed)

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
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Argumen tidak lengkap. Contoh penggunaan: `!{ctx.command.name} {ctx.command.signature}`", ephemeral=True)
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Argumen tidak valid. Pastikan kamu menyebutkan user yang benar atau angka yang valid.", ephemeral=True)
        elif isinstance(error, discord.Forbidden):
            await ctx.send("❌ Bot tidak memiliki izin untuk melakukan tindakan ini. Pastikan role bot berada di atas role lain dan memiliki izin yang diperlukan (misal: 'Manage Channels', 'Move Members', 'Manage Permissions').", ephemeral=True)
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
                "label": "Dukung via Saweria!",
                "url": "https://saweria.co/RH7155"
            },
            {
                "label": "Dukung via Sosiabuzz",
                "url": "https://sociabuzz.com/abogoboga7155/tribe"
            }
        ]
        with open(donation_file_path, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, indent=4)
    await bot.add_cog(Music(bot))
