import discord
from discord.ext import commands, tasks
import random
import asyncio
import time

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.mongo_client["reSwan"]
        self.col = self.db["prank_nicknames"]
        
        self.hewan_lucu = [
            "Ayam", "Kelinci", "Kucing", "Anjing", "Bebek", "Beruang", "Koala", "Kancil", 
            "Tupai", "Katak", "Burung", "Domba", "Sapi", "Kuda", "Singa", "Harimau", 
            "Gajah", "Jerapah", "Monyet", "Gorila", "Kudanil", "Babi", "Ular", "Musang", 
            "Lebah", "Capung", "Rubah", "Landak", "Lutung", "Rusa", "Kambing", "Kerbau", 
            "Banteng", "Unta", "Keledai", "Serigala", "Tikus", "Semut", "Nyamuk", "Lalat", 
            "Kecoak", "Belalang", "Merpati", "Elang", "Gagak", "Bangau", "Angsa", "Paus", 
            "Hiu", "Gurita", "Cumi", "Kepiting", "Udang", "Buaya", "Komodo", "Biawak", 
            "Kadal", "Cicak", "Tokek", "Bunglon", "Belut", "Kakap", "Gurame"
        ]
        
        self.check_expiry.start()

    def cog_unload(self):
        self.check_expiry.cancel()

    def parse_duration(self, duration_str: str) -> float:
        if not duration_str:
            return None
        unit = duration_str[-1].lower()
        try:
            val = int(duration_str[:-1])
        except ValueError:
            return None
            
        if unit == 's':
            return val
        elif unit == 'm':
            return val * 60
        elif unit == 'h':
            return val * 3600
        elif unit == 'd':
            return val * 86400
        return None

    @tasks.loop(seconds=30)
    async def check_expiry(self):
        now = time.time()
        # Cari prank aktif yang sudah expired
        expired_docs = self.col.find({"active": True, "expires_at": {"$lt": now}})
        for doc in list(expired_docs):
            guild_id = int(doc["_id"])
            guild = self.bot.get_guild(guild_id)
            if guild:
                success = 0
                failed = 0
                original_nicks = doc.get("original_nicknames", {})
                for member_id_str, assigned_nick in doc.get("nicknames", {}).items():
                    member_id = int(member_id_str)
                    member = guild.get_member(member_id)
                    if member:
                        try:
                            # Hanya reset jika nickname-nya memang nama prank-nya
                            if member.nick == assigned_nick:
                                orig_nick = original_nicks.get(member_id_str)
                                await member.edit(nick=orig_nick)
                                success += 1
                                await asyncio.sleep(1.2)
                        except Exception:
                            failed += 1
                
                channel = guild.system_channel
                if not channel:
                    for ch in guild.text_channels:
                        if ch.permissions_for(guild.me).send_messages:
                            channel = ch
                            break
                if channel:
                    await channel.send(f"⏰ **Prank Nickname Telah Berakhir!**\nSemua nickname member (termasuk bot) telah dikembalikan ke semula sebelum diubah. (Berhasil reset **{success}** member).")
            
            # Hapus dari db
            self.col.delete_one({"_id": doc["_id"]})

    @commands.command(name="pranknama", aliases=["hewanlucu", "ubahsemua"])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def pranknama(self, ctx, duration: str = None):
        """Ubah nickname semua member di server menjadi nama hewan lucu!
        Format waktu: 10m (menit), 2h (jam), 1d (hari). Contoh: !pranknama 1h
        """
        
        parsed_seconds = None
        expires_at = None
        if duration:
            parsed_seconds = self.parse_duration(duration)
            if parsed_seconds is None:
                await ctx.send("❌ Format durasi salah! Gunakan format seperti: `10m` (10 menit), `2h` (2 jam), atau `1d` (1 hari).")
                return
            expires_at = time.time() + parsed_seconds
            
        dur_msg = f"selama **{duration}**" if duration else "selamanya (atau sampai direset)"
        
        # Confirmation
        embed = discord.Embed(
            title="⚠️ Konfirmasi Prank Nickname",
            description=f"Apakah kamu yakin ingin mengubah **SEMUA** nickname member (termasuk bot ini sendiri) di server ini {dur_msg}? (Balas dengan `ya` atau `tidak`)",
            color=discord.Color.yellow()
        )
        await ctx.send(embed=embed)
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ["ya", "tidak"]
            
        try:
            response = await self.bot.wait_for("message", check=check, timeout=30.0)
            if response.content.lower() == "tidak":
                await ctx.send("Dibatalkan. Hufh, member server aman dari kejahilanmu! 😌")
                return
        except asyncio.TimeoutError:
            await ctx.send("Waktu habis! Perintah dibatalkan.")
            return

        await ctx.send("🔄 Mulai mengubah nickname semua member menjadi nama hewan lucu... Mohon tunggu!")
        
        success = 0
        failed = 0
        used_nicknames = set()
        assigned_nicknames = {}
        original_nicknames = {}
        
        for member in ctx.guild.members:
            # Skip bot lain, tapi JANGAN skip bot ini sendiri
            if member.bot and member.id != self.bot.user.id:
                continue
                
            # Skip owner dan member dengan role lebih tinggi (kecuali bot itu sendiri)
            if member != ctx.guild.owner and ctx.guild.me.top_role <= member.top_role and member.id != self.bot.user.id:
                failed += 1
                continue
                
            if member == ctx.guild.owner:
                failed += 1
                continue
                
            new_nickname = None
            attempts = 0
            while attempts < 100:
                random_animal = random.choice(self.hewan_lucu)
                last_char = random_animal[-1]
                repeated_chars = last_char * random.randint(8, 14)
                candidate = f"{random_animal[:-1]}{repeated_chars}"
                if candidate not in used_nicknames:
                    new_nickname = candidate
                    used_nicknames.add(candidate)
                    break
                attempts += 1
            
            if not new_nickname:
                new_nickname = f"{random_animal[:-1]}{repeated_chars}{random.randint(1, 99)}"
                used_nicknames.add(new_nickname)
            
            original_nick = member.nick # Simpan nama original (bisa berupa String atau None)
            
            try:
                await member.edit(nick=new_nickname)
                assigned_nicknames[str(member.id)] = new_nickname
                original_nicknames[str(member.id)] = original_nick
                success += 1
                await asyncio.sleep(1.2)
            except Exception:
                failed += 1
                
        # Simpan ke DB
        prank_data = {
            "_id": str(ctx.guild.id),
            "active": True,
            "expires_at": expires_at,
            "nicknames": assigned_nicknames,
            "original_nicknames": original_nicknames
        }
        self.col.replace_one({"_id": str(ctx.guild.id)}, prank_data, upsert=True)
        
        await ctx.send(f"✅ Selesai! Berhasil mengubah nickname **{success}** member (termasuk bot ini sendiri).\n❌ Gagal mengubah **{failed}** member.\n⏰ Prank aktif {dur_msg}.")

    @commands.command(name="resetnama")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def resetnama(self, ctx):
        """Hapus nickname semua member agar kembali normal."""
        
        embed = discord.Embed(
            title="⚠️ Konfirmasi Reset Nickname",
            description="Apakah kamu yakin ingin me-reset nickname **SEMUA** member di server ini ke kondisi awal sebelum prank? (Balas dengan `ya` atau `tidak`)",
            color=discord.Color.yellow()
        )
        await ctx.send(embed=embed)
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ["ya", "tidak"]
            
        try:
            response = await self.bot.wait_for("message", check=check, timeout=30.0)
            if response.content.lower() == "tidak":
                await ctx.send("Dibatalkan.")
                return
        except asyncio.TimeoutError:
            await ctx.send("Waktu habis! Perintah dibatalkan.")
            return
            
        await ctx.send("🔄 Mengembalikan semua nickname menjadi normal... Harap bersabar!")
        
        # Ambil data original nicknames dari DB
        doc = self.col.find_one({"_id": str(ctx.guild.id)})
        original_nicks = doc.get("original_nicknames", {}) if doc else {}
        
        success = 0
        failed = 0
        
        for member in ctx.guild.members:
            if member.bot and member.id != self.bot.user.id:
                continue
                
            if member == ctx.guild.owner:
                continue
                
            if ctx.guild.me.top_role <= member.top_role and member.id != self.bot.user.id:
                continue
                
            member_id_str = str(member.id)
            if member_id_str in original_nicks:
                orig_nick = original_nicks[member_id_str]
                try:
                    await member.edit(nick=orig_nick)
                    success += 1
                    await asyncio.sleep(1.2)
                except Exception:
                    failed += 1
            else:
                # Fallback jika tidak ada di DB, hapus nickname saja
                try:
                    if member.nick is not None:
                        await member.edit(nick=None)
                        success += 1
                        await asyncio.sleep(1.2)
                except Exception:
                    failed += 1
                
        # Hapus data dari DB
        self.col.delete_one({"_id": str(ctx.guild.id)})
        await ctx.send(f"✅ Selesai! Berhasil mereset nickname **{success}** member kembali ke semula.\n❌ Gagal mereset **{failed}** member.")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Proteksi agar nickname tetap (sticky)
        if before.nick != after.nick:
            doc = self.col.find_one({"_id": str(after.guild.id), "active": True})
            if doc:
                member_id_str = str(after.id)
                assigned_nick = doc.get("nicknames", {}).get(member_id_str)
                # Jika member mencoba mengganti namanya sendiri padahal prank sedang aktif, ubah balik!
                if assigned_nick and after.nick != assigned_nick:
                    try:
                        await after.edit(nick=assigned_nick)
                    except Exception:
                        pass

async def setup(bot):
    await bot.add_cog(Fun(bot))
