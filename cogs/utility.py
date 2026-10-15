import discord
from discord.ext import commands
from discord import app_commands
from hinglish_jokes import get_random_joke, build_joke_embed, JokeView
from response_utils import make_box_embed, reply_box

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
        embed = make_box_embed(
            title="FRIDAY COMMANDS",
            description="Here are all the commands you can use with Friday! 🌸",
            status="info",
            footer=f"Requested by {interaction.user.name}"
        )
        embed.add_field(name="◈ MODERATION", value="`/ban` • `/unban` • `/timeout` • `/untimeout` • `/purge`", inline=False)
        embed.add_field(name="◈ SECURITY", value="`/antinuke_toggle` • `/antinuke_refresh` • `/antinuke_limit`\n`/whitelist_add` • `/whitelist_remove`\n`/anti_abuse` • `/anti_abuse_remove` • `/anti_abuse_list`", inline=False)
        embed.add_field(name="◈ COMMUNITY & LEVELING", value="`/level_setup` • `/rank` • `/leaderboard` • `/reaction_panel` • `/joke`", inline=False)
        embed.add_field(name="◈ MUSIC & AUDIO", value="`/play` (YouTube High-Fidelity) • `/join` • `/leave` • `/skip`\n`/pause` • `/resume` • `/volume` • `/queue` • `/filter` • `/stop`", inline=False)
        embed.add_field(name="◈ MEDIA & PRIVACY", value="`/media` • `/private` • `/unprivate` • `/force_private`\n`/private_category` • `/unprivate_category`", inline=False)
        embed.add_field(name="◈ EXPRESSIONS & UTILITY", value="`/emoji_steal` • `/ping` • `/serverinfo` • `/bot_status` • `/sync`", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="sync", description="Forcefully sync the global slash command list to this server.")
    @app_commands.default_permissions(administrator=True)
    async def sync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.bot.tree.clear_commands(guild=interaction.guild)
        await self.bot.tree.sync(guild=interaction.guild)
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
