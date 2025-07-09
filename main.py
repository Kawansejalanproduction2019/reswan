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

logging.basicConfig(level=logging.INFO)!

def save_cookies_from_env():
    """Membaca cookies dari environment variable dan menyimpannya ke file."""
    encoded = os.getenv("COOKIES_BASE64")
    if not encoded:
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

try:
    from keep_alive import keep_alive
except ImportError:
    print("Peringatan: `keep_alive.py` tidak ditemukan. Jika Anda tidak menggunakan Replit, ini normal.")
    def keep_alive():
        pass

# Konfigurasi Intents Discord
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

# Inisialisasi Bot
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Event saat bot siap
@bot.event
async def on_ready():
    """Dipanggil ketika bot berhasil terhubung ke Discord."""
    print(f"😎 Bot {bot.user} is now online!")
    print(f"Registered commands: {[command.name for command in bot.commands]}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)

# --- COMMAND HELP KUSTOM KHUSUS ADMIN ---
@bot.command(name="help", aliases=["halp", "h"])
@commands.has_permissions(administrator=True) # Hanya pengguna dengan izin Administrator
async def custom_help(ctx, *, command_name: str = None):
    """
    Menampilkan informasi bantuan untuk admin.
    Jika ada command_name, akan menampilkan bantuan untuk command tersebut.
    Jika tidak, akan menampilkan daftar semua command yang tersedia.
    """
    if command_name:
        cmd = bot.get_command(command_name) or bot.get_cog(command_name.capitalize())

        if cmd:
            embed = discord.Embed(
                title=f"Bantuan untuk `{command_name}`",
                color=discord.Color.blue()
            )
            if isinstance(cmd, commands.Command):
                embed.add_field(name="Command", value=f"`{ctx.prefix}{cmd.name} {cmd.signature}`", inline=False)
                if cmd.aliases:
                    embed.add_field(name="Aliases", value=", ".join([f"`{alias}`" for alias in cmd.aliases]), inline=False)
                if cmd.help:
                    embed.description = cmd.help
                else:
                    embed.description = "Tidak ada deskripsi untuk command ini."
            elif isinstance(cmd, commands.Cog):
                embed.add_field(name="Cog", value=cmd.qualified_name, inline=False)
                embed.description = f"Command-command di bawah cog `{cmd.qualified_name}`:\n"
                cog_commands = [f"`{ctx.prefix}{c.name}`" for c in cmd.get_commands()]
                if cog_commands:
                    embed.description += ", ".join(cog_commands)
                else:
                    embed.description += "Tidak ada command di cog ini."
            
            message_sent = await ctx.send(embed=embed)
            # Hapus pesan setelah 1 menit (60 detik)
            await message_sent.delete(delay=60) 
        else:
            message_sent = await ctx.send(f"Command atau Cog `{command_name}` tidak ditemukan.")
            await message_sent.delete(delay=60)
    else:
        # Tampilkan daftar semua command dan cog
        embed = discord.Embed(
            title="Daftar Command Bot (Admin Only)",
            description="Berikut adalah semua command yang bisa kamu gunakan:",
            color=discord.Color.green()
        )

        for cog_name, cog in bot.cogs.items():
            if cog_name in ["Jishaku"] :
                continue
            
            commands_in_cog = [f"`{ctx.prefix}{command.name}`" for command in cog.get_commands()]
            if commands_in_cog:
                embed.add_field(name=f"__**{cog_name}**__", value=" ".join(commands_in_cog), inline=False)
            
        no_cog_commands = [f"`{ctx.prefix}{command.name}`" for command in bot.commands if command.cog is None and not command.hidden]
        if no_cog_commands:
            embed.add_field(name="__**Lain-lain**__", value=" ".join(no_cog_commands), inline=False)

        embed.set_footer(text=f"Gunakan {ctx.prefix}help <command> untuk detail. Pesan ini akan hilang dalam 1 menit.")
        message_sent = await ctx.send(embed=embed)
        # Hapus pesan setelah 1 menit (60 detik)
        await message_sent.delete(delay=60) 

@custom_help.error
async def custom_help_error(ctx, error):
    """Handler error untuk command help kustom."""
    if isinstance(error, commands.MissingPermissions):
        # Pesan menarik untuk non-admin
        embed = discord.Embed(
            title="Akses Ditolak! 🚫",
            description=(
                "Oops! Sepertinya kamu mencoba mengakses area terlarang.\n"
                "Command ini hanya untuk mata-mata terpilih yang memiliki izin khusus.\n\n"
                "Jika kamu merasa ini adalah kesalahan, hubungi petinggi server ya! 😉"
            ),
            color=discord.Color.red()
        )
        embed.set_thumbnail(url="https://i.imgur.com/example_forbidden_icon.png") # Ganti dengan URL ikon menarik
        embed.set_footer(text="Tetap semangat menjelajahi fitur lain!")
        
        message_sent = await ctx.send(embed=embed)
        # Opsional: Hapus pesan ini juga setelah beberapa detik agar tidak memenuhi chat
        await message_sent.delete(delay=15) # Hapus setelah 15 detik
    elif isinstance(error, commands.NotOwner):
        await ctx.send("❌ Maaf, command ini hanya bisa digunakan oleh **pemilik bot**.")
    else:
        await ctx.send(f"Terjadi error: {error}")
        print(f"Error di command help: {error}")


# Command untuk backup data dari folder root, data/, dan config/
@bot.command()
@commands.is_owner()
async def backupnow(ctx):
    """Membuat backup semua file .json di folder tertentu ke MongoDB."""
    await ctx.send("Starting backup process...")
    backup_data = {}

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
            
            print("✅ Backup data successfully saved to MongoDB.")
            await ctx.send("✅ Backup data successfully saved to MongoDB!")

        except Exception as e:
            await ctx.send(f"❌ Failed to save data to MongoDB: {e}")
            print(f"❌ Failed to save data to MongoDB: {e}")
    else:
        await ctx.send("🤷 No .json files found to backup.")

@bot.command()
@commands.is_owner()
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
        "cogs.koruptor",
        "cogs.psikotes"
    ]
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            print(f"✅ Loaded {extension}")
        except Exception as e:
            print(f"❌ Failed to load {extension}: {e}")

@bot.event
async def setup_hook():
    """Dipanggil sekali saat bot pertama kali startup."""
    print("🚀 Starting setup_hook and loading cogs...")
    await load_cogs()
    print(f"✅ Finished setup_hook and all cogs attempted to load.")
    print(f"All commands registered: {[command.name for command in bot.commands]}")


save_cookies_from_env()

keep_alive()

bot.run(os.getenv("DISCORD_TOKEN"))
