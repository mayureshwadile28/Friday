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

def make_box_embed(title: str, description: str, status: str = "info") -> discord.Embed:
    """Creates a sleek, dark-themed response box with monochrome status indicators."""
    prefix_map = {
        "success": "✔",
        "error": "✖",
        "cancel": "✖",
        "warning": "▲",
        "info": "ℹ"
    }
    symbol = prefix_map.get(status, "ℹ")
    clean_title = f"{symbol} {title}" if not title.startswith(("✔", "✖", "▲", "ℹ")) else title
    return discord.Embed(
        title=clean_title,
        description=description,
        color=0x2b2d31
    )

def get_guild_categories_and_channels(guild: discord.Guild):
    """Organizes guild sendable channels by category, returning {cat_id: {name, channels}}."""
    cat_map = {}
    if not guild:
        return cat_map

    # 1. Normal categories
    for cat in guild.categories:
        valid_channels = [
            ch for ch in cat.channels
            if isinstance(ch, (discord.TextChannel, discord.VoiceChannel))
        ]
        if valid_channels:
            cat_map[str(cat.id)] = {
                "name": cat.name,
                "channels": valid_channels
            }

    # 2. Channels without any category
    orphan_channels = [
        ch for ch in guild.text_channels
        if ch.category is None
    ]
    if orphan_channels:
        cat_map["none"] = {
            "name": "General / Uncategorized",
            "channels": orphan_channels
        }

    return cat_map

class CategorySelectDropdown(discord.ui.Select):
    def __init__(self, parent_view, categories_map: dict, active_cat_id: str):
        self.parent_view = parent_view
        options = []
        for cat_id, data in list(categories_map.items())[:25]:
            count = len(data["channels"])
            options.append(discord.SelectOption(
                label=data["name"][:100],
                value=cat_id,
                description=f"{count} channel{'s' if count != 1 else ''}"[:100],
                default=(cat_id == active_cat_id),
                emoji="📁"
            ))
        super().__init__(
            placeholder="Step 1: Select Category...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.parent_view.initiator:
            await interaction.response.send_message(
                embed=make_box_embed("Unauthorized", "Only the staff member who initiated this announcement can change settings.", status="warning"),
                ephemeral=True
            )
            return

        selected_cat_id = self.values[0]
        self.parent_view.switch_category(selected_cat_id)
        embed = self.parent_view.generate_embed()
        await interaction.response.edit_message(embed=embed, view=self.parent_view)

class CategoryChannelDropdown(discord.ui.Select):
    def __init__(self, parent_view, channels: list, active_channel_id: str | None):
        self.parent_view = parent_view
        options = []
        for ch in channels[:25]:
            is_def = (str(ch.id) == str(active_channel_id))
            is_news = getattr(ch, "is_news", lambda: False)()
            options.append(discord.SelectOption(
                label=ch.name[:100],
                value=str(ch.id),
                description=f"#{ch.name}"[:100],
                default=is_def,
                emoji="📢" if is_news else "💬"
            ))
        super().__init__(
            placeholder="Step 2: Select Channel in Category...",
            min_values=1,
            max_values=1,
            options=options if options else [discord.SelectOption(label="No sendable channels", value="none")],
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.parent_view.initiator:
            await interaction.response.send_message(
                embed=make_box_embed("Unauthorized", "Only the staff member who initiated this announcement can change channels.", status="warning"),
                ephemeral=True
            )
            return

        selected_ch_id = self.values[0]
        if selected_ch_id != "none" and interaction.guild:
            ch = interaction.guild.get_channel(int(selected_ch_id))
            if ch:
                self.parent_view.target_channel = ch
                for opt in self.options:
                    opt.default = (opt.value == selected_ch_id)

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
        self.format_mode = "normal"  # Default: clean normal message text (toggleable to Rich Embed)

        guild = source_msg.guild or (initiator.guild if hasattr(initiator, "guild") else None)
        self.categories_map = get_guild_categories_and_channels(guild) if guild else {}

        # Determine initial active category
        self.active_cat_id = "none"
        if target_channel and target_channel.category and str(target_channel.category.id) in self.categories_map:
            self.active_cat_id = str(target_channel.category.id)
        elif self.categories_map:
            self.active_cat_id = list(self.categories_map.keys())[0]

        # Initial channel options
        active_cat_data = self.categories_map.get(self.active_cat_id, {})
        initial_channels = active_cat_data.get("channels", [])
        if not self.target_channel and initial_channels:
            self.target_channel = initial_channels[0]

        active_ch_id = str(self.target_channel.id) if self.target_channel else None

        # Row 0: Category Selector
        if self.categories_map:
            self.category_select = CategorySelectDropdown(self, self.categories_map, self.active_cat_id)
            self.add_item(self.category_select)
        else:
            self.category_select = None

        # Row 1: Channel Selector in category
        self.channel_select = CategoryChannelDropdown(self, initial_channels, active_ch_id)
        self.add_item(self.channel_select)

    def switch_category(self, cat_id: str):
        self.active_cat_id = cat_id
        if self.category_select:
            for opt in self.category_select.options:
                opt.default = (opt.value == cat_id)

        cat_data = self.categories_map.get(cat_id, {})
        channels = cat_data.get("channels", [])

        channel_ids = [str(ch.id) for ch in channels]
        if self.target_channel and str(self.target_channel.id) in channel_ids:
            active_ch_id = str(self.target_channel.id)
        elif channels:
            self.target_channel = channels[0]
            active_ch_id = str(channels[0].id)
        else:
            self.target_channel = None
            active_ch_id = None

        options = []
        for ch in channels[:25]:
            is_def = (str(ch.id) == str(active_ch_id))
            is_news = getattr(ch, "is_news", lambda: False)()
            options.append(discord.SelectOption(
                label=ch.name[:100],
                value=str(ch.id),
                description=f"#{ch.name}"[:100],
                default=is_def,
                emoji="📢" if is_news else "💬"
            ))
        self.channel_select.options = options if options else [discord.SelectOption(label="No channels found", value="none")]

    def generate_embed(self) -> discord.Embed:
        chan_mention = self.target_channel.mention if self.target_channel else "*None Selected (Use dropdowns below)*"
        
        # Build snippet of source content
        content_preview = (self.source_msg.content or "").strip()
        if len(content_preview) > 300:
            content_preview = content_preview[:300] + "..."
        if not content_preview and self.source_msg.attachments:
            content_preview = f"*[File Attachment: {self.source_msg.attachments[0].filename}]*"
        elif not content_preview and self.source_msg.embeds:
            content_preview = "*[Rich Embed Card]*"
        elif not content_preview:
            content_preview = "*[No Text]*"

        fmt_desc = "💬 **Normal Message** (clean text, no embed box)" if self.format_mode == "normal" else "📦 **Rich Embed Box** (colored side line, thumbnail & footer)"

        embed = discord.Embed(
            title="Confirm Announcement Broadcast",
            description=(
                f"**Destination Channel:** {chan_mention}\n"
                f"**Broadcast Format:** {fmt_desc}\n"
                f"**Drafted By:** {self.source_msg.author.mention}\n"
                f"**Source Message:** [Jump to Message]({self.source_msg.jump_url})\n\n"
                f"**Message Preview:**\n>>> {content_preview}\n\n"
                f"Are you sure you want Friday to broadcast this announcement?"
            ),
            color=0x2b2d31
        )
        if self.source_msg.author.display_avatar:
            embed.set_author(name=f"Initiated by {self.initiator.display_name}", icon_url=self.initiator.display_avatar.url)
        embed.set_footer(text="Step 1: Pick Category • Step 2: Pick Channel • Toggle format or confirm below.")
        return embed

    async def on_timeout(self):
        if self.prompt_message:
            try:
                timeout_embed = make_box_embed(
                    "Confirmation Timed Out",
                    "The announcement confirmation window timed out without approval.",
                    status="cancel"
                )
                await self.prompt_message.edit(content=None, embed=timeout_embed, view=None)
            except Exception:
                pass

    @discord.ui.button(label="Format: 💬 Normal Message", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_format_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.initiator:
            await interaction.response.send_message(
                embed=make_box_embed("Unauthorized", "Only the staff member who initiated this announcement can toggle the format.", status="warning"),
                ephemeral=True
            )
            return

        if self.format_mode == "normal":
            self.format_mode = "embed"
            button.label = "Format: 📦 Rich Embed Box"
            button.style = discord.ButtonStyle.primary
        else:
            self.format_mode = "normal"
            button.label = "Format: 💬 Normal Message"
            button.style = discord.ButtonStyle.secondary

        embed = self.generate_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Broadcast Announcement", style=discord.ButtonStyle.success, row=2)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.initiator:
            await interaction.response.send_message(
                embed=make_box_embed("Unauthorized", "Only the staff member who initiated this announcement can confirm.", status="warning"),
                ephemeral=True
            )
            return

        if not self.target_channel:
            await interaction.response.send_message(
                embed=make_box_embed("Missing Destination", "Please select an announcement destination channel from the dropdown first.", status="warning"),
                ephemeral=True
            )
            return

        # Resolve target channel to concrete sendable channel
        target = self.target_channel
        if not hasattr(target, 'send') and hasattr(target, 'id') and interaction.guild:
            target = interaction.guild.get_channel(int(target.id))
            if not target:
                try:
                    target = await self.bot.fetch_channel(int(self.target_channel.id))
                except Exception:
                    target = None

        if not target or not hasattr(target, 'send'):
            await interaction.response.send_message(
                embed=make_box_embed("Channel Error", "Could not resolve destination channel to a sendable channel. Please re-select it.", status="error"),
                ephemeral=True
            )
            return

        gid = str(interaction.guild.id) if interaction.guild else ""
        # Remember chosen announcement channel
        if gid:
            db.announcement_channels[gid] = str(target.id)
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

        try:
            if self.format_mode == "embed":
                # Rich Embed Box format
                lines = [l for l in new_content.split('\n')]
                embed_title = None
                embed_desc = new_content
                if lines and lines[0].startswith('# '):
                    embed_title = lines[0].replace('# ', '').strip()
                    embed_desc = '\n'.join(lines[1:]).strip()

                embed = discord.Embed(
                    title=embed_title,
                    description=embed_desc if embed_desc else None,
                    color=0x2dd4bf
                )
                if interaction.guild.icon:
                    embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
                if self.bot.user and self.bot.user.display_avatar:
                    embed.set_thumbnail(url=self.bot.user.display_avatar.url)
                embed.set_footer(text=f"Official Server Announcement • Initiated by {self.initiator.display_name}")

                broadcasted = await target.send(
                    content="@everyone" if "@everyone" in new_content and embed_title else None,
                    embed=embed,
                    files=files if files else [],
                    allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True)
                )
            else:
                # Normal Clean Chat Message format (as seen in screenshot, no embed box)
                source_embeds = []
                for em in self.source_msg.embeds:
                    e = em.copy()
                    if e.title:
                        e.title = replace_plain_emojis(e.title, self.bot, guild=interaction.guild)
                    if e.description:
                        e.description = replace_plain_emojis(e.description, self.bot, guild=interaction.guild)
                    source_embeds.append(e)

                broadcasted = await target.send(
                    content=new_content if new_content else None,
                    embeds=source_embeds if source_embeds else None,
                    files=files if files else [],
                    allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True)
                )

            success_embed = make_box_embed(
                "Announcement Broadcasted",
                f"Successfully dispatched to {target.mention} • [Jump to Announcement]({broadcasted.jump_url})",
                status="success"
            )
            await interaction.response.edit_message(
                content=None,
                embed=success_embed,
                view=None
            )

            try:
                await self.source_msg.add_reaction("📢")
                await self.source_msg.add_reaction("✅")
            except Exception:
                pass

        except discord.Forbidden:
            err_embed = make_box_embed(
                "Permission Error",
                f"Friday does not have permission to send messages or embed links in {target.mention}. Please grant appropriate channel permissions.",
                status="error"
            )
            await interaction.response.edit_message(
                content=None,
                embed=err_embed,
                view=None
            )
        except Exception as err:
            err_embed = make_box_embed(
                "Broadcast Error",
                f"An error occurred while broadcasting the announcement:\n`{err}`",
                status="error"
            )
            await interaction.response.edit_message(
                content=None,
                embed=err_embed,
                view=None
            )

        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=2)
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.initiator:
            await interaction.response.send_message(
                embed=make_box_embed("Unauthorized", "Only the staff member who initiated this announcement can cancel.", status="warning"),
                ephemeral=True
            )
            return

        cancel_embed = make_box_embed(
            "Announcement Cancelled",
            "The announcement broadcast request has been cancelled.",
            status="cancel"
        )
        await interaction.response.edit_message(content=None, embed=cancel_embed, view=None)
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
            await interaction.response.send_message(
                embed=make_box_embed("Server Only", "This command can only be used in a Discord server.", status="error"),
                ephemeral=True
            )
            return

        # Staff Authorization: require Manage Messages, Manage Guild, or Administrator
        perms = interaction.user.guild_permissions
        if not (perms.administrator or perms.manage_guild or perms.manage_messages):
            await interaction.response.send_message(
                embed=make_box_embed("Access Denied", "Only staff members with **Manage Messages** or **Administrator** permissions can dispatch announcements.", status="error"),
                ephemeral=True
            )
            return

        # Ensure the message contains something to broadcast
        if not message.content and not message.attachments and not message.embeds:
            await interaction.response.send_message(
                embed=make_box_embed("Invalid Message", "That message does not contain any text, attachments, or embeds to announce.", status="warning"),
                ephemeral=True
            )
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

        # Send confirmation card with category & channel selectors (ephemeral for clean staff review)
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
            await interaction.response.send_message(
                embed=make_box_embed("Server Only", "This command can only be used in a Discord server.", status="error"),
                ephemeral=True
            )
            return

        perms = interaction.user.guild_permissions
        if not (perms.administrator or perms.manage_guild or perms.manage_messages):
            await interaction.response.send_message(
                embed=make_box_embed("Access Denied", "Only staff with **Manage Messages** or **Administrator** permissions can configure announcement channels.", status="error"),
                ephemeral=True
            )
            return

        gid = str(interaction.guild.id)
        if channel:
            db.announcement_channels[gid] = str(channel.id)
            db.save_data()
            await interaction.response.send_message(
                embed=make_box_embed(
                    "Announcement Channel Updated",
                    f"Official server announcements will now be sent to {channel.mention}.\n\n"
                    f"💡 Right-click any message or paragraph ➔ **Apps** ➔ **Initiate Announcement** to broadcast.",
                    status="success"
                ),
                ephemeral=True
            )
        else:
            current_id = db.announcement_channels.get(gid)
            if current_id:
                ch = interaction.guild.get_channel(int(current_id))
                ch_mention = ch.mention if ch else f"Channel ID `{current_id}` (Not Found)"
                await interaction.response.send_message(
                    embed=make_box_embed(
                        "Announcement Channel",
                        f"Current announcement channel: {ch_mention}\n\n"
                        f"💡 Right-click any message ➔ **Apps** ➔ **Initiate Announcement** to broadcast.",
                        status="info"
                    ),
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    embed=make_box_embed(
                        "No Channel Configured",
                        "No official announcement channel configured yet.\n"
                        "Use `/announcement_channel #channel` or configure it in the dashboard.",
                        status="warning"
                    ),
                    ephemeral=True
                )

async def setup(bot):
    await bot.add_cog(Announcements(bot))
