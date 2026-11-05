import re
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
from database import db
from response_utils import make_box_embed, reply_box

DEFAULT_WELCOME_TITLE = "WELCOME TO {server}!"
DEFAULT_WELCOME_MSG = (
    "Hey {user}, welcome to **{server}**! 🎉\n\n"
    "> We're thrilled to have you here with us.\n"
    "> Feel free to introduce yourself and say hello!\n\n"
    "📌 Review {rules} to get started and enjoy your stay."
)
DEFAULT_WELCOME_COLOR = "success"

def get_welcome_config(gid: str) -> dict:
    """Returns the welcome configuration for a guild with defaults populated."""
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    cfg = db.first_welcome.get(gid_str) or db.first_welcome.get(gid_int) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "channel_id": cfg.get("channel_id", None),
        "title": cfg.get("title", DEFAULT_WELCOME_TITLE),
        "message": cfg.get("message", DEFAULT_WELCOME_MSG),
        "show_avatar": cfg.get("show_avatar", True),
        "status_color": cfg.get("status_color", DEFAULT_WELCOME_COLOR),
        "custom_hex": cfg.get("custom_hex", "#10b981")
    }

def get_channel_markdown_link(channel: discord.abc.GuildChannel) -> str:
    """Returns a clean bright-blue clickable Discord markdown link without the hashtag pill box."""
    if not channel or not getattr(channel, "guild", None):
        return "#chat"
    return f"[#{channel.name}](https://discord.com/channels/{channel.guild.id}/{channel.id})"

def get_rules_channel(guild: discord.Guild) -> discord.TextChannel:
    """Finds the server's rules channel (guild.rules_channel or searches candidate names)."""
    if not guild:
        return None
    if getattr(guild, "rules_channel", None):
        return guild.rules_channel
    candidate_names = ["rules", "rule", "server-rules", "guidelines", "server_rules", "welcome-and-rules"]
    for name in candidate_names:
        ch = discord.utils.get(guild.text_channels, name=name)
        if ch:
            return ch
    return None

def format_welcome_text(text: str, member: discord.Member, guild: discord.Guild, channel: discord.abc.GuildChannel = None) -> str:
    """Replaces placeholders with real member/server data and clean bright-blue channel links."""
    if not text:
        return ""

    rules_ch = get_rules_channel(guild)
    rules_link = get_channel_markdown_link(rules_ch) if rules_ch else (get_channel_markdown_link(channel) if channel else "#rules")
    channel_link = get_channel_markdown_link(channel) if channel else "#chat"

    # Dynamic channel pattern: {link:channel-name}, {link:#channel-name}, or {link:channel_id}
    def replace_channel_pattern(m):
        raw = m.group(1).strip()
        clean = raw.lstrip("#").strip()
        if not clean:
            return "#channel"

        # 1. Match by channel ID if numeric
        if clean.isdigit():
            ch = guild.get_channel(int(clean))
            if ch:
                return get_channel_markdown_link(ch)

        # 2. Match exact name
        found_ch = discord.utils.get(guild.text_channels, name=clean)
        if found_ch:
            return get_channel_markdown_link(found_ch)

        # 3. Match case-insensitive
        clean_lower = clean.lower()
        for ch in guild.text_channels:
            if ch.name.lower() == clean_lower:
                return get_channel_markdown_link(ch)

        # 4. Match stripped symbols (ignoring unicode dashes, emojis, dots, spaces)
        def strip_symbols(s):
            return re.sub(r'[^\w]+', '', s, flags=re.UNICODE).lower()
        target_stripped = strip_symbols(clean)
        if target_stripped:
            for ch in guild.text_channels:
                if strip_symbols(ch.name) == target_stripped:
                    return get_channel_markdown_link(ch)
            for ch in guild.text_channels:
                if target_stripped in strip_symbols(ch.name):
                    return get_channel_markdown_link(ch)

        return f"#{clean}"

    res = re.sub(r'\{link:([^\}]+)\}', replace_channel_pattern, text, flags=re.IGNORECASE)

    # Replace standard placeholders
    res = (
        res.replace("{user}", member.mention)
           .replace("{username}", member.display_name)
           .replace("{name}", member.name)
           .replace("{server}", guild.name)
           .replace("{member_count}", f"{guild.member_count:,}")
           .replace("{rules}", rules_link)
           .replace("{rules_link}", rules_link)
           .replace("{rules_box}", rules_ch.mention if rules_ch else "#rules")
           .replace("{channel}", channel_link)
           .replace("{channel_link}", channel_link)
           .replace("{channel_box}", channel.mention if channel else "#chat")
    )
    return res

def build_welcome_embed(member: discord.Member, guild: discord.Guild, cfg: dict, channel: discord.abc.GuildChannel = None) -> discord.Embed:
    """Builds a polished, vertically proportioned welcome box embed with member avatar thumbnail."""
    title_raw = cfg.get("title", DEFAULT_WELCOME_TITLE)
    msg_raw = cfg.get("message", DEFAULT_WELCOME_MSG)
    show_avatar = cfg.get("show_avatar", True)
    custom_hex = cfg.get("custom_hex", "#10b981")

    formatted_title = format_welcome_text(title_raw, member, guild, channel)
    formatted_msg = format_welcome_text(msg_raw, member, guild, channel)

    color_val = 0x10b981
    if custom_hex and str(custom_hex).startswith("#") and len(custom_hex) == 7:
        try:
            color_val = int(custom_hex[1:], 16)
        except Exception:
            color_val = 0x10b981

    embed = discord.Embed(
        title=formatted_title,
        description=formatted_msg,
        color=color_val,
        timestamp=datetime.now(timezone.utc)
    )

    if member.display_avatar:
        embed.set_author(name=f"{member.display_name} joined!", icon_url=member.display_avatar.url)
    else:
        embed.set_author(name=f"{member.display_name} joined!")

    # Member avatar thumbnail on the right squeezes description horizontally into a clean box
    if show_avatar and member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)

    footer_text = f"Member #{guild.member_count:,} • {guild.name}"
    if guild.icon:
        embed.set_footer(text=footer_text, icon_url=guild.icon.url)
    else:
        embed.set_footer(text=footer_text)

    return embed

async def count_member_past_messages(member: discord.Member, message: discord.Message, cfg: dict = None) -> int:
    """
    Counts the number of past messages sent by this member across the current channel
    and main server chat channels, without relying on any XP or leveling system.
    """
    prior_msgs = 0

    # 1. Scan recent history of the current channel
    try:
        async for past_msg in message.channel.history(limit=50, before=message):
            if past_msg.author.id == member.id:
                prior_msgs += 1
                if prior_msgs >= 2:
                    return prior_msgs
    except Exception:
        pass

    # 2. If fewer than 2 found in current channel, check the target welcome channel or #general
    candidate_channels = []
    if cfg:
        target_cid = cfg.get("channel_id")
        if target_cid:
            try:
                target_ch = message.guild.get_channel(int(target_cid))
                if target_ch and target_ch.id != message.channel.id and target_ch.permissions_for(message.guild.me).read_message_history:
                    candidate_channels.append(target_ch)
            except Exception:
                pass

    for ch_name in ["general", "chat", "main", "lounge", "general-chat", "discussion"]:
        found_ch = discord.utils.get(message.guild.text_channels, name=ch_name)
        if found_ch and found_ch.id != message.channel.id and found_ch not in candidate_channels:
            if found_ch.permissions_for(message.guild.me).read_message_history:
                candidate_channels.append(found_ch)
                break

    for ch in candidate_channels:
        try:
            async for past_msg in ch.history(limit=50):
                if past_msg.id != message.id and past_msg.author.id == member.id:
                    prior_msgs += 1
                    if prior_msgs >= 2:
                        return prior_msgs
        except Exception:
            pass

    return prior_msgs

async def is_established_member(member: discord.Member, message: discord.Message, cfg: dict = None) -> bool:
    """
    Determines whether a member is an established / old member who should NOT be greeted.
    Directly checks the amount of chat that the member has done so far (message history >= 2).
    Does NOT rely on Friday XP system to ensure compatibility across all servers.
    """
    if member.bot or not message.guild:
        return True

    gid = str(message.guild.id)
    uid = str(member.id)
    guild_history = db.first_chat_welcomes.setdefault(gid, [])

    # 1. Already processed in welcome history
    if uid in guild_history:
        return True

    # 2. Direct chat count check: counts how many texts/messages this specific member has done so far
    # If user has sent 2 or more messages, consider them an old member!
    prior_msgs = await count_member_past_messages(member, message, cfg)
    if prior_msgs >= 2:
        guild_history.append(uid)
        db.save_data()
        return True

    # 3. Server tenure check: joined over 7 days ago
    if member.joined_at:
        days_in_guild = (datetime.now(timezone.utc) - member.joined_at).total_seconds() / 86400.0
        if days_in_guild > 7:
            guild_history.append(uid)
            db.save_data()
            return True

    # 4. Roles check: has 2+ custom non-default roles, or staff/moderator permissions
    custom_roles = [
        r for r in member.roles
        if hasattr(r, 'is_default') and not r.is_default() and not (hasattr(r, 'is_premium_subscriber') and r.is_premium_subscriber()) and not (hasattr(r, 'is_integration') and r.is_integration()) and not (hasattr(r, 'is_bot_managed') and r.is_bot_managed())
    ]
    has_staff_perms = False
    for r in member.roles:
        perms = getattr(r, 'permissions', None)
        if perms and isinstance(perms, discord.Permissions):
            if perms.administrator or perms.manage_messages or perms.kick_members or perms.ban_members:
                has_staff_perms = True
                break
    if len(custom_roles) >= 2 or has_staff_perms:
        guild_history.append(uid)
        db.save_data()
        return True

    # Genuine new member sending their first message!
    return False

class FirstWelcomeCog(commands.Cog, name="FirstWelcome"):
    """Greets new members on their very first message in the server or general chat."""
    def __init__(self, bot):
        self.bot = bot

    # Slash Command Group: /first_welcome strictly protected with Administrator permissions
    first_welcome_group = app_commands.Group(
        name="first_welcome",
        description="Configure first message welcome greetings for new members",
        default_permissions=discord.Permissions(administrator=True)
    )

    @first_welcome_group.command(name="set", description="Set welcome channel. Leave empty to use THIS current channel!")
    @app_commands.describe(channel="Channel to use (Leave empty to automatically use THIS channel where you run the command!)")
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

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
            f"• Friday will now greet new members with their avatar on their very first message in {target_channel.mention}!",
            title="FIRST WELCOME ACTIVATED",
            status="success",
            ephemeral=True
        )

    @first_welcome_group.command(name="disable", description="Disable first-chat welcome greetings.")
    async def disable(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

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
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

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
    async def test(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        cfg = get_welcome_config(gid)
        embed = build_welcome_embed(interaction.user, interaction.guild, cfg, interaction.channel)
        await interaction.response.send_message(
            content="🔍 **Test Preview of Squeezed First Chat Welcome Card:**",
            embed=embed,
            ephemeral=True
        )

    @first_welcome_group.command(name="message", description="Update the welcome message format.")
    @app_commands.describe(template="New template (use {user}, {username}, {server}, {member_count}, {rules}, {channel})")
    async def set_message(self, interaction: discord.Interaction, template: str):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

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

    @first_welcome_group.command(name="reset", description="Reset first-welcome history for a member or all members to re-test greetings.")
    @app_commands.describe(member="Member to reset (leave empty to reset all members in this server)")
    async def reset_history(self, interaction: discord.Interaction, member: discord.Member = None):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if member:
            uid = str(member.id)
            if gid in db.first_chat_welcomes and uid in db.first_chat_welcomes[gid]:
                db.first_chat_welcomes[gid].remove(uid)
                db.save_data()
            await reply_box(
                interaction,
                f"• First-chat welcome status has been **reset** for {member.mention}! Their next message will trigger the welcome greeting.",
                title="MEMBER WELCOME RESET",
                status="success",
                ephemeral=True
            )
        else:
            db.first_chat_welcomes[gid] = []
            db.save_data()
            await reply_box(
                interaction,
                "• First-chat welcome history for this server has been **cleared**! Recent new members will be greeted on their next message.",
                title="ALL WELCOMES RESET",
                status="warning",
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
    @app_commands.default_permissions(administrator=True)
    async def set_welcomer_command(
        self,
        interaction: discord.Interaction,
        mode: str = "first",
        channel: discord.TextChannel = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return
        await self.set_channel.callback(self, interaction, channel=channel)

    @app_commands.command(
        name="set_first_welcome",
        description="Quick shortcut to set first welcome channel (Leave empty for THIS channel)."
    )
    @app_commands.describe(channel="Channel to use (Leave empty to use THIS channel automatically!)")
    @app_commands.default_permissions(administrator=True)
    async def set_first_welcome_standalone(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return
        await self.set_channel.callback(self, interaction, channel=channel)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        gid = str(message.guild.id)
        uid = str(message.author.id)

        # 1. Check if first-welcome is configured and enabled
        cfg = get_welcome_config(gid)
        if not cfg.get("enabled"):
            return

        # 2. Check if member is an old/established member
        if await is_established_member(message.author, message, cfg):
            return

        # 3. Mark user as greeted in database
        guild_history = db.first_chat_welcomes.setdefault(gid, [])
        guild_history.append(uid)
        db.save_data()

        # 4. Determine destination channel
        target_channel_id = cfg.get("channel_id")
        destination_channel = None
        if target_channel_id:
            try:
                destination_channel = message.guild.get_channel(int(target_channel_id))
            except (ValueError, TypeError):
                destination_channel = None

        embed = build_welcome_embed(
            message.author,
            message.guild,
            cfg,
            destination_channel or message.channel
        )

        # Case A: Same channel (or no specific target channel set) -> Reply directly in chat
        if not destination_channel or destination_channel.id == message.channel.id:
            try:
                await message.reply(embed=embed, mention_author=True)
                return
            except Exception:
                try:
                    await message.channel.send(content=f"🎉 Welcome {message.author.mention}!", embed=embed)
                    return
                except Exception as e:
                    print(f"[FirstWelcome] Error sending in current channel: {e}")

        # Case B: Dedicated target channel configured (e.g. #welcome or #general)
        if destination_channel:
            try:
                await destination_channel.send(
                    content=f"🎉 Welcome {message.author.mention} to **{message.guild.name}**! Glad to see your first message!",
                    embed=embed
                )
                return
            except Exception as dest_err:
                print(f"[FirstWelcome] Failed sending to dedicated channel {destination_channel.id}: {dest_err}")
                try:
                    await message.reply(embed=embed, mention_author=True)
                except Exception:
                    await message.channel.send(content=f"🎉 Welcome {message.author.mention}!", embed=embed)

async def setup(bot):
    await bot.add_cog(FirstWelcomeCog(bot))
