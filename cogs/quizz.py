import discord
from discord.ext import commands, tasks
import json
import random
import asyncio
import os
from datetime import datetime, time, timedelta

# --- Helper Functions to handle JSON data from the bot's root directory ---
# These functions are designed to load/save JSON files relative to the bot's root directory ('../')
# They will also create the 'data' directory and empty default files if they don't exist or are corrupted.
def load_json_from_root(file_path, default_value=None):
    """
    Memuat data JSON dari file yang berada di root direktori proyek bot.
    Menambahkan `default_value` yang lebih fleksibel.
    """
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True) # Pastikan direktori ada
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[{datetime.now()}] [DEBUG HELPER] Peringatan: File {full_path} tidak ditemukan. Mengembalikan nilai default.")
        if default_value is not None:
            save_json_to_root(default_value, file_path) # Coba buat file dengan default
            return default_value
        # Default value untuk tipe data umum jika file tidak ditemukan
        if 'questions.json' in file_path:
            return {"questions": []} # Asumsi questions.json top-levelnya dict dengan key 'questions'
        if 'scores.json' in file_path or 'level_data.json' in file_path or 'bank_data.json' in file_path:
            return {}
        if 'donation_buttons.json' in file_path:
            return [] # Untuk tombol donasi, defaultnya list kosong
        return {} # Fallback
    except json.JSONDecodeError as e:
        print(f"[{datetime.now()}] [DEBUG HELPER] Peringatan: File {full_path} rusak (JSON tidak valid). Error: {e}. Mengembalikan nilai default.")
        if default_value is not None:
            save_json_to_root(default_value, file_path) # Coba buat ulang file dengan default jika rusak
            return default_value
        if 'questions.json' in file_path:
            return {"questions": []}
        if 'scores.json' in file_path or 'level_data.json' in file_path or 'bank_data.json' in file_path:
            return {}
        if 'donation_buttons.json' in file_path:
            return []
        return {}


def save_json_to_root(data, file_path):
    """Menyimpan data ke file JSON di root direktori proyek."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    full_path = os.path.join(base_dir, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True) # Pastikan direktori ada
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# --- New DonationView - MODIFIED TO LOAD BUTTONS FROM JSON ---
class DonationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Keep buttons active indefinitely
        self.load_donation_buttons()

    def load_donation_buttons(self):
        # Path relatif ke root proyek
        # Jika file tidak ditemukan atau kosong, load_json_from_root akan mengembalikan []
        donation_buttons_data = load_json_from_root('data/donation_buttons.json')
        
        # Jika data yang dimuat kosong, gunakan tombol default hardcoded
        if not donation_buttons_data:
            print(f"[{datetime.now()}] [DonationView] File 'data/donation_buttons.json' kosong atau tidak ditemukan. Menggunakan tombol default.")
            # Default buttons if JSON is empty or not found
            default_buttons = [
                {"label": "Dukung via Bagi-Bagi!", "url": "https://bagibagi.co/Rh7155"},
                {"label": "Donasi via Saweria!", "url": "https://saweria.co/RH7155"}
            ]
            donation_buttons_data = default_buttons

        # Tambahkan tombol ke view
        for button_info in donation_buttons_data:
            if "label" in button_info and "url" in button_info:
                button = discord.ui.Button(
                    label=button_info["label"],
                    style=discord.ButtonStyle.link,
                    url=button_info["url"]
                )
                self.add_item(button)
            else:
                print(f"[{datetime.now()}] [DonationView] Peringatan: Format tombol donasi tidak valid: {button_info}")

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

        # Menonaktifkan semua tombol setelah jawaban diberikan
        for child in self.parent_view.children:
            child.disabled = True

        await interaction.message.edit(view=self.parent_view)
        self.parent_view.stop() # Menghentikan View setelah jawaban diterima

class QuizView(discord.ui.View):
    def __init__(self, options, correct_answer, participants, on_answer):
        super().__init__(timeout=15) # Timeout 15 detik untuk setiap pertanyaan
        self.correct_answer = correct_answer
        self.participants = participants
        self.on_answer = on_answer
        # Menambahkan attribute answered_users untuk melacak siapa yang sudah menjawab di putaran ini
        self.answered_users = {str(p_id): False for p_id in participants}

        letters = ["A", "B", "C", "D"]
        for i, option in enumerate(options):
            self.add_item(QuizButton(option, letters[i], self))

class MusicQuiz(commands.Cog):
    # Constants for file paths, ensure they are relative to the bot's root 'data' directory
    QUESTIONS_FILE = "data/questions.json" # Asumsi questions.json ada di data/
    SCORES_FILE = "data/scores.json" # Asumsi scores.json ada di data/
    LEVEL_FILE = "data/level_data.json"
    BANK_FILE = "data/bank_data.json"

    def __init__(self, bot):
        self.bot = bot
        self.questions = self._load_questions_data() # Panggil helper function
        self.scores = {}
        self.active_quizzes = {}  # {guild_id: True/False} melacak apakah kuis aktif di guild ini
        self.disconnect_timers = {} # {guild_id: asyncio.Task} untuk timer auto-disconnect
        
        # Hapus inisialisasi quiz_attempts_per_question dan cooldown_users
        # self.quiz_attempts_per_question = {}
        # self.cooldown_users = {} 

        print(f"[{datetime.now()}] [MusicQuiz Cog] MusicQuiz cog initialized.")

    # --- Helper function untuk memuat data pertanyaan ---
    def _load_questions_data(self):
        # questions.json diharapkan memiliki struktur {"questions": [...]}
        data = load_json_from_root(self.QUESTIONS_FILE, default_value={"questions": []})
        return data.get("questions", [])

    # --- Helper function untuk memuat data JSON umum ---
    def _load_json_data(self, file_path):
        return load_json_from_root(file_path)

    # --- Helper function untuk menyimpan data JSON umum ---
    def _save_json_data(self, file_path, data):
        save_json_to_root(data, file_path)

    # --- FUNGSI PENANGANAN AKHIR GAME UNTUK DONASI DAN CLEANUP ---
    async def end_game_cleanup(self, guild_id, channel_obj=None):
        """
        Membersihkan status kuis aktif dan menampilkan tombol donasi.
        """
        if guild_id in self.active_quizzes:
            self.active_quizzes.pop(guild_id, None)
            print(f"[{datetime.now()}] [MusicQuiz Cog] Kuis musik di server {guild_id} telah selesai.")
        
        # Batalkan timer disconnect jika ada saat kuis berakhir
        if guild_id in self.disconnect_timers and not self.disconnect_timers[guild_id].done():
            self.disconnect_timers[guild_id].cancel()
            del self.disconnect_timers[guild_id]
            print(f"[{datetime.now()}] [MusicQuiz Cog] Disconnect timer untuk {guild_id} dibatalkan karena kuis berakhir.")

        # Disconnect bot dari voice channel jika masih terhubung
        guild = self.bot.get_guild(guild_id)
        if guild and guild.voice_client:
            await guild.voice_client.disconnect()
            print(f"[{datetime.now()}] [MusicQuiz Cog] Bot disconnected from voice channel in {guild.name} during cleanup.")
        
        # Hapus logika reset quiz attempts dan cooldowns
        # if guild_id in self.quiz_attempts_per_question:
        #     del self.quiz_attempts_per_question[guild_id]
        # for user_id in list(self.cooldown_users.keys()):
        #     member = guild.get_member(user_id)
        #     if member and member.voice and member.voice.channel == guild.voice_client.channel:
        #          if user_id in self.cooldown_users:
        #              del self.cooldown_users[user_id]
        #          try:
        #              await member.timeout(None, reason="Game ended, cooldown lifted.")
        #          except discord.Forbidden:
        #              pass
        #          except Exception as e:
        #              print(f"[{datetime.now()}] Error removing timeout on cleanup for {member.display_name}: {e}")


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
            print(f"[{datetime.now()}] [MusicQuiz Cog] Donation message sent after quiz cleanup.")

    async def join(self, ctx):
        if not ctx.author.voice:
            await ctx.send("Kamu harus ada di voice channel.", ephemeral=True)
            return False

        channel = ctx.author.voice.channel

        if not ctx.guild.voice_client or not ctx.guild.voice_client.is_connected():
            try:
                await channel.connect()
                await ctx.send(f"Bot telah bergabung ke **{channel.name}**.\n\n🎉 Siap-siap kuis!\nCara main: Bot akan memberikan pertanyaan pilihan ganda, kamu tinggal klik jawabannya secepat mungkin!\nKamu cuma punya 5 detik! Jawab benar duluan, kamu menang!")
                print(f"[{datetime.now()}] [MusicQuiz Cog] Bot joined VC {channel.name} in {ctx.guild.name}.")
                return True
            except discord.ClientException as e:
                await ctx.send(f"Gagal bergabung ke voice channel: {e}. Mungkin bot sudah di channel lain atau ada masalah izin.", ephemeral=True)
                print(f"[{datetime.now()}] [MusicQuiz Cog] Failed to join VC {channel.name}: {e}")
                return False
            except discord.Forbidden:
                await ctx.send("Aku tidak punya izin untuk bergabung ke voice channelmu. Pastikan aku punya izin `Connect` dan `Speak`.", ephemeral=True)
                print(f"[{datetime.now()}] [MusicQuiz Cog] Forbidden to join VC {channel.name}.")
                return False
        
        if ctx.guild.voice_client.channel != channel:
            await ctx.send("Bot sudah terhubung ke channel lain. Pindahkan bot ke channel ini atau gunakan channel yang sama.", ephemeral=True)
            print(f"[{datetime.now()}] [MusicQuiz Cog] Bot already in another VC in {ctx.guild.name}.")
            return False

        await ctx.send(f"Bot sudah berada di {channel.name}.", ephemeral=True)
        print(f"[{datetime.now()}] [MusicQuiz Cog] Bot already in VC {channel.name}.")
        return True

    @commands.command(name="join", help="Bot akan bergabung ke ruang voice.")
    async def join_command(self, ctx):
        await self.join(ctx)

    @commands.command(name="startquiz")
    async def start_quiz(self, ctx):
        guild_id = ctx.guild.id
        # Cek apakah sudah ada kuis aktif di guild ini
        if self.active_quizzes.get(guild_id):
            await ctx.send("❗ Masih ada sesi kuis yang aktif di server ini. Selesaikan dulu sebelum mulai baru.")
            print(f"[{datetime.now()}] [MusicQuiz Cog] Attempt to start quiz in active guild {guild_id}.")
            # Lakukan cleanup agar state tidak macet jika command dipanggil saat kuis stuck
            await self.end_game_cleanup(guild_id, ctx.channel)
            return
        
        # Cek apakah ada pertanyaan yang tersedia
        if not self.questions:
            await ctx.send("Tidak ada pertanyaan kuis yang tersedia. Silakan tambahkan pertanyaan ke `data/questions.json`.")
            print(f"[{datetime.now()}] [MusicQuiz Cog] No questions available in {ctx.guild.name}.")
            return

        # Coba gabungkan bot ke voice channel
        joined = await self.join(ctx)
        if not joined:
            # Jika bot gagal bergabung, lakukan cleanup dan batalkan kuis
            await self.end_game_cleanup(guild_id, ctx.channel)
            return

        self.active_quizzes[guild_id] = True # Tandai kuis sebagai aktif

        try:
            # Pastikan ada peserta non-bot di voice channel
            participants = [member.id for member in ctx.author.voice.channel.members if not member.bot]
            if len(participants) == 0:
                await ctx.send("Tidak ada peserta non-bot di voice channel. Kuis dibatalkan.")
                print(f"[{datetime.now()}] [MusicQuiz Cog] No human participants in VC. Quiz cancelled for {ctx.guild.name}.")
                # Ini akan mengarah ke finally block untuk cleanup
                return 

            self.scores = {str(member_id): 0 for member_id in participants} # Inisialisasi skor
            bonus_winners = [] # List untuk melacak pemenang bonus

            await ctx.send("⏳ Bersiaplah... Kuis akan dimulai dalam 3 detik!")
            await asyncio.sleep(3)
            await ctx.send("🎬 Selamat datang di kuis musik! Semoga kalian tidak fals jawabnya! 😎🎶")
            print(f"[{datetime.now()}] [MusicQuiz Cog] Quiz started in {ctx.guild.name}.")

            # Callback function untuk setiap jawaban
            def make_callback(question, is_bonus, correct_users_list):
                async def callback(interaction, is_correct):
                    uid = str(interaction.user.id)
                    # Hanya proses jawaban dari peserta yang valid dan belum menjawab di putaran ini
                    if uid in participants and not interaction.view.answered_users.get(uid, False):
                        interaction.view.answered_users[uid] = True # Tandai user sudah menjawab
                        if is_correct:
                            self.scores[uid] += 1
                            if is_bonus:
                                correct_users_list.append(uid)
                            await interaction.followup.send(f"✅ {interaction.user.mention} Jawaban benar!", ephemeral=False)
                            print(f"[{datetime.now()}] [MusicQuiz Cog] {interaction.user.display_name} answered correctly.")
                        else:
                            await interaction.followup.send(f"❌ {interaction.user.mention} Salah! Jawaban yang benar: **{question['answer']}**", ephemeral=False)
                            print(f"[{datetime.now()}] [MusicQuiz Cog] {interaction.user.display_name} answered incorrectly.")
                return callback

            # Acak dan pilih pertanyaan
            shuffled_questions = random.sample(self.questions, min(20, len(self.questions)))

            for nomor, q in enumerate(shuffled_questions[:20], 1): # Putar hingga 20 pertanyaan
                is_bonus = nomor >= 15 # Pertanyaan ke-15 dan seterusnya adalah bonus
                correct_users_this_round = [] # Reset pemenang bonus untuk putaran ini

                view = QuizView(q["options"], q["answer"], participants, make_callback(q, is_bonus, correct_users_this_round))
                view.answered_users = {str(p_id): False for p_id in participants} # Melacak siapa yang sudah menjawab di putaran ini
                
                embed = discord.Embed(
                    title=f"🎤 Pertanyaan {nomor}{' (BONUS)' if is_bonus else ''}",
                    description=q["question"],
                    color=discord.Color.gold() if is_bonus else discord.Color.blurple()
                )
                msg = await ctx.send(embed=embed, view=view)
                view.message = msg # Simpan referensi pesan untuk view

                try:
                    await view.wait() # Tunggu hingga timeout atau tombol ditekan
                except asyncio.TimeoutError:
                    await ctx.send(f"Waktu habis untuk pertanyaan ini! Jawaban yang benar: **{q['answer']}**")
                    print(f"[{datetime.now()}] [MusicQuiz Cog] Question {nomor} timed out.")
                    # Menonaktifkan tombol jika timeout terjadi tanpa jawaban
                    for child in view.children:
                        child.disabled = True
                    await msg.edit(view=view)
                
                # Tambahkan pemenang bonus dari putaran ini ke daftar keseluruhan
                if is_bonus:
                    bonus_winners.extend(correct_users_this_round)

                await asyncio.sleep(5) # Jeda antar pertanyaan

            await self.send_leaderboard(ctx, bonus_winners) # Kirim leaderboard akhir
        finally:
            # Pastikan cleanup terjadi terlepas dari bagaimana blok try berakhir
            await self.end_game_cleanup(guild_id, ctx.channel)
            print(f"[{datetime.now()}] [MusicQuiz Cog] Quiz process finished for {ctx.guild.name}. Triggering final cleanup.")


    async def send_leaderboard(self, ctx, bonus_winners):
        sorted_scores = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        top3 = sorted_scores[:3] # Ambil 3 teratas

        level_data = self._load_json_data(self.LEVEL_FILE)
        bank_data = self._load_json_data(self.BANK_FILE)

        rewards = [(50, 150), (25, 100), (15, 50)] # (EXP, RSWN) untuk juara 1, 2, 3

        embed = discord.Embed(title="🏆 **Leaderboard Akhir Kuis Musik:**", color=0x1DB954)
        if not top3:
            embed.description = "Tidak ada yang mendapatkan skor. Mungkin tidak ada yang menjawab dengan benar."
        else:
            for i, (user_id, score) in enumerate(top3):
                user = self.bot.get_user(int(user_id))
                name = user.display_name if user else f"Pengguna Tidak Dikenal ({user_id})"
                exp_reward, rswn_reward = rewards[i]

                # Pastikan struktur data guild dan user ada sebelum menambahkan hadiah
                level_data.setdefault(str(ctx.guild.id), {}).setdefault(user_id, {"exp": 0, "level": 1, "weekly_exp": 0, "badges": []})
                bank_data.setdefault(user_id, {"balance": 0, "debt": 0})

                level_data[str(ctx.guild.id)][user_id]["exp"] += exp_reward
                bank_data[user_id]["balance"] += rswn_reward
                
                # Juga update weekly_exp dan last_active
                level_data[str(ctx.guild.id)][user_id].setdefault("weekly_exp", 0)
                level_data[str(ctx.guild.id)][user_id]["weekly_exp"] += exp_reward
                level_data[str(ctx.guild.id)][user_id].setdefault("last_active", datetime.utcnow().isoformat())
                level_data[str(ctx.guild.id)][user_id]["last_active"] = datetime.utcnow().isoformat()

                embed.add_field(name=f"{i+1}. {name}", value=f"Skor: {score}\n+{exp_reward} EXP, +{rswn_reward} RSWN", inline=False)

        self._save_json_data(self.LEVEL_FILE, level_data)
        self._save_json_data(self.BANK_FILE, bank_data)

        await ctx.send(embed=embed)
        print(f"[{datetime.now()}] [MusicQuiz Cog] Leaderboard sent for {ctx.guild.name}.")

        # Pengumuman Hadiah Bonus
        bonus_award_summary = {}
        if bonus_winners: # Hanya proses jika ada pemenang bonus
            for uid in bonus_winners:
                # Pastikan struktur data
                level_data.setdefault(str(ctx.guild.id), {}).setdefault(uid, {"exp": 0, "level": 1, "weekly_exp": 0, "badges": []})
                bank_data.setdefault(uid, {"balance": 0, "debt": 0})

                level_data[str(ctx.guild.id)][uid]["exp"] += 25 # Hadiah bonus EXP
                bank_data[uid]["balance"] += 25 # Hadiah bonus RSWN

                user = self.bot.get_user(int(uid))
                name = user.display_name if user else f"Pengguna Tidak Dikenal ({uid})"
                bonus_award_summary[name] = bonus_award_summary.get(name, 0) + 1 # Hitung berapa kali menang bonus

            self._save_json_data(self.LEVEL_FILE, level_data)
            self._save_json_data(self.BANK_FILE, bank_data)

            if bonus_award_summary:
                desc = ""
                for name, count in bonus_award_summary.items():
                    desc += f"✅ **{name}** mendapatkan +{count * 25} EXP & +{count * 25} RSWN dari {count} babak bonus!\n"

                embed = discord.Embed(title="🎉 Hadiah Bonus!", description=desc, color=discord.Color.green())
                await ctx.send(embed=embed)
                print(f"[{datetime.now()}] [MusicQuiz Cog] Bonus rewards sent for {ctx.guild.name}.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Abaikan jika anggota adalah bot itu sendiri
        if member.id == self.bot.user.id:
            return

        # Abaikan jika bot tidak berada di voice channel di guild ini
        if not member.guild.voice_client:
            return
            
        voice_client = member.guild.voice_client
        
        # Cek apakah perubahan terjadi di channel tempat bot berada
        if before.channel != voice_client.channel and after.channel != voice_client.channel:
            return # Perubahan terjadi di channel lain yang tidak relevan dengan bot

        voice_channel = voice_client.channel
        guild_id = member.guild.id

        # Hitung anggota non-bot di channel bot (hanya mereka yang tidak mute/deafen diri sendiri)
        human_members_in_vc = [m for m in voice_channel.members if not m.bot and not m.voice.self_deaf and not m.voice.self_mute]

        if len(human_members_in_vc) == 0:
            # Jika tidak ada anggota manusia (yang aktif), mulai atau reset timer disconnect
            if guild_id in self.disconnect_timers and not self.disconnect_timers[guild_id].done():
                self.disconnect_timers[guild_id].cancel()
                print(f"[{datetime.now()}] [MusicQuiz Cog] Disconnect timer untuk {member.guild.name} dibatalkan (user keluar/masuk cepat).")

            async def disconnect_countdown():
                await asyncio.sleep(30) # Tunggu 30 detik
                # Cek lagi apakah channel masih kosong dan bot masih di VC sebelum disconnect
                current_human_members = [m for m in voice_channel.members if not m.bot and not m.voice.self_deaf and not m.voice.self_mute]
                if len(current_human_members) == 0 and voice_client and voice_client.is_connected():
                    # Jika ada kuis aktif, jangan disconnect. Ini agar bot tidak disconnect di tengah kuis.
                    if self.active_quizzes.get(guild_id):
                        print(f"[{datetime.now()}] [MusicQuiz Cog] Quiz is active in {member.guild.name}. Skipping auto-disconnect.")
                        return # Jangan disconnect jika kuis masih aktif

                    await voice_client.disconnect()
                    print(f"[{datetime.now()}] [MusicQuiz Cog] Bot keluar dari {voice_channel.name} karena kosong.")
                    
                    # Opsional: kirim pesan ke channel teks jika channel default/sistemnya ada
                    # Untuk MusicQuiz, pesan utama ada di channel tempat command dimulai
                    # Asumsi self.active_quizzes[guild_id] akan dihapus saat kuis selesai,
                    # jadi kita perlu channel konteks kuis untuk pesan auto-disconnect
                    # Kita bisa simpan channel_id di self.active_quizzes saat kuis dimulai
                    quiz_text_channel_id = self.active_quizzes.get(guild_id, {}).get('text_channel_id')
                    if quiz_text_channel_id:
                        text_channel = self.bot.get_channel(quiz_text_channel_id)
                        if text_channel:
                            await text_channel.send("Bot keluar dari voice channel karena tidak ada user aktif di dalamnya.")
                        else:
                            print(f"[{datetime.now()}] [MusicQuiz Cog] Text channel {quiz_text_channel_id} not found for auto-disconnect message.")
                    elif voice_channel.guild.system_channel: # Fallback ke system channel
                        await voice_channel.guild.system_channel.send("Bot keluar dari voice channel karena tidak ada user aktif di dalamnya.")
                
                # Hapus timer setelah selesai, terlepas dari apakah bot disconnect atau tidak
                del self.disconnect_timers[guild_id] 

            self.disconnect_timers[guild_id] = asyncio.create_task(disconnect_countdown())
            print(f"[{datetime.now()}] [MusicQuiz Cog] Disconnect timer 30 detik dimulai untuk {member.guild.name} di {voice_channel.name}.")

        elif len(human_members_in_vc) > 0:
            # Jika ada anggota manusia, batalkan timer disconnect jika ada
            if guild_id in self.disconnect_timers and not self.disconnect_timers[guild_id].done():
                self.disconnect_timers[guild_id].cancel()
                del self.disconnect_timers[guild_id]
                print(f"[{datetime.now()}] [MusicQuiz Cog] Disconnect timer untuk {member.guild.name} dibatalkan (ada user masuk).")

async def setup(bot):
    await bot.add_cog(MusicQuiz(bot))
