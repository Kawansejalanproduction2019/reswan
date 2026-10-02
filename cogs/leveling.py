import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import random
import logging
from pilmoji import Pilmoji
import asyncio
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
import time
from io import BytesIO
import io
import aiohttp
import unicodedata

try:
    from cogs.v2_layout import build_v2_card, send_v2_message, edit_v2_message
except ImportError:
    build_v2_card = None
    send_v2_message = None
    edit_v2_message = None

LEVEL_FILE = "data/level_data.json"
BANK_FILE = "data/bank_data.json"
SHOP_FILE = "data/shop_items.json"
QUESTS_FILE = "data/quests.json"
CONFIG_FILE = "data/config.json"
SHOP_STATUS_FILE = "data/shop_status.json"
COLLAGE_FILE = "data/shop_collage.json"
INVENTORY_FILE = "data/inventory.json"

WEEKLY_RESET_DAY = 0
EXP_PRICE_PER_UNIT = 10
DAILY_EXP_LIMIT = 1500

_memory_cache = {}
_font_bold_bytes = None
_font_reg_bytes = None

def load_json(path):
    if path in _memory_cache:
        return _memory_cache[path]
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
        
        temp_path = f"{path}.tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, indent=4)
        os.replace(temp_path, path)
        _memory_cache[path] = default_data
        return default_data

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            _memory_cache[path] = data
            return data
    except (json.JSONDecodeError, FileNotFoundError):
        _memory_cache[path] = {}
        return {}

def save_json(path, data):
    _memory_cache[path] = data
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    os.replace(temp_path, path)

def calculate_new_level(exp, exp_per_level, max_level):
    lvl = exp // exp_per_level
    if max_level > 0 and lvl > max_level:
        return max_level
    return lvl

def format_voice_duration(seconds: int) -> str:
    """Format durasi detik ke format teks manusia (Hari, Jam, Menit, Detik)."""
    if seconds <= 0:
        return "0 Menit"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days} Hari")
    if hours > 0:
        parts.append(f"{hours} Jam")
    if minutes > 0:
        parts.append(f"{minutes} Menit")
    if not parts:
        parts.append(f"{secs} Detik")
    return " ".join(parts)

async def crop_avatar_to_circle(user: discord.User):
    async with aiohttp.ClientSession() as session:
        async with session.get(user.display_avatar.url) as resp:
            avatar_bytes = await resp.read()

    def _crop():
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

    return await asyncio.to_thread(_crop)

class ConfigRatesModal(discord.ui.Modal, title="Konfigurasi Rate Server"):
    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = str(guild_id)
        all_configs = load_json(CONFIG_FILE)
        guild_config = all_configs.get(self.guild_id, {})
        
        self.exp_msg = discord.ui.TextInput(label="EXP per Pesan Teks", default=str(guild_config.get("exp_per_msg", 10)), required=True)
        self.rswn_msg = discord.ui.TextInput(label="RSWN per Pesan Teks", default=str(guild_config.get("rswn_per_msg", 1)), required=True)
        self.exp_vc = discord.ui.TextInput(label="EXP per Menit VC", default=str(guild_config.get("exp_per_vc_min", 5)), required=True)
        self.rswn_vc = discord.ui.TextInput(label="RSWN per Menit VC", default=str(guild_config.get("rswn_per_vc_min", 10)), required=True)
        
        self.add_item(self.exp_msg)
        self.add_item(self.rswn_msg)
        self.add_item(self.exp_vc)
        self.add_item(self.rswn_vc)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            exp_msg_val = int(self.exp_msg.value)
            rswn_msg_val = int(self.rswn_msg.value)
            exp_vc_val = int(self.exp_vc.value)
            rswn_vc_val = int(self.rswn_vc.value)
        except ValueError:
            return await interaction.response.send_message("Semua nilai harus berupa angka!", ephemeral=True)
            
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.setdefault(self.guild_id, {})
        config["exp_per_msg"] = exp_msg_val
        config["rswn_per_msg"] = rswn_msg_val
        config["exp_per_vc_min"] = exp_vc_val
        config["rswn_per_vc_min"] = rswn_vc_val
        save_json(CONFIG_FILE, all_configs)
        
        embed = discord.Embed(title="Konfigurasi Rate Diperbarui", color=discord.Color.green())
        embed.add_field(name="Pesan Teks", value=f"EXP: {exp_msg_val}\nRSWN: {rswn_msg_val}", inline=True)
        embed.add_field(name="Voice Chat", value=f"EXP: {exp_vc_val}\nRSWN: {rswn_vc_val}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ConfigRatesButton(discord.ui.Button):
    def __init__(self, guild_id):
        super().__init__(label="Atur Konfigurasi Rate", style=discord.ButtonStyle.primary, emoji="⚙️")
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ConfigRatesModal(self.guild_id))

class ConfigRatesView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=120)
        self.add_item(ConfigRatesButton(guild_id))

class EXPInputModal(discord.ui.Modal, title="Beli EXP Langsung"):
    def __init__(self, user_id, guild_id):
        super().__init__()
        self.user_id = str(user_id)
        self.guild_id = str(guild_id)
        self.exp_amount_input = discord.ui.TextInput(
            label="Berapa EXP yang ingin kamu beli?",
            placeholder=f"Maksimal {DAILY_EXP_LIMIT} EXP per hari.",
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
        all_configs = load_json(CONFIG_FILE)
        guild_config = all_configs.get(self.guild_id, {})
        
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
                f"❌ Kamu hanya bisa membeli maksimal **{DAILY_EXP_LIMIT} EXP** per hari. Sisa limit: **{remaining_limit} EXP**.",
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
        user_data.setdefault('weekly_exp', 0)
        user_data.setdefault('last_active', datetime.utcnow().isoformat())
        
        exp_per_level = guild_config.get("exp_per_level", 3500)
        max_level = guild_config.get("max_level", 0)
        new_level = calculate_new_level(user_data["exp"], exp_per_level, max_level)
        
        save_json(LEVEL_FILE, level_data)
        save_json(BANK_FILE, bank_data)
        await interaction.response.send_message(f"✅ Berhasil membeli **{amount_to_buy} EXP** seharga **{total_cost} RSWN**!", ephemeral=True)
        
        if new_level > user_data.get('level', 0):
            user_data['level'] = new_level
            save_json(LEVEL_FILE, level_data)
            cog = interaction.client.get_cog("Progression & Economy")
            member = interaction.guild.get_member(int(self.user_id))
            if cog and member:
                await cog.level_up(member, interaction.guild, interaction.channel, new_level, level_data.get(self.guild_id))

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
                                await interaction.user.send(content="Pembelian berhasil. Ini file avatarnya:", file=file)
                except Exception:
                    pass
            message_to_send = f"✅ Kamu berhasil membeli badge `{item['name']}` seharga **{item['price']} RSWN**!"
            purchase_successful = True
        elif self.category == "roles":
            user_data.setdefault("purchased_roles", []).append(item['name'])
            role_id = item.get("role_id")
            if role_id:
                role = interaction.guild.get_role(int(role_id))
                if role:
                    try:
                        await interaction.user.add_roles(role)
                        message_to_send = f"✅ Role `{item['name']}` berhasil diberikan!"
                    except discord.Forbidden:
                        message_to_send = f"✅ Role `{item['name']}` dibeli tapi izin bot tidak cukup untuk memberikannya."
                    except Exception as e:
                        message_to_send = f"✅ Role `{item['name']}` dibeli, namun terjadi error: {e}"
                else:
                    message_to_send = f"✅ Role `{item['name']}` dibeli, namun ID role tidak valid."
            purchase_successful = True
        elif self.category == "exp":
            user_data.setdefault("booster", {})["exp_multiplier"] = item.get("multiplier", 2)
            user_data["booster"]["expires_at"] = (datetime.utcnow() + timedelta(minutes=item.get("duration_minutes", 30))).isoformat()
            message_to_send = f"✅ Berhasil membeli booster EXP `{item['name']}`."
            purchase_successful = True
        elif self.category == "special_items":
            item_type = item.get('type')
            inventory_item_to_add = {"name": item['name'], "type": item_type}
            inventory_user.append(inventory_item_to_add)
            purchase_successful = True
            message_to_send = f"✅ Berhasil membeli item: `{item['name']}`."

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
            await interaction.response.send_message("Terjadi kesalahan saat pembelian.", ephemeral=True)

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
            description="Pilih item booster EXP di bawah.",
            color=discord.Color.blue()
        )
        for item in exp_boosters:
            stock_str = "∞" if item.get("stock", "unlimited") == "unlimited" else str(item["stock"])
            field_name = f"{item.get('emoji', '🔸')} {item['name']} — 💰{item['price']} | Stok: {stock_str}"
            embed.add_field(name=field_name, value=item.get('description', ''), inline=False)
        
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
        embed = discord.Embed(title="⚡ Toko EXP", color=discord.Color.gold())
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
            discord.SelectOption(label="🎭 Badges", value="badges"),
            discord.SelectOption(label="⚡ EXP", value="exp"),
            discord.SelectOption(label="👑 Roles", value="roles"),
            discord.SelectOption(label="🛡️ Bertahan Hidup", value="special_items")
        ]
        super().__init__(placeholder="Pilih kategori item", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        shop_status = load_json(SHOP_STATUS_FILE)
        
        if not shop_status.get("exp_shop_open", True) and category == "exp":
            embed = discord.Embed(title="⚡ Toko EXP", description="❌ Ditutup.", color=discord.Color.red())
            view = discord.ui.View(timeout=60)
            view.add_item(BackToCategoryButton(self.shop_data, self.user_id, self.guild_id))
            await interaction.response.edit_message(embed=embed, view=view)
            return

        if category == "exp":
            embed = discord.Embed(title="⚡ Toko EXP", color=discord.Color.gold())
            view = discord.ui.View(timeout=60)
            view.add_item(BuyEXPButton(self.user_id, self.guild_id))
            view.add_item(BuyEXPBoosterButton(self.shop_data, self.user_id, self.guild_id))
            view.add_item(BackToCategoryButton(self.shop_data, self.user_id, self.guild_id))
            await interaction.response.edit_message(embed=embed, view=view)
            return

        items = self.shop_data.get(category, [])
        embed = discord.Embed(title=f"🛍️ {category.title()} Shop", color=discord.Color.orange())
        if not items:
            embed.description = "Tidak ada item."
        else:
            for item in items:
                stock_str = "∞" if item.get("stock", "unlimited") == "unlimited" else str(item["stock"])
                name = item['name']
                price = item['price']
                field_name = f"{item.get('emoji', '🔸')} {name} — 💰{price} | Stok: {stock_str}"
                embed.add_field(name=field_name, value=item.get('description', ''), inline=False)

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

        embed = discord.Embed(title="💎 reSwan Shop", color=discord.Color.blurple())
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
        await interaction.response.edit_message(content=f"📦 Kategori: **{self.values[0]}**", view=ItemSelectionView(self.bot, self.values[0]))

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
                value=str(i)
            ))
        super().__init__(placeholder="Pilih item...", options=options)

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])
        await interaction.response.edit_message(
            content=f"🔧 Kelola item dari kategori **{self.category}**:",
            view=ItemActionView(self.bot, self.category, index)
        )

class EditItemButton(discord.ui.Button):
    def __init__(self, bot, category, index):
        super().__init__(label="Edit", style=discord.ButtonStyle.primary)
        self.bot = bot
        self.category = category
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditItemModal(self.bot, self.category, self.index))

class RestockItemButton(discord.ui.Button):
    def __init__(self, bot, category, index):
        super().__init__(label="Restock", style=discord.ButtonStyle.secondary)
        self.bot = bot
        self.category = category
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RestockModal(self.category, self.index))

class DeleteItemButton(discord.ui.Button):
    def __init__(self, bot, category, index):
        super().__init__(label="Hapus", style=discord.ButtonStyle.danger)
        self.category = category
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        with open(SHOP_FILE, 'r') as f:
            data = json.load(f)
        item_name = data[self.category][self.index]["name"]
        data[self.category].pop(self.index)
        with open(SHOP_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        await interaction.response.edit_message(content=f"🗑️ Item **{item_name}** dihapus.", view=None)

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
        self.emoji = discord.ui.TextInput(label="Emoji Baru", required=False)
        self.price = discord.ui.TextInput(label="Harga Baru", required=True)
        self.image_url = discord.ui.TextInput(label="Image URL", required=False)
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
        await interaction.response.send_message("✅ Item diperbarui.", ephemeral=True)

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
        await interaction.response.send_message("📦 Stok diperbarui.", ephemeral=True)
        
class GiveawayJoinView(discord.ui.View):
    def __init__(self, bot, message_id, min_level, min_messages, req_role_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.message_id = message_id
        self.min_level = min_level
        self.min_messages = min_messages
        self.req_role_id = req_role_id
        self.participants = []

    @discord.ui.button(label="Ikut Giveaway 🎉", style=discord.ButtonStyle.success, custom_id="giveaway_join_btn")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        user_data = all_level_data.get(guild_id, {}).get(user_id, {})

        if user_data.get("level", 0) < self.min_level:
            return await interaction.response.send_message(f"Level kamu belum cukup! Minimal level {self.min_level}.", ephemeral=True)

        if user_data.get("msg_count", 0) < self.min_messages:
            return await interaction.response.send_message(f"Total interaksi pesanmu kurang! Minimal {self.min_messages} pesan.", ephemeral=True)

        if self.req_role_id:
            role = interaction.guild.get_role(self.req_role_id)
            if role not in interaction.user.roles:
                return await interaction.response.send_message(f"Kamu harus memiliki role {role.mention} untuk ikut.", ephemeral=True)

        if interaction.user.id in self.participants:
            return await interaction.response.send_message("Kamu sudah terdaftar di giveaway ini!", ephemeral=True)

        self.participants.append(interaction.user.id)
        await interaction.response.send_message("Berhasil terdaftar ke dalam giveaway!", ephemeral=True)


class ProgressionSystem(commands.Cog, name="Progression & Economy"):
    def __init__(self, bot):
        self.bot = bot
        self.giveaways = {}
        self._voice_panel_locks = {}
        self.voice_task = self.create_voice_task()
        self.last_reset = datetime.utcnow()
        self._dirty_level = False
        self._dirty_bank = False
        self.daily_quest_task.start()
        self.voice_task.start()
        self.flush_buffer_task.start()
        self.shop_data = load_json(SHOP_FILE)
        self.collage_url = load_json(COLLAGE_FILE).get("collage_url")

    def cog_unload(self):
        self.daily_quest_task.cancel()
        self.voice_task.cancel()
        self.flush_buffer_task.cancel()
        if getattr(self, '_dirty_level', False):
            level_data = _memory_cache.get(LEVEL_FILE)
            if level_data:
                save_json(LEVEL_FILE, level_data)
        if getattr(self, '_dirty_bank', False):
            bank_data = _memory_cache.get(BANK_FILE)
            if bank_data:
                save_json(BANK_FILE, bank_data)

    @tasks.loop(seconds=30)
    async def flush_buffer_task(self):
        mongo_client = getattr(self.bot, 'mongo_client', None)
        if getattr(self, '_dirty_level', False):
            level_data = _memory_cache.get(LEVEL_FILE)
            if level_data:
                save_json(LEVEL_FILE, level_data)
                if mongo_client:
                    try:
                        def _sync_level():
                            mongo_client.get_database("rtmbot")["level_data"].replace_one(
                                {"_id": "global_levels"},
                                {"_id": "global_levels", "data": level_data, "updated_at": time.time()},
                                upsert=True
                            )
                        await asyncio.to_thread(_sync_level)
                    except Exception:
                        pass
            self._dirty_level = False
        if getattr(self, '_dirty_bank', False):
            bank_data = _memory_cache.get(BANK_FILE)
            if bank_data:
                save_json(BANK_FILE, bank_data)
                if mongo_client:
                    try:
                        def _sync_bank():
                            mongo_client.get_database("rtmbot")["bank_data"].replace_one(
                                {"_id": "global_banks"},
                                {"_id": "global_banks", "data": bank_data, "updated_at": time.time()},
                                upsert=True
                            )
                        await asyncio.to_thread(_sync_bank)
                    except Exception:
                        pass
            self._dirty_bank = False

    def get_anomaly_multiplier(self):
        try:
            dunia_cog = self.bot.get_cog('DuniaHidup')
            if dunia_cog and hasattr(dunia_cog, 'active_anomaly') and isinstance(dunia_cog.active_anomaly, dict):
                if dunia_cog.active_anomaly.get('type') == 'exp_boost':
                    return dunia_cog.active_anomaly.get('effect', {}).get('multiplier', 1)
        except Exception:
            pass
        return 1

    async def create_rank_image(self, target, level, exp, balance, guild, rank_pos, badges):
        guild_id = str(guild.id)
        all_configs = load_json(CONFIG_FILE)
        guild_config = all_configs.get(guild_id, {})
        exp_per_level = guild_config.get("exp_per_level", 3500)
        max_level = guild_config.get("max_level", 0)

        level_badges = guild_config.get("level_badges", {})
        earned_badge = ""
        for lvl_str in sorted(level_badges.keys(), key=int, reverse=True):
            if level >= int(lvl_str):
                earned_badge = level_badges[lvl_str]
                break

        display_badges = list(badges)
        if earned_badge and earned_badge not in display_badges:
            display_badges.insert(0, earned_badge)
        
        badges_str = " ".join(display_badges) if display_badges else "Pemula"

        if max_level > 0 and level >= max_level:
            progress_ratio = 1.0
            display_text = "MAX LEVEL"
        else:
            next_level_exp = (level + 1) * exp_per_level
            current_level_base_exp = level * exp_per_level
            exp_progress = exp - current_level_base_exp
            exp_needed = exp_per_level
            progress_ratio = min(exp_progress / exp_needed, 1.0)
            display_text = f"{exp} / {next_level_exp} EXP"

        avatar_bytes = await target.display_avatar.replace(size=256, format="png").read()
        g_icon_bytes = None
        if guild.icon:
            try:
                g_icon_bytes = await guild.icon.replace(size=64, format="png").read()
            except Exception:
                pass
        bot_avatar_bytes = None
        try:
            bot_avatar_bytes = await self.bot.user.display_avatar.replace(size=64, format="png").read()
        except Exception:
            pass

        global _font_bold_bytes, _font_reg_bytes
        if not _font_bold_bytes or not _font_reg_bytes:
            try:
                url_bold = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf"
                url_reg = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf"
                async with aiohttp.ClientSession() as session:
                    if not _font_bold_bytes:
                        async with session.get(url_bold) as resp_b:
                            if resp_b.status == 200:
                                _font_bold_bytes = await resp_b.read()
                    if not _font_reg_bytes:
                        async with session.get(url_reg) as resp_r:
                            if resp_r.status == 200:
                                _font_reg_bytes = await resp_r.read()
            except Exception:
                pass

        def _render_card():
            width = 1000
            height = 330
            background = Image.new('RGBA', (width, height), (20, 22, 25, 255))
            draw = ImageDraw.Draw(background)

            draw.polygon([(0, 0), (1000, 0), (1000, 330), (0, 330)], fill=(15, 15, 20, 255))
            draw.polygon([(0, 330), (320, 330), (450, 0), (0, 0)], fill=(30, 35, 45, 255))
            draw.line((448, 0, 318, 330), fill=(0, 255, 200, 255), width=6)

            draw.ellipse((40, 55, 260, 275), outline=(0, 255, 200, 180), width=4)
            draw.ellipse((25, 40, 275, 290), outline=(255, 255, 255, 40), width=1)
            draw.line((150, 10, 150, 45), fill=(0, 255, 200, 255), width=3)
            draw.line((150, 285, 150, 320), fill=(0, 255, 200, 255), width=3)
            draw.line((5, 165, 40, 165), fill=(0, 255, 200, 255), width=3)
            draw.line((260, 165, 295, 165), fill=(0, 255, 200, 255), width=3)

            avatar_img = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((200, 200))
            mask = Image.new("L", (200, 200), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0, 200, 200), fill=255)
            background.paste(avatar_img, (50, 65), mask)

            try:
                if _font_bold_bytes and _font_reg_bytes:
                    font_title = ImageFont.truetype(BytesIO(_font_bold_bytes), 45)
                    font_rank = ImageFont.truetype(BytesIO(_font_bold_bytes), 65)
                    font_subtitle = ImageFont.truetype(BytesIO(_font_bold_bytes), 35)
                    font_text = ImageFont.truetype(BytesIO(_font_reg_bytes), 22)
                    font_small = ImageFont.truetype(BytesIO(_font_reg_bytes), 18)
                else:
                    font_title = font_rank = font_subtitle = font_text = font_small = ImageFont.load_default()
            except Exception:
                font_title = font_rank = font_subtitle = font_text = font_small = ImageFont.load_default()

            safe_guild_name = unicodedata.normalize('NFKC', guild.name)
            safe_target_name = unicodedata.normalize('NFKC', target.display_name)

            if g_icon_bytes:
                try:
                    g_img = Image.open(BytesIO(g_icon_bytes)).convert("RGBA").resize((35, 35))
                    g_mask = Image.new("L", (35, 35), 0)
                    ImageDraw.Draw(g_mask).ellipse((0, 0, 35, 35), fill=255)
                    background.paste(g_img, (480, 45), g_mask)
                    draw.text((525, 50), f"{safe_guild_name}", font=font_small, fill=(180, 180, 180, 255))
                except Exception:
                    draw.text((480, 50), f"Server: {safe_guild_name}", font=font_small, fill=(180, 180, 180, 255))
            else:
                draw.text((480, 50), f"Server: {safe_guild_name}", font=font_small, fill=(180, 180, 180, 255))

            draw.text((480, 85), f"{safe_target_name}", font=font_title, fill=(255, 255, 255, 255))
            draw.text((480, 145), f"Level {level}", font=font_subtitle, fill=(0, 255, 200, 255))
            draw.text((650, 155), f"|  Saldo: {balance} RSWN", font=font_text, fill=(255, 215, 0, 255))

            with Pilmoji(background) as pilmoji:
                pilmoji.text((480, 195), f"Badges: {badges_str}", font=font_text, fill=(200, 200, 200, 255))

            draw.text((950, 80), f"#{rank_pos}", font=font_rank, fill=(255, 215, 0, 255), anchor="ra")

            bar_x1, bar_y1, bar_x2, bar_y2 = 480, 235, 950, 260
            draw.rounded_rectangle([(bar_x1, bar_y1), (bar_x2, bar_y2)], radius=12, fill=(40, 45, 55, 255))

            if progress_ratio > 0:
                current_bar_x2 = bar_x1 + (bar_x2 - bar_x1) * progress_ratio
                if current_bar_x2 < bar_x1 + 24:
                    current_bar_x2 = bar_x1 + 24
                draw.rounded_rectangle([(bar_x1, bar_y1), (current_bar_x2, bar_y2)], radius=12, fill=(0, 255, 200, 255))

            draw.text((950, 210), display_text, font=font_small, fill=(185, 187, 190, 255), anchor="ra")

            if bot_avatar_bytes:
                try:
                    bot_img = Image.open(BytesIO(bot_avatar_bytes)).convert("RGBA").resize((25, 25))
                    bot_mask = Image.new("L", (25, 25), 0)
                    ImageDraw.Draw(bot_mask).ellipse((0, 0, 25, 25), fill=255)
                    background.paste(bot_img, (740, 285), bot_mask)
                    draw.text((775, 288), f"© {self.bot.user.name} Leveling System", font=font_small, fill=(100, 100, 100, 255))
                except Exception:
                    draw.text((775, 288), f"© {self.bot.user.name} Leveling System", font=font_small, fill=(100, 100, 100, 255))
            else:
                draw.text((775, 288), f"© {self.bot.user.name} Leveling System", font=font_small, fill=(100, 100, 100, 255))

            buffer = BytesIO()
            background.save(buffer, format="PNG")
            buffer.seek(0)
            return buffer

        buffer = await asyncio.to_thread(_render_card)
        return discord.File(buffer, filename=f"rank_{target.name}.png")


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

                    all_configs = load_json(CONFIG_FILE)
                    guild_config = all_configs.get(guild_id, {})
                    base_exp_vc = guild_config.get("exp_per_vc_min", 5)
                    base_rswn_vc = guild_config.get("rswn_per_vc_min", 10)
                    exp_per_level = guild_config.get("exp_per_level", 3500)
                    max_level = guild_config.get("max_level", 0)

                    for vc in guild.voice_channels:
                        for member in vc.members:
                            if member.bot or member.voice.self_deaf or member.voice.self_mute:
                                continue

                            user_id = str(member.id)
                            if user_id not in data:
                                data[user_id] = {"exp": 0, "weekly_exp": 0, "level": 0, "badges": []}
                            
                            exp_gain_vc = int(base_exp_vc * anomaly_multiplier)
                            rswn_gain_vc = int(base_rswn_vc * anomaly_multiplier)

                            data[user_id]["exp"] += exp_gain_vc
                            data[user_id].setdefault("weekly_exp", 0)
                            data[user_id]["weekly_exp"] += exp_gain_vc

                            # Rekap durasi aktif voice (60 detik per menit perulangan)
                            data[user_id].setdefault("voice_time", 0)
                            data[user_id]["voice_time"] += 60
                            data[user_id].setdefault("weekly_voice_time", 0)
                            data[user_id]["weekly_voice_time"] += 60

                            if user_id not in bank_data:
                                bank_data[user_id] = {"balance": 0, "debt": 0}
                            bank_data[user_id]["balance"] += rswn_gain_vc

                            new_level = calculate_new_level(data[user_id]["exp"], exp_per_level, max_level)
                            if new_level > data[user_id].get("level", 0):
                                data[user_id]["level"] = new_level
                                await self.level_up(member, guild, None, new_level, data)

                    all_level_data[guild_id] = data
                    save_json(LEVEL_FILE, all_level_data)
                    save_json(BANK_FILE, bank_data)

                    # Pembaruan otomatis (auto-update) panel voice terlama jika aktif di server
                    try:
                        await self.update_voice_panel(guild)
                    except Exception:
                        pass

                    if now.weekday() == WEEKLY_RESET_DAY and now.date() != self.last_reset.date():
                        for user_data in data.values():
                            user_data["weekly_exp"] = 0
                            user_data["weekly_voice_time"] = 0
                        self.last_reset = now
                        save_json(LEVEL_FILE, all_level_data)
            except Exception:
                pass
        return voice_task

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        if message.content.startswith(self.bot.command_prefix):
            return

        user_id = str(message.author.id)
        guild_id = str(message.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.setdefault(guild_id, {})
        bank_data = load_json(BANK_FILE)

        all_configs = load_json(CONFIG_FILE)
        guild_config = all_configs.get(guild_id, {})

        # Sticky Voice Panel: jika ada pesan baru di channel panel, reposisi panel ke dasar channel
        try:
            v_channel_id = guild_config.get("voice_panel_channel_id")
            if v_channel_id and message.channel.id == v_channel_id:
                asyncio.create_task(self.reposition_voice_panel_bottom(message.guild, message.channel))
        except Exception:
            pass

        base_exp_msg = guild_config.get("exp_per_msg", 10)
        base_rswn_msg = guild_config.get("rswn_per_msg", 1)
        exp_per_level = guild_config.get("exp_per_level", 3500)
        max_level = guild_config.get("max_level", 0)

        if user_id not in data:
            data[user_id] = {"exp": 0, "weekly_exp": 0, "level": 0, "badges": [], "last_active": None, "booster": {}, "msg_count": 0, "last_msg_time": None, "last_daily": None}
        if user_id not in bank_data:
            bank_data[user_id] = {"balance": 0, "debt": 0}

        user_level_data = data[user_id]
        now = datetime.utcnow()

        last_msg_time_str = user_level_data.get("last_msg_time")
        if last_msg_time_str:
            last_msg_time = datetime.fromisoformat(last_msg_time_str)
            if (now - last_msg_time).total_seconds() > 5:
                user_level_data["msg_count"] = user_level_data.get("msg_count", 0) + 1
                user_level_data["last_msg_time"] = now.isoformat()
        else:
            user_level_data["msg_count"] = user_level_data.get("msg_count", 0) + 1
            user_level_data["last_msg_time"] = now.isoformat()

        last_daily_str = user_level_data.get("last_daily")
        if last_daily_str:
            last_daily = datetime.fromisoformat(last_daily_str)
            if (now - last_daily).total_seconds() >= 86400:
                reward_exp = random.randint(100, 300)
                reward_rswn = random.randint(20, 100)
                user_level_data["exp"] += reward_exp
                bank_data[user_id]["balance"] += reward_rswn
                user_level_data["last_daily"] = now.isoformat()
        else:
            user_level_data["last_daily"] = now.isoformat()

        booster = user_level_data.get("booster", {})
        personal_multiplier = 1
        expires = booster.get("expires_at")

        if expires:
            try:
                if now < datetime.fromisoformat(expires):
                    personal_multiplier = booster.get("exp_multiplier", 1)
                else:
                    user_level_data["booster"] = {}
            except Exception:
                user_level_data["booster"] = {}
        
        anomaly_multiplier = self.get_anomaly_multiplier()
        final_multiplier = personal_multiplier * anomaly_multiplier
        exp_gain = int(base_exp_msg * final_multiplier)
        rswn_gain = int(base_rswn_msg * final_multiplier)
        
        bank_data[user_id]["balance"] += rswn_gain
        user_level_data["exp"] += exp_gain
        user_level_data.setdefault("weekly_exp", 0)
        user_level_data["weekly_exp"] += exp_gain
        user_level_data["last_active"] = now.isoformat()

        new_level = calculate_new_level(user_level_data["exp"], exp_per_level, max_level)
        if new_level > user_level_data.get("level", 0):
            user_level_data["level"] = new_level
            await self.level_up(message.author, message.guild, message.channel, new_level, data)
            save_json(LEVEL_FILE, all_level_data)
        
        all_level_data[guild_id] = data
        self._dirty_level = True
        self._dirty_bank = True

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
            level_badges = config.get("level_badges", {"5": "🥉", "10": "🥈", "15": "🥇"})
            
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

            badge = level_badges.get(str(new_level))
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
                    custom_msg = config.get("levelup_message", "🎉 Selamat {mention}, kamu telah mencapai **Level {level}**!")
                    formatted_msg = custom_msg.replace("{mention}", member.mention).replace("{level}", str(new_level))
                    
                    user_id = str(member.id)
                    bank_data = load_json(BANK_FILE)
                    user_bank = bank_data.get(user_id, {"balance": 0})
                    balance = user_bank.get("balance", 0)
                    exp = data.get(user_id, {}).get("exp", 0)
                    
                    rank_image_file = await self.create_rank_image(member, new_level, exp, balance, guild)
                    await announce_channel.send(content=formatted_msg, file=rank_image_file)
        except Exception:
            pass
            
    @commands.hybrid_command(name="giveaway", description="Mulai giveaway baru dengan syarat tertentu")
    @commands.has_permissions(administrator=True)
    async def start_giveaway(self, ctx: commands.Context, hadiah: str, durasi_menit: int, jumlah_pemenang: int, min_level: int = 0, min_messages: int = 0, req_role: discord.Role = None):
        end_time = datetime.utcnow() + timedelta(minutes=durasi_menit)
        role_id = req_role.id if req_role else None

        embed = discord.Embed(
            title="🎉 GIVEAWAY BARU 🎉", 
            description=f"**Hadiah:** {hadiah}\n**Jumlah Pemenang:** {jumlah_pemenang}\n**Berakhir:** <t:{int(end_time.timestamp())}:R>", 
            color=discord.Color.purple()
        )
        
        syarat_teks = f"**Level Minimal:** {min_level}\n**Pesan Minimal:** {min_messages}\n**Role Wajib:** {req_role.mention if req_role else 'Tidak ada'}"
        embed.add_field(name="📜 Syarat & Ketentuan", value=syarat_teks)

        view = GiveawayJoinView(self.bot, None, min_level, min_messages, role_id)
        msg = await ctx.send(embed=embed, view=view)
        view.message_id = msg.id

        await asyncio.sleep(durasi_menit * 60)

        try:
            msg = await ctx.channel.fetch_message(msg.id)
        except discord.NotFound:
            return

        anim_texts = ["Mengocok dadu 🎲...", "Mencari pemenang yang beruntung 🔍...", "Menyiapkan hadiah ⏳..."]
        for teks in anim_texts:
            anim_embed = discord.Embed(title="🎉 MENGUNGKAP PEMENANG... 🎉", description=teks, color=discord.Color.gold())
            await msg.edit(embed=anim_embed, view=None)
            await asyncio.sleep(1.5)

        if len(view.participants) == 0:
            fail_embed = discord.Embed(title="🎉 GIVEAWAY SELESAI 🎉", description="Tidak ada yang mengikuti atau memenuhi syarat giveaway ini.", color=discord.Color.red())
            return await msg.edit(embed=fail_embed, view=None)

        winners = random.sample(view.participants, min(jumlah_pemenang, len(view.participants)))
        winner_mentions = ", ".join([f"<@{w}>" for w in winners])

        win_embed = discord.Embed(
            title="🎉 GIVEAWAY SELESAI 🎉", 
            description=f"**Hadiah:** {hadiah}\n**Pemenang:** {winner_mentions}", 
            color=discord.Color.green()
        )
        await msg.edit(embed=win_embed, view=None)
        await ctx.send(f"Selamat kepada {winner_mentions}! Kalian memenangkan **{hadiah}**! Silakan hubungi admin untuk klaim hadiah.")
        
    @commands.hybrid_command(name="reroll", description="Pilih ulang pemenang giveaway")
    @commands.has_permissions(administrator=True)
    async def reroll_giveaway(self, ctx: commands.Context, message_id: str):
        try:
            msg_id_int = int(message_id)
        except ValueError:
            return await ctx.send("ID Pesan tidak valid. Pastikan kamu memasukkan deretan angka ID pesan.")

        participants = self.giveaways.get(msg_id_int)
        
        if not participants:
            return await ctx.send("Data giveaway tidak ditemukan. Pastikan bot belum direstart sejak giveaway dibuat.")

        if len(participants) == 0:
            return await ctx.send("Tidak ada peserta yang bisa diundi ulang untuk giveaway ini.")

        winner = random.choice(participants)
        
        embed = discord.Embed(
            title="🎲 REROLL GIVEAWAY 🎲",
            description=f"Pemenang baru telah terpilih!\nSelamat kepada <@{winner}>!",
            color=discord.Color.blue()
        )
        
        await ctx.send(content=f"<@{winner}>", embed=embed)
           

    @commands.command(name="setlevelconfig", help="Atur kebutuhan EXP per level dan batas Max Level server")
    @commands.has_permissions(administrator=True)
    async def set_level_config(self, ctx: commands.Context, exp_per_level: int, max_level: int):
        guild_id = str(ctx.guild.id)
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.setdefault(guild_id, {})
        config["exp_per_level"] = exp_per_level
        config["max_level"] = max_level
        save_json(CONFIG_FILE, all_configs)
        await ctx.send(f"✅ Pengaturan Level berhasil diubah!\nEXP per Level: **{exp_per_level}**\nMax Level: **{max_level if max_level > 0 else 'Tidak Terbatas'}**")

    @commands.command(name="setlevelbadge", help="Atur badge khusus yang diberikan otomatis saat capai level tertentu")
    @commands.has_permissions(administrator=True)
    async def set_level_badge(self, ctx: commands.Context, level: int, emoji: str):
        guild_id = str(ctx.guild.id)
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.setdefault(guild_id, {})
        badges = config.setdefault("level_badges", {"5": "🥉", "10": "🥈", "15": "🥇"})
        badges[str(level)] = emoji
        save_json(CONFIG_FILE, all_configs)
        await ctx.send(f"✅ Badge untuk **Level {level}** berhasil diatur menjadi {emoji}")

    @commands.command(name="removelevelbadge", help="Hapus pengaturan badge pada level tertentu")
    @commands.has_permissions(administrator=True)
    async def remove_level_badge(self, ctx: commands.Context, level: int):
        guild_id = str(ctx.guild.id)
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.get(guild_id, {})
        badges = config.get("level_badges", {})
        if str(level) in badges:
            del badges[str(level)]
            save_json(CONFIG_FILE, all_configs)
            await ctx.send(f"✅ Pengaturan badge untuk **Level {level}** berhasil dihapus.")
        else:
            await ctx.send(f"❌ Tidak ada badge yang diatur untuk **Level {level}**.")

    @commands.command(name="viewlevelconfig", help="Lihat daftar konfigurasi badge dan role level server")
    async def view_level_config(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.get(guild_id, {})
        badges = config.get("level_badges", {"5": "🥉", "10": "🥈", "15": "🥇"})
        roles = config.get("level_roles", {})

        embed = discord.Embed(title="Pengaturan Level Server", color=discord.Color.gold())
        
        desc_badges = ""
        for level in sorted(badges.keys(), key=int):
            desc_badges += f"**Level {level}** ➜ {badges[level]}\n"
        embed.add_field(name="Badges", value=desc_badges if desc_badges else "Tidak ada", inline=False)
        
        desc_roles = ""
        for level in sorted(roles.keys(), key=int):
            role_id = roles[level]
            desc_roles += f"**Level {level}** ➜ <@&{role_id}>\n"
        embed.add_field(name="Roles", value=desc_roles if desc_roles else "Tidak ada", inline=False)
        
        await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="setlevelannouncement", help="Atur channel dan kustom pesan pengumuman naik level")
    async def set_level_announcement(self, ctx: commands.Context, channel: discord.TextChannel = None, pesan: str = None):
        guild_id = str(ctx.guild.id)
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.setdefault(guild_id, {})
        
        if channel:
            config["announce_channel"] = channel.id
        if pesan:
            config["levelup_message"] = pesan
            
        save_json(CONFIG_FILE, all_configs)
        await ctx.send("✅ Konfigurasi pengumuman level berhasil diperbarui.", ephemeral=True)
            
    @commands.command(name="configrates", help="Buka panel untuk mengatur pendapatan EXP dan RSWN server")
    @commands.has_permissions(administrator=True)
    async def configrates(self, ctx: commands.Context):
        embed = discord.Embed(
            title="Pengaturan Rate Server", 
            description="Klik tombol di bawah untuk mengatur jumlah base EXP dan RSWN yang didapat member.",
            color=discord.Color.blue()
        )
        view = ConfigRatesView(ctx.guild.id)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="setlevelrole", help="Atur role yang diberikan otomatis saat capai level tertentu")
    @commands.has_permissions(administrator=True)
    async def set_level_role(self, ctx: commands.Context, level: int, role: discord.Role):
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

    @commands.command(name="removelevelrole", help="Hapus pengaturan role pada level tertentu")
    @commands.has_permissions(administrator=True)
    async def remove_level_role(self, ctx: commands.Context, level: int):
        guild_id = str(ctx.guild.id)
        all_configs = load_json(CONFIG_FILE)
        config = all_configs.get(guild_id, {})
        level_roles = config.get("level_roles", {})
        if str(level) in level_roles:
            del level_roles[str(level)]
            save_json(CONFIG_FILE, all_configs)
            await ctx.send(f"✅ Pengaturan role untuk **Level {level}** dihapus.")
        else:
            await ctx.send(f"❌ Tidak ada pengaturan role untuk **Level {level}**.")

    @commands.command(name="uangall", help="Berikan RSWN ke seluruh member di server")
    @commands.has_permissions(administrator=True)
    async def give_all_money(self, ctx: commands.Context, amount: int):
        if amount <= 0:
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
        await ctx.send(f"✅ Berhasil memberikan **{amount} RSWN** kepada **{updated_users_count} anggota** di server ini!")

    @commands.command(name="xpall", help="Berikan EXP ke seluruh member di server")
    @commands.has_permissions(administrator=True)
    async def give_all_xp(self, ctx: commands.Context, amount: int):
        if amount <= 0:
            return await ctx.send("Jumlah EXP harus positif.", ephemeral=True)
        await ctx.defer()
        
        guild_id_str = str(ctx.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        level_data = all_level_data.setdefault(guild_id_str, {})
        
        all_configs = load_json(CONFIG_FILE)
        guild_config = all_configs.get(guild_id_str, {})
        exp_per_level = guild_config.get("exp_per_level", 3500)
        max_level = guild_config.get("max_level", 0)
        
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
            
            new_level = calculate_new_level(user_level_data["exp"], exp_per_level, max_level)
            if new_level > old_level:
                user_level_data["level"] = new_level
                await self.level_up(member, ctx.guild, ctx.channel, new_level, level_data)
            updated_users_count += 1
        
        all_level_data[guild_id_str] = level_data
        save_json(LEVEL_FILE, all_level_data)
        await ctx.send(f"✅ Berhasil memberikan **{amount} EXP** kepada **{updated_users_count} anggota** di server ini!")

    @commands.command(name="addquest", help="Tambahkan quest harian baru ke sistem")
    @commands.has_permissions(administrator=True)
    async def add_quest(self, ctx: commands.Context, description: str, reward_exp: int, reward_coins: int):
        if reward_exp < 0 or reward_coins < 0:
            return await ctx.send("❌ Reward harus bernilai positif!", ephemeral=True)
        quests_data = load_json(QUESTS_FILE)
        new_id = str(len(quests_data.get("quests", {})) + 1)
        quests_data.setdefault("quests", {})[new_id] = {
            "description": description, "reward_exp": reward_exp, "reward_coins": reward_coins
        }
        save_json(QUESTS_FILE, quests_data)
        await ctx.send(f"✅ Quest baru berhasil ditambahkan dengan ID `{new_id}`!")

    @commands.hybrid_command(name="daily_quest", description="Cek deskripsi quest harian yang aktif saat ini")
    async def daily_quest(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        try:
            with open(f"data/daily_quest_{guild_id}.json", "r", encoding="utf-8") as f:
                daily_quest_data = json.load(f)
            await ctx.send(f"🎯 Quest Harian: {daily_quest_data['description']}")
        except FileNotFoundError:
            await ctx.send("❌ Belum ada quest harian yang ditentukan!")

    @commands.hybrid_command(name="complete_quest", description="Selesaikan quest harian untuk mengambil hadiah")
    async def complete_quest(self, ctx: commands.Context):
        await ctx.defer()
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        daily_quest_file = f"data/daily_quest_{guild_id}.json"
        
        if not os.path.exists(daily_quest_file):
            return await ctx.send("❌ Belum ada quest harian yang ditentukan!")
            
        try:
            with open(daily_quest_file, "r") as f:
                daily_quest_data = json.load(f)
            
            all_level_data = load_json(LEVEL_FILE)
            data = all_level_data.setdefault(guild_id, {})
            
            all_configs = load_json(CONFIG_FILE)
            guild_config = all_configs.get(guild_id, {})
            exp_per_level = guild_config.get("exp_per_level", 3500)
            max_level = guild_config.get("max_level", 0)
            
            if user_id not in data:
                data[user_id] = {"exp": 0, "level": 0, "weekly_exp": 0, "badges": [], "last_completed_quest": None}
            
            user_level_data = data[user_id]
            last_completed = user_level_data.get("last_completed_quest")
            
            if last_completed:
                last_completed_date = datetime.fromisoformat(last_completed)
                if last_completed_date.date() == datetime.utcnow().date():
                    return await ctx.send("❌ Kamu sudah menyelesaikan quest harian hari ini!")
            
            old_level = user_level_data.get("level", 0)
            user_level_data["exp"] += daily_quest_data["reward_exp"]
            user_level_data["last_completed_quest"] = datetime.utcnow().isoformat()
            
            new_level = calculate_new_level(user_level_data["exp"], exp_per_level, max_level)
            
            save_json(LEVEL_FILE, all_level_data)
            
            bank_data = load_json(BANK_FILE)
            if user_id not in bank_data:
                bank_data[user_id] = {"balance": 0, "debt": 0}
                
            bank_data[user_id]["balance"] += daily_quest_data["reward_coins"]
            save_json(BANK_FILE, bank_data)
            
            await ctx.send(f"✅ Kamu telah menyelesaikan quest harian! Reward: {daily_quest_data['reward_exp']} EXP dan {daily_quest_data['reward_coins']} 🪙RSWN.")
            
            if new_level > old_level:
                user_level_data["level"] = new_level
                save_json(LEVEL_FILE, all_level_data)
                await self.level_up(ctx.author, ctx.guild, ctx.channel, new_level, data)
                
        except json.JSONDecodeError:
            await ctx.send("❌ Terjadi kesalahan saat membaca quest harian.")
        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {str(e)}")

    @commands.command(name="giveexp", help="Berikan EXP gratis kepada member tertentu")
    @commands.has_permissions(administrator=True)
    async def giveexp(self, ctx: commands.Context, member: discord.Member, amount: int):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.setdefault(guild_id, {})
        now = datetime.utcnow().isoformat()
        
        all_configs = load_json(CONFIG_FILE)
        guild_config = all_configs.get(guild_id, {})
        exp_per_level = guild_config.get("exp_per_level", 3500)
        max_level = guild_config.get("max_level", 0)
        
        user_level_data = data.setdefault(user_id, {"exp": 0, "level": 0, "last_active": now, "weekly_exp": 0, "badges": []})
        user_level_data["exp"] += amount
        user_level_data.setdefault("weekly_exp", 0)
        user_level_data["weekly_exp"] += amount
        user_level_data["last_active"] = now
        
        old_level = user_level_data.get("level", 0)
        new_level = calculate_new_level(user_level_data["exp"], exp_per_level, max_level)
        
        if new_level > old_level:
            user_level_data["level"] = new_level
            save_json(LEVEL_FILE, all_level_data)
            await self.level_up(member, ctx.guild, ctx.channel, new_level, data)
        else:
            save_json(LEVEL_FILE, all_level_data)
            
        # DM disabled based on request
        # try:
        #     await member.send(f"🎁 Kamu telah menerima **{amount} EXP gratis** dari {ctx.author.mention}!")
        # except discord.Forbidden:
        #     pass
        await ctx.send(f"✅ Kamu telah memberikan **{amount} EXP** ke {member.mention}.", ephemeral=True)

    @commands.command(name="givecoins", help="Berikan RSWN gratis kepada member tertentu")
    @commands.has_permissions(administrator=True)
    async def givecoins(self, ctx: commands.Context, member: discord.Member, amount: int):
        bank_data = load_json(BANK_FILE)
        user_id = str(member.id)
        if user_id not in bank_data:
            bank_data[user_id] = {"balance": 0, "debt": 0}
        bank_data[user_id]["balance"] += amount
        save_json(BANK_FILE, bank_data)
        # DM disabled
        # try:
        #     await member.send(f"🎉 Kamu telah menerima **{amount} 🪙RSWN gratis** dari admin {ctx.author.mention}!")
        # except discord.Forbidden:
        #     pass
        await ctx.send(f"✅ Kamu telah memberikan **{amount} 🪙RSWN gratis** ke {member.mention}.", ephemeral=True)

    @commands.hybrid_command(name="transfercoins", description="Transfer RSWN milikmu ke pengguna lain")
    async def transfercoins(self, ctx: commands.Context, member: discord.Member, amount: int):
        bank_data = load_json(BANK_FILE)
        sender_id = str(ctx.author.id)
        receiver_id = str(member.id)
        if sender_id not in bank_data or bank_data[sender_id].get("balance", 0) < amount:
            return await ctx.send("❌ Saldo tidak cukup!", ephemeral=True)
        if amount <= 0:
            return await ctx.send("❌ Jumlah transfer harus positif!", ephemeral=True)
        if receiver_id not in bank_data:
            bank_data[receiver_id] = {"balance": 0, "debt": 0}
        bank_data[sender_id]["balance"] -= amount
        bank_data[receiver_id]["balance"] += amount
        save_json(BANK_FILE, bank_data)
        # DM disabled
        # try:
        #     await member.send(f"🎉 Kamu telah menerima **{amount} 🪙RSWN** dari {ctx.author.mention}!")
        # except discord.Forbidden:
        #     pass
        await ctx.send(f"✅ Transfer **{amount} 🪙RSWN** ke {member.mention} berhasil.", ephemeral=True)

    @commands.command(name="setlevel", help="Ubah level member secara instan")
    @commands.has_permissions(administrator=True)
    async def setlevel(self, ctx: commands.Context, member: discord.Member, level: int):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.setdefault(guild_id, {})
        
        all_configs = load_json(CONFIG_FILE)
        guild_config = all_configs.get(guild_id, {})
        exp_per_level = guild_config.get("exp_per_level", 3500)
        
        user_level_data = data.setdefault(user_id, {"exp": 0, "level": 0, "weekly_exp": 0, "badges": []})
        user_level_data["exp"] = level * exp_per_level
        user_level_data["level"] = level
        save_json(LEVEL_FILE, all_level_data)
        await ctx.send(f"✅ Level {member.mention} telah diset menjadi **{level}**!")

    @commands.hybrid_command(name="leaderboard", description="Melihat peringkat 10 besar EXP di server ini")
    async def leaderboard(self, ctx: commands.Context):
        await ctx.defer()
        guild_id = str(ctx.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        if not data:
            return await ctx.send("Belum ada data EXP di server ini.")

        sorted_users = sorted(data.items(), key=lambda x: x[1].get('exp', 0), reverse=True)
        medals = ["🥇", "🥈", "🥉"] + [f"`#{i}`" for i in range(4, 11)]

        top_lines = []
        for idx, (user_id, user_data) in enumerate(sorted_users[:10], start=1):
            user = ctx.guild.get_member(int(user_id))
            if user:
                medal = medals[idx - 1] if idx <= 10 else f"`#{idx}`"
                badges = " ".join(user_data.get("badges", []))
                badge_str = f" • {badges}" if badges else ""
                exp_val = user_data.get('exp', 0)
                lvl_val = user_data.get('level', 0)
                vc_sec = user_data.get('voice_time', 0)
                vc_str = f" | 🎙️ {format_voice_duration(vc_sec)}" if vc_sec > 0 else ""
                top_lines.append(f"{medal} **{user.display_name}**\nLevel **{lvl_val}** (EXP: `{exp_val:,}`){badge_str}{vc_str}")

        v2_fields = [{
            "name": "🏆 TOP 10 PERINGKAT EXP SERVER",
            "value": "\n\n".join(top_lines) if top_lines else "Belum ada member yang memiliki EXP."
        }]

        card = build_v2_card(
            title=f"🏆 EXP Leaderboard — {ctx.guild.name}",
            description="Peringkat 10 anggota teratas dengan perolehan EXP dan level tertinggi di server ini.",
            fields=v2_fields,
            color=0xF1C40F,
            footer=f"Total Data: {len(data)} Member • Diperbarui: {datetime.now().strftime('%d/%m/%Y %H:%M')} WIB"
        )

        try:
            from cogs.v2_layout import send_v2_message
            resp = await send_v2_message(self.bot, ctx.channel.id, [card])
            if resp and (not isinstance(resp, dict) or "error_msg" not in resp):
                return
        except Exception:
            pass

        # Fallback ke Discord Embed jika layout V2 tidak tersedia
        embed = discord.Embed(
            title=f"🏆 EXP Leaderboard — {ctx.guild.name}",
            description="\n\n".join(top_lines) if top_lines else "Belum ada member.",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="weekly", description="Melihat peringkat 10 besar EXP mingguan di server ini")
    async def weekly(self, ctx: commands.Context):
        await ctx.defer()
        guild_id = str(ctx.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        if not data:
            return await ctx.send("Belum ada data EXP di server ini.")

        valid_users = {uid: udata for uid, udata in data.items() if ctx.guild.get_member(int(uid))}
        sorted_users = sorted(valid_users.items(), key=lambda x: x[1].get('weekly_exp', 0), reverse=True)
        medals = ["🥇", "🥈", "🥉"] + [f"`#{i}`" for i in range(4, 11)]

        top_lines = []
        for idx, (user_id, user_data) in enumerate(sorted_users[:10], start=1):
            user = ctx.guild.get_member(int(user_id))
            if user:
                medal = medals[idx - 1] if idx <= 10 else f"`#{idx}`"
                w_exp = user_data.get('weekly_exp', 0)
                w_vc = user_data.get('weekly_voice_time', 0)
                vc_info = f" | 🎙️ {format_voice_duration(w_vc)}" if w_vc > 0 else ""
                top_lines.append(f"{medal} **{user.display_name}**\nEXP Mingguan: `+{w_exp:,}`{vc_info}")

        v2_fields = [{
            "name": "🏅 TOP 10 PEROLEHAN EXP MINGGU INI",
            "value": "\n\n".join(top_lines) if top_lines else "Belum ada aktivitas mingguan."
        }]

        card = build_v2_card(
            title=f"🏅 Weekly Leaderboard — {ctx.guild.name}",
            description="Peringkat anggota paling aktif mengumpulkan EXP selama minggu ini (reset otomatis setiap Senin).",
            fields=v2_fields,
            color=0x3498DB,
            footer=f"Reset mingguan: Senin 00:00 UTC • {datetime.now().strftime('%d/%m/%Y %H:%M')} WIB"
        )

        try:
            from cogs.v2_layout import send_v2_message
            resp = await send_v2_message(self.bot, ctx.channel.id, [card])
            if resp and (not isinstance(resp, dict) or "error_msg" not in resp):
                return
        except Exception:
            pass

        embed = discord.Embed(
            title=f"🏅 Weekly Leaderboard — {ctx.guild.name}",
            description="\n\n".join(top_lines) if top_lines else "Belum ada aktivitas mingguan.",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)

    def build_voice_panel_card(self, guild: discord.Guild):
        guild_id = str(guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})

        # 1. Top 10 All-Time Voice Time
        users_with_voice = [
            (uid, udata) for uid, udata in data.items()
            if udata.get("voice_time", 0) > 0 and guild.get_member(int(uid))
        ]
        sorted_voice_all = sorted(users_with_voice, key=lambda x: x[1].get("voice_time", 0), reverse=True)[:10]

        medals = ["🥇", "🥈", "🥉"] + [f"`#{i}`" for i in range(4, 11)]
        top_all_lines = []
        for idx, (uid, udata) in enumerate(sorted_voice_all, start=1):
            member = guild.get_member(int(uid))
            if member:
                m_icon = medals[idx - 1]
                dur = format_voice_duration(udata.get("voice_time", 0))
                top_all_lines.append(f"{m_icon} **{member.display_name}** — `{dur}`")

        # 2. Top 5 Weekly Voice Time
        users_with_weekly = [
            (uid, udata) for uid, udata in data.items()
            if udata.get("weekly_voice_time", 0) > 0 and guild.get_member(int(uid))
        ]
        sorted_voice_weekly = sorted(users_with_weekly, key=lambda x: x[1].get("weekly_voice_time", 0), reverse=True)[:5]
        top_weekly_lines = []
        for idx, (uid, udata) in enumerate(sorted_voice_weekly, start=1):
            member = guild.get_member(int(uid))
            if member:
                dur = format_voice_duration(udata.get("weekly_voice_time", 0))
                top_weekly_lines.append(f"• **{member.display_name}** — `{dur}`")

        # 3. Aktivitas Voice Saat Ini
        active_members_count = 0
        active_channels_info = []
        for vc in guild.voice_channels:
            active_in_vc = [m for m in vc.members if not m.bot]
            if active_in_vc:
                active_members_count += len(active_in_vc)
                names = ", ".join(m.display_name for m in active_in_vc[:4])
                if len(active_in_vc) > 4:
                    names += f" +{len(active_in_vc) - 4} lainnya"
                active_channels_info.append(f"🔊 **{vc.name}** ({len(active_in_vc)} member): {names}")

        fields = [
            {
                "name": "👑 TOP 10 MEMBER VOICE TERLAMA (ALL-TIME)",
                "value": "\n".join(top_all_lines) if top_all_lines else "Belum ada catatan durasi voice."
            },
            {
                "name": "⚡ TOP VOICE MINGGU INI",
                "value": "\n".join(top_weekly_lines) if top_weekly_lines else "Belum ada catatan voice minggu ini."
            },
            {
                "name": f"🎙️ STATUS VOICE REAL-TIME ({active_members_count} MEMBER AKTIF)",
                "value": "\n".join(active_channels_info) if active_channels_info else "Saat ini belum ada member di Voice Channel."
            }
        ]

        buttons = [
            {"label": "Cek Voice Saya", "style": 1, "emoji": "⏱️", "custom_id": "voicepanel_check_self"},
            {"label": "Perbarui Panel", "style": 2, "emoji": "🔄", "custom_id": "voicepanel_refresh"}
        ]

        now_wib = datetime.utcnow() + timedelta(hours=7)
        card = build_v2_card(
            title=f"🎙️ Voice Activity & Leaderboard — {guild.name}",
            description="Papan statistik dan peringkat member terlama aktif di voice channel server.",
            fields=fields,
            color=0x2ECC71,
            buttons=buttons,
            footer=f"Auto-update tiap 1 menit • Terakhir diperbarui: {now_wib.strftime('%d/%m/%Y %H:%M:%S')} WIB"
        )
        return card

    async def reposition_voice_panel_bottom(self, guild: discord.Guild, channel: discord.abc.Messageable):
        """Hapus panel lama dan kirim ulang di paling bawah jika ada chat baru yang masuk ke channel panel."""
        guild_id = str(guild.id)
        lock = self._voice_panel_locks.setdefault(guild_id, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            all_configs = load_json(CONFIG_FILE)
            guild_config = all_configs.get(guild_id, {})
            panel_id = guild_config.get("voice_panel_message_id")
            channel_id = guild_config.get("voice_panel_channel_id")

            if not panel_id or channel.id != channel_id:
                return

            try:
                old_panel = await channel.fetch_message(panel_id)
                await old_panel.delete()
            except Exception:
                pass

            card = self.build_voice_panel_card(guild)
            try:
                from cogs.v2_layout import send_v2_message
                resp = await send_v2_message(self.bot, channel.id, [card])
                if resp and isinstance(resp, dict) and "id" in resp:
                    guild_config["voice_panel_message_id"] = int(resp["id"])
                    save_json(CONFIG_FILE, all_configs)
            except Exception:
                pass

    async def update_voice_panel(self, guild: discord.Guild):
        guild_id = str(guild.id)
        all_configs = load_json(CONFIG_FILE)
        guild_config = all_configs.get(guild_id, {})
        panel_id = guild_config.get("voice_panel_message_id")
        channel_id = guild_config.get("voice_panel_channel_id")

        if not panel_id or not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            return

        lock = self._voice_panel_locks.setdefault(guild_id, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            try:
                panel_message = await channel.fetch_message(panel_id)
            except discord.NotFound:
                guild_config["voice_panel_message_id"] = None
                save_json(CONFIG_FILE, all_configs)
                return
            except Exception:
                return

            card = self.build_voice_panel_card(guild)

            # Jika ada pesan baru di bawah panel (bukan pesan terbawah), hapus dan kirim ulang di paling bawah
            if channel.last_message_id and channel.last_message_id != panel_id:
                try:
                    await panel_message.delete()
                except Exception:
                    pass
                from cogs.v2_layout import send_v2_message
                resp = await send_v2_message(self.bot, channel.id, [card])
                if resp and isinstance(resp, dict) and "id" in resp:
                    guild_config["voice_panel_message_id"] = int(resp["id"])
                    save_json(CONFIG_FILE, all_configs)
                return

            # Jika panel sudah di paling bawah, update data secara in-place dengan edit_v2_message
            try:
                from cogs.v2_layout import edit_v2_message
                resp = await edit_v2_message(self.bot, channel.id, panel_message.id, [card])
                if resp is None:
                    try: await panel_message.delete()
                    except Exception: pass
                    from cogs.v2_layout import send_v2_message
                    new_resp = await send_v2_message(self.bot, channel.id, [card])
                    if new_resp and isinstance(new_resp, dict) and "id" in new_resp:
                        guild_config["voice_panel_message_id"] = int(new_resp["id"])
                        save_json(CONFIG_FILE, all_configs)
            except Exception:
                pass

    @commands.hybrid_command(name="voicepanel", description="Pasang panel leaderboard dan aktivitas voice server yang otomatis ter-update.")
    @commands.has_permissions(manage_guild=True)
    async def voicepanel(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        guild = ctx.guild
        guild_id = str(guild.id)
        all_configs = load_json(CONFIG_FILE)
        guild_config = all_configs.setdefault(guild_id, {})

        old_panel_id = guild_config.get("voice_panel_message_id")
        old_channel_id = guild_config.get("voice_panel_channel_id")
        if old_panel_id and old_channel_id:
            old_channel = guild.get_channel(old_channel_id)
            if old_channel:
                try:
                    old_msg = await old_channel.fetch_message(old_panel_id)
                    await old_msg.delete()
                except Exception:
                    pass

        card = self.build_voice_panel_card(guild)
        from cogs.v2_layout import send_v2_message
        resp = await send_v2_message(self.bot, ctx.channel.id, [card])
        if resp and isinstance(resp, dict) and "id" in resp:
            guild_config["voice_panel_message_id"] = int(resp["id"])
            guild_config["voice_panel_channel_id"] = ctx.channel.id
            save_json(CONFIG_FILE, all_configs)
            await ctx.send("✅ Panel aktivitas voice berhasil dipasang di channel ini dan akan selalu berada di posisi paling bawah!", ephemeral=True)
        else:
            await ctx.send("❌ Gagal mengirim panel voice dengan format Layout V2.", ephemeral=True)

    @commands.hybrid_command(name="voicetime", description="Cek total durasi aktif di voice channel server ini")
    @app_commands.describe(member="Member yang ingin dicek waktu voice-nya (kosongkan untuk diri sendiri)")
    async def voicetime(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        guild_id = str(ctx.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        user_data = data.get(str(target.id), {})

        v_time = user_data.get("voice_time", 0)
        w_time = user_data.get("weekly_voice_time", 0)

        all_v = sorted([(uid, ud.get("voice_time", 0)) for uid, ud in data.items()], key=lambda x: x[1], reverse=True)
        rank_no = "N/A"
        for idx, (uid, _) in enumerate(all_v, start=1):
            if uid == str(target.id):
                rank_no = f"#{idx}"
                break

        current_vc = target.voice.channel if target.voice else None
        status_text = f"🟢 Sedang online di **#{current_vc.name}**" if current_vc else "⚪ Sedang tidak berada di Voice Channel"

        embed = discord.Embed(
            title=f"🎙️ Statistik Voice • {target.display_name}",
            color=0x2ECC71 if current_vc else discord.Color.blue(),
            timestamp=datetime.now()
        )
        if target.avatar:
            embed.set_thumbnail(url=target.avatar.url)
        embed.add_field(name="⏱️ Total Waktu Voice (All-Time)", value=f"**{format_voice_duration(v_time)}**", inline=True)
        embed.add_field(name="⚡ Waktu Minggu Ini", value=f"**{format_voice_duration(w_time)}**", inline=True)
        embed.add_field(name="🏆 Peringkat Voice Server", value=f"**{rank_no}** dari {len(all_v)} member", inline=True)
        embed.add_field(name="📡 Status Voice Saat Ini", value=status_text, inline=False)
        embed.set_footer(text="Gunakan /voicepanel untuk memasang papan leaderboard voice lengkap.")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get("custom_id", "")
        if custom_id == "voicepanel_check_self":
            guild = interaction.guild
            if not guild:
                return
            all_level_data = load_json(LEVEL_FILE)
            data = all_level_data.get(str(guild.id), {})
            user_data = data.get(str(interaction.user.id), {})
            v_time = user_data.get("voice_time", 0)
            w_time = user_data.get("weekly_voice_time", 0)
            cur_vc = interaction.user.voice.channel if interaction.user.voice else None
            status_str = f"Sedang aktif di #{cur_vc.name}" if cur_vc else "Tidak sedang berada di Voice Channel"

            resp_text = (
                f"🎙️ **Statistik Voice Kamu di {guild.name}**:\n"
                f"• **Total Waktu Voice (All-Time):** `{format_voice_duration(v_time)}`\n"
                f"• **Total Waktu Minggu Ini:** `{format_voice_duration(w_time)}`\n"
                f"• **Status Sekarang:** {status_str}"
            )
            await interaction.response.send_message(resp_text, ephemeral=True)
        elif custom_id == "voicepanel_refresh":
            guild = interaction.guild
            if not guild:
                return
            await self.update_voice_panel(guild)
            await interaction.response.send_message("✅ Panel Voice berhasil diperbarui ke data terbaru!", ephemeral=True)
        
    @commands.hybrid_command(name="rank", description="Lihat kartu rank, progress level, dan status RSWN dengan visual eksklusif")
    @app_commands.describe(member="Pilih member untuk melihat rank mereka (opsional)")
    async def rank(self, ctx: commands.Context, member: discord.Member = None):
        await ctx.defer()
        
        target = member or ctx.author
        user_id = str(target.id)
        guild_id = str(ctx.guild.id)
        
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        bank = load_json(BANK_FILE)
        
        sorted_users = sorted(data.items(), key=lambda x: x[1].get('exp', 0), reverse=True)
        rank_pos = 1
        for idx, (uid, udata) in enumerate(sorted_users):
            if uid == user_id:
                rank_pos = idx + 1
                break

        user_data = data.get(user_id, {"level": 0, "exp": 0, "badges": []})
        user_bank = bank.get(user_id, {"balance": 0})
        
        level = user_data.get('level', 0)
        exp = user_data.get('exp', 0)
        balance = user_bank.get('balance', 0)
        badges = user_data.get('badges', [])

        rank_image_file = await self.create_rank_image(target, level, exp, balance, ctx.guild, rank_pos, badges)
        await ctx.send(file=rank_image_file)

    @commands.command(name="reduceuser", help="Kurangi EXP dan RSWN dari member beserta alasannya")
    @commands.has_permissions(administrator=True)
    async def reduce_user(self, ctx: commands.Context, member: discord.Member, exp: int, rswn: int, reason: str):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        bank_data = load_json(BANK_FILE)
        
        all_configs = load_json(CONFIG_FILE)
        guild_config = all_configs.get(guild_id, {})
        exp_per_level = guild_config.get("exp_per_level", 3500)
        max_level = guild_config.get("max_level", 0)
        
        if user_id not in data:
            return await ctx.send("❌ Pengguna tidak ditemukan dalam data!", ephemeral=True)
        if data[user_id].get("exp", 0) < exp:
            return await ctx.send("❌ Pengguna tidak memiliki cukup EXP untuk dikurangi!", ephemeral=True)
        if user_id not in bank_data or bank_data[user_id].get("balance", 0) < rswn:
            return await ctx.send("❌ Pengguna tidak memiliki cukup RSWN untuk dikurangi!", ephemeral=True)
        
        data[user_id]["exp"] -= exp
        bank_data[user_id]["balance"] -= rswn
        data[user_id]["level"] = calculate_new_level(data[user_id]["exp"], exp_per_level, max_level)
        
        save_json(LEVEL_FILE, all_level_data)
        save_json(BANK_FILE, bank_data)
        await ctx.send(f"✅ {member.mention} telah dikurangi **{exp} EXP** dan **{rswn} RSWN**! Alasan: *{reason}*")

    @commands.command(name="resetall", help="Reset ulang seluruh EXP dan Rank semua orang di server")
    @commands.has_permissions(administrator=True)
    async def resetall(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        all_level_data = load_json(LEVEL_FILE)
        data = all_level_data.get(guild_id, {})
        if not data:
            return await ctx.send("ℹ️ Tidak ada data untuk direset.", ephemeral=True)

        for user_id in data.keys():
            data[user_id]["exp"] = 0
            data[user_id]["weekly_exp"] = 0
            data[user_id]["level"] = 0
            data[user_id]["badges"] = []
        save_json(LEVEL_FILE, all_level_data)
        await ctx.send("✅ Semua data EXP, Level, dan Badge pengguna di server ini telah direset!")

    @commands.command(name="manageitems", help="Buka panel admin untuk edit dan hapus item di toko")
    @commands.has_permissions(administrator=True)
    async def manageitems(self, ctx: commands.Context):
        with open(SHOP_FILE, 'r') as f:
            data = json.load(f)
        
        if not data:
            return await ctx.send("📭 Tidak ada item di shop.", ephemeral=True)
        
        view = CategoryDropdownView(self.bot, list(data.keys()))
        await ctx.send("📂 Pilih kategori item yang ingin kamu kelola:", view=view, ephemeral=True)
    
    @commands.hybrid_command(name="shop", description="Buka antarmuka toko interaktif untuk membeli item")
    async def shop(self, ctx: commands.Context):
        status = load_json(SHOP_STATUS_FILE)
        if not status.get("is_open", True):
            return await ctx.send("⚠️ Toko sedang *ditutup*.", ephemeral=True)

        self.shop_data = load_json(SHOP_FILE)
        self.collage_url = load_json(COLLAGE_FILE).get("collage_url")

        embed = discord.Embed(
            title="💎 reSwan Shop",
            color=discord.Color.blurple()
        )

        if self.collage_url:
            embed.set_image(url=self.collage_url)
        
        view = ShopCategoryView(self.bot, self.shop_data, ctx.author.id, ctx.guild.id)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="toggleshop", help="Buka atau tutup akses ke shop utama")
    @commands.has_permissions(administrator=True)
    async def toggle_shop(self, ctx: commands.Context):
        status = load_json(SHOP_STATUS_FILE)
        status["is_open"] = not status.get("is_open", True)
        save_json(SHOP_STATUS_FILE, status)
        state = "🟢 TERBUKA" if status["is_open"] else "🔴 TERTUTUP"
        await ctx.send(f"Toko sekarang telah diatur ke: **{state}**", ephemeral=True)

    @commands.command(name="toggleexpshop", help="Buka atau tutup akses user untuk membeli EXP")
    @commands.has_permissions(administrator=True)
    async def toggle_exp_shop(self, ctx: commands.Context):
        status = load_json(SHOP_STATUS_FILE)
        status["exp_shop_open"] = not status.get("exp_shop_open", True)
        save_json(SHOP_STATUS_FILE, status)
        state = "🟢 TERBUKA" if status["exp_shop_open"] else "🔴 TERTUTUP"
        await ctx.send(f"Toko pembelian EXP sekarang telah diatur ke: **{state}**", ephemeral=True)

    @commands.command(name="additem", help="Tambahkan item baru ke toko")
    async def add_item(self, ctx: commands.Context, category: str, name: str, price: int, description: str, emoji_or_type: str = None, stock: str = "unlimited", extra_1: str = None, extra_2: str = None):
        shop_data = load_json(SHOP_FILE)
        valid_categories = ["badges", "exp", "roles", "special_items"]
        category_lower = category.lower()

        if category_lower not in valid_categories:
            await ctx.send(f"⚠️ Kategori tidak valid. Gunakan: `{', '.join(valid_categories)}`.", ephemeral=True)
            return

        if category_lower not in shop_data:
            shop_data[category_lower] = []
        
        item = {
            "name": name,
            "price": price,
            "description": description,
            "stock": int(stock) if stock.lower() != "unlimited" else "unlimited"
        }

        if category_lower == "roles":
            if not extra_1:
                return await ctx.send("⚠️ Argumen extra_1 harus diisi dengan ID Role.", ephemeral=True)
            item["role_id"] = int(extra_1)
            item["emoji"] = emoji_or_type or "👑"
        elif category_lower == "badges":
            item["emoji"] = emoji_or_type or "🎭"
            if extra_1:
                item["image_url"] = extra_1
        elif category_lower == "exp":
            if not extra_1 or not extra_2:
                return await ctx.send("⚠️ extra_1 (Multiplier) dan extra_2 (Durasi) harus diisi.", ephemeral=True)
            try:
                item["multiplier"] = int(extra_1)
                item["duration_minutes"] = int(extra_2)
            except ValueError:
                return await ctx.send("⚠️ Multiplier dan durasi harus berupa angka.", ephemeral=True)
            item["type"] = "exp_booster"
            item["emoji"] = emoji_or_type or "🚀"
        elif category_lower == "special_items":
            if not emoji_or_type:
                return await ctx.send("⚠️ Masukkan emoji_or_type sebagai tipe item.", ephemeral=True)
            item["type"] = emoji_or_type
            if emoji_or_type == "protection_shield":
                item["emoji"] = "🛡️"
            elif emoji_or_type == "gacha_medicine_box":
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
        await ctx.send(f"✅ Item baru di kategori **{category_lower}**: **{name}**")

    @commands.command(name="addcollage", help="Ubah gambar banner kolase pada shop")
    @commands.has_permissions(administrator=True)
    async def add_collage(self, ctx: commands.Context, url: str):
        if not url.startswith("http://") and not url.startswith("https://"):
            return await ctx.send("❌ URL gambar tidak valid.", ephemeral=True)
        
        save_json(COLLAGE_FILE, {"collage_url": url})
        self.collage_url = url
        await ctx.send("✅ Gambar kolase berhasil diperbarui.", ephemeral=True)

    @commands.command(name="removeitem", help="Hapus item tertentu dari shop secara instan")
    @commands.has_permissions(administrator=True)
    async def remove_item(self, ctx: commands.Context, category: str, name: str):
        shop_data = load_json(SHOP_FILE)
        category_lower = category.lower()

        if category_lower not in shop_data:
            return await ctx.send(f"❌ Kategori **{category}** tidak ditemukan.", ephemeral=True)

        original_len = len(shop_data[category_lower])
        shop_data[category_lower] = [item for item in shop_data[category_lower] if item['name'].lower() != name.lower()]

        if len(shop_data[category_lower]) < original_len:
            save_json(SHOP_FILE, shop_data)
            await ctx.send(f"✅ Item **{name}** berhasil dihapus.", ephemeral=True)
        else:
            await ctx.send(f"❌ Item **{name}** tidak ditemukan.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ProgressionSystem(bot))
