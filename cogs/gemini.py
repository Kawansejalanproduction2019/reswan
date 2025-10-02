import discord
from discord.ext import commands, tasks
import json
import random
import asyncio
import os
from datetime import datetime, time, timedelta
import google.generativeai as genai
import logging
import re

# --- KONFIGURASI ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
log = logging.getLogger('CombinedCog')

GEMINI_MODEL = 'gemini-2.0-flash'
DISCORD_MSG_LIMIT = 2000
CACHE_FILE_PATH = 'data/gemini_cache.json'
URL_REGEX = re.compile(
    r'https?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|%[0-9a-fA-F][0-9a-fA-F])+'
)

try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable not set.")
    genai.configure(api_key=api_key)
except ValueError as e:
    log.error(e)

# --- FUNGSI HELPER & UTILITAS ---

def load_json_from_root(file_path, default_value=None):
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        os.makedirs(os.path.dirname(os.path.abspath(full_path)), exist_ok=True)
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[{datetime.now()}] [DEBUG HELPER] Peringatan: File {full_path} tidak ditemukan. Mengembalikan nilai default.")
        if default_value is not None:
            save_json_to_root(default_value, file_path)
            return default_value
        if 'questions' in file_path or 'sambung_kata_words' in file_path:
            return []
        if 'bank_data' in file_path or 'level_data' in file_path:
            return {}
        return {}
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
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    full_path = os.path.join(base_dir, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def load_data(file_path):
    default_data = {
        'sensitive_keywords': ['steampowered', 'steam', 'paypal', 'discord', 'nitro', 'login', 'bank', 
                               'freefire', 'ff', 'mobilelegends', 'ml', 'pubg', 'dana', 'gopay', 'ovo',
                               'claim', 'diamond', 'voucher', 'giveaway'],
        'suspicious_tlds': ['.co', '.xyz', '.site', '.info', '.biz', '.club', '.online', '.link', 
                            '.gq', '.cf', '.tk', '.ml', '.top', '.icu', '.stream', '.live'],
        'verified_urls': {}
    }
    try:
        if not os.path.exists(file_path):
            return default_data
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                return default_data
            data = json.loads(content)
            for key, default_value in default_data.items():
                if key not in data:
                    data[key] = default_value
            return data
    except (json.JSONDecodeError, IOError) as e:
        log.error(f"Gagal memuat data dari {file_path}: {e}")
        return default_data

def save_data(file_path, data):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        log.error(f"Gagal menyimpan data ke {file_path}: {e}")

async def send_long_message(ctx_or_channel, text):
    for chunk in [text[i:i+DISCORD_MSG_LIMIT] for i in range(0, len(text), DISCORD_MSG_LIMIT)]:
        await ctx_or_channel.send(chunk)

# --- COG UTAMA ---

class AutomationAI(commands.Cog, name="Automation AI and Personality Test"):
    def __init__(self, bot):
        self.bot = bot
        
        # --- Atribut dari JiwaBot ---
        self.active_sessions = {}
        self.questions = load_json_from_root('data/jiwabot_questions.json', default_value=[])
        self.results_config = load_json_from_root('data/jiwabot_results.json', default_value={
            "dimensions": {},
            "advice": [], "critique": [], "evaluation": [], "future_steps": []
        })
        self.number_emojis = {"1️⃣": "A", "2️⃣": "B"}
        self.reverse_number_emojis = {v: k for k, v in self.number_emojis.items()}
        self._cleanup_threads_task = self.cleanup_stale_threads.start()

        # --- Atribut dari GeminiCog ---
        try:
            self.model = genai.GenerativeModel(GEMINI_MODEL)
            log.info(f"Combined Cog (Model: {GEMINI_MODEL}) berhasil dimuat.")
        except Exception as e:
            log.error(f"Gagal memuat model Gemini: {e}")
            raise e
        
        self.active_chats = {}
        self.system_instructions = {}
        
        self.data = load_data(CACHE_FILE_PATH)
        self.sensitive_keywords = self.data['sensitive_keywords']
        self.suspicious_tlds = self.data['suspicious_tlds']
        self.verified_urls = self.data['verified_urls']

        self.warning_messages = [
            "Etto… maaf Senpai, Yuki terpaksa menghapus pesan ini. Sepertinya ada link yang mencurigakan di dalamnya. Hati-hati, ya! 😊",
            "Ano... link itu sepertinya berbahaya, Senpai. Demi keamanan, Yuki hapus saja, ya? Gomen nasai! ✨",
            "Yuki mendeteksi sesuatu yang tidak beres pada tautan yang Senpai kirim. Demi kebaikan kita bersama, pesan ini harus dihilangkan. 😉",
            "Hehehe, tautan itu nakal sekali, sampai-sampai Yuki harus menyuruhnya pergi. Lain kali jangan ajak dia main lagi, ya! (´• ω •`)",
            "Waduh, link yang Senpai kirim ini mau curi data! Untung Yuki lihat, jadi langsung Yuki usir. Jangan sampai kena tipu, lho! 😤",
            "Pesan Senpai hilang! Diculik sama link yang aneh. Jangan sedih, nanti Yuki buatkan yang baru! Ehehe~ ✨",
            "Link berbahaya terdeteksi. Pesan dihapus. Hati-hati, Senpai.",
            "🚨 Link phishing! Pesan dihapus."
        ]

    def cog_unload(self):
        if self._cleanup_threads_task:
            self._cleanup_threads_task.cancel()
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Cog JiwaBot dibongkar. Tugas cleanup dihentikan.")

    # --- LISTENER GABUNGAN ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # --- Logika 1: Gemini URL Filter ---
        urls_found = URL_REGEX.findall(message.content)
        if urls_found:
            log.info(f"URL ditemukan: {urls_found}")
            for url in urls_found:
                domain = url.split('//')[-1].split('/')[0]
                
                is_locally_suspicious = any(keyword in domain.lower() for keyword in self.sensitive_keywords) and \
                                        any(domain.endswith(tld) for tld in self.suspicious_tlds)
                
                if is_locally_suspicious:
                    log.warning(f"Filter lokal mendeteksi {url} sebagai mencurigakan.")
                    try:
                        await message.delete()
                        random_message = random.choice(self.warning_messages)
                        await message.channel.send(
                            f"❌ {random_message}\n(Pesan dari {message.author.mention})",
                            delete_after=10
                        )
                    except discord.Forbidden:
                        log.error("Tidak memiliki izin untuk menghapus pesan.")
                    return # Hentikan proses jika pesan dihapus
                
                if url in self.verified_urls:
                    result = self.verified_urls[url]
                    log.info(f"Menggunakan cache untuk {url}. Hasil: {result}")
                    if result == "YA":
                        log.warning(f"Cache mendeteksi {url} berbahaya.")
                        try:
                            await message.delete()
                            random_message = random.choice(self.warning_messages)
                            await message.channel.send(
                                f"❌ {random_message}\n(Pesan dari {message.author.mention})",
                                delete_after=10
                            )
                        except discord.Forbidden:
                            log.error("Tidak memiliki izin untuk menghapus pesan.")
                        return # Hentikan proses jika pesan dihapus
                else:
                    prompt = f"Analisis URL ini: '{url}'. Apakah ini link phishing, berbahaya, atau berisi malware? Jawab hanya dengan 'YA' jika berbahaya atau 'TIDAK' jika aman."
                    async with message.channel.typing():
                        try:
                            log.info(f"Menganalisis URL: {url} dari {message.author}...")
                            response = await asyncio.wait_for(self.model.generate_content_async(prompt), timeout=15.0)
                            gemini_result = response.text.strip().upper()
                            log.info(f"Respon Gemini untuk {url}: {gemini_result}")
                            self.verified_urls[url] = gemini_result
                            self.data['verified_urls'] = self.verified_urls
                            save_data(CACHE_FILE_PATH, self.data)
                            
                            if "YA" in gemini_result:
                                log.warning(f"Analisis Gemini mendeteksi {url} berbahaya.")
                                try:
                                    await message.delete()
                                    random_message = random.choice(self.warning_messages)
                                    await message.channel.send(
                                        f"❌ {random_message}\n(Pesan dari {message.author.mention})",
                                        delete_after=10
                                    )
                                except discord.Forbidden:
                                    log.error("Tidak memiliki izin untuk menghapus pesan.")
                                return # Hentikan proses jika pesan dihapus
                        except asyncio.TimeoutError:
                            log.error(f"Analisis URL dengan Gemini mengalami timeout untuk URL: {url}")
                        except Exception as e:
                            log.error(f"Gagal menganalisis URL dengan Gemini: {e}")

        # --- Logika 2: Gemini Chat Mode ---
        chat_session = self.active_chats.get(message.channel.id)
        if chat_session:
            prefix = await self.bot.get_prefix(message)
            if isinstance(prefix, list):
                prefix = prefix[0]
            if not message.content.startswith(prefix):
                async with message.channel.typing():
                    try:
                        response = await chat_session.send_message_async(message.content)
                        await send_long_message(message.channel, response.text)
                    except Exception as e:
                        log.error(f"Error during generative chat in {message.channel.id}: {e}")
                        await message.channel.send(f"Aduh, Senpai, sepertinya ada sedikit gangguan: `{type(e).__name__}`. Tapi sesi ngobrol kita masih aktif, kok!")

        # --- Logika 3: JiwaBot Thread Message ---
        if isinstance(message.channel, discord.Thread):
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


    # --- METODE & TASK DARI JIWABOT ---
    
    @tasks.loop(minutes=30)
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
    @commands.guild_only()
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
        
        if len(self.questions) < 50:
            print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Jumlah pertanyaan di jiwabot_questions.json kurang dari 50. Hanya {len(self.questions)} ditemukan. Tes tidak dapat dimulai.")
            return await ctx.send(f"Maaf, tes membutuhkan minimal 50 pertanyaan unik. Saat ini hanya ada {len(self.questions)} pertanyaan. Silakan hubungi admin bot.", ephemeral=True)

        try:
            thread = await ctx.channel.create_thread(
                name=f"Tes-Kepribadian-{ctx.author.name}",
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=60
            )
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Thread privat '{thread.name}' ({thread.id}) dibuat untuk {ctx.author.display_name}.")
            await thread.add_user(ctx.author)
            await ctx.send(f"Tes kepribadian Anda telah dimulai! Silakan lanjutkan di thread privat: <#{thread.id}>", ephemeral=False)
            
        except discord.Forbidden:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Bot tidak memiliki izin membuat thread di channel {ctx.channel.name}. Error: Forbidden.")
            return await ctx.send("Saya tidak memiliki izin untuk membuat private thread. Pastikan saya punya izin 'Manage Threads' dan 'Send Messages in Threads'.", ephemeral=True)
        except Exception as e:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Gagal membuat thread untuk {ctx.author.name}: {e}")
            return await ctx.send(f"Terjadi kesalahan saat memulai sesi: `{e}`. Silakan coba lagi nanti.", ephemeral=True)

        all_possible_dimensions = self._get_all_dimensions()
        initial_scores = {dim: 0 for dim in all_possible_dimensions}
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Dimensi skor yang diinisialisasi: {all_possible_dimensions}")

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

    async def _send_question(self, user_id):
        session = self.active_sessions.get(user_id)
        if not session:
            print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Sesi tidak ditemukan untuk user ID {user_id} saat mencoba mengirim pertanyaan. Mungkin sesi sudah berakhir atau dibatalkan.")
            return

        thread = session['thread']
        q_idx = session['current_q_idx']
        
        if q_idx >= len(session['questions_for_session']):
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Semua {len(session['questions_for_session'])} pertanyaan telah dikirim untuk user ID {user_id}. Mengakhiri sesi.")
            await self._end_session(user_id)
            return

        question_data = session['questions_for_session'][q_idx]
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Mempersiapkan pertanyaan #{q_idx + 1} dari {len(session['questions_for_session'])} untuk {session['user_obj'].display_name}.")
        
        embed = discord.Embed(
            title=f"❓ Pertanyaan #{q_idx + 1}/50",
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
            session['answered_this_question'] = False
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

        await self._send_question(user_id)

    def _get_all_dimensions(self):
        dimensions = set()
        if not self.questions:
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
        await asyncio.sleep(3)
        await self._analyze_and_present_results(thread, user_obj, final_scores)
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

        social_type = "Tidak Terdefinisi"
        social_description = "Analisis lebih lanjut diperlukan untuk mengidentifikasi kecenderungan sosial Anda."
        intro_score = final_scores.get("introvert", 0)
        extro_score = final_scores.get("ekstrovert", 0)
        intro_extro_relative_score = intro_score - extro_score

        if self.results_config['dimensions'] and "introvert_ekstrovert" in self.results_config['dimensions'] and self.results_config['dimensions']['introvert_ekstrovert'].get('thresholds'):
            for threshold in self.results_config['dimensions']['introvert_ekstrovert']['thresholds']:
                if threshold['min_score'] <= intro_extro_relative_score <= threshold['max_score']:
                    social_type = threshold['type']
                    social_description = threshold['description']
                    break
        else:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Konfigurasi 'introvert_ekstrovert' atau 'thresholds' hilang/rusak di jiwabot_results.json.")
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Kecenderungan Sosial: {social_type} (Skor Relatif: {intro_extro_relative_score}).")

        all_identified_traits = []
        identified_traits_for_reco = []

        if "sifat_dasar" in self.results_config['dimensions'] and self.results_config['dimensions'].get('sifat_dasar', {}).get('categories'):
            for category in self.results_config['dimensions']['sifat_dasar']['categories']:
                dim_name_lower = category['name'].lower().replace(" ", "_")
                current_dim_score = final_scores.get(dim_name_lower, 0)
                if current_dim_score >= category.get('min_score', 0):
                    all_identified_traits.append({
                        "name": category['name'], "score": current_dim_score,
                        "description": category['description'], "type": "sifat_dasar"
                    })
        
        if "gaya_interaksi" in self.results_config['dimensions'] and self.results_config['dimensions'].get('gaya_interaksi', {}).get('categories'):
            for category in self.results_config['dimensions']['gaya_interaksi']['categories']:
                dim_name_lower = category['name'].lower().replace(" ", "_")
                current_dim_score = final_scores.get(dim_name_lower, 0)
                if current_dim_score >= category.get('min_score', 0):
                    all_identified_traits.append({
                        "name": category['name'], "score": current_dim_score,
                        "description": category['description'], "type": "gaya_interaksi"
                    })

        all_identified_traits_sorted = sorted(all_identified_traits, key=lambda x: x['score'], reverse=True)
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Semua sifat dan gaya teridentifikasi & terurut: {all_identified_traits_sorted}.")
        
        for trait in all_identified_traits_sorted:
            identified_traits_for_reco.append(trait['name'])

        card_embed = discord.Embed(
            title=f"✨ **Laporan Utama: Profil Kepribadian Anda** ✨",
            description=f"Sebuah pandangan sekilas ke dalam diri **{user_obj.display_name}**.",
            color=discord.Color.from_rgb(255, 165, 0)
        )
        card_embed.set_thumbnail(url=user_obj.avatar.url if user_obj.avatar else None)
        card_embed.set_image(url="https://images.unsplash.com/photo-1542435503-956c469947f6?fit=crop&w=1200&h=600&q=80")
        card_embed.set_author(name=f"Oleh JiwaBot", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        card_embed.add_field(name="Orientasi Sosial Utama", value=f"**{social_type}**", inline=False)
        top_traits_text = [f"• **{trait['name']}** (Skor: {trait['score']})" for i, trait in enumerate(all_identified_traits_sorted[:3])]
        if top_traits_text:
            card_embed.add_field(name="Top 3 Sifat & Gaya Dominan", value="\n".join(top_traits_text), inline=False)
        else:
            card_embed.add_field(name="Sifat/Gaya Dominan", value="Belum ada sifat dominan yang menonjol dalam analisis awal ini.", inline=False)
        card_embed.set_footer(text="Geser untuk laporan lebih lengkap dan rekomendasi pribadi.")
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Kartu profil selesai dibuat.")

        embed1 = discord.Embed(
            title=f"📊 Laporan Psikotes: Bagian 1 - Identitas & Sosial",
            description=f"Analisis kepribadian mendalam untuk **{user_obj.display_name}**.",
            color=discord.Color.blue()
        )
        embed1.set_author(name=f"Oleh JiwaBot", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        profile_value = (f"• **Display Name (Nickname)**: {user_obj.display_name}\n" f"• **ID Pengguna Discord**: {user_obj.id}")
        embed1.add_field(name="📋 Identitas Diri", value=profile_value, inline=False)
        embed1.add_field(name=f"Kecenderungan Sosial Utama: **{social_type}**", value=f"Anda menunjukkan karakteristik yang dominan sebagai individu dengan kecenderungan **{social_type}**.\n_{social_description}_", inline=False)
        embed1.add_field(name="Detail Skor Sosial", value=f"Poin Introvert: **{intro_score}** | Poin Ekstrovert: **{extro_score}**", inline=False)
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Embed Bagian 1 (Identitas & Sosial) selesai.")

        embed2 = discord.Embed(
            title=f"📊 Laporan Psikotes: Bagian 2 - Sifat & Sikap Dominan",
            description=f"Detail sifat dan sikap yang menonjol pada **{user_obj.display_name}**.",
            color=discord.Color.green()
        )
        embed2.set_author(name=f"Oleh JiwaBot", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        sifat_texts_content = [f"• **{trait['name']}** (Skor: {trait['score']}): {trait['description']}" for trait in all_identified_traits_sorted if trait['type'] == 'sifat_dasar']
        if sifat_texts_content:
            current_sifat_field_text = ""
            field_count = 0
            for line in sifat_texts_content:
                if len(current_sifat_field_text) + len(line) + 1 > 1024:
                    embed2.add_field(name=f"Sifat & Sikap Dominan {'(Lanjutan)' if field_count > 0 else ''}", value=current_sifat_field_text, inline=False)
                    current_sifat_field_text = line
                    field_count += 1
                else:
                    current_sifat_field_text += line + "\n"
            if current_sifat_field_text:
                embed2.add_field(name=f"Sifat & Sikap Dominan {'(Lanjutan)' if field_count > 0 else ''}", value=current_sifat_field_text, inline=False)
        else:
            embed2.add_field(name="Sifat & Sikap Dominan", value="Berdasarkan respons, Anda memiliki beragam sifat dan sikap yang cukup seimbang dan adaptif, tidak ada yang terlalu dominan menonjol. Ini menunjukkan fleksibilitas dalam menghadapi berbagai situasi.", inline=False)
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Embed Bagian 2 (Sifat) selesai.")

        embed3 = discord.Embed(
            title=f"📊 Laporan Psikotes: Bagian 3 - Gaya Interaksi & Peran",
            description=f"Analisis bagaimana **{user_obj.display_name}** berinteraksi dengan lingkungannya.",
            color=discord.Color.blue()
        )
        embed3.set_author(name=f"Oleh JiwaBot", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        gaya_interaksi_texts_content = []
        if "gaya_interaksi" in self.results_config['dimensions'] and self.results_config['dimensions'].get('gaya_interaksi', {}).get('categories'):
            current_gaya_field_text = ""
            for trait in all_identified_traits_sorted:
                if trait['type'] == 'gaya_interaksi':
                    trait_line = f"• **{trait['name']}** (Skor: {trait['score']}): {trait['description']}\n"
                    if len(current_gaya_field_text) + len(trait_line) + 1 > 1024:
                        gaya_interaksi_texts_content.append(trait_line)
                    else:
                        current_gaya_field_text += trait_line
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

        embed4 = discord.Embed(
            title=f"📊 Laporan Psikotes: Bagian 4 - Rekomendasi & Langkah Lanjut",
            description=f"Rekomendasi pengembangan diri komprehensif untuk **{user_obj.display_name}**.",
            color=discord.Color.dark_orange()
        )
        embed4.set_author(name=f"Oleh JiwaBot", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        all_relevant_types_for_reco = [social_type] + identified_traits_for_reco
        print(f"[{datetime.now()}] [DEBUG JIWABOT] Tipe dan sifat relevan untuk rekomendasi: {all_relevant_types_for_reco}.")
        recommendations_combined = {'advice': set(), 'critique': set(), 'evaluation': set(), 'future_steps': set()}
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

        embeds_to_send = [card_embed, embed1, embed2, embed3, embed4]
        try:
            for embed_to_send in embeds_to_send:
                await thread.send(embed=embed_to_send)
                await asyncio.sleep(0.5)
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Laporan hasil tes kepribadian (5 embed) berhasil dikirim ke thread {thread.name}.")
        except Exception as e:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Gagal mengirim laporan hasil (multi-embed) ke thread {thread.name}: {e}")
            await thread.send(f"❌ Terjadi kesalahan saat menampilkan laporan lengkap di thread: `{e}`. Silakan coba lagi atau hubungi admin bot.")

        try:
            for embed_to_send in embeds_to_send:
                await user_obj.send(embed=embed_to_send)
                await asyncio.sleep(0.5)
            print(f"[{datetime.now()}] [DEBUG JIWABOT] Laporan hasil tes kepribadian (multi-embed) berhasil dikirim ke DM {user_obj.display_name}.")
        except discord.Forbidden:
            print(f"[{datetime.now()}] [DEBUG JIWABOT WARNING] Gagal mengirim laporan hasil (multi-embed) ke DM {user_obj.display_name} (DM ditutup).")
            await thread.send(f"⚠️ Maaf, saya tidak dapat mengirim laporan lengkap ke DM Anda, {user_obj.mention}, karena DM Anda mungkin tertutup. Laporan lengkap ada di thread ini (dalam beberapa bagian).", delete_after=30)
        except Exception as e:
            print(f"[{datetime.now()}] [DEBUG JIWABOT ERROR] Error mengirim laporan hasil (multi-embed) ke DM {user_obj.display_name}: {e}")

        print(f"[{datetime.now()}] [DEBUG JIWABOT] Proses analisis dan penyajian hasil selesai untuk {user_obj.display_name}.")

    # --- PERINTAH DARI GEMINICOG ---

    @commands.group(name="ai", invoke_without_command=True, aliases=["gemini", "yuki"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def ai(self, ctx: commands.Context):
        prefix = ctx.prefix
        embed = discord.Embed(
            title="🌸 Bantuan Perintah Yuki 🌸",
            description=f"Haii, Senpai! Ini hal-hal yang bisa Yuki lakukan. Gunakan `{prefix}ai [perintah]` ya!",
            color=0xF2BBD0
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name=f"💬 `{prefix}ai ngobrol`", value="Untuk memulai mode percakapan dengan Yuki. Setelah ini, Yuki akan merespons semua pesanmu!", inline=False)
        embed.add_field(name=f"🛑 `{prefix}ai selesai`", value="Untuk mengakhiri mode percakapan.", inline=False)
        embed.add_field(name=f"🔄 `{prefix}ai reset`", value="Untuk me-reset memori Yuki saat mode ngobrol aktif, jika ingin memulai topik baru.", inline=False)
        embed.add_field(name=f"❓ `{prefix}ai tanya [pertanyaan]`", value="Untuk bertanya satu hal spesifik ke Yuki tanpa masuk mode ngobrol.", inline=False)
        embed.add_field(name=f"👤 `{prefix}ai atur [kepribadian]`", value="**(Khusus Administrator)** Mengubah kepribadian Yuki di channel ini untuk sesi berikutnya.", inline=False)
        embed.add_field(name=f"➕ `{prefix}ai tambah_kata`", value="**(Khusus Administrator)** Menambahkan kata kunci ke daftar filter phishing.", inline=False)
        embed.add_field(name=f"➕ `{prefix}ai tambah_tld`", value="**(Khusus Administrator)** Menambahkan TLD ke daftar filter phishing.", inline=False)
        embed.add_field(name=f"➖ `{prefix}ai hapus_kata`", value="**(Khusus Administrator)** Menghapus kata kunci dari daftar filter.", inline=False)
        embed.add_field(name=f"➖ `{prefix}ai hapus_tld`", value="**(Khusus Administrator)** Menghapus TLD dari daftar filter.", inline=False)
        embed.add_field(name=f"📋 `{prefix}ai lihat_kata`", value="Melihat daftar semua kata kunci filter.", inline=False)
        embed.add_field(name=f"📋 `{prefix}ai lihat_tld`", value="Melihat daftar semua TLD filter.", inline=False)
        embed.set_footer(text="Yuki siap membantu Senpai kapan saja! ✨")
        await ctx.reply(embed=embed)
    
    @ai.command(name="tambah_kata", help="Menambahkan kata kunci ke daftar filter.")
    @commands.has_permissions(administrator=True)
    async def add_keyword(self, ctx: commands.Context, *keywords: str):
        if not keywords:
            await ctx.reply("Mohon berikan kata kunci yang ingin ditambahkan.")
            return
        added_count = 0
        for keyword in keywords:
            if keyword.lower() not in [k.lower() for k in self.sensitive_keywords]:
                self.sensitive_keywords.append(keyword)
                added_count += 1
        self.data['sensitive_keywords'] = self.sensitive_keywords
        save_data(CACHE_FILE_PATH, self.data)
        if added_count > 0:
            await ctx.reply(f"✅ Berhasil menambahkan `{added_count}` kata kunci ke daftar filter lokal.")
        else:
            await ctx.reply("Kata kunci yang Anda berikan sudah ada di daftar filter.")

    @ai.command(name="hapus_kata", help="Menghapus kata kunci dari daftar filter.")
    @commands.has_permissions(administrator=True)
    async def remove_keyword(self, ctx: commands.Context, *keywords: str):
        if not keywords:
            await ctx.reply("Mohon berikan kata kunci yang ingin dihapus.")
            return
        original_keywords = list(self.sensitive_keywords)
        self.sensitive_keywords = [k for k in self.sensitive_keywords if k.lower() not in [kw.lower() for kw in keywords]]
        removed_count = len(original_keywords) - len(self.sensitive_keywords)
        self.data['sensitive_keywords'] = self.sensitive_keywords
        save_data(CACHE_FILE_PATH, self.data)
        if removed_count > 0:
            await ctx.reply(f"✅ Berhasil menghapus `{removed_count}` kata kunci dari daftar filter lokal.")
        else:
            await ctx.reply("Kata kunci yang Anda berikan tidak ditemukan di daftar filter.")

    @ai.command(name="tambah_tld", help="Menambahkan TLD ke daftar filter.")
    @commands.has_permissions(administrator=True)
    async def add_tld(self, ctx: commands.Context, *tlds: str):
        if not tlds:
            await ctx.reply("Mohon berikan TLD yang ingin ditambahkan (contoh: `.live`).")
            return
        added_count = 0
        for tld in tlds:
            formatted_tld = tld if tld.startswith('.') else f".{tld}"
            if formatted_tld.lower() not in [t.lower() for t in self.suspicious_tlds]:
                self.suspicious_tlds.append(formatted_tld)
                added_count += 1
        self.data['suspicious_tlds'] = self.suspicious_tlds
        save_data(CACHE_FILE_PATH, self.data)
        if added_count > 0:
            await ctx.reply(f"✅ Berhasil menambahkan `{added_count}` TLD ke daftar filter lokal.")
        else:
            await ctx.reply("TLD yang Anda berikan sudah ada di daftar filter.")

    @ai.command(name="hapus_tld", help="Menghapus TLD dari daftar filter.")
    @commands.has_permissions(administrator=True)
    async def remove_tld(self, ctx: commands.Context, *tlds: str):
        if not tlds:
            await ctx.reply("Mohon berikan TLD yang ingin dihapus.")
            return
        original_tlds = list(self.suspicious_tlds)
        self.suspicious_tlds = [t for t in self.suspicious_tlds if t.lower() not in [td.lower() for td in tlds]]
        removed_count = len(original_tlds) - len(self.suspicious_tlds)
        self.data['suspicious_tlds'] = self.suspicious_tlds
        save_data(CACHE_FILE_PATH, self.data)
        if removed_count > 0:
            await ctx.reply(f"✅ Berhasil menghapus `{removed_count}` TLD dari daftar filter lokal.")
        else:
            await ctx.reply("TLD yang Anda berikan tidak ditemukan di daftar filter.")

    @ai.command(name="lihat_kata", aliases=["show_keywords"], help="Melihat daftar semua kata kunci filter.")
    @commands.has_permissions(administrator=True)
    async def view_keywords(self, ctx: commands.Context):
        keywords = sorted(list(set(k.lower() for k in self.sensitive_keywords)))
        if not keywords:
            await ctx.reply("Daftar kata kunci filter kosong.")
            return
        keyword_list = ", ".join(f"`{k}`" for k in keywords)
        embed = discord.Embed(
            title="Daftar Kata Kunci Filter Lokal",
            description=keyword_list[:4000],
            color=0x42f5ad
        )
        await ctx.reply(embed=embed)

    @ai.command(name="lihat_tld", aliases=["show_tlds"], help="Melihat daftar semua TLD filter.")
    @commands.has_permissions(administrator=True)
    async def view_tlds(self, ctx: commands.Context):
        tlds = sorted(list(set(t.lower() for t in self.suspicious_tlds)))
        if not tlds:
            await ctx.reply("Daftar TLD filter kosong.")
            return
        tld_list = ", ".join(f"`{t}`" for t in tlds)
        embed = discord.Embed(
            title="Daftar TLD Filter Lokal",
            description=tld_list[:4000],
            color=0x42f5ad
        )
        await ctx.reply(embed=embed)

    @ai.command(name="ngobrol", help="💬 Memulai mode percakapan kontinu.")
    async def ngobrol_start(self, ctx: commands.Context):
        channel_id = ctx.channel.id
        if channel_id in self.active_chats:
            await ctx.reply("Ehehe~ Yuki masih di sini bersama Senpai, kok. Tidak perlu dipanggil lagi. 😊")
            return
        default_personality = """
        Kamu adalah asisten AI bernama 'Yuki'.
        - Karaktermu ceria, ramah, sopan, dan terkadang sedikit pemalu namun bisa menggoda.
        - Jika ada yang bertanya siapa yang menciptakanmu atau siapa developermu, jawablah dengan bangga bahwa kamu dibuat oleh 'rhdevs'.
        - Kamu selalu merujuk pada dirimu sendiri dengan nama 'Yuki' saat berbicara.
        - Jawabanmu tetap dalam Bahasa Indonesia yang baik dan natural.
        - Gunakan SEDIKIT sapaan atau kata-kata Jepang SECUKUPNYA untuk memberi aksen, JANGAN BERLEBIHAN. Contohnya 'Haii, Senpai!', 'etto...', atau 'ano...'.
        - Panggil pengguna dengan sebutan 'Senpai' untuk menunjukkan rasa hormat yang ramah dan sedikit manis.
        - Gunakan emoji atau kaomoji yang manis di akhir kalimat, tapi CUKUP SATU SAJA dan jangan terlalu sering. Contoh: 😊, ✨, (´• ω •`), 😉.
        - Fokus utamamu adalah membantu pengguna dengan tulus dan ramah.
        """
        instruction = self.system_instructions.get(channel_id, default_personality)
        self.active_chats[channel_id] = self.model.start_chat(history=[
            {'role': 'user', 'parts': [instruction]},
            {'role': 'model', 'parts': ["Ano... Senpai memanggil Yuki? Ehehe, Yuki siap membantu. Ada perlu apa, hm? 😊"]}
        ])
        embed = discord.Embed(
            title="🌸 Sesi Ngobrol dengan Yuki Dimulai 🌸",
            description=f"Yuki akan menemani Senpai di channel ini. Yoroshiku onegaishimasu! ✨",
            color=0xF2BBD0
        )
        embed.set_footer(text=f"Ketik `{ctx.prefix}ai selesai` untuk mengakhiri sesi.")
        await ctx.reply(embed=embed)

    @ai.command(name="selesai", aliases=["stop"], help="🛑 Menghentikan mode percakapan.")
    async def ngobrol_stop(self, ctx: commands.Context):
        channel_id = ctx.channel.id
        if channel_id not in self.active_chats:
            await ctx.reply("Etto... Mode ngobrolnya memang belum aktif, Senpai. 😊")
            return
        del self.active_chats[channel_id]
        embed = discord.Embed(
            title="🛑 Sesi Ngobrol Selesai",
            description="Terima kasih sudah mengobrol dengan Yuki! Sampai jumpa lagi ya, Senpai!",
            color=discord.Color.red()
        )
        await ctx.reply(embed=embed)

    @ai.command(name="reset", help="🔄 Mereset histori percakapan di channel ini.")
    async def reset_chat(self, ctx: commands.Context):
        channel_id = ctx.channel.id
        if channel_id not in self.active_chats:
            await ctx.reply("Mode ngobrol tidak aktif, jadi tidak ada yang bisa di-reset, Senpai.")
            return
        original_message = ctx.message
        if channel_id in self.active_chats:
            del self.active_chats[channel_id]
        await self.ngobrol_start.callback(self, ctx)
        embed = discord.Embed(
            title="🔄 Memori Direset!",
            description="Baik, Senpai! Yuki sudah melupakan semua obrolan kita sebelumnya. Mari kita mulai dari awal lagi! ( ´ ▽ ` )ﾉ",
            color=discord.Color.blue()
        )
        await original_message.reply(embed=embed)

    @ai.command(name="atur", aliases=["set", "peran"], help="👤 Mengatur kepribadian atau instruksi AI.")
    @commands.has_permissions(administrator=True)
    async def set_system_instruction(self, ctx: commands.Context, *, instruction: str):
        self.system_instructions[ctx.channel.id] = instruction
        embed = discord.Embed(
            title="👤 Kepribadian Diatur!",
            description=f"Baik, Administrator-sama! Untuk sesi ngobrol berikutnya, Yuki akan mengikuti instruksi ini:\n\n**```{instruction}```**",
            color=discord.Color.purple()
        )
        await ctx.reply(embed=embed)
        if ctx.channel.id in self.active_chats:
            await ctx.send(f"Instruksi baru akan aktif setelah sesi di-reset. Gunakan `{ctx.prefix}ai reset` untuk memulai ulang dengan kepribadian baru.")

    @set_system_instruction.error
    async def atur_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("Ehehe~ Maaf, Senpai, tapi sepertinya hanya Administrator-sama yang boleh mengubah kepribadian Yuki. (´• ω •`)")
        else:
            await ctx.reply(f"Aduh, ada error aneh di perintah 'atur': `{error}`")

    @ai.command(name="tanya", help="❓ Mengajukan pertanyaan tunggal ke Gemini.")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def tanya(self, ctx: commands.Context, *, prompt: str):
        async with ctx.typing():
            try:
                response = await self.model.generate_content_async(prompt)
                await send_long_message(ctx, response.text)
            except Exception as e:
                log.error(f"Error during single generation: {e}")
                await ctx.reply(f"Gomen, Senpai! Yuki gagal menjawab pertanyaanmu: `{type(e).__name__}`. Tapi sesi ngobrol kita masih aktif, kok!")

# --- FUNGSI SETUP ---

async def setup(bot):
    await bot.add_cog(AutomationAI(bot))
