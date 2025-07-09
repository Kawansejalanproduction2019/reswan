import discord
from discord.ext import commands
import json
import os
import io
from datetime import datetime, timedelta
import aiohttp

# --- PATH FILE DATA ---
SHOP_FILE = 'data/shop_items.json'
LEVEL_FILE = 'data/level_data.json'
BANK_FILE = 'data/bank_data.json'
SHOP_STATUS_FILE = 'data/shop_status.json'
COLLAGE_FILE = 'data/shop_collage.json' # File untuk URL kolase
INVENTORY_FILE = 'data/inventory.json'

# --- KONSTANTA ---
EXP_PRICE_PER_UNIT = 10 # Harga 1 EXP dalam RSWN
DAILY_EXP_LIMIT = 1500 # Maksimal EXP yang bisa dibeli per hari

# --- FUNGSI UTILITY LOAD/SAVE JSON ---
def load_json(path):
    # Pastikan direktori 'data' ada
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        # Beri nilai default yang sesuai jika file tidak ditemukan
        if path == INVENTORY_FILE:
            return {}
        if path == SHOP_FILE:
            return {"badges": [], "exp": [], "roles": [], "special_items": []} # Default shop structure
        if path == SHOP_STATUS_FILE:
            return {"is_open": True, "exp_shop_open": True}
        if path == COLLAGE_FILE:
            return {"collage_url": None} # Default empty collage
        return {} # Fallback untuk file lain
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"Critical Warning: Failed to load or corrupted file -> {path}. Returning empty data and attempting to reset.")
        # Reset file jika korup
        with open(path, 'w', encoding='utf-8') as f:
            if path == INVENTORY_FILE:
                json.dump({}, f)
            elif path == SHOP_FILE:
                json.dump({"badges": [], "exp": [], "roles": [], "special_items": []}, f)
            elif path == SHOP_STATUS_FILE:
                json.dump({"is_open": True, "exp_shop_open": True}, f)
            elif path == COLLAGE_FILE:
                json.dump({"collage_url": None}, f)
            else:
                json.dump({}, f)
        return load_json(path) # Coba load lagi setelah reset


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


def load_shop_status():
    status = load_json(SHOP_STATUS_FILE)
    status.setdefault("is_open", True) # Pastikan key ada
    status.setdefault("exp_shop_open", True) # Pastikan key ada
    return status


def save_shop_status(status: dict):
    save_json(SHOP_STATUS_FILE, status)

# --- MODAL UNTUK PEMBELIAN EXP LANGSUNG ---
class EXPInputModal(discord.ui.Modal, title="Beli EXP Langsung"):
    def __init__(self, user_id, guild_id):
        super().__init__()
        self.user_id = str(user_id)
        self.guild_id = str(guild_id)

        self.exp_amount_input = discord.ui.TextInput(
            label="Berapa EXP yang ingin kamu beli?",
            placeholder=f"Maksimal {DAILY_EXP_LIMIT} EXP per hari. Harga: {EXP_PRICE_PER_UNIT} RSWN/EXP",
            min_length=1,
            max_length=5,
            required=True,
            style=discord.TextStyle.short
        )
        self.add_item(self.exp_amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        shop_status = load_shop_status()
        if not shop_status.get("exp_shop_open", True):
            await interaction.response.send_message("❌ Pembelian EXP sedang ditutup oleh admin.", ephemeral=True)
            return

        try:
            amount_to_buy = int(self.exp_amount_input.value)
            if amount_to_buy <= 0:
                await interaction.response.send_message("Jumlah EXP harus lebih dari 0.", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Jumlah EXP harus berupa angka.", ephemeral=True)
            return

        level_data = load_json(LEVEL_FILE)
        bank_data = load_json(BANK_FILE)

        user_data = level_data.setdefault(self.guild_id, {}).setdefault(self.user_id, {})
        bank_user = bank_data.setdefault(self.user_id, {"balance": 0, "debt": 0})

        last_purchase_date_str = user_data.get("last_exp_purchase_date")
        exp_purchased_today = user_data.get("exp_purchased_today", 0)
        
        today = datetime.utcnow().date()

        if last_purchase_date_str:
            try:
                last_purchase_date = datetime.fromisoformat(last_purchase_date_str).date()
                if last_purchase_date != today: # Reset limit jika hari sudah berganti
                    exp_purchased_today = 0
                    user_data["last_exp_purchase_date"] = today.isoformat()
            except ValueError: # Jika format tanggal di file corrupt
                exp_purchased_today = 0
                user_data["last_exp_purchase_date"] = today.isoformat()
        else:
            user_data["last_exp_purchase_date"] = today.isoformat()


        if exp_purchased_today + amount_to_buy > DAILY_EXP_LIMIT:
            remaining_limit = DAILY_EXP_LIMIT - exp_purchased_today
            await interaction.response.send_message(
                f"❌ Kamu hanya bisa membeli maksimal **{DAILY_EXP_LIMIT} EXP** per hari. Kamu sudah membeli **{exp_purchased_today} EXP** hari ini. Sisa limit: **{remaining_limit} EXP**.",
                ephemeral=True
            )
            return

        total_cost = amount_to_buy * EXP_PRICE_PER_UNIT

        if bank_user['balance'] < total_cost:
            await interaction.response.send_message(f"❌ Saldo RSWN kamu tidak cukup! Kamu butuh **{total_cost} RSWN**.", ephemeral=True)
            return

        bank_user['balance'] -= total_cost
        user_data["exp"] = user_data.get("exp", 0) + amount_to_buy
        user_data["exp_purchased_today"] = exp_purchased_today + amount_to_buy
        
        # Pastikan key 'level' dan 'weekly_exp' ada
        user_data.setdefault('level', 0)
        user_data.setdefault('weekly_exp', 0)
        user_data.setdefault('last_active', datetime.utcnow().isoformat())


        save_json(LEVEL_FILE, level_data)
        save_json(BANK_FILE, bank_data)

        await interaction.response.send_message(
            f"✅ Kamu berhasil membeli **{amount_to_buy} EXP** seharga **{total_cost} RSWN**! Saldo RSWN-mu sekarang: **{bank_user['balance']}**. Sisa limit EXP harian: **{DAILY_EXP_LIMIT - user_data['exp_purchased_today']}**.",
            ephemeral=True
        )

# --- DROPDOWN UNTUK MEMILIH ITEM DALAM KATEGORI ---
class PurchaseDropdown(discord.ui.Select):
    def __init__(self, category, items, user_id, guild_id):
        self.category = category
        self.items = items
        self.user_id = str(user_id)
        self.guild_id = str(guild_id)
        options = []
        for item in items:
            label = f"{item.get('name')} — 💰{item['price']}"
            if item.get('stock', 'unlimited') != 'unlimited':
                label += f" | Stok: {item['stock']}"
            options.append(discord.SelectOption(
                label=label[:100], # Potong agar tidak lebih dari 100 karakter
                value=item['name'],
                description=item.get('description', '')[:100] # Potong agar tidak lebih dari 100 karakter
            ))
        super().__init__(placeholder=f"Pilih item dari {category.title()}", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_item_name = self.values[0]
        item = next((i for i in self.items if i['name'] == selected_item_name), None)
        if not item:
            await interaction.response.send_message("Item tidak ditemukan.", ephemeral=True)
            return

        # Cek stok
        if item.get("stock", "unlimited") != "unlimited" and item["stock"] <= 0:
            await interaction.response.send_message("Stok item ini sudah habis!", ephemeral=True)
            return

        level_data = load_json(LEVEL_FILE)
        bank_data = load_json(BANK_FILE)
        inventory_data = load_json(INVENTORY_FILE)
        
        user_data = level_data.setdefault(self.guild_id, {}).setdefault(self.user_id, {})
        bank_user = bank_data.setdefault(self.user_id, {"balance": 0, "debt": 0})
        inventory_user = inventory_data.setdefault(self.user_id, [])

        # Cek apakah sudah memiliki item tersebut (untuk badge dan role)
        if self.category == "badges" and item['emoji'] in user_data.get("badges", []):
            await interaction.response.send_message("Kamu sudah memiliki badge ini.", ephemeral=True)
            return
        elif self.category == "roles" and item['name'] in user_data.get("purchased_roles", []):
            await interaction.response.send_message("Kamu sudah memiliki role ini.", ephemeral=True)
            return

        # Cek saldo
        if bank_user['balance'] < item['price']:
            await interaction.response.send_message("Saldo RSWN kamu tidak cukup!", ephemeral=True)
            return

        bank_user['balance'] -= item['price']

        purchase_successful = False
        message_to_send = ""

        if self.category == "badges":
            user_data.setdefault("badges", []).append(item['emoji'])
            # Jika badge punya image_url, simpan ke user_data agar bisa dipakai di command rank
            if item.get("image_url"):
                user_data["image_url"] = item["image_url"]
                # Kirim file avatar jika ada image_url
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(item["image_url"]) as resp:
                            if resp.status == 200:
                                avatar_bytes = await resp.read()
                                file = discord.File(fp=io.BytesIO(avatar_bytes), filename="avatar.png")
                                await interaction.user.send(content="Selamat! Pembelian avatar kamu berhasil. Jika kamu mau pasang sebagai profil Discord, nih aku kasih filenya ya!", file=file)
                except Exception as e:
                    print(f"Gagal kirim DM avatar untuk {interaction.user.display_name}: {e}")
            message_to_send = f"✅ Kamu berhasil membeli badge `{item['name']}` seharga **{item['price']} RSWN**!"
            purchase_successful = True

        elif self.category == "roles":
            user_data.setdefault("purchased_roles", []).append(item['name'])
            role_id = item.get("role_id")
            if role_id:
                role = interaction.guild.get_role(int(role_id))
                if role: # Pastikan role ditemukan di guild
                    try:
                        await interaction.user.add_roles(role, reason="Pembelian dari shop")
                        message_to_send = f"✅ Kamu berhasil membeli role `{item['name']}` seharga **{item['price']} RSWN** dan role sudah diberikan!"
                    except discord.Forbidden:
                        message_to_send = f"✅ Kamu berhasil membeli role `{item['name']}` seharga **{item['price']} RSWN**! Tapi aku tidak punya izin untuk memberikan role tersebut. Silakan hubungi admin bot."
                    except Exception as e:
                        message_to_send = f"✅ Kamu berhasil membeli role `{item['name']}` seharga **{item['price']} RSWN**! Terjadi kesalahan saat memberikan role: {e}"
                else:
                    message_to_send = f"✅ Kamu berhasil membeli role `{item['name']}` seharga **{item['price']} RSWN**! Tapi role ID tidak valid atau role tidak ditemukan di server ini. Silakan hubungi admin bot."
            purchase_successful = True
            
        elif self.category == "exp": # Ini adalah pembelian item BOOSTER EXP, bukan EXP langsung
            user_data.setdefault("booster", {})["exp_multiplier"] = item.get("multiplier", 2)
            user_data["booster"]["expires_at"] = (datetime.utcnow() + timedelta(minutes=item.get("duration_minutes", 30))).isoformat()
            message_to_send = f"✅ Kamu berhasil membeli booster EXP `{item['name']}` seharga **{item['price']} RSWN**! Efek: **{item.get('multiplier', 2)}x** selama **{item.get('duration_minutes', 30)} menit**."
            purchase_successful = True

        elif self.category == "special_items":
            item_type = item.get('type')
            inventory_item_to_add = {"name": item['name'], "type": item_type}
            
            inventory_user.append(inventory_item_to_add)
            purchase_successful = True

            if item_type == 'protection_shield':
                message_to_send = f"✅ Kamu berhasil membeli **{item['name']}**! Item ini ada di inventory-mu dan akan aktif otomatis saat kamu diserang monster. Harga: **{item['price']} RSWN**."
            elif item_type == 'gacha_medicine_box':
                message_to_send = f"✅ Kamu berhasil membeli **{item['name']}**! Gunakan `!minumobat` untuk berjudi dengan nasibmu. Harga: **{item['price']} RSWN**."
            else:
                message_to_send = f"✅ Kamu telah membeli `{item['name']}` seharga **{item['price']} RSWN**!"

        if purchase_successful:
            # Kurangi stok jika bukan 'unlimited'
            if item.get("stock", "unlimited") != "unlimited":
                item["stock"] -= 1
                shop_data = load_json(SHOP_FILE)
                # Cari item yang baru saja dibeli di shop_data dan update stoknya
                for cat in shop_data:
                    for i, existing_item in enumerate(shop_data[cat]):
                        if existing_item['name'] == item['name']:
                            shop_data[cat][i] = item # Update item dengan stok baru
                            break
                save_json(SHOP_FILE, shop_data)
            
            save_json(LEVEL_FILE, level_data)
            save_json(BANK_FILE, bank_data)
            save_json(INVENTORY_FILE, inventory_data)
            
            await interaction.response.send_message(message_to_send, ephemeral=True)
        else:
            await interaction.response.send_message("Terjadi kesalahan saat pembelian. Silakan coba lagi.", ephemeral=True)


# --- TOMBOL UNTUK MEMILIH SUB-KATEGORI EXP (EXP Langsung / Booster) ---
class BuyEXPButton(discord.ui.Button):
    def __init__(self, user_id, guild_id):
        super().__init__(label="Beli EXP Langsung!", style=discord.ButtonStyle.success, emoji="⚡")
        self.user_id = user_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EXPInputModal(self.user_id, self.guild_id))


class BuyEXPBoosterButton(discord.ui.Button):
    def __init__(self, shop_data, user_id, guild_id):
        super().__init__(label="Beli Item Booster EXP", style=discord.ButtonStyle.primary, emoji="🚀")
        self.shop_data = shop_data
        self.user_id = user_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        exp_boosters = self.shop_data.get("exp", [])
        if not exp_boosters:
            await interaction.response.send_message("❌ Tidak ada item booster EXP yang tersedia.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🚀 Beli Item Booster EXP",
            description="Pilih item booster EXP di bawah. Ini akan menggandakan EXP dari aktivitas normal (pesan, voice chat) selama durasi tertentu.",
            color=discord.Color.blue()
        )
        # Menampilkan detail item booster di embed
        for item in exp_boosters:
            stock_str = "∞" if item.get("stock", "unlimited") == "unlimited" else str(item["stock"])
            field_name = f"{item.get('emoji', '🔸')} {item['name']} — 💰{item['price']} | Stok: {stock_str}"
            embed.add_field(name=field_name, value=item.get('description', '*Tidak ada deskripsi*') + f"\nEfek: {item.get('multiplier', 'N/A')}x EXP selama {item.get('duration_minutes', 'N/A')} menit.", inline=False)
        
        view = discord.ui.View(timeout=60)
        view.add_item(PurchaseDropdown("exp", exp_boosters, self.user_id, self.guild_id)) # Dropdown untuk memilih booster
        view.add_item(BackToEXPMenuButton(self.shop_data, self.user_id, self.guild_id)) # Tombol kembali
        await interaction.response.edit_message(embed=embed, view=view)

# --- TOMBOL KEMBALI KE MENU EXP UTAMA ---
class BackToEXPMenuButton(discord.ui.Button):
    def __init__(self, shop_data, user_id, guild_id):
        super().__init__(label="⬅️ Kembali ke Menu EXP", style=discord.ButtonStyle.secondary)
        self.shop_data = shop_data
        self.user_id = user_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        shop_status = load_shop_status()
        embed = discord.Embed(
            title="⚡ Toko EXP",
            description=(
                f"Beli EXP langsung (Harga: **{EXP_PRICE_PER_UNIT} RSWN/EXP**, Batas Harian: **{DAILY_EXP_LIMIT} EXP**).\n"
                f"Atau beli Item Booster untuk menggandakan EXP aktivitasmu."
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="Pilih opsi di bawah.")
        
        view = discord.ui.View(timeout=60)
        view.add_item(BuyEXPButton(self.user_id, self.guild_id))
        view.add_item(BuyEXPBoosterButton(self.shop_data, self.user_id, self.guild_id))
        view.add_item(BackToCategoryButton(self.shop_data, self.user_id, self.guild_id)) # Kembali ke menu kategori utama
        await interaction.response.edit_message(embed=embed, view=view)

# --- VIEW UTAMA UNTUK KATEGORI TOKO ---
class ShopCategoryView(discord.ui.View):
    def __init__(self, bot, shop_data, user_id, guild_id):
        super().__init__(timeout=120) # Timeout 2 menit
        self.bot = bot
        self.shop_data = shop_data
        self.user_id = user_id
        self.guild_id = guild_id
        self.add_item(ShopCategorySelect(shop_data, user_id, guild_id))


class ShopCategorySelect(discord.ui.Select):
    def __init__(self, shop_data, user_id, guild_id):
        self.shop_data = shop_data
        self.user_id = user_id
        self.guild_id = guild_id
        options = [
            discord.SelectOption(label="🎭 Badges", value="badges", description="Lencana keren buat profilmu!"),
            discord.SelectOption(label="⚡ EXP", value="exp", description=f"Opsi beli EXP langsung atau booster!"),
            discord.SelectOption(label="👑 Roles", value="roles", description="Dapatkan role spesial di server!"),
            discord.SelectOption(label="🛡️ Bertahan Hidup", value="special_items", description="Item untuk menghadapi ancaman dunia!")
        ]
        super().__init__(placeholder="Pilih kategori item", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        
        shop_status = load_shop_status()
        # Jika kategori EXP dipilih dan toko EXP ditutup
        if not shop_status.get("exp_shop_open", True) and category == "exp":
            embed = discord.Embed(
                title="⚡ Toko EXP",
                description="❌ Pembelian EXP (langsung dan booster) sedang **ditutup** oleh admin.",
                color=discord.Color.red()
            )
            view = discord.ui.View(timeout=60)
            view.add_item(BackToCategoryButton(self.shop_data, self.user_id, self.guild_id)) # Kembali ke menu kategori utama
            await interaction.response.edit_message(embed=embed, view=view)
            return

        # Jika kategori EXP dipilih dan toko EXP terbuka
        if category == "exp":
            embed = discord.Embed(
                title="⚡ Toko EXP",
                description=(
                    f"Beli EXP langsung (Harga: **{EXP_PRICE_PER_UNIT} RSWN/EXP**, Batas Harian: **{DAILY_EXP_LIMIT} EXP**).\n"
                    f"Atau beli Item Booster untuk menggandakan EXP aktivitasmu."
                ),
                color=discord.Color.gold()
            )
            embed.set_footer(text="Pilih opsi di bawah.")
            
            view = discord.ui.View(timeout=60)
            view.add_item(BuyEXPButton(self.user_id, self.guild_id)) # Tombol beli EXP langsung
            view.add_item(BuyEXPBoosterButton(self.shop_data, self.user_id, self.guild_id)) # Tombol beli booster
            view.add_item(BackToCategoryButton(self.shop_data, self.user_id, self.guild_id)) # Tombol kembali ke kategori
            await interaction.response.edit_message(embed=embed, view=view)
            return

        # Untuk kategori selain EXP
        items = self.shop_data.get(category, [])
        embed = discord.Embed(
            title=f"🛍️ {category.title()} Shop",
            description=f"Pilih item dari kategori **{category}** untuk dibeli.",
            color=discord.Color.orange()
        )
        if not items:
            embed.description = "Tidak ada item dalam kategori ini."
        else:
            for item in items:
                stock_str = "∞" if item.get("stock", "unlimited") == "unlimited" else str(item["stock"])
                name = item['name']
                price = item['price']
                desc = item.get('description', '*Tidak ada deskripsi*')
                field_name = f"{item.get('emoji', '🔸')} {name} — 💰{price} | Stok: {stock_str}"
                embed.add_field(name=field_name, value=desc, inline=False)

        view = discord.ui.View(timeout=60)
        if items: # Hanya tampilkan dropdown jika ada item
            view.add_item(PurchaseDropdown(category, items, self.user_id, self.guild_id))
        view.add_item(BackToCategoryButton(self.shop_data, self.user_id, self.guild_id))
        await interaction.response.edit_message(embed=embed, view=view)

# --- TOMBOL KEMBALI KE MENU UTAMA TOKO ---
class BackToCategoryButton(discord.ui.Button):
    def __init__(self, shop_data, user_id, guild_id):
        super().__init__(label="⬅️ Kembali", style=discord.ButtonStyle.secondary)
        self.shop_data = shop_data
        self.user_id = user_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        # Saat kembali, perlu muat ulang shop_data karena stok mungkin sudah berubah
        current_shop_data = load_json(SHOP_FILE)
        # Muat ulang URL kolase juga
        current_collage_url = load_json(COLLAGE_FILE).get("collage_url")

        embed = discord.Embed(
            title="💎 reSwan Shop",
            description="Pilih kategori di bawah untuk melihat item yang tersedia.",
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Gunakan dropdown untuk melihat item.")
        # Tambahkan kembali gambar kolase ke embed utama
        if current_collage_url:
            embed.set_image(url=current_collage_url)

        view = ShopCategoryView(interaction.client, current_shop_data, self.user_id, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)


# --- COG UTAMA SHOP ---
class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.shop_data = load_json(SHOP_FILE) # Memuat shop_data saat cog diinisialisasi
        self.collage_url = load_json(COLLAGE_FILE).get("collage_url") # Memuat URL kolase saat cog diinisialisasi

    @commands.command(name="shop")
    async def shop(self, ctx):
        status = load_shop_status()
        if not status.get("is_open", True):
            return await ctx.send("⚠️ Toko sedang *ditutup* oleh admin. Silakan kembali lagi nanti.", ephemeral=True)

        # Muat ulang data terbaru setiap kali command !shop dipanggil
        self.shop_data = load_json(SHOP_FILE)
        self.collage_url = load_json(COLLAGE_FILE).get("collage_url")

        embed = discord.Embed(
            title="💎 reSwan Shop",
            description="Pilih kategori di bawah untuk melihat item yang tersedia.",
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Gunakan dropdown untuk melihat item.")

        # Tambahkan gambar kolase ke embed utama toko
        if self.collage_url:
            embed.set_image(url=self.collage_url)

        view = ShopCategoryView(self.bot, self.shop_data, ctx.author.id, ctx.guild.id)

        try:
            await ctx.message.delete() # Hapus command user untuk kerapian
        except (discord.NotFound, discord.Forbidden):
            pass # Abaikan jika pesan tidak ditemukan atau bot tidak punya izin

        await ctx.send(embed=embed, view=view)

    @commands.command(name="toggleshop")
    @commands.has_permissions(administrator=True)
    async def toggle_shop(self, ctx):
        status = load_shop_status()
        status["is_open"] = not status.get("is_open", True)
        save_shop_status(status)

        state = "🟢 TERBUKA" if status["is_open"] else "🔴 TERTUTUP"
        await ctx.send(f"Toko sekarang telah diatur ke: **{state}**")

    @commands.command(name="toggleexpshop")
    @commands.has_permissions(administrator=True)
    async def toggle_exp_shop(self, ctx):
        status = load_shop_status()
        status["exp_shop_open"] = not status.get("exp_shop_open", True)
        save_shop_status(status)

        state = "🟢 TERBUKA" if status["exp_shop_open"] else "🔴 TERTUTUP"
        await ctx.send(f"Toko pembelian EXP sekarang telah diatur ke: **{state}**")

    @commands.command(name="additem")
    @commands.has_permissions(administrator=True)
    async def add_item(self, ctx, category: str, name: str, price: int, description: str, *args):
        shop_data = load_json(SHOP_FILE)

        valid_categories = ["badges", "exp", "roles", "special_items"]
        category_lower = category.lower() # Ubah ke huruf kecil untuk validasi

        if category_lower not in valid_categories:
            await ctx.send(f"⚠️ Kategori tidak valid. Gunakan: `{', '.join(valid_categories)}`.", ephemeral=True)
            return

        if category_lower not in shop_data:
            shop_data[category_lower] = [] # Pastikan list ada
        
        # Ambil argumen opsional dengan aman
        emoji_or_type = args[0] if len(args) > 0 else None
        stock_str = args[1] if len(args) > 1 else "unlimited"
        
        # Sisa argumen untuk multiplier dan duration (khusus exp) atau role_id/image_url (khusus badges/roles)
        remaining_args = args[2:] 

        item = {
            "name": name,
            "price": price,
            "description": description,
            "stock": int(stock_str) if stock_str.lower() != "unlimited" else "unlimited"
        }

        # Logika spesifik per kategori
        if category_lower == "roles":
            if not remaining_args:
                return await ctx.send("⚠️ Untuk kategori 'roles', harap masukkan `[role_id]` sebagai argumen terakhir.", ephemeral=True)
            item["role_id"] = int(remaining_args[0])
            item["emoji"] = emoji_or_type or "👑" # Default emoji jika tidak ada
        elif category_lower == "badges":
            item["emoji"] = emoji_or_type or "🎭" # Default emoji jika tidak ada
            if remaining_args: # image_url adalah argumen terakhir
                item["image_url"] = remaining_args[0]
        elif category_lower == "exp": # Ini untuk item BOOSTER EXP
            if len(remaining_args) < 2:
                return await ctx.send("⚠️ Untuk kategori 'exp' (booster), Anda harus menyediakan: `[multiplier]` dan `[duration_minutes]` setelah deskripsi dan stok.", ephemeral=True)
            try:
                item["multiplier"] = int(remaining_args[0])
                item["duration_minutes"] = int(remaining_args[1])
            except ValueError:
                return await ctx.send("⚠️ Untuk kategori 'exp' (booster), multiplier dan durasi (menit) harus angka.", ephemeral=True)
            item["type"] = "exp_booster"
            item["emoji"] = emoji_or_type or "🚀" # Default emoji jika tidak ada
        elif category_lower == "special_items":
            item_type = emoji_or_type # argumen pertama setelah deskripsi dan stok
            if not item_type:
                return await ctx.send("⚠️ Untuk kategori 'special_items', harap masukkan `[type_item]` (misal: `protection_shield`, `gacha_medicine_box`) sebagai argumen pertama setelah deskripsi dan stok.", ephemeral=True)
            item["type"] = item_type
            # Default emoji berdasarkan tipe
            if item_type == "protection_shield":
                item["emoji"] = "🛡️"
            elif item_type == "gacha_medicine_box":
                item["emoji"] = "💊"
            else:
                item["emoji"] = "📦" # Default lainnya

        # Cek apakah item sudah ada, jika ya, update; jika tidak, tambahkan baru
        item_exists = False
        for i, existing_item in enumerate(shop_data.get(category_lower, [])):
            if existing_item['name'] == name:
                shop_data[category_lower][i] = item # Update item yang sudah ada
                item_exists = True
                break
        
        if not item_exists:
            shop_data[category_lower].append(item) # Tambahkan item baru

        save_json(SHOP_FILE, shop_data)
        await ctx.send(f"✅ Item baru/diperbarui di kategori **{category_lower}**: **{name}** seharga **{price}** RSWN! 🎉")


    @commands.command(name="addcollage")
    @commands.has_permissions(administrator=True)
    async def add_collage(self, ctx, url: str):
        # Validasi URL sederhana
        if not url.startswith("http://") and not url.startswith("https://"):
            return await ctx.send("❌ URL gambar tidak valid. Harus dimulai dengan `http://` atau `https://`.", ephemeral=True)
        
        # Simpan URL kolase
        save_json(COLLAGE_FILE, {"collage_url": url})
        # Perbarui juga atribut cog untuk tampilan yang instan
        self.collage_url = url
        await ctx.send("✅ Gambar kolase berhasil diperbarui dan akan muncul di `!shop`!")

    @commands.command(name="removeitem")
    @commands.has_permissions(administrator=True)
    async def remove_item(self, ctx, category: str, name: str):
        shop_data = load_json(SHOP_FILE)
        category_lower = category.lower()

        if category_lower not in shop_data:
            return await ctx.send(f"❌ Kategori **{category}** tidak ditemukan di toko.", ephemeral=True)

        original_len = len(shop_data[category_lower])
        shop_data[category_lower] = [item for item in shop_data[category_lower] if item['name'].lower() != name.lower()]

        if len(shop_data[category_lower]) < original_len:
            save_json(SHOP_FILE, shop_data)
            await ctx.send(f"✅ Item **{name}** dari kategori **{category}** berhasil dihapus dari toko.", ephemeral=False)
        else:
            await ctx.send(f"❌ Item **{name}** tidak ditemukan di kategori **{category}**.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Shop(bot))
