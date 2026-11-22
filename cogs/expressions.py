import discord
from discord.ext import commands
from discord import app_commands
import re
import aiohttp
import io
import os
import json
import random
import uuid
import time
import traceback
from typing import Optional
from PIL import Image
from database import db
from response_utils import make_box_embed, reply_box

PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GREETINGS_FILE = os.path.join(PARENT_DIR, "data", "greetings.json")

def load_greetings():
    try:
        if os.path.exists(GREETINGS_FILE):
            with open(GREETINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return data
    except Exception as e:
        print(f"[Expressions] Warning loading greetings: {e}")
    return [
        "Heyy {user}! ✨", "Hii {user}~ 🌸", "Helloo {user}! 🎀",
        "Hey {user}, nice to see you! 💫", "Hiii {user}! Hope your day is super sweet 🌸",
        "Heyy {user}! I'm right here~ 🎧", "Hii {user}! Good to see you around ✨",
        "Oh hey {user}! 🤍", "Hello {user}! Hope you have the best day 🌷",
        "Heyy {user}! Right here with the best tunes 🎧"
    ]

GREETINGS = load_greetings()

def sanitize_emoji_name(raw_name: str, fallback_id: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_]', '', raw_name)
    if len(cleaned) < 2:
        cleaned = f"emoji_{cleaned}" if cleaned else f"emoji_{str(fallback_id)[-4:]}"
    if len(cleaned) > 32:
        cleaned = cleaned[:32]
    return cleaned

def extract_emojis_from_string(text: str):
    results = []
    seen = set()

    # 1. Match standard Discord formatted custom emojis: <:name:id> or <a:name:id>
    for m in re.finditer(r'<(a?):([a-zA-Z0-9_]+):([0-9]+)>', text):
        is_animated = bool(m.group(1))
        raw_name = m.group(2)
        emoji_id = m.group(3)
        if emoji_id not in seen:
            seen.add(emoji_id)
            name = sanitize_emoji_name(raw_name, emoji_id)
            results.append({
                "animated": is_animated,
                "name": name,
                "id": emoji_id,
                "url": f"https://cdn.discordapp.com/emojis/{emoji_id}.{'gif' if is_animated else 'png'}"
            })

    # 2. Match Discord CDN URLs: https://cdn.discordapp.com/emojis/<id>.<ext> or media.discordapp.net
    cdn_matches = re.finditer(r'https?://(?:cdn|media)\.discordapp\.(?:com|net)/emojis/([0-9]+)\.(gif|png|webp|jpg|jpeg)(?:\?[^\s]*)?', text, re.IGNORECASE)
    for m in cdn_matches:
        emoji_id = m.group(1)
        ext = m.group(2).lower()
        is_animated = (ext == "gif")
        if emoji_id not in seen:
            seen.add(emoji_id)
            name = f"emoji_{str(emoji_id)[-6:]}"
            results.append({
                "animated": is_animated,
                "name": name,
                "id": emoji_id,
                "url": f"https://cdn.discordapp.com/emojis/{emoji_id}.{'gif' if is_animated else 'png'}"
            })

    return results

def optimize_emoji_bytes(img_bytes: bytes, is_animated: bool = False, max_bytes: int = 256 * 1024) -> bytes:
    if len(img_bytes) <= max_bytes:
        return img_bytes

    if is_animated:
        try:
            with Image.open(io.BytesIO(img_bytes)) as im:
                frames = []
                durations = []
                for frame_idx in range(getattr(im, "n_frames", 1)):
                    im.seek(frame_idx)
                    new_frame = im.copy().convert("RGBA")
                    w, h = new_frame.size
                    new_size = (max(32, int(w * 0.8)), max(32, int(h * 0.8)))
                    new_frame = new_frame.resize(new_size, Image.Resampling.LANCZOS)
                    frames.append(new_frame)
                    durations.append(im.info.get("duration", 100))

                out_buf = io.BytesIO()
                frames[0].save(
                    out_buf,
                    format="GIF",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=0,
                    optimize=True
                )
                optimized = out_buf.getvalue()
                if len(optimized) < len(img_bytes):
                    return optimized
        except Exception:
            return img_bytes
        return img_bytes

    try:
        with Image.open(io.BytesIO(img_bytes)) as im:
            im = im.convert("RGBA")
            w, h = im.size
            if max(w, h) > 128:
                im.thumbnail((128, 128), Image.Resampling.LANCZOS)

            out_buf = io.BytesIO()
            im.save(out_buf, format="PNG", optimize=True)
            optimized = out_buf.getvalue()
            if len(optimized) <= max_bytes:
                return optimized

            im.thumbnail((96, 96), Image.Resampling.LANCZOS)
            out_buf = io.BytesIO()
            im.save(out_buf, format="PNG", optimize=True)
            return out_buf.getvalue()
    except Exception:
        return img_bytes


class Expressions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.emoji_rate_tracker = {}  # guild_id -> list of float timestamps in last 3600s

        self.steal_sticker_menu = app_commands.ContextMenu(
            name="Steal Sticker",
            callback=self.steal_sticker_context,
        )
        self.bot.tree.add_command(self.steal_sticker_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.steal_sticker_menu.name, type=self.steal_sticker_menu.type)

    def _check_bot_permissions(self, guild: discord.Guild) -> bool:
        if not guild or not guild.me:
            return False
        perms = guild.me.guild_permissions
        return bool(
            getattr(perms, "manage_expressions", False) or 
            getattr(perms, "manage_emojis_and_stickers", False) or 
            perms.administrator
        )

    @app_commands.command(name="emoji_steal", description="Steal emojis and add them to your server.")
    @app_commands.describe(emojis="Paste one or multiple emojis or Discord emoji CDN links to steal them.")
    @app_commands.default_permissions(manage_expressions=True)
    async def emoji_steal(self, interaction: discord.Interaction, emojis: str):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            if not interaction.guild:
                embed = discord.Embed(
                    title="✖ Server Only",
                    description="This command can only be used inside a Discord server.",
                    color=0xed4245
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            if not self._check_bot_permissions(interaction.guild):
                embed = discord.Embed(
                    title="✖ Missing Bot Permissions",
                    description="Friday lacks the **Manage Expressions** (or **Manage Emojis and Stickers**) permission in this server.\n"
                                "Please grant Friday this permission in **Server Settings > Roles**.",
                    color=0xed4245
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            extracted = extract_emojis_from_string(emojis)
            if not extracted:
                embed = discord.Embed(
                    title="✖ No Valid Emojis Found",
                    description="No custom emojis or Discord emoji links were found in your message.\n\n"
                                "**Usage:** Paste custom emojis (`:emoji:`) or Discord CDN links (`https://cdn.discordapp.com/emojis/...`).",
                    color=0x2b2d31
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Check guild emoji limits
            guild = interaction.guild
            limit = getattr(guild, "emoji_limit", 50)
            existing_static = len([e for e in guild.emojis if not e.animated])
            existing_animated = len([e for e in guild.emojis if e.animated])

            # ── Discord 50 Emojis / Hour Rate Limit Guard ──
            gid = interaction.guild.id
            now = time.time()
            recent_timestamps = [t for t in self.emoji_rate_tracker.get(gid, []) if now - t < 3600]
            self.emoji_rate_tracker[gid] = recent_timestamps

            max_hourly_quota = 50
            used_quota = len(recent_timestamps)
            remaining_quota = max(0, max_hourly_quota - used_quota)

            if remaining_quota <= 0:
                embed = discord.Embed(
                    title="⚠️ Discord Rate Limit Reached",
                    description="Discord enforces a hard server rate limit of **50 emojis created per hour**.\n\n"
                                f"This server has already added **{used_quota}/50** emojis in the last hour. "
                                "Please wait for the hourly cooldown before adding more emojis to avoid API bans.",
                    color=0xfaad14
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            to_process = extracted[:remaining_quota]
            excess_count = len(extracted) - len(to_process)

            added = []
            failed = 0
            fail_reasons = []
            rate_limit_tripped = False

            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for item in to_process:
                    animated = item["animated"]
                    name = item["name"]
                    url = item["url"]

                    # Quick pre-check for slots
                    if not animated and existing_static >= limit:
                        failed += 1
                        fail_reasons.append(f"`{name}`: Static emoji slots full ({limit}/{limit})")
                        continue
                    if animated and existing_animated >= limit:
                        failed += 1
                        fail_reasons.append(f"`{name}`: Animated emoji slots full ({limit}/{limit})")
                        continue

                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                raw_bytes = await resp.read()
                                optimized_bytes = optimize_emoji_bytes(raw_bytes, is_animated=animated)

                                try:
                                    new_emoji = await interaction.guild.create_custom_emoji(
                                        name=name,
                                        image=optimized_bytes,
                                        reason=f"Stolen by {interaction.user} via Friday"
                                    )
                                    emoji_format = f"<{'a' if animated else ''}:{new_emoji.name}:{new_emoji.id}>"
                                    added.append(emoji_format)
                                    self.emoji_rate_tracker[gid].append(time.time())
                                    if animated:
                                        existing_animated += 1
                                    else:
                                        existing_static += 1
                                except discord.Forbidden:
                                    embed = discord.Embed(
                                        title="✖ Missing Permissions",
                                        description="Friday lacks the **Manage Expressions** permission in this server.",
                                        color=0xed4245
                                    )
                                    await interaction.followup.send(embed=embed, ephemeral=True)
                                    return
                                except discord.HTTPException as http_err:
                                    failed += 1
                                    err_code = getattr(http_err, "code", 0)
                                    if err_code == 30008 or "maximum number of emojis" in str(http_err).lower():
                                        fail_reasons.append(f"`{name}`: Server emoji limit reached")
                                    elif getattr(http_err, "status", 0) == 429 or "rate" in str(http_err).lower():
                                        rate_limit_tripped = True
                                        fail_reasons.append("Discord API rate limit hit")
                                        break
                                    else:
                                        fail_reasons.append(f"`{name}`: Discord HTTP error ({http_err.text if hasattr(http_err, 'text') else http_err})")
                                except discord.InvalidArgument as arg_err:
                                    failed += 1
                                    fail_reasons.append(f"`{name}`: Invalid name ({arg_err})")
                                except Exception as inner_e:
                                    failed += 1
                                    fail_reasons.append(f"`{name}`: {inner_e}")
                            else:
                                failed += 1
                                fail_reasons.append(f"`{name}`: CDN returned HTTP {resp.status}")
                    except Exception as net_err:
                        failed += 1
                        fail_reasons.append(f"`{name}`: Download error ({net_err})")

            # Build result embed
            if added:
                embed = discord.Embed(
                    title="✔ Emojis Added Successfully",
                    description=f"Successfully added **{len(added)}** emoji{'s' if len(added) != 1 else ''}:\n{' '.join(added)}",
                    color=0x57f287
                )
            else:
                embed = discord.Embed(
                    title="✖ Failed to Add Emojis",
                    description="No emojis were added to the server.",
                    color=0xed4245
                )

            if failed > 0:
                short_reasons = "\n• " + "\n• ".join(fail_reasons[:5])
                if len(fail_reasons) > 5:
                    short_reasons += f"\n• ...and {len(fail_reasons) - 5} more"
                embed.add_field(name=f"Failed ({failed})", value=short_reasons, inline=False)

            if excess_count > 0 or rate_limit_tripped:
                skipped_total = excess_count + (len(to_process) - len(added) - failed if rate_limit_tripped else 0)
                embed.add_field(
                    name="⚠️ Rate Limit Protection",
                    value=f"Discord strictly caps creation at **50 emojis per hour**.\n"
                          f"**{max(1, skipped_total)}** emoji(s) were deferred to protect your server. "
                          "Please wait before adding more emojis.",
                    inline=False
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            traceback.print_exc()
            error_embed = discord.Embed(
                title="✖ Emoji Steal Error",
                description=f"An unexpected error occurred while executing the command: `{e}`",
                color=0xed4245
            )
            try:
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            except Exception:
                pass

    @commands.command(name="steal", aliases=["emojisteal", "stealemoji"])
    @commands.has_permissions(manage_expressions=True)
    async def prefix_steal(self, ctx: commands.Context, *, emojis: str):
        """Prefix command to steal custom emojis or Discord emoji CDN links (.steal <:emoji:id>)."""
        if not self._check_bot_permissions(ctx.guild):
            await ctx.send("❌ Friday lacks the **Manage Expressions** permission in this server.")
            return

        extracted = extract_emojis_from_string(emojis)
        if not extracted:
            await ctx.send("❌ No valid custom emojis or Discord emoji links found in your message.")
            return

        gid = ctx.guild.id
        now = time.time()
        recent_timestamps = [t for t in self.emoji_rate_tracker.get(gid, []) if now - t < 3600]
        self.emoji_rate_tracker[gid] = recent_timestamps

        max_hourly_quota = 50
        used_quota = len(recent_timestamps)
        remaining_quota = max(0, max_hourly_quota - used_quota)

        if remaining_quota <= 0:
            await ctx.send(f"⚠️ Discord rate limit reached (**{used_quota}/50** emojis created in the last hour). Please wait before stealing more.")
            return

        to_process = extracted[:remaining_quota]
        added = []
        failed = 0

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for item in to_process:
                animated = item["animated"]
                name = item["name"]
                url = item["url"]
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            raw_bytes = await resp.read()
                            optimized_bytes = optimize_emoji_bytes(raw_bytes, is_animated=animated)
                            new_emoji = await ctx.guild.create_custom_emoji(
                                name=name,
                                image=optimized_bytes,
                                reason=f"Stolen by {ctx.author} via Friday (.steal)"
                            )
                            emoji_format = f"<{'a' if animated else ''}:{new_emoji.name}:{new_emoji.id}>"
                            added.append(emoji_format)
                            self.emoji_rate_tracker[gid].append(time.time())
                        else:
                            failed += 1
                except Exception:
                    failed += 1

        if added:
            msg = f"✔ Successfully stole **{len(added)}** emoji{'s' if len(added) != 1 else ''}: {' '.join(added)}"
            if failed > 0:
                msg += f"\n✖ Failed to add {failed} (slots full or rate limited)."
            await ctx.send(msg)
        else:
            await ctx.send(f"❌ Failed to add emojis (server slots full or invalid image).")

    @app_commands.default_permissions(manage_expressions=True)
    async def steal_sticker_context(self, interaction: discord.Interaction, message: discord.Message):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            if not interaction.guild:
                await interaction.followup.send("❌ This context command can only be used in a server.", ephemeral=True)
                return

            if not self._check_bot_permissions(interaction.guild):
                embed = discord.Embed(
                    title="✖ Missing Bot Permissions",
                    description="Friday lacks permissions to manage expressions/stickers.",
                    color=0xed4245
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            if not message.stickers:
                embed = discord.Embed(
                    title="✖ No Sticker Found",
                    description="No sticker found in that message.",
                    color=0x2b2d31
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            sticker_item = message.stickers[0]
            try:
                full_sticker = await sticker_item.fetch()
            except discord.HTTPException:
                embed = discord.Embed(
                    title="✖ Fetch Failed",
                    description="Failed to fetch sticker data from Discord's servers.",
                    color=0x2b2d31
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            if type(full_sticker) == discord.StandardSticker:
                embed = discord.Embed(
                    title="✖ Standard Sticker",
                    description="You cannot steal Discord's official built-in standard stickers.",
                    color=0x2b2d31
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            img_bytes = await full_sticker.read()
            new_sticker = await interaction.guild.create_sticker(
                name=full_sticker.name[:30] if full_sticker.name else "stolen_sticker",
                description="Stolen by Friday",
                emoji=full_sticker.emoji or "✨",
                file=discord.File(fp=io.BytesIO(img_bytes), filename="sticker.png")
            )
            embed = discord.Embed(
                title="✔ Sticker Added",
                description=f"Successfully stole sticker: **{new_sticker.name}**",
                color=0x57f287
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            embed = discord.Embed(
                title="✖ Missing Permissions",
                description="Friday lacks permissions to manage stickers in this server.",
                color=0xed4245
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.HTTPException as e:
            embed = discord.Embed(
                title="✖ Failed to Add Sticker",
                description=f"Error: {e.text if hasattr(e, 'text') else e}",
                color=0xed4245
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            traceback.print_exc()
            embed = discord.Embed(
                title="✖ Sticker Steal Error",
                description=f"An unexpected error occurred: `{e}`",
                color=0xed4245
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ───────────────────── Autoreact Slash Commands Group ─────────────────────
    autoreact = app_commands.Group(name="autoreact", description="Manage emoji reactions when specific members are mentioned", default_permissions=discord.Permissions(manage_guild=True))

    @autoreact.command(name="add", description="Set Friday to auto-react with an emoji when a member is tagged.")
    @app_commands.describe(member="The member to trigger reaction on mention", emoji="The emoji or custom emoji to react with")
    @app_commands.default_permissions(manage_guild=True)
    async def autoreact_add(self, interaction: discord.Interaction, member: discord.Member, emoji: str):
        gid = str(interaction.guild.id)
        if gid not in db.autoreact or not isinstance(db.autoreact[gid], list):
            db.autoreact[gid] = []

        clean_emoji = emoji.strip()
        uid = str(member.id)
        existing = False
        for rule in db.autoreact[gid]:
            if str(rule.get("user_id")) == uid:
                rule["emoji"] = clean_emoji
                rule["user_name"] = member.display_name
                existing = True
                break

        if not existing:
            db.autoreact[gid].append({
                "user_id": uid,
                "user_name": member.display_name,
                "emoji": clean_emoji
            })
        db.save_data()

        embed = discord.Embed(
            title="✔ Trigger Added",
            description=f"Successfully added trigger {member.mention} with {clean_emoji}",
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed)

    @autoreact.command(name="remove", description="Remove auto-reaction rule for a member.")
    @app_commands.describe(member="The member whose auto-react rule should be removed")
    @app_commands.default_permissions(manage_guild=True)
    async def autoreact_remove(self, interaction: discord.Interaction, member: discord.Member):
        gid = str(interaction.guild.id)
        uid = str(member.id)
        if gid in db.autoreact and isinstance(db.autoreact[gid], list):
            initial_len = len(db.autoreact[gid])
            db.autoreact[gid] = [r for r in db.autoreact[gid] if str(r.get("user_id")) != uid]
            if len(db.autoreact[gid]) < initial_len:
                db.save_data()
                embed = discord.Embed(
                    title="✔ Trigger Removed",
                    description=f"Successfully removed trigger {member.mention}",
                    color=0x2b2d31
                )
                await interaction.response.send_message(embed=embed)
                return

        embed = discord.Embed(
            title="✖ Trigger Not Found",
            description=f"No active trigger found for {member.mention}.",
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @autoreact.command(name="list", description="List all active auto-reaction rules in this server.")
    async def autoreact_list(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        rules = db.autoreact.get(gid, [])
        if not rules:
            embed = discord.Embed(
                title="ℹ Auto-React Rules",
                description="No auto-reaction rules configured in this server.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="✔ Active Auto-React Rules",
            description="Friday will react with the specified emoji whenever these members are tagged:",
            color=0x2b2d31
        )
        lines = []
        for r in rules:
            uid = r.get("user_id")
            emoji = r.get("emoji", "")
            lines.append(f"• <@{uid}> ➔ {emoji}")
        embed.add_field(name="Configured Members", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed)

    # ───────────────────── Autoresponder Slash Commands Group ─────────────────────
    autoresponder = app_commands.Group(name="autoresponder", description="Manage automated replies and reactions on mentions or keywords", default_permissions=discord.Permissions(manage_guild=True))

    @autoresponder.command(name="add", description="Set Friday to auto-reply and/or react on member mention or standalone keyword.")
    @app_commands.describe(
        response="Optional reply message ({author} and {user} supported). Can be omitted if emoji is provided.",
        member="Target member to trigger on mention (optional if using keyword)",
        keyword="Standalone word/keyword to trigger (e.g. 'ip') (optional if using member)",
        emoji="Optional emoji to react to the message with. Can be set with or without reply text.",
        channel="Optional channel to restrict or exclude this rule from",
        scope="Channel scope mode if channel is selected ('only' in this channel, or 'ignore' in this channel)"
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="🎯 Only in this channel", value="only"),
        app_commands.Choice(name="🚫 Ignore in this channel", value="ignore")
    ])
    @app_commands.default_permissions(manage_guild=True)
    async def autoresponder_add(
        self,
        interaction: discord.Interaction,
        response: Optional[str] = None,
        member: Optional[discord.Member] = None,
        keyword: Optional[str] = None,
        emoji: Optional[str] = None,
        channel: Optional[discord.TextChannel] = None,
        scope: Optional[app_commands.Choice[str]] = None
    ):
        gid = str(interaction.guild.id)
        if gid not in db.autoresponder or not isinstance(db.autoresponder[gid], dict):
            db.autoresponder[gid] = {"rules": [], "ignored_channels": []}

        clean_resp = response.strip() if response else ""
        clean_emoji = emoji.strip() if emoji else ""
        rules = db.autoresponder[gid].setdefault("rules", [])

        # Channel filter configuration
        channel_mode = "all"
        rule_channels = []
        if channel:
            channel_mode = scope.value if scope else "only"
            rule_channels = [str(channel.id)]

        if not clean_resp and not clean_emoji:
            embed = discord.Embed(
                title="✖ Missing Action",
                description="Please provide either a **response** reply message or an **emoji** reaction (or both).",
                color=0xed4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not member and not keyword:
            embed = discord.Embed(
                title="✖ Missing Target",
                description="Please provide either a **member** (to trigger on mention) or a **keyword** (e.g. `ip`).",
                color=0xed4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        scope_desc = ""
        if channel:
            if channel_mode == "only":
                scope_desc = f"\n> **Channel Scope:** 🎯 Triggers ONLY in {channel.mention}"
            else:
                scope_desc = f"\n> **Channel Scope:** 🚫 Ignored in {channel.mention} (triggers elsewhere)"

        if keyword:
            clean_word = keyword.strip()
            rule_id = str(uuid.uuid4())[:8]
            existing = False
            for r in rules:
                if (r.get("type") == "word" or "trigger" in r) and str(r.get("trigger", "")).lower() == clean_word.lower():
                    r["type"] = "word"
                    r["trigger"] = clean_word
                    r["response"] = clean_resp
                    r["emoji"] = clean_emoji
                    r["channel_mode"] = channel_mode
                    r["channels"] = rule_channels
                    existing = True
                    break
            if not existing:
                rules.append({
                    "id": rule_id,
                    "type": "word",
                    "trigger": clean_word,
                    "response": clean_resp,
                    "emoji": clean_emoji,
                    "channel_mode": channel_mode,
                    "channels": rule_channels
                })
            db.save_data()

            emoji_note = f"\n> **Reaction:** {clean_emoji}" if clean_emoji else ""
            embed = discord.Embed(
                title="✔ Keyword Auto-Responder Configured",
                description=f"When someone writes standalone word `{clean_word}` (e.g. 'what is the {clean_word}?'), Friday will reply with:\n> {clean_resp}{emoji_note}{scope_desc}\n\n*Note: Partial words like `{clean_word}L` will strictly NOT trigger.*",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed)
            return

        if member:
            uid = str(member.id)
            rule_id = str(uuid.uuid4())[:8]
            existing = False
            for r in rules:
                if str(r.get("user_id")) == uid:
                    r["type"] = "mention"
                    r["response"] = clean_resp
                    r["user_name"] = member.display_name
                    r["emoji"] = clean_emoji
                    r["channel_mode"] = channel_mode
                    r["channels"] = rule_channels
                    existing = True
                    break
            if not existing:
                rules.append({
                    "id": rule_id,
                    "type": "mention",
                    "user_id": uid,
                    "user_name": member.display_name,
                    "response": clean_resp,
                    "emoji": clean_emoji,
                    "channel_mode": channel_mode,
                    "channels": rule_channels
                })
            db.save_data()

            emoji_note = f"\n> **Reaction:** {clean_emoji}" if clean_emoji else ""
            embed = discord.Embed(
                title="✔ Mention Auto-Responder Configured",
                description=f"When {member.mention} is tagged, Friday will reply with:\n> {clean_resp}{emoji_note}{scope_desc}",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed)
            return

    @autoresponder.command(name="remove", description="Remove auto-responder rule for a member or keyword.")
    @app_commands.describe(
        member="The member whose auto-responder rule should be removed",
        keyword="The keyword rule to remove (e.g. 'ip')"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def autoresponder_remove(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
        keyword: Optional[str] = None
    ):
        gid = str(interaction.guild.id)
        if not member and not keyword:
            embed = discord.Embed(
                title="✖ Missing Target",
                description="Please specify either a `member` or a `keyword` to remove.",
                color=0xed4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if gid in db.autoresponder and isinstance(db.autoresponder[gid], dict):
            rules = db.autoresponder[gid].get("rules", [])
            initial_len = len(rules)
            if keyword:
                clean_kw = keyword.strip().lower()
                db.autoresponder[gid]["rules"] = [
                    r for r in rules
                    if str(r.get("trigger", "")).lower() != clean_kw
                ]
                removed_target = f"keyword `{keyword}`"
            else:
                uid = str(member.id)
                db.autoresponder[gid]["rules"] = [
                    r for r in rules
                    if str(r.get("user_id")) != uid
                ]
                removed_target = member.mention

            if len(db.autoresponder[gid]["rules"]) < initial_len:
                db.save_data()
                embed = discord.Embed(
                    title="✔ Trigger Removed",
                    description=f"Successfully removed auto-responder trigger for {removed_target}.",
                    color=0x2b2d31
                )
                await interaction.response.send_message(embed=embed)
                return

        embed = discord.Embed(
            title="✖ Trigger Not Found",
            description=f"No active auto-responder rule found matching your input.",
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @autoresponder.command(name="list", description="List all active auto-responder rules and ignored channels.")
    async def autoresponder_list(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        ar_data = db.autoresponder.get(gid, {})
        rules = ar_data.get("rules", []) if isinstance(ar_data, dict) else []
        ignored = ar_data.get("ignored_channels", []) if isinstance(ar_data, dict) else []

        if not rules and not ignored:
            embed = discord.Embed(
                title="ℹ Auto-Responder Rules",
                description="No auto-responder rules configured in this server.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="✔ Active Auto-Responder Rules",
            color=0x2b2d31
        )

        mention_rules = [r for r in rules if r.get("user_id")]
        word_rules = [r for r in rules if r.get("type") == "word" or r.get("trigger")]

        if mention_rules:
            mlines = []
            for r in mention_rules[:15]:
                react_str = f" [React: {r.get('emoji')}]" if r.get("emoji") else ""
                scope_str = ""
                r_mode = r.get("channel_mode", "all")
                r_chans = r.get("channels", [])
                if r_mode == "only" and r_chans:
                    scope_str = f" [🎯 Only: {', '.join('<#' + str(c) + '>' for c in r_chans)}]"
                elif r_mode == "ignore" and r_chans:
                    scope_str = f" [🚫 Ignored: {', '.join('<#' + str(c) + '>' for c in r_chans)}]"
                resp_text = r.get('response') or '(Reaction only)'
                mlines.append(f"• <@{r.get('user_id')}>: \"{resp_text}\"{react_str}{scope_str}")
            embed.add_field(name="Mention Triggers", value="\n".join(mlines), inline=False)
        else:
            embed.add_field(name="Mention Triggers", value="None configured yet.", inline=False)

        if word_rules:
            wlines = []
            for r in word_rules[:15]:
                react_str = f" [React: {r.get('emoji')}]" if r.get("emoji") else ""
                scope_str = ""
                r_mode = r.get("channel_mode", "all")
                r_chans = r.get("channels", [])
                if r_mode == "only" and r_chans:
                    scope_str = f" [🎯 Only: {', '.join('<#' + str(c) + '>' for c in r_chans)}]"
                elif r_mode == "ignore" and r_chans:
                    scope_str = f" [🚫 Ignored: {', '.join('<#' + str(c) + '>' for c in r_chans)}]"
                resp_text = r.get('response') or '(Reaction only)'
                wlines.append(f"• Word `{r.get('trigger')}`: \"{resp_text}\"{react_str}{scope_str}")
            embed.add_field(name="Keyword / Word Triggers", value="\n".join(wlines), inline=False)
        else:
            embed.add_field(name="Keyword / Word Triggers", value="None configured yet.", inline=False)

        if ignored:
            ign_lines = [f"• <#{cid}>" for cid in ignored]
            embed.add_field(name="Ignored Channels", value="\n".join(ign_lines), inline=False)
        else:
            embed.add_field(name="Ignored Channels", value="None (active across all channels).", inline=False)

        await interaction.response.send_message(embed=embed)

    @autoresponder.command(name="ignore_channel", description="Prevent auto-responder from triggering in a specific channel.")
    @app_commands.describe(channel="The channel where auto-responses should be disabled")
    @app_commands.default_permissions(manage_guild=True)
    async def autoresponder_ignore_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        if gid not in db.autoresponder or not isinstance(db.autoresponder[gid], dict):
            db.autoresponder[gid] = {"rules": [], "ignored_channels": []}

        cid = str(channel.id)
        ignored = db.autoresponder[gid].setdefault("ignored_channels", [])
        if cid not in [str(x) for x in ignored]:
            ignored.append(cid)
            db.save_data()
            embed = discord.Embed(
                title="✔ Channel Ignored",
                description=f"Auto-responder will now ignore mentions in {channel.mention}.",
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

    @autoresponder.command(name="unignore_channel", description="Re-enable auto-responder in an ignored channel.")
    @app_commands.describe(channel="The channel to remove from ignore list")
    @app_commands.default_permissions(manage_guild=True)
    async def autoresponder_unignore_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        cid = str(channel.id)
        if gid in db.autoresponder and isinstance(db.autoresponder[gid], dict):
            ignored = db.autoresponder[gid].get("ignored_channels", [])
            initial_len = len(ignored)
            db.autoresponder[gid]["ignored_channels"] = [x for x in ignored if str(x) != cid]
            if len(db.autoresponder[gid]["ignored_channels"]) < initial_len:
                db.save_data()
                embed = discord.Embed(
                    title="✔ Channel Unignored",
                    description=f"Removed {channel.mention} from auto-responder ignore list.",
                    color=0x2b2d31
                )
                await interaction.response.send_message(embed=embed)
                return

        embed = discord.Embed(
            title="ℹ Channel Not Ignored",
            description=f"{channel.mention} was not in the ignore list.",
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _safe_add_reaction(self, message: discord.Message, raw_emoji: str):
        if not raw_emoji:
            return
        try:
            react_target = raw_emoji.strip()
            # Custom emoji format <:name:id> or <a:name:id>
            custom_match = re.match(r'^<a?:([a-zA-Z0-9_]+):([0-9]+)>$', react_target)
            if custom_match:
                eid = int(custom_match.group(2))
                custom_obj = self.bot.get_emoji(eid)
                react_target = custom_obj if custom_obj else f"{custom_match.group(1)}:{custom_match.group(2)}"
            await message.add_reaction(react_target)
        except Exception as e:
            print(f"[Expressions] Warning: Failed to react with {raw_emoji}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # If message contains only stickers with no text, strictly IGNORE
        if getattr(message, 'stickers', None) and not (message.content or "").strip():
            return

        gid = str(message.guild.id)
        content = message.content or ""

        # Only count members explicitly tagged with @ in message content (ignore reply pings)
        explicitly_mentioned_ids = set()
        if message.mentions:
            explicitly_mentioned_ids = {
                str(m.id) for m in message.mentions
                if f"<@{m.id}>" in content or f"<@!{m.id}>" in content
            }

        # 0. Tag Greeting Response: When someone explicitly tags @Friday with no message or simple greeting
        if self.bot.user and str(self.bot.user.id) in explicitly_mentioned_ids:
            clean_content = re.sub(r'<@!?' + str(self.bot.user.id) + r'>', '', content).strip()
            clean_lower = clean_content.lower().strip("!?,. ")
            GREETING_WORDS = {'', 'hi', 'hii', 'hiii', 'hey', 'heyy', 'heyyy', 'hello', 'helloo', 'yo', 'sup', 'friday'}
            if not clean_content or clean_lower in GREETING_WORDS:
                template = random.choice(GREETINGS)
                greeting = template.replace("{user}", message.author.mention)
                if message.author.mention not in greeting:
                    greeting = f"{message.author.mention} {greeting}"
                try:
                    await message.reply(greeting, mention_author=True)
                except Exception:
                    try:
                        await message.channel.send(greeting)
                    except Exception as e:
                        print(f"[Greeting Reply Error] {e}")
                return

        # 1. Autoreact on Mention
        if explicitly_mentioned_ids:
            autoreact_rules = db.autoreact.get(gid, [])
            if autoreact_rules and isinstance(autoreact_rules, list):
                for rule in autoreact_rules:
                    if str(rule.get("user_id")) in explicitly_mentioned_ids:
                        raw_emoji = rule.get("emoji")
                        if raw_emoji:
                            await self._safe_add_reaction(message, raw_emoji)

        # 2. Autoresponder (Word / Keyword Triggers & Mention Triggers)
        ar_data = db.autoresponder.get(gid, {})
        if isinstance(ar_data, dict):
            rules = ar_data.get("rules", [])
            ignored_channels = [str(c) for c in ar_data.get("ignored_channels", [])]
            curr_chan_id = str(message.channel.id)

            # Skip if current channel is globally ignored
            if curr_chan_id not in ignored_channels and rules:
                responded = False

                # Helper to check if a rule is eligible in the current channel
                def _is_channel_eligible(r):
                    mode = r.get("channel_mode", "all")
                    chan_list = [str(c) for c in r.get("channels", []) if str(c).strip()]
                    if mode == "only":
                        return bool(chan_list and curr_chan_id in chan_list)
                    elif mode == "ignore":
                        return bool(curr_chan_id not in chan_list)
                    return True

                # 2A. Check Word / Keyword Triggers (whole-word boundary match)
                for rule in rules:
                    if not _is_channel_eligible(rule):
                        continue
                    trigger = rule.get("trigger", "").strip() if (rule.get("type") == "word" or "trigger" in rule) else ""
                    if trigger:
                        # Match standalone word/phrase (e.g. 'ip' matches 'what is the ip?' but NOT 'IPL' or 'equipment')
                        pattern = rf'(?<!\w){re.escape(trigger)}(?!\w)'
                        if re.search(pattern, content, re.IGNORECASE):
                            # React with emoji if configured
                            raw_emoji = rule.get("emoji")
                            if raw_emoji:
                                await self._safe_add_reaction(message, raw_emoji)

                            # Reply with message if configured
                            resp_template = rule.get("response")
                            if resp_template:
                                formatted = resp_template.replace("{author}", message.author.mention).replace("{user}", message.author.display_name)
                                try:
                                    await message.reply(formatted, mention_author=False)
                                except Exception:
                                    try:
                                        await message.channel.send(formatted)
                                    except Exception as e:
                                        print(f"[Autoresponder Word Reply Error] {e}")
                            responded = True
                            break

                # 2B. If no keyword triggered, check Mention Triggers
                if not responded and explicitly_mentioned_ids:
                    for rule in rules:
                        if not _is_channel_eligible(rule):
                            continue
                        target_id = str(rule.get("user_id", ""))
                        if target_id and target_id in explicitly_mentioned_ids:
                            # Suppress autoresponder if target is currently AFK to prevent dual/conflicting messages
                            afk_members = getattr(db, "afk_data", {}).get(gid, {})
                            if target_id in afk_members:
                                continue

                            # React with emoji if configured
                            raw_emoji = rule.get("emoji")
                            if raw_emoji:
                                await self._safe_add_reaction(message, raw_emoji)

                            # Reply with message if configured
                            resp_template = rule.get("response")
                            if resp_template:
                                target_member = next((m for m in message.mentions if str(m.id) == target_id), None)
                                formatted = resp_template.replace("{author}", message.author.mention)
                                if target_member:
                                    formatted = formatted.replace("{user}", target_member.display_name).replace("{member}", target_member.mention)
                                try:
                                    await message.reply(formatted, mention_author=False)
                                except Exception:
                                    try:
                                        await message.channel.send(formatted)
                                    except Exception as e:
                                        print(f"[Autoresponder Mention Reply Error] {e}")
                            break


async def setup(bot):
    await bot.add_cog(Expressions(bot))
