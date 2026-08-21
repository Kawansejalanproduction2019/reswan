import discord
from discord.ext import commands, tasks
import json
import os
import re
import asyncio
from typing import Optional, Literal
from datetime import datetime, timedelta
import time
import aiohttp
import sys
from discord import app_commands
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont
import io
import unicodedata

WIB = timezone(timedelta(hours=7))

def load_data(file_path):
    try:
        if not os.path.exists(file_path):
            if not os.path.exists(os.path.dirname(file_path)):
                os.makedirs(os.path.dirname(file_path))
            return {}
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                return {}
            data = json.loads(content)
            return data
    except (json.JSONDecodeError, IOError) as e:
        return {}

def save_data(file_path, data):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        pass

def parse_duration(duration_str: str) -> Optional[timedelta]:
    match = re.match(r"(\d+)([smhd])", duration_str.lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == 's': return timedelta(seconds=value)
    if unit == 'm': return timedelta(minutes=value)
    if unit == 'h': return timedelta(hours=value)
    if unit == 'd': return timedelta(days=value)
    return None

async def process_and_send_announcement(cog, interaction, original_ctx, target_channel_obj, github_raw_url, title, username, profile_url, image_url, ping_everyone, poll_obj=None):
    full_description = ""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(github_raw_url) as resp:
                if resp.status == 200:
                    full_description = await resp.text()
                else:
                    await interaction.followup.send(embed=cog._create_embed(description=f"❌ Gagal mengambil deskripsi dari URL GitHub Raw ({github_raw_url}): Status HTTP {resp.status}. Pastikan URL valid dan publik.", color=cog.color_error), ephemeral=True); return
    except aiohttp.ClientError as e:
        await interaction.followup.send(embed=cog._create_embed(description=f"❌ Terjadi kesalahan jaringan saat mengambil deskripsi dari GitHub: {e}. Pastikan URL GitHub Raw benar.", color=cog.color_error), ephemeral=True); return
    except Exception as e:
        await interaction.followup.send(embed=cog._create_embed(description=f"❌ Terjadi kesalahan tidak terduga saat mengambil deskripsi: {e}", color=cog.color_error), ephemeral=True); return

    if not full_description.strip():
        await interaction.followup.send(embed=cog._create_embed(description="❌ Deskripsi pengumuman dari URL GitHub Raw kosong atau hanya berisi spasi. Pastikan file teks memiliki konten.", color=cog.color_error), ephemeral=True); return
    
    description_chunks = [full_description[i:i+4096] for i in range(0, len(full_description), 4096)]

    sent_any_embed = False
    try:
        from cogs.v2_layout import build_v2_card, send_v2_message
        for i, chunk in enumerate(description_chunks):
            if not chunk.strip(): continue
            
            footer_text = f"Pengumuman dari: {username}" if i == 0 else f"Lanjutan Pengumuman ({i+1}/{len(description_chunks)})"
            
            card = build_v2_card(
                title=title if i == 0 else None,
                description=chunk,
                color=None,
                footer=footer_text,
                media_url=image_url if i == 0 and image_url else None
            )
            
            if i == 0 and ping_everyone:
                try:
                    await target_channel_obj.send("@everyone")
                except:
                    pass
            
            result = await send_v2_message(
                bot=cog.bot, 
                channel_id=target_channel_obj.id, 
                components=[card]
            )
            if not result or (isinstance(result, dict) and "error_msg" in result):
                error_detail = result.get("error_msg", "Unknown") if isinstance(result, dict) else "None"
                raise Exception(f"Gagal mengirim pesan V2: {error_detail}")
            sent_any_embed = True
            
        if sent_any_embed and poll_obj:
            try:
                await target_channel_obj.send(poll=poll_obj)
            except Exception as e:
                await interaction.followup.send(embed=cog._create_embed(description=f"⚠️ Pengumuman terkirim, namun Polling gagal dikirim: {e}", color=cog.color_error), ephemeral=True)

    except Exception as e:
        if not sent_any_embed:
            await interaction.followup.send(embed=cog._create_embed(description=f"❌ Terjadi kesalahan saat mengirim pengumuman: {e}", color=cog.color_error), ephemeral=True)
        return

    if sent_any_embed:
        await interaction.followup.send(embed=cog._create_embed(description=f"✅ Pengumuman berhasil dikirim ke <#{target_channel_obj.id}>!", color=cog.color_success), ephemeral=True)
        await cog.log_action(original_ctx.guild, "📢 Pengumuman Baru Dibuat", {"Pengirim (Eksekutor)": original_ctx.author.mention, "Pengirim (Tampilan)": f"{username} ({profile_url if profile_url else 'Default'})", "Channel Target": f"<#{target_channel_obj.id}>", "Judul": title, "Deskripsi Sumber": github_raw_url, "Panjang Deskripsi": f"{len(full_description)} karakter", "Fitur Tambahan": f"Ping Everyone: {'Ya' if ping_everyone else 'Tidak'} | Polling: {'Ya' if poll_obj else 'Tidak'}"}, cog.color_announce)

class PollModal(discord.ui.Modal, title="Atur Polling (Jajak Pendapat)"):
    poll_question = discord.ui.TextInput(
        label="Pertanyaan Polling",
        placeholder="Contoh: Bagaimana pendapat kalian?",
        max_length=256,
        required=True,
        row=0
    )
    poll_opt1 = discord.ui.TextInput(label="Opsi 1", max_length=50, required=True, row=1)
    poll_opt2 = discord.ui.TextInput(label="Opsi 2", max_length=50, required=True, row=2)
    poll_opt3 = discord.ui.TextInput(label="Opsi 3 (Kosongkan jika tak perlu)", max_length=50, required=False, row=3)
    poll_opt4 = discord.ui.TextInput(label="Opsi 4 (Kosongkan jika tak perlu)", max_length=50, required=False, row=4)

    def __init__(self, cog, original_ctx, target_channel_obj, github_raw_url, ping_everyone, title, username, profile_url, image_url):
        super().__init__()
        self.cog = cog
        self.original_ctx = original_ctx
        self.target_channel_obj = target_channel_obj
        self.github_raw_url = github_raw_url
        self.ping_everyone = ping_everyone
        self.announcement_title = title
        self.username = username
        self.profile_url = profile_url
        self.image_url = image_url

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        question = self.poll_question.value.strip()
        answers = [self.poll_opt1.value.strip(), self.poll_opt2.value.strip()]
        if self.poll_opt3.value.strip(): answers.append(self.poll_opt3.value.strip())
        if self.poll_opt4.value.strip(): answers.append(self.poll_opt4.value.strip())
        
        from datetime import timedelta
        import discord
        poll_obj = discord.Poll(question=question, duration=timedelta(days=1))
        for answer in answers:
            poll_obj.add_answer(text=answer)
            
        await process_and_send_announcement(
            self.cog, interaction, self.original_ctx, self.target_channel_obj, self.github_raw_url,
            self.announcement_title, self.username, self.profile_url, self.image_url,
            self.ping_everyone, poll_obj
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan saat memproses polling: {error}", color=self.cog.color_error), ephemeral=True)
        else:
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan saat memproses polling: {error}", color=self.cog.color_error), ephemeral=True)

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

    def __init__(self, cog_instance, original_ctx, target_channel_obj, github_raw_url, ping_everyone, include_poll):
        super().__init__()
        self.cog = cog_instance
        self.original_ctx = original_ctx
        self.target_channel_obj = target_channel_obj
        self.github_raw_url = github_raw_url
        self.ping_everyone = ping_everyone
        self.include_poll = include_poll
        self.title = f"Pengumuman #{target_channel_obj.name}"[:45]

    async def on_submit(self, interaction: discord.Interaction):
        title = self.announcement_title.value.strip()
        username = self.custom_username.value.strip()
        profile_url = self.custom_profile_url.value.strip()
        image_url = self.announcement_image_url.value.strip()

        if not username:
            await interaction.response.send_message(embed=self.cog._create_embed(description="❌ Username Pengirim Kustom tidak boleh kosong.", color=self.cog.color_error), ephemeral=True); return
        if profile_url and not (profile_url.startswith("http://") or profile_url.startswith("https://")):
            await interaction.response.send_message(embed=self.cog._create_embed(description="❌ URL Avatar Pengirim tidak valid. Harus dimulai dengan `http://` atau `https://`.", color=self.cog.color_error), ephemeral=True); return
        if image_url and not (image_url.startswith("http://") or image_url.startswith("https://")):
            await interaction.response.send_message(embed=self.cog._create_embed(description="❌ URL Gambar Pengumuman tidak valid. Harus dimulai dengan `http://` atau `https://`.", color=self.cog.color_error), ephemeral=True); return
        
        if self.include_poll:
            class ContinuePollView(discord.ui.View):
                def __init__(self, cog, original_ctx, target_channel_obj, github_raw_url, ping_everyone, title, username, profile_url, image_url):
                    super().__init__(timeout=300)
                    self.cog = cog
                    self.original_ctx = original_ctx
                    self.target_channel_obj = target_channel_obj
                    self.github_raw_url = github_raw_url
                    self.ping_everyone = ping_everyone
                    self.announcement_title = title
                    self.username = username
                    self.profile_url = profile_url
                    self.image_url = image_url

                @discord.ui.button(label="Lanjut: Isi Polling", style=discord.ButtonStyle.primary, emoji="📋")
                async def open_poll_modal(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                    poll_modal = PollModal(
                        self.cog, self.original_ctx, self.target_channel_obj, self.github_raw_url,
                        self.ping_everyone, self.announcement_title, self.username, self.profile_url, self.image_url
                    )
                    await btn_interaction.response.send_modal(poll_modal)
                    button.disabled = True
                    try:
                        await btn_interaction.message.edit(view=self)
                    except:
                        pass

            view = ContinuePollView(
                self.cog, self.original_ctx, self.target_channel_obj, self.github_raw_url,
                self.ping_everyone, title, username, profile_url, image_url
            )
            await interaction.response.send_message(
                embed=self.cog._create_embed(description="✅ Data pengumuman disimpan! Klik tombol di bawah untuk mengisi opsi Polling.", color=self.cog.color_info),
                view=view,
                ephemeral=True
            )
            return
            
        await interaction.response.defer(ephemeral=True)
        await process_and_send_announcement(
            self.cog, interaction, self.original_ctx, self.target_channel_obj, self.github_raw_url,
            title, username, profile_url, image_url, self.ping_everyone, None
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tak terduga saat memproses formulir: {error}", color=self.cog.color_error), ephemeral=True)
        else:
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tak terduga saat memproses formulir: {error}", color=self.cog.color_error), ephemeral=True)

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
        max_length=4000,
        required=True,
        style=discord.TextStyle.paragraph,
        row=2
    )
    welcome_banner_url = discord.ui.TextInput(
        label="URL Banner (Opsional)",
        placeholder="Contoh: https://example.com/welcome_banner.png",
        max_length=2000,
        required=False,
        row=3
    )

    def __init__(self, cog_instance, guild_id, current_settings):
        super().__init__()
        self.cog = cog_instance
        self.guild_id = guild_id
        self.welcome_title.default = current_settings.get("welcome_embed_title", "")
        self.custom_sender_name.default = current_settings.get("welcome_sender_name", "")
        self.welcome_content.default = current_settings.get("welcome_message", "Selamat datang di **{guild_name}**, {user}! 🎉")
        self.welcome_banner_url.default = current_settings.get("welcome_banner_url", "")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        banner_url = self.welcome_banner_url.value.strip()
        if banner_url and not (banner_url.startswith("http://") or banner_url.startswith("https://")):
            await interaction.followup.send(embed=self.cog._create_embed(description="❌ URL Banner tidak valid. Harus dimulai dengan `http://` atau `https://`.", color=self.cog.color_error), ephemeral=True); return

        guild_settings = self.cog.get_guild_settings(self.guild_id)
        
        guild_settings["welcome_embed_title"] = self.welcome_title.value.strip()
        guild_settings["welcome_sender_name"] = self.custom_sender_name.value.strip()
        guild_settings["welcome_message"] = self.welcome_content.value.strip()
        guild_settings["welcome_banner_url"] = banner_url
        
        self.cog.save_settings()
        
        await interaction.followup.send(embed=self.cog._create_embed(description="✅ Pengaturan pesan selamat datang berhasil diperbarui!", color=self.cog.color_success), ephemeral=True)
        
        await self.cog.log_action(
            interaction.guild,
            "🎉 Pengaturan Selamat Datang Diperbarui",
            {
                "Moderator": interaction.user.mention,
                "Judul Embed": guild_settings["welcome_embed_title"],
                "Nama Pengirim": guild_settings["welcome_sender_name"],
                "Isi Pesan": f"```{guild_settings['welcome_message']}```",
                "URL Banner": guild_settings["welcome_banner_url"] if guild_settings["welcome_banner_url"] else "Tidak diatur"
            },
            self.cog.color_welcome
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tak terduga saat memproses formulir: {error}", color=self.cog.color_error), ephemeral=True)
        else:
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan tak terduga saat memproses formulir: {error}", color=self.cog.color_error), ephemeral=True)

class AnnounceButtonView(discord.ui.View):
    def __init__(self, bot_instance, cog_instance, original_ctx, target_channel_obj, github_raw_url):
        super().__init__(timeout=60)
        self.bot = bot_instance
        self.cog = cog_instance
        self.original_ctx = original_ctx
        self.target_channel_obj = target_channel_obj
        self.github_raw_url = github_raw_url 
        self.message = None
        self.ping_everyone = False
        self.include_poll = False
        self._update_buttons()

    def _update_buttons(self):
        self.toggle_ping_btn.label = "Ping @everyone: ON" if self.ping_everyone else "Ping @everyone: OFF"
        self.toggle_ping_btn.style = discord.ButtonStyle.green if self.ping_everyone else discord.ButtonStyle.secondary
        
        self.toggle_poll_btn.label = "Polling: ON" if self.include_poll else "Polling: OFF"
        self.toggle_poll_btn.style = discord.ButtonStyle.green if self.include_poll else discord.ButtonStyle.secondary

    @discord.ui.button(label="Ping @everyone: OFF", style=discord.ButtonStyle.secondary, emoji="🔔", row=0)
    async def toggle_ping_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_ctx.author.id: return await interaction.response.send_message("Bukan pesananmu.", ephemeral=True)
        self.ping_everyone = not self.ping_everyone
        self._update_buttons()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Polling: OFF", style=discord.ButtonStyle.secondary, emoji="📊", row=0)
    async def toggle_poll_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_ctx.author.id: return await interaction.response.send_message("Bukan pesananmu.", ephemeral=True)
        self.include_poll = not self.include_poll
        self._update_buttons()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Lanjut: Buka Formulir", style=discord.ButtonStyle.primary, emoji="📣", row=1)
    async def open_announcement_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_ctx.author.id:
            return await interaction.response.send_message("Hanya orang yang memulai perintah yang dapat membuat pengumuman ini.", ephemeral=True)
        
        if not self.original_ctx.author.guild_permissions.manage_guild:
            return await interaction.response.send_message("Anda tidak memiliki izin `Manage Server` untuk membuat pengumuman.", ephemeral=True)
        
        modal = AnnouncementModalGlobal(self.cog, self.original_ctx, self.target_channel_obj, self.github_raw_url, self.ping_everyone, self.include_poll)
        try:
            await interaction.response.send_modal(modal)
        except discord.Forbidden:
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Bot tidak memiliki izin untuk mengirim modal.", color=self.cog.color_error), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan saat menampilkan formulir: {e}", color=self.cog.color_error), ephemeral=True)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except:
            pass

class ModeratorActionView(discord.ui.View):
    def __init__(self, cog_instance, member: discord.Member, message: discord.Message, timeout_status: bool = False):
        super().__init__(timeout=180)
        self.cog = cog_instance
        self.member = member
        self.message = message
        self.timeout_status = timeout_status
        self._add_buttons()

    def _add_buttons(self):
        if self.member.is_timed_out():
            self.remove_timeout_button = discord.ui.Button(
                label="Remove Timeout",
                style=discord.ButtonStyle.success,
                emoji="✅",
            )
            self.remove_timeout_button.callback = self.remove_timeout_callback
            self.add_item(self.remove_timeout_button)

        self.timeout_button = discord.ui.Button(
            label="Timeout (1 Jam)",
            style=discord.ButtonStyle.green,
            emoji="⏳",
            disabled=self.timeout_status
        )
        self.timeout_button.callback = self.timeout_callback
        self.add_item(self.timeout_button)

        self.ban_button = discord.ui.Button(
            label="Ban",
            style=discord.ButtonStyle.red,
            emoji="🔨"
        )
        self.ban_button.callback = self.ban_callback
        self.add_item(self.ban_button)

        self.kick_button = discord.ui.Button(
            label="Kick",
            style=discord.ButtonStyle.secondary,
            emoji="👢"
        )
        self.kick_button.callback = self.kick_callback
        self.add_item(self.kick_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.kick_members or interaction.user.guild_permissions.ban_members

    async def remove_timeout_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.followup.send("❌ Anda tidak memiliki izin untuk mencabut timeout.", ephemeral=True)

        try:
            await self.member.timeout(None, reason=f"Timeout removed by moderator {interaction.user.display_name} via report.")
            await interaction.followup.send(f"✅ Timeout untuk anggota {self.member.mention} berhasil dicabut.", ephemeral=True)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak memiliki izin untuk mencabut timeout pada anggota ini.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    async def timeout_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.followup.send("❌ Anda tidak memiliki izin untuk melakukan timeout.", ephemeral=True)
        
        duration = timedelta(hours=1)
        reason = f"Timeout by moderator {interaction.user.display_name} via report for a rule violation (link filter)."
        try:
            await self.member.timeout(duration, reason=reason)
            await interaction.followup.send(f"✅ Anggota {self.member.mention} berhasil di-timeout lagi selama 1 jam.", ephemeral=True)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak memiliki izin untuk melakukan timeout pada anggota ini.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    async def ban_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.followup.send("❌ Anda tidak memiliki izin untuk melakukan ban.", ephemeral=True)

        reason = f"Banned by moderator {interaction.user.display_name} via report for a rule violation (link filter)."
        try:
            await self.member.ban(reason=reason)
            await interaction.followup.send(f"✅ Anggota {self.member.mention} berhasil di-ban.", ephemeral=True)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak memiliki izin untuk melakukan ban pada anggota ini.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    async def kick_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.kick_members:
            return await interaction.followup.send("❌ Anda tidak memiliki izin untuk melakukan kick.", ephemeral=True)

        reason = f"Kicked by moderator {interaction.user.display_name} via report for a rule violation (link filter)."
        try:
            await self.member.kick(reason=reason)
            await interaction.followup.send(f"✅ Anggota {self.member.mention} berhasil di-kick.", ephemeral=True)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak memiliki izin untuk melakukan kick pada anggota ini.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

class UniversalMembershipVerificationButton(discord.ui.Button):
    def __init__(self, cog_instance, label: str, **kwargs):
        super().__init__(label=label, **kwargs)
        self.cog = cog_instance
        self.custom_id = f"universal_membership_check_{label.replace(' ', '_').lower()}"

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        member = interaction.user
        guild_settings = self.cog.get_guild_settings(interaction.guild_id)
        
        is_member, tier_name = await self.cog.check_membership_status(member)
        
        if is_member:
            confirm_message = guild_settings.get("membership_confirm_message", "🎉 Anda sudah menjadi anggota! Anda adalah anggota tier: **{tier_name}**.")
            
            final_message = confirm_message.format(tier_name=tier_name, member=member.mention)
            await interaction.followup.send(embed=self.cog._create_embed(description=final_message, color=self.cog.color_success), ephemeral=True)
            
        else:
            invite_message = guild_settings.get("membership_invite_message", "🥺 Anda belum menjadi anggota channel YouTube. Silakan berlangganan untuk mendapatkan role eksklusif! [LINK MEMBERSHIP]")
            
            final_message = invite_message.format(member=member.mention) 
            
            await interaction.followup.send(embed=self.cog._create_embed(description=final_message, color=self.cog.color_warning), ephemeral=True)

class UniversalMembershipView(discord.ui.View):
    def __init__(self, cog_instance, button_label: str):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.add_item(UniversalMembershipVerificationButton(
            cog_instance=self.cog,
            label=button_label,
            style=discord.ButtonStyle.primary,
            emoji="✅"
        ))

class DynamicRoleSelect(discord.ui.Select):
    def __init__(self, roles_data, custom_id, placeholder_text="✨ Pilih role yang ingin kamu ambil"):
        options = []
        for role_id_str, data in roles_data.items():
            desc = data.get('description', None)
            options.append(discord.SelectOption(
                label=data['label'],
                emoji=data.get('emoji', None),
                value=role_id_str,
                description=desc
            ))
        super().__init__(
            placeholder=placeholder_text,
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id=custom_id
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user

        panel_role_ids = [int(r_id) for r_id in self.view.roles_data.keys()]
        selected_role_ids = [int(v) for v in self.values]

        added_roles = []
        removed_roles = []
        failed_roles = []

        for role_id in panel_role_ids:
            role = guild.get_role(role_id)
            if not role:
                continue
            try:
                if role_id in selected_role_ids and role not in member.roles:
                    await member.add_roles(role, reason="Role Panel Self-Assign")
                    added_roles.append(role.name)
                elif role_id not in selected_role_ids and role in member.roles:
                    await member.remove_roles(role, reason="Role Panel Self-Remove")
                    removed_roles.append(role.name)
            except discord.Forbidden:
                failed_roles.append(role.name)

        if not added_roles and not removed_roles and not failed_roles:
            result_embed = discord.Embed(
                description="ℹ️ Tidak ada perubahan role.",
                color=0x5865F2
            )
        else:
            lines = []
            if added_roles:
                lines.append(f"**➕ Ditambahkan**\n" + "\n".join(f"> `{r}`" for r in added_roles))
            if removed_roles:
                lines.append(f"**➖ Dilepas**\n" + "\n".join(f"> `{r}`" for r in removed_roles))
            if failed_roles:
                lines.append(f"**❌ Gagal (izin bot)**\n" + "\n".join(f"> `{r}`" for r in failed_roles))

            result_embed = discord.Embed(
                title="✅ Pembaruan Role Berhasil",
                description="\n\n".join(lines),
                color=0x57F287
            )
        result_embed.set_footer(text=f"Diperbarui untuk {member.display_name}")
        await interaction.followup.send(embed=result_embed, ephemeral=True)


class DynamicRoleButton(discord.ui.Button):
    def __init__(self, role_id_str, data):
        super().__init__(
            label=data['label'],
            emoji=data.get('emoji', None),
            style=discord.ButtonStyle.secondary,
            custom_id=f"rolebtn_{role_id_str}"
        )
        self.role_id = int(role_id_str)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        role = interaction.guild.get_role(self.role_id)
        if not role:
            return await interaction.followup.send(
                embed=discord.Embed(description="❌ Role tidak ditemukan di server.", color=0xED4245),
                ephemeral=True
            )
        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Role Panel Self-Remove")
                embed = discord.Embed(
                    description=f"➖ Role **{role.name}** berhasil dilepas.",
                    color=0xFEE75C
                )
            else:
                await interaction.user.add_roles(role, reason="Role Panel Self-Assign")
                embed = discord.Embed(
                    description=f"➕ Role **{role.name}** berhasil diberikan.",
                    color=0x57F287
                )
            embed.set_footer(text=f"Diperbarui untuk {interaction.user.display_name}")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=discord.Embed(description=f"❌ Bot tidak memiliki izin untuk mengatur role ini.", color=0xED4245),
                ephemeral=True
            )


class DynamicRoleView(discord.ui.View):
    def __init__(self, mode, roles_data, message_id, placeholder_text="✨ Pilih role yang ingin kamu ambil"):
        super().__init__(timeout=None)
        self.roles_data = roles_data
        self.message_id = message_id
        if not roles_data:
            empty_btn = discord.ui.Button(label="Belum ada role yang ditambahkan", disabled=True, style=discord.ButtonStyle.secondary)
            self.add_item(empty_btn)
            return
        if mode == "select":
            self.add_item(DynamicRoleSelect(roles_data, f"roleselect_{message_id}", placeholder_text))
        elif mode == "button":
            for role_id_str, data in roles_data.items():
                self.add_item(DynamicRoleButton(role_id_str, data))


class ServerAdminCog(commands.Cog, name="👑 Administrasi"):
    def __init__(self, bot):
        self.bot = bot
        self.settings_file = "data/settings.json"
        self.filters_file = "data/filters.json"
        self.warnings_file = "data/warnings.json"
        self.status_file = "data/status.json"
        self.mod_panel_message_id = None
        self.mod_panel_channel_id = None
        
        self.modpanel_buttons = [
            {"label": "Warn", "style": 2, "emoji": "⚠️", "custom_id": "modpanel_warn"},
            {"label": "Timeout", "style": 1, "emoji": "⏳", "custom_id": "modpanel_timeout"},
            {"label": "Kick", "style": 4, "emoji": "👢", "custom_id": "modpanel_kick"},
            {"label": "Ban", "style": 4, "emoji": "🔨", "custom_id": "modpanel_ban"},
            {"label": "Unwarn", "style": 3, "emoji": "🛡️", "custom_id": "modpanel_unwarn"},
            {"label": "Untimeout", "style": 3, "emoji": "⏱️", "custom_id": "modpanel_untimeout"},
            {"label": "Unban", "style": 3, "emoji": "🤝", "custom_id": "modpanel_unban"},
            {"label": "Clear Chat", "style": 4, "emoji": "🧹", "custom_id": "modpanel_clear"},
            {"label": "Lock", "style": 4, "emoji": "🔒", "custom_id": "modpanel_lock"},
            {"label": "Unlock", "style": 3, "emoji": "🔓", "custom_id": "modpanel_unlock"}
        ]
        self.spam_messages = {}
        self.spam_history = {}
        self.cross_channel_spam_history = {}
        
        self.reminder_channel_id = 1379762287149187162
        self.male_role_id = 1385246612288311326
        self.female_role_id = 1379461360873898017
        
        self.common_prefixes = ('!', '.', '?', '-', '$', '%', '&', '#', '+', '=')
        self.url_regex = re.compile(r'https?://[^\s/$.?#].[^\s]*')
        
        self.color_success = 0xFFE000 
        self.color_error = 0xFFE000
        self.color_info = 0xFFE000
        self.color_warning = 0xF1C40F
        self.color_log = 0xFFE000
        self.color_welcome = 0xFFE000
        self.color_announce = 0xFFE000
        self.color_booster = 0xFFE000
        
        self.media_spam_cooldown = commands.CooldownMapping.from_cooldown(3, 30.0, commands.BucketType.user)
        self.media_spam_rapid_cooldown = commands.CooldownMapping.from_cooldown(5, 10.0, commands.BucketType.user)
        self.media_spam_heavy_cooldown = commands.CooldownMapping.from_cooldown(8, 60.0, commands.BucketType.user)
        self.link_spam_cooldown = commands.CooldownMapping.from_cooldown(2, 60.0, commands.BucketType.user)
        self.fast_spam_cooldown = commands.CooldownMapping.from_cooldown(5, 10.0, commands.BucketType.user)
        self.global_spam_cooldown = commands.CooldownMapping.from_cooldown(8, 15.0, commands.BucketType.user)
        self.multi_media_cooldown = commands.CooldownMapping.from_cooldown(1, 5.0, commands.BucketType.user)

        self.mongo_client = getattr(bot, 'mongo_client', None)
        if self.mongo_client:
            self.db = self.mongo_client["reSwan"]
            self.settings_col = self.db["moderation_settings"]
            self.filters_col = self.db["moderation_filters"]
            self.warnings_col = self.db["moderation_warnings"]
            self.status_col = self.db["moderation_status"]
        else:
            self.settings_col = None
            self.filters_col = None
            self.warnings_col = None
            self.status_col = None

        self.settings = self.load_data_from_mongo(self.settings_col, self.settings_file)
        self.filters = self.load_data_from_mongo(self.filters_col, self.filters_file)
        self.warnings = self.load_data_from_mongo(self.warnings_col, self.warnings_file)
        self.status = self.load_data_from_mongo(self.status_col, self.status_file)
        
        for guild_id_str, g_settings in self.settings.items():
            if isinstance(g_settings, dict):
                if "announcement_webhooks" not in g_settings:
                    g_settings["announcement_webhooks"] = {}
        self.save_settings()

        if "status" not in self.status:
            self.status["status"] = "online"
            self.save_status()
        
        for guild_id_str, settings in self.settings.items():
            if isinstance(settings, dict):
                if 'verification_button_label' in settings:
                    try:
                        self.bot.add_view(UniversalMembershipView(self, settings['verification_button_label']))
                    except Exception:
                        pass

        self.update_panel_task.start()
        self.cleanup_spam_history.start()
        
    def cog_unload(self):
        self.update_panel_task.cancel()
        self.cleanup_spam_history.cancel()

    async def _create_welcome_card(self, member: discord.Member, title: str) -> io.BytesIO:
        width = 800
        height = 250
        background = Image.new('RGBA', (width, height), (20, 22, 26, 255))
        draw = ImageDraw.Draw(background)
        
        # Left accent circle
        draw.ellipse((-150, -50, 320, 400), fill=(30, 34, 45, 255)) 
        draw.ellipse((-130, -30, 300, 380), outline=(88, 101, 242, 180), width=4) 
        
        try:
            avatar_bytes = await member.display_avatar.replace(size=128, format="png").read()
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_img = avatar_img.resize((150, 150))
            mask = Image.new("L", (150, 150), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 150, 150), fill=255)
            background.paste(avatar_img, (60, 50), mask)
            draw.ellipse((56, 46, 214, 214), outline=(88, 101, 242, 255), width=6)
        except Exception:
            pass

        try:
            url_bold = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf"
            url_reg = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf"
            async with aiohttp.ClientSession() as session:
                async with session.get(url_bold) as r1:
                    font_bold_bytes = await r1.read()
                    font_bold = ImageFont.truetype(io.BytesIO(font_bold_bytes), 42)
                    font_title = ImageFont.truetype(io.BytesIO(font_bold_bytes), 22)
                async with session.get(url_reg) as r2:
                    font_reg_bytes = await r2.read()
                    font_sub = ImageFont.truetype(io.BytesIO(font_reg_bytes), 20)
                    font_small = ImageFont.truetype(io.BytesIO(font_reg_bytes), 16)
        except Exception:
            font_bold = ImageFont.load_default()
            font_title = ImageFont.load_default()
            font_sub = ImageFont.load_default()
            font_small = ImageFont.load_default()

        import unicodedata
        safe_guild = unicodedata.normalize('NFKC', member.guild.name)
        safe_name = unicodedata.normalize('NFKC', member.display_name)
        
        text_x = 360
        
        draw.text((text_x, 40), title, font=font_title, fill=(114, 137, 218, 255))
        draw.text((text_x, 70), safe_name, font=font_bold, fill=(255, 255, 255, 255))
        
        draw.line([(text_x, 135), (750, 135)], fill=(100, 100, 100, 80), width=2)
        
        draw.text((text_x, 150), f"Selamat datang di {safe_guild}!", font=font_sub, fill=(200, 200, 200, 255))
        draw.text((text_x, 185), "Semoga betah dan aktif terus ya!", font=font_sub, fill=(150, 255, 150, 255))
        
        badge_text = f"Member #{member.guild.member_count}"
        draw.rounded_rectangle([(630, 20), (760, 50)], radius=15, fill=(40, 44, 52, 255), outline=(88, 101, 242, 180), width=1)
        draw.text((650, 25), badge_text, font=font_small, fill=(200, 200, 200, 255))

        buffer = io.BytesIO()
        background.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    async def _create_goodbye_card(self, member: discord.Member, title: str) -> io.BytesIO:
        width = 800
        height = 250
        background = Image.new('RGBA', (width, height), (26, 20, 20, 255))
        draw = ImageDraw.Draw(background)
        
        draw.ellipse((-150, -50, 320, 400), fill=(40, 25, 25, 255)) 
        draw.ellipse((-130, -30, 300, 380), outline=(242, 88, 88, 180), width=4)
        
        try:
            avatar_bytes = await member.display_avatar.replace(size=128, format="png").read()
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_img = avatar_img.resize((150, 150))
            mask = Image.new("L", (150, 150), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 150, 150), fill=255)
            
            grayscale = avatar_img.convert('L')
            grayscale_rgba = Image.new("RGBA", grayscale.size)
            grayscale_rgba.paste(grayscale, (0, 0), mask)
            
            background.paste(grayscale_rgba, (60, 50), mask)
            draw.ellipse((56, 46, 214, 214), outline=(242, 88, 88, 255), width=6)
        except Exception:
            pass

        try:
            url_bold = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf"
            url_reg = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf"
            async with aiohttp.ClientSession() as session:
                async with session.get(url_bold) as r1:
                    font_bold_bytes = await r1.read()
                    font_bold = ImageFont.truetype(io.BytesIO(font_bold_bytes), 42)
                    font_title = ImageFont.truetype(io.BytesIO(font_bold_bytes), 22)
                async with session.get(url_reg) as r2:
                    font_reg_bytes = await r2.read()
                    font_sub = ImageFont.truetype(io.BytesIO(font_reg_bytes), 20)
        except Exception:
            font_bold = ImageFont.load_default()
            font_title = ImageFont.load_default()
            font_sub = ImageFont.load_default()

        import unicodedata
        safe_guild = unicodedata.normalize('NFKC', member.guild.name)
        safe_name = unicodedata.normalize('NFKC', member.display_name)
        
        text_x = 360
        
        draw.text((text_x, 40), title, font=font_title, fill=(235, 100, 100, 255))
        draw.text((text_x, 70), safe_name, font=font_bold, fill=(255, 255, 255, 255))
        
        draw.line([(text_x, 135), (750, 135)], fill=(100, 100, 100, 80), width=2)
        
        draw.text((text_x, 150), f"Telah meninggalkan {safe_guild}...", font=font_sub, fill=(180, 180, 180, 255))
        draw.text((text_x, 185), "Yah, padahal lagi seru-serunya...", font=font_sub, fill=(255, 150, 150, 255))

        buffer = io.BytesIO()
        background.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    def get_guild_settings(self, guild_id: int):
        guild_id_str = str(guild_id)
        if guild_id_str not in self.settings:
            self.settings[guild_id_str] = {
                "auto_role_id": None, 
                "welcome_channel_id": None,
                "welcome_message": "Selamat datang di **{guild_name}**, {user}! 🎉",
                "welcome_embed_title": "SELAMAT DATANG!",
                "welcome_sender_name": "Admin Server",
                "welcome_banner_url": None, 
                "log_channel_id": None, 
                "reaction_roles": {},
                "channel_rules": {},
                "boost_channel_id": None,
                "boost_message": "Terima kasih banyak, {user}, telah menjadi **Server Booster** kami di {guild_name}! Kami sangat menghargai dukunganmu! ❤️",
                "boost_embed_title": "TERIMA KASIH SERVER BOOSTER!",
                "boost_sender_name": "Tim Server",
                "boost_image_url": None,
                "mod_panel_message_id": None,
                "mod_panel_channel_id": None,
                "main_membership_role_id": None, 
                "membership_roles": {}, 
                "membership_invite_message": "🥺 Anda belum menjadi anggota channel YouTube. Silakan berlangganan untuk mendapatkan role eksklusif! [LINK MEMBERSHIP]", 
                "membership_confirm_message": "🎉 Anda sudah menjadi anggota! Anda adalah anggota tier: **{tier_name}**.",
                "verification_button_label": "Verifikasi Membership",
                "spam_whitelist_roles": [],
                "goodbye_message": "Selamat tinggal, **{user}**. Sampai jumpa lagi! 👋",
                "panel_role_stats": []
                
            }
            save_data(self.settings_file, self.settings)
        if "role_panels" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["role_panels"] = {}
        if "goodbye_message" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["goodbye_message"] = "Selamat tinggal, **{user}**. Sampai jumpa lagi! 👋"
        if "welcome_embed_title" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["welcome_embed_title"] = "SELAMAT DATANG!"
        if "welcome_sender_name" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["welcome_sender_name"] = "Admin Server"
        if "welcome_banner_url" not in self.settings[guild_id_str]: 
            self.settings[guild_id_str]["welcome_banner_url"] = None
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
        if "announcement_webhooks" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["announcement_webhooks"] = {}
        if "mod_panel_message_id" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["mod_panel_message_id"] = None
        if "mod_panel_channel_id" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["mod_panel_channel_id"] = None
        if "main_membership_role_id" not in self.settings[guild_id_str]: 
            self.settings[guild_id_str]["main_membership_role_id"] = None
        if "membership_roles" not in self.settings[guild_id_str]: 
            self.settings[guild_id_str]["membership_roles"] = {}
        if "membership_invite_message" not in self.settings[guild_id_str]: 
            self.settings[guild_id_str]["membership_invite_message"] = "🥺 Anda belum menjadi anggota channel YouTube. Silakan berlangganan untuk mendapatkan role eksklusif! [LINK MEMBERSHIP]"
        if "membership_confirm_message" not in self.settings[guild_id_str]: 
            self.settings[guild_id_str]["membership_confirm_message"] = "🎉 Anda sudah menjadi anggota! Anda adalah anggota tier: **{tier_name}**."
        if "verification_button_label" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["verification_button_label"] = "Verifikasi Membership" 
        if "spam_whitelist_roles" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["spam_whitelist_roles"] = []
        if "panel_role_stats" not in self.settings[guild_id_str]:
            self.settings[guild_id_str]["panel_role_stats"] = []


        save_data(self.settings_file, self.settings)
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
        return guild_settings["channel_rules"][channel_id_str]
        
    def get_guild_filters(self, guild_id: int):
        guild_id_str = str(guild_id)
        if guild_id_str not in self.filters:
            self.filters[guild_id_str] = { "bad_words": [], "link_patterns": [] }
            save_data(self.filters_file, self.filters)
        return self.filters[guild_id_str]
        
    def load_data_from_mongo(self, collection, local_path):
        if collection is not None:
            try:
                doc = collection.find_one({"_id": local_path})
                if doc and "data" in doc:
                    return doc["data"]
            except Exception:
                pass
        return load_data(local_path)

    def save_settings(self):
        save_data(self.settings_file, self.settings)
        if self.settings_col is not None:
            try:
                self.settings_col.replace_one({"_id": self.settings_file}, {"_id": self.settings_file, "data": self.settings}, upsert=True)
            except Exception:
                pass

    def save_filters(self):
        save_data(self.filters_file, self.filters)
        if self.filters_col is not None:
            try:
                self.filters_col.replace_one({"_id": self.filters_file}, {"_id": self.filters_file, "data": self.filters}, upsert=True)
            except Exception:
                pass

    def save_warnings(self):
        save_data(self.warnings_file, self.warnings)
        if self.warnings_col is not None:
            try:
                self.warnings_col.replace_one({"_id": self.warnings_file}, {"_id": self.warnings_file, "data": self.warnings}, upsert=True)
            except Exception:
                pass

    def save_status(self):
        save_data(self.status_file, self.status)
        if self.status_col is not None:
            try:
                self.status_col.replace_one({"_id": self.status_file}, {"_id": self.status_file, "data": self.status}, upsert=True)
            except Exception:
                pass

    async def check_and_escalate_warnings(self, guild, member, moderator):
        guild_id_str = str(guild.id)
        member_id_str = str(member.id)
        user_warnings = self.warnings.get(guild_id_str, {}).get(member_id_str, [])
        warn_count = len(user_warnings)

        escalation_applied = None
        duration = None

        if warn_count == 3:
            duration = timedelta(hours=1)
            escalation_applied = "Auto-Timeout (1 Hour) due to 3 warnings"
        elif warn_count >= 5:
            duration = timedelta(days=1)
            escalation_applied = "Auto-Timeout (1 Day) due to 5+ warnings"

        if duration:
            try:
                await member.timeout(duration, reason=escalation_applied)
                # Log escalation to channel
                log_embed = self._create_embed(
                    title="🚨 Auto Escalation Triggered",
                    description=f"{member.mention} has been auto-timed out because they have reached **{warn_count} warnings**.",
                    color=self.color_error
                )
                log_embed.add_field(name="Member", value=f"{member} ({member.id})", inline=True)
                log_embed.add_field(name="Action", value=escalation_applied, inline=True)

                log_channel_id = self.get_guild_settings(guild.id).get("log_channel_id")
                if log_channel_id:
                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel:
                        await log_channel.send(embed=log_embed)
                return escalation_applied
            except Exception:
                pass
        return None

    def _create_embed(self, title: str = "", description: str = "", color: int = 0, author_name: str = "", author_icon_url: str = ""):
        embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(WIB))
        if author_name: embed.set_author(name=author_name, icon_url=author_icon_url)
        bot_icon_url = self.bot.user.display_avatar.url if self.bot.user.display_avatar else None
        embed.set_footer(text=f"Dijalankan oleh {self.bot.user.name}", icon_url=bot_icon_url)
        return embed

    async def log_action(self, guild: discord.Guild, title: str, fields: dict, color: int):
        if not (log_channel_id := self.get_guild_settings(guild.id).get("log_channel_id")):
            return
        if (log_channel := guild.get_channel(log_channel_id)) and log_channel.permissions_for(guild.me).send_messages:
            embed = self._create_embed(title=title, color=color, timestamp=datetime.now(WIB))
            for name, value in fields.items():
                embed.add_field(name=name, value=value, inline=False)
            try:
                await log_channel.send(embed=embed)
            except discord.Forbidden:
                pass
        else:
            pass
    async def send_spam_log_v2(self, guild: discord.Guild, member: discord.Member, trigger_channels: str, reason: str, detailed_reason: str, message_id: str):
        spam_log_channel_id = self.get_guild_settings(guild.id).get("spam_log_channel_id")
        if not spam_log_channel_id: return
        log_channel = guild.get_channel(spam_log_channel_id)
        if not log_channel or not log_channel.permissions_for(guild.me).send_messages: return

        from cogs.v2_layout import build_v2_card, send_v2_message
        import time

        v2_fields = [
            {"name": "👤 Pelaku", "value": f"{member.mention} (`{member.id}`)"},
            {"name": "📝 Reason", "value": reason},
            {"name": "🔍 Detailed Reason", "value": detailed_reason},
            {"name": "📍 Channel", "value": trigger_channels},
            {"name": "🆔 Message ID", "value": f"`{message_id}`"},
            {"name": "⏰ Waktu Kejadian", "value": f"<t:{int(time.time())}:F>"}
        ]
        
        card = build_v2_card(
            title="⚠️ ANTI-SPAM & PHISHING SYSTEM ⚠️",
            description="Tindakan otomatis telah diambil berdasarkan kebijakan keamanan server.",
            fields=v2_fields,
            color=None,
            footer=f"Sistem Keamanan Otomatis • {guild.name}"
        )
        
        try:
            await send_v2_message(self.bot, log_channel.id, [card])
        except:
            pass

    async def get_or_create_announcement_webhook(self, channel: discord.TextChannel, custom_name: str):
        guild_settings = self.get_guild_settings(channel.guild.id)
        webhook_url = guild_settings.get("announcement_webhooks", {}).get(str(channel.id))
        
        if webhook_url:
            try:
                webhook = discord.Webhook.from_url(webhook_url, client=self.bot)
                await webhook.fetch()
                return webhook
            except (discord.NotFound, aiohttp.ClientError):
                pass
        
        try:
            webhook_name = f"{custom_name}" if custom_name else f"Pengumuman Server"
            avatar_url = channel.guild.icon.url if channel.guild.icon else None
            
            existing_webhooks = await channel.webhooks()
            for wh in existing_webhooks:
                if wh.user.id == self.bot.user.id:
                    webhook = wh
                    break
            else:
                webhook = await channel.create_webhook(name=webhook_name, avatar=await channel.guild.icon.read() if channel.guild.icon else None, reason="For automatic announcements.")
            
            guild_settings["announcement_webhooks"][str(channel.id)] = webhook.url
            self.save_settings()
            return webhook
        except discord.Forbidden:
            raise

    async def check_membership_status(self, member: discord.Member) -> tuple[bool, Optional[str]]:
        guild_settings = self.get_guild_settings(member.guild.id)
        main_role_id = guild_settings.get("main_membership_role_id")
        
        if not main_role_id:
            return False, "ERROR: Main Role Belum Diatur" 

        main_role = member.guild.get_role(main_role_id)
        if not main_role or main_role not in member.roles:
            return False, None

        membership_roles_data = guild_settings.get("membership_roles", {})
        
        tier_roles_in_guild = []
        for role_id_str, data in membership_roles_data.items():
            if role := member.guild.get_role(int(role_id_str)):
                tier_roles_in_guild.append((role.position, role.id, data['tier_name']))

        tier_roles_in_guild.sort(key=lambda x: x[0], reverse=True)

        for position, role_id, tier_name in tier_roles_in_guild:
            if role_id in [r.id for r in member.roles]:
                return True, tier_name
        
        return True, "Base Tier / Tier Role Belum Didaftarkan"

    def detect_suspicious_links(self, content: str) -> bool:
        suspicious_patterns = [
            r'discord\.gift', r'discord\.com\/gifts', r'discordapp\.com\/gifts',
            r'free-nitro', r'steam-community', r'steamcommunity\.com',
            r'bit\.ly', r'tinyurl\.com', r'shorturl\.at', r'rb\.gy',
            r'discord-nitro', r'claim-reward', r'free-gift'
        ]
        
        content_lower = content.lower()
        
        for pattern in suspicious_patterns:
            if re.search(pattern, content_lower):
                return True
        
        urls = self.url_regex.findall(content)
        for url in urls:
            if any(suspicious in url.lower() for suspicious in ['discordgift', 'nitro-free', 'steamgift']):
                return True
    
        return False

    def is_allowed_file_type(self, filename: str) -> bool:
        allowed_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
            '.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx',
            '.zip', '.rar', '.7z',
            '.mp3', '.wav', '.ogg',
            '.mp4', '.mov', '.avi'
        }
        
        file_ext = os.path.splitext(filename.lower())[1]
        return file_ext in allowed_extensions

    @tasks.loop(minutes=5)
    async def cleanup_spam_history(self):
        current_time = time.time()
        
        for user_id in list(self.cross_channel_spam_history.keys()):
            self.cross_channel_spam_history[user_id] = [
                entry for entry in self.cross_channel_spam_history[user_id]
                if current_time - entry['timestamp'] <= 300
            ]
            
            if not self.cross_channel_spam_history[user_id]:
                del self.cross_channel_spam_history[user_id]
    def _build_role_panel_embeds_and_view(
        self,
        guild: discord.Guild,
        panel_data: dict,
        message_id: str
    ) -> tuple[list[discord.Embed], DynamicRoleView]:
        embed1 = discord.Embed()

        title_text = panel_data.get("title", "Role Panel")
        desc_text = panel_data.get("description", "")

        full_desc = f"# {title_text}"
        if desc_text:
            full_desc += f"\n{desc_text}"

        embed1.description = full_desc

        if guild.icon:
            embed1.set_thumbnail(url=guild.icon.url)

        content_text = panel_data.get("content", "")
        embeds: list[discord.Embed] = [embed1]

        if content_text:
            embed2 = discord.Embed()
            embed2.description = content_text
            embeds.append(embed2)

        roles_data = panel_data.get("roles", {})
        mode = panel_data.get("mode", "select")
        placeholder = panel_data.get("placeholder", "✨ Pilih role yang ingin kamu ambil")
        view = DynamicRoleView(mode, roles_data, message_id, placeholder)

        return embeds, view

    @commands.hybrid_command(name="setuppanelrole", description="Buat panel role dengan UI embed keren")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        channel="Channel tujuan panel",
        mode="Pilih mode tampilan: select (dropdown) atau button",
        judul="Judul besar panel (akan ditampilkan sebagai heading)",
        deskripsi_judul="Teks biasa di bawah judul (opsional)",
        konten_embed2="Teks untuk embed kedua (opsional — bisa untuk panduan/deskripsi tambahan)",
        placeholder_select="Teks placeholder untuk dropdown select (opsional)",
    )
    async def setuppanelrole(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        mode: Literal["select", "button"],
        judul: str,
        deskripsi_judul: Optional[str] = None,
        konten_embed2: Optional[str] = None,
        placeholder_select: Optional[str] = None,
    ):
        guild_settings = self.get_guild_settings(ctx.guild.id)

        panel_data = {
            "channel_id":   channel.id,
            "mode":         mode,
            "title":        judul,
            "description":  deskripsi_judul or "",
            "content":      konten_embed2 or "",
            "placeholder":  placeholder_select or "✨ Pilih role yang ingin kamu ambil",
            "roles":        {}
        }

        embeds, view = self._build_role_panel_embeds_and_view(ctx.guild, panel_data, "PLACEHOLDER")
        msg = await channel.send(embeds=embeds, view=view)

        guild_settings.setdefault("role_panels", {})[str(msg.id)] = panel_data
        self.save_settings()

        _, real_view = self._build_role_panel_embeds_and_view(ctx.guild, panel_data, str(msg.id))
        await msg.edit(embeds=embeds, view=real_view)

        confirm_embed = self._create_embed(
            title="✅ Panel Role Berhasil Dibuat",
            description=(
                f"Panel dikirim ke {channel.mention}\n"
                f"**ID Pesan:** `{msg.id}`\n"
                f"**Mode:** `{mode}`\n\n"
                f"Gunakan `/addpanelrole {msg.id} @role 🎭 Label` untuk menambahkan role."
            ),
            color=self.color_success
        )
        await ctx.send(embed=confirm_embed, ephemeral=True)

    @commands.hybrid_command(name="addpanelrole", description="Tambah role ke dalam Panel Role")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        message_id="ID pesan panel role (dari /setuppanelrole)",
        role="Role yang akan ditambahkan",
        emoji="Emoji untuk role ini",
        label_teks="Label teks untuk role ini",
        deskripsi_role="Deskripsi singkat role (muncul di bawah label pada select mode, maks 100 karakter)",
    )
    async def addpanelrole(
        self,
        ctx: commands.Context,
        message_id: str,
        role: discord.Role,
        emoji: str,
        label_teks: str,
        deskripsi_role: Optional[str] = None,
    ):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        panels = guild_settings.get("role_panels", {})

        if message_id not in panels:
            return await ctx.send(
                embed=self._create_embed(description="❌ Panel tidak ditemukan. Pastikan ID pesan benar.", color=self.color_error),
                ephemeral=True
            )

        panel_data = panels[message_id]
        panel_data["roles"][str(role.id)] = {
            "emoji":       emoji,
            "label":       label_teks,
            "description": (deskripsi_role or "")[:100]
        }
        self.save_settings()

        try:
            channel = ctx.guild.get_channel(panel_data["channel_id"])
            if not channel:
                return await ctx.send(embed=self._create_embed(description="❌ Channel panel tidak ditemukan.", color=self.color_error), ephemeral=True)

            msg     = await channel.fetch_message(int(message_id))
            embeds, view = self._build_role_panel_embeds_and_view(ctx.guild, panel_data, message_id)
            await msg.edit(embeds=embeds, view=view)

            await ctx.send(
                embed=self._create_embed(
                    description=f"✅ Role {role.mention} berhasil ditambahkan ke panel.",
                    color=self.color_success
                ),
                ephemeral=True
            )
        except discord.NotFound:
            await ctx.send(embed=self._create_embed(description="❌ Pesan panel tidak ditemukan (mungkin sudah dihapus).", color=self.color_error), ephemeral=True)
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ Gagal mengedit panel: `{e}`", color=self.color_error), ephemeral=True)

    @commands.hybrid_command(name="removepanelrole", description="Hapus role dari Panel Role")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        message_id="ID pesan panel role",
        role="Role yang akan dihapus dari panel",
    )
    async def removepanelrole(self, ctx: commands.Context, message_id: str, role: discord.Role):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        panels = guild_settings.get("role_panels", {})

        if message_id not in panels:
            return await ctx.send(embed=self._create_embed(description="❌ Panel tidak ditemukan.", color=self.color_error), ephemeral=True)

        panel_data = panels[message_id]
        role_id_str = str(role.id)

        if role_id_str not in panel_data["roles"]:
            return await ctx.send(embed=self._create_embed(description=f"❌ Role {role.mention} tidak ada di panel ini.", color=self.color_error), ephemeral=True)

        del panel_data["roles"][role_id_str]
        self.save_settings()

        try:
            channel = ctx.guild.get_channel(panel_data["channel_id"])
            if not channel:
                return await ctx.send(embed=self._create_embed(description="❌ Channel panel tidak ditemukan.", color=self.color_error), ephemeral=True)

            msg     = await channel.fetch_message(int(message_id))
            embeds, view = self._build_role_panel_embeds_and_view(ctx.guild, panel_data, message_id)
            await msg.edit(embeds=embeds, view=view)

            await ctx.send(
                embed=self._create_embed(description=f"✅ Role **{role.name}** berhasil dihapus dari panel.", color=self.color_success),
                ephemeral=True
            )
        except discord.NotFound:
            await ctx.send(embed=self._create_embed(description="❌ Pesan panel tidak ditemukan.", color=self.color_error), ephemeral=True)
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ Gagal mengedit panel: `{e}`", color=self.color_error), ephemeral=True)

    @commands.hybrid_command(name="editpanelrole", description="Edit konten teks Panel Role yang sudah ada")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        message_id="ID pesan panel role",
        judul="Judul baru (kosongkan untuk tidak mengubah)",
        deskripsi_judul="Deskripsi teks di bawah judul (kosongkan untuk tidak mengubah)",
        konten_embed2="Teks embed kedua — kirim 'HAPUS' untuk menghapus embed kedua",
        placeholder_select="Teks placeholder dropdown baru",
    )
    async def editpanelrole(
        self,
        ctx: commands.Context,
        message_id: str,
        judul: Optional[str] = None,
        deskripsi_judul: Optional[str] = None,
        konten_embed2: Optional[str] = None,
        placeholder_select: Optional[str] = None,
    ):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        panels = guild_settings.get("role_panels", {})

        if message_id not in panels:
            return await ctx.send(embed=self._create_embed(description="❌ Panel tidak ditemukan.", color=self.color_error), ephemeral=True)

        panel_data = panels[message_id]

        if judul:
            panel_data["title"] = judul
        if deskripsi_judul is not None:
            panel_data["description"] = deskripsi_judul
        if konten_embed2 is not None:
            panel_data["content"] = "" if konten_embed2.upper() == "HAPUS" else konten_embed2
        if placeholder_select:
            panel_data["placeholder"] = placeholder_select

        self.save_settings()

        try:
            channel = ctx.guild.get_channel(panel_data["channel_id"])
            if not channel:
                return await ctx.send(embed=self._create_embed(description="❌ Channel panel tidak ditemukan.", color=self.color_error), ephemeral=True)

            msg     = await channel.fetch_message(int(message_id))
            embeds, view = self._build_role_panel_embeds_and_view(ctx.guild, panel_data, message_id)
            await msg.edit(embeds=embeds, view=view)

            await ctx.send(
                embed=self._create_embed(description="✅ Panel berhasil diperbarui.", color=self.color_success),
                ephemeral=True
            )
        except discord.NotFound:
            await ctx.send(embed=self._create_embed(description="❌ Pesan panel tidak ditemukan.", color=self.color_error), ephemeral=True)
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ Gagal mengedit panel: `{e}`", color=self.color_error), ephemeral=True)

    @commands.command(name="setmainmembershiprole", aliases=["smr"])
    @commands.has_permissions(manage_guild=True)
    async def set_main_membership_role(self, ctx: commands.Context, role: discord.Role):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        guild_settings["main_membership_role_id"] = role.id
        self.save_settings()
        
        await ctx.send(embed=self._create_embed(description=f"✅ Role **Pengecekan Utama Membership** berhasil diatur ke {role.mention}. Semua pengecekan akan berpatokan pada role ini.", color=self.color_success))
        await self.log_action(ctx.guild, "🔑 Role Utama Membership Diatur", {"Role": role.mention, "Moderator": ctx.author.mention}, self.color_info)

    @commands.command(name="addmembershiprole", aliases=["amr"])
    @commands.has_permissions(manage_roles=True)
    async def add_membership_role(self, ctx: commands.Context, role: discord.Role, *, tier_name: str):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        role_id_str = str(role.id)
        main_role_id = guild_settings.get("main_membership_role_id")

        if not main_role_id:
            await ctx.send(embed=self._create_embed(description="❌ Role Pengecekan Utama belum diatur! Harap atur dengan `!setmainmembershiprole <@role>` terlebih dahulu.", color=self.color_error))
            return
            
        if role.id == main_role_id:
            await ctx.send(embed=self._create_embed(description="❌ Role Tier tidak boleh sama dengan Role Pengecekan Utama.", color=self.color_error))
            return

        if role_id_str in guild_settings["membership_roles"]:
            await ctx.send(embed=self._create_embed(description=f"❌ Role {role.mention} sudah terdaftar sebagai tier **{guild_settings['membership_roles'][role_id_str]['tier_name']}**.", color=self.color_error))
            return

        guild_settings["membership_roles"][role_id_str] = {
            "tier_name": tier_name.strip(),
            "emoji": "🌟" 
        }
        self.save_settings()

        await ctx.send(embed=self._create_embed(description=f"✅ Role Tier **{role.mention}** berhasil ditambahkan untuk identifikasi tier: **{tier_name.strip()}**.", color=self.color_success))
        await self.log_action(ctx.guild, "➕ Membership Tier Ditambahkan", {"Role": role.mention, "Tier Name": tier_name.strip(), "Moderator": ctx.author.mention}, self.color_info)
        
    @commands.command(name="removemembershiprole", aliases=["rmr"])
    @commands.has_permissions(manage_roles=True)
    async def remove_membership_role(self, ctx: commands.Context, role: discord.Role):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        role_id_str = str(role.id)

        if role_id_str not in guild_settings["membership_roles"]:
            await ctx.send(embed=self._create_embed(description=f"❌ Role {role.mention} tidak terdaftar sebagai role tier membership YouTube.", color=self.color_error))
            return

        tier_name = guild_settings["membership_roles"].pop(role_id_str)["tier_name"]
        self.save_settings()

        await ctx.send(embed=self._create_embed(description=f"✅ Role Tier **{role.mention}** (Tier: **{tier_name}**) berhasil dihapus dari daftar identifikasi tier.", color=self.color_success))
        await self.log_action(ctx.guild, "➖ Membership Tier Dihapus", {"Role": role.mention, "Tier Name": tier_name, "Moderator": ctx.author.mention}, self.color_info)

    @commands.command(name="setmembershipmessage", aliases=["smm"])
    @commands.has_permissions(manage_guild=True)
    async def set_membership_message(self, ctx: commands.Context, type: Literal['invite', 'confirm', 'button_label'], *, message_content: str):
        guild_settings = self.get_guild_settings(ctx.guild.id)

        if type == 'invite':
            key = "membership_invite_message"
            guild_settings[key] = message_content
            self.save_settings()
            await ctx.send(embed=self._create_embed(description=f"✅ Pesan **ajakan membership** berhasil diatur.", color=self.color_success))
        elif type == 'confirm':
            key = "membership_confirm_message"
            guild_settings[key] = message_content
            self.save_settings()
            await ctx.send(embed=self._create_embed(description=f"✅ Pesan **konfirmasi membership** berhasil diatur. Gunakan `{{tier_name}}` untuk nama tier.", color=self.color_success))
        elif type == 'button_label':
            key = "verification_button_label"
            guild_settings[key] = message_content
            self.save_settings()
            await ctx.send(embed=self._create_embed(description=f"✅ Label tombol verifikasi berhasil diatur ke **'{message_content}'**.", color=self.color_success))
        else:
            await ctx.send(embed=self._create_embed(description="❌ Tipe pesan/label tidak valid. Gunakan `invite`, `confirm`, atau `button_label`.", color=self.color_error))
            return

        await self.log_action(ctx.guild, f"💬 Pesan Membership {type.capitalize()} Diatur", {"Moderator": ctx.author.mention, "Content": message_content}, self.color_info)

    @commands.command(name="sendverificationbutton", aliases=["svb"])
    @commands.has_permissions(manage_guild=True)
    async def send_verification_button(self, ctx: commands.Context, *, button_label: Optional[str] = None):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        
        final_label = button_label or guild_settings.get("verification_button_label", "Verifikasi Membership")

        main_role_id = guild_settings.get("main_membership_role_id")
        main_role = ctx.guild.get_role(main_role_id) if main_role_id else None

        if not main_role:
            await ctx.send(embed=self._create_embed(description="❌ **Role Pengecekan Utama** belum diatur. Harap atur dengan `!setmainmembershiprole <@role>` terlebih dahulu.", color=self.color_error))
            return

        tier_list = []
        for role_id_str, data in guild_settings.get("membership_roles", {}).items():
            role = ctx.guild.get_role(int(role_id_str))
            tier_info = role.mention if role else f'ID: `{role_id_str}`'
            tier_list.append(f"• **{data['tier_name']}** ({tier_info})") 

        list_tiers_str = '\n'.join(tier_list) if tier_list else '— Tidak ada Tier Membership spesifik yang didaftarkan. —'
        
        embed_desc = (
            f"Tekan tombol **{final_label}** di bawah untuk memverifikasi keanggotaan YouTube Anda. "
            f"Anda harus memiliki role **{main_role.mention}** untuk lolos verifikasi.\n\n"
            f"**Tier yang Dapat Diidentifikasi (untuk pesan konfirmasi):**\n"
            f"{list_tiers_str}"
        )

        embed = self._create_embed(
            title=" Verifikasi Status Membership",
            description=embed_desc,
            color=self.color_announce
        )

        view = UniversalMembershipView(self, final_label)
        await ctx.send(embed=embed, view=view)


    async def on_member_remove(self, member: discord.Member):
        if not member.guild:
            return
        
        try:
            dm_title = f"👋 Sampai Jumpa, {member.display_name}!"
            dm_message = (
                f"Kami dari **{member.guild.name}** sangat menyayangkan kepergian Anda. "
                f"Terima kasih banyak atas waktu dan kontribusi Anda selama berada di komunitas kami. "
                f"Semoga kita bisa bertemu lagi di masa depan! "
                f"\n\nJika ada masalah yang membuat Anda keluar, kami mohon maaf dan berharap Anda baik-baik saja."
            )
            
            dm_embed = self._create_embed(
                title=dm_title,
                description=dm_message,
                color=self.color_info 
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass
        except Exception:
            pass

        guild_settings = self.get_guild_settings(member.guild.id)
        welcome_channel_id = guild_settings.get("welcome_channel_id")
        channel = member.guild.get_channel(welcome_channel_id) if welcome_channel_id else None

        if channel and isinstance(channel, discord.TextChannel): 
            
            goodbye_message_content = guild_settings.get("goodbye_message", "Selamat tinggal, **{user}**. Sampai jumpa lagi! 👋")
            
            embed = discord.Embed(
                title="💔 Kehilangan Seorang Anggota",
                description=goodbye_message_content.format(user=member.display_name, guild_name=member.guild.name),
                color=self.color_warning,
                timestamp=discord.utils.utcnow()
            )
            embed.set_author(name=member.guild.name, icon_url=member.guild.icon.url if member.guild.icon else None)
            file = None
            welcome_banner_url = guild_settings.get("welcome_banner_url")
            if welcome_banner_url:
                embed.set_image(url=welcome_banner_url)
            else:
                try:
                    card_buffer = await self._create_goodbye_card(member, "SELAMAT TINGGAL!")
                    file = discord.File(fp=card_buffer, filename="goodbye.png")
                    embed.set_image(url="attachment://goodbye.png")
                except Exception:
                    pass

            embed.set_footer(text=f"Anggota tersisa {member.guild.member_count}.")
            
            try:
                if file:
                    await channel.send(embed=embed, file=file)
                else:
                    await channel.send(embed=embed)
            except discord.Forbidden:
                pass
            except Exception:
                pass

        guild_id_str = str(member.guild.id)
        member_id_str = str(member.id)
        
        warnings_cleared = False
        if guild_id_str in self.warnings and member_id_str in self.warnings[guild_id_str]:
            del self.warnings[guild_id_str][member_id_str]
            self.save_warnings()
            warnings_cleared = True

        log_fields = {
            "Member": f"{member} ({member.id})",
            "Nama Tampilan": member.display_name,
            "Total Anggota": member.guild.member_count
        }
        if warnings_cleared:
            log_fields["Data Hapus"] = "Warning History Dihapus"
            
        await self.log_action(
            member.guild,
            "🏃 Member Left Server",
            log_fields,
            self.color_warning
        )

        await self.update_panel(member.guild)
    
    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            embed = self._create_embed(description=f"❌ Anda tidak memiliki izin `{', '.join(error.missing_permissions)}` untuk menjalankan perintah ini.", color=self.color_error)
            await ctx.send(embed=embed, delete_after=15)
        elif isinstance(error, commands.CommandNotFound):
            pass
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=self._create_embed(description=f"❌ Anggota tidak ditemukan.", color=self.color_error))
        elif isinstance(error, commands.UserNotFound):
            await ctx.send(embed=self._create_embed(description=f"❌ Pengguna tidak ditemukan.", color=self.color_error))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=self._create_embed(description=f"❌ Argument tidak valid: {error}", color=self.color_error), delete_after=15)
        else:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_settings = self.get_guild_settings(member.guild.id)
        
        if (welcome_channel_id := guild_settings.get("welcome_channel_id")) and (channel := member.guild.get_channel(welcome_channel_id)):
            welcome_message_content = guild_settings.get("welcome_message", "Selamat datang di **{guild_name}**, {user}! 🎉")
            welcome_embed_title = guild_settings.get("welcome_embed_title", "SELAMAT DATANG!")
            welcome_sender_name = guild_settings.get("welcome_sender_name", "Admin Server")
            welcome_banner_url = guild_settings.get("welcome_banner_url")

            embed = discord.Embed(
                description=welcome_message_content.format(user=member.mention, guild_name=member.guild.name), 
                color=self.color_welcome,
                timestamp=discord.utils.utcnow()
            )
            
            embed.set_author(name=welcome_sender_name, icon_url=member.guild.icon.url if member.guild.icon else None)
            embed.title = welcome_embed_title 
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"Kamu adalah anggota ke-{member.guild.member_count}!")

            file = None
            if welcome_banner_url:
                embed.set_image(url=welcome_banner_url)
            else:
                try:
                    card_buffer = await self._create_welcome_card(member, welcome_embed_title)
                    file = discord.File(fp=card_buffer, filename="welcome.png")
                    embed.set_image(url="attachment://welcome.png")
                except Exception:
                    pass
            
            try:
                if file:
                    await channel.send(f"Halo, {member.mention}! Selamat datang!", embed=embed, file=file)
                else:
                    await channel.send(f"Halo, {member.mention}! Selamat datang!", embed=embed)
            except discord.Forbidden:
                pass
            except Exception as e:
                pass
    
        if (auto_role_id := guild_settings.get("auto_role_id")) and (role := member.guild.get_role(auto_role_id)):
            try:
                await member.add_roles(role, reason="Auto Role")
            except discord.Forbidden:
                pass
    
        await self.update_panel(member.guild)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
            
        if message.author.bot or message.author.id == self.bot.user.id:
            rules = self.get_channel_rules(message.guild.id, message.channel.id)
            if (delay := rules.get("auto_delete_seconds", 0)) > 0:
                try:
                    await message.delete(delay=delay)
                except Exception:
                    pass
            if rules.get("disallow_bots"):
                try:
                    await message.delete()
                except Exception:
                    pass
            return

        guild_settings = self.get_guild_settings(message.guild.id)
        whitelist_roles = guild_settings.get("spam_whitelist_roles", [])
        is_whitelisted = any(r.id in whitelist_roles for r in message.author.roles)
        user_id_str = str(message.author.id)
        is_command = message.content.startswith(tuple(await self.bot.get_prefix(message)))
        
        # Trigger Channel Trap (Honey-Pot)
        trigger_channels = guild_settings.get("trigger_channels", [])
        if message.channel.id in trigger_channels and not is_command:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
                
            is_immune = is_whitelisted or message.author.guild_permissions.administrator or message.author.guild_permissions.kick_members or str(message.author.id) == "1000737066822410311"
            if is_immune:
                return

            try:
                # Global Timeout (Lintas Server)
                timeout_duration = timedelta(days=27, hours=23, minutes=59)
                timeout_reason = "Terdeteksi mengirim pesan berisi spam atau phising (Sistem Anti-Spam)"
                
                for guild_obj in self.bot.guilds:
                    member_in_guild = guild_obj.get_member(message.author.id)
                    if member_in_guild and not member_in_guild.is_timed_out():
                        try:
                            await member_in_guild.timeout(timeout_duration, reason=timeout_reason)
                        except Exception:
                            pass
            except Exception as e:
                print(f"Global timeout failed: {e}")
                
            if user_id_str in self.cross_channel_spam_history:
                messages_to_delete = self.cross_channel_spam_history.pop(user_id_str, [])
                delete_tasks = []
                for entry in messages_to_delete:
                    try:
                        channel_to_purge = message.guild.get_channel(entry['channel_id'])
                        if channel_to_purge and channel_to_purge.permissions_for(message.guild.me).manage_messages:
                            delete_tasks.append(channel_to_purge.delete_messages([discord.Object(id=entry['message_id'])], reason="Trigger Channel Trap Activated"))
                    except Exception:
                        continue
                if delete_tasks:
                    try:
                        await asyncio.gather(*delete_tasks, return_exceptions=True)
                    except Exception:
                        pass
                        
            await self.send_spam_log_v2(message.guild, message.author, message.channel.mention, "Terdeteksi mengirim pesan berisi spam atau phising (Sistem Anti-Spam)", "Pengguna terdeteksi mengirim pesan berisi spam atau mengirim pesan di channel terlarang. Sistem telah menjatuhkan sanksi Timeout 28 Hari secara otomatis.", str(message.id))
            
            # Auto-update Trap Message Globally
            global_count = self.settings.get("global_trap_count", 30) + 1
            self.settings["global_trap_count"] = global_count
            self.save_settings()
            
            from cogs.v2_layout import build_v2_card, edit_v2_message, send_v2_message
            buttons = [
                {
                    "type": 2,
                    "style": 4, # Red
                    "label": f"Timeouts count: {global_count}",
                    "custom_id": "disabled_trap_counter",
                    "disabled": True,
                    "emoji": {"name": "🔨"}
                }
            ]
            card = build_v2_card(
                title="🚨 PERINGATAN KERAS / WARNING 🚨",
                description="**JANGAN MENGIRIM PESAN DI CHANNEL INI**\n**DO NOT SEND MESSAGES IN THIS CHANNEL**\n\nChannel ini khusus untuk mendeteksi spam & phishing. Setiap pesan yang Anda kirim di sini akan mengakibatkan sanksi **Timeout Otomatis 28 Hari**.\n\n*This channel is strictly for spam & phishing detection, any messages sent here will result in an immediate 28-day timeout.*\n\nMohon patuhi peraturan server yang ada untuk menghindari sanksi dari sistem otomatis kami.",
                color=None,
                buttons=buttons
            )
            
            # Recreate for current channel if needed
            current_trap_msg_id = guild_settings.get(f"trap_msg_{message.channel.id}")
            current_edited = False
            if current_trap_msg_id:
                try:
                    current_edited = await edit_v2_message(self.bot, message.channel.id, current_trap_msg_id, [card])
                except Exception:
                    pass
                
            if not current_edited:
                try:
                    await message.channel.purge(limit=10, check=lambda m: m.author == self.bot.user)
                    msg_data = await send_v2_message(self.bot, message.channel.id, [card])
                    if msg_data and "id" in msg_data:
                        guild_settings[f"trap_msg_{message.channel.id}"] = int(msg_data["id"])
                        self.save_settings()
                except Exception:
                    pass

            # Update other guilds globally
            for g_id, g_settings in self.settings.items():
                if not isinstance(g_settings, dict): continue
                trigger_channels_g = g_settings.get("trigger_channels", [])
                for ch_id in trigger_channels_g:
                    if str(ch_id) == str(message.channel.id):
                        continue # Already handled current channel
                    trap_msg_id = g_settings.get(f"trap_msg_{ch_id}")
                    if trap_msg_id:
                        try:
                            await edit_v2_message(self.bot, int(ch_id), trap_msg_id, [card])
                        except Exception:
                            pass
                            
            return

        current_time = time.time()
        message_content_lower = message.content.lower()
        


        if not message.author.guild_permissions.kick_members and not is_whitelisted and not is_command:
            
            if user_id_str not in self.cross_channel_spam_history:
                self.cross_channel_spam_history[user_id_str] = []
            
            self.cross_channel_spam_history[user_id_str].append({
                'channel_id': message.channel.id,
                'message_id': message.id,
                'timestamp': current_time,
                'content': message.content[:100]
            })
            
            self.cross_channel_spam_history[user_id_str] = [
                entry for entry in self.cross_channel_spam_history[user_id_str]
                if current_time - entry['timestamp'] <= 30
            ]
            
            global_bucket = self.global_spam_cooldown.get_bucket(message)
            global_retry_after = global_bucket.update_rate_limit()
            
            if global_retry_after:
                messages_to_delete = self.cross_channel_spam_history.pop(user_id_str, [])
                
                delete_tasks = []
                for entry in messages_to_delete:
                    try:
                        channel = message.guild.get_channel(entry['channel_id'])
                        if channel and channel.permissions_for(message.guild.me).manage_messages:
                            tasks.append(channel.delete_messages([discord.Object(id=entry['message_id'])], reason="Global Cross-Channel Spam Detected"))
                    except Exception:
                        continue
                
                if delete_tasks:
                    try:
                        await asyncio.gather(*delete_tasks, return_exceptions=True)
                    except discord.Forbidden:
                       await self.log_action(message.guild, "❌ PENGHAPUSAN SPAM LINTAS CHANNEL GAGAL", 
                           {"Member": message.author.mention, "Channel Pemicu": message.channel.mention, "Error": "Gagal menghapus beberapa pesan (Forbidden/Izin)."}, self.color_error)

                if not message.author.is_timed_out():
                    duration = timedelta(minutes=30)
                    reason = "Global Cross-Channel Spam Detection (Auto-Timeout 30m)"
                    
                    try:
                        await message.author.timeout(duration, reason=reason)
                        
                        spam_count = len(messages_to_delete)
                        channels_affected = len(set(entry['channel_id'] for entry in messages_to_delete))
                        
                        await message.channel.send(
                            embed=self._create_embed(
                                description=f"🚫 {message.author.mention} telah di-**TIMEOUT 30 MENIT** karena **Spam Massal Lintas Channel** ({spam_count} pesan di {channels_affected} channel).",
                                color=self.color_error
                            ),
                            delete_after=15
                        )
                        
                        await self.log_action(
                            message.guild, 
                            "🚫 Global Cross-Channel Spam Detected",
                            {
                                "Member": message.author.mention,
                                "Total Pesan": spam_count,
                                "Channel Terlibat": channels_affected,
                                "Aksi": "Timeout (30m) + Hapus Semua Pesan"
                            },
                            self.color_error
                        )
                        
                    except discord.Forbidden:
                        await self.send_spam_log_v2(message.guild, message.author, message.channel.mention, "Spam Massal (Gagal Timeout)", "Izin bot tidak cukup.", str(message.id))
                
                return
            
            self.spam_history.setdefault(user_id_str, []).append({
                'channel_id': message.channel.id, 
                'message_id': message.id, 
                'timestamp': current_time
            })

            bucket = self.fast_spam_cooldown.get_bucket(message)
            retry_after = bucket.update_rate_limit()

            if retry_after:
                
                messages_to_delete = self.spam_history.pop(user_id_str, [])
                
                tasks = []
                for entry in messages_to_delete:
                    try:
                        channel = message.guild.get_channel(entry['channel_id'])
                        if channel and channel.permissions_for(message.guild.me).manage_messages:
                            tasks.append(channel.delete_messages([discord.Object(id=entry['message_id'])], reason="Global Spam Detected"))
                    except Exception:
                        pass
                
                if tasks:
                    try:
                        await asyncio.gather(*tasks, return_exceptions=True)
                    except discord.Forbidden:
                       await self.send_spam_log_v2(message.guild, message.author, message.channel.mention, "Gagal Menghapus Pesan Spam", "Bot kekurangan izin Manage Messages.", str(message.id))


                if not message.author.is_timed_out():
                    duration = timedelta(minutes=10) 
                    reason = "Global Fast Spam: >5 messages in 10 seconds (Auto-Timeout 10m)."
                    try:
                        await message.author.timeout(duration, reason=reason)
                        try:
                            await message.author.send(embed=self._create_embed(description=f"⚠️ Anda telah di-timeout selama 10 Menit oleh sistem keamanan karena Spam Massal.\n\n*Anda dapat mengajukan banding atas aksi ini dengan mengirim DM ke admin/moderator server.*", color=self.color_error))
                        except: pass
                        await message.channel.send(
                            embed=self._create_embed(
                                description=f"🚫 {message.author.mention} telah di-**TIMEOUT** selama 10 menit karena **Spam Massal**.",
                                color=self.color_error
                            ),
                            delete_after=10
                        )
                        await self.send_spam_log_v2(message.guild, message.author, message.channel.mention, "Terdeteksi mengirim pesan berisi spam atau phising (Sistem Anti-Spam)", "Pengguna terdeteksi mengirim pesan teks berisi spam secara beruntun (Fast Spam). Sistem telah menjatuhkan sanksi Timeout 10 Menit secara otomatis.", str(message.id))
                    except discord.Forbidden:
                        await self.send_spam_log_v2(message.guild, message.author, message.channel.mention, "Terdeteksi mengirim pesan berisi spam atau phising (Sistem Anti-Spam)", "Pengguna terdeteksi mengirim pesan teks berisi spam secara beruntun (Fast Spam). Sistem gagal menjatuhkan sanksi karena kekurangan izin.", str(message.id))
                        
                return
            
            cooldown_duration = self.fast_spam_cooldown._cooldown.per 
            
            if user_id_str in self.spam_history:
                self.spam_history[user_id_str] = [
                    entry for entry in self.spam_history[user_id_str] 
                    if current_time - entry['timestamp'] <= cooldown_duration
                ]
                if not self.spam_history[user_id_str]:
                    del self.spam_history[user_id_str]
        
        if not message.author.guild_permissions.kick_members and not is_whitelisted:
            if self.detect_suspicious_links(message.content):
                try:
                    await message.delete()
                    
                    await message.channel.send(
                        embed=self._create_embed(
                            description=f"🛡️ {message.author.mention}, pesan Anda dihapus karena mengandung link mencurigakan yang berpotensi phising.",
                            color=self.color_warning
                        ),
                        delete_after=10
                    )
                    
                    if not message.author.is_timed_out():
                        try:
                            await message.author.timeout(
                                timedelta(hours=1), 
                                reason="Automatic timeout for suspicious/phishing links"
                            )
                            try:
                                await message.author.send(embed=self._create_embed(description=f"⚠️ Anda telah di-timeout selama 1 Jam oleh sistem keamanan karena mengirim link mencurigakan/phising.\n\n*Anda dapat mengajukan banding atas aksi ini dengan mengirim DM ke admin/moderator server.*", color=self.color_error))
                            except: pass
                        except discord.Forbidden:
                            pass
                    
                    await self.log_action(
                        message.guild,
                        "🛡️ Suspicious Link Detected & Blocked",
                        {
                            "Member": message.author.mention,
                            "Channel": message.channel.mention,
                            "Content Preview": message.content[:100] + "..." if len(message.content) > 100 else message.content,
                            "Action": "Message Deleted + Auto-Timeout"
                        },
                        self.color_warning
                    )
                    
                except discord.Forbidden:
                    pass
                
                return

        if message.attachments and not message.author.guild_permissions.kick_members and not is_whitelisted:
            total_size = sum(att.size for att in message.attachments)
            media_count = len(message.attachments)

            for attachment in message.attachments:
                if not self.is_allowed_file_type(attachment.filename):
                    try:
                        await message.delete()
                        await message.channel.send(
                            embed=self._create_embed(
                                description=f"🚫 {message.author.mention}, tipe file `{attachment.filename}` tidak diizinkan.",
                                color=self.color_error
                            ),
                            delete_after=10
                        )
                        return
                    except discord.Forbidden:
                        pass
                    return

            rapid_bucket = self.media_spam_rapid_cooldown.get_bucket(message)
            rapid_retry_after = rapid_bucket.update_rate_limit()

            if media_count >= 5:
                rapid_retry_after = 1.0
            
            if rapid_retry_after:
                try:
                    await message.delete()
                    if not message.author.is_timed_out():
                        await message.author.timeout(timeout_duration, reason="Rapid media spam (5+ media in 10 seconds or single message)")
                        try:
                            await message.author.send(embed=self._create_embed(description=f"⚠️ Anda telah di-timeout selama 15 Menit oleh sistem keamanan karena mengirim terlalu banyak media secara beruntun.\n\n*Anda dapat mengajukan banding atas aksi ini dengan mengirim DM ke admin/moderator server.*", color=self.color_error))
                        except: pass
                        await self.send_spam_log_v2(message.guild, message.author, message.channel.mention, "Terdeteksi mengirim pesan berisi spam atau phising (Sistem Anti-Spam)", "Pengguna terdeteksi mengirim pesan gambar berisi spam secara beruntun. Sistem telah menjatuhkan sanksi Timeout 15 Menit secara otomatis.", str(message.id))
                        
                        await message.channel.send(
                            embed=self._create_embed(
                                description=f"🚫 {message.author.mention} di-**TIMEOUT 15 MENIT** karena spam media terlalu cepat.",
                                color=self.color_error
                            ),
                            delete_after=10
                        )
                    return
                except discord.Forbidden:
                    pass

            basic_bucket = self.media_spam_cooldown.get_bucket(message)
            basic_retry_after = basic_bucket.update_rate_limit()

            if media_count >= 3:
                basic_retry_after = 1.0 # Force trigger jika 3+ media dalam satu pesan
            
            if basic_retry_after:
                try:
                    await message.delete()
                    await message.channel.send(
                        embed=self._create_embed(
                            description=f"🖼️ {message.author.mention}, terlalu banyak mengirim media ({media_count} files) dalam waktu singkat. Maksimal 2 media dalam 30 detik.",
                            color=self.color_warning
                        ),
                        delete_after=10
                    )
                    await self.send_spam_log_v2(
                        message.guild,
                        message.author,
                        message.channel.mention,
                        "Terdeteksi mengirim pesan berisi spam atau phising (Sistem Anti-Spam)",
                        "Pengguna terdeteksi mengirim terlalu banyak pesan gambar/file. Sistem telah menjatuhkan sanksi Timeout secara otomatis.",
                        str(message.id)
                    )
                    return
                except discord.Forbidden:
                    pass

            heavy_bucket = self.media_spam_heavy_cooldown.get_bucket(message)
            heavy_retry_after = heavy_bucket.update_rate_limit()
            
            if heavy_retry_after:
                try:
                    await message.delete()
                    if not message.author.is_timed_out():
                        await message.author.timeout(timeout_duration, reason="Heavy media spam (8+ media in 60 seconds)")
                        try:
                            await message.author.send(embed=self._create_embed(description=f"⚠️ Anda telah di-timeout selama 30 Menit oleh sistem keamanan karena spam media berat.\n\n*Anda dapat mengajukan banding atas aksi ini dengan mengirim DM ke admin/moderator server.*", color=self.color_error))
                        except: pass
                        await self.send_spam_log_v2(message.guild, message.author, message.channel.mention, "Terdeteksi mengirim pesan berisi spam atau phising (Sistem Anti-Spam)", "Pengguna terdeteksi mengirim pesan gambar berisi spam secara massal (Heavy Spam). Sistem telah menjatuhkan sanksi Timeout 30 Menit secara otomatis.", str(message.id))
                        
                        await message.channel.send(
                            embed=self._create_embed(
                                description=f"🚫 {message.author.mention} di-**TIMEOUT 30 MENIT** karena spam media berat.",
                                color=self.color_error
                            ),
                            delete_after=10
                        )
                    return
                except discord.Forbidden:
                    pass

            if len(message.attachments) > 5 or total_size > 50 * 1024 * 1024:
                try:
                    await message.delete()
                    await message.channel.send(
                        embed=self._create_embed(
                            description=f"📁 {message.author.mention}, batas maksimal: 5 file atau total 50MB per pesan.",
                            color=self.color_warning
                        ),
                        delete_after=10
                    )
                    return
                except discord.Forbidden:
                    pass

        if is_command:
            return 
        
        rules = self.get_channel_rules(message.guild.id, message.channel.id)

        if (delay := rules.get("auto_delete_seconds", 0)) > 0:
            try:
                await message.delete(delay=delay)
            except discord.NotFound:
                pass

        if rules.get("disallow_bots") and message.author.bot:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            return

        if rules.get("disallow_media") and message.attachments:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            await message.channel.send(
                embed=self._create_embed(description=f"🖼️ {message.author.mention}, media/files are not allowed in this channel.", color=self.color_warning),
                delete_after=10
            )
            return

        if rules.get("disallow_url") and self.url_regex.search(message.content):
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            await message.channel.send(
                embed=self._create_embed(description=f"🔗 {message.author.mention}, links are not allowed in this channel.", color=self.color_warning),
                delete_after=10
            )
            return

        if rules.get("disallow_prefix") and message.content.startswith(self.common_prefixes):
            command_prefixes = await self.bot.get_prefix(message)
            if not isinstance(command_prefixes, list):
                command_prefixes = [command_prefixes]
            is_actual_command = any(
                message.content.startswith(prefix) and self.bot.get_command(message.content[len(prefix):].split(' ')[0])
                for prefix in command_prefixes
            )
            if not is_actual_command:
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                await message.channel.send(
                    embed=self._create_embed(description=f"❗ {message.author.mention}, bot commands are not allowed in this channel.", color=self.color_warning),
                    delete_after=10
                )
                return

        guild_filters = self.get_guild_filters(message.guild.id)
        for bad_word in guild_filters.get("bad_words", []):
            if bad_word.lower() in message_content_lower:
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                await message.channel.send(
                    embed=self._create_embed(description=f"🤬 Pesan dari {message.author.mention} dihapus karena mengandung kata kasar.", color=self.color_warning),
                    delete_after=10
                )
                return
        
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.member is None or payload.member.bot: return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        guild_settings = self.get_guild_settings(payload.guild_id)
        role_map = guild_settings.get("reaction_roles", {}).get(str(payload.message_id))
        
        if role_map and (role_id := role_map.get(str(payload.emoji))):
            if (role := guild.get_role(role_id)):
                try:
                    await payload.member.add_roles(role, reason="Reaction Role")
                except discord.Forbidden:
                    pass
                except Exception as e:
                    pass
            else:
                pass
        else:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None: return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild or not (member := guild.get_member(payload.user_id)) or member.bot: return

        guild_settings = self.get_guild_settings(payload.guild_id)
        role_map = guild_settings.get("reaction_roles", {}).get(str(payload.message_id))
        
        if role_map and (role_id := role_map.get(str(payload.emoji))):
            if (role := guild.get_role(role_id)):
                if role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Reaction Role Removed")
                    except discord.Forbidden:
                        pass
                    except Exception as e:
                        pass
                else:
                    pass
            else:
                pass
        else:
            pass



    @commands.hybrid_command(name="kick", description="Keluarkan member dari server")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.describe(member="Member yang ingin di-kick", reason="Alasan mengeluarkan member")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: Optional[str] = "No reason provided."):
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot kick a member with an equal or higher role.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat menendang anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return
        if member.id == ctx.guild.owner.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot kick the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot kick this bot itself.", color=self.color_error)); return

        try:
            await member.kick(reason=reason)
            await ctx.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has been kicked.", color=self.color_success))
            await self.log_action(ctx.guild, "👢 Member Kicked", {"Member": f"{member} ({member.id})", "Moderator": ctx.author.mention, "Reason": reason}, self.color_warning)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to kick this member. Ensure the bot's role is higher.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while kicking the member: {e}", color=self.color_error))

    @commands.hybrid_command(name="ban", description="Blokir member dari server")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(member="Member target", reason="Alasan pemblokiran")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: Optional[str] = "No reason provided."):
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner: await ctx.send(embed=self._create_embed(description="❌ You cannot ban a member with an equal or higher role.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat memblokir anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return
        if member.id == ctx.guild.owner.id: await ctx.send(embed=self._create_embed(description="❌ You cannot ban the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id: await ctx.send(embed=self._create_embed(description="❌ You cannot ban this bot itself.", color=self.color_error)); return

        try:
            await member.ban(reason=reason)
            await ctx.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has been banned.", color=self.color_success))
            await self.log_action(ctx.guild, "🔨 Member Banned", {"Member": f"{member} ({member.id})", "Moderator": ctx.author.mention, "Reason": reason}, self.color_error)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to ban this member. Ensure the bot's role is higher.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while banning the member: {e}", color=self.color_error))

    @commands.hybrid_command(name="softban", description="Ban member dan langsung unban untuk bersihkan pesan dalam 7 hari")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(member="Member target", reason="Alasan softban")
    @commands.has_permissions(ban_members=True)
    async def softban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided."):
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot softban a member with an equal or higher role.", color=self.color_error))
            return
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat memblokir anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return
        if member.id == ctx.guild.owner.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot softban the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot softban this bot itself.", color=self.color_error)); return

        try:
            dm_embed = self._create_embed(title=f"🚨 You Were Softbanned from {ctx.guild.name}", color=self.color_error)
            dm_embed.add_field(name="Reason", value=reason, inline=False)
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        try:
            await member.ban(reason=f"Softban: {reason}", delete_message_seconds=604800)
            await ctx.guild.unban(member, reason="Softban cleanup complete")

            await ctx.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has been softbanned (messages from the last 7 days cleared).", color=self.color_success))
            await self.log_action(ctx.guild, "🔨 Member Softbanned", {"Member": f"{member} ({member.id})", "Moderator": ctx.author.mention, "Reason": reason}, self.color_error)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to ban/unban this member.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred during softban: {e}", color=self.color_error))

    @commands.hybrid_command(name="unban", description="Cabut blokir member")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(user_identifier="ID atau Username target", reason="Alasan pencabutan")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, *, user_identifier: str, reason: Optional[str] = "No reason provided."):
        user_to_unban = None
        try:
            user_id = int(user_identifier)
            temp_user = await self.bot.fetch_user(user_id)
            user_to_unban = temp_user
        except ValueError:
            for entry in [entry async for entry in ctx.guild.bans()]:
                if str(entry.user).lower() == user_identifier.lower():
                    user_to_unban = entry.user
                    break
        except discord.NotFound:
            pass

        if user_to_unban is None:
            await ctx.send(embed=self._create_embed(description=f"❌ User `{user_identifier}` not found in ban list or invalid ID/Name#Tag.", color=self.color_error))
            return

        try:
            await ctx.guild.unban(user_to_unban, reason=reason)
            await ctx.send(embed=self._create_embed(description=f"✅ Ban for **{user_to_unban}** has been lifted.", color=self.color_success))
            await self.log_action(ctx.guild, "🤝 Ban Lifted", {"User": f"{user_to_unban} ({user_to_unban.id})", "Moderator": ctx.author.mention, "Reason": reason}, self.color_success)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to unban this member. Ensure the bot's role is higher.", color=self.color_error))
        except discord.NotFound:
            await ctx.send(embed=self._create_embed(description=f"❌ User `{user_to_unban}` not found in ban list.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while unbanning: {e}", color=self.color_error))

    @commands.hybrid_command(name="warn", description="Beri peringatan tercatat pada member")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.describe(member="Member target", reason="Alasan peringatan")
    @commands.has_permissions(kick_members=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str):
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

        try:
            dm_embed = self._create_embed(title=f"🚨 You Received a Warning in {ctx.guild.name}", color=self.color_warning)
            dm_embed.add_field(name="Warning Reason", value=reason, inline=False)
            dm_embed.set_footer(text=f"Warning issued by {ctx.author.display_name}")
            await member.send(embed=dm_embed)
            dm_sent = True
        except discord.Forbidden:
            dm_sent = False

        confirm_desc = f"✅ **{member.display_name}** has been warned."
        if not dm_sent:
            confirm_desc += "\n*(Warning message could not be sent to user's DMs.)*"
            
        await ctx.send(embed=self._create_embed(description=confirm_desc, color=self.color_success))
        await self.log_action(ctx.guild, "⚠️ Member Warned", {"Member": f"{member} ({member.id})", "Moderator": ctx.author.mention, "Reason": reason}, self.color_warning)
        await self.check_and_escalate_warnings(ctx.guild, member, ctx.author)

    @commands.hybrid_command(name="unwarn", description="Hapus peringatan member")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.describe(member="Member target", warning_index="Nomor urut peringatan", reason="Alasan penghapusan")
    @commands.has_permissions(kick_members=True)
    async def unwarn(self, ctx: commands.Context, member: discord.Member, warning_index: int, *, reason: Optional[str] = "Admin error."):
        guild_id_str = str(ctx.guild.id)
        member_id_str = str(member.id)
        
        user_warnings = self.warnings.get(guild_id_str, {}).get(member_id_str, [])
        
        if not user_warnings:
            await ctx.send(embed=self._create_embed(description=f"❌ **{member.display_name}** has no warnings.", color=self.color_error))
            return

        if not (0 < warning_index <= len(user_warnings)):
            await ctx.send(embed=self._create_embed(description=f"❌ Invalid warning index. Use `!warnings {member.mention}` to see the warning list.", color=self.color_error))
            return
        
        removed_warning = self.warnings[guild_id_str][member_id_str].pop(warning_index - 1)
        self.save_warnings()
        
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
        guild_id_str = str(ctx.guild.id)
        member_id_str = str(member.id)
        
        user_warnings = self.warnings.get(guild_id_str, {}).get(member_id_str, [])
        
        if not user_warnings:
            await ctx.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has no warning history.", color=self.color_success))
            return

        embed = self._create_embed(title=f"Warning History for {member.display_name}", color=self.color_info)
        embed.set_thumbnail(url=member.display_avatar.url)

        for idx, warn_data in enumerate(user_warnings, 1):
            moderator = await self.bot.fetch_user(warn_data.get('moderator_id', 0))
            timestamp = warn_data.get('timestamp', 0)
            reason = warn_data.get('reason', 'N/A')
            field_value = f"**Reason:** {reason}\n**Moderator:** {moderator.mention if moderator else 'Unknown'}\n**Date:** <t:{timestamp}:F>"
            embed.add_field(name=f"Warning #{idx}", value=field_value, inline=False)
            
        await ctx.send(embed=embed)

    @commands.command(name="setgoodbye", aliases=["sbm"])
    @commands.has_permissions(manage_guild=True)
    async def set_goodbye_message(self, ctx, *, message_content: str):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        
        if len(message_content) > 4000:
            return await ctx.send(embed=self._create_embed(description="❌ Isi pesan terlalu panjang (maksimal 4000 karakter).", color=self.color_error))
        
        guild_settings["goodbye_message"] = message_content
        self.save_settings()
        
        embed = self._create_embed(
            description=f"✅ Pesan selamat tinggal berhasil diatur:\n```{message_content}```",
            color=self.color_success
        )
        await ctx.send(embed=embed)
        await self.log_action(ctx.guild, "💬 Pesan Selamat Tinggal Diatur", {"Moderator": ctx.author.mention, "Isi Pesan": message_content}, self.color_info)

    @commands.hybrid_command(name="timeout", aliases=["mute"], description="Bungkam member sementara")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(member="Member target", duration="Durasi (misal: 10m, 1h)", reason="Alasan timeout")
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx: commands.Context, member: discord.Member, duration: str, *, reason: Optional[str] = "No reason provided."):
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot timeout a member with an equal or higher role.", color=self.color_error)); return
        if member.id == ctx.guild.owner.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot timeout the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot timeout this bot itself.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat memberi timeout anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return

        delta = parse_duration(duration)
        if not delta: await ctx.send(embed=self._create_embed(description="❌ Invalid duration format. Use `s` (seconds), `m` (minutes), `h` (hours), `d` (days). Example: `10m`.", color=self.color_error)); return
        if delta.total_seconds() > 2419200:
            await ctx.send(embed=self._create_embed(description="❌ Timeout duration cannot exceed 28 days.", color=self.color_error)); return

        try:
            await member.timeout(delta, reason=reason)
            await ctx.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has been timed out for `{duration}`.", color=self.color_success))
            await self.log_action(ctx.guild, "🤫 Member Timeout", {"Member": f"{member} ({member.id})", "Duration": duration, "Moderator": ctx.author.mention, "Reason": reason}, self.color_warning)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to timeout this member. Ensure the bot's role is higher.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while timing out: {e}", color=self.color_error))

    @commands.hybrid_command(name="removetimeout", aliases=["unmute"], description="Cabut status bungkam member")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(member="Member target")
    @commands.has_permissions(moderate_members=True)
    async def remove_timeout(self, ctx: commands.Context, member: discord.Member):
        if member.id == ctx.guild.owner.id: await ctx.send(embed=self._create_embed(description="❌ You cannot remove timeout for the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id: await ctx.send(embed=self._create_embed(description="❌ You cannot remove timeout for this bot itself.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat menghapus timeout anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return

        if not member.is_timed_out():
            await ctx.send(embed=self._create_embed(description=f"❌ {member.display_name} is not currently timed out.", color=self.color_error))
            return

        try:
            await member.timeout(None, reason=f"Timeout removed by {ctx.author}")
            await ctx.send(embed=self._create_embed(description=f"✅ Timeout for **{member.display_name}** has been removed.", color=self.color_success))
            await self.log_action(ctx.guild, "😊 Timeout Removed", {"Member": f"{member} ({member.id})", "Moderator": ctx.author.mention}, self.color_success)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to remove timeout for this member. Ensure the bot's role is higher.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while removing timeout: {e}", color=self.color_error))

    @commands.hybrid_command(name="disconnect", aliases=["voicedisconnect", "vkick"], description="Keluarkan member dari Voice Channel")
    @app_commands.describe(member="Member yang ingin dikeluarkan dari Voice Channel", reason="Alasan disconnect")
    async def voice_disconnect(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Tidak ada alasan."):
        if member.id == ctx.guild.owner.id: await ctx.send(embed=self._create_embed(description="❌ Anda tidak bisa mengeluarkan pemilik server.", color=self.color_error)); return
        if member.id == self.bot.user.id: await ctx.send(embed=self._create_embed(description="❌ Anda tidak bisa mengeluarkan bot ini.", color=self.color_error)); return
        if member.guild_permissions.administrator: await ctx.send(embed=self._create_embed(description="❌ Anda tidak bisa mengeluarkan Administrator.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat mengeluarkan anggota ini karena peran mereka lebih tinggi dari peran bot.", color=self.color_error)); return

        if not member.voice or not member.voice.channel:
            await ctx.send(embed=self._create_embed(description=f"❌ {member.display_name} sedang tidak berada di dalam Voice Channel mana pun.", color=self.color_error))
            return

        vc_name = member.voice.channel.name
        try:
            await member.move_to(None, reason=f"Disconnected by {ctx.author}: {reason}")
            
            if not ctx.author.guild_permissions.administrator:
                try:
                    dm_embed = discord.Embed(title=f"⚠️ Disconnected dari Voice Channel - {ctx.guild.name}", description=f"Anda telah dikeluarkan dari Voice Channel **{vc_name}** atas permintaan dari **{ctx.author.display_name}**.\n\n**Alasan:** {reason}\n\n*Anda dapat mengajukan banding atas aksi ini dengan mengirim DM ke admin/moderator server.*", color=0xFF0000)
                    await member.send(embed=dm_embed)
                except: pass

            await ctx.send(embed=self._create_embed(description=f"✅ **{member.display_name}** telah dikeluarkan dari Voice Channel **{vc_name}** oleh **{ctx.author.display_name}**.\n**Alasan:** {reason}", color=self.color_success))
            await self.log_action(ctx.guild, "📞 Voice Disconnect", {"Member": f"{member} ({member.id})", "Channel": vc_name, "Requester": ctx.author.mention, "Reason": reason}, self.color_warning)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak memiliki izin (Move Members) untuk mengeluarkan member ini dari Voice Channel.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ Terjadi kesalahan: {e}", color=self.color_error))
        
    @commands.hybrid_command(name="clear", aliases=["purge"], description="Hapus pesan massal")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(amount="Jumlah pesan yang akan dihapus (1-100)")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx: commands.Context, amount: int):
        if amount <= 0: await ctx.send(embed=self._create_embed(description="❌ Amount must be greater than 0.", color=self.color_error)); return
        if amount > 100: await ctx.send(embed=self._create_embed(description="❌ You can only delete a maximum of 100 messages at once.", color=self.color_error)); return

        await ctx.defer(ephemeral=True)
        try:
            limit = amount if ctx.interaction else amount + 1
            deleted = await ctx.channel.purge(limit=limit)
            embed = self._create_embed(description=f"🗑️ Successfully deleted **{len(deleted) if ctx.interaction else len(deleted) - 1}** messages.", color=self.color_success)
            await ctx.send(embed=embed, delete_after=5 if not ctx.interaction else None)
            
            actual_deleted = len(deleted) if ctx.interaction else len(deleted) - 1
            if actual_deleted > 0:
                await self.log_action(ctx.guild, "🗑️ Messages Deleted", {"Channel": ctx.channel.mention, "Amount": f"{actual_deleted} messages", "Moderator": ctx.author.mention}, self.color_info)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have `Manage Messages` permission to delete messages.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while deleting messages: {e}", color=self.color_error))
        
    @commands.hybrid_command(name="slowmode", description="Atur batas waktu kirim pesan channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.describe(seconds="Waktu jeda dalam detik (0 untuk mematikan)")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx: commands.Context, seconds: int):
        if seconds < 0: await ctx.send(embed=self._create_embed(description="❌ Slowmode duration cannot be negative.", color=self.color_error)); return
        if seconds > 21600: await ctx.send(embed=self._create_embed(description="❌ Slowmode duration cannot exceed 6 hours (21600 seconds).", color=self.color_error)); return

        try:
            await ctx.channel.edit(slowmode_delay=seconds)
            status = f"set to `{seconds}` seconds" if seconds > 0 else "disabled"
            await ctx.send(embed=self._create_embed(description=f"✅ Slowmode in this channel has been {status}.", color=self.color_success))
            await self.log_action(ctx.guild, "⏳ Slowmode Changed", {"Channel": ctx.channel.mention, "Duration": f"{seconds} seconds", "Moderator": ctx.author.mention}, self.color_info)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have `Manage Channels` permission to set slowmode.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while setting slowmode: {e}", color=self.color_error))

    @commands.hybrid_command(name="lock", description="Kunci channel dari member biasa")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.describe(channel="Channel target (opsional)")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        target_channel = channel or ctx.channel
        current_perms = target_channel.permissions_for(ctx.guild.default_role)
        if not current_perms.send_messages is False:
            try:
                await target_channel.set_permissions(ctx.guild.default_role, send_messages=False)
                await ctx.send(embed=self._create_embed(description=f"🔒 Channel {target_channel.mention} has been locked.", color=self.color_success))
                await self.log_action(ctx.guild, "🔒 Channel Locked", {"Channel": target_channel.mention, "Moderator": ctx.author.mention}, self.color_warning)
            except discord.Forbidden:
                await ctx.send(embed=self._create_embed(description="❌ Bot does not have `Manage Channels` permission to lock the channel.", color=self.color_error))
            except Exception as e:
                await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while locking the channel: {e}", color=self.color_error))
        else:
            await ctx.send(embed=self._create_embed(description=f"❌ Channel {target_channel.mention} is already locked.", color=self.color_error))

    @commands.hybrid_command(name="unlock", description="Buka kembali kunci channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.describe(channel="Channel target (opsional)")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        target_channel = channel or ctx.channel
        current_perms = target_channel.permissions_for(ctx.guild.default_role)
        if not current_perms.send_messages is True:
            try:
                await target_channel.set_permissions(ctx.guild.default_role, send_messages=None)
                await ctx.send(embed=self._create_embed(description=f"🔓 Channel {target_channel.mention} has been unlocked.", color=self.color_success))
                await self.log_action(ctx.guild, "🔓 Channel Unlocked", {"Channel": target_channel.mention, "Moderator": ctx.author.mention}, self.color_success)
            except discord.Forbidden:
                await ctx.send(embed=self._create_embed(description="❌ Bot does not have `Manage Channels` permission to unlock the channel.", color=self.color_error))
            except Exception as e:
                await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while unlocking the channel: {e}", color=self.color_error))
        else:
            await ctx.send(embed=self._create_embed(description=f"❌ Channel {target_channel.mention} is already unlocked.", color=self.color_error))

    @commands.command(name="addrole")
    @commands.has_permissions(manage_roles=True)
    async def add_role(self, ctx, member: discord.Member, role: discord.Role):
        if ctx.author.top_role <= role:
            await ctx.send(embed=self._create_embed(description="❌ You cannot assign a role that is higher than or equal to your own role.", color=self.color_error))
            return
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot modify roles for a member with a higher or equal position.", color=self.color_error))
            return
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat menambahkan peran anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return
        if role in member.roles:
            await ctx.send(embed=self._create_embed(description=f"❌ {member.display_name} already has the role {role.mention}.", color=self.color_error))
            return
            
        try:
            await member.add_roles(role, reason=f"Assigned by {ctx.author}")
            await ctx.send(embed=self._create_embed(description=f"✅ Role {role.mention} has been given to {member.mention}.", color=self.color_success))
            await self.log_action(ctx.guild, "➕ Role Assigned", {"Member": member.mention, "Role": role.mention, "Moderator": ctx.author.mention}, self.color_info)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to assign this role. Ensure the bot's role is higher than the role to be assigned.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while assigning the role: {e}", color=self.color_error))

    @commands.command(name="removerole")
    @commands.has_permissions(manage_roles=True)
    async def remove_role(self, ctx, member: discord.Member, role: discord.Role):
        if ctx.author.top_role <= role:
            await ctx.send(embed=self._create_embed(description="❌ You cannot remove a role that is higher than or equal to your own role.", color=self.color_error))
            return
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot modify roles for a member with a higher or equal position.", color=self.color_error))
            return
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat menghapus peran anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return
        if role not in member.roles:
            await ctx.send(embed=self._create_embed(description=f"❌ {member.display_name} does not have the role {role.mention}.", color=self.color_error))
            return
            
        try:
            await member.remove_roles(role, reason=f"Removed by {ctx.author}")
            await ctx.send(embed=self._create_embed(description=f"✅ Role {role.mention} has been removed from {member.mention}.", color=self.color_success))
            await self.log_action(ctx.guild, "➖ Role Removed", {"Member": member.mention, "Role": role.mention, "Moderator": ctx.author.mention}, self.color_info)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to remove this role. Ensure the bot's role is higher than the role to be removed.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while removing the role: {e}", color=self.color_error))

    @commands.command(name="nick")
    @commands.has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, new_nickname: Optional[str] = None):
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send(embed=self._create_embed(description="❌ You cannot change the nickname of a member with an equal or higher role.", color=self.color_error))
            return
        if member.id == ctx.guild.owner.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot change the nickname of the server owner.", color=self.color_error)); return
        if member.id == self.bot.user.id:
            await ctx.send(embed=self._create_embed(description="❌ You cannot change the nickname of this bot itself.", color=self.color_error)); return
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(embed=self._create_embed(description="❌ Bot tidak dapat mengubah nickname anggota ini karena peran mereka sama atau lebih tinggi dari peran bot.", color=self.color_error)); return

        old_nickname = member.display_name
        try:
            await member.edit(nick=new_nickname, reason=f"Changed by {ctx.author}")
            if new_nickname:
                await ctx.send(embed=self._create_embed(description=f"✅ Nickname **{old_nickname}** has been changed to **{new_nickname}**.", color=self.color_success))
                await self.log_action(ctx.guild, "👤 Nickname Changed", {"Member": member.mention, "From": old_nickname, "To": new_nickname, "Moderator": ctx.author.mention}, self.color_info)
            else:
                await ctx.send(embed=self._create_embed(description=f"✅ Nickname for **{old_nickname}** has been reset.", color=self.color_success))
                await self.log_action(ctx.guild, "👤 Nickname Reset", {"Member": member.mention, "Moderator": ctx.author.mention}, self.color_info)
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to change this nickname. Ensure the bot's role is higher than this member.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred while changing nickname: {e}", color=self.color_error))

    @commands.command(name="channelrules", aliases=["cr"])
    @commands.has_permissions(manage_channels=True)
    async def channel_rules(self, ctx, channel: Optional[discord.TextChannel] = None):
        target_channel = channel or ctx.channel
        class ChannelRuleView(discord.ui.View):
            def __init__(self, cog_instance, author, target_channel):
                super().__init__(timeout=300)
                self.cog, self.author, self.target_channel = cog_instance, author, target_channel
                self.guild_id, self.channel_id = target_channel.guild.id, target_channel.id
                self.message = None
                self.update_buttons()

            def update_buttons(self):
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

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                if interaction.user != self.author:
                    await interaction.response.send_message("Hanya pengguna yang memulai perintah yang dapat berinteraksi.", ephemeral=True)
                    return False
                if not interaction.user.guild_permissions.manage_channels:
                    await interaction.response.send_message("Anda tidak memiliki izin `Manage Channels` untuk mengubah aturan ini.", ephemeral=True)
                    return False
                return True

            async def toggle_rule(self, interaction: discord.Interaction, rule_name: str):
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

            async def set_auto_delete(self, interaction: discord.Interaction):
                class AutoDeleteModal(discord.ui.Modal, title="Set Auto-Delete"):
                    def __init__(self, current_delay, parent_view_instance):
                        super().__init__()
                        self.cog = parent_view_instance.cog
                        self.guild_id = parent_view_instance.guild_id
                        self.channel_id = parent_view_instance.channel_id
                        self.parent_view = parent_view_instance

                        self.delay_input = discord.ui.TextInput(
                            label="Duration (seconds, 0 to disable)",
                            placeholder="Example: 30 (max 3600)",
                            default=str(current_delay),
                            max_length=4
                        )
                        self.add_item(self.delay_input)

                    async def on_submit(self, modal_interaction: discord.Interaction):
                        await modal_interaction.response.defer(ephemeral=True)
                        try:
                            delay = int(self.delay_input.value)
                            if not (0 <= delay <= 3600):
                                await modal_interaction.followup.send(embed=self.cog._create_embed(description="❌ Duration must be between 0 and 3600 seconds (1 hour).", color=self.cog.color_error), ephemeral=True)
                                return
                            
                            rules = self.cog.get_channel_rules(self.guild_id, self.channel_id)
                            rules["auto_delete_seconds"] = delay
                            self.cog.save_settings()
                            
                            self.parent_view.update_buttons()
                            await modal_interaction.message.edit(view=self.parent_view)
                            
                            await self.cog.log_action(
                                self.parent_view.target_channel.guild,
                                "⏳ Auto-Delete Changed",
                                {"Channel": self.parent_view.target_channel.mention, "Duration": f"{delay} seconds" if delay > 0 else "Disabled", "Moderator": modal_interaction.user.mention},
                                self.cog.color_info
                            )
                        except ValueError:
                            await modal_interaction.followup.send(embed=self.cog._create_embed(description="❌ Duration must be a number.", color=self.cog.color_error), ephemeral=True)
                        except Exception as e:
                            await modal_interaction.followup.send(embed=self.cog._create_embed(description=f"❌ An error occurred: {e}", color=self.cog.color_error), ephemeral=True)
                
                rules = self.cog.get_channel_rules(self.guild_id, self.channel_id)
                current_delay = rules.get("auto_delete_seconds", 0)
                await interaction.response.send_modal(AutoDeleteModal(current_delay, self))

        embed = self._create_embed(title=f"🔧 Rules for Channel: #{target_channel.name}", description="Press buttons to enable (green) or disable (red) rules for this channel. Press the auto-delete button to set its duration (default 30s).", color=self.color_info)
        view_instance = ChannelRuleView(self, ctx.author, target_channel)
        view_instance.message = await ctx.send(embed=embed, view=view_instance)

    @commands.hybrid_command(name="setwelcomechannel", description="Atur channel untuk ucapan selamat datang")
    @app_commands.describe(channel="Channel text untuk welcome message")
    @commands.has_permissions(manage_guild=True)
    async def set_welcome_channel(self, ctx, channel: discord.TextChannel):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        guild_settings["welcome_channel_id"] = channel.id
        self.save_settings()
        embed = self._create_embed(
            description=f"✅ Welcome channel successfully set to {channel.mention}.",
            color=self.color_success
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="setspamlog", description="Atur channel log khusus untuk sistem anti-spam & jebakan")
    @app_commands.describe(channel="Channel text untuk log anti-spam")
    @commands.has_permissions(manage_guild=True)
    async def set_spamlog_channel(self, ctx, channel: discord.TextChannel):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        guild_settings["spam_log_channel_id"] = channel.id
        self.save_settings()
        embed = self._create_embed(
            description=f"✅ Channel Log Anti-Spam berhasil diatur ke {channel.mention}.",
            color=self.color_success
        )
        await ctx.send(embed=embed)
        
    @commands.command(name="addwhitelistrole")
    @commands.has_permissions(manage_roles=True)
    async def add_whitelist_role(self, ctx, role_id: int):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        if "spam_whitelist_roles" not in guild_settings:
            guild_settings["spam_whitelist_roles"] = []
        if role_id in guild_settings["spam_whitelist_roles"]:
            await ctx.send(embed=self._create_embed(description="❌ Peran ini sudah ada di daftar whitelist.", color=self.color_error))
            return
        
        role = ctx.guild.get_role(role_id)
        if not role:
            await ctx.send(embed=self._create_embed(description="❌ ID peran tidak valid.", color=self.color_error))
            return
            
        guild_settings["spam_whitelist_roles"].append(role_id)
        self.save_settings()
        await ctx.send(embed=self._create_embed(description=f"✅ Peran {role.mention} telah ditambahkan ke whitelist spam.", color=self.color_success))

    @commands.command(name="removewhitelistrole")
    @commands.has_permissions(manage_roles=True)
    async def remove_whitelist_role(self, ctx, role_id: int):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        if "spam_whitelist_roles" not in guild_settings or role_id not in guild_settings["spam_whitelist_roles"]:
            await ctx.send(embed=self._create_embed(description="❌ Peran ini tidak ada di daftar whitelist.", color=self.color_error))
            return
            
        guild_settings["spam_whitelist_roles"].remove(role_id)
        self.save_settings()
        role = ctx.guild.get_role(role_id)
        role_mention = role.mention if role else str(role_id)
        await ctx.send(embed=self._create_embed(description=f"✅ Peran {role_mention} telah dihapus dari whitelist spam.", color=self.color_success))

    @commands.command(name="setreactionrole")
    @commands.has_permissions(manage_roles=True)
    async def set_reaction_role(self, ctx, message: discord.Message, emoji: str, role: discord.Role):
        if ctx.author.top_role <= role:
            return await ctx.send(embed=self._create_embed(description="❌ You cannot set a reaction role for a role higher than or equal to your own.", color=self.color_error))
        
        guild_settings = self.get_guild_settings(ctx.guild.id)
        message_id_str = str(message.id)
        if message_id_str not in guild_settings["reaction_roles"]: guild_settings["reaction_roles"][message_id_str] = {}
        guild_settings["reaction_roles"][message_id_str][emoji] = role.id
        self.save_settings()
        try:
            await message.add_reaction(emoji)
            await ctx.send(embed=self._create_embed(description=f"✅ Role **{role.mention}** will be given for {emoji} reaction on [that message]({message.jump_url}).", color=self.color_success))
        except discord.Forbidden:
            await ctx.send(embed=self._create_embed(description="❌ Bot does not have permission to add reactions or set roles. Ensure all permissions are complete.", color=self.color_error))
        except Exception as e:
            await ctx.send(embed=self._create_embed(description=f"❌ An error occurred: {e}", color=self.color_error))

    @commands.command(name="setup")
    @commands.has_permissions(manage_guild=True)
    async def setup(self, ctx):
        class SetupView(discord.ui.View):
            def __init__(self, cog_instance, author, ctx_instance):
                super().__init__(timeout=300)
                self.cog = cog_instance
                self.guild_id = ctx_instance.guild.id
                self.author = author
                self.ctx = ctx_instance
            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                if interaction.user != self.author:
                    await interaction.response.send_message("Hanya pengguna yang memulai setup yang dapat berinteraksi.", ephemeral=True)
                    return False
                if not interaction.user.guild_permissions.manage_guild:
                    await interaction.response.send_message("Anda tidak memiliki izin `Manage Server` untuk menggunakan setup ini.", ephemeral=True)
                    return False
                return True

            async def handle_response(self, interaction, prompt, callback):
                await interaction.response.send_message(embed=self.cog._create_embed(description=prompt, color=self.cog.color_info), ephemeral=True)
                try:
                    msg = await self.cog.bot.wait_for('message', check=lambda m: m.author == self.author and m.channel == interaction.channel, timeout=120)
                    await callback(msg, interaction)
                except asyncio.TimeoutError:
                    await interaction.followup.send(embed=self.cog._create_embed(description="❌ Waktu habis.", color=self.cog.color_error), ephemeral=True)
                except Exception as e:
                    await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Terjadi kesalahan: {e}", color=self.cog.color_error), ephemeral=True)

            @discord.ui.button(label="Auto Role", style=discord.ButtonStyle.primary, emoji="👤", row=0)
            async def set_auto_role(self, interaction: discord.Interaction, button: discord.ui.Button):
                async def callback(msg, inter):
                    role = msg.role_mentions[0] if msg.role_mentions else self.ctx.guild.get_role(int(msg.content)) if msg.content.isdigit() else None
                    if role:
                        self.cog.get_guild_settings(self.guild_id)['auto_role_id'] = role.id; self.cog.save_settings()
                        await inter.followup.send(embed=self.cog._create_embed(description=f"✅ Auto Role diatur ke **{role.mention}**.", color=self.cog.color_success), ephemeral=True)
                    else:
                        await inter.followup.send(embed=self.cog._create_embed(description="❌ Role tidak ditemukan.", color=self.cog.color_error), ephemeral=True)
                await self.handle_response(interaction, "Sebutkan (mention) atau masukkan ID role untuk pengguna baru:", callback)

            @discord.ui.button(label="Welcome Msg", style=discord.ButtonStyle.primary, emoji="💬", row=0)
            async def set_welcome_message(self, interaction: discord.Interaction, button: discord.ui.Button):
                current_settings = self.cog.get_guild_settings(self.guild_id)
                modal = WelcomeMessageModal(self.cog, self.guild_id, current_settings)
                await interaction.response.send_modal(modal)

            @discord.ui.button(label="Log Channel", style=discord.ButtonStyle.primary, emoji="📝", row=0)
            async def set_log_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
                async def callback(msg, inter):
                    channel = msg.channel_mentions[0] if msg.channel_mentions else self.ctx.guild.get_channel(int(msg.content)) if msg.content.isdigit() else None
                    if channel and isinstance(channel, discord.TextChannel):
                        self.cog.get_guild_settings(self.guild_id)['log_channel_id'] = channel.id; self.cog.save_settings()
                        await inter.followup.send(embed=self.cog._create_embed(description=f"✅ Log Channel diatur ke **{channel.mention}**.", color=self.cog.color_success), ephemeral=True)
                    else:
                        await inter.followup.send(embed=self.cog._create_embed(description="❌ Channel tidak ditemukan atau bukan channel teks.", color=self.cog.color_error), ephemeral=True)
                await self.handle_response(interaction, "Sebutkan (mention) atau masukkan ID channel untuk log aktivitas bot:", callback)
            
            @discord.ui.button(label="Kelola Filter", style=discord.ButtonStyle.secondary, emoji="🛡️", row=1)
            async def manage_filters(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_message(view=FilterManageView(self.cog, self.author), ephemeral=True)

            @discord.ui.button(label="Lihat Konfigurasi", style=discord.ButtonStyle.secondary, emoji="📋", row=2)
            async def view_config(self, interaction: discord.Interaction, button: discord.ui.Button):
                settings = self.cog.get_guild_settings(self.guild_id); filters = self.cog.get_guild_filters(self.guild_id)
                
                auto_role = self.ctx.guild.get_role(settings.get('auto_role_id')) if settings.get('auto_role_id') else "Tidak diatur"
                welcome_ch = self.ctx.guild.get_channel(settings.get('welcome_channel_id')) if settings.get('welcome_channel_id') else "Tidak diatur"
                log_ch = self.ctx.guild.get_channel(settings.get('log_channel_id')) if settings.get('log_channel_id') else "Tidak diatur"
                
                boost_ch = self.ctx.guild.get_channel(settings.get('boost_channel_id')) if settings.get('boost_channel_id') else "Tidak diatur"
                boost_image = f"[URL]({settings.get('boost_image_url')})" if settings.get('boost_image_url') else "Tidak diatur"
                
                welcome_banner = settings.get("welcome_banner_url")
                banner_url_display = f"[URL]({welcome_banner})" if welcome_banner else "Tidak diatur"

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
                        f"**URL Banner**: {banner_url_display}\n"
                        f"**Isi Pesan**: ```{settings.get('welcome_message')}```"
                    ), 
                    inline=False
                )

                membership_roles = settings.get('membership_roles', {})
                main_role = self.ctx.guild.get_role(settings.get('main_membership_role_id')) if settings.get('main_membership_role_id') else "Tidak diatur"
                membership_roles_display = "\n".join([
                    f" - **{data['tier_name']}**: <@&{role_id}>" 
                    for role_id, data in membership_roles.items()
                ]) or "Tidak Ada Role Tier Terdaftar"
                embed.add_field(
                    name="YouTube Membership Config",
                    value=(
                        f"**Role Cek Utama**: {main_role.mention if isinstance(main_role, discord.Role) else main_role}\n"
                        f"**Label Tombol**: `{settings.get('verification_button_label', 'N/A')}`\n"
                        f"**Pesan Ajakan**: ```{settings.get('membership_invite_message', 'N/A')[:50]}...```\n"
                        f"**Pesan Konfirmasi**: ```{settings.get('membership_confirm_message', 'N/A')[:50]}...```\n"
                        f"**Daftar Role Tier ({len(membership_roles)}):**\n{membership_roles_display}"
                    ),
                    inline=False
                )
                embed.add_field(name="Filter Kata Kasar", value=f"Total: {len(filters.get('bad_words',[]))} kata", inline=True)
                embed.add_field(name="Filter Link", value=f"Total: {len(filters.get('link_patterns',[]))} pola", inline=True)
                await interaction.response.send_message(embed=embed, ephemeral=True)

        class AddFilterModal(discord.ui.Modal, title="Tambah Filter"):
            def __init__(self, cog_instance, filter_type):
                super().__init__(); self.cog = cog_instance; self.filter_type = filter_type
                self.item_to_add = discord.ui.TextInput(label=f"Masukkan {('kata' if filter_type == 'bad_words' else 'pola regex')} untuk ditambahkan", style=discord.TextStyle.paragraph)
                self.add_item(self.item_to_add)
            async def on_submit(self, interaction: discord.Interaction):
                filters = self.cog.get_guild_filters(interaction.guild_id); item = self.item_to_add.value.lower().strip()
                if item in filters[self.filter_type]:
                    await interaction.response.send_message(embed=self.cog._create_embed(description=f"❌ `{item}` sudah ada di filter.", color=self.cog.color_error), ephemeral=True)
                else:
                    filters[self.filter_type].append(item); self.cog.save_filters()
                    await interaction.response.send_message(embed=self.cog._create_embed(description=f"✅ `{item}` berhasil ditambahkan ke filter.", color=self.cog.color_success), ephemeral=True)

        class RemoveFilterModal(discord.ui.Modal, title="Hapus Filter"):
            def __init__(self, cog_instance, filter_type):
                super().__init__(); self.cog = cog_instance; self.filter_type = filter_type
                self.item_to_remove = discord.ui.TextInput(label=f"Masukkan {('kata' if filter_type == 'bad_words' else 'pola')} yang akan dihapus")
                self.add_item(self.item_to_remove)
            async def on_submit(self, interaction: discord.Interaction):
                filters = self.cog.get_guild_filters(interaction.guild_id); item = self.item_to_remove.value.lower().strip()
                if item in filters[self.filter_type]:
                    filters[self.filter_type].remove(item); self.cog.save_filters()
                    await interaction.response.send_message(embed=self.cog._create_embed(description=f"✅ `{item}` berhasil dihapus dari filter.", color=self.cog.color_success), ephemeral=True)
                else:
                    await interaction.response.send_message(embed=self.cog._create_embed(description=f"❌ `{item}` tidak ditemukan di filter.", color=self.cog.color_error), ephemeral=True)

        class FilterManageView(discord.ui.View):
            def __init__(self, cog_instance, author):
                super().__init__(timeout=180); self.cog = cog_instance; self.author = author
            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                return interaction.user == self.author
            @discord.ui.button(label="Tambah Kata Kasar", style=discord.ButtonStyle.primary, emoji="🤬")
            async def add_bad_word(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_modal(AddFilterModal(self.cog, "bad_words"))
            @discord.ui.button(label="Hapus Kata Kasar", style=discord.ButtonStyle.danger, emoji="🗑️")
            async def remove_bad_word(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_modal(RemoveFilterModal(self.cog, "bad_words"))
            @discord.ui.button(label="Tambah Pola Link", style=discord.ButtonStyle.primary, emoji="🔗")
            async def add_link_pattern(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_modal(AddFilterModal(self.cog, "link_patterns"))
            @discord.ui.button(label="Hapus Pola Link", style=discord.ButtonStyle.danger, emoji="🔗")
            async def remove_link_pattern(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_modal(RemoveFilterModal(self.cog, "link_patterns"))
            @discord.ui.button(label="Lihat Semua Filter", style=discord.ButtonStyle.secondary, emoji="📋", row=2)
            async def view_filters(self, interaction: discord.Interaction, button: discord.ui.Button):
                filters = self.cog.get_guild_filters(interaction.guild_id); bad_words = ", ".join(f"`{w}`" for w in filters['bad_words']) or "Kosong"; link_patterns = ", ".join(f"`{p}`" for p in filters['link_patterns']) or "Kosong"
                embed = self.cog._create_embed(title="Daftar Filter Aktif", color=self.cog.color_info)
                embed.add_field(name="🚫 Kata Kasar", value=bad_words[:1024], inline=False); embed.add_field(name="🔗 Pola Link", value=link_patterns[:1024], inline=False)
                await interaction.response.send_message(embed=embed, ephemeral=True)

        embed = self._create_embed(title="⚙️ Panel Kontrol Server", description="Gunakan tombol di bawah ini untuk mengatur bot. Anda memiliki 5 menit sebelum panel ini nonaktif.", color=self.color_info, author_name=ctx.guild.name, author_icon_url=ctx.guild.icon.url if ctx.guild.icon else "")
        view_instance = SetupView(self, ctx.author, ctx)
        await ctx.send(embed=embed, view=view_instance)

    @commands.hybrid_command(name="announce", aliases=["pengumuman", "broadcast"], description="Kirim pengumuman V2 via modal")
    @app_commands.describe(channel_identifier="Tag channel, ID, atau nama channel")
    @commands.has_permissions(manage_guild=True)
    async def announce(self, ctx, channel_identifier: str):
        GITHUB_RAW_DESCRIPTION_URL = "https://raw.githubusercontent.com/Abogoboga04/OpenAI/main/announcement.txt"


        target_channel = None

        if channel_identifier.startswith('<#') and channel_identifier.endswith('>'):
            try:
                channel_id = int(channel_identifier[2:-1])
                target_channel = ctx.guild.get_channel(channel_id)
                if not target_channel:
                    target_channel = self.bot.get_channel(channel_id)
            except ValueError:
                pass
        
        if not target_channel and channel_identifier.isdigit():
            try:
                channel_id = int(channel_identifier)
                target_channel = ctx.guild.get_channel(channel_id)
                if not target_channel:
                    target_channel = self.bot.get_channel(channel_id)
            except ValueError:
                pass

        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            await ctx.send(embed=self._create_embed(
                description=f"❌ Channel '{channel_identifier}' tidak ditemukan atau bukan channel teks yang valid. Mohon gunakan mention channel (misal: `#general`) atau ID channel yang benar. Pastikan bot berada di server tersebut.",
                color=self.color_error
            ))
            return
        
        view_instance = AnnounceButtonView(self.bot, self, ctx, target_channel, GITHUB_RAW_DESCRIPTION_URL)
        initial_msg = await ctx.send(embed=self._create_embed(
            title="🔔 Siap Membuat Pengumuman?",
            description=f"Anda akan membuat pengumuman di channel {target_channel.mention}. **Pengumuman akan dikirim menggunakan format V2 Layout (Native)**. Tekan tombol di bawah untuk mengisi detail lainnya. Deskripsi pengumuman akan diambil otomatis dari file teks di GitHub (`{GITHUB_RAW_DESCRIPTION_URL}`). Anda memiliki **60 detik** untuk mengisi formulir.",
            color=self.color_info),
            view=view_instance
        )
        view_instance.message = initial_msg
        
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get("custom_id", "")
            if custom_id == "disabled_trap_counter":
                await interaction.response.send_message("🔨 Fitur ini berjalan otomatis. Anda tidak perlu mengklik tombol ini.", ephemeral=True)
                return
    
    @tasks.loop(minutes=1)
    async def update_panel_task(self):
        for guild in self.bot.guilds:
            await self.update_panel(guild)
    
    async def update_panel(self, guild: discord.Guild):
        guild_settings = self.get_guild_settings(guild.id)
        panel_id = guild_settings.get('mod_panel_message_id')
        channel_id = guild_settings.get('mod_panel_channel_id')

        if not panel_id or not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            return

        try:
            panel_message = await channel.fetch_message(panel_id)
        except discord.NotFound:
            guild_settings['mod_panel_message_id'] = None
            self.save_settings()
            
            await self.create_mod_panel_if_needed(guild)
            return
        
        except (discord.Forbidden, discord.errors.DiscordServerError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            return
        except Exception as e:
            return

        total_members = len(guild.members)
        bot_members = sum(1 for member in guild.members if member.bot)
        human_members = total_members - bot_members
        total_channels = len(guild.channels)
        
        status_data = load_data(self.status_file)
        current_status = status_data.get("status", "online")
        
        import random
        TIPS = [
            "Nyari teman mabar itu gampang, yang susah itu nyari yang nggak ngilang setelah sebulan.",
            "Online tiap hari di server, tapi tetep aja nggak ada yang nyadar pas off seminggu. 🚬",
            "Mute server sana-sini demi nungguin notif dari satu orang. Eh dia lagi DnD.",
            "Level di server udah mentok, tapi skill mabar masih di situ-situ aja. 🥲",
            "Discord cuma tempat mampir, dunia nyata tetep tempat kembali.",
            "Udah join banyak server, tetep aja ujung-ujungnya nongkrong di satu voice channel yang itu-itu lagi.",
            "Ngetik panjang di general, dibalesnya pake reaction doang. Sabar ya.",
            "Role lu emang paling atas, tapi kalau soal cari teman ngobrol, kita semua sama.",
            "Kalau sepi ya ngeramein sendiri, kalau rame malah jadi sider. Valid no debat.",
            "Kadang yang dicari di Discord bukan game-nya, tapi obrolan random jam 3 paginya. ☕"
        ]
        
        if current_status == "online":
            status_emoji = '🟢'
            status_text = 'Online & Berjalan'
        else:
            status_emoji = '🔴'
            status_text = 'Offline / DnD'

        tip = random.choice(TIPS)
        
        from cogs.v2_layout import build_v2_card, edit_v2_message
        
        v2_fields = [
            {
                "name": "📊 Statistik Server", 
                "value": f"👥 **Member:** `{total_members}` (🧍 `{human_members}` | 🤖 `{bot_members}`)\n📁 **Channel:** `{total_channels}`"
            },
            {
                "name": "🌐 Status Sistem", 
                "value": f"{status_emoji} **{status_text}**"
            }
        ]
        
        panel_roles = []
        for role_id in guild_settings.get("panel_role_stats", []):
            if role := guild.get_role(role_id):
                panel_roles.append(role)

        if panel_roles:
            v2_fields.append({"name": "✨ STATISTIK MEMBERSHIP", "value": "\u200B"})
            for role in panel_roles:
                member_count = len(role.members)
                v2_fields.append({"name": f"{role.name}", "value": f"```\n{member_count} Member\n```"})
                
        card = build_v2_card(
            title=f"🛡️ Moderator Control Panel - {guild.name}",
            description="Statistik real-time mengenai status server dan anggota.",
            fields=v2_fields,
            color=None,
            buttons=self.modpanel_buttons,
            footer=f"Terakhir diperbarui: {datetime.now(WIB).strftime('%d/%m/%Y %H:%M:%S')} WIB\n💡 Tips: {tip}"
        )
        
        try:
            from cogs.v2_layout import edit_v2_message
            resp = await edit_v2_message(self.bot, channel.id, panel_message.id, [card])
            if resp is None:
                # If editing fails (e.g. 400 Bad Request due to legacy embeds), we should delete the old one and clear the ID
                try: await panel_message.delete()
                except: pass
                guild_settings['mod_panel_message_id'] = None
                self.save_settings()
                await self.create_mod_panel_if_needed(guild)
        except discord.Forbidden:
            pass
        except Exception as e:
            print(f"Error updating mod panel V2: {e}")

    async def create_mod_panel_if_needed(self, guild: discord.Guild):
        guild_settings = self.get_guild_settings(guild.id)
        panel_id = guild_settings.get('mod_panel_message_id')
        channel_id = guild_settings.get('mod_panel_channel_id')
        
        if not panel_id and channel_id:
            channel = guild.get_channel(channel_id)
            if channel and channel.permissions_for(guild.me).send_messages:
                total_members = len(guild.members)
                bot_members = sum(1 for member in guild.members if member.bot)
                human_members = total_members - bot_members
                total_channels = len(guild.channels)

                status_data = load_data(self.status_file)
                current_status = status_data.get("status", "online")
                
                import random
                TIPS = [
                    "Nyari teman mabar itu gampang, yang susah itu nyari yang nggak ngilang setelah sebulan.",
                    "Online tiap hari di server, tapi tetep aja nggak ada yang nyadar pas off seminggu. 🚬",
                    "Mute server sana-sini demi nungguin notif dari satu orang. Eh dia lagi DnD.",
                    "Level di server udah mentok, tapi skill mabar masih di situ-situ aja. 🥲",
                    "Discord cuma tempat mampir, dunia nyata tetep tempat kembali.",
                    "Udah join banyak server, tetep aja ujung-ujungnya nongkrong di satu voice channel yang itu-itu lagi.",
                    "Ngetik panjang di general, dibalesnya pake reaction doang. Sabar ya.",
                    "Role lu emang paling atas, tapi kalau soal cari teman ngobrol, kita semua sama.",
                    "Kalau sepi ya ngeramein sendiri, kalau rame malah jadi sider. Valid no debat.",
                    "Kadang yang dicari di Discord bukan game-nya, tapi obrolan random jam 3 paginya. ☕"
                ]
                
                if current_status == "online":
                    status_emoji = '🟢'
                    status_text = 'Online & Berjalan'
                else:
                    status_emoji = '🔴'
                    status_text = 'Offline / DnD'

                tip = random.choice(TIPS)
                
                from cogs.v2_layout import build_v2_card, send_v2_message
                
                v2_fields = [
                    {
                        "name": "📊 Statistik Server", 
                        "value": f"👥 **Member:** `{total_members}` (🧍 `{human_members}` | 🤖 `{bot_members}`)\n📁 **Channel:** `{total_channels}`"
                    },
                    {
                        "name": "🌐 Status Sistem", 
                        "value": f"{status_emoji} **{status_text}**"
                    }
                ]
                
                panel_roles = []
                for role_id in guild_settings.get("panel_role_stats", []):
                    if role := guild.get_role(role_id):
                        panel_roles.append(role)

                if panel_roles:
                    v2_fields.append({"name": "✨ STATISTIK MEMBERSHIP", "value": "\u200B"})
                    for role in panel_roles:
                        member_count = len(role.members)
                        v2_fields.append({"name": f"{role.name}", "value": f"```\n{member_count} Member\n```"})
                
                card = build_v2_card(
                    title=f"🛡️ Moderator Control Panel - {guild.name}",
                    description="Statistik real-time mengenai status server dan anggota.",
                    fields=v2_fields,
                    color=None,
                    buttons=self.modpanel_buttons,
                    footer=f"Terakhir diperbarui: {datetime.now(WIB).strftime('%d/%m/%Y %H:%M:%S')} WIB\n💡 Tips: {tip}"
                )
                
                response = await send_v2_message(self.bot, channel.id, [card])
                if not response: return
                
                guild_settings['mod_panel_message_id'] = int(response['id'])
                guild_settings['mod_panel_channel_id'] = channel.id
                self.save_settings()

    @commands.hybrid_command(name="modpanel", description="Membuat panel statistik dan moderasi server.")
    @commands.has_permissions(manage_guild=True)
    async def modpanel(self, ctx: commands.Context):
        try:
            guild_settings = self.get_guild_settings(ctx.guild.id)
            panel_id = guild_settings.get('mod_panel_message_id')
            channel_id = guild_settings.get('mod_panel_channel_id')

            if panel_id and channel_id:
                try:
                    channel = ctx.guild.get_channel(channel_id)
                    if channel:
                        await channel.fetch_message(panel_id)
                        await ctx.send(embed=self._create_embed(description="❌ Panel moderasi sudah ada. Hapus pesan panel lama untuk membuat yang baru.", color=self.color_error), ephemeral=True)
                        return
                except discord.NotFound:
                    guild_settings['mod_panel_message_id'] = None
                    guild_settings['mod_panel_channel_id'] = None
                    self.save_settings()
                except discord.Forbidden:
                    await ctx.send(embed=self._create_embed(description="❌ Bot tidak memiliki izin untuk mengakses channel panel lama. Silakan minta admin server untuk mengatasinya.", color=self.color_error), ephemeral=True)
                    return

            total_members = len(ctx.guild.members)
            bot_members = sum(1 for member in ctx.guild.members if member.bot)
            human_members = total_members - bot_members
            total_channels = len(ctx.guild.channels)
            
            status_data = load_data(self.status_file)
            current_status = status_data.get("status", "online")
            
            import random
            TIPS = [
                "Nyari teman mabar itu gampang, yang susah itu nyari yang nggak ngilang setelah sebulan.",
                "Online tiap hari di server, tapi tetep aja nggak ada yang nyadar pas off seminggu. 🚬",
                "Mute server sana-sini demi nungguin notif dari satu orang. Eh dia lagi DnD.",
                "Level di server udah mentok, tapi skill mabar masih di situ-situ aja. 🥲",
                "Discord cuma tempat mampir, dunia nyata tetep tempat kembali.",
                "Udah join banyak server, tetep aja ujung-ujungnya nongkrong di satu voice channel yang itu-itu lagi.",
                "Ngetik panjang di general, dibalesnya pake reaction doang. Sabar ya.",
                "Role lu emang paling atas, tapi kalau soal cari teman ngobrol, kita semua sama.",
                "Kalau sepi ya ngeramein sendiri, kalau rame malah jadi sider. Valid no debat.",
                "Kadang yang dicari di Discord bukan game-nya, tapi obrolan random jam 3 paginya. ☕"
            ]
            
            if current_status == "online":
                status_emoji = '🟢'
                status_text = 'Online & Berjalan'
            else:
                status_emoji = '🔴'
                status_text = 'Offline / DnD'

            tip = random.choice(TIPS)
            
            from cogs.v2_layout import build_v2_card, send_v2_message
            
            v2_fields = [
                {
                    "name": "📊 Statistik Server", 
                    "value": f"👥 **Member:** `{total_members}` (🧍 `{human_members}` | 🤖 `{bot_members}`)\n📁 **Channel:** `{total_channels}`"
                },
                {
                    "name": "🌐 Status Sistem", 
                    "value": f"{status_emoji} **{status_text}**"
                }
            ]
            
            panel_roles = []
            for role_id in guild_settings.get("panel_role_stats", []):
                if role := ctx.guild.get_role(role_id):
                    panel_roles.append(role)

            if panel_roles:
                v2_fields.append({"name": "✨ STATISTIK MEMBERSHIP", "value": "\u200B"})
                for role in panel_roles:
                    member_count = len(role.members)
                    v2_fields.append({"name": f"{role.name}", "value": f"```\n{member_count} Member\n```"})
                    
            card = build_v2_card(
                title=f"🛡️ Moderator Control Panel - {ctx.guild.name}",
                description="Statistik real-time mengenai status server dan anggota.",
                fields=v2_fields,
                color=self.color_info,
                buttons=self.modpanel_buttons,
                footer=f"Terakhir diperbarui: {datetime.now(WIB).strftime('%d/%m/%Y %H:%M:%S')} WIB"
            )
            
            # Send message and get response dict
            response = await send_v2_message(self.bot, ctx.channel.id, [card])
            if response:
                guild_settings['mod_panel_message_id'] = int(response['id'])
                guild_settings['mod_panel_channel_id'] = ctx.channel.id
                self.save_settings()
            
            # We don't attach View directly to the API response, but since we registered the Persistent View globally in setup(),
            # discord.py will route the custom_ids to the callbacks!

        except discord.Forbidden:
            await ctx.author.send(embed=self._create_embed(description="❌ Bot tidak memiliki izin `Send Messages` dan `Embed Links` di channel tersebut. Silakan minta admin server untuk memberikan izin yang sesuai.", color=self.color_error))

        except Exception as e:
            await ctx.author.send(embed=self._create_embed(description=f"❌ Terjadi kesalahan tak terduga: {e}", color=self.color_error))

    @commands.command(name="toggle_status")
    @commands.has_permissions(manage_guild=True)
    async def toggle_status(self, ctx):
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass
            
        status_data = load_data(self.status_file)
        current_status = status_data.get("status", "online")

        if current_status == "online":
            status_data["status"] = "dnd"
            self.status["status"] = "dnd"
            self.save_status()
            await ctx.send(embed=self._create_embed(description="✅ Status panel bot berhasil diubah menjadi **Offline/Do Not Disturb**.", color=self.color_success), ephemeral=True)
        else:
            status_data["status"] = "online"
            self.status["status"] = "online"
            self.save_status()
            await ctx.send(embed=self._create_embed(description="✅ Status panel bot berhasil diubah menjadi **Online**.", color=self.color_success), ephemeral=True)
        
        await self.update_panel(ctx.guild)
    
    class ModPanelModal(discord.ui.Modal):
        def __init__(self, cog_instance, title):
            super().__init__(title=title)
            self.cog = cog_instance

    class WarnModal(ModPanelModal):
        def __init__(self, cog_instance):
            super().__init__(cog_instance, title="Peringatkan Pengguna")
            self.user_id = discord.ui.TextInput(
                label="ID atau username#tag",
                placeholder="Contoh: 123456789012345678 atau John#1234",
                required=True
            )
            self.reason = discord.ui.TextInput(
                label="Alasan Peringatan",
                placeholder="Contoh: Spam link di channel #general",
                style=discord.TextStyle.paragraph,
                required=True
            )
            self.add_item(self.user_id)
            self.add_item(self.reason)

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                member_id_or_name = self.user_id.value.strip()
                reason = self.reason.value.strip()
                member = await self.cog.fetch_member_from_id_or_name(interaction.guild, member_id_or_name)
                
                if member is None:
                    return await interaction.followup.send("❌ Pengguna tidak ditemukan.", ephemeral=True)
                
                warnings_list = self.cog.warnings.get(str(member.guild.id), {}).get(str(member.id), [])
                warning_count = len(warnings_list)
                
                await self.cog.warn_from_modal(interaction, member, reason)
                
                if warning_count > 0:
                     await interaction.followup.send(f"✅ {member.display_name} telah diberi peringatan. Total peringatan: **{warning_count + 1}**.", ephemeral=True)
                else:
                    await interaction.followup.send(f"✅ {member.display_name} telah diberi peringatan. Ini adalah peringatan pertama mereka.", ephemeral=True)
                
            except Exception as e:
                await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    class TimeoutModal(ModPanelModal):
        def __init__(self, cog_instance):
            super().__init__(cog_instance, title="Beri Timeout Pengguna")
            self.user_id = discord.ui.TextInput(
                label="ID atau username#tag",
                placeholder="Contoh: 123456789012345678 atau John#1234",
                required=True
            )
            self.duration = discord.ui.TextInput(
                label="Durasi (misal: 10m, 1h, 2d)",
                placeholder="Contoh: 30m (30 menit)",
                required=True
            )
            self.reason = discord.ui.TextInput(
                label="Alasan Timeout",
                placeholder="Contoh: Pelanggaran peraturan",
                required=False,
                style=discord.TextStyle.paragraph
            )
            self.add_item(self.user_id)
            self.add_item(self.duration)
            self.add_item(self.reason)
        
        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                member_id_or_name = self.user_id.value.strip()
                duration = self.duration.value.strip()
                reason = self.reason.value.strip() or "No reason provided."

                member = await self.cog.fetch_member_from_id_or_name(interaction.guild, member_id_or_name)

                if member is None:
                    return await interaction.followup.send("❌ Pengguna tidak ditemukan.", ephemeral=True)
                
                await self.cog.timeout_from_modal(interaction, member, duration, reason)
            except Exception as e:
                await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    class KickModal(ModPanelModal):
        def __init__(self, cog_instance):
            super().__init__(cog_instance, title="Tendang Pengguna")
            self.user_id = discord.ui.TextInput(
                label="ID atau username#tag",
                placeholder="Contoh: 123456789012345678 atau John#1234",
                required=True
            )
            self.reason = discord.ui.TextInput(
                label="Alasan Kick",
                placeholder="Contoh: Melanggar peraturan berulang kali",
                required=False,
                style=discord.TextStyle.paragraph
            )
            self.add_item(self.user_id)
            self.add_item(self.reason)
        
        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                member_id_or_name = self.user_id.value.strip()
                reason = self.reason.value.strip() or "No reason provided."
                
                member = await self.cog.fetch_member_from_id_or_name(interaction.guild, member_id_or_name)
                
                if member is None:
                    return await interaction.followup.send("❌ Pengguna tidak ditemukan.", ephemeral=True)

                await self.cog.kick_from_modal(interaction, member, reason)
            except Exception as e:
                await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    class BanModal(ModPanelModal):
        def __init__(self, cog_instance):
            super().__init__(cog_instance, title="Blokir Pengguna")
            self.user_id = discord.ui.TextInput(
                label="ID atau username#tag",
                placeholder="Contoh: 123456789012345678 atau John#1234",
                required=True
            )
            self.reason = discord.ui.TextInput(
                label="Alasan Ban",
                placeholder="Contoh: Pelanggaran berat",
                required=False,
                style=discord.TextStyle.paragraph
            )
            self.add_item(self.user_id)
            self.add_item(self.reason)
        
        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                member_id_or_name = self.user_id.value.strip()
                reason = self.reason.value.strip() or "No reason provided."

                member = await self.cog.fetch_member_from_id_or_name(interaction.guild, member_id_or_name)

                if member is None:
                    return await interaction.followup.send("❌ Pengguna tidak ditemukan.", ephemeral=True)
                
                await self.cog.ban_from_modal(interaction, member, reason)
            except Exception as e:
                await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    class ClearModal(ModPanelModal):
        def __init__(self, cog_instance):
            super().__init__(cog_instance, title="Hapus Pesan")
            self.amount = discord.ui.TextInput(
                label="Jumlah Pesan (1-100)",
                placeholder="Contoh: 10",
                required=True
            )
            self.channel_id = discord.ui.TextInput(
                label="Channel ID (Opsional)",
                placeholder="ID channel target (kosongkan untuk channel ini)",
                required=False
            )
            self.add_item(self.amount)
            self.add_item(self.channel_id)
        
        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                amount = int(self.amount.value.strip())
                if amount <= 0 or amount > 100:
                    return await interaction.followup.send("❌ Jumlah harus antara 1 dan 100.", ephemeral=True)

                channel_id_str = self.channel_id.value.strip()
                target_channel = interaction.channel
                if channel_id_str:
                    target_channel = interaction.guild.get_channel(int(channel_id_str))
                    if not target_channel or not isinstance(target_channel, discord.TextChannel):
                        return await interaction.followup.send("❌ Channel ID tidak valid.", ephemeral=True)
                
                deleted = await target_channel.purge(limit=amount)
                
                await self.cog.clear_from_modal(interaction, target_channel, len(deleted))
            except ValueError:
                await interaction.followup.send("❌ Masukkan angka yang valid.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    class UnbanModal(ModPanelModal):
        def __init__(self, cog_instance):
            super().__init__(cog_instance, title="Cabut Ban Pengguna")
            self.user_identifier = discord.ui.TextInput(
                label="ID atau username#tag",
                placeholder="Contoh: 123456789012345678 atau John#1234",
                required=True
            )
            self.reason = discord.ui.TextInput(
                label="Alasan Pencabutan Ban",
                placeholder="Contoh: Kesalahan administrasi",
                required=False,
                style=discord.TextStyle.paragraph
            )
            self.add_item(self.user_identifier)
            self.add_item(self.reason)

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                user_identifier = self.user_identifier.value.strip()
                reason = self.reason.value.strip() or "No reason provided."

                user_to_unban = None
                try:
                    user_id = int(user_identifier)
                    temp_user = await self.cog.bot.fetch_user(user_id)
                    user_to_unban = temp_user
                except ValueError:
                    for entry in [entry async for entry in interaction.guild.bans()]:
                        if str(entry.user).lower() == user_identifier.lower():
                            user_to_unban = entry.user
                            break
                except discord.NotFound:
                    pass

                if user_to_unban is None:
                    return await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ User `{user_identifier}` not found in ban list or invalid ID/Name#Tag.", color=self.cog.color_error), ephemeral=True)
                
                await self.cog.unban_from_modal(interaction, user_to_unban, reason)
            except Exception as e:
                await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    class UnwarnModal(ModPanelModal):
        def __init__(self, cog_instance):
            super().__init__(cog_instance, title="Cabut Peringatan Pengguna")
            self.user_id = discord.ui.TextInput(
                label="ID atau username#tag",
                placeholder="Contoh: 123456789012345678 atau John#1234",
                required=True
            )
            self.warning_index = discord.ui.TextInput(
                label="Nomor Peringatan",
                placeholder="Contoh: 1 (Gunakan !warnings untuk melihat nomor)",
                required=True
            )
            self.reason = discord.ui.TextInput(
                label="Alasan Pencabutan Peringatan",
                placeholder="Contoh: Kesalahan administrasi",
                required=False,
                style=discord.TextStyle.paragraph
            )
            self.add_item(self.user_id)
            self.add_item(self.warning_index)
            self.add_item(self.reason)

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                member_id_or_name = self.user_id.value.strip()
                warning_index = int(self.warning_index.value.strip())
                reason = self.reason.value.strip() or "Admin error."

                member = await self.cog.fetch_member_from_id_or_name(interaction.guild, member_id_or_name)
                
                if member is None:
                    return await interaction.followup.send("❌ Pengguna tidak ditemukan.", ephemeral=True)
                
                await self.cog.unwarn_from_modal(interaction, member, warning_index, reason)
            except ValueError:
                await interaction.followup.send("❌ Nomor peringatan harus berupa angka.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
    
    class RemoveTimeoutModal(ModPanelModal):
        def __init__(self, cog_instance):
            super().__init__(cog_instance, title="Cabut Timeout Pengguna")
            self.user_id = discord.ui.TextInput(
                label="ID atau username#tag",
                placeholder="Contoh: 123456789012345678 atau John#1234",
                required=True
            )
            self.add_item(self.user_id)
        
        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                member_id_or_name = self.user_id.value.strip()
                member = await self.cog.fetch_member_from_id_or_name(interaction.guild, member_id_or_name)
                
                if member is None:
                    return await interaction.followup.send("❌ Pengguna tidak ditemukan.", ephemeral=True)

                await self.cog.remove_timeout_from_modal(interaction, member)
            except Exception as e:
                await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    class LockModal(ModPanelModal):
        def __init__(self, cog_instance):
            super().__init__(cog_instance, title="Kunci Channel")
            self.channel_id = discord.ui.TextInput(
                label="Channel ID (Opsional)",
                placeholder="ID channel target (kosongkan untuk channel ini)",
                required=False
            )
            self.add_item(self.channel_id)
        
        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                channel_id_str = self.channel_id.value.strip()
                target_channel = interaction.channel
                if channel_id_str:
                    target_channel = interaction.guild.get_channel(int(channel_id_str))
                    if not target_channel or not isinstance(target_channel, discord.TextChannel):
                        return await interaction.followup.send("❌ Channel ID tidak valid.", ephemeral=True)

                current_perms = target_channel.permissions_for(interaction.guild.default_role)
                if not current_perms.send_messages is False:
                    await target_channel.set_permissions(interaction.guild.default_role, send_messages=False)
                    await interaction.followup.send(embed=self.cog._create_embed(description=f"🔒 Channel {target_channel.mention} telah dikunci.", color=self.cog.color_success), ephemeral=True)
                    await self.cog.log_action(interaction.guild, "🔒 Channel Locked", {"Channel": target_channel.mention, "Moderator": interaction.user.mention}, self.cog.color_warning)
                else:
                    await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Channel {target_channel.mention} sudah terkunci.", color=self.cog.color_error), ephemeral=True)

            except Exception as e:
                await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    class UnlockModal(ModPanelModal):
        def __init__(self, cog_instance):
            super().__init__(cog_instance, title="Buka Kunci Channel")
            self.channel_id = discord.ui.TextInput(
                label="Channel ID (Opsional)",
                placeholder="ID channel target (kosongkan untuk channel ini)",
                required=False
            )
            self.add_item(self.channel_id)
        
        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                channel_id_str = self.channel_id.value.strip()
                target_channel = interaction.channel
                if channel_id_str:
                    target_channel = interaction.guild.get_channel(int(channel_id_str))
                    if not target_channel or not isinstance(target_channel, discord.TextChannel):
                        return await interaction.followup.send("❌ Channel ID tidak valid.", ephemeral=True)

                current_perms = target_channel.permissions_for(interaction.guild.default_role)
                if not current_perms.send_messages is True:
                    await target_channel.set_permissions(interaction.guild.default_role, send_messages=None)
                    await interaction.followup.send(embed=self.cog._create_embed(description=f"🔓 Channel {target_channel.mention} telah dibuka kuncinya.", color=self.cog.color_success), ephemeral=True)
                    await self.cog.log_action(interaction.guild, "🔓 Channel Unlocked", {"Channel": target_channel.mention, "Moderator": interaction.user.mention}, self.cog.color_success)
                else:
                    await interaction.followup.send(embed=self.cog._create_embed(description=f"❌ Channel {target_channel.mention} sudah tidak terkunci.", color=self.cog.color_error), ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)


    async def fetch_member_from_id_or_name(self, guild, identifier):
        try:
            return await guild.fetch_member(int(identifier))
        except (ValueError, discord.NotFound):
            return guild.get_member_named(identifier)

    @commands.hybrid_command(name="remove_modpanel", description="Menghapus panel moderasi saat ini dari channel.")
    @commands.has_permissions(manage_guild=True)
    async def remove_modpanel(self, ctx: commands.Context):
        guild_settings = self.get_guild_settings(ctx.guild.id)
        panel_id = guild_settings.get('mod_panel_message_id')
        channel_id = guild_settings.get('mod_panel_channel_id')
        
        if panel_id and channel_id:
            try:
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    message = await channel.fetch_message(panel_id)
                    await message.delete()
            except Exception:
                pass
            
            guild_settings['mod_panel_message_id'] = None
            guild_settings['mod_panel_channel_id'] = None
            self.save_settings()
            await ctx.send("✅ Panel moderasi berhasil dihapus dan dinonaktifkan.", ephemeral=True)
        else:
            await ctx.send("⚠️ Tidak ada panel moderasi aktif di server ini.", ephemeral=True)

    class RealtimeModPanelView(discord.ui.View):
        def __init__(self, cog_instance):
            super().__init__(timeout=None)
            self.cog = cog_instance
            self.add_buttons()

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("❌ Anda harus memiliki izin `Manage Server` untuk menggunakan tombol moderasi ini.", ephemeral=True)
                return False
            return True

        def add_buttons(self):
            # Baris 0: Tindakan Hukuman (Punishments)
            warn_button = discord.ui.Button(label="Warn", style=discord.ButtonStyle.secondary, emoji="⚠️", row=0, custom_id="modpanel_warn")
            warn_button.callback = self.warn_user_callback
            self.add_item(warn_button)

            timeout_button = discord.ui.Button(label="Timeout", style=discord.ButtonStyle.primary, emoji="⏳", row=0, custom_id="modpanel_timeout")
            timeout_button.callback = self.timeout_user_callback
            self.add_item(timeout_button)

            kick_button = discord.ui.Button(label="Kick", style=discord.ButtonStyle.danger, emoji="👢", row=0, custom_id="modpanel_kick")
            kick_button.callback = self.kick_user_callback
            self.add_item(kick_button)

            ban_button = discord.ui.Button(label="Ban", style=discord.ButtonStyle.danger, emoji="🔨", row=0, custom_id="modpanel_ban")
            ban_button.callback = self.ban_user_callback
            self.add_item(ban_button)
            
            # Baris 1: Cabut Hukuman (Reversals)
            unwarn_button = discord.ui.Button(label="Unwarn", style=discord.ButtonStyle.success, emoji="🛡️", row=1, custom_id="modpanel_unwarn")
            unwarn_button.callback = self.unwarn_user_callback
            self.add_item(unwarn_button)

            remove_timeout_button = discord.ui.Button(label="Untimeout", style=discord.ButtonStyle.success, emoji="⏱️", row=1, custom_id="modpanel_untimeout")
            remove_timeout_button.callback = self.remove_timeout_callback
            self.add_item(remove_timeout_button)

            unban_button = discord.ui.Button(label="Unban", style=discord.ButtonStyle.success, emoji="🤝", row=1, custom_id="modpanel_unban")
            unban_button.callback = self.unban_user_callback
            self.add_item(unban_button)

            # Baris 2: Manajemen Channel (Channel Tools)
            clear_button = discord.ui.Button(label="Clear Chat", style=discord.ButtonStyle.danger, emoji="🧹", row=2, custom_id="modpanel_clear")
            clear_button.callback = self.clear_messages_callback
            self.add_item(clear_button)

            self.lock_button = discord.ui.Button(label="Lock", style=discord.ButtonStyle.danger, emoji="🔒", row=2, custom_id="modpanel_lock")
            self.lock_button.callback = self.lock_channel_callback
            self.add_item(self.lock_button)

            self.unlock_button = discord.ui.Button(label="Unlock", style=discord.ButtonStyle.success, emoji="🔓", row=2, custom_id="modpanel_unlock")
            self.unlock_button.callback = self.unlock_channel_callback
            self.add_item(self.unlock_button)

        async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
            await interaction.response.send_message(f"❌ Terjadi kesalahan: {error}", ephemeral=True)

        async def warn_user_callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.kick_members:
                return await interaction.response.send_message("❌ Anda tidak memiliki izin `Kick Members`.", ephemeral=True)
            await interaction.response.send_modal(self.cog.WarnModal(self.cog))

        async def timeout_user_callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.moderate_members:
                return await interaction.response.send_message("❌ Anda tidak memiliki izin `Moderate Members`.", ephemeral=True)
            await interaction.response.send_modal(self.cog.TimeoutModal(self.cog))

        async def kick_user_callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.kick_members:
                return await interaction.response.send_message("❌ Anda tidak memiliki izin `Kick Members`.", ephemeral=True)
            await interaction.response.send_modal(self.cog.KickModal(self.cog))

        async def ban_user_callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.ban_members:
                return await interaction.response.send_message("❌ Anda tidak memiliki izin `Ban Members`.", ephemeral=True)
            await interaction.response.send_modal(self.cog.BanModal(self.cog))

        async def unban_user_callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.ban_members:
                return await interaction.response.send_message("❌ Anda tidak memiliki izin `Ban Members`.", ephemeral=True)
            await interaction.response.send_modal(self.cog.UnbanModal(self.cog))

        async def unwarn_user_callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.kick_members:
                return await interaction.response.send_message("❌ Anda tidak memiliki izin `Kick Members`.", ephemeral=True)
            await interaction.response.send_modal(self.cog.UnwarnModal(self.cog))
        
        async def remove_timeout_callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.moderate_members:
                return await interaction.response.send_message("❌ Anda tidak memiliki izin `Moderate Members`.", ephemeral=True)
            await interaction.response.send_modal(self.cog.RemoveTimeoutModal(self.cog))

        async def clear_messages_callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.manage_messages:
                return await interaction.response.send_message("❌ Anda tidak memiliki izin `Manage Messages`.", ephemeral=True)
            await interaction.response.send_modal(self.cog.ClearModal(self.cog))

        async def lock_channel_callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.manage_channels:
                return await interaction.response.send_message("❌ Anda tidak memiliki izin `Manage Channels`.", ephemeral=True)
            
            target_channel = interaction.channel
            modal = self.cog.LockModal(self.cog)
            await interaction.response.send_modal(modal)

        async def unlock_channel_callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.manage_channels:
                return await interaction.response.send_message("❌ Anda tidak memiliki izin `Manage Channels`.", ephemeral=True)
            
            target_channel = interaction.channel
            modal = self.cog.UnlockModal(self.cog)
            await interaction.response.send_modal(modal)
    
    async def warn_from_modal(self, interaction, member, reason):
        timestamp = int(time.time())
        warning_data = {
            "moderator_id": interaction.user.id,
            "timestamp": timestamp,
            "reason": reason
        }
        guild_id_str = str(interaction.guild.id)
        member_id_str = str(member.id)

        self.warnings.setdefault(guild_id_str, {}).setdefault(member_id_str, []).append(warning_data)
        self.save_warnings()

        try:
            dm_embed = self._create_embed(title=f"🚨 You Received a Warning in {interaction.guild.name}", color=self.color_warning)
            dm_embed.add_field(name="Warning Reason", value=reason, inline=False)
            dm_embed.set_footer(text=f"Warning issued by {interaction.user.display_name}")
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        await self.check_and_escalate_warnings(interaction.guild, member, interaction.user)
    
    async def timeout_from_modal(self, interaction, member, duration, reason):
        delta = parse_duration(duration)
        if not delta: 
            await interaction.followup.send(embed=self._create_embed(description="❌ Invalid duration format. Use `s`, `m`, `h`, `d`. Example: `10m`.", color=self.color_error), ephemeral=True)
            return
        if delta.total_seconds() > 2419200:
            await interaction.followup.send(embed=self._create_embed(description="❌ Timeout duration cannot exceed 28 days.", color=self.color_error), ephemeral=True)
            return
        
        try:
            await member.timeout(delta, reason=reason)
            await interaction.followup.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has been timed out for `{duration}`.", color=self.color_success), ephemeral=True)
            await self.log_action(interaction.guild, "🤫 Member Timeout", {"Member": f"{member} ({member.id})", "Duration": duration, "Moderator": interaction.user.mention, "Reason": reason}, self.color_warning)
        except discord.Forbidden:
            await interaction.followup.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to timeout this member. Ensure the bot's role is higher.", color=self.color_error), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=self._create_embed(description=f"❌ An error occurred while timing out: {e}", color=self.color_error), ephemeral=True)
            
    async def kick_from_modal(self, interaction, member, reason):
        try:
            await member.kick(reason=reason)
            await interaction.followup.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has been kicked.", color=self.color_success), ephemeral=True)
            await self.log_action(interaction.guild, "👢 Member Kicked", {"Member": f"{member} ({member.id})", "Moderator": interaction.user.mention, "Reason": reason}, self.color_warning)
        except discord.Forbidden:
            await interaction.followup.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to kick this member. Ensure the bot's role is higher.", color=self.color_error), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=self._create_embed(description=f"❌ An error occurred while kicking the member: {e}", color=self.color_error), ephemeral=True)
            
    async def ban_from_modal(self, interaction, member, reason):
        try:
            await member.ban(reason=reason)
            await interaction.followup.send(embed=self._create_embed(description=f"✅ **{member.display_name}** has been banned.", color=self.color_success), ephemeral=True)
            await self.log_action(interaction.guild, "🔨 Member Banned", {"Member": f"{member} ({member.id})", "Moderator": interaction.user.mention, "Reason": reason}, self.color_error)
        except discord.Forbidden:
            await interaction.followup.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to ban this member. Ensure the bot's role is higher.", color=self.color_error), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=self._create_embed(description=f"❌ An error occurred while banning the member: {e}", color=self.color_error), ephemeral=True)
            
    async def unban_from_modal(self, interaction, user, reason):
        try:
            await interaction.guild.unban(user, reason=reason)
            await interaction.followup.send(embed=self._create_embed(description=f"✅ Ban for **{user}** has been lifted.", color=self.color_success), ephemeral=True)
            await self.log_action(interaction.guild, "🤝 Ban Lifted", {"User": f"{user} ({user.id})", "Moderator": interaction.user.mention, "Reason": reason}, self.color_success)
        except discord.Forbidden:
            await interaction.followup.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to unban this member.", color=self.color_error), ephemeral=True)
        except discord.NotFound:
            await interaction.followup.send(embed=self._create_embed(description=f"❌ User `{user}` not found in ban list.", color=self.color_error), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=self._create_embed(description=f"❌ An error occurred while unbanning: {e}", color=self.color_error), ephemeral=True)

    async def unwarn_from_modal(self, interaction, member, warning_index, reason):
        guild_id_str = str(interaction.guild.id)
        member_id_str = str(member.id)
        
        user_warnings = self.warnings.get(guild_id_str, {}).get(member_id_str, [])
        
        if not user_warnings:
            await interaction.followup.send(embed=self._create_embed(description=f"❌ **{member.display_name}** has no warnings.", color=self.color_error), ephemeral=True)
            return

        if not (0 < warning_index <= len(user_warnings)):
            await interaction.followup.send(embed=self._create_embed(description=f"❌ Invalid warning index. Use `!warnings {member.display_name}` to see the warning list.", color=self.color_error), ephemeral=True)
            return
        
        removed_warning = self.warnings[guild_id_str][member_id_str].pop(warning_index - 1)
        self.save_warnings()
        
        await interaction.followup.send(embed=self._create_embed(description=f"✅ Warning #{warning_index} for **{member.display_name}** has been removed.", color=self.color_success), ephemeral=True)
        
        log_fields = {
            "Member": f"{member} ({member.id})",
            "Moderator": interaction.user.mention,
            "Reason for Removal": reason,
            "Removed Warning": f"`{removed_warning['reason']}`"
        }
        await self.log_action(interaction.guild, "👍 Warning Removed", log_fields, self.color_success)

    async def remove_timeout_from_modal(self, interaction, member):
        if not member.is_timed_out():
            await interaction.followup.send(embed=self._create_embed(description=f"❌ {member.display_name} is not currently timed out.", color=self.color_error), ephemeral=True)
            return

        try:
            await member.timeout(None, reason=f"Timeout removed by {interaction.user.display_name}")
            await interaction.followup.send(embed=self._create_embed(description=f"✅ Timeout for **{member.display_name}** has been removed.", color=self.color_success), ephemeral=True)
            await self.log_action(interaction.guild, "😊 Timeout Removed", {"Member": f"{member} ({member.id})", "Moderator": interaction.user.mention}, self.color_success)
        except discord.Forbidden:
            await interaction.followup.send(embed=self._create_embed(description="❌ Bot does not have sufficient permissions to remove timeout for this member. Ensure the bot's role is higher.", color=self.color_error), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=self._create_embed(description=f"❌ An error occurred while removing timeout: {e}", color=self.color_error), ephemeral=True)


    async def clear_from_modal(self, interaction, target_channel, deleted_count):
        embed = self._create_embed(description=f"🗑️ Successfully deleted **{deleted_count}** messages from {target_channel.mention}.", color=self.color_success)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.log_action(interaction.guild, "🗑️ Messages Deleted", {"Channel": target_channel.mention, "Amount": f"{deleted_count} messages", "Moderator": interaction.user.mention}, self.color_info)
    
    @commands.hybrid_command(name="trap", aliases=["setjebakan", "triggerchannel"], description="Set atau hapus channel sebagai jebakan anti-spam (Honey-pot).")
    @app_commands.describe(action="Pilih 'add' untuk tambah, 'remove' untuk hapus jebakan", channel="Channel target")
    @commands.has_permissions(manage_guild=True)
    async def trap(self, ctx: commands.Context, action: str, channel: discord.TextChannel = None):
        action = action.lower()
        if action not in ["add", "remove"]:
            return await ctx.send("❌ Opsi tidak valid. Gunakan `add` atau `remove`.", ephemeral=True)
            
        target_channel = channel or ctx.channel
        guild_settings = self.get_guild_settings(ctx.guild.id)
        trigger_channels = guild_settings.get("trigger_channels", [])
        
        if action == "add":
            if target_channel.id in trigger_channels:
                return await ctx.send(f"⚠️ Channel {target_channel.mention} sudah menjadi Trigger Channel.", ephemeral=True)
            trigger_channels.append(target_channel.id)
            guild_settings["trigger_channels"] = trigger_channels
            self.save_settings()
            await ctx.send(embed=self._create_embed(description=f"✅ Channel {target_channel.mention} telah berhasil diatur sebagai jebakan anti-spam (Trap Channel).", color=self.color_success))
            
            from cogs.v2_layout import build_v2_card, send_v2_message
            
            global_count = self.settings.get("global_trap_count", 30)
            buttons = [
                {
                    "type": 2,
                    "style": 4, # Red / Danger
                    "label": f"Timeouts count: {global_count}",
                    "custom_id": "disabled_trap_counter",
                    "disabled": True,
                    "emoji": {"name": "🔨"}
                }
            ]
            
            card = build_v2_card(
                title="🚨 PERINGATAN KERAS / WARNING 🚨",
                description="**JANGAN MENGIRIM PESAN DI CHANNEL INI**\n**DO NOT SEND MESSAGES IN THIS CHANNEL**\n\nChannel ini khusus untuk mendeteksi spam & phishing. Setiap pesan yang Anda kirim di sini akan mengakibatkan sanksi **Timeout Otomatis 28 Hari**.\n\n*This channel is strictly for spam & phishing detection, any messages sent here will result in an immediate 28-day timeout.*\n\nMohon patuhi peraturan server yang ada untuk menghindari sanksi dari sistem otomatis kami.",
                color=None,
                buttons=buttons
            )
            
            try:
                msg_data = await send_v2_message(self.bot, target_channel.id, [card])
                if msg_data and "id" in msg_data:
                    guild_settings[f"trap_msg_{target_channel.id}"] = int(msg_data["id"])
                    
                    if "global_trap_count" not in self.settings:
                        self.settings["global_trap_count"] = 30
                    self.save_settings()
            except Exception as e:
                print(f"Failed to send trap message: {e}")
            
        elif action == "remove":
            if target_channel.id not in trigger_channels:
                return await ctx.send(f"⚠️ Channel {target_channel.mention} bukan Trigger Channel.", ephemeral=True)
            trigger_channels.remove(target_channel.id)
            guild_settings["trigger_channels"] = trigger_channels
            self.save_settings()
            await ctx.send(embed=self._create_embed(description=f"✅ Channel {target_channel.mention} telah dihapus dari daftar jebakan anti-spam.", color=self.color_success))

async def setup(bot):
    cog = ServerAdminCog(bot)
    await bot.add_cog(cog)
    bot.add_view(cog.RealtimeModPanelView(cog))
