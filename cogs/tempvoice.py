import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
import logging

log = logging.getLogger(__name__)

# --- KONFIGURASI ---
# Ganti dengan ID Voice Channel pemicu (tempat user bergabung untuk membuat VC baru)
TRIGGER_VOICE_CHANNEL_ID = 1382486705113927811 
# Ganti dengan ID Kategori tempat Voice Channel baru akan dibuat
TARGET_CATEGORY_ID = 1255211613326278716
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
            return {int(k) if k.isdigit() else k: v for k, v in data.items()}
    except json.JSONDecodeError as e:
        log.error(f"Failed to load {TEMP_CHANNELS_FILE}: {e}. Returning empty dict.")
        return {}

def save_temp_channels(data):
    os.makedirs('data', exist_ok=True) # Ensure data dir exists
    with open(TEMP_CHANNELS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


class TempVoice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.active_temp_channels: {channel_id: {"owner_id": int, "guild_id": int}}
        self.active_temp_channels = load_temp_channels() 
        log.info(f"TempVoice cog loaded. Active temporary channels: {self.active_temp_channels}")
        self.cleanup_task.start() # Mulai task cleanup

    def cog_unload(self):
        log.info("TempVoice cog unloaded. Cancelling cleanup task.")
        self.cleanup_task.cancel()

    @tasks.loop(seconds=10) # Cek setiap 10 detik
    async def cleanup_task(self):
        # log.debug("Running TempVoice cleanup task.")
        channels_to_remove = []
        for channel_id_str, channel_info in list(self.active_temp_channels.items()):
            channel_id = int(channel_id_str) # Pastikan channel_id adalah integer
            guild = self.bot.get_guild(channel_info["guild_id"])
            
            if not guild:
                log.warning(f"Guild {channel_info['guild_id']} not found for channel {channel_id}. Removing from tracking.")
                channels_to_remove.append(channel_id_str)
                continue

            channel = guild.get_channel(channel_id)
            
            if not channel:
                log.info(f"Temporary voice channel {channel_id} no longer exists in guild {guild.name}. Removing from tracking.")
                channels_to_remove.append(channel_id_str)
                continue

            # Jika channel kosong, hapus langsung
            if not channel.members: # Jika tidak ada member di channel
                try:
                    await channel.delete(reason="Temporary voice channel is empty.")
                    log.info(f"Deleted empty temporary voice channel: {channel.name} ({channel_id}).")
                    channels_to_remove.append(channel_id_str)
                except discord.NotFound:
                    log.info(f"Temporary voice channel {channel_id} already deleted (from Discord). Removing from tracking.")
                    channels_to_remove.append(channel_id_str)
                except discord.Forbidden:
                    log.error(f"Bot lacks permissions to delete temporary voice channel {channel.name} ({channel_id}).")
                except Exception as e:
                    log.error(f"Error deleting temporary voice channel {channel.name} ({channel_id}): {e}")
        
        # Hapus channel yang sudah dihapus dari daftar aktif
        for ch_id in channels_to_remove:
            self.active_temp_channels.pop(ch_id, None)
        if channels_to_remove:
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

        # Cek jika user bergabung ke trigger channel
        if after.channel and after.channel.id == TRIGGER_VOICE_CHANNEL_ID:
            log.info(f"User {member.display_name} joined trigger VC ({TRIGGER_VOICE_CHANNEL_ID}).")

            guild = member.guild
            category = guild.get_channel(TARGET_CATEGORY_ID)
            
            if not category or not isinstance(category, discord.CategoryChannel):
                log.error(f"Target category {TARGET_CATEGORY_ID} not found or is not a category channel in guild {guild.name}.")
                try: await member.send("❌ Gagal membuat channel suara pribadi: Kategori tujuan tidak ditemukan atau tidak valid. Hubungi admin server.")
                except discord.Forbidden: pass # If DM fails
                try: await member.move_to(None) # Disconnect user
                except: pass
                return

            # Cari nomor channel kosong berikutnya
            existing_temp_channels_in_guild = [ch for ch_id, ch in self.active_temp_channels.items() if ch["guild_id"] == guild.id]
            next_channel_number = 1
            if existing_temp_channels_in_guild:
                # Dapatkan nomor tertinggi dari channel yang aktif di guild ini
                max_num = 0
                for ch_id_str, ch_info in existing_temp_channels_in_guild:
                    try:
                        # Asumsi format nama "Music X"
                        ch_obj = guild.get_channel(int(ch_id_str))
                        if ch_obj and ch_obj.name.startswith(DEFAULT_CHANNEL_NAME_PREFIX):
                            parts = ch_obj.name.split()
                            if len(parts) > 1 and parts[-1].isdigit():
                                num = int(parts[-1])
                                if num > max_num:
                                    max_num = num
                    except Exception as e:
                        log.warning(f"Could not parse number from temp channel name {ch_obj.name} ({ch_id_str}): {e}")
                        continue
                next_channel_number = max_num + 1

            new_channel_name = f"{DEFAULT_CHANNEL_NAME_PREFIX} {next_channel_number}"
            
            # Buat voice channel baru
            try:
                new_vc = await guild.create_voice_channel(
                    name=new_channel_name,
                    category=category,
                    user_limit=0, # Default unlimited, can be changed by owner
                    reason=f"{member.display_name} created a temporary voice channel."
                )
                log.info(f"Created new temporary VC: {new_vc.name} ({new_vc.id}) by {member.display_name}.")

                # Pindahkan user ke channel baru
                await member.move_to(new_vc)
                log.info(f"Moved {member.display_name} to new VC {new_vc.name}.")

                # Simpan channel di daftar aktif
                self.active_temp_channels[str(new_vc.id)] = {"owner_id": member.id, "guild_id": guild.id}
                save_temp_channels(self.active_temp_channels)
                log.debug(f"Temporary VC {new_vc.id} added to tracking.")

                # Beri tahu user tentang command kontrol
                await new_vc.send(
                    f"🎉 Selamat datang di channel pribadimu, {member.mention}! Kamu adalah pemilik channel ini.\n"
                    f"Gunakan perintah di bawah untuk mengelola channel-mu:\n"
                    f"`!vc setlimit <angka>` - Atur batas user (0 untuk tak terbatas)\n"
                    f"`!vc rename <nama_baru>` - Ubah nama channel\n"
                    f"`!vc lock` - Kunci channel (hanya bisa masuk via invite)\n"
                    f"`!vc unlock` - Buka kunci channel\n"
                    f"`!vc kick @user` - Tendang user dari channel\n"
                    f"`!vc grant @user` - Beri user izin masuk channel yang terkunci\n"
                    f"`!vc revoke @user` - Cabut izin masuk channel yang terkunci\n"
                    f"`!vc owner @user` - Transfer kepemilikan channel ke user lain (hanya bisa 1 pemilik)"
                )

            except discord.Forbidden:
                log.error(f"Bot lacks permissions to create voice channels or move members in guild {guild.name}.")
                try: await member.send("❌ Gagal membuat channel suara pribadi: Bot tidak memiliki izin yang cukup (Manage Channels atau Move Members). Hubungi admin server.")
                except discord.Forbidden: pass
                try: await member.move_to(None)
                except: pass
            except Exception as e:
                log.error(f"Unexpected error creating or moving to new VC in guild {guild.name}: {e}")
                try: await member.send(f"❌ Terjadi kesalahan saat membuat channel suara pribadi: {e}. Hubungi admin server.")
                except discord.Forbidden: pass
                try: await member.move_to(None)
                except: pass

        # Cek jika user keluar dari channel sementara yang dimiliki
        elif before.channel and str(before.channel.id) in self.active_temp_channels:
            channel_info = self.active_temp_channels[str(before.channel.id)]
            # If the owner leaves the channel, and the channel becomes empty, it will be cleaned up by cleanup_task
            # If channel becomes empty due to ANYONE leaving, cleanup_task will delete it instantly.
            log.debug(f"User {member.display_name} left temporary VC ({before.channel.name}). Cleanup task will check if empty.")

        # Jika user keluar dari trigger channel tanpa membuat channel baru, abaikan
        # Jika user pindah dari channel sementara ke channel lain, cleanup_task akan menangani channel kosong.
    
    # --- Command Group untuk Mengelola Voice Channel Sementara ---
    @commands.group(name="vc", invoke_without_command=True)
    async def vc_group(self, ctx):
        """Kumpulan perintah untuk mengelola channel suara pribadi Anda."""
        await ctx.send("Gunakan `!vc help` untuk melihat semua perintah pengelolaan channel pribadi.", ephemeral=True)

    def is_owner_vc(self, ctx):
        """Check if the user is the owner of the temporary voice channel."""
        channel_id_str = str(ctx.author.voice.channel.id) if ctx.author.voice and ctx.author.voice.channel else None
        
        if not channel_id_str or channel_id_str not in self.active_temp_channels:
            return False # Not in a tracked temp VC

        return self.active_temp_channels[channel_id_str]["owner_id"] == ctx.author.id

    @vc_group.command(name="setlimit")
    @commands.check(is_owner_vc)
    async def set_limit(self, ctx, limit: int):
        """Atur batas user di channel suara pribadimu (0 untuk tak terbatas)."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ Kamu harus berada di channel suara pribadimu untuk menggunakan perintah ini.", ephemeral=True)
        
        if limit < 0 or limit > 99:
            return await ctx.send("❌ Batas user harus antara 0 (tak terbatas) hingga 99.", ephemeral=True)
        
        try:
            await ctx.author.voice.channel.edit(user_limit=limit, reason=f"User {ctx.author.display_name} set user limit.")
            await ctx.send(f"✅ Batas user channelmu diatur ke: **{limit if limit > 0 else 'tak terbatas'}**.")
            log.info(f"User {ctx.author.display_name} set user limit to {limit} for VC {ctx.author.voice.channel.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengubah batas user channel ini. Pastikan bot memiliki izin 'Manage Channels'.", ephemeral=True)
            log.error(f"Bot lacks permissions to set user limit for VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error setting user limit for VC {ctx.author.voice.channel.name}: {e}")

    @vc_group.command(name="rename")
    @commands.check(is_owner_vc)
    async def rename_vc(self, ctx, *, new_name: str):
        """Ubah nama channel suara pribadimu."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ Kamu harus berada di channel suara pribadimu untuk menggunakan perintah ini.", ephemeral=True)
        
        if len(new_name) < 2 or len(new_name) > 100:
            return await ctx.send("❌ Nama channel harus antara 2 hingga 100 karakter.", ephemeral=True)
        
        try:
            old_name = ctx.author.voice.channel.name
            await ctx.author.voice.channel.edit(name=new_name, reason=f"User {ctx.author.display_name} renamed VC.")
            await ctx.send(f"✅ Nama channelmu diubah dari **{old_name}** menjadi **{new_name}**.")
            log.info(f"User {ctx.author.display_name} renamed VC from {old_name} to {new_name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengubah nama channel ini. Pastikan bot memiliki izin 'Manage Channels'.", ephemeral=True)
            log.error(f"Bot lacks permissions to rename VC {ctx.author.voice.channel.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error renaming VC {ctx.author.voice.channel.name}: {e}")

    @vc_group.command(name="lock")
    @commands.check(is_owner_vc)
    async def lock_vc(self, ctx):
        """Kunci channel suara pribadimu (hanya bisa masuk via invite/grant)."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ Kamu harus berada di channel suara pribadimu untuk menggunakan perintah ini.", ephemeral=True)
        
        vc = ctx.author.voice.channel
        try:
            # Deny @everyone connect permission
            await vc.set_permissions(ctx.guild.default_role, connect=False, reason=f"User {ctx.author.display_name} locked VC.")
            await ctx.send(f"✅ Channel **{vc.name}** telah dikunci. Hanya user dengan izin khusus yang bisa bergabung.")
            log.info(f"User {ctx.author.display_name} locked VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mengunci channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to lock VC {vc.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error locking VC {vc.name}: {e}")

    @vc_group.command(name="unlock")
    @commands.check(is_owner_vc)
    async def unlock_vc(self, ctx):
        """Buka kunci channel suara pribadimu."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ Kamu harus berada di channel suara pribadimu untuk menggunakan perintah ini.", ephemeral=True)
        
        vc = ctx.author.voice.channel
        try:
            # Allow @everyone connect permission
            await vc.set_permissions(ctx.guild.default_role, connect=True, reason=f"User {ctx.author.display_name} unlocked VC.")
            await ctx.send(f"✅ Channel **{vc.name}** telah dibuka. Sekarang siapa pun bisa bergabung.")
            log.info(f"User {ctx.author.display_name} unlocked VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk membuka kunci channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to unlock VC {vc.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error unlocking VC {vc.name}: {e}")

    @vc_group.command(name="kick")
    @commands.check(is_owner_vc)
    async def kick_vc(self, ctx, member: discord.Member):
        """Tendang user dari channel suara pribadimu."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ Kamu harus berada di channel suara pribadimu untuk menggunakan perintah ini.", ephemeral=True)
        
        vc = ctx.author.voice.channel
        if member.id == ctx.author.id:
            return await ctx.send("❌ Kamu tidak bisa menendang dirimu sendiri dari channelmu!", ephemeral=True)
        if member.bot:
            return await ctx.send("❌ Kamu tidak bisa menendang bot.", ephemeral=True)
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

    @vc_group.command(name="grant")
    @commands.check(is_owner_vc)
    async def grant_vc(self, ctx, member: discord.Member):
        """Berikan user izin masuk channelmu yang terkunci."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ Kamu harus berada di channel suara pribadimu untuk menggunakan perintah ini.", ephemeral=True)
        
        vc = ctx.author.voice.channel
        if member.bot:
            return await ctx.send("❌ Kamu tidak bisa memberikan izin ke bot.", ephemeral=True)
        try:
            await vc.set_permissions(member, connect=True, reason=f"VC owner {ctx.author.display_name} granted access.")
            await ctx.send(f"✅ **{member.display_name}** sekarang memiliki izin untuk bergabung ke channelmu.")
            log.info(f"VC owner {ctx.author.display_name} granted access to {member.display_name} for VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk memberikan izin di channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to grant access for VC {vc.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error granting access for VC {vc.name}: {e}")

    @vc_group.command(name="revoke")
    @commands.check(is_owner_vc)
    async def revoke_vc(self, ctx, member: discord.Member):
        """Cabut izin masuk user dari channelmu yang terkunci."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ Kamu harus berada di channel suara pribadimu untuk menggunakan perintah ini.", ephemeral=True)
        
        vc = ctx.author.voice.channel
        if member.bot:
            return await ctx.send("❌ Kamu tidak bisa mencabut izin dari bot.", ephemeral=True)
        try:
            # Overwrite connect permission to False, if not explicitly denied, will fallback to @everyone
            await vc.set_permissions(member, connect=False, reason=f"VC owner {ctx.author.display_name} revoked access.")
            await ctx.send(f"✅ Izin **{member.display_name}** untuk bergabung ke channelmu telah dicabut.")
            log.info(f"VC owner {ctx.author.display_name} revoked access from {member.display_name} for VC {vc.name}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot tidak memiliki izin untuk mencabut izin di channel ini. Pastikan bot memiliki izin 'Manage Permissions'.", ephemeral=True)
            log.error(f"Bot lacks permissions to revoke access for VC {vc.name}.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {e}", ephemeral=True)
            log.error(f"Error revoking access for VC {vc.name}: {e}")

    @vc_group.command(name="owner")
    @commands.check(is_owner_vc)
    async def transfer_owner(self, ctx, new_owner: discord.Member):
        """Transfer kepemilikan channelmu ke user lain."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ Kamu harus berada di channel suara pribadimu untuk menggunakan perintah ini.", ephemeral=True)
        
        vc_id_str = str(ctx.author.voice.channel.id)
        if new_owner.bot:
            return await ctx.send("❌ Kamu tidak bisa mentransfer kepemilikan ke bot.", ephemeral=True)
        if new_owner.id == ctx.author.id:
            return await ctx.send("❌ Kamu sudah menjadi pemilik channel ini!", ephemeral=True)

        # Update owner di tracking
        self.active_temp_channels[vc_id_str]["owner_id"] = new_owner.id
        save_temp_channels(self.active_temp_channels)
        
        # Beri tahu owner lama dan baru
        await ctx.send(f"✅ Kepemilikan channel **{ctx.author.voice.channel.name}** telah ditransfer dari {ctx.author.mention} ke {new_owner.mention}!")
        log.info(f"VC ownership transferred from {ctx.author.display_name} to {new_owner.display_name} for VC {ctx.author.voice.channel.name}.")

        # Beri tahu owner baru tentang command
        try:
            await new_owner.send(
                f"🎉 Selamat! Anda sekarang adalah pemilik channel suara **{ctx.author.voice.channel.name}** di server **{ctx.guild.name}**!\n"
                f"Gunakan perintah `!vc help` untuk melihat cara mengelola channel ini."
            )
        except discord.Forbidden:
            log.warning(f"Could not send ownership transfer DM to {new_owner.display_name} (DMs closed).")

    @vc_group.command(name="help")
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
        `!vc setlimit <angka>`: Atur batas jumlah user yang bisa masuk (0 untuk tak terbatas). Contoh: `!vc setlimit 5`
        `!vc rename <nama_baru>`: Ubah nama channel suaramu. Contoh: `!vc rename My Secret Base`
        `!vc lock`: Kunci channelmu agar hanya user dengan izin yang bisa masuk (via `!vc grant`).
        `!vc unlock`: Buka kunci channelmu agar siapa pun bisa masuk.
        """, inline=False)

        embed.add_field(name="Manajemen User:", value="""
        `!vc kick @user`: Tendang user dari channelmu. Contoh: `!vc kick @TemanGanggu`
        `!vc grant @user`: Beri user izin masuk channelmu yang terkunci. Contoh: `!vc grant @TemanBaik`
        `!vc revoke @user`: Cabut izin user dari channelmu yang terkunci. Contoh: `!vc revoke @TemanJahat`
        `!vc owner @user`: Transfer kepemilikan channel ke user lain. Contoh: `!vc owner @CalonOwnerBaru`
        """, inline=False)
        
        embed.set_footer(text="Ingat, channel pribadimu akan otomatis terhapus jika kosong!")
        await ctx.send(embed=embed)
        log.info(f"Sent VC help message to {ctx.author.display_name}.")

    @vc_group.error
    @set_limit.error
    @rename_vc.error
    @lock_vc.error
    @unlock_vc.error
    @kick_vc.error
    @grant_vc.error
    @revoke_vc.error
    @transfer_owner.error
    async def vc_command_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("❌ Kamu harus berada di channel suara pribadi yang kamu miliki untuk menggunakan perintah ini.", ephemeral=True)
            log.warning(f"User {ctx.author.display_name} tried to use VC command but is not owner/in VC.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Argumen tidak lengkap. Contoh: `{ctx.command.usage}`", ephemeral=True)
            log.warning(f"Missing argument for {ctx.command.name} from {ctx.author.display_name}.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Argumen tidak valid. Pastikan kamu menyebutkan user yang benar atau angka yang valid.", ephemeral=True)
            log.warning(f"Bad argument for {ctx.command.name} from {ctx.author.display_name}.")
        else:
            await ctx.send(f"❌ Terjadi kesalahan pada perintah: {error}", ephemeral=True)
            log.error(f"Unhandled error in VC command {ctx.command.name} by {ctx.author.display_name}: {error}")
            
async def setup(bot):
    await bot.add_cog(TempVoice(bot))
