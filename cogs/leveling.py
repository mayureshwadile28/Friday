import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List, Dict, Any
import time
import random
import io
import math
import os
import unicodedata
import asyncio
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from easy_pil import Font
from database import db
from font_utils import get_unicode_font, clean_display_name, safe_channel_label

def draw_rounded_rect(draw, bbox, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)

def resolve_card_background(bg_path: str) -> Optional[str]:
    """Robustly resolve card background on local machine and Linux VM."""
    if not bg_path or not isinstance(bg_path, str):
        return None
    if os.path.exists(bg_path):
        return bg_path
    base = os.path.basename(bg_path)
    cand1 = os.path.join(os.getcwd(), "dashboard", "static", "uploads", "rank_backgrounds", base)
    if os.path.exists(cand1):
        return cand1
    cand2 = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "uploads", "rank_backgrounds", base)
    if os.path.exists(cand2):
        return os.path.abspath(cand2)
    return None

class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.xp_cooldowns = {}

    def get_xp_requirement(self, level: int) -> int:
        """
        Standard balanced XP formula (Arcane/Mee6 style):
        XP required for level L -> L+1: 5*(L^2) + 50*L + 100
        Level 0 -> 100 XP (~5 msgs)
        Level 1 -> 155 XP (~8 msgs)
        Level 2 -> 220 XP (~11 msgs)
        Level 3 -> 295 XP (~15 msgs)
        """
        return int(5 * (level ** 2) + 50 * level + 100)

    @app_commands.command(name="level_setup", description="Activate leveling and set the channel for Level Up updates.")
    @app_commands.default_permissions(manage_channels=True)
    async def level_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        db.level_channels[gid] = str(channel.id)
        db.save_data()
        await interaction.response.send_message(f"✅ Leveling system activated! Updates will now be posted in {channel.mention}.", ephemeral=True)

    @app_commands.command(name="rank", description="Check your current Level, XP, and progression card.")
    async def rank(self, interaction: discord.Interaction, user: discord.Member = None):
        await interaction.response.defer() 
        user = user or interaction.user
        gid = str(interaction.guild.id)
        uid = str(user.id)
        
        if gid not in db.xp_data or uid not in db.xp_data[gid]:
            await interaction.followup.send(f"{clean_display_name(user.display_name)} has no XP recorded yet! Send some messages to start leveling up.")
            return

        user_stats = db.xp_data[gid][uid]
        # Only rank current active members
        active_users = []
        for u_id, s in db.xp_data[gid].items():
            if interaction.guild.get_member(int(u_id)):
                active_users.append((u_id, s))
        sorted_users = sorted(active_users, key=lambda item: (item[1].get('level', 0), item[1].get('xp', 0)), reverse=True)
        try:
            rank_pos = [i[0] for i in sorted_users].index(uid) + 1
        except ValueError:
            rank_pos = len(sorted_users)
        
        current_xp = user_stats["xp"]
        current_level = user_stats["level"]
        next_xp = self.get_xp_requirement(current_level)
        percentage = min(100.0, max(2.0, (current_xp / max(1, next_xp)) * 100.0))

        # Check total messages from Activity cog DB if loaded
        total_messages = 0
        voice_str = "0m"
        act_cog = self.bot.get_cog("Activity")
        if act_cog:
            try:
                stats = act_cog.get_member_stats(interaction.guild.id, user.id)
                total_messages = stats.get("lifetime", 0)
                voice_str = act_cog.format_duration(stats.get("voice_lifetime", 0))
            except Exception:
                pass

        card_file = await self.generate_rank_card(
            user=user,
            rank_pos=rank_pos,
            total_members=len(sorted_users),
            current_level=current_level,
            current_xp=current_xp,
            next_xp=next_xp,
            percentage=percentage,
            total_messages=total_messages,
            voice_str=voice_str
        )
        await interaction.followup.send(file=card_file)

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
                import aiohttp
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

        fallback = Image.new("RGBA", (size, size), (88, 101, 242, 255))
        f_draw = ImageDraw.Draw(fallback)
        raw_name = getattr(target, "display_name", "") or getattr(target, "name", "U")
        clean_name = clean_display_name(raw_name)
        name_letter = clean_name[0].upper() if clean_name else "U"
        f_draw.text((size // 2 - 10, size // 2 - 16), name_letter, font=get_unicode_font(size // 3, bold=True), fill=(255, 255, 255, 255))
        return fallback

    async def generate_rank_card(
        self,
        user: discord.Member,
        rank_pos: int,
        total_members: int,
        current_level: int,
        current_xp: int,
        next_xp: int,
        percentage: float,
        total_messages: int = 0,
        voice_str: str = "0m"
    ) -> discord.File:
        """
        Renders a sleek, compact 840x270 dark glassmorphic rank card.
        Supports custom wallpapers from the dashboard with an adaptive dark frosted glass
        container ensuring all text and the dynamic progress bar stay 100% legible and vibrant.
        Accent color adapts to custom wallpaper using the same palette extractor as the level-up card.
        """
        import colorsys
        W, H = 840, 270
        gid = str(user.guild.id)
        
        # Check if a custom rank card background is configured via dashboard
        raw_bg = None
        bg_img = None
        custom_bg = resolve_card_background(db.rank_card_backgrounds.get(gid) or db.rank_backgrounds.get(gid))
        if custom_bg:
            try:
                loaded = Image.open(custom_bg).convert("RGBA")
                # Cover crop to W x H
                w_ratio = W / loaded.width
                h_ratio = H / loaded.height
                ratio = max(w_ratio, h_ratio)
                new_w = int(loaded.width * ratio)
                new_h = int(loaded.height * ratio)
                resized = loaded.resize((new_w, new_h), Image.Resampling.LANCZOS)
                crop_x = (new_w - W) // 2
                crop_y = (new_h - H) // 2
                raw_bg = resized.crop((crop_x, crop_y, crop_x + W, crop_y + H))
                _blurred = raw_bg.filter(ImageFilter.GaussianBlur(radius=3))
                bg_img = ImageEnhance.Brightness(_blurred).enhance(0.92)
            except Exception:
                raw_bg = bg_img = None

        # Extract adaptive accent color from wallpaper (or fallback indigo)
        accent_rgb = self._extract_accent_color(raw_bg) if raw_bg else (129, 140, 248)
        ar, ag, ab = accent_rgb
        # Boost for text legibility
        h_a, s_a, v_a = colorsys.rgb_to_hsv(ar / 255, ag / 255, ab / 255)
        text_r, text_g, text_b = colorsys.hsv_to_rgb(h_a, min(s_a, 0.65), max(v_a, 0.95))
        tar, tag, tab = int(text_r * 255), int(text_g * 255), int(text_b * 255)

        if not bg_img:
            # High-end default dark canvas
            bg_img = Image.new("RGBA", (W, H), (18, 20, 24, 255))
            d_bg = ImageDraw.Draw(bg_img)
            # Subtle gradient mesh accents
            d_bg.ellipse((-80, -80, 240, 240), fill=(ar, ag, ab, 35))
            d_bg.ellipse((W - 180, H - 180, W + 100, H + 100), fill=(ar // 2, ag // 2, ab, 25))

        # Frosted Glass Overlay (guarantees WCAG AAA contrast for all text & elements)
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        # Inner dark card container: subtle transparency when custom wallpaper is active
        container_fill = (10, 12, 18, 55) if custom_bg else (18, 20, 26, 215)
        draw_rounded_rect(od, (10, 10, W - 10, H - 10), radius=22, fill=container_fill, outline=(255, 255, 255, 60) if custom_bg else (255, 255, 255, 38), width=1)
        img = Image.alpha_composite(bg_img, overlay)
        draw = ImageDraw.Draw(img)

        # Fonts - using hinted unicode fonts to ensure uniform kerning with zero letter gaps
        font_title = get_unicode_font(24, bold=True)
        font_sub = get_unicode_font(12, bold=False)
        font_badge = get_unicode_font(11, bold=True)
        font_xp_num = get_unicode_font(14, bold=True)
        font_stat_val = get_unicode_font(16, bold=True)
        font_stat_lbl = get_unicode_font(11, bold=True)

        # Avatar on left (100x100)
        av_x, av_y, av_size = 36, 36, 100
        av_img = await self.fetch_avatar(user, size=av_size)
        img.paste(av_img, (av_x, av_y), av_img)
        draw.ellipse((av_x, av_y, av_x + av_size, av_y + av_size), outline=(tar, tag, tab, 255), width=3)

        # Member Info
        text_x = av_x + av_size + 20
        draw.text((text_x, 38), clean_display_name(user.display_name, max_len=20), font=font_title, fill=(255, 255, 255, 255), stroke_width=2 if custom_bg else 0, stroke_fill=(0, 0, 0, 200) if custom_bg else None)
        joined_str = user.joined_at.strftime("%B %d, %Y") if user.joined_at else "Unknown"
        draw.text((text_x, 70), f"@{clean_display_name(user.name, max_len=16)} • Joined {joined_str}", font=font_sub, fill=(235, 240, 250, 240) if custom_bg else (160, 165, 175, 255), stroke_width=1 if custom_bg else 0, stroke_fill=(0, 0, 0, 180) if custom_bg else None)

        # Top-right Badges — accent badge adapts to wallpaper
        top_role = user.top_role.name if (user.top_role and user.top_role.name != "@everyone") else "Member"
        badges = [
            (f"RANK #{rank_pos}", (245, 158, 11) if rank_pos <= 3 else (150, 155, 166)),
            (f"LEVEL {current_level}", (tar, tag, tab)),
            (clean_display_name(top_role, max_len=14), (ar, ag, ab))
        ]
        bx = W - 36
        for b_text, b_col in reversed(badges):
            bbox = font_badge.getbbox(b_text)
            bw = (bbox[2] - bbox[0]) + 20
            bpx = bx - bw
            draw_rounded_rect(draw, (bpx, 38, bpx + bw, 66), radius=10, fill=(14, 16, 22, 60) if custom_bg else (24, 27, 36, 170), outline=b_col + (190,), width=1)
            draw.text((bpx + 10, 45), b_text, font=font_badge, fill=b_col + (255,), stroke_width=1 if custom_bg else 0, stroke_fill=(0, 0, 0, 180) if custom_bg else None)
            bx = bpx - 8

        # Dynamic XP Progress Bar Section
        bar_x = text_x
        bar_y = 112
        bar_w = W - 36 - bar_x
        bar_h = 20

        draw.text((bar_x, 92), "EXP PROGRESSION", font=font_stat_lbl, fill=(tar, tag, tab, 255), stroke_width=1 if custom_bg else 0, stroke_fill=(0, 0, 0, 180) if custom_bg else None)
        xp_str = f"{current_xp:,} / {next_xp:,} XP ({percentage:.1f}%)"
        xb = font_xp_num.getbbox(xp_str)
        draw.text((bar_x + bar_w - (xb[2] - xb[0]), 90), xp_str, font=font_xp_num, fill=(255, 255, 255, 255), stroke_width=1 if custom_bg else 0, stroke_fill=(0, 0, 0, 180) if custom_bg else None)

        # Background track
        draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=10, fill=(0, 0, 0, 100) if custom_bg else (20, 23, 30, 200), outline=(tar, tag, tab, 60), width=1)
        fill_w = int(bar_w * (percentage / 100.0))
        if fill_w > 0:
            # Gradient fill on progress bar using adaptive accent color
            draw_rounded_rect(draw, (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=10, fill=(ar, ag, ab, 255))

        # Bottom 3 Telemetry Stat Cards - Frosted Glassmorphism
        stat_y = 152
        stat_h = 86
        sw = (bar_w - 20) // 3
        stat_items = [
            ("TOTAL MESSAGES", f"{total_messages:,} msgs", "Recorded chat volume"),
            ("VOICE DURATION", voice_str, "Recorded voice time"),
            ("SERVER STANDING", f"Top {max(1, round((rank_pos / max(1, total_members)) * 100))}%", f"Rank #{rank_pos} of {total_members}")
        ]

        # Render glassmorphic translucent containers via alpha composite
        glass_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        god = ImageDraw.Draw(glass_overlay)
        for idx, (lbl, val, sub) in enumerate(stat_items):
            sx = bar_x + idx * (sw + 10)
            draw_rounded_rect(god, (sx, stat_y, sx + sw, stat_y + stat_h), radius=12, fill=(14, 16, 22, 55) if custom_bg else (28, 30, 38, 255), outline=(255, 255, 255, 60) if custom_bg else (ar, ag, ab, 55), width=1)
        img = Image.alpha_composite(img, glass_overlay)
        draw = ImageDraw.Draw(img)

        # Draw text over glass containers — brighter labels + adaptive accent
        for idx, (lbl, val, sub) in enumerate(stat_items):
            sx = bar_x + idx * (sw + 10)
            draw.text((sx + 14, stat_y + 12), lbl, font=font_stat_lbl, fill=(tar, tag, tab, 255), stroke_width=1 if custom_bg else 0, stroke_fill=(0, 0, 0, 180) if custom_bg else None)
            draw.text((sx + 14, stat_y + 30), val, font=font_stat_val, fill=(255, 255, 255, 255), stroke_width=2 if custom_bg else 0, stroke_fill=(0, 0, 0, 200) if custom_bg else None)
            draw.text((sx + 14, stat_y + 57), sub, font=font_sub, fill=(220, 225, 235, 240) if custom_bg else (200, 205, 215, 255), stroke_width=1 if custom_bg else 0, stroke_fill=(0, 0, 0, 180) if custom_bg else None)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return discord.File(fp=buf, filename=f"rankcard_{user.id}.png")

    def _extract_accent_color(self, bg_img: "Image.Image") -> tuple:
        """
        Extracts the most visually vibrant (saturated) non-dark accent color from a background image.
        Returns an (R, G, B) tuple suitable for text and progress bar accent.
        Falls back to cyan (56, 189, 248) if no vibrant color is found.
        """
        import colorsys
        try:
            small = bg_img.convert("RGB").resize((60, 40), Image.Resampling.LANCZOS)
            quantized = small.quantize(colors=12).convert("RGB")
            counts = {}
            for px in quantized.getdata():
                counts[px] = counts.get(px, 0) + 1

            best_color = None
            best_score = -1
            for color, count in counts.items():
                r, g, b = color
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                # Skip near-black and near-white colors
                if v < 0.25 or (s < 0.15 and v > 0.85):
                    continue
                # Score = saturation * brightness weight * count
                score = s * (0.5 + v * 0.5) * (count ** 0.5)
                if score > best_score:
                    best_score = score
                    best_color = color

            if best_color:
                r, g, b = best_color
                # Ensure it's bright enough for legibility
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                v = max(v, 0.75)  # Minimum brightness
                s = max(s, 0.45)  # Minimum saturation
                rr, gg, bb = colorsys.hsv_to_rgb(h, s, v)
                return (int(rr * 255), int(gg * 255), int(bb * 255))
        except Exception:
            pass
        return (56, 189, 248)  # Fallback cyan

    async def generate_levelup_card(self, member: discord.Member, old_level: int, new_level: int, guild_id: str = None, xp_after: int = 0) -> discord.File:
        """
        Generates a high-quality 580x160 level-up card rendered at 2× for crisp anti-aliasing.
        - Wallpaper fills full card; glass card border is transparent (true glassmorphism)
        - Properly anti-aliased circular avatar with glowing ring
        - Gradient progress bar with rounded capsule shape
        - Adaptive accent color extracted from wallpaper palette
        """
        import colorsys
        from PIL import ImageFilter

        # Render at 2× resolution then downscale → crisp anti-aliasing
        SCALE = 2
        W, H = 580 * SCALE, 160 * SCALE
        RADIUS_CARD = 22 * SCALE
        gid = str(guild_id) if guild_id else (
            str(member.guild.id) if hasattr(member, "guild") and member.guild else None
        )

        # ── 1. Load & prepare background wallpaper ──
        raw_bg = None
        bg_img = None
        if gid:
            custom_bg = resolve_card_background(db.levelup_card_backgrounds.get(gid))
            if custom_bg:
                try:
                    loaded = Image.open(custom_bg).convert("RGBA")
                    w_r = W / loaded.width
                    h_r = H / loaded.height
                    ratio = max(w_r, h_r)
                    nw, nh = int(loaded.width * ratio), int(loaded.height * ratio)
                    resized = loaded.resize((nw, nh), Image.Resampling.LANCZOS)
                    cx, cy = (nw - W) // 2, (nh - H) // 2
                    raw_bg = resized.crop((cx, cy, cx + W, cy + H))
                    _blurred = raw_bg.filter(ImageFilter.GaussianBlur(radius=5 * SCALE))
                    bg_img = ImageEnhance.Brightness(_blurred).enhance(0.78)
                except Exception:
                    raw_bg = bg_img = None

        # ── 2. Extract accent color from raw (unblurred) wallpaper ──
        accent_color = self._extract_accent_color(raw_bg) if raw_bg else (56, 189, 248)
        ar, ag, ab = accent_color

        # Boost accent color specifically for text to guarantee high vibrancy and brightness
        h_a, s_a, v_a = colorsys.rgb_to_hsv(ar / 255, ag / 255, ab / 255)
        text_r, text_g, text_b = colorsys.hsv_to_rgb(h_a, min(s_a, 0.65), max(v_a, 0.95))
        tar, tag, tab = int(text_r * 255), int(text_g * 255), int(text_b * 255)

        if not bg_img:
            # Default dark canvas with gradient orbs (no wallpaper)
            bg_img = Image.new("RGBA", (W, H), (18, 20, 26, 255))
            d_bg = ImageDraw.Draw(bg_img)
            d_bg.ellipse((-80, -80, 320, 320), fill=(ar, ag, ab, 50))
            d_bg.ellipse((W - 240, H - 240, W + 100, H + 100), fill=(ar // 2, ag // 2, ab, 35))

        # ── 3. Smooth frosted glass backdrop — preserves wallpaper vibrancy while guaranteeing contrast ──
        glass_backdrop = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gb_draw = ImageDraw.Draw(glass_backdrop)
        gb_draw.rounded_rectangle((6, 6, W - 6, H - 6), radius=RADIUS_CARD, fill=(10, 14, 22, 95))
        img = Image.alpha_composite(bg_img, glass_backdrop)

        # ── 4. Glass card border — TRUE glassmorphism ──
        # Border: rounded rect with ONLY outline, fill is completely transparent
        glass_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gl_draw = ImageDraw.Draw(glass_layer)
        # Outer subtle glow (wider, transparent)
        gl_draw.rounded_rectangle(
            (4, 4, W - 4, H - 4), radius=RADIUS_CARD,
            outline=(ar, ag, ab, 70), width=6
        )
        # Inner crisp accent border
        gl_draw.rounded_rectangle(
            (8, 8, W - 8, H - 8), radius=RADIUS_CARD - 4,
            outline=(tar, tag, tab, 210), width=3
        )
        img = Image.alpha_composite(img, glass_layer)

        # ── 5. Avatar — perfectly round with anti-aliased glow ring ──
        av_size = 96 * SCALE
        av_x = 28 * SCALE
        av_y = (H - av_size) // 2

        # Fetch avatar at 2× size
        av_img_raw = await self.fetch_avatar(member, size=av_size)

        # Redraw avatar mask at 2× for crisp circle edge
        av_mask = Image.new("L", (av_size, av_size), 0)
        av_mask_draw = ImageDraw.Draw(av_mask)
        av_mask_draw.ellipse((0, 0, av_size - 1, av_size - 1), fill=255)

        av_circle = Image.new("RGBA", (av_size, av_size), (0, 0, 0, 0))
        av_circle.paste(av_img_raw.convert("RGBA"), (0, 0), av_mask)

        # Glow aura ring — drawn on separate layer for anti-aliasing
        ring_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ring_draw = ImageDraw.Draw(ring_layer)
        pad = 10
        ring_draw.ellipse(
            (av_x - pad, av_y - pad, av_x + av_size + pad, av_y + av_size + pad),
            outline=(ar, ag, ab, 60), width=14
        )
        ring_draw.ellipse(
            (av_x - 4, av_y - 4, av_x + av_size + 4, av_y + av_size + 4),
            outline=(tar, tag, tab, 220), width=5
        )
        img = Image.alpha_composite(img, ring_layer)

        # Paste circular avatar over ring
        img.paste(av_circle, (av_x, av_y), av_circle)

        # ── 6. Text content with cinematic soft drop shadow and crisp outline ──
        text_x = av_x + av_size + 24 * SCALE
        content_w = W - text_x - 26 * SCALE

        font_header = get_unicode_font(31 * SCALE, bold=True)
        font_sub = get_unicode_font(15 * SCALE, bold=True)
        font_lvl_lbl = get_unicode_font(13 * SCALE, bold=True)

        m_name = clean_display_name(
            getattr(member, "display_name", None) or getattr(member, "name", "User"),
            max_len=20
        )
        lbl_old = f"LVL {old_level}"
        lbl_new = f"LVL {new_level}"
        bar_top_y = 86 * SCALE
        bar_y = 106 * SCALE
        bar_h = 22 * SCALE
        bar_r = bar_h // 2

        # Pass A: Soft blurred drop shadow layer for maximum contrast against any wallpaper
        shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(shadow_layer)
        s_draw.text((text_x, 21 * SCALE), "Level-up!", font=font_header, fill=(0, 0, 0, 200))
        s_draw.text((text_x, 59 * SCALE), f"GG @{m_name}", font=font_sub, fill=(0, 0, 0, 180))
        s_draw.text((text_x, bar_top_y), lbl_old, font=font_lvl_lbl, fill=(0, 0, 0, 180))
        rbb = font_lvl_lbl.getbbox(lbl_new)
        s_draw.text((text_x + content_w - (rbb[2] - rbb[0]), bar_top_y), lbl_new, font=font_lvl_lbl, fill=(0, 0, 0, 180))

        blurred_shadow = shadow_layer.filter(ImageFilter.GaussianBlur(radius=3 * SCALE))
        img = Image.alpha_composite(img, blurred_shadow)

        # Pass B: Ultra-bright foreground text with subtle sharpening stroke
        draw = ImageDraw.Draw(img)
        draw.text(
            (text_x, 21 * SCALE), "Level-up!",
            font=font_header, fill=(255, 255, 255, 255),
            stroke_width=SCALE, stroke_fill=(0, 0, 0, 140)
        )
        draw.text(
            (text_x, 59 * SCALE), f"GG @{m_name}",
            font=font_sub, fill=(255, 255, 255, 255),
            stroke_width=SCALE, stroke_fill=(0, 0, 0, 130)
        )
        draw.text(
            (text_x, bar_top_y), lbl_old,
            font=font_lvl_lbl, fill=(tar, tag, tab, 255),
            stroke_width=SCALE, stroke_fill=(0, 0, 0, 150)
        )
        draw.text(
            (text_x + content_w - (rbb[2] - rbb[0]), bar_top_y), lbl_new,
            font=font_lvl_lbl, fill=(255, 255, 255, 255),
            stroke_width=SCALE, stroke_fill=(0, 0, 0, 150)
        )

        # ── 7. Dynamic Progress Bar ──
        # Track (rounded dark capsule with accent border)
        draw.rounded_rectangle(
            (text_x, bar_y, text_x + content_w, bar_y + bar_h),
            radius=bar_r, fill=(12, 16, 26, 210), outline=(tar, tag, tab, 80), width=2
        )

        # Compute actual fill ratio based on XP gained since level-up (0% at brand new level)
        req_new_xp = self.get_xp_requirement(new_level)
        fill_ratio = max(0.0, min(1.0, xp_after / req_new_xp)) if req_new_xp > 0 else 0.0
        # Minimum visual fill = bar_h so the endpoint dot still renders; skip if 0%
        fill_px = max(bar_h, int(content_w * fill_ratio)) if fill_ratio > 0 else 0

        # Build gradient band image (only if there is actual fill)
        if fill_px > 0:
            grad_band = Image.new("RGBA", (fill_px, bar_h), (0, 0, 0, 0))
            for i in range(fill_px):
                t = i / max(1, fill_px - 1)
                v_g = min(1.0, v_a + (1.0 - v_a) * t * 0.6)
                s_g = s_a * (1 - t * 0.25)
                rr, gg, bb = colorsys.hsv_to_rgb(h_a, s_g, v_g)
                ImageDraw.Draw(grad_band).line(
                    [(i, 0), (i, bar_h - 1)],
                    fill=(int(rr * 255), int(gg * 255), int(bb * 255), 255)
                )

            # Clip gradient to rounded capsule shape
            fill_mask = Image.new("L", (fill_px, bar_h), 0)
            ImageDraw.Draw(fill_mask).rounded_rectangle(
                (0, 0, fill_px - 1, bar_h - 1), radius=bar_r, fill=255
            )
            grad_band.putalpha(fill_mask)

            # Paste gradient fill onto card
            img.paste(grad_band, (text_x, bar_y), grad_band)
            draw = ImageDraw.Draw(img)

            # Glowing endpoint dot
            gx = text_x + fill_px
            gr = bar_h // 2 + 2
            draw.ellipse(
                (gx - gr, bar_y + bar_h // 2 - gr, gx + gr, bar_y + bar_h // 2 + gr),
                fill=(255, 255, 255, 240)
            )
            draw.ellipse(
                (gx - gr // 2, bar_y + bar_h // 2 - gr // 2, gx + gr // 2, bar_y + bar_h // 2 + gr // 2),
                fill=(255, 255, 255, 255)
            )

        # ── 8. Downscale 2× → 1× for final crisp output ──
        final = img.resize((W // SCALE, H // SCALE), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        final.save(buf, format="PNG", optimize=False, compress_level=1)
        buf.seek(0)
        return discord.File(fp=buf, filename=f"levelup_{member.id}.png")

    def render_xp_leaderboard_card(
        self,
        guild_name: str,
        guild_icon: Image.Image,
        page: int,
        total_pages: int,
        total_members: int,
        members_data: list, # [(rank, name, username, av_img, level, xp, next_xp), ...]
        max_xp: int = 1,
        guild_id: int = None
    ) -> io.BytesIO:
        """Renders high-resolution 1020x640 graphic XP leaderboard card with 10 members in a 2-column layout."""
        W, H = 1020, 640

        # Check custom wallpaper for leaderboard
        raw_bg = None
        bg_img = None
        custom_bg = resolve_card_background(db.leaderboard_card_backgrounds.get(str(guild_id))) if guild_id else None
        if custom_bg:
            try:
                loaded = Image.open(custom_bg).convert("RGBA")
                w_r = W / loaded.width
                h_r = H / loaded.height
                ratio = max(w_r, h_r)
                nw, nh = int(loaded.width * ratio), int(loaded.height * ratio)
                resized = loaded.resize((nw, nh), Image.Resampling.LANCZOS)
                cx = (nw - W) // 2
                cy = (nh - H) // 2
                raw_bg = resized.crop((cx, cy, cx + W, cy + H))
                _blurred = raw_bg.filter(ImageFilter.GaussianBlur(radius=3))
                bg_img = ImageEnhance.Brightness(_blurred).enhance(0.92)
            except Exception:
                raw_bg = bg_img = None

        if not bg_img:
            img = Image.new("RGBA", (W, H), (19, 20, 23, 255))
        else:
            img = bg_img.copy()

        # Outer Container with Frosted Glass when wallpaper is active
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        container_fill = (10, 12, 18, 55) if raw_bg else (28, 30, 36, 255)
        draw_rounded_rect(od, (12, 12, W - 12, H - 12), radius=26, fill=container_fill, outline=(255, 255, 255, 60) if raw_bg else (42, 45, 54, 255), width=2)
        img = Image.alpha_composite(img, overlay)

        accent_color = self._extract_accent_color(raw_bg) if raw_bg else (129, 140, 248)
        import colorsys as _cs
        if raw_bg:
            _ar, _ag, _ab = accent_color
            _h, _s, _v = _cs.rgb_to_hsv(_ar/255, _ag/255, _ab/255)
            _tr, _tg, _tb = _cs.hsv_to_rgb(_h, min(_s*1.2, 1.0), max(_v, 0.95))
            text_accent = (int(_tr*255), int(_tg*255), int(_tb*255))
        else:
            text_accent = (200, 205, 215)

        # Pre-composite glassmorphic member rows layer so wallpaper shines through!
        col_w = 460
        col1_x = 38
        col2_x = 522
        start_y = 114
        row_h = 80
        spacing = 14

        panel_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel_layer)
        p_row_fill = (14, 16, 22, 55) if raw_bg else (35, 38, 46, 255)
        p_row_outline = (255, 255, 255, 60) if raw_bg else (48, 52, 63, 255)

        for slot_idx in range(10):
            col = 0 if slot_idx < 5 else 1
            row = slot_idx % 5
            cx = col1_x if col == 0 else col2_x
            cy = start_y + row * (row_h + spacing)
            draw_rounded_rect(pd, (cx, cy, cx + col_w, cy + row_h), radius=14, fill=p_row_fill, outline=p_row_outline, width=1)

        img = Image.alpha_composite(img, panel_layer)
        draw = ImageDraw.Draw(img)

        font_title = get_unicode_font(22, bold=True)
        font_sub = Font.poppins(variant="regular", size=13)
        font_pill = Font.poppins(variant="bold", size=12)
        font_name = get_unicode_font(14, bold=True)
        font_user = Font.poppins(variant="regular", size=11)
        font_rank = get_unicode_font(13, bold=True)
        font_cnt = Font.poppins(variant="bold", size=13)
        font_lvl = Font.poppins(variant="bold", size=11)
        font_footer = Font.poppins(variant="regular", size=11)
        font_footer_bold = Font.poppins(variant="bold", size=11)

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
        draw.text((text_x, header_y + 6), clean_display_name(guild_name, max_len=28), font=font_title, fill=(255, 255, 255, 255), stroke_width=2 if raw_bg else 0, stroke_fill=(0, 0, 0, 200) if raw_bg else None)
        draw.text((text_x, header_y + 34), "Server XP & Level Leaderboard", font=font_sub, fill=(235, 240, 250, 240) if raw_bg else (142, 146, 155, 255), stroke_width=1 if raw_bg else 0, stroke_fill=(0, 0, 0, 180) if raw_bg else None)

        # Status pills
        pills = [
            f"PAGE {page} OF {total_pages}",
            f"{total_members:,} Active Members",
            "XP RANKINGS"
        ]
        pill_right = W - 38
        for p in reversed(pills):
            bbox = font_pill.getbbox(p)
            pw = (bbox[2] - bbox[0]) + 24
            px = pill_right - pw
            py = header_y + 14
            draw_rounded_rect(draw, (px, py, px + pw, py + 32), radius=16, fill=(14, 16, 22, 60) if raw_bg else (38, 41, 49, 255), outline=(255, 255, 255, 60) if raw_bg else (52, 56, 67, 255), width=1)
            draw.text((px + 12, py + 8), p, font=font_pill, fill=(255, 255, 255, 255), stroke_width=1 if raw_bg else 0, stroke_fill=(0, 0, 0, 180) if raw_bg else None)
            pill_right = px - 10

        m_dict = {m[0]: m for m in members_data}
        start_rank = (page - 1) * 10 + 1

        for slot_idx in range(10):
            current_rank = start_rank + slot_idx
            col = 0 if slot_idx < 5 else 1
            row = slot_idx % 5
            cx = col1_x if col == 0 else col2_x
            cy = start_y + row * (row_h + spacing)

            if not raw_bg:
                draw_rounded_rect(draw, (cx, cy, cx + col_w, cy + row_h), radius=14, fill=(35, 38, 46, 255), outline=(48, 52, 63, 255), width=1)

            if current_rank in m_dict:
                _, name_str, user_str, av_img, lvl_val, xp_val, req_val = m_dict[current_rank]

                ratio = xp_val / max(1, max_xp)
                fill_w = int(col_w * min(1.0, max(0.02, ratio)))
                if fill_w > 0:
                    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    od = ImageDraw.Draw(overlay)
                    draw_rounded_rect(od, (cx, cy, cx + fill_w, cy + row_h), radius=14, fill=accent_color + (35,))
                    img = Image.alpha_composite(img, overlay)
                    draw = ImageDraw.Draw(img)

                if current_rank == 1:
                    r_fill, r_out, r_txt = (60, 45, 15, 255), (217, 119, 6, 255), (245, 158, 11, 255)
                elif current_rank == 2:
                    r_fill, r_out, r_txt = (40, 45, 55, 255), (148, 163, 184, 255), (203, 213, 225, 255)
                elif current_rank == 3:
                    r_fill, r_out, r_txt = (55, 30, 15, 255), (234, 88, 12, 255), (249, 115, 22, 255)
                else:
                    r_fill, r_out, r_txt = (14, 16, 22, 100) if raw_bg else (28, 30, 36, 255), (255, 255, 255, 60) if raw_bg else (46, 50, 60, 255), text_accent if raw_bg else (150, 155, 166, 255)

                draw_rounded_rect(draw, (cx + 12, cy + 24, cx + 48, cy + 56), radius=10, fill=r_fill, outline=r_out, width=1)
                r_str = f"#{current_rank}"
                rb = font_rank.getbbox(r_str)
                rx = cx + 30 - (rb[2] - rb[0]) // 2
                draw.text((rx, cy + 31), r_str, font=font_rank, fill=r_txt, stroke_width=1 if raw_bg else 0, stroke_fill=(0, 0, 0, 180) if raw_bg else None)

                # Avatar
                av_x = cx + 58
                av_y = cy + 14
                if av_img:
                    try:
                        img.paste(av_img, (av_x, av_y), av_img)
                        draw.ellipse((av_x, av_y, av_x + 52, av_y + 52), outline=(55, 60, 72, 255), width=2)
                    except Exception:
                        pass

                # Name & Username
                nx = av_x + 64
                draw.text((nx, cy + 18), clean_display_name(name_str, max_len=14), font=font_name, fill=(255, 255, 255, 255), stroke_width=1 if raw_bg else 0, stroke_fill=(0, 0, 0, 180) if raw_bg else None)
                draw.text((nx, cy + 42), f"Level {lvl_val}", font=font_lvl, fill=accent_color + (255,), stroke_width=1 if raw_bg else 0, stroke_fill=(0, 0, 0, 180) if raw_bg else None)

                # XP Count on right
                c_str = f"{xp_val:,} XP"
                cb = font_cnt.getbbox(c_str)
                draw.text((cx + col_w - 20 - (cb[2] - cb[0]), cy + 28), c_str, font=font_cnt, fill=(255, 255, 255, 255), stroke_width=1 if raw_bg else 0, stroke_fill=(0, 0, 0, 180) if raw_bg else None)
            else:
                draw.text((cx + 20, cy + 28), f"#{current_rank}  —  Unclaimed", font=font_user, fill=(120, 125, 136, 255))

        # Footer
        footer_y = H - 36
        draw.text((38, footer_y), "Server XP Leaderboard • Top Active Members", font=font_footer, fill=(180, 185, 195, 255) if raw_bg else (115, 120, 130, 255))
        fb = font_footer_bold.getbbox("Powered by Friday")
        draw.text((W - 38 - (fb[2] - fb[0]), footer_y), "Powered by Friday", font=font_footer_bold, fill=(200, 205, 215, 255) if raw_bg else (150, 155, 166, 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf

    async def generate_xp_leaderboard_file(self, guild: discord.Guild, page: int = 1, per_page: int = 10) -> discord.File:
        gid = str(guild.id)
        raw_xp = db.xp_data.get(gid, {})
        
        # Only include active members currently in the server (eliminates left/deleted accounts)
        active_users = []
        for uid, data in raw_xp.items():
            try:
                uid_int = int(uid)
            except (ValueError, TypeError):
                continue
            mem = guild.get_member(uid_int)
            if not mem:
                try:
                    mem = await guild.fetch_member(uid_int)
                except Exception:
                    mem = None
            if mem and not getattr(mem, "bot", False):
                active_users.append((uid, data, mem))

        sorted_users = sorted(active_users, key=lambda item: (item[1].get('level', 0), item[1].get('xp', 0)), reverse=True)
        total_members = len(sorted_users)
        total_pages = max(1, math.ceil(total_members / per_page))
        current_page = max(1, min(page, total_pages))
        offset = (current_page - 1) * per_page
        page_users = sorted_users[offset:offset + per_page]

        async def fetch_item(rank_num, uid, data, mem):
            name = mem.display_name
            username = mem.name
            av = await self.fetch_avatar(mem, size=52)
            lvl = data.get("level", 0)
            xp = data.get("xp", 0)
            req = self.get_xp_requirement(lvl)
            return (rank_num, name, username, av, lvl, xp, req)

        tasks = [fetch_item(offset + i, uid, d, m) for i, (uid, d, m) in enumerate(page_users, start=1)]
        members_data = await asyncio.gather(*tasks) if tasks else []
        max_xp = sorted_users[0][1].get("xp", 1) if sorted_users else 1

        guild_icon = await self.fetch_avatar(guild, size=60)
        buf = self.render_xp_leaderboard_card(
            guild_name=guild.name,
            guild_icon=guild_icon,
            page=current_page,
            total_pages=total_pages,
            total_members=total_members,
            members_data=members_data,
            max_xp=max_xp,
            guild_id=guild.id
        )
        return discord.File(fp=buf, filename=f"xp_leaderboard_{guild.id}_p{current_page}.png")

    @app_commands.command(name="level_mode", description="Configure whether Level Up updates use text, image card, or both.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Text Message Only", value="text"),
        app_commands.Choice(name="Image Card Only", value="image"),
        app_commands.Choice(name="Both (Text + Image Card)", value="both")
    ])
    @app_commands.default_permissions(manage_channels=True)
    async def level_mode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        gid = str(interaction.guild.id)
        db.level_modes[gid] = mode.value
        db.save_data()
        await interaction.response.send_message(f"✅ Level Up notification mode set to **{mode.name}**.", ephemeral=True)

    # ────────────────────────── Staff Level & XP Admin Group ──────────────────────────
    level_admin = app_commands.Group(name="level_admin", description="Staff controls for server leveling, XP, and ranks.")

    @level_admin.command(name="add_xp", description="Add XP to a member.")
    @app_commands.describe(member="Member to award XP", amount="Amount of XP to add")
    @app_commands.default_permissions(administrator=True)
    async def admin_add_xp(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        gid, uid = str(interaction.guild.id), str(member.id)
        if gid not in db.xp_data: db.xp_data[gid] = {}
        if uid not in db.xp_data[gid]: db.xp_data[gid][uid] = {"xp": 0, "level": 0}

        db.xp_data[gid][uid]["xp"] += amount
        current_xp = db.xp_data[gid][uid]["xp"]
        current_level = db.xp_data[gid][uid]["level"]
        leveled_up = False

        while True:
            req_xp = self.get_xp_requirement(current_level)
            if current_xp >= req_xp:
                current_level += 1
                current_xp -= req_xp
                leveled_up = True
            else:
                break

        db.xp_data[gid][uid]["level"] = current_level
        db.xp_data[gid][uid]["xp"] = current_xp
        db.save_data()
        lvl_note = f" (Now **Level {current_level}**! 🎉)" if leveled_up else ""
        await interaction.response.send_message(f"✅ Added **{amount:,} XP** to {member.mention}. Current: Level **{current_level}** • **{current_xp:,} XP**{lvl_note}")

    @level_admin.command(name="remove_xp", description="Remove XP from a member.")
    @app_commands.describe(member="Member to deduct XP from", amount="Amount of XP to remove")
    @app_commands.default_permissions(administrator=True)
    async def admin_remove_xp(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        gid, uid = str(interaction.guild.id), str(member.id)
        if gid not in db.xp_data or uid not in db.xp_data[gid]:
            await interaction.response.send_message(f"❌ {member.mention} has no XP recorded.", ephemeral=True)
            return

        current_xp = db.xp_data[gid][uid].get("xp", 0)
        current_level = db.xp_data[gid][uid].get("level", 0)

        # Deduct XP cleanly
        if amount <= current_xp:
            current_xp -= amount
        else:
            remaining_to_remove = amount - current_xp
            current_xp = 0
            while remaining_to_remove > 0 and current_level > 0:
                current_level -= 1
                req_xp = self.get_xp_requirement(current_level)
                if remaining_to_remove <= req_xp:
                    current_xp = req_xp - remaining_to_remove
                    remaining_to_remove = 0
                else:
                    remaining_to_remove -= req_xp
                    current_xp = 0

        db.xp_data[gid][uid]["level"] = current_level
        db.xp_data[gid][uid]["xp"] = current_xp
        db.save_data()
        await interaction.response.send_message(f"✅ Removed **{amount:,} XP** from {member.mention}. Current: Level **{current_level}** • **{current_xp:,} XP**")

    @level_admin.command(name="set_level", description="Directly set a member's level.")
    @app_commands.describe(member="Target member", level="New level number (0 or higher)")
    @app_commands.default_permissions(administrator=True)
    async def admin_set_level(self, interaction: discord.Interaction, member: discord.Member, level: int):
        if level < 0:
            await interaction.response.send_message("❌ Level must be 0 or higher.", ephemeral=True)
            return
        gid, uid = str(interaction.guild.id), str(member.id)
        if gid not in db.xp_data: db.xp_data[gid] = {}
        if uid not in db.xp_data[gid]: db.xp_data[gid][uid] = {"xp": 0, "level": 0}

        db.xp_data[gid][uid]["level"] = level
        db.xp_data[gid][uid]["xp"] = 0
        db.save_data()
        await interaction.response.send_message(f"✅ Set {member.mention}'s level directly to **Level {level}** (XP reset to 0).")

    @level_admin.command(name="reset", description="Reset a member's XP and Level to 0.")
    @app_commands.describe(member="Target member to reset")
    @app_commands.default_permissions(administrator=True)
    async def admin_reset(self, interaction: discord.Interaction, member: discord.Member):
        gid, uid = str(interaction.guild.id), str(member.id)
        if gid in db.xp_data and uid in db.xp_data[gid]:
            db.xp_data[gid][uid] = {"xp": 0, "level": 0}
            db.save_data()
        await interaction.response.send_message(f"🧹 Reset XP and Level for {member.mention} to **Level 0 (0 XP)**.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot: return

        gid = str(message.guild.id)
        uid = str(message.author.id)
        
        now = time.time()
        if uid not in self.xp_cooldowns or (now - self.xp_cooldowns[uid]) >= 60:
            if gid not in db.xp_data: db.xp_data[gid] = {}
            if uid not in db.xp_data[gid]: db.xp_data[gid][uid] = {"xp": 0, "level": 0}

            gained_xp = random.randint(15, 25)
            db.xp_data[gid][uid]["xp"] += gained_xp
            self.xp_cooldowns[uid] = now
            
            current_xp = db.xp_data[gid][uid]["xp"]
            current_level = db.xp_data[gid][uid]["level"]
            required_xp = self.get_xp_requirement(current_level)

            if current_xp >= required_xp:
                old_lvl = current_level
                db.xp_data[gid][uid]["level"] += 1
                db.xp_data[gid][uid]["xp"] = current_xp - required_xp 
                new_level = db.xp_data[gid][uid]["level"]
                xp_after_levelup = db.xp_data[gid][uid]["xp"]  # XP carried over after level-up (usually ~0)
                db.save_data()

                channel_id = db.level_channels.get(gid)
                if channel_id:
                    try:
                        notif_channel = self.bot.get_channel(int(channel_id))
                    except (ValueError, TypeError):
                        notif_channel = None
                    if notif_channel:
                        from emoji_utils import replace_plain_emojis
                        template = db.custom_responses.get(gid, {}).get("level_up_msg") or db.level_messages.get(gid, "🎉 Congratulations {user}! You advanced to **Level {level}**!")
                        level_msg = template.replace("{user}", message.author.mention).replace("{level}", str(new_level))
                        level_msg = replace_plain_emojis(level_msg, self.bot, guild=message.guild)
                        
                        mode = db.level_modes.get(gid, "both")
                        try:
                            if mode == "text":
                                await notif_channel.send(level_msg)
                            elif mode == "image":
                                card_file = await self.generate_levelup_card(message.author, old_lvl, new_level, guild_id=gid, xp_after=xp_after_levelup)
                                await notif_channel.send(file=card_file)
                            else: # "both"
                                card_file = await self.generate_levelup_card(message.author, old_lvl, new_level, guild_id=gid, xp_after=xp_after_levelup)
                                await notif_channel.send(content=level_msg, file=card_file)
                        except Exception as e:
                            try:
                                await notif_channel.send(level_msg)
                            except Exception:
                                pass
            else:
                db.save_data()


class XPLeaderboardView(discord.ui.View):
    """Interactive pagination view for the XP Leaderboard Graphic Card."""
    def __init__(self, cog: Leveling, guild: discord.Guild, current_page: int = 1):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.current_page = current_page
        self.update_buttons()

    def get_total_pages(self) -> int:
        gid = str(self.guild.id)
        raw_xp = db.xp_data.get(gid, {})
        active_count = 0
        for uid in raw_xp.keys():
            try:
                mem = self.guild.get_member(int(uid))
                if mem and not getattr(mem, "bot", False):
                    active_count += 1
            except Exception:
                pass
        return max(1, math.ceil(active_count / 10))

    def update_buttons(self):
        total_pages = self.get_total_pages()
        self.prev_btn.disabled = (self.current_page <= 1)
        self.next_btn.disabled = (self.current_page >= total_pages)
        self.page_indicator.label = f"Page {self.current_page} / {total_pages}"

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, custom_id="xp_lb_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.current_page > 1:
            self.current_page -= 1
        self.update_buttons()
        file = await self.cog.generate_xp_leaderboard_file(self.guild, page=self.current_page)
        await interaction.edit_original_response(attachments=[file], view=self)

    @discord.ui.button(label="Page 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, custom_id="xp_lb_page")
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="xp_lb_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        total_pages = self.get_total_pages()
        if self.current_page < total_pages:
            self.current_page += 1
        self.update_buttons()
        file = await self.cog.generate_xp_leaderboard_file(self.guild, page=self.current_page)
        await interaction.edit_original_response(attachments=[file], view=self)


async def setup(bot):
    await bot.add_cog(Leveling(bot))
