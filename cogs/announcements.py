import discord
from discord.ext import commands
from discord import app_commands
import re
from database import db

from emoji_utils import replace_plain_emojis

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

        # Check if the user is replying to a draft announcement message
        if not message.reference or not message.reference.message_id:
            return

        # Clean content and check for announcement triggers (handling spelling variations and natural phrasing)
        cleaned_text = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip().lower()
        announcement_keywords = ["announcement", "annoucement", "anouncement", "announce", "elan", "elam", "aillan"]
        if not any(k in cleaned_text for k in announcement_keywords):
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

        # Check if the user mentioned a channel in the command (e.g. @Friday announcement #general)
        if message.channel_mentions:
            target_channel = message.channel_mentions[0]
            target_channel_id = str(target_channel.id)
            # Update the default channel in the database
            db.announcement_channels[gid] = target_channel_id
            db.save_data()
        else:
            target_channel_id = db.announcement_channels.get(gid)
            if not target_channel_id:
                await message.reply(
                    "⚠️ **Announcement Channel Not Specified!**\n"
                    "Please mention the target channel in your message, for example: `@Friday announcement #general`",
                    mention_author=False
                )
                return
            
            # Retrieve the target destination channel
            try:
                target_channel = message.guild.get_channel(int(target_channel_id))
            except (ValueError, TypeError):
                target_channel = None

        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            await message.reply(
                "❌ **Channel Not Found:** The configured announcement channel could not be found or was deleted. Please specify a channel in your message like `@Friday announcement #channel`.",
                mention_author=False
            )
            return

        # Fetch the referenced draft message
        try:
            if message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
                draft_msg = message.reference.resolved
            else:
                draft_msg = await message.channel.fetch_message(message.reference.message_id)
        except Exception as e:
            await message.reply(f"❌ Failed to fetch draft message: {e}", mention_author=False)
            return

        if not draft_msg.content and not draft_msg.attachments and not draft_msg.embeds:
            await message.reply("⚠️ The referenced message appears to be empty.", mention_author=False)
            return

        # Send confirmation prompt
        view = AnnouncementConfirmView(message, draft_msg, target_channel, self.bot)
        prompt_tpl = db.custom_responses.get(gid, {}).get("announcement_confirm_prompt", "❓ **Are you sure you want to send this message to {channel}?**")
        prompt_txt = prompt_tpl.replace("{channel}", target_channel.mention)
        prompt = await message.reply(
            prompt_txt,
            view=view,
            mention_author=False
        )
        view.prompt_message = prompt

async def setup(bot):
    await bot.add_cog(Announcements(bot))
