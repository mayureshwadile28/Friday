import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import datetime
import os
import time
from database import db

# SQLite Database path inside data/ directory
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_FILE = os.path.join(DATA_DIR, "activity.db")

class Activity(commands.Cog):
    """
    Tracks and displays member and server chat & voice statistics across:
    Today, This Week (7 days), This Month (30 days), This Year (365 days), and Lifetime.
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

    def get_connection(self):
        conn = sqlite3.connect(DB_FILE, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

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
        """Flushes elapsed seconds for users currently connected to voice channels."""
        now = time.time()
        for (gid, uid), start_time in list(self.voice_sessions.items()):
            elapsed = int(now - start_time)
            if elapsed > 0:
                self.add_voice_seconds(gid, uid, elapsed)
                self.voice_sessions[(gid, uid)] = now

    @tasks.loop(minutes=5)
    async def flush_voice_loop(self):
        """Periodically sync active voice time so data isn't lost on crashes or restarts."""
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
            return f"{minutes}m {secs}s"
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

                # 1. Message counts across intervals
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

                # 2. Voice seconds across intervals
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

                # 3. Top active channel for member
                cursor.execute("""
                    SELECT channel_id, SUM(message_count) AS total
                    FROM channel_messages
                    WHERE guild_id = ? AND user_id = ?
                    GROUP BY channel_id
                    ORDER BY total DESC
                    LIMIT 1
                """, (gid_str, uid_str))
                c_row = cursor.fetchone()
                if c_row:
                    stats["top_channel_id"] = c_row["channel_id"]
                    stats["top_channel_msgs"] = c_row["total"]

                # 4. Chat rank in server
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
            "voice_lifetime_sec": 0,
            "top_channels": [],
            "top_chatters": []
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

                # Top 3 Channels
                cursor.execute("""
                    SELECT channel_id, SUM(message_count) AS total
                    FROM channel_messages
                    WHERE guild_id = ?
                    GROUP BY channel_id
                    ORDER BY total DESC
                    LIMIT 3
                """, (gid_str,))
                stats["top_channels"] = [(r["channel_id"], r["total"]) for r in cursor.fetchall()]

                # Top 3 Chatters
                cursor.execute("""
                    SELECT user_id, SUM(message_count) AS total
                    FROM member_messages
                    WHERE guild_id = ?
                    GROUP BY user_id
                    ORDER BY total DESC
                    LIMIT 3
                """, (gid_str,))
                stats["top_chatters"] = [(r["user_id"], r["total"]) for r in cursor.fetchall()]
        except Exception as e:
            print(f"⚠️ Activity DB get_server_stats error: {e}")

        return stats

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

    # ────────────────────────── Embed Builders ──────────────────────────

    def build_user_activity_embed(self, guild: discord.Guild, member: discord.Member) -> discord.Embed:
        gid = guild.id
        uid = member.id
        stats = self.get_member_stats(gid, uid)

        # Format Chat Stats Box
        rank_str = f" • Rank **#{stats['rank']}** of {stats['total_chatters']}" if stats['rank'] > 0 else ""
        chat_box = (
            f"```yaml\n"
            f"📅 Today:            {stats['today']:,} messages\n"
            f"📆 This Week (7d):   {stats['week']:,} messages\n"
            f"🗓️ This Month (30d):  {stats['month']:,} messages\n"
            f"📅 This Year (365d): {stats['year']:,} messages\n"
            f"🏆 Lifetime Total:   {stats['lifetime']:,} messages\n"
            f"```"
        )

        # Format Voice Stats Box
        voice_box = (
            f"```yaml\n"
            f"📅 Today:            {self.format_duration(stats['voice_today'])}\n"
            f"📆 This Week (7d):   {self.format_duration(stats['voice_week'])}\n"
            f"🗓️ This Month (30d):  {self.format_duration(stats['voice_month'])}\n"
            f"📅 This Year (365d): {self.format_duration(stats['voice_year'])}\n"
            f"🏆 Lifetime Total:   {self.format_duration(stats['voice_lifetime'])}\n"
            f"```"
        )

        # Member Parameters & Extra Server Data
        joined_str = f"<t:{int(member.joined_at.timestamp())}:R> (<t:{int(member.joined_at.timestamp())}:D>)" if member.joined_at else "Unknown"
        created_str = f"<t:{int(member.created_at.timestamp())}:R>"
        top_role = member.top_role.mention if member.top_role else "@everyone"
        roles_count = max(0, len(member.roles) - 1)

        # Check most active channel
        top_chan_str = "None yet"
        if stats["top_channel_id"]:
            ch = guild.get_channel(int(stats["top_channel_id"]))
            if ch:
                top_chan_str = f"{ch.mention} (`{stats['top_channel_msgs']:,}` msgs)"
            else:
                top_chan_str = f"`#{stats['top_channel_id']}` (`{stats['top_channel_msgs']:,}` msgs)"

        # Check leveling XP if active
        xp_entry = db.xp_data.get(str(gid), {}).get(str(uid), {})
        level_str = f"Level **{xp_entry.get('level', 0)}** ({xp_entry.get('xp', 0):,} XP)" if xp_entry else "Level 0 (0 XP)"

        # Check warnings count if any
        warns = len(db.warnings.get(str(gid), {}).get(str(uid), []))
        warn_str = f"⚠️ **{warns}** warnings" if warns > 0 else "🟢 Clean (0 warnings)"

        embed = discord.Embed(
            title=f"📊 Activity & Chat Analytics · {member.display_name}",
            description=f"Activity matrix and lifetime telemetry for {member.mention}{rank_str}:",
            color=member.color if member.color.value != 0 else discord.Color.blurple(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="💬 Chat Activity", value=chat_box, inline=False)
        embed.add_field(name="🎙️ Voice Channel Activity", value=voice_box, inline=False)

        info_lines = [
            f"🗓️ **Joined Server:** {joined_str}",
            f"👶 **Account Created:** {created_str}",
            f"🏷️ **Top Role:** {top_role} *({roles_count} roles total)*",
            f"💬 **Most Active In:** {top_chan_str}",
            f"⭐ **Level & Rank:** {level_str}",
            f"🛡️ **Mod Record:** {warn_str}"
        ]
        embed.add_field(name="📌 Member Parameters & Information", value="\n".join(info_lines), inline=False)
        embed.set_footer(text=f"Friday Analytics Matrix • User ID: {member.id}", icon_url=guild.icon.url if guild.icon else None)
        return embed

    def build_server_activity_embed(self, guild: discord.Guild) -> discord.Embed:
        gid = guild.id
        stats = self.get_server_stats(gid)

        chat_box = (
            f"```yaml\n"
            f"📅 Today:            {stats['today']:,} messages\n"
            f"📆 This Week (7d):   {stats['week']:,} messages\n"
            f"🗓️ This Month (30d):  {stats['month']:,} messages\n"
            f"📅 This Year (365d): {stats['year']:,} messages\n"
            f"🏆 Lifetime Recorded:{stats['lifetime']:,} messages\n"
            f"```"
        )

        voice_hours = round(stats["voice_lifetime_sec"] / 3600, 1)
        voice_box = (
            f"```yaml\n"
            f"🎙️ Recorded Voice Time: {voice_hours:,} total hours\n"
            f"```"
        )

        # Server demographics
        total_members = guild.member_count or len(guild.members)
        humans = sum(1 for m in guild.members if not m.bot)
        bots = sum(1 for m in guild.members if m.bot)

        text_chans = len(guild.text_channels)
        voice_chans = len(guild.voice_channels)
        cat_chans = len(guild.categories)
        role_count = len(guild.roles)

        boost_lvl = guild.premium_tier
        boost_cnt = guild.premium_subscription_count or 0
        owner_mention = guild.owner.mention if guild.owner else "Unknown"
        created_str = f"<t:{int(guild.created_at.timestamp())}:D> (<t:{int(guild.created_at.timestamp())}:R>)"

        # Hotspots
        chan_hotspots = []
        for cid, total in stats["top_channels"]:
            ch = guild.get_channel(int(cid))
            c_name = ch.mention if ch else f"`#{cid}`"
            chan_hotspots.append(f"{c_name} — **{total:,}** msgs")
        hotspots_str = "\n".join(chan_hotspots) if chan_hotspots else "*No channel messages recorded yet.*"

        user_hotspots = []
        for idx, (uid, total) in enumerate(stats["top_chatters"], start=1):
            mem = guild.get_member(int(uid))
            u_name = mem.mention if mem else f"`<@{uid}>`"
            medals = ["🥇", "🥈", "🥉"]
            medal = medals[idx-1] if idx <= 3 else f"#{idx}"
            user_hotspots.append(f"{medal} {u_name} — **{total:,}** msgs")
        chatters_str = "\n".join(user_hotspots) if user_hotspots else "*No user messages recorded yet.*"

        embed = discord.Embed(
            title=f"🏰 Server Demographics & Activity Matrix · {guild.name}",
            description=f"Real-time server-wide message volume, voice analytics, and telemetry:",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="💬 Server Message Volume", value=chat_box, inline=False)
        embed.add_field(name="🎙️ Server Voice Telemetry", value=voice_box, inline=False)

        demographics_lines = [
            f"👥 **Members:** **{total_members:,}** *(Humans: {humans:,} | Bots: {bots:,})*",
            f"📁 **Channels:** **{len(guild.channels)}** *(Text: {text_chans} | Voice: {voice_chans} | Categories: {cat_chans})*",
            f"🏷️ **Roles:** **{role_count}** roles configured",
            f"🚀 **Server Boost:** Level **{boost_lvl}** *({boost_cnt} boosts)*",
            f"👑 **Server Owner:** {owner_mention}",
            f"🗓️ **Created On:** {created_str}"
        ]
        embed.add_field(name="👥 Server Parameters & Demographics", value="\n".join(demographics_lines), inline=False)

        embed.add_field(name="🏆 Most Active Channels", value=hotspots_str, inline=True)
        embed.add_field(name="👑 Top Chatters", value=chatters_str, inline=True)

        embed.set_footer(text=f"Friday Server Matrix • Server ID: {guild.id}", icon_url=guild.icon.url if guild.icon else None)
        return embed

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
            title=f"🏆 Top Chatters Leaderboard · {title_time}",
            description=f"Showing the top {len(top_list)} most active members in **{guild.name}** for **{title_time}**:",
            color=discord.Color.brand_green(),
            timestamp=discord.utils.utcnow()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        if not top_list:
            embed.description = f"No activity recorded yet for **{title_time}**. Send a message to start charting!"
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for idx, (uid, count) in enumerate(top_list, start=1):
                medal = medals[idx-1] if idx <= 3 else f"`#{idx:02d}`"
                mem = guild.get_member(int(uid))
                user_label = mem.mention if mem else f"`<@{uid}>`"
                lines.append(f"{medal} **{user_label}** — `{count:,}` messages")
            embed.add_field(name="📈 Member Rankings", value="\n".join(lines), inline=False)

        embed.set_footer(text="Friday Activity Matrix • Click buttons below to switch timeframe!")
        return embed

    # ────────────────────────── Slash Commands ──────────────────────────

    activity_group = app_commands.Group(name="activity", description="Inspect member and server chat activity, voice telemetry, and leaderboards.")

    @activity_group.command(name="member", description="View chat activity (today/week/month/year/lifetime) and telemetry for a member.")
    @app_commands.describe(member="The member to inspect (defaults to yourself)")
    async def activity_member(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        embed = self.build_user_activity_embed(interaction.guild, target)
        await interaction.response.send_message(embed=embed)

    @activity_group.command(name="server", description="View server-wide chat activity, voice hours, demographics, and active hotspots.")
    async def activity_server(self, interaction: discord.Interaction):
        embed = self.build_server_activity_embed(interaction.guild)
        await interaction.response.send_message(embed=embed)

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

    # Standalone convenience aliases
    @app_commands.command(name="chatstats", description="Check message counts (today/week/month/year/lifetime) for a member.")
    @app_commands.describe(member="Member to view chat stats for (defaults to yourself)")
    async def chatstats_command(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        embed = self.build_user_activity_embed(interaction.guild, target)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="messages", description="View how many messages a member has sent today, this week, month, year, and lifetime.")
    @app_commands.describe(member="Member to view message counts for (defaults to yourself)")
    async def messages_command(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        embed = self.build_user_activity_embed(interaction.guild, target)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverstats", description="View server chat volume, voice activity, and member parameters.")
    async def serverstats_command(self, interaction: discord.Interaction):
        embed = self.build_server_activity_embed(interaction.guild)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="topchatters", description="View the top chatters in the server across various timeframes.")
    @app_commands.choices(timeframe=[
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week (7 Days)", value="week"),
        app_commands.Choice(name="This Month (30 Days)", value="month"),
        app_commands.Choice(name="This Year (365 Days)", value="year"),
        app_commands.Choice(name="Lifetime", value="lifetime")
    ])
    async def topchatters_command(self, interaction: discord.Interaction, timeframe: app_commands.Choice[str] = None):
        tf = timeframe.value if timeframe else "lifetime"
        embed = self.build_leaderboard_embed(interaction.guild, tf)
        view = ActivityLeaderboardView(self, interaction.guild, tf)
        await interaction.response.send_message(embed=embed, view=view)

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
            ("📅 Today", "today"),
            ("📆 Week", "week"),
            ("🗓️ Month", "month"),
            ("📅 Year", "year"),
            ("🏆 Lifetime", "lifetime")
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
