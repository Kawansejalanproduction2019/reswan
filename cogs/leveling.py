import discord
from discord.ext import commands, tasks
import json
import os
import random
import logging
import asyncio
from datetime import datetime, timedelta
from PIL import Image, ImageDraw
import requests
from io import BytesIO
import io
import aiohttp

# --- PATH FILE DATA ---
LEVEL_FILE = "data/level_data.json"
BANK_FILE = "data/bank_data.json"
SHOP_FILE = "data/shop_items.json"
QUESTS_FILE = "data/quests.json"
CONFIG_FILE = "data/config.json"
SHOP_STATUS_FILE = 'data/shop_status.json'
COLLAGE_FILE = 'data/shop_collage.json'
INVENTORY_FILE = 'data/inventory.json'

# --- KONSTANTA ---
WEEKLY_RESET_DAY = 0
LEVEL_BADGES = {
    5: "🥉",
    10: "🥈",
    15: "🥇",
}
EXP_PRICE_PER_UNIT = 10
DAILY_EXP_LIMIT = 1500

# --- FUNGSI UTILITY LOAD/SAVE JSON ---
def load_json(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        default_data = {}
        if path in [INVENTORY_FILE, CONFIG_FILE, BANK_FILE, LEVEL_FILE]:
            default_data = {}
        elif path == SHOP_FILE:
            default_data = {"badges": [], "exp": [], "roles": [], "special_items": []}
        elif path == QUESTS_FILE:
             default_data = {"quests": {}}
        elif path == SHOP_STATUS_FILE:
            default_data = {"is_open": True, "exp_shop_open": True}
        elif path == COLLAGE_FILE:
            default_data = {"collage_url": None}
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, indent=4)
        return default_data

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"Critical Warning: Failed to load or corrupted file -> {path}. Returning empty data and attempting to reset.")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        return {}

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def calculate_level(exp):
    return exp // 3500

async def crop_avatar_to_circle(user: discord.User):
    async with aiohttp.ClientSession() as session:
        async with session.get(user.display_avatar.url) as resp:
            avatar_bytes = await resp.read()

    with Image.open(BytesIO(avatar_bytes)).convert("RGBA") as img:
        size = (256, 256)
        img = img.resize(size)
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0) + size, fill=255)
        output = Image.new("RGBA", size)
        output.paste(img, (0, 0), mask)
        buffer = BytesIO()
        output.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

# --- UI COMPONENTS (MODALS, VIEWS, BUTTONS) ---
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
        shop_status = load_json(SHOP_STATUS_FILE)
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
                if last_purchase_date != today:
                    exp_purchased_today = 0
                    user_data["last_exp_purchase_date"] = today.isoformat()
            except ValueError:
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
        user_data.setdefault('level', 0)
        user_data.setdefault('weekly_exp', 0)
        user_data.setdefault('last_active', datetime.utcnow().isoformat())

        save_json(LEVEL_FILE, level_data)
        save_json(BANK_FILE, bank_data)
        await interaction.response.send_message(
            f"✅ Kamu berhasil membeli **{amount_to_buy} EXP** seharga **{total_cost} RSWN**! Saldo RSWN-mu sekarang: **{bank_user['balance']}**. Sisa limit EXP harian: **{DAILY_EXP_LIMIT - user_data['exp_purchased_today']}**.",
            ephemeral=True
        )

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
                label=label[:100],
                value=item['name'],
                description=item.get('description', '')[:100]
            ))
        super().__init__(placeholder=f"Pilih item dari {category.title()}", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_item_name = self.values[0]
        item = next((i for i in self.items if i['name'] == selected_item_name), None)
        if not item:
            await interaction.response.send_message("Item tidak ditemukan.", ephemeral=True)
            return

        if item.get("stock", "unlimited") != "unlimited" and item["stock"] <= 0:
            await interaction.response.send_message("Stok item ini sudah habis!", ephemeral=True)
            return

        level_data = load_json(LEVEL_FILE)
        bank_data = load_json(BANK_FILE)
        inventory_data = load_json(INVENTORY_FILE)
        
        user_data = level_data.setdefault(self.guild_id, {}).setdefault(self.user_id, {})
        bank_user = bank_data.setdefault(self.user_id, {"balance": 0, "debt": 0})
        inventory_user = inventory_data.setdefault(self.user_id, [])

        if self.category == "badges" and item['emoji'] in user_data.get("badges", []):
            await interaction.response.send_message("Kamu sudah memiliki badge ini.", ephemeral=True)
            return
        elif self.category == "roles" and item['name'] in user_data.get("purchased_roles", []):
            await interaction.response.send_message("Kamu sudah memiliki role ini.", ephemeral=True)
            return

        if bank_user['balance'] < item['price']:
            await interaction.response.send_message("Saldo RSWN kamu tidak cukup!", ephemeral=True)
            return

        bank_user['balance'] -= item['price']
        purchase_successful = False
        message_to_send = ""

        if self.category == "badges":
            user_data.setdefault("badges", []).append(item['emoji'])
            if item.get("image_url"):
                user_data["image_url"] = item["image_url"]
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
                if role:
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
        elif self.category == "exp":
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
            if item.get("stock", "unlimited") != "unlimited":
                item["stock"] -= 1
                shop_data = load_json(SHOP_FILE)
                for cat in shop_data:
                    for i, existing_item in enumerate(shop_data[cat]):
                        if existing_item['name'] == item['name']:
                            shop_data[cat][i] = item
                            break
                save_json(SHOP_FILE, shop_data)
            
            save_json(LEVEL_FILE, level_data)
            save_json(BANK_FILE, bank_data)
            save_json(INVENTORY_FILE, inventory_data)
            
            await interaction.response.send_message(message_to_send, ephemeral=True)
        else:
            await interaction.response.send_message("Terjadi kesalahan saat pembelian. Silakan coba lagi.", ephemeral=True)

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
        for item in exp_boosters:
            stock_str = "∞" if item.get("stock", "unlimited") == "unlimited" else str(item["stock"])
            field_name = f"{item.get('emoji', '🔸')} {item['name']} — 💰{item['price']} | Stok: {stock_str}"
            embed.add_field(name=field_name, value=item.get('description', '*Tidak ada deskripsi*') + f"\nEfek: {item.get('multiplier', 'N/A')}x EXP selama {item.get('duration_minutes', 'N/A')} menit.", inline=False)
        
        view = discord.ui.View(timeout=60)
        view.add_item(PurchaseDropdown("exp", exp_boosters, self.user_id, self.guild_id))
        view.add_item(BackToEXPMenuButton(self.shop_data, self.user_id, self.guild_id))
        await interaction.response.edit_message(embed=embed, view=view)

class BackToEXPMenuButton(discord.ui.Button):
    def __init__(self, shop_data, user_id, guild_id):
        super().__init__(label="⬅️ Kembali ke Menu EXP", style=discord.ButtonStyle.secondary)
        self.shop_data = shop_data
        self.user_id = user_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
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
        view.add_item(BackToCategoryButton(self.shop_data, self.user_id, self.guild_id))
        await interaction.response.edit_message(embed=embed, view=view)

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
        shop_status = load_json(SHOP_STATUS_FILE)
        
        if not shop_status.get("exp_shop_open", True) and category == "exp":
            embed = discord.Embed(
                title="⚡ Toko EXP",
                description="❌ Pembelian EXP (langsung dan booster) sedang **ditutup** oleh admin.",
                color=discord.Color.red()
            )
            view = discord.ui.View(timeout=60)
            view.add_item(BackToCategoryButton(self.shop_data, self.user_id, self.guild_id))
            await interaction.response.edit_message(embed=embed, view=view)
            return

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
            view.add_item(BuyEXPButton(self.user_id, self.guild_id))
            view.add_item(BuyEXPBoosterButton(self.shop_data, self.user_id, self.guild_id))
            view.add_item(BackToCategoryButton(self.shop_data, self.user_id, self.guild_id))
            await interaction.response.edit_message(embed=embed, view=view)
            return

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
        if items:
            view.add_item(PurchaseDropdown(category, items, self.user_id, self.guild_id))
        view.add_item(BackToCategoryButton(self.shop_data, self.user_id, self.guild_id))
        await interaction.response.edit_message(embed=embed, view=view)

class BackToCategoryButton(discord.ui.Button):
    def __init__(self, shop_data, user_id, guild_id):
        super().__init__(label="⬅️ Kembali", style=discord.ButtonStyle.secondary)
        self.shop_data = shop_data
        self.user_id = user_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        current_shop_data = load_json(SHOP_FILE)
        current_collage_url = load_json(COLLAGE_FILE).get("collage_url")

        embed = discord.Embed(
            title="💎 reSwan Shop",
            description="Pilih kategori di bawah untuk melihat item yang tersedia.",
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Gunakan dropdown untuk melihat item.")
        if current_collage_url:
            embed.set_image(url=current_collage_url)

        view = ShopCategoryView(interaction.client, current_shop_data, self.user_id, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

class ShopCategoryView(discord.ui.View):
    def __init__(self, bot, shop_data, user_id, guild_id):
        super().__init__(timeout=120)
        self.bot = bot
        self.shop_data = shop_data
        self.user_id = user_id
        self.guild_id = guild_id
        self.add_item(ShopCategorySelect(shop_data, user_id, guild_id))

class CategoryDropdown(discord.ui.Select):
    def __init__(self, bot, categories):
        self.bot = bot
        options = [discord.SelectOption(label=cat) for cat in categories]
        super().__init__(placeholder="Pilih kategori...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content=f"📦 Kategori dipilih: **{self.values[0]}**\nPilih item yang ingin dikelola:", view=ItemSelectionView(self.bot, self.values[0]))

class ItemDropdown(discord.ui.Select):
    def __init__(self, bot, category):
        self.bot = bot
        self.category = category
        with open(SHOP_FILE, 'r') as f:
            data = json.load(f)
        options = []
        for i, item in enumerate(data.get(category, [])):
            options.append(discord.SelectOption(
                label=item.get("name", f"Item {i}"),
                description=item.get("description", "Tanpa deskripsi")[:100],
                emoji=item.get("emoji", None),
                value=str(i)
            ))
        super().__init__(placeholder="Pilih item untuk dikelola...", options=options)

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])
        await interaction.response.edit_message(
            content=f"🔧 Kelola item dari kategori **{self.category}**:",
            view=ItemActionView(self.bot, self.category, index)
        )

class EditItemButton(discord.ui.Button):
    def __init__(self, bot, category, index):
        super().__init__(label="Edit Item", style=discord.ButtonStyle.primary)
        self.bot = bot
        self.category = category
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditItemModal(self.bot, self.category, self.index))

class RestockItemButton(discord.ui.Button):
    def __init__(self, bot, category, index):
        super().__init__(label="Restock Item", style=discord.ButtonStyle.secondary)
        self.bot = bot
        self.category = category
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RestockModal(self.category, self.index))

class DeleteItemButton(discord.ui.Button):
    def __init__(self, bot, category, index):
        super().__init__(label="Hapus Item", style=discord.ButtonStyle.danger)
        self.category = category
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        with open(SHOP_FILE, 'r') as f:
            data = json.load(f)
        item_name = data[self.category][self.index]["name"]
        data[self.category].pop(self.index)
        with open(SHOP_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        await interaction.response.edit_message(content=f"🗑️ Item **{item_name}** berhasil dihapus.", view=None)

class ItemActionView(discord.ui.View):
    def __init__(self, bot, category, index):
        super().__init__(timeout=60)
        self.add_item(EditItemButton(bot, category, index))
        self.add_item(RestockItemButton(bot, category, index))
        self.add_item(DeleteItemButton(bot, category, index))

class ItemSelectionView(discord.ui.View):
    def __init__(self, bot, category):
        super().__init__(timeout=60)
        self.bot = bot
        self.category = category
        self.add_item(ItemDropdown(bot, category))
        
class CategoryDropdownView(discord.ui.View):
    def __init__(self, bot, categories):
        super().__init__(timeout=60)
        self.add_item(CategoryDropdown(bot, categories))

class EditItemModal(discord.ui.Modal, title="Edit Item"):
    def __init__(self, bot, category, index):
        super().__init__()
        self.bot = bot
        self.category = category
        self.index = index
        self.name = discord.ui.TextInput(label="Nama Baru", required=True)
        self.description = discord.ui.TextInput(label="Deskripsi Baru", required=True)
        self.emoji = discord.ui.TextInput(label="Emoji Baru (opsional)", required=False)
        self.price = discord.ui.TextInput(label="Harga Baru", required=True)
        self.image_url = discord.ui.TextInput(label="Image URL (opsional)", required=False)
        self.add_item(self.name)
        self.add_item(self.description)
        self.add_item(self.emoji)
        self.add_item(self.price)
        self.add_item(self.image_url)

    async def on_submit(self, interaction: discord.Interaction):
        with open(SHOP_FILE, 'r') as f:
            data = json.load(f)
        item = data[self.category][self.index]
        item["name"] = self.name.value
        item["description"] = self.description.value
        item["emoji"] = self.emoji.value or None
        item["price"] = int(self.price.value)
        item["image_url"] = self.image_url.value or None
        with open(SHOP_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        await interaction.response.send_message(f"✅ Item **{self.name.value}** berhasil diperbarui.", ephemeral=True)

class RestockModal(discord.ui.Modal, title="Restock Item"):
    def __init__(self, category, index):
        super().__init__()
        self.category = category
        self.index = index
        self.stock = discord.ui.TextInput(label="Stok Baru", required=True)
        self.add_item(self.stock)

    async def on_submit(self, interaction: discord.Interaction):
        with open(SHOP_FILE, 'r') as f:
            data = json.load(f)
        item = data[self.category][self.index]
        item["stock"] = int(self.stock.value)
        with open(SHOP_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        await interaction.response.send_message(f"📦 Stok untuk **{item['name']}** sekarang: {self.stock.value}", ephemeral=True)


# --- SINGLE INTEGRATED COG ---
class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # --- Attributes from Leveling Cog ---
        self.EXP_PER_MINUTE_VC = 5
        self.RSWN_PER_MINUTE_VC = 10
        self.EXP_PER_MESSAGE = 10
        self.RSWN_PER_MESSAGE = 1
        self.voice_task = self.create_voice_task()
        self.last_reset = datetime.utcnow()
        self.daily_quest_task.start()
        self.voice_task.start()
        logging.basicConfig(level=logging.INFO)
        
        # --- Attributes from Shop Cog ---
        self.shop_data = load_json(SHOP_FILE)
        self.collage_url = load_json(COLLAGE_FILE).get("collage_url")

    # --- METHODS FROM LEVELING COG ---
    def get_anomaly_multiplier(self):
        dunia_cog = self.bot.get_cog('DuniaHidup')
        if dunia_cog and dunia_cog.active_anomaly and dunia_cog.active_anomaly.get('type') == 'exp_boost':
            return dunia_cog.active_anomaly.get('effect', {}).get('multiplier', 1)
        return 1

    def create_voice_task(self):
        @tasks.loop(minutes=1)
        async def voice_task():
            try:
                now = datetime.utcnow()
                anomaly_multiplier = self.get_anomaly_multiplier()
                
                for guild in self.bot.guilds:
                    guild_id = str(guild.id)
                    all_level_data = load_json(LEVEL_FILE)
                    data = all_level_data.setdefault(guild_id, {})
                    bank_data = load_json(BANK_FILE)

                    for vc in guild.voice_channels:
                        for member in vc.members:
                            if member.bot or member.voice.self_deaf or member.voice.self_mute:
                                continue

                            user_id = str(member.id)
                            if user_id not in data:
                                data[user_id] = {"exp": 0, "weekly_exp": 0, "level": 0, "badges": []}
                            
                            exp_gain_vc = int(self.EXP_PER_MINUTE_VC * anomaly_multiplier)
                            rswn_gain_vc = int(self.RSWN_PER_MINUTE_VC * anomaly_multiplier)

                            data[user_id]["exp"] += exp_gain_vc
                            data[user_id].setdefault("weekly_exp", 0)
                            data[user_id]["weekly_exp"] += exp_gain_vc

                            if user_id not in bank_data:
                                bank_data[user_id] = {"balance": 0, "debt": 0}
                            bank_data[user_id]["balance"] += rswn_gain_vc

                            new_level = calculate_level(data[user_id]["exp"])
                            if new_level > data[user_id].get("level", 0):
                                data[user_id]["level"] = new_level
                                await self.level_up(member, guild, None, new_level, data)

                    all_level_data[guild_id] = data
                    save_json(LEVEL_FILE, all_level_data)
                    save_json(BANK_FILE, bank_data)

                    if now.weekday() == WEEKLY_RESET_DAY and now.date() != self.last_reset.date():
                        for user_data in data.values():
                            user_data["weekly_exp"] = 0
                        self.last_reset = now
                        save_json(LEVEL_FILE, all_level_data)
            except Exception as e:
                print(f"Error in voice task: {e}")
        return voice_task

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        if message.content.startswith(self.bot.command_prefix):
            logging.info(f"Pesan adalah perintah: {message.content}")
            return

        user_id = str(message.author.id)
        guild_id = str(message.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.setdefault(guild_id, {})

        if user_id not in data:
            data[user_id] = {"exp": 0, "weekly_exp": 0, "level": 0, "badges": [], "last_active": None, "booster": {}}
        
        user_level_data = data[user_id]
        booster = user_level_data.get("booster", {})
        personal_multiplier = 1
        expires = booster.get("expires_at")

        if expires:
            try:
                if datetime.utcnow() < datetime.fromisoformat(expires):
                    personal_multiplier = booster.get("exp_multiplier", 1)
                else:
                    user_level_data["booster"] = {}
            except Exception as e:
                print(f"[BOOSTER ERROR] Gagal parsing expires_at: {e}")
                user_level_data["booster"] = {}
        
        anomaly_multiplier = self.get_anomaly_multiplier()
        final_multiplier = personal_multiplier * anomaly_multiplier
        exp_gain = int(self.EXP_PER_MESSAGE * final_multiplier)
        rswn_gain = int(self.RSWN_PER_MESSAGE * final_multiplier)
        
        bank_data = load_json(BANK_FILE)
        if user_id not in bank_data:
            bank_data[user_id] = {"balance": 0, "debt": 0}
        bank_data[user_id]["balance"] += rswn_gain
        
        user_level_data["exp"] += exp_gain
        user_level_data.setdefault("weekly_exp", 0)
        user_level_data["weekly_exp"] += exp_gain
        user_level_data["last_active"] = datetime.utcnow().isoformat()
        print(f"[ACTIVITY] {message.author} dapat +{exp_gain} EXP & +{rswn_gain} RSWN (x{final_multiplier} booster total)")

        new_level = calculate_level(user_level_data["exp"])
        if new_level > user_level_data.get("level", 0):
            user_level_data["level"] = new_level
            await self.level_up(message.author, message.guild, message.channel, new_level, data)
        
        all_level_data[guild_id] = data
        save_json(LEVEL_FILE, all_level_data)
        save_json(BANK_FILE, bank_data)

    @tasks.loop(hours=24)
    async def daily_quest_task(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            guild_id = str(guild.id)
            all_configs = load_json(CONFIG_FILE)
            config = all_configs.get(guild_id, {})
            announce_channel_id = config.get("announce_channel")
            if not announce_channel_id:
                continue

            announce_channel = guild.get_channel(announce_channel_id)
            if not announce_channel:
                continue

            quests_data = load_json(QUESTS_FILE)
            if not quests_data or "quests" not in quests_data: continue
            
            quests = list(quests_data.get("quests", {}).values())
            if quests:
                random_quest = random.choice(quests)
                with open(f"data/daily_quest_{guild.id}.json", "w") as f:
                    json.dump(random_quest, f)
                await announce_channel.send(f"🎉 Quest Harian Baru! {random_quest['description']} (Reward: {random_quest['reward_exp']} EXP, {random_quest['reward_coins']} 🪙RSWN)")

    async def level_up(self, member, guild, channel, new_level, data):
        try:
            guild_id = str(guild.id)
            all_configs = load_json(CONFIG_FILE)
            config = all_configs.get(guild_id, {})
            level_roles = config.get("level_roles", {})
            
            role_id_str = level_roles.get(str(new_level))
            if role_id_str:
                role_id = int(role_id_str)
                role = guild.get_role(role_id)
                if role:
                    for lvl_str, r_id_str in level_roles.items():
                        lvl = int(lvl_str)
                        r_id = int(r_id_str)
                        if lvl < new_level and lvl != new_level:
                            prev_role = guild.get_role(r_id)
                            if prev_role and prev_role in member.roles:
                                await member.remove_roles(prev_role)
                    await member.add_roles(role)

            badge = LEVEL_BADGES.get(new_level)
            user_badges = data.get(str(member.id), {}).setdefault("badges", [])
            if badge and badge not in user_badges:
                user_badges.append(badge)
                all_level_data = load_json(LEVEL_FILE)
                all_level_data[guild_id] = data
                save_json(LEVEL_FILE, all_level_data)

            announce_channel_id = config.get("announce_channel")
            if announce_channel_id:
                announce_channel = guild.get_channel(announce_channel_id)
                if announce_channel:
                    embed = discord.Embed(
                        title="🎉 Level Up!",
                        description=f"{member.mention} telah mencapai level **{new_level}**!",
                        color=discord.Color.green()
                    )
                    await announce_channel.send(embed=embed)
        except Exception as e:
            print(f"Error in level_up: {e}")
            
    @commands.command(name="setannounce")
    @commands.has_permissions(administrator=True)
    async def set_announce_channel(self, ctx, channel: discord.TextChannel = None):
        if channel is None:
            channel = ctx.channel
        guild_id = str(ctx.guild.id)
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.setdefault(guild_id, {})
        config["announce_channel"] = channel.id
        save_json(CONFIG_FILE, all_configs)
        await ctx.send(f"✅ Channel pengumuman telah diatur ke {channel.mention}.")

    @commands.command(name="setlevelrole")
    @commands.has_permissions(administrator=True)
    async def set_level_role(self, ctx, level: int, role: discord.Role):
        if level <= 0:
            return await ctx.send("❌ Level harus lebih besar dari 0.")
        guild_id = str(ctx.guild.id)
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.setdefault(guild_id, {})
        if "level_roles" not in config:
            config["level_roles"] = {}
        config["level_roles"][str(level)] = role.id
        save_json(CONFIG_FILE, all_configs)
        await ctx.send(f"✅ Role {role.mention} akan diberikan saat mencapai **Level {level}**.")

    @commands.command(name="removelevelrole")
    @commands.has_permissions(administrator=True)
    async def remove_level_role(self, ctx, level: int):
        guild_id = str(ctx.guild.id)
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.get(guild_id, {})
        level_roles = config.get("level_roles", {})
        if str(level) in level_roles:
            del level_roles[str(level)]
            save_json(CONFIG_FILE, all_configs)
            await ctx.send(f"✅ Pengaturan role untuk **Level {level}** telah dihapus.")
        else:
            await ctx.send(f"❌ Tidak ada pengaturan role yang ditemukan untuk **Level {level}**.")

    @commands.command(name="viewlevelroles")
    @commands.has_permissions(administrator=True)
    async def view_level_roles(self, ctx):
        guild_id = str(ctx.guild.id)
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.get(guild_id, {})
        level_roles = config.get("level_roles", {})
        
        if not level_roles:
            return await ctx.send("ℹ️ Belum ada level role yang diatur di server ini.")
            
        embed = discord.Embed(title="Pengaturan Level Roles", color=discord.Color.blue())
        description = ""
        sorted_levels = sorted(level_roles.keys(), key=int)
        for level in sorted_levels:
            role_id = level_roles[level]
            role = ctx.guild.get_role(role_id)
            description += f"**Level {level}** ➜ {role.mention if role else f'ID Role: {role_id} (Tidak Ditemukan)'}\n"
        embed.description = description
        await ctx.send(embed=embed)

    @commands.command(name="uangall")
    @commands.has_permissions(administrator=True)
    async def give_all_money(self, ctx, amount: int):
        logging.info(f"Admin {ctx.author.display_name} initiating give_all_money: {amount} RSWN.")
        if amount <= 0:
            logging.warning("give_all_money amount is not positive.")
            return await ctx.send("Jumlah RSWN harus positif.", ephemeral=True)
        await ctx.defer()
        
        bank_data = load_json(BANK_FILE)
        updated_users_count = 0
        for member in ctx.guild.members:
            if member.bot: continue
            user_id_str = str(member.id)
            bank_data.setdefault(user_id_str, {"balance": 0, "debt": 0})["balance"] += amount
            updated_users_count += 1
        
        save_json(BANK_FILE, bank_data)
        logging.info(f"Successfully gave {amount} RSWN to {updated_users_count} users.")
        await ctx.send(f"✅ Berhasil memberikan **{amount} RSWN** kepada **{updated_users_count} anggota** di server ini!")

    @commands.command(name="xpall")
    @commands.has_permissions(administrator=True)
    async def give_all_xp(self, ctx, amount: int):
        logging.info(f"Admin {ctx.author.display_name} initiating give_all_xp: {amount} EXP.")
        if amount <= 0:
            logging.warning("give_all_xp amount is not positive.")
            return await ctx.send("Jumlah EXP harus positif.", ephemeral=True)
        await ctx.defer()
        
        guild_id_str = str(ctx.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        level_data = all_level_data.setdefault(guild_id_str, {})
        updated_users_count = 0

        for member in ctx.guild.members:
            if member.bot: continue
            user_id_str = str(member.id)
            user_level_data = level_data.setdefault(user_id_str, {
                "exp": 0, "level": 0, "weekly_exp": 0, "badges": [], "last_active": None, "booster": {}
            })
            
            old_level = user_level_data.get("level", 0)
            user_level_data["exp"] += amount
            user_level_data.setdefault("weekly_exp", 0)
            user_level_data["weekly_exp"] += amount
            user_level_data["last_active"] = datetime.utcnow().isoformat()
            
            new_level = calculate_level(user_level_data["exp"])
            if new_level > old_level:
                user_level_data["level"] = new_level
                logging.debug(f"User {member.display_name} leveled up from {old_level} to {new_level} due to give_all_xp.")
                await self.level_up(member, ctx.guild, ctx.channel, new_level, level_data)
            updated_users_count += 1
        
        all_level_data[guild_id_str] = level_data
        save_json(LEVEL_FILE, all_level_data)
        logging.info(f"Successfully gave {amount} EXP to {updated_users_count} users.")
        await ctx.send(f"✅ Berhasil memberikan **{amount} EXP** kepada **{updated_users_count} anggota** di server ini!")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def add_quest(self, ctx, description: str, reward_exp: int, reward_coins: int):
        if reward_exp < 0 or reward_coins < 0:
            return await ctx.send("❌ Reward harus bernilai positif!")
        quests_data = load_json(QUESTS_FILE)
        new_id = str(len(quests_data.get("quests", {})) + 1)
        quests_data.setdefault("quests", {})[new_id] = {
            "description": description, "reward_exp": reward_exp, "reward_coins": reward_coins
        }
        save_json(QUESTS_FILE, quests_data)
        await ctx.send(f"✅ Quest baru berhasil ditambahkan dengan ID `{new_id}`!")

    @commands.command()
    async def daily_quest(self, ctx):
        guild_id = str(ctx.guild.id)
        try:
            with open(f"data/daily_quest_{guild_id}.json", "r", encoding="utf-8") as f:
                daily_quest = json.load(f)
            await ctx.send(f"🎯 Quest Harian: {daily_quest['description']}")
        except FileNotFoundError:
            await ctx.send("❌ Belum ada quest harian yang ditentukan!")

    @commands.command()
    async def complete_quest(self, ctx):
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        daily_quest_file = f"data/daily_quest_{guild_id}.json"
        if not os.path.exists(daily_quest_file):
            return await ctx.send("❌ Belum ada quest harian yang ditentukan!")
        try:
            with open(daily_quest_file, "r") as f:
                daily_quest = json.load(f)
            
            all_level_data = load_json(LEVEL_FILE)
            data = all_level_data.setdefault(guild_id, {})
            
            if user_id not in data:
                data[user_id] = {"exp": 0, "level": 0, "weekly_exp": 0, "badges": [], "last_completed_quest": None}
            
            user_level_data = data[user_id]
            last_completed = user_level_data.get("last_completed_quest")
            if last_completed:
                last_completed_date = datetime.fromisoformat(last_completed)
                if last_completed_date.date() == datetime.utcnow().date():
                    return await ctx.send("❌ Kamu sudah menyelesaikan quest harian hari ini!")
            
            user_level_data["exp"] += daily_quest["reward_exp"]
            user_level_data["last_completed_quest"] = datetime.utcnow().isoformat()
            save_json(LEVEL_FILE, all_level_data)
            
            bank_data = load_json(BANK_FILE)
            if user_id not in bank_data:
                bank_data[user_id] = {"balance": 0, "debt": 0}
            bank_data[user_id]["balance"] += daily_quest["reward_coins"]
            save_json(BANK_FILE, bank_data)
            
            await ctx.send(f"✅ Kamu telah menyelesaikan quest harian! Reward: {daily_quest['reward_exp']} EXP dan {daily_quest['reward_coins']} 🪙RSWN.")
        except json.JSONDecodeError:
            await ctx.send("❌ Terjadi kesalahan saat membaca quest harian.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {str(e)}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def giveexp(self, ctx, member: discord.Member, amount: int):
        if ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.message.delete()
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.setdefault(guild_id, {})
        now = datetime.utcnow().isoformat()
        
        user_level_data = data.setdefault(user_id, {"exp": 0, "level": 0, "last_active": now, "weekly_exp": 0, "badges": []})
        user_level_data["exp"] += amount
        user_level_data.setdefault("weekly_exp", 0)
        user_level_data["weekly_exp"] += amount
        user_level_data["last_active"] = now
        
        old_level = user_level_data.get("level", 0)
        new_level = calculate_level(user_level_data["exp"])
        
        if new_level > old_level:
            user_level_data["level"] = new_level
            save_json(LEVEL_FILE, all_level_data)
            await self.level_up(member, ctx.guild, ctx.channel, new_level, data)
        else:
            save_json(LEVEL_FILE, all_level_data)
            
        try:
            await member.send(f"🎁 Kamu telah menerima **{amount} EXP gratis** dari {ctx.author.mention}!")
        except discord.Forbidden:
            pass
        await ctx.author.send(f"✅ Kamu telah memberikan **{amount} EXP** ke {member.mention} secara rahasia.", delete_after=10)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def givecoins(self, ctx, member: discord.Member, amount: int):
        if ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.message.delete()
        bank_data = load_json(BANK_FILE)
        user_id = str(member.id)
        if user_id not in bank_data:
            bank_data[user_id] = {"balance": 0, "debt": 0}
        bank_data[user_id]["balance"] += amount
        save_json(BANK_FILE, bank_data)
        try:
            await member.send(f"🎉 Kamu telah menerima **{amount} 🪙RSWN gratis** dari admin {ctx.author.mention}!")
        except discord.Forbidden:
            pass
        await ctx.author.send(f"✅ Kamu telah memberikan **{amount} 🪙RSWN gratis** ke {member.mention}.", delete_after=10)

    @commands.command()
    async def transfercoins(self, ctx, member: discord.Member, amount: int):
        if ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.message.delete()
        bank_data = load_json(BANK_FILE)
        sender_id = str(ctx.author.id)
        receiver_id = str(member.id)
        if sender_id not in bank_data or bank_data[sender_id].get("balance", 0) < amount:
            return await ctx.author.send("❌ Saldo tidak cukup!", delete_after=10)
        if amount <= 0:
            return await ctx.author.send("❌ Jumlah transfer harus positif!", delete_after=10)
        if receiver_id not in bank_data:
            bank_data[receiver_id] = {"balance": 0, "debt": 0}
        bank_data[sender_id]["balance"] -= amount
        bank_data[receiver_id]["balance"] += amount
        save_json(BANK_FILE, bank_data)
        try:
            await member.send(f"🎉 Kamu telah menerima **{amount} 🪙RSWN** dari {ctx.author.mention}!")
        except discord.Forbidden:
            pass
        await ctx.author.send(f"✅ Kamu telah memberikan **{amount} 🪙RSWN** ke {member.mention}.", delete_after=10)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setlevel(self, ctx, member: discord.Member, level: int):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.setdefault(guild_id, {})
        user_level_data = data.setdefault(user_id, {"exp": 0, "level": 0, "weekly_exp": 0, "badges": []})
        user_level_data["exp"] = level * 3500
        user_level_data["level"] = level
        save_json(LEVEL_FILE, all_level_data)
        await ctx.send(f"✅ Level {member.mention} telah diset menjadi **{level}**!")

    @commands.command()
    async def leaderboard(self, ctx):
        guild_id = str(ctx.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        if not data:
            return await ctx.send("Belum ada data EXP di server ini.")
        sorted_users = sorted(data.items(), key=lambda x: x[1].get('exp', 0), reverse=True)
        embed = discord.Embed(title="🏆 Leaderboard EXP", color=discord.Color.gold())
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        for idx, (user_id, user_data) in enumerate(sorted_users[:10], start=1):
            user = ctx.guild.get_member(int(user_id))
            if user:
                badges = " ".join(user_data.get("badges", [])) or "Tidak ada"
                embed.add_field(name=f"{idx}. {user.display_name}", 
                                value=f"**Level:** {user_data.get('level', 0)} | **EXP:** {user_data.get('exp', 0)}\n**Badges:** {badges}", 
                                inline=False)
        await ctx.send(embed=embed)

    @commands.command()
    async def weekly(self, ctx):
        guild_id = str(ctx.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        if not data:
            return await ctx.send("Belum ada data EXP di server ini.")
        valid_users = {uid: udata for uid, udata in data.items() if ctx.guild.get_member(int(uid))}
        sorted_users = sorted(valid_users.items(), key=lambda x: x[1].get('weekly_exp', 0), reverse=True)
        embed = discord.Embed(title="🏅 Weekly Leaderboard", color=discord.Color.blue())
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        for idx, (user_id, user_data) in enumerate(sorted_users[:10], start=1):
            user = ctx.guild.get_member(int(user_id))
            if user:
                embed.add_field(name=f"{idx}. {user.display_name}", 
                                value=f"**Weekly EXP:** {user_data.get('weekly_exp', 0)}", 
                                inline=False)
        await ctx.send(embed=embed)
        
    @commands.command()
    async def rank(self, ctx):
        user_id = str(ctx.author.id)
        guild_id = str(ctx.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        bank = load_json(BANK_FILE)
        
        user_data = data.get(user_id, {"level": 0, "exp": 0})
        user_bank = bank.get(user_id, {"balance": 0})
        
        avatar_file = discord.File(await crop_avatar_to_circle(ctx.author), "avatar.png")
        embed = discord.Embed(title=f"📊 Rank {ctx.author.display_name}", color=discord.Color.purple())
        embed.set_thumbnail(url="attachment://avatar.png")
        embed.add_field(name="Level", value=user_data.get('level', 0), inline=True)
        embed.add_field(name="Saldo", value=f"{user_bank.get('balance', 0)} 🪙RSWN", inline=True)
        embed.add_field(name="Total EXP", value=user_data.get('exp', 0), inline=True)
        await ctx.send(file=avatar_file, embed=embed)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def reduce_user(self, ctx, member: discord.Member, exp: int, rswn: int, *, reason: str):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        await ctx.message.delete()
        
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        bank_data = load_json(BANK_FILE)
        
        if user_id not in data:
            return await ctx.send("❌ Pengguna tidak ditemukan dalam data!", delete_after=10)
        if data[user_id].get("exp", 0) < exp:
            return await ctx.send("❌ Pengguna tidak memiliki cukup EXP untuk dikurangi!", delete_after=10)
        if user_id not in bank_data or bank_data[user_id].get("balance", 0) < rswn:
            return await ctx.send("❌ Pengguna tidak memiliki cukup RSWN untuk dikurangi!", delete_after=10)
        
        data[user_id]["exp"] -= exp
        bank_data[user_id]["balance"] -= rswn
        data[user_id]["level"] = calculate_level(data[user_id]["exp"])
        
        save_json(LEVEL_FILE, all_level_data)
        save_json(BANK_FILE, bank_data)
        await ctx.send(f"✅ {member.mention} telah dikurangi **{exp} EXP** dan **{rswn} RSWN**! Alasan: *{reason}*")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def resetall(self, ctx):
        guild_id = str(ctx.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        if not data:
            return await ctx.send("ℹ️ Tidak ada data untuk direset.")

        for user_id in data.keys():
            data[user_id]["exp"] = 0
            data[user_id]["weekly_exp"] = 0
            data[user_id]["level"] = 0
            data[user_id]["badges"] = []
        save_json(LEVEL_FILE, all_level_data)
        await ctx.send("✅ Semua data EXP, Level, dan Badge pengguna di server ini telah direset!")

    # --- METHODS FROM ITEMMANAGE COG ---
    @commands.command()
    async def manageitems(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("❌ Kamu tidak punya izin untuk melakukan ini.")
        
        with open(SHOP_FILE, 'r') as f:
            data = json.load(f)
        
        if not data:
            return await ctx.send("📭 Tidak ada item di shop.")
        
        view = CategoryDropdownView(self.bot, list(data.keys()))
        await ctx.send("📂 Pilih kategori item yang ingin kamu kelola:", view=view)
    
    # --- METHODS FROM SHOP COG ---
    @commands.command(name="shop")
    async def shop(self, ctx):
        status = load_json(SHOP_STATUS_FILE)
        if not status.get("is_open", True):
            return await ctx.send("⚠️ Toko sedang *ditutup* oleh admin. Silakan kembali lagi nanti.", ephemeral=True)

        self.shop_data = load_json(SHOP_FILE)
        self.collage_url = load_json(COLLAGE_FILE).get("collage_url")

        embed = discord.Embed(
            title="💎 reSwan Shop",
            description="Pilih kategori di bawah untuk melihat item yang tersedia.",
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Gunakan dropdown untuk melihat item.")

        if self.collage_url:
            embed.set_image(url=self.collage_url)
        
        view = ShopCategoryView(self.bot, self.shop_data, ctx.author.id, ctx.guild.id)
        
        try:
            await ctx.message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
        
        await ctx.send(embed=embed, view=view)

    @commands.command(name="toggleshop")
    @commands.has_permissions(administrator=True)
    async def toggle_shop(self, ctx):
        status = load_json(SHOP_STATUS_FILE)
        status["is_open"] = not status.get("is_open", True)
        save_json(SHOP_STATUS_FILE, status)
        state = "🟢 TERBUKA" if status["is_open"] else "🔴 TERTUTUP"
        await ctx.send(f"Toko sekarang telah diatur ke: **{state}**")

    @commands.command(name="toggleexpshop")
    @commands.has_permissions(administrator=True)
    async def toggle_exp_shop(self, ctx):
        status = load_json(SHOP_STATUS_FILE)
        status["exp_shop_open"] = not status.get("exp_shop_open", True)
        save_json(SHOP_STATUS_FILE, status)
        state = "🟢 TERBUKA" if status["exp_shop_open"] else "🔴 TERTUTUP"
        await ctx.send(f"Toko pembelian EXP sekarang telah diatur ke: **{state}**")

    @commands.command(name="additem")
    @commands.has_permissions(administrator=True)
    async def add_item(self, ctx, category: str, name: str, price: int, description: str, *args):
        shop_data = load_json(SHOP_FILE)
        valid_categories = ["badges", "exp", "roles", "special_items"]
        category_lower = category.lower()

        if category_lower not in valid_categories:
            await ctx.send(f"⚠️ Kategori tidak valid. Gunakan: `{', '.join(valid_categories)}`.", ephemeral=True)
            return

        if category_lower not in shop_data:
            shop_data[category_lower] = []
        
        emoji_or_type = args[0] if len(args) > 0 else None
        stock_str = args[1] if len(args) > 1 else "unlimited"
        remaining_args = args[2:] 

        item = {
            "name": name,
            "price": price,
            "description": description,
            "stock": int(stock_str) if stock_str.lower() != "unlimited" else "unlimited"
        }

        if category_lower == "roles":
            if not remaining_args:
                return await ctx.send("⚠️ Untuk kategori 'roles', harap masukkan `[role_id]` sebagai argumen terakhir.", ephemeral=True)
            item["role_id"] = int(remaining_args[0])
            item["emoji"] = emoji_or_type or "👑"
        elif category_lower == "badges":
            item["emoji"] = emoji_or_type or "🎭"
            if remaining_args:
                item["image_url"] = remaining_args[0]
        elif category_lower == "exp":
            if len(remaining_args) < 2:
                return await ctx.send("⚠️ Untuk kategori 'exp' (booster), Anda harus menyediakan: `[multiplier]` dan `[duration_minutes]` setelah deskripsi dan stok.", ephemeral=True)
            try:
                item["multiplier"] = int(remaining_args[0])
                item["duration_minutes"] = int(remaining_args[1])
            except ValueError:
                return await ctx.send("⚠️ Untuk kategori 'exp' (booster), multiplier dan durasi (menit) harus angka.", ephemeral=True)
            item["type"] = "exp_booster"
            item["emoji"] = emoji_or_type or "🚀"
        elif category_lower == "special_items":
            item_type = emoji_or_type
            if not item_type:
                return await ctx.send("⚠️ Untuk kategori 'special_items', harap masukkan `[type_item]` (misal: `protection_shield`, `gacha_medicine_box`) sebagai argumen pertama setelah deskripsi dan stok.", ephemeral=True)
            item["type"] = item_type
            if item_type == "protection_shield":
                item["emoji"] = "🛡️"
            elif item_type == "gacha_medicine_box":
                item["emoji"] = "💊"
            else:
                item["emoji"] = "📦"

        item_exists = False
        for i, existing_item in enumerate(shop_data.get(category_lower, [])):
            if existing_item['name'] == name:
                shop_data[category_lower][i] = item
                item_exists = True
                break
        
        if not item_exists:
            shop_data[category_lower].append(item)

        save_json(SHOP_FILE, shop_data)
        await ctx.send(f"✅ Item baru/diperbarui di kategori **{category_lower}**: **{name}** seharga **{price}** RSWN! 🎉")

    @commands.command(name="addcollage")
    @commands.has_permissions(administrator=True)
    async def add_collage(self, ctx, url: str):
        if not url.startswith("http://") and not url.startswith("https://"):
            return await ctx.send("❌ URL gambar tidak valid. Harus dimulai dengan `http://` atau `https://`.", ephemeral=True)
        
        save_json(COLLAGE_FILE, {"collage_url": url})
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

# --- BOT SETUP ---
async def setup(bot):
    await bot.add_cog(Leveling(bot))

