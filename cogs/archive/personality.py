import discord
from discord.ext import commands
from discord.ui import Button, View
import json
import os

# Tentukan PATH ke folder data relatif dari file cog ini
DATA_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
PERSONALITY_QUESTIONS_FILE = os.path.join(DATA_FOLDER, 'personality_questions.json') # Nama file baru
PERSONALITY_RESULTS_FILE = os.path.join(DATA_FOLDER, 'personality_results.json')     # Nama file baru

class PersonalityTest(commands.Cog): # Nama kelas cog baru
    def __init__(self, bot):
        self.bot = bot
        self.user_states = {} # Menyimpan progres tes setiap user
        self.questions_data = {}
        self.results_data = {}
        self._load_data()

    def _load_data(self):
        """Memuat data pertanyaan dan hasil dari file JSON."""
        try:
            with open(PERSONALITY_QUESTIONS_FILE, 'r', encoding='utf-8') as f:
                self.questions_data = json.load(f)
            with open(PERSONALITY_RESULTS_FILE, 'r', encoding='utf-8') as f:
                self.results_data = json.load(f)
            print(f"[{self.__class__.__name__}] Data pertanyaan dan hasil berhasil dimuat dari {PERSONALITY_QUESTIONS_FILE} dan {PERSONALITY_RESULTS_FILE}.")
        except FileNotFoundError:
            print(f"[{self.__class__.__name__}] Error: File tidak ditemukan. Pastikan '{PERSONALITY_QUESTIONS_FILE}' dan '{PERSONALITY_RESULTS_FILE}' ada di '{DATA_FOLDER}'.")
            raise FileNotFoundError(f"Missing data files: {PERSONALITY_QUESTIONS_FILE} or {PERSONALITY_RESULTS_FILE}")
        except json.JSONDecodeError as e:
            print(f"[{self.__class__.__name__}] Error: Pastikan format JSON valid di file data. Detail: {e}")
            raise json.JSONDecodeError(f"Invalid JSON in data files: {e}")

    @commands.command(name='testkepribadian') # Nama perintah baru
    async def start_quiz(self, ctx):
        """Memulai tes kepribadian interaktif dengan tombol."""
        user_id = ctx.author.id
        if user_id in self.user_states:
            await ctx.send(f"{ctx.author.mention}, kamu sudah dalam sesi tes. Selesaikan dulu atau ketik `!batalkantest` untuk memulai ulang.", ephemeral=True)
            return

        # Inisialisasi state user, termasuk semua trait dengan skor 0
        all_traits = set(self.results_data.get("trait_descriptions", {}).keys())
        # Pastikan semua trait dari questions.json juga ada di inisialisasi
        for q_id, q_data in self.questions_data.items():
            for opt_key, opt_data in q_data.get("options", {}).items():
                for trait in opt_data.get("traits_impact", {}).keys():
                    all_traits.add(trait)
        
        self.user_states[user_id] = {
            "current_question_id": "q1_start",
            "scores": {trait: 0 for trait in all_traits},
            "message_to_edit": None # Pesan yang akan diedit/dihapus
        }
        
        await self._send_question(ctx, user_id, ctx.channel)

    @commands.command(name='batalkantest') # Nama perintah baru
    async def cancel_quiz(self, ctx):
        """Membatalkan sesi tes kepribadian."""
        user_id = ctx.author.id
        if user_id in self.user_states:
            message_to_delete = self.user_states[user_id].get("message_to_edit")
            if message_to_delete:
                try:
                    # Nonaktifkan tombol sebelum menghapus
                    view = discord.View.from_message(message_to_delete)
                    for item in view.children:
                        item.disabled = True
                    await message_to_delete.edit(view=view)
                    await message_to_delete.delete(delay=3) # Hapus setelah beberapa detik
                except discord.NotFound:
                    pass
            del self.user_states[user_id]
            await ctx.send(f"✅ Sesi tesmu telah dibatalkan, {ctx.author.mention}. Sampai jumpa lagi!", ephemeral=True)
        else:
            await ctx.send(f"{ctx.author.mention}, kamu tidak sedang dalam sesi tes.", ephemeral=True)

    async def _send_question(self, ctx_or_interaction, user_id, channel):
        state = self.user_states[user_id]
        q_id = state["current_question_id"]
        question_data = self.questions_data.get(q_id)

        if not question_data:
            await channel.send(f"Maaf, terjadi kesalahan pada pertanyaan. Mohon hubungi admin bot. (ID pertanyaan tidak ditemukan: {q_id})", ephemeral=True)
            if user_id in self.user_states:
                del self.user_states[user_id]
            return

        embed = discord.Embed(
            title="💡 Tes Kepribadian",
            description=f"**{question_data['text']}**",
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Progress: {self._get_progress(q_id)}") # Menampilkan progress

        # Mengambil label tombol dan custom_id untuk QuestionView
        options_for_view = {key: val for key, val in question_data["options"].items()}
        view = QuestionView(self, user_id, q_id, options_for_view)
        
        # Menggunakan response.edit_message untuk mengedit pesan interaksi sebelumnya
        # Ini penting agar tidak ada "This interaction failed" jika pesan awal adalah respons defer
        if state["message_to_edit"]:
            try:
                # Jika ctx_or_interaction adalah Interaction, gunakan response.edit_message
                if isinstance(ctx_or_interaction, discord.Interaction) and not ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.response.edit_message(embed=embed, view=view)
                else: # Jika ini dipanggil dari command atau interaction yang sudah di-defer
                    await state["message_to_edit"].edit(embed=embed, view=view)
            except discord.NotFound: # Pesan mungkin sudah dihapus atau tidak ditemukan
                state["message_to_edit"] = await channel.send(embed=embed, view=view)
            except discord.HTTPException as e: # Error lain seperti invalid form body
                print(f"Error editing message: {e} - Attempting to send new message.")
                state["message_to_edit"] = await channel.send(embed=embed, view=view)
        else:
            # Ini untuk pesan awal command !testkepribadian
            if isinstance(ctx_or_interaction, commands.Context):
                state["message_to_edit"] = await ctx_or_interaction.send(embed=embed, view=view)
            else: # Fallback, misal dari interaction.response.defer() yang awal
                state["message_to_edit"] = await channel.send(embed=embed, view=view)


    def _get_progress(self, current_q_id):
        """Menghitung progress tes (estimasi)."""
        all_q_ids = list(self.questions_data.keys())
        try:
            current_index = all_q_ids.index(current_q_id)
            progress_percent = (current_index / len(all_q_ids)) * 100
            return f"Pertanyaan ke-{current_index + 1} dari {len(self.questions_data)} ({progress_percent:.0f}%)"
        except ValueError:
            return "Progress: N/A" # Jika ID tidak ditemukan

    async def _process_answer(self, interaction: discord.Interaction, user_id, q_id, selected_option_key):
        state = self.user_states.get(user_id)
        if not state or state["current_question_id"] != q_id:
            if not interaction.response.is_done(): # Pastikan belum ada respons sebelumnya
                await interaction.response.send_message("Ini bukan pertanyaanmu saat ini atau tes sudah selesai.", ephemeral=True)
            return

        question_data = self.questions_data.get(q_id)
        if not question_data or selected_option_key not in question_data["options"]:
            if not interaction.response.is_done():
                await interaction.response.send_message("Opsi tidak valid. Terjadi kesalahan internal.", ephemeral=True)
            return

        selected_option = question_data["options"][selected_option_key]

        # Nonaktifkan tombol di pesan yang sedang diinteraksi
        if interaction.message:
            try:
                view = discord.View.from_message(interaction.message)
                for item in view.children:
                    item.disabled = True
                await interaction.message.edit(view=view)
            except discord.NotFound:
                pass # Pesan mungkin sudah dihapus
            except discord.HTTPException:
                pass # Gagal edit, mungkin pesan sudah terlalu tua

        # Akumulasi skor trait
        for trait, value in selected_option.get("traits_impact", {}).items():
            if trait not in state["scores"]:
                state["scores"][trait] = 0
            state["scores"][trait] += value

        # Lanjutkan ke pertanyaan berikutnya atau tampilkan hasil
        if "next_question_id" in selected_option:
            state["current_question_id"] = selected_option["next_question_id"]
            if not interaction.response.is_done(): # Pastikan interaksi belum direspons
                await interaction.response.defer() # Acknowledge interaction before sending next question
            await self._send_question(interaction, user_id, interaction.channel)
            
        else: # Tes selesai
            if not interaction.response.is_done():
                await interaction.response.defer() # Acknowledge interaction before displaying results
            await self._display_final_results(interaction, user_id, interaction.channel)
            
            # Hapus pesan terakhir setelah hasil ditampilkan (jika belum dihapus oleh _display_final_results)
            if state["message_to_edit"]:
                try:
                    await state["message_to_edit"].delete(delay=5)
                except discord.NotFound:
                    pass

    async def _display_final_results(self, interaction, user_id, channel):
        state = self.user_states.get(user_id)
        if not state: # User state might have been deleted if test was cancelled or timed out
            return
        
        final_scores = state["scores"]
        trait_descriptions = self.results_data.get("trait_descriptions", {})
        main_personality_types_base = self.results_data.get("main_personality_types_base", {})
        dynamic_trait_feedback_data = self.results_data.get("dynamic_trait_feedback", []) # Pastikan ini di load

        # --- LOGIKA PENENTUAN TIPE UTAMA (Ekstrovert, Introvert, Ambivert) ---
        extro_score = final_scores.get('Ekstrovert', 0)
        intro_score = final_scores.get('Introvert', 0)
        ambivert_score = final_scores.get('Ambivert', 0)

        # Menghitung selisih Ekstrovert vs Introvert
        net_extro_intro = extro_score - intro_score
        
        # Ambang batas untuk menentukan Ekstrovert/Introvert yang jelas
        # Sesuaikan nilai ini untuk mendapatkan hasil yang lebih akurat
        # Misalnya, jika selisih > 3 poin, dia Ekstrovert/Introvert murni
        # Jika selisih <= 3, dia Ambivert
        EXTRO_INTRO_THRESHOLD = 3 
        
        if net_extro_intro > EXTRO_INTRO_THRESHOLD:
            base_type_key = "Ekstrovert_Result"
        elif net_extro_intro < -EXTRO_INTRO_THRESHOLD:
            base_type_key = "Introvert_Result"
        else: # Jika skor Ekstrovert dan Introvert relatif seimbang, atau Ambivert skornya signifikan
            # Prioritaskan Ambivert jika skor Ambivert positif signifikan, atau net scorenya kecil
            if ambivert_score >= 1.5 or abs(net_extro_intro) <= EXTRO_INTRO_THRESHOLD:
                base_type_key = "Ambivert_Result"
            elif extro_score > intro_score: # Kalau seimbang tapi lebih condong extro
                 base_type_key = "Ekstrovert_Result"
            else: # Kalau seimbang tapi lebih condong intro
                 base_type_key = "Introvert_Result"


        # Dapatkan data dasar untuk tipe kepribadian utama
        base_result = main_personality_types_base.get(base_type_key, {})
        
        member = channel.guild.get_member(user_id) if channel.guild else interaction.user
        member_name = member.display_name # Menggunakan display_name untuk nama yang lebih ramah

        result_embed = discord.Embed(
            title=f"🎉 Hasil Tes Kepribadianmu, {member_name}!",
            description=f"Dari jawaban-jawabanmu, tampaknya kamu adalah:\n\n**{base_result.get('name', 'Tipe Tidak Dikenal')}**",
            color=discord.Color.gold() # Warna cerah untuk hasil
        )
        result_embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

        # --- Bagian Keunggulan, Kekurangan, Saran & Kritik Didasarkan pada Trait Dinamis ---
        
        keunggulan_list = [base_result.get('keunggulan_base', 'Tidak ada deskripsi keunggulan dasar.')]
        kekurangan_list = [base_result.get('kekurangan_base', 'Tidak ada deskripsi kekurangan dasar.')]
        saran_kritik_list = [base_result.get('saran_base', 'Tidak ada saran dasar.')]

        # Ambil feedback dinamis berdasarkan skor trait
        for feedback_item in dynamic_trait_feedback_data:
            trait_name = feedback_item['trait']
            min_score = feedback_item['min_score']
            user_score = final_scores.get(trait_name, 0)

            if user_score >= min_score:
                keunggulan_list.append(f"**{trait_name.replace('_', ' ').title()}**: {feedback_item['feedback']}")
                saran_kritik_list.append(f"**{trait_name.replace('_', ' ').title()}**: {feedback_item['kritik_saran']}")
            # Untuk kekurangan, kita bisa menambahkan logika jika trait yang diharapkan rendah malah tinggi, atau trait negatifnya tinggi
            # Contoh: Jika Ekstrovert yang seharusnya rendah malah tinggi (misal untuk tipe introvert)
            # Ini akan membutuhkan logika lebih kompleks di sini atau di JSON
            # Untuk saat ini, kita akan fokus pada kritik_saran dari feedback_item


        result_embed.add_field(name="✨ Kesimpulan:", value=base_result.get('kesimpulan_base', 'Tidak ada kesimpulan dasar.'), inline=False)
        result_embed.add_field(name="👍 Keunggulanmu:", value="\n".join(keunggulan_list), inline=False)
        result_embed.add_field(name="🔍 Area Pengembangan (Kritik & Saran):", value="\n".join(saran_kritik_list), inline=False)
        
        # --- Menampilkan Data Trait Menyeluruh ---
        trait_data_text = ""
        
        # Tampilkan skor mentah trait Ekstrovert, Introvert, Ambivert sebagai informasi dasar
        trait_data_text += f"- **Ekstrovert**: {extro_score:.1f} poin ({trait_descriptions.get('Ekstrovert', '').split('.')[0]}.)\n"
        trait_data_text += f"- **Introvert**: {intro_score:.1f} poin ({trait_descriptions.get('Introvert', '').split('.')[0]}.)\n"
        trait_data_text += f"- **Ambivert**: {ambivert_score:.1f} poin ({trait_descriptions.get('Ambivert', '').split('.')[0]}.)\n"

        # Tampilkan trait positif signifikan lainnya
        significant_positive_traits = {trait: score for trait, score in final_scores.items() if score > 0 and trait not in ['Ekstrovert', 'Introvert', 'Ambivert']}
        
        if significant_positive_traits:
            sorted_traits = sorted(significant_positive_traits.items(), key=lambda item: item[1], reverse=True)
            sum_of_positive_scores_others = sum(score for score in significant_positive_traits.values())

            if sum_of_positive_scores_others > 0: # Pastikan ada skor positif selain E/I/A
                trait_data_text += "\n**Trait Positif Menonjol Lainnya:**\n"
                for trait, score in sorted_traits[:7]: # Tampilkan hingga 7 trait positif teratas lainnya
                    percentage_of_sum = (score / sum_of_positive_scores_others * 100) if sum_of_positive_scores_others > 0 else 0
                    trait_description_short = trait_descriptions.get(trait, "Tidak ada deskripsi.").split('.')[0]
                    trait_data_text += f"- **{trait.replace('_', ' ').title()}**: {score:.1f} poin ({percentage_of_sum:.1f}% dari total positif lainnya)\n"
                    trait_data_text += f"  *_{trait_description_short}._*\n"
                
        # Contoh spesifik untuk Pemarah dan Penyabar (jika ada skor yang signifikan)
        pemarah_score = final_scores.get('Pemarah', 0)
        penyabar_score = final_scores.get('Penyabar', 0)
        if pemarah_score > 0 or penyabar_score > 0:
            total_temper_score = abs(pemarah_score) + abs(penyabar_score)
            pemarah_percent = (pemarah_score / total_temper_score * 100) if total_temper_score > 0 else 0
            penyabar_percent = (penyabar_score / total_temper_score * 100) if total_temper_score > 0 else 0
            
            trait_data_text += "\n**Temperamenmu:**\n"
            if pemarah_score > penyabar_score and pemarah_score > 0.5: # Ambang batas minimal untuk dianggap menonjol
                trait_data_text += f"- Kamu cenderung **pemarah** dengan {pemarah_percent:.1f}% kecenderungan. ({trait_descriptions.get('Pemarah', '').split('.')[0]}.)\n"
            elif penyabar_score > pemarah_score and penyabar_score > 0.5:
                trait_data_text += f"- Kamu cenderung sangat **penyabar** dengan {penyabar_percent:.1f}% kecenderungan. ({trait_descriptions.get('Penyabar', '').split('.')[0]}.)\n"
            else:
                trait_data_text += "- Temperamenmu cukup seimbang antara Pemarah dan Penyabar.\n"

        if trait_data_text:
            result_embed.add_field(name="--- Data Trait Lengkap Anda ---", value=trait_data_text, inline=False)


        result_embed.set_footer(text="Ingat, ini hanyalah hasil tes, bukan diagnosis profesional. Tetaplah menjadi versi terbaik dari dirimu!")

        await channel.send(embed=result_embed)


class QuestionView(View):
    def __init__(self, cog, user_id, question_id, options_data):
        super().__init__(timeout=120) # Timeout setelah 2 menit tanpa interaksi
        self.cog = cog
        self.user_id = user_id
        self.question_id = question_id
        self.options_data = options_data
        self._add_buttons()

    def _add_buttons(self):
        # Tambahkan tombol untuk setiap opsi jawaban
        for option_key, _ in self.options_data.items():
            # Label tombol dibuat dari option_key dengan mengganti underscore jadi spasi dan kapitalisasi awal
            label = option_key.replace('_', ' ').title()
            # custom_id akan digunakan untuk mengidentifikasi tombol mana yang ditekan
            button = Button(label=label, custom_id=f"personality_{self.question_id}_{option_key}") # Custom ID unik
            self.add_item(button)

        # Tambahkan tombol 'Batalkan Tes'
        cancel_button = Button(label="Batalkan Tes", style=discord.ButtonStyle.red, custom_id=f"personality_cancel_{self.question_id}") # Custom ID unik
        self.add_item(cancel_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Pastikan hanya user yang memulai tes yang bisa berinteraksi dengan tombol
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ini bukan tesmu! Silakan mulai tesmu sendiri dengan `!testkepribadian`.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        # Ketika view timeout (tidak ada interaksi dalam 2 menit)
        if self.user_id in self.cog.user_states:
            channel = self.cog.bot.get_channel(self.message.channel.id) # Get channel to send message
            if not channel: # Fallback for private messages or specific channel types
                channel = self.message.channel
            await channel.send(f"Tes dibatalkan karena tidak ada respons dari <@{self.user_id}> selama 2 menit. Silakan mulai lagi dengan `!testkepribadian`.", ephemeral=True)
            del self.cog.user_states[self.user_id]
        
        # Nonaktifkan semua tombol
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)


    @discord.ui.button(label="Placeholder", custom_id="button_placeholder_ignore_this_one", style=discord.ButtonStyle.secondary)
    async def handle_button_click(self, interaction: discord.Interaction, button: Button):
        # Logika ini akan dipicu oleh setiap tombol yang tidak memiliki callback spesifik
        # Custom ID format: "personality_{question_id}_{option_key}" atau "personality_cancel_{question_id}"
        
        parts = button.custom_id.split('_')
        # parts[0] = "personality"
        action_or_q_id_prefix = parts[1] 
        q_id_from_button = parts[2] 

        if action_or_q_id_prefix == "cancel": # Cek action cancel
            if interaction.user.id == self.user_id: # Pastikan user yang benar
                # Batalkan tes
                if self.user_id in self.cog.user_states:
                    del self.cog.user_states[self.user_id]
                
                # Nonaktifkan semua tombol di pesan ini
                for item in self.children:
                    item.disabled = True
                await interaction.message.edit(content=f"Tes dibatalkan oleh {interaction.user.mention}.", view=self)
                await interaction.response.send_message("Tes kepribadian dibatalkan.", ephemeral=True)
            else:
                await interaction.response.send_message("Ini bukan tesmu!", ephemeral=True)
            return

        # Jika bukan tombol cancel, berarti ini jawaban pertanyaan
        # parts[0] = "personality", parts[1] = question_id, parts[2] = option_key (atau sisanya)
        selected_option_key = '_'.join(parts[2:]) # Rekonstruksi option_key dari custom_id, mulai dari index 2 (setelah "personality" dan "qX")
        
        # Panggil fungsi proses jawaban di cog
        await self.cog._process_answer(interaction, self.user_id, action_or_q_id_prefix, selected_option_key)


async def setup(bot):
    await bot.add_cog(PersonalityTest(bot))
