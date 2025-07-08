import discord
from discord.ext import commands, tasks
import json
import os
import shutil

ADMIN_ID = 1000737066822410311  # Ganti dengan ID Discord kamu
FOLDERS_TO_BACKUP = ['data', 'config']
BACKUP_FOLDER = 'backup'

class Backup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        os.makedirs(BACKUP_FOLDER, exist_ok=True)
        self.auto_backup.start()
        self.auto_restore_on_load()

    def auto_restore_on_load(self):
        for folder in FOLDERS_TO_BACKUP:
            if not os.path.exists(folder):
                os.makedirs(folder)
            for filename in os.listdir(f"{BACKUP_FOLDER}"):
                if filename.endswith('.json') and not os.path.exists(os.path.join(folder, filename)):
                    shutil.copy(os.path.join(BACKUP_FOLDER, filename), os.path.join(folder, filename))
                else:
                    try:
                        with open(os.path.join(folder, filename), 'r') as f:
                            json.load(f)
                    except Exception:
                        shutil.copy(os.path.join(BACKUP_FOLDER, filename), os.path.join(folder, filename))

    @tasks.loop(hours=1)
    async def auto_backup(self):
        try:
            user = await self.bot.fetch_user(ADMIN_ID)
            for folder in FOLDERS_TO_BACKUP:
                if os.path.exists(folder):
                    for filename in os.listdir(folder):
                        if filename.endswith('.json'):
                            src = os.path.join(folder, filename)
                            dst = os.path.join(BACKUP_FOLDER, filename)
                            shutil.copy(src, dst)

            for filename in os.listdir(BACKUP_FOLDER):
                if filename.endswith('.json'):
                    file_path = os.path.join(BACKUP_FOLDER, filename)
                    await user.send(file=discord.File(file_path))
        except Exception as e:
            print(f"[ERROR] Auto backup gagal: {e}")

    @commands.command(name="backup", help="Backup semua file JSON dan kirim ke DM admin.")
    @commands.has_permissions(administrator=True)
    async def manual_backup(self, ctx):
        await self.auto_backup()
        await ctx.send("✅ Backup manual berhasil dikirim ke DM admin.")

async def setup(bot):
    await bot.add_cog(Backup(bot))
