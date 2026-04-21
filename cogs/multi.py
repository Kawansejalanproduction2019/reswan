import discord
from discord.ext import commands
import os
import json
import time
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGODB_URI")
mongo_client = MongoClient(MONGO_URI) if MONGO_URI else None
mongo_db = mongo_client["reSwan"] if mongo_client is not None else None
mongo_col = mongo_db["bot_data"] if mongo_db is not None else None

ACTIVITY_FILE = 'data/bot_activity.json'

def load_activity():
    if mongo_col is not None:
        try:
            doc = mongo_col.find_one({"_id": ACTIVITY_FILE})
            if doc and "data" in doc:
                return doc["data"]
        except Exception:
            pass
    if not os.path.exists(ACTIVITY_FILE):
        os.makedirs(os.path.dirname(ACTIVITY_FILE), exist_ok=True)
        default = {"type": "watching", "name": "Kestabilan Server"}
        with open(ACTIVITY_FILE, 'w', encoding='utf-8') as f:
            json.dump(default, f)
        return default
    try:
        with open(ACTIVITY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"type": "watching", "name": "Kestabilan Server"}

def save_activity(data):
    try:
        os.makedirs(os.path.dirname(ACTIVITY_FILE), exist_ok=True)
        with open(ACTIVITY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass
    if mongo_col is not None:
        try:
            mongo_col.update_one(
                {"_id": ACTIVITY_FILE},
                {"$set": {"data": data, "updated_at": time.time()}},
                upsert=True
            )
        except Exception:
            pass

class CustomActModal(discord.ui.Modal, title="Set Activity Manual"):
    act_name = discord.ui.TextInput(label="Nama Activity", placeholder="Ketik teks activity...", max_length=100)

    def __init__(self, act_type, cog):
        super().__init__()
        self.act_type = act_type
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        name = self.act_name.value.strip()
        await self.cog.apply_activity(interaction, self.act_type, name)

class ActSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        options = [
            discord.SelectOption(label="Watching Moderation All Server", value="watch_mod", emoji="👁️"),
            discord.SelectOption(label="Watching Kestabilan & Keamanan", value="watch_sec", emoji="🛡️"),
            discord.SelectOption(label="Watching Tingkah Laku Member", value="watch_mem", emoji="👀"),
            discord.SelectOption(label="Watching Anime Donghua", value="watch_anime", emoji="📺"),
            discord.SelectOption(label="Listening Spotify", value="list_spot", emoji="🎧"),
            discord.SelectOption(label="Listening Curhatan Member", value="list_curhat", emoji="👂"),
            discord.SelectOption(label="Listening Perintah Master Rhdevs", value="list_master", emoji="👑"),
            discord.SelectOption(label="Playing Roblox", value="play_rbx", emoji="🎮"),
            discord.SelectOption(label="Playing GTA Roleplay", value="play_gta", emoji="🚗"),
            discord.SelectOption(label="Playing Catur 4D", value="play_chess", emoji="♟️"),
            discord.SelectOption(label="Custom Playing...", value="custom_play", emoji="✏️"),
            discord.SelectOption(label="Custom Watching...", value="custom_watch", emoji="✏️"),
            discord.SelectOption(label="Custom Listening...", value="custom_list", emoji="✏️")
        ]
        super().__init__(placeholder="Pilih Activity Bot...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        presets = {
            "watch_mod": ("watching", "Moderation All Server"),
            "watch_sec": ("watching", "Kestabilan & Keamanan Server"),
            "watch_mem": ("watching", "Tingkah Laku Member"),
            "watch_anime": ("watching", "Anime Donghua"),
            "list_spot": ("listening", "Spotify"),
            "list_curhat": ("listening", "Curhatan Member"),
            "list_master": ("listening", "Perintah Master Rhdevs"),
            "play_rbx": ("playing", "Roblox"),
            "play_gta": ("playing", "GTA Roleplay"),
            "play_chess": ("playing", "Catur 4D")
        }

        if val in presets:
            act_type, act_name = presets[val]
            await self.cog.apply_activity(interaction, act_type, act_name)
        elif val == "custom_play":
            await interaction.response.send_modal(CustomActModal("playing", self.cog))
        elif val == "custom_watch":
            await interaction.response.send_modal(CustomActModal("watching", self.cog))
        elif val == "custom_list":
            await interaction.response.send_modal(CustomActModal("listening", self.cog))

class ActView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=120)
        self.add_item(ActSelect(cog))

class BotActivity(commands.Cog, name="Bot Activity Manager"):
    def __init__(self, bot):
        self.bot = bot

    async def apply_activity(self, interaction, act_type, act_name):
        save_activity({"type": act_type, "name": act_name})
        
        if act_type == "watching":
            act_obj = discord.Activity(type=discord.ActivityType.watching, name=act_name)
        elif act_type == "listening":
            act_obj = discord.Activity(type=discord.ActivityType.listening, name=act_name)
        else:
            act_obj = discord.Game(name=act_name)
            
        await self.bot.change_presence(activity=act_obj)
        
        msg = f"✅ Status berhasil diupdate: **{act_type.capitalize()} {act_name}**"
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        data = load_activity()
        act_type = data.get("type", "watching")
        act_name = data.get("name", "Kestabilan Server")
        
        if act_type == "watching":
            act_obj = discord.Activity(type=discord.ActivityType.watching, name=act_name)
        elif act_type == "listening":
            act_obj = discord.Activity(type=discord.ActivityType.listening, name=act_name)
        else:
            act_obj = discord.Game(name=act_name)
            
        await self.bot.change_presence(activity=act_obj)

    @commands.command(name="act", aliases=["setact", "statusbot"])
    @commands.is_owner()
    async def set_activity_cmd(self, ctx):
        embed = discord.Embed(
            title="⚙️ Pengaturan Activity Bot",
            description="Pilih status presence bot melalui menu dropdown di bawah ini. Jika memilih *Custom*, form isian akan muncul.",
            color=0x3498DB
        )
        await ctx.send(embed=embed, view=ActView(self))

async def setup(bot):
    await bot.add_cog(BotActivity(bot))
