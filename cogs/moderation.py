import discord
import re
import aiohttp
import time
from discord.ext import commands
from discord import app_commands
import datetime
from typing import Optional, List, Dict, Union
from database import db
from response_utils import make_box_embed, reply_box


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._unlocking_channels = set()

    def check_mod_permission(self, interaction: discord.Interaction, perm_name: str) -> bool:
        """Strict runtime check verifying Administrator, Server Owner, or the explicit moderation permission."""
        if not interaction.guild:
            return False
        if interaction.user.id == interaction.guild.owner_id:
            return True
        perms = getattr(interaction.user, "guild_permissions", None)
        if not perms:
            return False
        if perms.administrator:
            return True
        return getattr(perms, perm_name, False)

    async def require_mod_permission(self, interaction: discord.Interaction, perm_name: str, friendly_name: str) -> bool:
        """Enforces runtime permission; sends an authentic error box if unauthorized."""
        if self.check_mod_permission(interaction, perm_name):
            return True
        gid = str(interaction.guild.id)
        err_tpl = db.custom_responses.get(gid, {}).get(
            f"perm_err_{perm_name}",
            f"You do not possess the required **{friendly_name}** permission to execute this moderation action."
        )
        await reply_box(interaction, err_tpl, title="PERMISSION DENIED", status="danger", ephemeral=True)
        return False

    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Rule violation."):
        if not await self.require_mod_permission(interaction, "ban_members", "Ban Members"):
            return
        gid = str(interaction.guild.id)
        if interaction.user.top_role <= member.top_role and interaction.user != interaction.guild.owner:
            err_tpl = db.custom_responses.get(gid, {}).get("hierarchy_err", "You cannot moderate someone with a higher or equal role hierarchy.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="HIERARCHY CONFLICT", status="danger", ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role and member != interaction.guild.owner:
            err_tpl = db.custom_responses.get(gid, {}).get("perm_err_ban", "Friday's role hierarchy is not high enough to ban this user.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="PERMISSION FAULT", status="danger", ephemeral=True)
            return
        try:
            await member.ban(reason=reason)
            msg_fmt = db.custom_responses.get(gid, {}).get("ban_success", "Successfully banned {member}.\nReason: {reason}")
            formatted = msg_fmt.replace("{member}", member.mention).replace("{reason}", reason)
            await reply_box(interaction, formatted, title="BAN EXECUTED", status="danger")
        except discord.Forbidden:
            err_tpl = db.custom_responses.get(gid, {}).get("perm_err_ban", "Friday lacks permission or role hierarchy to ban this user.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="PERMISSION FAULT", status="danger", ephemeral=True)

    async def unban_autocomplete(self, interaction: discord.Interaction, current: str):
        choices = []
        try:
            async for ban_entry in interaction.guild.bans(limit=50):
                u = ban_entry.user
                label = f"{u.name} ({u.id})"
                if current.lower() in label.lower() or current.lower() in u.name.lower():
                    choices.append(app_commands.Choice(name=label[:100], value=str(u.id)))
                if len(choices) >= 25:
                    break
        except Exception:
            pass
        return choices

    @app_commands.command(name="unban", description="Unban a user by their username, tag, or User ID.")
    @app_commands.autocomplete(user=unban_autocomplete)
    @app_commands.default_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user: str, reason: str = "Pardoned."):
        if not await self.require_mod_permission(interaction, "ban_members", "Ban Members"):
            return
        await interaction.response.defer(ephemeral=False)
        guild = interaction.guild
        gid = str(interaction.guild.id)
        target_user = None

        # 1. Direct ID check (if user is numeric string or from autocomplete)
        if user.isdigit():
            user_id = int(user)
            try:
                ban_entry = await guild.fetch_ban(discord.Object(id=user_id))
                target_user = ban_entry.user
            except Exception:
                target_user = discord.Object(id=user_id)

        # 2. Search banned list by username or global name or tag
        if not target_user or isinstance(target_user, discord.Object):
            search_str = user.lower().strip()
            try:
                async for ban_entry in guild.bans(limit=1000):
                    b_user = ban_entry.user
                    if (b_user.name.lower() == search_str or
                        (b_user.global_name and b_user.global_name.lower() == search_str) or
                        str(b_user).lower() == search_str or
                        str(b_user.id) == search_str):
                        target_user = b_user
                        break
            except Exception:
                pass

        if not target_user:
            err_tpl = db.custom_responses.get(gid, {}).get("unban_not_found", "Could not locate any banned user record matching **{user}**.")
            await reply_box(interaction, err_tpl.replace("{user}", user), title="LOOKUP ERROR", status="warning", ephemeral=True)
            return

        try:
            await guild.unban(target_user, reason=reason)
            display_name = target_user.name if hasattr(target_user, 'name') else f"ID {user}"
            msg_fmt = db.custom_responses.get(gid, {}).get("unban_success", "Successfully pardoned and unbanned **{member}**.")
            formatted = msg_fmt.replace("{member}", display_name)
            await reply_box(interaction, formatted, title="UNBAN EXECUTED", status="success")

            # Log to audit-banned channel if configured
            log_id = db.server_logs.get(gid, {}).get("audit-banned")
            if log_id:
                log_channel = self.bot.get_channel(log_id)
                if log_channel:
                    audit_embed = make_box_embed(
                        title="AUDIT: USER UNBANNED",
                        description=f"• Target: **{display_name}**\n• Staff: {interaction.user.mention}\n• Reason: {reason}",
                        status="info"
                    )
                    await log_channel.send(embed=audit_embed)
        except discord.NotFound:
            await reply_box(interaction, "That user is not currently recorded on the server ban list.", title="NOT BANNED", status="warning", ephemeral=True)
        except discord.Forbidden:
            err_tpl = db.custom_responses.get(gid, {}).get("perm_err_unban", "Friday lacks permission to unban users in this server.")
            await reply_box(interaction, err_tpl.replace("{user}", user), title="PERMISSION FAULT", status="danger", ephemeral=True)
        except Exception as e:
            await reply_box(interaction, f"Error processing unban: {e}", title="EXECUTION ERROR", status="danger", ephemeral=True)

    @app_commands.command(name="timeout", description="Timeout a member for a set number of minutes.")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Rule violation."):
        if not await self.require_mod_permission(interaction, "moderate_members", "Moderate Members (Timeout)"):
            return
        gid = str(interaction.guild.id)
        if interaction.user.top_role <= member.top_role and interaction.user != interaction.guild.owner:
            err_tpl = db.custom_responses.get(gid, {}).get("hierarchy_err", "You cannot moderate someone with a higher or equal role hierarchy.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="HIERARCHY CONFLICT", status="danger", ephemeral=True)
            return
        if member.guild_permissions.administrator:
            err_tpl = db.custom_responses.get(gid, {}).get("admin_timeout_err", "Cannot apply timeout to a server Administrator.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="IMMUNITY RESTRICTION", status="warning", ephemeral=True)
            return
        if member.top_role >= interaction.guild.me.top_role and member != interaction.guild.owner:
            err_tpl = db.custom_responses.get(gid, {}).get("perm_err_timeout", "Friday's role hierarchy is not high enough to timeout this user.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="PERMISSION FAULT", status="danger", ephemeral=True)
            return
        try:
            duration = datetime.timedelta(minutes=minutes)
            await member.timeout(duration, reason=reason)
            resp_tpl = db.custom_responses.get(gid, {}).get("timeout_success", "{member} timed out for **{minutes}** minutes.\nReason: {reason}")
            formatted = resp_tpl.replace("{member}", member.mention).replace("{minutes}", str(minutes)).replace("{reason}", reason)
            await reply_box(interaction, formatted, title="TIMEOUT APPLIED", status="warning")
            
            log_id = db.server_logs.get(gid, {}).get("audit-timeouts")
            if log_id: 
                log_channel = self.bot.get_channel(log_id)
                if log_channel:
                    audit_embed = make_box_embed(
                        title="AUDIT: TIMEOUT ENFORCED",
                        description=f"• Target: {member.mention}\n• Duration: `{minutes}m`\n• Staff: {interaction.user.mention}\n• Reason: {reason}",
                        status="warning"
                    )
                    await log_channel.send(embed=audit_embed)
        except discord.Forbidden:
            err_tpl = db.custom_responses.get(gid, {}).get("perm_err_timeout", "Friday lacks permission to modify this user's timeout status.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="PERMISSION FAULT", status="danger", ephemeral=True)

    @app_commands.command(name="untimeout", description="Remove a timeout from a member.")
    @app_commands.default_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Timeout lifted."):
        if not await self.require_mod_permission(interaction, "moderate_members", "Moderate Members (Timeout)"):
            return
        gid = str(interaction.guild.id)
        if interaction.user.top_role <= member.top_role and interaction.user != interaction.guild.owner:
            err_tpl = db.custom_responses.get(gid, {}).get("hierarchy_err", "You cannot remove a timeout from someone with a higher or equal role.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="HIERARCHY CONFLICT", status="danger", ephemeral=True)
            return

        if not member.is_timed_out():
            err_tpl = db.custom_responses.get(gid, {}).get("not_timed_out", "{member} does not currently have an active timeout.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="NO TIMEOUT ACTIVE", status="info", ephemeral=True)
            return

        if member.guild_permissions.administrator:
            err_tpl = db.custom_responses.get(gid, {}).get("admin_timeout_err", "Discord restricts timeout modifications on server Administrators.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="IMMUNITY RESTRICTION", status="warning", ephemeral=True)
            return

        if member.top_role >= interaction.guild.me.top_role and member != interaction.guild.owner:
            err_tpl = db.custom_responses.get(gid, {}).get("perm_err_timeout", "Friday's role hierarchy is not high enough to modify {member}'s timeout status.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="PERMISSION FAULT", status="danger", ephemeral=True)
            return

        try:
            await member.timeout(None, reason=reason)
            resp_tpl = db.custom_responses.get(gid, {}).get("untimeout_success", "Timeout lifted for {member}.\nReason: {reason}")
            formatted = resp_tpl.replace("{member}", member.mention).replace("{reason}", reason)
            await reply_box(interaction, formatted, title="TIMEOUT RESCINDED", status="success")
        except discord.Forbidden:
            err_tpl = db.custom_responses.get(gid, {}).get("perm_err_timeout", "Friday lacks permission to modify this user's timeout status.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="PERMISSION FAULT", status="danger", ephemeral=True)

    @app_commands.command(name="purge", description="Delete a specific number of recent messages in this channel.")
    @app_commands.default_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: int):
        if not await self.require_mod_permission(interaction, "manage_messages", "Manage Messages"):
            return
        await interaction.response.defer(ephemeral=True)
        gid = str(interaction.guild.id)
        try:
            deleted = await interaction.channel.purge(limit=amount)
            msg_fmt = db.custom_responses.get(gid, {}).get("purge_success", "Successfully purged {count} messages from this channel.")
            formatted = msg_fmt.replace("{count}", str(len(deleted)))
            await reply_box(interaction, formatted, title="PURGE EXECUTED", status="info", ephemeral=True)
        except discord.Forbidden:
            err_tpl = db.custom_responses.get(gid, {}).get("perm_err_purge", "Friday lacks Manage Messages permission in this channel.")
            await reply_box(interaction, err_tpl, title="PERMISSION FAULT", status="danger", ephemeral=True)
        except discord.HTTPException:
            await reply_box(interaction, "Discord restricts bots from bulk-deleting messages older than 14 days.", title="PURGE RESTRICTION", status="warning", ephemeral=True)

    async def execute_channel_lock(self, target, user, reason: str = "Channel locked by staff.") -> tuple[bool, str, list[int]]:
        """Ironclad persistent channel lock: locks @everyone and all member roles that have send_messages=True."""
        if isinstance(target, discord.Thread):
            if target.locked:
                return False, "This thread is already locked.", []
            try:
                await target.edit(locked=True, reason=f"Thread locked by {user}: {reason}")
                db.data.setdefault("locked_channels", {})[str(target.id)] = {
                    "is_thread": True,
                    "guild_id": str(target.guild.id),
                    "locked_by": user.id,
                    "timestamp": time.time(),
                    "roles": []
                }
                db.save_data()
                return True, "Thread locked.", []
            except discord.Forbidden:
                return False, "Friday lacks permission to lock this thread.", []

        default_role = target.guild.default_role
        current_ow = target.overwrites_for(default_role)
        current_ow.send_messages = False
        current_ow.add_reactions = False
        if hasattr(current_ow, "send_messages_in_threads"):
            current_ow.send_messages_in_threads = False
        if hasattr(current_ow, "create_public_threads"):
            current_ow.create_public_threads = False
        if hasattr(current_ow, "create_private_threads"):
            current_ow.create_private_threads = False

        try:
            await target.set_permissions(default_role, overwrite=current_ow, reason=f"Channel locked by {user}: {reason}")
        except discord.Forbidden:
            return False, "Friday lacks Manage Channels permission to modify channel overwrites.", []

        affected_roles = []
        # In Discord, role overwrites override @everyone. Check existing overwrites to deny non-staff member roles
        for target_obj, ow in list(target.overwrites.items()):
            if isinstance(target_obj, discord.Role) and target_obj != default_role:
                # Do NOT lock staff roles with administrative/mod powers
                if not (target_obj.permissions.administrator or target_obj.permissions.manage_guild or target_obj.permissions.manage_channels):
                    if ow.send_messages is True:
                        ow.send_messages = False
                        if hasattr(ow, "send_messages_in_threads") and ow.send_messages_in_threads is True:
                            ow.send_messages_in_threads = False
                        if hasattr(ow, "create_public_threads") and ow.create_public_threads is True:
                            ow.create_public_threads = False
                        if hasattr(ow, "create_private_threads") and ow.create_private_threads is True:
                            ow.create_private_threads = False
                        try:
                            await target.set_permissions(target_obj, overwrite=ow, reason=f"Channel locked by {user}: {reason}")
                            affected_roles.append(target_obj.id)
                        except Exception:
                            pass

        db.data.setdefault("locked_channels", {})[str(target.id)] = {
            "is_thread": False,
            "guild_id": str(target.guild.id),
            "locked_by": user.id,
            "timestamp": time.time(),
            "roles": affected_roles
        }
        db.save_data()
        return True, "Channel locked.", affected_roles

    async def execute_channel_unlock(self, target, user, reason: str = "Channel unlocked by staff.") -> tuple[bool, str, int]:
        """Unlocks channel and restores permissions for @everyone and previously denied member roles."""
        if isinstance(target, discord.Thread):
            if not target.locked:
                return False, "This thread is already unlocked.", 0
            try:
                await target.edit(locked=False, reason=f"Thread unlocked by {user}: {reason}")
                db.data.setdefault("locked_channels", {}).pop(str(target.id), None)
                db.save_data()
                return True, "Thread unlocked.", 0
            except discord.Forbidden:
                return False, "Friday lacks permission to unlock this thread.", 0

        # 1. Pop locked_channels record and register in _unlocking_channels BEFORE modifying permissions
        # This completely prevents on_guild_channel_update race condition where Discord events re-lock the channel
        stored_info = db.data.setdefault("locked_channels", {}).pop(str(target.id), None)
        db.save_data()

        self._unlocking_channels.add(target.id)
        try:
            default_role = target.guild.default_role
            current_ow = target.overwrites_for(default_role)
            current_ow.send_messages = None
            current_ow.add_reactions = None
            if hasattr(current_ow, "send_messages_in_threads"):
                current_ow.send_messages_in_threads = None
            if hasattr(current_ow, "create_public_threads"):
                current_ow.create_public_threads = None
            if hasattr(current_ow, "create_private_threads"):
                current_ow.create_private_threads = None

            try:
                await target.set_permissions(default_role, overwrite=current_ow, reason=f"Channel unlocked by {user}: {reason}")
            except discord.Forbidden:
                # If failed due to lack of bot permissions, restore database record
                if stored_info:
                    db.data.setdefault("locked_channels", {})[str(target.id)] = stored_info
                    db.save_data()
                return False, "Friday lacks Manage Channels permission to modify channel overwrites.", 0

            restored_count = 0
            if stored_info and isinstance(stored_info, dict):
                for r_id in stored_info.get("roles", []):
                    role_obj = target.guild.get_role(int(r_id))
                    if role_obj:
                        ow = target.overwrites_for(role_obj)
                        ow.send_messages = True
                        if hasattr(ow, "send_messages_in_threads"):
                            ow.send_messages_in_threads = None
                        if hasattr(ow, "create_public_threads"):
                            ow.create_public_threads = None
                        if hasattr(ow, "create_private_threads"):
                            ow.create_private_threads = None
                        try:
                            await target.set_permissions(role_obj, overwrite=ow, reason=f"Channel unlocked by {user}: {reason}")
                            restored_count += 1
                        except Exception:
                            pass

            return True, "Channel unlocked.", restored_count
        finally:
            self._unlocking_channels.discard(target.id)

    @app_commands.command(name="lock", description="Lock a text or voice channel chat to prevent regular members from chatting.")
    @app_commands.describe(
        channel="The text or voice channel to lock (leave empty for current channel)",
        reason="Reason for locking the channel"
    )
    @app_commands.default_permissions(manage_channels=True)
    async def lock(
        self,
        interaction: discord.Interaction,
        channel: Optional[Union[discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread]] = None,
        reason: str = "Channel locked by staff."
    ):
        if not await self.require_mod_permission(interaction, "manage_channels", "Manage Channels"):
            return
        target = channel or interaction.channel
        if not isinstance(target, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread)):
            await reply_box(interaction, "Only text, voice, or stage channels (and threads) can be locked.", title="INVALID TARGET", status="error", ephemeral=True)
            return

        bot_member = interaction.guild.me or interaction.guild.get_member(self.bot.user.id)
        if bot_member and not target.permissions_for(bot_member).manage_channels:
            await reply_box(interaction, "Friday lacks the **Manage Channels** permission in that channel.", title="PERMISSION FAULT", status="error", ephemeral=True)
            return

        channel_type_name = "Voice Chat" if isinstance(target, discord.VoiceChannel) else ("Stage Chat" if isinstance(target, discord.StageChannel) else ("Thread" if isinstance(target, discord.Thread) else "Channel"))

        # Check if already locked
        if isinstance(target, discord.Thread):
            if target.locked:
                await reply_box(interaction, f"This thread ({target.mention}) is already locked.", title="ALREADY LOCKED", status="info", ephemeral=True)
                return
        else:
            default_role = interaction.guild.default_role
            current_ow = target.overwrites_for(default_role)
            if current_ow.send_messages is False and str(target.id) in db.data.get("locked_channels", {}):
                await reply_box(interaction, f"This {channel_type_name.lower()} ({target.mention}) is already locked.", title="ALREADY LOCKED", status="info", ephemeral=True)
                return

        success, err_msg, affected = await self.execute_channel_lock(target, interaction.user, reason=reason)
        if not success:
            await reply_box(interaction, err_msg, title="LOCK FAILED", status="error", ephemeral=True)
            return

        lock_embed = make_box_embed(
            title=f"{channel_type_name.upper()} LOCKED",
            description=f"🔒 This {channel_type_name.lower()} has been locked by {interaction.user.mention}.\n\n**Reason:** {reason}\n*Regular members cannot send messages until unlocked by staff.*",
            status="error"
        )
        if target.id == interaction.channel_id:
            await interaction.response.send_message(embed=lock_embed)
        else:
            await target.send(embed=lock_embed)
            await reply_box(interaction, f"Successfully locked {target.mention}.", title=f"{channel_type_name.upper()} LOCKED", status="error", ephemeral=True)

    @app_commands.command(name="unlock", description="Unlock a previously locked text or voice channel chat.")
    @app_commands.describe(
        channel="The text or voice channel to unlock (leave empty for current channel)",
        reason="Reason for unlocking the channel"
    )
    @app_commands.default_permissions(manage_channels=True)
    async def unlock(
        self,
        interaction: discord.Interaction,
        channel: Optional[Union[discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread]] = None,
        reason: str = "Channel unlocked by staff."
    ):
        if not await self.require_mod_permission(interaction, "manage_channels", "Manage Channels"):
            return
        target = channel or interaction.channel
        if not isinstance(target, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread)):
            await reply_box(interaction, "Only text, voice, or stage channels (and threads) can be unlocked.", title="INVALID TARGET", status="error", ephemeral=True)
            return

        bot_member = interaction.guild.me or interaction.guild.get_member(self.bot.user.id)
        if bot_member and not target.permissions_for(bot_member).manage_channels:
            await reply_box(interaction, "Friday lacks the **Manage Channels** permission in that channel.", title="PERMISSION FAULT", status="error", ephemeral=True)
            return

        channel_type_name = "Voice Chat" if isinstance(target, discord.VoiceChannel) else ("Stage Chat" if isinstance(target, discord.StageChannel) else ("Thread" if isinstance(target, discord.Thread) else "Channel"))

        # Check if channel is already unlocked
        if isinstance(target, discord.Thread):
            if not target.locked:
                await reply_box(interaction, f"This thread ({target.mention}) is already unlocked.", title="ALREADY UNLOCKED", status="info", ephemeral=True)
                return
        else:
            default_role = interaction.guild.default_role
            current_ow = target.overwrites_for(default_role)
            if current_ow.send_messages is not False and str(target.id) not in db.data.get("locked_channels", {}):
                await reply_box(interaction, f"This {channel_type_name.lower()} ({target.mention}) is already unlocked.", title="ALREADY UNLOCKED", status="info", ephemeral=True)
                return

        success, err_msg, restored = await self.execute_channel_unlock(target, interaction.user, reason=reason)
        if not success:
            await reply_box(interaction, err_msg, title="UNLOCK FAILED", status="error", ephemeral=True)
            return

        unlock_embed = make_box_embed(
            title=f"{channel_type_name.upper()} UNLOCKED",
            description=f"🔓 This {channel_type_name.lower()} has been unlocked by {interaction.user.mention}.\n\n**Reason:** {reason}\n*Members may now send messages and participate in chat.*",
            status="success"
        )
        if target.id == interaction.channel_id:
            await interaction.response.send_message(embed=unlock_embed)
        else:
            await target.send(embed=unlock_embed)
            await reply_box(interaction, f"Successfully unlocked {target.mention}.", title=f"{channel_type_name.upper()} UNLOCKED", status="success", ephemeral=True)

    @app_commands.command(name="slowmode", description="Set or disable the slowmode chat cooldown for a text or voice channel.")
    @app_commands.describe(
        seconds="Cooldown in seconds (0 to disable slowmode, max 21600 / 6h)",
        channel="The channel to modify (leave empty for current channel)"
    )
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, 21600],
        channel: Optional[Union[discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread]] = None
    ):
        if not await self.require_mod_permission(interaction, "manage_channels", "Manage Channels"):
            return
        target = channel or interaction.channel
        if not isinstance(target, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread)):
            await reply_box(interaction, "Only text, voice, or stage channels (and threads) support slowmode.", title="INVALID TARGET", status="error", ephemeral=True)
            return

        try:
            await target.edit(slowmode_delay=seconds, reason=f"Slowmode adjusted by {interaction.user}")
            if seconds == 0:
                await reply_box(interaction, f"Slowmode cooldown has been disabled for {target.mention}.", title="SLOWMODE DISABLED", status="success")
            else:
                await reply_box(interaction, f"Slowmode cooldown for {target.mention} has been set to **{seconds} seconds**.", title="SLOWMODE UPDATED", status="info")
        except discord.Forbidden:
            await reply_box(interaction, "Friday lacks permission to edit channel settings.", title="PERMISSION FAULT", status="error", ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(
        member="The member to kick",
        reason="Reason for kicking the member"
    )
    @app_commands.default_permissions(kick_members=True)
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided."
    ):
        if not await self.require_mod_permission(interaction, "kick_members", "Kick Members"):
            return
        if member.id == interaction.user.id:
            await reply_box(interaction, "You cannot kick yourself.", title="INVALID TARGET", status="warning", ephemeral=True)
            return

        if member.id == interaction.guild.owner_id:
            await reply_box(interaction, "You cannot kick the server owner.", title="INVALID TARGET", status="error", ephemeral=True)
            return

        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await reply_box(interaction, f"You cannot kick {member.mention} because their highest role is equal to or higher than yours.", title="HIERARCHY ERROR", status="error", ephemeral=True)
            return

        bot_member = interaction.guild.me or interaction.guild.get_member(self.bot.user.id)
        if bot_member and member.top_role >= bot_member.top_role:
            await reply_box(interaction, f"Friday cannot kick {member.mention} because their highest role is higher than Friday's top role.", title="HIERARCHY ERROR", status="error", ephemeral=True)
            return

        try:
            try:
                dm_embed = make_box_embed(
                    title="YOU WERE KICKED",
                    description=f"You have been kicked from **{interaction.guild.name}**.\n\n**Reason:** {reason}",
                    status="error"
                )
                await member.send(embed=dm_embed)
            except Exception:
                pass

            await member.kick(reason=f"Kicked by {interaction.user}: {reason}")
            await reply_box(interaction, f"👢 **{member}** has been kicked from the server.\n**Reason:** {reason}", title="MEMBER KICKED", status="error")
        except discord.Forbidden:
            await reply_box(interaction, "Friday lacks permission to kick this member.", title="PERMISSION FAULT", status="error", ephemeral=True)

    @app_commands.command(name="warn", description="Issue a formal warning to a server member (via DM, Chat, or Both).")
    @app_commands.describe(
        member="The server member to warn",
        reason="Reason for issuing the warning",
        delivery="Where to send the warning notice: Both, DM Only, or Channel Chat Only"
    )
    @app_commands.choices(delivery=[
        app_commands.Choice(name="Both (DM + Channel Chat)", value="both"),
        app_commands.Choice(name="DM Only (Private Warning)", value="dm"),
        app_commands.Choice(name="Channel Chat Only (Public)", value="chat"),
    ])
    @app_commands.default_permissions(moderate_members=True)
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Rule violation.",
        delivery: str = "both"
    ):
        if not await self.require_mod_permission(interaction, "moderate_members", "Moderate Members"):
            return
        gid = str(interaction.guild.id)
        uid = str(member.id)

        # 1. Validation checks
        if member.bot:
            await reply_box(interaction, "Bot accounts cannot be warned.", title="INVALID TARGET", status="warning", ephemeral=True)
            return

        if member.id == interaction.user.id:
            await reply_box(interaction, "You cannot issue a warning to yourself.", title="INVALID TARGET", status="warning", ephemeral=True)
            return

        if interaction.user.top_role <= member.top_role and interaction.user != interaction.guild.owner:
            err_tpl = db.custom_responses.get(gid, {}).get("hierarchy_err", "You cannot moderate someone with a higher or equal role hierarchy.")
            await reply_box(interaction, err_tpl.replace("{member}", member.mention), title="HIERARCHY CONFLICT", status="danger", ephemeral=True)
            return

        if member.guild_permissions.administrator or member == interaction.guild.owner:
            await reply_box(interaction, "Cannot issue warnings to a server Administrator or Server Owner.", title="IMMUNITY RESTRICTION", status="warning", ephemeral=True)
            return

        if member.top_role >= interaction.guild.me.top_role and member != interaction.guild.owner:
            await reply_box(interaction, "Friday's role hierarchy is not high enough to moderate this user.", title="PERMISSION FAULT", status="danger", ephemeral=True)
            return

        # 2. Record warning in database
        if not hasattr(db, "warnings") or not isinstance(db.warnings, dict):
            db.warnings = {}
        if gid not in db.warnings:
            db.warnings[gid] = {}
        if uid not in db.warnings[gid]:
            db.warnings[gid][uid] = []

        warn_id = len(db.warnings[gid][uid]) + 1
        now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        warn_entry = {
            "warn_id": warn_id,
            "moderator_id": interaction.user.id,
            "moderator_name": interaction.user.display_name,
            "reason": reason,
            "delivery": delivery,
            "timestamp": now_ts
        }
        db.warnings[gid][uid].append(warn_entry)
        db.save_data()
        total_warns = len(db.warnings[gid][uid])

        # 3. Direct Message Delivery
        dm_delivered = False
        if delivery in ("both", "dm"):
            dm_embed = make_box_embed(
                title="▲ OFFICIAL WARNING",
                description=(
                    f"You have received a formal warning in **{interaction.guild.name}**.\n\n"
                    f"• **Reason:** {reason}\n"
                    f"• **Moderator:** {interaction.user.display_name}\n"
                    f"• **Warning Count:** `{total_warns}`\n\n"
                    f"Please respect the server rules to avoid timeouts or permanent removal."
                ),
                status="warning"
            )
            try:
                await member.send(embed=dm_embed)
                dm_delivered = True
            except (discord.Forbidden, discord.HTTPException):
                dm_delivered = False

        # 4. Response Dispatch
        if delivery == "dm":
            status_text = "Delivered to member's DM ✓" if dm_delivered else "DM delivery failed (User's DMs are closed/blocked) ✕"
            desc = (
                f"• **Target:** {member.mention}\n"
                f"• **Reason:** {reason}\n"
                f"• **Mode:** `DM Only`\n"
                f"• **Status:** {status_text}\n"
                f"• **Total Warnings:** `{total_warns}`"
            )
            await reply_box(interaction, desc, title="WARNING ISSUED", status="warning", ephemeral=True)
        else:
            dm_note = ""
            if delivery == "both":
                dm_note = f"\n• **DM Delivery:** {'Delivered to DM ✓' if dm_delivered else 'DM Closed / Blocked ✕'}"
            desc = (
                f"• **Target:** {member.mention}\n"
                f"• **Reason:** {reason}\n"
                f"• **Moderator:** {interaction.user.mention}\n"
                f"• **Total Warnings:** `{total_warns}`"
                f"{dm_note}"
            )
            await reply_box(interaction, desc, title="WARNING ISSUED", status="warning", ephemeral=False)

        # 5. Audit Logging
        log_id = db.server_logs.get(gid, {}).get("audit-warns") or db.server_logs.get(gid, {}).get("audit-abuse")
        if log_id:
            log_channel = self.bot.get_channel(log_id)
            if log_channel:
                audit_embed = make_box_embed(
                    title="AUDIT: MEMBER WARNED",
                    description=(
                        f"• Target: {member.mention} (`{member.id}`)\n"
                        f"• Staff: {interaction.user.mention}\n"
                        f"• Reason: {reason}\n"
                        f"• Mode: `{delivery.upper()}`\n"
                        f"• Total Warnings:** `{total_warns}`"
                    ),
                    status="warning"
                )
                await log_channel.send(embed=audit_embed)

    @app_commands.command(name="warnings", description="View all recorded warnings for a member.")
    @app_commands.describe(member="The member whose warnings you want to review")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        gid = str(interaction.guild.id)
        uid = str(member.id)
        warn_list = db.warnings.get(gid, {}).get(uid, [])

        if not warn_list:
            await reply_box(interaction, f"**{member.display_name}** has a clean record with **0** active warnings.", title="NO WARNINGS", status="success", ephemeral=True)
            return

        desc_lines = [f"**Total Active Warnings:** `{len(warn_list)}` for {member.mention}\n"]
        for w in warn_list[-10:]:
            desc_lines.append(
                f"• **[#{w.get('warn_id')}]** {w.get('reason')}\n"
                f"  └ *By:* `{w.get('moderator_name', 'Staff')}` • *Date:* `{w.get('timestamp', 'Unknown')}`"
            )

        if len(warn_list) > 10:
            desc_lines.append(f"\n*(Showing 10 most recent warnings out of {len(warn_list)})*")

        await reply_box(interaction, "\n".join(desc_lines), title="MEMBER WARNING HISTORY", status="warning", ephemeral=True)

    @app_commands.command(name="clearwarns", description="Clear all warnings or a specific warning for a member.")
    @app_commands.describe(
        member="The member whose warnings should be cleared",
        warn_id="Optional: Specific Warning ID to remove (Leave empty to clear all)"
    )
    @app_commands.default_permissions(moderate_members=True)
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member, warn_id: int = None):
        if not await self.require_mod_permission(interaction, "moderate_members", "Moderate Members"):
            return
        gid = str(interaction.guild.id)
        uid = str(member.id)
        warn_list = db.warnings.get(gid, {}).get(uid, [])

        if not warn_list:
            await reply_box(interaction, f"**{member.display_name}** has no active warnings to clear.", title="NO WARNINGS FOUND", status="info", ephemeral=True)
            return

        if warn_id is not None:
            initial_count = len(warn_list)
            warn_list = [w for w in warn_list if w.get("warn_id") != warn_id]
            if len(warn_list) == initial_count:
                await reply_box(interaction, f"Warning ID `#{warn_id}` was not found for {member.mention}.", title="WARNING NOT FOUND", status="warning", ephemeral=True)
                return
            db.warnings[gid][uid] = warn_list
            db.save_data()
            await reply_box(interaction, f"Successfully removed warning `#{warn_id}` from {member.mention}. Remaining warnings: `{len(warn_list)}`.", title="WARNING REMOVED", status="success")
        else:
            count = len(warn_list)
            db.warnings[gid][uid] = []
            db.save_data()
            await reply_box(interaction, f"Successfully cleared all **{count}** warning(s) for {member.mention}.", title="WARNINGS CLEARED", status="success")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Trigger 1: Nickname Change via Mention: @Friday nick @User [New Nickname] OR @Friday @User [New Nickname]
        bot_mention_str1 = f"<@{self.bot.user.id}>"
        bot_mention_str2 = f"<@!{self.bot.user.id}>"

        raw_content = message.content.strip()
        if raw_content.startswith(bot_mention_str1) or raw_content.startswith(bot_mention_str2):
            import re
            parts = raw_content.split()
            if len(parts) >= 2:
                # Detect explicit nickname commands or mention syntax
                is_explicit_cmd = False
                target_member = None
                new_nickname = None

                # Format A: @Friday nick/setnick/nickname @User [New Nickname]
                if parts[1].lower() in ("nick", "setnick", "nickname", "resetnick") and len(parts) >= 3:
                    is_explicit_cmd = True
                    target_match = re.match(r'^<@!?(\d+)>$', parts[2])
                    if target_match:
                        target_member = message.guild.get_member(int(target_match.group(1)))
                        if parts[1].lower() != "resetnick" and len(parts) > 3:
                            new_nickname = " ".join(parts[3:])

                # Format B: @Friday @User [New Nickname]
                else:
                    target_match = re.match(r'^<@!?(\d+)>$', parts[1])
                    if target_match:
                        potential_target = message.guild.get_member(int(target_match.group(1)))
                        if potential_target:
                            remainder = " ".join(parts[2:]).strip()
                            # Check conversational indicators: question marks, common question/chat words, or long sentences
                            conversational_keywords = re.compile(
                                r'(?:who|what|why|where|when|how|is|are|tell|help|kya|kaun|kaise|kaisi|batao|kyun|kaisa|hi|hello|hey|listen|sun|suno)|\?',
                                re.IGNORECASE
                            )
                            # If it looks conversational or has question marks, ignore in moderation cog and let AI handle it!
                            if not conversational_keywords.search(remainder) and len(remainder) <= 32 and len(parts[2:]) <= 3:
                                target_member = potential_target
                                new_nickname = remainder if remainder else None
                                is_explicit_cmd = len(parts) == 2 or bool(remainder)

                if target_member:
                    perms = message.author.guild_permissions
                    gid = str(message.guild.id)

                    # 1. Author Permission Check
                    if not (perms.administrator or perms.manage_nicknames):
                        # If user typed an explicit nickname command without permission, reject cleanly
                        if is_explicit_cmd and (parts[1].lower() in ("nick", "setnick", "nickname", "resetnick") or len(parts) == 2):
                            err_tpl = db.custom_responses.get(gid, {}).get("nick_perm_err", "Only staff with Manage Nicknames or Administrator permissions can change nicknames.")
                            embed = make_box_embed(title="ACCESS DENIED", description=err_tpl, status="danger")
                            await message.reply(embed=embed, mention_author=False)
                            return
                        # Otherwise, let Friday AI conversationally answer the comment/question!
                        return

                    # 2. Server Owner Protection Check
                    if target_member.id == message.guild.owner_id and message.author.id != message.guild.owner_id:
                        embed = make_box_embed(
                            title="HIERARCHY RESTRICTION",
                            description="You cannot change the nickname of the Server Owner.",
                            status="danger"
                        )
                        await message.reply(embed=embed, mention_author=False)
                        return

                    # 3. Author Role Hierarchy Check
                    if target_member.top_role >= message.author.top_role and message.author.id != message.guild.owner_id:
                        embed = make_box_embed(
                            title="HIERARCHY RESTRICTION",
                            description=f"You cannot modify {target_member.mention}'s nickname because their role is higher than or equal to yours.",
                            status="danger"
                        )
                        await message.reply(embed=embed, mention_author=False)
                        return

                    # 4. Friday Bot Role Hierarchy Check
                    if target_member.top_role >= message.guild.me.top_role or target_member.id == message.guild.owner_id:
                        err_tpl = db.custom_responses.get(gid, {}).get("nick_bot_err", "Friday does not have permission or role hierarchy to modify this user's nickname.")
                        embed = make_box_embed(title="PERMISSION FAULT", description=err_tpl, status="danger")
                        await message.reply(embed=embed, mention_author=False)
                        return

                    # 5. Execute Nickname Update
                    try:
                        await target_member.edit(nick=new_nickname, reason=f"Nickname update commanded by {message.author.name} ({message.author.id})")
                        if new_nickname:
                            resp_tpl = db.custom_responses.get(gid, {}).get("nick_success", "Nickname of {member} changed to **{nick}**.")
                            desc = resp_tpl.replace("{member}", target_member.mention).replace("{nick}", new_nickname)
                            embed = make_box_embed(title="NICKNAME UPDATED", description=desc, status="success")
                            await message.reply(embed=embed, mention_author=False)
                        else:
                            resp_tpl = db.custom_responses.get(gid, {}).get("nick_reset", "Nickname of {member} has been successfully reset.")
                            desc = resp_tpl.replace("{member}", target_member.mention)
                            embed = make_box_embed(title="NICKNAME RESET", description=desc, status="success")
                            await message.reply(embed=embed, mention_author=False)
                        return
                    except discord.Forbidden:
                        err_tpl = db.custom_responses.get(gid, {}).get("nick_bot_err", "Friday does not have permission or role hierarchy to modify this user's nickname.")
                        embed = make_box_embed(title="PERMISSION FAULT", description=err_tpl, status="danger")
                        await message.reply(embed=embed, mention_author=False)
                        return
                    except Exception as e:
                        embed = make_box_embed(title="EXECUTION ERROR", description=f"Error changing nickname: {e}", status="danger")
                        await message.reply(embed=embed, mention_author=False)
                        return


    # ───────────────────── Voice Move Commands ─────────────────────

    def _check_voice_perms(self, member: discord.Member, guild: discord.Guild) -> bool:
        """Verify user is Server Owner, Administrator, or possesses Manage Channels / Move Members."""
        if not member or not guild:
            return False
        if member.id == guild.owner_id:
            return True
        perms = member.guild_permissions
        return bool(perms.administrator or perms.manage_channels or perms.move_members or perms.manage_guild)

    def _resolve_members_from_input(
        self,
        guild: discord.Guild,
        text: Optional[str],
        single_member: Optional[discord.Member] = None,
        direct_mentions: Optional[List[discord.Member]] = None
    ) -> List[discord.Member]:
        """Resolves Discord members from mentions, IDs, and names without duplicates."""
        results = []
        seen_ids = set()

        if single_member:
            results.append(single_member)
            seen_ids.add(single_member.id)

        if direct_mentions:
            for m in direct_mentions:
                if isinstance(m, discord.Member) and m.id not in seen_ids:
                    results.append(m)
                    seen_ids.add(m.id)

        if not text:
            return results

        # 1. Regex find all user mentions <@!?(\d+)>
        for match in re.finditer(r'<@!?(\d+)>', text):
            uid = int(match.group(1))
            if uid not in seen_ids:
                m = guild.get_member(uid)
                if m:
                    results.append(m)
                    seen_ids.add(uid)

        # 2. Split remainder by whitespace and commas
        cleaned_text = re.sub(r'<@!?\d+>', ' ', text)
        tokens = [t.strip() for t in re.split(r'[,;\s]+', cleaned_text) if t.strip()]

        for token in tokens:
            if token.isdigit():
                uid = int(token)
                if uid not in seen_ids:
                    m = guild.get_member(uid)
                    if m:
                        results.append(m)
                        seen_ids.add(uid)
                continue

            t_lower = token.lstrip("@").lower()
            if len(t_lower) >= 2:
                for m in guild.members:
                    if m.id in seen_ids:
                        continue
                    d_name = m.display_name.lower()
                    u_name = m.name.lower()
                    if d_name == t_lower or u_name == t_lower:
                        results.append(m)
                        seen_ids.add(m.id)
                        break

        return results

    async def _resolve_voice_channel(self, guild: discord.Guild, text: str) -> Optional[discord.VoiceChannel]:
        """Resolve a voice channel from a mention, ID, or name."""
        if not text or not guild:
            return None
        text_str = str(text).strip()
        m = re.search(r'<#(\d+)>', text_str)
        if m:
            ch = guild.get_channel(int(m.group(1)))
            if isinstance(ch, discord.VoiceChannel):
                return ch
        if text_str.isdigit():
            ch = guild.get_channel(int(text_str))
            if isinstance(ch, discord.VoiceChannel):
                return ch
        clean = text_str.lstrip("#").lower()
        for ch in guild.voice_channels:
            if ch.name.lower() == clean:
                return ch
        for ch in guild.voice_channels:
            if clean in ch.name.lower():
                return ch
        return None

    @app_commands.command(name="move", description="Move specific member(s) to a voice channel.")
    @app_commands.describe(
        target_channel="The destination voice channel to move member(s) to",
        members="Mention members, enter IDs, or names separated by spaces (e.g. @Alex @Bob @Charlie)",
        member="Or pick a single member from the list"
    )
    @app_commands.default_permissions(move_members=True)
    async def move(
        self,
        interaction: discord.Interaction,
        target_channel: discord.VoiceChannel,
        members: Optional[str] = None,
        member: Optional[discord.Member] = None
    ):
        if not self._check_voice_perms(interaction.user, interaction.guild):
            embed = make_box_embed(
                title="ACCESS DENIED",
                description="Only Server Owners, Administrators, and staff with **Manage Channels** or **Move Members** permissions can shift voice members.",
                status="danger"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.move_members:
            embed = make_box_embed(
                title="PERMISSION FAULT",
                description="Friday lacks the **Move Members** permission in this server to transfer members between voice channels.",
                status="danger"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        members_to_process = self._resolve_members_from_input(interaction.guild, members, member)
        if not members_to_process:
            embed = make_box_embed(
                title="NO MEMBERS SPECIFIED",
                description="Please mention or specify at least one member to move (e.g. `/move target_channel: #Voice members: @user1 @user2`).",
                status="warning"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer()

        moved = []
        not_in_vc = []
        already_there = []
        failed = []

        for m in members_to_process:
            if not m.voice or not m.voice.channel:
                not_in_vc.append(m)
            elif m.voice.channel.id == target_channel.id:
                already_there.append(m)
            else:
                try:
                    await m.move_to(target_channel, reason=f"Moved by {interaction.user.name} ({interaction.user.id})")
                    moved.append(m)
                except Exception as e:
                    failed.append((m, str(e)))

        lines = []
        if moved:
            m_list = ", ".join(m.mention for m in moved)
            lines.append(f"✓ **Transferred ({len(moved)}):** {m_list} ➔ {target_channel.mention}")
        if already_there:
            a_list = ", ".join(m.mention for m in already_there)
            lines.append(f"• **Already in {target_channel.mention} ({len(already_there)}):** {a_list}")
        if not_in_vc:
            n_list = ", ".join(m.mention for m in not_in_vc)
            lines.append(f"▲ **Not in any voice channel ({len(not_in_vc)}):** {n_list}")
        if failed:
            f_list = ", ".join(f"{m.mention} ({err})" for m, err in failed)
            lines.append(f"✕ **Failed to move ({len(failed)}):** {f_list}")

        status = "success" if moved else ("warning" if already_there or not_in_vc else "danger")
        embed = make_box_embed(
            title="VOICE MEMBERS SHIFT",
            description="\n\n".join(lines) or "No members were moved.",
            status=status
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="moveall", description="Move all members from one voice channel to another.")
    @app_commands.describe(
        target_channel="The destination voice channel to move all members to",
        source_channel="The source voice channel (defaults to your current voice channel)"
    )
    @app_commands.default_permissions(move_members=True)
    async def moveall(
        self,
        interaction: discord.Interaction,
        target_channel: discord.VoiceChannel,
        source_channel: Optional[discord.VoiceChannel] = None
    ):
        if not self._check_voice_perms(interaction.user, interaction.guild):
            embed = make_box_embed(
                title="ACCESS DENIED",
                description="Only Server Owners, Administrators, and staff with **Manage Channels** or **Move Members** permissions can shift voice members.",
                status="danger"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.move_members:
            embed = make_box_embed(
                title="PERMISSION FAULT",
                description="Friday lacks the **Move Members** permission in this server to transfer members between voice channels.",
                status="danger"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if source_channel is None:
            if interaction.user.voice and interaction.user.voice.channel:
                source_channel = interaction.user.voice.channel
            else:
                embed = make_box_embed(
                    title="SOURCE CHANNEL REQUIRED",
                    description="You are not currently in any voice channel! Please join a voice channel or specify the `source_channel` parameter.",
                    status="warning"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        if source_channel.id == target_channel.id:
            embed = make_box_embed(
                title="IDENTICAL CHANNELS",
                description=f"Source and destination voice channels are identical ({target_channel.mention})!",
                status="warning"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        members_to_move = list(source_channel.members)
        if not members_to_move:
            embed = make_box_embed(
                title="CHANNEL EMPTY",
                description=f"There are no members currently connected to {source_channel.mention}!",
                status="warning"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer()

        moved = []
        failed = []
        for m in members_to_move:
            try:
                await m.move_to(target_channel, reason=f"Mass voice shift commanded by {interaction.user.name} ({interaction.user.id})")
                moved.append(m)
            except Exception as e:
                failed.append((m, str(e)))

        desc = f"Successfully shifted **{len(moved)}** member(s) from {source_channel.mention} to {target_channel.mention}!"
        if moved:
            desc += f"\n\n**Transferred Members ({len(moved)}):**\n> " + ", ".join(m.mention for m in moved)
        if failed:
            desc += f"\n\n✕ **Failed ({len(failed)}):** " + ", ".join(f"{m.mention} ({err})" for m, err in failed)

        embed = make_box_embed(
            title="MASS VOICE MIGRATION",
            description=desc,
            status="success" if moved else "danger"
        )
        await interaction.followup.send(embed=embed)

    @commands.command(name="move")
    async def prefix_move(self, ctx: commands.Context, *args):
        """
        Move members to a voice channel via prefix command.
        Usage:
          !move <#target_channel> <@member1 @member2...>
          !move all <#target_channel> [#source_channel]
        """
        if not self._check_voice_perms(ctx.author, ctx.guild):
            embed = make_box_embed(
                title="ACCESS DENIED",
                description="Only Server Owners, Administrators, and staff with **Manage Channels** or **Move Members** permissions can shift voice members.",
                status="danger"
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        if not ctx.guild.me.guild_permissions.move_members:
            embed = make_box_embed(
                title="PERMISSION FAULT",
                description="Friday lacks the **Move Members** permission in this server to transfer members between voice channels.",
                status="danger"
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        if not args:
            embed = make_box_embed(
                title="COMMAND USAGE: MOVE",
                description=(
                    "**Move specific members:**\n"
                    f"`{ctx.prefix}move <#destination> @member1 @member2...`\n\n"
                    "**Move all members:**\n"
                    f"`{ctx.prefix}move all <#destination> [#source]`\n\n"
                    "*(Or use the slash commands `/move` and `/moveall`)*"
                ),
                status="info"
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        if args[0].lower() == "all":
            remaining = args[1:]
            if not remaining:
                embed = make_box_embed(title="USAGE ERROR", description=f"Usage: `{ctx.prefix}move all <#destination_channel> [#source_channel]`", status="warning")
                await ctx.reply(embed=embed, mention_author=False)
                return

            target_ch = await self._resolve_voice_channel(ctx.guild, remaining[0])
            if not target_ch:
                embed = make_box_embed(title="INVALID CHANNEL", description=f"Could not find destination voice channel `{remaining[0]}`.", status="warning")
                await ctx.reply(embed=embed, mention_author=False)
                return

            source_ch = None
            if len(remaining) > 1:
                source_ch = await self._resolve_voice_channel(ctx.guild, remaining[1])
            elif ctx.author.voice and ctx.author.voice.channel:
                source_ch = ctx.author.voice.channel

            if not source_ch:
                embed = make_box_embed(title="SOURCE CHANNEL REQUIRED", description="You are not in a voice channel! Please join one or specify: `!move all <#dest> <#source>`", status="warning")
                await ctx.reply(embed=embed, mention_author=False)
                return

            await self._run_mass_move(ctx, target_ch, source_ch)
            return

        target_ch = await self._resolve_voice_channel(ctx.guild, args[0])
        if not target_ch:
            embed = make_box_embed(title="INVALID CHANNEL", description=f"First argument must be the destination voice channel. Could not find `{args[0]}`.", status="warning")
            await ctx.reply(embed=embed, mention_author=False)
            return

        raw_members_text = " ".join(args[1:])
        members_list = self._resolve_members_from_input(ctx.guild, raw_members_text, direct_mentions=ctx.message.mentions)
        if not members_list:
            embed = make_box_embed(title="NO MEMBERS SPECIFIED", description=f"Please specify members to move! E.g. `{ctx.prefix}move #{target_ch.name} @user1 @user2`", status="warning")
            await ctx.reply(embed=embed, mention_author=False)
            return

        await self._run_members_move(ctx, target_ch, members_list)

    @commands.command(name="moveall")
    async def prefix_moveall(self, ctx: commands.Context, target: str = None, source: str = None):
        """Move all members from one voice channel to another: !moveall <#dest> [#source]"""
        if not self._check_voice_perms(ctx.author, ctx.guild):
            embed = make_box_embed(
                title="ACCESS DENIED",
                description="Only Server Owners, Administrators, and staff with **Manage Channels** or **Move Members** permissions can shift voice members.",
                status="danger"
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        if not target:
            embed = make_box_embed(title="USAGE ERROR", description=f"Usage: `{ctx.prefix}moveall <#destination_channel> [#source_channel]`", status="info")
            await ctx.reply(embed=embed, mention_author=False)
            return

        target_ch = await self._resolve_voice_channel(ctx.guild, target)
        if not target_ch:
            embed = make_box_embed(title="INVALID CHANNEL", description=f"Could not find voice channel `{target}`.", status="warning")
            await ctx.reply(embed=embed, mention_author=False)
            return

        source_ch = None
        if source:
            source_ch = await self._resolve_voice_channel(ctx.guild, source)
        elif ctx.author.voice and ctx.author.voice.channel:
            source_ch = ctx.author.voice.channel

        if not source_ch:
            embed = make_box_embed(title="SOURCE CHANNEL REQUIRED", description="You are not in a voice channel! Please join one or specify: `!moveall <#dest> <#source>`", status="warning")
            await ctx.reply(embed=embed, mention_author=False)
            return

        await self._run_mass_move(ctx, target_ch, source_ch)

    async def _run_members_move(self, ctx: commands.Context, target_channel: discord.VoiceChannel, members: List[discord.Member]):
        moved = []
        not_in_vc = []
        already_there = []
        failed = []

        for m in members:
            if not m.voice or not m.voice.channel:
                not_in_vc.append(m)
            elif m.voice.channel.id == target_channel.id:
                already_there.append(m)
            else:
                try:
                    await m.move_to(target_channel, reason=f"Moved by {ctx.author.name} ({ctx.author.id})")
                    moved.append(m)
                except Exception as e:
                    failed.append((m, str(e)))

        lines = []
        if moved:
            m_list = ", ".join(m.mention for m in moved)
            lines.append(f"✓ **Transferred ({len(moved)}):** {m_list} ➔ {target_channel.mention}")
        if already_there:
            a_list = ", ".join(m.mention for m in already_there)
            lines.append(f"• **Already in {target_channel.mention} ({len(already_there)}):** {a_list}")
        if not_in_vc:
            n_list = ", ".join(m.mention for m in not_in_vc)
            lines.append(f"▲ **Not in any voice channel ({len(not_in_vc)}):** {n_list}")
        if failed:
            f_list = ", ".join(f"{m.mention} ({err})" for m, err in failed)
            lines.append(f"✕ **Failed to move ({len(failed)}):** {f_list}")

        status = "success" if moved else ("warning" if already_there or not_in_vc else "danger")
        embed = make_box_embed(
            title="VOICE MEMBERS SHIFT",
            description="\n\n".join(lines) or "No members were moved.",
            status=status
        )
        await ctx.reply(embed=embed, mention_author=False)

    async def _run_mass_move(self, ctx: commands.Context, target_channel: discord.VoiceChannel, source_channel: discord.VoiceChannel):
        if source_channel.id == target_channel.id:
            embed = make_box_embed(
                title="IDENTICAL CHANNELS",
                description=f"Source and destination voice channels are identical ({target_channel.mention})!",
                status="warning"
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        members_to_move = list(source_channel.members)
        if not members_to_move:
            embed = make_box_embed(
                title="CHANNEL EMPTY",
                description=f"There are no members currently connected to {source_channel.mention}!",
                status="warning"
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        moved = []
        failed = []
        for m in members_to_move:
            try:
                await m.move_to(target_channel, reason=f"Mass voice shift commanded by {ctx.author.name} ({ctx.author.id})")
                moved.append(m)
            except Exception as e:
                failed.append((m, str(e)))

        desc = f"Successfully shifted **{len(moved)}** member(s) from {source_channel.mention} to {target_channel.mention}!"
        if moved:
            desc += f"\n\n**Transferred Members ({len(moved)}):**\n> " + ", ".join(m.mention for m in moved)
        if failed:
            desc += f"\n\n✕ **Failed ({len(failed)}):** " + ", ".join(f"{m.mention} ({err})" for m, err in failed)

        embed = make_box_embed(
            title="MASS VOICE MIGRATION",
            description=desc,
            status="success" if moved else "danger"
        )
        await ctx.reply(embed=embed, mention_author=False)

    # ─────────────────────────────────────────────────────────────
    # Role Management Slash Commands
    # ─────────────────────────────────────────────────────────────
    role_group = app_commands.Group(
        name="role",
        description="Assign, remove, and inspect roles with hierarchy security.",
        default_permissions=discord.Permissions(manage_roles=True)
    )

    @role_group.command(name="add", description="Assign a role to a server member.")
    @app_commands.describe(member="The member to receive the role", role="The role to assign")
    @app_commands.default_permissions(manage_roles=True)
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if not await self.require_mod_permission(interaction, "manage_roles", "Manage Roles"):
            return
        # 1. Invalid / default / managed role checks
        if role.is_default():
            await reply_box(interaction, "Cannot assign the default @everyone role.", title="INVALID ROLE", status="error", ephemeral=True)
            return
        if role.managed:
            await reply_box(interaction, f"The role {role.mention} is managed by an integration or bot and cannot be assigned manually.", title="INTEGRATION ROLE", status="error", ephemeral=True)
            return

        # 2. Already has role check
        if role in member.roles:
            await reply_box(interaction, f"{member.mention} already has the {role.mention} role.", title="ALREADY ASSIGNED", status="error", ephemeral=True)
            return

        # 3. Hierarchy check: executor vs target role
        if interaction.user.id != interaction.guild.owner_id and role >= interaction.user.top_role:
            await reply_box(
                interaction,
                f"You cannot assign {role.mention} because it is higher than or equal to your highest role ({interaction.user.top_role.mention}).",
                title="HIERARCHY ERROR",
                status="error",
                ephemeral=True
            )
            return

        # 4. Hierarchy check: executor vs target member
        if interaction.user.id != interaction.guild.owner_id and member.top_role >= interaction.user.top_role and member.id != interaction.user.id:
            await reply_box(
                interaction,
                f"You cannot modify roles for {member.mention} because their highest role ({member.top_role.mention}) is equal to or higher than yours.",
                title="HIERARCHY ERROR",
                status="error",
                ephemeral=True
            )
            return

        # 5. Hierarchy check: bot vs target role
        if role >= interaction.guild.me.top_role:
            await reply_box(
                interaction,
                f"Friday cannot assign {role.mention} because it is higher than or equal to Friday's highest role ({interaction.guild.me.top_role.mention}).\n"
                "Please drag Friday's role higher in Server Settings > Roles.",
                title="BOT HIERARCHY LIMIT",
                status="error",
                ephemeral=True
            )
            return

        # 6. Assign role
        try:
            await member.add_roles(role, reason=f"Role added by {interaction.user} ({interaction.user.id})")
            await reply_box(
                interaction,
                f"Successfully added {role.mention} to {member.mention}.",
                title="ROLE ASSIGNED",
                status="success"
            )
        except discord.Forbidden:
            await reply_box(interaction, f"Friday lacks permission to assign {role.mention}.", title="PERMISSION DENIED", status="error", ephemeral=True)
        except Exception as e:
            await reply_box(interaction, f"Failed to add role: {e}", title="EXECUTION ERROR", status="error", ephemeral=True)

    @role_group.command(name="remove", description="Remove a role from a server member.")
    @app_commands.describe(member="The member to remove the role from", role="The role to remove")
    @app_commands.default_permissions(manage_roles=True)
    async def role_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if not await self.require_mod_permission(interaction, "manage_roles", "Manage Roles"):
            return
        # 1. Has role check
        if role not in member.roles:
            await reply_box(interaction, f"{member.mention} does not have the {role.mention} role.", title="ROLE NOT FOUND", status="error", ephemeral=True)
            return

        if role.is_default() or role.managed:
            await reply_box(interaction, f"The role {role.mention} cannot be modified manually.", title="INVALID ROLE", status="error", ephemeral=True)
            return

        # 2. Hierarchy check: executor vs target role
        if interaction.user.id != interaction.guild.owner_id and role >= interaction.user.top_role:
            await reply_box(
                interaction,
                f"You cannot remove {role.mention} because it is higher than or equal to your highest role ({interaction.user.top_role.mention}).",
                title="HIERARCHY ERROR",
                status="error",
                ephemeral=True
            )
            return

        # 3. Hierarchy check: executor vs target member
        if interaction.user.id != interaction.guild.owner_id and member.top_role >= interaction.user.top_role and member.id != interaction.user.id:
            await reply_box(
                interaction,
                f"You cannot modify roles for {member.mention} because their highest role ({member.top_role.mention}) is equal to or higher than yours.",
                title="HIERARCHY ERROR",
                status="error",
                ephemeral=True
            )
            return

        # 4. Hierarchy check: bot vs target role
        if role >= interaction.guild.me.top_role:
            await reply_box(
                interaction,
                f"Friday cannot remove {role.mention} because it is higher than or equal to Friday's highest role ({interaction.guild.me.top_role.mention}).\n"
                "Please drag Friday's role higher in Server Settings > Roles.",
                title="BOT HIERARCHY LIMIT",
                status="error",
                ephemeral=True
            )
            return

        # 5. Remove role
        try:
            await member.remove_roles(role, reason=f"Role removed by {interaction.user} ({interaction.user.id})")
            await reply_box(
                interaction,
                f"Successfully removed {role.mention} from {member.mention}.",
                title="ROLE REMOVED",
                status="success"
            )
        except discord.Forbidden:
            await reply_box(interaction, f"Friday lacks permission to remove {role.mention}.", title="PERMISSION DENIED", status="error", ephemeral=True)
        except Exception as e:
            await reply_box(interaction, f"Failed to remove role: {e}", title="EXECUTION ERROR", status="error", ephemeral=True)

    @role_group.command(name="info", description="Display detailed information about a role.")
    @app_commands.describe(role="The role to inspect")
    async def role_info(self, interaction: discord.Interaction, role: discord.Role):
        created_ts = int(role.created_at.timestamp())
        member_count = len(role.members)
        hex_color = str(role.color).upper()
        
        desc = (
            f"> **Name:** {role.mention} (`{role.name}`)\n"
            f"> **Role ID:** `{role.id}`\n"
            f"> **Color:** `{hex_color}`\n"
            f"> **Position:** `{role.position}` (from bottom)\n"
            f"> **Hoisted (Separated):** {'Yes' if role.hoist else 'No'}\n"
            f"> **Mentionable:** {'Yes' if role.mentionable else 'No'}\n"
            f"> **Managed (Bot/Integration):** {'Yes' if role.managed else 'No'}\n"
            f"> **Members Assigned:** `{member_count}`\n"
            f"> **Created At:** <t:{created_ts}:R> (<t:{created_ts}:F>)"
        )
        await reply_box(interaction, desc, title=f"ROLE INFO: {role.name}", status="info")

    @role_group.command(name="list", description="List all roles assigned to a member.")
    @app_commands.describe(member="The member whose roles to view")
    async def role_list(self, interaction: discord.Interaction, member: discord.Member):
        roles = [r.mention for r in reversed(member.roles) if not r.is_default()]
        count = len(roles)
        if not roles:
            desc = f"{member.mention} has no special roles assigned."
        else:
            desc = f"**Total Roles ({count}):**\n" + ", ".join(roles)
        await reply_box(interaction, desc, title=f"ROLES: {member.display_name}", status="info")

    @role_group.command(name="emoji", description="Set, update, or remove the emoji / icon for a server role.")
    @app_commands.describe(role="The role to update", emoji="The emoji or custom emoji to assign (type 'none' to remove)")
    @app_commands.default_permissions(manage_roles=True)
    async def role_emoji(self, interaction: discord.Interaction, role: discord.Role, emoji: str):
        if not await self.require_mod_permission(interaction, "manage_roles", "Manage Roles"):
            return
        # 1. Invalid / default / managed role checks
        if role.is_default():
            await reply_box(interaction, "Cannot modify the default @everyone role.", title="INVALID ROLE", status="error", ephemeral=True)
            return
        if role.managed:
            await reply_box(interaction, f"The role {role.mention} is managed by an integration or bot and cannot be modified manually.", title="INTEGRATION ROLE", status="error", ephemeral=True)
            return

        # 2. Hierarchy check: executor vs target role
        if interaction.user.id != interaction.guild.owner_id and role >= interaction.user.top_role:
            await reply_box(
                interaction,
                f"You cannot modify {role.mention} because it is higher than or equal to your highest role ({interaction.user.top_role.mention}).",
                title="HIERARCHY ERROR",
                status="error",
                ephemeral=True
            )
            return

        # 3. Hierarchy check: bot vs target role
        if role >= interaction.guild.me.top_role:
            await reply_box(
                interaction,
                f"Friday cannot modify {role.mention} because it is higher than or equal to Friday's highest role ({interaction.guild.me.top_role.mention}).\n"
                "Please drag Friday's role higher in Server Settings > Roles.",
                title="BOT HIERARCHY LIMIT",
                status="error",
                ephemeral=True
            )
            return

        clean = emoji.strip()
        # Removal case
        if clean.lower() in ("none", "remove", "clear", "0", "delete", "off"):
            try:
                await role.edit(display_icon=None, reason=f"Role icon removed by {interaction.user} ({interaction.user.id})")
                await reply_box(interaction, f"Successfully removed the emoji / icon from {role.mention}.", title="ROLE EMOJI REMOVED", status="success")
                return
            except discord.Forbidden:
                await reply_box(interaction, f"Friday lacks permission to edit {role.mention}.", title="PERMISSION DENIED", status="error", ephemeral=True)
                return
            except Exception as e:
                await reply_box(interaction, f"Failed to clear role icon: {e}", title="EXECUTION ERROR", status="error", ephemeral=True)
                return

        # Custom Discord emoji: <:name:id> or <a:name:id>
        custom_m = re.match(r'<a?:([a-zA-Z0-9_]+):([0-9]+)>', clean)
        icon_val = None
        if custom_m:
            emoji_id = int(custom_m.group(2))
            custom_emoji = interaction.guild.get_emoji(emoji_id) or self.bot.get_emoji(emoji_id)
            if not custom_emoji:
                try:
                    custom_emoji = await self.bot.fetch_emoji(emoji_id)
                except Exception:
                    custom_emoji = None
            if custom_emoji:
                try:
                    icon_val = await custom_emoji.read()
                except Exception as e:
                    await reply_box(interaction, f"Failed to load custom emoji bytes: {e}", title="EMOJI FETCH ERROR", status="error", ephemeral=True)
                    return
            else:
                # Fallback: fetch asset directly from Discord CDN
                try:
                    async with aiohttp.ClientSession() as session:
                        url = f"https://cdn.discordapp.com/emojis/{emoji_id}.png"
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                icon_val = await resp.read()
                except Exception:
                    pass

            if not icon_val:
                await reply_box(interaction, f"Could not find or load custom emoji `{clean}`.", title="EMOJI NOT FOUND", status="error", ephemeral=True)
                return
        else:
            # Standard unicode emoji (e.g. 👑, 🔥, 🛡️)
            icon_val = clean

        try:
            await role.edit(display_icon=icon_val, reason=f"Role icon updated by {interaction.user} ({interaction.user.id})")
            await reply_box(
                interaction,
                f"Successfully set the emoji for {role.mention} to {clean}!",
                title="ROLE EMOJI UPDATED",
                status="success"
            )
        except discord.Forbidden:
            await reply_box(interaction, f"Friday lacks permission to update {role.mention}.", title="PERMISSION DENIED", status="error", ephemeral=True)
        except discord.HTTPException as e:
            if "ROLE_ICONS" in str(e) or "feature" in str(e).lower():
                await reply_box(
                    interaction,
                    f"⚠️ This server has not unlocked the **Role Icons** perk yet (Discord requires Server Boost Level 2).\n\n"
                    f"Once your server reaches Level 2 Boost, Friday will be able to display role emojis!",
                    title="SERVER BOOST REQUIRED",
                    status="warning",
                    ephemeral=True
                )
            else:
                await reply_box(interaction, f"Discord error while setting role emoji: {e}", title="DISCORD API ERROR", status="error", ephemeral=True)
        except Exception as e:
            await reply_box(interaction, f"Failed to set role emoji: {e}", title="EXECUTION ERROR", status="error", ephemeral=True)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        """Reinforce channel lock if permissions are altered by category sync or external bots."""
        if not hasattr(after, "id") or not hasattr(after, "guild"):
            return
        if getattr(self, "_unlocking_channels", None) and after.id in self._unlocking_channels:
            return
        chan_id_str = str(after.id)
        locked_channels = db.data.get("locked_channels", {})
        if chan_id_str not in locked_channels:
            return
        try:
            default_role = after.guild.default_role
            ow = after.overwrites_for(default_role)
            if ow.send_messages is not False:
                ow.send_messages = False
                await after.set_permissions(default_role, overwrite=ow, reason="Friday Lock Reinforcement: Locked channel permission restored.")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Custom Prefix Engine exclusively for Server Owner and whitelisted staff members/roles.
        Supported prefix commands: purge, lock, unlock, ban, tm (timeout).
        Normal members cannot invoke these commands."""
        if not message.guild or message.author.bot:
            return

        gid = str(message.guild.id)
        prefix = db.custom_prefixes.get(gid, "!")
        content = message.content.strip()
        if not content.startswith(prefix):
            return

        cmd_raw = content[len(prefix):].strip()
        if not cmd_raw:
            return

        parts = cmd_raw.split()
        cmd_name = parts[0].lower()

        # Strict set of essential staff prefix commands
        allowed_prefix_cmds = {"purge", "lock", "unlock", "ban", "tm"}
        if cmd_name not in allowed_prefix_cmds:
            return

        # 1. Ironclad Whitelist & In-Server Permission Check
        author = message.author
        guild = message.guild
        channel = message.channel

        is_owner = (author.id == guild.owner_id)
        is_bot_owner = False
        try:
            is_bot_owner = await self.bot.is_owner(author)
        except Exception:
            pass

        perms = getattr(author, "guild_permissions", None)
        is_admin = bool(perms and perms.administrator)

        wl = db.prefix_whitelist.get(gid, {})
        wl_users = [int(u) for u in wl.get("members", []) if str(u).isdigit()]
        wl_roles = [int(r) for r in wl.get("roles", []) if str(r).isdigit()]
        author_roles = getattr(author, "roles", [])
        has_role = any(r.id in wl_roles for r in author_roles)
        is_user_whitelisted = author.id in wl_users

        # Check native in-server Discord permissions specifically required for each command
        chan_perms = channel.permissions_for(author) if hasattr(channel, "permissions_for") else perms
        has_native_perm = False

        if is_admin:
            has_native_perm = True
        elif cmd_name == "purge":
            # Requires Manage Messages ("manage chat / delete permission")
            has_native_perm = bool((chan_perms and chan_perms.manage_messages) or (perms and perms.manage_messages))
        elif cmd_name in ("lock", "unlock"):
            # Requires Manage Channels
            has_native_perm = bool((chan_perms and chan_perms.manage_channels) or (perms and perms.manage_channels))
        elif cmd_name == "ban":
            # Requires Ban Members
            has_native_perm = bool(perms and perms.ban_members)
        elif cmd_name == "tm":
            # Requires Moderate Members (Timeout)
            has_native_perm = bool(perms and perms.moderate_members)

        # If author is NOT server owner, bot owner, admin, dashboard whitelisted, or natively permitted -> SILENT IGNORE
        if not (is_owner or is_bot_owner or is_admin or is_user_whitelisted or has_role or has_native_perm):
            return

        # 2. Check if specific command is enabled in whitelist configuration
        cmd_toggles = wl.get("commands", {"purge": True, "lock": True, "unlock": True, "ban": True, "tm": True})
        if not cmd_toggles.get(cmd_name, True):
            return

        args = parts[1:]

        # ── 1. PURGE: !purge <count> or !purge @user <count> ──
        if cmd_name == "purge":
            if not channel.permissions_for(guild.me).manage_messages:
                m = await channel.send("❌ Friday lacks **Manage Messages** permission in this channel.")
                await m.delete(delay=4)
                return

            count = 10
            target_user = None
            if message.mentions:
                target_user = message.mentions[0]
                for a in args:
                    if a.isdigit():
                        count = int(a)
                        break
            elif args and args[0].isdigit():
                count = int(args[0])

            count = max(1, min(count, 100))
            try:
                await message.delete()
            except Exception:
                pass

            try:
                if target_user:
                    deleted = await channel.purge(limit=count, check=lambda m: m.author.id == target_user.id)
                else:
                    deleted = await channel.purge(limit=count)
                confirm = await channel.send(f"🗑️ Purged **{len(deleted)}** message(s).")
                await confirm.delete(delay=3)
            except Exception as e:
                err_m = await channel.send(f"❌ Purge error: {e}")
                await err_m.delete(delay=5)

        # ── 2. LOCK: !lock [reason] or !lock #channel [reason] ──
        elif cmd_name == "lock":
            target_chan = channel
            reason_words = list(args)
            if message.channel_mentions:
                target_chan = message.channel_mentions[0]
                reason_words = [w for w in reason_words if not (w.startswith("<#") and w.endswith(">"))]
            elif args and args[0].isdigit():
                found_ch = guild.get_channel(int(args[0]))
                if found_ch:
                    target_chan = found_ch
                    reason_words = args[1:]

            reason = " ".join(reason_words).strip() or "Channel locked by staff."
            success, msg_text, _ = await self.execute_channel_lock(target_chan, author, reason=reason)
            if success:
                lock_embed = make_box_embed(
                    title="CHANNEL LOCKED",
                    description=f"🔒 {target_chan.mention} has been locked by {author.mention}.\n\n**Reason:** {reason}\n*Regular members cannot send messages until unlocked by staff.*",
                    status="error"
                )
                if target_chan.id == channel.id:
                    await channel.send(embed=lock_embed)
                else:
                    await target_chan.send(embed=lock_embed)
                    await channel.send(f"🔒 Successfully locked {target_chan.mention}.")
            else:
                await channel.send(f"ℹ️ {msg_text}")

        # ── 3. UNLOCK: !unlock or !unlock #channel [reason] ──
        elif cmd_name == "unlock":
            target_chan = channel
            reason_words = list(args)
            if message.channel_mentions:
                target_chan = message.channel_mentions[0]
                reason_words = [w for w in reason_words if not (w.startswith("<#") and w.endswith(">"))]
            elif args and args[0].isdigit():
                found_ch = guild.get_channel(int(args[0]))
                if found_ch:
                    target_chan = found_ch
                    reason_words = args[1:]

            reason = " ".join(reason_words).strip() or "Channel unlocked by staff."
            success, msg_text, _ = await self.execute_channel_unlock(target_chan, author, reason=reason)
            if success:
                unlock_embed = make_box_embed(
                    title="CHANNEL UNLOCKED",
                    description=f"🔓 {target_chan.mention} has been unlocked by {author.mention}.\n\n**Reason:** {reason}\n*Members may now resume chatting.*",
                    status="success"
                )
                if target_chan.id == channel.id:
                    await channel.send(embed=unlock_embed)
                else:
                    await target_chan.send(embed=unlock_embed)
                    await channel.send(f"🔓 Successfully unlocked {target_chan.mention}.")
            else:
                await channel.send(f"ℹ️ {msg_text}")

        # ── 4. BAN: !ban @user [reason] or !ban <id> [reason] ──
        elif cmd_name == "ban":
            target_member = None
            reason_words = list(args)
            if message.mentions:
                target_member = message.mentions[0]
                reason_words = [w for w in reason_words if not (w.startswith("<@") and w.endswith(">"))]
            elif args and args[0].isdigit():
                target_member = guild.get_member(int(args[0]))
                if not target_member:
                    try:
                        target_member = await guild.fetch_member(int(args[0]))
                    except Exception:
                        pass
                reason_words = args[1:]

            if not target_member:
                await channel.send(f"❌ Usage: `{prefix}ban @user [reason]`")
                return

            reason = " ".join(reason_words).strip() or "Banned by staff via prefix command."
            if not is_owner and author.top_role <= target_member.top_role:
                await channel.send("❌ You cannot ban someone with a higher or equal role hierarchy.")
                return
            if target_member.top_role >= guild.me.top_role and target_member != guild.owner:
                await channel.send("❌ Friday's role hierarchy is not high enough to ban this user.")
                return

            try:
                await target_member.ban(reason=f"{author} via prefix: {reason}")
                ban_embed = make_box_embed(
                    title="BAN EXECUTED",
                    description=f"🔨 Successfully banned {target_member.mention} (`{target_member.name}`).\n\n**Staff:** {author.mention}\n**Reason:** {reason}",
                    status="danger"
                )
                await channel.send(embed=ban_embed)
            except discord.Forbidden:
                await channel.send("❌ Failed to ban: Friday lacks Ban Members permission.")
            except Exception as e:
                await channel.send(f"❌ Error banning member: {e}")

        # ── 5. TM: !tm @user <duration> [reason] ── (Specifically named tm!)
        elif cmd_name == "tm":
            target_member = None
            reason_words = list(args)
            if message.mentions:
                target_member = message.mentions[0]
                reason_words = [w for w in reason_words if not (w.startswith("<@") and w.endswith(">"))]
            elif args and args[0].isdigit():
                target_member = guild.get_member(int(args[0]))
                reason_words = args[1:]

            if not target_member or not reason_words:
                await channel.send(f"❌ Usage: `{prefix}tm @user <duration> [reason]` (e.g. `{prefix}tm @user 10m` or `{prefix}tm @user 1h spamming`)")
                return

            raw_dur = reason_words[0].lower()
            dur_reason = " ".join(reason_words[1:]).strip() or "Timed out by staff via prefix command."

            # Parse duration: 10m, 1h, 1d, 30s, or integer (default minutes)
            seconds = 600
            m_dur = re.match(r'^(\d+)([smhd]?)$', raw_dur)
            if m_dur:
                val = int(m_dur.group(1))
                unit = m_dur.group(2) or "m"
                if unit == "s": seconds = val
                elif unit == "m": seconds = val * 60
                elif unit == "h": seconds = val * 3600
                elif unit == "d": seconds = val * 86400
            elif raw_dur.isdigit():
                seconds = int(raw_dur) * 60

            # Max Discord timeout is 28 days
            seconds = max(10, min(seconds, 2419200))
            duration = datetime.timedelta(seconds=seconds)

            if not is_owner and author.top_role <= target_member.top_role:
                await channel.send("❌ You cannot timeout someone with a higher or equal role hierarchy.")
                return
            if target_member.guild_permissions.administrator:
                await channel.send("❌ Cannot timeout a server Administrator.")
                return
            if target_member.top_role >= guild.me.top_role and target_member != guild.owner:
                await channel.send("❌ Friday's role hierarchy is not high enough to timeout this user.")
                return

            try:
                await target_member.timeout(duration, reason=f"{author} via prefix: {dur_reason}")
                tm_embed = make_box_embed(
                    title="TIMEOUT APPLIED",
                    description=f"⏳ Successfully timed out {target_member.mention}.\n\n**Duration:** `{raw_dur}`\n**Staff:** {author.mention}\n**Reason:** {dur_reason}",
                    status="warning"
                )
                await channel.send(embed=tm_embed)
            except discord.Forbidden:
                await channel.send("❌ Failed to timeout: Friday lacks Moderate Members permission.")
            except Exception as e:
                await channel.send(f"❌ Error applying timeout: {e}")

async def setup(bot):
    await bot.add_cog(Moderation(bot))
