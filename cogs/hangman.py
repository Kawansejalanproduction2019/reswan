import discord
from discord.ext import commands
import json
import random
import asyncio
import os
import aiohttp
from io import BytesIO

# New DonationView - reusable for any game cog
class DonationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Keep buttons active indefinitely

        bagi_bagi_button = discord.ui.Button(
            label="Dukung via Bagi-Bagi!",
            style=discord.ButtonStyle.link,
            url="https://bagibagi.co/Rh7155"
        )
        self.add_item(bagi_bagi_button)

        saweria_button = discord.ui.Button(
            label="Donasi via Saweria!",
            style=discord.ButtonStyle.link,
            url="https://saweria.co/RH7155"
        )
        self.add_item(saweria_button)

class Hangman(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}
        self.bank_data = self.load_bank_data()
        self.level_data = self.load_level_data()
        self.questions = self.load_hangman_data()
        self.scores = {}  # Menyimpan skor peserta per sesi

        self.game_channel_id = 765140300145360896  # ID channel yang diizinkan
        self.bantuan_price = 40 # Harga bantuan, bisa disesuaikan
        self.reward_per_correct_answer = 30 # Hadiah dasar per jawaban benar

    # --- PENAMBAHAN: Helper untuk "berkomunikasi" dengan cog DuniaHidup ---
    def get_anomaly_multiplier(self):
        """Mengecek apakah ada anomali EXP boost aktif dari cog DuniaHidup."""
        dunia_cog = self.bot.get_cog('DuniaHidup')
        if dunia_cog and dunia_cog.active_anomaly and dunia_cog.active_anomaly.get('type') == 'exp_boost':
            return dunia_cog.active_anomaly.get('effect', {}).get('multiplier', 1)
        return 1
    # ----------------------------------------------------------------------

    def load_bank_data(self):
        try:
            with open('data/bank_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                else:
                    raise ValueError("Data harus dalam format dictionary.")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error decoding JSON from bank_data.json: {e}")
            return {}
        except Exception as e:
            print(f"Error loading bank data: {e}")
            return {}

    def load_level_data(self):
        try:
            with open('data/level_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                else:
                    raise ValueError("Data harus dalam format dictionary.")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error decoding JSON from level_data.json: {e}")
            return {}
        except Exception as e:
            print(f"Error loading level data: {e}")
            return {}

    def load_hangman_data(self):
        current_dir = os.path.dirname(__file__)  # Folder cogs/
        file_path = os.path.join(current_dir, "..", "data", "questions_hangman.json")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
                else:
                    raise ValueError("Data harus berupa list dan tidak kosong.")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error decoding JSON from questions_hangman.json: {e}")
            return []
        except Exception as e:
            print(f"Error loading hangman data: {e}")
            return []
    
    # --- FUNGSI PENANGANAN AKHIR GAME UNTUK DONASI ---
    async def end_game_cleanup(self, channel_id, channel_obj=None):
        """
        Membersihkan status game Hangman yang aktif dan menampilkan tombol donasi.
        """
        if channel_id in self.active_games:
            self.active_games.pop(channel_id, None)
            print(f"Game Hangman di channel {channel_id} telah selesai.")
        
        if channel_obj:
            donation_message = (
                "🎮 **Permainan Telah Usai!** Terima kasih sudah bermain bersama kami.\n\n"
                "Apakah kamu menikmati ketegangan Hangman yang kami hadirkan?\n"
                "Dukung terus pengembangan bot ini agar kami bisa terus berinovasi dan "
                "memberikan pengalaman bermain yang lebih seru lagi!\n\n"
                "Donasi sekecil apa pun sangat berarti untuk kami! 🙏"
            )
            donation_view = DonationView()
            await channel_obj.send(donation_message, view=donation_view)


    @commands.command(name="resman", help="Mulai permainan Hangman.")
    async def hangman(self, ctx):
        if ctx.channel.id != self.game_channel_id:
            await ctx.send("Permainan Hangman hanya bisa dimainkan di channel yang ditentukan.")
            return

        if ctx.channel.id in self.active_games:
            await ctx.send("Permainan sudah sedang berlangsung di channel ini. Silakan tunggu hingga selesai.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel) # Cleanup if already active
            return

        self.scores = {}

        embed = discord.Embed(
            title="🎮 Cara Bermain Hangman",
            description=(
                "Selamat datang di Dunia Sunyi Hangman! 🖤🌧️\n\n"
                "Di sini, kamu tak hanya menebak kata... tapi juga menebak makna dari kesepian yang tak bertepi.\n"
                "Jawablah satu per satu, berharap RSWN bisa sedikit mengisi kekosongan itu.\n"
                "Selesaikan 10 soal... kalau kamu masih punya semangat itu.\n\n"
                "💸 Ngerasa buntu? Beli **bantuan** aja pake:\n"
                f"**!hmanplis** – Harga: {self.bantuan_price} RSWN. Jawaban dikirim via DM.\n"
                "*Karena terkadang, kita semua butuh sedikit cahaya di dalam gelap.*\n\n"
                "Kalau kamu cukup kuat, cukup tahan, cukup sad... klik tombol di bawah ini. Mulai permainanmu."
            ),
            color=0x5500aa
        )

        view = discord.ui.View()
        start_button = discord.ui.Button(label="🔵 START", style=discord.ButtonStyle.primary)

        async def start_game(interaction):
            await interaction.message.delete() # Hapus pesan setelah tombol diklik
            self.active_games[ctx.channel.id] = {
                "score": 0, "correct": 0, "wrong": 0, "current_question": 0,
                "time_limit": 120, "start_time": None, "question": None,
                "game_over": False, "answers": []
            }
            await ctx.send(f"{ctx.author.mention}, permainan Hangman dimulai!")
            await self.play_game(ctx)

        start_button.callback = start_game
        view.add_item(start_button)
        await ctx.send(embed=embed, view=view)


    @commands.command(name="hmanplis", help="Membeli bantuan untuk jawaban Hangman.")
    async def hmanplis(self, ctx):
        user_id = str(ctx.author.id)
        channel_id = ctx.channel.id

        if channel_id not in self.active_games:
            await ctx.send("Tidak ada permainan Hangman yang sedang berlangsung di channel ini.")
            return

        game_data = self.active_games[channel_id]
        
        if user_id not in self.bank_data:
            self.bank_data[user_id] = {"balance": 0, "debt": 0}

        user_data = self.bank_data[user_id]

        if user_data.get('balance', 0) < self.bantuan_price:
            await ctx.send(f"😢 Saldo RSWN tidak cukup untuk membeli bantuan. Harga: {self.bantuan_price} RSWN.")
            return

        initial_balance = user_data.get('balance', 0)
        user_data['balance'] -= self.bantuan_price
        final_balance = user_data['balance']

        # Pastikan game_data["question"] adalah list dan current_question adalah indeks yang valid
        # current_question di game_data adalah hitungan soal ke-, jadi dikurangi 1 untuk indeks
        current_question_index = game_data["current_question"] - 1 
        
        # Tambahan pengecekan untuk menghindari IndexError jika pertanyaan belum ada atau sudah lewat
        if game_data["question"] and 0 <= current_question_index < len(game_data["question"]):
            correct_word = game_data["question"][current_question_index]['word']
            try:
                await ctx.author.send(f"🔐 Jawaban untuk pertanyaan Hangman saat ini adalah: **{correct_word}**")
                await ctx.author.send(f"✅ Pembelian bantuan berhasil! Saldo RSWN Anda berkurang dari **{initial_balance}** menjadi **{final_balance}**.")
                await ctx.send(f"{ctx.author.mention}, bantuan telah berhasil dikirim ke DM Anda!")
                with open('data/bank_data.json', 'w', encoding='utf-8') as f:
                    json.dump(self.bank_data, f, indent=4)
            except discord.Forbidden:
                await ctx.send(f"{ctx.author.mention}, saya tidak bisa mengirim DM. Mohon aktifkan izin DM dari server ini.")
                user_data['balance'] += self.bantuan_price # Kembalikan uang
                with open('data/bank_data.json', 'w', encoding='utf-8') as f:
                    json.dump(self.bank_data, f, indent=4)
        else:
            await ctx.send("Tidak bisa mendapatkan pertanyaan saat ini. Mungkin game sedang berganti soal atau telah berakhir.")
            user_data['balance'] += self.bantuan_price # Kembalikan uang
            with open('data/bank_data.json', 'w', encoding='utf-8') as f:
                json.dump(self.bank_data, f, indent=4)


    async def play_game(self, ctx):
        game_data = self.active_games[ctx.channel.id]
        game_data["start_time"] = asyncio.get_event_loop().time()

        if not self.questions or len(self.questions) < 10:
            await ctx.send("Tidak cukup pertanyaan untuk memulai permainan. Hubungi admin.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel) # Cleanup on insufficient questions
            return

        game_data["question"] = random.sample(self.questions, 10)

        for index, question in enumerate(game_data["question"]):
            if game_data.get("game_over", False):
                break
            game_data["current_question"] = index + 1
            await self.ask_question(ctx, question)

        if not game_data.get("game_over", False):
            await self.end_game(ctx)

    async def ask_question(self, ctx, question):
        game_data = self.active_games[ctx.channel.id]

        embed = discord.Embed(
            title=f"❓ Pertanyaan {game_data['current_question']}/10",
            description=(
                f"Kategori: **{question['category']}**\n"
                f"Kisi-kisi: {question['clue']}\n"
                f"Sebutkan satu kata: `{self.display_word(question['word'], [])}`" # Tampilkan underscore
            ),
            color=0x00ff00
        )
        await ctx.send(embed=embed)

        try:
            def check(m):
                return m.channel == ctx.channel and not m.author.bot

            while True:
                user_answer_msg = await self.bot.wait_for('message', timeout=game_data["time_limit"], check=check)

                if user_answer_msg.content.strip().lower() == question['word'].lower():
                    # --- PENAMBAHAN: Logika Integrasi DuniaHidup ---
                    # 1. Panggil fungsi "mata-mata" untuk cek kondisi dunia
                    anomaly_multiplier = self.get_anomaly_multiplier()
                    
                    # 2. Hitung hadiah final berdasarkan kondisi dunia
                    final_reward = int(self.reward_per_correct_answer * anomaly_multiplier)
                    
                    author = user_answer_msg.author
                    author_id = author.id

                    if author_id not in self.scores:
                        self.scores[author_id] = {"user": author, "correct": 0, "wrong": 0, "total_rsw": 0}

                    # 3. Berikan hadiah yang sudah disesuaikan
                    self.scores[author_id]["correct"] += 1
                    self.scores[author_id]["total_rsw"] += final_reward
                    
                    # 4. Beri tahu user kalau mereka dapat bonus
                    if anomaly_multiplier > 1:
                        await ctx.send(f"✅ Jawaban Benar dari {author.display_name}! Karena ada anomali, hadiahmu dilipatgandakan menjadi **{final_reward} RSWN**!")
                    else:
                        await ctx.send(f"✅ Jawaban Benar dari {author.display_name}! Kamu dapat **{final_reward} RSWN**.")
                    # --- INTEGRASI SELESAI ---
                    break
                else:
                    if not user_answer_msg.content.startswith(self.bot.command_prefix): # Hindari reaksi ke command
                        author = user_answer_msg.author
                        author_id = author.id
                        if author_id not in self.scores:
                            self.scores[author_id] = {"user": author, "correct": 0, "wrong": 0, "total_rsw": 0}
                        self.scores[author_id]["wrong"] += 1
                        await user_answer_msg.add_reaction("❌")

        except asyncio.TimeoutError:
            await ctx.send(f"Waktu habis! Jawaban yang benar adalah **{question['word']}**.")
            # Tidak menghentikan game, hanya lanjut ke soal berikutnya

    def display_word(self, word, guessed_letters):
        # Di game ini, kita hanya menampilkan underscore sesuai panjang kata
        return ' '.join(['_' for _ in word])

    async def end_game(self, ctx):
        game_data = self.active_games.pop(ctx.channel.id, None)
        if game_data:
            # --- PENAMBAHAN: Update bank data dengan total RSWN yang dimenangkan ---
            bank_data = self.load_bank_data()
            level_data = self.load_level_data()
            guild_id = str(ctx.guild.id)

            for user_id, score_data in self.scores.items():
                user_id_str = str(user_id)
                # Tambah RSWN
                if user_id_str not in bank_data:
                    bank_data[user_id_str] = {"balance": 0, "debt": 0}
                bank_data[user_id_str]['balance'] += score_data['total_rsw']
                
                # Tambah EXP
                if user_id_str not in level_data.get(guild_id, {}):
                    level_data.setdefault(guild_id, {})[user_id_str] = {"exp": 0, "level": 0, "weekly_exp": 0, "badges": []}
                exp_gain = score_data['correct'] * 10 # Contoh 10 EXP per jawaban benar
                level_data[guild_id][user_id_str]['exp'] += exp_gain
                level_data[guild_id][user_id_str].setdefault('weekly_exp', 0)
                level_data[guild_id][user_id_str]['weekly_exp'] += exp_gain
                
            with open('data/bank_data.json', 'w', encoding='utf-8') as f:
                json.dump(bank_data, f, indent=4)
            with open('data/level_data.json', 'w', encoding='utf-8') as f:
                json.dump(level_data, f, indent=4)
            # --------------------------------------------------------------------
            
            await self.display_leaderboard(ctx)
            await self.end_game_cleanup(ctx.channel.id, ctx.channel) # Call cleanup after leaderboard

    async def display_leaderboard(self, ctx):
        if not self.scores:
            await ctx.send("Tidak ada yang berpartisipasi dalam sesi Hangman kali ini. 💔")
            return
            
        sorted_scores = sorted(self.scores.values(), key=lambda x: x["correct"], reverse=True)[:5]
        embed = discord.Embed(title="🏆 Leaderboard Sesi Hangman", color=0x00ff00)

        for i, score in enumerate(sorted_scores, start=1):
            user = score['user']
            embed.add_field(
                name=f"#{i}. {user.display_name}",
                value=(f"💰 **Total RSWN Didapat:** {score.get('total_rsw', 0)}\n"
                       f"✅ **Jawaban Benar:** {score['correct']}\n"
                       f"❌ **Jawaban Salah:** {score['wrong']}"),
                inline=False
            )

        if sorted_scores:
            top_user = sorted_scores[0]['user']
            image_url = str(top_user.display_avatar.url)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url) as resp:
                        if resp.status == 200:
                            image_data = BytesIO(await resp.read())
                            await ctx.send(file=discord.File(image_data, filename='winner_avatar.png'))
            except Exception as e:
                print(f"Error fetching image for {top_user.display_name}: {e}")

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Hangman(bot))
