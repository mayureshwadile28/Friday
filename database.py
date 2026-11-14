import json
import os

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "friday_memory.json")

class Database:
    def __init__(self):
        self.reload()

    def reload(self):
        self.data = self.load_data()
        self.nuke_settings = self.data.get("nuke_settings", {})
        self.whitelist = self.data.get("whitelist", {})
        self.antinuke_active = self.data.get("antinuke_active", {})
        self.server_logs = self.data.get("server_logs", {})
        self.banned_words = self.data.get("banned_words", {})
        self.abuse_whitelist = self.data.get("abuse_whitelist", {})
        self.xp_data = self.data.get("xp_data", {})
        self.level_channels = self.data.get("level_channels", {})
        self.level_messages = self.data.get("level_messages", {})
        self.reaction_roles = self.data.get("reaction_roles", {})
        self.ignored_private = self.data.get("ignored_private", {})
        self.lockdown_active = self.data.get("lockdown_active", {})
        self.announcement_channels = self.data.get("announcement_channels", {})
        self.tickets = self.data.get("tickets", {})
        self.level_modes = self.data.get("level_modes", {})
        self.security_settings = self.data.get("security_settings", {})
        self.custom_responses = self.data.get("custom_responses", {})
        self.feature_whitelists = self.data.get("feature_whitelists", {})
        self.autoreact = self.data.get("autoreact", {})
        self.autoresponder = self.data.get("autoresponder", {})
        self.media_channels = self.data.get("media_channels", {})
        self.media_whitelist = self.data.get("media_whitelist", {})
        self.media_announcements = self.data.get("media_announcements", {})
        self.liked_songs = self.data.get("liked_songs", {})
        self.warnings = self.data.get("warnings", {})
        self.first_welcome = self.data.get("first_welcome", {})
        self.first_chat_welcomes = self.data.get("first_chat_welcomes", {})
        self.first_welcome_allow_test = self.data.get("first_welcome_allow_test", {})
        self.welcome = self.data.get("welcome", {})
        self.farewell = self.data.get("farewell", {})
        self.afk_data = self.data.get("afk_data", {})
        self.user_memories = self.data.get("user_memories", {})
        self.server_instructions = self.data.get("server_instructions", {})
        self.temp_voice = self.data.get("temp_voice", {})
        self.server_backups = self.data.get("server_backups", {})
        self.special_invites = self.data.get("special_invites", {})
        gw = self.data.get("giveaways")
        self.giveaways = gw if isinstance(gw, dict) else {}
        gw_cfg = self.data.get("giveaways_config")
        self.giveaways_config = gw_cfg if isinstance(gw_cfg, dict) else {}
        bd = self.data.get("birthdays")
        self.birthdays = bd if isinstance(bd, dict) else {}
        bdr = self.data.get("birthdays_restricted")
        self.birthdays_restricted = bdr if isinstance(bdr, dict) else {}
        bd_cfg = self.data.get("birthdays_config")
        self.birthdays_config = bd_cfg if isinstance(bd_cfg, dict) else {}
        sa = self.data.get("scheduled_announcements")
        self.scheduled_announcements = sa if isinstance(sa, dict) else {}
        apps = self.data.get("applications")
        self.applications = apps if isinstance(apps, dict) else {}
        rc_bg = self.data.get("rank_card_backgrounds")
        self.rank_card_backgrounds = rc_bg if isinstance(rc_bg, dict) else {}
        lu_bg = self.data.get("levelup_card_backgrounds")
        self.levelup_card_backgrounds = lu_bg if isinstance(lu_bg, dict) else {}
        ic_bg = self.data.get("invite_card_backgrounds")
        self.invite_card_backgrounds = ic_bg if isinstance(ic_bg, dict) else {}
        ac_bg = self.data.get("activity_card_backgrounds")
        self.activity_card_backgrounds = ac_bg if isinstance(ac_bg, dict) else {}
        lb_bg = self.data.get("leaderboard_card_backgrounds")
        self.leaderboard_card_backgrounds = lb_bg if isinstance(lb_bg, dict) else {}
        inv_trk = self.data.get("invite_tracker")
        self.invite_tracker = inv_trk if isinstance(inv_trk, dict) else {}
        inv_cnt = self.data.get("invite_counts")
        self.invite_counts = inv_cnt if isinstance(inv_cnt, dict) else {}
        inv_hist = self.data.get("invite_history")
        self.invite_history = inv_hist if isinstance(inv_hist, dict) else {}
        bp = self.data.get("booster_perks")
        self.booster_perks = bp if isinstance(bp, dict) else {}
        bb = self.data.get("booster_backgrounds")
        self.booster_backgrounds = bb if isinstance(bb, dict) else {}
        lc = self.data.get("locked_channels")
        self.locked_channels = lc if isinstance(lc, dict) else {}
        cp = self.data.get("custom_prefixes")
        self.custom_prefixes = cp if isinstance(cp, dict) else {}
        pw = self.data.get("prefix_whitelist")
        self.prefix_whitelist = pw if isinstance(pw, dict) else {}
        srr = self.data.get("saved_reaction_roles")
        self.saved_reaction_roles = srr if isinstance(srr, dict) else {}

    def load_data(self):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
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
                "level_messages": {},
                "reaction_roles": {},
                "ignored_private": {},
                "lockdown_active": {},
                "announcement_channels": {},
                "tickets": {},
                "level_modes": {},
                "security_settings": {},
                "custom_responses": {},
                "feature_whitelists": {},
                "autoreact": {},
                "autoresponder": {},
                "media_channels": {},
                "media_whitelist": {},
                "media_announcements": {},
                "liked_songs": {},
                "warnings": {},
                "first_welcome": {},
                "first_chat_welcomes": {},
                "first_welcome_allow_test": {},
                "welcome": {},
                "farewell": {},
                "afk_data": {},
                "user_memories": {},
                "server_instructions": {},
                "temp_voice": {},
                "server_backups": {},
                "special_invites": {},
                "giveaways": {},
                "giveaways_config": {},
                "birthdays": {},
                "birthdays_restricted": {},
                "birthdays_config": {},
                "scheduled_announcements": {},
                "applications": {},
                "rank_card_backgrounds": {},
                "levelup_card_backgrounds": {},
                "invite_card_backgrounds": {},
                "activity_card_backgrounds": {},
                "leaderboard_card_backgrounds": {},
                "invite_tracker": {},
                "invite_counts": {},
                "invite_history": {},
                "booster_perks": {},
                "booster_backgrounds": {},
                "locked_channels": {},
                "custom_prefixes": {},
                "prefix_whitelist": {},
                "saved_reaction_roles": {}
            }

    def reload(self):
        """Reload data from disk into memory."""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    disk = json.load(f)
                if isinstance(disk, dict):
                    self.data = disk
                    for k, v in disk.items():
                        self.__dict__[k] = v
        except Exception as e:
            print(f"Error reloading database: {e}")

    def __getattr__(self, name):
        """Dynamic fallback to ensure no missing attribute ever raises AttributeError."""
        if "data" in self.__dict__ and isinstance(self.data, dict) and name in self.data:
            val = self.data[name]
            self.__dict__[name] = val
            return val
        default_val = {}
        if "data" in self.__dict__ and isinstance(self.data, dict):
            self.data[name] = default_val
        self.__dict__[name] = default_val
        return default_val

    def save_data(self):
        disk_data = {}
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    disk_data = json.load(f)
        except Exception:
            pass

        payload = {}
        if hasattr(self, "data") and isinstance(self.data, dict):
            payload.update(self.data)
        if isinstance(disk_data, dict):
            payload.update(disk_data)
        for k, v in self.__dict__.items():
            if k != "data" and not k.startswith("_"):
                payload[k] = v
        self.data = payload
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)

db = Database()
