import discord
from discord.ext import commands
from discord import app_commands
import datetime
import math
import unicodedata
from database import db
from emoji_utils import replace_plain_emojis
from font_utils import clean_display_name

class InviteTracker(commands.Cog):
    """
    Advanced Invite Tracker Module:
    - Tracks Regular, Left, Fake, and Bonus invites: Total = Regular + Bonus - Left - Fake.
    - Caches guild invites in memory and diffs on member join.
    - Anti-fake detection (accounts < 3 days old).
    - Syncs with Web Dashboard and supports custom embed announcements with visual server emojis.
    """
    def __init__(self, bot):
        self.bot = bot
        # In-memory invite cache: guild_id -> {invite_code: uses}
        self.invites_cache = {}
        self.vanity_cache = {}

    async def cog_load(self):
        # Cache invites on cog load
        await self.bot.wait_until_ready()
        await self.refresh_all_guild_invites()

    async def refresh_all_guild_invites(self):
        """Builds in-memory invite cache across all guilds the bot belongs to."""
        for guild in self.bot.guilds:
            await self.cache_guild_invites(guild)

    async def cache_guild_invites(self, guild: discord.Guild):
        """Caches invites for a single guild."""
        if not guild.me.guild_permissions.manage_guild:
            return
        try:
            invs = await guild.invites()
            self.invites_cache[guild.id] = {inv.code: inv.uses for inv in invs}
            if "VANITY_URL" in guild.features:
                try:
                    vanity = await guild.vanity_invite()
                    if vanity:
                        self.vanity_cache[guild.id] = vanity.uses
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ [InviteTracker] Failed to cache invites for '{guild.name}': {e}")

    # ────────────────────────── Event Listeners ──────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        await self.refresh_all_guild_invites()

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if not invite.guild:
            return
        gid = invite.guild.id
        if gid not in self.invites_cache:
            self.invites_cache[gid] = {}
        self.invites_cache[gid][invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if not invite.guild:
            return
        gid = invite.guild.id
        if gid in self.invites_cache and invite.code in self.invites_cache[gid]:
            self.invites_cache[gid].pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        if not guild:
            return
        gid_str = str(guild.id)
        mid_str = str(member.id)

        # Skip bots
        if member.bot:
            return

        inviter = None
        used_code = None
        is_vanity = False

        # Attempt to determine which invite was used by diffing cache
        if guild.me.guild_permissions.manage_guild:
            try:
                new_invites = await guild.invites()
                cached = self.invites_cache.get(guild.id, {})

                for inv in new_invites:
                    old_uses = cached.get(inv.code, 0)
                    if inv.uses > old_uses:
                        inviter = inv.inviter
                        used_code = inv.code
                        break

                # If not found, check vanity URL
                if not used_code and "VANITY_URL" in guild.features:
                    try:
                        vanity = await guild.vanity_invite()
                        if vanity:
                            old_vanity = self.vanity_cache.get(guild.id, 0)
                            if vanity.uses > old_vanity:
                                is_vanity = True
                                used_code = vanity.code
                                self.vanity_cache[guild.id] = vanity.uses
                    except Exception:
                        pass

                # Update in-memory cache
                self.invites_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
            except Exception as e:
                print(f"⚠️ [InviteTracker] Error checking invites on join: {e}")

        # Anti-Fake check: Account age < 3 days (259200 seconds)
        now = datetime.datetime.now(datetime.timezone.utc)
        created_at = member.created_at
        account_age_sec = (now - created_at).total_seconds()
        is_fake = account_age_sec < (3 * 86400)

        # Update database records
        if gid_str not in db.invite_counts:
            db.invite_counts[gid_str] = {}
        if gid_str not in db.invite_history:
            db.invite_history[gid_str] = {}

        inviter_id_str = str(inviter.id) if inviter else None

        if inviter and not is_vanity:
            if inviter_id_str not in db.invite_counts[gid_str]:
                db.invite_counts[gid_str][inviter_id_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

            if is_fake:
                db.invite_counts[gid_str][inviter_id_str]["fake"] += 1
            else:
                db.invite_counts[gid_str][inviter_id_str]["regular"] += 1

        # Store member history
        db.invite_history[gid_str][mid_str] = {
            "inviter_id": inviter_id_str,
            "code": used_code or ("vanity" if is_vanity else "unknown"),
            "is_fake": is_fake,
            "joined_at": now.isoformat()
        }
        db.save_data()

        # Send notification to configured invite channel
        cfg = db.invite_tracker.get(gid_str, {})
        if cfg.get("enabled", True):
            channel_id = cfg.get("log_channel")
            if channel_id:
                try:
                    ch = guild.get_channel(int(channel_id))
                    if ch:
                        await self.send_join_notification(ch, member, inviter, used_code, is_fake, is_vanity)
                except Exception as e:
                    print(f"⚠️ [InviteTracker] Failed to send join notification: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        if not guild:
            return
        gid_str = str(guild.id)
        mid_str = str(member.id)

        history = db.invite_history.get(gid_str, {}).get(mid_str)
        inviter_id = history.get("inviter_id") if history else None
        is_fake = history.get("is_fake", False) if history else False

        inviter = None
        if inviter_id and not is_fake:
            if gid_str in db.invite_counts and inviter_id in db.invite_counts[gid_str]:
                db.invite_counts[gid_str][inviter_id]["left"] += 1
                db.save_data()
            try:
                inviter = guild.get_member(int(inviter_id))
            except Exception:
                pass

        cfg = db.invite_tracker.get(gid_str, {})
        if cfg.get("enabled", True) and cfg.get("log_channel"):
            try:
                ch = guild.get_channel(int(cfg["log_channel"]))
                if ch:
                    await self.send_leave_notification(ch, member, inviter)
            except Exception as e:
                print(f"⚠️ [InviteTracker] Failed to send leave notification: {e}")

    def get_user_invites(self, guild_id: int, user_id: int) -> dict:
        """Returns {regular, left, fake, bonus, total} for a user."""
        gid_str, uid_str = str(guild_id), str(user_id)
        counts = db.invite_counts.get(gid_str, {}).get(uid_str, {"regular": 0, "left": 0, "fake": 0, "bonus": 0})
        reg = counts.get("regular", 0)
        left = counts.get("left", 0)
        fake = counts.get("fake", 0)
        bonus = counts.get("bonus", 0)
        total = reg + bonus - left - fake
        return {
            "regular": reg,
            "left": left,
            "fake": fake,
            "bonus": bonus,
            "total": total
        }

    async def send_join_notification(self, channel: discord.TextChannel, member: discord.Member, inviter: discord.Member, code: str, is_fake: bool, is_vanity: bool):
        gid_str = str(member.guild.id)
        cfg = db.invite_tracker.get(gid_str, {})

        inv_stats = self.get_user_invites(member.guild.id, inviter.id) if inviter else {"total": 0, "regular": 0, "left": 0, "fake": 0, "bonus": 0}
        
        inviter_mention = inviter.mention if inviter else ("Vanity URL" if is_vanity else "Unknown")
        inviter_name = inviter.name if inviter else ("Vanity" if is_vanity else "Unknown")
        
        # Default template
        default_tpl = (
            "👋 Welcome {user} to **{guild}**!\n"
            "Invited by {inviter} (Code: `{code}`).\n"
            "📈 {inviter_name} now has **{invites}** invites (**{regular}** regular, **{bonus}** bonus, **{left}** left, **{fake}** fake)!"
        )
        template = cfg.get("join_msg") or default_tpl
        formatted = template.replace("{user}", member.mention) \
                            .replace("{user.name}", member.name) \
                            .replace("{guild}", member.guild.name) \
                            .replace("{inviter}", inviter_mention) \
                            .replace("{inviter.name}", inviter_name) \
                            .replace("{code}", code or "N/A") \
                            .replace("{invites}", str(inv_stats["total"])) \
                            .replace("{regular}", str(inv_stats["regular"])) \
                            .replace("{bonus}", str(inv_stats["bonus"])) \
                            .replace("{left}", str(inv_stats["left"])) \
                            .replace("{fake}", str(inv_stats["fake"])) \
                            .replace("{total_members}", str(member.guild.member_count))

        formatted = replace_plain_emojis(formatted, self.bot, guild=member.guild)

        if cfg.get("embed", True):
            color = int(cfg.get("embed_color", "5865F2").replace("#", ""), 16)
            embed = discord.Embed(
                title=cfg.get("embed_title", "📥 Member Joined"),
                description=formatted,
                color=color
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            if is_fake:
                embed.set_footer(text="⚠️ Suspected alt / fresh account (< 3 days old)")
            else:
                embed.set_footer(text=f"Member #{member.guild.member_count} • Server Time")
            await channel.send(embed=embed)
        else:
            await channel.send(formatted)

    async def send_leave_notification(self, channel: discord.TextChannel, member: discord.Member, inviter: discord.Member):
        gid_str = str(member.guild.id)
        cfg = db.invite_tracker.get(gid_str, {})
        inv_stats = self.get_user_invites(member.guild.id, inviter.id) if inviter else {"total": 0, "regular": 0, "left": 0, "fake": 0, "bonus": 0}
        
        inviter_mention = inviter.mention if inviter else "Unknown"
        inviter_name = inviter.name if inviter else "Unknown"

        default_leave = "📤 **{user.name}** left the server. They were invited by {inviter}. ({inviter_name} now has **{invites}** invites)."
        template = cfg.get("leave_msg") or default_leave
        formatted = template.replace("{user}", member.mention) \
                            .replace("{user.name}", member.name) \
                            .replace("{guild}", member.guild.name) \
                            .replace("{inviter}", inviter_mention) \
                            .replace("{inviter.name}", inviter_name) \
                            .replace("{invites}", str(inv_stats["total"])) \
                            .replace("{regular}", str(inv_stats["regular"])) \
                            .replace("{bonus}", str(inv_stats["bonus"])) \
                            .replace("{left}", str(inv_stats["left"])) \
                            .replace("{fake}", str(inv_stats["fake"])) \
                            .replace("{total_members}", str(member.guild.member_count))

        formatted = replace_plain_emojis(formatted, self.bot, guild=member.guild)

        if cfg.get("embed", True):
            embed = discord.Embed(
                title="📤 Member Left",
                description=formatted,
                color=0xED4245
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)
        else:
            await channel.send(formatted)

    # ────────────────────────── Slash Commands ──────────────────────────

    @app_commands.command(name="invites", description="Check your or another member's invite statistics.")
    @app_commands.describe(member="Member to inspect (defaults to yourself)")
    async def invites(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        stats = self.get_user_invites(interaction.guild.id, target.id)

        embed = discord.Embed(
            title=f"📨 Invite Summary • {clean_display_name(target.display_name)}",
            color=0x5865F2,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        net_total = stats["total"]
        embed.add_field(name="✨ Total Net Invites", value=f"**{net_total}**", inline=False)
        embed.add_field(name="📥 Regular", value=f"`{stats['regular']}`", inline=True)
        embed.add_field(name="🎁 Bonus", value=f"`{stats['bonus']}`", inline=True)
        embed.add_field(name="📤 Left", value=f"`{stats['left']}`", inline=True)
        embed.add_field(name="⚠️ Fake (<3d)", value=f"`{stats['fake']}`", inline=True)

        embed.set_footer(text=f"Requested by @{clean_display_name(interaction.user.name)}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="invite_leaderboard", description="View the top inviters in the server.")
    async def invite_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        gid = str(interaction.guild.id)
        all_counts = db.invite_counts.get(gid, {})

        leaderboard_data = []
        for uid_str, data in all_counts.items():
            reg = data.get("regular", 0)
            bon = data.get("bonus", 0)
            left = data.get("left", 0)
            fake = data.get("fake", 0)
            total = reg + bon - left - fake
            leaderboard_data.append((uid_str, total, reg, bon, left, fake))

        leaderboard_data.sort(key=lambda x: x[1], reverse=True)

        if not leaderboard_data:
            await interaction.followup.send("No invite statistics recorded yet!")
            return

        view = InviteLeaderboardView(interaction.guild, leaderboard_data, current_page=1)
        embed = view.build_embed()
        await interaction.followup.send(embed=embed, view=view)

    # ────────────────────────── Admin Subgroup ──────────────────────────

    invite_admin = app_commands.Group(name="invite_admin", description="Configure and manage the server invite tracker.")

    @invite_admin.command(name="add", description="Add bonus invites to a member.")
    @app_commands.default_permissions(administrator=True)
    async def add_bonus(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        gid_str, uid_str = str(interaction.guild.id), str(member.id)
        if gid_str not in db.invite_counts: db.invite_counts[gid_str] = {}
        if uid_str not in db.invite_counts[gid_str]:
            db.invite_counts[gid_str][uid_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

        db.invite_counts[gid_str][uid_str]["bonus"] += amount
        db.save_data()
        stats = self.get_user_invites(interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ Added **{amount}** bonus invites to {member.mention}. New total: **{stats['total']}** invites.")

    @invite_admin.command(name="remove", description="Remove bonus invites from a member.")
    @app_commands.default_permissions(administrator=True)
    async def remove_bonus(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        gid_str, uid_str = str(interaction.guild.id), str(member.id)
        if gid_str not in db.invite_counts: db.invite_counts[gid_str] = {}
        if uid_str not in db.invite_counts[gid_str]:
            db.invite_counts[gid_str][uid_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

        db.invite_counts[gid_str][uid_str]["bonus"] = max(0, db.invite_counts[gid_str][uid_str]["bonus"] - amount)
        db.save_data()
        stats = self.get_user_invites(interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ Removed **{amount}** bonus invites from {member.mention}. New total: **{stats['total']}** invites.")

    @invite_admin.command(name="add_fake", description="Add fake invites to a member.")
    @app_commands.describe(member="Target member", amount="Number of fake invites to add")
    @app_commands.default_permissions(administrator=True)
    async def add_fake(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        gid_str, uid_str = str(interaction.guild.id), str(member.id)
        if gid_str not in db.invite_counts: db.invite_counts[gid_str] = {}
        if uid_str not in db.invite_counts[gid_str]:
            db.invite_counts[gid_str][uid_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

        db.invite_counts[gid_str][uid_str]["fake"] += amount
        db.save_data()
        stats = self.get_user_invites(interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ Added **{amount}** fake invites to {member.mention}. (Net: **{stats['total']}**, Fake: **{stats['fake']}**)")

    @invite_admin.command(name="remove_fake", description="Remove fake invites from a member.")
    @app_commands.describe(member="Target member", amount="Number of fake invites to remove")
    @app_commands.default_permissions(administrator=True)
    async def remove_fake(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        gid_str, uid_str = str(interaction.guild.id), str(member.id)
        if gid_str not in db.invite_counts: db.invite_counts[gid_str] = {}
        if uid_str not in db.invite_counts[gid_str]:
            db.invite_counts[gid_str][uid_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

        db.invite_counts[gid_str][uid_str]["fake"] = max(0, db.invite_counts[gid_str][uid_str]["fake"] - amount)
        db.save_data()
        stats = self.get_user_invites(interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ Removed **{amount}** fake invites from {member.mention}. (Net: **{stats['total']}**, Fake: **{stats['fake']}**)")

    @invite_admin.command(name="set", description="Manually set exact invite numbers for a member.")
    @app_commands.describe(
        member="Target member",
        regular="Regular invites (optional)",
        fake="Fake invites (optional)",
        bonus="Bonus invites (optional)",
        left="Left invites (optional)"
    )
    @app_commands.default_permissions(administrator=True)
    async def set_invites(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        regular: Optional[int] = None,
        fake: Optional[int] = None,
        bonus: Optional[int] = None,
        left: Optional[int] = None
    ):
        gid_str, uid_str = str(interaction.guild.id), str(member.id)
        if gid_str not in db.invite_counts: db.invite_counts[gid_str] = {}
        if uid_str not in db.invite_counts[gid_str]:
            db.invite_counts[gid_str][uid_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

        rec = db.invite_counts[gid_str][uid_str]
        if regular is not None: rec["regular"] = max(0, regular)
        if fake is not None: rec["fake"] = max(0, fake)
        if bonus is not None: rec["bonus"] = max(0, bonus)
        if left is not None: rec["left"] = max(0, left)

        db.save_data()
        stats = self.get_user_invites(interaction.guild.id, member.id)
        await interaction.response.send_message(
            f"✅ Updated invites for {member.mention}:\n"
            f"> **Net Total:** `{stats['total']}`\n"
            f"> **Regular:** `{rec['regular']}` • **Fake:** `{rec['fake']}` • **Bonus:** `{rec['bonus']}` • **Left:** `{rec['left']}`"
        )

    @invite_admin.command(name="clear", description="Reset all invite records for a member.")
    @app_commands.default_permissions(administrator=True)
    async def clear_invites(self, interaction: discord.Interaction, member: discord.Member):
        gid_str, uid_str = str(interaction.guild.id), str(member.id)
        if gid_str in db.invite_counts and uid_str in db.invite_counts[gid_str]:
            db.invite_counts[gid_str][uid_str] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}
            db.save_data()
        await interaction.response.send_message(f"🧹 Successfully reset invite counts for {member.mention}.")

    @invite_admin.command(name="channel", description="Set the channel where invite join/leave logs are posted.")
    @app_commands.default_permissions(administrator=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid_str = str(interaction.guild.id)
        if gid_str not in db.invite_tracker: db.invite_tracker[gid_str] = {}
        db.invite_tracker[gid_str]["log_channel"] = str(channel.id)
        db.invite_tracker[gid_str]["enabled"] = True
        db.save_data()
        await interaction.response.send_message(f"✅ Invite log channel set to {channel.mention}.")

    @invite_admin.command(name="message", description="Configure the custom join message template.")
    @app_commands.default_permissions(administrator=True)
    async def set_join_msg(self, interaction: discord.Interaction, template: str):
        gid_str = str(interaction.guild.id)
        if gid_str not in db.invite_tracker: db.invite_tracker[gid_str] = {}
        db.invite_tracker[gid_str]["join_msg"] = template
        db.save_data()
        await interaction.response.send_message("✅ Custom invite join message template updated successfully!")

    @invite_admin.command(name="leave_message", description="Configure the custom leave message template.")
    @app_commands.default_permissions(administrator=True)
    async def set_leave_msg(self, interaction: discord.Interaction, template: str):
        gid_str = str(interaction.guild.id)
        if gid_str not in db.invite_tracker: db.invite_tracker[gid_str] = {}
        db.invite_tracker[gid_str]["leave_msg"] = template
        db.save_data()
        await interaction.response.send_message("✅ Custom invite leave message template updated successfully!")


class InviteLeaderboardView(discord.ui.View):
    """Interactive pagination view for Invite Leaderboard."""
    def __init__(self, guild: discord.Guild, data: list, current_page: int = 1, per_page: int = 10):
        super().__init__(timeout=300)
        self.guild = guild
        self.data = data
        self.current_page = current_page
        self.per_page = per_page
        self.total_pages = max(1, math.ceil(len(data) / per_page))
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = (self.current_page <= 1)
        self.next_btn.disabled = (self.current_page >= self.total_pages)
        self.page_indicator.label = f"Page {self.current_page} / {self.total_pages}"

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🏆 Top Inviters • {self.guild.name}",
            color=0x5865F2,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)

        offset = (self.current_page - 1) * self.per_page
        page_items = self.data[offset:offset + self.per_page]

        lines = []
        for idx, (uid_str, total, reg, bon, left, fake) in enumerate(page_items, start=offset + 1):
            member = self.guild.get_member(int(uid_str))
            name = clean_display_name(member.display_name if member else f"User {uid_str[-4:]}")
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"`#{idx}`"
            lines.append(f"{medal} **{name}** — **{total}** invites (`+{reg}` reg, `+{bon}` bonus, `-{left}` left, `-{fake}` fake)")

        embed.description = "\n".join(lines) if lines else "No ranked inviters found."
        embed.set_footer(text=f"Page {self.current_page} of {self.total_pages} • Total {len(self.data)} inviters")
        return embed

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, custom_id="inv_lb_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.current_page > 1:
            self.current_page -= 1
        self.update_buttons()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Page 1 / 1", style=discord.ButtonStyle.secondary, disabled=True, custom_id="inv_lb_page")
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="inv_lb_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.current_page < self.total_pages:
            self.current_page += 1
        self.update_buttons()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


async def setup(bot):
    await bot.add_cog(InviteTracker(bot))

