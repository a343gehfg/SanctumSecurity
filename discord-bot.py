import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from datetime import datetime
import os
import logging
from dotenv import load_dotenv
from keep_alive import keep_alive

# Load environment variables
load_dotenv()

# Bot Setup
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Constants
DB_FILE = "banlist.db"
OWNER_ID = 1053047461280759860
GUILD_ID = YOUR_GUILD_ID_HERE  # ← Replace with your test server ID

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# DB Init
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS banned_users (
                        user_id TEXT PRIMARY KEY,
                        reason TEXT,
                        added_by TEXT,
                        timestamp TEXT)""")
        c.execute("CREATE TABLE IF NOT EXISTS autoban_servers (server_id TEXT PRIMARY KEY)")
        c.execute("CREATE TABLE IF NOT EXISTS blacklisted_servers (server_id TEXT PRIMARY KEY)")

init_db()

# DB Helpers
def db_query(query, params=(), fetchone=False, fetchall=False):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()
        if fetchone:
            return c.fetchone()
        if fetchall:
            return c.fetchall()

# Core Logic
def is_user_banned(user_id):
    result = db_query("SELECT reason FROM banned_users WHERE user_id=?", (str(user_id),), fetchone=True)
    return result[0] if result else None

def get_user_details(user_id):
    return db_query("SELECT reason, added_by, timestamp FROM banned_users WHERE user_id=?", (str(user_id),), fetchone=True)

def is_autoban_enabled(server_id):
    return db_query("SELECT 1 FROM autoban_servers WHERE server_id=?", (str(server_id),), fetchone=True) is not None

def is_server_blacklisted(server_id):
    return db_query("SELECT 1 FROM blacklisted_servers WHERE server_id=?", (str(server_id),), fetchone=True) is not None

def add_flagged_user(user_id, reason, added_by):
    timestamp = datetime.utcnow().isoformat()
    db_query("INSERT OR REPLACE INTO banned_users (user_id, reason, added_by, timestamp) VALUES (?, ?, ?, ?)",
             (str(user_id), reason, added_by, timestamp))

# Ready Event
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Protect Children Simulator"))
    logging.info(f"Connected to {len(bot.guilds)} servers. {db_query('SELECT COUNT(*) FROM banned_users', fetchone=True)[0]} users flagged.")

# Auto-ban logic
@bot.event
async def on_member_join(member):
    if is_server_blacklisted(str(member.guild.id)):
        try:
            await member.ban(reason="Server is blacklisted")
            logging.info(f"Banned {member} from blacklisted server {member.guild.name}")
            return
        except Exception as e:
            logging.error(f"Error banning from blacklisted server: {e}")

    if is_autoban_enabled(str(member.guild.id)):
        reason = is_user_banned(str(member.id))
        if reason:
            try:
                await member.send(f"You were banned from {member.guild.name}.\nReason: {reason}")
            except:
                pass  # Ignore DMs failing
            try:
                await member.ban(reason=f"Auto-flagged: {reason}")
                logging.info(f"Auto-banned {member} in {member.guild.name} for: {reason}")
            except Exception as e:
                logging.error(f"Failed to auto-ban {member}: {e}")

# Slash Command: /flag
@tree.command(name="flag", description="Flag a user", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="User to flag", reason="Reason for flagging")
async def flag(interaction: discord.Interaction, user: discord.User, reason: str):
    if not interaction.user.guild_permissions.administrator and interaction.user.id != OWNER_ID:
        await interaction.response.send_message("You don't have permission to flag users.", ephemeral=True)
        return

    add_flagged_user(user.id, reason, interaction.user.id)

    embed = discord.Embed(title="User Flagged", color=discord.Color.red())
    embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text=f"Flagged by {interaction.user} • UTC")

    try:
        await user.send(f"You’ve been flagged globally.\nReason: `{reason}`")
    except:
        pass  # Fail silently if DMs closed

    await interaction.response.send_message(embed=embed)

# Slash Command: /list_flags
@tree.command(name="list_flags", description="List all flagged users", guild=discord.Object(id=GUILD_ID))
async def list_flags(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("You don't have permission to view flagged users.", ephemeral=True)
        return

    users = db_query("SELECT user_id, reason, added_by, timestamp FROM banned_users", fetchall=True)
    if not users:
        await interaction.response.send_message("No users flagged.")
        return

    embed = discord.Embed(title="Flagged Users", color=discord.Color.orange())
    for uid, reason, added_by, timestamp in users[:25]:  # Discord limit
        embed.add_field(
            name=f"User ID: {uid}",
            value=f"Reason: {reason}\nAdded By: <@{added_by}>\nTime: {timestamp}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# Keep bot alive
keep_alive()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
