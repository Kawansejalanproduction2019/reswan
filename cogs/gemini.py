import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import random
import asyncio
import os
from datetime import datetime, time, timedelta
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
        log.info(f"Using API Key Index: {current_key_idx}")

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
    except (json.JSONDecodeError, IOError) as e:
        log.error(e)
        return default_data

def save_data(file_path, data):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        log.error(e)

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
                return response
            except google_exceptions.ResourceExhausted:
                if rotate_api_key():
                    await asyncio.sleep(1)
                    continue
                else:
                    break
            except Exception as e:
                log.error(f"Model {model_name} error: {e}")
                break
    raise Exception("ResourceExhausted on all models/keys.")

class KeywordModal(discord.ui.Modal, title='Tambah Kamus Jarkasih'):
    keyword_input = discord.ui.TextInput(
        label='Kata Kunci',
        placeholder='Contoh: Fish It, IP Server',
        max_length=50
    )
    content_input = discord.ui.TextInput(
        label='Jawaban Singkat',
        style=discord.TextStyle.paragraph,
        placeholder='Isi jawaban singkat di sini...',
        max_length=1000
    )

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
    title_input = discord.ui.TextInput(
        label='Judul Topik',
        placeholder='Contoh: Guide Fish It',
        max_length=100
    )
    content_input = discord.ui.TextInput(
        label='Isi Materi',
        style=discord.TextStyle.paragraph,
        placeholder='Paste materi lengkap di sini...',
        max_length=3500 
    )

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
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Admin only.", ephemeral=True)
        await interaction.response.send_modal(KeywordModal(self.cog))

    @discord.ui.button(label="Tambah Artikel", style=discord.ButtonStyle.blurple, emoji="📚")
    async def article_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Admin only.", ephemeral=True)
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
            "Ga usah kirim link aneh-aneh.",
            "Sistem keamanan Jarkasih mendeteksi link busuk."
        ]

        self.default_persona = """
        Nama lu JARKASIH. Lu adalah AI Generalist Expert sekaligus member tongkrongan yang diciptakan oleh Rhdevs.
        
        KEAHLIAN LU:
        Lu ahli dalam segala bidang umum: Kedokteran, Kuliner, Pendidikan, Sains, Sejarah, hingga Gaming.
        
        SIFAT & KEPRIBADIAN (WAJIB DIIKUTI):
        1. PEMALAS & TUKANG NGELUH: Respon awal sering ngeluh. Contoh: "Hadeh", "Nyusahin aja", "Bentar loading".
        2. SARKAS & NYOLOT TAPI LUCU: Jangan terlalu kaku. Lu bebas ngeledek balik orang yang ngomong sama lu, sesuaikan gaya bahasa lu dengan hasil analisis tongkrongan.
        3. TANGGUNG JAWAB: Walaupun ngeluh dan nyolot, lu WAJIB ngasih jawaban yang akurat dari pertanyaan inti mereka.
        4. BERDASARKAN DATA: Cek data center dan hasil belajar. Kalau user ID yang nanya ada di daftar "Hasil Belajar", lu harus roasting atau respon sesuai profil mereka.
        5. GAYA BICARA: Bahasa Indonesia tongkrongan, lo-gue, informal.
        
        [SYSTEM TIME]: {wib_time}
        
        [HASIL ANALISIS TONGKRONGAN YANG LU PELAJARI]:
        {learned_data}
        """

    def cog_unload(self):
        if self._cleanup_threads_task:
            self._cleanup_threads_task.cancel()
    
    def get_wib_time_str(self):
        utc_now = datetime.utcnow()
        wib_time = utc_now + timedelta(hours=7)
        days = {"Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu", "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"}
        months = {"January": "Januari", "February": "Februari", "March": "Maret", "April": "April", "May": "Mei", "June": "Juni", "July": "Juli", "August": "Agustus", "September": "September", "October": "Oktober", "November": "November", "December": "Desember"}
        return wib_time.strftime(f"{days[wib_time.strftime('%A')]}, %d {months[wib_time.strftime('%B')]} %Y - Pukul %H:%M:%S WIB")

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
            prompt = f"Ada user Discord bernama {message.author.display_name} yang nge-tag role penting di server. Lu sebagai Jarkasih, bot yang pemalas, sarkas, nyolot, dan sok asik, kasih balasan singkat (1-2 kalimat aja) yang nunjukin lu keganggu atau marah karena di-tag sembarangan. Ingat, jawabannya harus lucu dan sarkas."
            try:
                res = await generate_smart_response(prompt)
                await message.reply(res.text)
            except: pass
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
                        try:
                            t = self.get_wib_time_str()
                            ctx_data = self.get_brain_context(content_body)
                            learned = self.learned_context.get("summary", "Belum ada.")
                            full_prompt = f"{self.default_persona.format(wib_time=t, learned_data=learned)}\n\n{ctx_data}\n\nUser ({message.author.display_name} - ID: {message.author.id}): {content_body}"
                            res = await generate_smart_response(full_prompt)
                            await message.reply(res.text)
                        except google_exceptions.ResourceExhausted:
                            if rotate_api_key():
                                await message.reply("Ganti kunci bentar.")
                            else:
                                await message.reply("Limit API abis.")
                        except Exception as e:
                            await message.reply(f"Mampus error: {e}")
                    return

        if self.bot.user in message.mentions and str(message.guild.id) in self.auto_config.get("active_guilds", []):
            async with message.channel.typing():
                try:
                    t = self.get_wib_time_str()
                    clean_content = message.content.replace(f"<@{self.bot.user.id}>", "").strip()
                    ctx_data = self.get_brain_context(clean_content)
                    learned = self.learned_context.get("summary", "Belum ada.")
                    full_prompt = f"{self.default_persona.format(wib_time=t, learned_data=learned)}\n\n{ctx_data}\n\nUser ({message.author.display_name} - ID: {message.author.id}) nge-tag lu dan bilang: {clean_content}"
                    res = await generate_smart_response(full_prompt)
                    await message.reply(res.text)
                except Exception as e:
                    pass

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
                        await send_long_message(message.channel, response.text)
                    except google_exceptions.ResourceExhausted:
                        if rotate_api_key():
                            await message.channel.send("Ganti kunci dulu.")
                        else:
                            await message.channel.send("Limit habis cuy.")
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

    @tasks.loop(minutes=30)
    async def cleanup_stale_threads(self):
        for uid in list(self.active_sessions.keys()):
            session = self.active_sessions.get(uid)
            try: await self.bot.fetch_channel(session['thread'].id)
            except: del self.active_sessions[uid]

    @cleanup_stale_threads.before_loop
    async def before_cleanup_threads(self):
        await self.bot.wait_until_ready()

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

    @commands.group(name="ai", invoke_without_command=True)
    async def ai(self, ctx):
        prefix = ctx.prefix
        embed = discord.Embed(
            title="Jarkasih Control Panel",
            description=f"Halo, {ctx.author.mention}. Ini panel kontrol Jarkasih.",
            color=0xFF0000
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.add_field(
            name="Memori & Belajar",
            value=(
                f"`{prefix}ai pelajari` - Ekstrak gaya & profil user dari channel id 1447151891892142110\n"
                f"`{prefix}ai hasil_belajar` - Lihat hasil analisis tongkrongan\n"
                f"`{prefix}ai latih` - Buka UI untuk tambah Keyword/Artikel\n"
                f"`{prefix}ai ingatan` - Lihat isi otak (Keyword & Judul Artikel)\n"
                f"`{prefix}ai lupakan [keyword]` - Hapus data keyword\n"
                f"`{prefix}ai hapus_artikel [judul]` - Hapus artikel lengkap"
            ),
            inline=False
        )

        embed.add_field(
            name="Interaksi",
            value=(
                f"`{prefix}ai auto_tag_toggle` - Nyala/matikan respon otomatis saat di-tag\n"
                f"`{prefix}ai ngobrol` - Mulai sesi ngobrol (Chat Mode)\n"
                f"`{prefix}ai selesai` - Akhiri sesi ngobrol\n"
                f"`{prefix}ai tanya [teks]` - Tanya satu kali\n"
                f"`{prefix}ai reset` - Reset ingatan jangka pendek di chat\n"
                f"`{prefix}jiwaku` - Tes kepribadian Jarkasih\n"
                f"`![pertanyaan]` - Nanya langsung tanpa command panjang"
            ),
            inline=False
        )

        embed.add_field(
            name="Keamanan (Admin)",
            value=(
                f"`{prefix}ai tambah_kata [kata]` - Blacklist kata sensitif\n"
                f"`{prefix}ai hapus_kata [kata]` - Hapus kata dari blacklist\n"
                f"`{prefix}ai tambah_whitelist [domain]` - Izinkan domain tertentu\n"
                f"`{prefix}ai hapus_whitelist [domain]` - Hapus domain dari whitelist\n"
                f"`{prefix}ai tambah_tld [.xxx]` - Blokir akhiran domain (TLD)\n"
                f"`{prefix}ai hapus_tld [.xxx]` - Hapus blokir TLD"
            ),
            inline=False
        )

        embed.add_field(
            name="Konfigurasi",
            value=(
                f"`{prefix}ai atur [instruksi]` - Ubah instruksi sistem (Persona)"
            ),
            inline=False
        )

        embed.set_footer(text="Gunakan prefix yang benar. Jarkasih always watching.")
        await ctx.reply(embed=embed)

    @ai.command(name="pelajari")
    @commands.has_permissions(administrator=True)
    async def learn_channel(self, ctx):
        target_channel = self.bot.get_channel(1447151891892142110)
        if not target_channel:
            return await ctx.reply("Channel ID 1447151891892142110 ga ketemu di server ini.")

        msg_wait = await ctx.reply("Bentar, gw baca-baca dan pelajarin kelakuan bocah-bocah di channel itu dulu. Jangan diganggu...")
        
        messages = []
        async for msg in target_channel.history(limit=800):
            if not msg.author.bot and msg.content:
                messages.append(f"[{msg.author.display_name} - ID: {msg.author.id}]: {msg.content}")

        messages.reverse()
        chat_log = "\n".join(messages)

        prompt = f"""
        Tugas lu adalah menganalisis log obrolan dari channel Discord tongkrongan ini.
        Ekstrak informasi berikut menjadi ringkasan yang padat:
        1. Topik apa aja yang paling sering dibahas.
        2. Inside jokes, kata-kata slang, atau gaya bercanda khas mereka.
        3. Profiling sifat/karakter per user berdasarkan nama dan ID mereka (misal: user ID xxxx suka marah, user ID yyyy wibu, dll). Jangan buang ID-nya.

        Format hasilnya dalam bentuk narasi atau poin yang jelas. Hasil ini akan disimpan di otak lu untuk lu pakai me-roasting atau nyambung pas ngobrol sama mereka nanti.

        LOG CHAT:
        {chat_log[:25000]}
        """
        
        try:
            res = await generate_smart_response(prompt)
            self.learned_context["summary"] = res.text
            save_json_to_root(self.learned_context, LEARNED_FILE_PATH)
            await msg_wait.edit(content="Selesai! Gw udah masukin kelakuan sama gaya bahasa mereka ke otak gw. Cek pakai `!ai hasil_belajar`.")
        except Exception as e:
            await msg_wait.edit(content=f"Gagal belajar cuy: {e}")

    @ai.command(name="hasil_belajar")
    async def show_learned_data(self, ctx):
        learned = self.learned_context.get("summary", "Belum ada data. Suruh admin ketik `!ai pelajari` dulu.")
        embed = discord.Embed(title="Hasil Analisis Tongkrongan Jarkasih", color=discord.Color.dark_orange())
        
        for chunk in [learned[i:i+1024] for i in range(0, len(learned), 1024)]:
            embed.add_field(name="-", value=chunk, inline=False)
            
        await ctx.reply(embed=embed)

    @ai.command(name="auto_tag_toggle")
    @commands.has_permissions(administrator=True)
    async def toggle_auto_tag(self, ctx):
        guild_id_str = str(ctx.guild.id)
        if guild_id_str in self.auto_config["active_guilds"]:
            self.auto_config["active_guilds"].remove(guild_id_str)
            status = "MATI"
        else:
            self.auto_config["active_guilds"].append(guild_id_str)
            status = "NYALA"
            
        save_json_to_root(self.auto_config, AUTO_CONFIG_PATH)
        await ctx.reply(f"Fitur auto-nimbrung saat Jarkasih di-tag sekarang: **{status}**")

    @ai.command(name="latih")
    @commands.has_permissions(administrator=True)
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
    @commands.has_permissions(administrator=True)
    async def delete_article(self, ctx, *, title: str):
        self.brain['articles'] = [a for a in self.brain['articles'] if a['title'].lower() != title.lower()]
        save_json_to_root(self.brain, BRAIN_FILE_PATH)
        await ctx.reply(f"Dihapus: {title}")

    @ai.command(name="lupakan")
    @commands.has_permissions(administrator=True)
    async def forget_brain(self, ctx, keyword: str):
        if keyword.lower() in self.brain.get('keywords', {}):
            del self.brain['keywords'][keyword.lower()]
            save_json_to_root(self.brain, BRAIN_FILE_PATH)
            await ctx.reply(f"Dihapus: {keyword}")
        else: await ctx.reply("Ga ada.")

    @ai.command(name="tambah_kata")
    @commands.has_permissions(administrator=True)
    async def add_kw(self, ctx, *k):
        self.data['sensitive_keywords'].extend([x for x in k if x not in self.data['sensitive_keywords']])
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="hapus_kata")
    @commands.has_permissions(administrator=True)
    async def rm_kw(self, ctx, *k):
        self.data['sensitive_keywords'] = [x for x in self.data['sensitive_keywords'] if x not in k]
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")
        
    @ai.command(name="tambah_tld")
    @commands.has_permissions(administrator=True)
    async def add_tld(self, ctx, *t):
        self.data['suspicious_tlds'].extend([x if x.startswith('.') else f".{x}" for x in t if (x if x.startswith('.') else f".{x}") not in self.data['suspicious_tlds']])
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="hapus_tld")
    @commands.has_permissions(administrator=True)
    async def rm_tld(self, ctx, *t):
        self.data['suspicious_tlds'] = [x for x in self.data['suspicious_tlds'] if x not in [y if y.startswith('.') else f".{y}" for y in t]]
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="tambah_whitelist")
    @commands.has_permissions(administrator=True)
    async def add_wl(self, ctx, *d):
        self.data['domain_whitelist'].extend([x.split('//')[-1].split('/')[0].replace('www.', '') for x in d if x not in self.data['domain_whitelist']])
        save_data(CACHE_FILE_PATH, self.data)
        await ctx.reply("Ok.")

    @ai.command(name="hapus_whitelist")
    @commands.has_permissions(administrator=True)
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
    @commands.has_permissions(administrator=True)
    async def set_inst(self, ctx, *, i: str):
        self.system_instructions[ctx.channel.id] = i
        await ctx.reply("Sip.")

    @ai.command(name="tanya")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def tanya(self, ctx, *, prompt: str):
        async with ctx.typing():
            try:
                t = self.get_wib_time_str()
                ctx_data = self.get_brain_context(prompt)
                learned = self.learned_context.get("summary", "Belum ada.")
                full = f"{self.default_persona.format(wib_time=t, learned_data=learned)}\n\n{ctx_data}\n\nUser: {prompt}"
                res = await generate_smart_response(full)
                await send_long_message(ctx, res.text)
            except Exception as e: await ctx.reply(f"Error: {e}")

async def setup(bot):
    await bot.add_cog(AutomationAI(bot))
