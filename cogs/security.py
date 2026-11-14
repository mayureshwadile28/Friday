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
    "audit-edits",
    "audit-banned",
    "audit-timeouts",
    "audit-whitelisted",
    "audit-antinuke",
    "audit-abuse",
    "audit-antiraid",
    "audit-antispam",
    "audit-roles",
    "audit-channels",
    "audit-voice",
    "audit-members",
    "audit-server"
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
        "anti_link": {"enabled": True, "allow_gifs": True},
        "anti_gif": {"enabled": False},
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
        import copy
        for key in ["limits", "instant", "detect", "antiraid", "antispam"]:
            if key not in cfg:
                cfg[key] = copy.deepcopy(DEFAULT_SECURITY_CONFIG[key])
        if "detect" in cfg:
            for det_k, det_v in DEFAULT_SECURITY_CONFIG["detect"].items():
                if det_k not in cfg["detect"]:
                    cfg["detect"][det_k] = copy.deepcopy(det_v)
        return cfg

    def is_whitelisted(self, guild: discord.Guild, member_or_user, feature: str = None) -> bool:
        if not member_or_user: return True
        if member_or_user.id == self.bot.user.id: return True
        if member_or_user.id == guild.owner_id: return True
        gid_str = str(guild.id)
        gid_int = int(guild.id) if str(guild.id).isdigit() else None
        
        # 1. Direct user whitelist (Master / Universal Immunity: covers ALL security, links, gifs, invites, antinuke)
        wl_raw = (db.whitelist.get(gid_str, []) or []) + (db.whitelist.get(gid_int, []) or [] if gid_int else [])
        wl_set = {str(x) for x in wl_raw}
        if str(member_or_user.id) in wl_set:
            return True

        # 2. Feature-specific whitelist (Granular per-action overrides)
        feat_set = set()
        if feature:
            feat_dict = db.feature_whitelists.get(gid_str, {}) or db.feature_whitelists.get(gid_int, {}) or {}
            feat_raw = feat_dict.get(feature, []) or []
            feat_set = {str(x) for x in feat_raw}
            if str(member_or_user.id) in feat_set:
                return True

        # 3. Check role-based whitelisting (if member)
        member = member_or_user if hasattr(member_or_user, "roles") else (guild.get_member(member_or_user.id) if guild else None)
        if member and hasattr(member, "roles"):
            for role in member.roles:
                rid_str = str(role.id)
                if rid_str in wl_set:
                    return True
                if feature and rid_str in feat_set:
                    return True

        # Note: Administrators and higher-role members are NOT automatically immune to anti-nuke or security rules.
        # Only the Server Owner, bot, or explicitly whitelisted users/roles have immunity.
        return False

    def is_gif_url(self, url: str) -> bool:
        """Check if a URL points to a GIF or GIF service (Tenor, Giphy, Gfycat, Discord, Imgur)."""
        if not url:
            return False
        # Common GIF providers (including subdomains and shortlinks like tenor.co, gph.is, media.tenor.com, c.tenor.com, i.giphy.com)
        if re.search(r'(?:tenor\.(?:com|co)|giphy\.com|gph\.is|gfycat\.com)', url, re.IGNORECASE):
            return True
        # Direct .gif or .gifv extensions or imgur gifv with optional query parameters/fragments
        if re.search(r'\.(?:gif|gifv)(?:[?&#/].*)?$', url, re.IGNORECASE) or re.search(r'\.(?:gif|gifv)\b', url, re.IGNORECASE):
            return True
        # Discord attachments/media links ending in .gif or .gifv
        if re.search(r'(?:cdn|media)\.discordapp\.(?:com|net)/attachments/.*\.(?:gif|gifv)', url, re.IGNORECASE):
            return True
        # Imgur image / gif links
        if re.search(r'imgur\.com/.*\.(?:gif|gifv)', url, re.IGNORECASE):
            return True
        return False

    def is_gif_attachment(self, attachment: discord.Attachment) -> bool:
        """Check if an attachment is an animated GIF."""
        if not attachment:
            return False
        ct = (attachment.content_type or "").lower()
        fn = (attachment.filename or "").lower()
        return "image/gif" in ct or fn.endswith((".gif", ".gifv"))

    def has_gif_content(self, message: discord.Message) -> bool:
        """Return True if the message contains any GIF link, GIF attachment, or GIF embed."""
        for att in getattr(message, "attachments", []):
            if self.is_gif_attachment(att):
                return True
        for link in self.link_regex.findall(getattr(message, "content", "")):
            if self.is_gif_url(link):
                return True
        for emb in getattr(message, "embeds", []):
            if getattr(emb, "type", "") == "gifv":
                return True
            if emb.url and self.is_gif_url(emb.url):
                return True
            if emb.image and emb.image.url and self.is_gif_url(emb.image.url):
                return True
            if emb.video and emb.video.url and self.is_gif_url(emb.video.url):
                return True
            if emb.thumbnail and emb.thumbnail.url and self.is_gif_url(emb.thumbnail.url):
                return True
        return False

    def member_has_embed_permission(self, member, channel) -> bool:
        """Check if a member explicitly has embed_links or attach_files via role.
        NOTE: Administrator does NOT count here — admins are still subject to anti-gif/anti-link rules
        unless they are explicitly whitelisted. manage_guild / manage_messages also do NOT exempt."""
        if not isinstance(member, discord.Member):
            return False
        gp = member.guild_permissions
        # Only explicit embed/attach bits grant bypass — NOT administrator or manage_guild.
        if gp.embed_links or gp.attach_files:
            return True
        if hasattr(channel, "permissions_for"):
            try:
                cp = channel.permissions_for(member)
                if cp.embed_links or cp.attach_files:
                    return True
            except Exception:
                pass
        return False

    async def safe_delete_violating_message(self, message: discord.Message, violation_label: str = "violation") -> bool:
        """Directly attempts to delete a violating message. Returns True if deleted or already gone.
        Tries message.delete() first, then channel.delete_messages() as a fallback.
        Only returns False if Discord API explicitly denies deletion with 403 Forbidden."""
        guild = message.guild
        if not guild:
            return False

        # --- Attempt 1: Standard single-message delete ---
        try:
            await message.delete()
            return True
        except discord.NotFound:
            return True  # Already deleted, that's fine
        except discord.Forbidden:
            pass  # Fall through to Attempt 2
        except Exception:
            pass

        # --- Attempt 2: Bulk-delete fallback (different API endpoint, bypasses some channel quirks) ---
        if hasattr(message.channel, "delete_messages"):
            try:
                await message.channel.delete_messages([message])
                return True
            except discord.NotFound:
                return True
            except Exception:
                pass

        # Both attempts failed or raised Forbidden. Log full diagnostic info to audit channel.
        channel = message.channel
        me = guild.me or guild.get_member(self.bot.user.id)
        if me:
            gp = me.guild_permissions
            try:
                cp = channel.permissions_for(me)
                cp_admin = cp.administrator
                cp_manage = cp.manage_messages
                cp_admin_bits = gp.administrator
            except Exception:
                cp_admin = cp_manage = cp_admin_bits = "unknown"
        else:
            cp_admin = cp_manage = cp_admin_bits = "bot member not found"

        embed = discord.Embed(
            title="⛔ Message Deletion Forbidden — Both Methods Failed",
            description=(
                f"**Culprit:** {message.author.mention} (`{message.author.id}`)\n"
                f"**Channel:** {channel.mention} (`{channel.id}`)\n"
                f"**Message ID:** `{message.id}`\n"
                f"**Violation:** {violation_label}\n"
                f"**Friday's Guild Admin Perm:** `{cp_admin_bits}`\n"
                f"**Friday's Channel Admin Override:** `{cp_admin}`\n"
                f"**Friday's Channel Manage Messages:** `{cp_manage}`\n\n"
                f"⚠️ **Action Required:** Go to **Server Settings → Roles**, ensure Friday's role has "
                f"**Administrator** checked AND is **above all other roles** in the list. "
                f"If Friday has Administrator, channel overwrites cannot block her."
            ),
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow()
        )
        try:
            await self.log_security_event(guild, "audit-antispam", embed)
        except Exception:
            pass
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
        if not guild:
            return
        gid = str(guild.id)
        chan_id = db.server_logs.get(gid, {}).get(channel_name)
        if not chan_id:
            # Smart fallbacks to existing channels if specific channel not created yet
            if channel_name == "audit-edits":
                chan_id = db.server_logs.get(gid, {}).get("audit-deleted")
            elif channel_name == "audit-voice":
                chan_id = db.server_logs.get(gid, {}).get("audit-channels")
            elif channel_name == "audit-members":
                chan_id = db.server_logs.get(gid, {}).get("audit-roles")
            elif channel_name == "audit-server":
                chan_id = db.server_logs.get(gid, {}).get("audit-antinuke")
            if not chan_id:
                chan_id = db.server_logs.get(gid, {}).get("audit-antinuke")
        if chan_id:
            ch = guild.get_channel(chan_id)
            if not ch:
                try:
                    ch = self.bot.get_channel(chan_id)
                except Exception:
                    ch = None
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
        
        # Resolve culprit to Member if passed as discord.User
        if not isinstance(culprit, discord.Member):
            mem = guild.get_member(culprit.id)
            if not mem:
                try:
                    mem = await guild.fetch_member(culprit.id)
                except Exception:
                    mem = None
            if mem:
                culprit = mem

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
                if isinstance(culprit, discord.Member):
                    await guild.kick(culprit, reason=reason)
                    success = True
                else:
                    await guild.ban(culprit, reason=f"{reason} (Kicked via ban as user was not in cache)")
                    await guild.unban(culprit, reason="Unbanning after simulated kick")
                    success = True
            elif punishment_type == "strip_roles":
                if isinstance(culprit, discord.Member):
                    dangerous_roles = [r for r in culprit.roles if (r.permissions.administrator or r.permissions.manage_guild or r.permissions.ban_members or r.permissions.manage_roles or r.permissions.manage_channels) and r < guild.me.top_role]
                    if dangerous_roles:
                        await culprit.remove_roles(*dangerous_roles, reason=reason)
                    success = True
                else:
                    success = True
            elif punishment_type == "timeout":
                if isinstance(culprit, discord.Member):
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
                    success = False
                    error_detail = "Target is not currently a member in this server."
            else:
                if isinstance(culprit, discord.Member):
                    await guild.kick(culprit, reason=reason)
                else:
                    await guild.ban(culprit, reason=reason)
                success = True
        except discord.Forbidden:
            is_member = isinstance(culprit, discord.Member)
            if is_member and guild.me.top_role <= culprit.top_role:
                error_detail = "Friday's role is below this user in role hierarchy. Place Friday at top of Roles in Server Settings!"
                # Emergency mitigation: attempt to strip any subordinate dangerous roles below Friday
                try:
                    subordinate_dangerous_roles = [
                        r for r in culprit.roles 
                        if (r.permissions.administrator or r.permissions.manage_guild or r.permissions.ban_members or r.permissions.manage_roles or r.permissions.manage_channels) 
                        and r < guild.me.top_role
                    ]
                    if subordinate_dangerous_roles:
                        await culprit.remove_roles(*subordinate_dangerous_roles, reason=f"Emergency partial mitigation: {reason}")
                except Exception:
                    pass
            elif is_member and culprit.guild_permissions.administrator:
                error_detail = "Discord forbids timing out users with Administrator permission. Dangerous roles could not be removed."
            else:
                error_detail = "Discord permission error (403 Forbidden). Ensure Friday has required moderation permissions."

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
        # 1. Server Owner always permitted
        if interaction.user.id == guild.owner_id:
            return True
        # 2. Bot Owner always permitted
        if hasattr(self.bot, "owner_id") and self.bot.owner_id and interaction.user.id == self.bot.owner_id:
            return True
        if hasattr(self.bot, "owner_ids") and self.bot.owner_ids and interaction.user.id in self.bot.owner_ids:
            return True
        # 3. Whitelisted Co-Owner / Second Owner (direct user ID or whitelisted role)
        user = interaction.user
        gid_str = str(guild.id)
        gid_int = int(guild.id) if str(guild.id).isdigit() else None
        wl_raw = (db.whitelist.get(gid_str, []) or []) + (db.whitelist.get(gid_int, []) or [] if gid_int else [])
        wl_set = {str(x) for x in wl_raw}
        if str(user.id) in wl_set:
            return True
        if hasattr(user, "roles"):
            for role in user.roles:
                if str(role.id) in wl_set:
                    return True
        return False

    @app_commands.command(name="antinuke_toggle", description="Turn the Anti-Nuke system ON or OFF.")
    @app_commands.choices(status=[
        app_commands.Choice(name="Turn ON", value=1),
        app_commands.Choice(name="Turn OFF", value=0)
    ])
    @app_commands.default_permissions(administrator=True)
    async def antinuke_toggle(self, interaction: discord.Interaction, status: app_commands.Choice[int]):
        if not self.can_manage_antinuke(interaction):
            await interaction.response.send_message(
                "⛔ **Access Denied:** Only the Server Owner or whitelisted security administrators can edit or configure Anti-Nuke settings.",
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
                "⛔ **Access Denied:** Only the Server Owner or whitelisted security administrators can edit or configure Anti-Nuke settings.",
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
                "⛔ **Access Denied:** Only the Server Owner or whitelisted security administrators can edit or configure Anti-Nuke settings.",
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
                "⛔ **Access Denied:** Only the Server Owner or whitelisted security administrators can edit or configure Anti-Nuke settings.",
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
                "⛔ **Access Denied:** Only the Server Owner or whitelisted security administrators can edit or configure Anti-Nuke settings.",
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
        else: await interaction.followup.send(f"✅ All {len(CHANNELS_TO_CHECK)} security log channels already exist and are fully linked to Friday's systems.")

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
                "⛔ **Access Denied:** Only the Server Owner or whitelisted security administrators can edit or configure Anti-Nuke settings.",
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
                "⛔ **Access Denied:** Only the Server Owner or whitelisted security administrators can edit or configure Anti-Nuke settings.",
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
                "⛔ **Access Denied:** Only the Server Owner or whitelisted security administrators can edit or configure Anti-Nuke settings.",
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

        # 1. Channel Rename
        if before.name != after.name:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.channel_update, target_id=after.id)
            culprit = entry.user if entry else None
            if culprit and self.is_whitelisted(guild, culprit, feature="channel_rename"): pass
            else:
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

        # 2. Channel Topic Change
        old_topic = getattr(before, 'topic', None)
        new_topic = getattr(after, 'topic', None)
        if old_topic != new_topic:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.channel_update, target_id=after.id)
            culprit = entry.user if entry else None
            mod_str = culprit.mention if culprit else "Unknown / Unverified"
            embed = discord.Embed(
                title="📝 Channel Topic Modified",
                description=f"**Channel:** {after.mention}\n**Updated By:** {mod_str}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Old Topic", value=f"`{old_topic[:1000]}`" if old_topic else "*None*", inline=False)
            embed.add_field(name="New Topic", value=f"`{new_topic[:1000]}`" if new_topic else "*None*", inline=False)
            await self.log_security_event(guild, "audit-channels", embed)

        # 3. Slowmode (Rate Limit) Change
        old_slow = getattr(before, 'slowmode_delay', 0)
        new_slow = getattr(after, 'slowmode_delay', 0)
        if old_slow != new_slow:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.channel_update, target_id=after.id)
            culprit = entry.user if entry else None
            mod_str = culprit.mention if culprit else "Unknown / Unverified"
            embed = discord.Embed(
                title="⏱️ Channel Slowmode Modified",
                description=f"**Channel:** {after.mention}\n**Old Slowmode:** `{old_slow}s`\n**New Slowmode:** `{new_slow}s`\n**Updated By:** {mod_str}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-channels", embed)

        # 4. NSFW Age-Restriction Toggled
        if hasattr(before, 'is_nsfw') and hasattr(after, 'is_nsfw') and before.is_nsfw() != after.is_nsfw():
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.channel_update, target_id=after.id)
            culprit = entry.user if entry else None
            mod_str = culprit.mention if culprit else "Unknown / Unverified"
            embed = discord.Embed(
                title="🔞 Age-Restriction (NSFW) Toggled",
                description=f"**Channel:** {after.mention}\n**Status:** **{'Enabled' if after.is_nsfw() else 'Disabled'}**\n**Updated By:** {mod_str}",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-channels", embed)

        # 5. Permission Overwrites Changes
        if hasattr(before, 'overwrites') and hasattr(after, 'overwrites') and before.overwrites != after.overwrites:
            before_targets = set(before.overwrites.keys())
            after_targets = set(after.overwrites.keys())
            
            created_targets = after_targets - before_targets
            deleted_targets = before_targets - after_targets
            common_targets = before_targets & after_targets

            entry = (
                await self.get_recent_audit_entry(guild, discord.AuditLogAction.overwrite_create, target_id=after.id) or
                await self.get_recent_audit_entry(guild, discord.AuditLogAction.overwrite_update, target_id=after.id) or
                await self.get_recent_audit_entry(guild, discord.AuditLogAction.overwrite_delete, target_id=after.id) or
                await self.get_recent_audit_entry(guild, discord.AuditLogAction.channel_update, target_id=after.id)
            )
            mod_str = entry.user.mention if entry and entry.user else "Unknown / Unverified"

            changes_desc = []
            for t in created_targets:
                changes_desc.append(f"➕ Added overwrites for {t.mention}")
            for t in deleted_targets:
                changes_desc.append(f"➖ Deleted overwrites for {t.mention}")
            for t in common_targets:
                b_ov = before.overwrites[t]
                a_ov = after.overwrites[t]
                if b_ov != a_ov:
                    b_allow, b_deny = b_ov.pair()
                    a_allow, a_deny = a_ov.pair()
                    diffs = []
                    for perm, val in a_allow:
                        if val and not getattr(b_allow, perm):
                            diffs.append(f"✅ `{perm.replace('_', ' ').title()}`")
                    for perm, val in a_deny:
                        if val and not getattr(b_deny, perm):
                            diffs.append(f"❌ `{perm.replace('_', ' ').title()}`")
                    for perm, val in b_allow:
                        if val and not getattr(a_allow, perm) and not getattr(a_deny, perm):
                            diffs.append(f"⚪ Reset `{perm.replace('_', ' ').title()}`")
                    for perm, val in b_deny:
                        if val and not getattr(a_deny, perm) and not getattr(a_allow, perm):
                            diffs.append(f"⚪ Reset `{perm.replace('_', ' ').title()}`")
                    if diffs:
                        changes_desc.append(f"✏️ **{t.mention}:** {', '.join(diffs[:6])}")

            if changes_desc:
                embed = discord.Embed(
                    title="🔒 Channel Permissions Modified",
                    description=f"**Channel:** {after.mention} (`#{after.name}`)\n**Modified By:** {mod_str}\n\n" + "\n".join(changes_desc[:8]),
                    color=discord.Color.dark_teal(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-channels", embed)

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
        
        # 1. Anti-Nuke: Check dangerous permissions added
        had_dangerous = before.permissions.administrator or before.permissions.manage_guild or before.permissions.ban_members or before.permissions.manage_roles
        has_dangerous = after.permissions.administrator or after.permissions.manage_guild or after.permissions.ban_members or after.permissions.manage_roles
        
        if not had_dangerous and has_dangerous:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.role_update, target_id=after.id)
            culprit = entry.user if entry else None

            # Revert unauthorized permission escalation back to safe permissions
            try:
                await after.edit(permissions=before.permissions, reason="Anti-Nuke: Reverting unauthorized dangerous role permission escalation.")
            except Exception:
                pass

            if culprit and self.is_whitelisted(guild, culprit, feature="dangerous_perms"): pass
            else:
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
            return

        # 2. General Role Permission Updates Log
        if before.permissions.value != after.permissions.value:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.role_update, target_id=after.id)
            culprit = entry.user if entry else None
            mod_str = culprit.mention if culprit else "Unknown / Unverified"

            added_perms = [p.replace('_', ' ').title() for p, val in after.permissions if val and not getattr(before.permissions, p)]
            revoked_perms = [p.replace('_', ' ').title() for p, val in before.permissions if val and not getattr(after.permissions, p)]

            embed = discord.Embed(
                title="🛡️ Role Permissions Modified",
                description=f"**Role:** {after.mention} (`@{after.name}`)\n**Updated By:** {mod_str}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            if added_perms:
                embed.add_field(name="➕ Granted Permissions", value=", ".join([f"`{p}`" for p in added_perms[:10]]), inline=False)
            if revoked_perms:
                embed.add_field(name="➖ Revoked Permissions", value=", ".join([f"`{p}`" for p in revoked_perms[:10]]), inline=False)
            await self.log_security_event(guild, "audit-roles", embed)

        # 3. Role Settings (Name, Color, Hoist, Mentionable)
        settings_diff = []
        if before.name != after.name:
            settings_diff.append(f"• **Name:** `@{before.name}` ➔ `@{after.name}`")
        if before.color != after.color:
            settings_diff.append(f"• **Color:** `{before.color}` ➔ `{after.color}`")
        if before.hoist != after.hoist:
            settings_diff.append(f"• **Display Separately:** `{'Yes' if after.hoist else 'No'}`")
        if before.mentionable != after.mentionable:
            settings_diff.append(f"• **Mentionable:** `{'Yes' if after.mentionable else 'No'}`")

        if settings_diff:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.role_update, target_id=after.id)
            culprit = entry.user if entry else None
            mod_str = culprit.mention if culprit else "Unknown / Unverified"
            embed = discord.Embed(
                title="🛡️ Role Settings Updated",
                description=f"**Role:** {after.mention}\n**Updated By:** {mod_str}\n\n" + "\n".join(settings_diff),
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-roles", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        guild = after.guild
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return

        # 1. Member Role Changes
        added_roles = [r for r in after.roles if r not in before.roles]
        removed_roles = [r for r in before.roles if r not in after.roles]

        if added_roles or removed_roles:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.member_role_update, target_id=after.id)
            culprit = entry.user if entry else None

            # Check if dangerous roles were added to the member
            dangerous_added = [
                r for r in added_roles if (
                    r.permissions.administrator or 
                    r.permissions.manage_guild or 
                    r.permissions.manage_roles or 
                    r.permissions.ban_members or 
                    r.permissions.manage_channels
                )
            ]

            if dangerous_added and culprit and not self.is_whitelisted(guild, culprit, feature="dangerous_role_add"):
                # Revert unauthorized dangerous role assignments
                revert_roles = [r for r in dangerous_added if r < guild.me.top_role]
                if revert_roles:
                    try:
                        await after.remove_roles(*revert_roles, reason="Anti-Nuke: Unauthorized dangerous role assignment revoked.")
                    except Exception:
                        pass

                embed = discord.Embed(
                    title="👑 Unauthorized Dangerous Role Added",
                    description=f"**Target:** {after.mention} (`{after.id}`)\n**Role(s):** {', '.join([r.mention for r in dangerous_added])} (Revoked)\n**Assigned By:** {culprit.mention} (`{culprit.id}`)",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-roles", embed)

                cfg = self.get_security_config(gid)
                rule = cfg.get("instant", {}).get("dangerous_role_add", {})
                if rule.get("enabled", True):
                    tm = rule.get("timeout_mins", 10)
                    await self.execute_punishment(guild, culprit, rule.get("punishment", "strip_roles"), "Instant Punishment: Unauthorized dangerous role assignment.", log_channel="audit-antinuke", timeout_mins=tm, feature="dangerous_role_add")
                return

            # Standard Member Roles Log
            mod_str = culprit.mention if culprit else "Unknown / Integration"
            embed = discord.Embed(
                title="👤 Member Roles Updated",
                description=f"**Member:** {after.mention} (`{after.name}`)\n**Updated By:** {mod_str}",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow()
            )
            if added_roles:
                embed.add_field(name="➕ Roles Added", value=", ".join([r.mention for r in added_roles]), inline=False)
            if removed_roles:
                embed.add_field(name="➖ Roles Removed", value=", ".join([r.mention for r in removed_roles]), inline=False)
            await self.log_security_event(guild, "audit-roles", embed)

        # 2. Nickname Changes
        if before.nick != after.nick:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.member_update, target_id=after.id)
            culprit = entry.user if entry else after
            old_nick = before.nick or before.name
            new_nick = after.nick or after.name
            embed = discord.Embed(
                title="✏️ Member Nickname Changed",
                description=f"**Member:** {after.mention}\n**Old Nickname:** `{old_nick}`\n**New Nickname:** `{new_nick}`\n**Changed By:** {culprit.mention}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-members", embed)

        # 3. Timeout Applied or Cleared
        if before.timed_out_until != after.timed_out_until:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.member_update, target_id=after.id)
            culprit = entry.user if entry else None
            mod_str = culprit.mention if culprit else "Unknown / System"
            now = discord.utils.utcnow()
            if after.timed_out_until and after.timed_out_until > now:
                expires_ts = int(after.timed_out_until.timestamp())
                reason = entry.reason if entry and entry.reason else "No reason specified."
                embed = discord.Embed(
                    title="⏳ Member Timed Out",
                    description=f"**Member:** {after.mention} (`{after.name}`)\n**Timed Out By:** {mod_str}\n**Expires:** <t:{expires_ts}:R> (<t:{expires_ts}:F>)\n**Reason:** {reason}",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-timeouts", embed)
            elif before.timed_out_until and (not after.timed_out_until or after.timed_out_until <= now):
                embed = discord.Embed(
                    title="⌛ Member Timeout Cleared",
                    description=f"**Member:** {after.mention} (`{after.name}`)\n**Cleared By:** {mod_str}",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-timeouts", embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        gid = str(guild.id)
        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.ban, target_id=user.id)
        culprit = entry.user if entry else None
        reason = entry.reason if entry and entry.reason else "No reason specified."
        mod_str = culprit.mention if culprit else "Unknown / Integration"

        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"**User:** {user.mention} (`{user.name}` - `{user.id}`)\n**Banned By:** {mod_str}\n**Reason:** {reason}",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        if hasattr(user, 'display_avatar'):
            embed.set_thumbnail(url=user.display_avatar.url)
        await self.log_security_event(guild, "audit-banned", embed)

        if not db.antinuke_active.get(gid, True): return
        if not culprit: return
        if self.is_whitelisted(guild, culprit, feature="ban"): return
        should_punish = self.record_action_and_check(guild.id, culprit.id, 'ban')
        if should_punish:
            cfg = self.get_security_config(gid)
            rule = cfg.get("limits", {}).get("ban", {})
            punishment = rule.get("punishment", "ban")
            tm = rule.get("timeout_mins", 10)
            await self.execute_punishment(guild, culprit, punishment, "Anti-Nuke: Triggered mass-ban limit.", log_channel="audit-antinuke", timeout_mins=tm, feature="ban")

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        gid = str(guild.id)
        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.unban, target_id=user.id)
        culprit = entry.user if entry else None
        mod_str = culprit.mention if culprit else "Unknown / Integration"
        embed = discord.Embed(
            title="🔓 Member Unbanned",
            description=f"**User:** {user.mention} (`{user.name}` - `{user.id}`)\n**Unbanned By:** {mod_str}",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        if hasattr(user, 'display_avatar'):
            embed.set_thumbnail(url=user.display_avatar.url)
        await self.log_security_event(guild, "audit-banned", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        gid = str(guild.id)
        
        # Check if this removal was a kick
        entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.kick, target_id=member.id, max_age_seconds=10)
        culprit = entry.user if entry else None

        if culprit:
            reason = entry.reason if entry.reason else "No reason provided."
            embed = discord.Embed(
                title="👢 Member Kicked",
                description=f"**Member:** {member.mention} (`{member.name}` - `{member.id}`)\n**Kicked By:** {culprit.mention}\n**Reason:** {reason}",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await self.log_security_event(guild, "audit-timeouts", embed)

            if db.antinuke_active.get(gid, True) and not self.is_whitelisted(guild, culprit, feature="kick"):
                should_punish = self.record_action_and_check(guild.id, culprit.id, 'kick')
                if should_punish:
                    cfg = self.get_security_config(gid)
                    rule = cfg.get("limits", {}).get("kick", {})
                    punishment = rule.get("punishment", "kick")
                    tm = rule.get("timeout_mins", 10)
                    await self.execute_punishment(guild, culprit, punishment, "Anti-Nuke: Triggered mass-kick limit.", log_channel="audit-antinuke", timeout_mins=tm, feature="kick")
        else:
            # Voluntary leave
            joined_str = f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown"
            role_names = [r.name for r in member.roles if r.name != "@everyone"]
            roles_str = ", ".join(role_names[:10]) if role_names else "None"
            embed = discord.Embed(
                title="📤 Member Left Server",
                description=f"**Member:** {member.mention} (`{member.name}` - `{member.id}`)\n**Joined:** {joined_str}\n**Roles Held:** `{roles_str}`\n**Member Count:** **{guild.member_count}**",
                color=discord.Color.dark_grey(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await self.log_security_event(guild, "audit-members", embed)

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

        # 2. Standard Member Join Log to audit-members
        created_ts = int(member.created_at.timestamp())
        embed = discord.Embed(
            title="📥 Member Joined",
            description=f"**Member:** {member.mention} (`{member.name}` - `{member.id}`)\n**Account Created:** <t:{created_ts}:R> (<t:{created_ts}:D>)\n**Member Count:** **{guild.member_count}**",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await self.log_security_event(guild, "audit-members", embed)

        # 3. Anti-Raid Join Flood Protection
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

        # Check if author is Server Owner, Bot, or explicitly Whitelisted
        is_owner_or_bot = (author.id == guild.owner_id or author.id == self.bot.user.id)
        is_immune = is_owner_or_bot or self.is_whitelisted(guild, author)

        # 1. Detect Only: Anti Invite Link (Auto-Delete & Log)
        if cfg.get("detect", {}).get("invite_link", {}).get("enabled", True) and self.invite_regex.search(message.content):
            if not is_immune and not self.is_whitelisted(guild, author, feature="invite_link"):
                deleted = await self.safe_delete_violating_message(message, violation_label="Invite Link")
                try:
                    resp_tpl = db.custom_responses.get(gid, {}).get("security_invite_warn", "🔗 {member}, discord invite links are not allowed in this server.")
                    warn_text = resp_tpl.replace("{member}", author.mention)
                    if not deleted:
                        warn_text += " *(⚠️ Warning: Discord API rejected the deletion — check bot permissions)*"
                    warn_msg = await message.channel.send(warn_text)
                    await warn_msg.delete(delay=5)
                except Exception:
                    pass
                embed = discord.Embed(
                    title="🔗 Invite Link Removed" if deleted else "🔗 Invite Link Detected (Deletion Blocked)",
                    description=f"**User:** {author.mention}\n**Channel:** {message.channel.mention}\n**Content:** `{message.content[:200]}`",
                    color=discord.Color.orange() if deleted else discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-antispam", embed)
                return

        # 2. Detect Only: Anti GIF (Auto-Delete & Log)
        # Note: has_gif_content checks attachments, URL text, AND embeds (e.g. Tenor GIFs from Discord picker).
        # anti_gif_cfg.enabled must be True (default is False — admin must enable it in dashboard).
        anti_gif_cfg = cfg.get("detect", {}).get("anti_gif", {})
        if anti_gif_cfg.get("enabled", False) and self.has_gif_content(message):
            # Members who have Discord in-server embed/attach permissions, or are explicitly whitelisted/immune, can send GIFs!
            has_embed_perm = self.member_has_embed_permission(author, message.channel)
            can_send_gif = is_immune or self.is_whitelisted(guild, author, feature="anti_gif") or has_embed_perm
            if not can_send_gif:
                deleted = await self.safe_delete_violating_message(message, violation_label="GIF Content")
                try:
                    resp_tpl = db.custom_responses.get(gid, {}).get("security_gif_warn", "🎞️ {member}, GIFs are not allowed in this server.")
                    warn_text = resp_tpl.replace("{member}", author.mention)
                    if not deleted:
                        warn_text += " *(⚠️ Warning: Discord API rejected the deletion — check bot permissions)*"
                    warn_msg = await message.channel.send(warn_text)
                    await warn_msg.delete(delay=5)
                except Exception:
                    pass
                embed = discord.Embed(
                    title="🎞️ GIF Removed" if deleted else "🎞️ GIF Detected (Deletion Blocked)",
                    description=f"**User:** {author.mention}\n**Channel:** {message.channel.mention}\n**Content:** `{message.content[:200]}`",
                    color=discord.Color.orange() if deleted else discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                await self.log_security_event(guild, "audit-antispam", embed)
                return

        # 3. Detect Only: Anti Link (Auto-Delete & Log)
        anti_link_cfg = cfg.get("detect", {}).get("anti_link", {})
        if anti_link_cfg.get("enabled", True):
            all_links = self.link_regex.findall(message.content)
            if all_links:
                non_invite_links = [l for l in all_links if not self.invite_regex.search(l)]
                if non_invite_links:
                    can_send_all_links = is_immune or self.is_whitelisted(guild, author, feature="anti_link")
                    if not can_send_all_links:
                        is_gif_whitelisted = is_immune or self.is_whitelisted(guild, author, feature="anti_gif")
                        has_embed_perm = self.member_has_embed_permission(author, message.channel)
                        allow_gifs = anti_link_cfg.get("allow_gifs", True)

                        gif_links = [l for l in non_invite_links if self.is_gif_url(l)]
                        non_gif_links = [l for l in non_invite_links if not self.is_gif_url(l)]

                        # If Discord resolved a GIF embed/attachment and there is only 1 link, it's definitely the GIF
                        if self.has_gif_content(message) and len(non_invite_links) == 1 and not gif_links:
                            gif_links = non_invite_links
                            non_gif_links = []

                        # A member can send GIF links without being deleted by anti-link if:
                        # 1. They are explicitly GIF-whitelisted (or immune) — completely bypassing the allow_gifs toggle!
                        # 2. OR the member has in-server Discord embed/attach permissions enabled!
                        is_gif_permitted = is_gif_whitelisted or has_embed_perm or (allow_gifs and has_embed_perm)

                        if is_gif_permitted and (gif_links or self.has_gif_content(message)) and not non_gif_links:
                            pass  # GIF is authorized, do NOT delete as external link!
                        else:
                            deleted = await self.safe_delete_violating_message(message, violation_label="External Link")
                            try:
                                if not non_gif_links and gif_links:
                                    resp_tpl = "🎞️ {member}, GIFs and external media links are not allowed in this server."
                                else:
                                    resp_tpl = db.custom_responses.get(gid, {}).get("security_link_warn", "🔗 {member}, external links are not allowed in this server.")
                                warn_text = resp_tpl.replace("{member}", author.mention)
                                if not deleted:
                                    warn_text += " *(⚠️ Warning: Discord API rejected the deletion — check bot permissions)*"
                                warn_msg = await message.channel.send(warn_text)
                                await warn_msg.delete(delay=5)
                            except Exception:
                                pass
                            embed = discord.Embed(
                                title=("🔗 Link Removed" if non_gif_links else "🎞️ GIF Link Removed") if deleted else ("🔗 Link Detected (Deletion Blocked)" if non_gif_links else "🎞️ GIF Link Detected (Deletion Blocked)"),
                                description=f"**User:** {author.mention}\n**Channel:** {message.channel.mention}\n**Content:** `{message.content[:200]}`",
                                color=discord.Color.orange() if deleted else discord.Color.red(),
                                timestamp=discord.utils.utcnow()
                            )
                            await self.log_security_event(guild, "audit-antispam", embed)
                            return

        # Whitelist protects administrative commands & punishments
        if is_immune or self.is_whitelisted(guild, author, feature="antispam"):
            return

        # 4. Anti-Mention Limit
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
    async def on_message_edit(self, before, after):
        """Re-run security checks when a message is edited OR when Discord appends embed metadata.
        Also logs content edits to 'audit-edits'."""
        if not after.guild or after.author.bot:
            return

        # 1. Log message text edits to audit-edits
        if before.content != after.content and before.content:
            embed = discord.Embed(
                title="✏️ Message Edited",
                description=f"**Author:** {after.author.mention} (`{after.author.name}`)\n**Channel:** {after.channel.mention} | [Jump to Message]({after.jump_url})",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Before", value=before.content[:1024] or "*No text*", inline=False)
            embed.add_field(name="After", value=after.content[:1024] or "*No text*", inline=False)
            embed.set_footer(text=f"Author ID: {after.author.id} • Message ID: {after.id}")
            await self.log_security_event(after.guild, "audit-edits", embed)

        # 2. Re-run security checks (e.g. Tenor/Giphy GIF picker embed appended or links inserted)
        content_changed = before.content != after.content
        attachment_changed = len(before.attachments) != len(after.attachments)
        embed_added = len(after.embeds) > len(before.embeds)  # Discord appended a GIF embed
        if content_changed or attachment_changed or embed_added:
            await self.on_message(after)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Comprehensive Voice Channel audit logger: joins, leaves, moves, server mute/deafen, streaming, camera."""
        guild = member.guild
        if not guild: return
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return

        # 1. Joined VC
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(
                title="🔊 Voice Channel Joined",
                description=f"**Member:** {member.mention} (`{member.name}`)\n**Channel:** {after.channel.mention} (`{after.channel.name}`)",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await self.log_security_event(guild, "audit-voice", embed)

        # 2. Left VC
        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(
                title="🔇 Voice Channel Left",
                description=f"**Member:** {member.mention} (`{member.name}`)\n**Channel:** `#{before.channel.name}`",
                color=discord.Color.dark_red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await self.log_security_event(guild, "audit-voice", embed)

        # 3. Switched / Moved VC
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.member_move, max_age_seconds=5, wait_delay=0.5)
            mover = entry.user if entry else None
            moved_by_str = f"\n**Moved By:** {mover.mention}" if mover and mover.id != member.id else ""
            embed = discord.Embed(
                title="🔀 Voice Channel Switched",
                description=f"**Member:** {member.mention} (`{member.name}`)\n**From:** `#{before.channel.name}`\n**To:** {after.channel.mention} (`{after.channel.name}`){moved_by_str}",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await self.log_security_event(guild, "audit-voice", embed)

        # 4. Server Mute
        if before.mute != after.mute:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.member_update, target_id=member.id)
            culprit = entry.user if entry else None
            mod_str = culprit.mention if culprit else "Unknown / Unverified"
            chan_name = f" in {after.channel.mention}" if after.channel else ""
            embed = discord.Embed(
                title="🎙️ Member Server Muted" if after.mute else "🎙️ Member Server Unmuted",
                description=f"**Member:** {member.mention} (`{member.name}`){chan_name}\n**Action:** `{'Server Muted' if after.mute else 'Server Unmuted'}`\n**Moderator:** {mod_str}",
                color=discord.Color.red() if after.mute else discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-voice", embed)

        # 5. Server Deafen
        if before.deaf != after.deaf:
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.member_update, target_id=member.id)
            culprit = entry.user if entry else None
            mod_str = culprit.mention if culprit else "Unknown / Unverified"
            chan_name = f" in {after.channel.mention}" if after.channel else ""
            embed = discord.Embed(
                title="🎧 Member Server Deafened" if after.deaf else "🎧 Member Server Undeafened",
                description=f"**Member:** {member.mention} (`{member.name}`){chan_name}\n**Action:** `{'Server Deafened' if after.deaf else 'Server Undeafened'}`\n**Moderator:** {mod_str}",
                color=discord.Color.red() if after.deaf else discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-voice", embed)

        # 6. Screen Share / Stream
        if before.self_stream != after.self_stream:
            curr_ch = after.channel or before.channel
            embed = discord.Embed(
                title="📺 Screen Share Started" if after.self_stream else "📺 Screen Share Stopped",
                description=f"**Member:** {member.mention} (`{member.name}`)\n**Channel:** {curr_ch.mention if curr_ch else 'Voice'}",
                color=discord.Color.purple(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-voice", embed)

        # 7. Video Camera
        if before.self_video != after.self_video:
            curr_ch = after.channel or before.channel
            embed = discord.Embed(
                title="📷 Camera Turned On" if after.self_video else "📷 Camera Turned Off",
                description=f"**Member:** {member.mention} (`{member.name}`)\n**Channel:** {curr_ch.mention if curr_ch else 'Voice'}",
                color=discord.Color.teal(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-voice", embed)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        """Catch message updates (e.g. Discord resolving Tenor/Giphy GIF picker embeds)
        even if the original message was not in discord.py's internal cache."""
        if not payload.guild_id:
            return
        if payload.cached_message:
            return  # Handled by on_message_edit
        channel = self.bot.get_channel(payload.channel_id)
        if not channel or not hasattr(channel, "fetch_message"):
            return
        try:
            msg = await channel.fetch_message(payload.message_id)
            if msg and not msg.author.bot:
                await self.on_message(msg)
        except Exception:
            pass

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

        # Server Banner Change
        if before.banner != after.banner:
            mod_str = culprit.mention if culprit else "Unknown / Unverified"
            embed = discord.Embed(
                title="🖼️ Server Banner Modified",
                description=f"**Modified By:** {mod_str}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(after, "audit-server", embed)

        # Server Setting Changes (AFK, Verification, Notifications, System Channel)
        server_diff = []
        if before.afk_channel != after.afk_channel:
            old_afk = before.afk_channel.mention if before.afk_channel else "None"
            new_afk = after.afk_channel.mention if after.afk_channel else "None"
            server_diff.append(f"• **AFK Channel:** {old_afk} ➔ {new_afk}")
        if before.afk_timeout != after.afk_timeout:
            server_diff.append(f"• **AFK Timeout:** `{before.afk_timeout}s` ➔ `{after.afk_timeout}s`")
        if before.verification_level != after.verification_level:
            server_diff.append(f"• **Verification Level:** `{str(before.verification_level).title()}` ➔ `{str(after.verification_level).title()}`")
        if before.default_notifications != after.default_notifications:
            server_diff.append(f"• **Default Notifications:** `{str(before.default_notifications).title()}` ➔ `{str(after.default_notifications).title()}`")
        if before.system_channel != after.system_channel:
            old_sys = before.system_channel.mention if before.system_channel else "None"
            new_sys = after.system_channel.mention if after.system_channel else "None"
            server_diff.append(f"• **System Channel:** {old_sys} ➔ {new_sys}")
        if getattr(before, 'description', None) != getattr(after, 'description', None):
            server_diff.append("• **Server Description Updated**")

        if server_diff:
            mod_str = culprit.mention if culprit else "Unknown / Unverified"
            embed = discord.Embed(
                title="⚙️ Server Settings Modified",
                description=f"**Modified By:** {mod_str}\n\n" + "\n".join(server_diff),
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(after, "audit-server", embed)

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
            await self.log_security_event(guild, "audit-server", embed)
            if culprit:
                rule = cfg.get("instant", {}).get("emoji_delete", {})
                if rule.get("enabled", False):
                    tm = rule.get("timeout_mins", 10)
                    await self.execute_punishment(guild, culprit, rule.get("punishment", "kick"), "Instant Punishment: Emoji deletion violation.", log_channel="audit-antinuke", timeout_mins=tm, feature="emoji_delete")

        # 2. Emoji Create
        elif len(after) > len(before):
            created = [e for e in after if e.id not in [b.id for b in before]]
            c_names = ", ".join([f":{e.name}:" for e in created])
            entry = await self.get_recent_audit_entry(guild, discord.AuditLogAction.emoji_create)
            culprit = entry.user if entry else None
            c_str = culprit.mention if culprit else "Unknown / Unverified"
            embed = discord.Embed(
                title="✨ Emoji Created",
                description=f"**Emojis:** {c_names}\n**Created By:** {c_str}",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            await self.log_security_event(guild, "audit-server", embed)

        # 3. Emoji Rename
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
                await self.log_security_event(guild, "audit-server", embed)
                if culprit:
                    rule = cfg.get("instant", {}).get("emoji_rename", {})
                    if rule.get("enabled", False):
                        tm = rule.get("timeout_mins", 10)
                        await self.execute_punishment(guild, culprit, rule.get("punishment", "kick"), "Instant Punishment: Emoji rename violation.", log_channel="audit-antinuke", timeout_mins=tm, feature="emoji_rename")

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        guild = invite.guild
        if not guild: return
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return
        inviter = invite.inviter.mention if invite.inviter else "Unknown"
        max_uses_str = str(invite.max_uses) if invite.max_uses else "Unlimited"
        expires_str = f"<t:{int((discord.utils.utcnow() + datetime.timedelta(seconds=invite.max_age)).timestamp())}:R>" if invite.max_age else "Never"
        embed = discord.Embed(
            title="📨 Instant Invite Created",
            description=f"**Code:** `{invite.code}`\n**Channel:** {invite.channel.mention if invite.channel else 'Unknown'}\n**Created By:** {inviter}\n**Max Uses:** `{max_uses_str}`\n**Expires:** {expires_str}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        await self.log_security_event(guild, "audit-server", embed)

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
        await self.log_security_event(guild, "audit-server", embed)
        if culprit:
            cfg = self.get_security_config(gid)
            rule = cfg.get("instant", {}).get("invite_delete", {})
            if rule.get("enabled", False):
                tm = rule.get("timeout_mins", 10)
                await self.execute_punishment(guild, culprit, rule.get("punishment", "kick"), "Instant Punishment: Invite deletion violation.", log_channel="audit-antinuke", timeout_mins=tm, feature="invite_delete")

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        if not guild: return
        gid = str(guild.id)
        if not db.antinuke_active.get(gid, True): return
        entry = (
            await self.get_recent_audit_entry(guild, discord.AuditLogAction.webhook_create, target_id=channel.id) or
            await self.get_recent_audit_entry(guild, discord.AuditLogAction.webhook_update, target_id=channel.id) or
            await self.get_recent_audit_entry(guild, discord.AuditLogAction.webhook_delete, target_id=channel.id)
        )
        action_name = "Modified"
        if entry:
            if entry.action == discord.AuditLogAction.webhook_create: action_name = "Created"
            elif entry.action == discord.AuditLogAction.webhook_delete: action_name = "Deleted"
        mod_str = entry.user.mention if entry and entry.user else "Unknown / Integration"
        embed = discord.Embed(
            title=f"🪝 Webhook {action_name}",
            description=f"**Channel:** {channel.mention}\n**Action:** Webhook {action_name}\n**Updated By:** {mod_str}",
            color=discord.Color.dark_purple(),
            timestamp=discord.utils.utcnow()
        )
        await self.log_security_event(guild, "audit-server", embed)

async def setup(bot):
    await bot.add_cog(Security(bot))
