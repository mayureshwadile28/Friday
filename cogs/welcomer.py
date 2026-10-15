import discord
from discord.ext import commands
from discord import app_commands
from database import db
from response_utils import make_box_embed, reply_box

DEFAULT_WELCOME_TITLE = "WELCOME TO {server}"
DEFAULT_WELCOME_MSG = "Welcome to **{server}**, {user}! We are thrilled to have you here. Feel free to introduce yourself and make yourself at home! 💫"
DEFAULT_WELCOME_COLOR = "success"

def get_welcome_config(gid: str) -> dict:
    """Returns the welcome configuration for a guild with defaults populated."""
    cfg = db.first_welcome.get(gid, {})
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": cfg.get("enabled", False),
        "channel_id": cfg.get("channel_id", None),
        "title": cfg.get("title", DEFAULT_WELCOME_TITLE),
        "message": cfg.get("message", DEFAULT_WELCOME_MSG),
        "show_avatar": cfg.get("show_avatar", True),
        "status_color": cfg.get("status_color", DEFAULT_WELCOME_COLOR),
        "custom_hex": cfg.get("custom_hex", None)
    }

def format_welcome_text(text: str, member: discord.Member, guild: discord.Guild, channel: discord.abc.GuildChannel = None) -> str:
    """Replaces placeholders with real member/server data."""
    if not text:
        return ""
    channel_mention = channel.mention if channel else "#chat"
    return (
        text.replace("{user}", member.mention)
            .replace("{username}", member.display_name)
            .replace("{name}", member.name)
            .replace("{server}", guild.name)
            .replace("{member_count}", str(guild.member_count))
            .replace("{channel}", channel_mention)
    )

def build_welcome_embed(member: discord.Member, guild: discord.Guild, cfg: dict, channel: discord.abc.GuildChannel = None) -> discord.Embed:
    """Builds a polished welcome box embed with member avatar thumbnail."""
    title_raw = cfg.get("title", DEFAULT_WELCOME_TITLE)
    msg_raw = cfg.get("message", DEFAULT_WELCOME_MSG)
    status = cfg.get("status_color", DEFAULT_WELCOME_COLOR)
    show_avatar = cfg.get("show_avatar", True)

    formatted_title = format_welcome_text(title_raw, member, guild, channel)
    formatted_msg = format_welcome_text(msg_raw, member, guild, channel)

    embed = make_box_embed(
        title=formatted_title,
        description=formatted_msg,
        status=status,
        footer=f"Member #{guild.member_count} • Welcome to our community"
    )

    custom_hex = cfg.get("custom_hex")
    if custom_hex and str(custom_hex).startswith("#") and len(custom_hex) == 7:
        try:
            embed.color = discord.Color(int(custom_hex[1:], 16))
        except Exception:
            pass

    if show_avatar and member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)

    return embed

class FirstWelcomeCog(commands.Cog, name="FirstWelcome"):
    """Greets new members on their very first message in the server or general chat."""
    def __init__(self, bot):
        self.bot = bot

    # Slash Command Group: /first_welcome
    first_welcome_group = app_commands.Group(
        name="first_welcome",
        description="Configure first message welcome greetings for new members"
    )

    @first_welcome_group.command(name="set", description="Set welcome channel. Leave empty to use THIS current channel!")
    @app_commands.describe(channel="Channel to use (Leave empty to automatically use THIS channel where you run the command!)")
    @commands.has_permissions(administrator=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target_channel = channel or interaction.channel
        gid = str(interaction.guild.id)
        if gid not in db.first_welcome:
            db.first_welcome[gid] = {}

        db.first_welcome[gid]["channel_id"] = str(target_channel.id)
        db.first_welcome[gid]["enabled"] = True
        db.save_data()

        await reply_box(
            interaction,
            f"• **Welcome Channel Set:** {target_channel.mention}\n"
            f"• **Status:** Active\n"
            f"• Friday will now greet new members with their avatar on their very first message here in {target_channel.mention}!",
            title="FIRST WELCOME ACTIVATED",
            status="success",
            ephemeral=True
        )

    @first_welcome_group.command(name="disable", description="Disable first-chat welcome greetings.")
    @commands.has_permissions(administrator=True)
    async def disable(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        if gid in db.first_welcome:
            db.first_welcome[gid]["enabled"] = False
            db.save_data()

        await reply_box(
            interaction,
            "• First message welcome greetings are now **DISABLED**.",
            title="FIRST WELCOME DISABLED",
            status="warning",
            ephemeral=True
        )

    @first_welcome_group.command(name="status", description="View current first-welcome configuration.")
    async def status(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        cfg = get_welcome_config(gid)

        chan_id = cfg.get("channel_id")
        chan_text = f"<#{chan_id}>" if chan_id else "`Any Chat Channel`"
        status_text = "🟢 Active" if cfg.get("enabled") else "🔴 Disabled"

        desc = (
            f"• **System Status:** {status_text}\n"
            f"• **Target Channel:** {chan_text}\n"
            f"• **Avatar Display:** `{'Enabled' if cfg.get('show_avatar') else 'Disabled'}`\n"
            f"• **Title Template:** `{cfg.get('title')}`\n\n"
            f"**Message Template:**\n>>> {cfg.get('message')}"
        )

        embed = make_box_embed(
            title="FIRST WELCOME STATUS",
            description=desc,
            status="info",
            footer="Friday Welcome System"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @first_welcome_group.command(name="test", description="Send a test welcome card to preview the layout.")
    @commands.has_permissions(administrator=True)
    async def test(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        cfg = get_welcome_config(gid)
        embed = build_welcome_embed(interaction.user, interaction.guild, cfg, interaction.channel)
        await interaction.response.send_message(
            content="🔍 **Test Preview of First Chat Welcome Card:**",
            embed=embed,
            ephemeral=True
        )

    @first_welcome_group.command(name="message", description="Update the welcome message format.")
    @app_commands.describe(template="New template (use {user}, {username}, {server}, {member_count}, {channel})")
    @commands.has_permissions(administrator=True)
    async def set_message(self, interaction: discord.Interaction, template: str):
        gid = str(interaction.guild.id)
        if gid not in db.first_welcome:
            db.first_welcome[gid] = {}

        db.first_welcome[gid]["message"] = template
        db.first_welcome[gid]["enabled"] = True
        db.save_data()

        await reply_box(
            interaction,
            f"• **Template Updated:**\n>>> {template}",
            title="WELCOME TEMPLATE SAVED",
            status="success",
            ephemeral=True
        )

    # ──────────────── Convenience Shortcut Commands ────────────────

    @app_commands.command(
        name="set_welcomer",
        description="Set THIS channel (or chosen channel) for welcome greetings. No channel name required!"
    )
    @app_commands.describe(
        mode="Welcome mode (defaults to 'first' chat greeting)",
        channel="Channel to use (Leave empty to use THIS channel automatically!)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="First Message Greeting (Default)", value="first"),
    ])
    @commands.has_permissions(administrator=True)
    async def set_welcomer_command(
        self,
        interaction: discord.Interaction,
        mode: str = "first",
        channel: discord.TextChannel = None
    ):
        await self.set_channel.callback(self, interaction, channel=channel)

    @app_commands.command(
        name="set_first_welcome",
        description="Quick shortcut to set first welcome channel (Leave empty for THIS channel)."
    )
    @app_commands.describe(channel="Channel to use (Leave empty to use THIS channel automatically!)")
    @commands.has_permissions(administrator=True)
    async def set_first_welcome_standalone(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None
    ):
        await self.set_channel.callback(self, interaction, channel=channel)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        gid = str(message.guild.id)
        uid = str(message.author.id)

        # Check if first-welcome is configured and enabled
        cfg = get_welcome_config(gid)
        if not cfg.get("enabled"):
            return

        # Check channel restriction
        target_channel_id = cfg.get("channel_id")
        if target_channel_id and str(message.channel.id) != str(target_channel_id):
            return

        # Check if user has already spoken their first message
        guild_history = db.first_chat_welcomes.setdefault(gid, [])
        if uid in guild_history:
            return

        # Mark user as having spoken their first message
        guild_history.append(uid)
        db.save_data()

        # Build and send the welcome card
        embed = build_welcome_embed(message.author, message.guild, cfg, message.channel)
        try:
            await message.reply(embed=embed, mention_author=True)
        except Exception:
            try:
                await message.channel.send(embed=embed)
            except Exception as e:
                print(f"[FirstWelcome] Error sending welcome card: {e}")

async def setup(bot):
    await bot.add_cog(FirstWelcomeCog(bot))
