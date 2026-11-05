import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import random
import re
import uuid
from typing import Optional, List, Dict
from datetime import datetime, timezone
from database import db

# ─────────────────────────────────────────────────────────────
# Helper Utilities
# ─────────────────────────────────────────────────────────────

def parse_duration(duration_str: str) -> Optional[int]:
    """
    Parse a human duration string (e.g. '30s', '10m', '1h', '2d', '1w', '1h 30m') into total seconds.
    Returns total seconds as an integer, or None if invalid.
    """
    if not duration_str:
        return None
    raw = duration_str.strip().lower()
    
    # Check compound patterns like "1h 30m", "2d 4h"
    compound_pattern = r'(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks)'
    matches = re.findall(compound_pattern, raw)
    if not matches:
        return None

    multipliers = {
        's': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
        'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
        'h': 3600, 'hr': 3600, 'hrs': 3600, 'hour': 3600, 'hours': 3600,
        'd': 86400, 'day': 86400, 'days': 86400,
        'w': 604800, 'wk': 604800, 'wks': 604800, 'week': 604800, 'weeks': 604800
    }

    total_seconds = 0
    for value_str, unit in matches:
        try:
            total_seconds += int(value_str) * multipliers.get(unit, 1)
        except ValueError:
            return None

    return total_seconds if total_seconds > 0 else None


def format_duration(seconds: int) -> str:
    """Formats seconds into a readable string (e.g. '1 day, 2 hours')."""
    if seconds <= 0:
        return "0s"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 and not parts:
        parts.append(f"{secs}s")
    return " ".join(parts) if parts else "0s"


def get_giveaway_config(guild_id: int) -> dict:
    """Fetches giveaway configuration for a guild."""
    gid_str = str(guild_id)
    cfg = db.giveaways_config.get(gid_str, {})
    if not isinstance(cfg, dict):
        cfg = {}
        db.giveaways_config[gid_str] = cfg
    return cfg


def is_giveaway_configured(guild_id: int) -> bool:
    """Checks whether giveaway channels (broadcast, approvals, logs) are set up."""
    cfg = get_giveaway_config(guild_id)
    return bool(cfg.get("giveaway_channel") and cfg.get("approval_channel") and cfg.get("log_channel"))


# ─────────────────────────────────────────────────────────────
# Persistent Giveaway Views
# ─────────────────────────────────────────────────────────────

class GiveawayEnterView(discord.ui.View):
    """
    Persistent button view for giveaway messages.
    Allows members to enter or leave the giveaway with real-time counter updates.
    """
    def __init__(self, giveaway_key: str, entry_count: int = 0, disabled: bool = False):
        super().__init__(timeout=None)
        self.giveaway_key = giveaway_key
        button_label = f"🎁 Enter Giveaway ({entry_count})" if not disabled else f"🔒 Giveaway Ended ({entry_count})"
        self.enter_btn = discord.ui.Button(
            style=discord.ButtonStyle.primary if not disabled else discord.ButtonStyle.secondary,
            label=button_label,
            custom_id=f"gw_enter:{giveaway_key}",
            disabled=disabled
        )
        self.enter_btn.callback = self.enter_callback
        self.add_item(self.enter_btn)

    async def enter_callback(self, interaction: discord.Interaction):
        gw = db.giveaways.get(self.giveaway_key)
        if not gw or gw.get("status") != "active":
            await interaction.response.send_message("⚠️ This giveaway has already ended or is no longer active.", ephemeral=True)
            self.enter_btn.disabled = True
            self.enter_btn.label = f"🔒 Giveaway Ended ({len(gw.get('entries', [])) if gw else 0})"
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            return

        entries = gw.setdefault("entries", [])
        uid = interaction.user.id
        prize = gw.get("prize", "the prize")

        if uid in entries:
            entries.remove(uid)
            action_msg = f"👋 You left the giveaway for **{prize}**."
        else:
            entries.append(uid)
            action_msg = f"🎉 You have entered the giveaway for **{prize}**! Good luck! 🍀"

        db.save_data()

        # Update button label and embed entry count
        count = len(entries)
        self.enter_btn.label = f"🎁 Enter Giveaway ({count})"

        try:
            embed = interaction.message.embeds[0]
            for i, field in enumerate(embed.fields):
                if "entries" in field.name.lower():
                    embed.set_field_at(i, name=field.name, value=f"**{count}**", inline=True)
                    break
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

        await interaction.response.send_message(action_msg, ephemeral=True)


class GiveawayApprovalView(discord.ui.View):
    """
    Approval view sent to the staff `#giveaway-approvals` channel
    when regular members submit a giveaway proposal.
    """
    def __init__(self, request_id: str):
        super().__init__(timeout=None)
        self.request_id = request_id

        self.approve_btn = discord.ui.Button(
            style=discord.ButtonStyle.success,
            label="Approve & Publish",
            emoji="✅",
            custom_id=f"gw_app:{request_id}"
        )
        self.approve_btn.callback = self.approve_callback
        self.add_item(self.approve_btn)

        self.reject_btn = discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label="Reject",
            emoji="❌",
            custom_id=f"gw_rej:{request_id}"
        )
        self.reject_btn.callback = self.reject_callback
        self.add_item(self.reject_btn)

    async def approve_callback(self, interaction: discord.Interaction):
        # Only administrators or staff with Manage Server can approve
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🛡️ Only server administrators or staff can approve giveaways.", ephemeral=True)
            return

        req = db.giveaways.get(f"req_{self.request_id}")
        if not req or req.get("status") != "pending":
            await interaction.response.send_message("⚠️ This giveaway request has already been processed.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        cfg = get_giveaway_config(guild.id)
        gw_channel_id = cfg.get("giveaway_channel")
        gw_channel = guild.get_channel(gw_channel_id) if gw_channel_id else None

        if not gw_channel:
            await interaction.followup.send("❌ Configured giveaway channel not found. Please re-run `/gsetup`.", ephemeral=True)
            return

        # Launch the giveaway
        now = time.time()
        duration_sec = req["duration_seconds"]
        end_time = now + duration_sec
        sponsor_id = req["sponsor_id"]
        prize = req["prize"]
        winners_count = req["winners_count"]
        description = req.get("description", "")

        end_timestamp = int(end_time)
        embed = discord.Embed(
            title=f"🎁 GIVEAWAY: {prize} 🎁",
            description=(
                f"{description}\n\n" if description else ""
            ) + (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "> React or click below to enter! Winners will be randomly selected.\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(88, 101, 242), # Modern Discord Blurple
            timestamp=datetime.fromtimestamp(end_time, timezone.utc)
        )
        embed.add_field(name="👑 Sponsored by", value=f"<@{sponsor_id}>", inline=True)
        embed.add_field(name="🏆 Winners", value=f"**{winners_count}**", inline=True)
        embed.add_field(name="🎟️ Entries", value="**0**", inline=True)
        embed.add_field(name="⏳ Ends", value=f"<t:{end_timestamp}:R> (<t:{end_timestamp}:f>)", inline=False)
        embed.set_footer(text=f"Giveaway ID: {self.request_id} • Ends at", icon_url=guild.icon.url if guild.icon else None)

        gw_key = f"{guild.id}_{self.request_id}"
        view = GiveawayEnterView(giveaway_key=gw_key, entry_count=0)

        gw_msg = await gw_channel.send(content="🎉 **NEW GIVEAWAY!** 🎉", embed=embed, view=view)

        # Re-key with the real message id
        real_key = f"{guild.id}_{gw_msg.id}"
        gw_data = {
            "message_id": gw_msg.id,
            "channel_id": gw_channel.id,
            "guild_id": guild.id,
            "prize": prize,
            "host_id": interaction.user.id,
            "sponsor_id": sponsor_id,
            "winners_count": winners_count,
            "created_at": now,
            "end_time": end_time,
            "status": "active",
            "entries": [],
            "winners": [],
            "description": description
        }
        db.giveaways[real_key] = gw_data
        req["status"] = "approved"
        req["approved_by"] = interaction.user.id
        req["giveaway_message_id"] = gw_msg.id
        db.save_data()

        # Update original approval message in #giveaway-approvals
        for item in self.children:
            item.disabled = True
        try:
            app_embed = interaction.message.embeds[0]
            app_embed.color = discord.Color.green()
            app_embed.add_field(name="Status", value=f"✅ Approved by {interaction.user.mention}\nPublished in {gw_channel.mention}", inline=False)
            await interaction.message.edit(embed=app_embed, view=self)
        except Exception:
            pass

        # Notify sponsor in DM
        try:
            sponsor_member = guild.get_member(sponsor_id) or await guild.fetch_member(sponsor_id)
            if sponsor_member:
                dm_embed = discord.Embed(
                    title="🎉 Giveaway Approved & Published!",
                    description=f"Your giveaway request for **{prize}** has been approved by staff and is now live in {gw_channel.mention}!",
                    color=discord.Color.green()
                )
                await sponsor_member.send(embed=dm_embed)
        except Exception:
            pass

        # Log to #giveaway-logs
        log_ch_id = cfg.get("log_channel")
        log_channel = guild.get_channel(log_ch_id) if log_ch_id else None
        if log_channel:
            log_embed = discord.Embed(
                title="📜 Giveaway Approved & Launched",
                description=f"**Prize:** {prize}\n**Sponsor:** <@{sponsor_id}>\n**Approved By:** {interaction.user.mention}\n**Channel:** {gw_channel.mention}\n**Duration:** {format_duration(duration_sec)}",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            await log_channel.send(embed=log_embed)

        await interaction.followup.send(f"✅ Successfully approved and published the giveaway in {gw_channel.mention}!", ephemeral=True)

    async def reject_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🛡️ Only server administrators or staff can reject giveaways.", ephemeral=True)
            return

        req = db.giveaways.get(f"req_{self.request_id}")
        if not req or req.get("status") != "pending":
            await interaction.response.send_message("⚠️ This giveaway request has already been processed.", ephemeral=True)
            return

        req["status"] = "rejected"
        req["rejected_by"] = interaction.user.id
        db.save_data()

        for item in self.children:
            item.disabled = True

        try:
            app_embed = interaction.message.embeds[0]
            app_embed.color = discord.Color.red()
            app_embed.add_field(name="Status", value=f"❌ Rejected by {interaction.user.mention}", inline=False)
            await interaction.message.edit(embed=app_embed, view=self)
        except Exception:
            pass

        # Notify sponsor in DM
        try:
            sponsor_id = req["sponsor_id"]
            sponsor_member = interaction.guild.get_member(sponsor_id) or await interaction.guild.fetch_member(sponsor_id)
            if sponsor_member:
                dm_embed = discord.Embed(
                    title="❌ Giveaway Request Declined",
                    description=f"Your giveaway request for **{req['prize']}** was declined by the staff team in **{interaction.guild.name}**.",
                    color=discord.Color.red()
                )
                await sponsor_member.send(embed=dm_embed)
        except Exception:
            pass

        await interaction.response.send_message(f"❌ Giveaway request for **{req['prize']}** was rejected.", ephemeral=True)


# ─────────────────────────────────────────────────────────────
# Setup Wizard Components
# ─────────────────────────────────────────────────────────────

class SetupCategorySelect(discord.ui.Select):
    """Select menu for choosing the Discord category where giveaway channels should live."""
    def __init__(self, guild: discord.Guild):
        options = []
        # List up to 22 existing categories
        for cat in guild.categories[:22]:
            options.append(discord.SelectOption(
                label=cat.name[:100],
                value=str(cat.id),
                description=f"Channels: {len(cat.channels)}",
                emoji="📁"
            ))
        # Special option: Auto-create a brand new category
        options.append(discord.SelectOption(
            label="Create New 'GIVEAWAYS' Category",
            value="create_new",
            description="Friday will automatically create a dedicated category",
            emoji="🪄"
        ))
        # Special option: Top-level (no category)
        options.append(discord.SelectOption(
            label="No Category (Top Level)",
            value="no_category",
            description="Create channels without any parent category",
            emoji="🌐"
        ))
        super().__init__(
            placeholder="Select a category for giveaway channels...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        # Acknowledge immediately to prevent any Discord interaction timeout
        await interaction.response.defer()

        selected_val = self.values[0]
        self.view.selected_category_id = selected_val
        category_name = "None"
        if selected_val == "create_new":
            category_name = "New '🎉 GIVEAWAYS' Category"
        elif selected_val == "no_category":
            category_name = "Top-level (No Category)"
        else:
            cat = interaction.guild.get_channel(int(selected_val))
            if cat:
                category_name = cat.name

        embed = discord.Embed(
            title="◈ Friday Giveaway Engine • Channel Setup ◈",
            description=(
                "```ansi\n"
                "\u001b[1;36m[ STEP 2: CHANNEL PROVISIONING ]\u001b[0m\n"
                "```\n"
                f"**Target Category:** `{category_name}`\n\n"
                "> Choose an automated or manual provisioning path below:\n\n"
                "**Option A — Automated Provisioning (Recommended):**\n"
                "```\n"
                "📢 #giveaways          -> Public (view & enter only)\n"
                "🛡️ #giveaway-approvals -> Private Staff Queue (members submit)\n"
                "📜 #giveaway-logs      -> Private Audit Log (draws & rerolls)\n"
                "```\n"
                "**Option B — Manual Routing:**\n"
                "> Assign your server's pre-existing channels one by one.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(99, 102, 241)
        )
        self.view.clear_items()
        self.view.add_item(AutoCreateChannelsButton())
        self.view.add_item(ManualChannelsButton())
        await interaction.edit_original_response(embed=embed, view=self.view)


class AutoCreateChannelsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.success,
            label="Auto-Create All 3 Channels",
            emoji="🪄"
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != guild.owner_id:
            await interaction.response.send_message("🛡️ Only server administrators can configure channels.", ephemeral=True)
            return

        await interaction.response.defer()

        # 1. Resolve or create Category
        cat_id_val = getattr(self.view, "selected_category_id", "no_category")
        category = None
        if cat_id_val == "create_new":
            try:
                category = await guild.create_category(name="🎉 GIVEAWAYS", reason="Friday Giveaway Setup")
            except Exception as e:
                await interaction.followup.send(f"⚠️ Failed to create category: {e}", ephemeral=True)
        elif cat_id_val != "no_category":
            try:
                category = guild.get_channel(int(cat_id_val))
            except Exception:
                pass

        # 2. Permissions Setup
        everyone_role = guild.default_role
        bot_member = guild.me

        # Public Giveaway Channel Overwrites:
        # Everyone can view and read history, but CANNOT send messages. Bot & Admins have full access.
        public_overwrites = {
            everyone_role: discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                read_message_history=True,
                send_messages=False,
                add_reactions=False
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                manage_messages=True
            )
        }

        # Private Staff Overwrites (#giveaway-approvals and #giveaway-logs):
        # Strictly deny @everyone view_channel!
        private_overwrites = {
            everyone_role: discord.PermissionOverwrite(view_channel=False),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                embed_links=True,
                manage_messages=True
            )
        }

        created_channels = {}
        try:
            # Channel 1: #giveaways
            gw_ch = await guild.create_text_channel(
                name="giveaways",
                category=category,
                overwrites=public_overwrites,
                topic="Official server giveaways hosted by Friday! 🎁",
                reason="Friday Giveaway Setup"
            )
            created_channels["giveaway_channel"] = gw_ch.id

            # Channel 2: #giveaway-approvals (Private)
            app_ch = await guild.create_text_channel(
                name="giveaway-approvals",
                category=category,
                overwrites=private_overwrites,
                topic="Private staff approval queue for member-submitted giveaways 🛡️",
                reason="Friday Giveaway Setup"
            )
            created_channels["approval_channel"] = app_ch.id

            # Channel 3: #giveaway-logs (Private)
            log_ch = await guild.create_text_channel(
                name="giveaway-logs",
                category=category,
                overwrites=private_overwrites,
                topic="Audit log of giveaway winners, rerolls, and endings 📜",
                reason="Friday Giveaway Setup"
            )
            created_channels["log_channel"] = log_ch.id

        except discord.Forbidden:
            await interaction.followup.send("❌ Friday lacks the `Manage Channels` permission to create channels automatically! Please grant `Manage Channels` or assign channels manually.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Error creating channels: {e}", ephemeral=True)
            return

        # Save config
        cfg = get_giveaway_config(guild.id)
        cfg["giveaway_channel"] = created_channels["giveaway_channel"]
        cfg["approval_channel"] = created_channels["approval_channel"]
        cfg["log_channel"] = created_channels["log_channel"]
        db.giveaways_config[str(guild.id)] = cfg
        db.save_data()

        # Send structured success embed
        embed = discord.Embed(
            title="🎉 Giveaway Architecture Deployed Successfully!",
            description=(
                "```ansi\n"
                "\u001b[1;32m[ SETUP COMPLETE • READY FOR BROADCAST ]\u001b[0m\n"
                "```\n"
                "> All necessary channels have been provisioned and configured with strict permissions:\n\n"
                f"• 📢 **Broadcast Channel:** <#{created_channels['giveaway_channel']}>\n"
                f"• 🛡️ **Staff Approvals:** <#{created_channels['approval_channel']}> *(Strictly Private)*\n"
                f"• 📜 **Audit Logs:** <#{created_channels['log_channel']}> *(Strictly Private)*\n\n"
                "```\n"
                "• Staff Command:      /gcreate or /gstart\n"
                "• Member Submissions: Sent to #giveaway-approvals\n"
                "• Entries:            Real-time interactive button\n"
                "```\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(16, 185, 129),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Friday Giveaway Engine • Setup Complete")
        await interaction.edit_original_response(embed=embed, view=None)


class ManualChannelsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Select Existing Channels",
            emoji="⚙️"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = discord.Embed(
            title="◈ Friday Giveaway Engine • Manual Routing ◈",
            description=(
                "```ansi\n"
                "\u001b[1;34m[ STEP 1 OF 3: BROADCAST CHANNEL ]\u001b[0m\n"
                "```\n"
                "> Select which channel will serve as your **Public Giveaway Broadcast Channel**:\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.blue()
        )
        self.view.clear_items()
        self.view.add_item(ManualChannelSelect(role_type="giveaway_channel"))
        await interaction.edit_original_response(embed=embed, view=self.view)


class ManualChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, role_type: str):
        self.role_type = role_type
        placeholders = {
            "giveaway_channel": "Select Public Giveaway Broadcast Channel...",
            "approval_channel": "Select Private Staff Approvals Channel...",
            "log_channel": "Select Private Giveaway Logs Channel..."
        }
        super().__init__(
            placeholder=placeholders.get(role_type, "Select channel..."),
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        ch_id = int(self.values[0].id)
        cfg = get_giveaway_config(interaction.guild.id)
        cfg[self.role_type] = ch_id
        db.giveaways_config[str(interaction.guild.id)] = cfg
        db.save_data()

        if self.role_type == "giveaway_channel":
            embed = discord.Embed(
                title="◈ Friday Giveaway Engine • Manual Routing ◈",
                description=(
                    "```ansi\n"
                    "\u001b[1;34m[ STEP 2 OF 3: STAFF APPROVALS CHANNEL ]\u001b[0m\n"
                    "```\n"
                    f"✅ **Broadcast Channel:** <#{ch_id}>\n\n"
                    "> Select your **Staff Approvals Channel** (private channel for review queue):\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=discord.Color.blue()
            )
            self.view.clear_items()
            self.view.add_item(ManualChannelSelect(role_type="approval_channel"))
            await interaction.edit_original_response(embed=embed, view=self.view)
        elif self.role_type == "approval_channel":
            embed = discord.Embed(
                title="◈ Friday Giveaway Engine • Manual Routing ◈",
                description=(
                    "```ansi\n"
                    "\u001b[1;34m[ STEP 3 OF 3: AUDIT LOGS CHANNEL ]\u001b[0m\n"
                    "```\n"
                    f"✅ **Staff Approvals Channel:** <#{ch_id}>\n\n"
                    "> Select your **Giveaway Logs Channel** (records winner draws & rerolls):\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=discord.Color.blue()
            )
            self.view.clear_items()
            self.view.add_item(ManualChannelSelect(role_type="log_channel"))
            await interaction.edit_original_response(embed=embed, view=self.view)
        else:
            embed = discord.Embed(
                title="🎉 Giveaway Channels Successfully Assigned!",
                description=(
                    "```ansi\n"
                    "\u001b[1;32m[ CHANNELS ROUTED SUCCESSFULLY ]\u001b[0m\n"
                    "```\n"
                    f"• 📢 **Public Broadcast:** <#{cfg.get('giveaway_channel')}>\n"
                    f"• 🛡️ **Staff Approvals:** <#{cfg.get('approval_channel')}>\n"
                    f"• 📜 **Audit Logs:** <#{cfg.get('log_channel')}>\n\n"
                    "> You are now ready to launch giveaways with `/gcreate` or `/gstart`!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=discord.Color.green()
            )
            await interaction.edit_original_response(embed=embed, view=None)


class SetupWizardView(discord.ui.View):
    """Overall container view for the `/gsetup` configuration wizard."""
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.selected_category_id = None
        self.add_item(SetupCategorySelect(guild))


class LaunchSetupButtonView(discord.ui.View):
    """Button attached to first-time setup warnings that launches the wizard."""
    def __init__(self):
        super().__init__(timeout=None)
        btn = discord.ui.Button(
            style=discord.ButtonStyle.primary,
            label="Launch Setup Wizard",
            emoji="⚙️",
            custom_id="gsetup_launch_btn"
        )
        btn.callback = self.launch_callback
        self.add_item(btn)

    async def launch_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🛡️ Only server administrators can configure the giveaway system.", ephemeral=True)
            return

        embed = discord.Embed(
            title="◈ Friday Giveaway Engine • Setup Wizard ◈",
            description=(
                "```ansi\n"
                "\u001b[1;35m[ GIVEAWAY ARCHITECTURE SETUP ]\u001b[0m\n"
                "```\n"
                "> Welcome to the **Friday Giveaway Setup Wizard**! 🎉\n\n"
                "**Step 1: Select Channel Category**\n"
                "```\n"
                "📁 Choose an existing server category from the dropdown below,\n"
                "   or select 'Create New GIVEAWAYS Category'.\n"
                "```\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(99, 102, 241)
        )
        view = SetupWizardView(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ─────────────────────────────────────────────────────────────
# Cog: Giveaways
# ─────────────────────────────────────────────────────────────

class Giveaways(commands.Cog):
    """Full-featured Discord Giveaway System with approval queues, random winner RNG, and persistent views."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.giveaway_checker.start()

    def cog_unload(self):
        self.giveaway_checker.cancel()

    async def cog_load(self):
        """Restore persistent views for active giveaways and pending requests across restarts."""
        try:
            # Register persistent launch button
            self.bot.add_view(LaunchSetupButtonView())

            # Register entry buttons for active giveaways
            giveaways_dict = getattr(db, "giveaways", {})
            for key, data in list(giveaways_dict.items()):
                if isinstance(data, dict):
                    if data.get("status") == "active":
                        entries = data.get("entries", [])
                        self.bot.add_view(GiveawayEnterView(giveaway_key=key, entry_count=len(entries)))
                    elif data.get("status") == "pending" and key.startswith("req_"):
                        req_id = key.replace("req_", "")
                        self.bot.add_view(GiveawayApprovalView(request_id=req_id))
        except Exception as e:
            print(f"[Giveaways] Error restoring persistent views: {e}")

    # ─────────────────────────────────────────────────────────────
    # Background Worker: Check Expired Giveaways
    # ─────────────────────────────────────────────────────────────
    @tasks.loop(seconds=10)
    async def giveaway_checker(self):
        """Monitors active giveaways every 10 seconds and automatically draws winners upon expiration."""
        now = time.time()
        giveaways_dict = getattr(db, "giveaways", {})

        for key, gw in list(giveaways_dict.items()):
            if not isinstance(gw, dict) or gw.get("status") != "active":
                continue

            end_time = gw.get("end_time", 0)
            if now < end_time:
                continue

            # Giveaway has expired: draw winners!
            await self.conclude_giveaway(key, gw)

    async def conclude_giveaway(self, key: str, gw: dict):
        """Concludes an active giveaway, picks random winners, edits the card, and logs the result."""
        gw["status"] = "ended"
        guild_id = gw.get("guild_id")
        channel_id = gw.get("channel_id")
        message_id = gw.get("message_id")
        prize = gw.get("prize", "Unknown Prize")
        host_id = gw.get("host_id")
        sponsor_id = gw.get("sponsor_id", host_id)
        winners_count = gw.get("winners_count", 1)
        entries = gw.get("entries", [])

        # Pick random winners without duplicates
        if entries:
            chosen = random.sample(entries, k=min(len(entries), winners_count))
        else:
            chosen = []

        gw["winners"] = chosen
        gw["ended_at"] = time.time()
        db.save_data()

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            return

        # Fetch original message and update card
        try:
            msg = await channel.fetch_message(message_id)
            if msg and msg.embeds:
                old_embed = msg.embeds[0]
                winners_text = ", ".join(f"<@{w}>" for w in chosen) if chosen else "No valid entries received."

                ended_embed = discord.Embed(
                    title=f"🎉 GIVEAWAY ENDED: {prize} 🎉",
                    description=old_embed.description,
                    color=discord.Color.from_rgb(47, 49, 54), # Sleek dark
                    timestamp=datetime.now(timezone.utc)
                )
                ended_embed.add_field(name="Winners", value=winners_text, inline=False)
                ended_embed.add_field(name="Hosted / Sponsored by", value=f"<@{sponsor_id}>", inline=True)
                ended_embed.add_field(name="Total Entries", value=f"**{len(entries)}**", inline=True)
                ended_embed.set_footer(text="Giveaway Ended • Friday Engine", icon_url=guild.icon.url if guild.icon else None)

                disabled_view = GiveawayEnterView(giveaway_key=key, entry_count=len(entries), disabled=True)
                await msg.edit(embed=ended_embed, view=disabled_view)
        except Exception as e:
            print(f"[Giveaways] Failed to edit ended message {message_id}: {e}")

        # Send public winner announcement in the giveaway channel
        try:
            if chosen:
                mentions_str = " ".join(f"<@{w}>" for w in chosen)
                announcement = (
                    f"🎉 **GIVEAWAY CONCLUDED!** 🎉\n\n"
                    f"Congratulations {mentions_str}! You won **{prize}**! 🎁\n"
                    f"Hosted by: <@{sponsor_id}>\n"
                    f"Message link: https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
                )
                await channel.send(announcement)
            else:
                await channel.send(f"⚠️ The giveaway for **{prize}** has ended with no entries. No winners were selected.")
        except Exception as e:
            print(f"[Giveaways] Failed to send winner announcement: {e}")

        # Log conclusion to #giveaway-logs
        cfg = get_giveaway_config(guild_id)
        log_ch_id = cfg.get("log_channel")
        log_channel = guild.get_channel(log_ch_id) if log_ch_id else None
        if log_channel:
            winners_str = ", ".join(f"<@{w}>" for w in chosen) if chosen else "None"
            log_embed = discord.Embed(
                title="📜 Giveaway Concluded",
                description=(
                    f"**Prize:** {prize}\n"
                    f"**Winners ({len(chosen)}):** {winners_str}\n"
                    f"**Total Entries:** {len(entries)}\n"
                    f"**Channel:** <#{channel_id}>\n"
                    f"**Sponsored by:** <@{sponsor_id}>"
                ),
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            try:
                await log_channel.send(embed=log_embed)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────
    # Slash Commands
    # ─────────────────────────────────────────────────────────────

    @app_commands.command(name="gsetup", description="Configure Friday Giveaway channels (Category, Broadcast, Approvals, Logs)")
    @app_commands.default_permissions(manage_guild=True)
    async def gsetup(self, interaction: discord.Interaction):
        """Interactive setup wizard for giveaway channels with category selection and auto-creation."""
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🛡️ Only server administrators can configure the giveaway system.", ephemeral=True)
            return

        embed = discord.Embed(
            title="◈ Friday Giveaway Engine • Setup Wizard ◈",
            description=(
                "```ansi\n"
                "\u001b[1;35m[ GIVEAWAY ARCHITECTURE SETUP ]\u001b[0m\n"
                "```\n"
                "> Welcome to the **Friday Giveaway Setup Wizard**! 🎉\n\n"
                "**Step 1: Select Channel Category**\n"
                "```\n"
                "📁 Choose an existing server category from the dropdown below,\n"
                "   or select 'Create New GIVEAWAYS Category'.\n"
                "```\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(99, 102, 241)
        )
        view = SetupWizardView(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="gcreate", description="Create a new giveaway (Instant for Staff, Approval Queue for Members)")
    @app_commands.describe(
        prize="The item, role, or gift to give away",
        duration="Duration of the giveaway (e.g. 10m, 1h, 2d, 1w)",
        winners="Number of winners to pick (default: 1)",
        description="Optional detailed description or rules",
        channel="Optional channel to post in (defaults to configured giveaway channel)"
    )
    async def gcreate(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: Optional[int] = 1,
        description: Optional[str] = None,
        channel: Optional[discord.TextChannel] = None
    ):
        """Creates a giveaway. Admins launch instantly; regular members submit for staff approval."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command can only be used inside a server.", ephemeral=True)
            return

        # ── 1. First-Time Setup Guard ──
        if not is_giveaway_configured(guild.id):
            is_admin = interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator or interaction.user.id == guild.owner_id
            if is_admin:
                embed = discord.Embed(
                    title="⚠️ Giveaway System Not Configured Yet!",
                    description=(
                        "Before launching giveaways, Friday needs to know where to:\n"
                        "1. 📢 **Broadcast** public giveaways\n"
                        "2. 🛡️ **Approve** member-submitted giveaways\n"
                        "3. 📜 **Log** winner draws and rerolls\n\n"
                        "Please click the button below or run `/gsetup` to start the quick interactive setup wizard!"
                    ),
                    color=discord.Color.gold()
                )
                await interaction.response.send_message(embed=embed, view=LaunchSetupButtonView(), ephemeral=True)
            else:
                await interaction.response.send_message(
                    "⚠️ The giveaway system has not been configured by server administrators yet. Please ask a server admin to run `/gsetup`!",
                    ephemeral=True
                )
            return

        # ── 2. Validate Duration & Winners ──
        duration_sec = parse_duration(duration)
        if not duration_sec or duration_sec < 10:
            await interaction.response.send_message(
                "❌ Invalid duration format! Please use formats like `10m`, `1h`, `2d`, `1w`, or `1h 30m` (minimum 10 seconds).",
                ephemeral=True
            )
            return

        winners_count = max(1, min(winners or 1, 25))
        cfg = get_giveaway_config(guild.id)
        target_channel = channel or guild.get_channel(cfg.get("giveaway_channel"))

        if not target_channel:
            await interaction.response.send_message("❌ Giveaway broadcast channel could not be found. Please check `/gsetup`.", ephemeral=True)
            return

        is_admin_or_owner = (
            interaction.user.guild_permissions.manage_guild or
            interaction.user.guild_permissions.administrator or
            interaction.user.id == guild.owner_id
        )

        # ── 3. Branch: Regular Member Submission (Approval Queue) ──
        if not is_admin_or_owner:
            app_ch_id = cfg.get("approval_channel")
            app_ch = guild.get_channel(app_ch_id) if app_ch_id else None

            if not app_ch:
                await interaction.response.send_message(
                    "❌ Staff approval channel is not configured. Please notify a server administrator.",
                    ephemeral=True
                )
                return

            request_id = str(uuid.uuid4())[:8]
            req_data = {
                "request_id": request_id,
                "sponsor_id": interaction.user.id,
                "guild_id": guild.id,
                "prize": prize,
                "duration_seconds": duration_sec,
                "duration_str": duration,
                "winners_count": winners_count,
                "description": description or "",
                "status": "pending",
                "submitted_at": time.time()
            }
            db.giveaways[f"req_{request_id}"] = req_data
            db.save_data()

            # Post approval card in #giveaway-approvals
            app_embed = discord.Embed(
                title="📝 New Member Giveaway Request",
                description=(
                    f"A member has requested to host a giveaway!\n\n"
                    f"**Prize:** {prize}\n"
                    f"**Sponsor:** {interaction.user.mention} (`{interaction.user.name}`)\n"
                    f"**Duration:** `{format_duration(duration_sec)}`\n"
                    f"**Winners:** `{winners_count}`\n"
                    f"**Description:** {description or '*None provided*'}"
                ),
                color=discord.Color.from_rgb(245, 158, 11), # Amber
                timestamp=datetime.now(timezone.utc)
            )
            app_embed.set_footer(text=f"Request ID: {request_id}")
            view = GiveawayApprovalView(request_id=request_id)
            await app_ch.send(embed=app_embed, view=view)

            await interaction.response.send_message(
                f"✅ Your giveaway request for **{prize}** has been submitted for staff approval in {app_ch.mention}! You'll be notified once reviewed.",
                ephemeral=True
            )
            return

        # ── 4. Branch: Administrator Direct Launch ──
        now = time.time()
        end_time = now + duration_sec
        end_timestamp = int(end_time)

        embed = discord.Embed(
            title=f"🎁 GIVEAWAY: {prize} 🎁",
            description=(
                f"{description}\n\n" if description else ""
            ) + (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "> React or click below to enter! Winners will be randomly selected.\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.from_rgb(88, 101, 242), # Blurple
            timestamp=datetime.fromtimestamp(end_time, timezone.utc)
        )
        embed.add_field(name="👑 Hosted by", value=interaction.user.mention, inline=True)
        embed.add_field(name="🏆 Winners", value=f"**{winners_count}**", inline=True)
        embed.add_field(name="🎟️ Entries", value="**0**", inline=True)
        embed.add_field(name="⏳ Ends", value=f"<t:{end_timestamp}:R> (<t:{end_timestamp}:f>)", inline=False)
        embed.set_footer(text="Friday Giveaway Engine • Ends at", icon_url=guild.icon.url if guild.icon else None)

        # Temporary key before message is sent
        temp_id = str(uuid.uuid4())[:8]
        temp_key = f"{guild.id}_{temp_id}"
        view = GiveawayEnterView(giveaway_key=temp_key, entry_count=0)

        gw_msg = await target_channel.send(content="🎉 **NEW GIVEAWAY!** 🎉", embed=embed, view=view)

        real_key = f"{guild.id}_{gw_msg.id}"
        real_view = GiveawayEnterView(giveaway_key=real_key, entry_count=0)
        await gw_msg.edit(view=real_view)

        # Save giveaway
        gw_data = {
            "message_id": gw_msg.id,
            "channel_id": target_channel.id,
            "guild_id": guild.id,
            "prize": prize,
            "host_id": interaction.user.id,
            "sponsor_id": interaction.user.id,
            "winners_count": winners_count,
            "created_at": now,
            "end_time": end_time,
            "status": "active",
            "entries": [],
            "winners": [],
            "description": description or ""
        }
        db.giveaways[real_key] = gw_data
        db.save_data()

        # Log event in #giveaway-logs
        log_ch_id = cfg.get("log_channel")
        log_channel = guild.get_channel(log_ch_id) if log_ch_id else None
        if log_channel:
            log_embed = discord.Embed(
                title="📜 Giveaway Created",
                description=(
                    f"**Prize:** {prize}\n"
                    f"**Host:** {interaction.user.mention}\n"
                    f"**Duration:** {format_duration(duration_sec)}\n"
                    f"**Winners:** {winners_count}\n"
                    f"**Channel:** {target_channel.mention}\n"
                    f"**Message Link:** [Jump to Giveaway]({gw_msg.jump_url})"
                ),
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            try:
                await log_channel.send(embed=log_embed)
            except Exception:
                pass

        await interaction.response.send_message(
            f"🎉 Giveaway for **{prize}** created successfully in {target_channel.mention}!\n[Click here to view]({gw_msg.jump_url})",
            ephemeral=True
        )

    @app_commands.command(name="gstart", description="Alias for /gcreate to quickly launch a giveaway")
    @app_commands.describe(
        prize="The item, role, or gift to give away",
        duration="Duration of the giveaway (e.g. 10m, 1h, 2d, 1w)",
        winners="Number of winners to pick (default: 1)",
        description="Optional detailed description or rules",
        channel="Optional channel to post in"
    )
    async def gstart(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: Optional[int] = 1,
        description: Optional[str] = None,
        channel: Optional[discord.TextChannel] = None
    ):
        """Direct alias invoking /gcreate logic."""
        await self.gcreate.callback(self, interaction, prize, duration, winners, description, channel)

    @app_commands.command(name="gend", description="End an active giveaway early and pick winners immediately")
    @app_commands.describe(message_id="The Discord Message ID of the giveaway")
    @app_commands.default_permissions(manage_guild=True)
    async def gend(self, interaction: discord.Interaction, message_id: str):
        """Immediately ends an active giveaway and draws winners."""
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🛡️ Only server staff can end giveaways.", ephemeral=True)
            return

        clean_id = message_id.strip()
        key = f"{interaction.guild_id}_{clean_id}"
        gw = db.giveaways.get(key)

        if not gw or gw.get("status") != "active":
            await interaction.response.send_message(f"❌ Active giveaway with message ID `{clean_id}` was not found.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await self.conclude_giveaway(key, gw)
        await interaction.followup.send(f"✅ Successfully ended the giveaway for **{gw.get('prize')}** early!", ephemeral=True)

    @app_commands.command(name="greroll", description="Reroll new winner(s) for an ended giveaway")
    @app_commands.describe(
        message_id="The Discord Message ID of the ended giveaway",
        winners="Number of new winners to pick (default: 1)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def greroll(self, interaction: discord.Interaction, message_id: str, winners: Optional[int] = 1):
        """Rerolls winners from the entry pool of an ended giveaway."""
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🛡️ Only server staff can reroll giveaways.", ephemeral=True)
            return

        clean_id = message_id.strip()
        key = f"{interaction.guild_id}_{clean_id}"
        gw = db.giveaways.get(key)

        if not gw:
            await interaction.response.send_message(f"❌ Giveaway with message ID `{clean_id}` was not found.", ephemeral=True)
            return

        entries = gw.get("entries", [])
        if not entries:
            await interaction.response.send_message("❌ This giveaway has 0 entries, so it cannot be rerolled.", ephemeral=True)
            return

        count = max(1, min(winners or 1, len(entries)))
        new_winners = random.sample(entries, k=count)
        gw["winners"] = new_winners
        db.save_data()

        channel = interaction.guild.get_channel(gw.get("channel_id"))
        prize = gw.get("prize", "the prize")

        if channel:
            mentions_str = " ".join(f"<@{w}>" for w in new_winners)
            msg = (
                f"🎲 **GIVEAWAY REROLLED!** 🎲\n\n"
                f"New Winner: {mentions_str}! Congratulations, you won **{prize}**! 🎁\n"
                f"Message link: https://discord.com/channels/{interaction.guild_id}/{channel.id}/{clean_id}"
            )
            await channel.send(msg)

        # Log reroll
        cfg = get_giveaway_config(interaction.guild_id)
        log_ch_id = cfg.get("log_channel")
        log_channel = interaction.guild.get_channel(log_ch_id) if log_ch_id else None
        if log_channel:
            log_embed = discord.Embed(
                title="📜 Giveaway Rerolled",
                description=(
                    f"**Prize:** {prize}\n"
                    f"**Rerolled by:** {interaction.user.mention}\n"
                    f"**New Winners:** {', '.join(f'<@{w}>' for w in new_winners)}\n"
                    f"**Giveaway ID:** `{clean_id}`"
                ),
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            try:
                await log_channel.send(embed=log_embed)
            except Exception:
                pass

        await interaction.response.send_message(f"✅ Rerolled {count} new winner(s) for **{prize}**!", ephemeral=True)

    @app_commands.command(name="gcancel", description="Cancel an active giveaway without picking winners")
    @app_commands.describe(message_id="The Discord Message ID of the giveaway")
    @app_commands.default_permissions(manage_guild=True)
    async def gcancel(self, interaction: discord.Interaction, message_id: str):
        """Cancels an active giveaway without drawing any winners."""
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🛡️ Only server staff can cancel giveaways.", ephemeral=True)
            return

        clean_id = message_id.strip()
        key = f"{interaction.guild_id}_{clean_id}"
        gw = db.giveaways.get(key)

        if not gw or gw.get("status") != "active":
            await interaction.response.send_message(f"❌ Active giveaway with message ID `{clean_id}` was not found.", ephemeral=True)
            return

        gw["status"] = "cancelled"
        db.save_data()

        channel = interaction.guild.get_channel(gw.get("channel_id"))
        if channel:
            try:
                msg = await channel.fetch_message(int(clean_id))
                if msg:
                    embed = msg.embeds[0]
                    embed.title = f"❌ GIVEAWAY CANCELLED: {gw.get('prize')} ❌"
                    embed.color = discord.Color.red()
                    embed.set_footer(text=f"Cancelled by {interaction.user.display_name}")
                    disabled_view = GiveawayEnterView(giveaway_key=key, entry_count=len(gw.get("entries", [])), disabled=True)
                    await msg.edit(embed=embed, view=disabled_view)
            except Exception:
                pass

        await interaction.response.send_message(f"❌ Successfully cancelled the giveaway for **{gw.get('prize')}**.", ephemeral=True)

    @app_commands.command(name="glist", description="List all active giveaways running in this server")
    async def glist(self, interaction: discord.Interaction):
        """Displays all running giveaways in the guild."""
        gid = interaction.guild_id
        active = []
        giveaways_dict = getattr(db, "giveaways", {})

        for key, gw in giveaways_dict.items():
            if isinstance(gw, dict) and gw.get("guild_id") == gid and gw.get("status") == "active":
                active.append(gw)

        if not active:
            await interaction.response.send_message("🎁 No active giveaways are currently running in this server.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🎁 Active Giveaways in {interaction.guild.name}",
            color=discord.Color.from_rgb(88, 101, 242),
            timestamp=datetime.now(timezone.utc)
        )

        for gw in active[:15]:
            end_ts = int(gw.get("end_time", time.time()))
            entries_count = len(gw.get("entries", []))
            ch_id = gw.get("channel_id")
            msg_id = gw.get("message_id")
            link = f"https://discord.com/channels/{gid}/{ch_id}/{msg_id}"
            embed.add_field(
                name=f"🎉 {gw.get('prize')}",
                value=(
                    f"• **Channel:** <#{ch_id}>\n"
                    f"• **Winners:** {gw.get('winners_count', 1)}\n"
                    f"• **Entries:** {entries_count}\n"
                    f"• **Ends:** <t:{end_ts}:R>\n"
                    f"• [Jump to Giveaway]({link})"
                ),
                inline=False
            )

        embed.set_footer(text=f"Total Active Giveaways: {len(active)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))

