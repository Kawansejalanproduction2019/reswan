import discord
from discord.ext import commands
import json
import random
import asyncio
import os
from datetime import datetime, timedelta

# Helper untuk memuat data JSON dari direktori utama bot
def load_json_from_root(file_path):
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"Peringatan: Tidak dapat memuat {file_path}. Pastikan file ada dan formatnya benar.")
        return []

def save_json_to_root(data, file_path):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    full_path = os.path.join(base_dir, file_path)
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

class SerbaSerbiGame(commands.Cog, name="🕹️ Serba-Serbi"):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = set()
        self.siapakah_aku_data = load_json_from_root('data/siapakah_aku.json')
        self.pernah_gak_pernah_data = load_json_from_root('data/pernah_gak_pernah.json')
        self.hitung_cepat_data = load_json_from_root('data/hitung_cepat.json')
        self.mata_mata_locations = load_json_from_root('data/mata_mata_locations.json')
        self.reward = {"rsw": 50, "exp": 100}

    # --- PENAMBAHAN INTEGRASI: Fungsi "Mata-mata" dan Pemberian Hadiah ---
    def get_anomaly_multiplier(self):
        """Mengecek apakah ada anomali EXP boost aktif dari cog DuniaHidup."""
        dunia_cog = self.bot.get_cog('DuniaHidup')
        if dunia_cog and dunia_cog.active_anomaly and dunia_cog.active_anomaly.get('type') == 'exp_boost':
            return dunia_cog.active_anomaly.get('effect', {}).get('multiplier', 1)
        return 1

    async def give_rewards_with_bonus_check(self, user: discord.Member, guild_id: int, channel: discord.TextChannel):
        """Fungsi baru yang menghitung bonus dan memanggil fungsi give_rewards asli."""
        anomaly_multiplier = self.get_anomaly_multiplier()
        
        # Simpan hadiah asli untuk dikembalikan nanti
        original_reward = self.reward.copy()
        
        # Modifikasi hadiah sementara berdasarkan multiplier
        self.reward = {
            "rsw": int(original_reward['rsw'] * anomaly_multiplier),
            "exp": int(original_reward['exp'] * anomaly_multiplier)
        }
        
        # Panggil fungsi give_rewards asli Anda yang tidak diubah
        self.give_rewards(user, guild_id)
        
        # Kembalikan self.reward ke nilai semula setelah selesai
        self.reward = original_reward
        
        if anomaly_multiplier > 1 and channel:
            await channel.send(f"✨ **BONUS ANOMALI!** {user.mention} mendapatkan hadiah yang dilipatgandakan!", delete_after=15)
    # ----------------------------------------------------------------------

    # FUNGSI give_rewards ASLI ANDA (TIDAK DIUBAH)
    def give_rewards(self, user: discord.Member, guild_id: int):
        user_id_str, guild_id_str = str(user.id), str(guild_id)
        
        bank_data = load_json_from_root('data/bank_data.json')
        if user_id_str not in bank_data: bank_data[user_id_str] = {'balance': 0, 'debt': 0}
        bank_data[user_id_str]['balance'] += self.reward['rsw']
        save_json_to_root(bank_data, 'data/bank_data.json')
        
        level_data = load_json_from_root('data/level_data.json')
        guild_data = level_data.setdefault(guild_id_str, {})
        user_data = guild_data.setdefault(user_id_str, {'exp': 0, 'level': 1})
        if 'exp' not in user_data: user_data['exp'] = 0
        user_data['exp'] += self.reward['exp']
        save_json_to_root(level_data, 'data/level_data.json')
        
    async def start_game_check(self, ctx):
        if ctx.channel.id in self.active_games:
            await ctx.send("Maaf, sudah ada permainan lain yang sedang berlangsung di channel ini.", delete_after=10)
            return False
        self.active_games.add(ctx.channel.id)
        return True

    def end_game_cleanup(self, channel_id):
        self.active_games.discard(channel_id)

    # =======================================================================================
    # ---> GAME 1: SIAPAKAH AKU? <---
    # =======================================================================================
    @commands.command(name="siapakahaku", help="Mulai sesi 10 soal tebak-tebakan kompetitif.")
    @commands.cooldown(1, 60, commands.BucketType.channel)
    async def siapakahaku(self, ctx):
        if not await self.start_game_check(ctx):
            return
        
        if not ctx.guild.me.guild_permissions.moderate_members:
            await ctx.send("⚠️ **Peringatan Izin:** Saya tidak memiliki izin `Moderate Members` untuk memberikan timeout jika ada yang spam jawaban.")
        
        if len(self.siapakah_aku_data) < 10:
            await ctx.send("Tidak cukup soal di database untuk memulai sesi (butuh minimal 10).")
            self.end_game_cleanup(ctx.channel.id)
            return
            
        questions = random.sample(self.siapakah_aku_data, 10)
        leaderboard = {}
        
        game_start_embed = discord.Embed(
            title="🕵️‍♂️ Sesi Kuis 'Siapakah Aku?' Dimulai!",
            description="Akan ada **10 soal** berturut-turut. Petunjuk akan muncul setiap **10 detik**.",
            color=0x1abc9c
        )
        await ctx.send(embed=game_start_embed)
        await asyncio.sleep(5)

        for i, item in enumerate(questions):
            word = item['name'].lower()
            clues = item['clues']
            attempts = {}
            timed_out_users = set()
            winner = None
            round_over = False

            embed = discord.Embed(
                title=f"SOAL #{i+1} dari 10",
                description=f"Kategori: **{item['category']}**",
                color=0x1abc9c
            )
            embed.set_footer(text="Anda punya 5x kesempatan menjawab salah per soal!")
            msg = await ctx.send(embed=embed)

            for clue_index, clue in enumerate(clues):
                if round_over: break

                embed.add_field(name=f"Petunjuk #{clue_index + 1}", value=f"_{clue}_", inline=False)
                await msg.edit(embed=embed)

                try:
                    async def listen_for_answer():
                        nonlocal winner, round_over
                        while True:
                            message = await self.bot.wait_for("message", check=lambda m: m.channel == ctx.channel and not m.author.bot)
                            if message.author.id in timed_out_users: continue
                            if message.content.lower() == word:
                                winner = message.author
                                round_over = True
                                return
                            else:
                                await message.add_reaction("❌")
                                user_attempts = attempts.get(message.author.id, 0) + 1
                                attempts[message.author.id] = user_attempts
                                
                                if user_attempts >= 5:
                                    timed_out_users.add(message.author.id)
                                    try:
                                        await message.author.timeout(timedelta(seconds=60), reason="Melebihi batas percobaan di game")
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan & di-timeout sementara.", delete_after=10)
                                    except discord.Forbidden:
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan di ronde ini.", delete_after=10)
                    
                    await asyncio.wait_for(listen_for_answer(), timeout=10.0)

                except asyncio.TimeoutError:
                    if clue_index == len(clues) - 1:
                        await ctx.send(f"Waktu habis! Jawaban yang benar adalah **{item['name']}**.")
                    else:
                        continue

            if winner:
                # --- PERUBAHAN: Memanggil fungsi reward baru ---
                await self.give_rewards_with_bonus_check(winner, ctx.guild.id, ctx.channel)
                # -----------------------------------------------
                await ctx.send(f"🎉 **Benar!** {winner.mention} berhasil menebak **{item['name']}**!")
                leaderboard[winner.name] = leaderboard.get(winner.name, 0) + 1

            for user_id in timed_out_users:
                member = ctx.guild.get_member(user_id)
                if member:
                    try:
                        await member.timeout(None, reason="Ronde game telah berakhir.")
                    except discord.Forbidden: pass

            if i < len(questions) - 1:
                await ctx.send(f"Soal berikutnya dalam **5 detik**...", delete_after=4.5)
                await asyncio.sleep(5)
        
        if leaderboard:
            sorted_leaderboard = sorted(leaderboard.items(), key=lambda item: item[1], reverse=True)
            leaderboard_text = "\n".join([f"{rank}. {name}: **{score}** poin" for rank, (name, score) in enumerate(sorted_leaderboard, 1)])
            final_embed = discord.Embed(title="🏆 Papan Skor Akhir 'Siapakah Aku?'", description=leaderboard_text, color=0xffd700)
            await ctx.send(embed=final_embed)
        else:
            await ctx.send("Sesi game berakhir tanpa ada pemenang.")
            
        self.end_game_cleanup(ctx.channel.id)
        
    # --- GAME 2: PERNAH GAK PERNAH ---
    @commands.command(name="pernahgak")
    async def pernahgak(self, ctx):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Kamu harus berada di voice channel untuk memulai game ini.", delete_after=10)
        vc = ctx.author.voice.channel
        members = [m for m in vc.members if not m.bot]
        if len(members) < 2:
            return await ctx.send("Game ini butuh minimal 2 orang di voice channel.", delete_after=10)
        if not await self.start_game_check(ctx): return
        statement = random.choice(self.pernah_gak_pernah_data)
        embed = discord.Embed(title="🤔 Pernah Gak Pernah...", description=f"## _{statement}_", color=0xf1c40f)
        embed.set_footer(text="Jawab dengan jujur menggunakan reaksi di bawah! Semua peserta dapat hadiah.")
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅"); await msg.add_reaction("❌")
        await asyncio.sleep(20)
        try:
            cached_msg = await ctx.channel.fetch_message(msg.id)
            pernah_count, gak_pernah_count, rewarded_users = 0, 0, set()
            for reaction in cached_msg.reactions:
                if str(reaction.emoji) in ["✅", "❌"]:
                    if str(reaction.emoji) == "✅": pernah_count = reaction.count - 1
                    if str(reaction.emoji) == "❌": gak_pernah_count = reaction.count - 1
                    async for user in reaction.users():
                        if not user.bot and user.id not in rewarded_users:
                            # --- PERUBAHAN: Memanggil fungsi reward baru ---
                            await self.give_rewards_with_bonus_check(user, ctx.guild.id, ctx.channel)
                            # -----------------------------------------------
                            rewarded_users.add(user.id)
            result_embed = discord.Embed(title="Hasil 'Pernah Gak Pernah'", color=0xf1c40f)
            result_embed.description = f"Untuk pernyataan:\n**_{statement}_**\n\n✅ **{pernah_count} orang** mengaku pernah.\n❌ **{gak_pernah_count} orang** mengaku tidak pernah."
            await ctx.send(embed=result_embed)
            if rewarded_users: await ctx.send(f"Terima kasih sudah berpartisipasi! {len(rewarded_users)} pemain telah mendapatkan hadiah.")
        except discord.NotFound: await ctx.send("Pesan game tidak ditemukan.")
        self.end_game_cleanup(ctx.channel.id)

    # --- GAME 3: HITUNG CEPAT ---
    @commands.command(name="hitungcepat")
    async def hitungcepat(self, ctx):
        if not await self.start_game_check(ctx): return
        item = random.choice(self.hitung_cepat_data)
        problem, answer = item['problem'], str(item['answer'])
        embed = discord.Embed(title="🧮 Hitung Cepat!", description=f"Selesaikan soal matematika ini secepat mungkin!\n\n## `{problem} = ?`", color=0xe74c3c)
        await ctx.send(embed=embed)
        try:
            async def listen_for_math_answer():
                while True:
                    message = await self.bot.wait_for("message", check=lambda m: m.channel == ctx.channel and not m.author.bot)
                    if message.content.strip() == answer: return message
                    else:
                        if message.content.strip().replace('-', '').isdigit(): await message.add_reaction("❌")
            winner_msg = await asyncio.wait_for(listen_for_math_answer(), timeout=30.0)
            winner = winner_msg.author
            # --- PERUBAHAN: Memanggil fungsi reward baru ---
            await self.give_rewards_with_bonus_check(winner, ctx.guild.id, ctx.channel)
            # -----------------------------------------------
            await ctx.send(f"⚡ **Luar Biasa Cepat!** {winner.mention} menjawab **{answer}** dengan benar!")
        except asyncio.TimeoutError:
            await ctx.send(f"Waktu habis! Jawaban yang benar adalah **{answer}**.")
        self.end_game_cleanup(ctx.channel.id)

    # --- GAME 4: MATA-MATA ---
    @commands.command(name="matamata")
    async def matamata(self, ctx):
        if not await self.start_game_check(ctx): return
        if not ctx.author.voice or not ctx.author.voice.channel: return await ctx.send("Kamu harus berada di voice channel untuk memulai game ini.", delete_after=10)
        vc = ctx.author.voice.channel
        members = [m for m in vc.members if not m.bot]
        if len(members) < 3: return await ctx.send("Game ini butuh minimal 3 orang di voice channel.", delete_after=10)
        
        location, spy = random.choice(self.mata_mata_locations), random.choice(members)
        for member in members:
            try:
                if member.id == spy.id: await member.send("🤫 Kamu adalah **Mata-Mata**! Tugasmu adalah menebak lokasi tanpa ketahuan.")
                else: await member.send(f"📍 Lokasi rahasia adalah: **{location}**. Temukan siapa mata-matanya!")
            except discord.Forbidden:
                await ctx.send(f"Gagal memulai game karena tidak bisa mengirim DM ke {member.mention}. Pastikan DM-nya terbuka."); self.end_game_cleanup(ctx.channel.id); return
        
        embed = discord.Embed(title="🎭 Game Mata-Mata Dimulai!", color=0x7289da); embed.description = "Peran dan lokasi telah dikirim melalui DM. Salah satu dari kalian adalah mata-mata!\n\n**Tujuan Pemain Biasa:** Temukan mata-mata.\n**Tujuan Mata-Mata:** Bertahan tanpa ketahuan & menebak lokasi.\n\nWaktu diskusi: **3 menit**. Gunakan `!tuduh @user` untuk menuduh di akhir."; embed.set_footer(text="Diskusi bisa dimulai sekarang!"); await ctx.send(embed=embed)
        
        if not hasattr(self.bot, 'active_spyfall_games'): self.bot.active_spyfall_games = {}
        self.bot.active_spyfall_games[ctx.channel.id] = {'spy': spy, 'location': location, 'players': members}
        
        await asyncio.sleep(180) 
        
        if ctx.channel.id in self.active_games:
            await ctx.send("Waktu diskusi habis! Mata-mata menang karena tidak ada yang dituduh!")
            # --- PERUBAHAN: Memanggil fungsi reward baru ---
            await self.give_rewards_with_bonus_check(spy, ctx.guild.id, ctx.channel)
            # -----------------------------------------------
            self.end_game_cleanup(ctx.channel.id)
            if ctx.channel.id in self.bot.active_spyfall_games: del self.bot.active_spyfall_games[ctx.channel.id]

    @commands.command(name="tuduh")
    async def tuduh(self, ctx, member: discord.Member):
        if not hasattr(self.bot, 'active_spyfall_games') or ctx.channel.id not in self.bot.active_spyfall_games: return
        
        game = self.bot.active_spyfall_games[ctx.channel.id]
        spy, location, players = game['spy'], game['location'], game['players']
        if ctx.author not in players or member not in players: return await ctx.send("Hanya pemain yang berpartisipasi yang bisa menuduh atau dituduh.")
        
        await ctx.send(f"🚨 **VOTING AKHIR!** {ctx.author.mention} menuduh {member.mention} sebagai mata-mata.")
        if member.id == spy.id:
            await ctx.send(f"**Tuduhan Benar!** {member.mention} memang mata-matanya. Lokasinya adalah **{location}**. Selamat kepada tim warga, kalian semua mendapat hadiah!")
            for p in players:
                if p.id != spy.id:
                    # --- PERUBAHAN: Memanggil fungsi reward baru ---
                    await self.give_rewards_with_bonus_check(p, ctx.guild.id, ctx.channel)
                    # -----------------------------------------------
        else:
            await ctx.send(f"**Tuduhan Salah!** {member.mention} bukan mata-matanya. **Mata-mata ({spy.mention}) menang!** Lokasinya adalah **{location}**.")
            # --- PERUBAHAN: Memanggil fungsi reward baru ---
            await self.give_rewards_with_bonus_check(spy, ctx.guild.id, ctx.channel)
            # -----------------------------------------------
            
        self.end_game_cleanup(ctx.channel.id)
        if ctx.channel.id in self.bot.active_spyfall_games: del self.bot.active_spyfall_games[ctx.channel.id]

async def setup(bot):
    await bot.add_cog(SerbaSerbiGame(bot))

