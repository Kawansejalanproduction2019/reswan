import discord
from discord.ext import commands
import json
import uuid
import asyncio
import os
from datetime import datetime, timedelta
import logging
import pytz
import re

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

def truncate_text(text, limit=1000):
    text_str = str(text) if text else "Belum diatur"
    return f"{text_str[:limit]}..." if len(text_str) > limit else text_str

class TextModal(discord.ui.Modal, title='Masukkan Teks'):
    def __init__(self, key, config, view):
        super().__init__()
        self.key = key
        self.config = config
        self.view = view
        self.text_input = discord.ui.TextInput(
            label=self.get_label(key),
            style=discord.TextStyle.paragraph if key in ['desc', 'content'] else discord.TextStyle.short,
            default=config.get(key, ''),
            required=False,
            max_length=4000 if key in ['desc', 'content'] else 256
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
        self.config[self.key] = self.text_input.value or None
        await interaction.response.edit_message(embed=self.view.build_embed())

class ButtonsModal(discord.ui.Modal, title='Edit JSON Tombol'):
    def __init__(self, config, view):
        super().__init__()
        self.config = config
        self.view = view
        self.buttons_input = discord.ui.TextInput(
            label='Data Tombol (JSON)',
            style=discord.TextStyle.paragraph,
            placeholder='[{"label": "Web", "style": "grey", "action": "url", "value": "https://..."}]',
            default=json.dumps(config.get('buttons', []), indent=2),
            required=False
        )
        self.add_item(self.buttons_input)

    async def on_submit(self, interaction: discord.Interaction):
        val = self.buttons_input.value.strip()
        if not val:
            self.config['buttons'] = []
            return await interaction.response.edit_message(embed=self.view.build_embed())
        try:
            buttons_data = json.loads(val)
            if not isinstance(buttons_data, list):
                raise ValueError
            self.config['buttons'] = buttons_data
            await interaction.response.edit_message(embed=self.view.build_embed())
        except (json.JSONDecodeError, ValueError):
            await interaction.response.send_message("Format JSON tidak valid. Pastikan menggunakan format Array (kurung siku).", ephemeral=True)

class ButtonBuilderModal(discord.ui.Modal, title='Wizard Tambah Tombol'):
    def __init__(self, config, view):
        super().__init__()
        self.config = config
        self.view = view
        self.label_input = discord.ui.TextInput(label='Teks Tombol', placeholder='Misal: Buka Web', max_length=80)
        self.style_input = discord.ui.TextInput(label='Warna (blurple/green/red/grey)', default='blurple', max_length=20)
        self.action_input = discord.ui.TextInput(label='Aksi (role/ticket/channel/url)', placeholder='Misal: url', max_length=50)
        self.value_input = discord.ui.TextInput(label='ID Target / Link URL', placeholder='ID Angka / https://...', max_length=500)
        self.add_item(self.label_input)
        self.add_item(self.style_input)
        self.add_item(self.action_input)
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        style_val = self.style_input.value.strip().lower()
        if style_val not in ['blurple', 'green', 'red', 'grey']:
            style_val = 'blurple'
        action_val = self.action_input.value.strip().lower()
        new_btn = {
            "label": self.label_input.value.strip(),
            "style": style_val,
            "action": action_val,
            "value": self.value_input.value.strip()
        }
        if 'buttons' not in self.config or not isinstance(self.config['buttons'], list):
            self.config['buttons'] = []
        self.config['buttons'].append(new_btn)
        await interaction.response.edit_message(embed=self.view.build_embed())

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
            default=config.get('color', ''),
            required=False
        )
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        color_str = self.color_input.value.strip()
        try:
            if color_str:
                if not color_str.startswith('#'):
                    color_str = '#' + color_str
                int(color_str.replace('#', ''), 16)
            self.config['color'] = color_str or None
            await interaction.response.edit_message(embed=self.view.build_embed())
            await self.color_message.delete()
        except ValueError:
            await interaction.response.send_message("Kode warna tidak valid.", ephemeral=True)

class ColorView(discord.ui.View):
    def __init__(self, config, parent_view):
        super().__init__(timeout=60)
        self.config = config
        self.parent_view = parent_view
        colors = [
            ("Biru", "#3498DB"), ("Merah", "#E74C3C"), ("Hijau", "#2ECC71"),
            ("Emas", "#F1C40F"), ("Ungu", "#9B59B6"), ("Oranye", "#E67E22"),
            ("Abu-abu", "#95A5A6"), ("Biru Tua", "#0000FF"), ("Cyan", "#00FFFF"),
            ("Merah Tua", "#8B0000"), ("Hijau Tua", "#006400"), ("Coklat", "#A52A2A")
        ]
        for label, hex_val in colors:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            btn.callback = self.make_callback(hex_val)
            self.add_item(btn)

    def make_callback(self, hex_val):
        async def callback(interaction: discord.Interaction):
            self.config['color'] = hex_val
            await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
            self.stop()
        return callback
        
    @discord.ui.button(label="Pilih Kustom", style=discord.ButtonStyle.primary)
    async def custom_color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ColorModal(self.config, self.parent_view, interaction.message))
        self.stop()
        
    async def on_timeout(self):
        if self.message:
            try: await self.message.delete()
            except: pass

class SaveConfigModal(discord.ui.Modal, title='Simpan Konfigurasi'):
    def __init__(self, config, cog, target_channel):
        super().__init__()
        self.config = config
        self.cog = cog
        self.target_channel = target_channel
        self.name_input = discord.ui.TextInput(
            label='Nama Konfigurasi',
            placeholder='e.g., "Pesan Selamat Datang"',
            required=True
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        config_name = self.name_input.value
        self.cog.save_config_to_file(self.target_channel.guild.id, self.target_channel.id, config_name, self.config)
        await interaction.response.send_message(f"Konfigurasi '{config_name}' berhasil disimpan!", ephemeral=True)

class WebhookConfigView(discord.ui.View):
    def __init__(self, bot, channel: discord.TextChannel, initial_config=None):
        super().__init__(timeout=600)
        self.bot = bot
        self.channel = channel
        self.config = initial_config or {}

    def build_embed(self):
        embed = discord.Embed(
            title="Konfigurasi Pesan Webhook",
            description=f"Target: {self.channel.mention} di {self.channel.guild.name}",
            color=0x2b2d31
        )
        embed.add_field(name="Judul", value=f"`{truncate_text(self.config.get('title'))}`", inline=False)
        embed.add_field(name="Deskripsi", value=f"`{truncate_text(self.config.get('desc'))}`", inline=False)
        embed.add_field(name="Warna", value=f"`{truncate_text(self.config.get('color'))}`", inline=False)
        embed.add_field(name="Pengirim", value=f"`{truncate_text(self.config.get('author'))}`", inline=False)
        embed.add_field(name="Foto Pengirim", value=f"`{truncate_text(self.config.get('avatar'))}`", inline=False)
        embed.add_field(name="Tombol", value=f"`{len(self.config.get('buttons', []))} tombol`", inline=False)
        return embed

    @discord.ui.button(label="Judul & Deskripsi", style=discord.ButtonStyle.blurple, row=0)
    async def title_desc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class TitleDescModal(discord.ui.Modal, title="Judul & Deskripsi"):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.title_input = discord.ui.TextInput(label="Judul Embed", default=config.get('title', ''), required=False, max_length=256)
                self.desc_input = discord.ui.TextInput(label="Deskripsi Embed", style=discord.TextStyle.paragraph, default=config.get('desc', ''), required=False, max_length=4000)
                self.add_item(self.title_input)
                self.add_item(self.desc_input)
            
            async def on_submit(self, interaction: discord.Interaction):
                self.config['title'] = self.title_input.value or None
                self.config['desc'] = self.desc_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())
        
        await interaction.response.send_modal(TitleDescModal(self.config, self))

    @discord.ui.button(label="Warna", style=discord.ButtonStyle.blurple, row=0)
    async def color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=ColorView(self.config, self))

    @discord.ui.button(label="Pesan Teks Biasa", style=discord.ButtonStyle.blurple, row=0)
    async def content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextModal('content', self.config, self))

    @discord.ui.button(label="Pengirim", style=discord.ButtonStyle.blurple, row=0)
    async def author_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextModal('author', self.config, self))

    @discord.ui.button(label="Foto Pengirim", style=discord.ButtonStyle.blurple, row=0)
    async def avatar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextModal('avatar', self.config, self))

    @discord.ui.button(label="Tambah Tombol (+)", style=discord.ButtonStyle.green, row=1)
    async def add_btn_wizard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ButtonBuilderModal(self.config, self))

    @discord.ui.button(label="Edit JSON Tombol", style=discord.ButtonStyle.secondary, row=1)
    async def buttons_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ButtonsModal(self.config, self))

    @discord.ui.button(label="Hapus Semua Tombol", style=discord.ButtonStyle.red, row=1)
    async def clear_btns(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.config['buttons'] = []
        await interaction.response.edit_message(embed=self.build_embed())

    @discord.ui.button(label="Simpan Konfigurasi", style=discord.ButtonStyle.secondary, row=2)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SaveConfigModal(self.config, self.bot.get_cog('WebhookCog'), self.channel))

    @discord.ui.button(label="Kirim Webhook", style=discord.ButtonStyle.green, row=2)
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed = None
        if self.config.get('title') or self.config.get('desc') or self.config.get('color'):
            try:
                color = int(self.config['color'].replace('#', ''), 16) if self.config.get('color') else 0x2b2d31
                embed = discord.Embed(title=self.config.get('title'), description=self.config.get('desc'), color=color)
            except (ValueError, TypeError):
                return await interaction.followup.send("Format warna tidak valid. Pesan tidak dikirim.", ephemeral=True)

        webhook = discord.utils.get(await self.channel.webhooks(), name="Webhook Bot")
        if not webhook:
            try: webhook = await self.channel.create_webhook(name="Webhook Bot")
            except discord.Forbidden: return await interaction.followup.send("Gagal membuat webhook. Pastikan bot memiliki izin Manage Webhooks di channel tujuan.", ephemeral=True)

        view = None
        buttons_data = self.config.get('buttons', [])
        if buttons_data:
            try:
                actions_map = {}
                for btn_data in buttons_data:
                    if btn_data.get('action') != 'url':
                        btn_id = btn_data.get('id') or str(uuid.uuid4())
                        btn_data['id'] = btn_id
                        actions_map[btn_id] = {'action': btn_data.get('action'), 'value': btn_data.get('value')}
                self.bot.get_cog('WebhookCog').button_actions.update(actions_map)
                view = WebhookButtonView(buttons_data)
            except Exception:
                return await interaction.followup.send("Gagal membuat tombol. Mohon periksa format JSON.", ephemeral=True)

        payload = {
            'content': self.config.get('content'),
            'username': self.config.get('author') or self.bot.user.name,
            'avatar_url': self.config.get('avatar') or self.bot.user.display_avatar.url,
            'embeds': [embed] if embed else [],
            'wait': True
        }
        if view:
            payload['view'] = view

        try:
            sent_message = await webhook.send(**payload)
            if sent_message:
                config_name = str(sent_message.id)
                self.bot.get_cog('WebhookCog').save_config_to_file(self.channel.guild.id, self.channel.id, config_name, self.config)
                await interaction.followup.send(f"Pesan webhook berhasil dikirim ke {self.channel.mention}!", ephemeral=True)
            try: await interaction.message.delete()
            except: pass
        except Exception as e:
            await interaction.followup.send(f"Gagal mengirim pesan: {e}", ephemeral=True)
            
    @discord.ui.button(label="Batalkan", style=discord.ButtonStyle.red, row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try: await interaction.message.delete()
        except: pass
        self.stop()
        
class WebhookButtonView(discord.ui.View):
    def __init__(self, buttons_data):
        super().__init__(timeout=None)
        for data in buttons_data:
            self.add_item(self.create_button(data))

    def create_button(self, data):
        action = data.get('action')
        label = data.get('label', 'Tombol')
        
        if action == 'url':
            return discord.ui.Button(label=label, url=data.get('value'))
            
        style_map = {
            'blurple': discord.ButtonStyle.blurple,
            'red': discord.ButtonStyle.red,
            'green': discord.ButtonStyle.green,
            'grey': discord.ButtonStyle.grey,
        }
        style = style_map.get(data.get('style', 'blurple'), discord.ButtonStyle.blurple)
        return discord.ui.Button(label=label, style=style, custom_id=data['id'])

class AnnouncementConfigView(discord.ui.View):
    def __init__(self, bot, channel: discord.TextChannel, initial_config=None):
        super().__init__(timeout=600)
        self.bot = bot
        self.channel = channel
        self.config = initial_config or {}

    def build_embed(self):
        embed = discord.Embed(
            title="Konfigurasi Pesan Pengumuman",
            description=f"Target: {self.channel.mention} di {self.channel.guild.name}",
            color=0x2b2d31
        )
        embed.add_field(name="Judul", value=f"`{truncate_text(self.config.get('title'))}`", inline=False)
        embed.add_field(name="Deskripsi", value=f"`{truncate_text(self.config.get('desc'))}`", inline=False)
        embed.add_field(name="Warna", value=f"`{truncate_text(self.config.get('color'))}`", inline=False)
        embed.add_field(name="Pesan Teks", value=f"`{truncate_text(self.config.get('content'))}`", inline=False)
        embed.add_field(name="Media URL", value=f"`{truncate_text(self.config.get('media_url'))}`", inline=False)
        return embed

    @discord.ui.button(label="Judul & Deskripsi", style=discord.ButtonStyle.blurple)
    async def title_desc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class TitleDescModal(discord.ui.Modal, title="Judul & Deskripsi"):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.title_input = discord.ui.TextInput(label="Judul Embed", default=config.get('title', ''), required=False, max_length=256)
                self.desc_input = discord.ui.TextInput(label="Deskripsi Embed", style=discord.TextStyle.paragraph, default=config.get('desc', ''), required=False, max_length=4000)
                self.add_item(self.title_input)
                self.add_item(self.desc_input)
            
            async def on_submit(self, interaction: discord.Interaction):
                self.config['title'] = self.title_input.value or None
                self.config['desc'] = self.desc_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())
        
        await interaction.response.send_modal(TitleDescModal(self.config, self))

    @discord.ui.button(label="Pesan Teks Biasa", style=discord.ButtonStyle.blurple)
    async def content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ContentModal(discord.ui.Modal, title='Teks Pesan'):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.text_input = discord.ui.TextInput(label='Teks Pesan Biasa', style=discord.TextStyle.paragraph, default=config.get('content', ''), required=False, max_length=4000)
                self.add_item(self.text_input)

            async def on_submit(self, interaction: discord.Interaction):
                self.config['content'] = self.text_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())
        
        await interaction.response.send_modal(ContentModal(self.config, self))
        
    @discord.ui.button(label="Media (URL)", style=discord.ButtonStyle.blurple)
    async def media_url_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class MediaUrlModal(discord.ui.Modal, title='URL Media'):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.url_input = discord.ui.TextInput(label='URL', placeholder='https://...', default=config.get('media_url', ''), required=False)
                self.add_item(self.url_input)

            async def on_submit(self, interaction: discord.Interaction):
                self.config['media_url'] = self.url_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())

        await interaction.response.send_modal(MediaUrlModal(self.config, self))

    @discord.ui.button(label="Warna", style=discord.ButtonStyle.blurple)
    async def color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=ColorView(self.config, self))
        
    @discord.ui.button(label="Kirim Pengumuman", style=discord.ButtonStyle.green, row=1)
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embed = None
        if self.config.get('title') or self.config.get('desc') or self.config.get('color') or self.config.get('media_url'):
            try:
                color = int(self.config['color'].replace('#', ''), 16) if self.config.get('color') else 0x2b2d31
                embed = discord.Embed(title=self.config.get('title'), description=self.config.get('desc'), color=color)
                if self.config.get('media_url'): embed.set_image(url=self.config['media_url'])
            except (ValueError, TypeError):
                return await interaction.followup.send("Format warna tidak valid.", ephemeral=True)

        try:
            msg = await self.channel.send(content=self.config.get('content'), embeds=[embed] if embed else [])
            self.bot.get_cog('WebhookCog').save_config_to_file(self.channel.guild.id, self.channel.id, str(msg.id), self.config)
            await interaction.followup.send(f"Pengumuman terkirim ke {self.channel.mention}!", ephemeral=True)
            try: await interaction.message.delete()
            except: pass
        except Exception as e:
            await interaction.followup.send(f"Gagal mengirim: {e}", ephemeral=True)

    @discord.ui.button(label="Batalkan", style=discord.ButtonStyle.red, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try: await interaction.message.delete()
        except: pass
        self.stop()
        
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
            placeholder='15:30',
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.time_input)

        self.channel_input = discord.ui.TextInput(
            label='ID Kanal Tujuan',
            placeholder='Masukkan ID Kanal Server',
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
            if scheduled_datetime_wib < now_wib - timedelta(minutes=5):
                return await interaction.response.send_message("Waktu harus di masa mendatang.", ephemeral=True)
            
            self.config['scheduled_time'] = scheduled_datetime_wib.isoformat()
            
            try:
                channel_id = int(re.sub(r'\D', '', self.channel_input.value))
                channel = interaction.client.get_channel(channel_id)
                if not channel:
                    channel = await interaction.client.fetch_channel(channel_id)
                self.config['channel_id'] = channel.id
                self.config['guild_id'] = channel.guild.id
            except Exception:
                return await interaction.response.send_message("ID kanal tidak valid atau bot tidak memiliki akses ke kanal tersebut.", ephemeral=True)

            await interaction.response.edit_message(embed=self.view.build_embed())
        except ValueError:
            await interaction.response.send_message("Format tanggal atau waktu tidak valid.", ephemeral=True)

class ScheduleConfigView(discord.ui.View):
    def __init__(self, bot, initial_config=None):
        super().__init__(timeout=600)
        self.bot = bot
        self.config = initial_config or {}

    def build_embed(self):
        embed = discord.Embed(
            title="Konfigurasi Pengumuman Berjadwal",
            description="Atur pesan dan jadwal pengumuman di sini.",
            color=0x2b2d31
        )
        
        sch_time = self.config.get('scheduled_time')
        sch_display = datetime.fromisoformat(sch_time).astimezone(pytz.timezone('Asia/Jakarta')).strftime('%d %B %Y, %H:%M WIB') if sch_time else "Belum diatur"

        c_id = self.config.get('channel_id')
        channel = self.bot.get_channel(c_id) if c_id else None
        ch_display = f"{channel.mention} ({channel.guild.name})" if channel else (f"ID: {c_id}" if c_id else "Belum diatur")

        embed.add_field(name="Waktu Terjadwal", value=f"`{sch_display}`", inline=False)
        embed.add_field(name="Kanal Tujuan", value=ch_display, inline=False)
        embed.add_field(name="Judul Embed", value=f"`{truncate_text(self.config.get('title'))}`", inline=False)
        embed.add_field(name="Deskripsi Embed", value=f"`{truncate_text(self.config.get('desc'))}`", inline=False)
        embed.add_field(name="Warna", value=f"`{truncate_text(self.config.get('color'))}`", inline=False)
        embed.add_field(name="Pesan Teks", value=f"`{truncate_text(self.config.get('content'))}`", inline=False)
        embed.add_field(name="Media (URL)", value=f"`{truncate_text(self.config.get('media_url'))}`", inline=False)
        
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
                self.title_input = discord.ui.TextInput(label="Judul Embed", default=config.get('title', ''), required=False, max_length=256)
                self.desc_input = discord.ui.TextInput(label="Deskripsi Embed", style=discord.TextStyle.paragraph, default=config.get('desc', ''), required=False, max_length=4000)
                self.add_item(self.title_input)
                self.add_item(self.desc_input)
            
            async def on_submit(self, interaction: discord.Interaction):
                self.config['title'] = self.title_input.value or None
                self.config['desc'] = self.desc_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())
        
        await interaction.response.send_modal(TitleDescModal(self.config, self))

    @discord.ui.button(label="Pesan Teks", style=discord.ButtonStyle.blurple, row=1)
    async def content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ContentModal(discord.ui.Modal, title='Teks Pesan'):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.text_input = discord.ui.TextInput(label='Teks Pesan Biasa', style=discord.TextStyle.paragraph, default=config.get('content', ''), required=False, max_length=4000)
                self.add_item(self.text_input)

            async def on_submit(self, interaction: discord.Interaction):
                self.config['content'] = self.text_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())
        
        await interaction.response.send_modal(ContentModal(self.config, self))
        
    @discord.ui.button(label="Media URL", style=discord.ButtonStyle.blurple, row=1)
    async def media_url_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class MediaUrlModal(discord.ui.Modal, title='URL Media'):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.url_input = discord.ui.TextInput(label='URL', placeholder='https://...', default=config.get('media_url', ''), required=False)
                self.add_item(self.url_input)

            async def on_submit(self, interaction: discord.Interaction):
                self.config['media_url'] = self.url_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())

        await interaction.response.send_modal(MediaUrlModal(self.config, self))

    @discord.ui.button(label="Warna", style=discord.ButtonStyle.blurple, row=1)
    async def color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=ColorView(self.config, self))
        
    @discord.ui.button(label="Jadwalkan", style=discord.ButtonStyle.green, row=2)
    async def schedule_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not self.config.get('scheduled_time') or not self.config.get('channel_id'):
            return await interaction.followup.send("Tentukan jadwal dan kanal tujuan terlebih dahulu.", ephemeral=True)
        if not self.config.get('content') and not self.config.get('title') and not self.config.get('media_url'):
            return await interaction.followup.send("Pesan harus memiliki konten, judul, atau media URL.", ephemeral=True)

        scheduled_announcements = self.bot.get_cog('WebhookCog').load_scheduled_announcements()
        job_id = str(uuid.uuid4())
        job_data = {
            'guild_id': self.config['guild_id'],
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
        
        dt_wib = datetime.fromisoformat(self.config['scheduled_time']).astimezone(pytz.timezone('Asia/Jakarta'))
        channel = self.bot.get_channel(self.config['channel_id'])
        ch_str = channel.mention if channel else f"ID {self.config['channel_id']}"
        await interaction.followup.send(f"Pengumuman dijadwalkan ke {ch_str} pada **{dt_wib.strftime('%d %B %Y pukul %H:%M WIB')}**.", ephemeral=True)
        try: await interaction.message.delete()
        except: pass

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.red, row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try: await interaction.message.delete()
        except: pass
        self.stop()

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
        self.single_role_file = os.path.join(self.data_dir, 'single_role_messages.json')
        self.single_role_messages = self.load_single_role_messages()

    @commands.Cog.listener()
    async def on_ready(self):
        self._load_all_button_actions()

    async def get_target_channel(self, ctx, identifier):
        if not identifier:
            return ctx.channel
        try:
            channel_id = int(re.sub(r'\D', '', str(identifier)))
            channel = self.bot.get_channel(channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(channel_id)
            return channel
        except Exception:
            return None

    async def check_scheduled_announcements(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                schedules = self.load_scheduled_announcements()
                now_wib = datetime.now(self.wib_timezone)
                tasks_to_remove = []

                for job_id, job_data in list(schedules.items()):
                    sch_wib = datetime.fromisoformat(job_data['scheduled_time']).astimezone(self.wib_timezone)
                    if now_wib >= sch_wib:
                        channel = self.bot.get_channel(job_data['channel_id'])
                        if not channel:
                            try: channel = await self.bot.fetch_channel(job_data['channel_id'])
                            except:
                                tasks_to_remove.append(job_id)
                                continue

                        embed = None
                        if job_data.get('title') or job_data.get('desc') or job_data.get('media_url') or job_data.get('color'):
                            try:
                                color = int(job_data['color'].replace('#', ''), 16) if job_data.get('color') else 0x2b2d31
                                embed = discord.Embed(title=job_data.get('title'), description=job_data.get('desc'), color=color)
                                if job_data.get('media_url'):
                                    embed.set_image(url=job_data['media_url'])
                            except: pass

                        try:
                            await channel.send(content=job_data.get('content'), embeds=[embed] if embed else [])
                        except Exception: pass
                        tasks_to_remove.append(job_id)

                if tasks_to_remove:
                    self.remove_scheduled_announcements(tasks_to_remove)
            except Exception: pass
            await asyncio.sleep(60)

    def load_scheduled_announcements(self):
        if not os.path.exists(self.scheduled_announcements_file): return {}
        try:
            with open(self.scheduled_announcements_file, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}

    def save_scheduled_announcements(self, data):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.scheduled_announcements_file, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)

    def remove_scheduled_announcements(self, ids):
        schedules = self.load_scheduled_announcements()
        for jid in ids: schedules.pop(jid, None)
        self.save_scheduled_announcements(schedules)

    def _load_all_button_actions(self):
        if not os.path.exists(self.config_file): return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f: all_configs = json.load(f)
            for g in all_configs.values():
                for c in g.values():
                    for conf in c.values():
                        for btn in conf.get('buttons', []):
                            if btn.get('id'):
                                self.button_actions[btn['id']] = {'action': btn.get('action'), 'value': btn.get('value')}
        except: pass

    def save_config_to_file(self, guild_id, channel_id, config_name, config_data):
        os.makedirs(self.data_dir, exist_ok=True)
        all_configs = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f: all_configs = json.load(f)
            except: pass
        
        g_id, c_id = str(guild_id), str(channel_id)
        if g_id not in all_configs: all_configs[g_id] = {}
        if c_id not in all_configs[g_id]: all_configs[g_id][c_id] = {}
        all_configs[g_id][c_id][config_name] = config_data
        
        with open(self.config_file, 'w', encoding='utf-8') as f: json.dump(all_configs, f, indent=4)

    def load_single_role_messages(self):
        if not os.path.exists(self.single_role_file): return {} 
        try:
            with open(self.single_role_file, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}

    def save_single_role_messages(self):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.single_role_file, 'w', encoding='utf-8') as f: json.dump(self.single_role_messages, f, indent=4)

    @commands.command(aliases=['swh'])
    @commands.has_permissions(manage_webhooks=True)
    async def send_webhook(self, ctx, channel_id: str = None):
        try: await ctx.message.delete()
        except: pass
        target = await self.get_target_channel(ctx, channel_id)
        if not target or not isinstance(target, discord.TextChannel):
            return await ctx.send("Kanal tidak valid atau bot tidak memiliki akses.", ephemeral=True, delete_after=5)
        view = WebhookConfigView(self.bot, target)
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(name='announcement')
    @commands.has_permissions(manage_messages=True)
    async def announcement(self, ctx, channel_id: str = None):
        try: await ctx.message.delete()
        except: pass
        target = await self.get_target_channel(ctx, channel_id)
        if not target or not isinstance(target, discord.TextChannel):
            return await ctx.send("Kanal tidak valid.", ephemeral=True, delete_after=5)
        view = AnnouncementConfigView(self.bot, target)
        await ctx.send(embed=view.build_embed(), view=view)
    
    @commands.command(name='send_media')
    @commands.has_permissions(manage_messages=True)
    async def send_media(self, ctx, channel_id: str = None):
        if not ctx.message.reference:
            return await ctx.send("Silakan balas pesan yang berisi media.", ephemeral=True, delete_after=5)
        try:
            replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if not replied_message.attachments:
                return await ctx.send("Pesan tidak memiliki lampiran media.", ephemeral=True, delete_after=5)
            target = await self.get_target_channel(ctx, channel_id)
            if not target:
                return await ctx.send("Kanal tujuan tidak valid.", ephemeral=True, delete_after=5)
            for attachment in replied_message.attachments:
                file_to_send = await attachment.to_file()
                await target.send(content=replied_message.content, file=file_to_send)
            await ctx.send(f"Media terkirim ke {target.mention}!", ephemeral=True, delete_after=5)
            try: await ctx.message.delete()
            except: pass
        except Exception as e:
            await ctx.send(f"Gagal mengirim media: {e}", ephemeral=True, delete_after=10)
    
    @commands.command(name='schedule')
    @commands.has_permissions(manage_messages=True)
    async def schedule(self, ctx):
        try: await ctx.message.delete()
        except: pass
        view = ScheduleConfigView(self.bot)
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(name='list_schedules')
    @commands.has_permissions(manage_messages=True)
    async def list_schedules(self, ctx):
        schedules = self.load_scheduled_announcements()
        if not schedules:
            return await ctx.send("Tidak ada pengumuman berjadwal.", ephemeral=True, delete_after=10)
        embed = discord.Embed(title="Pengumuman Berjadwal", color=discord.Color.blue())
        for job_id, data in schedules.items():
            try:
                dt = datetime.fromisoformat(data['scheduled_time']).astimezone(self.wib_timezone)
                ch = self.bot.get_channel(data['channel_id'])
                ch_str = ch.mention if ch else f"ID: {data['channel_id']}"
                c_text = data.get('content') or data.get('title') or "Tanpa teks"
                embed.add_field(name=f"ID: {job_id[:8]}", value=f"**Waktu:** `{dt.strftime('%H:%M WIB, %d-%m-%Y')}`\n**Kanal:** {ch_str}\n**Info:** `{truncate_text(c_text, 60)}`", inline=False)
            except: pass
        await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name='load_config')
    @commands.has_permissions(manage_webhooks=True)
    async def load_config(self, ctx, config_name: str, channel_id: str = None):
        target = await self.get_target_channel(ctx, channel_id)
        if not target:
            return await ctx.send("Kanal tidak valid.", ephemeral=True)
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f: all_configs = json.load(f)
            config_data = all_configs[str(target.guild.id)][str(target.id)][config_name]
            view = WebhookConfigView(self.bot, target, initial_config=config_data)
            await ctx.send(embed=view.build_embed(), view=view)
        except Exception:
            await ctx.send("Konfigurasi tidak ditemukan.", ephemeral=True)

    @commands.command(name='backup_config')
    @commands.has_permissions(manage_webhooks=True)
    async def backup_config(self, ctx, message_id: int):
        try:
            msg = await ctx.channel.fetch_message(message_id)
            with open(self.config_file, 'r', encoding='utf-8') as f: all_configs = json.load(f)
            config_data = all_configs[str(ctx.guild.id)][str(ctx.channel.id)][str(msg.id)]
            
            osmakedirs(self.data_dir, exist_ok=True)
            backup_configs = {}
            if os.path.exists(self.backup_file):
                try:
                    with open(self.backup_file, 'r', encoding='utf-8') as f: backup_configs = json.load(f)
                except: pass
            
            g_id, c_id, m_id = str(ctx.guild.id), str(ctx.channel.id), str(msg.id)
            if g_id not in backup_configs: backup_configs[g_id] = {}
            if c_id not in backup_configs[g_id]: backup_configs[g_id][c_id] = {}
            backup_configs[g_id][c_id][m_id] = config_data
            
            with open(self.backup_file, 'w', encoding='utf-8') as f: json.dump(backup_configs, f, indent=4)
            await ctx.send(f"Pesan `{msg.id}` dicadangkan.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Gagal mencadangkan: {e}", ephemeral=True)

    @commands.command(name='list_configs')
    @commands.has_permissions(manage_webhooks=True)
    async def list_configs(self, ctx):
        if not ctx.guild: return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f: all_configs = json.load(f)
            g_configs = all_configs.get(str(ctx.guild.id))
            if not g_configs: raise ValueError
            embed = discord.Embed(title=f"Konfigurasi Tersimpan", color=discord.Color.blue())
            for c_id, configs in g_configs.items():
                ch = ctx.guild.get_channel(int(c_id))
                ch_name = ch.name if ch else str(c_id)
                c_list = "\n".join([f"`{n}`" for n in configs.keys()])
                if c_list: embed.add_field(name=f"#{ch_name}", value=c_list, inline=False)
            await ctx.send(embed=embed, ephemeral=True)
        except:
            await ctx.send("Tidak ada konfigurasi tersimpan.", ephemeral=True)

    @commands.command(name='set_single_role')
    @commands.has_permissions(manage_roles=True)
    async def set_single_role(self, ctx, message_id: int, channel_id: str = None):
        try: await ctx.message.delete()
        except: pass
        target = await self.get_target_channel(ctx, channel_id)
        if not target: return await ctx.send("Kanal tidak valid.", ephemeral=True)
        try:
            msg = await target.fetch_message(message_id)
            g_id, m_id = str(target.guild.id), str(msg.id)
            if g_id not in self.single_role_messages: self.single_role_messages[g_id] = []
            if m_id in self.single_role_messages[g_id]:
                self.single_role_messages[g_id].remove(m_id)
                status = "dihapus"
            else:
                self.single_role_messages[g_id].append(m_id)
                status = "diaktifkan"
            self.save_single_role_messages()
            await ctx.send(f"Single role pesan `{m_id}` {status}.", ephemeral=True)
        except Exception:
            await ctx.send("Pesan tidak ditemukan atau bot tidak memiliki akses.", ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component: return
        data = self.button_actions.get(interaction.data.get('custom_id'))
        if not data: return
        action, value = data.get('action'), data.get('value')
        
        if action == 'role':
            try:
                role_to_add = interaction.guild.get_role(int(value))
                if not role_to_add: return await interaction.response.send_message("Role hilang.", ephemeral=True)
                if role_to_add in interaction.user.roles:
                    return await interaction.response.send_message(f"Sudah memiliki role **{role_to_add.name}**.", ephemeral=True)
                
                is_single = str(interaction.guild.id) in self.single_role_messages and str(interaction.message.id) in self.single_role_messages[str(interaction.guild.id)]
                to_remove = []
                if is_single:
                    msg_role_ids = set()
                    for comp in interaction.message.components:
                        for child in comp.children:
                            btn_data = self.button_actions.get(child.custom_id)
                            if btn_data and btn_data.get('action') == 'role':
                                try: msg_role_ids.add(int(btn_data.get('value')))
                                except: pass
                    for r in interaction.user.roles:
                        if r.id in msg_role_ids and r.id != role_to_add.id:
                            to_remove.append(r)
                
                if to_remove: await interaction.user.remove_roles(*to_remove)
                await interaction.user.add_roles(role_to_add)
                await interaction.response.send_message(f"Role **{role_to_add.name}** ditambahkan!", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)
                
        elif action == 'ticket':
            cfg = value if isinstance(value, dict) else {'category_id': value, 'allowed_roles': [], 'blocked_roles': []}
            cat_id = int(cfg.get('category_id')) if cfg.get('category_id') else None
            allowed = [int(r) for r in cfg.get('allowed_roles', [])]
            blocked = [int(r) for r in cfg.get('blocked_roles', [])]
            u_roles = [r.id for r in interaction.user.roles]

            if any(r in blocked for r in u_roles): return await interaction.response.send_message("Akses ditolak.", ephemeral=True)
            if allowed and not any(r in allowed for r in u_roles): return await interaction.response.send_message("Akses ditolak.", ephemeral=True)
            if interaction.user.id in self.active_tickets: return await interaction.response.send_message("Tiket aktif sudah ada.", ephemeral=True)

            await interaction.response.defer(ephemeral=True)
            category = interaction.guild.get_channel(cat_id) if cat_id else None
            specific_role = interaction.guild.get_role(1264935423184998422)

            ow = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            if specific_role: ow[specific_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            tc = await interaction.guild.create_text_channel(f"ticket-{interaction.user.name.lower()}", overwrites=ow, category=category)
            cid = str(uuid.uuid4())
            self.button_actions[cid] = {'action': 'close_ticket', 'value': str(interaction.user.id)}
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="Tutup Tiket", style=discord.ButtonStyle.red, custom_id=cid))
            m_str = specific_role.mention if specific_role else ""
            await tc.send(f"Tiket dari {interaction.user.mention} {m_str}", view=view)
            await interaction.followup.send(f"Tiket: {tc.mention}", ephemeral=True)
            self.active_tickets[interaction.user.id] = tc.id
            self.bot.loop.create_task(self.delete_ticket_after_delay(tc, interaction.user.id))

        elif action == 'close_ticket':
            await interaction.response.defer()
            uid = int(value)
            if uid in self.active_tickets: del self.active_tickets[uid]
            try: await interaction.channel.delete()
            except: pass
            
        elif action == 'channel':
            try:
                tc = interaction.guild.get_channel(int(value))
                if tc:
                    await tc.set_permissions(interaction.user, view_channel=True)
                    await interaction.response.send_message(f"Akses ke {tc.mention} dibuka!", ephemeral=True)
            except:
                await interaction.response.send_message("Gagal akses kanal.", ephemeral=True)

    async def delete_ticket_after_delay(self, channel, user_id):
        await asyncio.sleep(3600)
        if user_id in self.active_tickets and self.active_tickets[user_id] == channel.id:
            replied = False
            async for msg in channel.history(limit=50):
                if msg.author.guild_permissions.manage_channels and msg.author.id != self.bot.user.id:
                    replied = True
                    break
            if not replied:
                try: await channel.delete()
                except: pass
                if user_id in self.active_tickets: del self.active_tickets[user_id]

async def setup(bot):
    await bot.add_cog(WebhookCog(bot))
