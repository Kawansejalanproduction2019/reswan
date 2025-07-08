import discord
from discord.ext import commands
import json
import os

SHOP_FILE = 'data/shop_items.json'

class ItemManage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

class CategoryDropdownView(discord.ui.View):
    def __init__(self, bot, categories):
        super().__init__(timeout=60)
        self.add_item(CategoryDropdown(bot, categories))

class CategoryDropdown(discord.ui.Select):
    def __init__(self, bot, categories):
        self.bot = bot
        options = [discord.SelectOption(label=cat) for cat in categories]
        super().__init__(placeholder="Pilih kategori...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content=f"📦 Kategori dipilih: **{self.values[0]}**\nPilih item yang ingin dikelola:", view=ItemSelectionView(self.bot, self.values[0]))

class ItemSelectionView(discord.ui.View):
    def __init__(self, bot, category):
        super().__init__(timeout=60)
        self.bot = bot
        self.category = category
        self.add_item(ItemDropdown(bot, category))

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

class ItemActionView(discord.ui.View):
    def __init__(self, bot, category, index):
        super().__init__(timeout=60)
        self.add_item(EditItemButton(bot, category, index))
        self.add_item(RestockItemButton(bot, category, index))
        self.add_item(DeleteItemButton(bot, category, index))

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

async def setup(bot):
    await bot.add_cog(ItemManage(bot))
