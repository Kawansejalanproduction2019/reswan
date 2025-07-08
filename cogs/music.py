import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import functools
from discord import FFmpegPCMAudio
from discord.utils import get
from lyricsgenius import Genius
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Konfigurasi Genius API untuk lirik
GENIUS_API_TOKEN = os.getenv("GENIUS_API")
genius = Genius(GENIUS_API_TOKEN)

# Spotify API setup
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

# YTDL dan FFMPEG opsi
ytdl_opts = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'cookiefile': 'cookies.txt',
    'quiet': True,
    'default_search': 'ytsearch',  # ⬅️ Tambahkan ini
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'noplaylist': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
        'preferredquality': '192',
    }],
}


FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -b:a 192k'
}

ytdl = yt_dlp.YoutubeDL(ytdl_opts)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.8):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}

    def get_queue(self, guild_id):
        return self.queues.setdefault(guild_id, [])

    async def play_next(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if not queue:
            await ctx.send("Antrian kosong. Keluar dari voice channel.")
            await ctx.voice_client.disconnect()
            return

        url = queue.pop(0)
        try:
            source = await YTDLSource.from_url(url, loop=self.bot.loop)
            ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop))
            await ctx.send(f'Now playing: **{source.title}**')
        except Exception as e:
            await ctx.send(f'Gagal memutar lagu: {e}')

    @commands.command(name="resjoin")
    async def join(self, ctx):
        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                return await ctx.send("Bot sudah berada di voice channel lain. Harap keluarkan dulu.")
            return
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
            await ctx.send(f"Joined {ctx.author.voice.channel.name}")
        else:
            await ctx.send("Kamu harus berada di voice channel dulu.")

    @commands.command(name="resp")
    async def play(self, ctx, *, query):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            if not ctx.voice_client:
                return

        urls = []

        if "open.spotify.com" in query:
            if "track" in query:
                track = spotify.track(query)
                search_query = f"{track['name']} {track['artists'][0]['name']}"
                urls.append(search_query)
            elif "playlist" in query:
                results = spotify.playlist_tracks(query)
                for item in results['items']:
                    track = item['track']
                    search_query = f"{track['name']} {track['artists'][0]['name']}"
                    urls.append(search_query)
            else:
                return await ctx.send("Spotify link tidak dikenali.")
        else:
            urls.append(query)

        queue = self.get_queue(ctx.guild.id)
        queue.extend(urls)

        if not ctx.voice_client.is_playing():
            await self.play_next(ctx)
        else:
            await ctx.send(f"Ditambahkan ke antrian: {len(urls)} lagu.")

    @commands.command(name="resskip")
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ Skip lagu.")
        else:
            await ctx.send("Tidak ada lagu yang sedang diputar.")

    @commands.command(name="respause")
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Lagu dijeda.")

    @commands.command(name="resresume")
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Lanjut lagu.")

    @commands.command(name="resstop")
    async def stop(self, ctx):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            self.queues[ctx.guild.id] = []
            await ctx.send("⏹️ Stop dan keluar dari voice.")

    @commands.command(name="resqueue")
    async def queue(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            msg = "\n".join([f"{i+1}. {q}" for i, q in enumerate(queue)])
            await ctx.send(f"🎶 Antrian lagu:\n{msg}")
        else:
            await ctx.send("Antrian kosong.")

    @commands.command(name="reslyrics")
    async def lyrics(self, ctx, *, song_name):
        try:
            song = genius.search_song(song_name)
            if song:
                await ctx.send(f"**{song.title} by {song.artist}**\n{song.lyrics[:1900]}")
            else:
                await ctx.send("Lirik tidak ditemukan.")
        except Exception as e:
            await ctx.send(f"Gagal mengambil lirik: {e}")

async def setup(bot):
    await bot.add_cog(Music(bot))
