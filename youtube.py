import discord
from discord.ext import commands
import requests
import re
from typing import Optional

class YoutubeControlCog(commands.Cog):
    """Cog yang berisi perintah untuk mengontrol bot YouTube."""

    def __init__(self, bot):
        self.bot = bot
        # Ganti localhost dengan IP server jika bot YouTube di server lain
        self.youtube_bot_api_url = "http://localhost:5000"

    @commands.command(name="monitor")
    @commands.has_permissions(administrator=True)
    async def monitor(self, ctx, live_url: str):
        """Memulai pemantauan live chat YouTube dengan URL."""
        try:
            payload = {"url": live_url}
            response = requests.post(f"{self.youtube_bot_api_url}/start_monitoring", json=payload)
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube. Pastikan bot YouTube sedang berjalan.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan saat memulai pemantauan: {e}")

    @commands.command(name="stopmonitor")
    @commands.has_permissions(administrator=True)
    async def stopmonitor(self, ctx):
        """Menghentikan pemantauan live chat."""
        try:
            response = requests.post(f"{self.youtube_bot_api_url}/stop_monitoring")
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube. Pastikan bot YouTube sedang berjalan.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan saat menghentikan pemantauan: {e}")

    @commands.command(name="addcommand")
    @commands.has_permissions(administrator=True)
    async def addcommand(self, ctx, trigger: str, *, response: str):
        """Menambahkan custom command untuk bot YouTube."""
        try:
            payload = {"trigger": trigger, "response": response}
            response = requests.post(f"{self.youtube_bot_api_url}/add_command", json=payload)
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube. Pastikan bot YouTube sedang berjalan.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

    @commands.command(name="addauto")
    @commands.has_permissions(administrator=True)
    async def addauto(self, ctx, *, message: str):
        """Menambahkan pesan otomatis untuk bot YouTube."""
        try:
            payload = {"message": message}
            response = requests.post(f"{self.youtube_bot_api_url}/add_automessage", json=payload)
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube. Pastikan bot YouTube sedang berjalan.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

    @commands.command(name="setautointerval")
    @commands.has_permissions(administrator=True)
    async def setautointerval(self, ctx, minutes: int):
        """Mengatur interval pesan otomatis dalam menit."""
        try:
            payload = {"interval": minutes}
            response = requests.post(f"{self.youtube_bot_api_url}/update_interval", json=payload)
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube. Pastikan bot YouTube sedang berjalan.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

    ---
    
    ## Tambahan Perintah
    
    Perintah-perintah berikut telah ditambahkan untuk membantu Anda mengelola bot YouTube:
    
    * **!viewconfigs** atau **!listconfigs**: Menampilkan semua custom command dan pesan otomatis yang telah Anda atur.
    * **!delcommand `<trigger>`**: Menghapus custom command dengan nama pemicu (`trigger`) yang Anda sebutkan.
    * **!reset**: Mereset semua konfigurasi (custom commands dan pesan otomatis) secara keseluruhan.

    @commands.command(name="viewconfigs", aliases=['listconfigs'])
    @commands.has_permissions(administrator=True)
    async def view_configs(self, ctx):
        try:
            response = requests.get(f"{self.youtube_bot_api_url}/get_all_configs")
            response_json = response.json()

            embed = discord.Embed(title="Konfigurasi Bot YouTube", color=discord.Color.blue())
            
            commands_list = response_json.get('commands', [])
            if commands_list:
                commands_text = "\n".join([f"**`!{cmd['trigger']}`** → {cmd['response']}" for cmd in commands_list])
                embed.add_field(name="Custom Commands", value=commands_text, inline=False)
            else:
                embed.add_field(name="Custom Commands", value="Tidak ada custom command yang diset.", inline=False)

            automessages_list = response_json.get('automessages', [])
            if automessages_list:
                automessages_text = "\n".join([f"**`#{i+1}`** → {msg['message']}" for i, msg in enumerate(automessages_list)])
                embed.add_field(name="Auto Messages", value=automessages_text, inline=False)
            else:
                embed.add_field(name="Auto Messages", value="Tidak ada auto message yang diset.", inline=False)
            
            await ctx.send(embed=embed)

        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

    @commands.command(name="delcommand")
    @commands.has_permissions(administrator=True)
    async def del_command(self, ctx, trigger: str):
        try:
            payload = {"trigger": trigger}
            response = requests.post(f"{self.youtube_bot_api_url}/del_command", json=payload)
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

    @commands.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def reset_all(self, ctx):
        try:
            response = requests.post(f"{self.youtube_bot_api_url}/reset_all_configs")
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

# Fungsi ini harus ada agar bot utama bisa memuat cog
async def setup(bot):
    await bot.add_cog(YoutubeControlCog(bot))
