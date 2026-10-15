import discord
from discord.ext import commands
from discord import app_commands
import re
from database import db

class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="reaction_panel", description="Create an interactive role assignment panel.")
    @app_commands.describe(
        channel="Where to post the panel", title="Title of the panel", description="Text above the roles",
        role1="First Role to assign", emoji1="Emoji for Role 1",
        role2="Second Role to assign", emoji2="Emoji for Role 2",
        role3="Third Role to assign", emoji3="Emoji for Role 3"
    )
    @app_commands.default_permissions(manage_roles=True)
    async def reaction_panel(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str,
        role1: discord.Role, emoji1: str, role2: discord.Role = None, emoji2: str = None, role3: discord.Role = None, emoji3: str = None
    ):
        await interaction.response.defer(ephemeral=True)
        
        bot_role = interaction.guild.me.top_role
        for role in [role1, role2, role3]:
            if role and role >= bot_role:
                await interaction.followup.send(f"❌ Error: My role must be physically higher than {role.name} to assign it.")
                return

        def parse_emoji(input_str):
            if not input_str: return None
            input_str = input_str.strip()
            match = re.match(r'<(a?):([a-zA-Z0-9_]+):([0-9]+)>', input_str)
            if match:
                return discord.PartialEmoji(name=match.group(2), id=int(match.group(3)), animated=bool(match.group(1)))
            clean_name = input_str.strip(':')
            for e in interaction.guild.emojis:
                if e.name == clean_name:
                    return e 
            return input_str

        e1 = parse_emoji(emoji1)
        e2 = parse_emoji(emoji2)
        e3 = parse_emoji(emoji3)

        roles_setup = []
        if role1 and e1: roles_setup.append((role1, e1))
        if role2 and e2: roles_setup.append((role2, e2))
        if role3 and e3: roles_setup.append((role3, e3))
        
        if not roles_setup:
            await interaction.followup.send("❌ Error: You must provide at least one valid role and emoji pair.")
            return

        embed = discord.Embed(title=title, description=description, color=discord.Color.teal())
        panel_text = ""
        for role, emoji in roles_setup:
            panel_text += f"{str(emoji)} - {role.mention}\n\n"
            
        embed.add_field(name="Available Roles", value=panel_text, inline=False)
        embed.set_footer(text="React below to claim your roles!")

        try:
            msg = await channel.send(embed=embed)
            msg_id = str(msg.id)
            db.reaction_roles[msg_id] = {}
            
            for role, emoji_obj in roles_setup:
                await msg.add_reaction(emoji_obj) 
                db.reaction_roles[msg_id][str(emoji_obj)] = role.id
                
            db.save_data()
            await interaction.followup.send(f"✅ Reaction panel deployed successfully in {channel.mention}.")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ Error: I lack permissions to send messages or add reactions in that channel.")
        except discord.HTTPException:
            if 'msg' in locals(): await msg.delete() 
            await interaction.followup.send("❌ Error: One or more emojis are invalid. Ensure they belong to this server.")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.member.bot: return
            
        msg_id = str(payload.message_id)
        if msg_id in db.reaction_roles:
            emoji_key = str(payload.emoji)
            role_id = db.reaction_roles[msg_id].get(emoji_key)
            
            if role_id:
                guild = self.bot.get_guild(payload.guild_id)
                role = guild.get_role(role_id)
                if role:
                    try:
                        await payload.member.add_roles(role)
                    except discord.Forbidden:
                        pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        msg_id = str(payload.message_id)
        if msg_id in db.reaction_roles:
            emoji_key = str(payload.emoji)
            role_id = db.reaction_roles[msg_id].get(emoji_key)
            
            if role_id:
                guild = self.bot.get_guild(payload.guild_id)
                role = guild.get_role(role_id)
                member = guild.get_member(payload.user_id)
                
                if role and member and not member.bot:
                    try:
                        await member.remove_roles(role)
                    except discord.Forbidden:
                        pass

async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
