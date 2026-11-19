import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import os
import time
import random
import json
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from contextlib import contextmanager
from database import db
from font_utils import clean_display_name
from response_utils import ensure_admin_or_owner

# Safe initialization of database attributes if not present on older database.py instances
for attr in ("economy_config", "economy_channels", "economy_log_channels", "economy_paused"):
    if not hasattr(db, attr):
        setattr(db, attr, {})

# SQLite Database Setup
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "economy.db")

# Default Items Catalog
DEFAULT_SHOP_ITEMS = {
    "padlock": {
        "name": "Padlock",
        "emoji": "🔒",
        "price": 750,
        "type": "defense",
        "max_hold": 1,
        "desc": "Blocks the next /rob attempt against your wallet, then shatters."
    },
    "landmine": {
        "name": "Landmine",
        "emoji": "💣",
        "price": 1200,
        "type": "defense",
        "max_hold": 1,
        "desc": "50% chance to detonate when someone robs you, doubling their fine."
    },
    "xp_booster": {
        "name": "2x XP Booster",
        "emoji": "⚡",
        "price": 3000,
        "type": "consumable",
        "duration_hours": 2,
        "desc": "Hooks into Friday's leveling system to grant 2x Chat XP for 2 hours."
    },
    "bank_expansion": {
        "name": "Bank Expansion Pass",
        "emoji": "🏦",
        "price": 2500,
        "type": "upgrade",
        "bank_increase": 5000,
        "desc": "Permanently increases your bank vault storage capacity by +5,000."
    },
    "custom_role_color": {
        "name": "Custom Role Color",
        "emoji": "🎨",
        "price": 15000,
        "type": "cosmetic",
        "desc": "Grants access to a custom cosmetic color role on the server."
    },
    "vip_badge": {
        "name": "VIP Badge",
        "emoji": "👑",
        "price": 50000,
        "type": "status",
        "desc": "Displays a permanent VIP crown badge on your /balance and profile."
    }
}

WORK_PROMPTS = [
    ("You fixed a critical memory leak in Friday's background task loop.", 120, 200),
    ("You moderated the server chat and kept the community friendly.", 90, 160),
    ("You configured Friday's systemd service and achieved 100% uptime.", 130, 210),
    ("You organized a movie night in the community voice lounge.", 80, 150),
    ("You helped a newcomer find their way through the role assignment panel.", 85, 140),
    ("You reported a suspicious user attempt before anti-raid was even triggered.", 100, 180),
    ("You designed a sleek new wallpaper for the server rank cards.", 110, 195),
    ("You hosted a trivia game in general chat and energized the lobby.", 95, 165),
    ("You optimized Friday's database indexes and sped up query times.", 140, 220),
    ("You assisted staff during a server migration event.", 100, 175)
]

CRIME_SUCCESS_PROMPTS = [
    "You successfully infiltrated a crypto whale's hot wallet!",
    "You sold illegal memes on the server black market without getting caught.",
    "You bypassed a high-roller casino firewall and snatched a jackpot bounty!",
    "You pulled off an undercover heist on the rival bot's coin stash!",
    "You counterfeited limited edition server badges and cashed out!"
]

CRIME_FAIL_PROMPTS = [
    "You got caught red-handed by the server police!",
    "Your fake ID slipped out of your pocket right in front of the moderator desk!",
    "Friday's biometric security scanner triggered an alarm on your face!",
    "You tripped the laser tripwire trying to steal from the vault!",
    "The target's guard dog tackled you into a stack of empty crates!"
]


class EconomyDB:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self.get_conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            
            # Users table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS economy_users (
                    guild_id      TEXT    NOT NULL,
                    user_id       TEXT    NOT NULL,
                    wallet        INTEGER NOT NULL DEFAULT 0,
                    bank          INTEGER NOT NULL DEFAULT 0,
                    bank_max      INTEGER NOT NULL DEFAULT 2500,
                    streak        INTEGER NOT NULL DEFAULT 0,
                    last_daily    REAL    NOT NULL DEFAULT 0,
                    last_work     REAL    NOT NULL DEFAULT 0,
                    last_crime    REAL    NOT NULL DEFAULT 0,
                    last_rob      REAL    NOT NULL DEFAULT 0,
                    passive_mode  INTEGER NOT NULL DEFAULT 0,
                    net_earned    INTEGER NOT NULL DEFAULT 0,
                    net_spent     INTEGER NOT NULL DEFAULT 0,
                    created_at    REAL    NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)

            # Inventory table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS economy_inventory (
                    guild_id    TEXT    NOT NULL,
                    user_id     TEXT    NOT NULL,
                    item_id     TEXT    NOT NULL,
                    quantity    INTEGER NOT NULL DEFAULT 1,
                    expires_at  REAL    NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, item_id)
                )
            """)

            # Transactions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS economy_transactions (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id      TEXT    NOT NULL,
                    user_id       TEXT    NOT NULL,
                    type          TEXT    NOT NULL,
                    amount        INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    related_uid   TEXT    DEFAULT NULL,
                    note          TEXT,
                    ts            REAL    NOT NULL
                )
            """)

            # Active games table (anti-dupe for Blackjack / Coinflip)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS economy_active_games (
                    guild_id    TEXT    NOT NULL,
                    user_id     TEXT    NOT NULL,
                    game_type   TEXT    NOT NULL DEFAULT 'blackjack',
                    bet_locked  INTEGER NOT NULL DEFAULT 0,
                    game_state  TEXT    NOT NULL DEFAULT '{}',
                    started_at  REAL    NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)

    def get_user(self, gid: str, uid: str) -> Optional[dict]:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM economy_users WHERE guild_id=? AND user_id=?", (gid, uid)
            ).fetchone()
            return dict(row) if row else None

    def get_or_init_user(self, gid: str, uid: str, starter_bank: int = 100, bank_max: int = 2500) -> dict:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM economy_users WHERE guild_id=? AND user_id=?", (gid, uid)
            ).fetchone()
            if row:
                return dict(row)
            
            now = time.time()
            conn.execute("""
                INSERT INTO economy_users (guild_id, user_id, wallet, bank, bank_max, streak, created_at)
                VALUES (?, ?, 0, ?, ?, 0, ?)
            """, (gid, uid, starter_bank, bank_max, now))
            
            row = conn.execute(
                "SELECT * FROM economy_users WHERE guild_id=? AND user_id=?", (gid, uid)
            ).fetchone()
            return dict(row)

    def delta_wallet(self, gid: str, uid: str, delta: int) -> int:
        """Atomically modifies wallet balance, clamped at >= 0. Returns new wallet balance."""
        with self.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                UPDATE economy_users
                SET wallet = MAX(0, wallet + ?),
                    net_earned = CASE WHEN ? > 0 THEN net_earned + ? ELSE net_earned END,
                    net_spent  = CASE WHEN ? < 0 THEN net_spent + ABS(?) ELSE net_spent END
                WHERE guild_id=? AND user_id=?
            """, (delta, delta, delta, delta, delta, gid, uid))
            
            row = conn.execute(
                "SELECT wallet FROM economy_users WHERE guild_id=? AND user_id=?", (gid, uid)
            ).fetchone()
            return row["wallet"] if row else 0

    def delta_bank(self, gid: str, uid: str, delta: int, max_cap: Optional[int] = None) -> int:
        """Atomically modifies bank balance, auto-expanding bank_max if needed so vault capacity never displays over-capacity."""
        with self.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if max_cap is not None and delta > 0:
                conn.execute("""
                    UPDATE economy_users
                    SET bank = MIN(?, MAX(0, bank + ?)),
                        bank_max = MAX(bank_max, MIN(?, MAX(0, bank + ?)))
                    WHERE guild_id=? AND user_id=?
                """, (max_cap, delta, max_cap, delta, gid, uid))
            else:
                conn.execute("""
                    UPDATE economy_users
                    SET bank = MAX(0, bank + ?),
                        bank_max = MAX(bank_max, bank + ?)
                    WHERE guild_id=? AND user_id=?
                """, (delta, delta, gid, uid))
            row = conn.execute(
                "SELECT bank FROM economy_users WHERE guild_id=? AND user_id=?", (gid, uid)
            ).fetchone()
            return row["bank"] if row else 0

    def transfer_wallet_to_bank(self, gid: str, uid: str, amount: int) -> Tuple[bool, int, int, str]:
        """Atomically moves funds from wallet to bank up to bank_max."""
        with self.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT wallet, bank, bank_max FROM economy_users WHERE guild_id=? AND user_id=?",
                (gid, uid)
            ).fetchone()
            if not row:
                return False, 0, 0, "Profile not found."
            
            wallet, bank, bank_max = row["wallet"], row["bank"], row["bank_max"]
            if amount <= 0:
                return False, wallet, bank, "Deposit amount must be greater than zero."
            if wallet < amount:
                return False, wallet, bank, "You do not have enough coins in your wallet."
            
            available_space = max(0, bank_max - bank)
            if available_space <= 0:
                return False, wallet, bank, f"Your bank is completely full! Capacity: {bank_max:,} coins. Upgrade via `/bank_upgrade`."
            
            deposit_amount = min(amount, available_space)
            new_wallet = wallet - deposit_amount
            new_bank = bank + deposit_amount
            
            conn.execute("""
                UPDATE economy_users
                SET wallet = ?, bank = ?
                WHERE guild_id=? AND user_id=?
            """, (new_wallet, new_bank, gid, uid))
            
            return True, new_wallet, new_bank, f"Successfully deposited {deposit_amount:,} coins into your safe bank vault!"

    def transfer_bank_to_wallet(self, gid: str, uid: str, amount: int) -> Tuple[bool, int, int, str]:
        """Atomically moves funds from bank back to wallet."""
        with self.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT wallet, bank FROM economy_users WHERE guild_id=? AND user_id=?", (gid, uid)
            ).fetchone()
            if not row:
                return False, 0, 0, "Profile not found."
            
            wallet, bank = row["wallet"], row["bank"]
            if amount <= 0:
                return False, wallet, bank, "Withdraw amount must be greater than zero."
            if bank < amount:
                return False, wallet, bank, "You do not have that many coins in your bank vault."
            
            new_bank = bank - amount
            new_wallet = wallet + amount
            
            conn.execute("""
                UPDATE economy_users
                SET wallet = ?, bank = ?
                WHERE guild_id=? AND user_id=?
            """, (new_wallet, new_bank, gid, uid))
            
            return True, new_wallet, new_bank, f"Successfully withdrew {amount:,} coins into your wallet!"

    def upgrade_bank(self, gid: str, uid: str, cost: int, increase: int) -> Tuple[bool, int, int, str]:
        """Burns coins from wallet to increase bank_max capacity."""
        with self.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT wallet, bank_max FROM economy_users WHERE guild_id=? AND user_id=?", (gid, uid)
            ).fetchone()
            if not row:
                return False, 0, 0, "Profile not found."
            
            wallet, bank_max = row["wallet"], row["bank_max"]
            if wallet < cost:
                return False, wallet, bank_max, f"You need at least {cost:,} coins in your wallet to upgrade your bank."
            
            new_wallet = wallet - cost
            new_max = bank_max + increase
            
            conn.execute("""
                UPDATE economy_users
                SET wallet = ?, bank_max = ?
                WHERE guild_id=? AND user_id=?
            """, (new_wallet, new_max, gid, uid))
            
            return True, new_wallet, new_max, f"Bank Vault upgraded! Capacity increased by +{increase:,} to **{new_max:,} Coins**!"

    def update_field(self, gid: str, uid: str, field: str, value: Any):
        with self.get_conn() as conn:
            conn.execute(f"UPDATE economy_users SET {field} = ? WHERE guild_id=? AND user_id=?", (value, gid, uid))

    def get_inventory(self, gid: str, uid: str) -> List[dict]:
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM economy_inventory WHERE guild_id=? AND user_id=? AND quantity > 0",
                (gid, uid)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_item(self, gid: str, uid: str, item_id: str) -> Optional[dict]:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM economy_inventory WHERE guild_id=? AND user_id=? AND item_id=?",
                (gid, uid, item_id)
            ).fetchone()
            return dict(row) if row else None

    def add_item(self, gid: str, uid: str, item_id: str, qty: int = 1, expires_at: float = 0):
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO economy_inventory (guild_id, user_id, item_id, quantity, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET
                    quantity = quantity + excluded.quantity,
                    expires_at = CASE WHEN excluded.expires_at > expires_at THEN excluded.expires_at ELSE expires_at END
            """, (gid, uid, item_id, qty, expires_at))

    def consume_item(self, gid: str, uid: str, item_id: str, qty: int = 1) -> bool:
        with self.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT quantity FROM economy_inventory WHERE guild_id=? AND user_id=? AND item_id=?",
                (gid, uid, item_id)
            ).fetchone()
            if not row or row["quantity"] < qty:
                return False
            
            new_qty = row["quantity"] - qty
            if new_qty <= 0:
                conn.execute(
                    "DELETE FROM economy_inventory WHERE guild_id=? AND user_id=? AND item_id=?",
                    (gid, uid, item_id)
                )
            else:
                conn.execute(
                    "UPDATE economy_inventory SET quantity=? WHERE guild_id=? AND user_id=? AND item_id=?",
                    (new_qty, gid, uid, item_id)
                )
            return True

    def log_tx(self, gid: str, uid: str, tx_type: str, amount: int, balance_after: int, related_uid: str = None, note: str = None):
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO economy_transactions (guild_id, user_id, type, amount, balance_after, related_uid, note, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (gid, uid, tx_type, amount, balance_after, related_uid, note, time.time()))

    def get_top_users(self, gid: str, limit: int = 10) -> List[dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT user_id, wallet, bank, bank_max, (wallet + bank) AS net_worth
                FROM economy_users
                WHERE guild_id=?
                ORDER BY net_worth DESC
                LIMIT ?
            """, (gid, limit)).fetchall()
            return [dict(r) for r in rows]

    def get_user_rank(self, gid: str, uid: str) -> int:
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) + 1 AS rank
                FROM economy_users
                WHERE guild_id=? AND (wallet + bank) > (
                    SELECT (wallet + bank) FROM economy_users WHERE guild_id=? AND user_id=?
                )
            """, (gid, gid, uid)).fetchone()
            return row["rank"] if row else 1

    # Active games (Blackjack / Coinflip lock)
    def start_game(self, gid: str, uid: str, game_type: str, bet: int, state: dict) -> bool:
        with self.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM economy_active_games WHERE guild_id=? AND user_id=?", (gid, uid)
            ).fetchone()
            if existing:
                return False
            conn.execute("""
                INSERT INTO economy_active_games (guild_id, user_id, game_type, bet_locked, game_state, started_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (gid, uid, game_type, bet, json.dumps(state), time.time()))
            return True

    def get_active_game(self, gid: str, uid: str) -> Optional[dict]:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM economy_active_games WHERE guild_id=? AND user_id=?", (gid, uid)
            ).fetchone()
            if row:
                res = dict(row)
                res["game_state"] = json.loads(res["game_state"])
                return res
            return None

    def update_game(self, gid: str, uid: str, state: dict, bet_locked: Optional[int] = None):
        with self.get_conn() as conn:
            if bet_locked is not None:
                conn.execute("""
                    UPDATE economy_active_games
                    SET game_state=?, bet_locked=?
                    WHERE guild_id=? AND user_id=?
                """, (json.dumps(state), bet_locked, gid, uid))
            else:
                conn.execute("""
                    UPDATE economy_active_games
                    SET game_state=?
                    WHERE guild_id=? AND user_id=?
                """, (json.dumps(state), gid, uid))

    def end_game(self, gid: str, uid: str):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM economy_active_games WHERE guild_id=? AND user_id=?", (gid, uid))

    def admin_reset_user(self, gid: str, uid: str):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM economy_users WHERE guild_id=? AND user_id=?", (gid, uid))
            conn.execute("DELETE FROM economy_inventory WHERE guild_id=? AND user_id=?", (gid, uid))
            conn.execute("DELETE FROM economy_active_games WHERE guild_id=? AND user_id=?", (gid, uid))


_SHARED_ECONOMY_DB: Optional[EconomyDB] = None

def get_economy_db() -> EconomyDB:
    """Returns a singleton/shared instance of EconomyDB."""
    global _SHARED_ECONOMY_DB
    if _SHARED_ECONOMY_DB is None:
        _SHARED_ECONOMY_DB = EconomyDB(DB_FILE)
    return _SHARED_ECONOMY_DB


# Interactive UI Views

class CoinDropView(discord.ui.View):
    def __init__(self, cog, gid: str, amount: int, currency_name: str, currency_emoji: str):
        super().__init__(timeout=45)
        self.cog = cog
        self.gid = gid
        self.amount = amount
        self.currency_name = currency_name
        self.currency_emoji = currency_emoji
        self.claimed = False
        self._lock = asyncio.Lock()

    @discord.ui.button(label="🪙 Grab Coin Drop!", style=discord.ButtonStyle.success)
    async def claim_drop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        async with self._lock:
            if self.claimed:
                return await interaction.followup.send("❌ Someone already claimed this drop!", ephemeral=True)
            self.claimed = True
            
        uid = str(interaction.user.id)
        user = self.cog.db.get_or_init_user(self.gid, uid)
        new_wallet = self.cog.db.delta_wallet(self.gid, uid, self.amount)
        self.cog.db.log_tx(self.gid, uid, "coin_drop", self.amount, new_wallet, note="Chat coin drop claim")
        
        button.disabled = True
        button.label = f"Claimed by {clean_display_name(interaction.user.display_name)}!"
        button.style = discord.ButtonStyle.secondary
        
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="🪙 Coin Drop!")
        embed.color = discord.Color.green()
        embed.description = f"🎉 **{interaction.user.mention}** grabbed the drop and pocketed **+{self.amount:,} {self.currency_emoji} {self.currency_name}**!"
        
        try:
            if interaction.message:
                await interaction.message.edit(embed=embed, view=self)
            else:
                await interaction.edit_original_response(embed=embed, view=self)
        except Exception:
            try:
                await interaction.edit_original_response(embed=embed, view=self)
            except Exception:
                pass


class PayConfirmView(discord.ui.View):
    def __init__(self, cog, gid: str, sender: discord.Member, target: discord.Member, gross: int, net: int, tax: int, currency_name: str, currency_emoji: str):
        super().__init__(timeout=45)
        self.cog = cog
        self.gid = gid
        self.sender = sender
        self.target = target
        self.gross = gross
        self.net = net
        self.tax = tax
        self.currency_name = currency_name
        self.currency_emoji = currency_emoji
        self.processed = False
        self._lock = asyncio.Lock()

    @discord.ui.button(label="Confirm Transfer", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.sender.id:
            return await interaction.response.send_message("❌ This confirmation prompt is not for you.", ephemeral=True)
        
        # Defer immediately so Discord's 3-second interaction window never times out!
        await interaction.response.defer()
        
        async with self._lock:
            if self.processed:
                return await interaction.followup.send("⚠️ This transfer has already been processed.", ephemeral=True)
            self.processed = True
            
        # Re-check sender balance
        sender_profile = self.cog.db.get_or_init_user(self.gid, str(self.sender.id))
        if sender_profile["wallet"] < self.gross:
            self.disable_all_items()
            await interaction.edit_original_response(view=self)
            return await interaction.followup.send(
                f"❌ Transfer cancelled: You no longer have **{self.gross:,} {self.currency_name}** in your wallet.",
                ephemeral=True
            )
            
        # Atomic deduction and credit
        s_wallet = self.cog.db.delta_wallet(self.gid, str(self.sender.id), -self.gross)
        t_wallet = self.cog.db.delta_wallet(self.gid, str(self.target.id), self.net)
        
        self.cog.db.log_tx(self.gid, str(self.sender.id), "pay_send", -self.gross, s_wallet, related_uid=str(self.target.id), note=f"Tax: {self.tax}")
        self.cog.db.log_tx(self.gid, str(self.target.id), "pay_receive", self.net, t_wallet, related_uid=str(self.sender.id), note=f"Gross: {self.gross}")
        
        self.disable_all_items()
        
        tax_rate_disp = f"{int((self.tax / self.gross) * 100)}%" if self.gross > 0 else "8%"
        embed = discord.Embed(
            title="💸 Payment Successful",
            color=discord.Color.green(),
            description=f"**{self.sender.mention}** transferred **{self.net:,} {self.currency_emoji} {self.currency_name}** to **{self.target.mention}**!"
        )
        embed.add_field(name="Gross Amount", value=f"`{self.gross:,}`", inline=True)
        embed.add_field(name=f"Server Tax ({tax_rate_disp})", value=f"`{self.tax:,}` 🔥 (Burned)", inline=True)
        embed.add_field(name="Net Received", value=f"`{self.net:,}`", inline=True)
        embed.set_footer(text="Friday Anti-Inflation Economy • Funds delivered instantly")
        
        try:
            if interaction.message:
                await interaction.message.edit(embed=embed, view=self)
            else:
                await interaction.edit_original_response(embed=embed, view=self)
        except Exception:
            try:
                await interaction.edit_original_response(embed=embed, view=self)
            except Exception:
                pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.sender.id:
            return await interaction.response.send_message("❌ This confirmation prompt is not for you.", ephemeral=True)
        await interaction.response.defer()
        self.processed = True
        self.disable_all_items()
        try:
            if interaction.message:
                await interaction.message.edit(content="❌ Transfer cancelled.", embed=None, view=self)
            else:
                await interaction.edit_original_response(content="❌ Transfer cancelled.", embed=None, view=self)
        except Exception:
            try:
                await interaction.edit_original_response(content="❌ Transfer cancelled.", embed=None, view=self)
            except Exception:
                pass


class ShopSelect(discord.ui.Select):
    def __init__(self, cog, gid: str):
        self.cog = cog
        self.gid = gid
        options = [
            discord.SelectOption(label="Defense & Utility", value="cat_defense", emoji="🛡️", description="Padlocks, Landmines, and Protection items"),
            discord.SelectOption(label="Progression & Perks", value="cat_upgrades", emoji="🏦", description="Bank Expansions, VIP Badges, Custom Colors"),
            discord.SelectOption(label="Custom Roles & Items", value="cat_custom", emoji="🎁", description="Server roles and custom catalog items"),
            discord.SelectOption(label="Casino & Mini-Games", value="cat_casino", emoji="🎲", description="Guide on /coinflip, /blackjack, and risk games")
        ]
        super().__init__(placeholder="Select a shop category to browse...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        cat = self.values[0]
        cfg = self.cog.get_config(self.gid)
        cur = cfg.get("currency_name", "Coins")
        cur_e = cfg.get("currency_emoji", "🪙")
        items = cfg.get("shop_items", DEFAULT_SHOP_ITEMS)
        
        embed = discord.Embed(color=discord.Color.teal())
        
        if cat == "cat_defense":
            embed.title = "🛡️ Shop — Defense & Utility Consumables"
            embed.description = f"Protect your hard-earned wallet coins from thieves and rivals.\nBuy with `/buy <item_id>`\n"
            for k in ["padlock", "landmine", "xp_booster"]:
                it = items.get(k, DEFAULT_SHOP_ITEMS.get(k))
                if not it or not it.get("enabled", True):
                    continue
                p = it.get("price", 0)
                em = it.get("emoji", "📦")
                embed.add_field(
                    name=f"{em} {it.get('name')} (`{k}`)",
                    value=f"**Price:** `{p:,} {cur_e} {cur}`\n{it.get('desc', '')}",
                    inline=False
                )
        elif cat == "cat_upgrades":
            embed.title = "🏦 Shop — Status & Progression Upgrades"
            embed.description = f"Permanent sinks and cosmetic bragging rights.\nBuy with `/buy <item_id>`\n"
            for k in ["bank_expansion", "custom_role_color", "vip_badge"]:
                it = items.get(k, DEFAULT_SHOP_ITEMS.get(k))
                if not it or not it.get("enabled", True):
                    continue
                p = it.get("price", 0)
                em = it.get("emoji", "⭐")
                embed.add_field(
                    name=f"{em} {it.get('name')} (`{k}`)",
                    value=f"**Price:** `{p:,} {cur_e} {cur}`\n{it.get('desc', '')}",
                    inline=False
                )
        elif cat == "cat_custom":
            embed.title = "🎁 Shop — Server Roles & Custom Store Items"
            embed.description = f"Exclusive custom roles and specialty server items.\nBuy with `/buy <item_id>`\n\n"
            custom_count = 0
            for k, it in items.items():
                if k in ("padlock", "landmine", "xp_booster", "bank_expansion", "custom_role_color", "vip_badge"):
                    continue
                if not it.get("enabled", True):
                    continue
                p = it.get("price", 0)
                em = it.get("emoji", "🎁")
                role_desc = ""
                if (it.get("type") == "role" or "role_id" in it) and it.get("role_id"):
                    role_desc = f"\n👑 **Grants Discord Role:** <@&{it['role_id']}>"
                embed.add_field(
                    name=f"{em} {it.get('name')} (`{k}`)",
                    value=f"**Price:** `{p:,} {cur_e} {cur}`{role_desc}\n{it.get('desc', 'Custom store item.')}",
                    inline=False
                )
                custom_count += 1
            if custom_count == 0:
                embed.description += "*No custom roles or store items configured yet. Server administrators can add items in the Friday Dashboard!*"
        else:
            embed.title = "🎲 Friday Casino & Mini-Games"
            embed.description = (
                "Take calculated risks to multiply your coin balance!\n\n"
                "**1. `/coinflip <heads/tails> <bet>` (or `!cf <bet> <h/t>`)**\n"
                "• 48% Win Chance with a **1.95x Payout**.\n"
                "• Fast, direct double-or-nothing coin toss.\n\n"
                "**2. `/tictactoe play @opponent [bet]`**\n"
                "• Play Tic-Tac-Toe! Beat Friday on Hard mode for a bounty, or challenge friends with a coin bet.\n\n"
                "**3. `/ludo [bet]`**\n"
                "• Authentic 4-token Ludo Royale! Defeat Friday AI for cash, or place a wager in the lobby for winner-takes-all."
            )
            
        embed.set_footer(text=f"Use /buy <item> to purchase • Currency: {cur}")
        await interaction.response.edit_message(embed=embed, view=self.view)


class ShopView(discord.ui.View):
    def __init__(self, cog, gid: str):
        super().__init__(timeout=60)
        self.add_item(ShopSelect(cog, gid))


async def shop_item_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """Autocomplete for /buy command showing all available and enabled shop items & roles."""
    gid = str(interaction.guild_id) if interaction.guild_id else ""
    cog = interaction.client.get_cog("Economy")
    cfg = cog.get_config(gid) if cog else {}
    items = cfg.get("shop_items", DEFAULT_SHOP_ITEMS)
    choices = []
    for item_id, it in items.items():
        if it.get("enabled", True):
            name = it.get("name", item_id)
            price = it.get("price", 0)
            em = it.get("emoji", "")
            is_role = (it.get("type") == "role" or "role_id" in it)
            if not em or "<:" in em or "<a:" in em:
                icon = "👑 [Role]" if is_role else "🎁"
            else:
                icon = em
            label = f"{icon} {name} ({price:,} coins)"
            if current.lower() in item_id.lower() or current.lower() in name.lower():
                choices.append(app_commands.Choice(name=label[:100], value=item_id))
    return choices[:25]


class Economy(commands.Cog):
    """
    Friday Closed-Loop Server Economy.
    Features: Passive drops, VC rewards, Robbery, Taxes, Banking, Shop, Coinflip & Blackjack.
    Fully configurable via dashboard.
    """
    def __init__(self, bot):
        self.bot = bot
        self.db = get_economy_db()
        self._user_locks: Dict[str, asyncio.Lock] = {}
        self._msg_cooldowns: Dict[str, float] = {}
        self.vc_coin_tick.start()

    def cog_unload(self):
        self.vc_coin_tick.cancel()

    def _get_lock(self, gid: str, uid: str) -> asyncio.Lock:
        key = f"{gid}:{uid}"
        if key not in self._user_locks:
            self._user_locks[key] = asyncio.Lock()
        return self._user_locks[key]

    def get_config(self, gid: str) -> dict:
        eco_cfg = getattr(db, "economy_config", {})
        cfg = eco_cfg.get(str(gid), {})
        return cfg

    def is_paused(self, gid: str) -> bool:
        """Returns True if the economy is disabled or under emergency maintenance hold."""
        cfg = self.get_config(gid)
        if not cfg.get("enabled", True):
            return True
        if cfg.get("paused", False):
            return True
        return False

    async def _check_economy_active(self, interaction: discord.Interaction) -> bool:
        """Guard check for all economy commands to block execution during emergency maintenance."""
        if not interaction.guild:
            await interaction.response.send_message("❌ Economy commands can only be used inside a server!", ephemeral=True)
            return False
        gid = str(interaction.guild.id)
        if self.is_paused(gid):
            embed = discord.Embed(
                title="⏸️ Friday's Economy is currently on hold",
                description="The server economy is currently paused by server administration.\nPlease wait until maintenance concludes.",
                color=discord.Color.orange()
            )
            embed.set_footer(text="Admin Emergency Hold Active • Friday Economy")
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
            return False
        return True

    def check_prefix_channel(self, ctx: commands.Context) -> bool:
        """
        Enforces dedicated member command channel and staff whitelist toggles.
        """
        if not ctx.guild:
            return True
        gid = str(ctx.guild.id)
        # Check if staff disabled economy prefix commands
        wl = getattr(db, "prefix_whitelist", {}).get(gid, {})
        if wl.get("commands", {}).get("economy", True) is False:
            return False
            
        # Check dedicated member command channel
        allowed_chan = getattr(db, "bot_command_channels", {}).get(gid)
        if allowed_chan and str(ctx.channel.id) != str(allowed_chan):
            perms = getattr(ctx.author, "guild_permissions", None)
            if perms and perms.administrator:
                return True
            return False
        return True

    # ───────────────────── Background Tasks & Event Listeners ─────────────────────

    @tasks.loop(minutes=5)
    async def vc_coin_tick(self):
        """Grants passive coins every 5 minutes spent in active voice channels."""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            gid = str(guild.id)
            if self.is_paused(gid):
                continue
            cfg = self.get_config(gid)
            
            reward = int(cfg.get("vc_reward_per_5min", 20))
            min_members = int(cfg.get("vc_min_members", 2))
            
            for vc in guild.voice_channels:
                eligible = [
                    m for m in vc.members 
                    if not m.bot and not m.voice.self_deaf and not m.voice.deaf
                ]
                if len(eligible) < min_members:
                    continue
                
                for m in eligible:
                    uid = str(m.id)
                    self.db.get_or_init_user(gid, uid)
                    new_w = self.db.delta_wallet(gid, uid, reward)
                    self.db.log_tx(gid, uid, "vc_reward", reward, new_w, note=f"VC: {vc.name}")

    async def spawn_coin_drop(self, guild: discord.Guild, drop_amt: Optional[int] = None, channel: Optional[discord.TextChannel] = None) -> Optional[discord.Message]:
        gid = str(guild.id)
        if self.is_paused(gid):
            return None
        cfg = self.get_config(gid)
        if not cfg.get("enabled", True):
            return None
            
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        if drop_amt is None or drop_amt <= 0:
            drop_amt = int(cfg.get("coin_drop_amount", 250))
            
        target_ch = channel
        if not target_ch:
            drop_channel_id = getattr(db, "economy_log_channels", {}).get(gid) or cfg.get("drop_channel_id")
            if drop_channel_id:
                target_ch = guild.get_channel(int(drop_channel_id))
        if not target_ch:
            cmd_chan = getattr(db, "bot_command_channels", {}).get(gid)
            if cmd_chan:
                target_ch = guild.get_channel(int(cmd_chan))
        if not target_ch:
            preferred = [c for c in guild.text_channels if any(kw in c.name.lower() for kw in ("bot", "command", "chat", "general", "lounge", "talk")) and c.permissions_for(guild.me).send_messages]
            if preferred:
                target_ch = preferred[0]
        if not target_ch:
            target_ch = guild.system_channel
        if not target_ch:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    target_ch = ch
                    break
        if not target_ch:
            return None
            
        view = CoinDropView(self, gid, drop_amt, cur_name, cur_emoji)
        embed = discord.Embed(
            title="💰 Surprise Coin Drop Event!",
            description=(
                f"A supply crate loaded with **{drop_amt:,} {cur_emoji} {cur_name}** just dropped!\n"
                f"First one to click the button claims the loot!"
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="Click fast before someone else claims it!")
        try:
            return await target_ch.send(embed=embed, view=view)
        except Exception:
            return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Passive text chat earnings + 1% Coin Drop button trigger."""
        if message.author.bot or not message.guild:
            return
        
        gid = str(message.guild.id)
        if self.is_paused(gid):
            return
            
        uid = str(message.author.id)
        cfg = self.get_config(gid)
        
        # Channel Whitelist Check (empty means ALL channels earn, selected means ONLY those earn)
        allowed_channels = getattr(db, "economy_channels", {}).get(gid, [])
        if allowed_channels and str(message.channel.id) not in [str(c) for c in allowed_channels]:
            return
        
        now = time.time()
        cd_key = f"{gid}:{uid}"
        last_chat = self._msg_cooldowns.get(cd_key, 0)
        
        # 60s silent chat cooldown
        if now - last_chat < 60:
            return
        self._msg_cooldowns[cd_key] = now
        
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        
        # 40% chance of passive coins
        earn_chance = float(cfg.get("passive_earn_chance", 0.40))
        if random.random() < earn_chance:
            min_c = int(cfg.get("passive_min", 5))
            max_c = int(cfg.get("passive_max", 15))
            earned = random.randint(min_c, max_c)
            self.db.get_or_init_user(gid, uid)
            new_w = self.db.delta_wallet(gid, uid, earned)
            self.db.log_tx(gid, uid, "chat_drop", earned, new_w, note="Passive text drop")
        
        # 1% chance of global Coin Drop button in configured drop channel
        drop_chance = float(cfg.get("coin_drop_chance", 0.01))
        if random.random() < drop_chance:
            await self.spawn_coin_drop(message.guild)

    # ───────────────────── Slash Command Groups ─────────────────────
    eco_admin = app_commands.Group(
        name="economy",
        description="Server economy administration and configuration",
        default_permissions=discord.Permissions(administrator=True)
    )
    casino_group = app_commands.Group(
        name="casino",
        description="Gambling and casino minigames"
    )

    # ───────────────────── Core Member Commands ─────────────────────

    def _build_balance_embed(self, gid: str, target: discord.Member) -> discord.Embed:
        uid = str(target.id)
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        
        profile = self.db.get_or_init_user(gid, uid, starter_bank=int(cfg.get("starter_bank", 100)), bank_max=int(cfg.get("bank_max_initial", 2500)))
        rank = self.db.get_user_rank(gid, uid)
        inventory = self.db.get_inventory(gid, uid)
        
        wallet = profile["wallet"]
        bank = profile["bank"]
        bank_max = profile["bank_max"]
        # Invariant safety: vault max must always accommodate current bank balance
        if bank > bank_max:
            bank_max = bank
            self.db.update_field(gid, uid, "bank_max", bank_max)
            
        net_worth = wallet + bank
        
        # Collect active buffs / status (strictly item-based; no free passive mode)
        buffs = []
        has_vip = False
        for item in inventory:
            iid = item["item_id"]
            qty = item["quantity"]
            exp = item["expires_at"]
            if iid == "padlock":
                buffs.append(f"🔒 **Padlock:** Equipped ({qty} held — blocks next `/rob`)")
            elif iid == "landmine":
                buffs.append(f"💣 **Landmine:** Armed ({qty} held — 50% robber blast)")
            elif iid == "xp_booster":
                if exp > time.time():
                    mins = max(1, int((exp - time.time()) / 60))
                    buffs.append(f"⚡ **2x XP Booster:** Active ({mins}m remaining)")
                elif exp == 0:
                    buffs.append(f"⚡ **2x XP Booster:** In Inventory (Use via `/use`)")
            elif iid == "vip_badge":
                has_vip = True
                
        buffs_str = "\n".join(buffs) if buffs else "*No defensive items or active boosters.*"
        
        title_str = f"👑 {clean_display_name(target.display_name)}'s Financial Dossier" if has_vip else f"💳 {clean_display_name(target.display_name)}'s Balance"
        embed = discord.Embed(title=title_str, color=discord.Color.gold() if has_vip else discord.Color.teal())
        if target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)
            
        embed.add_field(
            name=f"💵 Cash in Hand (Wallet)",
            value=f"**{wallet:,} {cur_emoji} {cur_name}**\n*(Vulnerable to `/rob`!)*",
            inline=True
        )
        embed.add_field(
            name=f"🏦 Vault (Bank Storage)",
            value=f"**{bank:,} / {bank_max:,} {cur_emoji}**\n*(100% Protected)*",
            inline=True
        )
        embed.add_field(
            name="💎 Net Worth",
            value=f"**{net_worth:,} {cur_emoji} {cur_name}**\nServer Standing: **#{rank}**",
            inline=True
        )
        embed.add_field(name="🛡️ Active Protection & Defense Items", value=buffs_str, inline=False)
        embed.set_footer(text=f"Deposit wallet cash via /deposit • Safe bank vault capacity: {bank_max:,}")
        return embed

    @app_commands.command(name="balance", description="Check your cash wallet, secure bank vault, rank, and active buffs.")
    @app_commands.describe(user="The member whose balance you want to view.")
    async def balance(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if not await self._check_economy_active(interaction):
            return
        target = user or interaction.user
        gid = str(interaction.guild.id)
        embed = self._build_balance_embed(gid, target)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="wallet", description="Quick shortcut to check your cash wallet and vault balance.")
    @app_commands.describe(user="The member whose wallet you want to view.")
    async def wallet(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if not await self._check_economy_active(interaction):
            return
        target = user or interaction.user
        gid = str(interaction.guild.id)
        embed = self._build_balance_embed(gid, target)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="wallet", aliases=["bal", "balance", "bank"])
    async def prefix_balance(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        gid = str(ctx.guild.id)
        cfg = self.get_config(gid)
        if not cfg.get("enabled", True) or cfg.get("paused", False):
            return await ctx.send("⏸️ The server economy is currently on hold.")
        target = user or ctx.author
        embed = self._build_balance_embed(gid, target)
        await ctx.send(embed=embed)

    @app_commands.command(name="deposit", description="Transfer cash from your vulnerable wallet to your safe bank vault.")
    @app_commands.describe(amount="Amount to deposit, or type 'all' / 'max'.")
    async def deposit(self, interaction: discord.Interaction, amount: str):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        
        # Anti-dupe: block deposit mid-game
        active_game = self.db.get_active_game(gid, uid)
        if active_game:
            return await interaction.response.send_message(
                "🎰 You cannot deposit while an interactive casino game is active! Finish your hand first.",
                ephemeral=True
            )
            
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            wallet = profile["wallet"]
            
            if amount.lower() in ("all", "max"):
                amt = wallet
            else:
                try:
                    amt = int(amount)
                except ValueError:
                    return await interaction.response.send_message("❌ Please enter a valid number or 'all'.", ephemeral=True)
                
            success, new_w, new_b, msg = self.db.transfer_wallet_to_bank(gid, uid, amt)
            if not success:
                return await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
            
            cfg = self.get_config(gid)
            cur_name = cfg.get("currency_name", "Coins")
            cur_emoji = cfg.get("currency_emoji", "🪙")
            
            embed = discord.Embed(title="🏦 Bank Deposit Successful", color=discord.Color.green(), description=msg)
            embed.add_field(name="Wallet Cash", value=f"`{new_w:,} {cur_emoji}`", inline=True)
            embed.add_field(name="Vault Bank", value=f"`{new_b:,} / {profile['bank_max']:,} {cur_emoji}`", inline=True)
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="withdraw", description="Withdraw coins from your bank vault into your wallet.")
    @app_commands.describe(amount="Amount to withdraw, or type 'all' / 'max'.")
    async def withdraw(self, interaction: discord.Interaction, amount: str):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            bank = profile["bank"]
            
            if amount.lower() in ("all", "max"):
                amt = bank
            else:
                try:
                    amt = int(amount)
                except ValueError:
                    return await interaction.response.send_message("❌ Please enter a valid number or 'all'.", ephemeral=True)
                
            success, new_w, new_b, msg = self.db.transfer_bank_to_wallet(gid, uid, amt)
            if not success:
                return await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
            
            cfg = self.get_config(gid)
            cur_name = cfg.get("currency_name", "Coins")
            cur_emoji = cfg.get("currency_emoji", "🪙")
            
            embed = discord.Embed(title="💵 Bank Withdrawal Complete", color=discord.Color.teal(), description=msg)
            embed.add_field(name="Wallet Cash", value=f"`{new_w:,} {cur_emoji}`", inline=True)
            embed.add_field(name="Vault Bank", value=f"`{new_b:,} / {profile['bank_max']:,} {cur_emoji}`", inline=True)
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="bank_upgrade", description="Expand your bank vault capacity by burning wallet cash.")
    async def bank_upgrade(self, interaction: discord.Interaction):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        
        cfg = self.get_config(gid)
        cost = int(cfg.get("bank_upgrade_cost", 1500))
        increase = int(cfg.get("bank_upgrade_increase", 2500))
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        
        async with self._get_lock(gid, uid):
            success, new_w, new_max, msg = self.db.upgrade_bank(gid, uid, cost, increase)
            if not success:
                return await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
            
            embed = discord.Embed(title="🏦 Vault Upgrade Purchased!", color=discord.Color.gold(), description=msg)
            embed.add_field(name="Cost Burned", value=f"`-{cost:,} {cur_emoji}`", inline=True)
            embed.add_field(name="New Capacity", value=f"`{new_max:,} {cur_emoji}`", inline=True)
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Claim your daily login reward and build a 7-day streak!")
    async def daily(self, interaction: discord.Interaction):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        
        base = int(cfg.get("daily_base", 250))
        bonus = int(cfg.get("daily_streak_bonus", 50))
        max_streak = int(cfg.get("daily_streak_max_days", 7))
        
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            now = time.time()
            last = profile["last_daily"]
            hours_since = (now - last) / 3600
            
            if hours_since < 24:
                rem_h = int(24 - hours_since)
                rem_m = int(((24 - hours_since) % 1) * 60)
                return await interaction.response.send_message(
                    f"⏳ Daily reward on cooldown! Return in **{rem_h}h {rem_m}m** to claim your next bonus.",
                    ephemeral=True
                )
                
            streak = profile["streak"]
            if 24 <= hours_since <= 48:
                streak = (streak % max_streak) + 1
            else:
                streak = 1  # Reset if more than 48 hours passed
                
            reward = base + (bonus * (streak - 1))
            new_w = self.db.delta_wallet(gid, uid, reward)
            self.db.update_field(gid, uid, "last_daily", now)
            self.db.update_field(gid, uid, "streak", streak)
            self.db.log_tx(gid, uid, "daily", reward, new_w, note=f"Streak day {streak}")
            
            embed = discord.Embed(
                title="🎁 Daily Login Bonus Claimed!",
                color=discord.Color.gold(),
                description=f"You pocketed **+{reward:,} {cur_emoji} {cur_name}** directly into your cash wallet!"
            )
            embed.add_field(name="🔥 Daily Streak", value=f"**Day {streak} / {max_streak}**", inline=True)
            embed.add_field(name="Current Wallet", value=f"`{new_w:,} {cur_emoji}`", inline=True)
            embed.set_footer(text="Claim again in 24 to 48 hours to maintain your streak bonus!")
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="work", description="Do an hourly job prompt to earn clean money.")
    async def work(self, interaction: discord.Interaction):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        cd_min = int(cfg.get("work_cooldown_minutes", 60))
        
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            now = time.time()
            elapsed_m = (now - profile["last_work"]) / 60
            
            if elapsed_m < cd_min:
                rem_m = int(cd_min - elapsed_m)
                rem_s = int(((cd_min - elapsed_m) % 1) * 60)
                return await interaction.response.send_message(
                    f"☕ You are tired from your last shift! Come back to work in **{rem_m}m {rem_s}s**.",
                    ephemeral=True
                )
                
            prompt, p_min, p_max = random.choice(WORK_PROMPTS)
            w_min = int(cfg.get("work_min", p_min))
            w_max = int(cfg.get("work_max", p_max))
            reward = random.randint(min(w_min, w_max), max(w_min, w_max))
            
            new_w = self.db.delta_wallet(gid, uid, reward)
            self.db.update_field(gid, uid, "last_work", now)
            self.db.log_tx(gid, uid, "work", reward, new_w, note=prompt)
            
            embed = discord.Embed(title="💼 Work Shift Complete", color=discord.Color.teal(), description=f"{prompt}\n\nYou earned **+{reward:,} {cur_emoji} {cur_name}**!")
            embed.set_footer(text=f"Wallet: {new_w:,} coins • Cooldown: {cd_min} minutes")
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="crime", description="High-risk, high-reward illegal activity with risk of police fine.")
    async def crime(self, interaction: discord.Interaction):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        cd_min = int(cfg.get("crime_cooldown_minutes", 30))
        success_pct = int(cfg.get("crime_success_pct", 55))
        
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            now = time.time()
            elapsed_m = (now - profile["last_crime"]) / 60
            
            if elapsed_m < cd_min:
                rem_m = int(cd_min - elapsed_m)
                rem_s = int(((cd_min - elapsed_m) % 1) * 60)
                return await interaction.response.send_message(
                    f"🚨 Heat is too high! Wait for the cops to cool off in **{rem_m}m {rem_s}s**.",
                    ephemeral=True
                )
                
            self.db.update_field(gid, uid, "last_crime", now)
            
            if random.randint(1, 100) <= success_pct:
                c_min = int(cfg.get("crime_earn_min", 300))
                c_max = int(cfg.get("crime_earn_max", 600))
                earned = random.randint(min(c_min, c_max), max(c_min, c_max))
                new_w = self.db.delta_wallet(gid, uid, earned)
                self.db.log_tx(gid, uid, "crime_success", earned, new_w)
                
                embed = discord.Embed(
                    title="🕶️ Heist Successful!",
                    color=discord.Color.green(),
                    description=f"{random.choice(CRIME_SUCCESS_PROMPTS)}\n\nYou got away with **+{earned:,} {cur_emoji} {cur_name}**!"
                )
                embed.set_footer(text=f"Wallet: {new_w:,} coins • Hide it in the bank before someone robs you!")
            else:
                fine = int(cfg.get("crime_fail_fine", 200))
                new_w = self.db.delta_wallet(gid, uid, -fine)
                self.db.log_tx(gid, uid, "crime_fail", -fine, new_w)
                
                embed = discord.Embed(
                    title="🚔 Busted by Police!",
                    color=discord.Color.red(),
                    description=f"{random.choice(CRIME_FAIL_PROMPTS)}\n\nYou paid a police fine of **-{fine:,} {cur_emoji} {cur_name}**!"
                )
                embed.set_footer(text=f"Wallet: {new_w:,} coins • Practice your skills next time.")
                
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rob", description="Attempt a PvP heist against another member's vulnerable cash wallet.")
    @app_commands.describe(target="The member you want to steal from.")
    async def rob(self, interaction: discord.Interaction, target: discord.Member):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        t_id = str(target.id)
        
        if uid == t_id:
            return await interaction.response.send_message("❌ You cannot rob yourself.", ephemeral=True)
        if target.bot:
            return await interaction.response.send_message("❌ Bots have military-grade encryption and cannot be robbed.", ephemeral=True)
        
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        cd_hours = float(cfg.get("rob_cooldown_hours", 2))
        min_robber = int(cfg.get("rob_min_robber_wallet", 500))
        min_target = int(cfg.get("rob_min_victim_wallet", 500))
        
        async with self._get_lock(gid, uid):
            robber = self.db.get_or_init_user(gid, uid)
            victim = self.db.get_or_init_user(gid, t_id)
            
            # Cooldown check
            now = time.time()
            if now - robber["last_rob"] < cd_hours * 3600:
                rem_h = (cd_hours * 3600 - (now - robber["last_rob"])) / 3600
                return await interaction.response.send_message(
                    f"⏳ Robbery cooldown active! You can plan another heist in **{rem_h:.1f} hours**.",
                    ephemeral=True
                )
                
            # Pre-flight checks
            if robber["wallet"] < min_robber:
                return await interaction.response.send_message(
                    f"❌ You need at least **{min_robber:,} {cur_emoji} {cur_name}** in your cash wallet to stage a heist!",
                    ephemeral=True
                )
            if victim["wallet"] < min_target:
                return await interaction.response.send_message(
                    f"❌ **{clean_display_name(target.display_name)}** only has **{victim['wallet']:,} {cur_name}** in their wallet. Not worth the risk!",
                    ephemeral=True
                )
                
            self.db.update_field(gid, uid, "last_rob", now)
            
            # 1. Padlock Defense Check
            if self.db.consume_item(gid, t_id, "padlock", 1):
                fine = int(cfg.get("padlock_fine", 250))
                r_w = self.db.delta_wallet(gid, uid, -fine)
                v_w = self.db.delta_wallet(gid, t_id, fine)
                self.db.log_tx(gid, uid, "rob_padlock_fine", -fine, r_w, related_uid=t_id)
                self.db.log_tx(gid, t_id, "rob_padlock_received", fine, v_w, related_uid=uid)
                
                embed = discord.Embed(
                    title="🔒 Robbery Failed — Padlock Shattered!",
                    color=discord.Color.red(),
                    description=(
                        f"**{interaction.user.mention}** tried to rob **{target.mention}**, but triggered their heavy **Padlock**!\n\n"
                        f"💥 The padlock shattered upon impact.\n"
                        f"💸 The robber was fined **{fine:,} {cur_emoji} {cur_name}** paid directly to the victim!"
                    )
                )
                return await interaction.response.send_message(embed=embed)
                
            # 2. Landmine Defense Check (50% detonation chance)
            landmine = self.db.get_item(gid, t_id, "landmine")
            if landmine and landmine["quantity"] > 0 and random.random() < 0.50:
                self.db.consume_item(gid, t_id, "landmine", 1)
                mult = int(cfg.get("landmine_fine_multiplier", 2))
                fail_pct = float(cfg.get("rob_fail_fine_pct", 0.20))
                total_fine = max(100, int(robber["wallet"] * fail_pct * mult))
                
                r_w = self.db.delta_wallet(gid, uid, -total_fine)
                embed = discord.Embed(
                    title="💣 BOOM! Landmine Detonated!",
                    color=discord.Color.dark_red(),
                    description=(
                        f"**{interaction.user.mention}** stepped directly on **{target.mention}**'s hidden **Landmine**!\n\n"
                        f"💥 The blast destroyed the heist gear!\n"
                        f"💸 Medical & hazard fines cost the robber **{total_fine:,} {cur_emoji} {cur_name}**!"
                    )
                )
                return await interaction.response.send_message(embed=embed)
                
            # 3. Roll Heist Success (Default 40%)
            success_rate = float(cfg.get("rob_success_chance", 0.40))
            if random.random() < success_rate:
                min_pct = float(cfg.get("rob_steal_min_pct", 0.15))
                max_pct = float(cfg.get("rob_steal_max_pct", 0.35))
                steal_pct = random.uniform(min_pct, max_pct)
                
                # Re-read victim's current wallet
                v_curr = self.db.get_user(gid, t_id)["wallet"]
                stolen = max(1, int(v_curr * steal_pct))
                
                v_w = self.db.delta_wallet(gid, t_id, -stolen)
                r_w = self.db.delta_wallet(gid, uid, stolen)
                
                self.db.log_tx(gid, uid, "rob_success", stolen, r_w, related_uid=t_id)
                self.db.log_tx(gid, t_id, "robbed", -stolen, v_w, related_uid=uid)
                
                embed = discord.Embed(
                    title="🥷 Clean Getaway! Heist Successful",
                    color=discord.Color.green(),
                    description=(
                        f"**{interaction.user.mention}** successfully pickpocketed **{target.mention}**!\n\n"
                        f"💰 Loot Stolen: **{stolen:,} {cur_emoji} {cur_name}** ({int(steal_pct*100)}% of their wallet)!"
                    )
                )
                embed.set_footer(text=f"Victim wallet: {v_w:,} • Robber wallet: {r_w:,}")
                await interaction.response.send_message(embed=embed)
            else:
                fail_pct = float(cfg.get("rob_fail_fine_pct", 0.20))
                r_curr = self.db.get_user(gid, uid)["wallet"]
                fine = max(50, int(r_curr * fail_pct))
                to_victim = fine // 2
                burned = fine - to_victim
                
                r_w = self.db.delta_wallet(gid, uid, -fine)
                v_w = self.db.delta_wallet(gid, t_id, to_victim)
                
                self.db.log_tx(gid, uid, "rob_failed", -fine, r_w, related_uid=t_id, note=f"Burned: {burned}")
                self.db.log_tx(gid, t_id, "rob_compensation", to_victim, v_w, related_uid=uid)
                
                embed = discord.Embed(
                    title="🚔 Heist Busted! Caught Red-Handed",
                    color=discord.Color.red(),
                    description=(
                        f"**{interaction.user.mention}** botched the robbery on **{target.mention}**!\n\n"
                        f"💸 Fine Assessed: **{fine:,} {cur_emoji} {cur_name}**\n"
                        f"• **{to_victim:,}** paid directly to victim as restitution.\n"
                        f"• **{burned:,}** permanently burned by Friday as server fine."
                    )
                )
                embed.set_footer(text="Crime doesn't pay without a plan.")
                await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pay", description="Transfer wallet coins to another member with flat 8% server anti-inflation tax.")
    @app_commands.describe(target="Member receiving the coins.", amount="Number of coins to send.")
    async def pay(self, interaction: discord.Interaction, target: discord.Member, amount: int):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        sender_id = str(interaction.user.id)
        target_id = str(target.id)
        
        if sender_id == target_id:
            return await interaction.response.send_message("❌ You cannot send coins to yourself.", ephemeral=True)
        if target.bot:
            return await interaction.response.send_message("❌ Bots cannot hold an economy profile.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Transfer amount must be greater than zero.", ephemeral=True)
            
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        tax_pct = float(cfg.get("pay_tax_pct", 0.08))
        
        user = self.db.get_or_init_user(gid, sender_id)
        if user["wallet"] < amount:
            return await interaction.response.send_message(
                f"❌ Insufficient funds: You only have **{user['wallet']:,} {cur_name}** in your cash wallet.",
                ephemeral=True
            )
            
        tax = int(amount * tax_pct)
        net = amount - tax
        
        view = PayConfirmView(self, gid, interaction.user, target, amount, net, tax, cur_name, cur_emoji)
        embed = discord.Embed(
            title="💸 Confirm Coin Transfer",
            color=discord.Color.gold(),
            description=(
                f"You are about to transfer **{amount:,} {cur_emoji} {cur_name}** to **{target.mention}**.\n\n"
                f"• **Server Anti-Inflation Tax (8%):** `-{tax:,} {cur_name}` 🔥 (Permanently Burned)\n"
                f"• **Recipient Receives:** `+{net:,} {cur_name}`\n\n"
                f"*Please confirm or cancel this transfer below:*"
            )
        )
        embed.set_footer(text="Taxes protect the server economy against multi-account funnels.")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="shop", description="Open the Friday Server Shop to browse and buy items.")
    async def shop(self, interaction: discord.Interaction):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        
        view = ShopView(self, gid)
        embed = discord.Embed(
            title="🛒 Friday Server Shop",
            color=discord.Color.teal(),
            description=(
                f"Welcome to the official economy market!\n"
                f"Select a category from the dropdown menu below to view available items and upgrades.\n\n"
                f"• **Defensive Items:** Padlocks, Landmines & Shields\n"
                f"• **Progression Perks:** Bank Expansions & VIP Badges\n"
                f"• **Custom Roles & Items:** Server exclusive roles & items\n"
                f"• **Casino Games:** Risk and reward gambling\n\n"
                f"*Buy any item directly via `/buy <item_id>`.*"
            )
        )
        embed.set_footer(text=f"Server Currency: {cur_name}")
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="buy", description="Purchase an item or role from the server shop.")
    @app_commands.describe(item="Item ID or role to purchase.", quantity="Quantity to purchase (defaults to 1; roles always default to 1).")
    @app_commands.autocomplete(item=shop_item_autocomplete)
    async def buy(self, interaction: discord.Interaction, item: str, quantity: Optional[int] = 1):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        item_id = item.lower().strip()
        
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        shop_items = cfg.get("shop_items", DEFAULT_SHOP_ITEMS)
        
        item_cfg = shop_items.get(item_id, DEFAULT_SHOP_ITEMS.get(item_id))
        if not item_cfg or not item_cfg.get("enabled", True):
            return await interaction.response.send_message(f"❌ Item `{item_id}` is not available in the shop.", ephemeral=True)

        is_role = (item_cfg.get("type") == "role" or "role_id" in item_cfg) and item_cfg.get("role_id")
        if is_role:
            quantity = 1
        elif not quantity or quantity <= 0:
            quantity = 1
            
        price = int(item_cfg.get("price", 0))
        total_cost = price * quantity
        max_hold = item_cfg.get("max_hold")
        
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            if profile["wallet"] < total_cost:
                return await interaction.response.send_message(
                    f"❌ Insufficient wallet funds: You need **{total_cost:,} {cur_name}** but only have **{profile['wallet']:,}** in your cash wallet.",
                    ephemeral=True
                )
                
            cur_item = self.db.get_item(gid, uid, item_id)
            cur_qty = cur_item["quantity"] if cur_item else 0
            if max_hold and (cur_qty + quantity) > max_hold:
                return await interaction.response.send_message(
                    f"❌ You can only hold a maximum of **{max_hold}** `{item_cfg['name']}` at a time (You currently hold {cur_qty}).",
                    ephemeral=True
                )

            # 1. Special Case: Discord Role Purchase
            if is_role:
                role_id = item_cfg.get("role_id")
                role = interaction.guild.get_role(int(role_id))
                if not role:
                    return await interaction.response.send_message("❌ The assigned Discord role was deleted or no longer exists on this server.", ephemeral=True)
                
                if not interaction.guild.me.guild_permissions.manage_roles:
                    return await interaction.response.send_message("❌ Friday is missing the **Manage Roles** permission to assign roles.", ephemeral=True)
                
                if interaction.guild.me.top_role <= role:
                    return await interaction.response.send_message(
                        f"❌ Friday's highest role is lower than or equal to **@{role.name}**. Administrators must drag Friday's role higher in Server Settings.",
                        ephemeral=True
                    )
                
                if role in interaction.user.roles:
                    return await interaction.response.send_message(f"❌ You already hold the **@{role.name}** role!", ephemeral=True)
                
                # Deduct wallet
                new_w = self.db.delta_wallet(gid, uid, -total_cost)
                try:
                    await interaction.user.add_roles(role, reason=f"Purchased in Friday Economy Shop ({total_cost} {cur_name})")
                except Exception as e:
                    # Rollback wallet deduction if role grant failed
                    self.db.delta_wallet(gid, uid, total_cost)
                    return await interaction.response.send_message(f"❌ Failed to assign role: {e}. Coins have been refunded to your wallet.", ephemeral=True)
                    
                self.db.add_item(gid, uid, item_id, 1)
                self.db.log_tx(gid, uid, "shop_buy_role", -total_cost, new_w, note=f"Role: @{role.name}")
                
                embed_color = role.color if role.color and role.color.value != 0 else discord.Color.purple()
                embed = discord.Embed(
                    title="🎉 Role Purchase Successful!",
                    color=embed_color,
                    description=f"Congratulations {interaction.user.mention}!\nYou purchased the **@{role.name}** role for **{total_cost:,} {cur_emoji} {cur_name}**!\nThe role has been assigned to your profile."
                )
                embed.add_field(name="Wallet Remaining", value=f"`{new_w:,} {cur_emoji}`", inline=True)
                embed.set_footer(text="Friday Economy Marketplace")
                return await interaction.response.send_message(embed=embed)
                embed.add_field(name="Wallet Remaining", value=f"`{new_w:,} {cur_emoji}`", inline=True)
                embed.set_footer(text="Friday Economy Marketplace")
                return await interaction.response.send_message(embed=embed)
                
            # 2. Special Case: Bank Vault Expansion Pass
            elif item_id == "bank_expansion":
                new_w = self.db.delta_wallet(gid, uid, -total_cost)
                inc = int(item_cfg.get("bank_increase", 5000)) * quantity
                self.db.update_field(gid, uid, "bank_max", profile["bank_max"] + inc)
                self.db.log_tx(gid, uid, "shop_buy_expansion", -total_cost, new_w, note=f"+{inc} cap")
                embed = discord.Embed(
                    title="🏦 Bank Expansion Activated!",
                    color=discord.Color.gold(),
                    description=f"Purchased **{quantity}x {item_cfg['name']}**!\nYour bank vault capacity increased by **+{inc:,}** to **{profile['bank_max'] + inc:,} Coins**!"
                )
                embed.add_field(name="Wallet Remaining", value=f"`{new_w:,} {cur_emoji}`", inline=True)
                return await interaction.response.send_message(embed=embed)

            # 3. Standard Items & Custom Perks
            else:
                new_w = self.db.delta_wallet(gid, uid, -total_cost)
                self.db.add_item(gid, uid, item_id, quantity)
                self.db.log_tx(gid, uid, "shop_buy", -total_cost, new_w, note=f"Bought {quantity}x {item_id}")
                embed = discord.Embed(
                    title="🛍️ Purchase Complete",
                    color=discord.Color.green(),
                    description=f"Purchased **{quantity}x {item_cfg.get('emoji', '📦')} {item_cfg['name']}** for **{total_cost:,} {cur_emoji} {cur_name}**!"
                )
                embed.add_field(name="Wallet Remaining", value=f"`{new_w:,} {cur_emoji}`", inline=True)
                embed.set_footer(text=f"View owned items via /inventory • Use consumable items via /use <item>")
                await interaction.response.send_message(embed=embed)

    @app_commands.command(name="use", description="Activate or consume an item from your inventory.")
    @app_commands.describe(item="The ID of the item to use (e.g. xp_booster).")
    async def use(self, interaction: discord.Interaction, item: str):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        item_id = item.lower().strip()
        
        async with self._get_lock(gid, uid):
            owned = self.db.get_item(gid, uid, item_id)
            if not owned or owned["quantity"] <= 0:
                return await interaction.response.send_message(f"❌ You do not have any `{item_id}` in your inventory.", ephemeral=True)
                
            if item_id == "xp_booster":
                duration_hrs = 2
                now = time.time()
                cur_exp = owned.get("expires_at", 0)
                new_exp = (cur_exp if cur_exp > now else now) + (duration_hrs * 3600)
                
                # Consume 1 booster and update expiry
                self.db.consume_item(gid, uid, "xp_booster", 1)
                self.db.add_item(gid, uid, "xp_booster", 1, expires_at=new_exp)
                
                embed = discord.Embed(
                    title="⚡ 2x XP Booster Activated!",
                    color=discord.Color.gold(),
                    description=f"Double Chat XP is now active for **{duration_hrs} hours**!\nEvery text message you send will grant 2x leveling progression!"
                )
                return await interaction.response.send_message(embed=embed)
            elif item_id in ("padlock", "landmine"):
                return await interaction.response.send_message(
                    f"🛡️ `{item_id}` is automatically equipped as passive protection! No need to use it manually.",
                    ephemeral=True
                )
            elif item_id == "vip_badge":
                return await interaction.response.send_message(
                    "👑 VIP Badge is a permanent status symbol displayed on your `/balance` card!",
                    ephemeral=True
                )
            else:
                cfg = self.get_config(gid)
                item_cfg = cfg.get("shop_items", {}).get(item_id, {})
                if item_cfg.get("type") == "role" or "role_id" in item_cfg:
                    return await interaction.response.send_message(f"👑 This role item was assigned to you upon purchase and is active!", ephemeral=True)
                return await interaction.response.send_message(f"ℹ️ Item `{item_id}` is stored in your personal inventory.", ephemeral=True)

    @app_commands.command(name="inventory", description="View items, boosters, and defense gear in your inventory.")
    @app_commands.describe(user="The member whose inventory you want to view.")
    async def inventory(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if not await self._check_economy_active(interaction):
            return
        target = user or interaction.user
        gid = str(interaction.guild.id)
        uid = str(target.id)
        
        items = self.db.get_inventory(gid, uid)
        cfg = self.get_config(gid)
        shop_cfg = cfg.get("shop_items", DEFAULT_SHOP_ITEMS)
        
        embed = discord.Embed(title=f"🎒 {clean_display_name(target.display_name)}'s Inventory", color=discord.Color.teal())
        if target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)
            
        if not items:
            embed.description = "Your inventory is currently empty! Browse the store using `/shop`."
        else:
            for it in items:
                iid = it["item_id"]
                qty = it["quantity"]
                exp = it["expires_at"]
                
                meta = shop_cfg.get(iid, DEFAULT_SHOP_ITEMS.get(iid, {}))
                em = meta.get("emoji", "📦")
                name = meta.get("name", iid.title())
                
                detail = f"Quantity: **{qty}**"
                if exp > time.time():
                    mins = int((exp - time.time()) / 60)
                    detail += f" • Active ({mins}m left)"
                embed.add_field(name=f"{em} {name}", value=detail, inline=True)
                
        embed.set_footer(text="Purchase more items at /shop • Use items via /use <item>")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="baltop", description="View the server's wealthiest members by Net Worth.")
    async def baltop(self, interaction: discord.Interaction):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        top = self.db.get_top_users(gid, limit=10)
        
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        
        if not top:
            return await interaction.response.send_message("No members have recorded any economy balance yet!", ephemeral=True)
            
        embed = discord.Embed(title="🏆 Server Wealth Leaderboard", color=discord.Color.gold())
        medals = ["🥇", "🥈", "🥉"]
        
        for idx, row in enumerate(top, start=1):
            m_id = int(row["user_id"])
            member = interaction.guild.get_member(m_id)
            name = clean_display_name(member.display_name) if member else f"User {m_id}"
            
            icon = medals[idx - 1] if idx <= 3 else f"**#{idx}**"
            wallet = row["wallet"]
            bank = row["bank"]
            net = row["net_worth"]
            
            embed.add_field(
                name=f"{icon} {name}",
                value=f"💎 **{net:,} {cur_emoji}** (Cash: `{wallet:,}` | Vault: `{bank:,}`)",
                inline=False
            )
            
        embed.set_footer(text="Leaderboard updates in real-time • Earn coins via /work, /daily, and chat drops")
        await interaction.response.send_message(embed=embed)

    # ───────────────────── Gambling & Mini-Games ─────────────────────

    @casino_group.command(name="coinflip", description="Flip a coin: 48% Win Chance with 1.95x payout.")
    @app_commands.describe(choice="Call heads or tails.", bet="Amount of coins to bet.")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails")
    ])
    async def coinflip(self, interaction: discord.Interaction, choice: app_commands.Choice[str], bet: int):
        if not await self._check_economy_active(interaction):
            return
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        
        cfg = self.get_config(gid)
        allowed_channels = cfg.get("coinflip_channels", [])
        if allowed_channels and str(interaction.channel_id) not in [str(c) for c in allowed_channels]:
            ch_mentions = ", ".join(f"<#{c}>" for c in allowed_channels)
            return await interaction.response.send_message(
                f"❌ Coinflip can only be played in: {ch_mentions}!",
                ephemeral=True
            )
            
        if bet <= 0:
            return await interaction.response.send_message("❌ Bet must be greater than zero.", ephemeral=True)
            
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        win_chance = float(cfg.get("coinflip_win_chance", 0.48))
        mult = float(cfg.get("coinflip_win_multiplier", 1.95))
        
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            if profile["wallet"] < bet:
                return await interaction.response.send_message(
                    f"❌ You only have **{profile['wallet']:,} {cur_name}** in your cash wallet!",
                    ephemeral=True
                )
                
            # Lock bet immediately
            self.db.delta_wallet(gid, uid, -bet)
            
            # Roll
            won = random.random() < win_chance
            flipped = choice.value if won else ("tails" if choice.value == "heads" else "heads")
            
            if won:
                payout = int(bet * mult)
                profit = payout - bet
                new_w = self.db.delta_wallet(gid, uid, payout)
                self.db.log_tx(gid, uid, "coinflip_win", profit, new_w)
                
                embed = discord.Embed(
                    title="🪙 Coinflip Result: WINNER!",
                    color=discord.Color.green(),
                    description=(
                        f"The coin landed on **{flipped.upper()}**!\n\n"
                        f"🎉 You won **+{payout:,} {cur_emoji} {cur_name}**!\n"
                        f"Net Profit: `+{profit:,} {cur_name}`"
                    )
                )
            else:
                new_w = self.db.get_user(gid, uid)["wallet"]
                self.db.log_tx(gid, uid, "coinflip_loss", -bet, new_w)
                
                embed = discord.Embed(
                    title="🪙 Coinflip Result: LOSS",
                    color=discord.Color.red(),
                    description=(
                        f"The coin landed on **{flipped.upper()}**.\n\n"
                        f"💔 You lost your bet of **{bet:,} {cur_emoji} {cur_name}**."
                    )
                )
            embed.set_footer(text=f"Wallet: {new_w:,} coins • Odds: 48% with 1.95x payout")
            await interaction.response.send_message(embed=embed)

    @commands.command(name="cf", aliases=["coinflip"])
    async def cmd_coinflip(self, ctx: commands.Context, arg1: str = "", arg2: str = ""):
        """Text command for quick coinflip: .cf <amount|all> <heads|tails|h|t>"""
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        gid = str(ctx.guild.id)
        uid = str(ctx.author.id)
        cfg = self.get_config(gid)
        p = ctx.prefix or "!"
        
        if not cfg.get("enabled", True):
            return
        if self.is_paused(gid):
            return await ctx.reply("⏸️ **The server economy is currently paused on emergency hold.** Please try again later!")
            
        allowed_channels = cfg.get("coinflip_channels", [])
        if allowed_channels and str(ctx.channel.id) not in [str(c) for c in allowed_channels]:
            ch_mentions = ", ".join(f"<#{c}>" for c in allowed_channels)
            return await ctx.reply(f"❌ Coinflip can only be played in: {ch_mentions}!")
            
        if not arg1 or not arg2:
            return await ctx.reply(f"🪙 **Usage:** `{p}cf <amount|all> <h|t>` (Example: `{p}cf 100 h` or `{p}cf all tails`)")
            
        choice_val = None
        bet_raw = None
        for a in [arg1.lower().strip(), arg2.lower().strip()]:
            if a in ("h", "head", "heads"):
                choice_val = "heads"
            elif a in ("t", "tail", "tails"):
                choice_val = "tails"
            else:
                bet_raw = a
                
        if not choice_val or not bet_raw:
            return await ctx.reply(f"❌ Invalid choice! Choose `heads` (`h`) or `tails` (`t`). **Usage:** `{p}cf <amount|all> <h|t>`")
            
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            wallet = profile["wallet"]
            
            if bet_raw in ("all", "max"):
                bet = wallet
            else:
                try:
                    bet = int(bet_raw)
                except ValueError:
                    return await ctx.reply("❌ Bet must be a positive integer or `all`.")
                    
            if bet <= 0:
                return await ctx.reply("❌ Bet must be greater than zero.")
            if wallet < bet:
                cur_name = cfg.get("currency_name", "Coins")
                return await ctx.reply(f"❌ You only have **{wallet:,} {cur_name}** in your cash wallet!")
                
            cur_name = cfg.get("currency_name", "Coins")
            cur_emoji = cfg.get("currency_emoji", "🪙")
            win_chance = float(cfg.get("coinflip_win_chance", 0.48))
            mult = float(cfg.get("coinflip_win_multiplier", 1.95))
            
            self.db.delta_wallet(gid, uid, -bet)
            won = random.random() < win_chance
            flipped = choice_val if won else ("tails" if choice_val == "heads" else "heads")
            
            if won:
                payout = int(bet * mult)
                profit = payout - bet
                new_w = self.db.delta_wallet(gid, uid, payout)
                self.db.log_tx(gid, uid, "coinflip_win", profit, new_w)
                
                embed = discord.Embed(
                    title="🪙 Coinflip Result: WINNER!",
                    color=discord.Color.green(),
                    description=(
                        f"The coin landed on **{flipped.upper()}**!\n\n"
                        f"🎉 {ctx.author.mention} won **+{payout:,} {cur_emoji} {cur_name}**!\n"
                        f"Net Profit: `+{profit:,} {cur_name}`"
                    )
                )
            else:
                new_w = self.db.get_user(gid, uid)["wallet"]
                self.db.log_tx(gid, uid, "coinflip_loss", -bet, new_w)
                
                embed = discord.Embed(
                    title="🪙 Coinflip Result: LOSS",
                    color=discord.Color.red(),
                    description=(
                        f"The coin landed on **{flipped.upper()}**.\n\n"
                        f"💔 {ctx.author.mention} lost their bet of **{bet:,} {cur_emoji} {cur_name}**."
                    )
                )
            embed.set_footer(text=f"Wallet: {new_w:,} coins • Odds: 48% with 1.95x payout")
            await ctx.reply(embed=embed)

    # ───────────────────── Member Economy Prefix Commands ─────────────────────

    @commands.command(name="daily")
    async def prefix_daily(self, ctx: commands.Context):
        """Claim daily login bonus via prefix."""
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        gid = str(ctx.guild.id)
        uid = str(ctx.author.id)
        cfg = self.get_config(gid)
        if not cfg.get("enabled", True) or cfg.get("paused", False):
            return await ctx.send("⏸️ The server economy is currently on hold.")
            
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        base = int(cfg.get("daily_base", 250))
        bonus = int(cfg.get("daily_streak_bonus", 50))
        max_streak = int(cfg.get("daily_streak_max_days", 7))
        
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            now = time.time()
            last = profile["last_daily"]
            hours_since = (now - last) / 3600
            
            if hours_since < 24:
                rem_h = int(24 - hours_since)
                rem_m = int(((24 - hours_since) % 1) * 60)
                return await ctx.send(f"⏳ Daily reward on cooldown! Return in **{rem_h}h {rem_m}m**.")
                
            streak = profile["streak"]
            if 24 <= hours_since <= 48:
                streak = (streak % max_streak) + 1
            else:
                streak = 1
                
            reward = base + (bonus * (streak - 1))
            new_w = self.db.delta_wallet(gid, uid, reward)
            self.db.update_field(gid, uid, "last_daily", now)
            self.db.update_field(gid, uid, "streak", streak)
            self.db.log_tx(gid, uid, "daily", reward, new_w, note=f"Streak day {streak}")
            
            embed = discord.Embed(
                title="🎁 Daily Login Bonus Claimed!",
                color=discord.Color.gold(),
                description=f"You collected **+{reward:,} {cur_name}** {cur_emoji}!\n🔥 **Daily Streak:** `{streak}/{max_streak} Days`\n💰 **Wallet:** `{new_w:,} {cur_name}`"
            )
            await ctx.send(embed=embed)

    @commands.command(name="work")
    async def prefix_work(self, ctx: commands.Context):
        """Earn salary by completing hourly server jobs."""
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        gid = str(ctx.guild.id)
        uid = str(ctx.author.id)
        cfg = self.get_config(gid)
        if not cfg.get("enabled", True) or cfg.get("paused", False):
            return await ctx.send("⏸️ The server economy is currently on hold.")
            
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        min_p = int(cfg.get("work_min", 50))
        max_p = int(cfg.get("work_max", 150))
        cd = int(cfg.get("work_cooldown_min", 60)) * 60
        
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            now = time.time()
            elapsed = now - profile["last_work"]
            if elapsed < cd:
                rem = int((cd - elapsed) / 60)
                return await ctx.send(f"⏳ You are exhausted! Rest for **{rem}m** before working again.")
                
            payout = random.randint(min_p, max_p)
            new_w = self.db.delta_wallet(gid, uid, payout)
            self.db.update_field(gid, uid, "last_work", now)
            self.db.log_tx(gid, uid, "work", payout, new_w)
            
            scenarios = [
                f"You worked as a Discord moderator and earned **+{payout:,} {cur_name}** {cur_emoji}!",
                f"You fixed server bugs and were rewarded **+{payout:,} {cur_name}** {cur_emoji}!",
                f"You hosted a server event and earned **+{payout:,} {cur_name}** {cur_emoji}!",
                f"You designed custom server banners and received **+{payout:,} {cur_name}** {cur_emoji}!"
            ]
            embed = discord.Embed(
                title="💼 Shift Completed!",
                color=discord.Color.green(),
                description=f"{random.choice(scenarios)}\n💰 **Wallet:** `{new_w:,} {cur_name}`"
            )
            await ctx.send(embed=embed)

    @commands.command(name="dep", aliases=["deposit"])
    async def prefix_deposit(self, ctx: commands.Context, amount: str = ""):
        """Transfer cash to safe bank vault: .dep <amount|all>"""
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        gid = str(ctx.guild.id)
        uid = str(ctx.author.id)
        cfg = self.get_config(gid)
        p = ctx.prefix or "!"
        if not amount:
            return await ctx.send(f"🪙 **Usage:** `{p}dep <amount|all>`")
            
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        
        # Anti-dupe: block deposit mid-game
        active_game = self.db.get_active_game(gid, uid)
        if active_game:
            return await ctx.send("🎰 You cannot deposit while an interactive casino game is active! Finish your hand first.")
            
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            wallet = profile["wallet"]
            
            if amount.lower() in ("all", "max"):
                amt = wallet
            else:
                try:
                    amt = int(amount)
                except ValueError:
                    return await ctx.send("❌ Please enter a valid number or `all`.")
                    
            success, new_w, new_b, msg = self.db.transfer_wallet_to_bank(gid, uid, amt)
            if not success:
                return await ctx.send(f"❌ {msg}")
                
            embed = discord.Embed(title="🏦 Bank Deposit Successful", color=discord.Color.green(), description=msg)
            embed.add_field(name="Wallet Cash", value=f"`{new_w:,} {cur_emoji}`", inline=True)
            embed.add_field(name="Vault Bank", value=f"`{new_b:,} / {profile['bank_max']:,} {cur_emoji}`", inline=True)
            await ctx.send(embed=embed)

    @commands.command(name="with", aliases=["withdraw"])
    async def prefix_withdraw(self, ctx: commands.Context, amount: str = ""):
        """Withdraw cash from bank vault: .with <amount|all>"""
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        gid = str(ctx.guild.id)
        uid = str(ctx.author.id)
        cfg = self.get_config(gid)
        p = ctx.prefix or "!"
        if not amount:
            return await ctx.send(f"🪙 **Usage:** `{p}with <amount|all>`")
            
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        
        async with self._get_lock(gid, uid):
            profile = self.db.get_or_init_user(gid, uid)
            bank = profile["bank"]
            
            if amount.lower() in ("all", "max"):
                amt = bank
            else:
                try:
                    amt = int(amount)
                except ValueError:
                    return await ctx.send("❌ Please enter a valid number or `all`.")
                    
            success, new_w, new_b, msg = self.db.transfer_bank_to_wallet(gid, uid, amt)
            if not success:
                return await ctx.send(f"❌ {msg}")
                
            embed = discord.Embed(title="💸 Bank Withdrawal Successful", color=discord.Color.green(), description=msg)
            embed.add_field(name="Wallet Cash", value=f"`{new_w:,} {cur_emoji}`", inline=True)
            embed.add_field(name="Vault Bank", value=f"`{new_b:,} / {profile['bank_max']:,} {cur_emoji}`", inline=True)
            await ctx.send(embed=embed)

    @commands.command(name="pay", aliases=["give"])
    async def prefix_pay(self, ctx: commands.Context, member: Optional[discord.Member] = None, amount: Optional[int] = None):
        """Transfer cash to another player: .pay @user <amount>"""
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        p = ctx.prefix or "!"
        if not member or amount is None:
            return await ctx.send(f"💸 **Usage:** `{p}pay @user <amount>`")
        if member.id == ctx.author.id:
            return await ctx.send("❌ You cannot send coins to yourself.")
        if member.bot:
            return await ctx.send("❌ Bots cannot hold an economy profile.")
        if amount <= 0:
            return await ctx.send("❌ Transfer amount must be greater than zero.")
            
        gid = str(ctx.guild.id)
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        tax_pct = float(cfg.get("pay_tax_pct", 0.08))
        
        user = self.db.get_or_init_user(gid, str(ctx.author.id))
        if user["wallet"] < amount:
            return await ctx.send(f"❌ Insufficient funds: You only have **{user['wallet']:,} {cur_name}** in your cash wallet.")
            
        tax = int(amount * tax_pct)
        net = amount - tax
        
        view = PayConfirmView(self, gid, ctx.author, member, amount, net, tax, cur_name, cur_emoji)
        tax_pct_display = int(tax_pct * 100)
        embed = discord.Embed(
            title="💸 Confirm Coin Transfer",
            color=discord.Color.gold(),
            description=(
                f"You are about to transfer **{amount:,} {cur_emoji} {cur_name}** to **{member.mention}**.\n\n"
                f"• **Server Anti-Inflation Tax ({tax_pct_display}%):** `-{tax:,} {cur_name}` 🔥 (Permanently Burned)\n"
                f"• **Recipient Receives:** `+{net:,} {cur_name}`\n\n"
                f"*Please confirm or cancel this transfer below:*"
            )
        )
        embed.set_footer(text="Taxes protect the server economy against multi-account funnels.")
        await ctx.send(embed=embed, view=view)

    @commands.command(name="drop", aliases=["coindrop"])
    async def prefix_drop(self, ctx: commands.Context, amount: Optional[int] = None):
        """Admin prefix command to manually trigger a surprise clickable coin drop."""
        if not ctx.guild:
            return
        perms = getattr(ctx.author, "guild_permissions", None)
        is_owner = (ctx.author.id == ctx.guild.owner_id)
        if not (is_owner or (perms and perms.administrator)):
            return await ctx.send("❌ Only Administrators or Server Owner can trigger coin drops.")
            
        msg = await self.spawn_coin_drop(ctx.guild, drop_amt=amount, channel=ctx.channel)
        if msg:
            try:
                await ctx.message.delete()
            except Exception:
                pass
        else:
            await ctx.send("❌ Failed to spawn coin drop. Ensure economy is enabled and Friday has permission to send embeds here.")

    @commands.command(name="rob", aliases=["steal"])
    async def prefix_rob(self, ctx: commands.Context, target: Optional[discord.Member] = None):
        """Stage a wallet heist against another player: .rob @user"""
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        p = ctx.prefix or "!"
        if not target:
            return await ctx.send(f"🥷 **Usage:** `{p}rob @user`")
        if target.id == ctx.author.id:
            return await ctx.send("❌ You cannot rob yourself.")
        if target.bot:
            return await ctx.send("❌ You cannot rob bots.")
            
        gid = str(ctx.guild.id)
        cfg = self.get_config(gid)
        if not cfg.get("rob_enabled", True):
            return await ctx.send("🛡️ Robbery is disabled in this server.")
            
        uid = str(ctx.author.id)
        tid = str(target.id)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        cooldown = int(cfg.get("rob_cooldown_min", 120)) * 60
        
        async with self._get_lock(gid, uid):
            robber = self.db.get_or_init_user(gid, uid)
            now = time.time()
            if (now - robber["last_rob"]) < cooldown:
                rem = int((cooldown - (now - robber["last_rob"])) / 60)
                return await ctx.send(f"⏳ The cops are still watching you! Wait **{rem}m** before staging another robbery.")
            if robber.get("passive", False):
                return await ctx.send("🛡️ You are in **Passive Mode**! Turn it off with `/passive` to rob others.")
            if robber["wallet"] < 100:
                return await ctx.send(f"❌ You need at least **100 {cur_name}** in your wallet to cover bail if you get caught!")
                
        async with self._get_lock(gid, tid):
            victim = self.db.get_or_init_user(gid, tid)
            if victim.get("passive", False):
                return await ctx.send(f"🛡️ **{target.display_name}** is in Passive Mode and cannot be robbed.")
            if victim["wallet"] < 100:
                return await ctx.send(f"❌ **{target.display_name}** has less than 100 {cur_name} in their wallet. Not worth the risk!")
            has_padlock = self.db.has_item(gid, tid, "padlock")
            
        self.db.update_field(gid, uid, "last_rob", now)
        if has_padlock:
            self.db.consume_item(gid, tid, "padlock")
            fine = min(robber["wallet"], 250)
            self.db.delta_wallet(gid, uid, -fine)
            return await ctx.send(f"🔒 **Robbery Blocked!** {target.display_name}'s padlock snapped shut! You were fined **{fine:,} {cur_name}** for trespassing.")
            
        chance = float(cfg.get("rob_success_rate", 0.45))
        if random.random() < chance:
            pct = random.uniform(0.15, 0.40)
            stolen = max(1, int(victim["wallet"] * pct))
            self.db.delta_wallet(gid, tid, -stolen)
            new_w = self.db.delta_wallet(gid, uid, stolen)
            await ctx.send(f"🥷 **Success!** You sneaked past {target.display_name} and stole **{stolen:,} {cur_name}** {cur_emoji}!")
        else:
            fine = min(robber["wallet"], int(victim["wallet"] * 0.20))
            self.db.delta_wallet(gid, uid, -fine)
            self.db.delta_wallet(gid, tid, fine)
            await ctx.send(f"🚨 **Busted!** You were caught red-handed and had to pay **{fine:,} {cur_name}** in compensation to {target.mention}!")

    @commands.command(name="shop", aliases=["store"])
    async def prefix_shop(self, ctx: commands.Context):
        """View active server shop catalog."""
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        gid = str(ctx.guild.id)
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        catalog = self.db.get_shop_catalog(gid)
        
        if not catalog:
            return await ctx.send("🏪 The server shop is currently empty.")
            
        lines = ["🏪 **Server Shop Catalog**\n"]
        for item in catalog:
            item_id = item.get("id", "")
            name = item.get("name", "Item")
            emoji = item.get("emoji", "📦")
            price = item.get("price", 0)
            desc = item.get("description", "")
            lines.append(f"{emoji} **{name}** (`{item_id}`) — **{price:,} {cur_name}** {cur_emoji}\n*{desc}*\n")
        lines.append(f"💡 *Purchase items with `/buy <item>`.*")
        await ctx.send("\n".join(lines))

    @commands.command(name="inv", aliases=["inventory"])
    async def prefix_inventory(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """View user inventory via prefix."""
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        target = member or ctx.author
        gid = str(ctx.guild.id)
        uid = str(target.id)
        items = self.db.get_user_inventory(gid, uid)
        
        if not items:
            return await ctx.send(f"🎒 **{target.display_name}'s Backpack is empty.** Visit `/shop` to purchase items!")
            
        catalog = {i["id"]: i for i in self.db.get_shop_catalog(gid)}
        lines = [f"🎒 **{target.display_name}'s Inventory:**\n"]
        for it in items:
            cat_item = catalog.get(it["item_id"], {})
            name = cat_item.get("name", it["item_id"])
            emoji = cat_item.get("emoji", "📦")
            qty = it.get("quantity", 1)
            lines.append(f"{emoji} **{name}** ×`{qty}`")
        await ctx.send("\n".join(lines))

    @commands.command(name="ecolb", aliases=["rich", "richest"])
    async def prefix_ecolb(self, ctx: commands.Context):
        """View top richest members leaderboard."""
        if not ctx.guild or not self.check_prefix_channel(ctx):
            return
        gid = str(ctx.guild.id)
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        users = self.db.get_guild_users(gid)
        if not users:
            return await ctx.send("📊 No player accounts found yet.")
            
        ranked = sorted(users.items(), key=lambda x: (x[1].get("wallet", 0) + x[1].get("bank", 0)), reverse=True)[:10]
        lines = [f"🏆 **Top Richest Members in {ctx.guild.name}**\n"]
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for idx, (uid, prof) in enumerate(ranked):
            tot = prof.get("wallet", 0) + prof.get("bank", 0)
            mem = ctx.guild.get_member(int(uid))
            name = mem.display_name if mem else f"User {uid[:6]}"
            lines.append(f"{medals[idx]} **{name}** — `{tot:,} {cur_name}` {cur_emoji} (Wallet: `{prof.get('wallet',0):,}` • Bank: `{prof.get('bank',0):,}`)")
        await ctx.send("\n".join(lines))

    # ───────────────────── Admin Configuration Commands ─────────────────────

    @eco_admin.command(name="setup", description="Configure or enable Friday's server economy system.")
    @app_commands.describe(
        enabled="Enable or disable the entire economy.",
        drop_channel="Channel where surprise Coin Drops will spawn.",
        starter_bank="Starting bank bonus for new members (default: 100).",
        currency_name="Name of currency (default: Coins)."
    )
    @app_commands.default_permissions(administrator=True)
    async def economy_setup(
        self,
        interaction: discord.Interaction,
        enabled: Optional[bool] = None,
        drop_channel: Optional[discord.TextChannel] = None,
        starter_bank: Optional[int] = None,
        currency_name: Optional[str] = None
    ):
        if not await ensure_admin_or_owner(interaction):
            return
            
        gid = str(interaction.guild.id)
        if gid not in db.economy_config:
            db.economy_config[gid] = {}
            
        cfg = db.economy_config[gid]
        if enabled is not None:
            cfg["enabled"] = enabled
        if starter_bank is not None:
            cfg["starter_bank"] = starter_bank
        if currency_name:
            cfg["currency_name"] = currency_name.strip()
        if drop_channel:
            db.economy_log_channels[gid] = drop_channel.id
            cfg["drop_channel_id"] = drop_channel.id
            
        db.save_data()
        
        status_str = "ENABLED ✅" if cfg.get("enabled", True) else "DISABLED ❌"
        ch_str = drop_channel.mention if drop_channel else (f"<#{cfg.get('drop_channel_id')}>" if cfg.get("drop_channel_id") else "*Current channel*")
        cur_str = cfg.get("currency_name", "Coins")
        
        embed = discord.Embed(title="⚙️ Friday Economy Configuration Updated", color=discord.Color.green())
        embed.add_field(name="Status", value=status_str, inline=True)
        embed.add_field(name="Currency Name", value=cur_str, inline=True)
        embed.add_field(name="Coin Drop Channel", value=ch_str, inline=True)
        embed.set_footer(text="All sliders and shop items can also be edited live via the Web Dashboard.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @eco_admin.command(name="drop", description="Trigger an instant clickable coin drop in a channel.")
    @app_commands.describe(
        amount="Amount of coins to drop (default from config).",
        channel="Target channel where crate drops (defaults to configured drop channel or current)."
    )
    @app_commands.default_permissions(administrator=True)
    async def economy_drop(self, interaction: discord.Interaction, amount: Optional[int] = None, channel: Optional[discord.TextChannel] = None):
        if not await ensure_admin_or_owner(interaction):
            return
        msg = await self.spawn_coin_drop(interaction.guild, drop_amt=amount, channel=channel)
        if msg:
            await interaction.response.send_message(f"✅ Spawned a surprise coin drop in {msg.channel.mention}!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Failed to spawn coin drop. Check channel send permissions or ensure economy is unpaused.", ephemeral=True)

    @eco_admin.command(name="give", description="Grant or remove coins from a member's profile.")
    @app_commands.describe(user="Target member.", amount="Coins to give (negative number to deduct).", destination="Where to deposit.")
    @app_commands.choices(destination=[
        app_commands.Choice(name="Cash Wallet", value="wallet"),
        app_commands.Choice(name="Bank Vault", value="bank")
    ])
    @app_commands.default_permissions(administrator=True)
    async def economy_give(self, interaction: discord.Interaction, user: discord.Member, amount: int, destination: app_commands.Choice[str]):
        if not await ensure_admin_or_owner(interaction):
            return
            
        gid = str(interaction.guild.id)
        uid = str(user.id)
        cfg = self.get_config(gid)
        cur_name = cfg.get("currency_name", "Coins")
        
        async with self._get_lock(gid, uid):
            self.db.get_or_init_user(gid, uid)
            if destination.value == "wallet":
                new_val = self.db.delta_wallet(gid, uid, amount)
                self.db.log_tx(gid, uid, "admin_grant_wallet", amount, new_val, related_uid=str(interaction.user.id), note="Admin give")
                dest_str = "Cash Wallet"
            else:
                new_val = self.db.delta_bank(gid, uid, amount)
                self.db.log_tx(gid, uid, "admin_grant_bank", amount, new_val, related_uid=str(interaction.user.id), note="Admin give")
                dest_str = "Bank Vault"
                
            action = "Granted" if amount >= 0 else "Deducted"
            embed = discord.Embed(
                title=f"💸 Admin Economy Adjustment",
                color=discord.Color.gold(),
                description=f"{action} **{amount:,} {cur_name}** to {user.mention}'s **{dest_str}**!\nNew Balance: **{new_val:,} {cur_name}**."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @eco_admin.command(name="reset", description="Wipe a user's economy balances, items, and stats.")
    @app_commands.describe(user="The member to reset.")
    @app_commands.default_permissions(administrator=True)
    async def economy_reset(self, interaction: discord.Interaction, user: discord.Member):
        if not await ensure_admin_or_owner(interaction):
            return
            
        gid = str(interaction.guild.id)
        uid = str(user.id)
        
        async with self._get_lock(gid, uid):
            self.db.admin_reset_user(gid, uid)
            embed = discord.Embed(
                title="🧹 Economy Profile Wiped",
                color=discord.Color.orange(),
                description=f"Successfully wiped all wallet, bank, inventory, and game data for **{user.mention}**."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @eco_admin.command(name="channels", description="Configure channels where passive chat drops are allowed.")
    @app_commands.describe(action="Add, Remove, or List allowed channels.", channel="Target channel.")
    @app_commands.choices(action=[
        app_commands.Choice(name="Add Channel", value="add"),
        app_commands.Choice(name="Remove Channel", value="remove"),
        app_commands.Choice(name="List Allowed Channels", value="list")
    ])
    @app_commands.default_permissions(administrator=True)
    async def economy_channels(self, interaction: discord.Interaction, action: app_commands.Choice[str], channel: Optional[discord.TextChannel] = None):
        if not await ensure_admin_or_owner(interaction):
            return
            
        gid = str(interaction.guild.id)
        if gid not in db.economy_channels:
            db.economy_channels[gid] = []
            
        ch_list = db.economy_channels[gid]
        
        if action.value == "list":
            if not ch_list:
                return await interaction.response.send_message("🌐 **Passive chat drops are enabled in ALL channels** (no whitelist set).", ephemeral=True)
            formatted = ", ".join(f"<#{c}>" for c in ch_list)
            return await interaction.response.send_message(f"📋 **Allowed Passive Earn Channels:** {formatted}", ephemeral=True)
            
        if not channel:
            return await interaction.response.send_message("❌ Please specify a channel.", ephemeral=True)
            
        if action.value == "add":
            if channel.id not in ch_list:
                ch_list.append(channel.id)
                db.save_data()
                await interaction.response.send_message(f"✅ Added {channel.mention} to allowed economy chat channels.", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ {channel.mention} is already in the allowed list.", ephemeral=True)
        elif action.value == "remove":
            if channel.id in ch_list:
                ch_list.remove(channel.id)
                db.save_data()
                await interaction.response.send_message(f"❌ Removed {channel.mention} from allowed economy chat channels.", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ {channel.mention} was not in the allowed list.", ephemeral=True)

    @eco_admin.command(name="pause", description="Emergency pause or resume all economy commands, chat drops, and voice rewards.")
    @app_commands.describe(action="Choose whether to pause or resume the economy.")
    @app_commands.choices(action=[
        app_commands.Choice(name="Pause Economy (Emergency Hold)", value="pause"),
        app_commands.Choice(name="Resume Economy (Active)", value="resume")
    ])
    @app_commands.default_permissions(administrator=True)
    async def economy_pause(self, interaction: discord.Interaction, action: Optional[app_commands.Choice[str]] = None):
        if not await ensure_admin_or_owner(interaction):
            return
            
        gid = str(interaction.guild.id)
        if gid not in db.economy_config:
            db.economy_config[gid] = {}
        cfg = db.economy_config[gid]
        
        cur_p = cfg.get("paused", False)
        if action:
            new_p = (action.value == "pause")
        else:
            new_p = not cur_p
            
        cfg["paused"] = new_p
        db.save_data()
        
        status_text = "PAUSED ⏸️ (Emergency Hold Active)" if new_p else "RESUMED ▶️ (Active)"
        color = discord.Color.red() if new_p else discord.Color.green()
        embed = discord.Embed(
            title="⚙️ Friday Economy Emergency State",
            description=(
                f"The server economy is now **{status_text}**.\n\n"
                f"{'⚠️ **All economy commands, faucets, chat drops, and voice rewards are currently frozen.**' if new_p else '✅ **Economy commands, faucets, and trading have resumed normal operation.**'}"
            ),
            color=color
        )
        embed.set_footer(text="Manage anytime from Discord or the Friday Web Dashboard")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Economy(bot))

