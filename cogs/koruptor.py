import discord
from discord.ext import commands, tasks
import json
import random
import asyncio
import os
from datetime import datetime, time, timedelta
import logging 
import sys 
from collections import Counter

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__) # Dapatkan instance logger untuk cog ini

# --- KONFIGURASI FILE DATA ---
DATA_DIR = "data"
LEVEL_DATA_FILE = os.path.join(DATA_DIR, "level_data.json")
BANK_FILE = os.path.join(DATA_DIR, "bank_data.json")
ECONOMY_CONFIG_FILE = os.path.join(DATA_DIR, "economy_config.json")
PROJECT_FILE = os.path.join(DATA_DIR, "active_projects.json")
TRIVIA_QUESTIONS_FILE = os.path.join(DATA_DIR, "government_trivia.json")
NGAWUR_PROJECTS_FILE = os.path.join(DATA_DIR, "ngawur_projects.json")
JAIL_HELP_FILE = os.path.join(DATA_DIR, "jail_help_requests.json") 


# --- KONFIGURASI ROLE DAN CHANNEL ---
EVENT_CHANNEL_ID = 765140300145360896 # ID Channel Event (Ganti dengan ID channel event Anda)

JAIL_ROLE_ID = 1392292683552260198 # ID Role Tahanan (Ganti dengan ID role Tahanan Anda)
OFFICIAL_ROLE_ID = 1255468095217078272 # ID Role Pejabat (Ganti dengan ID role Pejabat Anda)

# --- KONFIGURASI EVENT KEUANGAN ---
HEIST_COST = 500
LOOT_MIN = 800
LOOT_MAX = 1700
RESPONSE_TIME_SECONDS = 45
JAIL_DURATION_HOURS = 2
BUREAUCRACY_CHANCE = 0.25

PROJECT_CONTRIBUTION_COST = 700
MYSTERIOUS_AID_MIN = 500
MYSTERIOUS_AID_MAX = 2000

# --- KONFIGURASI KUIS ---
QUIZ_REWARD_MIN = 25
QUIZ_REWARD_MAX = 100
QUIZ_PENALTY = 25
QUIZ_QUESTION_TIME = 30 # Waktu per pertanyaan dalam detik
QUIZ_TOTAL_QUESTIONS = 10 # Jumlah pertanyaan per sesi kuis
CORRUPTION_CHANCE_HIGH_REWARD = 0.30 # 30% peluang korupsi jika hadiah > 80 RSWN

# --- KONFIGURASI PUNGUTAN POLISI DAN SOGOKAN ---
POLICE_BRIBE_COST_MIN = 0
POLICE_BRIBE_COST_MAX = 100
CORRUPTION_CHARGE_COST_MIN = 250
CORRUPTION_CHARGE_COST_MAX = 500


# --- FUNGSI UTILITAS UNTUK LOAD/SAVE JSON ---
def ensure_data_files():
    """Memastikan folder data ada dan file JSON dasar terinisialisasi."""
    os.makedirs(DATA_DIR, exist_ok=True)
    for file_path in [LEVEL_DATA_FILE, BANK_FILE, ECONOMY_CONFIG_FILE, PROJECT_FILE, TRIVIA_QUESTIONS_FILE, NGAWUR_PROJECTS_FILE, JAIL_HELP_FILE]: # Tambah JAIL_HELP_FILE
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                if file_path == ECONOMY_CONFIG_FILE:
                    json.dump({"global_tax_percentage": 0, "server_funds_balance": 0, "last_tax_run": None}, f, indent=4)
                elif file_path == PROJECT_FILE:
                    json.dump({}, f, indent=4)
                elif file_path == TRIVIA_QUESTIONS_FILE:
                    json.dump({"questions": []}, f, indent=4)
                elif file_path == NGAWUR_PROJECTS_FILE:
                    json.dump({"projects": []}, f, indent=4)
                elif file_path == JAIL_HELP_FILE: # Inisialisasi file permintaan bantuan penjara
                    json.dump({}, f, indent=4)
                else:
                    json.dump({}, f, indent=4)
    log.info(f"Memastikan folder '{DATA_DIR}' dan file data exist.")

def load_level_data(guild_id: str):
    ensure_data_files()
    try:
        with open(LEVEL_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            log.debug(f"Level data loaded for guild {guild_id}.")
            return data.get(guild_id, {})
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log.warning(f"Failed to load level data for guild {guild_id}: {e}. Returning empty dict.")
        return {}

def save_level_data(guild_id: str, data: dict):
    ensure_data_files()
    try:
        with open(LEVEL_DATA_FILE, "r", encoding="utf-8") as f:
            all_data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        all_data = {}
    all_data[guild_id] = data
    with open(LEVEL_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=4)
    log.debug(f"Level data saved for guild {guild_id}.")

def load_bank_data():
    ensure_data_files()
    try:
        with open(BANK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            log.debug("Bank data loaded.")
            return data
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log.warning(f"Failed to load bank data: {e}. Returning empty dict.")
        return {}

def save_bank_data(data):
    ensure_data_files()
    with open(BANK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    log.debug("Bank data saved.")

def load_economy_config():
    ensure_data_files()
    try:
        with open(ECONOMY_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            log.debug("Economy config loaded.")
            return data
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log.warning(f"Failed to load economy config: {e}. Returning default config.")
        return {"global_tax_percentage": 0, "server_funds_balance": 0, "last_tax_run": None}

def save_economy_config(data):
    ensure_data_files()
    with open(ECONOMY_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    log.debug("Economy config saved.")

def load_project_data():
    ensure_data_files()
    try:
        with open(PROJECT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            log.debug("Project data loaded.")
            return data
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log.warning(f"Failed to load project data: {e}. Returning empty dict.")
        return {}

def save_project_data(data):
    ensure_data_files()
    with open(PROJECT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    log.debug("Project data saved.")

def load_trivia_questions():
    ensure_data_files()
    try:
        with open(TRIVIA_QUESTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            log.debug("Trivia questions loaded.")
            return data
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log.warning(f"Failed to load trivia questions: {e}. Returning empty list.")
        return {"questions": []}

def save_trivia_questions(data):
    ensure_data_files()
    with open(TRIVIA_QUESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    log.debug("Trivia questions saved.")

def load_ngawur_projects_data(): # Fungsi baru untuk memuat proyek ngawur
    ensure_data_files()
    try:
        with open(NGAWUR_PROJECTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            log.debug("Ngawur projects data loaded.")
            return data
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log.warning(f"Failed to load ngawur projects data: {e}. Returning empty list.")
        return {"projects": []}

def load_jail_help_requests():
    ensure_data_files()
    try:
        with open(JAIL_HELP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            log.debug("Jail help requests loaded.")
            return data
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log.warning(f"Failed to load jail help requests: {e}. Returning empty dict.")
        return {}

def save_jail_help_requests(data):
    ensure_data_files()
    with open(JAIL_HELP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    log.debug("Jail help requests saved.")


class EconomyEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_heists = {}
        self.active_fires = {}
        self.active_projects = load_project_data()
        self.active_quizzes = {}
        self.jail_help_requests = load_jail_help_requests() # Muat permintaan bantuan penjara
        self.active_investigations = {} # {guild_id: {'reporter_id': id, 'suspect_id': id, 'bribe_cost': int, 'message_id': id, 'status': 'pending'}}

        # --- Konfigurasi Pajak ---
        self.funny_tax_insults = [
            "Hmmph! Lihat ini! Dompetmu kosong melompong seperti janji kampanye! Mau bayar pakai daun kering? Pajakmu nihil karena saldo juga nihil! Kau sungguh menyedihkan! Cepat cari uang sana, jangan cuma jadi beban negara! Kami para pejabat butuh uang untuk pembangunan 'proyek pribadi'! Cih! 😤",
            "Dasar rakyat miskin! Saldo nol rupiah masih berani hidup?! Kami para pejabat pusing melihatmu! Ini bukan negara gratisan! Cepat cari pekerjaan, jangan bisanya cuma rebahan! Gih sana, bantu pembangunan negara dengan uangmu! Kalau ada. *uhuk* 🙄",
            "Ya ampun, kasihan sekali! Saldomu bahkan tidak cukup untuk beli permen karet! Karena Anda tidak punya uang, Anda kami bebaskan pajak kali ini, tapi jangan sampai ketahuan lagi ya! Nanti kami bisa dimarahi Bos Besar! *pura-pura marah*",
            "Sungguh memprihatinkan! Pajakmu sebesar 0 RSWN karena hartamu juga 0! Kami hampir lupa kalau ada rakyat sepertimu. Coba lebih semangat lagi, jangan sampai masuk berita 'kemiskinan abadi' di koran pejabat!",
            "Halo, rakyat! Ini dari pemerintah. Kami mau ambil pajakmu, tapi... *ngintip dompetmu* ...oh, tidak jadi deh! Tidak ada apa-apa! Kami doakan semoga rezekimu melimpah biar tahun depan kami bisa ambil banyak! Amin! 🙏",
            "Pejabat PajakBot: 'Waduh! Aku kira ada hama di dompetmu, ternyata kosong melompong! Jadi, pajakmu untuk hari ini NOL! Tapi jangan senang dulu, kami akan terus memantau sampai kamu punya banyak uang. Selamat berjuang, rakyat jelata! *tertawa licik*'",
        ]
        
        # --- Konfigurasi Penjara ---
        self.funny_jail_nicknames_part = [
            "Kopi", "Malam", "Tidur", "Jomblo", "Nganggur", "Bucin", "Santuy",
            "BarBar", "Donat", "Telat", "Gaming", "Rebahan", "Magabut", "Gabut",
            "Gorengan", "Mager", "Wibu", "Kpop", "Drakor", "Gacha", "Halu"
        ]

        # --- Konfigurasi Hinaan Khusus ---
        self.special_insults = [
            "Wahai **{user_mention}**, kami para pejabat sudah berminggu-minggu berdebat! Akhirnya kami sepakat bahwa Anda adalah definisi sempurna dari 'hidup tanpa arah'. Selamat!",
            "Halo, **{user_mention}**! Berdasarkan pengamatan ketat tim intelijen kami, aura kemiskinan Anda semakin hari semakin bersinar. Luar biasa!",
            "Untuk **{user_mention}**: Pemerintah telah mengadakan survey, dan hasilnya Anda adalah salah satu dari 0.0001% penduduk yang paling 'tidak berguna' secara ekonomi. Selamat atas pencapaiannya!",
            "Pejabat PajakBot: '**{user_mention}**, kamu itu seperti sinyal Wi-Fi di pelosok, ada tapi tidak berfungsi! Tolong perbaiki dirimu!'",
            "Pemberitahuan khusus untuk **{user_mention}**: Otak Anda sepertinya sudah di-format ulang oleh virus 'kemalasan'. Segera lakukan instalasi ulang otak baru di bengkel terdekat!"
        ]

        # --- Konfigurasi Proyek Ngawur ---
        self.project_update_duration_hours = 6
        self.project_fail_duration_hours = 24
        self.last_project_check = datetime.utcnow()

        # --- Mulai Background Tasks ---
        self.auto_tax_task.start()
        self.jail_check_task.start()
        self.heist_fire_event_scheduler.start()
        self.project_scheduler.start()

    # Pastikan untuk menghentikan task saat cog di-unload
    def cog_unload(self):
        log.info("Unloading EconomyEvents cog. Cancelling all tasks.")
        self.auto_tax_task.cancel()
        self.jail_check_task.cancel()
        self.heist_fire_event_scheduler.cancel()
        self.project_scheduler.cancel()
        
    # --- Helper untuk Pengecekan User di Penjara ---
    async def _is_user_jailed(self, member_id, guild_id):
        data = load_level_data(str(guild_id))
        user_data = data.get(str(member_id), {})
        if "jailed_until" in user_data and user_data["jailed_until"]:
            jailed_until_dt = datetime.fromisoformat(user_data["jailed_until"])
            if datetime.utcnow() < jailed_until_dt:
                log.debug(f"User {member_id} is jailed until {jailed_until_dt}.")
                return True, jailed_until_dt
        return False, None

    # --- Helper untuk Menambahkan User ke Penjara ---
    async def _jail_user(self, member: discord.Member, duration_hours: int = JAIL_DURATION_HOURS):
        log.info(f"Jailing user {member.display_name} for {duration_hours} hours.")
        guild_id = str(member.guild.id)
        user_id = str(member.id)
        data = load_level_data(guild_id)
        user_data = data.setdefault(user_id, {})

        jail_role = member.guild.get_role(JAIL_ROLE_ID)
        if not jail_role:
            log.error(f"Role 'Tahanan' (ID: {JAIL_ROLE_ID}) not found in guild {member.guild.name}.")
            try: await member.send(f"⚠️ Role 'Tahanan' tidak ditemukan di server {member.guild.name}! Hubungi admin untuk mengaturnya agar sanksi penjara bisa berfungsi.")
            except discord.Forbidden: pass
            return

        user_data["original_nickname"] = member.nick if member.nick else member.name
        
        funny_part = random.choice(self.funny_jail_nicknames_part)
        try:
            new_nickname = f"Tahanan {funny_part} {user_data['original_nickname']}"
            if len(new_nickname) > 32:
                new_nickname = f"Tahanan {funny_part} {user_data['original_nickname'][:(32 - len(f'Tahanan {funny_part} '))]}"
            await member.edit(nick=new_nickname)
            log.info(f"Changed nickname of {member.display_name} to {new_nickname}.")
        except discord.HTTPException as e:
            log.error(f"Failed to change nickname of {member.display_name}: {e}")
            try: await member.send(f"⚠️ Gagal mengubah nickname Anda karena izin. Silakan hubungi admin.")
            except discord.Forbidden: pass

        try:
            await member.add_roles(jail_role)
            log.info(f"Added Tahanan role to {member.display_name}.")
        except discord.HTTPException as e:
            log.error(f"Failed to add Tahanan role to {member.display_name}: {e}")
            try: await member.send(f"⚠️ Gagal menambahkan role Tahanan. Silakan hubungi admin.")
            except discord.Forbidden: pass

        release_time = datetime.utcnow() + timedelta(hours=duration_hours)
        message_cooldown_end = datetime.utcnow() + timedelta(hours=duration_hours)

        user_data["jailed_until"] = release_time.isoformat()
        user_data["message_cooldown_end"] = message_cooldown_end.isoformat()
        
        save_level_data(guild_id, data)
        log.debug(f"Saved jail status for {member.display_name}.")
        try:
            await member.send(
                f"🚨 **ANDA DITANGKAP!** Anda dijebloskan ke penjara virtual selama **{duration_hours} jam**!\n"
                f"Nickname Anda sekarang: **{member.display_name}**.\n"
                f"Selama di penjara, Anda hanya bisa mengirim pesan **1 menit sekali** dan tidak bisa menggunakan command ekonomi/game lainnya."
            )
        except discord.Forbidden:
            log.warning(f"Could not send jail DM to {member.display_name} (DMs closed).")

    # --- Helper untuk Membebaskan User dari Penjara ---
    async def _release_user(self, member: discord.Member):
        log.info(f"Releasing user {member.display_name} from jail.")
        guild_id_str = str(member.guild.id)
        user_id_str = str(member.id)
        data = load_level_data(guild_id_str)
        user_data = data.get(user_id_str, {})

        jail_role = member.guild.get_role(JAIL_ROLE_ID)
        if jail_role and jail_role in member.roles:
            try: await member.remove_roles(jail_role)
            except discord.HTTPException as e: log.error(f"Error removing jail role for {member.display_name}: {e}")

        if "original_nickname" in user_data and member.display_name.startswith("Tahanan"):
            try:
                await member.edit(nick=user_data["original_nickname"])
            except discord.HTTPException as e: log.error(f"Error restoring nickname for {member.display_name}: {e}")
        
        # Hapus data penjara dari user_data
        user_data.pop("jailed_until", None)
        user_data.pop("original_nickname", None)
        user_data.pop("message_cooldown_end", None)
        data[user_id_str] = user_data # Update data di dictionary utama
        
        save_level_data(guild_id_str, data)
        log.debug(f"Jail status cleared for {member.display_name}.")
        try: await member.send("🎉 **BEBAS!** Masa penjaramu sudah berakhir! Kamu bebas lagi menjelajahi server ini!")
        except discord.Forbidden: log.warning(f"Could not send freedom DM to {member.display_name} (DMs closed).")

    # --- Background Task untuk Pemungutan Pajak Otomatis ---
    @tasks.loop(hours=24)
    async def auto_tax_task(self):
        log.info("Auto tax task started.")
        await self.bot.wait_until_ready()
        
        config = load_economy_config()
        last_tax_run_str = config.get("last_tax_run")
        last_tax_run = datetime.fromisoformat(last_tax_run_str) if last_tax_run_str else datetime.min
        
        # Jeda minimal 23.5 jam sebelum jalankan lagi untuk menghindari double run di waktu yang sama (jika bot restart)
        if (datetime.utcnow() - last_tax_run).total_seconds() < 23.5 * 3600: 
            log.info("Auto tax task skipped: Not yet time to run.")
            return
        
        config["last_tax_run"] = datetime.utcnow().isoformat()
        save_economy_config(config)
        log.info(f"Auto tax task running. Last run updated to {config['last_tax_run']}.")
        
        tax_percentage = config.get("global_tax_percentage", 0)
        server_funds = config.get("server_funds_balance", 0)

        bank_data = load_bank_data()
        
        for guild in self.bot.guilds:
            log.debug(f"Processing tax for guild: {guild.name} ({guild.id})")
            for member in guild.members:
                if member.bot: continue

                user_id = str(member.id)
                user_balance = bank_data.get(user_id, {}).get("balance", 0)
                
                tax_amount = int(user_balance * (tax_percentage / 100))
                
                # Pastikan minimal pajak adalah 1 jika persentase > 0 dan saldo > 0, tapi hasil hitungan kurang dari 1
                if tax_percentage > 0 and user_balance > 0 and tax_amount < 1:
                    tax_amount = 1
                
                if user_balance > 0 and tax_amount > 0:
                    if user_balance >= tax_amount:
                        bank_data[user_id]["balance"] -= tax_amount
                        server_funds += tax_amount
                        log.info(f"User {member.display_name} ({user_id}) paid {tax_amount} tax. New balance: {bank_data[user_id]['balance']}.")
                    else: # Saldo tidak cukup untuk bayar penuh, potong semua yang ada
                        paid_amount = user_balance
                        bank_data[user_id]["balance"] = 0
                        server_funds += paid_amount
                        hinaan = random.choice(self.funny_tax_insults)
                        try:
                            await member.send(f"**Pesan Resmi dari Pejabat PajakBot:**\n\n{hinaan.replace('[Nama Pengguna]', member.display_name)}")
                            log.info(f"Sent tax insult DM to {member.display_name} (insufficient balance, paid {paid_amount}).")
                        except discord.Forbidden:
                            log.warning(f"Failed to send tax insult DM to {member.display_name} (DMs closed).")
                elif user_balance == 0 and tax_percentage > 0: # Saldo 0 tapi pajak diaktifkan
                    hinaan = random.choice(self.funny_tax_insults)
                    try:
                        await member.send(f"**Pesan Resmi dari Pejabat PajakBot:**\n\n{hinaan.replace('[Nama Pengguna]', member.display_name)}")
                        log.info(f"Sent tax insult DM to {member.display_name} (zero balance).")
                    except discord.Forbidden:
                        log.warning(f"Failed to send tax insult DM to {member.display_name} (DMs closed).")

        save_bank_data(bank_data)
        config["server_funds_balance"] = server_funds
        save_economy_config(config)
        log.info(f"Auto tax task finished. Final Server Funds: {server_funds} RSWN.")

    @auto_tax_task.before_loop
    async def before_auto_tax_task(self):
        log.info("Waiting for bot to be ready before starting auto tax task.")
        await self.bot.wait_until_ready()
        log.info("Bot ready, auto tax task is about to start.")

    # --- Background Task untuk Mengecek Masa Penjara ---
    @tasks.loop(minutes=5)
    async def jail_check_task(self):
        log.info("Jail check task started.")
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            guild_id_str = str(guild.id)
            data = load_level_data(guild_id_str)
            
            users_to_release = []  # List untuk mengumpulkan user yang akan dibebaskan

            for user_id, user_data in list(data.items()): # Gunakan list(data.items()) untuk modifikasi dictionary saat iterasi
                if "jailed_until" in user_data and user_data["jailed_until"]:
                    try:
                        jailed_until_dt = datetime.fromisoformat(user_data["jailed_until"])
                        if datetime.utcnow() >= jailed_until_dt:
                            users_to_release.append(user_id)
                    except ValueError: # Tangani jika data jailed_until corrupt
                        log.error(f"Invalid datetime format for jailed_until for user {user_id}. Removing corrupted data.")
                        users_to_release.append(user_id) # Hapus data yang korup

            for user_id in users_to_release:
                log.info(f"Releasing user {user_id} from jail in guild {guild.name}.")
                member = guild.get_member(int(user_id))
                if member: # Pastikan user masih ada di guild
                    await self._release_user(member) # Panggil helper _release_user
                else:
                    log.warning(f"Jailed user {user_id} not found in guild {guild.name}. Cleaning up jail status (data only).")
                    # Tetap bersihkan data meskipun member tidak ditemukan
                    user_data = data.get(user_id, {})
                    user_data.pop("jailed_until", None)
                    user_data.pop("original_nickname", None)
                    user_data.pop("message_cooldown_end", None)
                    data[user_id] = user_data # Update data di dictionary utama
                    save_level_data(guild_id_str, data) # Simpan perubahan data

            if users_to_release: # Hanya simpan jika ada perubahan yang membebaskan user yang masih di guild
                # save_level_data(guild_id_str, data) # Sudah dipanggil di _release_user atau di blok else atas
                log.info(f"Jail statuses updated for guild {guild.name}.")
                
    @jail_check_task.before_loop
    async def before_jail_check_task(self):
        log.info("Waiting for bot to be ready before starting Jail check task.")
        await self.bot.wait_until_ready()
        log.info("Bot ready, Jail check task is about to start.")

    # --- Background Task untuk Menjadwalkan Event Heist/Fire/Quiz Acak ---
    @tasks.loop(hours=random.randint(1, 4)) # Event setiap 1-4 jam
    async def heist_fire_event_scheduler(self):
        log.info("Heist/Fire/Quiz event scheduler started.")
        await self.bot.wait_until_ready()
        await asyncio.sleep(random.randint(60, 300)) # Jeda acak 1-5 menit sebelum eksekusi pertama untuk menghindari bentrok startup

        event_channel = self.bot.get_channel(EVENT_CHANNEL_ID)
        if not event_channel:
            log.error(f"Event channel (ID: {EVENT_CHANNEL_ID}) not found. Skipping event scheduler.")
            return

        for guild in self.bot.guilds:
            # Pastikan event hanya berjalan di guild yang memiliki channel event yang ditentukan
            if guild.id != event_channel.guild.id:
                continue

            if not guild.members:  # Pastikan ada anggota di guild
                log.debug(f"No members in guild {guild.name}. Skipping event scheduling.")
                continue
            
            # Kumpulkan user yang eligible (bukan bot, tidak dalam penjara, tidak sedang dalam event lain)
            potential_victims = [m for m in guild.members if not m.bot]
            
            active_heist_victims = set(self.active_heists.get(str(guild.id), {}).keys())
            active_fire_victims = set(self.active_fires.get(str(guild.id), {}).keys())
            active_quiz_guilds = set(self.active_quizzes.keys()) # Cek apakah ada kuis aktif di guild ini
            
            # Filter korban: tidak dalam penjara, tidak sedang dalam event heist/fire, tidak sedang dalam kuis
            potential_victims = [m for m in potential_victims 
                                 if not (await self._is_user_jailed(m.id, guild.id))[0] and \
                                    str(m.id) not in active_heist_victims and \
                                    str(m.id) not in active_fire_victims]

            event_options = []
            if potential_victims: # Hanya bisa ada heist/fire jika ada target yang valid
                event_options.extend(["heist", "fire"])
            
            # Hanya bisa ada kuis jika belum ada kuis aktif DAN ada cukup pertanyaan di JSON
            trivia_data = load_trivia_questions()
            if str(guild.id) not in active_quiz_guilds and trivia_data.get("questions") and len(trivia_data["questions"]) >= QUIZ_TOTAL_QUESTIONS:
                event_options.append("quiz")

            if not event_options:
                log.info(f"No available event options for guild {guild.name}.")
                continue

            chosen_event_type = random.choice(event_options)
            
            # Logic untuk memilih korban berdasarkan kriteria yang lebih baik (misalnya saldo cukup)
            if chosen_event_type == "heist":
                eligible_for_heist = [m for m in potential_victims if load_bank_data().get(str(m.id), {}).get("balance", 0) >= LOOT_MIN * 2]
                if not eligible_for_heist:
                    log.info(f"No eligible victims for heist in {guild.name} (low balance).")
                    continue
                victim = random.choice(eligible_for_heist)
                log.info(f"Scheduling random heist event for {victim.display_name} in guild {guild.name}.")
                await self._start_heist(guild, victim, event_channel, initiator=self.bot.user)
            elif chosen_event_type == "fire":
                eligible_for_fire = [m for m in potential_victims if load_bank_data().get(str(m.id), {}).get("balance", 0) >= LOOT_MIN]
                if not eligible_for_fire:
                    log.info(f"No eligible victims for fire in {guild.name} (low balance).")
                    continue
                victim = random.choice(eligible_for_fire)
                log.info(f"Scheduling random fire event for {victim.display_name} in guild {guild.name}.")
                await self._start_fire(guild, victim, event_channel)
            elif chosen_event_type == "quiz":
                log.info(f"Scheduling random quiz event in guild {guild.name}.")
                await self._start_quiz_session(guild, event_channel)
            
    @heist_fire_event_scheduler.before_loop
    async def before_heist_fire_scheduler(self):
        log.info("Waiting for bot to be ready before starting heist/fire/quiz scheduler.")
        await self.bot.wait_until_ready()
        log.info("Bot ready, heist/fire/quiz scheduler is about to start.")

    # --- Background Task untuk Proyek Ngawur ---
    @tasks.loop(hours=random.randint(48, 96)) # Proyek baru setiap 2-4 hari
    async def project_scheduler(self):
        log.info("Project scheduler started.")
        await self.bot.wait_until_ready()
        
        event_channel = self.bot.get_channel(EVENT_CHANNEL_ID)
        if not event_channel:
            log.error(f"Event channel (ID: {EVENT_CHANNEL_ID}) not found. Skipping project scheduler.")
            return

        for guild in self.bot.guilds:
            if guild.id != event_channel.guild.id:
                continue

            guild_id_str = str(guild.id)
            # Hanya jalankan jika tidak ada proyek aktif atau proyek yang aktif sudah "failed"
            if guild_id_str in self.active_projects and self.active_projects[guild_id_str].get("status") != "failed":
                log.info(f"Active ngawur project '{self.active_projects[guild_id_str]['name']}' already running in guild {guild.name}. Skipping new project.")
                continue

            # Load projects from JSON file
            ngawur_projects_data = load_ngawur_projects_data()["projects"] # Load from JSON
            if not ngawur_projects_data:
                log.warning("Ngawur projects list is empty. Cannot start new project.")
                continue

            chosen_project = random.choice(ngawur_projects_data) # Use loaded data
            project_name = chosen_project["name"]
            
            log.info(f"Starting random ngawur project: '{project_name}' in guild {guild.name}.")
            await self._start_ngawur_project(guild, project_name, event_channel)

    @project_scheduler.before_loop
    async def before_project_scheduler(self):
        log.info("Waiting for bot to be ready before starting project scheduler.")
        await self.bot.wait_until_ready()
        log.info("Bot ready, project scheduler is about to start.")

    # --- Helper untuk Proyek Ngawur (Private/Internal Use) ---
    async def _start_ngawur_project(self, guild: discord.Guild, project_name: str, event_channel: discord.TextChannel):
        log.info(f"Initiating ngawur project '{project_name}' in guild {guild.name}.")
        guild_id_str = str(guild.id)
        
        # Inisialisasi proyek baru
        self.active_projects[guild_id_str] = {
            "name": project_name,
            "status": "announced", # Status proyek: announced, update, failed, completed (if ever)
            "start_time": datetime.utcnow().isoformat(),
            "last_update_time": datetime.utcnow().isoformat(),
            "phase": "announcement", # Fase proyek: announcement, update, resolution
            "collected_funds": 0 # Dana yang terkumpul spesifik untuk proyek ini
        }
        save_project_data(self.active_projects)
        log.debug(f"Project '{project_name}' state saved.")

        bank_data = load_bank_data()
        collected_from_users = 0
        
        # Kumpulkan dana dari user
        for member in guild.members:
            if member.bot: continue
            user_id_str = str(member.id)
            user_balance = bank_data.get(user_id_str, {}).get("balance", 0)

            if user_balance >= PROJECT_CONTRIBUTION_COST:
                bank_data[user_id_str]["balance"] -= PROJECT_CONTRIBUTION_COST
                collected_from_users += PROJECT_CONTRIBUTION_COST
                log.debug(f"Collected {PROJECT_CONTRIBUTION_COST} from {member.display_name} for project '{project_name}'.")
            else:
                log.debug(f"Skipping collection from {member.display_name} for project '{project_name}' (insufficient funds: {user_balance}).")
        
        save_bank_data(bank_data)
        log.debug("Bank data saved after project fund collection.")

        config = load_economy_config()
        config["server_funds_balance"] += collected_from_users # Tambahkan dana yang terkumpul ke dana server keseluruhan
        save_economy_config(config)
        log.info(f"Added {collected_from_users} to server funds for project '{project_name}'. New server funds: {config['server_funds_balance']}.")

        ngawur_projects_data = load_ngawur_projects_data()["projects"] # Load dari JSON
        chosen_project_data = next((p for p in ngawur_projects_data if p["name"] == project_name), None)
        announcement_text = chosen_project_data["announcement"] if chosen_project_data else f"Proyek {project_name} diumumkan!"

        embed = discord.Embed(
            title=f"🚨 PENGUMUMAN PROYEK TERBARU! 🚨",
            description=(
                f"**PEGAWAI KEMENTERIAN PROYEK NGAWUR:** '{announcement_text}\n\n"
                f"Untuk mendukung proyek visioner ini (dan memastikan pejabat bisa liburan ke Mars), setiap warga yang memiliki cukup dana telah dikenakan 'dana partisipasi pembangunan' sebesar **{PROJECT_CONTRIBUTION_COST} RSWN**.'\n\n"
                f"Total dana terkumpul dari rakyat: **{collected_from_users} RSWN**.'\n"
                f"*(Jangan protes, ini demi negara, kok! Tentu saja, negara versi kami.) 🤫*"
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="Proyek ini akan selalu gagal, tapi pungutan tetap jalan! 😂")
        await event_channel.send(embed=embed)
        log.info(f"Sent project announcement for '{project_name}' to channel {event_channel.name}.")
        
        log.debug(f"Scheduling first update for project '{project_name}' in {self.project_update_duration_hours} hours.")
        await asyncio.sleep(self.project_update_duration_hours * 3600)
        # Panggil update, tapi cek dulu apakah proyek ini masih yang aktif
        if self.active_projects.get(guild_id_str, {}).get("name") == project_name:
            await self._update_ngawur_project(guild, project_name, event_channel)


    async def _update_ngawur_project(self, guild: discord.Guild, project_name: str, event_channel: discord.TextChannel):
        log.info(f"Updating ngawur project '{project_name}' in guild {guild.name}.")
        guild_id_str = str(guild.id)
        # Penting: Pastikan proyek yang sedang di-update masih aktif dan sama
        if guild_id_str not in self.active_projects or self.active_projects[guild_id_str]["name"] != project_name:  
            log.warning(f"Project '{project_name}' not active or changed for update in guild {guild.name}. Skipping update.")
            return

        ngawur_projects_data = load_ngawur_projects_data()["projects"] # Load dari JSON
        chosen_project_data = next((p for p in ngawur_projects_data if p["name"] == project_name), None)
        update_text = chosen_project_data["update"] if chosen_project_data else f"Update proyek {project_name}..."

        self.active_projects[guild_id_str]["status"] = "update"
        self.active_projects[guild_id_str]["last_update_time"] = datetime.utcnow().isoformat()
        save_project_data(self.active_projects)
        log.debug(f"Project '{project_name}' status updated to 'update'.")

        embed = discord.Embed(
            title=f"🚧 UPDATE PROYEK: {project_name} 🚧",
            description=(
                f"**PEMBARUAN DARI LAPANGAN:** '{update_text}\n\n"
                f"Perkembangan proyek saat ini... *batuk-batuk* ...sedang berjalan sangat lancar, sesuai dengan tradisi negara kita, yaitu **'mundur tiga langkah, maju satu langkah'**! Kami optimistis akan selesai tepat waktu, di waktu yang tidak ditentukan! *(Mungkin mirip proyek di negara X yang bangun jalan cuma pakai spidol permanen di aspal).* 🙄"
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text="Jangan terlalu berharap, ya. Ini kan proyek pemerintah.")
        await event_channel.send(embed=embed)
        log.info(f"Sent project update for '{project_name}' to channel {event_channel.name}.")

        log.debug(f"Scheduling project failure for '{project_name}' in {(self.project_fail_duration_hours - self.project_update_duration_hours)} hours.")
        await asyncio.sleep((self.project_fail_duration_hours - self.project_update_duration_hours) * 3600)
        # Panggil resolve, tapi cek dulu apakah proyek ini masih yang aktif
        if self.active_projects.get(guild_id_str, {}).get("name") == project_name:
            await self._resolve_ngawur_project(guild, project_name, event_channel)


    async def _resolve_ngawur_project(self, guild: discord.Guild, project_name: str, event_channel: discord.TextChannel):
        log.info(f"Resolving ngawur project '{project_name}' in guild {guild.name}.")
        guild_id_str = str(guild.id)
        # Penting: Pastikan proyek yang sedang di-resolve masih aktif dan sama
        if guild_id_str not in self.active_projects or self.active_projects[guild_id_str]["name"] != project_name:  
            log.warning(f"Project '{project_name}' not active or changed for resolution in guild {guild.name}. Skipping resolution.")
            return

        ngawur_projects_data = load_ngawur_projects_data()["projects"] # Load dari JSON
        chosen_project_data = next((p for p in ngawur_projects_data if p["name"] == project_name), None)
        failure_text = chosen_project_data["failure"] if chosen_project_data else f"Proyek {project_name} gagal total!"

        embed = discord.Embed(
            title=f"💔 PROYEK GAGAL TOTAL: {project_name} 💔",
            description=(
                f"**BERITA TERAKHIR DARI KEMENTERIAN PROYEK NGAWUR:** '{failure_text}\n\n"
                f"Ini adalah contoh nyata bahwa bahkan dengan teknologi dan niat baik (katanya), jika pondasinya kerupuk dan anggarannya bolong-bolong, hasilnya akan mirip dengan proyek infrastruktur di negara lain yang bangun jembatan pakai karet gelang. Dananya? Ludes!"
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text="Uang rakyat? Ya sudah, ikhlaskan saja. Anggap sedekah.")
        await event_channel.send(embed=embed)
        log.info(f"Sent project failure announcement for '{project_name}' to channel {event_channel.name}.")

        self.active_projects.pop(guild_id_str, None) # Hapus dari daftar aktif
        save_project_data(self.active_projects)
        log.info(f"Project '{project_name}' status removed. Funds considered lost.")


    # --- Implementasi Event Pencurian (Heist) ---
    async def _start_heist(self, guild: discord.Guild, victim: discord.Member, event_channel: discord.TextChannel, initiator: discord.Member = None):
        log.info(f"Starting heist for {victim.display_name} by {initiator.display_name if initiator else 'bot'}.")
        guild_id_str = str(guild.id)
        victim_id_str = str(victim.id)

        if guild_id_str not in self.active_heists:
            self.active_heists[guild_id_str] = {}
        if victim_id_str in self.active_heists[guild_id_str]:
            log.debug(f"Heist already active for {victim.display_name}. Skipping new heist.")
            return

        self.active_heists[guild_id_str][victim_id_str] = {
            "initiator_id": str(initiator.id) if initiator else "bot",
            "start_time": datetime.utcnow(),
            "channel_id": event_channel.id,
            "status": "pending" # Menambahkan status untuk melacak apakah sudah direspon
        }
        log.debug(f"Heist data stored: {self.active_heists[guild_id_str][victim_id_str]}")
        
        heist_msg = (
            f"🚨 **DRRRTT! DRRRTT!** Alarm keamananmu berteriak histeris! Kamu melihat siluet mencurigakan di jendela! Seseorang, sepertinya **{(initiator.display_name if initiator else 'sesosok misterius')}**, sedang mencoba menyelinap masuk! 🚨\n\n"
            f"Cepat, **{victim.display_name}**! Panggil POLISI dengan mengetik `!polisi` di channel <#{EVENT_CHANNEL_ID}> dalam **{RESPONSE_TIME_SECONDS} detik** atau semua harta di rumahmu bisa lenyap tak bersisa! Jangan sampai telat, mereka bisa saja lagi minum kopi di pos! ☕"
        )
        try:
            await victim.send(heist_msg)
            log.info(f"Sent heist warning DM to {victim.display_name}.")
        except discord.Forbidden:
            await event_channel.send(f"🚨 **PERINGATAN! {victim.mention}!** Alarm keamananmu berbunyi! Seseorang mencoba mencuri! Periksa DMmu untuk detail, atau ketik `!polisi` di sini dalam **{RESPONSE_TIME_SECONDS} detik**!", delete_after=RESPONSE_TIME_SECONDS + 10)
            log.warning(f"Could not send heist DM to {victim.display_name} (DMs closed), sent to channel instead.")


        if initiator and initiator != self.bot.user:
            try:
                await initiator.send(
                    f"🕵️‍♂️ **Misi Pencurian Dimulai!** Kamu sudah masuk halaman, alarm si korban sudah bunyi, dan detak jantungmu berpacu! Jangan sampai polisi cepat datang! Kamu punya waktu **{RESPONSE_TIME_SECONDS} detik** sebelum dia lapor. Modalmu **{HEIST_COST} koin** sudah kami pegang."
                )
            except discord.Forbidden:
                log.warning(f"Could not send heist initiation DM to initiator {initiator.display_name} (DMs closed).")
            bank_data = load_bank_data()
            bank_data.setdefault(str(initiator.id), {"balance":0, "debt":0})["balance"] -= HEIST_COST
            save_bank_data(bank_data)
            log.info(f"Heist cost {HEIST_COST} deducted from {initiator.display_name}.")

        log.debug(f"Heist timer started for {victim.display_name}. Waiting {RESPONSE_TIME_SECONDS} seconds.")
        await asyncio.sleep(RESPONSE_TIME_SECONDS)
        # Periksa status sebelum resolve, jika sudah direspon, jangan resolve lagi
        if victim_id_str in self.active_heists.get(guild_id_str, {}) and self.active_heists[guild_id_str][victim_id_str].get("status") == "pending":
            log.info(f"Heist timer expired for {victim.display_name}. Resolving as not responded.")
            await self._resolve_heist(guild, victim, event_channel, initiator, responded=False)

    async def _resolve_heist(self, guild: discord.Guild, victim: discord.Member, event_channel: discord.TextChannel, initiator: discord.Member, responded: bool):
        log.info(f"Resolving heist for {victim.display_name}. Responded: {responded}.")
        guild_id_str = str(guild.id)
        victim_id_str = str(victim.id)
        
        heist_data = self.active_heists.get(guild_id_str, {}).pop(victim_id_str, None)
        if not heist_data:  # Jika sudah di-pop oleh respon sebelumnya
            log.warning(f"Heist data not found for {victim.display_name}. Already resolved or not active.")
            return

        bank_data = load_bank_data()
        victim_balance = bank_data.get(victim_id_str, {}).get("balance", 0)
        
        loot_amount = random.randint(LOOT_MIN, LOOT_MAX)
        actual_loot = 0

        heist_outcome_text = ""
        announcement_text = ""
        is_jailed = False
        
        police_names = ["Bripka Jono", "Aipda Siti", "Kompol Budi", "Iptu Rani", "Brigadir Cecep"]
        random_police_name = random.choice(police_names)

        # Mendapatkan objek initiator dan victim yang aman dari NoneType
        # initiator sudah ditangani di atas function, tapi kita re-check untuk keamanannya
        # victim adalah discord.Member, jadi display_name dan mention aman
        initiator_display_name = initiator.display_name if isinstance(initiator, discord.User) else initiator
        initiator_mention = initiator.mention if isinstance(initiator, discord.User) else initiator_display_name

        victim_display_name = victim.display_name if isinstance(victim, discord.Member) else f"User Tak Dikenal ({victim_id_str})"
        victim_mention = victim.mention if isinstance(victim, discord.Member) else victim_display_name


        if responded and random.random() < BUREAUCRACY_CHANCE: # Birokrasi mengganggu respon (25% chance)
            log.info(f"Heist for {victim_display_name}: Birokrasi scenario triggered.")
            heist_outcome_text = (
                f"📞 Kamu buru-buru menelepon 110. 'Halo, ini darurat! Ada pencuri di rumah saya!' katamu panik. Petugas di seberang menjawab santai, 'Baik, Pak/Bu. Bisa tolong kirimkan **fotokopi KTP, KK, akta kelahiran, surat keterangan tidak mampu, bukti pembayaran PBB tiga bulan terakhir, dan surat pernyataan belum menikah bermaterai Rp 10.000** ke fax kami? Jangan lupa sertakan pas foto ukuran 3x4!' Kamu melongo. **Panggilan terputus!** Ah, sial! Kamu sibuk mencari berkas, pencuri **{initiator_display_name}** dengan santai menggasak rumahmu!\n"
                f"Kamu kehilangan **{min(loot_amount, victim_balance)} RSWN**!"
            )
            announcement_text = f"KARENA BIROKRASI: **{victim_mention}** gagal melapor, rumahnya jadi sasaran empuk **{initiator_mention}**! Korbannya sibuk fotokopi KTP!"
            actual_loot = min(loot_amount, victim_balance)
            victim_balance -= actual_loot
            log.debug(f"Victim lost {actual_loot} due to bureaucracy.")

        elif responded: # Korban merespon, tapi tanpa birokrasi
            rand_chance = random.random()
            if rand_chance < 0.40: # 40% Cepat & Profesional: Pencuri Tertangkap
                heist_outcome_text = (
                    f"🚓💨 **NYIIIIEEEEEENGGG!** Sirene polisi meraung kencang, membelah keheningan malam! Mobil patroli tiba dalam hitungan detik, nge-drift epik di depan rumahmu! Petugas **{random_police_name}** dengan sigap melompat keluar, menodongkan senter ke arah **{initiator_display_name}** yang terkejut setengah mati! 'Tangan di atas!' teriaknya. Pencuri panik, menjatuhkan semua perkakasnya dan mencoba kabur, tapi kakinya tersandung pot bunga mawar kesayanganmu! **TERTANGKAP!** Rumahmu aman, **{victim_display_name}**! Barang-barangmu selamat! 🎉"
                )
                announcement_text = f"BERITA PANAS! **{initiator_mention}** tertangkap basah saat mencoba mencuri dari **{victim_mention}**! Polisi tanggap, pencuri kini mendekam di balik jeruji besi! 🚨"
                is_jailed = True # Pencuri masuk penjara
                log.info(f"Heist for {victim_display_name}: Police caught initiator {initiator_display_name}.")
            elif rand_chance < 0.75: # 35% Agak Lambat: Pencuri Kabur dengan Sebagian Jarahan
                log.info(f"Heist for {victim_display_name}: Police a bit slow. Partial loot taken.")
                partial_loot_amount = random.randint(int(LOOT_MIN * 0.2), int(LOOT_MAX * 0.4))
                actual_loot = min(partial_loot_amount, victim_balance)
                heist_outcome_text = (
                    f"🚨💨 Kamu sudah memanggil polisi, tapi sepertinya mereka lagi menikmati donat di pos. Sirene terdengar samar-samar dan makin dekat, tapi butuh waktu! Pencuri **{initiator_display_name}** yang sudah di dalam rumah, mendengar itu dan sempat meraih **{actual_loot} RSWN** sebelum kabur lewat jendela belakang! 'Sial, cepat sekali!' desisnya sambil membawa kabur hasil jarahanmu. 😩 Kamu kehilangan **{actual_loot} RSWN**!"
                )
                announcement_text = f"Kabar Buruk! **{initiator_mention}** berhasil kabur dengan jarahan kecil dari **{victim_mention}**! Polisi agak telat! 😥"
                victim_balance -= actual_loot
                log.debug(f"Victim lost {actual_loot} due to slow police.")
            else: # 25% Gagal/Kocak: Pencuri Kabur dengan Banyak Jarahan
                log.info(f"Heist for {victim_display_name}: Police failed/comical. Medium loot taken.")
                medium_loot_amount = random.randint(int(LOOT_MIN * 0.5), int(LOOT_MAX * 0.8))
                actual_loot = min(medium_loot_amount, victim_balance)
                heist_outcome_text = (
                    f"🚓💨 Kamu memanggil polisi, tapi rupanya mereka malah tersesat di peta Google! Ketika akhirnya tiba, mereka malah minta selfie dengan rumahmu yang sudah kosong! Pencuri **{initiator_display_name}** sudah jauh melesat dengan motor balapnya, membawa kabur **{actual_loot} RSWN**! 'Maaf, Pak, kami kira ini latihan evakuasi kucing,' kata salah satu petugas cengengesan. 🤦‍♂️ Kamu kehilangan **{actual_loot} RSWN**!"
                )
                announcement_text = f"WAH Gawat! Polisi salah jalan! **{initiator_mention}** berhasil merampok **{victim_mention}** tanpa halangan! 😭"
                victim_balance -= actual_loot
                log.debug(f"Victim lost {actual_loot} due to failed police.")
        else: # Korban tidak merespon atau terlambat
            log.info(f"Heist for {victim_display_name}: Victim did not respond. Large loot taken.")
            large_loot_amount = random.randint(int(LOOT_MIN * 0.8), LOOT_MAX)
            actual_loot = min(large_loot_amount, victim_balance)
            heist_outcome_text = (
                f"⏱️ Waktu habis! Karena kamu terlalu lama, pencuri **{initiator_display_name}** dengan santai membersihkan seluruh rumahmu! Dia bahkan sempat menyeduh kopi dan membaca koran sebelum pergi! 'Terima kasih atas keramahannya!' teriaknya dari jauh.💔 Kamu kehilangan **{actual_loot} RSWN**!"
            )
            announcement_text = f"TRAGIS! **{victim_mention}** lupa ada pencurian, **{initiator_mention}** panen raya! 💀"
            victim_balance -= actual_loot
            log.debug(f"Victim lost {actual_loot} due to no response.")
        
        bank_data[victim_id_str]["balance"] = victim_balance
        save_bank_data(bank_data)
        log.info(f"Victim {victim_display_name}'s new balance: {victim_balance}.")

        if isinstance(initiator, discord.Member) and initiator.id != self.bot.user.id: # Jika pencurian dipicu oleh user (bukan bot)
            bank_data = load_bank_data() # Muat ulang bank_data karena mungkin sudah berubah
            if is_jailed:
                log.info(f"Initiator {initiator_display_name} jailed. No loot gained.")
                await self._jail_user(initiator, JAIL_DURATION_HOURS)
                try: await initiator.send(f"💔 Anda tertangkap basah dan dijebloskan ke penjara! Modalnya hangus dan tidak dapat hasil. Malu! 😱")
                except discord.Forbidden: log.warning(f"Could not send jail result DM to initiator {initiator_display_name} (DMs closed).")
            else:
                bank_data.setdefault(str(initiator.id), {"balance":0, "debt":0})["balance"] += (HEIST_COST + actual_loot) # Modal kembali + hasil curian
                save_bank_data(bank_data)
                log.info(f"Initiator {initiator_display_name} gained {actual_loot} loot (total {HEIST_COST + actual_loot}). New balance: {bank_data[str(initiator.id)]['balance']}.")
                try:
                    await initiator.send(f"🎉 **MISI SELESAI!** Kamu berhasil mendapatkan **{actual_loot} RSWN** dari pencurian! Total yang kamu dapatkan (modal kembali + hasil curian) adalah **{HEIST_COST + actual_loot} RSWN**!")
                except discord.Forbidden:
                    log.warning(f"Could not send heist result DM to initiator {initiator_display_name} (DMs closed).")

        try:
            await victim.send(heist_outcome_text)
        except discord.Forbidden:
            await event_channel.send(f"🚨 Laporan Heist untuk {victim_mention}:\n{heist_outcome_text}", delete_after=60)
            log.warning(f"Could not send victim DM to {victim_display_name} (DMs closed), sent to channel instead.")
            
        await event_channel.send(announcement_text)
        log.info(f"Heist result announced in {event_channel.name}.")
        

    @commands.command(name="curi") # Command tanpa prefiks rtm
    async def curi(self, ctx, target_user: discord.Member):
        logging.info(f"Command !curi used by {ctx.author.display_name} targeting {target_user.display_name}.")
        if ctx.channel.id != EVENT_CHANNEL_ID:
            logging.debug(f"Command curi used in wrong channel ({ctx.channel.id}). Expected {EVENT_CHANNEL_ID}.")
            return await ctx.send(f"Command ini hanya bisa digunakan di <#{EVENT_CHANNEL_ID}>.", ephemeral=True)
            
        if target_user.bot:
            logging.debug("Target is a bot. Cannot rob.")
            return await ctx.send("❌ Kamu tidak bisa mencuri dari bot! Mereka tidak punya apa-apa (atau mereka menyembunyikannya dengan sangat baik).", ephemeral=True)
        if target_user.id == ctx.author.id:
            logging.debug("User trying to rob themselves.")
            return await ctx.send("❌ Kamu tidak bisa mencuri dari dirimu sendiri, dasar aneh.", ephemeral=True)

        guild_id_str = str(ctx.guild.id)
        jailed, jailed_until = await self._is_user_jailed(ctx.author.id, guild_id_str)
        if jailed:
            logging.debug(f"Robber {ctx.author.display_name} is jailed. Cannot rob.")
            return await ctx.send(f"❌ Kamu sedang dalam masa tahanan sampai {jailed_until.strftime('%d-%m-%Y %H:%M WIB')}! Tidak bisa melakukan aksi kriminal.", ephemeral=True)
        
        # Cek apakah initiator atau target sedang dalam event aktif lainnya
        if str(ctx.author.id) in self.active_heists.get(guild_id_str, {}) or \
           str(ctx.author.id) in self.active_fires.get(guild_id_str, {}) or \
           str(ctx.guild.id) in self.active_quizzes: # Cek jika user sendiri sedang di heist/fire/quiz
            logging.debug(f"Robber {ctx.author.display_name} is in another active event/quiz.")
            return await ctx.send("❌ Kamu sedang dalam proses event lain!", ephemeral=True)
        if str(target_user.id) in self.active_heists.get(guild_id_str, {}) or \
           str(target_user.id) in self.active_fires.get(guild_id_str, {}): # Cek jika target sedang di heist/fire
            logging.debug(f"Target {target_user.display_name} is in another active event.")
            return await ctx.send("❌ Target sedang dalam proses event lain! Coba cari target lain.", ephemeral=True)


        bank_data = load_bank_data()
        initiator_balance = bank_data.get(str(ctx.author.id), {}).get("balance", 0)

        if initiator_balance < HEIST_COST:
            logging.debug(f"Robber {ctx.author.display_name} has insufficient funds ({initiator_balance}) to pay heist cost ({HEIST_COST}).")
            return await ctx.send(f"❌ Kamu butuh **{HEIST_COST} RSWN** untuk modal beli linggis dan obeng. Saldomu tidak cukup!")
            
        target_balance = bank_data.get(str(target_user.id), {}).get("balance", 0)
        
        if target_balance < LOOT_MIN: # Target terlalu miskin, pencurian tetap jalan tapi gagal panen
            logging.info(f"Robbing {target_user.display_name}. Target balance {target_balance} is too low ({LOOT_MIN}). Heist will fail, cost will be deducted.")
            # Potong modal HEIST_COST duluan
            bank_data.setdefault(str(ctx.author.id), {"balance":0, "debt":0})["balance"] -= HEIST_COST
            save_bank_data(bank_data)
            await ctx.send(
                f"🕵️‍♂️ Kamu membayar **{HEIST_COST} koin** untuk 'modal awal' operasi ini. Uang ini sudah termasuk sewa linggis antik, obeng set lengkap, penutup wajah bergambar monyet, dan sekantong permen karet biar gak tegang di lapangan. Misi ini resmi dimulai!\n\n"
                f"Kamu berhasil menyelinap masuk ke rumah **{target_user.display_name}**! Kamu mencari-cari, mengobrak-abrik, tapi yang kamu temukan cuma debu tebal, remahan biskuit di bawah sofa, dan tagihan listrik yang belum dibayar. Astaga, sepertinya targetmu kali ini lagi bokek parah! Kamu pulang dengan tangan hampa. Linggismu kini terasa sangat berat. Modal **{HEIST_COST} koinmu hangus** karena 'risiko operasional'!"
            )
            return

        logging.info(f"Heist started by {ctx.author.display_name} targeting {target_user.display_name}. Cost: {HEIST_COST}.")
        await self._start_heist(ctx.guild, target_user, ctx.channel, initiator=ctx.author)
        
    @commands.command(name="polisi") # Command tanpa prefiks rtm
    async def call_police(self, ctx):
        logging.info(f"Command !polisi used by {ctx.author.display_name}.")
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        if guild_id not in self.active_heists or user_id not in self.active_heists[guild_id]:
            logging.debug(f"No active heist found for {ctx.author.display_name}.")
            return await ctx.send("❌ Tidak ada pencurian yang sedang terjadi di rumahmu! Atau kamu telat. Jangan panik tanpa sebab!", ephemeral=True)

        heist_info = self.active_heists[guild_id][user_id]
        # Pastikan status 'pending' sebelum diproses
        if heist_info.get("status") != "pending":
            logging.debug(f"Heist for {ctx.author.display_name} already responded or invalid status.")
            return await ctx.send("❌ Pencurian ini sudah ditangani atau tidak valid.", ephemeral=True)

        time_elapsed = (datetime.utcnow() - heist_info["start_time"]).total_seconds()

        if time_elapsed > RESPONSE_TIME_SECONDS:
            logging.info(f"Police called too late by {ctx.author.display_name} ({time_elapsed:.2f}s elapsed).")
            await ctx.send("❌ Kamu terlalu lambat! Polisi tidak bisa menanggapi panggilan yang terlambat. Pencurian sudah selesai.", ephemeral=True)
            initiator_id = heist_info["initiator_id"] # Ambil ID initiator dari data
            initiator = self.bot.get_user(int(initiator_id)) if initiator_id != "bot" else self.bot.user # Dapatkan objectnya
            self.active_heists[guild_id][user_id]["status"] = "responded" # Tandai status sebagai 'responded' sebelum memanggil _resolve_heist
            await self._resolve_heist(ctx.guild, ctx.author, ctx.channel, initiator, responded=False)
            return

        self.active_heists[guild_id][user_id]["status"] = "responded" # Tandai sudah direspon
        logging.info(f"Police called in time by {ctx.author.display_name}. Resolving heist.")
        initiator_id = heist_info["initiator_id"] # Ambil ID initiator dari data
        initiator = self.bot.get_user(int(initiator_id)) if initiator_id != "bot" else self.bot.user # Dapatkan objectnya
        await self._resolve_heist(ctx.guild, ctx.author, ctx.channel, initiator, responded=True)
        try: await ctx.message.delete()
        except discord.HTTPException: pass


    # --- Implementasi Event Kebakaran (Fire) ---
    async def _start_fire(self, guild: discord.Guild, victim: discord.Member, event_channel: discord.TextChannel):
        log.info(f"Starting fire event for {victim.display_name}.")
        guild_id_str = str(guild.id)
        victim_id_str = str(victim.id)

        if guild_id_str not in self.active_fires:
            self.active_fires[guild_id_str] = {}
        if victim_id_str in self.active_fires[guild_id_str]:
            log.debug(f"Fire event already active for {victim.display_name}. Skipping new event.")
            return

        self.active_fires[guild_id_str][victim_id_str] = {
            "start_time": datetime.utcnow(),
            "channel_id": event_channel.id,
            "status": "pending" # Menambahkan status untuk melacak apakah sudah direspon
        }
        log.debug(f"Fire data stored: {self.active_fires[guild_id_str][victim_id_str]}")
        
        fire_msg = (
            f"🔥 **API! API!** Kamu mencium bau gosong yang aneh, dan tiba-tiba alarm asap di rumahmu berteriak kencang! Asap tebal mengepul dari dapur, dan api mulai menjilat! 🔥\n\n"
            f"**Panik boleh, tapi bertindak lebih baik!** Panggil PEMADAM KEBAKARAN dengan mengetik `!pemadam` di channel <#{EVENT_CHANNEL_ID}> dalam **{RESPONSE_TIME_SECONDS} detik** atau rumahmu bisa jadi abu! Jangan sampai petugasnya lagi asyik nge-Tiktok!🤳"
        )
        try:
            await victim.send(fire_msg)
            log.info(f"Sent fire warning DM to {victim.display_name}.")
        except discord.Forbidden:
            await event_channel.send(f"🔥 **PERINGATAN! {victim.mention}!** Rumahmu terbakar! Periksa DMmu untuk detail, atau ketik `!pemadam` di sini dalam **{RESPONSE_TIME_SECONDS} detik**!", delete_after=RESPONSE_TIME_SECONDS + 10)
            log.warning(f"Could not send fire DM to {victim.display_name} (DMs closed), sent to channel instead.")

        log.debug(f"Fire timer started for {victim.display_name}. Waiting {RESPONSE_TIME_SECONDS} seconds.")
        await asyncio.sleep(RESPONSE_TIME_SECONDS)
        # Periksa status sebelum resolve, jika sudah direspon, jangan resolve lagi
        if victim_id_str in self.active_fires.get(guild_id_str, {}) and self.active_fires[guild_id_str][victim_id_str].get("status") == "pending":
            log.info(f"Fire timer expired for {victim.display_name}. Resolving as not responded.")
            await self._resolve_fire(guild, victim, event_channel, responded=False)

    async def _resolve_fire(self, guild: discord.Guild, victim: discord.Member, event_channel: discord.TextChannel, responded: bool):
        log.info(f"Resolving fire event for {victim.display_name}. Responded: {responded}.")
        guild_id_str = str(guild.id)
        victim_id_str = str(victim.id)

        fire_data = self.active_fires.get(guild_id_str, {}).pop(victim_id_str, None)
        if not fire_data:  # Jika sudah di-pop oleh respon sebelumnya
            log.warning(f"Fire data not found for {victim.display_name}. Already resolved or not active.")
            return

        bank_data = load_bank_data()
        victim_balance = bank_data.get(victim_id_str, {}).get("balance", 0)
        
        damage_amount = random.randint(LOOT_MIN, LOOT_MAX) # loot_min/max digunakan juga untuk damage di sini
        actual_damage = 0

        fire_outcome_text = ""
        announcement_text = ""
        
        firefighter_names = ["Petugas Alex", "Komandan Bella", "Asisten Chandra", "Bapak Dedi", "Ibu Endang"]
        random_firefighter_name = random.choice(firefighter_names)

        if responded and random.random() < BUREAUCRACY_CHANCE: # Birokrasi mengganggu respon (25% chance)
            log.info(f"Fire for {victim.display_name}: Birokrasi scenario triggered.")
            fire_outcome_text = (
                f"📞 Kamu panik menelepon 112. 'Kebakaran! Rumah saya terbakar!' teriakmu. Petugas di seberang dengan suara malas menjawab, 'Bapak/Ibu, bisa tolong jelaskan dulu kronologinya dari awal? Lalu, berapa jumlah titik apinya? Sudah coba padamkan pakai air keran? Ah, dan jangan lupa, kami butuh **surat izin bakar dari RT/RW setempat** dan **fotokopi kartu keluarga**!' Kamu kaget bukan kepalang. **Panggilan terputus!** Sementara kamu mencari berkas, api sudah merajalela!\n"
                f"Kamu kehilangan **{min(damage_amount, victim_balance)} RSWN**!"
            )
            announcement_text = f"KEBAKARAN PARAH! Rumah **{victim.mention}** hangus karena petugas pemadam kebakaran terlalu banyak birokrasi! 😭"
            actual_damage = min(damage_amount, victim_balance)
            victim_balance -= actual_damage
            log.debug(f"Victim lost {actual_damage} due to bureaucracy.")

        elif responded: # Korban merespon, tapi tanpa birokrasi
            rand_chance = random.random()
            if rand_chance < 0.40: # 40% Cepat & Efisien: Kerugian Minimal
                log.info(f"Fire for {victim.display_name}: Firefighters fast & efficient.")
                min_loss = int(damage_amount * 0.1)
                max_loss = int(damage_amount * 0.2)
                actual_damage = random.randint(min_loss, max_loss)
                actual_damage = min(actual_damage, victim_balance)
                fire_outcome_text = (
                    f"🚒💨 **WWUUUUSSSHHHH!** Sirene meraung dan pemadam kebakaran tiba dalam sekejap mata! Petugas **{random_firefighter_name}** dengan helm khasnya langsung menyemprotkan air, memadamkan api hanya dalam hitungan menit! 'Untung cepat, Pak/Bu!' katanya. Kerugian minimal! Hanya **{actual_damage} RSWN** yang hangus, itu pun cuma sandal jepit favoritmu. 😅"
                )
                announcement_text = f"BERHASIL! Rumah **{victim.mention}** nyaris hangus, tapi pemadam kebakaran bertindak cepat! 🎉"
                victim_balance -= actual_damage
                log.debug(f"Victim lost {actual_damage} due to fast firefighters.")
            elif rand_chance < 0.75: # 35% Agak Lambat: Kerugian Sedang
                log.info(f"Fire for {victim.display_name}: Firefighters a bit slow. Medium damage.")
                min_loss = int(damage_amount * 0.4)
                max_loss = int(damage_amount * 0.6)
                actual_damage = random.randint(min_loss, max_loss)
                actual_damage = min(actual_damage, victim_balance)
                fire_outcome_text = (
                    f"🚨💨 Kamu sudah memanggil pemadam, tapi mereka sepertinya sedang sibuk melayani pesanan es krim. Mereka memang datang, tapi setelah api sempat melahap sebagian atap dan beberapa perabotan pentingmu. 'Maaf, Pak, tadi ada kucing nyangkut di pohon,' dalih mereka. Kamu kehilangan **{actual_damage} RSWN**!"
                )
                announcement_text = f"KEBAKARAN! Rumah **{victim.mention}** terbakar cukup parah, pemadam kebakaran agak lambat! 😩"
                victim_balance -= actual_damage
                log.debug(f"Victim lost {actual_damage} due to slow firefighters.")
            else: # 25% Gagal/Kocak: Kerugian Besar
                log.info(f"Fire for {victim.display_name}: Firefighters failed/comical. Large damage.")
                min_loss = int(damage_amount * 0.7)
                max_loss = int(damage_amount * 0.9)
                actual_damage = random.randint(min_loss, max_loss)
                actual_damage = min(actual_damage, victim_balance)
                fire_outcome_text = (
                    f"🚒💥 Kamu memanggil pemadam, tapi entah selang airnya bocor, atau mereka lupa membawa air! Mereka hanya bisa menonton dengan mulut menganga saat api terus berkobar! 'Ehm, ini kan cuma api kecil...' kata salah satu petugas sambil garuk-garuk kepala. Rumahmu habis terbakar rata dengan tanah! 😭 Kamu kehilangan **{actual_damage} RSWN**!"
                )
                announcement_text = f"TRAGEDI! Rumah **{victim.mention}** hangus total, pemadam kebakaran cuma numpang lewat! 💀"
                victim_balance -= actual_damage
                log.debug(f"Victim lost {actual_damage} due to failed firefighters.")
        else: # Korban tidak merespon atau terlambat
            log.info(f"Fire for {victim.display_name}: Victim did not respond. Total loss.")
            total_loss_amount = random.randint(int(LOOT_MIN * 0.9), LOOT_MAX)
            actual_damage = min(total_loss_amount, victim_balance)
            fire_outcome_text = (
                f"⏱️ Waktu habis! Karena tidak ada tanggapan, api melalap habis seluruh rumahmu tanpa ampun. Semua hartamu, kenangan, semuanya ludes jadi abu! Mungkin kamu harus pindah ke goa sekarang. 💔 Kamu kehilangan **{actual_damage} RSWN**!"
            )
            announcement_text = f"DUKA! Rumah **{victim.mention}** ludes terbakar karena tidak ada tanggapan! 😭"
            victim_balance -= actual_damage
            log.debug(f"Victim lost {actual_damage} due to no response.")

        bank_data[victim_id_str]["balance"] = victim_balance
        save_bank_data(bank_data)
        log.info(f"Victim {victim.display_name}'s new balance after fire: {victim_balance}.")

        try:
            await victim.send(fire_outcome_text)
        except discord.Forbidden:
            await event_channel.send(f"🔥 Laporan Kebakaran untuk {victim.mention}:\n{fire_outcome_text}", delete_after=60)
            log.warning(f"Could not send fire outcome DM to {victim.display_name} (DMs closed), sent to channel instead.")
            
        await event_channel.send(announcement_text)
        log.info(f"Fire event result announced in {event_channel.name}.")

    @commands.command(name="pemadam") # Command tanpa prefiks rtm
    async def call_fire_department(self, ctx):
        log.info(f"Command !pemadam used by {ctx.author.display_name}.")
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        if guild_id not in self.active_fires or user_id not in self.active_fires[guild_id]:
            log.debug(f"No active fire found for {ctx.author.display_name}.")
            return await ctx.send("❌ Tidak ada kebakaran yang sedang terjadi di rumahmu! Atau kamu telat. Jangan panik tanpa sebab!", ephemeral=True)

        fire_info = self.active_fires[guild_id][user_id]
        # Pastikan status 'pending' sebelum diproses
        if fire_info.get("status") != "pending":
            log.debug(f"Fire for {ctx.author.display_name} already responded or invalid status.")
            return await ctx.send("❌ Kebakaran ini sudah ditangani atau tidak valid.", ephemeral=True)

        time_elapsed = (datetime.utcnow() - fire_info["start_time"]).total_seconds()

        if time_elapsed > RESPONSE_TIME_SECONDS:
            log.info(f"Firefighters called too late by {ctx.author.display_name} ({time_elapsed:.2f}s elapsed).")
            await ctx.send("❌ Kamu terlalu lambat! Pemadam kebakaran tidak bisa menanggapi panggilan yang terlambat. Kebakaran sudah selesai.", ephemeral=True)
            # Tandai status sebagai 'responded' sebelum memanggil _resolve_fire
            self.active_fires[guild_id][user_id]["status"] = "responded"
            await self._resolve_fire(ctx.guild, ctx.author, ctx.channel, responded=False)
            return

        self.active_fires[guild_id][user_id]["status"] = "responded" # Tandai sudah direspon
        log.info(f"Firefighters called in time by {ctx.author.display_name}. Resolving fire event.")
        await self._resolve_fire(ctx.guild, ctx.author, ctx.channel, responded=True)
        try: await ctx.message.delete()
        except discord.HTTPException: pass


    # --- Command Admin untuk Memaksa Event ---
    @commands.command(name="forceheist") # Command tanpa prefiks rtm
    @commands.has_permissions(administrator=True)
    async def force_heist(self, ctx, target_user: discord.Member):
        logging.info(f"Admin {ctx.author.display_name} forcing heist on {target_user.display_name}.")
        if ctx.channel.id != EVENT_CHANNEL_ID:
            logging.debug(f"Command forceheist used in wrong channel ({ctx.channel.id}). Expected {EVENT_CHANNEL_ID}.")
            return await ctx.send(f"Command ini hanya bisa digunakan di <#{EVENT_CHANNEL_ID}>.", ephemeral=True)

        if target_user.bot:
            logging.debug("Target is a bot. Cannot force event.")
            return await ctx.send("❌ Tidak bisa memaksakan event ke bot.", ephemeral=True)
        
        guild_id_str = str(ctx.guild.id)
        if str(target_user.id) in self.active_heists.get(guild_id_str, {}) or \
           str(target_user.id) in self.active_fires.get(guild_id_str, {}) or \
           str(ctx.guild.id) in self.active_quizzes: # Cek jika target sedang di heist/fire/quiz
            logging.debug(f"Target {target_user.display_name} is in another active event/quiz. Cannot force heist.")
            return await ctx.send("❌ Pengguna ini atau server ini sedang dalam proses event lain!", ephemeral=True)

        bank_data = load_bank_data()
        target_balance = bank_data.get(str(target_user.id), {}).get("balance", 0)
        if target_balance < LOOT_MIN:
            logging.debug(f"Target {target_user.display_name} has insufficient balance ({target_balance}) for forced heist (min {LOOT_MIN}).")
            return await ctx.send(f"❌ Target terlalu miskin ({target_user.display_name} RSWN), tidak layak dicuri oleh Bot.", ephemeral=True)

        await ctx.send(f"🚨 Admin memicu pencurian pada **{target_user.mention}**!")
        await self._start_heist(ctx.guild, target_user, ctx.channel, initiator=self.bot.user)
        logging.info(f"Forced heist initiated on {target_user.display_name}.")

    @commands.command(name="forcefire") # Command tanpa prefiks rtm
    @commands.has_permissions(administrator=True)
    async def force_fire(self, ctx, target_user: discord.Member):
        logging.info(f"Admin {ctx.author.display_name} forcing fire on {target_user.display_name}.")
        if ctx.channel.id != EVENT_CHANNEL_ID:
            logging.debug(f"Command forcefire used in wrong channel ({ctx.channel.id}). Expected {EVENT_CHANNEL_ID}.")
            return await ctx.send(f"Command ini hanya bisa digunakan di <#{EVENT_CHANNEL_ID}>.", ephemeral=True)

        if target_user.bot:
            logging.debug("Target is a bot. Cannot force event.")
            return await ctx.send("❌ Tidak bisa memaksakan event ke bot.", ephemeral=True)
        
        guild_id_str = str(ctx.guild.id)
        if str(target_user.id) in self.active_heists.get(guild_id_str, {}) or \
           str(target_user.id) in self.active_fires.get(guild_id_str, {}) or \
           str(ctx.guild.id) in self.active_quizzes: # Cek jika target sedang di heist/fire/quiz
            logging.debug(f"Target {target_user.display_name} is in another active event/quiz. Cannot force fire.")
            return await ctx.send("❌ Pengguna ini atau server ini sedang dalam proses event lain!", ephemeral=True)
            
        bank_data = load_bank_data()
        target_balance = bank_data.get(str(target_user.id), {}).get("balance", 0)
        if target_balance < LOOT_MIN:
            logging.debug(f"Target {target_user.display_name} has insufficient balance ({target_balance}) for forced fire (min {LOOT_MIN}).")
            return await ctx.send(f"❌ Target terlalu miskin ({target_user.display_name} RSWN), tidak ada yang bisa dibakar.", ephemeral=True)

        await ctx.send(f"🔥 Admin memicu kebakaran di rumah **{target_user.mention}**!")
        await self._start_fire(ctx.guild, target_user, ctx.channel)
        logging.info(f"Forced fire initiated on {target_user.display_name}.")
        
    @commands.command(name="uangall") # Command tanpa prefiks rtm
    @commands.has_permissions(administrator=True)
    async def give_all_money(self, ctx, amount: int):
        logging.info(f"Admin {ctx.author.display_name} initiating give_all_money: {amount} RSWN.")
        if amount <= 0:
            logging.debug("Give_all_money amount is not positive.")
            return await ctx.send("❌ Jumlah RSWN harus positif.", ephemeral=True)

        await ctx.send(f"💰 Memulai proses pemberian **{amount} RSWN** kepada semua anggota server...")
        
        bank_data = load_bank_data()
        updated_users_count = 0

        for member in ctx.guild.members:
            if member.bot: continue

            user_id_str = str(member.id)
            bank_data.setdefault(user_id_str, {"balance": 0, "debt": 0})["balance"] += amount
            updated_users_count += 1
            logging.debug(f"Gave {amount} RSWN to {member.display_name}.")

        save_bank_data(bank_data)
        logging.info(f"Successfully gave {amount} RSWN to {updated_users_count} users.")
        await ctx.send(f"✅ Berhasil memberikan **{amount} RSWN** kepada **{updated_users_count} anggota** di server ini!")

    @commands.command(name="xpall") # Command tanpa prefiks rtm
    @commands.has_permissions(administrator=True)
    async def give_all_xp(self, ctx, amount: int):
        logging.info(f"Admin {ctx.author.display_name} initiating give_all_xp: {amount} EXP.")
        if amount <= 0:
            logging.debug("Give_all_xp amount is not positive.")
            return await ctx.send("❌ Jumlah EXP harus positif.", ephemeral=True)

        await ctx.send(f"✨ Memulai proses pemberian **{amount} EXP** kepada semua anggota server...")
        
        guild_id_str = str(ctx.guild.id)
        level_data = load_level_data(guild_id_str)
        updated_users_count = 0

        # Ambil cog Leveling untuk update level secara instan
        leveling_cog = self.bot.get_cog('Leveling')

        for member in ctx.guild.members:
            if member.bot: continue

            user_id_str = str(member.id)
            user_level_data = level_data.setdefault(user_id_str, {
                "exp": 0, "level": 0, "weekly_exp": 0, "badges": [], "last_active": None, "booster": {}
            })
            
            old_level = user_level_data.get("level", 0) # Ambil level lama sebelum diubah
            user_level_data["exp"] += amount
            user_level_data["weekly_exp"] += amount
            user_level_data["last_active"] = datetime.utcnow().isoformat()
            
            if leveling_cog: # Jika cog Leveling ditemukan, hitung dan update level
                new_level = leveling_cog.calculate_level(user_level_data["exp"])
                if new_level > old_level:
                    user_level_data["level"] = new_level
                    logging.debug(f"User {member.display_name} leveled up from {old_level} to {new_level} due to give_all_xp.")
                    # Panggil fungsi level_up dari Leveling cog untuk handle role/pengumuman
                    await leveling_cog.level_up(member, ctx.guild, ctx.channel, new_level, level_data)
            updated_users_count += 1

        save_level_data(guild_id_str, level_data)
        logging.info(f"Successfully gave {amount} EXP to {updated_users_count} users.")
        await ctx.send(f"✅ Berhasil memberikan **{amount} EXP** kepada **{updated_users_count} anggota** di server ini!")


    # --- Command untuk Sistem Investasi ---
    current_investment_scheme = {} # State untuk skema investasi aktif

    @commands.command(name="mulaiinvestasi") # Command tanpa prefiks rtm
    @commands.has_role("Pejabat") # Hanya role Pejabat yang bisa memulai
    async def start_investment(self, ctx, min_investors: int, cost_per_investor: int):
        logging.info(f"Pejabat {ctx.author.display_name} starting investment scheme. Min investors: {min_investors}, cost: {cost_per_investor}.")
        if ctx.channel.id != EVENT_CHANNEL_ID:
            logging.debug(f"Command mulaiinvestasi used in wrong channel ({ctx.channel.id}). Expected {EVENT_CHANNEL_ID}.")
            return await ctx.send(f"Command ini hanya bisa digunakan di <#{EVENT_CHANNEL_ID}>.", ephemeral=True)

        guild_id_str = str(ctx.guild.id)
        if guild_id_str in self.current_investment_scheme and self.current_investment_scheme[guild_id_str].get("status") == "open":
            logging.debug(f"Investment scheme already active in guild {ctx.guild.name}.")
            return await ctx.send("❌ Skema investasi sedang berjalan di server ini!", ephemeral=True)
            
        if min_investors < 10:
            logging.debug("Min investors less than 10.")
            return await ctx.send("❌ Minimal investor harus 10 orang.", ephemeral=True)
            
        if cost_per_investor != 500: # Batasi biaya investasi
            logging.debug("Cost per investor is not 500.")
            return await ctx.send("❌ Biaya investasi per pengguna harus **500 RSWN**.", ephemeral=True)

        self.current_investment_scheme[guild_id_str] = {
            "status": "open",
            "min_investors": min_investors,
            "cost_per_investor": cost_per_investor,
            "investors": [], # List of user IDs who invested
            "total_funds": 0,
            "initiator_id": str(ctx.author.id),
            "start_time": datetime.utcnow().isoformat()
        }
        logging.info(f"Investment scheme '{guild_id_str}' initiated.")

        embed = discord.Embed(
            title="🚨 PENGUMUMAN PENTING DARI PEMERINTAH! 🚨",
            description=(
                f"Para pejabat kami membuka skema investasi baru yang sangat menguntungkan (tentunya untuk kami)! "
                f"Minimal **{min_investors} investor** diperlukan, dan setiap investor wajib menyetor **{cost_per_investor} RSWN**!\n\n"
                f"Ketik `!gabunginvestasi` untuk berpartisipasi dan jadi bagian dari 'rakyat kaya'!"
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="Pendaftaran dibuka selama 30 menit atau sampai pejabat menutupnya.")
        await ctx.send(embed=embed)
        
        logging.info(f"Investment scheme '{guild_id_str}' announced.")
        
        # Timer untuk menutup pendaftaran otomatis
        await asyncio.sleep(30 * 60) # Tunggu 30 menit
        
        # Cek apakah skema masih terbuka dan belum mencapai minimal investor
        if guild_id_str in self.current_investment_scheme and self.current_investment_scheme[guild_id_str].get("status") == "open":
            if len(self.current_investment_scheme[guild_id_str]["investors"]) < min_investors:
                logging.info(f"Investment scheme '{guild_id_str}' failed due to insufficient investors. Forcing failure.")
                await ctx.send(f"❌ Pendaftaran investasi ditutup karena tidak mencapai minimal investor (**{min_investors}**). Dana akan dikembalikan ke yang sudah daftar.", ephemeral=False)
                await self._resolve_investment(ctx.guild, ctx.channel, force_failure=True)
            elif len(self.current_investment_scheme[guild_id_str]["investors"]) >= min_investors:
                await ctx.send("🔔 Pendaftaran investasi otomatis ditutup karena waktu habis. Memulai proses hasil investasi.", ephemeral=False)
                self.current_investment_scheme[guild_id_str]["status"] = "closed" # Tandai sebagai ditutup
                await asyncio.sleep(random.randint(60*5, 60*60*2)) # Tunggu 5 menit - 2 jam sebelum hasil
                await self._resolve_investment(ctx.guild, ctx.channel)


    @commands.command(name="gabunginvestasi") # Command tanpa prefiks rtm
    async def join_investment(self, ctx):
        logging.info(f"User {ctx.author.display_name} trying to join investment.")
        if ctx.channel.id != EVENT_CHANNEL_ID:
            logging.debug(f"Command gabunginvestasi used in wrong channel ({ctx.channel.id}). Expected {EVENT_CHANNEL_ID}.")
            return await ctx.send(f"Command ini hanya bisa digunakan di <#{EVENT_CHANNEL_ID}>.", ephemeral=True)

        guild_id_str = str(ctx.guild.id)
        user_id_str = str(ctx.author.id)

        if guild_id_str not in self.current_investment_scheme or self.current_investment_scheme[guild_id_str].get("status") != "open":
            logging.debug("No open investment scheme found.")
            return await ctx.send("❌ Saat ini tidak ada skema investasi yang dibuka.", ephemeral=True)
            
        if user_id_str in self.current_investment_scheme[guild_id_str]["investors"]:
            logging.debug(f"User {ctx.author.display_name} already joined investment.")
            return await ctx.send("❌ Kamu sudah bergabung dalam skema investasi ini.", ephemeral=True)

        bank_data = load_bank_data()
        cost = self.current_investment_scheme[guild_id_str]["cost_per_investor"]
        
        if bank_data.get(user_id_str, {}).get("balance", 0) < cost:
            logging.debug(f"User {ctx.author.display_name} insufficient balance ({bank_data.get(user_id_str, {}).get('balance', 0)}) for investment cost ({cost}).")
            return await ctx.send(f"❌ Saldo RSWN-mu tidak cukup. Kamu butuh **{cost} RSWN** untuk bergabung.", ephemeral=True)
            
        bank_data.setdefault(user_id_str, {"balance":0, "debt":0})["balance"] -= cost
        save_bank_data(bank_data)
        logging.info(f"Deducted {cost} RSWN from {ctx.author.display_name} for investment. New balance: {bank_data[user_id_str]['balance']}.")

        self.current_investment_scheme[guild_id_str]["investors"].append(user_id_str)
        self.current_investment_scheme[guild_id_str]["total_funds"] += cost
        logging.debug(f"User {ctx.author.display_name} added to investment. Total funds: {self.current_investment_scheme[guild_id_str]['total_funds']}.")

        await ctx.send(f"✅ **{ctx.author.display_name}**, investasi Anda sebesar **{cost} RSWN** telah diterima! Menunggu investor lain. (**{len(self.current_investment_scheme[guild_id_str]['investors'])}/{self.current_investment_scheme[guild_id_str]['min_investors']}** investor)", ephemeral=False)

        if len(self.current_investment_scheme[guild_id_str]["investors"]) >= self.current_investment_scheme[guild_id_str]["min_investors"]:
            initiator_id = self.current_investment_scheme[guild_id_str]["initiator_id"]
            initiator = ctx.guild.get_member(int(initiator_id))
            if initiator:
                try: await initiator.send(f"🎉 **Skema Investasi di {ctx.guild.name} telah mencapai minimal investor!** Anda bisa menutup pendaftaran dengan `!tutupinvestasi`.")
                except discord.Forbidden: logging.warning(f"Could not send investment min investors DM to initiator {initiator.display_name} (DMs closed).")


    @commands.command(name="tutupinvestasi") # Command tanpa prefiks rtm
    @commands.has_role("Pejabat")
    async def close_investment(self, ctx):
        logging.info(f"Pejabat {ctx.author.display_name} trying to close investment scheme.")
        if ctx.channel.id != EVENT_CHANNEL_ID:
            logging.debug(f"Command tutupinvestasi used in wrong channel ({ctx.channel.id}). Expected {EVENT_CHANNEL_ID}.")
            return await ctx.send(f"Command ini hanya bisa digunakan di <#{EVENT_CHANNEL_ID}>.", ephemeral=True)

        guild_id_str = str(ctx.guild.id)
        if guild_id_str not in self.current_investment_scheme or self.current_investment_scheme[guild_id_str].get("status") != "open":
            logging.debug("No open investment scheme found to close.")
            return await ctx.send("❌ Tidak ada skema investasi yang sedang dibuka.", ephemeral=True)
            
        if str(ctx.author.id) != self.current_investment_scheme[guild_id_str]["initiator_id"]:
            logging.warning(f"User {ctx.author.display_name} tried to close investment but is not the initiator.")
            return await ctx.send("❌ Hanya pejabat yang memulai skema ini yang bisa menutupnya.", ephemeral=True)

        if len(self.current_investment_scheme[guild_id_str]["investors"]) < self.current_investment_scheme[guild_id_str]["min_investors"]:
            logging.debug(f"Investment scheme not enough investors to close ({len(self.current_investment_scheme[guild_id_str]['investors'])}/{self.current_investment_scheme[guild_id_str]['min_investors']}).")
            return await ctx.send(f"❌ Skema investasi belum mencapai minimal **{self.current_investment_scheme[guild_id_str]['min_investors']} investor** untuk ditutup. Batalkan atau tunggu!", ephemeral=True)
            
        self.current_investment_scheme[guild_id_str]["status"] = "closed"
        logging.info(f"Investment scheme '{guild_id_str}' closed by {ctx.author.display_name}. Total funds: {self.current_investment_scheme[guild_id_str]['total_funds']}.")

        embed = discord.Embed(
            title="💼 INVESTASI DITUTUP! 💼",
            description=(
                f"Dengan **{len(self.current_investment_scheme[guild_id_str]['investors'])} investor** dan total dana terkumpul **{self.current_investment_scheme[guild_id_str]['total_funds']} RSWN**, "
                f"kami akan segera memproses investasi ini. Pejabat kami akan bekerja keras (atau santai-santai) untuk menggandakan uang Anda! Ditunggu hasil laporannya ya...🤫"
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="Hasil akan diumumkan nanti. Semoga cuan!")
        await ctx.send(embed=embed)
        
        logging.info(f"Investment scheme '{guild_id_str}' closed. Scheduling resolution.")
        await asyncio.sleep(random.randint(60*5, 60*60*2))
        await self._resolve_investment(ctx.guild, ctx.channel)

    async def _resolve_investment(self, guild: discord.Guild, channel: discord.TextChannel, force_failure: bool = False):
        logging.info(f"Resolving investment scheme for guild {guild.name}. Forced failure: {force_failure}.")
        guild_id_str = str(guild.id)
        
        if guild_id_str not in self.current_investment_scheme:  
            logging.warning(f"Investment scheme for guild {guild.name} not found for resolution.")
            return
        
        scheme_info = self.current_investment_scheme[guild_id_str]
        initiator_id = scheme_info["initiator_id"]
        investors = scheme_info["investors"]
        total_funds = scheme_info["total_funds"]
        
        self.current_investment_scheme.pop(guild_id_str) # Hapus skema setelah diambil datanya
        logging.debug(f"Investment scheme '{guild_id_str}' removed from active list.")

        success_chance = 0.70 # 70% peluang sukses jika tidak dipaksa gagal
        is_success = random.random() < success_chance and not force_failure
        
        if is_success:
            logging.info(f"Investment scheme for guild {guild.name} was successful.")
            profit_percentage = random.uniform(0.10, 0.50) # Keuntungan 10-50%
            total_profit = int(total_funds * profit_percentage)
            total_return_to_distribute = total_funds + total_profit
            
            embed_title = "🎉 BERITA GEMBIRA! INVESTASI SUKSES BESAR! 🎉"
            embed_desc = (
                f"Berkat kebijaksanaan pejabat kami, dana Anda berlipat ganda!\n"
                f"Total dana terkumpul: **{total_funds} RSWN**\n"
                f"Total keuntungan: **{total_profit} RSWN**\n\n"
                f"Setiap investor mendapatkan bagiannya!"
            )
            embed_color = discord.Color.green()

            initiator_member = guild.get_member(int(initiator_id))
            if initiator_member:
                logging.info(f"Offering corruption chance to initiator {initiator_member.display_name}.")
                corruption_offer_msg = await initiator_member.send(
                    f"**Pejabat PajakBot:** 'Wahai Pejabat **{initiator_member.display_name}**, sini sebentar. Investasi kita sukses besar! Apakah Anda ingin 'mengamankan' sebagian dana ini untuk 'operasional rahasia negara'? Ketik `!korupsi <jumlah>` dalam **60 detik** untuk ambil bagianmu, atau ketik `!tidakkorupsi`."
                )
                
                def check_corruption_response(m):
                    return m.author.id == initiator_member.id and m.channel == initiator_member.dm_channel and (m.content.lower().startswith("!korupsi") or m.content.lower() == "!tidakkorupsi")

                try:
                    msg = await self.bot.wait_for('message', check=check_corruption_response, timeout=60.0)
                    if msg.content.lower().startswith("!korupsi"):
                        try:
                            corrupt_amount = int(msg.content.lower().split()[1])
                            if corrupt_amount <= 0 or corrupt_amount > total_profit:
                                logging.warning(f"Invalid corruption amount {corrupt_amount} from {initiator_member.display_name}. Considered not corrupt.")
                                await initiator_member.send("Jumlah korupsi tidak valid atau melebihi keuntungan. Anda dianggap tidak korupsi.")
                                corrupt_amount = 0 # Set to 0 if invalid
                            
                            if corrupt_amount > 0:
                                logging.info(f"Pejabat {initiator_member.display_name} attempted to corrupt {corrupt_amount} RSWN.")
                                if random.random() < 0.30: # 30% chance to be caught
                                    logging.info(f"Corruption attempt by {initiator_member.display_name} DETECTED.")
                                    await channel.send(f"🚨 **SKANDAL TERKUAK! PEJABAT {initiator_member.mention} TERTANGKAP KORUPSI!**")
                                    penalty_percentage = 0.25 # Denda 25% dari jumlah yang mau dikorupsi
                                    penalty_amount = int(corrupt_amount * penalty_percentage)
                                    bank_data_temp = load_bank_data() # Muat ulang untuk data terbaru
                                    current_initiator_balance = bank_data_temp.get(str(initiator_id), {}).get("balance", 0)
                                    
                                    actual_penalty = min(penalty_amount, current_initiator_balance) # Tidak bisa denda lebih dari saldo
                                    bank_data_temp.setdefault(str(initiator_id), {})["balance"] -= actual_penalty
                                    save_bank_data(bank_data_temp)
                                    logging.info(f"Pejabat {initiator_member.display_name} penalized {actual_penalty} RSWN. New balance: {bank_data_temp[str(initiator_id)]['balance']}.")

                                    if investors:
                                        penalty_per_investor = actual_penalty // len(investors) if len(investors) > 0 else 0
                                        if penalty_per_investor > 0:
                                            for inv_id in investors:
                                                bank_data_dist = load_bank_data() # Muat ulang untuk distribusi
                                                bank_data_dist.setdefault(str(inv_id), {})["balance"] += penalty_per_investor
                                                save_bank_data(bank_data_dist)
                                                investor_user = guild.get_member(int(inv_id))
                                                if investor_user:
                                                    try: await investor_user.send(f"🎉 **Selamat!** Anda mendapatkan **{penalty_per_investor} RSWN** dari denda korupsi pejabat!")
                                                    except discord.Forbidden: pass
                                            logging.info(f"Distributed {actual_penalty} penalty RSWN among {len(investors)} investors.")
                                            await channel.send(f"🎉 **{actual_penalty} RSWN** telah disita dari {initiator_member.mention} dan dibagikan ke para investor!")
                                        else:
                                            logging.debug("Penalty too small to distribute among investors.")
                                            await channel.send("Audit menemukan korupsi, tapi jumlahnya terlalu kecil untuk dibagikan. Pejabat sudah menerima sanksi moral!")
                                    
                                    try: await initiator_member.send(f"💔 Anda ketahuan korupsi sebesar **{corrupt_amount} RSWN**! Anda didenda **{penalty_amount} RSWN** yang dibagikan ke investor. Malu! 😱")
                                    except discord.Forbidden: logging.warning(f"Could not send corruption penalty DM to {initiator_member.display_name} (DMs closed).")
                                else: # Tidak tertangkap
                                    logging.info(f"Corruption attempt by {initiator_member.display_name} NOT DETECTED. {corrupt_amount} RSWN secured.")
                                    try: await initiator_member.send(f"✅ Anda berhasil 'mengamankan' **{corrupt_amount} RSWN**! Diam-diam saja ya! 😈")
                                    except discord.Forbidden: logging.warning(f"Could not send corruption success DM to {initiator_member.display_name} (DMs closed).")
                                    bank_data_temp = load_bank_data()
                                    bank_data_temp.setdefault(str(initiator_id), {})["balance"] += corrupt_amount
                                    save_bank_data(bank_data_temp)
                                    logging.debug(f"Pejabat {initiator_member.display_name}'s new balance: {bank_data_temp[str(initiator_id)]['balance']}.")
                                    
                                    total_return_to_distribute -= corrupt_amount # Kurangi dari yang akan didistribusikan ke investor
                                    if total_return_to_distribute < 0: total_return_to_distribute = 0 # Pastikan tidak negatif
                        except ValueError:
                            logging.warning(f"Invalid input for corruption amount from {initiator_member.display_name}.")
                            try: await initiator_member.send("Jumlah korupsi tidak valid. Anda dianggap tidak korupsi.")
                            except discord.Forbidden: pass
                        except Exception as e:
                            logging.error(f"Error during corruption attempt by {initiator_member.display_name}: {e}", exc_info=True)
                            try: await initiator_member.send("Terjadi kesalahan saat memproses korupsi.")
                            except discord.Forbidden: pass
                    elif msg.content.lower() == "!tidakkorupsi":
                        logging.info(f"Pejabat {initiator_member.display_name} chose not to corrupt.")
                        try: await initiator_member.send("👍 Anda memilih untuk tetap jujur! Salut!")
                        except discord.Forbidden: pass
                except asyncio.TimeoutError:
                    logging.info(f"Pejabat {initiator_member.display_name} did not respond to corruption offer. Considered not corrupt.")
                    try: await initiator_member.send("Waktu habis! Anda dianggap tidak korupsi.")
                    except discord.Forbidden: pass
                finally:
                    try: await corruption_offer_msg.delete()
                    except (discord.NotFound, discord.HTTPException): pass

            if investors:
                if total_return_to_distribute < 0: total_return_to_distribute = 0
                
                profit_per_investor = total_return_to_distribute // len(investors) if len(investors) > 0 else 0
                if profit_per_investor > 0:
                    for inv_id in investors:
                        bank_data_temp = load_bank_data() # Muat ulang untuk distribusi
                        bank_data_temp.setdefault(str(inv_id), {})["balance"] += profit_per_investor
                        save_bank_data(bank_data_temp)
                        investor_user = guild.get_member(int(inv_id))
                        if investor_user:
                            try: await investor_user.send(f"🎉 Investasi sukses! Anda mendapatkan **{profit_per_investor} RSWN** dari keuntungan!")
                            except discord.Forbidden: pass
                    logging.info(f"Distributed {profit_per_investor} RSWN per investor to {len(investors)} investors.")
                    await channel.send(f"🎉 **{total_return_to_distribute} RSWN** telah didistribusikan ke **{len(investors)} investor**!")
                else: # Keuntungan terlalu kecil atau tidak ada
                    logging.info("Profit too small or zero for investors.")
                    await channel.send("Investasi sukses, tetapi keuntungan terlalu kecil untuk dibagikan secara adil. Modal awal dikembalikan ke investor.")
                    # Kembalikan modal awal ke investor jika keuntungan 0 atau negatif
                    for inv_id in investors:
                        bank_data_temp = load_bank_data()
                        cost_returned = scheme_info["cost_per_investor"]
                        bank_data_temp.setdefault(str(inv_id), {})["balance"] += cost_returned
                        save_bank_data(bank_data_temp)
                        investor_user = guild.get_member(int(inv_id))
                        if investor_user:
                            try: await investor_user.send(f"Investasi sukses, tetapi keuntungan terlalu kecil untuk dibagikan secara adil. Anda hanya mendapatkan kembali modal awal Anda ({cost_returned} RSWN).")
                            except discord.Forbidden: pass
            
            await channel.send(embed=discord.Embed(title=embed_title, description=embed_desc, color=embed_color))
            logging.info(f"Investment successful result announced for guild {guild.name}.")

        else: # Gagal (atau dipaksa gagal)
            logging.info(f"Investment scheme for guild {guild.name} failed.")
            return_percentage = 0.50 # Modal kembali 50%
            total_return = int(total_funds * return_percentage)
            
            embed_title = "💔 BERITA BURUK! INVESTASI GAGAL! 💔"
            embed_desc = (
                f"Maaf, dana Anda tidak berkembang. Pasar sedang tidak bersahabat, atau mungkin kami salah perhitungan.\n"
                f"Total dana terkumpul: **{total_funds} RSWN**\n"
                f"Modal yang dikembalikan: **{total_return} RSWN**\n\n"
                f"Pejabat kami mohon maaf dan berjanji akan lebih 'rajin' di investasi berikutnya! 😉"
            )
            embed_color = discord.Color.red()

            if investors:
                return_per_investor = total_return // len(investors) if len(investors) > 0 else 0
                if return_per_investor > 0:
                    for inv_id in investors:
                        bank_data_temp = load_bank_data() # Muat ulang untuk distribusi
                        bank_data_temp.setdefault(str(inv_id), {})["balance"] += return_per_investor
                        save_bank_data(bank_data_temp)
                        investor_user = guild.get_member(int(inv_id))
                        if investor_user:
                            try: await investor_user.send(f"Investasi gagal. Modal Anda dikembalikan sebesar **{return_per_investor} RSWN**.")
                            except discord.Forbidden: pass
                    logging.info(f"Distributed {return_per_investor} RSWN per investor as partial return to {len(investors)} investors.")
                else: # Pengembalian terlalu kecil atau nol
                    logging.info("Partial return too small or zero for investors.")
                    await channel.send("Investasi gagal total! Modal Anda tidak dapat dikembalikan. Semoga beruntung di lain waktu!")
                    for inv_id in investors:
                        investor_user = guild.get_member(int(inv_id))
                        if investor_user:
                            try: await investor_user.send(f"Investasi gagal total! Modal Anda tidak dapat dikembalikan. Semoga beruntung di lain waktu!")
                            except discord.Forbidden: pass
            
            await channel.send(embed=discord.Embed(title=embed_title, description=embed_desc, color=embed_color))
            logging.info(f"Investment failed result announced for guild {guild.name}.")

    @commands.command(name="audit") # Command tanpa prefiks rtm
    @commands.has_permissions(administrator=True)
    async def audit_command(self, ctx):
        logging.info(f"Admin {ctx.author.display_name} used !audit.")
        # Ambil data ekonomi
        eco_config = load_economy_config()
        server_funds = eco_config.get("server_funds_balance", 0)
        global_tax_percentage = eco_config.get("global_tax_percentage", 0)
        last_tax_run = eco_config.get("last_tax_run", "Belum pernah")

        # Ambil data proyek aktif
        active_projects = load_project_data()
        current_project_info = active_projects.get(str(ctx.guild.id))

        embed = discord.Embed(
            title="📊 Laporan Audit Keuangan Pemerintah",
            description="Laporan transparansi keuangan dan proyek-proyek yang ada (atau pernah ada).",
            color=discord.Color.blue()
        )

        embed.add_field(name="💰 Dana Kas Negara (Server Funds)", value=f"Total: **{server_funds:,} RSWN**", inline=False)
        embed.add_field(name="🏛️ Pajak Global", value=f"Persentase: **{global_tax_percentage}%**\nTerakhir dipungut: {last_tax_run}", inline=False)

        if current_project_info:
            embed.add_field(
                name="🚧 Proyek Ngawur Aktif",
                value=f"Nama: **{current_project_info.get('name', 'N/A')}**\n"
                      f"Status: **{current_project_info.get('status', 'N/A').upper()}**\n"
                      f"Dana Terkumpul: **{current_project_info.get('collected_funds', 0):,} RSWN**",
                inline=False
            )
        else:
            embed.add_field(name="🚧 Proyek Ngawur Aktif", value="Tidak ada proyek ngawur yang sedang berjalan.", inline=False)
        
        # Bisa tambahkan detail lain seperti total dana di bank_data, total EXP, dll.
        # bank_data = load_bank_data()
        # total_rswn_users = sum(d.get('balance', 0) for d in bank_data.values())
        # embed.add_field(name="Total RSWN di Tangan Rakyat", value=f"{total_rswn_users:,} RSWN", inline=False)

        embed.set_footer(text=f"Laporan per: {datetime.now().strftime('%d-%m-%Y %H:%M WIB')}")
        await ctx.send(embed=embed)
        logging.info(f"Audit report sent to {ctx.author.display_name}.")
        
    @commands.command(name="hina") # Command tanpa prefiks rtm
    @commands.has_permissions(administrator=True)
    async def hina_user(self, ctx, target_user: discord.Member, *, custom_insult: str = None):
        logging.info(f"Admin {ctx.author.display_name} used !hina on {target_user.display_name}.")
        try:
            await ctx.message.delete()
            logging.debug("Deleted !hina command message.")
        except discord.HTTPException:
            logging.warning("Failed to delete !hina command message.")
            pass

        if target_user.bot:
            logging.debug("Target is a bot. Cannot insult.")
            return await ctx.send("❌ Kamu tidak bisa menghina bot! Mereka terlalu canggih untuk dihina.", ephemeral=True)

        if custom_insult:
            final_insult = f"Perhatian rakyat! Pesan khusus untuk **{target_user.mention}**: {custom_insult}"
            logging.info(f"Used custom insult for {target_user.display_name}: '{custom_insult}'.")
        else:
            insult_message = random.choice(self.special_insults)
            final_insult = insult_message.replace("{user_mention}", target_user.mention)
            logging.info(f"Used random insult for {target_user.display_name}: '{insult_message}'.")

        embed = discord.Embed(
            title="🎤 Pengumuman Penting dari Pemerintah!",
            description=final_insult,
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Pesan ini disampaikan langsung oleh Pejabat PajakBot.")
        
        await ctx.send(embed=embed)
        logging.info(f"Sent insult message for {target_user.display_name}.")

    @commands.command(name="bantuan") # Command tanpa prefiks rtm
    @commands.has_permissions(administrator=True)
    async def mysterious_aid(self, ctx, amount: int = 0, target_user: discord.Member = None):
        logging.info(f"Admin {ctx.author.display_name} used !bantuan. Amount: {amount}, Target: {target_user.display_name if target_user else 'random'}.")
        
        if amount < 0: # Jumlah harus positif atau 0 (untuk random)
             logging.debug("Amount not positive.")
             return await ctx.send("❌ Jumlah bantuan harus positif atau 0 (jika targetnya acak).", ephemeral=True)

        if amount == 0 and target_user: # Jika jumlah 0 tapi target spesifik
            logging.debug("Amount is 0 for specific target. Invalid input.")
            return await ctx.send("❌ Jumlah bantuan harus positif jika diberikan ke target spesifik.", ephemeral=True)

        if amount > 0 and not target_user: # Jika ada jumlah tapi target acak belum ditentukan, akan dipilih secara acak
            logging.debug("Amount is positive for random target. Will proceed with fixed amount for random user.")
            
        if ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            try: await ctx.message.delete()
            except discord.HTTPException: pass

        bank_data = load_bank_data()
        
        chosen_user = None
        aid_amount = 0

        if target_user:
            chosen_user = target_user
            aid_amount = amount
            logging.debug(f"Assigned specific aid {aid_amount} to {chosen_user.display_name}.")
        else:
            active_users = [m for m in ctx.guild.members if not m.bot]
            if not active_users:
                logging.warning("No active users found for random aid distribution.")
                return await ctx.send("❌ Tidak ada pengguna aktif untuk diberi dana bantuan.", ephemeral=True)
            chosen_user = random.choice(active_users)
            aid_amount = random.randint(MYSTERIOUS_AID_MIN, MYSTERIOUS_AID_MAX) # Ambil acak dari rentang
            logging.debug(f"Assigned random aid {aid_amount} to {chosen_user.display_name}.")

        user_id_str = str(chosen_user.id)
        bank_data.setdefault(user_id_str, {"balance": 0, "debt": 0})["balance"] += aid_amount
        save_bank_data(bank_data)
        logging.info(f"Gave {aid_amount} RSWN mysterious aid to {chosen_user.display_name}. New balance: {bank_data[user_id_str]['balance']}.")

        narration = (
            f"TRANSFER MISTERIUS: Selamat, **{chosen_user.mention}**! Anda baru saja menerima transfer dana sebesar **{aid_amount} RSWN**! "
            f"Sumber dana tidak diketahui, sepertinya ini hasil 'dana aspirasi' yang salah alamat atau mungkin bagian dari 'uang pelicin' proyek yang bocor. "
            f"Anggap saja rezeki nomplok ya, jangan banyak tanya!🤫"
        )
        
        embed = discord.Embed(
            title="💸 Dana Bantuan Misterius Tiba! 💸",
            description=narration,
            color=discord.Color.dark_teal()
        )
        embed.set_footer(text="Dari pemerintah yang peduli (tapi rahasia).")
        
        await ctx.send(embed=embed)
        logging.info(f"Mysterious aid announced for {chosen_user.display_name}.")

    # --- Implementasi Kuis Kebobrokan Pemerintah ---
    async def _start_quiz_session(self, guild: discord.Guild, channel: discord.TextChannel):
        logging.info(f"Starting quiz session in guild {guild.name}.")
        guild_id_str = str(guild.id)
        
        if guild_id_str in self.active_quizzes:
            logging.debug(f"Quiz already active in guild {guild.name}.")
            return # Quiz sudah aktif, jangan mulai lagi

        questions_data = load_trivia_questions()
        if not questions_data.get("questions"):
            logging.warning("Trivia questions bank is empty for quiz session.")
            return # Tidak ada soal

        if len(questions_data["questions"]) < QUIZ_TOTAL_QUESTIONS:
            logging.warning(f"Not enough trivia questions ({len(questions_data['questions'])}) for a session of {QUIZ_TOTAL_QUESTIONS} questions.")
            return # Soal tidak cukup

        quiz_questions = random.sample(questions_data["questions"], QUIZ_TOTAL_QUESTIONS)
        
        self.active_quizzes[guild_id_str] = {
            "current_question_idx": 0,
            "questions_list": quiz_questions,
            "score_board": {}, # {user_id: score}
            "channel_id": channel.id,
            "question_message": None, # Pesan pertanyaan yang sedang aktif
            "responded_to_current": False # Flag untuk memastikan hanya satu jawaban yang diproses per pertanyaan
        }
        logging.info(f"New quiz session state created for guild {guild.name}.")
        
        await self._start_next_quiz_question(guild, channel)

    @commands.command(name="kuisbobrok") # Command tanpa prefiks rtm
    async def start_trivia_session_cmd(self, ctx):
        logging.info(f"Command !kuisbobrok used by {ctx.author.display_name}.")
        if ctx.channel.id != EVENT_CHANNEL_ID:
            logging.debug(f"Command kuisbobrok used in wrong channel ({ctx.channel.id}). Expected {EVENT_CHANNEL_ID}.")
            return await ctx.send(f"Command ini hanya bisa digunakan di <#{EVENT_CHANNEL_ID}>.", ephemeral=True)

        guild_id_str = str(ctx.guild.id)
        if guild_id_str in self.active_quizzes:
            logging.debug(f"Quiz already active in guild {ctx.guild.name}.")
            return await ctx.send("❌ Kuis sedang aktif di server ini! Harap tunggu hingga selesai.", ephemeral=True)
            
        questions_data = load_trivia_questions()
        if not questions_data.get("questions"):
            logging.warning("Trivia questions bank is empty.")
            return await ctx.send("❌ Bank soal kuis kebobrokan masih kosong! Admin perlu menambahkannya dengan `!addsoal`.", ephemeral=True)

        if len(questions_data["questions"]) < QUIZ_TOTAL_QUESTIONS:
            logging.warning(f"Not enough trivia questions ({len(questions_data['questions'])}) for a session of {QUIZ_TOTAL_QUESTIONS} questions.")
            return await ctx.send(f"❌ Bank soal kuis kebobrokan hanya memiliki {len(questions_data['questions'])} soal. Perlu minimal {QUIZ_TOTAL_QUESTIONS} soal untuk memulai sesi.", ephemeral=True)

        # Mulai sesi kuis
        await ctx.send("📢 Kuis Kebobrokan Pemerintah akan segera dimulai! Bersiaplah menguji pemahamanmu!")
        await self._start_quiz_session(ctx.guild, ctx.channel)
        logging.info(f"Manual start quiz session by {ctx.author.display_name} in guild {ctx.guild.name}.")

    async def _start_next_quiz_question(self, guild: discord.Guild, channel: discord.TextChannel):
        guild_id_str = str(guild.id)
        quiz_session = self.active_quizzes.get(guild_id_str)
        if not quiz_session:
            logging.debug(f"No active quiz session for guild {guild.name}. Stopping quiz loop.")
            return

        current_idx = quiz_session["current_question_idx"]
        questions_list = quiz_session["questions_list"]

        if current_idx >= len(questions_list):
            logging.info(f"Quiz session finished for guild {guild.name}. All {QUIZ_TOTAL_QUESTIONS} questions answered.")
            await self._end_quiz_session(guild, channel)
            return

        question_info = questions_list[current_idx]
        
        quiz_opener = (
            f"**Pejabat Penguji Kebobrokan:** 'Selamat datang, warga! Mari kita uji seberapa dalam pemahaman Anda tentang 'seluk-beluk' pemerintahan kami. Jika Anda terlalu jujur, bisa jadi Anda kena sanksi! Hahaha! *suara batuk-batuk uang*' 💰"
        )
        
        embed = discord.Embed(
            title=f"🎤 Kuis Kebobrokan Pemerintah! (Soal {current_idx + 1}/{QUIZ_TOTAL_QUESTIONS}) 🕵️‍♂️",
            description=f"{quiz_opener}\n\n**Pertanyaan:**\n{question_info['question']}",
            color=discord.Color.dark_red()
        )
        if question_info.get("options"):
            # Format opsi jawaban dengan huruf A, B, C, D
            options_text = "\n".join([f"{chr(65+i)}. {option}" for i, option in enumerate(question_info["options"])])
            embed.add_field(name="Pilihan Jawaban", value=options_text, inline=False)
        embed.set_footer(text=f"Jawab dalam {QUIZ_QUESTION_TIME} detik! Siapa cepat dia dapat!")

        try:
            quiz_session["question_message"] = await channel.send(embed=embed)
            quiz_session["responded_to_current"] = False # Reset flag jawaban untuk pertanyaan baru
            logging.debug(f"Question {current_idx + 1} sent to channel {channel.name}.")
        except Exception as e:
            logging.error(f"Failed to send quiz question to channel {channel.name}: {e}", exc_info=True)
            await channel.send(f"❌ Terjadi kesalahan saat mengirim pertanyaan kuis: `{e}`. Sesi dihentikan.")
            await self._end_quiz_session(guild, channel) # Akhiri sesi jika ada masalah pengiriman pertanyaan
            return

        # Tunggu waktu pertanyaan habis atau jawaban masuk
        await asyncio.sleep(QUIZ_QUESTION_TIME)
        
        if not quiz_session["responded_to_current"]: # Jika tidak ada yang menjawab dengan benar atau waktu habis
            logging.info(f"Question {current_idx + 1} for guild {guild.name} timed out. No correct answer.")
            
            bank_data = load_bank_data()
            for member in guild.members:
                if member.bot: continue # Abaikan bot
                # Hanya denda user yang punya saldo cukup
                member_id_str = str(member.id)
                current_balance = bank_data.get(member_id_str, {}).get("balance", 0)
                if current_balance >= QUIZ_PENALTY:
                    bank_data.setdefault(member_id_str, {"balance":0, "debt":0})["balance"] -= QUIZ_PENALTY
            save_bank_data(bank_data)
            logging.info(f"Penalty of {QUIZ_PENALTY} RSWN applied to users with sufficient funds for timed out quiz question {current_idx + 1}.")
            
            await channel.send(f"⏱️ Waktu untuk soal {current_idx + 1} habis! Jawaban yang benar adalah: **{question_info['answer']}**. Denda otomatis **{QUIZ_PENALTY} RSWN** bagi yang punya uang karena tidak berpartisipasi! 😂", delete_after=15)
            
            if quiz_session["question_message"]:
                try: await quiz_session["question_message"].delete()
                except discord.HTTPException: pass

            quiz_session["current_question_idx"] += 1
            await asyncio.sleep(2) # Jeda singkat sebelum pertanyaan berikutnya
            await self._start_next_quiz_question(guild, channel)


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
            
        guild_id_str = str(message.guild.id)
        if guild_id_str not in self.active_quizzes:
            return # Tidak ada kuis aktif di guild ini

        quiz_session = self.active_quizzes[guild_id_str]
        if message.channel.id != quiz_session["channel_id"]:
            return # Pesan bukan di channel kuis yang aktif

        if quiz_session["responded_to_current"]:
            logging.debug(f"Message from {message.author.display_name} ignored, question already answered.")
            return # Pertanyaan sudah dijawab, abaikan pesan lain

        question_info = quiz_session["questions_list"][quiz_session["current_question_idx"]]
        user_answer = message.content.strip()
        correct_answer = question_info["answer"].strip()
        
        is_correct = False
        if question_info["type"] == "multiple_choice":
            # Periksa jawaban berdasarkan huruf opsi (A, B, C, D) atau teks lengkap
            # Asumsi correct_answer di JSON adalah huruf opsi (misal "A", "B")
            if user_answer.lower() == correct_answer.lower():
                is_correct = True
            elif len(user_answer) == 1 and user_answer.upper() in [chr(65+i) for i in range(len(question_info["options"]))]:
                if user_answer.upper() == correct_answer.upper():
                    is_correct = True
        else: # Tipe 'essay'
            is_correct = user_answer.lower() == correct_answer.lower()

        if is_correct:
            quiz_session["responded_to_current"] = True # Set flag agar tidak ada jawaban lain yang masuk
            
            reward = random.randint(QUIZ_REWARD_MIN, QUIZ_REWARD_MAX)
            corruption_text = ""
            if reward > (QUIZ_REWARD_MAX * 0.8) and random.random() < CORRUPTION_CHANCE_HIGH_REWARD: # Peluang korupsi jika hadiah besar
                corrupted_amount = int(reward * random.uniform(0.1, 0.4)) # Ambil 10-40% dari hadiah
                reward -= corrupted_amount
                corruption_text = f"\n\n*(Catatan dari Pejabat PajakBot: Sebagian kecil hadiah Anda ({corrupted_amount} RSWN) terpaksa kami 'amankan' untuk 'dana operasional mendesak' para pejabat. Jangan protes, ini demi negara, kok!)* 😈"
                
                config = load_economy_config()
                config["server_funds_balance"] += corrupted_amount
                save_economy_config(config)
                logging.info(f"Corruption: {corrupted_amount} RSWN taken from {message.author.display_name}'s quiz reward.")

            bank_data = load_bank_data()
            user_id_str = str(message.author.id)
            bank_data.setdefault(user_id_str, {"balance":0, "debt":0})["balance"] += reward
            save_bank_data(bank_data)
            logging.info(f"User {message.author.display_name} answered correctly. Gained {reward} RSWN. New balance: {bank_data[user_id_str]['balance']}.")

            quiz_session["score_board"].setdefault(user_id_str, 0)
            quiz_session["score_board"][user_id_str] += 1
            
            result_embed_title = "🎉 BENAR! Anda Jenius Bobrok! 🎉"
            result_embed_desc = f"{message.author.mention}, {question_info['correct_response']}\nAnda mendapatkan **{reward} RSWN**!{corruption_text}"
            result_embed_color = discord.Color.green()
            
        else: # Jawaban salah
            user_balance = load_bank_data().get(str(message.author.id), {}).get("balance", 0)
            
            result_embed_title = "💔 SALAH! Anda Terlalu Jujur! 💔"
            result_embed_desc = f"{message.author.mention}, {question_info['wrong_response']}\nJawaban yang benar adalah: **{question_info['answer']}**."
            result_embed_color = discord.Color.red()
            
            if user_balance >= QUIZ_PENALTY:
                bank_data = load_bank_data()
                bank_data.setdefault(user_id_str, {"balance":0, "debt":0})["balance"] -= QUIZ_PENALTY
                save_bank_data(bank_data)
                result_embed_desc += f"\nAnda didenda **{QUIZ_PENALTY} RSWN** karena 'gagal memahami sistem'!"
                logging.info(f"User {message.author.display_name} answered incorrectly. Penalized {QUIZ_PENALTY} RSWN. New balance: {bank_data[user_id_str]['balance']}.")
            else:
                result_embed_desc += "\nAnda lolos denda karena dompet Anda sudah dihisap habis oleh birokrasi sebelumnya. Syukurlah!"
                logging.info(f"User {message.author.display_name} answered incorrectly. No penalty (insufficient funds).")

        result_embed = discord.Embed(
            title=result_embed_title,
            description=result_embed_desc,
            color=result_embed_color
        )
        await message.channel.send(embed=result_embed, delete_after=15)
        
        # Hapus pesan pertanyaan dan pesan jawaban user untuk kerapian
        if quiz_session["question_message"]:
            try: await quiz_session["question_message"].delete()
            except discord.HTTPException: pass
        try:
            await message.delete() # Hapus pesan user yang menjawab
        except discord.HTTPException: pass
        
        quiz_session["current_question_idx"] += 1
        await asyncio.sleep(2) # Jeda singkat sebelum pertanyaan berikutnya
        await self._start_next_quiz_question(message.guild, message.channel)


    async def _end_quiz_session(self, guild: discord.Guild, channel: discord.TextChannel):
        logging.info(f"Ending quiz session for guild {guild.name}.")
        guild_id_str = str(guild.id)
        quiz_session = self.active_quizzes.pop(guild_id_str, None) # Hapus sesi aktif
        if not quiz_session: return

        scoreboard = quiz_session["score_board"]
        
        sorted_scores = sorted(scoreboard.items(), key=lambda item: item[1], reverse=True)
        
        embed = discord.Embed(
            title="🎉 Kuis Kebobrokan Selesai! 🎉",
            description="Laporan akhir dari Ujian Nasional Kebobrokan:",
            color=discord.Color.purple()
        )

        if not sorted_scores:
            embed.add_field(name="Hasil:", value="Tidak ada yang berhasil menjawab dengan benar! Mungkin terlalu jujur untuk kuis ini. 🤦‍♂️", inline=False)
        else:
            rank_text = ""
            for idx, (user_id, score) in enumerate(sorted_scores[:5]): # Tampilkan top 5
                member = guild.get_member(int(user_id))
                if member:
                    rank_text += f"{idx + 1}. **{member.display_name}** - {score} jawaban benar\n"
                else:
                    rank_text += f"{idx + 1}. Pengguna Tidak Dikenal ({user_id}) - {score} jawaban benar\n"
            embed.add_field(name="Top Pembobrok:", value=rank_text if rank_text else "Tidak ada yang berhasil menjawab dengan benar.", inline=False)
            embed.set_footer(text="Terima kasih telah berpartisipasi dalam program kebobrokan kami!")
            
        await channel.send(embed=embed)
        logging.info(f"Quiz session results announced for guild {guild.name}.")

    @commands.command(name="addsoal") # Command tanpa prefiks rtm
    @commands.has_permissions(administrator=True)
    async def add_trivia_question(self, ctx, q_type: str, question: str, answer: str, correct_resp: str, wrong_resp: str, *, options: str = None):
        logging.info(f"Admin {ctx.author.display_name} adding trivia question. Type: {q_type}, Question: {question[:50]}...")
        if q_type.lower() not in ["mc", "essay"]:
            logging.debug("Invalid question type.")
            return await ctx.send("❌ Tipe soal harus 'mc' (multiple choice) atau 'essay'.", ephemeral=True)
            
        questions_data = load_trivia_questions()
        
        new_question = {
            "id": f"Q{len(questions_data.get('questions', [])) + 1:03d}", # ID unik
            "type": q_type.lower(),
            "question": question,
            "answer": answer, # Jawaban benar (untuk MC, ini harus huruf opsi seperti "A")
            "correct_response": correct_resp,
            "wrong_response": wrong_resp,
        }

        if q_type.lower() == "mc":
            if not options:
                logging.debug("Missing options for multiple choice question.")
                return await ctx.send("⚠️ Untuk tipe 'mc', pilihan jawaban harus disediakan (pisahkan dengan '||').", ephemeral=True)
            new_question["options"] = [opt.strip() for opt in options.split("||")]
            if not new_question["options"]: # Pastikan ada opsi setelah split
                return await ctx.send("❌ Pilihan jawaban kosong setelah di-split. Pastikan formatnya benar (opsi1||opsi2).", ephemeral=True)
            # Validasi jawaban untuk MC harus berupa salah satu huruf opsi (A, B, C, D)
            if answer.upper() not in [chr(65+i) for i in range(len(new_question["options"]))]:
                 return await ctx.send("❌ Untuk tipe 'mc', jawaban harus berupa huruf opsi yang valid (misal: A, B, C, D) sesuai jumlah opsi yang diberikan.", ephemeral=True)
        
        questions_data.setdefault("questions", []).append(new_question)
        save_trivia_questions(questions_data)
        logging.info(f"New trivia question added. ID: {new_question['id']}.")
        
        await ctx.send(f"✅ Soal kuis kebobrokan baru berhasil ditambahkan! ID: `{new_question['id']}`")

    @commands.command(name="listsoal") # Command tanpa prefiks rtm
    @commands.has_permissions(administrator=True)
    async def list_trivia_questions(self, ctx):
        logging.info(f"Admin {ctx.author.display_name} requesting trivia questions list.")
        questions_data = load_trivia_questions()
        if not questions_data.get("questions"):
            logging.debug("Trivia questions bank is empty for listing.")
            return await ctx.send("Bank soal kuis kebobobrokan masih kosong.")
            
        embed = discord.Embed(
            title="📚 Daftar Soal Kuis Kebobrokan",
            description=f"Total soal: **{len(questions_data['questions'])}**\nBerikut adalah soal-soal yang terdaftar:",
            color=discord.Color.blue()
        )
        
        # Kirim dalam beberapa embed jika terlalu panjang
        current_description = ""
        embed_count = 0
        for q in questions_data["questions"]:
            options_text = ""
            if q.get("options"):
                options_text = "\n" + "\n".join([f"{chr(65+i)}. {option}" for i, option in enumerate(q["options"])]) # Tampilkan opsi dengan A,B,C,D
            
            question_entry = (
                f"**ID:** {q['id']} | **Tipe:** {q['type'].upper()}\n"
                f"**Q:** {q['question']}\n"
                f"**A:** {q['answer']}{options_text}\n"
                f"*(Benar: '{q['correct_response']}' | Salah: '{q['wrong_response']}')*\n\n" # Menambahkan respons
            )
            
            if len(current_description) + len(question_entry) > 1000: # Batas field value adalah 1024
                embed.add_field(name=f"Soal ({embed_count + 1})", value=current_description, inline=False)
                current_description = question_entry
                embed_count += 1
            else:
                current_description += question_entry
        
        if current_description: # Tambahkan sisa soal
            embed.add_field(name=f"Soal ({embed_count + 1})", value=current_description, inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="setglobaltax")
    @commands.has_permissions(administrator=True)
    async def set_global_tax(self, ctx, percentage: int):
        if not (0 <= percentage <= 100):
            return await ctx.send("❌ Persentase pajak harus antara 0 dan 100.", ephemeral=True)
        
        config = load_economy_config()
        config["global_tax_percentage"] = percentage
        save_economy_config(config)
        await ctx.send(f"✅ Persentase pajak global diatur menjadi **{percentage}%**.")
        logging.info(f"Global tax set to {percentage}% by {ctx.author.display_name}.")
    
    @commands.command(name="resettaxdate")
    @commands.has_permissions(administrator=True)
    async def reset_tax_date(self, ctx):
        config = load_economy_config()
        config["last_tax_run"] = None # Reset agar pajak bisa dipungut lagi segera
        save_economy_config(config)
        await ctx.send("✅ Tanggal pungutan pajak terakhir telah direset. Pajak akan segera dipungut dalam siklus berikutnya.")
        logging.info(f"Tax date reset by {ctx.author.display_name}.")

    @commands.command(name="proyekbaru") # Command baru untuk memulai proyek ngawur secara paksa
    @commands.has_permissions(administrator=True)
    async def force_start_new_random_project_cmd(self, ctx):
        """
        [ADMIN ONLY] Menghentikan proyek ngawur yang sedang berjalan (jika ada)
        dan memulai proyek ngawur baru secara paksa (random).
        Semua user yang memiliki cukup saldo akan otomatis dipotong RSWN-nya.
        """
        logging.info(f"Admin {ctx.author.display_name} memicu !proyekbaru.")

        if ctx.channel.id != EVENT_CHANNEL_ID:
            return await ctx.send(f"❌ Command ini hanya bisa digunakan di <#{EVENT_CHANNEL_ID}>.", ephemeral=True)

        guild_id_str = str(ctx.guild.id)
        current_active_project = self.active_projects.get(guild_id_str)

        # 1. Hentikan proyek yang sedang berjalan (jika ada)
        if current_active_project and current_active_project.get("status") != "failed":
            project_name_to_stop = current_active_project["name"]
            
            # Hapus proyek dari active_projects agar bisa dimulai yang baru
            self.active_projects.pop(guild_id_str, None)
            save_project_data(self.active_projects)
            logging.info(f"Proyek '{project_name_to_stop}' di guild {guild_id_str} dihentikan secara paksa oleh !proyekbaru.")
            
            await ctx.send(f"⚠️ Proyek sebelumnya: **{project_name_to_stop}** telah dihentikan secara paksa oleh {ctx.author.mention}. Lupakan saja kegagalannya...", ephemeral=False)
            await asyncio.sleep(2) # Jeda singkat untuk pesan

        # 2. Ambil proyek baru secara acak
        ngawur_projects_data = load_ngawur_projects_data()["projects"]
        if not ngawur_projects_data:
            return await ctx.send("❌ Daftar proyek ngawur kosong. Tidak ada proyek baru untuk dimulai. Harap tambahkan proyek ke `ngawur_projects.json`.", ephemeral=True)

        chosen_project = random.choice(ngawur_projects_data)
        new_project_name = chosen_project["name"]

        # Cek apakah bot punya izin kirim pesan di channel event
        event_channel = self.bot.get_channel(EVENT_CHANNEL_ID)
        if not event_channel or not event_channel.permissions_for(ctx.guild.me).send_messages:
            return await ctx.send("❌ Bot tidak punya izin untuk mengirim pesan di channel event. Mohon periksa izin.", ephemeral=True)

        # 3. Mulai proyek baru
        await ctx.send(f"✨ Admin {ctx.author.mention} memicu proyek ngawur baru secara paksa: **{new_project_name}**! Bersiaplah untuk menyumbang, wahai warga!")
        await self._start_ngawur_project(ctx.guild, new_project_name, ctx.channel) # Menggunakan ctx.channel sebagai channel event
        logging.info(f"Admin forced start of new random project '{new_project_name}' via !proyekbaru.")

    # --- Command: Lapor Polisi (User Curiga) ---
    @commands.command(name="lapormata")
    async def report_suspect(self, ctx, target_user: discord.Member):
        guild_id_str = str(ctx.guild.id)
        user_id_str = str(ctx.author.id)
        logging.info(f"User {ctx.author.display_name} ({user_id_str}) called !lapormata on {target_user.display_name} ({target_user.id}).")

        # Cek apakah user sedang dalam masa tahanan
        jailed, _ = await self._is_user_jailed(ctx.author.id, guild_id_str)
        if jailed:
            return await ctx.send("❌ Anda sedang dalam masa tahanan dan tidak bisa melaporkan siapa pun.", ephemeral=True)

        # Cek validitas target
        if target_user.bot:
            return await ctx.send("❌ Anda tidak bisa melaporkan bot.", ephemeral=True)
        if target_user.id == ctx.author.id:
            return await ctx.send("❌ Anda tidak bisa melaporkan diri sendiri.", ephemeral=True)
        
        # Cek apakah sudah ada investigasi aktif untuk user ini atau target ini
        # Dapatkan semua investigasi aktif di guild ini
        guild_investigations = self.active_investigations.get(guild_id_str, {})
        # Cek apakah pelapor sedang terlibat investigasi
        if user_id_str in guild_investigations:
            return await ctx.send("❌ Anda sudah mengajukan laporan dan sedang menunggu hasilnya.", ephemeral=True)
        # Cek apakah target sedang dalam investigasi
        if any(inv['suspect_id'] == str(target_user.id) and inv['status'] == 'pending' for inv in guild_investigations.values()):
            return await ctx.send("❌ Target Anda sedang dalam investigasi aktif. Mohon tunggu.", ephemeral=True)


        bank_data = load_bank_data()
        user_balance = bank_data.get(user_id_str, {}).get("balance", 0)

        # Tentukan biaya pungli acak (0-100 RSWN)
        bribe_cost = random.randint(POLICE_BRIBE_COST_MIN, POLICE_BRIBE_COST_MAX)
        
        if user_balance < bribe_cost:
            return await ctx.send(f"❌ Saldo Anda tidak cukup untuk membayar biaya laporan ke polisi (minimal **{bribe_cost} RSWN**). Anda punya: **{user_balance} RSWN**.", ephemeral=True)

        # Simpan status investigasi
        self.active_investigations.setdefault(guild_id_str, {})[user_id_str] = {
            'reporter_id': user_id_str,
            'suspect_id': str(target_user.id),
            'bribe_cost': bribe_cost,
            'status': 'pending', # Status investigasi: pending, resolved_success, resolved_fail
            'start_time': datetime.utcnow().isoformat()
        }
        
        # Potong biaya pungli dari pelapor
        bank_data[user_id_str]["balance"] -= bribe_cost
        save_bank_data(bank_data)

        # Narasi awal laporan
        report_initial_message = (
            f"📢 **Laporan Masuk!** **{ctx.author.display_name}** (`{ctx.author.mention}`) telah mengajukan laporan 'intelijen' terhadap **{target_user.display_name}** (`{target_user.mention}`)!\n\n"
            f"Polisi telah menerima laporan ini dengan biaya 'administrasi' sebesar **{bribe_cost} RSWN**.\n\n"
        )
        
        # Alasan pungli/layanan berdasarkan biaya
        if bribe_cost == 0:
            report_initial_message += "_(Sepertinya kali ini polisi sedang berintegritas tinggi. Sebuah keajaiban!)_"
        elif bribe_cost <= 25:
            police_reason = "Biaya ini untuk 'formulir' dan 'materai'. Lumayan untuk kas negara."
            report_initial_message += f"_{police_reason}_"
        elif bribe_cost <= 70:
            police_reason = "Uang ini untuk 'kopi dan rokok' para petugas di pos. Mereka butuh energi ekstra."
            report_initial_message += f"_{police_reason}_"
        else: # bribe_cost > 70
            police_reason = "Biaya ini untuk 'operasional lapangan' yang sangat mendesak. Paham kan, butuh 'dana tak terduga'."
            report_initial_message += f"_{police_reason}_"
        
        # Kirim pengumuman ke channel event
        report_msg = await ctx.send(report_initial_message)
        logging.info(f"Report by {ctx.author.display_name} against {target_user.display_name} initiated with bribe {bribe_cost}.")

        # Simulasi investigasi
        await asyncio.sleep(random.randint(15, 45)) # Investigasi berjalan 15-45 detik

        # Pastikan investigasi ini masih pending dan belum dibatalkan/diselesaikan di luar alur ini
        current_investigation_state = self.active_investigations.get(guild_id_str, {}).get(user_id_str)
        if not current_investigation_state or current_investigation_state['status'] != 'pending':
            logging.info(f"Investigation for {user_id_str} was already resolved or cancelled. Skipping automated resolution.")
            return

        # Acak hasil investigasi (peluang tertangkap: 60%)
        if random.random() < 0.60: # Target tertangkap
            logging.info(f"Investigation against {target_user.display_name} succeeded. Jailing target.")
            await self._jail_user(target_user, JAIL_DURATION_HOURS) # Penjarakan target
            
            self.active_investigations[guild_id_str][user_id_str]['status'] = 'resolved_success'
            success_message = (
                f"🚨 **BERHASIL!** Setelah investigasi yang mendalam (dan beberapa amplop tebal), Polisi berhasil membuktikan laporan Anda!\n"
                f"**{target_user.mention}** telah ditangkap dan dijebloskan ke penjara! Mampus kau dikorup! 😈\n"
                f"Terima kasih atas 'kerja sama' Anda, **{ctx.author.display_name}**."
            )
            await ctx.send(success_message)
            # Memberikan sedikit reward kepada pelapor atas 'jasanya'
            bank_data = load_bank_data()
            bounty = random.randint(50, 200)
            bank_data.setdefault(user_id_str, {})['balance'] += bounty
            save_bank_data(bank_data)
            await ctx.author.send(f"🎉 **BONUS!** Atas 'jasa' Anda melaporkan, Anda menerima **{bounty} RSWN** sebagai bonus rahasia dari polisi!", ephemeral=True)

        else: # Target tidak tertangkap
            logging.info(f"Investigation against {target_user.display_name} failed. Target not jailed.")
            self.active_investigations[guild_id_str][user_id_str]['status'] = 'resolved_fail'
            fail_message = (
                f"⚠️ **GAGAL!** Hasil investigasi menunjukkan laporan Anda tidak memiliki cukup 'bukti' (atau mungkin uangnya kurang). \n"
                f"**{target_user.mention}** lolos dari jeratan hukum! Polisi meminta maaf atas ketidaknyamanan, dan menyarankan untuk 'melengkapi' laporan Anda lain kali. 😉"
            )
            await ctx.send(fail_message)

        # Hapus investigasi dari daftar aktif setelah resolusi
        self.active_investigations.get(guild_id_str, {}).pop(user_id_str, None)


    # --- Command: Butuh Orang Dalam (Sogok Polisi/Pemerintah) ---
    @commands.command(name="butuhorangdalam", aliases=["sogokpolisi", "bebaspenjara"])
    async def need_insider(self, ctx):
        guild_id_str = str(ctx.guild.id)
        user_id_str = str(ctx.author.id)

        logging.info(f"User {ctx.author.display_name} ({user_id_str}) called !butuhorangdalam.")

        # Cek apakah user memang sedang dalam masa tahanan
        jailed, jailed_until = await self._is_user_jailed(ctx.author.id, guild_id_str)
        if not jailed:
            return await ctx.send("❌ Anda tidak sedang dalam masa tahanan. Kenapa butuh orang dalam?", ephemeral=True)

        # Cek apakah user sudah meminta bantuan sebelumnya (cooldown)
        jail_help_requests_data = load_jail_help_requests()
        last_request_time_str = jail_help_requests_data.get(user_id_str, {}).get("last_request_time")
        
        if last_request_time_str:
            last_request_time = datetime.fromisoformat(last_request_time_str)
            # Batasi permintaan sogok setiap 1 jam, misalnya
            if datetime.utcnow() - last_request_time < timedelta(hours=1):
                time_left = timedelta(hours=1) - (datetime.utcnow() - last_request_time)
                minutes, seconds = divmod(int(time_left.total_seconds()), 60)
                return await ctx.send(f"❌ Anda baru saja meminta bantuan. Coba lagi dalam {minutes} menit {seconds} detik.", ephemeral=True)

        bank_data = load_bank_data()
        user_balance = bank_data.get(user_id_str, {}).get("balance", 0)

        sogok_cost = random.randint(CORRUPTION_CHARGE_COST_MIN, CORRUPTION_CHARGE_COST_MAX)
        
        if user_balance < sogok_cost:
            return await ctx.send(f"❌ Saldo Anda tidak cukup untuk menyogok pejabat ({sogok_cost} RSWN diperlukan). Anda punya: **{user_balance} RSWN**. Coba lagi nanti kalau sudah punya uang busuk.", ephemeral=True)
        
        # Potong biaya sogokan
        bank_data[user_id_str]["balance"] -= sogok_cost
        save_bank_data(bank_data)

        # Simpan waktu permintaan untuk cooldown
        jail_help_requests_data[user_id_str] = {"last_request_time": datetime.utcnow().isoformat()}
        save_jail_help_requests(jail_help_requests_data)

        # Acak hasil sogokan
        if random.random() < 0.60: # 60% berhasil
            logging.info(f"User {ctx.author.display_name} successfully bribed for release from jail. Cost: {sogok_cost}.")
            await self._release_user(ctx.author) # Bebaskan user
            await ctx.send(f"🎉 **SELAMAT!** Biaya **{sogok_cost} RSWN** telah diterima oleh 'orang dalam'. Anda bebas! Ingat, kami punya hutang budi sekarang...", ephemeral=False)
            await ctx.author.send(f"Biaya sogokanmu sebesar **{sogok_cost} RSWN** telah diterima. Kau bebas sekarang, tapi jangan bilang siapa-siapa ya!")
        else: # 40% gagal
            logging.info(f"User {ctx.author.display_name} failed to bribe for release. Cost: {sogok_cost}.")
            await ctx.send(f"💔 Sogokan Anda gagal! Biaya **{sogok_cost} RSWN** hangus! Pejabatnya mungkin kurang 'terkesan' atau dia lagi puasa. Tetaplah busuk di penjara!", ephemeral=False)
            await ctx.author.send(f"Sogokanmu sebesar **{sogok_cost} RSWN** gagal. Mungkin kau harus coba lagi nanti dengan jumlah yang lebih besar, atau pejabatnya lagi tidur.")

async def setup(bot):
    await bot.add_cog(EconomyEvents(bot))
