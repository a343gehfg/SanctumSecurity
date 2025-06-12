import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from datetime import datetime
import os
from dotenv import load_dotenv
from keep_alive import keep_alive  # If you use replit or hosting keep_alive.py

# Load .env file
load_dotenv()

# Constants
OWNER_ID = 1053047461280759860  # Replace with your user ID
GUILD_ID = 1377401935367508110  # Your test server ID
DB_FILE = "banlist.db"

# Bot setup
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Database init
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS banned_users (
            user_id TEXT PRIMARY KEY,
            reason TEXT,
            added_by TEXT,
            timestamp TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS autoban_servers (
            server_id TEXT PRIMARY KEY)""")
init_db()

# DB helper
def db_query(query, params=(), fetch=False, one=False):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()
        if fetch:
            return c.fetchone() if one else c.fetchall()

# Flag logic
def is_user_flagged(uid): return db_query("SELECT * FROM banned_users WHERE user_id=?", (str(uid),), fetch=True, one=True)
def is_autoban_enabled(gid): return db_query("SELECT * FROM autoban_servers WHERE server_id=?", (str(gid),), fetch=True, one=True)

# Bot Ready
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    await bot.change_presence(activity=discord.Game(name="Protecting Kids"))
    print(f"Logged in as {bot.user} | Watching {len(bot.guilds)} servers.")

# Autoban on join
@bot.event
async def on_member_join(member):
    if is_autoban_enabled(member.guild.id):
        result = is_user_flagged(member.id)
        if result:
            try:
                await member.send(f"You were auto-banned from {member.guild.name}.\nReason: {result[1]}")
            except: pass
            try:
                await member.ban(reason="Flagged User")
                print(f"Auto-banned {member}")
            except Exception as e:
                print(f"Error banning {member}: {e}")

# /flag
@tree.command(name="flag", description="Flag a user", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="User to flag", reason="Reason for flagging")
async def flag(interaction: discord.Interaction, user: discord.User, reason: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Only the bot owner can use this command.", ephemeral=True)
        return

    db_query("INSERT OR REPLACE INTO banned_users VALUES (?, ?, ?, ?)", (
        str(user.id), reason, str(interaction.user.id), datetime.utcnow().isoformat()
    ))
    try: await user.send(f"You’ve been globally flagged.\nReason: `{reason}`")
    except: pass

    embed = discord.Embed(title="User Flagged", color=discord.Color.red())
    embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text=f"Flagged by {interaction.user}")
    await interaction.response.send_message(embed=embed)

# /unflag
@tree.command(name="unflag", description="Unflag a user", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="User to unflag")
async def unflag(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Only the bot owner can unflag.", ephemeral=True)
        return

    db_query("DELETE FROM banned_users WHERE user_id=?", (str(user.id),))
    await interaction.response.send_message(f"{user} has been unflagged.")

# /listflags
@tree.command(name="listflags", description="List all flagged users", guild=discord.Object(id=GUILD_ID))
async def listflags(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Only the bot owner can use this.", ephemeral=True)
        return

    users = db_query("SELECT * FROM banned_users", fetch=True)
    if not users:
        await interaction.response.send_message("No users flagged.")
        return

    embed = discord.Embed(title="Flagged Users", color=discord.Color.orange())
    for uid, reason, added_by, timestamp in users[:25]:  # Discord embed limit
        embed.add_field(
            name=f"User ID: {uid}",
            value=f"Reason: {reason}\nAdded By: <@{added_by}>\nTime: {timestamp}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# /serverflags
@tree.command(name="serverflags", description="List flagged users in this server", guild=discord.Object(id=GUILD_ID))
async def serverflags(interaction: discord.Interaction):
    members = interaction.guild.members
    flagged = []
    for member in members:
        if is_user_flagged(member.id):
            flagged.append(member)

    if not flagged:
        await interaction.response.send_message("No flagged users in this server.")
        return

    embed = discord.Embed(title="Flagged Users in This Server", color=discord.Color.red())
    for user in flagged:
        reason = is_user_flagged(user.id)[1]
        embed.add_field(name=f"{user}", value=f"Reason: {reason}", inline=False)
    await interaction.response.send_message(embed=embed)

# /search
@tree.command(name="search", description="Search if a user is flagged", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="User to search")
async def search(interaction: discord.Interaction, user: discord.User):
    result = is_user_flagged(user.id)
    if result:
        embed = discord.Embed(title="Flagged User", color=discord.Color.red())
        embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=False)
        embed.add_field(name="Reason", value=result[1], inline=False)
        embed.add_field(name="Added By", value=f"<@{result[2]}>", inline=False)
        embed.set_footer(text=f"Flagged at {result[3]}")
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("User is not flagged.")

# /autoban enable
@tree.command(name="autoban", description="Toggle autoban on or off", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(option="enable or disable")
async def autoban(interaction: discord.Interaction, option: str):
    if option not in ["enable", "disable"]:
        await interaction.response.send_message("Usage: /autoban enable OR /autoban disable", ephemeral=True)
        return

    sid = str(interaction.guild.id)
    if option == "enable":
        db_query("INSERT OR IGNORE INTO autoban_servers VALUES (?)", (sid,))
        await interaction.response.send_message("AutoBan enabled.")
    else:
        db_query("DELETE FROM autoban_servers WHERE server_id=?", (sid,))
        await interaction.response.send_message("AutoBan disabled.")

# /support
@tree.command(name="support", description="Get support server invite", guild=discord.Object(id=GUILD_ID))
async def support(interaction: discord.Interaction):
    await interaction.response.send_message("Join the support server: https://discord.gg/cWNVQDejPE")

# /help
@tree.command(name="help", description="List available commands", guild=discord.Object(id=GUILD_ID))
async def help_cmd(interaction: discord.Interaction):
    help_text = """
**Available Commands:**
- `/flag user reason` *(Owner only)*
- `/unflag user` *(Owner only)*
- `/listflags` *(Owner only)*
- `/serverflags`
- `/search user`
- `/autoban enable|disable`
- `/support`
- `/help`
"""
    await interaction.response.send_message(help_text)

# Start
keep_alive()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
