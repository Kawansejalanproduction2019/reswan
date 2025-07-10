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
from pymongo import MongoClient, errors as pymongo_errors # Import errors for specific exception handling
from dotenv import load_dotenv
from datetime import datetime

load_dotenv() # Load environment variables from .env file

# --- Setup Logging ---
# Set logging level to DEBUG to see detailed messages, INFO for less verbose output
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
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
    log.debug(f"Attempting to connect to MongoDB with URI: {mongo_uri}")
    # Initialize MongoClient with a timeout for server selection
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000) # 5-second timeout for connection
    
    # Define database and collection names
    db = client["reSwan"]
    collection = db["Data collection"]
    
    # Attempt a simple ping command to verify the connection works
    log.debug("Attempting MongoDB ping to verify connection...")
    client.admin.command('ping') 
    log.info("✅ Successfully connected to MongoDB!")
    log.debug("MongoDB connection verified successfully.")
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

# --- Custom Help Command (Admin Only) ---
@bot.command(name="help", aliases=["halp", "h"])
@commands.has_permissions(administrator=True) # Only users with Administrator permission can use this
async def custom_help(ctx, *, command_name: str = None):
    """
    Menampilkan informasi bantuan untuk admin.
    Jika ada command_name, akan menampilkan bantuan untuk command tersebut.
    Jika tidak, akan menampilkan daftar semua command yang tersedia.
    """
    if command_name:
        # Try to find a command or a cog
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
                # Get commands from the cog that are not hidden
                cog_commands = [f"`{ctx.prefix}{c.name}`" for c in cmd.get_commands() if not c.hidden]
                if cog_commands:
                    embed.description += ", ".join(cog_commands)
                else:
                    embed.description += "Tidak ada command di cog ini."
            
            message_sent = await ctx.send(embed=embed)
            await message_sent.delete(delay=60) # Delete message after 1 minute
        else:
            message_sent = await ctx.send(f"Command atau Cog `{command_name}` tidak ditemukan.")
            await message_sent.delete(delay=60)
    else:
        # Display a list of all commands and cogs
        embed = discord.Embed(
            title="Daftar Command Bot (Admin Only)",
            description="Berikut adalah semua command yang bisa kamu gunakan:",
            color=discord.Color.green()
        )

        for cog_name, cog in bot.cogs.items():
            # Skip Jishaku if it's an internal development cog
            if cog_name == "Jishaku": 
                continue
            
            # Get commands from the cog that are not hidden
            commands_in_cog = [f"`{ctx.prefix}{command.name}`" for command in cog.get_commands() if not command.hidden]
            if commands_in_cog:
                embed.add_field(name=f"__**{cog_name}**__", value=" ".join(commands_in_cog), inline=False)
            
        # Get commands that are not part of any cog and are not hidden
        no_cog_commands = [f"`{ctx.prefix}{command.name}`" for command in bot.commands if command.cog is None and not command.hidden]
        if no_cog_commands:
            embed.add_field(name="__**Lain-lain**__", value=" ".join(no_cog_commands), inline=False)

        embed.set_footer(text=f"Gunakan {ctx.prefix}help <command> untuk detail. Pesan ini akan hilang dalam 1 menit.")
        message_sent = await ctx.send(embed=embed)
        await message_sent.delete(delay=60)


@custom_help.error
async def custom_help_error(ctx, error):
    """Error handler for the custom help command."""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="Akses Ditolak! 🚫",
            description=(
                "Oops! Sepertinya kamu mencoba mengakses area terlarang.\n"
                "Command ini hanya untuk mata-mata terpilih yang memiliki izin khusus.\n\n"
                "Jika kamu merasa ini adalah kesalahan, hubungi petinggi server ya! 😉"
            ),
            color=discord.Color.red()
        )
        embed.set_thumbnail(url="https://i.imgur.com/example_forbidden_icon.png") # Placeholder image
        embed.set_footer(text="Tetap semangat menjelajahi fitur lain!")
        
        message_sent = await ctx.send(embed=embed)
        await message_sent.delete(delay=15) # Delete after 15 seconds
    elif isinstance(error, commands.NotOwner):
        await ctx.send("❌ Maaf, command ini hanya bisa digunakan oleh **pemilik bot**.", ephemeral=True)
    else:
        await ctx.send(f"❌ Terjadi error: {error}", ephemeral=True)
        log.error(f"Error in custom help command: {error}", exc_info=True)


# --- Backup Commands (Owner Only) ---
@bot.command()
@commands.is_owner()
async def backupnow(ctx):
    """Creates a backup of all .json files in specified folders to MongoDB."""
    await ctx.send("Starting backup process...")
    backup_data = {}

    # Verify MongoDB client connection before proceeding
    if not client:
        await ctx.send("❌ MongoDB client not initialized. Cannot perform backup.", ephemeral=True)
        log.error("MongoDB client is None, cannot perform backupnow.")
        return

    try:
        # Ping MongoDB to ensure active connection
        client.admin.command('ping') 
    except Exception as e:
        await ctx.send(f"❌ Gagal terhubung ke MongoDB untuk backup: {e}. Tidak dapat melakukan backup.", ephemeral=True)
        log.error(f"MongoDB ping failed for backupnow command: {e}", exc_info=True)
        return

    directories_to_scan = ['.', 'data/', 'config/'] # Folders to scan for JSON files

    for directory in directories_to_scan:
        if not os.path.isdir(directory):
            log.warning(f"Directory '{directory}' not found, skipping for backup.")
            continue
        
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if filename.endswith('.json') and os.path.isfile(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                        backup_data[file_path] = json_data # Store JSON data in the backup dictionary
                        log.info(f"✅ File '{file_path}' successfully read for backup.")
                except json.JSONDecodeError as e:
                    await ctx.send(f"❌ Failed to read JSON file for backup: `{file_path}`. Error: {e}")
                    log.error(f"❌ Failed to read JSON file for backup: {file_path}, Error: {e}", exc_info=True)
                except Exception as e:
                    await ctx.send(f"❌ An unexpected error occurred while reading `{file_path}` for backup: {e}")
                    log.error(f"❌ An unexpected error occurred while reading `{file_path}` for backup: {e}", exc_info=True)

    if backup_data:
        try:
            # Update or insert the latest backup document in MongoDB
            collection.update_one(
                {"_id": "latest_backup"},
                {"$set": {
                    "backup": backup_data,
                    "timestamp": datetime.utcnow()
                }},
                upsert=True # Create the document if it doesn't exist
            )
            
            log.info("✅ Backup data successfully saved to MongoDB.")
            await ctx.send("✅ Backup data successfully saved to MongoDB!")

        except pymongo_errors.PyMongoError as e: # Catch PyMongo specific errors
            # This will catch authentication errors, connection errors, etc.
            await ctx.send(f"❌ Failed to save data to MongoDB: {e}")
            log.error(f"❌ Failed to save data to MongoDB: {e}", exc_info=True)
        except Exception as e:
            await ctx.send(f"❌ An unexpected error occurred while saving data to MongoDB: {e}")
            log.error(f"❌ An unexpected error occurred while saving data to MongoDB: {e}", exc_info=True)
    else:
        await ctx.send("🤷 No .json files found to backup.")
        log.warning("No .json files found to backup.")

@bot.command()
@commands.is_owner()
async def sendbackup(ctx):
    """Sends the latest backup file from MongoDB to the bot owner's DM."""
    # Verify MongoDB client connection
    if not client:
        await ctx.send("❌ MongoDB client not initialized. Cannot retrieve backup.", ephemeral=True)
        log.error("MongoDB client is None, cannot perform sendbackup.")
        return

    try:
        client.admin.command('ping') # Ping MongoDB to ensure active connection
    except Exception as e:
        await ctx.send(f"❌ Gagal terhubung ke MongoDB untuk mengirim backup: {e}. Tidak dapat mengambil backup.", ephemeral=True)
        log.error(f"MongoDB ping failed for sendbackup command: {e}", exc_info=True)
        return

    user_id = 1000737066822410311  # Replace with your Discord User ID
    user = await bot.fetch_user(user_id) # Fetch the user object

    try:
        stored_data = collection.find_one({"_id": "latest_backup"})
        if not stored_data or 'backup' not in stored_data:
            await ctx.send("❌ No backup data available.")
            log.warning("No backup data available in MongoDB.")
            return

        backup_data = stored_data["backup"]
        await ctx.send("📬 Sending backup files one by one to DM...")
        log.info("Starting to send backup files to owner DM.")

        for file_path, content in backup_data.items():
            filename = os.path.basename(file_path)
            
            # Convert JSON content to a BytesIO object for sending as a file
            string_content = json.dumps(content, indent=4, ensure_ascii=False)
            byte_buffer = io.BytesIO(string_content.encode('utf-8'))
            
            file = discord.File(fp=byte_buffer, filename=filename)

            try:
                await user.send(content=f"📄 Here's a backup file from `/{file_path}`:", file=file)
                log.info(f"✅ File '{filename}' successfully sent to DM.")
            except discord.HTTPException as e:
                await ctx.send(f"❌ Failed to send file `{filename}` to DM: {e}")
                log.error(f"❌ Failed to send file `{filename}` to DM: {e}", exc_info=True)
            except Exception as e:
                await ctx.send(f"❌ An unexpected error occurred while sending `{filename}` to DM: {e}")
                log.error(f"❌ An unexpected error occurred while sending `{filename}` to DM: {e}", exc_info=True)
            
            byte_buffer.seek(0) # Reset buffer position for the next file

        await ctx.send("✅ All backup files successfully sent to DM!")
        log.info("All backup files successfully sent to owner DM.")

    except discord.Forbidden:
        await ctx.send("❌ Failed to send DM. Make sure I can send DMs to this user.")
        log.error("❌ Bot forbidden from sending DM to owner for backup.")
    except pymongo_errors.PyMongoError as e:
        await ctx.send(f"❌ An error occurred while retrieving backup data from MongoDB: {e}")
        log.error(f"❌ Failed to retrieve data from MongoDB: {e}", exc_info=True)
    except Exception as e:
        await ctx.send(f"❌ An unexpected error occurred while retrieving backup data: {e}")
        log.error(f"❌ An unexpected error occurred while retrieving backup data: {e}", exc_info=True)

# --- Cog Loading ---
async def load_cogs():
    """Loads all cogs from the 'cogs' folder."""
    # List of cog extensions to load. Ensure these names match your Python file names in the 'cogs' folder.
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
        "cogs.multigame"
        "cogs.dunia",
        "cogs.koruptor",
        "cogs.psikotes",
        "cogs.tempvoice",
        "cogs.endgame",
        "cogs.personality",
        "cogs.psikotes"
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
    await load_extension()
    log.info(f"✅ Finished setup_hook and all cogs attempted to load.")
    # Log registered commands after cogs are loaded
    log.info(f"All commands registered: {[command.name for command in bot.commands]}")

# --- Entry Point of the Bot ---
# Save cookies if configured (for yt-dlp)
save_cookies_from_env()

# Run the bot with the Discord token from environment variables
bot.run(os.getenv("DISCORD_TOKEN"))
