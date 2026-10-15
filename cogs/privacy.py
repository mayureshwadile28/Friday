import discord
from discord.ext import commands
from discord import app_commands
from database import db

class Privacy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def private_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        choices = []
        for ch in interaction.guild.text_channels:
            if ch.category and ch.category.name == "Friday Security Logs": continue
            if ch.overwrites_for(interaction.guild.default_role).read_messages != False:
                if current.lower() in ch.name.lower():
                    choices.append(app_commands.Choice(name=ch.name, value=str(ch.id)))
                if len(choices) >= 25: break
        return choices

    async def unprivate_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        choices = []
        for ch in interaction.guild.text_channels:
            if ch.category and ch.category.name == "Friday Security Logs": continue
            ow = ch.overwrites_for(interaction.guild.default_role)
            if ow.read_messages == False or ow.send_messages == False:
                if current.lower() in ch.name.lower():
                    choices.append(app_commands.Choice(name=ch.name, value=str(ch.id)))
                if len(choices) >= 25: break
        return choices

    async def private_cat_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        choices = []
        for cat in interaction.guild.categories:
            if cat.name == "Friday Security Logs": continue
            if cat.overwrites_for(interaction.guild.default_role).read_messages != False:
                if current.lower() in cat.name.lower():
                    choices.append(app_commands.Choice(name=cat.name, value=str(cat.id)))
                if len(choices) >= 25: break
        return choices

    async def unprivate_cat_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        choices = []
        for cat in interaction.guild.categories:
            if cat.name == "Friday Security Logs": continue
            if cat.overwrites_for(interaction.guild.default_role).read_messages == False:
                if current.lower() in cat.name.lower():
                    choices.append(app_commands.Choice(name=cat.name, value=str(cat.id)))
                if len(choices) >= 25: break
        return choices

    @app_commands.command(name="private", description="Make a specific channel private.")
    @app_commands.describe(channel_id="Select a channel (only unprivated channels are shown)")
    @app_commands.autocomplete(channel_id=private_autocomplete)
    @app_commands.default_permissions(manage_channels=True)
    async def private_channel(self, interaction: discord.Interaction, channel_id: str = None):
        if channel_id:
            try: target = interaction.guild.get_channel(int(channel_id))
            except ValueError: target = None
            if not target:
                await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
                return
        else:
            target = interaction.channel
            
        await target.set_permissions(interaction.guild.default_role, read_messages=False)
        await interaction.response.send_message(f"🔒 {target.mention} is now private.")

    @app_commands.command(name="unprivate", description="Unprivate a specific channel or ALL channels.")
    @app_commands.describe(channel_id="Select a channel (only privated channels are shown)", all_channels="Set to True to unprivate ALL text channels")
    @app_commands.autocomplete(channel_id=unprivate_autocomplete)
    @app_commands.default_permissions(manage_channels=True)
    async def unprivate_channel(self, interaction: discord.Interaction, channel_id: str = None, all_channels: bool = False):
        await interaction.response.defer()
        if all_channels:
            count = 0
            for ch in interaction.guild.text_channels:
                if ch.category and ch.category.name == "Friday Security Logs":
                    continue
                overwrites = ch.overwrites_for(interaction.guild.default_role)
                if overwrites.read_messages is not None or overwrites.send_messages is not None:
                    await ch.set_permissions(interaction.guild.default_role, read_messages=None, send_messages=None)
                    count += 1
            db.lockdown_active[str(interaction.guild.id)] = False
            db.save_data()
            gid = str(interaction.guild.id)
            resp_tpl = db.custom_responses.get(gid, {}).get("lockdown_lifted", "🔓 Successfully unprivated and unlocked {count} channels.")
            await interaction.followup.send(resp_tpl.replace("{count}", str(count)))
        else:
            if channel_id:
                try: target = interaction.guild.get_channel(int(channel_id))
                except ValueError: target = None
                if not target:
                    await interaction.followup.send("❌ Channel not found.", ephemeral=True)
                    return
            else:
                target = interaction.channel
                
            if target.category and target.category.name == "Friday Security Logs":
                await interaction.followup.send("❌ Security Alert: Channels in the Friday Security Logs category must remain private.")
                return
            await target.set_permissions(interaction.guild.default_role, read_messages=None, send_messages=None)
            await interaction.followup.send(f"🔓 {target.mention} is no longer private (and unlocked if it was read-only).")

    @app_commands.command(name="ignore_private_add", description="Add a channel to the ignore list (won't be affected by force private).")
    @app_commands.default_permissions(manage_channels=True)
    async def ignore_private_add(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        if gid not in db.ignored_private:
            db.ignored_private[gid] = []
        if channel.id not in db.ignored_private[gid]:
            db.ignored_private[gid].append(channel.id)
            db.save_data()
            embed = discord.Embed(
                title="✔ Channel Ignored",
                description=f"{channel.mention} added to the privacy ignore list.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="ℹ Channel Ignored",
                description=f"{channel.mention} is already in the ignore list.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ignore_private_remove", description="Remove a channel from the ignore list.")
    @app_commands.default_permissions(manage_channels=True)
    async def ignore_private_remove(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        if gid in db.ignored_private and channel.id in db.ignored_private[gid]:
            db.ignored_private[gid].remove(channel.id)
            db.save_data()
            embed = discord.Embed(
                title="✔ Channel Unignored",
                description=f"{channel.mention} removed from the privacy ignore list.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="ℹ Channel Not Ignored",
                description=f"{channel.mention} is not in the ignore list.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="force_private", description="Make ALL channels private EXCEPT those in the ignore list.")
    @app_commands.default_permissions(manage_channels=True)
    async def force_private(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        ignore_list = db.ignored_private.get(gid, [])
        
        if not ignore_list:
            embed = discord.Embed(
                title="✖ Action Blocked",
                description="Cannot execute force private! You must have at least 1 channel in the ignore list (use `/ignore_private_add`) so members have somewhere to go.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        await interaction.response.defer()
        ignored_count = 0
        privated_count = 0
        for ch in interaction.guild.text_channels:
            if ch.id in ignore_list:
                await ch.set_permissions(interaction.guild.default_role, read_messages=True, send_messages=False)
                ignored_count += 1
            else:
                if ch.overwrites_for(interaction.guild.default_role).read_messages != False:
                    await ch.set_permissions(interaction.guild.default_role, read_messages=False)
                    privated_count += 1
                    
        db.lockdown_active[gid] = True
        db.save_data()
        resp_tpl = db.custom_responses.get(gid, {}).get("lockdown_initiated", "🔒 **LOCKDOWN INITIATED:** {privated} channels privated. {ignored} ignored channels are now Read-Only for members.")
        await interaction.followup.send(resp_tpl.replace("{privated}", str(privated_count)).replace("{ignored}", str(ignored_count)))

    @app_commands.command(name="private_category", description="Make an entire category and its channels private.")
    @app_commands.describe(category_id="Select a category (only unprivated categories are shown)")
    @app_commands.autocomplete(category_id=private_cat_autocomplete)
    @app_commands.default_permissions(manage_channels=True)
    async def private_category(self, interaction: discord.Interaction, category_id: str):
        try: category = interaction.guild.get_channel(int(category_id))
        except ValueError: category = None
        
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("❌ Category not found.", ephemeral=True)
            return
            
        await interaction.response.defer()
        await category.set_permissions(interaction.guild.default_role, read_messages=False)
        count = 0
        for ch in category.channels:
            await ch.set_permissions(interaction.guild.default_role, read_messages=False)
            count += 1
        await interaction.followup.send(f"🔒 **{category.name}** and its {count} channels are now private.")

    @app_commands.command(name="unprivate_category", description="Unprivate an entire category and its channels.")
    @app_commands.describe(category_id="Select a category (only privated categories are shown)")
    @app_commands.autocomplete(category_id=unprivate_cat_autocomplete)
    @app_commands.default_permissions(manage_channels=True)
    async def unprivate_category(self, interaction: discord.Interaction, category_id: str):
        try: category = interaction.guild.get_channel(int(category_id))
        except ValueError: category = None
        
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("❌ Category not found.", ephemeral=True)
            return
            
        if category.name == "Friday Security Logs":
            await interaction.response.send_message("❌ Security Alert: The Friday Security Logs category must remain private.", ephemeral=True)
            return
            
        await interaction.response.defer()
        await category.set_permissions(interaction.guild.default_role, read_messages=None, send_messages=None)
        count = 0
        for ch in category.channels:
            await ch.set_permissions(interaction.guild.default_role, read_messages=None, send_messages=None)
            count += 1
        await interaction.followup.send(f"🔓 **{category.name}** and its {count} channels are no longer private (and unlocked).")

async def setup(bot):
    await bot.add_cog(Privacy(bot))
