import discord
from discord.ext import commands
import os
import json
import base64
import logging
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

# Muat variabel lingkungan dari file .env
load_dotenv()

# --- KONFIGURASI LOGGING ---
# Pastikan logging dikonfigurasi di awal agar semua log tercatat
# Level INFO akan menampilkan pesan INFO, WARNING, ERROR, CRITICAL.
# Untuk melihat lebih detail (termasuk DEBUG), ganti level=logging.DEBUG
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__) # Logger untuk main.py

# --- FUNGSI UTILITY GLOBAL ---
def save_cookies_from_env():
    """Membaca cookies dari environment variable dan menyimpannya ke file cookies.txt."""
    encoded = os.getenv("COOKIES_BASE64")
    if not encoded:
        log.error("Environment variable COOKIES_BASE64 not found. Cookies.txt will not be created.")
        return # Jangan raise error fatal jika ini opsional

    try:
        decoded = base64.b64decode(encoded)
        with open("cookies.txt", "wb") as f:
            f.write(decoded)
        log.info("✅ File cookies.txt successfully created from environment variable.")
    except Exception as e:
        log.error(f"❌ Failed to decode or write cookies.txt: {e}")

# Koneksi ke MongoDB
mongo_uri = os.getenv("MONGODB_URI")
if not mongo_uri:
    log.warning("Environment variable MONGODB_URI not found. MongoDB features will be unavailable.")
    client = None # Set client ke None jika URI tidak ada
    db = None
    collection = None
else:
    try:
        client = MongoClient(mongo_uri)
        db = client["reSwan"]  # Nama database Anda
        collection = db["Data collection"]  # Nama koleksi Anda
        log.info("✅ Connected to MongoDB.")
    except Exception as e:
        log.error(f"❌ Failed to connect to MongoDB: {e}")
        client = None
        db = None
        collection = None

# Fungsi keep_alive jika menggunakan Replit
try:
    from keep_alive import keep_alive
    log.info("`keep_alive.py` found and imported.")
except ImportError:
    log.info("`keep_alive.py` not found. Assuming not running on Replit or similar environment.")
    def keep_alive():
        pass # Fungsi dummy jika tidak ditemukan


# --- INISIALISASI BOT ---
intents = discord.Intents.default()
intents.message_content = True # Diperlukan untuk membaca konten pesan
intents.guilds = True
intents.members = True # Diperlukan untuk member list di giveallmoney/xpall, dan untuk cek role
intents.voice_states = True # Diperlukan untuk fitur voice channel di cog leveling

# Inisialisasi Bot tanpa help_command bawaan
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# --- EVENT BOT ---
@bot.event
async def on_ready():
    """Dipanggil ketika bot berhasil terhubung ke Discord."""
    log.info(f"😎 Bot {bot.user} is now online!")
    log.info(f"Registered commands: {[command.name for command in bot.commands]}")
    print(f"😎 Bot {bot.user} is now online!") # Cetak juga ke konsol agar terlihat jelas

@bot.event
async def on_message(message):
    """
    Menangani semua pesan yang diterima oleh bot.
    Ini adalah satu-satunya tempat di mana bot.process_commands(message)
    seharusnya dipanggil untuk memastikan perintah diproses sekali saja.
    """
    if message.author.bot:
        return

    # Log pesan masuk (opsional, bisa diubah ke DEBUG jika terlalu banyak)
    log.debug(f"Pesan dari {message.author}: {message.content} di #{message.channel.name} ({message.guild.name})")

    # Pastikan untuk memproses command setelah listener on_message di cogs selesai.
    # Namun, karena ini adalah on_message global, ia akan dipanggil setelah listener cogs.
    # Jika ada listener on_message di cogs (seperti di Leveling.py atau EconomyEvents.py
    # untuk memantau pesan penjara atau EXP), mereka akan dipanggil dulu.
    await bot.process_commands(message)


# --- COMMAND UTAMA BOT (Dapat ditambahkan sesuai kebutuhan, contoh: untuk owner/debugging) ---
@bot.command()
@commands.is_owner() # Hanya pemilik bot yang bisa menjalankan perintah ini
async def load(ctx, extension):
    """[OWNER] Memuat (load) cog baru."""
    try:
        await bot.load_extension(f'cogs.{extension}')
        await ctx.send(f'✅ Cog {extension} berhasil dimuat!')
        log.info(f"Cog {extension} loaded by {ctx.author}.")
    except commands.ExtensionAlreadyLoaded:
        await ctx.send(f'❌ Cog {extension} sudah dimuat.', ephemeral=True)
        log.warning(f"Attempted to load already loaded cog {extension} by {ctx.author}.")
    except commands.ExtensionNotFound:
        await ctx.send(f'❌ Cog {extension} tidak ditemukan.', ephemeral=True)
        log.warning(f"Cog {extension} not found when attempted to load by {ctx.author}.")
    except Exception as e:
        await ctx.send(f'❌ Gagal memuat cog {extension}: {e}', ephemeral=True)
        log.error(f"Failed to load cog {extension} by {ctx.author}: {e}")

@bot.command()
@commands.is_owner()
async def unload(ctx, extension):
    """[OWNER] Mengeluarkan (unload) cog."""
    try:
        await bot.unload_extension(f'cogs.{extension}')
        await ctx.send(f'✅ Cog {extension} berhasil dikeluarkan!')
        log.info(f"Cog {extension} unloaded by {ctx.author}.")
    except commands.ExtensionNotLoaded:
        await ctx.send(f'❌ Cog {extension} tidak dimuat.', ephemeral=True)
        log.warning(f"Attempted to unload not loaded cog {extension} by {ctx.author}.")
    except Exception as e:
        await ctx.send(f'❌ Gagal mengeluarkan cog {extension}: {e}', ephemeral=True)
        log.error(f"Failed to unload cog {extension} by {ctx.author}: {e}")

@bot.command()
@commands.is_owner()
async def reload(ctx, extension):
    """[OWNER] Memuat ulang (reload) cog."""
    try:
        await bot.reload_extension(f'cogs.{extension}')
        await ctx.send(f'✅ Cog {extension} berhasil dimuat ulang!')
        log.info(f"Cog {extension} reloaded by {ctx.author}.")
    except commands.ExtensionNotLoaded:
        await ctx.send(f'❌ Cog {extension} tidak dimuat, mencoba memuatnya...', ephemeral=True)
        log.warning(f"Attempted to reload not loaded cog {extension}. Trying to load.")
        await ctx.invoke(bot.get_command('load'), extension=extension) # Coba load jika belum dimuat
    except Exception as e:
        await ctx.send(f'❌ Gagal memuat ulang cog {extension}: {e}', ephemeral=True)
        log.error(f"Failed to reload cog {extension} by {ctx.author}: {e}")

# Command untuk backup data ke MongoDB (memastikan MongoDB terhubung)
@bot.command()
@commands.is_owner()
async def backupnow(ctx):
    """Membuat backup semua file .json di folder tertentu ke MongoDB."""
    if collection is None:
        return await ctx.send("❌ Koneksi MongoDB tidak aktif. Fitur backup tidak tersedia.")
    
    await ctx.send("Starting backup process...")
    backup_data = {}

    directories_to_scan = ['./data', './config'] # Scan folder data dan config

    for directory in directories_to_scan:
        if not os.path.isdir(directory):
            log.warning(f"Directory '{directory}' not found, skipping backup.")
            continue
        
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if filename.endswith('.json') and os.path.isfile(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                        backup_data[file_path] = json_data 
                        log.info(f"✅ File '{file_path}' successfully read for backup.")
                except json.JSONDecodeError as e:
                    await ctx.send(f"❌ Failed to read JSON file: `{file_path}` (Corrupted).")
                    log.error(f"❌ Failed to read JSON file: {file_path} - {e}")
                except Exception as e:
                    await ctx.send(f"❌ An error occurred while reading `{file_path}`: {e}")
                    log.error(f"Error reading file {file_path} for backup: {e}")

    if backup_data:
        try:
            collection.update_one(
                {"_id": "latest_backup"},
                {"$set": {
                    "backup": backup_data,
                    "timestamp": datetime.utcnow()
                }},
                upsert=True
            )
            
            log.info("✅ Backup data successfully saved to MongoDB.")
            await ctx.send("✅ Backup data successfully saved to MongoDB!")

        except Exception as e:
            await ctx.send(f"❌ Failed to save data to MongoDB: {e}")
            log.error(f"❌ Failed to save data to MongoDB: {e}")
    else:
        await ctx.send("🤷 No .json files found to backup.")
        log.info("No JSON files found in specified directories for backup.")

# Command untuk mengirim data backup ke DM (memastikan MongoDB terhubung)
@bot.command()
@commands.is_owner()
async def sendbackup(ctx):
    """Mengirim file backup dari MongoDB ke DM pemilik bot."""
    if collection is None:
        return await ctx.send("❌ Koneksi MongoDB tidak aktif. Fitur backup tidak tersedia.")

    user_id = ctx.author.id # Mengirim ke owner yang menjalankan command
    user = await bot.fetch_user(user_id)

    try:
        stored_data = collection.find_one({"_id": "latest_backup"})
        if not stored_data or 'backup' not in stored_data:
            await ctx.send("❌ No backup data available.")
            log.info("No backup data found in MongoDB to send.")
            return

        backup_data = stored_data["backup"]
        await ctx.send("📬 Sending backup files one by one to DM...")
        log.info(f"Sending backup files to owner {user.display_name} via DM.")

        for file_path, content in backup_data.items():
            filename = os.path.basename(file_path)
            
            string_buffer = io.StringIO()
            json.dump(content, string_buffer, indent=4, ensure_ascii=False)
            string_buffer.seek(0)

            byte_buffer = io.BytesIO(string_buffer.read().encode('utf-8'))
            byte_buffer.seek(0)

            file = discord.File(fp=byte_buffer, filename=filename)

            try:
                await user.send(content=f"📄 Here's a backup file from `/{file_path}`:", file=file)
                log.debug(f"Sent backup file {filename} to DM.")
            except discord.HTTPException as e:
                await ctx.send(f"❌ Failed to send file `{filename}` to DM: {e}")
                log.error(f"Failed to send backup file {filename} to owner DM: {e}")

        await ctx.send("✅ All backup files successfully sent to DM!")
        log.info("All backup files sent to owner DM.")

    except discord.Forbidden:
        await ctx.send("❌ Failed to send DM. Make sure I can send DMs to this user.")
        log.error(f"Bot forbidden from sending DM to owner {user.display_name}.")
    except Exception as e:
        await ctx.send(f"❌ An error occurred while retrieving backup data: {e}")
        log.error(f"Error during sendbackup: {e}")


# --- SETUP COGS ---
async def load_cogs():
    """Memuat semua cogs dari folder 'cogs'."""
    # Pastikan urutan loading jika ada ketergantungan antar cogs
    # Misalnya, Leveling.py mungkin perlu dimuat sebelum EconomyEvents.py
    # karena EconomyEvents.py memanggil fungsi dari Leveling.py.
    initial_extensions = [
        "cogs.leveling",
        "cogs.shop",
        "cogs.quizz",
        "cogs.music",
        "cogs.itemmanage",
        "cogs.moderation",
        "cogs.emojiquiz",
        "cogs.hangman", 
        "cogs.quotes",
        "cogs.newgame",
        "cogs.multigame",
        "cogs.dunia", # Jika Anda punya cog ini dan Leveling.py bergantung padanya
        "cogs.endgame",
        "cogs.personality",
        "cogs.psikotes",
        "cogs.koruptor"
    ]
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            log.info(f"✅ Loaded {extension}")
        except Exception as e:
            log.error(f"❌ Failed to load {extension}: {e}")

# setup_hook dipanggil setelah bot.run() tetapi sebelum bot.on_ready()
@bot.event
async def setup_hook():
    """Dipanggil sekali saat bot pertama kali startup."""
    log.info("🚀 Starting setup_hook and loading cogs...")
    await load_cogs()
    log.info(f"✅ Finished setup_hook and all cogs attempted to load.")
    log.info(f"All commands registered: {[command.name for command in bot.commands]}")


# --- MENJALANKAN BOT ---
if __name__ == "__main__":
    # Menjalankan fungsi untuk menyimpan cookies dari env variable
    save_cookies_from_env()

    # Menjalankan server web keep_alive jika ada
    keep_alive()

    # Menjalankan bot dengan token dari environment variable
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    if not DISCORD_TOKEN:
        log.critical("DISCORD_TOKEN not found in environment variables. Bot cannot start.")
        raise ValueError("DISCORD_TOKEN not found in environment variables.")
        
    bot.run(DISCORD_TOKEN)
