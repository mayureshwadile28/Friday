import re
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
from database import db
from response_utils import make_box_embed, reply_box
from emoji_utils import replace_plain_emojis

# ──────────────── Welcome On-Join Defaults ────────────────
DEFAULT_WELCOME_TITLE = "WELCOME TO {server}!"
DEFAULT_WELCOME_MSG = (
    "Hey {user}, welcome to **{server}**! 🎉\n\n"
    "> We're thrilled to have you here with us.\n"
    "> Feel free to introduce yourself and say hello!\n\n"
    "📌 Review {rules} to get started and enjoy your stay."
)
DEFAULT_WELCOME_COLOR = "success"
DEFAULT_WELCOME_HEX = "#10b981"

# ──────────────── Farewell On-Leave Defaults ────────────────
DEFAULT_FAREWELL_TITLE = "GOODBYE FROM {server}"
DEFAULT_FAREWELL_MSG = (
    "**{user_display}** has left the server. 👋\n\n"
    "> We're sad to see you go! Thank you for being a part of our community.\n\n"
    "📉 We now have **{member_count}** members remaining."
)
DEFAULT_FAREWELL_COLOR = "error"
DEFAULT_FAREWELL_HEX = "#ef4444"

# ──────────────── First Chat Welcome Defaults ────────────────
DEFAULT_FIRST_WELCOME_TITLE = "WELCOME TO {server}!"
DEFAULT_FIRST_WELCOME_MSG = (
    "Hey {user}, welcome to **{server}**! 🎉\n\n"
    "> We're thrilled to have you here with us.\n"
    "> Feel free to introduce yourself and say hello!\n\n"
    "📌 Review {rules} to get started and enjoy your stay."
)

# ──────────────── Helper Configurations ────────────────

def get_welcome_config(gid: str) -> dict:
    """Returns the server-join welcome configuration for a guild with defaults."""
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    try:
        db.reload()
    except Exception:
        pass
    cfg = db.welcome.get(gid_str) or db.welcome.get(gid_int) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "channel_id": cfg.get("channel_id", None),
        "header_text": cfg.get("header_text", "👋 Welcome {user} !"),
        "title": cfg.get("title", DEFAULT_WELCOME_TITLE),
        "message": cfg.get("message", DEFAULT_WELCOME_MSG),
        "image_url": cfg.get("image_url", "").strip(),
        "show_avatar": bool(cfg.get("show_avatar", True)),
        "ping_user": bool(cfg.get("ping_user", True)),
        "is_embed": bool(cfg.get("is_embed", True)),
        "status_color": cfg.get("status_color", DEFAULT_WELCOME_COLOR),
        "custom_hex": cfg.get("custom_hex", DEFAULT_WELCOME_HEX)
    }

def get_farewell_config(gid: str) -> dict:
    """Returns the server-leave farewell configuration for a guild with defaults."""
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    try:
        db.reload()
    except Exception:
        pass
    cfg = db.farewell.get(gid_str) or db.farewell.get(gid_int) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "channel_id": cfg.get("channel_id", None),
        "header_text": cfg.get("header_text", "👋 Farewell {user} !"),
        "title": cfg.get("title", DEFAULT_FAREWELL_TITLE),
        "message": cfg.get("message", DEFAULT_FAREWELL_MSG),
        "image_url": cfg.get("image_url", "").strip(),
        "show_avatar": bool(cfg.get("show_avatar", True)),
        "identifier_mode": cfg.get("identifier_mode", "name"),  # "name", "id", "mention", "both"
        "is_embed": bool(cfg.get("is_embed", True)),
        "status_color": cfg.get("status_color", DEFAULT_FAREWELL_COLOR),
        "custom_hex": cfg.get("custom_hex", DEFAULT_FAREWELL_HEX)
    }

def get_first_welcome_config(gid: str) -> dict:
    """Returns the first-chat welcome configuration for a guild with defaults populated."""
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    try:
        db.reload()
    except Exception:
        pass
    cfg = db.first_welcome.get(gid_str) or db.first_welcome.get(gid_int) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "channel_id": cfg.get("channel_id", None),
        "title": cfg.get("title", DEFAULT_FIRST_WELCOME_TITLE),
        "message": cfg.get("message", DEFAULT_FIRST_WELCOME_MSG),
        "show_avatar": bool(cfg.get("show_avatar", True)),
        "status_color": cfg.get("status_color", "success"),
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

        if clean.isdigit():
            ch = guild.get_channel(int(clean))
            if ch:
                return get_channel_markdown_link(ch)

        found_ch = discord.utils.get(guild.text_channels, name=clean)
        if found_ch:
            return get_channel_markdown_link(found_ch)

        clean_lower = clean.lower()
        for ch in guild.text_channels:
            if ch.name.lower() == clean_lower:
                return get_channel_markdown_link(ch)

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

    # Standard placeholders
    res = (
        res.replace("{user}", member.mention)
           .replace("{username}", member.display_name)
           .replace("{name}", member.name)
           .replace("{id}", str(member.id))
           .replace("{user_id}", str(member.id))
           .replace("{server}", guild.name)
           .replace("{member_count}", f"{guild.member_count:,}")
           .replace("{rules}", rules_link)
           .replace("{rules_link}", rules_link)
           .replace("{rules_box}", rules_ch.mention if rules_ch else "#rules")
           .replace("{channel}", channel_link)
           .replace("{channel_link}", channel_link)
           .replace("{channel_box}", channel.mention if channel else "#chat")
    )

    # Dynamic channel pattern: <#channel_name> or <#channel_id>
    def replace_bracket_channel_pattern(m):
        raw = m.group(1).strip()
        clean = raw.lstrip("#").strip()
        if not clean:
            return m.group(0)
        if clean.isdigit():
            return f"<#{clean}>"
        for ch in guild.text_channels:
            if ch.name.lower() == clean.lower():
                return f"<#{ch.id}>"
        return m.group(0)

    res = re.sub(r'<#([^>]+)>', replace_bracket_channel_pattern, res)
    res = replace_plain_emojis(res, guild=guild)
    return res

def format_farewell_text(text: str, member: discord.Member, guild: discord.Guild, channel: discord.abc.GuildChannel = None, identifier_mode: str = "name") -> str:
    """
    Replaces placeholders for a departing member with intelligent fallbacks.
    When a member leaves, they may not be cached in memory or may only have their snowflake ID.
    """
    if not text:
        return ""

    channel_link = get_channel_markdown_link(channel) if channel else "#chat"

    # Member information extraction with resilient fallbacks
    user_id = str(getattr(member, "id", "Unknown"))
    user_name = getattr(member, "name", None) or "User"
    display_name = getattr(member, "display_name", None) or getattr(member, "global_name", None) or user_name

    # Determine user_display based on identifier_mode
    mode = str(identifier_mode).lower().strip()
    if mode == "id":
        user_display = user_id
    elif mode == "mention":
        user_display = f"<@{user_id}>"
    elif mode == "both":
        if display_name and display_name.lower() not in ("user", "unknown"):
            user_display = f"{display_name} ({user_id})"
        else:
            user_display = f"User ID: {user_id}"
    else:  # "name" (default: name with ID fallback)
        if display_name and display_name.lower() not in ("user", "unknown"):
            user_display = display_name
        else:
            user_display = f"User ID: {user_id}"

    # Dynamic channel pattern: {link:channel-name}
    def replace_channel_pattern(m):
        raw = m.group(1).strip()
        clean = raw.lstrip("#").strip()
        if not clean:
            return "#channel"
        if clean.isdigit():
            ch = guild.get_channel(int(clean))
            if ch:
                return get_channel_markdown_link(ch)
        found_ch = discord.utils.get(guild.text_channels, name=clean)
        if found_ch:
            return get_channel_markdown_link(found_ch)
        clean_lower = clean.lower()
        for ch in guild.text_channels:
            if ch.name.lower() == clean_lower:
                return get_channel_markdown_link(ch)
        return f"#{clean}"

    res = re.sub(r'\{link:([^\}]+)\}', replace_channel_pattern, text, flags=re.IGNORECASE)

    # Standard placeholders
    res = (
        res.replace("{user_display}", user_display)
           .replace("{user}", f"<@{user_id}>")
           .replace("{username}", display_name)
           .replace("{name}", user_name)
           .replace("{id}", user_id)
           .replace("{user_id}", user_id)
           .replace("{server}", guild.name)
           .replace("{member_count}", f"{guild.member_count:,}")
           .replace("{channel}", channel_link)
           .replace("{channel_link}", channel_link)
           .replace("{channel_box}", channel.mention if channel else "#chat")
    )

    # Dynamic channel pattern: <#channel_name> or <#channel_id>
    def replace_bracket_channel_pattern(m):
        raw = m.group(1).strip()
        clean = raw.lstrip("#").strip()
        if not clean:
            return m.group(0)
        if clean.isdigit():
            return f"<#{clean}>"
        for ch in guild.text_channels:
            if ch.name.lower() == clean.lower():
                return f"<#{ch.id}>"
        return m.group(0)

    res = re.sub(r'<#([^>]+)>', replace_bracket_channel_pattern, res)
    res = replace_plain_emojis(res, guild=guild)
    return res

def parse_color_hex(custom_hex: str, default: int = 0x10b981) -> int:
    """Parses a hex string into an integer color code with fallback."""
    if custom_hex and str(custom_hex).startswith("#") and len(custom_hex) == 7:
        try:
            return int(custom_hex[1:], 16)
        except Exception:
            pass
    return default

def build_welcome_embed(member: discord.Member, guild: discord.Guild, cfg: dict, channel: discord.abc.GuildChannel = None) -> discord.Embed:
    """Builds a polished welcome embed with avatar thumbnail and optional banner image/GIF."""
    title_raw = cfg.get("title", DEFAULT_WELCOME_TITLE)
    msg_raw = cfg.get("message", DEFAULT_WELCOME_MSG)
    show_avatar = cfg.get("show_avatar", True)
    custom_hex = cfg.get("custom_hex", DEFAULT_WELCOME_HEX)
    image_url = str(cfg.get("image_url", "")).strip()

    formatted_title = format_welcome_text(title_raw, member, guild, channel)
    formatted_msg = format_welcome_text(msg_raw, member, guild, channel)
    color_val = parse_color_hex(custom_hex, 0x10b981)

    embed = discord.Embed(
        title=formatted_title,
        description=formatted_msg,
        color=color_val,
        timestamp=datetime.now(timezone.utc)
    )

    if hasattr(member, "display_avatar") and member.display_avatar:
        embed.set_author(name=f"{member.display_name} joined!", icon_url=member.display_avatar.url)
        if show_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
    else:
        embed.set_author(name=f"{getattr(member, 'display_name', 'Member')} joined!")

    # Embedded Image, GIF, or file banner
    if image_url and (image_url.startswith("http://") or image_url.startswith("https://")):
        embed.set_image(url=image_url)

    footer_text = f"Member #{guild.member_count:,} • {guild.name}"
    if guild.icon:
        embed.set_footer(text=footer_text, icon_url=guild.icon.url)
    else:
        embed.set_footer(text=footer_text)

    return embed

def build_farewell_embed(member: discord.Member, guild: discord.Guild, cfg: dict, channel: discord.abc.GuildChannel = None) -> discord.Embed:
    """Builds a polished farewell embed with avatar thumbnail and optional banner image/GIF."""
    title_raw = cfg.get("title", DEFAULT_FAREWELL_TITLE)
    msg_raw = cfg.get("message", DEFAULT_FAREWELL_MSG)
    show_avatar = cfg.get("show_avatar", True)
    identifier_mode = cfg.get("identifier_mode", "name")
    custom_hex = cfg.get("custom_hex", DEFAULT_FAREWELL_HEX)
    image_url = str(cfg.get("image_url", "")).strip()

    formatted_title = format_farewell_text(title_raw, member, guild, channel, identifier_mode)
    formatted_msg = format_farewell_text(msg_raw, member, guild, channel, identifier_mode)
    color_val = parse_color_hex(custom_hex, 0xef4444)

    embed = discord.Embed(
        title=formatted_title,
        description=formatted_msg,
        color=color_val,
        timestamp=datetime.now(timezone.utc)
    )

    user_name = getattr(member, "name", "User")
    display_name = getattr(member, "display_name", None) or getattr(member, "global_name", None) or user_name

    if hasattr(member, "display_avatar") and member.display_avatar:
        embed.set_author(name=f"{display_name} left", icon_url=member.display_avatar.url)
        if show_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
    else:
        embed.set_author(name=f"{display_name} left")

    # Embedded Image, GIF, or file banner
    if image_url and (image_url.startswith("http://") or image_url.startswith("https://")):
        embed.set_image(url=image_url)

    footer_text = f"User ID: {getattr(member, 'id', 'Unknown')} • {guild.name}"
    if guild.icon:
        embed.set_footer(text=footer_text, icon_url=guild.icon.url)
    else:
        embed.set_footer(text=footer_text)

    return embed

# ──────────────── First-Chat Member History Helpers ────────────────

async def count_member_past_messages(member: discord.Member, message: discord.Message, cfg: dict = None) -> int:
    """Counts member past messages across channels to detect established members."""
    prior_msgs = 0
    try:
        async for past_msg in message.channel.history(limit=50, before=message):
            if past_msg.author.id == member.id:
                prior_msgs += 1
                if prior_msgs >= 2:
                    return prior_msgs
    except Exception:
        pass

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
    """Determines whether a member is an established / old member who should NOT be greeted on first chat."""
    if member.bot or not message.guild:
        return True

    gid = str(message.guild.id)
    uid = str(member.id)
    guild_history = db.first_chat_welcomes.setdefault(gid, [])

    if uid in guild_history:
        return True

    prior_msgs = await count_member_past_messages(member, message, cfg)
    if prior_msgs >= 2:
        guild_history.append(uid)
        db.save_data()
        return True

    if member.joined_at:
        days_in_guild = (datetime.now(timezone.utc) - member.joined_at).total_seconds() / 86400.0
        if days_in_guild > 7:
            guild_history.append(uid)
            db.save_data()
            return True

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

    return False

# ─────────────────────────────────────────────────────────────
# 🌟 WELCOMER & FAREWELL COG
# ─────────────────────────────────────────────────────────────

class WelcomerCog(commands.Cog, name="Welcomer"):
    """Comprehensive Welcome and Farewell system featuring rich embed cards, animated GIFs, and custom formats."""
    def __init__(self, bot):
        self.bot = bot

    # ══════════════════════════════════════════════════════════════
    # 🌟 /welcome COMMAND GROUP (Server Join Greetings)
    # ══════════════════════════════════════════════════════════════
    welcome_group = app_commands.Group(
        name="welcome",
        description="Configure server-join welcome greetings for new members",
        default_permissions=discord.Permissions(administrator=True)
    )

    @welcome_group.command(name="setup", description="Complete setup for server-join welcome greetings.")
    @app_commands.describe(
        channel="Destination channel for welcome cards (defaults to current channel if blank)",
        message="Custom message template ({user}, {username}, {server}, {member_count}, {rules}, {channel})",
        title="Custom card title template",
        image="URL to banner image or animated GIF",
        embed="Send as rich embed card (True) or plain chat text (False)",
        ping="Ping/mention the new member in chat (True/False)"
    )
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        message: str = None,
        title: str = None,
        image: str = None,
        embed: bool = True,
        ping: bool = True
    ):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        target_channel = channel or interaction.channel
        gid = str(interaction.guild.id)
        if gid not in db.welcome:
            db.welcome[gid] = {}

        db.welcome[gid]["channel_id"] = str(target_channel.id)
        db.welcome[gid]["enabled"] = True
        db.welcome[gid]["is_embed"] = embed
        db.welcome[gid]["ping_user"] = ping
        if message is not None:
            db.welcome[gid]["message"] = message
        if title is not None:
            db.welcome[gid]["title"] = title
        if image is not None:
            clean_img = image.strip()
            db.welcome[gid]["image_url"] = "" if clean_img.lower() in ("none", "remove", "clear", "0") else clean_img

        db.save_data()

        cfg = get_welcome_config(gid)
        summary = (
            f"• **Status:** 🟢 Active\n"
            f"• **Channel:** {target_channel.mention}\n"
            f"• **Card Format:** `{'Rich Embed' if cfg.get('is_embed') else 'Plain Text'}`\n"
            f"• **Ping Member:** `{'Enabled' if cfg.get('ping_user') else 'Disabled'}`\n"
            f"• **Banner Image/GIF:** `{'Configured' if cfg.get('image_url') else 'None'}`\n\n"
            f"Friday will now warmly greet every newly joined member in {target_channel.mention}!"
        )
        await reply_box(interaction, summary, title="WELCOME SYSTEM CONFIGURED", status="success", ephemeral=True)

    @welcome_group.command(name="channel", description="Set or change the welcome greetings destination channel.")
    @app_commands.describe(channel="Target channel (leave blank to use current channel)")
    async def welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        target_channel = channel or interaction.channel
        gid = str(interaction.guild.id)
        if gid not in db.welcome:
            db.welcome[gid] = {}

        db.welcome[gid]["channel_id"] = str(target_channel.id)
        db.welcome[gid]["enabled"] = True
        db.save_data()

        await reply_box(
            interaction,
            f"• **Welcome Channel Set:** {target_channel.mention}\n• **Status:** Active\nNew members will be greeted here upon joining.",
            title="WELCOME CHANNEL UPDATED",
            status="success",
            ephemeral=True
        )

    @welcome_group.command(name="message", description="Update the welcome message template.")
    @app_commands.describe(template="New message (supports {user}, {username}, {server}, {member_count}, {rules}, {channel})")
    async def welcome_message(self, interaction: discord.Interaction, template: str):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if gid not in db.welcome:
            db.welcome[gid] = {}

        db.welcome[gid]["message"] = template
        db.welcome[gid]["enabled"] = True
        db.save_data()

        await reply_box(
            interaction,
            f"• **Welcome Message Saved:**\n>>> {template}",
            title="WELCOME TEMPLATE UPDATED",
            status="success",
            ephemeral=True
        )

    @welcome_group.command(name="title", description="Update the welcome embed title template.")
    @app_commands.describe(title="Card title template (supports {server}, {user}, {username})")
    async def welcome_title(self, interaction: discord.Interaction, title: str):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if gid not in db.welcome:
            db.welcome[gid] = {}

        db.welcome[gid]["title"] = title
        db.save_data()

        await reply_box(
            interaction,
            f"• **Welcome Title Saved:** `{title}`",
            title="WELCOME TITLE UPDATED",
            status="success",
            ephemeral=True
        )

    @welcome_group.command(name="image", description="Set or remove the welcome banner image / animated GIF.")
    @app_commands.describe(url="Direct URL to image or GIF (type 'none' to remove)")
    async def welcome_image(self, interaction: discord.Interaction, url: str):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if gid not in db.welcome:
            db.welcome[gid] = {}

        clean_url = url.strip()
        if clean_url.lower() in ("none", "remove", "clear", "0"):
            db.welcome[gid]["image_url"] = ""
            msg = "• Welcome banner image/GIF has been **removed**."
        else:
            db.welcome[gid]["image_url"] = clean_url
            msg = f"• Welcome banner image/GIF updated:\n<{clean_url}>"

        db.save_data()
        await reply_box(interaction, msg, title="WELCOME IMAGE UPDATED", status="success", ephemeral=True)

    @welcome_group.command(name="toggle", description="Enable or disable server-join welcome greetings.")
    @app_commands.describe(status="Choose whether to enable or disable welcome greetings")
    @app_commands.choices(status=[
        app_commands.Choice(name="Enable Welcome Greetings", value="on"),
        app_commands.Choice(name="Disable Welcome Greetings", value="off")
    ])
    async def welcome_toggle(self, interaction: discord.Interaction, status: str):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if gid not in db.welcome:
            db.welcome[gid] = {}

        is_on = (status == "on")
        db.welcome[gid]["enabled"] = is_on
        db.save_data()

        if is_on:
            await reply_box(interaction, "• Server-join welcome greetings are now **ACTIVE**.", title="WELCOME ACTIVATED", status="success", ephemeral=True)
        else:
            await reply_box(interaction, "• Server-join welcome greetings are now **DISABLED**.", title="WELCOME PAUSED", status="warning", ephemeral=True)

    @welcome_group.command(name="status", description="Review current server-join welcome settings.")
    async def welcome_status(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        cfg = get_welcome_config(gid)

        chan_id = cfg.get("channel_id")
        chan_text = f"<#{chan_id}>" if chan_id else "`Not Set (Disabled)`"
        status_text = "🟢 Active" if cfg.get("enabled") else "🔴 Disabled"

        desc = (
            f"• **System Status:** {status_text}\n"
            f"• **Destination Channel:** {chan_text}\n"
            f"• **Card Format:** `{'Rich Embed' if cfg.get('is_embed') else 'Plain Text'}`\n"
            f"• **Avatar Thumbnail:** `{'Enabled' if cfg.get('show_avatar') else 'Disabled'}`\n"
            f"• **Ping Member:** `{'Enabled' if cfg.get('ping_user') else 'Disabled'}`\n"
            f"• **Theme Accent:** `{cfg.get('custom_hex', '#10b981')}`\n"
            f"• **Banner Image/GIF:** `{'Yes' if cfg.get('image_url') else 'None'}`\n\n"
            f"**Title Template:**\n`{cfg.get('title')}`\n\n"
            f"**Message Template:**\n>>> {cfg.get('message')}"
        )

        embed = make_box_embed(title="WELCOME SYSTEM STATUS", description=desc, status="info", footer="Friday Welcomer")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="test", description="Send a test welcome card into the configured channel or current channel.")
    async def welcome_test(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        cfg = get_welcome_config(gid)

        target_ch = None
        if cfg.get("channel_id"):
            target_ch = interaction.guild.get_channel(int(cfg["channel_id"]))
        if not target_ch:
            target_ch = interaction.channel

        if cfg.get("is_embed", True):
            embed = build_welcome_embed(interaction.user, interaction.guild, cfg, target_ch)
            content = f"👋 **[Welcome Preview]** Welcome {interaction.user.mention}!" if cfg.get("ping_user", True) else None
            await target_ch.send(content=content, embed=embed)
        else:
            text = format_welcome_text(cfg.get("message", DEFAULT_WELCOME_MSG), interaction.user, interaction.guild, target_ch)
            await target_ch.send(content=f"🧪 **[Test Welcome Message]**\n{text}")

        await reply_box(
            interaction,
            f"• Test welcome card dispatched to {target_ch.mention}!",
            title="TEST DISPATCHED",
            status="success",
            ephemeral=True
        )

    # ══════════════════════════════════════════════════════════════
    # 🚪 /farewell COMMAND GROUP (Server Leave Messages)
    # ══════════════════════════════════════════════════════════════
    farewell_group = app_commands.Group(
        name="farewell",
        description="Configure farewell messages when members leave the server",
        default_permissions=discord.Permissions(administrator=True)
    )

    @farewell_group.command(name="setup", description="Complete setup for server-leave farewell announcements.")
    @app_commands.describe(
        channel="Destination channel for farewell notices (defaults to current channel if blank)",
        message="Custom message template ({user_display}, {username}, {id}, {server}, {member_count}, {channel})",
        title="Custom card title template",
        image="URL to farewell image or animated GIF",
        identifier="How to display the leaving member (Username, ID Only, Mention, Both)",
        embed="Send as rich embed card (True) or plain chat text (False)"
    )
    @app_commands.choices(identifier=[
        app_commands.Choice(name="Username (Fallback to User ID if not cached)", value="name"),
        app_commands.Choice(name="User ID Only (Numeric Snowflake ID)", value="id"),
        app_commands.Choice(name="User Mention (<@ID>)", value="mention"),
        app_commands.Choice(name="Both Username + User ID", value="both")
    ])
    async def farewell_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        message: str = None,
        title: str = None,
        image: str = None,
        identifier: str = "name",
        embed: bool = True
    ):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        target_channel = channel or interaction.channel
        gid = str(interaction.guild.id)
        if gid not in db.farewell:
            db.farewell[gid] = {}

        db.farewell[gid]["channel_id"] = str(target_channel.id)
        db.farewell[gid]["enabled"] = True
        db.farewell[gid]["is_embed"] = embed
        db.farewell[gid]["identifier_mode"] = identifier
        if message is not None:
            db.farewell[gid]["message"] = message
        if title is not None:
            db.farewell[gid]["title"] = title
        if image is not None:
            clean_img = image.strip()
            db.farewell[gid]["image_url"] = "" if clean_img.lower() in ("none", "remove", "clear", "0") else clean_img

        db.save_data()

        cfg = get_farewell_config(gid)
        summary = (
            f"• **Status:** 🟢 Active\n"
            f"• **Channel:** {target_channel.mention}\n"
            f"• **Member Identifier Mode:** `{identifier}`\n"
            f"• **Card Format:** `{'Rich Embed' if cfg.get('is_embed') else 'Plain Text'}`\n"
            f"• **Banner Image/GIF:** `{'Configured' if cfg.get('image_url') else 'None'}`\n\n"
            f"Friday will now post a farewell notice whenever someone leaves {interaction.guild.name}."
        )
        await reply_box(interaction, summary, title="FAREWELL SYSTEM CONFIGURED", status="success", ephemeral=True)

    @farewell_group.command(name="channel", description="Set or change the farewell notices destination channel.")
    @app_commands.describe(channel="Target channel (leave blank to use current channel)")
    async def farewell_channel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        target_channel = channel or interaction.channel
        gid = str(interaction.guild.id)
        if gid not in db.farewell:
            db.farewell[gid] = {}

        db.farewell[gid]["channel_id"] = str(target_channel.id)
        db.farewell[gid]["enabled"] = True
        db.save_data()

        await reply_box(
            interaction,
            f"• **Farewell Channel Set:** {target_channel.mention}\n• **Status:** Active\nDeparting member notices will be posted here.",
            title="FAREWELL CHANNEL UPDATED",
            status="success",
            ephemeral=True
        )

    @farewell_group.command(name="message", description="Update the farewell message template.")
    @app_commands.describe(template="New message (supports {user_display}, {username}, {id}, {server}, {member_count}, {channel})")
    async def farewell_message(self, interaction: discord.Interaction, template: str):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if gid not in db.farewell:
            db.farewell[gid] = {}

        db.farewell[gid]["message"] = template
        db.farewell[gid]["enabled"] = True
        db.save_data()

        await reply_box(
            interaction,
            f"• **Farewell Message Saved:**\n>>> {template}",
            title="FAREWELL TEMPLATE UPDATED",
            status="success",
            ephemeral=True
        )

    @farewell_group.command(name="title", description="Update the farewell embed title template.")
    @app_commands.describe(title="Card title template (supports {server}, {user_display}, {username})")
    async def farewell_title(self, interaction: discord.Interaction, title: str):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if gid not in db.farewell:
            db.farewell[gid] = {}

        db.farewell[gid]["title"] = title
        db.save_data()

        await reply_box(
            interaction,
            f"• **Farewell Title Saved:** `{title}`",
            title="FAREWELL TITLE UPDATED",
            status="success",
            ephemeral=True
        )

    @farewell_group.command(name="identifier", description="Choose how departing members are identified (Name, ID, Mention, Both).")
    @app_commands.describe(mode="Identification method for leaving members")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Username (Fallback to User ID if not cached)", value="name"),
        app_commands.Choice(name="User ID Only (Numeric Snowflake ID)", value="id"),
        app_commands.Choice(name="User Mention (<@ID>)", value="mention"),
        app_commands.Choice(name="Both Username + User ID", value="both")
    ])
    async def farewell_identifier(self, interaction: discord.Interaction, mode: str):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if gid not in db.farewell:
            db.farewell[gid] = {}

        db.farewell[gid]["identifier_mode"] = mode
        db.save_data()

        labels = {
            "name": "Username with User ID Fallback",
            "id": "User Snowflake ID Only",
            "mention": "User Mention (<@ID>)",
            "both": "Both Username and User ID"
        }
        await reply_box(
            interaction,
            f"• **Farewell Identifier Mode Set:** `{labels.get(mode, mode)}`\nDeparting members will now be represented using this format.",
            title="IDENTIFIER MODE SAVED",
            status="success",
            ephemeral=True
        )

    @farewell_group.command(name="image", description="Set or remove the farewell banner image / animated GIF.")
    @app_commands.describe(url="Direct URL to image or GIF (type 'none' to remove)")
    async def farewell_image(self, interaction: discord.Interaction, url: str):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if gid not in db.farewell:
            db.farewell[gid] = {}

        clean_url = url.strip()
        if clean_url.lower() in ("none", "remove", "clear", "0"):
            db.farewell[gid]["image_url"] = ""
            msg = "• Farewell banner image/GIF has been **removed**."
        else:
            db.farewell[gid]["image_url"] = clean_url
            msg = f"• Farewell banner image/GIF updated:\n<{clean_url}>"

        db.save_data()
        await reply_box(interaction, msg, title="FAREWELL IMAGE UPDATED", status="success", ephemeral=True)

    @farewell_group.command(name="toggle", description="Enable or disable server-leave farewell messages.")
    @app_commands.describe(status="Choose whether to enable or disable farewell messages")
    @app_commands.choices(status=[
        app_commands.Choice(name="Enable Farewell Messages", value="on"),
        app_commands.Choice(name="Disable Farewell Messages", value="off")
    ])
    async def farewell_toggle(self, interaction: discord.Interaction, status: str):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if gid not in db.farewell:
            db.farewell[gid] = {}

        is_on = (status == "on")
        db.farewell[gid]["enabled"] = is_on
        db.save_data()

        if is_on:
            await reply_box(interaction, "• Server-leave farewell announcements are now **ACTIVE**.", title="FAREWELL ACTIVATED", status="success", ephemeral=True)
        else:
            await reply_box(interaction, "• Server-leave farewell announcements are now **DISABLED**.", title="FAREWELL PAUSED", status="warning", ephemeral=True)

    @farewell_group.command(name="status", description="Review current server-leave farewell settings.")
    async def farewell_status(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        cfg = get_farewell_config(gid)

        chan_id = cfg.get("channel_id")
        chan_text = f"<#{chan_id}>" if chan_id else "`Not Set (Disabled)`"
        status_text = "🟢 Active" if cfg.get("enabled") else "🔴 Disabled"

        desc = (
            f"• **System Status:** {status_text}\n"
            f"• **Destination Channel:** {chan_text}\n"
            f"• **Identifier Mode:** `{cfg.get('identifier_mode', 'name')}`\n"
            f"• **Card Format:** `{'Rich Embed' if cfg.get('is_embed') else 'Plain Text'}`\n"
            f"• **Avatar Thumbnail:** `{'Enabled' if cfg.get('show_avatar') else 'Disabled'}`\n"
            f"• **Theme Accent:** `{cfg.get('custom_hex', '#ef4444')}`\n"
            f"• **Banner Image/GIF:** `{'Yes' if cfg.get('image_url') else 'None'}`\n\n"
            f"**Title Template:**\n`{cfg.get('title')}`\n\n"
            f"**Message Template:**\n>>> {cfg.get('message')}"
        )

        embed = make_box_embed(title="FAREWELL SYSTEM STATUS", description=desc, status="info", footer="Friday Welcomer")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @farewell_group.command(name="test", description="Send a test farewell card into the configured channel or current channel.")
    async def farewell_test(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        cfg = get_farewell_config(gid)

        target_ch = None
        if cfg.get("channel_id"):
            target_ch = interaction.guild.get_channel(int(cfg["channel_id"]))
        if not target_ch:
            target_ch = interaction.channel

        if cfg.get("is_embed", True):
            embed = build_farewell_embed(interaction.user, interaction.guild, cfg, target_ch)
            await target_ch.send(content="🚪 **[Farewell Preview]**", embed=embed)
        else:
            text = format_farewell_text(cfg.get("message", DEFAULT_FAREWELL_MSG), interaction.user, interaction.guild, target_ch, cfg.get("identifier_mode", "name"))
            await target_ch.send(content=f"🧪 **[Test Farewell Message]**\n{text}")

        await reply_box(
            interaction,
            f"• Test farewell card dispatched to {target_ch.mention}!",
            title="TEST DISPATCHED",
            status="success",
            ephemeral=True
        )

    # ══════════════════════════════════════════════════════════════
    # 💬 /first_welcome COMMAND GROUP (First Chat Message Preserved)
    # ══════════════════════════════════════════════════════════════
    first_welcome_group = app_commands.Group(
        name="first_welcome",
        description="Configure first message welcome greetings for new members",
        default_permissions=discord.Permissions(administrator=True)
    )

    @first_welcome_group.command(name="set", description="Set welcome channel. Leave empty to use THIS current channel!")
    @app_commands.describe(channel="Channel to use (Leave empty to automatically use THIS channel where you run the command!)")
    async def fw_set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
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
            f"• **First Chat Channel Set:** {target_channel.mention}\n"
            f"• **Status:** Active\n"
            f"• Friday will now greet new members with their avatar on their very first message in {target_channel.mention}!",
            title="FIRST WELCOME ACTIVATED",
            status="success",
            ephemeral=True
        )

    @first_welcome_group.command(name="disable", description="Disable first-chat welcome greetings.")
    async def fw_disable(self, interaction: discord.Interaction):
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
    async def fw_status(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        cfg = get_first_welcome_config(gid)

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
    async def fw_test(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        cfg = get_first_welcome_config(gid)
        embed = build_welcome_embed(interaction.user, interaction.guild, cfg, interaction.channel)
        await interaction.response.send_message(
            content="🔍 **Test Preview of First Chat Welcome Card:**",
            embed=embed,
            ephemeral=True
        )

    @first_welcome_group.command(name="message", description="Update the first-welcome message format.")
    @app_commands.describe(template="New template (use {user}, {username}, {server}, {member_count}, {rules}, {channel})")
    async def fw_set_message(self, interaction: discord.Interaction, template: str):
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
    async def fw_reset_history(self, interaction: discord.Interaction, member: discord.Member = None):
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
        mode="Welcome mode (server join or first chat)",
        channel="Channel to use (Leave empty to use THIS channel automatically!)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Server Join Greeting (New Member Arrival)", value="join"),
        app_commands.Choice(name="First Message Greeting (First Chat in Channel)", value="first"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def set_welcomer_command(
        self,
        interaction: discord.Interaction,
        mode: str = "join",
        channel: discord.TextChannel = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await reply_box(interaction, "You need **Administrator** permissions to use this command.", title="PERMISSION DENIED", status="error", ephemeral=True)
            return

        if mode == "first":
            await self.fw_set_channel.callback(self, interaction, channel=channel)
        else:
            await self.welcome_channel.callback(self, interaction, channel=channel)

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
        await self.fw_set_channel.callback(self, interaction, channel=channel)

    # ══════════════════════════════════════════════════════════════
    # 🎧 DISCORD EVENT LISTENERS
    # ══════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Greets new members immediately when they join the Discord server."""
        print(f"📥 [Welcomer Event] on_member_join triggered for {member.name}#{getattr(member, 'discriminator', '0')} (ID: {member.id}, bot={member.bot}) in '{getattr(member.guild, 'name', 'Unknown')}' (ID: {getattr(member.guild, 'id', '0')})")
        if member.bot:
            print(f"ℹ️ [Welcomer] Skipping bot account {member.name} in '{getattr(member.guild, 'name', 'Unknown')}'.")
            return
        if not member.guild:
            return

        gid = str(member.guild.id)
        cfg = get_welcome_config(gid)
        if not cfg.get("enabled"):
            print(f"ℹ️ [Welcomer] Welcome is currently PAUSED / DISABLED for '{member.guild.name}' ({gid}).")
            return

        channel_id = cfg.get("channel_id")
        target_channel = None
        if channel_id:
            try:
                cid = int(channel_id)
                target_channel = member.guild.get_channel(cid) or self.bot.get_channel(cid)
                if not target_channel:
                    try:
                        target_channel = await self.bot.fetch_channel(cid)
                    except Exception as fe:
                        print(f"⚠️ [Welcomer] Failed to fetch configured welcome channel {cid}: {fe}")
            except (ValueError, TypeError):
                print(f"⚠️ [Welcomer] Invalid welcome channel_id '{channel_id}' in {member.guild.name}.")

        # Smart fallback if channel_id is not set or channel was not found
        if not target_channel:
            print(f"🔍 [Welcomer] Configured channel not found for '{member.guild.name}', attempting auto-discovery fallback...")
            bot_member = member.guild.me or member.guild.get_member(self.bot.user.id)
            if member.guild.system_channel and (not bot_member or member.guild.system_channel.permissions_for(bot_member).send_messages):
                target_channel = member.guild.system_channel
            if not target_channel:
                for candidate_name in ["welcome", "welcome-and-rules", "joins", "general", "lobby", "chat"]:
                    ch = discord.utils.get(member.guild.text_channels, name=candidate_name)
                    if ch and (not bot_member or ch.permissions_for(bot_member).send_messages):
                        target_channel = ch
                        break
            if not target_channel and bot_member:
                for ch in member.guild.text_channels:
                    if ch.permissions_for(bot_member).send_messages:
                        target_channel = ch
                        break

        if not target_channel:
            print(f"❌ [Welcomer] No writable welcome channel found for {member.guild.name}.")
            return

        # Check bot permissions safely
        bot_member = member.guild.me or member.guild.get_member(self.bot.user.id)
        if not bot_member and self.bot.user:
            try:
                bot_member = await member.guild.fetch_member(self.bot.user.id)
            except Exception:
                bot_member = None

        if bot_member:
            perms = target_channel.permissions_for(bot_member)
            if not perms.send_messages:
                print(f"❌ [Welcomer] Missing send_messages permission in #{target_channel.name} ({member.guild.name}).")
                return

        try:
            can_embed = perms.embed_links if bot_member else True
            if cfg.get("is_embed", True) and can_embed:
                embed = build_welcome_embed(member, member.guild, cfg, target_channel)
                content = None
                if cfg.get("ping_user", True):
                    raw_hdr = cfg.get("header_text") or "👋 Welcome {user} !"
                    content = format_welcome_text(raw_hdr, member, member.guild, target_channel)
                discord_file = None
                img_url = str(cfg.get("image_url", "")).strip()
                if "/static/uploads/welcome_banners/" in img_url:
                    fname = os.path.basename(img_url)
                    fpath = os.path.join("dashboard", "static", "uploads", "welcome_banners", fname)
                    if not os.path.exists(fpath):
                        fpath = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "uploads", "welcome_banners", fname)
                    if os.path.exists(fpath):
                        discord_file = discord.File(fpath, filename=fname)
                        embed.set_image(url=f"attachment://{fname}")
                elif img_url and (img_url.startswith("http://") or img_url.startswith("https://")):
                    embed.set_image(url=img_url)

                send_kwargs = {"content": content, "embed": embed} if content else {"embed": embed}
                if discord_file:
                    send_kwargs["file"] = discord_file
                await target_channel.send(**send_kwargs)
                print(f"✅ [Welcomer] Successfully delivered welcome card for {member} in #{target_channel.name} ({member.guild.name})")
            else:
                text = format_welcome_text(cfg.get("message", DEFAULT_WELCOME_MSG), member, member.guild, target_channel)
                await target_channel.send(content=text)
                print(f"✅ [Welcomer] Successfully delivered plain welcome text for {member} in #{target_channel.name} ({member.guild.name})")
        except Exception as e:
            print(f"❌ [Welcomer] Error delivering server join greeting in {member.guild.name}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Sends a farewell notification when a member leaves or is removed from the Discord server."""
        print(f"📤 [Welcomer Event] on_member_remove triggered for {member.name}#{getattr(member, 'discriminator', '0')} (ID: {member.id}) from '{getattr(member.guild, 'name', 'Unknown')}' (ID: {getattr(member.guild, 'id', '0')})")
        if not member.guild:
            return

        gid = str(member.guild.id)
        cfg = get_farewell_config(gid)
        if not cfg.get("enabled"):
            print(f"ℹ️ [Welcomer] Farewell is currently PAUSED / DISABLED for '{member.guild.name}' ({gid}).")
            return

        channel_id = cfg.get("channel_id")
        target_channel = None
        if channel_id:
            try:
                cid = int(channel_id)
                target_channel = member.guild.get_channel(cid) or self.bot.get_channel(cid)
                if not target_channel:
                    try:
                        target_channel = await self.bot.fetch_channel(cid)
                    except Exception as fe:
                        print(f"⚠️ [Welcomer] Failed to fetch configured farewell channel {cid}: {fe}")
            except (ValueError, TypeError):
                print(f"⚠️ [Welcomer] Invalid farewell channel_id '{channel_id}' in {member.guild.name}.")

        # Smart fallback if channel_id is not set or channel was not found
        if not target_channel:
            print(f"🔍 [Welcomer] Configured farewell channel not found for '{member.guild.name}', attempting auto-discovery fallback...")
            bot_member = member.guild.me or member.guild.get_member(self.bot.user.id)
            if member.guild.system_channel and (not bot_member or member.guild.system_channel.permissions_for(bot_member).send_messages):
                target_channel = member.guild.system_channel
            if not target_channel:
                for candidate_name in ["farewell", "goodbye", "welcome", "general", "lobby", "chat"]:
                    ch = discord.utils.get(member.guild.text_channels, name=candidate_name)
                    if ch and (not bot_member or ch.permissions_for(bot_member).send_messages):
                        target_channel = ch
                        break
            if not target_channel and bot_member:
                for ch in member.guild.text_channels:
                    if ch.permissions_for(bot_member).send_messages:
                        target_channel = ch
                        break

        if not target_channel:
            print(f"❌ [Welcomer] No writable farewell channel found for {member.guild.name}.")
            return

        bot_member = member.guild.me or member.guild.get_member(self.bot.user.id)
        if not bot_member and self.bot.user:
            try:
                bot_member = await member.guild.fetch_member(self.bot.user.id)
            except Exception:
                bot_member = None

        if bot_member:
            perms = target_channel.permissions_for(bot_member)
            if not perms.send_messages:
                print(f"❌ [Welcomer] Missing send_messages permission for farewell in #{target_channel.name} ({member.guild.name}).")
                return

        try:
            can_embed = perms.embed_links if bot_member else True
            if cfg.get("is_embed", True) and can_embed:
                embed = build_farewell_embed(member, member.guild, cfg, target_channel)
                content = None
                raw_hdr = str(cfg.get("header_text", "")).strip()
                if raw_hdr:
                    content = format_farewell_text(raw_hdr, member, member.guild, target_channel, cfg.get("identifier_mode", "name"))
                discord_file = None
                img_url = str(cfg.get("image_url", "")).strip()
                target_dir = "farewell_banners" if "/static/uploads/farewell_banners/" in img_url else "welcome_banners"
                if f"/static/uploads/{target_dir}/" in img_url:
                    fname = os.path.basename(img_url)
                    fpath = os.path.join("dashboard", "static", "uploads", target_dir, fname)
                    if not os.path.exists(fpath):
                        fpath = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "uploads", target_dir, fname)
                    if os.path.exists(fpath):
                        discord_file = discord.File(fpath, filename=fname)
                        embed.set_image(url=f"attachment://{fname}")
                elif img_url and (img_url.startswith("http://") or img_url.startswith("https://")):
                    embed.set_image(url=img_url)

                send_kwargs = {"content": content, "embed": embed} if content else {"embed": embed}
                if discord_file:
                    send_kwargs["file"] = discord_file
                await target_channel.send(**send_kwargs)
                print(f"✅ [Welcomer] Successfully delivered farewell card for {member} in #{target_channel.name} ({member.guild.name})")
            else:
                text = format_farewell_text(cfg.get("message", DEFAULT_FAREWELL_MSG), member, member.guild, target_channel, cfg.get("identifier_mode", "name"))
                await target_channel.send(content=text)
                print(f"✅ [Welcomer] Successfully delivered plain farewell text for {member} in #{target_channel.name} ({member.guild.name})")
        except Exception as e:
            print(f"❌ [Welcomer] Error delivering server leave farewell in {member.guild.name}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Greets genuine newcomers on their very first message in chat (preserved First Chat Welcome)."""
        if message.author.bot or not message.guild:
            return

        gid = str(message.guild.id)
        uid = str(message.author.id)

        # 1. Check if first-welcome is configured and enabled
        cfg = get_first_welcome_config(gid)
        if not cfg.get("enabled"):
            return

        # 2. Check if member is an old/established member
        if await is_established_member(message.author, message, cfg):
            return

        # 3. Mark user as greeted in database
        guild_history = db.first_chat_welcomes.setdefault(gid, [])
        if uid in guild_history:
            return
        guild_history.append(uid)
        db.save_data()

        # 4. Determine destination channel
        target_channel_id = cfg.get("channel_id")
        destination_channel = None
        if target_channel_id:
            try:
                cid = int(target_channel_id)
                destination_channel = message.guild.get_channel(cid) or self.bot.get_channel(cid)
                if not destination_channel:
                    try:
                        destination_channel = await self.bot.fetch_channel(cid)
                    except Exception:
                        destination_channel = None
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

        # Case B: Dedicated target channel configured
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
    await bot.add_cog(WelcomerCog(bot))
