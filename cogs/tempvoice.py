import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
import logging
from datetime import datetime

log = logging.getLogger(__name__)

# --- KONFIGURASI ---
# Ganti dengan ID Voice Channel pemicu (tempat user bergabung untuk membuat VC baru)
TRIGGER_VOICE_CHANNEL_ID = 1382486705113927811 # Ganti dengan ID VC pemicu Anda
# Ganti dengan ID Kategori tempat Voice Channel baru akan dibuat
TARGET_CATEGORY_ID = 1255211613326278716 # Ganti dengan ID Kategori target Anda
# Nama dasar untuk channel yang dibuat
DEFAULT_CHANNEL_NAME_PREFIX = "Music"

# --- FILE DATA UNTUK MELACAK CHANNEL SEMENTARA (Persisten antar restart bot) ---
TEMP_CHANNELS_FILE = 'data/temp_voice_channels.json'

def load_temp_channels():
    if not os.path.exists('data'):
        os.makedirs('data')
    if not os.path.exists(TEMP_CHANNELS_FILE):
        with open(TEMP_CHANNELS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=4)
        return {}
    try:
        with open(TEMP_CHANNELS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Konversi string ID kembali ke int jika perlu, atau pastikan selalu string
            return {str(k): v for k, v in data.items()} # Simpan sebagai string key
    except json.JSONDecodeError as e:
        log.error(f"Failed to load {TEMP_CHANNELS_FILE}: {e}. File might be corrupted. Attempting to reset it.")
        # Reset file jika korup
        with open(TEMP_CHANNELS_FILE, 'w', encoding='utf-8') as f: # Changed to utf-8
            json.dump({}, f, indent=4)
        return {}

def save_temp_channels(data):
    os.makedirs('data', exist_ok=True) # Ensure data dir exists
    # Pastikan semua key adalah string sebelum disimpan
    data_to_save = {str(k): v for k, v in data.items()}
    with open(TEMP_CHANNELS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data_to_save, f, indent=4)


class TempVoice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.active_temp_channels: {channel_id_str: {"owner_id": int, "guild_id": int}}
        self.active_temp_channels = load_temp_channels() 
        log.info(f"TempVoice cog loaded. Active temporary channels: {self.active_temp_channels}")
        self.cleanup_task.start()

    def cog_unload(self):
        log.info("TempVoice cog unloaded. Cancelling cleanup task.")
        self.cleanup_task.cancel()

    @tasks.loop(seconds=10) # Cek setiap 10 detik
    async def cleanup_task(self):
        # log.debug("Running TempVoice cleanup task.") # Terlalu banyak log jika setiap 10 detik
        channels_to_remove = []
        for channel_id_str, channel_info in list(self.active_temp_channels.items()): # Gunakan list() untuk iterasi yang aman saat pop
            channel_id = int(channel_id_str) # Konversi ke int untuk fetch channel
            guild = self.bot.get_guild(channel_info["guild_id"])
            
            if not guild:
                log.warning(f"Guild {channel_info['guild_id']} not found for channel {channel_id}. Removing from tracking.")
                channels_to_remove.append(channel_id_str)
                continue

            channel = guild.get_channel(channel_id)
            
            if not channel: # Channel sudah dihapus dari Discord
                log.info(f"Temporary voice channel {channel_id} no longer exists in guild {guild.name}. Removing from tracking.")
                channels_to_remove.append(channel_id_str)
                continue

            # Jika channel kosong (tidak ada member), hapus
            if not channel.members: 
                try:
                    await channel.delete(reason="Temporary voice channel is empty.")
                    log.info(f"Deleted empty temporary voice channel: {channel.name} ({channel_id}).")
                    channels_to_remove.append(channel_id_str)
                except discord.NotFound: # Channel mungkin baru saja dihapus oleh Discord/admin lain
                    log.info(f"Temporary voice channel {channel_id} already deleted (from Discord). Removing from tracking.")
                    channels_to_remove.append(channel_id_str)
                except discord.Forbidden:
                    log.error(f"Bot lacks permissions to delete temporary voice channel {channel.name} ({channel_id}). Please check 'Manage Channels' permission.")
                except Exception as e:
                    log.error(f"Error deleting temporary voice channel {channel.name} ({channel_id}): {e}")
        
        # Hapus channel yang sudah diproses dari daftar aktif
        for ch_id in channels_to_remove:
            self.active_temp_channels.pop(ch_id, None)
        if channels_to_remove: # Hanya simpan jika ada perubahan
            save_temp_channels(self.active_temp_channels)
            log.debug(f"Temporary channel data saved after cleanup. Remaining: {len(self.active_temp_channels)}.")

    @cleanup_task.before_loop
    async def before_cleanup_task(self):
        log.info("Waiting for bot to be ready before starting TempVoice cleanup task.")
        await self.bot.wait_until_ready()
        log.info("Bot ready, TempVoice cleanup task is about to start.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Hanya proses jika user bukan bot
        if member.bot:
            return

        # --- LOGIKA PEMBUATAN CHANNEL BARU ---
        # Cek jika user bergabung ke trigger channel
        if after.channel and after.channel.id == TRIGGER_VOICE_CHANNEL_ID:
            log.info(f"User {member.display_name} ({member.id}) joined trigger VC ({TRIGGER_VOICE_CHANNEL_ID}).")

            # Cek apakah user ini sudah punya channel sementara yang aktif
            # Iterasi melalui self.active_temp_channels untuk mencari channel yang dimiliki user ini
            for ch_id_str, ch_info in list(self.active_temp_channels.items()): # Gunakan list() untuk iterasi aman
                if ch_info["owner_id"] == member.id and ch_info["guild_id"] == member.guild.id:
                    existing_channel = member.guild.get_channel(int(ch_id_str))
                    if existing_channel:
                        log.info(f"User {member.display_name} already has active temporary VC {existing_channel.name}. Moving them there.")
                        try:
                            await member.move_to(existing_channel)
                            return # Selesai, karena user sudah dipindahkan
                        except discord.Forbidden:
                            log.error(f"Bot lacks permissions to move {member.display_name} to their existing VC {existing_channel.name}.")
                            try: await member.send(f"❌ Gagal memindahkan Anda ke channel pribadi Anda: Bot tidak memiliki izin 'Move Members'. Silakan hubungi admin server.")
                            except discord.Forbidden: pass
                            return
                        except Exception as e:
                            log.error(f"Error moving {member.display_name} to existing VC {existing_channel.name}: {e}")
                            try: await member.send(f"❌ Terjadi kesalahan saat memindahkan Anda ke channel pribadi Anda: {e}. Hubungi admin server.")
                            except discord.Forbidden: pass
                            return
                    else: # Channel ada di data tapi tidak ada di Discord, hapus dari tracking
                        log.warning(f"Temporary channel {ch_id_str} in data not found on Discord. Removing from tracking.")
                        self.active_temp_channels.pop(ch_id_str)
                        save_temp_channels(self.active_temp_channels)
                        # Lanjutkan untuk membuat channel baru karena yang lama tidak valid

            guild = member.guild
            category = guild.get_channel(TARGET_CATEGORY_ID)
            
            if not category or not isinstance(category, discord.CategoryChannel):
                log.error(f"Target category {TARGET_CATEGORY_ID} not found or is not a category channel in guild {guild.name}. Skipping VC creation.")
                try: await member.send("❌ Gagal membuat channel suara pribadi: Kategori tujuan tidak ditemukan atau tidak valid. Hubungi admin server.")
                except discord.Forbidden: pass
                try: await member.move_to(None, reason="Target category invalid.")
                except: pass
                return

            current_category_channels = [ch for ch in category.voice_channels if ch.name.startswith(DEFAULT_CHANNEL_NAME_PREFIX)]
            
            next_channel_number = 1
            if current_category_channels:
                max_num = 0
                for ch_obj in current_category_channels:
                    try:
                        parts = ch_obj.name.split()
                        if len(parts) > 1 and parts[-1].isdigit():
                            num = int(parts[-1])
                            if num > max_num:
                                max_num = num
                    except Exception as e:
                        log.warning(f"Could not parse number from channel name {ch_obj.name}: {e}")
                        continue
                next_channel_number = max_num + 1

            new_channel_name = f"{DEFAULT_CHANNEL_NAME_PREFIX} {next_channel_number}"
            
            try:
                everyone_role = guild.default_role
                admin_role = discord.utils.get(guild.roles, permissions=discord.Permissions(administrator=True))
                
                overwrites = {
                    everyone_role: discord.PermissionOverwrite(connect=False, speak=False, send_messages=False, view_channel=False),
                    guild.me: discord.PermissionOverwrite(connect=True, speak=True, send_messages=True, view_channel=True, read_message_history=True)
                }
                
                if admin_role:
                    overwrites[admin_role] = discord.PermissionOverwrite(connect=True, speak=True, send_messages=True, view_channel=True)

                # Dapatkan bitrate maksimal yang diizinkan oleh server
                # guild.bitrate_limit akan otomatis memberikan nilai maksimal sesuai level server (64kbps, 128kbps, atau 256kbps)
                max_bitrate = guild.bitrate_limit # Ini akan langsung mengambil batas bitrate server (misal: 256000 untuk Level 2)
                
                new_vc = await guild.create_voice_channel(
                    name=new_channel_name,
                    category=category,
                    user_limit=0,
                    overwrites=overwrites,
                    bitrate=max_bitrate, # Set bitrate maksimal sesuai batas server
                    reason=f"{member.display_name} created a temporary voice channel."
                )
                log.info(f"Created new temporary VC: {new_vc.name} ({new_vc.id}) by {member.display_name} with bitrate {max_bitrate}.")

                await member.move_to(new_vc)
                log.info(f"Moved {member.display_name} to new VC {new_vc.name}.")

                self.active_temp_channels[str(new_vc.id)] = {"owner_id": member.id, "guild_id": guild.id}
                save_temp_channels(self.active_temp_channels)
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
                log.error(f"Bot lacks permissions to create voice channels or move members in guild {guild.name}. Please check 'Manage Channels' and 'Move Members' permissions.")
                try: await member.send(f"❌ Gagal membuat channel suara pribadi: Bot tidak memiliki izin yang cukup (Manage Channels atau Move Members). Hubungi admin server.")
                except discord.Forbidden: pass
                try: await member.move_to(None, reason="Bot lacks permissions.")
                except: pass
            except Exception as e:
                log.error(f"Unexpected error creating or moving to new VC in guild {guild.name}: {e}", exc_info=True)
                try: await member.send(f"❌ Terjadi kesalahan saat membuat channel suara pribadi: {e}. Hubungi admin server.")
                except discord.Forbidden: pass
                try: await member.move_to(None, reason="Unexpected error.")
                except: pass

        # --- LOGIKA PEMBERSIHAN CHANNEL KETIKA OWNER KELUAR ---
        if before.channel and str(before.channel.id) in self.active_temp_channels:
            channel_info = self.active_temp_channels[str(before.channel.id)]
            if channel_info["owner_id"] == member.id:
                log.info(f"Owner {member.display_name} left temporary VC ({before.channel.name}). Triggering immediate cleanup check.")
                pass 
    
    # --- Command Individual untuk Mengelola Voice Channel Sementara ---
    # is_owner_vc checker method (tetap synchronous karena ini adalah check)
    def is_owner_vc(self, ctx):
        """Check if the user is the owner of the temporary voice channel."""
        # Pastikan user ada di voice channel
        if not ctx.author.voice:
            log.debug(f"is_owner_vc check failed for {ctx.author.display_name}: not in any voice channel.")
            return False
        
        # Pastikan user ada di channel (bukan None)
        if not ctx.author.voice.channel:
            log.debug(f"is_owner_vc check failed for {ctx.author.display_name}: voice.channel is None.")
            return False
        
        channel_id_str = str(ctx.author.voice.channel.id)
        
        # Pastikan channel ID ada dalam daftar channel sementara yang aktif
        if channel_id_str not in self.active_temp_channels:
            log.debug(f"is_owner_vc check failed for {ctx.author.display_name}: channel {channel_id_str} not a tracked temporary VC.")
            return False # Not a tracked temp VC

        # Cek apakah user adalah owner dari channel yang sedang dilacak
        is_owner = self.active_temp_channels[channel_id_str]["owner_id"] == ctx.author.id
        if not is_owner:
            log.debug(f"is_owner_vc check failed for {ctx.author.display_name}: not owner of VC {channel_id_str}. Owner: {self.active_temp_channels[channel_id_str]['owner_id']}.")
        
        return is_owner

    @commands.command(name="vcsetlimit")
    @commands.check(is_owner_vc)
    async def vc_set_limit(self, ctx, limit: int):
        """Atur batas user di channel suara pribadimu (0 untuk tak terbatas)."""
        if limit < 0 or limit > 99:
            return await ctx.send("❌ Batas user harus antara 0 (tak terbatas) hingga 99.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            await vc.edit(user_limit=limit, reason=f"User {ctx.author.display_name} set user limit.")
            await ctx.send(f"✅ Batas user channelmu diatur ke: **{limit if limit > 0 else 'tak terbatas'}**.")
            log.info(f"User {ctx.author.display_name} set user limit to {limit} for VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengubah batas user channel ini. Pastikan bot memiliki izin 'Manage Channels'.", ephemeral=True)
            log.error(f"Bot lacks permissions to set user limit for VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error setting user limit for VC {ctx.author.voice.channel.name}: {e}")

    @commands.command(name="vcrename")
    @commands.check(is_owner_vc)
    async def vc_rename(self, ctx, *, new_name: str):
        """Ubah nama channel suara pribadimu."""
        if len(new_name) < 2 or len(new_name) > 100:
            return await ctx.send("❌ Nama channel harus antara 2 hingga 100 karakter.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            old_name = vc.name
            await vc.edit(name=new_name, reason=f"User {ctx.author.display_name} renamed VC.")
            await ctx.send(f"✅ Nama channelmu diubah dari **{old_name}** menjadi **{new_name}**.")
            log.info(f"User {ctx.author.display_name} renamed VC from {old_name} to {new_name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengubah nama channel ini. Pastikan bot memiliki izin 'Manage Channels'.", ephemeral=True)
            log.error(f"Bot lacks permissions to rename VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error renaming VC {ctx.author.voice.channel.name}: {e}")

    @commands.command(name="vclock")
    @commands.check(is_owner_vc)
    async def vc_lock(self, ctx):
        """Kunci channel suara pribadimu (hanya bisa masuk via invite/grant)."""
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(ctx.guild.default_role, connect=False, reason=f"User {ctx.author.display_name} locked VC.")
            await ctx.send(f"✅ Channel **{vc.name}** telah dikunci. Hanya user dengan izin khusus yang bisa bergabung.")
            log.info(f"User {ctx.author.display_name} locked VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengunci channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to lock VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error locking VC {ctx.author.voice.channel.name}: {e}")

    @commands.command(name="vcunlock")
    @commands.check(is_owner_vc)
    async def vc_unlock(self, ctx):
        """Buka kunci channel suara pribadimu."""
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(ctx.guild.default_role, connect=True, speak=True, send_messages=True, reason=f"User {ctx.author.display_name} unlocked VC.")
            await ctx.send(f"✅ Channel **{vc.name}** telah dibuka. Sekarang siapa pun bisa bergabung, berbicara, dan mengirim pesan.")
            log.info(f"User {ctx.author.display_name} unlocked VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk membuka kunci channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to unlock VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error unlocking VC {ctx.author.voice.channel.name}: {e}")

    @commands.command(name="vckick")
    @commands.check(is_owner_vc)
    async def vc_kick(self, ctx, member: discord.Member):
        """Tendang user dari channel suara pribadimu."""
        if member.id == ctx.author.id:
            return await ctx.send("❌ Kamu tidak bisa menendang dirimu sendiri dari channelmu!", ephemeral=True)
        if member.bot:
            return await ctx.send("❌ Kamu tidak bisa menendang bot.", ephemeral=True)
        
        vc = ctx.author.voice.channel
        if member.voice and member.voice.channel == vc:
            try:
                await member.move_to(None, reason=f"Kicked by VC owner {ctx.author.display_name}.")
                await ctx.send(f"✅ **{member.display_name}** telah ditendang dari channelmu.")
                log.info(f"VC owner {ctx.author.display_name} kicked {member.display_name} from {vc.name}.")
            except discord.Forbidden:
                await ctx.send("❌ Bot tidak memiliki izin untuk menendang pengguna ini. Pastikan bot memiliki izin 'Move Members'.", ephemeral=True)
                log.error(f"Bot lacks permissions to kick {member.display_name} from VC {vc.name}.")
            except Exception as e:
                await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
                log.error(f"Error kicking {member.display_name} from VC {vc.name}: {e}")
        else:
            await ctx.send("❌ Pengguna tersebut tidak berada di channelmu.", ephemeral=True)

    @commands.command(name="vcgrant")
    @commands.check(is_owner_vc)
    async def vc_grant(self, ctx, member: discord.Member):
        """Berikan user izin masuk channelmu yang terkunci."""
        if member.bot:
            return await ctx.send("❌ Kamu tidak bisa memberikan izin ke bot.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(member, connect=True, reason=f"VC owner {ctx.author.display_name} granted access.")
            await ctx.send(f"✅ **{member.display_name}** sekarang memiliki izin untuk bergabung ke channelmu.")
            log.info(f"VC owner {ctx.author.display_name} granted access to {member.display_name} for VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk memberikan izin di channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to grant access for VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error granting access for VC {ctx.author.voice.channel.name}: {e}")

    @commands.command(name="vcrevoke")
    @commands.check(is_owner_vc)
    async def vc_revoke(self, ctx, member: discord.Member):
        """Cabut izin masuk user dari channelmu yang terkunci."""
        if member.bot:
            return await ctx.send("❌ Kamu tidak bisa mencabut izin dari bot.", ephemeral=True)
        try:
            vc = ctx.author.voice.channel
            await vc.set_permissions(member, connect=False, reason=f"VC owner {ctx.author.display_name} revoked access.")
            await ctx.send(f"✅ Izin **{member.display_name}** untuk bergabung ke channelmu telah dicabut.")
            log.info(f"VC owner {ctx.author.display_name} revoked access from {member.display_name} for VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mencabut izin di channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to revoke access for VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error revoking access for VC {ctx.author.voice.channel.name}: {e}")

    @commands.command(name="vcowner")
    @commands.check(is_owner_vc)
    async def vc_transfer_owner(self, ctx, new_owner: discord.Member):
        """Transfer kepemilikan channelmu ke user lain."""
        vc_id_str = str(ctx.author.voice.channel.id)
        if new_owner.bot:
            return await ctx.send("❌ Kamu tidak bisa mentransfer kepemilikan ke bot.", ephemeral=True)
        if new_owner.id == ctx.author.id:
            return await ctx.send("❌ Kamu sudah menjadi pemilik channel ini!", ephemeral=True)

        self.active_temp_channels[vc_id_str]["owner_id"] = new_owner.id
        save_temp_channels(self.active_temp_channels)
        
        await ctx.send(f"✅ Kepemilikan channel **{ctx.author.voice.channel.name}** telah ditransfer dari {ctx.author.mention} ke {new_owner.mention}!")
        log.info(f"VC ownership transferred from {ctx.author.display_name} to {new_owner.display_name} for VC {ctx.author.voice.channel.name}.")

        try:
            await new_owner.send(
                f"🎉 Selamat! Anda sekarang adalah pemilik channel suara **{ctx.author.voice.channel.name}** di server **{ctx.guild.name}**!\n"
                f"Gunakan perintah `!vchelp` untuk melihat cara mengelola channel ini."
            )
        except discord.Forbidden:
            log.warning(f"Could not send ownership transfer DM to {new_owner.display_name} (DMs closed).")

    @commands.command(name="vchelp")
    async def vc_help(self, ctx):
        """Menampilkan daftar perintah untuk mengelola channel suara pribadi."""
        embed = discord.Embed(
            title="🎧 Panduan Channel Suara Pribadi 🎧",
            description="""
            Saat kamu bergabung ke **Channel Khusus Buat VC Baru**, bot akan otomatis membuat channel suara baru untukmu!
            Kamu akan menjadi pemilik channel tersebut dan punya kendali penuh atasnya.

            **Perintah yang bisa kamu gunakan (harus di channel pribadimu):**
            """,
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Manajemen Channel:", value="""
        `!vcsetlimit <angka>`: Atur batas jumlah user yang bisa masuk (0 untuk tak terbatas). Contoh: `!vcsetlimit 5`
        `!vcrename <nama_baru>`: Ubah nama channel suaramu. Contoh: `!vcrename My Secret Base`
        `!vclock`: Kunci channelmu agar hanya user dengan izin yang bisa masuk (via `!vcgrant`).
        `!vcunlock`: Buka kunci channelmu agar siapa pun bisa masuk.
        """, inline=False)

        embed.add_field(name="Manajemen User:", value="""
        `!vckick @user`: Tendang user dari channelmu. Contoh: `!vckick @TemanGanggu`
        `!vcgrant @user`: Beri user izin masuk channelmu yang terkunci. Contoh: `!vcgrant @TemanBaik`
        `!vcrevoke @user`: Cabut izin user dari channelmu yang terkunci. Contoh: `!vcrevoke @TemanJahat`
        `!vcowner @user`: Transfer kepemilikan channel ke user lain. Contoh: `!vcowner @CalonOwnerBaru`
        """, inline=False)
        
        embed.set_footer(text="Ingat, channel pribadimu akan otomatis terhapus jika kosong!")
        await ctx.send(embed=embed)
        log.info(f"Sent VC help message to {ctx.author.display_name}.")

    # --- Error Handlers untuk command vc tanpa spasi ---
    # Global error handler untuk cog ini yang akan menangkap semua error dari command
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        # Hanya tangani error dari command yang dimiliki oleh cog ini
        if ctx.cog != self:
            return

        # Tangani Commands.CheckFailure untuk is_owner_vc
        if isinstance(error, commands.CheckFailure):
            if not ctx.author.voice or not ctx.author.voice.channel or str(ctx.author.voice.channel.id) not in self.active_temp_channels:
                await ctx.send("❌ Kamu harus berada di channel suara pribadi yang kamu miliki untuk menggunakan perintah ini.", ephemeral=True)
            else:
                await ctx.send("❌ Kamu harus menjadi pemilik channel ini untuk menggunakan perintah ini.", ephemeral=True)
            log.warning(f"User {ctx.author.display_name} tried to use VC command but failed check: {error}")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Argumen tidak lengkap. Contoh penggunaan: `!{ctx.command.name} {ctx.command.signature}`", ephemeral=True)
            log.warning(f"Missing argument for {ctx.command.name} from {ctx.author.display_name}. Error: {error}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Argumen tidak valid. Pastikan kamu menyebutkan user yang benar atau angka yang valid.", ephemeral=True)
            log.warning(f"Bad argument for {ctx.command.name} from {ctx.author.display_name}. Error: {error}")
        elif isinstance(error, discord.Forbidden):
            await ctx.send("❌ Bot tidak memiliki izin untuk melakukan tindakan ini. Pastikan role bot berada di atas role lain dan memiliki izin yang diperlukan (misal: 'Manage Channels', 'Move Members', 'Manage Permissions').", ephemeral=True)
            log.error(f"Bot forbidden from performing VC action in guild {ctx.guild.name}. Error: {error}")
        else:
            # Ini akan menangkap error yang tidak spesifik ditangani di atas
            await ctx.send(f"❌ Terjadi kesalahan pada perintah: {error}", ephemeral=True)
            log.error(f"Unhandled error in VC command {ctx.command.name} by {ctx.author.display_name}: {error}", exc_info=True)


async def setup(bot):
    await bot.add_cog(TempVoice(bot))
