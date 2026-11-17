import discord
from discord.ext import commands
from discord import app_commands
import io
import time
import random
import asyncio
from datetime import datetime
import pytz
from typing import Optional, List, Tuple, Dict
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────────────────────
# BOARD GEOMETRY & TRACK DEFINITIONS (15x15 GRID)
# ─────────────────────────────────────────────────────────────

CELL_SIZE = 44
BOARD_SIZE = CELL_SIZE * 15  # 660 x 660 px

# Authentic 52-square Ludo track coordinates (row, col)
TRACK_COORDS: List[Tuple[int, int]] = []
# Col 6, rows 13 down to 9 (5 squares)
for r in range(13, 8, -1): TRACK_COORDS.append((r, 6))
# Row 8, cols 5 down to 0 (6 squares)
for c in range(5, -1, -1): TRACK_COORDS.append((8, c))
# Col 0, row 7 (1 square)
TRACK_COORDS.append((7, 0))
# Row 6, cols 0 up to 5 (6 squares)
for c in range(0, 6): TRACK_COORDS.append((6, c))
# Col 6, rows 5 down to 0 (6 squares)
for r in range(5, -1, -1): TRACK_COORDS.append((r, 6))
# Row 0, col 7 (1 square)
TRACK_COORDS.append((0, 7))
# Col 8, rows 0 up to 5 (6 squares)
for r in range(0, 6): TRACK_COORDS.append((r, 8))
# Row 6, cols 9 up to 14 (6 squares)
for c in range(9, 15): TRACK_COORDS.append((6, c))
# Col 14, row 7 (1 square)
TRACK_COORDS.append((7, 14))
# Row 8, cols 14 down to 9 (6 squares)
for c in range(14, 8, -1): TRACK_COORDS.append((8, c))
# Col 8, rows 9 up to 14 (6 squares)
for r in range(9, 15): TRACK_COORDS.append((r, 8))
# Row 14, col 7 (1 square)
TRACK_COORDS.append((14, 7))
# Col 6, row 14 (1 square)
TRACK_COORDS.append((14, 6))

# Safe track square indices (no captures permitted here)
SAFE_TRACK_INDICES = {0, 8, 13, 21, 26, 34, 39, 47}

# Home path coordinates (5 squares before center)
RED_HOME_PATH = [(13, 7), (12, 7), (11, 7), (10, 7), (9, 7)]
YELLOW_HOME_PATH = [(1, 7), (2, 7), (3, 7), (4, 7), (5, 7)]

# Center Home Triangle Center
RED_HOME_CENTER = (8.0, 7.0)
YELLOW_HOME_CENTER = (6.0, 7.0)

# Base (Yard) Token resting spots (row, col)
RED_BASE_SPOTS = [(10.8, 1.8), (10.8, 3.8), (12.8, 1.8), (12.8, 3.8)]
YELLOW_BASE_SPOTS = [(1.8, 10.8), (1.8, 12.8), (3.8, 10.8), (3.8, 12.8)]

# Active game session registry (user_id -> LudoGame) with 180s auto-expiry
ACTIVE_LUDO_GAMES: Dict[int, "LudoGame"] = {}


# ─────────────────────────────────────────────────────────────
# HIGH-SPEED CANVAS RENDERING ENGINE (PRE-CACHED IN RAM)
# ─────────────────────────────────────────────────────────────

def _create_base_board() -> Image.Image:
    """Pre-generates the static 15x15 Ludo board into RAM once on startup."""
    img = Image.new("RGB", (BOARD_SIZE, BOARD_SIZE), (24, 25, 28))
    d = ImageDraw.Draw(img)

    c_red = (220, 53, 69)
    c_green = (40, 167, 69)
    c_yellow = (245, 185, 15)
    c_blue = (23, 162, 184)
    c_white = (248, 249, 250)
    c_dark_line = (60, 64, 69)
    c_safe = (245, 230, 160)

    # 1. Base Yards
    d.rectangle([0, 0, CELL_SIZE * 6, CELL_SIZE * 6], fill=c_green)
    d.rectangle([CELL_SIZE, CELL_SIZE, CELL_SIZE * 5, CELL_SIZE * 5], fill=c_white)

    d.rectangle([CELL_SIZE * 9, 0, BOARD_SIZE, CELL_SIZE * 6], fill=c_yellow)
    d.rectangle([CELL_SIZE * 10, CELL_SIZE, CELL_SIZE * 14, CELL_SIZE * 5], fill=c_white)

    d.rectangle([0, CELL_SIZE * 9, CELL_SIZE * 6, BOARD_SIZE], fill=c_red)
    d.rectangle([CELL_SIZE, CELL_SIZE * 10, CELL_SIZE * 5, CELL_SIZE * 14], fill=c_white)

    d.rectangle([CELL_SIZE * 9, CELL_SIZE * 9, BOARD_SIZE, BOARD_SIZE], fill=c_blue)
    d.rectangle([CELL_SIZE * 10, CELL_SIZE * 10, CELL_SIZE * 14, CELL_SIZE * 14], fill=c_white)

    # Base resting circles
    all_bases = [
        (1.8, 1.8, c_green), (1.8, 3.8, c_green), (3.8, 1.8, c_green), (3.8, 3.8, c_green),
        (1.8, 10.8, c_yellow), (1.8, 12.8, c_yellow), (3.8, 10.8, c_yellow), (3.8, 12.8, c_yellow),
        (10.8, 1.8, c_red), (10.8, 3.8, c_red), (12.8, 1.8, c_red), (12.8, 3.8, c_red),
        (10.8, 10.8, c_blue), (10.8, 12.8, c_blue), (12.8, 10.8, c_blue), (12.8, 12.8, c_blue)
    ]
    for r, c, col in all_bases:
        x = int(c * CELL_SIZE)
        y = int(r * CELL_SIZE)
        d.ellipse([x - 17, y - 17, x + 17, y + 17], fill=col, outline=(30, 30, 30), width=2)

    # 2. Track cells
    for r in range(15):
        for c in range(15):
            in_cross = (6 <= r <= 8) or (6 <= c <= 8)
            in_center = (6 <= r <= 8) and (6 <= c <= 8)
            if in_cross and not in_center:
                x1, y1 = c * CELL_SIZE, r * CELL_SIZE
                x2, y2 = x1 + CELL_SIZE, y1 + CELL_SIZE
                d.rectangle([x1, y1, x2, y2], fill=c_white, outline=c_dark_line, width=1)

    # 3. Colored Start squares & Home columns
    # Red start (13, 6) & home column (cols 7, rows 9..13)
    d.rectangle([6 * CELL_SIZE, 13 * CELL_SIZE, 7 * CELL_SIZE, 14 * CELL_SIZE], fill=c_red, outline=c_dark_line)
    for r in range(9, 14):
        d.rectangle([7 * CELL_SIZE, r * CELL_SIZE, 8 * CELL_SIZE, (r + 1) * CELL_SIZE], fill=c_red, outline=c_dark_line)

    # Yellow start (1, 8) & home column (cols 7, rows 1..5)
    d.rectangle([8 * CELL_SIZE, 1 * CELL_SIZE, 9 * CELL_SIZE, 2 * CELL_SIZE], fill=c_yellow, outline=c_dark_line)
    for r in range(1, 6):
        d.rectangle([7 * CELL_SIZE, r * CELL_SIZE, 8 * CELL_SIZE, (r + 1) * CELL_SIZE], fill=c_yellow, outline=c_dark_line)

    # Green start (6, 1) & home column
    d.rectangle([1 * CELL_SIZE, 6 * CELL_SIZE, 2 * CELL_SIZE, 7 * CELL_SIZE], fill=c_green, outline=c_dark_line)
    for c in range(1, 6):
        d.rectangle([c * CELL_SIZE, 7 * CELL_SIZE, (c + 1) * CELL_SIZE, 8 * CELL_SIZE], fill=c_green, outline=c_dark_line)

    # Blue start (8, 13) & home column
    d.rectangle([13 * CELL_SIZE, 8 * CELL_SIZE, 14 * CELL_SIZE, 9 * CELL_SIZE], fill=c_blue, outline=c_dark_line)
    for c in range(9, 14):
        d.rectangle([c * CELL_SIZE, 7 * CELL_SIZE, (c + 1) * CELL_SIZE, 8 * CELL_SIZE], fill=c_blue, outline=c_dark_line)

    # 4. Safe Star tiles (⭐)
    stars = [(8, 2), (2, 6), (6, 12), (12, 8)]
    for r, c in stars:
        x1, y1 = c * CELL_SIZE, r * CELL_SIZE
        x2, y2 = x1 + CELL_SIZE, y1 + CELL_SIZE
        d.rectangle([x1, y1, x2, y2], fill=c_safe, outline=c_dark_line)
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        d.polygon([
            (cx, cy - 12), (cx + 3, cy - 3), (cx + 12, cy - 3), (cx + 5, cy + 3),
            (cx + 8, cy + 12), (cx, cy + 6), (cx - 8, cy + 12), (cx - 5, cy + 3),
            (cx - 12, cy - 3), (cx - 3, cy - 3)
        ], fill=(212, 175, 55))

    # 5. Center Home Triangles
    cx1, cy1 = 6 * CELL_SIZE, 6 * CELL_SIZE
    cx2, cy2 = 9 * CELL_SIZE, 9 * CELL_SIZE
    mid_x, mid_y = (cx1 + cx2) // 2, (cy1 + cy2) // 2

    d.polygon([(cx1, cy1), (cx1, cy2), (mid_x, mid_y)], fill=c_green, outline=c_dark_line)
    d.polygon([(cx1, cy1), (cx2, cy1), (mid_x, mid_y)], fill=c_yellow, outline=c_dark_line)
    d.polygon([(cx2, cy1), (cx2, cy2), (mid_x, mid_y)], fill=c_blue, outline=c_dark_line)
    d.polygon([(cx1, cy2), (cx2, cy2), (mid_x, mid_y)], fill=c_red, outline=c_dark_line)

    # Outer border
    d.rectangle([0, 0, BOARD_SIZE - 1, BOARD_SIZE - 1], outline=(40, 44, 52), width=3)
    return img

# Initialize pre-cached RAM image
_CACHED_BASE_BOARD = _create_base_board()


def get_token_xy(color: str, token_idx: int, steps: int) -> Tuple[float, float]:
    """Returns the (x, y) canvas pixel center for a token at a given step count."""
    if steps == -1:
        # In Yard Base
        r, c = RED_BASE_SPOTS[token_idx] if color == "red" else YELLOW_BASE_SPOTS[token_idx]
        return (c * CELL_SIZE, r * CELL_SIZE)

    if steps == 56:
        # Inside Center Home Triangle
        r, c = RED_HOME_CENTER if color == "red" else YELLOW_HOME_CENTER
        offset_x = (token_idx - 0.5) * 14 if token_idx in (0, 1) else (token_idx - 2.5) * 14
        offset_y = 0 if token_idx in (0, 1) else (6 if color == "red" else -6)
        return (c * CELL_SIZE + CELL_SIZE // 2 + offset_x, r * CELL_SIZE + CELL_SIZE // 2 + offset_y)

    if steps >= 51:
        # Inside Home Run Path (51..55)
        path = RED_HOME_PATH if color == "red" else YELLOW_HOME_PATH
        r, c = path[steps - 51]
        return (c * CELL_SIZE + CELL_SIZE // 2, r * CELL_SIZE + CELL_SIZE // 2)

    # Main Track (0..50)
    track_offset = 0 if color == "red" else 26
    track_idx = (track_offset + steps) % 52
    r, c = TRACK_COORDS[track_idx]
    return (c * CELL_SIZE + CELL_SIZE // 2, r * CELL_SIZE + CELL_SIZE // 2)


def render_board_image(red_tokens: List[int], yellow_tokens: List[int], tokens_per_player: int) -> io.BytesIO:
    """Renders all active tokens onto the pre-cached base board in <25ms."""
    canvas = _CACHED_BASE_BOARD.copy()
    draw = ImageDraw.Draw(canvas)

    # Collect positions to handle overlapping tokens on the same tile
    pos_map: Dict[Tuple[int, int], List[Tuple[str, int, float, float]]] = {}

    all_tokens = []
    for i in range(tokens_per_player):
        all_tokens.append(("red", i + 1, red_tokens[i]))
        all_tokens.append(("yellow", i + 1, yellow_tokens[i]))

    for col, num, steps in all_tokens:
        x, y = get_token_xy(col, num - 1, steps)
        key = (int(round(x)), int(round(y)))
        pos_map.setdefault(key, []).append((col, num, x, y))

    # Draw tokens with slight offset if multiple tokens share the exact same cell
    token_radius = 15
    for key, tokens_on_spot in pos_map.items():
        count = len(tokens_on_spot)
        for idx, (col, num, x, y) in enumerate(tokens_on_spot):
            dx, dy = 0, 0
            if count == 2:
                dx = -6 if idx == 0 else 6
                dy = -6 if idx == 0 else 6
            elif count > 2:
                angles = [(-7, -7), (7, -7), (-7, 7), (7, 7)]
                dx, dy = angles[idx % 4]

            px, py = x + dx, y + dy
            fill_color = (235, 59, 69) if col == "red" else (245, 185, 15)
            rim_color = (255, 255, 255) if col == "red" else (30, 30, 30)
            text_color = (255, 255, 255) if col == "red" else (20, 20, 20)

            # Drop shadow
            draw.ellipse([px - token_radius + 1, py - token_radius + 2, px + token_radius + 1, py + token_radius + 2], fill=(0, 0, 0, 120))
            # Token body
            draw.ellipse([px - token_radius, py - token_radius, px + token_radius, py + token_radius], fill=fill_color, outline=rim_color, width=2)
            # Token number
            draw.text((px - 4, py - 7), str(num), fill=text_color)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", compress_level=1)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────────────────────
# LUDO GAME STATE & LOGIC
# ─────────────────────────────────────────────────────────────

class LudoGame:
    def __init__(self, player_red: discord.Member, bot: commands.Bot, tokens_per_player: int = 2, difficulty: str = "Smart"):
        self.player_red = player_red
        self.bot = bot
        self.tokens_per_player = tokens_per_player
        self.difficulty = difficulty

        # Tokens position (steps_taken: -1=Base, 0=Start, 1..50=Track, 51..55=HomePath, 56=Home)
        self.red_tokens = [-1] * tokens_per_player
        self.yellow_tokens = [-1] * tokens_per_player

        self.current_turn = "red"  # Human starts
        self.last_roll: Optional[int] = None
        self.consecutive_sixes = 0
        self.game_over = False
        self.winner: Optional[str] = None
        self.start_time = time.time()
        self.last_updated = time.time()
        self.log_history: List[str] = ["🎲 **Match started!** Click **Roll Dice** to begin."]

    def is_expired(self) -> bool:
        """Returns True if the game has been inactive for > 180 seconds."""
        return (time.time() - self.last_updated) > 180

    def get_track_index(self, color: str, steps: int) -> int:
        offset = 0 if color == "red" else 26
        return (offset + steps) % 52

    def get_legal_moves(self, color: str, roll: int) -> List[int]:
        """Returns list of token indices (0..tokens_per_player-1) that can legally move with `roll`."""
        tokens = self.red_tokens if color == "red" else self.yellow_tokens
        legal = []
        for i, pos in enumerate(tokens):
            if pos == -1:
                if roll == 6:
                    legal.append(i)
            elif 0 <= pos < 56:
                if pos + roll <= 56:
                    legal.append(i)
        return legal

    def apply_move(self, color: str, token_idx: int, roll: int) -> Dict[str, bool]:
        """Applies movement, handles captures, and returns event flags."""
        tokens = self.red_tokens if color == "red" else self.yellow_tokens
        opp_tokens = self.yellow_tokens if color == "red" else self.red_tokens
        opp_color = "yellow" if color == "red" else "red"

        pos = tokens[token_idx]
        captured = False
        reached_home = False
        brought_out = False

        if pos == -1 and roll == 6:
            tokens[token_idx] = 0
            brought_out = True
        else:
            new_pos = pos + roll
            tokens[token_idx] = new_pos
            if new_pos == 56:
                reached_home = True
            elif 0 <= new_pos <= 50:
                # Check for capture on common track
                track_idx = self.get_track_index(color, new_pos)
                if track_idx not in SAFE_TRACK_INDICES:
                    for opp_i in range(len(opp_tokens)):
                        opp_pos = opp_tokens[opp_i]
                        if 0 <= opp_pos <= 50:
                            if self.get_track_index(opp_color, opp_pos) == track_idx:
                                opp_tokens[opp_i] = -1
                                captured = True

        self.last_updated = time.time()
        self.check_win()
        return {
            "captured": captured,
            "reached_home": reached_home,
            "brought_out": brought_out
        }

    def check_win(self):
        if all(p == 56 for p in self.red_tokens):
            self.game_over = True
            self.winner = "red"
        elif all(p == 56 for p in self.yellow_tokens):
            self.game_over = True
            self.winner = "yellow"

    def choose_ai_move(self, roll: int, legal_moves: List[int]) -> int:
        """Heuristic decision tree for Friday AI."""
        if len(legal_moves) == 1:
            return legal_moves[0]

        best_score = -9999
        best_token = legal_moves[0]

        for t_idx in legal_moves:
            pos = self.yellow_tokens[t_idx]
            score = 0

            # 1. Immediate capture of human token (Top priority!)
            if pos >= 0 and pos + roll <= 50:
                target_track = self.get_track_index("yellow", pos + roll)
                if target_track not in SAFE_TRACK_INDICES:
                    for red_pos in self.red_tokens:
                        if 0 <= red_pos <= 50 and self.get_track_index("red", red_pos) == target_track:
                            score += 1500

            # 2. Enter Home (Winning step)
            if pos + roll == 56:
                score += 1000

            # 3. Bring piece out of Base on 6
            if pos == -1 and roll == 6:
                score += 500

            # 4. Land on Safe Star square
            if pos >= 0 and pos + roll <= 50:
                if self.get_track_index("yellow", pos + roll) in SAFE_TRACK_INDICES:
                    score += 300

            # 5. Advance pieces closer to home
            score += (pos + roll) * 5

            if score > best_score:
                best_score = score
                best_token = t_idx

        return best_token


# ─────────────────────────────────────────────────────────────
# DISCORD INTERACTION UI: BUTTONS & LUDO VIEW
# ─────────────────────────────────────────────────────────────

class LudoRollButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.primary, label="Roll Dice", emoji="🎲", row=0)

    async def callback(self, interaction: discord.Interaction):
        view: LudoView = self.view
        await view.handle_human_roll(interaction)


class LudoTokenSelectButton(discord.ui.Button):
    def __init__(self, token_idx: int):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label=f"Move Token {token_idx + 1}",
            emoji="🔴",
            row=0
        )
        self.token_idx = token_idx

    async def callback(self, interaction: discord.Interaction):
        view: LudoView = self.view
        await view.handle_human_token_pick(interaction, self.token_idx)


class LudoForfeitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.secondary, label="Forfeit", emoji="🏳️", row=1)

    async def callback(self, interaction: discord.Interaction):
        view: LudoView = self.view
        await view.handle_forfeit(interaction)


class LudoRematchButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.success, label="Play Rematch", emoji="🔄", row=0)

    async def callback(self, interaction: discord.Interaction):
        view: LudoView = self.view
        await view.handle_rematch(interaction)


class LudoView(discord.ui.View):
    def __init__(self, game: LudoGame):
        super().__init__(timeout=120)
        self.game = game
        self.message: Optional[discord.Message] = None
        self.setup_buttons_for_roll()

    def setup_buttons_for_roll(self):
        self.clear_items()
        self.add_item(LudoRollButton())
        self.add_item(LudoForfeitButton())

    def setup_buttons_for_token_pick(self, legal_moves: List[int]):
        self.clear_items()
        for idx in legal_moves:
            self.add_item(LudoTokenSelectButton(idx))
        self.add_item(LudoForfeitButton())

    def setup_buttons_game_over(self):
        self.clear_items()
        self.add_item(LudoRematchButton())

    def build_embed(self) -> discord.Embed:
        g = self.game
        red_home = sum(1 for p in g.red_tokens if p == 56)
        yellow_home = sum(1 for p in g.yellow_tokens if p == 56)

        title = "🎲  Ludo Solo • Human vs Friday AI"
        color = 0xED4245 if g.current_turn == "red" else 0xFEE75C

        if g.game_over:
            if g.winner == "red":
                title = "🏆  Victory! You Defeated Friday in Ludo!"
                color = 0x57F287
            else:
                title = "🤖  Friday Won the Match!"
                color = 0xED4245

        # Format recent log history (last 3 items)
        log_str = "\n".join(g.log_history[-3:])

        turn_indicator = (
            f"👉 **Your Turn (🔴 Red):** Click **Roll Dice**!"
            if g.current_turn == "red" and not g.game_over
            else f"🤖 **Friday's Turn (🟡 Yellow)...**"
        )
        if g.game_over:
            turn_indicator = f"🎉 **Game Finished!** Final tokens home: Red **{red_home}/{g.tokens_per_player}** • Yellow **{yellow_home}/{g.tokens_per_player}**."

        desc = (
            f"🔴 **{g.player_red.display_name}** (`Red`) vs 🟡 **Friday** (`Yellow`)\n"
            f"• Mode: **{g.tokens_per_player} Tokens** • Goal: Move all tokens to Center Home!\n\n"
            f"**Recent Actions:**\n{log_str}\n\n"
            f"{turn_indicator}\n\n"
            f"📊 **Score:** 🔴 `{red_home}/{g.tokens_per_player}` Home | 🟡 `{yellow_home}/{g.tokens_per_player}` Home"
        )

        embed = discord.Embed(
            title=title,
            description=desc,
            color=color,
            timestamp=datetime.now(pytz.utc)
        )
        embed.set_image(url="attachment://ludo_board.png")
        embed.set_footer(text="Friday Ludo • 120s Turn Timer")
        return embed

    async def update_view(self, interaction: Optional[discord.Interaction] = None):
        """Renders board in background thread and updates message."""
        buf = await asyncio.to_thread(
            render_board_image,
            self.game.red_tokens,
            self.game.yellow_tokens,
            self.game.tokens_per_player
        )
        file = discord.File(buf, filename="ludo_board.png")
        embed = self.build_embed()

        if interaction and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self, attachments=[file])
        elif self.message:
            try:
                await self.message.edit(embed=embed, view=self, attachments=[file])
            except Exception:
                pass

    async def handle_human_roll(self, interaction: discord.Interaction):
        try:
            if interaction.user.id != self.game.player_red.id:
                return await interaction.response.send_message("❌ This is not your game! Start your own with `/ludo`.", ephemeral=True)

            if self.game.current_turn != "red" or self.game.game_over:
                return await interaction.response.defer()

            await interaction.response.defer()

            roll = random.randint(1, 6)
            self.game.last_roll = roll

            legal = self.game.get_legal_moves("red", roll)

            if roll == 6:
                self.game.consecutive_sixes += 1
            else:
                self.game.consecutive_sixes = 0

            # 3 consecutive sixes penalty: pass turn
            if self.game.consecutive_sixes >= 3:
                self.game.log_history.append(f"⚠️ **{self.game.player_red.display_name}** rolled three 6s in a row! Turn forfeited.")
                self.game.consecutive_sixes = 0
                self.game.current_turn = "yellow"
                await self.update_view()
                return asyncio.create_task(self.run_friday_turn())

            if not legal:
                self.game.log_history.append(f"🎲 **{self.game.player_red.display_name}** rolled a **{roll}** (no legal moves).")
                if roll == 6:
                    self.setup_buttons_for_roll()
                    await self.update_view()
                else:
                    self.game.current_turn = "yellow"
                    await self.update_view()
                    asyncio.create_task(self.run_friday_turn())
                return

            if len(legal) == 1:
                # Auto-move single option for ultra-fluid mobile play!
                chosen_t = legal[0]
                ev = self.game.apply_move("red", chosen_t, roll)
                extra_str = ""
                if ev["brought_out"]: extra_str = " (brought token onto the track! 🚀)"
                elif ev["reached_home"]: extra_str = " (token reached Home! 🌟)"
                elif ev["captured"]: extra_str = " (CAPTURED Friday's token! 💥)"

                self.game.log_history.append(f"🎲 **{self.game.player_red.display_name}** rolled a **{roll}** & moved **Token {chosen_t+1}**{extra_str}")

                if self.game.game_over:
                    self.setup_buttons_game_over()
                    ACTIVE_LUDO_GAMES.pop(self.game.player_red.id, None)
                    return await self.update_view()

                if roll == 6 or ev["captured"]:
                    self.setup_buttons_for_roll()
                    await self.update_view()
                else:
                    self.game.current_turn = "yellow"
                    await self.update_view()
                    asyncio.create_task(self.run_friday_turn())
            else:
                # Multiple tokens can move: ask user to choose
                self.game.log_history.append(f"🎲 **{self.game.player_red.display_name}** rolled a **{roll}**! Choose a token to move below:")
                self.setup_buttons_for_token_pick(legal)
                await self.update_view()
        except Exception as e:
            print(f"[Ludo] Error in handle_human_roll: {e}")

    async def handle_human_token_pick(self, interaction: discord.Interaction, token_idx: int):
        try:
            if interaction.user.id != self.game.player_red.id:
                return await interaction.response.send_message("❌ This is not your game!", ephemeral=True)

            await interaction.response.defer()
            roll = self.game.last_roll or 6

            ev = self.game.apply_move("red", token_idx, roll)
            extra_str = ""
            if ev["brought_out"]: extra_str = " (brought token onto the track! 🚀)"
            elif ev["reached_home"]: extra_str = " (token reached Home! 🌟)"
            elif ev["captured"]: extra_str = " (CAPTURED Friday's token! 💥)"

            self.game.log_history.append(f"🔴 Moved **Token {token_idx+1}** by **{roll}** steps{extra_str}")

            if self.game.game_over:
                self.setup_buttons_game_over()
                ACTIVE_LUDO_GAMES.pop(self.game.player_red.id, None)
                return await self.update_view()

            if roll == 6 or ev["captured"]:
                self.setup_buttons_for_roll()
                await self.update_view()
            else:
                self.game.current_turn = "yellow"
                self.setup_buttons_for_roll()
                await self.update_view()
                asyncio.create_task(self.run_friday_turn())
        except Exception as e:
            print(f"[Ludo] Error in handle_human_token_pick: {e}")

    async def run_friday_turn(self):
        """Asynchronously executes Friday AI's turn with human-like realistic pacing."""
        try:
            await asyncio.sleep(1.2)  # Pacing pause
            if self.game.game_over:
                return

            roll = random.randint(1, 6)
            self.game.last_roll = roll

            legal = self.game.get_legal_moves("yellow", roll)

            if not legal:
                self.game.log_history.append(f"🤖 **Friday** rolled a **{roll}** (no legal moves).")
                if roll == 6:
                    # Friday gets another roll on 6
                    return asyncio.create_task(self.run_friday_turn())
                else:
                    self.game.current_turn = "red"
                    self.setup_buttons_for_roll()
                    return await self.update_view()

            chosen_t = self.game.choose_ai_move(roll, legal)
            ev = self.game.apply_move("yellow", chosen_t, roll)

            extra_str = ""
            if ev["brought_out"]: extra_str = " (brought token out! 🚀)"
            elif ev["reached_home"]: extra_str = " (token entered Home! 🌟)"
            elif ev["captured"]: extra_str = " (CAPTURED your token! 💥)"

            self.game.log_history.append(f"🤖 **Friday** rolled a **{roll}** & moved **Token {chosen_t+1}**{extra_str}")

            if self.game.game_over:
                self.setup_buttons_game_over()
                ACTIVE_LUDO_GAMES.pop(self.game.player_red.id, None)
                return await self.update_view()

            if roll == 6 or ev["captured"]:
                await self.update_view()
                await asyncio.sleep(1.0)
                return asyncio.create_task(self.run_friday_turn())
            else:
                self.game.current_turn = "red"
                self.setup_buttons_for_roll()
                await self.update_view()
        except Exception as e:
            print(f"[Ludo] Error in run_friday_turn: {e}")

    async def handle_forfeit(self, interaction: discord.Interaction):
        try:
            if interaction.user.id != self.game.player_red.id:
                return await interaction.response.send_message("❌ You are not part of this game.", ephemeral=True)

            self.game.game_over = True
            self.game.winner = "yellow"
            ACTIVE_LUDO_GAMES.pop(self.game.player_red.id, None)
            self.setup_buttons_game_over()
            self.game.log_history.append(f"🏳️ **{self.game.player_red.display_name}** surrendered the match.")
            await self.update_view(interaction)
        except Exception as e:
            print(f"[Ludo] Error in handle_forfeit: {e}")

    async def handle_rematch(self, interaction: discord.Interaction):
        try:
            if interaction.user.id != self.game.player_red.id:
                return await interaction.response.send_message("❌ Only the match player can start a rematch.", ephemeral=True)

            new_game = LudoGame(
                player_red=self.game.player_red,
                bot=self.game.bot,
                tokens_per_player=self.game.tokens_per_player,
                difficulty=self.game.difficulty
            )
            ACTIVE_LUDO_GAMES[self.game.player_red.id] = new_game

            new_view = LudoView(new_game)
            new_view.message = interaction.message
            await new_view.update_view(interaction)
        except Exception as e:
            print(f"[Ludo] Error in handle_rematch: {e}")

    async def on_timeout(self):
        ACTIVE_LUDO_GAMES.pop(self.game.player_red.id, None)
        if not self.game.game_over:
            self.game.game_over = True
            self.clear_items()
            self.game.log_history.append("⏰ **Match Abandoned:** Game timed out after 120s of inactivity.")
            await self.update_view()


# ─────────────────────────────────────────────────────────────
# LUDO COG SETUP (SLASH COMMAND)
# ─────────────────────────────────────────────────────────────

class Ludo(commands.Cog, name="Games"):
    """Interactive Ludo board game with high-speed canvas image rendering."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ludo", description="Play a solo game of Ludo (X & O board style) against Friday AI!")
    @app_commands.describe(
        mode="Game length: Quick (2 tokens) or Classic (4 tokens)",
        difficulty="Friday AI difficulty level"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="⚡ Quick Mode (2 Tokens — Fast & Fun)", value="2"),
        app_commands.Choice(name="🏆 Classic Mode (4 Tokens — Full Experience)", value="4")
    ])
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="Smart AI (Plays with strategic awareness)", value="Smart"),
        app_commands.Choice(name="Casual AI (Plays relaxed & fun)", value="Casual")
    ])
    async def ludo_slash(
        self,
        interaction: discord.Interaction,
        mode: Optional[str] = "2",
        difficulty: Optional[str] = "Smart"
    ):
        try:
            author = interaction.user

            # Check if active game exists
            active = ACTIVE_LUDO_GAMES.get(author.id)
            if active and not active.is_expired():
                return await interaction.response.send_message(
                    "⚠️ You already have an active Ludo match! Finish it or click **Forfeit** before starting a new one.",
                    ephemeral=True
                )

            await interaction.response.defer()

            num_tokens = int(mode or "2")
            game = LudoGame(
                player_red=author,
                bot=self.bot,
                tokens_per_player=num_tokens,
                difficulty=difficulty or "Smart"
            )
            ACTIVE_LUDO_GAMES[author.id] = game

            view = LudoView(game)
            buf = await asyncio.to_thread(
                render_board_image,
                game.red_tokens,
                game.yellow_tokens,
                game.tokens_per_player
            )
            file = discord.File(buf, filename="ludo_board.png")
            embed = view.build_embed()

            msg = await interaction.followup.send(embed=embed, view=view, file=file)
            view.message = msg
        except Exception as e:
            print(f"[Ludo] Slash command error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Failed to launch Ludo: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ludo(bot))
