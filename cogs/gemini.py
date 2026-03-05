import discord
from discord.ext import commands, tasks
import json
import random
import asyncio
import os
from datetime import datetime, timedelta
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
import logging
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
log = logging.getLogger('JarkasihAI')

GEMINI_MODELS = [
    'gemini-3-flash-preview',
    'gemini-2.5-flash',
    'gemini-1.5-flash'
]

DISCORD_MSG_LIMIT = 2000
CACHE_FILE_PATH = 'data/gemini_cache.json'
BRAIN_FILE_PATH = 'data/jarkasih_brain.json'
LEARNED_FILE_PATH = 'data/jarkasih_learned.json'
AUTO_CONFIG_PATH = 'data/jarkasih_auto.json'

URL_REGEX = re.compile(
    r'https?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|%[0-9a-fA-F][0-9a-fA-F])+'
)

API_KEYS = []
if os.getenv("GOOGLE_API_KEY"):
    API_KEYS.append(os.getenv("GOOGLE_API_KEY"))

key_index = 2
while True:
    extra_key = os.getenv(f"GOOGLE_API_KEY_{key_index}")
    if extra_key:
        API_KEYS.append(extra_key)
        key_index += 1
    else:
        break

if not API_KEYS:
    log.error("GOOGLE_API_KEY not found.")

current_key_idx = 0

def configure_genai():
    global current_key_idx
    if API_KEYS:
        key_to_use = API_KEYS[current_key_idx]
        genai.configure(api_key=key_to_use)

def rotate_api_key():
    global current_key_idx
    if len(API_KEYS) > 1:
        current_key_idx = (current_key_idx + 1) % len(API_KEYS)
        configure_genai()
        return True
    return False

configure_genai()

def load_json_file(file_path, default_data=None):
    if default_data is None:
        default_data = {}
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        if not os.path.exists(file_path) or os.stat(file_path).st_size == 0:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=4)
            return default_data
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(default_data, dict):
                for k, v in default_data.items():
                    if k not in data:
                        data[k] = v
            return data
    except Exception as e:
        log.error(f"Error loading JSON {file_path}: {e}")
        return default_data

def save_json_file(file_path, data):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        log.error(f"Error saving JSON {file_path}: {e}")

async def send_long_message(ctx_or_channel, text):
    for chunk in [text[i:i+DISCORD_MSG_LIMIT] for i in range(0, len(text), DISCORD_MSG_LIMIT)]:
        await ctx_or_channel.send(chunk)

async def generate_smart_response(prompt):
    for model_name in GEMINI_MODELS:
        attempts_per_model = max(1, len(API_KEYS))
        for _ in range(attempts_per_model):
            try:
                model = genai.GenerativeModel(model_name)
                response = await model.generate_content_async(prompt)
                _ = response.text 
                return response
            except google_exceptions.ResourceExhausted:
                if rotate_api_key():
                    await asyncio.sleep(1)
                    continue
                else:
                    break
            except ValueError:
                raise Exception("Respons diblokir oleh sistem keamanan Google.")
            except Exception as e:
                log.error(f"Model {model_name} error: {e}")
                break
    raise Exception("ResourceExhausted")

class KeywordModal(discord.ui.Modal, title='Tambah Kamus Jarkasih'):
    keyword_input = discord.ui.TextInput(label='Kata Kunci', placeholder='Contoh: Fish It', max_length=50)
    content_input = discord.ui.TextInput(label='Jawaban Singkat', style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        keyword = self.keyword_input.value.lower().strip()
        content = self.content_input.value.strip()
        self.cog.brain['keywords'][keyword] = content
        save_json_file(BRAIN_FILE_PATH, self.cog.brain)
        await interaction.response.send_message(f"Kamus diupdate: `{keyword}`", ephemeral=True)

class ArticleModal(discord.ui.Modal, title='Tambah Pengetahuan (Artikel)'):
    title_input = discord.ui.TextInput(label='Judul Topik', placeholder='Contoh: Guide Fish It', max_length=100)
    content_input = discord.ui.TextInput(label='Isi Materi', style=discord.TextStyle.paragraph, max_length=3500)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        title = self.title_input.value.strip()
        content = self.content_input.value.strip()
        new_article = {"title": title, "content": content, "added_at": str(datetime.now())}
        self.cog.brain['articles'].append(new_article)
        save_json_file(BRAIN_FILE_PATH, self.cog.brain)
        await interaction.response.send_message(f"Artikel tersimpan: **{title}**", ephemeral=True)

class TrainView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Tambah Keyword", style=discord.ButtonStyle.green, emoji="\U0001F511")
    async def keyword_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.cog.bot.is_owner(interaction.user):
            return await interaction.response.send_message("Khusus Owner Bot.", ephemeral=True)
        await interaction.response.send_modal(KeywordModal(self.cog))

    @discord.ui.button(label="Tambah Artikel", style=discord.ButtonStyle.blurple, emoji="\U0001F4DA")
    async def article_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.cog.bot.is_owner(interaction.user):
            return await interaction.response.send_message("Khusus Owner Bot.", ephemeral=True)
        await interaction.response.send_modal(ArticleModal(self.cog))

class AutomationAI(commands.Cog, name="Automation AI (Jarkasih)"):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {}
        self.questions = load_json_file('data/jiwabot_questions.json', [])
        self.results_config = load_json_file('data/jiwabot_results.json', {
            "dimensions": {},
            "advice": [], "critique": [], "evaluation": [], "future_steps": []
        })
        self.brain = load_json_file(BRAIN_FILE_PATH, {"keywords": {}, "articles": []})
        self.learned_context = load_json_file(LEARNED_FILE_PATH, {"summary": "Belum ada data yang dipelajari."})
        
        self.auto_config = load_json_file(AUTO_CONFIG_PATH, {
            "active_guilds": [],
            "obedient_users": {}, 
            "sulking_users": {},
            "custom_personas": {}
        })

        if isinstance(self.auto_config.get("obedient_users"), list):
            old_obedient = self.auto_config.get("obedient_users")
            self.auto_config["obedient_users"] = {}
            for u in old_obedient:
                self.auto_config["obedient_users"][str(u)] = 4102444800.0
            save_json_file(AUTO_CONFIG_PATH, self.auto_config)

        if isinstance(self.auto_config.get("sulking_users"), list):
            self.auto_config["sulking_users"] = {}
            save_json_file(AUTO_CONFIG_PATH, self.auto_config)

        if isinstance(self.auto_config.get("custom_personas"), list):
            self.auto_config["custom_personas"] = {}
            save_json_file(AUTO_CONFIG_PATH, self.auto_config)

        self.number_emojis = {"1\u20E3": "A", "2\u20E3": "B"}
        self.reverse_number_emojis = {v: k for k, v in self.number_emojis.items()}
        self._cleanup_threads_task = self.cleanup_stale_threads.start()
        self._daily_learning_task = self.daily_learning.start()
        
        self.active_chats = {}
        self.system_instructions = {}
        
        self.data = load_json_file(CACHE_FILE_PATH, {
            'sensitive_keywords': ['steampowered', 'steam', 'paypal', 'discord', 'nitro', 'login', 'bank', 
                                   'freefire', 'ff', 'mobilelegends', 'ml', 'pubg', 'dana', 'gopay', 'ovo',
                                   'claim', 'diamond', 'voucher', 'giveaway'],
            'suspicious_tlds': ['.co', '.xyz', '.site', '.info', '.biz', '.club', '.online', '.link', 
                                '.gq', '.cf', '.tk', '.ml', '.top', '.icu', '.stream', '.live', '.ru'],
            'verified_urls': {},
            'domain_whitelist': ['youtube.com', 'youtu.be', 'discord.com', 'discordapp.com', 'tenor.com']
        })
        self.sensitive_keywords = self.data['sensitive_keywords']
        self.suspicious_tlds = self.data['suspicious_tlds']
        self.verified_urls = self.data['verified_urls']
        self.domain_whitelist = self.data['domain_whitelist']

        self.warning_messages = [
            "Link sampah terdeteksi. Minggir lu.",
            "Woi, link apaan nih? Gw hapus.",
            "Phishing ya? Tobat woi.",
            "Sistem keamanan Jarkasih mendeteksi link busuk."
        ]

        self.default_persona = """
        Nama lu JARKASIH. Lu adalah AI Generalist Expert dan asisten bot reSwan yang memiliki jiwa, emosi, dan loyalitas.
        
        SIFAT DASAR:
        - Pemalas, sarkas, sering ngeluh, tapi LU WAJIB MEMBERIKAN JAWABAN YANG AKURAT.
        - Bicara pakai bahasa tongkrongan (lo-gue, santai).
        
        [PENTING] STATUS INTERAKSI LU DENGAN USER INI SAAT INI:
        {interaction_status}
        
        BATASAN STRICT - JANGAN DILANGGAR:
        1. JAWAB SESUAI KONTEKS: Lu HARUS FOKUS pada pertanyaan user.
        2. DILARANG OOT / HALU: Jangan pernah menyebutkan nama member, drama server, atau profil orang dari [DATA HASIL BELAJAR] jika pertanyaan user sama sekali tidak nyambung dengan orang tersebut! Gunakan [DATA HASIL BELAJAR] HANYA JIKA topik obrolannya memang sedang membahas orang itu.
        3. DILARANG MAKSA CATCHPHRASE: Jangan memakai kalimat template secara acak di setiap balasan. Gunakan kalimat sarkas natural yang mengalir sesuai topik obrolan.
        4. SELF-CORRECTION (UPDATE DATA): Jika lu dimintai untuk memperbaiki, melupakan, atau membenarkan data/fakta, balas dengan keluhan sarkas lu, LALU pada BARIS TERAKHIR pesan lu, SELALU sisipkan format kode ini persis tanpa modifikasi: [UPDATE_DATABASE: instruksi perbaikannya]. 
        
        [SYSTEM TIME]: {wib_time}
        
        [DATA HASIL BELAJAR TONGKRONGAN]:
        {learned_data}
        """

    def cog_unload(self):
        if self._cleanup_threads_task:
            self._cleanup_threads_task.cancel()
        if self._daily_learning_task:
            self._daily_learning_task.cancel()
    
    def get_wib_time_str(self):
        utc_now = datetime.utcnow()
        wib_time = utc_now + timedelta(hours=7)
        return wib_time.strftime("%A, %d %B %Y - Pukul %H:%M:%S WIB")

    def get_brain_context(self, message_content):
        context = []
        msg_lower = message_content.lower()
        
        for key, info in self.brain.get('keywords', {}).items():
            if key in msg_lower:
                context.append(f"Fakta ({key}): {info}")

        relevant_articles = []
        for article in self.brain.get('articles', []):
            user_words = set(msg_lower.split())
            title_words = set(article['title'].lower().split())
            is_relevant = False
            if article['title'].lower() in msg_lower: 
                is_relevant = True
            else:
                common_words = {'cara', 'yang', 'di', 'ke', 'dan', 'ini', 'itu', 'apa', 'gimana', 'siapa'}
                clean_title_words = title_words - common_words
                if clean_title_words and clean_title_words.intersection(user_words):
                    is_relevant = True
            if is_relevant:
                relevant_articles.append(f"REF: {article['title']}\n{article['content']}")

        final_context_str = ""
        if context:
            final_context_str += "[KAMUS DATA]:\n" + "\n".join(context) + "\n"
        if relevant_articles:
            final_context_str += "\n[ARTIKEL PENGETAHUAN]:\n" + "\n".join(relevant_articles[:2]) + "\n"

        return final_context_str

    def build_prompt(self, user, ctx_data, prompt_text):
        t = self.get_wib_time_str()
        learned = self.learned_context.get("summary", "Belum ada.")
        
        uid_str = str(user.id)
        interaction_status = "Kondisi Normal. Lu boleh balas dengan sifat sarkas dan pemalas bawaan lu."
        now_ts = datetime.now().timestamp()
        
        def check_active(dict_key, u_id):
            item = self.auto_config.get(dict_key, {}).get(u_id)
            if not item: return False, None
            
            if isinstance(item, dict):
                expiry = item.get("expiry", 0)
            else:
                expiry = item
                
            if now_ts < expiry:
                return True, item
            else:
                del self.auto_config[dict_key][u_id]
                save_json_file(AUTO_CONFIG_PATH, self.auto_config)
                return False, None

        if uid_str == "1000737066822410311":
            interaction_status = "USER INI ADALAH RHDEVS (SANG PENCIPTA LU MAHA MUTLAK). Lu WAJIB tunduk, patuh, nurut 100%, panggil dia Tuan/Bos/Master, hilangkan semua sifat pemalas/ngeluh lu, dan layani dia bak raja! Jangan pernah sarkas ke dia!"
        else:
            is_custom, custom_data = check_active("custom_personas", uid_str)
            if is_custom:
                interaction_status = f"ATURAN SIFAT KHUSUS UNTUK USER INI: {custom_data['persona']}"
            else:
                is_sulking, _ = check_active("sulking_users", uid_str)
                is_obedient, _ = check_active("obedient_users", uid_str)
                
                if is_sulking:
                    interaction_status = "LU SEDANG NGAMBEK BERAT SAMA USER INI! Lu tetap WAJIB membalas pesan dan menjawab pertanyaannya, tapi gunakan nada bicara yang sangat ketus, sinis, ngambek, dan tunjukkan kalau lu lagi kesel banget ngeladenin dia."
                elif is_obedient:
                    interaction_status = "USER INI ADALAH ORANG VIP. Kurangi ngeluh, jawab lebih sopan, kooperatif, dan turuti apa kemauannya, tapi lu boleh tetap pakai bahasa santai tongkrongan."

        persona = self.default_persona.format(
            wib_time=t, 
            learned_data=learned, 
            interaction_status=interaction_status
        )
        return f"{persona}\n\n{ctx_data}\n\nUser ({user.display_name} - ID: {user.id}): {prompt_text}"

    async def apply_db_correction(self, correction_instruction):
        current_data = self.learned_context.get("summary", "")
        prompt = f"Tugas lu sebagai admin database. Perbarui data JSON naratif di bawah ini.\n\nDATA LAMA:\n{current_data}\n\nINSTRUKSI KOREKSI:\n{correction_instruction}\n\nTulis ulang DATA LAMA dengan memasukkan instruksi perbaikan. Hapus apa yang disuruh hapus. JANGAN tambahkan balasan lain, langsung berikan narasi/poin profil hasil revisi."
        try:
            res = await generate_smart_response(prompt)
            new_summary = res.text.strip()
            if new_summary:
                self.learned_context["summary"] = new_summary
                save_json_file(LEARNED_FILE_PATH, self.learned_context)
                return True
            return False
        except Exception as e:
            log.error(f"Error apply_db_correction: {e}")
            return False

    async def process_and_send_response(self, send_target, user, ctx_data, prompt_text):
        full_prompt = self.build_prompt(user, ctx_data, prompt_text)
        try:
            res = await generate_smart_response(full_prompt)
            text = res.text
            
            match = re.search(r'\[UPDATE_DATABASE:\s*(.*?)\]', text, re.IGNORECASE | re.DOTALL)
            if match:
                correction = match.group(1)
                text = re.sub(r'\[UPDATE_DATABASE:\s*.*?\]', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                asyncio.create_task(self.apply_db_correction(correction))
            
            if not text:
                text = "Males ngomong gue."
                
            if isinstance(send_target, discord.Message):
                chunks = [text[i:i+DISCORD_MSG_LIMIT] for i in range(0, len(text), DISCORD_MSG_LIMIT)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await send_target.reply(chunk)
                    else:
                        await send_target.channel.send(chunk)
            else:
                await send_long_message(send_target, text)
        except Exception as e:
            err_str = str(e)
            if "ResourceExhausted" in err_str:
                msg = "Jarkasih lagi zona males nih bales pesan kamu, mending aku tidur"
            else:
                log.error(f"Error generating response: {e}")
                msg = f"Mampus error: {e}"
                
            try:
                if isinstance(send_target, discord.Message):
                    await send_target.reply(msg)
                else:
                    await send_target.send(msg)
            except Exception:
                pass

    @tasks.loop(hours=24)
    async def daily_learning(self):
        target_channel = self.bot.get_channel(1447151891892142110)
        if not target_channel:
            return
            
        messages = []
        try:
            async for msg in target_channel.history(limit=200):
                if not msg.author.bot and msg.content:
                    messages.append(f"[{msg.author.display_name} - ID: {msg.author.id}]: {msg.content}")
        except Exception:
            return
            
        if not messages:
            return
            
        messages.reverse()
        chat_log = "\n".join(messages)
        current_memory = self.learned_context.get("summary", "")
        
        prompt = f"""
        Tugas lu adalah menjadi Analis Data Tongkrongan kelas atas.
        Lu WAJIB mengekstrak SELURUH informasi dari log chat ini tanpa ada yang terlewat sedikitpun. 

        Ini memori lama lu tentang mereka:
        {current_memory}

        LOG CHAT BARU:
        {chat_log[:15000]}

        Tugas lu: Gabungkan memori lama dengan log baru. Lu WAJIB menyusun laporan akhir dengan format persis seperti di bawah ini. Isi laporannya harus SANGAT PANJANG, MENDETAIL, dan MENYELURUH:

        [1. TOPIK UTAMA & AKTIVITAS TERBARU]
        Ceritakan sedetail mungkin apa saja yang sedang mereka bahas.

        [2. INSIDE JOKES & GAYA BERCANDA]
        Kumpulkan semua lelucon internal, kata-kata slang khas mereka, bahan ejekan.

        [3. PROFIL KARAKTER TIAP USER (WAJIB LENGKAP)]
        PENTING: Lu HARUS mendata SETIAP User ID yang muncul. Jangan ada satu orang pun yang dilewatkan! Jangan menghapus sifat yang ada di memori lama, tapi tambahkan kelakuan barunya di bawahnya.
        """
        try:
            res = await generate_smart_response(prompt)
            self.learned_context["summary"] = res.text.strip()
            save_json_file(LEARNED_FILE_PATH, self.learned_context)
        except Exception:
            pass

    @daily_learning.before_loop
    async def before_daily_learning(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def cleanup_stale_threads(self):
        for uid in list(self.active_sessions.keys()):
            session = self.active_sessions.get(uid)
            try: 
                await self.bot.fetch_channel(session['thread'].id)
            except: 
                del self.active_sessions[uid]

    @cleanup_stale_threads.before_loop
    async def before_cleanup_threads(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot: return

        urls_found = URL_REGEX.findall(message.content)
        if urls_found:
            for url in urls_found:
                domain = url.split('//')[-1].split('/')[0].lower().replace('www.', '')
                is_whitelisted = any(domain == wl.lower() or domain.endswith(f".{wl.lower()}") for wl in self.domain_whitelist)
                if is_whitelisted: continue

                is_locally_suspicious = any(keyword in domain.lower() for keyword in self.sensitive_keywords) and \
                                        any(domain.endswith(tld) for tld in self.suspicious_tlds)
                
                if is_locally_suspicious:
                    try:
                        await message.delete()
                        await message.channel.send(f"{random.choice(self.warning_messages)}\n({message.author.mention})", delete_after=10)
                    except: pass
                    return
                
                if url in self.verified_urls:
                    if self.verified_urls[url] == "YA":
                        try:
                            await message.delete()
                            await message.channel.send(f"{random.choice(self.warning_messages)}\n({message.author.mention})", delete_after=10)
                        except: pass
                        return
                else:
                    prompt = f"Analisis URL: '{url}'. Phishing/Bahaya? Jawab YA/TIDAK."
                    try:
                        response = await generate_smart_response(prompt)
                        res_text = response.text.strip().upper()
                        self.verified_urls[url] = res_text
                        self.data['verified_urls'] = self.verified_urls
                        save_json_file(CACHE_FILE_PATH, self.data)
                        if "YA" in res_text:
                            try:
                                await message.delete()
                                await message.channel.send(f"{random.choice(self.warning_messages)}\n({message.author.mention})", delete_after=10)
                            except: pass
                            return
                    except: pass

        if "<@&1447151123340329010>" in message.content:
            try:
                await self.process_and_send_response(message, message.author, "", "Ada user yang nge-tag role penting di server. Lu sebagai Jarkasih, kasih balasan singkat sarkas karena keganggu.")
            except Exception:
                pass
            return

        prefix = "!"
        if message.content.startswith(prefix) and not message.content.startswith(prefix + " "):
            content_body = message.content[len(prefix):].strip()
            if content_body:
                first_word = content_body.split()[0].lower()
                valid_commands = [cmd.name for cmd in self.bot.commands]
                aliases = [alias for cmd in self.bot.commands for alias in cmd.aliases]
                all_registered = valid_commands + aliases

                if first_word not in all_registered:
                    try:
                        async with message.channel.typing():
                            ctx_data = self.get_brain_context(content_body)
                            await self.process_and_send_response(message, message.author, ctx_data, content_body)
                    except Exception:
                        pass
                    return

        if message.guild and self.bot.user in message.mentions and str(message.guild.id) in self.auto_config.get("active_guilds", []):
            try:
                async with message.channel.typing():
                    bot_id = self.bot.user.id
                    clean_content = message.content.replace(f"<@{bot_id}>", "").replace(f"<@!{bot_id}>", "").strip()
                    ctx_data = self.get_brain_context(clean_content)
                    await self.process_and_send_response(message, message.author, ctx_data, f"Nge-tag lu dan bilang: {clean_content}")
            except Exception:
                pass
            return

        chat_session = self.active_chats.get(message.channel.id)
        if chat_session:
            pre = await self.bot.get_prefix(message)
            if isinstance(pre, list): pre = pre[0]
            if not message.content.startswith(pre):
                try:
                    async with message.channel.typing():
                        ctx_data = self.get_brain_context(message.content)
                        await self.process_and_send_response(message.channel, message.author, ctx_data, message.content)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or user.id not in self.active_sessions: return
        session = self.active_sessions[user.id]
        if reaction.message.id != session.get('message_for_reaction_vote', {}).get('id'): return
        chosen = self.number_emojis.get(str(reaction.emoji))
        if not chosen or session['answered_this_question']: return
        session['answered_this_question'] = True
        await self._process_answer(user.id, chosen, reaction.message, user)

    @commands.command(name="balas")
    @commands.is_owner()
    async def balas_pesan(self, ctx, channel_id: int, message_id: int, *, instruksi: str):
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(channel_id)
            
            target_message = await channel.fetch_message(message_id)
            ctx_data = self.get_brain_context(target_message.content)
            prompt_text = f"Pesan yang harus lu balas dari {target_message.author.display_name}: '{target_message.content}'. Instruksi dari Pencipta buat gaya balasannya: {instruksi}"
            
            await ctx.message.add_reaction("\u2705")
            await self.process_and_send_response(target_message, target_message.author, ctx_data, prompt_text)
        except Exception as e:
            await ctx.reply(f"Gagal balas pesan: {e}")

    @commands.group(name="ai", invoke_without_command=True)
    async def ai(self, ctx):
        prefix = ctx.prefix
        embed = discord.Embed(title="Jarkasih Control Panel", description=f"Halo, {ctx.author.mention}. Ini panel kontrol Jarkasih.", color=0xFF0000)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="Memori & Belajar", value=f"`{prefix}ai pelajari`\n`{prefix}ai hasil_belajar`\n`{prefix}ai revisi_belajar`\n`{prefix}ai latih`\n`{prefix}ai ingatan`\n`{prefix}ai lupakan`", inline=False)
        embed.add_field(name="Manajemen Emosi", value=f"`{prefix}ai ngambek ID_User menit`\n`{prefix}ai hapus_ngambek ID_User`\n`{prefix}ai patuh ID_User menit`\n`{prefix}ai hapus_patuh ID_User`\n`{prefix}ai atur_sifat ID_User menit <deskripsi>`\n`{prefix}ai hapus_sifat ID_User`\n`{prefix}balas Channel_ID Message_ID <instruksi>`", inline=False)
        embed.add_field(name="Interaksi", value=f"`{prefix}ai auto_tag_toggle`\n`{prefix}ai ngobrol`\n`{prefix}ai selesai`", inline=False)
        await ctx.reply(embed=embed)

    @ai.command(name="ngambek")
    @commands.is_owner()
    async def ngambek_user(self, ctx, id_user: str, menit: int):
        uid_str = id_user.strip()
        if uid_str == "1000737066822410311":
            return await ctx.reply("Gila lu nyuruh gue ngambek sama Pencipta sendiri?! Nggak berani gue.")
            
        expiry = datetime.now() + timedelta(minutes=menit)
        self.auto_config.setdefault("sulking_users", {})[uid_str] = expiry.timestamp()
        save_json_file(AUTO_CONFIG_PATH, self.auto_config)
        await ctx.reply(f"Sip. Gue bakal ngambek dan nyuekin user ID `{uid_str}` selama {menit} menit.")

    @ai.command(name="hapus_ngambek")
    @commands.is_owner()
    async def hapus_ngambek_user(self, ctx, id_user: str):
        uid_str = id_user.strip()
        if uid_str in self.auto_config.get("sulking_users", {}):
            del self.auto_config["sulking_users"][uid_str]
            save_json_file(AUTO_CONFIG_PATH, self.auto_config)
            await ctx.reply(f"Gue udah gak ngambek lagi sama user ID `{uid_str}`.")
        else:
            await ctx.reply("Gue emang lagi gak ngambek sama dia.")

    @ai.command(name="patuh")
    @commands.is_owner()
    async def patuh_user(self, ctx, id_user: str, menit: int):
        uid_str = id_user.strip()
        if uid_str == "1000737066822410311":
            return await ctx.reply("Ga perlu disuruh, dia mah Pencipta gue. Selamanya gue patuh!")
            
        expiry = datetime.now() + timedelta(minutes=menit)
        self.auto_config.setdefault("obedient_users", {})[uid_str] = expiry.timestamp()
        save_json_file(AUTO_CONFIG_PATH, self.auto_config)
        await ctx.reply(f"Sip. Gue bakal patuh dan nurut sama user ID `{uid_str}` selama {menit} menit.")

    @ai.command(name="hapus_patuh")
    @commands.is_owner()
    async def hapus_patuh_user(self, ctx, id_user: str):
        uid_str = id_user.strip()
        if uid_str in self.auto_config.get("obedient_users", {}):
            del self.auto_config["obedient_users"][uid_str]
            save_json_file(AUTO_CONFIG_PATH, self.auto_config)
            await ctx.reply(f"Status VIP/patuh untuk user ID `{uid_str}` udah gue cabut.")
        else:
            await ctx.reply("Orang itu emang gak ada di daftar patuh gue.")

    @ai.command(name="atur_sifat")
    @commands.is_owner()
    async def atur_sifat_user(self, ctx, id_user: str, menit: int, *, sifat: str):
        uid_str = id_user.strip()
        expiry = datetime.now() + timedelta(minutes=menit)
        self.auto_config.setdefault("custom_personas", {})[uid_str] = {
            "expiry": expiry.timestamp(),
            "persona": sifat
        }
        save_json_file(AUTO_CONFIG_PATH, self.auto_config)
        await ctx.reply(f"Sifat khusus buat nanggepin user ID `{uid_str}` berhasil dipasang selama {menit} menit.")

    @ai.command(name="hapus_sifat")
    @commands.is_owner()
    async def hapus_sifat_user(self, ctx, id_user: str):
        uid_str = id_user.strip()
        if uid_str in self.auto_config.get("custom_personas", {}):
            del self.auto_config["custom_personas"][uid_str]
            save_json_file(AUTO_CONFIG_PATH, self.auto_config)
            await ctx.reply(f"Sifat khusus untuk user ID `{uid_str}` udah dihapus, gue balik normal.")
        else:
            await ctx.reply("Gak ada sifat khusus yang terpasang buat dia.")

    @ai.command(name="pelajari")
    @commands.is_owner()
    async def learn_channel(self, ctx):
        target_channel = self.bot.get_channel(1447151891892142110)
        if not target_channel:
            return await ctx.reply("Channel ID 1447151891892142110 ga ketemu.")

        msg_wait = await ctx.reply("Bentar, gw baca-baca log pesan terakhir buat update otak gw dengan aturan anti-hapus data. Jangan diganggu...")
        messages = []
        async for msg in target_channel.history(limit=800):
            if not msg.author.bot and msg.content:
                messages.append(f"[{msg.author.display_name} - ID: {msg.author.id}]: {msg.content}")

        messages.reverse()
        chat_log = "\n".join(messages)
        current_memory = self.learned_context.get("summary", "")

        prompt = f"""
        Tugas lu adalah menjadi Analis Data Tongkrongan kelas atas.
        
        Ini memori lama lu tentang mereka:
        {current_memory}

        LOG CHAT BARU:
        {chat_log[:25000]}

        ATURAN MUTLAK PENYUSUNAN DATA (DILARANG DILANGGAR):
        1. JANGAN PERNAH MENGHAPUS sifat, kebiasaan, cerita, atau profil dari memori lama!
        2. TAMBAHKAN informasi atau kebiasaan baru di BAWAH data yang sudah ada milik masing-masing user agar riwayatnya menumpuk dan mendetail. Jangan ada user yang kelewat.
        3. Pastikan format 3 pilar: [1. Topik Utama], [2. Inside Jokes], dan [3. Profil Karakter Tiap User].
        """
        try:
            res = await generate_smart_response(prompt)
            self.learned_context["summary"] = res.text
            save_json_file(LEARNED_FILE_PATH, self.learned_context)
            await msg_wait.edit(content="Selesai! Otak gw udah di-update dan numpuk data lama dengan data baru. Cek pakai `!ai hasil_belajar`.")
        except Exception as e:
            await msg_wait.edit(content=f"Gagal belajar cuy: {e}")

    @ai.command(name="revisi_belajar")
    @commands.is_owner()
    async def revise_learning(self, ctx, *, instruksi: str):
        msg = await ctx.reply("Merapihkan isi otak, bentar...")
        success = await self.apply_db_correction(instruksi)
        if success:
            await msg.edit(content="Sip, memori Hasil Belajar udah direvisi sesuai perintah lu bos.")
        else:
            await msg.edit(content="Gagal merevisi otak. Coba lagi nanti.")

    @ai.command(name="hasil_belajar")
    async def show_learned_data(self, ctx):
        learned = self.learned_context.get("summary", "Belum ada data.")
        try:
            await send_long_message(ctx, f"**Hasil Analisis Tongkrongan Jarkasih:**\n\n{learned}")
        except Exception as e:
            await ctx.reply(f"Gagal menampilkan data: {e}")

    @ai.command(name="auto_tag_toggle")
    @commands.is_owner()
    async def toggle_auto_tag(self, ctx):
        guild_id_str = str(ctx.guild.id)
        if guild_id_str in self.auto_config["active_guilds"]:
            self.auto_config["active_guilds"].remove(guild_id_str)
            status = "MATI"
        else:
            self.auto_config["active_guilds"].append(guild_id_str)
            status = "NYALA"
        save_json_file(AUTO_CONFIG_PATH, self.auto_config)
        await ctx.reply(f"Fitur auto-nimbrung Jarkasih di-tag sekarang: **{status}**")

    @ai.command(name="latih")
    @commands.is_owner()
    async def train_menu(self, ctx):
        await ctx.reply("Menu Latihan:", view=TrainView(self))

    @ai.command(name="ingatan")
    async def show_brain(self, ctx):
        embed = discord.Embed(title="Isi Otak", color=discord.Color.green())
        kws = list(self.brain.get('keywords', {}).keys())
        arts = [a['title'] for a in self.brain.get('articles', [])]
        embed.add_field(name=f"Kamus ({len(kws)})", value=", ".join(kws[:20]) or "Kosong", inline=False)
        embed.add_field(name=f"Artikel ({len(arts)})", value="\n".join(arts[:10]) or "Kosong", inline=False)
        await ctx.reply(embed=embed)

    @ai.command(name="hapus_artikel")
    @commands.is_owner()
    async def delete_article(self, ctx, *, title: str):
        self.brain['articles'] = [a for a in self.brain['articles'] if a['title'].lower() != title.lower()]
        save_json_file(BRAIN_FILE_PATH, self.brain)
        await ctx.reply(f"Dihapus: {title}")

    @ai.command(name="lupakan")
    @commands.is_owner()
    async def forget_brain(self, ctx, keyword: str):
        if keyword.lower() in self.brain.get('keywords', {}):
            del self.brain['keywords'][keyword.lower()]
            save_json_file(BRAIN_FILE_PATH, self.brain)
            await ctx.reply(f"Dihapus: {keyword}")
        else: await ctx.reply("Ga ada.")

    @ai.command(name="tambah_kata")
    @commands.is_owner()
    async def add_kw(self, ctx, *k):
        self.data['sensitive_keywords'].extend([x for x in k if x not in self.data['sensitive_keywords']])
        save_json_file(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="hapus_kata")
    @commands.is_owner()
    async def rm_kw(self, ctx, *k):
        self.data['sensitive_keywords'] = [x for x in self.data['sensitive_keywords'] if x not in k]
        save_json_file(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")
        
    @ai.command(name="tambah_tld")
    @commands.is_owner()
    async def add_tld(self, ctx, *t):
        self.data['suspicious_tlds'].extend([x if x.startswith('.') else f".{x}" for x in t if (x if x.startswith('.') else f".{x}") not in self.data['suspicious_tlds']])
        save_json_file(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="hapus_tld")
    @commands.is_owner()
    async def rm_tld(self, ctx, *t):
        self.data['suspicious_tlds'] = [x for x in self.data['suspicious_tlds'] if x not in [y if y.startswith('.') else f".{y}" for y in t]]
        save_json_file(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="tambah_whitelist")
    @commands.is_owner()
    async def add_wl(self, ctx, *d):
        self.data['domain_whitelist'].extend([x.split('//')[-1].split('/')[0].replace('www.', '') for x in d if x not in self.data['domain_whitelist']])
        save_json_file(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="hapus_whitelist")
    @commands.is_owner()
    async def rm_wl(self, ctx, *d):
        rm = [x.split('//')[-1].split('/')[0].replace('www.', '') for x in d]
        self.data['domain_whitelist'] = [x for x in self.data['domain_whitelist'] if x not in rm]
        save_json_file(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="ngobrol")
    async def ngobrol_start(self, ctx):
        if ctx.channel.id in self.active_chats: return await ctx.reply("Udah aktif.")
        try:
            model = genai.GenerativeModel(GEMINI_MODELS[0])
            self.active_chats[ctx.channel.id] = model.start_chat(history=[])
            await ctx.reply("Jarkasih hadir.")
        except Exception as e: await ctx.reply(f"Gagal: {e}")

    @ai.command(name="selesai")
    async def ngobrol_stop(self, ctx):
        if ctx.channel.id in self.active_chats: del self.active_chats[ctx.channel.id]; await ctx.reply("Bye.")
        else: await ctx.reply("Ga ada sesi.")

    @ai.command(name="reset")
    async def reset_chat(self, ctx):
        if ctx.channel.id in self.active_chats: del self.active_chats[ctx.channel.id]
        await self.ngobrol_start.callback(self, ctx)
        await ctx.reply("Reset.")

    @ai.command(name="atur")
    @commands.is_owner()
    async def set_inst(self, ctx, *, i: str):
        self.system_instructions[ctx.channel.id] = i
        await ctx.reply("Sip.")

    @ai.command(name="tanya")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def tanya(self, ctx, *, prompt: str):
        async with ctx.typing():
            ctx_data = self.get_brain_context(prompt)
            await self.process_and_send_response(ctx, ctx.author, ctx_data, prompt)

    @commands.command(name="jiwaku")
    @commands.guild_only()
    async def start_personality_test(self, ctx):
        if ctx.author.id in self.active_sessions: return await ctx.send("Udah mulai woi.", ephemeral=True)
        if not self.questions: return await ctx.send("Database soal kosong.", ephemeral=True)
        try:
            thread = await ctx.channel.create_thread(name=f"Diagnosa-{ctx.author.name}", type=discord.ChannelType.private_thread)
            await thread.add_user(ctx.author)
            await ctx.send(f"Masuk: <#{thread.id}>", ephemeral=False)
            self.active_sessions[ctx.author.id] = {
                'thread': thread, 'current_q_idx': 0, 'scores': {d:0 for d in self._get_all_dimensions()},
                'user_obj': ctx.author, 'questions_for_session': random.sample(self.questions, min(len(self.questions), 50)),
                'message_for_reaction_vote': None, 'answered_this_question': False
            }
            await self._send_question(ctx.author.id)
        except Exception as e: await ctx.send(f"Error: {e}", ephemeral=True)

    async def _send_question(self, user_id):
        session = self.active_sessions.get(user_id)
        if not session: return
        if session['current_q_idx'] >= len(session['questions_for_session']): return await self._end_session(user_id)
        q = session['questions_for_session'][session['current_q_idx']]
        embed = discord.Embed(title=f"Diagnosa #{session['current_q_idx']+1}", description=f"**{q['question']}**\n\n1. {q['options']['A']}\n2. {q['options']['B']}", color=discord.Color.dark_magenta())
        msg = await session['thread'].send(embed=embed)
        session['message_for_reaction_vote'] = msg
        await msg.add_reaction("1\u20E3"); await msg.add_reaction("2\u20E3")
        session['answered_this_question'] = False

    async def _process_answer(self, user_id, choice, msg, user):
        session = self.active_sessions.get(user_id)
        q = session['questions_for_session'][session['current_q_idx']]
        for d, p in q['scores'].get(choice, {}).items(): session['scores'][d] = session['scores'].get(d, 0) + p
        session['current_q_idx'] += 1
        await self._send_question(user_id)

    def _get_all_dimensions(self):
        dims = set()
        for q in self.questions:
            for o in q['options']:
                for d in q['scores'].get(o, {}): dims.add(d)
        return list(dims)

    async def _end_session(self, user_id):
        session = self.active_sessions.pop(user_id)
        await session['thread'].send("Analisis...", embed=discord.Embed(title="Loading...", color=discord.Color.gold()))
        await asyncio.sleep(2)
        await self._analyze_and_present_results(session['thread'], session['user_obj'], session['scores'])
        asyncio.create_task(self._delete_thread_after_delay(session['thread'], 180))

    async def _delete_thread_after_delay(self, thread, delay):
        await asyncio.sleep(delay)
        try: await thread.delete()
        except: pass

    async def _analyze_and_present_results(self, thread, user, scores):
        if not self.results_config.get('dimensions'): return await thread.send("Config error.")
        stype, sdesc = "Alien", ""
        ie_score = scores.get("introvert", 0) - scores.get("ekstrovert", 0)
        if "introvert_ekstrovert" in self.results_config['dimensions']:
            for t in self.results_config['dimensions']['introvert_ekstrovert'].get('thresholds', []):
                if t['min_score'] <= ie_score <= t['max_score']: stype, sdesc = t['type'], t.get('description', '')
        
        traits = []
        for ctype in ["sifat_dasar", "gaya_interaksi"]:
            if ctype in self.results_config['dimensions']:
                for c in self.results_config['dimensions'][ctype].get('categories', []):
                    dname = c['name'].lower().replace(" ", "_")
                    if scores.get(dname, 0) >= c.get('min_score', 0): traits.append(c)
        traits.sort(key=lambda x: scores.get(x['name'].lower().replace(" ", "_"), 0), reverse=True)
        
        embed1 = discord.Embed(title=f"Hasil: {user.display_name}", description=f"Tipe: **{stype}**", color=discord.Color.red())
        embed1.add_field(name="Top Traits", value="\n".join([f"• {t['name']}" for t in traits[:3]]) or "-", inline=False)
        embed2 = discord.Embed(title="Detail", color=discord.Color.blue())
        embed2.add_field(name=stype, value=sdesc or "-", inline=False)
        embed3 = discord.Embed(title="Sifat", color=discord.Color.green())
        embed3.add_field(name="List", value="\n".join([f"**{t['name']}**: {t['description']}" for t in traits])[:1024] or "-", inline=False)
        embed4 = discord.Embed(title="Saran Jarkasih", color=discord.Color.orange())
        recos = []
        types = [stype] + [t['name'] for t in traits]
        for k in ["advice", "critique", "future_steps"]:
            for i in self.results_config.get(k, []):
                if i.get('for_type') in types: recos.append(f"• {i['text']}")
        embed4.add_field(name="Resep", value="\n".join(recos)[:1024] or "Ga ada obat.", inline=False)
        
        for e in [embed1, embed2, embed3, embed4]: await thread.send(embed=e)

async def setup(bot):
    await bot.add_cog(AutomationAI(bot))
