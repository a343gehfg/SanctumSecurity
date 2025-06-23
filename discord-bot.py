import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from datetime import datetime
import os
from dotenv import load_dotenv
from keep_alive import keep_alive  # If you use replit or hosting keep_alive.py

load_dotenv()

OWNER_ID = 1053047461280759860  # Replace with your user ID
DB_FILE = "banlist.db"

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
        c.execute("""CREATE TABLE IF NOT EXISTS alts (
            alt_id TEXT PRIMARY KEY,
            main_id TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS server_admins (
            server_id TEXT,
            user_id TEXT,
            PRIMARY KEY (server_id, user_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS config (
            server_id TEXT PRIMARY KEY,
            log_channel_id TEXT,
            ban_role_id TEXT,
            kick_role_id TEXT,
            mute_role_id TEXT,
            timeout_role_id TEXT,
            warn_role_id TEXT)""")
init_db()

def db_query(query, params=(), fetch=False, one=False):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()
        if fetch:
            return c.fetchone() if one else c.fetchall()

# Helpers for flags, autoban, admins, config, alts

def is_user_flagged(uid):
    return db_query("SELECT * FROM banned_users WHERE user_id=?", (str(uid),), fetch=True, one=True)

def is_autoban_enabled(gid):
    return db_query("SELECT * FROM autoban_servers WHERE server_id=?", (str(gid),), fetch=True, one=True)

def is_server_owner(interaction):
    return interaction.guild and interaction.user.id == interaction.guild.owner_id

def is_server_admin(interaction):
    if not interaction.guild:
        return False
    if is_server_owner(interaction):
        return True
    # Check if user is marked as Sanctum admin on this server
    return db_query(
        "SELECT * FROM server_admins WHERE server_id=? AND user_id=?",
        (str(interaction.guild.id), str(interaction.user.id)),
        fetch=True, one=True
    ) is not None

def get_config(guild_id):
    row = db_query("SELECT * FROM config WHERE server_id=?", (str(guild_id),), fetch=True, one=True)
    if not row:
        return None
    keys = ["server_id","log_channel_id","ban_role_id","kick_role_id","mute_role_id","timeout_role_id","warn_role_id"]
    return dict(zip(keys, row))

def get_alts(user_id):
    # Return all alts linked to this user (both directions)
    user_id = str(user_id)
    linked = set()
    # Alts where user is main
    rows = db_query("SELECT alt_id FROM alts WHERE main_id=?", (user_id,), fetch=True)
    linked.update([r[0] for r in rows])
    # Alts where user is alt
    rows = db_query("SELECT main_id FROM alts WHERE alt_id=?", (user_id,), fetch=True)
    linked.update([r[0] for r in rows])
    # Remove self if present
    linked.discard(user_id)
    return linked

# Events

@bot.event
async def on_ready():
    # Global slash command sync (fix commands not showing on new servers)
    await tree.sync()
    await bot.change_presence(activity=discord.Game(name="Protecting Kids"))
    print(f"Logged in as {bot.user} | Watching {len(bot.guilds)} servers.")

@bot.event
async def on_member_join(member):
    if is_autoban_enabled(member.guild.id):
        flagged = is_user_flagged(member.id)
        if flagged:
            try:
                await member.send(f"You were auto-banned from {member.guild.name}.\nReason: {flagged[1]}")
            except: pass
            try:
                await member.ban(reason="Flagged User")
                print(f"Auto-banned {member}")
            except Exception as e:
                print(f"Error banning {member}: {e}")

# Commands

# /flag (owner only)
@tree.command(name="flag", description="Flag a user")
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

# /unflag (owner only)
@tree.command(name="unflag", description="Unflag a user")
@app_commands.describe(user="User to unflag")
async def unflag(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Only the bot owner can unflag.", ephemeral=True)
        return
    db_query("DELETE FROM banned_users WHERE user_id=?", (str(user.id),))
    await interaction.response.send_message(f"{user} has been unflagged.")

# /listflags (owner only)
@tree.command(name="listflags", description="List all flagged users")
async def listflags(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Only the bot owner can use this.", ephemeral=True)
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

# /serverflags (server admin)
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

# /search (server admin) — with avatar, join date, flagged status, alts
@tree.command(name="search", description="Search if a user is flagged")
@app_commands.describe(user="User to search")
async def search(interaction: discord.Interaction, user: discord.User):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
    flagged = is_user_flagged(user.id)
    alts = get_alts(user.id)
    embed_color = discord.Color.red() if flagged else discord.Color.green()
    embed = discord.Embed(title=f"User Info - {user}", color=embed_color)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Username", value=str(user), inline=True)
    embed.add_field(name="User ID", value=str(user.id), inline=True)
    # Join date (in this guild)
    member = interaction.guild.get_member(user.id)
    if member:
        join_date = member.joined_at.strftime("%Y-%m-%d %H:%M UTC") if member.joined_at else "Unknown"
    else:
        join_date = "Not in this server"
    embed.add_field(name="Join Date", value=join_date, inline=True)
    embed.add_field(name="Flagged Status", value="🚩 Flagged" if flagged else "✅ Not flagged", inline=True)
    if alts:
        alt_mentions = []
        for alt_id in alts:
            alt_member = interaction.guild.get_member(int(alt_id))
            if alt_member:
                alt_mentions.append(str(alt_member))
            else:
                alt_mentions.append(f"<@{alt_id}>")
        embed.add_field(name="Potential Alts", value=", ".join(alt_mentions), inline=False)
    else:
        embed.add_field(name="Potential Alts", value="None", inline=False)
    if flagged:
        embed.add_field(name="Flag Reason", value=flagged[1], inline=False)
    await interaction.response.send_message(embed=embed)

# /flagalt (owner only)
@tree.command(name="flagalt", description="Link an alt account to a main account")
@app_commands.describe(alt="Alt user", main="Main user")
async def flagalt(interaction: discord.Interaction, alt: discord.User, main: discord.User):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Only the bot owner can use this command.", ephemeral=True)
        return
    if alt.id == main.id:
        await interaction.response.send_message("Alt and main cannot be the same user.", ephemeral=True)
        return
    db_query("INSERT OR REPLACE INTO alts VALUES (?, ?)", (str(alt.id), str(main.id)))
    await interaction.response.send_message(f"Linked alt {alt} to main {main}.")

# /unlink (owner only)
@tree.command(name="unlink", description="Unlink an alt account")
@app_commands.describe(alt="Alt user to unlink")
async def unlink(interaction: discord.Interaction, alt: discord.User):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Only the bot owner can use this command.", ephemeral=True)
        return
    db_query("DELETE FROM alts WHERE alt_id=?", (str(alt.id),))
    await interaction.response.send_message(f"Unlinked alt {alt}.")

# Moderation commands (server admin, require roles if set)

def get_action_role(guild_id, action):
    cfg = get_config(guild_id)
    if not cfg:
        return None
    role_id = cfg.get(f"{action}_role_id")
    return int(role_id) if role_id else None

async def has_action_permission(interaction, action):
    # Server admin role required to run moderation commands
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return False
    # Check if user has role for this action if set
    role_id = get_action_role(interaction.guild.id, action)
    if role_id and not discord.utils.get(interaction.user.roles, id=role_id):
        await interaction.response.send_message(f"You need the role for `{action}` to use this command.", ephemeral=True)
        return False
    return True

# /ban user [reason]
@tree.command(name="ban", description="Ban a user")
@app_commands.describe(user="User to ban", reason="Reason for ban")
async def ban(interaction: discord.Interaction, user: discord.User, reason: str = None):
    if not await has_action_permission(interaction, "ban"):
        return
    try:
        await interaction.guild.ban(user, reason=reason or "No reason provided")
        await interaction.response.send_message(f"Banned {user}.\nReason: {reason or 'No reason provided'}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to ban {user}: {e}")

# /kick user [reason]
@tree.command(name="kick", description="Kick a user")
@app_commands.describe(user="User to kick", reason="Reason for kick")
async def kick(interaction: discord.Interaction, user: discord.User, reason: str = None):
    if not await has_action_permission(interaction, "kick"):
        return
    try:
        await interaction.guild.kick(user, reason=reason or "No reason provided")
        await interaction.response.send_message(f"Kicked {user}.\nReason: {reason or 'No reason provided'}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to kick {user}: {e}")

# /mute user (assigns mute role if set, else fails)
@tree.command(name="mute", description="Mute a user")
@app_commands.describe(user="User to mute")
async def mute(interaction: discord.Interaction, user: discord.User):
    if not await has_action_permission(interaction, "mute"):
        return
    mute_role_id = get_action_role(interaction.guild.id, "mute")
    if not mute_role_id:
        await interaction.response.send_message("Mute role not configured.", ephemeral=True)
        return
    mute_role = interaction.guild.get_role(mute_role_id)
    if not mute_role:
        await interaction.response.send_message("Mute role not found.", ephemeral=True)
        return
    member = interaction.guild.get_member(user.id)
    if not member:
        await interaction.response.send_message("User not found in this server.", ephemeral=True)
        return
    try:
        await member.add_roles(mute_role, reason=f"Muted by {interaction.user}")
        await interaction.response.send_message(f"Muted {user}.")
    except Exception as e:
        await interaction.response.send_message(f"Failed to mute {user}: {e}")

# /timeout user duration_seconds (Discord native timeout)
@tree.command(name="timeout", description="Timeout a user")
@app_commands.describe(user="User to timeout", duration_seconds="Duration in seconds")
async def timeout(interaction: discord.Interaction, user: discord.User, duration_seconds: int):
    if not await has_action_permission(interaction, "timeout"):
        return
    member = interaction.guild.get_member(user.id)
    if not member:
        await interaction.response.send_message("User not found in this server.", ephemeral=True)
        return
    try:
        until = datetime.utcnow() + timedelta(seconds=duration_seconds)
        await member.timeout(until, reason=f"Timeout by {interaction.user}")
        await interaction.response.send_message(f"Timed out {user} for {duration_seconds} seconds.")
    except Exception as e:
        await interaction.response.send_message(f"Failed to timeout {user}: {e}")

# /warn user reason (just logs or message)
@tree.command(name="warn", description="Warn a user")
@app_commands.describe(user="User to warn", reason="Reason for warning")
async def warn(interaction: discord.Interaction, user: discord.User, reason: str):
    if not await has_action_permission(interaction, "warn"):
        return
    # For now, just send a DM and log if possible
    try:
        await user.send(f"You have been warned in {interaction.guild.name}.\nReason: {reason}")
    except: pass
    log_channel_id = None
    cfg = get_config(interaction.guild.id)
    if cfg:
        log_channel_id = cfg.get("log_channel_id")
    if log_channel_id:
        channel = interaction.guild.get_channel(int(log_channel_id))
        if channel:
            embed = discord.Embed(title="User Warned", color=discord.Color.orange())
            embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=False)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.set_footer(text=f"Warned by {interaction.user}")
            await channel.send(embed=embed)
    await interaction.response.send_message(f"Warned {user}.")

# /admin (server owner only)
@tree.command(name="admin", description="Grant server admin role for Sanctum")
@app_commands.describe(user="User to grant admin")
async def admin(interaction: discord.Interaction, user: discord.User):
    if not is_server_owner(interaction):
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return
    sid = str(interaction.guild.id)
    uid = str(user.id)
    if db_query("SELECT * FROM server_admins WHERE server_id=? AND user_id=?", (sid, uid), fetch=True, one=True):
        await interaction.response.send_message(f"{user} is already a Sanctum admin.")
        return
    db_query("INSERT INTO server_admins VALUES (?, ?)", (sid, uid))
    await interaction.response.send_message(f"Granted Sanctum admin to {user}.")

# /unadmin (server owner only)
@tree.command(name="unadmin", description="Remove server admin role for Sanctum")
@app_commands.describe(user="User to remove admin")
async def unadmin(interaction: discord.Interaction, user: discord.User):
    if not is_server_owner(interaction):
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return
    sid = str(interaction.guild.id)
    uid = str(user.id)
    if not db_query("SELECT * FROM server_admins WHERE server_id=? AND user_id=?", (sid, uid), fetch=True, one=True):
        await interaction.response.send_message(f"{user} is not a Sanctum admin.")
        return
    db_query("DELETE FROM server_admins WHERE server_id=? AND user_id=?", (sid, uid))
    await interaction.response.send_message(f"Removed Sanctum admin from {user}.")

# Config group using subclassed app_commands.Group
class ConfigGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="config", description="Manage bot configuration")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return False
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="setlogchannel")
    @app_commands.describe(channel="Channel to send logs")
    async def setlogchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        sid = str(interaction.guild.id)
        cfg = get_config(interaction.guild.id)
        if cfg:
            db_query("UPDATE config SET log_channel_id=? WHERE server_id=?", (str(channel.id), sid))
        else:
            db_query("INSERT INTO config (server_id, log_channel_id) VALUES (?, ?)", (sid, str(channel.id)))
        await interaction.response.send_message(f"Log channel set to {channel.mention}.")

    @app_commands.command(name="setrole")
    @app_commands.describe(action="Action (ban/kick/mute/timeout/warn)", role="Role to assign")
    async def setrole(self, interaction: discord.Interaction, action: str, role: discord.Role):
        action = action.lower()
        valid = ["ban", "kick", "mute", "timeout", "warn"]
        if action not in valid:
            await interaction.response.send_message(f"Invalid action. Choose from: {', '.join(valid)}", ephemeral=True)
            return
        sid = str(interaction.guild.id)
        cfg = get_config(interaction.guild.id)
        col = f"{action}_role_id"
        if cfg:
            db_query(f"UPDATE config SET {col}=? WHERE server_id=?", (str(role.id), sid))
        else:
            vals = {f"{a}_role_id": None for a in valid}
            vals[col] = str(role.id)
            db_query(
                "INSERT INTO config (server_id, ban_role_id, kick_role_id, mute_role_id, timeout_role_id, warn_role_id) VALUES (?, ?, ?, ?, ?, ?)",
                (sid, vals["ban_role_id"], vals["kick_role_id"], vals["mute_role_id"], vals["timeout_role_id"], vals["warn_role_id"])
            )
        await interaction.response.send_message(f"Role for `{action}` set to {role.mention}.")

    @app_commands.command(name="resetrole")
    @app_commands.describe(action="Action to reset (ban/kick/mute/timeout/warn)")
    async def resetrole(self, interaction: discord.Interaction, action: str):
        action = action.lower()
        valid = ["ban", "kick", "mute", "timeout", "warn"]
        if action not in valid:
            await interaction.response.send_message(f"Invalid action. Choose from: {', '.join(valid)}", ephemeral=True)
            return
        sid = str(interaction.guild.id)
        db_query(f"UPDATE config SET {action}_role_id=NULL WHERE server_id=?", (sid,))
        await interaction.response.send_message(f"Role for `{action}` reset.")

    @app_commands.command(name="show")
    async def show(self, interaction: discord.Interaction):
        cfg = get_config(interaction.guild.id)
        if not cfg:
            await interaction.response.send_message("No config found for this server.")
            return
        embed = discord.Embed(title="Sanctum Configuration", color=discord.Color.blue())
        if cfg["log_channel_id"]:
            ch = interaction.guild.get_channel(int(cfg["log_channel_id"]))
            embed.add_field(name="Log Channel", value=ch.mention if ch else "Not found", inline=False)
        else:
            embed.add_field(name="Log Channel", value="Not set", inline=False)
        for action in ["ban", "kick", "mute", "timeout", "warn"]:
            rid = cfg.get(f"{action}_role_id")
            role = interaction.guild.get_role(int(rid)) if rid else None
            embed.add_field(name=f"{action.capitalize()} Role", value=role.mention if role else "Not set", inline=False)
        await interaction.response.send_message(embed=embed)

config_group = ConfigGroup()
tree.add_command(config_group)

# /autoban (server admin)
@tree.command(name="autoban", description="Enable/disable autoban on join for this server")
@app_commands.describe(state="Enable or disable autoban")
async def autoban(interaction: discord.Interaction, state: bool):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission.", ephemeral=True)
        return
    sid = str(interaction.guild.id)
    if state:
        if not is_autoban_enabled(interaction.guild.id):
            db_query("INSERT INTO autoban_servers VALUES (?)", (sid,))
        await interaction.response.send_message("Autoban on join enabled.")
    else:
        db_query("DELETE FROM autoban_servers WHERE server_id=?", (sid,))
        await interaction.response.send_message("Autoban on join disabled.")

# /help (server admin)
@tree.command(name="help", description="Show bot help info")
async def help_command(interaction: discord.Interaction):
    if not is_server_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
    embed = discord.Embed(title="Sanctum Bot Help", color=discord.Color.blue())
    embed.add_field(name="/flag", value="(Owner) Flag a user", inline=False)
    embed.add_field(name="/unflag", value="(Owner) Remove user from flagged list", inline=False)
    embed.add_field(name="/listflags", value="(Owner) List all flagged users", inline=False)
    embed.add_field(name="/serverflags", value="(Server Admin) List flagged users in this server", inline=False)
    embed.add_field(name="/search", value="(Server Admin) Search a user's flagged status and alts", inline=False)
    embed.add_field(name="/flagalt", value="(Owner) Link alt account", inline=False)
    embed.add_field(name="/unlink", value="(Owner) Unlink alt account", inline=False)
    embed.add_field(name="/ban, /kick, /mute, /timeout, /warn", value="(Server Admin) Moderation commands", inline=False)
    embed.add_field(name="/admin, /unadmin", value="(Server Owner) Grant/revoke server Sanctum admin", inline=False)
    embed.add_field(name="/config", value="(Server Owner) Manage config: setlogchannel, setrole, resetrole, show", inline=False)
    embed.add_field(name="/autoban", value="(Server Admin) Enable/disable autoban on join", inline=False)
    await interaction.response.send_message(embed=embed)

# Run
keep_alive()  # if you have keep_alive.py for hosting
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
