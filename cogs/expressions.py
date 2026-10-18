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
from typing import Optional
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



class Expressions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.steal_sticker_menu = app_commands.ContextMenu(
            name="Steal Sticker",
            callback=self.steal_sticker_context,
        )
        self.bot.tree.add_command(self.steal_sticker_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.steal_sticker_menu.name, type=self.steal_sticker_menu.type)

    @app_commands.command(name="emoji_steal", description="Steal emojis and add them to your server.")
    @app_commands.describe(emojis="Paste one or multiple emojis here to steal them in bulk.")
    @app_commands.default_permissions(manage_expressions=True)
    async def emoji_steal(self, interaction: discord.Interaction, emojis: str):
        await interaction.response.defer(ephemeral=True)
        matches = re.findall(r'<(a?):([a-zA-Z0-9_]+):([0-9]+)>', emojis)
        
        if not matches:
            embed = discord.Embed(
                title="✖ No Emojis Found",
                description="No valid custom emojis found in your message.",
                color=0x2b2d31
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
            
        added = []
        failed = 0
        async with aiohttp.ClientSession() as session:
            for animated, name, emoji_id in matches:
                ext = "gif" if animated else "png"
                url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
                
                async with session.get(url) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        try:
                            new_emoji = await interaction.guild.create_custom_emoji(name=name, image=img_bytes)
                            emoji_format = f"<{'a' if animated else ''}:{new_emoji.name}:{new_emoji.id}>"
                            added.append(emoji_format)
                        except discord.Forbidden:
                            embed = discord.Embed(
                                title="✖ Missing Permissions",
                                description="I lack permissions to manage emojis in this server.",
                                color=0x2b2d31
                            )
                            await interaction.followup.send(embed=embed, ephemeral=True)
                            return
                        except discord.HTTPException:
                            failed += 1 
                            
        embed = discord.Embed(
            title="✔ Emojis Added",
            description=f"Successfully stole **{len(added)}** emojis: {' '.join(added)}",
            color=0x2b2d31
        )
        if failed > 0:
            embed.description += f"\n✖ Failed to add {failed} emojis (server slots may be full)."
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.default_permissions(manage_expressions=True)
    async def steal_sticker_context(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True)
        
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
            
        try:
            img_bytes = await full_sticker.read()
            new_sticker = await interaction.guild.create_sticker(
                name=full_sticker.name,
                description="Stolen by Friday",
                emoji=full_sticker.emoji or "✨",
                file=discord.File(fp=io.BytesIO(img_bytes), filename="sticker.png")
            )
            embed = discord.Embed(
                title="✔ Sticker Added",
                description=f"Successfully stole sticker: **{new_sticker.name}**",
                color=0x2b2d31
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            embed = discord.Embed(
                title="✖ Missing Permissions",
                description="I lack permissions to manage stickers.",
                color=0x2b2d31
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.HTTPException as e:
            embed = discord.Embed(
                title="✖ Failed to Add Sticker",
                description=f"Error: {e.text}",
                color=0x2b2d31
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ───────────────────── Autoreact Slash Commands Group ─────────────────────
    autoreact = app_commands.Group(name="autoreact", description="Manage emoji reactions when specific members are mentioned")

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
    autoresponder = app_commands.Group(name="autoresponder", description="Manage automated replies and reactions on mentions or keywords")

    @autoresponder.command(name="add", description="Set Friday to auto-reply and/or react on member mention or standalone keyword.")
    @app_commands.describe(
        response="The reply message ({author} and {user} supported)",
        member="Target member to trigger on mention (optional if using keyword)",
        keyword="Standalone word/keyword to trigger (e.g. 'ip') (optional if using member)",
        emoji="Optional emoji to react to the message with"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def autoresponder_add(
        self,
        interaction: discord.Interaction,
        response: str,
        member: Optional[discord.Member] = None,
        keyword: Optional[str] = None,
        emoji: Optional[str] = None
    ):
        gid = str(interaction.guild.id)
        if gid not in db.autoresponder or not isinstance(db.autoresponder[gid], dict):
            db.autoresponder[gid] = {"rules": [], "ignored_channels": []}

        clean_resp = response.strip()
        clean_emoji = emoji.strip() if emoji else ""
        rules = db.autoresponder[gid].setdefault("rules", [])

        if not member and not keyword:
            embed = discord.Embed(
                title="✖ Missing Target",
                description="Please provide either a **member** (to trigger on mention) or a **keyword** (e.g. `ip`).",
                color=0xed4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

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
                    existing = True
                    break
            if not existing:
                rules.append({
                    "id": rule_id,
                    "type": "word",
                    "trigger": clean_word,
                    "response": clean_resp,
                    "emoji": clean_emoji
                })
            db.save_data()

            emoji_note = f"\n> **Reaction:** {clean_emoji}" if clean_emoji else ""
            embed = discord.Embed(
                title="✔ Keyword Auto-Responder Configured",
                description=f"When someone writes standalone word `{clean_word}` (e.g. 'what is the {clean_word}?'), Friday will reply with:\n> {clean_resp}{emoji_note}\n\n*Note: Partial words like `{clean_word}L` will strictly NOT trigger.*",
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
                    existing = True
                    break
            if not existing:
                rules.append({
                    "id": rule_id,
                    "type": "mention",
                    "user_id": uid,
                    "user_name": member.display_name,
                    "response": clean_resp,
                    "emoji": clean_emoji
                })
            db.save_data()

            emoji_note = f"\n> **Reaction:** {clean_emoji}" if clean_emoji else ""
            embed = discord.Embed(
                title="✔ Mention Auto-Responder Configured",
                description=f"When {member.mention} is tagged, Friday will reply with:\n> {clean_resp}{emoji_note}",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed)

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
                mlines.append(f"• <@{r.get('user_id')}>: \"{r.get('response')}\"{react_str}")
            embed.add_field(name="Mention Triggers", value="\n".join(mlines), inline=False)
        else:
            embed.add_field(name="Mention Triggers", value="None configured yet.", inline=False)

        if word_rules:
            wlines = []
            for r in word_rules[:15]:
                react_str = f" [React: {r.get('emoji')}]" if r.get("emoji") else ""
                wlines.append(f"• Word `{r.get('trigger')}`: \"{r.get('response')}\"{react_str}")
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

            # Skip if current channel is ignored
            if str(message.channel.id) not in ignored_channels and rules:
                responded = False

                # 2A. Check Word / Keyword Triggers (whole-word boundary match)
                for rule in rules:
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
