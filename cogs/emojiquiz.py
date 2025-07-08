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

class EmojiQuiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}
        self.bank_data = self.load_bank_data()
        self.level_data = self.load_level_data()
        self.questions = self.load_quiz_data()
        self.scores = {}  # Menyimpan skor peserta

        self.game_channel_id = 765140300145360896  # ID channel yang diizinkan
        self.bantuan_price = 35  # Harga bantuan
        self.reward_per_correct_answer = 30  # Hadiah per pertanyaan benar
        self.time_limit = 60  # Waktu batas untuk setiap pertanyaan

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
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            print(f"Error loading bank data: {e}")
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
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            print(f"Error loading level data: {e}")
            return {}
        except Exception as e:
            print(f"Error loading level data: {e}")
            return {}

    def load_quiz_data(self):
        current_dir = os.path.dirname(__file__)  # Folder cogs/
        file_path = os.path.join(current_dir, '..', 'data', 'emoji_questions.json')
        try:
            with open(file_path, "r", encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data.get("questions"), list) and len(data["questions"]) > 0:
                    return data["questions"]
                else:
                    raise ValueError("Data harus berupa list dan tidak kosong.")
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            print(f"Error loading quiz data: {e}")
            return []
        except Exception as e:
            print(f"Error loading quiz data: {e}")
            return []

    # --- FUNGSI PENANGANAN AKHIR GAME UNTUK DONASI ---
    async def end_game_cleanup(self, channel_id, channel_obj=None):
        """
        Membersihkan status game yang aktif dan menampilkan tombol donasi.
        """
        if channel_id in self.active_games:
            self.active_games.pop(channel_id, None)
            print(f"Game EmojiQuiz di channel {channel_id} telah selesai.")
        
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


    @commands.command(name="resmoji", help="Mulai permainan EmojiQuiz.")
    async def resmoji(self, ctx):
        if ctx.channel.id != self.game_channel_id:
            await ctx.send("Permainan EmojiQuiz hanya bisa dimainkan di channel yang ditentukan.")
            return

        # Memeriksa apakah sesi aktif untuk channel ini
        if ctx.channel.id in self.active_games:
            await ctx.send("Permainan sudah sedang berlangsung di channel ini.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel) # Cleanup if already active
            return
        
        self.scores = {}  # Reset skor untuk setiap permainan baru

        embed = discord.Embed(
            title="🎮 Cara Bermain EmojiQuiz",
            description=(
                "Selamat datang di **Kuis Emoji** — game buat kamu yang masih mau main meski server sepi... lagi. 💔\n\n"
                "📌 Kamu akan dikasih 1 atau lebih emoji dari bot.\n"
                "🫵 Tebak maksudnya, bisa 1–3 kata. Bebas.\n"
                "⏳ Kalau gak ada yang jawab dalam 1 menit, soal langsung lanjut ke berikutnya.\n"
                f"🎁 Jawaban benar dapet **+{self.reward_per_correct_answer} RSWN**. Lumayan buat beli badge atau sekadar merasa berguna.\n\n"
                "💸 Ngerasa buntu? Beli **bantuan** aja pake:\n"
                "**!resplis** – Harga: 35 RSWN. Dibalas via DM.\n"
                "*Bantuan gak dibatasin... karena kami ngerti, kadang kita butuh banyak petunjuk buat ngerti sesuatu.*\n\n"
                "🖤 Terima kasih buat kalian yang masih sering nongol di sini...\n"
                "Walau orangnya itu-itu aja, ... tapi hati kami tetap hangat karena kalian."
                "\n\nKlik tombol di bawah ini kalau kamu siap... atau kalau cuma pengen ditemani sebentar sama bot ini."
            ),
            color=0x5500aa
        )

        view = discord.ui.View()
        start_button = discord.ui.Button(label="🔵 START", style=discord.ButtonStyle.primary)

        async def start_game(interaction):
            # Menambahkan pengguna ke active_games dan mengatur data permainan
            self.active_games[ctx.channel.id] = {
                "user": ctx.author,
                "correct": 0,
                "wrong": 0,
                "current_question": None,
                "questions": [],
                "game_over": False,
                "bantuan_used": 0,
                "start_time": None,
                "total_rsw": 0
            }
            # Menghapus pesan tombol setelah ditekan
            await interaction.message.delete()
            await self.play_game(ctx)

        start_button.callback = start_game
        view.add_item(start_button)

        await ctx.send(embed=embed, view=view)

    @commands.command(name="resplis", help="Membeli bantuan untuk jawaban pertanyaan saat ini.")
    async def resplis(self, ctx):
        user_id = str(ctx.author.id)

        # Memastikan bahwa data pengguna ada di bank_data
        if user_id not in self.bank_data:
            self.bank_data[user_id] = {"balance": 0, "debt": 0}
            await ctx.send("Akun Anda telah dibuat. Saldo awal Anda adalah 0 RSWN.")

        user_data = self.bank_data[user_id]

        if user_data.get('balance', 0) < self.bantuan_price:
            await ctx.send("😢 Saldo RSWN tidak cukup untuk membeli bantuan.")
            return

        if ctx.channel.id not in self.active_games or self.active_games[ctx.channel.id].get("current_question") is None:
            await ctx.send("Tidak ada permainan aktif untuk membeli bantuan.")
            return

        initial_balance = user_data['balance']
        user_data['balance'] -= self.bantuan_price
        final_balance = user_data['balance']

        current_question_index = self.active_games[ctx.channel.id]["current_question"]
        current_question = self.active_games[ctx.channel.id]["questions"][current_question_index]

        try:
            await ctx.author.send(f"🔐 Jawaban untuk pertanyaan saat ini adalah: **{current_question['answer']}**")
            await ctx.author.send(f"✅ Pembelian bantuan berhasil! Saldo RSWN Anda berkurang dari **{initial_balance}** menjadi **{final_balance}**.")
            await ctx.send(f"{ctx.author.mention}, bantuan telah dikirim ke DM Anda!")
        except discord.Forbidden:
            await ctx.send(f"Gagal mengirim DM ke {ctx.author.mention}. Mohon aktifkan DM dari server ini.")
            user_data['balance'] += self.bantuan_price # Kembalikan uang

        with open('data/bank_data.json', 'w', encoding='utf-8') as f:
            json.dump(self.bank_data, f, indent=4)

    async def play_game(self, ctx):
        game_data = self.active_games[ctx.channel.id]
        game_data["start_time"] = asyncio.get_event_loop().time()

        if not self.questions:
            await ctx.send("Tidak ada pertanyaan yang tersedia. Pastikan emoji_questions.json diisi dengan benar.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel) # Call cleanup here
            return

        if len(self.questions) < 10:
            await ctx.send("Tidak cukup pertanyaan untuk memulai permainan. Pastikan ada setidaknya 10 pertanyaan di emoji_questions.json.")
            await self.end_game_cleanup(ctx.channel.id, ctx.channel) # Call cleanup here
            return

        game_data["questions"] = random.sample(self.questions, 10)

        for index, question in enumerate(game_data["questions"]):
            if game_data.get("game_over"):
                break
            game_data["current_question"] = index
            await self.ask_question(ctx, question)

        if not game_data.get("game_over"):
            await self.end_game(ctx)

    async def ask_question(self, ctx, question):
        game_data = self.active_games[ctx.channel.id]

        embed = discord.Embed(
            title=f"❓ Pertanyaan {game_data['current_question'] + 1}",
            description=(f"Emoji: **{question['emoji']}**\nSebutkan frasa yang sesuai!"),
            color=0x00ff00
        )
        await ctx.send(embed=embed)

        try:
            def check(m):
                return m.channel == ctx.channel and not m.author.bot

            while True:
                user_answer = await self.bot.wait_for('message', timeout=self.time_limit, check=check)

                if user_answer.content.strip().lower() == question['answer'].lower():
                    # --- PENAMBAHAN: Logika Integrasi DuniaHidup ---
                    # 1. Panggil fungsi "mata-mata" untuk cek kondisi dunia
                    anomaly_multiplier = self.get_anomaly_multiplier()
                    
                    # 2. Hitung hadiah final berdasarkan kondisi dunia
                    final_reward = int(self.reward_per_correct_answer * anomaly_multiplier)

                    if user_answer.author.id not in self.scores:
                        self.scores[user_answer.author.id] = {"score": 0, "correct": 0, "wrong": 0, "user": user_answer.author}
                    
                    # 3. Berikan hadiah yang sudah disesuaikan
                    game_data["correct"] += 1
                    game_data.setdefault("total_rsw", 0)
                    game_data["total_rsw"] += final_reward
                    self.scores[user_answer.author.id]["score"] += final_reward
                    self.scores[user_answer.author.id]["correct"] += 1

                    # 4. Beri tahu user kalau mereka dapat bonus
                    if anomaly_multiplier > 1:
                        await ctx.send(f"✅ Jawaban Benar dari {user_answer.author.display_name}! Karena ada anomali, hadiahmu dilipatgandakan menjadi **{final_reward} RSWN**!")
                    else:
                        await ctx.send(f"✅ Jawaban Benar dari {user_answer.author.display_name}! Kamu dapat **{final_reward} RSWN**.")
                    # --- INTEGRASI SELESAI ---
                    break
                else:
                    if user_answer.author.id not in self.scores:
                        self.scores[user_answer.author.id] = {"score": 0, "correct": 0, "wrong": 0, "user": user_answer.author}
                    self.scores[user_answer.author.id]["wrong"] += 1
                    await user_answer.add_reaction("❌") # Memberi feedback dengan reaksi

        except asyncio.TimeoutError:
            await ctx.send("Waktu habis! Melanjutkan ke soal berikutnya.")

    async def end_game(self, ctx):
        game_data = self.active_games.pop(ctx.channel.id, None)
        if game_data:
            # --- PENAMBAHAN: Update bank data dengan total RSWN yang dimenangkan ---
            bank_data = self.load_bank_data()
            for user_id, score_data in self.scores.items():
                user_id_str = str(user_id)
                if user_id_str not in bank_data:
                    bank_data[user_id_str] = {"balance": 0, "debt": 0}
                bank_data[user_id_str]['balance'] += score_data['score']
            
            with open('data/bank_data.json', 'w', encoding='utf-8') as f:
                json.dump(bank_data, f, indent=4)
            # --------------------------------------------------------------------

            await self.display_leaderboard(ctx)
            await self.end_game_cleanup(ctx.channel.id, ctx.channel) # Call cleanup at the very end

    async def display_leaderboard(self, ctx):
        if not self.scores:
            return # Tidak menampilkan leaderboard jika tidak ada yang bermain

        sorted_scores = sorted(self.scores.values(), key=lambda x: x["score"], reverse=True)
        embed = discord.Embed(title="🏆 Leaderboard Sesi EmojiQuiz", color=0x00ff00)

        for i, top_user_data in enumerate(sorted_scores[:5]):
            user = top_user_data['user']
            embed.add_field(
                name=f"#{i + 1}. {user.display_name}",
                value=(f"💰 **Total RSWN Didapat:** {top_user_data['score']}\n"
                       f"✅ **Jawaban Benar:** {top_user_data['correct']}\n"
                       f"❌ **Jawaban Salah:** {top_user_data['wrong']}"),
                inline=False
            )

        # Mengirim gambar pemenang pertama
        if sorted_scores:
            winner_user = sorted_scores[0]['user']
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(str(winner_user.display_avatar.url)) as resp:
                        if resp.status == 200:
                            image_data = BytesIO(await resp.read())
                            await ctx.send(file=discord.File(image_data, filename='winner_avatar.png'))
            except Exception as e:
                print(f"Gagal mengambil avatar pemenang: {e}")

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(EmojiQuiz(bot))
