import discord
from discord.ext import commands
from discord import app_commands
import os
import sys
import time

# Ensure parent directory is in sys.path
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from database import db

MEDIA_EXTENSIONS = (
    # Images
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.heic', '.heif',
    '.dng', '.raw', '.cr2', '.nef', '.tiff', '.tif', '.jfif', '.pjpeg', '.pjp',
    '.avif', '.apng', '.ico',
    # Videos
    '.mp4', '.mov', '.webm', '.mkv', '.avi', '.m4v', '.wmv', '.flv', '.3gp',
    '.ogv', '.ogg', '.qt', '.ts', '.m2ts', '.mts', '.vob', '.divx', '.asf',
    # Audio / Voice clips (media)
    '.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac', '.opus', '.wma'
)

MEDIA_DOMAINS = (
    "tenor.com", "giphy.com", "imgur.com", "gfycat.com", "redgifs.com",
    "cdn.discordapp.com", "media.discordapp.net", "youtube.com", "youtu.be",
    "tiktok.com", "instagram.com", "twitter.com", "x.com", "streamable.com",
    "pinterest.com", "reddit.com", "vimeo.com"
)


def has_media_content(message: discord.Message) -> bool:
    """Checks whether a message contains images, videos, audio, GIFs, stickers, or media links."""
    # 1. Check attachments (uploaded files)
    if message.attachments:
        for att in message.attachments:
            # If Discord identified image/video dimensions
            if getattr(att, "width", None) is not None or getattr(att, "height", None) is not None:
                return True
            ctype = (att.content_type or "").lower()
            if ctype.startswith(("image/", "video/", "audio/")):
                return True
            fname = (att.filename or "").lower()
            if any(fname.endswith(ext) for ext in MEDIA_EXTENSIONS):
                return True
            if "." in fname and any(ext in fname for ext in ('.png', '.jpg', '.jpeg', '.gif', '.mp4', '.mov', '.webp', '.heic')):
                return True
            # Any attachment uploaded by user counts as media in a media channel
            if fname:
                return True

    # 2. Check stickers (Discord animated or static stickers)
    if hasattr(message, "stickers") and message.stickers:
        return True

    # 3. Check embeds (GIFs, images, or video embeds from links)
    if hasattr(message, "embeds") and message.embeds:
        for emb in message.embeds:
            if emb.type in ("image", "video", "gifv", "article"):
                if getattr(emb, "image", None) or getattr(emb, "video", None) or getattr(emb, "thumbnail", None):
                    return True

    # 4. Check links in content pointing to media domains or media files
    content = message.content.lower()
    if any(ext in content for ext in ('.png', '.jpg', '.jpeg', '.gif', '.mp4', '.mov', '.webm', '.webp', '.heic')):
        return True
    if any(domain in content for domain in MEDIA_DOMAINS):
        return True

    return False


def has_actual_media(message: discord.Message) -> bool:
    """Strictly checks if the message contains an actual image, video, sticker, or media link.
    Returns False for pure text messages even if sent by server owner or administrators."""
    # 1. Attachments: image or video file
    if message.attachments:
        for att in message.attachments:
            if getattr(att, "width", None) is not None or getattr(att, "height", None) is not None:
                return True
            ctype = (att.content_type or "").lower()
            if ctype.startswith(("image/", "video/")):
                return True
            fname = (att.filename or "").lower()
            if any(fname.endswith(ext) for ext in (
                '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.heic', '.heif',
                '.jfif', '.avif', '.mp4', '.mov', '.webm', '.mkv', '.avi', '.m4v', '.3gp'
            )):
                return True

    # 2. Stickers
    if hasattr(message, "stickers") and message.stickers:
        return True

    # 3. Embeds: image, video, gifv
    if hasattr(message, "embeds") and message.embeds:
        for emb in message.embeds:
            if emb.type in ("image", "video", "gifv"):
                return True
            if getattr(emb, "image", None) or getattr(emb, "video", None):
                return True

    # 4. Media links in message content
    content = message.content.lower()
    if any(domain in content for domain in ("tenor.com", "giphy.com", "imgur.com", "gfycat.com", "cdn.discordapp.com", "media.discordapp.net")):
        return True
    if any(ext in content for ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.mov', '.webm')):
        return True

    return False


class MediaChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._announcement_cooldowns = {}

    def _get_wl(self, gid: str) -> dict:
        """Safely fetch and normalize media whitelist dict for a guild."""
        if not hasattr(db, "media_whitelist") or not isinstance(db.media_whitelist, dict):
            db.media_whitelist = {}
        wl = db.media_whitelist.get(gid)
        if not isinstance(wl, dict):
            wl = {"users": [], "roles": []}
            db.media_whitelist[gid] = wl
        else:
            wl.setdefault("users", [])
            wl.setdefault("roles", [])
        return wl

    def is_user_immune(self, message: discord.Message) -> bool:
        """
        Determines whether a user is immune from media channel chat deletion.
        Immune:
        1. Server Owner
        2. Administrators
        3. Members with Manage Channels or Manage Guild permissions
        4. Members in Master Security Whitelist (db.whitelist)
        5. Members in Media Whitelist (explicit user or role ID)
        """
        # 1. Server Owner is always exempt
        if message.author.id == message.guild.owner_id:
            return True

        # 2. Member Permissions (Admin, Manage Channels, Manage Guild)
        if isinstance(message.author, discord.Member):
            perms = message.author.guild_permissions
            if perms.administrator or perms.manage_guild or perms.manage_channels:
                return True

        gid = str(message.guild.id)

        # 3. Master Security Whitelist
        master_wl = [str(x) for x in db.whitelist.get(gid, [])]
        if str(message.author.id) in master_wl:
            return True

        # 4. Media Whitelist (Users & Roles)
        wl = self._get_wl(gid)
        user_wl = [str(x) for x in wl.get("users", [])]
        role_wl = [str(x) for x in wl.get("roles", [])]

        if str(message.author.id) in user_wl:
            return True

        if isinstance(message.author, discord.Member):
            user_roles = [str(r.id) for r in message.author.roles]
            if any(rid in role_wl for rid in user_roles):
                return True

        return False

    @app_commands.command(
        name="media",
        description="Designate or manage media-only channels and whitelist users/roles."
    )
    @app_commands.describe(
        action="Action to perform",
        channel="Target text channel",
        user="User to add or remove from whitelist",
        role="Role to add or remove from whitelist"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Set as Media-Only Channel", value="set"),
        app_commands.Choice(name="Remove Media-Only Channel", value="remove"),
        app_commands.Choice(name="List Media-Only Channels", value="list"),
        app_commands.Choice(name="Whitelist Add (User or Role)", value="whitelist_add"),
        app_commands.Choice(name="Whitelist Remove (User or Role)", value="whitelist_remove"),
        app_commands.Choice(name="List Whitelisted Users & Roles", value="whitelist_list")
    ])
    @app_commands.default_permissions(manage_channels=True)
    async def media(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: str = None,
        user: discord.Member = None,
        role: discord.Role = None
    ):
        gid = str(interaction.guild.id)
        if gid not in db.media_channels or not isinstance(db.media_channels[gid], list):
            db.media_channels[gid] = []

        # Handling Channel Setup Actions
        if action.value in ("set", "remove", "list"):
            target_ch = interaction.channel
            if channel:
                clean = channel.strip().replace("<#", "").replace(">", "")
                if clean.isdigit():
                    found = interaction.guild.get_channel(int(clean))
                    if found:
                        target_ch = found
                else:
                    for ch in interaction.guild.channels:
                        if clean.lower() in ch.name.lower():
                            target_ch = ch
                            break

            cid_str = str(target_ch.id)

            if action.value == "set":
                if cid_str not in db.media_channels[gid]:
                    db.media_channels[gid].append(cid_str)
                    db.save_data()
                    embed = discord.Embed(
                        title="✔ Media-Only Channel Activated",
                        description=(
                            f"{target_ch.mention} is now configured as a **Media-Only Channel**.\n\n"
                            f"• Members can only send **Images** or **Videos**.\n"
                            f"• Pure text messages from non-whitelisted members will be deleted.\n"
                            f"• Server Owner, Admins, and Whitelisted roles/users are immune."
                        ),
                        color=0x2b2d31
                    )
                    await interaction.response.send_message(embed=embed)
                else:
                    embed = discord.Embed(
                        title="ℹ Already Configured",
                        description=f"{target_ch.mention} is already configured as a media-only channel.",
                        color=0x2b2d31
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)

            elif action.value == "remove":
                if cid_str in db.media_channels[gid]:
                    db.media_channels[gid].remove(cid_str)
                    db.save_data()
                    embed = discord.Embed(
                        title="✔ Media-Only Restriction Removed",
                        description=f"{target_ch.mention} is no longer restricted to media only. Regular chatting is now allowed.",
                        color=0x2b2d31
                    )
                    await interaction.response.send_message(embed=embed)
                else:
                    embed = discord.Embed(
                        title="ℹ Not Configured",
                        description=f"{target_ch.mention} was not set as a media-only channel.",
                        color=0x2b2d31
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)

            elif action.value == "list":
                active_ids = db.media_channels.get(gid, [])
                mentions = []
                for cid in active_ids:
                    ch = interaction.guild.get_channel(int(cid))
                    if ch:
                        mentions.append(ch.mention)
                    else:
                        mentions.append(f"<#{cid}>")

                embed = discord.Embed(
                    title="✔ Media-Only Channels",
                    color=0x2b2d31
                )
                if mentions:
                    embed.description = "\n".join(f"• {m}" for m in mentions)
                else:
                    embed.description = "*No media-only channels are currently active in this server.*"
                embed.set_footer(text="Use /media action:Set as Media-Only to add channels.")
                await interaction.response.send_message(embed=embed)

        # Handling Whitelist Actions
        elif action.value == "whitelist_add":
            if not user and not role:
                await interaction.response.send_message(
                    "❌ Please specify a **user** or a **role** to add to the media whitelist.",
                    ephemeral=True
                )
                return

            wl = self._get_wl(gid)
            added = []
            if user:
                if user.id not in wl["users"]:
                    wl["users"].append(user.id)
                    added.append(f"User {user.mention}")
            if role:
                if role.id not in wl["roles"]:
                    wl["roles"].append(role.id)
                    added.append(f"Role {role.mention}")

            if added:
                db.save_data()
                embed = discord.Embed(
                    title="✔ Media Whitelist Updated",
                    description=f"Added {' and '.join(added)} to the media-only chat exemption list.\nThey can now chat freely in media channels without deletion.",
                    color=0x2b2d31
                )
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("ℹ The specified user/role is already whitelisted.", ephemeral=True)

        elif action.value == "whitelist_remove":
            if not user and not role:
                await interaction.response.send_message(
                    "❌ Please specify a **user** or a **role** to remove from the media whitelist.",
                    ephemeral=True
                )
                return

            wl = self._get_wl(gid)
            removed = []
            if user and user.id in wl["users"]:
                wl["users"].remove(user.id)
                removed.append(f"User {user.mention}")
            if role and role.id in wl["roles"]:
                wl["roles"].remove(role.id)
                removed.append(f"Role {role.mention}")

            if removed:
                db.save_data()
                embed = discord.Embed(
                    title="✔ Media Whitelist Updated",
                    description=f"Removed {' and '.join(removed)} from the media-only chat exemption list.",
                    color=0x2b2d31
                )
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("ℹ The specified user/role was not in the media whitelist.", ephemeral=True)

        elif action.value == "whitelist_list":
            wl = self._get_wl(gid)
            u_mentions = [f"<@{uid}>" for uid in wl.get("users", [])]
            r_mentions = [f"<@&{rid}>" for rid in wl.get("roles", [])]

            embed = discord.Embed(
                title="🛡️ Media-Only Channel Whitelist",
                description="Members and roles below can chat in media-only channels without message deletion.\n*(Server Owner & Administrators are immune by default)*",
                color=0x2b2d31
            )
            embed.add_field(
                name="👤 Whitelisted Members",
                value="\n".join(f"• {m}" for m in u_mentions) if u_mentions else "*None*",
                inline=False
            )
            embed.add_field(
                name="🎭 Whitelisted Roles",
                value="\n".join(f"• {m}" for m in r_mentions) if r_mentions else "*None*",
                inline=False
            )
            await interaction.response.send_message(embed=embed)

    @media.autocomplete("channel")
    async def media_channel_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        guild = interaction.guild
        if not guild:
            return []

        choices = []
        query = current.strip().lower()

        for ch in guild.channels:
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread)):
                if not query or query in ch.name.lower() or query == str(ch.id):
                    choices.append(app_commands.Choice(name=f"#{ch.name}"[:100], value=str(ch.id)))
                if len(choices) >= 25:
                    break
        return choices

    # Dedicated direct convenience commands for ease of use
    @app_commands.command(
        name="media_whitelist_add",
        description="Exempt a member or role from media-only channel chat deletion."
    )
    @app_commands.describe(
        user="Member to exempt from deletion",
        role="Role to exempt from deletion"
    )
    @app_commands.default_permissions(manage_channels=True)
    async def media_whitelist_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        role: discord.Role = None
    ):
        if not user and not role:
            await interaction.response.send_message("❌ Please specify at least a **user** or **role**.", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        wl = self._get_wl(gid)
        added = []
        if user and user.id not in wl["users"]:
            wl["users"].append(user.id)
            added.append(f"Member {user.mention}")
        if role and role.id not in wl["roles"]:
            wl["roles"].append(role.id)
            added.append(f"Role {role.mention}")

        if added:
            db.save_data()
            embed = discord.Embed(
                title="✔ Media Whitelist Updated",
                description=f"Granted chat immunity in media channels to {' and '.join(added)}.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("ℹ The specified target is already whitelisted.", ephemeral=True)

    @app_commands.command(
        name="media_whitelist_remove",
        description="Remove media-only chat exemption for a member or role."
    )
    @app_commands.describe(
        user="Member to remove from exemption list",
        role="Role to remove from exemption list"
    )
    @app_commands.default_permissions(manage_channels=True)
    async def media_whitelist_remove(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        role: discord.Role = None
    ):
        if not user and not role:
            await interaction.response.send_message("❌ Please specify at least a **user** or **role**.", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        wl = self._get_wl(gid)
        removed = []
        if user and user.id in wl["users"]:
            wl["users"].remove(user.id)
            removed.append(f"Member {user.mention}")
        if role and role.id in wl["roles"]:
            wl["roles"].remove(role.id)
            removed.append(f"Role {role.mention}")

        if removed:
            db.save_data()
            embed = discord.Embed(
                title="✔ Media Whitelist Updated",
                description=f"Removed {' and '.join(removed)} from media chat exemptions.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("ℹ The specified target was not in the media whitelist.", ephemeral=True)

    @app_commands.command(
        name="media_whitelist_list",
        description="View all members and roles exempt from media-only channel chat deletion."
    )
    @app_commands.default_permissions(manage_channels=True)
    async def media_whitelist_list(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        wl = self._get_wl(gid)
        u_mentions = [f"<@{uid}>" for uid in wl.get("users", [])]
        r_mentions = [f"<@&{rid}>" for rid in wl.get("roles", [])]

        embed = discord.Embed(
            title="🛡️ Media-Only Channel Whitelist",
            description="The following members and roles can chat in media-only channels without message deletion.\n\n*(Note: Server Owner & Administrators have automatic immunity)*",
            color=0x2b2d31
        )
        embed.add_field(
            name="👤 Whitelisted Members",
            value="\n".join(f"• {m}" for m in u_mentions) if u_mentions else "*None*",
            inline=False
        )
        embed.add_field(
            name="🎭 Whitelisted Roles",
            value="\n".join(f"• {m}" for m in r_mentions) if r_mentions else "*None*",
            inline=False
        )
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots, DMs, or non-guild messages
        if message.author.bot or not message.guild:
            return

        gid = str(message.guild.id)
        cid = str(message.channel.id)

        media_channels = getattr(db, "media_channels", {}).get(gid, [])
        if cid not in [str(x) for x in media_channels]:
            return

        # 1. Immunity check & non-media deletion for regular members
        is_immune = self.is_user_immune(message)
        if not is_immune:
            if not has_media_content(message):
                try:
                    await message.delete()
                except Exception as e:
                    print(f"[MediaChannel] Unable to delete non-media message in {message.channel.id}: {e}")
                    return

                warning = (
                    f"⚠️ {message.author.mention}, {message.channel.mention} is a **Media-Only Channel**.\n"
                    f"Only images, videos, GIFs, and media files are allowed here. Pure text chatting is prohibited."
                )
                try:
                    await message.channel.send(warning, delete_after=6)
                except Exception:
                    pass
                return

        # 2. Cross-Channel Media Announcement / Notification
        # ONLY announce if the message actually contains an image or video! Pure text from anyone (including Admin/Owner) is NOT announced.
        if not has_actual_media(message):
            return

        ann_cfg = getattr(db, "media_announcements", {}).get(gid, {})
        if not ann_cfg or not ann_cfg.get("enabled", False):
            return

        target_ch_id = ann_cfg.get("channel_id")
        if not target_ch_id or str(target_ch_id) == cid:
            return

        target_channel = message.guild.get_channel(int(target_ch_id))
        if not target_channel or not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
            return

        # Cooldown: 15s per author in that media channel to avoid spamming when posting multiple files
        cooldown_key = (message.author.id, message.channel.id)
        now = time.time()
        if cooldown_key in self._announcement_cooldowns:
            if (now - self._announcement_cooldowns[cooldown_key]) < 15:
                return
        self._announcement_cooldowns[cooldown_key] = now

        # Format message template
        raw_tmpl = ann_cfg.get("message", "").strip() or "{user} just shared a new image/video in {channel}! Go check it out! ✨"
        rendered = raw_tmpl
        rendered = rendered.replace("{user}", message.author.mention)
        rendered = rendered.replace("{user_name}", message.author.display_name)
        rendered = rendered.replace("{channel}", message.channel.mention)
        rendered = rendered.replace("{channel_name}", message.channel.name)

        # Replace server emoji placeholders like <:name:id> or :name:
        try:
            from emoji_utils import replace_plain_emojis
            rendered = replace_plain_emojis(rendered, message.guild)
        except Exception:
            pass

        try:
            await target_channel.send(
                rendered,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True)
            )
        except Exception as e:
            print(f"[MediaChannel] Failed to post media announcement in {target_channel.id}: {e}")

async def setup(bot):
    await bot.add_cog(MediaChannel(bot))
