import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
from contextlib import contextmanager
import datetime
import os
import io
import math
import time
import aiohttp
from PIL import Image, ImageDraw, ImageFont
from easy_pil import Font
from database import db

# SQLite Database path inside data/ directory
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_FILE = os.path.join(DATA_DIR, "activity.db")

def create_smooth_spline_points(points, num_subdivisions=12):
    """Generates smooth Catmull-Rom spline points through the given control points."""
    if len(points) < 2:
        return points
    pts = [points[0]] + list(points) + [points[-1]]
    curve = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i-1], pts[i], pts[i+1], pts[i+2]
        for t_step in range(num_subdivisions):
            t = t_step / num_subdivisions
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * ((2 * p1[0]) +
                       (-p0[0] + p2[0]) * t +
                       (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                       (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) +
                       (-p0[1] + p2[1]) * t +
                       (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                       (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            curve.append((x, y))
    curve.append(points[-1])
    return curve

def draw_rounded_rect(draw, bbox, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)

class Activity(commands.Cog):
    """
    Tracks and displays member and server chat & voice statistics across:
    Today, This Week (7 days), This Month (30 days), This Year (365 days), and Lifetime.
    Generates high-resolution dashboard cards for both Server and Member activity.
    """
    def __init__(self, bot):
        self.bot = bot
        os.makedirs(DATA_DIR, exist_ok=True)
        self.init_db()
        self.voice_sessions = {}  # (guild_id, user_id) -> start_timestamp

    async def cog_load(self):
        if not self.flush_voice_loop.is_running():
            self.flush_voice_loop.start()

    async def cog_unload(self):
        if self.flush_voice_loop.is_running():
            self.flush_voice_loop.cancel()
        self.flush_active_voice_sessions()

    # ────────────────────────── Database Helpers ──────────────────────────

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(DB_FILE, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS member_messages (
                    guild_id TEXT,
                    user_id TEXT,
                    date TEXT,
                    message_count INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, date)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS member_voice (
                    guild_id TEXT,
                    user_id TEXT,
                    date TEXT,
                    seconds INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, date)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS channel_messages (
                    guild_id TEXT,
                    channel_id TEXT,
                    user_id TEXT,
                    date TEXT,
                    message_count INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, channel_id, user_id, date)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_member_msg_date ON member_messages(guild_id, user_id, date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_member_voice_date ON member_voice(guild_id, user_id, date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_channel_msg_date ON channel_messages(guild_id, channel_id, date)")
            conn.commit()

    def record_message(self, guild_id: int, channel_id: int, user_id: int):
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        gid_str, cid_str, uid_str = str(guild_id), str(channel_id), str(user_id)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO member_messages (guild_id, user_id, date, message_count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(guild_id, user_id, date)
                    DO UPDATE SET message_count = message_count + 1
                """, (gid_str, uid_str, today))
                cursor.execute("""
                    INSERT INTO channel_messages (guild_id, channel_id, user_id, date, message_count)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(guild_id, channel_id, user_id, date)
                    DO UPDATE SET message_count = message_count + 1
                """, (gid_str, cid_str, uid_str, today))
                conn.commit()
        except Exception as e:
            print(f"⚠️ Activity DB record_message error: {e}")

    def add_voice_seconds(self, guild_id: int, user_id: int, seconds: int):
        if seconds <= 0:
            return
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        gid_str, uid_str = str(guild_id), str(user_id)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO member_voice (guild_id, user_id, date, seconds)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(guild_id, user_id, date)
                    DO UPDATE SET seconds = seconds + excluded.seconds
                """, (gid_str, uid_str, today, int(seconds)))
                conn.commit()
        except Exception as e:
            print(f"⚠️ Activity DB add_voice_seconds error: {e}")

    def flush_active_voice_sessions(self):
        now = time.time()
        for (gid, uid), start_time in list(self.voice_sessions.items()):
            elapsed = int(now - start_time)
            if elapsed > 0:
                self.add_voice_seconds(gid, uid, elapsed)
                self.voice_sessions[(gid, uid)] = now

    @tasks.loop(minutes=5)
    async def flush_voice_loop(self):
        try:
            self.flush_active_voice_sessions()
        except Exception:
            pass

    # ────────────────────────── Query Helpers ──────────────────────────

    def format_duration(self, seconds: int) -> str:
        if not seconds or seconds <= 0:
            return "0m"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m"
        else:
            return f"{secs}s"

    def get_member_stats(self, guild_id: int, user_id: int):
        gid_str, uid_str = str(guild_id), str(user_id)
        now = datetime.datetime.now(datetime.timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        week_str = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        month_str = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        year_str = (now - datetime.timedelta(days=365)).strftime("%Y-%m-%d")

        stats = {
            "today": 0, "week": 0, "month": 0, "year": 0, "lifetime": 0,
            "voice_today": 0, "voice_week": 0, "voice_month": 0, "voice_year": 0, "voice_lifetime": 0,
            "top_channel_id": None, "top_channel_msgs": 0, "rank": 0, "total_chatters": 0
        }

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT
                        COALESCE(SUM(CASE WHEN date = ? THEN message_count ELSE 0 END), 0) AS today_msgs,
                        COALESCE(SUM(CASE WHEN date >= ? THEN message_count ELSE 0 END), 0) AS week_msgs,
                        COALESCE(SUM(CASE WHEN date >= ? THEN message_count ELSE 0 END), 0) AS month_msgs,
                        COALESCE(SUM(CASE WHEN date >= ? THEN message_count ELSE 0 END), 0) AS year_msgs,
                        COALESCE(SUM(message_count), 0) AS lifetime_msgs
                    FROM member_messages
                    WHERE guild_id = ? AND user_id = ?
                """, (today_str, week_str, month_str, year_str, gid_str, uid_str))
                row = cursor.fetchone()
                if row:
                    stats["today"] = row["today_msgs"]
                    stats["week"] = row["week_msgs"]
                    stats["month"] = row["month_msgs"]
                    stats["year"] = row["year_msgs"]
                    stats["lifetime"] = row["lifetime_msgs"]

                cursor.execute("""
                    SELECT
                        COALESCE(SUM(CASE WHEN date = ? THEN seconds ELSE 0 END), 0) AS today_voice,
                        COALESCE(SUM(CASE WHEN date >= ? THEN seconds ELSE 0 END), 0) AS week_voice,
                        COALESCE(SUM(CASE WHEN date >= ? THEN seconds ELSE 0 END), 0) AS month_voice,
                        COALESCE(SUM(CASE WHEN date >= ? THEN seconds ELSE 0 END), 0) AS year_voice,
                        COALESCE(SUM(seconds), 0) AS lifetime_voice
                    FROM member_voice
                    WHERE guild_id = ? AND user_id = ?
                """, (today_str, week_str, month_str, year_str, gid_str, uid_str))
                v_row = cursor.fetchone()
                if v_row:
                    stats["voice_today"] = v_row["today_voice"]
                    stats["voice_week"] = v_row["week_voice"]
                    stats["voice_month"] = v_row["month_voice"]
                    stats["voice_year"] = v_row["year_voice"]
                    stats["voice_lifetime"] = v_row["lifetime_voice"]

                # Rank in server
                cursor.execute("""
                    SELECT user_id, SUM(message_count) AS total
                    FROM member_messages
                    WHERE guild_id = ?
                    GROUP BY user_id
                    ORDER BY total DESC
                """, (gid_str,))
                all_ranks = cursor.fetchall()
                stats["total_chatters"] = len(all_ranks)
                for idx, r in enumerate(all_ranks, start=1):
                    if r["user_id"] == uid_str:
                        stats["rank"] = idx
                        break
        except Exception as e:
            print(f"⚠️ Activity DB get_member_stats error: {e}")

        return stats

    def get_server_stats(self, guild_id: int):
        gid_str = str(guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        week_str = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        month_str = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        year_str = (now - datetime.timedelta(days=365)).strftime("%Y-%m-%d")

        stats = {
            "today": 0, "week": 0, "month": 0, "year": 0, "lifetime": 0,
            "voice_lifetime_sec": 0
        }

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT
                        COALESCE(SUM(CASE WHEN date = ? THEN message_count ELSE 0 END), 0) AS today_msgs,
                        COALESCE(SUM(CASE WHEN date >= ? THEN message_count ELSE 0 END), 0) AS week_msgs,
                        COALESCE(SUM(CASE WHEN date >= ? THEN message_count ELSE 0 END), 0) AS month_msgs,
                        COALESCE(SUM(CASE WHEN date >= ? THEN message_count ELSE 0 END), 0) AS year_msgs,
                        COALESCE(SUM(message_count), 0) AS lifetime_msgs
                    FROM member_messages
                    WHERE guild_id = ?
                """, (today_str, week_str, month_str, year_str, gid_str))
                row = cursor.fetchone()
                if row:
                    stats["today"] = row["today_msgs"]
                    stats["week"] = row["week_msgs"]
                    stats["month"] = row["month_msgs"]
                    stats["year"] = row["year_msgs"]
                    stats["lifetime"] = row["lifetime_msgs"]

                cursor.execute("""
                    SELECT COALESCE(SUM(seconds), 0) AS total_sec
                    FROM member_voice
                    WHERE guild_id = ?
                """, (gid_str,))
                v_row = cursor.fetchone()
                if v_row:
                    stats["voice_lifetime_sec"] = v_row["total_sec"]
        except Exception as e:
            print(f"⚠️ Activity DB get_server_stats error: {e}")

        return stats

    def get_daily_trend(self, guild_id: int, user_id: int = None, days: int = 7):
        """Returns (labels, values) for the past `days` days."""
        gid_str = str(guild_id)
        uid_str = str(user_id) if user_id else None
        now = datetime.datetime.now(datetime.timezone.utc)

        dates = [(now - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
        labels = [(now - datetime.timedelta(days=i)).strftime("%b %d") for i in range(days - 1, -1, -1)]

        values = []
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for d in dates:
                    if uid_str:
                        cursor.execute("SELECT COALESCE(SUM(message_count), 0) FROM member_messages WHERE guild_id = ? AND user_id = ? AND date = ?", (gid_str, uid_str, d))
                    else:
                        cursor.execute("SELECT COALESCE(SUM(message_count), 0) FROM member_messages WHERE guild_id = ? AND date = ?", (gid_str, d))
                    row = cursor.fetchone()
                    values.append(row[0] if row else 0)
        except Exception as e:
            print(f"⚠️ Activity DB get_daily_trend error: {e}")
            values = [0] * days

        return labels, values

    def get_active_chatters_count(self, guild_id: int, days: int = 7) -> int:
        gid_str = str(guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)
        since_date = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(DISTINCT user_id) FROM member_messages WHERE guild_id = ? AND date >= ?", (gid_str, since_date))
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            print(f"⚠️ Activity DB get_active_chatters_count error: {e}")
            return 0

    def get_top_channels_list(self, guild_id: int, user_id: int = None, limit: int = 5):
        gid_str = str(guild_id)
        uid_str = str(user_id) if user_id else None
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if uid_str:
                    cursor.execute("""
                        SELECT channel_id, SUM(message_count) AS total
                        FROM channel_messages
                        WHERE guild_id = ? AND user_id = ?
                        GROUP BY channel_id
                        ORDER BY total DESC
                        LIMIT ?
                    """, (gid_str, uid_str, limit))
                else:
                    cursor.execute("""
                        SELECT channel_id, SUM(message_count) AS total
                        FROM channel_messages
                        WHERE guild_id = ?
                        GROUP BY channel_id
                        ORDER BY total DESC
                        LIMIT ?
                    """, (gid_str, limit))
                return [(r["channel_id"], r["total"]) for r in cursor.fetchall()]
        except Exception as e:
            print(f"⚠️ Activity DB get_top_channels_list error: {e}")
            return []

    def get_leaderboard(self, guild_id: int, timeframe: str = "lifetime", limit: int = 10):
        gid_str = str(guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        week_str = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        month_str = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        year_str = (now - datetime.timedelta(days=365)).strftime("%Y-%m-%d")

        query = "SELECT user_id, SUM(message_count) AS total FROM member_messages WHERE guild_id = ?"
        params = [gid_str]

        if timeframe == "today":
            query += " AND date = ?"
            params.append(today_str)
        elif timeframe == "week":
            query += " AND date >= ?"
            params.append(week_str)
        elif timeframe == "month":
            query += " AND date >= ?"
            params.append(month_str)
        elif timeframe == "year":
            query += " AND date >= ?"
            params.append(year_str)

        query += " GROUP BY user_id ORDER BY total DESC LIMIT ?"
        params.append(limit)

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, tuple(params))
                return [(r["user_id"], r["total"]) for r in cursor.fetchall()]
        except Exception as e:
            print(f"⚠️ Activity DB get_leaderboard error: {e}")
            return []

    # ────────────────────────── Event Listeners ──────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        self.record_message(message.guild.id, message.channel.id, message.author.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not member.guild or member.bot:
            return
        gid = member.guild.id
        uid = member.id
        now = time.time()
        key = (gid, uid)

        # Joined VC
        if before.channel is None and after.channel is not None:
            self.voice_sessions[key] = now

        # Left VC
        elif before.channel is not None and after.channel is None:
            start_time = self.voice_sessions.pop(key, None)
            if start_time:
                elapsed = int(now - start_time)
                self.add_voice_seconds(gid, uid, elapsed)

        # Switched VC
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            start_time = self.voice_sessions.get(key)
            if start_time:
                elapsed = int(now - start_time)
                self.add_voice_seconds(gid, uid, elapsed)
            self.voice_sessions[key] = now

    # ────────────────────────── High-Res Image Rendering ──────────────────────────

    async def fetch_avatar_image(self, target) -> Image.Image:
        """Fetch member avatar or guild icon with clean fallback."""
        url = None
        if hasattr(target, 'icon') and target.icon:
            url = str(target.icon.url)
        elif hasattr(target, 'display_avatar') and target.display_avatar:
            url = str(target.display_avatar.url)

        if url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            return Image.open(io.BytesIO(data))
            except Exception:
                pass

        # Fallback monogram circle
        name = getattr(target, 'name', 'F') or 'F'
        letter = name[0].upper()
        fb = Image.new("RGBA", (100, 100), (88, 101, 242, 255))
        d = ImageDraw.Draw(fb)
        try:
            f = Font.poppins(variant="bold", size=50)
            bbox = f.getbbox(letter)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            d.text(((100 - w) // 2, (100 - h) // 2 - 5), letter, font=f, fill=(255, 255, 255, 255))
        except Exception:
            pass
        return fb

    def render_graphic_card(
        self,
        title: str,
        subtitle: str,
        icon_img: Image.Image,
        pills: list,
        kpi_cards: list, # [(label, value, icon_type), ...]
        chart_title: str,
        chart_labels: list,
        chart_values: list,
        right_panel_title: str,
        right_panel_items: list, # [(name, count), ...]
        footer_left: str,
        footer_right: str = "Powered by Friday",
        accent_color = (56, 189, 248) # Cyan/Blue accent
    ) -> io.BytesIO:
        W, H = 1020, 620
        img = Image.new("RGBA", (W, H), (19, 20, 23, 255))
        draw = ImageDraw.Draw(img)

        # 1. Main Outer Card Container
        draw_rounded_rect(draw, (12, 12, W - 12, H - 12), radius=26, fill=(28, 30, 36, 255), outline=(42, 45, 54, 255), width=2)

        # Fonts from easy_pil Poppins
        font_title = Font.poppins(variant="bold", size=22)
        font_sub = Font.poppins(variant="regular", size=13)
        font_pill = Font.poppins(variant="bold", size=12)
        font_kpi_lbl = Font.poppins(variant="bold", size=11)
        font_kpi_val = Font.poppins(variant="bold", size=32)
        font_box_title = Font.poppins(variant="bold", size=16)
        font_axis = Font.poppins(variant="regular", size=11)
        font_list = Font.poppins(variant="regular", size=13)
        font_list_badge = Font.poppins(variant="bold", size=12)
        font_footer = Font.poppins(variant="regular", size=11)
        font_footer_bold = Font.poppins(variant="bold", size=11)

        # 2. Header
        header_x, header_y = 38, 34
        if icon_img:
            try:
                icon_resized = icon_img.convert("RGBA").resize((60, 60), Image.Resampling.LANCZOS)
                mask = Image.new("L", (60, 60), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, 60, 60), fill=255)
                img.paste(icon_resized, (header_x, header_y), mask)
                draw.ellipse((header_x, header_y, header_x + 60, header_y + 60), outline=(55, 60, 72, 255), width=2)
            except Exception:
                pass

        # Header texts
        text_x = header_x + 74
        draw.text((text_x, header_y + 6), title[:30], font=font_title, fill=(255, 255, 255, 255))
        draw.text((text_x, header_y + 34), subtitle[:45], font=font_sub, fill=(142, 146, 155, 255))

        # Top-right pills
        pill_right = W - 38
        for p_text in reversed(pills):
            p_bbox = font_pill.getbbox(p_text)
            pw = (p_bbox[2] - p_bbox[0]) + 26
            ph = 32
            px = pill_right - pw
            py = header_y + 14
            draw_rounded_rect(draw, (px, py, px + pw, py + ph), radius=16, fill=(38, 41, 49, 255), outline=(52, 56, 67, 255), width=1)
            draw.text((px + 13, py + 8), p_text, font=font_pill, fill=(240, 242, 245, 255))
            pill_right = px - 12

        # 3. KPI Cards Row (3 Cards)
        kpi_y = 114
        kpi_h = 88
        card_w = 296
        spacing = 16
        for idx, (label, val_str, _) in enumerate(kpi_cards[:3]):
            cx = 38 + idx * (card_w + spacing)
            draw_rounded_rect(draw, (cx, kpi_y, cx + card_w, kpi_y + kpi_h), radius=16, fill=(35, 38, 46, 255), outline=(48, 52, 63, 255), width=1)
            draw.text((cx + 18, kpi_y + 14), label.upper(), font=font_kpi_lbl, fill=(155, 160, 169, 255))
            draw.text((cx + 18, kpi_y + 36), str(val_str), font=font_kpi_val, fill=(255, 255, 255, 255))

            # Mini vector icon indicator on right
            ix = cx + card_w - 36
            iy = kpi_y + 18
            if idx == 0:
                draw.line((ix, iy + 14, ix, iy + 6), fill=(100, 105, 118, 255), width=3)
                draw.line((ix + 6, iy + 14, ix + 6, iy + 2), fill=accent_color + (255,), width=3)
                draw.line((ix + 12, iy + 14, ix + 12, iy + 9), fill=(100, 105, 118, 255), width=3)
            elif idx == 1:
                draw.ellipse((ix + 3, iy, ix + 11, iy + 8), fill=(100, 105, 118, 255))
                draw.arc((ix, iy + 7, ix + 14, iy + 18), start=180, end=0, fill=(100, 105, 118, 255), width=2)
            else:
                draw.arc((ix, iy + 1, ix + 14, iy + 15), start=140, end=400, fill=(100, 105, 118, 255), width=2)
                draw.line((ix + 7, iy + 8, ix + 11, iy + 4), fill=accent_color + (255,), width=2)

        # 4. Main Body: Left Panel (Trend Chart) & Right Panel (Top Channels)
        body_y = 218
        body_h = 328
        left_w = 560
        right_x = 614
        right_w = W - 38 - right_x

        # Left Container
        draw_rounded_rect(draw, (38, body_y, 38 + left_w, body_y + body_h), radius=18, fill=(35, 38, 46, 255), outline=(48, 52, 63, 255), width=1)
        draw.text((60, body_y + 18), chart_title, font=font_box_title, fill=(255, 255, 255, 255))

        # Legend
        legend_text = "Messages"
        leg_bbox = font_axis.getbbox(legend_text)
        leg_x = 38 + left_w - 30 - (leg_bbox[2] - leg_bbox[0])
        draw.ellipse((leg_x - 14, body_y + 24, leg_x - 6, body_y + 32), fill=accent_color + (255,))
        draw.text((leg_x, body_y + 21), legend_text, font=font_axis, fill=(142, 146, 155, 255))

        # Plot geometry
        plot_x = 94
        plot_y = body_y + 70
        plot_w = left_w - 82
        plot_h = 195

        max_val = max(chart_values) if chart_values and max(chart_values) > 0 else 10
        if max_val <= 10: max_y = 10
        elif max_val <= 50: max_y = math.ceil(max_val / 10) * 10
        elif max_val <= 500: max_y = math.ceil(max_val / 50) * 50
        else: max_y = math.ceil(max_val / 100) * 100

        # Horizontal gridlines & Y labels
        for step in range(4):
            val = int(max_y * (3 - step) / 3)
            gy = plot_y + int(plot_h * step / 3)
            draw.line((plot_x, gy, plot_x + plot_w, gy), fill=(44, 48, 58, 255), width=1)
            val_str = f"{val:,}"
            draw.text((plot_x - 48, gy - 7), val_str, font=font_axis, fill=(115, 120, 131, 255))

        # Plot points
        raw_points = []
        num_pts = len(chart_values)
        for i, v in enumerate(chart_values):
            cx = plot_x + int(i * (plot_w / max(1, num_pts - 1)))
            cy = plot_y + plot_h - int((v / max_y) * plot_h)
            raw_points.append((cx, cy))

        spline_points = create_smooth_spline_points(raw_points, num_subdivisions=12)

        # Gradient fill
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        poly_points = [(plot_x, plot_y + plot_h)] + spline_points + [(plot_x + plot_w, plot_y + plot_h)]
        overlay_draw.polygon(poly_points, fill=accent_color + (38,))
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        # Spline line
        for i in range(len(spline_points) - 1):
            draw.line([spline_points[i], spline_points[i+1]], fill=accent_color + (255,), width=3)

        # Point markers & X labels
        for i, (px, py) in enumerate(raw_points):
            draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=(28, 30, 36, 255), outline=accent_color + (255,), width=2)
            draw.ellipse((px - 2, py - 2, px + 2, py + 2), fill=(255, 255, 255, 255))
            if i < len(chart_labels):
                lbl = chart_labels[i]
                l_bbox = font_axis.getbbox(lbl)
                lw = l_bbox[2] - l_bbox[0]
                draw.text((px - lw // 2, plot_y + plot_h + 14), lbl, font=font_axis, fill=(130, 135, 146, 255))

        # Right Container
        draw_rounded_rect(draw, (right_x, body_y, right_x + right_w, body_y + body_h), radius=18, fill=(35, 38, 46, 255), outline=(48, 52, 63, 255), width=1)
        draw.text((right_x + 22, body_y + 18), right_panel_title, font=font_box_title, fill=(255, 255, 255, 255))
        draw.text((right_x + right_w - 32, body_y + 18), "#", font=font_box_title, fill=(110, 115, 126, 255))

        # 5 items list
        row_y = body_y + 58
        row_h = 44
        for idx, (name_str, count_val) in enumerate(right_panel_items[:5], start=1):
            ry = row_y + (idx - 1) * row_h
            draw_rounded_rect(draw, (right_x + 12, ry, right_x + right_w - 12, ry + 36), radius=10, fill=(29, 31, 38, 255))
            draw.text((right_x + 26, ry + 9), str(idx), font=font_list_badge, fill=(255, 255, 255, 255) if idx <= 3 else (140, 145, 155, 255))
            c_name = name_str if name_str.startswith("#") else f"# {name_str}"
            draw.text((right_x + 56, ry + 9), c_name[:18], font=font_list, fill=(235, 238, 242, 255))
            c_str = f"{count_val:,}"
            c_bbox = font_list_badge.getbbox(c_str)
            cw = (c_bbox[2] - c_bbox[0]) + 18
            cx = right_x + right_w - 22 - cw
            draw_rounded_rect(draw, (cx, ry + 4, cx + cw, ry + 32), radius=8, fill=(38, 41, 50, 255))
            draw.text((cx + 9, ry + 9), c_str, font=font_list_badge, fill=(255, 255, 255, 255))

        if not right_panel_items:
            draw.text((right_x + 24, body_y + 80), "No recorded activity yet", font=font_sub, fill=(120, 125, 136, 255))

        # 5. Footer
        footer_y = H - 38
        draw.text((38, footer_y), footer_left, font=font_footer, fill=(115, 120, 130, 255))
        f_bbox = font_footer_bold.getbbox(footer_right)
        draw.text((W - 38 - (f_bbox[2] - f_bbox[0]), footer_y), footer_right, font=font_footer_bold, fill=(150, 155, 166, 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf

    async def generate_server_card_file(self, guild: discord.Guild) -> discord.File:
        gid = guild.id
        icon_img = await self.fetch_avatar_image(guild)
        labels, values = self.get_daily_trend(gid, days=7)
        srv_stats = self.get_server_stats(gid)
        active_chatters = self.get_active_chatters_count(gid, days=7)

        week_msgs = srv_stats["week"]
        msgs_per_day = round(week_msgs / 7) if week_msgs > 0 else srv_stats["today"]

        top_raw = self.get_top_channels_list(gid, limit=5)
        top_channels = []
        for cid, total in top_raw:
            ch = guild.get_channel(int(cid))
            c_name = ch.name if ch else f"channel-{cid}"
            top_channels.append((c_name, total))

        created_str = f"Created {guild.created_at.strftime('%B %d, %Y')}" if guild.created_at else "Created Unknown"
        members_count = guild.member_count or len(guild.members)
        pills = ["MESSAGES", f"{members_count:,} Members"]
        if guild.premium_tier > 0:
            pills.append(f"Level {guild.premium_tier}")

        kpi_cards = [
            ("MESSAGES", f"{srv_stats['lifetime']:,}", "bar"),
            ("ACTIVE CHATTERS", f"{active_chatters:,}", "users"),
            ("MSGS / DAY", f"{msgs_per_day:,}", "clock")
        ]

        buf = self.render_graphic_card(
            title=guild.name,
            subtitle=created_str,
            icon_img=icon_img,
            pills=pills,
            kpi_cards=kpi_cards,
            chart_title="Last 7 days",
            chart_labels=labels,
            chart_values=values,
            right_panel_title="Top Channels",
            right_panel_items=top_channels,
            footer_left="Server Lookback: Last 7 days • Timezone: UTC",
            footer_right="Powered by Friday",
            accent_color=(56, 189, 248) # Sky blue
        )
        return discord.File(fp=buf, filename=f"server_activity_{guild.id}.png")

    async def generate_member_card_file(self, guild: discord.Guild, member: discord.Member) -> discord.File:
        gid = guild.id
        uid = member.id
        avatar_img = await self.fetch_avatar_image(member)
        labels, values = self.get_daily_trend(gid, user_id=uid, days=7)
        m_stats = self.get_member_stats(gid, uid)

        top_raw = self.get_top_channels_list(gid, user_id=uid, limit=5)
        top_channels = []
        for cid, total in top_raw:
            ch = guild.get_channel(int(cid))
            c_name = ch.name if ch else f"channel-{cid}"
            top_channels.append((c_name, total))

        joined_str = f"Joined {member.joined_at.strftime('%B %d, %Y')}" if member.joined_at else f"Tag: @{member.name}"
        pills = ["MESSAGES"]
        if m_stats["rank"] > 0:
            pills.append(f"Rank #{m_stats['rank']}")
        if member.top_role and member.top_role.name != "@everyone":
            pills.append(member.top_role.name[:16])

        voice_str = self.format_duration(m_stats["voice_lifetime"])

        kpi_cards = [
            ("TODAY", f"{m_stats['today']:,}", "bar"),
            ("PAST 7 DAYS", f"{m_stats['week']:,}", "users"),
            ("LIFETIME", f"{m_stats['lifetime']:,}", "clock")
        ]

        buf = self.render_graphic_card(
            title=member.display_name,
            subtitle=joined_str,
            icon_img=avatar_img,
            pills=pills,
            kpi_cards=kpi_cards,
            chart_title="Last 7 days Activity",
            chart_labels=labels,
            chart_values=values,
            right_panel_title="Top Channels",
            right_panel_items=top_channels,
            footer_left=f"Member Lookback: Last 7 days • Voice: {voice_str} • User ID: {member.id}",
            footer_right="Powered by Friday",
            accent_color=(129, 140, 248) # Indigo / Blurple
        )
        return discord.File(fp=buf, filename=f"member_activity_{member.id}.png")

    # ────────────────────────── Leaderboard Embed ──────────────────────────

    def build_leaderboard_embed(self, guild: discord.Guild, timeframe: str) -> discord.Embed:
        timeframe_names = {
            "today": "Today's",
            "week": "This Week's (7 Days)",
            "month": "This Month's (30 Days)",
            "year": "This Year's (365 Days)",
            "lifetime": "Lifetime"
        }
        title_time = timeframe_names.get(timeframe, "Lifetime")
        top_list = self.get_leaderboard(guild.id, timeframe=timeframe, limit=10)

        embed = discord.Embed(
            title=f"Top Chatters Leaderboard · {title_time}",
            description=f"Showing the top {len(top_list)} most active members in **{guild.name}** for **{title_time}**:",
            color=discord.Color.brand_green(),
            timestamp=discord.utils.utcnow()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        if not top_list:
            embed.description = f"No activity recorded yet for **{title_time}**. Send a message to start charting!"
        else:
            lines = []
            for idx, (uid, count) in enumerate(top_list, start=1):
                mem = guild.get_member(int(uid))
                user_label = mem.mention if mem else f"`<@{uid}>`"
                lines.append(f"`#{idx:02d}` **{user_label}** — `{count:,}` messages")
            embed.add_field(name="Member Rankings", value="\n".join(lines), inline=False)

        embed.set_footer(text="Friday Activity Matrix • Click buttons below to switch timeframe!")
        return embed

    # ────────────────────────── Slash Commands ──────────────────────────

    activity_group = app_commands.Group(name="activity", description="Inspect member and server chat activity, voice telemetry, and leaderboards.")
    my_group = app_commands.Group(name="my", description="Personal stats and shortcuts.")

    @activity_group.command(name="member", description="View custom graphic activity dashboard for a member (today, week, month, year, lifetime).")
    @app_commands.describe(member="The member to inspect (defaults to yourself)")
    async def activity_member(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        target = member or interaction.user
        file = await self.generate_member_card_file(interaction.guild, target)
        await interaction.followup.send(file=file)

    @activity_group.command(name="server", description="View custom graphic analytics dashboard for the server.")
    async def activity_server(self, interaction: discord.Interaction):
        await interaction.response.defer()
        file = await self.generate_server_card_file(interaction.guild)
        await interaction.followup.send(file=file)

    @activity_group.command(name="leaderboard", description="View the top chatters for Today, This Week, This Month, This Year, or Lifetime.")
    @app_commands.choices(timeframe=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week (7 Days)", value="week"),
        app_commands.Choice(name="This Month (30 Days)", value="month"),
        app_commands.Choice(name="This Year (365 Days)", value="year"),
        app_commands.Choice(name="Lifetime", value="lifetime")
    ])
    async def activity_leaderboard(self, interaction: discord.Interaction, timeframe: app_commands.Choice[str] = None):
        tf = timeframe.value if timeframe else "lifetime"
        embed = self.build_leaderboard_embed(interaction.guild, tf)
        view = ActivityLeaderboardView(self, interaction.guild, tf)
        await interaction.response.send_message(embed=embed, view=view)

    # ─── User shortcut: /my msg and /my stats ───
    @my_group.command(name="msg", description="View your personal chat activity and message stats graphic card.")
    async def my_msg(self, interaction: discord.Interaction):
        await interaction.response.defer()
        file = await self.generate_member_card_file(interaction.guild, interaction.user)
        await interaction.followup.send(file=file)

    @my_group.command(name="stats", description="View your personal chat activity and message stats graphic card.")
    async def my_stats(self, interaction: discord.Interaction):
        await interaction.response.defer()
        file = await self.generate_member_card_file(interaction.guild, interaction.user)
        await interaction.followup.send(file=file)

class ActivityLeaderboardView(discord.ui.View):
    def __init__(self, cog: Activity, guild: discord.Guild, current_tf: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.current_tf = current_tf
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        buttons = [
            ("Today", "today"),
            ("Week", "week"),
            ("Month", "month"),
            ("Year", "year"),
            ("Lifetime", "lifetime")
        ]
        for label, val in buttons:
            style = discord.ButtonStyle.primary if val == self.current_tf else discord.ButtonStyle.secondary
            btn = discord.ui.Button(label=label, custom_id=f"act_lb_{val}", style=style)
            btn.callback = self.make_callback(val)
            self.add_item(btn)

    def make_callback(self, tf: str):
        async def callback(interaction: discord.Interaction):
            self.current_tf = tf
            self.update_buttons()
            embed = self.cog.build_leaderboard_embed(self.guild, tf)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

async def setup(bot):
    await bot.add_cog(Activity(bot))
