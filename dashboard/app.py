from flask import Flask, render_template, jsonify, request as flask_request
import json
import os
import sys
import uuid
import requests
import asyncio
import time
import discord
from datetime import datetime, timezone
from urllib.parse import urlparse
from dotenv import load_dotenv

# Ensure parent directory is in sys.path to import database and models
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from database import db
from emoji_utils import replace_plain_emojis, parse_btn, format_embed_description

# Load environment variables
load_dotenv(os.path.join(PARENT_DIR, '.env'))

app = Flask(__name__)
BOT_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_API = "https://discord.com/api/v10"

RANK_BG_DIR = os.path.join(app.root_path, "static", "uploads", "rank_backgrounds")
os.makedirs(RANK_BG_DIR, exist_ok=True)

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
    return render_template('dashboard.html', cache_buster=int(time.time()))

@app.after_request
def add_no_cache_headers(response):
    if flask_request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@app.route('/favicon.ico')
def favicon():
    from flask import Response
    return Response(status=204)

@app.route('/static/avatar.png')
def default_avatar_redirect():
    from flask import redirect
    return redirect("https://cdn.discordapp.com/embed/avatars/0.png")

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
            cat_map = {str(ch["id"]): ch.get("name", "Category") for ch in channels if ch.get("type") == 4}
            result = [{
                "id": str(ch["id"]),
                "name": ch["name"],
                "category": cat_map.get(str(ch.get("parent_id")), "General / Uncategorized")
            } for ch in channels if ch.get("type") in (0, 5)]
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
        
        # 1. Current guild emojis first
        if guild:
            for e in guild.emojis:
                if not e.available: continue
                seen_ids.add(e.id)
                result.append({
                    "id": str(e.id),
                    "name": e.name,
                    "animated": bool(e.animated),
                    "url": str(e.url),
                    "code": f"<a:{e.name}:{e.id}>" if e.animated else f"<:{e.name}:{e.id}>",
                    "server": guild.name,
                    "current_guild": True
                })
                
        # 2. Other connected servers Friday is in
        for g in bot_instance.guilds:
            if guild and g.id == guild.id: continue
            for e in g.emojis:
                if not e.available or e.id in seen_ids: continue
                seen_ids.add(e.id)
                result.append({
                    "id": str(e.id),
                    "name": e.name,
                    "animated": bool(e.animated),
                    "url": str(e.url),
                    "code": f"<a:{e.name}:{e.id}>" if e.animated else f"<:{e.name}:{e.id}>",
                    "server": g.name,
                    "current_guild": False
                })
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
            "audit-deleted", "audit-edits", "audit-banned", "audit-timeouts", "audit-whitelisted", 
            "audit-antinuke", "audit-abuse", "audit-antiraid", "audit-antispam", 
            "audit-roles", "audit-channels", "audit-voice", "audit-members", "audit-server"
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

def resolve_card_bg_url(path):
    """Robustly resolve static URL for uploaded card backgrounds."""
    if not path or not isinstance(path, str):
        return ""
    if path.startswith("http://") or path.startswith("https://") or path.startswith("/static/"):
        return path
    base = os.path.basename(path)
    if os.path.exists(os.path.join(RANK_BG_DIR, base)):
        return f"/static/uploads/rank_backgrounds/{base}"
    if os.path.exists(path):
        return f"/static/uploads/rank_backgrounds/{base}"
    if base and ("." in base):
        return f"/static/uploads/rank_backgrounds/{base}"
    return ""

@app.route('/api/guild/<gid>/leveling')
def get_leveling(gid):
    gid_str = str(gid)
    chan_id = db.level_channels.get(gid_str, None)
    lu_path = db.levelup_card_backgrounds.get(gid_str)
    rk_path = db.rank_card_backgrounds.get(gid_str) or db.rank_backgrounds.get(gid_str)
    lu_url = resolve_card_bg_url(lu_path)
    rk_url = resolve_card_bg_url(rk_path)

    return jsonify({
        "channel": str(chan_id) if chan_id else "",
        "message": db.level_messages.get(gid_str, "--------------------\n# 🎉 LEVEL UP!\n**{user}** just advanced to **Level {level}**! Keep it up!\n--------------------"),
        "mode": db.level_modes.get(gid_str, "both"),
        "levelup_background": lu_url,
        "rank_background": rk_url,
        "background": lu_url or rk_url
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

        mode = db.level_modes.get(gid, "both")
        card_file = None
        if mode in ("image", "both"):
            leveling_cog = bot_instance.get_cog("Leveling")
            if leveling_cog:
                try:
                    target_user = channel.guild.me if channel.guild and channel.guild.me else bot_instance.user
                    card_fut = asyncio.run_coroutine_threadsafe(
                        leveling_cog.generate_levelup_card(target_user, 4, 5, guild_id=str(gid)),
                        bot_instance.loop
                    )
                    card_file = card_fut.result(timeout=6)
                except Exception as card_err:
                    print(f"⚠️ Level test card generation error: {card_err}")

        # Safely run channel.send on bot's asyncio event loop from Flask thread
        if mode == "image" and card_file:
            coro = channel.send(file=card_file)
        elif mode == "both" and card_file:
            coro = channel.send(content=formatted_msg, file=card_file)
        else:
            coro = channel.send(formatted_msg)

        future = asyncio.run_coroutine_threadsafe(coro, bot_instance.loop)
        future.result(timeout=6)

        return jsonify({"success": True, "channel_name": channel.name})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/guild/<gid>/leveling/upload-background', methods=['POST'])
@app.route('/api/guild/<gid>/card-background/upload', methods=['POST'])
def upload_rank_background(gid):
    gid_str = str(gid)
    card_type = flask_request.form.get("card_type", "rank")
    try:
        os.makedirs(RANK_BG_DIR, exist_ok=True)
        file = flask_request.files.get('background_file') or flask_request.files.get('file') or flask_request.files.get('background')
        if not file or not file.filename:
            return jsonify({"success": False, "error": "No file uploaded."}), 400
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.webp']:
            return jsonify({"success": False, "error": "Unsupported file format. Please upload PNG, JPG, or WebP."}), 400
        safe_filename = f"{card_type}_bg_{gid_str}_{uuid.uuid4().hex[:8]}{ext}"
        save_path = os.path.join(RANK_BG_DIR, safe_filename)
        file.save(save_path)
        
        rel_url = f"/static/uploads/rank_backgrounds/{safe_filename}"
        if card_type == "levelup":
            db.levelup_card_backgrounds[gid_str] = save_path
        elif card_type == "invite":
            db.invite_card_backgrounds[gid_str] = save_path
        elif card_type == "activity":
            db.activity_card_backgrounds[gid_str] = save_path
        elif card_type == "leaderboard":
            db.leaderboard_card_backgrounds[gid_str] = save_path
        elif card_type == "booster":
            db.booster_backgrounds[gid_str] = save_path
        else:
            db.rank_card_backgrounds[gid_str] = save_path
        db.save_data()
        return jsonify({"success": True, "url": rel_url, "path": save_path, "card_type": card_type})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/leveling/reset-background', methods=['POST'])
@app.route('/api/guild/<gid>/card-background/reset', methods=['POST'])
def reset_rank_background(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    card_type = body.get("card_type") or flask_request.args.get("card_type", "rank")
    if card_type == "levelup" and gid_str in db.levelup_card_backgrounds:
        del db.levelup_card_backgrounds[gid_str]
    elif card_type == "invite" and gid_str in db.invite_card_backgrounds:
        del db.invite_card_backgrounds[gid_str]
    elif card_type == "activity" and gid_str in db.activity_card_backgrounds:
        del db.activity_card_backgrounds[gid_str]
    elif card_type == "leaderboard" and gid_str in db.leaderboard_card_backgrounds:
        del db.leaderboard_card_backgrounds[gid_str]
    elif card_type == "booster" and gid_str in db.booster_backgrounds:
        del db.booster_backgrounds[gid_str]
    elif gid_str in db.rank_card_backgrounds:
        del db.rank_card_backgrounds[gid_str]
    db.save_data()
    return jsonify({"success": True, "card_type": card_type})

# ───────────────────── API: Booster Perks & Announcements ─────────────────────

BOOSTER_BG_DIR = os.path.join(app.root_path, "static", "uploads", "booster_backgrounds")
os.makedirs(BOOSTER_BG_DIR, exist_ok=True)

@app.route('/api/guild/<gid>/booster', methods=['GET'])
def get_booster_settings(gid):
    gid_str = str(gid)
    cfg = db.booster_perks.get(gid_str, {
        "enabled": True,
        "channel_id": "",
        "reward_role_id": "",
        "remove_role_on_unboost": True,
        "mode": "both",
        "announcement_message": "🚀 Huge thank you to {user} for boosting **{guild}**! You unlocked {reward_role} perks! ✨",
        "dm_enabled": True,
        "dm_message": "💜 Huge thank you for boosting **{guild}**, {user}!\nYou've unlocked exclusive booster perks and our deepest appreciation! ✨",
        "embed_color": "#f47fff"
    })
    
    current_boosts = 0
    current_tier = 0
    if bot_instance and gid_str.isdigit():
        g = bot_instance.get_guild(int(gid_str))
        if g:
            current_boosts = getattr(g, "premium_subscription_count", 0) or 0
            current_tier = getattr(g, "premium_tier", 0) or 0

    bg_path = db.booster_backgrounds.get(gid_str)
    wallpaper_url = resolve_card_bg_url(bg_path) if bg_path else ""

    return jsonify({
        "success": True,
        "config": cfg,
        "current_boosts": current_boosts,
        "current_tier": current_tier,
        "wallpaper_url": wallpaper_url
    })

@app.route('/api/guild/<gid>/booster', methods=['POST'])
def save_booster_settings(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    
    cfg = db.booster_perks.get(gid_str, {})
    cfg["enabled"] = bool(body.get("enabled", True))
    cfg["channel_id"] = str(body.get("channel_id", "")).strip()
    cfg["reward_role_id"] = str(body.get("reward_role_id", "")).strip()
    cfg["remove_role_on_unboost"] = bool(body.get("remove_role_on_unboost", True))
    cfg["mode"] = str(body.get("mode", "both")).strip()
    cfg["announcement_message"] = str(body.get("announcement_message", "")).strip()
    cfg["dm_enabled"] = bool(body.get("dm_enabled", True))
    cfg["dm_message"] = str(body.get("dm_message", "")).strip()
    cfg["embed_color"] = str(body.get("embed_color", "#f47fff")).strip()

    db.booster_perks[gid_str] = cfg
    db.save_data()
    return jsonify({"success": True, "config": cfg})

@app.route('/api/guild/<gid>/booster/test', methods=['POST'])
def test_booster_announcement(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    cfg = db.booster_perks.get(gid_str, {})

    channel_id = body.get("channel_id") or cfg.get("channel_id")
    if not channel_id:
        return jsonify({"success": False, "error": "Please configure or select an announcement channel first."}), 400

    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected to Discord right now."}), 503

    try:
        g = bot_instance.get_guild(int(gid_str)) if gid_str.isdigit() else None
        if not g:
            return jsonify({"success": False, "error": "Server guild not found or Friday is not connected to it."}), 404

        chan = g.get_channel(int(channel_id))
        if not chan:
            return jsonify({"success": False, "error": f"Channel ID {channel_id} not found in {g.name}."}), 404

        booster_cog = bot_instance.get_cog("BoosterPerks")
        if not booster_cog:
            return jsonify({"success": False, "error": "BoosterPerks cog is not loaded on Friday bot."}), 500

        # Pick test booster member
        test_member = g.me or bot_instance.user
        if g.members:
            boosters = [m for m in g.members if m.premium_since is not None]
            if boosters:
                test_member = boosters[0]
            elif g.owner:
                test_member = g.owner

        mode = body.get("mode") or cfg.get("mode", "both")
        msg_template = body.get("announcement_message") or cfg.get("announcement_message") or (
            "🚀 Huge thank you to {user} for boosting **{guild}**! You unlocked {reward_role} perks! ✨"
        )

        role_str = "@Booster"
        reward_role_id = body.get("reward_role_id") or cfg.get("reward_role_id")
        if reward_role_id:
            try:
                r = g.get_role(int(reward_role_id))
                if r:
                    role_str = r.mention
            except Exception:
                pass

        formatted_msg = msg_template.replace("{user}", test_member.mention) \
                                    .replace("{username}", test_member.name) \
                                    .replace("{guild}", g.name) \
                                    .replace("{boosts}", str(g.premium_subscription_count or 0)) \
                                    .replace("{tier}", str(g.premium_tier or 0)) \
                                    .replace("{reward_role}", role_str)

        formatted_msg = replace_plain_emojis(formatted_msg, bot_instance, guild_id=gid, guild=g)

        card_file = None
        if mode in ("both", "image"):
            card_fut = asyncio.run_coroutine_threadsafe(
                booster_cog.generate_booster_card(test_member, g),
                bot_instance.loop
            )
            card_file = card_fut.result(timeout=10)

        # Dispatch
        async def do_send():
            if mode == "image" and card_file:
                return await chan.send(file=card_file)
            elif mode == "both" and card_file:
                return await chan.send(content=formatted_msg, file=card_file)
            else:
                return await chan.send(content=formatted_msg)

        fut = asyncio.run_coroutine_threadsafe(do_send(), bot_instance.loop)
        fut.result(timeout=10)

        return jsonify({"success": True, "channel_name": chan.name})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/booster/wallpaper', methods=['POST'])
def upload_booster_wallpaper(gid):
    gid_str = str(gid)
    try:
        os.makedirs(BOOSTER_BG_DIR, exist_ok=True)
        file = flask_request.files.get('file') or flask_request.files.get('background_file') or flask_request.files.get('background')
        if not file or not file.filename:
            return jsonify({"success": False, "error": "No file uploaded."}), 400
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.webp']:
            return jsonify({"success": False, "error": "Unsupported format. Please upload PNG, JPG, or WebP."}), 400
        safe_filename = f"booster_bg_{gid_str}_{uuid.uuid4().hex[:8]}{ext}"
        save_path = os.path.join(BOOSTER_BG_DIR, safe_filename)
        file.save(save_path)
        
        db.booster_backgrounds[gid_str] = save_path
        db.save_data()
        
        rel_url = f"/static/uploads/booster_backgrounds/{safe_filename}"
        return jsonify({"success": True, "url": rel_url, "path": save_path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/booster/wallpaper/reset', methods=['POST'])
def reset_booster_wallpaper(gid):
    gid_str = str(gid)
    if gid_str in db.booster_backgrounds:
        del db.booster_backgrounds[gid_str]
        db.save_data()
    return jsonify({"success": True})

# ───────────────────── API: Invite Tracker ─────────────────────

@app.route('/api/guild/<gid>/invite-tracker', methods=['GET'])
def get_invite_tracker(gid):
    gid_str = str(gid)
    cfg = db.invite_tracker.get(gid_str, {
        "enabled": True,
        "log_channel": "",
        "join_msg": "👋 Welcome {user} to **{guild}**!\nInvited by {inviter} (Code: `{code}`).\n📈 {inviter_name} now has **{invites}** invites (**{regular}** regular, **{bonus}** bonus, **{left}** left, **{fake}** fake)!",
        "leave_msg": "📤 **{user.name}** left the server. They were invited by {inviter}. ({inviter_name} now has **{invites}** invites).",
        "embed": True,
        "embed_title": "📥 Member Joined",
        "embed_color": "#5865F2"
    })
    
    # Compile top inviters
    counts = db.invite_counts.get(gid_str, {})
    inviters_list = []
    guild_obj = bot_instance.get_guild(int(gid)) if bot_instance and str(gid).isdigit() else None
    
    for uid_str, d in counts.items():
        reg = d.get("regular", 0)
        bon = d.get("bonus", 0)
        lft = d.get("left", 0)
        fak = d.get("fake", 0)
        tot = reg + bon - lft - fak
        
        name = f"User {uid_str[-4:]}"
        avatar_url = "/static/avatar.png"
        if guild_obj:
            m = guild_obj.get_member(int(uid_str))
            if m:
                name = m.display_name
                avatar_url = m.display_avatar.url
                
        inviters_list.append({
            "user_id": uid_str,
            "name": name,
            "avatar": str(avatar_url),
            "regular": reg,
            "bonus": bon,
            "left": lft,
            "fake": fak,
            "total": tot
        })
    inviters_list.sort(key=lambda x: x["total"], reverse=True)

    inv_bg = db.invite_card_backgrounds.get(gid_str)
    inv_bg_url = resolve_card_bg_url(inv_bg)

    return jsonify({
        "success": True,
        "config": cfg,
        "inviters": inviters_list[:50],
        "invite_card_background": inv_bg_url
    })

@app.route('/api/guild/<gid>/activity-cards', methods=['GET'])
def get_activity_cards(gid):
    gid_str = str(gid)
    act_bg = db.activity_card_backgrounds.get(gid_str)
    lb_bg = db.leaderboard_card_backgrounds.get(gid_str)
    return jsonify({
        "success": True,
        "activity_card_background": resolve_card_bg_url(act_bg),
        "leaderboard_card_background": resolve_card_bg_url(lb_bg)
    })

@app.route('/api/guild/<gid>/invite-tracker/save', methods=['POST'])
def save_invite_tracker(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    
    if gid_str not in db.invite_tracker:
        db.invite_tracker[gid_str] = {}
        
    db.invite_tracker[gid_str]["enabled"] = bool(body.get("enabled", True))
    db.invite_tracker[gid_str]["log_channel"] = str(body.get("log_channel", "")).strip()
    db.invite_tracker[gid_str]["join_msg"] = body.get("join_msg", "")
    db.invite_tracker[gid_str]["leave_msg"] = body.get("leave_msg", "")
    db.invite_tracker[gid_str]["embed"] = bool(body.get("embed", True))
    db.invite_tracker[gid_str]["embed_title"] = body.get("embed_title", "📥 Member Joined")
    db.invite_tracker[gid_str]["embed_color"] = body.get("embed_color", "#5865F2")
    db.invite_tracker[gid_str]["banner_url"] = str(body.get("banner_url", "")).strip()
    db.save_data()
    return jsonify({"success": True, "message": "Invite tracker settings saved successfully!"})

@app.route('/api/guild/<gid>/invite-tracker/upload-banner', methods=['POST'])
def upload_invite_banner(gid):
    gid_str = str(gid)
    try:
        os.makedirs(INVITE_BANNER_DIR, exist_ok=True)
        file = flask_request.files.get('banner_file') or flask_request.files.get('file')
        if not file or not file.filename:
            return jsonify({"success": False, "error": "No file uploaded."}), 400
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
            return jsonify({"success": False, "error": "Unsupported file format. Please upload PNG, JPG, GIF, or WebP."}), 400
        safe_filename = f"invite_banner_{gid_str}_{uuid.uuid4().hex[:8]}{ext}"
        save_path = os.path.join(INVITE_BANNER_DIR, safe_filename)
        file.save(save_path)
        
        rel_url = f"/static/uploads/invite_banners/{safe_filename}"
        if gid_str not in db.invite_tracker:
            db.invite_tracker[gid_str] = {}
        db.invite_tracker[gid_str]["banner_url"] = rel_url
        db.save_data()
        return jsonify({"success": True, "url": rel_url})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/invite-tracker/bonus', methods=['POST'])
def adjust_invite_bonus(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    user_id = str(body.get("user_id", "")).strip()
    amount = int(body.get("amount", 0))
    action = body.get("action", "add") # 'add' or 'remove' or 'clear'

    if not user_id:
        return jsonify({"success": False, "error": "Invalid user ID"}), 400

    if gid_str not in db.invite_counts:
        db.invite_counts[gid_str] = {}
    if user_id not in db.invite_counts[gid_str]:
        db.invite_counts[gid_str][user_id] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

    if action == "add":
        db.invite_counts[gid_str][user_id]["bonus"] += amount
    elif action == "remove":
        db.invite_counts[gid_str][user_id]["bonus"] = max(0, db.invite_counts[gid_str][user_id]["bonus"] - amount)
    elif action == "clear":
        db.invite_counts[gid_str][user_id] = {"regular": 0, "left": 0, "fake": 0, "bonus": 0}

    db.save_data()
    c = db.invite_counts[gid_str][user_id]
    net_total = c["regular"] + c["bonus"] - c["left"] - c["fake"]
    return jsonify({"success": True, "counts": c, "total": net_total})

@app.route('/api/guild/<gid>/invite-tracker/test', methods=['POST'])
def test_invite_message(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    channel_id = body.get("channel_id")
    msg_type = body.get("type", "join") # 'join' or 'leave'

    if not channel_id:
        return jsonify({"success": False, "error": "Please select a channel to send the test message to."})

    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected right now."})

    try:
        channel = bot_instance.get_channel(int(channel_id))
        if not channel:
            return jsonify({"success": False, "error": "Channel not found or Friday lacks permissions."})

        cfg = db.invite_tracker.get(gid_str, {})
        # If body provides preview overrides, use them
        if "join_msg" in body:
            cfg["join_msg"] = body["join_msg"]
        if "embed_title" in body:
            cfg["embed_title"] = body["embed_title"]
        if "banner_url" in body:
            cfg["banner_url"] = body["banner_url"]

        inv_cog = bot_instance.get_cog("InviteTracker")
        if inv_cog:
            coro = inv_cog.send_test_notification(channel, bot_instance.user, cfg=cfg, msg_type=msg_type)
            future = asyncio.run_coroutine_threadsafe(coro, bot_instance.loop)
            future.result(timeout=6)
            return jsonify({"success": True, "channel_name": channel.name})

        # Fallback manual build if cog not resolved
        tpl = cfg.get("join_msg") if msg_type == "join" else cfg.get("leave_msg")
        if not tpl:
            tpl = "👋 Welcome {user} to **{guild}**! Invited by {inviter}. {inviter_name} now has **{invites}** invites!"
        
        formatted = tpl.replace("{user}", bot_instance.user.mention) \
                       .replace("{user.name}", bot_instance.user.name) \
                       .replace("{guild}", channel.guild.name) \
                       .replace("{inviter}", bot_instance.user.mention) \
                       .replace("{inviter.name}", bot_instance.user.name) \
                       .replace("{code}", "friday-vip") \
                       .replace("{invites}", "12") \
                       .replace("{regular}", "10") \
                       .replace("{bonus}", "3") \
                       .replace("{left}", "1") \
                       .replace("{fake}", "0") \
                       .replace("{total_members}", str(channel.guild.member_count))

        formatted = replace_plain_emojis(formatted, bot_instance, guild_id=gid)

        if cfg.get("embed", True):
            color = int(cfg.get("embed_color", "5865F2").replace("#", ""), 16)
            raw_title = cfg.get("embed_title", "📥 Member Joined (Test Preview)")
            title = replace_plain_emojis(raw_title, bot_instance, guild_id=gid)
            embed = discord.Embed(
                title=title,
                description=formatted,
                color=color
            )
            embed.set_thumbnail(url=bot_instance.user.display_avatar.url)
            banner = cfg.get("banner_url") or cfg.get("banner")
            if banner:
                embed.set_image(url=banner)
            embed.set_footer(text="Friday Invite Tracker • Test Card • Timezone: IST")
            coro = channel.send(embed=embed)
        else:
            coro = channel.send(formatted)

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
    exclusive = bool(body.get("exclusive", True))
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
        if p_desc:
            p_desc = format_embed_description(p_desc, target_width=50)

        embed = discord.Embed(title=p_title, description=p_desc, color=discord.Color(color_int))
        
        avatar_url = str(bot_instance.user.display_avatar.url) if bot_instance.user and bot_instance.user.display_avatar else None
        thumbnail_mode = str(body.get("thumbnail_mode") or ("bot" if body.get("show_thumbnail") else "none")).lower()
        if thumbnail_mode == "bot" and avatar_url:
            embed.set_thumbnail(url=avatar_url)
        elif thumbnail_mode == "server" and guild.icon:
            embed.set_thumbnail(url=str(guild.icon.url))

        panel_text = ""
        for role, emoji_obj in roles_setup:
            panel_text += f"{str(emoji_obj)} ─ {role.mention}\n"

        if footer_text:
            p_footer = replace_plain_emojis(footer_text, bot_instance, guild_id=gid)
            has_custom_emoji = bool(re.search(r'<a?:[a-zA-Z0-9_]+:[0-9]+>', p_footer))
            is_callout = p_footer.strip().startswith(">")

            if has_custom_emoji or is_callout:
                # Discord embed footers DO NOT support custom emojis or markdown (they render raw <a:name:id> strings).
                # To display the true animated GIF/custom emoji and formatted blockquote, we embed it directly into the panel body:
                callout_line = p_footer.strip()
                if not callout_line.startswith(">"):
                    callout_line = f"> {callout_line}"
                panel_text += f"\n{callout_line}"

                # In the native Discord footer bar, provide clean text without raw syntax:
                clean_footer = re.sub(r'<a?:([a-zA-Z0-9_]+):[0-9]+>', r'', p_footer)
                clean_footer = re.sub(r'^[>\s*#]+', '', clean_footer).strip()
                clean_footer = re.sub(r'\*+', '', clean_footer).strip()
                if clean_footer:
                    embed.set_footer(text=clean_footer, icon_url=avatar_url)
                elif avatar_url:
                    embed.set_footer(text=guild.name, icon_url=avatar_url)
            else:
                embed.set_footer(text=p_footer, icon_url=avatar_url)

        embed.add_field(name="Available Roles", value=panel_text, inline=False)

        panel_type = str(body.get("panel_type") or "select").lower()
        if panel_type not in ("select", "reaction"):
            panel_type = "select"

        if panel_type == "select":
            from cogs.reaction_roles import ReactionRoleSelectView
            temp_id = str(discord.utils.time_snowflake(discord.utils.utcnow()))
            select_options = []
            stored_opts = []
            for role, emoji_obj in roles_setup:
                opt = discord.SelectOption(
                    label=role.name[:100],
                    value=str(role.id),
                    description="Claim this role"[:100],
                    emoji=emoji_obj if isinstance(emoji_obj, (discord.PartialEmoji, discord.Emoji)) else (emoji_obj if isinstance(emoji_obj, str) and len(emoji_obj) <= 4 else None)
                )
                select_options.append(opt)
                stored_opts.append({
                    "label": role.name[:100],
                    "value": str(role.id),
                    "description": "Claim this role",
                    "emoji": str(emoji_obj)
                })

            select_options.append(discord.SelectOption(
                label="None / Remove Role",
                value="clear",
                emoji="❌",
                description="Clear your self-role selection"
            ))
            stored_opts.append({
                "label": "None / Remove Role",
                "value": "clear",
                "description": "Clear your self-role selection",
                "emoji": "❌"
            })

            view = ReactionRoleSelectView(options=select_options, panel_id=temp_id, exclusive=exclusive)
            msg = await channel.send(embed=embed, view=view)
            msg_id = str(msg.id)
            view.panel_id = msg_id
            bot_instance.add_view(view)

            db.reaction_roles[msg_id] = {str(e): r.id for r, e in roles_setup}
            db.data.setdefault("reaction_roles_meta", {})[msg_id] = {
                "exclusive": exclusive,
                "channel_id": str(channel_id),
                "guild_id": str(gid),
                "panel_type": "select",
                "options": stored_opts
            }
        else:
            msg = await channel.send(embed=embed)
            msg_id = str(msg.id)
            if msg_id not in db.reaction_roles:
                db.reaction_roles[msg_id] = {}

            for role, emoji_obj in roles_setup:
                await msg.add_reaction(emoji_obj)
                db.reaction_roles[msg_id][str(emoji_obj)] = role.id

            db.data.setdefault("reaction_roles_meta", {})[msg_id] = {
                "exclusive": exclusive,
                "channel_id": str(channel_id),
                "guild_id": str(gid),
                "panel_type": "reaction"
            }

        # Auto-save current configuration as saved draft so refresh never wipes out the 10 roles
        if not hasattr(db, "saved_reaction_roles") or not isinstance(db.saved_reaction_roles, dict):
            db.saved_reaction_roles = {}
        db.saved_reaction_roles[str(gid)] = body
        db.save_data()
        return channel.name, len(roles_setup)

    try:
        fut = asyncio.run_coroutine_threadsafe(do_create_panel(), bot_instance.loop)
        ch_name, count = fut.result(timeout=10)
        return jsonify({"success": True, "channel_name": ch_name, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/guild/<gid>/reaction_roles/saved_draft', methods=['GET'])
def get_reaction_roles_draft(gid):
    draft = getattr(db, "saved_reaction_roles", {}).get(str(gid), {})
    return jsonify({"success": True, "draft": draft})


@app.route('/api/guild/<gid>/reaction_roles/save_draft', methods=['POST'])
def save_reaction_roles_draft_endpoint(gid):
    body = flask_request.json or {}
    if not hasattr(db, "saved_reaction_roles") or not isinstance(db.saved_reaction_roles, dict):
        db.saved_reaction_roles = {}
    db.saved_reaction_roles[str(gid)] = body
    db.save_data()
    return jsonify({"success": True, "message": "Draft saved successfully!"})


@app.route('/api/guild/<gid>/reaction_roles/clear_draft', methods=['POST'])
def clear_reaction_roles_draft_endpoint(gid):
    if hasattr(db, "saved_reaction_roles") and isinstance(db.saved_reaction_roles, dict):
        db.saved_reaction_roles.pop(str(gid), None)
        db.save_data()
    return jsonify({"success": True})


# ───────────────────── API: Staff Custom Prefix & Whitelist ─────────────────────

@app.route('/api/guild/<gid>/prefix_settings', methods=['GET'])
def get_prefix_settings(gid):
    gid_str = str(gid)
    prefix = getattr(db, "custom_prefixes", {}).get(gid_str, "!")
    wl = getattr(db, "prefix_whitelist", {}).get(gid_str, {
        "roles": [],
        "members": [],
        "commands": {"purge": True, "lock": True, "unlock": True, "ban": True, "tm": True}
    })
    return jsonify({
        "success": True,
        "prefix": prefix,
        "whitelist": wl
    })


@app.route('/api/guild/<gid>/prefix_settings', methods=['POST'])
def save_prefix_settings(gid):
    gid_str = str(gid)
    body = flask_request.json or {}
    new_prefix = str(body.get("prefix") or "!").strip()
    if len(new_prefix) > 5:
        return jsonify({"success": False, "error": "Prefix cannot be longer than 5 characters."})
    if not new_prefix:
        new_prefix = "!"

    if not hasattr(db, "custom_prefixes") or not isinstance(db.custom_prefixes, dict):
        db.custom_prefixes = {}
    db.custom_prefixes[gid_str] = new_prefix

    if not hasattr(db, "prefix_whitelist") or not isinstance(db.prefix_whitelist, dict):
        db.prefix_whitelist = {}

    wl_data = body.get("whitelist") or {}
    db.prefix_whitelist[gid_str] = {
        "roles": [str(r) for r in wl_data.get("roles", []) if str(r).isdigit()],
        "members": [str(m) for m in wl_data.get("members", []) if str(m).isdigit()],
        "commands": {
            "purge": bool(wl_data.get("commands", {}).get("purge", True)),
            "lock": bool(wl_data.get("commands", {}).get("lock", True)),
            "unlock": bool(wl_data.get("commands", {}).get("unlock", True)),
            "ban": bool(wl_data.get("commands", {}).get("ban", True)),
            "tm": bool(wl_data.get("commands", {}).get("tm", True))
        }
    }
    db.save_data()
    return jsonify({"success": True, "prefix": new_prefix, "whitelist": db.prefix_whitelist[gid_str]})

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
    avatar_mode = str(data.get("avatar_mode") or ("friday" if show_thumbnail else "none")).lower()
    footer_text = data.get("footer", "").strip()
    ann_format = data.get("format", "embed").strip().lower()

    if not content and not title:
        return jsonify({"success": False, "error": "Announcement content or title is required."})

    try:
        color_int = int(color_hex.lstrip('#'), 16)
    except Exception:
        color_int = 0x2dd4bf

    # Check if this broadcast is scheduled for a future time
    scheduled_time = data.get("scheduled_time")
    if scheduled_time:
        try:
            if "T" in str(scheduled_time):
                sched_dt = datetime.datetime.fromisoformat(str(scheduled_time))
            else:
                sched_dt = datetime.datetime.strptime(str(scheduled_time), "%Y-%m-%d %H:%M")
        except Exception as e:
            return jsonify({"success": False, "error": f"Invalid scheduled date/time format: {e}"}), 400

        tz_name = db.birthdays_config.get(gid_str, {}).get("timezone", "Asia/Kolkata")
        try:
            loc_tz = pytz.timezone(tz_name)
        except Exception:
            loc_tz = pytz.timezone("Asia/Kolkata")

        if sched_dt.tzinfo is None:
            sched_dt = loc_tz.localize(sched_dt)
        sched_utc = sched_dt.astimezone(datetime.timezone.utc)
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        if sched_utc <= now_utc + datetime.timedelta(seconds=15):
            return jsonify({"success": False, "error": "Scheduled time must be in the future! Please pick a future date and time."}), 400

        item_id = uuid.uuid4().hex[:10]
        scheduled_item = {
            "id": item_id,
            "guild_id": gid_str,
            "channel_id": str(channel_id),
            "title": title,
            "content": content,
            "ping": ping,
            "color": color_hex,
            "avatar_mode": avatar_mode,
            "footer": footer_text,
            "format": ann_format,
            "format_mode": ann_format,
            "scheduled_ts": sched_utc.timestamp(),
            "scheduled_iso": sched_utc.isoformat(),
            "created_at": now_utc.isoformat(),
            "status": "pending",
            "author_name": "Dashboard Admin"
        }
        queue = db.scheduled_announcements.setdefault(gid_str, [])
        queue.append(scheduled_item)
        db.save_data()

        display_time = sched_dt.strftime("%b %d, %Y at %I:%M %p")
        return jsonify({
            "success": True,
            "scheduled": True,
            "message": f"Announcement successfully scheduled for {display_time} ({tz_name})!",
            "scheduled_time": display_time,
            "item": scheduled_item
        })

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

            chosen_avatar_url = None
            if avatar_mode == "friday":
                if bot_instance.user and bot_instance.user.display_avatar:
                    chosen_avatar_url = str(bot_instance.user.display_avatar.url)
            elif avatar_mode == "server":
                if guild.icon:
                    chosen_avatar_url = str(guild.icon.url)
                elif bot_instance.user and bot_instance.user.display_avatar:
                    chosen_avatar_url = str(bot_instance.user.display_avatar.url)

            if chosen_avatar_url:
                embed.set_thumbnail(url=chosen_avatar_url)

            if footer_text:
                embed.set_footer(text=footer_text, icon_url=chosen_avatar_url)

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

@app.route('/api/guild/<gid>/announcements/scheduled')
def get_scheduled_announcements(gid):
    gid_str = str(gid)
    queue = db.scheduled_announcements.get(gid_str, [])
    if not isinstance(queue, list):
        queue = []

    result = []
    for item in queue:
        entry = dict(item)
        ch_name = item.get("channel_id")
        if bot_instance:
            try:
                g = bot_instance.get_guild(int(gid_str))
                if g:
                    ch = g.get_channel(int(item.get("channel_id", 0)))
                    if ch:
                        ch_name = ch.name
            except Exception:
                pass
        entry["channel_name"] = ch_name
        result.append(entry)

    result.sort(key=lambda x: x.get("scheduled_ts", 0))
    return jsonify({"success": True, "scheduled": result})

@app.route('/api/guild/<gid>/announcements/scheduled/<ann_id>/cancel', methods=['POST'])
def cancel_scheduled_announcement(gid, ann_id):
    gid_str = str(gid)
    queue = db.scheduled_announcements.get(gid_str, [])
    if not isinstance(queue, list):
        return jsonify({"success": False, "error": "Queue not found."}), 404

    initial_len = len(queue)
    queue = [x for x in queue if str(x.get("id")) != str(ann_id)]
    if len(queue) == initial_len:
        return jsonify({"success": False, "error": "Scheduled announcement not found."}), 404

    db.scheduled_announcements[gid_str] = queue
    db.save_data()
    return jsonify({"success": True, "message": "Scheduled announcement cancelled and removed from queue."})

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
        "color": data.get("color", "#2dd4bf"),
        "dm_on_close": data.get("dm_on_close", True),
        "dm_require_modal": data.get("dm_require_modal", True),
        "dm_title": data.get("dm_title", "🎫 Ticket Closed • {ticket}"),
        "dm_description": data.get("dm_description", "Hello {user}, your ticket **{ticket}** in **{server}** has been closed.\n\n**Closed By:** {closer}\n**Reason:** {reason}\n\nThank you for reaching out! If you have further questions, feel free to open a new ticket."),
        "dm_color": data.get("dm_color", "#2dd4bf")
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
            "color": embed_color,
            "dm_on_close": data.get("dm_on_close", True),
            "dm_require_modal": data.get("dm_require_modal", True),
            "dm_title": data.get("dm_title", "🎫 Ticket Closed • {ticket}"),
            "dm_description": data.get("dm_description", "Hello {user}, your ticket **{ticket}** in **{server}** has been closed.\n\n**Closed By:** {closer}\n**Reason:** {reason}\n\nThank you for reaching out! If you have further questions, feel free to open a new ticket."),
            "dm_color": data.get("dm_color", "#2dd4bf")
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
    channel_mode = str(data.get("channel_mode", "all")).strip().lower()
    if channel_mode not in ("all", "only", "ignore"):
        channel_mode = "all"
    channels = [str(c).strip() for c in data.get("channels", []) if str(c).strip()]

    if not response_text and not raw_emoji:
        return jsonify({"success": False, "error": "Please provide either an auto-response message, an emoji reaction, or both."}), 400

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
                rule["channel_mode"] = channel_mode
                rule["channels"] = channels
                existing = True
                break
        if not existing:
            rules.append({
                "id": rule_id,
                "type": "word",
                "trigger": trigger,
                "response": response_text,
                "emoji": raw_emoji,
                "channel_mode": channel_mode,
                "channels": channels
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
                rule["channel_mode"] = channel_mode
                rule["channels"] = channels
                existing = True
                break
        if not existing:
            rules.append({
                "id": rule_id,
                "type": "mention",
                "user_id": user_id,
                "user_name": user_name,
                "response": response_text,
                "emoji": raw_emoji,
                "channel_mode": channel_mode,
                "channels": channels
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

# ───────────────────── Welcome & Farewell Endpoints ─────────────────────

@app.route('/api/guild/<gid>/welcome', methods=['GET'])
def get_welcome(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    from cogs.welcomer import get_welcome_config
    cfg = get_welcome_config(gid_str)
    return jsonify({"success": True, "config": cfg})

@app.route('/api/guild/<gid>/welcome/toggle', methods=['POST'])
def toggle_welcome(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    data = flask_request.json or {}
    active = bool(data.get("active", False))
    if gid_str not in db.welcome or not isinstance(db.welcome[gid_str], dict):
        db.welcome[gid_str] = {}
    db.welcome[gid_str]["enabled"] = active
    db.save_data()
    return jsonify({"success": True, "enabled": active})

@app.route('/api/guild/<gid>/welcome/upload-banner', methods=['POST'])
def upload_welcome_banner(gid):
    try:
        if 'banner_file' not in flask_request.files:
            return jsonify({"success": False, "error": "No file uploaded."}), 400
        file = flask_request.files['banner_file']
        if not file or not file.filename:
            return jsonify({"success": False, "error": "Empty filename."}), 400
        
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
            return jsonify({"success": False, "error": "Unsupported file format. Please upload PNG, JPG, GIF, or WebP."}), 400
        
        token = uuid.uuid4().hex[:12]
        safe_filename = f"welcome_{gid}_{token}{ext}"
        save_path = os.path.join(WELCOME_UPLOAD_DIR, safe_filename)
        file.save(save_path)
        
        rel_url = f"/static/uploads/welcome_banners/{safe_filename}"
        return jsonify({
            "success": True,
            "url": rel_url,
            "filename": safe_filename
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/welcome/update', methods=['POST'])
def update_welcome(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    data = flask_request.json or {}
    if gid_str not in db.welcome or not isinstance(db.welcome[gid_str], dict):
        db.welcome[gid_str] = {}
    
    for key in ["enabled", "channel_id", "header_text", "title", "message", "image_url", "show_avatar", "ping_user", "is_embed", "status_color", "custom_hex"]:
        if key in data:
            val = data[key]
            if key in ("enabled", "show_avatar", "ping_user", "is_embed"):
                db.welcome[gid_str][key] = bool(val)
            elif key == "channel_id":
                db.welcome[gid_str][key] = str(val).strip() if val else None
            else:
                db.welcome[gid_str][key] = str(val).strip() if val is not None else ""
    db.save_data()
    from cogs.welcomer import get_welcome_config
    return jsonify({"success": True, "config": get_welcome_config(gid_str)})

@app.route('/api/guild/<gid>/welcome/test', methods=['POST'])
def test_welcome(gid):
    if not bot_instance:
        return jsonify({"success": False, "error": "Bot is not connected"}), 503
    gid_str = str(gid)
    from cogs.welcomer import get_welcome_config, build_welcome_embed, format_welcome_text
    cfg = get_welcome_config(gid_str)
    target_channel_id = cfg.get("channel_id")
    
    async def do_test():
        guild = bot_instance.get_guild(int(gid))
        if not guild:
            raise Exception("Guild not found")
        channel = None
        if target_channel_id:
            try:
                channel = guild.get_channel(int(target_channel_id))
            except Exception:
                pass
        if not channel:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break
        if not channel:
            raise Exception("No writable text channel found")
        sample_member = guild.owner or guild.me
        if cfg.get("is_embed", True):
            embed = build_welcome_embed(sample_member, guild, cfg, channel)
            content = None
            if cfg.get("ping_user", True):
                raw_hdr = cfg.get("header_text") or "👋 Welcome {user} !"
                content = f"👋 **[Welcome Preview]** " + format_welcome_text(raw_hdr, sample_member, guild, channel)
            discord_file = None
            raw_img = str(cfg.get("image_url", "")).strip()
            if "/static/uploads/welcome_banners/" in raw_img:
                bname = os.path.basename(raw_img)
                lpath = os.path.join(WELCOME_UPLOAD_DIR, bname)
                if os.path.exists(lpath):
                    discord_file = discord.File(lpath, filename=bname)
                    embed.set_image(url=f"attachment://{bname}")
            send_kw = {"content": content, "embed": embed} if content else {"embed": embed}
            if discord_file:
                send_kw["file"] = discord_file
            await channel.send(**send_kw)
        else:
            text = format_welcome_text(cfg.get("message"), sample_member, guild, channel)
            await channel.send(content=f"🧪 **[Test Welcome Message]**\n{text}")
        return channel.name
    
    try:
        fut = asyncio.run_coroutine_threadsafe(do_test(), bot_instance.loop)
        chan_name = fut.result(timeout=10)
        return jsonify({"success": True, "channel_name": chan_name})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/farewell/upload-banner', methods=['POST'])
def upload_farewell_banner(gid):
    try:
        if 'banner_file' not in flask_request.files:
            return jsonify({"success": False, "error": "No file uploaded."}), 400
        file = flask_request.files['banner_file']
        if not file or not file.filename:
            return jsonify({"success": False, "error": "Empty filename."}), 400
        
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
            return jsonify({"success": False, "error": "Unsupported file format. Please upload PNG, JPG, GIF, or WebP."}), 400
        
        token = uuid.uuid4().hex[:12]
        safe_filename = f"farewell_{gid}_{token}{ext}"
        save_path = os.path.join(FAREWELL_UPLOAD_DIR, safe_filename)
        file.save(save_path)
        
        rel_url = f"/static/uploads/farewell_banners/{safe_filename}"
        return jsonify({
            "success": True,
            "url": rel_url,
            "filename": safe_filename
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/auto-cache-banner', methods=['POST'])
def auto_cache_banner(gid):
    try:
        body = flask_request.json or {}
        raw_url = str(body.get('url', '')).strip()
        category = str(body.get('category', 'welcome')).strip().lower()
        if not raw_url or not raw_url.startswith(('http://', 'https://')):
            return jsonify({"success": False, "error": "Invalid URL"}), 400
        
        target_dir = WELCOME_UPLOAD_DIR
        url_prefix = "welcome_banners"
        if category == 'farewell':
            target_dir = FAREWELL_UPLOAD_DIR
            url_prefix = "farewell_banners"
        elif category == 'giveaway':
            target_dir = BANNER_UPLOAD_DIR
            url_prefix = "giveaway_banners"
            
        import urllib.request
        req = urllib.request.Request(raw_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = resp.read()
            ct = resp.headers.get('content-type', '').lower()
            ext = '.gif' if 'gif' in ct or '.gif' in raw_url.lower() else ('.png' if 'png' in ct else ('.webp' if 'webp' in ct else '.jpg'))
            token = uuid.uuid4().hex[:12]
            safe_filename = f"{category}_{gid}_{token}{ext}"
            save_path = os.path.join(target_dir, safe_filename)
            with open(save_path, 'wb') as out_f:
                out_f.write(data)
            rel_url = f"/static/uploads/{url_prefix}/{safe_filename}"
            return jsonify({"success": True, "url": rel_url, "filename": safe_filename})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route('/api/guild/<gid>/farewell', methods=['GET'])
def get_farewell(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    from cogs.welcomer import get_farewell_config
    cfg = get_farewell_config(gid_str)
    return jsonify({"success": True, "config": cfg})

@app.route('/api/guild/<gid>/farewell/toggle', methods=['POST'])
def toggle_farewell(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    data = flask_request.json or {}
    active = bool(data.get("active", False))
    if gid_str not in db.farewell or not isinstance(db.farewell[gid_str], dict):
        db.farewell[gid_str] = {}
    db.farewell[gid_str]["enabled"] = active
    db.save_data()
    return jsonify({"success": True, "enabled": active})

@app.route('/api/guild/<gid>/farewell/update', methods=['POST'])
def update_farewell(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    data = flask_request.json or {}
    if gid_str not in db.farewell or not isinstance(db.farewell[gid_str], dict):
        db.farewell[gid_str] = {}
    for key in ["enabled", "channel_id", "header_text", "title", "message", "image_url", "show_avatar", "identifier_mode", "is_embed", "status_color", "custom_hex"]:
        if key in data:
            val = data[key]
            if key in ("enabled", "show_avatar", "is_embed"):
                db.farewell[gid_str][key] = bool(val)
            elif key == "channel_id":
                db.farewell[gid_str][key] = str(val).strip() if val else None
            else:
                db.farewell[gid_str][key] = str(val).strip() if val is not None else ""
    db.save_data()
    from cogs.welcomer import get_farewell_config
    return jsonify({"success": True, "config": get_farewell_config(gid_str)})

@app.route('/api/guild/<gid>/farewell/test', methods=['POST'])
def test_farewell(gid):
    if not bot_instance:
        return jsonify({"success": False, "error": "Bot is not connected"}), 503
    gid_str = str(gid)
    from cogs.welcomer import get_farewell_config, build_farewell_embed, format_farewell_text
    cfg = get_farewell_config(gid_str)
    target_channel_id = cfg.get("channel_id")
    
    async def do_test():
        guild = bot_instance.get_guild(int(gid))
        if not guild:
            raise Exception("Guild not found")
        channel = None
        if target_channel_id:
            try:
                channel = guild.get_channel(int(target_channel_id))
            except Exception:
                pass
        if not channel:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break
        if not channel:
            raise Exception("No writable text channel found")
        sample_member = guild.owner or guild.me
        if cfg.get("is_embed", True):
            embed = build_farewell_embed(sample_member, guild, cfg, channel)
            discord_file = None
            raw_img = str(cfg.get("image_url", "")).strip()
            target_dir = FAREWELL_UPLOAD_DIR if "/static/uploads/farewell_banners/" in raw_img else WELCOME_UPLOAD_DIR
            target_url_part = "farewell_banners" if "/static/uploads/farewell_banners/" in raw_img else "welcome_banners"
            if f"/static/uploads/{target_url_part}/" in raw_img:
                bname = os.path.basename(raw_img)
                lpath = os.path.join(target_dir, bname)
                if os.path.exists(lpath):
                    discord_file = discord.File(lpath, filename=bname)
                    embed.set_image(url=f"attachment://{bname}")
            raw_hdr = str(cfg.get("header_text", "")).strip()
            content = format_farewell_text(raw_hdr, sample_member, guild, channel, cfg.get("identifier_mode", "name")) if raw_hdr else "🚪 **[Farewell Preview]**"
            send_kw = {"content": content, "embed": embed}
            if discord_file:
                send_kw["file"] = discord_file
            await channel.send(**send_kw)
        else:
            text = format_farewell_text(cfg.get("message"), sample_member, guild, channel, cfg.get("identifier_mode", "name"))
            await channel.send(content=f"🧪 **[Test Farewell Message]**\n{text}")
        return channel.name
    
    try:
        fut = asyncio.run_coroutine_threadsafe(do_test(), bot_instance.loop)
        chan_name = fut.result(timeout=10)
        return jsonify({"success": True, "channel_name": chan_name})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/first_welcome', methods=['GET'])
def get_first_welcome(gid):
    gid_str = str(gid)
    gid_int = int(gid) if str(gid).isdigit() else None
    try:
        db.reload()
    except Exception:
        pass
    cfg = db.first_welcome.get(gid_str) or db.first_welcome.get(gid_int) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return jsonify({
        "success": True,
        "config": {
            "enabled": bool(cfg.get("enabled", False)),
            "channel_id": cfg.get("channel_id"),
            "title": cfg.get("title", "WELCOME TO {server}!"),
            "message": cfg.get("message", "Hey {user}, welcome to **{server}**! 🎉\n\n> We're thrilled to have you here with us.\n> Feel free to introduce yourself and say hello!\n\n📌 Review {rules} to get started and enjoy your stay."),
            "show_avatar": cfg.get("show_avatar", True),
            "status_color": cfg.get("status_color", "success"),
            "custom_hex": cfg.get("custom_hex", "#10b981")
        }
    })

@app.route('/api/guild/<gid>/first_welcome/toggle', methods=['POST'])
def toggle_first_welcome(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    data = flask_request.json or {}
    active = bool(data.get("active", False))
    
    if gid_str not in db.first_welcome or not isinstance(db.first_welcome[gid_str], dict):
        db.first_welcome[gid_str] = {}
        
    db.first_welcome[gid_str]["enabled"] = active
    db.save_data()
    return jsonify({"success": True, "enabled": active})

@app.route('/api/guild/<gid>/first_welcome/update', methods=['POST'])
def update_first_welcome(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    data = flask_request.json or {}
    
    if gid_str not in db.first_welcome or not isinstance(db.first_welcome[gid_str], dict):
        db.first_welcome[gid_str] = {}

    if "enabled" in data:
        db.first_welcome[gid_str]["enabled"] = bool(data.get("enabled", False))
    if "channel_id" in data:
        db.first_welcome[gid_str]["channel_id"] = str(data.get("channel_id")).strip() if data.get("channel_id") else None
    if "title" in data:
        db.first_welcome[gid_str]["title"] = str(data.get("title", "WELCOME TO {server}!")).strip()
    if "message" in data:
        db.first_welcome[gid_str]["message"] = str(data.get("message", "Hey {user}, welcome to **{server}**! 🎉\n\n> We're thrilled to have you here with us.\n> Feel free to introduce yourself and say hello!\n\n📌 Review {rules} to get started and enjoy your stay.")).strip()
    if "show_avatar" in data:
        db.first_welcome[gid_str]["show_avatar"] = bool(data.get("show_avatar", True))
    if "status_color" in data:
        db.first_welcome[gid_str]["status_color"] = str(data.get("status_color", "success"))
    if "custom_hex" in data:
        db.first_welcome[gid_str]["custom_hex"] = str(data.get("custom_hex", "#10b981"))
    if "image_url" in data:
        db.first_welcome[gid_str]["image_url"] = str(data.get("image_url", "")).strip()

    db.save_data()
    return jsonify({"success": True, "config": db.first_welcome[gid_str]})

@app.route('/api/guild/<gid>/first_welcome/reset-history', methods=['POST'])
def reset_first_welcome_history(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    db.first_chat_welcomes[gid_str] = []
    db.first_welcome_allow_test[gid_str] = ["*"]
    db.save_data()
    return jsonify({"success": True, "message": "First chat welcome history reset. The next message sent in chat will trigger the greeting."})

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

# ───────────────────── API: Live LLM Usage & Rate Limit Telemetry ─────────────────────

@app.route('/api/llm/telemetry', methods=['GET'])
def get_llm_telemetry():
    from cogs.ai_chat import llm_telemetry
    return jsonify({"success": True, "telemetry": llm_telemetry})

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


@app.route('/api/guild/<gid>/special_invites/update_nickname', methods=['POST'])
def update_special_invite_nickname(gid):
    body = flask_request.json or {}
    user_id = str(body.get("user_id", "")).strip()
    nickname = str(body.get("nickname", "")).strip()
    if not user_id:
        return jsonify({"success": False, "error": "User ID is required."})

    try:
        db.reload()
    except Exception:
        pass

    if hasattr(db, "special_invites") and user_id in db.special_invites:
        try:
            from cogs.ai_chat import clean_vip_nickname
            clean_name = clean_vip_nickname(nickname)
        except Exception:
            clean_name = nickname.title()

        db.special_invites[user_id]["custom_nickname"] = clean_name
        db.save_data()
        return jsonify({"success": True, "nickname": clean_name})
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



# ───────────────────── Giveaways Studio & Hub ─────────────────────

BANNER_UPLOAD_DIR = os.path.join(app.root_path, "static", "uploads", "giveaway_banners")
os.makedirs(BANNER_UPLOAD_DIR, exist_ok=True)
WELCOME_UPLOAD_DIR = os.path.join(app.root_path, "static", "uploads", "welcome_banners")
os.makedirs(WELCOME_UPLOAD_DIR, exist_ok=True)
FAREWELL_UPLOAD_DIR = os.path.join(app.root_path, "static", "uploads", "farewell_banners")
os.makedirs(FAREWELL_UPLOAD_DIR, exist_ok=True)
BIRTHDAY_BANNER_DIR = os.path.join(app.root_path, "static", "uploads", "birthday_banners")
os.makedirs(BIRTHDAY_BANNER_DIR, exist_ok=True)
APPLICATION_BANNER_DIR = os.path.join(app.root_path, "static", "uploads", "application_banners")
os.makedirs(APPLICATION_BANNER_DIR, exist_ok=True)
RANK_BG_DIR = os.path.join(app.root_path, "static", "uploads", "rank_backgrounds")
os.makedirs(RANK_BG_DIR, exist_ok=True)
INVITE_BANNER_DIR = os.path.join(app.root_path, "static", "uploads", "invite_banners")
os.makedirs(INVITE_BANNER_DIR, exist_ok=True)

def validate_image_url(url):
    if not url:
        return None
    url = str(url).strip()
    if not url:
        return None
    if url.startswith("attachment://"):
        return url
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith(("http://", "https://")):
        if "." in url and not url.startswith(("/", "\\")):
            url = "https://" + url
        else:
            return None
    try:
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.netloc and "." in parsed.netloc:
            return url
    except Exception:
        pass
    return None

def resolve_safe_emoji(bot, emoji_str, fallback="🎁"):
    if not emoji_str:
        return fallback
    emoji_str = str(emoji_str).strip()
    if not emoji_str:
        return fallback
    if emoji_str.startswith("<") and emoji_str.endswith(">"):
        match = re.search(r":(\d+)>$", emoji_str)
        if match:
            eid = int(match.group(1))
            if bot and bot.get_emoji(eid):
                return emoji_str
            return fallback
    return emoji_str

def parse_hex_color(hex_str, default=0x5865F2):
    if not hex_str:
        return discord.Color(default)
    clean = str(hex_str).strip().lstrip("#")
    try:
        if len(clean) == 6:
            return discord.Color(int(clean, 16))
        elif len(clean) == 3:
            expanded = "".join(c * 2 for c in clean)
            return discord.Color(int(expanded, 16))
    except Exception:
        pass
    return discord.Color(default)

@app.route('/api/proxy-image', methods=['GET'])
def proxy_external_image():
    raw_url = flask_request.args.get('url', '').strip()
    if not raw_url or not raw_url.startswith(('http://', 'https://')):
        return jsonify({"error": "Invalid image URL"}), 400
    try:
        import urllib.request, re
        from flask import Response
        # Clean outer quotes if any
        if (raw_url.startswith('"') and raw_url.endswith('"')) or (raw_url.startswith("'") and raw_url.endswith("'")):
            raw_url = raw_url[1:-1].strip()

        target_url = raw_url
        # Resolve Tenor view page URL if user copied web link
        if "tenor.com/view/" in target_url:
            try:
                t_req = urllib.request.Request(target_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(t_req, timeout=5) as t_resp:
                    html_c = t_resp.read().decode('utf-8', errors='ignore')
                    og_m = re.search(r'<meta property="og:image"\s+content="([^"]+)"', html_c)
                    if og_m:
                        target_url = og_m.group(1)
            except Exception:
                pass
        elif "giphy.com/gifs/" in target_url and not target_url.endswith(('.gif', '.webp', '.png', '.jpg')):
            try:
                g_req = urllib.request.Request(target_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(g_req, timeout=5) as g_resp:
                    html_c = g_resp.read().decode('utf-8', errors='ignore')
                    og_m = re.search(r'<meta property="og:image"\s+content="([^"]+)"', html_c)
                    if og_m:
                        target_url = og_m.group(1)
            except Exception:
                pass

        req = urllib.request.Request(target_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            content_type = resp.headers.get('content-type', 'image/png')
            data = resp.read()
            return Response(data, mimetype=content_type, headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*"
            })
    except Exception as e:
        return jsonify({"error": f"Failed to proxy image: {str(e)}"}), 502

@app.route('/api/guild/<gid>/giveaways/upload-banner', methods=['POST'])
def upload_giveaway_banner(gid):
    try:
        if 'banner_file' not in flask_request.files:
            return jsonify({"success": False, "error": "No file uploaded."}), 400
        file = flask_request.files['banner_file']
        if not file or not file.filename:
            return jsonify({"success": False, "error": "Empty filename."}), 400
        
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
            return jsonify({"success": False, "error": "Unsupported file format. Please upload PNG, JPG, GIF, or WebP."}), 400
        
        token = uuid.uuid4().hex[:12]
        safe_filename = f"gw_{gid}_{token}{ext}"
        save_path = os.path.join(BANNER_UPLOAD_DIR, safe_filename)
        file.save(save_path)
        
        rel_url = f"/static/uploads/giveaway_banners/{safe_filename}"
        return jsonify({
            "success": True,
            "url": rel_url,
            "filename": safe_filename
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/guild/<gid>/giveaways', methods=['GET'])
def get_guild_giveaways(gid):
    try:
        db.reload()
    except Exception:
        pass
    gid_str = str(gid)
    if not isinstance(getattr(db, "giveaways_config", None), dict):
        db.giveaways_config = {}
    cfg = db.giveaways_config.get(gid_str, {})
    if not isinstance(cfg, dict):
        cfg = {}
    all_gw = getattr(db, "giveaways", {}) or {}
    
    active = []
    ended = []
    
    import time
    now = time.time()
    seen_msg_ids = set()
    for key, item in list(all_gw.items()):
        if not isinstance(item, dict) or key.startswith("req_"):
            continue
        if str(item.get("guild_id")) == gid_str:
            msg_id_val = str(item.get("message_id") or key.split("_")[-1])
            # Guard against triplication: if this message_id was already processed, skip duplicate alias rows
            if msg_id_val in seen_msg_ids:
                # If this is a redundant temp_key or bare msg.id, clean it up from db if canonical real_key exists
                real_k = f"{gid_str}_{msg_id_val}"
                if key != real_k and real_k in all_gw:
                    try:
                        all_gw.pop(key, None)
                    except Exception:
                        pass
                continue
            seen_msg_ids.add(msg_id_val)

            gw_copy = dict(item)
            gw_copy["key"] = f"{gid_str}_{msg_id_val}"
            gw_copy["id"] = msg_id_val
            gw_copy["message_id"] = msg_id_val
            gw_copy["channel_id"] = str(item.get("channel_id") or "")
            gw_copy["guild_id"] = str(item.get("guild_id") or "")
            gw_copy["host_id"] = str(item.get("host_id") or "")
            gw_copy["sponsor_id"] = str(item.get("sponsor_id") or "")
            gw_copy["entries"] = [str(e) for e in item.get("entries", [])]
            resolved_winners = []
            guild_obj = bot_instance.get_guild(int(gid)) if bot_instance and str(gid).isdigit() else None
            for w in item.get("winners", []):
                w_str = str(w)
                w_obj = {"id": w_str, "username": f"User {w_str[-4:]}", "display_name": f"User {w_str[-4:]}"}
                if guild_obj:
                    m = guild_obj.get_member(int(w)) if w_str.isdigit() else None
                    if m:
                        w_obj["username"] = m.name
                        w_obj["display_name"] = m.display_name
                    elif bot_instance:
                        u = bot_instance.get_user(int(w)) if w_str.isdigit() else None
                        if u:
                            w_obj["username"] = u.name
                            w_obj["display_name"] = getattr(u, "global_name", None) or u.name
                resolved_winners.append(w_obj)
            gw_copy["winners"] = resolved_winners
            if guild_obj and gw_copy.get("sponsor_id"):
                s_id = gw_copy.get("sponsor_id")
                sm = guild_obj.get_member(int(s_id)) if str(s_id).isdigit() else None
                if sm:
                    gw_copy["host_name"] = sm.display_name or sm.name
            gw_copy["entries_count"] = len(item.get("entries", []))
            gw_copy["time_left_seconds"] = max(0, int(item.get("end_time", now) - now))
            if item.get("status") == "active":
                active.append(gw_copy)
            else:
                ended.append(gw_copy)
                
    active.sort(key=lambda x: x.get("end_time", 0))
    ended.sort(key=lambda x: x.get("ended_at", x.get("created_at", 0)), reverse=True)
    
    cfg_out = dict(cfg)
    for ch_key in ["giveaway_channel", "approval_channel", "log_channel"]:
        if cfg_out.get(ch_key):
            cfg_out[ch_key] = str(cfg_out[ch_key])
            
    return jsonify({
        "success": True,
        "config": cfg_out,
        "active": active,
        "ended": ended[:30]
    })

@app.route('/api/guild/<gid>/giveaways/config', methods=['POST'])
def save_guild_giveaway_config(gid):
    body = flask_request.json or {}
    gid_str = str(gid)
    
    if not isinstance(getattr(db, "giveaways_config", None), dict):
        db.giveaways_config = {}
    cfg = db.giveaways_config.get(gid_str, {})
    if not isinstance(cfg, dict):
        cfg = {}
    if "giveaway_channel" in body:
        val = body.get("giveaway_channel")
        cfg["giveaway_channel"] = str(val).strip() if val and str(val).strip() else None
    if "approval_channel" in body:
        val = body.get("approval_channel")
        cfg["approval_channel"] = str(val).strip() if val and str(val).strip() else None
    if "log_channel" in body:
        val = body.get("log_channel")
        cfg["log_channel"] = str(val).strip() if val and str(val).strip() else None
    if "embed_color" in body:
        cfg["embed_color"] = str(body.get("embed_color", "#5865F2")).strip() or "#5865F2" 
    if "entry_method" in body:
        val = str(body.get("entry_method", "button")).strip().lower()
        cfg["entry_method"] = "reaction" if val == "reaction" else "button"

    # Custom styling emojis
    for emoji_key in ["emoji_header", "emoji_prize", "emoji_participants", "emoji_participants_response", "emoji_host", "emoji_winners", "emoji_entries", "emoji_ends", "emoji_ended", "emoji_bullet"]:
        if emoji_key in body:
            val = str(body.get(emoji_key, "")).strip()
            if val:
                cfg[emoji_key] = val

    if "default_banner" in body:
        val = str(body.get("default_banner", "")).strip()
        cfg["default_banner"] = val or None

    # Announcement, Log, and Proposal formatting templates
    for text_key in [
        "winner_title", "winner_message", "winner_ping", "reroll_title", "reroll_message", "reroll_ping",
        "participants_header", "participants_empty", "no_entries_title", "no_entries_message",
        "log_created_title", "log_created_message", "log_concluded_title", "log_concluded_message",
        "log_reroll_title", "log_reroll_message", "req_submitted_message", "req_approval_title",
        "req_approval_message", "req_approved_message", "req_rejected_message"
    ]:
        if text_key in body:
            val = str(body.get(text_key, "")).strip()
            if val:
                cfg[text_key] = val

    db.giveaways_config[gid_str] = cfg
    db.save_data()
    return jsonify({"success": True, "config": cfg})

@app.route('/api/guild/<gid>/giveaways/autohub', methods=['POST'])
def autohub_guild_giveaways(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."}), 503

    gid_int = int(gid)
    async def do_autohub():
        guild = bot_instance.get_guild(gid_int)
        if not guild:
            raise Exception("Guild not found or Friday is not connected to it.")

        # Find or create Category "🎉 GIVEAWAYS"
        category = discord.utils.get(guild.categories, name="🎉 GIVEAWAYS")
        if not category:
            category = await guild.create_category(name="🎉 GIVEAWAYS", reason="Friday Dashboard Giveaway Setup")

        everyone_role = guild.default_role
        bot_member = guild.me

        public_overwrites = {
            everyone_role: discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                read_message_history=True,
                send_messages=False,
                add_reactions=False
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                manage_messages=True
            )
        }
        private_overwrites = {
            everyone_role: discord.PermissionOverwrite(view_channel=False),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                embed_links=True,
                manage_messages=True
            )
        }

        # Check existing channels in category
        gw_ch = discord.utils.get(category.text_channels, name="giveaways")
        if not gw_ch:
            gw_ch = await guild.create_text_channel(
                name="giveaways",
                category=category,
                overwrites=public_overwrites,
                topic="Official server giveaways hosted by Friday! 🎁",
                reason="Friday Dashboard Giveaway Setup"
            )

        app_ch = discord.utils.get(category.text_channels, name="giveaway-approvals")
        if not app_ch:
            app_ch = await guild.create_text_channel(
                name="giveaway-approvals",
                category=category,
                overwrites=private_overwrites,
                topic="Private staff approval queue for member-submitted giveaways 🛡️",
                reason="Friday Dashboard Giveaway Setup"
            )

        log_ch = discord.utils.get(category.text_channels, name="giveaway-logs")
        if not log_ch:
            log_ch = await guild.create_text_channel(
                name="giveaway-logs",
                category=category,
                overwrites=private_overwrites,
                topic="Audit log of giveaway winners, rerolls, and endings 📜",
                reason="Friday Dashboard Giveaway Setup"
            )

        cfg = db.giveaways_config.get(str(gid), {})
        cfg["giveaway_channel"] = str(gw_ch.id)
        cfg["approval_channel"] = str(app_ch.id)
        cfg["log_channel"] = str(log_ch.id)
        db.giveaways_config[str(gid)] = cfg
        db.save_data()
        return {
            "giveaway_channel": gw_ch.id,
            "approval_channel": app_ch.id,
            "log_channel": log_ch.id
        }

    try:
        fut = asyncio.run_coroutine_threadsafe(do_autohub(), bot_instance.loop)
        created = fut.result(timeout=15)
        return jsonify({"success": True, "created": created})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/giveaways/<gw_id>/entries', methods=['GET'])
def get_giveaway_entries(gid, gw_id):
    clean_id = str(gw_id).strip()
    if "_" in clean_id:
        clean_id = clean_id.split("_")[-1]
    key = f"{gid}_{clean_id}"
    gw = db.giveaways.get(key)
    if not gw:
        gw = db.giveaways.get(str(gw_id))
    if not gw:
        return jsonify({"success": False, "error": "Giveaway not found."}), 404

    entry_ids = gw.get("entries", [])
    participants = []
    
    for uid in entry_ids:
        info = fetch_user_info(uid)
        participants.append({
            "id": str(uid),
            "username": info.get("username", f"User {uid}"),
            "display_name": info.get("display_name", f"User {uid}"),
            "avatar": info.get("avatar_url") or "https://cdn.discordapp.com/embed/avatars/0.png"
        })
        
    return jsonify({
        "success": True,
        "prize": gw.get("prize", "Giveaway"),
        "total": len(entry_ids),
        "participants": participants
    })

async def resolve_giveaway_log_channel(bot, guild, cfg: dict = None):
    """Resolves the Discord log channel for giveaways with safe integer conversion, cache lookup, fetch, and auto-discovery."""
    if not guild:
        return None
    if cfg is None:
        cfg = getattr(db, "giveaways_config", {}).get(str(guild.id), {}) if hasattr(db, "giveaways_config") else {}
    log_ch_id = cfg.get("log_channel") if isinstance(cfg, dict) else None
    ch = None
    if log_ch_id:
        try:
            cid = int(str(log_ch_id).strip())
            ch = guild.get_channel(cid)
            if not ch and bot:
                ch = bot.get_channel(cid)
            if not ch and bot:
                ch = await bot.fetch_channel(cid)
        except Exception:
            ch = None
    if not ch and hasattr(guild, "text_channels"):
        for name in ("giveaway-logs", "giveaways-log", "gw-logs", "giveaway-log", "gw_logs", "giveaways_log"):
            ch = discord.utils.get(guild.text_channels, name=name)
            if ch:
                break
    return ch

@app.route('/api/guild/<gid>/giveaways/create', methods=['POST'])
def create_guild_giveaway(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."}), 503

    body = flask_request.json or {}
    prize = str(body.get("prize", "")).strip()
    duration_str = str(body.get("duration", "1h")).strip()
    winners = int(body.get("winners", 1))
    description = str(body.get("description", "")).strip()
    channel_id = body.get("channel_id")

    if not prize:
        return jsonify({"success": False, "error": "Prize title is required."})

    from cogs.giveaways import parse_duration, GiveawayEnterView
    from datetime import datetime, timezone
    import time, uuid

    duration_sec = parse_duration(duration_str)
    if not duration_sec or duration_sec < 10:
        return jsonify({"success": False, "error": "Invalid duration. Minimum is 10s (e.g. 10m, 1h, 2d)."})

    winners_count = max(1, min(winners, 25))
    gid_int = int(gid)

    async def do_launch():
        guild = bot_instance.get_guild(gid_int)
        if not guild:
            raise Exception("Guild not found.")

        target_ch_id = channel_id or db.giveaways_config.get(str(gid), {}).get("giveaway_channel")
        if not target_ch_id:
            raise Exception("No giveaway channel configured. Please set one or run Auto-Provision.")

        channel = guild.get_channel(int(target_ch_id))
        if not channel:
            raise Exception("Configured giveaway text channel was not found on Discord.")

        now = time.time()
        end_time = now + duration_sec
        end_timestamp = int(end_time)

        cfg = db.giveaways_config.get(str(gid), {})
        raw_img_val = body.get("image_url")
        raw_image = str(raw_img_val).strip() if raw_img_val is not None else ""
        if not raw_image or raw_image.lower() in ("none", "null", "undefined"):
            raw_image = str(cfg.get("default_banner") or "").strip()

        embed_color_hex = body.get("embed_color") or cfg.get("embed_color") or "#5865F2"
        embed_color = parse_hex_color(embed_color_hex, default=0x5865F2)

        emoji_header = resolve_safe_emoji(bot_instance, body.get("emoji_header") or cfg.get("emoji_header"), fallback="🎉")
        emoji_prize = resolve_safe_emoji(bot_instance, body.get("emoji_prize") or cfg.get("emoji_prize"), fallback="🎁")
        emoji_host = resolve_safe_emoji(bot_instance, body.get("emoji_host") or cfg.get("emoji_host"), fallback="👑")
        emoji_winners = resolve_safe_emoji(bot_instance, body.get("emoji_winners") or cfg.get("emoji_winners"), fallback="🏆")
        emoji_entries = resolve_safe_emoji(bot_instance, body.get("emoji_entries") or cfg.get("emoji_entries"), fallback="🎟️")
        emoji_ends = resolve_safe_emoji(bot_instance, body.get("emoji_ends") or cfg.get("emoji_ends"), fallback="⏳")
        emoji_ended = resolve_safe_emoji(bot_instance, body.get("emoji_ended") or cfg.get("emoji_ended"), fallback="🔒")
        emoji_bullet = resolve_safe_emoji(bot_instance, body.get("emoji_bullet") or cfg.get("emoji_bullet"), fallback="•")

        host_id = body.get("host_id")
        host_name = str(body.get("host_name") or "").strip()
        host_member = None
        if host_id and str(host_id).isdigit() and str(host_id) != "0":
            host_member = guild.get_member(int(host_id))
            if not host_member:
                try:
                    host_member = await guild.fetch_member(int(host_id))
                except Exception:
                    try:
                        host_member = await bot_instance.fetch_user(int(host_id))
                    except Exception:
                        host_member = None

        if not host_member and host_name and host_name != "Server Staff (Default)":
            clean_search = host_name.lstrip("@").lower()
            for m in guild.members:
                if m.name.lower() == clean_search or (m.global_name and m.global_name.lower() == clean_search) or m.display_name.lower() == clean_search:
                    host_member = m
                    break

        if host_member:
            sponsor_id = str(host_member.id)
            host_mention = host_member.mention
            saved_host_name = host_member.display_name or host_member.name
        elif host_name and host_name != "Server Staff (Default)":
            sponsor_id = "0"
            host_mention = f"@{host_name.lstrip('@')}"
            saved_host_name = host_name.lstrip('@')
        else:
            sponsor_id = "0"
            host_mention = "Server Staff"
            saved_host_name = "Server Staff"

        entry_method = str(body.get("entry_method") or cfg.get("entry_method") or "button").lower()
        if entry_method != "reaction":
            entry_method = "button"
        emoji_participants = resolve_safe_emoji(bot_instance, cfg.get("emoji_participants"), fallback="👥")

        default_instr = "Click the button below to participate!" if entry_method != "reaction" else f"React with {emoji_prize} to participate!"
        desc_body = (
            f"{emoji_bullet} **Winners:** {winners_count}\n"
            f"{emoji_bullet} **Ends In:** <t:{end_timestamp}:R> (<t:{end_timestamp}:f>)\n"
            f"{emoji_bullet} **Hosted By:** {host_mention}\n\n"
            f"{emoji_bullet} {description or default_instr}"
        )

        embed = discord.Embed(
            title=f"{emoji_prize} {prize} {emoji_prize}",
            description=desc_body,
            color=embed_color,
            timestamp=datetime.fromtimestamp(end_time, timezone.utc)
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        discord_file = None
        final_image_url = None

        if raw_image:
            # Check if this is an uploaded local banner file
            if "/static/uploads/giveaway_banners/" in raw_image:
                banner_name = os.path.basename(raw_image)
                local_path = os.path.join(BANNER_UPLOAD_DIR, banner_name)
                if os.path.exists(local_path):
                    # To permanently prevent Discord from displaying loose/duplicate attachment images above the embed card,
                    # upload the asset to log_channel to obtain a permanent Discord CDN URL so the public card has ZERO loose attachments.
                    cdn_url = None
                    try:
                        cfg_gw = db.giveaways_config.get(str(gid), {})
                        log_ch = await resolve_giveaway_log_channel(bot_instance, guild, cfg_gw)
                        if log_ch:
                            asset_msg = await log_ch.send(
                                content=f"🖼️ **Giveaway Asset Stored for `{prize}`**",
                                file=discord.File(local_path, filename=banner_name)
                            )
                            if asset_msg.attachments:
                                cdn_url = asset_msg.attachments[0].url
                    except Exception as e:
                        print(f"[Giveaway Asset Upload Notice] {e}")

                    if cdn_url:
                        embed.set_image(url=cdn_url)
                        final_image_url = cdn_url
                    else:
                        discord_file = discord.File(local_path, filename=banner_name)
                        embed.set_image(url=f"attachment://{banner_name}")
                        final_image_url = raw_image
            else:
                validated = validate_image_url(raw_image)
                if validated:
                    embed.set_image(url=validated)
                    final_image_url = validated

        ends_date_str = datetime.fromtimestamp(end_time, timezone.utc).strftime("%m/%d/%y")
        embed.set_footer(text=f"Ends • {ends_date_str}", icon_url=guild.icon.url if guild.icon else None)

        temp_id = str(uuid.uuid4())[:8]
        temp_key = f"{gid}_{temp_id}"
        real_view = GiveawayEnterView(giveaway_key=temp_key, entry_count=0, emoji=emoji_prize, emoji_participants=emoji_participants) if entry_method == "button" else None

        send_kwargs = {"content": f"{emoji_header} **New Giveaway** {emoji_header}", "embed": embed}
        if real_view:
            send_kwargs["view"] = real_view
        if discord_file:
            send_kwargs["file"] = discord_file

        msg = await channel.send(**send_kwargs)

        # Only add reaction if entry_method is 'reaction'
        if entry_method == "reaction":
            try:
                if emoji_prize.startswith("<") and emoji_prize.endswith(">"):
                    m = re.search(r":(\d+)>$", emoji_prize)
                    if m:
                        rx = bot_instance.get_emoji(int(m.group(1)))
                        if rx:
                            await msg.add_reaction(rx)
                        else:
                            await msg.add_reaction("🎁")
                    else:
                        await msg.add_reaction("🎁")
                else:
                    await msg.add_reaction(emoji_prize)
            except Exception:
                try:
                    await msg.add_reaction("🎁")
                except Exception:
                    pass

        # If uploaded as attachment, store permanent Discord CDN attachment URL
        if discord_file and msg.attachments:
            final_image_url = msg.attachments[0].url

        real_key = f"{gid}_{msg.id}"

        # Re-edit the message to bind the persistent view to real_key and fix CDN image URL (prevents attachment detachment)
        if entry_method == "button":
            try:
                real_view = GiveawayEnterView(giveaway_key=real_key, entry_count=0, emoji=emoji_prize, emoji_participants=emoji_participants)
                if final_image_url:
                    embed.set_image(url=final_image_url)
                await msg.edit(embed=embed, view=real_view)
            except Exception:
                pass

        gw_data = {
            "message_id": msg.id,
            "giveaway_key": real_key,
            "key": real_key,
            "channel_id": channel.id,
            "guild_id": gid_int,
            "prize": prize,
            "host_id": sponsor_id,
            "sponsor_id": sponsor_id,
            "host_name": saved_host_name,
            "entry_method": entry_method,
            "winners_count": winners_count,
            "created_at": now,
            "end_time": end_time,
            "status": "active",
            "entries": [],
            "winners": [],
            "description": description,
            "image_url": final_image_url or "",
            "embed_color": embed_color_hex,
            "header_emoji": emoji_header
        }
        # ONLY store canonical real_key! Pop temporary uuid key and bare msg.id to eliminate duplicate rows in UI
        db.giveaways.pop(temp_key, None)
        db.giveaways.pop(str(msg.id), None)
        db.giveaways[real_key] = gw_data
        db.save_data()

        # Log event in #giveaway-logs channel
        try:
            cfg = db.giveaways_config.get(str(gid), {})
            log_channel = await resolve_giveaway_log_channel(bot_instance, guild, cfg)
            if log_channel:
                default_log_title = "📜 Giveaway Created (Dashboard)"
                default_log_desc = (
                    f"**Prize:** {prize}\n"
                    f"**Channel:** {channel.mention}\n"
                    f"**Sponsored by:** {host_display}\n"
                    f"**Winners Count:** {winners_count}\n"
                    f"**Duration:** {duration_str}\n"
                    f"**Entry Method:** {entry_method.title()}\n"
                    f"[Jump to Giveaway]({msg.jump_url})"
                )
                raw_log_title = cfg.get("log_created_title") or default_log_title
                raw_log_desc = cfg.get("log_created_message") or default_log_desc
                formatted_log_desc = (
                    raw_log_desc
                    .replace("{prize}", prize)
                    .replace("{channel}", channel.mention)
                    .replace("{host}", host_display)
                    .replace("{winners}", str(winners_count))
                    .replace("{duration}", duration_str)
                    .replace("{entry_method}", entry_method.title())
                    .replace("{server}", guild.name)
                    .replace("{link}", msg.jump_url)
                )
                log_embed = discord.Embed(
                    title=raw_log_title.replace("{prize}", prize),
                    description=formatted_log_desc,
                    color=discord.Color.blue(),
                    timestamp=datetime.now(timezone.utc)
                )
                if final_image_url and final_image_url.startswith("http"):
                    log_embed.set_thumbnail(url=final_image_url)
                if guild.icon:
                    log_embed.set_footer(text="Friday Giveaway Engine • Audit Log", icon_url=guild.icon.url)
                await log_channel.send(embed=log_embed)
        except Exception as e:
            print(f"[Giveaways] Error logging giveaway creation to Discord channel: {e}")

        return {
            "message_id": str(msg.id),
            "jump_url": msg.jump_url,
            "channel_name": channel.name
        }

    try:
        fut = asyncio.run_coroutine_threadsafe(do_launch(), bot_instance.loop)
        res = fut.result(timeout=15)
        return jsonify({"success": True, "result": res})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/giveaways/end', methods=['POST'])
def end_guild_giveaway(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."}), 503

    body = flask_request.json or {}
    raw_id = str(body.get("message_id") or body.get("id") or body.get("key") or "").strip()
    if not raw_id or raw_id == "undefined":
        return jsonify({"success": False, "error": "Valid Giveaway Message ID required."})

    msg_id = raw_id.split("_")[-1]
    key = f"{gid}_{msg_id}"
    gw = db.giveaways.get(key) or db.giveaways.get(raw_id)
    if not gw or gw.get("status") != "active":
        return jsonify({"success": False, "error": "Active giveaway not found."})

    cog = bot_instance.get_cog("Giveaways")
    if not cog:
        return jsonify({"success": False, "error": "Giveaways cog not loaded."})

    async def do_end():
        await cog.conclude_giveaway(key, gw)

    try:
        fut = asyncio.run_coroutine_threadsafe(do_end(), bot_instance.loop)
        fut.result(timeout=10)
        return jsonify({"success": True, "message": f"Giveaway for '{gw.get('prize')}' ended early!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/giveaways/reroll', methods=['POST'])
def reroll_guild_giveaway(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."}), 503

    body = flask_request.json or {}
    raw_id = str(body.get("message_id") or body.get("id") or body.get("key") or "").strip()
    if not raw_id or raw_id == "undefined":
        return jsonify({"success": False, "error": "Valid Giveaway Message ID required."})

    msg_id = raw_id.split("_")[-1]
    winners = int(body.get("winners", 1))

    key = f"{gid}_{msg_id}"
    gw = db.giveaways.get(key) or db.giveaways.get(raw_id)
    if not gw:
        return jsonify({"success": False, "error": "Giveaway not found."})

    entries = gw.get("entries", [])
    if not entries:
        return jsonify({"success": False, "error": "No entries in this giveaway to reroll."})

    import random
    new_winners = random.sample(entries, k=min(len(entries), max(1, winners)))
    gw["winners"] = new_winners
    db.save_data()

    async def do_announce():
        guild = bot_instance.get_guild(int(gid))
        if guild:
            ch = guild.get_channel(gw.get("channel_id"))
            if ch:
                mentions = " ".join(f"<@{w}>" for w in new_winners)
                jump_url = f"https://discord.com/channels/{gid}/{ch.id}/{msg_id}"
                cfg = db.giveaways_config.get(str(gid), {})
                reroll_title = cfg.get("reroll_title") or "🎲 GIVEAWAY REROLLED (via Dashboard)! 🎲"
                emoji_prize = cfg.get("emoji_prize", "🎁")
                emoji_winners = cfg.get("emoji_winners", "🏆")
                default_reroll = f"> 🥳 New winner selected! Congratulations {{winners}}! You won **{{prize}}**! {emoji_prize}\n\n🔗 **Jump to Giveaway:** {{link}}"
                raw_reroll = cfg.get("reroll_message") or default_reroll
                desc = raw_reroll.replace("{winners}", mentions)\
                                 .replace("{winner}", mentions)\
                                 .replace("{prize}", gw.get("prize", "the prize"))\
                                 .replace("{host}", "Dashboard Administrator")\
                                 .replace("{link}", jump_url)\
                                 .replace("{entries}", str(len(entries)))
                embed = discord.Embed(
                    title=reroll_title,
                    description=desc,
                    color=discord.Color.from_rgb(245, 158, 11),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name=f"{emoji_prize} Prize", value=f"**{gw.get('prize')}**", inline=True)
                embed.add_field(name=f"{emoji_winners} New Winner(s)", value=mentions, inline=True)
                embed.set_footer(text="Friday Giveaway Engine • Dashboard Reroll", icon_url=guild.icon.url if guild.icon else None)
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="View Giveaway Message", url=jump_url, emoji="🔗", style=discord.ButtonStyle.link))
                await ch.send(content=f"🎲 **Giveaway Rerolled!** Congratulations {mentions}!", embed=embed, view=view)

                # Log reroll to #giveaway-logs channel
                try:
                    log_channel = await resolve_giveaway_log_channel(bot_instance, guild, cfg)
                    if log_channel:
                        default_reroll_log_title = "🎲 Giveaway Rerolled"
                        default_reroll_log_desc = (
                            f"**Prize:** {gw.get('prize')}\n"
                            f"**New Winner(s):** {mentions}\n"
                            f"**Channel:** <#{ch.id}>\n"
                            f"**Rerolled by:** Dashboard Administrator"
                        )
                        raw_reroll_log_title = cfg.get("log_reroll_title") or default_reroll_log_title
                        raw_reroll_log_desc = cfg.get("log_reroll_message") or default_reroll_log_desc
                        formatted_log = (
                            raw_reroll_log_desc
                            .replace("{prize}", str(gw.get("prize")))
                            .replace("{winners}", mentions)
                            .replace("{channel}", f"<#{ch.id}>")
                            .replace("{staff}", "Dashboard Administrator")
                            .replace("{server}", guild.name)
                            .replace("{link}", jump_url)
                        )
                        reroll_log_embed = discord.Embed(
                            title=raw_reroll_log_title.replace("{prize}", str(gw.get("prize"))),
                            description=formatted_log,
                            color=discord.Color.from_rgb(245, 158, 11),
                            timestamp=datetime.now(timezone.utc)
                        )
                        if guild.icon:
                            reroll_log_embed.set_footer(text="Friday Giveaway Engine • Audit Log", icon_url=guild.icon.url)
                        await log_channel.send(embed=reroll_log_embed)
                except Exception as e:
                    print(f"[Giveaways] Error logging reroll to Discord channel: {e}")

    try:
        fut = asyncio.run_coroutine_threadsafe(do_announce(), bot_instance.loop)
        fut.result(timeout=10)
        return jsonify({"success": True, "winners": new_winners})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/giveaways/cancel', methods=['POST'])
def cancel_guild_giveaway(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."}), 503

    body = flask_request.json or {}
    raw_id = str(body.get("message_id") or body.get("id") or body.get("key") or "").strip()
    if not raw_id or raw_id == "undefined":
        return jsonify({"success": False, "error": "Valid Giveaway Message ID required."})

    msg_id = raw_id.split("_")[-1]
    key = f"{gid}_{msg_id}"
    gw = db.giveaways.get(key) or db.giveaways.get(raw_id)
    if not gw or gw.get("status") != "active":
        return jsonify({"success": False, "error": "Active giveaway not found."})

    gw["status"] = "cancelled"
    db.save_data()

    async def do_cancel():
        guild = bot_instance.get_guild(int(gid))
        if guild:
            ch = guild.get_channel(gw.get("channel_id"))
            if ch:
                try:
                    m = await ch.fetch_message(int(msg_id))
                    if m and m.embeds:
                        embed = m.embeds[0]
                        embed.title = f"❌ GIVEAWAY CANCELLED: {gw.get('prize')} ❌"
                        embed.color = discord.Color.red()
                        from cogs.giveaways import GiveawayEnterView
                        view = GiveawayEnterView(giveaway_key=key, entry_count=len(gw.get("entries", [])), disabled=True)
                        await m.edit(embed=embed, view=view)
                except Exception:
                    pass

                # Log cancellation to #giveaway-logs
                try:
                    cfg = db.giveaways_config.get(str(gid), {})
                    log_channel = await resolve_giveaway_log_channel(bot_instance, guild, cfg)
                    if log_channel:
                        cancel_log = discord.Embed(
                            title="❌ Giveaway Cancelled",
                            description=f"**Prize:** {gw.get('prize')}\n**Channel:** <#{ch.id}>\n**Action:** Cancelled via Dashboard",
                            color=discord.Color.red(),
                            timestamp=datetime.now(timezone.utc)
                        )
                        if guild.icon:
                            cancel_log.set_footer(text="Friday Giveaway Engine • Audit Log", icon_url=guild.icon.url)
                        await log_channel.send(embed=cancel_log)
                except Exception as e:
                    print(f"[Giveaways] Error logging cancellation: {e}")

    try:
        fut = asyncio.run_coroutine_threadsafe(do_cancel(), bot_instance.loop)
        fut.result(timeout=10)
        return jsonify({"success": True, "message": "Giveaway cancelled."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ───────────────────── Birthday Studio & Tracker ─────────────────────

@app.route('/api/guild/<gid>/birthdays', methods=['GET'])
def get_guild_birthdays(gid):
    gid_str = str(gid)
    try:
        db.reload()
    except Exception:
        pass
    cfg = db.birthdays_config.get(gid_str, {})
    if not isinstance(cfg, dict):
        cfg = {}

    bds_map = db.birthdays.get(gid_str, {})
    if not isinstance(bds_map, dict):
        bds_map = {}

    guild = bot_instance.get_guild(int(gid)) if bot_instance else None

    birthdays_list = []
    for uid, rec in bds_map.items():
        name = str(rec.get("user_name") or f"Member {uid}")
        try:
            default_idx = int(str(uid)[-2:]) % 5
        except Exception:
            default_idx = 0
        avatar = f"https://cdn.discordapp.com/embed/avatars/{default_idx}.png"

        if guild:
            try:
                mem = guild.get_member(int(uid))
                if mem:
                    name = mem.display_name
                    if mem.display_avatar:
                        avatar = str(mem.display_avatar.url)
            except Exception:
                pass

        birthdays_list.append({
            "user_id": str(uid),
            "user_name": name,
            "avatar_url": avatar,
            "month": int(rec.get("month", 1)),
            "day": int(rec.get("day", 1)),
            "registered_at": rec.get("registered_at", "")
        })
    birthdays_list.sort(key=lambda x: (x["month"], x["day"]))

    restricted_data = []
    for r_uid in db.birthdays_restricted.get(gid_str, []):
        r_str = str(r_uid)
        r_name = f"User {r_str}"
        try:
            default_idx = int(r_str[-2:]) % 5
        except Exception:
            default_idx = 0
        r_avatar = f"https://cdn.discordapp.com/embed/avatars/{default_idx}.png"

        if guild:
            try:
                mem = guild.get_member(int(r_str))
                if mem:
                    r_name = mem.display_name
                    if mem.display_avatar:
                        r_avatar = str(mem.display_avatar.url)
            except Exception:
                pass

        restricted_data.append({
            "user_id": r_str,
            "user_name": r_name,
            "avatar_url": r_avatar
        })

    return jsonify({
        "success": True,
        "status": "success",
        "config": cfg,
        "birthdays": birthdays_list,
        "members": birthdays_list,
        "restricted": restricted_data,
        "restricted_ids": [x["user_id"] for x in restricted_data]
    })

@app.route('/api/guild/<gid>/birthdays/config', methods=['POST'])
def update_birthday_config(gid):
    gid_str = str(gid)
    data = flask_request.json or {}

    cfg = db.birthdays_config.setdefault(gid_str, {})
    raw_enabled = data.get("enabled", False)
    if isinstance(raw_enabled, str):
        cfg["enabled"] = raw_enabled.strip().lower() in ("true", "1", "yes", "on")
    else:
        cfg["enabled"] = bool(raw_enabled)
    cfg["form_channel_id"] = str(data.get("form_channel_id") or "").strip()
    cfg["wish_channel_id"] = str(data.get("wish_channel_id") or "").strip()
    cfg["role_id"] = str(data.get("role_id") or "").strip()
    cfg["ping_everyone"] = bool(data.get("ping_everyone", False))
    cfg["mention_user"] = bool(data.get("mention_user", True))
    cfg["wish_time"] = str(data.get("wish_time") or "00:00").strip()
    cfg["timezone"] = str(data.get("timezone") or "Asia/Kolkata").strip()
    cfg["form_card_title"] = str(data.get("form_card_title") or "🎂 Member Birthday Registration").strip()
    cfg["form_card_desc"] = str(data.get("form_card_desc") or "").strip()
    cfg["form_card_banner"] = str(data.get("form_card_banner") or "").strip()
    cfg["wish_message"] = str(data.get("wish_message") or "🎂 Happy Birthday {mention}! Let's celebrate! 🎉").strip()
    cfg["embed_title"] = str(data.get("embed_title") or "🎉 HAPPY BIRTHDAY, {user}! 🎂").strip()
    cfg["embed_description"] = str(data.get("embed_description") or "").strip()
    cfg["embed_color"] = str(data.get("embed_color") or "#ff69b4").strip()
    cfg["embed_image"] = str(data.get("embed_image") or "").strip()
    cfg["embed_footer"] = str(data.get("embed_footer") or "Friday Birthday Engine • Wish them in chat!").strip()

    if hasattr(db, "data") and isinstance(db.data, dict):
        db.data.setdefault("birthdays_config", {})[gid_str] = cfg
    db.save_data()
    return jsonify({"success": True, "message": "Birthday settings saved successfully.", "config": cfg})

@app.route('/api/guild/<gid>/birthdays/upload-banner', methods=['POST'])
@app.route('/api/guild/<gid>/birthdays/upload-card-banner', methods=['POST'])
def upload_birthday_banner(gid):
    try:
        os.makedirs(BIRTHDAY_BANNER_DIR, exist_ok=True)
        file = flask_request.files.get('banner_file') or flask_request.files.get('banner') or flask_request.files.get('file')
        if not file or not file.filename:
            return jsonify({"success": False, "status": "error", "error": "No file uploaded."}), 400

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
            return jsonify({"success": False, "error": "Unsupported file format. Please upload PNG, JPG, GIF, or WebP."}), 400

        token = uuid.uuid4().hex[:12]
        safe_filename = f"bd_{gid}_{token}{ext}"
        save_path = os.path.join(BIRTHDAY_BANNER_DIR, safe_filename)
        file.save(save_path)

        rel_url = f"/static/uploads/birthday_banners/{safe_filename}"
        return jsonify({
            "success": True,
            "status": "success",
            "url": rel_url,
            "banner_url": rel_url,
            "filename": safe_filename
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/birthdays/post-form', methods=['POST'])
def post_birthday_form_card(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."}), 503

    gid_str = str(gid)
    cfg = db.birthdays_config.get(gid_str, {})
    form_chan_id = cfg.get("form_channel_id")
    if not form_chan_id:
        return jsonify({"success": False, "error": "Please select and save a Form Channel first."}), 400

    async def do_post():
        guild = bot_instance.get_guild(int(gid))
        if not guild:
            raise Exception("Guild not found.")
        channel = guild.get_channel(int(form_chan_id))
        if not channel:
            raise Exception("Form channel could not be found.")

        from emoji_utils import clean_embed_title, normalize_discord_markdown
        raw_card_title = cfg.get("form_card_title", "🎂 Member Birthday Registration")
        card_title = clean_embed_title(replace_plain_emojis(raw_card_title, bot=bot_instance, guild=guild, guild_id=gid_str))
        raw_card_desc = cfg.get(
            "form_card_desc",
            "Click the button below to register your birthday!\n\n"
            "🎉 Friday will deliver celebratory wishes on your special day.\n"
            "🔒 **Strict Privacy:** Only Month & Day are saved. Zero birth year or age is stored."
        )
        card_desc = normalize_discord_markdown(replace_plain_emojis(raw_card_desc, bot=bot_instance, guild=guild, guild_id=gid_str))
        embed = discord.Embed(
            title=card_title,
            description=card_desc,
            color=0xff69b4
        )
        banner_url = cfg.get("form_card_banner")
        discord_file = None
        if banner_url:
            if banner_url.startswith("/static/"):
                fname = os.path.basename(banner_url)
                fpath = os.path.join(app.root_path, "static", "uploads", "birthday_banners", fname)
                if not os.path.exists(fpath):
                    fpath = os.path.join(app.root_path, banner_url.lstrip("/").replace("/", os.sep))
                if os.path.exists(fpath):
                    discord_file = discord.File(fpath, filename=fname)
                    embed.set_image(url=f"attachment://{fname}")
            elif banner_url.startswith(("http://", "https://")):
                embed.set_image(url=banner_url)

        embed.set_footer(text="Friday Birthday Engine • Ephemeral & Private Submission")

        from cogs.birthdays import BirthdayRegisterView
        if discord_file:
            msg = await channel.send(embed=embed, file=discord_file, view=BirthdayRegisterView())
        else:
            msg = await channel.send(embed=embed, view=BirthdayRegisterView())
        cfg["form_message_id"] = str(msg.id)
        db.save_data()
        return msg.id

    try:
        fut = asyncio.run_coroutine_threadsafe(do_post(), bot_instance.loop)
        msg_id = fut.result(timeout=10)
        return jsonify({"success": True, "message": "Interactive Registration Card deployed to channel!", "message_id": str(msg_id)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/birthdays/test', methods=['POST'])
def test_birthday_wish(gid):
    if not bot_instance or not bot_instance.loop:
        return jsonify({"success": False, "error": "Friday bot is not connected."}), 503

    gid_str = str(gid)
    cfg = db.birthdays_config.get(gid_str, {})
    wish_chan_id = cfg.get("wish_channel_id")
    if not wish_chan_id:
        return jsonify({"success": False, "error": "Please select and save a Wish Channel first."}), 400

    async def do_test():
        guild = bot_instance.get_guild(int(gid))
        if not guild:
            raise Exception("Guild not found.")
        channel = guild.get_channel(int(wish_chan_id))
        if not channel:
            raise Exception("Wish channel could not be found.")

        cog = bot_instance.get_cog("Birthdays")
        if not cog:
            raise Exception("Birthdays cog is not active.")

        sample_member = guild.owner or guild.me
        await cog._send_birthday_wish(guild, channel, sample_member, cfg)

    try:
        fut = asyncio.run_coroutine_threadsafe(do_test(), bot_instance.loop)
        fut.result(timeout=10)
        return jsonify({"success": True, "message": "Sample birthday wish sent to the wish channel!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/guild/<gid>/birthdays/member/edit', methods=['POST'])
def edit_birthday_member(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    uid = str(data.get("user_id") or "").strip()
    if not uid:
        return jsonify({"success": False, "error": "User ID required."}), 400

    try:
        month = int(data.get("month"))
        day = int(data.get("day"))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Valid Month (1-12) and Day (1-31) required."}), 400

    if month < 1 or month > 12 or day < 1 or day > 31:
        return jsonify({"success": False, "error": "Date values out of range."}), 400

    guild_bds = db.birthdays.setdefault(gid_str, {})
    rec = guild_bds.setdefault(uid, {"user_id": uid, "registered_at": datetime.now(timezone.utc).isoformat()})
    rec["month"] = month
    rec["day"] = day
    if "user_name" in data and data["user_name"]:
        rec["user_name"] = str(data["user_name"]).strip()

    db.save_data()
    return jsonify({"success": True, "message": "Member birthday updated."})

@app.route('/api/guild/<gid>/birthdays/member/delete', methods=['POST'])
def delete_birthday_member(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    uid = str(data.get("user_id") or "").strip()
    if not uid:
        return jsonify({"success": False, "error": "User ID required."}), 400

    guild_bds = db.birthdays.get(gid_str, {})
    if uid in guild_bds:
        del guild_bds[uid]

    restricted = db.birthdays_restricted.setdefault(gid_str, [])
    if uid not in restricted:
        restricted.append(uid)

    db.save_data()
    return jsonify({"success": True, "message": "Member birthday removed and locked from self-registration."})

@app.route('/api/guild/<gid>/birthdays/member/unlock', methods=['POST'])
def unlock_birthday_member(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    uid = str(data.get("user_id") or "").strip()
    if not uid:
        return jsonify({"success": False, "error": "User ID required."}), 400

    restricted = db.birthdays_restricted.get(gid_str, [])
    if uid in restricted:
        restricted.remove(uid)
        db.save_data()
        return jsonify({"success": True, "message": f"Member {uid} unlocked! They can now register their birthday again."})

    return jsonify({"success": True, "message": "Member was not in restricted list."})


# ───────────────────── API: Birthday System Quick Toggle ─────────────────────

@app.route('/api/guild/<gid>/birthdays/toggle', methods=['POST'])
def toggle_birthday_system(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    cfg = db.birthdays_config.setdefault(gid_str, {})
    if "enabled" in data:
        raw_val = data["enabled"]
        if isinstance(raw_val, str):
            new_state = raw_val.strip().lower() in ("true", "1", "yes", "on")
        else:
            new_state = bool(raw_val)
    else:
        new_state = not cfg.get("enabled", False)
    cfg["enabled"] = new_state
    if hasattr(db, "data") and isinstance(db.data, dict):
        db.data.setdefault("birthdays_config", {})[gid_str] = cfg
    db.save_data()
    return jsonify({"success": True, "enabled": new_state, "message": f"Birthday system {'enabled' if new_state else 'disabled'}."})


# ───────────────────── API: Staff Applications Studio ─────────────────────

@app.route('/api/guild/<gid>/applications', methods=['GET'])
def get_guild_applications(gid):
    gid_str = str(gid)
    gdata = db.applications.get(gid_str, {})
    
    try:
        from cogs.applications import get_app_config
        cfg = get_app_config(gid_str)
    except Exception:
        cfg = gdata.get("config", {})

    submissions = gdata.get("submissions", {})
    sub_list = list(submissions.values())
    sub_list.sort(key=lambda s: s.get("number", 0), reverse=True)

    return jsonify({
        "success": True,
        "config": cfg,
        "panels": gdata.get("panels", {}),
        "submissions": sub_list,
        "submission_counter": gdata.get("submission_counter", 0)
    })

@app.route('/api/guild/<gid>/applications/config', methods=['POST'])
def save_applications_config(gid):
    gid_str = str(gid)
    data = flask_request.json or {}
    gdata = db.applications.setdefault(gid_str, {})
    
    try:
        from cogs.applications import get_app_config
        cfg = get_app_config(gid_str)
    except Exception:
        cfg = gdata.setdefault("config", {})

    if "panel_channel_id" in data:
        cfg["panel_channel_id"] = str(data["panel_channel_id"]).strip() if data["panel_channel_id"] else None
    if "review_channel_id" in data:
        cfg["review_channel_id"] = str(data["review_channel_id"]).strip() if data["review_channel_id"] else None
    if "approved_role_id" in data:
        cfg["approved_role_id"] = str(data["approved_role_id"]).strip() if data["approved_role_id"] else None
    if "delivery_mode" in data:
        cfg["delivery_mode"] = str(data["delivery_mode"]).strip() or "server"

    if "panel" in data and isinstance(data["panel"], dict):
        p = data["panel"]
        cfg["panel"] = {
            "title": str(p.get("title") or "📋 Staff Application").strip(),
            "description": str(p.get("description") or "Click below to apply!").strip(),
            "color": str(p.get("color") or "#5865f2").strip(),
            "footer": str(p.get("footer") or "Friday Applications • Click below to apply").strip(),
            "button_label": str(p.get("button_label") or "Apply Now").strip(),
            "button_emoji": str(p.get("button_emoji") or "📝").strip(),
            "button_style": str(p.get("button_style") or "primary").strip(),
            "thumbnail_mode": str(p.get("thumbnail_mode") or "friday").strip(),
            "image_url": str(p.get("image_url") or p.get("banner") or "").strip()
        }

    if "questions" in data and isinstance(data["questions"], list):
        clean_qs = [str(q).strip() for q in data["questions"] if str(q).strip()]
        if clean_qs:
            cfg["questions"] = clean_qs

    if "dm_flow" in data and isinstance(data["dm_flow"], dict):
        d = data["dm_flow"]
        cfg["dm_flow"] = {
            "intro_title": str(d.get("intro_title") or "📝 Staff Application • {server}").strip(),
            "intro_description": str(d.get("intro_description") or "").strip(),
            "intro_color": str(d.get("intro_color") or "#5865f2").strip(),
            "start_btn_label": str(d.get("start_btn_label") or "Let's Start").strip(),
            "start_btn_emoji": str(d.get("start_btn_emoji") or "🚀").strip(),
            "cancel_btn_label": str(d.get("cancel_btn_label") or "Cancel").strip(),
            "cancel_btn_emoji": str(d.get("cancel_btn_emoji") or "✖️").strip()
        }

    if "approved_msg" in data and isinstance(data["approved_msg"], dict):
        a = data["approved_msg"]
        cfg["approved_msg"] = {
            "title": str(a.get("title") or "🎉 Application Approved • {server}").strip(),
            "description": str(a.get("description") or "").strip(),
            "color": str(a.get("color") or "#10b981").strip()
        }

    if "rejected_msg" in data and isinstance(data["rejected_msg"], dict):
        r = data["rejected_msg"]
        cfg["rejected_msg"] = {
            "title": str(r.get("title") or "Application Update • {server}").strip(),
            "description": str(r.get("description") or "").strip(),
            "color": str(r.get("color") or "#ef4444").strip()
        }

    gdata["config"] = cfg
    db.save_data()
    return jsonify({"success": True, "message": "Application configuration saved successfully.", "config": cfg})

@app.route('/api/guild/<gid>/applications/upload-banner', methods=['POST'])
def upload_application_banner(gid):
    if 'banner' not in flask_request.files:
        return jsonify({"success": False, "error": "No file uploaded."}), 400
    file = flask_request.files['banner']
    if file.filename == '':
        return jsonify({"success": False, "error": "Empty filename."}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
        return jsonify({"success": False, "error": "Invalid format. Supported: PNG, JPG, GIF, WebP."}), 400

    from werkzeug.utils import secure_filename
    import time
    clean_name = secure_filename(file.filename)
    safe_filename = f"app_banner_{gid}_{int(time.time())}_{clean_name}"
    filepath = os.path.join(APPLICATION_BANNER_DIR, safe_filename)
    file.save(filepath)

    rel_url = f"/static/uploads/application_banners/{safe_filename}"
    return jsonify({"success": True, "url": rel_url})

@app.route('/api/guild/<gid>/applications/panel', methods=['POST'])
def deploy_application_panel(gid):
    if not bot_instance:
        return jsonify({"success": False, "error": "Bot not connected."}), 503

    gid_str = str(gid)
    data = flask_request.json or {}
    channel_id = data.get("channel_id")
    if not channel_id:
        return jsonify({"success": False, "error": "Panel destination channel is required."}), 400

    async def do_deploy():
        guild = bot_instance.get_guild(int(gid))
        if not guild:
            raise Exception("Guild not found or Friday is not connected to it.")
        channel = guild.get_channel(int(channel_id))
        if not channel:
            raise Exception("Target text channel not found.")

        from cogs.applications import get_app_config, get_button_style, hex_to_int, ApplicationPanelView
        from emoji_utils import replace_plain_emojis, resolve_single_emoji, clean_embed_title, normalize_discord_markdown

        cfg = get_app_config(gid_str)
        p_cfg = cfg.get("panel", {})

        title_raw = str(data.get("title") or p_cfg.get("title") or "📋 Staff Application")
        desc_raw = str(data.get("description") or p_cfg.get("description") or "Click below to submit your application!")
        color_val = str(data.get("color") or p_cfg.get("color") or "#5865f2")
        footer_val = str(data.get("footer") or p_cfg.get("footer") or "Friday Applications • Click below to apply")
        btn_label = str(data.get("button_label") or p_cfg.get("button_label") or "Apply Now")
        btn_emoji_raw = str(data.get("button_emoji") or p_cfg.get("button_emoji") or "📝")
        btn_style_str = str(data.get("button_style") or p_cfg.get("button_style") or "primary")

        embed_title = clean_embed_title(replace_plain_emojis(title_raw, bot=bot_instance, guild=guild, guild_id=gid_str))
        embed_desc = normalize_discord_markdown(replace_plain_emojis(desc_raw, bot=bot_instance, guild=guild, guild_id=gid_str))
        embed_color = hex_to_int(color_val)

        embed = discord.Embed(title=embed_title, description=embed_desc, color=embed_color)
        embed.set_footer(text=footer_val, icon_url=guild.icon.url if guild.icon else None)
        embed.timestamp = discord.utils.utcnow()

        thumbnail_mode = str(data.get("thumbnail_mode") or p_cfg.get("thumbnail_mode") or "friday").lower()
        if thumbnail_mode == "server" and guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        elif thumbnail_mode == "friday" and bot_instance and bot_instance.user and bot_instance.user.display_avatar:
            embed.set_thumbnail(url=bot_instance.user.display_avatar.url)

        # Support large banner image / GIF from URL or local upload
        raw_image_url = str(data.get("image_url") or data.get("banner") or p_cfg.get("image_url") or p_cfg.get("banner") or "").strip()
        discord_file = None
        if raw_image_url:
            if raw_image_url.startswith("/static/"):
                fname = os.path.basename(raw_image_url)
                fpath = os.path.join(APPLICATION_BANNER_DIR, fname)
                if not os.path.exists(fpath):
                    fpath = os.path.join(app.root_path, raw_image_url.lstrip("/").replace("/", os.sep))
                if os.path.exists(fpath):
                    discord_file = discord.File(fpath, filename=fname)
                    embed.set_image(url=f"attachment://{fname}")
            elif raw_image_url.startswith(("http://", "https://")):
                embed.set_image(url=raw_image_url)

        btn_style = get_button_style(btn_style_str)
        btn_emoji = resolve_single_emoji(btn_emoji_raw, bot=bot_instance, guild=guild, guild_id=gid_str)

        temp_view = discord.ui.View()
        temp_btn = discord.ui.Button(label=btn_label, style=btn_style, emoji=btn_emoji)
        temp_view.add_item(temp_btn)
        if discord_file:
            msg = await channel.send(embed=embed, file=discord_file, view=temp_view)
        else:
            msg = await channel.send(embed=embed, view=temp_view)

        gdata = db.applications.setdefault(gid_str, {})
        panels = gdata.setdefault("panels", {})
        panel_record = {
            "channel_id": int(channel_id),
            "title": title_raw,
            "description": desc_raw,
            "color": color_val,
            "footer": footer_val,
            "button_label": btn_label,
            "button_emoji": btn_emoji_raw,
            "button_style": btn_style_str,
            "thumbnail_mode": thumbnail_mode,
            "image_url": raw_image_url
        }
        panels[str(msg.id)] = panel_record
        cfg["panel_channel_id"] = str(channel_id)
        p_cfg.update(panel_record)
        cfg["panel"] = p_cfg
        gdata["config"] = cfg
        db.save_data()

        app_cog = bot_instance.get_cog("Applications")
        if app_cog:
            actual_view = ApplicationPanelView(app_cog, msg.id)
            actual_view.clear_items()
            real_btn = discord.ui.Button(
                label=btn_label,
                style=btn_style,
                emoji=btn_emoji,
                custom_id=f"app_apply_btn_{msg.id}"
            )
            real_btn.callback = actual_view.apply_button.callback
            actual_view.add_item(real_btn)
            await msg.edit(view=actual_view)
            bot_instance.add_view(actual_view, message_id=msg.id)

        return msg.id

    try:
        fut = asyncio.run_coroutine_threadsafe(do_deploy(), bot_instance.loop)
        msg_id = fut.result(timeout=10)
        return jsonify({"success": True, "message": "Application panel deployed successfully!", "message_id": str(msg_id)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
