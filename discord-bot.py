import sqlite3
import discord
from discord.ext import commands, tasks
from datetime import datetime
import logging

# Logging Configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Bot Configuration
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
DB_FILE = "banlist.db"

# Database Initialization
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS banned_users (
                        user_id TEXT PRIMARY KEY,
                        reason TEXT,
                        added_by TEXT,
                        timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS autoban_servers (
                        server_id TEXT PRIMARY KEY)''')

init_db()

# DB Helper Functions
def db_query(query, params=(), fetchone=False, fetchall=False):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()
        if fetchone:
            return c.fetchone()
        elif fetchall:
            return c.fetchall()

# Core Logic
def is_user_banned(user_id):
    result = db_query("SELECT reason FROM banned_users WHERE user_id=?", (str(user_id),), fetchone=True)
    return result[0] if result else None

def get_user_details(user_id):
    return db_query("SELECT reason, added_by, timestamp FROM banned_users WHERE user_id=?", (str(user_id),), fetchone=True)

def is_autoban_enabled(server_id):
    return db_query("SELECT 1 FROM autoban_servers WHERE server_id=?", (str(server_id),), fetchone=True) is not None

def add_flagged_user(user_id, reason, added_by):
    timestamp = datetime.utcnow().isoformat()
    db_query("INSERT OR REPLACE INTO banned_users (user_id, reason, added_by, timestamp) VALUES (?, ?, ?, ?)",
             (str(user_id), reason, added_by, timestamp))

# Events
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="protecting kids"))

@bot.event
async def on_member_join(member):
    if is_autoban_enabled(member.guild.id):
        reason = is_user_banned(member.id)
        if reason:
            try:
                await member.ban(reason=f"Auto-flagged: {reason}")
                logging.info(f"Auto-banned {member} in {member.guild.name} for: {reason}")
            except discord.Forbidden:
                logging.warning(f"Missing permissions to ban {member} in {member.guild.name}")
            except Exception as e:
                logging.error(f"Failed to auto-ban {member}: {e}")

# Help Command
@bot.command()
async def help(ctx):
    embed = discord.Embed(title="FlagShield Bot Help", color=discord.Color.blurple())
    commands_info = {
        "!enable_autoban": "Enable auto-banning flagged users on join.",
        "!disable_autoban": "Disable autoban.",
        "!add_flag <user_id> <reason>": "Globally flag a user.",
        "!remove_flag <user_id>": "Remove flag from user.",
        "!check_flag <user_id>": "Check if a user is flagged.",
        "!list_flagged": "List flagged users in server.",
        "!ban_flagged": "Ban flagged users in server."
    }
    for cmd, desc in commands_info.items():
        embed.add_field(name=cmd, value=desc, inline=False)
    await ctx.send(embed=embed)

# Commands
@bot.command()
@commands.has_permissions(administrator=True)
async def enable_autoban(ctx):
    db_query("INSERT OR REPLACE INTO autoban_servers (server_id) VALUES (?)", (str(ctx.guild.id),))
    await ctx.send("Autoban has been **enabled**.")

@bot.command()
@commands.has_permissions(administrator=True)
async def disable_autoban(ctx):
    db_query("DELETE FROM autoban_servers WHERE server_id=?", (str(ctx.guild.id),))
    await ctx.send("Autoban has been **disabled**.")

@bot.command()
@commands.has_permissions(administrator=True)
async def list_flagged(ctx):
    flagged = []
    for member in ctx.guild.members:
        reason = is_user_banned(member.id)
        if reason:
            flagged.append(f"`{member}` ({member.id}) - {reason}")
    if flagged:
        await ctx.send("**Flagged users in this server:**\n" + "\n".join(flagged))
    else:
        await ctx.send("No flagged users in this server.")

@bot.command()
@commands.has_permissions(administrator=True)
async def ban_flagged(ctx):
    count = 0
    for member in ctx.guild.members:
        reason = is_user_banned(member.id)
        if reason:
            try:
                await member.ban(reason=f"Flagged: {reason}")
                count += 1
            except discord.Forbidden:
                logging.warning(f"Permission issue banning {member}")
            except Exception as e:
                logging.error(f"Error banning flagged user {member}: {e}")
    await ctx.send(f"Banned {count} flagged user(s).")

@bot.command()
@commands.has_permissions(administrator=True)
async def add_flag(ctx, user_id: int, *, reason: str = "No reason provided"):
    add_flagged_user(user_id, reason, str(ctx.author))
    await ctx.send(f"User `{user_id}` has been **flagged** for: *{reason}*.")
    logging.info(f"Flagged {user_id} for: {reason} by {ctx.author}")

@bot.command()
@commands.has_permissions(administrator=True)
async def remove_flag(ctx, user_id: int):
    db_query("DELETE FROM banned_users WHERE user_id=?", (str(user_id),))
    await ctx.send(f"User `{user_id}` has been **unflagged**.")
    logging.info(f"Unflagged {user_id} by {ctx.author}")

@bot.command()
@commands.has_permissions(administrator=True)
async def check_flag(ctx, user_id: int):
    result = get_user_details(user_id)
    if result:
        reason, added_by, timestamp = result
        embed = discord.Embed(title="Flagged User Info", color=discord.Color.red())
        embed.add_field(name="User ID", value=user_id, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Flagged By", value=added_by, inline=True)
        embed.set_footer(text=f"Flagged on {timestamp}")
        await ctx.send(embed=embed)
    else:
        await ctx.send("This user is **not flagged**.")

# bot.run("MTM3NTU3MjQxNjc3MTY1MzY0Mg.GN4i2L.KsinN6NQxmKU8K13Xr2B2ezhkJ0cGSghVPEckQ")
