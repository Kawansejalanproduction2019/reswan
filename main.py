import discord
from discord.ext import commands
import aiohttp
import base64
import logging
import os
import io
import asyncio
import json
from io import BytesIO
from pymongo import MongoClient, errors as pymongo_errors
from dotenv import load_dotenv
from datetime import datetime

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
            # Handle logs before the event loop starts
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
                "timestamp": datetime.utcnow().isoformat()
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

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

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
        timestamp=datetime.utcnow()
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
        timestamp=datetime.utcnow()
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

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)

@bot.command(name="help", aliases=["h"])
async def custom_help(ctx, *, command_name: str = None):
    prefix = ctx.prefix

    if not command_name:
        embed = discord.Embed(
            title="👋 Bantuan Perintah Bot",
            description=f"Gunakan `{prefix}help [nama_command]` untuk melihat info detail dari sebuah command.",
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
            name="🔗 Panduan Lengkap",
            value='Untuk cara pakai yang lebih detail, kunjungi website kami di:\n**🔗 [Klik di sini untuk melihat cara pakai]( http://3.27.18.147/ )**',
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


async def load_cogs():
    initial_extensions = [
        "cogs.music"
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
    await load_cogs()
    log.info("✅ setup_hook selesai.")

save_cookies_from_env()
bot.run(os.getenv("DISCORD_TOKEN"))
