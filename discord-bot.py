import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from datetime import datetime
import os
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()

OWNER_ID = 1053047461280759860  # Your user ID
DB_FILE = "banlist.db"

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# --- Database Setup ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS banned_users (
            user_id TEXT PRIMARY KEY,
            reason TEXT,
            added_by TEXT,
            timestamp TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS autoban_servers (
            server_id TEXT PRIMARY KEY
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS alts (
            alt_id TEXT PRIMARY KEY,
            main_id TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS admin_roles (
            server_id TEXT PRIMARY KEY,
            role_id TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS config (
            server_id TEXT PRIMARY KEY,
            log_channel_id TEXT,
            ban_role_id TEXT,
            kick_role_id TEXT,
            mute_role_id TEXT,
            timeout_role_id TEXT,
            warn_role_id TEXT
        )""")
init_db()

def db_query(query, params=(), fetch=False, one=False):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()
        if fetch:
            return c.fetchone() if one else c.fetchall()

def is_user_flagged(uid):
    return db_query("SELECT * FROM banned_users WHERE user_id=?", (str(uid),), fetch=True, one=True)

def is_autoban_enabled(gid):
    return db_query("SELECT * FROM autoban_servers WHERE server_id=?", (str(gid),), fetch=True, one=True)

def get_admin_role(guild_id):
    row = db_query("SELECT role_id FROM admin_roles WHERE server_id=?", (str(guild_id),), fetch=True, one=True)
    if row:
        return int(row[0])
    return None

def get_config(guild_id):
    row = db_query("SELECT * FROM config WHERE server_id=?", (str(guild_id),), fetch=True, one=True)
    if row:
        keys = ["server_id", "log_channel_id", "ban_role_id", "kick_role_id", "mute_role_id", "timeout_role_id", "warn_role_id"]
        return dict(zip(keys, row))
    return None

def is_bot_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID

def is_server_owner(interaction: discord.Interaction) -> bool:
    return interaction.guild and interaction.guild.owner_id == interaction.user.id

def is_server_admin(interaction: discord.Interaction) -> bool:
    if is_bot_owner(interaction):
        return True
    admin_role_id = get_admin_role(interaction.guild.id)
    if admin_role_id is None:
        return False
    admin_role = discord.utils.get(interaction.guild.roles, id=admin_role_id)
    return admin_role in interaction.user.roles if admin_role else False

# --- Events ---
@bot.event
async def on_ready():
    await tree.sync()  # global sync for commands
    await bot.change_presence(activity=discord.Game(name="Protecting Kids"))
    print(f"Logged in as {bot.user} | Watching {len(bot.guilds)} servers.")

@bot.event
async def on_member_join(member):
    if is_autoban_enabled(member.guild.id):
        flagged = is_user_flagged(member.id)
        if flagged:
            try:
                await member.send(f"You were auto-banned from {member.guild.name}.\nReason: {flagged[1]}")
            except:
                pass
            try:
                await member.ban(reason="Flagged User")
                print(f"Auto-banned {member}")
            except Exception as e:
                print(f"Error banning {member}: {e}")

# --- Commands ---

# /flag (Bot Owner only)
@tree.command(name="flag", description="Flag a user")
@app_commands.describe(user="User to flag", reason="Reason for flagging")
async def flag(interaction: discord.Interaction, user: discord.User, reason: str):
    if not is_bot_owner(interaction):
        await interaction.response.send_message("Only the bot owner can use this command.", ephemeral=True)
        return

    db_query("INSERT OR REPLACE INTO banned_users VALUES (?, ?, ?, ?)", (
        str(user.id), reason, str(interaction.user.id), datetime.utcnow().isoformat()
    ))
    try:
        await user.send(f"You've been globally flagged.\nReason: `{reason}`")
    except:
        pass

    embed = discord.Embed(title="User Flagged", color=discord.Color.red())
    embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text=f"Flagged by {interaction.user}")
    await interaction.response.send_message(embed=embed)

# /unflag (Bot Owner only)
@tree.command(name="unflag", description="Unflag a user")
@app_commands.describe(user="User to unflag")
async def unflag(interaction: discord.Interaction, user: discord.User):
    if not is_bot_owner(interaction):
        await interaction.response.send_message("Only the bot owner can use this command.", ephemeral=True)
        return

    db_query("DELETE FROM banned_users WHERE user_id=?", (str(user.id),))
    await interaction.response.send_message(f"{user} has been unflagged.")

# /listflags (Bot Owner only)
@tree.command(name="listflags", description="List all flagged users")
async def listflags(interaction: discord.Interaction):
    if not is_bot_owner(interaction):
        await interaction.response.send_message("Only the bot owner can use this command.", ephemeral=True)
        return

    users = db_query("SELECT * FROM banned_users", fetch=True)
    if not users:
        await interaction.response.send_message("No users flagged.")
        return

    embed = discord.Embed(title="Flagged Users", color=discord.Color.orange())
    for uid, reason, added_by, timestamp in users[:25]:
        embed.add_field(
            name=f"User ID: {uid}",
            value=f"Reason: {reason}\nAdded By: <@{added_by}>\nTime: {timestamp}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# /serverflags (Server Admin)
@tree.command(name="serverflags", description="List flagged users in this server")
async def serverflags(interaction: discord.Interaction):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    flagged = []
    for member in interaction.guild.members:
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

# /search (Server Admin)
@tree.command(name="search", description="Search if a user is flagged")
@app_commands.describe(user="User to search")
async def search(interaction: discord.Interaction, user: discord.User):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    guild = interaction.guild
    member = guild.get_member(user.id)
    flagged = is_user_flagged(user.id)

    confirmed_alts = db_query("SELECT alt_id FROM alts WHERE main_id=?", (str(user.id),), fetch=True)
    main = db_query("SELECT main_id FROM alts WHERE alt_id=?", (str(user.id),), fetch=True, one=True)

    embed_color = discord.Color.red() if flagged else discord.Color.green()
    embed = discord.Embed(title=f"User Search: {user}", color=embed_color)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Username", value=str(user), inline=True)
    embed.add_field(name="User ID", value=str(user.id), inline=True)
    if member and member.joined_at:
        embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d %H:%M UTC"), inline=False)
    else:
        embed.add_field(name="Joined Server", value="Not in this server", inline=False)
    embed.add_field(name="Flagged Status", value="🚩 Flagged" if flagged else "✅ Not flagged", inline=False)
    if flagged:
        embed.add_field(name="Flag Reason", value=flagged[1], inline=False)

    alts_list = []
    if confirmed_alts:
        alts_list += [f"<@{alt[0]}>" for alt in confirmed_alts]
    if main:
        alts_list.append(f"Main Account: <@{main[0]}>")
    if alts_list:
        embed.add_field(name="Confirmed/Potential Alts", value="\n".join(alts_list), inline=False)

    await interaction.response.send_message(embed=embed)

# /flagalt (Bot Owner only)
@tree.command(name="flagalt", description="Link an alt account to a main account")
@app_commands.describe(alt="Alt user", main="Main user")
async def flagalt(interaction: discord.Interaction, alt: discord.User, main: discord.User):
    if not is_bot_owner(interaction):
        await interaction.response.send_message("Only the bot owner can use this command.", ephemeral=True)
        return

    if alt.id == main.id:
        await interaction.response.send_message("Alt and main cannot be the same user.", ephemeral=True)
        return

    db_query("INSERT OR REPLACE INTO alts VALUES (?, ?)", (str(alt.id), str(main.id)))
    await interaction.response.send_message(f"Linked alt {alt} to main {main}.")

# /unlink (Bot Owner only)
@tree.command(name="unlink", description="Unlink an alt account")
@app_commands.describe(alt="Alt user")
async def unlink(interaction: discord.Interaction, alt: discord.User):
    if not is_bot_owner(interaction):
        await interaction.response.send_message("Only the bot owner can use this command.", ephemeral=True)
        return

    db_query("DELETE FROM alts WHERE alt_id=?", (str(alt.id),))
    await interaction.response.send_message(f"Unlinked alt {alt}.")

# Moderation commands (Server Admin)

@tree.command(name="ban", description="Ban a user")
@app_commands.describe(user="User to ban", reason="Reason")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
    try:
        await user.ban(reason=reason)
        await interaction.response.send_message(f"Banned {user} for: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to ban: {e}")

@tree.command(name="kick", description="Kick a user")
@app_commands.describe(user="User to kick", reason="Reason")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
    try:
        await user.kick(reason=reason)
        await interaction.response.send_message(f"Kicked {user} for: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to kick: {e}")

@tree.command(name="mute", description="Mute a user (add mute role)")
@app_commands.describe(user="User to mute")
async def mute(interaction: discord.Interaction, user: discord.Member):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    config = get_config(interaction.guild.id)
    if not config or not config["mute_role_id"]:
        await interaction.response.send_message("Mute role is not configured. Use `/config setrole mute @role` first.", ephemeral=True)
        return

    mute_role = discord.utils.get(interaction.guild.roles, id=int(config["mute_role_id"]))
    if not mute_role:
        await interaction.response.send_message("Configured mute role not found.", ephemeral=True)
        return

    try:
        await user.add_roles(mute_role, reason="Muted by admin command")
        await interaction.response.send_message(f"Muted {user}.")
    except Exception as e:
        await interaction.response.send_message(f"Failed to mute: {e}")

@tree.command(name="timeout", description="Timeout a user")
@app_commands.describe(user="User to timeout", duration_seconds="Duration in seconds")
async def timeout(interaction: discord.Interaction, user: discord.Member, duration_seconds: int):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
    try:
        await user.timeout(datetime.utcnow() + discord.utils.timedelta(seconds=duration_seconds), reason="Timeout by admin command")
        await interaction.response.send_message(f"Timed out {user} for {duration_seconds} seconds.")
    except Exception as e:
        await interaction.response.send_message(f"Failed to timeout: {e}")

@tree.command(name="warn", description="Warn a user")
@app_commands.describe(user="User to warn", reason="Reason for warning")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
    try:
        await user.send(f"You have been warned in {interaction.guild.name}.\nReason: {reason}")
        await interaction.response.send_message(f"Warned {user}.")
    except Exception as e:
        await interaction.response.send_message(f"Failed to warn: {e}")

# /admin and /unadmin (Server Owner only)
@tree.command(name="admin", description="Set the server admin role")
@app_commands.describe(role="Role to grant admin access")
async def admin(interaction: discord.Interaction, role: discord.Role):
    if not is_server_owner(interaction):
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return
    sid = str(interaction.guild.id)
    db_query("INSERT OR REPLACE INTO admin_roles VALUES (?, ?)", (sid, str(role.id)))
    await interaction.response.send_message(f"Set {role.mention} as Sanctum admin role for this server.")

@tree.command(name="unadmin", description="Remove the server admin role")
async def unadmin(interaction: discord.Interaction):
    if not is_server_owner(interaction):
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return
    sid = str(interaction.guild.id)
    db_query("DELETE FROM admin_roles WHERE server_id=?", (sid,))
    await interaction.response.send_message("Removed Sanctum admin role for this server.")

# /config group (Server Owner only)
@tree.group(name="config", description="Manage bot configuration")
async def config(interaction: discord.Interaction):
    if not is_server_owner(interaction):
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return

@config.command(name="setlogchannel")
@app_commands.describe(channel="Channel to send logs")
async def config_setlogchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_server_owner(interaction):
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return

    sid = str(interaction.guild.id)
    cfg = get_config(interaction.guild.id)
    if cfg:
        db_query("UPDATE config SET log_channel_id=? WHERE server_id=?", (str(channel.id), sid))
    else:
        db_query("INSERT INTO config (server_id, log_channel_id) VALUES (?, ?)", (sid, str(channel.id)))
    await interaction.response.send_message(f"Log channel set to {channel.mention}.")

@config.command(name="setrole")
@app_commands.describe(action="Action to set role for (ban/kick/mute/timeout/warn)", role="Role to assign")
async def config_setrole(interaction: discord.Interaction, action: str, role: discord.Role):
    if not is_server_owner(interaction):
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return
    action = action.lower()
    valid_actions = ["ban", "kick", "mute", "timeout", "warn"]
    if action not in valid_actions:
        await interaction.response.send_message(f"Invalid action. Choose from: {', '.join(valid_actions)}", ephemeral=True)
        return

    sid = str(interaction.guild.id)
    cfg = get_config(interaction.guild.id)
    col = f"{action}_role_id"

    if cfg:
        db_query(f"UPDATE config SET {col}=? WHERE server_id=?", (str(role.id), sid))
    else:
        # Insert with role for this action only, others null
        vals = {f"{a}_role_id": None for a in valid_actions}
        vals[col] = str(role.id)
        db_query("""INSERT INTO config
            (server_id, ban_role_id, kick_role_id, mute_role_id, timeout_role_id, warn_role_id)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (sid, vals["ban_role_id"], vals["kick_role_id"], vals["mute_role_id"], vals["timeout_role_id"], vals["warn_role_id"])
        )
    await interaction.response.send_message(f"Role for `{action}` set to {role.mention}.")

@config.command(name="resetrole")
@app_commands.describe(action="Action to reset role for (ban/kick/mute/timeout/warn)")
async def config_resetrole(interaction: discord.Interaction, action: str):
    if not is_server_owner(interaction):
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return
    action = action.lower()
    valid_actions = ["ban", "kick", "mute", "timeout", "warn"]
    if action not in valid_actions:
        await interaction.response.send_message(f"Invalid action. Choose from: {', '.join(valid_actions)}", ephemeral=True)
        return

    sid = str(interaction.guild.id)
    db_query(f"UPDATE config SET {action}_role_id=NULL WHERE server_id=?", (sid,))
    await interaction.response.send_message(f"Role for `{action}` reset.")

@config.command(name="show")
async def config_show(interaction: discord.Interaction):
    if not is_server_owner(interaction):
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return
    cfg = get_config(interaction.guild.id)
    if not cfg:
        await interaction.response.send_message("No configuration found for this server.")
        return

    embed = discord.Embed(title="Sanctum Configuration", color=discord.Color.blue())
    if cfg["log_channel_id"]:
        channel = interaction.guild.get_channel(int(cfg["log_channel_id"]))
        embed.add_field(name="Log Channel", value=channel.mention if channel else "Not found", inline=False)
    else:
        embed.add_field(name="Log Channel", value="Not set", inline=False)

    for action in ["ban", "kick", "mute", "timeout", "warn"]:
        rid = cfg.get(f"{action}_role_id")
        role = interaction.guild.get_role(int(rid)) if rid else None
        embed.add_field(name=f"{action.capitalize()} Role", value=role.mention if role else "Not set", inline=False)

    await interaction.response.send_message(embed=embed)

# /autoban (Server Admin)
@tree.command(name="autoban", description="Toggle autoban on or off")
@app_commands.describe(option="enable or disable")
async def autoban(interaction: discord.Interaction, option: str):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
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

# /support (Public)
@tree.command(name="support", description="Get support server invite")
async def support(interaction: discord.Interaction):
    await interaction.response.send_message("Join the support server: https://discord.gg/cWNVQDejPE")

# /help (Server Admin)
@tree.command(name="help", description="List available commands")
async def help_cmd(interaction: discord.Interaction):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
    help_text = """
**Available Commands:**
- `/flag user reason` *(Owner only)*
- `/unflag user` *(Owner only)*
- `/listflags` *(Owner only)*
- `/serverflags`
- `/search user`
- `/flagalt alt main` *(Owner only)*
- `/unlink alt` *(Owner only)*
- `/ban user [reason]`
- `/kick user [reason]`
- `/mute user`
- `/timeout user duration_seconds`
- `/warn user reason`
- `/admin role` *(Server Owner only)*
- `/unadmin` *(Server Owner only)*
- `/config setlogchannel #channel` *(Server Owner only)*
- `/config setrole action @role` *(Server Owner only)*
- `/config resetrole action` *(Server Owner only)*
- `/config show` *(Server Owner only)*
- `/autoban enable|disable`
- `/support`
- `/help`
"""
    await interaction.response.send_message(help_text)

# Run the bot
keep_alive()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
