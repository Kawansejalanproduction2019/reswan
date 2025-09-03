import discord
from discord.ext import commands
import requests

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

# Fungsi ini harus ada agar bot utama bisa memuat cog
async def setup(bot):
    await bot.add_cog(YoutubeControlCog(bot))
