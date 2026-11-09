import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
from typing import Optional, List, Dict
import pytz
import re
from database import db
from response_utils import make_box_embed, reply_box
from emoji_utils import replace_plain_emojis

MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December"
}

MONTH_LOOKUP = {
    "jan": 1, "january": 1, "1": 1, "01": 1,
    "feb": 2, "february": 2, "2": 2, "02": 2,
    "mar": 3, "march": 3, "3": 3, "03": 3,
    "apr": 4, "april": 4, "4": 4, "04": 4,
    "may": 5, "5": 5, "05": 5,
    "jun": 6, "june": 6, "6": 6, "06": 6,
    "jul": 7, "july": 7, "7": 7, "07": 7,
    "aug": 8, "august": 8, "8": 8, "08": 8,
    "sep": 9, "sept": 9, "september": 9, "9": 9, "09": 9,
    "oct": 10, "october": 10, "10": 10,
    "nov": 11, "november": 11, "11": 11,
    "dec": 12, "december": 12, "12": 12
}

DAYS_IN_MONTH = {
    1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31
}


def parse_wish_time_hour_min(time_str: str) -> tuple[int, int]:
    """
    Parses various time formats into (hour, minute) 24-hr ints.
    Supports '00:00', '10:50', '10:50 AM', '10:50 PM', '22:50', etc.
    Defaults to (0, 0) for Midnight.
    """
    if not time_str or not isinstance(time_str, str):
        return (0, 0)
    cleaned = time_str.strip().upper()

    # 12-Hour AM/PM check
    if "AM" in cleaned or "PM" in cleaned:
        for fmt in ("%I:%M %p", "%I:%M%p", "%I %p"):
            try:
                dt = datetime.datetime.strptime(cleaned, fmt)
                return (dt.hour, dt.minute)
            except Exception:
                pass

    # 24-Hour HH:MM check
    try:
        parts = cleaned.split(":")
        if len(parts) >= 2:
            h = int(parts[0])
            m = int(parts[1][:2])
            return (max(0, min(23, h)), max(0, min(59, m)))
        elif len(parts) == 1 and parts[0].isdigit():
            h = int(parts[0])
            return (max(0, min(23, h)), 0)
    except Exception:
        pass

    return (0, 0)


class BirthdayModal(discord.ui.Modal, title="Register Your Birthday"):
    month_input = discord.ui.TextInput(
        label="Birth Month",
        placeholder="e.g. May or 5",
        required=True,
        max_length=15
    )
    day_input = discord.ui.TextInput(
        label="Birth Day (Date)",
        placeholder="e.g. 14 (between 1 and 31)",
        required=True,
        max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        gid = str(guild.id)
        uid = str(interaction.user.id)

        # 1. Anti-abuse / Lockout Check
        restricted_list = db.birthdays_restricted.get(gid, [])
        if uid in restricted_list:
            embed = make_box_embed(
                title="Registration Locked",
                description=(
                    "You have previously removed or reset your birthday.\n\n"
                    "To prevent exploit loops, self-registration is locked for your profile. "
                    "Please contact server administration or the bot owner to unlock your registration."
                ),
                status="error"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 2. Existing birthday check
        guild_bds = db.birthdays.setdefault(gid, {})
        if uid in guild_bds:
            existing = guild_bds[uid]
            m_name = MONTH_NAMES.get(existing.get("month", 1), "Unknown")
            d_val = existing.get("day", 1)
            embed = make_box_embed(
                title="Already Registered",
                description=(
                    f"Your birthday is already registered as **{m_name} {d_val}**.\n\n"
                    "To prevent date cycling, you cannot change it yourself. "
                    "If you made an honest mistake, please ask a server administrator to update it for you."
                ),
                status="info"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 3. Parse Month
        clean_month = self.month_input.value.strip().lower()
        month = MONTH_LOOKUP.get(clean_month)
        if not month:
            embed = make_box_embed(
                title="Invalid Month",
                description="Please enter a valid month name or number (e.g. `May`, `December`, or `5`).",
                status="error"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 4. Parse Day
        try:
            day = int(self.day_input.value.strip())
        except ValueError:
            embed = make_box_embed(
                title="Invalid Day",
                description="Please enter a valid day number (e.g. `14`).",
                status="error"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        max_days = DAYS_IN_MONTH.get(month, 31)
        if day < 1 or day > max_days:
            embed = make_box_embed(
                title="Invalid Day For Month",
                description=f"**{MONTH_NAMES[month]}** only has up to **{max_days}** days. Please enter a valid date.",
                status="error"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 5. Save Birthday
        guild_bds[uid] = {
            "user_id": uid,
            "user_name": interaction.user.display_name,
            "month": month,
            "day": day,
            "registered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "last_wished_year": 0
        }
        db.save_data()

        cfg = db.birthdays_config.get(gid, {})
        wish_chan_id = cfg.get("wish_channel_id")
        wish_note = f" in <#{wish_chan_id}>" if wish_chan_id else ""

        embed = make_box_embed(
            title="Birthday Registered",
            description=(
                f"Your birthday has been locked and saved for **{MONTH_NAMES[month]} {day}**! 🎉\n\n"
                f"Friday will celebrate and wish you{wish_note} when your special day arrives!\n\n"
                "*Note: Strictly your Day & Month are saved. No birth year or age is stored.*"
            ),
            status="success"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ConfirmBirthdayRemoveView(discord.ui.View):
    def __init__(self, user_id: str, guild_id: str):
        super().__init__(timeout=60)
        self.user_id = str(user_id)
        self.guild_id = str(guild_id)

    @discord.ui.button(
        label="Yes, Confirm Delete",
        style=discord.ButtonStyle.danger,
        custom_id="friday_birthday_confirm_del_btn"
    )
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("This confirmation is not for you.", ephemeral=True)
            return

        guild_bds = db.birthdays.get(self.guild_id, {})
        if self.user_id in guild_bds:
            del guild_bds[self.user_id]

        restricted = db.birthdays_restricted.setdefault(self.guild_id, [])
        if self.user_id not in restricted:
            restricted.append(self.user_id)
        db.save_data()

        # Remove birthday role if assigned
        cfg = db.birthdays_config.get(self.guild_id, {})
        role_id = cfg.get("birthday_role_id")
        if role_id and interaction.guild:
            try:
                role = interaction.guild.get_role(int(role_id))
                mem = interaction.guild.get_member(int(self.user_id))
                if role and mem and role in mem.roles:
                    await mem.remove_roles(role, reason="Birthday removed by user")
            except Exception:
                pass

        embed = make_box_embed(
            title="Birthday Removed & Locked",
            description=(
                "Your birthday registration has been removed.\n\n"
                "🔒 **Notice:** To prevent re-registration exploits, your birthday profile is now locked. "
                "You will be unable to set your birthdate again unless you contact the bot owner / server administrator to unlock your profile."
            ),
            status="warning"
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        custom_id="friday_birthday_cancel_del_btn"
    )
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("This confirmation is not for you.", ephemeral=True)
            return

        embed = make_box_embed(
            title="Action Cancelled",
            description="Your birthday remains registered and safe. No changes were made.",
            status="info"
        )
        await interaction.response.edit_message(embed=embed, view=None)


class BirthdayRegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎂 Register Birthday",
        style=discord.ButtonStyle.primary,
        custom_id="friday_birthday_register_btn"
    )
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BirthdayModal())

    @discord.ui.button(
        label="🗑 Remove Birthday",
        style=discord.ButtonStyle.secondary,
        custom_id="friday_birthday_remove_btn"
    )
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        gid = str(guild.id)
        uid = str(interaction.user.id)
        guild_bds = db.birthdays.get(gid, {})

        if uid not in guild_bds:
            embed = make_box_embed(
                title="No Birthday Registered",
                description="You do not currently have a registered birthday on this server.",
                status="info"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        confirm_embed = make_box_embed(
            title="Confirm Birthday Removal",
            description=(
                "**Are you sure you want to remove your registered birthday?**\n\n"
                "⚠️ **Important Notice:** If you remove your birthday, you will be **unable to set your birthdate again** unless you contact the bot owner / server administrator to unlock your profile.\n\n"
                "Click **Yes, Confirm Delete** to proceed, or **Cancel** to keep your birthday."
            ),
            status="warning"
        )
        view = ConfirmBirthdayRemoveView(user_id=uid, guild_id=gid)
        await interaction.response.send_message(embed=confirm_embed, view=view, ephemeral=True)


class BirthdayPaginationView(discord.ui.View):
    def __init__(self, pages: List[discord.Embed]):
        super().__init__(timeout=120)
        self.pages = pages
        self.current_page = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = (self.current_page == 0)
        self.next_btn.disabled = (self.current_page >= len(self.pages) - 1)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)


class BirthdaysCog(commands.Cog, name="Birthdays"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(BirthdayRegisterView())
        self.daily_birthday_task.start()

    def cog_unload(self):
        self.daily_birthday_task.cancel()

    # ─────────────────────────────────────────────────────────────
    # Automated Daily Scheduler Loop (Runs every 30 seconds to catch exact minute)
    # ─────────────────────────────────────────────────────────────
    @tasks.loop(seconds=30)
    async def daily_birthday_task(self):
        """Checks for member birthdays and delivers automated celebratory wishes & temporary roles at the exact configured time."""
        await self.bot.wait_until_ready()

        now_utc = datetime.datetime.now(datetime.timezone.utc)

        for guild in self.bot.guilds:
            gid = str(guild.id)
            cfg = db.birthdays_config.get(gid, {})
            if not cfg.get("enabled", False):
                continue

            wish_chan_id = cfg.get("wish_channel_id")
            if not wish_chan_id:
                continue

            wish_channel = guild.get_channel(int(wish_chan_id))
            if not wish_channel:
                continue

            # Determine local timezone date and time
            tz_str = cfg.get("timezone", "Asia/Kolkata")
            try:
                local_tz = pytz.timezone(tz_str)
            except Exception:
                local_tz = pytz.timezone("Asia/Kolkata")

            local_now = datetime.datetime.now(local_tz)
            today_month = local_now.month
            today_day = local_now.day
            current_year = local_now.year

            # Enforce wish_time (e.g. "10:50", "00:00", "22:50")
            # Strictly do not deliver before the configured minute in the guild's local timezone
            wish_time_str = cfg.get("wish_time", "00:00")
            target_hour, target_minute = parse_wish_time_hour_min(wish_time_str)
            if (local_now.hour < target_hour) or (local_now.hour == target_hour and local_now.minute < target_minute):
                # Not yet time for daily wishes in this server's timezone today
                continue

            # Optional: Revoke expired temporary birthday roles (roles older than 24h)
            active_roles = db.data.setdefault("birthday_active_roles", {}).setdefault(gid, {})
            expired_uids = []
            for uid, grant_time in list(active_roles.items()):
                try:
                    grant_dt = datetime.datetime.fromisoformat(grant_time)
                    if (now_utc - grant_dt).total_seconds() >= 86400:  # 24 hours
                        mem = guild.get_member(int(uid))
                        role_id = cfg.get("role_id")
                        if mem and role_id:
                            role = guild.get_role(int(role_id))
                            if role and role in mem.roles:
                                try:
                                    await mem.remove_roles(role, reason="Birthday role expired after 24 hours.")
                                except Exception:
                                    pass
                        expired_uids.append(uid)
                except Exception:
                    expired_uids.append(uid)

            for uid in expired_uids:
                active_roles.pop(uid, None)

            # Check today's birthdays
            guild_bds = db.birthdays.get(gid, {})
            if not guild_bds:
                continue

            departed_uids = []

            for uid, record in list(guild_bds.items()):
                if record.get("month") == today_month and record.get("day") == today_day:
                    # Check if already wished this year
                    if record.get("last_wished_year") == current_year:
                        continue

                    member = guild.get_member(int(uid))
                    if not member:
                        # Member left server -> purge from database cleanly
                        departed_uids.append(uid)
                        continue

                    # Deliver Celebration
                    try:
                        await self._send_birthday_wish(guild, wish_channel, member, cfg)
                        record["last_wished_year"] = current_year

                        # Assign Birthday Role for 24 hours if configured
                        role_id = cfg.get("role_id")
                        if role_id:
                            role = guild.get_role(int(role_id))
                            if role and role not in member.roles:
                                try:
                                    await member.add_roles(role, reason="Happy Birthday! Temporary celebratory role.")
                                    active_roles[uid] = now_utc.isoformat()
                                except Exception as e:
                                    print(f"[Birthday Role Assign Error] {e}")

                    except Exception as e:
                        print(f"[Birthday Deliver Error in {guild.name}] {e}")

            if departed_uids:
                for uid in departed_uids:
                    guild_bds.pop(uid, None)
                    restricted = db.birthdays_restricted.get(gid, [])
                    if uid in restricted:
                        restricted.remove(uid)

            db.save_data()

    async def _send_birthday_wish(self, guild: discord.Guild, channel: discord.TextChannel, member: discord.Member, cfg: dict):
        """Constructs and sends the customized birthday celebratory card."""
        mention_txt = member.mention
        display_name = member.display_name
        server_name = guild.name

        # Custom header text
        wish_msg_tpl = cfg.get("wish_message", "🎂 Happy Birthday {mention}! Let's celebrate! 🎉")
        header_text = wish_msg_tpl.replace("{mention}", mention_txt).replace("{user}", display_name).replace("{server}", server_name)
        header_text = replace_plain_emojis(header_text, bot=self.bot, guild=guild, guild_id=str(guild.id))

        if cfg.get("ping_everyone", False):
            header_text = f"@everyone\n{header_text}"

        # Custom Embed
        raw_embed_title = cfg.get("embed_title", "🎉 HAPPY BIRTHDAY, {user}! 🎂").replace("{user}", display_name).replace("{mention}", mention_txt)
        embed_title = replace_plain_emojis(raw_embed_title, bot=self.bot, guild=guild, guild_id=str(guild.id))
        embed_desc_tpl = cfg.get(
            "embed_description",
            "Wishing a very Happy Birthday to {mention}! May your special day be filled with happiness, success, and endless joy! 🎈✨"
        )
        raw_embed_desc = embed_desc_tpl.replace("{mention}", mention_txt).replace("{user}", display_name).replace("{server}", server_name)
        embed_desc = replace_plain_emojis(raw_embed_desc, bot=self.bot, guild=guild, guild_id=str(guild.id))

        color_hex = cfg.get("embed_color", "#ff69b4")
        try:
            color_int = int(color_hex.lstrip('#'), 16)
        except Exception:
            color_int = 0xff69b4

        embed = discord.Embed(
            title=embed_title,
            description=embed_desc,
            color=color_int,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

        embed.set_thumbnail(url=member.display_avatar.url)

        banner_url = cfg.get("embed_image")
        discord_file = None
        if banner_url:
            if banner_url.startswith("/static/"):
                fname = os.path.basename(banner_url)
                fpath = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "uploads", "birthday_banners", fname)
                if not os.path.exists(fpath):
                    fpath = os.path.join("dashboard", "static", "uploads", "birthday_banners", fname)
                if os.path.exists(fpath):
                    discord_file = discord.File(fpath, filename=fname)
                    embed.set_image(url=f"attachment://{fname}")
            elif banner_url.startswith(("http://", "https://")):
                embed.set_image(url=banner_url)

        footer_text = cfg.get("embed_footer", "Friday Birthday Engine • Wish them in chat!")
        embed.set_footer(text=footer_text, icon_url=guild.icon.url if guild.icon else None)

        if discord_file:
            await channel.send(content=header_text, embed=embed, file=discord_file)
        else:
            await channel.send(content=header_text, embed=embed)

    # ─────────────────────────────────────────────────────────────
    # Member Departure Listener
    # ─────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Automatically purges departing member's birthday and lockout records."""
        gid = str(member.guild.id)
        uid = str(member.id)
        purged = False

        guild_bds = db.birthdays.get(gid, {})
        if uid in guild_bds:
            del guild_bds[uid]
            purged = True

        restricted = db.birthdays_restricted.get(gid, [])
        if uid in restricted:
            restricted.remove(uid)
            purged = True

        active_roles = db.data.get("birthday_active_roles", {}).get(gid, {})
        if uid in active_roles:
            active_roles.pop(uid, None)
            purged = True

        if purged:
            db.save_data()
            print(f"🗑️ [Birthdays] Purged records for departing member {member.name} ({uid}) in '{member.guild.name}'")

    # ─────────────────────────────────────────────────────────────
    # Slash Commands Suite
    # ─────────────────────────────────────────────────────────────
    birthday_group = app_commands.Group(
        name="birthday",
        description="Track and celebrate member birthdays with automated wishes and roles."
    )

    @birthday_group.command(name="toggle", description="Quickly enable or disable the birthday celebration engine in this server.")
    @app_commands.default_permissions(administrator=True)
    async def birthday_toggle(self, interaction: discord.Interaction):
        guild = interaction.guild
        gid = str(guild.id)
        cfg = db.birthdays_config.setdefault(gid, {})
        new_state = not cfg.get("enabled", False)
        cfg["enabled"] = new_state
        db.save_data()
        status_text = "✅ **ENABLED**" if new_state else "⏸️ **DISABLED**"
        embed = make_box_embed(
            title="Birthday System Toggle",
            description=f"The Birthday Celebration Engine is now {status_text} in **{interaction.guild.name}**.",
            status="success" if new_state else "neutral"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @birthday_group.command(name="setup", description="Configure birthday form channel, wish announcement channel, and optional role.")
    @app_commands.describe(
        form_channel="Channel where Friday posts the permanent 'Register Birthday' card",
        wish_channel="Channel where Friday sends celebratory birthday wishes",
        birthday_role="Optional role granted to members on their birthday for 24 hours"
    )
    @app_commands.default_permissions(administrator=True)
    async def birthday_setup(
        self,
        interaction: discord.Interaction,
        form_channel: discord.TextChannel,
        wish_channel: discord.TextChannel,
        birthday_role: Optional[discord.Role] = None
    ):
        guild = interaction.guild
        gid = str(guild.id)
        cfg = db.birthdays_config.setdefault(gid, {})
        cfg["enabled"] = True
        cfg["form_channel_id"] = str(form_channel.id)
        cfg["wish_channel_id"] = str(wish_channel.id)
        if birthday_role:
            cfg["role_id"] = str(birthday_role.id)

        # Deploy permanent interactive registration card into form_channel
        raw_card_title = cfg.get("form_card_title", "🎂 Member Birthday Registration")
        card_title = replace_plain_emojis(raw_card_title, bot=self.bot, guild=guild, guild_id=str(guild.id))
        raw_card_desc = cfg.get(
            "form_card_desc",
            "Click the button below to register your birthday!\n\n"
            "🎉 Friday will deliver celebratory wishes on your special day.\n"
            "🔒 **Strict Privacy:** Only Month & Day are saved. Zero birth year or age is stored."
        )
        card_desc = replace_plain_emojis(raw_card_desc, bot=self.bot, guild=guild, guild_id=str(guild.id))
        embed = discord.Embed(
            title=card_title,
            description=card_desc,
            color=0xff69b4
        )
        banner_url = cfg.get("form_card_banner")
        discord_file = None
        if banner_url:
            if banner_url.startswith("/static/"):
                fname = os.path.basename(banner_url)
                fpath = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "uploads", "birthday_banners", fname)
                if not os.path.exists(fpath):
                    fpath = os.path.join("dashboard", "static", "uploads", "birthday_banners", fname)
                if os.path.exists(fpath):
                    discord_file = discord.File(fpath, filename=fname)
                    embed.set_image(url=f"attachment://{fname}")
            elif banner_url.startswith(("http://", "https://")):
                embed.set_image(url=banner_url)
        embed.set_footer(text="Friday Birthday Engine • Ephemeral & Private Submission")

        try:
            if discord_file:
                card_msg = await form_channel.send(embed=embed, file=discord_file, view=BirthdayRegisterView())
            else:
                card_msg = await form_channel.send(embed=embed, view=BirthdayRegisterView())
            cfg["form_message_id"] = str(card_msg.id)
        except Exception as e:
            await reply_box(interaction, f"Failed to post card into {form_channel.mention}: {e}", title="CARD POST FAILED", status="error", ephemeral=True)
            return

        db.save_data()

        role_info = f"\n> **Birthday Role:** {birthday_role.mention}" if birthday_role else ""
        desc = (
            f"Successfully configured Birthday Studio!\n"
            f"> **Registration Channel:** {form_channel.mention}\n"
            f"> **Wish Channel:** {wish_channel.mention}{role_info}\n\n"
            f"The permanent registration card has been deployed to {form_channel.mention}."
        )
        await reply_box(interaction, desc, title="BIRTHDAY SETUP COMPLETE", status="success")

    @birthday_group.command(name="set", description="Register or check your birthday (Month & Day only).")
    @app_commands.describe(
        month="Your birth month (1-12 or month name)",
        day="Your birth day (1-31)"
    )
    async def birthday_set(self, interaction: discord.Interaction, month: str, day: int):
        guild = interaction.guild
        gid = str(guild.id)
        uid = str(interaction.user.id)

        # Lockout check
        restricted = db.birthdays_restricted.get(gid, [])
        if uid in restricted:
            await reply_box(
                interaction,
                "You have previously removed or reset your birthday. Registration is locked. Please contact server staff to unlock.",
                title="REGISTRATION LOCKED",
                status="error",
                ephemeral=True
            )
            return

        guild_bds = db.birthdays.setdefault(gid, {})
        if uid in guild_bds:
            existing = guild_bds[uid]
            m_name = MONTH_NAMES.get(existing.get("month", 1), "Unknown")
            await reply_box(
                interaction,
                f"Your birthday is already registered as **{m_name} {existing.get('day')}**. Contact staff to update if incorrect.",
                title="ALREADY REGISTERED",
                status="info",
                ephemeral=True
            )
            return

        clean_month = month.strip().lower()
        m_num = MONTH_LOOKUP.get(clean_month)
        if not m_num:
            await reply_box(interaction, "Please enter a valid month (e.g. `May`, `December`, or `5`).", title="INVALID MONTH", status="error", ephemeral=True)
            return

        max_days = DAYS_IN_MONTH.get(m_num, 31)
        if day < 1 or day > max_days:
            await reply_box(interaction, f"**{MONTH_NAMES[m_num]}** only has up to {max_days} days.", title="INVALID DAY", status="error", ephemeral=True)
            return

        guild_bds[uid] = {
            "user_id": uid,
            "user_name": interaction.user.display_name,
            "month": m_num,
            "day": day,
            "registered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "last_wished_year": 0
        }
        db.save_data()

        cfg = db.birthdays_config.get(gid, {})
        wish_chan_id = cfg.get("wish_channel_id")
        wish_note = f" in <#{wish_chan_id}>" if wish_chan_id else ""
        await reply_box(
            interaction,
            f"Your birthday has been registered for **{MONTH_NAMES[m_num]} {day}**! Friday will wish you{wish_note} when your special day arrives!",
            title="BIRTHDAY REGISTERED",
            status="success",
            ephemeral=True
        )

    @birthday_group.command(name="remove", description="Remove your registered birthday.")
    async def birthday_remove(self, interaction: discord.Interaction):
        guild = interaction.guild
        gid = str(guild.id)
        uid = str(interaction.user.id)
        guild_bds = db.birthdays.get(gid, {})

        if uid not in guild_bds:
            await reply_box(interaction, "You do not have a registered birthday on this server.", title="NOT FOUND", status="error", ephemeral=True)
            return

        confirm_embed = make_box_embed(
            title="Confirm Birthday Removal",
            description=(
                "**Are you sure you want to remove your registered birthday?**\n\n"
                "⚠️ **Important Notice:** If you remove your birthday, you will be **unable to set your birthdate again** unless you contact the bot owner / server administrator to unlock your profile.\n\n"
                "Click **Yes, Confirm Delete** to proceed, or **Cancel** to keep your birthday."
            ),
            status="warning"
        )
        view = ConfirmBirthdayRemoveView(user_id=uid, guild_id=gid)
        await interaction.response.send_message(embed=confirm_embed, view=view, ephemeral=True)

    @birthday_group.command(name="list", description="View upcoming birthdays in the server (Supports 1000+ members with pagination).")
    @app_commands.describe(month="Optional month filter (e.g. May or 5)")
    async def birthday_list(self, interaction: discord.Interaction, month: Optional[str] = None):
        guild = interaction.guild
        gid = str(guild.id)
        guild_bds = db.birthdays.get(gid, {})

        if not guild_bds:
            await reply_box(interaction, "No birthdays registered in this server yet.", title="NO BIRTHDAYS", status="info", ephemeral=True)
            return

        target_month = None
        if month:
            target_month = MONTH_LOOKUP.get(month.strip().lower())

        # Sort birthdays by month and day
        items = []
        for uid, rec in guild_bds.items():
            m = rec.get("month", 1)
            d = rec.get("day", 1)
            if target_month and m != target_month:
                continue
            items.append((m, d, rec.get("user_name", f"User {uid}"), uid))

        items.sort(key=lambda x: (x[0], x[1]))

        if not items:
            filter_note = f" for **{MONTH_NAMES.get(target_month, month)}**" if target_month else ""
            await reply_box(interaction, f"No birthdays found{filter_note}.", title="NO BIRTHDAYS FOUND", status="info", ephemeral=True)
            return

        # Paginate 10 members per page
        page_size = 10
        pages = []
        total_pages = (len(items) + page_size - 1) // page_size

        for p in range(total_pages):
            chunk = items[p * page_size:(p + 1) * page_size]
            lines = []
            for m, d, uname, uid in chunk:
                lines.append(f"• <@{uid}> — **{MONTH_NAMES[m]} {d}**")

            embed = discord.Embed(
                title=f"🎂 Server Birthdays ({len(items)} Total)",
                description="\n".join(lines),
                color=0xff69b4
            )
            embed.set_footer(text=f"Page {p + 1} of {total_pages} • Friday Birthday Engine")
            pages.append(embed)

        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0])
        else:
            view = BirthdayPaginationView(pages)
            await interaction.response.send_message(embed=pages[0], view=view)

    @birthday_group.command(name="test", description="Send a sample birthday wish embed to the wish channel to verify formatting.")
    @app_commands.default_permissions(manage_guild=True)
    async def birthday_test(self, interaction: discord.Interaction):
        guild = interaction.guild
        gid = str(guild.id)
        cfg = db.birthdays_config.get(gid, {})
        wish_chan_id = cfg.get("wish_channel_id")

        if not wish_chan_id:
            await reply_box(interaction, "No wish channel configured. Please run `/birthday setup` first.", title="NOT CONFIGURED", status="error", ephemeral=True)
            return

        wish_chan = interaction.guild.get_channel(int(wish_chan_id))
        if not wish_chan:
            await reply_box(interaction, f"Wish channel with ID `{wish_chan_id}` could not be found.", title="CHANNEL NOT FOUND", status="error", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await self._send_birthday_wish(interaction.guild, wish_chan, interaction.user, cfg)
            await reply_box(interaction, f"Sample birthday wish delivered to {wish_chan.mention}!", title="TEST WISH SENT", status="success", ephemeral=True)
        except Exception as e:
            await reply_box(interaction, f"Failed to send test wish: {e}", title="DELIVERY ERROR", status="error", ephemeral=True)


async def setup(bot):
    await bot.add_cog(BirthdaysCog(bot))
