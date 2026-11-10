import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List, Dict, Any
import datetime
import math
import io
import unicodedata
import aiohttp
from PIL import Image, ImageDraw
from database import db
from emoji_utils import replace_plain_emojis
from font_utils import clean_display_name, get_unicode_font

def draw_rounded_rect(draw, bounds, radius, fill=None, outline=None, width=1):
    x1, y1, x2, y2 = bounds
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill, outline=outline, width=width)

class InviteTracker(commands.Cog):
    """
    Advanced Invite Tracker Module:
    - Tracks Regular, Left, Fake, and Bonus invites: Total = Regular + Bonus - Left - Fake.
    - Caches guild invites in memory and diffs on member join.
    - Anti-fake detection (accounts < 3 days old).
    - Syncs with Web Dashboard and supports custom embed announcements with visual server emojis.
    """
    def __init__(self, bot):
        self.bot = bot
        # In-memory invite cache: guild_id -> {invite_code: uses}
        self.invites_cache = {}
        self.vanity_cache = {}

    async def cog_load(self):
        # Cache invites on cog load via background task
        import asyncio
        asyncio.create_task(self._init_cache())

    async def _init_cache(self):
        try:
            await self.bot.wait_until_ready()
            await self.refresh_all_guild_invites()
        except Exception:
            pass

    async def refresh_all_guild_invites(self):
        """Builds in-memory invite cache across all guilds the bot belongs to."""
        for guild in self.bot.guilds:
            await self.cache_guild_invites(guild)

    async def cache_guild_invites(self, guild: discord.Guild):
        """Caches invites for a single guild."""
        if not guild.me.guild_permissions.manage_guild:
            return
        try:
            invs = await guild.invites()
            self.invites_cache[guild.id] = {inv.code: inv.uses for inv in invs}
            if "VANITY_URL" in guild.features:
                try:
                    vanity = await guild.vanity_invite()
                    if vanity:
                        self.vanity_cache[guild.id] = vanity.uses
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ [InviteTracker] Failed to cache invites for '{guild.name}': {e}")

    # ────────────────────────── Event Listeners ──────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        await self.refresh_all_guild_invites()

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if not invite.guild:
            return
        gid = invite.guild.id
        if gid not in self.invites_cache:
            self.invites_cache[gid] = {}
        self.invites_cache[gid][invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if not invite.guild:
            return
        gid = invite.guild.id
        if gid in self.invites_cache and invite.code in self.invites_cache[gid]:
            self.invites_cache[gid].pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if not guild:
            return
        gid_str = str(guild.id)
        mid_str = str(member.id)

        # Skip bots
        if member.bot:
            return

        inviter = None
        used_code = None
        is_vanity = False

        # Attempt to determine which invite was used by diffing cache
        if guild.me.guild_permissions.manage_guild:
            try:
                new_invites = await guild.invites()
                cached = self.invites_cache.get(guild.id, {})

                for inv in new_invites:
                    old_uses = cached.get(inv.code, 0)
                    if inv.uses > old_uses:
                        inviter = inv.inviter
                        used_code = inv.code
                        break

                # If not found, check vanity URL
                if not used_code and "VANITY_URL" in guild.features:
                    try:
                        vanity = await guild.vanity_invite()
                        if vanity:
                            old_vanity = self.vanity_cache.get(guild.id, 0)
                            if vanity.uses > old_vanity:
                                is_vanity = True
                                used_code = vanity.code
                                self.vanity_cache[guild.id] = vanity.uses
                    except Exception:
                        pass

                # Update in-memory cache
                self.invites_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
            except Exception as e:
                print(f"⚠️ [InviteTracker] Error checking invites on join: {e}")

        # Anti-Fake check: Account age < 3 days (259200 seconds)
        now = datetime.datetime.now(datetime.timezone.utc)
        created_at = member.created_at
        account_age_sec = (now - created_at).total_seconds()
        is_fake = account_age_sec < (3 * 86400)

        # Update database records
        if gid_str not in db.invite_counts:
            db.invite_counts[gid_str] = {}
        if gid_str not in db.invite_history:
            db.invite_history[gid_str] = {}

        inviter_id_str = str(inviter.id) if inviter else None

        if inviter and not is_vanity:
            if inviter_id_str not in db.invite_counts[gid_str]:
                db.invite_counts[gid_str][inviter_id_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

            if is_fake:
                db.invite_counts[gid_str][inviter_id_str]["fake"] += 1
            else:
                db.invite_counts[gid_str][inviter_id_str]["regular"] += 1

        # Store member history
        db.invite_history[gid_str][mid_str] = {
            "inviter_id": inviter_id_str,
            "code": used_code or ("vanity" if is_vanity else "unknown"),
            "is_fake": is_fake,
            "joined_at": now.isoformat()
        }
        db.save_data()

        # Send notification to configured invite channel
        cfg = db.invite_tracker.get(gid_str, {})
        if cfg.get("enabled", True):
            channel_id = cfg.get("log_channel")
            if channel_id:
                try:
                    ch = guild.get_channel(int(channel_id))
                    if ch:
                        await self.send_join_notification(ch, member, inviter, used_code, is_fake, is_vanity)
                except Exception as e:
                    print(f"⚠️ [InviteTracker] Failed to send join notification: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        if not guild:
            return
        gid_str = str(guild.id)
        mid_str = str(member.id)

        history = db.invite_history.get(gid_str, {}).get(mid_str)
        inviter_id = history.get("inviter_id") if history else None
        is_fake = history.get("is_fake", False) if history else False

        inviter = None
        if inviter_id and not is_fake:
            if gid_str in db.invite_counts and inviter_id in db.invite_counts[gid_str]:
                db.invite_counts[gid_str][inviter_id]["left"] += 1
                db.save_data()
            try:
                inviter = guild.get_member(int(inviter_id))
            except Exception:
                pass

        cfg = db.invite_tracker.get(gid_str, {})
        if cfg.get("enabled", True) and cfg.get("log_channel"):
            try:
                ch = guild.get_channel(int(cfg["log_channel"]))
                if ch:
                    await self.send_leave_notification(ch, member, inviter)
            except Exception as e:
                print(f"⚠️ [InviteTracker] Failed to send leave notification: {e}")

    def get_user_invites(self, guild_id: int, user_id: int) -> dict:
        """Returns {regular, left, fake, bonus, total} for a user."""
        gid_str, uid_str = str(guild_id), str(user_id)
        counts = db.invite_counts.get(gid_str, {}).get(uid_str, {"regular": 0, "left": 0, "fake": 0, "bonus": 0})
        reg = counts.get("regular", 0)
        left = counts.get("left", 0)
        fake = counts.get("fake", 0)
        bonus = counts.get("bonus", 0)
        total = reg + bonus - left - fake
        return {
            "regular": reg,
            "left": left,
            "fake": fake,
            "bonus": bonus,
            "total": total
        }

    async def send_join_notification(self, channel: discord.TextChannel, member: discord.Member, inviter: discord.Member, code: str, is_fake: bool, is_vanity: bool):
        gid_str = str(member.guild.id)
        cfg = db.invite_tracker.get(gid_str, {})

        inv_stats = self.get_user_invites(member.guild.id, inviter.id) if inviter else {"total": 0, "regular": 0, "left": 0, "fake": 0, "bonus": 0}
        
        inviter_mention = inviter.mention if inviter else ("Vanity URL" if is_vanity else "Unknown")
        inviter_name = inviter.name if inviter else ("Vanity" if is_vanity else "Unknown")
        
        # Default template
        default_tpl = (
            "👋 Welcome {user} to **{guild}**!\n"
            "Invited by {inviter} (Code: `{code}`).\n"
            "📈 {inviter_name} now has **{invites}** invites (**{regular}** regular, **{bonus}** bonus, **{left}** left, **{fake}** fake)!"
        )
        template = cfg.get("join_msg") or default_tpl
        formatted = template.replace("{user}", member.mention) \
                            .replace("{user.name}", member.name) \
                            .replace("{guild}", member.guild.name) \
                            .replace("{inviter}", inviter_mention) \
                            .replace("{inviter.name}", inviter_name) \
                            .replace("{code}", code or "N/A") \
                            .replace("{invites}", str(inv_stats["total"])) \
                            .replace("{regular}", str(inv_stats["regular"])) \
                            .replace("{bonus}", str(inv_stats["bonus"])) \
                            .replace("{left}", str(inv_stats["left"])) \
                            .replace("{fake}", str(inv_stats["fake"])) \
                            .replace("{total_members}", str(member.guild.member_count))

        formatted = replace_plain_emojis(formatted, self.bot, guild=member.guild)

        if cfg.get("embed", True):
            color = int(cfg.get("embed_color", "5865F2").replace("#", ""), 16)
            raw_title = cfg.get("embed_title", "📥 Member Joined")
            title = replace_plain_emojis(raw_title, self.bot, guild=member.guild)
            embed = discord.Embed(
                title=title,
                description=formatted,
                color=color
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            
            # Custom Banner Image or Animated GIF
            banner = cfg.get("banner_url") or cfg.get("banner")
            if banner:
                embed.set_image(url=banner)

            if is_fake:
                embed.set_footer(text="⚠️ Suspected alt / fresh account (< 3 days old)")
            else:
                embed.set_footer(text=f"Member #{member.guild.member_count} • Timezone: IST")
            await channel.send(embed=embed)
        else:
            await channel.send(formatted)

    async def send_test_notification(self, channel: discord.TextChannel, user: discord.Member, cfg: dict = None, msg_type: str = "join"):
        """Dispatches an authentic test invite notification card to verify emojis, markdown, and banner."""
        if cfg is None:
            cfg = db.invite_tracker.get(str(channel.guild.id), {})

        default_tpl = (
            "👋 Welcome {user} to **{guild}**!\n"
            "Invited by {inviter} (Code: `{code}`).\n"
            "📈 {inviter.name} now has **{invites}** invites (**{regular}** regular, **{bonus}** bonus, **{left}** left, **{fake}** fake)!"
        )
        template = cfg.get("join_msg") if msg_type == "join" else cfg.get("leave_msg")
        if not template:
            template = default_tpl

        formatted = template.replace("{user}", user.mention) \
                            .replace("{user.name}", user.name) \
                            .replace("{guild}", channel.guild.name) \
                            .replace("{inviter}", channel.guild.me.mention) \
                            .replace("{inviter.name}", channel.guild.me.name) \
                            .replace("{code}", "friday-vip") \
                            .replace("{invites}", "12") \
                            .replace("{regular}", "10") \
                            .replace("{bonus}", "3") \
                            .replace("{left}", "1") \
                            .replace("{fake}", "0") \
                            .replace("{total_members}", str(channel.guild.member_count))

        formatted = replace_plain_emojis(formatted, self.bot, guild=channel.guild)

        if cfg.get("embed", True):
            raw_title = cfg.get("embed_title", "📥 Member Joined")
            title = replace_plain_emojis(raw_title, self.bot, guild=channel.guild)
            color = int(cfg.get("embed_color", "5865F2").replace("#", ""), 16)
            embed = discord.Embed(
                title=f"{title} (Test Card)",
                description=formatted,
                color=color
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            banner = cfg.get("banner_url") or cfg.get("banner")
            if banner:
                embed.set_image(url=banner)
            embed.set_footer(text=f"Test Simulation • Member #{channel.guild.member_count} • Timezone: IST")
            await channel.send(embed=embed)
        else:
            await channel.send(formatted)

    async def send_leave_notification(self, channel: discord.TextChannel, member: discord.Member, inviter: discord.Member):
        gid_str = str(member.guild.id)
        cfg = db.invite_tracker.get(gid_str, {})
        inv_stats = self.get_user_invites(member.guild.id, inviter.id) if inviter else {"total": 0, "regular": 0, "left": 0, "fake": 0, "bonus": 0}
        
        inviter_mention = inviter.mention if inviter else "Unknown"
        inviter_name = inviter.name if inviter else "Unknown"

        default_leave = "📤 **{user.name}** left the server. They were invited by {inviter}. ({inviter_name} now has **{invites}** invites)."
        template = cfg.get("leave_msg") or default_leave
        formatted = template.replace("{user}", member.mention) \
                            .replace("{user.name}", member.name) \
                            .replace("{guild}", member.guild.name) \
                            .replace("{inviter}", inviter_mention) \
                            .replace("{inviter.name}", inviter_name) \
                            .replace("{invites}", str(inv_stats["total"])) \
                            .replace("{regular}", str(inv_stats["regular"])) \
                            .replace("{bonus}", str(inv_stats["bonus"])) \
                            .replace("{left}", str(inv_stats["left"])) \
                            .replace("{fake}", str(inv_stats["fake"])) \
                            .replace("{total_members}", str(member.guild.member_count))

        formatted = replace_plain_emojis(formatted, self.bot, guild=member.guild)

        if cfg.get("embed", True):
            embed = discord.Embed(
                title="📤 Member Left",
                description=formatted,
                color=0xED4245
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)
        else:
            await channel.send(formatted)

    async def fetch_avatar(self, target, size: int = 110) -> Image.Image:
        """Helper to fetch and circle-mask an avatar or server icon, or return a default colored circle."""
        icon_url = None
        if hasattr(target, "display_avatar") and target.display_avatar:
            try:
                icon_url = str(target.display_avatar.with_format("png").with_size(128).url)
            except Exception:
                icon_url = str(target.display_avatar.url)
        elif hasattr(target, "icon") and target.icon:
            try:
                icon_url = str(target.icon.with_format("png").with_size(128).url)
            except Exception:
                icon_url = str(target.icon.url)

        if icon_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(icon_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            av_raw = Image.open(io.BytesIO(data)).convert("RGBA")
                            av_resized = av_raw.resize((size, size), Image.Resampling.LANCZOS)
                            mask = Image.new("L", (size, size), 0)
                            ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
                            output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                            output.paste(av_resized, (0, 0), mask)
                            return output
            except Exception:
                pass

        # Fallback circle
        av_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(av_img)
        d.ellipse((0, 0, size - 1, size - 1), fill=(70, 75, 90, 255), outline=(90, 95, 115, 255), width=2)
        return av_img

    def render_invite_leaderboard_card(
        self,
        guild_name: str,
        guild_icon: Image.Image,
        page: int,
        total_pages: int,
        total_inviters: int,
        members_data: list,  # [(rank, name, username, av_img, total, reg, bonus, left, fake), ...]
        max_invites: int = 1
    ) -> io.BytesIO:
        """Renders high-resolution 1020x640 graphic Invite leaderboard card with 10 members in a 2-column layout."""
        W, H = 1020, 640
        img = Image.new("RGBA", (W, H), (19, 20, 23, 255))
        draw = ImageDraw.Draw(img)

        # Outer Container
        draw_rounded_rect(draw, (12, 12, W - 12, H - 12), radius=26, fill=(28, 30, 36, 255), outline=(42, 45, 54, 255), width=2)

        font_title = get_unicode_font(22, bold=True)
        font_sub = get_unicode_font(13)
        font_pill = get_unicode_font(12, bold=True)
        font_name = get_unicode_font(14, bold=True)
        font_user = get_unicode_font(11)
        font_rank = get_unicode_font(13, bold=True)
        font_cnt = get_unicode_font(13, bold=True)
        font_breakdown = get_unicode_font(10, bold=True)
        font_footer = get_unicode_font(11)
        font_footer_bold = get_unicode_font(11, bold=True)

        # Header
        header_x, header_y = 38, 34
        if guild_icon:
            try:
                icon_resized = guild_icon.convert("RGBA").resize((60, 60), Image.Resampling.LANCZOS)
                mask = Image.new("L", (60, 60), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, 60, 60), fill=255)
                img.paste(icon_resized, (header_x, header_y), mask)
                draw.ellipse((header_x, header_y, header_x + 60, header_y + 60), outline=(55, 60, 72, 255), width=2)
            except Exception:
                pass

        text_x = header_x + 74
        draw.text((text_x, header_y + 6), clean_display_name(guild_name, max_len=28), font=font_title, fill=(255, 255, 255, 255))
        draw.text((text_x, header_y + 34), "Server Invites Leaderboard", font=font_sub, fill=(142, 146, 155, 255))

        # Status pills
        pills = [
            f"PAGE {page} OF {total_pages}",
            f"{total_inviters:,} Total Inviters",
            "INVITE RANKINGS"
        ]
        pill_right = W - 38
        for p in reversed(pills):
            bbox = font_pill.getbbox(p)
            pw = (bbox[2] - bbox[0]) + 24
            px = pill_right - pw
            py = header_y + 14
            draw_rounded_rect(draw, (px, py, px + pw, py + 32), radius=16, fill=(38, 41, 49, 255), outline=(52, 56, 67, 255), width=1)
            draw.text((px + 12, py + 8), p, font=font_pill, fill=(240, 242, 245, 255))
            pill_right = px - 10

        col_w = 460
        col1_x = 38
        col2_x = 522
        start_y = 114
        row_h = 80
        spacing = 14

        m_dict = {m[0]: m for m in members_data}
        start_rank = (page - 1) * 10 + 1

        for slot_idx in range(10):
            current_rank = start_rank + slot_idx
            col = 0 if slot_idx < 5 else 1
            row = slot_idx % 5
            cx = col1_x if col == 0 else col2_x
            cy = start_y + row * (row_h + spacing)

            draw_rounded_rect(draw, (cx, cy, cx + col_w, cy + row_h), radius=14, fill=(35, 38, 46, 255), outline=(48, 52, 63, 255), width=1)

            if current_rank in m_dict:
                _, name_str, user_str, av_img, total_inv, reg_val, bns_val, left_val, fake_val = m_dict[current_rank]

                ratio = max(0.02, min(1.0, total_inv / max(1, max_invites)))
                fill_w = int(col_w * ratio)
                if fill_w > 0:
                    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    od = ImageDraw.Draw(overlay)
                    draw_rounded_rect(od, (cx, cy, cx + fill_w, cy + row_h), radius=14, fill=(99, 102, 241, 24))
                    img = Image.alpha_composite(img, overlay)
                    draw = ImageDraw.Draw(img)

                if current_rank == 1:
                    r_fill, r_out, r_txt = (60, 45, 15, 255), (217, 119, 6, 255), (245, 158, 11, 255)
                elif current_rank == 2:
                    r_fill, r_out, r_txt = (40, 45, 55, 255), (148, 163, 184, 255), (203, 213, 225, 255)
                elif current_rank == 3:
                    r_fill, r_out, r_txt = (55, 30, 15, 255), (234, 88, 12, 255), (249, 115, 22, 255)
                else:
                    r_fill, r_out, r_txt = (28, 30, 36, 255), (45, 48, 58, 255), (130, 135, 148, 255)

                rx, ry, rw, rh = cx + 12, cy + 18, 36, 44
                draw_rounded_rect(draw, (rx, ry, rx + rw, ry + rh), radius=8, fill=r_fill, outline=r_out, width=1)
                r_str = f"#{current_rank}"
                rb = font_rank.getbbox(r_str)
                draw.text((rx + (rw - (rb[2] - rb[0])) // 2, ry + (rh - (rb[3] - rb[1])) // 2), r_str, font=font_rank, fill=r_txt)

                ax, ay, asz = rx + rw + 12, cy + 15, 50
                if av_img:
                    try:
                        av_thumb = av_img.convert("RGBA").resize((asz, asz), Image.Resampling.LANCZOS)
                        img.paste(av_thumb, (ax, ay), av_thumb)
                        draw.ellipse((ax, ay, ax + asz, ay + asz), outline=(52, 56, 68, 255), width=2)
                    except Exception:
                        pass

                nx = ax + asz + 12
                clean_name = clean_display_name(name_str, max_len=18)
                clean_handle = clean_display_name(user_str, max_len=16)
                draw.text((nx, cy + 16), clean_name, font=font_name, fill=(255, 255, 255, 255))
                draw.text((nx, cy + 36), f"@{clean_handle}", font=font_user, fill=(140, 144, 155, 255))

                bd_text = f"+{reg_val} reg • +{bns_val} bns • -{left_val} left • -{fake_val} fake"
                draw.text((nx, cy + 52), bd_text, font=font_breakdown, fill=(115, 120, 135, 255))

                inv_str = f"{total_inv:,} invites" if total_inv != 1 else "1 invite"
                tb = font_cnt.getbbox(inv_str)
                tw = (tb[2] - tb[0]) + 18
                tx = cx + col_w - tw - 12
                ty = cy + 24
                draw_rounded_rect(draw, (tx, ty, tx + tw, ty + 30), radius=8, fill=(45, 48, 58, 255), outline=(62, 68, 82, 255), width=1)
                draw.text((tx + 9, ty + 7), inv_str, font=font_cnt, fill=(99, 102, 241, 255))
            else:
                draw.text((cx + 20, cy + (row_h // 2) - 8), f"#{current_rank}  —  Unclaimed", font=font_user, fill=(75, 80, 92, 255))

        footer_y = H - 34
        draw.text((38, footer_y), f"Server Invites Leaderboard • Page {page} of {total_pages} • Timezone: IST", font=font_footer, fill=(115, 120, 130, 255))
        f_brand = "Powered by Friday"
        fbb = font_footer_bold.getbbox(f_brand)
        draw.text((W - 38 - (fbb[2] - fbb[0]), footer_y), f_brand, font=font_footer_bold, fill=(140, 145, 155, 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf

    # ────────────────────────── Slash Commands ──────────────────────────

    @app_commands.command(name="invites", description="Check your or another member's invite statistics.")
    @app_commands.describe(member="Member to inspect (defaults to yourself)")
    async def invites(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        stats = self.get_user_invites(interaction.guild.id, target.id)

        embed = discord.Embed(
            title=f"📨 Invite Summary • {clean_display_name(target.display_name)}",
            color=0x5865F2,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        net_total = stats["total"]
        embed.add_field(name="✨ Total Net Invites", value=f"**{net_total}**", inline=False)
        embed.add_field(name="📥 Regular", value=f"`{stats['regular']}`", inline=True)
        embed.add_field(name="🎁 Bonus", value=f"`{stats['bonus']}`", inline=True)
        embed.add_field(name="📤 Left", value=f"`{stats['left']}`", inline=True)
        embed.add_field(name="⚠️ Fake (<3d)", value=f"`{stats['fake']}`", inline=True)

        embed.set_footer(text=f"Requested by @{clean_display_name(interaction.user.name)}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="invite_leaderboard", description="View custom graphic leaderboard of top inviters in the server.")
    async def invite_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        gid = str(interaction.guild.id)
        all_counts = db.invite_counts.get(gid, {})

        leaderboard_data = []
        for uid_str, data in all_counts.items():
            reg = data.get("regular", 0)
            bon = data.get("bonus", 0)
            left = data.get("left", 0)
            fake = data.get("fake", 0)
            total = reg + bon - left - fake
            leaderboard_data.append((uid_str, total, reg, bon, left, fake))

        leaderboard_data.sort(key=lambda x: x[1], reverse=True)

        if not leaderboard_data:
            await interaction.followup.send("No invite statistics recorded yet!", ephemeral=True)
            return

        view = InviteLeaderboardView(self, interaction.guild, leaderboard_data, current_page=1, per_page=10)
        file = await view.generate_card_file()
        await interaction.followup.send(file=file, view=view)

    # ────────────────────────── Admin Subgroup ──────────────────────────

    invite_admin = app_commands.Group(name="invite_admin", description="Configure and manage the server invite tracker.")

    @invite_admin.command(name="add", description="Add bonus or fake invites to a member.")
    @app_commands.describe(
        member="Target member",
        amount="Number of invites to add",
        invite_type="Type of invite to adjust (Bonus or Fake)"
    )
    @app_commands.choices(invite_type=[
        app_commands.Choice(name="Bonus Invites (Default)", value="bonus"),
        app_commands.Choice(name="Fake Invites", value="fake"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def add_invites(self, interaction: discord.Interaction, member: discord.Member, amount: int, invite_type: str = "bonus"):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        gid_str, uid_str = str(interaction.guild.id), str(member.id)
        if gid_str not in db.invite_counts: db.invite_counts[gid_str] = {}
        if uid_str not in db.invite_counts[gid_str]:
            db.invite_counts[gid_str][uid_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

        target_field = "fake" if invite_type == "fake" else "bonus"
        db.invite_counts[gid_str][uid_str][target_field] += amount
        db.save_data()
        stats = self.get_user_invites(interaction.guild.id, member.id)
        await interaction.response.send_message(
            f"✅ Added **{amount}** {target_field} invites to {member.mention}. "
            f"New stats: **{stats['total']}** net invites (Regular: {stats['regular']}, Bonus: {stats['bonus']}, Left: {stats['left']}, Fake: {stats['fake']})."
        )

    @invite_admin.command(name="remove", description="Remove bonus or fake invites from a member.")
    @app_commands.describe(
        member="Target member",
        amount="Number of invites to remove",
        invite_type="Type of invite to adjust (Bonus or Fake)"
    )
    @app_commands.choices(invite_type=[
        app_commands.Choice(name="Bonus Invites (Default)", value="bonus"),
        app_commands.Choice(name="Fake Invites", value="fake"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def remove_invites(self, interaction: discord.Interaction, member: discord.Member, amount: int, invite_type: str = "bonus"):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        gid_str, uid_str = str(interaction.guild.id), str(member.id)
        if gid_str not in db.invite_counts: db.invite_counts[gid_str] = {}
        if uid_str not in db.invite_counts[gid_str]:
            db.invite_counts[gid_str][uid_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

        target_field = "fake" if invite_type == "fake" else "bonus"
        db.invite_counts[gid_str][uid_str][target_field] = max(0, db.invite_counts[gid_str][uid_str][target_field] - amount)
        db.save_data()
        stats = self.get_user_invites(interaction.guild.id, member.id)
        await interaction.response.send_message(
            f"✅ Removed **{amount}** {target_field} invites from {member.mention}. "
            f"New stats: **{stats['total']}** net invites (Regular: {stats['regular']}, Bonus: {stats['bonus']}, Left: {stats['left']}, Fake: {stats['fake']})."
        )

    @invite_admin.command(name="set", description="Manually set exact invite numbers for a member.")
    @app_commands.describe(
        member="Target member",
        regular="Regular invites (optional)",
        fake="Fake invites (optional)",
        bonus="Bonus invites (optional)",
        left="Left invites (optional)"
    )
    @app_commands.default_permissions(administrator=True)
    async def set_invites(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        regular: Optional[int] = None,
        fake: Optional[int] = None,
        bonus: Optional[int] = None,
        left: Optional[int] = None
    ):
        gid_str, uid_str = str(interaction.guild.id), str(member.id)
        if gid_str not in db.invite_counts: db.invite_counts[gid_str] = {}
        if uid_str not in db.invite_counts[gid_str]:
            db.invite_counts[gid_str][uid_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

        rec = db.invite_counts[gid_str][uid_str]
        if regular is not None: rec["regular"] = max(0, regular)
        if fake is not None: rec["fake"] = max(0, fake)
        if bonus is not None: rec["bonus"] = max(0, bonus)
        if left is not None: rec["left"] = max(0, left)

        db.save_data()
        stats = self.get_user_invites(interaction.guild.id, member.id)
        await interaction.response.send_message(
            f"✅ Updated invites for {member.mention}:\n"
            f"> **Net Total:** `{stats['total']}`\n"
            f"> **Regular:** `{rec['regular']}` • **Fake:** `{rec['fake']}` • **Bonus:** `{rec['bonus']}` • **Left:** `{rec['left']}`"
        )

    @invite_admin.command(name="clear", description="Reset all invite records for a member.")
    @app_commands.default_permissions(administrator=True)
    async def clear_invites(self, interaction: discord.Interaction, member: discord.Member):
        gid_str, uid_str = str(interaction.guild.id), str(member.id)
        if gid_str in db.invite_counts and uid_str in db.invite_counts[gid_str]:
            db.invite_counts[gid_str][uid_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}
            db.save_data()
        await interaction.response.send_message(f"🧹 Successfully reset invite counts for {member.mention}.")

    @invite_admin.command(name="channel", description="Set the channel where invite join/leave logs are posted.")
    @app_commands.default_permissions(administrator=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid_str = str(interaction.guild.id)
        if gid_str not in db.invite_tracker: db.invite_tracker[gid_str] = {}
        db.invite_tracker[gid_str]["log_channel"] = str(channel.id)
        db.invite_tracker[gid_str]["enabled"] = True
        db.save_data()
        await interaction.response.send_message(f"✅ Invite log channel set to {channel.mention}.")

    @invite_admin.command(name="message", description="Configure the custom join message template.")
    @app_commands.default_permissions(administrator=True)
    async def set_join_msg(self, interaction: discord.Interaction, template: str):
        gid_str = str(interaction.guild.id)
        if gid_str not in db.invite_tracker: db.invite_tracker[gid_str] = {}
        db.invite_tracker[gid_str]["join_msg"] = template
        db.save_data()
        await interaction.response.send_message("✅ Custom invite join message template updated successfully!")

    @invite_admin.command(name="leave_message", description="Configure the custom leave message template.")
    @app_commands.default_permissions(administrator=True)
    async def set_leave_msg(self, interaction: discord.Interaction, template: str):
        gid_str = str(interaction.guild.id)
        if gid_str not in db.invite_tracker: db.invite_tracker[gid_str] = {}
        db.invite_tracker[gid_str]["leave_msg"] = template
        db.save_data()
        await interaction.response.send_message("✅ Custom invite leave message template updated successfully!")


class InviteLeaderboardView(discord.ui.View):
    """Interactive pagination view for Invite Graphic Leaderboard."""
    def __init__(self, cog, guild: discord.Guild, data: list, current_page: int = 1, per_page: int = 10):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.data = data
        self.current_page = current_page
        self.per_page = per_page
        self.total_pages = max(1, math.ceil(len(data) / per_page))
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = (self.current_page <= 1)
        self.next_btn.disabled = (self.current_page >= self.total_pages)
        self.page_indicator.label = f"Page {self.current_page} / {self.total_pages}"

    async def generate_card_file(self) -> discord.File:
        offset = (self.current_page - 1) * self.per_page
        page_items = self.data[offset:offset + self.per_page]

        async def fetch_item(rank_num, uid_str, total, reg, bon, left, fake):
            mem = self.guild.get_member(int(uid_str))
            name = mem.display_name if mem else f"User {uid_str[-4:]}"
            username = mem.name if mem else f"id_{uid_str}"
            av = await self.cog.fetch_avatar(mem or uid_str, size=60)
            return (rank_num, name, username, av, total, reg, bon, left, fake)

        import asyncio
        tasks_list = [
            fetch_item(offset + i, uid_str, total, reg, bon, left, fake)
            for i, (uid_str, total, reg, bon, left, fake) in enumerate(page_items, start=1)
        ]
        members_data = await asyncio.gather(*tasks_list) if tasks_list else []

        max_inv = self.data[0][1] if self.data else 1
        guild_icon = await self.cog.fetch_avatar(self.guild, size=60)

        buf = self.cog.render_invite_leaderboard_card(
            guild_name=self.guild.name,
            guild_icon=guild_icon,
            page=self.current_page,
            total_pages=self.total_pages,
            total_inviters=len(self.data),
            members_data=members_data,
            max_invites=max_inv
        )
        return discord.File(fp=buf, filename=f"invite_leaderboard_{self.guild.id}.png")

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, custom_id="inv_lb_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.current_page > 1:
            self.current_page -= 1
        self.update_buttons()
        file = await self.generate_card_file()
        await interaction.edit_original_response(attachments=[file], view=self)

    @discord.ui.button(label="Page 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, custom_id="inv_lb_page")
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="inv_lb_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.current_page < self.total_pages:
            self.current_page += 1
        self.update_buttons()
        file = await self.generate_card_file()
        await interaction.edit_original_response(attachments=[file], view=self)


async def setup(bot):
    await bot.add_cog(InviteTracker(bot))

