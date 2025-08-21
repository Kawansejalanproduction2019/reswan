import discord
from discord.ext import commands
import json
import os
from datetime import datetime

class BotFeatures(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = 'gender_roles_config.json'
        self.config = self.load_config()

    def load_config(self):
        """Memuat ID role dan pesan kustom dari file JSON."""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {}

    def save_config(self):
        """Menyimpan ID role dan pesan kustom ke file JSON."""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=4)

    def has_gender_role(self, member, guild_id):
        """Memeriksa apakah user memiliki salah satu role gender yang terdaftar."""
        guild_settings = self.config.get(str(guild_id), {})
        male_id = guild_settings.get('male')
        female_id = guild_settings.get('female')

        if male_id and any(role.id == male_id for role in member.roles):
            return True
        if female_id and any(role.id == female_id for role in member.roles):
            return True
        
        return False

    def format_time(self, dt):
        """Memformat objek datetime menjadi string yang mudah dibaca."""
        return dt.strftime("%A, %d %B %Y pukul %H:%M WIB")

    def get_user_info_embed(self, user, member):
        """Membuat Discord.Embed untuk menampilkan info user."""
        embed = discord.Embed(
            title=f"Profil {user.display_name}",
            description=f"**Username:** {user.name}",
            color=discord.Color.blue()
        )

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"ID: {user.id}")

        embed.add_field(name="Waktu Pembuatan Akun", value=self.format_time(user.created_at), inline=False)
        
        if member:
            embed.add_field(name="Waktu Bergabung Server", value=self.format_time(member.joined_at), inline=False)
            
            roles = [role.mention for role in member.roles if role.name != '@everyone']
            if roles:
                embed.add_field(name="Roles", value=" ".join(roles), inline=False)
            else:
                embed.add_field(name="Roles", value="Tidak ada role.", inline=False)

        if user.banner:
            embed.set_image(url=user.banner.url)
        
        return embed

    # Command: !user
    @commands.command(name='user', help='Menampilkan info profil user.')
    async def user_info(self, ctx, user: commands.UserConverter = None):
        if not user:
            user = ctx.author

        member = ctx.guild.get_member(user.id)
        
        embed = self.get_user_info_embed(user, member)
        await ctx.send(embed=embed)

    # Command: !avatar
    @commands.command(name='avatar', help='Menampilkan avatar user.')
    async def avatar(self, ctx, user: commands.UserConverter = None):
        target = user or ctx.author
        embed = discord.Embed(
            title=f"Avatar dari {target.display_name}",
            color=discord.Color.random()
        )
        embed.set_image(url=target.display_avatar.url)
        embed.set_footer(text=f"Diminta oleh {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # Command: !set_gender (pengganti !setup)
    @commands.hybrid_command(name='set_gender', help='Menyiapkan pengaturan role gender via UI.')
    @commands.has_permissions(manage_guild=True)
    async def set_gender(self, ctx):
        embed = discord.Embed(
            title="⚙️ Pengaturan Role Gender",
            description="Klik tombol di bawah ini untuk membuka formulir pengaturan.",
            color=discord.Color.blue()
        )
        view = discord.ui.View()
        view.add_item(SetGenderButton(self.bot, self))
        await ctx.send(embed=embed, view=view, ephemeral=True)

    @set_gender.error
    async def set_gender_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Maaf, kamu tidak punya izin `Manage Server` untuk menggunakan perintah ini.", ephemeral=True)
        else:
            print(f'Error: {error}')

    # Event Listener: on_message
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        guild_id = str(message.guild.id)
        
        if guild_id not in self.config:
            return
        
        prefix = self.bot.command_prefix
        if message.content.startswith(prefix):
            return

        member = message.author
        if not self.has_gender_role(member, guild_id):
            guild_settings = self.config.get(guild_id, {})
            custom_message = guild_settings.get('custom_message')
            
            if custom_message:
                description = custom_message.replace('{user}', member.mention)
            else:
                description = (
                    f"Halo {member.mention}, sepertinya kamu belum memilih role gender.\n\n"
                    f"Mohon ambil salah satu role yang tersedia, seperti **Male** atau **Female**, "
                    f"untuk bisa berinteraksi di server ini."
                )

            embed = discord.Embed(
                title="⚠️ Peringatan Role Gender!",
                description=description,
                color=discord.Color.gold()
            )
            embed.set_footer(text="Pengingat ini akan terus muncul sampai kamu mengambil role.")
            
            await message.channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BotFeatures(bot))

# Class untuk Modal (Formulir)
class SetGenderModal(discord.ui.Modal, title='Pengaturan Role Gender'):
    def __init__(self, cog, bot):
        super().__init__()
        self.cog = cog
        self.bot = bot
        
    male_role_id = discord.ui.TextInput(
        label='ID Role Male',
        placeholder='Masukkan ID role Male...',
        required=True
    )
    
    female_role_id = discord.ui.TextInput(
        label='ID Role Female',
        placeholder='Masukkan ID role Female...',
        required=True
    )
    
    custom_message = discord.ui.TextInput(
        label='Pesan Kustom (Opsional)',
        placeholder='Contoh: Halo {user}, silakan pilih role gender.',
        style=discord.TextStyle.paragraph,
        required=False
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            male_id = int(self.male_role_id.value)
            female_id = int(self.female_role_id.value)
            
            guild = interaction.guild
            male_role = guild.get_role(male_id)
            female_role = guild.get_role(female_id)
            
            if not male_role or not female_role:
                await interaction.response.send_message("ID role tidak ditemukan. Pastikan ID-nya benar.", ephemeral=True)
                return

            guild_id = str(guild.id)
            
            if guild_id not in self.cog.config:
                self.cog.config[guild_id] = {}
            
            self.cog.config[guild_id]['male'] = male_role.id
            self.cog.config[guild_id]['female'] = female_role.id
            self.cog.config[guild_id]['custom_message'] = self.custom_message.value or None
            
            self.cog.save_config()

            embed = discord.Embed(
                title="✅ Pengaturan Selesai!",
                description="Pengaturan role gender untuk server ini berhasil disimpan.",
                color=discord.Color.green()
            )
            embed.add_field(name="Role Male", value=f"`{male_role.name}` (ID: {male_role.id})", inline=False)
            embed.add_field(name="Role Female", value=f"`{female_role.name}` (ID: {female_role.id})", inline=False)
            if self.custom_message.value:
                embed.add_field(name="Pesan Kustom", value=self.custom_message.value, inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except ValueError:
            await interaction.response.send_message("ID role harus berupa angka.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Terjadi kesalahan: {e}", ephemeral=True)

# Class untuk Tombol
class SetGenderButton(discord.ui.Button):
    def __init__(self, bot, cog):
        super().__init__(label="Buka Formulir Pengaturan", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.bot = bot
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SetGenderModal(self.cog, self.bot))
