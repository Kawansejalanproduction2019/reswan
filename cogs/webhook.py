import discord
from discord.ext import commands
import json
import uuid
import asyncio
import os

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
        self.cog.save_config_to_file(interaction.guild.id, config_name, self.config)
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
        await interaction.response.send_message("Pilih warna:", view=ColorView(self.config, self), ephemeral=True)

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
                await interaction.followup.send("Format warna tidak valid. Pesan tidak dikirim.", ephemeral=True)
                return

        webhook = discord.utils.get(await self.channel.webhooks(), name="Webhook Bot")
        if not webhook:
            webhook = await self.channel.create_webhook(name="Webhook Bot")

        view = None
        buttons_data = self.config.get('buttons', [])
        if buttons_data:
            actions_map = {}
            for btn_data in buttons_data:
                btn_id = str(uuid.uuid4())
                btn_data['id'] = btn_id
                actions_map[btn_id] = {'action': btn_data.get('action'), 'value': btn_data.get('value')}
            
            self.bot.get_cog('WebhookCog').button_actions.update(actions_map)
            
            view = ButtonView(buttons_data)

        sent_message = None
        try:
            sent_message = await webhook.send(
                content=self.config.get('content'),
                username=self.config.get('author') or interaction.guild.name,
                avatar_url=self.config.get('avatar') or interaction.guild.icon.url,
                embeds=[embed] if embed else [],
                view=view
            )
        except Exception as e:
            await interaction.followup.send(f"Gagal mengirim pesan webhook: {e}", ephemeral=True)
            return

        if sent_message:
            try:
                config_name = str(sent_message.id)
                self.bot.get_cog('WebhookCog').save_config_to_file(interaction.guild.id, config_name, self.config)
            except Exception as e:
                await interaction.followup.send(f"Pesan webhook berhasil dikirim, tetapi gagal menyimpan konfigurasi otomatis: {e}", ephemeral=True)
        else:
            await interaction.followup.send("Pesan gagal terkirim, konfigurasi tidak disimpan.", ephemeral=True)

        try:
            if sent_message:
                await interaction.followup.send(f"Pesan webhook berhasil dikirim ke {self.channel.mention}! Konfigurasi tersimpan otomatis dengan nama `{sent_message.id}`.", ephemeral=True)
            await interaction.message.delete()
        except Exception as e:
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
# Main Cog
# =================================================================
class WebhookCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.button_actions = {}
        self.active_tickets = {}
        self.data_dir = 'data'
        
    @commands.Cog.listener()
    async def on_ready(self):
        print("Bot siap. Memuat semua aksi tombol dari file JSON...")
        self._load_all_button_actions()
        print("Aksi tombol berhasil dimuat.")

    def _load_all_button_actions(self):
        """Helper function to load all button actions from JSON files."""
        if not os.path.exists(self.data_dir):
            return

        for filename in os.listdir(self.data_dir):
            if filename.endswith('.json'):
                file_path = os.path.join(self.data_dir, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        all_configs = json.load(f)
                    
                    for config_name, config_data in all_configs.items():
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
                    print(f"ERROR: Gagal memuat file konfigurasi {filename}: {e}")

    def save_config_to_file(self, guild_id, config_name, config_data):
        """Helper function untuk menyimpan konfigurasi per-guild."""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        
        config_file = os.path.join(self.data_dir, f'{guild_id}.json')
        all_configs = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    all_configs = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        
        all_configs[config_name] = config_data
        
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(all_configs, f, indent=4)
        except Exception as e:
            print(f"ERROR: Gagal menyimpan konfigurasi ke file: {e}")

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

    @commands.command(name='save_config')
    @commands.has_permissions(manage_webhooks=True)
    async def save_config(self, ctx, config_name: str):
        """Menyimpan konfigurasi webhook saat ini ke file."""
        if not ctx.guild:
            await ctx.send("Perintah ini hanya bisa digunakan di dalam server.")
            return

        view = discord.utils.get(self.bot.get_all_views(), __class__=WebhookConfigView)
        if not view:
            await ctx.send("Tidak ada konfigurasi aktif untuk disimpan. Mohon gunakan perintah `!swh` terlebih dahulu.", ephemeral=True)
            return

        self.save_config_to_file(ctx.guild.id, config_name, view.config)
        await ctx.send(f"Konfigurasi '{config_name}' berhasil disimpan untuk server ini.", ephemeral=True)

    @commands.command(name='load_config')
    @commands.has_permissions(manage_webhooks=True)
    async def load_config(self, ctx, config_name: str, channel: discord.TextChannel):
        """Memuat konfigurasi webhook dari file dan memulainya."""
        if not ctx.guild:
            await ctx.send("Perintah ini hanya bisa digunakan di dalam server.")
            return
            
        config_file = os.path.join(self.data_dir, f'{ctx.guild.id}.json')
        all_configs = {}
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                all_configs = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            await ctx.send(f"File konfigurasi server tidak ditemukan atau tidak valid. Tidak ada konfigurasi yang bisa dimuat.")
            return

        if config_name not in all_configs:
            await ctx.send(f"Konfigurasi dengan nama `{config_name}` tidak ditemukan di server ini.")
            return

        config_data = all_configs[config_name]
        
        view = WebhookConfigView(self.bot, channel, initial_config=config_data)
        await ctx.send(embed=view.build_embed(), view=view)

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
            if interaction.user.id in self.active_tickets:
                await interaction.response.send_message("Anda sudah memiliki tiket aktif.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            category_id = int(value) if value else None
            category = interaction.guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                category = None

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            admin_roles = [role for role in interaction.guild.roles if role.permissions.manage_channels]
            for role in admin_roles:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            channel_name = f"ticket-{interaction.user.name.lower()}"
            ticket_channel = await interaction.guild.create_text_channel(
                channel_name,
                overwrites=overwrites,
                category=category
            )

            admin_mentions = " ".join([f"{role.mention}" for role in admin_roles])

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

            await ticket_channel.send(f"**Tiket Baru!** {admin_mentions} {interaction.user.mention}", embed=embed, view=view)
            
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
