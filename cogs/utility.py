import discord
from discord.ext import commands
from discord import app_commands
from hinglish_jokes import get_random_joke, build_joke_embed, JokeView
from response_utils import make_box_embed, reply_box

# ───────────────────── Help System Data & Components ─────────────────────

HELP_MODULES = [
    {
        "id": "antinuke",
        "name": "Antinuke",
        "emoji": "🛡",
        "desc": "Get All Antinuke & Security Commands",
        "sections": [
            ("Antinuke", ["antinuke_toggle", "antinuke_limit", "antinuke_refresh", "antinuke_sync", "antiraid", "antispam", "security_status"]),
            ("Whitelist", ["whitelist_add", "whitelist_remove"])
        ]
    },
    {
        "id": "antiabuse",
        "name": "Anti-Abuse",
        "emoji": "⚔",
        "desc": "Get All Anti-Abuse & Word Filter Commands",
        "sections": [
            ("Word Filters", ["anti_abuse", "anti_abuse_remove", "anti_abuse_list"]),
            ("Filter Immunity", ["anti_abuse_whitelist_add", "anti_abuse_whitelist_remove"])
        ]
    },
    {
        "id": "moderation",
        "name": "Moderation",
        "emoji": "🔨",
        "desc": "Get All Moderation Commands",
        "sections": [
            ("Member Moderation", ["ban", "unban", "timeout", "untimeout", "purge"]),
            ("Infractions", ["warn", "warnings", "clearwarns"])
        ]
    },
    {
        "id": "music",
        "name": "Music",
        "emoji": "🎵",
        "desc": "Get All Music & Audio Commands",
        "sections": [
            ("Playback", ["play", "pause", "resume", "skip", "stop", "volume"]),
            ("Queue & Sound Effects", ["queue", "shuffle", "filter", "likes", "join", "leave", "soundtest"])
        ]
    },
    {
        "id": "tickets",
        "name": "Ticket",
        "emoji": "🎫",
        "desc": "Get All Ticket Commands",
        "sections": [
            ("Interactive Panels", ["create_ticket_panel"])
        ]
    },
    {
        "id": "voice",
        "name": "Voice",
        "emoji": "🔊",
        "desc": "Get All Temporary Voice (Join-to-Create) Commands",
        "sections": [
            ("Hub Setup", ["voice setup", "voice autohub", "voice status"]),
            ("Room Controls", ["voice lock", "voice unlock", "voice hide", "voice unhide", "voice limit", "voice name", "voice kick", "voice claim"])
        ]
    },
    {
        "id": "privacy",
        "name": "Privacy",
        "emoji": "🔒",
        "desc": "Get All Privacy & Channel Lockdown Commands",
        "sections": [
            ("Lockdown Actions", ["private", "unprivate", "force_private"]),
            ("Categories", ["private_category", "unprivate_category"]),
            ("Exemptions", ["ignore_private_add", "ignore_private_remove"])
        ]
    },
    {
        "id": "reactionroles",
        "name": "ReactionRoles",
        "emoji": "🔥",
        "desc": "Get All Reaction Role Commands",
        "sections": [
            ("Interactive Panels", ["reaction_panel"])
        ]
    },
    {
        "id": "leveling",
        "name": "Leveling",
        "emoji": "🏆",
        "desc": "Get All XP & Rank Commands",
        "sections": [
            ("Rank & Progression", ["rank", "leaderboard", "level_setup", "level_mode"])
        ]
    },
    {
        "id": "announcements",
        "name": "Announcements",
        "emoji": "📢",
        "desc": "Get All Announcement Broadcast Commands",
        "sections": [
            ("Dispatcher", ["announcement_channel"]),
            ("Quick Broadcast", ["Apps -> Initiate Announcement"])
        ]
    },
    {
        "id": "utility",
        "name": "Utility",
        "emoji": "⚙",
        "desc": "Get All Utility & Expression Commands",
        "sections": [
            ("System", ["ping", "serverinfo", "bot_status", "sync", "joke", "afk"]),
            ("Expressions & Media", ["emoji_steal", "media"])
        ]
    },
    {
        "id": "welcomer",
        "name": "Welcomer",
        "emoji": "🚪",
        "desc": "Get All Welcomer Commands",
        "sections": [
            ("Member Welcomes", ["welcomer_setup", "welcome_test"])
        ]
    }
]

TOTAL_COMMANDS = sum(len(cmds) for mod in HELP_MODULES for _, cmds in mod["sections"])

class HelpSelect(discord.ui.Select):
    def __init__(self, current_page: int):
        options = [
            discord.SelectOption(
                label="Home / Overview",
                value="home",
                emoji="🏠",
                description="Return to the main overview page",
                default=(current_page == 0)
            )
        ]
        for idx, mod in enumerate(HELP_MODULES):
            options.append(discord.SelectOption(
                label=mod["name"],
                value=str(idx + 1),
                emoji=mod["emoji"],
                description=mod["desc"][:100],
                default=(current_page == idx + 1)
            ))
        super().__init__(
            placeholder="> Select Module From Here",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "home":
            self.view.current_page = 0
        else:
            self.view.current_page = int(val)
        await self.view.update_view(interaction)

class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author: discord.User | discord.Member):
        super().__init__(timeout=120)
        self.bot = bot
        self.author = author
        self.current_page = 0
        self.total_pages = 1 + len(HELP_MODULES)
        self.message = None

        self.select_menu = HelpSelect(self.current_page)
        self.add_item(self.select_menu)
        self.update_buttons()

    def update_buttons(self):
        self.first_btn.disabled = (self.current_page == 0)
        self.prev_btn.disabled = (self.current_page == 0)
        self.next_btn.disabled = (self.current_page == self.total_pages - 1)
        self.last_btn.disabled = (self.current_page == self.total_pages - 1)

    def generate_embed(self) -> discord.Embed:
        if self.current_page == 0:
            module_lines = "\n".join([f"  {m['emoji']} » **{m['name']}**" for m in HELP_MODULES])
            embed = discord.Embed(
                title="Hey , I'm Friday™",
                description=(
                    "A powerful multipurpose bot with Fastest Antinuke & Community Security.\n\n"
                    "• **My Prefix is** `/`\n"
                    f"• **Total Commands:** `{TOTAL_COMMANDS}`\n"
                    "• **Choose a Specific Module of your Desire**\n\n"
                    f"{module_lines}"
                ),
                color=0x2b2d31
            )
            embed.set_footer(text=f"Requested by {self.author.name} | Page 1 / {self.total_pages}")
        else:
            mod_idx = self.current_page - 1
            mod = HELP_MODULES[mod_idx]
            sections_text = []
            for sec_name, cmds in mod["sections"]:
                cmd_tags = " , ".join([f"`{c}`" for c in cmds])
                sections_text.append(f"**{sec_name}**\n{cmd_tags}\n")

            embed = discord.Embed(
                title=f"{mod['emoji']} {mod['name']}",
                description="\n".join(sections_text).strip(),
                color=0x2b2d31
            )
            embed.set_footer(text=f"Requested by {self.author.name} | Page {self.current_page + 1} / {self.total_pages}")

        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        return embed

    async def update_view(self, interaction: discord.Interaction):
        for opt in self.select_menu.options:
            if opt.value == "home":
                opt.default = (self.current_page == 0)
            else:
                opt.default = (int(opt.value) == self.current_page)

        self.update_buttons()
        embed = self.generate_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="✖ Unauthorized",
                    description=f"Only {self.author.mention} can interact with this help panel.",
                    color=0x2b2d31
                ),
                ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="<<", style=discord.ButtonStyle.secondary, row=1)
    async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        await self.update_view(interaction)

    @discord.ui.button(label="<", style=discord.ButtonStyle.secondary, row=1)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_view(interaction)

    @discord.ui.button(emoji="🗑", style=discord.ButtonStyle.danger, row=1)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.message.delete()
        except Exception:
            await interaction.response.edit_message(content="*Help panel closed.*", embed=None, view=None)

    @discord.ui.button(label=">", style=discord.ButtonStyle.secondary, row=1)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
        await self.update_view(interaction)

    @discord.ui.button(label=">>", style=discord.ButtonStyle.secondary, row=1)
    async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = self.total_pages - 1
        await self.update_view(interaction)


# ───────────────────── Utility Cog Implementation ─────────────────────

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="joke", description="Get a hilarious Hinglish, Desi, or tech joke!")
    @app_commands.choices(category=[
        app_commands.Choice(name="🎲 Random Surprise (Default)", value="any"),
        app_commands.Choice(name="🎓 Student & College Life", value="student"),
        app_commands.Choice(name="🏠 Desi Family & Parents", value="desi_family"),
        app_commands.Choice(name="💼 Office & Corporate Life", value="corporate"),
        app_commands.Choice(name="🎅 Santa Banta & Pappu", value="classics"),
        app_commands.Choice(name="❤️ Dating & Relationships", value="dating"),
        app_commands.Choice(name="🛵 Daily Desi Life", value="daily_life"),
        app_commands.Choice(name="💻 Tech & Programmer", value="tech")
    ])
    async def joke(self, interaction: discord.Interaction, category: str = "any"):
        joke_data = get_random_joke(category=category)
        embed = build_joke_embed(joke_data, user=interaction.user)
        view = JokeView(category=category, author_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="ping", description="Check Friday's response latency.")
    async def ping(self, interaction: discord.Interaction):
        lat = round(self.bot.latency * 1000)
        await reply_box(
            interaction,
            f"• Response time: `{lat}ms` ✨\n• Friday is running smoothly and ready for you!",
            title="PONG!",
            status="success",
            ephemeral=True
        )

    @app_commands.command(name="serverinfo", description="Display information about the server.")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        created = guild.created_at.strftime("%B %d, %Y")
        owner_mention = guild.owner.mention if guild.owner else "Unknown"

        embed = make_box_embed(
            title=f"SERVER INFO: {guild.name.upper()}",
            description=(
                f"• **Owner:** {owner_mention}\n"
                f"• **Total Members:** `{guild.member_count}`\n"
                f"• **Total Roles:** `{len(guild.roles)}`\n"
                f"• **Created:** `{created}`"
            ),
            status="info",
            footer=f"Server ID: {guild.id}"
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="View all of Friday's commands and features.")
    async def help(self, interaction: discord.Interaction):
        view = HelpView(self.bot, interaction.user)
        embed = view.generate_embed()
        await interaction.response.send_message(embed=embed, view=view)
        try:
            view.message = await interaction.original_response()
        except Exception:
            pass

    @app_commands.command(name="sync", description="Forcefully sync the global slash command list to this server.")
    @app_commands.default_permissions(administrator=True)
    async def sync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        synced = await self.bot.tree.sync()
        await reply_box(
            interaction,
            f"Command tree synced across **{len(synced)}** slash commands.\nPress **Ctrl+R** in your Discord client to reload the command cache.",
            title="SYNC COMPLETE",
            status="success",
            ephemeral=True
        )

    @app_commands.command(name="bot_status", description="Staff Dashboard: View Friday's current security and system status.")
    @app_commands.default_permissions(manage_messages=True)
    async def status_dashboard(self, interaction: discord.Interaction):
        from database import db
        gid = str(interaction.guild.id)

        antinuke = "ACTIVE" if db.antinuke_active.get(gid, True) else "DISABLED"
        whitelist_count = len(db.whitelist.get(gid, []))
        banned_words_count = len(db.banned_words.get(gid, []))
        ignore_channels_count = len(db.ignored_private.get(gid, []))

        privated_count = 0
        for ch in interaction.guild.text_channels:
            if ch.overwrites_for(interaction.guild.default_role).read_messages == False:
                privated_count += 1

        # Tickets
        ticket_settings = db.tickets.get(gid, {})
        panels_count = len(ticket_settings.get("panels", {}))
        active_tickets = len(ticket_settings.get("active_tickets", {}))

        # Announcements
        ann_channel_id = db.announcement_channels.get(gid)
        ann_channel_text = f"<#{ann_channel_id}>" if ann_channel_id else "Not set"

        embed = make_box_embed(
            title="SYSTEM STATUS DASHBOARD",
            description=(
                f"• **Anti-Nuke:** `{antinuke}`\n"
                f"• **Whitelisted Staff:** `{whitelist_count}`\n"
                f"• **Word Filters:** `{banned_words_count}` active\n"
                f"• **Privated Channels:** `{privated_count}`\n"
                f"• **Lockdown Ignored:** `{ignore_channels_count}`\n"
                f"• **Ticket Panels:** `{panels_count}` | Active: `{active_tickets}`\n"
                f"• **Announcement Channel:** {ann_channel_text}\n"
                f"• **Heartbeat Latency:** `{round(self.bot.latency * 1000)}ms`"
            ),
            status="info",
            footer="Friday Operations Center"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Utility(bot))
