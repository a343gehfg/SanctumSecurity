import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True  # if you need message content
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Database stubs (replace with actual DB calls)
alts_db = {}  # alt_user_id : main_user_id
flagged_users = set()  # flagged user ids
server_admins = {}  # guild_id : set(user_id)
server_owners = {}  # guild_id : owner_id
server_admin_roles = {}  # guild_id : dict(action : role_id)
server_log_channels = {}  # guild_id : channel_id

# Utility permission checks
def is_server_owner(interaction: discord.Interaction):
    return interaction.user.id == interaction.guild.owner_id

def is_server_admin(interaction: discord.Interaction):
    admins = server_admins.get(interaction.guild.id, set())
    if interaction.user.id in admins:
        return True
    # Also check roles maybe? Up to you
    return False

# Clear duplicates on startup before syncing commands
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await tree.sync()  # global sync to clear duplicates and register commands

# /search command - server admin only
@tree.command(name="search", description="Search user info")
@app_commands.check(is_server_admin)
async def search(interaction: discord.Interaction, user: discord.User):
    embed_color = discord.Color.red() if user.id in flagged_users else discord.Color.green()
    embed = discord.Embed(title=f"User Info: {user}", color=embed_color)
    member = interaction.guild.get_member(user.id)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="User ID", value=str(user.id))
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d") if member else "N/A")
    embed.add_field(name="Flagged", value="Yes" if user.id in flagged_users else "No")

    potential_alts = [alt for alt, main in alts_db.items() if main == user.id]
    if potential_alts:
        alt_mentions = ", ".join(f"<@{alt}>" for alt in potential_alts)
        embed.add_field(name="Potential Alts", value=alt_mentions)
    else:
        embed.add_field(name="Potential Alts", value="None")

    await interaction.response.send_message(embed=embed)

# /flagalt command - server admin only
@tree.command(name="flagalt", description="Link alt account to main")
@app_commands.check(is_server_admin)
async def flagalt(interaction: discord.Interaction, alt: discord.User, main: discord.User):
    alts_db[alt.id] = main.id
    await interaction.response.send_message(f"Linked {alt} as alt of {main}.")

# /unlink command - server admin only
@tree.command(name="unlink", description="Remove alt link")
@app_commands.check(is_server_admin)
async def unlink(interaction: discord.Interaction, alt: discord.User):
    if alt.id in alts_db:
        del alts_db[alt.id]
        await interaction.response.send_message(f"Unlinked alt {alt}.")
    else:
        await interaction.response.send_message(f"No alt link found for {alt}.")

# Admin management commands - server owner only
@tree.command(name="admin", description="Grant server admin role to a user")
@app_commands.check(is_server_owner)
async def admin(interaction: discord.Interaction, user: discord.User):
    guild_id = interaction.guild.id
    admins = server_admins.setdefault(guild_id, set())
    admins.add(user.id)
    await interaction.response.send_message(f"Granted server admin to {user}.")

@tree.command(name="unadmin", description="Remove server admin role from a user")
@app_commands.check(is_server_owner)
async def unadmin(interaction: discord.Interaction, user: discord.User):
    guild_id = interaction.guild.id
    admins = server_admins.setdefault(guild_id, set())
    if user.id in admins:
        admins.remove(user.id)
        await interaction.response.send_message(f"Removed server admin from {user}.")
    else:
        await interaction.response.send_message(f"{user} was not a server admin.")

# --- Fix for config group commands ---

# Define config group as app_commands.Group
class ConfigGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="config", description="Manage bot configuration")

    @app_commands.command(name="setlogchannel", description="Set log channel")
    async def setlogchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        server_log_channels[interaction.guild.id] = channel.id
        await interaction.response.send_message(f"Log channel set to {channel.mention}")

    @app_commands.command(name="setrole", description="Set role for action")
    async def setrole(self, interaction: discord.Interaction, action: str, role: discord.Role):
        roles = server_admin_roles.setdefault(interaction.guild.id, {})
        roles[action] = role.id
        await interaction.response.send_message(f"Set role for {action} to {role.mention}")

    @app_commands.command(name="resetrole", description="Reset role for action")
    async def resetrole(self, interaction: discord.Interaction, action: str):
        roles = server_admin_roles.get(interaction.guild.id, {})
        if action in roles:
            del roles[action]
            await interaction.response.send_message(f"Reset role for {action}")
        else:
            await interaction.response.send_message(f"No role set for {action}")

    @app_commands.command(name="show", description="Show config")
    async def show(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        log_channel_id = server_log_channels.get(guild_id)
        roles = server_admin_roles.get(guild_id, {})
        embed = discord.Embed(title="Config for this server")
        embed.add_field(name="Log Channel", value=f"<#{log_channel_id}>" if log_channel_id else "Not Set")
        if roles:
            roles_str = "\n".join(f"{action}: <@&{role_id}>" for action, role_id in roles.items())
        else:
            roles_str = "No roles set"
        embed.add_field(name="Roles", value=roles_str)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Instantiate the group and add permission checks
config_group = ConfigGroup()
config_group.checks.append(is_server_owner)
tree.add_command(config_group)

# Support command (server admin only)
@tree.command(name="support", description="Get support info")
@app_commands.check(is_server_admin)
async def support(interaction: discord.Interaction):
    await interaction.response.send_message("For support, join our support server: https://discord.gg/yourserver")

# Error handler for permission checks
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
    else:
        print(f"Error in command {interaction.command}: {error}")
        await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)

# Run bot
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
