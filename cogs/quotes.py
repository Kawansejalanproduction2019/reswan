import discord
from discord.ext import commands
import json
import os
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class Quotes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file_path = os.path.join('data', 'quotes_config.json')
        self.quotes_file_path = os.path.join('data', 'quotes.json')
        self.bank_file_path = os.path.join('data', 'bank_data.json')
        self.level_file_path = os.path.join('data', 'level_data.json')
        self.config = self.load_config()

    def load_config(self):
        try:
            with open(self.config_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_config(self):
        with open(self.config_file_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)

    @commands.hybrid_command(name="setchannelq", help="Admin untuk mengatur channel kutipan.")
    @commands.has_permissions(manage_guild=True)
    async def set_quotes_channel(self, ctx, channel: discord.TextChannel):
        guild_id = str(ctx.guild.id)
        self.config[guild_id] = {'channel_id': channel.id}
        self.save_config()
        await ctx.send(f"✅ **Channel kutipan telah diatur ke `{channel.name}`**.", ephemeral=True)

    @commands.command(name="sendquote", help="Admin hanya untuk mengirim kutipan.")
    @commands.has_permissions(administrator=True)
    async def sendquote(self, ctx, *, quote_text: str):
        guild_id = str(ctx.guild.id)
        if guild_id not in self.config:
            await ctx.send("Channel kutipan belum diatur. Gunakan perintah `setchannel` terlebih dahulu.", ephemeral=True)
            return

        user_id = str(ctx.author.id)
        user_name = ctx.author.display_name
        self.save_quote_to_json(user_id, user_name, quote_text)
        logging.info(f"Admin {user_name} ({user_id}) telah mengirim kutipan: {quote_text}")

        channel_id = self.config[guild_id]['channel_id']
        channel = self.bot.get_channel(channel_id)
        if channel:
            embed = discord.Embed(title="Quotes", description=quote_text, color=0x00ff00)
            embed.set_footer(text=f"Quotes by {user_name}")
            msg = await channel.send(embed=embed)

            view = discord.ui.View(timeout=43200)
            approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.green)
            deny_button = discord.ui.Button(label="Deny", style=discord.ButtonStyle.red)

            approve_button.callback = lambda inter: self.approve_quote(inter, user_id, quote_text, msg.id)
            deny_button.callback = lambda inter: self.deny_quote(inter, msg)

            view.add_item(approve_button)
            view.add_item(deny_button)
            await msg.edit(view=view)

        await ctx.message.delete()

    @commands.command(name="resq", help="Kirim quotes.")
    async def resq(self, ctx, show_name: str = "yes", *, quote_text: str):
        guild_id = str(ctx.guild.id)
        if guild_id not in self.config:
            await ctx.send("Channel kutipan belum diatur oleh admin.", ephemeral=True)
            return
            
        user_id = str(ctx.author.id)
        user_name = ctx.author.display_name
        display_name = user_name if show_name.lower() in ["yes", "y", "true"] else "Anonymous"

        self.save_quote_to_json(user_id, display_name, quote_text)
        logging.info(f"User {user_name} ({user_id}) telah mengirim kutipan: {quote_text}")

        channel_id = self.config[guild_id]['channel_id']
        channel = self.bot.get_channel(channel_id)
        if channel:
            embed = discord.Embed(title="Quotes", description=quote_text, color=0x00ff00)
            embed.set_footer(text=f"Quotes by {display_name}")
            msg = await channel.send(embed=embed)

            view = discord.ui.View(timeout=43200)
            approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.green)
            deny_button = discord.ui.Button(label="Deny", style=discord.ButtonStyle.red)

            approve_button.callback = lambda inter: self.approve_quote(inter, user_id, quote_text, msg.id)
            deny_button.callback = lambda inter: self.deny_quote(inter, msg)

            view.add_item(approve_button)
            view.add_item(deny_button)
            await msg.edit(view=view)

        await ctx.message.delete()

    @commands.command(name="deletequote", help="Menghapus kutipan berdasarkan ID.")
    @commands.has_permissions(administrator=True)
    async def deletequote(self, ctx, quote_id: int):
        quotes = self.load_quotes_from_json()
        if 0 < quote_id <= len(quotes):
            quotes.pop(quote_id - 1)
            with open(self.quotes_file_path, 'w', encoding='utf-8') as f:
                json.dump(quotes, f, indent=4)
            await ctx.send(f"Kutipan dengan ID {quote_id} telah dihapus.")
            logging.info(f"Kutipan dengan ID {quote_id} telah dihapus oleh admin {ctx.author.display_name}.")
        else:
            await ctx.send("ID kutipan tidak valid. Silakan coba lagi.")

    @commands.command(name="listquotes", help="Menampilkan semua kutipan yang telah dikirim.")
    @commands.has_permissions(administrator=True)
    async def listquotes(self, ctx):
        quotes = self.load_quotes_from_json()
        if not quotes:
            await ctx.send("Tidak ada kutipan yang tersedia.")
            return
        
        embed = discord.Embed(title="Daftar Kutipan", color=0x00ff00)
        for quote in quotes:
            embed.add_field(name=f"ID {quote['id']}", value=f"{quote['text']} - **{quote['user']}**", inline=False)
        
        await ctx.send(embed=embed)

    def save_quote_to_json(self, user_id, user_name, quote_text):
        quotes = self.load_quotes_from_json()
        quotes.append({
            "id": len(quotes) + 1,
            "user": user_name,
            "text": quote_text,
            "user_id": user_id,
            "timestamp": str(datetime.now()),
            "is_random": False
        })
        with open(self.quotes_file_path, 'w', encoding='utf-8') as f:
            json.dump(quotes, f, indent=4)

    def load_quotes_from_json(self):
        try:
            with open(self.quotes_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Error loading quotes from JSON: {e}")
            return []

    async def approve_quote(self, interaction: discord.Interaction, user_id, quote_text, message_id):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Anda bukan admin! Hanya admin yang dapat memberikan persetujuan.", ephemeral=True)
            return
        
        await self.give_reward(interaction.guild.id, user_id, 100, 100)
        await interaction.response.send_message(f"✅ Kutipan disetujui! Pengguna mendapatkan 100 EXP dan 100 RSWN.", ephemeral=True)

        user = self.bot.get_user(int(user_id))
        if user:
            try:
                await user.send(f"😢 Kutipanmu: \"{quote_text}\" telah disetujui, dan kamu mendapatkan 100 EXP dan 100 RSWN. "
                                f"Semoga ini sedikit menghiburmu di hari yang kelabu ini. 🌧️")
            except discord.Forbidden:
                logging.warning(f"Tidak dapat mengirim DM ke user {user_id}. DM mereka mungkin tertutup.")
    
        await interaction.message.edit(view=None)

    async def deny_quote(self, interaction: discord.Interaction, msg):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Anda bukan admin! Hanya admin yang dapat memberikan penolakan.", ephemeral=True)
            return
        
        await msg.delete()
        await interaction.response.send_message("Kutipan telah ditolak dan dihapus.", ephemeral=True)

    async def give_reward(self, server_id, user_id, exp, rswn):
        try:
            with open(self.level_file_path, 'r', encoding='utf-8') as f:
                level_data = json.load(f)
            
            server_data = level_data.get(str(server_id), {})
            user_levels = server_data.get(user_id, {'level': 1, 'exp': 0})
            user_levels['exp'] += exp

            if user_levels['exp'] >= 10000:
                user_levels['level'] += 1
                user_levels['exp'] -= 10000
            
            if str(server_id) not in level_data:
                level_data[str(server_id)] = {}
            level_data[str(server_id)][user_id] = user_levels

            with open(self.level_file_path, 'w', encoding='utf-8') as f:
                json.dump(level_data, f, indent=4)

            with open(self.bank_file_path, 'r', encoding='utf-8') as f:
                bank_data = json.load(f)
            
            if user_id in bank_data:
                bank_data[user_id]['balance'] += rswn
            else:
                bank_data[user_id] = {'balance': rswn, 'debt': 0}

            with open(self.bank_file_path, 'w', encoding='utf-8') as f:
                json.dump(bank_data, f, indent=4)

            logging.info(f"User {user_id} di server {server_id} diberi hadiah: {exp} EXP dan {rswn} RSWN.")
        except Exception as e:
            logging.error(f"Error memberikan hadiah kepada user {user_id} di server {server_id}: {e}")

async def setup(bot):
    await bot.add_cog(Quotes(bot))
