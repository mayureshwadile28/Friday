import discord
from discord.ext import commands
from discord import app_commands
import time
from database import db
from response_utils import make_box_embed, reply_box

def format_duration(seconds: float) -> str:
    """Formats seconds into human-readable duration like '1h 15m' or '45m'."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m {seconds % 60}s"
    hours = minutes // 60
    rem_min = minutes % 60
    if hours < 24:
        return f"{hours}h {rem_min}m"
    days = hours // 24
    rem_hours = hours % 24
    return f"{days}d {rem_hours}h"

class AFKCog(commands.Cog, name="AFK"):
    """Handles member AFK status, nickname prefixing, mention tracking, and welcome back notifications."""
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="afk", description="Set your AFK status with an optional reason.")
    @app_commands.describe(reason="Why are you stepping away? (e.g. Studying, Lunch, Sleeping)")
    async def afk(self, interaction: discord.Interaction, reason: str = "AFK"):
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)

        if gid not in db.afk_data:
            db.afk_data[gid] = {}

        now = time.time()
        member = interaction.user
        original_nick = member.nick  # None if no custom guild nickname

        nick_changed = False
        display_base = original_nick if original_nick else member.display_name
        new_nick = f"[AFK] {display_base}"[:32]

        # Attempt to change nickname safely
        try:
            if not display_base.startswith("[AFK]"):
                await member.edit(nick=new_nick, reason="Member entered AFK mode")
                nick_changed = True
        except (discord.Forbidden, discord.HTTPException):
            nick_changed = False

        db.afk_data[gid][uid] = {
            "reason": reason,
            "time": now,
            "original_nick": original_nick,
            "nick_changed": nick_changed,
            "mentions": []
        }
        db.save_data()

        status_desc = (
            f"**{member.mention} is now away.** 🌸\n\n"
            f"• **Reason:** {reason}\n"
            f"• I'll save your pings while you're away. Just send a message when you return!"
        )

        embed = make_box_embed(
            title="SEE YOU SOON",
            description=status_desc,
            status="info",
            footer="Friday 🌸"
        )
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)

        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        gid = str(message.guild.id)
        author_id = str(message.author.id)
        afk_dict = getattr(db, "afk_data", {}).get(gid, {})

        # ───────── 1. RETURN DETECTION (Author was AFK) ─────────
        if author_id in afk_dict:
            afk_info = afk_dict.pop(author_id, None)
            db.save_data()

            if afk_info:
                start_time = afk_info.get("time", time.time())
                elapsed = time.time() - start_time
                duration_str = format_duration(elapsed)
                reason = afk_info.get("reason", "AFK")
                original_nick = afk_info.get("original_nick")
                nick_changed = afk_info.get("nick_changed", False)

                # Revert nickname if we altered it
                if nick_changed:
                    try:
                        # If original_nick was None, passing None removes guild nickname
                        await message.author.edit(nick=original_nick, reason="Member returned from AFK")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

                # Compile missed mentions (clean & compact, no message snippets)
                missed_mentions = afk_info.get("mentions", [])
                
                lines = [
                    f"Welcome back {message.author.mention}! Glad to see you again 🌸"
                ]

                if reason and reason.strip().lower() != "afk":
                    lines.append(f"• **Away for:** `{duration_str}` • **Reason:** {reason}")
                else:
                    lines.append(f"• **Away for:** `{duration_str}`")

                if missed_mentions:
                    lines.append(f"\n📬 **Missed Pings ({len(missed_mentions)}):**")
                    current_chan_name = message.channel.name if hasattr(message.channel, "name") else ""
                    # Keep at most last 6 pings for a neat, compact layout
                    for m in missed_mentions[-6:]:
                        m_author = m.get("author_name", "Someone")
                        m_chan = m.get("channel_name", "")
                        m_url = m.get("jump_url", "")
                        jump_part = f" — [Jump to Message]({m_url})" if m_url else ""
                        
                        if m_chan and m_chan != current_chan_name:
                            lines.append(f"• **{m_author}** in #{m_chan}{jump_part}")
                        else:
                            lines.append(f"• **{m_author}**{jump_part}")

                    overflow = len(missed_mentions) - 6
                    if overflow > 0:
                        lines.append(f"*...and {overflow} more*")

                return_desc = "\n".join(lines)

                embed = make_box_embed(
                    title="WELCOME BACK",
                    description=return_desc,
                    status="success",
                    footer="Friday 🌸"
                )
                if message.author.display_avatar:
                    embed.set_thumbnail(url=message.author.display_avatar.url)

                try:
                    await message.reply(embed=embed, mention_author=False)
                except Exception:
                    try:
                        await message.channel.send(embed=embed)
                    except Exception as e:
                        print(f"[AFK] Error sending return message: {e}")

        # ───────── 2. MENTION DETECTION (Checking if mentioned members are AFK) ─────────
        # Extract all mentioned members (excluding the author himself)
        target_members = []
        for user in message.mentions:
            if user.id != message.author.id and not user.bot:
                target_members.append(user)

        # Also check reply author if someone replied to a message without @tagging
        if message.reference and hasattr(message.reference, "resolved") and isinstance(message.reference.resolved, discord.Message):
            ref_author = message.reference.resolved.author
            if ref_author.id != message.author.id and not ref_author.bot:
                if ref_author not in target_members:
                    target_members.append(ref_author)

        if not target_members:
            return

        notified_users = set()
        for target in target_members:
            t_id = str(target.id)
            if t_id in afk_dict and t_id not in notified_users:
                notified_users.add(t_id)
                t_info = afk_dict[t_id]
                afk_time = t_info.get("time", time.time())
                elapsed = time.time() - afk_time
                duration_str = format_duration(elapsed)
                t_reason = t_info.get("reason", "AFK")

                # Record this ping in the target's missed mentions (no message snippet needed)
                mention_entry = {
                    "author_name": message.author.display_name,
                    "author_id": message.author.id,
                    "jump_url": message.jump_url,
                    "channel_name": message.channel.name if hasattr(message.channel, "name") else "chat",
                    "time": time.time()
                }
                t_info.setdefault("mentions", []).append(mention_entry)
                db.save_data()

                # Dispatch AFK notification embed
                desc = (
                    f"**{target.display_name}** is currently away.\n\n"
                    f"• **Reason:** {t_reason}\n"
                    f"• **Away since:** <t:{int(afk_time)}:R> (`{duration_str}` ago)\n\n"
                    f"I've saved your ping and will let them know when they're back! ✨"
                )
                embed = make_box_embed(
                    title="CURRENTLY AWAY",
                    description=desc,
                    status="warning",
                    footer="Friday 🌸"
                )
                if target.display_avatar:
                    embed.set_thumbnail(url=target.display_avatar.url)

                try:
                    await message.reply(embed=embed, mention_author=False)
                except Exception:
                    try:
                        await message.channel.send(embed=embed)
                    except Exception as e:
                        print(f"[AFK] Error notifying mention: {e}")

async def setup(bot):
    await bot.add_cog(AFKCog(bot))
