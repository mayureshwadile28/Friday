import io
import asyncio
from datetime import datetime, timezone
from typing import Optional, Union
import discord
from discord.ext import commands
from discord import app_commands
from hinglish_jokes import get_random_joke, build_joke_embed, JokeView
from response_utils import make_box_embed, reply_box

def extract_dominant_color(image_bytes: bytes) -> int:
    """Extract dominant matching vibrant color from image bytes to style Discord embed border lines."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = img.resize((48, 48), Image.Resampling.LANCZOS)
        quantized = img.quantize(colors=16)
        palette = quantized.getpalette()
        counts = sorted(quantized.getcolors() or [], key=lambda x: x[0], reverse=True)
        for count, idx in counts:
            r = palette[idx * 3]
            g = palette[idx * 3 + 1]
            b = palette[idx * 3 + 2]
            if 35 < (r + g + b) < 710:
                return (r << 16) | (g << 8) | b
        if counts:
            top_idx = counts[0][1]
            r = palette[top_idx * 3]
            g = palette[top_idx * 3 + 1]
            b = palette[top_idx * 3 + 2]
            return (r << 16) | (g << 8) | b
    except Exception:
        pass
    return 0x2dd4bf

# ───────────────────── Help System Data & Components ─────────────────────

HELP_MODULES = [
    {
        "id": "antinuke",
        "name": "Antinuke",
        "emoji": "⛨",
        "desc": "Fastest Antinuke & Core Server Protection",
        "sections": [
            ("Antinuke", ["antinuke_toggle", "antinuke_limit", "antinuke_refresh", "antinuke_sync", "antiraid", "antispam", "security_status", "diagnose"]),
            ("Whitelist", ["whitelist_add", "whitelist_remove"])
        ]
    },
    {
        "id": "antiabuse",
        "name": "Anti-Abuse",
        "emoji": "⚔",
        "desc": "Word Filter & Message Abuse Protection",
        "sections": [
            ("Word Filters", ["anti_abuse", "anti_abuse_remove", "anti_abuse_list"]),
            ("Filter Immunity", ["anti_abuse_whitelist_add", "anti_abuse_whitelist_remove"])
        ]
    },
    {
        "id": "moderation",
        "name": "Moderation",
        "emoji": "⚒",
        "desc": "Member Moderation & Infraction System",
        "sections": [
            ("Member Moderation", ["ban", "unban", "timeout", "untimeout", "purge"]),
            ("Role Management", ["role add", "role remove", "role info", "role list", "role emoji"]),
            ("Infractions", ["warn", "warnings", "clearwarns"])
        ]
    },
    {
        "id": "music",
        "name": "Music",
        "emoji": "♫",
        "desc": "High Quality Audio & Queue Controls",
        "sections": [
            ("Playback", ["play", "pause", "resume", "skip", "stop", "volume"]),
            ("Queue & Sound Effects", ["queue", "shuffle", "filter", "likes", "join", "leave", "soundtest"])
        ]
    },
    {
        "id": "tickets",
        "name": "Ticket",
        "emoji": "⊞",
        "desc": "Interactive Support Ticket System",
        "sections": [
            ("Interactive Panels", ["create_ticket_panel"])
        ]
    },
    {
        "id": "voice",
        "name": "Voice",
        "emoji": "☊",
        "desc": "Temporary Join-to-Create Voice Rooms",
        "sections": [
            ("Hub Setup", ["voice setup", "voice autohub", "voice status"]),
            ("Room Controls", ["voice lock", "voice unlock", "voice hide", "voice unhide", "voice limit", "voice name", "voice kick", "voice claim"])
        ]
    },
    {
        "id": "privacy",
        "name": "Privacy",
        "emoji": "⚿",
        "desc": "Channel & Category Privacy Lockdowns",
        "sections": [
            ("Lockdown Actions", ["private", "unprivate", "force_private"]),
            ("Categories", ["private_category", "unprivate_category"]),
            ("Exemptions", ["ignore_private_add", "ignore_private_remove"])
        ]
    },
    {
        "id": "reactionroles",
        "name": "ReactionRoles",
        "emoji": "✦",
        "desc": "Self-Assignable Role Panels",
        "sections": [
            ("Interactive Panels", ["reaction_panel"])
        ]
    },
    {
        "id": "leveling",
        "name": "Leveling",
        "emoji": "▲",
        "desc": "XP Progression, Ranks & Leaderboards",
        "sections": [
            ("Rank & Progression", ["rank", "leaderboard", "level_setup", "level_mode"])
        ]
    },
    {
        "id": "announcements",
        "name": "Announcements",
        "emoji": "⚑",
        "desc": "Scheduled & Category Broadcast Dispatcher",
        "sections": [
            ("Dispatcher", ["announcement_channel"]),
            ("Quick Broadcast", ["Apps -> Initiate Announcement"])
        ]
    },
    {
        "id": "utility",
        "name": "Utility",
        "emoji": "⚙",
        "desc": "Server Utility & Identity Tools",
        "sections": [
            ("System", ["ping", "serverinfo", "bot_status", "sync", "joke", "afk"]),
            ("Expressions & Media", ["avatar", "emoji_steal", "media"])
        ]
    },
    {
        "id": "welcomer",
        "name": "Welcomer",
        "emoji": "⎆",
        "desc": "Automated Member Welcomes & Canvas Cards",
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
                label="⌂  Home / Overview",
                value="home",
                description="Return to the main overview page",
                default=(current_page == 0)
            )
        ]
        for idx, mod in enumerate(HELP_MODULES):
            options.append(discord.SelectOption(
                label=f"{mod['emoji']}  {mod['name']}",
                value=str(idx + 1),
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
            module_lines = "\n".join([f" `{m['emoji']}`  **{m['name']}** — *{m['desc']}*" for m in HELP_MODULES])
            embed = discord.Embed(
                title="⌂  Friday™ Security & Management",
                description=(
                    "Next-generation Discord infrastructure with instant Anti-Nuke and automated community security.\n\n"
                    "• **Prefix:** `/` (Slash Commands)\n"
                    f"• **Commands Available:** `{TOTAL_COMMANDS}`\n"
                    "• **Navigation:** Select a module from the menu below to view commands.\n\n"
                    "**SYSTEM MODULES**\n"
                    f"{module_lines}"
                ),
                color=0x2b2d31
            )
            embed.set_footer(text=f"Requested by {self.author.name} • Page 1 / {self.total_pages}")
        else:
            mod_idx = self.current_page - 1
            mod = HELP_MODULES[mod_idx]
            sections_text = []
            for sec_name, cmds in mod["sections"]:
                cmd_tags = " ".join([f"`/{c}`" for c in cmds])
                sections_text.append(f"**{sec_name}**\n{cmd_tags}\n")

            embed = discord.Embed(
                title=f"{mod['emoji']}  {mod['name']} Module",
                description=f"*{mod['desc']}*\n\n" + "\n".join(sections_text).strip(),
                color=0x2b2d31
            )
            embed.set_footer(text=f"Requested by {self.author.name} • Page {self.current_page + 1} / {self.total_pages}")

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

    @discord.ui.button(label="✕", style=discord.ButtonStyle.danger, row=1)
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
        for cmd in self.bot.tree.get_commands():
            if cmd.name in ("avatar", "vip"):
                cmd.guild_only = False
            else:
                try:
                    cmd.guild_only = True
                except Exception:
                    pass
        if interaction.guild:
            self.bot.tree.copy_global_to(guild=interaction.guild)
            await self.bot.tree.sync(guild=interaction.guild)
        synced = await self.bot.tree.sync()
        await reply_box(
            interaction,
            f"Command tree synced across **{len(synced)}** slash commands (instantly updated in **{interaction.guild.name if interaction.guild else 'this guild'}**).\nPress **Ctrl+R** in your Discord client to reload the command cache.",
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

    @app_commands.command(name="diagnose", description="Diagnose Friday's permissions, roles, and message deletion capabilities in this channel.")
    @app_commands.default_permissions(manage_guild=True)
    async def diagnose_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        channel = interaction.channel
        me = guild.me or guild.get_member(self.bot.user.id)

        # 1. Guild Permissions
        gp = me.guild_permissions if me else None
        has_admin = gp.administrator if gp else False
        has_manage_msgs_guild = gp.manage_messages if gp else False

        # 2. Channel Permissions
        cp = channel.permissions_for(me) if me and hasattr(channel, "permissions_for") else None
        cp_admin = cp.administrator if cp else False
        cp_manage_msgs = cp.manage_messages if cp else False
        cp_send_msgs = cp.send_messages if cp else False
        cp_view = cp.view_channel if cp else False

        # 3. Roles and hierarchy
        roles_list = [r for r in me.roles if not r.is_default()] if me else []
        roles_str = ", ".join([f"`{r.name}` (pos {r.position})" for r in sorted(roles_list, key=lambda r: r.position, reverse=True)]) or "None"

        # 4. Live Message Deletion Test
        deletion_test_status = "Not Tested"
        try:
            test_msg = await channel.send("🔍 *Friday live diagnostic test... (auto-deleting)*")
            await asyncio.sleep(0.5)
            await test_msg.delete()
            deletion_test_status = "✅ PASSED (Friday can send and delete messages in this channel)"
        except discord.Forbidden as e:
            deletion_test_status = f"❌ FAILED (HTTP 403 Forbidden: {e})"
        except Exception as e:
            deletion_test_status = f"⚠️ FAILED ({type(e).__name__}: {e})"

        # 5. Security Feature Status
        sec_cog = self.bot.get_cog("Security")
        sec_info = "Security Cog not loaded"
        if sec_cog:
            cfg = sec_cog.get_security_config(str(guild.id))
            det = cfg.get("detect", {})
            anti_gif = det.get("anti_gif", {}).get("enabled", False)
            anti_link = det.get("anti_link", {}).get("enabled", False)
            allow_gifs = det.get("anti_link", {}).get("allow_gifs", True)
            sec_info = (
                f"• **Anti-GIF Rule:** `{'ENABLED' if anti_gif else 'DISABLED (Turn ON in Dashboard -> Security)'}`\n"
                f"• **Anti-Link Rule:** `{'ENABLED' if anti_link else 'DISABLED'}`\n"
                f"• **Anti-Link Allows GIFs:** `{'YES' if allow_gifs else 'NO'}`"
            )

        # 6. Server 2FA
        mfa_level = getattr(guild, "mfa_level", "Unknown")
        mfa_text = "⚠️ Enforced (Requires 2FA on Bot Developer account!)" if str(mfa_level) in ("1", "MFALevel.elevated", "elevated") else "Not enforced"

        embed = discord.Embed(
            title=f"🛠️ Friday Diagnostic Report: #{getattr(channel, 'name', 'current-channel')}",
            color=0x2dd4bf if (has_admin and "PASSED" in deletion_test_status) else 0xef4444,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(
            name="🤖 Friday Role Hierarchy",
            value=(
                f"• **Top Role:** `{me.top_role.name if me else 'Unknown'}` (position `{me.top_role.position if me else '?'}`)\n"
                f"• **Assigned Roles:** {roles_str}"
            ),
            inline=False
        )
        embed.add_field(
            name="🛡️ Discord Permissions",
            value=(
                f"• **Guild Administrator:** `{'✅ YES' if has_admin else '❌ NO (Turn ON in Server Settings -> Roles)'}`\n"
                f"• **Guild Manage Messages:** `{'✅ YES' if has_manage_msgs_guild else '❌ NO'}`\n"
                f"• **Channel View Channel:** `{'✅ YES' if cp_view else '❌ NO'}`\n"
                f"• **Channel Send Messages:** `{'✅ YES' if cp_send_msgs else '❌ NO'}`\n"
                f"• **Channel Manage Messages:** `{'✅ YES' if cp_manage_msgs else '❌ NO'}`"
            ),
            inline=False
        )
        embed.add_field(
            name="🧪 Live Message Deletion Test",
            value=deletion_test_status,
            inline=False
        )
        embed.add_field(
            name="⚙️ Security Feature Status",
            value=sec_info,
            inline=False
        )
        embed.add_field(
            name="🔐 Server 2FA Moderation Requirement",
            value=mfa_text,
            inline=False
        )
        has_mod = self.bot.get_cog("Moderation") is not None
        has_gw = self.bot.get_cog("Giveaways") is not None
        cmd_names = [c.name for c in self.bot.tree.get_commands()]
        has_move = "move" in cmd_names
        embed.add_field(
            name="📦 Engine & Cogs Status",
            value=(
                f"• **Moderation Cog (/move, /moveall):** {'✅ Online' if has_mod and has_move else '❌ Offline'}\n"
                f"• **Giveaways Engine (/gsetup, /gcreate):** {'✅ Online (v2 2-Button Wizard)' if has_gw else '❌ Offline'}\n"
                f"• **Total Registered Slash Commands:** `{len(cmd_names)}`"
            ),
            inline=False
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _handle_avatar(self, interaction: discord.Interaction, user: Optional[Union[discord.Member, discord.User]] = None):
        target = user or interaction.user
        await interaction.response.defer()

        # Extract avatar bytes and dominant matching color
        color_int = 0x2dd4bf
        try:
            avatar_bytes = await target.display_avatar.read()
            color_int = extract_dominant_color(avatar_bytes)
        except Exception:
            if hasattr(target, "accent_color") and target.accent_color:
                color_int = target.accent_color.value
            elif hasattr(target, "color") and target.color and target.color.value != 0:
                color_int = target.color.value

        hex_str = hex(color_int)[2:].zfill(6).upper()

        embed = discord.Embed(
            title=f"Avatar of {target.display_name}",
            color=discord.Color(color_int),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_image(url=target.display_avatar.url)
        embed.description = f"• **User:** {target.mention} (`{target.name}`)\n• **Matching Color Line:** `#{hex_str}`"
        
        avatar_type = "Server Avatar" if (isinstance(target, discord.Member) and target.guild_avatar) else "Global Avatar"
        embed.set_footer(
            text=f"{avatar_type} • Requested by {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url
        )

        view = discord.ui.View(timeout=180)
        view.add_item(discord.ui.Button(
            label="Open Full Resolution",
            style=discord.ButtonStyle.link,
            url=target.display_avatar.url,
            emoji="🔍"
        ))

        # If user has a separate global and guild avatar, provide button for both
        if isinstance(target, discord.Member) and target.guild_avatar and target.avatar:
            view.add_item(discord.ui.Button(
                label="Global Avatar",
                style=discord.ButtonStyle.link,
                url=target.avatar.url,
                emoji="🌐"
            ))

        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="avatar", description="View a member's avatar in full resolution with an avatar-matching color line.")
    @app_commands.describe(user="The member or user whose avatar you want to view (defaults to you)")
    async def avatar_cmd(self, interaction: discord.Interaction, user: Optional[Union[discord.Member, discord.User]] = None):
        await self._handle_avatar(interaction, user)

async def setup(bot):
    await bot.add_cog(Utility(bot))
