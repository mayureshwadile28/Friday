import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import time
import datetime
import re
from database import db

CHANNELS_TO_CHECK = [
    "audit-deleted",
    "audit-banned",
    "audit-timeouts",
    "audit-whitelisted",
    "audit-antinuke",
    "audit-abuse",
    "audit-antiraid",
    "audit-antispam",
    "audit-roles",
    "audit-channels"
]

DEFAULT_SECURITY_CONFIG = {
    "limits": {
        "ban": {"limit": 5, "punishment": "ban", "enabled": True},
        "kick": {"limit": 3, "punishment": "kick", "enabled": True},
        "role_create": {"limit": 1, "punishment": "ban", "enabled": True},
        "role_delete": {"limit": 1, "punishment": "ban", "enabled": True},
        "channel_create": {"limit": 1, "punishment": "ban", "enabled": True},
        "channel_delete": {"limit": 1, "punishment": "ban", "enabled": True},
        "mention": {"limit": 5, "punishment": "timeout", "enabled": True}
    },
    "instant": {
        "bot_add": {"punishment": "kick", "enabled": True},
        "prune": {"punishment": "ban", "enabled": True},
        "dangerous_perms": {"punishment": "strip_roles", "enabled": True},
        "dangerous_role_add": {"punishment": "strip_roles", "enabled": True},
        "vanity_change": {"punishment": "ban", "enabled": False},
        "server_rename": {"punishment": "kick", "enabled": True},
        "server_icon": {"punishment": "kick", "enabled": True},
        "role_rename": {"punishment": "kick", "enabled": False},
        "channel_rename": {"punishment": "kick", "enabled": False},
        "emoji_delete": {"punishment": "kick", "enabled": False},
        "emoji_rename": {"punishment": "kick", "enabled": False},
        "invite_delete": {"punishment": "kick", "enabled": False}
    },
    "detect": {
        "invite_link": {"enabled": True},
        "anti_link": {"enabled": True},
        "ghost_ping": {"enabled": True}
    },
    "antiraid": {
        "enabled": True,
        "join_threshold": 5,
        "time_window": 10,
        "action": "lockdown"
    },
    "antispam": {
        "enabled": True,
        "rate_limit": 5,
        "time_window": 4,
        "duplicate_limit": 3,
        "action": "timeout"
    }
}

class Security(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.action_tracker = {}
        self.recent_joins = {}      # guild_id -> list of join timestamps
        self.message_tracker = {}   # guild_id -> user_id -> list of (timestamp, content)
        self.invite_regex = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discord(?:app)?\.com/invite|dsc\.gg)/[a-zA-Z0-9\-_]+", re.IGNORECASE)
        self.link_regex = re.compile(r"(?:https?://|www\.)[^\s]+", re.IGNORECASE)

    def get_security_config(self, gid: str):
        """Retrieve guild security config merged with defaults."""
        if gid not in db.security_settings:
            import copy
            db.security_settings[gid] = copy.deepcopy(DEFAULT_SECURITY_CONFIG)
            db.save_data()
        cfg = db.security_settings[gid]
        for key in ["limits", "instant", "detect", "antiraid", "antispam"]:
            if key not in cfg:
                import copy
                cfg[key] = copy.deepcopy(DEFAULT_SECURITY_CONFIG[key])
        return cfg

    def is_whitelisted(self, guild: discord.Guild, member_or_user, feature: str = None) -> bool:
        if not member_or_user: return True
        if member_or_user.id == self.bot.user.id: return True
        if member_or_user.id == guild.owner_id: return True
        gid = str(guild.id)
        if member_or_user.id in db.whitelist.get(gid, []): return True
        if feature:
            feat_wl = db.feature_whitelists.get(gid, {}).get(feature, [])
            if member_or_user.id in feat_wl: return True
        # Server Administrators and Managers are always considered whitelisted/immune
        if isinstance(member_or_user, discord.Member):
            if member_or_user.guild_permissions.administrator:
                return True
        return False

    def record_action_and_check(self, guild_id, user_id, action_type):
        gid = str(guild_id)
        uid = str(user_id)
        now = time.time()
        time_window = 60 
        
        if gid not in self.action_tracker:
            self.action_tracker[gid] = {}
        if uid not in self.action_tracker[gid]:
            self.action_tracker[gid][uid] = []
            
        self.action_tracker[gid][uid].append(now)
        self.action_tracker[gid][uid] = [t for t in self.action_tracker[gid][uid] if now - t <= time_window]
        
        cfg = self.get_security_config(gid)
        limit_rule = cfg.get("limits", {}).get(action_type, {})
        limit = limit_rule.get("limit") or db.nuke_settings.get(gid, {}).get(action_type, DEFAULT_SECURITY_CONFIG["limits"].get(action_type, {}).get("limit", 1))
        enabled = limit_rule.get("enabled", True)
        
        if not enabled:
            return False
            
        return len(self.action_tracker[gid][uid]) >= limit

    async def log_security_event(self, guild: discord.Guild, channel_name: str, embed: discord.Embed):
        """Send embed log to specified security channel in 'Friday Security Logs'."""
        gid = str(guild.id)
        chan_id = db.server_logs.get(gid, {}).get(channel_name)
        if not chan_id:
            chan_id = db.server_logs.get(gid, {}).get("audit-antinuke")
        if chan_id:
            ch = guild.get_channel(chan_id)
            if ch:
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

    async def execute_punishment(self, guild: discord.Guild, culprit: discord.Member, punishment_type: str, reason: str, log_channel="audit-antinuke", timeout_mins=None, feature: str = None):
        if self.is_whitelisted(guild, culprit, feature=feature):
            return False
            
        success = False
        action_name = punishment_type.upper()
        gid = str(guild.id)
        
        if timeout_mins is None:
            timeout_mins = 10
        try:
            timeout_mins = max(1, int(timeout_mins))
        except Exception:
            timeout_mins = 10

        error_detail = None
        try:
            if punishment_type == "ban":
                await guild.ban(culprit, reason=reason)
                success = True
            elif punishment_type == "kick":
                await guild.kick(culprit, reason=reason)
                success = True
            elif punishment_type == "strip_roles":
                dangerous_roles = [r for r in culprit.roles if (r.permissions.administrator or r.permissions.manage_guild or r.permissions.ban_members or r.permissions.manage_roles or r.permissions.manage_channels) and r < guild.me.top_role]
                if dangerous_roles:
                    await culprit.remove_roles(*dangerous_roles, reason=reason)
                success = True
            elif punishment_type == "timeout":
                # DISCORD API SPEC: Discord strictly prohibits timing out users with ADMINISTRATOR permission.
                # If culprit has Administrator permission from roles lower than Friday, revoke those roles first!
                if culprit.guild_permissions.administrator:
                    admin_roles = [r for r in culprit.roles if (r.permissions.administrator or r.permissions.manage_guild or r.permissions.manage_roles) and r < guild.me.top_role]
                    if admin_roles:
                        try:
                            await culprit.remove_roles(*admin_roles, reason=f"Revoking admin role before timeout: {reason}")
                        except Exception:
                            pass
                await culprit.timeout(datetime.timedelta(minutes=timeout_mins), reason=reason)
                success = True
            else:
                await guild.kick(culprit, reason=reason)
                success = True
        except discord.Forbidden:
            # Diagnose the exact reason for accurate feedback
            if guild.me.top_role <= culprit.top_role:
                error_detail = "Friday's role is below this user in role hierarchy. Immediate manual action required!"
            elif culprit.guild_permissions.administrator:
                error_detail = "Discord forbids timing out users with Administrator permission. Dangerous roles could not be removed."
            else:
                error_detail = "Discord permission error (403 Forbidden). Ensure Friday has 'Moderate Members' and 'Manage Roles'."

            if guild.owner:
                try:
                    await guild.owner.send(
                        f"🚨 **EMERGENCY: SECURITY TRIGGER IN {guild.name}!** 🚨\n"
                        f"**Culprit:** {culprit.mention} (`{culprit.name}`)\n"
                        f"**Trigger:** {reason}\n"
                        f"**Required Punishment:** {action_name}\n\n"
                        f"⚠️ **Error:** {error_detail}"
                    )
                except discord.Forbidden:
                    pass
            success = False

        status_text = '✅ Executed' if success else (f'❌ Blocked ({error_detail})' if error_detail else '❌ Action Blocked')
        embed = discord.Embed(
            title=f"🛡️ Security Enforcement: {action_name}",
            description=f"**Target:** {culprit.mention} (`{culprit.id}`)\n**Reason:** {reason}\n**Status:** {status_text}",
            color=discord.Color.red() if success else discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        await self.log_security_event(guild, log_channel, embed)
        return success

    async def handle_nuker_punishment(self, guild, culprit, reason):
        return await self.execute_punishment(guild, culprit, "ban", reason, log_channel="audit-antinuke")

    async def auto_sync_security_channels(self, guild):
        """Automatically scan and link all Friday security log channels."""
        if not guild: return 0
        gid = str(guild.id)
        if gid not in db.server_logs:
            db.server_logs[gid] = {}

        synced = 0
        category = discord.utils.get(guild.categories, name="Friday Security Logs")
        category_channels = category.text_channels if category else []

        for name in CHANNELS_TO_CHECK:
            ch = discord.utils.get(category_channels, name=name)
            if not ch:
                ch = discord.utils.get(guild.text_channels, name=name)
            if ch:
                db.server_logs[gid][name] = ch.id
                synced += 1

        db.save_data()
        return synced

    # ───────────────────── Slash Commands ─────────────────────

    def can_manage_antinuke(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        if not guild:
            return False
        if interaction.user.id == guild.owner_id:
            return True
        user = interaction.user
        if not isinstance(user, discord.Member):
            return False
        bot_member = guild.me
        if not bot_member:
            return False
        return user.top_role > bot_member.top_role

    @app_commands.command(name="antinuke_toggle", description="Turn the Anti-Nuke system ON or OFF.")
    @app_commands.choices(status=[
        app_commands.Choice(name="Turn ON", value=1),
        app_commands.Choice(name="Turn OFF", value=0)
    ])
    @app_commands.default_permissions(administrator=True)
    async def antinuke_toggle(self, interaction: discord.Interaction, status: app_commands.Choice[int]):
        if not self.can_manage_antinuke(interaction):
            await interaction.response.send_message(
                "⛔ **Hierarchy Access Denied:** Only the Server Owner or members with a role strictly higher than Friday can edit or configure Anti-Nuke settings.",
                ephemeral=True
            )
            return
        gid = str(interaction.guild.id)
        is_active = bool(status.value)
        db.antinuke_active[gid] = is_active
        db.save_data()
        embed = discord.Embed(
            title="✔ System Updated" if is_active else "✖ System Disabled",
            description=f"Anti-Nuke system is now **{'Enabled' if is_active else 'Disabled'}**.",
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="antiraid", description="Configure Friday's high-speed Anti-Raid join protection.")
    @app_commands.choices(status=[
        app_commands.Choice(name="Enable Anti-Raid", value=1),
        app_commands.Choice(name="Disable Anti-Raid", value=0)
    ])
    @app_commands.default_permissions(administrator=True)
    async def antiraid_command(self, interaction: discord.Interaction, status: app_commands.Choice[int]):
        if not self.can_manage_antinuke(interaction):
            await interaction.response.send_message(
                "⛔ **Hierarchy Access Denied:** Only the Server Owner or members with a role strictly higher than Friday can edit or configure Anti-Nuke settings.",
                ephemeral=True
            )
            return
        gid = str(interaction.guild.id)
        cfg = self.get_security_config(gid)
        cfg["antiraid"]["enabled"] = bool(status.value)
        db.save_data()
        embed = discord.Embed(
            title="✔ System Updated" if status.value else "✖ System Disabled",
            description=f"Anti-Raid mass-join protection is now **{'Enabled' if status.value else 'Disabled'}**.",
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="antispam", description="Configure Friday's rapid message and flood Anti-Spam filter.")
    @app_commands.choices(status=[
        app_commands.Choice(name="Enable Anti-Spam", value=1),
        app_commands.Choice(name="Disable Anti-Spam", value=0)
    ])
    @app_commands.default_permissions(administrator=True)
    async def antispam_command(self, interaction: discord.Interaction, status: app_commands.Choice[int]):
        if not self.can_manage_antinuke(interaction):
            await interaction.response.send_message(
                "⛔ **Hierarchy Access Denied:** Only the Server Owner or members with a role strictly higher than Friday can edit or configure Anti-Nuke settings.",
                ephemeral=True
            )
            return
        gid = str(interaction.guild.id)
        cfg = self.get_security_config(gid)
        cfg["antispam"]["enabled"] = bool(status.value)
        db.save_data()
        embed = discord.Embed(
            title="✔ System Updated" if status.value else "✖ System Disabled",
            description=f"Anti-Spam rate flood protection is now **{'Enabled' if status.value else 'Disabled'}**.",
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="security_status", description="Inspect all Friday Security modules, thresholds, and log links.")
    @app_commands.default_permissions(administrator=True)
    async def security_status(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        cfg = self.get_security_config(gid)
        is_nuke = db.antinuke_active.get(gid, True)
        is_raid = cfg.get("antiraid", {}).get("enabled", True)
        is_spam = cfg.get("antispam", {}).get("enabled", True)

        embed = discord.Embed(title="🛡️ Friday Security Matrix & Systems", color=discord.Color.blurple())
        embed.add_field(name="Anti-Nuke", value="🟢 Enabled" if is_nuke else "🔴 Disabled", inline=True)
        embed.add_field(name="Anti-Raid", value="🟢 Enabled" if is_raid else "🔴 Disabled", inline=True)
        embed.add_field(name="Anti-Spam", value="🟢 Enabled" if is_spam else "🔴 Disabled", inline=True)

        logs_count = sum(1 for ch_name in CHANNELS_TO_CHECK if db.server_logs.get(gid, {}).get(ch_name))
        embed.add_field(name="Security Log Channels", value=f"📡 **{logs_count} / {len(CHANNELS_TO_CHECK)}** Active Channels Linked", inline=False)
        embed.set_footer(text="Manage full matrix settings anytime in the web dashboard!")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="antinuke_sync", description="Instantly re-sync and link all existing Friday security audit channels.")
    @app_commands.default_permissions(administrator=True)
    async def antinuke_sync(self, interaction: discord.Interaction):
        if not self.can_manage_antinuke(interaction):
            await interaction.response.send_message(
                "⛔ **Hierarchy Access Denied:** Only the Server Owner or members with a role strictly higher than Friday can edit or configure Anti-Nuke settings.",
                ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        count = await self.auto_sync_security_channels(interaction.guild)
        await interaction.followup.send(f"🛡️ Security sync complete! **{count}** security audit channels are actively linked to Friday.", ephemeral=True)

    @app_commands.command(name="antinuke_refresh", description="Auto-create and link all missing Friday security log channels.")
    @app_commands.default_permissions(administrator=True)
    async def antinuke_refresh(self, interaction: discord.Interaction):
        if not self.can_manage_antinuke(interaction):
            await interaction.response.send_message(
                "⛔ **Hierarchy Access Denied:** Only the Server Owner or members with a role strictly higher than Friday can edit or configure Anti-Nuke settings.",
                ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        gid = str(guild.id)
        category = discord.utils.get(guild.categories, name="Friday Security Logs")
        if not category: category = await guild.create_category("Friday Security Logs")

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        created_list = []
        if gid not in db.server_logs: db.server_logs[gid] = {}

        for name in CHANNELS_TO_CHECK:
            existing_channel = discord.utils.get(guild.channels, name=name)
            if not existing_channel:
                existing_channel = await guild.create_text_channel(name, category=category, overwrites=overwrites)
                created_list.append(existing_channel.mention)
            db.server_logs[gid][name] = existing_channel.id
            
        db.save_data()
        if created_list: await interaction.followup.send(f"✅ Infrastructure built! Created: {', '.join(created_list)}")
        else: await interaction.followup.send("✅ All 10 security log channels already exist and are fully linked to Friday's systems.")

    @app_commands.command(name="antinuke_limit", description="Set limits for anti-nuke protection (within a 60s window).")
    @app_commands.choices(action_type=[
        app_commands.Choice(name="Channel Deletions", value="channel_delete"),
        app_commands.Choice(name="Channel Creations", value="channel_create"),
        app_commands.Choice(name="Member Bans", value="ban"),
        app_commands.Choice(name="Member Kicks", value="kick"),
        app_commands.Choice(name="Role Deletions", value="role_delete"),
        app_commands.Choice(name="Role Creations", value="role_create"),
        app_commands.Choice(name="Mass Mentions", value="mention")
    ])
    @app_commands.default_permissions(administrator=True)
    async def antinuke_limit(self, interaction: discord.Interaction, action_type: app_commands.Choice[str], limit: int):
        if not self.can_manage_antinuke(interaction):
            await interaction.response.send_message(
                "⛔ **Hierarchy Access Denied:** Only the Server Owner or members with a role strictly higher than Friday can edit or configure Anti-Nuke settings.",
                ephemeral=True
            )
            return
        gid = str(interaction.guild.id)
        if gid not in db.nuke_settings: db.nuke_settings[gid] = {}
        db.nuke_settings[gid][action_type.value] = limit
        
        cfg = self.get_security_config(gid)
        if action_type.value in cfg.get("limits", {}):
            cfg["limits"][action_type.value]["limit"] = limit
            
        db.save_data()
        await interaction.response.send_message(f"🛡️ Anti-nuke updated: A user will be punished if they trigger {limit} **{action_type.name}** within 60 seconds.", ephemeral=True)

    @app_commands.command(name="whitelist_add", description="Add a user to the Anti-Nuke whitelist.")
    @app_commands.default_permissions(administrator=True)
    async def whitelist_add(self, interaction: discord.Interaction, user: discord.Member):
        if not self.can_manage_antinuke(interaction):
            await interaction.response.send_message(
                "⛔ **Hierarchy Access Denied:** Only the Server Owner or members with a role strictly higher than Friday can edit or configure Anti-Nuke settings.",
                ephemeral=True
            )
            return
        gid = str(interaction.guild.id)
        if gid not in db.whitelist: db.whitelist[gid] = []
        if user.id not in db.whitelist[gid]:
            db.whitelist[gid].append(user.id)
            db.save_data()
            embed = discord.Embed(
                title="🛡️ Whitelist Member Added",
                description=f"{user.mention} (`{user.id}`) was added to the Security Whitelist by {interaction.user.mention}.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(interaction.guild, "audit-whitelisted", embed)
            resp_embed = discord.Embed(
                title="✔ Whitelist Updated",
                description=f"{user.mention} has been added to the Anti-Nuke whitelist.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=resp_embed, ephemeral=True)
        else:
            resp_embed = discord.Embed(
                title="ℹ Already Whitelisted",
                description=f"{user.mention} is already whitelisted.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=resp_embed, ephemeral=True)

    @app_commands.command(name="whitelist_remove", description="Remove a user from the Anti-Nuke whitelist.")
    @app_commands.default_permissions(administrator=True)
    async def whitelist_remove(self, interaction: discord.Interaction, user: discord.Member):
        if not self.can_manage_antinuke(interaction):
            await interaction.response.send_message(
                "⛔ **Hierarchy Access Denied:** Only the Server Owner or members with a role strictly higher than Friday can edit or configure Anti-Nuke settings.",
                ephemeral=True
            )
            return
        gid = str(interaction.guild.id)
        if gid in db.whitelist and user.id in db.whitelist[gid]:
            db.whitelist[gid].remove(user.id)
            db.save_data()
            embed = discord.Embed(
                title="🛡️ Whitelist Member Removed",
                description=f"{user.mention} (`{user.id}`) was removed from the Security Whitelist by {interaction.user.mention}.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(interaction.guild, "audit-whitelisted", embed)
            resp_embed = discord.Embed(
                title="✔ Whitelist Updated",
                description=f"{user.mention} has been removed from the Anti-Nuke whitelist.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=resp_embed, ephemeral=True)
        else:
            resp_embed = discord.Embed(
                title="✖ Not Whitelisted",
                description=f"{user.mention} was not on the Anti-Nuke whitelist.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=resp_embed, ephemeral=True)

    async def get_recent_audit_entry(self, guild: discord.Guild, action: discord.AuditLogAction, target_id=None, max_age_seconds: int = 25, wait_delay: float = 1.0):
        """
        Safely retrieve the relevant audit log entry matching target_id within max_age_seconds.
        Applies a slight propagation delay (wait_delay) to avoid reading stale logs before Discord's API updates.
        """
        if wait_delay > 0:
            await asyncio.sleep(wait_delay)
        
        try:
            async for entry in guild.audit_logs(action=action, limit=6):
                # Ensure the entry is fresh and not an old historical action
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if age > max_age_seconds:
                    continue
                
                # Match target ID if specified
                if target_id is not None:
                    entry_target_id = getattr(entry.target, 'id', None)
                    if str(entry_target_id) != str(target_id):
                        continue
                
                return entry
        except Exception:
            pass
        return None

    # ───────────────────── Security Event Listeners ─────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        guild = channel.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return

        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.channel_delete, target_id=channel.id)
        if not entry or not entry.user:
            embed = discord.Embed(
                title="📁 Channel Deleted",
                description=f"**Channel:** `#{channel.name}` (`{channel.id}`)\n**Deleted By:** Unknown / External Integration",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-channels", embed)
            return

        culprit = entry.user
        if self.is_whitelisted(guild, culprit, feature="channel_delete"): return
        
        # Log channel deletion to audit-channels
        embed = discord.Embed(
            title="📁 Channel Deleted",
            description=f"**Channel:** `#{channel.name}` (`{channel.id}`)\n**Deleted By:** {culprit.mention}",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        await self.log_security_event(guild, "audit-channels", embed)

        should_punish = self.record_action_and_check(guild.id, culprit.id, 'channel_delete')
        if should_punish:
            cfg = self.get_security_config(gid)
            rule = cfg.get("limits", {}).get("channel_delete", {})
            punishment = rule.get("punishment", "ban")
            tm = rule.get("timeout_mins", 10)
            await self.execute_punishment(guild, culprit, punishment, "Anti-Nuke: Triggered channel deletion limit.", log_channel="audit-antinuke", timeout_mins=tm, feature="channel_delete")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        guild = channel.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return

        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.channel_create, target_id=channel.id)
        if not entry or not entry.user:
            embed = discord.Embed(
                title="📁 Channel Created",
                description=f"**Channel:** {channel.mention} (`{channel.id}`)\n**Created By:** Unknown / External Integration",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-channels", embed)
            return

        culprit = entry.user
        if self.is_whitelisted(guild, culprit, feature="channel_create"): return

        # Log channel creation to audit-channels
        embed = discord.Embed(
            title="📁 Channel Created",
            description=f"**Channel:** {channel.mention} (`{channel.id}`)\n**Created By:** {culprit.mention}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        await self.log_security_event(guild, "audit-channels", embed)

        should_punish = self.record_action_and_check(guild.id, culprit.id, 'channel_create')
        if should_punish:
            cfg = self.get_security_config(gid)
            rule = cfg.get("limits", {}).get("channel_create", {})
            punishment = rule.get("punishment", "ban")
            tm = rule.get("timeout_mins", 10)
            await self.execute_punishment(guild, culprit, punishment, "Anti-Nuke: Triggered channel creation limit.", log_channel="audit-antinuke", timeout_mins=tm, feature="channel_create")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        guild = after.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return
        if before.name != after.name:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.channel_update, target_id=after.id)
            culprit = entry.user if entry else None
            if culprit and self.is_whitelisted(guild, culprit, feature="channel_rename"): return
            
            mod_str = culprit.mention if culprit else "Unknown / Unverified"
            embed = discord.Embed(
                title="📝 Channel Renamed",
                description=f"**Old Name:** `#{before.name}`\n**New Name:** {after.mention}\n**Updated By:** {mod_str}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-channels", embed)
            
            if culprit:
                cfg = self.get_security_config(gid)
                rule = cfg.get("instant", {}).get("channel_rename", {})
                if rule.get("enabled", False):
                    tm = rule.get("timeout_mins", 10)
                    await self.execute_punishment(guild, culprit, rule.get("punishment", "kick"), "Instant Punishment: Channel rename violation.", log_channel="audit-antinuke", timeout_mins=tm, feature="channel_rename")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        guild = role.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return

        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.role_delete, target_id=role.id)
        if not entry or not entry.user:
            embed = discord.Embed(
                title="🛡️ Role Deleted",
                description=f"**Role:** `@{role.name}` (`{role.id}`)\n**Deleted By:** Unknown / External Integration",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-roles", embed)
            return

        culprit = entry.user
        if self.is_whitelisted(guild, culprit, feature="role_delete"): return
        
        embed = discord.Embed(
            title="🛡️ Role Deleted",
            description=f"**Role:** `@{role.name}` (`{role.id}`)\n**Deleted By:** {culprit.mention}",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        await self.log_security_event(guild, "audit-roles", embed)

        should_punish = self.record_action_and_check(guild.id, culprit.id, 'role_delete')
        if should_punish:
            cfg = self.get_security_config(gid)
            rule = cfg.get("limits", {}).get("role_delete", {})
            punishment = rule.get("punishment", "ban")
            tm = rule.get("timeout_mins", 10)
            await self.execute_punishment(guild, culprit, punishment, "Anti-Nuke: Triggered role deletion limit.", log_channel="audit-antinuke", timeout_mins=tm, feature="role_delete")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        guild = role.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return

        # 1. Managed bot / integration roles (e.g. @AutoReacter created upon bot join)
        if role.managed:
            bot_str = "Managed Bot / Integration"
            if hasattr(role, 'tags') and role.tags and role.tags.bot_id:
                bot_mem = guild.get_member(role.tags.bot_id)
                bot_str = f"Managed Bot ({bot_mem.mention if bot_mem else f'<@{role.tags.bot_id}>'})"
            embed = discord.Embed(
                title="🛡️ Role Created",
                description=f"**Role:** {role.mention} (`{role.id}`)\n**Created By:** {bot_str}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-roles", embed)
            return

        # 2. Regular Roles: query fresh audit log matching THIS specific role ID
        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.role_create, target_id=role.id)
        if not entry or not entry.user:
            embed = discord.Embed(
                title="🛡️ Role Created",
                description=f"**Role:** {role.mention} (`{role.id}`)\n**Created By:** Unknown / External Integration",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-roles", embed)
            return

        culprit = entry.user
        if self.is_whitelisted(guild, culprit, feature="role_create"): return
        
        embed = discord.Embed(
            title="🛡️ Role Created",
            description=f"**Role:** {role.mention} (`{role.id}`)\n**Created By:** {culprit.mention}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        await self.log_security_event(guild, "audit-roles", embed)

        should_punish = self.record_action_and_check(guild.id, culprit.id, 'role_create')
        if should_punish:
            cfg = self.get_security_config(gid)
            rule = cfg.get("limits", {}).get("role_create", {})
            punishment = rule.get("punishment", "ban")
            tm = rule.get("timeout_mins", 10)
            await self.execute_punishment(guild, culprit, punishment, "Anti-Nuke: Triggered role creation limit.", log_channel="audit-antinuke", timeout_mins=tm, feature="role_create")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        guild = after.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return
        
        # Check dangerous permissions added
        had_dangerous = before.permissions.administrator or before.permissions.manage_guild or before.permissions.ban_members or before.permissions.manage_roles
        has_dangerous = after.permissions.administrator or after.permissions.manage_guild or after.permissions.ban_members or after.permissions.manage_roles
        
        if not had_dangerous and has_dangerous:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.role_update, target_id=after.id)
            culprit = entry.user if entry else None

            # 1. Immediately revert unauthorized permission escalation back to safe permissions!
            try:
                await after.edit(permissions=before.permissions, reason="Anti-Nuke: Reverting unauthorized dangerous role permission escalation.")
            except Exception:
                pass

            if culprit and self.is_whitelisted(guild, culprit, feature="dangerous_perms"): return

            mod_str = culprit.mention if culprit else "Unknown / Unverified"
            embed = discord.Embed(
                title="⚠️ Dangerous Role Permission Escalation",
                description=f"**Role:** {after.mention}\n**Escalated By:** {mod_str}\n**Added:** Administrator/Management Permissions (Reverted)",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-roles", embed)
            
            if culprit:
                cfg = self.get_security_config(gid)
                rule = cfg.get("instant", {}).get("dangerous_perms", {})
                if rule.get("enabled", True):
                    tm = rule.get("timeout_mins", 10)
                    await self.execute_punishment(guild, culprit, rule.get("punishment", "strip_roles"), "Instant Punishment: Dangerous role permission update.", log_channel="audit-antinuke", timeout_mins=tm, feature="dangerous_perms")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        guild = after.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return

        # Check if dangerous roles were added to the member
        added_roles = [
            r for r in after.roles 
            if r not in before.roles and (
                r.permissions.administrator or 
                r.permissions.manage_guild or 
                r.permissions.manage_roles or 
                r.permissions.ban_members or 
                r.permissions.manage_channels
            )
        ]
        if not added_roles: return

        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.member_role_update, target_id=after.id)
        if not entry or not entry.user: return
        culprit = entry.user
        if self.is_whitelisted(guild, culprit, feature="dangerous_role_add"): return
        
        # Revert unauthorized dangerous role assignments
        revert_roles = [r for r in added_roles if r < guild.me.top_role]
        if revert_roles:
            try:
                await after.remove_roles(*revert_roles, reason="Anti-Nuke: Unauthorized dangerous role assignment revoked.")
            except Exception:
                pass

        embed = discord.Embed(
            title="👑 Unauthorized Dangerous Role Added",
            description=f"**Target:** {after.mention} (`{after.id}`)\n**Role(s):** {', '.join([r.mention for r in added_roles])} (Revoked)\n**Assigned By:** {culprit.mention} (`{culprit.id}`)",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        await self.log_security_event(guild, "audit-roles", embed)

        cfg = self.get_security_config(gid)
        rule = cfg.get("instant", {}).get("dangerous_role_add", {})
        if rule.get("enabled", True):
            tm = rule.get("timeout_mins", 10)
            await self.execute_punishment(guild, culprit, rule.get("punishment", "strip_roles"), "Instant Punishment: Unauthorized dangerous role assignment.", log_channel="audit-antinuke", timeout_mins=tm, feature="dangerous_role_add")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        gid = str(guild.id)
        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"**User:** {user.mention} (`{user.id}`)\n**Tag:** `{user.name}`",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        await self.log_security_event(guild, "audit-banned", embed)

        if not db.antinuke_active.get(gid, True): return
        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.ban, target_id=user.id)
        if not entry or not entry.user: return
        culprit = entry.user
        if self.is_whitelisted(guild, culprit, feature="ban"): return
        should_punish = self.record_action_and_check(guild.id, culprit.id, 'ban')
        if should_punish:
            cfg = self.get_security_config(gid)
            rule = cfg.get("limits", {}).get("ban", {})
            punishment = rule.get("punishment", "ban")
            tm = rule.get("timeout_mins", 10)
            await self.execute_punishment(guild, culprit, punishment, "Anti-Nuke: Triggered mass-ban limit.", log_channel="audit-antinuke", timeout_mins=tm, feature="ban")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return
        
        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.kick, target_id=member.id)
        if not entry or not entry.user: return
        culprit = entry.user
        if self.is_whitelisted(guild, culprit, feature="kick"): return
        should_punish = self.record_action_and_check(guild.id, culprit.id, 'kick')
        if should_punish:
            cfg = self.get_security_config(gid)
            rule = cfg.get("limits", {}).get("kick", {})
            punishment = rule.get("punishment", "kick")
            tm = rule.get("timeout_mins", 10)
            await self.execute_punishment(guild, culprit, punishment, "Anti-Nuke: Triggered mass-kick limit.", log_channel="audit-antinuke", timeout_mins=tm, feature="kick")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return
        cfg = self.get_security_config(gid)

        # 1. Anti-Bot Add Instant Protection
        if member.bot:
            rule = cfg.get("instant", {}).get("bot_add", {})
            if rule.get("enabled", True):
                entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.bot_add, target_id=member.id)
                if entry and entry.user:
                    inviter = entry.user
                    if not self.is_whitelisted(guild, inviter, feature="bot_add"):
                        try:
                            await member.kick(reason="Anti-Bot: Unauthorized bot addition.")
                        except Exception:
                            pass
                        tm = rule.get("timeout_mins", 10)
                        await self.execute_punishment(
                            guild, inviter, rule.get("punishment", "kick"),
                            f"Anti-Bot: Added unauthorized bot ({member.name}) without whitelist.",
                            log_channel="audit-antinuke",
                            timeout_mins=tm,
                            feature="bot_add"
                        )
            return

        # 2. Anti-Raid Join Flood Protection
        antiraid = cfg.get("antiraid", {})
        if antiraid.get("enabled", True):
            now = time.time()
            window = antiraid.get("time_window", 10)
            threshold = antiraid.get("join_threshold", 5)

            if gid not in self.recent_joins:
                self.recent_joins[gid] = []
            self.recent_joins[gid].append(now)
            self.recent_joins[gid] = [t for t in self.recent_joins[gid] if now - t <= window]

            if len(self.recent_joins[gid]) >= threshold:
                embed = discord.Embed(
                    title="🚨 ANTI-RAID TRIGGERED: MASS JOIN SURGE",
                    description=f"Detected **{len(self.recent_joins[gid])} joins** in {window} seconds!\n**Raider Member:** {member.mention} (`{member.id}`)\nAction taken: Automatic Quarantine/Protection.",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-antiraid", embed)

                action = antiraid.get("action", "kick")
                tm = antiraid.get("timeout_mins", 10)
                if action == "ban":
                    try: await member.ban(reason="Anti-Raid: Mass join velocity surge.")
                    except Exception: pass
                elif action == "timeout":
                    try: await member.timeout(datetime.timedelta(minutes=tm), reason="Anti-Raid: Mass join velocity surge.")
                    except Exception: pass
                else:
                    try: await member.kick(reason="Anti-Raid: Mass join velocity surge.")
                    except Exception: pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot: return
        guild = message.guild
        gid = str(guild.id)
        author = message.author

        if not db.antinuke_active.get(gid, True): return
        cfg = self.get_security_config(gid)

        # Check if author is Server Owner, Administrator, or Whitelisted
        is_admin_or_owner = False
        if isinstance(author, discord.Member):
            is_admin_or_owner = (
                author.id == guild.owner_id or
                author.guild_permissions.administrator or
                author.guild_permissions.manage_guild or
                author.guild_permissions.manage_messages
            )
        is_immune = is_admin_or_owner or self.is_whitelisted(guild, author)

        # 1. Detect Only: Anti Invite Link (Auto-Delete & Log)
        if cfg.get("detect", {}).get("invite_link", {}).get("enabled", True) and self.invite_regex.search(message.content):
            if not is_immune and not self.is_whitelisted(guild, author, feature="invite_link"):
                try:
                    await message.delete()
                except Exception:
                    pass
                try:
                    resp_tpl = db.custom_responses.get(gid, {}).get("security_invite_warn", "🔗 {member}, discord invite links are not allowed in this server.")
                    warn_msg = await message.channel.send(resp_tpl.replace("{member}", author.mention))
                    await warn_msg.delete(delay=5)
                except Exception:
                    pass
                embed = discord.Embed(
                    title="🔗 Invite Link Removed",
                    description=f"**User:** {author.mention}\n**Channel:** {message.channel.mention}\n**Content:** `{message.content[:200]}`",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-antispam", embed)
                return

        # 2. Detect Only: Anti Link (Auto-Delete & Log)
        if cfg.get("detect", {}).get("anti_link", {}).get("enabled", True) and self.link_regex.search(message.content):
            can_send_link = is_immune or self.is_whitelisted(guild, author, feature="anti_link")

            if not can_send_link:
                # Check if this is a GIF (tenor, giphy, or .gif) and member has embed/attachment permissions
                gif_patterns = re.compile(r'(?:tenor\.com|giphy\.com|gfycat\.com|\.gif(?:\?|$)|media\.discordapp\.net/attachments/.*\.gif)', re.IGNORECASE)
                is_gif = bool(gif_patterns.search(message.content))
                if is_gif and isinstance(author, discord.Member):
                    channel_perms = message.channel.permissions_for(author)
                    if channel_perms.embed_links or channel_perms.attach_files:
                        can_send_link = True

            if not can_send_link:
                try:
                    await message.delete()
                except Exception:
                    pass
                try:
                    resp_tpl = db.custom_responses.get(gid, {}).get("security_link_warn", "🔗 {member}, external links are not allowed in this server.")
                    warn_msg = await message.channel.send(resp_tpl.replace("{member}", author.mention))
                    await warn_msg.delete(delay=5)
                except Exception:
                    pass
                embed = discord.Embed(
                    title="🔗 Link Removed",
                    description=f"**User:** {author.mention}\n**Channel:** {message.channel.mention}\n**Content:** `{message.content[:200]}`",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-antispam", embed)
                return

        # Whitelist protects administrative commands & punishments
        if is_immune or self.is_whitelisted(guild, author, feature="antispam"):
            return

        # 3. Anti-Mention Limit
        mention_rule = cfg.get("limits", {}).get("mention", {})
        if mention_rule.get("enabled", True):
            total_mentions = len(message.mentions) + len(message.role_mentions)
            mention_limit = mention_rule.get("limit", 5)
            if total_mentions >= mention_limit:
                if self.is_whitelisted(guild, author, feature="mention"):
                    return
                try:
                    await message.delete()
                except Exception:
                    pass
                punishment = mention_rule.get("punishment", "timeout")
                tm = mention_rule.get("timeout_mins", 10)
                await self.execute_punishment(guild, author, punishment, f"Anti-Mention: Exceeded mass mention limit ({total_mentions} mentions).", log_channel="audit-antispam", timeout_mins=tm, feature="mention")
                return

        # 4. Anti-Spam Rate Flood & Duplicates
        antispam = cfg.get("antispam", {})
        if antispam.get("enabled", True):
            now = time.time()
            uid = str(author.id)
            window = antispam.get("time_window", 4)
            rate_limit = antispam.get("rate_limit", 5)
            dup_limit = antispam.get("duplicate_limit", 3)
            action = antispam.get("action", "timeout")
            tm = antispam.get("timeout_mins", 2)

            if gid not in self.message_tracker:
                self.message_tracker[gid] = {}
            if uid not in self.message_tracker[gid]:
                self.message_tracker[gid][uid] = []

            self.message_tracker[gid][uid].append((now, message.content.strip().lower()))
            self.message_tracker[gid][uid] = [entry for entry in self.message_tracker[gid][uid] if now - entry[0] <= window]

            entries = self.message_tracker[gid][uid]
            # Check rate flood
            if len(entries) >= rate_limit:
                try:
                    await message.channel.purge(limit=25, check=lambda m: m.author.id == author.id and (now - m.created_at.timestamp()) <= window + 5)
                except Exception:
                    pass
                try:
                    resp_spam = db.custom_responses.get(gid, {}).get("security_spam_warn", "⚠️ {member}, please slow down! Spamming is not permitted.")
                    warn_msg = await message.channel.send(resp_spam.replace("{member}", author.mention))
                    await warn_msg.delete(delay=5)
                except Exception:
                    pass
                await self.execute_punishment(guild, author, action, f"Anti-Spam: Sent {len(entries)} messages in {window}s.", log_channel="audit-antispam", timeout_mins=tm)
                self.message_tracker[gid][uid] = []
                return

            # Check duplicate message flood
            if len(entries) >= dup_limit:
                contents = [e[1] for e in entries[-dup_limit:] if len(e[1]) > 2]
                if len(contents) >= dup_limit and len(set(contents)) == 1:
                    try:
                        await message.channel.purge(limit=20, check=lambda m: m.author.id == author.id and (now - m.created_at.timestamp()) <= window + 10)
                    except Exception:
                        pass
                    try:
                        resp_spam = db.custom_responses.get(gid, {}).get("security_spam_warn", "⚠️ {member}, please slow down! Spamming is not permitted.")
                        warn_msg = await message.channel.send(resp_spam.replace("{member}", author.mention))
                        await warn_msg.delete(delay=5)
                    except Exception:
                        pass
                    await self.execute_punishment(guild, author, action, "Anti-Spam: Repeated identical message flood.", log_channel="audit-antispam", timeout_mins=tm)
                    self.message_tracker[gid][uid] = []
                    return

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot: return
        guild = message.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return
        cfg = self.get_security_config(gid)

        # Ghost Ping Detection
        if cfg.get("detect", {}).get("ghost_ping", {}).get("enabled", True):
            if (message.mentions or message.role_mentions) and not self.is_whitelisted(guild, message.author):
                mentions_str = ", ".join([m.mention for m in message.mentions] + [r.mention for r in message.role_mentions])
                embed = discord.Embed(
                    title="👻 Ghost Ping Detected",
                    description=f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Pings Mentioned:** {mentions_str}\n**Original Content:** `{message.content[:250]}`",
                    color=discord.Color.dark_purple(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-antispam", embed)

        # Standard Deleted Message Log
        log_id = db.server_logs.get(gid, {}).get("audit-deleted")
        if log_id:
            log_channel = self.bot.get_channel(log_id)
            if log_channel:
                timestamp = discord.utils.utcnow().strftime("%B %d, %Y at %I:%M %p UTC")
                embed = discord.Embed(title="🗑️ Message Deleted", color=discord.Color.red())
                embed.add_field(name="Author", value=message.author.mention, inline=True)
                embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                embed.add_field(name="Content", value=message.content if message.content else "*No text*", inline=False)
                embed.set_footer(text=f"Deleted on {timestamp}")
                try:
                    await log_channel.send(embed=embed)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        gid = str(after.id)
        if not db.antinuke_active.get(gid, True): return
        cfg = self.get_security_config(gid)

        entry = await self.get_recent_audit_entry(after, discord.AuditLogAction.guild_update)
        culprit = entry.user if entry else None

        # Server Rename
        if before.name != after.name:
            if culprit and self.is_whitelisted(after, culprit, feature="server_rename"): pass
            else:
                mod_str = culprit.mention if culprit else "Unknown / Unverified"
                embed = discord.Embed(
                    title="🏰 Server Renamed",
                    description=f"**Old Name:** `{before.name}`\n**New Name:** `{after.name}`\n**Modified By:** {mod_str}",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(after, "audit-antinuke", embed)
                if culprit:
                    rule = cfg.get("instant", {}).get("server_rename", {})
                    if rule.get("enabled", True):
                        tm = rule.get("timeout_mins", 10)
                        await self.execute_punishment(after, culprit, rule.get("punishment", "kick"), "Instant Punishment: Server rename violation.", timeout_mins=tm, feature="server_rename")

        # Server Icon Change
        if before.icon != after.icon:
            if culprit and self.is_whitelisted(after, culprit, feature="server_icon"): pass
            else:
                mod_str = culprit.mention if culprit else "Unknown / Unverified"
                embed = discord.Embed(
                    title="🖼️ Server Icon Modified",
                    description=f"**Modified By:** {mod_str}",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(after, "audit-antinuke", embed)
                if culprit:
                    rule = cfg.get("instant", {}).get("server_icon", {})
                    if rule.get("enabled", True):
                        tm = rule.get("timeout_mins", 10)
                        await self.execute_punishment(after, culprit, rule.get("punishment", "kick"), "Instant Punishment: Server icon modification.", timeout_mins=tm, feature="server_icon")

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return
        cfg = self.get_security_config(gid)

        # 1. Emoji Delete
        if len(after) < len(before):
            deleted = [e for e in before if e.id not in [a.id for a in after]]
            del_names = ", ".join([f":{e.name}:" for e in deleted])
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.emoji_delete)
            culprit = entry.user if entry else None
            
            if culprit and self.is_whitelisted(guild, culprit, feature="emoji_delete"): return
            del_str = culprit.mention if culprit else "Unknown / Unverified"
            embed = discord.Embed(
                title="💔 Emoji Deleted",
                description=f"**Emojis:** {del_names}\n**Deleted By:** {del_str}",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-antinuke", embed)
            if culprit:
                rule = cfg.get("instant", {}).get("emoji_delete", {})
                if rule.get("enabled", False):
                    tm = rule.get("timeout_mins", 10)
                    await self.execute_punishment(guild, culprit, rule.get("punishment", "kick"), "Instant Punishment: Emoji deletion violation.", log_channel="audit-antinuke", timeout_mins=tm, feature="emoji_delete")

        # 2. Emoji Rename
        elif len(after) == len(before):
            before_map = {e.id: e.name for e in before}
            renamed = [a for a in after if a.id in before_map and before_map[a.id] != a.name]
            if renamed:
                r_details = ", ".join([f"`{before_map[e.id]}` ➔ `{e.name}`" for e in renamed])
                entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.emoji_update)
                culprit = entry.user if entry else None

                if culprit and self.is_whitelisted(guild, culprit, feature="emoji_rename"): return
                mod_str = culprit.mention if culprit else "Unknown / Unverified"
                embed = discord.Embed(
                    title="✏️ Emoji Renamed",
                    description=f"**Renamed:** {r_details}\n**Modified By:** {mod_str}",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-antinuke", embed)
                if culprit:
                    rule = cfg.get("instant", {}).get("emoji_rename", {})
                    if rule.get("enabled", False):
                        tm = rule.get("timeout_mins", 10)
                        await self.execute_punishment(guild, culprit, rule.get("punishment", "kick"), "Instant Punishment: Emoji rename violation.", log_channel="audit-antinuke", timeout_mins=tm, feature="emoji_rename")

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        guild = invite.guild
        if not guild: return
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return

        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.invite_delete)
        culprit = entry.user if entry else None

        if culprit and self.is_whitelisted(guild, culprit, feature="invite_delete"): return
        del_str = culprit.mention if culprit else "Unknown / Unverified"
        embed = discord.Embed(
            title="🗑️ Invite Deleted",
            description=f"**Invite Code:** `{invite.code}`\n**Deleted By:** {del_str}",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        await self.log_security_event(guild, "audit-antinuke", embed)
        if culprit:
            cfg = self.get_security_config(gid)
            rule = cfg.get("instant", {}).get("invite_delete", {})
            if rule.get("enabled", False):
                tm = rule.get("timeout_mins", 10)
                await self.execute_punishment(guild, culprit, rule.get("punishment", "kick"), "Instant Punishment: Invite deletion violation.", log_channel="audit-antinuke", timeout_mins=tm, feature="invite_delete")

async def setup(bot):
    await bot.add_cog(Security(bot))
