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
intents.message_content = True
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
        c.execute('''CREATE TABLE IF NOT EXISTS blacklist_servers (
                        server_id TEXT PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS shame_settings (
                        guild_id TEXT PRIMARY KEY,
                        channel_id TEXT,
                        message TEXT DEFAULT "User {user} is flagged! Watch out!",
                        frequency INTEGER DEFAULT 5)''')

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
    await tree.sync()
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

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    shame = db_query("SELECT channel_id, message, frequency FROM shame_settings WHERE guild_id=?", (str(message.guild.id),), fetchone=True)
    if shame:
        channel_id, shame_msg, frequency = shame
        count_key = f"shame_count_{message.guild.id}_{message.author.id}"
        if not hasattr(bot, "shame_counters"):
            bot.shame_counters = {}
        bot.shame_counters[count_key] = bot.shame_counters.get(count_key, 0) + 1

        if bot.shame_counters[count_key] % frequency == 0:
            if is_user_banned(message.author.id):
                channel = bot.get_channel(int(channel_id))
                if channel:
                    try:
                        await channel.send(shame_msg.replace("{user}", message.author.mention))
                    except Exception as e:
                        logging.error(f"Failed to send shame message: {e}")

    await bot.process_commands(message)

# Slash Commands
@tree.command(name="set_shame_channel", description="Set the public shaming channel and message.")
@app_commands.describe(channel="Channel for shame messages", message="Custom message, use {user} as placeholder", frequency="How often to shame")
async def set_shame(interaction: discord.Interaction, channel: discord.TextChannel, message: str, frequency: int = 5):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need to be an administrator to use this.", ephemeral=True)
        return
    db_query("INSERT OR REPLACE INTO shame_settings (guild_id, channel_id, message, frequency) VALUES (?, ?, ?, ?)",
             (str(interaction.guild.id), str(channel.id), message, frequency))
    await interaction.response.send_message(f"Public shaming set to {channel.mention} every {frequency} messages.")

keep_alive()

# Run the bot using token from environment variables
bot.run(os.getenv('DISCORD_BOT_TOKEN'))
