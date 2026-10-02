import discord
from discord.ext import commands
from discord import ui, app_commands

# --- ID Channel yang Sudah Diperbarui ---
FAQ_CHANNEL_ID = 765140300145360896
ROLE_CHANNEL_ID = 1255221263811743836

# --- Kelas View untuk Tombol FAQ ---
class FAQView(ui.View):
    def __init__(self):
        super().__init__(timeout=180) # Timeout setelah 3 menit

    # --- Tombol untuk FAQ Umum ---
    @ui.button(label="FAQ Umum", style=discord.ButtonStyle.primary, emoji="❔")
    async def faq_umum_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="❔ FAQ Umum",
            description="Pertanyaan dan jawaban dasar seputar server ini.",
            color=discord.Color.from_rgb(123, 0, 255) # Ungu neon
        )
        embed.add_field(name="Apa itu Discord?", value="Discord adalah aplikasi komunikasi gratis yang dirancang untuk komunitas, gamer, dan grup. Di Discord, Anda dapat mengobrol melalui teks, suara, dan video, serta berbagi layar di dalam server.", inline=False)
        embed.add_field(name="Bagaimana cara bergabung ke server Njan Discord?", value="Anda dapat bergabung ke server Njan Discord dengan menggunakan tautan undangan yang valid. Setelah mengklik tautan tersebut, Anda akan otomatis diarahkan untuk bergabung ke server. Pastikan Anda sudah memiliki akun Discord.", inline=False)
        embed.add_field(name="Apa itu 'role' di Discord?", value="'Role' adalah peran atau status yang diberikan kepada anggota di sebuah server. Role ini memberikan warna khusus pada nama, dan juga dapat memberikan akses ke channel atau fitur tertentu di dalam server, seperti channel khusus anggota atau moderator.", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Tombol untuk Profil & Media Sosial ---
    @ui.button(label="Profil & Media Sosial", style=discord.ButtonStyle.success, emoji="👤")
    async def profil_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="👤 Tentang Rizwan Fadilah",
            description="Saya Rizwan Fadilah, dikenal sebagai Njan. Saya adalah seorang gamer, streamer, dan penyanyi dengan banyak konten seru di YouTube. Bergabunglah bersama saya dan komunitas ini untuk mabar, mendengarkan lagu, dan berbagai keseruan lainnya!",
            color=discord.Color.from_rgb(0, 255, 209) # Cyan
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

    # --- Tombol untuk Membership YouTube ---
    @ui.button(label="Membership YouTube", style=discord.ButtonStyle.secondary, emoji="▶️")
    async def membership_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="▶️ Membership YouTube",
            description="Informasi penting untuk mendapatkan role membership YouTube Anda.",
            color=discord.Color.from_rgb(255, 94, 94) # Merah menyala
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

    # --- Tombol untuk Peraturan Server ---
    @ui.button(label="Aturan Server", style=discord.ButtonStyle.danger, emoji="📜")
    async def rules_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="📜 Aturan Utama Server",
            description="Aturan ini dibuat untuk menjaga lingkungan yang nyaman dan positif bagi semua anggota. Berikut adalah ringkasan peraturan penting yang harus dipatuhi:",
            color=discord.Color.from_rgb(255, 69, 0) # Oranye terang
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
    
    # --- Tombol untuk ambil role ---
    @ui.button(label="Ambil Role", style=discord.ButtonStyle.success, emoji="✅")
    async def get_role_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"Silakan kunjungi channel <#{ROLE_CHANNEL_ID}> untuk mengambil role Anda!", ephemeral=True)

# --- Kelas Cog untuk Bot ---
class FAQBot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="faq", help="Menampilkan FAQ dengan tombol.")
    async def faq_command(self, ctx: commands.Context):
        # Menghapus pesan perintah dari user
        await ctx.message.delete()

        # Memeriksa apakah perintah digunakan di channel yang benar
        if ctx.channel.id != FAQ_CHANNEL_ID:
            # Menggunakan delete_after untuk menghapus pesan balasan bot
            await ctx.send("Perintah ini hanya bisa digunakan di channel FAQ.", ephemeral=True, delete_after=5)
            return

        embed = discord.Embed(
            title="📚 FAQ - Njan Discord",
            description="Halo! Silakan pilih salah satu tombol di bawah untuk melihat informasi yang Anda butuhkan.",
            color=discord.Color.blue()
        )
        # Menggunakan delete_after untuk menghapus pesan bot setelah 5 menit (300 detik)
        await ctx.send(embed=embed, view=FAQView(), delete_after=300)

# --- Fungsi setup untuk memuat cog ---
async def setup(bot: commands.Bot):
    await bot.add_cog(FAQBot(bot))
