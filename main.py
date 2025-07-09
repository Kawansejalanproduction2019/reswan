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
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

logging.basicConfig(level=logging.INFO)

def save_cookies_from_env():
    """Membaca cookies dari environment variable dan menyimpannya ke file."""
    encoded = os.getenv("COOKIES_BASE64")
    if not encoded:
        # Lebih baik raise error langsung jika ini adalah konfigurasi penting
        raise ValueError("Environment variable COOKIES_BASE64 not found. Please set it up.")
    
    try:
        decoded = base64.b64decode(encoded)
        with open("cookies.txt", "wb") as f:
            f.write(decoded)
        print("✅ File cookies.txt successfully created from environment variable.")
    except Exception as e:
        print(f"❌ Failed to decode cookies: {e}")

# Koneksi ke MongoDB
mongo_uri = os.getenv("MONGODB_URI")
if not mongo_uri:
    raise ValueError("Environment variable MONGODB_URI not found. Please set it up.")
client = MongoClient(mongo_uri)
db = client["reSwan"]  # Nama database Anda
collection = db["Data collection"]  # Nama koleksi Anda

# Import fungsi keep_alive jika Anda menggunakan Replit
# Pastikan file keep_alive.py ada di root folder Anda
try:
    from keep_alive import keep_alive
except ImportError:
    print("Peringatan: `keep_alive.py` tidak ditemukan. Jika Anda tidak menggunakan Replit, ini normal.")
    def keep_alive():
        pass # Fungsi dummy jika tidak ditemukan

# Konfigurasi Intents Discord
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True # Diperlukan untuk membaca konten pesan
intents.guilds = True
intents.members = True
intents.voice_states = True # Diperlukan untuk fitur voice channel di cog leveling

# Inisialisasi Bot
bot = commands.Bot(command_prefix="!", intents=intents)

# Event saat bot siap
@bot.event
async def on_ready():
    """Dipanggil ketika bot berhasil terhubung ke Discord."""
    print(f"ðŸ¤– Bot {bot.user} is now online!")
    print(f"Registered commands: {[command.name for command in bot.commands]}")

# --- Perbaikan Utama: Event on_message Global ---
@bot.event
async def on_message(message):
    """
    Menangani semua pesan yang diterima oleh bot.
    Ini adalah satu-satunya tempat di mana bot.process_commands(message)
    seharusnya dipanggil untuk memastikan perintah diproses sekali saja.
    """
    # Abaikan pesan dari bot itu sendiri agar tidak masuk ke loop tak terbatas
    if message.author.bot:
        return

    # Meneruskan pesan ke pemroses perintah Discord.py.
    # Semua `commands.Cog.listener()` `on_message` akan dipanggil terlebih dahulu.
    await bot.process_commands(message)

# Command untuk backup data dari folder root, data/, dan config/
@bot.command()
@commands.is_owner() # Hanya pemilik bot yang bisa menjalankan perintah ini
async def backupnow(ctx):
    """Membuat backup semua file .json di folder tertentu ke MongoDB."""
    await ctx.send("Starting backup process...")
    backup_data = {}

    # Direktori yang akan di-backup
    directories_to_scan = ['.', 'data/', 'config/']

    for directory in directories_to_scan:
        if not os.path.isdir(directory):
            print(f"Warning: Directory '{directory}' not found, skipping.")
            continue
        
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if filename.endswith('.json') and os.path.isfile(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                        backup_data[file_path] = json_data 
                        print(f"✅ File '{file_path}' successfully read.")
                except json.JSONDecodeError:
                    await ctx.send(f"❌ Failed to read JSON file: `{file_path}`")
                    print(f"❌ Failed to read JSON file: {file_path}")
                except Exception as e:
                    await ctx.send(f"❌ An error occurred while reading `{file_path}`: {e}")

    # Simpan data backup ke MongoDB
    if backup_data:
        try:
            collection.update_one(
                {"_id": "latest_backup"},  # Menggunakan ID tetap untuk menimpa backup terbaru
                {"$set": {
                    "backup": backup_data,
                    "timestamp": datetime.utcnow() # Menambahkan timestamp backup
                }},
                upsert=True  # Membuat dokumen jika belum ada
            )
            
            print("✅ Backup data successfully saved to MongoDB.")
            await ctx.send("✅ Backup data successfully saved to MongoDB!")

        except Exception as e:
            await ctx.send(f"❌ Failed to save data to MongoDB: {e}")
            print(f"❌ Failed to save data to MongoDB: {e}")
    else:
        await ctx.send("🤷 No .json files found to backup.")

# Command untuk mengirim data backup ke DM
@bot.command()
@commands.is_owner() # Hanya pemilik bot yang bisa menjalankan perintah ini
async def sendbackup(ctx):
    """Mengirim file backup dari MongoDB ke DM pemilik bot."""
    user_id = 1000737066822410311  # Ganti dengan ID Discord Anda
    user = await bot.fetch_user(user_id)

    try:
        stored_data = collection.find_one({"_id": "latest_backup"})
        if not stored_data or 'backup' not in stored_data:
            await ctx.send("❌ No backup data available.")
            return

        backup_data = stored_data["backup"]
        await ctx.send("📬 Sending backup files one by one to DM...")

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
            except discord.HTTPException as e:
                await ctx.send(f"❌ Failed to send file `{filename}`: {e}")

        await ctx.send("✅ All backup files successfully sent to DM!")

    except discord.Forbidden:
        await ctx.send("❌ Failed to send DM. Make sure I can send DMs to this user.")
    except Exception as e:
        await ctx.send(f"❌ An error occurred while retrieving backup data: {e}")
        print(f"❌ Error during sendbackup: {e}")

# Fungsi untuk memuat semua cog
async def load_cogs():
    """Memuat semua cogs dari folder 'cogs'."""
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
        "cogs.dunia", 
        "cogs.endgame",
        "cogs.personality",
        "cogs.psikotes"
    ]
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            print(f"✅ Loaded {extension}")
        except Exception as e:
            print(f"❌ Failed to load {extension}: {e}")

# setup_hook dipanggil setelah bot.run() tetapi sebelum bot.on_ready()
@bot.event
async def setup_hook():
    """Dipanggil sekali saat bot pertama kali startup."""
    print("ðŸ” Starting setup_hook and loading cogs...")
    await load_cogs()
    await load_extension()
    print(f"✅ Finished setup_hook and all cogs attempted to load.")
    # Ini akan dicetak setelah semua cog dimuat, tetapi sebelum on_ready sepenuhnya selesai
    print(f"All commands registered: {[command.name for command in bot.commands]}")


# Menjalankan fungsi untuk menyimpan cookies dari env variable
save_cookies_from_env()

# Menjalankan server web keep_alive jika ada
keep_alive()

# Menjalankan bot dengan token dari environment variable
bot.run(os.getenv("DISCORD_TOKEN"))
