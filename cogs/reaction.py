import json
import discord
from discord.ext import commands
import logging
import json

# --- Konfigurasi Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- Konfigurasi Awal Bot ---
CONFIG_FILE = 'apreciator_config.json'

# Fungsi untuk mengecek izin administrator
def is_allowed_user(ctx):
    """Mengecek apakah user yang menjalankan perintah memiliki izin Administrator di server."""
    if ctx.author.guild_permissions.administrator:
        return True
    return False

def load_apreciator_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            log.info(f"Konfigurasi '{CONFIG_FILE}' berhasil dimuat.")
            return data
    except FileNotFoundError:
        log.warning(f"File konfigurasi '{CONFIG_FILE}' tidak ditemukan. Membuat struktur default.")
        return {"link_channels": {}, "text_triggers": {}}
    except json.JSONDecodeError:
        log.error(f"File konfigurasi '{CONFIG_FILE}' rusak atau formatnya salah. Membuat ulang struktur default.", exc_info=True)
        return {"link_channels": {}, "text_triggers": {}}

def save_apreciator_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4)
    log.info(f"Konfigurasi '{CONFIG_FILE}' berhasil disimpan.")

class Apreciator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_data = load_apreciator_config()
        log.info("Apreciator Cog diinisialisasi.")

    async def _add_reactions_ordered(self, message: discord.Message, emojis: list):
        emojis_to_add = emojis[:30] 
        for emoji_str in emojis_to_add:
            try:
                await message.add_reaction(emoji_str)
                log.debug(f"Menambahkan reaksi '{emoji_str}' ke pesan {message.id} di channel {message.channel.id}.")
            except discord.HTTPException as e:
                log.error(f"Gagal menambahkan reaksi '{emoji_str}' ke pesan {message.id} di channel {message.channel.id} (HTTP): {e}", exc_info=True)
            except Exception as e:
                log.error(f"Error tidak terduga saat menambahkan reaksi '{emoji_str}' ke pesan {message.id}: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.webhook_id:
            return

        channel_id_str = str(message.channel.id)
        content_lower = message.content.lower()

        if channel_id_str in self.config_data.get('link_channels', {}):
            if "http://" in content_lower or "https://" in content_lower or "www." in content_lower:
                emojis = self.config_data['link_channels'][channel_id_str]
                log.info(f"Link terdeteksi di <#{channel_id_str}> (Pesan ID: {message.id}). Merekasi dengan LinkMark.")
                await self._add_reactions_ordered(message, emojis)
                return 

        if channel_id_str in self.config_data.get('text_triggers', {}):
            channel_triggers = self.config_data['text_triggers'].get(channel_id_str, {})
            for trigger_phrase, emojis in channel_triggers.items():
                if trigger_phrase.lower() in content_lower:
                    log.info(f"Teks pemicu '{trigger_phrase}' terdeteksi di <#{channel_id_str}> (Pesan ID: {message.id}). Merekasi dengan TextReact.")
                    await self._add_reactions_ordered(message, emojis)
                    return 

    @commands.command(name='set')
    @commands.check(is_allowed_user)
    @commands.guild_only() 
    async def set_link_reaction(self, ctx: commands.Context, channel_id: int, *emojis: str):
        if not emojis or len(emojis) > 30:
            return await ctx.send("Gagal: Minimal 1 dan maksimal 30 emoji harus diberikan.")
        
        self.config_data['link_channels'][str(channel_id)] = list(emojis)
        save_apreciator_config(self.config_data)
        log.info(f"LinkMark untuk <#{channel_id}> diatur oleh {ctx.author.name} (ID: {ctx.author.id}).")
        await ctx.send(f"✅ Reaksi LinkMark untuk <#{channel_id}> berhasil diatur: {' '.join(emojis)}")

    @set_link_reaction.error
    async def set_link_reaction_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Penggunaan tidak benar: `/set <channel_id> <emoji1> [emoji2] ...`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Gagal: Pastikan ID channel adalah angka yang valid.")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("⛔ Kamu tidak memiliki izin Administrator untuk menggunakan perintah ini.")
        else:
            log.error(f"Error di perintah /set (oleh {ctx.author.name}, Guild: {ctx.guild.id}): {error}", exc_info=True)
            await ctx.send("❌ Terjadi kesalahan internal saat memproses perintah ini.")

    @commands.command(name='rem')
    @commands.check(is_allowed_user)
    @commands.guild_only()
    async def remove_link_reaction(self, ctx: commands.Context, channel_id: int):
        if str(channel_id) in self.config_data['link_channels']:
            del self.config_data['link_channels'][str(channel_id)]
            save_apreciator_config(self.config_data)
            log.info(f"LinkMark untuk <#{channel_id}> dihapus oleh {ctx.author.name} (ID: {ctx.author.id}).")
            await ctx.send(f"✅ Reaksi LinkMark untuk <#{channel_id}> berhasil dihapus.")
        else:
            await ctx.send(f"❌ Gagal: Channel ID <#{channel_id}> tidak ditemukan dalam konfigurasi LinkMark.")

    @remove_link_reaction.error
    async def remove_link_reaction_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Penggunaan tidak benar: `/rem <channel_id>`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Gagal: Pastikan ID channel adalah angka yang valid.")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("⛔ Kamu tidak memiliki izin Administrator untuk menggunakan perintah ini.")
        else:
            log.error(f"Error di perintah /rem (oleh {ctx.author.name}, Guild: {ctx.guild.id}): {error}", exc_info=True)
            await ctx.send("❌ Terjadi kesalahan internal saat memproses perintah ini.")

    @commands.command(name='show')
    @commands.guild_only()
    async def show_config(self, ctx: commands.Context):
        response = "**Konfigurasi Apreciator Saat Ini:**\n\n"
        
        response += "__**LinkMark (Reaksi Tautan Otomatis):**__\n"
        if not self.config_data.get('link_channels'):
            response += "Tidak ada channel yang terdaftar.\n"
        else:
            for channel_id, emojis in self.config_data['link_channels'].items():
                response += f"- <#{channel_id}>: {' '.join(emojis)}\n"
        
        response += "\n__**TextReact (Reaksi Pesan Teks Kustom):**__\n"
        if not self.config_data.get('text_triggers'):
            response += "Tidak ada pemicu teks yang terdaftar.\n"
        else:
            for channel_id, triggers in self.config_data['text_triggers'].items():
                response += f"- <#{channel_id}>:\n"
                if not triggers:
                    response += "  Tidak ada pemicu di channel ini.\n"
                else:
                    for trigger_phrase, emojis in triggers.items():
                        response += f"  - `\"{trigger_phrase}\"`: {' '.join(emojis)}\n"
        
        await ctx.send(response)

    @commands.command(name='textset')
    @commands.check(is_allowed_user)
    @commands.guild_only()
    async def set_text_reaction(self, ctx: commands.Context, channel_id: int, trigger_phrase: str, *emojis: str):
        if not emojis or len(emojis) > 30:
            return await ctx.send("Gagal: Minimal 1 dan maksimal 30 emoji harus diberikan.")

        channel_id_str = str(channel_id)
        if channel_id_str not in self.config_data['text_triggers']:
            self.config_data['text_triggers'][channel_id_str] = {}
        
        self.config_data['text_triggers'][channel_id_str][trigger_phrase.lower()] = list(emojis)
        save_apreciator_config(self.config_data)
        log.info(f"TextReact '{trigger_phrase}' di <#{channel_id}> diatur oleh {ctx.author.name} (ID: {ctx.author.id}).")
        await ctx.send(f"✅ Reaksi TextReact untuk `\"{trigger_phrase}\"` di <#{channel_id}> berhasil diatur: {' '.join(emojis)}")

    @set_text_reaction.error
    async def set_text_reaction_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Penggunaan tidak benar: `/textset <channel_id> \"teks pemicu\" <emoji1> [emoji2] ...`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Gagal: Pastikan ID channel adalah angka yang valid dan teks pemicu diapit tanda kutip.")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("⛔ Kamu tidak memiliki izin Administrator untuk menggunakan perintah ini.")
        else:
            log.error(f"Error di perintah /textset (oleh {ctx.author.name}, Guild: {ctx.guild.id}): {error}", exc_info=True)
            await ctx.send("❌ Terjadi kesalahan internal saat memproses perintah ini.")

    @commands.command(name='textrem')
    @commands.check(is_allowed_user)
    @commands.guild_only()
    async def remove_text_reaction(self, ctx: commands.Context, channel_id: int, trigger_phrase: str):
        channel_id_str = str(channel_id)
        if channel_id_str in self.config_data['text_triggers'] and \
           trigger_phrase.lower() in self.config_data['text_triggers'][channel_id_str]:
            del self.config_data['text_triggers'][channel_id_str][trigger_phrase.lower()]
            if not self.config_data['text_triggers'][channel_id_str]:
                del self.config_data['text_triggers'][channel_id_str]
            save_apreciator_config(self.config_data)
            log.info(f"TextReact '{trigger_phrase}' di <#{channel_id}> dihapus oleh {ctx.author.name} (ID: {ctx.author.id}).")
            await ctx.send(f"✅ Reaksi TextReact untuk `\"{trigger_phrase}\"` di <#{channel_id}> berhasil dihapus.")
        else:
            await ctx.send(f"❌ Gagal: Pemicu `\"{trigger_phrase}\"` di channel <#{channel_id}> tidak ditemukan.")

    @remove_text_reaction.error
    async def remove_text_reaction_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Penggunaan tidak benar: `/textrem <channel_id> \"teks pemicu\"`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Gagal: Pastikan ID channel adalah angka yang valid dan teks pemicu diapit tanda kutip.")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("⛔ Kamu tidak memiliki izin Administrator untuk menggunakan perintah ini.")
        else:
            log.error(f"Error di perintah /textrem (oleh {ctx.author.name}, Guild: {ctx.guild.id}): {error}", exc_info=True)
            await ctx.send("❌ Terjadi kesalahan internal saat memproses perintah ini.")

    @commands.command(name='msgadd')
    @commands.check(is_allowed_user)
    @commands.guild_only()
    async def add_message_reaction(self, ctx: commands.Context, channel_id: int, message_id: int, *emojis: str):
        if not emojis or len(emojis) > 30:
            return await ctx.send("Gagal: Minimal 1 dan maksimal 30 emoji harus diberikan.")
        
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(channel_id)
            
            message = await channel.fetch_message(message_id)
            await self._add_reactions_ordered(message, list(emojis))
            log.info(f"Reaksi ditambahkan ke pesan ID {message_id} di <#{channel_id}> oleh {ctx.author.name} (ID: {ctx.author.id}).")
            await ctx.send(f"✅ Reaksi berhasil ditambahkan ke pesan ID `{message_id}` di <#{channel_id}>.")
        except discord.NotFound:
            await ctx.send("❌ Gagal: Channel atau Pesan tidak ditemukan. Pastikan ID benar dan bot bisa melihatnya.")
        except discord.Forbidden:
            await ctx.send("❌ Gagal: Bot tidak memiliki izin untuk melihat channel atau menambahkan reaksi di sana.")
        except discord.HTTPException as e:
            log.error(f"Error HTTP di /msgadd (oleh {ctx.author.name}, Guild: {ctx.guild.id}): {e}", exc_info=True)
            await ctx.send(f"❌ Terjadi kesalahan Discord API: {e}")
        except Exception as e:
            log.error(f"Error tak terduga di /msgadd (oleh {ctx.author.name}, Guild: {ctx.guild.id}): {e}", exc_info=True)
            await ctx.send(f"❌ Terjadi error tak terduga: {e}")
    
    @add_message_reaction.error
    async def add_message_reaction_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Penggunaan tidak benar: `/msgadd <channel_id> <message_id> <emoji1> [emoji2] ...`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Gagal: Pastikan ID channel dan message adalah angka yang valid.")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("⛔ Kamu tidak memiliki izin Administrator untuk menggunakan perintah ini.")
        else:
            log.error(f"Error di perintah /msgadd: {error}", exc_info=True)
            await ctx.send("❌ Terjadi kesalahan saat memproses perintah ini.")

    @commands.command(name='msgrem')
    @commands.check(is_allowed_user)
    @commands.guild_only()
    async def remove_message_reaction(self, ctx: commands.Context, channel_id: int, message_id: int, *emojis: str):
        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            
            if not emojis:
                bot_reactions_on_message = [r for r in message.reactions if r.me]
                if not bot_reactions_on_message:
                    return await ctx.send(f"ℹ️ Bot tidak memiliki reaksi pada pesan ID `{message_id}` di <#{channel_id}>.")

                for reaction in bot_reactions_on_message:
                    await message.remove_reaction(reaction.emoji, self.bot.user)
                log.info(f"Semua reaksi bot dihapus dari pesan ID {message_id} di <#{channel_id}> oleh {ctx.author.name} (ID: {ctx.author.id}).")
                await ctx.send(f"✅ Semua reaksi bot berhasil dihapus dari pesan ID `{message_id}` di <#{channel_id}>.")
            else:
                for emoji_str in emojis:
                    try:
                        await message.remove_reaction(emoji_str, self.bot.user)
                    except discord.NotFound:
                        await ctx.send(f"ℹ️ Emoji '{emoji_str}' tidak ditemukan pada pesan ID `{message_id}`.")
                    except Exception as e:
                        log.error(f"Error menghapus reaksi '{emoji_str}' dari pesan {message_id}: {e}", exc_info=True)
                        await ctx.send(f"❌ Gagal menghapus emoji '{emoji_str}': {e}")
                log.info(f"Reaksi spesifik dihapus dari pesan ID {message_id} di <#{channel_id}> oleh {ctx.author.name} (ID: {ctx.author.id}).")
                await ctx.send(f"✅ Reaksi spesifik berhasil diproses untuk pesan ID `{message_id}` di <#{channel_id}>.")
            
        except discord.NotFound:
            await ctx.send("❌ Gagal: Channel atau Pesan tidak ditemukan. Pastikan ID benar dan bot bisa melihatnya.")
        except discord.Forbidden:
            await ctx.send("❌ Gagal: Bot tidak memiliki izin untuk melihat channel atau menghapus reaksi di sana.")
        except discord.HTTPException as e:
            log.error(f"Error HTTP di /msgrem (oleh {ctx.author.name}, Guild: {ctx.guild.id}): {e}", exc_info=True)
            await ctx.send(f"❌ Terjadi kesalahan Discord API: {e}")
        except Exception as e:
            log.error(f"Error tak terduga di /msgrem (oleh {ctx.author.name}, Guild: {ctx.guild.id}): {e}", exc_info=True)
            await ctx.send(f"❌ Terjadi error tak terduga: {e}")

    @remove_message_reaction.error
    async def remove_message_reaction_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Penggunaan tidak benar: `/msgrem <channel_id> <message_id> [emoji1] [emoji2] ...`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Gagal: Pastikan ID channel dan message adalah angka yang valid.")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("⛔ Kamu tidak memiliki izin Administrator untuk menggunakan perintah ini.")
        else:
            log.error(f"Error di perintah /msgrem: {error}", exc_info=True)
            await ctx.send("❌ Terjadi kesalahan saat memproses perintah ini.")
            
async def setup(bot):
    """Fungsi yang dipanggil saat cog dimuat oleh bot utama."""
    await bot.add_cog(Apreciator(bot))
    log.info("Cog Apreciator berhasil dimuat dan siap!")
