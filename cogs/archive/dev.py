import discord
from discord.ext import commands

class DevTools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        return await self.bot.is_owner(ctx.author)

    @commands.command(name="listserver")
    async def list_servers(self, ctx):
        msg = "List Server Bot:\n"
        for guild in self.bot.guilds:
            msg += f"Name: {guild.name} | ID: {guild.id} | Owner: {guild.owner} | Members: {guild.member_count}\n"
        
        if len(msg) > 2000:
            for i in range(0, len(msg), 1900):
                await ctx.send(f"```\n{msg[i:i+1900]}\n```")
        else:
            await ctx.send(f"```\n{msg}\n```")

    @commands.command(name="listchannel")
    async def list_channels(self, ctx, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            await ctx.send("Server tidak ditemukan atau bot tidak ada di server tersebut.")
            return

        msg = f"Detail Server: {guild.name} ({guild.id})\n"
        msg += f"Owner: {guild.owner}\n"
        msg += f"Total Channels: {len(guild.channels)}\n\nList Channel:\n"
        
        categories = {}
        for channel in guild.channels:
            cat_name = channel.category.name if channel.category else "No Category"
            if cat_name not in categories:
                categories[cat_name] = []
            categories[cat_name].append(channel)

        for cat, channels in categories.items():
            msg += f"--- {cat} ---\n"
            for c in channels:
                c_type = str(c.type).upper()
                msg += f"[{c_type}] {c.name} | ID: {c.id}\n"
            msg += "\n"

        if len(msg) > 2000:
            for i in range(0, len(msg), 1900):
                await ctx.send(f"```\n{msg[i:i+1900]}\n```")
        else:
            await ctx.send(f"```\n{msg}\n```")

async def setup(bot):
    await bot.add_cog(DevTools(bot))

