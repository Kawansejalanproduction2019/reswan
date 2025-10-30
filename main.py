import discord
from discord.ext import commands
import discord.ui as ui
import aiohttp
import base64
import logging
import os
import sys
import io
import asyncio
import json
from io import BytesIO
from pymongo import MongoClient, errors as pymongo_errors
from dotenv import load_dotenv
from datetime import datetime, timezone 
import zipfile

base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))


if base_dir:
    os.chdir(base_dir)


load_dotenv()

class WebhookHandler(logging.Handler):
    def __init__(self, webhook_url):
        super().__init__()
        self.webhook_url = webhook_url
        self.session = None

    def emit(self, record):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.send_log(record))
        except RuntimeError:
            print(self.format(record))
            
    async def send_log(self, record):
        if not self.webhook_url:
            return

        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            
        try:
            log_entry = self.format(record)
            if len(log_entry) > 1900:
                log_entry = log_entry[:1900] + "..."

            embed = {
                "title": f"🚨 Bot Error: {record.levelname}",
                "description": f"```python\n{log_entry}\n```",
                "color": 0xFF0000,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            payload = {"embeds": [embed], "username": "Bot Logger"}
            
            async with self.session.post(self.webhook_url, json=payload) as response:
                if not response.ok:
                    print(f"Gagal mengirim log ke webhook: Status {response.status}")
        except Exception as e:
            print(f"Terjadi error pada WebhookHandler: {e}")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

WEBHOOK_URL = os.getenv("LOG_WEBHOOK_URL")
if WEBHOOK_URL:
    webhook_handler_error = WebhookHandler(WEBHOOK_URL)
    webhook_handler_error.setLevel(logging.ERROR)
    
    root_logger = logging.getLogger()
    root_logger.addHandler(webhook_handler_error)
    log.info("✅ Webhook logger untuk error kritikal telah aktif.")
else:
    log.warning("Variabel LOG_WEBHOOK_URL tidak ditemukan di .env. Logging error ke Discord dinonaktifkan.")

def save_cookies_from_env():
    encoded = os.getenv("COOKIES_BASE64")
    if not encoded:
        log.warning("Environment variable COOKIES_BASE64 not found. Skipping cookies.txt creation.")
        return
    
    try:
        decoded = base64.b64decode(encoded)
        with open("cookies.txt", "wb") as f:
            f.write(decoded)
        log.info("✅ File cookies.txt successfully created from environment variable.")
    except Exception as e:
        log.error(f"❌ Failed to decode or save cookies: {e}")

mongo_uri = os.getenv("MONGODB_URI")
if not mongo_uri:
    log.critical("Environment variable MONGODB_URI not found. Bot cannot connect to MongoDB.")
    raise ValueError("Environment variable MONGODB_URI not found. Please set it up.")

client = None
db = None
collection = None

try:
    log.info(f"Attempting to connect to MongoDB...")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = client["reSwan"]
    collection = db["Data collection"]
    client.admin.command('ping') 
    log.info("✅ Successfully connected to MongoDB!")
except pymongo_errors.ServerSelectionTimeoutError as err:
    log.critical(f"❌ MongoDB Server Selection Timeout: {err}. Check your network connection and MongoDB Atlas IP whitelist settings.")
    raise Exception("MongoDB connection failed at startup.") from err
except pymongo_errors.ConfigurationError as err:
    log.critical(f"❌ MongoDB Configuration Error: {err}. Check your MONGODB_URI format and credentials carefully.")
    raise Exception("MongoDB configuration failed at startup.") from err
except Exception as e:
    log.critical(f"❌ An unexpected error occurred during MongoDB connection: {e}")
    raise Exception("Unexpected MongoDB connection error at startup.") from e

try:
    from keep_alive import keep_alive
    keep_alive()
    log.info("✅ `keep_alive.py` found and initiated.")
except ImportError:
    log.warning("`keep_alive.py` not found. If you are not using Replit, this is normal.")
except Exception as e:
    log.error(f"❌ Error calling keep_alive: {e}", exc_info=True)

class CogBackupView(ui.View):
    def __init__(self, ctx, files, webhook_url, log_obj):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.files = files
        self.webhook_url = webhook_url
        self.log = log_obj
        self.selected_file = None
        self.message = None
        
        options = [
            discord.SelectOption(label=file, value=file, description=f"Backup file {file}")
            for file in files
        ]
        
        if len(options) > 25:
             options = options[:25]
             self.log.warning("Lebih dari 25 file .py ditemukan, hanya 25 file pertama yang ditampilkan.")

        self.file_select = ui.Select(
            placeholder="Pilih file .py untuk di-backup...",
            options=options,
            min_values=1,
            max_values=1
        )
        self.file_select.callback = self.select_callback
        self.add_item(self.file_select)
        
        self.process_button = ui.Button(
            label="Proses Backup", 
            style=discord.ButtonStyle.green, 
            disabled=True
        )
        self.process_button.callback = self.process_backup_callback
        self.add_item(self.process_button)

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            try:
                await self.message.edit(content="❌ Waktu interaksi habis (3 menit). Backup dibatalkan.", view=self)
            except:
                pass

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ Ini bukan menu untukmu.", ephemeral=True)
            return

        self.selected_file = interaction.data['values'][0]
        
        self.process_button.disabled = False
        self.file_select.placeholder = f"Dipilih: {self.selected_file}"
        
        await interaction.response.edit_message(content=f"Pilih file: **{self.selected_file}**. Klik **Proses Backup** untuk melanjutkan.", view=self)

    async def process_backup_callback(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ Ini bukan tombol untukmu.", ephemeral=True)
            return

        if not self.selected_file:
            await interaction.response.send_message("❌ Harap pilih file terlebih dahulu.", ephemeral=True)
            return
        
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=f"⚙️ Memproses backup file: **{self.selected_file}**...", view=self)
        
        file_path = os.path.join("cogs", self.selected_file)
        
        try:
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            success = await self.send_file_to_webhook(self.selected_file, file_content)
            
            if success:
                await self.message.edit(content=f"✅ Backup file **{self.selected_file}** berhasil dan telah dikirim ke webhook!", view=self)
            else:
                await self.message.edit(content=f"❌ Gagal mengirim backup file **{self.selected_file}** ke webhook. Cek log bot.", view=self)
                
        except FileNotFoundError:
            await self.message.edit(content=f"❌ File **{self.selected_file}** tidak ditemukan di folder `cogs/`.", view=self)
            self.log.error(f"File {file_path} tidak ditemukan saat backup.")
        except Exception as e:
            await self.message.edit(content=f"❌ Terjadi error saat memproses backup: {e}", view=self)
            self.log.error(f"Error saat backup {file_path}: {e}", exc_info=True)
            
        self.stop()

    async def send_file_to_webhook(self, filename, content):
        if not self.webhook_url:
            self.log.warning("Variabel BACKUP_WEBHOOK_URL tidak ditemukan. Backup ke webhook dilewati.")
            return False

        file_obj = discord.File(io.BytesIO(content), filename=filename)
        
        embed = discord.Embed(
            title="💾 Backup File Cog",
            description=f"File **`{filename}`** berhasil di-backup.",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Diinisiasi oleh", value=f"{self.ctx.author.name} (`{self.ctx.author.id}`)", inline=False)
        
        webhook = discord.Webhook.from_url(self.webhook_url, session=self.ctx.bot.session)
        try:
            await webhook.send(
                content="**Backup File Cog (.py)**", 
                file=file_obj, 
                embed=embed,
                username="Cog Backup Notifier"
            )
            self.log.info(f"✅ File backup {filename} berhasil dikirim ke webhook.")
            return True
        except Exception as e:
            self.log.error(f"❌ Gagal mengirim file backup ke webhook: {e}", exc_info=True)
            return False

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=("!", "?", "m!"), intents=intents, help_command=None)

# --- EVENT ON_MESSAGE BARU UNTUK MENCEGAH DUPLIKASI COMMAND ---
@bot.event
async def on_message(message):
    # Abaikan pesan dari bot itu sendiri
    if message.author.bot:
        return

    # Pastikan command hanya diproses di sini
    await bot.process_commands(message)
# -------------------------------------------------------------

@bot.event
async def on_ready():
    log.info(f"😎 Bot {bot.user} is now online and ready!")
    log.info(f"Total server: {len(bot.guilds)}")

@bot.event
async def on_guild_join(guild):
    JOIN_WEBHOOK_URL = os.getenv("JOIN_WEBHOOK_URL")
    if not JOIN_WEBHOOK_URL:
        log.warning(f"Bot joined '{guild.name}' but JOIN_WEBHOOK_URL is not set. Skipping notification.")
        return

    invite_link = "Tidak dapat membuat invite (kurang izin)."
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).create_instant_invite:
            try:
                invite = await channel.create_invite(max_age=0, max_uses=0, reason="Notifikasi Bot Join")
                invite_link = invite.url
                break
            except Exception as e:
                log.error(f"Gagal membuat invite untuk server {guild.name}: {e}")
                break

    embed = discord.Embed(
        title="🎉 Bot Bergabung ke Server Baru!",
        description=f"Bot telah ditambahkan ke server **{guild.name}**.",
        color=0x00FF00,
        timestamp=datetime.now(timezone.utc)
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="👑 Pemilik Server", value=f"{guild.owner.mention} (`{guild.owner.id}`)", inline=False)
    embed.add_field(name="👥 Jumlah Anggota", value=str(guild.member_count), inline=True)
    embed.add_field(name="🆔 ID Server", value=f"`{guild.id}`", inline=True)
    embed.add_field(name="🔗 Link Invite", value=invite_link, inline=False)
    embed.set_footer(text=f"Total server saat ini: {len(bot.guilds)}")

    payload = {"embeds": [embed.to_dict()], "username": "Notifikasi Server"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(JOIN_WEBHOOK_URL, json=payload) as response:
                if not response.ok:
                    log.error(f"Gagal mengirim notifikasi join server ke webhook: Status {response.status}")
                else:
                    log.info(f"Notifikasi join server '{guild.name}' berhasil dikirim.")
        except Exception as e:
            log.error(f"Terjadi error saat mengirim notifikasi join server: {e}")

@bot.event
async def on_guild_remove(guild):
    JOIN_WEBHOOK_URL = os.getenv("JOIN_WEBHOOK_URL")
    if not JOIN_WEBHOOK_URL:
        log.warning(f"Bot was removed from '{guild.name}' but JOIN_WEBHOOK_URL is not set. Skipping notification.")
        return

    embed = discord.Embed(
        title="💔 Bot Dikeluarkan dari Server",
        description=f"Bot telah dikeluarkan dari server **{guild.name}**.",
        color=0xFF0000, 
        timestamp=datetime.now(timezone.utc)
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    owner_info = f"{guild.owner.mention} (`{guild.owner.id}`)" if guild.owner else "Tidak diketahui"
    embed.add_field(name="👑 Pemilik Server", value=owner_info, inline=False)
    embed.add_field(name="👥 Jumlah Anggota", value=str(guild.member_count), inline=True)
    embed.add_field(name="🆔 ID Server", value=f"`{guild.id}`", inline=True)
    embed.set_footer(text=f"Total server saat ini: {len(bot.guilds)}")

    payload = {"embeds": [embed.to_dict()], "username": "Notifikasi Server"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(JOIN_WEBHOOK_URL, json=payload) as response:
                if not response.ok:
                    log.error(f"Gagal mengirim notifikasi keluar server ke webhook: Status {response.status}")
                else:
                    log.info(f"Notifikasi keluar server '{guild.name}' berhasil dikirim.")
        except Exception as e:
            log.error(f"Terjadi error saat mengirim notifikasi keluar server: {e}")


@bot.command(name="help", aliases=["h"])
async def custom_help(ctx, *, command_name: str = None):
    prefix = ctx.prefix

    if not command_name:
        embed = discord.Embed(
            title="👋 Bantuan Perintah Bot",
            description=f"Cek website untuk detail cara penggunaan nya",
            color=0x3498db
        )
        if bot.user.avatar:
            embed.set_thumbnail(url=bot.user.avatar.url)

        for cog_name, cog in bot.cogs.items():
            if cog_name in ["Jishaku"]:
                continue
            
            commands_list = [f"`{c.name}`" for c in cog.get_commands() if not c.hidden]
            if commands_list:
                embed.add_field(
                    name=f"**Kategori: {cog_name}**",
                    value=" ".join(commands_list),
                    inline=False
                )
        
        embed.add_field(
            name="Panduan Lengkap",
            value='Untuk cara pakai yang lebih detail, kunjungi website kami di:\n**🔗 [Klik di sini untuk melihat cara pakai]( https://kawansejalanproduction2019.github.io/html/ )**',
            inline=False
        )
        
        embed.set_footer(text=f"Diminta oleh: {ctx.author.display_name}")
        await ctx.send(embed=embed)
        return

    cmd = bot.get_command(command_name.lower())
    if not cmd or cmd.hidden:
        await ctx.send(f"❌ Command `{command_name}` tidak ditemukan.", delete_after=10)
        return

    embed = discord.Embed(
        title=f"🔎 Detail Command: `{cmd.name}`",
        description=cmd.help or "Tidak ada deskripsi untuk command ini.",
        color=0x2ecc71
    )
    
    aliases = ", ".join([f"`{a}`" for a in cmd.aliases]) if cmd.aliases else "Tidak ada"
    embed.add_field(name="Alias", value=aliases, inline=True)
    
    usage = f"`{prefix}{cmd.name} {cmd.signature}`"
    embed.add_field(name="Cara Penggunaan", value=usage, inline=True)
    
    embed.set_footer(text="Tanda < > berarti wajib, [ ] berarti opsional.")
    await ctx.send(embed=embed)

async def send_backup_to_webhook(backup_data):
    BACKUP_WEBHOOK_URL = os.getenv("BACKUP_WEBHOOK_URL")
    if not BACKUP_WEBHOOK_URL:
        log.warning("Variabel BACKUP_WEBHOOK_URL tidak ditemukan. Backup ke webhook dilewati.")
        return False

    try:
        payload = {
            "content": f"✅ Backup database berhasil dikirim pada <t:{int(datetime.now(timezone.utc).timestamp())}:F>."
        }
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_path, content in backup_data.items():
                filename = os.path.basename(file_path)
                string_content = json.dumps(content, indent=4, ensure_ascii=False)
                zip_file.writestr(filename, string_content)
        
        zip_buffer.seek(0)
        
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field(
                'file',
                zip_buffer,
                filename='backup.zip',
                content_type='application/zip'
            )
            
            form.add_field('payload_json', json.dumps(payload), content_type='application/json')
            
            async with session.post(BACKUP_WEBHOOK_URL, data=form) as response:
                if not response.ok:
                    log.error(f"Gagal mengirim backup ke webhook: Status {response.status}, Respon: {await response.text()}")
                    return False
                log.info("✅ Backup berhasil dikirim ke webhook.")
                return True
    except Exception as e:
        log.error(f"❌ Terjadi error saat mengirim backup ke webhook: {e}", exc_info=True)
        return False

@bot.command()
@commands.is_owner()
async def backup(ctx):
    await ctx.send("Memulai proses backup...")
    backup_data = {}

    if not client:
        await ctx.send("❌ MongoDB client tidak aktif. Backup dibatalkan.", ephemeral=True)
        log.error("MongoDB client is None, cannot perform backupnow.")
        return

    try:
        client.admin.command('ping')
    except Exception as e:
        await ctx.send(f"❌ Gagal terhubung ke MongoDB untuk backup: {e}", ephemeral=True)
        log.error(f"MongoDB ping failed for backupnow command: {e}", exc_info=True)
        return

    directories_to_scan = ['.', 'data/', 'config/']

    for directory in directories_to_scan:
        if not os.path.isdir(directory):
            log.warning(f"Direktori '{directory}' tidak ditemukan, dilewati.")
            continue
        
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if filename.endswith('.json') and os.path.isfile(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                        backup_data[file_path] = json_data
                        log.info(f"✅ File '{file_path}' berhasil dibaca untuk backup.")
                except Exception as e:
                    await ctx.send(f"❌ Gagal membaca file `{file_path}`: {e}")
                    log.error(f"❌ Gagal membaca file `{file_path}`: {e}", exc_info=True)

    if backup_data:
        try:
            collection.update_one(
                {"_id": "latest_backup"},
                {"$set": {
                    "backup": backup_data,
                    "timestamp": datetime.now(timezone.utc)
                }},
                upsert=True
            )
            log.info("✅ Data backup berhasil disimpan ke MongoDB.")
            await ctx.send("✅ Data backup berhasil disimpan ke MongoDB!")
        except Exception as e:
            await ctx.send(f"❌ Gagal menyimpan data ke MongoDB: {e}")
            log.error(f"❌ Gagal menyimpan data ke MongoDB: {e}", exc_info=True)
    else:
        await ctx.send("🤷 Tidak ada file .json yang ditemukan untuk di-backup.")
        log.warning("Tidak ada file .json ditemukan untuk di-backup.")

@bot.command()
@commands.is_owner()
async def send(ctx):
    if not client:
        await ctx.send("❌ MongoDB client tidak aktif.", ephemeral=True)
        log.error("MongoDB client is None, cannot perform sendbackup.")
        return

    try:
        client.admin.command('ping')
    except Exception as e:
        await ctx.send(f"❌ Gagal terhubung ke MongoDB: {e}", ephemeral=True)
        log.error(f"MongoDB ping failed for sendbackup command: {e}", exc_info=True)
        return

    try:
        stored_data = collection.find_one({"_id": "latest_backup"})
        if not stored_data or 'backup' not in stored_data:
            await ctx.send("❌ Tidak ada data backup yang tersedia.")
            log.warning("Tidak ada data backup di MongoDB.")
            return

        backup_data = stored_data["backup"]
        
        await ctx.send("🌐 Mengirim file backup ke webhook...")
        webhook_sent = await send_backup_to_webhook(backup_data)
        
        if webhook_sent:
            await ctx.send("✅ File backup berhasil dikirim ke webhook!")
            log.info("File backup berhasil dikirim ke webhook.")
        else:
            await ctx.send("❌ Gagal mengirim file backup ke webhook.")

    except Exception as e:
        await ctx.send(f"❌ Terjadi error saat mengambil data backup: {e}")
        log.error(f"❌ Terjadi error saat mengambil data backup: {e}", exc_info=True)

@bot.command(name="cogbackup")
@commands.is_owner()
async def cog_backup(ctx):
    """
    Mem-backup file .py dari folder cogs dan mengirimkannya ke webhook dengan UI pilih.
    """
    BACKUP_WEBHOOK_URL = os.getenv("BACKUP_WEBHOOK_URL")
    if not BACKUP_WEBHOOK_URL:
        await ctx.send("❌ Variabel **BACKUP_WEBHOOK_URL** belum diatur. Backup dibatalkan.", ephemeral=True)
        log.error("BACKUP_WEBHOOK_URL tidak ditemukan untuk cog backup.")
        return
        
    cogs_dir = "cogs"
    if not os.path.isdir(cogs_dir):
        await ctx.send(f"❌ Direktori `{cogs_dir}` tidak ditemukan. Pastikan folder 'cogs' ada di direktori kerja bot.", ephemeral=True)
        log.error(f"Direktori {cogs_dir} tidak ditemukan.")
        return

    all_files = os.listdir(cogs_dir)
    py_files = sorted([f for f in all_files if f.endswith(".py") and os.path.isfile(os.path.join(cogs_dir, f))])

    if not py_files:
        await ctx.send(f"🤷 Tidak ada file **.py** yang ditemukan di folder `{cogs_dir}`.")
        return
    
    view = CogBackupView(ctx, py_files, BACKUP_WEBHOOK_URL, log)
    
    embed = discord.Embed(
        title="📂 Backup File Cogs",
        description=f"Ditemukan **{len(py_files)}** file `.py` di folder `cogs/`. Silakan pilih file yang ingin Anda backup menggunakan menu di bawah ini. Waktu interaksi 3 menit.",
        color=discord.Color.orange()
    )
    
    message = await ctx.send(embed=embed, view=view)
    view.message = message

@cog_backup.error
async def cog_backup_error(ctx, error):
    if isinstance(error, commands.NotOwner):
        await ctx.send("❌ Command ini hanya bisa digunakan oleh Owner Bot.", ephemeral=True)
    elif isinstance(error, commands.CommandInvokeError):
        await ctx.send(f"❌ Terjadi error saat menjalankan backup: {error.original}", ephemeral=True)
        log.error(f"Error pada !cogbackup: {error.original}", exc_info=True)
    else:
        await ctx.send(f"❌ Error yang tidak terduga terjadi: {error}", ephemeral=True)
        log.error(f"Error tak terduga pada !cogbackup: {error}", exc_info=True)

async def load_cogs():
    initial_extensions = [
        "cogs.leveling", "cogs.moderation", "cogs.quotes", "cogs.endgame",
        "cogs.webhook", "cogs.notif", "cogs.multi", "cogs.info", "cogs.gemini", "cogs.game", "cogs.youtube"
    ]
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            log.info(f"✅ Cog berhasil dimuat: {extension}")
        except Exception as e:
            log.error(f"❌ Cog gagal dimuat: {extension}: {e}", exc_info=True)

@bot.event
async def setup_hook():
    log.info("🚀 Memulai setup_hook dan memuat cogs...")
    bot.session = aiohttp.ClientSession()
    await load_cogs()
    log.info("✅ setup_hook selesai.")

save_cookies_from_env()
bot.run(os.getenv("DISCORD_TOKEN"))
