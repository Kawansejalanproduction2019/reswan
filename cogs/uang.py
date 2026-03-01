import discord
from discord.ext import commands
import json
import os
import time
import csv
import io
from datetime import datetime

class PayModal(discord.ui.Modal):
    def __init__(self, list_unique_id, member_index, member_name, cog, guild_id):
        super().__init__(title=f"Bayar: {member_name}")
        self.list_unique_id = list_unique_id
        self.member_index = member_index
        self.cog = cog
        self.guild_id = guild_id

        self.amount = discord.ui.TextInput(
            label="Nominal",
            placeholder="Contoh: 50000",
            required=True,
            style=discord.TextStyle.short
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            nominal = int(self.amount.value.replace('.', '').replace(',', ''))
        except ValueError:
            await interaction.response.send_message("Nominal harus angka!", ephemeral=True)
            return
        await self.cog.process_payment(interaction, self.guild_id, self.list_unique_id, self.member_index, nominal)

class CashoutModal(discord.ui.Modal):
    def __init__(self, cog, guild_id):
        super().__init__(title="💸 Form Pengeluaran (Cashout)")
        self.cog = cog
        self.guild_id = guild_id

        self.amount = discord.ui.TextInput(
            label="Nominal Keluar",
            placeholder="Contoh: 150000",
            required=True,
            style=discord.TextStyle.short
        )
        self.reason = discord.ui.TextInput(
            label="Keperluan / Alasan",
            placeholder="Contoh: Bayar sewa server",
            required=True,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.amount)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            nominal = int(self.amount.value.replace('.', '').replace(',', ''))
        except ValueError:
            await interaction.response.send_message("Nominal harus angka!", ephemeral=True)
            return
        
        await self.cog.process_transaction(interaction, self.guild_id, nominal, self.reason.value, "OUT")

class ManualIncomeModal(discord.ui.Modal):
    def __init__(self, cog, guild_id):
        super().__init__(title="💰 Form Tambah Saldo (Manual)")
        self.cog = cog
        self.guild_id = guild_id

        self.amount = discord.ui.TextInput(
            label="Nominal Masuk",
            placeholder="Contoh: 1000000",
            required=True,
            style=discord.TextStyle.short
        )
        self.reason = discord.ui.TextInput(
            label="Sumber Dana / Keterangan",
            placeholder="Contoh: Sisa kas bulan lalu",
            required=True,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.amount)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            nominal = int(self.amount.value.replace('.', '').replace(',', ''))
        except ValueError:
            await interaction.response.send_message("Nominal harus angka!", ephemeral=True)
            return
        
        await self.cog.process_transaction(interaction, self.guild_id, nominal, self.reason.value, "IN_MANUAL")

class PayDropdown(discord.ui.Select):
    def __init__(self, list_unique_id, unpaid_members, cog, guild_id):
        options = []
        for idx, m in unpaid_members:
            options.append(discord.SelectOption(label=m['name'], value=str(idx), description=f"Urutan: {idx + 1}"))
        super().__init__(placeholder="Pilih nama yang mau bayar...", min_values=1, max_values=1, options=options)
        self.list_unique_id = list_unique_id
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        data = self.cog.get_data(self.guild_id)
        current_name = data['lists'][self.list_unique_id]['participants'][idx]['name']
        await interaction.response.send_modal(PayModal(self.list_unique_id, idx, current_name, self.cog, self.guild_id))

class PayView(discord.ui.View):
    def __init__(self, list_unique_id, unpaid_members, cog, guild_id):
        super().__init__()
        self.add_item(PayDropdown(list_unique_id, unpaid_members, cog, guild_id))

class ListSelectDropdown(discord.ui.Select):
    def __init__(self, active_lists, names_to_add, cog, guild_id):
        options = []
        for uid, ldata in active_lists:
            options.append(discord.SelectOption(label=ldata['title'], value=uid, description=f"Peserta: {len(ldata['participants'])} orang"))
        super().__init__(placeholder="Pilih List Tujuan...", min_values=1, max_values=1, options=options)
        self.names_to_add = names_to_add
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        uid = self.values[0]
        await self.cog.execute_add_names(interaction, self.guild_id, uid, self.names_to_add)

class ListSelectView(discord.ui.View):
    def __init__(self, active_lists, names_to_add, cog, guild_id):
        super().__init__()
        self.add_item(ListSelectDropdown(active_lists, names_to_add, cog, guild_id))

class CloseListDropdown(discord.ui.Select):
    def __init__(self, active_lists, cog, guild_id):
        options = []
        for uid, ldata in active_lists:
            collected = ldata.get('collected', 0)
            options.append(discord.SelectOption(label=ldata['title'], value=uid, description=f"Terkumpul: Rp {collected:,}"))
        super().__init__(placeholder="Pilih List yang mau DITUTUP...", min_values=1, max_values=1, options=options)
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        uid = self.values[0]
        await self.cog.execute_close_list(interaction, self.guild_id, uid)

class CloseListView(discord.ui.View):
    def __init__(self, active_lists, cog, guild_id):
        super().__init__()
        self.add_item(CloseListDropdown(active_lists, cog, guild_id))

class TriggerCashoutView(discord.ui.View):
    def __init__(self, cog, guild_id):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
    
    @discord.ui.button(label="Buka Form Cashout", style=discord.ButtonStyle.danger)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.check_role_interaction(interaction):
            await interaction.response.send_message("🚫 Anda tidak memiliki izin Admin Keuangan.", ephemeral=True)
            return
        await interaction.response.send_modal(CashoutModal(self.cog, self.guild_id))

class TriggerIncomeView(discord.ui.View):
    def __init__(self, cog, guild_id):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
    
    @discord.ui.button(label="Buka Form Tambah Saldo", style=discord.ButtonStyle.success)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.check_role_interaction(interaction):
            await interaction.response.send_message("🚫 Anda tidak memiliki izin Admin Keuangan.", ephemeral=True)
            return
        await interaction.response.send_modal(ManualIncomeModal(self.cog, self.guild_id))

class FinanceBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_file = "finance_db.json"
        self.data = {}
        self.DEFAULT_ADMIN_ROLE = 1472179349913600051 
        self.load_data()

    def load_data(self):
        if os.path.exists(self.db_file):
            with open(self.db_file, "r") as f:
                self.data = json.load(f)
        else:
            self.data = {}

    def save_data(self):
        with open(self.db_file, "w") as f:
            json.dump(self.data, f, indent=4)

    def get_data(self, guild_id):
        sid = str(guild_id)
        if sid not in self.data:
            self.data[sid] = {
                "lists": {},
                "balance": 0,
                "history": [],
                "log_channel": None,
                "admin_role": self.DEFAULT_ADMIN_ROLE
            }
        if "admin_role" not in self.data[sid]:
            self.data[sid]["admin_role"] = self.DEFAULT_ADMIN_ROLE
        return self.data[sid]

    def check_role(self, ctx):
        data = self.get_data(ctx.guild.id)
        role_id = data.get('admin_role', self.DEFAULT_ADMIN_ROLE)
        role = discord.utils.get(ctx.author.roles, id=role_id)
        return role is not None

    def check_role_interaction(self, interaction):
        data = self.get_data(interaction.guild.id)
        role_id = data.get('admin_role', self.DEFAULT_ADMIN_ROLE)
        role = discord.utils.get(interaction.user.roles, id=role_id)
        return role is not None

    async def delete_user_message(self, ctx):
        try:
            await ctx.message.delete()
        except:
            pass

    async def resend_list_message(self, guild, list_unique_id):
        sid = str(guild.id)
        data = self.data[sid]
        
        if list_unique_id not in data['lists']: return

        list_data = data['lists'][list_unique_id]
        channel = self.bot.get_channel(list_data['channel_id'])
        if not channel: return

        old_msg_id = list_data.get('message_id')
        if old_msg_id:
            try:
                old_msg = await channel.fetch_message(old_msg_id)
                await old_msg.delete()
            except: pass

        desc = ""
        for i, p in enumerate(list_data['participants']):
            status = "✅" if p['paid'] else ""
            desc += f"{i+1}. {p['name']} {status}\n"
        
        is_open = list_data['status'] == 'open'
        color = discord.Color.green() if is_open else discord.Color.red()
        status_text = "" if is_open else "🔴 [DITUTUP]"
        
        embed = discord.Embed(title=f"{list_data['title']} {status_text}", description=desc, color=color)
        embed.set_footer(text=f"Total Terkumpul: Rp {list_data.get('collected', 0):,}")
        
        new_msg = await channel.send(embed=embed)
        list_data['message_id'] = new_msg.id
        self.save_data()

    async def process_payment(self, interaction, guild_id, list_unique_id, idx, nominal):
        sid = str(guild_id)
        data = self.data[sid]
        
        participant = data['lists'][list_unique_id]['participants'][idx]
        participant['paid'] = True
        participant['paid_amount'] = nominal
        
        if 'collected' not in data['lists'][list_unique_id]:
            data['lists'][list_unique_id]['collected'] = 0
        data['lists'][list_unique_id]['collected'] += nominal
        
        data['balance'] += nominal
        
        log_msg = f"Pembayaran {participant['name']} ({data['lists'][list_unique_id]['title']})"
        data['history'].append({
            "type": "IN", "desc": log_msg, "amount": nominal, "date": str(datetime.now())
        })
        
        self.save_data()
        await self.resend_list_message(interaction.guild, list_unique_id)
        await interaction.response.send_message(f"Berhasil! **{participant['name']}** lunas Rp {nominal:,} ✅", ephemeral=True)
        
        if data.get('log_channel'):
            c = self.bot.get_channel(data['log_channel'])
            if c:
                e = discord.Embed(title="💰 Uang Masuk", color=discord.Color.green())
                e.add_field(name="Dari", value=participant['name'])
                e.add_field(name="Nominal", value=f"Rp {nominal:,}")
                e.add_field(name="List", value=data['lists'][list_unique_id]['title'])
                await c.send(embed=e)

    async def process_transaction(self, interaction, guild_id, amount, reason, type):
        sid = str(guild_id)
        data = self.data[sid]

        if type == "OUT":
            if data['balance'] < amount:
                await interaction.response.send_message(f"Saldo tidak cukup! Saldo saat ini: Rp {data['balance']:,}", ephemeral=True)
                return
            data['balance'] -= amount
            title = "💸 Pengeluaran (Cashout)"
            color = discord.Color.red()
            hist_type = "OUT"
        else:
            data['balance'] += amount
            title = "💰 Tambah Saldo (Manual)"
            color = discord.Color.blue()
            hist_type = "IN"

        data['history'].append({
            "type": hist_type, "desc": reason, "amount": amount, "date": str(datetime.now())
        })
        self.save_data()

        embed = discord.Embed(title=title, color=color)
        embed.add_field(name="Nominal", value=f"Rp {amount:,}")
        embed.add_field(name="Keterangan", value=reason)
        embed.add_field(name="Sisa Saldo", value=f"Rp {data['balance']:,}")
        embed.set_footer(text=f"Admin: {interaction.user.name}")

        await interaction.response.send_message("Transaksi berhasil dicatat.", ephemeral=True)

        if data.get('log_channel'):
            c = self.bot.get_channel(data['log_channel'])
            if c: await c.send(embed=embed)
        else:
            await interaction.channel.send(embed=embed, delete_after=10)

    async def execute_add_names(self, interaction, guild_id, list_unique_id, names):
        sid = str(guild_id)
        data = self.data[sid]
        list_data = data['lists'][list_unique_id]

        name_list = [n.strip() for n in names.replace(',', ' ').split() if n.strip()]
        for n in name_list:
            list_data['participants'].append({"name": n, "paid": False, "paid_amount": 0})
        
        self.save_data()
        msg = f"Berhasil menambahkan peserta ke **{list_data['title']}**"
        
        if isinstance(interaction, discord.Interaction):
            await interaction.response.send_message(msg, ephemeral=True)
            await self.resend_list_message(interaction.guild, list_unique_id)
        else:
            await self.resend_list_message(interaction.guild, list_unique_id)

    async def execute_close_list(self, interaction, guild_id, list_unique_id):
        sid = str(guild_id)
        data = self.data[sid]
        list_data = data['lists'][list_unique_id]
        
        list_data['status'] = 'closed'
        self.save_data()
        
        await interaction.response.send_message(f"List **{list_data['title']}** berhasil ditutup.", ephemeral=True)
        await self.resend_list_message(interaction.guild, list_unique_id)

    @commands.command(name="setadminrole")
    @commands.has_permissions(administrator=True)
    async def set_admin_role(self, ctx, role: discord.Role):
        await self.delete_user_message(ctx)
        sid = str(ctx.guild.id)
        data = self.get_data(ctx.guild.id)
        data['admin_role'] = role.id
        self.save_data()
        await ctx.send(f"✅ Role Admin Keuangan diatur ke: {role.mention}", delete_after=5)

    @commands.command(name="setfinance")
    async def set_finance_channel(self, ctx, channel: discord.TextChannel):
        await self.delete_user_message(ctx)
        if not self.check_role(ctx):
            await ctx.send("🚫 Akses ditolak.", delete_after=3)
            return
        sid = str(ctx.guild.id)
        data = self.get_data(ctx.guild.id)
        data['log_channel'] = channel.id
        self.save_data()
        await ctx.send(f"Channel keuangan diatur ke {channel.mention}", delete_after=5)

    @commands.command(name="pt")
    async def create_list(self, ctx, *, title: str):
        await self.delete_user_message(ctx)
        sid = str(ctx.guild.id)
        self.get_data(ctx.guild.id)

        unique_id = str(int(time.time())) + str(ctx.channel.id)[-4:]
        embed = discord.Embed(title=title, description="(List Kosong)", color=discord.Color.green())
        embed.set_footer(text="Gunakan !ln <nama> untuk tambah peserta")
        msg = await ctx.send(embed=embed)

        self.data[sid]['lists'][unique_id] = {
            "title": title, "participants": [], "channel_id": ctx.channel.id,
            "message_id": msg.id, "status": "open", "collected": 0,
            "created_at": str(datetime.now())
        }
        self.save_data()

    @commands.command(name="ln")
    async def add_name(self, ctx, *, names: str):
        await self.delete_user_message(ctx)
        sid = str(ctx.guild.id)
        data = self.get_data(ctx.guild.id)
        
        active_lists = []
        for uid, ldata in data['lists'].items():
            if ldata['channel_id'] == ctx.channel.id and ldata['status'] == 'open':
                active_lists.append((uid, ldata))
        
        if not active_lists:
            await ctx.send("Tidak ada list aktif.", delete_after=5); return

        if len(active_lists) == 1:
            await self.execute_add_names(ctx, ctx.guild.id, active_lists[0][0], names)
        else:
            view = ListSelectView(active_lists, names, self, ctx.guild.id)
            await ctx.send("Pilih list tujuan:", view=view, delete_after=60)

    @commands.command(name="masuk")
    async def manual_income_command(self, ctx):
        await self.delete_user_message(ctx)
        if not self.check_role(ctx):
            await ctx.send("🚫 Akses ditolak.", delete_after=3); return
        
        await ctx.send("Silakan isi data pemasukan manual:", view=TriggerIncomeView(self, ctx.guild.id), delete_after=60)

    @commands.command(name="out")
    async def cashout_command(self, ctx):
        await self.delete_user_message(ctx)
        if not self.check_role(ctx):
            await ctx.send("🚫 Akses ditolak.", delete_after=3); return
        
        await ctx.send("Silakan isi data pengeluaran:", view=TriggerCashoutView(self, ctx.guild.id), delete_after=60)

    @commands.command(name="tutup")
    async def close_list_command(self, ctx):
        await self.delete_user_message(ctx)
        if not self.check_role(ctx):
            await ctx.send("🚫 Akses ditolak.", delete_after=3); return

        sid = str(ctx.guild.id)
        data = self.get_data(ctx.guild.id)

        active_lists = []
        for uid, ldata in data['lists'].items():
            if ldata['channel_id'] == ctx.channel.id and ldata['status'] == 'open':
                active_lists.append((uid, ldata))
        
        if not active_lists:
            await ctx.send("Tidak ada list aktif.", delete_after=3); return

        if len(active_lists) == 1:
            await self.execute_close_list(ctx, ctx.guild.id, active_lists[0][0])
        else:
            view = CloseListView(active_lists, self, ctx.guild.id)
            await ctx.send("Pilih list yang mau ditutup:", view=view, delete_after=60)

    @commands.command(name="hapus")
    async def remove_participant(self, ctx, *, name_query: str):
        await self.delete_user_message(ctx)
        if not self.check_role(ctx):
            await ctx.send("🚫 Akses ditolak.", delete_after=3); return
        
        sid = str(ctx.guild.id)
        data = self.get_data(ctx.guild.id)
        sorted_lists = sorted(
            [ (uid, l) for uid, l in data['lists'].items() if l['channel_id'] == ctx.channel.id and l['status'] == 'open' ],
            key=lambda x: x[1]['created_at'], reverse=True
        )
        if not sorted_lists: await ctx.send("Tidak ada list aktif.", delete_after=3); return

        target_uid, target_list = sorted_lists[0]
        participants = target_list['participants']
        found = False
        
        for i, p in enumerate(participants):
            if name_query.lower() in p['name'].lower():
                removed = participants.pop(i)
                found = True
                if removed['paid']:
                    self.data[sid]['balance'] -= removed['paid_amount']
                    target_list['collected'] -= removed['paid_amount']
                    self.data[sid]['history'].append({
                        "type": "CORRECTION", "desc": f"Hapus peserta {removed['name']}",
                        "amount": -removed['paid_amount'], "date": str(datetime.now())
                    })
                break
        
        if found:
            self.save_data()
            await self.resend_list_message(ctx.guild, target_uid)
        else:
            await ctx.send(f"Nama '{name_query}' tidak ditemukan.", delete_after=3)

    @commands.command(name="bayar")
    async def pay_status(self, ctx):
        await self.delete_user_message(ctx)
        sid = str(ctx.guild.id)
        data = self.get_data(ctx.guild.id)
        active_lists = []
        for uid, ldata in data['lists'].items():
            if ldata['channel_id'] == ctx.channel.id and ldata['status'] == 'open':
                active_lists.append((uid, ldata))

        if not active_lists: await ctx.send("Tidak ada list aktif.", delete_after=3); return
        uid, list_data = active_lists[-1] 
        unpaid = [(i, p) for i, p in enumerate(list_data['participants']) if not p['paid']]

        if not unpaid: await ctx.send("Semua lunas! 🎉", delete_after=5); return
        view = PayView(uid, unpaid[:25], self, ctx.guild.id)
        await ctx.send(f"Pembayaran: **{list_data['title']}**", view=view, delete_after=60)

    @commands.command(name="editbayar")
    async def edit_payment(self, ctx, amount_str: str, *, name_query: str):
        await self.delete_user_message(ctx)
        if not self.check_role(ctx): await ctx.send("🚫 Akses ditolak.", delete_after=3); return

        # FIX: Manual parsing string to int to handle dots/commas
        try:
            amount = int(amount_str.replace('.', '').replace(',', ''))
        except ValueError:
            await ctx.send("Format nominal salah. Gunakan angka.", delete_after=3)
            return

        sid = str(ctx.guild.id)
        data = self.get_data(ctx.guild.id)
        sorted_lists = sorted(
            [ (uid, l) for uid, l in data['lists'].items() if l['channel_id'] == ctx.channel.id and l['status'] == 'open' ],
            key=lambda x: x[1]['created_at'], reverse=True
        )
        if not sorted_lists: await ctx.send("Tidak ada list aktif.", delete_after=3); return

        target_uid, target_list = sorted_lists[0]
        found_p = None
        for p in target_list['participants']:
            if name_query.lower() in p['name'].lower():
                found_p = p; break
        
        if not found_p: await ctx.send(f"Peserta '{name_query}' tidak ditemukan.", delete_after=3); return
        if not found_p['paid']: await ctx.send("Peserta ini belum bayar.", delete_after=3); return

        diff = amount - found_p['paid_amount']
        found_p['paid_amount'] = amount
        target_list['collected'] += diff
        self.data[sid]['balance'] += diff
        self.data[sid]['history'].append({
            "type": "CORRECTION", "desc": f"Revisi {found_p['name']}",
            "amount": diff, "date": str(datetime.now())
        })
        
        self.save_data()
        await self.resend_list_message(ctx.guild, target_uid)
        await ctx.send(f"Revisi sukses: {found_p['name']} kini Rp {amount:,}", delete_after=5)

    @commands.command(name="tagih")
    async def remind_payment(self, ctx):
        await self.delete_user_message(ctx)
        if not self.check_role(ctx): await ctx.send("🚫 Akses ditolak.", delete_after=3); return
        sid = str(ctx.guild.id); data = self.get_data(ctx.guild.id)
        sorted_lists = sorted(
            [ (uid, l) for uid, l in data['lists'].items() if l['channel_id'] == ctx.channel.id and l['status'] == 'open' ],
            key=lambda x: x[1]['created_at'], reverse=True
        )
        if not sorted_lists: await ctx.send("Tidak ada list aktif.", delete_after=3); return
        target_uid, target_list = sorted_lists[0]
        unpaid = [p['name'] for p in target_list['participants'] if not p['paid']]
        
        if not unpaid: await ctx.send("Semua aman!", delete_after=5); return
        msg = f"📢 **TAGIHAN: {target_list['title']}**\n\n" + "\n".join([f"👉 {n}" for n in unpaid])
        await ctx.send(msg)

    @commands.command(name="export")
    async def export_data(self, ctx):
        await self.delete_user_message(ctx)
        if not self.check_role(ctx): await ctx.send("🚫 Akses ditolak.", delete_after=3); return
        sid = str(ctx.guild.id); data = self.get_data(ctx.guild.id)
        sorted_lists = sorted(
            [ (uid, l) for uid, l in data['lists'].items() if l['channel_id'] == ctx.channel.id ],
            key=lambda x: x[1]['created_at'], reverse=True
        )
        if not sorted_lists: await ctx.send("Data kosong.", delete_after=3); return
        target_uid, target_list = sorted_lists[0]
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Nama', 'Status', 'Nominal', 'Judul List'])
        for p in target_list['participants']:
            writer.writerow([p['name'], "Lunas" if p['paid'] else "Belum", p['paid_amount'], target_list['title']])
        output.seek(0)
        await ctx.send(file=discord.File(fp=io.BytesIO(output.getvalue().encode()), filename=f"Report.csv"))

    @commands.command(name="dompet")
    async def wallet_info(self, ctx):
        await self.delete_user_message(ctx)
        sid = str(ctx.guild.id); data = self.get_data(ctx.guild.id)
        embed = discord.Embed(title="💰 Keuangan", color=discord.Color.gold())
        embed.add_field(name="Saldo Total", value=f"Rp {data['balance']:,}", inline=False)
        hist = ""
        for h in reversed(data['history'][-10:]):
            icon = "🟢" if h['type'] in ["IN", "IN_MANUAL"] else "🔴"
            hist += f"{icon} **Rp {h['amount']:,}** - {h['desc']}\n"
        embed.add_field(name="Riwayat Terakhir", value=hist if hist else "Kosong", inline=False)
        await ctx.send(embed=embed, delete_after=60)

async def setup(bot):
    await bot.add_cog(FinanceBot(bot))
