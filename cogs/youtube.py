import discord
from discord.ext import commands
import requests

# ---------------- Modal untuk Auto Message ----------------
class AutoMessageModal(discord.ui.Modal, title="Setup Auto Message"):
    auto_name = discord.ui.TextInput(
        label="Auto Message Name (contoh: auto1, auto2)",
        placeholder="auto1",
        required=True,
        max_length=20
    )
    auto_message = discord.ui.TextInput(
        label="Auto Message Text",
        style=discord.TextStyle.paragraph,
        placeholder="Isi pesan otomatis",
        required=True,
        max_length=200
    )
    interval = discord.ui.TextInput(
        label="Interval (menit)",
        placeholder="5",
        required=True,
        max_length=3
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            payload = {"name": self.auto_name.value, "message": self.auto_message.value}
            r = requests.post(f"{self.cog.youtube_bot_api_url}/add_automessage", json=payload)
            data = r.json()

            payload_interval = {"interval": int(self.interval.value)}
            r2 = requests.post(f"{self.cog.youtube_bot_api_url}/update_interval", json=payload_interval)
            data2 = r2.json()

            await interaction.response.send_message(
                f"✅ {data['message']}\n⏱️ {data2['message']}", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Gagal setup auto message: {e}", ephemeral=True)

# ---------------- View dengan Tombol ----------------
class AutoButtonView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Setup Auto Message", style=discord.ButtonStyle.primary)
    async def setup_auto_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AutoMessageModal(self.cog)
        await interaction.response.send_modal(modal)

# ---------------- Cog Utama ----------------
class YoutubeControlCog(commands.Cog):
    """Cog yang berisi perintah untuk mengontrol bot YouTube."""

    def __init__(self, bot):
        self.bot = bot
        self.youtube_bot_api_url = "http://127.0.0.1:5000"

    # ---------- Monitoring ----------
    @commands.command(name="monitor")
    @commands.has_permissions(administrator=True)
    async def monitor(self, ctx, live_url: str):
        try:
            payload = {"url": live_url}
            r = requests.post(f"{self.youtube_bot_api_url}/start_monitoring", json=payload)
            data = r.json()
            await ctx.send(data["message"])
        except Exception as e:
            await ctx.send(f"❌ Gagal memulai monitoring: {e}")

    @commands.command(name="stopmonitor")
    @commands.has_permissions(administrator=True)
    async def stopmonitor(self, ctx):
        try:
            r = requests.post(f"{self.youtube_bot_api_url}/stop_monitoring")
            data = r.json()
            await ctx.send(data["message"])
        except Exception as e:
            await ctx.send(f"❌ Gagal stop monitoring: {e}")

        # ---------- Delete Custom Command ----------
    @commands.command(name="delcommand")
    @commands.has_permissions(administrator=True)
    async def delcommand(self, ctx, trigger: str):
        """Hapus command custom satu per satu"""
        try:
            payload = {"trigger": trigger}
            r = requests.post(f"{self.youtube_bot_api_url}/delete_command", json=payload)
            data = r.json()
            if data["success"]:
                await ctx.send(f"✅ Command `!{trigger}` berhasil dihapus.")
            else:
                await ctx.send(f"❌ {data['message']}")
        except Exception as e:
            await ctx.send(f"⚠️ Error hapus command: {e}")

    # ---------- Delete Auto Message ----------
    @commands.command(name="delautomsg")
    @commands.has_permissions(administrator=True)
    async def delautomsg(self, ctx, name: str):
        """Hapus auto message satu per satu"""
        try:
            payload = {"name": name}
            r = requests.post(f"{self.youtube_bot_api_url}/delete_automessage", json=payload)
            data = r.json()
            if data["success"]:
                await ctx.send(f"✅ Auto message `{name}` berhasil dihapus.")
            else:
                await ctx.send(f"❌ {data['message']}")
        except Exception as e:
            await ctx.send(f"⚠️ Error hapus auto message: {e}")


    # ---------- Custom Commands ----------
    @commands.command(name="addcommand")
    @commands.has_permissions(administrator=True)
    async def addcommand(self, ctx, trigger: str, *, response: str):
        try:
            payload = {"trigger": trigger, "response": response}
            r = requests.post(f"{self.youtube_bot_api_url}/add_command", json=payload)
            data = r.json()
            if data["success"]:
                await ctx.send(f"✅ Command `!{trigger}` berhasil ditambahkan!\nRespon: {response}")
            else:
                await ctx.send(f"❌ {data['message']}")
        except Exception as e:
            await ctx.send(f"⚠️ Error tambah command: {e}")

    # ---------- Auto Messages via Button ----------
    @commands.command(name="setupauto")
    @commands.has_permissions(administrator=True)
    async def setupauto(self, ctx):
        view = AutoButtonView(self)
        await ctx.send("📋 Klik tombol berikut untuk setup auto message:", view=view)

    @commands.command(name="setupautoform")
    @commands.has_permissions(administrator=True)
    async def setupautoform(self, ctx):
        modal = AutoMessageModal(self)
        await ctx.send("📋 Silakan isi form untuk setup auto message.")
        await ctx.author.send_modal(modal)

    # ---------- Reset & Settings ----------
    @commands.command(name="ytreset")
    @commands.has_permissions(administrator=True)
    async def ytreset(self, ctx):
        try:
            r = requests.post(f"{self.youtube_bot_api_url}/reset_all")
            data = r.json()
            await ctx.send(data["message"])
        except Exception as e:
            await ctx.send(f"❌ Gagal reset: {e}")

    @commands.command(name="getsettings")
    @commands.has_permissions(administrator=True)
    async def getsettings(self, ctx):
        try:
            r = requests.get(f"{self.youtube_bot_api_url}/get_settings")
            data = r.json()

            if not data["success"]:
                await ctx.send(f"❌ {data['message']}")
                return

            commands_list = "\n".join([f"• !{k} → {v}" for k, v in data["commands"].items()]) or "Tidak ada command."
            auto_msgs = "\n".join([f"• {name}: {msg}" for name, msg in data["automessages"]["messages"].items()]) or "Tidak ada pesan otomatis."
            interval = data["automessages"]["interval_minutes"]

            msg = (
                f"**📋 Setting Bot YouTube**\n\n"
                f"**Custom Commands:**\n{commands_list}\n\n"
                f"**Auto Messages (interval {interval} menit):**\n{auto_msgs}"
            )
            await ctx.send(msg)
        except Exception as e:
            await ctx.send(f"❌ Gagal ambil setting: {e}")

# ---------------- Setup Cog ----------------
async def setup(bot):
    await bot.add_cog(YoutubeControlCog(bot))

