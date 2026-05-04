import discord
from discord.ext import commands, tasks
import json
import uuid
import asyncio
import os
from datetime import datetime, timedelta
import logging
import pytz
import re
import google.generativeai as genai

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

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
            await interaction.response.send_message("Format JSON tidak valid.", ephemeral=True)

class DropdownModal(discord.ui.Modal, title='Edit JSON Dropdown'):
    def __init__(self, config, view):
        super().__init__()
        self.config = config
        self.view = view
        self.drops_input = discord.ui.TextInput(
            label='Data Dropdown (JSON)',
            style=discord.TextStyle.paragraph,
            placeholder='[{"placeholder": "Pilih", "options": [{"label": "A", "value": "1", "action": "role"}]}]',
            default=json.dumps(config.get('dropdowns', []), indent=2),
            required=False
        )
        self.add_item(self.drops_input)

    async def on_submit(self, interaction: discord.Interaction):
        val = self.drops_input.value.strip()
        if not val:
            self.config['dropdowns'] = []
            return await interaction.response.edit_message(embed=self.view.build_embed())
        try:
            drops_data = json.loads(val)
            if not isinstance(drops_data, list):
                raise ValueError
            self.config['dropdowns'] = drops_data
            await interaction.response.edit_message(embed=self.view.build_embed())
        except (json.JSONDecodeError, ValueError):
            await interaction.response.send_message("Format JSON tidak valid.", ephemeral=True)

class AIWriterModal(discord.ui.Modal, title='AI Auto-Writer'):
    def __init__(self, config, view):
        super().__init__()
        self.config = config
        self.view = view
        self.prompt_input = discord.ui.TextInput(
            label='Perintah untuk AI',
            style=discord.TextStyle.paragraph,
            placeholder='Bikinin pengumuman mabar nanti malam jam 8 bahasa tongkrongan...',
            required=True
        )
        self.add_item(self.prompt_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            prompt = f"Buatkan pengumuman Discord: {self.prompt_input.value}. Balas HANYA dengan JSON murni tanpa format markdown: {{\"title\": \"Judul\", \"desc\": \"Deskripsi embed panjang\", \"content\": \"Teks biasa opsional\", \"color\": \"#HexColorTerkaitTema\"}}"
            res = await model.generate_content_async(prompt)
            clean_json = res.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(clean_json)
            self.config.update(data)
            await interaction.message.edit(embed=self.view.build_embed())
            await interaction.followup.send("AI berhasil merakit pengumuman!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Gagal pakai AI: {e}", ephemeral=True)

class DestructModal(discord.ui.Modal, title='Auto-Hapus (Self Destruct)'):
    def __init__(self, config, view):
        super().__init__()
        self.config = config
        self.view = view
        self.min_input = discord.ui.TextInput(
            label='Menit',
            placeholder='Misal: 60',
            default=str(config.get('destruct', '')),
            required=False
        )
        self.add_item(self.min_input)

    async def on_submit(self, interaction: discord.Interaction):
        val = self.min_input.value.strip()
        if val.isdigit():
            self.config['destruct'] = int(val)
        else:
            self.config['destruct'] = None
        await interaction.response.edit_message(embed=self.view.build_embed())

class ButtonBuilderModal(discord.ui.Modal, title='Wizard Tambah Tombol'):
    def __init__(self, config, view):
        super().__init__()
        self.config = config
        self.view = view
        self.label_input = discord.ui.TextInput(label='Teks Tombol', placeholder='Misal: Buka Web', max_length=80)
        self.style_input = discord.ui.TextInput(label='Warna (blurple/green/red/grey)', default='blurple', max_length=20)
        self.action_input = discord.ui.TextInput(label='Aksi (role/ticket/channel/url/translate)', placeholder='Misal: url', max_length=50)
        self.value_input = discord.ui.TextInput(label='ID Target / Link URL / Bahasa', placeholder='ID Angka / https://... / English', max_length=500)
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

class InteractiveView(discord.ui.View):
    def __init__(self, config):
        super().__init__(timeout=None)
        for b in config.get('buttons', []):
            if b.get('action') == 'url':
                self.add_item(discord.ui.Button(label=b.get('label'), url=b.get('value')))
            else:
                style = {'blurple': discord.ButtonStyle.blurple, 'green': discord.ButtonStyle.green, 'red': discord.ButtonStyle.red, 'grey': discord.ButtonStyle.grey}.get(b.get('style'), discord.ButtonStyle.blurple)
                self.add_item(discord.ui.Button(label=b.get('label'), style=style, custom_id=b.get('id')))
        
        for d in config.get('dropdowns', []):
            opts = [discord.SelectOption(label=o['label'], value=o['value']) for o in d.get('options', [])]
            if opts:
                sel = discord.ui.Select(custom_id=d.get('id'), placeholder=d.get('placeholder', 'Pilih...'), options=opts)
                self.add_item(sel)

class WebhookConfigView(discord.ui.View):
    def __init__(self, bot, channels, initial_config=None, msg_id_to_edit=None):
        super().__init__(timeout=600)
        self.bot = bot
        self.channels = channels
        self.config = initial_config or {}
        self.msg_id_to_edit = msg_id_to_edit
        self.config.setdefault('pin', False)
        self.config.setdefault('lock', False)

    def build_embed(self):
        ch_mentions = " ".join([ch.mention for ch in self.channels][:5])
        if len(self.channels) > 5: ch_mentions += f" (+{len(self.channels)-5} lainnya)"
        
        mode_text = f"EDIT PESAN ID: {self.msg_id_to_edit}" if self.msg_id_to_edit else "BUAT BARU"
        embed = discord.Embed(
            title=f"Konfigurasi Pesan | {mode_text}",
            description=f"Target: {ch_mentions}",
            color=0x2b2d31
        )
        embed.add_field(name="Judul", value=f"`{truncate_text(self.config.get('title'))}`", inline=False)
        embed.add_field(name="Deskripsi", value=f"`{truncate_text(self.config.get('desc'))}`", inline=False)
        embed.add_field(name="Warna", value=f"`{truncate_text(self.config.get('color'))}`", inline=False)
        embed.add_field(name="Pengirim", value=f"`{truncate_text(self.config.get('author'))}`", inline=False)
        embed.add_field(name="Foto Pengirim", value=f"`{truncate_text(self.config.get('avatar'))}`", inline=False)
        embed.add_field(name="Interaktif", value=f"Tombol: `{len(self.config.get('buttons', []))}` | Dropdown: `{len(self.config.get('dropdowns', []))}`", inline=False)
        
        pin_lock = f"Pin: {'✅' if self.config['pin'] else '❌'} | Lock: {'✅' if self.config['lock'] else '❌'}"
        destruct = f"💣 Auto-Hapus: {self.config['destruct']} Menit" if self.config.get('destruct') else "💣 Auto-Hapus: ❌"
        embed.add_field(name="Ekstra", value=f"{pin_lock}\n{destruct}", inline=False)
        
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

    @discord.ui.button(label="🤖 AI Auto-Writer", style=discord.ButtonStyle.primary, row=1)
    async def ai_writer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AIWriterModal(self.config, self))

    @discord.ui.button(label="Tambah Tombol (+)", style=discord.ButtonStyle.green, row=1)
    async def add_btn_wizard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ButtonBuilderModal(self.config, self))

    @discord.ui.button(label="JSON Tombol", style=discord.ButtonStyle.secondary, row=1)
    async def buttons_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ButtonsModal(self.config, self))
        
    @discord.ui.button(label="JSON Dropdown", style=discord.ButtonStyle.secondary, row=1)
    async def drops_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DropdownModal(self.config, self))

    @discord.ui.button(label="Hapus Tombol & Menu", style=discord.ButtonStyle.red, row=1)
    async def clear_btns(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.config['buttons'] = []
        self.config['dropdowns'] = []
        await interaction.response.edit_message(embed=self.build_embed())

    @discord.ui.button(label="Toggle Pin & Lock", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_pin_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.config['pin'] = not self.config['pin']
        self.config['lock'] = not self.config['lock']
        await interaction.response.edit_message(embed=self.build_embed())

    @discord.ui.button(label="💣 Auto-Hapus", style=discord.ButtonStyle.secondary, row=2)
    async def destruct_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DestructModal(self.config, self))

    @discord.ui.button(label="Preview (Sini Aja)", style=discord.ButtonStyle.secondary, row=2)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cog_instance = self.bot.get_cog('RTMBroadcast')
        payload, view = cog_instance.build_payload(self.config, self.bot)
        
        preview_kwargs = {}
        content_header = "👀 **[PREVIEW PESAN]**\n"
        
        if payload.get('content'):
            preview_kwargs['content'] = content_header + payload['content']
        else:
            preview_kwargs['content'] = content_header
            
        if payload.get('embeds'):
            preview_kwargs['embeds'] = payload['embeds']
            
        if view:
            preview_kwargs['view'] = view
            
        try:
            await interaction.followup.send(**preview_kwargs, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Gagal nampilin preview: {e}", ephemeral=True)

    @discord.ui.button(label="Simpan Konfig", style=discord.ButtonStyle.grey, row=2)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SaveConfigModal(self.config, self.bot.get_cog('RTMBroadcast'), self.channels[0]))

    @discord.ui.button(label="Kirim Webhook", style=discord.ButtonStyle.green, row=2)
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cog = self.bot.get_cog('RTMBroadcast')

        success_count = 0
        errors_log = []
        
        for ch in self.channels:
            try:
                payload, view = cog.build_payload(self.config, self.bot)
                
                if self.msg_id_to_edit:
                    try:
                        msg = await ch.fetch_message(self.msg_id_to_edit)
                        edit_payload = {}
                        if 'content' in payload:
                            edit_payload['content'] = payload['content']
                        if 'embeds' in payload:
                            edit_payload['embeds'] = payload['embeds']
                        if view:
                            edit_payload['view'] = view
                            
                        await msg.edit(**edit_payload)
                        success_count += 1
                        continue
                    except Exception as e:
                        errors_log.append(f"Gagal edit di {ch.name}: {str(e)}")
                        continue

                webhook = discord.utils.get(await ch.webhooks(), name="RTMBroadcast")
                if not webhook:
                    webhook = await ch.create_webhook(name="RTMBroadcast")

                sent_msg = await webhook.send(wait=True, **payload)
                if sent_msg:
                    success_count += 1
                    cog.save_config_to_file(ch.guild.id, ch.id, str(sent_msg.id), self.config)
                    
                    if self.config.get('pin'):
                        try:
                            await sent_msg.pin()
                        except Exception:
                            pass
                            
                    if self.config.get('lock'):
                        try:
                            await ch.set_permissions(ch.guild.default_role, send_messages=False)
                        except Exception:
                            pass
                            
                    if self.config.get('destruct'):
                        cog.register_destruct(ch.guild.id, ch.id, sent_msg.id, self.config['destruct'])
                        
            except Exception as e:
                errors_log.append(f"{ch.name}: {str(e)}")

        report_message = f"Berhasil diproses di {success_count}/{len(self.channels)} channel!"
        if errors_log:
            report_message += "\n**Error Info:**\n"
            for err in errors_log[:5]:
                report_message += err + "\n"
            if len(errors_log) > 5:
                report_message += "...dan error lainnya."

        await interaction.followup.send(report_message, ephemeral=True)
        
        try:
            await interaction.message.delete()
        except Exception:
            pass

        await interaction.followup.send(f"Berhasil diproses di {success_count}/{len(self.channels)} channel!", ephemeral=True)
        try: await interaction.message.delete()
        except: pass

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
        
        self.rec_input = discord.ui.TextInput(
            label='Ulang Jadwal (none/daily/weekly)',
            placeholder='none',
            default='none',
            style=discord.TextStyle.short,
            required=False
        )
        self.add_item(self.rec_input)

        self.channel_input = discord.ui.TextInput(
            label='ID Kanal Tujuan (Bisa banyak dipisah koma)',
            placeholder='123456789, 987654321',
            style=discord.TextStyle.paragraph,
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
            self.config['recurring'] = self.rec_input.value.strip().lower()
            
            cids = [re.sub(r'\D', '', c) for c in self.channel_input.value.split(',') if re.sub(r'\D', '', c)]
            if not cids:
                return await interaction.response.send_message("Tidak ada ID kanal yang valid.", ephemeral=True)
            self.config['channels'] = cids

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

        ch_len = len(self.config.get('channels', []))
        ch_display = f"{ch_len} Kanal Target" if ch_len else "Belum diatur"

        embed.add_field(name="Waktu Terjadwal", value=f"`{sch_display}` | Ulang: `{self.config.get('recurring', 'none')}`", inline=False)
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

    @discord.ui.button(label="Pesan Teks Biasa", style=discord.ButtonStyle.blurple, row=1)
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
        if not self.config.get('scheduled_time') or not self.config.get('channels'):
            return await interaction.followup.send("Tentukan jadwal dan kanal tujuan terlebih dahulu.", ephemeral=True)

        scheduled_announcements = self.bot.get_cog('RTMBroadcast').load_scheduled_announcements()
        job_id = str(uuid.uuid4())
        scheduled_announcements[job_id] = self.config
        self.bot.get_cog('RTMBroadcast').save_scheduled_announcements(scheduled_announcements)
        
        dt_wib = datetime.fromisoformat(self.config['scheduled_time']).astimezone(pytz.timezone('Asia/Jakarta'))
        await interaction.followup.send(f"Pengumuman dijadwalkan ke {len(self.config['channels'])} kanal pada **{dt_wib.strftime('%d %B %Y pukul %H:%M WIB')}**.", ephemeral=True)
        try: await interaction.message.delete()
        except: pass

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.red, row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try: await interaction.message.delete()
        except: pass
        self.stop()

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
            self.bot.get_cog('RTMBroadcast').save_config_to_file(self.channel.guild.id, self.channel.id, str(msg.id), self.config)
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

class RTMBroadcast(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.button_actions = {}
        self.active_tickets = {}
        self.data_dir = 'data'
        self.config_file = os.path.join(self.data_dir, 'webhook.json')
        self.backup_file = os.path.join(self.data_dir, 'configbackup.json')
        self.scheduled_announcements_file = os.path.join(self.data_dir, 'scheduled_announcements.json')
        self.destruct_file = os.path.join(self.data_dir, 'broadcast_destructs.json')
        self.wib_timezone = pytz.timezone('Asia/Jakarta')
        
        self.loop_destruct.start()
        self.loop_sch.start()
        self.single_role_file = os.path.join(self.data_dir, 'single_role_messages.json')
        self.single_role_messages = self.load_single_role_messages()

    def cog_unload(self):
        self.loop_destruct.cancel()
        self.loop_sch.cancel()

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

    def load_json(self, path):
        if not os.path.exists(path): return {}
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}

    def save_json(self, path, data):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)

    def register_destruct(self, g_id, c_id, m_id, mins):
        data = self.load_json(self.destruct_file)
        dt = (datetime.utcnow() + timedelta(minutes=mins)).isoformat()
        data[str(m_id)] = {'g': g_id, 'c': c_id, 'time': dt}
        self.save_json(self.destruct_file, data)

    def build_payload(self, config, bot):
        embed = None
        if config.get('title') or config.get('desc') or config.get('color') or config.get('media_url'):
            color = int(config.get('color', '#2b2d31').replace('#', ''), 16) if config.get('color') else 0x2b2d31
            embed = discord.Embed(title=config.get('title'), description=config.get('desc'), color=color)
            if config.get('media_url'): embed.set_image(url=config['media_url'])

        for obj in config.get('buttons', []) + config.get('dropdowns', []):
            if obj.get('action') != 'url' and not obj.get('id'):
                obj['id'] = str(uuid.uuid4())
            if obj.get('id'):
                self.button_actions[obj['id']] = {'action': obj.get('action'), 'value': obj.get('value')}

        view = InteractiveView(config) if (config.get('buttons') or config.get('dropdowns')) else None

        payload = {
            'content': config.get('content'),
            'username': config.get('author') or bot.user.name,
            'avatar_url': config.get('avatar') or bot.user.display_avatar.url,
            'embeds': [embed] if embed else []
        }
        if view: payload['view'] = view
        return payload, view

    @tasks.loop(minutes=1)
    async def loop_destruct(self):
        data = self.load_json(self.destruct_file)
        now = datetime.utcnow()
        to_del = []
        for m_id, info in data.items():
            if now >= datetime.fromisoformat(info['time']):
                try:
                    ch = self.bot.get_channel(info['c']) or await self.bot.fetch_channel(info['c'])
                    msg = await ch.fetch_message(int(m_id))
                    await msg.delete()
                except: pass
                to_del.append(m_id)
        if to_del:
            for d in to_del: del data[d]
            self.save_json(self.destruct_file, data)

    @tasks.loop(minutes=1)
    async def loop_sch(self):
        schedules = self.load_scheduled_announcements()
        now_wib = datetime.now(self.wib_timezone)
        tasks_to_remove = []

        for job_id, job_data in list(schedules.items()):
            try:
                sch_wib = datetime.fromisoformat(job_data['scheduled_time']).astimezone(self.wib_timezone)
                if now_wib >= sch_wib:
                    payload, _ = self.build_payload(job_data, self.bot)
                    
                    for cid in job_data.get('channels', []):
                        try:
                            ch = self.bot.get_channel(int(cid)) or await self.bot.fetch_channel(int(cid))
                            if not ch: continue
                            webhook = discord.utils.get(await ch.webhooks(), name="RTMBroadcast") or await ch.create_webhook(name="RTMBroadcast")
                            sent = await webhook.send(wait=True, **payload)
                            if sent and job_data.get('destruct'): self.register_destruct(ch.guild.id, ch.id, sent.id, job_data['destruct'])
                        except: pass
                    
                    rec = job_data.get('recurring')
                    if rec == 'daily': job_data['scheduled_time'] = (sch_wib + timedelta(days=1)).isoformat()
                    elif rec == 'weekly': job_data['scheduled_time'] = (sch_wib + timedelta(days=7)).isoformat()
                    else: tasks_to_remove.append(job_id)
            except:
                tasks_to_remove.append(job_id)

        if tasks_to_remove or any(c.get('recurring') in ['daily','weekly'] for c in schedules.values()):
            for d in tasks_to_remove: schedules.pop(d, None)
            self.save_scheduled_announcements(schedules)

    @loop_destruct.before_loop
    @loop_sch.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

    def load_scheduled_announcements(self):
        if not os.path.exists(self.scheduled_announcements_file): return {}
        try:
            with open(self.scheduled_announcements_file, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}

    def save_scheduled_announcements(self, data):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.scheduled_announcements_file, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)

    def _load_all_button_actions(self):
        if not os.path.exists(self.config_file): return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f: all_configs = json.load(f)
            for g in all_configs.values():
                for c in g.values():
                    for conf in c.values():
                        for btn in conf.get('buttons', []) + conf.get('dropdowns', []):
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
    async def send_webhook(self, ctx, *channels: str):
        try: await ctx.message.delete()
        except: pass
        targets = []
        for c in channels:
            cid = re.sub(r'\D', '', c)
            if cid:
                ch = self.bot.get_channel(int(cid)) or await self.bot.fetch_channel(int(cid))
                if ch: targets.append(ch)
        if not targets: targets = [ctx.channel]
        view = WebhookConfigView(self.bot, targets)
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(aliases=['eb'])
    @commands.has_permissions(manage_messages=True)
    async def edit_broadcast(self, ctx, msg_id: int, channel_id: str = None):
        try: await ctx.message.delete()
        except: pass
        cid = int(re.sub(r'\D', '', channel_id)) if channel_id else ctx.channel.id
        ch = self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
        try:
            msg = await ch.fetch_message(msg_id)
            cfg = {'content': msg.content}
            if msg.embeds:
                e = msg.embeds[0]
                cfg.update({'title': e.title, 'desc': e.description, 'color': f"#{e.color.value:06x}" if e.color else None, 'media_url': e.image.url if e.image else None})
            view = WebhookConfigView(self.bot, [ch], cfg, msg_id)
            await ctx.send(embed=view.build_embed(), view=view)
        except:
            await ctx.send("Pesan gagal diambil.", ephemeral=True, delete_after=5)

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
    
    @commands.command(name='send_media', aliases=['sm'])
    @commands.has_permissions(manage_messages=True)
    async def send_media(self, ctx, channel_id: str = None):
        target = await self.get_target_channel(ctx, channel_id)
        if not target:
            return await ctx.send("Kanal tujuan tidak valid.", delete_after=5)

        source_msg = None

        if ctx.message.attachments:
            source_msg = ctx.message
        elif ctx.message.reference:
            try:
                source_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if not source_msg.attachments:
                    return await ctx.send("Pesan yang dibalas tidak memiliki media.", delete_after=5)
            except Exception:
                return await ctx.send("Pesan yang dibalas tidak ditemukan.", delete_after=5)
        else:
            prompt_msg = await ctx.send(f"Kirim foto/video kamu sekarang di sini untuk diteruskan ke {target.mention}.\nWaktu tunggumu **3 menit** (biar aman pas upload).\nKetik `batal` buat cancel.")
            
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            try:
                msg = await self.bot.wait_for('message', timeout=180.0, check=check)
                if msg.content.strip().lower() == 'batal':
                    try: await prompt_msg.delete()
                    except: pass
                    try: await msg.delete()
                    except: pass
                    return await ctx.send("Operasi dibatalkan.", delete_after=5)
                
                if not msg.attachments:
                    try: await prompt_msg.delete()
                    except: pass
                    return await ctx.send("Gagal: Pesanmu barusan gak ada file/media-nya.", delete_after=5)
                
                source_msg = msg
                try: await prompt_msg.delete()
                except: pass
            except asyncio.TimeoutError:
                try: await prompt_msg.delete()
                except: pass
                return await ctx.send("Waktu habis. Proses dibatalkan otomatis.", delete_after=5)

        processing_msg = await ctx.send("Sedang memproses dan mengirim media...")
        try:
            files = []
            for attachment in source_msg.attachments:
                files.append(await attachment.to_file())
            
            content_to_send = source_msg.content
            if content_to_send and content_to_send.startswith(('!send_media', '!sm')):
                if channel_id:
                    content_to_send = content_to_send.replace(f'!send_media {channel_id}', '').replace(f'!sm {channel_id}', '').strip()
                else:
                    content_to_send = content_to_send.replace('!send_media', '').replace('!sm', '').strip()
                if not content_to_send:
                    content_to_send = None

            await target.send(content=content_to_send, files=files)
            await processing_msg.edit(content=f"✅ Media berhasil terkirim ke {target.mention}!", delete_after=5)
            
            try: await ctx.message.delete()
            except: pass
            if source_msg.id != ctx.message.id:
                try: await source_msg.delete()
                except: pass
        except Exception as e:
            await processing_msg.edit(content=f"❌ Gagal mengirim media: {e}", delete_after=10)
    
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
                ch = self.bot.get_channel(int(data.get('channels', [data.get('channel_id')])[0]))
                ch_str = ch.mention if ch else f"ID"
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
            view = WebhookConfigView(self.bot, [target], initial_config=config_data)
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
            
            os.makedirs(self.data_dir, exist_ok=True)
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
        cid = interaction.data.get('custom_id')
        data = self.button_actions.get(cid)
        if not data and interaction.data.get('values'):
            data = self.button_actions.get(interaction.data['values'][0])
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

        elif action == 'translate':
            await interaction.response.defer(ephemeral=True)
            txt = interaction.message.content or ""
            if interaction.message.embeds: txt += "\n" + (interaction.message.embeds[0].description or "")
            try:
                res = await genai.GenerativeModel('gemini-2.5-flash').generate_content_async(f"Terjemahkan ke {value}:\n{txt}")
                await interaction.followup.send(res.text, ephemeral=True)
            except Exception as e: await interaction.followup.send(f"Error AI: {e}", ephemeral=True)

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
    await bot.add_cog(RTMBroadcast(bot))
