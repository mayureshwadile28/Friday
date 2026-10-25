import discord
from discord.ext import commands
from discord import app_commands
import re
import io
from database import db
from emoji_utils import replace_plain_emojis

# Announcement intent patterns
ANN_KEYWORD_REGEX = re.compile(
    r'\b(?:announc(?:e|ement)|announcment|annoucement|anouncement|annonucment|elan|elam|ailaan|aillan|ghoshna)\b',
    re.IGNORECASE
)

# Drafting and prompt instruction keywords (these indicate the user wants the LLM to write/draft an announcement!)
DRAFT_INSTRUCTION_REGEX = re.compile(
    r'\b(?:likh\s*do|likhdo|likho|likh\s*de|likhde|likh|write|compose|draft|drafting|bana\s*do|banado|banao|bana\s*de|banade|create|generate|prepare|tayyar\s*karo|soch\s*ke|ek\s+badhiya|ek\s+ac?chha|ek\s+naya|ke\s+liye|ke\s+leye|for\s+staff|for\s+server|about)\b',
    re.IGNORECASE
)

# Dispatch action keywords (these indicate publishing / sending the draft)
DISPATCH_ACTION_REGEX = re.compile(
    r'\b(?:kar\s*do|kardo|karo|kar\s*de|karde|kar\s*dena|kardena|send|send\s*it|send\s*this|bhej\s*do|bhejdo|bhejo|bhej\s*dena|bhejdena|post|post\s*it|post\s*this|post\s*kardo|push|push\s*kardo|broadcast|publish|daal\s*do|daaldo|daalo)\b',
    re.IGNORECASE
)

def is_announcement_dispatch_command(text: str, is_reply: bool = False) -> bool:
    """Classify whether a user input is an announcement dispatch/publish command versus an LLM drafting prompt."""
    clean = text.strip()
    clean_no_ch = re.sub(r'<#\d+>', '', clean).strip()
    words = [w.strip('!?,.: ') for w in clean_no_ch.split() if w.strip('!?,.: ')]

    # 1. If it contains drafting/writing instructions, it belongs to the LLM
    if DRAFT_INSTRUCTION_REGEX.search(clean):
        return False

    has_ann_kw = bool(ANN_KEYWORD_REGEX.search(clean))
    has_dispatch_action = bool(DISPATCH_ACTION_REGEX.search(clean))

    # 2. If announcement keyword is present
    if has_ann_kw:
        if has_dispatch_action:
            return True
        if len(words) <= 3:
            return True
        if is_reply:
            return True

    # 3. If replying to Friday and user issues a dispatch verb (e.g. "@Friday kardo", "@Friday send it")
    if is_reply and has_dispatch_action and len(words) <= 4:
        return True

    return False

def format_announcement_broadcast_text(raw_text: str, guild: discord.Guild, bot: commands.Bot) -> str:
    """Prepare and format announcement text for broadcast with @everyone and custom emojis."""
    if not raw_text:
        return ""

    # 1. Un-sanitize zero-width space in @everyone or @here
    processed = raw_text.replace('@\u200beveryone', '@everyone').replace('@\u200bhere', '@here')

    # 2. Convert conversational greetings like "Hey everyone" or "Hello everyone" to "Hey @everyone!"
    processed = re.sub(
        r'\b(hey|hello|hi|namaste)\s+everyone\b(!|\?|\.|\,)?',
        r'\1 @everyone\2',
        processed,
        flags=re.IGNORECASE
    )

    # 3. If @everyone is not yet present, ensure @everyone is included
    if '@everyone' not in processed and '@here' not in processed:
        if processed.startswith('# '):
            lines = processed.split('\n')
            lines.insert(1, '\n@everyone')
            processed = '\n'.join(lines)
        elif processed:
            processed = f"@everyone\n\n{processed}"
        else:
            processed = "@everyone"

    # 4. Replace plain emoji representations with server/custom emojis
    return replace_plain_emojis(processed, bot, guild=guild)

class ChannelSelectDropdown(discord.ui.ChannelSelect):
    def __init__(self, parent_view):
        self.parent_view = parent_view
        super().__init__(
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            placeholder="Change destination channel (optional)...",
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.parent_view.initiator:
            await interaction.response.send_message("Only the staff member who initiated this announcement can change the channel.", ephemeral=True)
            return
        selected_channel = self.values[0]
        self.parent_view.target_channel = selected_channel
        embed = self.parent_view.generate_embed()
        await interaction.response.edit_message(embed=embed, view=self.parent_view)

class AnnouncementConfirmView(discord.ui.View):
    def __init__(self, initiator: discord.Member, source_msg: discord.Message, target_channel: discord.TextChannel | None, bot: commands.Bot):
        super().__init__(timeout=60)
        self.initiator = initiator
        self.source_msg = source_msg
        self.target_channel = target_channel
        self.bot = bot
        self.prompt_message = None

        # Add destination channel selector
        self.add_item(ChannelSelectDropdown(self))

    def generate_embed(self) -> discord.Embed:
        chan_mention = self.target_channel.mention if self.target_channel else "⚠️ *None Selected (Use dropdown below)*"
        
        # Build snippet of source content
        content_preview = (self.source_msg.content or "").strip()
        if len(content_preview) > 350:
            content_preview = content_preview[:350] + "..."
        if not content_preview and self.source_msg.attachments:
            content_preview = f"*[File Attachment: {self.source_msg.attachments[0].filename}]*"
        elif not content_preview and self.source_msg.embeds:
            content_preview = "*[Rich Embed Card]*"
        elif not content_preview:
            content_preview = "*[No Text]*"

        embed = discord.Embed(
            title="📢 Confirm Announcement Broadcast",
            description=(
                f"🎯 **Destination Channel:** {chan_mention}\n"
                f"👤 **Drafted By:** {self.source_msg.author.mention}\n"
                f"🔗 **Source Message:** [Jump to Message]({self.source_msg.jump_url})\n\n"
                f"📝 **Message Preview:**\n>>> {content_preview}\n\n"
                f"❓ **Are you sure you want Friday to broadcast this announcement?**"
            ),
            color=0x2dd4bf
        )
        if self.source_msg.author.display_avatar:
            embed.set_author(name=f"Initiated by {self.initiator.display_name}", icon_url=self.initiator.display_avatar.url)
        embed.set_footer(text="Click 'Yes, Broadcast Announcement' to publish, or select a different channel above.")
        return embed

    async def on_timeout(self):
        if self.prompt_message:
            try:
                gid = str(self.source_msg.guild.id) if self.source_msg.guild else ""
                msg_tpl = db.custom_responses.get(gid, {}).get("announcement_timeout", "⏳ **Announcement confirmation timed out.**")
                await self.prompt_message.edit(content=msg_tpl, embed=None, view=None)
            except Exception:
                pass

    @discord.ui.button(label="Yes, Broadcast Announcement", style=discord.ButtonStyle.success, emoji="📢", row=1)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.initiator:
            await interaction.response.send_message("Only the staff member who initiated this announcement can confirm.", ephemeral=True)
            return

        if not self.target_channel:
            await interaction.response.send_message("⚠️ Please select an announcement destination channel from the dropdown first!", ephemeral=True)
            return

        gid = str(interaction.guild.id) if interaction.guild else ""
        # Remember chosen announcement channel
        if gid:
            db.announcement_channels[gid] = str(self.target_channel.id)
            db.save_data()

        # Prepare attachments
        files = []
        for att in self.source_msg.attachments:
            try:
                files.append(await att.to_file())
            except Exception:
                pass

        # Prepare content & emojis
        raw_content = self.source_msg.content or ""
        new_content = format_announcement_broadcast_text(raw_content, interaction.guild, self.bot)

        # Prepare embeds
        new_embeds = []
        for em in self.source_msg.embeds:
            e = em.copy()
            if e.title:
                e.title = replace_plain_emojis(e.title, self.bot, guild=interaction.guild)
            if e.description:
                e.description = replace_plain_emojis(e.description, self.bot, guild=interaction.guild)
            for i, field in enumerate(e.fields):
                e.set_field_at(
                    i,
                    name=replace_plain_emojis(field.name, self.bot, guild=interaction.guild),
                    value=replace_plain_emojis(field.value, self.bot, guild=interaction.guild),
                    inline=field.inline
                )
            new_embeds.append(e)

        try:
            broadcasted = await self.target_channel.send(
                content=new_content if new_content else None,
                embeds=new_embeds,
                files=files if files else [],
                allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True)
            )

            default_success = "📢 **Announcement Broadcasted Successfully!**\nPosted to {channel} • [Jump to Announcement]({url})"
            msg_tpl = db.custom_responses.get(gid, {}).get("announcement_broadcast_success", default_success)
            formatted = msg_tpl.replace("{channel}", self.target_channel.mention).replace("{url}", broadcasted.jump_url)

            await interaction.response.edit_message(
                content=formatted,
                embed=None,
                view=None
            )

            try:
                await self.source_msg.add_reaction("📢")
                await self.source_msg.add_reaction("✅")
            except Exception:
                pass

        except discord.Forbidden:
            default_err = "❌ **Permission Error:** Friday does not have permission to send messages or embed links in {channel}. Please grant appropriate channel permissions."
            err_tpl = db.custom_responses.get(gid, {}).get("announcement_perm_err", default_err)
            await interaction.response.edit_message(
                content=err_tpl.replace("{channel}", self.target_channel.mention),
                embed=None,
                view=None
            )
        except Exception as err:
            await interaction.response.edit_message(content=f"❌ Error broadcasting announcement: {err}", embed=None, view=None)

        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌", row=1)
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.initiator:
            await interaction.response.send_message("Only the staff member who initiated this announcement can cancel.", ephemeral=True)
            return

        gid = str(interaction.guild.id) if interaction.guild else ""
        msg_tpl = db.custom_responses.get(gid, {}).get("announcement_cancel", "❌ **Announcement cancelled.**")
        await interaction.response.edit_message(content=msg_tpl, embed=None, view=None)
        self.stop()

class Announcements(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Context Menu: Right-click any message -> Apps -> Initiate Announcement
        self.ctx_menu = app_commands.ContextMenu(
            name="Initiate Announcement",
            callback=self.initiate_announcement_context,
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    async def initiate_announcement_context(self, interaction: discord.Interaction, message: discord.Message):
        """Context menu action to turn a message or paragraph into a verified server announcement."""
        if not interaction.guild:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return

        # Staff Authorization: require Manage Messages, Manage Guild, or Administrator
        perms = interaction.user.guild_permissions
        if not (perms.administrator or perms.manage_guild or perms.manage_messages):
            gid = str(interaction.guild.id)
            msg_tpl = db.custom_responses.get(gid, {}).get(
                "announcement_access_denied",
                "🛡️ **Access Denied:** Only staff members with **Manage Messages** or **Administrator** permissions can dispatch announcements."
            )
            await interaction.response.send_message(msg_tpl, ephemeral=True)
            return

        # Ensure the message contains something to broadcast
        if not message.content and not message.attachments and not message.embeds:
            await interaction.response.send_message("⚠️ That message does not contain any text, attachments, or embeds to announce.", ephemeral=True)
            return

        gid = str(interaction.guild.id)

        # 1. Target Channel resolution
        target_channel = None
        target_channel_id = db.announcement_channels.get(gid)
        if target_channel_id:
            try:
                target_channel = interaction.guild.get_channel(int(target_channel_id))
            except (ValueError, TypeError):
                target_channel = None

        # Fallback auto-detection for announcement channel in the server
        if not target_channel:
            for candidate_name in ["announcements", "announcement", "updates", "server-announcements", "news"]:
                found = discord.utils.get(interaction.guild.text_channels, name=candidate_name)
                if found:
                    target_channel = found
                    db.announcement_channels[gid] = str(found.id)
                    db.save_data()
                    break

        # Send confirmation card with channel selector and buttons (ephemeral for clean staff review)
        view = AnnouncementConfirmView(interaction.user, message, target_channel, self.bot)
        await interaction.response.send_message(
            embed=view.generate_embed(),
            view=view,
            ephemeral=True
        )
        view.prompt_message = await interaction.original_response()

    @app_commands.command(name="announcement_channel", description="Set or view the server's official announcement destination channel.")
    @app_commands.describe(channel="The text channel to send server announcements to (leave empty to view current)")
    @app_commands.default_permissions(manage_messages=True)
    async def announcement_channel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        """Slash command to configure or inspect the server's official announcement channel."""
        if not interaction.guild:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return

        perms = interaction.user.guild_permissions
        if not (perms.administrator or perms.manage_guild or perms.manage_messages):
            await interaction.response.send_message("🛡️ **Access Denied:** Only staff with **Manage Messages** or **Administrator** permissions can configure announcement channels.", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        if channel:
            db.announcement_channels[gid] = str(channel.id)
            db.save_data()
            await interaction.response.send_message(
                f"✅ **Official Announcement Channel Updated!**\n"
                f"Announcements will now be sent to {channel.mention}.\n\n"
                f"💡 **Tip:** Right-click any message or paragraph &rarr; **Apps** &rarr; **Initiate Announcement** to broadcast!",
                ephemeral=True
            )
        else:
            current_id = db.announcement_channels.get(gid)
            if current_id:
                ch = interaction.guild.get_channel(int(current_id))
                ch_mention = ch.mention if ch else f"Channel ID `{current_id}` (Not Found)"
                await interaction.response.send_message(
                    f"📢 **Current Announcement Channel:** {ch_mention}\n\n"
                    f"💡 Right-click any message &rarr; **Apps** &rarr; **Initiate Announcement** to broadcast!",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "⚠️ No official announcement channel configured yet.\n"
                    "Use `/announcement_channel #channel` or configure it in the dashboard.",
                    ephemeral=True
                )

async def setup(bot):
    await bot.add_cog(Announcements(bot))
