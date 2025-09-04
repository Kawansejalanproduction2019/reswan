import discord
from discord.ext import commands
import requests
import re

class YoutubeControlCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.youtube_bot_api_url = "http://localhost:5000"

    def extract_video_id(self, url: str) -> str | None:
        match = re.search(r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})', url)
        if match:
            return match.group(1)
        return None

    @commands.command(name="monitor")
    @commands.has_permissions(administrator=True)
    async def monitor(self, ctx, live_url: str):
        video_id = self.extract_video_id(live_url)
        if not video_id:
            await ctx.send("URL YouTube tidak valid. Mohon berikan URL yang benar.")
            return

        try:
            payload = {"video_id": video_id}
            response = requests.post(f"{self.youtube_bot_api_url}/start_monitoring", json=payload)
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

    @commands.command(name="stopmonitor")
    @commands.has_permissions(administrator=True)
    async def stopmonitor(self, ctx):
        try:
            response = requests.post(f"{self.youtube_bot_api_url}/stop_monitoring")
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

    @commands.command(name="addcommand")
    @commands.has_permissions(administrator=True)
    async def addcommand(self, ctx, trigger: str, *, response: str):
        try:
            payload = {"trigger": trigger, "response": response}
            response = requests.post(f"{self.youtube_bot_api_url}/add_command", json=payload)
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

    @commands.command(name="addauto")
    @commands.has_permissions(administrator=True)
    async def addauto(self, ctx, *, message: str):
        try:
            payload = {"message": message}
            response = requests.post(f"{self.youtube_bot_api_url}/add_automessage", json=payload)
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

    @commands.command(name="setautointerval")
    @commands.has_permissions(administrator=True)
    async def setautointerval(self, ctx, minutes: int):
        try:
            payload = {"interval": minutes}
            response = requests.post(f"{self.youtube_bot_api_url}/update_interval", json=payload)
            response_json = response.json()
            await ctx.send(response_json['message'])
        except requests.exceptions.ConnectionError:
            await ctx.send("Gagal terhubung ke bot YouTube.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")

async def setup(bot):
    await bot.add_cog(YoutubeControlCog(bot))
