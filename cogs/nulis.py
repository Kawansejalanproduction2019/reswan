import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
import requests
import io
import os
from pilmoji import Pilmoji # Tambahkan ini

# URL aset dari repositori GitHub
FONT_URL = "https://github.com/MFarelS/RajinNulis-BOT/raw/master/font/Zahraaa.ttf"
IMAGE_URL = "https://github.com/MFarelS/RajinNulis-BOT/raw/master/MFarelSZ/Farelll/magernulis1.jpg"

# Pengaturan yang bisa diubah di dalam kode
UKURAN_FONT_NAMA = 22
UKURAN_FONT_TEKS = 18

def download_asset(url, is_font=False):
    """Mengunduh file dari URL dan mengembalikan objek file-like (bytes)."""
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
    """Memecah teks menjadi baris-baris yang sesuai dengan lebar maksimum."""
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

def buat_tulisan_tangan(teks, nama):
    """
    Mengubah teks menjadi gambar tulisan tangan dengan mengunduh aset.
    """
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
    
    # Gunakan Pilmoji untuk menggambar teks
    with Pilmoji(gambar_latar) as pilmoji:
        # Tambahkan nama pengguna di bagian atas
        pilmoji.text((nama_x, nama_y), nama, font=font_nama, fill=(0, 0, 0))
    
        x_pos, y_pos = start_x, start_y
        paragraphs = teks.split('\n')
        
        for paragraph in paragraphs:
            lines_to_draw = wrap_text(ImageDraw.Draw(gambar_latar), paragraph, font_tulisan, max_width)
            for line in lines_to_draw:
                pilmoji.text((x_pos, y_pos), line, font=font_tulisan, fill=(0, 0, 0))
                y_pos += line_spacing
            y_pos += line_spacing * 0.5
    
    nama_file_hasil = "tulisan_tangan_hasil.png"
    gambar_latar.save(nama_file_hasil)

    if os.path.exists(temp_font_path):
        os.remove(temp_font_path)

    return nama_file_hasil

# --- Class Cog ---
class TulisanCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='tulis', help='Mengubah teks menjadi gambar tulisan tangan.')
    async def tulis_tangan(self, ctx, nama: str, *, teks: str):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            await ctx.send("Saya tidak memiliki izin untuk menghapus pesan. Mohon berikan saya izin 'Manage Messages'.")
        
        if not nama or not teks:
            await ctx.send("Mohon berikan nama dan teks yang ingin Anda ubah menjadi tulisan tangan. Contoh: `!tulis Rhdevs Ini adalah teks`")
            return

        await ctx.send("Sedang menulis... Mohon tunggu sebentar.")
        
        nama_file_hasil = buat_tulisan_tangan(teks, nama)

        if nama_file_hasil:
            try:
                await ctx.send(file=discord.File(nama_file_hasil))
            finally:
                if os.path.exists(nama_file_hasil):
                    os.remove(nama_file_hasil)
        else:
            await ctx.send("Terjadi kesalahan saat membuat gambar. Coba lagi nanti.")

# Fungsi setup untuk memuat cogs
async def setup(bot):
    await bot.add_cog(TulisanCog(bot))
