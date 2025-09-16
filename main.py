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

load_dotenv() # Load environment variables from .env file

# --- Setup Logging ---
# Set logging level to INFO for general information, WARNING/ERROR for issues.
# Remove DEBUG to avoid excessive logging unless specifically troubleshooting.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__) # Get a logger instance for this module

# --- Helper to save cookies from environment variable ---
def save_cookies_from_env():
    """Reads base64 encoded cookies from environment variable and saves them to a file."""
    encoded = os.getenv("COOKIES_BASE64")
    if not encoded:
        log.warning("Environment variable COOKIES_BASE64 not found. Skipping cookies.txt creation.")
        return # Don't raise error, allow bot to run without cookies if not set
    
    try:
        decoded = base64.b64decode(encoded)
        with open("cookies.txt", "wb") as f:
            f.write(decoded)
        log.info("✅ File cookies.txt successfully created from environment variable.")
    except Exception as e:
        log.error(f"❌ Failed to decode or save cookies: {e}")

# --- MongoDB Connection ---
mongo_uri = os.getenv("MONGODB_URI")
if not mongo_uri:
    log.critical("Environment variable MONGODB_URI not found. Bot cannot connect to MongoDB.")
    # If MONGODB_URI is not set, it's a critical configuration error, so raise an exception
    raise ValueError("Environment variable MONGODB_URI not found. Please set it up.")

# Global client, db, and collection variables, initialized here for accessibility
client = None
db = None
collection = None

try:
    log.info(f"Attempting to connect to MongoDB...") # Simplified log
    # Initialize MongoClient with a timeout for server selection
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000) # 5-second timeout for connection
    
    # Define database and collection names
    db = client["reSwan"]
    collection = db["Data collection"]
    
    # Attempt a simple ping command to verify the connection works
    client.admin.command('ping') 
    log.info("✅ Successfully connected to MongoDB!")
except pymongo_errors.ServerSelectionTimeoutError as err:
    log.critical(f"❌ MongoDB Server Selection Timeout: {err}. Check your network connection and MongoDB Atlas IP whitelist settings.")
    # If connection fails at startup, raise an exception to prevent the bot from running
    raise Exception("MongoDB connection failed at startup.") from err
except pymongo_errors.ConfigurationError as err:
    log.critical(f"❌ MongoDB Configuration Error: {err}. Check your MONGODB_URI format and credentials carefully.")
    raise Exception("MongoDB configuration failed at startup.") from err
except Exception as e:
    log.critical(f"❌ An unexpected error occurred during MongoDB connection: {e}")
    raise Exception("Unexpected MongoDB connection error at startup.") from e

# --- Keep Alive for Replit or similar hosting ---
try:
    from keep_alive import keep_alive
    # Call keep_alive if successfully imported
    keep_alive()
    log.info("✅ `keep_alive.py` found and initiated.")
except ImportError:
    log.warning("`keep_alive.py` not found. If you are not using Replit, this is normal and can be ignored.")
    def keep_alive(): # Define a dummy function to avoid errors if not imported
        pass
except Exception as e:
    log.error(f"❌ Error calling keep_alive: {e}", exc_info=True)


# --- Discord Intents Configuration ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True # Required to read message content from Discord API v2
intents.guilds = True
intents.members = True # Required for member caching and voice state updates
intents.voice_states = True # Required for voice channel monitoring (Music, TempVoice cogs)

# --- Bot Initialization ---
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None) # help_command=None to use custom help

# --- Bot Events ---
@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord."""
    log.info(f"😎 Bot {bot.user} is now online!")

@bot.event
async def on_message(message):
    # Ignore messages from bots to prevent infinite loops or unwanted processing
    if message.author.bot:
        return
    # Process commands found in the message
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


# --- Cog Loading ---
async def load_cogs():
    """Loads all cogs from the 'cogs' folder."""
    # This list will be dynamically generated by scanning the 'cogs' directory.
    initial_extensions = [
        "cogs.music"
    ]
    for extension in initial_extensions:
        try:
            await bot.load_extension(extension)
            log.info(f"✅ Loaded {extension}")
        except Exception as e:
            log.error(f"❌ Failed to load {extension}: {e}", exc_info=True) # Log full traceback on error


@bot.event
async def setup_hook():
    """Called once when the bot first starts up."""
    log.info("🚀 Starting setup_hook and loading cogs...")
    await load_cogs()
    log.info(f"✅ Finished setup_hook and all cogs attempted to load.")
    # Log registered commands after cogs are loaded
    log.info(f"All commands registered: {[command.name for command in bot.commands]}")

# --- Entry Point of the Bot ---
# Save cookies if configured (for yt-dlp)
save_cookies_from_env()

# Run the bot with the Discord token from environment variables
bot.run(os.getenv("DISCORD_TOKEN"))
