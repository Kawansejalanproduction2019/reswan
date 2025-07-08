import discord
from discord.ext import tasks, commands
import aiohttp
import os

class LiveStream(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = int(os.getenv("DISCORD_CHANNEL_ID"))
        self.api_key = os.getenv("YOUTUBE_API_KEY")
        self.youtube_channel_id = os.getenv("YOUTUBE_CHANNEL_ID")
        self.notified_video_id = None
        self.check_live_stream.start()

    def cog_unload(self):
        self.check_live_stream.cancel()

    @tasks.loop(seconds=15)  # Cek setiap 15 detik
    async def check_live_stream(self):
        url = (
            f"https://www.googleapis.com/youtube/v3/search?"
            f"part=snippet&channelId={self.youtube_channel_id}&eventType=live"
            f"&type=video&key={self.api_key}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                if "items" in data and data["items"]:
                    video = data["items"][0]
                    video_id = video["id"]["videoId"]
                    title = video["snippet"]["title"]
                    channel_title = video["snippet"]["channelTitle"]
                    video_url = f"https://www.youtube.com/watch?v={video_id}"

                    if video_id != self.notified_video_id:
                        self.notified_video_id = video_id

                        channel = self.bot.get_channel(self.channel_id)
                        if channel:
                            message = (
                                "@everyone 🚨 **LIVE ALERT!**\n"
                                f"📺 **{channel_title}** is now live!\n"
                                f"🎬 **{title}**\n"
                                f"{video_url}"  # Ini akan munculin preview
                            )
                            await channel.send(message)

async def setup(bot):
    await bot.add_cog(LiveStream(bot))
