import discord
from discord.ext import commands
from discord import app_commands
import time
import random
from easy_pil import Editor, load_image_async, Font, Canvas
from database import db

class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.xp_cooldowns = {}

    def get_xp_requirement(self, level):
        return 100 * (level + 1)

    @app_commands.command(name="level_setup", description="Activate leveling and set the channel for Level Up updates.")
    @app_commands.default_permissions(manage_channels=True)
    async def level_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        db.level_channels[gid] = str(channel.id)
        db.save_data()
        await interaction.response.send_message(f"✅ Leveling system activated! Updates will now be posted in {channel.mention}.", ephemeral=True)

    @app_commands.command(name="rank", description="Check your current Level and XP.")
    async def rank(self, interaction: discord.Interaction, user: discord.Member = None):
        await interaction.response.defer() 
        user = user or interaction.user
        gid = str(interaction.guild.id)
        uid = str(user.id)
        
        if gid not in db.xp_data or uid not in db.xp_data[gid]:
            await interaction.followup.send(f"{user.display_name} has no XP yet! Send some messages first.")
            return

        user_stats = db.xp_data[gid][uid]
        sorted_users = sorted(db.xp_data[gid].items(), key=lambda item: (item[1]['level'], item[1]['xp']), reverse=True)
        rank_pos = [i[0] for i in sorted_users].index(uid) + 1
        
        current_xp = user_stats["xp"]
        current_level = user_stats["level"]
        next_xp = self.get_xp_requirement(current_level)
        percentage = (current_xp / next_xp) * 100

        background = Editor(Canvas((900, 300), color="#1e1f22"))
        try:
            profile_image = await load_image_async(str(user.display_avatar.url))
            profile = Editor(profile_image).resize((200, 200)).circle_image()
            background.paste(profile, (50, 50))
        except:
            pass 

        big_font = Font.poppins(variant="bold", size=60)
        small_font = Font.poppins(variant="regular", size=40)

        background.text((300, 50), str(user.display_name), font=big_font, color="#ffffff")
        background.text((300, 150), f"Level: {current_level}   Rank: #{rank_pos}", font=small_font, color="#40e0d0")
        background.text((650, 150), f"{current_xp} / {next_xp} XP", font=small_font, color="#ffffff")

        background.bar((300, 220), max_width=550, height=40, percentage=100, color="#2b2d31", radius=20)
        background.bar((300, 220), max_width=550, height=40, percentage=percentage, color="#40e0d0", radius=20)

        file = discord.File(fp=background.image_bytes, filename="rankcard.png")
        await interaction.followup.send(file=file)

    @app_commands.command(name="leaderboard", description="View the top 10 most active members.")
    async def leaderboard(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        if gid not in db.xp_data or not db.xp_data[gid]:
            await interaction.response.send_message("No one has earned any XP yet!")
            return

        sorted_users = sorted(db.xp_data[gid].items(), key=lambda item: (item[1]['level'], item[1]['xp']), reverse=True)[:10]
        
        embed = discord.Embed(title="🏆 Server Leaderboard", color=discord.Color.gold())
        for index, (uid, data) in enumerate(sorted_users, start=1):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"Unknown User ({uid})"
            embed.add_field(name=f"#{index} - {name}", value=f"Level: **{data['level']}** | XP: **{data['xp']}**", inline=False)
            
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="level_mode", description="Configure whether Level Up updates use text, image card, or both.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Text Message Only", value="text"),
        app_commands.Choice(name="Image Card Only", value="image"),
        app_commands.Choice(name="Both (Text + Image Card)", value="both")
    ])
    @app_commands.default_permissions(manage_channels=True)
    async def level_mode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        gid = str(interaction.guild.id)
        db.level_modes[gid] = mode.value
        db.save_data()
        await interaction.response.send_message(f"✅ Level Up notification mode set to **{mode.name}**.", ephemeral=True)

    async def generate_levelup_card(self, member: discord.Member, old_level: int, new_level: int):
        """Generate a sleek, futuristic Level-Up milestone image card."""
        width, height = 900, 320
        card = Editor(Canvas((width, height), color="#121316"))
        
        # Top gradient aesthetic bar
        card.bar((0, 0), max_width=900, height=8, percentage=100, color="#5865f2")
        
        try:
            avatar_img = await load_image_async(str(member.display_avatar.url))
            avatar = Editor(avatar_img).resize((180, 180)).circle_image()
            ring = Editor(Canvas((196, 196), color="#5865f2")).circle_image()
            card.paste(ring, (42, 62))
            card.paste(avatar, (50, 70))
        except Exception:
            pass

        font_title = Font.poppins(variant="bold", size=42)
        font_sub = Font.poppins(variant="bold", size=28)
        font_small = Font.poppins(variant="regular", size=24)
        font_badge = Font.poppins(variant="bold", size=32)

        card.text((270, 75), "LEVEL UP!", font=font_title, color="#5865f2")
        card.text((270, 135), member.display_name[:20], font=font_sub, color="#ffffff")
        card.text((270, 185), "Server Activity Milestone", font=font_small, color="#949ba4")
        
        # Milestone Level Progress Pill
        card.bar((270, 230), max_width=580, height=50, percentage=100, color="#232428", radius=12)
        card.text((300, 240), f"Level {old_level}  ->", font=font_small, color="#b5bac1")
        card.text((430, 236), f"LEVEL {new_level}", font=font_badge, color="#40e0d0")
        
        return discord.File(fp=card.image_bytes, filename=f"levelup-{member.id}.png")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot: return

        gid = str(message.guild.id)
        uid = str(message.author.id)
        
        now = time.time()
        if uid not in self.xp_cooldowns or (now - self.xp_cooldowns[uid]) >= 60:
            if gid not in db.xp_data: db.xp_data[gid] = {}
            if uid not in db.xp_data[gid]: db.xp_data[gid][uid] = {"xp": 0, "level": 0}

            gained_xp = random.randint(15, 40)
            db.xp_data[gid][uid]["xp"] += gained_xp
            self.xp_cooldowns[uid] = now
            
            current_xp = db.xp_data[gid][uid]["xp"]
            current_level = db.xp_data[gid][uid]["level"]
            required_xp = self.get_xp_requirement(current_level)

            if current_xp >= required_xp:
                old_lvl = current_level
                db.xp_data[gid][uid]["level"] += 1
                db.xp_data[gid][uid]["xp"] = current_xp - required_xp 
                new_level = db.xp_data[gid][uid]["level"]
                db.save_data()

                channel_id = db.level_channels.get(gid)
                if channel_id:
                    try:
                        notif_channel = self.bot.get_channel(int(channel_id))
                    except (ValueError, TypeError):
                        notif_channel = None
                    if notif_channel:
                        from emoji_utils import replace_plain_emojis
                        template = db.custom_responses.get(gid, {}).get("level_up_msg") or db.level_messages.get(gid, "🎉 Congratulations {user}! You advanced to **Level {level}**!")
                        level_msg = template.replace("{user}", message.author.mention).replace("{level}", str(new_level))
                        level_msg = replace_plain_emojis(level_msg, self.bot, guild=message.guild)
                        
                        mode = db.level_modes.get(gid, "both")
                        try:
                            if mode == "text":
                                await notif_channel.send(level_msg)
                            elif mode == "image":
                                card_file = await self.generate_levelup_card(message.author, old_lvl, new_level)
                                await notif_channel.send(file=card_file)
                            else: # "both"
                                card_file = await self.generate_levelup_card(message.author, old_lvl, new_level)
                                await notif_channel.send(content=level_msg, file=card_file)
                        except Exception as e:
                            # Fallback in case image generation encounters an issue
                            try:
                                await notif_channel.send(level_msg)
                            except Exception:
                                pass
            else:
                db.save_data()

async def setup(bot):
    await bot.add_cog(Leveling(bot))
