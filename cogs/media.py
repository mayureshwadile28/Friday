import discord
from discord.ext import commands
from discord import app_commands
import os
import sys

# Ensure parent directory is in sys.path
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from database import db

MEDIA_EXTENSIONS = (
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg',
    '.mp4', '.mov', '.webm', '.mkv', '.avi', '.m4v', '.wmv', '.flv'
)

class MediaChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

        # Immunity check: Owner, Admins, Manage Channels, Whitelisted Users/Roles
        if self.is_user_immune(message):
            return

        # Check if the message contains valid image or video attachments
        has_valid_media = False
        if message.attachments:
            for att in message.attachments:
                ctype = (att.content_type or "").lower()
                fname = att.filename.lower()
                if ctype.startswith("image/") or ctype.startswith("video/"):
                    has_valid_media = True
                    break
                if any(fname.endswith(ext) for ext in MEDIA_EXTENSIONS):
                    has_valid_media = True
                    break

        if not has_valid_media:
            try:
                await message.delete()
            except Exception as e:
                print(f"[MediaChannel] Unable to delete non-media message in {message.channel.id}: {e}")
                return

            warning = (
                f"⚠️ {message.author.mention}, {message.channel.mention} is a **Media-Only Channel**.\n"
                f"You can only post images or videos here. (Text captions with media files are allowed, but pure text/links are not)."
            )
            try:
                await message.channel.send(warning, delete_after=6)
            except Exception:
                pass

async def setup(bot):
    await bot.add_cog(MediaChannel(bot))
