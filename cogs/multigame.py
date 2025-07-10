import discord
from discord.ext import commands, tasks
import json
import random
import asyncio
import os
from datetime import datetime, time, timedelta
import pytz # Import pytz untuk zona waktu

# --- Helper Functions (Wajib ada di awal) ---
def load_json_from_root(file_path):
    """Memuat data JSON dari file yang berada di root direktori proyek."""
    try:
        # Menggunakan os.path.join untuk memastikan path yang benar di berbagai OS
        # dan os.path.dirname(__file__) untuk mendapatkan direktori file saat ini (cogs)
        # Kemudian '..' untuk naik satu level ke root proyek
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True) # Pastikan direktori ada
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"Peringatan: Tidak dapat memuat {file_path}. Pastikan file ada dan formatnya benar.")
        # Mengembalikan struktur default berdasarkan nama file
        if 'config.json' in file_path:
            return {'last_spy_id': None}
        if 'bank_data.json' in file_path or 'level_data.json' in file_path or 'protected_users.json' in file_path or 'sick_users_cooldown.json' in file_path:
            return {}
        # Untuk file data game yang berisi list
        if any(key in file_path for key in ['monsters', 'anomalies', 'medicines', 'siapakah_aku', 'pernah_gak_pernah', 'hitung_cepat', 'mata_mata_locations', 'deskripsi_tebak', 'perang_otak', 'cerita_pembuka', 'teka_teki_harian', 'donation_buttons']):
            return [] # Mengembalikan list kosong untuk data game dan tombol donasi
        return {} # Default fallback

def save_json_to_root(data, file_path):
    """Menyimpan data ke file JSON di root direktori proyek."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    full_path = os.path.join(base_dir, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True) # Pastikan direktori ada
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# New DonationView - MODIFIED TO LOAD BUTTONS FROM JSON
class DonationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Keep buttons active indefinitely
        self.load_donation_buttons()

    def load_donation_buttons(self):
        # Path relatif ke root proyek
        donation_buttons_data = load_json_from_root('data/donation_buttons.json')
        
        if not donation_buttons_data:
            print("Peringatan: File 'data/donation_buttons.json' kosong atau tidak ditemukan. Menggunakan tombol default.")
            # Default buttons if JSON is empty or not found
            default_buttons = [
                {"label": "Dukung via Bagi-Bagi!", "url": "https://bagibagi.co/Rh7155"},
                {"label": "Donasi via Saweria!", "url": "https://saweria.co/RH7155"}
            ]
            donation_buttons_data = default_buttons

        for button_info in donation_buttons_data:
            if "label" in button_info and "url" in button_info:
                button = discord.ui.Button(
                    label=button_info["label"],
                    style=discord.ButtonStyle.link,
                    url=button_info["url"]
                )
                self.add_item(button)
            else:
                print(f"Peringatan: Format tombol donasi tidak valid: {button_info}")

class TicTacToeView(discord.ui.View):
    def __init__(self, game_cog, player1, player2):
        super().__init__(timeout=300)
        self.game_cog = game_cog
        self.player1 = player1
        self.player2 = player2
        self.current_player = player1
        self.board = [None] * 9
        self.winner = None
        for i in range(9):
            self.add_item(TicTacToeButton(row=i // 3))

    async def update_board(self, interaction: discord.Interaction):
        winning_combinations = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
        for combo in winning_combinations:
            if self.board[combo[0]] is not None and self.board[combo[0]] == self.board[combo[1]] == self.board[combo[2]]:
                self.winner = self.current_player
                break
        is_draw = all(spot is not None for spot in self.board) and self.winner is None
        embed = interaction.message.embeds[0]
        if self.winner:
            embed.description = f"🎉 **{self.winner.mention} Menang!** 🎉"
            embed.color = discord.Color.gold()
            await self.game_cog.give_rewards_with_bonus_check(self.winner, interaction.guild.id, interaction.channel)
            for item in self.children: item.disabled = True
        elif is_draw:
            embed.description = "⚖️ **Permainan Berakhir Seri!**"
            embed.color = discord.Color.light_grey()
            for player in [self.player1, self.player2]:
                await self.game_cog.give_rewards_with_bonus_check(player, interaction.guild.id, interaction.channel)
            for item in self.children: item.disabled = True
        else:
            self.current_player = self.player2 if self.current_player == self.player1 else self.player1
            embed.description = f"Giliran: **{self.current_player.mention}**"
        await interaction.message.edit(embed=embed, view=self)
        if self.winner or is_draw:
            self.stop()
            await self.game_cog.end_game_cleanup(interaction.channel.id, interaction.channel) # Pass channel object

class TicTacToeButton(discord.ui.Button):
    def __init__(self, row: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=row)

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view
        if interaction.user != view.current_player:
            return await interaction.response.send_message("Bukan giliranmu!", ephemeral=True)
        await interaction.response.defer()
        self.style = discord.ButtonStyle.danger if view.current_player == view.player1 else discord.ButtonStyle.success
        self.label = "X" if view.current_player == view.player1 else "O"
        self.disabled = True
        button_index = self.view.children.index(self)
        view.board[button_index] = self.label
        await view.update_board(interaction)

class UltimateGameArena(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = set()
        self.spyfall_game_states = {}
        
        self.config_data = load_json_from_root('data/config.json')
        self.last_spy_id = self.config_data.get('last_spy_id', None)

        self.siapakah_aku_data = load_json_from_root('data/siapakah_aku.json')
        self.pernah_gak_pernah_data = load_json_from_root('data/pernah_gak_pernah.json')
        self.hitung_cepat_data = load_json_from_root('data/hitung_cepat.json')
        self.mata_mata_locations = load_json_from_root('data/mata_mata_locations.json')
        self.deskripsi_data = load_json_from_root('data/deskripsi_tebak.json') # Perbaikan bug di sini
        self.perang_otak_data = load_json_from_root('data/perang_otak.json') 
        self.cerita_pembuka_data = load_json_from_root('data/cerita_pembuka.json')
        self.tekateki_harian_data = load_json_from_root('data/teka_teki_harian.json')

        self.reward = {"rsw": 50, "exp": 100}
        self.daily_puzzle = None
        self.daily_puzzle_solvers = set()
        self.daily_puzzle_channel_id = 765140300145360896 # Ganti dengan ID channel Anda
        self.post_daily_puzzle.start()

        # Dictionary untuk melacak percobaan jawaban per user per soal
        self.quiz_attempts_per_question = {} # {channel_id: {user_id: attempts}}
        self.cooldown_users = {} # {user_id: datetime_obj}

    def cog_unload(self):
        self.post_daily_puzzle.cancel()

    def get_anomaly_multiplier(self):
        dunia_cog = self.bot.get_cog('DuniaHidup')
        if dunia_cog and dunia_cog.active_anomaly and dunia_cog.active_anomaly.get('type') == 'exp_boost':
            return dunia_cog.active_anomaly.get('effect', {}).get('multiplier', 1)
        return 1

    async def give_rewards_with_bonus_check(self, user: discord.Member, guild_id: int, channel: discord.TextChannel):
        anomaly_multiplier = self.get_anomaly_multiplier()
        original_reward = self.reward.copy()
        current_rsw_reward = int(original_reward['rsw'] * anomaly_multiplier)
        current_exp_reward = int(original_reward['exp'] * anomaly_multiplier)
        
        self.give_rewards(user, guild_id, current_rsw_reward, current_exp_reward)
        
        if anomaly_multiplier > 1 and channel:
            await channel.send(f"✨ **BONUS ANOMALI!** {user.mention} mendapatkan hadiah yang dilipatgandakan!", delete_after=15)

    def give_rewards(self, user: discord.Member, guild_id: int, rsw_amount: int, exp_amount: int):
        user_id_str, guild_id_str = str(user.id), str(guild_id)
        bank_data = load_json_from_root('data/bank_data.json')
        bank_data.setdefault(user_id_str, {'balance': 0, 'debt': 0})['balance'] += rsw_amount
        save_json_to_root(bank_data, 'data/bank_data.json')
        level_data = load_json_from_root('data/level_data.json')
        guild_data = level_data.setdefault(guild_id_str, {})
        user_data = guild_data.setdefault(user_id_str, {'exp': 0, 'level': 1})
        user_data.setdefault('exp', 0)
        user_data['exp'] += exp_amount
        save_json_to_root(level_data, 'data/level_data.json')

    async def start_game_check(self, ctx):
        if ctx.channel.id in self.active_games:
            await ctx.send("Maaf, sudah ada permainan lain di channel ini. Tunggu selesai ya!", delete_after=10)
            return False
        self.active_games.add(ctx.channel.id)
        return True

    async def end_game_cleanup(self, channel_id, channel_obj=None):
        self.active_games.discard(channel_id)
        if channel_id in self.spyfall_game_states:
            spy_member = self.spyfall_game_states[channel_id]['spy']
            self.last_spy_id = spy_member.id if spy_member else None
            
            self.config_data['last_spy_id'] = self.last_spy_id
            save_json_to_root(self.config_data, 'data/config.json')
            
            del self.spyfall_game_states[channel_id]
        print(f"Game cleanup complete for channel {channel_id}.")

        # Reset quiz attempts and cooldowns for this channel
        if channel_id in self.quiz_attempts_per_question:
            del self.quiz_attempts_per_question[channel_id]
        # Clear cooldowns for users who were in this channel's game
        # (This is a simplified approach, a more robust one might track users per channel)
        users_in_cooldown_from_this_game = [
            user_id for user_id, cooldown_end_time in self.cooldown_users.items()
            if cooldown_end_time > datetime.now() # only clear active cooldowns
        ]
        for user_id in users_in_cooldown_from_this_game:
            if user_id in self.cooldown_users:
                del self.cooldown_users[user_id]


        # Add donation buttons at the end of the game
        if channel_obj:
            donation_message = (
                "🎮 **Permainan Telah Usai!** Terima kasih sudah bermain bersama kami.\n\n"
                "Apakah kamu menikmati petualangan dan keseruan yang kami hadirkan?\n"
                "Dukung terus pengembangan bot ini agar kami bisa terus berinovasi dan "
                "memberikan pengalaman bermain yang lebih seru lagi!\n\n"
                "Donasi sekecil apa pun sangat berarti untuk kami! 🙏"
            )
            donation_view = DonationView()
            await channel_obj.send(donation_message, view=donation_view)


    # --- GAME 1: SIAPAKAH AKU? ---
    @commands.command(name="siapakahaku", help="Mulai sesi 10 soal tebak-tebakan kompetitif.")
    @commands.cooldown(1, 60, commands.BucketType.channel)
    async def siapakahaku(self, ctx):
        if not await self.start_game_check(ctx): return
        if len(self.siapakah_aku_data) < 10:
            await ctx.send("Tidak cukup soal di database untuk memulai sesi (butuh minimal 10).")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            return
        
        questions = random.sample(self.siapakah_aku_data, 10)
        leaderboard = {}
        
        # Inisialisasi attempts dan cooldown untuk channel ini
        self.quiz_attempts_per_question[ctx.channel.id] = {}
        
        game_start_embed = discord.Embed(title="🕵️‍♂️ Sesi Kuis 'Siapakah Aku?' Dimulai!", description="Akan ada **10 soal** berturut-turut. Petunjuk akan muncul setiap **10 detik**.", color=0x1abc9c)
        await ctx.send(embed=game_start_embed)
        await asyncio.sleep(5)
        
        for i, item in enumerate(questions):
            word = item['name'].lower()
            clues = item['clues']
            
            # Reset attempts for the new question
            self.quiz_attempts_per_question[ctx.channel.id] = {} 
            
            winner = None
            round_over = False
            
            embed = discord.Embed(title=f"SOAL #{i+1} dari 10", description=f"Kategori: **{item['category']}**", color=0x1abc9c)
            embed.set_footer(text="Anda punya 2x kesempatan menjawab salah per soal! Jika lebih, Anda di-cooldown.")
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
                            
                            # Cek apakah user sedang dalam cooldown
                            if message.author.id in self.cooldown_users:
                                if datetime.now() < self.cooldown_users[message.author.id]:
                                    # User masih dalam cooldown, abaikan pesan ini
                                    try:
                                        await message.delete() # Hapus pesan yang dikirim saat cooldown
                                    except discord.Forbidden:
                                        pass # Tidak bisa menghapus pesan
                                    continue # Lanjutkan menunggu pesan lain
                                else:
                                    # Cooldown sudah berakhir, hapus dari daftar
                                    del self.cooldown_users[message.author.id]

                            # Lacak percobaan user
                            user_attempts = self.quiz_attempts_per_question[ctx.channel.id].setdefault(message.author.id, 0)
                            
                            if message.content.lower() == word:
                                winner = message.author
                                round_over = True
                                return
                            else:
                                await message.add_reaction("❌")
                                user_attempts += 1
                                self.quiz_attempts_per_question[ctx.channel.id][message.author.id] = user_attempts
                                
                                if user_attempts >= 2: # Maksimal 2 kali percobaan salah
                                    # Beri cooldown 30 detik (atau sampai soal selesai)
                                    cooldown_end_time = datetime.now() + timedelta(seconds=30)
                                    self.cooldown_users[message.author.id] = cooldown_end_time
                                    
                                    try:
                                        # Timeout user di channel jika bot punya izin
                                        # Discord API v2: timeout() requires Manage Messages permission
                                        await message.author.timeout(timedelta(seconds=30), reason="Melebihi batas percobaan kuis")
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan & di-timeout sementara (30 detik).", delete_after=10)
                                    except discord.Forbidden:
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan di ronde ini. Anda tidak bisa menjawab sampai soal ini selesai.", delete_after=10)
                                    except Exception as e:
                                        print(f"Error applying timeout: {e}")
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan di ronde ini. Anda tidak bisa menjawab sampai soal ini selesai.", delete_after=10)

                    await asyncio.wait_for(listen_for_answer(), timeout=10.0) # Waktu per petunjuk
                except asyncio.TimeoutError:
                    if clue_index == len(clues) - 1:
                        await ctx.send(f"Waktu habis! Jawaban yang benar adalah **{item['name']}**.")
                    else:
                        continue
            
            if winner:
                await self.give_rewards_with_bonus_check(winner, ctx.guild.id, ctx.channel)
                await ctx.send(f"🎉 **Benar!** {winner.mention} berhasil menebak **{item['name']}**!")
                leaderboard[winner.name] = leaderboard.get(winner.name, 0) + 1
            
            # Hapus cooldown untuk semua user di channel ini setelah soal selesai
            for user_id in list(self.cooldown_users.keys()):
                if ctx.guild.get_member(user_id) and ctx.guild.get_member(user_id).voice and ctx.guild.get_member(user_id).voice.channel == ctx.channel:
                    if user_id in self.cooldown_users:
                        del self.cooldown_users[user_id]
                    member = ctx.guild.get_member(user_id)
                    if member:
                        try:
                            await member.timeout(None, reason="Ronde game telah berakhir.") # Hapus timeout Discord
                        except discord.Forbidden:
                            pass # Bot tidak punya izin untuk menghapus timeout

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
        
        await self.end_game_cleanup(ctx.channel.id, ctx.channel)

    # --- GAME 2: PERNAH GAK PERNAH (Disesuaikan) ---
    @commands.command(name="pernahgak", help="Mulai game 'Pernah Gak Pernah' di voice channelmu.")
    @commands.cooldown(1, 30, commands.BucketType.channel)
    async def pernahgak(self, ctx):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Kamu harus berada di voice channel untuk memulai game ini.", delete_after=10)
        vc = ctx.author.voice.channel
        members = [m for m m.bot]
        if len(members) < 2:
            return await ctx.send("Game ini butuh minimal 2 orang di voice channel.", delete_after=10)
        if not await self.start_game_check(ctx):
            return

        if len(self.pernah_gak_pernah_data) < 10:
            await ctx.send("Tidak cukup pertanyaan di database untuk sesi ini (butuh minimal 10).")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            return

        questions = random.sample(self.pernah_gak_pernah_data, 10)
        session_results = [] # Untuk menyimpan hasil setiap pertanyaan

        await ctx.send(embed=discord.Embed(title="🤔 Sesi 'Pernah Gak Pernah' Dimulai!", description="Akan ada **10 pertanyaan**! Siapkan reaksimu!", color=0xf1c40f))
        await asyncio.sleep(3)

        for i, statement in enumerate(questions):
            embed = discord.Embed(title=f"❓ Pertanyaan #{i+1} dari 10", description=f"## _{statement}_", color=0xf1c40f)
            embed.set_footer(text="Jawab dengan jujur menggunakan reaksi ✅ (Pernah) atau ❌ (Tidak Pernah) di bawah! Waktu 15 detik.")
            msg = await ctx.send(embed=embed)
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            
            await asyncio.sleep(15) # Waktu untuk bereaksi

            try:
                cached_msg = await ctx.channel.fetch_message(msg.id)
                
                pernah_users = []
                gak_pernah_users = []
                round_rewarded_users = set() 
                
                for reaction in cached_msg.reactions:
                    if str(reaction.emoji) == "✅":
                        async for user in reaction.users():
                            if not user.bot and user in members and user.id not in round_rewarded_users:
                                pernah_users.append(user.display_name)
                                await self.give_rewards_with_bonus_check(user, ctx.guild.id, ctx.channel)
                                round_rewarded_users.add(user.id)
                    elif str(reaction.emoji) == "❌":
                        async for user in reaction.users():
                            if not user.bot and user in members and user.id not in round_rewarded_users:
                                gak_pernah_users.append(user.display_name)
                                await self.give_rewards_with_bonus_check(user, ctx.guild.id, ctx.channel)
                                round_rewarded_users.add(user.id)
                
                session_results.append({
                    "statement": statement,
                    "pernah_users": pernah_users,
                    "gak_pernah_users": gak_pernah_users
                })

                if i < len(questions) - 1:
                    await ctx.send(f"Pertanyaan berikutnya dalam **3 detik**...", delete_after=2.5)
                    await asyncio.sleep(3)
            except discord.NotFound:
                await ctx.send("Pesan pertanyaan tidak ditemukan, sesi Pernah Gak Pernah terganggu.")
                break
            except Exception as e:
                print(f"Error in Pernah Gak Pernah round: {e}")
                break

        # Ringkasan Akhir
        if session_results:
            summary_embed = discord.Embed(title="📊 Ringkasan Sesi 'Pernah Gak Pernah'", color=0x3498db)
            summary_text = ""
            for i, result in enumerate(session_results):
                summary_text += f"**{i+1}. __{result['statement']}__**\n"
                summary_text += f"  ✅ Pernah ({len(result['pernah_users'])}): {'Tidak ada' if not result['pernah_users'] else ', '.join(result['pernah_users'])}\n"
                summary_text += f"  ❌ Tidak Pernah ({len(result['gak_pernah_users'])}): {'Tidak ada' if not result['gak_pernah_users'] else ', '.join(result['gak_pernah_users'])}\n\n"
            
            summary_embed.description = summary_text
            await ctx.send(embed=summary_embed)
        else:
            await ctx.send("Sesi 'Pernah Gak Pernah' berakhir tanpa hasil yang tercatat.")

        await self.end_game_cleanup(ctx.channel.id, ctx.channel)

    # --- GAME 3: HITUNG CEPAT (Disesuaikan) ---
    @commands.command(name="hitungcepat", help="Selesaikan soal matematika secepat mungkin!")
    @commands.cooldown(1, 15, commands.BucketType.channel)
    async def hitungcepat(self, ctx):
        if not await self.start_game_check(ctx): return

        if len(self.hitung_cepat_data) < 10:
            await ctx.send("Tidak cukup soal di database untuk sesi ini (butuh minimal 10).")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            return
        
        problems = random.sample(self.hitung_cepat_data, 10)
        leaderboard = {} # {user_id: score}

        # Inisialisasi attempts dan cooldown untuk channel ini
        self.quiz_attempts_per_question[ctx.channel.id] = {}

        await ctx.send(embed=discord.Embed(title="⚡ Sesi Hitung Cepat Dimulai!", description="Akan ada **10 soal**! Jawab dengan cepat dan benar!", color=0xe74c3c))
        await asyncio.sleep(3)

        for i, item in enumerate(problems):
            problem, answer = item['problem'], str(item['answer'])
            
            # Reset attempts for the new question
            self.quiz_attempts_per_question[ctx.channel.id] = {}
            
            embed = discord.Embed(title=f"🧮 Soal #{i+1} dari 10", description=f"## `{problem} = ?`", color=0xe74c3c)
            msg = await ctx.send(embed=embed)
            
            try:
                async def listen_for_math_answer():
                    while True:
                        message = await self.bot.wait_for("message", check=lambda m: m.channel == ctx.channel and not m.author.bot)
                        
                        # Cek apakah user sedang dalam cooldown
                        if message.author.id in self.cooldown_users:
                            if datetime.now() < self.cooldown_users[message.author.id]:
                                try:
                                    await message.delete()
                                except discord.Forbidden:
                                    pass
                                continue
                            else:
                                del self.cooldown_users[message.author.id]

                        # Lacak percobaan user
                        user_attempts = self.quiz_attempts_per_question[ctx.channel.id].setdefault(message.author.id, 0)

                        if message.content.strip() == answer:
                            return message
                        else:
                            if message.content.strip().replace('-', '').isdigit(): # Hanya bereaksi jika inputnya angka
                                await message.add_reaction("❌")
                                user_attempts += 1
                                self.quiz_attempts_per_question[ctx.channel.id][message.author.id] = user_attempts

                                if user_attempts >= 2: # Maksimal 2 kali percobaan salah
                                    cooldown_end_time = datetime.now() + timedelta(seconds=30)
                                    self.cooldown_users[message.author.id] = cooldown_end_time
                                    try:
                                        await message.author.timeout(timedelta(seconds=30), reason="Melebihi batas percobaan kuis")
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan & di-timeout sementara (30 detik).", delete_after=10)
                                    except discord.Forbidden:
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan di ronde ini. Anda tidak bisa menjawab sampai soal ini selesai.", delete_after=10)
                                    except Exception as e:
                                        print(f"Error applying timeout: {e}")
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan di ronde ini. Anda tidak bisa menjawab sampai soal ini selesai.", delete_after=10)
                
                winner_msg = await asyncio.wait_for(listen_for_math_answer(), timeout=15.0)
                winner = winner_msg.author
                
                leaderboard[winner.id] = leaderboard.get(winner.id, 0) + 1
                await ctx.send(f"⚡ **Benar!** {winner.mention} menjawab **{answer}** dengan benar!")
                
                await self.give_rewards_with_bonus_check(winner, ctx.guild.id, ctx.channel)
                
            except asyncio.TimeoutError:
                await ctx.send(f"Waktu habis! Jawaban yang benar adalah **{answer}**.")
            except Exception as e:
                print(f"Error in Hitung Cepat round: {e}")
            
            # Hapus cooldown untuk semua user di channel ini setelah soal selesai
            for user_id in list(self.cooldown_users.keys()):
                if ctx.guild.get_member(user_id) and ctx.guild.get_member(user_id).voice and ctx.guild.get_member(user_id).voice.channel == ctx.channel:
                    if user_id in self.cooldown_users:
                        del self.cooldown_users[user_id]
                    member = ctx.guild.get_member(user_id)
                    if member:
                        try:
                            await member.timeout(None, reason="Ronde game telah berakhir.")
                        except discord.Forbidden:
                            pass

            if i < len(problems) - 1:
                await ctx.send(f"Soal berikutnya dalam **3 detik**...", delete_after=2.5)
                await asyncio.sleep(3)
        
        # Tampilkan Leaderboard 5 Besar
        if leaderboard:
            sorted_leaderboard = sorted(leaderboard.items(), key=lambda item: item[1], reverse=True)
            
            leaderboard_text = ""
            for rank, (user_id, score) in enumerate(sorted_leaderboard[:5], 1):
                user_obj = ctx.guild.get_member(user_id)
                user_name = user_obj.display_name if user_obj else f"Pengguna Tidak Dikenal ({user_id})"
                leaderboard_text += f"{rank}. **{user_name}**: **{score}** jawaban benar\n"
            
            final_embed = discord.Embed(title="🏆 Papan Skor Akhir Hitung Cepat (Top 5)", description=leaderboard_text, color=0x2ecc71)
            await ctx.send(embed=final_embed)
        else:
            await ctx.send("Sesi Hitung Cepat berakhir tanpa ada jawaban benar.")

        await self.end_game_cleanup(ctx.channel.id, ctx.channel)


    # --- GAME 4: MATA-MATA ---
    @commands.command(name="matamata", help="Mulai game Mata-Mata. Temukan siapa mata-matanya!")
    @commands.cooldown(1, 300, commands.BucketType.channel)
    async def matamata(self, ctx):
        if not await self.start_game_check(ctx):
            return
        
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("Kamu harus berada di voice channel untuk memulai game ini.", delete_after=10)
            await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            return
        
        vc = ctx.author.voice.channel
        members = [m for m in vc.members if not m.bot]
        if len(members) < 3:
            await ctx.send("Game ini butuh minimal 3 orang di voice channel.", delete_after=10)
            await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            return
        
        if not self.mata_mata_locations:
            await ctx.send("Tidak ada lokasi yang tersedia untuk game Mata-Mata. Mohon tambahkan data lokasi.", delete_after=10)
            await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            return

        location = random.choice(self.mata_mata_locations)
        
        eligible_spies = [m for m in members if m.id != self.last_spy_id]
        
        if eligible_spies:
            spy = random.choice(eligible_spies)
        else:
            spy = random.choice(members)

        self.spyfall_game_states[ctx.channel.id] = {
            'spy': spy,
            'location': location,
            'players': members,
            'discussion_start_time': datetime.utcnow(),
            'vote_in_progress': False,
            'game_ended': False
        }

        failed_dms = []
        for member in members:
            try:
                if member.id == spy.id:
                    await member.send("🤫 Kamu adalah **Mata-Mata**! Tugasmu adalah menebak lokasi tanpa ketahuan.")
                else:
                    await member.send(f"📍 Lokasi rahasia adalah: **{location}**. Temukan siapa mata-matanya!")
            except discord.Forbidden:
                failed_dms.append(member.mention)
        
        if failed_dms:
            await ctx.send(f"Gagal memulai game karena tidak bisa mengirim DM ke: {', '.join(failed_dms)}. Pastikan DM-nya terbuka."); 
            await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            return

        embed = discord.Embed(title="🎭 Game Mata-Mata Dimulai!", color=0x7289da)
        embed.description = "Peran dan lokasi telah dikirim melalui DM. Salah satu dari kalian adalah mata-mata!\n\n" \
                            "**Tujuan Pemain Biasa:** Temukan mata-matanya.\n" \
                            "**Tujuan Mata-Mata:** Bertahan tanpa ketahuan & menebak lokasi.\n\n" \
                            "Waktu diskusi: **5 menit**. Kalian bisa `!tuduh @user` kapan saja (akan memicu voting).\n\n" \
                            "**Diskusi bisa dimulai sekarang!**"
        embed.set_footer(text="Jika 5 menit habis, fase penuduhan akhir dimulai, atau mata-mata bisa coba menebak lokasi.")
        game_start_message = await ctx.send(embed=embed)
        
        self.spyfall_game_states[ctx.channel.id]['game_start_message_id'] = game_start_message.id

        try:
            await asyncio.sleep(300)
            
            if ctx.channel.id not in self.spyfall_game_states or self.spyfall_game_states[ctx.channel.id]['game_ended']:
                return

            await ctx.send(f"⏰ **Waktu diskusi 5 menit habis!** Sekarang adalah fase penuduhan akhir. "
                           f"Pemain biasa bisa menggunakan `!tuduh @nama_pemain` untuk memulai voting.\n"
                           f"Mata-mata bisa menggunakan `!ungkap_lokasi <lokasi>` untuk mencoba menebak lokasi.\n\n"
                           f"Jika mata-mata berhasil menebak lokasi dengan benar dan belum dituduh, mata-mata menang! Jika tidak ada yang menuduh atau mata-mata tidak menebak lokasi dalam waktu 2 menit, maka **mata-mata menang secara otomatis.**")
            
            await asyncio.sleep(120)

            if ctx.channel.id in self.spyfall_game_states and not self.spyfall_game_states[ctx.channel.id]['game_ended']:
                await ctx.send(f"Waktu penuduhan habis! Mata-mata ({spy.mention}) menang karena tidak ada yang berhasil menuduh atau mata-mata tidak mengungkapkan lokasi! Lokasi sebenarnya adalah **{location}**.")
                await self.give_rewards_with_bonus_check(spy, ctx.guild.id, ctx.channel)
                self.spyfall_game_states[ctx.channel.id]['game_ended'] = True
                await self.end_game_cleanup(ctx.channel.id, ctx.channel)

        except asyncio.CancelledError:
            print(f"Mata-Mata game in channel {ctx.channel.id} was cancelled.")
        except Exception as e:
            print(f"Error in Mata-Mata game loop for channel {ctx.channel.id}: {e}")
        finally:
            if ctx.channel.id in self.spyfall_game_states and not self.spyfall_game_states[ctx.channel.id]['game_ended']:
                self.spyfall_game_states[ctx.channel.id]['game_ended'] = True
                await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            elif ctx.channel.id not in self.spyfall_game_states:
                print(f"Mata-Mata game in channel {ctx.channel.id} already cleaned up.")


    @commands.command(name="tuduh", help="Tuduh seseorang sebagai mata-mata.")
    async def tuduh(self, ctx, member: discord.Member):
        if ctx.channel.id not in self.spyfall_game_states:
            return await ctx.send("Game Mata-Mata belum dimulai di channel ini.", ephemeral=True)
        
        game = self.spyfall_game_states[ctx.channel.id]
        spy, location, players = game['spy'], game['location'], game['players']

        if ctx.author not in players or member not in players: 
            return await ctx.send("Hanya pemain yang berpartisipasi yang bisa menuduh atau dituduh.", ephemeral=True)
        
        if game['vote_in_progress']:
            return await ctx.send("Saat ini sedang ada voting lain. Tunggu sampai selesai.", ephemeral=True)

        game['vote_in_progress'] = True

        vote_embed = discord.Embed(
            title="🗳️ VOTING UNTUK MATA-MATA!",
            description=f"{ctx.author.mention} menuduh {member.mention} sebagai mata-mata!\n\n"
                        f"**Setuju (✅) atau Tidak Setuju (❌)?**",
            color=discord.Color.red()
        )
        vote_embed.set_footer(text="Voting akan berakhir dalam 30 detik. Mayoritas menentukan.")
        
        vote_msg = await ctx.send(embed=vote_embed)
        await vote_msg.add_reaction("✅")
        await vote_msg.add_reaction("❌")
        
        await asyncio.sleep(30)
        
        try:
            cached_vote_msg = await ctx.channel.fetch_message(vote_msg.id)
            
            valid_voters_ids = {p.id for p in players if p.id != ctx.author.id and p.id != member.id}
            
            final_yes_votes = 0
            final_no_votes = 0
            voted_users = set()

            for reaction in cached_vote_msg.reactions:
                if str(reaction.emoji) == "✅":
                    async for user_reaction in reaction.users():
                        if not user_reaction.bot and user_reaction.id in valid_voters_ids and user_reaction.id not in voted_users:
                            final_yes_votes += 1
                            voted_users.add(user_reaction.id)
                elif str(reaction.emoji) == "❌":
                    async for user_reaction in reaction.users():
                        if not user_reaction.bot and user_reaction.id in valid_voters_ids and user_reaction.id not in voted_users:
                            final_no_votes += 1
                            voted_users.add(user_reaction.id)
            
            if not voted_users:
                await ctx.send("Voting gagal karena tidak ada pemain yang berpartisipasi dalam voting. Permainan dilanjutkan.")
                game['vote_in_progress'] = False
                return

            if final_yes_votes > final_no_votes:
                await ctx.send(f"✅ **Voting Berhasil!** Mayoritas setuju {member.mention} adalah mata-mata.")
                if member.id == spy.id:
                    await ctx.send(f"**Tuduhan Benar!** {member.mention} memang mata-matanya. Lokasinya adalah **{location}**.")
                    await ctx.send(f"Selamat kepada tim warga, kalian semua mendapat hadiah!")
                    for p in players:
                        if p.id != spy.id: await self.give_rewards_with_bonus_check(p, ctx.guild.id, ctx.channel)
                else:
                    await ctx.send(f"**Tuduhan Salah!** {member.mention} bukan mata-matanya. Lokasi sebenarnya adalah **{location}**.")
                    await ctx.send(f"**Mata-mata ({spy.mention}) menang!**")
                    await self.give_rewards_with_bonus_check(spy, ctx.guild.id, ctx.channel)
                
                game['game_ended'] = True
                await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            else:
                await ctx.send(f"❌ **Voting Gagal.** Tidak cukup suara untuk menuduh {member.mention}. Permainan dilanjutkan!")
                game['vote_in_progress'] = False
        
        except discord.NotFound:
            await ctx.send("Pesan voting tidak ditemukan.")
            game['vote_in_progress'] = False
        except Exception as e:
            print(f"Error during voting in channel {ctx.channel.id}: {e}")
            game['vote_in_progress'] = False


    @commands.command(name="ungkap_lokasi", aliases=['ulokasi'], help="Sebagai mata-mata, coba tebak lokasi rahasia.")
    async def ungkap_lokasi(self, ctx, *, guessed_location: str):
        if ctx.channel.id not in self.spyfall_game_states:
            return await ctx.send("Game Mata-Mata belum dimulai.", ephemeral=True)

        game = self.spyfall_game_states[ctx.channel.id]
        spy, location = game['spy'], game['location']

        if ctx.author.id != spy.id:
            return await ctx.send("Hanya mata-mata yang bisa menggunakan perintah ini.", ephemeral=True)
        
        if game['vote_in_progress']:
            return await ctx.send("Saat ini sedang ada voting. Tunggu sampai selesai.", ephemeral=True)

        if guessed_location.lower() == location.lower():
            await ctx.send(f"🎉 **Mata-Mata Ungkap Lokasi Dengan Benar!** {spy.mention} berhasil menebak lokasi rahasia yaitu **{location}**! Mata-mata menang!")
            await self.give_rewards_with_bonus_check(spy, ctx.guild.id, ctx.channel)
        else:
            await ctx.send(f"❌ **Mata-Mata Gagal Mengungkap Lokasi!** Tebakan {guessed_location} salah. Lokasi sebenarnya adalah **{location}**. Warga menang!")
            for p in game['players']:
                if p.id != spy.id:
                    await self.give_rewards_with_bonus_check(p, ctx.guild.id, ctx.channel)
        
        game['game_ended'] = True
        await self.end_game_cleanup(ctx.channel.id, ctx.channel)

    # --- GAME TEKA-TEKI HARIAN ---
    @tasks.loop(time=time(hour=5, minute=0, tzinfo=None)) # Menggunakan UTC (jam 5 pagi WIB = jam 22.00 UTC hari sebelumnya)
    async def post_daily_puzzle(self):
        await self.bot.wait_until_ready()
        
        if not self.tekateki_harian_data: return
        
        self.daily_puzzle = random.choice(self.tekateki_harian_data)
        self.daily_puzzle_solvers.clear()
        
        channel = self.bot.get_channel(self.daily_puzzle_channel_id)
        if channel:
            embed = discord.Embed(title="🤔 Teka-Teki Harian!", description=f"**Teka-teki untuk hari ini:**\n\n> {self.daily_puzzle['riddle']}", color=0x99aab5)
            embed.set_footer(text="Gunakan !jawab <jawabanmu> untuk menebak!")
            await channel.send(embed=embed)

    @post_daily_puzzle.before_loop
    async def before_daily_puzzle(self):
        await self.bot.wait_until_ready()

    @commands.command(name="jawab", help="Jawab teka-teki harian.")
    async def jawab(self, ctx, *, answer: str):
        if not self.daily_puzzle: return await ctx.send("Belum ada teka-teki untuk hari ini. Sabar ya!")
        if ctx.author.id in self.daily_puzzle_solvers: return await ctx.send("Kamu sudah menjawab dengan benar hari ini!", ephemeral=True)
            
        if answer.lower() == self.daily_puzzle['answer'].lower():
            self.daily_puzzle_solvers.add(ctx.author.id)
            await self.give_rewards_with_bonus_check(ctx.author, ctx.guild.id, ctx.channel)
            await ctx.message.add_reaction("✅")
            await ctx.send(f"🎉 Selamat {ctx.author.mention}! Jawabanmu benar!")
        else:
            await ctx.message.add_reaction("❌")

async def setup(bot):
    await bot.add_cog(UltimateGameArena(bot))
