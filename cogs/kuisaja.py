import discord
from discord.ext import commands
import json
import random
import asyncio
import os
import aiohttp
from io import BytesIO

class HangmanQuiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.quiz_data = self.load_hangman_data()  # Mengambil data dari hangman
        self.bank_data = self.load_bank_data()
        self.current_question = None
        self.current_answers = {}
        self.participants = []
        self.correct_count = {}
        self.bantuan_used = {}
        self.bantuan_price = 25
        self.quiz_active = False
        self.messages = []
        self.host = None
        self.question_active = False

    def load_hangman_data(self):
        current_dir = os.path.dirname(__file__)
        file_path = os.path.join(current_dir, '..', 'data', 'questions_hangman.json')  # Mengambil dari file hangman
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if "questions" in data and isinstance(data["questions"], list):
                return data["questions"]
            else:
                raise ValueError("Data tidak dalam format yang benar!")

    def load_bank_data(self):
        with open('data/bank_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)

    async def get_user_image(self, ctx, user_data):
        """Mengambil gambar pengguna dari URL yang disimpan atau menggunakan avatar pengguna."""
        custom_image_url = user_data.get("image_url") or str(ctx.author.avatar.url)

        # Cek validitas URL gambar
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(custom_image_url) as resp:
                    if resp.status == 200:
                        image_data = BytesIO(await resp.read())
                        return image_data
                    else:
                        raise Exception("Invalid image URL")
        except Exception:
            default_image_url = str(ctx.author.avatar.url)
            async with aiohttp.ClientSession() as session:
                async with session.get(default_image_url) as resp:
                    return BytesIO(await resp.read())

    @commands.command(name="ressman", help="Mulai Kuis Hangman")
    async def reshangman(self, ctx):
        if self.quiz_active:
            await ctx.send("Kuis sudah aktif, tunggu hingga sesi ini selesai!", ephemeral=True)
            return

        self.host = ctx.author
        embed = discord.Embed(
            title="🎮 Kuis Hangman! 🎮",
            description=(
                "Selamat datang di Kuis Hangman! 🖤\n\n"
                "**Cara Main:**\n"
                "1. Akan ada 10 pertanyaan Hangman.\n"
                "2. Semua peserta bisa menjawab dengan sistem siapa cepat dia dapat.\n"
                "3. Jawaban benar = +25 RSWN.\n"
                "4. Bonus 50 RSWN jika semua pertanyaan dijawab benar.\n"
                "5. Minimal 2 peserta.\n\n"
                "Klik tombol di bawah untuk mulai."
            ),
            color=0x00ff00
        )

        view = discord.ui.View()
        start_button = discord.ui.Button(label="🎮 Mulai Kuis", style=discord.ButtonStyle.primary)

        async def start_quiz(interaction):
            if self.quiz_active:
                await ctx.send("Kuis sudah dimulai!", ephemeral=True)
                return
            if ctx.author != self.host:
                await ctx.send("Hanya host yang bisa memulai kuis!", ephemeral=True)
                return

            self.quiz_active = True
            await ctx.send("Kuis dimulai!")
            await self.start_quiz(ctx)

        start_button.callback = start_quiz
        view.add_item(start_button)

        await ctx.send(embed=embed, view=view)

    async def start_quiz(self, ctx):
        if ctx.guild is None:
            await ctx.send("Kuis hanya dapat dimulai di server!", ephemeral=True)
            return

        self.participants = [ctx.author]
        for member in ctx.guild.members:
            if len(self.participants) >= 5:
                break
            if member != ctx.author and not member.bot:
                self.participants.append(member)

        if len(self.participants) < 2:
            await ctx.send("😢 Minimal 2 peserta diperlukan untuk memulai kuis!")
            return

        for participant in self.participants:
            self.correct_count[participant.id] = 0
            self.bantuan_used[participant.id] = 0

        questions_to_ask = random.sample(self.quiz_data, min(10, len(self.quiz_data)))
        for question in questions_to_ask:
            self.current_question = question
            await self.ask_question(ctx, question)

        await self.end_quiz(ctx)

    async def ask_question(self, ctx, question):
        embed = discord.Embed(
            title="⏳ Pertanyaan Hangman!",
            description=f"Tebak kata ini: **{self.display_word(question['word'], self.current_answers.values())}**",
            color=0x0000ff
        )
        message = await ctx.send(embed=embed)
        self.messages.append(message)

        self.current_answers.clear()
        self.question_active = True

        for i in range(15, 0, -1):
            embed.description = f"Tebak kata ini: **{self.display_word(question['word'], self.current_answers.values())}**\nWaktu tersisa: {i} detik"
            await message.edit(embed=embed)
            await asyncio.sleep(1)

        self.question_active = False
        await self.evaluate_answers(ctx, question)

    async def evaluate_answers(self, ctx, question):
        if not self.question_active:
            return
        
        correct_answer = question['word'].strip().lower()
        answer_found = False

        for participant in self.participants:
            if participant.id in self.current_answers:
                user_answer = self.current_answers[participant.id].strip().lower()

                if user_answer == correct_answer:
                    self.correct_count[participant.id] += 1
                    self.bank_data[str(participant.id)]['balance'] += 25
                    await ctx.send(f"✅ {participant.mention} menjawab dengan benar! Jawabannya: **{correct_answer}**")
                    answer_found = True
                    break

        await asyncio.sleep(2)

        if answer_found:
            await ctx.send("➡️ Pertanyaan berikutnya...")
        self.question_active = False

    async def end_quiz(self, ctx):
        for message in self.messages:
            await message.delete()

        embed = discord.Embed(title="🏆 Hasil Kuis Hangman!", color=0x00ff00)

        for participant in self.participants:
            correct = self.correct_count.get(participant.id, 0)
            total_questions = 10
            wrong = total_questions - correct
            earned = correct * 25

            pid = str(participant.id)
            if pid not in self.bank_data:
                self.bank_data[pid] = {"balance": 0}

            final_balance = self.bank_data[pid]['balance']
            initial_balance = final_balance + earned  # karena udah dikurangi pas benar

            user_data = self.bank_data.get(pid, {})
            image_data = await self.get_user_image(ctx, user_data)

            embed.add_field(
                name=f"{participant.display_name} {participant.mention}",
                value=(
                    f"Jawaban Benar: {correct}\n"
                    f"Jawaban Salah: {wrong}\n"
                    f"Saldo RSWN Awal: {initial_balance}\n"
                    f"Saldo RSWN Akhir: {final_balance}\n"
                    f"Total RSWN Didapat: {earned}\n"
                ),
                inline=False
            )

            # Mengirim gambar pengguna
            if image_data:
                await ctx.send(file=discord.File(image_data, "avatar.png"))

        await ctx.send(embed=embed)

        with open('data/bank_data.json', 'w', encoding='utf-8') as f:
            json.dump(self.bank_data, f, indent=4)

        self.quiz_active = False
        self.messages.clear()
        self.participants.clear()
        self.correct_count.clear()
        self.current_answers.clear()

    def display_word(self, word, guessed_letters):
        displayed_word = ''.join([letter if letter in guessed_letters else '_' for letter in word])
        return displayed_word

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not self.quiz_active:
            return

        if message.author in self.participants and self.current_question:
            user_answer = message.content.strip().lower()
            if user_answer not in self.current_answers.values():
                self.current_answers[message.author.id] = user_answer
                await self.evaluate_answers(message.channel, self.current_question)

async def setup(bot):
    await bot.add_cog(HangmanQuiz(bot))
