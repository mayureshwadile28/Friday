import discord
from discord.ext import commands
from discord import app_commands
import datetime
from database import db
from response_utils import make_box_embed, reply_box


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Rule violation."):
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

        # Trigger 1: Nickname Change via Mention: @Friday @User New Nickname
        bot_mention_str1 = f"<@{self.bot.user.id}>"
        bot_mention_str2 = f"<@!{self.bot.user.id}>"
        
        content = message.content.strip()
        if content.startswith(bot_mention_str1) or content.startswith(bot_mention_str2):
            parts = content.split()
            if len(parts) >= 2:
                import re
                target_match = re.match(r'^<@!?(\d+)>$', parts[1])
                if target_match:
                    target_id = int(target_match.group(1))
                    target_member = message.guild.get_member(target_id)
                    
                    if target_member:
                        # Validate permissions
                        perms = message.author.guild_permissions
                        gid = str(message.guild.id)
                        if not (perms.administrator or perms.manage_nicknames):
                            err_tpl = db.custom_responses.get(gid, {}).get("nick_perm_err", "Only staff with Manage Nicknames or Administrator permissions can change nicknames.")
                            embed = make_box_embed(title="ACCESS DENIED", description=err_tpl, status="danger")
                            await message.reply(embed=embed, mention_author=False)
                            return
                            
                        # If a new nickname is provided, use it. Otherwise, if empty, reset the nickname.
                        new_nickname = " ".join(parts[2:]) if len(parts) > 2 else None
                        
                        try:
                            await target_member.edit(nick=new_nickname)
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
                        except discord.Forbidden:
                            err_tpl = db.custom_responses.get(gid, {}).get("nick_bot_err", "Friday does not have permission or role hierarchy to modify this user's nickname.")
                            embed = make_box_embed(title="PERMISSION FAULT", description=err_tpl, status="danger")
                            await message.reply(embed=embed, mention_author=False)
                        except Exception as e:
                            embed = make_box_embed(title="EXECUTION ERROR", description=f"Error changing nickname: {e}", status="danger")
                            await message.reply(embed=embed, mention_author=False)
                        return

async def setup(bot):
    await bot.add_cog(Moderation(bot))
