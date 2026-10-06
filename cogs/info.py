import discord
from discord.ext import commands
from discord import ui, app_commands
from PIL import Image, ImageDraw, ImageFont
import aiohttp
import asyncio
import uuid
import time
import io
import os
import json
from datetime import datetime

FONT_URL = "https://github.com/MFarelS/RajinNulis-BOT/raw/master/font/Zahraaa.ttf"
IMAGE_URL = "https://github.com/MFarelS/RajinNulis-BOT/raw/master/MFarelSZ/Farelll/magernulis1.jpg"
UKURAN_FONT_NAMA = 22
UKURAN_FONT_TEKS = 18

FAQ_CHANNEL_ID = int(os.getenv("FAQ_CHANNEL_ID", 765140300145360896))
ROLE_CHANNEL_ID = int(os.getenv("ROLE_CHANNEL_ID", 1255221263811743836))

async def download_asset(url, session, is_font=False):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status == 200:
                content = await response.read()
                if is_font:
                    return content
                else:
                    return io.BytesIO(content)
            print(f"Gagal mengunduh aset dari {url}: status {response.status}")
            return None
    except Exception as e:
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
        channel_mention = f"<#{ROLE_CHANNEL_ID}>" if (ROLE_CHANNEL_ID and interaction.guild and interaction.guild.get_channel(ROLE_CHANNEL_ID)) else "channel role server"
        await interaction.response.send_message(f"Silakan kunjungi {channel_mention} untuk mengambil role Anda!", ephemeral=True)

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
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 Kamu tidak memiliki izin `Manage Server`.", ephemeral=True)
            return
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
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 Kamu tidak memiliki izin `Manage Server` untuk mengatur role gender.", ephemeral=True)
            return
        await interaction.response.send_modal(SetGenderModal(self.cog, self.bot))

HELP_CATEGORIES = {
    "overview": {
        "title": "🚀 RTM-Bot • PANDUAN PUSAT BANTUAN",
        "desc": "Selamat datang di pusat panduan **RTM-Bot**! Bot ini dilengkapi 13 modul sistem untuk mengelola administrasi, hiburan, dan komunitas Anda.\n\n"
                "📌 **Format Penggunaan:**\n"
                "• Mendukung **Slash Command** (`/`) dengan autokomplet di Mobile & PC.\n"
                "• Mendukung **Prefix Command** (`!`) untuk perintah klasik.\n\n"
                "👉 **Pilih kategori di menu Dropdown di bawah** untuk melihat daftar perintah terperinci.",
        "color": 0x3498DB,
        "fields": [
            {"name": "🛡️ Moderasi & Sentinel", "value": "Proteksi bot raid, timeout otomatis, honeypot, dan anti-phising AI."},
            {"name": "💼 Asisten Keuangan Pribadi", "value": "Manajer arus kas (Cash In/Out), target anggaran belanja, dan evaluasi finansial."},
            {"name": "📡 Radar & Notifikasi Media", "value": "Deteksi dan notifikasi otomatis konten YouTube, TikTok, dan Instagram secara real-time."},
            {"name": "🎮 Party Games & Minigames", "value": "Balapan kuda taruhan, game Werewolf, tebak emoji, dan kuis asah otak."},
            {"name": "⭐ Leveling & Ekonomi RSWN", "value": "Perolehan EXP chat/voice, kartu profil rank Pillow, dan toko server."},
            {"name": "🤖 Asisten AI & Hiburan", "value": "Chatbot persona Raka tongkrongan, kartu tarot, zodiak, dan curhat anonim."},
            {"name": "🎙️ Voice Dinamis & Utilitas", "value": "Join-to-Create Temporary Voice Channel dan utilitas profil member."}
        ]
    },
    "moderation": {
        "title": "🛡️ MODERASI & SENTINEL DEFENSE",
        "desc": "Sistem penegakan disiplin dan pertahanan otomatis server:",
        "color": 0xE74C3C,
        "fields": [
            {"name": "🔨 /ban <member> [alasan]", "value": "Blokir member permanen dari server dengan proteksi hierarki role."},
            {"name": "🔓 /unban <user_id> [alasan]", "value": "Buka kembali blokir pengguna berdasarkan ID akun Discord."},
            {"name": "👢 /kick <member> [alasan]", "value": "Keluarkan member dari server secara aman."},
            {"name": "🧹 /softban <member> [alasan]", "value": "Ban dan unban instan untuk membersihkan seluruh pesan 7 hari terakhir."},
            {"name": "⏳ /timeout <member> <durasi> [alasan]", "value": "Bungkam member sementara (contoh: 10m, 1h, 1d)."},
            {"name": "🔊 /untimeout <member>", "value": "Cabut status bungkam (timeout) member seketika."},
            {"name": "⚠️ /warn <member> [alasan]", "value": "Catat surat peringatan resmi untuk member."},
            {"name": "📋 /warnings <member>", "value": "Lihat daftar dan riwayat catatan peringatan resmi member."},
            {"name": "🗑️ /clear <jumlah>", "value": "Hapus pesan massal di channel (hingga 100 pesan sekaligus)."},
            {"name": "🔒 /lock & /unlock", "value": "Kunci atau buka kembali izin berbicara channel dari member biasa."},
            {"name": "⏱️ /slowmode <detik>", "value": "Atur batas waktu jeda cooldown kirim pesan di channel (0 untuk matikan)."},
            {"name": "🍯 /trap", "value": "Atur channel jebakan (Honey-Pot) untuk auto-timeout 28 hari spammer/phishing."},
            {"name": "📜 /set_log_channel <channel>", "value": "Atur channel khusus untuk pencatatan log sistem keamanan & moderasi."},
            {"name": "🚨 /report", "value": "Kirimkan laporan pelanggaran rahasia kepada tim moderator server via form modal."},
            {"name": "🤖 /cyber_toggle", "value": "Aktifkan atau matikan proteksi anti-phising, anti-scam, dan filter AI."}
        ]
    },
    "finance": {
        "title": "💼 ASISTEN KEUANGAN & MANAJER CASHFLOW",
        "desc": "Manajer keuangan profesional untuk mengelola arus kas pribadi, target anggaran, dan konsultasi finansial:",
        "color": 0x2ECC71,
        "fields": [
            {"name": "➕ /cash_in <nominal> [kategori] [catatan]", "value": "Catat pemasukan kas (Gaji, Bisnis, Freelance, Dividen, dll.) (alias `!in`, `!masuk`)."},
            {"name": "➖ /cash_out <nominal> [kategori] [catatan]", "value": "Catat pengeluaran kas harian dengan proteksi batas anggaran (alias `!out`, `!keluar`)."},
            {"name": "📊 /keuangan", "value": "Buka dasbor finansial lengkap, saldo kas bersih, rasio tabungan, dan tombol interaktif (alias `!saldo`, `!wallet`)."},
            {"name": "📈 /cashflow", "value": "Laporan arus kas bulanan, komposisi persentase belanja, dan 10 mutasi terakhir (alias `!mutasi`)."},
            {"name": "🎯 /anggaran <nominal>", "value": "Tetapkan pagu batas belanja bulanan dengan peringatan overbudget (alias `!budget`)."},
            {"name": "💡 /konsultasi_keuangan", "value": "Evaluasi kesehatan finansial menggunakan kaidah perencana keuangan profesional 50/30/20 (alias `!evaluasi_keuangan`)."},
            {"name": "📥 /export_keuangan", "value": "Unduh seluruh riwayat transaksi keuangan pribadi ke format file CSV spreadsheet (alias `!exportfin`)."},
            {"name": "🗑️ /reset_keuangan", "value": "Hapus dan bersihkan seluruh catatan keuangan pribadi Anda dengan konfirmasi aman (alias `!resetfin`)."}
        ]
    },
    "notif": {
        "title": "📡 RADAR & NOTIFIKASI MEDIA SOSIAL",
        "desc": "Sistem deteksi dan notifikasi konten otomatis lintas platform (YouTube, TikTok, Instagram):",
        "color": 0xE67E22,
        "fields": [
            {"name": "🚀 Deteksi Otomatis", "value": "Mendeteksi link YouTube (Live, Video, Shorts), TikTok (Video, Live), dan Instagram (Reel/Post) di channel sumber dan memformatnya jadi kartu notifikasi."},
            {"name": "➕ !addpath <source_channel_id> <target_channel_id>", "value": "Hubungkan channel sumber link dengan channel tujuan notifikasi *(Admin/Owner)*."},
            {"name": "➖ !removepath <path_id>", "value": "Hapus konfigurasi jalur notifikasi berdasarkan ID *(Admin/Owner)*."},
            {"name": "⚙️ !config", "value": "Buka panel kustomisasi interaktif: atur format pesan, custom role ping, tombol tonton, dan embed *(Admin/Owner)*."},
            {"name": "📦 !checkcache", "value": "Periksa daftar video atau konten terbaru yang tersimpan dalam antrean cache notifikasi."},
            {"name": "🧹 !resetcache", "value": "Bersihkan memori cache video untuk keperluan pengujian kirim ulang *(Admin/Owner)*."}
        ]
    },
    "games": {
        "title": "🎮 TAVERN PARTY & MINIGAMES",
        "desc": "Game interaktif multipemain dan kuis asah otak komunitas:",
        "color": 0xF1C40F,
        "fields": [
            {"name": "🏇 !balapan (alias !race)", "value": "Mulai arena taruhan balap kuda multiplayer berhadiah koin RSWN."},
            {"name": "🪙 !taruhan <jumlah> <nomor_kuda>", "value": "Pasang taruhan pada kuda jagoanmu sebelum balapan dimulai."},
            {"name": "🐺 /ww (alias !ww)", "value": "Mulai sesi game Werewolf klasik bersama warga server."},
            {"name": "🧩 !resmoji", "value": "Tebak judul film atau lagu berdasarkan petunjuk deretan emoji."},
            {"name": "🔤 !resacak", "value": "Susun kembali kata yang diacak hurufnya (Anagram)."},
            {"name": "🔬 !resipa", "value": "Kuis tebak fakta sains dan pengetahuan umum berhadiah EXP."},
            {"name": "🔗 !ressambung", "value": "Tantangan sambung suku kata berantai antar-pemain."},
            {"name": "✍️ !jawab <jawaban>", "value": "Kirimkan jawaban kuis yang sedang berlangsung."}
        ]
    },
    "leveling": {
        "title": "⭐ LEVELING, RANK & PROGRESSION",
        "desc": "Sistem pengalaman (EXP), Voice Tracking, papan aktivitas, dan pasar komunitas:",
        "color": 0x9B59B6,
        "fields": [
            {"name": "🎖️ /rank [member]", "value": "Lihat kartu profil grafis HD lengkap dengan progress bar, level, dan saldo RSWN."},
            {"name": "🏆 /leaderboard (alias /top)", "value": "Tampilkan 10 member dengan perolehan level tertinggi di server."},
            {"name": "📅 /weekly", "value": "Papan peringkat perolehan EXP mingguan server."},
            {"name": "🎙️ /voicepanel", "value": "Pasang papan live aktivitas voice, rekor room terlama, dan peringkat voice yang selalu di paling bawah channel *(Admin)*."},
            {"name": "❌ /voicepanel_remove", "value": "Hapus dan nonaktifkan papan aktivitas voice di server *(Admin)*."},
            {"name": "⏱️ /voicetime [member]", "value": "Cek total waktu aktif di voice channel server all-time, mingguan, & peringkat server."},
            {"name": "🏆 /voicerecord", "value": "Cek rekor durasi sesi voice channel terlama server dan channel pemegang rekor."},
            {"name": "⚙️ /setchannelrecord <channel> <jam> [menit] [detik] [sedang_aktif]", "value": "Atur atau adopsi rekor voice room terlama server agar bot melanjutkan hitungan *(Admin/Owner)*."},
            {"name": "➕ /addvoicetime <jam> [menit] [detik] [member] [weekly]", "value": "Tambahkan durasi voice untuk diri sendiri atau member target *(Admin/Owner)*."},
            {"name": "✏️ /setvoicetime <jam> [menit] [detik] [member] [weekly]", "value": "Atur ulang total durasi voice diri sendiri atau member target *(Admin/Owner)*."},
            {"name": "🛒 /shop", "value": "Buka katalog toko interaktif untuk membeli item dan badge profil."},
            {"name": "📜 /daily_quest", "value": "Periksa quest harian dan klaim hadiah EXP serta koin RSWN."},
            {"name": "💸 /transfercoins <member> <jumlah>", "value": "Kirimkan saldo koin RSWN milikmu ke pengguna lain."},
            {"name": "🏦 /bank (alias /balance)", "value": "Periksa saldo rekening bank RSWN dan status utang/kredit."},
            {"name": "💼 !work, !daily, !crime, !rob", "value": "Perintah ekonomi kasual untuk mengumpulkan koin RSWN tambahan."}
        ]
    },
    "ai": {
        "title": "🤖 ASISTEN AI RAKA & HIBURAN",
        "desc": "Kecerdasan buatan Gemini persona Raka dan fitur interaksi kasual:",
        "color": 0x1ABC9C,
        "fields": [
            {"name": "💬 @Mention / Reply Bot", "value": "Ajak Raka ngobrol santai dengan persona khas anak tongkrongan."},
            {"name": "🔮 /tarot", "value": "Tarik 3 kartu Tarot (Masa Lalu, Sekarang, Depan) dengan tafsiran filosofis."},
            {"name": "♈ /zodiak <nama/tanggal>", "value": "Ramalan peruntungan zodiak hari ini ala Raka."},
            {"name": "💘 /ship <user1> [user2]", "value": "Kalkulator kecocokan persentase cinta dua pengguna."},
            {"name": "🔥 /roast [user]", "value": "Minta Raka meroast seseorang dengan sindiran pedas tapi kocak."},
            {"name": "🤫 /confess", "value": "Buka formulir modal rahasia untuk mengirim curhatan anonim."}
        ]
    },
    "utility": {
        "title": "🎙️ DYNAMIC VOICE & UTILITAS SERVER",
        "desc": "Saluran suara otomatis dan fitur pendukung server:",
        "color": 0x34495E,
        "fields": [
            {"name": "🔊 Join-to-Create Voice", "value": "Masuk ke channel suara trigger untuk membuat room private otomatis."},
            {"name": "🎛️ VC Control Panel", "value": "Panel tombol lengkap: Gembok, Mode Siluman, Tambah Kursi, Ganti Nama."},
            {"name": "📝 /tulis <nama> <teks>", "value": "Renders teks menjadi gambar lembaran tulisan tangan di buku bergaris."},
            {"name": "👤 /user [user]", "value": "Lihat kartu informasi lengkap akun, tanggal gabung, dan peran member."},
            {"name": "🖼️ /avatar [user]", "value": "Ambil gambar avatar profil pengguna dalam resolusi tinggi."},
            {"name": "❓ /faq", "value": "Buka menu FAQ interaktif seputar server dan aturan komunitas."},
            {"name": "💬 /quote <teks>", "value": "Kirim kutipan bijak untuk dikurasi admin dan raih reward EXP."},
            {"name": "⚙️ /set_gender", "value": "Buka formulir modal untuk pengaturan role gender otomatis *(Admin)*."}
        ]
    }
}

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="📂 Pilih kategori perintah di sini...",
        custom_id="rtmbot:help_category_select",
        row=0,
        options=[
            discord.SelectOption(label="Beranda Panduan", value="overview", description="Ringkasan umum sistem RTM-Bot", emoji="🏠"),
            discord.SelectOption(label="Moderasi & Keamanan", value="moderation", description="Perintah ban, kick, timeout, filter AI", emoji="🛡️"),
            discord.SelectOption(label="Keuangan Pribadi", value="finance", description="Manajer arus kas, cash in/out, budgeting", emoji="💼"),
            discord.SelectOption(label="Radar & Notifikasi Media", value="notif", description="Deteksi & notifikasi YouTube, TikTok, Instagram", emoji="📡"),
            discord.SelectOption(label="Games & Minigames", value="games", description="Balapan kuda taruhan, Werewolf, kuis", emoji="🎮"),
            discord.SelectOption(label="Leveling & Ekonomi", value="leveling", description="Kartu rank, leaderboard, toko item", emoji="⭐"),
            discord.SelectOption(label="AI Raka & Hiburan", value="ai", description="Chat persona Raka, tarot, zodiak, confess", emoji="🤖"),
            discord.SelectOption(label="Voice & Utilitas", value="utility", description="Temp Voice channel, tulis tangan, profil", emoji="🎙️")
        ]
    )
    async def select_category(self, interaction: discord.Interaction, select: discord.ui.Select):
        selected_key = select.values[0]

        if selected_key == "notif":
            owner_id_env = os.getenv("BOT_OWNER_ID", "1000737066822410311")
            is_owner = (
                interaction.user.id == 1000737066822410311
                or str(interaction.user.id) == owner_id_env
                or await interaction.client.is_owner(interaction.user)
            )
            if not is_owner:
                await interaction.response.send_message(
                    "🚫 **Akses Ditolak**: Menu panduan **Radar & Notifikasi Media** khusus diperuntukkan bagi **Pemilik Bot (Owner)**.",
                    ephemeral=True
                )
                return

        cat_data = HELP_CATEGORIES.get(selected_key, HELP_CATEGORIES["overview"])
        embed = discord.Embed(
            title=cat_data["title"],
            description=cat_data["desc"],
            color=cat_data["color"]
        )
        for f in cat_data["fields"]:
            embed.add_field(name=f["name"], value=f["value"], inline=False)
            
        embed.set_footer(text=f"RTM-Bot • Modul Aktif: 13 • Kategori: {selected_key.capitalize()}")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Beranda", style=discord.ButtonStyle.primary, emoji="🏠", custom_id="rtmbot:help_home_btn", row=1)
    async def home_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cat_data = HELP_CATEGORIES["overview"]
        embed = discord.Embed(
            title=cat_data["title"],
            description=cat_data["desc"],
            color=cat_data["color"]
        )
        for f in cat_data["fields"]:
            embed.add_field(name=f["name"], value=f["value"], inline=False)
        embed.set_footer(text="RTM-Bot • Modul Aktif: 13 • Kategori: Overview")
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Terjadi kendala saat memperbarui tampilan. Coba jalankan kembali `/help`.", ephemeral=True)
        except Exception:
            pass

class InsightHub(commands.Cog, name="Community Insights & Utility"):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = 'gender_roles_config.json'
        self.config = self.load_config()
        self.gender_warning_cooldown = {}

    async def cog_load(self):
        self.bot.add_view(HelpView())

    async def buat_tulisan_tangan(self, teks, nama):
        session = getattr(self.bot, 'session', None)
        close_session = False
        if not session or session.closed:
            session = aiohttp.ClientSession()
            close_session = True
        try:
            gambar_data = await download_asset(IMAGE_URL, session)
            if not gambar_data:
                return None
                
            font_data = await download_asset(FONT_URL, session, is_font=True)
            if not font_data:
                return None

            file_id = uuid.uuid4().hex[:8]
            temp_font_path = f"temp_font_{file_id}.ttf"
            with open(temp_font_path, "wb") as f:
                f.write(font_data)

            def _render():
                try:
                    gambar_latar = Image.open(gambar_data)
                    font_tulisan = ImageFont.truetype(temp_font_path, UKURAN_FONT_TEKS)
                    font_nama = ImageFont.truetype(temp_font_path, UKURAN_FONT_NAMA)

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

                    nama_file_hasil = f"tulisan_tangan_{file_id}.png"
                    gambar_latar.save(nama_file_hasil)
                    return nama_file_hasil
                finally:
                    if os.path.exists(temp_font_path):
                        try:
                            os.remove(temp_font_path)
                        except Exception:
                            pass

            return await asyncio.to_thread(_render)
        except Exception as e:
            print(f"Error dalam memuat aset: {e}")
            return None
        finally:
            if close_session and not session.closed:
                await session.close()

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
             pass

        member = message.author
        if not self.has_gender_role(member, guild_id):
            now = time.time()
            last_warn = self.gender_warning_cooldown.get(member.id, 0)
            if now - last_warn < 600:  # Cooldown 10 menit per user agar tidak spam channel
                return
            self.gender_warning_cooldown[member.id] = now

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
            embed.set_footer(text="Pengingat ini muncul berkala sampai kamu mengambil role.")
            await message.channel.send(embed=embed)

    @commands.hybrid_command(name='tulis', description='Mengubah teks menjadi gambar tulisan tangan.')
    @app_commands.describe(nama="Nama pembuat tulisan", teks="Teks yang ingin diubah menjadi tulisan tangan")
    async def tulis_tangan(self, ctx, nama: str, *, teks: str):
        if not nama or not teks:
            await ctx.send("Mohon berikan nama dan teks yang ingin Anda ubah menjadi tulisan tangan.\nContoh: `!tulis Rhdevs Ini adalah teks`")
            return

        await ctx.send("Sedang menulis... Mohon tunggu sebentar.")
        
        nama_file_hasil = await self.buat_tulisan_tangan(teks, nama)

        if nama_file_hasil:
            try:
                await ctx.send(file=discord.File(nama_file_hasil))
            finally:
                if os.path.exists(nama_file_hasil):
                    try:
                        os.remove(nama_file_hasil)
                    except Exception:
                        pass
        else:
            await ctx.send("Terjadi kesalahan saat membuat gambar. Coba lagi nanti.")

    @commands.hybrid_command(name="faq", description="Menampilkan FAQ dengan tombol.")
    async def faq_command(self, ctx: commands.Context):
        if ctx.message:
            try: await ctx.message.delete()
            except: pass
        if FAQ_CHANNEL_ID and ctx.guild and ctx.guild.get_channel(FAQ_CHANNEL_ID):
            if ctx.channel.id != FAQ_CHANNEL_ID:
                await ctx.send("Perintah ini hanya bisa digunakan di channel FAQ.", delete_after=5)
                return

        embed = discord.Embed(
            title="📚 FAQ - Njan Discord",
            description="Halo! Silakan pilih salah satu tombol di bawah untuk melihat informasi yang Anda butuhkan.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, view=FAQView(), delete_after=300)

    @commands.hybrid_command(name='user', description='Menampilkan info profil user.')
    @app_commands.describe(user="User yang ingin diperiksa")
    async def user_info(self, ctx, user: discord.User = None):
        if not user:
            user = ctx.author

        member = ctx.guild.get_member(user.id) if ctx.guild else None
        embed = self.get_user_info_embed(user, member)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='avatar', description='Menampilkan avatar user.')
    @app_commands.describe(user="User yang ingin dilihat avatarnya")
    async def avatar(self, ctx, user: discord.User = None):
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

    @commands.hybrid_command(name="help", aliases=["h", "bantuan"], description="Pusat panduan perintah dan fitur interaktif RTM-Bot")
    async def help_command(self, ctx: commands.Context):
        cat_data = HELP_CATEGORIES["overview"]
        embed = discord.Embed(
            title=cat_data["title"],
            description=cat_data["desc"],
            color=cat_data["color"]
        )
        for f in cat_data["fields"]:
            embed.add_field(name=f["name"], value=f["value"], inline=False)
        embed.set_footer(text="RTM-Bot • Modul Aktif: 13 • Kategori: Overview")

        view = HelpView()
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(InsightHub(bot))
