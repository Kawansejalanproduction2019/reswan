import discord
from discord.ext import commands
import json
import os
import logging
import asyncio
import uuid
from datetime import datetime
import pytz
import re

# =================================================================
# Kelas Modal dan View untuk UI
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

class SetChannelView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="Channel Pengumuman", style=discord.ButtonStyle.blurple, custom_id="announce_button")
    async def announce_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChannelModal(self.cog, "announcement"))

    @discord.ui.button(label="Channel Share Link", style=discord.ButtonStyle.green, custom_id="link_button")
    async def link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChannelModal(self.cog, "link_share"))

class ChannelModal(discord.ui.Modal, title='Set Channel'):
    def __init__(self, cog, channel_type):
        super().__init__()
        self.cog = cog
        self.channel_type = channel_type
        self.channel_input = discord.ui.TextInput(
            label=f'ID Channel untuk {self.channel_type.replace("_", " ").title()}',
            placeholder='Masukkan ID Channel',
            required=True
        )
        self.add_item(self.channel_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel_id = int(self.channel_input.value)
            channel = interaction.guild.get_channel(channel_id)
            if not channel:
                await interaction.response.send_message("ID channel tidak valid atau channel tidak ditemukan.", ephemeral=True)
                return
            
            self.cog.set_target_channel(interaction.guild.id, channel_id, self.channel_type)
            await interaction.response.send_message(f"✅ Channel **{self.channel_type.replace('_', ' ').title()}** berhasil disetel ke {channel.mention}!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Input ID channel tidak valid. Mohon masukkan angka saja.", ephemeral=True)
            return

class MultiSendAnnounceView(discord.ui.View):
    def __init__(self, bot, initial_config=None):
        super().__init__(timeout=300)
        self.bot = bot
        self.config = initial_config or {}

    def build_embed(self):
        embed = discord.Embed(
            title="Konfigurasi Pengumuman",
            description="Atur pesan yang akan dikirim ke semua channel pengumuman.",
            color=0x2b2d31
        )
        embed.add_field(name="Pesan Teks Biasa", value=f"`{self.config.get('content', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Judul Embed", value=f"`{self.config.get('title', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Deskripsi Embed", value=f"`{self.config.get('desc', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Warna", value=f"`{self.config.get('color', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Media (URL)", value=f"`{self.config.get('media_url', 'Belum diatur')}`", inline=False)
        return embed

    @discord.ui.button(label="Pesan Teks Biasa", style=discord.ButtonStyle.blurple, row=0)
    async def content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextModal('content', self.config, self))

    @discord.ui.button(label="Judul & Deskripsi Embed", style=discord.ButtonStyle.blurple, row=0)
    async def embed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class EmbedModal(discord.ui.Modal, title='Atur Embed'):
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
        await interaction.response.send_modal(EmbedModal(self.config, self))

    @discord.ui.button(label="Warna Embed", style=discord.ButtonStyle.blurple, row=0)
    async def color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=ColorView(self.config, self))

    @discord.ui.button(label="URL Media", style=discord.ButtonStyle.blurple, row=1)
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
        
    @discord.ui.button(label="Kirim Pengumuman", style=discord.ButtonStyle.green, row=2)
    async def send_all_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not (self.config.get('content') or self.config.get('title') or self.config.get('media_url')):
            await interaction.followup.send("Pengumuman harus memiliki minimal satu konten.", ephemeral=True)
            return
        embed = None
        if self.config.get('title') or self.config.get('desc') or self.config.get('media_url') or self.config.get('color'):
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
                await interaction.followup.send("Format warna tidak valid. Pesan tidak dikirim.", ephemeral=True)
                return
        sent_count = 0
        failed_guilds = []
        for guild in self.bot.guilds:
            channel_id = self.bot.get_cog('MultiSendCog').get_target_channel(guild.id, "announcement")
            if not channel_id:
                failed_guilds.append(f"`{guild.name}` (Kanal tidak disetel)")
                continue
            channel = guild.get_channel(channel_id)
            if not channel:
                failed_guilds.append(f"`{guild.name}` (Kanal tidak ditemukan)")
                continue
            try:
                await channel.send(content=self.config.get('content'), embeds=[embed] if embed else [])
                sent_count += 1
            except discord.errors.Forbidden:
                failed_guilds.append(f"`{guild.name}` (Izin ditolak)")
            except Exception as e:
                failed_guilds.append(f"`{guild.name}` ({e})")
        await interaction.message.delete()
        response_message = f"✅ Pengumuman berhasil dikirim ke **{sent_count}** dari **{len(self.bot.guilds)}** server."
        if failed_guilds:
            response_message += "\n\nGagal dikirim ke server berikut:\n" + "\n".join(failed_guilds[:5])
            if len(failed_guilds) > 5:
                response_message += f"\n...dan {len(failed_guilds) - 5} lainnya."
        await interaction.followup.send(response_message, ephemeral=True)
    
    @discord.ui.button(label="Batalkan", style=discord.ButtonStyle.red, row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Operasi dibatalkan.", ephemeral=True)
        await interaction.message.delete()
        self.stop()

class MultiSendLinkView(discord.ui.View):
    def __init__(self, bot, initial_config=None):
        super().__init__(timeout=300)
        self.bot = bot
        self.config = initial_config or {}

    def build_embed(self):
        embed = discord.Embed(
            title="Konfigurasi Share Link",
            description="Atur link dan pesan yang akan dibagikan ke semua channel share link.",
            color=0x2b2d31
        )
        embed.add_field(name="Link Konten", value=f"`{self.config.get('link', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Pesan Teks Biasa", value=f"`{self.config.get('content', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Judul Embed", value=f"`{self.config.get('title', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Deskripsi Embed", value=f"`{self.config.get('desc', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Warna", value=f"`{self.config.get('color', 'Belum diatur')}`", inline=False)
        embed.add_field(name="Media (URL)", value=f"`{self.config.get('media_url', 'Belum diatur')}`", inline=False)
        return embed
    
    @discord.ui.button(label="Link Konten", style=discord.ButtonStyle.primary, row=0)
    async def set_link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class LinkModal(discord.ui.Modal, title='Masukkan URL Link'):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.url_input = discord.ui.TextInput(
                    label='URL Link',
                    placeholder='e.g., https://youtube.com/watch?v=...',
                    default=config.get('link')
                )
                self.add_item(self.url_input)
            async def on_submit(self, interaction: discord.Interaction):
                self.config['link'] = self.url_input.value
                await interaction.response.edit_message(embed=self.view.build_embed())
        await interaction.response.send_modal(LinkModal(self.config, self))

    @discord.ui.button(label="Pesan Teks Biasa", style=discord.ButtonStyle.blurple, row=1)
    async def content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextModal('content', self.config, self))
    
    @discord.ui.button(label="Judul & Deskripsi Embed", style=discord.ButtonStyle.blurple, row=1)
    async def embed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        class EmbedModal(discord.ui.Modal, title='Atur Embed'):
            def __init__(self, config, view):
                super().__init__()
                self.config = config
                self.view = view
                self.title_input = discord.ui.TextInput(label="Judul Embed", default=config.get('title', ''), required=False)
                self.desc_input = discord.ui.TextInput(label="Deskripsi Embed", style=discord.TextStyle.paragraph, default=config.get('desc', ''), required=False)
                self.add_item(self.title_input)
            async def on_submit(self, interaction: discord.Interaction):
                self.config['title'] = self.title_input.value or None
                self.config['desc'] = self.desc_input.value or None
                await interaction.response.edit_message(embed=self.view.build_embed())
        await interaction.response.send_modal(EmbedModal(self.config, self))

    @discord.ui.button(label="Warna Embed", style=discord.ButtonStyle.blurple, row=1)
    async def color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=ColorView(self.config, self))

    @discord.ui.button(label="URL Media", style=discord.ButtonStyle.blurple, row=1)
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
        
    @discord.ui.button(label="Bagikan Link", style=discord.ButtonStyle.green, row=2)
    async def send_all_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not (self.config.get('link') or self.config.get('content') or self.config.get('title') or self.config.get('media_url')):
            await interaction.followup.send("Pesan harus memiliki minimal satu konten.", ephemeral=True)
            return

        embed = None
        if self.config.get('title') or self.config.get('desc') or self.config.get('media_url') or self.config.get('color'):
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
                await interaction.followup.send("Format warna tidak valid. Pesan tidak dikirim.", ephemeral=True)
                return

        content = self.config.get('content')
        if self.config.get('link'):
            if content:
                content = f"{content}\n{self.config.get('link')}"
            else:
                content = self.config.get('link')

        sent_count = 0
        failed_guilds = []

        for guild in self.bot.guilds:
            channel_id = self.bot.get_cog('MultiSendCog').get_target_channel(guild.id, "link_share")
            if not channel_id:
                failed_guilds.append(f"`{guild.name}` (Kanal tidak disetel)")
                continue

            channel = guild.get_channel(channel_id)
            if not channel:
                continue
            
            try:
                await channel.send(content=content, embeds=[embed] if embed else [])
                sent_count += 1
            except discord.errors.Forbidden:
                failed_guilds.append(f"`{guild.name}` (Izin ditolak)")
            except Exception as e:
                failed_guilds.append(f"`{guild.name}` ({e})")
        
        await interaction.message.delete()
        
        response_message = f"✅ Link berhasil dibagikan ke **{sent_count}** dari **{len(self.bot.guilds)}** server."
        if failed_guilds:
            response_message += "\n\nGagal dikirim ke server berikut:\n" + "\n".join(failed_guilds[:5])
            if len(failed_guilds) > 5:
                response_message += f"\n...dan {len(failed_guilds) - 5} lainnya."

        await interaction.followup.send(response_message, ephemeral=True)

    @discord.ui.button(label="Batalkan", style=discord.ButtonStyle.red, row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Operasi dibatalkan.", ephemeral=True)
        await interaction.message.delete()
        self.stop()
        
class MultiSendCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_dir = 'data'
        self.config_file = os.path.join(self.data_dir, 'multisend_channels.json')
        self.sent_links_file = os.path.join(self.data_dir, 'sent_links.json')
        self.sent_links = self._load_sent_links()

    def get_target_channel(self, guild_id, channel_type):
        configs = self._load_configs()
        return configs.get(str(guild_id), {}).get(channel_type)

    def set_target_channel(self, guild_id, channel_id, channel_type):
        configs = self._load_configs()
        guild_id_str = str(guild_id)
        if not isinstance(configs.get(guild_id_str), dict):
            configs[guild_id_str] = {}
        configs[guild_id_str][channel_type] = channel_id
        self._save_configs(configs)

    def set_source_channel(self, guild_id, channel_id):
        configs = self._load_configs()
        guild_id_str = str(guild_id)
        if not isinstance(configs.get(guild_id_str), dict):
            configs[guild_id_str] = {}
        configs[guild_id_str]['source_channel_id'] = channel_id
        self._save_configs(configs)

    def get_source_channel(self, guild_id):
        configs = self._load_configs()
        return configs.get(str(guild_id), {}).get('source_channel_id')

    def _get_link_from_url(self, message):
        youtube_regex = r'(?:https?:\/\/)?(?:www\.)?(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.*&v=))([a-zA-Z0-9_-]{11})'
        tiktok_regex = r'(?:https?:\/\/)?(?:www\.)?(?:tiktok\.com\/.*\/video\/(\d+))'

        match_youtube = re.search(youtube_regex, message.content)
        if match_youtube:
            link = match_youtube.group(0)
            if "premier" in message.content.lower():
                return "premier", link
            elif "live" in message.content.lower():
                return "youtube_live", link
            else:
                return "youtube_upload", link

        match_tiktok = re.search(tiktok_regex, message.content)
        if match_tiktok:
            link = match_tiktok.group(0)
            if not link.startswith(('https://www.', 'http://www.')):
                if link.startswith('https://'):
                    link = link.replace('https://', 'https://www.')
                elif link.startswith('http://'):
                    link = link.replace('http://', 'http://www.')
                else:
                    link = f"https://www.{link}"
            return "default", link

        return None, None

    def _load_configs(self):
        if not os.path.exists(self.config_file):
            return {}
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_configs(self, configs):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(configs, f, indent=4)
    
    def _load_sent_links(self):
        if not os.path.exists(self.sent_links_file):
            return []
        try:
            with open(self.sent_links_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_sent_links(self, links):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        with open(self.sent_links_file, 'w', encoding='utf-8') as f:
            json.dump(links, f, indent=4)
            
    @commands.command(name='set_channels')
    @commands.has_permissions(manage_channels=True)
    async def set_channels(self, ctx):
        await ctx.send("Silakan pilih jenis channel yang ingin Anda setel:", view=SetChannelView(self))

    @commands.command(name='set_source_channel')
    @commands.has_permissions(manage_channels=True)
    async def set_source_channel(self, ctx, channel: discord.TextChannel):
        self.set_source_channel(ctx.guild.id, channel.id)
        await ctx.send(f"✅ Channel sumber telah disetel ke {channel.mention}. Pesan dengan link di channel ini akan otomatis dibagikan.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.id == self.bot.user.id or message.author.bot:
            return

        source_channel_id = self.get_source_channel(message.guild.id)
        if message.channel.id != source_channel_id:
            return
        
        link_type, link_to_share = self._get_link_from_url(message)
        
        if not link_to_share:
            return

        # Cek duplikat
        if link_to_share in self.sent_links:
            return
        
        sent_count = 0
        failed_guilds = []

        for guild in self.bot.guilds:
            channel_id = self.get_target_channel(guild.id, "link_share")
            if not channel_id:
                continue

            channel = guild.get_channel(channel_id)
            if not channel:
                continue
            
            try:
                await channel.send(link_to_share)
                sent_count += 1
            except discord.errors.Forbidden:
                failed_guilds.append(f"`{guild.name}` (Izin ditolak)")
            except Exception as e:
                failed_guilds.append(f"`{guild.name}` ({e})")
        
        if sent_count > 0:
            self.sent_links.append(link_to_share)
            self._save_sent_links(self.sent_links)
            logging.info(f"Berhasil membagikan link ke {sent_count} server.")
        if failed_guilds:
            logging.error(f"Gagal membagikan link ke server: {', '.join(failed_guilds)}")

    @commands.command(name='multisend')
    @commands.is_owner()
    async def multisend(self, ctx):
        await ctx.send("Silakan pilih opsi pengiriman:", view=MultiSendOptionsView(self.bot))

class MultiSendOptionsView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot

    @discord.ui.button(label="Kirim Pengumuman", style=discord.ButtonStyle.blurple)
    async def announce_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=MultiSendAnnounceView(self.bot).build_embed(), view=MultiSendAnnounceView(self.bot))

    @discord.ui.button(label="Kirim Share Link", style=discord.ButtonStyle.green)
    async def link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=MultiSendLinkView(self.bot).build_embed(), view=MultiSendLinkView(self.bot))
    
    @discord.ui.button(label="Batalkan", style=discord.ButtonStyle.red, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Operasi dibatalkan.", ephemeral=True)
        self.stop()
async def setup(bot):
    await bot.add_cog(MultiSendCog(bot))
