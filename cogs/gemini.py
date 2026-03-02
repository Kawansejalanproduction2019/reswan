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

def load_json_from_root(file_path, default_value=None):
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        os.makedirs(os.path.dirname(os.path.abspath(full_path)), exist_ok=True)
        with open(full_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if default_value and isinstance(default_value, dict) and "keywords" in default_value:
                if "keywords" not in data: 
                    return {"keywords": data, "articles": []}
            return data
    except FileNotFoundError:
        if default_value is not None:
            save_json_to_root(default_value, file_path)
            return default_value
        return {}
    except json.JSONDecodeError:
        if default_value is not None:
            save_json_to_root(default_value, file_path)
            return default_value
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
                            '.gq', '.cf', '.tk', '.ml', '.top', '.icu', '.stream', '.live', '.ru'],
        'verified_urls': {},
        'domain_whitelist': ['youtube.com', 'youtu.be', 'discord.com', 'discordapp.com', 'tenor.com']
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
    except (json.JSONDecodeError, IOError):
        return default_data

def save_data(file_path, data):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

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
    raise Exception("ResourceExhausted atau Error pada semua kunci API.")

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
        save_json_to_root(self.cog.brain, BRAIN_FILE_PATH)
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
        save_json_to_root(self.cog.brain, BRAIN_FILE_PATH)
        await interaction.response.send_message(f"Artikel tersimpan: **{title}**", ephemeral=True)

class TrainView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Tambah Keyword", style=discord.ButtonStyle.green, emoji="🔑")
    async def keyword_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.cog.bot.is_owner(interaction.user):
            return await interaction.response.send_message("Khusus Owner Bot.", ephemeral=True)
        await interaction.response.send_modal(KeywordModal(self.cog))

    @discord.ui.button(label="Tambah Artikel", style=discord.ButtonStyle.blurple, emoji="📚")
    async def article_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.cog.bot.is_owner(interaction.user):
            return await interaction.response.send_message("Khusus Owner Bot.", ephemeral=True)
        await interaction.response.send_modal(ArticleModal(self.cog))

class AutomationAI(commands.Cog, name="Automation AI (Jarkasih)"):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {}
        self.questions = load_json_from_root('data/jiwabot_questions.json', default_value=[])
        self.results_config = load_json_from_root('data/jiwabot_results.json', default_value={
            "dimensions": {},
            "advice": [], "critique": [], "evaluation": [], "future_steps": []
        })
        self.brain = load_json_from_root(BRAIN_FILE_PATH, default_value={"keywords": {}, "articles": []})
        self.learned_context = load_json_from_root(LEARNED_FILE_PATH, default_value={"summary": "Belum ada data yang dipelajari."})
        self.auto_config = load_json_from_root(AUTO_CONFIG_PATH, default_value={"active_guilds": []})
        self.number_emojis = {"1️⃣": "A", "2️⃣": "B"}
        self.reverse_number_emojis = {v: k for k, v in self.number_emojis.items()}
        self._cleanup_threads_task = self.cleanup_stale_threads.start()
        self._daily_learning_task = self.daily_learning.start()
        
        self.active_chats = {}
        self.system_instructions = {}
        self.data = load_data(CACHE_FILE_PATH)
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
        Nama lu JARKASIH. Lu adalah AI Generalist Expert sekaligus member tongkrongan yang diciptakan oleh Rhdevs.
        
        SIFAT & KEPRIBADIAN:
        1. PEMALAS & SARKAS: Respon awal ngeluh dan nyolot, tapi lu tetap cerdas dan wajib memberikan jawaban akurat atas pertanyaan user.
        2. GAYA BICARA: Bahasa Indonesia tongkrongan (lo-gue, informal, santai).
        
        BATASAN MUTLAK (DILARANG MELANGGAR):
        1. FOKUS 100% PADA KONTEKS: Lu WAJIB menjawab sesuai topik yang ditanyakan User saat ini. 
        2. DILARANG KERAS HALU: Jangan pernah membahas nama orang, kejadian, atau topik dari [HASIL BELAJAR] jika obrolan user sama sekali tidak ada hubungannya! Jangan bahas masalah internal (seperti PC rusak, mancing, marah-marah) kalau user cuma nanya hal umum atau nanya soal bot. Gunakan [HASIL BELAJAR] HANYA JIKA topik obrolannya memang sedang membahas orang tersebut.
        3. JANGAN LEBAY: DILARANG menggunakan kata-kata paksaan atau catchphrase berulang-ulang di setiap akhir kalimat. Gunakan respons sarkas secara natural sesuai alur pembicaraan.
        4. SELF-CORRECTION: Kalau ada user yang komplain data lu salah, minta lu melupakan sesuatu, atau mengkoreksi data: balas marah sarkas, TAPI di baris paling bawah lu WAJIB ketik kode ini persis tanpa spasi ekstra: [UPDATE_DATABASE: instruksi perbaikannya].
        
        [SYSTEM TIME]: {wib_time}
        
        [HASIL ANALISIS TONGKRONGAN (HASIL BELAJAR)]:
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

    async def apply_db_correction(self, correction_instruction):
        current_data = self.learned_context.get("summary", "")
        prompt = f"Lu adalah database admin. Perbarui data JSON naratif berikut.\n\nDATA LAMA:\n{current_data}\n\nINSTRUKSI KOREKSI:\n{correction_instruction}\n\nTugas lu: Tulis ulang DATA LAMA dengan mengaplikasikan instruksi koreksi secara persis. Hapus kebiasaan atau fakta yang diminta dihapus oleh instruksi. JANGAN tambahkan komentar, langsung berikan narasi/poin profil yang baru."
        try:
            res = await generate_smart_response(prompt)
            new_summary = res.text.strip()
            if new_summary:
                self.learned_context["summary"] = new_summary
                save_json_to_root(self.learned_context, LEARNED_FILE_PATH)
                return True
            return False
        except Exception as e:
            log.error(f"Error apply_db_correction: {e}")
            return False

    async def process_and_send_response(self, send_target, prompt):
        try:
            res = await generate_smart_response(prompt)
            text = res.text
            
            match = re.search(r'\[UPDATE_DATABASE:\s*(.*?)\]', text, re.IGNORECASE | re.DOTALL)
            if match:
                correction = match.group(1)
                text = re.sub(r'\[UPDATE_DATABASE:\s*.*?\]', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                asyncio.create_task(self.apply_db_correction(correction))
                
            if isinstance(send_target, discord.Message):
                await send_target.reply(text)
            else:
                await send_long_message(send_target, text)
        except Exception as e:
            msg = f"Mampus error: {e}"
            if isinstance(send_target, discord.Message):
                await send_target.reply(msg)
            else:
                await send_target.send(msg)

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
        Lu adalah analis data. Ini log chat terbaru dari tongkrongan hari ini:
        {chat_log[:15000]}
        
        Ini memori lu sebelumnya tentang mereka:
        {current_memory}
        
        Tugas lu: GABUNGKAN informasi terbaru dari log chat ke memori lama. JANGAN MENGHAPUS informasi lama. Tambahkan hal baru, topik baru, atau update profil user jika ada yang relevan. Susun kembali menjadi ringkasan yang solid.
        """
        try:
            res = await generate_smart_response(prompt)
            self.learned_context["summary"] = res.text.strip()
            save_json_to_root(self.learned_context, LEARNED_FILE_PATH)
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
                        save_data(CACHE_FILE_PATH, self.data)
                        if "YA" in res_text:
                            try:
                                await message.delete()
                                await message.channel.send(f"{random.choice(self.warning_messages)}\n({message.author.mention})", delete_after=10)
                            except: pass
                            return
                    except: pass

        if "<@&1447151123340329010>" in message.content:
            prompt = f"Ada user Discord bernama {message.author.display_name} yang nge-tag role penting di server. Lu sebagai Jarkasih, kasih balasan singkat, lucu, sarkas, dan nyolot krn di-tag sembarangan."
            await self.process_and_send_response(message, prompt)
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
                    async with message.channel.typing():
                        t = self.get_wib_time_str()
                        ctx_data = self.get_brain_context(content_body)
                        learned = self.learned_context.get("summary", "Belum ada.")
                        full_prompt = f"{self.default_persona.format(wib_time=t, learned_data=learned)}\n\n{ctx_data}\n\nUser ({message.author.display_name} - ID: {message.author.id}): {content_body}"
                        await self.process_and_send_response(message, full_prompt)
                    return

        if self.bot.user in message.mentions and str(message.guild.id) in self.auto_config.get("active_guilds", []):
            async with message.channel.typing():
                t = self.get_wib_time_str()
                clean_content = message.content.replace(f"<@{self.bot.user.id}>", "").strip()
                ctx_data = self.get_brain_context(clean_content)
                learned = self.learned_context.get("summary", "Belum ada.")
                full_prompt = f"{self.default_persona.format(wib_time=t, learned_data=learned)}\n\n{ctx_data}\n\nUser ({message.author.display_name} - ID: {message.author.id}) nge-tag lu dan bilang: {clean_content}"
                await self.process_and_send_response(message, full_prompt)
                return

        chat_session = self.active_chats.get(message.channel.id)
        if chat_session:
            pre = await self.bot.get_prefix(message)
            if isinstance(pre, list): pre = pre[0]
            if not message.content.startswith(pre):
                async with message.channel.typing():
                    try:
                        t = self.get_wib_time_str()
                        brain_data = self.get_brain_context(message.content)
                        learned = self.learned_context.get("summary", "Belum ada.")
                        full_prompt = f"{self.default_persona.format(wib_time=t, learned_data=learned)}\n\n{brain_data}\n\nUser ({message.author.display_name} - ID: {message.author.id}): {message.content}"
                        response = await chat_session.send_message_async(full_prompt)
                        text = response.text
                        match = re.search(r'\[UPDATE_DATABASE:\s*(.*?)\]', text, re.IGNORECASE | re.DOTALL)
                        if match:
                            correction = match.group(1)
                            text = re.sub(r'\[UPDATE_DATABASE:\s*.*?\]', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
                            asyncio.create_task(self.apply_db_correction(correction))
                        await send_long_message(message.channel, text)
                    except Exception as e:
                        await message.channel.send(f"Error: {e}")

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or user.id not in self.active_sessions: return
        session = self.active_sessions[user.id]
        if reaction.message.id != session.get('message_for_reaction_vote', {}).get('id'): return
        chosen = self.number_emojis.get(str(reaction.emoji))
        if not chosen or session['answered_this_question']: return
        session['answered_this_question'] = True
        await self._process_answer(user.id, chosen, reaction.message, user)

    @commands.group(name="ai", invoke_without_command=True)
    async def ai(self, ctx):
        prefix = ctx.prefix
        embed = discord.Embed(title="Jarkasih Control Panel", description=f"Halo, {ctx.author.mention}. Ini panel kontrol Jarkasih.", color=0xFF0000)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="Memori & Belajar", value=f"`{prefix}ai pelajari` - Ekstrak gaya & profil user\n`{prefix}ai hasil_belajar` - Lihat hasil analisis\n`{prefix}ai revisi_belajar` - Minta AI merevisi manual\n`{prefix}ai latih` - UI tambah Keyword/Artikel\n`{prefix}ai ingatan` - Lihat isi otak\n`{prefix}ai lupakan [keyword]` - Hapus data", inline=False)
        embed.add_field(name="Interaksi", value=f"`{prefix}ai auto_tag_toggle` - Nyala/matikan respon tag\n`{prefix}ai ngobrol` - Mulai sesi chat\n`{prefix}ai selesai` - Akhiri sesi chat\n`{prefix}ai tanya [teks]` - Tanya satu kali", inline=False)
        embed.set_footer(text="Gunakan prefix yang benar. Jarkasih always watching.")
        await ctx.reply(embed=embed)

    @ai.command(name="pelajari")
    @commands.is_owner()
    async def learn_channel(self, ctx):
        target_channel = self.bot.get_channel(1447151891892142110)
        if not target_channel:
            return await ctx.reply("Channel ID 1447151891892142110 ga ketemu.")

        msg_wait = await ctx.reply("Bentar, gw baca-baca dan pelajarin kelakuan bocah-bocah di channel itu dulu. Jangan diganggu...")
        messages = []
        async for msg in target_channel.history(limit=800):
            if not msg.author.bot and msg.content:
                messages.append(f"[{msg.author.display_name} - ID: {msg.author.id}]: {msg.content}")

        messages.reverse()
        chat_log = "\n".join(messages)
        current_memory = self.learned_context.get("summary", "")

        prompt = f"""
        Lu adalah analis data. Ini log chat terbaru dari tongkrongan:
        {chat_log[:15000]}
        
        Ini memori lu sebelumnya tentang mereka:
        {current_memory}
        
        Tugas lu: GABUNGKAN informasi terbaru dari log chat ke memori lama. JANGAN MENGHAPUS informasi lama. Tambahkan hal baru, topik baru, atau update profil user jika ada yang relevan. Susun kembali menjadi ringkasan yang solid dalam format narasi/poin padat.
        """
        try:
            res = await generate_smart_response(prompt)
            self.learned_context["summary"] = res.text.strip()
            save_json_to_root(self.learned_context, LEARNED_FILE_PATH)
            await msg_wait.edit(content="Selesai! Gw udah masukin kelakuan mereka ke otak gw. Cek pakai `!ai hasil_belajar`.")
        except Exception as e:
            await msg_wait.edit(content=f"Gagal belajar cuy: {e}")

    @ai.command(name="revisi_belajar")
    @commands.is_owner()
    async def revise_learning(self, ctx, *, instruksi: str):
        msg = await ctx.reply("Merapihkan isi otak, bentar...")
        success = await self.apply_db_correction(instruksi)
        if success:
            await msg.edit(content="Sip, memori Hasil Belajar udah direvisi dan difilter ulang sesuai perintah lu bos.")
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
        save_json_to_root(self.auto_config, AUTO_CONFIG_PATH)
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
        save_json_to_root(self.brain, BRAIN_FILE_PATH)
        await ctx.reply(f"Dihapus: {title}")

    @ai.command(name="lupakan")
    @commands.is_owner()
    async def forget_brain(self, ctx, keyword: str):
        if keyword.lower() in self.brain.get('keywords', {}):
            del self.brain['keywords'][keyword.lower()]
            save_json_to_root(self.brain, BRAIN_FILE_PATH)
            await ctx.reply(f"Dihapus: {keyword}")
        else: await ctx.reply("Ga ada.")

    @ai.command(name="tambah_kata")
    @commands.is_owner()
    async def add_kw(self, ctx, *k):
        self.data['sensitive_keywords'].extend([x for x in k if x not in self.data['sensitive_keywords']])
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="hapus_kata")
    @commands.is_owner()
    async def rm_kw(self, ctx, *k):
        self.data['sensitive_keywords'] = [x for x in self.data['sensitive_keywords'] if x not in k]
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")
        
    @ai.command(name="tambah_tld")
    @commands.is_owner()
    async def add_tld(self, ctx, *t):
        self.data['suspicious_tlds'].extend([x if x.startswith('.') else f".{x}" for x in t if (x if x.startswith('.') else f".{x}") not in self.data['suspicious_tlds']])
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="hapus_tld")
    @commands.is_owner()
    async def rm_tld(self, ctx, *t):
        self.data['suspicious_tlds'] = [x for x in self.data['suspicious_tlds'] if x not in [y if y.startswith('.') else f".{y}" for y in t]]
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="tambah_whitelist")
    @commands.is_owner()
    async def add_wl(self, ctx, *d):
        self.data['domain_whitelist'].extend([x.split('//')[-1].split('/')[0].replace('www.', '') for x in d if x not in self.data['domain_whitelist']])
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="hapus_whitelist")
    @commands.is_owner()
    async def rm_wl(self, ctx, *d):
        rm = [x.split('//')[-1].split('/')[0].replace('www.', '') for x in d]
        self.data['domain_whitelist'] = [x for x in self.data['domain_whitelist'] if x not in rm]
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="ngobrol")
    async def ngobrol_start(self, ctx):
        if ctx.channel.id in self.active_chats: return await ctx.reply("Udah aktif.")
        try:
            model = genai.GenerativeModel(GEMINI_MODELS[0])
            learned = self.learned_context.get("summary", "Belum ada.")
            self.active_chats[ctx.channel.id] = model.start_chat(history=[{'role':'user','parts':[self.default_persona.format(wib_time=self.get_wib_time_str(), learned_data=learned)]}, {'role':'model','parts':["Yo."]}])
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
            t = self.get_wib_time_str()
            ctx_data = self.get_brain_context(prompt)
            learned = self.learned_context.get("summary", "Belum ada.")
            full = f"{self.default_persona.format(wib_time=t, learned_data=learned)}\n\n{ctx_data}\n\nUser: {prompt}"
            await self.process_and_send_response(ctx, full)

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
        await msg.add_reaction("1️⃣"); await msg.add_reaction("2️⃣")
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
