import os
import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import get
import sqlite3
from datetime import datetime

# Setup intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Bot and tree setup
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

OWNER_ID = 123456789012345678  # Replace with your Discord user ID

DB_PATH = "sanctum.db"

# Connect to DB
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Create tables
c.execute('''CREATE TABLE IF NOT EXISTS flagged_users (
    user_id INTEGER PRIMARY KEY,
    flagged BOOLEAN NOT NULL
)''')

c.execute('''CREATE TABLE IF NOT EXISTS alt_links (
    alt_id INTEGER PRIMARY KEY,
    main_id INTEGER NOT NULL
)''')

c.execute('''CREATE TABLE IF NOT EXISTS admins (
    server_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (server_id, user_id)
)''')

c.execute('''CREATE TABLE IF NOT EXISTS configs (
    server_id INTEGER PRIMARY KEY,
    log_channel_id INTEGER,
    ban_role_id INTEGER,
    kick_role_id INTEGER,
    mute_role_id INTEGER,
    timeout_role_id INTEGER,
    warn_role_id INTEGER
)''')

conn.commit()

def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID

def is_server_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id == interaction.guild.owner_id

def is_server_admin(interaction: discord.Interaction) -> bool:
    # Check if user has Sanctum admin role for the server
    c.execute("SELECT 1 FROM admins WHERE server_id=? AND user_id=?", (interaction.guild.id, interaction.user.id))
    if c.fetchone():
        return True
    # fallback: check if user has Administrator permission on guild
    return interaction.user.guild_permissions.administrator

# Utility: Fetch config for server
def get_config(server_id):
    c.execute("SELECT * FROM configs WHERE server_id=?", (server_id,))
    row = c.fetchone()
    if not row:
        return {}
    keys = ['server_id', 'log_channel_id', 'ban_role_id', 'kick_role_id', 'mute_role_id', 'timeout_role_id', 'warn_role_id']
    return dict(zip(keys, row))

# Clear and sync commands to avoid duplicates
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

    # Clear existing commands to avoid duplicates
    await tree.sync(guild=None)  # Sync globally

# --------- Commands -----------

# /search command (server admin only)
@tree.command(name="search", description="Search a user and show their flagged status")
@app_commands.check(is_server_admin)
@app_commands.describe(user="User to search")
async def search(interaction: discord.Interaction, user: discord.User):
    # Fetch flagged status
    c.execute("SELECT flagged FROM flagged_users WHERE user_id=?", (user.id,))
    flagged_row = c.fetchone()
    flagged = flagged_row[0] if flagged_row else False

    # Get alts linked to this user
    # Alts where user is main
    c.execute("SELECT alt_id FROM alt_links WHERE main_id=?", (user.id,))
    alts = c.fetchall()
    # Alts where user is alt (reverse lookup)
    c.execute("SELECT main_id FROM alt_links WHERE alt_id=?", (user.id,))
    main = c.fetchone()

    embed = discord.Embed(
        title=f"User info: {user}",
        color=discord.Color.red() if flagged else discord.Color.green()
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="User ID", value=str(user.id), inline=False)
    embed.add_field(name="Joined Server", value=str(user.joined_at) if hasattr(user, "joined_at") and user.joined_at else "Unknown", inline=False)
    embed.add_field(name="Flagged", value="Yes" if flagged else "No", inline=False)

    # Show alts
    alt_ids = [str(alt[0]) for alt in alts]
    if main:
        main_id = main[0]
        embed.add_field(name="Linked Main Account", value=f"<@{main_id}>", inline=False)
    if alt_ids:
        embed.add_field(name="Linked Alts", value=", ".join(f"<@{alt_id}>" for alt_id in alt_ids), inline=False)

    await interaction.response.send_message(embed=embed)

# /flagalt [alt] [main] (server admin only)
@tree.command(name="flagalt", description="Link an alt account to a main account")
@app_commands.check(is_server_admin)
@app_commands.describe(alt="Alt user", main="Main user")
async def flagalt(interaction: discord.Interaction, alt: discord.User, main: discord.User):
    if alt.id == main.id:
        await interaction.response.send_message("Alt and main cannot be the same user.", ephemeral=True)
        return

    # Add to DB or update existing
    c.execute("INSERT OR REPLACE INTO alt_links (alt_id, main_id) VALUES (?, ?)", (alt.id, main.id))
    conn.commit()
    await interaction.response.send_message(f"Linked alt {alt.mention} to main {main.mention}.")

# /unlink [alt] (server admin only)
@tree.command(name="unlink", description="Unlink an alt account")
@app_commands.check(is_server_admin)
@app_commands.describe(alt="Alt user")
async def unlink(interaction: discord.Interaction, alt: discord.User):
    c.execute("DELETE FROM alt_links WHERE alt_id=?", (alt.id,))
    conn.commit()
    await interaction.response.send_message(f"Unlinked alt {alt.mention}.")

# Admin tools: /ban, /kick, /mute, /timeout, /warn (server admin only)

@tree.command(name="ban", description="Ban a user")
@app_commands.check(is_server_admin)
@app_commands.describe(user="User to ban", reason="Reason for ban")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = None):
    try:
        await user.ban(reason=reason)
        await interaction.response.send_message(f"Banned {user.mention}. Reason: {reason or 'No reason provided.'}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to ban {user.mention}: {e}", ephemeral=True)

@tree.command(name="kick", description="Kick a user")
@app_commands.check(is_server_admin)
@app_commands.describe(user="User to kick", reason="Reason for kick")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = None):
    try:
        await user.kick(reason=reason)
        await interaction.response.send_message(f"Kicked {user.mention}. Reason: {reason or 'No reason provided.'}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to kick {user.mention}: {e}", ephemeral=True)

@tree.command(name="mute", description="Mute a user")
@app_commands.check(is_server_admin)
@app_commands.describe(user="User to mute", reason="Reason for mute")
async def mute(interaction: discord.Interaction, user: discord.Member, reason: str = None):
    config = get_config(interaction.guild.id)
    mute_role_id = config.get('mute_role_id')
    if not mute_role_id:
        await interaction.response.send_message("Mute role not configured.", ephemeral=True)
        return
    mute_role = interaction.guild.get_role(mute_role_id)
    if not mute_role:
        await interaction.response.send_message("Mute role not found on this server.", ephemeral=True)
        return
    try:
        await user.add_roles(mute_role, reason=reason)
        await interaction.response.send_message(f"Muted {user.mention}. Reason: {reason or 'No reason provided.'}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to mute {user.mention}: {e}", ephemeral=True)

@tree.command(name="timeout", description="Timeout a user")
@app_commands.check(is_server_admin)
@app_commands.describe(user="User to timeout", duration_seconds="Duration in seconds", reason="Reason for timeout")
async def timeout(interaction: discord.Interaction, user: discord.Member, duration_seconds: int, reason: str = None):
    try:
        await user.timeout(discord.utils.utcnow() + discord.timedelta(seconds=duration_seconds), reason=reason)
        await interaction.response.send_message(f"Timed out {user.mention} for {duration_seconds} seconds. Reason: {reason or 'No reason provided.'}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to timeout {user.mention}: {e}", ephemeral=True)

@tree.command(name="warn", description="Warn a user")
@app_commands.check(is_server_admin)
@app_commands.describe(user="User to warn", reason="Reason for warning")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = None):
    # Here, you might want to log warns or send a DM to the user
    await interaction.response.send_message(f"{user.mention} has been warned. Reason: {reason or 'No reason provided.'}")

# /admin and /unadmin - grant/remove sanctum admin role (server owner only)

@tree.command(name="admin", description="Grant Sanctum admin role")
@app_commands.check(is_server_owner)
@app_commands.describe(user="User to grant admin")
async def admin(interaction: discord.Interaction, user: discord.Member):
    c.execute("INSERT OR IGNORE INTO admins (server_id, user_id) VALUES (?, ?)", (interaction.guild.id, user.id))
    conn.commit()
    await interaction.response.send_message(f"Granted Sanctum admin to {user.mention}.")

@tree.command(name="unadmin", description="Remove Sanctum admin role")
@app_commands.check(is_server_owner)
@app_commands.describe(user="User to remove admin")
async def unadmin(interaction: discord.Interaction, user: discord.Member):
    c.execute("DELETE FROM admins WHERE server_id=? AND user_id=?", (interaction.guild.id, user.id))
    conn.commit()
    await interaction.response.send_message(f"Removed Sanctum admin from {user.mention}.")

# Config commands - owner only

@tree.command(name="config", description="Configure Sanctum (owner only)")
@app_commands.check(is_owner)
async def config(interaction: discord.Interaction):
    await interaction.response.send_message("Use subcommands: setlogchannel, setrole, show, resetrole", ephemeral=True)

@config_group = app_commands.Group(name="config", description="Manage bot configuration")

@config_group.command(name="setlogchannel", description="Set the log channel")
@app_commands.check(is_owner)
@app_commands.describe(channel="Channel to send logs")
async def setlogchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    c.execute("INSERT OR REPLACE INTO configs (server_id, log_channel_id) VALUES (?, ?)", (interaction.guild.id, channel.id))
    conn.commit()
    await interaction.response.send_message(f"Log channel set to {channel.mention}")

@config_group.command(name="setrole", description="Set role for action")
@app_commands.check(is_owner)
@app_commands.describe(action="Action to set role for (ban/kick/mute/timeout/warn)", role="Role to assign")
async def setrole(interaction: discord.Interaction, action: str, role: discord.Role):
    if action.lower() not in ['ban', 'kick', 'mute', 'timeout', 'warn']:
        await interaction.response.send_message("Invalid action. Must be one of ban, kick, mute, timeout, warn.", ephemeral=True)
        return
    config = get_config(interaction.guild.id)
    # Update or insert role id for the action
    # Build dict to update correct column
    columns = {
        'ban': 'ban_role_id',
        'kick': 'kick_role_id',
        'mute': 'mute_role_id',
        'timeout': 'timeout_role_id',
        'warn': 'warn_role_id'
    }
    key = columns[action.lower()]
    # Save updated config or insert if none
    if config:
        # Update existing config row
        c.execute(f"UPDATE configs SET {key}=? WHERE server_id=?", (role.id, interaction.guild.id))
    else:
        # Insert with nulls except this role id
        values = {
            'server_id': interaction.guild.id,
            'log_channel_id': None,
            'ban_role_id': None,
            'kick_role_id': None,
            'mute_role_id': None,
            'timeout_role_id': None,
            'warn_role_id': None
        }
        values[key] = role.id
        c.execute("INSERT INTO configs (server_id, log_channel_id, ban_role_id, kick_role_id, mute_role_id, timeout_role_id, warn_role_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (values['server_id'], values['log_channel_id'], values['ban_role_id'], values['kick_role_id'], values['mute_role_id'], values['timeout_role_id'], values['warn_role_id']))
    conn.commit()
    await interaction.response.send_message(f"Set role for {action} to {role.mention}")

@config_group.command(name="show", description="Show current config")
@app_commands.check(is_owner)
async def show(interaction: discord.Interaction):
    config = get_config(interaction.guild.id)
    if not config:
        await interaction.response.send_message("No config set for this server.", ephemeral=True)
        return

    lines = []
    for k, v in config.items():
        if k == 'server_id':
            continue
        if v:
            # Try to fetch role/channel mention
            obj = None
            try:
                if 'role' in k:
                    obj = interaction.guild.get_role(v)
                elif 'channel' in k:
                    obj = interaction.guild.get_channel(v)
            except:
                pass
            lines.append(f"**{k}:** {obj.mention if obj else v}")
        else:
            lines.append(f"**{k}:** None")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@config_group.command(name="resetrole", description="Reset role for action")
@app_commands.check(is_owner)
@app_commands.describe(action="Action to reset role for (ban/kick/mute/timeout/warn)")
async def resetrole(interaction: discord.Interaction, action: str):
    if action.lower() not in ['ban', 'kick', 'mute', 'timeout', 'warn']:
        await interaction.response.send_message("Invalid action. Must be one of ban, kick, mute, timeout, warn.", ephemeral=True)
        return
    columns = {
        'ban': 'ban_role_id',
        'kick': 'kick_role_id',
        'mute': 'mute_role_id',
        'timeout': 'timeout_role_id',
        'warn': 'warn_role_id'
    }
    key = columns[action.lower()]
    c.execute(f"UPDATE configs SET {key}=NULL WHERE server_id=?", (interaction.guild.id,))
    conn.commit()
    await interaction.response.send_message(f"Reset role for {action}")

# Register config group
tree.add_command(config_group)

# /support (server admin only)
@tree.command(name="support", description="Get support information")
async def support(interaction: discord.Interaction):
    await interaction.response.send_message("For support, visit: https://discord.gg/your-support-server", ephemeral=True)

# /serverflags (server admin only)
@tree.command(name="serverflags", description="List flagged users in this server")
@app_commands.check(is_server_admin)
async def serverflags(interaction: discord.Interaction):
    flagged_list = []
    for member in interaction.guild.members:
        c.execute("SELECT flagged FROM flagged_users WHERE user_id=?", (member.id,))
        flagged = c.fetchone()
        if flagged and flagged[0]:
            flagged_list.append(f"{member.mention} (ID: {member.id})")
    if flagged_list:
        await interaction.response.send_message("Flagged users in this server:\n" + "\n".join(flagged_list))
    else:
        await interaction.response.send_message("No flagged users in this server.")

# /autoban (server admin only) — placeholder example
@tree.command(name="autoban", description="Enable/disable AutoBan system")
@app_commands.check(is_server_admin)
@app_commands.describe(enable="Enable or disable AutoBan")
async def autoban(interaction: discord.Interaction, enable: bool):
    # Just an example stub for now
    await interaction.response.send_message(f"AutoBan {'enabled' if enable else 'disabled'} on this server.")

# Run bot
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
