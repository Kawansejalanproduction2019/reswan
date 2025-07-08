import discord
from discord.ext import commands, tasks
import asyncio
import json
from datetime import datetime

CHANNEL_ID = 1379458566452154438  # ID channel target

LEVEL_FILE = 'data/level_data.json'
BANK_FILE = 'data/bank_data.json'

def load_data(guild_id):
    try:
        with open(LEVEL_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get(str(guild_id), {})
    except Exception:
        return {}

def save_data(guild_id, data):
    try:
        with open(LEVEL_FILE, 'r', encoding='utf-8') as f:
            full_data = json.load(f)
    except:
        full_data = {}

    full_data[str(guild_id)] = data
    with open(LEVEL_FILE, 'w', encoding='utf-8') as f:
        json.dump(full_data, f, indent=4)

def load_bank_data():
    try:
        with open(BANK_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

class Repeat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.message = "!rank"
        self.interval = 500  # Detik
        self.repeat_message.start()

    @tasks.loop(seconds=500)
    async def repeat_message(self):
        channel = self.bot.get_channel(CHANNEL_ID)
        if channel:
            await channel.send(self.message)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.channel.id != CHANNEL_ID:
            return

        if message.content.strip() == "!rank":
            user_id = str(message.author.id)
            guild_id = str(message.guild.id)

            data = load_data(guild_id)
            bank = load_bank_data()

            # Inisialisasi data jika belum ada
            if user_id not in data:
                data[user_id] = {
                    "exp": 0,
                    "level": 0,
                    "weekly_exp": 0,
                    "badges": [],
                    "booster": {},
                    "last_active": datetime.utcnow().isoformat()
                }
                save_data(guild_id, data)

            user_data = data[user_id]
            badges = " ".join(user_data.get("badges", [])) or "Tidak ada"
            balance = bank.get(user_id, {}).get("balance", 0)

            embed = discord.Embed(
                title=f"📊 Rank {message.author.display_name}",
                color=discord.Color.purple()
            )
            embed.set_thumbnail(url=message.author.avatar.url if message.author.avatar else discord.Embed.Empty)
            embed.add_field(name="Level", value=user_data["level"], inline=True)
            embed.add_field(name="EXP", value=user_data["exp"], inline=True)
            embed.add_field(name="Saldo", value=f"{balance} 🪙RSWN", inline=True)
            embed.add_field(name="Badges", value=badges, inline=False)

            await message.channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Repeat(bot))
