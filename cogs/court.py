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
        "total_trials": 0,
        "settlements": 0,
        "bailed_friends": 0
    })


# ─────────────────────────────────────────────────────────────
# MODALS: STATEMENTS, SETTLEMENT, AND CONTEXT SUE
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


class SettlementModal(discord.ui.Modal):
    def __init__(self, trial_runner, defendant: discord.Member):
        super().__init__(title="🤝 Propose Out-of-Court Settlement")
        self.trial_runner = trial_runner
        self.defendant = defendant

        self.terms = discord.ui.TextInput(
            label="Settlement Terms / Formal Apology",
            style=discord.TextStyle.paragraph,
            placeholder="E.g., Bhai galti ho gayi, treat dunga / I apologize sincerely and return the stolen items...",
            required=True,
            max_length=500
        )
        self.add_item(self.terms)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        terms = str(self.terms.value).strip()
        await self.trial_runner.propose_settlement(interaction, terms)


class ContextSueModal(discord.ui.Modal):
    def __init__(self, cog, target_message: discord.Message):
        super().__init__(title="⚖️ Sue for this Message")
        self.cog = cog
        self.target_message = target_message
        self.defendant = target_message.author

        self.charges = discord.ui.TextInput(
            label="Specific Charges / Allegations",
            style=discord.TextStyle.paragraph,
            placeholder=f"Accuse @{self.defendant.display_name} for this message...",
            required=True,
            max_length=500
        )
        self.statement = discord.ui.TextInput(
            label="Additional Context / Evidence",
            style=discord.TextStyle.paragraph,
            placeholder="Explain why this message is capping, a broken promise, or illegal...",
            required=False,
            max_length=500
        )
        self.add_item(self.charges)
        self.add_item(self.statement)

    async def on_submit(self, interaction: discord.Interaction):
        # Immediate deferral
        await interaction.response.defer(ephemeral=False)
        gid = str(interaction.guild_id)

        charges_val = str(self.charges.value).strip()
        statement_val = str(self.statement.value).strip() if self.statement.value else ""

        try:
            trial = TrialRunner(
                cog=self.cog,
                interaction=interaction,
                defendant=self.defendant,
                charges=charges_val,
                initial_statement=statement_val,
                exhibit_msg=self.target_message
            )
            self.cog.set_active_trial(gid, trial.case_id)
            await trial.start()
        except Exception as e:
            self.cog.clear_active_trial(gid)
            print(f"[Court] Context menu trial launch error: {e}", flush=True)
            try:
                await interaction.followup.send(f"⚠️ Failed to convene Court: {e}", ephemeral=True)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────
# VIEWS: SUMMONS, SETTLEMENT DECISION, JURY, AND VERDICT/BAIL
# ─────────────────────────────────────────────────────────────

class CourtSummonsView(discord.ui.View):
    def __init__(self, trial_runner, defendant: discord.Member, plaintiff: discord.Member, timeout: int = 90):
        super().__init__(timeout=timeout)
        self.trial_runner = trial_runner
        self.defendant = defendant
        self.plaintiff = plaintiff

    @discord.ui.button(label="Plead Not Guilty", style=discord.ButtonStyle.primary, emoji="⚖️", row=0)
    async def not_guilty_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.defendant.id:
            await interaction.response.send_message("❌ Only the summoned Defendant can enter a plea for this case.", ephemeral=True)
            return
        modal = DefendantStatementModal(self.trial_runner, self.defendant)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Plead Guilty", style=discord.ButtonStyle.danger, emoji="🏳️", row=0)
    async def guilty_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.defendant.id:
            await interaction.response.send_message("❌ Only the summoned Defendant can enter a plea for this case.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.trial_runner.receive_plea(interaction, plea="guilty", statement="The Defendant formally pleaded GUILTY and threw themselves upon the mercy of the Court.")

    @discord.ui.button(label="Plaintiff Notes", style=discord.ButtonStyle.secondary, emoji="📜", row=0)
    async def evidence_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.plaintiff.id:
            await interaction.response.send_message("❌ Only the Plaintiff can submit additional plaintiff notes.", ephemeral=True)
            return
        modal = PlaintiffEvidenceModal(self.trial_runner, self.plaintiff)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Offer Settlement", style=discord.ButtonStyle.secondary, emoji="🤝", row=1)
    async def settlement_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.defendant.id:
            await interaction.response.send_message("❌ Only the summoned Defendant can propose an out-of-court settlement.", ephemeral=True)
            return
        modal = SettlementModal(self.trial_runner, self.defendant)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Call Saul Goodman", style=discord.ButtonStyle.secondary, emoji="📞", row=1)
    async def public_defender_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.defendant.id:
            await interaction.response.send_message("❌ Only the Defendant can invoke their right to an AI Public Defender!", ephemeral=True)
            return
        await interaction.response.defer()
        await self.trial_runner.summon_public_defender(interaction)

    async def on_timeout(self):
        await self.trial_runner.handle_summons_timeout()


class SettlementDecisionView(discord.ui.View):
    def __init__(self, trial_runner, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.trial_runner = trial_runner
        self.message: Optional[discord.Message] = None

    @discord.ui.button(label="Accept Settlement", style=discord.ButtonStyle.success, emoji="✅")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.trial_runner.plaintiff.id:
            await interaction.response.send_message("❌ Only the Plaintiff can accept or reject this settlement offer.", ephemeral=True)
            return
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
            elif interaction.message:
                await interaction.message.edit(view=self)
        except Exception:
            pass
        await self.trial_runner.resolve_settlement(accepted=True)

    @discord.ui.button(label="Reject & Demand Trial", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.trial_runner.plaintiff.id:
            await interaction.response.send_message("❌ Only the Plaintiff can accept or reject this settlement offer.", ephemeral=True)
            return
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
            elif interaction.message:
                await interaction.message.edit(view=self)
        except Exception:
            pass
        await self.trial_runner.resolve_settlement(accepted=False)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass
        if not self.trial_runner.resolved:
            await self.trial_runner.channel.send("⏱️ **Settlement Offer Expired:** The Plaintiff did not accept within 60 seconds. The Court resumes trial proceedings!")
            await self.trial_runner.proceed_to_trial()


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


class CourtVerdictView(discord.ui.View):
    def __init__(self, cog, case_id: str, defendant_id: int, guilty_role_id: Optional[int] = None):
        super().__init__(timeout=3600)  # Active for 1 hour while penalty is live
        self.cog = cog
        self.case_id = case_id
        self.defendant_id = defendant_id
        self.guilty_role_id = guilty_role_id

    @discord.ui.button(label="Post Bail", style=discord.ButtonStyle.success, emoji="💸")
    async def bail_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.process_bail(
            interaction=interaction,
            case_id=self.case_id,
            defendant_id=self.defendant_id,
            guilty_role_id=self.guilty_role_id
        )


# ─────────────────────────────────────────────────────────────
# TRIAL RUNNER CONTROLLER
# ─────────────────────────────────────────────────────────────

class TrialRunner:
    """Manages the full lifecycle of a single courtroom trial."""
    def __init__(
        self,
        cog,
        interaction: discord.Interaction,
        defendant: discord.Member,
        charges: str,
        initial_statement: Optional[str] = None,
        exhibit_msg: Optional[discord.Message] = None
    ):
        self.cog = cog
        self.bot = cog.bot
        self.interaction = interaction
        self.guild = interaction.guild
        self.channel = interaction.channel or (interaction.guild.get_channel(interaction.channel_id) if interaction.guild else None)
        self.plaintiff = interaction.user
        self.defendant = defendant
        self.charges = charges
        self.plaintiff_statement = initial_statement or ""
        self.defendant_statement = ""
        self.exhibit_msg = exhibit_msg
        self.settlement_terms = ""
        self.plea = None
        self.case_id = generate_case_id()
        self.cfg = get_court_config(str(self.guild.id) if self.guild else "")
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

        exhibit_text = ""
        if self.exhibit_msg:
            snip = self.exhibit_msg.clean_content[:150] if self.exhibit_msg.clean_content else "[Media Attachment]"
            exhibit_text = f"\n📌 **Exhibit A (Flagged Message):**\n> *\"{snip}\"*\n"

        embed = discord.Embed(
            title=f"{gavel_e} THE COURT OF FRIDAY: OFFICIAL WRIT OF SUMMONS",
            description=(
                f"**Docket Case ID:** `{self.case_id}`\n"
                f"**Presiding Magistrate:** Chief Justice Friday\n"
                f"**Plaintiff:** {self.plaintiff.mention}\n"
                f"**Accused Defendant:** {self.defendant.mention}\n\n"
                f"**Official Charge(s):**\n"
                f"```fix\n{self.charges}\n```{exhibit_text}\n"
                f"⚖️ {self.defendant.mention}, you stand accused before the High Vibe Tribunal!\n"
                f"You have **{timeout_sec} seconds** to enter your plea, propose a settlement, or summon counsel.\n\n"
                f"*Failure to respond will result in an immediate Default Judgment for Contempt of Court!*"
            ),
            color=0xF59E0B
        )
        if self.defendant.display_avatar:
            embed.set_thumbnail(url=self.defendant.display_avatar.url)
        embed.set_footer(text=f"Court of Friday • Docket {self.case_id} • Fair Trial Guaranteed")
        embed.timestamp = discord.utils.utcnow()

        self.summons_view = CourtSummonsView(self, self.defendant, self.plaintiff, timeout=timeout_sec)
        content_text = f"🔔 **COURT CONVENED!** {self.defendant.mention}, you have been sued by {self.plaintiff.mention}!"

        # Send response through interaction followup so Discord NEVER times out
        try:
            if self.interaction and self.interaction.response.is_done():
                self.summons_message = await self.interaction.followup.send(
                    content=content_text,
                    embed=embed,
                    view=self.summons_view,
                    wait=True
                )
            elif self.interaction and not self.interaction.response.is_done():
                await self.interaction.response.send_message(
                    content=content_text,
                    embed=embed,
                    view=self.summons_view
                )
                self.summons_message = await self.interaction.original_response()
            elif self.channel:
                self.summons_message = await self.channel.send(
                    content=content_text,
                    embed=embed,
                    view=self.summons_view
                )
        except Exception as e:
            print(f"[Court] Error sending summons message: {e}", flush=True)
            if self.channel:
                try:
                    self.summons_message = await self.channel.send(
                        content=content_text,
                        embed=embed,
                        view=self.summons_view
                    )
                except Exception as ex:
                    print(f"[Court] Channel fallback failed: {ex}", flush=True)

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
                await interaction.followup.send("🏳️ **Guilty Plea Entered:** The accused has admitted to the charges. The Court proceeds directly to judicial deliberation and sentencing!", ephemeral=True)
            except Exception:
                pass
            await self.deliberate_and_sentence(jury_votes={"guilty": 1, "innocent": 0})
        else:
            try:
                await interaction.followup.send("⚖️ **Not Guilty Plea Logged:** Trial commences! Evidence is being subpoenaed and the Server Jury is being empaneled.", ephemeral=True)
            except Exception:
                pass
            await self.proceed_to_trial()

    async def summon_public_defender(self, interaction: discord.Interaction):
        if self.resolved:
            return

        # Disable summons view buttons
        if self.summons_view:
            for item in self.summons_view.children:
                item.disabled = True
            if self.summons_message:
                try:
                    await self.summons_message.edit(view=self.summons_view)
                except Exception:
                    pass

        status_msg = await self.channel.send("📞 **DIALING 1-800-SAUL-GOODMAN...** Calling Public Defender Co-Counsel...")

        brief = await self.cog.generate_defense_counsel_brief(
            case_id=self.case_id,
            plaintiff=self.plaintiff,
            defendant=self.defendant,
            charges=self.charges
        )

        embed = discord.Embed(
            title="📞 LEGAL CO-COUNSEL ENTERED: SAUL GOODMAN, ESQ.",
            description=(
                f"**Docket ID:** `{self.case_id}`\n"
                f"**Client:** {self.defendant.mention}\n"
                f"**Chief Justice Friday Presiding**\n\n"
                f"⚖️ **Formal Defense Brief:**\n{brief}\n\n"
                f"🏛️ *Chief Justice Friday has accepted this legal defense into the official record. Case proceeds to trial!*"
            ),
            color=0xF59E0B
        )
        embed.set_footer(text="Court of Friday • Saul Goodman Defense Network • 'Better Call Saul!'")
        await status_msg.edit(content=None, embed=embed)

        self.defendant_statement = f"⚖️ [Co-Counsel Saul Goodman]: {brief}"
        self.plea = "not_guilty"
        await self.proceed_to_trial()

    async def propose_settlement(self, interaction: discord.Interaction, terms: str):
        self.settlement_terms = terms
        embed = discord.Embed(
            title="🤝 OUT-OF-COURT SETTLEMENT OFFER FILED",
            description=(
                f"**Docket ID:** `{self.case_id}`\n"
                f"**Accused Defendant:** {self.defendant.mention}\n"
                f"**Plaintiff:** {self.plaintiff.mention}\n\n"
                f"🕊️ **Proposed Settlement Terms / Apology:**\n"
                f"```fix\n{terms}\n```\n"
                f"{self.plaintiff.mention}, the Defendant has offered this settlement to avoid a full trial and criminal record.\n"
                f"Do you accept these terms to dismiss the case peacefully, or do you reject and demand full judicial sentencing?"
            ),
            color=0x10B981
        )
        embed.set_footer(text="Plaintiff has 60 seconds to decide.")
        view = SettlementDecisionView(self, timeout=60)
        settlement_msg = await self.channel.send(content=f"🔔 {self.plaintiff.mention}, settlement offer received!", embed=embed, view=view)
        view.message = settlement_msg

    async def resolve_settlement(self, accepted: bool):
        if self.resolved:
            return

        if accepted:
            self.resolved = True
            self.cog.clear_active_trial(str(self.guild.id))

            embed = discord.Embed(
                title="🕊️ LAWSUIT SETTLED OUT OF COURT: CASE CLOSED",
                description=(
                    f"**Docket ID:** `{self.case_id}`\n"
                    f"**Plaintiff:** {self.plaintiff.mention}\n"
                    f"**Defendant:** {self.defendant.mention}\n\n"
                    f"🤝 Both parties have reached an amicable agreement!\n"
                    f"**Agreed Terms:** *\"{self.settlement_terms}\"*\n\n"
                    f"Chief Justice Friday hereby approves the compromise decree. "
                    f"All charges are formally withdrawn with prejudice. No penalty roles assigned!"
                ),
                color=0x10B981
            )
            embed.set_footer(text="Court of Friday • Case Closed via Peace Treaty")
            embed.timestamp = discord.utils.utcnow()
            await self.channel.send(embed=embed)

            # Record in DB
            gid = str(self.guild.id)
            if not hasattr(db, "court_cases") or not isinstance(db.court_cases, dict):
                db.court_cases = {}
            db.court_cases[self.case_id] = {
                "id": self.case_id,
                "guild_id": gid,
                "channel_id": str(self.channel.id),
                "plaintiff_id": str(self.plaintiff.id),
                "plaintiff_name": self.plaintiff.display_name,
                "defendant_id": str(self.defendant.id),
                "defendant_name": self.defendant.display_name,
                "charges": self.charges,
                "plea": "settlement_accepted",
                "verdict": "SETTLED (OUT-OF-COURT)",
                "rationale": f"Case amicably settled out of court. Terms: {self.settlement_terms}",
                "sentence": "No penalty. Mutual peace treaty signed.",
                "created_at": time.time(),
                "status": "settled"
            }
            p_rec = get_user_court_record(gid, str(self.plaintiff.id))
            d_rec = get_user_court_record(gid, str(self.defendant.id))
            p_rec["total_trials"] = p_rec.get("total_trials", 0) + 1
            d_rec["total_trials"] = d_rec.get("total_trials", 0) + 1
            p_rec["settlements"] = p_rec.get("settlements", 0) + 1
            d_rec["settlements"] = d_rec.get("settlements", 0) + 1
            try:
                db.save_data()
            except Exception:
                pass
        else:
            await self.channel.send(f"⚔️ **SETTLEMENT REJECTED!** {self.plaintiff.mention} demands full trial and accountability! Chief Justice Friday convenes the jury!")
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

        verdict_view = CourtVerdictView(self.cog, self.case_id, self.defendant.id, self.cfg.get("guilty_role"))
        await self.channel.send(embed=embed, view=verdict_view)
        await self._apply_penalties(verdict="GUILTY", rationale="Defendant fled the jurisdiction and refused to enter a plea.")
        self._record_case(verdict="GUILTY", rationale="Default judgment entered for contempt of court.", sentence="Fined and reprimanded for dodging summons.")

    async def proceed_to_trial(self):
        # Deep evidence scanner (scans up to 250 messages back)
        evidence_limit = int(self.cfg.get("evidence_limit", 15))
        self.chat_evidence = await self.cog.fetch_filtered_evidence(
            channel=self.channel,
            plaintiff_id=self.plaintiff.id,
            defendant_id=self.defendant.id,
            charges=self.charges,
            exhibit_msg=self.exhibit_msg,
            limit=evidence_limit
        )

        evidence_summary_lines = []
        if self.chat_evidence:
            for item in self.chat_evidence:
                auth = f"@{item['author_name']}"
                snippet = item['content'][:140]
                evidence_summary_lines.append(f"`[{item['timestamp']}]` **{auth}:** {snippet}")
        else:
            evidence_summary_lines.append("*No recent direct dispute dialogue between the parties was found in channel history.*")

        evidence_text = "\n".join(evidence_summary_lines)

        docket_embed = discord.Embed(
            title=f"📜 DOCKET {self.case_id}: EVIDENCE & STATEMENTS",
            description=(
                f"**Plaintiff's Allegations:**\n> *\"{self.charges}\"*\n"
                f"{f'**Plaintiff Statement:** {self.plaintiff_statement}' if self.plaintiff_statement else ''}\n\n"
                f"**Defendant's Defense:**\n> *\"{self.defendant_statement}\"*\n\n"
                f"**Subpoenaed Chat Evidence (Deep Scanned Dispute Dialogue, {len(self.chat_evidence)} Messages):**\n"
                f"{evidence_text}\n\n"
                f"🏛️ **THE FLOOR IS NOW OPEN TO THE SERVER JURY!**\n"
                f"Members of the server, cast your vote below! Does the defendant walk free, or are they guilty as charged?"
            ),
            color=0x3B82F6
        )
        docket_embed.set_footer(text="The Server Jury has 45 seconds to cast their ballots.")
        await self.channel.send(embed=docket_embed)

        # Open Server Jury Poll
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
        is_guilty = ("GUILTY" in verdict and "NOT" not in verdict)
        if is_guilty:
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

        verdict_view = None
        if is_guilty:
            verdict_view = CourtVerdictView(self.cog, self.case_id, self.defendant.id, self.cfg.get("guilty_role"))

        if verdict_view:
            await self.channel.send(embed=verdict_embed, view=verdict_view)
        else:
            await self.channel.send(embed=verdict_embed)

        # Apply roles and record history
        await self._apply_penalties(verdict=verdict_clean, rationale=analysis)
        self._record_case(verdict=verdict_clean, rationale=analysis, sentence=sentence, jury_votes=jury_votes)

    async def _apply_penalties(self, verdict: str, rationale: str):
        guilty_role_id = self.cfg.get("guilty_role")
        innocent_role_id = self.cfg.get("innocent_role")
        role_duration_mins = int(self.cfg.get("role_duration", 60))

        if "GUILTY" in verdict and "NOT" not in verdict:
            if guilty_role_id:
                try:
                    role = self.guild.get_role(int(guilty_role_id))
                    if role and role not in self.defendant.roles:
                        await self.defendant.add_roles(role, reason=f"Court of Friday Conviction ({self.case_id})")
                        await self.channel.send(f"🚨 **Penalty Enforced:** {self.defendant.mention} has been sentenced with the **{role.name}** role for {role_duration_mins} minutes!\n*(Friends can use `/court bail` or click **Post Bail** to rescue them!)*")
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

COURT_HINGLISH_INDICATORS = re.compile(
    r'\b(kya|kaise|kaisi|kaha|kyun|kyu|bolo|bol|dekh|dekho|kar|karo|kardo|karna|hatao|chahiye|hai|hain|hu|hoon|mujhe|tum|tumhe|aap|aapka|meri|mera|mere|nahi|nahin|achha|badhiya|baat|sun|suno|bhai|yaar|chori|churaya|mara|maar|ladai|paise|kuch|tera|teri|sab|bhi|toh|to|mat|chal|chalo|mein|me|se|ko|ne|aur|par|pe|baut|bohot|boht|zyada|sath|khaya|khao|liya|diya|de|pata|thief|kurkure|kutti|kutta|chirkut|nalla|bakwaas|faltu)\b',
    re.IGNORECASE
)

def is_hinglish_dispute(text: str) -> bool:
    if not text:
        return False
    return len(COURT_HINGLISH_INDICATORS.findall(text)) >= 1


class Court(commands.Cog):
    """The Court of Friday: AI-powered interactive community tribunal."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_trials: Dict[str, str] = {}  # guild_id -> case_id

        # Register Context Menu for Message Apps: "⚖️ Sue for this Message"
        self.ctx_menu_sue = app_commands.ContextMenu(
            name="⚖️ Sue for this Message",
            callback=self.context_sue_callback
        )
        self.bot.tree.add_command(self.ctx_menu_sue)

        self.check_penalty_expirations.start()

    def cog_unload(self):
        self.check_penalty_expirations.cancel()
        try:
            self.bot.tree.remove_command(self.ctx_menu_sue.name, type=self.ctx_menu_sue.type)
        except Exception:
            pass

    def set_active_trial(self, guild_id: str, case_id: str):
        self._active_trials[guild_id] = case_id

    def clear_active_trial(self, guild_id: str):
        self._active_trials.pop(guild_id, None)

    def is_trial_active(self, guild_id: str) -> bool:
        return guild_id in self._active_trials

    # ─────────────────────────────────────────────────────────
    # CONTEXT MENU HANDLER: "⚖️ Sue for this Message"
    # ─────────────────────────────────────────────────────────

    async def context_sue_callback(self, interaction: discord.Interaction, message: discord.Message):
        if not interaction.guild:
            await interaction.response.send_message("🔒 Court commands can only be executed inside a server.", ephemeral=True)
            return

        gid = str(interaction.guild_id)
        cfg = get_court_config(gid)

        if not cfg.get("enabled", True):
            await interaction.response.send_message("⚖️ The Court of Friday is currently closed by the server administration.", ephemeral=True)
            return

        if getattr(message.author, "bot", False):
            await interaction.response.send_message("🤖 Chief Justice Friday refuses to litigate artificial intelligence. Sue a human mortal instead!", ephemeral=True)
            return

        if message.author.id == interaction.user.id:
            await interaction.response.send_message("⚖️ You cannot sue yourself in the Court of Friday! Self-reflection is completely free.", ephemeral=True)
            return

        court_channel_id = cfg.get("court_channel")
        if court_channel_id:
            try:
                cid_int = int(str(court_channel_id).strip())
                if cid_int and cid_int != interaction.channel_id:
                    ch = interaction.guild.get_channel(cid_int)
                    if ch:
                        await interaction.response.send_message(f"⚖️ Court sessions are restricted to {ch.mention}. Please file your lawsuit there!", ephemeral=True)
                        return
            except (ValueError, TypeError):
                pass

        if self.is_trial_active(gid):
            await interaction.response.send_message("⚖️ Another trial is currently in session in this server! Chief Justice Friday demands decorum—please wait for the current docket to conclude.", ephemeral=True)
            return

        modal = ContextSueModal(self, message)
        await interaction.response.send_modal(modal)

    # ─────────────────────────────────────────────────────────
    # SMART DEEP EVIDENCE SCANNER
    # ─────────────────────────────────────────────────────────

    async def fetch_filtered_evidence(
        self,
        channel: discord.TextChannel,
        plaintiff_id: int,
        defendant_id: int,
        charges: str = "",
        exhibit_msg: Optional[discord.Message] = None,
        limit: int = 15
    ) -> List[dict]:
        """
        Deep scans recent channel history (up to 250 messages back), accurately isolating
        the dispute dialogue between plaintiff and defendant even in high-volume (1000+ member) channels.
        Leverages Exhibit A, Discord reply references (m.reference), user mentions, and charge keywords.
        """
        evidence = []
        if not channel or not hasattr(channel, "history"):
            return evidence

        # Extract charge keywords for dispute relevance (ignore common stopwords)
        stopwords = {
            'the', 'and', 'for', 'this', 'that', 'with', 'from', 'your', 'have', 'has', 'had',
            'sue', 'court', 'case', 'why', 'what', 'when', 'where', 'are', 'was', 'were', 'not',
            'you', 'his', 'her', 'their', 'our', 'will', 'did', 'does', 'but', 'all', 'any', 'can',
            'cant', 'cannot', 'bhai', 'hai', 'hain', 'mein', 'kya', 'ko', 'se', 'pe', 'par', 'yeh', 'woh'
        }
        raw_words = re.findall(r'\b[a-zA-Z0-9_\u0900-\u097F]{3,}\b', charges.lower())
        keywords = {w for w in raw_words if w not in stopwords}

        raw_candidates = []
        seen_ids = set()

        # If Exhibit A is pinned, include it first with highest score
        if exhibit_msg and not getattr(exhibit_msg.author, "bot", False):
            seen_ids.add(exhibit_msg.id)
            content = exhibit_msg.clean_content.strip() if exhibit_msg.clean_content else ""
            if not content and exhibit_msg.attachments:
                content = f"[Attachment: {exhibit_msg.attachments[0].filename}]"
            raw_candidates.append({
                "message_id": exhibit_msg.id,
                "author_id": exhibit_msg.author.id,
                "author_name": exhibit_msg.author.display_name,
                "content": content or "[Empty message]",
                "timestamp": exhibit_msg.created_at.strftime("%I:%M %p"),
                "score": 100,  # Top priority
                "created_at": exhibit_msg.created_at,
                "is_exhibit": True,
                "is_reply": False
            })

        # Deep scan up to 250 messages back
        try:
            async for m in channel.history(limit=250):
                if m.author.bot or m.id in seen_ids:
                    continue

                is_plaintiff = (m.author.id == plaintiff_id)
                is_defendant = (m.author.id == defendant_id)

                # Check if this message replies to the other litigant
                is_reply_to_opponent = False
                if m.reference and m.reference.resolved:
                    ref_author = getattr(m.reference.resolved, "author", None)
                    if ref_author:
                        if is_plaintiff and ref_author.id == defendant_id:
                            is_reply_to_opponent = True
                        elif is_defendant and ref_author.id == plaintiff_id:
                            is_reply_to_opponent = True

                # Check mentions
                mentions_opponent = False
                if is_plaintiff and any(u.id == defendant_id for u in m.mentions):
                    mentions_opponent = True
                elif is_defendant and any(u.id == plaintiff_id for u in m.mentions):
                    mentions_opponent = True

                # Only evaluate messages authored by the two parties
                if is_plaintiff or is_defendant:
                    score = 1
                    content = m.clean_content.strip() if m.clean_content else ""
                    if not content and m.attachments:
                        content = f"[Attachment: {m.attachments[0].filename}]"

                    content_lower = content.lower()

                    if is_reply_to_opponent:
                        score += 8
                    if mentions_opponent:
                        score += 6

                    # Charge keyword matches
                    for kw in keywords:
                        if kw in content_lower:
                            score += 4

                    raw_candidates.append({
                        "message_id": m.id,
                        "author_id": m.author.id,
                        "author_name": m.author.display_name,
                        "content": content or "[Empty message]",
                        "timestamp": m.created_at.strftime("%I:%M %p"),
                        "score": score,
                        "created_at": m.created_at,
                        "is_exhibit": False,
                        "is_reply": is_reply_to_opponent
                    })
                    seen_ids.add(m.id)
        except Exception as e:
            print(f"[Court] Error during deep evidence scan: {e}")

        if not raw_candidates:
            return []

        # Sort candidate messages: prioritize Exhibit A, replies, and keyword matches
        scored_sorted = sorted(raw_candidates, key=lambda x: (x["score"], x["created_at"]), reverse=True)
        selected = scored_sorted[:limit]

        # Order chronologically (oldest to newest)
        selected.sort(key=lambda x: x["created_at"])

        final_evidence = []
        for item in selected:
            prefix = ""
            if item.get("is_exhibit"):
                prefix = "📌 [EXHIBIT A] "
            elif item.get("is_reply"):
                prefix = "↩️ "

            final_evidence.append({
                "author_id": item["author_id"],
                "author_name": item["author_name"],
                "content": f"{prefix}{item['content']}",
                "timestamp": item["timestamp"]
            })

        return final_evidence

    # ─────────────────────────────────────────────────────────
    # SAUL GOODMAN PUBLIC DEFENDER CO-COUNSEL GENERATOR
    # ─────────────────────────────────────────────────────────

    async def generate_defense_counsel_brief(
        self,
        case_id: str,
        plaintiff: discord.Member,
        defendant: discord.Member,
        charges: str
    ) -> str:
        """Invokes Friday's LLM to generate a hilarious, fast-talking Saul Goodman defense brief."""
        is_hinglish = is_hinglish_dispute(charges)
        if is_hinglish:
            system_prompt = (
                "You are Saul Goodman (aka K.D. Pathak), a flamboyant, dramatic, fast-talking defense lawyer in the Court of Friday Discord Tribunal. "
                "You represent your client @Defendant who is sued by @Plaintiff.\n"
                "TONE: Hilarious, sassy, fast-paced Desi HINGLISH (Hindi written in English letters).\n"
                "STYLE: Cite fake Discord laws (e.g. 'Section 420 of Vibe Penal Code', 'Doctrine of Kurkure Possession'). Act 100% confident that your client did nothing wrong.\n"
                "LENGTH: 50 to 75 words maximum (1 short punchy paragraph). Bold key phrases and names."
            )
        else:
            system_prompt = (
                "You are Saul Goodman, the ultimate fast-talking, charismatic, dramatic criminal defense attorney in the Court of Friday Discord Tribunal. "
                "You represent your client @Defendant who is sued by @Plaintiff.\n"
                "TONE: Witty, hilarious, fast-paced casual English.\n"
                "STYLE: Cite ridiculous legal principles (e.g. 'The Gaming Statute of Limitations', 'Section 69 of the Discord Code of Conduct'). Bold key phrases and names.\n"
                "LENGTH: 50 to 75 words maximum (1 short punchy paragraph). Bold key phrases and names."
            )

        user_content = (
            f"Case: {case_id}\n"
            f"Plaintiff: @{plaintiff.display_name}\n"
            f"Client (Defendant): @{defendant.display_name}\n"
            f"Accusation: \"{charges}\"\n"
            f"Give your dramatic opening defense brief to Chief Justice Friday."
        )

        ai_cog = self.bot.get_cog("AIChat")
        llm_reply = None
        if ai_cog and hasattr(ai_cog, "_call_openrouter"):
            try:
                llm_reply = await ai_cog._call_openrouter(
                    messages=[{"role": "user", "content": user_content}],
                    system_prompt=system_prompt,
                    max_tokens=180
                )
            except Exception:
                pass

        if not llm_reply or len(llm_reply) < 20:
            llm_reply = await self._fallback_llm_query(system_prompt, user_content, is_hinglish=is_hinglish)

        if not llm_reply or len(llm_reply) < 20:
            if is_hinglish:
                return (
                    f"**Chief Justice Friday Sahiba!** Main **{defendant.display_name}** ka legal counsel Saul Goodman bol raha hu. "
                    f"Yeh **{plaintiff.display_name}** ka case bilkul farzi aur fabricated hai! **Section 420 of Vibe Code** ke mutabik "
                    f"mere client ne koi jurm nahi kiya. Hum immediate dismissal aur legal expenses ki maang karte hain!"
                )
            else:
                return (
                    f"**Your Honor Chief Justice Friday!** I represent **{defendant.display_name}**. "
                    f"This entire lawsuit filed by **{plaintiff.display_name}** is unconstitutional slander! "
                    f"Under the **Doctrine of Reasonable Doubt**, my client is 100% innocent. We move for an immediate dismissal with prejudice!"
                )

        return llm_reply.strip()

    # ─────────────────────────────────────────────────────────
    # CHIEF JUSTICE FRIDAY LLM VERDICT GENERATOR
    # ─────────────────────────────────────────────────────────

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

        # Detect if the dispute or chat evidence is in Hinglish
        full_context_text = f"{charges} {plaintiff_statement} {defendant_statement} {chat_transcript}"
        is_hinglish = is_hinglish_dispute(full_context_text)

        if is_hinglish:
            lang_directive = (
                "LANGUAGE & TONE: NATURAL HINGLISH (MANDATORY)\n"
                "- The complaint or chat evidence contains Hinglish. You MUST write the ENTIRE 'ANALYSIS' and 'SENTENCE' in casual, hilarious, modern HINGLISH (Desi Hindi in English/Latin letters)!\n"
                "- Speak like a sassy, witty Desi lady judge (e.g. 'Arey bhai @User...', 'Yeh toh seedha timepass hai!').\n"
                "- Use simple everyday conversational words (no complex or difficult words).\n"
                "- Highlight important words, accusations, and names in **bold** (e.g. **@User**, **Kurkure chori**, **0 votes**).\n"
                "- LENGTH: Keep it MEDIUM length! Strictly 1 to 2 short punchy paragraphs (maximum 75-90 words total). Do NOT write huge essays!"
            )
        else:
            lang_directive = (
                "LANGUAGE & TONE: SIMPLE CASUAL ENGLISH (MANDATORY)\n"
                "- Use simple, natural everyday English that anyone can easily read.\n"
                "- STRICTLY AVOID overly complex, academic, or big dictionary words (NEVER use words like 'seismograph', 'linguistically vacuous', 'diplomacy', etc.)!\n"
                "- Speak like a witty, sharp, funny judge roasting silly disputes.\n"
                "- Highlight important words, accusations, and names in **bold** (e.g. **@User**, **stolen snacks**, **0 votes**).\n"
                "- LENGTH: Keep it MEDIUM length! Strictly 1 to 2 short punchy paragraphs (maximum 75-90 words total). Do NOT write huge essays!"
            )

        system_prompt = (
            "You are Chief Justice Friday, presiding over the Court of Friday Discord Tribunal. "
            "You judge funny member beefs, gaming claims, and silly disputes.\n\n"
            f"{lang_directive}\n\n"
            "VERDICT CHOICES:\n"
            "- GUILTY: Defendant is caught red-handed or capping.\n"
            "- NOT GUILTY: Charges are baseless, defendant is innocent.\n"
            "- BOTH GUILTY: Both are acting like clowns and deserve mutual roast.\n"
            "- MISTRIAL: The lawsuit is complete nonsense, silly timepass, or frivolous.\n\n"
            "STRICT RESPONSE FORMAT:\n"
            "VERDICT: [GUILTY, NOT GUILTY, BOTH GUILTY, or MISTRIAL]\n"
            "ANALYSIS: [1 to 2 short punchy paragraphs. Simple vocabulary only, bold key phrases, strictly medium length under 90 words.]\n"
            "SENTENCE: [1 to 2 short sentences giving the funny penalty or dismissal order.]"
        )

        user_content = (
            f"CASE DOCKET: {case_id}\n"
            f"Plaintiff: @{plaintiff.display_name} (ID: {plaintiff.id})\n"
            f"Defendant: @{defendant.display_name} (ID: {defendant.id})\n"
            f"Charges Filed: \"{charges}\"\n"
            f"Defendant Formal Plea: {plea.upper() if plea else 'UNKNOWN'}\n"
            f"Plaintiff Testimony: \"{plaintiff_statement or 'No additional notes provided.'}\"\n"
            f"Defendant Defense: \"{defendant_statement or 'Defendant provided no defense.'}\"\n\n"
            f"SUBPOENAED CHAT LOG EVIDENCE (Dispute Dialogue):\n"
            f"{chat_transcript}\n\n"
            f"COMMUNITY JURY BALLOT TALLY:\n"
            f"Guilty Votes: {g_votes} | Innocent Votes: {i_votes}\n\n"
            f"Chief Justice Friday, please review the docket and pronounce your binding judgment now."
        )

        ai_cog = self.bot.get_cog("AIChat")
        llm_reply = None

        if ai_cog and hasattr(ai_cog, "_call_openrouter"):
            try:
                llm_reply = await ai_cog._call_openrouter(
                    messages=[{"role": "user", "content": user_content}],
                    system_prompt=system_prompt,
                    max_tokens=300
                )
            except Exception as e:
                print(f"[Court] AIChat call error: {e}")

        # Fallback if AIChat is unavailable
        if not llm_reply or len(llm_reply) < 25:
            llm_reply = await self._fallback_llm_query(system_prompt, user_content, is_hinglish=is_hinglish)

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

        analysis = re.sub(r'^(?:ANALYSIS|FAISLA|OPINION):\s*', '', analysis, flags=re.IGNORECASE).strip()
        sentence = re.sub(r'^(?:SENTENCE|ORDER|SAZA):\s*', '', sentence, flags=re.IGNORECASE).strip()

        return {
            "verdict": verdict,
            "analysis": analysis,
            "sentence": sentence
        }

    async def _fallback_llm_query(self, system_prompt: str, user_content: str, is_hinglish: bool = False) -> Optional[str]:
        """Direct fallback API query in case AIChat cog is not reachable."""
        groq_key = os.getenv("GROQ_API_KEY")
        openrouter_key = (os.getenv("OPENROUTER_API_KEY") or "").split(",")[0].strip()

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 300,
            "temperature": 0.7
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
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

        if is_hinglish:
            return (
                "VERDICT: MISTRIAL\n"
                "ANALYSIS: Chat aur saboot dekh kar saaf pata chal raha hai ki yeh koi serious case nahi balki **pure timepass** hai! Dono parties faltu baaton pe lad rahi hain aur **server jury** ne bhi koi bhav nahi diya.\n"
                "SENTENCE: Case dismiss kiya jata hai! Dono faltu drama band karein aur shaanti se rahein."
            )
        else:
            return (
                "VERDICT: MISTRIAL\n"
                "ANALYSIS: Looking at the chat evidence, this entire dispute is just **pure drama** over nothing! Both parties are wasting the Court's time, and the **jury** didn't even bother to vote.\n"
                "SENTENCE: Case dismissed! Stop arguing over silly things and get back to gaming."
            )

    # ─────────────────────────────────────────────────────────
    # COMMUNITY BAIL SYSTEM
    # ─────────────────────────────────────────────────────────

    async def process_bail(
        self,
        interaction: discord.Interaction,
        case_id: Optional[str],
        defendant_id: int,
        guilty_role_id: Optional[int] = None
    ):
        """Processes community bail posted by a friend."""
        if not interaction.guild:
            await interaction.response.send_message("🔒 Bail can only be posted inside a server.", ephemeral=True)
            return

        bailor = interaction.user
        gid = str(interaction.guild_id)

        if bailor.id == defendant_id:
            await interaction.response.send_message("❌ **Self-Bail Prohibited:** You cannot post your own bail! Only a loyal server friend or guildmate can rescue you from the slammer.", ephemeral=True)
            return

        member = interaction.guild.get_member(defendant_id)
        if not member:
            await interaction.response.send_message("❌ Accused member not found in this server.", ephemeral=True)
            return

        cfg = get_court_config(gid)
        r_id = guilty_role_id or cfg.get("guilty_role")
        role = interaction.guild.get_role(int(r_id)) if r_id else None

        if role and role not in member.roles:
            await interaction.response.send_message(f"⚖️ {member.display_name} is not currently serving a court penalty role!", ephemeral=True)
            return

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False)

        # Bail XP Cost check (50 XP if leveling is active)
        bail_cost = 50
        deducted = False
        if hasattr(db, "xp_data") and isinstance(db.xp_data, dict):
            guild_xp = db.xp_data.setdefault(gid, {})
            user_xp_data = guild_xp.setdefault(str(bailor.id), {"xp": 0, "level": 0})
            if user_xp_data.get("xp", 0) >= bail_cost:
                user_xp_data["xp"] -= bail_cost
                deducted = True

        # Remove the penalty role
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason=f"Court bail posted by {bailor.display_name}")
            except Exception as e:
                print(f"[Court Bail] Role removal failed: {e}")

        # Update case records in database
        if hasattr(db, "court_cases") and isinstance(db.court_cases, dict):
            if case_id and case_id in db.court_cases:
                c = db.court_cases[case_id]
                c["penalty_expires_at"] = 0
                c["role_expired"] = True
                c["bailed_by"] = str(bailor.id)
                c["bailed_by_name"] = bailor.display_name
            else:
                for c in db.court_cases.values():
                    if isinstance(c, dict) and c.get("guild_id") == gid and c.get("defendant_id") == str(defendant_id):
                        if c.get("penalty_expires_at", 0) > time.time():
                            c["penalty_expires_at"] = 0
                            c["role_expired"] = True
                            c["bailed_by"] = str(bailor.id)
                            c["bailed_by_name"] = bailor.display_name

        # Update bailor record
        b_rec = get_user_court_record(gid, str(bailor.id))
        b_rec["bailed_friends"] = b_rec.get("bailed_friends", 0) + 1

        try:
            db.save_data()
        except Exception:
            pass

        bond_desc = f"**Bail Bond Paid:** `{bail_cost} XP` deducted from {bailor.mention}." if deducted else "**Bail Bond Paid:** Pro Bono Friendship Bond (True Camaraderie! ❤️)"

        embed = discord.Embed(
            title="💸 BAIL POSTED! FREEDOM RESTORED!",
            description=(
                f"🚨 **Emergency Clemency:** {bailor.mention} has stepped forward and posted bail for {member.mention}!\n\n"
                f"{bond_desc}\n"
                f"The court penalty role **{role.name if role else 'Convicted'}** has been stripped immediately.\n\n"
                f"⚖️ Chief Justice Friday declares **{member.display_name}** a free citizen once more!"
            ),
            color=0x10B981
        )
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Court of Friday • Bail Registry • Sponsored by {bailor.display_name}")
        embed.timestamp = discord.utils.utcnow()

        await interaction.followup.send(content=f"🔔 {member.mention}, you have been bailed out!", embed=embed)

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
        statement="Optional detailed evidence or context",
        evidence_link="Optional Discord message link of the incriminating message (Exhibit A)"
    )
    async def sue(
        self,
        interaction: discord.Interaction,
        defendant: discord.Member,
        charges: str,
        statement: Optional[str] = None,
        evidence_link: Optional[str] = None
    ):
        # Immediate deferral so Discord never times out
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=False)
            except Exception as e:
                print(f"[Court] Defer notice in sue: {e}", flush=True)

        async def reply_error(msg: str):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

        if not interaction.guild:
            await reply_error("🔒 Court commands can only be executed inside a server.")
            return

        gid = str(interaction.guild_id)
        cfg = get_court_config(gid)

        if not cfg.get("enabled", True):
            await reply_error("⚖️ The Court of Friday is currently closed by the server administration.")
            return

        if getattr(defendant, "bot", False):
            await reply_error("🤖 Chief Justice Friday refuses to litigate artificial intelligence. Sue a human mortal instead!")
            return

        if defendant.id == interaction.user.id:
            await reply_error("⚖️ You cannot sue yourself in the Court of Friday! Self-reflection is completely free.")
            return

        court_channel_id = cfg.get("court_channel")
        if court_channel_id:
            try:
                cid_int = int(str(court_channel_id).strip())
                if cid_int and cid_int != interaction.channel_id:
                    ch = interaction.guild.get_channel(cid_int)
                    if ch:
                        await reply_error(f"⚖️ Court sessions are restricted to the official courtroom: {ch.mention}. Please file your lawsuit there!")
                        return
            except (ValueError, TypeError):
                pass

        if self.is_trial_active(gid):
            await reply_error("⚖️ Another trial is currently in session in this server! Chief Justice Friday demands decorum—please wait for the current docket to conclude.")
            return

        # Fetch optional Exhibit A message if evidence_link provided
        exhibit_msg = None
        if evidence_link:
            link_match = re.search(r'channels/(\d+)/(\d+)/(\d+)', evidence_link)
            if link_match:
                ch_id, msg_id = int(link_match.group(2)), int(link_match.group(3))
                target_ch = interaction.guild.get_channel(ch_id)
                if target_ch:
                    try:
                        exhibit_msg = await target_ch.fetch_message(msg_id)
                    except Exception as e:
                        print(f"[Court] Could not fetch exhibit message from link: {e}")

        try:
            trial = TrialRunner(
                cog=self,
                interaction=interaction,
                defendant=defendant,
                charges=charges,
                initial_statement=statement,
                exhibit_msg=exhibit_msg
            )
            self.set_active_trial(gid, trial.case_id)
            await trial.start()
        except Exception as e:
            self.clear_active_trial(gid)
            import traceback
            traceback.print_exc()
            await reply_error(f"⚠️ Failed to convene the Court of Friday: {e}")

    @court_group.command(name="bail", description="Post bail for a convicted friend to immediately remove their penalty role.")
    @app_commands.describe(user="The convicted friend you want to bail out")
    async def bail(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.guild:
            await interaction.response.send_message("🔒 Court commands can only be executed in a server.", ephemeral=True)
            return

        cfg = get_court_config(str(interaction.guild_id))
        if not cfg.get("enabled", True):
            await interaction.response.send_message("⚖️ The Court of Friday is currently closed.", ephemeral=True)
            return

        await self.process_bail(interaction, case_id=None, defendant_id=user.id)

    @court_group.command(name="docket", description="View the case history and verdict for a specific case.")
    @app_commands.describe(case_id="The docket case ID (e.g. CASE-1234)")
    async def docket(self, interaction: discord.Interaction, case_id: str):
        if not interaction.response.is_done():
            try:
                await interaction.response.defer()
            except Exception:
                pass

        cid = case_id.strip().upper()
        if not hasattr(db, "court_cases") or not isinstance(db.court_cases, dict) or cid not in db.court_cases:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Case `{cid}` was not found in the Court archives.", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Case `{cid}` was not found in the Court archives.", ephemeral=True)
            return

        c = db.court_cases[cid]
        p_name = c.get("plaintiff_name", "Unknown")
        d_name = c.get("defendant_name", "Unknown")
        charges = c.get("charges", "None")
        verdict = c.get("verdict", "PENDING")
        rationale = c.get("rationale", "No analysis recorded.")
        sentence = c.get("sentence", "No sentence recorded.")
        bailed = c.get("bailed_by_name")
        bail_str = f"\n**Bailed By:** @{bailed} 💸" if bailed else ""
        created_str = datetime.fromtimestamp(c.get("created_at", time.time()), tz=timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

        embed = discord.Embed(
            title=f"📜 OFFICIAL COURT DOCKET: {cid}",
            description=(
                f"**Date Filed:** {created_str}\n"
                f"**Plaintiff:** @{p_name}\n"
                f"**Defendant:** @{d_name}\n"
                f"**Verdict:** **{verdict}**{bail_str}\n\n"
                f"**Charges:**\n> *\"{charges}\"*\n\n"
                f"**Judicial Rationale:**\n{rationale[:800]}\n\n"
                f"**Sentence / Order:**\n{sentence}"
            ),
            color=0x3B82F6
        )
        embed.set_footer(text=f"Court of Friday Archive • {cid}")
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

    @court_group.command(name="records", description="Check the court litigation record and conviction stats of a member.")
    @app_commands.describe(user="The member whose court record to view (defaults to yourself)")
    async def records(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if not interaction.response.is_done():
            try:
                await interaction.response.defer()
            except Exception:
                pass

        target = user or interaction.user
        gid = str(interaction.guild_id) if interaction.guild_id else ""
        rec = get_user_court_record(gid, str(target.id))

        sued_others = rec.get("sued_others", 0)
        been_sued = rec.get("been_sued", 0)
        convictions = rec.get("convictions", 0)
        acquittals = rec.get("acquittals", 0)
        won_as_plaintiff = rec.get("won_as_plaintiff", 0)
        total_trials = rec.get("total_trials", 0)
        settlements = rec.get("settlements", 0)
        bailed_friends = rec.get("bailed_friends", 0)

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
                f"• **Settled Out-of-Court:** `{settlements}` 🤝\n"
                f"• **Friends Bailed Out:** `{bailed_friends}` 💸\n"
                f"• **Total Court Appearances:** `{total_trials}`"
            ),
            color=color
        )
        if target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text="Court of Friday Registry • Records are permanent and immutable")
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

    @court_group.command(name="leaderboard", description="View the server's top litigators and most convicted cappers.")
    async def leaderboard(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            try:
                await interaction.response.defer()
            except Exception:
                pass

        gid = str(interaction.guild_id) if interaction.guild_id else ""
        if not hasattr(db, "court_records") or not isinstance(db.court_records, dict):
            db.court_records = {}
        g_recs = db.court_records.get(gid, {})

        if not g_recs:
            msg = "⚖️ No court records or trials have been conducted in this server yet!"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        convicted_sorted = sorted(g_recs.items(), key=lambda x: x[1].get("convictions", 0), reverse=True)[:5]
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
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

    @court_group.command(name="pardon", description="Pardon a convicted member and remove any active penalty role (Staff/Admin only).")
    @app_commands.describe(user="The member to pardon")
    @app_commands.default_permissions(administrator=True)
    async def pardon(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

        if not interaction.guild:
            msg = "🔒 This command can only be executed in a server."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        gid = str(interaction.guild_id)
        cfg = get_court_config(gid)
        guilty_role_id = cfg.get("guilty_role")

        if guilty_role_id:
            try:
                role = interaction.guild.get_role(int(str(guilty_role_id).strip()))
                if role and role in user.roles:
                    await user.remove_roles(role, reason=f"Pardoned by {interaction.user.display_name}")
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
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Court(bot))
