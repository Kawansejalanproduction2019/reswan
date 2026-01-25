import discord
from discord.ext import commands, tasks
import json
import random
import asyncio
import os
import aiohttp
from io import BytesIO
from datetime import datetime, time, timedelta
import pytz

def load_json_from_root(file_path):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    full_path = os.path.join(base_dir, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        if 'config.json' in file_path:
            return {'last_spy_id': None}
        if any(key in file_path for key in ['bank_data.json', 'level_data.json', 'protected_users.json', 'sick_users_cooldown.json']):
            return {}
        if any(key in file_path for key in ['monsters', 'anomalies', 'medicines', 'siapakah_aku', 'pernah_gak_pernah', 'hitung_cepat', 'mata_mata_locations', 'deskripsi_tebak', 'perang_otak', 'cerita_pembuka', 'teka_teki_harian']):
            return []
        if 'donation_buttons.json' in file_path:
            return []
        return {}

def save_json_to_root(data, file_path):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    full_path = os.path.join(base_dir, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

class DonationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.load_donation_buttons()

    def load_donation_buttons(self):
        donation_buttons_data = load_json_from_root('data/donation_buttons.json')
        if not donation_buttons_data:
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

class QuizButton(discord.ui.Button):
    def __init__(self, label, option_letter, parent_view):
        super().__init__(label=f"{option_letter}. {label}", style=discord.ButtonStyle.primary)
        self.parent_view = parent_view
        self.option_letter = option_letter

    async def callback(self, interaction: discord.Interaction):
        if not hasattr(self.parent_view, "participants") or interaction.user.id not in self.parent_view.participants:
            await interaction.response.send_message("Ini bukan pertanyaan untukmu!", ephemeral=True)
            return
        await interaction.response.defer()
        is_correct = self.option_letter.upper() == self.parent_view.correct_answer.upper()
        await self.parent_view.on_answer(interaction, is_correct)
        for child in self.parent_view.children:
            child.disabled = True
        await interaction.message.edit(view=self.parent_view)
        self.parent_view.stop()

class QuizView(discord.ui.View):
    def __init__(self, options, correct_answer, participants, on_answer):
        super().__init__(timeout=15)
        self.correct_answer = correct_answer
        self.participants = participants
        self.on_answer = on_answer
        letters = ["A", "B", "C", "D"]
        for i, option in enumerate(options):
            self.add_item(QuizButton(option, letters[i], self))

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
            await self.game_cog.give_rewards_with_bonus_check(self.winner, interaction.channel)
            for item in self.children: item.disabled = True
        elif is_draw:
            embed.description = "⚖️ **Permainan Berakhir Seri!**"
            embed.color = discord.Color.light_grey()
            for player in [self.player1, self.player2]:
                await self.game_cog.give_rewards_with_bonus_check(player, interaction.channel)
            for item in self.children: item.disabled = True
        else:
            self.current_player = self.player2 if self.current_player == self.player1 else self.player1
            embed.description = f"Giliran: **{self.current_player.mention}**"
        await interaction.message.edit(embed=embed, view=self)
        if self.winner or is_draw:
            self.stop()
            await self.game_cog.end_game_cleanup(interaction.channel.id, interaction.channel)

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

class Games1(commands.Cog):
    DONATION_BUTTONS_FILE = 'data/donation_buttons.json'

    def __init__(self, bot):
        self.bot = bot
        self.active_emoji_games = {}
        self.active_music_quizzes = {}
        self.active_hangman_games = {}
        self.active_resacak_games = {}
        self.active_resipa_games = {}
        self.active_sambung_games = {}
        self.active_games = set()
        self.spyfall_game_states = {}
        self.session_scores = {}
        self.bank_data = load_json_from_root('data/bank_data.json')
        self.level_data = load_json_from_root('data/level_data.json')
        self.allowed_channels = load_json_from_root('data/game_channels.json')
        self.config_data = load_json_from_root('data/config.json')
        self.last_spy_id = self.config_data.get('last_spy_id', None)
        self.emoji_questions = self.load_data_file('data/emoji_questions.json', "questions")
        self.music_questions = self.load_data_file('questions.json', "questions")
        self.hangman_questions = self.load_data_file('data/questions_hangman.json')
        self.resacak_questions = self.load_data_file('data/questions_hangman.json')
        self.resipa_questions = self.load_data_file('data/questions_resipa.json')
        self.sambung_kata_words = self.load_data_file('data/sambung_kata_words.json')
        self.siapakah_aku_data = load_json_from_root('data/siapakah_aku.json')
        self.pernah_gak_pernah_data = load_json_from_root('data/pernah_gak_pernah.json')
        self.hitung_cepat_data = load_json_from_root('data/hitung_cepat.json')
        self.mata_mata_locations = load_json_from_root('data/mata_mata_locations.json')
        self.deskripsi_data = load_json_from_root('data/deskripsi_tebak.json')
        self.perang_otak_data = load_json_from_root('data/perang_otak.json')
        self.cerita_pembuka_data = load_json_from_root('data/cerita_pembuka.json')
        self.tekateki_harian_data = load_json_from_root('data/teka_teki_harian.json')
        self.bantuan_price_emoji = 35
        self.reward_per_correct_emoji = 30
        self.time_limit_emoji = 60
        self.bantuan_price_hangman = 40
        self.reward_per_correct_hangman = 30
        self.resacak_reward = {"rsw": 50, "exp": 100}
        self.resipa_reward = {"rsw": 50, "exp": 100}
        self.sambung_kata_winner_reward = {"rsw": 50, "exp": 100}
        self.resacak_time_limit = 30
        self.resipa_time_limit = 30
        self.sambung_kata_time_limit = 20
        self.reward = {"rsw": 50, "exp": 100}
        self.daily_puzzle = None
        self.daily_puzzle_solvers = set()
        self.daily_puzzle_channel_id = 765140300145360896
        #self.post_daily_puzzle.start()
        self.quiz_attempts_per_question = {}
        self.cooldown_users = {}

    def cog_unload(self):
        self.post_daily_puzzle.cancel()

    def load_data_file(self, file_path, key=None):
        data = load_json_from_root(file_path)
        if key:
            return data.get(key, [])
        return data

    def get_anomaly_multiplier(self):
        dunia_cog = self.bot.get_cog('DuniaHidup')
        if dunia_cog and dunia_cog.active_anomaly and dunia_cog.active_anomaly.get('type') == 'exp_boost':
            return dunia_cog.active_anomaly.get('effect', {}).get('multiplier', 1)
        return 1

    async def end_game_cleanup(self, channel_id, channel_obj=None, game_type=None):
        self.active_games.discard(channel_id)
        if channel_id in self.spyfall_game_states:
            spy_member = self.spyfall_game_states[channel_id]['spy']
            self.last_spy_id = spy_member.id if spy_member else None
            self.config_data['last_spy_id'] = self.last_spy_id
            save_json_to_root(self.config_data, 'data/config.json')
            del self.spyfall_game_states[channel_id]

        if channel_id in self.quiz_attempts_per_question:
            del self.quiz_attempts_per_question[channel_id]
        
        users_in_cooldown_from_this_game = [user_id for user_id, cooldown_end_time in self.cooldown_users.items() if cooldown_end_time > datetime.now()]
        for user_id in users_in_cooldown_from_this_game:
            if user_id in self.cooldown_users:
                del self.cooldown_users[user_id]
        
        if game_type:
            identifier = channel_id
            active_games_map = {
                'emoji': self.active_emoji_games,
                'music': self.active_music_quizzes,
                'hangman': self.active_hangman_games,
                'resacak': self.active_resacak_games,
                'resipa': self.active_resipa_games,
                'sambung_kata': self.active_sambung_games
            }
            game_dict = active_games_map.get(game_type)
            if game_dict and identifier in game_dict:
                game_dict.pop(identifier, None)

        if channel_obj:
            donation_message = (
                "🎮 **Permainan Telah Usai!** Terima kasih sudah bermain bersama kami.\n\n"
                "Apakah kamu menikmati petualangan dan keseruan yang kami hadirkan?\n"
                "Dukung terus pengembangan bot ini agar kami bisa terus berinovasi dan "
                "memberikan pengalaman bermain yang lebih seru lagi!\n\n"
                "Donasi sekecil apa pun sangat berarti untuk kami! 🙏"
            )
            await channel_obj.send(donation_message, view=DonationView())

    async def give_rewards_with_bonus_check(self, user: discord.Member, channel: discord.TextChannel, reward_base: dict = None):
        if reward_base is None:
            reward_base = self.reward.copy()
        
        anomaly_multiplier = self.get_anomaly_multiplier()
        final_rsw = int(reward_base.get('rsw', 0) * anomaly_multiplier)
        final_exp = int(reward_base.get('exp', 0) * anomaly_multiplier)

        user_id_str, guild_id_str = str(user.id), str(user.guild.id)
        
        self.bank_data = load_json_from_root('data/bank_data.json')
        self.level_data = load_json_from_root('data/level_data.json')
        
        self.bank_data.setdefault(user_id_str, {'balance': 0, 'debt': 0})['balance'] += final_rsw
        user_level_data = self.level_data.setdefault(guild_id_str, {}).setdefault(user_id_str, {'exp': 0, 'level': 1})
        user_level_data['exp'] += final_exp
        
        save_json_to_root(self.bank_data, 'data/bank_data.json')
        save_json_to_root(self.level_data, 'data/level_data.json')
        
        if anomaly_multiplier > 1 and channel:
            await channel.send(f"✨ **BONUS ANOMALI!** {user.mention} mendapatkan hadiah yang dilipatgandakan!", delete_after=15)

    async def start_game_check(self, ctx):
        if ctx.channel.id in self.active_games:
            await ctx.send("Maaf, sudah ada permainan lain di channel ini. Tunggu selesai ya!", delete_after=10)
            return False
        self.active_games.add(ctx.channel.id)
        return True

    def is_channel_allowed(self, game_name, channel_id):
        game_channels = self.allowed_channels.get(game_name)
        if game_channels and channel_id not in game_channels:
            return False
        return True

    @commands.command(name="setgamechannel")
    @commands.has_permissions(administrator=True)
    async def set_game_channel(self, ctx, game_name: str, action: str, channel: discord.TextChannel = None):
        game_name = game_name.lower()
        valid_games = ['resmoji', 'startquiz', 'resman', 'resacak', 'resipa', 'ressambung']
        if game_name not in valid_games:
            await ctx.send(f"Nama game tidak valid. Pilih dari: {', '.join(valid_games)}")
            return
        if game_name not in self.allowed_channels:
            self.allowed_channels[game_name] = []
        action = action.lower()
        if action == 'add':
            if not channel:
                await ctx.send("Sebutkan channel yang ingin ditambahkan.")
                return
            if channel.id not in self.allowed_channels[game_name]:
                self.allowed_channels[game_name].append(channel.id)
                await ctx.send(f"Channel {channel.mention} telah diizinkan untuk game `{game_name}`.")
            else:
                await ctx.send(f"Channel {channel.mention} sudah diizinkan untuk game `{game_name}`.")
        elif action == 'remove':
            if not channel:
                await ctx.send("Sebutkan channel yang ingin dihapus.")
                return
            if channel.id in self.allowed_channels[game_name]:
                self.allowed_channels[game_name].remove(channel.id)
                await ctx.send(f"Channel {channel.mention} telah dihapus dari izin game `{game_name}`.")
            else:
                await ctx.send(f"Channel {channel.mention} tidak ditemukan di daftar izin game `{game_name}`.")
        elif action == 'list':
            channels = self.allowed_channels.get(game_name, [])
            if not channels:
                await ctx.send(f"Tidak ada channel spesifik yang diatur untuk `{game_name}`. Game dapat dimainkan di mana saja.")
                return
            channel_mentions = [f"<#{cid}>" for cid in channels]
            await ctx.send(f"Channel yang diizinkan for `{game_name}`: {', '.join(channel_mentions)}")
        else:
            await ctx.send("Aksi tidak valid. Gunakan `add`, `remove`, atau `list`.")
        save_json_to_root(self.allowed_channels, 'data/game_channels.json')

    @commands.command(name="resmoji")
    async def resmoji(self, ctx):
        if not self.is_channel_allowed('resmoji', ctx.channel.id):
            return await ctx.send("Permainan EmojiQuiz tidak bisa dimainkan di channel ini.")
        if not await self.start_game_check(ctx):
            return
        if ctx.channel.id in self.active_emoji_games:
            await ctx.send("Permainan sudah sedang berlangsung di channel ini.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel, 'emoji')
            return
        self.session_scores = {}
        embed = discord.Embed(title="🎮 Cara Bermain EmojiQuiz", description=f"Selamat datang di **Kuis Emoji**.\n\n📌 Kamu akan dikasih 1 atau lebih emoji dari bot.\n🫵 Tebak maksudnya, bisa 1–3 kata. Bebas.\n⏳ Kalau gak ada yang jawab dalam 1 menit, soal langsung lanjut ke berikutnya.\n🎁 Jawaban benar dapet **+{self.reward_per_correct_emoji} RSWN**. Lumayan buat beli badge atau sekadar merasa berguna.\n\n💸 Ngerasa buntu? Beli **bantuan** aja pake:\n**!resplis** – Harga: {self.bantuan_price_emoji} RSWN. Dibalas via DM.\n*Bantuan gak dibatasin... karena kami ngerti, kadang kita butuh banyak petunjuk buat ngerti sesuatu.*\n\n🖤 Terima kasih buat kalian yang masih sering nongol di sini...\nWalau orangnya itu-itu aja, ... tapi hati kami tetap hangat karena kalian.\n\nKlik tombol di bawah ini kalau kamu siap... atau kalau cuma pengen ditemani sebentar sama bot ini.", color=0x5500aa)
        view = discord.ui.View()
        start_button = discord.ui.Button(label="🔵 START", style=discord.ButtonStyle.primary)
        async def start_game(interaction):
            self.active_emoji_games[ctx.channel.id] = {"user": ctx.author, "correct": 0, "wrong": 0, "current_question": None, "questions": [], "game_over": False, "bantuan_used": 0, "start_time": None, "total_rsw": 0}
            await interaction.message.delete()
            await self.play_emoji_game(ctx)
        start_button.callback = start_game
        view.add_item(start_button)
        await ctx.send(embed=embed, view=view)

    async def play_emoji_game(self, ctx):
        game_data = self.active_emoji_games[ctx.channel.id]
        if not self.emoji_questions or len(self.emoji_questions) < 10:
            await ctx.send("Tidak cukup pertanyaan untuk memulai permainan.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel, 'emoji')
            return
        game_data["questions"] = random.sample(self.emoji_questions, 10)
        for index, question in enumerate(game_data["questions"]):
            if game_data.get("game_over"): break
            game_data["current_question"] = index
            await self.ask_emoji_question(ctx, question)
        if not game_data.get("game_over"):
            await self.end_emoji_game(ctx)

    async def ask_emoji_question(self, ctx, question):
        game_data = self.active_emoji_games[ctx.channel.id]
        embed = discord.Embed(title=f"❓ Pertanyaan {game_data['current_question'] + 1}", description=f"Emoji: **{question['emoji']}**\nSebutkan frasa yang sesuai!", color=0x00ff00)
        await ctx.send(embed=embed)
        try:
            def check(m): return m.channel == ctx.channel and not m.author.bot
            while True:
                user_answer = await self.bot.wait_for('message', timeout=self.time_limit_emoji, check=check)
                if user_answer.content.strip().lower() == question['answer'].lower():
                    anomaly_multiplier = self.get_anomaly_multiplier()
                    final_reward = int(self.reward_per_correct_emoji * anomaly_multiplier)
                    if user_answer.author.id not in self.session_scores:
                        self.session_scores[user_answer.author.id] = {"score": 0, "correct": 0, "wrong": 0, "user": user_answer.author}
                    game_data["correct"] += 1
                    game_data.setdefault("total_rsw", 0)
                    game_data["total_rsw"] += final_reward
                    self.session_scores[user_answer.author.id]["score"] += final_reward
                    self.session_scores[user_answer.author.id]["correct"] += 1
                    if anomaly_multiplier > 1:
                        await ctx.send(f"✅ Jawaban Benar dari {user_answer.author.display_name}! Karena ada anomali, hadiahmu dilipatgandakan menjadi **{final_reward} RSWN**!")
                    else:
                        await ctx.send(f"✅ Jawaban Benar dari {user_answer.author.display_name}! Kamu dapat **{final_reward} RSWN**.")
                    break
                else:
                    if user_answer.author.id not in self.session_scores:
                        self.session_scores[user_answer.author.id] = {"score": 0, "correct": 0, "wrong": 0, "user": user_answer.author}
                    self.session_scores[user_answer.author.id]["wrong"] += 1
                    await user_answer.add_reaction("❌")
        except asyncio.TimeoutError:
            await ctx.send("Waktu habis! Melanjutkan ke soal berikutnya.")

    async def end_emoji_game(self, ctx):
        if ctx.channel.id in self.active_emoji_games:
            self.bank_data = load_json_from_root('data/bank_data.json')
            for user_id, score_data in self.session_scores.items():
                user_id_str = str(user_id)
                if user_id_str not in self.bank_data:
                    self.bank_data[user_id_str] = {"balance": 0, "debt": 0}
                self.bank_data[user_id_str]['balance'] += score_data['score']
            save_json_to_root(self.bank_data, 'data/bank_data.json')
            await self.display_leaderboard(ctx, 'EmojiQuiz')
            await self.end_game_cleanup(ctx.channel.id, ctx.channel, 'emoji')

    @commands.command(name="resplis")
    async def resplis(self, ctx):
        user_id = str(ctx.author.id)
        if user_id not in self.bank_data:
            self.bank_data[user_id] = {"balance": 0, "debt": 0}
        user_data = self.bank_data[user_id]
        if user_data.get('balance', 0) < self.bantuan_price_emoji:
            return await ctx.send("😢 Saldo RSWN tidak cukup untuk membeli bantuan.")
        if ctx.channel.id not in self.active_emoji_games or self.active_emoji_games[ctx.channel.id].get("current_question") is None:
            return await ctx.send("Tidak ada permainan aktif untuk membeli bantuan.")
        initial_balance = user_data['balance']
        user_data['balance'] -= self.bantuan_price_emoji
        final_balance = user_data['balance']
        current_question_index = self.active_emoji_games[ctx.channel.id]["current_question"]
        current_question = self.active_emoji_games[ctx.channel.id]["questions"][current_question_index]
        try:
            await ctx.author.send(f"🔐 Jawaban untuk pertanyaan saat ini adalah: **{current_question['answer']}**")
            await ctx.author.send(f"✅ Pembelian bantuan berhasil! Saldo RSWN Anda berkurang dari **{initial_balance}** menjadi **{final_balance}**.")
            await ctx.send(f"{ctx.author.mention}, bantuan telah dikirim ke DM Anda!")
        except discord.Forbidden:
            await ctx.send(f"Gagal mengirim DM ke {ctx.author.mention}. Mohon aktifkan DM dari server ini.")
            user_data['balance'] += self.bantuan_price_emoji
        save_json_to_root(self.bank_data, 'data/bank_data.json')

    @commands.command(name="startquiz")
    async def start_quiz(self, ctx):
        if not self.is_channel_allowed('startquiz', ctx.channel.id):
            return await ctx.send("Permainan MusicQuiz tidak bisa dimainkan di channel ini.")
        if not await self.start_game_check(ctx):
            return
        guild_id = ctx.guild.id
        if self.active_music_quizzes.get(guild_id):
            await ctx.send("❗ Masih ada sesi kuis yang aktif di server ini.")
            await self.end_game_cleanup(guild_id, ctx.channel, 'music')
            return
        if not self.music_questions:
            return await ctx.send("Tidak ada pertanyaan kuis yang tersedia.")
        async def join_vc():
            if not ctx.author.voice:
                await ctx.send("Kamu harus ada di voice channel.")
                return False
            channel = ctx.author.voice.channel
            if not ctx.guild.voice_client or not ctx.guild.voice_client.is_connected():
                try:
                    await channel.connect()
                    return True
                except discord.ClientException:
                    return False
            return True
        if not await join_vc():
            await self.end_game_cleanup(guild_id, ctx.channel, 'music')
            return
        self.active_music_quizzes[guild_id] = True
        try:
            participants = [member.id for member in ctx.author.voice.channel.members if not member.bot]
            if not participants:
                await ctx.send("Tidak ada peserta non-bot di voice channel.")
                return
            self.session_scores = {str(mid): 0 for mid in participants}
            bonus_winners = []
            await ctx.send("⏳ Bersiaplah... Kuis akan dimulai dalam 3 detik!")
            await asyncio.sleep(3)
            def make_callback(question, is_bonus, correct_users):
                async def callback(interaction, is_correct):
                    uid = str(interaction.user.id)
                    if uid not in self.session_scores: self.session_scores[uid] = 0
                    if is_correct:
                        self.session_scores[uid] += 1
                        if is_bonus: correct_users.append(uid)
                        await interaction.followup.send(f"✅ {interaction.user.mention} Jawaban benar!", ephemeral=False)
                    else:
                        await interaction.followup.send(f"❌ {interaction.user.mention} Salah! Jawaban yang benar: **{question['answer']}**", ephemeral=False)
                return callback
            shuffled_questions = random.sample(self.music_questions, min(20, len(self.music_questions)))
            for nomor, q in enumerate(shuffled_questions, 1):
                is_bonus = nomor >= 15
                correct_users_this_round = []
                view = QuizView(q["options"], q["answer"], participants, make_callback(q, is_bonus, correct_users_this_round))
                embed = discord.Embed(title=f"🎤 Pertanyaan {nomor}{' (BONUS)' if is_bonus else ''}", description=q["question"], color=discord.Color.gold() if is_bonus else discord.Color.blurple())
                await ctx.send(embed=embed, view=view)
                await view.wait()
                if is_bonus: bonus_winners.extend(correct_users_this_round)
                await asyncio.sleep(5)
            await self.send_music_leaderboard(ctx, bonus_winners)
        finally:
            await self.end_game_cleanup(guild_id, ctx.channel, 'music')

    async def send_music_leaderboard(self, ctx, bonus_winners):
        sorted_scores = sorted(self.session_scores.items(), key=lambda x: x[1], reverse=True)
        top3 = sorted_scores[:3]
        self.level_data = load_json_from_root('data/level_data.json')
        self.bank_data = load_json_from_root('data/bank_data.json')
        rewards = [(50, 150), (25, 100), (15, 50)]
        embed = discord.Embed(title="🏆 **Leaderboard Akhir Kuis Musik:**", color=0x1DB954)
        if not top3:
            embed.description = "Tidak ada yang mendapatkan skor."
        else:
            for i, (user_id, score) in enumerate(top3):
                user = self.bot.get_user(int(user_id))
                name = user.display_name if user else f"User ({user_id})"
                exp_reward, rswn_reward = rewards[i]
                self.level_data.setdefault(str(ctx.guild.id), {}).setdefault(user_id, {"exp": 0, "level": 1})
                self.bank_data.setdefault(user_id, {"balance": 0, "debt": 0})
                self.level_data[str(ctx.guild.id)][user_id]["exp"] += exp_reward
                self.bank_data[user_id]["balance"] += rswn_reward
                embed.add_field(name=f"{i+1}. {name}", value=f"Skor: {score}\n+{exp_reward} EXP, +{rswn_reward} RSWN", inline=False)
        save_json_to_root(self.level_data, 'data/level_data.json')
        save_json_to_root(self.bank_data, 'data/bank_data.json')
        await ctx.send(embed=embed)
        bonus_award_summary = {}
        for uid in bonus_winners:
            self.level_data.setdefault(str(ctx.guild.id), {}).setdefault(uid, {"exp": 0, "level": 1})
            self.bank_data.setdefault(uid, {"balance": 0, "debt": 0})
            self.level_data[str(ctx.guild.id)][uid]["exp"] += 25
            self.bank_data[uid]["balance"] += 25
            user = self.bot.get_user(int(uid))
            name = user.display_name if user else f"User ({uid})"
            bonus_award_summary[name] = bonus_award_summary.get(name, 0) + 1
        save_json_to_root(self.level_data, 'data/level_data.json')
        save_json_to_root(self.bank_data, 'data/bank_data.json')
        if bonus_award_summary:
            desc = "".join([f"✅ **{name}** mendapatkan +{count * 25} EXP & +{count * 25} RSWN dari {count} babak bonus!\n" for name, count in bonus_award_summary.items()])
            await ctx.send(embed=discord.Embed(title="🎉 Hadiah Bonus!", description=desc, color=discord.Color.green()))

    @commands.command(name="resman")
    async def hangman(self, ctx):
        if not self.is_channel_allowed('resman', ctx.channel.id):
            return await ctx.send("Permainan Hangman tidak bisa dimainkan di channel ini.")
        if not await self.start_game_check(ctx):
            return
        if ctx.channel.id in self.active_hangman_games:
            await ctx.send("Permainan sudah sedang berlangsung di channel ini.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel, 'hangman')
            return
        self.session_scores = {}
        embed = discord.Embed(title="🎮 Cara Bermain Hangman", description=f"Selamat datang di Dunia Sunyi Hangman! 🖤🌧️\n\nDi sini, kamu tak hanya menebak kata... tapi juga menebak makna dari kesepian yang tak bertepi.\nJawablah satu per satu, berharap RSWN bisa sedikit mengisi kekosongan itu.\nSelesaikan 10 soal... kalau kamu masih punya semangat itu.\n\n💸 Ngerasa buntu? Beli **bantuan** aja pake:\n**!hmanplis** – Harga: {self.bantuan_price_hangman} RSWN. Jawaban dikirim via DM.\n*Karena terkadang, kita semua butuh sedikit cahaya di dalam gelap.*\n\nKalau kamu cukup kuat, cukup tahan, cukup sad... klik tombol di bawah ini. Mulai permainanmu.", color=0x5500aa)
        view = discord.ui.View()
        start_button = discord.ui.Button(label="🔵 START", style=discord.ButtonStyle.primary)
        async def start_game(interaction):
            await interaction.message.delete()
            self.active_hangman_games[ctx.channel.id] = {"score": 0, "correct": 0, "wrong": 0, "current_question": 0, "time_limit": 120, "start_time": None, "question": None, "game_over": False, "answers": []}
            await ctx.send(f"{ctx.author.mention}, permainan Hangman dimulai!")
            await self.play_hangman_game(ctx)
        start_button.callback = start_game
        view.add_item(start_button)
        await ctx.send(embed=embed, view=view)

    async def play_hangman_game(self, ctx):
        game_data = self.active_hangman_games[ctx.channel.id]
        if not self.hangman_questions or len(self.hangman_questions) < 10:
            await ctx.send("Tidak cukup pertanyaan untuk memulai permainan.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel, 'hangman')
            return
        game_data["question"] = random.sample(self.hangman_questions, 10)
        for index, question in enumerate(game_data["question"]):
            if game_data.get("game_over", False): break
            game_data["current_question"] = index + 1
            await self.ask_hangman_question(ctx, question)
        if not game_data.get("game_over", False):
            await self.end_hangman_game(ctx)

    async def ask_hangman_question(self, ctx, question):
        game_data = self.active_hangman_games[ctx.channel.id]
        embed = discord.Embed(title=f"❓ Pertanyaan {game_data['current_question']}/10", description=f"Kategori: **{question['category']}**\nKisi-kisi: {question['clue']}\nSebutkan satu kata: `{' '.join(['_' for _ in question['word']])}`", color=0x00ff00)
        await ctx.send(embed=embed)
        try:
            def check(m): return m.channel == ctx.channel and not m.author.bot
            while True:
                user_answer_msg = await self.bot.wait_for('message', timeout=game_data["time_limit"], check=check)
                if user_answer_msg.content.strip().lower() == question['word'].lower():
                    anomaly_multiplier = self.get_anomaly_multiplier()
                    final_reward = int(self.reward_per_correct_hangman * anomaly_multiplier)
                    author = user_answer_msg.author
                    author_id = author.id
                    if author_id not in self.session_scores:
                        self.session_scores[author_id] = {"user": author, "correct": 0, "wrong": 0, "total_rsw": 0}
                    self.session_scores[author_id]["correct"] += 1
                    self.session_scores[author_id]["total_rsw"] += final_reward
                    if anomaly_multiplier > 1:
                        await ctx.send(f"✅ Jawaban Benar dari {author.display_name}! Karena ada anomali, hadiahmu dilipatgandakan menjadi **{final_reward} RSWN**!")
                    else:
                        await ctx.send(f"✅ Jawaban Benar dari {author.display_name}! Kamu dapat **{final_reward} RSWN**.")
                    break
                else:
                    if not user_answer_msg.content.startswith(self.bot.command_prefix):
                        author_id = user_answer_msg.author.id
                        if author_id not in self.session_scores:
                            self.session_scores[author_id] = {"user": user_answer_msg.author, "correct": 0, "wrong": 0, "total_rsw": 0}
                        self.session_scores[author_id]["wrong"] += 1
                        await user_answer_msg.add_reaction("❌")
        except asyncio.TimeoutError:
            await ctx.send(f"Waktu habis! Jawaban yang benar adalah **{question['word']}**.")

    async def end_hangman_game(self, ctx):
        if ctx.channel.id in self.active_hangman_games:
            self.bank_data = load_json_from_root('data/bank_data.json')
            self.level_data = load_json_from_root('data/level_data.json')
            guild_id = str(ctx.guild.id)
            for user_id, score_data in self.session_scores.items():
                user_id_str = str(user_id)
                if user_id_str not in self.bank_data: self.bank_data[user_id_str] = {"balance": 0, "debt": 0}
                self.bank_data[user_id_str]['balance'] += score_data['total_rsw']
                if user_id_str not in self.level_data.get(guild_id, {}):
                    self.level_data.setdefault(guild_id, {})[user_id_str] = {"exp": 0, "level": 0}
                exp_gain = score_data['correct'] * 10
                self.level_data[guild_id][user_id_str]['exp'] += exp_gain
            save_json_to_root(self.bank_data, 'data/bank_data.json')
            save_json_to_root(self.level_data, 'data/level_data.json')
            await self.display_leaderboard(ctx, 'Hangman')
            await self.end_game_cleanup(ctx.channel.id, ctx.channel, 'hangman')

    @commands.command(name="hmanplis")
    async def hmanplis(self, ctx):
        user_id = str(ctx.author.id)
        if ctx.channel.id not in self.active_hangman_games:
            return await ctx.send("Tidak ada permainan Hangman yang sedang berlangsung.")
        self.bank_data = load_json_from_root('data/bank_data.json')
        if user_id not in self.bank_data: self.bank_data[user_id] = {"balance": 0, "debt": 0}
        user_data = self.bank_data[user_id]
        if user_data.get('balance', 0) < self.bantuan_price_hangman:
            return await ctx.send(f"😢 Saldo RSWN tidak cukup. Harga: {self.bantuan_price_hangman} RSWN.")
        game_data = self.active_hangman_games[ctx.channel.id]
        current_question_index = game_data["current_question"] - 1
        if game_data["question"] and 0 <= current_question_index < len(game_data["question"]):
            initial_balance = user_data.get('balance', 0)
            user_data['balance'] -= self.bantuan_price_hangman
            final_balance = user_data['balance']
            correct_word = game_data["question"][current_question_index]['word']
            try:
                await ctx.author.send(f"🔐 Jawaban Hangman saat ini: **{correct_word}**")
                await ctx.author.send(f"✅ Bantuan berhasil! Saldo RSWN Anda: **{initial_balance}** -> **{final_balance}**.")
                await ctx.send(f"{ctx.author.mention}, bantuan dikirim ke DM!")
            except discord.Forbidden:
                await ctx.send(f"{ctx.author.mention}, saya tidak bisa mengirim DM.")
                user_data['balance'] += self.bantuan_price_hangman
            save_json_to_root(self.bank_data, 'data/bank_data.json')
        else:
            await ctx.send("Tidak bisa mendapatkan pertanyaan saat ini.")

    @commands.command(name="resacak")
    async def resacak(self, ctx):
        if not self.is_channel_allowed('resacak', ctx.channel.id):
            return await ctx.send("Permainan Resacak tidak bisa dimainkan di channel ini.", delete_after=10)
        if not await self.start_game_check(ctx):
            return
        if ctx.channel.id in self.active_resacak_games:
            return await ctx.send("Permainan Resacak sudah berlangsung.", delete_after=10)
        embed = discord.Embed(title="🎲 Siap Bermain Resacak (Tebak Kata Acak)?", description=f"Uji kecepatan berpikir dan kosakatamu!\n\n**Aturan Main:**\n1. Bot akan memberikan kata yang hurufnya diacak, dilengkapi **kategori** dan **kisi-kisi**.\n2. Tebak kata aslinya secepat mungkin.\n3. Jawaban benar pertama mendapat **{self.resacak_reward['rsw']} RSWN** & **{self.resacak_reward['exp']} EXP**.\n4. Permainan terdiri dari 10 ronde.\n\nKlik tombol di bawah untuk memulai!", color=0x3498db)
        view = discord.ui.View(timeout=60)
        start_button = discord.ui.Button(label="MULAI SEKARANG", style=discord.ButtonStyle.primary, emoji="▶️")
        async def start_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("Hanya pemanggil perintah yang bisa memulai.", ephemeral=True)
            self.active_resacak_games[ctx.channel.id] = True
            await interaction.message.delete()
            await self.play_resacak_game(ctx)
        start_button.callback = start_callback
        view.add_item(start_button)
        await ctx.send(embed=embed, view=view)

    async def play_resacak_game(self, ctx):
        if not self.resacak_questions or len(self.resacak_questions) < 10:
            await ctx.send("Maaf, bank soal Resacak tidak cukup.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel, 'resacak')
            return
        questions_for_game = random.sample(self.resacak_questions, 10)
        leaderboard = {}
        for i, q_data in enumerate(questions_for_game):
            correct_answer = q_data['word'].lower()
            scrambled_word = "".join(random.sample(q_data['word'], len(q_data['word'])))
            embed = discord.Embed(title=f"📝 Soal #{i+1} - Tebak Kata Acak!", color=0x2ecc71)
            embed.add_field(name="Kategori", value=q_data['category'], inline=True)
            embed.add_field(name="Kata Teracak", value=f"## `{scrambled_word.upper()}`", inline=False)
            embed.add_field(name="Kisi-kisi", value=q_data['clue'], inline=False)
            question_msg = await ctx.send(embed=embed)
            winner = await self.wait_for_answer_with_timer(ctx, correct_answer, question_msg, self.resacak_time_limit)
            if winner:
                await self.give_rewards_with_bonus_check(winner, ctx.channel, self.resacak_reward)
                leaderboard[winner.display_name] = leaderboard.get(winner.display_name, 0) + 1
            else:
                await ctx.send(f"Waktu habis! Jawaban: **{correct_answer.upper()}**.")
        if leaderboard:
            sorted_lb = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
            desc = "\n".join([f"**#{n}.** {user}: {score} poin" for n, (user, score) in enumerate(sorted_lb, 1)])
            await ctx.send(embed=discord.Embed(title="🏆 Papan Skor Akhir", description=desc, color=discord.Color.gold()))
        await self.end_game_cleanup(ctx.channel.id, ctx.channel, 'resacak')

    @commands.command(name="resipa")
    async def resipa(self, ctx):
        if not self.is_channel_allowed('resipa', ctx.channel.id):
            return await ctx.send("Permainan Resipa tidak bisa dimainkan di channel ini.", delete_after=10)
        if not await self.start_game_check(ctx):
            return
        if ctx.channel.id in self.active_resipa_games:
            return await ctx.send("Permainan Kuis Resipa sudah berlangsung.", delete_after=10)
        embed = discord.Embed(title="🧠 Siap Bermain Kuis Resipa (Tebak Kata)?", description=f"Uji kecepatan berpikir dan kosakatamu!\n\n**Aturan Main:**\n1. Bot akan memberikan **kata yang hurufnya diacak**, dilengkapi **kategori** dan **kisi-kisi**.\n2. Tebak kata aslinya secepat mungkin.\n3. Jawaban benar pertama mendapat **{self.resipa_reward['rsw']} RSWN** & **{self.resipa_reward['exp']} EXP**.\n4. Permainan terdiri dari 10 ronde.\n\nKlik tombol di bawah untuk memulai!", color=0x3498db)
        view = discord.ui.View(timeout=60)
        start_button = discord.ui.Button(label="MULAI SEKARANG", style=discord.ButtonStyle.primary, emoji="▶️")
        async def start_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("Hanya pemanggil perintah yang bisa memulai.", ephemeral=True)
            self.active_resipa_games[ctx.channel.id] = True
            await interaction.message.delete()
            await self.play_resipa_game(ctx)
        start_button.callback = start_callback
        view.add_item(start_button)
        await ctx.send(embed=embed, view=view)

    async def play_resipa_game(self, ctx):
        if not self.resipa_questions or len(self.resipa_questions) < 10:
            await ctx.send("Maaf, bank soal Kuis Resipa tidak cukup.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel, 'resipa')
            return
        questions_for_game = random.sample(self.resipa_questions, 10)
        leaderboard = {}
        for i, q_data in enumerate(questions_for_game):
            correct_answer = q_data['word'].lower()
            scrambled_word = "".join(random.sample(q_data['word'], len(q_data['word'])))
            embed = discord.Embed(title=f"📝 Soal #{i+1} - Tebak Kata!", color=0x2ecc71)
            embed.add_field(name="Kategori", value=q_data['category'], inline=True)
            embed.add_field(name="Kata Teracak", value=f"## `{scrambled_word.upper()}`", inline=False)
            embed.add_field(name="Kisi-kisi", value=q_data['clue'], inline=False)
            question_msg = await ctx.send(embed=embed)
            winner = await self.wait_for_answer_with_timer(ctx, correct_answer, question_msg, self.resipa_time_limit)
            if winner:
                await self.give_rewards_with_bonus_check(winner, ctx.channel, self.resipa_reward)
                leaderboard[winner.display_name] = leaderboard.get(winner.display_name, 0) + 1
            else:
                await ctx.send(f"Waktu habis! Jawaban: **{correct_answer.upper()}**.")
        if leaderboard:
            sorted_lb = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
            desc = "\n".join([f"**#{n}.** {user}: {score} poin" for n, (user, score) in enumerate(sorted_lb, 1)])
            await ctx.send(embed=discord.Embed(title="🏆 Papan Skor Akhir", description=desc, color=discord.Color.gold()))
        await self.end_game_cleanup(ctx.channel.id, ctx.channel, 'resipa')

    @commands.command(name="ressambung")
    async def ressambung(self, ctx):
        if not self.is_channel_allowed('ressambung', ctx.channel.id):
            return await ctx.send("Permainan Sambung Kata tidak bisa dimainkan di channel ini.", delete_after=10)
        if not await self.start_game_check(ctx):
            return
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Kamu harus berada di voice channel.", delete_after=10)
        vc = ctx.author.voice.channel
        if vc.id in self.active_sambung_games:
            return await ctx.send(f"Sudah ada permainan Sambung Kata di voice channel ini.", delete_after=10)
        members = [m for m in vc.members if not m.bot]
        if len(members) < 2:
            return await ctx.send("Permainan ini membutuhkan minimal 2 orang.", delete_after=10)
        game_state = {"players": {p.id: p for p in members}, "turn_index": 0, "current_word": "", "used_words": set(), "channel": ctx.channel}
        self.active_sambung_games[vc.id] = game_state
        player_mentions = ", ".join([p.mention for p in game_state["players"].values()])
        embed = discord.Embed(title="🔗 Siap Bermain Sambung Kata?", description=f"Uji kosakatamu dan bertahanlah sampai akhir!\n\n**Aturan Main:**\n1. Pemain bergiliran menyambung kata berdasarkan **2 huruf terakhir**.\n2. Waktu menjawab **{self.sambung_kata_time_limit} detik** per giliran.\n3. Pemain yang gagal atau salah kata akan tereliminasi.\n4. Pemenang terakhir mendapat **{self.sambung_kata_winner_reward['rsw']} RSWN** & **{self.sambung_kata_winner_reward['exp']} EXP**.", color=0xe91e63)
        embed.add_field(name="👥 Pemain Bergabung", value=player_mentions)
        await ctx.send(embed=embed)
        await asyncio.sleep(5)
        await self.play_sambung_kata_game(vc.id)

    async def play_sambung_kata_game(self, vc_id):
        game = self.active_sambung_games.get(vc_id)
        if not game: return
        player_ids = list(game["players"].keys())
        random.shuffle(player_ids)
        if not self.sambung_kata_words:
            await game["channel"].send("Bank kata tidak ditemukan.")
            return await self.end_game_cleanup(vc_id, game["channel"], 'sambung_kata')
        game["current_word"] = random.choice(self.sambung_kata_words).lower()
        game["used_words"].add(game["current_word"])
        await game["channel"].send(f"Kata pertama dari bot: **{game['current_word'].upper()}**")
        while len(player_ids) > 1:
            current_player_id = player_ids[game["turn_index"]]
            current_player = game["players"][current_player_id]
            prefix = game["current_word"][-2:].lower()
            embed = discord.Embed(title=f"Giliran {current_player.display_name}!", description=f"Sebutkan kata yang diawali dengan **`{prefix.upper()}`**", color=current_player.color)
            await game["channel"].send(embed=embed)
            try:
                def check(m): return m.author.id == current_player_id and m.channel == game["channel"]
                msg = await self.bot.wait_for('message', check=check, timeout=self.sambung_kata_time_limit)
                new_word = msg.content.strip().lower()
                if not new_word.startswith(prefix) or new_word in game["used_words"]:
                    await game["channel"].send(f"❌ Salah! {current_player.mention} tereliminasi!")
                    player_ids.pop(game["turn_index"])
                else:
                    await msg.add_reaction("✅")
                    game["current_word"] = new_word
                    game["used_words"].add(new_word)
                    game["turn_index"] = (game["turn_index"] + 1) % len(player_ids)
            except asyncio.TimeoutError:
                await game["channel"].send(f"⌛ Waktu habis! {current_player.mention} tereliminasi!")
                player_ids.pop(game["turn_index"])
            if len(player_ids) > 0 and game["turn_index"] >= len(player_ids):
                game["turn_index"] = 0
            await asyncio.sleep(2)
        if len(player_ids) == 1:
            winner = game["players"][player_ids[0]]
            await self.give_rewards_with_bonus_check(winner, game["channel"], self.sambung_kata_winner_reward)
            await game["channel"].send(f"🏆 Pemenangnya adalah {winner.mention}!")
        await self.end_game_cleanup(vc_id, game["channel"], 'sambung_kata')

    async def wait_for_answer_with_timer(self, ctx, correct_answer, question_msg, time_limit):
        try:
            def check(m): return m.channel == ctx.channel and not m.author.bot and m.content.lower() == correct_answer.lower()
            msg = await self.bot.wait_for('message', check=check, timeout=time_limit)
            return msg.author
        except asyncio.TimeoutError:
            return None

    async def display_leaderboard(self, ctx, game_title):
        if not self.session_scores: return
        sorted_scores = sorted(self.session_scores.values(), key=lambda x: x.get("score", x.get("correct", 0)), reverse=True)
        embed = discord.Embed(title=f"🏆 Leaderboard Sesi {game_title}", color=0x00ff00)
        for i, data in enumerate(sorted_scores[:5]):
            user = data['user']
            score = data.get('score', data.get('total_rsw', 0))
            embed.add_field(name=f"#{i + 1}. {user.display_name}", value=f"💰 **Total RSWN:** {score}\n✅ **Benar:** {data['correct']}\n❌ **Salah:** {data['wrong']}", inline=False)
        if sorted_scores:
            winner_user = sorted_scores[0]['user']
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(str(winner_user.display_avatar.url)) as resp:
                        if resp.status == 200:
                            image_data = BytesIO(await resp.read())
                            await ctx.send(file=discord.File(image_data, filename='winner_avatar.png'))
            except Exception as e:
                print(f"Failed to fetch winner avatar: {e}")
        await ctx.send(embed=embed)

    @commands.command(name="siapakahaku")
    @commands.cooldown(1, 60, commands.BucketType.channel)
    async def siapakahaku(self, ctx):
        if not await self.start_game_check(ctx): return
        if len(self.siapakah_aku_data) < 10:
            await ctx.send("Tidak cukup soal di database untuk memulai sesi (butuh minimal 10).")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            return
        questions = random.sample(self.siapakah_aku_data, 10)
        leaderboard = {}
        self.quiz_attempts_per_question[ctx.channel.id] = {}
        game_start_embed = discord.Embed(title="🕵️‍♂️ Sesi Kuis 'Siapakah Aku?' Dimulai!", description="Akan ada **10 soal** berturut-turut. Petunjuk akan muncul setiap **10 detik**.", color=0x1abc9c)
        await ctx.send(embed=game_start_embed)
        await asyncio.sleep(5)
        for i, item in enumerate(questions):
            word = item['name'].lower()
            clues = item['clues']
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
                            if message.author.id in self.cooldown_users:
                                if datetime.now() < self.cooldown_users[message.author.id]:
                                    try:
                                        await message.delete()
                                    except discord.Forbidden:
                                        pass
                                    await ctx.send(f"🚨 {message.author.mention}, Anda masih dalam cooldown di ronde ini. Tunggu atau soal akan berlanjut.", delete_after=5)
                                    continue
                                else:
                                    del self.cooldown_users[message.author.id]
                            user_attempts = self.quiz_attempts_per_question[ctx.channel.id].setdefault(message.author.id, 0)
                            if message.content.lower() == word:
                                winner = message.author
                                round_over = True
                                return
                            else:
                                await message.add_reaction("❌")
                                user_attempts += 1
                                self.quiz_attempts_per_question[ctx.channel.id][message.author.id] = user_attempts
                                if user_attempts >= 2:
                                    cooldown_end_time = datetime.now() + timedelta(seconds=30)
                                    self.cooldown_users[message.author.id] = cooldown_end_time
                                    try:
                                        await message.author.timeout(timedelta(seconds=30), reason="Melebihi batas percobaan kuis")
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan & di-timeout sementara (30 detik).", delete_after=10)
                                    except discord.Forbidden:
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan di ronde ini. Anda tidak bisa menjawab sampai soal ini selesai.", delete_after=10)
                                    except Exception as e:
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan di ronde ini. Anda tidak bisa menjawab sampai soal ini selesai.", delete_after=10)
                    await asyncio.wait_for(listen_for_answer(), timeout=10.0)
                except asyncio.TimeoutError:
                    if clue_index == len(clues) - 1:
                        await ctx.send(f"Waktu habis! Jawaban yang benar adalah **{item['name']}**.")
                    else:
                        continue
            if winner:
                await self.give_rewards_with_bonus_check(winner, ctx.channel)
                await ctx.send(f"🎉 **Benar!** {winner.mention} berhasil menebak **{item['name']}**!")
                leaderboard[winner.name] = leaderboard.get(winner.name, 0) + 1
            for user_id in list(self.cooldown_users.keys()):
                member = ctx.guild.get_member(user_id)
                if member and member.voice and member.voice.channel == ctx.channel:
                    if user_id in self.cooldown_users:
                        del self.cooldown_users[user_id]
                    try:
                        await member.timeout(None, reason="Ronde game telah berakhir.")
                    except discord.Forbidden:
                        pass
                    except Exception as e:
                        pass
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

    @commands.command(name="pernahgak")
    @commands.cooldown(1, 30, commands.BucketType.channel)
    async def pernahgak(self, ctx):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Kamu harus berada di voice channel untuk memulai game ini.", delete_after=10)
        vc = ctx.author.voice.channel
        members = [m for m in vc.members if not m.bot]
        if len(members) < 2:
            return await ctx.send("Game ini butuh minimal 2 orang di voice channel.", delete_after=10)
        if not await self.start_game_check(ctx):
            return
        if len(self.pernah_gak_pernah_data) < 10:
            await ctx.send("Tidak cukup pertanyaan di database untuk sesi ini (butuh minimal 10).")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            return
        questions = random.sample(self.pernah_gak_pernah_data, 10)
        session_results = []
        await ctx.send(embed=discord.Embed(title="🤔 Sesi 'Pernah Gak Pernah' Dimulai!", description="Akan ada **10 pertanyaan**! Siapkan reaksimu!", color=0xf1c40f))
        await asyncio.sleep(3)
        for i, statement in enumerate(questions):
            embed = discord.Embed(title=f"❓ Pertanyaan #{i+1} dari 10", description=f"## _{statement}_", color=0xf1c40f)
            embed.set_footer(text="Jawab dengan jujur menggunakan reaksi ✅ (Pernah) atau ❌ (Tidak Pernah) di bawah! Waktu 15 detik.")
            msg = await ctx.send(embed=embed)
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            await asyncio.sleep(15)
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
                                await self.give_rewards_with_bonus_check(user, ctx.channel)
                                round_rewarded_users.add(user.id)
                    elif str(reaction.emoji) == "❌":
                        async for user in reaction.users():
                            if not user.bot and user in members and user.id not in round_rewarded_users:
                                gak_pernah_users.append(user.display_name)
                                await self.give_rewards_with_bonus_check(user, ctx.channel)
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
                break
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

    @commands.command(name="hitungcepat")
    @commands.cooldown(1, 15, commands.BucketType.channel)
    async def hitungcepat(self, ctx):
        if not await self.start_game_check(ctx): return
        if len(self.hitung_cepat_data) < 10:
            await ctx.send("Tidak cukup soal di database untuk sesi ini (butuh minimal 10).")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            return
        problems = random.sample(self.hitung_cepat_data, 10)
        leaderboard = {}
        self.quiz_attempts_per_question[ctx.channel.id] = {}
        await ctx.send(embed=discord.Embed(title="⚡ Sesi Hitung Cepat Dimulai!", description="Akan ada **10 soal**! Jawab dengan cepat dan benar!", color=0xe74c3c))
        await asyncio.sleep(3)
        for i, item in enumerate(problems):
            problem, answer = item['problem'], str(item['answer'])
            self.quiz_attempts_per_question[ctx.channel.id] = {}
            embed = discord.Embed(title=f"🧮 Soal #{i+1} dari 10", description=f"## `{problem} = ?`", color=0xe74c3c)
            await ctx.send(embed=embed)
            try:
                async def listen_for_math_answer():
                    while True:
                        message = await self.bot.wait_for("message", check=lambda m: m.channel == ctx.channel and not m.author.bot)
                        if message.author.id in self.cooldown_users:
                            if datetime.now() < self.cooldown_users[message.author.id]:
                                try:
                                    await message.delete()
                                except discord.Forbidden:
                                    pass
                                await ctx.send(f"🚨 {message.author.mention}, Anda masih dalam cooldown di ronde ini. Tunggu atau soal akan berlanjut.", delete_after=5)
                                continue
                            else:
                                del self.cooldown_users[message.author.id]
                        user_attempts = self.quiz_attempts_per_question[ctx.channel.id].setdefault(message.author.id, 0)
                        if message.content.strip() == answer:
                            return message
                        else:
                            if message.content.strip().replace('-', '').isdigit():
                                await message.add_reaction("❌")
                                user_attempts += 1
                                self.quiz_attempts_per_question[ctx.channel.id][message.author.id] = user_attempts
                                if user_attempts >= 2:
                                    cooldown_end_time = datetime.now() + timedelta(seconds=30)
                                    self.cooldown_users[message.author.id] = cooldown_end_time
                                    try:
                                        await message.author.timeout(timedelta(seconds=30), reason="Melebihi batas percobaan kuis")
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan & di-timeout sementara (30 detik).", delete_after=10)
                                    except discord.Forbidden:
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan di ronde ini. Anda tidak bisa menjawab sampai soal ini selesai.", delete_after=10)
                                    except Exception as e:
                                        await ctx.send(f"🚨 {message.author.mention}, Anda kehabisan kesempatan di ronde ini. Anda tidak bisa menjawab sampai soal ini selesai.", delete_after=10)
                winner_msg = await asyncio.wait_for(listen_for_math_answer(), timeout=15.0)
                winner = winner_msg.author
                leaderboard[winner.id] = leaderboard.get(winner.id, 0) + 1
                await ctx.send(f"⚡ **Benar!** {winner.mention} menjawab **{answer}** dengan benar!")
                await self.give_rewards_with_bonus_check(winner, ctx.channel)
            except asyncio.TimeoutError:
                await ctx.send(f"Waktu habis! Jawaban yang benar adalah **{answer}**.")
            except Exception as e:
                pass
            for user_id in list(self.cooldown_users.keys()):
                member = ctx.guild.get_member(user_id)
                if member and member.voice and member.voice.channel == ctx.channel:
                    if user_id in self.cooldown_users:
                        del self.cooldown_users[user_id]
                    try:
                        await member.timeout(None, reason="Ronde game telah berakhir.")
                    except discord.Forbidden:
                        pass
                    except Exception as e:
                        pass
            if i < len(problems) - 1:
                await ctx.send(f"Soal berikutnya dalam **3 detik**...", delete_after=2.5)
                await asyncio.sleep(3)
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

    @commands.command(name="matamata")
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
            'spy': spy, 'location': location, 'players': members,
            'discussion_start_time': datetime.utcnow(),
            'vote_in_progress': False, 'game_ended': False
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
                await self.give_rewards_with_bonus_check(spy, ctx.channel)
                self.spyfall_game_states[ctx.channel.id]['game_ended'] = True
                await self.end_game_cleanup(ctx.channel.id, ctx.channel)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            pass
        finally:
            if ctx.channel.id in self.spyfall_game_states and not self.spyfall_game_states[ctx.channel.id]['game_ended']:
                self.spyfall_game_states[ctx.channel.id]['game_ended'] = True
                await self.end_game_cleanup(ctx.channel.id, ctx.channel)

    @commands.command(name="tuduh")
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
                        if p.id != spy.id: await self.give_rewards_with_bonus_check(p, ctx.channel)
                else:
                    await ctx.send(f"**Tuduhan Salah!** {member.mention} bukan mata-matanya. Lokasi sebenarnya adalah **{location}**.")
                    await ctx.send(f"**Mata-mata ({spy.mention}) menang!**")
                    await self.give_rewards_with_bonus_check(spy, ctx.channel)
                game['game_ended'] = True
                await self.end_game_cleanup(ctx.channel.id, ctx.channel)
            else:
                await ctx.send(f"❌ **Voting Gagal.** Tidak cukup suara untuk menuduh {member.mention}. Permainan dilanjutkan!")
                game['vote_in_progress'] = False
        except discord.NotFound:
            await ctx.send("Pesan voting tidak ditemukan.")
            game['vote_in_progress'] = False
        except Exception as e:
            game['vote_in_progress'] = False

    @commands.command(name="ungkap_lokasi", aliases=['ulokasi'])
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
            await self.give_rewards_with_bonus_check(spy, ctx.channel)
        else:
            await ctx.send(f"❌ **Mata-Mata Gagal Mengungkap Lokasi!** Tebakan {guessed_location} salah. Lokasi sebenarnya adalah **{location}**. Warga menang!")
            for p in game['players']:
                if p.id != spy.id:
                    await self.give_rewards_with_bonus_check(p, ctx.channel)
        game['game_ended'] = True
        await self.end_game_cleanup(ctx.channel.id, ctx.channel)

    @tasks.loop(time=time(hour=5, minute=0, tzinfo=None))
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

    @commands.command(name="jawab")
    async def jawab(self, ctx, *, answer: str):
        if not self.daily_puzzle: return await ctx.send("Belum ada teka-teki untuk hari ini. Sabar ya!")
        if ctx.author.id in self.daily_puzzle_solvers: return await ctx.send("Kamu sudah menjawab dengan benar hari ini!", ephemeral=True)
        if answer.lower() == self.daily_puzzle['answer'].lower():
            self.daily_puzzle_solvers.add(ctx.author.id)
            await self.give_rewards_with_bonus_check(ctx.author, ctx.channel)
            await ctx.message.add_reaction("✅")
            await ctx.send(f"🎉 Selamat {ctx.author.mention}! Jawabanmu benar!")
        else:
            await ctx.message.add_reaction("❌")

    @commands.command(name="adddonasibtn")
    @commands.has_permissions(administrator=True)
    async def add_donation_button_cmd(self, ctx, label: str, url: str):
        if not url.startswith("http://") and not url.startswith("https://"):
            return await ctx.send("❌ URL tidak valid. Harus dimulai dengan `http://` atau `https://`.", ephemeral=True)
        donation_buttons_data = load_json_from_root(self.DONATION_BUTTONS_FILE)
        new_button = {"label": label, "url": url}
        for btn in donation_buttons_data:
            if btn["label"] == label or btn["url"] == url:
                return await ctx.send(f"❌ Tombol dengan label atau URL yang sama sudah ada: '{label}'.", ephemeral=True)
        donation_buttons_data.append(new_button)
        save_json_to_root(donation_buttons_data, self.DONATION_BUTTONS_FILE)
        await ctx.send(f"✅ Tombol donasi '{label}' berhasil ditambahkan!")

    @commands.command(name="listdonasibtn")
    @commands.has_permissions(administrator=True)
    async def list_donation_buttons_cmd(self, ctx):
        donation_buttons_data = load_json_from_root(self.DONATION_BUTTONS_FILE)
        if not donation_buttons_data:
            return await ctx.send("Tidak ada tombol donasi yang terdaftar.")
        embed = discord.Embed(title="💸 Daftar Tombol Donasi", color=discord.Color.blue())
        for i, btn in enumerate(donation_buttons_data):
            embed.add_field(name=f"Tombol #{i+1}", value=f"Label: `{btn['label']}`\nURL: <{btn['url']}>", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="removedonasibtn")
    @commands.has_permissions(administrator=True)
    async def remove_donation_button_cmd(self, ctx, index: int):
        donation_buttons_data = load_json_from_root(self.DONATION_BUTTONS_FILE)
        if not donation_buttons_data:
            return await ctx.send("Tidak ada tombol donasi untuk dihapus.", ephemeral=True)
        if not (1 <= index <= len(donation_buttons_data)):
            return await ctx.send(f"❌ Indeks tidak valid. Gunakan `!listdonasibtn` untuk melihat indeks yang benar (1 sampai {len(donation_buttons_data)}).", ephemeral=True)
        removed_button = donation_buttons_data.pop(index - 1)
        save_json_to_root(donation_buttons_data, self.DONATION_BUTTONS_FILE)
        await ctx.send(f"✅ Tombol donasi '{removed_button['label']}' berhasil dihapus.")

async def setup(bot):
    await bot.add_cog(Games1(bot))

