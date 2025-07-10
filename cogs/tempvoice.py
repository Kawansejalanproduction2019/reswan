import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# --- KONFIGURASI ---
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
        with open(TEMP_CHANNels_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Konversi string ID kembali ke int jika perlu, atau pastikan selalu string
            return {str(k): v for k, v in data.items()} # Simpan sebagai string key
    except json.JSONDecodeError as e:
        log.error(f"Failed to load {TEMP_CHANNELS_FILE}: {e}. File might be corrupted. Attempting to reset it.")
        # Reset file jika korup
        with open(TEMP_CHANNELS_FILE, 'w', encoding='utf-8') as f:
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
        self.active_temp_channels = load_temp_channels() # {guild_id_str: {channel_id_str: {"owner_id": str, "guild_id": str, "is_creator_channel": bool}}}
        log.info(f"TempVoice cog loaded. Active temporary channels: {self.active_temp_channels}")
        self.cleanup_task.start()

    def _save_temp_channels_state(self):
        save_temp_channels(self.active_temp_channels)
        log.debug("Temporary channel state saved.")

    def cog_unload(self):
        log.info("TempVoice cog unloaded. Cancelling cleanup task.")
        self.cleanup_task.cancel()

    @tasks.loop(seconds=10) # Cek setiap 10 detik
    async def cleanup_task(self):
        log.debug("Running cleanup task for temporary voice channels.")
        channels_to_remove_from_guilds = []
        for guild_id_str in list(self.active_temp_channels.keys()):
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                log.info(f"Guild {guild_id_str} not found, removing all its temp channel data.")
                channels_to_remove_from_guilds.append(guild_id_str)
                continue

            for channel_id_str, channel_info in list(self.active_temp_channels[guild_id_str].items()):
                channel = guild.get_channel(int(channel_id_str))
                
                # If channel is a creator channel, skip deletion
                if channel_info.get("is_creator_channel", False):
                    continue

                if not channel: # Channel tidak ditemukan di Discord, hapus dari tracking
                    log.info(f"Temp channel {channel_id_str} not found in Discord, removing from state.")
                    self.active_temp_channels[guild_id_str].pop(channel_id_str, None)
                    continue

                # Delete if empty (and not a creator channel)
                if not channel.members: 
                    try:
                        await channel.delete(reason="Temporary voice channel is empty.")
                        self.active_temp_channels[guild_id_str].pop(channel_id_str, None)
                        log.info(f"Deleted empty temp channel: {channel.name} ({channel.id}).")
                    except discord.NotFound:
                        self.active_temp_channels[guild_id_str].pop(channel_id_str, None)
                        log.info(f"Temp channel {channel.name} already deleted, removing from state.")
                    except discord.Forbidden:
                        log.warning(f"Bot lacks permissions to delete temp channel {channel.name} ({channel.id}). Please check 'Manage Channels' permission.")
                    except Exception as e:
                        log.error(f"Error deleting temp channel {channel.name} ({channel.id}): {e}", exc_info=True)
            
            # If a guild no longer has any tracked channels (temp or creator), remove it from active_temp_channels
            if not self.active_temp_channels.get(guild_id_str):
                channels_to_remove_from_guilds.append(guild_id_str)
        
        for g_id in channels_to_remove_from_guilds:
            self.active_temp_channels.pop(g_id, None)
        self._save_temp_channels_state()
        log.debug(f"Temporary channel data saved after cleanup. Remaining: {len(self.active_temp_channels)} guilds tracked.")

    @cleanup_task.before_loop
    async def before_cleanup_task(self):
        log.info("Waiting for bot to be ready before starting TempVoice cleanup task.")
        await self.bot.wait_until_ready()
        log.info("Bot ready, TempVoice cleanup task is about to start.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        guild_id_str = str(member.guild.id)
        
        is_creator_channel_join = False
        creator_channel_obj = None

        if after.channel: # User joined a channel
            if guild_id_str in self.active_temp_channels:
                for ch_id, ch_info in self.active_temp_channels[guild_id_str].items():
                    if ch_info.get("is_creator_channel", False) and int(ch_id) == after.channel.id:
                        is_creator_channel_join = True
                        creator_channel_obj = after.channel
                        break
        
        if is_creator_channel_join:
            log.info(f"User {member.display_name} joined creator channel {creator_channel_obj.name}.")
            
            # Prevent user from creating multiple channels
            for ch_id_str, ch_info in self.active_temp_channels.get(guild_id_str, {}).items():
                if ch_info.get("owner_id") == str(member.id) and not ch_info.get("is_creator_channel", False):
                    existing_channel = member.guild.get_channel(int(ch_id_str))
                    if existing_channel:
                        log.info(f"User {member.display_name} already has temp channel {existing_channel.name}. Moving back.")
                        try:
                            await member.move_to(existing_channel)
                            return # Selesai, karena user sudah dipindahkan
                        except discord.Forbidden:
                            log.warning(f"Bot lacks permissions to move {member.display_name} to their existing VC {existing_channel.name}.")
                            try: await member.send(f"❌ Gagal memindahkan Anda ke channel pribadi Anda: Bot tidak memiliki izin 'Pindahkan Anggota'. Silakan hubungi admin server.")
                            except discord.Forbidden: pass
                            return
                        except Exception as e:
                            log.error(f"Error moving {member.display_name} to existing VC {existing_channel.name}: {e}", exc_info=True)
                            try: await member.send(f"❌ Terjadi kesalahan saat memindahkan Anda ke channel pribadi Anda. Hubungi admin server.")
                            except discord.Forbidden: pass
                            return
                    else: # Channel ada di data tapi tidak ada di Discord, hapus dari tracking
                        self.active_temp_channels[guild_id_str].pop(ch_id_str, None)
                        self._save_temp_channels_state() 
                        log.info(f"Cleaned up stale temp channel data for {member.display_name}.")
                        # Lanjutkan untuk membuat channel baru karena yang lama tidak valid

            # Create new temp channel
            category = creator_channel_obj.category

            if not category or not isinstance(category, discord.CategoryChannel):
                log.error(f"Creator channel {creator_channel_obj.name} ({creator_channel_obj.id}) in guild {member.guild.name} is not in a valid category. Skipping VC creation.")
                try: await member.send("❌ Gagal membuat channel suara pribadi: Kategori tujuan tidak ditemukan atau tidak valid. Hubungi admin server.")
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
                        # Improved parsing to handle "Music 1", "Music Channel 2" etc.
                        parts = ch_obj.name.rsplit(' ', 1) # Split only on the last space
                        if len(parts) > 1 and parts[-1].isdigit():
                            num = int(parts[-1])
                            if num > max_num: max_num = num
                    except: pass
                next_channel_number = max_num + 1

            new_channel_name = f"{self.DEFAULT_CHANNEL_NAME_PREFIX} {next_channel_number}"
            
            try:
                everyone_role = member.guild.default_role
                admin_role = discord.utils.get(member.guild.roles, permissions=discord.Permissions(administrator=True))
                
                overwrites = {
                    everyone_role: discord.PermissionOverwrite(connect=False, speak=False, send_messages=False, view_channel=False),
                    member.guild.me: discord.PermissionOverwrite(connect=True, speak=True, send_messages=True, view_channel=True, read_message_history=True)
                }
                if admin_role: overwrites[admin_role] = discord.PermissionOverwrite(connect=True, speak=True, send_messages=True, view_channel=True)
                
                # Allow the creating member to connect, speak, and manage their own channel
                overwrites[member] = discord.PermissionOverwrite(connect=True, speak=True, send_messages=True, view_channel=True,
                                                                 manage_channels=True, manage_roles=True,
                                                                 mute_members=True, deafen_members=True, move_members=True)


                max_bitrate = member.guild.bitrate_limit if member.guild.bitrate_limit else 64000
                
                new_vc = await category.create_voice_channel(
                    name=new_channel_name,
                    user_limit=0,
                    overwrites=overwrites,
                    bitrate=max_bitrate,
                    reason=f"{member.display_name} created a temporary voice channel."
                )
                log.info(f"Created new temp VC: {new_vc.name} ({new_vc.id}) for {member.display_name} with bitrate {max_bitrate}.")

                await member.move_to(new_vc)
                log.info(f"Moved {member.display_name} to new VC {new_vc.name}.")

                # Store new channel info in active_temp_channels
                self.active_temp_channels.setdefault(guild_id_str, {})[str(new_vc.id)] = {
                    "owner_id": str(member.id), 
                    "guild_id": guild_id_str,
                    "is_creator_channel": False 
                }
                self._save_temp_channels_state() 

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
                log.warning(f"Bot lacks permissions to create VC or move members in {member.guild.name}.")
                try: await member.send("❌ Gagal membuat channel pribadi: Bot tidak memiliki izin yang cukup. Pastikan saya memiliki izin 'Kelola Saluran' dan 'Pindahkan Anggota' di kategori tempat channel ini dibuat.")
                except discord.Forbidden: pass
                try: await member.move_to(None)
                except: pass
            except Exception as e:
                log.error(f"Unexpected error creating VC or moving member for {member.display_name}: {e}", exc_info=True)
                try: await member.send(f"❌ Terjadi kesalahan saat membuat channel pribadi Anda. Silakan coba lagi atau hubungi admin server.")
                except discord.Forbidden: pass
                try: await member.move_to(None)
                except: pass

        # The cleanup task already handles deletion, so we just log if an owner left
        if before.channel and str(before.channel.id) in self.active_temp_channels.get(guild_id_str, {}):
            channel_data = self.active_temp_channels[guild_id_str][str(before.channel.id)]
            if not channel_data.get("is_creator_channel", False) and not before.channel.members:
                log.info(f"Owner {member.display_name} left temp VC {before.channel.name}. Triggering cleanup check.")
                pass 

    # --- TempVoice Command Checks ---
    def is_temp_channel_owner(self, ctx):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return False
        guild_id_str = str(ctx.guild.id)
        channel_id_str = str(ctx.author.voice.channel.id)
        if guild_id_str not in self.active_temp_channels or channel_id_str not in self.active_temp_channels[guild_id_str]:
            return False
        # Add a check to ensure it's not a creator channel
        if self.active_temp_channels[guild_id_str][channel_id_str].get("is_creator_channel", False):
            return False
        return self.active_temp_channels[guild_id_str][channel_id_str].get("owner_id") == str(ctx.author.id)

    # --- TempVoice Commands ---
    @commands.command(name="setvccreator", help="[ADMIN] Set a voice channel as a temporary channel creator. Users joining it will get a new private channel.")
    @commands.has_permissions(administrator=True)
    async def set_vc_creator(self, ctx, channel: discord.VoiceChannel):
        guild_id_str = str(ctx.guild.id)
        self.active_temp_channels.setdefault(guild_id_str, {})[str(channel.id)] = {
            "is_creator_channel": True,
            "creator_channel_id": str(channel.id) 
        }
        self._save_temp_channels_state()
        await ctx.send(f"✅ Channel {channel.mention} telah diatur sebagai channel pembuat saluran sementara.")
        log.info(f"Set {channel.name} as creator channel in guild {ctx.guild.name}.")

    @commands.command(name="removevccreator", help="[ADMIN] Remove a voice channel from being a temporary channel creator.")
    @commands.has_permissions(administrator=True)
    async def remove_vc_creator(self, ctx, channel: discord.VoiceChannel):
        guild_id_str = str(ctx.guild.id)
        if guild_id_str in self.active_temp_channels and str(channel.id) in self.active_temp_channels[guild_id_str]:
            if self.active_temp_channels[guild_id_str][str(channel.id)].get("is_creator_channel", False):
                del self.active_temp_channels[guild_id_str][str(channel.id)]
                # If the guild has no more tracked channels, remove it from the main dict
                if not self.active_temp_channels[guild_id_str]:
                    del self.active_temp_channels[guild_id_str]
                self._save_temp_channels_state()
                await ctx.send(f"✅ Channel {channel.mention} telah dihapus dari daftar channel pembuat.")
                log.info(f"Removed {channel.name} as creator channel in guild {ctx.guild.name}.")
            else:
                await ctx.send(f"❌ Channel {channel.mention} bukan channel pembuat.")
        else:
            await ctx.send("❌ Channel tidak ditemukan di daftar channel pembuat.")

    @commands.command(name="vclock", help="Kunci channel pribadimu (hanya bisa masuk via invite).")
    @commands.check(is_temp_channel_owner)
    async def vc_lock(self, ctx):
        vc = ctx.author.voice.channel
        overwrites = vc.overwrites_for(ctx.guild.default_role)
        overwrites.connect = False
        await vc.set_permissions(ctx.guild.default_role, overwrite=overwrites)
        await ctx.send(f"✅ Channel **{vc.name}** telah dikunci.")
        log.info(f"User {ctx.author.display_name} locked channel {vc.name}.")

    @commands.command(name="vcunlock", help="Buka kunci channel pribadimu.")
    @commands.check(is_temp_channel_owner)
    async def vc_unlock(self, ctx):
        vc = ctx.author.voice.channel
        overwrites = vc.overwrites_for(ctx.guild.default_role)
        overwrites.connect = True
        await vc.set_permissions(ctx.guild.default_role, overwrite=overwrites)
        await ctx.send(f"✅ Channel **{vc.name}** telah dibuka.")
        log.info(f"User {ctx.author.display_name} unlocked channel {vc.name}.")

    @commands.command(name="vcsetlimit", help="Atur batas user di channel pribadimu (0 untuk tak terbatas).")
    @commands.check(is_temp_channel_owner)
    async def vc_set_limit(self, ctx, limit: int):
        if not 0 <= limit <= 99: return await ctx.send("Limit harus antara 0 dan 99.")
        await ctx.author.voice.channel.edit(user_limit=limit)
        await ctx.send(f"✅ User limit diatur ke {limit}.")
        log.info(f"User {ctx.author.display_name} set limit of {ctx.author.voice.channel.name} to {limit}.")

    @commands.command(name="vcrename", help="Ubah nama channel pribadimu.")
    @commands.check(is_temp_channel_owner)
    async def vc_rename(self, ctx, *, name: str):
        if not 1 <= len(name) <= 100: return await ctx.send("Nama harus antara 1 dan 100 karakter.")
        old_name = ctx.author.voice.channel.name
        await ctx.author.voice.channel.edit(name=name)
        await ctx.send(f"✅ Nama channel diubah menjadi `{name}`.")
        log.info(f"User {ctx.author.display_name} renamed channel from {old_name} to {name}.")

    @commands.command(name="vckick", help="Tendang user dari channel pribadimu.")
    @commands.check(is_temp_channel_owner)
    async def vc_kick(self, ctx, member: discord.Member):
        if member.id == ctx.author.id: return await ctx.send("Tidak bisa kick diri sendiri.")
        if member.bot: return await ctx.send("Tidak bisa kick bot.")
        if member.voice and member.voice.channel == ctx.author.voice.channel:
            await member.move_to(None)
            await ctx.send(f"✅ {member.display_name} di-kick dari channelmu.")
            log.info(f"User {ctx.author.display_name} kicked {member.display_name} from {ctx.author.voice.channel.name}.")
        else: await ctx.send(f"❌ {member.display_name} tidak ada di channelmu.")

    @commands.command(name="vcgrant", help="Beri user izin masuk channel pribadimu yang terkunci.")
    @commands.check(is_temp_channel_owner)
    async def vc_grant(self, ctx, member: discord.Member):
        if member.bot: return await ctx.send("Tidak bisa grant ke bot.")
        vc = ctx.author.voice.channel
        await vc.set_permissions(member, connect=True)
        await ctx.send(f"✅ {member.display_name} diberikan akses ke channelmu.")
        log.info(f"User {ctx.author.display_name} granted {member.display_name} access to {vc.name}.")

    @commands.command(name="vcrevoke", help="Cabut izin masuk user dari channel pribadimu yang terkunci.")
    @commands.check(is_temp_channel_owner)
    async def vc_revoke(self, ctx, member: discord.Member):
        if member.bot: return await ctx.send("Tidak bisa revoke dari bot.")
        vc = ctx.author.voice.channel
        await vc.set_permissions(member, connect=False)
        await ctx.send(f"✅ Akses {member.display_name} dicabut dari channelmu.")
        log.info(f"User {ctx.author.display_name} revoked {member.display_name}'s access to {vc.name}.")

    @commands.command(name="vcowner", help="Transfer kepemilikan channel pribadimu ke user lain.")
    @commands.check(is_temp_channel_owner) # Hanya pemilik channel yang bisa mentransfer
    async def vc_transfer_owner(self, ctx, new_owner: discord.Member):
        guild_id_str = str(ctx.guild.id)
        channel = ctx.author.voice.channel # Channel yang sedang diakses user
        channel_id_str = str(channel.id)

        if new_owner.bot:
            await ctx.send("❌ Tidak bisa mengalihkan kepemilikan ke bot.")
            return
        if new_owner.id == ctx.author.id:
            await ctx.send("❌ Anda sudah menjadi pemilik channel ini.")
            return

        old_owner_id = self.active_temp_channels[guild_id_str][channel_id_str].get('owner_id')
        old_owner = ctx.guild.get_member(int(old_owner_id)) if old_owner_id else None

        # Update data kepemilikan
        self.active_temp_channels[guild_id_str][channel_id_str]['owner_id'] = str(new_owner.id)
        self._save_temp_channels_state() # Simpan perubahan

        # Hapus izin manajemen dari pemilik lama (ctx.author)
        # Pastikan kita tidak menghapus izin jika old_owner == new_owner (meskipun sudah dicek di atas)
        # Ini penting agar old_owner tidak memiliki izin ganda atau sisa
        if old_owner and old_owner.id == ctx.author.id: # Pemilik lama adalah orang yang menjalankan perintah
            old_owner_overwrites = channel.overwrites_for(old_owner)
            old_owner_overwrites.manage_channels = None
            old_owner_overwrites.manage_roles = None
            old_owner_overwrites.mute_members = None
            old_owner_overwrites.deafen_members = None
            old_owner_overwrites.move_members = None
            await channel.set_permissions(old_owner, overwrite=old_owner_overwrites)
            log.info(f"Removed old owner permissions from {old_owner.display_name} for channel {channel.name}.")

        # Berikan izin manajemen ke pemilik baru
        new_owner_overwrites = channel.overwrites_for(new_owner)
        new_owner_overwrites.manage_channels = True
        new_owner_overwrites.manage_roles = True
        new_owner_overwrites.mute_members = True
        new_owner_overwrites.deafen_members = True
        new_owner_overwrites.move_members = True
        await channel.set_permissions(new_owner, overwrite=new_owner_overwrites)
        
        await ctx.send(f"✅ Kepemilikan saluran {channel.mention} telah dialihkan dari {ctx.author.mention} ke {new_owner.mention}.")
        log.info(f"Ownership of channel {channel.name} transferred from {ctx.author.display_name} to {new_owner.display_name}.")


    @commands.command(name="adminvcowner", help="[ADMIN] Mengatur pemilik saluran suara sementara mana pun.")
    @commands.has_permissions(administrator=True)
    async def admin_vc_transfer_owner(self, ctx, channel: discord.VoiceChannel, new_owner: discord.Member):
        guild_id_str = str(ctx.guild.id)
        channel_id_str = str(channel.id)

        if guild_id_str not in self.active_temp_channels or channel_id_str not in self.active_temp_channels[guild_id_str]:
            await ctx.send("❌ Saluran ini bukan saluran suara sementara yang terdaftar.", ephemeral=True)
            return
        
        if new_owner.bot:
            await ctx.send("❌ Tidak bisa mengalihkan kepemilikan ke bot.")
            return

        old_owner_id = self.active_temp_channels[guild_id_str][channel_id_str].get('owner_id')
        old_owner = ctx.guild.get_member(int(old_owner_id)) if old_owner_id else None

        self.active_temp_channels[guild_id_str][channel_id_str]['owner_id'] = str(new_owner.id)
        self._save_temp_channels_state()

        # Hapus izin dari pemilik lama jika ada dan berbeda dari pemilik baru
        if old_owner and old_owner != new_owner:
            old_owner_overwrites = channel.overwrites_for(old_owner)
            old_owner_overwrites.manage_channels = None
            old_owner_overwrites.manage_roles = None
            old_owner_overwrites.mute_members = None
            old_owner_overwrites.deafen_members = None
            old_owner_overwrites.move_members = None
            await channel.set_permissions(old_owner, overwrite=old_owner_overwrites)
            log.info(f"Removed owner permissions from {old_owner.display_name} for channel {channel.name} (by admin).")

        # Berikan izin ke pemilik baru
        new_owner_overwrites = channel.overwrites_for(new_owner)
        new_owner_overwrites.manage_channels = True
        new_owner_overwrites.manage_roles = True
        new_owner_overwrites.mute_members = True
        new_owner_overwrites.deafen_members = True
        new_owner_overwrites.move_members = True
        await channel.set_permissions(new_owner, overwrite=new_owner_overwrites)
        
        await ctx.send(f"✅ Kepemilikan saluran {channel.mention} telah dialihkan ke {new_owner.mention} (oleh admin).")
        log.info(f"Admin {ctx.author.display_name} transferred ownership of {channel.name} to {new_owner.display_name}.")

    @commands.command(name="vchelp", help="Menampilkan panduan untuk mengelola channel pribadimu.")
    async def vc_help(self, ctx):
        embed = discord.Embed(
            title="🎧 Panduan Channel Pribadi",
            description="Perintah untuk mengelola channel suara yang Anda miliki.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Manajemen Channel:", value="""
        `!vcsetlimit <angka>`: Atur batas user (0 untuk tak terbatas)
        `!vcrename <nama_baru>`: Ubah nama channel
        `!vclock`: Kunci channel (hanya bisa masuk via invite)
        `!vcunlock`: Buka kunci channel
        """, inline=False)
        embed.add_field(name="Manajemen User:", value="""
        `!vckick @user`: Tendang user dari channel
        `!vcgrant @user`: Beri user izin masuk channel yang terkunci
        `!vcrevoke @user`: Cabut izin masuk channel yang terkunci
        `!vcowner @user`: Transfer kepemilikan channel ke user lain (hanya bisa 1 pemilik)
        """, inline=False)
        embed.set_footer(text="Channel akan otomatis terhapus jika kosong.")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(TempVoice(bot))
