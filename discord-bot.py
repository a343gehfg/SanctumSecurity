# Fixed version of your bot code with the integer bug addressed
# and global blacklist restricted to only the bot owner

import sqlite3
import discord
import os
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import logging
from dotenv import load_dotenv
from keep_alive import keep_alive

# Load environment variables
load_dotenv()

# Logging Configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Bot Configuration
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
DB_FILE = "banlist.db"
OWNER_ID = 1053047461280759860  # Replace with your actual Discord user ID

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
        c.execute('''CREATE TABLE IF NOT EXISTS blacklisted_servers (
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

def is_server_blacklisted(server_id):
    return db_query("SELECT 1 FROM blacklisted_servers WHERE server_id=?", (str(server_id),), fetchone=True) is not None

def add_flagged_user(user_id, reason, added_by):
    timestamp = datetime.utcnow().isoformat()
    db_query("INSERT OR REPLACE INTO banned_users (user_id, reason, added_by, timestamp) VALUES (?, ?, ?, ?)",
             (str(user_id), reason, added_by, timestamp))

# Permissions check
def is_admin(interaction):
    return interaction.user.guild_permissions.administrator or interaction.user.id == OWNER_ID

def is_owner(interaction):
    return interaction.user.id == OWNER_ID

# Events
@bot.event
async def on_ready():
    await tree.sync()
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Protect Children Simulator"))

    # Diagnostics
    flagged_count = db_query("SELECT COUNT(*) FROM banned_users", fetchone=True)[0]
    server_count = len(bot.guilds)
    logging.info(f"Connected to {server_count} servers. {flagged_count} users flagged.")

@bot.event
async def on_member_join(member):
    if is_server_blacklisted(member.guild.id):
        try:
            await member.ban(reason="Server is blacklisted")
            logging.info(f"Banned {member} from blacklisted server {member.guild.name}")
            return
        except Exception as e:
            logging.error(f"Error banning from blacklisted server: {e}")

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

# Slash Commands
@tree.command(name="enable_autoban", description="Enable auto-banning flagged users on join.")
async def enable_autoban(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("You need to be an administrator to use this.", ephemeral=True)
        return
    db_query("INSERT OR REPLACE INTO autoban_servers (server_id) VALUES (?)", (str(interaction.guild.id),))
    await interaction.response.send_message("Autoban has been **enabled**.")

@tree.command(name="disable_autoban", description="Disable auto-banning flagged users.")
async def disable_autoban(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("You need to be an administrator to use this.", ephemeral=True)
        return
    db_query("DELETE FROM autoban_servers WHERE server_id=?", (str(interaction.guild.id),))
    await interaction.response.send_message("Autoban has been **disabled**.")

@tree.command(name="add_flag", description="Globally flag a user.")
@app_commands.describe(user_id="User ID to flag", reason="Reason for flagging")
async def add_flag(interaction: discord.Interaction, user_id: int, reason: str = "No reason provided"):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return
    add_flagged_user(user_id, reason, str(interaction.user))
    await interaction.response.send_message(f"✅ User `{user_id}` has been **flagged** for: *{reason}*.")
    logging.info(f"Flagged {user_id} for: {reason} by {interaction.user}")

@tree.command(name="mass_flag", description="Flag multiple user IDs at once.")
@app_commands.describe(user_ids="Comma-separated user IDs", reason="Reason for flagging")
async def mass_flag(interaction: discord.Interaction, user_ids: str, reason: str = "No reason provided"):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return
    ids = [str(uid.strip()) for uid in user_ids.split(",") if uid.strip().isdigit()]
    count = 0
    for uid in ids:
        add_flagged_user(uid, reason, str(interaction.user))
        count += 1
    await interaction.response.send_message(f"✅ {count} users flagged for: *{reason}*.")
    logging.info(f"Mass flagged {count} users by {interaction.user}")

@tree.command(name="remove_flag", description="Remove a flag from a user.")
@app_commands.describe(user_id="User ID to unflag")
async def remove_flag(interaction: discord.Interaction, user_id: int):
    if not is_admin(interaction):
        await interaction.response.send_message("You need to be an administrator to use this.", ephemeral=True)
        return
    db_query("DELETE FROM banned_users WHERE user_id=?", (str(user_id),))
    await interaction.response.send_message(f"User `{user_id}` has been **unflagged**.")
    logging.info(f"Unflagged {user_id} by {interaction.user}")

@tree.command(name="check_flag", description="Check if a user is flagged.")
@app_commands.describe(user_id="User ID to check")
async def check_flag(interaction: discord.Interaction, user_id: int):
    result = get_user_details(user_id)
    if result:
        reason, added_by, timestamp = result
        embed = discord.Embed(title="Flagged User Info", color=discord.Color.red(), timestamp=datetime.utcnow())
        embed.add_field(name="User ID", value=user_id, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Flagged By", value=added_by, inline=True)
        embed.set_footer(text=f"Flagged on {timestamp}")
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("This user is **not flagged**.")

@tree.command(name="list_flagged", description="List flagged users in the server.")
async def list_flagged(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("You need to be an administrator to use this.", ephemeral=True)
        return
    flagged = []
    for member in interaction.guild.members:
        reason = is_user_banned(member.id)
        if reason:
            flagged.append(f"`{member}` ({member.id}) - {reason}")
    if flagged:
        await interaction.response.send_message("**Flagged users in this server:**\n" + "\n".join(flagged))
    else:
        await interaction.response.send_message("No flagged users in this server.")

@tree.command(name="ban_flagged", description="Ban all flagged users in the server.")
async def ban_flagged(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("You need to be an administrator to use this.", ephemeral=True)
        return
    count = 0
    for member in interaction.guild.members:
        reason = is_user_banned(member.id)
        if reason:
            try:
                await member.ban(reason=f"Flagged: {reason}")
                count += 1
            except discord.Forbidden:
                logging.warning(f"Permission issue banning {member}")
            except Exception as e:
                logging.error(f"Error banning flagged user {member}: {e}")
    await interaction.response.send_message(f"Banned {count} flagged user(s).")

@tree.command(name="blacklist_server", description="Add a server to the global blacklist.")
@app_commands.describe(server_id="ID of the server to blacklist")
async def blacklist_server(interaction: discord.Interaction, server_id: str):
    if not is_owner(interaction):
        await interaction.response.send_message("Only the owner can blacklist servers.", ephemeral=True)
        return
    if not server_id.isdigit():
        await interaction.response.send_message("❌ Invalid server ID.", ephemeral=True)
        return
    db_query("INSERT OR REPLACE INTO blacklisted_servers (server_id) VALUES (?)", (server_id,))
    await interaction.response.send_message(f"✅ Server `{server_id}` has been blacklisted.")
    logging.info(f"Server {server_id} blacklisted by {interaction.user}")

@tree.command(name="unblacklist_server", description="Remove a server from the global blacklist.")
@app_commands.describe(server_id="ID of the server to unblacklist")
async def unblacklist_server(interaction: discord.Interaction, server_id: str):
    if not is_owner(interaction):
        await interaction.response.send_message("Only the owner can unblacklist servers.", ephemeral=True)
        return
    db_query("DELETE FROM blacklisted_servers WHERE server_id=?", (server_id,))
    await interaction.response.send_message(f"✅ Server `{server_id}` has been removed from the blacklist.")

keep_alive()

# Run the bot using token from environment variables
bot.run(os.getenv('DISCORD_BOT_TOKEN'))
