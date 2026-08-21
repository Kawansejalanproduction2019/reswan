import discord
from discord.ext import commands, tasks
import asyncio
import os
import logging
import json
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

TEMP_CHANNELS_FILE = 'data/temp_voice_channels.json'
GUILD_CONFIG_FILE = 'data/guild_config.json'

ENABLE_SCHEDULED_CREATION = False
CREATION_START_TIME = (20, 0)
CREATION_END_TIME = (6, 0)
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
    except json.JSONDecodeError:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, indent=4)
        return data
    except Exception:
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

def load_guild_config():
    return load_json_file(GUILD_CONFIG_FILE)

def save_guild_config(data):
    save_json_file(GUILD_CONFIG_FILE, data)

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
            return await interaction.response.send_message("Bot: Kamu bukan pemilik channel ini!", ephemeral=True)
        vc = interaction.user.voice.channel
        new_name = self.new_name.value
        try:
            await vc.edit(name=new_name, reason=f"User {interaction.user.display_name} renamed VC via UI.")
            await interaction.response.send_message(f"Bot: Nama channelmu diubah menjadi {new_name}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Bot: Tidak memiliki izin untuk mengubah nama channel ini.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)

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
        except Exception:
            pass

    async def _check_owner(self, interaction: discord.Interaction):
        if not self.cog.is_owner_vc_by_interaction(interaction):
            await interaction.response.send_message("Bot: Kamu bukan pemilik channel ini!", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="➕", label="Tambah Kursi", style=discord.ButtonStyle.secondary, custom_id="vc:limit_plus", row=0)
    async def limit_plus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        new_limit = min(vc.user_limit + 1, 99)
        try:
            await vc.edit(user_limit=new_limit, reason=f"User {interaction.user.display_name} increased user limit.")
            await interaction.response.send_message(f"🪑 Kursi ditambah! Maksimal orang sekarang: {new_limit}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Tidak memiliki izin untuk mengubah batas user.", ephemeral=True)
    
    @discord.ui.button(emoji="➖", label="Kurangi Kursi", style=discord.ButtonStyle.secondary, custom_id="vc:limit_minus", row=0)
    async def limit_minus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        new_limit = max(vc.user_limit - 1, 0)
        try:
            await vc.edit(user_limit=new_limit, reason=f"User {interaction.user.display_name} decreased user limit.")
            await interaction.response.send_message(f"🪑 Kursi dikurangi! Maksimal orang sekarang: {new_limit if new_limit > 0 else 'tak terbatas'}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Tidak memiliki izin untuk mengubah batas user.", ephemeral=True)

    @discord.ui.button(emoji="🏷️", label="Ganti Papan Nama", style=discord.ButtonStyle.secondary, custom_id="vc:rename", row=1)
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        await interaction.response.send_modal(RenameVCModal(self.cog))

    @discord.ui.button(emoji="🔐", label="Gembok Ruangan", style=discord.ButtonStyle.secondary, custom_id="vc:lock", row=1)
    async def lock_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        try:
            await vc.set_permissions(interaction.guild.default_role, connect=False, reason=f"User {interaction.user.display_name} locked VC via UI.")
            await interaction.response.send_message(f"🔐 Pintu ruangan digembok! Orang luar tidak bisa masuk lagi.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Tidak memiliki izin untuk mengunci channel ini.", ephemeral=True)
    
    @discord.ui.button(emoji="🔓", label="Buka Gembok", style=discord.ButtonStyle.secondary, custom_id="vc:unlock", row=1)
    async def unlock_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        try:
            await vc.set_permissions(interaction.guild.default_role, connect=True, reason=f"User {interaction.user.display_name} unlocked VC via UI.")
            await interaction.response.send_message(f"🔓 Gembok dibuka! Sekarang siapa saja bisa masuk.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Tidak memiliki izin untuk membuka kunci channel ini.", ephemeral=True)

    @discord.ui.button(emoji="👻", label="Mode Siluman", style=discord.ButtonStyle.secondary, custom_id="vc:toggle_visibility", row=2)
    async def toggle_visibility_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        everyone_role = interaction.guild.default_role
        current_permission = vc.overwrites_for(everyone_role).view_channel
        try:
            if current_permission is True or current_permission is None:
                await vc.set_permissions(everyone_role, view_channel=False)
                await interaction.response.send_message("👻 Mode Siluman Aktif! Orang luar tidak bisa melihat ruangan ini.", ephemeral=True)
            else:
                await vc.set_permissions(everyone_role, view_channel=True)
                await interaction.response.send_message("👀 Mode Siluman Mati! Ruangan sekarang terlihat umum.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Tidak memiliki izin untuk mengubah visibilitas channel ini.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
    
    @discord.ui.button(emoji="🔗", label="Buat Undangan", style=discord.ButtonStyle.secondary, custom_id="vc:invite", row=2)
    async def invite_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        try:
            invite = await vc.create_invite(max_age=3600, max_uses=1, unique=True, reason=f"Invite created by VC owner {interaction.user.display_name} via UI.")
            await interaction.response.send_message(f"🔗 Ini link undangan rahasia untuk ruanganmu: {invite.url}\n(Link ini hanya bisa dipakai 1 kali)", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Tidak memiliki izin untuk membuat link undangan di channel ini.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Terjadi kesalahan saat membuat undangan: {e}", ephemeral=True)

    @discord.ui.button(emoji="🛑", label="Tutup Ruangan", style=discord.ButtonStyle.danger, custom_id="vc:delete", row=2)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        vc_id_str = str(vc.id)
        if vc_id_str in self.cog.active_temp_channels:
            del self.cog.active_temp_channels[vc_id_str]
            save_temp_channels(self.cog.active_temp_channels)
        try:
            await interaction.response.send_message(f"🛑 Ruangan telah dibongkar dan ditutup.", ephemeral=True)
            await vc.delete(reason=f"VC deleted by owner {interaction.user.display_name} via UI.")
        except discord.NotFound:
            await interaction.response.send_message("❌ Channel ini sudah terhapus.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Tidak memiliki izin untuk menghapus channel ini.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Terjadi kesalahan saat menghapus channel: {e}", ephemeral=True)

    @discord.ui.button(emoji="👢", label="Usir Penyusup", style=discord.ButtonStyle.danger, custom_id="vc:kick", row=3)
    async def kick_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_owner(interaction): return
        vc = interaction.user.voice.channel
        
        options = []
        for member in vc.members:
            if member.id != interaction.user.id and not member.bot:
                options.append(discord.SelectOption(label=member.display_name, value=str(member.id)))
                
        if not options:
            return await interaction.response.send_message("❌ Tidak ada orang lain di ruanganmu untuk diusir.", ephemeral=True)
            
        select = discord.ui.Select(placeholder="Pilih penyusup yang mau diusir...", options=options)
        
        async def select_callback(inter):
            if inter.user.id != interaction.user.id:
                return
            target_id = int(select.values[0])
            target_member = vc.guild.get_member(target_id)
            if target_member and target_member in vc.members:
                await target_member.move_to(None)
                await inter.response.send_message(f"👢 {target_member.display_name} telah ditendang dari ruangan!", ephemeral=True)
            else:
                await inter.response.send_message("❌ Orang tersebut sudah tidak ada di ruangan.", ephemeral=True)
                
        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Pilih penyusup yang ingin kamu tendang:", view=view, ephemeral=True)

    @discord.ui.button(emoji="👑", label="Klaim Ruangan", style=discord.ButtonStyle.primary, custom_id="vc:claim", row=3)
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            return await interaction.response.send_message("❌ Kamu harus berada di dalam ruangan suara untuk mengklaimnya.", ephemeral=True)
        
        vc_id_str = str(vc.id)
        if vc_id_str not in self.cog.active_temp_channels:
            return await interaction.response.send_message("❌ Ini bukan ruangan sementara yang bisa diklaim.", ephemeral=True)
            
        current_owner_id = int(self.cog.active_temp_channels[vc_id_str]["owner_id"])
        if current_owner_id == interaction.user.id:
            return await interaction.response.send_message("✅ Kamu sudah menjadi pemilik ruangan ini!", ephemeral=True)
            
        current_owner_in_vc = any(member.id == current_owner_id for member in vc.members)
        if current_owner_in_vc:
            return await interaction.response.send_message("❌ Pemilik aslinya masih ada di dalam ruangan! Kamu tidak bisa merebutnya.", ephemeral=True)
            
        self.cog.active_temp_channels[vc_id_str]["owner_id"] = str(interaction.user.id)
        save_temp_channels(self.cog.active_temp_channels)
        await interaction.response.send_message("👑 Berhasil! Kamu sekarang adalah Ketua RT (Pemilik) ruangan ini.", ephemeral=True)


class TempVoice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_config = load_guild_config()
        self.active_temp_channels = load_temp_channels()
        self.bot.add_view(VCControlView(self))
        self.cleanup_task.start()
        
    def cog_unload(self):
        self.cleanup_task.cancel()

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
                except Exception:
                    pass
        for ch_id in channels_to_remove:
            self.active_temp_channels.pop(ch_id, None)
        if channels_to_remove:
            save_temp_channels(self.active_temp_channels)

    @cleanup_task.before_loop
    async def before_cleanup_task(self):
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
                        return await self.send_scheduled_message(member, "Bot: Maaf, pembuatan channel pribadi hanya tersedia pada waktu yang ditentukan.")
                elif not (start_time <= now <= end_time):
                    return await self.send_scheduled_message(member, "Bot: Maaf, pembuatan channel pribadi hanya tersedia pada waktu yang ditentukan.")
            
            for ch_id_str, ch_info in list(self.active_temp_channels.items()):
                if not isinstance(ch_info, dict):
                    continue
                if ch_info.get("owner_id") == str(member.id) and ch_info.get("guild_id") == guild_id_str:
                    existing_channel = member.guild.get_channel(int(ch_id_str))
                    if existing_channel:
                        try:
                            await member.move_to(existing_channel)
                            return
                        except Exception:
                            return
                    else:
                        self.active_temp_channels.pop(ch_id_str)
                        save_temp_channels(self.active_temp_channels)
            
            guild = member.guild
            category = guild.get_channel(target_cat_id)
            if not category or not isinstance(category, discord.CategoryChannel):
                try: await member.send("Bot: Gagal membuat channel suara pribadi. Kategori target tidak valid.")
                except discord.Forbidden: pass
                try: await member.move_to(None)
                except Exception: pass
                return
            
            current_category_channels = [ch for ch in category.voice_channels if ch.name.startswith("Music ") or ch.name.startswith("Voice ")]
            next_channel_number = len(current_category_channels) + 1
            new_channel_name = f"Voice {next_channel_number}"
            
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
                
                bitrate_to_set = guild.bitrate_limit
                bitrate_kbps = bitrate_to_set // 1000 
                
                new_vc = await guild.create_voice_channel(
                    name=new_channel_name,
                    category=category,
                    user_limit=0,
                    overwrites=overwrites,
                    bitrate=bitrate_to_set, 
                    rtc_region=TARGET_REGION,
                    reason=f"{member.display_name} created a temporary voice channel."
                )
                
                await member.move_to(new_vc)
                self.active_temp_channels[str(new_vc.id)] = {"owner_id": str(member.id), "guild_id": guild_id_str}
                save_temp_channels(self.active_temp_channels)
                
                try:
                    from cogs.v2_layout import build_v2_card, send_v2_message
                    buttons = [
                        {"label": "Tambah Kursi", "emoji": "🪑", "style": 2, "custom_id": "vc:limit_plus"},
                        {"label": "Kurangi Kursi", "emoji": "🪑", "style": 2, "custom_id": "vc:limit_minus"},
                        {"label": "Ganti Papan Nama", "emoji": "🏷️", "style": 2, "custom_id": "vc:rename"},
                        {"label": "Gembok Ruangan", "emoji": "🔐", "style": 2, "custom_id": "vc:lock"},
                        {"label": "Buka Gembok", "emoji": "🔓", "style": 2, "custom_id": "vc:unlock"},
                        {"label": "Mode Siluman", "emoji": "👻", "style": 2, "custom_id": "vc:toggle_visibility"},
                        {"label": "Buat Undangan", "emoji": "🔗", "style": 2, "custom_id": "vc:invite"},
                        {"label": "Tutup Ruangan", "emoji": "🛑", "style": 4, "custom_id": "vc:delete"},
                        {"label": "Usir Penyusup", "emoji": "👢", "style": 4, "custom_id": "vc:kick"},
                        {"label": "Klaim Ruangan", "emoji": "👑", "style": 1, "custom_id": "vc:claim"}
                    ]
                    
                    card_json = build_v2_card(
                        title="🎙️ Ruang Pribadimu Siap!",
                        description=f"Selamat datang di {new_vc.name}, <@{member.id}>!\nRuangan ini sepenuhnya milikmu.\nBitrate: **{bitrate_kbps} kbps** | Region: **{TARGET_REGION.upper()}**\n\n**📖 Panduan Tombol Ruangan:**\n🪑 **Kursi**: Menambah atau mengurangi batas maksimal orang yang bisa masuk.\n🏷️ **Ganti Papan Nama**: Mengubah nama ruanganmu sesuka hati.\n🔐 **Gembok & Buka Gembok**: Mengunci pintu agar orang luar tidak bisa masuk (dan sebaliknya).\n👻 **Mode Siluman**: Menyembunyikan ruanganmu dari pandangan orang lain di server.\n🔗 **Buat Undangan**: Membuat link khusus untuk mengajak teman bergabung.\n👢 **Usir Penyusup**: Menendang orang yang masuk tanpa izin.\n👑 **Klaim Ruangan**: Mengambil alih hak milik jika si pembuat ruangan pergi.\n🛑 **Tutup Ruangan**: Membongkar dan menghapus ruangan ini seketika.\n\n*Ruangan akan otomatis hilang sendiri jika semua orang sudah keluar.*",
                        color=0x2ecc71,
                        buttons=buttons
                    )
                    await send_v2_message(self.bot, new_vc.id, components=card_json.get("components", []))
                except Exception as e:
                    print(f"[V2 CARD ERROR] {e}")
                    embed = discord.Embed(
                        title="Channel Pribadimu Dibuat!",
                        description=f"Selamat datang di {new_vc.name}, {member.mention}! Kamu adalah pemilik channel ini.\nBitrate diatur maksimal ({bitrate_kbps} kbps) dan Region diatur ke {TARGET_REGION.upper()}.\n\nGunakan tombol di bawah untuk mengelola channelmu tanpa perintah teks.\nChannel ini akan otomatis dihapus jika tidak ada user di dalamnya.",
                        color=discord.Color.green()
                    )
                    view = VCControlView(self)
                    await new_vc.send(embed=embed, view=view)
            except discord.Forbidden:
                try: await member.send(f"Bot: Gagal membuat channel suara pribadi, pastikan bot memiliki izin yang cukup.")
                except discord.Forbidden: pass
                try: await member.move_to(None)
                except Exception: pass
            except Exception as e:
                try: await member.send(f"Bot: Terjadi kesalahan saat membuat channel pribadi: {e}")
                except discord.Forbidden: pass
                try: await member.move_to(None)
                except Exception: pass

    async def send_scheduled_message(self, member, message_content):
        try:
            await member.move_to(None)
        except Exception:
            pass
        try:
            await member.send(message_content)
        except discord.Forbidden:
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
        return channel_info.get("owner_id") == str(ctx.author.id)
        
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
        return channel_info.get("owner_id") == str(interaction.user.id)

    @commands.hybrid_group(name="vcadmin", description="Admin: Kelola konfigurasi channel suara sementara", fallback="help")
    async def vcadmin_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Gunakan subcommand seperti `/vcadmin settrigger` atau `/vcadmin setcat`.", ephemeral=True)

    @vcadmin_group.command(name="settrigger", description="Admin: Atur channel pemicu untuk join-to-create")
    @commands.has_permissions(administrator=True)
    async def set_trigger_channel(self, ctx, channel: discord.VoiceChannel):
        try:
            self.guild_config[str(ctx.guild.id)] = self.guild_config.get(str(ctx.guild.id), {})
            self.guild_config[str(ctx.guild.id)]['trigger_vc_id'] = channel.id
            save_guild_config(self.guild_config)
            await ctx.send(f"Bot: Saluran pemicu untuk server ini telah diatur ke {channel.mention}.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)

    @vcadmin_group.command(name="setcat", description="Admin: Atur kategori tempat channel sementara dibuat")
    @commands.has_permissions(administrator=True)
    async def set_target_category(self, ctx, category: discord.CategoryChannel):
        try:
            self.guild_config[str(ctx.guild.id)] = self.guild_config.get(str(ctx.guild.id), {})
            self.guild_config[str(ctx.guild.id)]['target_category_id'] = category.id
            save_guild_config(self.guild_config)
            await ctx.send(f"Bot: Kategori target untuk saluran sementara telah diatur ke {category.mention}.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)

    @vcadmin_group.command(name="reset", description="Admin: Hapus total/reset pengaturan trigger & kategori (Mematikan fitur Temp VC)")
    @commands.has_permissions(administrator=True)
    async def reset_config(self, ctx):
        try:
            guild_id_str = str(ctx.guild.id)
            if guild_id_str in self.guild_config:
                self.guild_config[guild_id_str].pop('trigger_vc_id', None)
                self.guild_config[guild_id_str].pop('target_category_id', None)
                save_guild_config(self.guild_config)
                await ctx.send("🧹 Konfigurasi berhasil dihapus! Fitur Join-to-Create sekarang dalam kondisi **MATI** di server ini.", ephemeral=True)
            else:
                await ctx.send("❌ Server ini belum memiliki pengaturan Temp VC.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)

    @commands.hybrid_group(name="vc", description="Kelola ruangan pribadimu", fallback="help")
    async def vc_group(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Panduan Channel Suara Pribadi",
                description="Saat kamu bergabung ke Channel Khusus Buat VC Baru, bot akan otomatis membuat channel suara baru untukmu!",
                color=discord.Color.blue()
            )
            embed.add_field(name="Manajemen Channel:", value="`/vc limit <angka>`: Atur batas jumlah user.\n`/vc rename <nama_baru>`: Ubah nama channel suaramu.\n`/vc lock`: Kunci channel\n`/vc unlock`: Buka kunci channelmu\n`/vc delete`: Hapus ruangan", inline=False)
            embed.add_field(name="Manajemen User:", value="`/vc kick @user`: Tendang user dari channelmu.\n`/vc grant @user`: Beri user izin masuk.\n`/vc revoke @user`: Cabut izin user.\n`/vc transfer @user`: Transfer kepemilikan.", inline=False)
            await ctx.send(embed=embed)

    @vc_group.command(name="lock", description="Gembok ruangan agar orang lain tidak bisa masuk")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_lock(self, ctx):
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(ctx.guild.default_role, connect=False, reason=f"User {ctx.author.display_name} locked VC.")
            await ctx.send(f"🔐 Pintu ruangan {vc.name} telah digembok.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)

    @vc_group.command(name="unlock", description="Buka gembok ruangan agar siapa saja bisa masuk")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_unlock(self, ctx):
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(ctx.guild.default_role, connect=True, reason=f"User {ctx.author.display_name} unlocked VC.")
            await ctx.send(f"🔓 Gembok ruangan {vc.name} telah dibuka.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)

    @vc_group.command(name="limit", description="Atur maksimal jumlah orang di ruangan")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_set_limit(self, ctx, limit: int):
        if limit < 0 or limit > 99:
            return await ctx.send("Bot: Batas user harus antara 0 hingga 99.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            await vc.edit(user_limit=limit, reason=f"User {ctx.author.display_name} set user limit.")
            await ctx.send(f"🪑 Batas kursi diatur ke: {limit if limit > 0 else 'tak terbatas'}.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)

    @vc_group.command(name="rename", description="Ganti papan nama ruangan")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_rename(self, ctx, *, new_name: str):
        if len(new_name) < 2 or len(new_name) > 100:
            return await ctx.send("Bot: Nama channel harus antara 2 hingga 100 karakter.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            await vc.edit(name=new_name, reason=f"User {ctx.author.display_name} renamed VC.")
            await ctx.send(f"🏷️ Nama ruangan diubah menjadi {new_name}.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)

    @vc_group.command(name="kick", description="Tendang penyusup dari ruangan")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_kick(self, ctx, member: discord.Member):
        if member.id == ctx.author.id or member.bot:
            return await ctx.send("Bot: Kamu tidak bisa menendang dirimu sendiri atau bot.", ephemeral=True)
        vc = ctx.author.voice.channel
        if member.voice and member.voice.channel == vc:
            try:
                await member.move_to(None, reason=f"Kicked by VC owner {ctx.author.display_name}.")
                await ctx.send(f"👢 {member.display_name} telah ditendang dari ruangan.", ephemeral=True)
            except Exception as e:
                await ctx.send(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)
        else:
            await ctx.send("Bot: Pengguna tersebut tidak berada di ruanganmu.", ephemeral=True)

    @vc_group.command(name="grant", description="Beri izin VIP untuk user tertentu masuk")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_grant(self, ctx, member: discord.Member):
        if member.bot: return
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(member, connect=True, reason=f"VC owner {ctx.author.display_name} granted access.")
            await ctx.send(f"✅ {member.display_name} sekarang diizinkan bergabung ke ruangan.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)

    @vc_group.command(name="revoke", description="Cabut izin VIP dari user tertentu")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_revoke(self, ctx, member: discord.Member):
        if member.bot: return
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(member, connect=False, reason=f"VC owner {ctx.author.display_name} revoked access.")
            await ctx.send(f"❌ Izin akses {member.display_name} telah dicabut.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)

    @vc_group.command(name="transfer", description="Berikan hak milik ruangan ke temanmu")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_transfer_owner(self, ctx, new_owner: discord.Member):
        vc = ctx.author.voice.channel
        vc_id_str = str(vc.id)
        if new_owner.bot or new_owner.id == ctx.author.id: return
        try:
            self.active_temp_channels[vc_id_str]["owner_id"] = str(new_owner.id)
            save_temp_channels(self.active_temp_channels)
            
            old_owner_overwrites = vc.overwrites_for(ctx.author)
            old_owner_overwrites.manage_channels = None
            old_owner_overwrites.manage_roles = None
            old_owner_overwrites.mute_members = None
            old_owner_overwrites.deafen_members = None
            old_owner_overwrites.move_members = None
            await vc.set_permissions(ctx.author, overwrite=old_owner_overwrites)
            
            new_owner_overwrites = vc.overwrites_for(new_owner)
            new_owner_overwrites.manage_channels = True
            new_owner_overwrites.manage_roles = True
            new_owner_overwrites.mute_members = True
            new_owner_overwrites.deafen_members = True
            new_owner_overwrites.move_members = True
            await vc.set_permissions(new_owner, overwrite=new_owner_overwrites)
            
            await ctx.send(f"👑 Kepemilikan ruangan ditransfer ke {new_owner.mention}!", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan saat mengalihkan kepemilikan: {e}", ephemeral=True)

    @vc_group.command(name="delete", description="Tutup paksa dan hapus ruanganmu sekarang")
    @commands.check(lambda ctx: ctx.cog.is_owner_vc(ctx))
    async def vc_delete(self, ctx):
        vc = ctx.author.voice.channel
        vc_id_str = str(vc.id)
        try:
            if vc_id_str in self.active_temp_channels:
                del self.active_temp_channels[vc_id_str]
                save_temp_channels(self.active_temp_channels)
            await ctx.send(f"🛑 Ruangan telah dibongkar dan ditutup.", ephemeral=True)
            await vc.delete(reason=f"VC deleted by owner {ctx.author.display_name} via Command.")
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan saat menghapus channel: {e}", ephemeral=True)

    @vcadmin_group.command(name="transfer", description="Admin: Paksa alihkan hak milik sebuah ruangan sementara")
    @commands.has_permissions(administrator=True)
    async def admin_vc_transfer_owner(self, ctx, channel: discord.VoiceChannel, new_owner: discord.Member):
        channel_id_str = str(channel.id)
        if channel_id_str not in self.active_temp_channels or new_owner.bot: return
        
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
                await channel.set_permissions(old_owner, overwrite=old_owner_overwrites)
                
            new_owner_overwrites = channel.overwrites_for(new_owner)
            new_owner_overwrites.manage_channels = True
            new_owner_overwrites.manage_roles = True
            new_owner_overwrites.mute_members = True
            new_owner_overwrites.deafen_members = True
            new_owner_overwrites.move_members = True
            await channel.set_permissions(new_owner, overwrite=new_owner_overwrites)
            
            await ctx.send(f"👑 Kepemilikan saluran {channel.mention} dialihkan ke {new_owner.mention}.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Bot: Terjadi kesalahan: {e}", ephemeral=True)



    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if ctx.cog != self:
            return
        
        try:
            if isinstance(error, commands.CheckFailure):
                await ctx.send("Bot: Kamu harus berada di channel suara pribadi milikmu untuk menggunakan perintah ini.", ephemeral=True)
            elif isinstance(error, commands.MissingRequiredArgument):
                await ctx.send(f"Bot: Argumen tidak lengkap. Contoh penggunaan: !{ctx.command.name} {ctx.command.signature}", ephemeral=True)
            elif isinstance(error, commands.BadArgument):
                await ctx.send(f"Bot: Argumen tidak valid.", ephemeral=True)
            elif isinstance(error, discord.Forbidden):
                await ctx.send("Bot: Bot tidak memiliki izin yang diperlukan.", ephemeral=True)
        except Exception:
            pass

async def setup(bot):
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
    await bot.add_cog(TempVoice(bot))
