import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import datetime
import re
import uuid
from typing import Optional, List, Dict
from database import db
from emoji_utils import replace_plain_emojis, parse_btn, resolve_single_emoji, clean_embed_title, normalize_discord_markdown
from response_utils import make_box_embed, reply_box, ensure_admin_or_owner

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG DEFAULTS & HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_app_config(gid_str: str) -> dict:
    guild_data = db.applications.setdefault(gid_str, {})
    cfg = guild_data.setdefault("config", {})
    if "panel" not in cfg:
        cfg["panel"] = {
            "title": "📋 Staff Application",
            "description": "Interested in joining our staff team? Click the button below to submit your application!",
            "color": "#5865f2",
            "footer": "Friday Applications • Click below to apply",
            "button_label": "Apply Now",
            "button_emoji": "📝",
            "button_style": "primary"
        }
    if "questions" not in cfg or not isinstance(cfg["questions"], list) or len(cfg["questions"]) == 0:
        cfg["questions"] = [
            "What position are you applying for and why?",
            "What is your age and timezone?",
            "How many hours per week can you dedicate to the server?",
            "Do you have previous staff or moderation experience? Please describe.",
            "How would you handle a conflict between two heated members in chat?"
        ]
    if "dm_flow" not in cfg:
        cfg["dm_flow"] = {
            "intro_title": "📝 Staff Application • {server}",
            "intro_description": "Hello {user}! Thank you for your interest in joining the staff team in **{server}**.\n\nYou are about to begin the application form. Please make sure you have enough time to answer all questions thoughtfully.",
            "intro_color": "#5865f2",
            "start_btn_label": "Let's Start",
            "start_btn_emoji": "🚀",
            "cancel_btn_label": "Cancel",
            "cancel_btn_emoji": "✖️"
        }
    if "approved_msg" not in cfg:
        cfg["approved_msg"] = {
            "title": "🎉 Application Approved • {server}",
            "description": "Congratulations {user}!\n\nYour staff application for **{server}** has been **APPROVED**! 🎉\nYou have been granted the {role} role. Welcome to the team!",
            "color": "#10b981"
        }
    if "rejected_msg" not in cfg:
        cfg["rejected_msg"] = {
            "title": "Application Update • {server}",
            "description": "Hello {user},\n\nThank you for taking the time to apply for a staff position in **{server}**.\nAfter careful review, we regret to inform you that your application was not accepted at this time.\n\n**Reason:** {reason}\n\nYou are welcome to re-apply in the future.",
            "color": "#ef4444"
        }
    if "delivery_mode" not in cfg:
        cfg["delivery_mode"] = "server"  # 'server' (private temp channel) or 'dm'
    return cfg


def hex_to_int(color_str: str, default: int = 0x5865F2) -> int:
    try:
        if isinstance(color_str, str) and color_str.startswith("#"):
            return int(color_str.replace("#", ""), 16)
        elif isinstance(color_str, int):
            return color_str
        elif isinstance(color_str, str) and color_str.isdigit():
            return int(color_str)
    except Exception:
        pass
    return default


def get_button_style(style_str: str) -> discord.ButtonStyle:
    s = str(style_str).lower().strip()
    if s in ("success", "green"):
        return discord.ButtonStyle.success
    elif s in ("danger", "red"):
        return discord.ButtonStyle.danger
    elif s in ("secondary", "grey", "gray"):
        return discord.ButtonStyle.secondary
    return discord.ButtonStyle.primary


# Active in-memory session tracking: key = f"{gid}_{uid}"
ACTIVE_APPLICATION_SESSIONS = set()


# ─────────────────────────────────────────────────────────────────────────────
# MODAL FOR REJECTION REASON
# ─────────────────────────────────────────────────────────────────────────────

class ApplicationRejectModal(discord.ui.Modal, title="Reject Application"):
    reason_input = discord.ui.TextInput(
        label="Reason for Rejection",
        placeholder="e.g. Insufficient experience, Inactive profile, Position filled...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=400,
        default="Application was not accepted at this time."
    )

    def __init__(self, cog, submission_id: str, guild_id: str):
        super().__init__()
        self.cog = cog
        self.submission_id = submission_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason_input.value.strip() or "Application was not accepted at this time."
        await self.cog.process_decision(
            interaction=interaction,
            submission_id=self.submission_id,
            guild_id=self.guild_id,
            action="reject",
            reason=reason
        )


# ─────────────────────────────────────────────────────────────────────────────
# PERSISTENT VIEW: STAFF REVIEW CHANNEL
# ─────────────────────────────────────────────────────────────────────────────

class ApplicationReviewView(discord.ui.View):
    def __init__(self, cog, submission_id: str, guild_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.submission_id = submission_id
        self.guild_id = str(guild_id)

        # Dynamic custom IDs so persistent listeners can map directly to the submission
        self.approve_btn.custom_id = f"app_rev_approve_{self.submission_id}"
        self.reject_btn.custom_id = f"app_rev_reject_{self.submission_id}"

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Strict permission check: Server Owner or Administrator ONLY
        if interaction.user.id != interaction.guild.owner_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ **Permission Denied:** Only administrators and the server owner can approve applications.",
                ephemeral=True
            )
            return

        await self.cog.process_decision(
            interaction=interaction,
            submission_id=self.submission_id,
            guild_id=self.guild_id,
            action="approve"
        )

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Strict permission check: Server Owner or Administrator ONLY
        if interaction.user.id != interaction.guild.owner_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ **Permission Denied:** Only administrators and the server owner can reject applications.",
                ephemeral=True
            )
            return

        # Prompt for optional rejection reason via modal
        await interaction.response.send_modal(ApplicationRejectModal(self.cog, self.submission_id, self.guild_id))


# ─────────────────────────────────────────────────────────────────────────────
# INTERACTIVE VIEWS: INTRO & SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

class ApplicationIntroView(discord.ui.View):
    def __init__(self, on_start, on_cancel, start_label="Let's Start", start_emoji="🚀", cancel_label="Cancel", cancel_emoji="✖️"):
        super().__init__(timeout=300)
        self.on_start = on_start
        self.on_cancel = on_cancel

        self.start_btn.label = start_label
        self.start_btn.emoji = start_emoji
        self.cancel_btn.label = cancel_label
        self.cancel_btn.emoji = cancel_emoji

    @discord.ui.button(style=discord.ButtonStyle.success)
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_start(interaction)

    @discord.ui.button(style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_cancel(interaction)


class ApplicationSummaryView(discord.ui.View):
    def __init__(self, on_submit, on_retake, on_cancel):
        super().__init__(timeout=600)
        self.on_submit = on_submit
        self.on_retake = on_retake
        self.on_cancel = on_cancel

    @discord.ui.button(label="Submit Application", style=discord.ButtonStyle.success, emoji="✅")
    async def submit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_submit(interaction)

    @discord.ui.button(label="Retake Application", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def retake_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_retake(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="✖️")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.on_cancel(interaction)


# ─────────────────────────────────────────────────────────────────────────────
# PERSISTENT VIEW: APPLICATION PANEL (APPLY NOW)
# ─────────────────────────────────────────────────────────────────────────────

class ApplicationPanelView(discord.ui.View):
    def __init__(self, cog, panel_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.panel_id = str(panel_id)

    @discord.ui.button(label="Apply Now", style=discord.ButtonStyle.primary, emoji="📝", custom_id="app_apply_btn_default")
    async def apply_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid_str = str(interaction.guild.id)
        uid_str = str(interaction.user.id)
        session_key = f"{gid_str}_{uid_str}"

        if session_key in ACTIVE_APPLICATION_SESSIONS:
            await interaction.response.send_message(
                "⚠️ You already have an active application session in progress! Please finish or cancel your current form before opening a new one.",
                ephemeral=True
            )
            return

        cfg = get_app_config(gid_str)
        mode = cfg.get("delivery_mode", "server")

        if mode == "dm":
            # Direct Message flow
            try:
                # Test if DM is open
                test_embed = discord.Embed(
                    title="Checking DM status...",
                    description="Preparing your application...",
                    color=0x5865f2
                )
                dm_test_msg = await interaction.user.send(embed=test_embed)
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ **Could not send you a Direct Message.**\n"
                    "Please enable **Direct Messages from server members** in your Discord Privacy Settings and try again.",
                    ephemeral=True
                )
                return
            except Exception as e:
                await interaction.response.send_message(
                    f"❌ An error occurred while opening your Direct Messages: {e}",
                    ephemeral=True
                )
                return

            await interaction.response.send_message(
                "📬 **Check your DMs!** Friday has sent you the application form in private chat.",
                ephemeral=True
            )
            # Delete test message
            try:
                await dm_test_msg.delete()
            except Exception:
                pass

            # Launch DM session asynchronously
            asyncio.create_task(
                self.cog.run_application_session(
                    guild=interaction.guild,
                    user=interaction.user,
                    target_channel=interaction.user,
                    is_dm=True
                )
            )

        else:
            # In-Server flow: Create temporary private text channel
            await interaction.response.defer(ephemeral=True)

            guild = interaction.guild
            user = interaction.user

            # Generate safe channel name
            safe_name = re.sub(r'[^a-zA-Z0-9]', '', user.name.lower())[:15] or "applicant"
            chan_name = f"apply-{safe_name}"

            # Check if temporary channel already exists
            existing_ch = discord.utils.get(guild.text_channels, name=chan_name)
            if existing_ch:
                await interaction.followup.send(
                    f"⚠️ You already have an application channel open: {existing_ch.mention}. Please finish your application there.",
                    ephemeral=True
                )
                return

            # Overwrites: Only applicant, bot, and staff/admins can view
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, view_channel=False),
                user: discord.PermissionOverwrite(read_messages=True, view_channel=True, send_messages=True, attach_files=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, view_channel=True, send_messages=True, manage_channels=True)
            }

            # Optional: Allow review staff role to inspect live
            review_cid = cfg.get("review_channel_id")
            if review_cid:
                r_ch = guild.get_channel(int(review_cid))
                if r_ch and r_ch.category:
                    cat = r_ch.category
                else:
                    cat = interaction.channel.category if isinstance(interaction.channel, discord.TextChannel) else None
            else:
                cat = interaction.channel.category if isinstance(interaction.channel, discord.TextChannel) else None

            try:
                temp_ch = await guild.create_text_channel(
                    name=chan_name,
                    category=cat,
                    overwrites=overwrites,
                    topic=f"Temporary Private Application Channel for {user} (ID: {user.id})"
                )
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Failed to create private application channel: {e}",
                    ephemeral=True
                )
                return

            await interaction.followup.send(
                f"✅ **Your private application channel has been created:** {temp_ch.mention}\nPlease head over to begin your application!",
                ephemeral=True
            )

            # Launch in-channel session
            asyncio.create_task(
                self.cog.run_application_session(
                    guild=guild,
                    user=user,
                    target_channel=temp_ch,
                    is_dm=False
                )
            )


# ─────────────────────────────────────────────────────────────────────────────
# COG IMPLEMENTATION
# ─────────────────────────────────────────────────────────────────────────────

class Applications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        asyncio.create_task(self.restore_views())

    async def restore_views(self):
        """Restores persistent views across bot restarts for all panels and pending reviews."""
        try:
            await self.bot.wait_until_ready()
        except Exception:
            pass

        restored_panels = 0
        restored_reviews = 0

        for gid_str, gdata in db.applications.items():
            if not isinstance(gdata, dict):
                continue

            # 1. Restore Panels
            panels = gdata.get("panels", {})
            guild = self.bot.get_guild(int(gid_str)) if gid_str.isdigit() else None
            for pid_str, pdata in panels.items():
                try:
                    panel_id = int(pid_str)
                    btn_label = pdata.get("button_label", "Apply Now")
                    btn_emoji_raw = pdata.get("button_emoji", "📝")
                    btn_style = get_button_style(pdata.get("button_style", "primary"))
                    btn_emoji = resolve_single_emoji(btn_emoji_raw, bot=self.bot, guild=guild, guild_id=gid_str)

                    view = ApplicationPanelView(self, panel_id)
                    view.clear_items()
                    btn = discord.ui.Button(
                        label=btn_label,
                        style=btn_style,
                        emoji=btn_emoji,
                        custom_id=f"app_apply_btn_{pid_str}"
                    )
                    btn.callback = view.apply_button.callback
                    view.add_item(btn)

                    self.bot.add_view(view, message_id=panel_id)
                    restored_panels += 1
                except Exception as e:
                    print(f"[Applications] Failed restoring panel {pid_str}: {e}")

            # 2. Restore Pending Review Submissions
            submissions = gdata.get("submissions", {})
            for sub_id, sdata in submissions.items():
                if sdata.get("status") == "pending":
                    try:
                        view = ApplicationReviewView(self, sub_id, gid_str)
                        self.bot.add_view(view)
                        restored_reviews += 1
                    except Exception as e:
                        print(f"[Applications] Failed restoring review {sub_id}: {e}")

        print(f"📋 [Applications Cog] Restored {restored_panels} application panels and {restored_reviews} pending review views.")

    # ─────────────────────────────────────────────────────────────────────────
    # SESSION RUNNER (DM OR TEMP CHANNEL)
    # ─────────────────────────────────────────────────────────────────────────

    async def run_application_session(self, guild: discord.Guild, user: discord.Member, target_channel, is_dm: bool):
        gid_str = str(guild.id)
        uid_str = str(user.id)
        session_key = f"{gid_str}_{uid_str}"
        ACTIVE_APPLICATION_SESSIONS.add(session_key)

        try:
            cfg = get_app_config(gid_str)
            dm_cfg = cfg.get("dm_flow", {})
            questions = cfg.get("questions", [])

            if not questions:
                questions = ["Why do you want to join our staff team?"]

            # ── 1. Send Intro Message with Let's Start / Cancel ──
            raw_intro_title = dm_cfg.get("intro_title", "📝 Staff Application • {server}")
            raw_intro_desc = dm_cfg.get(
                "intro_description",
                "Hello {user}! Thank you for your interest in joining the staff team in **{server}**.\n\nYou are about to begin the application form. Please make sure you have enough time to answer all questions thoughtfully."
            )
            intro_color = hex_to_int(dm_cfg.get("intro_color", "#5865f2"))

            start_label = dm_cfg.get("start_btn_label", "Let's Start")
            start_emoji_raw = dm_cfg.get("start_btn_emoji", "🚀")
            cancel_label = dm_cfg.get("cancel_btn_label", "Cancel")
            cancel_emoji_raw = dm_cfg.get("cancel_btn_emoji", "✖️")

            start_emoji = resolve_single_emoji(start_emoji_raw, bot=self.bot, guild=guild, guild_id=gid_str) or "🚀"
            cancel_emoji = resolve_single_emoji(cancel_emoji_raw, bot=self.bot, guild=guild, guild_id=gid_str) or "✖️"

            parsed_title = clean_embed_title(replace_plain_emojis(
                raw_intro_title.replace("{server}", guild.name).replace("{user}", user.name),
                bot=self.bot, guild=guild, guild_id=gid_str
            ))
            parsed_desc = normalize_discord_markdown(replace_plain_emojis(
                raw_intro_desc.replace("{server}", guild.name).replace("{user}", user.mention).replace("{username}", user.name),
                bot=self.bot, guild=guild, guild_id=gid_str
            ))

            intro_embed = discord.Embed(
                title=parsed_title,
                description=parsed_desc,
                color=intro_color
            )
            intro_embed.set_footer(text=f"{guild.name} • Application Form", icon_url=guild.icon.url if guild.icon else None)
            intro_embed.timestamp = discord.utils.utcnow()

            started_event = asyncio.Event()
            cancelled_event = asyncio.Event()

            async def handle_start(inter: discord.Interaction):
                if inter.user.id != user.id:
                    await inter.response.send_message("❌ This is not your application session.", ephemeral=True)
                    return
                await inter.response.defer()
                started_event.set()

            async def handle_cancel(inter: discord.Interaction):
                if inter.user.id != user.id:
                    await inter.response.send_message("❌ This is not your application session.", ephemeral=True)
                    return
                await inter.response.defer()
                cancelled_event.set()

            intro_view = ApplicationIntroView(
                on_start=handle_start,
                on_cancel=handle_cancel,
                start_label=start_label,
                start_emoji=start_emoji,
                cancel_label=cancel_label,
                cancel_emoji=cancel_emoji
            )

            intro_msg = await target_channel.send(content=user.mention if not is_dm else None, embed=intro_embed, view=intro_view)

            # Wait for user choice (timeout after 5 minutes)
            done_tasks, _ = await asyncio.wait(
                [
                    asyncio.create_task(started_event.wait()),
                    asyncio.create_task(cancelled_event.wait())
                ],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=300
            )

            if cancelled_event.is_set():
                await self.abort_session(target_channel, is_dm, user, reason="Cancelled by applicant.")
                return

            if not started_event.is_set():
                await self.abort_session(target_channel, is_dm, user, reason="Session timed out due to inactivity.")
                return

            # Disable intro view buttons
            try:
                for item in intro_view.children:
                    item.disabled = True
                await intro_msg.edit(view=intro_view)
            except Exception:
                pass

            # ── 2. Sequential Question Asking Loop ──
            while True:
                answers = []
                abandoned = False

                for idx, question_text in enumerate(questions, start=1):
                    q_title = f"📋 Question {idx} of {len(questions)}"
                    q_parsed = replace_plain_emojis(question_text, bot=self.bot, guild=guild, guild_id=gid_str)
                    
                    q_embed = discord.Embed(
                        title=q_title,
                        description=f"**{q_parsed}**\n\n*Type your response in this chat below. Type `cancel` to quit anytime.*",
                        color=intro_color
                    )
                    q_embed.set_footer(text=f"Progress: {idx}/{len(questions)} Questions • 10 min limit per question")
                    await target_channel.send(embed=q_embed)

                    # Message check
                    def msg_check(m):
                        if m.author.id != user.id:
                            return False
                        if is_dm:
                            return isinstance(m.channel, discord.DMChannel)
                        else:
                            return m.channel.id == target_channel.id

                    try:
                        user_reply = await self.bot.wait_for('message', check=msg_check, timeout=600)
                    except asyncio.TimeoutError:
                        await self.abort_session(target_channel, is_dm, user, reason="Application timed out waiting for answer.")
                        return

                    ans_text = user_reply.content.strip()
                    if ans_text.lower() == "cancel":
                        await self.abort_session(target_channel, is_dm, user, reason="Application cancelled by applicant.")
                        return

                    if not ans_text and user_reply.attachments:
                        ans_text = f"[Attached File: {user_reply.attachments[0].url}]"

                    answers.append(ans_text or "(No answer provided)")

                # ── 3. Summary & Verification ──
                sum_title = "📋 Application Review & Confirmation"
                sum_embed = discord.Embed(
                    title=sum_title,
                    description="Please review all your answers below. If everything is accurate, click **Submit Application**. If you wish to redo your responses, click **Retake Application**.",
                    color=0x2dd4bf
                )
                for q_idx, (q_t, a_t) in enumerate(zip(questions, answers), start=1):
                    clean_a = a_t if len(a_t) <= 1024 else a_t[:1020] + "..."
                    sum_embed.add_field(name=f"Q{q_idx}: {q_t[:250]}", value=clean_a, inline=False)

                sum_embed.set_footer(text=f"{guild.name} • Ready to submit?")
                sum_embed.timestamp = discord.utils.utcnow()

                submit_event = asyncio.Event()
                retake_event = asyncio.Event()
                cancel_sum_event = asyncio.Event()

                async def handle_submit(inter: discord.Interaction):
                    if inter.user.id != user.id:
                        await inter.response.send_message("❌ This is not your session.", ephemeral=True)
                        return
                    await inter.response.defer()
                    submit_event.set()

                async def handle_retake(inter: discord.Interaction):
                    if inter.user.id != user.id:
                        await inter.response.send_message("❌ This is not your session.", ephemeral=True)
                        return
                    await inter.response.defer()
                    retake_event.set()

                async def handle_cancel_sum(inter: discord.Interaction):
                    if inter.user.id != user.id:
                        await inter.response.send_message("❌ This is not your session.", ephemeral=True)
                        return
                    await inter.response.defer()
                    cancel_sum_event.set()

                summary_view = ApplicationSummaryView(
                    on_submit=handle_submit,
                    on_retake=handle_retake,
                    on_cancel=handle_cancel_sum
                )

                sum_msg = await target_channel.send(embed=sum_embed, view=summary_view)

                done_sum, _ = await asyncio.wait(
                    [
                        asyncio.create_task(submit_event.wait()),
                        asyncio.create_task(retake_event.wait()),
                        asyncio.create_task(cancel_sum_event.wait())
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=600
                )

                if cancel_sum_event.is_set():
                    await self.abort_session(target_channel, is_dm, user, reason="Application cancelled by applicant.")
                    return

                if not submit_event.is_set() and not retake_event.is_set():
                    await self.abort_session(target_channel, is_dm, user, reason="Confirmation timed out.")
                    return

                if retake_event.is_set():
                    # Member clicked retake -> loop back
                    await target_channel.send("🔄 **Retaking Application:** Let's start fresh from Question 1!")
                    try:
                        for item in summary_view.children:
                            item.disabled = True
                        await sum_msg.edit(view=summary_view)
                    except Exception:
                        pass
                    continue

                if submit_event.is_set():
                    # ── 4. Dispatch Submission to Staff Review Channel ──
                    try:
                        for item in summary_view.children:
                            item.disabled = True
                        await sum_msg.edit(view=summary_view)
                    except Exception:
                        pass

                    await self.finalize_submission(
                        guild=guild,
                        applicant=user,
                        questions=questions,
                        answers=answers,
                        target_channel=target_channel,
                        is_dm=is_dm
                    )
                    break

        except Exception as e:
            import traceback
            print(f"[Applications] Error in session for {user}: {e}")
            traceback.print_exc()
            try:
                await target_channel.send(f"❌ An error occurred during your application session: {e}")
            except Exception:
                pass
        finally:
            ACTIVE_APPLICATION_SESSIONS.discard(session_key)

    async def abort_session(self, target_channel, is_dm: bool, user: discord.Member, reason: str):
        try:
            cancel_embed = discord.Embed(
                title="✖️ Application Cancelled",
                description=f"{reason}\n\nYou can start a new application at any time from the server panel.",
                color=0xef4444
            )
            await target_channel.send(embed=cancel_embed)
            if not is_dm and hasattr(target_channel, "delete"):
                await target_channel.send("🗑️ *Closing and deleting this temporary channel in 5 seconds...*")
                await asyncio.sleep(5)
                await target_channel.delete(reason="Application cancelled/closed.")
        except Exception:
            pass

    async def finalize_submission(self, guild: discord.Guild, applicant: discord.Member, questions: List[str], answers: List[str], target_channel, is_dm: bool):
        gid_str = str(guild.id)
        gdata = db.applications.setdefault(gid_str, {})
        cfg = get_app_config(gid_str)

        counter = gdata.get("submission_counter", 0) + 1
        gdata["submission_counter"] = counter

        sub_id = uuid.uuid4().hex[:10]

        submission_record = {
            "id": sub_id,
            "number": counter,
            "guild_id": guild.id,
            "applicant_id": applicant.id,
            "applicant_name": applicant.name,
            "applicant_avatar": applicant.display_avatar.url,
            "created_at": datetime.datetime.utcnow().isoformat(),
            "status": "pending",
            "reviewer_id": None,
            "reason": None,
            "questions": questions,
            "answers": answers,
            "review_message_id": None,
            "review_channel_id": None
        }

        submissions = gdata.setdefault("submissions", {})
        submissions[sub_id] = submission_record
        db.save_data()

        # Send to Review Channel
        review_cid = cfg.get("review_channel_id")
        review_channel = guild.get_channel(int(review_cid)) if review_cid else None

        if not review_channel:
            # Fallback to system logs channel or first writable text channel
            review_channel = guild.system_channel

        if review_channel:
            created_ts = int(applicant.created_at.timestamp()) if (applicant and applicant.created_at) else None
            created_str = f"<t:{created_ts}:R>" if created_ts else "Unknown"
            joined_ts = int(applicant.joined_at.timestamp()) if (applicant and applicant.joined_at) else None
            joined_str = f"<t:{joined_ts}:R>" if joined_ts else "Unknown"

            review_embed = discord.Embed(
                title=f"📋 New Staff Application • #{counter:04d}",
                description=f"**Applicant:** {applicant.mention} (`{applicant.name}` • ID: `{applicant.id}`)\n"
                            f"**Account Created:** {created_str}\n"
                            f"**Server Joined:** {joined_str}\n"
                            f"**Status:** ⏳ `Pending Review`",
                color=0xf59e0b
            )
            review_embed.set_thumbnail(url=applicant.display_avatar.url)

            for i, (q, a) in enumerate(zip(questions, answers), start=1):
                clean_ans = a if len(a) <= 1024 else a[:1020] + "..."
                review_embed.add_field(
                    name=f"{i}. {q[:250]}",
                    value=clean_ans,
                    inline=False
                )

            review_embed.set_footer(text=f"Submission ID: {sub_id} • Reviewed by Server Administrators")
            review_embed.timestamp = discord.utils.utcnow()

            review_view = ApplicationReviewView(self, sub_id, gid_str)
            review_msg = await review_channel.send(embed=review_embed, view=review_view)

            submission_record["review_message_id"] = review_msg.id
            submission_record["review_channel_id"] = review_channel.id
            db.save_data()

        # Confirmation message to applicant
        succ_embed = discord.Embed(
            title="✅ Application Submitted Successfully!",
            description=f"Thank you, {applicant.mention}! Your application has been dispatched to our staff team for review.\n\nYou will receive a Direct Message from Friday once a decision has been reached.",
            color=0x10b981
        )
        succ_embed.set_footer(text=f"Application #{counter:04d} • {guild.name}")
        succ_embed.timestamp = discord.utils.utcnow()

        await target_channel.send(embed=succ_embed)

        # If in temporary channel, countdown and auto-delete
        if not is_dm and hasattr(target_channel, "delete"):
            await target_channel.send("🔒 *This temporary application channel will be closed and deleted in 5 seconds...*")
            await asyncio.sleep(5)
            try:
                await target_channel.delete(reason="Application successfully submitted.")
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # DECISION PROCESSOR (APPROVE / REJECT)
    # ─────────────────────────────────────────────────────────────────────────

    async def process_decision(self, interaction: discord.Interaction, submission_id: str, guild_id: str, action: str, reason: str = ""):
        gid_str = str(guild_id)
        gdata = db.applications.get(gid_str, {})
        submissions = gdata.get("submissions", {})
        sub = submissions.get(submission_id)

        if not sub:
            await interaction.response.send_message("❌ This application submission could not be found.", ephemeral=True)
            return

        if sub.get("status") != "pending":
            await interaction.response.send_message(
                f"⚠️ This application has already been **{sub.get('status').upper()}** by <@{sub.get('reviewer_id')}>.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)

        cfg = get_app_config(gid_str)
        guild = interaction.guild
        applicant_id = sub.get("applicant_id")
        applicant = guild.get_member(applicant_id) if guild else None

        now_ts = int(discord.utils.utcnow().timestamp())
        reviewer = interaction.user

        if action == "approve":
            sub["status"] = "approved"
            sub["reviewer_id"] = reviewer.id
            sub["reviewed_at"] = datetime.datetime.utcnow().isoformat()
            db.save_data()

            role_msg = ""
            approved_role_id = cfg.get("approved_role_id")
            granted_role = None
            if approved_role_id and guild:
                granted_role = guild.get_role(int(approved_role_id))
                if granted_role and applicant:
                    try:
                        await applicant.add_roles(granted_role, reason=f"Staff application approved by {reviewer}")
                        role_msg = f"\n**Role Granted:** {granted_role.mention}"
                    except Exception as e:
                        role_msg = f"\n⚠️ *Failed to grant role {granted_role.mention}: {e}*"

            # Update Review Channel Embed
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            embed.color = 0x10b981
            embed.set_field_at(
                0,
                name=embed.fields[0].name,
                value=embed.fields[0].value,
                inline=False
            ) if False else None  # preserve fields

            # Update description header with status
            new_desc = (
                f"**Applicant:** <@{applicant_id}> (ID: `{applicant_id}`)\n"
                f"**Status:** ✅ **APPROVED** by {reviewer.mention} (<t:{now_ts}:R>)"
                f"{role_msg}"
            )
            embed.description = new_desc

            # Disable buttons
            for item in interaction.message.components:
                for child in getattr(item, "children", []):
                    child.disabled = True
            
            # Create a disabled view to show decision
            disabled_view = discord.ui.View()
            btn_app = discord.ui.Button(label=f"Approved by {reviewer.display_name}", style=discord.ButtonStyle.success, emoji="✅", disabled=True)
            disabled_view.add_item(btn_app)

            await interaction.message.edit(embed=embed, view=disabled_view)

            # Post decision as an embedded box in review channel
            app_num = sub.get('number', 0)
            app_log_embed = discord.Embed(
                title=f"✅ Staff Application Approved • #{app_num:04d}",
                description=(
                    f"**Applicant:** <@{applicant_id}> (`{applicant.name if applicant else applicant_id}`)\n"
                    f"**Reviewed By:** {reviewer.mention}\n"
                    f"**Decision:** ✅ **Approved**\n"
                    f"**Assigned Role:** {granted_role.mention if granted_role else 'None'}\n"
                    f"**Application Card:** [Jump to Application]({interaction.message.jump_url})"
                ),
                color=0x10b981,
                timestamp=discord.utils.utcnow()
            )
            app_log_embed.set_author(name=f"Decision by {reviewer.display_name}", icon_url=reviewer.display_avatar.url if reviewer.display_avatar else None)
            if applicant and hasattr(applicant, "display_avatar") and applicant.display_avatar:
                app_log_embed.set_thumbnail(url=applicant.display_avatar.url)
            app_log_embed.set_footer(text=f"{guild.name} • Application Review", icon_url=guild.icon.url if guild.icon else None)
            await interaction.followup.send(embed=app_log_embed)

            # Send Congratulatory DM to Applicant
            app_cfg = cfg.get("approved_msg", {})
            raw_title = app_cfg.get("title", "🎉 Application Approved • {server}")
            raw_desc = app_cfg.get(
                "description",
                "Congratulations {user}!\n\nYour staff application for **{server}** has been **APPROVED**! 🎉\nYou have been granted the {role} role. Welcome to the team!"
            )
            color_int = hex_to_int(app_cfg.get("color", "#10b981"), 0x10b981)

            # In DMs, role mention <@&id> renders as @unknown-role because DMs have no server context.
            # Using bold role name e.g. **Staff** or **Moderator** ensures clean, authentic rendering.
            role_dm_str = f"**@{granted_role.name}**" if granted_role else "**Staff**"
            role_name_str = granted_role.name if granted_role else "Staff"

            dm_title = clean_embed_title(replace_plain_emojis(
                raw_title.replace("{server}", guild.name).replace("{user}", applicant.name if applicant else "Applicant"),
                bot=self.bot, guild=guild, guild_id=gid_str
            ))
            dm_desc = normalize_discord_markdown(replace_plain_emojis(
                raw_desc.replace("{server}", guild.name)
                        .replace("{user}", applicant.mention if applicant else f"<@{applicant_id}>")
                        .replace("{username}", applicant.name if applicant else "Applicant")
                        .replace("{role}", role_dm_str)
                        .replace("{role_name}", role_name_str),
                bot=self.bot, guild=guild, guild_id=gid_str
            ))

            # Strip/convert any residual <@&id> role mentions to role names so Discord DM never shows @unknown-role
            def _clean_dm_role_mention(m):
                r_id = int(m.group(1))
                r = guild.get_role(r_id)
                return f"**@{r.name}**" if r else "**Staff**"
            dm_desc = re.sub(r"<@&(\d+)>", _clean_dm_role_mention, dm_desc)
            dm_title = re.sub(r"<@&(\d+)>", _clean_dm_role_mention, dm_title)

            dm_embed = discord.Embed(title=dm_title, description=dm_desc, color=color_int)
            dm_embed.set_footer(text=f"{guild.name} • Applications", icon_url=guild.icon.url if guild.icon else None)
            dm_embed.timestamp = discord.utils.utcnow()

            if applicant:
                try:
                    await applicant.send(embed=dm_embed)
                except Exception:
                    pass
            else:
                try:
                    user_obj = await self.bot.fetch_user(applicant_id)
                    if user_obj:
                        await user_obj.send(embed=dm_embed)
                except Exception:
                    pass

        elif action == "reject":
            sub["status"] = "rejected"
            sub["reviewer_id"] = reviewer.id
            sub["reviewed_at"] = datetime.datetime.utcnow().isoformat()
            sub["reason"] = reason
            db.save_data()

            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            embed.color = 0xef4444

            new_desc = (
                f"**Applicant:** <@{applicant_id}> (ID: `{applicant_id}`)\n"
                f"**Status:** ❌ **REJECTED** by {reviewer.mention} (<t:{now_ts}:R>)\n"
                f"**Reason:** {reason}"
            )
            embed.description = new_desc

            disabled_view = discord.ui.View()
            btn_rej = discord.ui.Button(label=f"Rejected by {reviewer.display_name}", style=discord.ButtonStyle.danger, emoji="❌", disabled=True)
            disabled_view.add_item(btn_rej)

            await interaction.message.edit(embed=embed, view=disabled_view)

            # Post decision as an embedded box in review channel
            app_num = sub.get('number', 0)
            rej_log_embed = discord.Embed(
                title=f"❌ Staff Application Rejected • #{app_num:04d}",
                description=(
                    f"**Applicant:** <@{applicant_id}> (`{applicant.name if applicant else applicant_id}`)\n"
                    f"**Reviewed By:** {reviewer.mention}\n"
                    f"**Decision:** ❌ **Rejected**\n"
                    f"**Reason:** {reason}\n"
                    f"**Application Card:** [Jump to Application]({interaction.message.jump_url})"
                ),
                color=0xef4444,
                timestamp=discord.utils.utcnow()
            )
            rej_log_embed.set_author(name=f"Decision by {reviewer.display_name}", icon_url=reviewer.display_avatar.url if reviewer.display_avatar else None)
            if applicant and hasattr(applicant, "display_avatar") and applicant.display_avatar:
                rej_log_embed.set_thumbnail(url=applicant.display_avatar.url)
            rej_log_embed.set_footer(text=f"{guild.name} • Application Review", icon_url=guild.icon.url if guild.icon else None)
            await interaction.followup.send(embed=rej_log_embed)

            # Send Rejection DM to Applicant
            rej_cfg = cfg.get("rejected_msg", {})
            raw_title = rej_cfg.get("title", "Application Update • {server}")
            raw_desc = rej_cfg.get(
                "description",
                "Hello {user},\n\nThank you for taking the time to apply for a staff position in **{server}**.\nAfter careful review, we regret to inform you that your application was not accepted at this time.\n\n**Reason:** {reason}\n\nYou are welcome to re-apply in the future."
            )
            color_int = hex_to_int(rej_cfg.get("color", "#ef4444"), 0xef4444)

            dm_title = clean_embed_title(replace_plain_emojis(
                raw_title.replace("{server}", guild.name).replace("{user}", applicant.name if applicant else "Applicant"),
                bot=self.bot, guild=guild, guild_id=gid_str
            ))
            dm_desc = normalize_discord_markdown(replace_plain_emojis(
                raw_desc.replace("{server}", guild.name)
                        .replace("{user}", applicant.mention if applicant else f"<@{applicant_id}>")
                        .replace("{username}", applicant.name if applicant else "Applicant")
                        .replace("{reason}", reason),
                bot=self.bot, guild=guild, guild_id=gid_str
            ))

            dm_embed = discord.Embed(title=dm_title, description=dm_desc, color=color_int)
            dm_embed.set_footer(text=f"{guild.name} • Applications", icon_url=guild.icon.url if guild.icon else None)
            dm_embed.timestamp = discord.utils.utcnow()

            if applicant:
                try:
                    await applicant.send(embed=dm_embed)
                except Exception:
                    pass
            else:
                try:
                    user_obj = await self.bot.fetch_user(applicant_id)
                    if user_obj:
                        await user_obj.send(embed=dm_embed)
                except Exception:
                    pass

    # ─────────────────────────────────────────────────────────────────────────
    # SLASH COMMANDS
    # ─────────────────────────────────────────────────────────────────────────

    app_group = app_commands.Group(name="application", description="Staff application system commands", default_permissions=discord.Permissions(administrator=True))

    @app_group.command(name="panel", description="Deploy the application panel to a channel.")
    @app_commands.describe(channel="Channel where the interactive application embed will be posted")
    @app_commands.default_permissions(administrator=True)
    async def application_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await ensure_admin_or_owner(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        gid_str = str(interaction.guild.id)
        cfg = get_app_config(gid_str)
        p_cfg = cfg.get("panel", {})

        title = clean_embed_title(replace_plain_emojis(p_cfg.get("title", "📋 Staff Application"), bot=self.bot, guild=interaction.guild))
        desc = normalize_discord_markdown(replace_plain_emojis(p_cfg.get("description", "Click below to apply!"), bot=self.bot, guild=interaction.guild))
        color = hex_to_int(p_cfg.get("color", "#5865f2"))
        footer = p_cfg.get("footer", "Friday Applications • Click below to apply")

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.set_footer(text=footer, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.timestamp = discord.utils.utcnow()

        thumbnail_mode = str(p_cfg.get("thumbnail_mode", "friday")).lower()
        if thumbnail_mode == "server" and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        elif thumbnail_mode == "friday" and self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        # Support large banner image / GIF from URL or local upload
        banner_url = str(p_cfg.get("image_url") or p_cfg.get("banner") or "").strip()
        discord_file = None
        if banner_url:
            if banner_url.startswith("/static/"):
                fname = os.path.basename(banner_url)
                import os
                fpath = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "uploads", "application_banners", fname)
                if not os.path.exists(fpath):
                    fpath = os.path.join("dashboard", "static", "uploads", "application_banners", fname)
                if os.path.exists(fpath):
                    discord_file = discord.File(fpath, filename=fname)
                    embed.set_image(url=f"attachment://{fname}")
            elif banner_url.startswith(("http://", "https://")):
                embed.set_image(url=banner_url)

        btn_label = p_cfg.get("button_label", "Apply Now")
        btn_emoji_raw = p_cfg.get("button_emoji", "📝")
        btn_style = get_button_style(p_cfg.get("button_style", "primary"))
        btn_emoji = resolve_single_emoji(btn_emoji_raw, bot=self.bot, guild=interaction.guild, guild_id=gid_str)

        try:
            temp_view = discord.ui.View()
            temp_btn = discord.ui.Button(label=btn_label, style=btn_style, emoji=btn_emoji)
            temp_view.add_item(temp_btn)
            if discord_file:
                msg = await channel.send(embed=embed, file=discord_file, view=temp_view)
            else:
                msg = await channel.send(embed=embed, view=temp_view)

            # Store panel record
            gdata = db.applications.setdefault(gid_str, {})
            panels = gdata.setdefault("panels", {})
            panels[str(msg.id)] = {
                "channel_id": channel.id,
                "button_label": btn_label,
                "button_emoji": btn_emoji_raw,
                "button_style": p_cfg.get("button_style", "primary"),
                "image_url": banner_url
            }
            cfg["panel_channel_id"] = str(channel.id)
            db.save_data()

            # Attach actual persistent view
            actual_view = ApplicationPanelView(self, msg.id)
            actual_view.clear_items()
            real_btn = discord.ui.Button(
                label=btn_label,
                style=btn_style,
                emoji=btn_emoji,
                custom_id=f"app_apply_btn_{msg.id}"
            )
            real_btn.callback = actual_view.apply_button.callback
            actual_view.add_item(real_btn)

            await msg.edit(view=actual_view)
            self.bot.add_view(actual_view, message_id=msg.id)

            await interaction.followup.send(f"✅ **Application panel successfully deployed** in {channel.mention}!")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to post panel: {e}")

    @app_group.command(name="set_channel", description="Set panel channel and staff review log channel.")
    @app_commands.describe(review_channel="Channel where submitted applications are logged for staff review")
    @app_commands.default_permissions(administrator=True)
    async def set_channel(self, interaction: discord.Interaction, review_channel: discord.TextChannel):
        if not await ensure_admin_or_owner(interaction):
            return
        gid_str = str(interaction.guild.id)
        cfg = get_app_config(gid_str)
        cfg["review_channel_id"] = str(review_channel.id)
        db.save_data()

        await interaction.response.send_message(
            f"✅ **Staff Review Channel configured:** {review_channel.mention}\nAll incoming applications will be posted there with Approve & Reject controls.",
            ephemeral=True
        )

    @app_group.command(name="role", description="Set the role automatically granted when an application is approved.")
    @app_commands.describe(role="Role to grant upon approval")
    @app_commands.default_permissions(administrator=True)
    async def set_role(self, interaction: discord.Interaction, role: discord.Role):
        if not await ensure_admin_or_owner(interaction):
            return
        gid_str = str(interaction.guild.id)
        cfg = get_app_config(gid_str)
        cfg["approved_role_id"] = str(role.id)
        db.save_data()

        await interaction.response.send_message(
            f"✅ **Approval Role Set:** {role.mention}\nMembers will automatically receive this role when their application is approved by an administrator.",
            ephemeral=True
        )

    @app_group.command(name="mode", description="Configure where applications are filled (in a private channel or in DM).")
    @app_commands.choices(delivery_mode=[
        app_commands.Choice(name="🏢 In Server (Private Temporary Channel)", value="server"),
        app_commands.Choice(name="📬 Direct Message (DM)", value="dm")
    ])
    @app_commands.default_permissions(administrator=True)
    async def set_mode(self, interaction: discord.Interaction, delivery_mode: str):
        if not await ensure_admin_or_owner(interaction):
            return
        gid_str = str(interaction.guild.id)
        cfg = get_app_config(gid_str)
        cfg["delivery_mode"] = delivery_mode
        db.save_data()

        mode_name = "🏢 In Server (Private Temporary Channel)" if delivery_mode == "server" else "📬 Direct Message (DM)"
        await interaction.response.send_message(
            f"✅ **Application delivery mode updated to:** **{mode_name}**.",
            ephemeral=True
        )

    @app_group.command(name="question_add", description="Add a new question to the application form.")
    @app_commands.describe(question="The question to ask the applicant")
    @app_commands.default_permissions(administrator=True)
    async def question_add(self, interaction: discord.Interaction, question: str):
        if not await ensure_admin_or_owner(interaction):
            return
        gid_str = str(interaction.guild.id)
        cfg = get_app_config(gid_str)
        questions = cfg.setdefault("questions", [])
        questions.append(question.strip())
        db.save_data()

        await interaction.response.send_message(
            f"✅ Added Question #{len(questions)}: **{question.strip()}**",
            ephemeral=True
        )

    @app_group.command(name="question_remove", description="Remove a question by its number.")
    @app_commands.describe(number="The question number to remove (1, 2, ...)")
    @app_commands.default_permissions(administrator=True)
    async def question_remove(self, interaction: discord.Interaction, number: int):
        if not await ensure_admin_or_owner(interaction):
            return
        gid_str = str(interaction.guild.id)
        cfg = get_app_config(gid_str)
        questions = cfg.setdefault("questions", [])

        if number < 1 or number > len(questions):
            await interaction.response.send_message(f"❌ Invalid question number. Currently there are {len(questions)} questions.", ephemeral=True)
            return

        removed = questions.pop(number - 1)
        db.save_data()

        await interaction.response.send_message(
            f"🗑️ Removed Question #{number}: **{removed}**\nTotal remaining: {len(questions)}.",
            ephemeral=True
        )

    @app_group.command(name="question_list", description="List all configured application questions.")
    @app_commands.default_permissions(administrator=True)
    async def question_list(self, interaction: discord.Interaction):
        if not await ensure_admin_or_owner(interaction):
            return
        gid_str = str(interaction.guild.id)
        cfg = get_app_config(gid_str)
        questions = cfg.get("questions", [])

        if not questions:
            await interaction.response.send_message("ℹ️ No questions configured yet. Use `/application question_add` to add one.", ephemeral=True)
            return

        lines = [f"`#{i}` **{q}**" for i, q in enumerate(questions, start=1)]
        embed = discord.Embed(
            title=f"📋 Application Questions ({len(questions)})",
            description="\n".join(lines),
            color=0x5865f2
        )
        embed.set_footer(text="Reorder or add more questions in the Web Dashboard!")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_group.command(name="view_config", description="Display current application module configuration.")
    @app_commands.default_permissions(administrator=True)
    async def view_config(self, interaction: discord.Interaction):
        if not await ensure_admin_or_owner(interaction):
            return
        gid_str = str(interaction.guild.id)
        cfg = get_app_config(gid_str)

        panel_ch = interaction.guild.get_channel(int(cfg["panel_channel_id"])) if cfg.get("panel_channel_id") else None
        review_ch = interaction.guild.get_channel(int(cfg["review_channel_id"])) if cfg.get("review_channel_id") else None
        role = interaction.guild.get_role(int(cfg["approved_role_id"])) if cfg.get("approved_role_id") else None
        mode = "🏢 In Server (Private Temp Channel)" if cfg.get("delivery_mode") == "server" else "📬 Direct Message (DM)"

        embed = discord.Embed(title="⚙️ Application Module Configuration", color=0x5865f2)
        embed.add_field(name="Delivery Mode", value=mode, inline=True)
        embed.add_field(name="Panel Channel", value=panel_ch.mention if panel_ch else "*Not set*", inline=True)
        embed.add_field(name="Review Channel", value=review_ch.mention if review_ch else "*Not set*", inline=True)
        embed.add_field(name="Approval Role", value=role.mention if role else "*None*", inline=True)
        embed.add_field(name="Questions Configured", value=str(len(cfg.get("questions", []))), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Applications(bot))

