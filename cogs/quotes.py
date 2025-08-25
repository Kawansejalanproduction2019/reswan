import discord
from discord.ext import commands
import json
import os
from datetime import datetime
import logging
import asyncio
import functools

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions (Memuat dan menyimpan data) ---
def load_json_data(file_path, default_value=None):
    """Membantu memuat data JSON dengan penanganan error."""
    if default_value is None:
        default_value = {}
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.warning(f"File {file_path} tidak ditemukan atau rusak. Membuat file baru.")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(default_value, f, indent=4)
        return default_value

def save_json_data(file_path, data):
    """Membantu menyimpan data ke file JSON."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# --- Kelas View untuk Interaksi Tombol ---
class QuoteApprovalView(discord.ui.View):
    def __init__(self, cog, user_id, quote_text, is_anonymous):
        super().__init__(timeout=43200) # Timeout 12 jam
        self.cog = cog
        self.user_id = user_id
        self.quote_text = quote_text
        self.is_anonymous = is_anonymous
    
    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="approve_quote_button")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Anda tidak memiliki izin untuk menyetujui kutipan ini.", ephemeral=True)
        
        await interaction.response.send_message("✅ Kutipan telah disetujui! Hadiah sedang diproses...", ephemeral=True)
        await self.cog.approve_quote_action(interaction, self.user_id, self.quote_text, self.is_anonymous)
        self.stop() # Hentikan interaksi setelah selesai
    
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, custom_id="deny_quote_button")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Anda tidak memiliki izin untuk menolak kutipan ini.", ephemeral=True)
        
        await interaction.message.delete()
        await interaction.response.send_message("❌ Kutipan telah ditolak dan dihapus.", ephemeral=True)
        self.stop() # Hentikan interaksi setelah selesai

class Quotes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.quotes_channel_id = 1255226119221940265
        self.quotes_file_path = os.path.join('data', 'quotes.json')
        self.bank_file_path = os.path.join('data', 'bank_data.json')
        self.level_file_path = os.path.join('data', 'level_data.json')
        
        # Panggil helper function saat inisialisasi untuk memastikan file ada
        load_json_data(self.quotes_file_path, default_value=[])
        load_json_data(self.bank_file_path, default_value={})
        load_json_data(self.level_file_path, default_value={})

    @commands.command(name="sendquote", help="[Admin] Mengirim kutipan tanpa persetujuan.")
    @commands.has_permissions(administrator=True)
    async def sendquote(self, ctx, *, quote_text: str):
        """Mengirim kutipan yang sudah disetujui admin langsung ke channel quotes."""
        user_name = ctx.author.display_name
        
        self.save_quote_to_json(str(ctx.author.id), user_name, quote_text, is_approved=True)
        logging.info(f"Admin {user_name} ({ctx.author.id}) telah mengirim kutipan: {quote_text}")
        
        channel = self.bot.get_channel(self.quotes_channel_id)
        if channel:
            embed = discord.Embed(
                title="Quotes", 
                description=quote_text, 
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Quotes by {user_name}")
            await channel.send(embed=embed)
        
        await ctx.message.delete()
        await ctx.send("✅ Kutipan telah berhasil dikirim ke channel Quotes.", ephemeral=True)

    @commands.command(name="resq", help="Mengirim kutipan untuk persetujuan admin. Gunakan '!resq <yes/no> <quotes>'")
    async def resq(self, ctx, show_name: str, *, quote_text: str):
        """Mengirim kutipan untuk persetujuan admin sebelum dipublikasikan."""
        if ctx.guild.get_member(ctx.author.id).guild_permissions.administrator:
            return await self.sendquote(ctx, quote_text=f"{show_name} {quote_text}")

        user_id = str(ctx.author.id)
        user_name = ctx.author.display_name
        
        is_anonymous = show_name.lower() in ["no", "n", "false"]
        display_name = "Anonymous" if is_anonymous else user_name
        
        quotes_channel = self.bot.get_channel(self.quotes_channel_id)
        if not quotes_channel:
            return await ctx.send("❌ Channel quotes tidak ditemukan.", ephemeral=True)

        embed = discord.Embed(
            title="Quotes - Menunggu Persetujuan",
            description=quote_text,
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"Quotes by {display_name} | Menunggu persetujuan admin...")
        
        view = QuoteApprovalView(self, user_id, quote_text, is_anonymous)
        await quotes_channel.send(embed=embed, view=view)
        
        await ctx.send("✅ Kutipanmu telah dikirim untuk persetujuan admin.", ephemeral=True)
        await ctx.message.delete()

    @commands.command(name="deletequote", help="[Admin] Menghapus kutipan berdasarkan ID.")
    @commands.has_permissions(administrator=True)
    async def deletequote(self, ctx, quote_id: int):
        quotes = load_json_data(self.quotes_file_path, default_value=[])
        quote_to_delete = next((q for q in quotes if q.get('id') == quote_id), None)
        
        if quote_to_delete:
            quotes.remove(quote_to_delete)
            save_json_data(self.quotes_file_path, quotes)
            await ctx.send(f"✅ Kutipan dengan ID {quote_id} telah dihapus.", ephemeral=True)
            logging.info(f"Kutipan dengan ID {quote_id} telah dihapus oleh admin {ctx.author.display_name}.")
        else:
            await ctx.send("❌ ID kutipan tidak valid. Silakan coba lagi.", ephemeral=True)

    @commands.command(name="listquotes", help="[Admin] Menampilkan semua kutipan yang disetujui.")
    @commands.has_permissions(administrator=True)
    async def listquotes(self, ctx):
        quotes = load_json_data(self.quotes_file_path, default_value=[])
        approved_quotes = [q for q in quotes if q.get('is_approved', False)]
        
        if not approved_quotes:
            return await ctx.send("Tidak ada kutipan yang disetujui.", ephemeral=True)
        
        embed = discord.Embed(title="Daftar Kutipan yang Disetujui", color=discord.Color.blue())
        
        for quote in approved_quotes[-10:]:
            embed.add_field(name=f"ID: {quote.get('id', 'N/A')}", 
                            value=f"**{quote.get('text', 'N/A')}** - oleh **{quote.get('user', 'N/A')}**", 
                            inline=False)
        
        await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="resrandom", help="Mengirim kutipan acak yang disetujui.")
    async def resrandom(self, ctx):
        quotes = load_json_data(self.quotes_file_path, default_value=[])
        approved_quotes = [q for q in quotes if q.get('is_approved', False)]
        
        if not approved_quotes:
            return await ctx.send("Tidak ada kutipan yang tersedia untuk diacak.", ephemeral=True)

        random_quote = random.choice(approved_quotes)
        
        embed = discord.Embed(
            title="Quotes Acak",
            description=f"**{random_quote['text']}**",
            color=discord.Color.purple()
        )
        embed.set_footer(text=f"Quotes by {random_quote['user']}")
        await ctx.send(embed=embed)
        
    def save_quote_to_json(self, user_id, user_name, quote_text, is_approved):
        quotes = load_json_data(self.quotes_file_path, default_value=[])
        
        quote_id = int(datetime.now().timestamp() * 1000)
        
        quotes.append({
            "id": quote_id,
            "user": user_name,
            "text": quote_text,
            "user_id": user_id,
            "timestamp": str(datetime.now()),
            "is_approved": is_approved
        })
        save_json_data(self.quotes_file_path, quotes)
        
    async def approve_quote_action(self, interaction: discord.Interaction, user_id: str, quote_text: str, is_anonymous: bool):
        user_name = "Anonymous" if is_anonymous else interaction.user.display_name
        self.save_quote_to_json(user_id, user_name, quote_text, is_approved=True)

        await self.give_reward(interaction.guild.id, user_id, 100, 100)
        
        user = self.bot.get_user(int(user_id))
        if user:
            try:
                await user.send(f"✅ Kutipanmu: \"{quote_text}\" telah disetujui! Kamu mendapatkan 100 EXP dan 100 RSWN.")
            except discord.Forbidden:
                logging.warning(f"Tidak dapat mengirim DM ke pengguna {user.display_name} ({user_id}).")

    async def give_reward(self, server_id, user_id, exp, rswn):
        try:
            level_data = load_json_data(self.level_file_path, default_value={})
            server_data = level_data.setdefault(str(server_id), {})
            user_levels = server_data.setdefault(user_id, {'level': 1, 'exp': 0})
            
            user_levels['exp'] += exp
            while user_levels['exp'] >= 1000:
                user_levels['level'] += 1
                user_levels['exp'] -= 1000
                logging.info(f"User {user_id} di server {server_id} naik ke level {user_levels['level']}!")

            save_json_data(self.level_file_path, level_data)

            bank_data = load_json_data(self.bank_file_path, default_value={})
            user_bank = bank_data.setdefault(user_id, {'balance': 0, 'debt': 0})
            user_bank['balance'] += rswn
            
            save_json_data(self.bank_file_path, bank_data)

            logging.info(f"User {user_id} di server {server_id} diberi hadiah: {exp} EXP dan {rswn} RSWN.")
        except Exception as e:
            logging.error(f"Error memberikan hadiah kepada user {user_id} di server {server_id}: {e}", exc_info=True)

async def setup(bot):
    await bot.add_cog(Quotes(bot))
