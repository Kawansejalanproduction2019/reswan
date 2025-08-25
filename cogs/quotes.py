import discord
from discord.ext import commands
import json
import os
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class Quotes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = 1255226119221940265  # Ganti dengan ID channel yang sesuai
        self.quotes_file_path = os.path.join('data', 'quotes.json')
        self.bank_file_path = os.path.join('data', 'bank_data.json')
        self.level_file_path = os.path.join('data', 'level_data.json')

    @commands.command(name="sendquote", help="Admin hanya untuk mengirim kutipan.")
    @commands.has_permissions(administrator=True)
    async def sendquote(self, ctx, *, quote_text: str):
        user_id = str(ctx.author.id)
        user_name = ctx.author.display_name

        # Simpan kutipan ke JSON
        self.save_quote_to_json(user_id, user_name, quote_text)
        logging.info(f"Admin {user_name} ({user_id}) telah mengirim kutipan: {quote_text}")

        # Kirim kutipan ke channel yang ditentukan
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            embed = discord.Embed(title="Quotes", description=quote_text, color=0x00ff00)
            embed.set_footer(text=f"Quotes by {user_name}")
            msg = await channel.send(embed=embed)  # Kirim ke channel yang ditentukan

            # Tambahkan buttons untuk review oleh admin
            view = discord.ui.View(timeout=43200)  # Timeout 12 jam (43200 detik)
            approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.green)
            deny_button = discord.ui.Button(label="Deny", style=discord.ButtonStyle.red)

            approve_button.callback = lambda inter: self.approve_quote(inter, user_id, quote_text, msg.id)
            deny_button.callback = lambda inter: self.deny_quote(inter, msg)

            view.add_item(approve_button)
            view.add_item(deny_button)

            await msg.edit(view=view)  # Edit pesan untuk menambahkan tombol

        await ctx.message.delete()  # Hapus pesan admin setelah mengirim kutipan

    @commands.command(name="resq", help="Kirim quotes.")
    async def resq(self, ctx, show_name: str = "yes", *, quote_text: str):
        user_id = str(ctx.author.id)
        user_name = ctx.author.display_name
        display_name = user_name if show_name.lower() in ["yes", "y", "true"] else "Anonymous"

        # Simpan quotes ke JSON
        self.save_quote_to_json(user_id, display_name, quote_text)
        logging.info(f"User {user_name} ({user_id}) telah mengirim kutipan: {quote_text}")

        # Kirim ke channel yang ditentukan
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            embed = discord.Embed(title="Quotes", description=quote_text, color=0x00ff00)
            embed.set_footer(text=f"Quotes by {display_name}")
            msg = await channel.send(embed=embed)  # Kirim ke channel yang ditentukan

            # Tambahkan buttons untuk review oleh admin
            view = discord.ui.View(timeout=43200)  # Timeout 12 jam (43200 detik)
            approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.green)
            deny_button = discord.ui.Button(label="Deny", style=discord.ButtonStyle.red)

            approve_button.callback = lambda inter: self.approve_quote(inter, user_id, quote_text, msg.id)
            deny_button.callback = lambda inter: self.deny_quote(inter, msg)

            view.add_item(approve_button)
            view.add_item(deny_button)

            await msg.edit(view=view)  # Edit pesan untuk menambahkan tombol

        await ctx.message.delete()  # Hapus pesan pengguna setelah mengirim kutipan

    @commands.command(name="deletequote", help="Menghapus kutipan berdasarkan ID.")
    @commands.has_permissions(administrator=True)
    async def deletequote(self, ctx, quote_id: int):
        quotes = self.load_quotes_from_json()
        if 0 < quote_id <= len(quotes):
            deleted_quote = quotes.pop(quote_id - 1)  # Hapus kutipan berdasarkan ID
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
            "is_random": False  # Kutipan yang dikirim oleh admin tidak dapat diacak
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
        
        # Proses persetujuan kutipan dengan memberikan 100 EXP dan 100 RSWN
        await self.give_reward(interaction.guild.id, user_id, 100, 100)  # Menambahkan 100 EXP dan 100 RSWN
        await interaction.response.send_message(f"✅ Kutipan disetujui! Pengguna {quote_text} mendapatkan 100 EXP dan 100 RSWN.", ephemeral=True)

        # Kirim DM kepada pengguna yang kutipannya disetujui
        user = self.bot.get_user(int(user_id))
        if user:
            await user.send(f"😢 Kutipanmu: \"{quote_text}\" telah disetujui, dan kamu mendapatkan 100 EXP dan 100 RSWN. "
                            f"Semoga ini sedikit menghiburmu di hari yang kelabu ini. 🌧️")
    
        # Hapus tombol setelah disetujui
        await interaction.message.edit(view=None)

    async def deny_quote(self, interaction: discord.Interaction, msg):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Anda bukan admin! Hanya admin yang dapat memberikan penolakan.", ephemeral=True)
            return
        
        # Hapus pesan jika admin memberikan deny
        await msg.delete()  # Hapus pesan kutipan
        await interaction.response.send_message("Kutipan telah ditolak dan dihapus.", ephemeral=True)

    async def give_reward(self, server_id, user_id, exp, rswn):
        try:
            # Memperbarui level_data.json
            with open(self.level_file_path, 'r', encoding='utf-8') as f:
                level_data = json.load(f)

            # Ambil data level pengguna atau buat baru jika tidak ada
            server_data = level_data.get(str(server_id), {})
            user_levels = server_data.get(user_id, {'level': 1, 'exp': 0})

            # Tambahkan EXP
            user_levels['exp'] += exp

            # Level up jika cukup EXP
            if user_levels['exp'] >= 10000:  # Misalnya, threshold level up
                user_levels['level'] += 1
                user_levels['exp'] -= 10000  # Sisa EXP setelah level up

            # Simpan kembali data level pengguna
            if str(server_id) not in level_data:
                level_data[str(server_id)] = {}
            level_data[str(server_id)][user_id] = user_levels

            with open(self.level_file_path, 'w', encoding='utf-8') as f:
                json.dump(level_data, f, indent=4)

            # Memperbarui bank_data.json
            with open(self.bank_file_path, 'r', encoding='utf-8') as f:
                bank_data = json.load(f)

            # Tambahkan RSWN
            if user_id in bank_data:
                bank_data[user_id]['balance'] += rswn
            else:
                bank_data[user_id] = {'balance': rswn, 'debt': 0}

            with open(self.bank_file_path, 'w', encoding='utf-8') as f:
                json.dump(bank_data, f, indent=4)

            logging.info(f"User {user_id} di server {server_id} diberi hadiah: {exp} EXP dan {rswn} RSWN.")
        except Exception as e:
            logging.error(f"Error memberikan hadiah kepada user {user_id} di server {server_id}: {e}")

# Memungkinkan pengaturan cog
async def setup(bot):
    await bot.add_cog(Quotes(bot))
