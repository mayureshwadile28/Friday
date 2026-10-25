import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv
import datetime
import time
import json
import pyjokes
from hinglish_jokes import get_random_joke, build_joke_embed, JokeView
import random
import re
import aiohttp
import io
from easy_pil import Editor, load_image_async, Font, Canvas

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
intents.moderation = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

# --- PERMANENT MEMORY SETUP ---
DATA_FILE = "friday_memory.json"

def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "nuke_settings": {}, 
            "whitelist": {}, 
            "antinuke_active": {}, 
            "server_logs": {},
            "banned_words": {},     
            "abuse_whitelist": {},
            "xp_data": {},          
            "level_channels": {},
            "reaction_roles": {},
            "ignored_private": {}
        }

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump({
            "nuke_settings": nuke_settings,
            "whitelist": whitelist,
            "antinuke_active": antinuke_active,
            "server_logs": server_logs,
            "banned_words": banned_words,
            "abuse_whitelist": abuse_whitelist,
            "xp_data": xp_data,
            "level_channels": level_channels,
            "reaction_roles": reaction_roles,
            "ignored_private": ignored_private
        }, f, indent=4)

db = load_data()
nuke_settings = db.get("nuke_settings", {})
whitelist = db.get("whitelist", {})
antinuke_active = db.get("antinuke_active", {})
server_logs = db.get("server_logs", {})
banned_words = db.get("banned_words", {})
abuse_whitelist = db.get("abuse_whitelist", {})
xp_data = db.get("xp_data", {})
level_channels = db.get("level_channels", {})
reaction_roles = db.get("reaction_roles", {})
ignored_private = db.get("ignored_private", {})

action_tracker = {} 
xp_cooldowns = {} 

def record_action_and_check(guild_id, user_id, action_type):
    gid = str(guild_id)
    uid = str(user_id)
    now = time.time()
    time_window = 60 
    
    if gid not in action_tracker:
        action_tracker[gid] = {}
    if uid not in action_tracker[gid]:
        action_tracker[gid][uid] = []
        
    action_tracker[gid][uid].append(now)
    action_tracker[gid][uid] = [t for t in action_tracker[gid][uid] if now - t <= time_window]
    
    limit = nuke_settings.get(gid, {}).get(action_type, 999) 
    if len(action_tracker[gid][uid]) >= limit:
        return True
    return False

def get_xp_requirement(level):
    return 100 * (level + 1)

@bot.event
async def on_ready():
    for cmd in bot.tree.get_commands():
        if cmd.name in ("avatar", "avtar"):
            cmd.guild_only = False
        else:
            try:
                cmd.guild_only = True
            except Exception:
                pass
    await bot.tree.sync()
    print(f'System online: {bot.user.name} is connected to Discord!')

# --- ACTIVE CHAT FILTER & XP SYSTEM ---
@bot.event
async def on_message(message):
    if message.author.bot: 
        return

    gid = str(message.guild.id)
    uid = str(message.author.id)
    
    if message.author.id not in abuse_whitelist.get(gid, []):
        word_list = banned_words.get(gid, [])
        content_lower = message.content.lower()
        
        triggered_word = None
        for word in word_list:
            if re.search(rf'\b{re.escape(word)}\b', content_lower):
                triggered_word = word
                break
        
        if triggered_word:
            try:
                await message.delete()
                warning = await message.channel.send(f"⚠️ {message.author.mention}, that word is not allowed here.")
                await warning.delete(delay=5)
                
                log_id = server_logs.get(gid, {}).get("audit-abuse")
                if log_id:
                    log_channel = bot.get_channel(log_id)
                    if log_channel:
                        embed = discord.Embed(title="🤬 Abuse Word Detected", color=discord.Color.orange())
                        embed.add_field(name="Author", value=message.author.mention, inline=True)
                        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                        embed.add_field(name="Trigger Word", value=f"`{triggered_word}`", inline=False)
                        embed.add_field(name="Full Message", value=message.content, inline=False)
                        embed.set_footer(text=f"Detected on {discord.utils.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')}")
                        await log_channel.send(embed=embed)
                return
            except discord.Forbidden:
                pass

    now = time.time()
    if uid not in xp_cooldowns or (now - xp_cooldowns[uid]) >= 60:
        if gid not in xp_data: xp_data[gid] = {}
        if uid not in xp_data[gid]: xp_data[gid][uid] = {"xp": 0, "level": 0}

        gained_xp = random.randint(15, 40)
        xp_data[gid][uid]["xp"] += gained_xp
        xp_cooldowns[uid] = now
        
        current_xp = xp_data[gid][uid]["xp"]
        current_level = xp_data[gid][uid]["level"]
        required_xp = get_xp_requirement(current_level)

        if current_xp >= required_xp:
            xp_data[gid][uid]["level"] += 1
            xp_data[gid][uid]["xp"] = current_xp - required_xp 
            new_level = xp_data[gid][uid]["level"]
            save_data()

            channel_id = level_channels.get(gid)
            if channel_id:
                notif_channel = bot.get_channel(channel_id)
                if notif_channel:
                    level_msg = f"""--------------------
# 🎉 LEVEL UP!
**{message.author.mention}** just advanced to **Level {new_level}**! Keep it up!
--------------------"""
                    await notif_channel.send(level_msg)
        else:
            save_data()

    await bot.process_commands(message)

# --- REACTION ROLE EVENTS ---
@bot.event
async def on_raw_reaction_add(payload):
    if payload.member.bot: 
        return
        
    msg_id = str(payload.message_id)
    if msg_id in reaction_roles:
        emoji_key = str(payload.emoji)
        role_id = reaction_roles[msg_id].get(emoji_key)
        
        if role_id:
            guild = bot.get_guild(payload.guild_id)
            role = guild.get_role(role_id)
            if role:
                try:
                    await payload.member.add_roles(role)
                except discord.Forbidden:
                    pass

@bot.event
async def on_raw_reaction_remove(payload):
    msg_id = str(payload.message_id)
    if msg_id in reaction_roles:
        emoji_key = str(payload.emoji)
        role_id = reaction_roles[msg_id].get(emoji_key)
        
        if role_id:
            guild = bot.get_guild(payload.guild_id)
            role = guild.get_role(role_id)
            member = guild.get_member(payload.user_id)
            
            if role and member and not member.bot:
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    pass

# --- SECURITY EVENTS ---
@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    gid = str(guild.id)
    if not antinuke_active.get(gid, True): return
    culprit = None
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=5):
            if entry.target and entry.target.id == channel.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 25:
                culprit = entry.user
                break
    except Exception:
        pass
    if not culprit or culprit.bot or culprit.id in whitelist.get(gid, []): return
    should_ban = record_action_and_check(guild.id, culprit.id, 'channel')
    if should_ban:
        try:
            await guild.ban(culprit, reason="Anti-Nuke: Triggered channel deletion limit.")
            log_id = server_logs.get(gid, {}).get("audit-antinuke")
            if log_id: await bot.get_channel(log_id).send(f"🚨 **ANTI-NUKE TRIGGERED:** Banned {culprit.mention} for deleting too many channels.")
        except discord.Forbidden:
            pass

@bot.event
async def on_member_ban(guild, user):
    gid = str(guild.id)
    log_id = server_logs.get(gid, {}).get("audit-banned")
    if log_id: await bot.get_channel(log_id).send(f"🔨 **User Banned:** {user.mention} has been banned from the server.")
    if not antinuke_active.get(gid, True): return
    culprit = None
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=5):
            if entry.target and entry.target.id == user.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 25:
                culprit = entry.user
                break
    except Exception:
        pass
    if not culprit or culprit.bot or culprit.id in whitelist.get(gid, []): return
    should_ban = record_action_and_check(guild.id, culprit.id, 'ban')
    if should_ban:
        try:
            await guild.ban(culprit, reason="Anti-Nuke: Triggered mass-ban limit.")
            nuke_log = server_logs.get(gid, {}).get("audit-antinuke")
            if nuke_log: await bot.get_channel(nuke_log).send(f"🚨 **ANTI-NUKE TRIGGERED:** Banned {culprit.mention} for mass-banning members.")
        except discord.Forbidden:
            pass

@bot.event
async def on_message_delete(message):
    if message.author.bot: return
    gid = str(message.guild.id)
    log_id = server_logs.get(gid, {}).get("audit-deleted")
    if log_id:
        log_channel = bot.get_channel(log_id)
        if log_channel:
            timestamp = discord.utils.utcnow().strftime("%B %d, %Y at %I:%M %p UTC")
            embed = discord.Embed(title="🗑️ Message Deleted", color=discord.Color.red())
            embed.add_field(name="Author", value=message.author.mention, inline=True)
            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
            embed.add_field(name="Content", value=message.content if message.content else "*No text*", inline=False)
            embed.set_footer(text=f"Deleted on {timestamp}")
            await log_channel.send(embed=embed)

# --- REACTION ROLES ---
@bot.tree.command(name="reaction_panel", description="Create an interactive role assignment panel.")
@app_commands.describe(
    channel="Where to post the panel", title="Title of the panel", description="Text above the roles",
    role1="First Role to assign", emoji1="Emoji for Role 1",
    role2="Second Role to assign", emoji2="Emoji for Role 2",
    role3="Third Role to assign", emoji3="Emoji for Role 3"
)
@app_commands.default_permissions(manage_roles=True)
async def reaction_panel(
    interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str,
    role1: discord.Role, emoji1: str, role2: discord.Role = None, emoji2: str = None, role3: discord.Role = None, emoji3: str = None
):
    await interaction.response.defer(ephemeral=True)
    
    bot_role = interaction.guild.me.top_role
    for role in [role1, role2, role3]:
        if role and role >= bot_role:
            await interaction.followup.send(f"❌ Error: My role must be physically higher than {role.name} to assign it.")
            return

    # NEW: Advanced API Emoji Parser
    def parse_emoji(input_str):
        if not input_str: return None
        input_str = input_str.strip()
        
        # Scenario 1: Raw custom emoji tag string
        match = re.match(r'<(a?):([a-zA-Z0-9_]+):([0-9]+)>', input_str)
        if match:
            return discord.PartialEmoji(name=match.group(2), id=int(match.group(3)), animated=bool(match.group(1)))
            
        # Scenario 2: User provided the shortcode name without the ID
        clean_name = input_str.strip(':')
        for e in interaction.guild.emojis:
            if e.name == clean_name:
                return e 
                
        # Scenario 3: Standard unicode emoji
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
        # Resolves PartialEmoji/Emoji objects back to string for the embed text
        panel_text += f"{str(emoji)} - {role.mention}\n\n"
        
    embed.add_field(name="Available Roles", value=panel_text, inline=False)
    embed.set_footer(text="React below to claim your roles!")

    try:
        msg = await channel.send(embed=embed)
        msg_id = str(msg.id)
        reaction_roles[msg_id] = {}
        
        for role, emoji_obj in roles_setup:
            # API can now safely process the raw PartialEmoji object
            await msg.add_reaction(emoji_obj) 
            # We strictly save the string translation to the DB to match Discord payloads later
            reaction_roles[msg_id][str(emoji_obj)] = role.id
            
        save_data()
        await interaction.followup.send(f"✅ Reaction panel deployed successfully in {channel.mention}.")
        
    except discord.Forbidden:
        await interaction.followup.send("❌ Error: I lack permissions to send messages or add reactions in that channel.")
    except discord.HTTPException:
        if 'msg' in locals(): await msg.delete() 
        await interaction.followup.send("❌ Error: One or more emojis are invalid. Ensure they belong to this server.")

# --- EXPRESSIONS (EMOJIS & RIGHT-CLICK STICKER STEAL) ---
@bot.tree.command(name="emoji_steal", description="Steal emojis and add them to your server.")
@app_commands.describe(emojis="Paste one or multiple emojis here to steal them in bulk.")
@app_commands.default_permissions(manage_expressions=True)
async def emoji_steal(interaction: discord.Interaction, emojis: str):
    await interaction.response.defer(ephemeral=True)
    matches = re.findall(r'<(a?):([a-zA-Z0-9_]+):([0-9]+)>', emojis)
    
    if not matches:
        await interaction.followup.send("❌ No valid custom emojis found in your message.", ephemeral=True)
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
                        await interaction.followup.send("❌ I lack permissions to manage emojis.")
                        return
                    except discord.HTTPException:
                        failed += 1 
                        
    result_msg = f"✅ Successfully stole **{len(added)}** emojis: {' '.join(added)}"
    if failed > 0: result_msg += f"\n❌ Failed to add {failed} (your server might be out of slots)."
    await interaction.followup.send(result_msg, ephemeral=True)

@bot.tree.context_menu(name="Steal Sticker")
@app_commands.default_permissions(manage_expressions=True)
async def steal_sticker_context(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer(ephemeral=True)
    
    if not message.stickers:
        await interaction.followup.send("❌ No sticker found in that message.", ephemeral=True)
        return
        
    sticker_item = message.stickers[0]
    
    try:
        full_sticker = await sticker_item.fetch()
    except discord.HTTPException:
        await interaction.followup.send("❌ Failed to fetch full sticker data from Discord's servers.", ephemeral=True)
        return
        
    if type(full_sticker) == discord.StandardSticker:
        await interaction.followup.send("❌ You cannot steal Discord's official built-in standard stickers.", ephemeral=True)
        return
        
    try:
        img_bytes = await full_sticker.read()
        new_sticker = await interaction.guild.create_sticker(
            name=full_sticker.name,
            description="Stolen by Friday",
            emoji=full_sticker.emoji or "✨",
            file=discord.File(fp=io.BytesIO(img_bytes), filename="sticker.png")
        )
        await interaction.followup.send(f"✅ Successfully stole sticker: **{new_sticker.name}**", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ I lack permissions to manage stickers.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Failed to add sticker. Error: {e.text}", ephemeral=True)

# --- XP & LEVELING COMMANDS ---
@bot.tree.command(name="level_setup", description="Activate leveling and set the channel for Level Up updates.")
@app_commands.default_permissions(manage_channels=True)
async def level_setup(interaction: discord.Interaction, channel: discord.TextChannel):
    gid = str(interaction.guild.id)
    level_channels[gid] = channel.id
    save_data()
    await interaction.response.send_message(f"✅ Leveling system activated! Updates will now be posted in {channel.mention}.", ephemeral=True)

@bot.tree.command(name="rank", description="Check your current Level and XP.")
async def rank(interaction: discord.Interaction, user: discord.Member = None):
    await interaction.response.defer() 
    user = user or interaction.user
    gid = str(interaction.guild.id)
    uid = str(user.id)
    
    if gid not in xp_data or uid not in xp_data[gid]:
        await interaction.followup.send(f"{user.display_name} has no XP yet! Send some messages first.")
        return

    user_stats = xp_data[gid][uid]
    sorted_users = sorted(xp_data[gid].items(), key=lambda item: (item[1]['level'], item[1]['xp']), reverse=True)
    rank_pos = [i[0] for i in sorted_users].index(uid) + 1
    
    current_xp = user_stats["xp"]
    current_level = user_stats["level"]
    next_xp = get_xp_requirement(current_level)
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

@bot.tree.command(name="leaderboard", description="View the top 10 most active members.")
async def leaderboard(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    if gid not in xp_data or not xp_data[gid]:
        await interaction.response.send_message("No one has earned any XP yet!")
        return

    sorted_users = sorted(xp_data[gid].items(), key=lambda item: (item[1]['level'], item[1]['xp']), reverse=True)[:10]
    
    embed = discord.Embed(title="🏆 Server Leaderboard", color=discord.Color.gold())
    for index, (uid, data) in enumerate(sorted_users, start=1):
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else f"Unknown User ({uid})"
        embed.add_field(name=f"#{index} - {name}", value=f"Level: **{data['level']}** | XP: **{data['xp']}**", inline=False)
        
    await interaction.response.send_message(embed=embed)

# --- ANTI-ABUSE COMMANDS ---
@bot.tree.command(name="anti_abuse", description="Add bad words to the filter, separated by commas.")
@app_commands.default_permissions(manage_messages=True)
async def anti_abuse(interaction: discord.Interaction, words: str):
    gid = str(interaction.guild.id)
    if gid not in banned_words:
        banned_words[gid] = []
        
    new_words = [w.strip().lower() for w in words.split(',') if w.strip()]
    banned_words[gid].extend(new_words)
    banned_words[gid] = list(set(banned_words[gid])) 
    save_data()
    
    await interaction.response.send_message(f"✅ Successfully added `{', '.join(new_words)}` to the word filter.", ephemeral=True)

@bot.tree.command(name="anti_abuse_remove", description="Remove a specific word from the filter.")
@app_commands.default_permissions(manage_messages=True)
async def anti_abuse_remove(interaction: discord.Interaction, word: str):
    gid = str(interaction.guild.id)
    if gid not in banned_words or not banned_words[gid]:
        await interaction.response.send_message("🛡️ The word filter is currently empty.", ephemeral=True)
        return

    target_word = word.strip().lower()
    
    if target_word in banned_words[gid]:
        banned_words[gid].remove(target_word)
        save_data()
        await interaction.response.send_message(f"✅ Successfully removed `{target_word}` from the word filter.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ The word `{target_word}` is not currently in the filter.", ephemeral=True)

@bot.tree.command(name="anti_abuse_list", description="View all currently banned words in the server's filter.")
@app_commands.default_permissions(manage_messages=True)
async def anti_abuse_list(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    word_list = banned_words.get(gid, [])
    
    if not word_list:
        await interaction.response.send_message("🛡️ The anti-abuse filter is currently empty.", ephemeral=True)
        return
        
    words_formatted = ", ".join(f"`{w}`" for w in word_list)
    embed = discord.Embed(title="🤬 Anti-Abuse Word List", description=words_formatted, color=discord.Color.orange())
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="anti_abuse_whitelist_add", description="Make a user IMMUNE to the word filter.")
@app_commands.default_permissions(manage_messages=True)
async def anti_abuse_whitelist_add(interaction: discord.Interaction, user: discord.Member):
    gid = str(interaction.guild.id)
    if gid not in abuse_whitelist:
        abuse_whitelist[gid] = []
        
    if user.id not in abuse_whitelist[gid]:
        abuse_whitelist[gid].append(user.id)
        save_data()
        await interaction.response.send_message(f"✅ {user.mention} is now IMMUNE to the Anti-Abuse word filter.", ephemeral=True)
    else:
        await interaction.response.send_message(f"✅ {user.mention} is already immune.", ephemeral=True)

@bot.tree.command(name="anti_abuse_whitelist_remove", description="Remove a user's immunity to the word filter.")
@app_commands.default_permissions(manage_messages=True)
async def anti_abuse_whitelist_remove(interaction: discord.Interaction, user: discord.Member):
    gid = str(interaction.guild.id)
    if gid in abuse_whitelist and user.id in abuse_whitelist[gid]:
        abuse_whitelist[gid].remove(user.id)
        save_data()
        await interaction.response.send_message(f"❌ {user.mention} is no longer immune to the word filter.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ {user.mention} was not on the whitelist.", ephemeral=True)

# --- INFRASTRUCTURE & SETTINGS COMMANDS ---
@bot.tree.command(name="antinuke_toggle", description="Turn the Anti-Nuke system ON or OFF.")
@app_commands.choices(status=[
    app_commands.Choice(name="Turn ON", value=1),
    app_commands.Choice(name="Turn OFF", value=0)
])
@app_commands.default_permissions(administrator=True)
async def antinuke_toggle(interaction: discord.Interaction, status: app_commands.Choice[int]):
    gid = str(interaction.guild.id)
    is_active = bool(status.value)
    antinuke_active[gid] = is_active
    save_data()
    state = "✅ ON" if is_active else "❌ OFF"
    await interaction.response.send_message(f"🛡️ Anti-Nuke system is now **{state}**.", ephemeral=True)

@bot.tree.command(name="antinuke_refresh", description="Auto-create and link missing Friday security log channels.")
@app_commands.default_permissions(administrator=True)
async def antinuke_refresh(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    gid = str(guild.id)
    category = discord.utils.get(guild.categories, name="Friday Security Logs")
    if not category: category = await guild.create_category("Friday Security Logs")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True)
    }
    channels_to_check = [
        "audit-deleted", "audit-banned", "audit-timeouts", "audit-whitelisted", 
        "audit-antinuke", "audit-abuse", "audit-antiraid", "audit-antispam", 
        "audit-roles", "audit-channels"
    ]
    created_list = []
    if gid not in server_logs: server_logs[gid] = {}

    for name in channels_to_check:
        existing_channel = discord.utils.get(guild.channels, name=name)
        if not existing_channel:
            existing_channel = await guild.create_text_channel(name, category=category, overwrites=overwrites)
            created_list.append(existing_channel.mention)
        server_logs[gid][name] = existing_channel.id
        
    save_data()
    if created_list: await interaction.followup.send(f"✅ Infrastructure built! Created: {', '.join(created_list)}")
    else: await interaction.followup.send("✅ All log channels already exist and are fully linked to Friday's systems.")

@bot.tree.command(name="antinuke_limit", description="Set limits for anti-nuke protection (within a 60s window).")
@app_commands.choices(action_type=[
    app_commands.Choice(name="Channel Deletions", value="channel"),
    app_commands.Choice(name="Member Bans", value="ban")
])
@app_commands.default_permissions(administrator=True)
async def antinuke_limit(interaction: discord.Interaction, action_type: app_commands.Choice[str], limit: int):
    gid = str(interaction.guild.id)
    if gid not in nuke_settings: nuke_settings[gid] = {}
    nuke_settings[gid][action_type.value] = limit
    save_data()
    await interaction.response.send_message(f"🛡️ Anti-nuke updated: A user will be banned if they trigger {limit} **{action_type.name}** within 60 seconds.", ephemeral=True)

@bot.tree.command(name="whitelist_add", description="Add a user to the Anti-Nuke whitelist.")
@app_commands.default_permissions(administrator=True)
async def whitelist_add(interaction: discord.Interaction, user: discord.Member):
    gid = str(interaction.guild.id)
    if gid not in whitelist: whitelist[gid] = []
    if user.id not in whitelist[gid]:
        whitelist[gid].append(user.id)
        save_data()
        log_id = server_logs.get(gid, {}).get("audit-whitelisted")
        if log_id: await bot.get_channel(log_id).send(f"🛡️ {user.mention} was added to the Anti-Nuke whitelist by {interaction.user.mention}.")
        await interaction.response.send_message(f"✅ {user.mention} has been added to the Anti-Nuke whitelist.", ephemeral=True)
    else:
        await interaction.response.send_message(f"✅ {user.mention} is already whitelisted.", ephemeral=True)

@bot.tree.command(name="whitelist_remove", description="Remove a user from the Anti-Nuke whitelist.")
@app_commands.default_permissions(administrator=True)
async def whitelist_remove(interaction: discord.Interaction, user: discord.Member):
    gid = str(interaction.guild.id)
    if gid in whitelist and user.id in whitelist[gid]:
        whitelist[gid].remove(user.id)
        save_data()
        log_id = server_logs.get(gid, {}).get("audit-whitelisted")
        if log_id: await bot.get_channel(log_id).send(f"🛡️ {user.mention} was removed from the Anti-Nuke whitelist by {interaction.user.mention}.")
        await interaction.response.send_message(f"❌ {user.mention} has been removed from the Anti-Nuke whitelist.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ {user.mention} was not on the Anti-Nuke whitelist.", ephemeral=True)

# --- MODERATION SLASH COMMANDS ---
@bot.tree.command(name="ban", description="Ban a member from the server.")
@app_commands.default_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Rule violation."):
    if interaction.user.top_role <= member.top_role and interaction.user != interaction.guild.owner:
        await interaction.response.send_message("❌ Security Alert: You cannot ban someone with a higher or equal role than you.", ephemeral=True)
        return
    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(f'🔨 Successfully banned {member.mention}. Reason: {reason}')
    except discord.Forbidden:
        await interaction.response.send_message("❌ Error: My role is not high enough to ban this user.", ephemeral=True)

@bot.tree.command(name="unban", description="Unban a user by their ID.")
@app_commands.default_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "Pardoned."):
    try:
        user = discord.Object(id=int(user_id))
        await interaction.guild.unban(user, reason=reason)
        await interaction.response.send_message(f'✅ Successfully unbanned user ID {user_id}.')
    except ValueError:
        await interaction.response.send_message("❌ Error: User ID must be a number.", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ Error: That user is not currently banned.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Error: I lack permission to unban users.", ephemeral=True)

@bot.tree.command(name="timeout", description="Timeout a member for a set number of minutes.")
@app_commands.default_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Rule violation."):
    if interaction.user.top_role <= member.top_role and interaction.user != interaction.guild.owner:
        await interaction.response.send_message("❌ Security Alert: You cannot timeout someone with a higher or equal role than you.", ephemeral=True)
        return
    try:
        duration = datetime.timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await interaction.response.send_message(f'⏱️ {member.mention} timed out for {minutes} minutes.')
        gid = str(interaction.guild.id)
        log_id = server_logs.get(gid, {}).get("audit-timeouts")
        if log_id: await bot.get_channel(log_id).send(f"⏱️ **Timeout:** {member.mention} timed out for {minutes}m by {interaction.user.mention}.")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Error: My role is not high enough to timeout this user.", ephemeral=True)

@bot.tree.command(name="untimeout", description="Remove a timeout from a member.")
@app_commands.default_permissions(moderate_members=True)
async def untimeout(interaction: discord.Interaction, member: discord.Member, reason: str = "Timeout lifted."):
    if interaction.user.top_role <= member.top_role and interaction.user != interaction.guild.owner:
        await interaction.response.send_message("❌ Security Alert: You cannot remove a timeout from someone with a higher or equal role.", ephemeral=True)
        return
    if not member.is_timed_out():
        await interaction.response.send_message(f"❌ {member.mention} is not currently timed out.", ephemeral=True)
        return
    if member.guild_permissions.administrator:
        await interaction.response.send_message("❌ Cannot modify timeout: Discord restricts timeout actions on server Administrators.", ephemeral=True)
        return
    if member.top_role >= interaction.guild.me.top_role and member != interaction.guild.owner:
        await interaction.response.send_message(f"❌ Error: My highest role is not high enough to modify {member.mention}'s timeout status.", ephemeral=True)
        return
    try:
        await member.timeout(None, reason=reason)
        await interaction.response.send_message(f'✅ Removed the timeout for {member.mention}.')
    except discord.Forbidden:
        await interaction.response.send_message("❌ Error: I lack permission to modify this user's timeout status.", ephemeral=True)

@bot.tree.command(name="purge", description="Delete a specific number of recent messages in this channel.")
@app_commands.default_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Successfully purged {len(deleted)} messages from this channel.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ Error: I lack permission to manage messages in this channel.", ephemeral=True)
    except discord.HTTPException:
        await interaction.followup.send("❌ Error: Discord restricts bots from bulk-deleting messages older than 14 days.", ephemeral=True)

# --- CHANNEL PRIVACY COMMANDS ---
@bot.tree.command(name="private", description="Make a specific channel private.")
@app_commands.default_permissions(manage_channels=True)
async def private_channel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    target = channel or interaction.channel
    await target.set_permissions(interaction.guild.default_role, read_messages=False)
    await interaction.response.send_message(f"🔒 {target.mention} is now private.")

@bot.tree.command(name="unprivate", description="Unprivate a specific channel or ALL channels.")
@app_commands.describe(channel="Channel to unprivate (leave empty if using 'all_channels')", all_channels="Set to True to unprivate ALL text channels")
@app_commands.default_permissions(manage_channels=True)
async def unprivate_channel(interaction: discord.Interaction, channel: discord.TextChannel = None, all_channels: bool = False):
    await interaction.response.defer()
    if all_channels:
        count = 0
        for ch in interaction.guild.text_channels:
            if ch.overwrites_for(interaction.guild.default_role).read_messages == False:
                await ch.set_permissions(interaction.guild.default_role, read_messages=None)
                count += 1
        await interaction.followup.send(f"🔓 Successfully unprivated {count} channels.")
    else:
        target = channel or interaction.channel
        await target.set_permissions(interaction.guild.default_role, read_messages=None)
        await interaction.followup.send(f"🔓 {target.mention} is no longer private.")

@bot.tree.command(name="ignore_private_add", description="Add a channel to the ignore list (won't be affected by force private).")
@app_commands.default_permissions(manage_channels=True)
async def ignore_private_add(interaction: discord.Interaction, channel: discord.TextChannel):
    gid = str(interaction.guild.id)
    if gid not in ignored_private:
        ignored_private[gid] = []
    if channel.id not in ignored_private[gid]:
        ignored_private[gid].append(channel.id)
        save_data()
        await interaction.response.send_message(f"✅ {channel.mention} added to the privacy ignore list.")
    else:
        await interaction.response.send_message(f"⚠️ {channel.mention} is already in the ignore list.")

@bot.tree.command(name="ignore_private_remove", description="Remove a channel from the ignore list.")
@app_commands.default_permissions(manage_channels=True)
async def ignore_private_remove(interaction: discord.Interaction, channel: discord.TextChannel):
    gid = str(interaction.guild.id)
    if gid in ignored_private and channel.id in ignored_private[gid]:
        ignored_private[gid].remove(channel.id)
        save_data()
        await interaction.response.send_message(f"❌ {channel.mention} removed from the privacy ignore list.")
    else:
        await interaction.response.send_message(f"⚠️ {channel.mention} is not in the ignore list.")

@bot.tree.command(name="force_private", description="Make ALL channels private EXCEPT those in the ignore list.")
@app_commands.default_permissions(manage_channels=True)
async def force_private(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    ignore_list = ignored_private.get(gid, [])
    
    if not ignore_list:
        await interaction.response.send_message("❌ Cannot execute force private! You must have at least 1 channel in the ignore list (use `/ignore_private_add`) so members have somewhere to go.", ephemeral=True)
        return
        
    await interaction.response.defer()
    count = 0
    for ch in interaction.guild.text_channels:
        if ch.id not in ignore_list:
            # Check if it's already private to avoid rate limits
            if ch.overwrites_for(interaction.guild.default_role).read_messages != False:
                await ch.set_permissions(interaction.guild.default_role, read_messages=False)
                count += 1
                
    await interaction.followup.send(f"🔒 **LOCKDOWN INITIATED:** {count} channels have been set to private. Members can only see the {len(ignore_list)} ignored channels.")


@bot.tree.command(name="joke", description="Get a hilarious Hinglish, Desi, or tech joke!")
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
async def joke(interaction: discord.Interaction, category: str = "any"):
    joke_data = get_random_joke(category=category)
    embed = build_joke_embed(joke_data, user=interaction.user)
    view = JokeView(category=category, author_id=interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="ping", description="Check Friday's latency.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message('Pong! Friday is fully operational and listening.', ephemeral=True)

@bot.tree.command(name="serverinfo", description="Display information about the server.")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"📊 Server Info: {guild.name}", color=discord.Color.blue())
    created = guild.created_at.strftime("%B %d, %Y")
    owner_mention = guild.owner.mention if guild.owner else "Unknown"
    
    embed.add_field(name="Owner", value=owner_mention, inline=True)
    embed.add_field(name="Total Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Total Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="Server Created On", value=created, inline=False)
    
    if guild.icon: embed.set_thumbnail(url=guild.icon.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="help", description="View all of Friday's commands and features.")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="🌸 Friday Command Center", description="Here are all the commands you can use with Friday!", color=discord.Color.blue())
    
    embed.add_field(name="🛡️ Moderation", value="`/ban`\n`/unban`\n`/timeout`\n`/untimeout`\n`/purge`", inline=False)
    embed.add_field(name="⚙️ Security", value="`/antinuke_toggle`\n`/antinuke_refresh`\n`/antinuke_limit`\n`/whitelist_add`\n`/whitelist_remove`\n`/anti_abuse`\n`/anti_abuse_remove`\n`/anti_abuse_list`\n`/anti_abuse_whitelist_add`\n`/anti_abuse_whitelist_remove`", inline=False)
    embed.add_field(name="🎉 Community & Leveling", value="`/level_setup`\n`/rank`\n`/leaderboard`\n`/reaction_panel`\n`/joke`", inline=False)
    embed.add_field(name="🎨 Expressions", value="`/emoji_steal`\n`Right-Click Sticker -> Apps -> Steal Sticker`", inline=False)
    embed.add_field(name="🔒 Channel Privacy", value="`/private`\n`/unprivate`\n`/force_private`\n`/ignore_private_add`\n`/ignore_private_remove`", inline=False)
    embed.add_field(name="📊 Utility", value="`/ping`\n`/serverinfo`\n`/help`\n`/sync`", inline=False)
    
    embed.set_footer(text=f"Requested by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="sync", description="Forcefully sync the global slash command list to this server.")
@app_commands.default_permissions(administrator=True)
async def sync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    bot.tree.clear_commands(guild=interaction.guild)
    await bot.tree.sync(guild=interaction.guild)
    for cmd in bot.tree.get_commands():
        if cmd.name in ("avatar", "avtar"):
            cmd.guild_only = False
        else:
            try:
                cmd.guild_only = True
            except Exception:
                pass
    synced = await bot.tree.sync()
    await interaction.followup.send(f"🧹 Cleaned up local duplicates! {len(synced)} global commands registered (DM restrictions active: only /avatar in DMs). Press Ctrl+R to refresh your Discord client.")

bot.run(TOKEN)