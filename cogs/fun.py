import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import re
import time
from datetime import datetime
import asyncio
from cogs.gemini import generate_smart_response

TAROT_CARDS = {
    "The Fool": "Spontanitas, awal baru, kepolosan, petualangan, potensi besar.",
    "The Magician": "Kekuatan kehendak, manifestasi, konsentrasi, kecakapan, aksi terarah.",
    "The High Priestess": "Intuisi, misteri, ketidaksadaran, suara hati, kebijaksanaan feminin.",
    "The Empress": "Kelimpahan, kreativitas, keibuan, alam, kesuburan, kenyamanan.",
    "The Emperor": "Otoritas, struktur, kontrol, stabilitas, perlindungan, figur ayah.",
    "The Hierophant": "Tradisi, konformitas, institusi, keyakinan spiritual, bimbingan.",
    "The Lovers": "Pilihan penting, keselarasan, kemitraan, cinta, nilai-nilai pribadi.",
    "The Chariot": "Tekad, kemenangan melalui usaha, kontrol diri, fokus, mengatasi rintangan.",
    "Strength": "Keberanian, kesabaran, kekuatan batin, kelembutan yang menaklukkan.",
    "The Hermit": "Introspeksi, pencarian jiwa, kesendirian, bimbingan batin, kedewasaan.",
    "Wheel of Fortune": "Perubahan nasib, siklus kehidupan, takdir, keberuntungan, peluang baru.",
    "Justice": "Keadilan, kebenaran, hukum sebab-akibat, integritas, keputusan jujur.",
    "The Hanged Man": "Perspektif baru, pengorbanan, melepaskan kontrol, menunggu dengan sabar.",
    "Death": "Transformasi besar, akhir dari suatu siklus, transisi, melepaskan yang lama.",
    "Temperance": "Keseimbangan, moderasi, kesabaran, kombinasi harmonis, kedamaian.",
    "The Devil": "Keterikatan, kecanduan, bayangan diri, materialisme berlebih, ilusi keterbatasan.",
    "The Tower": "Perubahan mendadak, kehancuran ilusi, wahyu, krisis yang membersihkan.",
    "The Star": "Harapan, pemulihan, inspirasi spiritual, kedamaian pikiran, optimisme.",
    "The Moon": "Ilusi, ketakutan batin, kecemasan, kebingungan, mimpi, intuisi tajam.",
    "The Sun": "Keceriaan, sukses, kejelasan, energi positif, vitalitas, pencapaian.",
    "Judgement": "Panggilan jiwa, evaluasi diri, kebangkitan, pengampunan, keputusan matang.",
    "The World": "Penyelesaian, integrasi, pencapaian tujuan, kebebasan, pemenuhan spiritual."
}

class ConfessionModal(discord.ui.Modal, title="Kirim Curhatan Anonim"):
    confess_title = discord.ui.TextInput(
        label="Judul Curhatan (Opsional)",
        placeholder="Misal: Patah Hati, Capek Kuliah, dll...",
        required=False,
        max_length=100
    )
    confess_content = discord.ui.TextInput(
        label="Isi Curhatan",
        style=discord.TextStyle.long,
        placeholder="Tulis curhatan kamu di sini secara anonim...",
        required=True,
        max_length=1500
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id_str = str(interaction.guild_id)
        settings = self.cog.confess_col.find_one({"_id": guild_id_str})
        if not settings or not settings.get("channel_id"):
            await interaction.followup.send("❌ Channel pengakuan belum diset oleh Admin. Minta admin menjalankan `/set_confess_channel` terlebih dahulu.", ephemeral=True)
            return

        content = self.confess_content.value
        title_val = self.confess_title.value or "Curhatan Anonim"

        moderation_prompt = (
            "Lu adalah sistem moderasi untuk curhatan anonim. Tugas lu adalah menilai apakah pesan di bawah ini layak diposting. "
            "Kriteria REJECTED jika mengandung: doxxing (menyebar info pribadi orang), ancaman kekerasan nyata, ajakan bunuh diri/self-harm parah, atau spam kasar. "
            "Selain itu, jika layak, balas dengan 'SAFE'. Jika tidak layak, balas dengan 'REJECTED: [alasan singkat dalam bahasa Indonesia]'.\n\n"
            f"Pesan: {content}"
        )

        try:
            mod_response = await generate_smart_response(moderation_prompt)
            mod_result = mod_response.text.strip()
        except Exception:
            mod_result = "SAFE"

        if mod_result.startswith("REJECTED"):
            reason = mod_result.replace("REJECTED:", "").strip()
            await interaction.followup.send(f"❌ Curhatan kamu ditolak oleh filter AI karena: {reason}", ephemeral=True)
            return

        raka_prompt = (
            "Lu adalah Raka, seorang sahabat dan psikolog AI yang suportif namun realistis dan tidak ragu memberikan kritik membangun (tidak bermuka dua/palsu). "
            f"User mengirimkan curhatan anonim dengan judul '{title_val}' dan isi: '{content}'. "
            "Berikan tanggapan singkat, padat (maksimal 3-4 kalimat). "
            "Tanggapan lu harus terasa seperti teman dekat sekaligus psikolog yang peduli: berikan kata penyemangat, "
            "tapi jika ada kesalahan atau pola pikir dari user yang keliru, beri kritik/saran jujur secara sopan namun tajam (jangan halu/palsu). "
            "Gunakan gaya bahasa santai gaul Indonesia (lu/gue) tapi tetap sopan."
        )

        try:
            raka_response = await generate_smart_response(raka_prompt)
            raka_advice = raka_response.text.strip()
        except Exception:
            raka_advice = "Raka lagi sibuk merenung, tapi intinya tetap semangat ya! Lu pasti bisa ngelewatin ini."

        counter = settings.get("counter", 0) + 1
        self.cog.confess_col.update_one({"_id": guild_id_str}, {"$set": {"counter": counter}})

        channel = interaction.guild.get_channel(int(settings["channel_id"]))
        if not channel:
            await interaction.followup.send("❌ Channel pengakuan tidak ditemukan di server ini. Hubungi admin.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🤫 Bilik Rahasia #Confess-{counter}",
            color=discord.Color.from_rgb(88, 101, 242),
            timestamp=datetime.now()
        )
        embed.add_field(name=f"📌 {title_val}", value=content, inline=False)
        embed.add_field(name="💬 Catatan Sahabat & Psikolog (Raka AI)", value=raka_advice, inline=False)
        embed.set_footer(text="Ingin curhat juga secara anonim? Klik tombol di pesan panduan channel ini.")

        await channel.send(embed=embed)
        await interaction.followup.send("✅ Curhatan anonim kamu berhasil diposting di channel pengakuan!", ephemeral=True)

class ConfessionSetupView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Kirim Curhat Anonim", style=discord.ButtonStyle.blurple, custom_id="send_confess_button", emoji="🤫")
    async def send_confess(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ConfessionModal(self.cog))

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.mongo_client["reSwan"]
        self.col = self.db["prank_nicknames"]
        self.confess_col = self.db["confession_settings"]
        
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
        self.bot.add_view(ConfessionSetupView(self))

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
                    
                    # Ambil member dengan fallback fetch jika cache kosong
                    member = guild.get_member(member_id)
                    if not member:
                        try:
                            member = await guild.fetch_member(member_id)
                        except Exception:
                            pass
                            
                    if member:
                        try:
                            orig_nick = original_nicks.get(member_id_str)
                            # Reset jika nama saat ini tidak sama dengan nama awal sebelum prank
                            if member.nick != orig_nick:
                                await member.edit(nick=orig_nick)
                                success += 1
                                await asyncio.sleep(1.2)
                        except Exception:
                            failed += 1
                
                # Kirim pengumuman ke channel asal tempat prank diaktifkan
                channel_id_str = doc.get("activation_channel_id")
                channel = None
                if channel_id_str:
                    channel = guild.get_channel(int(channel_id_str))
                
                if not channel:
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

    @commands.hybrid_command(name="pranknama", aliases=["hewanlucu", "ubahsemua"], description="Prank ubah nama semua member server jadi nama hewan lucu sementara.")
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
            "activation_channel_id": str(ctx.channel.id),
            "nicknames": assigned_nicknames,
            "original_nicknames": original_nicknames
        }
        self.col.replace_one({"_id": str(ctx.guild.id)}, prank_data, upsert=True)
        
        await ctx.send(f"✅ Selesai! Berhasil mengubah nickname **{success}** member (termasuk bot ini sendiri).\n❌ Gagal mengubah **{failed}** member.\n⏰ Prank aktif {dur_msg}.")

    @commands.hybrid_command(name="resetnama", description="Hapus nickname semua member agar kembali normal setelah prank.")
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
            guild_id_str = str(after.guild.id)
            doc = self.col.find_one({"_id": guild_id_str, "active": True})
            if doc:
                if after.bot and after.id != self.bot.user.id:
                    return
                if after == after.guild.owner:
                    return
                if after.guild.me.top_role <= after.top_role and after.id != self.bot.user.id:
                    return

                member_id_str = str(after.id)
                assigned_nick = doc.get("nicknames", {}).get(member_id_str)
                
                # Jika member mencoba mengganti namanya sendiri padahal prank sedang aktif, ubah balik!
                if assigned_nick:
                    if after.nick != assigned_nick:
                        try:
                            await after.edit(nick=assigned_nick)
                        except Exception:
                            pass
                else:
                    # Jika member belum terdaftar nickname pranknya (misal terlewat), generate baru
                    used_nicks = set(doc.get("nicknames", {}).values())
                    new_nickname = None
                    attempts = 0
                    while attempts < 100:
                        random_animal = random.choice(self.hewan_lucu)
                        last_char = random_animal[-1]
                        repeated_chars = last_char * random.randint(8, 14)
                        candidate = f"{random_animal[:-1]}{repeated_chars}"
                        if candidate not in used_nicks:
                            new_nickname = candidate
                            break
                        attempts += 1
                    
                    if not new_nickname:
                        new_nickname = f"{random_animal[:-1]}{repeated_chars}{random.randint(1, 99)}"
                    
                    self.col.update_one(
                        {"_id": guild_id_str},
                        {"$set": {
                            f"nicknames.{member_id_str}": new_nickname,
                            f"original_nicknames.{member_id_str}": before.nick
                        }}
                    )
                    try:
                        await after.edit(nick=new_nickname)
                    except Exception:
                        pass

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Otomatis ubah nama member baru yang join jika prank sedang aktif
        guild_id_str = str(member.guild.id)
        doc = self.col.find_one({"_id": guild_id_str, "active": True})
        if doc:
            if member.bot:
                return
            if member.guild.me.top_role <= member.top_role:
                return
                
            member_id_str = str(member.id)
            used_nicks = set(doc.get("nicknames", {}).values())
            new_nickname = None
            attempts = 0
            while attempts < 100:
                random_animal = random.choice(self.hewan_lucu)
                last_char = random_animal[-1]
                repeated_chars = last_char * random.randint(8, 14)
                candidate = f"{random_animal[:-1]}{repeated_chars}"
                if candidate not in used_nicks:
                    new_nickname = candidate
                    break
                attempts += 1
            
            if not new_nickname:
                new_nickname = f"{random_animal[:-1]}{repeated_chars}{random.randint(1, 99)}"
                
            self.col.update_one(
                {"_id": guild_id_str},
                {"$set": {
                    f"nicknames.{member_id_str}": new_nickname,
                    f"original_nicknames.{member_id_str}": None
                }}
            )
            try:
                await member.edit(nick=new_nickname)
            except Exception:
                pass

    # ==========================================
    # CONFESSION & FORTUNE TELLER COMMANDS (HYBRID/SLASH)
    # ==========================================

    @app_commands.command(name="set_confess_channel", description="Set channel untuk menampung curhatan anonim.")
    @app_commands.describe(channel="Channel text tujuan")
    @app_commands.default_permissions(administrator=True)
    async def set_confess_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id_str = str(interaction.guild_id)
        self.confess_col.update_one(
            {"_id": guild_id_str},
            {"$set": {"channel_id": str(channel.id)}, "$setOnInsert": {"counter": 0}},
            upsert=True
        )
        await interaction.response.send_message(f"✅ Channel pengakuan anonim berhasil diset ke {channel.mention}!", ephemeral=True)

    @app_commands.command(name="confess_setup", description="Kirim pesan instruksi dengan tombol curhat anonim di channel ini.")
    @app_commands.default_permissions(administrator=True)
    async def confess_setup(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🤫 Bilik Rahasia - Kirim Curhatan Anonim",
            description=(
                "Punya rahasia, kekesalan, kesedihan, atau curhatan yang ingin dikeluarkan tanpa ada orang yang tahu siapa kamu? \n\n"
                "Klik tombol **Kirim Curhat Anonim** di bawah ini untuk menulis curhatmu secara rahasia. \n"
                "Curhatan kamu akan diproses dan dibalas oleh **Raka (AI Psychologist)** secara otomatis di channel ini."
            ),
            color=discord.Color.from_rgb(88, 101, 242)
        )
        await interaction.channel.send(embed=embed, view=ConfessionSetupView(self))
        await interaction.response.send_message("✅ Pesan setup berhasil dikirim!", ephemeral=True)

    @app_commands.command(name="confess", description="Kirim curhatan anonim lewat modal.")
    async def confess_slash(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ConfessionModal(self))

    @commands.hybrid_command(name="tarot", description="Lakukan ramalan Tarot (3 Kartu: Past, Present, Future) dengan tafsiran Raka.")
    async def tarot(self, ctx, *, pertanyaan: str = None):
        await ctx.defer()
        
        keys = list(TAROT_CARDS.keys())
        drawn_keys = random.sample(keys, 3)
        
        past_card = drawn_keys[0]
        present_card = drawn_keys[1]
        future_card = drawn_keys[2]
        
        past_meaning = TAROT_CARDS[past_card]
        present_meaning = TAROT_CARDS[present_card]
        future_meaning = TAROT_CARDS[future_card]
        
        q_text = f"Pertanyaan user: '{pertanyaan}'" if pertanyaan else "Melihat kondisi umum hidup user."
        
        prompt = (
            "Lu adalah Raka, seorang pembaca kartu tarot profesional sekaligus teman dekat dan psikolog yang suportif namun realistis. "
            "Lu tidak ragu memberikan kritik jika user melakukan kesalahan, bersikap malas, atau menyangkal realita. "
            f"User melakukan tebaran tarot 3 kartu. {q_text}\n"
            f"Kartu Masa Lalu (Past): {past_card} (Makna: {past_meaning})\n"
            f"Kartu Masa Kini (Present): {present_card} (Makna: {present_meaning})\n"
            f"Kartu Masa Depan (Future): {future_card} (Makna: {future_meaning})\n\n"
            "Tafsirkan tebaran ini dalam bahasa Indonesia dengan gaya santai gaul (lu/gue) tapi mendalam. "
            "Berikan analisis psikologis yang logis (jangan halu/mistis berlebihan), tunjukkan empati sebagai sahabat, "
            "berikan kata penyemangat di akhir, tapi jangan segan memberikan kritik tajam atas kartu masa kini/masa depan jika ada pola negatif dari kartu tersebut."
        )
        
        try:
            response = await generate_smart_response(prompt)
            result_text = response.text
        except Exception as e:
            result_text = f"Gagal memanggil Raka AI: {e}"

        embed = discord.Embed(
            title="🃏 Ramalan Tarot Raka",
            description=f"🔮 **Pertanyaan:** {pertanyaan or 'Kondisi Umum'}",
            color=discord.Color.purple(),
            timestamp=datetime.now()
        )
        embed.add_field(name="⏪ Masa Lalu (Past)", value=f"**{past_card}**\n*{past_meaning}*", inline=False)
        embed.add_field(name="⏺️ Masa Kini (Present)", value=f"**{present_card}**\n*{present_meaning}*", inline=False)
        embed.add_field(name="⏩ Masa Depan (Future)", value=f"**{future_card}**\n*{future_meaning}*", inline=False)
        
        if len(result_text) > 1024:
            embed.add_field(name="💬 Tafsiran Raka (Bagian 1)", value=result_text[:1000], inline=False)
            embed.add_field(name="💬 Tafsiran Raka (Bagian 2)", value=result_text[1000:2000], inline=False)
        else:
            embed.add_field(name="💬 Tafsiran Raka", value=result_text, inline=False)
            
        embed.set_footer(text=f"Ramalan Tarot oleh {ctx.author.display_name}")
        await ctx.send(embed=embed)

    def get_zodiac_sign(self, day: int, month: int) -> str:
        if (month == 12 and day >= 22) or (month == 1 and day <= 19):
            return "Capricorn"
        elif (month == 1 and day >= 20) or (month == 2 and day <= 18):
            return "Aquarius"
        elif (month == 2 and day >= 19) or (month == 3 and day <= 20):
            return "Pisces"
        elif (month == 3 and day >= 21) or (month == 4 and day <= 19):
            return "Aries"
        elif (month == 4 and day >= 20) or (month == 5 and day <= 20):
            return "Taurus"
        elif (month == 5 and day >= 21) or (month == 6 and day <= 20):
            return "Gemini"
        elif (month == 6 and day >= 21) or (month == 7 and day <= 22):
            return "Cancer"
        elif (month == 7 and day >= 23) or (month == 8 and day <= 22):
            return "Leo"
        elif (month == 8 and day >= 23) or (month == 9 and day <= 22):
            return "Virgo"
        elif (month == 9 and day >= 23) or (month == 10 and day <= 22):
            return "Libra"
        elif (month == 10 and day >= 23) or (month == 11 and day <= 21):
            return "Scorpio"
        elif (month == 11 and day >= 22) or (month == 12 and day <= 21):
            return "Sagittarius"
        return None

    @commands.hybrid_command(name="zodiak", description="Lihat ramalan zodiak harian ala Raka berdasarkan nama zodiak atau tanggal lahir (contoh: 25-10).")
    async def zodiak(self, ctx, *, zodiak_atau_tanggal: str):
        await ctx.defer()
        
        sign = zodiak_atau_tanggal.strip().capitalize()
        match = re.match(r"(\d{1,2})[-/.](\d{1,2})", zodiak_atau_tanggal)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            calculated_sign = self.get_zodiac_sign(day, month)
            if calculated_sign:
                sign = calculated_sign
            else:
                await ctx.send("❌ Tanggal lahir tidak valid!")
                return

        valid_signs = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
        if sign not in valid_signs:
            await ctx.send(f"❌ Zodiak '{zodiak_atau_tanggal}' tidak valid. Gunakan nama zodiak (misal: Scorpio) atau tanggal lahir (misal: 25-10).")
            return

        prompt = (
            f"Lu adalah Raka, teman dekat sekaligus psikolog/astrolog yang jujur. Berikan ramalan zodiak harian untuk bintang **{sign}**. "
            "Ramalan tidak boleh bersifat mistis/takhayul berlebihan (jangan halu), tapi berikan analisis psikologis realistis mengenai karir/keuangan, cinta, dan kesehatan mereka hari ini. "
            "Berikan semangat layaknya sahabat karib, tapi jangan sungkan memberikan kritik tajam jika ada kelemahan mendasar dari zodiak ini yang harus diperbaiki. "
            "Gunakan bahasa gaul Indonesia santai (lu/gue) namun peduli."
        )

        try:
            response = await generate_smart_response(prompt)
            result_text = response.text
        except Exception as e:
            result_text = f"Gagal memanggil Raka AI: {e}"

        embed = discord.Embed(
            title=f"✨ Ramalan Zodiak {sign} - Raka AI",
            description=result_text,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Zodiak oleh {ctx.author.display_name}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="lifepath", description="Hitung Angka Lifepath (Numerologi) kamu berdasarkan tanggal lahir (format: DD-MM-YYYY).")
    async def lifepath(self, ctx, *, tanggal_lahir: str):
        await ctx.defer()
        
        digits = [int(char) for char in tanggal_lahir if char.isdigit()]
        parts = re.split(r'[-/.]', tanggal_lahir)
        day, month, year = None, None, None
        if len(parts) != 3:
            clean = "".join(str(d) for d in digits)
            if len(clean) == 8:
                day = int(clean[:2])
                month = int(clean[2:4])
                year = int(clean[4:])
            else:
                await ctx.send("❌ Format tanggal salah! Gunakan format: DD-MM-YYYY (contoh: 25-10-1999).")
                return
        else:
            try:
                day = int(parts[0])
                month = int(parts[1])
                year = int(parts[2])
            except ValueError:
                await ctx.send("❌ Tanggal lahir harus berupa angka!")
                return
                
        if day < 1 or day > 31 or month < 1 or month > 12 or year < 1900 or year > 2030:
            await ctx.send("❌ Tanggal lahir tidak logis!")
            return
            
        def reduce_num(n):
            while n > 9:
                if n in [11, 22, 33]:
                    return n
                n = sum(int(d) for d in str(n))
            return n

        r_day = reduce_num(day)
        r_month = reduce_num(month)
        r_year = reduce_num(year)
        
        total = r_day + r_month + r_year
        lifepath_num = reduce_num(total)

        prompt = (
            f"Lu adalah Raka, teman dan psikolog AI yang memahami ilmu numerologi. Jelaskan arti Angka Lifepath **{lifepath_num}** (dari tanggal lahir {day}-{month}-{year}). "
            "Jelaskan karakteristik kepribadian mereka secara realistis and logis (tidak halu/takhayul ekstrem). "
            "Berikan nasihat psikologis, tunjukkan sisi kekuatan dan kelemahan terbesar mereka, "
            "serta beri kritik keras/tegas terhadap kecenderungan buruk lifepath tersebut (misalnya keras kepala, egois, atau peragu). "
            "Gunakan bahasa gaul Indonesia santai (lu/gue) tapi mendalam."
        )

        try:
            response = await generate_smart_response(prompt)
            result_text = response.text
        except Exception as e:
            result_text = f"Gagal memanggil Raka AI: {e}"

        embed = discord.Embed(
            title=f"🔢 Lifepath Number {lifepath_num} - Numerologi Raka",
            description=f"📅 **Tanggal Lahir:** {day:02d}-{month:02d}-{year}\n\n{result_text}",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Lifepath oleh {ctx.author.display_name}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="roast", description="Minta Raka buat nge-roast (ngejek) seseorang atau diri sendiri.")
    async def roast(self, ctx, user: discord.Member = None):
        await ctx.defer()
        target = user or ctx.author
        
        prompt = (
            f"Lu adalah Raka, cowok gaul yang suka ngomong sarkas, nyelekit, tapi tetep lucu. "
            f"Coba roast (ejek dengan gaya bercanda yang agak tajam) orang yang namanya {target.display_name}. "
            "Gunakan bahasa gaul Indonesia (lu/gue, anjir, dll). Jangan terlalu toxic sampai SARA/NSFW, tapi pastikan roastingannya pedas dan ngena. Maksimal 3 kalimat aja."
        )
        
        try:
            response = await generate_smart_response(prompt)
            result_text = response.text
        except Exception as e:
            result_text = f"Gagal mikir roastingan: {e}"
            
        embed = discord.Embed(
            title=f"🔥 Roasting untuk {target.display_name}",
            description=result_text,
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="ship", description="Cek persentase kecocokan jodoh antara dua orang!")
    async def ship(self, ctx, user1: discord.Member, user2: discord.Member = None):
        await ctx.defer()
        
        if user2 is None:
            user2 = ctx.author
            
        if user1 == user2:
            await ctx.send("Lu mau ship sama diri sendiri? Jomblo banget sih bang. 🗿")
            return
            
        # Menggunakan seed berdasarkan ID kedua user supaya hasilnya konsisten
        seed = int(user1.id) + int(user2.id)
        random.seed(seed)
        percent = random.randint(0, 100)
        random.seed() # reset seed
        
        bar_length = 10
        filled = int((percent / 100) * bar_length)
        bar = "❤️" * filled + "🖤" * (bar_length - filled)
        
        prompt = (
            f"Lu adalah Raka, teman yang suka julid dan ngeledek soal percintaan. "
            f"Tingkat kecocokan antara {user1.display_name} dan {user2.display_name} adalah {percent}%. "
            f"Berikan komentar lucu, sarkas, atau menyemangati (tergantung persentasenya) tentang hubungan mereka berdua. "
            f"Gunakan bahasa gaul Indonesia."
        )
        
        try:
            response = await generate_smart_response(prompt)
            result_text = response.text
        except Exception as e:
            result_text = f"Komentar Raka error: {e}"
            
        embed = discord.Embed(
            title="💘 Matchmaker 💘",
            description=f"**{user1.display_name}** x **{user2.display_name}**\n\nKecocokan: **{percent}%**\n{bar}\n\n**Komentar Raka:**\n{result_text}",
            color=discord.Color.pink()
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="8ball", description="Tanya apa saja ke Magic 8-Ball ala Raka yang sarkas.")
    async def eight_ball(self, ctx, *, pertanyaan: str):
        await ctx.defer()
        
        prompt = (
            f"Lu adalah Raka yang sedang bertugas jadi Magic 8-Ball. "
            f"Seseorang bertanya: '{pertanyaan}'. "
            f"Berikan jawaban singkat (seperti magic 8-ball pada umumnya: ya, tidak, mungkin, tanya lagi nanti) "
            f"TAPI tambahkan komentar nyinyir, lucu, atau ngeledek setelahnya pakai bahasa gaul."
        )
        
        try:
            response = await generate_smart_response(prompt)
            result_text = response.text
        except Exception as e:
            result_text = f"Otak Raka error: {e}"
            
        embed = discord.Embed(
            title="🎱 Magic 8-Ball Raka",
            color=discord.Color.dark_theme()
        )
        embed.add_field(name="Pertanyaan", value=pertanyaan, inline=False)
        embed.add_field(name="Jawaban Raka", value=result_text, inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Fun(bot))
