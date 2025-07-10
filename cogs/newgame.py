import discord
from discord.ext import commands, tasks
import json
import random
import asyncio
import os
from datetime import datetime, time, timedelta
import pytz # Import pytz untuk zona waktu

# --- Helper Functions to handle JSON data from the bot's root directory ---
def load_json_from_root(file_path):
    """Memuat data JSON dari direktori utama bot dengan aman."""
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        full_path = os.path.join(base_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True) # Pastikan direktori ada
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[{datetime.now()}] [DEBUG HELPER] Peringatan: File {full_path} tidak ditemukan. Mengembalikan nilai default.")
        # Mengembalikan struktur data kosong yang sesuai berdasarkan nama file
        if 'questions_hangman' in file_path or 'questions_resipa' in file_path or 'sambung_kata_words' in file_path:
            return []
        elif any(name in file_path for name in ['bank_data', 'level_data']):
            return {}
        # Untuk file data game yang berisi list, termasuk donation_buttons
        if 'donation_buttons.json' in file_path:
            return [] # Default list kosong untuk tombol donasi
        return [] # Default fallback for lists
    except json.JSONDecodeError as e:
        print(f"[{datetime.now()}] [DEBUG HELPER] Peringatan: File {full_path} rusak (JSON tidak valid). Error: {e}. Mengembalikan nilai default.")
        if 'questions_hangman' in file_path or 'questions_resipa' in file_path or 'sambung_kata_words' in file_path:
            return []
        elif any(name in file_path for name in ['bank_data', 'level_data']):
            return {}
        if 'donation_buttons.json' in file_path:
            return []
        return []


def save_json_to_root(data, file_path):
    """Menyimpan data ke file JSON di direktori utama bot."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    full_path = os.path.join(base_dir, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True) # Pastikan direktori ada
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# --- New DonationView - MODIFIED TO LOAD BUTTONS FROM JSON ---
class DonationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Keep buttons active indefinitely
        self.load_donation_buttons()

    def load_donation_buttons(self):
        # Path relatif ke root proyek
        # Jika file tidak ditemukan atau kosong, load_json_from_root akan mengembalikan []
        donation_buttons_data = load_json_from_root('data/donation_buttons.json')
        
        # Jika data yang dimuat kosong, gunakan tombol default hardcoded
        if not donation_buttons_data:
            print(f"[{datetime.now()}] [DonationView] File 'data/donation_buttons.json' kosong atau tidak ditemukan. Menggunakan tombol default.")
            default_buttons = [
                {"label": "Dukung via Bagi-Bagi!", "url": "https://bagibagi.co/Rh7155"},
                {"label": "Donasi via Saweria!", "url": "https://saweria.co/RH7155"}
            ]
            donation_buttons_data = default_buttons

        # Tambahkan tombol ke view
        for button_info in donation_buttons_data:
            if "label" in button_info and "url" in button_info:
                button = discord.ui.Button(
                    label=button_info["label"],
                    style=discord.ButtonStyle.link,
                    url=button_info["url"]
                )
                self.add_item(button)
            else:
                print(f"[{datetime.now()}] [DonationView] Peringatan: Format tombol donasi tidak valid: {button_info}")

class GameLanjutan(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Game State Management
        self.active_resacak_games = {} # Untuk !resacak
        self.active_resipa_games = {}  # Untuk !resipa
        self.active_sambung_games = {}
        
        # Load Data
        # questions_hangman.json sekarang akan berisi list of dicts (word, category, clue)
        self.resacak_questions = load_json_from_root('data/questions_hangman.json') 
        # questions_resipa.json juga akan berisi list of dicts (word, category, clue)
        self.resipa_questions = load_json_from_root('data/questions_resipa.json') 
        self.sambung_kata_words = load_json_from_root('data/sambung_kata_words.json')

        # Game Configuration
        self.game_channel_id = 765140300145360896 # ID channel yang diizinkan untuk kuis
        self.resacak_reward = {"rsw": 50, "exp": 100}
        self.resipa_reward = {"rsw": 50, "exp": 100}
        self.sambung_kata_winner_reward = {"rsw": 50, "exp": 100}
        self.resacak_time_limit = 30 # Detik per soal resacak
        self.resipa_time_limit = 30  # Detik per soal resipa
        self.sambung_kata_time_limit = 20 # Detik per giliran sambung kata

        # Untuk melacak percobaan jawaban dan cooldown kuis
        self.quiz_attempts_per_question = {} # {channel_id: {user_id: attempts}}
        self.cooldown_users = {} # {user_id: datetime_obj}

    def cog_unload(self):
        self.post_daily_puzzle.cancel()

    def get_anomaly_multiplier(self):
        """Mengecek apakah ada anomali EXP boost aktif dari cog DuniaHidup."""
        dunia_cog = self.bot.get_cog('DuniaHidup')
        if dunia_cog and dunia_cog.active_anomaly and dunia_cog.active_anomaly.get('type') == 'exp_boost':
            return dunia_cog.active_anomaly.get('effect', {}).get('multiplier', 1)
        return 1

    async def give_rewards_with_bonus_check(self, user: discord.Member, reward_base: dict, channel: discord.TextChannel):
        """Fungsi baru yang menghitung bonus dan memberikan hadiah."""
        anomaly_multiplier = self.get_anomaly_multiplier()
        
        final_reward = {
            "rsw": int(reward_base['rsw'] * anomaly_multiplier),
            "exp": int(reward_base['exp'] * anomaly_multiplier)
        }
        
        # Logika give_rewards disatukan di sini agar lebih efisien
        user_id_str, guild_id_str = str(user.id), str(user.guild.id)
        bank_data = load_json_from_root('data/bank_data.json')
        level_data = load_json_from_root('data/level_data.json')

        bank_data.setdefault(user_id_str, {'balance': 0, 'debt': 0})['balance'] += final_reward.get('rsw', 0)
        
        guild_data = level_data.setdefault(guild_id_str, {})
        user_data = guild_data.setdefault(user_id_str, {'exp': 0, 'level': 1})
        user_data.setdefault('exp', 0)
        user_data['exp'] += final_reward.get('exp', 0)

        save_json_to_root(bank_data, 'data/bank_data.json')
        save_json_to_root(level_data, 'data/level_data.json')
        
        if anomaly_multiplier > 1 and channel:
            await channel.send(f"✨ **BONUS ANOMALI!** {user.mention} mendapatkan hadiah yang dilipatgandakan!", delete_after=15)

    # --- FUNGSI PENANGANAN AKHIR GAME UNTUK DONASI ---
    async def end_game_cleanup(self, channel_id, game_type, channel_obj=None):
        """
        Membersihkan status game yang aktif dan menampilkan tombol donasi.
        game_type bisa 'resacak', 'resipa', atau 'sambung_kata'.
        """
        if game_type == 'resacak' and channel_id in self.active_resacak_games:
            self.active_resacak_games.pop(channel_id, None)
            print(f"[{datetime.now()}] Game Resacak di channel {channel_id} telah selesai.")
        elif game_type == 'resipa' and channel_id in self.active_resipa_games:
            self.active_resipa_games.pop(channel_id, None)
            print(f"[{datetime.now()}] Game Resipa di channel {channel_id} telah selesai.")
        elif game_type == 'sambung_kata' and channel_id in self.active_sambung_games:
            self.active_sambung_games.pop(channel_id, None)
            print(f"[{datetime.now()}] Game Sambung Kata di voice channel {channel_id} telah selesai.")
        
        # Reset quiz attempts and cooldowns for this channel (specifically for Siapakah Aku/Hitung Cepat)
        if channel_id in self.quiz_attempts_per_question:
            del self.quiz_attempts_per_question[channel_id]
        # Clear cooldowns for users who were in this channel's game
        for user_id in list(self.cooldown_users.keys()):
            # Only remove if the cooldown is tied to a user currently in the channel (simplified)
            # A more robust solution might tie cooldowns directly to game sessions
            if user_id in self.cooldown_users and (channel_obj and self.bot.get_user(user_id) in channel_obj.members):
                del self.cooldown_users[user_id]
                member = channel_obj.guild.get_member(user_id)
                if member:
                    try:
                        await member.timeout(None, reason="Game ended, cooldown lifted.")
                    except discord.Forbidden:
                        pass
                    except Exception as e:
                        print(f"[{datetime.now()}] Error removing timeout on cleanup for {member.display_name}: {e}")

        if channel_obj:
            donation_message = (
                "🎮 **Permainan Telah Usai!** Terima kasih sudah bermain bersama kami.\n\n"
                "Apakah kamu menikmati petualangan dan keseruan yang kami hadirkan?\n"
                "Dukung terus pengembangan bot ini agar kami bisa terus berinovasi dan "
                "memberikan pengalaman bermain yang lebih seru lagi!\n\n"
                "Donasi sekecil apa pun sangat berarti untuk kami! 🙏"
            )
            donation_view = DonationView()
            await channel_obj.send(donation_message, view=donation_view)


    # --- GAME 1: RESACAK (TEBAK KATA ACAK DENGAN KATEGORI & KISI-KISI) ---
    @commands.command(name="resacak", help="Mulai permainan Tebak Kata Acak (Resacak).")
    async def resacak(self, ctx):
        if ctx.channel.id != self.game_channel_id:
            return await ctx.send("Permainan ini hanya bisa dimainkan di channel yang ditentukan.", delete_after=10)
        if ctx.channel.id in self.active_resacak_games:
            return await ctx.send("Permainan Resacak sudah berlangsung. Mohon tunggu hingga selesai.", delete_after=10)
            
        embed = discord.Embed(title="🎲 Siap Bermain Resacak (Tebak Kata Acak)?", color=0x3498db)
        embed.description = (
            "Uji kecepatan berpikir dan kosakatamu dalam game seru ini!\n\n"
            "**Aturan Main:**\n"
            "1. Bot akan memberikan kata yang hurufnya diacak, dilengkapi **kategori** dan **kisi-kisi**.\n"
            "2. Tebak kata aslinya secepat mungkin.\n"
            f"3. Jawaban benar pertama mendapat **{self.resacak_reward['rsw']} RSWN** & **{self.resacak_reward['exp']} EXP**.\n"
            "4. Permainan terdiri dari 10 ronde.\n\n"
            "Klik tombol di bawah untuk memulai petualangan katamu!"
        )
        embed.set_thumbnail(url="https://raw.githubusercontent.com/Abogoboga04/OpenAI/main/AB6.jpeg")
        embed.set_footer(text="Hanya pemanggil perintah yang bisa memulai permainan.")
        
        view = discord.ui.View(timeout=60)
        start_button = discord.ui.Button(label="MULAI SEKARANG", style=discord.ButtonStyle.primary, emoji="▶️")

        async def start_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("Hanya pemanggil perintah yang bisa memulai permainan.", ephemeral=True)
            
            self.active_resacak_games[ctx.channel.id] = True
            await interaction.message.delete()
            await ctx.send(f"**Permainan Resacak Dimulai!** Diselenggarakan oleh {ctx.author.mention}", delete_after=10)
            await self.play_resacak_game(ctx)
            
        start_button.callback = start_callback
        view.add_item(start_button)
        await ctx.send(embed=embed, view=view)

    async def play_resacak_game(self, ctx):
        # Memastikan bank soal cukup
        if not self.resacak_questions or len(self.resacak_questions) < 10:
            await ctx.send("Maaf, bank soal Resacak tidak ditemukan atau tidak cukup. Pastikan ada minimal 10 soal di `data/questions_hangman.json` dengan format `word`, `category`, `clue`.")
            await self.end_game_cleanup(ctx.channel.id, 'resacak', ctx.channel)
            return
            
        questions_for_game = random.sample(self.resacak_questions, 10) 
        leaderboard = {}

        for i, question_data in enumerate(questions_for_game):
            word = question_data['word']
            category = question_data['category']
            clue = question_data['clue'] 
            
            correct_answer = word.lower()
            scrambled_word = "".join(random.sample(word, len(word)))

            embed = discord.Embed(title=f"📝 Soal #{i+1} - Tebak Kata Acak!", color=0x2ecc71)
            embed.add_field(name="Kategori", value=category, inline=True) 
            embed.add_field(name="Kata Teracak", value=f"## `{scrambled_word.upper()}`", inline=False)
            embed.add_field(name="Kisi-kisi", value=clue, inline=False) 
            embed.set_footer(text=f"Waktu terbatas: {self.resacak_time_limit} detik!")
            
            question_msg = await ctx.send(embed=embed)
            winner = await self.wait_for_answer_with_timer(ctx, correct_answer, question_msg, self.resacak_time_limit)

            if winner:
                await self.give_rewards_with_bonus_check(winner, self.resacak_reward, ctx.channel)
                await ctx.send(f"🎉 Selamat {winner.mention}! Jawabanmu benar!")
                leaderboard[winner.display_name] = leaderboard.get(winner.display_name, 0) + 1
            else:   
                await ctx.send(f"Waktu habis! Jawaban yang benar adalah: **{correct_answer.upper()}**.")

        await ctx.send("🏁 Permainan Resacak selesai! Terima kasih sudah bermain.")
        if leaderboard:
            sorted_lb = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
            desc = "\n".join([f"**#{n}.** {user}: {score} poin" for n, (user, score) in enumerate(sorted_lb, 1)])
            final_embed = discord.Embed(title="🏆 Papan Skor Akhir", description=desc, color=discord.Color.gold())
            await ctx.send(embed=final_embed)

        await self.end_game_cleanup(ctx.channel.id, 'resacak', ctx.channel)

    # --- GAME 2: RESIPA (TEBAK KATA DENGAN KATEGORI & KISI-KISI) ---
    @commands.command(name="resipa", help="Mulai permainan Kuis Resipa (Tebak Kata).")
    @commands.cooldown(1, 30, commands.BucketType.channel)
    async def resipa(self, ctx):
        if ctx.channel.id != self.game_channel_id:
            return await ctx.send("Permainan ini hanya bisa dimainkan di channel yang ditentukan.", delete_after=10)
        if ctx.channel.id in self.active_resipa_games:
            return await ctx.send("Permainan Kuis Resipa sudah berlangsung. Mohon tunggu hingga selesai.", delete_after=10)
        
        embed = discord.Embed(title="🧠 Siap Bermain Kuis Resipa (Tebak Kata)?", color=0x3498db)
        embed.description = (
            "Uji kecepatan berpikir dan kosakatamu dalam game seru ini!\n\n"
            "**Aturan Main:**\n"
            "1. Bot akan memberikan **kata yang hurufnya diacak**, dilengkapi **kategori** dan **kisi-kisi**.\n"
            "2. Tebak kata aslinya secepat mungkin.\n"
            f"3. Jawaban benar pertama mendapat **{self.resipa_reward['rsw']} RSWN** & **{self.resipa_reward['exp']} EXP**.\n"
            "4. Permainan terdiri dari 10 ronde.\n\n"
            "Klik tombol di bawah untuk memulai tantangan katamu!"
        )
        embed.set_thumbnail(url="https://raw.githubusercontent.com/Abogoboga04/OpenAI/main/AB6.jpeg") # Bisa diganti thumbnail yang lebih sesuai
        embed.set_footer(text="Hanya pemanggil perintah yang bisa memulai permainan.")
        
        view = discord.ui.View(timeout=60)
        start_button = discord.ui.Button(label="MULAI SEKARANG", style=discord.ButtonStyle.primary, emoji="▶️")

        async def start_callback(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                return await interaction.response.send_message("Hanya pemanggil perintah yang bisa memulai permainan.", ephemeral=True)
            
            self.active_resipa_games[ctx.channel.id] = True
            await interaction.message.delete()
            await ctx.send(f"**Permainan Kuis Resipa Dimulai!** Diselenggarakan oleh {ctx.author.mention}", delete_after=10)
            await self.play_resipa_game(ctx)
            
        start_button.callback = start_callback
        view.add_item(start_button)
        await ctx.send(embed=embed, view=view)

    async def play_resipa_game(self, ctx):
        # Memastikan bank soal cukup
        if not self.resipa_questions or len(self.resipa_questions) < 10:
            await ctx.send("Maaf, bank soal Kuis Resipa tidak ditemukan atau tidak cukup. Pastikan ada minimal 10 soal di `data/questions_resipa.json` dengan format `word`, `category`, `clue`.")
            await self.end_game_cleanup(ctx.channel.id, 'resipa', ctx.channel)
            return
            
        questions_for_game = random.sample(self.resipa_questions, 10) 
        leaderboard = {}

        for i, question_data in enumerate(questions_for_game):
            word = question_data['word']
            category = question_data['category']
            clue = question_data['clue'] # Mengambil clue dari JSON
            
            correct_answer = word.lower()
            scrambled_word = "".join(random.sample(word, len(word)))

            embed = discord.Embed(title=f"📝 Soal #{i+1} - Tebak Kata!", color=0x2ecc71)
            embed.add_field(name="Kategori", value=category, inline=True) 
            embed.add_field(name="Kata Teracak", value=f"## `{scrambled_word.upper()}`", inline=False)
            embed.add_field(name="Kisi-kisi", value=clue, inline=False) 
            embed.set_footer(text=f"Waktu terbatas: {self.resipa_time_limit} detik!")
            
            question_msg = await ctx.send(embed=embed)
            winner = await self.wait_for_answer_with_timer(ctx, correct_answer, question_msg, self.resipa_time_limit)

            if winner:
                await self.give_rewards_with_bonus_check(winner, self.resipa_reward, ctx.channel)
                await ctx.send(f"🎉 Selamat {winner.mention}! Jawabanmu benar!")
                leaderboard[winner.display_name] = leaderboard.get(winner.display_name, 0) + 1
            else:   
                await ctx.send(f"Waktu habis! Jawaban yang benar adalah: **{correct_answer.upper()}**.")

        await ctx.send("🏁 Permainan Kuis Resipa selesai! Terima kasih sudah bermain.")
        if leaderboard:
            sorted_lb = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
            desc = "\n".join([f"**#{n}.** {user}: {score} poin" for n, (user, score) in enumerate(sorted_lb, 1)])
            final_embed = discord.Embed(title="🏆 Papan Skor Akhir", description=desc, color=discord.Color.gold())
            await ctx.send(embed=final_embed)

        await self.end_game_cleanup(ctx.channel.id, 'resipa', ctx.channel)
    
    # --- GAME 3: SAMBUNG KATA ---
    @commands.command(name="ressambung", help="Mulai permainan Sambung Kata di Voice Channel.")
    async def ressambung(self, ctx):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("Kamu harus berada di dalam voice channel untuk memulai game ini.", delete_after=10)
        vc = ctx.author.voice.channel
        if vc.id in self.active_sambung_games:
            return await ctx.send(f"Sudah ada permainan Sambung Kata yang berlangsung di voice channel ini.", delete_after=10)

        members = [m for m in vc.members if not m.bot]
        if len(members) < 2:
            await ctx.send("Permainan ini membutuhkan minimal 2 orang di dalam voice channel.", delete_after=10)
            return
        
        game_state = {
            "players": {p.id: p for p in members}, "turn_index": 0, "current_word": "",
            "used_words": set(), "channel": ctx.channel, "guild_id": ctx.guild.id,
            "voice_channel_id": vc.id # Store VC ID for cleanup if needed
        }
        self.active_sambung_games[vc.id] = game_state
        
        player_mentions = ", ".join([p.mention for p in game_state["players"].values()])
        embed = discord.Embed(title="🔗 Siap Bermain Sambung Kata?", color=0xe91e63)
        embed.description = (
            "Uji kosakatamu dan bertahanlah sampai akhir!\n\n"
            "**Aturan Main:**\n"
            "1. Pemain bergiliran menyambung kata berdasarkan **2 huruf terakhir**.\n"
            "2. Waktu menjawab **20 detik** per giliran.\n"
            "3. Pemain yang gagal atau salah kata akan tereliminasi.\n"
            f"4. Pemenang terakhir mendapat **{self.sambung_kata_winner_reward['rsw']} RSWN** & **{self.sambung_kata_winner_reward['exp']} EXP**.\n"
        )
        embed.add_field(name="👥 Pemain Bergabung", value=player_mentions)
        embed.set_thumbnail(url="https://raw.githubusercontent.com/Abogoboga04/OpenAI/main/AB5.jpeg")
        
        await ctx.send(embed=embed)
        await asyncio.sleep(5)
        await self.play_sambung_kata_game(vc.id)

    async def play_sambung_kata_game(self, vc_id):
        game = self.active_sambung_games.get(vc_id)
        if not game:
            await self.end_game_cleanup(vc_id, 'sambung_kata', game.get("channel"))
            return

        player_ids = list(game["players"].keys())
        random.shuffle(player_ids)
        
        if not self.sambung_kata_words:
            await game["channel"].send("Bank kata untuk memulai tidak ditemukan.")
            await self.end_game_cleanup(vc_id, 'sambung_kata', game["channel"])
            return

        game["current_word"] = random.choice(self.sambung_kata_words).lower()
        game["used_words"].add(game["current_word"])
        
        await game["channel"].send(f"Kata pertama dari bot adalah: **{game['current_word'].upper()}**")

        while len(player_ids) > 1:
            current_player_id = player_ids[game["turn_index"]]
            current_player = game["players"][current_player_id]
            prefix = game["current_word"][-2:].lower()
            
            embed = discord.Embed(title=f"Giliran {current_player.display_name}!", description=f"Sebutkan kata yang diawali dengan **`{prefix.upper()}`**", color=current_player.color)
            prompt_msg = await game["channel"].send(embed=embed)

            try:
                async def timer_task():
                    for i in range(self.sambung_kata_time_limit, -1, -1):
                        new_embed = embed.copy()
                        new_embed.set_footer(text=f"Waktu tersisa: {i} detik ⏳")
                        try: await prompt_msg.edit(embed=new_embed)
                        except discord.NotFound: break
                        await asyncio.sleep(1)
                
                def check(m): return m.author.id == current_player_id and m.channel == game["channel"]
                
                wait_for_msg = self.bot.loop.create_task(self.bot.wait_for('message', check=check))
                timer = self.bot.loop.create_task(timer_task())
                done, pending = await asyncio.wait([wait_for_msg, timer], return_when=asyncio.FIRST_COMPLETED)
                timer.cancel()
                for task in pending: task.cancel()
                
                if wait_for_msg in done:
                    msg = wait_for_msg.result()
                    new_word = msg.content.strip().lower()
                    if not new_word.startswith(prefix):
                        await game["channel"].send(f"❌ Salah! {current_player.mention} tereliminasi!")
                        player_ids.pop(game["turn_index"])
                    elif new_word in game["used_words"]:
                        await game["channel"].send(f"❌ Kata sudah digunakan! {current_player.mention} tereliminasi!")
                        player_ids.pop(game["turn_index"])
                    else:
                        await msg.add_reaction("✅")
                        game["current_word"], game["used_words"] = new_word, game["used_words"] | {new_word}
                        game["turn_index"] = (game["turn_index"] + 1) % len(player_ids)
                else: # Timeout
                    await game["channel"].send(f"⌛ Waktu habis! {current_player.mention} tereliminasi!")
                    player_ids.pop(game["turn_index"])
                
            except asyncio.CancelledError: # Game was cancelled externally
                await game["channel"].send("Permainan Sambung Kata dihentikan.")
                break # Exit loop cleanly
            except Exception as e:
                print(f"Terjadi error dalam play_sambung_kata_game: {e}")
                await game["channel"].send(f"Terjadi error pada game Sambung Kata: `{e}`. Permainan dihentikan.")
                break # Exit loop on unexpected error
            
            if len(player_ids) > 0 and game["turn_index"] >= len(player_ids):
                game["turn_index"] = 0
            await asyncio.sleep(2)

        if len(player_ids) == 1:
            winner = game["players"][player_ids[0]]
            await self.give_rewards_with_bonus_check(winner, self.sambung_kata_winner_reward, game["channel"])
            await game["channel"].send(f"🏆 Pemenangnya adalah {winner.mention}! Kamu mendapatkan hadiah!")
        else:
            await game["channel"].send("Permainan berakhir tanpa pemenang.")
            
        await self.end_game_cleanup(vc_id, 'sambung_kata', game["channel"])
    
    # --- HELPER FUNCTION FOR TIMER ---
    async def wait_for_answer_with_timer(self, ctx, correct_answer, question_msg, time_limit):
        async def timer_task():
            for i in range(time_limit, -1, -1):
                new_embed = question_msg.embeds[0].copy()
                new_embed.set_footer(text=f"Waktu tersisa: {i} detik ⏳")
                try: await question_msg.edit(embed=new_embed)
                except discord.NotFound: break
                await asyncio.sleep(1)

        def check(m): return m.channel == ctx.channel and not m.author.bot and m.content.lower() == correct_answer.lower()

        wait_for_msg_task = self.bot.loop.create_task(self.bot.wait_for('message', check=check))
        timer = self.bot.loop.create_task(timer_task())
        done, pending = await asyncio.wait([wait_for_msg_task, timer], return_when=asyncio.FIRST_COMPLETED)
        timer.cancel()
        for task in pending: task.cancel()
        if wait_for_msg_task in done: return wait_for_msg_task.result().author
        else: return None

async def setup(bot):
    await bot.add_cog(GameLanjutan(bot))
