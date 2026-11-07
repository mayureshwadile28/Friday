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
    if not isinstance(getattr(db, "giveaways_config", None), dict):
        db.giveaways_config = {}
    cfg = db.giveaways_config.get(gid_str, {})
    if not isinstance(cfg, dict):
        cfg = {}
        db.giveaways_config[gid_str] = cfg
    return cfg


def is_giveaway_configured(guild_id: int) -> bool:
    """Checks whether giveaway channels (broadcast, approvals, logs) are set up."""
    cfg = get_giveaway_config(guild_id)
    return bool(cfg.get("giveaway_channel") and cfg.get("approval_channel") and cfg.get("log_channel"))


from urllib.parse import urlparse

def validate_image_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = str(url).strip()
    if not url:
        return None
    if url.startswith("attachment://"):
        return url
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith(("http://", "https://")):
        if "." in url and not url.startswith(("/", "\\")):
            url = "https://" + url
        else:
            return None
    try:
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.netloc and "." in parsed.netloc:
            return url
    except Exception:
        pass
    return None

def parse_hex_color(hex_str: Optional[str], default: int = 0x5865F2) -> discord.Color:
    if not hex_str:
        return discord.Color(default)
    clean = str(hex_str).strip().lstrip("#")
    try:
        if len(clean) == 6:
            return discord.Color(int(clean, 16))
        elif len(clean) == 3:
            expanded = "".join(c * 2 for c in clean)
            return discord.Color(int(expanded, 16))
    except Exception:
        pass
    return discord.Color(default)

def resolve_safe_emoji(bot, emoji_str: Optional[str], fallback: str = "🎁") -> str:
    if not emoji_str:
        return fallback
    emoji_str = str(emoji_str).strip()
    if not emoji_str:
        return fallback
    if emoji_str.startswith("<") and emoji_str.endswith(">"):
        match = re.search(r":(\d+)>$", emoji_str)
        if match:
            eid = int(match.group(1))
            if bot and bot.get_emoji(eid):
                return emoji_str
            return fallback
    return emoji_str

def parse_discord_button_emoji(emoji_str: Optional[str]):
    if not emoji_str:
        return "🎁"
    emoji_str = str(emoji_str).strip()
    try:
        if emoji_str.startswith("<") and emoji_str.endswith(">"):
            return discord.PartialEmoji.from_str(emoji_str)
        return emoji_str
    except Exception:
        return "🎁"

# ─────────────────────────────────────────────────────────────
# Persistent Giveaway Views
# ─────────────────────────────────────────────────────────────

class GiveawayEnterView(discord.ui.View):
    """
    Persistent button view for giveaway messages.
    Allows members to enter or leave the giveaway, or view participants list with real-time updates.
    """
    def __init__(self, giveaway_key: str, entry_count: int = 0, disabled: bool = False, emoji: str = "🎁", emoji_participants: str = "👥"):
        super().__init__(timeout=None)
        self.giveaway_key = giveaway_key
        self.emoji = emoji or "🎁"
        self.emoji_participants = emoji_participants or "👥"
        parsed_emoji = parse_discord_button_emoji(self.emoji) if not disabled else "🔒"
        button_label = f"Enter Giveaway ({entry_count})" if not disabled else f"Giveaway Ended ({entry_count})"
        self.enter_btn = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label=button_label,
            emoji=parsed_emoji,
            custom_id=f"gw_enter:{giveaway_key}",
            disabled=disabled,
            row=0
        )
        self.enter_btn.callback = self.enter_callback
        self.add_item(self.enter_btn)

        # Participants Button (same secondary curved gray style, ephemeral visibility)
        parsed_part_emoji = parse_discord_button_emoji(self.emoji_participants)
        self.participants_btn = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Participants",
            emoji=parsed_part_emoji,
            custom_id=f"gw_parts:{giveaway_key}",
            disabled=False,
            row=0
        )
        self.participants_btn.callback = self.participants_callback
        self.add_item(self.participants_btn)

    async def participants_callback(self, interaction: discord.Interaction):
        gw = db.giveaways.get(self.giveaway_key)
        if not gw:
            await interaction.response.send_message("⚠️ Giveaway data could not be found or has expired.", ephemeral=True)
            return

        guild_id = interaction.guild_id or gw.get("guild_id")
        cfg = get_giveaway_config(guild_id) if guild_id else {}
        entries = gw.get("entries", [])
        total = len(entries)
        prize = gw.get("prize", "the prize")

        # Resolve customized participants emoji (supports server custom static & animated emojis)
        raw_part_emoji = cfg.get("emoji_participants_response") or cfg.get("emoji_participants") or self.emoji_participants or "👥"
        safe_part_emoji = resolve_safe_emoji(interaction.client, raw_part_emoji, fallback="👥")

        if total == 0:
            empty_tpl = cfg.get("participants_empty") or "{emoji} **Participants for {prize} (0):**\nNo members have entered this giveaway yet. Be the first to enter!"
            empty_msg = (
                empty_tpl
                .replace("{emoji}", safe_part_emoji)
                .replace("{prize}", prize)
                .replace("{count}", "0")
                .replace("{total}", "0")
                .replace("{server}", interaction.guild.name if interaction.guild else "this server")
            )
            await interaction.response.send_message(empty_msg, ephemeral=True)
            return

        gid_str = str(guild_id)
        cr = getattr(db, "custom_responses", {}).get(gid_str, {})
        header_tpl = cr.get("gw_participants_response") or cfg.get("participants_header") or "{emoji} **Participants for {prize} ({count}):**\n"
        header = (
            header_tpl
            .replace("{emoji}", safe_part_emoji)
            .replace("{prize}", prize)
            .replace("{count}", str(total))
            .replace("{total}", str(total))
            .replace("{server}", interaction.guild.name if interaction.guild else "this server")
        )
        if not header.endswith("\n"):
            header += "\n"

        p_lines = []
        for idx, uid in enumerate(entries[:60], 1):
            p_lines.append(f"{idx}. <@{uid}>")
        
        body = "\n".join(p_lines)
        if total > 60:
            body += f"\n\n*... and {total - 60} more participants.*"

        full_msg = header + body
        if len(full_msg) > 1950:
            full_msg = full_msg[:1900] + f"\n\n*... and {total - len(p_lines)} more participants.*"

        await interaction.response.send_message(full_msg, ephemeral=True)

    async def enter_callback(self, interaction: discord.Interaction):
        gw = db.giveaways.get(self.giveaway_key)
        if not gw or gw.get("status") != "active":
            await interaction.response.send_message("⚠️ This giveaway has already ended or is no longer active.", ephemeral=True)
            self.enter_btn.disabled = True
            self.enter_btn.label = f"Giveaway Ended ({len(gw.get('entries', [])) if gw else 0})"
            self.enter_btn.emoji = "🔒"
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

        # Sync entries across all alias keys sharing message_id
        msg_id = gw.get("message_id")
        if msg_id:
            for k, v in getattr(db, "giveaways", {}).items():
                if isinstance(v, dict) and v.get("message_id") == msg_id:
                    v["entries"] = list(entries)

        db.save_data()

        # Update button label with the new entry count
        count = len(entries)
        self.enter_btn.label = f"Enter Giveaway ({count})"
        self.enter_btn.emoji = parse_discord_button_emoji(self.emoji)

        try:
            # ONLY edit view (the button label). Never re-edit the embed upon entry click!
            # Re-editing the embed on a message with attachment files causes Discord API to
            # un-embed the attachment and display duplicate GIF/image banners above the embed card.
            await interaction.message.edit(view=self)
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

        cfg = get_giveaway_config(guild.id)
        emoji_prize = cfg.get("emoji_prize", "🎁")
        emoji_host = cfg.get("emoji_host", "👑")
        emoji_winners = cfg.get("emoji_winners", "🏆")
        emoji_entries = cfg.get("emoji_entries", "🎟️")
        emoji_ends = cfg.get("emoji_ends", "⏳")

        end_timestamp = int(end_time)
        image_url = req.get("image_url") or cfg.get("default_banner")

        dot = resolve_safe_emoji(self.bot, cfg.get("emoji_bullet"), fallback="•")
        desc_body = (
            f"{dot} **Winners:** {winners_count}\n"
            f"{dot} **Ends In:** <t:{end_timestamp}:R> (<t:{end_timestamp}:f>)\n"
            f"{dot} **Hosted By:** <@{sponsor_id}>\n\n"
            f"{dot} {description or 'Click the button below to participate!'}"
        )

        embed_color_hex = cfg.get("embed_color", "#5865F2")
        embed_color = parse_hex_color(embed_color_hex, default=0x5865F2)
        valid_img = validate_image_url(image_url)

        embed = discord.Embed(
            title=f"{emoji_prize} {prize} {emoji_prize}",
            description=desc_body,
            color=embed_color,
            timestamp=datetime.fromtimestamp(end_time, timezone.utc)
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if valid_img:
            embed.set_image(url=valid_img)

        ends_date_str = datetime.fromtimestamp(end_time, timezone.utc).strftime("%m/%d/%y")
        embed.set_footer(text=f"Ends • {ends_date_str}", icon_url=guild.icon.url if guild.icon else None)

        cfg = get_giveaway_config(guild.id)
        emoji_parts = cfg.get("emoji_participants", "👥")
        entry_method = str(cfg.get("entry_method", "button")).lower()
        if entry_method != "reaction":
            entry_method = "button"

        gw_key = f"{guild.id}_{self.request_id}"
        view = GiveawayEnterView(giveaway_key=gw_key, entry_count=0, emoji=emoji_prize, emoji_participants=emoji_parts) if entry_method == "button" else None

        emoji_header = resolve_safe_emoji(self.bot, req.get("header_emoji") or req.get("emoji_header") or cfg.get("emoji_header"), fallback="🎉")
        send_kwargs = {"content": f"{emoji_header} **New Giveaway** {emoji_header}", "embed": embed}
        if view:
            send_kwargs["view"] = view
        gw_msg = await gw_channel.send(**send_kwargs)

        if entry_method == "reaction":
            try:
                if emoji_prize.startswith("<") and emoji_prize.endswith(">"):
                    m = re.search(r":(\d+)>$", emoji_prize)
                    if m:
                        rx = self.bot.get_emoji(int(m.group(1)))
                        if rx:
                            await gw_msg.add_reaction(rx)
                        else:
                            await gw_msg.add_reaction("🎁")
                    else:
                        await gw_msg.add_reaction("🎁")
                else:
                    await gw_msg.add_reaction(emoji_prize)
            except Exception:
                try:
                    await gw_msg.add_reaction("🎁")
                except Exception:
                    pass

        # Re-key with the real message id
        real_key = f"{guild.id}_{gw_msg.id}"
        if entry_method == "button":
            real_view = GiveawayEnterView(giveaway_key=real_key, entry_count=0, emoji=emoji_prize, emoji_participants=emoji_parts)
            try:
                await gw_msg.edit(view=real_view)
            except Exception:
                pass

        gw_data = {
            "message_id": gw_msg.id,
            "channel_id": gw_channel.id,
            "guild_id": guild.id,
            "prize": prize,
            "host_id": interaction.user.id,
            "sponsor_id": sponsor_id,
            "entry_method": entry_method,
            "winners_count": winners_count,
            "created_at": now,
            "end_time": end_time,
            "status": "active",
            "entries": [],
            "winners": [],
            "description": description,
            "image_url": image_url or "",
            "header_emoji": emoji_header
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
# Setup Wizard Components  (Slash-command-only, no prefix commands)
# ─────────────────────────────────────────────────────────────

class SetupWizardView(discord.ui.View):
    """
    Root setup view shown by /gsetup.
    Two buttons — no dynamic dropdown that can silently fail.
    """
    def __init__(self):
        super().__init__(timeout=300)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        import traceback
        traceback.print_exc()
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⚠️ Setup error: `{error}`", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠️ Setup error: `{error}`", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="🪄  Auto-Create All Channels", style=discord.ButtonStyle.success, row=0)
    async def auto_create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild = interaction.guild
        bot_member = guild.me
        everyone = guild.default_role

        public_ow = {
            everyone: discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False),
            bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, manage_messages=True)
        }
        private_ow = {
            everyone: discord.PermissionOverwrite(view_channel=False),
            bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, manage_messages=True)
        }

        try:
            gw_ch = await guild.create_text_channel(
                name="giveaways", overwrites=public_ow,
                topic="Official Friday giveaways 🎁", reason="Friday /gsetup auto-create"
            )
            app_ch = await guild.create_text_channel(
                name="giveaway-approvals", overwrites=private_ow,
                topic="Private staff approval queue 🛡️", reason="Friday /gsetup auto-create"
            )
            log_ch = await guild.create_text_channel(
                name="giveaway-logs", overwrites=private_ow,
                topic="Audit log of winners & rerolls 📜", reason="Friday /gsetup auto-create"
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I need **Manage Channels** permission to create channels. Please grant it, then run `/gsetup` again.",
                ephemeral=True
            )
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Channel creation failed: `{e}`", ephemeral=True)
            return

        cfg = get_giveaway_config(guild.id)
        cfg["giveaway_channel"] = str(gw_ch.id)
        cfg["approval_channel"] = str(app_ch.id)
        cfg["log_channel"] = str(log_ch.id)
        db.giveaways_config[str(guild.id)] = cfg
        db.save_data()

        embed = discord.Embed(
            title="✅ Giveaway Channels Created!",
            description=(
                "All 3 channels have been provisioned:\n\n"
                f"📢 **Broadcast:** {gw_ch.mention}\n"
                f"🛡️ **Staff Approvals:** {app_ch.mention} *(private)*\n"
                f"📜 **Audit Logs:** {log_ch.mention} *(private)*\n\n"
                "> You're all set! Use `/gcreate` to launch your first giveaway."
            ),
            color=discord.Color.green()
        )
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="🔗  Link Existing Channels", style=discord.ButtonStyle.secondary, row=0)
    async def link_existing(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = CategorySelectStepView(role_type="giveaway_channel")
        embed = view.get_embed()
        await interaction.edit_original_response(embed=embed, view=view)


GW_ROLE_METADATA = {
    "giveaway_channel": {
        "step_num": "1 of 3",
        "title": "📢 Public Giveaway Broadcast Channel",
        "desc": "Where all giveaway cards will be posted for server members to enter.",
        "next": "approval_channel"
    },
    "approval_channel": {
        "step_num": "2 of 3",
        "title": "🛡️ Staff Approvals Channel (Private)",
        "desc": "Private staff queue where member-submitted giveaway requests are reviewed.",
        "next": "log_channel"
    },
    "log_channel": {
        "step_num": "3 of 3",
        "title": "📜 Giveaway Audit Logs Channel (Private)",
        "desc": "Private audit trail recording all winner selections, rerolls, and early endings.",
        "next": None
    }
}


class CategorySelectStepView(discord.ui.View):
    """Step A: Category selector to prevent channel overflow in servers with 50+ channels."""
    def __init__(self, role_type: str):
        super().__init__(timeout=300)
        self.role_type = role_type
        self.meta = GW_ROLE_METADATA.get(role_type, GW_ROLE_METADATA["giveaway_channel"])

        self.cat_select = discord.ui.ChannelSelect(
            placeholder=f"📁 Step {self.meta['step_num']}: Pick Category…"[:100],
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.category],
            row=0
        )
        self.cat_select.callback = self.cat_callback
        self.add_item(self.cat_select)

    def get_embed(self) -> discord.Embed:
        desc = (
            f"**Target:** {self.meta['title']}\n"
            f"> {self.meta['desc']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📁 **First, choose the Category where this channel is located:**\n"
            "*(Friday will show only the text channels inside your selected category)*"
        )
        return discord.Embed(
            title=f"◈ Friday Giveaway Engine • Step {self.meta['step_num']}",
            description=desc,
            color=discord.Color.blurple()
        )

    async def cat_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cat = self.cat_select.values[0]
        cat_id = int(cat.id if hasattr(cat, "id") else cat)
        category = interaction.guild.get_channel(cat_id)
        if not category:
            await interaction.followup.send("❌ Category not found. Please try again.", ephemeral=True)
            return

        text_channels = [c for c in category.text_channels if isinstance(c, discord.TextChannel)]
        if not text_channels:
            embed = self.get_embed()
            embed.description += f"\n\n⚠️ **Notice:** No text channels found in **{category.name}**. Please choose another category."
            await interaction.edit_original_response(embed=embed, view=self)
            return

        view = ChannelInCatStepView(role_type=self.role_type, category=category, channels=text_channels)
        embed = view.get_embed()
        await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="🌐  Uncategorized Channels", style=discord.ButtonStyle.secondary, row=1)
    async def uncat_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        uncat_channels = [c for c in interaction.guild.text_channels if c.category is None]
        if not uncat_channels:
            embed = self.get_embed()
            embed.description += "\n\n⚠️ **Notice:** No uncategorized text channels found on this server."
            await interaction.edit_original_response(embed=embed, view=self)
            return

        view = ChannelInCatStepView(role_type=self.role_type, category=None, channels=uncat_channels)
        embed = view.get_embed()
        await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="⚡  Direct Channel Pick (All)", style=discord.ButtonStyle.secondary, row=1)
    async def direct_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = DirectChannelPickView(role_type=self.role_type)
        desc = (
            f"**Target:** {self.meta['title']}\n"
            f"> {self.meta['desc']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ **Select the channel directly from the dropdown below:**"
        )
        embed = discord.Embed(
            title=f"◈ Friday Giveaway Engine • Step {self.meta['step_num']}",
            description=desc,
            color=discord.Color.blurple()
        )
        await interaction.edit_original_response(embed=embed, view=view)


class ChannelInCatStepView(discord.ui.View):
    """Step B: Prompts user to pick a text channel from within the chosen Category."""
    def __init__(self, role_type: str, category: Optional[discord.CategoryChannel], channels: list):
        super().__init__(timeout=300)
        self.role_type = role_type
        self.category = category
        self.channels = channels
        self.meta = GW_ROLE_METADATA.get(role_type, GW_ROLE_METADATA["giveaway_channel"])

        cat_name = category.name if category else "Uncategorized"
        options = [
            discord.SelectOption(
                label=f"#{c.name}"[:100],
                value=str(c.id),
                description=f"ID: {c.id}"
            )
            for c in channels[:25]
        ]

        self.ch_select = discord.ui.Select(
            placeholder=f"Select channel inside {cat_name}…"[:100],
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )
        self.ch_select.callback = self.channel_callback
        self.add_item(self.ch_select)

    def get_embed(self) -> discord.Embed:
        cat_name = self.category.name if self.category else "Uncategorized"
        desc = (
            f"**Target:** {self.meta['title']}\n"
            f"📁 **Selected Category:** `{cat_name}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Now pick the channel from `{cat_name}`:**"
        )
        return discord.Embed(
            title=f"◈ Friday Giveaway Engine • Step {self.meta['step_num']}",
            description=desc,
            color=discord.Color.blurple()
        )

    async def channel_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        ch_id = int(self.ch_select.values[0])
        cfg = get_giveaway_config(interaction.guild.id)
        cfg[self.role_type] = str(ch_id)
        db.giveaways_config[str(interaction.guild.id)] = cfg
        db.save_data()

        next_role = self.meta.get("next")
        if next_role:
            view = CategorySelectStepView(role_type=next_role)
            embed = view.get_embed()
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            # Final Step Completed!
            desc = (
                f"All giveaway channels have been linked successfully:\n\n"
                f"📢 **Broadcast:** <#{cfg.get('giveaway_channel')}>\n"
                f"🛡️ **Staff Approvals:** <#{cfg.get('approval_channel')}>\n"
                f"📜 **Audit Logs:** <#{cfg.get('log_channel')}>\n\n"
                "> You're all set! Use `/gcreate` or the Web Dashboard to launch your first giveaway."
            )
            embed = discord.Embed(
                title="✅ Giveaway Channels Linked!",
                description=desc,
                color=discord.Color.green()
            )
            await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="🔙  Change Category", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = CategorySelectStepView(role_type=self.role_type)
        embed = view.get_embed()
        await interaction.edit_original_response(embed=embed, view=view)


class DirectChannelPickView(discord.ui.View):
    """Direct ChannelSelect fallback."""
    def __init__(self, role_type: str):
        super().__init__(timeout=300)
        self.role_type = role_type
        self.meta = GW_ROLE_METADATA.get(role_type, GW_ROLE_METADATA["giveaway_channel"])
        self.ch_select = discord.ui.ChannelSelect(
            placeholder="Select a text channel…",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
            row=0
        )
        self.ch_select.callback = self.ch_callback
        self.add_item(self.ch_select)

    async def ch_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        ch = self.ch_select.values[0]
        ch_id = int(ch.id if hasattr(ch, "id") else ch)
        cfg = get_giveaway_config(interaction.guild.id)
        cfg[self.role_type] = str(ch_id)
        db.giveaways_config[str(interaction.guild.id)] = cfg
        db.save_data()

        next_role = self.meta.get("next")
        if next_role:
            view = CategorySelectStepView(role_type=next_role)
            embed = view.get_embed()
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            desc = (
                f"📢 **Broadcast:** <#{cfg.get('giveaway_channel')}>\n"
                f"🛡️ **Staff Approvals:** <#{cfg.get('approval_channel')}>\n"
                f"📜 **Audit Logs:** <#{cfg.get('log_channel')}>\n\n"
                "> You're all set! Use `/gcreate` or the Web Dashboard to launch your first giveaway."
            )
            embed = discord.Embed(
                title="✅ Giveaway Channels Linked!",
                description=desc,
                color=discord.Color.green()
            )
            await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="🔙  Filter by Category Instead", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = CategorySelectStepView(role_type=self.role_type)
        embed = view.get_embed()
        await interaction.edit_original_response(embed=embed, view=view)


class LaunchSetupButtonView(discord.ui.View):
    """Persistent button shown by /gcreate when setup has never been done."""
    def __init__(self):
        super().__init__(timeout=None)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        import traceback
        traceback.print_exc()
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⚠️ Error: `{error}`", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠️ Error: `{error}`", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="⚙️  Launch Setup Wizard", style=discord.ButtonStyle.primary, custom_id="gsetup_launch_btn")
    async def launch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🛡️ Only administrators can configure the giveaway system.", ephemeral=True)
            return
        embed = discord.Embed(
            title="◈ Friday Giveaway Engine • Setup Wizard ◈",
            description=(
                "Friday needs **3 channels** to run giveaways:\n\n"
                "📢 **Broadcast** — public, members enter giveaways here\n"
                "🛡️ **Approvals** — private, staff review member requests\n"
                "📜 **Logs** — private, records all winners & rerolls\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Choose below — Friday can create them automatically, or link ones you already have."
            ),
            color=discord.Color.from_rgb(99, 102, 241)
        )
        await interaction.response.send_message(embed=embed, view=SetupWizardView(), ephemeral=True)

    async def launch_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🛡️ Only server administrators can configure the giveaway system.", ephemeral=True)
            return
        embed = discord.Embed(
            title="◈ Friday Giveaway Engine • Setup Wizard ◈",
            description=(
                "Friday needs **3 channels** to run giveaways:\n\n"
                "📢 **Broadcast** — public, members enter giveaways here\n"
                "🛡️ **Approvals** — private, staff review member requests\n"
                "📜 **Logs** — private, records all winners & rerolls\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Choose below — Friday can create them automatically, or link ones you already have."
            ),
            color=discord.Color.from_rgb(99, 102, 241)
        )
        await interaction.response.send_message(embed=embed, view=SetupWizardView(), ephemeral=True)


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
                        cfg = get_giveaway_config(data.get("guild_id", 0))
                        emoji_prize = cfg.get("emoji_prize", "🎁")
                        emoji_parts = cfg.get("emoji_participants", "👥")
                        self.bot.add_view(GiveawayEnterView(giveaway_key=key, entry_count=len(entries), emoji=emoji_prize, emoji_participants=emoji_parts))
                    elif data.get("status") == "pending" and key.startswith("req_"):
                        req_id = key.replace("req_", "")
                        self.bot.add_view(GiveawayApprovalView(request_id=req_id))
        except Exception as e:
            print(f"[Giveaways] Error restoring persistent views: {e}")

    # ─────────────────────────────────────────────────────────────
    # Background Worker: Check Expired Giveaways
    # ─────────────────────────────────────────────────────────────
        # ─────────────────────────────────────────────────────────────
    # Reaction Listeners: React with emoji to enter / unenter
    # ─────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Allow members to enter the giveaway by reacting to the giveaway card."""
        if payload.user_id == self.bot.user.id or not payload.guild_id:
            return

        key = f"{payload.guild_id}_{payload.message_id}"
        gw = db.giveaways.get(key)
        if not gw or gw.get("status") != "active":
            return

        entries = gw.setdefault("entries", [])
        if payload.user_id not in entries:
            entries.append(payload.user_id)
            db.save_data()

            # Update button entry counter on the message
            try:
                channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
                msg = await channel.fetch_message(payload.message_id)
                cfg = get_giveaway_config(payload.guild_id)
                emoji_prize = cfg.get("emoji_prize", "🎁")
                emoji_parts = cfg.get("emoji_participants", "👥")
                view = GiveawayEnterView(giveaway_key=key, entry_count=len(entries), emoji=emoji_prize, emoji_participants=emoji_parts)
                await msg.edit(view=view)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Allow members to leave the giveaway by removing their reaction."""
        if payload.user_id == self.bot.user.id or not payload.guild_id:
            return

        key = f"{payload.guild_id}_{payload.message_id}"
        gw = db.giveaways.get(key)
        if not gw or gw.get("status") != "active":
            return

        entries = gw.setdefault("entries", [])
        if payload.user_id in entries:
            entries.remove(payload.user_id)
            db.save_data()

            try:
                channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
                msg = await channel.fetch_message(payload.message_id)
                cfg = get_giveaway_config(payload.guild_id)
                emoji_prize = cfg.get("emoji_prize", "🎁")
                emoji_parts = cfg.get("emoji_participants", "👥")
                view = GiveawayEnterView(giveaway_key=key, entry_count=len(entries), emoji=emoji_prize, emoji_participants=emoji_parts)
                await msg.edit(view=view)
            except Exception:
                pass

    @tasks.loop(seconds=10)
    async def giveaway_checker(self):
        """Monitors active giveaways every 10 seconds and automatically draws winners upon expiration."""
        now = time.time()
        giveaways_dict = getattr(db, "giveaways", {})
        processed_msg_ids = set()

        for key, gw in list(giveaways_dict.items()):
            if not isinstance(gw, dict) or gw.get("status") != "active":
                continue

            msg_id = gw.get("message_id")
            if msg_id and msg_id in processed_msg_ids:
                gw["status"] = "ended"
                continue

            end_time = gw.get("end_time", 0)
            if now < end_time:
                continue

            if msg_id:
                processed_msg_ids.add(msg_id)

            # Giveaway has expired: draw winners!
            await self.conclude_giveaway(key, gw)

    async def conclude_giveaway(self, key: str, gw: dict):
        """Concludes an active giveaway, picks random winners, edits the card, and logs the result."""
        message_id = gw.get("message_id")
        
        # Guard against duplicate conclusions across alias keys
        if gw.get("status") == "ended" and gw.get("winners") is not None:
            return
        if message_id:
            for k, v in list(getattr(db, "giveaways", {}).items()):
                if isinstance(v, dict) and v.get("message_id") == message_id:
                    if v.get("status") == "ended" and v.get("winners") is not None:
                        gw["status"] = "ended"
                        gw["winners"] = v.get("winners", [])
                        gw["ended_at"] = v.get("ended_at", time.time())
                        db.save_data()
                        return

        guild_id = gw.get("guild_id")
        channel_id = gw.get("channel_id")
        prize = gw.get("prize", "Unknown Prize")
        host_id = gw.get("host_id")
        sponsor_id = gw.get("sponsor_id", host_id)
        host_name = gw.get("host_name")
        if sponsor_id and str(sponsor_id).isdigit() and str(sponsor_id) != "0":
            host_display = f"<@{sponsor_id}>"
        elif host_name and host_name != "Server Staff":
            host_display = f"@{host_name.lstrip('@')}"
        else:
            host_display = "Server Staff"
        winners_count = gw.get("winners_count", 1)

        # Consolidate entries across any duplicate alias keys
        all_entries = list(gw.get("entries", []))
        if message_id:
            for k, v in getattr(db, "giveaways", {}).items():
                if isinstance(v, dict) and v.get("message_id") == message_id:
                    for uid in v.get("entries", []):
                        if uid not in all_entries:
                            all_entries.append(uid)
        entries = all_entries
        gw["entries"] = entries

        # Pick random winners without duplicates
        if entries:
            chosen = random.sample(entries, k=min(len(entries), winners_count))
        else:
            chosen = []

        ended_timestamp = time.time()
        # Mark ALL alias keys sharing message_id as ended at once
        if message_id:
            for k, v in getattr(db, "giveaways", {}).items():
                if isinstance(v, dict) and v.get("message_id") == message_id:
                    v["status"] = "ended"
                    v["winners"] = chosen
                    v["ended_at"] = ended_timestamp
                    v["entries"] = entries
        gw["status"] = "ended"
        gw["winners"] = chosen
        gw["ended_at"] = ended_timestamp
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

                cfg = get_giveaway_config(guild_id)
                dot = resolve_safe_emoji(self.bot, cfg.get("emoji_bullet"), fallback="•")
                ended_desc = (
                    f"{dot} **Winners:** {winners_text}\n"
                    f"{dot} **Hosted By:** {host_display}\n"
                    f"{dot} **Total Entries:** **{len(entries)}**\n\n"
                    f"{dot} {gw.get('description') or 'Giveaway has ended.'}"
                )
                emoji_ended = cfg.get("emoji_ended", "🔒")

                ended_embed = discord.Embed(
                    title=f"{emoji_ended} GIVEAWAY ENDED: {prize}",
                    description=ended_desc,
                    color=discord.Color.from_rgb(47, 49, 54), # Sleek dark
                    timestamp=datetime.now(timezone.utc)
                )
                if guild.icon:
                    ended_embed.set_thumbnail(url=guild.icon.url)
                if gw.get("image_url"):
                    valid_ended_img = validate_image_url(gw.get("image_url"))
                    if valid_ended_img:
                        ended_embed.set_image(url=valid_ended_img)
                ended_embed.set_footer(text="Ended • Friday Engine", icon_url=guild.icon.url if guild.icon else None)

                disabled_view = GiveawayEnterView(giveaway_key=key, entry_count=len(entries), disabled=True, emoji=emoji_ended)
                await msg.edit(embed=ended_embed, view=disabled_view)
        except Exception as e:
            print(f"[Giveaways] Failed to edit ended message {message_id}: {e}")

        # Send public winner announcement in the giveaway channel
        try:
            cfg = get_giveaway_config(guild_id)
            jump_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
            emoji_prize = cfg.get("emoji_prize", "🎁")
            emoji_host = cfg.get("emoji_host", "👑")
            emoji_entries = cfg.get("emoji_entries", "🎟️")
            
            if chosen:
                mentions_str = " ".join(f"<@{w}>" for w in chosen)
                winner_title = cfg.get("winner_title") or "🎉 GIVEAWAY CONCLUDED! 🎉"
                default_msg = (
                    f"> 🎊 Congratulations {{winners}}! You won **{{prize}}**! {emoji_prize}\n\n"
                    f"{emoji_host} **Hosted by:** {{host}}\n"
                    f"{emoji_entries} **Entries:** {{entries}}\n"
                    "🔗 **Jump to Giveaway:** {link}"
                )
                raw_template = cfg.get("winner_message") or default_msg
                
                formatted_desc = raw_template.replace("{winners}", mentions_str)\
                                             .replace("{winner}", mentions_str)\
                                             .replace("{prize}", prize)\
                                             .replace("{host}", host_display)\
                                             .replace("{link}", jump_url)\
                                             .replace("{entries}", str(len(entries)))
                
                embed = discord.Embed(
                    title=winner_title,
                    description=formatted_desc,
                    color=discord.Color.from_rgb(245, 158, 11),  # Celebratory Amber / Gold
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name=f"{emoji_prize} Prize", value=f"**{prize}**", inline=True)
                embed.add_field(name=f"{emoji_host} Hosted By", value=host_display, inline=True)
                embed.add_field(name=f"{emoji_entries} Total Entries", value=f"**{len(entries)}**", inline=True)
                embed.set_footer(text="Friday Giveaway Engine • Concluded", icon_url=guild.icon.url if guild.icon else None)
                
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="View Giveaway Message", url=jump_url, emoji="🔗", style=discord.ButtonStyle.link))
                
                default_ping = f"🎉 **Congratulations** {mentions_str}! You won **{prize}**! {emoji_prize}"
                raw_ping = cfg.get("winner_ping") or default_ping
                ping_content = raw_ping.replace("{winners}", mentions_str)\
                                       .replace("{winner}", mentions_str)\
                                       .replace("{prize}", prize)\
                                       .replace("{emoji_prize}", emoji_prize)\
                                       .replace("{host}", host_display)
                await channel.send(content=ping_content, embed=embed, view=view)
            else:
                gid_str = str(guild_id)
                cr = getattr(db, "custom_responses", {}).get(gid_str, {})
                raw_no_entries = cfg.get("no_entries_message") or cr.get("gw_no_entries_response") or "The giveaway for **{prize}** has ended with **0 entries**.\nNo winners could be selected."
                desc_text = (
                    raw_no_entries
                    .replace("{prize}", prize)
                    .replace("{host}", host_display)
                    .replace("{link}", jump_url)
                    .replace("{server}", guild.name)
                )
                raw_title = cfg.get("no_entries_title") or "⚠️ Giveaway Concluded • No Entries"
                embed = discord.Embed(
                    title=raw_title.replace("{prize}", prize),
                    description=desc_text,
                    color=discord.Color.from_rgb(107, 114, 128),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text="Friday Giveaway Engine • Concluded", icon_url=guild.icon.url if guild.icon else None)
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="View Giveaway Message", url=jump_url, emoji="🔗", style=discord.ButtonStyle.link))
                await channel.send(embed=embed, view=view)
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
                    f"**Sponsored by:** {host_display}"
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

    @app_commands.command(name="gsetup", description="Configure Friday Giveaway channels (Broadcast, Approvals, Logs)")
    @app_commands.default_permissions(manage_guild=True)
    async def gsetup(self, interaction: discord.Interaction):
        """Interactive setup wizard for giveaway channels — slash command only, no prefix."""
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🛡️ Only server administrators can configure the giveaway system.", ephemeral=True)
            return

        embed = discord.Embed(
            title="◈ Friday Giveaway Engine • Setup Wizard ◈",
            description=(
                "Friday needs **3 channels** to run giveaways:\n\n"
                "📢 **Broadcast** — public, members enter giveaways here\n"
                "🛡️ **Approvals** — private, staff review member requests\n"
                "📜 **Logs** — private, records all winners & rerolls\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Choose below — Friday can **auto-create** them, or you can **link** existing ones."
            ),
            color=discord.Color.from_rgb(99, 102, 241)
        )
        await interaction.response.send_message(embed=embed, view=SetupWizardView(), ephemeral=True)

    @app_commands.command(name="gcreate", description="Create a new giveaway (Instant for Staff, Approval Queue for Members)")
    @app_commands.describe(
        prize="The item, role, or gift to give away",
        duration="Duration of the giveaway (e.g. 10m, 1h, 2d, 1w)",
        winners="Number of winners to pick (default: 1)",
        description="Optional detailed description or rules",
        image="Optional image or GIF banner URL for the embed",
        channel="Optional channel to post in (defaults to configured giveaway channel)"
    )
    async def gcreate(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: Optional[int] = 1,
        description: Optional[str] = None,
        image: Optional[str] = None,
        channel: Optional[discord.TextChannel] = None,
        header_emoji: Optional[str] = None
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
            banner_url = image.strip() if image else ""
            req_data = {
                "request_id": request_id,
                "sponsor_id": interaction.user.id,
                "guild_id": guild.id,
                "prize": prize,
                "duration_seconds": duration_sec,
                "duration_str": duration,
                "winners_count": winners_count,
                "description": description or "",
                "image_url": banner_url,
                "header_emoji": header_emoji or cfg.get("emoji_header") or "🎉",
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
                    f"**Description:** {description or '*None provided*'}\n"
                    + (f"**Banner:** [Preview Image]({banner_url})" if banner_url else "")
                ),
                color=discord.Color.from_rgb(245, 158, 11), # Amber
                timestamp=datetime.now(timezone.utc)
            )
            if banner_url:
                app_embed.set_thumbnail(url=banner_url)
            app_embed.set_footer(text=f"Request ID: {request_id}")
            view = GiveawayApprovalView(request_id=request_id)
            await app_ch.send(embed=app_embed, view=view)

            await interaction.response.send_message(
                f"✅ Your giveaway request for **{prize}** has been submitted for staff approval in {app_ch.mention}! You'll be notified once reviewed.",
                ephemeral=True
            )
            return

        # ── 4. Branch: Administrator Direct Launch ──
        cfg = get_giveaway_config(guild.id)
        emoji_prize = cfg.get("emoji_prize", "🎁")
        emoji_host = cfg.get("emoji_host", "👑")
        emoji_winners = cfg.get("emoji_winners", "🏆")
        emoji_entries = cfg.get("emoji_entries", "🎟️")
        emoji_ends = cfg.get("emoji_ends", "⏳")

        now = time.time()
        end_time = now + duration_sec
        end_timestamp = int(end_time)
        image_url = (image.strip() if image else None) or cfg.get("default_banner")

        dot = resolve_safe_emoji(self.bot, cfg.get("emoji_bullet"), fallback="•")
        desc_body = (
            f"{dot} **Winners:** {winners_count}\n"
            f"{dot} **Ends In:** <t:{end_timestamp}:R> (<t:{end_timestamp}:f>)\n"
            f"{dot} **Hosted By:** {interaction.user.mention}\n\n"
            f"{dot} {description or 'Click the button below to participate!'}"
        )

        embed_color_hex = cfg.get("embed_color", "#5865F2")
        embed_color = parse_hex_color(embed_color_hex, default=0x5865F2)
        valid_img = validate_image_url(image_url)

        embed = discord.Embed(
            title=f"{emoji_prize} {prize} {emoji_prize}",
            description=desc_body,
            color=embed_color,
            timestamp=datetime.fromtimestamp(end_time, timezone.utc)
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if valid_img:
            embed.set_image(url=valid_img)

        ends_date_str = datetime.fromtimestamp(end_time, timezone.utc).strftime("%m/%d/%y")
        embed.set_footer(text=f"Ends • {ends_date_str}", icon_url=guild.icon.url if guild.icon else None)

        # Temporary key before message is sent
        temp_id = str(uuid.uuid4())[:8]
        temp_key = f"{guild.id}_{temp_id}"
        entry_method = str(cfg.get("entry_method", "button")).lower()
        if entry_method != "reaction":
            entry_method = "button"
        emoji_parts = cfg.get("emoji_participants", "👥")
        view = GiveawayEnterView(giveaway_key=temp_key, entry_count=0, emoji=emoji_prize, emoji_participants=emoji_parts) if entry_method == "button" else None

        emoji_header = resolve_safe_emoji(self.bot, header_emoji or cfg.get("emoji_header"), fallback="🎉")
        send_kwargs = {"content": f"{emoji_header} **New Giveaway** {emoji_header}", "embed": embed}
        if view:
            send_kwargs["view"] = view
        gw_msg = await target_channel.send(**send_kwargs)

        # Only add reaction if entry_method is 'reaction'
        if entry_method == "reaction":
            try:
                if emoji_prize.startswith("<") and emoji_prize.endswith(">"):
                    m = re.search(r":(\d+)>$", emoji_prize)
                    if m:
                        rx = self.bot.get_emoji(int(m.group(1)))
                        if rx:
                            await gw_msg.add_reaction(rx)
                        else:
                            await gw_msg.add_reaction("🎁")
                    else:
                        await gw_msg.add_reaction("🎁")
                else:
                    await gw_msg.add_reaction(emoji_prize)
            except Exception:
                try:
                    await gw_msg.add_reaction("🎁")
                except Exception:
                    pass

        real_key = f"{guild.id}_{gw_msg.id}"
        if entry_method == "button":
            real_view = GiveawayEnterView(giveaway_key=real_key, entry_count=0, emoji=emoji_prize, emoji_participants=emoji_parts)
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
            "description": description or "",
            "image_url": valid_img or "",
            "embed_color": embed_color_hex
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
            jump_url = f"https://discord.com/channels/{interaction.guild_id}/{channel.id}/{clean_id}"
            
            cfg = get_giveaway_config(interaction.guild_id)
            reroll_title = cfg.get("reroll_title") or "🎲 GIVEAWAY REROLLED! 🎲"
            emoji_prize = cfg.get("emoji_prize", "🎁")
            emoji_winners = cfg.get("emoji_winners", "🏆")
            default_reroll_msg = (
                f"> 🥳 New winner selected! Congratulations {{winners}}! You won **{{prize}}**! {emoji_prize}\n\n"
                "🔗 **Jump to Giveaway:** {link}"
            )
            raw_reroll_msg = cfg.get("reroll_message") or default_reroll_msg
            
            formatted_reroll = raw_reroll_msg.replace("{winners}", mentions_str)\
                                             .replace("{winner}", mentions_str)\
                                             .replace("{prize}", prize)\
                                             .replace("{host}", interaction.user.mention)\
                                             .replace("{link}", jump_url)\
                                             .replace("{entries}", str(len(entries)))
            
            embed = discord.Embed(
                title=reroll_title,
                description=formatted_reroll,
                color=discord.Color.from_rgb(245, 158, 11),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name=f"{emoji_prize} Prize", value=f"**{prize}**", inline=True)
            embed.add_field(name="🎲 Rerolled By", value=interaction.user.mention, inline=True)
            embed.add_field(name=f"{emoji_winners} New Winner(s)", value=mentions_str, inline=True)
            embed.set_footer(text="Friday Giveaway Engine • Reroll", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
            
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="View Giveaway Message", url=jump_url, emoji="🔗", style=discord.ButtonStyle.link))
            
            default_reroll_ping = f"🎲 **Giveaway Rerolled!** Congratulations {mentions_str}!"
            raw_reroll_ping = cfg.get("reroll_ping") or default_reroll_ping
            ping_content = raw_reroll_ping.replace("{winners}", mentions_str)\
                                          .replace("{winner}", mentions_str)\
                                          .replace("{prize}", prize)\
                                          .replace("{emoji_prize}", emoji_prize)
            await channel.send(content=ping_content, embed=embed, view=view)

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
            cfg = get_giveaway_config(interaction.guild_id)
            dot = resolve_safe_emoji(self.bot, cfg.get("emoji_bullet"), fallback="•")
            embed.add_field(
                name=f"🎉 {gw.get('prize')}",
                value=(
                    f"{dot} **Channel:** <#{ch_id}>\n"
                    f"{dot} **Winners:** {gw.get('winners_count', 1)}\n"
                    f"{dot} **Entries:** {entries_count}\n"
                    f"{dot} **Ends:** <t:{end_ts}:R>\n"
                    f"{dot} [Jump to Giveaway]({link})"
                ),
                inline=False
            )

        embed.set_footer(text=f"Total Active Giveaways: {len(active)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))

