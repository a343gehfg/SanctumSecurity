import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import os
from dotenv import load_dotenv
from datetime import datetime

# Load .env
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OWNER_ID = 1053047461280759860  # Replace with your Discord user ID
SUPPORT_INVITE = "https://discord.gg/cWNVQDejPE"  # Update with your server

# Set up bot
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
DB_FILE = "banlist.db"

# DB Setup
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
        c.execute('''CREATE TABLE IF NOT EXISTS blacklisted_servers (
                        server_id TEXT PRIMARY KEY)''')
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

# Core Functions
def is_user_flagged(user_id):
    return db_query("SELECT reason FROM banned_users WHERE user_id=?", (str(user_id),), fetchone=True)

def get_user_details(user_id):
    return db_query("SELECT reason, added_by, timestamp FROM banned_users WHERE user_id=?", (str(user_id),), fetchone=True)

def is_autoban_enabled(server_id):
    return db_query("SELECT 1 FROM autoban_servers WHERE server_id=?", (str(server_id),), fetchone=True) is not None

def add_flagged_user(user_id, reason, added_by):
    timestamp = datetime.utcnow().isoformat()
    db_query("INSERT OR REPLACE INTO banned_users (user_id, reason, added_by, timestamp) VALUES (?, ?, ?, ?)",
             (str(user_id), reason, str(added_by), timestamp))

def remove_flagged_user(user_id):
    db_query("DELETE FROM banned_users WHERE user_id=?", (str(user_id),))

# Slash Commands
@tree.command(name="flag", description="Flag a user globally.")
@app_commands.describe(user="User to flag", reason="Reason for flagging")
async def flag_user(interaction: discord.Interaction, user: discord.User, reason: str):
    add_flagged_user(user.id, reason, interaction.user.id)
    await interaction.response.send_message(f"✅ {user.mention} has been flagged for: {reason}", ephemeral=True)

@tree.command(name="unflag", description="Unflag a user (Owner only)")
@app_commands.describe(user="User to unflag")
async def unflag_user(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("❌ Only the bot owner can unflag users.", ephemeral=True)
    remove_flagged_user(user.id)
    await interaction.response.send_message(f"✅ {user.mention} has been unflagged.", ephemeral=True)

@tree.command(name="listflags", description="Show all globally flagged users.")
async def list_flags(interaction: discord.Interaction):
    data = db_query("SELECT user_id, reason FROM banned_users", fetchall=True)
    if not data:
        await interaction.response.send_message("✅ No users are flagged.", ephemeral=True)
        return

    embed = discord.Embed(title="Global Flag List", color=discord.Color.red())
    for uid, reason in data[:20]:  # Limit to 20 entries for now
        embed.add_field(name=uid, value=reason, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="serverflags", description="Show flagged users in this server.")
async def server_flags(interaction: discord.Interaction):
    members = interaction.guild.members
    flagged = []
    for member in members:
        if is_user_flagged(member.id):
            flagged.append((member.id, is_user_flagged(member.id)[0]))

    if not flagged:
        await interaction.response.send_message("✅ No flagged users in this server.", ephemeral=True)
        return

    embed = discord.Embed(title="Flagged Users In This Server", color=discord.Color.orange())
    for uid, reason in flagged[:20]:  # Limit to 20 entries
        embed.add_field(name=str(uid), value=reason, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="search", description="Search if a user is flagged.")
@app_commands.describe(user="User to search")
async def search(interaction: discord.Interaction, user: discord.User):
    details = get_user_details(user.id)
    if not details:
        await interaction.response.send_message(f"✅ {user.mention} is not flagged.", ephemeral=True)
    else:
        reason, added_by, timestamp = details
        embed = discord.Embed(title="User Flag Info", color=discord.Color.red())
        embed.add_field(name="User", value=str(user), inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Flagged By", value=f"<@{added_by}>", inline=False)
        embed.add_field(name="Time", value=timestamp, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="autoban", description="Enable or disable auto-ban for flagged users.")
@app_commands.describe(mode="Enable or disable")
async def autoban(interaction: discord.Interaction, mode: str):
    sid = str(interaction.guild.id)
    if mode.lower() == "enable":
        db_query("INSERT OR REPLACE INTO autoban_servers (server_id) VALUES (?)", (sid,))
        await interaction.response.send_message("✅ AutoBan enabled for this server.", ephemeral=True)
    elif mode.lower() == "disable":
        db_query("DELETE FROM autoban_servers WHERE server_id=?", (sid,))
        await interaction.response.send_message("✅ AutoBan disabled for this server.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Please specify either 'enable' or 'disable'.", ephemeral=True)

@tree.command(name="logs", description="View all flagged logs (Owner only).")
async def logs(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("❌ Only the owner can view logs.", ephemeral=True)
    data = db_query("SELECT user_id, reason, timestamp FROM banned_users", fetchall=True)
    embed = discord.Embed(title="Global Flag Logs", color=discord.Color.dark_red())
    for uid, reason, time in data[:20]:
        embed.add_field(name=f"{uid} at {time}", value=reason, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="serverlogs", description="Show flagged user logs for this server.")
async def server_logs(interaction: discord.Interaction):
    members = interaction.guild.members
    logs = []
    for member in members:
        details = get_user_details(member.id)
        if details:
            reason, added_by, time = details
            logs.append((member.id, reason, added_by, time))

    if not logs:
        await interaction.response.send_message("✅ No logs for this server.", ephemeral=True)
        return

    embed = discord.Embed(title="Server Flag Logs", color=discord.Color.teal())
    for uid, reason, added_by, time in logs[:20]:
        embed.add_field(name=f"{uid} at {time}", value=f"{reason} (by <@{added_by}>)", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="support", description="Get support server invite link.")
async def support(interaction: discord.Interaction):
    await interaction.response.send_message(f"🔗 Support Server: {SUPPORT_INVITE}", ephemeral=True)

@tree.command(name="help", description="List all commands.")
async def help_cmd(interaction: discord.Interaction):
    help_text = """
**/flag user reason** – Flag a user globally  
**/unflag user** – Remove a flagged user (owner only)  
**/listflags** – View all flagged users  
**/serverflags** – View flagged users in your server  
**/search user** – See if a user is flagged  
**/autoban enable/disable** – Auto-ban flagged users that join  
**/logs** – View global logs (owner only)  
**/serverlogs** – View flag logs in your server  
**/support** – Support server invite  
**/help** – This command
"""
    await interaction.response.send_message(help_text, ephemeral=True)

# Auto-ban flagged users on join
@bot.event
async def on_member_join(member):
    if is_autoban_enabled(str(member.guild.id)):
        reason = is_user_flagged(member.id)
        if reason:
            try:
                await member.ban(reason=f"Flagged: {reason}")
            except Exception as e:
                print(f"Ban failed: {e}")

@bot.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Protecting Kids Globally"))

