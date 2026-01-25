import discord
from discord.ext import commands
from discord import ui, app_commands
from PIL import Image, ImageDraw, ImageFont
import requests
import io
import os
import json
from datetime import datetime

# URL Aset dan Pengaturan Global
FONT_URL = "https://github.com/MFarelS/RajinNulis-BOT/raw/master/font/Zahraaa.ttf"
IMAGE_URL = "https://github.com/MFarelS/RajinNulis-BOT/raw/master/MFarelSZ/Farelll/magernulis1.jpg"
UKURAN_FONT_NAMA = 22
UKURAN_FONT_TEKS = 18

# ID Channel
FAQ_CHANNEL_ID = 765140300145360896
ROLE_CHANNEL_ID = 1255221263811743836

# Fungsi Bantuan Global
def download_asset(url, is_font=False):
    try:
        response = requests.get(url)
        response.raise_for_status()
        if is_font:
            return response.content
        else:
            return io.BytesIO(response.content)
    except requests.exceptions.RequestException as e:
        print(f"Error saat mengunduh aset: {e}")
        return None

def wrap_text(draw, text, font, max_width):
    lines = []
    if not text:
        return lines
    
    words = text.split(' ')
    current_line = ""
    for word in words:
        if draw.textlength(current_line + " " + word, font=font) < max_width:
            if current_line == "":
                current_line = word
            else:
                current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines

# Kelas untuk UI (Views, Buttons, Modals)
class FAQView(ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @ui.button(label="FAQ Umum", style=discord.ButtonStyle.primary, emoji="❔")
    async def faq_umum_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="❔ FAQ Umum",
            description="Pertanyaan dan jawaban dasar seputar server ini.",
            color=discord.Color.from_rgb(123, 0, 255)
        )
        embed.add_field(name="Apa itu Discord?", value="Discord adalah aplikasi komunikasi gratis yang dirancang untuk komunitas, gamer, dan grup. Di Discord, Anda dapat mengobrol melalui teks, suara, dan video, serta berbagi layar di dalam server.", inline=False)
        embed.add_field(name="Bagaimana cara bergabung ke server Njan Discord?", value="Anda dapat bergabung ke server Njan Discord dengan menggunakan tautan undangan yang valid. Setelah mengklik tautan tersebut, Anda akan otomatis diarahkan untuk bergabung ke server. Pastikan Anda sudah memiliki akun Discord.", inline=False)
        embed.add_field(name="Apa itu 'role' di Discord?", value="'Role' adalah peran atau status yang diberikan kepada anggota di sebuah server. Role ini memberikan warna khusus pada nama, dan juga dapat memberikan akses ke channel atau fitur tertentu di dalam server, seperti channel khusus anggota atau moderator.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Profil & Media Sosial", style=discord.ButtonStyle.success, emoji="👤")
    async def profil_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="👤 Tentang Rizwan Fadilah",
            description="Saya Rizwan Fadilah, dikenal sebagai Njan. Saya adalah seorang gamer, streamer, dan penyanyi dengan banyak konten seru di YouTube. Bergabunglah bersama saya dan komunitas ini untuk mabar, mendengarkan lagu, dan berbagai keseruan lainnya!",
            color=discord.Color.from_rgb(0, 255, 209)
        )
        embed.add_field(name="Link Resmi", value="""
• [Youtube Game](https://youtube.com/@njanlive)
• [Youtube Music](https://music.youtube.com/channel/UCJGkN_PN8fnFirhbPCCOnvg?si=hVbVq8RnWJe298Mv)
• [Spotify](https://open.spotify.com/artist/6usptTdSkyzOX8rWIE4Y12?si=OFvTWh2MS1SCI9BfFVm-wA)
• [Apple Music](https://music.apple.com/id/artist/rizwan-fadilah/1644827546)
• [TikTok](https://tiktok.com/@rizwanfadilah.a.s)
• [Instagram](https://instagram.com/rizwanfadilah.a.s)
• [Youtube Utama](https://www.youtube.com/@RizwanFadilah)
""", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Membership YouTube", style=discord.ButtonStyle.secondary, emoji="▶️")
    async def membership_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="▶️ Membership YouTube",
            description="Informasi penting untuk mendapatkan role membership YouTube Anda.",
            color=discord.Color.from_rgb(255, 94, 94)
        )
        embed.add_field(name="Cara menjadi anggota (member) di YouTube Njan?", value="Untuk menjadi anggota resmi channel YouTube Njan dan mendukungnya, Anda bisa bergabung melalui tautan resmi berikut ini: [Bergabung Menjadi Anggota YouTube](https://www.youtube.com/channel/UCW2TTb26sRBrU7jlKpjCHVA/join)", inline=False)
        embed.add_field(name="Cara menautkan akun YouTube dengan Discord?", value="""
1. Buka **User Settings** (tombol gerigi di kiri bawah layar Discord Anda).
2. Masuk ke tab **Connections**.
3. Klik ikon **YouTube**.
4. Ikuti petunjuk untuk login ke akun Google/YouTube Anda. Pastikan Anda login dengan akun yang memiliki membership.
5. Setelah berhasil, akun YouTube Anda akan terhubung. Secara otomatis, Discord akan memberikan role khusus bagi anggota (member) YouTube Anda.
""", inline=False)
        embed.add_field(name="Saya sudah menautkan akun, tapi role tidak muncul. Apa yang harus saya lakukan?", value="""
Ada beberapa alasan mengapa role membership mungkin tidak langsung muncul:
1. **Sinkronisasi**: Terkadang ada jeda waktu (hingga 1 jam) untuk proses sinkronisasi. Tunggu sebentar dan cek kembali.
2. **Periksa Role**: Pastikan Anda sudah menjadi anggota (*member*) dari channel YouTube yang sesuai.
3. **Hubungkan Kembali**: Coba putuskan koneksi YouTube Anda dari Discord, lalu hubungkan kembali untuk menyegarkan data.
""", inline=False)
        embed.add_field(name="Bagaimana cara mengatasi jika koneksi YouTube gagal?", value="Jika Anda mengalami masalah saat menautkan atau sinkronisasi akun YouTube, Anda bisa mencoba beberapa solusi. Untuk panduan yang lebih detail, silakan tonton video tutorial berikut ini: [Tutorial Mengatasi Gagal Sinkronisasi YouTube ke Discord](https://youtu.be/p6XtY6qXDpk)", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Aturan Server", style=discord.ButtonStyle.danger, emoji="📜")
    async def rules_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="📜 Aturan Utama Server",
            description="Aturan ini dibuat untuk menjaga lingkungan yang nyaman dan positif bagi semua anggota. Berikut adalah ringkasan peraturan penting yang harus dipatuhi:",
            color=discord.Color.from_rgb(255, 69, 0)
        )
        embed.add_field(name="Peraturan Server", value="""
• **Peraturan Utama:** Jaga sikap dan bahasa. Hindari pelecehan, rasisme, atau serangan pribadi. Jangan membuat drama dan bersikap "toxic" yang tidak perlu.
• **Gunakan Channel Sesuai Topik:** Setiap channel memiliki fungsinya masing-masing. Pastikan Anda mengirim pesan atau bergabung di channel yang sesuai.
• **Konten yang Sesuai:** Dilarang keras memposting konten dewasa (NSFW), gore, phishing, atau spam.
• **Bergabung Voice Chat:** Voice chat adalah tempat untuk berinteraksi dan bersenang-senang. Jangan ragu untuk bergabung dan ciptakan suasana yang akrab.
• **Hindari Ping Massal:** Jangan melakukan ping `@everyone` atau `@here` tanpa alasan yang benar-benar penting.
• **Kerja Sama dengan Staf:** Staf siap membantu. Silakan berkoordinasi dengan mereka jika ada kendala.
• **Cara Melaporkan:** Jika Anda menemukan pelanggaran, laporkan ke tim moderasi (Moderator atau Admin) dengan bukti yang jelas.
""", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @ui.button(label="Ambil Role", style=discord.ButtonStyle.success, emoji="✅")
    async def get_role_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"Silakan kunjungi channel <#{ROLE_CHANNEL_ID}> untuk mengambil role Anda!", ephemeral=True)

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

class SetGenderButton(discord.ui.Button):
    def __init__(self, bot, cog):
        super().__init__(label="Buka Formulir Pengaturan", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.bot = bot
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SetGenderModal(self.cog, self.bot))

# --- Main Cog ---
class Addon(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = 'gender_roles_config.json'
        self.config = self.load_config()

    # Metode untuk Fitur Tulis
    def buat_tulisan_tangan(self, teks, nama):
        try:
            gambar_data = download_asset(IMAGE_URL)
            if not gambar_data:
                return None
            gambar_latar = Image.open(gambar_data)
            
            font_data = download_asset(FONT_URL, is_font=True)
            if not font_data:
                return None
                
            temp_font_path = "temp_font.ttf"
            with open(temp_font_path, "wb") as f:
                f.write(font_data)

            font_tulisan = ImageFont.truetype(temp_font_path, UKURAN_FONT_TEKS)
            font_nama = ImageFont.truetype(temp_font_path, UKURAN_FONT_NAMA)
        except Exception as e:
            print(f"Error dalam memuat aset: {e}")
            return None
        
        start_x = 345
        start_y = 130
        line_spacing = 22
        max_width = 500
        nama_x = 500
        nama_y = 70
        
        draw = ImageDraw.Draw(gambar_latar)
        draw.text((nama_x, nama_y), nama, font=font_nama, fill=(0, 0, 0))
        
        x_pos, y_pos = start_x, start_y
        paragraphs = teks.split('\n')
        
        for paragraph in paragraphs:
            lines_to_draw = wrap_text(draw, paragraph, font_tulisan, max_width)
            for line in lines_to_draw:
                draw.text((x_pos, y_pos), line, font=font_tulisan, fill=(0, 0, 0))
                y_pos += line_spacing
            y_pos += line_spacing * 0.5
        
        nama_file_hasil = "tulisan_tangan_hasil.png"
        gambar_latar.save(nama_file_hasil)

        if os.path.exists(temp_font_path):
            os.remove(temp_font_path)

        return nama_file_hasil

    # Metode untuk Fitur Gender dan Info
    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {}

    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=4)

    def has_gender_role(self, member, guild_id):
        guild_settings = self.config.get(str(guild_id), {})
        male_id = guild_settings.get('male')
        female_id = guild_settings.get('female')

        if male_id and any(role.id == male_id for role in member.roles):
            return True
        if female_id and any(role.id == female_id for role in member.roles):
            return True
        
        return False

    def format_time(self, dt):
        return dt.strftime("%A, %d %B %Y pukul %H:%M WIB")

    def get_user_info_embed(self, user, member):
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

    # Event Listener
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        guild_id = str(message.guild.id)
        if guild_id not in self.config:
            return
        
        try:
            prefix = self.bot.command_prefix
            if isinstance(prefix, str) and message.content.startswith(prefix):
                 return
            elif callable(prefix):
                 prefixes = await prefix(self.bot, message)
                 if any(message.content.startswith(p) for p in prefixes):
                      return
        except Exception:
             # Fallback or logging if prefix check fails
             pass

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

    # Commands
    @commands.command(name='tulis', help='Mengubah teks menjadi gambar tulisan tangan.')
    async def tulis_tangan(self, ctx, nama: str, *, teks: str):
        if not nama or not teks:
            await ctx.send("Mohon berikan nama dan teks yang ingin Anda ubah menjadi tulisan tangan.\nContoh: `!tulis Rhdevs Ini adalah teks`")
            return

        await ctx.send("Sedang menulis... Mohon tunggu sebentar.")
        
        nama_file_hasil = self.buat_tulisan_tangan(teks, nama)

        if nama_file_hasil:
            try:
                await ctx.send(file=discord.File(nama_file_hasil))
            finally:
                if os.path.exists(nama_file_hasil):
                    os.remove(nama_file_hasil)
        else:
            await ctx.send("Terjadi kesalahan saat membuat gambar. Coba lagi nanti.")

    @commands.command(name="faq", help="Menampilkan FAQ dengan tombol.")
    async def faq_command(self, ctx: commands.Context):
        await ctx.message.delete()
        if ctx.channel.id != FAQ_CHANNEL_ID:
            await ctx.send("Perintah ini hanya bisa digunakan di channel FAQ.", ephemeral=True, delete_after=5)
            return

        embed = discord.Embed(
            title="📚 FAQ - Njan Discord",
            description="Halo! Silakan pilih salah satu tombol di bawah untuk melihat informasi yang Anda butuhkan.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, view=FAQView(), delete_after=300)

    @commands.command(name='user', help='Menampilkan info profil user.')
    async def user_info(self, ctx, user: commands.UserConverter = None):
        if not user:
            user = ctx.author

        member = ctx.guild.get_member(user.id)
        embed = self.get_user_info_embed(user, member)
        await ctx.send(embed=embed)

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

# Fungsi setup untuk memuat cog
async def setup(bot):
    await bot.add_cog(Addon(bot))
