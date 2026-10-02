import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import time
import csv
import io
import uuid
import re
import logging
from datetime import datetime

log = logging.getLogger("FinancialAdvisor")

generate_smart_response = None

INCOME_CATEGORIES = [
    ("💼 Gaji", "Gaji"),
    ("🏢 Bisnis / Usaha", "Bisnis"),
    ("💻 Freelance / Projek", "Freelance"),
    ("📈 Investasi / Dividen", "Investasi"),
    ("🎁 Bonus / Hadiah", "Bonus"),
    ("🏷️ Penjualan Barang", "Penjualan"),
    ("🌐 Pemasukan Lainnya", "Lainnya")
]

EXPENSE_CATEGORIES = [
    ("🍔 Makanan & Minuman", "Makanan"),
    ("🏠 Tempat Tinggal & Kos", "Tempat Tinggal"),
    ("🚗 Transportasi & Bensin", "Transportasi"),
    ("💡 Tagihan & Utilitas", "Tagihan"),
    ("🛍️ Belanja & Kebutuhan", "Belanja"),
    ("🎮 Hiburan & Hobi", "Hiburan"),
    ("💊 Kesehatan & Medis", "Kesehatan"),
    ("📚 Edukasi & Buku", "Edukasi"),
    ("🪙 Tabungan & Investasi", "Tabungan"),
    ("💳 Cicilan & Hutang", "Cicilan"),
    ("📦 Pengeluaran Lainnya", "Lainnya")
]

def format_rupiah(nominal: int) -> str:
    return f"Rp {nominal:,.0f}".replace(",", ".")

def make_progress_bar(percentage: float, length: int = 10) -> str:
    filled = int(round(length * min(max(percentage, 0.0), 100.0) / 100.0))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percentage:.1f}%"

def strip_discord_formatting(text: str) -> str:
    """Bersihkan mention user/bot, role, channel, custom emoji, dan URL dari teks."""
    cleaned = re.sub(r'<@!?\d+>', '', text)
    cleaned = re.sub(r'<@&\d+>', '', cleaned)
    cleaned = re.sub(r'<#\d+>', '', cleaned)
    cleaned = re.sub(r'<a?:\w+:\d+>', '', cleaned)
    cleaned = re.sub(r'https?://\S+', '', cleaned)
    return cleaned.strip()

def parse_quick_amount(text: str) -> int:
    """
    Ekstrak nominal uang dari teks santai:
    - 25k / 25rb / 25 ribu -> 25.000
    - 1.5jt / 1,5 juta -> 1.500.000
    - rp 50000 / rp. 50.000 -> 50.000
    - makan 25000 -> 25.000 (hanya jika ada konteks transaksi keuangan)
    """
    # 1. Bersihkan mention discord dan url dulu agar ID snowflake bot/user tidak terdeteksi sebagai nominal uang
    text_clean = strip_discord_formatting(text).lower().replace(",", ".")
    if not text_clean:
        return 0

    # 2. Format Juta (jt / juta): contoh 1.5jt, 2 juta
    match_jt = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:jt|juta)\b', text_clean)
    if match_jt:
        try:
            val = int(float(match_jt.group(1)) * 1_000_000)
            if 0 < val <= 1_000_000_000:
                return val
        except Exception: pass

    # 3. Format Ribu (rb / k / ribu): contoh 25k, 50rb, 100 ribu
    match_rb = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:rb|k|ribu)\b', text_clean)
    if match_rb:
        try:
            val = int(float(match_rb.group(1)) * 1_000)
            if 0 < val <= 1_000_000_000:
                return val
        except Exception: pass

    # 4. Format Eksplisit Rupiah (rp / rp.): contoh rp 50.000, rp50000
    match_rp = re.search(r'\brp\.?\s*(\d{1,3}(?:\.\d{3})+|\d{3,9})\b', text_clean)
    if match_rp:
        try:
            raw_num = match_rp.group(1).replace(".", "")
            val = int(raw_num)
            if 0 < val <= 1_000_000_000:
                return val
        except Exception: pass

    # 5. Format Angka bertitik ribuan (contoh: 25.000, 150.000)
    match_dot = re.search(r'\b(\d{1,3}(?:\.\d{3})+)\b', text_clean)
    if match_dot:
        try:
            raw_num = match_dot.group(1).replace(".", "")
            val = int(raw_num)
            if 0 < val <= 1_000_000_000:
                return val
        except Exception: pass

    # 6. Angka polos 4-9 digit (contoh: 25000, 50000)
    # HANYA diekstrak jika terdapat kata kunci transaksi keuangan yang jelas
    tx_intent_words = [
        "catat", "beli", "bayar", "makan", "minum", "jajan", "bensin", "parkir",
        "ongkir", "gaji", "masuk", "keluar", "topup", "sewa", "tagihan", "belanja",
        "transfer", "kas", "pengeluaran", "pemasukan", "biaya"
    ]
    if any(w in text_clean for w in tx_intent_words):
        match_plain = re.search(r'\b(\d{4,9})\b', text_clean)
        if match_plain:
            try:
                val = int(match_plain.group(1))
                if 0 < val <= 1_000_000_000:
                    return val
            except Exception: pass

    return 0

def detect_category(text: str, tx_type: str) -> str:
    t = text.lower()
    if tx_type == "IN":
        if any(w in t for w in ["gaji", "salary", "upah"]): return "Gaji"
        if any(w in t for w in ["bisnis", "usaha", "omset", "toko", "jual"]): return "Bisnis"
        if any(w in t for w in ["freelance", "projek", "side", "jasa"]): return "Freelance"
        if any(w in t for w in ["investasi", "dividen", "saham", "crypto", "profit"]): return "Investasi"
        if any(w in t for w in ["bonus", "hadiah", "giveaway", "angpao", "thr"]): return "Bonus"
        return "Lainnya"
    else:
        if any(w in t for w in ["makan", "minum", "kopi", "sarapan", "lunch", "dinner", "jajan", "snack", "resto", "cafe", "boba", "nasgor", "bakso", "mie"]): return "Makanan"
        if any(w in t for w in ["kos", "sewa", "rumah", "kontrakan", "kamar"]): return "Tempat Tinggal"
        if any(w in t for w in ["bensin", "parkir", "tol", "gojek", "grab", "ojol", "angkot", "kereta", "mrt", "service", "oli", "transport"]): return "Transportasi"
        if any(w in t for w in ["listrik", "pln", "air", "pdam", "wifi", "indihome", "kuota", "pulsa", "tagihan", "iuran"]): return "Tagihan"
        if any(w in t for w in ["baju", "sepatu", "celana", "shopee", "tokped", "belanja", "skincare", "supermarket", "minimarket", "alfa", "indo"]): return "Belanja"
        if any(w in t for w in ["game", "steam", "topup", "ml", "ff", "genshin", "nonton", "bioskop", "karaoke", "hiburan", "hobi"]): return "Hiburan"
        if any(w in t for w in ["obat", "dokter", "klinik", "apotek", "vitamin", "sakit", "medis"]): return "Kesehatan"
        if any(w in t for w in ["buku", "kursus", "kuliah", "sekolah", "udemy", "spp"]): return "Edukasi"
        if any(w in t for w in ["tabung", "reksadana", "emas", "deposito", "bibit", "ajaib"]): return "Tabungan"
        if any(w in t for w in ["cicilan", "hutang", "pinjol", "kredit", "paylater"]): return "Cicilan"
        return "Lainnya"

def detect_tx_type(text: str) -> str:
    t = text.lower()
    in_keywords = ["masuk", "gaji", "bonus", "cuan", "terima", "dapat", "dapet", "penghasilan", "income", "in "]
    if any(k in t for k in in_keywords):
        return "IN"
    return "OUT"

class QuickCashInModal(discord.ui.Modal, title="💼 Catat Pemasukan (Cash In)"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

        self.amount_input = discord.ui.TextInput(
            label="Nominal Pemasukan (Rupiah)",
            placeholder="Contoh: 1500000",
            min_length=1,
            max_length=15,
            required=True
        )
        self.category_input = discord.ui.TextInput(
            label="Kategori (Gaji / Bisnis / Freelance / Bonus)",
            placeholder="Pilihan: Gaji, Bisnis, Freelance, Investasi, Bonus, Lainnya",
            default="Gaji",
            required=True
        )
        self.note_input = discord.ui.TextInput(
            label="Keterangan / Sumber Dana (Opsional)",
            placeholder="Contoh: Pembayaran invoice projek website",
            required=False,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.amount_input)
        self.add_item(self.category_input)
        self.add_item(self.note_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val_clean = self.amount_input.value.replace(".", "").replace(",", "").replace("Rp", "").strip()
            nominal = int(val_clean)
        except ValueError:
            await interaction.response.send_message("❌ Nominal harus berupa angka yang valid.", ephemeral=True)
            return

        if nominal <= 0 or nominal > 1_000_000_000_000:
            await interaction.response.send_message("❌ Nominal tidak valid (1 s.d. Rp 1 Triliun).", ephemeral=True)
            return

        cat = self.category_input.value.strip() or "Lainnya"
        note = self.note_input.value.strip() or "Pencatatan cepat"

        res = self.cog.add_transaction(interaction.user.id, "IN", nominal, cat, note)
        embed = self.cog.build_transaction_embed(interaction.user, res, "IN")
        await interaction.response.send_message(embed=embed)

class QuickCashOutModal(discord.ui.Modal, title="💸 Catat Pengeluaran (Cash Out)"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

        self.amount_input = discord.ui.TextInput(
            label="Nominal Pengeluaran (Rupiah)",
            placeholder="Contoh: 75000",
            min_length=1,
            max_length=15,
            required=True
        )
        self.category_input = discord.ui.TextInput(
            label="Kategori (Makanan / Transport / Belanja)",
            placeholder="Pilihan: Makanan, Transportasi, Tagihan, Belanja, Hiburan, Lainnya",
            default="Makanan",
            required=True
        )
        self.note_input = discord.ui.TextInput(
            label="Keterangan / Keperluan (Opsional)",
            placeholder="Contoh: Makan siang bersama tim",
            required=False,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.amount_input)
        self.add_item(self.category_input)
        self.add_item(self.note_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val_clean = self.amount_input.value.replace(".", "").replace(",", "").replace("Rp", "").strip()
            nominal = int(val_clean)
        except ValueError:
            await interaction.response.send_message("❌ Nominal harus berupa angka yang valid.", ephemeral=True)
            return

        if nominal <= 0 or nominal > 1_000_000_000_000:
            await interaction.response.send_message("❌ Nominal tidak valid (1 s.d. Rp 1 Triliun).", ephemeral=True)
            return

        cat = self.category_input.value.strip() or "Lainnya"
        note = self.note_input.value.strip() or "Pencatatan cepat"

        res = self.cog.add_transaction(interaction.user.id, "OUT", nominal, cat, note)
        embed = self.cog.build_transaction_embed(interaction.user, res, "OUT")
        await interaction.response.send_message(embed=embed)

class ResetConfirmView(discord.ui.View):
    def __init__(self, cog, user_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Anda tidak berhak menekan tombol ini.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ya, Hapus Semua Catatan", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.reset_user_data(self.user_id)
        embed = discord.Embed(
            title="✅ Data Finansial Direset",
            description="Seluruh saldo, target anggaran, dan riwayat transaksi keuangan Anda telah berhasil dibersihkan.",
            color=0x2ECC71
        )
        embed.set_footer(text="RTM-Bot • Asisten Keuangan Pribadi")
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="Pembersihan Dibatalkan",
            description="Catatan finansial Anda tetap tersimpan aman.",
            color=0x95A5A6
        )
        await interaction.response.edit_message(embed=embed, view=self)

class DashboardView(discord.ui.View):
    def __init__(self, cog, user: discord.User):
        super().__init__(timeout=300)
        self.cog = cog
        self.user = user

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ Buka dasbor Anda sendiri menggunakan perintah `/keuangan`.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Catat Masuk", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def in_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(QuickCashInModal(self.cog))

    @discord.ui.button(label="Catat Keluar", style=discord.ButtonStyle.danger, emoji="➖", row=0)
    async def out_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(QuickCashOutModal(self.cog))

    @discord.ui.button(label="Arus Kas", style=discord.ButtonStyle.primary, emoji="📊", row=0)
    async def cashflow_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.cog.build_cashflow_embed(self.user)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Saran Finansial", style=discord.ButtonStyle.secondary, emoji="💡", row=0)
    async def advice_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.cog.build_advice_embed(self.user)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class FinancialAdvisor(commands.Cog, name="Personal Financial Advisor"):
    def __init__(self, bot):
        self.bot = bot
        self.db_file = os.path.join("data", "user_finance.json")
        self.data = {}
        self.load_data()

    def load_data(self):
        os.makedirs("data", exist_ok=True)
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}
        else:
            self.data = {}

        if not self.data:
            mongo_client = getattr(self.bot, "mongo_client", None)
            if mongo_client:
                try:
                    doc = mongo_client.get_database("rtmbot")["user_finance"].find_one({"_id": "all_users"})
                    if doc and "data" in doc:
                        self.data = doc["data"]
                except Exception:
                    pass

        # Sanitasi data: bersihkan transaksi anomali hasil salah tangkap mention bot (> 10 Miliar atau note bot)
        changed = False
        for uid, profile in list(self.data.items()):
            txs = profile.get("transactions", [])
            valid_txs = []
            recalc_balance = 0
            for tx in txs:
                note = str(tx.get("note", ""))
                amt = tx.get("amount", 0)
                if amt >= 10_000_000_000 or "<@" in note or "rtmxbadut" in note.lower():
                    changed = True
                    continue
                valid_txs.append(tx)
                if tx.get("type") == "IN":
                    recalc_balance += amt
                else:
                    recalc_balance -= amt
            if len(valid_txs) != len(txs):
                profile["transactions"] = valid_txs
                profile["balance"] = recalc_balance
                changed = True

        if changed:
            self.save_data()

    def save_data(self):
        try:
            os.makedirs("data", exist_ok=True)
            temp_file = f"{self.db_file}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
            os.replace(temp_file, self.db_file)
        except Exception as e:
            print(f"[FINANCE SAVE ERROR] {e}")

        mongo_client = getattr(self.bot, "mongo_client", None)
        if mongo_client:
            try:
                mongo_client.get_database("rtmbot")["user_finance"].replace_one(
                    {"_id": "all_users"},
                    {"_id": "all_users", "data": self.data, "updated_at": time.time()},
                    upsert=True
                )
            except Exception:
                pass

    def get_user_profile(self, user_id: int):
        uid = str(user_id)
        if uid not in self.data:
            self.data[uid] = {
                "balance": 0,
                "monthly_budget": 0,
                "transactions": []
            }
        return self.data[uid]

    def reset_user_data(self, user_id: int):
        uid = str(user_id)
        if uid in self.data:
            del self.data[uid]
            self.save_data()

    def add_transaction(self, user_id: int, tx_type: str, amount: int, category: str, note: str):
        profile = self.get_user_profile(user_id)
        now = datetime.now()

        tx = {
            "id": f"TX-{uuid.uuid4().hex[:6].upper()}",
            "type": tx_type,
            "amount": amount,
            "category": category,
            "note": note,
            "timestamp": time.time(),
            "month_key": now.strftime("%Y-%m"),
            "date_str": now.strftime("%d/%m/%Y %H:%M")
        }

        if tx_type == "IN":
            profile["balance"] += amount
        else:
            profile["balance"] -= amount

        profile["transactions"].insert(0, tx)
        if len(profile["transactions"]) > 200:
            profile["transactions"] = profile["transactions"][:200]

        self.save_data()
        return tx

    def calculate_stats(self, user_id: int):
        profile = self.get_user_profile(user_id)
        current_month = datetime.now().strftime("%Y-%m")

        total_in_all = sum(t["amount"] for t in profile["transactions"] if t["type"] == "IN")
        total_out_all = sum(t["amount"] for t in profile["transactions"] if t["type"] == "OUT")

        month_txs = [t for t in profile["transactions"] if t.get("month_key") == current_month]
        total_in_month = sum(t["amount"] for t in month_txs if t["type"] == "IN")
        total_out_month = sum(t["amount"] for t in month_txs if t["type"] == "OUT")

        budget = profile.get("monthly_budget", 0)
        budget_used_pct = (total_out_month / budget * 100.0) if budget > 0 else 0.0

        if total_in_month > 0:
            saving_rate = ((total_in_month - total_out_month) / total_in_month) * 100.0
        else:
            saving_rate = 0.0 if total_out_month == 0 else -100.0

        category_breakdown = {}
        for t in month_txs:
            if t["type"] == "OUT":
                cat = t.get("category", "Lainnya")
                category_breakdown[cat] = category_breakdown.get(cat, 0) + t["amount"]

        return {
            "balance": profile["balance"],
            "total_in_all": total_in_all,
            "total_out_all": total_out_all,
            "total_in_month": total_in_month,
            "total_out_month": total_out_month,
            "budget": budget,
            "budget_used_pct": budget_used_pct,
            "saving_rate": saving_rate,
            "category_breakdown": category_breakdown,
            "recent_transactions": profile["transactions"][:5]
        }

    def build_transaction_embed(self, user: discord.User, tx: dict, tx_type: str) -> discord.Embed:
        stats = self.calculate_stats(user.id)
        is_in = tx_type == "IN"

        if is_in:
            embed = discord.Embed(
                title="💼 Pemasukan Berhasil Dicatat (Cash In)",
                color=0x2ECC71,
                timestamp=datetime.now()
            )
            embed.description = f"Hai **{user.display_name}**, dana masuk berhasil diverifikasi oleh asisten finansial Anda."
            embed.add_field(name="💵 Nominal Masuk", value=f"**+{format_rupiah(tx['amount'])}**", inline=True)
            embed.add_field(name="📂 Kategori", value=f"`{tx['category']}`", inline=True)
            embed.add_field(name="🏦 Saldo Kas Baru", value=f"**{format_rupiah(stats['balance'])}**", inline=True)
            if tx.get("note"):
                embed.add_field(name="📝 Catatan", value=f"*{tx['note']}*", inline=False)
            embed.set_footer(text="Tips: Sisihkan sebagian pemasukan ini untuk tabungan & dana darurat!")
        else:
            embed = discord.Embed(
                title="💸 Pengeluaran Berhasil Dicatat (Cash Out)",
                color=0xE74C3C,
                timestamp=datetime.now()
            )
            embed.description = f"Pengeluaran telah dibukukan ke dalam arus kas **{user.display_name}**."
            embed.add_field(name="💸 Nominal Keluar", value=f"**-{format_rupiah(tx['amount'])}**", inline=True)
            embed.add_field(name="📂 Kategori", value=f"`{tx['category']}`", inline=True)
            embed.add_field(name="🏦 Sisa Saldo Kas", value=f"**{format_rupiah(stats['balance'])}**", inline=True)
            if tx.get("note"):
                embed.add_field(name="📝 Catatan", value=f"*{tx['note']}*", inline=False)

            if stats["budget"] > 0:
                pct = stats["budget_used_pct"]
                bar = make_progress_bar(pct)
                if pct >= 100.0:
                    embed.add_field(
                        name="🚨 PERINGATAN OVERBUDGET",
                        value=f"Anggaran bulan ini terlampaui!\n`{bar}`\nPengeluaran: **{format_rupiah(stats['total_out_month'])}** / Limit: **{format_rupiah(stats['budget'])}**",
                        inline=False
                    )
                elif pct >= 80.0:
                    embed.add_field(
                        name="⚠️ Pengingat Limit Anggaran",
                        value=f"Pemakaian anggaran mendekati batas maksimal:\n`{bar}`\nSisa Anggaran: **{format_rupiah(max(stats['budget'] - stats['total_out_month'], 0))}**",
                        inline=False
                    )

            embed.set_footer(text=f"ID Transaksi: {tx['id']} • RTM-Bot Finansial")

        return embed

    def build_dashboard_embed(self, user: discord.User) -> discord.Embed:
        stats = self.calculate_stats(user.id)
        current_month_name = datetime.now().strftime("%B %Y")

        embed = discord.Embed(
            title=f"📊 DASBOR KEUANGAN PRIBADI • {user.display_name.upper()}",
            description=f"Ringkasan arus kas dan kesehatan finansial pribadi Anda periode **{current_month_name}**.",
            color=0x3498DB,
            timestamp=datetime.now()
        )

        embed.add_field(
            name="🏦 Saldo Kas Bersih (Net Cash)",
            value=f"### {format_rupiah(stats['balance'])}",
            inline=False
        )

        embed.add_field(
            name="📈 Pemasukan (Bulan Ini)",
            value=f"**+{format_rupiah(stats['total_in_month'])}**\n*All-time: {format_rupiah(stats['total_in_all'])}*",
            inline=True
        )
        embed.add_field(
            name="📉 Pengeluaran (Bulan Ini)",
            value=f"**-{format_rupiah(stats['total_out_month'])}**\n*All-time: {format_rupiah(stats['total_out_all'])}*",
            inline=True
        )

        if stats["budget"] > 0:
            bar = make_progress_bar(stats["budget_used_pct"])
            budget_info = (
                f"Limit: **{format_rupiah(stats['budget'])}**\n"
                f"Status: `{bar}`\n"
                f"Sisa Pagu: **{format_rupiah(max(stats['budget'] - stats['total_out_month'], 0))}**"
            )
        else:
            budget_info = "Target anggaran belum diatur.\n*Gunakan `/anggaran <nominal>` untuk membatasi belanja.*"
        embed.add_field(name="🎯 Target Anggaran Bulanan", value=budget_info, inline=False)

        rate = stats["saving_rate"]
        if rate >= 30.0:
            health_badge = f"🟢 **PRIMA & SURPLUS** (Saving Rate: {rate:.1f}%)"
            health_desc = "Kinerja arus kas sangat baik. Sebagian besar pemasukan berhasil dipertahankan."
        elif rate >= 10.0:
            health_badge = f"🟡 **STABIL & AMAN** (Saving Rate: {rate:.1f}%)"
            health_desc = "Arus kas positif, disarankan menekan pos pengeluaran sekunder."
        elif rate >= 0.0:
            health_badge = f"🟠 **RENTAN (PAS-PASAN)** (Saving Rate: {rate:.1f}%)"
            health_desc = "Pengeluaran hampir menghabiskan seluruh pemasukan bulan ini."
        else:
            health_badge = f"🔴 **DEFISIT KAS** (Saving Rate: {rate:.1f}%)"
            health_desc = "Pengeluaran melebihi pemasukan. Segera tinjau pos pengeluaran Anda."

        embed.add_field(name="🩺 Status Kesehatan Finansial", value=f"{health_badge}\n*{health_desc}*", inline=False)

        if stats["recent_transactions"]:
            tx_lines = []
            for t in stats["recent_transactions"]:
                icon = "🟢" if t["type"] == "IN" else "🔴"
                sign = "+" if t["type"] == "IN" else "-"
                tx_lines.append(f"{icon} `{t['date_str'][:10]}` **{sign}{format_rupiah(t['amount'])}** • {t['category']} (*{t.get('note', '')[:25]}*)")
            embed.add_field(name="🔄 5 Mutasi Terakhir", value="\n".join(tx_lines), inline=False)
        else:
            embed.add_field(name="🔄 Riwayat Mutasi", value="Belum ada transaksi yang dibukukan.", inline=False)

        embed.set_footer(text="RTM-Bot • Manajer Keuangan Profesional Pribadi")
        return embed

    def build_cashflow_embed(self, user: discord.User) -> discord.Embed:
        stats = self.calculate_stats(user.id)
        current_month_name = datetime.now().strftime("%B %Y")

        embed = discord.Embed(
            title=f"📈 LAPORAN ARUS KAS • {user.display_name.upper()}",
            description=f"Detail distribusi pengeluaran dan mutasi kas periode **{current_month_name}**.",
            color=0x9B59B6,
            timestamp=datetime.now()
        )

        breakdown = stats["category_breakdown"]
        total_out = stats["total_out_month"]
        if breakdown and total_out > 0:
            cat_lines = []
            sorted_cats = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)
            for cat, amt in sorted_cats:
                pct = (amt / total_out) * 100.0
                bar = make_progress_bar(pct, length=8)
                cat_lines.append(f"• **{cat}**: {format_rupiah(amt)} (`{bar}`)")
            embed.add_field(name="📂 Komposisi Pengeluaran Bulan Ini", value="\n".join(cat_lines), inline=False)
        else:
            embed.add_field(name="📂 Komposisi Pengeluaran", value="Belum ada catatan pengeluaran bulan ini.", inline=False)

        profile = self.get_user_profile(user.id)
        all_txs = profile.get("transactions", [])[:10]
        if all_txs:
            tx_lines = []
            for t in all_txs:
                icon = "🟢 [IN]" if t["type"] == "IN" else "🔴 [OUT]"
                sign = "+" if t["type"] == "IN" else "-"
                tx_lines.append(f"`{icon}` **{sign}{format_rupiah(t['amount'])}** | `{t['category']}` | *{t.get('note', '-')[:30]}* ({t['date_str']})")
            embed.add_field(name="📋 10 Transaksi Terakhir", value="\n".join(tx_lines), inline=False)
        else:
            embed.add_field(name="📋 10 Transaksi Terakhir", value="Belum ada catatan transaksi.", inline=False)

        embed.set_footer(text="Gunakan /export_keuangan untuk mengunduh rekap spreadsheet CSV lengkap.")
        return embed

    async def generate_ai_financial_advice(self, user: discord.User, user_question: str = None) -> str:
        global generate_smart_response
        if generate_smart_response is None:
            try:
                from cogs.gemini import generate_smart_response
            except ImportError:
                generate_smart_response = None
        if not generate_smart_response:
            return None

        breakdown_str = ", ".join(f"{k}: Rp {v:,.0f}" for k, v in stats['category_breakdown'].items()) if stats['category_breakdown'] else "Belum ada rincian"
        
        profile = self.get_user_profile(user.id)
        recent_txs = profile.get("transactions", [])[:5]
        recent_tx_str = "\n".join(f"- {t['type']} Rp {t['amount']:,} ({t['category']}: {t.get('note', '')})" for t in recent_txs) if recent_txs else "Belum ada transaksi"

        prompt = (
            "Kamu adalah Raka / Njan Financial Advisor, seorang Certified Financial Planner (CFP) berwawasan tajam setara manajer investasi Wall Street, "
            "namun berbicara dengan gaya santai, cerdas, solutif, dan blak-blakan khas anak muda Indonesia (lu/gue). "
            "Tugasmu adalah menganalisis data keuangan aktual user di bawah ini:\n\n"
            f"Nama User: {user.display_name}\n"
            f"Saldo Kas Bersih: Rp {stats['balance']:,}\n"
            f"Pemasukan Bulan Ini: Rp {stats['total_in_month']:,}\n"
            f"Pengeluaran Bulan Ini: Rp {stats['total_out_month']:,}\n"
            f"Target Anggaran Bulanan: Rp {stats['budget']:,} (Terpakai: {stats['budget_used_pct']:.1f}%)\n"
            f"Saving Rate: {stats['saving_rate']:.1f}%\n"
            f"Rincian Pos Pengeluaran: {breakdown_str}\n"
            f"5 Transaksi Terakhir:\n{recent_tx_str}\n\n"
        )
        if user_question:
            prompt += f"Pertanyaan Spesifik User: \"{user_question}\"\nJawab pertanyaan user secara spesifik dan tajam berdasarkan kondisi keuangannya di atas (maksimal 3 paragraf padat)."
        else:
            prompt += (
                "Berikan evaluasi keuangan personal (maksimal 3-4 paragraf):\n"
                "1. Audit kondisi kas saat ini: apakah surplus, aman, atau boncos/defisit?\n"
                "2. Soroti pos pengeluaran mana yang paling berisiko atau bocor halus.\n"
                "3. Berikan 2 tips taktis langsung yang bisa dieksekusi minggu ini agar saldo bertambah dan keuangan sehat."
            )

        try:
            res = await generate_smart_response(prompt)
            if res and hasattr(res, 'text') and res.text:
                return res.text.strip()
        except Exception as e:
            log.error(f"[FINANCE_AI_ERROR] {e}")
        return None

    def build_advice_embed(self, user: discord.User, ai_analysis: str = None) -> discord.Embed:
        stats = self.calculate_stats(user.id)
        total_in = stats["total_in_month"]
        total_out = stats["total_out_month"]
        breakdown = stats["category_breakdown"]

        needs_categories = ["Makanan", "Tempat Tinggal", "Transportasi", "Tagihan", "Kesehatan", "Cicilan"]
        wants_categories = ["Belanja", "Hiburan", "Lainnya"]
        savings_categories = ["Tabungan", "Edukasi"]

        needs_total = sum(amt for cat, amt in breakdown.items() if any(k.lower() in cat.lower() for k in needs_categories))
        wants_total = sum(amt for cat, amt in breakdown.items() if any(k.lower() in cat.lower() for k in wants_categories))
        savings_total = sum(amt for cat, amt in breakdown.items() if any(k.lower() in cat.lower() for k in savings_categories))

        ref_amount = total_in if total_in > 0 else (total_out if total_out > 0 else 1)
        needs_pct = (needs_total / ref_amount) * 100.0
        wants_pct = (wants_total / ref_amount) * 100.0
        savings_pct = (savings_total / ref_amount) * 100.0

        embed = discord.Embed(
            title=f"💡 EVALUASI PERENCANA KEUANGAN • {user.display_name.upper()}",
            description="Analisis pola alokasi dana menggunakan formula baku **50/30/20 Rule**:",
            color=0xF1C40F,
            timestamp=datetime.now()
        )

        needs_bar = make_progress_bar(needs_pct, length=8)
        wants_bar = make_progress_bar(wants_pct, length=8)
        savings_bar = make_progress_bar(savings_pct, length=8)

        embed.add_field(
            name="1️⃣ Kebutuhan Pokok (Target: ≤50%)",
            value=f"Realisasi: **{format_rupiah(needs_total)}** (`{needs_bar}`)\n*(Makanan, Tempat Tinggal, Tagihan, Transportasi)*",
            inline=False
        )
        embed.add_field(
            name="2️⃣ Keinginan & Gaya Hidup (Target: ≤30%)",
            value=f"Realisasi: **{format_rupiah(wants_total)}** (`{wants_bar}`)\n*(Belanja, Game, Hobi, Hiburan)*",
            inline=False
        )
        embed.add_field(
            name="3️⃣ Tabungan & Investasi (Target: ≥20%)",
            value=f"Realisasi: **{format_rupiah(savings_total)}** (`{savings_bar}`)\n*(Tabungan, Dana Darurat, Edukasi)*",
            inline=False
        )

        if ai_analysis:
            if len(ai_analysis) > 1024:
                embed.add_field(name="🧠 Analisis AI Financial Advisor (Raka CFP)", value=ai_analysis[:1020] + "...", inline=False)
                if len(ai_analysis) > 1020:
                    embed.add_field(name="📌 Rekomendasi Taktis AI", value=ai_analysis[1020:2040], inline=False)
            else:
                embed.add_field(name="🧠 Analisis AI Financial Advisor (Raka CFP)", value=ai_analysis, inline=False)
        else:
            tips = []
            if wants_pct > 35.0:
                tips.append("⚠️ **Kendalikan Pos Gaya Hidup:** Pengeluaran untuk keinginan Anda melampaui batas wajar 30%. Tunda pembelian barang yang belum mendesak.")
            if savings_pct < 15.0 and total_in > 0:
                tips.append("💡 **Tingkatkan Alokasi Tabungan:** Alokasi tabungan Anda masih di bawah standar aman 20%. Terapkan prinsip *pay yourself first* begitu menerima pemasukan.")
            if total_out > total_in and total_in > 0:
                tips.append("🚨 **Rem Arus Kas Negatif:** Pengeluaran bulan ini melebihi pendapatan. Segera audit pos pengeluaran terbesar Anda.")
            if not tips:
                tips.append("🌟 **Struktur Keuangan Prima:** Distribusi kas Anda berada dalam koridor seimbang dan sangat ideal. Terus pertahankan kedisiplinan pencatatan ini!")

            embed.add_field(name="📌 Rekomendasi Manajer Keuangan", value="\n".join(tips), inline=False)
        embed.set_footer(text="RTM-Bot • Konsultan Perencanaan Keuangan")
        return embed

    @commands.hybrid_command(
        name="cash_in",
        aliases=["in", "masuk", "pemasukan"],
        description="Catat dana masuk atau penghasilan baru ke rekening pribadi Anda."
    )
    @app_commands.describe(
        nominal="Jumlah uang masuk dalam Rupiah (contoh: 5000000)",
        kategori="Kategori sumber dana",
        keterangan="Catatan atau sumber dana pemasukan (opsional)"
    )
    @app_commands.choices(kategori=[
        app_commands.Choice(name=label, value=val) for label, val in INCOME_CATEGORIES
    ])
    async def cash_in_command(self, ctx: commands.Context, nominal: int, kategori: str = "Gaji", *, keterangan: str = "Pemasukan"):
        if nominal <= 0:
            return await ctx.send("❌ Nominal pemasukan harus lebih dari 0.", ephemeral=True)
        if nominal > 1_000_000_000_000:
            return await ctx.send("❌ Nominal melebihi batas wajar (maksimal Rp 1 Triliun).", ephemeral=True)

        tx = self.add_transaction(ctx.author.id, "IN", nominal, kategori, keterangan)
        embed = self.build_transaction_embed(ctx.author, tx, "IN")
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="cash_out",
        aliases=["out", "keluar", "pengeluaran"],
        description="Catat pengeluaran atau belanja kas harian Anda."
    )
    @app_commands.describe(
        nominal="Jumlah uang keluar dalam Rupiah (contoh: 50000)",
        kategori="Kategori pengeluaran",
        keterangan="Catatan keperluan belanja (opsional)"
    )
    @app_commands.choices(kategori=[
        app_commands.Choice(name=label, value=val) for label, val in EXPENSE_CATEGORIES
    ])
    async def cash_out_command(self, ctx: commands.Context, nominal: int, kategori: str = "Makanan", *, keterangan: str = "Pengeluaran"):
        if nominal <= 0:
            return await ctx.send("❌ Nominal pengeluaran harus lebih dari 0.", ephemeral=True)
        if nominal > 1_000_000_000_000:
            return await ctx.send("❌ Nominal melebihi batas wajar (maksimal Rp 1 Triliun).", ephemeral=True)

        tx = self.add_transaction(ctx.author.id, "OUT", nominal, kategori, keterangan)
        embed = self.build_transaction_embed(ctx.author, tx, "OUT")
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="keuangan",
        aliases=["saldo", "wallet", "dompet"],
        description="Buka dasbor portofolio keuangan pribadi dan saldo kas Anda."
    )
    async def keuangan_command(self, ctx: commands.Context):
        embed = self.build_dashboard_embed(ctx.author)
        view = DashboardView(self, ctx.author)
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(
        name="cashflow",
        aliases=["mutasi", "laporan_keuangan"],
        description="Lihat laporan arus kas bulanan dan rincian transaksi terbaru."
    )
    async def cashflow_command(self, ctx: commands.Context):
        embed = self.build_cashflow_embed(ctx.author)
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="anggaran",
        aliases=["budget", "setbudget"],
        description="Tetapkan target batas pengeluaran (budget) bulanan Anda."
    )
    @app_commands.describe(nominal="Pagu batas belanja bulanan dalam Rupiah (masukkan 0 untuk menghapus)")
    async def budget_command(self, ctx: commands.Context, nominal: int):
        if nominal < 0 or nominal > 1_000_000_000_000:
            return await ctx.send("❌ Nominal batas anggaran tidak valid.", ephemeral=True)

        profile = self.get_user_profile(ctx.author.id)
        profile["monthly_budget"] = nominal
        self.save_data()

        if nominal == 0:
            embed = discord.Embed(
                title="🎯 Batas Anggaran Dihapus",
                description="Batas anggaran bulanan Anda telah dinonaktifkan.",
                color=0x95A5A6
            )
        else:
            embed = discord.Embed(
                title="🎯 Target Anggaran Berhasil Ditetapkan",
                description=f"Asisten keuangan akan memantau pengeluaran Anda agar tidak melampaui **{format_rupiah(nominal)}** per bulan.",
                color=0x2ECC71
            )
            embed.set_footer(text="Anda akan menerima notifikasi otomatis saat pengeluaran mendekati 80% & 100%.")

        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="konsultasi_keuangan",
        aliases=["evaluasi_keuangan", "fin_advice", "nasehat_keuangan"],
        description="Konsultasikan portofolio & evaluasi pengeluaran langsung dengan AI Perencana Keuangan."
    )
    async def consultation_command(self, ctx: commands.Context):
        await ctx.defer()
        ai_advice = await self.generate_ai_financial_advice(ctx.author)
        embed = self.build_advice_embed(ctx.author, ai_analysis=ai_advice)
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="export_keuangan",
        aliases=["exportfin", "unduh_keuangan"],
        description="Unduh rekapan riwayat mutasi transaksi keuangan pribadi Anda dalam file CSV."
    )
    async def export_command(self, ctx: commands.Context):
        profile = self.get_user_profile(ctx.author.id)
        txs = profile.get("transactions", [])

        if not txs:
            return await ctx.send("❌ Belum ada riwayat transaksi yang dapat diekspor.", ephemeral=True)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID Transaksi", "Waktu", "Tipe", "Kategori", "Nominal (IDR)", "Keterangan"])

        for t in txs:
            writer.writerow([
                t.get("id", ""),
                t.get("date_str", ""),
                t.get("type", ""),
                t.get("category", ""),
                t.get("amount", 0),
                t.get("note", "")
            ])

        output.seek(0)
        file_bytes = io.BytesIO(output.getvalue().encode("utf-8"))
        filename = f"mutasi_keuangan_{ctx.author.name}_{datetime.now().strftime('%Y%m%d')}.csv"
        discord_file = discord.File(fp=file_bytes, filename=filename)

        embed = discord.Embed(
            title="📥 Rekap Finansial Berhasil Dibuat",
            description=f"File rekap CSV berisi **{len(txs)} mutasi transaksi** siap diunduh untuk pembukuan Excel / Google Sheets.",
            color=0x2ECC71
        )
        embed.set_footer(text="RTM-Bot • Asisten Keuangan Pribadi")
        await ctx.send(embed=embed, file=discord_file, ephemeral=True)

    @commands.hybrid_command(
        name="reset_keuangan",
        aliases=["resetfin"],
        description="Hapus seluruh saldo dan riwayat catatan finansial pribadi Anda."
    )
    async def reset_command(self, ctx: commands.Context):
        embed = discord.Embed(
            title="⚠️ Konfirmasi Pembersihan Data Finansial",
            description="Apakah Anda yakin ingin menghapus seluruh saldo, target anggaran, dan riwayat transaksi keuangan Anda?\n\n**Tindakan ini permanen dan tidak dapat dibatalkan.**",
            color=0xE74C3C
        )
        view = ResetConfirmView(self, ctx.author.id)
        await ctx.send(embed=embed, view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Hanya layani percakapan di Direct Message (DM) pribadi yang bukan dari bot
        if message.guild is not None or message.author.bot:
            return

        prefixes = ("!", "?", "/", ".", "-")
        if message.content.startswith(prefixes):
            return

        # Bersihkan mention user/bot, role, channel, emoji, dan url
        text_clean = strip_discord_formatting(message.content).strip()
        if not text_clean:
            return  # Pesan hanya berisi mention bot / link, jangan diintersep

        text_lower = text_clean.lower()

        # 1. Cek Intent: Cek Saldo / Buka Dasbor Portofolio
        if text_lower in ["saldo", "dompet", "cek saldo", "cek dompet", "kas", "keuangan", "portofolio", "dasbor"] or \
           bool(re.search(r'\b(cek saldo|saldo saya|lihat saldo|dompet saya|dasbor keuangan)\b', text_lower)):
            embed = self.build_dashboard_embed(message.author)
            view = DashboardView(self, message.author)
            await message.channel.send(embed=embed, view=view)
            return

        # 2. Cek Intent: Mutasi / Arus Kas
        if text_lower in ["mutasi", "cashflow", "arus kas", "rekap", "laporan"] or \
           bool(re.search(r'\b(cek mutasi|arus kas|laporan keuangan|rekap keuangan|riwayat transaksi)\b', text_lower)):
            embed = self.build_cashflow_embed(message.author)
            await message.channel.send(embed=embed)
            return

        # 3. Cek Intent: Pencatatan Transaksi Cepat (Natural Language Logging via DM)
        nominal = parse_quick_amount(text_clean)
        if nominal > 0:
            tx_type = detect_tx_type(text_clean)
            category = detect_category(text_clean, tx_type)
            note = text_clean[:100]

            tx = self.add_transaction(message.author.id, tx_type, nominal, category, note)
            embed = self.build_transaction_embed(message.author, tx, tx_type)
            await message.channel.send(embed=embed)
            return

        # 4. Cek Intent: Konsultasi Keuangan Eksplisit via Chat DM (AI Financial Advisor)
        # HANYA jika pesan secara spesifik membahas rencana keuangan/investasi/budgeting
        financial_explicit_triggers = [
            "konsultasi keuangan", "saran keuangan", "tips keuangan", "manajemen keuangan",
            "audit keuangan", "rekomendasi budget", "rencana keuangan", "dana darurat",
            "investasi apa", "reksadana", "kenapa boncos", "evaluasi pengeluaran"
        ]
        if any(trigger in text_lower for trigger in financial_explicit_triggers):
            async with message.channel.typing():
                ai_reply = await self.generate_ai_financial_advice(message.author, user_question=text_clean)
                if ai_reply:
                    embed = discord.Embed(
                        title="💡 Konsultasi Finansial Pribadi",
                        description=ai_reply[:4000],
                        color=0xF1C40F,
                        timestamp=datetime.now()
                    )
                    embed.set_footer(text="RTM-Bot • Asisten Perencana Keuangan Pribadi (CFP)")
                    await message.channel.send(embed=embed)
                else:
                    embed = self.build_advice_embed(message.author)
                    await message.channel.send(embed=embed)
            return

        # Jika pesan adalah percakapan biasa (contoh: "halo", "lagi apa", dsb),
        # biarkan lewat agar cogs/gemini.py (Raka AI) dapat merespons obrolan secara alami.

async def setup(bot):
    await bot.add_cog(FinancialAdvisor(bot))
