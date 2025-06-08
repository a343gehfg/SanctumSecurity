# Updated Sanctum Pro core with slash commands and integer bug fixes (IDs as strings)
# Adds: slash-based wrappers only, RoCleaner import not yet added

import sqlite3
import discord
import os
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import logging
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
DB_FILE = "banlist.db"
OWNER_ID = 1053047461280759860

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

def db_query(query, params=(), fetchone=False, fetchall=False):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()
        if fetchone:
            return c.fetchone()
        elif fetchall:
            return c.fetchall()

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

def is_admin(interaction):
    return interaction.user.guild_permissions.administrator or interaction.user.id == OWNER_ID

def is_owner(interaction):
    return interaction.user.id == OWNER_ID

@bot.event
async def on_ready():
    await tree.sync()
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Protect Children Simulator"))
    flagged_count = db_query("SELECT COUNT(*) FROM banned_users", fetchone=True)[0]
    server_count = len(bot.guilds)
    logging.info(f"Connected to {server_count} servers. {flagged_count} users flagged.")

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
                await member.send(f"You were banned from {member.guild.name} for: {reason}")
            except:
                pass
            try:
                await member.ban(reason=f"Auto-flagged: {reason}")
                logging.info(f"Auto-banned {member} in {member.guild.name} for: {reason}")
            except discord.Forbidden:
                logging.warning(f"Missing permissions to ban {member} in {member.guild.name}")
            except Exception as e:
                logging.error(f"Failed to auto-ban {member}: {e}")

keep_alive()
bot.run(os.getenv('DISCORD_BOT_TOKEN'))
