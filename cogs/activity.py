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
import unicodedata
import asyncio
import aiohttp
from PIL import Image, ImageDraw
from easy_pil import Font

# SQLite Database path inside data/ directory
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_FILE = os.path.join(DATA_DIR, "activity.db")

def clean_display_name(name: str, max_len: int = 22) -> str:
    """Sanitizes user display names and titles, normalizing decorative unicode so no tofu boxes appear."""
    if not name:
        return "Unknown"
    norm = unicodedata.normalize('NFKD', str(name))
    cleaned = "".join(ch for ch in norm if 32 <= ord(ch) <= 126 and ch not in "`*~_<>|\\")
    cleaned = cleaned.strip(" -_#|•·~+=[]{}()<>")
    if not cleaned:
        cleaned = "".join(ch for ch in name if ch.isalnum() or ch in " -_")
    if not cleaned:
        cleaned = "User"
    return cleaned[:max_len]

def clean_channel_name(name: str, max_len: int = 20) -> str:
    """Sanitizes channel names, removing unrenderable emoji prefixes and symbols."""
    if not name:
        return "channel"
    norm = unicodedata.normalize('NFKD', str(name))
    cleaned = "".join(ch for ch in norm if 32 <= ord(ch) <= 126 and ch not in "`*~_<>|\\")
    cleaned = cleaned.strip(" -_#|•·~+=[]{}()<>")
    if not cleaned:
        cleaned = "".join(ch for ch in name if ch.isalnum() or ch in "-_")
    if not cleaned:
        cleaned = "channel"
    return cleaned[:max_len]

def monotone_cubic_spline(points, num_subdivisions=16):
    """
    Computes a monotone cubic Hermite spline (Fritsch-Carlson algorithm).
    Guarantees monotonicity: flat values remain strictly flat, never dips below 0 / baseline,
    and prevents overshoot / undershoot artifacts.
    """
    n = len(points)
    if n < 2:
        return points
    if n == 2:
        return [points[0], points[1]]

    x = [p[0] for p in points]
    y = [p[1] for p in points]

    # 1. Secant slopes
    dx = [x[i+1] - x[i] for i in range(n - 1)]
    dy = [y[i+1] - y[i] for i in range(n - 1)]
    m = [dy[i] / dx[i] if dx[i] != 0 else 0.0 for i in range(n - 1)]

    # 2. Tangents (Fritsch-Carlson condition)
    tangents = [0.0] * n
    tangents[0] = m[0]
    for i in range(1, n - 1):
        if m[i-1] * m[i] <= 0:
            tangents[i] = 0.0
        else:
            tangents[i] = 2.0 / (1.0 / m[i-1] + 1.0 / m[i])
    tangents[-1] = m[-1]

    # 3. Interpolate Hermite cubic spline
    curve = []
    for i in range(n - 1):
        h = dx[i]
        for step in range(num_subdivisions):
            t = step / num_subdivisions
            t2 = t * t
            t3 = t2 * t

            h00 = 2 * t3 - 3 * t2 + 1
            h10 = t3 - 2 * t2 + t
            h01 = -2 * t3 + 3 * t2
            h11 = t3 - t2

            px = x[i] + t * h
            py = h00 * y[i] + h10 * h * tangents[i] + h01 * y[i+1] + h11 * h * tangents[i+1]
            curve.append((px, py))
    curve.append(points[-1])
    return curve

def draw_rounded_rect(draw, bbox, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)

class Activity(commands.Cog):
    """
    Tracks and displays member and server chat & voice statistics across:
    Today, This Week (7 days), This Month (30 days), This Year (365 days), and Lifetime.
    Generates high-resolution dashboard cards for Server, Member, and Leaderboard activity.
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
                        COALESCE(SUM(CASE WHEN date = ? THEN seconds ELSE 0 END), 0) AS voice_today,
                        COALESCE(SUM(CASE WHEN date >= ? THEN seconds ELSE 0 END), 0) AS voice_week,
                        COALESCE(SUM(CASE WHEN date >= ? THEN seconds ELSE 0 END), 0) AS voice_month,
                        COALESCE(SUM(CASE WHEN date >= ? THEN seconds ELSE 0 END), 0) AS voice_year,
                        COALESCE(SUM(seconds), 0) AS voice_lifetime
                    FROM member_voice
                    WHERE guild_id = ? AND user_id = ?
                """, (today_str, week_str, month_str, year_str, gid_str, uid_str))
                v_row = cursor.fetchone()
                if v_row:
                    stats["voice_today"] = v_row["voice_today"]
                    stats["voice_week"] = v_row["voice_week"]
                    stats["voice_month"] = v_row["voice_month"]
                    stats["voice_year"] = v_row["voice_year"]
                    stats["voice_lifetime"] = v_row["voice_lifetime"]

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

    def get_leaderboard(self, guild_id: int, timeframe: str = "lifetime", limit: int = 10, offset: int = 0):
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

        query += " GROUP BY user_id ORDER BY total DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, tuple(params))
                return [(r["user_id"], r["total"]) for r in cursor.fetchall()]
        except Exception as e:
            print(f"⚠️ Activity DB get_leaderboard error: {e}")
            return []

    def get_leaderboard_total_count(self, guild_id: int, timeframe: str = "lifetime") -> int:
        gid_str = str(guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        week_str = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        month_str = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        year_str = (now - datetime.timedelta(days=365)).strftime("%Y-%m-%d")

        query = "SELECT COUNT(DISTINCT user_id) FROM member_messages WHERE guild_id = ?"
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

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, tuple(params))
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

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
        """Fetch member avatar or guild icon with clean monogram fallback."""
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
        clean = clean_display_name(name)
        letter = clean[0].upper() if clean else 'F'
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

        # Header texts (clean unicode)
        text_x = header_x + 74
        draw.text((text_x, header_y + 6), clean_display_name(title, max_len=28), font=font_title, fill=(255, 255, 255, 255))
        draw.text((text_x, header_y + 34), clean_display_name(subtitle, max_len=45), font=font_sub, fill=(142, 146, 155, 255))

        # Top-right pills
        pill_right = W - 38
        for p_text in reversed(pills):
            p_clean = clean_display_name(p_text, max_len=18)
            p_bbox = font_pill.getbbox(p_clean)
            pw = (p_bbox[2] - p_bbox[0]) + 26
            ph = 32
            px = pill_right - pw
            py = header_y + 14
            draw_rounded_rect(draw, (px, py, px + pw, py + ph), radius=16, fill=(38, 41, 49, 255), outline=(52, 56, 67, 255), width=1)
            draw.text((px + 13, py + 8), p_clean, font=font_pill, fill=(240, 242, 245, 255))
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
        baseline_y = plot_y + plot_h

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
            cy = baseline_y - int((v / max_y) * plot_h)
            raw_points.append((cx, cy))

        # Fritsch-Carlson monotone cubic spline interpolation (NEVER dips below baseline)
        raw_spline = monotone_cubic_spline(raw_points, num_subdivisions=16)
        spline_points = [(p[0], min(baseline_y, max(plot_y, p[1]))) for p in raw_spline]

        # Area Gradient fill under curve
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        poly_points = [(plot_x, baseline_y)] + spline_points + [(plot_x + plot_w, baseline_y)]
        overlay_draw.polygon(poly_points, fill=accent_color + (38,))
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        # Spline stroke line
        for i in range(len(spline_points) - 1):
            draw.line([spline_points[i], spline_points[i+1]], fill=accent_color + (255,), width=3)

        # Point markers & X date labels
        for i, (px, py) in enumerate(raw_points):
            draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=(28, 30, 36, 255), outline=accent_color + (255,), width=2)
            draw.ellipse((px - 2, py - 2, px + 2, py + 2), fill=(255, 255, 255, 255))
            if i < len(chart_labels):
                lbl = chart_labels[i]
                l_bbox = font_axis.getbbox(lbl)
                lw = l_bbox[2] - l_bbox[0]
                draw.text((px - lw // 2, baseline_y + 14), lbl, font=font_axis, fill=(130, 135, 146, 255))

        # Right Container: Top Channels
        draw_rounded_rect(draw, (right_x, body_y, right_x + right_w, body_y + body_h), radius=18, fill=(35, 38, 46, 255), outline=(48, 52, 63, 255), width=1)
        draw.text((right_x + 22, body_y + 18), right_panel_title, font=font_box_title, fill=(255, 255, 255, 255))
        draw.text((right_x + right_w - 32, body_y + 18), "#", font=font_box_title, fill=(110, 115, 126, 255))

        # Balanced 5 slots list (fills empty slots cleanly so panel is never blank)
        row_y = body_y + 58
        row_h = 44
        for slot in range(1, 6):
            ry = row_y + (slot - 1) * row_h
            draw_rounded_rect(draw, (right_x + 12, ry, right_x + right_w - 12, ry + 36), radius=10, fill=(29, 31, 38, 255))
            if slot <= len(right_panel_items):
                name_str, count_val = right_panel_items[slot - 1]
                draw.text((right_x + 26, ry + 9), str(slot), font=font_list_badge, fill=(255, 255, 255, 255) if slot <= 3 else (140, 145, 155, 255))
                clean_name = clean_channel_name(name_str, max_len=18)
                c_name = clean_name if clean_name.startswith("#") else f"# {clean_name}"
                draw.text((right_x + 56, ry + 9), c_name, font=font_list, fill=(235, 238, 242, 255))
                c_str = f"{count_val:,}"
                c_bbox = font_list_badge.getbbox(c_str)
                cw = (c_bbox[2] - c_bbox[0]) + 18
                cx = right_x + right_w - 22 - cw
                draw_rounded_rect(draw, (cx, ry + 4, cx + cw, ry + 32), radius=8, fill=(38, 41, 50, 255))
                draw.text((cx + 9, ry + 9), c_str, font=font_list_badge, fill=(255, 255, 255, 255))
            else:
                # Dimmed placeholder slot
                draw.text((right_x + 26, ry + 9), str(slot), font=font_list_badge, fill=(70, 75, 86, 255))
                draw.text((right_x + 56, ry + 9), "# —", font=font_list, fill=(75, 80, 92, 255))
                draw.text((right_x + right_w - 38, ry + 9), "—", font=font_list_badge, fill=(70, 75, 86, 255))

        # 5. Footer
        footer_y = H - 38
        draw.text((38, footer_y), clean_display_name(footer_left, max_len=80), font=font_footer, fill=(115, 120, 130, 255))
        f_bbox = font_footer_bold.getbbox(footer_right)
        draw.text((W - 38 - (f_bbox[2] - f_bbox[0]), footer_y), footer_right, font=font_footer_bold, fill=(150, 155, 166, 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf

    def render_leaderboard_card(
        self,
        guild_name: str,
        guild_icon: Image.Image,
        timeframe_name: str,
        page: int,
        total_pages: int,
        total_chatters: int,
        members_data: list, # [(rank, name, username, avatar_img, count), ...]
        max_msgs: int = 1
    ) -> io.BytesIO:
        """Renders high-resolution 1020x640 graphic leaderboard card with 10 members per page in a 2-column grid."""
        W, H = 1020, 640
        img = Image.new("RGBA", (W, H), (19, 20, 23, 255))
        draw = ImageDraw.Draw(img)

        # 1. Main Outer Container
        draw_rounded_rect(draw, (12, 12, W - 12, H - 12), radius=26, fill=(28, 30, 36, 255), outline=(42, 45, 54, 255), width=2)

        font_title = Font.poppins(variant="bold", size=22)
        font_sub = Font.poppins(variant="regular", size=13)
        font_pill = Font.poppins(variant="bold", size=12)
        font_name = Font.poppins(variant="bold", size=14)
        font_user = Font.poppins(variant="regular", size=11)
        font_rank = Font.poppins(variant="bold", size=13)
        font_cnt = Font.poppins(variant="bold", size=13)
        font_footer = Font.poppins(variant="regular", size=11)
        font_footer_bold = Font.poppins(variant="bold", size=11)

        # 2. Header
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
        draw.text((text_x, header_y + 34), f"Top Chatters Leaderboard • {timeframe_name}", font=font_sub, fill=(142, 146, 155, 255))

        # Top-right status pills
        pills = [
            f"PAGE {page} OF {total_pages}",
            f"{total_chatters:,} Chatters",
            "RANKINGS"
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

        # 3. Two-Column Grid: 5 Rows on Left, 5 Rows on Right
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
                _, name_str, user_str, av_img, cnt = m_dict[current_rank]

                # Progress bar underlay
                ratio = cnt / max(1, max_msgs)
                fill_w = int(col_w * min(1.0, max(0.02, ratio)))
                if fill_w > 0:
                    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    od = ImageDraw.Draw(overlay)
                    draw_rounded_rect(od, (cx, cy, cx + fill_w, cy + row_h), radius=14, fill=(56, 189, 248, 22))
                    img = Image.alpha_composite(img, overlay)
                    draw = ImageDraw.Draw(img)

                # Rank badge styling
                if current_rank == 1:
                    r_fill, r_out, r_txt = (60, 45, 15, 255), (217, 119, 6, 255), (245, 158, 11, 255)
                elif current_rank == 2:
                    r_fill, r_out, r_txt = (40, 45, 55, 255), (148, 163, 184, 255), (203, 213, 225, 255)
                elif current_rank == 3:
                    r_fill, r_out, r_txt = (55, 30, 15, 255), (234, 88, 12, 255), (249, 115, 22, 255)
                else:
                    r_fill, r_out, r_txt = (28, 30, 36, 255), (46, 50, 60, 255), (150, 155, 166, 255)

                draw_rounded_rect(draw, (cx + 12, cy + 24, cx + 48, cy + 56), radius=10, fill=r_fill, outline=r_out, width=1)
                r_str = f"#{current_rank}"
                rb = font_rank.getbbox(r_str)
                rw = rb[2] - rb[0]
                draw.text((cx + 12 + (36 - rw) // 2, cy + 32), r_str, font=font_rank, fill=r_txt)

                # Avatar (44x44 circular crop)
                av_x = cx + 60
                av_y = cy + 18
                if av_img:
                    try:
                        av_resized = av_img.convert("RGBA").resize((44, 44), Image.Resampling.LANCZOS)
                        mask = Image.new("L", (44, 44), 0)
                        mask_draw = ImageDraw.Draw(mask)
                        mask_draw.ellipse((0, 0, 44, 44), fill=255)
                        img.paste(av_resized, (av_x, av_y), mask)
                        draw.ellipse((av_x, av_y, av_x + 44, av_y + 44), outline=(55, 60, 72, 255), width=1)
                    except Exception:
                        pass
                else:
                    # Monogram circle
                    draw.ellipse((av_x, av_y, av_x + 44, av_y + 44), fill=(88, 101, 242, 255))
                    c_letter = clean_display_name(name_str)[0].upper() if name_str else '?'
                    ab = font_pill.getbbox(c_letter)
                    draw.text((av_x + (44 - (ab[2] - ab[0])) // 2, av_y + 14), c_letter, font=font_pill, fill=(255, 255, 255, 255))

                # Name & Tag
                tx = av_x + 54
                draw.text((tx, cy + 20), clean_display_name(name_str, max_len=16), font=font_name, fill=(255, 255, 255, 255))
                draw.text((tx, cy + 44), f"@{clean_display_name(user_str, max_len=18)}", font=font_user, fill=(130, 135, 146, 255))

                # Count pill
                cnt_str = f"{cnt:,} msgs"
                cb = font_cnt.getbbox(cnt_str)
                cw = (cb[2] - cb[0]) + 20
                cpx = cx + col_w - 14 - cw
                draw_rounded_rect(draw, (cpx, cy + 24, cpx + cw, cy + 56), radius=10, fill=(28, 30, 37, 255), outline=(48, 52, 63, 255), width=1)
                draw.text((cpx + 10, cy + 32), cnt_str, font=font_cnt, fill=(255, 255, 255, 255))
            else:
                # Dimmed available slot
                draw.text((cx + 18, cy + 30), f"#{current_rank}  — No more recorded chatters —", font=font_sub, fill=(75, 80, 92, 255))

        # 4. Footer
        footer_y = H - 36
        draw.text((38, footer_y), "Use the Previous and Next buttons below to navigate pages • Timezone: UTC", font=font_footer, fill=(115, 120, 130, 255))
        fb = font_footer_bold.getbbox("Powered by Friday")
        draw.text((W - 38 - (fb[2] - fb[0]), footer_y), "Powered by Friday", font=font_footer_bold, fill=(150, 155, 166, 255))

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
            top_channels.append((clean_channel_name(c_name), total))

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
            top_channels.append((clean_channel_name(c_name), total))

        joined_str = f"Joined {member.joined_at.strftime('%B %d, %Y')}" if member.joined_at else f"Tag: @{clean_display_name(member.name)}"
        pills = ["MESSAGES"]
        if m_stats["rank"] > 0:
            pills.append(f"Rank #{m_stats['rank']}")
        if member.top_role and member.top_role.name != "@everyone":
            pills.append(clean_display_name(member.top_role.name, max_len=14))

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

    async def generate_leaderboard_card_file(
        self,
        guild: discord.Guild,
        timeframe: str = "lifetime",
        page: int = 1,
        per_page: int = 10
    ) -> discord.File:
        """Generates graphic leaderboard image file for a given page and timeframe."""
        timeframe_names = {
            "today": "Today's",
            "week": "This Week's (7 Days)",
            "month": "This Month's (30 Days)",
            "year": "This Year's (365 Days)",
            "lifetime": "Lifetime"
        }
        tf_name = timeframe_names.get(timeframe, "Lifetime")
        total_chatters = self.get_leaderboard_total_count(guild.id, timeframe)
        total_pages = max(1, math.ceil(total_chatters / per_page))
        current_page = max(1, min(page, total_pages))
        offset = (current_page - 1) * per_page

        raw_list = self.get_leaderboard(guild.id, timeframe, limit=per_page, offset=offset)

        # Concurrently fetch avatar images for members on this page
        async def fetch_item(rank_num, uid, count):
            mem = guild.get_member(int(uid))
            name = mem.display_name if mem else f"User {uid[-4:]}"
            username = mem.name if mem else f"id_{uid}"
            av = await self.fetch_avatar_image(mem or uid)
            return (rank_num, name, username, av, count)

        tasks_list = [fetch_item(offset + i, uid, count) for i, (uid, count) in enumerate(raw_list, start=1)]
        members_data = await asyncio.gather(*tasks_list) if tasks_list else []

        # Find max message count on page 1 for proportional relative bar
        top_one = self.get_leaderboard(guild.id, timeframe, limit=1, offset=0)
        max_msgs = top_one[0][1] if top_one else 1

        guild_icon = await self.fetch_avatar_image(guild)
        buf = self.render_leaderboard_card(
            guild_name=guild.name,
            guild_icon=guild_icon,
            timeframe_name=tf_name,
            page=current_page,
            total_pages=total_pages,
            total_chatters=total_chatters,
            members_data=members_data,
            max_msgs=max_msgs
        )
        return discord.File(fp=buf, filename=f"leaderboard_{guild.id}_{timeframe}_p{current_page}.png")

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

    @activity_group.command(name="leaderboard", description="View custom graphic leaderboard for Today, Week, Month, Year, or Lifetime.")
    @app_commands.choices(timeframe=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week (7 Days)", value="week"),
        app_commands.Choice(name="This Month (30 Days)", value="month"),
        app_commands.Choice(name="This Year (365 Days)", value="year"),
        app_commands.Choice(name="Lifetime", value="lifetime")
    ])
    async def activity_leaderboard(self, interaction: discord.Interaction, timeframe: app_commands.Choice[str] = None):
        await interaction.response.defer()
        tf = timeframe.value if timeframe else "lifetime"
        view = ActivityLeaderboardView(self, interaction.guild, current_tf=tf, current_page=1)
        file = await self.generate_leaderboard_card_file(interaction.guild, tf, page=1)
        await interaction.followup.send(file=file, view=view)

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
    """
    Interactive pagination view for Leaderboard Image Cards.
    Provides clean 'Previous' and 'Next' buttons and timeframe switcher with zero emojis.
    """
    def __init__(self, cog: Activity, guild: discord.Guild, current_tf: str = "lifetime", current_page: int = 1):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.current_tf = current_tf
        self.current_page = current_page
        self.update_buttons()

    def get_total_pages(self) -> int:
        total = self.cog.get_leaderboard_total_count(self.guild.id, self.current_tf)
        return max(1, math.ceil(total / 10))

    def update_buttons(self):
        self.clear_items()
        total_pages = self.get_total_pages()
        self.current_page = max(1, min(self.current_page, total_pages))

        # Row 0: Pagination Buttons (Clean text labels, no mobile emojis)
        prev_btn = discord.ui.Button(
            label="Previous",
            style=discord.ButtonStyle.secondary,
            disabled=(self.current_page <= 1),
            row=0
        )
        prev_btn.callback = self.on_prev_clicked
        self.add_item(prev_btn)

        page_btn = discord.ui.Button(
            label=f"Page {self.current_page} / {total_pages}",
            style=discord.ButtonStyle.primary,
            disabled=True,
            row=0
        )
        self.add_item(page_btn)

        next_btn = discord.ui.Button(
            label="Next",
            style=discord.ButtonStyle.secondary,
            disabled=(self.current_page >= total_pages),
            row=0
        )
        next_btn.callback = self.on_next_clicked
        self.add_item(next_btn)

        # Row 1: Timeframe selectors
        tf_options = [
            ("Today", "today"),
            ("Week", "week"),
            ("Month", "month"),
            ("Year", "year"),
            ("Lifetime", "lifetime")
        ]
        for label, tf in tf_options:
            style = discord.ButtonStyle.success if tf == self.current_tf else discord.ButtonStyle.secondary
            btn = discord.ui.Button(label=label, style=style, row=1)
            btn.callback = self.make_tf_callback(tf)
            self.add_item(btn)

    async def on_prev_clicked(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if self.current_page > 1:
            self.current_page -= 1
        await self.refresh_view(interaction)

    async def on_next_clicked(self, interaction: discord.Interaction):
        await interaction.response.defer()
        total_pages = self.get_total_pages()
        if self.current_page < total_pages:
            self.current_page += 1
        await self.refresh_view(interaction)

    def make_tf_callback(self, tf: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            self.current_tf = tf
            self.current_page = 1
            await self.refresh_view(interaction)
        return callback

    async def refresh_view(self, interaction: discord.Interaction):
        self.update_buttons()
        file = await self.cog.generate_leaderboard_card_file(self.guild, self.current_tf, self.current_page)
        await interaction.edit_original_response(attachments=[file], view=self)

async def setup(bot):
    await bot.add_cog(Activity(bot))
