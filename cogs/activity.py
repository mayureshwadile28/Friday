import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional, List, Dict, Tuple, Any
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
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from database import db
from font_utils import get_unicode_font, clean_display_name, safe_channel_label

# SQLite Database path inside data/ directory
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_FILE = os.path.join(DATA_DIR, "activity.db")

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

def extract_accent_color(img: Image.Image, default_rgb=(56, 189, 248)) -> tuple:
    """Extract vibrant dominant accent color from image palette."""
    if not img:
        return default_rgb
    try:
        import colorsys
        small = img.convert("RGB").resize((60, 60), Image.Resampling.BILINEAR)
        colors = small.getcolors(maxcolors=3600)
        if not colors:
            return default_rgb
        best_color = None
        best_score = -1.0
        for count, color in colors:
            r, g, b = color
            h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            if v < 0.25 or (s < 0.15 and v > 0.85):
                continue
            score = s * 2.0 + v * 1.0 + (count / 2400) * 0.5
            if score > best_score:
                best_score = score
                best_color = color
        if best_color:
            return best_color
    except Exception:
        pass
    return default_rgb

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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS channel_names (
                    channel_id TEXT PRIMARY KEY,
                    guild_id TEXT,
                    name TEXT,
                    updated_at TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_member_msg_date ON member_messages(guild_id, user_id, date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_member_voice_date ON member_voice(guild_id, user_id, date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_channel_msg_date ON channel_messages(guild_id, channel_id, date)")
            conn.commit()

    def record_message(self, guild_id: int, channel_id: int, user_id: int, channel_name: str = None):
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
                if channel_name:
                    cursor.execute("""
                        INSERT INTO channel_names (channel_id, guild_id, name, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(channel_id) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at
                    """, (cid_str, gid_str, channel_name, today))
                conn.commit()
        except Exception as e:
            print(f"⚠️ Activity DB record_message error: {e}")

    async def get_channel_display_name(self, guild, channel_id) -> str:
        """Resolves the best human-readable channel name from guild cache, bot cache, Discord API, or SQLite database."""
        cid_int = int(channel_id) if str(channel_id).isdigit() else 0
        cid_str = str(channel_id)
        if guild:
            ch = None
            if hasattr(guild, "get_channel_or_thread"):
                ch = guild.get_channel_or_thread(cid_int)
            if not ch:
                ch = guild.get_channel(cid_int)
            if not ch and hasattr(guild, "get_thread"):
                ch = guild.get_thread(cid_int)
            if ch and getattr(ch, "name", None):
                return ch.name
        if self.bot:
            ch = self.bot.get_channel(cid_int)
            if ch and getattr(ch, "name", None):
                return ch.name
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM channel_names WHERE channel_id = ?", (cid_str,))
                row = cursor.fetchone()
                if row and row["name"]:
                    return row["name"]
        except Exception:
            pass

        # Attempt to fetch directly from Discord API if not in cache
        if guild and cid_int > 0:
            try:
                ch = await guild.fetch_channel(cid_int)
                if ch and getattr(ch, "name", None):
                    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
                    try:
                        with self.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO channel_names (channel_id, guild_id, name, updated_at)
                                VALUES (?, ?, ?, ?)
                                ON CONFLICT(channel_id) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at
                            """, (cid_str, str(guild.id), ch.name, today))
                            conn.commit()
                    except Exception:
                        pass
                    return ch.name
            except Exception:
                pass
        return "deleted-channel"

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

                # Voice rank in server
                cursor.execute("""
                    SELECT user_id, SUM(seconds) AS total
                    FROM member_voice
                    WHERE guild_id = ?
                    GROUP BY user_id
                    ORDER BY total DESC
                """, (gid_str,))
                all_v_ranks = cursor.fetchall()
                stats["total_voice_members"] = len(all_v_ranks)
                stats["voice_rank"] = 0
                for idx, r in enumerate(all_v_ranks, start=1):
                    if r["user_id"] == uid_str:
                        stats["voice_rank"] = idx
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
        self.record_message(message.guild.id, message.channel.id, message.author.id, channel_name=getattr(message.channel, 'name', ''))

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
            try:
                url = str(target.icon.with_format("png").with_size(128).url)
            except Exception:
                url = str(target.icon.url)
        elif hasattr(target, 'display_avatar') and target.display_avatar:
            try:
                url = str(target.display_avatar.with_format("png").with_size(128).url)
            except Exception:
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
            f = get_unicode_font(50, bold=True)
            bbox = f.getbbox(letter)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            d.text(((100 - w) // 2, (100 - h) // 2 - 5), letter, font=f, fill=(255, 255, 255, 255))
        except Exception:
            pass
        return fb

    def render_server_matrix_card(
        self,
        guild_name: str,
        guild_icon: Image.Image,
        owner_name: str,
        created_date_str: str,
        boost_tier: int,
        boost_count: int,
        member_count: int,
        humans_count: int,
        bots_count: int,
        text_count: int,
        voice_count: int,
        cat_count: int,
        roles_count: int,
        voice_hours: float,
        kpi_metrics: list, # [(Today, val), (Week, val), (Month, val), (Year, val), (Lifetime, val)]
        chart_labels: list,
        chart_values: list,
        top_channels: list, # [(name, count), ...]
        top_chatters: list, # [(name, count), ...]
        footer_left: str,
        footer_right: str = "Powered by Friday",
        guild_id: int = None
    ) -> io.BytesIO:
        """Renders comprehensive 1080x760 Master Server Demographics & Activity Telemetry Card."""
        W, H = 1080, 760

        # Check custom wallpaper for activity card
        raw_bg = None
        bg_img = None
        custom_bg = resolve_card_background(db.activity_card_backgrounds.get(str(guild_id))) if guild_id else None
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
                _blurred = raw_bg.filter(ImageFilter.GaussianBlur(radius=5))
                bg_img = ImageEnhance.Brightness(_blurred).enhance(0.78)
            except Exception:
                raw_bg = bg_img = None

        if not bg_img:
            img = Image.new("RGBA", (W, H), (19, 20, 23, 255))
        else:
            img = bg_img.copy()

        # Outer rounded container (Frosted glass when custom wallpaper is set)
        container_fill = (20, 22, 28, 205) if raw_bg else (28, 30, 36, 255)
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        draw_rounded_rect(od, (12, 12, W - 12, H - 12), radius=26, fill=container_fill, outline=(255, 255, 255, 38) if raw_bg else (42, 45, 54, 255), width=2)
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        font_title = get_unicode_font(22, bold=True)
        font_sub = get_unicode_font(13)
        font_pill = get_unicode_font(11, bold=True)
        font_kpi_lbl = get_unicode_font(11, bold=True)
        font_kpi_val = get_unicode_font(26, bold=True)
        font_box_title = get_unicode_font(15, bold=True)
        font_axis = get_unicode_font(11)
        font_list = get_unicode_font(13)
        font_list_badge = get_unicode_font(12, bold=True)
        font_ribbon_lbl = get_unicode_font(10, bold=True)
        font_ribbon_val = get_unicode_font(16, bold=True)
        font_ribbon_sub = get_unicode_font(11)
        font_footer = get_unicode_font(11)
        font_footer_bold = get_unicode_font(11, bold=True)

        accent_color = extract_accent_color(raw_bg, default_rgb=(56, 189, 248)) if raw_bg else (56, 189, 248)
        import colorsys as _cs
        if raw_bg:
            _ar, _ag, _ab = accent_color
            _h, _s, _v = _cs.rgb_to_hsv(_ar/255, _ag/255, _ab/255)
            _tr, _tg, _tb = _cs.hsv_to_rgb(_h, min(_s*1.2, 1.0), max(_v, 0.95))
            text_accent = (int(_tr*255), int(_tg*255), int(_tb*255))
        else:
            text_accent = (200, 205, 215)
        # Convenience: fills for inner boxes (glassmorphic when wallpaper active)
        inner_fill = (25, 28, 36, 100) if raw_bg else (35, 38, 46, 255)
        inner_outline = (255, 255, 255, 30) if raw_bg else (48, 52, 63, 255)
        row_fill = (20, 22, 30, 80) if raw_bg else (29, 31, 38, 255)
        badge_fill = (20, 22, 30, 80) if raw_bg else (38, 41, 50, 255)
        lbl_fill = text_accent + (200,) if raw_bg else (155, 160, 169, 255)
        sub_fill = text_accent + (160,) if raw_bg else (142, 146, 155, 255)
        axis_fill = text_accent + (140,) if raw_bg else (115, 120, 131, 255)
        ribbon_lbl_fill = text_accent + (190,) if raw_bg else (150, 155, 166, 255)
        ribbon_sub_fill = text_accent + (150,) if raw_bg else (125, 130, 142, 255)

        # 1. Header
        header_x, header_y = 38, 30
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
        draw.text((text_x, header_y + 4), clean_display_name(guild_name, max_len=26), font=font_title, fill=(255, 255, 255, 255))
        draw.text((text_x, header_y + 32), f"Server Demographics Matrix • Owner: @{clean_display_name(owner_name, max_len=18)} • Created {created_date_str}", font=font_sub, fill=(142, 146, 155, 255))

        # Top-right status pills
        pills = [
            f"Level {boost_tier} ({boost_count} Boosts)",
            f"{member_count:,} Members ({humans_count}H / {bots_count}B)",
            "SERVER MATRIX"
        ]
        pill_right = W - 38
        for p in reversed(pills):
            bbox = font_pill.getbbox(p)
            pw = (bbox[2] - bbox[0]) + 22
            px = pill_right - pw
            py = header_y + 12
            draw_rounded_rect(draw, (px, py, px + pw, py + 30), radius=15, fill=(38, 41, 49, 255), outline=(52, 56, 67, 255), width=1)
            draw.text((px + 11, py + 7), p, font=font_pill, fill=(240, 242, 245, 255))
            pill_right = px - 10

        # 2. Row 1: 5 Full-Horizon Metric Cards (Today, Week, Month, Year, Lifetime)
        kpi_y = 104
        kpi_h = 76
        card_w = 190
        spacing = 13
        for idx, (label, val_num) in enumerate(kpi_metrics[:5]):
            cx = 38 + idx * (card_w + spacing)
            draw_rounded_rect(draw, (cx, kpi_y, cx + card_w, kpi_y + kpi_h), radius=14, fill=inner_fill, outline=inner_outline, width=1)
            draw.text((cx + 16, kpi_y + 11), label.upper(), font=font_kpi_lbl, fill=lbl_fill)
            draw.text((cx + 16, kpi_y + 31), f"{val_num:,}", font=font_kpi_val, fill=(255, 255, 255, 255))

            # Status dot
            ix = cx + card_w - 22
            iy = kpi_y + 16
            draw.ellipse((ix, iy, ix + 6, iy + 6), fill=accent_color + (255,))

        # 3. Row 2: Middle Section (Left: Trend Spline Chart | Right: Top Channels & Chatters)
        body_y = 196
        body_h = 370
        left_w = 540
        right_x = 594
        right_w = W - 38 - right_x

        # Left Container: 7-Day Spline Chart
        draw_rounded_rect(draw, (38, body_y, 38 + left_w, body_y + body_h), radius=18, fill=inner_fill, outline=inner_outline, width=1)
        draw.text((58, body_y + 16), "7-Day Server Message Volume Trend", font=font_box_title, fill=(255, 255, 255, 255))

        # Legend
        legend_text = "Messages"
        leg_bbox = font_axis.getbbox(legend_text)
        leg_x = 38 + left_w - 26 - (leg_bbox[2] - leg_bbox[0])
        draw.ellipse((leg_x - 14, body_y + 22, leg_x - 6, body_y + 30), fill=accent_color + (255,))
        draw.text((leg_x, body_y + 19), legend_text, font=font_axis, fill=sub_fill)

        plot_x = 94
        plot_y = body_y + 64
        plot_w = left_w - 82
        plot_h = 230
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
            draw.text((plot_x - 48, gy - 7), val_str, font=font_axis, fill=axis_fill)

        raw_points = []
        num_pts = len(chart_values)
        for i, v in enumerate(chart_values):
            cx = plot_x + int(i * (plot_w / max(1, num_pts - 1)))
            cy = baseline_y - int((v / max_y) * plot_h)
            raw_points.append((cx, cy))

        # Monotone cubic spline (strictly flat baseline, no dip below 0)
        raw_spline = monotone_cubic_spline(raw_points, num_subdivisions=16)
        spline_points = [(p[0], min(baseline_y, max(plot_y, p[1]))) for p in raw_spline]

        # Area Gradient fill under curve
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        poly_points = [(plot_x, baseline_y)] + spline_points + [(plot_x + plot_w, baseline_y)]
        overlay_draw.polygon(poly_points, fill=accent_color + (36,))
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
                draw.text((px - lw // 2, baseline_y + 14), lbl, font=font_axis, fill=axis_fill)

        # Right Container: Top Channels & Top Chatters
        draw_rounded_rect(draw, (right_x, body_y, right_x + right_w, body_y + body_h), radius=18, fill=inner_fill, outline=inner_outline, width=1)
        
        # Sub-header 1: Top Channels
        draw.text((right_x + 20, body_y + 16), "Top Active Channels", font=font_box_title, fill=(255, 255, 255, 255))
        draw.text((right_x + right_w - 32, body_y + 16), "#", font=font_box_title, fill=(110, 115, 126, 255))

        ch_y = body_y + 48
        ch_h = 42
        for slot in range(1, 4):
            sy = ch_y + (slot - 1) * ch_h
            draw_rounded_rect(draw, (right_x + 12, sy, right_x + right_w - 12, sy + 34), radius=9, fill=row_fill)
            if slot <= len(top_channels):
                c_name, c_cnt = top_channels[slot - 1]
                draw.text((right_x + 24, sy + 8), str(slot), font=font_list_badge, fill=(255, 255, 255, 255) if slot == 1 else (150, 155, 166, 255))
                clean_lbl = safe_channel_label(c_name, max_len=18)
                c_text = clean_lbl if clean_lbl.startswith("#") else f"# {clean_lbl}"
                draw.text((right_x + 52, sy + 8), c_text, font=font_list, fill=(235, 238, 242, 255))
                cnt_str = f"{c_cnt:,}"
                c_box = font_list_badge.getbbox(cnt_str)
                cw = (c_box[2] - c_box[0]) + 18
                cx = right_x + right_w - 20 - cw
                draw_rounded_rect(draw, (cx, sy + 4, cx + cw, sy + 30), radius=7, fill=badge_fill)
                draw.text((cx + 9, sy + 8), cnt_str, font=font_list_badge, fill=(255, 255, 255, 255))
            else:
                draw.text((right_x + 24, sy + 8), str(slot), font=font_list_badge, fill=(70, 75, 86, 255))
                draw.text((right_x + 52, sy + 8), "# —", font=font_list, fill=(75, 80, 92, 255))
                draw.text((right_x + right_w - 36, sy + 8), "—", font=font_list_badge, fill=(70, 75, 86, 255))

        # Divider
        div_y = body_y + 184
        draw.line((right_x + 16, div_y, right_x + right_w - 16, div_y), fill=(46, 50, 60, 255), width=1)

        # Sub-header 2: Top Chatters
        draw.text((right_x + 20, div_y + 14), "Top Chatters Leaderboard", font=font_box_title, fill=(255, 255, 255, 255))
        draw.text((right_x + right_w - 32, div_y + 14), "@", font=font_box_title, fill=(110, 115, 126, 255))

        chat_y = div_y + 44
        for slot in range(1, 4):
            sy = chat_y + (slot - 1) * ch_h
            draw_rounded_rect(draw, (right_x + 12, sy, right_x + right_w - 12, sy + 34), radius=9, fill=row_fill)
            if slot <= len(top_chatters):
                m_name, m_cnt = top_chatters[slot - 1]
                draw.text((right_x + 24, sy + 8), str(slot), font=font_list_badge, fill=(245, 158, 11, 255) if slot == 1 else (150, 155, 166, 255))
                m_text = f"@{clean_display_name(m_name, max_len=18)}"
                draw.text((right_x + 52, sy + 8), m_text, font=font_list, fill=(235, 238, 242, 255))
                cnt_str = f"{m_cnt:,} msgs"
                c_box = font_list_badge.getbbox(cnt_str)
                cw = (c_box[2] - c_box[0]) + 18
                cx = right_x + right_w - 20 - cw
                draw_rounded_rect(draw, (cx, sy + 4, cx + cw, sy + 30), radius=7, fill=badge_fill)
                draw.text((cx + 9, sy + 8), cnt_str, font=font_list_badge, fill=(255, 255, 255, 255))
            else:
                draw.text((right_x + 24, sy + 8), str(slot), font=font_list_badge, fill=(70, 75, 86, 255))
                draw.text((right_x + 52, sy + 8), "@ —", font=font_list, fill=(75, 80, 92, 255))
                draw.text((right_x + right_w - 36, sy + 8), "—", font=font_list_badge, fill=(70, 75, 86, 255))

        # 4. Row 3: Server Demographics & Voice Telemetry Ribbon (4 Badges)
        ribbon_y = 582
        ribbon_h = 114
        rw_w = 238
        rw_space = 18

        ribbon_cards = [
            ("VOICE TELEMETRY", f"{voice_hours:.1f} Total Hours", "Recorded voice room duration"),
            ("SERVER CHANNELS", f"{text_count + voice_count} Channels", f"{text_count} Text • {voice_count} VC • {cat_count} Cat"),
            ("DEMOGRAPHICS", f"{member_count:,} Members", f"{humans_count} Humans • {bots_count} Bots"),
            ("CONFIGURATION", f"{roles_count} Roles Configured", f"Created {created_date_str}")
        ]

        for idx, (head_t, val_t, sub_t) in enumerate(ribbon_cards):
            rx = 38 + idx * (rw_w + rw_space)
            draw_rounded_rect(draw, (rx, ribbon_y, rx + rw_w, ribbon_y + ribbon_h), radius=14, fill=inner_fill, outline=inner_outline, width=1)
            draw.text((rx + 16, ribbon_y + 14), head_t, font=font_ribbon_lbl, fill=ribbon_lbl_fill)
            draw.text((rx + 16, ribbon_y + 36), val_t, font=font_ribbon_val, fill=(255, 255, 255, 255))
            draw.text((rx + 16, ribbon_y + 68), sub_t, font=font_ribbon_sub, fill=ribbon_sub_fill)

        # 5. Footer
        footer_y = H - 36
        draw.text((38, footer_y), footer_left, font=font_footer, fill=(115, 120, 130, 255))
        fb = font_footer_bold.getbbox(footer_right)
        draw.text((W - 38 - (fb[2] - fb[0]), footer_y), footer_right, font=font_footer_bold, fill=(150, 155, 166, 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf

    def render_member_matrix_card(
        self,
        member_name: str,
        avatar_img: Image.Image,
        joined_str: str,
        created_str: str,
        rank_num: int,
        total_chatters: int,
        level_num: int,
        current_xp: int,
        required_xp: int,
        xp_percentage: float,
        top_role_str: str,
        voice_str: str,
        user_tag: str,
        user_id_str: str,
        kpi_metrics: list, # [(Today, val), (Week, val), (Month, val), (Year, val), (Lifetime, val)]
        chart_labels: list,
        chart_values: list,
        top_channels: list, # [(name, count), ...]
        footer_left: str,
        footer_right: str = "Powered by Friday",
        voice_rank_num: int = 0,
        voice_today_str: str = "0m",
        guild_id: int = None
    ) -> io.BytesIO:
        """Renders comprehensive 1080x760 Master Member Telemetry & Activity Card."""
        W, H = 1080, 760

        # Check custom wallpaper for activity card
        raw_bg = None
        bg_img = None
        custom_bg = resolve_card_background(db.activity_card_backgrounds.get(str(guild_id))) if guild_id else None
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
                _blurred = raw_bg.filter(ImageFilter.GaussianBlur(radius=5))
                bg_img = ImageEnhance.Brightness(_blurred).enhance(0.78)
            except Exception:
                raw_bg = bg_img = None

        if not bg_img:
            img = Image.new("RGBA", (W, H), (19, 20, 23, 255))
        else:
            img = bg_img.copy()

        # Outer rounded container (Frosted glass when custom wallpaper is set)
        container_fill = (20, 22, 28, 205) if raw_bg else (28, 30, 36, 255)
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        draw_rounded_rect(od, (12, 12, W - 12, H - 12), radius=26, fill=container_fill, outline=(255, 255, 255, 38) if raw_bg else (42, 45, 54, 255), width=2)
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        font_title = get_unicode_font(22, bold=True)
        font_sub = get_unicode_font(13)
        font_pill = get_unicode_font(11, bold=True)
        font_kpi_lbl = get_unicode_font(11, bold=True)
        font_kpi_val = get_unicode_font(26, bold=True)
        font_box_title = get_unicode_font(15, bold=True)
        font_axis = get_unicode_font(11)
        font_list = get_unicode_font(13)
        font_list_badge = get_unicode_font(12, bold=True)
        font_ribbon_lbl = get_unicode_font(10, bold=True)
        font_ribbon_val = get_unicode_font(15, bold=True)
        font_ribbon_sub = get_unicode_font(11)
        font_footer = get_unicode_font(11)
        font_footer_bold = get_unicode_font(11, bold=True)

        accent_color = extract_accent_color(raw_bg, default_rgb=(129, 140, 248)) if raw_bg else (129, 140, 248)
        import colorsys as _cs
        if raw_bg:
            _ar, _ag, _ab = accent_color
            _h, _s, _v = _cs.rgb_to_hsv(_ar/255, _ag/255, _ab/255)
            _tr, _tg, _tb = _cs.hsv_to_rgb(_h, min(_s*1.2, 1.0), max(_v, 0.95))
            text_accent = (int(_tr*255), int(_tg*255), int(_tb*255))
        else:
            text_accent = (200, 205, 215)
        inner_fill = (25, 28, 36, 100) if raw_bg else (35, 38, 46, 255)
        inner_outline = (255, 255, 255, 30) if raw_bg else (48, 52, 63, 255)
        row_fill = (20, 22, 30, 80) if raw_bg else (29, 31, 38, 255)
        badge_fill = (20, 22, 30, 80) if raw_bg else (38, 41, 50, 255)
        lbl_fill = text_accent + (200,) if raw_bg else (155, 160, 169, 255)
        sub_fill = text_accent + (160,) if raw_bg else (142, 146, 155, 255)
        axis_fill = text_accent + (140,) if raw_bg else (115, 120, 131, 255)
        ribbon_lbl_fill = text_accent + (190,) if raw_bg else (150, 155, 166, 255)
        ribbon_sub_fill = text_accent + (150,) if raw_bg else (125, 130, 142, 255)

        # 1. Header
        header_x, header_y = 38, 30
        if avatar_img:
            try:
                icon_resized = avatar_img.convert("RGBA").resize((60, 60), Image.Resampling.LANCZOS)
                mask = Image.new("L", (60, 60), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, 60, 60), fill=255)
                img.paste(icon_resized, (header_x, header_y), mask)
                draw.ellipse((header_x, header_y, header_x + 60, header_y + 60), outline=(55, 60, 72, 255), width=2)
            except Exception:
                pass

        text_x = header_x + 74
        draw.text((text_x, header_y + 4), clean_display_name(member_name, max_len=24), font=font_title, fill=(255, 255, 255, 255))
        draw.text((text_x, header_y + 32), f"Joined {joined_str} • Account Created {created_str}", font=font_sub, fill=(142, 146, 155, 255))

        # Top-right status pills (Statbot-inspired richness: Level, Msg Rank, Voice Rank, Top Role)
        pills = [
            f"Level {level_num}",
            f"Rank #{rank_num}" if rank_num > 0 else "Unranked",
            f"Voice #{voice_rank_num}" if voice_rank_num > 0 else None,
            clean_display_name(top_role_str, max_len=14)
        ]
        pills = [p for p in pills if p]
        pill_right = W - 38
        for p in reversed(pills):
            bbox = font_pill.getbbox(p)
            pw = (bbox[2] - bbox[0]) + 22
            px = pill_right - pw
            py = header_y + 12
            draw_rounded_rect(draw, (px, py, px + pw, py + 30), radius=15, fill=(38, 41, 49, 255), outline=(52, 56, 67, 255), width=1)
            draw.text((px + 11, py + 7), p, font=font_pill, fill=(240, 242, 245, 255))
            pill_right = px - 10

        # 2. Row 1: 5 Full-Horizon Metric Cards
        kpi_y = 104
        kpi_h = 76
        card_w = 190
        spacing = 13
        for idx, (label, val_num) in enumerate(kpi_metrics[:5]):
            cx = 38 + idx * (card_w + spacing)
            draw_rounded_rect(draw, (cx, kpi_y, cx + card_w, kpi_y + kpi_h), radius=14, fill=inner_fill, outline=inner_outline, width=1)
            draw.text((cx + 16, kpi_y + 11), label.upper(), font=font_kpi_lbl, fill=lbl_fill)
            draw.text((cx + 16, kpi_y + 31), f"{val_num:,}", font=font_kpi_val, fill=(255, 255, 255, 255))

            # Status dot
            ix = cx + card_w - 22
            iy = kpi_y + 16
            draw.ellipse((ix, iy, ix + 6, iy + 6), fill=accent_color + (255,))

        # 3. Row 2: Middle Section (Left: Trend Spline Chart | Right: Top Channels)
        body_y = 196
        body_h = 370
        left_w = 540
        right_x = 594
        right_w = W - 38 - right_x

        # Left Container: Personal 7-Day Chart
        draw_rounded_rect(draw, (38, body_y, 38 + left_w, body_y + body_h), radius=18, fill=inner_fill, outline=inner_outline, width=1)
        draw.text((58, body_y + 16), "Personal 7-Day Activity Trend", font=font_box_title, fill=(255, 255, 255, 255))

        legend_text = "Messages"
        leg_bbox = font_axis.getbbox(legend_text)
        leg_x = 38 + left_w - 26 - (leg_bbox[2] - leg_bbox[0])
        draw.ellipse((leg_x - 14, body_y + 22, leg_x - 6, body_y + 30), fill=accent_color + (255,))
        draw.text((leg_x, body_y + 19), legend_text, font=font_axis, fill=sub_fill)

        plot_x = 94
        plot_y = body_y + 64
        plot_w = left_w - 82
        plot_h = 230
        baseline_y = plot_y + plot_h

        max_val = max(chart_values) if chart_values and max(chart_values) > 0 else 10
        if max_val <= 10: max_y = 10
        elif max_val <= 50: max_y = math.ceil(max_val / 10) * 10
        elif max_val <= 500: max_y = math.ceil(max_val / 50) * 50
        else: max_y = math.ceil(max_val / 100) * 100

        for step in range(4):
            val = int(max_y * (3 - step) / 3)
            gy = plot_y + int(plot_h * step / 3)
            draw.line((plot_x, gy, plot_x + plot_w, gy), fill=(44, 48, 58, 255), width=1)
            val_str = f"{val:,}"
            draw.text((plot_x - 48, gy - 7), val_str, font=font_axis, fill=axis_fill)

        raw_points = []
        num_pts = len(chart_values)
        for i, v in enumerate(chart_values):
            cx = plot_x + int(i * (plot_w / max(1, num_pts - 1)))
            cy = baseline_y - int((v / max_y) * plot_h)
            raw_points.append((cx, cy))

        raw_spline = monotone_cubic_spline(raw_points, num_subdivisions=16)
        spline_points = [(p[0], min(baseline_y, max(plot_y, p[1]))) for p in raw_spline]

        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        poly_points = [(plot_x, baseline_y)] + spline_points + [(plot_x + plot_w, baseline_y)]
        overlay_draw.polygon(poly_points, fill=accent_color + (36,))
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        for i in range(len(spline_points) - 1):
            draw.line([spline_points[i], spline_points[i+1]], fill=accent_color + (255,), width=3)

        for i, (px, py) in enumerate(raw_points):
            draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=(28, 30, 36, 255), outline=accent_color + (255,), width=2)
            draw.ellipse((px - 2, py - 2, px + 2, py + 2), fill=(255, 255, 255, 255))
            if i < len(chart_labels):
                lbl = chart_labels[i]
                l_bbox = font_axis.getbbox(lbl)
                lw = l_bbox[2] - l_bbox[0]
                draw.text((px - lw // 2, baseline_y + 14), lbl, font=font_axis, fill=axis_fill)

        # Right Container: Top Channels (5 slots)
        draw_rounded_rect(draw, (right_x, body_y, right_x + right_w, body_y + body_h), radius=18, fill=inner_fill, outline=inner_outline, width=1)
        draw.text((right_x + 20, body_y + 16), "Top Channels Chatted", font=font_box_title, fill=(255, 255, 255, 255))
        draw.text((right_x + right_w - 32, body_y + 16), "#", font=font_box_title, fill=(110, 115, 126, 255))

        row_y = body_y + 54
        row_h = 58
        for slot in range(1, 6):
            ry = row_y + (slot - 1) * row_h
            draw_rounded_rect(draw, (right_x + 12, ry, right_x + right_w - 12, ry + 46), radius=10, fill=row_fill)
            if slot <= len(top_channels):
                name_str, count_val = top_channels[slot - 1]
                draw.text((right_x + 24, ry + 13), str(slot), font=font_list_badge, fill=(255, 255, 255, 255) if slot <= 3 else (140, 145, 155, 255))
                clean_name = safe_channel_label(name_str, max_len=18)
                c_name = clean_name if clean_name.startswith("#") else f"# {clean_name}"
                draw.text((right_x + 52, ry + 13), c_name, font=font_list, fill=(235, 238, 242, 255))
                c_str = f"{count_val:,} msgs"
                c_bbox = font_list_badge.getbbox(c_str)
                cw = (c_bbox[2] - c_bbox[0]) + 18
                cx = right_x + right_w - 20 - cw
                draw_rounded_rect(draw, (cx, ry + 8, cx + cw, ry + 38), radius=8, fill=badge_fill)
                draw.text((cx + 9, ry + 13), c_str, font=font_list_badge, fill=(255, 255, 255, 255))
            else:
                draw.text((right_x + 24, ry + 13), str(slot), font=font_list_badge, fill=(70, 75, 86, 255))
                draw.text((right_x + 52, ry + 13), "# —", font=font_list, fill=(75, 80, 92, 255))
                draw.text((right_x + right_w - 36, ry + 13), "—", font=font_list_badge, fill=(70, 75, 86, 255))

        # 4. Row 3: Level & XP Progression Ribbon + Telemetry
        ribbon_y = 582
        ribbon_h = 114

        # Left Ribbon: XP & Level Progress
        rx1 = 38
        rw1 = 540
        draw_rounded_rect(draw, (rx1, ribbon_y, rx1 + rw1, ribbon_y + ribbon_h), radius=14, fill=inner_fill, outline=inner_outline, width=1)
        draw.text((rx1 + 18, ribbon_y + 14), "LEVEL & XP PROGRESSION", font=font_ribbon_lbl, fill=ribbon_lbl_fill)
        draw.text((rx1 + 18, ribbon_y + 34), f"Level {level_num}", font=font_ribbon_val, fill=(255, 255, 255, 255))
        draw.text((rx1 + 110, ribbon_y + 36), f"• {current_xp:,} / {required_xp:,} XP ({xp_percentage:.1f}%)", font=font_ribbon_sub, fill=ribbon_sub_fill)

        # Glowing Progress Bar (ADAPTIVE ACCENT COLOR!)
        bar_x = rx1 + 18
        bar_y = ribbon_y + 68
        bar_w = rw1 - 36
        bar_h = 18
        draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=9, fill=(26, 28, 34, 200) if raw_bg else (26, 28, 34, 255))
        fill_len = int(bar_w * (min(100.0, max(2.0, xp_percentage)) / 100.0))
        if fill_len > 0:
            draw_rounded_rect(draw, (bar_x, bar_y, bar_x + fill_len, bar_y + bar_h), radius=9, fill=accent_color + (255,))

        # Right Ribbon: Voice, Standing, Identity
        rx2 = 594
        rw2 = W - 38 - rx2
        draw_rounded_rect(draw, (rx2, ribbon_y, rx2 + rw2, ribbon_y + ribbon_h), radius=14, fill=inner_fill, outline=inner_outline, width=1)
        
        draw.text((rx2 + 18, ribbon_y + 14), "VOICE TELEMETRY", font=font_ribbon_lbl, fill=ribbon_lbl_fill)
        draw.text((rx2 + 18, ribbon_y + 34), voice_str, font=font_ribbon_val, fill=(255, 255, 255, 255))
        voice_sub_str = f"Voice Rank #{voice_rank_num} • Today: {voice_today_str}" if voice_rank_num > 0 else (f"Today: {voice_today_str}" if voice_today_str != "0s" else "Total recorded VC time")
        draw.text((rx2 + 18, ribbon_y + 68), voice_sub_str, font=font_ribbon_sub, fill=ribbon_sub_fill)

        col2_x = rx2 + 220
        draw.text((col2_x, ribbon_y + 14), "SERVER STANDING", font=font_ribbon_lbl, fill=ribbon_lbl_fill)
        draw.text((col2_x, ribbon_y + 34), f"Msg #{rank_num}" if rank_num > 0 else "Unranked", font=font_ribbon_val, fill=(255, 255, 255, 255))
        top_pct = max(1, round((rank_num / max(1, total_chatters)) * 100)) if (rank_num > 0 and total_chatters > 0) else 0
        standing_sub = f"Top {top_pct}% of {total_chatters:,} chatters" if top_pct > 0 else f"Out of {total_chatters:,} chatters"
        draw.text((col2_x, ribbon_y + 68), standing_sub, font=font_ribbon_sub, fill=ribbon_sub_fill)

        # 5. Footer
        footer_y = H - 36
        draw.text((38, footer_y), footer_left, font=font_footer, fill=(115, 120, 130, 255))
        fb = font_footer_bold.getbbox(footer_right)
        draw.text((W - 38 - (fb[2] - fb[0]), footer_y), footer_right, font=font_footer_bold, fill=(150, 155, 166, 255))

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
        max_msgs: int = 1,
        guild_id: int = None
    ) -> io.BytesIO:
        """Renders high-resolution 1020x640 graphic leaderboard card with 10 members per page in a 2-column grid."""
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
                _blurred = raw_bg.filter(ImageFilter.GaussianBlur(radius=5))
                bg_img = ImageEnhance.Brightness(_blurred).enhance(0.78)
            except Exception:
                raw_bg = bg_img = None

        if not bg_img:
            img = Image.new("RGBA", (W, H), (19, 20, 23, 255))
        else:
            img = bg_img.copy()

        # Outer Container (Frosted glass when custom wallpaper is set)
        container_fill = (20, 22, 28, 205) if raw_bg else (28, 30, 36, 255)
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        draw_rounded_rect(od, (12, 12, W - 12, H - 12), radius=26, fill=container_fill, outline=(255, 255, 255, 38) if raw_bg else (42, 45, 54, 255), width=2)
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        accent_color = extract_accent_color(raw_bg, default_rgb=(56, 189, 248)) if raw_bg else (56, 189, 248)
        import colorsys as _cs
        if raw_bg:
            _ar, _ag, _ab = accent_color
            _h, _s, _v = _cs.rgb_to_hsv(_ar/255, _ag/255, _ab/255)
            _tr, _tg, _tb = _cs.hsv_to_rgb(_h, min(_s*1.2, 1.0), max(_v, 0.95))
            text_accent = (int(_tr*255), int(_tg*255), int(_tb*255))
        else:
            text_accent = (200, 205, 215)
        card_item_fill = (25, 28, 36, 110) if raw_bg else (35, 38, 46, 255)
        card_item_outline = (255, 255, 255, 30) if raw_bg else (48, 52, 63, 255)
        badge_count_fill = (20, 22, 30, 80) if raw_bg else (28, 30, 37, 255)

        font_title = get_unicode_font(22, bold=True)
        font_sub = get_unicode_font(13)
        font_pill = get_unicode_font(12, bold=True)
        font_name = get_unicode_font(14, bold=True)
        font_user = get_unicode_font(11)
        font_rank = get_unicode_font(13, bold=True)
        font_cnt = get_unicode_font(13, bold=True)
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
        draw.text((text_x, header_y + 34), f"Top Chatters Leaderboard • {timeframe_name}", font=font_sub, fill=(142, 146, 155, 255))

        # Status pills
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

            draw_rounded_rect(draw, (cx, cy, cx + col_w, cy + row_h), radius=14, fill=card_item_fill, outline=card_item_outline, width=1)

            if current_rank in m_dict:
                _, name_str, user_str, av_img, cnt = m_dict[current_rank]

                ratio = cnt / max(1, max_msgs)
                fill_w = int(col_w * min(1.0, max(0.02, ratio)))
                if fill_w > 0:
                    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    od = ImageDraw.Draw(overlay)
                    draw_rounded_rect(od, (cx, cy, cx + fill_w, cy + row_h), radius=14, fill=accent_color + (28,))
                    img = Image.alpha_composite(img, overlay)
                    draw = ImageDraw.Draw(img)

                if current_rank == 1:
                    r_fill, r_out, r_txt = (60, 45, 15, 255), (217, 119, 6, 255), (245, 158, 11, 255)
                elif current_rank == 2:
                    r_fill, r_out, r_txt = (40, 45, 55, 255), (148, 163, 184, 255), (203, 213, 225, 255)
                elif current_rank == 3:
                    r_fill, r_out, r_txt = (55, 30, 15, 255), (234, 88, 12, 255), (249, 115, 22, 255)
                else:
                    r_fill, r_out, r_txt = (20, 22, 30, 150) if raw_bg else (28, 30, 36, 255), (255, 255, 255, 40) if raw_bg else (46, 50, 60, 255), text_accent if raw_bg else (150, 155, 166, 255)

                draw_rounded_rect(draw, (cx + 12, cy + 24, cx + 48, cy + 56), radius=10, fill=r_fill, outline=r_out, width=1)
                r_str = f"#{current_rank}"
                rb = font_rank.getbbox(r_str)
                rw = rb[2] - rb[0]
                draw.text((cx + 12 + (36 - rw) // 2, cy + 32), r_str, font=font_rank, fill=r_txt)

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
                    draw.ellipse((av_x, av_y, av_x + 44, av_y + 44), fill=(88, 101, 242, 255))
                    c_letter = clean_display_name(name_str)[0].upper() if name_str else '?'
                    ab = font_pill.getbbox(c_letter)
                    draw.text((av_x + (44 - (ab[2] - ab[0])) // 2, av_y + 14), c_letter, font=font_pill, fill=(255, 255, 255, 255))

                tx = av_x + 54
                draw.text((tx, cy + 20), clean_display_name(name_str, max_len=16), font=font_name, fill=(255, 255, 255, 255))
                draw.text((tx, cy + 44), f"@{clean_display_name(user_str, max_len=18)}", font=font_user, fill=text_accent + (160,) if raw_bg else (130, 135, 146, 255))

                cnt_str = f"{cnt:,} msgs"
                cb = font_cnt.getbbox(cnt_str)
                cw = (cb[2] - cb[0]) + 20
                cpx = cx + col_w - 14 - cw
                draw_rounded_rect(draw, (cpx, cy + 24, cpx + cw, cy + 56), radius=10, fill=badge_count_fill, outline=(255, 255, 255, 30) if raw_bg else (48, 52, 63, 255), width=1)
                draw.text((cpx + 10, cy + 32), cnt_str, font=font_cnt, fill=(255, 255, 255, 255))
            else:
                draw.text((cx + 18, cy + 30), f"#{current_rank}  — No more recorded chatters —", font=font_sub, fill=(75, 80, 92, 255))

        footer_y = H - 36
        draw.text((38, footer_y), "Use the Previous and Next buttons below to navigate pages • Timezone: IST", font=font_footer, fill=(115, 120, 130, 255))
        fb = font_footer_bold.getbbox("Powered by Friday")
        draw.text((W - 38 - (fb[2] - fb[0]), footer_y), "Powered by Friday", font=font_footer_bold, fill=(150, 155, 166, 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf

    async def generate_server_card_file(self, guild: discord.Guild, viewer: Optional[discord.Member] = None) -> discord.File:
        gid = guild.id
        icon_img = await self.fetch_avatar_image(guild)
        labels, values = self.get_daily_trend(gid, days=7)
        srv_stats = self.get_server_stats(gid)

        humans_count = sum(1 for m in guild.members if not m.bot)
        bots_count = sum(1 for m in guild.members if m.bot)
        member_count = guild.member_count or len(guild.members)
        text_count = len(guild.text_channels)
        voice_count = len(guild.voice_channels)
        cat_count = len(guild.categories)
        roles_count = len(guild.roles)
        owner_name = clean_display_name(guild.owner.display_name if guild.owner else "Unknown")
        created_str = guild.created_at.strftime("%B %d, %Y") if guild.created_at else "Unknown"

        voice_hours = round(srv_stats["voice_lifetime_sec"] / 3600, 1)

        # Top 3 Channels with guaranteed safe labels and viewer permission privacy
        top_raw_channels = self.get_top_channels_list(gid, limit=3)
        top_channels = []
        for cid, total in top_raw_channels:
            cid_int = int(cid) if str(cid).isdigit() else 0
            ch = guild.get_channel_or_thread(cid_int) if hasattr(guild, "get_channel_or_thread") else guild.get_channel(cid_int)
            is_hidden = False
            if ch:
                if viewer and isinstance(viewer, discord.Member):
                    perms = ch.permissions_for(viewer)
                    if not perms.view_channel or not perms.read_messages:
                        is_hidden = True
                else:
                    d_perms = ch.permissions_for(guild.default_role)
                    if not d_perms.view_channel:
                        is_hidden = True
            if is_hidden:
                top_channels.append(("🔒 Private Channel", total))
            else:
                raw_c_name = await self.get_channel_display_name(guild, cid)
                top_channels.append((safe_channel_label(raw_c_name, cid=cid), total))

        # Top 3 Chatters
        top_raw_chatters = self.get_leaderboard(gid, timeframe="lifetime", limit=3, offset=0)
        top_chatters = []
        for uid, total in top_raw_chatters:
            m = guild.get_member(int(uid))
            name = clean_display_name(m.display_name if m else f"User {uid[-4:]}", max_len=18)
            top_chatters.append((name, total))

        kpi_metrics = [
            ("Today", srv_stats["today"]),
            ("Week (7d)", srv_stats["week"]),
            ("Month (30d)", srv_stats["month"]),
            ("Year (365d)", srv_stats["year"]),
            ("Lifetime", srv_stats["lifetime"])
        ]

        buf = self.render_server_matrix_card(
            guild_name=guild.name,
            guild_icon=icon_img,
            owner_name=owner_name,
            created_date_str=created_str,
            boost_tier=guild.premium_tier,
            boost_count=guild.premium_subscription_count or 0,
            member_count=member_count,
            humans_count=humans_count,
            bots_count=bots_count,
            text_count=text_count,
            voice_count=voice_count,
            cat_count=cat_count,
            roles_count=roles_count,
            voice_hours=voice_hours,
            kpi_metrics=kpi_metrics,
            chart_labels=labels,
            chart_values=values,
            top_channels=top_channels,
            top_chatters=top_chatters,
            footer_left=f"Server Demographics & Telemetry Matrix • Server ID: {guild.id} • Timezone: UTC",
            footer_right="Powered by Friday",
            guild_id=guild.id
        )
        return discord.File(fp=buf, filename=f"server_matrix_{guild.id}.png")

    async def generate_member_card_file(self, guild: discord.Guild, member: discord.Member, viewer: Optional[discord.Member] = None) -> discord.File:
        gid = guild.id
        uid = member.id
        avatar_img = await self.fetch_avatar_image(member)
        labels, values = self.get_daily_trend(gid, user_id=uid, days=7)
        m_stats = self.get_member_stats(gid, uid)

        # Top 5 channels with guaranteed safe labels and viewer permission privacy
        top_raw = self.get_top_channels_list(gid, user_id=uid, limit=5)
        top_channels = []
        for cid, total in top_raw:
            cid_int = int(cid) if str(cid).isdigit() else 0
            ch = guild.get_channel_or_thread(cid_int) if hasattr(guild, "get_channel_or_thread") else guild.get_channel(cid_int)
            is_hidden = False
            if ch:
                if viewer and isinstance(viewer, discord.Member):
                    perms = ch.permissions_for(viewer)
                    if not perms.view_channel or not perms.read_messages:
                        is_hidden = True
                else:
                    d_perms = ch.permissions_for(guild.default_role)
                    if not d_perms.view_channel:
                        is_hidden = True
            if is_hidden:
                top_channels.append(("🔒 Private Channel", total))
            else:
                raw_c_name = await self.get_channel_display_name(guild, cid)
                top_channels.append((safe_channel_label(raw_c_name, cid=cid), total))

        joined_str = member.joined_at.strftime("%B %d, %Y") if member.joined_at else "Unknown"
        created_str = member.created_at.strftime("%B %d, %Y") if member.created_at else "Unknown"

        top_role = member.top_role.name if (member.top_role and member.top_role.name != "@everyone") else "Member"

        # Level & XP Progression
        gid_str, uid_str = str(gid), str(uid)
        xp_info = db.xp_data.get(gid_str, {}).get(uid_str, {"xp": 0, "level": 0})
        curr_xp = xp_info.get("xp", 0)
        level_num = xp_info.get("level", 0)
        # Standard transparent formula: 5*(L^2) + 50*L + 100
        req_xp = int(5 * (level_num ** 2) + 50 * level_num + 100)
        xp_percentage = min(100.0, (curr_xp / req_xp) * 100.0) if req_xp > 0 else 0.0

        voice_str = self.format_duration(m_stats["voice_lifetime"])
        voice_today_str = self.format_duration(m_stats.get("voice_today", 0))
        voice_rank_num = m_stats.get("voice_rank", 0)

        kpi_metrics = [
            ("Today", m_stats["today"]),
            ("Week (7d)", m_stats["week"]),
            ("Month (30d)", m_stats["month"]),
            ("Year (365d)", m_stats["year"]),
            ("Lifetime", m_stats["lifetime"])
        ]

        buf = self.render_member_matrix_card(
            member_name=member.display_name,
            avatar_img=avatar_img,
            joined_str=joined_str,
            created_str=created_str,
            rank_num=m_stats["rank"],
            total_chatters=m_stats["total_chatters"],
            level_num=level_num,
            current_xp=curr_xp,
            required_xp=req_xp,
            xp_percentage=xp_percentage,
            top_role_str=top_role,
            voice_str=voice_str,
            user_tag=member.name,
            user_id_str=str(member.id),
            kpi_metrics=kpi_metrics,
            chart_labels=labels,
            chart_values=values,
            top_channels=top_channels,
            footer_left=f"Member Telemetry Matrix • Tag: @{clean_display_name(member.name)} • User ID: {member.id} • Timezone: UTC",
            footer_right="Powered by Friday",
            voice_rank_num=voice_rank_num,
            voice_today_str=voice_today_str,
            guild_id=guild.id
        )
        return discord.File(fp=buf, filename=f"member_matrix_{member.id}.png")

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

        async def fetch_item(rank_num, uid, count):
            mem = guild.get_member(int(uid))
            name = mem.display_name if mem else f"User {uid[-4:]}"
            username = mem.name if mem else f"id_{uid}"
            av = await self.fetch_avatar_image(mem or uid)
            return (rank_num, name, username, av, count)

        tasks_list = [fetch_item(offset + i, uid, count) for i, (uid, count) in enumerate(raw_list, start=1)]
        members_data = await asyncio.gather(*tasks_list) if tasks_list else []

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
            max_msgs=max_msgs,
            guild_id=guild.id
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
        file = await self.generate_member_card_file(interaction.guild, target, viewer=interaction.user)
        await interaction.followup.send(file=file)

    @activity_group.command(name="server", description="View custom graphic analytics dashboard for the server.")
    async def activity_server(self, interaction: discord.Interaction):
        await interaction.response.defer()
        file = await self.generate_server_card_file(interaction.guild, viewer=interaction.user)
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

    # ─── User shortcut: /my stats ───
    @my_group.command(name="stats", description="View your personal chat activity and message stats graphic card.")
    async def my_stats(self, interaction: discord.Interaction):
        await interaction.response.defer()
        file = await self.generate_member_card_file(interaction.guild, interaction.user, viewer=interaction.user)
        await interaction.followup.send(file=file)

    # ─── Unified /leaderboard commands (Messages & XP) ───
    leaderboard_group = app_commands.Group(name="leaderboard", description="View server leaderboards for messages or XP.")

    @leaderboard_group.command(name="msg", description="View custom graphic leaderboard of members with most messages.")
    @app_commands.choices(timeframe=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week (7 Days)", value="week"),
        app_commands.Choice(name="This Month (30 Days)", value="month"),
        app_commands.Choice(name="This Year (365 Days)", value="year"),
        app_commands.Choice(name="Lifetime", value="lifetime")
    ])
    async def lb_msg(self, interaction: discord.Interaction, timeframe: app_commands.Choice[str] = None):
        await interaction.response.defer()
        tf = timeframe.value if timeframe else "lifetime"
        view = ActivityLeaderboardView(self, interaction.guild, current_tf=tf, current_page=1)
        file = await self.generate_leaderboard_card_file(interaction.guild, tf, page=1)
        await interaction.followup.send(file=file, view=view)

    @leaderboard_group.command(name="xp", description="View custom graphic leaderboard of top members by XP and level.")
    async def lb_xp(self, interaction: discord.Interaction):
        await interaction.response.defer()
        lvl_cog = self.bot.get_cog("Leveling")
        if not lvl_cog:
            await interaction.followup.send("Leveling module is currently offline.")
            return
        from cogs.leveling import XPLeaderboardView
        view = XPLeaderboardView(lvl_cog, interaction.guild, current_page=1)
        file = await lvl_cog.generate_xp_leaderboard_file(interaction.guild, page=1)
        await interaction.followup.send(file=file, view=view)

    @leaderboard_group.command(name="invites", description="View custom graphic leaderboard of top inviters in the server.")
    async def lb_invites(self, interaction: discord.Interaction):
        inv_cog = self.bot.get_cog("InviteTracker")
        if not inv_cog:
            await interaction.response.send_message("❌ Invite Tracker module is currently offline.", ephemeral=True)
            return
        await inv_cog.invite_leaderboard(interaction)

class ActivityLeaderboardView(discord.ui.View):
    """
    Interactive pagination view for Leaderboard Image Cards.
    Provides clean '◀ Previous' and 'Next ▶' buttons and timeframe switcher with zero emojis.
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
            label="◀ Previous",
            style=discord.ButtonStyle.secondary,
            disabled=(self.current_page <= 1),
            row=0
        )
        prev_btn.callback = self.on_prev_clicked
        self.add_item(prev_btn)

        page_btn = discord.ui.Button(
            label=f"Page {self.current_page} / {total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=0
        )
        self.add_item(page_btn)

        next_btn = discord.ui.Button(
            label="Next ▶",
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
