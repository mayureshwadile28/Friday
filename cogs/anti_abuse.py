import discord
from discord.ext import commands
from discord import app_commands
import re
from database import db

class AntiAbuse(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="anti_abuse", description="Add bad words to the filter, separated by commas.")
    @app_commands.default_permissions(manage_messages=True)
    async def anti_abuse(self, interaction: discord.Interaction, words: str):
        gid = str(interaction.guild.id)
        if gid not in db.banned_words:
            db.banned_words[gid] = []
            
        new_words = [w.strip().lower() for w in words.split(',') if w.strip()]
        db.banned_words[gid].extend(new_words)
        db.banned_words[gid] = list(set(db.banned_words[gid])) 
        db.save_data()
        
        embed = discord.Embed(
            title="✔ Filter Updated",
            description=f"Successfully added `{', '.join(new_words)}` to the word filter.",
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="anti_abuse_remove", description="Remove a specific word from the filter.")
    @app_commands.default_permissions(manage_messages=True)
    async def anti_abuse_remove(self, interaction: discord.Interaction, word: str):
        gid = str(interaction.guild.id)
        if gid not in db.banned_words or not db.banned_words[gid]:
            embed = discord.Embed(
                title="ℹ Filter Empty",
                description="The word filter is currently empty.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        target_word = word.strip().lower()
        
        if target_word in db.banned_words[gid]:
            db.banned_words[gid].remove(target_word)
            db.save_data()
            embed = discord.Embed(
                title="✔ Filter Updated",
                description=f"Successfully removed `{target_word}` from the word filter.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="✖ Word Not Found",
                description=f"The word `{target_word}` is not currently in the filter.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="anti_abuse_list", description="View all currently banned words in the server's filter.")
    @app_commands.default_permissions(manage_messages=True)
    async def anti_abuse_list(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        word_list = db.banned_words.get(gid, [])
        
        if not word_list:
            embed = discord.Embed(
                title="ℹ Filter Empty",
                description="The anti-abuse filter is currently empty.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        words_formatted = ", ".join(f"`{w}`" for w in word_list)
        embed = discord.Embed(title="✔ Anti-Abuse Word List", description=words_formatted, color=0x2b2d31)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="anti_abuse_whitelist_add", description="Make a user IMMUNE to the word filter.")
    @app_commands.default_permissions(manage_messages=True)
    async def anti_abuse_whitelist_add(self, interaction: discord.Interaction, user: discord.Member):
        gid = str(interaction.guild.id)
        if gid not in db.abuse_whitelist:
            db.abuse_whitelist[gid] = []
            
        if user.id not in db.abuse_whitelist[gid]:
            db.abuse_whitelist[gid].append(user.id)
            db.save_data()
            embed = discord.Embed(
                title="✔ Whitelist Updated",
                description=f"{user.mention} is now immune to the Anti-Abuse word filter.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="ℹ Already Immune",
                description=f"{user.mention} is already immune.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="anti_abuse_whitelist_remove", description="Remove a user's immunity to the word filter.")
    @app_commands.default_permissions(manage_guild=True)
    async def anti_abuse_whitelist_remove(self, interaction: discord.Interaction, user: discord.Member):
        gid = str(interaction.guild.id)
        if gid in db.abuse_whitelist and user.id in db.abuse_whitelist[gid]:
            db.abuse_whitelist[gid].remove(user.id)
            db.save_data()
            embed = discord.Embed(
                title="✔ Whitelist Updated",
                description=f"{user.mention} is no longer immune to the word filter.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="✖ Not Whitelisted",
                description=f"{user.mention} was not on the whitelist.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    def is_immune(self, message: discord.Message) -> bool:
        """Determines if the message author is immune to anti-abuse message deletion and warnings."""
        if not message.guild or not message.author:
            return True
        if message.author.bot:
            return True

        # 1. Server Owner is ALWAYS immune
        if message.author.id == message.guild.owner_id:
            return True

        # 2. Server Administrators & Guild Managers are ALWAYS immune
        perms = getattr(message.author, "guild_permissions", None)
        if perms and (perms.administrator or perms.manage_guild or perms.manage_messages):
            return True

        gid = str(message.guild.id)
        uid_int = message.author.id
        uid_str = str(uid_int)

        # Anti-Abuse Dedicated Whitelist (db.abuse_whitelist)
        abuse_wl = db.abuse_whitelist.get(gid, []) or db.abuse_whitelist.get(int(gid) if gid.isdigit() else 0, [])
        abuse_wl_ids = {str(x) for x in abuse_wl}
        if uid_str in abuse_wl_ids:
            return True

        return False

    @commands.Cog.listener()
    async def on_message(self, message):
        if self.is_immune(message):
            return

        gid = str(message.guild.id)
        word_list = db.banned_words.get(gid, [])
        content_lower = message.content.lower()
        
        triggered_word = None
        for word in word_list:
            if re.search(rf'\b{re.escape(word)}\b', content_lower):
                triggered_word = word
                break
        
        if triggered_word:
            try:
                await message.delete()
                resp_tpl = db.custom_responses.get(gid, {}).get("abuse_warning_msg", "⚠️ {member}, that word is not allowed here.")
                warning = await message.channel.send(resp_tpl.replace("{member}", message.author.mention))
                await warning.delete(delay=5)
                
                log_id = db.server_logs.get(gid, {}).get("audit-abuse")
                if log_id:
                    log_channel = self.bot.get_channel(log_id)
                    if log_channel:
                        embed = discord.Embed(title="🤬 Abuse Word Detected", color=discord.Color.orange())
                        embed.add_field(name="Author", value=message.author.mention, inline=True)
                        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                        embed.add_field(name="Trigger Word", value=f"`{triggered_word}`", inline=False)
                        embed.add_field(name="Full Message", value=message.content, inline=False)
                        embed.set_footer(text=f"Detected on {discord.utils.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')}")
                        await log_channel.send(embed=embed)
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if self.is_immune(after):
            return

        gid = str(after.guild.id)
        word_list = db.banned_words.get(gid, [])
        content_lower = after.content.lower()
        
        triggered_word = None
        for word in word_list:
            if re.search(rf'\b{re.escape(word)}\b', content_lower):
                triggered_word = word
                break
        
        if triggered_word:
            try:
                await after.delete()
                resp_tpl = db.custom_responses.get(gid, {}).get("abuse_edit_warning_msg", "⚠️ {member}, you cannot edit your message to include a banned word.")
                warning = await after.channel.send(resp_tpl.replace("{member}", after.author.mention))
                await warning.delete(delay=5)
                
                log_id = db.server_logs.get(gid, {}).get("audit-abuse")
                if log_id:
                    log_channel = self.bot.get_channel(log_id)
                    if log_channel:
                        embed = discord.Embed(title="🤬 Edited Abuse Word Detected", color=discord.Color.orange())
                        embed.add_field(name="Author", value=after.author.mention, inline=True)
                        embed.add_field(name="Channel", value=after.channel.mention, inline=True)
                        embed.add_field(name="Trigger Word", value=f"`{triggered_word}`", inline=False)
                        embed.add_field(name="Old Message", value=before.content if before.content else "*No text*", inline=False)
                        embed.add_field(name="New Message", value=after.content, inline=False)
                        embed.set_footer(text=f"Detected on {discord.utils.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')}")
                        await log_channel.send(embed=embed)
            except discord.Forbidden:
                pass

async def setup(bot):
    await bot.add_cog(AntiAbuse(bot))
