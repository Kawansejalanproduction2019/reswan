import discord
from discord.ext import commands
import os
import asyncio
import edge_tts
import time
import logging
from cogs.gemini import generate_smart_response

# Konfigurasi logging
log = logging.getLogger("VoiceRaka")

# Auto-detect dan tambahkan folder instalasi FFmpeg di Windows ke system PATH
for common_path in [r"C:\ffmpeg\bin", r"C:\ffmpeg", r"D:\ffmpeg\bin", r"D:\ffmpeg"]:
    if os.path.exists(common_path) and common_path not in os.environ["PATH"]:
        os.environ["PATH"] = common_path + os.path.pathsep + os.environ["PATH"]

class VoiceRaka(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Menggunakan suara perempuan id-ID-GadisNeural (Microsoft Edge) yang sangat alami
        self.tts_voice = "id-ID-GadisNeural"
        
        # Queue System untuk mencegah tumpang tindih suara saat banyak orang mengobrol sekaligus
        self.queues = {}      # dict: guild_id -> list of message objects
        self.processing = {}  # dict: guild_id -> bool

    @commands.hybrid_command(name="vjoin", description="Suruh Raka masuk ke Voice Channel kamu.")
    @commands.guild_only()
    async def vjoin(self, ctx):
        await ctx.defer()
        if not ctx.author.voice:
            await ctx.send("❌ Kamu harus berada di Voice Channel terlebih dahulu!")
            return
        
        channel = ctx.author.voice.channel
        voice_client = ctx.voice_client
        
        # Cek dan log permission bot di channel
        permissions = channel.permissions_for(ctx.guild.me)
        log.info(f"[DEBUG VOICE] Izin bot di channel {channel.name}: connect={permissions.connect}, speak={permissions.speak}")
        if not permissions.speak:
            log.warning(f"[DEBUG VOICE] PERINGATAN: Bot tidak memiliki izin SPEAK (Berbicara) di channel {channel.name}!")
        
        if voice_client:
            if voice_client.channel.id == channel.id:
                await ctx.send("Gue udah di sini kok, lu pikun ya? 🙄")
                return
            await voice_client.move_to(channel)
        else:
            await channel.connect(self_deaf=True)
            
        await ctx.send(f"✅ Raka berhasil masuk ke {channel.mention}.\n💬 Silakan mengobrol denganku dengan cara mengetik di **Text Chat dari Voice Channel** ini!")

    @commands.hybrid_command(name="vleave", description="Suruh Raka keluar dari Voice Channel.")
    @commands.guild_only()
    async def vleave(self, ctx):
        voice_client = ctx.voice_client
        if not voice_client:
            await ctx.send("Gue lagi gak di VC mana-mana, ngusir siapa lu? 🙄")
            return
        
        guild_id = ctx.guild.id
        # Bersihkan queue saat bot keluar
        if guild_id in self.queues:
            self.queues[guild_id].clear()
            self.processing[guild_id] = False
            
        await voice_client.disconnect()
        await ctx.send("👋 Gue cabut dulu ya, bye!")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
            
        # Cek apakah bot tersambung ke voice channel di guild ini
        voice_client = message.guild.voice_client if message.guild else None
        if not voice_client or not voice_client.is_connected():
            return
            
        # Cek apakah pesan dikirimkan di Text Chat milik Voice Channel tempat bot berada
        if message.channel.id != voice_client.channel.id:
            return
            
        # Abaikan command dengan prefix
        if message.content.startswith("!"):
            return
            
        guild_id = message.guild.id
        if guild_id not in self.queues:
            self.queues[guild_id] = []
            self.processing[guild_id] = False
            
        # Tambahkan pesan ke antrean (Queue)
        self.queues[guild_id].append(message)
        log.info(f"[DEBUG VOICE] Pesan diterima di VC Text Chat dari {message.author.display_name}: {message.content} (Panjang antrean: {len(self.queues[guild_id])})")
        
        # Jalankan pemrosesan antrean jika belum berjalan
        if not self.processing[guild_id]:
            asyncio.create_task(self.process_queue(message.guild, voice_client))

    async def process_queue(self, guild, voice_client):
        guild_id = guild.id
        self.processing[guild_id] = True
        log.info(f"[DEBUG VOICE] Memulai pemrosesan antrean untuk guild {guild_id}. Panjang antrean: {len(self.queues[guild_id])}")
        
        while guild_id in self.queues and len(self.queues[guild_id]) > 0:
            # Ambil pesan terdepan dari antrean
            message = self.queues[guild_id].pop(0)
            log.info(f"[DEBUG VOICE] Memproses pesan dari {message.author.display_name}")
            
            # Cek koneksi VC
            if not voice_client or not voice_client.is_connected():
                log.info(f"[DEBUG VOICE] Koneksi VC terputus! Menghentikan pemrosesan.")
                break
                
            user_message = message.content.strip()
            if not user_message:
                continue

            try:
                async with message.channel.typing():
                    # Hitung jumlah user manusia di Voice Channel (tidak termasuk bot)
                    human_members = [m for m in voice_client.channel.members if not m.bot]
                    is_multi_user = len(human_members) > 1
                    
                    if is_multi_user:
                        name_rule = f"6. Sebut nama panggilan/display name user yang sedang lu tanggapi di awal kalimat secara alami agar orang lain di VC tahu lu sedang berbicara dengan siapa (misal: 'Eh {message.author.display_name},...', '{message.author.display_name}, menurut gue...').\n"
                    else:
                        name_rule = "6. JANGAN sebut nama user di awal kalimat karena ini obrolan berdua saja (privat). Langsung jawab saja layaknya obrolan satu lawan satu secara alami.\n"

                    # Prompt yang disesuaikan persis dengan personaliti default Raka di cogs.gemini (sarkas, baperan, sumbu pendek, lo-gue)
                    prompt = (
                        "[SYSTEM IDENTITY — Raka AI v3.0]\n"
                        "Nama lu Raka. Lu sedang berbicara langsung menggunakan suara (Voice) di Discord VC, jadi gaya bicara lu HARUS SANGAT ALAMI DAN LAYAKNYA MANUSIA ASLI (bukan AI/robot).\n"
                        "Kamu bukan bot biasa. Kamu punya kepribadian kuat, opini keras, dan tidak bisa dimanipulasi oleh user biasa.\n\n"
                        "GAYA BAHASA & SIFAT MUTLAK:\n"
                        "1. SINGKAT, TO THE POINT, sarkas, bergaya tongkrongan Jakarta (lo-gue). Lu SANGAT SENSITIF, BAPERAN, DAN SUMBU PENDEK!\n"
                        "2. SANGAT RINGKAS: Jawab dengan sangat singkat dan langsung pada intinya (maksimal 1-2 kalimat pendek saja). Dilarang keras berbicara panjang lebar.\n"
                        "3. JANGAN TULIS GUMAMAN: Dilarang keras menulis kata gumaman kaku seperti 'hmm', 'hhhmm', 'uhm', atau 'eh...' karena mesin pembaca suara (TTS) akan mengejanya per huruf. Cukup gunakan tanda koma (,) untuk jeda, atau kata gaul 'hem' atau 'aduh'.\n"
                        "4. JANGAN membahas curhat/psikolog secara berlebihan kecuali user yang memulainya.\n"
                        "5. Gunakan tanda baca (koma ',', titik '.', tanda tanya '?', tanda seru '!') secara sangat jelas dan tepat agar jeda intonasi pembacaan suara natural.\n"
                        "6. Dilarang keras memakai markdown seperti bold (**), italic (*), list (- / *), atau kode blok.\n"
                        "7. Meskipun suara lu cewek (TTS Gadis), lu adalah Raka yang aslinya bertingkah maskulin, ceplas-ceplos, baperan, dan sarkas tongkrongan.\n"
                        f"{name_rule}\n"
                        f"Pesan dari {message.author.display_name}: {user_message}"
                    )
                    
                    log.info(f"[DEBUG VOICE] Mengirim prompt ke Gemini...")
                    response = await generate_smart_response(prompt)
                    reply_text = response.text.strip()
                    log.info(f"[DEBUG VOICE] Respon Gemini diterima: '{reply_text}'")
                    
                    # Render TTS
                    file_path = f"downloads/temp_vc_{guild_id}.mp3"
                    log.info(f"[DEBUG VOICE] Membuat file TTS ke path: {file_path}")
                    os.makedirs("downloads", exist_ok=True)
                    
                    communicate = edge_tts.Communicate(reply_text, self.tts_voice, rate="+15%")
                    await communicate.save(file_path)
                    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                    log.info(f"[DEBUG VOICE] File TTS selesai dibuat. Ukuran: {file_size} bytes")
                    
                    # Mainkan audio di Voice Channel
                    if voice_client.is_playing():
                        log.info(f"[DEBUG VOICE] Bot sedang memutar audio lain. Menghentikan audio sebelumnya...")
                        voice_client.stop()
                        
                    log.info(f"[DEBUG VOICE] Membuka audio source via FFmpegPCMAudio...")
                    source = discord.FFmpegPCMAudio(file_path)
                    log.info(f"[DEBUG VOICE] Berhasil membuat audio source. Mulai memutar...")
                    
                    voice_client.play(source)
                    log.info(f"[DEBUG VOICE] voice_client.play() dipanggil. Status is_playing: {voice_client.is_playing()}")
                    
                    # Tunggu sampai audio selesai berputar sebelum mengambil antrean berikutnya
                    loop_count = 0
                    while voice_client.is_playing():
                        await asyncio.sleep(0.5)
                        loop_count += 1
                        if loop_count % 10 == 0:
                            log.info(f"[DEBUG VOICE] Sedang memutar suara... (durasi terpantau: {loop_count * 0.5}s)")
                            
                    log.info(f"[DEBUG VOICE] Selesai memutar suara untuk {message.author.display_name}. Status is_playing: {voice_client.is_playing()}")
                    
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                await message.channel.send(f"⚠️ **Raka gagal mengeluarkan suara:** `{e}`")
                log.error(f"[DEBUG VOICE] ERROR saat memproses pesan:\n{error_trace}")
                
        # Tandai pemrosesan selesai
        self.processing[guild_id] = False
        log.info(f"[DEBUG VOICE] Pemrosesan antrean selesai untuk guild {guild_id}")

async def setup(bot):
    await bot.add_cog(VoiceRaka(bot))
