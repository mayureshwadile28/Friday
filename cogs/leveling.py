import discord
from discord.ext import commands
from discord import app_commands
import time
import random
import io
import unicodedata
from PIL import Image, ImageDraw
from easy_pil import Font
from database import db

def clean_display_name(name: str, max_len: int = 22) -> str:
    """Sanitizes user display names into guaranteed printable ASCII characters (eliminates tofu boxes)."""
    if not name:
        return "Unknown"
    norm = unicodedata.normalize('NFKD', str(name))
    cleaned = "".join(ch for ch in norm if 32 <= ord(ch) <= 126 and ch not in "`*~_<>|\\")
    cleaned = cleaned.strip(" -_#|•·~+=[]{}()<>/")
    return cleaned[:max_len] if cleaned else "User"

def draw_rounded_rect(draw, bbox, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)

class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.xp_cooldowns = {}

    def get_xp_requirement(self, level: int) -> int:
        """
        Standard balanced XP formula (Mee6/Arcane style):
        XP required for level L -> L+1: 5*(L^2) + 50*L + 100
        Level 0 -> 100 XP (~5 msgs)
        Level 1 -> 155 XP (~8 msgs)
        Level 2 -> 220 XP (~11 msgs)
        Level 3 -> 295 XP (~15 msgs)
        """
        return int(5 * (level ** 2) + 50 * level + 100)

    @app_commands.command(name="level_setup", description="Activate leveling and set the channel for Level Up updates.")
    @app_commands.default_permissions(manage_channels=True)
    async def level_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        db.level_channels[gid] = str(channel.id)
        db.save_data()
        await interaction.response.send_message(f"✅ Leveling system activated! Updates will now be posted in {channel.mention}.", ephemeral=True)

    @app_commands.command(name="rank", description="Check your current Level, XP, and progression card.")
    async def rank(self, interaction: discord.Interaction, user: discord.Member = None):
        await interaction.response.defer() 
        user = user or interaction.user
        gid = str(interaction.guild.id)
        uid = str(user.id)
        
        if gid not in db.xp_data or uid not in db.xp_data[gid]:
            await interaction.followup.send(f"{clean_display_name(user.display_name)} has no XP recorded yet! Send some messages to start leveling up.")
            return

        user_stats = db.xp_data[gid][uid]
        sorted_users = sorted(db.xp_data[gid].items(), key=lambda item: (item[1]['level'], item[1]['xp']), reverse=True)
        rank_pos = [i[0] for i in sorted_users].index(uid) + 1
        
        current_xp = user_stats["xp"]
        current_level = user_stats["level"]
        next_xp = self.get_xp_requirement(current_level)
        percentage = min(100.0, max(2.0, (current_xp / max(1, next_xp)) * 100.0))

        # Check total messages from Activity cog DB if loaded
        total_messages = 0
        voice_str = "0m"
        act_cog = self.bot.get_cog("Activity")
        if act_cog:
            try:
                stats = act_cog.get_member_stats(interaction.guild.id, user.id)
                total_messages = stats.get("lifetime", 0)
                voice_str = act_cog.format_duration(stats.get("voice_lifetime", 0))
            except Exception:
                pass

        card_file = await self.generate_rank_card(
            user=user,
            rank_pos=rank_pos,
            total_members=len(sorted_users),
            current_level=current_level,
            current_xp=current_xp,
            next_xp=next_xp,
            percentage=percentage,
            total_messages=total_messages,
            voice_str=voice_str
        )
        await interaction.followup.send(file=card_file)

    async def generate_rank_card(
        self,
        user: discord.Member,
        rank_pos: int,
        total_members: int,
        current_level: int,
        current_xp: int,
        next_xp: int,
        percentage: float,
        total_messages: int = 0,
        voice_str: str = "0m"
    ) -> discord.File:
        """Renders high-resolution 960x340 dark SaaS rank card."""
        W, H = 960, 340
        img = Image.new("RGBA", (W, H), (19, 20, 23, 255))
        draw = ImageDraw.Draw(img)

        # Outer Container
        draw_rounded_rect(draw, (12, 12, W - 12, H - 12), radius=24, fill=(28, 30, 36, 255), outline=(42, 45, 54, 255), width=2)

        font_title = Font.poppins(variant="bold", size=26)
        font_sub = Font.poppins(variant="regular", size=13)
        font_badge = Font.poppins(variant="bold", size=12)
        font_xp_num = Font.poppins(variant="bold", size=15)
        font_stat_val = Font.poppins(variant="bold", size=16)
        font_stat_lbl = Font.poppins(variant="bold", size=10)

        # Avatar on left (130x130)
        av_x, av_y, av_size = 46, 50, 130
        av_drawn = False
        try:
            if user.display_avatar:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(str(user.display_avatar.url), timeout=aiohttp.ClientTimeout(total=4)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            av_raw = Image.open(io.BytesIO(data)).convert("RGBA").resize((av_size, av_size), Image.Resampling.LANCZOS)
                            mask = Image.new("L", (av_size, av_size), 0)
                            mask_draw = ImageDraw.Draw(mask)
                            mask_draw.ellipse((0, 0, av_size, av_size), fill=255)
                            img.paste(av_raw, (av_x, av_y), mask)
                            draw.ellipse((av_x, av_y, av_x + av_size, av_y + av_size), outline=(129, 140, 248, 255), width=3)
                            av_drawn = True
        except Exception:
            pass

        if not av_drawn:
            draw.ellipse((av_x, av_y, av_x + av_size, av_y + av_size), fill=(88, 101, 242, 255), outline=(129, 140, 248, 255), width=3)
            c_letter = clean_display_name(user.display_name)[0].upper()
            draw.text((av_x + 44, av_y + 36), c_letter, font=Font.poppins(variant="bold", size=56), fill=(255, 255, 255, 255))

        # Member Info
        text_x = 206
        draw.text((text_x, 48), clean_display_name(user.display_name, max_len=20), font=font_title, fill=(255, 255, 255, 255))
        joined_str = user.joined_at.strftime("%B %d, %Y") if user.joined_at else "Unknown"
        draw.text((text_x, 84), f"@{clean_display_name(user.name, max_len=16)} • Joined {joined_str}", font=font_sub, fill=(142, 146, 155, 255))

        # Top-right Badges
        top_role = user.top_role.name if (user.top_role and user.top_role.name != "@everyone") else "Member"
        badges = [
            (f"RANK #{rank_pos}", (245, 158, 11) if rank_pos <= 3 else (150, 155, 166)),
            (f"LEVEL {current_level}", (129, 140, 248)),
            (clean_display_name(top_role, max_len=14), (56, 189, 248))
        ]
        bx = W - 46
        for b_text, b_col in reversed(badges):
            bbox = font_badge.getbbox(b_text)
            bw = (bbox[2] - bbox[0]) + 22
            bpx = bx - bw
            draw_rounded_rect(draw, (bpx, 50, bpx + bw, 80), radius=12, fill=(38, 41, 50, 255), outline=b_col + (180,), width=1)
            draw.text((bpx + 11, 58), b_text, font=font_badge, fill=b_col + (255,))
            bx = bpx - 10

        # XP Progress Bar Section
        bar_x = text_x
        bar_y = 132
        bar_w = W - 46 - bar_x
        bar_h = 24

        draw.text((bar_x, 110), "EXP PROGRESSION", font=font_stat_lbl, fill=(142, 146, 155, 255))
        xp_str = f"{current_xp:,} / {next_xp:,} XP ({percentage:.1f}%)"
        xb = font_xp_num.getbbox(xp_str)
        draw.text((bar_x + bar_w - (xb[2] - xb[0]), 108), xp_str, font=font_xp_num, fill=(255, 255, 255, 255))

        draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=12, fill=(24, 26, 32, 255))
        fill_w = int(bar_w * (percentage / 100.0))
        if fill_w > 0:
            draw_rounded_rect(draw, (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=12, fill=(129, 140, 248, 255))

        # Bottom Telemetry Cards (3 sub-cards)
        stat_y = 196
        stat_h = 96
        sw = (bar_w - 24) // 3
        stat_items = [
            ("TOTAL MESSAGES", f"{total_messages:,} msgs", "Recorded chat volume"),
            ("VOICE DURATION", voice_str, "Total recorded voice time"),
            ("SERVER STANDING", f"Top {max(1, round((rank_pos / max(1, total_members)) * 100))}%", f"Rank #{rank_pos} of {total_members}")
        ]
        for idx, (lbl, val, sub) in enumerate(stat_items):
            sx = bar_x + idx * (sw + 12)
            draw_rounded_rect(draw, (sx, stat_y, sx + sw, stat_y + stat_h), radius=14, fill=(35, 38, 46, 255), outline=(48, 52, 63, 255), width=1)
            draw.text((sx + 16, stat_y + 14), lbl, font=font_stat_lbl, fill=(140, 145, 156, 255))
            draw.text((sx + 16, stat_y + 34), val, font=font_stat_val, fill=(255, 255, 255, 255))
            draw.text((sx + 16, stat_y + 64), sub, font=font_sub, fill=(120, 125, 136, 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return discord.File(fp=buf, filename=f"rankcard_{user.id}.png")

    @app_commands.command(name="leaderboard", description="View the top 10 most active members by XP.")
    async def leaderboard(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        if gid not in db.xp_data or not db.xp_data[gid]:
            await interaction.response.send_message("No one has earned any XP yet!")
            return

        sorted_users = sorted(db.xp_data[gid].items(), key=lambda item: (item[1]['level'], item[1]['xp']), reverse=True)[:10]
        
        embed = discord.Embed(title="Server XP Leaderboard", color=discord.Color.gold())
        for index, (uid, data) in enumerate(sorted_users, start=1):
            member = interaction.guild.get_member(int(uid))
            name = clean_display_name(member.display_name if member else f"User {uid[-4:]}")
            embed.add_field(name=f"#{index} - {name}", value=f"Level: **{data['level']}** | XP: **{data['xp']:,}**", inline=False)
            
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

    async def generate_levelup_card(self, member: discord.Member, old_level: int, new_level: int) -> discord.File:
        """Generate a sleek Level-Up milestone image card without tofu boxes."""
        W, H = 900, 320
        img = Image.new("RGBA", (W, H), (18, 19, 22, 255))
        draw = ImageDraw.Draw(img)

        # Top gradient line
        draw_rounded_rect(draw, (0, 0, W, 8), radius=0, fill=(88, 101, 242, 255))
        draw_rounded_rect(draw, (12, 12, W - 12, H - 12), radius=22, fill=(28, 30, 36, 255), outline=(42, 45, 54, 255), width=2)

        # Avatar
        av_x, av_y, av_size = 50, 70, 180
        av_drawn = False
        try:
            if member.display_avatar:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(str(member.display_avatar.url), timeout=aiohttp.ClientTimeout(total=4)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            av_raw = Image.open(io.BytesIO(data)).convert("RGBA").resize((av_size, av_size), Image.Resampling.LANCZOS)
                            mask = Image.new("L", (av_size, av_size), 0)
                            mask_draw = ImageDraw.Draw(mask)
                            mask_draw.ellipse((0, 0, av_size, av_size), fill=255)
                            img.paste(av_raw, (av_x, av_y), mask)
                            draw.ellipse((av_x, av_y, av_x + av_size, av_y + av_size), outline=(88, 101, 242, 255), width=4)
                            av_drawn = True
        except Exception:
            pass

        if not av_drawn:
            draw.ellipse((av_x, av_y, av_x + av_size, av_y + av_size), fill=(88, 101, 242, 255))
            c_letter = clean_display_name(member.display_name)[0].upper()
            draw.text((av_x + 60, av_y + 45), c_letter, font=Font.poppins(variant="bold", size=70), fill=(255, 255, 255, 255))

        font_title = Font.poppins(variant="bold", size=42)
        font_sub = Font.poppins(variant="bold", size=26)
        font_small = Font.poppins(variant="regular", size=22)
        font_badge = Font.poppins(variant="bold", size=30)

        draw.text((270, 70), "LEVEL UP!", font=font_title, fill=(88, 101, 242, 255))
        draw.text((270, 130), clean_display_name(member.display_name, max_len=20), font=font_sub, fill=(255, 255, 255, 255))
        draw.text((270, 175), "Server Activity Milestone", font=font_small, fill=(148, 155, 164, 255))

        # Milestone Level Pill
        draw_rounded_rect(draw, (270, 225, 850, 275), radius=12, fill=(35, 36, 40, 255))
        draw.text((300, 236), f"Level {old_level}  ->", font=font_small, fill=(181, 186, 193, 255))
        draw.text((430, 232), f"LEVEL {new_level}", font=font_badge, fill=(56, 189, 248, 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return discord.File(fp=buf, filename=f"levelup-{member.id}.png")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot: return

        gid = str(message.guild.id)
        uid = str(message.author.id)
        
        now = time.time()
        if uid not in self.xp_cooldowns or (now - self.xp_cooldowns[uid]) >= 60:
            if gid not in db.xp_data: db.xp_data[gid] = {}
            if uid not in db.xp_data[gid]: db.xp_data[gid][uid] = {"xp": 0, "level": 0}

            gained_xp = random.randint(15, 25)
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
                            try:
                                await notif_channel.send(level_msg)
                            except Exception:
                                pass
            else:
                db.save_data()

async def setup(bot):
    await bot.add_cog(Leveling(bot))
