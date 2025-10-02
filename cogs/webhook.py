import discord
from discord.ext import commands
import json
import uuid
import asyncio
import os
from datetime import datetime, timedelta
import sys
import logging
import pytz

# =================================================================
# Konfigurasi Logging
# =================================================================
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# =================================================================
# Kelas Modal dan View untuk UI Konfigurasi
# =================================================================

class TextModal(discord.ui.Modal, title='Masukkan Teks'):
    def __init__(self, key, config, view):
        super().__init__()
        self.key = key
        self.config = config
        self.view = view
        self.text_input = discord.ui.TextInput(
            label=self.get_label(key),
            style=discord.TextStyle.paragraph if key == 'desc' else discord.TextStyle.short,
            default=config.get(key)
        )
        self.add_item(self.text_input)

    def get_label(self, key):
        labels = {
            'author': 'Nama Pengirim',
            'avatar': 'URL Foto Pengirim',
            'title': 'Judul Embed',
            'desc': 'Deskripsi Embed',
            'content': 'Teks Pesan Biasa',
        }
        return labels.get(key, key.capitalize())

    async def on_submit(self, interaction: discord.Interaction):
        self.config[self.key] = self.text_input.value
        await interaction.response.edit_message(embed=self.view.build_embed())

class ButtonsModal(discord.ui.Modal, title='Konfigurasi Tombol'):
    def __init__(self, config, view):
        super().__init__()
        self.config = config
        self.view = view
        self.buttons_input = discord.ui.TextInput(
            label='Data Tombol (JSON)',
            style=discord.TextStyle.paragraph,
            placeholder='[{"label": "Ambil Role", "style": "green", "action": "role", "value": "123456789012345678"}]',
            default=json.dumps(config.get('buttons', []), indent=2)
        )
        self.add_item(self.buttons_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            buttons_data = json.loads(self.buttons_input.value)
            self.config['buttons'] = buttons_data
            await interaction.response.edit_message(embed=self.view.build_embed())
        except json.JSONDecodeError:
            await interaction.response.send_message("Format JSON tidak valid. Periksa sintaks Anda.", ephemeral=True)

class ColorModal(discord.ui.Modal, title='Pilih Warna Kustom'):
    def __init__(self, config, view, color_message):
        super().__init__()
        self.config = config
        self.view = view
        self.color_message = color_message

        self.color_input = discord.ui.TextInput(
            label='Masukkan kode Hex kustom:',
            style=discord.TextStyle.short,
            placeholder='#2b2d31',
            default=config.get('color')
        )
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        color_str = self.color_input.value
        try:
            if not color_str.startswith('#'):
                color_str = '#' + color_str
            int_color = int(color_str.replace('#', ''), 16)
            self.config['color'] = color_str
            await interaction.response.edit_message(embed=self.view.build_embed())
            await self.color_message.delete()
        except ValueError:
            await interaction.response.send_message("Kode warna tidak valid. Gunakan format heksadesimal (e.g., `#2b2d31`).", ephemeral=True)

class ColorView(discord.ui.View):
    def __init__(self, config, parent_view):
        super().__init__(timeout=60)
        self.config = config
        self.parent_view = parent_view
        
        self.add_button_color("Biru", "#3498DB")
        self.add_button_color("Merah", "#E74C3C")
        self.add_button_color("Hijau", "#2ECC71")
        self.add_button_color("Emas", "#F1C40F")
        self.add_button_color("Ungu", "#9B59B6")
        self.add_button_color("Oranye", "#E67E22")
        self.add_button_color("Abu-abu", "#95A5A6")
        self.add_button_color("Biru Tua", "#0000FF")
        self.add_button_color("Cyan", "#00FFFF")
        self.add_button_color("Merah Tua", "#8B0000")
        self.add_button_color("Hijau Tua", "#006400")
        self.add_button_color("Coklat", "#A52A2A")

    def add_button_color(self, label, hex_value):
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
        button.callback = lambda i: self.select_color(i, hex_value)
        self.add_item(button)

    async def select_color(self, interaction: discord.Interaction, hex_value):
        self.config['color'] = hex_value
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
        self.stop()
        
    @discord.ui.button(label="Pilih Kustom", style=discord.ButtonStyle.primary)
    async def custom_color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ColorModal(self.config, self.parent_view, interaction.message))
        self.stop()
        
    async def on_timeout(self):
        if self.message:
            await self.message.delete()

class SaveConfigModal(discord.ui.Modal, title='Simpan Konfigurasi'):
    def __init__(self, config, cog):
        super().__init__()
        self.config = config
        self.cog = cog
        self.name_input = discord.ui.TextInput(
            label='Nama Konfigurasi',
            placeholder='e.g., "Pesan Selamat Datang"',
            required=True
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        config_name = self.name_input.value
        self.cog.save_config_to_file(interaction.guild.id, interaction.channel.id, config_name, self.config)
        await interaction.response.send_message(f"Konfigurasi '{config_name}' berhasil disimpan!", ephemeral=True)

class WebhookConfigView(discord.ui.View):
    def __init__(self, bot, channel: discord.TextChannel, initial_config=None):
        super().__init__(timeout=300)
        self.bot = bot
        self.channel = channel
        self.config = initial_config or {}

    def build_embed(self):
        embed = discord.Embed(
            title="Konfigurasi Pesan Webhook",
            description="Silakan gunakan tombol di bawah untuk mengatur pesan.",
            color=0x2b2d31
        )
        
        embed.add_field(name="Judul", value=f"`{self.config.get('title', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Deskripsi", value=f"`{self.config.get('desc', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Warna", value=f"`{self.config.get('color', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Pengirim", value=f"`{self.config.get('author', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Foto Pengirim", value=f"`{self.config.get('avatar', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Tombol", value=f"`{len(self.config.get('buttons', []))} tombol`", inline=False)
        embed.add_field(name="Kanal Tujuan", value=self.channel.mention, inline=False)
        
        return embed

    @discord.ui.button(label="Judul & Deskripsi", style=discord.ButtonStyle.blurple)
    async def title_desc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class TitleDescModal(discord.ui.Modal, title="Judul & Deskripsi"):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.title_input = discord.ui.TextInput(label="Judul Embed", default=config.get('title', ''), required=False)
                self.desc_input = discord.ui.TextInput(label="Deskripsi Embed", style=discord.TextStyle.paragraph, default=config.get('desc', ''), required=False)
                self.add_item(self.title_input)
                self.add_item(self.desc_input)
            
            async def on_submit(self, interaction: discord.Interaction):
                self.config['title'] = self.title_input.value or None
                self.config['desc'] = self.desc_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())
        
        await interaction.response.send_modal(TitleDescModal(self.config, self))

    @discord.ui.button(label="Warna", style=discord.ButtonStyle.blurple)
    async def color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=ColorView(self.config, self))

    @discord.ui.button(label="Pengirim", style=discord.ButtonStyle.blurple)
    async def author_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextModal('author', self.config, self))

    @discord.ui.button(label="Foto Pengirim", style=discord.ButtonStyle.blurple)
    async def avatar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextModal('avatar', self.config, self))

    @discord.ui.button(label="Tombol Interaktif", style=discord.ButtonStyle.blurple)
    async def buttons_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ButtonsModal(self.config, self))
        
    @discord.ui.button(label="Pesan Teks Biasa", style=discord.ButtonStyle.blurple)
    async def content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextModal('content', self.config, self))
        
    @discord.ui.button(label="Simpan Konfigurasi", style=discord.ButtonStyle.grey, row=1)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SaveConfigModal(self.config, self.bot.get_cog('WebhookCog')))

    @discord.ui.button(label="Kirim Webhook", style=discord.ButtonStyle.green, row=1)
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Menerima permintaan kirim webhook dari pengguna {interaction.user.name}")
        await interaction.response.defer(ephemeral=True)

        embed = None
        if self.config.get('title') or self.config.get('desc') or self.config.get('color'):
            try:
                color = int(self.config['color'].replace('#', ''), 16) if self.config.get('color') else 0x2b2d31
                embed = discord.Embed(
                    title=self.config.get('title'),
                    description=self.config.get('desc'),
                    color=color
                )
            except (ValueError, TypeError):
                logging.error("Gagal membuat embed. Format warna tidak valid.")
                await interaction.followup.send("Format warna tidak valid. Pesan tidak dikirim.", ephemeral=True)
                return

        webhook = discord.utils.get(await self.channel.webhooks(), name="Webhook Bot")
        if not webhook:
            logging.info("Webhook tidak ditemukan, membuat webhook baru.")
            try:
                webhook = await self.channel.create_webhook(name="Webhook Bot")
            except discord.Forbidden:
                await interaction.followup.send("Gagal membuat webhook. Pastikan bot memiliki izin `Manage Webhooks`.", ephemeral=True)
                return

        view = None
        buttons_data = self.config.get('buttons', [])
        if buttons_data:
            try:
                actions_map = {}
                for btn_data in buttons_data:
                    btn_id = btn_data.get('id') or str(uuid.uuid4())
                    btn_data['id'] = btn_id
                    actions_map[btn_id] = {'action': btn_data.get('action'), 'value': btn_data.get('value')}
                
                self.bot.get_cog('WebhookCog').button_actions.update(actions_map)
                
                view = ButtonView(buttons_data)
            except Exception as e:
                logging.error(f"Gagal membuat view tombol: {e}", exc_info=True)
                await interaction.followup.send("Gagal membuat tombol. Mohon periksa format JSON Anda.", ephemeral=True)
                return

        sent_message = None
        try:
            logging.info("Mencoba mengirim pesan webhook...")
            sent_message = await webhook.send(
                content=self.config.get('content'),
                username=self.config.get('author') or interaction.guild.name,
                avatar_url=self.config.get('avatar') or interaction.guild.icon.url,
                embeds=[embed] if embed else [],
                view=view,
                wait=True
            )
            logging.info("Pesan webhook berhasil terkirim.")
            
            logging.info("Webhook berhasil dikirim, memeriksa objek pesan...")
            if sent_message:
                logging.info("Objek pesan valid, melanjutkan ke penyimpanan.")
                config_name = str(sent_message.id)
                self.bot.get_cog('WebhookCog').save_config_to_file(interaction.guild.id, interaction.channel.id, config_name, self.config)
                await interaction.followup.send(f"Pesan webhook berhasil dikirim ke {self.channel.mention}! Konfigurasi tersimpan otomatis dengan nama `{config_name}`.", ephemeral=True)
                logging.info(f"Konfigurasi berhasil disimpan dengan nama: {config_name}")
            else:
                logging.error("Objek pesan tidak valid, tidak dapat menyimpan konfigurasi.")
                await interaction.followup.send("Pesan webhook berhasil dikirim, tetapi gagal mendapatkan objek pesan untuk menyimpan konfigurasi. Mohon hubungi admin.", ephemeral=True)

            await interaction.message.delete()

        except discord.errors.NotFound:
            logging.info("Menu konfigurasi sudah tidak ada, tidak dapat dihapus.")
        except Exception as e:
            logging.error(f"Gagal mengirim atau menyimpan: {e}", exc_info=True)
            await interaction.followup.send(f"Gagal menyelesaikan proses. Mohon hapus menu konfigurasi secara manual: {e}", ephemeral=True)
            
    @discord.ui.button(label="Batalkan", style=discord.ButtonStyle.red, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Operasi dibatalkan.", ephemeral=True)
        await interaction.message.delete()
        self.stop()
        
# =================================================================
# Kelas View untuk Tombol Interaktif di Pesan Final
# =================================================================
class ButtonView(discord.ui.View):
    def __init__(self, buttons_data):
        super().__init__(timeout=None)
        for data in buttons_data:
            self.add_item(self.create_button(data))

    def create_button(self, data):
        label = data.get('label', 'Tombol')
        style_str = data.get('style', 'blurple')
        style_map = {
            'blurple': discord.ButtonStyle.blurple,
            'red': discord.ButtonStyle.red,
            'green': discord.ButtonStyle.green,
            'grey': discord.ButtonStyle.grey,
        }
        style = style_map.get(style_str, discord.ButtonStyle.blurple)
        
        button = discord.ui.Button(label=label, style=style, custom_id=data['id'])
        return button

# =================================================================
# Kelas Modal dan View untuk UI Konfigurasi Announcement
# =================================================================
class AnnouncementConfigView(discord.ui.View):
    def __init__(self, bot, channel: discord.TextChannel, initial_config=None):
        super().__init__(timeout=300)
        self.bot = bot
        self.channel = channel
        self.config = initial_config or {}

    def build_embed(self):
        embed = discord.Embed(
            title="Konfigurasi Pesan Pengumuman",
            description="Silakan gunakan tombol di bawah untuk mengatur pesan.",
            color=0x2b2d31
        )
        
        embed.add_field(name="Judul", value=f"`{self.config.get('title', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Deskripsi", value=f"`{self.config.get('desc', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Warna", value=f"`{self.config.get('color', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Pesan Teks", value=f"`{self.config.get('content', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Media (URL)", value=f"`{self.config.get('media_url', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Kanal Tujuan", value=self.channel.mention, inline=False)
        
        return embed

    @discord.ui.button(label="Judul & Deskripsi", style=discord.ButtonStyle.blurple)
    async def title_desc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class TitleDescModal(discord.ui.Modal, title="Judul & Deskripsi"):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.title_input = discord.ui.TextInput(label="Judul Embed", default=config.get('title', ''), required=False)
                self.desc_input = discord.ui.TextInput(label="Deskripsi Embed", style=discord.TextStyle.paragraph, default=config.get('desc', ''), required=False)
                self.add_item(self.title_input)
                self.add_item(self.desc_input)
            
            async def on_submit(self, interaction: discord.Interaction):
                self.config['title'] = self.title_input.value or None
                self.config['desc'] = self.desc_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())
        
        await interaction.response.send_modal(TitleDescModal(self.config, self))

    @discord.ui.button(label="Pesan Teks Biasa", style=discord.ButtonStyle.blurple)
    async def content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ContentModal(discord.ui.Modal, title='Masukkan Teks Pesan'):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.text_input = discord.ui.TextInput(
                    label='Teks Pesan Biasa',
                    style=discord.TextStyle.paragraph,
                    default=config.get('content')
                )
                self.add_item(self.text_input)

            async def on_submit(self, interaction: discord.Interaction):
                self.config['content'] = self.text_input.value
                await interaction.response.edit_message(embed=self.view.build_embed())
        
        await interaction.response.send_modal(ContentModal(self.config, self))
        
    @discord.ui.button(label="Media (URL)", style=discord.ButtonStyle.blurple)
    async def media_url_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class MediaUrlModal(discord.ui.Modal, title='Tambahkan URL Media'):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.url_input = discord.ui.TextInput(
                    label='URL Gambar/Video',
                    placeholder='e.g., https://example.com/image.png',
                    default=config.get('media_url')
                )
                self.add_item(self.url_input)

            async def on_submit(self, interaction: discord.Interaction):
                self.config['media_url'] = self.url_input.value
                await interaction.response.edit_message(embed=self.view.build_embed())

        await interaction.response.send_modal(MediaUrlModal(self.config, self))

    @discord.ui.button(label="Warna", style=discord.ButtonStyle.blurple)
    async def color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=ColorView(self.config, self))
        
    @discord.ui.button(label="Kirim Pengumuman", style=discord.ButtonStyle.green, row=1)
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Menerima permintaan kirim pengumuman dari pengguna {interaction.user.name}")
        await interaction.response.defer(ephemeral=True)

        embed = None
        if self.config.get('title') or self.config.get('desc') or self.config.get('color'):
            try:
                color = int(self.config['color'].replace('#', ''), 16) if self.config.get('color') else 0x2b2d31
                embed = discord.Embed(
                    title=self.config.get('title'),
                    description=self.config.get('desc'),
                    color=color
                )
                if self.config.get('media_url'):
                    embed.set_image(url=self.config['media_url'])
            except (ValueError, TypeError):
                logging.error("Gagal membuat embed. Format warna tidak valid.")
                await interaction.followup.send("Format warna tidak valid. Pesan tidak dikirim.", ephemeral=True)
                return

        # Kirim pesan
        try:
            await self.channel.send(content=self.config.get('content'), embeds=[embed] if embed else [])
            await interaction.followup.send(f"Pesan pengumuman berhasil dikirim ke {self.channel.mention}!", ephemeral=True)
            await interaction.message.delete()
        except Exception as e:
            logging.error(f"Gagal mengirim pengumuman: {e}", exc_info=True)
            await interaction.followup.send(f"Gagal mengirim pengumuman. Mohon periksa izin bot di channel tujuan. ({e})", ephemeral=True)

    @discord.ui.button(label="Batalkan", style=discord.ButtonStyle.red, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Operasi dibatalkan.", ephemeral=True)
        await interaction.message.delete()
        self.stop()
        
# =================================================================
# Kelas View untuk Tombol Interaktif di Pesan Final
# =================================================================
class ButtonView(discord.ui.View):
    def __init__(self, buttons_data):
        super().__init__(timeout=None)
        for data in buttons_data:
            self.add_item(self.create_button(data))

    def create_button(self, data):
        label = data.get('label', 'Tombol')
        style_str = data.get('style', 'blurple')
        style_map = {
            'blurple': discord.ButtonStyle.blurple,
            'red': discord.ButtonStyle.red,
            'green': discord.ButtonStyle.green,
            'grey': discord.ButtonStyle.grey,
        }
        style = style_map.get(style_str, discord.ButtonStyle.blurple)
        
        button = discord.ui.Button(label=label, style=style, custom_id=data['id'])
        return button

# =================================================================
# Kelas Modal dan View untuk UI Konfigurasi Schedule
# =================================================================
class ScheduleTimeModal(discord.ui.Modal, title='Tentukan Jadwal & Kanal'):
    def __init__(self, config, view):
        super().__init__()
        self.config = config
        self.view = view
        self.date_input = discord.ui.TextInput(
            label='Tanggal (YYYY-MM-DD)',
            placeholder=datetime.now().strftime('%Y-%m-%d'),
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.date_input)
        
        self.time_input = discord.ui.TextInput(
            label='Waktu (HH:MM WIB)',
            placeholder='Contoh: 15:30',
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.time_input)

        self.channel_input = discord.ui.TextInput(
            label='ID Kanal Tujuan',
            placeholder='Masukkan ID Kanal',
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.channel_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            scheduled_time_str = f"{self.date_input.value} {self.time_input.value}"
            wib_timezone = pytz.timezone('Asia/Jakarta')
            scheduled_datetime_wib = wib_timezone.localize(datetime.strptime(scheduled_time_str, "%Y-%m-%d %H:%M"))

            now_wib = datetime.now(wib_timezone)
            
            # Memperbolehkan penjadwalan hingga 5 menit ke belakang
            if scheduled_datetime_wib < now_wib - timedelta(minutes=5):
                await interaction.response.send_message("Tanggal dan waktu yang dijadwalkan harus di masa mendatang, atau maksimal 5 menit yang lalu.", ephemeral=True)
                return
            
            self.config['scheduled_time'] = scheduled_datetime_wib.isoformat()
            
            try:
                channel_id = int(self.channel_input.value)
                channel = interaction.guild.get_channel(channel_id)
                if not channel:
                    raise ValueError
                self.config['channel_id'] = channel_id
            except ValueError:
                await interaction.response.send_message("ID kanal tidak valid. Mohon masukkan ID kanal yang benar.", ephemeral=True)
                return

            await interaction.response.edit_message(embed=self.view.build_embed())
        
        except ValueError:
            await interaction.response.send_message("Format tanggal atau waktu tidak valid. Gunakan format YYYY-MM-DD HH:MM.", ephemeral=True)

class ScheduleConfigView(discord.ui.View):
    def __init__(self, bot, guild, initial_config=None):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild = guild
        self.config = initial_config or {}

    def build_embed(self):
        embed = discord.Embed(
            title="Konfigurasi Pengumuman Berjadwal",
            description="Atur pesan dan jadwal pengumuman di sini.",
            color=0x2b2d31
        )
        
        scheduled_time = self.config.get('scheduled_time')
        scheduled_time_display = "Belum diatur"
        if scheduled_time:
            wib_timezone = pytz.timezone('Asia/Jakarta')
            scheduled_datetime_wib = datetime.fromisoformat(scheduled_time).astimezone(wib_timezone)
            scheduled_time_display = scheduled_datetime_wib.strftime('%d %B %Y, %H:%M WIB')

        channel_id = self.config.get('channel_id')
        channel_display = "Belum diatur"
        if channel_id:
            channel = self.guild.get_channel(channel_id)
            channel_display = channel.mention if channel else f"Kanal tidak ditemukan ({channel_id})"

        embed.add_field(name="Waktu Terjadwal", value=f"`{scheduled_time_display}`", inline=False)
        embed.add_field(name="Kanal Tujuan", value=channel_display, inline=False)
        embed.add_field(name="Judul Embed", value=f"`{self.config.get('title', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Deskripsi Embed", value=f"`{self.config.get('desc', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Warna", value=f"`{self.config.get('color', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Pesan Teks", value=f"`{self.config.get('content', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Media (URL)", value=f"`{self.config.get('media_url', 'Belum diatur')}`", inline=False)
        
        return embed

    @discord.ui.button(label="Tentukan Jadwal & Kanal", style=discord.ButtonStyle.primary, row=0)
    async def schedule_time_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ScheduleTimeModal(self.config, self))

    @discord.ui.button(label="Judul & Deskripsi", style=discord.ButtonStyle.blurple, row=1)
    async def title_desc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class TitleDescModal(discord.ui.Modal, title="Judul & Deskripsi"):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.title_input = discord.ui.TextInput(label="Judul Embed", default=config.get('title', ''), required=False)
                self.desc_input = discord.ui.TextInput(label="Deskripsi Embed", style=discord.TextStyle.paragraph, default=config.get('desc', ''), required=False)
                self.add_item(self.title_input)
                self.add_item(self.desc_input)
            
            async def on_submit(self, interaction: discord.Interaction):
                self.config['title'] = self.title_input.value or None
                self.config['desc'] = self.desc_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())
        
        await interaction.response.send_modal(TitleDescModal(self.config, self))

    @discord.ui.button(label="Pesan Teks Biasa", style=discord.ButtonStyle.blurple, row=1)
    async def content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ContentModal(discord.ui.Modal, title='Masukkan Teks Pesan'):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.text_input = discord.ui.TextInput(
                    label='Teks Pesan Biasa',
                    style=discord.TextStyle.paragraph,
                    default=config.get('content')
                )
                self.add_item(self.text_input)

            async def on_submit(self, interaction: discord.Interaction):
                self.config['content'] = self.text_input.value
                await interaction.response.edit_message(embed=self.view.build_embed())
        
        await interaction.response.send_modal(ContentModal(self.config, self))
        
    @discord.ui.button(label="Media (URL)", style=discord.ButtonStyle.blurple, row=1)
    async def media_url_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class MediaUrlModal(discord.ui.Modal, title='Tambahkan URL Media'):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.url_input = discord.ui.TextInput(
                    label='URL Gambar/Video',
                    placeholder='e.g., https://example.com/image.png',
                    default=config.get('media_url')
                )
                self.add_item(self.url_input)

            async def on_submit(self, interaction: discord.Interaction):
                self.config['media_url'] = self.url_input.value
                await interaction.response.edit_message(embed=self.view.build_embed())

        await interaction.response.send_modal(MediaUrlModal(self.config, self))

    @discord.ui.button(label="Warna", style=discord.ButtonStyle.blurple, row=1)
    async def color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=ColorView(self.config, self))
        
    @discord.ui.button(label="Jadwalkan Pengumuman", style=discord.ButtonStyle.green, row=2)
    async def schedule_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logging.info(f"Menerima permintaan menjadwalkan pengumuman dari pengguna {interaction.user.name}")
        await interaction.response.defer(ephemeral=True)

        # Validasi konfigurasi
        if not self.config.get('scheduled_time'):
            await interaction.followup.send("Mohon tentukan jadwal pengumuman terlebih dahulu.", ephemeral=True)
            return
        if not self.config.get('channel_id'):
            await interaction.followup.send("Mohon tentukan kanal tujuan terlebih dahulu.", ephemeral=True)
            return
        if not self.config.get('content') and not self.config.get('title') and not self.config.get('media_url'):
            await interaction.followup.send("Pengumuman harus memiliki konten, judul embed, atau URL media.", ephemeral=True)
            return

        # Simpan data ke file
        scheduled_announcements = self.bot.get_cog('WebhookCog').load_scheduled_announcements()
        job_id = str(uuid.uuid4())
        job_data = {
            'guild_id': self.guild.id,
            'channel_id': self.config['channel_id'],
            'scheduled_time': self.config['scheduled_time'],
            'content': self.config.get('content'),
            'title': self.config.get('title'),
            'desc': self.config.get('desc'),
            'media_url': self.config.get('media_url'),
            'color': self.config.get('color')
        }
        scheduled_announcements[job_id] = job_data
        self.bot.get_cog('WebhookCog').save_scheduled_announcements(scheduled_announcements)
        
        # Konfirmasi ke pengguna
        scheduled_datetime_wib = datetime.fromisoformat(self.config['scheduled_time']).astimezone(pytz.timezone('Asia/Jakarta'))
        channel = self.guild.get_channel(self.config['channel_id'])
        await interaction.followup.send(f"✅ Pengumuman berhasil dijadwalkan untuk dikirim ke {channel.mention} pada **{scheduled_datetime_wib.strftime('%d %B %Y pukul %H:%M WIB')}**.", ephemeral=True)
        await interaction.message.delete()
        self.stop()

    @discord.ui.button(label="Batalkan", style=discord.ButtonStyle.red, row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Operasi dibatalkan.", ephemeral=True)
        await interaction.message.delete()
        self.stop()
# =================================================================
# Main Cog
# =================================================================
class WebhookCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.button_actions = {}
        self.active_tickets = {}
        self.data_dir = 'data'
        self.config_file = os.path.join(self.data_dir, 'webhook.json')
        self.backup_file = os.path.join(self.data_dir, 'configbackup.json')
        self.scheduled_announcements_file = os.path.join(self.data_dir, 'scheduled_announcements.json')
        self.wib_timezone = pytz.timezone('Asia/Jakarta')
        self.scheduler_task = self.bot.loop.create_task(self.check_scheduled_announcements())

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("Bot siap. Memuat semua aksi tombol dari file JSON...")
        self._load_all_button_actions()
        logging.info("Aksi tombol berhasil dimuat.")

    async def check_scheduled_announcements(self):
        """Background task untuk memeriksa dan mengirim pengumuman berjadwal."""
        await self.bot.wait_until_ready()
        logging.info("Memulai pengecekan pengumuman berjadwal.")
        while not self.bot.is_closed():
            try:
                scheduled_announcements = self.load_scheduled_announcements()
                
                now_wib = datetime.now(self.wib_timezone)
                tasks_to_remove = []

                for job_id, job_data in list(scheduled_announcements.items()):
                    scheduled_time_wib = datetime.fromisoformat(job_data['scheduled_time']).astimezone(self.wib_timezone)

                    if now_wib >= scheduled_time_wib:
                        logging.info(f"Menjalankan pengumuman berjadwal: {job_data.get('content')}")
                        guild = self.bot.get_guild(job_data['guild_id'])
                        if not guild:
                            logging.error(f"Guild tidak ditemukan untuk job ID: {job_id}")
                            tasks_to_remove.append(job_id)
                            continue
                        
                        channel = guild.get_channel(job_data['channel_id'])
                        if not channel:
                            logging.error(f"Channel tidak ditemukan untuk job ID: {job_id}")
                            tasks_to_remove.append(job_id)
                            continue

                        content = job_data.get('content')
                        embed = None
                        if job_data.get('title') or job_data.get('desc') or job_data.get('media_url') or job_data.get('color'):
                            try:
                                color = int(job_data['color'].replace('#', ''), 16) if job_data.get('color') else 0x2b2d31
                                embed = discord.Embed(
                                    title=job_data.get('title'),
                                    description=job_data.get('desc'),
                                    color=color
                                )
                                if job_data.get('media_url'):
                                    embed.set_image(url=job_data['media_url'])
                            except (ValueError, TypeError):
                                logging.error(f"Format warna tidak valid pada job ID: {job_id}")

                        try:
                            await channel.send(content=content, embeds=[embed] if embed else [])
                        except discord.errors.Forbidden:
                            logging.error(f"Bot tidak memiliki izin kirim pesan di channel {channel.name}")
                        except Exception as e:
                            logging.error(f"Gagal mengirim pesan berjadwal: {e}")

                        tasks_to_remove.append(job_id)

                if tasks_to_remove:
                    self.remove_scheduled_announcements(tasks_to_remove)
                    
            except Exception as e:
                logging.error(f"Terjadi kesalahan pada scheduler: {e}", exc_info=True)
            
            await asyncio.sleep(60) # Cek setiap 60 detik

    def load_scheduled_announcements(self):
        """Memuat pengumuman berjadwal dari file JSON."""
        if not os.path.exists(self.scheduled_announcements_file):
            return {}
        try:
            with open(self.scheduled_announcements_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def save_scheduled_announcements(self, data):
        """Menyimpan pengumuman berjadwal ke file JSON."""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        try:
            with open(self.scheduled_announcements_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logging.error(f"Gagal menyimpan pengumuman berjadwal: {e}")

    def remove_scheduled_announcements(self, ids):
        """Menghapus pengumuman berjadwal dari file."""
        scheduled_announcements = self.load_scheduled_announcements()
        for job_id in ids:
            scheduled_announcements.pop(job_id, None)
        self.save_scheduled_announcements(scheduled_announcements)

    def _load_all_button_actions(self):
        """Helper function to load all button actions from the single JSON file."""
        if not os.path.exists(self.config_file):
            return

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                all_configs = json.load(f)
            
            for guild_id, guild_configs in all_configs.items():
                for channel_id, channel_configs in guild_configs.items():
                    for config_name, config_data in channel_configs.items():
                        buttons_data = config_data.get('buttons', [])
                        if buttons_data:
                            for btn_data in buttons_data:
                                btn_id = btn_data.get('id')
                                if btn_id:
                                    self.button_actions[btn_id] = {
                                        'action': btn_data.get('action'),
                                        'value': btn_data.get('value')
                                    }
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logging.error(f"Gagal memuat file konfigurasi {self.config_file}: {e}")

    def save_config_to_file(self, guild_id, channel_id, config_name, config_data):
        """Helper function untuk menyimpan konfigurasi ke file dengan struktur hierarkis."""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        
        all_configs = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    all_configs = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        
        guild_id_str = str(guild_id)
        channel_id_str = str(channel_id)

        if guild_id_str not in all_configs:
            all_configs[guild_id_str] = {}
        if channel_id_str not in all_configs[guild_id_str]:
            all_configs[guild_id_str][channel_id_str] = {}
        
        all_configs[guild_id_str][channel_id_str][config_name] = config_data
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(all_configs, f, indent=4)
        except Exception as e:
            logging.error(f"Gagal menyimpan konfigurasi ke file: {e}")

    @commands.command(aliases=['swh'])
    @commands.has_permissions(manage_webhooks=True)
    async def send_webhook(self, ctx, channel: discord.TextChannel):
        """Memulai wizard untuk membuat pesan webhook."""
        try:
            await ctx.message.delete()
        except discord.errors.NotFound:
            pass

        view = WebhookConfigView(self.bot, channel)
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(name='announcement')
    @commands.has_permissions(manage_messages=True)
    async def announcement(self, ctx, channel: discord.TextChannel = None):
        """Memulai wizard untuk membuat pesan pengumuman."""
        try:
            await ctx.message.delete()
        except discord.errors.NotFound:
            pass
        
        if not channel:
            channel = ctx.channel

        view = AnnouncementConfigView(self.bot, channel)
        await ctx.send(embed=view.build_embed(), view=view)
    
    @commands.command(name='send_media')
    @commands.has_permissions(manage_messages=True)
    async def send_media(self, ctx, channel: discord.TextChannel = None):
        """
        Mengirim media dari pesan yang dibalas ke channel pengumuman.
        Usage: !send_media [channel] (reply to a message with an attachment)
        """
        if not ctx.message.reference:
            await ctx.send("Silakan balas pesan yang berisi media (foto, video, atau dokumen) yang ingin kamu kirim.", ephemeral=True)
            return
            
        try:
            replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        except discord.errors.NotFound:
            await ctx.send("Pesan yang kamu balas tidak ditemukan.", ephemeral=True)
            return

        if not replied_message.attachments:
            await ctx.send("Pesan yang kamu balas tidak memiliki media (foto, video, atau dokumen).", ephemeral=True)
            return

        if not channel:
            channel = ctx.channel

        try:
            for attachment in replied_message.attachments:
                file_to_send = await attachment.to_file()
                await channel.send(content=replied_message.content, file=file_to_send)
            
            await ctx.send(f"Media berhasil dikirim ke {channel.mention}!", ephemeral=True)
            await ctx.message.delete()
            
        except discord.errors.Forbidden:
            await ctx.send("Saya tidak memiliki izin untuk mengirim pesan atau mengunggah file di channel itu.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan saat mengirim media: {e}", ephemeral=True)
    
    @commands.command(name='schedule')
    @commands.has_permissions(manage_messages=True)
    async def schedule(self, ctx):
        """Memulai wizard untuk menjadwalkan pengumuman."""
        try:
            await ctx.message.delete()
        except discord.errors.NotFound:
            pass

        view = ScheduleConfigView(self.bot, ctx.guild)
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(name='list_schedules')
    @commands.has_permissions(manage_messages=True)
    async def list_schedules(self, ctx):
        """Menampilkan daftar pengumuman yang sedang dijadwalkan."""
        scheduled_announcements = self.load_scheduled_announcements()
        if not scheduled_announcements:
            await ctx.send("Tidak ada pengumuman yang sedang dijadwalkan.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Daftar Pengumuman Berjadwal",
            description="Berikut adalah pengumuman yang akan dikirim bot.",
            color=discord.Color.blue()
        )
        
        wib_timezone = pytz.timezone('Asia/Jakarta')
        
        for job_id, job_data in scheduled_announcements.items():
            try:
                scheduled_time_wib = datetime.fromisoformat(job_data['scheduled_time']).astimezone(wib_timezone)
                channel = self.bot.get_channel(job_data['channel_id'])
                channel_name = channel.mention if channel else f"Kanal tidak ditemukan ({job_data['channel_id']})"
                
                content = job_data.get('content') or job_data.get('title') or "Tanpa konten"
                if len(content) > 50:
                    content = content[:47] + "..."
                
                embed.add_field(
                    name=f"ID: {job_id[:8]}",
                    value=f"**Waktu:** `{scheduled_time_wib.strftime('%H:%M WIB, %d-%m-%Y')}`\n**Kanal:** {channel_name}\n**Konten:** `{content}`",
                    inline=False
                )
            except Exception:
                embed.add_field(name=f"ID: {job_id[:8]}", value="Data tidak valid. Mohon hubungi admin.", inline=False)
        
        await ctx.send(embed=embed, ephemeral=True)


    @commands.command(name='load_config')
    @commands.has_permissions(manage_webhooks=True)
    async def load_config(self, ctx, config_name: str, channel: discord.TextChannel):
        """Memuat konfigurasi webhook dari file dan memulainya."""
        if not ctx.guild:
            await ctx.send("Perintah ini hanya bisa digunakan di dalam server.")
            return
            
        all_configs = {}
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                all_configs = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            await ctx.send(f"File konfigurasi tidak ditemukan atau tidak valid. Tidak ada konfigurasi yang bisa dimuat.")
            return
        
        try:
            config_data = all_configs[str(ctx.guild.id)][str(ctx.channel.id)][config_name]
        except KeyError:
            await ctx.send(f"Konfigurasi dengan nama `{config_name}` tidak ditemukan di kanal ini.")
            return
        
        view = WebhookConfigView(self.bot, channel, initial_config=config_data)
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(name='backup_config')
    @commands.has_permissions(manage_webhooks=True)
    async def backup_config(self, ctx, message: discord.Message):
        """Mencadangkan konfigurasi webhook ke file backup.

        Penggunaan:
        !backup_config <ID pesan>
        """
        if not ctx.guild:
            await ctx.send("Perintah ini hanya bisa digunakan di dalam server.")
            return

        all_configs = {}
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                all_configs = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            await ctx.send("File konfigurasi utama tidak ditemukan atau tidak valid.", ephemeral=True)
            return

        try:
            config_data = all_configs[str(ctx.guild.id)][str(message.channel.id)][str(message.id)]
        except KeyError:
            await ctx.send("Konfigurasi untuk pesan ini tidak ditemukan di file utama.", ephemeral=True)
            return
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        backup_configs = {}
        if os.path.exists(self.backup_file):
            try:
                with open(self.backup_file, 'r', encoding='utf-8') as f:
                    backup_configs = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        
        guild_id_str = str(ctx.guild.id)
        channel_id_str = str(message.channel.id)
        message_id_str = str(message.id)

        if guild_id_str not in backup_configs:
            backup_configs[guild_id_str] = {}
        if channel_id_str not in backup_configs[guild_id_str]:
            backup_configs[guild_id_str][channel_id_str] = {}

        backup_configs[guild_id_str][channel_id_str][message_id_str] = config_data

        try:
            with open(self.backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_configs, f, indent=4)
            await ctx.send(f"Konfigurasi pesan `{message.id}` berhasil dicadangkan ke `{self.backup_file}`.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Gagal mencadangkan konfigurasi: {e}", ephemeral=True)


    @commands.command(name='list_configs')
    @commands.has_permissions(manage_webhooks=True)
    async def list_configs(self, ctx):
        """Menampilkan daftar konfigurasi yang tersimpan di server ini."""
        if not ctx.guild:
            await ctx.send("Perintah ini hanya bisa digunakan di dalam server.", ephemeral=True)
            return
            
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                all_configs = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            await ctx.send("Tidak ada konfigurasi yang tersimpan di server ini.", ephemeral=True)
            return
        
        guild_configs = all_configs.get(str(ctx.guild.id))
        if not guild_configs:
            await ctx.send("Tidak ada konfigurasi yang tersimpan di server ini.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Konfigurasi Tersimpan di {ctx.guild.name}",
            description="Daftar konfigurasi yang bisa Anda muat ulang dengan `!load_config <nama_konfigurasi> #kanal`.",
            color=discord.Color.blue()
        )

        for channel_id, channel_configs in guild_configs.items():
            channel = ctx.guild.get_channel(int(channel_id))
            channel_name = channel.name if channel else f"Kanal tidak ditemukan ({channel_id})"
            
            config_list = "\n".join([f"`{name}`" for name in channel_configs.keys()])
            if config_list:
                embed.add_field(name=f"Kanal: #{channel_name}", value=config_list, inline=False)
        
        await ctx.send(embed=embed, ephemeral=True)


    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.type == discord.InteractionType.component:
            return
            
        custom_id = interaction.data.get('custom_id')
        action_data = self.button_actions.get(custom_id)
        
        if not action_data:
            return

        action = action_data.get('action')
        value = action_data.get('value')
        
        if action == 'role':
            try:
                role_id = int(value)
                role = interaction.guild.get_role(role_id)
                if not role:
                    await interaction.response.send_message("Role tidak ditemukan. Mohon hubungi admin.", ephemeral=True)
                    return

                if role in interaction.user.roles:
                    await interaction.user.remove_roles(role)
                    await interaction.response.send_message(f"Role **{role.name}** telah dihapus.", ephemeral=True)
                else:
                    await interaction.user.add_roles(role)
                    await interaction.response.send_message(f"Anda telah mendapatkan role **{role.name}**!", ephemeral=True)
                    
            except (ValueError, TypeError):
                await interaction.response.send_message("ID role tidak valid. Mohon hubungi admin.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Terjadi kesalahan saat memberikan/menghapus role: {e}", ephemeral=True)
        
        elif action == 'ticket':
            # --- Perbaikan untuk menangani format JSON baru dan lama ---
            if isinstance(value, dict):
                ticket_config = value
                category_id_str = ticket_config.get('category_id')
                allowed_roles_str = ticket_config.get('allowed_roles', [])
                blocked_roles_str = ticket_config.get('blocked_roles', [])
            else: # Format lama (value adalah string)
                category_id_str = value
                allowed_roles_str = []
                blocked_roles_str = []
                
            # Mengubah ID role dari string menjadi integer untuk perbandingan
            allowed_roles = [int(role_id) for role_id in allowed_roles_str]
            blocked_roles = [int(role_id) for role_id in blocked_roles_str]

            # Mengambil ID role pengguna
            user_role_ids = [role.id for role in interaction.user.roles]
            
            # Logika Filter
            if any(role_id in blocked_roles for role_id in user_role_ids):
                await interaction.response.send_message("Anda tidak diizinkan untuk membuka tiket ini.", ephemeral=True)
                return
            
            if allowed_roles and not any(role_id in allowed_roles for role_id in user_role_ids):
                await interaction.response.send_message("Anda harus memiliki role tertentu untuk membuka tiket ini.", ephemeral=True)
                return
            # --- Akhir Logika Filter ---

            if interaction.user.id in self.active_tickets:
                await interaction.response.send_message("Anda sudah memiliki tiket aktif.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            try:
                category_id = int(category_id_str)
                category = interaction.guild.get_channel(category_id)
                if not isinstance(category, discord.CategoryChannel):
                    category = None
            except (ValueError, TypeError):
                category = None # Jika ID kategori tidak valid, set ke None

            specific_mention_role_id = 1264935423184998422
            specific_role = interaction.guild.get_role(specific_mention_role_id)

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }

            if specific_role:
                overwrites[specific_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
                
            channel_name = f"ticket-{interaction.user.name.lower()}"
            ticket_channel = await interaction.guild.create_text_channel(
                channel_name,
                overwrites=overwrites,
                category=category
            )

            mention_string = ""
            if specific_role:
                mention_string = specific_role.mention

            embed = discord.Embed(
                title=f"Tiket dari {interaction.user.name}",
                description="Seorang admin akan segera membantu Anda. Mohon jelaskan masalah Anda.",
                color=discord.Color.green()
            )
            
            close_ticket_id = str(uuid.uuid4())
            self.button_actions[close_ticket_id] = {'action': 'close_ticket', 'value': str(interaction.user.id)}
            
            close_ticket_button = discord.ui.Button(label="Tutup Tiket", style=discord.ButtonStyle.red, custom_id=close_ticket_id)
            view = discord.ui.View(timeout=None)
            view.add_item(close_ticket_button)

            await ticket_channel.send(f"**Tiket Baru!** {mention_string} {interaction.user.mention}", embed=embed, view=view)
            
            await interaction.followup.send(f"Tiket Anda telah dibuat di {ticket_channel.mention}", ephemeral=True)
            
            self.active_tickets[interaction.user.id] = ticket_channel.id
            self.bot.loop.create_task(self.delete_ticket_after_delay(ticket_channel, interaction.user.id))

        elif action == 'close_ticket':
            await interaction.response.defer()
            user_id_to_remove = int(value)
            
            if user_id_to_remove in self.active_tickets:
                del self.active_tickets[user_id_to_remove]
            
            await interaction.channel.delete(reason="Tiket ditutup oleh pengguna atau admin.")
            
        elif action == 'channel':
            try:
                channel_id = int(value)
                target_channel = interaction.guild.get_channel(channel_id)
                
                if target_channel:
                    await target_channel.set_permissions(interaction.user, view_channel=True)
                    await interaction.response.send_message(f"Anda sekarang bisa mengakses kanal {target_channel.mention}!", ephemeral=True)
                else:
                    await interaction.response.send_message("Kanal tidak ditemukan. Mohon hubungi admin.", ephemeral=True)
            except (ValueError, TypeError):
                await interaction.response.send_message("ID kanal tidak valid. Mohon hubungi admin.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Terjadi kesalahan saat memberikan akses kanal: {e}", ephemeral=True)

    async def delete_ticket_after_delay(self, channel, user_id):
        await asyncio.sleep(3600)
        
        if user_id in self.active_tickets and self.active_tickets[user_id] == channel.id:
            is_replied_by_admin = False
            async for message in channel.history(limit=50):
                if message.author.guild_permissions.manage_channels and message.author.id != self.bot.user.id:
                    is_replied_by_admin = True
                    break
            
            if not is_replied_by_admin:
                try:
                    await channel.delete(reason="Tiket otomatis dihapus karena tidak ada balasan admin dalam 1 jam.")
                    del self.active_tickets[user_id]
                except discord.errors.NotFound:
                    pass
            else:
                del self.active_tickets[user_id]

async def setup(bot):
    await bot.add_cog(WebhookCog(bot))
