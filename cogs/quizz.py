import discord
from discord.ext import commands
import json
import random
import asyncio
import os

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

class QuizButton(discord.ui.Button):
    def __init__(self, label, option_letter, parent_view):
        super().__init__(label=f"{option_letter}. {label}", style=discord.ButtonStyle.primary)
        self.parent_view = parent_view
        self.option_letter = option_letter

    async def callback(self, interaction: discord.Interaction):
        if not hasattr(self.parent_view, "participants"):
            await interaction.response.send_message("Sesi kuis tidak valid. Coba lagi.", ephemeral=True)
            return

        if interaction.user.id not in self.parent_view.participants:
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

class MusicQuiz(commands.Cog):
    SCORES_FILE = "scores.json"
    LEVEL_FILE = "data/level_data.json"
    BANK_FILE = "data/bank_data.json"

    def __init__(self, bot):
        self.bot = bot
        self.load_questions()
        self.scores = {}
        self.active_quizzes = {}  # guild_id: bool

    def load_questions(self):
        try:
            with open("questions.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                self.questions = data.get("questions", [])
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading questions.json: {e}")
            self.questions = []

    def load_json(self, path):
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from {path}: {e}")
            return {}

    def save_json(self, path, data):
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving JSON to {path}: {e}")

    # --- FUNGSI PENANGANAN AKHIR GAME UNTUK DONASI ---
    async def end_game_cleanup(self, guild_id, channel_obj=None):
        """
        Membersihkan status kuis aktif dan menampilkan tombol donasi.
        """
        if guild_id in self.active_quizzes:
            self.active_quizzes.pop(guild_id, None)
            print(f"Kuis musik di server {guild_id} telah selesai.")
        
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


    async def join(self, ctx):
        if not ctx.author.voice:
            await ctx.send("Kamu harus ada di voice channel.")
            return False

        channel = ctx.author.voice.channel

        if not ctx.guild.voice_client or not ctx.guild.voice_client.is_connected():
            try:
                await channel.connect()
                await ctx.send(f"Bot telah bergabung ke {channel.name}.\n\n🎉 Siap-siap kuis!\nCara main: Bot akan memberikan pertanyaan pilihan ganda, kamu tinggal klik jawabannya secepat mungkin!\nKamu cuma punya 5 detik! Jawab benar duluan, kamu menang!")
                return True
            except discord.ClientException:
                await ctx.send("Gagal bergabung ke voice channel. Mungkin bot sudah di channel lain atau ada masalah izin.")
                return False
        if ctx.guild.voice_client.channel != channel:
            await ctx.send("Bot sudah terhubung ke channel lain. Pindahkan bot ke channel ini atau gunakan channel yang sama.")
            return False

        await ctx.send(f"Bot sudah berada di {channel.name}.")
        return True

    @commands.command(name="join", help="Bot akan bergabung ke ruang voice.")
    async def join_command(self, ctx):
        await self.join(ctx)

    @commands.command(name="startquiz")
    async def start_quiz(self, ctx):
        guild_id = ctx.guild.id
        if self.active_quizzes.get(guild_id):
            await ctx.send("❗ Masih ada sesi kuis yang aktif di server ini. Selesaikan dulu sebelum mulai baru.")
            await self.end_game_cleanup(guild_id, ctx.channel) # Add cleanup if game can't start
            return
        
        if not self.questions:
            await ctx.send("Tidak ada pertanyaan kuis yang tersedia. Silakan tambahkan pertanyaan ke `questions.json`.")
            return

        joined = await self.join(ctx)
        if not joined:
            await self.end_game_cleanup(guild_id, ctx.channel) # Add cleanup if bot can't join VC
            return

        self.active_quizzes[guild_id] = True

        try:
            participants = [member.id for member in ctx.author.voice.channel.members if not member.bot]
            if len(participants) == 0:
                await ctx.send("Tidak ada peserta non-bot di voice channel. Kuis dibatalkan.")
                return # This will lead to finally block and cleanup

            self.scores = {str(member_id): 0 for member_id in participants}
            bonus_winners = []

            await ctx.send("⏳ Bersiaplah... Kuis akan dimulai dalam 3 detik!")
            await asyncio.sleep(3)
            await ctx.send("🎬 Selamat datang di kuis musik! Semoga kalian tidak fals jawabnya! 😎🎶")

            def make_callback(question, is_bonus, correct_users):
                async def callback(interaction, is_correct):
                    uid = str(interaction.user.id)
                    if uid not in self.scores:
                        self.scores[uid] = 0 # Initialize score if somehow not in participants (shouldn't happen with current logic)
                    if is_correct:
                        self.scores[uid] += 1
                        if is_bonus:
                            correct_users.append(uid)
                        await interaction.followup.send(f"✅ {interaction.user.mention} Jawaban benar!", ephemeral=False)
                    else:
                        await interaction.followup.send(f"❌ {interaction.user.mention} Salah! Jawaban yang benar: **{question['answer']}**", ephemeral=False)
                return callback

            # Create a shuffled list of questions to draw from
            shuffled_questions = random.sample(self.questions, min(20, len(self.questions)))

            for nomor, q in enumerate(shuffled_questions[:20], 1): # Play up to 20 questions
                is_bonus = nomor >= 15
                correct_users_this_round = [] # Reset for each question

                view = QuizView(q["options"], q["answer"], participants, make_callback(q, is_bonus, correct_users_this_round))
                embed = discord.Embed(
                    title=f"🎤 Pertanyaan {nomor}{' (BONUS)' if is_bonus else ''}",
                    description=q["question"],
                    color=discord.Color.gold() if is_bonus else discord.Color.blurple()
                )
                msg = await ctx.send(embed=embed, view=view)
                view.message = msg
                
                try:
                    await view.wait() # Wait for timeout or button press
                except asyncio.TimeoutError:
                    await ctx.send(f"Waktu habis untuk pertanyaan ini! Jawaban yang benar: **{q['answer']}**")
                    # Disable buttons if timeout occurred without a response
                    for child in view.children:
                        child.disabled = True
                    await msg.edit(view=view)

                # Add correct users from this round to overall bonus winners list
                if is_bonus:
                    bonus_winners.extend(correct_users_this_round)

                await asyncio.sleep(5) # Pause between questions

            await self.send_leaderboard(ctx, bonus_winners)
        finally:
            # Ensure cleanup happens regardless of how the try block exits
            await self.end_game_cleanup(guild_id, ctx.channel)


    async def send_leaderboard(self, ctx, bonus_winners):
        sorted_scores = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        top3 = sorted_scores[:3]

        level_data = self.load_json(self.LEVEL_FILE)
        bank_data = self.load_json(self.BANK_FILE)

        rewards = [(50, 150), (25, 100), (15, 50)] # EXP, RSWN for 1st, 2nd, 3rd

        embed = discord.Embed(title="🏆 **Leaderboard Akhir Kuis Musik:**", color=0x1DB954)
        if not top3:
            embed.description = "Tidak ada yang mendapatkan skor. Mungkin tidak ada yang menjawab dengan benar."
        else:
            for i, (user_id, score) in enumerate(top3):
                user = self.bot.get_user(int(user_id))
                name = user.display_name if user else f"Pengguna Tidak Dikenal ({user_id})"
                exp_reward, rswn_reward = rewards[i]

                # Ensure guild and user data structures exist
                level_data.setdefault(str(ctx.guild.id), {}).setdefault(user_id, {"exp": 0, "level": 1})
                bank_data.setdefault(user_id, {"balance": 0, "debt": 0})

                level_data[str(ctx.guild.id)][user_id]["exp"] += exp_reward
                bank_data[user_id]["balance"] += rswn_reward

                embed.add_field(name=f"{i+1}. {name}", value=f"Skor: {score}\n+{exp_reward} EXP, +{rswn_reward} RSWN", inline=False)

        self.save_json(self.LEVEL_FILE, level_data)
        self.save_json(self.BANK_FILE, bank_data)

        await ctx.send(embed=embed)

        # Bonus Reward Announcement
        bonus_award_summary = {}
        for uid in bonus_winners:
            # Ensure data structures
            level_data.setdefault(str(ctx.guild.id), {}).setdefault(uid, {"exp": 0, "level": 1})
            bank_data.setdefault(uid, {"balance": 0, "debt": 0})

            level_data[str(ctx.guild.id)][uid]["exp"] += 25
            bank_data[uid]["balance"] += 25

            user = self.bot.get_user(int(uid))
            name = user.display_name if user else f"Pengguna Tidak Dikenal ({uid})"
            bonus_award_summary[name] = bonus_award_summary.get(name, 0) + 1 # Track how many times they won bonus

        self.save_json(self.LEVEL_FILE, level_data)
        self.save_json(self.BANK_FILE, bank_data)

        if bonus_award_summary:
            desc = ""
            for name, count in bonus_award_summary.items():
                desc += f"✅ **{name}** mendapatkan +{count * 25} EXP & +{count * 25} RSWN dari {count} babak bonus!\n"

            embed = discord.Embed(title="🎉 Hadiah Bonus!", description=desc, color=discord.Color.green())
            await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(MusicQuiz(bot))
