import discord
from discord.ext import commands
import json
import os
import random
from datetime import datetime

class Economy(commands.Cog):
    def __init__(self, bot):  # Perbaikan: __init__ bukan init
        self.bot = bot
        self.min_rswn = 20
        self.max_rswn = 50

    def load_data(self, filename):  
        if not os.path.exists(f"data/{filename}"):  
            return {} if filename.endswith(".json") else {"items": {}}  
        with open(f"data/{filename}", "r") as f:  
            return json.load(f)  

    def save_data(self, data, filename):  
        os.makedirs("data", exist_ok=True)  # Membuat folder data jika belum ada
        with open(f"data/{filename}", "w") as f:  
            json.dump(data, f, indent=4)  

    
    @commands.command()  
    @commands.has_permissions(administrator=True)  
    async def add_money(self, ctx, member: discord.Member, amount: int):  
        """Add money to a user's account (Admin only)"""
        bank_data = self.load_data("bank_data.json")  
        user_id = str(member.id)  
          
        if user_id not in bank_data:  
            bank_data[user_id] = {"balance": 0, "debt": 0}  
          
        bank_data[user_id]["balance"] += amount  
        self.save_data(bank_data, "bank_data.json")  
        await ctx.send(f"✅ Added {amount} RSWN to {member.mention}'s account!")

async def setup(bot):
    await bot.add_cog(Economy(bot))