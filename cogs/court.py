import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import re
import time
import random
import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from database import db
from emoji_utils import replace_plain_emojis

# Default Court Configuration Template
DEFAULT_COURT_CONFIG = {
    "enabled": True,
    "court_channel": None,
    "jury_voting": True,
    "jury_duration": 45,        # seconds for jury poll
    "summons_timeout": 90,      # seconds to plead before default judgment
    "guilty_role": None,        # role ID for guilty penalty
    "innocent_role": None,      # role ID for exoneration
    "role_duration": 60,        # penalty duration in minutes
    "evidence_limit": 15,       # strictly last 15 messages between plaintiff & defendant
    "emojis": {
        "gavel": "⚖️",
        "guilty": "🔴",
        "innocent": "🟢",
        "docket": "📜"
    }
}

def get_court_config(guild_id: str) -> dict:
    if not hasattr(db, "court_config") or not isinstance(db.court_config, dict):
        db.court_config = {}
    cfg = db.court_config.setdefault(str(guild_id), {})
    for k, v in DEFAULT_COURT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
    if "emojis" not in cfg or not isinstance(cfg["emojis"], dict):
        cfg["emojis"] = dict(DEFAULT_COURT_CONFIG["emojis"])
    return cfg

def generate_case_id() -> str:
    rnd = random.randint(1000, 9999)
    return f"CASE-{rnd}"

def get_user_court_record(guild_id: str, user_id: str) -> dict:
    if not hasattr(db, "court_records") or not isinstance(db.court_records, dict):
        db.court_records = {}
    g_recs = db.court_records.setdefault(str(guild_id), {})
    return g_recs.setdefault(str(user_id), {
        "name": "Unknown",
        "sued_others": 0,
        "been_sued": 0,
        "convictions": 0,
        "acquittals": 0,
        "won_as_plaintiff": 0,
        "total_trials": 0
    })


# ─────────────────────────────────────────────────────────────
# MODALS: STATEMENT & EVIDENCE SUBMISSION
# ─────────────────────────────────────────────────────────────

class DefendantStatementModal(discord.ui.Modal):
    def __init__(self, trial_runner, defendant: discord.Member):
        super().__init__(title="⚖️ Defense Statement & Plea")
        self.trial_runner = trial_runner
        self.defendant = defendant

        self.defense_statement = discord.ui.TextInput(
            label="Your Defense & Explanation",
            style=discord.TextStyle.paragraph,
            placeholder="Explain why you are NOT GUILTY of the charges...",
            required=True,
            max_length=1200
        )
        self.alibi_notes = discord.ui.TextInput(
            label="Alibi, Mitigating Factors, or Excuses",
            style=discord.TextStyle.paragraph,
            placeholder="Any context, lag, friendly joke, or counterpoints...",
            required=False,
            max_length=500
        )
        self.add_item(self.defense_statement)
        self.add_item(self.alibi_notes)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        statement = str(self.defense_statement.value).strip()
        alibi = str(self.alibi_notes.value).strip()
        full_statement = statement
        if alibi:
            full_statement += f"\n**Context / Alibi:** {alibi}"
        await self.trial_runner.receive_plea(interaction, plea="not_guilty", statement=full_statement)


class PlaintiffEvidenceModal(discord.ui.Modal):
    def __init__(self, trial_runner, plaintiff: discord.Member):
        super().__init__(title="📜 Plaintiff's Rebuttal / Evidence")
        self.trial_runner = trial_runner
        self.plaintiff = plaintiff

        self.plaintiff_statement = discord.ui.TextInput(
            label="Additional Evidence & Details",
            style=discord.TextStyle.paragraph,
            placeholder="Detail the defendant's transgressions, broken bets, or offenses...",
            required=True,
            max_length=1200
        )
        self.add_item(self.plaintiff_statement)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        statement = str(self.plaintiff_statement.value).strip()
        await self.trial_runner.receive_plaintiff_statement(interaction, statement=statement)


# ─────────────────────────────────────────────────────────────
# VIEWS: SUMMONS & JURY VOTING
# ─────────────────────────────────────────────────────────────

class CourtSummonsView(discord.ui.View):
    def __init__(self, trial_runner, defendant: discord.Member, plaintiff: discord.Member, timeout: int = 90):
        super().__init__(timeout=timeout)
        self.trial_runner = trial_runner
        self.defendant = defendant
        self.plaintiff = plaintiff

    @discord.ui.button(label="Plead Not Guilty", style=discord.ButtonStyle.primary, emoji="⚖️")
    async def not_guilty_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.defendant.id:
            await interaction.response.send_message("❌ Only the summoned Defendant can enter a plea for this case.", ephemeral=True)
            return
        modal = DefendantStatementModal(self.trial_runner, self.defendant)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Plead Guilty", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def guilty_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.defendant.id:
            await interaction.response.send_message("❌ Only the summoned Defendant can enter a plea for this case.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.trial_runner.receive_plea(interaction, plea="guilty", statement="The Defendant formally pleaded GUILTY and threw themselves upon the mercy of the Court.")

    @discord.ui.button(label="Submit Plaintiff Notes", style=discord.ButtonStyle.secondary, emoji="📜")
    async def evidence_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.plaintiff.id:
            await interaction.response.send_message("❌ Only the Plaintiff can submit additional plaintiff notes.", ephemeral=True)
            return
        modal = PlaintiffEvidenceModal(self.trial_runner, self.plaintiff)
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        await self.trial_runner.handle_summons_timeout()


class CourtJuryView(discord.ui.View):
    def __init__(self, trial_runner, jury_duration: int = 45):
        super().__init__(timeout=jury_duration)
        self.trial_runner = trial_runner
        self.votes: Dict[int, str] = {}  # user_id -> 'guilty' or 'innocent'
        self.guilty_btn = None
        self.innocent_btn = None
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        guilty_count = sum(1 for v in self.votes.values() if v == 'guilty')
        innocent_count = sum(1 for v in self.votes.values() if v == 'innocent')

        self.guilty_btn = discord.ui.Button(
            label=f"Guilty ({guilty_count})",
            style=discord.ButtonStyle.danger,
            emoji="🔴",
            custom_id="jury_guilty"
        )
        self.guilty_btn.callback = self._handle_guilty
        self.add_item(self.guilty_btn)

        self.innocent_btn = discord.ui.Button(
            label=f"Innocent ({innocent_count})",
            style=discord.ButtonStyle.success,
            emoji="🟢",
            custom_id="jury_innocent"
        )
        self.innocent_btn.callback = self._handle_innocent
        self.add_item(self.innocent_btn)

    async def _handle_guilty(self, interaction: discord.Interaction):
        if interaction.user.id in (self.trial_runner.plaintiff.id, self.trial_runner.defendant.id):
            await interaction.response.send_message("❌ Litigants (plaintiff and defendant) cannot vote on their own jury panel!", ephemeral=True)
            return
        prev = self.votes.get(interaction.user.id)
        if prev == "guilty":
            await interaction.response.send_message("⚖️ You have already cast your jury vote for **Guilty**.", ephemeral=True)
            return
        self.votes[interaction.user.id] = "guilty"
        self._build_buttons()
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass

    async def _handle_innocent(self, interaction: discord.Interaction):
        if interaction.user.id in (self.trial_runner.plaintiff.id, self.trial_runner.defendant.id):
            await interaction.response.send_message("❌ Litigants (plaintiff and defendant) cannot vote on their own jury panel!", ephemeral=True)
            return
        prev = self.votes.get(interaction.user.id)
        if prev == "innocent":
            await interaction.response.send_message("⚖️ You have already cast your jury vote for **Innocent**.", ephemeral=True)
            return
        self.votes[interaction.user.id] = "innocent"
        self._build_buttons()
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.trial_runner.jury_message:
            try:
                await self.trial_runner.jury_message.edit(view=self)
            except Exception:
                pass
        await self.trial_runner.finish_jury_phase(self.votes)


# ─────────────────────────────────────────────────────────────
# TRIAL RUNNER CONTROLLER
# ─────────────────────────────────────────────────────────────

class TrialRunner:
    """Manages the full lifecycle of a single courtroom trial."""
    def __init__(self, cog, interaction: discord.Interaction, defendant: discord.Member, charges: str, initial_statement: Optional[str] = None):
        self.cog = cog
        self.bot = cog.bot
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.plaintiff = interaction.user
        self.defendant = defendant
        self.charges = charges
        self.plaintiff_statement = initial_statement or ""
        self.defendant_statement = ""
        self.plea = None
        self.case_id = generate_case_id()
        self.cfg = get_court_config(str(self.guild.id))
        self.summons_message: Optional[discord.Message] = None
        self.summons_view: Optional[CourtSummonsView] = None
        self.jury_message: Optional[discord.Message] = None
        self.jury_view: Optional[CourtJuryView] = None
        self.chat_evidence: List[dict] = []
        self.resolved = False

    async def start(self):
        emojis = self.cfg.get("emojis", {})
        gavel_e = emojis.get("gavel", "⚖️")
        timeout_sec = int(self.cfg.get("summons_timeout", 90))

        embed = discord.Embed(
            title=f"{gavel_e} THE COURT OF FRIDAY: OFFICIAL WRIT OF SUMMONS",
            description=(
                f"**Docket Case ID:** `{self.case_id}`\n"
                f"**Presiding Magistrate:** Chief Justice Friday\n"
                f"**Plaintiff:** {self.plaintiff.mention}\n"
                f"**Accused Defendant:** {self.defendant.mention}\n\n"
                f"**Official Charge(s):**\n"
                f"```fix\n{self.charges}\n```\n"
                f"⚖️ {self.defendant.mention}, you stand accused before the High Vibe Tribunal!\n"
                f"You have **{timeout_sec} seconds** to enter your formal plea using the buttons below.\n\n"
                f"*Failure to appear or enter a plea will result in an immediate Default Judgment for Contempt of Court!*"
            ),
            color=0xF59E0B
        )
        if self.defendant.display_avatar:
            embed.set_thumbnail(url=self.defendant.display_avatar.url)
        embed.set_footer(text=f"Court of Friday • Docket {self.case_id} • Fair Trial Guaranteed")
        embed.timestamp = discord.utils.utcnow()

        self.summons_view = CourtSummonsView(self, self.defendant, self.plaintiff, timeout=timeout_sec)
        self.summons_message = await self.channel.send(
            content=f"🔔 **COURT CONVENED!** {self.defendant.mention}, you have been sued by {self.plaintiff.mention}!",
            embed=embed,
            view=self.summons_view
        )

    async def receive_plaintiff_statement(self, interaction: discord.Interaction, statement: str):
        self.plaintiff_statement = statement
        await interaction.followup.send(f"✅ **Evidence Accepted:** Additional plaintiff testimony logged for Docket `{self.case_id}`.", ephemeral=True)

    async def receive_plea(self, interaction: discord.Interaction, plea: str, statement: str):
        if self.resolved:
            return
        self.plea = plea
        self.defendant_statement = statement

        # Disable summons view
        if self.summons_view:
            for item in self.summons_view.children:
                item.disabled = True
            if self.summons_message:
                try:
                    await self.summons_message.edit(view=self.summons_view)
                except Exception:
                    pass

        if plea == "guilty":
            try:
                await interaction.followup.send("🏳️ **Guilty Plea Entered:** The accused has admitted to the charges. The Court will now proceed directly to judicial deliberation and sentencing!", ephemeral=True)
            except Exception:
                pass
            await self.deliberate_and_sentence(jury_votes={"guilty": 1, "innocent": 0})
        else:
            try:
                await interaction.followup.send("⚖️ **Not Guilty Plea Logged:** Trial commences! Evidence is being subpoenaed and the Server Jury is being empaneled.", ephemeral=True)
            except Exception:
                pass
            await self.proceed_to_trial()

    async def handle_summons_timeout(self):
        if self.resolved or self.plea:
            return
        self.resolved = True
        self.cog.clear_active_trial(str(self.guild.id))

        if self.summons_view:
            for item in self.summons_view.children:
                item.disabled = True
            if self.summons_message:
                try:
                    await self.summons_message.edit(view=self.summons_view)
                except Exception:
                    pass

        embed = discord.Embed(
            title=f"⚖️ CONTEMPT OF COURT: DEFAULT JUDGMENT RENDERED",
            description=(
                f"**Docket Case ID:** `{self.case_id}`\n"
                f"**Defendant:** {self.defendant.mention}\n\n"
                f"🚨 The Defendant failed to appear and plea within the allotted time!\n"
                f"Chief Justice Friday hereby finds **{self.defendant.display_name}** in willful Contempt of Court.\n\n"
                f"**Verdict:** **DEFAULT SUMMARY GUILTY**\n"
                f"**Penalty:** Contempt of Court penalty role assigned, public reprimand issued."
            ),
            color=0xEF4444
        )
        embed.set_footer(text=f"Court of Friday • Case Closed via Default Judgment")
        embed.timestamp = discord.utils.utcnow()

        await self.channel.send(embed=embed)
        await self._apply_penalties(verdict="GUILTY", rationale="Defendant fled the jurisdiction and refused to enter a plea.")
        self._record_case(verdict="GUILTY", rationale="Default judgment entered for contempt of court.", sentence="Fined and reprimanded for dodging summons.")

    async def proceed_to_trial(self):
        # Step 1: Scrape channel history strictly for Plaintiff & Defendant
        evidence_limit = int(self.cfg.get("evidence_limit", 15))
        self.chat_evidence = await self.cog.fetch_filtered_evidence(
            channel=self.channel,
            plaintiff_id=self.plaintiff.id,
            defendant_id=self.defendant.id,
            limit=evidence_limit
        )

        evidence_summary_lines = []
        if self.chat_evidence:
            for item in self.chat_evidence:
                auth = f"@{item['author_name']}"
                snippet = item['content'][:120]
                evidence_summary_lines.append(f"`[{item['timestamp']}]` **{auth}:** {snippet}")
        else:
            evidence_summary_lines.append("*No recent direct dialogue between the parties was found in this channel.*")

        evidence_text = "\n".join(evidence_summary_lines)

        docket_embed = discord.Embed(
            title=f"📜 DOCKET {self.case_id}: EVIDENCE & STATEMENTS",
            description=(
                f"**Plaintiff's Allegations:**\n> *\"{self.charges}\"*\n"
                f"{f'**Plaintiff Statement:** {self.plaintiff_statement}' if self.plaintiff_statement else ''}\n\n"
                f"**Defendant's Defense:**\n> *\"{self.defendant_statement}\"*\n\n"
                f"**Subpoenaed Chat Evidence (Strictly Litigants Only, Last {len(self.chat_evidence)} Messages):**\n"
                f"{evidence_text}\n\n"
                f"🏛️ **THE FLOOR IS NOW OPEN TO THE SERVER JURY!**\n"
                f"Members of the server, cast your vote below! Does the defendant walk free, or are they guilty as charged?"
            ),
            color=0x3B82F6
        )
        docket_embed.set_footer(text="The Server Jury has 45 seconds to cast their ballots.")
        await self.channel.send(embed=docket_embed)

        # Step 2: Open Server Jury Poll
        jury_dur = int(self.cfg.get("jury_duration", 45))
        self.jury_view = CourtJuryView(self, jury_duration=jury_dur)
        self.jury_message = await self.channel.send(
            content=f"🗳️ **JURY DELIBERATION ACTIVE:** You have **{jury_dur} seconds** to vote on Docket `{self.case_id}`!",
            view=self.jury_view
        )

    async def finish_jury_phase(self, votes: Dict[int, str]):
        guilty_count = sum(1 for v in votes.values() if v == 'guilty')
        innocent_count = sum(1 for v in votes.values() if v == 'innocent')
        total = guilty_count + innocent_count

        announcement = (
            f"🔔 **JURY DELIBERATION CONCLUDED!**\n"
            f"Total Ballots Cast: **{total}** (🔴 Guilty: **{guilty_count}** | 🟢 Innocent: **{innocent_count}**)\n\n"
            f"⚖️ Chief Justice Friday is now deliberating, reviewing the evidence, and formulating the supreme judicial decree..."
        )
        await self.channel.send(announcement)
        await self.deliberate_and_sentence(jury_votes={"guilty": guilty_count, "innocent": innocent_count})

    async def deliberate_and_sentence(self, jury_votes: dict):
        self.resolved = True
        self.cog.clear_active_trial(str(self.guild.id))

        # Invoke Friday's LLM
        verdict_data = await self.cog.generate_ai_verdict(
            case_id=self.case_id,
            plaintiff=self.plaintiff,
            defendant=self.defendant,
            charges=self.charges,
            plaintiff_statement=self.plaintiff_statement,
            defendant_statement=self.defendant_statement,
            chat_evidence=self.chat_evidence,
            jury_votes=jury_votes,
            plea=self.plea
        )

        verdict = verdict_data.get("verdict", "GUILTY").upper()
        analysis = verdict_data.get("analysis", "The Court has reviewed all presented facts.")
        sentence = verdict_data.get("sentence", "Defendant is reprimanded.")

        # Determine embed styling & color
        emojis = self.cfg.get("emojis", {})
        if "GUILTY" in verdict and "NOT" not in verdict:
            verdict_clean = "GUILTY"
            color = 0xEF4444  # Red
            status_emoji = emojis.get("guilty", "🔴")
        elif "NOT GUILTY" in verdict:
            verdict_clean = "NOT GUILTY"
            color = 0x10B981  # Green
            status_emoji = emojis.get("innocent", "🟢")
        elif "BOTH" in verdict:
            verdict_clean = "MUTUAL CLOWNS (BOTH GUILTY)"
            color = 0x8B5CF6  # Purple
            status_emoji = "🤡"
        else:
            verdict_clean = "MISTRIAL / DISMISSED"
            color = 0x6B7280  # Gray
            status_emoji = "⚖️"

        g_votes = jury_votes.get("guilty", 0)
        i_votes = jury_votes.get("innocent", 0)
        tot = g_votes + i_votes
        g_pct = int((g_votes / tot * 100)) if tot > 0 else 0
        i_pct = int((i_votes / tot * 100)) if tot > 0 else 0

        verdict_embed = discord.Embed(
            title=f"⚖️ SUPREME COURT OF FRIDAY: FINAL VERDICT",
            description=(
                f"**Docket ID:** `{self.case_id}`\n"
                f"**Official Decree:** {status_emoji} **{verdict_clean}**\n\n"
                f"**Plaintiff:** {self.plaintiff.mention}\n"
                f"**Defendant:** {self.defendant.mention}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"### ⚖️ Judicial Analysis & Opinion\n"
                f"{analysis}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"### 🔨 Sentence & Remedial Order\n"
                f"{sentence}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 **Jury Vote Ratio:** 🔴 `{g_pct}% Guilty` vs 🟢 `{i_pct}% Innocent` ({tot} total votes)"
            ),
            color=color
        )
        if self.defendant.display_avatar:
            verdict_embed.set_thumbnail(url=self.defendant.display_avatar.url)
        verdict_embed.set_footer(text=f"Court of Friday • Case Closed • Chief Justice Friday Presiding")
        verdict_embed.timestamp = discord.utils.utcnow()

        await self.channel.send(embed=verdict_embed)

        # Apply roles and record history
        await self._apply_penalties(verdict=verdict_clean, rationale=analysis)
        self._record_case(verdict=verdict_clean, rationale=analysis, sentence=sentence, jury_votes=jury_votes)

    async def _apply_penalties(self, verdict: str, rationale: str):
        guilty_role_id = self.cfg.get("guilty_role")
        innocent_role_id = self.cfg.get("innocent_role")
        role_duration_mins = int(self.cfg.get("role_duration", 60))
        expires_at = time.time() + (role_duration_mins * 60)

        if "GUILTY" in verdict and "NOT" not in verdict:
            if guilty_role_id:
                try:
                    role = self.guild.get_role(int(guilty_role_id))
                    if role and role not in self.defendant.roles:
                        await self.defendant.add_roles(role, reason=f"Court of Friday Conviction ({self.case_id})")
                        await self.channel.send(f"🚨 **Penalty Enforced:** {self.defendant.mention} has been sentenced with the **{role.name}** role for {role_duration_mins} minutes!")
                except Exception as e:
                    print(f"[Court] Failed to add guilty role: {e}")
        elif "NOT GUILTY" in verdict:
            if innocent_role_id:
                try:
                    role = self.guild.get_role(int(innocent_role_id))
                    if role and role not in self.defendant.roles:
                        await self.defendant.add_roles(role, reason=f"Court of Friday Exoneration ({self.case_id})")
                        await self.channel.send(f"🛡️ **Exoneration Honored:** {self.defendant.mention} has been crowned with **{role.name}**!")
                except Exception as e:
                    print(f"[Court] Failed to add innocent role: {e}")
            if guilty_role_id:
                try:
                    g_role = self.guild.get_role(int(guilty_role_id))
                    if g_role and g_role in self.defendant.roles:
                        await self.defendant.remove_roles(g_role, reason=f"Court of Friday Acquittal ({self.case_id})")
                except Exception:
                    pass

    def _record_case(self, verdict: str, rationale: str, sentence: str, jury_votes: Optional[dict] = None):
        gid = str(self.guild.id)
        if not hasattr(db, "court_cases") or not isinstance(db.court_cases, dict):
            db.court_cases = {}
        role_duration_mins = int(self.cfg.get("role_duration", 60))

        case_entry = {
            "id": self.case_id,
            "guild_id": gid,
            "channel_id": str(self.channel.id),
            "plaintiff_id": str(self.plaintiff.id),
            "plaintiff_name": self.plaintiff.display_name,
            "defendant_id": str(self.defendant.id),
            "defendant_name": self.defendant.display_name,
            "charges": self.charges,
            "plea": self.plea or "contempt_default",
            "plaintiff_statement": self.plaintiff_statement,
            "defendant_statement": self.defendant_statement,
            "evidence_count": len(self.chat_evidence),
            "jury_votes": jury_votes or {"guilty": 0, "innocent": 0},
            "verdict": verdict,
            "rationale": rationale,
            "sentence": sentence,
            "penalty_role_id": str(self.cfg.get("guilty_role")) if "GUILTY" in verdict else None,
            "penalty_expires_at": time.time() + (role_duration_mins * 60) if "GUILTY" in verdict else 0,
            "created_at": time.time(),
            "status": "closed"
        }
        db.court_cases[self.case_id] = case_entry

        # Update career stats in db.court_records
        p_rec = get_user_court_record(gid, str(self.plaintiff.id))
        d_rec = get_user_court_record(gid, str(self.defendant.id))

        p_rec["name"] = self.plaintiff.display_name
        d_rec["name"] = self.defendant.display_name

        p_rec["sued_others"] = p_rec.get("sued_others", 0) + 1
        p_rec["total_trials"] = p_rec.get("total_trials", 0) + 1
        d_rec["been_sued"] = d_rec.get("been_sued", 0) + 1
        d_rec["total_trials"] = d_rec.get("total_trials", 0) + 1

        if "GUILTY" in verdict and "NOT" not in verdict:
            p_rec["won_as_plaintiff"] = p_rec.get("won_as_plaintiff", 0) + 1
            d_rec["convictions"] = d_rec.get("convictions", 0) + 1
        elif "NOT GUILTY" in verdict:
            d_rec["acquittals"] = d_rec.get("acquittals", 0) + 1

        try:
            db.save_data()
        except Exception as e:
            print(f"[Court] Failed to persist court case: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN COG CLASS
# ─────────────────────────────────────────────────────────────

class Court(commands.Cog):
    """The Court of Friday: AI-powered interactive community tribunal."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_trials: Dict[str, str] = {}  # guild_id -> case_id
        self.check_penalty_expirations.start()

    def cog_unload(self):
        self.check_penalty_expirations.cancel()

    def set_active_trial(self, guild_id: str, case_id: str):
        self._active_trials[guild_id] = case_id

    def clear_active_trial(self, guild_id: str):
        self._active_trials.pop(guild_id, None)

    def is_trial_active(self, guild_id: str) -> bool:
        return guild_id in self._active_trials

    async def fetch_filtered_evidence(self, channel: discord.TextChannel, plaintiff_id: int, defendant_id: int, limit: int = 15) -> List[dict]:
        """
        Subpoenas recent channel history, strictly filtering out bot messages and third-party chatter.
        Captures only the direct dialogue between the plaintiff and defendant.
        """
        evidence = []
        try:
            async for m in channel.history(limit=80):
                if m.author.bot:
                    continue
                if m.author.id in (plaintiff_id, defendant_id):
                    content = m.clean_content.strip() if m.clean_content else ""
                    if not content and m.attachments:
                        content = f"[Attachment: {m.attachments[0].filename}]"
                    evidence.append({
                        "author_id": m.author.id,
                        "author_name": m.author.display_name,
                        "content": content or "[Empty message]",
                        "timestamp": m.created_at.strftime("%I:%M %p")
                    })
                    if len(evidence) >= limit:
                        break
        except Exception as e:
            print(f"[Court] Error fetching chat evidence: {e}")

        # Return in chronological order (oldest to newest)
        evidence.reverse()
        return evidence

    async def generate_ai_verdict(
        self,
        case_id: str,
        plaintiff: discord.Member,
        defendant: discord.Member,
        charges: str,
        plaintiff_statement: str,
        defendant_statement: str,
        chat_evidence: List[dict],
        jury_votes: dict,
        plea: Optional[str]
    ) -> dict:
        """Invokes Friday's existing LLM engine to render a witty, authoritative judicial decree."""
        chat_lines = []
        for item in chat_evidence:
            chat_lines.append(f"[{item['timestamp']}] @{item['author_name']}: {item['content']}")
        chat_transcript = "\n".join(chat_lines) if chat_lines else "No prior direct dialogue between the parties was found in channel history."

        g_votes = jury_votes.get("guilty", 0)
        i_votes = jury_votes.get("innocent", 0)

        system_prompt = (
            "You are Chief Justice Friday, the supreme presiding judge of the Court of Friday Discord Tribunal. "
            "You embody the sharp, no-nonsense judicial wit of Judge Judy blended with the tactical AI brilliance and "
            "playful sarcasm of Tony Stark's FRIDAY. You speak with high feminine elegance, supreme authority, and hilarious legal banter. "
            "You dissect weak excuses, highlight funny contradictions in the chat logs, evaluate the community jury vote, and issue a definitive verdict.\n\n"
            "VERDICT CHOICES:\n"
            "- GUILTY: Defendant is caught red-handed, breaking promises, or capping hard.\n"
            "- NOT GUILTY: Charges are baseless, exaggerated, or defendant successfully defended themselves.\n"
            "- BOTH GUILTY: Both plaintiff and defendant are acting like clowns and deserve mutual roast.\n"
            "- MISTRIAL: Frivolous lawsuit that wasted Court GPU cycles.\n\n"
            "STRICT RESPONSE FORMAT (YOU MUST ADHERE TO THIS EXACT STRUCTURE):\n"
            "VERDICT: [GUILTY, NOT GUILTY, BOTH GUILTY, or MISTRIAL]\n"
            "ANALYSIS: [2 to 3 paragraphs of sharp, witty judicial opinion, roasting the behavior, citing chat quotes, and addressing the jury's vote]\n"
            "SENTENCE: [1 to 2 sharp sentences stating the official penalty, formal apology order, or vindication]"
        )

        user_content = (
            f"CASE DOCKET: {case_id}\n"
            f"Plaintiff: @{plaintiff.display_name} (ID: {plaintiff.id})\n"
            f"Defendant: @{defendant.display_name} (ID: {defendant.id})\n"
            f"Charges Filed: \"{charges}\"\n"
            f"Defendant Formal Plea: {plea.upper() if plea else 'UNKNOWN'}\n"
            f"Plaintiff Testimony: \"{plaintiff_statement or 'No additional notes provided.'}\"\n"
            f"Defendant Testimony: \"{defendant_statement or 'Defendant provided no defense.'}\"\n\n"
            f"SUBPOENAED CHAT LOG EVIDENCE (Strictly between Plaintiff and Defendant):\n"
            f"{chat_transcript}\n\n"
            f"COMMUNITY JURY BALLOT TALLY:\n"
            f"Guilty Votes: {g_votes} | Innocent Votes: {i_votes}\n\n"
            f"Chief Justice Friday, please review the docket and pronounce your binding judgment now."
        )

        # 1. Try to use existing AIChat cog directly
        ai_cog = self.bot.get_cog("AIChat")
        llm_reply = None

        if ai_cog and hasattr(ai_cog, "_call_openrouter"):
            try:
                llm_reply = await ai_cog._call_openrouter(
                    messages=[{"role": "user", "content": user_content}],
                    system_prompt=system_prompt,
                    max_tokens=650
                )
            except Exception as e:
                print(f"[Court] AIChat call error: {e}")

        # 2. Autonomous fallback if AIChat cog is unavailable or failed
        if not llm_reply or len(llm_reply) < 30:
            llm_reply = await self._fallback_llm_query(system_prompt, user_content)

        # Parse LLM structured output
        verdict = "GUILTY"
        analysis = "The Court has weighed the evidence and found the accused lacking in credibility."
        sentence = "Defendant is sentenced to public embarrassment."

        if llm_reply:
            v_match = re.search(r'VERDICT:\s*([^\n]+)', llm_reply, re.IGNORECASE)
            if v_match:
                verdict = v_match.group(1).strip().upper()

            a_match = re.search(r'ANALYSIS:\s*(.+?)(?=SENTENCE:|$)', llm_reply, re.DOTALL | re.IGNORECASE)
            if a_match:
                analysis = a_match.group(1).strip()

            s_match = re.search(r'SENTENCE:\s*(.+)', llm_reply, re.DOTALL | re.IGNORECASE)
            if s_match:
                sentence = s_match.group(1).strip()

        return {
            "verdict": verdict,
            "analysis": analysis,
            "sentence": sentence
        }

    async def _fallback_llm_query(self, system_prompt: str, user_content: str) -> Optional[str]:
        """Direct fallback API query in case AIChat cog is not reachable."""
        groq_key = os.getenv("GROQ_API_KEY")
        openrouter_key = (os.getenv("OPENROUTER_API_KEY") or "").split(",")[0].strip()
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 600,
            "temperature": 0.7
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
            # Try Groq
            if groq_key:
                try:
                    payload["model"] = "llama-3.3-70b-versatile"
                    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                    async with session.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data["choices"][0]["message"]["content"]
                except Exception:
                    pass

            # Try OpenRouter
            if openrouter_key:
                try:
                    payload["model"] = "google/gemma-4-26b-a4b-it:free"
                    headers = {"Authorization": f"Bearer {openrouter_key}", "Content-Type": "application/json"}
                    async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data["choices"][0]["message"]["content"]
                except Exception:
                    pass

        return (
            "VERDICT: GUILTY\n"
            "ANALYSIS: Having examined the chat logs, the Defendant's behavior exhibits overwhelming symptoms of capping. "
            "The community jury confirms what the evidence clearly demonstrates.\n"
            "SENTENCE: The accused is sentenced to wear the Certified Clown mantle and perform a formal apology."
        )

    # ─────────────────────────────────────────────────────────
    # BACKGROUND TASK: PENALTY ROLE EXPIRATIONS
    # ─────────────────────────────────────────────────────────

    @tasks.loop(seconds=60)
    async def check_penalty_expirations(self):
        """Scans database for expired court penalties and cleanly removes the role."""
        if not hasattr(db, "court_cases") or not isinstance(db.court_cases, dict):
            return
        now = time.time()
        modified = False

        for case_id, case_data in list(db.court_cases.items()):
            if not isinstance(case_data, dict):
                continue
            expires_at = case_data.get("penalty_expires_at", 0)
            role_id = case_data.get("penalty_role_id")
            if expires_at and expires_at <= now and not case_data.get("role_expired"):
                gid = case_data.get("guild_id")
                uid = case_data.get("defendant_id")
                if gid and uid and role_id:
                    guild = self.bot.get_guild(int(gid))
                    if guild:
                        member = guild.get_member(int(uid))
                        role = guild.get_role(int(role_id))
                        if member and role and role in member.roles:
                            try:
                                await member.remove_roles(role, reason=f"Court of Friday sentence expired ({case_id})")
                                print(f"[Court] Expired penalty role {role.name} removed from {member.display_name}")
                            except Exception as e:
                                print(f"[Court] Error removing expired role: {e}")
                case_data["role_expired"] = True
                modified = True

        if modified:
            try:
                db.save_data()
            except Exception:
                pass

    @check_penalty_expirations.before_loop
    async def before_check_expirations(self):
        await self.bot.wait_until_ready()

    # ─────────────────────────────────────────────────────────
    # SLASH COMMANDS
    # ─────────────────────────────────────────────────────────

    court_group = app_commands.Group(name="court", description="The Court of Friday: AI Vibe Tribunal and Lawsuits")

    @court_group.command(name="sue", description="Sue a server member in the Court of Friday for friendly disputes or capping.")
    @app_commands.describe(
        defendant="The member you are taking to court",
        charges="The specific accusations, broken bets, or gaming claims",
        statement="Optional detailed evidence or context"
    )
    async def sue(
        self,
        interaction: discord.Interaction,
        defendant: discord.Member,
        charges: str,
        statement: Optional[str] = None
    ):
        gid = str(interaction.guild_id)
        cfg = get_court_config(gid)

        if not cfg.get("enabled", True):
            await interaction.response.send_message("⚖️ The Court of Friday is currently closed by the server administration.", ephemeral=True)
            return

        if defendant.bot:
            await interaction.response.send_message("🤖 Chief Justice Friday refuses to litigate artificial intelligence. Sue a human mortal instead!", ephemeral=True)
            return

        if defendant.id == interaction.user.id:
            await interaction.response.send_message("⚖️ You cannot sue yourself in the Court of Friday! Self-reflection is completely free.", ephemeral=True)
            return

        court_channel_id = cfg.get("court_channel")
        if court_channel_id and int(court_channel_id) != interaction.channel_id:
            ch = interaction.guild.get_channel(int(court_channel_id))
            if ch:
                await interaction.response.send_message(
                    f"⚖️ Court sessions are restricted to the official courtroom: {ch.mention}. Please file your lawsuit there!",
                    ephemeral=True
                )
                return

        if self.is_trial_active(gid):
            await interaction.response.send_message(
                "⚖️ Another trial is currently in session in this server! Chief Justice Friday demands decorum—please wait for the current docket to conclude.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        trial = TrialRunner(
            cog=self,
            interaction=interaction,
            defendant=defendant,
            charges=charges,
            initial_statement=statement
        )
        self.set_active_trial(gid, trial.case_id)
        await trial.start()

    @court_group.command(name="docket", description="View the case history and verdict for a specific case.")
    @app_commands.describe(case_id="The docket case ID (e.g. CASE-1234)")
    async def docket(self, interaction: discord.Interaction, case_id: str):
        cid = case_id.strip().upper()
        if not hasattr(db, "court_cases") or not isinstance(db.court_cases, dict) or cid not in db.court_cases:
            await interaction.response.send_message(f"❌ Case `{cid}` was not found in the Court archives.", ephemeral=True)
            return

        c = db.court_cases[cid]
        p_name = c.get("plaintiff_name", "Unknown")
        d_name = c.get("defendant_name", "Unknown")
        charges = c.get("charges", "None")
        verdict = c.get("verdict", "PENDING")
        rationale = c.get("rationale", "No analysis recorded.")
        sentence = c.get("sentence", "No sentence recorded.")
        created_str = datetime.fromtimestamp(c.get("created_at", time.time()), tz=timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

        embed = discord.Embed(
            title=f"📜 OFFICIAL COURT DOCKET: {cid}",
            description=(
                f"**Date Filed:** {created_str}\n"
                f"**Plaintiff:** @{p_name}\n"
                f"**Defendant:** @{d_name}\n"
                f"**Verdict:** **{verdict}**\n\n"
                f"**Charges:**\n> *\"{charges}\"*\n\n"
                f"**Judicial Rationale:**\n{rationale[:800]}\n\n"
                f"**Sentence / Order:**\n{sentence}"
            ),
            color=0x3B82F6
        )
        embed.set_footer(text=f"Court of Friday Archive • {cid}")
        await interaction.response.send_message(embed=embed)

    @court_group.command(name="records", description="Check the court litigation record and conviction stats of a member.")
    @app_commands.describe(user="The member whose court record to view (defaults to yourself)")
    async def records(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        gid = str(interaction.guild_id)
        rec = get_user_court_record(gid, str(target.id))

        sued_others = rec.get("sued_others", 0)
        been_sued = rec.get("been_sued", 0)
        convictions = rec.get("convictions", 0)
        acquittals = rec.get("acquittals", 0)
        won_as_plaintiff = rec.get("won_as_plaintiff", 0)
        total_trials = rec.get("total_trials", 0)

        # Title calculation based on win rate & convictions
        if convictions >= 4:
            rank_title = "🤡 Habitual Capper (Known Offender)"
            color = 0xEF4444
        elif won_as_plaintiff >= 3 and convictions == 0:
            rank_title = "⚖️ Supreme Litigator (Undefeated)"
            color = 0x10B981
        elif acquittals >= 2 and convictions == 0:
            rank_title = "🛡️ Lawful Saint (Unblemished Record)"
            color = 0x3B82F6
        else:
            rank_title = "🏛️ Regular Citizen"
            color = 0x6B7280

        embed = discord.Embed(
            title=f"⚖️ COURT RECORD: {target.display_name}",
            description=(
                f"**Judicial Title:** {rank_title}\n\n"
                f"• **Lawsuits Filed:** `{sued_others}` (Won: `{won_as_plaintiff}`)\n"
                f"• **Times Sued:** `{been_sued}`\n"
                f"• **Guilty Convictions:** `{convictions}` 🔴\n"
                f"• **Acquittals / Exonerations:** `{acquittals}` 🟢\n"
                f"• **Total Court Appearances:** `{total_trials}`"
            ),
            color=color
        )
        if target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text="Court of Friday Registry • Records are permanent and immutable")
        await interaction.response.send_message(embed=embed)

    @court_group.command(name="leaderboard", description="View the server's top litigators and most convicted cappers.")
    async def leaderboard(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        if not hasattr(db, "court_records") or not isinstance(db.court_records, dict):
            db.court_records = {}
        g_recs = db.court_records.get(gid, {})

        if not g_recs:
            await interaction.response.send_message("⚖️ No court records or trials have been conducted in this server yet!", ephemeral=True)
            return

        # Top Cappers (Most convictions)
        convicted_sorted = sorted(g_recs.items(), key=lambda x: x[1].get("convictions", 0), reverse=True)[:5]
        # Top Litigators (Most wins as plaintiff)
        litigators_sorted = sorted(g_recs.items(), key=lambda x: x[1].get("won_as_plaintiff", 0), reverse=True)[:5]

        capper_lines = []
        for idx, (uid, data) in enumerate(convicted_sorted, 1):
            cnt = data.get("convictions", 0)
            if cnt > 0:
                name = data.get("name", f"User {uid}")
                capper_lines.append(f"`#{idx}` **{name}** — `{cnt}` Convictions 🔴")

        litigator_lines = []
        for idx, (uid, data) in enumerate(litigators_sorted, 1):
            wins = data.get("won_as_plaintiff", 0)
            if wins > 0:
                name = data.get("name", f"User {uid}")
                litigator_lines.append(f"`#{idx}` **{name}** — `{wins}` Wins ⚖️")

        cappers_text = "\n".join(capper_lines) if capper_lines else "*No convicted cappers yet!*"
        litigators_text = "\n".join(litigator_lines) if litigator_lines else "*No victorious plaintiffs yet!*"

        embed = discord.Embed(
            title="🏆 COURT OF FRIDAY: HALL OF JUSTICE & CLOWNS",
            description=(
                f"### 🤡 Most Convicted Cappers\n{cappers_text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"### ⚖️ Top Litigators & Plaintiffs\n{litigators_text}"
            ),
            color=0xF59E0B
        )
        embed.set_footer(text="Court of Friday Leaderboard • Updated Live")
        await interaction.response.send_message(embed=embed)

    @court_group.command(name="pardon", description="Pardon a convicted member and remove any active penalty role (Staff/Admin only).")
    @app_commands.describe(user="The member to pardon")
    @app_commands.default_permissions(administrator=True)
    async def pardon(self, interaction: discord.Interaction, user: discord.Member):
        gid = str(interaction.guild_id)
        cfg = get_court_config(gid)
        guilty_role_id = cfg.get("guilty_role")

        removed = False
        if guilty_role_id:
            role = interaction.guild.get_role(int(guilty_role_id))
            if role and role in user.roles:
                try:
                    await user.remove_roles(role, reason=f"Pardoned by {interaction.user.display_name}")
                    removed = True
                except Exception as e:
                    print(f"[Court] Pardon role removal error: {e}")

        # Update any pending cases for this user to expired
        if hasattr(db, "court_cases") and isinstance(db.court_cases, dict):
            for c in db.court_cases.values():
                if isinstance(c, dict) and c.get("guild_id") == gid and c.get("defendant_id") == str(user.id):
                    c["penalty_expires_at"] = 0
                    c["role_expired"] = True
            try:
                db.save_data()
            except Exception:
                pass

        embed = discord.Embed(
            title="🕊️ EXECUTIVE PARDON ISSUED",
            description=(
                f"**Member Pardoned:** {user.mention}\n"
                f"**Issued By:** {interaction.user.mention}\n\n"
                f"Chief Justice Friday acknowledges this act of executive clemency. "
                f"Any active court penalty roles have been rescinded."
            ),
            color=0x10B981
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Court(bot))
