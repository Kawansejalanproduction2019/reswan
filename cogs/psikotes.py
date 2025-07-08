import discord
from discord.ext import commands, tasks
import json
import random
import asyncio
import os
from datetime import datetime, time, timedelta

# --- Helper Functions (reusable from other cogs) ---
def load_json_from_root(file_path, default_value=None):
    """
    Memuat data JSON dari file yang berada di root direktori proyek bot.
    Menambahkan `default_value` yang lebih fleksibel.
    """
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        os.makedirs(os.path.dirname(os.path.abspath(full_path)), exist_ok=True) # Pastikan direktori ada
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[{datetime.now()}] [DEBUG HELPER] Peringatan: File {full_path} tidak ditemukan. Mengembalikan nilai default.")
        if default_value is not None:
            save_json_to_root(default_value, file_path)
            return default_value
        # Default value for common JSON types
        if 'questions' in file_path or 'sambung_kata_words' in file_path: # Ini untuk jiwabot_questions.json juga
            return []
        if 'bank_data' in file_path or 'level_data' in file_path:
            return {}
        return {} # Fallback
    except json.JSONDecodeError:
        print(f"[{datetime.now()}] [DEBUG HELPER] Peringatan: File {full_path} rusak (JSON tidak valid). Mengembalikan nilai default.")
        if default_value is not None:
            save_json_to_root(default_value, file_path)
            return default_value
        if 'questions' in file_path or 'sambung_kata_words' in file_path:
            return []
        if 'bank_data' in file_path or 'level_data' in file_path:
            return {}
        return {}


def save_json_to_root(data, file_path):
    """Menyimpan data ke file JSON di root direktori proyek."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    full_path = os.path.join(base_dir, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


class JiwaBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # {user_id: {'thread': thread_obj, 'current_q_idx': int, 'scores': {}, 'user_obj': member_obj, 'questions_for_session': [], 'message_for_reaction_vote': msg_obj}}
        self.active_sessions = {}  
        self.questions = load_json_from_root('data/jiwabot_questions.json', default_value=[])
        self.results_config = load_json_from_root('data/jiwabot_results.json', default_value={
            "dimensions": {},
            "advice": [], "critique": [], "evaluation": [], "future_steps": []
        })
        # self.admin_role_id = 1255204693391441920 # BARIS INI DIHAPUS/DINONAKTIFKAN
        
        # Mapping numerical emojis to option keys (A, B)
        self.number_emojis = {
            "1️⃣": "A", 
            "2️⃣": "B"
        }
        self.reverse_number_emojis = {v: k for k, v in self.number_emojis.items()}

        # Initiate cleanup task in case bot restarts unexpectedly
        self._cleanup_threads_task = self.cleanup_stale_threads.start()

    def cog_unload(self):
        # Cancel any running tasks when the cog is unloaded
        if self._cleanup_threads_task:
            self._cleanup_threads_task.cancel()
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Cog JiwaBot dibongkar. Tugas cleanup dihentikan.")


    @tasks.loop(minutes=30) # Run cleanup every 30 minutes
    async def cleanup_stale_threads(self):
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Menjalankan tugas pembersihan thread yang macet.")
        sessions_to_clean = list(self.active_sessions.keys()) 
        for user_id in sessions_to_clean:
            session = self.active_sessions.get(user_id)
            if session and session.get('thread'):
                try:
                    await self.bot.fetch_channel(session['thread'].id)
                except discord.NotFound:
                    print(f"[{datetime.now()}] [DEBUG JIWABOT] Menghapus sesi macet untuk user ID {user_id} karena thread {session['thread'].id} tidak ditemukan di Discord.")
                    del self.active_sessions[user_id]
                except Exception as e:
                    print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Error saat membersihkan thread {session['thread'].id} untuk user ID {user_id}: {e}")

    @cleanup_stale_threads.before_loop
    async def before_cleanup_threads(self):
        await self.bot.wait_until_ready()
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Menunggu bot siap sebelum memulai tugas pembersihan thread.")


    @commands.command(name="jiwaku", help="Mulai sesi tes kepribadian JiwaBot.")
    @commands.guild_only() # Pastikan hanya bisa di guild (server)
    async def start_personality_test(self, ctx):
        user_id = ctx.author.id
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Command !jiwaku dipanggil oleh {ctx.author.display_name} ({user_id}).")

        if user_id in self.active_sessions:
            thread_id = self.active_sessions[user_id]['thread'].id
            print(f"[{datetime.now()}] [DEBUG JIWABOT] {ctx.author.display_name} sudah punya sesi aktif di thread {thread_id}.")
            return await ctx.send(f"Anda sudah memiliki sesi tes yang sedang berjalan di <#{thread_id}>. Selesaikan sesi Anda saat ini atau tunggu hingga berakhir.", ephemeral=True)

        if not self.questions:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Bank pertanyaan jiwabot_questions.json kosong atau tidak ditemukan.")
            return await ctx.send("Maaf, bank pertanyaan tes kepribadian tidak ditemukan atau kosong. Silakan hubungi admin bot.", ephemeral=True)
        
        # Check if there are enough questions to draw 50 unique questions
        if len(self.questions) < 50:
            print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Jumlah pertanyaan di jiwabot_questions.json kurang dari 50. Hanya {len(self.questions)} ditemukan. Tes tidak dapat dimulai.")
            return await ctx.send(f"Maaf, tes membutuhkan minimal 50 pertanyaan unik. Saat ini hanya ada {len(self.questions)} pertanyaan. Silakan hubungi admin bot.", ephemeral=True)

        # Buat thread privat
        try:
            thread = await ctx.channel.create_thread(
                name=f"Tes-Kepribadian-{ctx.author.name}",
                type=discord.ChannelType.private_thread,
                invitable=False, # Tidak bisa di-invite sembarangan
                auto_archive_duration=60 # Arsip setelah 1 jam tidak aktif
            )
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Thread privat '{thread.name}' ({thread.id}) dibuat untuk {ctx.author.display_name}.")
            await thread.add_user(ctx.author) # Tambahkan peserta

            # --- Bagian untuk menambahkan admin dihapus ---
            # if self.admin_role_id:
            #     admin_role = ctx.guild.get_role(self.admin_role_id)
            #     if admin_role:
            #         for member in admin_role.members:
            #             try:
            #                 await thread.add_user(member)
            #                 print(f"[{datetime.now()}] [DEBUG JIWABOT] Admin {member.display_name} ditambahkan ke thread {thread.name}.")
            #             except discord.HTTPException as e:
            #                 print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Gagal menambahkan admin {member.display_name} ke thread {thread.name}: {e}")
            
            await ctx.send(f"Tes kepribadian Anda telah dimulai! Silakan lanjutkan di thread privat: <#{thread.id}>", ephemeral=False)
            
        except discord.Forbidden:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Bot tidak memiliki izin membuat thread di channel {ctx.channel.name}. Error: Forbidden.")
            return await ctx.send("Saya tidak memiliki izin untuk membuat private thread. Pastikan saya punya izin 'Manage Threads' dan 'Send Messages in Threads'.", ephemeral=True)
        except Exception as e:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Gagal membuat thread untuk {ctx.author.name}: {e}")
            return await ctx.send(f"Terjadi kesalahan saat memulai sesi: `{e}`. Silakan coba lagi nanti.", ephemeral=True)

        # Inisialisasi semua dimensi skor yang mungkin ada di questions.json
        all_possible_dimensions = self._get_all_dimensions()
        initial_scores = {dim: 0 for dim in all_possible_dimensions}
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Dimensi skor yang diinisialisasi: {all_possible_dimensions}")

        # Select 50 unique questions for this session
        questions_for_this_session = random.sample(self.questions, 50)
        print(f"[{datetime.now()}] [DEBUG JIWABOT] {len(questions_for_this_session)} pertanyaan dipilih secara acak untuk sesi ini.")

        self.active_sessions[user_id] = {
            'thread': thread,
            'current_q_idx': 0,
            'scores': initial_scores, 
            'user_obj': ctx.author,
            'questions_for_session': questions_for_this_session, 
            'message_for_reaction_vote': None,
            'answered_this_question': False 
        }
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Sesi baru dimulai untuk {ctx.author.display_name} ({user_id}).")
        
        await self._send_question(user_id)


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not isinstance(message.channel, discord.Thread):
            return
        
        user_id_from_session = None
        for uid, s in self.active_sessions.items():
            if s.get('thread') and s['thread'].id == message.channel.id:
                user_id_from_session = uid
                break

        if not user_id_from_session or message.author.id != user_id_from_session:
            return

        print(f"[{datetime.now()}] [DEBUG JIWABOT] Pesan teks diterima di thread sesi {message.channel.name} dari {message.author.display_name}: '{message.content}'.")
        pass


    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or user.id not in self.active_sessions:
            return

        session = self.active_sessions[user.id]

        if reaction.message.channel.id != session['thread'].id or \
           not session.get('message_for_reaction_vote') or \
           reaction.message.id != session['message_for_reaction_vote'].id:
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Reaksi diabaikan dari {user.display_name} (bukan di pesan kuis aktif).")
            return

        print(f"[{datetime.now()}] [DEBUG JIWABOT] Reaksi '{reaction.emoji}' ditambahkan oleh {user.display_name} ({user.id}) di thread {session['thread'].name}.")

        chosen_option_key = self.number_emojis.get(str(reaction.emoji))
        if chosen_option_key is None:
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Reaksi tidak valid '{reaction.emoji}' dari {user.display_name}. Menghapus reaksi.")
            try:
                await reaction.remove(user)
            except discord.Forbidden:
                print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Bot tidak bisa menghapus reaksi tidak valid dari {user.display_name} karena izin.")
            return

        if session['answered_this_question']:
            print(f"[{datetime.now()}] [DEBUG JIWABOT] {user.display_name} mencoba menjawab ulang pertanyaan #{session['current_q_idx'] + 1}. Reaksi diabaikan.")
            try:
                await reaction.remove(user)
            except discord.Forbidden:
                pass
            return

        session['answered_this_question'] = True
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Jawaban '{chosen_option_key}' diterima dari {user.display_name} untuk pertanyaan #{session['current_q_idx'] + 1}.")

        await self._process_answer(user.id, chosen_option_key, reaction.message, user)


    async def _send_question(self, user_id):
        session = self.active_sessions.get(user_id)
        if not session:
            print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Sesi tidak ditemukan untuk user ID {user_id} saat mencoba mengirim pertanyaan. Mungkin sesi sudah berakhir atau dibatalkan.")
            return

        thread = session['thread']
        q_idx = session['current_q_idx']
        
        # Logika ini yang sangat penting: Jika indeks pertanyaan sudah mencapai jumlah total pertanyaan yang disiapkan untuk sesi, maka selesaikan sesi.
        if q_idx >= len(session['questions_for_session']):
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Semua {len(session['questions_for_session'])} pertanyaan telah dikirim untuk user ID {user_id}. Mengakhiri sesi.")
            await self._end_session(user_id)
            return

        question_data = session['questions_for_session'][q_idx]
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Mempersiapkan pertanyaan #{q_idx + 1} dari {len(session['questions_for_session'])} untuk {session['user_obj'].display_name}.")
        
        embed = discord.Embed(
            title=f"❓ Pertanyaan #{q_idx + 1}/50", # Pastikan ini selalu menunjukkan 50
            description=f"**{question_data['question']}**\n\n"
                        f"**1.** {question_data['options']['A']}\n"
                        f"**2.** {question_data['options']['B']}",
            color=discord.Color.blue()
        )
        if 'category' in question_data:
            embed.add_field(name="Kategori", value=question_data['category'], inline=True) 

        embed.set_footer(text=f"Silakan bereaksi dengan 1️⃣ atau 2️⃣ untuk memilih jawaban Anda.")

        try:
            question_msg = await thread.send(embed=embed)
            session['message_for_reaction_vote'] = question_msg 
            await question_msg.add_reaction("1️⃣")
            await question_msg.add_reaction("2️⃣")
            session['answered_this_question'] = False # Reset for new question
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Pertanyaan #{q_idx + 1} berhasil dikirim ke thread {thread.name}.")
        except discord.Forbidden:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Bot tidak memiliki izin mengirim atau bereaksi di thread {thread.name} untuk {session['user_obj'].display_name}. Error: Forbidden.")
            await thread.send("Saya tidak bisa mengirim atau bereaksi di thread ini. Pastikan izin saya sudah benar (Manage Threads, Send Messages in Threads, Add Reactions).")
            await self._end_session(user_id)
        except Exception as e:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Gagal mengirim pertanyaan #{q_idx + 1} ke {session['user_obj'].display_name}: {e}")
            await thread.send(f"Terjadi kesalahan saat menampilkan pertanyaan: `{e}`. Sesi dihentikan.")
            await self._end_session(user_id)

    async def _process_answer(self, user_id, chosen_option_key, question_message, reacting_user):
        session = self.active_sessions.get(user_id)
        if not session:
            print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Sesi tidak ditemukan untuk user ID {user_id} saat memproses jawaban.")
            return

        q_idx = session['current_q_idx']
        question_data = session['questions_for_session'][q_idx]
        
        selected_scores = question_data['scores'].get(chosen_option_key, {})
        for dimension, points in selected_scores.items():
            session['scores'][dimension] = session['scores'].get(dimension, 0) + points
        
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Skor untuk pertanyaan #{q_idx + 1} dari {session['user_obj'].display_name}: Jawaban '{chosen_option_key}', Penambahan skor: {selected_scores}.")

        session['current_q_idx'] += 1

        try:
            await question_message.clear_reactions()
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Reaksi dibersihkan dari pesan pertanyaan #{q_idx + 1}.")
        except discord.Forbidden:
            print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Bot tidak bisa menghapus reaksi dari pesan {question_message.id} karena izin.")
        except Exception as e:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Error menghapus reaksi dari pesan {question_message.id}: {e}")

        # Send next question or end session
        await self._send_question(user_id)


    def _get_all_dimensions(self):
        """Collects all unique dimension keys from questions to initialize scores."""
        dimensions = set()
        if not self.questions: # Handle case where questions data might be empty
            return []
        for q_data in self.questions:
            for option_key in q_data['options']: 
                if option_key in q_data['scores']: 
                    for dim in q_data['scores'][option_key].keys():
                        dimensions.add(dim)
        return list(dimensions)


    async def _end_session(self, user_id):
        session = self.active_sessions.pop(user_id, None)
        if not session:
            print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Sesi tidak ditemukan untuk user ID {user_id} saat mengakhiri sesi. Mungkin sudah selesai.")
            return

        thread = session['thread']
        user_obj = session['user_obj']
        final_scores = session['scores']

        print(f"[{datetime.now()}] [DEBUG JIWABOT] Tes selesai untuk {user_obj.display_name}. Final skor yang akan dianalisis: {final_scores}")

        await thread.send(f"✅ Tes Kepribadian Anda telah selesai, {user_obj.mention}!\nMemproses hasil Anda...", embed=discord.Embed(title="Tes Selesai!", description="Terima kasih telah berpartisipasi!", color=discord.Color.green()))
        
        # Give some processing time illusion
        await asyncio.sleep(3)

        # Generate and send results to thread and DM
        await self._analyze_and_present_results(thread, user_obj, final_scores)

        # Delete the thread after a delay
        # Thread will be deleted after 3 minutes (180 seconds)
        asyncio.create_task(self._delete_thread_after_delay(thread, 180, user_obj))

    async def _delete_thread_after_delay(self, thread, delay, user_obj):
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Menunggu {delay} detik sebelum menghapus thread {thread.name} untuk {user_obj.display_name}.")
        await asyncio.sleep(delay)
        try:
            await thread.delete()
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Thread tes kepribadian {thread.name} untuk {user_obj.display_name} dihapus.")
        except discord.NotFound:
            print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Thread {thread.name} sudah tidak ditemukan (mungkin sudah dihapus manual).")
        except discord.Forbidden:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Bot tidak memiliki izin untuk menghapus thread {thread.name} untuk {user_obj.display_name}. Izin 'Manage Threads' mungkin diperlukan.")
            try:
                await user_obj.send(f"⚠️ Maaf, saya tidak bisa menghapus thread tes kepribadian Anda ({thread.mention}). Mohon hapus secara manual untuk menjaga privasi.")
            except discord.Forbidden:
                print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Gagal mengirim DM ke {user_obj.display_name} tentang kegagalan hapus thread (DM tertutup).")
        except Exception as e:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Error menghapus thread {thread.name} untuk {user_obj.display_name}: {e}")


    async def _analyze_and_present_results(self, thread, user_obj, final_scores):
        """
        Menganalisis skor dan menyajikan hasil psikotes secara rinci ke thread dan DM user.
        Memecah menjadi beberapa embed jika terlalu panjang.
        """
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Memulai analisis hasil untuk {user_obj.display_name}. Skor: {final_scores}")
        if not self.results_config.get('dimensions'):
            error_msg_content = "Maaf, konfigurasi hasil tes tidak ditemukan atau rusak. Tidak bisa menganalisis hasil. Silakan hubungi admin bot untuk memeriksa file 'jiwabot_results.json'."
            await thread.send(error_msg_content)
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Konfigurasi hasil tes (jiwabot_results.json) tidak ditemukan atau tidak valid.")
            try:
                await user_obj.send(error_msg_content)
            except discord.Forbidden:
                pass
            return

        # --- Bagian Data yang Dikumpulkan dari Skor ---
        social_type = "Tidak Terdefinisi"
        social_description = "Analisis lebih lanjut diperlukan untuk mengidentifikasi kecenderungan sosial Anda."
        intro_score = final_scores.get("introvert", 0)
        extro_score = final_scores.get("ekstrovert", 0)
        intro_extro_relative_score = intro_score - extro_score 

        if self.results_config['dimensions'] and "introvert_ekstrovert" in self.results_config['dimensions'] and \
           self.results_config['dimensions']['introvert_ekstrovert'].get('thresholds'):
            for threshold in self.results_config['dimensions']['introvert_ekstrovert']['thresholds']:
                if threshold['min_score'] <= intro_extro_relative_score <= threshold['max_score']:
                    social_type = threshold['type']
                    social_description = threshold['description']
                    break
        else:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Konfigurasi 'introvert_ekstrovert' atau 'thresholds' hilang/rusak di jiwabot_results.json.")
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Kecenderungan Sosial: {social_type} (Skor Relatif: {intro_extro_relative_score}).")

        all_identified_traits = [] # Stores {'name': 'Sifat', 'score': X, 'description': '...', 'type': 'sifat_dasar'/'gaya_interaksi'}
        identified_traits_for_reco = [] # Stores just the 'name' string for recommendation matching

        # Collect Sifat Dasar
        if "sifat_dasar" in self.results_config['dimensions'] and self.results_config['dimensions'].get('sifat_dasar', {}).get('categories'):
            for category in self.results_config['dimensions']['sifat_dasar']['categories']:
                dim_name_lower = category['name'].lower().replace(" ", "_")
                current_dim_score = final_scores.get(dim_name_lower, 0)
                if current_dim_score >= category.get('min_score', 0): 
                    all_identified_traits.append({
                        "name": category['name'], 
                        "score": current_dim_score, 
                        "description": category['description'],
                        "type": "sifat_dasar"
                    })
        
        # Collect Gaya Interaksi
        if "gaya_interaksi" in self.results_config['dimensions'] and self.results_config['dimensions'].get('gaya_interaksi', {}).get('categories'):
            for category in self.results_config['dimensions']['gaya_interaksi']['categories']:
                dim_name_lower = category['name'].lower().replace(" ", "_")
                current_dim_score = final_scores.get(dim_name_lower, 0)
                if current_dim_score >= category.get('min_score', 0):
                    all_identified_traits.append({
                        "name": category['name'], 
                        "score": current_dim_score, 
                        "description": category['description'],
                        "type": "gaya_interaksi"
                    })

        # Sort all identified traits by score in descending order
        all_identified_traits_sorted = sorted(all_identified_traits, key=lambda x: x['score'], reverse=True)
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Semua sifat dan gaya teridentifikasi & terurut: {all_identified_traits_sorted}.")
        
        # Populate identified_traits_for_reco list (just names)
        for trait in all_identified_traits_sorted:
            identified_traits_for_reco.append(trait['name'])

        # --- Embed 1: Kartu Profil Utama (Top 3) ---
        card_embed = discord.Embed(
            title=f"✨ **Laporan Utama: Profil Kepribadian Anda** ✨",
            description=f"Sebuah pandangan sekilas ke dalam diri **{user_obj.display_name}**.",
            color=discord.Color.from_rgb(255, 165, 0) # Orange/Gold color
        )
        card_embed.set_thumbnail(url=user_obj.avatar.url if user_obj.avatar else None)
        card_embed.set_image(url="https://images.unsplash.com/photo-1542435503-956c469947f6?fit=crop&w=1200&h=600&q=80") # Gambar latar abstrak keren
        card_embed.set_author(name=f"Oleh JiwaBot", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)

        card_embed.add_field(
            name="Orientasi Sosial Utama", 
            value=f"**{social_type}**", 
            inline=False # Set to False for better readability of longer texts
        )

        top_traits_text = []
        for i, trait in enumerate(all_identified_traits_sorted[:3]): # Ambil top 3 sifat/gaya dominan
            top_traits_text.append(f"• **{trait['name']}** (Skor: {trait['score']})")
        
        if top_traits_text:
            card_embed.add_field(name="Top 3 Sifat & Gaya Dominan", value="\n".join(top_traits_text), inline=False)
        else:
            card_embed.add_field(name="Sifat/Gaya Dominan", value="Belum ada sifat dominan yang menonjol dalam analisis awal ini.", inline=False)
        
        card_embed.set_footer(text="Geser untuk laporan lebih lengkap dan rekomendasi pribadi.")
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Kartu profil selesai dibuat.")


        # --- Embed 2: Identitas & Kecenderungan Sosial Lebih Detail ---
        embed1 = discord.Embed( # Renamed from embed1 for clarity in sending order
            title=f"📊 Laporan Psikotes: Bagian 1 - Identitas & Sosial",
            description=f"Analisis kepribadian mendalam untuk **{user_obj.display_name}**.",
            color=discord.Color.blue()
        )
        embed1.set_author(name=f"Oleh JiwaBot", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)

        profile_value = (
            f"• **Display Name (Nickname)**: {user_obj.display_name}\n"
            f"• **ID Pengguna Discord**: {user_obj.id}"
        )
        embed1.add_field(name="📋 Identitas Diri", value=profile_value, inline=False)
        embed1.add_field(
            name=f"Kecenderungan Sosial Utama: **{social_type}**",
            value=f"Anda menunjukkan karakteristik yang dominan sebagai individu dengan kecenderungan **{social_type}**. \n_{social_description}_",
            inline=False
        )
        embed1.add_field(name="Detail Skor Sosial", value=f"Poin Introvert: **{intro_score}** | Poin Ekstrovert: **{extro_score}**", inline=False)
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Embed Bagian 1 (Identitas & Sosial) selesai.")


        # --- Embed 3: Profil Sifat & Sikap Mendalam ---
        embed2 = discord.Embed( # Renamed from embed2 for clarity in sending order
            title=f"📊 Laporan Psikotes: Bagian 2 - Sifat & Sikap Dominan",
            description=f"Detail sifat dan sikap yang menonjol pada **{user_obj.display_name}**.",
            color=discord.Color.green()
        )
        embed2.set_author(name=f"Oleh JiwaBot", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        
        sifat_texts_content = []
        if self.results_config['dimensions'] and self.results_config['dimensions'].get('sifat_dasar', {}).get('categories'):
            for trait in all_identified_traits_sorted: # Use the already sorted list
                if trait['type'] == 'sifat_dasar':
                    sifat_texts_content.append(f"• **{trait['name']}** (Skor: {trait['score']}): {trait['description']}")
        
        if sifat_texts_content:
            # Join and check total length, splitting into multiple fields if necessary
            current_sifat_field_text = ""
            field_count = 0
            for line in sifat_texts_content:
                if len(current_sifat_field_text) + len(line) + 1 > 1024: # +1 for newline
                    embed2.add_field(name=f"Sifat & Sikap Dominan {'(Lanjutan)' if field_count > 0 else ''}", value=current_sifat_field_text, inline=False)
                    current_sifat_field_text = line
                    field_count += 1
                else:
                    current_sifat_field_text += line + "\n"
            if current_sifat_field_text: # Add any remaining text
                embed2.add_field(name=f"Sifat & Sikap Dominan {'(Lanjutan)' if field_count > 0 else ''}", value=current_sifat_field_text, inline=False)
        else:
            embed2.add_field(name="Sifat & Sikap Dominan", value="Berdasarkan respons, Anda memiliki beragam sifat dan sikap yang cukup seimbang dan adaptif, tidak ada yang terlalu dominan menonjol. Ini menunjukkan fleksibilitas dalam menghadapi berbagai situasi.", inline=False)
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Embed Bagian 2 (Sifat) selesai.")


        # --- Embed 4: Gaya Interaksi & Peran dalam Lingkungan ---
        embed3 = discord.Embed( # Renamed from embed3 for clarity in sending order
            title=f"📊 Laporan Psikotes: Bagian 3 - Gaya Interaksi & Peran",
            description=f"Analisis bagaimana **{user_obj.display_name}** berinteraksi dengan lingkungannya.",
            color=discord.Color.blue() # Change color for variety
        )
        embed3.set_author(name=f"Oleh JiwaBot", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)

        gaya_interaksi_texts_content = []
        if "gaya_interaksi" in self.results_config['dimensions'] and self.results_config['dimensions'].get('gaya_interaksi', {}).get('categories'):
            for trait in all_identified_traits_sorted: # Use sorted list
                if trait['type'] == 'gaya_interaksi':
                    trait_line = f"• **{trait['name']}** (Skor: {trait['score']}): {trait['description']}\n"
                    if len(current_sifat_field_text) + len(trait_line) + 1 > 1024: # Stay a bit below 1024
                        gaya_interaksi_texts_content.append(trait_line)
                    else:
                        current_sifat_field_text += trait_line # Continue adding if space allows
        
        if gaya_interaksi_texts_content:
            current_gaya_field_text = ""
            field_count = 0
            for line in gaya_interaksi_texts_content:
                if len(current_gaya_field_text) + len(line) + 1 > 1024:
                    embed3.add_field(name=f"Gaya Interaksi & Peran {'(Lanjutan)' if field_count > 0 else ''}", value=current_gaya_field_text, inline=False)
                    current_gaya_field_text = line
                    field_count += 1
                else:
                    current_gaya_field_text += line + "\n"
            if current_gaya_field_text:
                embed3.add_field(name=f"Gaya Interaksi & Peran {'(Lanjutan)' if field_count > 0 else ''}", value=current_gaya_field_text, inline=False)
        else:
            embed3.add_field(name="Gaya Interaksi & Peran dalam Lingkungan", value="Gaya interaksi Anda cukup fleksibel dan unik, sehingga tidak masuk dalam satu kategori dominan berdasarkan tes ini. Anda dapat menyesuaikan diri dengan berbagai peran.", inline=False)
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Embed Bagian 3 (Gaya Interaksi) selesai.")


        # --- Embed 5: Rekomendasi Komprehensif ---
        embed4 = discord.Embed( # Renamed from embed3 for clarity in sending order
            title=f"📊 Laporan Psikotes: Bagian 4 - Rekomendasi & Langkah Lanjut",
            description=f"Rekomendasi pengembangan diri komprehensif untuk **{user_obj.display_name}**.",
            color=discord.Color.dark_orange()
        )
        embed4.set_author(name=f"Oleh JiwaBot", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        
        all_relevant_types_for_reco = [social_type] + identified_traits_for_reco 
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Tipe dan sifat relevan untuk rekomendasi: {all_relevant_types_for_reco}.")

        recommendations_combined = {
            'advice': set(),    
            'critique': set(),
            'evaluation': set(),
            'future_steps': set()
        }

        for rec_key in recommendations_combined.keys():
            if self.results_config.get(rec_key) and isinstance(self.results_config[rec_key], list): 
                for rec_item in self.results_config[rec_key]:
                    if isinstance(rec_item, dict) and rec_item.get('for_type') and rec_item.get('text'):
                        if rec_item['for_type'] in all_relevant_types_for_reco:
                            recommendations_combined[rec_key].add(rec_item['text']) 
                    else:
                        print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Item rekomendasi '{rec_item}' tidak memiliki format for_type/text yang benar di {rec_key}.")
            else:
                print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Kunci rekomendasi '{rec_key}' hilang atau bukan list di jiwabot_results.json.")
        
        # Format values, respecting 1024 char limit per field
        # Break down each recommendation section into multiple fields if needed
        rec_sections = {
            "Saran Peningkatan Diri": recommendations_combined['advice'],
            "Area Pengembangan & Tantangan": recommendations_combined['critique'],
            "Potensi & Evaluasi Diri": recommendations_combined['evaluation'],
            "Rencana Tindak Lanjut": recommendations_combined['future_steps']
        }

        for title, texts_set in rec_sections.items():
            texts_list = sorted(list(texts_set))
            if not texts_list:
                embed4.add_field(name=title, value=f"Tidak ada {title.lower()} spesifik yang teridentifikasi dari tes ini.", inline=False)
                continue
            
            current_rec_field_text = ""
            field_count = 0
            for line in texts_list:
                formatted_line = f"• {line}\n"
                if len(current_rec_field_text) + len(formatted_line) > 1024:
                    embed4.add_field(name=f"{title} {'(Lanjutan)' if field_count > 0 else ''}", value=current_rec_field_text, inline=False)
                    current_rec_field_text = formatted_line
                    field_count += 1
                else:
                    current_rec_field_text += formatted_line
            if current_rec_field_text:
                embed4.add_field(name=f"{title} {'(Lanjutan)' if field_count > 0 else ''}", value=current_rec_field_text, inline=False)
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Embed Bagian 4 (Rekomendasi) selesai.")


        # --- Kirim Semua Embed ---
        embeds_to_send = [card_embed, embed1, embed2, embed3, embed4] # Now 5 embeds in total

        # Send to thread
        try:
            for i, embed_to_send in enumerate(embeds_to_send):
                await thread.send(embed=embed_to_send)
                await asyncio.sleep(0.5) # Small delay between embeds for better display
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Laporan hasil tes kepribadian (5 embed) berhasil dikirim ke thread {thread.name}.")
        except Exception as e:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Gagal mengirim laporan hasil (multi-embed) ke thread {thread.name}: {e}")
            await thread.send(f"❌ Terjadi kesalahan saat menampilkan laporan lengkap di thread: `{e}`. Silakan coba lagi atau hubungi admin bot.")


        # Send to user DM
        try:
            for i, embed_to_send in enumerate(embeds_to_send):
                await user_obj.send(embed=embed_to_send)
                await asyncio.sleep(0.5) # Small delay
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Laporan hasil tes kepribadian (multi-embed) berhasil dikirim ke DM {user_obj.display_name}.")
        except discord.Forbidden:
            print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Gagal mengirim laporan hasil (multi-embed) ke DM {user_obj.display_name} (DM ditutup).")
            await thread.send(f"⚠️ Maaf, saya tidak dapat mengirim laporan lengkap ke DM Anda, {user_obj.mention}, karena DM Anda mungkin tertutup. Laporan lengkap ada di thread ini (dalam beberapa bagian).", delete_after=30)
        except Exception as e:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Error mengirim laporan hasil (multi-embed) ke DM {user_obj.display_name}: {e}")

        print(f"[{datetime.now()}] [DEBUG JIWABOT] Proses analisis dan penyajian hasil selesai untuk {user_obj.display_name}.")


async def setup(bot):
    await bot.add_cog(JiwaBot(bot))
