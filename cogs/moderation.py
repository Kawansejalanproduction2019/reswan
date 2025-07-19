import discord
from discord.ext import commands
import json
import os
import re
import asyncio
from typing import Optional
from datetime import datetime, timedelta
import time
import aiohttp
import sys

# =======================================================================================
# UTILITY FUNCTIONS
# =======================================================================================

def load_data(file_path):
    """Loads data from a JSON file. Returns an empty dict if file not found or empty."""
    try:
        if not os.path.exists(file_path):
            print(f"[{datetime.now()}] [DEBUG HELPER] File not found: {file_path}. Returning empty data.")
            return {}
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                print(f"[{datetime.now()}] [DEBUG HELPER] Empty file: {file_path}. Returning empty data.")
                return {}
            data = json.loads(content)
            print(f"[{datetime.now()}] [DEBUG HELPER] Data successfully loaded from: {file_path}.")
            return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"[{datetime.now()}] [DEBUG HELPER] ERROR loading {file_path}: {e}. Returning empty data.", file=sys.stderr)
        return {}

def save_data(file_path, data):
    """Saves data to a JSON file."""
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        print(f"[{datetime.now()}] [DEBUG HELPER] Data successfully saved to: {file_path}.")
    except Exception as e:
        print(f"[{datetime.now()}] [DEBUG HELPER] ERROR saving {file_path}: {e}.", file=sys.stderr)

def parse_duration(duration_str: str) -> Optional[timedelta]:
    """Converts a duration string (e.g., 10s, 5m, 1h, 1d) into a timedelta object."""
    match = re.match(r"(\d+)([smhd])", duration_str.lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == 's': return timedelta(seconds=value)
    if unit == 'm': return timedelta(minutes=value)
    if unit == 'h': return timedelta(hours=value)
    if unit == 'd': return timedelta(days=value)
    return None

# =======================================================================================
# GLOBAL MODAL CLASS FOR ANNOUNCEMENT (UPDATED FOR WEBHOOKS)
# =======================================================================================
class AnnouncementModalGlobal(discord.ui.Modal, title="Buat Pengumuman"):
    announcement_title = discord.ui.TextInput(
        label="Judul Pengumuman",
        placeholder="Contoh: Pembaruan Server Penting!",
        max_length=256,
        required=True,
        row=0
    )
    custom_username = discord.ui.TextInput(
        label="Pengirim (Contoh: Tim Admin)",
        placeholder="Contoh: Tim Admin / Pengumuman Resmi",
        max_length=256,
        required=True,
        row=1
    )
    custom_profile_url = discord.ui.TextInput(
        label="URL Avatar (Opsional)",
        placeholder="Contoh: https://example.com/avatar.png",
        max_length=2000,
        required=False,
        row=2
    )
    announcement_image_url = discord.ui.TextInput(
        label="URL Gambar (Opsional)",
        placeholder="Contoh: https://example.com/banner.png",
        max_length=2000,
        required=False,
        row=3
    )

    def __init__(self, cog_instance, original_ctx, target_channel_obj, github_raw_url):
        super().__init__()
        self.cog = cog_instance
        self.original_ctx = original_ctx
        self.target_channel_obj = target_channel_obj
        self.github_raw_url = github_raw_url
        self.title = f"Buat Pengumuman untuk #{target_channel_obj.name}"
        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] AnnouncementModalGlobal initialized for {target_channel_obj.name}.")

    async def on_submit(self, interaction: discord.Interaction):
        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] AnnouncementModalGlobal: on_submit triggered by {interaction.user.display_name}.")
        await interaction.response.defer(ephemeral=True)

        title = self.announcement_title.value.strip()
        username = self.custom_username.value.strip()
        profile_url = self.custom_profile_url.value.strip()
        image_url = self.announcement_image_url.value.strip()

        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Modal inputs - Title: '{title}', User: '{username}'.")

        # --- Input Validation ---
        if not username:
            print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Custom username is empty.")
            await interaction.followup.send(embed=self.cog._create_embed(description="❌ Username Pengirim Kustom tidak boleh kosong.", color=self.cog.color_error), ephemeral=True); return
        if profile_url and not (profile_url.startswith("http://") or profile_url.startswith("https://")):
            print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Invalid avatar URL: {profile_url}.")
            await interaction.followup.send(embed=self.cog._create_embed(description="❌ URL Avatar Pengirim tidak valid. Harus dimulai dengan `http://` atau `https://`.", color=self.cog.color_error), ephemeral=True); return
        if image_url and not (image_url.startswith("http://") or image_url.startswith("https://")):
            print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Invalid image URL: {image_url}.")
            await interaction.followup.send(embed=self.cog._create_embed(description="❌ URL Gambar Pengumuman tidak valid. Harus dimulai dengan `http://` atau `https://`.", color=self.cog.color_error), ephemeral=True); return
        
        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Inputs validated. Fetching description from {self.github_raw_url}.")

        # --- Fetch Description from GitHub Raw URL ---
        full_description = ""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.github_raw_url) as resp:
                    print(f"[{datetime.now()}] [DEBUG ANNOUNCE] GitHub fetch status: {resp.status}, Content-Type: {resp.headers.get('Content-Type')}.")
                    if resp.status == 200:
                        full_description = await resp.text()
                        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] GitHub fetch: Description retrieved ({len(full_description)} chars). Start: '{full_description[:100]}...'")
                    else:
                        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] GitHub fetch: Failed (HTTP Status {resp.status}).")
                        await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Gagal mengambil deskripsi dari URL GitHub Raw ({self.github_raw_url}): Status HTTP {resp.status}. Pastikan URL valid dan publik.", color=self.cog.color_error), ephemeral=True); return
        except aiohttp.ClientError as e:
            print(f"[{datetime.now()}] [ERROR ANNOUNCE] GitHub fetch network error: {e}.", file=sys.stderr)
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan jaringan saat mengambil deskripsi dari GitHub: {e}. Pastikan URL GitHub Raw benar.", color=self.cog.color_error), ephemeral=True); return
        except Exception as e:
            print(f"[{datetime.now()}] [ERROR ANNOUNCE] Unexpected error fetching description: {e}.", file=sys.stderr)
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tidak terduga saat mengambil deskripsi: {e}", color=self.cog.color_error), ephemeral=True); return

        if not full_description.strip():
            print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Description from GitHub Raw is empty or only whitespace.")
            await interaction.followup.send(embed=self.cog._create_embed(description="❌ Deskripsi pengumuman dari URL GitHub Raw kosong atau hanya berisi spasi. Pastikan file teks memiliki konten.", color=self.cog.color_error), ephemeral=True); return
        
        description_chunks = [full_description[i:i+4096] for i in range(0, len(full_description), 4096)]
        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Description split into 1 chunks.")

        # --- Get or Create Webhook ---
        try:
            webhook = await self.cog.get_or_create_announcement_webhook(self.target_channel_obj, username)
            print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Webhook ready: {webhook.name}.")
        except discord.Forbidden:
            print(f"[{datetime.now()}] [ERROR ANNOUNCE] Bot lacks permission to manage webhooks.", file=sys.stderr)
            await interaction.followup.send(embed=self.cog._create_embed(description="❌ Bot tidak memiliki izin `Manage Webhooks` untuk mengirim pengumuman via webhook.", color=self.cog.color_error), ephemeral=True)
            return

        # --- MODIFIKASI: Dapatkan URL avatar server untuk default ---
        server_icon_url = self.original_ctx.guild.icon.url if self.original_ctx.guild.icon else None
        
        # --- Create and Send Embeds via Webhook ---
        sent_any_embed = False
        try:
            for i, chunk in enumerate(description_chunks):
                if not chunk.strip(): continue

                embed = discord.Embed(
                    description=chunk,
                    color=self.cog.color_announce,
                    timestamp=discord.utils.utcnow() if i == 0 else discord.Embed.Empty
                )
                
                if i == 0:
                    embed.title = title
                    # --- MODIFIKASI: Gunakan URL dari modal, jika kosong pakai avatar server ---
                    final_avatar_url = profile_url if profile_url else server_icon_url
                    embed.set_author(name=username, icon_url=final_avatar_url)
                    # --- AKHIR MODIFIKASI ---
                    
                    if image_url: embed.set_image(url=image_url)
                    embed.set_footer(text=f"Pengumuman dari {self.original_ctx.guild.name}", icon_url=self.original_ctx.guild.icon.url if self.original_ctx.guild.icon else None)
                else:
                    embed.set_footer(text=f"Lanjutan Pengumuman ({i+1}/{len(description_chunks)})")

                # --- MODIFIKASI: Tambahkan tag @everyone di luar embed, hanya pada chunk pertama ---
                content_message = "@everyone" if i == 0 else ""
                await webhook.send(content=content_message, embed=embed, username=username, avatar_url=final_avatar_url, wait=True)
                # --- AKHIR MODIFIKASI ---

                sent_any_embed = True
                print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Embed #{i+1} sent via webhook to {self.target_channel_obj.name}.")
        except Exception as e:
            print(f"[{datetime.now()}] [ERROR ANNOUNCE] Error sending embed via webhook to {self.target_channel_obj.name}: {e}.", file=sys.stderr)
            if not sent_any_embed:
                await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan saat mengirim pengumuman: {e}", color=self.cog.color_error), ephemeral=True)
            return

        if sent_any_embed:
            await interaction.followup.send(embed=self.cog._create_embed(description=f"✅ Pengumuman berhasil dikirim ke <#{self.target_channel_obj.id}>!", color=self.cog.color_success), ephemeral=True)
            await self.cog.log_action(self.original_ctx.guild, "📢 Pengumuman Baru Dibuat", {"Pengirim (Eksekutor)": self.original_ctx.author.mention, "Pengirim (Tampilan)": f"{username} ({profile_url if profile_url else 'Default'})", "Channel Target": f"<#{self.target_channel_obj.id}>", "Judul": title, "Deskripsi Sumber": self.github_raw_url, "Panjang Deskripsi": f"{len(full_description)} karakter"}, self.cog.color_announce)
            print(f"[{datetime.now()}] [DEBUG ANNOUNCE] AnnouncementModalGlobal: Announcement confirmation and logging complete.")
        else:
            print(f"[{datetime.now()}] [DEBUG ANNOUNCE] AnnouncementModalGlobal: No embeds were successfully sent.")

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f"[{datetime.now()}] [ERROR ANNOUNCE] Error in AnnouncementModalGlobal (on_error): {error}", file=sys.stderr)
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tak terduga saat memproses formulir: {error}", color=self.cog.color_error), ephemeral=True)
        else:
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tak terduga saat memproses formulir: {error}", color=self.cog.color_error), ephemeral=True)

# =======================================================================================
# WELCOME MESSAGE MODAL CLASS
# =======================================================================================
class WelcomeMessageModal(discord.ui.Modal, title="Atur Pesan Selamat Datang"):
    welcome_title = discord.ui.TextInput(
        label="Judul Pesan Selamat Datang",
        placeholder="Contoh: Selamat Datang Anggota Baru!",
        max_length=256,
        required=True,
        row=0
    )
    custom_sender_name = discord.ui.TextInput(
        label="Pengirim (Contoh: Tim Admin)",
        placeholder="Contoh: Tim Admin / Bot Resmi",
        max_length=256,
        required=True,
        row=1
    )
    welcome_content = discord.ui.TextInput(
        label="Isi Pesan (Gunakan {user}, {guild_name})",
        placeholder="Contoh: Halo {user}, selamat datang di {guild_name}!",
        max_length=4000, # Max embed description is 4096, give some buffer
        required=True,
        style=discord.TextStyle.paragraph,
        row=2
    )

    def __init__(self, cog_instance, guild_id, current_settings):
        super().__init__()
        self.cog = cog_instance
        self.guild_id = guild_id
        # Isi dengan nilai saat ini jika ada
        self.welcome_title.default = current_settings.get("welcome_embed_title", "")
        self.custom_sender_name.default = current_settings.get("welcome_sender_name", "")
        self.welcome_content.default = current_settings.get("welcome_message", "Selamat datang di **{guild_name}**, {user}! 🎉")
        print(f"[{datetime.now()}] [DEBUG WELCOME] WelcomeMessageModal initialized for guild {guild_id}.")

    async def on_submit(self, interaction: discord.Interaction):
        print(f"[{datetime.now()}] [DEBUG WELCOME] WelcomeMessageModal: on_submit triggered by {interaction.user.display_name}.")
        await interaction.response.defer(ephemeral=True)

        guild_settings = self.cog.get_guild_settings(self.guild_id)
        
        # Simpan semua nilai baru
        guild_settings["welcome_embed_title"] = self.welcome_title.value.strip()
        guild_settings["welcome_sender_name"] = self.custom_sender_name.value.strip()
        guild_settings["welcome_message"] = self.welcome_content.value.strip()
        
        self.cog.save_settings()
        
        await interaction.followup.send(embed=self.cog._create_embed(description="✅ Pengaturan pesan selamat datang berhasil diperbarui!", color=self.cog.color_success), ephemeral=True)
        
        await self.cog.log_action(
            interaction.guild,
            "🎉 Pengaturan Selamat Datang Diperbarui",
            {
                "Moderator": interaction.user.mention,
                "Judul Embed": guild_settings["welcome_embed_title"],
                "Nama Pengirim": guild_settings["welcome_sender_name"],
                "Isi Pesan": f"```{guild_settings['welcome_message']}```"
            },
            self.cog.color_welcome
        )
        print(f"[{datetime.now()}] [DEBUG WELCOME] Welcome message settings saved and logged for guild {self.guild_id}.")

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f"[{datetime.now()}] [ERROR WELCOME] Error in WelcomeMessageModal (on_error): {error}", file=sys.stderr)
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tak terduga saat memproses formulir: {error}", color=self.cog.color_error), ephemeral=True)
        else:
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tak terduga saat memproses formulir: {error}", color=self.cog.color_error), ephemeral=True)

# =======================================================================================
# SERVER BOOSTER MESSAGE MODAL CLASS
# =======================================================================================
class ServerBoostModal(discord.ui.Modal, title="Atur Pesan Server Booster"):
    boost_title = discord.ui.TextInput(
        label="Judul Pesan Booster",
        placeholder="Contoh: Terima Kasih Server Booster!",
        max_length=256,
        required=True,
        row=0
    )
    custom_sender_name = discord.ui.TextInput(
        label="Pengirim (Contoh: Tim Server)",
        placeholder="Contoh: Tim Server / Bot Resmi",
        max_length=256,
        required=True,
        row=1
    )
    boost_content = discord.ui.TextInput(
        label="Isi Pesan (Gunakan {user}, {guild_name})",
        placeholder="Contoh: Terima kasih, {user}, telah boost {guild_name}!",
        max_length=4000,
        required=True,
        style=discord.TextStyle.paragraph,
        row=2
    )
    boost_image_url = discord.ui.TextInput(
        label="URL Gambar (Opsional, untuk banner)", # Updated label
        placeholder="Contoh: https://example.com/booster_banner.png",
        max_length=2000,
        required=False,
        row=3
    )

    def __init__(self, cog_instance, guild_id, current_settings):
        super().__init__()
        self.cog = cog_instance
        self.guild_id = guild_id
        
        self.boost_title.default = current_settings.get("boost_embed_title", "")
        self.custom_sender_name.default = current_settings.get("boost_sender_name", "")
        self.boost_content.default = current_settings.get("boost_message", "Terima kasih banyak, {user}, telah menjadi **Server Booster** kami di {guild_name}! Kami sangat menghargai dukunganmu! ❤️")
        self.boost_image_url.default = current_settings.get("boost_image_url", "")
        print(f"[{datetime.now()}] [DEBUG BOOSTER] ServerBoostModal initialized for guild {guild_id}.")

    async def on_submit(self, interaction: discord.Interaction):
        print(f"[{datetime.now()}] [DEBUG BOOSTER] ServerBoostModal: on_submit triggered by {interaction.user.display_name}.")
        await interaction.response.defer(ephemeral=True)

        # Input validation for URL
        image_url = self.boost_image_url.value.strip()
        if image_url and not (image_url.startswith("http://") or image_url.startswith("https://")):
            print(f"[{datetime.now()}] [DEBUG BOOSTER] Invalid image URL: {image_url}.")
            await interaction.followup.send(embed=self.cog._create_embed(description="❌ URL Gambar tidak valid. Harus dimulai dengan `http://` atau `https://`.", color=self.cog.color_error), ephemeral=True); return

        guild_settings = self.cog.get_guild_settings(self.guild_id)
        
        guild_settings["boost_embed_title"] = self.boost_title.value.strip()
        guild_settings["boost_sender_name"] = self.custom_sender_name.value.strip()
        guild_settings["boost_message"] = self.boost_content.value.strip()
        guild_settings["boost_image_url"] = image_url # Simpan URL gambar
        
        self.cog.save_settings()
        
        await interaction.followup.send(embed=self.cog._create_embed(description="✅ Pengaturan pesan Server Booster berhasil diperbarui!", color=self.cog.color_success), ephemeral=True)
        
        await self.cog.log_action(
            interaction.guild,
            "✨ Pengaturan Server Booster Diperbarui",
            {
                "Moderator": interaction.user.mention,
                "Judul Embed": guild_settings["boost_embed_title"],
                "Nama Pengirim": guild_settings["boost_sender_name"],
                "Isi Pesan": f"```{guild_settings['boost_message']}```",
                "URL Gambar": guild_settings["boost_image_url"] if guild_settings["boost_image_url"] else "Tidak diatur"
            },
            self.cog.color_announce # Anda bisa menggunakan warna yang berbeda jika mau
        )
        print(f"[{datetime.now()}] [DEBUG BOOSTER] Server Booster message settings saved and logged for guild {self.guild_id}.")

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f"[{datetime.now()}] [ERROR BOOSTER] Error in ServerBoostModal (on_error): {error}", file=sys.stderr)
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tak terduga saat memproses formulir: {error}", color=self.cog.color_error), ephemeral=True)
        else:
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tak terduga saat memproses formulir: {error}", color=self.cog.color_error), ephemeral=True)


# =======================================================================================
# VIEW CLASSES
# =======================================================================================
class AnnounceButtonView(discord.ui.View):
    def __init__(self, bot_instance, cog_instance, original_ctx, target_channel_obj, github_raw_url):
        super().__init__(timeout=60)
        self.bot = bot_instance
        self.cog = cog_instance
        self.original_ctx = original_ctx
        self.target_channel_obj = target_channel_obj
        self.github_raw_url = github_raw_url
        self.message = None # This will be set after the initial message is sent
        print(f"[{datetime.now()}] [DEBUG ADMIN] AnnounceButtonView initialized.")

    @discord.ui.button(label="Buka Formulir Pengumuman", style=discord.ButtonStyle.primary, emoji="📣")
    async def open_announcement_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"[{datetime.now()}] [DEBUG ADMIN] 'Open Announcement Form' button clicked by {interaction.user.display_name}.")
        if interaction.user.id != self.original_ctx.author.id:
            print(f"[{datetime.now()}] [DEBUG ADMIN] AnnounceButtonView: User is not the original caller, blocking.")
            return await interaction.response.send_message("Hanya orang yang memulai perintah yang dapat membuat pengumuman ini.", ephemeral=True)
        
        if not self.original_ctx.author.guild_permissions.manage_guild:
            print(f"[{datetime.now()}] [DEBUG ADMIN] AnnounceButtonView: Original caller lacks 'Manage Server' permission, blocking.")
            return await interaction.response.send_message("Anda tidak memiliki izin `Manage Server` untuk membuat pengumuman.", ephemeral=True)
        
        modal = AnnouncementModalGlobal(self.cog, self.original_ctx, self.target_channel_obj, self.github_raw_url)
        try:
            await interaction.response.send_modal(modal)
            print(f"[{datetime.now()}] [DEBUG ADMIN] AnnounceButtonView: Announcement modal successfully sent.")
        except discord.Forbidden:
            print(f"[{datetime.now()}] [ERROR ADMIN] AnnounceButtonView: Bot Forbidden from sending modal. Check DM permissions or server permissions.", file=sys.stderr)
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Bot tidak memiliki izin untuk mengirim modal (pop-up form). Ini mungkin karena bot tidak bisa mengirim DM ke Anda atau ada masalah izin di server.", color=self.cog.color_error), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan saat menampilkan formulir: {e}", color=self.cog.color_error), ephemeral=True)
            print(f"[{datetime.now()}] [ERROR ADMIN] AnnounceButtonView: Error displaying announcement modal: {e}.", file=sys.stderr)

    async def on_timeout(self) -> None:
        print(f"[{datetime.now()}] [DEBUG ADMIN] AnnounceButtonView: View timeout.")
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
                print(f"[{datetime.now()}] [DEBUG ADMIN] AnnounceButtonView: View message disabled.")
            else:
                print(f"[{datetime.now()}] [DEBUG ADMIN] AnnounceButtonView: View message not found during timeout (not set).")
        except discord.NotFound:
            print(f"[{datetime.now()}] [DEBUG ADMIN] AnnounceButtonView: View message not found during timeout.")
            pass # Message might have been deleted by user/Discord
        except Exception as e:
            print(f"[{datetime.now()}] [ERROR ADMIN] AnnounceButtonView: ERROR disabling buttons on timeout: {e}.", file=sys.stderr)


class ServerAdminCog(commands.Cog, name="👑 Administrasi"):
    def __init__(self, bot):
        self.bot = bot
        self.settings_file = "data/settings.json"
        self.filters_file = "data/filters.json"
        self.warnings_file = "data/warnings.json"
        
        self.common_prefixes = ('!', '.', '?', '-', '$', '%', '&', '#', '+', '=')
        self.url_regex = re.compile(r'https?://[^\s/$.?#].[^\s]*')
        
        self.color_success = 0x2ECC71
        self.color_error = 0xE74C3C
        self.color_info = 0x3498DB
        self.color_warning = 0xF1C40F
        self.color_log = 0x95A5A6
        self.color_welcome = 0x9B59B6
        self.color_announce = 0x7289DA
        self.color_booster = 0xF47FFF # Pinkish color for Discord Nitro Boost

        self.settings = load_data(self.settings_file)
        self.filters = load_data(self.filters_file)
        self.warnings = load_data(self.warnings_file)
        # --- MULAI DARI SINI: Perubahan untuk mendukung Webhooks ---
        for guild_id_str in self.settings.keys():
            if "announcement_webhooks" not in self.settings[guild_id_str]:
                self.settings[guild_id_str]["announcement_webhooks"] = {}
        save_data(self.settings_file, self.settings)
        # --- AKHIR PERUBAHAN ---
        print(f"[{datetime.now()}] [DEBUG ADMIN] ServerAdminCog initialized. Settings: {len(self.settings)} guild, Filters: {len(self.filters)} guild, Warnings: {len(self.warnings)} guild.")

    # --- Helper Methods for Data Management ---
    def get_guild_settings(self, guild_id: int):
        guild_id_str = str(guild_id)
        if guild_id_str not in self.settings:
            self.settings[guild_id_str] = {
                "auto_role_id": None, 
                "welcome_channel_id": None,
                "welcome_message": "Selamat datang di **{guild_name}**, {user}! 🎉",
                "welcome_embed_title": "SELAMAT DATANG!",
                "welcome_sender_name": "Admin Server",
                "log_channel_id": None, 
                "reaction_roles": {},
                "channel_rules": {},
                "boost_channel_id": None,
                "boost_message": "Terima kasih banyak, {user}, telah menjadi **Server Booster** kami di {guild_name}! Kami sangat menghargai dukunganmu! ❤️",
                "boost_embed_title": "TERIMA KASIH SERVER BOOSTER!",
                "boost_sender_name": "Tim Server",
                "boost_image_url": None,
                # --- BARU: TAMBAHKAN KEY UNTUK WEBHOOK ANNOUNCEMENT ---
                "announcement_webhooks": {}
            }
            save_data(self.settings_file, self.settings)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Default settings created for guild {guild_id}.")
        
        # Pastikan field baru ada, untuk kompatibilitas mundur
        if "welcome_embed_title" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["welcome_embed_title"] = "SELAMAT DATANG!"
        if "welcome_sender_name" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["welcome_sender_name"] = "Admin Server"
        if "channel_rules" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["channel_rules"] = {}
        if "boost_channel_id" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["boost_channel_id"] = None
        if "boost_message" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["boost_message"] = "Terima kasih banyak, {user}, telah menjadi **Server Booster** kami di {guild_name}! Kami sangat menghargai dukunganmu! ❤️"
        if "boost_embed_title" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["boost_embed_title"] = "TERIMA KASIH SERVER BOOSTER!"
        if "boost_sender_name" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["boost_sender_name"] = "Tim Server"
        if "boost_image_url" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["boost_image_url"] = None
        # --- BARU: PASTIKAN KEY UNTUK WEBHOOK ANNOUNCEMENT ADA ---
        if "announcement_webhooks" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["announcement_webhooks"] = {}
        # --- AKHIR PASTIKAN FIELD BOOSTER ADA ---
        
        save_data(self.settings_file, self.settings) # Simpan perubahan default
        print(f"[{datetime.now()}] [DEBUG ADMIN] Settings ensured for guild {guild_id}.")
        return self.settings[guild_id_str]
        
    def get_channel_rules(self, guild_id: int, channel_id: int) -> dict:
        guild_settings = self.get_guild_settings(guild_id)
        channel_id_str = str(channel_id)
        if channel_id_str not in guild_settings["channel_rules"]:
            guild_settings["channel_rules"][channel_id_str] = {
                "disallow_bots": False, "disallow_media": False, "disallow_prefix": False,
                "disallow_url": False, "auto_delete_seconds": 0
            }
            save_data(self.settings_file, self.settings)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Default rules created for channel {channel_id} in guild {guild_id}.")
        return guild_settings["channel_rules"][channel_id_str]
        
    def get_guild_filters(self, guild_id: int):
        guild_id_str = str(guild_id)
        if guild_id_str not in self.filters:
            self.filters[guild_id_str] = { "bad_words": [], "link_patterns": [] }
            save_data(self.filters_file, self.filters)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Default filters created for guild {guild_id}.")
        return self.filters[guild_id_str]
        
    def save_settings(self): save_data(self.settings_file, self.settings)
    def save_filters(self): save_data(self.filters_file, self.filters)
    def save_warnings(self): save_data(self.warnings_file, self.warnings)

    # --- Helper Methods for UI & Logging ---
    def _create_embed(self, title: str = "", description: str = "", color: int = 0, author_name: str = "", author_icon_url: str = ""):
        embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
        if author_name: embed.set_author(name=author_name, icon_url=author_icon_url)
        bot_icon_url = self.bot.user.display_avatar.url if self.bot.user.display_avatar else None
        embed.set_footer(text=f"Dijalankan oleh {self.bot.user.name}", icon_url=bot_icon_url)
        return embed

    async def log_action(self, guild: discord.Guild, title: str, fields: dict, color: int):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Logging action: {title} in guild {guild.name}.")
        if not (log_channel_id := self.get_guild_settings(guild.id).get("log_channel_id")):
            print(f"[{datetime.now()}] [DEBUG ADMIN] Log channel not set for guild {guild.name}.")
            return
        if (log_channel := guild.get_channel(log_channel_id)) and log_channel.permissions_for(guild.me).send_messages:
            embed = self._create_embed(title=title, color=color)
            for name, value in fields.items():
                embed.add_field(name=name, value=value, inline=False)
            await log_channel.send(embed=embed)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Action '{title}' successfully logged to {log_channel.name}.")
        else:
            print(f"[{datetime.now()}] [DEBUG ADMIN] Failed to log action '{title}': Channel not found or bot lacks send permissions.")

    # --- BARU: HELPER UNTUK MENGELOLA WEBHOOK ANNOUNCEMENT ---
    async def get_or_create_announcement_webhook(self, channel: discord.TextChannel, custom_name: str):
        guild_settings = self.get_guild_settings(channel.guild.id)
        webhook_url = guild_settings.get("announcement_webhooks", {}).get(str(channel.id))
        
        # Periksa apakah URL webhook valid dan masih berfungsi
        if webhook_url:
            try:
                # --- PERBAIKAN DI SINI: client=self.bot, bukan client=self.bot.session ---
                webhook = discord.Webhook.from_url(webhook_url, client=self.bot)
                await webhook.fetch() # Memastikan webhook masih ada
                print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Using existing webhook for channel {channel.name}.")
                return webhook
            except (discord.NotFound, aiohttp.ClientError):
                print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Existing webhook for {channel.name} not found or invalid. Creating a new one.")
                pass
        
        # Jika tidak ada atau tidak valid, buat yang baru
        try:
            webhook_name = f"{custom_name}" if custom_name else f"Pengumuman Server"
            avatar_url = channel.guild.icon.url if channel.guild.icon else None
            
            # Coba cari webhook yang sudah dibuat oleh bot, jika ada, gunakan itu saja
            existing_webhooks = await channel.webhooks()
            for wh in existing_webhooks:
                if wh.user.id == self.bot.user.id:
                    webhook = wh
                    break
            else: # Jika tidak ada, baru buat
                webhook = await channel.create_webhook(name=webhook_name, avatar=await channel.guild.icon.read() if channel.guild.icon else None, reason="For automatic announcements.")
            
            guild_settings["announcement_webhooks"][str(channel.id)] = webhook.url
            self.save_settings()
            print(f"[{datetime.now()}] [DEBUG ANNOUNCE] New webhook created and saved for {channel.name}.")
            return webhook
        except discord.Forbidden:
            print(f"[{datetime.now()}] [ERROR ANNOUNCE] Bot does not have 'Manage Webhooks' permission in {channel.name}.", file=sys.stderr)
            raise

    # =======================================================================================
    # EVENT LISTENERS
    # =======================================================================================

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        print(f"[{datetime.now()}] [DEBUG ADMIN] on_command_error triggered for command '{ctx.command}': {type(error).__name__}.")
        if isinstance(error, commands.MissingPermissions):
            embed = self._create_embed(description=f"❌ Anda tidak memiliki izin `{', '.join(error.missing_permissions)}` untuk menjalankan perintah ini.", color=self.color_error)
            await ctx.send(embed=embed, delete_after=15)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Error: MissingPermissions. Message sent.")
        elif isinstance(error, commands.CommandNotFound):
            print(f"[{datetime.now()}] [DEBUG ADMIN] Error: CommandNotFound. Ignored.")
            pass
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=self._create_embed(description=f"❌ Anggota tidak ditemukan.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] Error: MemberNotFound. Message sent.")
        elif isinstance(error, commands.UserNotFound):
            await ctx.send(embed=self._create_embed(description=f"❌ Pengguna tidak ditemukan.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] Error: UserNotFound. Message sent.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=self._create_embed(description=f"❌ Argument tidak valid: {error}", color=self.color_error), delete_after=15)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Error: BadArgument. Message sent.")
        else:
            print(f"[{datetime.now()}] [DEBUG ADMIN] Unexpected error on command '{ctx.command}': {error}", file=sys.stderr)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        print(f"[{datetime.now()}] [DEBUG ADMIN] on_member_join triggered for {member.display_name} in {member.guild.name}.")
        guild_settings = self.get_guild_settings(member.guild.id)
        
        if (welcome_channel_id := guild_settings.get("welcome_channel_id")) and (channel := member.guild.get_channel(welcome_channel_id)):
            welcome_message_content = guild_settings.get("welcome_message", "Selamat datang di **{guild_name}**, {user}! 🎉")
            welcome_embed_title = guild_settings.get("welcome_embed_title", "SELAMAT DATANG!")
            welcome_sender_name = guild_settings.get("welcome_sender_name", "Admin Server")

            embed = discord.Embed(
                description=welcome_message_content.format(user=member.mention, guild_name=member.guild.name), 
                color=self.color_welcome,
                timestamp=discord.utils.utcnow()
            )
            
            embed.set_author(name=welcome_sender_name, icon_url=member.guild.icon.url if member.guild.icon else None)
            embed.title = welcome_embed_title 

            # Tambahkan field tambahan yang secara eksplisit me-mention pengguna
            embed.add_field(name="Anggota Baru", value=f"Selamat datang di server kami, {member.mention}!", inline=False)
            
            embed.set_thumbnail(url=member.display_avatar.url)
            
            embed.set_footer(text=f"Kamu adalah anggota ke-{member.guild.member_count}!")
            
            try:
                # Kirim pesan dengan mention di luar embed untuk memastikan notifikasi
                await channel.send(f"Halo, {member.mention}! Selamat datang!", embed=embed)
                print(f"[{datetime.now()}] [DEBUG ADMIN] Welcome message sent to {channel.name} for {member.display_name}.")
            except discord.Forbidden:
                print(f"[{datetime.now()}] [ERROR ADMIN] Bot lacks permissions to send welcome message in {channel.name} for {member.display_name}.", file=sys.stderr)
            except Exception as e:
                print(f"[{datetime.now()}] [ERROR ADMIN] Failed to send welcome message for {member.display_name}: {e}", file=sys.stderr)

        if (auto_role_id := guild_settings.get("auto_role_id")) and (role := member.guild.get_role(auto_role_id)):
            try:
                await member.add_roles(role, reason="Auto Role")
                print(f"[{datetime.now()}] [DEBUG ADMIN] Auto-role {role.name} given to {member.display_name}.")
            except discord.Forbidden:
                print(f"[{datetime.now()}] [DEBUG ADMIN] Bot lacks permissions to assign auto-role {role.name} in {member.guild.name}.", file=sys.stderr)
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.guild.id not in self.settings:
            return # Skip if guild settings not initialized (prevent error on fresh start)

        guild_settings = self.get_guild_settings(before.guild.id)
        boost_channel_id = guild_settings.get("boost_channel_id")
        
        # Periksa apakah boost_channel_id diatur
        if not boost_channel_id:
            return

        boost_channel = before.guild.get_channel(boost_channel_id)
        if not boost_channel or not boost_channel.permissions_for(before.guild.me).send_messages:
            print(f"[{datetime.now()}] [DEBUG BOOSTER] Boost channel not found or bot lacks send permissions in guild {before.guild.name}.")
            return # Channel not set or bot can't send messages there

        # Deteksi status booster berubah dari tidak menjadi iya (memberikan boost baru)
        if not before.premium_since and after.premium_since:
            print(f"[{datetime.now()}] [DEBUG BOOSTER] Member {after.display_name} started boosting {after.guild.name}.")
            
            boost_message_content = guild_settings.get("boost_message", "Terima kasih banyak, {user}, telah menjadi **Server Booster** kami di {guild_name}! Kami sangat menghargai dukunganmu! ❤️")
            boost_embed_title = guild_settings.get("boost_embed_title", "TERIMA KASIH SERVER BOOSTER!")
            boost_sender_name = guild_settings.get("boost_sender_name", "Tim Server")
            boost_image_url = guild_settings.get("boost_image_url") # Mengambil URL gambar yang disetel pengguna

            embed = discord.Embed(
                description=boost_message_content.format(user=after.mention, guild_name=after.guild.name),
                color=self.color_booster, # Menggunakan warna khusus booster
                timestamp=discord.utils.utcnow()
            )
            
            # Menggunakan set_author untuk menampilkan "Njan" atau "Tim Server"
            # icon_url bisa icon guild atau jika ada, icon_url khusus yang disetel user (walaupun di modal ini tidak ada)
            embed.set_author(name=boost_sender_name, icon_url=after.guild.icon.url if after.guild.icon else None)
            embed.title = boost_embed_title
            
            # --- MODIFIKASI UNTUK MENJADIKAN FOTO PROFIL SEBAGAI BANNER UTAMA ---
            # Jika boost_image_url disetel di pengaturan, gunakan itu.
            if boost_image_url:
                embed.set_image(url=boost_image_url) 
            # Jika boost_image_url TIDAK disetel (None/kosong), gunakan avatar user yang nge-boost sebagai gambar utama (banner).
            # Ini adalah bagian yang akan membuat tampilan seperti yang Anda inginkan.
            else: 
                embed.set_image(url=after.display_avatar.url)
            # --- AKHIR MODIFIKASI ---
            
            # Footer: "Di atas foto orang baik • 10/06/2025 1:29" (tanggal akan dinamis)
            # Dan juga menampilkan jumlah boost server seperti di contoh Anda.
            # Perhatikan: Bagian "Di atas foto orang baik" kemungkinan adalah teks statis yang menjadi bagian dari gambar yang Anda upload
            # atau merupakan deskripsi di bawah gambar. Karena embed tidak mendukung teks di atas gambar secara langsung,
            # kita bisa memasukkannya di deskripsi jika memang teks statis, atau di footer jika berhubungan dengan data embed.
            # Untuk meniru tampilan Anda, saya asumsikan itu adalah bagian dari footer.
            
            # Menambahkan waktu saat ini ke footer untuk meniru format tanggal/waktu
            footer_text = f"Jumlah boost server: {after.guild.premium_subscription_count} ✨"
            # Jika Anda ingin menambahkan teks statis seperti "Di atas foto orang baik", bisa diletakkan di sini:
            # footer_text = f"Di atas foto orang baik • {discord.utils.utcnow().strftime('%d/%m/%Y %H:%M')} WIB • Jumlah boost server: {after.guild.premium_subscription_count} ✨"
            # Namun, untuk meniru persis gambar yang Anda kirim, hanya teks jumlah boost dan foto profil sebagai image sudah cukup.
            # Bagian "Di atas foto orang baik" pada gambar contoh Anda terlihat seperti teks di bawah gambar, jadi saya menempatkannya di footer.
            embed.set_footer(text=footer_text)


            try:
                await boost_channel.send(embed=embed)
                await self.log_action(
                    after.guild,
                    "✨ Anggota Baru Jadi Booster!",
                    {"Anggota": after.mention, "Channel Target": boost_channel.mention},
                    self.color_booster
                )
                print(f"[{datetime.now()}] [DEBUG BOOSTER] Server booster message sent for {after.display_name}.")
            except discord.Forbidden:
                print(f"[{datetime.now()}] [ERROR BOOSTER] Bot lacks permissions to send boost message in {boost_channel.name}.", file=sys.stderr)
            except Exception as e:
                print(f"[{datetime.now()}] [ERROR BOOSTER] Failed to send boost message: {e}", file=sys.stderr)

        # Deteksi status booster berubah dari iya menjadi tidak (berhenti boost) - Opsional
        elif before.premium_since and not after.premium_since:
            print(f"[{datetime.now()}] [DEBUG BOOSTER] Member {after.display_name} stopped boosting {after.guild.name}.")
            await self.log_action(
                after.guild,
                "💔 Anggota Berhenti Jadi Booster",
                {"Anggota": after.mention, "Channel Target": boost_channel.mention},
                self.color_warning
            )
        
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.id == self.bot.user.id: return
        
        rules = self.get_channel_rules(message.guild.id, message.channel.id)
        log_fields = {"Pengirim": message.author.mention, "Channel": message.channel.mention, "Isi Pesan": f"```{message.content[:1000]}```"}
        
        if (delay := rules.get("auto_delete_seconds", 0)) > 0:
            try:
                await message.delete(delay=delay)
                print(f"[{datetime.now()}] [DEBUG ADMIN] Message from {message.author.display_name} auto-deleted after {delay} seconds.")
            except discord.NotFound:
                pass # Message might have been deleted by user/Discord already

        if rules.get("disallow_bots") and message.author.bot:
            await message.delete()
            await self.log_action(message.guild, "🛡️ Bot Message Deleted", log_fields, self.color_info)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Bot message from {message.author.display_name} deleted.")
            return

        if message.author.bot:
            return

        if rules.get("disallow_media") and message.attachments:
            await message.delete()
            await message.channel.send(embed=self._create_embed(description=f"🖼️ {message.author.mention}, media/files are not allowed in this channel.", color=self.color_warning), delete_after=10)
            await self.log_action(message.guild, "🖼️ Media Deleted", log_fields, self.color_warning)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Media message from {message.author.display_name} deleted.")
            try:
                dm_embed = self._create_embed(title="Warning: Rule Violation", color=self.color_warning)
                dm_embed.add_field(name="Server", value=message.guild.name, inline=False)
                dm_embed.add_field(name="Violation", value="Your message was deleted because it contained a **URL/link** in a channel where they are not allowed.", inline=False)
                dm_embed.add_field(name="Suggestion", value="Please send links in designated channels. Review server rules.", inline=False)
                await message.author.send(embed=dm_embed)
            except discord.Forbidden: print(f"[{datetime.now()}] [DEBUG ADMIN] Failed to send DM warning to {message.author.display_name} (Forbidden).")
            return
        
        if message.content and message.content.startswith(self.bot.command_prefix):
            command_prefixes = await self.bot.get_prefix(message)
            if not isinstance(command_prefixes, list):
                command_prefixes = [command_prefixes]

            is_actual_command = False
            for prefix in command_prefixes:
                if message.content.startswith(prefix):
                    command_name = message.content[len(prefix):].split(' ')[0]
                    if self.bot.get_command(command_name):
                        is_actual_command = True
                        break
            
            if rules.get("disallow_prefix") and not is_actual_command:
                await message.delete()
                await message.channel.send(embed=self._create_embed(description=f"❗ {message.author.mention}, bot commands are not allowed in this channel.", color=self.color_warning), delete_after=10)
                await self.log_action(message.guild, "❗ Bot Command Deleted", log_fields, self.color_warning)
                print(f"[{datetime.now()}] [DEBUG ADMIN] Message with prefix from {message.author.display_name} deleted (not a valid command).")
                return

        if rules.get("disallow_url") and self.url_regex.search(message.content):
            await message.delete()
            await message.channel.send(embed=self._create_embed(description=f"🔗 {message.author.mention}, links are not allowed in this channel.", color=self.color_warning), delete_after=10)
            await self.log_action(message.guild, "🔗 Link Deleted", log_fields, self.color_warning)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Link message from {message.author.display_name} deleted.")
            try:
                dm_embed = self._create_embed(title="Warning: Rule Violation", color=self.color_warning)
                dm_embed.add_field(name="Server", value=message.guild.name, inline=False)
                dm_embed.add_field(name="Violation", value="Your message was deleted because it contained a **URL/link** in a channel where they are not allowed.", inline=False)
                dm_embed.add_field(name="Suggestion", value="Please send links in designated channels. Review server rules.", inline=False)
                await message.author.send(embed=dm_embed)
            except discord.Forbidden: print(f"[{datetime.now()}] [DEBUG ADMIN] Failed to send DM warning to {message.author.display_name} (Forbidden).")
            return

        guild_filters = self.get_guild_filters(message.guild.id)
        content_lower = message.content.lower()
        for bad_word in guild_filters.get("bad_words", []):
            if bad_word.lower() in content_lower:
                await message.delete()
                await message.channel.send(embed=self._create_embed(description=f"🤫 Message from {message.author.mention} deleted due to rule violation.", color=self.color_warning), delete_after=10)
                await self.log_action(message.guild, "🚫 Message Censored (Bad Word)", log_fields, self.color_warning)
                print(f"[{datetime.now()}] [DEBUG ADMIN] Bad word message from {message.author.display_name} deleted.")
                return
        for pattern in guild_filters.get("link_patterns", []):
            try:
                if re.search(pattern, message.content):
                    await message.delete()
                    await message.channel.send(embed=self._create_embed(description=f"🚨 {message.author.mention}, that type of link is not allowed here.", color=self.color_warning), delete_after=10)
                    await self.log_action(message.guild, "🔗 Message Censored (Link Pattern)", log_fields, self.color_warning)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] Link pattern message from {message.author.display_name} deleted.")
                    return
            except re.error as e:
                print(f"[{datetime.now()}] [DEBUG ADMIN] ERROR: Invalid regex filter pattern '{pattern}': {e}", file=sys.stderr)
        
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.member is None or payload.member.bot: return
        print(f"[{datetime.now()}] [DEBUG ADMIN] on_raw_reaction_add triggered by {payload.member.display_name} in guild {payload.guild_id}.")

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            print(f"[{datetime.now()}] [DEBUG ADMIN] on_raw_reaction_add: Guild not found for payload {payload.guild_id}.")
            return
        
        guild_settings = self.get_guild_settings(payload.guild_id)
        role_map = guild_settings.get("reaction_roles", {}).get(str(payload.message_id))
        
        if role_map and (role_id := role_map.get(str(payload.emoji))):
            if (role := guild.get_role(role_id)):
                try:
                    await payload.member.add_roles(role, reason="Reaction Role")
                    print(f"[{datetime.now()}] [DEBUG ADMIN] Reaction Role: {role.name} given to {payload.member.display_name}.")
                except discord.Forbidden:
                    print(f"[{datetime.now()}] [DEBUG ADMIN] Bot lacks permissions to assign reaction role {role.name} to {payload.member.display_name} in {guild.name}.", file=sys.stderr)
                except Exception as e:
                    print(f"[{datetime.now()}] [DEBUG ADMIN] Error assigning reaction role: {e}.", file=sys.stderr)
            else:
                print(f"[{datetime.now()}] [DEBUG ADMIN] Reaction Role: Role with ID {role_id} not found in guild {guild.name}.")
        else:
            print(f"[{datetime.now()}] [DEBUG ADMIN] Reaction Role: No reaction role settings for message {payload.message_id} or emoji {payload.emoji}.")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None: return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild or not (member := guild.get_member(payload.user_id)) or member.bot: return
        print(f"[{datetime.now()}] [DEBUG ADMIN] on_raw_reaction_remove triggered by {member.display_name} in guild {payload.guild_id}.")

        guild_settings = self.get_guild_settings(payload.guild_id)
        role_map = guild_settings.get("reaction_roles", {}).get(str(payload.message_id))
        
        if role_map and (role_id := role_map.get(str(payload.emoji))):
            if (role := guild.get_role(role_id)):
                if role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Reaction Role Removed")
                        print(f"[{datetime.now()}] [DEBUG ADMIN] Reaction Role Removed: {role.name} removed from {member.display_name}.")
                    except discord.Forbidden:
                        print(f"[{datetime.now()}] [DEBUG ADMIN] Bot lacks permissions to remove reaction role {role.name} from {member.display_name} in {guild.name}.", file=sys.stderr)
                    except Exception as e:
                        print(f"[{datetime.now()}] [DEBUG ADMIN] Error removing reaction role: {e}.", file=sys.stderr)
                else:
                    print(f"[{datetime.now()}] [DEBUG ADMIN] Reaction Role Removed: {member.display_name} does not have role {role.name}.")
            else:
                print(f"[{datetime.now()}] [DEBUG ADMIN] Reaction Role Removed: Role with ID {role_id} not found in guild {guild.name}.")
        else:
            print(f"[{datetime.now()}] [DEBUG ADMIN] Reaction Role Removed: No reaction role settings for message {payload.message_id} or emoji {payload.emoji}.")

    # =======================================================================================
    # MODERATION COMMANDS
    # =======================================================================================

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: Optional[str] = "No reason provided."):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !kick called by {ctx.author.display_name} for {member.display_name}.")
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot kick a member with an equal or higher role.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role: # Tambahan pemeriksaan peran bot
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat menendang anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return
        if member.id == ctx.guild.owner.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot kick the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot kick this bot itself.", color=self.color_error)); return

        try:
            await member.kick(reason=reason)
            await ctx.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has been kicked.", color=self.color_success))
            await self.log_action(ctx.guild, "👢 Member Kicked", {"Member": f"{member} ({member.id})", "Moderator": ctx.author.mention, "Reason": reason}, self.color_warning)
            print(f"[{datetime.now()}] [DEBUG ADMIN] {member.display_name} successfully kicked.")
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to kick this member. Ensure the bot's role is higher.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !kick: Bot Forbidden.")
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while kicking the member: {e}", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !kick: ERROR: {e}.", file=sys.stderr)

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: Optional[str] = "No reason provided."):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !ban called by {ctx.author.display_name} for {member.display_name}.")
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner: await ctx.send(embed=self._create_embed(description="❌ You cannot ban a member with an equal or higher role.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role: # Tambahan pemeriksaan peran bot
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat memblokir anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return
        if member.id == ctx.guild.owner.id: await ctx.send(embed=self._create_embed(description="❌ You cannot ban the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id: await ctx.send(embed=self._create_embed(description="❌ You cannot ban this bot itself.", color=self.color_error)); return

        try:
            await member.ban(reason=reason)
            await ctx.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has been banned.", color=self.color_success))
            await self.log_action(ctx.guild, "🔨 Member Banned", {"Member": f"{member} ({member.id})", "Moderator": ctx.author.mention, "Reason": reason}, self.color_error)
            print(f"[{datetime.now()}] [DEBUG ADMIN] {member.display_name} successfully banned.")
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to ban this member. Ensure the bot's role is higher.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !ban: Bot Forbidden.")
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while banning the member: {e}", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !ban: ERROR: {e}.", file=sys.stderr)

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, *, user_identifier: str, reason: Optional[str] = "No reason provided."):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !unban called by {ctx.author.display_name} for '{user_identifier}'.")
        user_to_unban = None
        try:
            user_id = int(user_identifier)
            temp_user = await self.bot.fetch_user(user_id)
            user_to_unban = temp_user
            print(f"[{datetime.now()}] [DEBUG ADMIN] !unban: User found by ID: {user_to_unban.display_name}.")
        except ValueError:
            print(f"[{datetime.now()}] [DEBUG ADMIN] !unban: '{user_identifier}' is not an ID, searching by Name#Tag.")
            for entry in [entry async for entry in ctx.guild.bans()]:
                if str(entry.user).lower() == user_identifier.lower():
                    user_to_unban = entry.user
                    print(f"[{datetime.now()}] [DEBUG ADMIN] !unban: User found by Name#Tag: {user_to_unban.display_name}.")
                    break
        except discord.NotFound:
            print(f"[{datetime.now()}] [DEBUG ADMIN] !unban: User not found in Discord API.")
            pass

        if user_to_unban is None:
            await ctx.send(embed=self._create_embed(description=f"❌ User `{user_identifier}` not found in ban list or invalid ID/Name#Tag.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !unban: User not found for unban.")
            return

        try:
            await ctx.guild.unban(user_to_unban, reason=reason)
            await ctx.send(embed=self._create_embed(description=f"✅ Ban for **{user_to_unban}** has been lifted.", color=self.color_success))
            await self.log_action(ctx.guild, "🤝 Ban Lifted", {"User": f"{user_to_unban} ({user_to_unban.id})", "Moderator": ctx.author.mention, "Reason": reason}, self.color_success)
            print(f"[{datetime.now()}] [DEBUG ADMIN] {user_to_unban.display_name} successfully unbanned.")
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to unban this member. Ensure the bot's role is higher.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !unban: Bot Forbidden.")
        except discord.NotFound:
            await ctx.send(embed=self._create_embed(description=f"❌ User `{user_to_unban}` not found in ban list.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !unban: User not in ban list.")
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while unbanning: {e}", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !unban: ERROR: {e}.", file=sys.stderr)

    @commands.command(name="warn")
    @commands.has_permissions(kick_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !warn called by {ctx.author.display_name} for {member.display_name} with reason: '{reason}'.")
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot warn a member with an equal or higher role.", color=self.color_error))
            return
        if member.bot:
            await ctx.send(embed=self._create_embed(description="❌ You cannot warn a bot.", color=self.color_error)); return
        if member.id == ctx.guild.owner.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot warn the server owner.", color=self.color_error)); return

        timestamp = int(time.time())
        warning_data = {
            "moderator_id": ctx.author.id,
            "timestamp": timestamp,
            "reason": reason
        }
        guild_id_str = str(ctx.guild.id)
        member_id_str = str(member.id)
        
        self.warnings.setdefault(guild_id_str, {}).setdefault(member_id_str, []).append(warning_data)
        self.save_warnings()
        print(f"[{datetime.now()}] [DEBUG ADMIN] Warning saved for {member.display_name}.")

        try:
            dm_embed = self._create_embed(title=f"🚨 You Received a Warning in {ctx.guild.name}", color=self.color_warning)
            dm_embed.add_field(name="Warning Reason", value=reason, inline=False)
            dm_embed.set_footer(text=f"Warning issued by {ctx.author.display_name}")
            await member.send(embed=dm_embed)
            dm_sent = True
            print(f"[{datetime.now()}] [DEBUG ADMIN] DM warning successfully sent to {member.display_name}.")
        except discord.Forbidden:
            dm_sent = False
            print(f"[{datetime.now()}] [DEBUG ADMIN] Failed to send DM warning to {member.display_name} (Forbidden).")

        confirm_desc = f"✅ **{member.display_name}** has been warned."
        if not dm_sent:
            confirm_desc += "\n*(Warning message could not be sent to user's DMs.)*"
            
        await ctx.send(embed=self._create_embed(description=confirm_desc, color=self.color_success))
        await self.log_action(ctx.guild, "⚠️ Member Warned", {"Member": f"{member} ({member.id})", "Moderator": ctx.author.mention, "Reason": reason}, self.color_warning)

    @commands.command(name="unwarn")
    @commands.has_permissions(kick_members=True)
    async def unwarn(self, ctx, member: discord.Member, warning_index: int, *, reason: Optional[str] = "Admin error."):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !unwarn called by {ctx.author.display_name} for {member.display_name} (index {warning_index}).")
        guild_id_str = str(ctx.guild.id)
        member_id_str = str(member.id)
        
        user_warnings = self.warnings.get(guild_id_str, {}).get(member_id_str, [])
        
        if not user_warnings:
            await ctx.send(embed=self._create_embed(description=f"❌ **{member.display_name}** has no warnings.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !unwarn: {member.display_name} has no warnings.")
            return

        if not (0 < warning_index <= len(user_warnings)):
            await ctx.send(embed=self._create_embed(description=f"❌ Invalid warning index. Use `!warnings {member.mention}` to see the warning list.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !unwarn: Invalid warning index ({warning_index}).")
            return
        
        removed_warning = self.warnings[guild_id_str][member_id_str].pop(warning_index - 1)
        self.save_warnings()
        print(f"[{datetime.now()}] [DEBUG ADMIN] Warning {warning_index} removed for {member.display_name}.")
        
        await ctx.send(embed=self._create_embed(description=f"✅ Warning #{warning_index} for **{member.display_name}** has been removed.", color=self.color_success))
        
        log_fields = {
            "Member": f"{member} ({member.id})",
            "Moderator": ctx.author.mention,
            "Reason for Removal": reason,
            "Removed Warning": f"`{removed_warning['reason']}`"
        }
        await self.log_action(ctx.guild, "👍 Warning Removed", log_fields, self.color_success)

    @commands.command(name="warnings", aliases=["history"])
    @commands.has_permissions(kick_members=True)
    async def warnings(self, ctx, member: discord.Member):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !warnings called by {ctx.author.display_name} for {member.display_name}.")
        guild_id_str = str(ctx.guild.id)
        member_id_str = str(member.id)
        
        user_warnings = self.warnings.get(guild_id_str, {}).get(member_id_str, [])
        
        if not user_warnings:
            await ctx.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has no warning history.", color=self.color_success))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !warnings: {member.display_name} has no warning history.")
            return

        embed = self._create_embed(title=f"Warning History for {member.display_name}", color=self.color_info)
        embed.set_thumbnail(url=member.display_avatar.url)

        for idx, warn_data in enumerate(user_warnings, 1):
            moderator = await self.bot.fetch_user(warn_data.get('moderator_id', 0))
            timestamp = warn_data.get('timestamp', 0)
            reason = warn_data.get('reason', 'N/A')
            field_value = f"**Reason:** {reason}\n**Moderator:** {moderator.mention if moderator else 'Unknown'}\n**Date:** <t:{timestamp}:F>"
            embed.add_field(name=f"Warning #{idx}", value=field_value, inline=False)
            print(f"[{datetime.now()}] [DEBUG ADMIN] !warnings: Adding warning #{idx}.")
            
        await ctx.send(embed=embed)
        print(f"[{datetime.now()}] [DEBUG ADMIN] !warnings: Warning history sent.")

    @commands.command(name="timeout", aliases=["mute"])
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, duration: str, *, reason: Optional[str] = "No reason provided."):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !timeout called by {ctx.author.display_name} for {member.display_name} for {duration}.")
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot timeout a member with an equal or higher role.", color=self.color_error)); return
        if member.id == ctx.guild.owner.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot timeout the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot timeout this bot itself.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role: # Tambahan pemeriksaan peran bot
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat memberi timeout anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return


        delta = parse_duration(duration)
        if not delta: await ctx.send(embed=self._create_embed(description="❌ Invalid duration format. Use `s` (seconds), `m` (minutes), `h` (hours), `d` (days). Example: `10m`.", color=self.color_error)); return
        if delta.total_seconds() > 2419200:
            await ctx.send(embed=self._create_embed(description="❌ Timeout duration cannot exceed 28 days.", color=self.color_error)); return

        try:
            await member.timeout(delta, reason=reason)
            await ctx.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has been timed out for `{duration}`.", color=self.color_success))
            await self.log_action(ctx.guild, "🤫 Member Timeout", {"Member": f"{member} ({member.id})", "Duration": duration, "Moderator": ctx.author.mention, "Reason": reason}, self.color_warning)
            print(f"[{datetime.now()}] [DEBUG ADMIN] {member.display_name} successfully timed out.")
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to timeout this member. Ensure the bot's role is higher.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !timeout: Bot Forbidden.")
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while timing out: {e}", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !timeout: ERROR: {e}.", file=sys.stderr)

    @commands.command(name="removetimeout", aliases=["unmute"])
    @commands.has_permissions(moderate_members=True)
    async def remove_timeout(self, ctx, member: discord.Member):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !removetimeout called by {ctx.author.display_name} for {member.display_name}.")
        if member.id == ctx.guild.owner.id: await ctx.send(embed=self._create_embed(description="❌ You cannot remove timeout for the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id: await ctx.send(embed=self._create_embed(description="❌ You cannot remove timeout for this bot itself.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role: # Tambahan pemeriksaan peran bot
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat menghapus timeout anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return

        if not member.is_timed_out():
            await ctx.send(embed=self._create_embed(description=f"❌ {member.display_name} is not currently timed out.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !removetimeout: {member.display_name} not timed out.")
            return

        try:
            await member.timeout(None, reason=f"Timeout removed by {ctx.author}")
            await ctx.send(embed=self._create_embed(description=f"✅ Timeout for **{member.display_name}** has been removed.", color=self.color_success))
            await self.log_action(ctx.guild, "😊 Timeout Removed", {"Member": f"{member} ({member.id})", "Moderator": ctx.author.mention}, self.color_success)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Timeout for {member.display_name} successfully removed.")
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to remove timeout for this member. Ensure the bot's role is higher.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !removetimeout: Bot Forbidden.")
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while removing timeout: {e}", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !removetimeout: ERROR: {e}.", file=sys.stderr)
        
    @commands.command(name="clear", aliases=["purge"])
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !clear called by {ctx.author.display_name} for {amount} messages.")
        if amount <= 0: await ctx.send(embed=self._create_embed(description="❌ Amount must be greater than 0.", color=self.color_error)); return
        if amount > 100: await ctx.send(embed=self._create_embed(description="❌ You can only delete a maximum of 100 messages at once.", color=self.color_error)); return

        try:
            deleted = await ctx.channel.purge(limit=amount + 1) # +1 to also delete the command message
            embed = self._create_embed(description=f"🗑️ Successfully deleted **{len(deleted) - 1}** messages.", color=self.color_success)
            await ctx.send(embed=embed, delete_after=5)
            await self.log_action(ctx.guild, "🗑️ Messages Deleted", {"Channel": ctx.channel.mention, "Amount": f"{len(deleted) - 1} messages", "Moderator": ctx.author.mention}, self.color_info)
            print(f"[{datetime.now()}] [DEBUG ADMIN] {len(deleted) - 1} messages successfully deleted.")
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have `Manage Messages` permission to delete messages.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !clear: Bot Forbidden.")
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while deleting messages: {e}", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !clear: ERROR: {e}.", file=sys.stderr)
        
    @commands.command(name="slowmode")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !slowmode called by {ctx.author.display_name} for {seconds} seconds.")
        if seconds < 0: await ctx.send(embed=self._create_embed(description="❌ Slowmode duration cannot be negative.", color=self.color_error)); return
        if seconds > 21600: await ctx.send(embed=self._create_embed(description="❌ Slowmode duration cannot exceed 6 hours (21600 seconds).", color=self.color_error)); return

        try:
            await ctx.channel.edit(slowmode_delay=seconds)
            status = f"set to `{seconds}` seconds" if seconds > 0 else "disabled"
            await ctx.send(embed=self._create_embed(description=f"✅ Slowmode in this channel has been {status}.", color=self.color_success))
            await self.log_action(ctx.guild, "⏳ Slowmode Changed", {"Channel": ctx.channel.mention, "Duration": f"{seconds} seconds", "Moderator": ctx.author.mention}, self.color_info)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Slowmode in channel {ctx.channel.name} set to {seconds} seconds.")
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have `Manage Channels` permission to set slowmode.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !slowmode: Bot Forbidden.")
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while setting slowmode: {e}", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !slowmode: ERROR: {e}.", file=sys.stderr)

    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: Optional[discord.TextChannel] = None):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !lock called by {ctx.author.display_name} for channel: {channel.name if channel else ctx.channel.name}.")
        target_channel = channel or ctx.channel
        current_perms = target_channel.permissions_for(ctx.guild.default_role)
        if not current_perms.send_messages is False: # Check if send_messages is NOT explicitly False
            try:
                await target_channel.set_permissions(ctx.guild.default_role, send_messages=False)
                await ctx.send(embed=self._create_embed(description=f"🔒 Channel {target_channel.mention} has been locked.", color=self.color_success))
                await self.log_action(ctx.guild, "🔒 Channel Locked", {"Channel": target_channel.mention, "Moderator": ctx.author.mention}, self.color_warning)
                print(f"[{datetime.now()}] [DEBUG ADMIN] Channel {target_channel.name} successfully locked.")
            except discord.Forbidden:
                await ctx.send(embed=self._create_embed(description="❌ Bot does not have `Manage Channels` permission to lock the channel.", color=self.color_error))
                print(f"[{datetime.now()}] [DEBUG ADMIN] !lock: Bot Forbidden.")
            except Exception as e:
                await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while locking the channel: {e}", color=self.color_error))
                print(f"[{datetime.now()}] [DEBUG ADMIN] !lock: ERROR: {e}.", file=sys.stderr)
        else:
            await ctx.send(embed=self._create_embed(description=f"❌ Channel {target_channel.mention} is already locked.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !lock: Channel {target_channel.name} already locked.")

    @commands.command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: Optional[discord.TextChannel] = None):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !unlock called by {ctx.author.display_name} for channel: {channel.name if channel else ctx.channel.name}.")
        target_channel = channel or ctx.channel
        current_perms = target_channel.permissions_for(ctx.guild.default_role)
        if not current_perms.send_messages is True: # Check if send_messages is NOT explicitly True (i.e., it's False or None)
            try:
                await target_channel.set_permissions(ctx.guild.default_role, send_messages=None) # Reset permissions to neutral
                await ctx.send(embed=self._create_embed(description=f"🔓 Channel {target_channel.mention} has been unlocked.", color=self.color_success))
                await self.log_action(ctx.guild, "🔓 Channel Unlocked", {"Channel": target_channel.mention, "Moderator": ctx.author.mention}, self.color_success)
                print(f"[{datetime.now()}] [DEBUG ADMIN] Channel {target_channel.name} successfully unlocked.")
            except discord.Forbidden:
                await ctx.send(embed=self._create_embed(description="❌ Bot does not have `Manage Channels` permission to unlock the channel.", color=self.color_error))
                print(f"[{datetime.now()}] [DEBUG ADMIN] !unlock: Bot Forbidden.")
            except Exception as e:
                await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while unlocking the channel: {e}", color=self.color_error))
                print(f"[{datetime.now()}] [DEBUG ADMIN] !unlock: ERROR: {e}.", file=sys.stderr)
        else:
            await ctx.send(embed=self._create_embed(description=f"❌ Channel {target_channel.mention} is already unlocked.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !unlock: Channel {target_channel.name} already unlocked.")

    @commands.command(name="addrole")
    @commands.has_permissions(manage_roles=True)
    async def add_role(self, ctx, member: discord.Member, role: discord.Role):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !addrole called by {ctx.author.display_name} for {member.display_name} role {role.name}.")
        if ctx.author.top_role <= role:
            await ctx.send(embed=self._create_embed(description="❌ You cannot assign a role that is higher than or equal to your own role.", color=self.color_error))
            return
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot modify roles for a member with a higher or equal position.", color=self.color_error))
            return
        if member.top_role >= ctx.guild.me.top_role: # Tambahan pemeriksaan peran bot
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat menambahkan peran anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return
        if role in member.roles:
            await ctx.send(embed=self._create_embed(description=f"❌ {member.display_name} already has the role {role.mention}.", color=self.color_error))
            return
            
        try:
            await member.add_roles(role, reason=f"Assigned by {ctx.author}")
            await ctx.send(embed=self._create_embed(description=f"✅ Role {role.mention} has been given to {member.mention}.", color=self.color_success))
            await self.log_action(ctx.guild, "➕ Role Assigned", {"Member": member.mention, "Role": role.mention, "Moderator": ctx.author.mention}, self.color_info)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Role {role.name} successfully assigned to {member.display_name}.")
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to assign this role. Ensure the bot's role is higher than the role to be assigned.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !addrole: Bot Forbidden.")
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while assigning the role: {e}", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !addrole: ERROR: {e}.", file=sys.stderr)

    @commands.command(name="removerole")
    @commands.has_permissions(manage_roles=True)
    async def remove_role(self, ctx, member: discord.Member, role: discord.Role):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !removerole called by {ctx.author.display_name} for {member.display_name} role {role.name}.")
        if ctx.author.top_role <= role:
            await ctx.send(embed=self._create_embed(description="❌ You cannot remove a role that is higher than or equal to your own role.", color=self.color_error))
            return
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot modify roles for a member with a higher or equal position.", color=self.color_error))
            return
        if member.top_role >= ctx.guild.me.top_role: # Tambahan pemeriksaan peran bot
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat menghapus peran anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return
        if role not in member.roles:
            await ctx.send(embed=self._create_embed(description=f"❌ {member.display_name} does not have the role {role.mention}.", color=self.color_error))
            return
            
        try:
            await member.remove_roles(role, reason=f"Removed by {ctx.author}")
            await ctx.send(embed=self._create_embed(description=f"✅ Role {role.mention} has been removed from {member.mention}.", color=self.color_success))
            await self.log_action(ctx.guild, "➖ Role Removed", {"Member": member.mention, "Role": role.mention, "Moderator": ctx.author.mention}, self.color_info)
            print(f"[{datetime.now()}] [DEBUG ADMIN] Role {role.name} successfully removed from {member.display_name}.")
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to remove this role. Ensure the bot's role is higher than the role to be removed.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !removerole: Bot Forbidden.")
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while removing the role: {e}", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !removerole: ERROR: {e}.", file=sys.stderr)

    @commands.command(name="nick")
    @commands.has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, new_nickname: Optional[str] = None):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !nick called by {ctx.author.display_name} for {member.display_name} with new nickname: '{new_nickname}'.")
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot change the nickname of a member with a higher or equal role.", color=self.color_error))
            return
        if member.id == ctx.guild.owner.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot change the nickname of the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot change the nickname of this bot itself.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role: # Tambahan pemeriksaan peran bot
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat mengubah nickname anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return

        old_nickname = member.display_name
        try:
            await member.edit(nick=new_nickname, reason=f"Changed by {ctx.author}")
            if new_nickname:
                await ctx.send(embed=self._create_embed(description=f"✅ Nickname **{old_nickname}** has been changed to **{new_nickname}**.", color=self.color_success))
                await self.log_action(ctx.guild, "👤 Nickname Changed", {"Member": member.mention, "From": old_nickname, "To": new_nickname, "Moderator": ctx.author.mention}, self.color_info)
                print(f"[{datetime.now()}] [DEBUG ADMIN] Nickname {member.display_name} changed to {new_nickname}.")
            else:
                await ctx.send(embed=self._create_embed(description=f"✅ Nickname for **{old_nickname}** has been reset.", color=self.color_success))
                await self.log_action(ctx.guild, "👤 Nickname Reset", {"Member": member.mention, "Moderator": ctx.author.mention}, self.color_info)
                print(f"[{datetime.now()}] [DEBUG ADMIN] Nickname {member.display_name} reset.")
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to change this nickname. Ensure the bot's role is higher than this member.", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !nick: Bot Forbidden.")
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while changing nickname: {e}", color=self.color_error))
            print(f"[{datetime.now()}] [DEBUG ADMIN] !nick: ERROR: {e}.", file=sys.stderr)

    # =======================================================================================
    # CHANNEL RULES COMMANDS
    # =======================================================================================
    @commands.command(name="channelrules", aliases=["cr"])
    @commands.has_permissions(manage_channels=True)
    async def channel_rules(self, ctx, channel: Optional[discord.TextChannel] = None):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !channelrules called by {ctx.author.display_name} for channel: {channel.name if channel else ctx.channel.name}.")
        target_channel = channel or ctx.channel
        class ChannelRuleView(discord.ui.View):
            def __init__(self, cog_instance, author, target_channel):
                super().__init__(timeout=300)
                self.cog, self.author, self.target_channel = cog_instance, author, target_channel
                self.guild_id, self.channel_id = target_channel.guild.id, target_channel.id
                self.message = None # This will be set after the initial message is sent
                self.update_buttons()
                print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView initialized for {target_channel.name}.")

            def update_buttons(self):
                print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView: update_buttons called.")
                rules = self.cog.get_channel_rules(self.guild_id, self.channel_id)
                def set_button_state(button, label_text, is_active):
                    button.label = f"{label_text}: {'Aktif' if is_active else 'Nonaktif'}"
                    button.style = discord.ButtonStyle.green if is_active else discord.ButtonStyle.red
                
                self.clear_items()
                
                self.toggle_bots = discord.ui.Button(emoji="🛡️", row=0)
                self.toggle_bots.callback = lambda i: self.toggle_rule(i, "disallow_bots")
                set_button_state(self.toggle_bots, "Dilarang Bot", rules.get("disallow_bots", False))
                self.add_item(self.toggle_bots)

                self.toggle_media = discord.ui.Button(emoji="🖼️", row=0)
                self.toggle_media.callback = lambda i: self.toggle_rule(i, "disallow_media")
                set_button_state(self.toggle_media, "Dilarang Media", rules.get("disallow_media", False))
                self.add_item(self.toggle_media)

                self.toggle_prefix = discord.ui.Button(emoji="❗", row=0)
                self.toggle_prefix.callback = lambda i: self.toggle_rule(i, "disallow_prefix")
                set_button_state(self.toggle_prefix, "Dilarang Prefix", rules.get("disallow_prefix", False))
                self.add_item(self.toggle_prefix)

                self.toggle_url = discord.ui.Button(emoji="🔗", row=1)
                self.toggle_url.callback = lambda i: self.toggle_rule(i, "disallow_url")
                set_button_state(self.toggle_url, "Dilarang URL", rules.get("disallow_url", False))
                self.add_item(self.toggle_url)
                
                self.toggle_auto_delete = discord.ui.Button(emoji="⏳", row=1)
                self.toggle_auto_delete.callback = lambda i: self.set_auto_delete(i)
                delay = rules.get("auto_delete_seconds", 0)
                self.toggle_auto_delete.label = f"Hapus Otomatis: {delay}s" if delay > 0 else "Hapus Otomatis: Nonaktif"
                self.toggle_auto_delete.style = discord.ButtonStyle.green if delay > 0 else discord.ButtonStyle.red
                self.add_item(self.toggle_auto_delete)
                print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView: Buttons updated.")

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView: interaction_check triggered by {interaction.user.display_name}.")
                if interaction.user != self.author:
                    await interaction.response.send_message("Hanya pengguna yang memulai perintah yang dapat berinteraksi.", ephemeral=True)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView: User is not original caller.")
                    return False
                if not interaction.user.guild_permissions.manage_channels:
                    await interaction.response.send_message("Anda tidak memiliki izin `Manage Channels` untuk mengubah aturan ini.", ephemeral=True)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView: User lacks permissions.")
                    return False
                print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView: Interaction check passed.")
                return True

            async def toggle_rule(self, interaction: discord.Interaction, rule_name: str):
                print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView: toggle_rule '{rule_name}' clicked by {interaction.user.display_name}.")
                rules = self.cog.get_channel_rules(self.guild_id, self.channel_id)
                rules[rule_name] = not rules.get(rule_name, False)
                self.cog.save_settings()
                self.update_buttons()
                await interaction.response.edit_message(view=self)
                await self.cog.log_action(
                    self.target_channel.guild,
                    "🔧 Channel Rule Changed",
                    {"Channel": self.target_channel.mention, f"Rule '{rule_name}'": "Enabled" if rules[rule_name] else "Disabled", "Moderator": interaction.user.mention},
                    self.cog.color_info
                )
                print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView: Rule '{rule_name}' toggled to {rules[rule_name]}.")

            async def set_auto_delete(self, interaction: discord.Interaction):
                print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView: set_auto_delete clicked by {interaction.user.display_name}.")
                class AutoDeleteModal(discord.ui.Modal, title="Set Auto-Delete"):
                    def __init__(self, current_delay, parent_view_instance):
                        super().__init__()
                        self.cog = parent_view_instance.cog
                        self.guild_id = parent_view_instance.guild_id
                        self.channel_id = parent_view_instance.channel_id
                        self.parent_view = parent_view_instance

                        self.delay_input = discord.ui.TextInput(
                            label="Duration (seconds, 0 to disable)", # FIXED: <= 45 chars
                            placeholder="Example: 30 (max 3600)",
                            default=str(current_delay),
                            max_length=4
                        )
                        self.add_item(self.delay_input)
                        print(f"[{datetime.now()}] [DEBUG ADMIN] AutoDeleteModal initialized (current_delay: {current_delay}).")

                    async def on_submit(self, modal_interaction: discord.Interaction):
                        print(f"[{datetime.now()}] [DEBUG ADMIN] AutoDeleteModal: on_submit called by {modal_interaction.user.display_name}.")
                        await modal_interaction.response.defer(ephemeral=True)
                        try:
                            delay = int(self.delay_input.value)
                            if not (0 <= delay <= 3600):
                                print(f"[{datetime.now()}] [DEBUG ADMIN] AutoDeleteModal: Invalid duration ({delay}).")
                                await modal_interaction.followup.send(embed=self.cog._create_embed(description="❌ Duration must be between 0 and 3600 seconds (1 hour).", color=self.cog.color_error), ephemeral=True)
                                return
                            
                            rules = self.cog.get_channel_rules(self.guild_id, self.channel_id)
                            rules["auto_delete_seconds"] = delay
                            self.cog.save_settings()
                            print(f"[{datetime.now()}] [DEBUG ADMIN] Auto delete duration set to {delay}s.")
                            
                            self.parent_view.update_buttons()
                            # Edit the original message of the modal trigger (the view's message)
                            await modal_interaction.message.edit(view=self.parent_view)
                            
                            await self.cog.log_action(
                                self.parent_view.target_channel.guild,
                                "⏳ Auto-Delete Changed",
                                {"Channel": self.parent_view.target_channel.mention, "Duration": f"{delay} seconds" if delay > 0 else "Disabled", "Moderator": modal_interaction.user.mention},
                                self.cog.color_info
                            )
                        except ValueError:
                            print(f"[{datetime.now()}] [DEBUG ADMIN] AutoDeleteModal: Duration input is not a number.")
                            await modal_interaction.followup.send(embed=self.cog._create_embed(description="❌ Duration must be a number.", color=self.cog.color_error), ephemeral=True)
                        except Exception as e:
                            await modal_interaction.followup.send(embed=self.cog._create_embed(description=f"❌ An error occurred: {e}", color=self.cog.color_error), ephemeral=True)
                            print(f"[{datetime.now()}] [ERROR ADMIN] AutoDeleteModal: ERROR in on_submit: {e}.", file=sys.stderr)
                
                rules = self.cog.get_channel_rules(self.guild_id, self.channel_id)
                current_delay = rules.get("auto_delete_seconds", 0)
                await interaction.response.send_modal(AutoDeleteModal(current_delay, self))
                print(f"[{datetime.now()}] [DEBUG ADMIN] ChannelRuleView: AutoDeleteModal sent.")

        embed = self._create_embed(title=f"🔧 Rules for Channel: #{target_channel.name}", description="Press buttons to enable (green) or disable (red) rules for this channel. Press the auto-delete button to set its duration (default 30s).", color=self.color_info)
        view_instance = ChannelRuleView(self, ctx.author, target_channel)
        view_instance.message = await ctx.send(embed=embed, view=view_instance) # Set message object for the view
        print(f"[{datetime.now()}] [DEBUG ADMIN] !channelrules: ChannelRuleView message sent.")
        
    # =======================================================================================
    # SETUP COMMANDS
    # =======================================================================================

    @commands.command(name="setwelcomechannel")
    @commands.has_permissions(manage_guild=True)
    async def set_welcome_channel(self, ctx, channel: discord.TextChannel):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !setwelcomechannel called by {ctx.author.display_name} for channel: {channel.name}.")
        """Sets the channel for welcome messages."""
        guild_settings = self.get_guild_settings(ctx.guild.id)
        guild_settings["welcome_channel_id"] = channel.id
        self.save_settings()
        embed = self._create_embed(
            description=f"✅ Welcome channel successfully set to {channel.mention}.",
            color=self.color_success
        )
        await ctx.send(embed=embed)
        print(f"[{datetime.now()}] [DEBUG ADMIN] Welcome channel set to {channel.name}.")

    @commands.command(name="setboostchannel") # COMMAND BARU
    @commands.has_permissions(manage_guild=True)
    async def set_boost_channel(self, ctx, channel: discord.TextChannel):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !setboostchannel called by {ctx.author.display_name} for channel: {channel.name}.")
        """Sets the channel for server booster messages."""
        guild_settings = self.get_guild_settings(ctx.guild.id)
        guild_settings["boost_channel_id"] = channel.id
        self.save_settings()
        embed = self._create_embed(
            description=f"✅ Server Booster channel berhasil diatur ke {channel.mention}.",
            color=self.color_success
        )
        await ctx.send(embed=embed)
        print(f"[{datetime.now()}] [DEBUG ADMIN] Server Booster channel set to {channel.name}.")

    @commands.command(name="setreactionrole")
    @commands.has_permissions(manage_roles=True)
    async def set_reaction_role(self, ctx, message: discord.Message, emoji: str, role: discord.Role):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !setreactionrole called by {ctx.author.display_name} for message {message.id}, emoji {emoji}, role {role.name}.")
        if ctx.author.top_role <= role:
            print(f"[{datetime.now()}] [DEBUG ADMIN] !setreactionrole: Caller lacks permission (role too low).")
            return await ctx.send(embed=self._create_embed(description="❌ You cannot set a reaction role for a role higher than or equal to your own.", color=self.color_error))
        
        guild_settings = self.get_guild_settings(ctx.guild.id)
        message_id_str = str(message.id)
        if message_id_str not in guild_settings["reaction_roles"]: guild_settings["reaction_roles"][message_id_str] = {}
        guild_settings["reaction_roles"][message_id_str][emoji] = role.id
        self.save_settings()
        print(f"[{datetime.now()}] [DEBUG ADMIN] Reaction role setting saved.")
        try:
            await message.add_reaction(emoji)
            await ctx.send(embed=self._create_embed(description=f"✅ Role **{role.mention}** will be given for {emoji} reaction on [that message]({message.jump_url}).", color=self.color_success))
            print(f"[{datetime.now()}] [DEBUG ADMIN] Reaction {emoji} added to message {message.id}.")
        except discord.Forbidden:
            print(f"[{datetime.now()}] [DEBUG ADMIN] !setreactionrole: Bot Forbidden to add reaction or set role.", file=sys.stderr)
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have permission to add reactions or set roles. Ensure all permissions are complete.", color=self.color_error))
        except Exception as e:
            print(f"[{datetime.now()}] [DEBUG ADMIN] !setreactionrole: ERROR: {e}.", file=sys.stderr)
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred: {e}", color=self.color_error))

    @commands.command(name="setup")
    @commands.has_permissions(manage_guild=True)
    async def setup(self, ctx):
        print(f"[{datetime.now()}] [DEBUG ADMIN] Command !setup called by {ctx.author.display_name}.")
        class SetupView(discord.ui.View):
            def __init__(self, cog_instance, author, ctx_instance): # Changed to ctx_instance to avoid conflict with ctx variable in command
                super().__init__(timeout=300)
                self.cog = cog_instance
                self.guild_id = ctx_instance.guild.id
                self.author = author
                self.ctx = ctx_instance # Store ctx_instance
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView initialized.")
            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: interaction_check triggered by {interaction.user.display_name}.")
                if interaction.user != self.author:
                    await interaction.response.send_message("Hanya pengguna yang memulai setup yang dapat berinteraksi.", ephemeral=True)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: User is not original caller.")
                    return False
                if not interaction.user.guild_permissions.manage_guild:
                    await interaction.response.send_message("Anda tidak memiliki izin `Manage Server` untuk menggunakan setup ini.", ephemeral=True)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: User lacks permissions.")
                    return False
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Interaction check passed.")
                return True

            async def handle_response(self, interaction, prompt, callback):
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: handle_response called.")
                await interaction.response.send_message(embed=self.cog._create_embed(description=prompt, color=self.cog.color_info), ephemeral=True)
                try:
                    msg = await self.cog.bot.wait_for('message', check=lambda m: m.author == self.author and m.channel == interaction.channel, timeout=120)
                    await callback(msg, interaction)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Response for handle_response received.")
                except asyncio.TimeoutError:
                    await interaction.followup.send(embed=self.cog._create_embed(description="❌ Waktu habis.", color=self.cog.color_error), ephemeral=True)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: handle_response timed out.")
                except Exception as e:
                    await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan: {e}", color=self.cog.color_error), ephemeral=True)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: handle_response ERROR: {e}.", file=sys.stderr)

            @discord.ui.button(label="Auto Role", style=discord.ButtonStyle.primary, emoji="👤", row=0)
            async def set_auto_role(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Auto Role button clicked.")
                async def callback(msg, inter):
                    role = msg.role_mentions[0] if msg.role_mentions else self.ctx.guild.get_role(int(msg.content)) if msg.content.isdigit() else None
                    if role:
                        self.cog.get_guild_settings(self.guild_id)['auto_role_id'] = role.id; self.cog.save_settings()
                        await inter.followup.send(embed=self.cog._create_embed(description=f"✅ Auto Role diatur ke **{role.mention}**.", color=self.cog.color_success), ephemeral=True)
                        print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Auto Role set to {role.name}.")
                    else:
                        await inter.followup.send(embed=self.cog._create_embed(description="❌ Role tidak ditemukan.", color=self.cog.color_error), ephemeral=True)
                        print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Role not found for Auto Role.")
                await self.handle_response(interaction, "Sebutkan (mention) atau masukkan ID role untuk pengguna baru:", callback)

            @discord.ui.button(label="Welcome Msg", style=discord.ButtonStyle.primary, emoji="💬", row=0)
            async def set_welcome_message(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Welcome Msg button clicked.")
                
                # Mengambil pengaturan saat ini untuk mengisi modal
                current_settings = self.cog.get_guild_settings(self.guild_id)
                modal = WelcomeMessageModal(self.cog, self.guild_id, current_settings)
                
                await interaction.response.send_modal(modal)
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: WelcomeMessageModal sent.")

            @discord.ui.button(label="Log Channel", style=discord.ButtonStyle.primary, emoji="📝", row=0)
            async def set_log_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Log Channel button clicked.")
                async def callback(msg, inter):
                    channel = msg.channel_mentions[0] if msg.channel_mentions else self.ctx.guild.get_channel(int(msg.content)) if msg.content.isdigit() else None
                    if channel and isinstance(channel, discord.TextChannel):
                        self.cog.get_guild_settings(self.guild_id)['log_channel_id'] = channel.id; self.cog.save_settings()
                        await inter.followup.send(embed=self.cog._create_embed(description=f"✅ Log Channel diatur ke **{channel.mention}**.", color=self.cog.color_success), ephemeral=True)
                        print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Log Channel set to {channel.name}.")
                    else:
                        await inter.followup.send(embed=self.cog._create_embed(description="❌ Channel tidak ditemukan atau bukan channel teks.", color=self.cog.color_error), ephemeral=True)
                        print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Channel not found for Log Channel.")
                await self.handle_response(interaction, "Sebutkan (mention) atau masukkan ID channel untuk log aktivitas bot:", callback)
            
            # --- TOMBOL BARU UNTUK SERVER BOOSTER ---
            @discord.ui.button(label="Server Booster", style=discord.ButtonStyle.primary, emoji="✨", row=1) # Row 1, agar tetap rapi
            async def set_server_booster_message(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Server Booster button clicked.")
                current_settings = self.cog.get_guild_settings(self.guild_id)
                modal = ServerBoostModal(self.cog, self.guild_id, current_settings)
                await interaction.response.send_modal(modal)
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: ServerBoostModal sent.")
            # --- AKHIR TOMBOL BARU ---

            @discord.ui.button(label="Kelola Filter", style=discord.ButtonStyle.secondary, emoji="🛡️", row=1)
            async def manage_filters(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Manage Filters button clicked.")
                await interaction.response.send_message(view=FilterManageView(self.cog, self.author), ephemeral=True)

            @discord.ui.button(label="Lihat Konfigurasi", style=discord.ButtonStyle.secondary, emoji="📋", row=2) # Pindah ke row 2 agar rapi
            async def view_config(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: View Config button clicked.")
                settings = self.cog.get_guild_settings(self.guild_id); filters = self.cog.get_guild_filters(self.guild_id)
                
                auto_role = self.ctx.guild.get_role(settings.get('auto_role_id')) if settings.get('auto_role_id') else "Tidak diatur"
                welcome_ch = self.ctx.guild.get_channel(settings.get('welcome_channel_id')) if settings.get('welcome_channel_id') else "Tidak diatur"
                log_ch = self.ctx.guild.get_channel(settings.get('log_channel_id')) if settings.get('log_channel_id') else "Tidak diatur"
                
                boost_ch = self.ctx.guild.get_channel(settings.get('boost_channel_id')) if settings.get('boost_channel_id') else "Tidak diatur"
                boost_image = f"[URL]({settings.get('boost_image_url')})" if settings.get('boost_image_url') else "Tidak diatur"

                embed = self.cog._create_embed(title=f"Konfigurasi untuk {self.ctx.guild.name}", color=self.cog.color_info)
                embed.add_field(
                    name="Pengaturan Dasar", 
                    value=(
                        f"**Auto Role**: {auto_role.mention if isinstance(auto_role, discord.Role) else auto_role}\n"
                        f"**Welcome Channel**: {welcome_ch.mention if isinstance(welcome_ch, discord.TextChannel) else welcome_ch}\n"
                        f"**Log Channel**: {log_ch.mention if isinstance(log_ch, discord.TextChannel) else log_ch}"
                    ), 
                    inline=False
                )
                embed.add_field(
                    name="Pesan Selamat Datang", 
                    value=(
                        f"**Judul Embed**: `{settings.get('welcome_embed_title', 'Tidak diatur')}`\n"
                        f"**Pengirim Kustom**: `{settings.get('welcome_sender_name', 'Tidak diatur')}`\n"
                        f"**Isi Pesan**: ```{settings.get('welcome_message')}```"
                    ), 
                    inline=False
                )
                # --- TAMBAHKAN KONFIGURASI BOOSTER DI SINI ---
                embed.add_field(
                    name="Pesan Server Booster",
                    value=(
                        f"**Channel Booster**: {boost_ch.mention if isinstance(boost_ch, discord.TextChannel) else boost_ch}\n"
                        f"**Judul Embed**: `{settings.get('boost_embed_title', 'Tidak diatur')}`\n"
                        f"**Pengirim Kustom**: `{settings.get('boost_sender_name', 'Tidak diatur')}`\n"
                        f"**URL Gambar (Banner)**: {boost_image}\n" # Updated label here too
                        f"**Isi Pesan**: ```{settings.get('boost_message')}```"
                    ),
                    inline=False
                )
                # --- AKHIR KONFIGURASI BOOSTER ---
                embed.add_field(name="Filter Kata Kasar", value=f"Total: {len(filters.get('bad_words',[]))} kata", inline=True)
                embed.add_field(name="Filter Link", value=f"Total: {len(filters.get('link_patterns',[]))} pola", inline=True)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                print(f"[{datetime.now()}] [DEBUG ADMIN] SetupView: Configuration viewed.")

        class AddFilterModal(discord.ui.Modal, title="Tambah Filter"):
            def __init__(self, cog_instance, filter_type):
                super().__init__(); self.cog = cog_instance; self.filter_type = filter_type
                self.item_to_add = discord.ui.TextInput(label=f"Masukkan {('kata' if filter_type == 'bad_words' else 'pola regex')} untuk ditambahkan", style=discord.TextStyle.paragraph)
                self.add_item(self.item_to_add)
                print(f"[{datetime.now()}] [DEBUG ADMIN] AddFilterModal initialized (type: {filter_type}).")
            async def on_submit(self, interaction: discord.Interaction):
                print(f"[{datetime.now()}] [DEBUG ADMIN] AddFilterModal: on_submit called by {interaction.user.display_name}.")
                filters = self.cog.get_guild_filters(interaction.guild_id); item = self.item_to_add.value.lower().strip()
                if item in filters[self.filter_type]:
                    await interaction.response.send_message(embed=self.cog._create_embed(description=f"❌ `{item}` sudah ada di filter.", color=self.cog.color_error), ephemeral=True)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] AddFilterModal: Item already exists.")
                else:
                    filters[self.filter_type].append(item); self.cog.save_filters()
                    await interaction.response.send_message(embed=self.cog._create_embed(description=f"✅ `{item}` berhasil ditambahkan ke filter.", color=self.cog.color_success), ephemeral=True)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] AddFilterModal: Item '{item}' added.")

        class RemoveFilterModal(discord.ui.Modal, title="Hapus Filter"):
            def __init__(self, cog_instance, filter_type):
                super().__init__(); self.cog = cog_instance; self.filter_type = filter_type
                self.item_to_remove = discord.ui.TextInput(label=f"Masukkan {('kata' if filter_type == 'bad_words' else 'pola')} yang akan dihapus")
                self.add_item(self.item_to_remove)
                print(f"[{datetime.now()}] [DEBUG ADMIN] RemoveFilterModal initialized (type: {filter_type}).")
            async def on_submit(self, interaction: discord.Interaction):
                print(f"[{datetime.now()}] [DEBUG ADMIN] RemoveFilterModal: on_submit called by {interaction.user.display_name}.")
                filters = self.cog.get_guild_filters(interaction.guild_id); item = self.item_to_remove.value.lower().strip()
                if item in filters[self.filter_type]:
                    filters[self.filter_type].remove(item); self.cog.save_filters()
                    await interaction.response.send_message(embed=self.cog._create_embed(description=f"✅ `{item}` berhasil dihapus dari filter.", color=self.cog.color_success), ephemeral=True)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] RemoveFilterModal: Item '{item}' removed.")
                else:
                    await interaction.response.send_message(embed=self.cog._create_embed(description=f"❌ `{item}` tidak ditemukan di filter.", color=self.cog.color_error), ephemeral=True)
                    print(f"[{datetime.now()}] [DEBUG ADMIN] RemoveFilterModal: Item not found.")

        class FilterManageView(discord.ui.View):
            def __init__(self, cog_instance, author):
                super().__init__(timeout=180); self.cog = cog_instance; self.author = author
                print(f"[{datetime.now()}] [DEBUG ADMIN] FilterManageView initialized.")
            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                print(f"[{datetime.now()}] [DEBUG ADMIN] FilterManageView: interaction_check triggered by {interaction.user.display_name}.")
                return interaction.user == self.author
            @discord.ui.button(label="Tambah Kata Kasar", style=discord.ButtonStyle.primary, emoji="🤬")
            async def add_bad_word(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] FilterManageView: Add Bad Word button clicked.")
                await interaction.response.send_modal(AddFilterModal(self.cog, "bad_words"))
            @discord.ui.button(label="Hapus Kata Kasar", style=discord.ButtonStyle.danger, emoji="🗑️")
            async def remove_bad_word(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] FilterManageView: Remove Bad Word button clicked.")
                await interaction.response.send_modal(RemoveFilterModal(self.cog, "bad_words"))
            @discord.ui.button(label="Tambah Pola Link", style=discord.ButtonStyle.primary, emoji="🔗")
            async def add_link_pattern(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] FilterManageView: Add Link Pattern button clicked.")
                await interaction.response.send_modal(AddFilterModal(self.cog, "link_patterns"))
            @discord.ui.button(label="Hapus Pola Link", style=discord.ButtonStyle.danger, emoji="🔗")
            async def remove_link_pattern(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] FilterManageView: Remove Link Pattern button clicked.")
                await interaction.response.send_modal(RemoveFilterModal(self.cog, "link_patterns"))
            @discord.ui.button(label="Lihat Semua Filter", style=discord.ButtonStyle.secondary, emoji="📋", row=2)
            async def view_filters(self, interaction: discord.Interaction, button: discord.ui.Button):
                print(f"[{datetime.now()}] [DEBUG ADMIN] FilterManageView: View All Filters button clicked.")
                filters = self.cog.get_guild_filters(interaction.guild_id); bad_words = ", ".join(f"`{w}`" for w in filters['bad_words']) or "Kosong"; link_patterns = ", ".join(f"`{p}`" for p in filters['link_patterns']) or "Kosong"
                embed = self.cog._create_embed(title="Daftar Filter Aktif", color=self.cog.color_info)
                embed.add_field(name="🚫 Kata Kasar", value=bad_words[:1024], inline=False); embed.add_field(name="🔗 Pola Link", value=link_patterns[:1024], inline=False)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                print(f"[{datetime.now()}] [DEBUG ADMIN] FilterManageView: Filters viewed.")

        embed = self._create_embed(title="⚙️ Panel Kontrol Server", description="Gunakan tombol di bawah ini untuk mengatur bot. Anda memiliki 5 menit sebelum panel ini nonaktif.", color=self.color_info, author_name=ctx.guild.name, author_icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        view_instance = SetupView(self, ctx.author, ctx)
        await ctx.send(embed=embed, view=view_instance)
        print(f"[{datetime.now()}] [DEBUG ADMIN] !setup: SetupView message sent.")

# =======================================================================================
# ANNOUNCE COMMAND (MODIFIED FOR WEBHOOKS)
# =======================================================================================
    @commands.command(name="announce", aliases=["pengumuman", "broadcast"])
    @commands.has_permissions(manage_guild=True)
    async def announce(self, ctx, channel_identifier: str):
        """
        Creates a custom announcement via UI form to a specific channel.
        Target channel is provided via command (mention or ID).
        Other details (title, custom profile, image) are filled via a modal.
        Description is fetched from a hardcoded GitHub Raw URL.
        Format: !announce <#channel_mention_OR_channel_ID>
        Example: !announce #general
        Example: !announce 123456789012345678
        """
        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Command !announce called by {ctx.author.display_name} for channel: '{channel_identifier}'.")
        # Hardcode the GitHub Raw URL for the announcement description
        # IMPORTANT: Ensure this URL points to a public raw text file.
        GITHUB_RAW_DESCRIPTION_URL = "https://raw.githubusercontent.com/Abogoboga04/OpenAI/main/announcement.txt" # Adjust branch if needed
        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] !announce: Using GitHub Raw URL: {GITHUB_RAW_DESCRIPTION_URL}.")

        # --- Parsing Channel from Command Argument ---
        target_channel = None
        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Analyzing channel_identifier: '{channel_identifier}'")

        if channel_identifier.startswith('<#') and channel_identifier.endswith('>'):
            try:
                channel_id = int(channel_identifier[2:-1])
                target_channel = ctx.guild.get_channel(channel_id)
                if not target_channel:
                    target_channel = self.bot.get_channel(channel_id)
                print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Channel identified via mention as ID: {channel_id}, Result: {target_channel.name if target_channel else 'None'}.")
            except ValueError:
                print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Failed to parse channel mention. Trying raw ID.")
                pass
        
        if not target_channel and channel_identifier.isdigit():
            try:
                channel_id = int(channel_identifier)
                target_channel = ctx.guild.get_channel(channel_id)
                if not target_channel:
                    target_channel = self.bot.get_channel(channel_id)
                print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Channel identified via ID: {channel_id}, Result: {target_channel.name if target_channel else 'None'}.")
            except ValueError:
                print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Failed to parse raw channel ID.")
                pass

        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Target channel '{channel_identifier}' not found or is not a valid text channel.")
            await ctx.send(embed=self._create_embed(
                description=f"❌ Channel '{channel_identifier}' tidak ditemukan atau bukan channel teks yang valid. Mohon gunakan mention channel (misal: `#general`) atau ID channel yang benar. Pastikan bot berada di server tersebut.",
                color=self.color_error
            ))
            return
        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] Target channel is valid: {target_channel.name} ({target_channel.id}).")
        
        # Initial message with the button to trigger the modal
        view_instance = AnnounceButtonView(self.bot, self, ctx, target_channel, GITHUB_RAW_DESCRIPTION_URL)
        initial_msg = await ctx.send(embed=self._create_embed(
            title="🔔 Siap Membuat Pengumuman?",
            description=f"Anda akan membuat pengumuman di channel {target_channel.mention}. **Pengumuman akan dikirim menggunakan webhook**. Tekan tombol di bawah untuk mengisi detail lainnya. Deskripsi pengumuman akan diambil otomatis dari file teks di GitHub (`{GITHUB_RAW_DESCRIPTION_URL}`). Anda memiliki **60 detik** untuk mengisi formulir.",
            color=self.color_info),
            view=view_instance
        )
        view_instance.message = initial_msg
        print(f"[{datetime.now()}] [DEBUG ANNOUNCE] !announce: Modal trigger message sent.")


# Function to setup the cog in your main bot file
async def setup(bot):
    await bot.add_cog(ServerAdminCog(bot))
