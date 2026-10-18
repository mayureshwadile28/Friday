import discord
from discord.ext import commands
from discord import app_commands
import re
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

class AnnouncementConfirmView(discord.ui.View):
    def __init__(self, original_msg: discord.Message, draft_msg: discord.Message, target_channel: discord.TextChannel, bot: commands.Bot):
        super().__init__(timeout=60)
        self.original_msg = original_msg
        self.draft_msg = draft_msg
        self.target_channel = target_channel
        self.bot = bot
        self.prompt_message = None

    async def on_timeout(self):
        if self.prompt_message:
            try:
                gid = str(self.original_msg.guild.id) if self.original_msg.guild else ""
                msg_tpl = db.custom_responses.get(gid, {}).get("announcement_timeout", "⏳ **Announcement confirmation timed out.**")
                await self.prompt_message.edit(content=msg_tpl, view=None)
            except Exception:
                pass

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.original_msg.author:
            await interaction.response.send_message("Only the command author can approve this.", ephemeral=True)
            return

        # Prepare attachments
        files = []
        for att in self.draft_msg.attachments:
            try:
                files.append(await att.to_file())
            except Exception:
                pass

        # Process content and ensure @everyone mention for broadcast (not during draft)
        raw_content = self.draft_msg.content or ""

        # 1. Un-sanitize any zero-width space in @everyone or @here
        processed_content = raw_content.replace('@\u200beveryone', '@everyone').replace('@\u200bhere', '@here')

        # 2. Convert conversational "Hey everyone" or "Hello everyone" to "Hey @everyone!"
        processed_content = re.sub(
            r'\b(hey|hello|hi|namaste)\s+everyone\b(!|\?|\.|\,)?',
            r'\1 @everyone\2',
            processed_content,
            flags=re.IGNORECASE
        )

        # 3. If @everyone is not yet present in the content, ensure @everyone is included
        if '@everyone' not in processed_content:
            if processed_content.startswith('# '):
                lines = processed_content.split('\n')
                lines.insert(1, '\n@everyone')
                processed_content = '\n'.join(lines)
            elif processed_content:
                processed_content = f"@everyone\n\n{processed_content}"
            else:
                processed_content = "@everyone"

        # Process emojis
        new_content = replace_plain_emojis(processed_content, self.bot, guild=self.original_msg.guild)
        new_embeds = []
        for em in self.draft_msg.embeds:
            e = em.copy()
            if e.title: e.title = replace_plain_emojis(e.title, self.bot, guild=self.original_msg.guild)
            if e.description: e.description = replace_plain_emojis(e.description, self.bot, guild=self.original_msg.guild)
            for i, field in enumerate(e.fields):
                e.set_field_at(i, name=replace_plain_emojis(field.name, self.bot, guild=self.original_msg.guild), 
                               value=replace_plain_emojis(field.value, self.bot, guild=self.original_msg.guild), 
                               inline=field.inline)
            new_embeds.append(e)

        try:
            broadcasted = await self.target_channel.send(
                content=new_content if new_content else None,
                embeds=new_embeds,
                files=files if files else [],
                allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True)
            )

            gid = str(interaction.guild.id) if interaction.guild else ""
            default_success = "📢 **Announcement Broadcasted Successfully!**\nPosted to {channel} • [Jump to Announcement]({url})"
            msg_tpl = db.custom_responses.get(gid, {}).get("announcement_broadcast_success", default_success)
            formatted = msg_tpl.replace("{channel}", self.target_channel.mention).replace("{url}", broadcasted.jump_url)

            await interaction.response.edit_message(
                content=formatted,
                view=None
            )

            try:
                await self.original_msg.add_reaction("📢")
                await self.original_msg.add_reaction("✅")
            except Exception:
                pass

        except discord.Forbidden:
            gid = str(interaction.guild.id) if interaction.guild else ""
            default_err = "❌ **Permission Error:** Friday does not have permission to send messages or embed links in {channel}. Please grant appropriate channel permissions."
            err_tpl = db.custom_responses.get(gid, {}).get("announcement_perm_err", default_err)
            await interaction.response.edit_message(
                content=err_tpl.replace("{channel}", self.target_channel.mention),
                view=None
            )
        except Exception as err:
            await interaction.response.edit_message(content=f"❌ Error broadcasting announcement: {err}", view=None)

        self.stop()

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.original_msg.author:
            await interaction.response.send_message("Only the command author can deny this.", ephemeral=True)
            return

        gid = str(interaction.guild.id) if interaction.guild else ""
        msg_tpl = db.custom_responses.get(gid, {}).get("announcement_cancel", "❌ **Announcement cancelled.**")
        await interaction.response.edit_message(content=msg_tpl, view=None)
        self.stop()

class Announcements(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Check if Friday is mentioned in the message
        is_bot_mentioned = (
            self.bot.user in message.mentions or 
            f"<@{self.bot.user.id}>" in message.content or 
            f"<@!{self.bot.user.id}>" in message.content
        )
        if not is_bot_mentioned:
            return

        # Clean content and check whether this is an announcement dispatch command
        cleaned_text = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
        is_reply = bool(message.reference and message.reference.message_id)

        # Dispatch command check: If this is an LLM drafting prompt (e.g. "likh do ek badhiya sa..."), ignore it here!
        if not is_announcement_dispatch_command(cleaned_text, is_reply=is_reply):
            return

        gid = str(message.guild.id)

        # Authorization: require Manage Messages, Manage Guild, or Administrator
        perms = message.author.guild_permissions
        if not (perms.administrator or perms.manage_guild or perms.manage_messages):
            msg_tpl = db.custom_responses.get(gid, {}).get("announcement_access_denied", "🛡️ **Access Denied:** Only staff members with **Manage Messages** or **Administrator** permissions can dispatch announcements.")
            await message.reply(
                msg_tpl,
                mention_author=False
            )
            return

        # 1. Target Channel resolution
        target_channel = None
        if message.channel_mentions:
            target_channel = message.channel_mentions[0]
            db.announcement_channels[gid] = str(target_channel.id)
            db.save_data()
        else:
            target_channel_id = db.announcement_channels.get(gid)
            if target_channel_id:
                try:
                    target_channel = message.guild.get_channel(int(target_channel_id))
                except (ValueError, TypeError):
                    target_channel = None

            # Fallback auto-detection for announcement channel in the server
            if not target_channel:
                for candidate_name in ["announcements", "announcement", "updates", "server-announcements", "news"]:
                    found = discord.utils.get(message.guild.text_channels, name=candidate_name)
                    if found:
                        target_channel = found
                        db.announcement_channels[gid] = str(found.id)
                        db.save_data()
                        break

        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            await message.reply(
                "⚠️ **Announcement Channel Not Specified!**\n"
                "Please specify the target channel in your message (e.g. `@Friday announcement #announcements`) or configure it in the dashboard.",
                mention_author=False
            )
            return

        # 2. Draft message resolution
        draft_msg = None
        if message.reference and message.reference.message_id:
            try:
                if message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
                    draft_msg = message.reference.resolved
                else:
                    draft_msg = await message.channel.fetch_message(message.reference.message_id)
            except Exception:
                draft_msg = None

        if not draft_msg:
            # Fallback: scan last 15 messages in the channel to find Friday's latest draft
            try:
                async for past_msg in message.channel.history(limit=15):
                    if past_msg.id == message.id:
                        continue
                    if past_msg.author.id == self.bot.user.id and past_msg.content:
                        if past_msg.content.strip().startswith('#') or 'announcement' in past_msg.content.lower():
                            draft_msg = past_msg
                            break
                        elif not past_msg.embeds and not past_msg.components and len(past_msg.content) > 30:
                            draft_msg = past_msg
                            break
            except Exception:
                pass

        if not draft_msg or (not draft_msg.content and not draft_msg.attachments and not draft_msg.embeds):
            await message.reply(
                "⚠️ **No Announcement Draft Found!**\n"
                "Please reply directly to Friday's announcement draft with `@Friday announcement kardo`, or ask Friday to write one first with `@Friday announcement likh do...`! 🌸",
                mention_author=False
            )
            return

        # Send confirmation prompt with buttons
        view = AnnouncementConfirmView(message, draft_msg, target_channel, self.bot)
        prompt_tpl = db.custom_responses.get(gid, {}).get("announcement_confirm_prompt", "❓ **Are you sure you want to broadcast this announcement to {channel}?**")
        prompt_txt = prompt_tpl.replace("{channel}", target_channel.mention)
        prompt = await message.reply(
            prompt_txt,
            view=view,
            mention_author=False
        )
        view.prompt_message = prompt

async def setup(bot):
    await bot.add_cog(Announcements(bot))
