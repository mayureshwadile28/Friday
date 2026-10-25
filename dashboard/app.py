from flask import Flask, render_template, jsonify, request as flask_request
import json
import os
import sys
import uuid
import requests
import asyncio
import discord
from dotenv import load_dotenv

# Ensure parent directory is in sys.path to import database and models
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from database import db
from emoji_utils import replace_plain_emojis, parse_btn

# Load environment variables
load_dotenv(os.path.join(PARENT_DIR, '.env'))

app = Flask(__name__)
BOT_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_API = "https://discord.com/api/v10"

bot_instance = None

def set_bot_instance(b):
    global bot_instance
    bot_instance = b

# ───────────────────── Helpers ─────────────────────

def discord_headers():
    return {"Authorization": f"Bot {BOT_TOKEN}"}

def fetch_user_info(user_id):
    """Try to resolve user info via bot guilds cache, global bot user cache, then Discord API fallback."""
    uid_int = int(user_id) if str(user_id).isdigit() else None
    if bot_instance and uid_int:
        user = bot_instance.get_user(uid_int)
        if not user:
            for g in bot_instance.guilds:
                m = g.get_member(uid_int)
                if m:
                    user = m
                    break
        if user:
            avatar_url = str(user.display_avatar.url) if user.display_avatar else None
            return {
                "id": str(user.id),
                "username": getattr(user, "display_name", None) or user.name,
                "avatar": avatar_url
            }

    try:
        resp = requests.get(f"{DISCORD_API}/users/{user_id}", headers=discord_headers(), timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            avatar_hash = data.get("avatar")
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=64" if avatar_hash else None
            return {
                "id": str(user_id),
                "username": data.get("global_name") or data.get("username", f"User {user_id}"),
                "avatar": avatar_url
            }
    except Exception:
        pass
    return {"id": str(user_id), "username": f"User {user_id}", "avatar": None}

# ───────────────────── Pages ─────────────────────

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# ───────────────────── API: Bot Profile & Guilds ─────────────────────

@app.route('/api/bot/profile')
def get_bot_profile():
    if bot_instance and bot_instance.user:
        avatar_url = str(bot_instance.user.display_avatar.url) if bot_instance.user.display_avatar else None
        return jsonify({
            "name": bot_instance.user.name,
            "display_name": bot_instance.user.display_name or bot_instance.user.name,
            "avatar": avatar_url,
            "id": str(bot_instance.user.id)
        })
    try:
        resp = requests.get(f"{DISCORD_API}/users/@me", headers=discord_headers(), timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            ext = "gif" if avatar_hash and avatar_hash.startswith("a_") else "png"
            avatar_url = f"https://cdn.discordapp.com/avatars/{uid}/{avatar_hash}.{ext}?size=256" if avatar_hash else None
            return jsonify({
                "name": data.get("username", "Friday"),
                "display_name": data.get("global_name") or data.get("username", "Friday"),
                "avatar": avatar_url,
                "id": str(uid)
            })
    except Exception:
        pass
    return jsonify({"name": "Friday", "display_name": "Friday", "avatar": None, "id": None})

@app.route('/api/guilds')
def get_guilds():
    # Priority 1: Direct bot cache
    if bot_instance and bot_instance.guilds:
        result = []
        for g in bot_instance.guilds:
            icon_url = str(g.icon.url) if g.icon else None
            result.append({"id": str(g.id), "name": g.name, "icon": icon_url})
        return jsonify(result)

    # Priority 2: Discord REST API
    try:
        resp = requests.get(f"{DISCORD_API}/users/@me/guilds", headers=discord_headers(), timeout=5)
        if resp.status_code == 200:
            guilds = resp.json()
            result = []
            for g in guilds:
                icon_hash = g.get("icon")
                icon_url = f"https://cdn.discordapp.com/icons/{g['id']}/{icon_hash}.png?size=64" if icon_hash else None
                result.append({"id": str(g["id"]), "name": g["name"], "icon": icon_url})
            return jsonify(result)
    except Exception:
        pass

    # Priority 3: Fallback from in-memory Database
    guild_ids = set()
    for store in [db.nuke_settings, db.whitelist, db.antinuke_active, db.xp_data, db.level_channels]:
        if isinstance(store, dict):
            guild_ids.update(store.keys())
    return jsonify([{"id": str(gid), "name": f"Server {gid}", "icon": None} for gid in guild_ids if str(gid).isdigit()])

@app.route('/api/guild/<gid>/members')
def get_members(gid):
    if bot_instance:
        guild = bot_instance.get_guild(int(gid))
        if guild and guild.members:
            result = []
            for m in guild.members:
                if m.bot: continue
                avatar = str(m.display_avatar.url) if m.display_avatar else None
                result.append({
                    "id": str(m.id),
                    "username": m.display_name or m.name,
                    "avatar": avatar
                })
            if result:
                return jsonify(result)

    try:
        resp = requests.get(f"{DISCORD_API}/guilds/{gid}/members?limit=1000", headers=discord_headers(), timeout=5)
        if resp.status_code == 200:
            members = resp.json()
            result = []
            for m in members:
                u = m.get("user", {})
                if u.get("bot"): continue
                avatar = u.get("avatar")
                avatar_url = f"https://cdn.discordapp.com/avatars/{u['id']}/{avatar}.png?size=64" if avatar else None
                result.append({
                    "id": str(u.get("id")),
                    "username": u.get("global_name") or u.get("username", f"User {u.get('id')}"),
                    "avatar": avatar_url
                })
            return jsonify(result)
    except Exception:
        pass
    return jsonify([])

@app.route('/api/guild/<gid>/channels')
def get_channels(gid):
    if bot_instance:
        guild = bot_instance.get_guild(int(gid))
        if guild:
            channels = []
            for c in guild.channels:
                if c.type in (discord.ChannelType.text, discord.ChannelType.news):
                    channels.append({
                        "id": str(c.id),
                        "name": c.name,
                        "category": c.category.name if c.category else "General / Uncategorized"
                    })
            return jsonify(channels)

    try:
        resp = requests.get(f"{DISCORD_API}/guilds/{gid}/channels", headers=discord_headers(), timeout=5)
        if resp.status_code == 200:
            channels = resp.json()
            result = [{"id": str(c["id"]), "name": c["name"]} for c in channels if c.get("type") in (0, 5)]
            return jsonify(result)
    except Exception:
        pass
    return jsonify([])

@app.route('/api/guild/<gid>/voice-channels')
def get_voice_channels(gid):
    if bot_instance:
        guild = bot_instance.get_guild(int(gid))
        if guild:
            result = [{"id": str(c.id), "name": c.name} for c in guild.voice_channels]
            return jsonify(result)

    try:
        resp = requests.get(f"{DISCORD_API}/guilds/{gid}/channels", headers=discord_headers(), timeout=5)
        if resp.status_code == 200:
            channels = resp.json()
            result = [{"id": str(c["id"]), "name": c["name"]} for c in channels if c.get("type") == 2]
            return jsonify(result)
    except Exception:
        pass
    return jsonify([])


@app.route('/api/guild/<gid>/emojis')
def get_guild_emojis(gid):
    if bot_instance:
        result = []
        seen_ids = set()
        guild = bot_instance.get_guild(int(gid))
        
        # Current guild emojis first
        if guild:
            for e in guild.emojis:
                if not e.available: continue
                seen_ids.add(e.id)
                result.append({
                    "id": str(e.id),
                    "name": e.name,
                    "animated": bool(e.animated),
                    "url": str(e.url),
                    "code": f"<a:{e.name}:{e.id}>" if e.animated else f"<:{e.name}:{e.id}>"
                })
                
        # Removed global loop so it ONLY shows the current server's emojis to prevent confusion.
        return jsonify(result)

    try:
        resp = requests.get(f"{DISCORD_API}/guilds/{gid}/emojis", headers=discord_headers(), timeout=5)
        if resp.status_code == 200:
            emojis = resp.json()
            result = []
            for e in emojis:
                if not e.get("available", True): continue
                is_animated = bool(e.get("animated", False))
                ext = "gif" if is_animated else "png"
                result.append({
                    "id": str(e["id"]),
                    "name": e["name"],
                    "animated": is_animated,
                    "url": f"https://cdn.discordapp.com/emojis/{e['id']}.{ext}?size=48&quality=lossless",
                    "code": f"<a:{e['name']}:{e['id']}>" if is_animated else f"<:{e['name']}:{e['id']}>"
                })
            return jsonify(result)
    except Exception:
        pass
    return jsonify([])

# ───────────────────── API: Anti-Nuke (Direct In-Memory DB Sync) ─────────────────────

@app.route('/api/guild/<gid>/antinuke')
def get_antinuke(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    try:
        db.reload()
    except Exception:
        pass
    whitelist_ids = db.whitelist.get(gid_str) or db.whitelist.get(gid_int) or []
    whitelist_users = [fetch_user_info(uid) for uid in whitelist_ids]

    return jsonify({
        "active": db.antinuke_active.get(gid_str, db.antinuke_active.get(gid_int, True)),
        "limits": {
            "channel": (db.nuke_settings.get(gid_str) or db.nuke_settings.get(gid_int) or {}).get("channel", 3),
            "ban": (db.nuke_settings.get(gid_str) or db.nuke_settings.get(gid_int) or {}).get("ban", 3),
            "kick": (db.nuke_settings.get(gid_str) or db.nuke_settings.get(gid_int) or {}).get("kick", 3),
            "role": (db.nuke_settings.get(gid_str) or db.nuke_settings.get(gid_int) or {}).get("role", 3),
        },
        "whitelist": whitelist_users
    })

@app.route('/api/guild/<gid>/antinuke/toggle', methods=['POST'])
def toggle_antinuke(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    is_active = body.get("active", True)
    db.antinuke_active[gid_str] = is_active
    db.save_data()
    return jsonify({"active": db.antinuke_active[gid_str]})

@app.route('/api/guild/<gid>/antinuke/sync', methods=['POST'])
def sync_antinuke_channels(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."})
    async def do_sync():
        guild = bot_instance.get_guild(int(gid))
        if not guild: raise Exception("Guild not found.")
        sec_cog = bot_instance.get_cog("Security")
        if not sec_cog: raise Exception("Security system not loaded.")
        return await sec_cog.auto_sync_security_channels(guild)
    try:
        fut = asyncio.run_coroutine_threadsafe(do_sync(), bot_instance.loop)
        cnt = fut.result(timeout=6)
        return jsonify({"success": True, "count": cnt})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/antinuke/refresh', methods=['POST'])
def refresh_antinuke_channels(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."})
    async def do_refresh():
        guild = bot_instance.get_guild(int(gid))
        if not guild: raise Exception("Guild not found.")
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
        created = []
        gid_str = str(guild.id)
        if gid_str not in db.server_logs: db.server_logs[gid_str] = {}
        for name in channels_to_check:
            ch = discord.utils.get(guild.channels, name=name)
            if not ch:
                ch = await guild.create_text_channel(name, category=category, overwrites=overwrites)
                created.append(name)
            db.server_logs[gid_str][name] = ch.id
        db.save_data()
        return len(created)
    try:
        fut = asyncio.run_coroutine_threadsafe(do_refresh(), bot_instance.loop)
        cnt = fut.result(timeout=10)
        return jsonify({"success": True, "created": cnt})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/antinuke/limits', methods=['POST'])
def update_limits(gid):
    gid_str = str(gid)
    if gid_str not in db.nuke_settings:
        db.nuke_settings[gid_str] = {}
        
    limits = flask_request.json or {}
    for key in ["channel", "ban", "kick", "role"]:
        if key in limits:
            val = int(limits[key])
            if val > 0:
                db.nuke_settings[gid_str][key] = val
            elif key in db.nuke_settings[gid_str]:
                del db.nuke_settings[gid_str][key]
                
    db.save_data()
    print(f"🔄 [SYNC SUCCESS] Anti-Nuke limits updated in memory for Guild {gid_str}: {db.nuke_settings[gid_str]}")
    return jsonify({"limits": db.nuke_settings[gid_str]})

@app.route('/api/guild/<gid>/security', methods=['GET'])
def get_security_settings(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    try:
        db.reload()
    except Exception:
        pass
    sec_cog = bot_instance.get_cog("Security") if bot_instance else None
    cfg = sec_cog.get_security_config(gid_str) if sec_cog else (db.security_settings.get(gid_str) or db.security_settings.get(gid_int) or {})
    server_logs = db.server_logs.get(gid_str) or db.server_logs.get(gid_int) or {}
    
    raw_fw = db.feature_whitelists.get(gid_str) or db.feature_whitelists.get(gid_int) or {}
    feature_whitelists_data = {}
    for feat, uids in raw_fw.items():
        feature_whitelists_data[feat] = [fetch_user_info(uid) for uid in uids]

    raw_wl = db.whitelist.get(gid_str) or db.whitelist.get(gid_int) or []
    whitelist_users = [fetch_user_info(uid) for uid in raw_wl]

    return jsonify({
        "success": True,
        "antinuke_active": db.antinuke_active.get(gid_str, db.antinuke_active.get(gid_int, True)),
        "whitelist": whitelist_users,
        "nuke_settings": db.nuke_settings.get(gid_str) or db.nuke_settings.get(gid_int) or {},
        "security_settings": cfg,
        "server_logs": server_logs,
        "feature_whitelists": feature_whitelists_data
    })

@app.route('/api/guild/<gid>/security/feature_whitelist/add', methods=['POST'])
def feature_whitelist_add(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    feature = body.get("feature")
    user_id = body.get("user_id")
    if not feature or not user_id:
        return jsonify({"success": False, "error": "Feature and user ID required"})
    try:
        db.reload()
    except Exception:
        pass
    if gid_str not in db.feature_whitelists:
        db.feature_whitelists[gid_str] = {}
    if feature not in db.feature_whitelists[gid_str]:
        db.feature_whitelists[gid_str][feature] = []
    try:
        uid = int(user_id)
        if uid not in db.feature_whitelists[gid_str][feature]:
            db.feature_whitelists[gid_str][feature].append(uid)
            db.save_data()
        return jsonify({"success": True, "user": fetch_user_info(uid)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/security/feature_whitelist/remove', methods=['POST'])
def feature_whitelist_remove(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    body = flask_request.json or {}
    feature = body.get("feature")
    user_id = body.get("user_id")
    if not feature or not user_id:
        return jsonify({"success": False, "error": "Feature and user ID required"})
    try:
        db.reload()
    except Exception:
        pass
    try:
        uid = int(user_id)
        removed = False
        for g_key in [gid_str, gid_int]:
            if g_key and g_key in db.feature_whitelists and feature in db.feature_whitelists[g_key]:
                for item in list(db.feature_whitelists[g_key][feature]):
                    try:
                        if int(item) == uid:
                            db.feature_whitelists[g_key][feature].remove(item)
                            removed = True
                    except (ValueError, TypeError):
                        pass
        if removed:
            db.save_data()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/security/update', methods=['POST'])
def update_security_settings(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    
    if "antinuke_active" in body:
        db.antinuke_active[gid_str] = bool(body["antinuke_active"])
    
    if "security_settings" in body:
        db.security_settings[gid_str] = body["security_settings"]
        if gid_str not in db.nuke_settings:
            db.nuke_settings[gid_str] = {}
        limits = body["security_settings"].get("limits", {})
        for k, v in limits.items():
            if isinstance(v, dict) and "limit" in v:
                db.nuke_settings[gid_str][k] = int(v["limit"])

    if "feature_whitelists" in body and isinstance(body["feature_whitelists"], dict):
        if gid_str not in db.feature_whitelists:
            db.feature_whitelists[gid_str] = {}
        for feat, items in body["feature_whitelists"].items():
            uids = []
            for it in items:
                uid = it.get("id") if isinstance(it, dict) else it
                try:
                    uids.append(int(uid))
                except (ValueError, TypeError):
                    pass
            db.feature_whitelists[gid_str][feat] = uids

    db.save_data()
    return jsonify({"success": True})

@app.route('/api/guild/<gid>/security/antiraid', methods=['POST'])
def toggle_antiraid(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    enabled = bool(body.get("enabled", True))
    if gid_str not in db.security_settings:
        db.security_settings[gid_str] = {}
    if "antiraid" not in db.security_settings[gid_str]:
        db.security_settings[gid_str]["antiraid"] = {}
    db.security_settings[gid_str]["antiraid"]["enabled"] = enabled
    db.save_data()
    return jsonify({"success": True, "enabled": enabled})

@app.route('/api/guild/<gid>/security/antispam', methods=['POST'])
def toggle_antispam(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    enabled = bool(body.get("enabled", True))
    if gid_str not in db.security_settings:
        db.security_settings[gid_str] = {}
    if "antispam" not in db.security_settings[gid_str]:
        db.security_settings[gid_str]["antispam"] = {}
    db.security_settings[gid_str]["antispam"]["enabled"] = enabled
    db.save_data()
    return jsonify({"success": True, "enabled": enabled})

@app.route('/api/guild/<gid>/whitelist/add', methods=['POST'])
def whitelist_add(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    if gid_str not in db.whitelist:
        db.whitelist[gid_str] = []
        
    user_id = flask_request.json.get("user_id")
    if user_id:
        try:
            uid = int(user_id)
            if uid not in db.whitelist[gid_str]:
                db.whitelist[gid_str].append(uid)
                db.save_data()
            return jsonify({"success": True, "user": fetch_user_info(uid)})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    return jsonify({"success": False, "error": "Invalid user ID"})

@app.route('/api/guild/<gid>/whitelist/remove', methods=['POST'])
def whitelist_remove(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    user_id = flask_request.json.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "User ID required"})
    try:
        db.reload()
    except Exception:
        pass
    try:
        uid = int(user_id)
        removed = False
        for g_key in [gid_str, gid_int]:
            if g_key and g_key in db.whitelist:
                for item in list(db.whitelist[g_key]):
                    try:
                        if int(item) == uid:
                            db.whitelist[g_key].remove(item)
                            removed = True
                    except (ValueError, TypeError):
                        pass
        if removed:
            db.save_data()
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "User not in whitelist"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ───────────────────── API: Leveling (With Test Message Sender) ─────────────────────

@app.route('/api/guild/<gid>/leveling')
def get_leveling(gid):
    gid_str = str(gid)
    chan_id = db.level_channels.get(gid_str, None)
    return jsonify({
        "channel": str(chan_id) if chan_id else "",
        "message": db.level_messages.get(gid_str, "--------------------\n# 🎉 LEVEL UP!\n**{user}** just advanced to **Level {level}**! Keep it up!\n--------------------"),
        "mode": db.level_modes.get(gid_str, "both")
    })

@app.route('/api/guild/<gid>/leveling/update', methods=['POST'])
def update_leveling(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    
    channel_id = body.get("channel")
    if channel_id and str(channel_id).strip():
        db.level_channels[gid_str] = str(channel_id).strip()
    elif gid_str in db.level_channels:
        del db.level_channels[gid_str]
        
    db.level_messages[gid_str] = body.get("message", "")
    if "mode" in body:
        db.level_modes[gid_str] = str(body["mode"])
    db.save_data()
    return jsonify({"success": True})

@app.route('/api/guild/<gid>/leveling/test', methods=['POST'])
def test_leveling_message(gid):
    body = flask_request.json or {}
    channel_id = body.get("channel")
    message_text = body.get("message", "")

    if not channel_id:
        return jsonify({"success": False, "error": "Please select a channel to send the test message to."})

    if not message_text.strip():
        return jsonify({"success": False, "error": "Message template cannot be empty."})

    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected to Discord right now."})

    try:
        chan_id_int = int(channel_id)
        channel = bot_instance.get_channel(chan_id_int)
        if not channel:
            return jsonify({"success": False, "error": f"Channel ID {channel_id} not found or Friday lacks access."})

        # Render preview variables: {user} and {level}
        formatted_msg = message_text.replace("{user}", bot_instance.user.mention).replace("{level}", "5")
        formatted_msg = replace_plain_emojis(formatted_msg, bot_instance, guild_id=gid)

        # Safely run channel.send on bot's asyncio event loop from Flask thread
        coro = channel.send(formatted_msg)
        future = asyncio.run_coroutine_threadsafe(coro, bot_instance.loop)
        future.result(timeout=6)

        return jsonify({"success": True, "channel_name": channel.name})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})



# ───────────────────── API: Anti-Abuse ─────────────────────

@app.route('/api/guild/<gid>/antiabuse')
def get_antiabuse(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    try:
        db.reload()
    except Exception:
        pass
    raw_abuse = db.abuse_whitelist.get(gid_str) or db.abuse_whitelist.get(gid_int) or []
    return jsonify({
        "words": db.banned_words.get(gid_str) or db.banned_words.get(gid_int) or [],
        "whitelist": [fetch_user_info(uid) for uid in raw_abuse]
    })

@app.route('/api/guild/<gid>/antiabuse/words', methods=['POST'])
def update_antiabuse_words(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    db.banned_words[gid_str] = body.get("words", [])
    db.save_data()
    return jsonify({"success": True})

@app.route('/api/guild/<gid>/antiabuse/whitelist/add', methods=['POST'])
def abuse_whitelist_add(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    if gid_str not in db.abuse_whitelist:
        db.abuse_whitelist[gid_str] = []
        
    user_id = flask_request.json.get("user_id")
    if user_id:
        try:
            uid = int(user_id)
            if uid not in db.abuse_whitelist[gid_str]:
                db.abuse_whitelist[gid_str].append(uid)
                db.save_data()
            return jsonify({"success": True, "user": fetch_user_info(uid)})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    return jsonify({"success": False, "error": "Invalid user ID"})

@app.route('/api/guild/<gid>/antiabuse/whitelist/remove', methods=['POST'])
def abuse_whitelist_remove(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    user_id = flask_request.json.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "User ID required"})
    try:
        db.reload()
    except Exception:
        pass
    try:
        uid = int(user_id)
        removed = False
        for g_key in [gid_str, gid_int]:
            if g_key and g_key in db.abuse_whitelist:
                for item in list(db.abuse_whitelist[g_key]):
                    try:
                        if int(item) == uid:
                            db.abuse_whitelist[g_key].remove(item)
                            removed = True
                    except (ValueError, TypeError):
                        pass
        if removed:
            db.save_data()
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "User not in whitelist"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ───────────────────── API: Roles & Categories ─────────────────────

@app.route('/api/guild/<gid>/roles')
def get_roles(gid):
    if bot_instance:
        guild = bot_instance.get_guild(int(gid))
        if guild:
            bot_role = guild.me.top_role
            result = []
            for r in guild.roles:
                if r.is_default() or r.managed: continue
                result.append({
                    "id": str(r.id),
                    "name": r.name,
                    "color": f"#{r.color.value:06x}" if r.color.value else "#94a3b8",
                    "position": r.position,
                    "assignable": r < bot_role
                })
            result.sort(key=lambda x: x["position"], reverse=True)
            return jsonify(result)
    return jsonify([])

@app.route('/api/guild/<gid>/categories')
def get_categories(gid):
    if bot_instance:
        guild = bot_instance.get_guild(int(gid))
        if guild:
            result = []
            for c in guild.categories:
                if c.name == "Friday Security Logs": continue
                ow = c.overwrites_for(guild.default_role)
                result.append({
                    "id": str(c.id),
                    "name": c.name,
                    "is_private": (ow.read_messages == False),
                    "channel_count": len(c.channels)
                })
            return jsonify(result)

    try:
        resp = requests.get(f"{DISCORD_API}/guilds/{gid}/channels", headers=discord_headers(), timeout=5)
        if resp.status_code == 200:
            raw_channels = resp.json()
            result = []
            for c in raw_channels:
                if c.get("type") == 4:
                    if c.get("name") == "Friday Security Logs": continue
                    is_priv = False
                    for ow in c.get("permission_overwrites", []):
                        if str(ow.get("id")) == str(gid):
                            if int(ow.get("deny", 0)) & 0x400:
                                is_priv = True
                    count = sum(1 for ch in raw_channels if ch.get("parent_id") == c["id"])
                    result.append({
                        "id": str(c["id"]),
                        "name": c["name"],
                        "is_private": is_priv,
                        "channel_count": count
                    })
            return jsonify(result)
    except Exception:
        pass
    return jsonify([])

# ───────────────────── API: Channel Privacy & Lockdowns ─────────────────────

@app.route('/api/guild/<gid>/privacy')
def get_privacy(gid):
    gid_str = str(gid)
    ignored_list = db.ignored_private.get(gid_str, [])
    channels_info = []
    categories_info = []

    if bot_instance:
        guild = bot_instance.get_guild(int(gid))
        if guild:
            for ch in guild.text_channels:
                if ch.category and ch.category.name == "Friday Security Logs": continue
                ow = ch.overwrites_for(guild.default_role)
                channels_info.append({
                    "id": str(ch.id),
                    "name": ch.name,
                    "category": ch.category.name if ch.category else "Uncategorized",
                    "is_private": (ow.read_messages == False),
                    "is_ignored": ch.id in ignored_list
                })
            for cat in guild.categories:
                if cat.name == "Friday Security Logs": continue
                ow = cat.overwrites_for(guild.default_role)
                categories_info.append({
                    "id": str(cat.id),
                    "name": cat.name,
                    "is_private": (ow.read_messages == False),
                    "channel_count": len(cat.channels)
                })

    if not channels_info:
        try:
            resp = requests.get(f"{DISCORD_API}/guilds/{gid}/channels", headers=discord_headers(), timeout=5)
            if resp.status_code == 200:
                raw_channels = resp.json()
                cats = {str(c["id"]): c["name"] for c in raw_channels if c.get("type") == 4}
                for c in raw_channels:
                    c_type = c.get("type")
                    if c_type == 0:
                        parent_id = str(c.get("parent_id") or "")
                        cat_name = cats.get(parent_id, "Uncategorized")
                        if cat_name == "Friday Security Logs": continue
                        is_priv = False
                        for ow in c.get("permission_overwrites", []):
                            if str(ow.get("id")) == str(gid):
                                if int(ow.get("deny", 0)) & 0x400:
                                    is_priv = True
                        channels_info.append({
                            "id": str(c["id"]),
                            "name": c["name"],
                            "category": cat_name,
                            "is_private": is_priv,
                            "is_ignored": int(c["id"]) in ignored_list
                        })
                    elif c_type == 4:
                        if c.get("name") == "Friday Security Logs": continue
                        is_priv = False
                        for ow in c.get("permission_overwrites", []):
                            if str(ow.get("id")) == str(gid):
                                if int(ow.get("deny", 0)) & 0x400:
                                    is_priv = True
                        count = sum(1 for ch in raw_channels if ch.get("parent_id") == c["id"])
                        categories_info.append({
                            "id": str(c["id"]),
                            "name": c["name"],
                            "is_private": is_priv,
                            "channel_count": count
                        })
        except Exception:
            pass

    return jsonify({
        "ignored": ignored_list,
        "channels": channels_info,
        "categories": categories_info,
        "lockdown_active": bool(db.lockdown_active.get(str(gid), False))
    })

@app.route('/api/guild/<gid>/privacy/ignored', methods=['POST'])
def update_privacy_ignored(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    db.ignored_private[gid_str] = [int(c) for c in body.get("ignored", [])]
    db.save_data()
    return jsonify({"success": True})

@app.route('/api/guild/<gid>/privacy/lockdown', methods=['POST'])
def execute_lockdown(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Bot is not connected."})
    gid_str = str(gid)
    ignore_list = db.ignored_private.get(gid_str, [])
    if not ignore_list:
        return jsonify({"success": False, "error": "Cannot execute lockdown! You must have at least 1 channel in the exempt list before locking down."})

    async def do_lockdown():
        guild = bot_instance.get_guild(int(gid))
        if not guild: raise Exception("Guild not found.")
        ignored_count = 0
        privated_count = 0
        just_privated = []
        for ch in guild.text_channels:
            if ch.category and ch.category.name == "Friday Security Logs": continue
            if ch.id in ignore_list:
                await ch.set_permissions(guild.default_role, read_messages=True, send_messages=False)
                ignored_count += 1
            else:
                ow = ch.overwrites_for(guild.default_role)
                if ow.read_messages != False:
                    await ch.set_permissions(guild.default_role, read_messages=False)
                    privated_count += 1
                    just_privated.append(ch.id)
        return {"privated": privated_count, "ignored": ignored_count, "locked_ids": just_privated}

    try:
        fut = asyncio.run_coroutine_threadsafe(do_lockdown(), bot_instance.loop)
        res = fut.result(timeout=10)
        db.lockdown_active[gid_str] = True
        if not hasattr(db, "lockdown_channels") or not isinstance(db.lockdown_channels, dict):
            db.lockdown_channels = {}
        db.lockdown_channels[gid_str] = res.get("locked_ids", [])
        db.save_data()
        return jsonify({"success": True, "privated": res["privated"], "ignored": res["ignored"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/privacy/unlock_all', methods=['POST'])
def execute_unlock_all(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Bot is not connected."})
    gid_str = str(gid)

    async def do_unlock():
        guild = bot_instance.get_guild(int(gid))
        if not guild: raise Exception("Guild not found.")
        locked_ids = set(getattr(db, "lockdown_channels", {}).get(gid_str, []))
        count = 0
        for ch in guild.text_channels:
            if ch.category and ch.category.name == "Friday Security Logs": continue
            if locked_ids:
                if ch.id in locked_ids:
                    await ch.set_permissions(guild.default_role, read_messages=None, send_messages=None)
                    count += 1
            else:
                ow = ch.overwrites_for(guild.default_role)
                if ow.read_messages == False:
                    name_low = ch.name.lower()
                    cat_low = ch.category.name.lower() if ch.category else ""
                    if any(w in name_low or w in cat_low for w in ["staff", "admin", "mod", "log", "private", "ticket"]):
                        continue
                if ow.read_messages is not None or ow.send_messages is not None:
                    await ch.set_permissions(guild.default_role, read_messages=None, send_messages=None)
                    count += 1
        return {"unlocked": count}

    try:
        fut = asyncio.run_coroutine_threadsafe(do_unlock(), bot_instance.loop)
        res = fut.result(timeout=10)
        db.lockdown_active[gid_str] = False
        if hasattr(db, "lockdown_channels") and isinstance(db.lockdown_channels, dict) and gid_str in db.lockdown_channels:
            del db.lockdown_channels[gid_str]
        db.save_data()
        return jsonify({"success": True, "unlocked": res["unlocked"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/privacy/channel', methods=['POST'])
def toggle_channel_privacy(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Bot is not connected."})
    body = flask_request.json or {}
    channel_id = body.get("channel_id")
    action = body.get("action", "private")

    if not channel_id:
        return jsonify({"success": False, "error": "No channel selected."})

    async def do_toggle():
        ch = bot_instance.get_channel(int(channel_id))
        if not ch: raise Exception("Channel not found.")
        if ch.category and ch.category.name == "Friday Security Logs":
            raise Exception("Friday Security Logs channels must remain private.")
        if action == "private":
            await ch.set_permissions(ch.guild.default_role, read_messages=False)
        else:
            await ch.set_permissions(ch.guild.default_role, read_messages=None, send_messages=None)
        return ch.name

    try:
        fut = asyncio.run_coroutine_threadsafe(do_toggle(), bot_instance.loop)
        ch_name = fut.result(timeout=6)
        return jsonify({"success": True, "channel_name": ch_name, "action": action})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/privacy/category', methods=['POST'])
def toggle_category_privacy(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Bot is not connected."})
    body = flask_request.json or {}
    category_id = body.get("category_id")
    action = body.get("action", "private")

    if not category_id:
        return jsonify({"success": False, "error": "No category selected."})

    async def do_toggle_cat():
        import discord
        cat = bot_instance.get_channel(int(category_id))
        if not cat or not isinstance(cat, discord.CategoryChannel):
            raise Exception("Category not found.")
        if cat.name == "Friday Security Logs":
            raise Exception("Friday Security Logs category must remain private.")

        cat_key = str(cat.id)
        if not hasattr(db, "category_locked_channels") or not isinstance(db.category_locked_channels, dict):
            db.category_locked_channels = {}

        if action == "private":
            await cat.set_permissions(cat.guild.default_role, read_messages=False)
            just_privated = []
            count = 0
            for ch in cat.channels:
                ow = ch.overwrites_for(cat.guild.default_role)
                if ow.read_messages != False:
                    await ch.set_permissions(cat.guild.default_role, read_messages=False)
                    just_privated.append(ch.id)
                    count += 1
            db.category_locked_channels[cat_key] = just_privated
            db.save_data()
            return cat.name, count
        else:
            await cat.set_permissions(cat.guild.default_role, read_messages=None, send_messages=None)
            locked_ids = set(getattr(db, "category_locked_channels", {}).get(cat_key, []))
            count = 0
            for ch in cat.channels:
                if locked_ids:
                    if ch.id in locked_ids:
                        await ch.set_permissions(cat.guild.default_role, read_messages=None, send_messages=None)
                        count += 1
                else:
                    ow = ch.overwrites_for(cat.guild.default_role)
                    if ow.read_messages == False:
                        name_low = ch.name.lower()
                        if any(w in name_low for w in ["staff", "admin", "mod", "log", "private", "ticket"]):
                            continue
                    await ch.set_permissions(cat.guild.default_role, read_messages=None, send_messages=None)
                    count += 1
            if cat_key in db.category_locked_channels:
                del db.category_locked_channels[cat_key]
                db.save_data()
            return cat.name, count

    try:
        fut = asyncio.run_coroutine_threadsafe(do_toggle_cat(), bot_instance.loop)
        cat_name, count = fut.result(timeout=8)
        return jsonify({"success": True, "category_name": cat_name, "count": count, "action": action})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ───────────────────── API: Custom Responses ─────────────────────

@app.route('/api/guild/<gid>/custom_responses', methods=['GET'])
def get_custom_responses(gid):
    gid_str = str(gid)
    responses = db.custom_responses.get(gid_str, {})
    return jsonify(responses)

@app.route('/api/guild/<gid>/custom_responses/update', methods=['POST'])
def update_custom_responses(gid):
    gid_str = str(gid)
    if gid_str not in db.custom_responses:
        db.custom_responses[gid_str] = {}
        
    body = flask_request.json or {}
    for key, val in body.items():
        if val.strip() == "":
            if key in db.custom_responses[gid_str]:
                del db.custom_responses[gid_str][key]
        else:
            db.custom_responses[gid_str][key] = val.strip()
            
    db.save_data()
    return jsonify({"success": True})


# ───────────────────── API: Reaction Roles ─────────────────────

@app.route('/api/guild/<gid>/reaction_roles/create', methods=['POST'])
def create_reaction_panel(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Bot is not connected."})
    body = flask_request.json or {}
    channel_id = body.get("channel_id")
    title = body.get("title", "Role Assignment")
    description = body.get("description", "React below to get your roles!")
    mappings = body.get("mappings", [])

    color_hex = (body.get("color") or "#2dd4bf").lstrip("#")
    try:
        color_int = int(color_hex, 16)
    except Exception:
        color_int = 0x2dd4bf

    show_thumbnail = bool(body.get("show_thumbnail", False))
    footer_text = (body.get("footer") or "React below to claim your roles!").strip()

    if not channel_id:
        return jsonify({"success": False, "error": "Please select a channel to post the panel."})
    if not mappings:
        return jsonify({"success": False, "error": "Please add at least one role & emoji pairing."})

    import re, discord

    async def do_create_panel():
        guild = bot_instance.get_guild(int(gid))
        if not guild: raise Exception("Guild not found.")
        channel = guild.get_channel(int(channel_id))
        if not channel: raise Exception("Channel not found.")
        bot_role = guild.me.top_role

        roles_setup = []
        for m in mappings:
            r_id = int(m.get("role_id"))
            e_raw = m.get("emoji", "").strip()
            role = guild.get_role(r_id)
            if not role: continue
            if role >= bot_role:
                raise Exception(f"Friday's role must be higher than @{role.name} to assign it.")

            # Parse emoji
            emoji_obj = None
            match = re.match(r'<(a?):([a-zA-Z0-9_]+):([0-9]+)>', e_raw)
            if match:
                emoji_obj = discord.PartialEmoji(name=match.group(2), id=int(match.group(3)), animated=bool(match.group(1)))
            else:
                clean_name = e_raw.strip(':')
                for e in guild.emojis:
                    if e.name == clean_name:
                        emoji_obj = e
                        break
                if not emoji_obj:
                    emoji_obj = e_raw
            roles_setup.append((role, emoji_obj))

        if not roles_setup:
            raise Exception("No valid role and emoji pairings could be parsed.")

        p_title = replace_plain_emojis(title, bot_instance, guild_id=gid) if title else None
        p_desc = replace_plain_emojis(description, bot_instance, guild_id=gid) if description else None
        embed = discord.Embed(title=p_title, description=p_desc, color=discord.Color(color_int))
        panel_text = ""
        for role, emoji_obj in roles_setup:
            panel_text += f"{str(emoji_obj)} - {role.mention}\n\n"
        embed.add_field(name="Available Roles", value=panel_text, inline=False)
        
        avatar_url = str(bot_instance.user.display_avatar.url) if bot_instance.user and bot_instance.user.display_avatar else None
        if show_thumbnail and avatar_url:
            embed.set_thumbnail(url=avatar_url)

        if footer_text:
            embed.set_footer(text=footer_text, icon_url=avatar_url)

        msg = await channel.send(embed=embed)
        msg_id = str(msg.id)
        if msg_id not in db.reaction_roles:
            db.reaction_roles[msg_id] = {}

        for role, emoji_obj in roles_setup:
            await msg.add_reaction(emoji_obj)
            db.reaction_roles[msg_id][str(emoji_obj)] = role.id

        db.save_data()
        return channel.name, len(roles_setup)

    try:
        fut = asyncio.run_coroutine_threadsafe(do_create_panel(), bot_instance.loop)
        ch_name, count = fut.result(timeout=10)
        return jsonify({"success": True, "channel_name": ch_name, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

import re

# ───────────────────── API: Announcements Dispatcher ─────────────────────

@app.route('/api/guild/<gid>/announcements')
def get_announcements_config(gid):
    gid_str = str(gid)
    chan_id = db.announcement_channels.get(gid_str)
    return jsonify({
        "channel_id": str(chan_id) if chan_id else None
    })

@app.route('/api/guild/<gid>/announcements/channel', methods=['POST'])
def set_announcements_channel(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    channel_id = data.get("channel_id")
    if channel_id:
        db.announcement_channels[gid_str] = str(channel_id)
    else:
        db.announcement_channels.pop(gid_str, None)
    db.save_data()
    return jsonify({"success": True, "channel_id": str(channel_id) if channel_id else None})

@app.route('/api/guild/<gid>/announcements/send', methods=['POST'])
def broadcast_announcement(gid):
    if not bot_instance:
        return jsonify({"success": False, "error": "Friday bot instance is not connected."})

    data = flask_request.json or {}
    gid_str = str(gid)
    channel_id = data.get("channel_id") or db.announcement_channels.get(gid_str)
    if not channel_id:
        return jsonify({"success": False, "error": "No announcement channel selected or configured."})

    title = data.get("title", "").strip()
    content = data.get("content", "").strip()
    ping = data.get("ping", "none").strip()
    color_hex = data.get("color", "#2dd4bf")
    show_thumbnail = data.get("show_thumbnail", False)
    footer_text = data.get("footer", "").strip()
    ann_format = data.get("format", "embed").strip().lower()

    if not content and not title:
        return jsonify({"success": False, "error": "Announcement content or title is required."})

    try:
        color_int = int(color_hex.lstrip('#'), 16)
    except Exception:
        color_int = 0x2dd4bf

    async def do_broadcast():
        guild = bot_instance.get_guild(int(gid))
        if not guild:
            raise Exception("Guild not found.")
        channel = guild.get_channel(int(channel_id))
        if not channel:
            raise Exception("Destination channel not found in server.")

        mention_str = ""
        if ping == "everyone" or ping == "@everyone":
            mention_str = "@everyone"
        elif ping == "here" or ping == "@here":
            mention_str = "@here"

        processed_title = replace_plain_emojis(title, bot_instance, guild_id=gid)
        processed_content = replace_plain_emojis(content, bot_instance, guild_id=gid)

        if ann_format == "normal":
            # Normal clean chat text format (no embed box)
            msg_parts = []
            if mention_str:
                msg_parts.append(mention_str)
            if processed_title:
                msg_parts.append(f"# {processed_title}")
            if processed_content:
                msg_parts.append(processed_content)

            full_msg = "\n\n".join(msg_parts)
            msg = await channel.send(
                content=full_msg,
                allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True)
            )
            return channel.name, msg.jump_url
        else:
            # Rich Embed Box format
            embed = discord.Embed(
                title=processed_title if processed_title else None,
                description=processed_content if processed_content else None,
                color=discord.Color(color_int)
            )

            avatar_url = str(bot_instance.user.display_avatar.url) if bot_instance.user and bot_instance.user.display_avatar else None
            if show_thumbnail and avatar_url:
                embed.set_thumbnail(url=avatar_url)

            if footer_text:
                embed.set_footer(text=footer_text, icon_url=avatar_url if show_thumbnail else None)

            msg = await channel.send(
                content=mention_str if mention_str else None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True)
            )
            return channel.name, msg.jump_url

    try:
        fut = asyncio.run_coroutine_threadsafe(do_broadcast(), bot_instance.loop)
        ch_name, jump_url = fut.result(timeout=10)
        return jsonify({
            "success": True,
            "channel_name": ch_name,
            "jump_url": jump_url
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ───────────────────── API: Tickets System ─────────────────────

@app.route('/api/guild/<gid>/tickets', methods=['GET', 'POST'])
def manage_tickets(gid):
    gid_str = str(gid)
    if flask_request.method == 'GET':
        settings = db.tickets.get(gid_str, {})
        return jsonify(settings)
    
    if flask_request.method == 'POST':
        data = flask_request.json or {}
        if gid_str not in db.tickets:
            db.tickets[gid_str] = {}
        if "support_role_id" in data:
            db.tickets[gid_str]["support_role_id"] = int(data["support_role_id"]) if data["support_role_id"] else None
        db.save_data()
        return jsonify({"success": True})

@app.route('/api/guild/<gid>/tickets/config', methods=['POST'])
def save_ticket_config(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    if gid_str not in db.tickets:
        db.tickets[gid_str] = {"panels": {}, "active_tickets": {}, "ticket_counter": 0}
        
    if "support_role_id" in data and data["support_role_id"]:
        try:
            db.tickets[gid_str]["support_role_id"] = int(data["support_role_id"])
        except Exception:
            pass

    db.tickets[gid_str]["config"] = {
        "channel_id": data.get("channel_id"),
        "category_id": data.get("category_id"),
        "transcript_channel_id": data.get("transcript_channel_id"),
        "transcript_category_id": data.get("transcript_category_id"),
        "title": data.get("title"),
        "description": data.get("description"),
        "buttons": data.get("buttons", []),
        "private": data.get("private", True),
        "transcription": data.get("transcription", True),
        "color": data.get("color", "#2dd4bf")
    }
    db.save_data()
    return jsonify({"success": True, "config": db.tickets[gid_str]["config"]})

@app.route('/api/guild/<gid>/reaction_roles', methods=['GET'])
def get_guild_reaction_roles(gid):
    gid_str = str(gid)
    guild_roles_map = {}
    for msg_id, pairs in db.reaction_roles.items():
        if isinstance(pairs, dict):
            for emoji, role_id in pairs.items():
                guild_roles_map[emoji] = str(role_id)
    return jsonify({
        "success": True,
        "roles": guild_roles_map
    })

@app.route('/api/guild/<gid>/tickets/panel', methods=['POST'])
def create_ticket_panel(gid):
    if not bot_instance:
        return jsonify({"success": False, "error": "Bot not connected"})
        
    data = flask_request.json or {}
    channel_id = data.get("channel_id")
    category_id = data.get("category_id")
    if not channel_id or not category_id:
        return jsonify({"success": False, "error": "Channel and Category are required"})
        
    title = data.get("title", "Support")
    desc = data.get("description", "Click below to open a ticket")
    buttons = data.get("buttons", [])
    private = data.get("private", True)
    transcription = data.get("transcription", True)
    transcript_channel_id = data.get("transcript_channel_id")
    transcript_category_id = data.get("transcript_category_id")
    raw_color = data.get("color", "#2dd4bf")
    try:
        if isinstance(raw_color, str) and raw_color.startswith("#"):
            embed_color = int(raw_color.replace("#", ""), 16)
        else:
            embed_color = int(raw_color)
    except Exception:
        embed_color = 0x2dd4bf
    
    async def do_panel():
        guild = bot_instance.get_guild(int(gid))
        if not guild: raise Exception("Guild not found")
        channel = guild.get_channel(int(channel_id))
        if not channel: raise Exception("Channel not found")
        
        from cogs.tickets import TicketPanelView
        p_title = replace_plain_emojis(title, bot_instance, guild_id=gid)
        p_desc = replace_plain_emojis(desc, bot_instance, guild_id=gid)
        embed = discord.Embed(title=p_title, description=p_desc, color=embed_color)
        view = discord.ui.View(timeout=None)
        for b in buttons:
            if b.strip():
                label, emoji = parse_btn(b, bot=bot_instance, guild=guild, guild_id=gid)
                view.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"ticket_btn_{b.strip()}", emoji=emoji))
        
        msg = await channel.send(embed=embed, view=view)
        
        gid_str = str(gid)
        if gid_str not in db.tickets:
            db.tickets[gid_str] = {"panels": {}, "active_tickets": {}, "ticket_counter": 0}
        if "panels" not in db.tickets[gid_str]:
            db.tickets[gid_str]["panels"] = {}
            
        panel_record = {
            "channel_id": int(channel_id),
            "title": title,
            "description": desc,
            "buttons": [b.strip() for b in buttons if b.strip()],
            "category_id": int(category_id),
            "private": private,
            "transcription": transcription,
            "transcript_channel_id": int(transcript_channel_id) if transcript_channel_id else None,
            "transcript_category_id": int(transcript_category_id) if transcript_category_id else None,
            "color": embed_color
        }
        db.tickets[gid_str]["panels"][str(msg.id)] = panel_record
        db.tickets[gid_str]["config"] = panel_record
        db.save_data()
        
        # Attach the actual view so it handles interactions correctly without reload
        actual_view = TicketPanelView(bot_instance, msg.id)
        for b in buttons:
            if b.strip():
                label, emoji = parse_btn(b, bot=bot_instance, guild=guild, guild_id=gid)
                actual_view.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"ticket_btn_{b.strip()}", emoji=emoji))
        await msg.edit(view=actual_view)
        
        return msg.id

    try:
        fut = asyncio.run_coroutine_threadsafe(do_panel(), bot_instance.loop)
        msg_id = fut.result(timeout=10)
        return jsonify({"success": True, "message_id": str(msg_id)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/guild/<gid>/responses', methods=['GET', 'POST'])
@app.route('/api/guild/<gid>/custom_responses', methods=['GET', 'POST'])
@app.route('/api/guild/<gid>/custom_responses/update', methods=['POST'])
def manage_responses(gid):
    gid_str = str(gid)
    if flask_request.method == 'GET':
        return jsonify({"success": True, "config": db.custom_responses.get(gid_str, {})})
    else:
        data = flask_request.json or {}
        if gid_str not in db.custom_responses:
            db.custom_responses[gid_str] = {}
        for k, v in data.items():
            if v and str(v).strip():
                db.custom_responses[gid_str][k] = str(v).strip()
            else:
                db.custom_responses[gid_str].pop(k, None)
        db.save_data()
        return jsonify({"success": True, "config": db.custom_responses.get(gid_str, {})})

# ───────────────────── API: Automations (Autoreact & Autoresponder) ─────────────────────

@app.route('/api/guild/<gid>/automations', methods=['GET'])
def get_automations(gid):
    gid_str = str(gid)
    autoreact_list = db.autoreact.get(gid_str, [])
    autoresponder_data = db.autoresponder.get(gid_str, {"rules": [], "ignored_channels": []})
    if not isinstance(autoresponder_data, dict):
        autoresponder_data = {"rules": [], "ignored_channels": []}
    return jsonify({
        "success": True,
        "autoreact": autoreact_list,
        "autoresponder": autoresponder_data
    })

@app.route('/api/guild/<gid>/autoreact/add', methods=['POST'])
def add_autoreact(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    user_id = str(data.get("user_id", "")).strip()
    user_name = str(data.get("user_name", f"User {user_id}")).strip()
    emoji = str(data.get("emoji", "")).strip()

    if not user_id or not emoji:
        return jsonify({"success": False, "error": "User ID and Emoji are required"}), 400

    if gid_str not in db.autoreact or not isinstance(db.autoreact[gid_str], list):
        db.autoreact[gid_str] = []

    # Update if already exists, else append
    existing = False
    for rule in db.autoreact[gid_str]:
        if str(rule.get("user_id")) == user_id:
            rule["emoji"] = emoji
            rule["user_name"] = user_name
            existing = True
            break
    if not existing:
        db.autoreact[gid_str].append({
            "user_id": user_id,
            "user_name": user_name,
            "emoji": emoji
        })

    db.save_data()
    return jsonify({"success": True, "autoreact": db.autoreact[gid_str]})

@app.route('/api/guild/<gid>/autoreact/remove', methods=['POST'])
def remove_autoreact(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    user_id = str(data.get("user_id", "")).strip()

    if gid_str in db.autoreact and isinstance(db.autoreact[gid_str], list):
        db.autoreact[gid_str] = [r for r in db.autoreact[gid_str] if str(r.get("user_id")) != user_id]
        db.save_data()

    return jsonify({"success": True, "autoreact": db.autoreact.get(gid_str, [])})

@app.route('/api/guild/<gid>/autoresponder/add', methods=['POST'])
def add_autoresponder(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    rule_type = str(data.get("type", "mention")).strip().lower()
    response_text = str(data.get("response", "")).strip()
    raw_emoji = str(data.get("emoji", "")).strip()

    if not response_text:
        return jsonify({"success": False, "error": "Response message is required"}), 400

    if gid_str not in db.autoresponder or not isinstance(db.autoresponder[gid_str], dict):
        db.autoresponder[gid_str] = {"rules": [], "ignored_channels": []}

    rules = db.autoresponder[gid_str].setdefault("rules", [])
    rule_id = str(uuid.uuid4())[:8]

    if rule_type == "word" or "trigger" in data:
        trigger = str(data.get("trigger", "")).strip()
        if not trigger:
            return jsonify({"success": False, "error": "Trigger word or phrase is required"}), 400
        clean_trigger = trigger.lower()
        existing = False
        for rule in rules:
            if (rule.get("type") == "word" or "trigger" in rule) and str(rule.get("trigger", "")).lower() == clean_trigger:
                rule["type"] = "word"
                rule["trigger"] = trigger
                rule["response"] = response_text
                rule["emoji"] = raw_emoji
                existing = True
                break
        if not existing:
            rules.append({
                "id": rule_id,
                "type": "word",
                "trigger": trigger,
                "response": response_text,
                "emoji": raw_emoji
            })
    else:
        # Mention rule
        user_id = str(data.get("user_id", "")).strip()
        user_name = str(data.get("user_name", f"User {user_id}")).strip()
        if not user_id:
            return jsonify({"success": False, "error": "Target member is required"}), 400
        existing = False
        for rule in rules:
            if str(rule.get("user_id")) == user_id:
                rule["type"] = "mention"
                rule["user_name"] = user_name
                rule["response"] = response_text
                rule["emoji"] = raw_emoji
                existing = True
                break
        if not existing:
            rules.append({
                "id": rule_id,
                "type": "mention",
                "user_id": user_id,
                "user_name": user_name,
                "response": response_text,
                "emoji": raw_emoji
            })

    db.save_data()
    return jsonify({"success": True, "autoresponder": db.autoresponder[gid_str]})

@app.route('/api/guild/<gid>/autoresponder/remove', methods=['POST'])
def remove_autoresponder(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    rule_id = str(data.get("id", "")).strip()
    user_id = str(data.get("user_id", "")).strip()
    trigger = str(data.get("trigger", "")).strip().lower()

    if gid_str in db.autoresponder and isinstance(db.autoresponder[gid_str], dict):
        rules = db.autoresponder[gid_str].get("rules", [])
        if rule_id:
            db.autoresponder[gid_str]["rules"] = [r for r in rules if str(r.get("id")) != rule_id]
        elif trigger:
            db.autoresponder[gid_str]["rules"] = [
                r for r in rules
                if str(r.get("trigger", "")).lower() != trigger
            ]
        elif user_id:
            db.autoresponder[gid_str]["rules"] = [
                r for r in rules
                if str(r.get("user_id")) != user_id
            ]
        db.save_data()

    return jsonify({"success": True, "autoresponder": db.autoresponder.get(gid_str, {"rules": [], "ignored_channels": []})})

@app.route('/api/guild/<gid>/autoresponder/ignore_channel', methods=['POST'])
def ignore_channel_autoresponder(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    channel_id = str(data.get("channel_id", "")).strip()

    if not channel_id:
        return jsonify({"success": False, "error": "Channel ID is required"}), 400

    if gid_str not in db.autoresponder or not isinstance(db.autoresponder[gid_str], dict):
        db.autoresponder[gid_str] = {"rules": [], "ignored_channels": []}

    ignored = db.autoresponder[gid_str].setdefault("ignored_channels", [])
    if channel_id not in [str(c) for c in ignored]:
        ignored.append(channel_id)
        db.save_data()

    return jsonify({"success": True, "autoresponder": db.autoresponder[gid_str]})

@app.route('/api/guild/<gid>/autoresponder/unignore_channel', methods=['POST'])
def unignore_channel_autoresponder(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    channel_id = str(data.get("channel_id", "")).strip()

    if gid_str in db.autoresponder and isinstance(db.autoresponder[gid_str], dict):
        ignored = db.autoresponder[gid_str].get("ignored_channels", [])
        db.autoresponder[gid_str]["ignored_channels"] = [str(c) for c in ignored if str(c) != channel_id]
        db.save_data()

    return jsonify({"success": True, "autoresponder": db.autoresponder.get(gid_str, {"rules": [], "ignored_channels": []})})

# ───────────────────── First Chat Welcome Endpoints ─────────────────────

@app.route('/api/guild/<gid>/first_welcome', methods=['GET'])
def get_first_welcome(gid):
    gid_str = str(gid)
    cfg = db.first_welcome.get(gid_str, {})
    if not isinstance(cfg, dict):
        cfg = {}
    return jsonify({
        "success": True,
        "config": {
            "enabled": cfg.get("enabled", False),
            "channel_id": cfg.get("channel_id"),
            "title": cfg.get("title", "WELCOME TO {server}"),
            "message": cfg.get("message", "Welcome to **{server}**, {user}! We are thrilled to have you here. Feel free to introduce yourself and make yourself at home! 💫"),
            "show_avatar": cfg.get("show_avatar", True),
            "status_color": cfg.get("status_color", "success"),
            "custom_hex": cfg.get("custom_hex", "#10b981")
        }
    })

@app.route('/api/guild/<gid>/first_welcome/update', methods=['POST'])
def update_first_welcome(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    
    if gid_str not in db.first_welcome or not isinstance(db.first_welcome[gid_str], dict):
        db.first_welcome[gid_str] = {}

    db.first_welcome[gid_str]["enabled"] = bool(data.get("enabled", False))
    db.first_welcome[gid_str]["channel_id"] = str(data.get("channel_id")).strip() if data.get("channel_id") else None
    db.first_welcome[gid_str]["title"] = str(data.get("title", "WELCOME TO {server}")).strip()
    db.first_welcome[gid_str]["message"] = str(data.get("message", "Welcome to **{server}**, {user}! Glad to have you here!")).strip()
    db.first_welcome[gid_str]["show_avatar"] = bool(data.get("show_avatar", True))
    db.first_welcome[gid_str]["status_color"] = str(data.get("status_color", "success"))
    db.first_welcome[gid_str]["custom_hex"] = str(data.get("custom_hex", "#10b981"))

    db.save_data()
    return jsonify({"success": True, "config": db.first_welcome[gid_str]})

@app.route('/api/guild/<gid>/first_welcome/test', methods=['POST'])
def test_first_welcome(gid):
    if not bot_instance:
        return jsonify({"success": False, "error": "Bot is not connected"})
        
    gid_str = str(gid)
    cfg = db.first_welcome.get(gid_str, {})
    target_channel_id = cfg.get("channel_id")

    async def do_test():
        guild = bot_instance.get_guild(int(gid))
        if not guild:
            raise Exception("Guild not found")
        channel = None
        if target_channel_id:
            channel = guild.get_channel(int(target_channel_id))
        if not channel:
            # Fallback to first text channel bot can send messages in
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break
        if not channel:
            raise Exception("No writable channel found")

        from cogs.welcomer import build_welcome_embed
        # Use bot user or guild owner as sample member
        sample_member = guild.owner or guild.me
        embed = build_welcome_embed(sample_member, guild, cfg, channel)
        await channel.send(content="🧪 **[Test Preview] First Chat Welcome Card:**", embed=embed)
        return channel.name

    try:
        fut = asyncio.run_coroutine_threadsafe(do_test(), bot_instance.loop)
        chan_name = fut.result(timeout=10)
        return jsonify({"success": True, "channel_name": chan_name})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ───────────────────── AFK System Endpoints ─────────────────────

@app.route('/api/guild/<gid>/afk', methods=['GET'])
def get_afk_data(gid):
    gid_str = str(gid)
    afk_dict = getattr(db, "afk_data", {}).get(gid_str, {})
    import time
    
    result = []
    guild = bot_instance.get_guild(int(gid)) if bot_instance else None

    for uid, data in afk_dict.items():
        user_info = fetch_user_info(uid)
        username = user_info.get("username", f"User {uid}")
        avatar = user_info.get("avatar")
        
        # If in guild cache, check member display name
        if guild:
            m = guild.get_member(int(uid))
            if m:
                username = m.display_name
                if m.display_avatar:
                    avatar = str(m.display_avatar.url)

        elapsed = time.time() - data.get("time", time.time())
        seconds = max(0, int(elapsed))
        if seconds < 60:
            dur = f"{seconds}s"
        elif seconds < 3600:
            dur = f"{seconds // 60}m"
        elif seconds < 86400:
            dur = f"{seconds // 3600}h {(seconds % 3600) // 60}m"
        else:
            dur = f"{seconds // 86400}d {(seconds % 86400) // 3600}h"

        result.append({
            "user_id": str(uid),
            "username": username,
            "avatar": avatar,
            "reason": data.get("reason", "AFK"),
            "duration": dur,
            "time": data.get("time", 0),
            "mentions_count": len(data.get("mentions", []))
        })

    return jsonify({"success": True, "afk_members": result})

@app.route('/api/guild/<gid>/afk/clear', methods=['POST'])
def clear_afk_status(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    user_id = str(data.get("user_id", "")).strip()

    if not user_id:
        return jsonify({"success": False, "error": "user_id is required"}), 400

    afk_dict = getattr(db, "afk_data", {}).get(gid_str, {})
    if user_id in afk_dict:
        afk_info = afk_dict.pop(user_id, None)
        db.save_data()

        # If bot instance running, attempt to revert nickname
        if bot_instance and afk_info and afk_info.get("nick_changed"):
            async def revert_nick():
                try:
                    guild = bot_instance.get_guild(int(gid))
                    if guild:
                        member = guild.get_member(int(user_id))
                        if member:
                            await member.edit(nick=afk_info.get("original_nick"), reason="AFK cleared from Dashboard")
                except Exception:
                    pass
            try:
                asyncio.run_coroutine_threadsafe(revert_nick(), bot_instance.loop)
            except Exception:
                pass

        return jsonify({"success": True, "message": f"AFK cleared for user {user_id}"})
    
    return jsonify({"success": False, "error": "User not currently AFK"}), 404

# ───────────────────── API: Temp Voice (Join to Create) ─────────────────────

@app.route('/api/guild/<gid>/temp-voice', methods=['GET'])
def get_temp_voice_config(gid):
    gid_str = str(gid)
    cfg = getattr(db, "temp_voice", {}).get(gid_str, {})
    
    # Get active rooms from TempVoice cog if loaded
    active_rooms = []
    if bot_instance:
        cog = bot_instance.get_cog("TempVoice")
        if cog and hasattr(cog, "active_channels"):
            for ch_id, data in cog.active_channels.items():
                if data.get("guild_id") == gid_str:
                    ch = bot_instance.get_channel(int(ch_id))
                    owner = ch.guild.get_member(data.get("owner_id")) if ch and ch.guild else None
                    active_rooms.append({
                        "id": ch_id,
                        "name": ch.name if ch else data.get("channel_name", "Voice Room"),
                        "owner_id": str(data.get("owner_id")),
                        "owner_name": owner.display_name if owner else f"User {data.get('owner_id')}",
                        "owner_avatar": str(owner.display_avatar.url) if owner and owner.display_avatar else None,
                        "member_count": len(ch.members) if ch else 0,
                        "locked": bool(data.get("locked")),
                        "hidden": bool(data.get("hidden")),
                        "limit": ch.user_limit if ch else 0
                    })

    return jsonify({
        "enabled": bool(cfg.get("enabled", False)),
        "hub_channel_id": cfg.get("hub_channel_id"),
        "category_id": cfg.get("category_id"),
        "default_name": cfg.get("default_name", "🔊 {user}'s Room"),
        "user_limit": int(cfg.get("user_limit", 0)),
        "active_rooms": active_rooms
    })

@app.route('/api/guild/<gid>/temp-voice', methods=['POST'])
def save_temp_voice_config(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    
    if not hasattr(db, "temp_voice") or not isinstance(db.temp_voice, dict):
        db.temp_voice = {}

    db.temp_voice[gid_str] = {
        "enabled": bool(data.get("enabled", False)),
        "hub_channel_id": data.get("hub_channel_id") or None,
        "category_id": data.get("category_id") or None,
        "default_name": (data.get("default_name") or "🔊 {user}'s Room").strip()[:80],
        "user_limit": max(0, min(99, int(data.get("user_limit", 0))))
    }
    db.save_data()
    return jsonify({"success": True, "message": "Voice Hub settings saved successfully!"})

@app.route('/api/guild/<gid>/temp-voice/autohub', methods=['POST'])
def autohub_temp_voice(gid):
    gid_str = str(gid)
    if not bot_instance:
        return jsonify({"success": False, "error": "Bot instance offline"}), 503

    future_result = asyncio.run_coroutine_threadsafe(
        _create_autohub_coroutine(int(gid)),
        bot_instance.loop
    )
    try:
        res = future_result.result(timeout=10)
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

async def _create_autohub_coroutine(guild_id):
    guild = bot_instance.get_guild(guild_id)
    if not guild:
        return {"success": False, "error": "Guild not found"}

    category = discord.utils.get(guild.categories, name="TEMPORARY CHANNELS")
    if not category:
        category = await guild.create_category("TEMPORARY CHANNELS", reason="Friday Voice Hub Auto-Setup")

    hub_vc = await guild.create_voice_channel(
        name="➕ Join to Create",
        category=category,
        reason="Friday Voice Hub Auto-Setup"
    )

    if not hasattr(db, "temp_voice") or not isinstance(db.temp_voice, dict):
        db.temp_voice = {}

    db.temp_voice[str(guild_id)] = {
        "enabled": True,
        "hub_channel_id": str(hub_vc.id),
        "category_id": str(category.id),
        "default_name": "🔊 {user}'s Room",
        "user_limit": 0
    }
    db.save_data()
    return {
        "success": True,
        "hub_channel_id": str(hub_vc.id),
        "hub_channel_name": hub_vc.name,
        "category_id": str(category.id),
        "category_name": category.name,
        "message": f"Created '➕ Join to Create' under '{category.name}'!"
    }

# ───────────────────── API: Server Backups & Disaster Recovery ─────────────────────

@app.route('/api/guild/<gid>/backups', methods=['GET'])
def get_guild_backups(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    try:
        db.reload()
    except Exception:
        pass
    backups = (db.server_backups.get(gid_str) or db.server_backups.get(gid_int) or []) if hasattr(db, "server_backups") else []
    return jsonify({"success": True, "backups": backups})

@app.route('/api/guild/<gid>/backups/<bid>/audit', methods=['GET'])
def audit_guild_backup(gid, bid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    
    if not bot_instance:
        return jsonify({"success": False, "error": "Friday bot is not connected to Discord right now."})
        
    guild = bot_instance.get_guild(gid_int or int(gid_str))
    if not guild:
        return jsonify({"success": False, "error": f"Server {gid} not found or Friday lacks access."})
        
    try:
        db.reload()
    except Exception:
        pass
        
    backups = (db.server_backups.get(gid_str) or db.server_backups.get(gid_int) or []) if hasattr(db, "server_backups") else []
    target_backup = next((b for b in backups if b.get("id") == bid.strip()), None)
    if not target_backup:
        return jsonify({"success": False, "error": f"Backup snapshot '{bid}' not found."})
        
    try:
        from cogs.backup import audit_server_status
        audit_res = audit_server_status(guild, target_backup)
        return jsonify({"success": True, "audit": audit_res, "backup": target_backup})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/backups/create', methods=['POST'])
def create_guild_backup(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    body = flask_request.json or {}
    name = body.get("name")
    
    if not bot_instance:
        return jsonify({"success": False, "error": "Friday bot is not connected to Discord right now."})
    
    guild = bot_instance.get_guild(gid_int or int(gid_str))
    if not guild:
        return jsonify({"success": False, "error": f"Server {gid} not found or Friday lacks access."})
    
    try:
        from cogs.backup import capture_server_backup
        snapshot = capture_server_backup(guild, name=name, creator_name="Dashboard Administrator")
        return jsonify({"success": True, "backup": snapshot})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/backups/update', methods=['POST'])
def update_guild_backup(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    body = flask_request.json or {}
    backup_id = body.get("backup_id")
    name = body.get("name")
    
    if not backup_id:
        return jsonify({"success": False, "error": "Backup ID is required."})
        
    if not bot_instance:
        return jsonify({"success": False, "error": "Friday bot is not connected to Discord right now."})
        
    guild = bot_instance.get_guild(gid_int or int(gid_str))
    if not guild:
        return jsonify({"success": False, "error": f"Server {gid} not found or Friday lacks access."})
        
    try:
        from cogs.backup import update_server_backup
        snapshot = update_server_backup(guild, backup_id=backup_id, new_name=name, updater_name="Dashboard Administrator")
        return jsonify({"success": True, "backup": snapshot})
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/backups/restore', methods=['POST'])
def restore_guild_backup(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    body = flask_request.json or {}
    backup_id = body.get("backup_id")
    clean_unauthorized = bool(body.get("clean_unauthorized", False))
    
    if not backup_id:
        return jsonify({"success": False, "error": "Backup ID is required."})
        
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected to Discord right now."})
        
    guild = bot_instance.get_guild(gid_int or int(gid_str))
    if not guild:
        return jsonify({"success": False, "error": f"Server {gid} not found or Friday lacks access."})
        
    try:
        db.reload()
    except Exception:
        pass
        
    backups = (db.server_backups.get(gid_str) or db.server_backups.get(gid_int) or []) if hasattr(db, "server_backups") else []
    target_backup = next((b for b in backups if b.get("id") == backup_id.strip()), None)
    if not target_backup:
        return jsonify({"success": False, "error": f"Backup snapshot '{backup_id}' not found."})
        
    try:
        from cogs.backup import apply_server_restore
        coro = apply_server_restore(guild, target_backup, clean_unauthorized=clean_unauthorized)
        future = asyncio.run_coroutine_threadsafe(coro, bot_instance.loop)
        summary = future.result(timeout=180)
        return jsonify({"success": True, "summary": summary, "backup": target_backup})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/backups/delete', methods=['POST'])
def delete_guild_backup(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    body = flask_request.json or {}
    backup_id = body.get("backup_id")
    
    if not backup_id:
        return jsonify({"success": False, "error": "Backup ID is required."})
        
    try:
        db.reload()
    except Exception:
        pass
        
    deleted = False
    for g_key in [gid_str, gid_int]:
        if hasattr(db, "server_backups") and g_key in db.server_backups:
            orig = len(db.server_backups[g_key])
            db.server_backups[g_key] = [b for b in db.server_backups[g_key] if b.get("id") != backup_id.strip()]
            if len(db.server_backups[g_key]) < orig:
                deleted = True
                
    if deleted:
        db.save_data()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": f"Backup '{backup_id}' not found."})

# ───────────────────── API: Special VIP Invites & Direct DMs ─────────────────────

@app.route('/api/guild/<gid>/special_invites', methods=['GET'])
def get_special_invites(gid):
    try:
        db.reload()
    except Exception:
        pass
    invites_data = getattr(db, "special_invites", {}) or {}
    results = []
    for uid, data in invites_data.items():
        user_info = fetch_user_info(uid)
        results.append({
            "user_id": str(uid),
            "username": user_info.get("username", f"User {uid}"),
            "avatar": user_info.get("avatar"),
            "status": data.get("status", "invited"),
            "custom_nickname": data.get("custom_nickname", ""),
            "current_mood": data.get("current_mood", "cheerful"),
            "invited_at": data.get("invited_at", ""),
            "notes": data.get("notes", ""),
            "message_count": data.get("message_count", 0)
        })
    return jsonify(results)

@app.route('/api/guild/<gid>/special_invites/invite', methods=['POST'])
def send_special_invite(gid):
    body = flask_request.json or {}
    user_id = str(body.get("user_id", "")).strip()
    invite_msg = body.get("invite_message", "").strip()

    if not user_id:
        return jsonify({"success": False, "error": "Please provide a valid User ID or select a member."})

    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."})

    if not invite_msg:
        invite_msg = (
            "🎉 **Congratulations {mention}!** You have been granted an exclusive VIP pass to chat with me directly in DMs! ✨\n\n"
            "I'm so excited to get to know you better. To make our private conversations feel just right, what should I call you, and what kind of conversations do you enjoy the most? 🌸"
        )

    invite_msg = replace_plain_emojis(invite_msg)

    async def do_send_invite():
        uid_int = int(user_id) if user_id.isdigit() else None
        if not uid_int:
            raise Exception("Invalid User ID format.")
        user = bot_instance.get_user(uid_int) or await bot_instance.fetch_user(uid_int)
        if not user:
            raise Exception("Discord user not found.")
        
        final_text = (
            invite_msg
            .replace("{mention}", user.mention)
            .replace("{username}", user.name)
            .replace("{display_name}", getattr(user, "display_name", user.name))
            .replace("{id}", str(user.id))
        )

        dm_channel = await user.create_dm()
        sent = await dm_channel.send(final_text)

        ai_cog = bot_instance.get_cog("AIChat")
        if ai_cog and hasattr(ai_cog, "llm_message_ids"):
            ai_cog.llm_message_ids.add(sent.id)

        import time
        from datetime import datetime, timezone
        try:
            db.reload()
        except Exception:
            pass
        if not hasattr(db, "special_invites") or db.special_invites is None:
            db.special_invites = {}

        db.special_invites[str(user_id)] = {
            "invited_by": "Dashboard Owner",
            "invited_at": datetime.now(timezone.utc).strftime("%B %d, %Y %I:%M %p"),
            "status": "onboarding",
            "onboarding_step": 0,
            "custom_nickname": "",
            "current_mood": "cheerful",
            "last_mood_switch": time.time(),
            "message_count": 0,
            "notes": ""
        }
        db.save_data()
        return getattr(user, "display_name", user.name)

    try:
        future = asyncio.run_coroutine_threadsafe(do_send_invite(), bot_instance.loop)
        name = future.result(timeout=10)
        return jsonify({"success": True, "message": f"Special VIP Invite delivered to {name}'s DM!"})
    except discord.Forbidden:
        return jsonify({"success": False, "error": "Cannot send DM to this user. Their Discord DMs are closed or they do not accept DMs from bots."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/special_invites/send_dm', methods=['POST'])
def send_custom_dm(gid):
    body = flask_request.json or {}
    user_id = str(body.get("user_id", "")).strip()
    msg_text = body.get("message", "").strip()

    if not user_id:
        return jsonify({"success": False, "error": "Please provide a valid User ID or select a member."})
    if not msg_text:
        return jsonify({"success": False, "error": "Message content cannot be empty."})

    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."})

    msg_text = replace_plain_emojis(msg_text)

    async def do_send_dm():
        uid_int = int(user_id) if user_id.isdigit() else None
        if not uid_int:
            raise Exception("Invalid User ID format.")
        user = bot_instance.get_user(uid_int) or await bot_instance.fetch_user(uid_int)
        if not user:
            raise Exception("Discord user not found.")

        final_text = (
            msg_text
            .replace("{mention}", user.mention)
            .replace("{username}", user.name)
            .replace("{display_name}", getattr(user, "display_name", user.name))
            .replace("{id}", str(user.id))
        )

        dm_channel = await user.create_dm()
        await dm_channel.send(final_text)
        return getattr(user, "display_name", user.name)

    try:
        future = asyncio.run_coroutine_threadsafe(do_send_dm(), bot_instance.loop)
        name = future.result(timeout=10)
        return jsonify({"success": True, "message": f"Direct message sent successfully to {name}'s DM!"})
    except discord.Forbidden:
        return jsonify({"success": False, "error": "Cannot send DM to this user. Their Discord DMs are closed or they do not accept DMs from bots."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/special_invites/revoke', methods=['POST'])
def revoke_special_invite(gid):
    body = flask_request.json or {}
    user_id = str(body.get("user_id", "")).strip()
    if not user_id:
        return jsonify({"success": False, "error": "User ID is required."})

    try:
        db.reload()
    except Exception:
        pass

    if hasattr(db, "special_invites") and user_id in db.special_invites:
        del db.special_invites[user_id]
        db.save_data()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "User is not in the VIP invites list."})

@app.route('/api/guild/<gid>/special_invites/reset_persona', methods=['POST'])
def reset_special_invite_persona(gid):
    body = flask_request.json or {}
    user_id = str(body.get("user_id", "")).strip()
    if not user_id:
        return jsonify({"success": False, "error": "User ID is required."})

    try:
        db.reload()
    except Exception:
        pass

    if hasattr(db, "special_invites") and user_id in db.special_invites:
        db.special_invites[user_id]["status"] = "onboarding"
        db.special_invites[user_id]["onboarding_step"] = 0
        db.special_invites[user_id]["custom_nickname"] = ""
        db.special_invites[user_id]["notes"] = ""
        db.special_invites[user_id]["current_mood"] = "cheerful"
        db.save_data()
        return jsonify({"success": True, "message": "VIP Persona reset. Friday will re-interview them on next DM!"})
    return jsonify({"success": False, "error": "User is not in the VIP invites list."})

# ───────────────────── Bot Lifecycle ─────────────────────

@app.route('/api/bot/stop', methods=['POST'])
def stop_bot():
    import signal, threading, time
    def kill_server():
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=kill_server).start()
    return jsonify({"success": True})

if __name__ == '__main__':
    print("\n🤖 Friday Dashboard is running!")
    print("   Open http://localhost:5000 in your browser.\n")
    app.run(debug=True, port=5000)
