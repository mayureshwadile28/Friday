import os
import io
import re
import colorsys
import asyncio
import unicodedata
from typing import Optional, Tuple
from datetime import datetime
import pytz
import aiohttp
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageStat

from database import db
from font_utils import get_unicode_font, clean_display_name, safe_channel_label
from emoji_utils import replace_plain_emojis

# ───────────────────── Card Helpers ─────────────────────

def draw_rounded_rect(draw, bbox, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)

def draw_luminous_text(draw, pos, text, font, fill, shadow_fill=(0, 0, 0, 180), offset=(1, 1)):
    """Draw luminous text with a soft shadow offset rather than jagged PIL stroke."""
    x, y = pos
    if shadow_fill:
        draw.text((x + offset[0], y + offset[1]), text, font=font, fill=shadow_fill)
    draw.text((x, y), text, font=font, fill=fill)

def resolve_booster_background(bg_path: str) -> Optional[str]:
    """Robustly resolve booster card background on Windows and Linux VPS."""
    if not bg_path or not isinstance(bg_path, str):
        return None
    if os.path.exists(bg_path):
        return bg_path
    base = os.path.basename(bg_path)
    candidates = [
        os.path.join(os.getcwd(), "dashboard", "static", "uploads", "booster_backgrounds", base),
        os.path.join(os.getcwd(), "dashboard", "static", "uploads", "rank_backgrounds", base),
        os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "uploads", "booster_backgrounds", base),
        os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "uploads", "rank_backgrounds", base),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


class BoosterPerks(commands.Cog):
    """
    Server Booster Perks & Celebration Cog.
    Manages custom booster announcements, glassmorphic celebration cards,
    and automatic reward role assignment/revocation.
    Operates strictly via the Web Dashboard (ZERO in-server slash commands).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _extract_accent_color(self, bg_img: Optional[Image.Image]) -> Tuple[int, int, int]:
        """
        Extracts the most visually vibrant (saturated) non-dark accent color from a background image.
        Returns an (R, G, B) tuple. Falls back to Discord Booster Magenta (244, 127, 255).
        """
        if not bg_img:
            return (244, 127, 255)
        try:
            small = bg_img.convert("RGB").resize((60, 40), Image.Resampling.LANCZOS)
            quantized = small.quantize(colors=16, method=Image.Quantize.MEDIANCUT).convert("RGB")
            colors = quantized.getcolors(maxcolors=256) or []
            best_rgb = None
            best_score = -1.0
            for count, (r, g, b) in colors:
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                # Filter out dark/near-black (<0.22) and desaturated grey (<0.28)
                if v < 0.22 or s < 0.28:
                    continue
                score = (s * 1.5 + v) * (count ** 0.5)
                if score > best_score:
                    best_score = score
                    best_rgb = (r, g, b)
            if best_rgb:
                return best_rgb
        except Exception:
            pass
        return (244, 127, 255)

    async def fetch_avatar(self, target, size: int = 120) -> Image.Image:
        """Helper to fetch and circle-mask a member avatar with smooth anti-aliasing."""
        icon_url = None
        if hasattr(target, "display_avatar") and target.display_avatar:
            try:
                icon_url = str(target.display_avatar.with_format("png").with_size(256).url)
            except Exception:
                icon_url = str(target.display_avatar.url)
        elif hasattr(target, "avatar") and target.avatar:
            try:
                icon_url = str(target.avatar.with_format("png").with_size(256).url)
            except Exception:
                icon_url = str(target.avatar.url)

        if icon_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(icon_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            av_raw = Image.open(io.BytesIO(data)).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
                            mask = Image.new("L", (size, size), 0)
                            mask_draw = ImageDraw.Draw(mask)
                            mask_draw.ellipse((0, 0, size, size), fill=255)
                            circle_av = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                            circle_av.paste(av_raw, (0, 0), mask)
                            return circle_av
            except Exception:
                pass

        # Fallback circle avatar
        fallback = Image.new("RGBA", (size, size), (244, 127, 255, 255))
        f_draw = ImageDraw.Draw(fallback)
        raw_name = getattr(target, "display_name", "") or getattr(target, "name", "B")
        initial = (raw_name[0] if raw_name else "B").upper()
        f_font = get_unicode_font(int(size * 0.45), bold=True)
        f_draw.text((size // 2, size // 2), initial, font=f_font, fill=(255, 255, 255), anchor="mm")
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        circle_fb = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        circle_fb.paste(fallback, (0, 0), mask)
        return circle_fb

    def get_tier_milestone_info(self, boost_count: int, tier: int) -> Tuple[int, int, float, str]:
        """
        Returns (current_boosts, next_milestone_target, progress_fraction, milestone_name)
        Tier 0: 0 -> 2 boosts (Tier 1)
        Tier 1: 2 -> 7 boosts (Tier 2)
        Tier 2: 7 -> 14 boosts (Tier 3)
        Tier 3: 14+ boosts (Max Tier Reached)
        """
        if tier == 0:
            target = 2
            frac = min(1.0, max(0.0, boost_count / 2.0))
            name = "Tier 1"
        elif tier == 1:
            target = 7
            frac = min(1.0, max(0.0, (boost_count - 2) / (7 - 2))) if (7 - 2) > 0 else 1.0
            name = "Tier 2"
        elif tier == 2:
            target = 14
            frac = min(1.0, max(0.0, (boost_count - 7) / (14 - 7))) if (14 - 7) > 0 else 1.0
            name = "Tier 3"
        else:
            target = 14
            frac = 1.0
            name = "Max Tier Reached"
        return boost_count, target, frac, name

    async def generate_booster_card(
        self,
        member: discord.Member,
        guild: discord.Guild,
        custom_bg: Optional[str] = None
    ) -> discord.File:
        """
        Renders an ultra-crisp 840x300 glassmorphic server booster celebration card.
        Rendered at 2× (1680x600) with Lanczos downscale for razor-sharp typography and anti-aliasing.
        Features:
        - Slightly blurred & dimmed custom wallpaper keeping background recognizable while guaranteeing text legibility.
        - Adaptive text & accent colors extracted from the wallpaper.
        - Frosted glass container with shine border.
        - Glowing booster avatar with double concentric aura and boost badge.
        - Server boost tier badge, total boost count, and milestone progression bar.
        - Celebratory plaque and IST timestamp.
        """
        SCALE = 2
        W, H = 840 * SCALE, 300 * SCALE
        RADIUS_CARD = 22 * SCALE
        gid = str(guild.id) if guild else "0"

        # ── 1. Resolve & prepare wallpaper ──
        raw_bg = None
        bg_img = None
        container_alpha = 32
        panel_alpha = 48

        # Check explicitly passed bg, or guild's booster wallpaper, or fallback rank wallpaper
        bg_candidate = custom_bg or db.booster_backgrounds.get(gid) or db.rank_card_backgrounds.get(gid)
        resolved_path = resolve_booster_background(bg_candidate)

        if resolved_path and os.path.exists(resolved_path):
            try:
                loaded = Image.open(resolved_path).convert("RGBA")
                w_ratio = W / loaded.width
                h_ratio = H / loaded.height
                ratio = max(w_ratio, h_ratio)
                new_w = int(loaded.width * ratio)
                new_h = int(loaded.height * ratio)
                resized = loaded.resize((new_w, new_h), Image.Resampling.LANCZOS)
                crop_x = (new_w - W) // 2
                crop_y = (new_h - H) // 2
                raw_bg = resized.crop((crop_x, crop_y, crop_x + W, crop_y + H))

                # Subtle blur (3 * SCALE) so wallpaper remains recognizable
                _blurred = raw_bg.filter(ImageFilter.GaussianBlur(radius=3 * SCALE))

                # Dynamic luminance adaptation: dims bright backdrops to keep text 100% readable
                mean_lum = ImageStat.Stat(raw_bg.convert('L')).mean[0]
                if mean_lum > 120:
                    dim_factor = max(0.65, 0.90 - ((mean_lum - 120) / 200.0))
                    container_alpha = 36
                    panel_alpha = 56
                elif mean_lum > 85:
                    dim_factor = 0.78
                    container_alpha = 32
                    panel_alpha = 50
                else:
                    dim_factor = 0.88
                    container_alpha = 26
                    panel_alpha = 42

                bg_img = ImageEnhance.Brightness(_blurred).enhance(dim_factor)
            except Exception as e:
                print(f"⚠️ Booster wallpaper loading error: {e}")
                raw_bg = bg_img = None

        # ── 2. Adaptive color extraction ──
        accent_rgb = self._extract_accent_color(raw_bg) if raw_bg else (244, 127, 255)
        ar, ag, ab = accent_rgb

        # Boost saturation and brightness for luminous primary text and badges
        h_a, s_a, v_a = colorsys.rgb_to_hsv(ar / 255, ag / 255, ab / 255)
        text_r, text_g, text_b = colorsys.hsv_to_rgb(h_a, min(s_a, 0.65), max(v_a, 0.96))
        tar, tag, tab = int(text_r * 255), int(text_g * 255), int(text_b * 255)

        # Secondary text color: soft luminous warm tone adapted from accent
        sec_r, sec_g, sec_b = colorsys.hsv_to_rgb(h_a, min(s_a * 0.25, 0.20), 0.92)
        star, stag, stab = int(sec_r * 255), int(sec_g * 255), int(sec_b * 255)

        if not bg_img:
            # High-end default dark celestial canvas with nebula glows
            bg_img = Image.new("RGBA", (W, H), (14, 16, 22, 255))
            d_bg = ImageDraw.Draw(bg_img)
            # Subtle gradient mesh accents
            d_bg.ellipse((-100 * SCALE, -100 * SCALE, 300 * SCALE, 300 * SCALE), fill=(ar, ag, ab, 45))
            d_bg.ellipse((W - 240 * SCALE, H - 240 * SCALE, W + 120 * SCALE, H + 120 * SCALE), fill=(244, 114, 182, 35))
            d_bg.ellipse((W // 2 - 150 * SCALE, -80 * SCALE, W // 2 + 150 * SCALE, 220 * SCALE), fill=(147, 51, 234, 30))

        # ── 3. Frosted Glass Container Overlay ──
        card_margin = 14 * SCALE
        card_box = (card_margin, card_margin, W - card_margin, H - card_margin)

        # ── 4. Telemetry & Boost Stats ──
        boost_count = getattr(guild, "premium_subscription_count", 0) or 0
        tier = getattr(guild, "premium_tier", 0) or 0
        cur_b, target_b, prog_frac, next_milestone_name = self.get_tier_milestone_info(boost_count, tier)

        # Fonts
        font_title = get_unicode_font(28 * SCALE, bold=True)
        font_sub = get_unicode_font(15 * SCALE, bold=False)
        font_badge = get_unicode_font(13 * SCALE, bold=True)
        font_bar_lbl = get_unicode_font(12 * SCALE, bold=True)
        font_praise = get_unicode_font(16 * SCALE, bold=True)
        font_footer = get_unicode_font(11 * SCALE, bold=False)

        # Avatar layout coordinates
        av_size = 112 * SCALE
        av_x = card_margin + 26 * SCALE
        av_y = card_margin + 26 * SCALE

        # Text and Pill layout
        text_x = av_x + av_size + 26 * SCALE
        text_y = av_y + 4 * SCALE
        right_margin = W - card_margin - 26 * SCALE

        # Top-Right Guild Telemetry Badges
        tier_label = f"TIER {tier}" if tier > 0 else "LEVEL 0"
        tier_w = 95 * SCALE
        tier_x = right_margin - tier_w
        tier_y = text_y + 2 * SCALE

        boosts_label = f"💎 {boost_count} Boosts"
        boost_w = 120 * SCALE
        boost_x = tier_x - boost_w - 12 * SCALE

        # Booster badge pill
        pill_x = text_x
        pill_y = text_y + 58 * SCALE
        pill_w = 160 * SCALE
        pill_h = 24 * SCALE

        # Milestone Progress Bar layout
        bar_x = text_x
        bar_y = card_margin + 144 * SCALE
        bar_w = right_margin - bar_x
        bar_h = 14 * SCALE

        # Celebratory Plaque layout
        plaque_x = card_margin + 24 * SCALE
        plaque_y = card_margin + 188 * SCALE
        plaque_w = W - (card_margin + 24 * SCALE) * 2
        plaque_h = 44 * SCALE

        # ── 5. Render All Translucent Glass Panels via Overlay ──
        glass_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        god = ImageDraw.Draw(glass_overlay)

        # (a) Outer card container
        container_fill = (12, 14, 20, container_alpha) if raw_bg else (16, 18, 26, 215)
        container_border = (255, 255, 255, 75) if raw_bg else (255, 255, 255, 45)
        draw_rounded_rect(god, card_box, radius=RADIUS_CARD, fill=container_fill, outline=container_border, width=max(1, int(1.5 * SCALE)))

        # (b) Status badge pill background
        draw_rounded_rect(god, (pill_x, pill_y, pill_x + pill_w, pill_y + pill_h), radius=pill_h // 2, fill=(ar, ag, ab, 45), outline=(tar, tag, tab, 180), width=max(1, 1 * SCALE))

        # (c) Top-right tier pill background
        draw_rounded_rect(god, (tier_x, tier_y, tier_x + tier_w, tier_y + 30 * SCALE), radius=15 * SCALE, fill=(ar, ag, ab, 50), outline=(tar, tag, tab, 200), width=max(1, int(1.5 * SCALE)))

        # (d) Top-right boost count pill background
        draw_rounded_rect(god, (boost_x, tier_y, boost_x + boost_w, tier_y + 30 * SCALE), radius=15 * SCALE, fill=(20, 22, 30, 150), outline=(255, 255, 255, 60), width=max(1, 1 * SCALE))

        # (e) Progress bar track (dark translucent glass track)
        draw_rounded_rect(god, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=bar_h // 2, fill=(10, 12, 18, 120), outline=(255, 255, 255, 40), width=1)

        # (f) Progress bar fill
        fill_w = max(int(bar_h), int(bar_w * prog_frac))
        if fill_w > 0:
            draw_rounded_rect(god, (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=bar_h // 2, fill=(ar, ag, ab, 220))
            # Subtle gradient sheen on top half of bar
            god.rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h // 2), fill=(255, 255, 255, 45))

        # (g) Celebratory Plaque
        plaque_fill = (12, 14, 22, panel_alpha) if raw_bg else (20, 22, 32, 180)
        draw_rounded_rect(god, (plaque_x, plaque_y, plaque_x + plaque_w, plaque_y + plaque_h), radius=14 * SCALE, fill=plaque_fill, outline=(tar, tag, tab, 140), width=max(1, int(1.5 * SCALE)))

        # Composite all glass panels onto background
        img = Image.alpha_composite(bg_img, glass_overlay)
        draw = ImageDraw.Draw(img)

        # ── 6. Booster Avatar with Double Glow Rings ──
        # Outer glowing auras
        draw.ellipse((av_x - 6 * SCALE, av_y - 6 * SCALE, av_x + av_size + 6 * SCALE, av_y + av_size + 6 * SCALE), outline=(ar, ag, ab, 70), width=max(1, 2 * SCALE))
        draw.ellipse((av_x - 3 * SCALE, av_y - 3 * SCALE, av_x + av_size + 3 * SCALE, av_y + av_size + 3 * SCALE), outline=(tar, tag, tab, 210), width=max(1, int(2.5 * SCALE)))

        av_img = await self.fetch_avatar(member, size=av_size)
        img.paste(av_img, (av_x, av_y), av_img)

        # Boost badge on avatar bottom-right
        badge_dia = 32 * SCALE
        bdg_x = av_x + av_size - badge_dia + 4 * SCALE
        bdg_y = av_y + av_size - badge_dia + 4 * SCALE
        draw.ellipse((bdg_x, bdg_y, bdg_x + badge_dia, bdg_y + badge_dia), fill=(18, 20, 26, 240), outline=(tar, tag, tab, 220), width=max(1, int(1.5 * SCALE)))
        f_badge_icon = get_unicode_font(15 * SCALE, bold=True)
        draw.text((bdg_x + badge_dia // 2, bdg_y + badge_dia // 2), "🚀", font=f_badge_icon, fill=(tar, tag, tab), anchor="mm")

        # ── 7. Header Typography & Badges ──
        raw_display = getattr(member, "display_name", None) or member.name
        safe_name = clean_display_name(raw_display, max_len=20)
        draw_luminous_text(draw, (text_x, text_y), safe_name, font=font_title, fill=(star, stag, stab), shadow_fill=(0, 0, 0, 200), offset=(2 * SCALE, 2 * SCALE))

        # Username Tag
        user_tag = f"@{member.name}"
        draw_luminous_text(draw, (text_x, text_y + 34 * SCALE), user_tag, font=font_sub, fill=(tar, tag, tab), shadow_fill=(0, 0, 0, 160), offset=(1 * SCALE, 1 * SCALE))

        # Status badge pill text
        draw.text((pill_x + pill_w // 2, pill_y + pill_h // 2), "🚀 SERVER BOOSTER", font=font_badge, fill=(tar, tag, tab), anchor="mm")

        # Top-Right Badges Text
        draw.text((tier_x + tier_w // 2, tier_y + 15 * SCALE), tier_label, font=font_badge, fill=(tar, tag, tab), anchor="mm")
        draw.text((boost_x + boost_w // 2, tier_y + 15 * SCALE), boosts_label, font=font_badge, fill=(star, stag, stab), anchor="mm")

        # ── 8. Milestone Progression Bar Label ──
        pct_display = int(prog_frac * 100)
        if tier >= 3:
            prog_label = f"MAX TIER ACHIEVED • Total {boost_count} Boosts Active (100%)"
        else:
            prog_label = f"MILESTONE PROGRESS: {boost_count} / {target_b} Boosts towards {next_milestone_name} ({pct_display}%)"

        draw_luminous_text(draw, (bar_x, bar_y - 20 * SCALE), prog_label, font=font_bar_lbl, fill=(tar, tag, tab), shadow_fill=(0, 0, 0, 160), offset=(1 * SCALE, 1 * SCALE))

        # ── 9. Celebratory Plaque Text ──
        praise_msg = "✨ HUGE THANKS FOR EMPOWERING OUR SERVER! ✨"
        draw.text((plaque_x + plaque_w // 2, plaque_y + plaque_h // 2), praise_msg, font=font_praise, fill=(tar, tag, tab), anchor="mm")

        # ── 10. Footer & IST Timestamp ──
        ist = pytz.timezone('Asia/Kolkata')
        ist_now = datetime.now(ist).strftime("%b %d, %Y • %I:%M %p IST")
        guild_name = clean_display_name(guild.name if guild else "Community", max_len=24)
        footer_left = f"{guild_name} • {ist_now}"
        footer_y = H - card_margin - 22 * SCALE

        draw_luminous_text(draw, (plaque_x + 4 * SCALE, footer_y), footer_left, font=font_footer, fill=(star, stag, stab), shadow_fill=(0, 0, 0, 140))
        draw_luminous_text(draw, (plaque_x + plaque_w - 110 * SCALE, footer_y), "Powered by Friday", font=font_footer, fill=(tar, tag, tab), shadow_fill=(0, 0, 0, 140))

        # ── 11. Downscale to 840x300 for butter-smooth anti-aliasing ──
        final_img = img.resize((840, 300), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        final_img.convert("RGBA").save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return discord.File(fp=buf, filename=f"booster_{member.id}.png")

    # ───────────────────── Discord Event Listeners ─────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        Listens for server boost events and unboost events.
        Grants reward role, generates celebratory card, dispatches channel announcement, and sends optional DM.
        """
        guild = after.guild
        gid = str(guild.id)
        cfg = db.booster_perks.get(gid, {})
        if not cfg.get("enabled", True):
            return

        # Boost status detection
        was_boosting = before.premium_since is not None
        is_boosting = after.premium_since is not None

        # 1. Member started boosting
        if not was_boosting and is_boosting:
            print(f"🚀 New booster detected in {guild.name}: {after.name} ({after.id})")
            reward_role_id = cfg.get("reward_role_id")
            if reward_role_id:
                try:
                    role_id_int = int(reward_role_id)
                    role = guild.get_role(role_id_int)
                    if role and role not in after.roles:
                        await after.add_roles(role, reason="Friday Server Booster Perks: Reward Role Granted")
                        print(f"✅ Assigned booster reward role '{role.name}' to {after.name}")
                except Exception as e:
                    print(f"⚠️ Failed to grant booster role in {guild.name}: {e}")

            # Send announcement
            try:
                await self.dispatch_booster_announcement(guild, after)
            except Exception as e:
                print(f"⚠️ Failed to dispatch booster announcement in {guild.name}: {e}")

            # Send DM thank-you if configured
            if cfg.get("dm_enabled", True):
                try:
                    dm_tmpl = cfg.get("dm_message") or (
                        "💜 Huge thank you for boosting **{guild}**, {user}!\n"
                        "You've unlocked exclusive booster perks and our deepest appreciation! ✨"
                    )
                    role_str = ""
                    if reward_role_id:
                        r = guild.get_role(int(reward_role_id))
                        if r:
                            role_str = r.name
                    formatted_dm = dm_tmpl.replace("{user}", after.mention) \
                                          .replace("{username}", after.name) \
                                          .replace("{guild}", guild.name) \
                                          .replace("{boosts}", str(guild.premium_subscription_count or 0)) \
                                          .replace("{tier}", str(guild.premium_tier or 0)) \
                                          .replace("{reward_role}", role_str or "Server Booster")
                    formatted_dm = replace_plain_emojis(formatted_dm, self.bot, guild_id=gid, guild=guild)
                    await after.send(formatted_dm)
                except Exception as e:
                    print(f"ℹ️ Could not send booster thank-you DM to {after.name}: {e}")

        # 2. Member stopped boosting (Unboosted)
        elif was_boosting and not is_boosting:
            print(f"📉 Member unboosted in {guild.name}: {after.name} ({after.id})")
            if cfg.get("remove_role_on_unboost", True):
                reward_role_id = cfg.get("reward_role_id")
                if reward_role_id:
                    try:
                        role_id_int = int(reward_role_id)
                        role = guild.get_role(role_id_int)
                        if role and role in after.roles:
                            await after.remove_roles(role, reason="Friday Server Booster Perks: Member unboosted")
                            print(f"🗑️ Removed booster reward role '{role.name}' from {after.name}")
                    except Exception as e:
                        print(f"⚠️ Failed to remove booster role from {after.name}: {e}")

    # ───────────────────── Dispatch Announcement ─────────────────────

    async def dispatch_booster_announcement(
        self,
        guild: discord.Guild,
        member: discord.Member,
        is_test: bool = False,
        target_channel: Optional[discord.TextChannel] = None
    ) -> bool:
        """
        Formats and dispatches the booster celebration message and/or glassmorphic card.
        Can be triggered by live on_member_update event or from Dashboard Live Test.
        """
        gid = str(guild.id)
        cfg = db.booster_perks.get(gid, {})
        channel_id = str(target_channel.id) if target_channel else str(cfg.get("channel_id", ""))
        if not channel_id:
            return False

        chan = target_channel or guild.get_channel(int(channel_id))
        if not chan:
            return False

        mode = cfg.get("mode", "both")  # "both", "image", "text"

        # Resolve reward role name for variable replacement
        reward_role_id = cfg.get("reward_role_id")
        role_mention = "@Booster"
        if reward_role_id:
            try:
                r = guild.get_role(int(reward_role_id))
                if r:
                    role_mention = r.mention
            except Exception:
                pass

        default_msg = (
            "🚀 Huge thank you to {user} for boosting **{guild}**! "
            "You unlocked {reward_role} perks! ✨"
        )
        msg_template = cfg.get("announcement_message") or default_msg
        formatted_msg = msg_template.replace("{user}", member.mention) \
                                    .replace("{username}", member.name) \
                                    .replace("{guild}", guild.name) \
                                    .replace("{boosts}", str(guild.premium_subscription_count or 0)) \
                                    .replace("{tier}", str(guild.premium_tier or 0)) \
                                    .replace("{reward_role}", role_mention)

        formatted_msg = replace_plain_emojis(formatted_msg, self.bot, guild_id=gid, guild=guild)

        card_file = None
        if mode in ("both", "image"):
            try:
                card_file = await self.generate_booster_card(member, guild)
            except Exception as e:
                print(f"⚠️ Booster card generation error: {e}")

        # Send to Discord channel
        if mode == "image" and card_file:
            await chan.send(file=card_file)
        elif mode == "both" and card_file:
            await chan.send(content=formatted_msg, file=card_file)
        else:
            await chan.send(content=formatted_msg)

        return True


async def setup(bot: commands.Bot):
    await bot.add_cog(BoosterPerks(bot))
