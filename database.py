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
        self.liked_songs = self.data.get("liked_songs", {})
        self.warnings = self.data.get("warnings", {})
        self.first_welcome = self.data.get("first_welcome", {})
        self.first_chat_welcomes = self.data.get("first_chat_welcomes", {})
        self.afk_data = self.data.get("afk_data", {})
        self.user_memories = self.data.get("user_memories", {})
        self.server_instructions = self.data.get("server_instructions", {})
        self.temp_voice = self.data.get("temp_voice", {})

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
                "liked_songs": {},
                "warnings": {},
                "first_welcome": {},
                "first_chat_welcomes": {},
                "afk_data": {},
                "user_memories": {},
                "server_instructions": {},
                "temp_voice": {}
            }

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
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)

db = Database()
