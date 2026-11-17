import discord
from discord.ext import commands
from discord import app_commands
import io
import time
import random
import asyncio
from datetime import datetime
import pytz
from typing import Optional, List, Tuple, Dict, Any
from PIL import Image, ImageDraw

# ─────────────────────────────────────────────────────────────
# BOARD GEOMETRY & TRACK DEFINITIONS (15x15 GRID ON 700x850 CANVAS)
# ─────────────────────────────────────────────────────────────

CELL_SIZE = 44
BOARD_SIZE = CELL_SIZE * 15  # 660 x 660 px
CANVAS_W = 700
CANVAS_H = 850
BOARD_X = 20
BOARD_Y = 95

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

# Track start offsets for each of the 4 colors (Clockwise)
COLOR_TRACK_OFFSET = {
    "red": 0,       # Bottom-Left start (13, 6)
    "green": 13,    # Top-Left start (6, 1)
    "yellow": 26,   # Top-Right start (1, 8)
    "blue": 39      # Bottom-Right start (8, 13)
}

# 5 Home run path squares before center for each color
HOME_PATHS = {
    "red": [(13, 7), (12, 7), (11, 7), (10, 7), (9, 7)],
    "green": [(7, 1), (7, 2), (7, 3), (7, 4), (7, 5)],
    "yellow": [(1, 7), (2, 7), (3, 7), (4, 7), (5, 7)],
    "blue": [(7, 13), (7, 12), (7, 11), (7, 10), (7, 9)]
}

# Center triangle home coordinates (step 56)
HOME_CENTERS = {
    "red": (8.0, 7.0),
    "green": (7.0, 6.0),
    "yellow": (6.0, 7.0),
    "blue": (7.0, 8.0)
}

# Base (Yard) token resting spots for up to 4 tokens per color (row, col)
BASE_SPOTS = {
    "green": [(1.8, 1.8), (1.8, 3.8), (3.8, 1.8), (3.8, 3.8)],
    "yellow": [(1.8, 10.8), (1.8, 12.8), (3.8, 10.8), (3.8, 12.8)],
    "red": [(10.8, 1.8), (10.8, 3.8), (12.8, 1.8), (12.8, 3.8)],
    "blue": [(10.8, 10.8), (10.8, 12.8), (12.8, 10.8), (12.8, 12.8)]
}

COLOR_THEMES = {
    "red": {
        "name": "Red",
        "emoji": "🔴",
        "rgb": (220, 53, 69),
        "highlight": (255, 75, 90)
    },
    "green": {
        "name": "Green",
        "emoji": "🟢",
        "rgb": (40, 167, 69),
        "highlight": (50, 205, 50)
    },
    "yellow": {
        "name": "Yellow",
        "emoji": "🟡",
        "rgb": (245, 185, 15),
        "highlight": (255, 215, 0)
    },
    "blue": {
        "name": "Blue",
        "emoji": "🔵",
        "rgb": (23, 162, 184),
        "highlight": (0, 210, 255)
    }
}

COLOR_CLOCKWISE = ["red", "green", "yellow", "blue"]

# Active game and lobby session registries (host_id -> Game/Lobby)
ACTIVE_LUDO_GAMES: Dict[int, "LudoGame"] = {}
ACTIVE_LUDO_LOBBIES: Dict[int, "LudoLobbyView"] = {}


# ─────────────────────────────────────────────────────────────
# HIGH-SPEED CANVAS RENDERING ENGINE (PRE-CACHED IN RAM)
# ─────────────────────────────────────────────────────────────

def _create_base_board() -> Image.Image:
    """Pre-generates the static 15x15 Ludo board into RAM once on startup."""
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), (18, 19, 23))
    d = ImageDraw.Draw(img)

    c_red = (220, 53, 69)
    c_green = (40, 167, 69)
    c_yellow = (245, 185, 15)
    c_blue = (23, 162, 184)
    c_white = (248, 249, 250)
    c_dark_line = (60, 64, 69)
    c_safe = (245, 230, 160)
    c_base_slot = (240, 243, 246)
    c_base_slot_border = (195, 200, 210)

    # 1. Base Yards
    d.rectangle([BOARD_X, BOARD_Y, BOARD_X + CELL_SIZE * 6, BOARD_Y + CELL_SIZE * 6], fill=c_green)
    d.rectangle([BOARD_X + CELL_SIZE, BOARD_Y + CELL_SIZE, BOARD_X + CELL_SIZE * 5, BOARD_Y + CELL_SIZE * 5], fill=c_white)

    d.rectangle([BOARD_X + CELL_SIZE * 9, BOARD_Y, BOARD_X + BOARD_SIZE, BOARD_Y + CELL_SIZE * 6], fill=c_yellow)
    d.rectangle([BOARD_X + CELL_SIZE * 10, BOARD_Y + CELL_SIZE, BOARD_X + CELL_SIZE * 14, BOARD_Y + CELL_SIZE * 5], fill=c_white)

    d.rectangle([BOARD_X, BOARD_Y + CELL_SIZE * 9, BOARD_X + CELL_SIZE * 6, BOARD_Y + BOARD_SIZE], fill=c_red)
    d.rectangle([BOARD_X + CELL_SIZE, BOARD_Y + CELL_SIZE * 10, BOARD_X + CELL_SIZE * 5, BOARD_Y + CELL_SIZE * 14], fill=c_white)

    d.rectangle([BOARD_X + CELL_SIZE * 9, BOARD_Y + CELL_SIZE * 9, BOARD_X + BOARD_SIZE, BOARD_Y + BOARD_SIZE], fill=c_blue)
    d.rectangle([BOARD_X + CELL_SIZE * 10, BOARD_Y + CELL_SIZE * 10, BOARD_X + CELL_SIZE * 14, BOARD_Y + CELL_SIZE * 14], fill=c_white)

    # Base resting circles (Ivory pedestal slots with high contrast)
    all_bases = [
        (1.8, 1.8), (1.8, 3.8), (3.8, 1.8), (3.8, 3.8),
        (1.8, 10.8), (1.8, 12.8), (3.8, 10.8), (3.8, 12.8),
        (10.8, 1.8), (10.8, 3.8), (12.8, 1.8), (12.8, 3.8),
        (10.8, 10.8), (10.8, 12.8), (12.8, 10.8), (12.8, 12.8)
    ]
    for r, c in all_bases:
        x = int(BOARD_X + c * CELL_SIZE)
        y = int(BOARD_Y + r * CELL_SIZE)
        d.ellipse([x - 20, y - 19, x + 20, y + 21], fill=(215, 220, 228))
        d.ellipse([x - 20, y - 20, x + 20, y + 20], fill=c_base_slot, outline=c_base_slot_border, width=2)

    # 2. Track cells
    for r in range(15):
        for c in range(15):
            in_cross = (6 <= r <= 8) or (6 <= c <= 8)
            in_center = (6 <= r <= 8) and (6 <= c <= 8)
            if in_cross and not in_center:
                x1 = BOARD_X + c * CELL_SIZE
                y1 = BOARD_Y + r * CELL_SIZE
                x2, y2 = x1 + CELL_SIZE, y1 + CELL_SIZE
                d.rectangle([x1, y1, x2, y2], fill=c_white, outline=c_dark_line, width=1)

    # 3. Colored Start squares & Home columns
    # Red start (13, 6) & home column (cols 7, rows 9..13)
    d.rectangle([BOARD_X + 6 * CELL_SIZE, BOARD_Y + 13 * CELL_SIZE, BOARD_X + 7 * CELL_SIZE, BOARD_Y + 14 * CELL_SIZE], fill=c_red, outline=c_dark_line)
    for r in range(9, 14):
        d.rectangle([BOARD_X + 7 * CELL_SIZE, BOARD_Y + r * CELL_SIZE, BOARD_X + 8 * CELL_SIZE, BOARD_Y + (r + 1) * CELL_SIZE], fill=c_red, outline=c_dark_line)

    # Yellow start (1, 8) & home column (cols 7, rows 1..5)
    d.rectangle([BOARD_X + 8 * CELL_SIZE, BOARD_Y + 1 * CELL_SIZE, BOARD_X + 9 * CELL_SIZE, BOARD_Y + 2 * CELL_SIZE], fill=c_yellow, outline=c_dark_line)
    for r in range(1, 6):
        d.rectangle([BOARD_X + 7 * CELL_SIZE, BOARD_Y + r * CELL_SIZE, BOARD_X + 8 * CELL_SIZE, BOARD_Y + (r + 1) * CELL_SIZE], fill=c_yellow, outline=c_dark_line)

    # Green start (6, 1) & home column
    d.rectangle([BOARD_X + 1 * CELL_SIZE, BOARD_Y + 6 * CELL_SIZE, BOARD_X + 2 * CELL_SIZE, BOARD_Y + 7 * CELL_SIZE], fill=c_green, outline=c_dark_line)
    for c in range(1, 6):
        d.rectangle([BOARD_X + c * CELL_SIZE, BOARD_Y + 7 * CELL_SIZE, BOARD_X + (c + 1) * CELL_SIZE, BOARD_Y + 8 * CELL_SIZE], fill=c_green, outline=c_dark_line)

    # Blue start (8, 13) & home column
    d.rectangle([BOARD_X + 13 * CELL_SIZE, BOARD_Y + 8 * CELL_SIZE, BOARD_X + 14 * CELL_SIZE, BOARD_Y + 9 * CELL_SIZE], fill=c_blue, outline=c_dark_line)
    for c in range(9, 14):
        d.rectangle([BOARD_X + c * CELL_SIZE, BOARD_Y + 7 * CELL_SIZE, BOARD_X + (c + 1) * CELL_SIZE, BOARD_Y + 8 * CELL_SIZE], fill=c_blue, outline=c_dark_line)

    # 4. Safe Star tiles (⭐)
    stars = [(8, 2), (2, 6), (6, 12), (12, 8)]
    for r, c in stars:
        x1, y1 = BOARD_X + c * CELL_SIZE, BOARD_Y + r * CELL_SIZE
        x2, y2 = x1 + CELL_SIZE, y1 + CELL_SIZE
        d.rectangle([x1, y1, x2, y2], fill=c_safe, outline=c_dark_line)
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        d.polygon([
            (cx, cy - 12), (cx + 3, cy - 3), (cx + 12, cy - 3), (cx + 5, cy + 3),
            (cx + 8, cy + 12), (cx, cy + 6), (cx - 8, cy + 12), (cx - 5, cy + 3),
            (cx - 12, cy - 3), (cx - 3, cy - 3)
        ], fill=(212, 175, 55))

    # 5. Center Home Triangles
    cx1, cy1 = BOARD_X + 6 * CELL_SIZE, BOARD_Y + 6 * CELL_SIZE
    cx2, cy2 = BOARD_X + 9 * CELL_SIZE, BOARD_Y + 9 * CELL_SIZE
    mid_x, mid_y = (cx1 + cx2) // 2, (cy1 + cy2) // 2

    d.polygon([(cx1, cy1), (cx1, cy2), (mid_x, mid_y)], fill=c_green, outline=c_dark_line)
    d.polygon([(cx1, cy1), (cx2, cy1), (mid_x, mid_y)], fill=c_yellow, outline=c_dark_line)
    d.polygon([(cx2, cy1), (cx2, cy2), (mid_x, mid_y)], fill=c_blue, outline=c_dark_line)
    d.polygon([(cx1, cy2), (cx2, cy2), (mid_x, mid_y)], fill=c_red, outline=c_dark_line)

    # Outer board border
    d.rectangle([BOARD_X, BOARD_Y, BOARD_X + BOARD_SIZE - 1, BOARD_Y + BOARD_SIZE - 1], outline=(40, 44, 52), width=3)
    return img

_CACHED_BASE_BOARD = _create_base_board()


def get_token_xy(color: str, token_idx: int, steps: int) -> Tuple[float, float]:
    """Returns the (x, y) canvas pixel center for a token at a given step count."""
    if steps == -1:
        # In Yard Base
        r, c = BASE_SPOTS[color][token_idx]
        return (BOARD_X + c * CELL_SIZE, BOARD_Y + r * CELL_SIZE)

    if steps == 56:
        # Inside Center Home Triangle
        r, c = HOME_CENTERS[color]
        if color in ("red", "yellow"):
            offset_x = (token_idx - 0.5) * 14 if token_idx in (0, 1) else (token_idx - 2.5) * 14
            offset_y = 0 if token_idx in (0, 1) else (6 if color == "red" else -6)
        else:
            offset_y = (token_idx - 0.5) * 14 if token_idx in (0, 1) else (token_idx - 2.5) * 14
            offset_x = 0 if token_idx in (0, 1) else (-6 if color == "green" else 6)
        return (
            BOARD_X + c * CELL_SIZE + CELL_SIZE // 2 + offset_x,
            BOARD_Y + r * CELL_SIZE + CELL_SIZE // 2 + offset_y
        )

    if steps >= 51:
        # Inside Home Run Path (51..55)
        path = HOME_PATHS[color]
        r, c = path[steps - 51]
        return (BOARD_X + c * CELL_SIZE + CELL_SIZE // 2, BOARD_Y + r * CELL_SIZE + CELL_SIZE // 2)

    # Main Track (0..50)
    track_offset = COLOR_TRACK_OFFSET[color]
    track_idx = (track_offset + steps) % 52
    r, c = TRACK_COORDS[track_idx]
    return (BOARD_X + c * CELL_SIZE + CELL_SIZE // 2, BOARD_Y + r * CELL_SIZE + CELL_SIZE // 2)


def draw_corner_player_hud(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    color_name: str,
    player_info: Optional[Dict[str, Any]],
    roll: Optional[int],
    is_active: bool,
    align_left: bool = True
):
    """Renders a dedicated 3D corner player profile card and their dice block."""
    if not player_info:
        # Empty/Unused Slot
        draw.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=(24, 25, 29), outline=(42, 45, 52), width=1)
        draw.text((x + w // 2 - 35, y + h // 2 - 7), "[ Empty Slot ]", fill=(100, 105, 115))
        return

    theme = COLOR_THEMES[color_name]
    card_bg = (30, 32, 38)
    border_col = theme["highlight"] if is_active else (52, 55, 63)
    border_w = 3 if is_active else 1

    # Card background
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=card_bg, outline=border_col, width=border_w)

    # Position dice
    if align_left:
        dx, dy = x + 8, y + 8
        tx = x + 68
    else:
        dx, dy = x + w - 58, y + 8
        tx = x + 14

    # 3D Dice block
    draw.rounded_rectangle([dx + 2, dy + 2, dx + 52, dy + 52], radius=8, fill=(12, 13, 15))
    draw.rounded_rectangle([dx, dy, dx + 50, dy + 50], radius=8, fill=(255, 255, 255), outline=(210, 215, 220), width=2)

    # 3D Dots in matching player theme color
    if roll and 1 <= roll <= 6:
        dot_r = 4
        coords = {
            1: [(25, 25)],
            2: [(14, 14), (36, 36)],
            3: [(14, 14), (25, 25), (36, 36)],
            4: [(14, 14), (14, 36), (36, 14), (36, 36)],
            5: [(14, 14), (14, 36), (25, 25), (36, 14), (36, 36)],
            6: [(14, 14), (14, 25), (14, 36), (36, 14), (36, 25), (36, 36)]
        }
        for px, py in coords[roll]:
            draw.ellipse([dx + px - dot_r, dy + py - dot_r, dx + px + dot_r, dy + py + dot_r], fill=theme["rgb"])
    else:
        draw.text((dx + 19, dy + 14), "?", fill=(120, 125, 135))

    # Player labels
    name = player_info["name"][:13]
    home_cnt = sum(1 for p in player_info["tokens"] if p == 56)
    total_tokens = len(player_info["tokens"])

    draw.text((tx, y + 14), f"{theme['emoji']} {name}", fill=(255, 255, 255))
    if is_active:
        draw.text((tx, y + 36), "👉 YOUR TURN!", fill=(87, 242, 135))
    else:
        draw.text((tx, y + 36), f"Score: {home_cnt}/{total_tokens} Home", fill=(160, 165, 175))


def render_board_image(
    players: Dict[str, Dict[str, Any]],
    current_turn: str,
    last_rolls: Dict[str, Optional[int]],
    tokens_per_player: int,
    movable_tokens: Optional[List[int]] = None
) -> io.BytesIO:
    """Renders the 15x15 Ludo board with all 4 corner player HUD cards and their dice blocks."""
    canvas = _CACHED_BASE_BOARD.copy()
    draw = ImageDraw.Draw(canvas)

    # 1. Render All 4 Corner Player Cards & Dedicated Dice
    # Top-Left: Green
    draw_corner_player_hud(
        draw, 20, 14, 310, 66, "green",
        players.get("green"), last_rolls.get("green"),
        (current_turn == "green"), align_left=True
    )
    # Top-Right: Yellow
    draw_corner_player_hud(
        draw, 370, 14, 310, 66, "yellow",
        players.get("yellow"), last_rolls.get("yellow"),
        (current_turn == "yellow"), align_left=False
    )
    # Bottom-Left: Red
    draw_corner_player_hud(
        draw, 20, 768, 310, 66, "red",
        players.get("red"), last_rolls.get("red"),
        (current_turn == "red"), align_left=True
    )
    # Bottom-Right: Blue
    draw_corner_player_hud(
        draw, 370, 768, 310, 66, "blue",
        players.get("blue"), last_rolls.get("blue"),
        (current_turn == "blue"), align_left=False
    )

    # 2. Map token positions for overlap handling across all players
    pos_map: Dict[Tuple[int, int], List[Tuple[str, int, float, float, bool]]] = {}
    movable_set = set(movable_tokens or [])

    for col, pdata in players.items():
        for i in range(tokens_per_player):
            pos = pdata["tokens"][i]
            is_movable = (col == current_turn and i in movable_set)
            x, y = get_token_xy(col, i, pos)
            key = (int(round(x)), int(round(y)))
            pos_map.setdefault(key, []).append((col, i + 1, x, y, is_movable))

    # 3. Render 3D Tokens with Side-by-Side Multi-Token Support & Glow
    for key, tokens_on_spot in pos_map.items():
        count = len(tokens_on_spot)
        for idx, (col, num, x, y, is_movable) in enumerate(tokens_on_spot):
            if count == 1:
                token_radius = 15
                px, py = int(round(x)), int(round(y))
                text_dx, text_dy = -4, -6
            elif count == 2:
                # 2 Tokens in 1 box: Place side-by-side (offset ±10px, radius 11px)
                token_radius = 11
                offset_x = -10 if idx == 0 else 10
                px, py = int(round(x + offset_x)), int(round(y))
                text_dx, text_dy = -3, -5
            else:
                # 3 or 4 Tokens: 2x2 grid layout inside the 44px cell (radius 9px)
                token_radius = 9
                quad_offsets = [(-9, -9), (9, -9), (-9, 9), (9, 9)]
                ox, oy = quad_offsets[idx % 4]
                px, py = int(round(x + ox)), int(round(y + oy))
                text_dx, text_dy = -3, -5

            # Glowing Neon Green Ring if token is legal to move!
            if is_movable:
                ring_r = token_radius + 4
                draw.ellipse([px - ring_r, py - ring_r, px + ring_r, py + ring_r], outline=(87, 242, 135), width=2)

            # Drop shadow
            draw.ellipse([px - token_radius + 1, py - token_radius + 2, px + token_radius + 1, py + token_radius + 2], fill=(0, 0, 0, 160))

            # Token 3D Body
            theme = COLOR_THEMES[col]
            fill_color = theme["rgb"]
            rim_color = (255, 255, 255) if col in ("red", "blue") else (30, 30, 30)
            text_color = (255, 255, 255) if col in ("red", "blue") else (20, 20, 20)

            draw.ellipse(
                [px - token_radius, py - token_radius, px + token_radius, py + token_radius],
                fill=fill_color,
                outline=rim_color,
                width=2 if count > 1 else 3
            )

            # Specular 3D highlight (top-left shine)
            shine_color = theme["highlight"]
            shine_w = max(3, token_radius // 2)
            draw.ellipse(
                [px - token_radius + 2, py - token_radius + 2, px - token_radius + 2 + shine_w, py - token_radius + 2 + shine_w],
                fill=shine_color
            )

            # Token number
            draw.text((px + text_dx, py + text_dy), str(num), fill=text_color)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", compress_level=1)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────────────────────
# LUDO MULTIPLAYER GAME STATE & DETERMINISTIC HEURISTIC AI
# ─────────────────────────────────────────────────────────────

class LudoGame:
    def __init__(self, players_config: List[Dict[str, Any]], tokens_per_player: int = 2):
        self.tokens_per_player = tokens_per_player
        self.players: Dict[str, Dict[str, Any]] = {}
        self.turn_order: List[str] = []

        for p in players_config:
            col = p["color"]
            self.players[col] = {
                "color": col,
                "member": p.get("member"),
                "name": p.get("name", "Player"),
                "is_ai": p.get("is_ai", False),
                "tokens": [-1] * tokens_per_player
            }
            self.turn_order.append(col)

        self.current_turn = self.turn_order[0]
        self.last_rolls: Dict[str, Optional[int]] = {col: None for col in self.turn_order}
        self.consecutive_sixes = 0
        self.game_over = False
        self.winner: Optional[str] = None
        self.last_updated = time.time()
        self.log_history: List[str] = ["🎲 **Match initialized!** Click **Roll Dice** to begin."]

    def is_expired(self) -> bool:
        """Returns True if inactive for > 180 seconds."""
        return (time.time() - self.last_updated) > 180

    def get_track_index(self, color: str, steps: int) -> int:
        offset = COLOR_TRACK_OFFSET[color]
        return (offset + steps) % 52

    def get_legal_moves(self, color: str, roll: int) -> List[int]:
        tokens = self.players[color]["tokens"]
        legal = []
        for i, pos in enumerate(tokens):
            if pos == -1:
                if roll == 6:
                    legal.append(i)
            elif 0 <= pos < 56:
                if pos + roll <= 56:
                    legal.append(i)
        return legal

    def apply_move(self, color: str, token_idx: int, roll: int) -> Dict[str, Any]:
        """Applies movement, checks captures against all opponents, and tests for win."""
        player = self.players[color]
        tokens = player["tokens"]
        pos = tokens[token_idx]

        captured_info: Optional[str] = None
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
                track_idx = self.get_track_index(color, new_pos)
                if track_idx not in SAFE_TRACK_INDICES:
                    # Check all opponent tokens for capture
                    for opp_col, opp_data in self.players.items():
                        if opp_col != color:
                            for opp_i, opp_pos in enumerate(opp_data["tokens"]):
                                if 0 <= opp_pos <= 50:
                                    if self.get_track_index(opp_col, opp_pos) == track_idx:
                                        opp_data["tokens"][opp_i] = -1
                                        captured_info = f"{opp_data['name']} ({opp_col.title()})"
                                        break

        self.last_updated = time.time()
        self.check_win()
        return {
            "captured": captured_info is not None,
            "captured_name": captured_info,
            "reached_home": reached_home,
            "brought_out": brought_out
        }

    def check_win(self):
        for col, pdata in self.players.items():
            if all(p == 56 for p in pdata["tokens"]):
                self.game_over = True
                self.winner = col
                break

    def advance_turn(self):
        """Passes turn to the next active player in clockwise rotation."""
        idx = self.turn_order.index(self.current_turn)
        self.current_turn = self.turn_order[(idx + 1) % len(self.turn_order)]
        self.consecutive_sixes = 0

    def choose_ai_move(self, color: str, roll: int, legal_moves: List[int]) -> int:
        """Deterministic, zero-latency rule-based heuristic AI (Strictly NO LLM)."""
        if len(legal_moves) == 1:
            return legal_moves[0]

        tokens = self.players[color]["tokens"]
        best_score = -9999
        best_token = legal_moves[0]

        for t_idx in legal_moves:
            pos = tokens[t_idx]
            score = 0

            # 1. Immediate capture of an opponent token (Top Priority!)
            if pos >= 0 and pos + roll <= 50:
                target_track = (COLOR_TRACK_OFFSET[color] + pos + roll) % 52
                if target_track not in SAFE_TRACK_INDICES:
                    for opp_col, opp_data in self.players.items():
                        if opp_col != color:
                            for opp_pos in opp_data["tokens"]:
                                if 0 <= opp_pos <= 50:
                                    opp_track = (COLOR_TRACK_OFFSET[opp_col] + opp_pos) % 52
                                    if opp_track == target_track:
                                        score += 1500

            # 2. Enter Center Home (Winning move!)
            if pos + roll == 56:
                score += 1000

            # 3. Release piece from base on a 6
            if pos == -1 and roll == 6:
                score += 500

            # 4. Land on a Safe Star tile ⭐
            if pos >= 0 and pos + roll <= 50:
                target_track = (COLOR_TRACK_OFFSET[color] + pos + roll) % 52
                if target_track in SAFE_TRACK_INDICES:
                    score += 300

            # 5. Move tokens closer to home
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
    def __init__(self, token_idx: int, label: str):
        super().__init__(
            style=discord.ButtonStyle.success,
            label=label,
            emoji="🟢",
            row=0
        )
        self.token_idx = token_idx

    async def callback(self, interaction: discord.Interaction):
        view: LudoView = self.view
        await view.handle_human_token_pick(interaction, self.token_idx)


class LudoPassButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.secondary, label="Pass Turn", emoji="⏩", row=0)

    async def callback(self, interaction: discord.Interaction):
        view: LudoView = self.view
        await view.handle_human_pass(interaction)


class LudoForfeitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.secondary, label="Forfeit", emoji="🏳️", row=1)

    async def callback(self, interaction: discord.Interaction):
        view: LudoView = self.view
        await view.handle_forfeit(interaction)


class LudoRematchButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.primary, label="Play Rematch", emoji="🔄", row=0)

    async def callback(self, interaction: discord.Interaction):
        view: LudoView = self.view
        await view.handle_rematch(interaction)


class LudoView(discord.ui.View):
    def __init__(self, game: LudoGame):
        super().__init__(timeout=90)
        self.game = game
        self.message: Optional[discord.Message] = None
        self.movable_tokens: List[int] = []
        self.setup_buttons_for_roll()

    def setup_buttons_for_roll(self):
        self.clear_items()
        self.movable_tokens = []
        self.add_item(LudoRollButton())
        self.add_item(LudoForfeitButton())

    def setup_buttons_no_moves(self):
        self.clear_items()
        self.movable_tokens = []
        self.add_item(LudoPassButton())
        self.add_item(LudoForfeitButton())

    def setup_buttons_for_token_pick(self, legal_moves: List[int], roll: int):
        self.clear_items()
        self.movable_tokens = legal_moves
        g = self.game
        current_col = g.current_turn
        pdata = g.players[current_col]

        for idx in legal_moves:
            pos = pdata["tokens"][idx]
            if pos == -1:
                label = f"Token {idx+1}: Leave Base ➔ Start 🚀"
            elif pos + roll == 56:
                label = f"Token {idx+1}: Enter Home! 🌟"
            else:
                target_track = (COLOR_TRACK_OFFSET[current_col] + pos + roll) % 52
                will_capture = False
                if target_track not in SAFE_TRACK_INDICES:
                    for opp_col, opp_data in g.players.items():
                        if opp_col != current_col:
                            for opp_pos in opp_data["tokens"]:
                                if 0 <= opp_pos <= 50 and (COLOR_TRACK_OFFSET[opp_col] + opp_pos) % 52 == target_track:
                                    will_capture = True
                                    break
                if will_capture:
                    label = f"Token {idx+1}: CAPTURE Opponent! 💥"
                elif target_track in SAFE_TRACK_INDICES:
                    label = f"Token {idx+1}: Move {roll} (Safe Star ⭐)"
                else:
                    label = f"Token {idx+1}: Advance {roll} Steps 🏃"

            self.add_item(LudoTokenSelectButton(idx, label=label[:80]))
        self.add_item(LudoForfeitButton())

    def setup_buttons_game_over(self):
        self.clear_items()
        self.movable_tokens = []
        self.add_item(LudoRematchButton())

    def build_embed(self, status_text: Optional[str] = None) -> discord.Embed:
        g = self.game
        cur_col = g.current_turn
        cur_p = g.players[cur_col]
        theme = COLOR_THEMES[cur_col]

        title = f"🎲  Ludo Royale • {len(g.turn_order)} Players"
        color = discord.Color.from_rgb(*theme["rgb"])

        if g.game_over:
            winner_p = g.players[g.winner]
            title = f"🏆  Victory! {winner_p['name']} Won the Match!"
            color = discord.Color.green()

        # Clean Player Standings Table
        standings_lines = []
        for col in g.turn_order:
            p = g.players[col]
            t = COLOR_THEMES[col]
            home_cnt = sum(1 for pos in p["tokens"] if pos == 56)
            base_cnt = sum(1 for pos in p["tokens"] if pos == -1)
            track_cnt = sum(1 for pos in p["tokens"] if 0 <= pos < 56)
            active_marker = " 👈 *(Their Turn)*" if (col == cur_col and not g.game_over) else ""
            standings_lines.append(
                f"{t['emoji']} **{p['name']}**: `🏠 Base: {base_cnt}` · `🛤️ Track: {track_cnt}` · `🏁 Home: {home_cnt}/{g.tokens_per_player}`{active_marker}"
            )
        standings_str = "\n".join(standings_lines)

        # Upper Live Guidance
        if status_text:
            turn_box = status_text
        elif g.game_over:
            turn_box = f"🎉 **Match Concluded!** Winner: **{g.players[g.winner]['name']}**!"
        elif cur_p["is_ai"]:
            turn_box = f"🤖 **{cur_p['name']}** is calculating optimal move..."
        elif self.movable_tokens:
            turn_box = f"👉 **{cur_p['name']}'s Turn:** Pick a glowing token button below to move!"
        else:
            turn_box = f"👉 **{cur_p['name']}'s Turn:** Click **Roll Dice** below!"

        # Recent actions
        log_str = "\n".join(g.log_history[-3:])

        desc = (
            f"{turn_box}\n\n"
            f"📊 **Live Player Standings:**\n{standings_str}\n\n"
            f"📜 **Match Log:**\n{log_str}"
        )

        embed = discord.Embed(
            title=title,
            description=desc,
            color=color,
            timestamp=datetime.now(pytz.utc)
        )
        embed.set_image(url="attachment://ludo_board.png")
        embed.set_footer(text="Friday Ludo Royale • 90s Turn Timer")
        return embed

    async def update_view(self, interaction: Optional[discord.Interaction] = None):
        """Renders board in background thread and updates message."""
        buf = await asyncio.to_thread(
            render_board_image,
            self.game.players,
            self.game.current_turn,
            self.game.last_rolls,
            self.game.tokens_per_player,
            self.movable_tokens
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
            cur_col = self.game.current_turn
            cur_p = self.game.players[cur_col]

            if cur_p["is_ai"]:
                return await interaction.response.send_message("🤖 It is Friday AI's turn!", ephemeral=True)

            if interaction.user.id != cur_p["member"].id:
                return await interaction.response.send_message(f"❌ It is currently {cur_p['name']}'s turn!", ephemeral=True)

            if self.game.game_over:
                return await interaction.response.defer()

            # 1. Rolling suspense animation
            self.clear_items()
            btn_rolling = discord.ui.Button(style=discord.ButtonStyle.secondary, label="Rolling...", emoji="🎲", disabled=True)
            self.add_item(btn_rolling)
            rolling_embed = self.build_embed(status_text=f"🎲 *{cur_p['name']} is shaking the dice cup...*")
            await interaction.response.edit_message(embed=rolling_embed, view=self)

            await asyncio.sleep(0.4)

            # 2. Generate Roll
            roll = random.randint(1, 6)
            self.game.last_rolls[cur_col] = roll
            theme = COLOR_THEMES[cur_col]

            legal = self.game.get_legal_moves(cur_col, roll)

            if roll == 6:
                self.game.consecutive_sixes += 1
            else:
                self.game.consecutive_sixes = 0

            # 3 consecutive sixes penalty
            if self.game.consecutive_sixes >= 3:
                self.game.log_history.append(f"⚠️ {theme['emoji']} **{cur_p['name']}** rolled three 6s in a row! Turn forfeited.")
                self.game.advance_turn()
                self.setup_buttons_for_roll()
                await self.update_view()
                return await self.check_and_run_ai_turn()

            if not legal:
                self.game.log_history.append(f"{theme['emoji']} **{cur_p['name']}** rolled a **[ {roll} ]** (no legal moves).")
                if roll == 6:
                    self.setup_buttons_for_roll()
                    await self.update_view()
                else:
                    self.setup_buttons_no_moves()
                    await self.update_view()
                return

            action_text = "Choose which token to release from base or move:" if roll == 6 else "Choose which token to move:"
            self.game.log_history.append(f"{theme['emoji']} **{cur_p['name']}** rolled a **[ {roll} ]**! {action_text}")
            self.setup_buttons_for_token_pick(legal, roll)
            await self.update_view()
        except Exception as e:
            print(f"[Ludo] Error in handle_human_roll: {e}")

    async def handle_human_pass(self, interaction: discord.Interaction):
        try:
            cur_col = self.game.current_turn
            cur_p = self.game.players[cur_col]

            if interaction.user.id != cur_p["member"].id:
                return await interaction.response.send_message("❌ This is not your turn!", ephemeral=True)

            await interaction.response.defer()
            self.game.advance_turn()
            self.setup_buttons_for_roll()
            await self.update_view()
            await self.check_and_run_ai_turn()
        except Exception as e:
            print(f"[Ludo] Error in handle_human_pass: {e}")

    async def handle_human_token_pick(self, interaction: discord.Interaction, token_idx: int):
        try:
            cur_col = self.game.current_turn
            cur_p = self.game.players[cur_col]

            if interaction.user.id != cur_p["member"].id:
                return await interaction.response.send_message("❌ This is not your turn!", ephemeral=True)

            await interaction.response.defer()
            roll = self.game.last_rolls.get(cur_col) or 6
            theme = COLOR_THEMES[cur_col]

            ev = self.game.apply_move(cur_col, token_idx, roll)
            extra_str = ""
            if ev["brought_out"]: extra_str = " (brought token onto track! 🚀)"
            elif ev["reached_home"]: extra_str = " (token reached Home! 🌟)"
            elif ev["captured"]: extra_str = f" (CAPTURED {ev['captured_name']}! 💥)"

            self.game.log_history.append(f"{theme['emoji']} **{cur_p['name']}** moved **Token {token_idx+1}** by **[ {roll} ]** steps{extra_str}")

            if self.game.game_over:
                self.setup_buttons_game_over()
                host_id = list(self.game.players.values())[0]["member"].id
                ACTIVE_LUDO_GAMES.pop(host_id, None)
                return await self.update_view()

            if roll == 6 or ev["captured"]:
                self.setup_buttons_for_roll()
                await self.update_view()
            else:
                self.game.advance_turn()
                self.setup_buttons_for_roll()
                await self.update_view()
                await self.check_and_run_ai_turn()
        except Exception as e:
            print(f"[Ludo] Error in handle_human_token_pick: {e}")

    async def check_and_run_ai_turn(self):
        """If current turn belongs to Friday AI, triggers automated turn execution."""
        cur_col = self.game.current_turn
        cur_p = self.game.players[cur_col]
        if cur_p["is_ai"] and not self.game.game_over:
            asyncio.create_task(self.run_ai_turn())

    async def run_ai_turn(self):
        """Asynchronously executes Friday AI's turn with human-like realistic pacing (Strictly NO LLM)."""
        try:
            await asyncio.sleep(1.2)
            if self.game.game_over:
                return

            cur_col = self.game.current_turn
            cur_p = self.game.players[cur_col]
            if not cur_p["is_ai"]:
                return

            roll = random.randint(1, 6)
            self.game.last_rolls[cur_col] = roll
            theme = COLOR_THEMES[cur_col]

            legal = self.game.get_legal_moves(cur_col, roll)

            if not legal:
                self.game.log_history.append(f"🤖 **{cur_p['name']}** rolled a **[ {roll} ]** (no legal moves).")
                if roll == 6:
                    await self.update_view()
                    await asyncio.sleep(1.0)
                    return asyncio.create_task(self.run_ai_turn())
                else:
                    self.game.advance_turn()
                    self.setup_buttons_for_roll()
                    await self.update_view()
                    return await self.check_and_run_ai_turn()

            chosen_t = self.game.choose_ai_move(cur_col, roll, legal)
            ev = self.game.apply_move(cur_col, chosen_t, roll)

            extra_str = ""
            if ev["brought_out"]: extra_str = " (brought token out! 🚀)"
            elif ev["reached_home"]: extra_str = " (token entered Home! 🌟)"
            elif ev["captured"]: extra_str = f" (CAPTURED {ev['captured_name']}! 💥)"

            self.game.log_history.append(f"🤖 **{cur_p['name']}** rolled a **[ {roll} ]** & moved **Token {chosen_t+1}**{extra_str}")

            if self.game.game_over:
                self.setup_buttons_game_over()
                host_id = list(self.game.players.values())[0]["member"].id
                ACTIVE_LUDO_GAMES.pop(host_id, None)
                return await self.update_view()

            if roll == 6 or ev["captured"]:
                await self.update_view()
                await asyncio.sleep(1.2)
                return asyncio.create_task(self.run_ai_turn())
            else:
                self.game.advance_turn()
                self.setup_buttons_for_roll()
                await self.update_view()
                await self.check_and_run_ai_turn()
        except Exception as e:
            print(f"[Ludo] Error in run_ai_turn: {e}")

    async def handle_forfeit(self, interaction: discord.Interaction):
        try:
            author = interaction.user
            # Find author's color
            user_color = None
            for col, pdata in self.game.players.items():
                if pdata["member"] and pdata["member"].id == author.id:
                    user_color = col
                    break

            if not user_color:
                return await interaction.response.send_message("❌ You are not part of this match.", ephemeral=True)

            self.game.game_over = True
            # Winner is next active player
            idx = self.game.turn_order.index(user_color)
            self.game.winner = self.game.turn_order[(idx + 1) % len(self.game.turn_order)]
            host_id = list(self.game.players.values())[0]["member"].id
            ACTIVE_LUDO_GAMES.pop(host_id, None)

            self.setup_buttons_game_over()
            self.game.log_history.append(f"🏳️ **{author.display_name}** surrendered the match.")
            await self.update_view(interaction)
        except Exception as e:
            print(f"[Ludo] Error in handle_forfeit: {e}")

    async def handle_rematch(self, interaction: discord.Interaction):
        try:
            author = interaction.user
            is_player = any(p["member"] and p["member"].id == author.id for p in self.game.players.values())
            if not is_player:
                return await interaction.response.send_message("❌ Only players from this match can start a rematch.", ephemeral=True)

            new_configs = []
            for col in self.game.turn_order:
                old_p = self.game.players[col]
                new_configs.append({
                    "color": col,
                    "member": old_p["member"],
                    "name": old_p["name"],
                    "is_ai": old_p["is_ai"]
                })

            new_game = LudoGame(new_configs, tokens_per_player=self.game.tokens_per_player)
            host_id = list(self.game.players.values())[0]["member"].id
            ACTIVE_LUDO_GAMES[host_id] = new_game

            new_view = LudoView(new_game)
            new_view.message = interaction.message
            await new_view.update_view(interaction)
        except Exception as e:
            print(f"[Ludo] Error in handle_rematch: {e}")

    async def on_timeout(self):
        host_id = list(self.game.players.values())[0]["member"].id
        ACTIVE_LUDO_GAMES.pop(host_id, None)
        if not self.game.game_over:
            self.game.game_over = True
            self.clear_items()
            self.game.log_history.append("⏰ **Match Abandoned:** Game timed out after inactivity.")
            await self.update_view()


# ─────────────────────────────────────────────────────────────
# 100-SECOND MULTIPLAYER MATCHMAKING LOBBY VIEW
# ─────────────────────────────────────────────────────────────

class LudoLobbyView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        host: discord.Member,
        invited_members: List[discord.Member],
        tokens_per_player: int = 2,
        add_friday: bool = False
    ):
        super().__init__(timeout=100)
        self.bot = bot
        self.host = host
        self.tokens_per_player = tokens_per_player
        self.message: Optional[discord.Message] = None
        self.start_timestamp = int(time.time()) + 100

        # Assign initial slots: Slot 0 = Red (Host)
        self.slots: Dict[str, Dict[str, Any]] = {
            "red": {"member": host, "name": host.display_name, "is_ai": False, "ready": True},
            "green": None,
            "yellow": None,
            "blue": None
        }

        # Pre-assign invited members into slots
        open_colors = ["green", "yellow", "blue"]
        for m in invited_members:
            if open_colors and m.id != host.id:
                col = open_colors.pop(0)
                self.slots[col] = {"member": m, "name": m.display_name, "is_ai": False, "ready": False}

        # If add_friday requested or host invited bot
        if add_friday and open_colors:
            col = open_colors.pop(0)
            self.slots[col] = {"member": None, "name": "Friday (AI)", "is_ai": True, "ready": True}

        self.setup_lobby_buttons()

    def get_active_count(self) -> int:
        return sum(1 for s in self.slots.values() if s is not None and s.get("ready"))

    def setup_lobby_buttons(self):
        self.clear_items()

        # Join button
        btn_join = discord.ui.Button(style=discord.ButtonStyle.success, label="Join Game", emoji="🎮", custom_id="ludo_lobby_join")
        btn_join.callback = self.handle_join
        self.add_item(btn_join)

        # Add Friday AI button
        btn_ai = discord.ui.Button(style=discord.ButtonStyle.primary, label="Add Friday AI", emoji="🤖", custom_id="ludo_lobby_ai")
        btn_ai.callback = self.handle_add_ai
        self.add_item(btn_ai)

        # Start button (Host only, enabled when >= 2 ready)
        can_start = self.get_active_count() >= 2
        btn_start = discord.ui.Button(
            style=discord.ButtonStyle.success if can_start else discord.ButtonStyle.secondary,
            label="Start Game Now",
            emoji="🚀",
            disabled=not can_start,
            custom_id="ludo_lobby_start"
        )
        btn_start.callback = self.handle_start_now
        self.add_item(btn_start)

        # Cancel button (Host only)
        btn_cancel = discord.ui.Button(style=discord.ButtonStyle.danger, label="Cancel", emoji="❌", custom_id="ludo_lobby_cancel")
        btn_cancel.callback = self.handle_cancel
        self.add_item(btn_cancel)

    def build_lobby_embed(self) -> discord.Embed:
        lines = []
        for col in COLOR_CLOCKWISE:
            theme = COLOR_THEMES[col]
            slot = self.slots[col]
            if slot is None:
                lines.append(f"{theme['emoji']} **{theme['name']} Slot:** `[ Open Slot — Click Join below ]`")
            elif slot["is_ai"]:
                lines.append(f"{theme['emoji']} **{theme['name']} Slot:** 🤖 **{slot['name']}** `[ Ready ]`")
            elif slot["ready"]:
                host_str = " *(Host)*" if slot["member"].id == self.host.id else ""
                lines.append(f"{theme['emoji']} **{theme['name']} Slot:** {slot['member'].mention}{host_str} `[ ✅ Ready ]`")
            else:
                lines.append(f"{theme['emoji']} **{theme['name']} Slot:** {slot['member'].mention} `[ ⏳ Invited — Click Join ]`")

        slots_str = "\n".join(lines)
        ready_cnt = self.get_active_count()

        desc = (
            f"👑 **Host:** {self.host.mention} · Mode: **{self.tokens_per_player} Tokens**\n"
            f"⏳ **Starts automatically:** <t:{self.start_timestamp}:R> (100s timer)\n\n"
            f"👥 **Player Rosters ({ready_cnt}/4 Ready):**\n"
            f"{slots_str}\n\n"
            f"👉 *Click **Join Game** to grab a seat, or **Add Friday AI** to fill open slots!*"
        )

        embed = discord.Embed(
            title="🎲  Ludo Royale Matchmaking Lobby",
            description=desc,
            color=0x2dd4bf,
            timestamp=datetime.now(pytz.utc)
        )
        embed.set_footer(text="Friday Ludo • Up to 4 Players Supported")
        return embed

    async def handle_join(self, interaction: discord.Interaction):
        user = interaction.user

        # Check if already joined
        for col, slot in self.slots.items():
            if slot and not slot["is_ai"] and slot["member"].id == user.id:
                if slot["ready"]:
                    return await interaction.response.send_message("✅ You are already ready in the lobby!", ephemeral=True)
                else:
                    # User accepted invite
                    slot["ready"] = True
                    self.setup_lobby_buttons()
                    await interaction.response.edit_message(embed=self.build_lobby_embed(), view=self)
                    if self.get_active_count() == 4:
                        await self.launch_game()
                    return

        # Find first open slot
        open_col = None
        for col in COLOR_CLOCKWISE:
            if self.slots[col] is None:
                open_col = col
                break

        if not open_col:
            return await interaction.response.send_message("❌ The lobby is already full (4/4 players)!", ephemeral=True)

        self.slots[open_col] = {
            "member": user,
            "name": user.display_name,
            "is_ai": False,
            "ready": True
        }
        self.setup_lobby_buttons()
        await interaction.response.edit_message(embed=self.build_lobby_embed(), view=self)

        if self.get_active_count() == 4:
            await self.launch_game()

    async def handle_add_ai(self, interaction: discord.Interaction):
        # Find first open slot
        open_col = None
        for col in COLOR_CLOCKWISE:
            if self.slots[col] is None:
                open_col = col
                break

        if not open_col:
            return await interaction.response.send_message("❌ No open slots remaining for AI!", ephemeral=True)

        self.slots[open_col] = {
            "member": None,
            "name": "Friday (AI)",
            "is_ai": True,
            "ready": True
        }
        self.setup_lobby_buttons()
        await interaction.response.edit_message(embed=self.build_lobby_embed(), view=self)

        if self.get_active_count() == 4:
            await self.launch_game()

    async def handle_start_now(self, interaction: discord.Interaction):
        if interaction.user.id != self.host.id:
            return await interaction.response.send_message("❌ Only the lobby host can force-start the match!", ephemeral=True)

        if self.get_active_count() < 2:
            return await interaction.response.send_message("⚠️ You need at least 2 players to start! Click 'Add Friday AI' to fill a slot.", ephemeral=True)

        await interaction.response.defer()
        await self.launch_game()

    async def handle_cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.host.id:
            return await interaction.response.send_message("❌ Only the lobby host can cancel this game.", ephemeral=True)

        ACTIVE_LUDO_LOBBIES.pop(self.host.id, None)
        self.stop()
        await interaction.response.edit_message(
            content="❌ **Matchmaking Lobby Cancelled by Host.**",
            embed=None,
            view=None
        )

    async def launch_game(self):
        """Builds game configurations from active ready slots and launches match."""
        ACTIVE_LUDO_LOBBIES.pop(self.host.id, None)
        self.stop()

        active_configs = []
        for col in COLOR_CLOCKWISE:
            slot = self.slots[col]
            if slot and slot.get("ready"):
                active_configs.append({
                    "color": col,
                    "member": slot.get("member"),
                    "name": slot.get("name"),
                    "is_ai": slot.get("is_ai", False)
                })

        # Fallback: if only host ready, add Friday AI automatically
        if len(active_configs) == 1:
            active_configs.append({
                "color": "yellow",
                "member": None,
                "name": "Friday (AI)",
                "is_ai": True
            })

        game = LudoGame(active_configs, tokens_per_player=self.tokens_per_player)
        ACTIVE_LUDO_GAMES[self.host.id] = game

        game_view = LudoView(game)
        game_view.message = self.message

        buf = await asyncio.to_thread(
            render_board_image,
            game.players,
            game.current_turn,
            game.last_rolls,
            game.tokens_per_player,
            []
        )
        file = discord.File(buf, filename="ludo_board.png")
        embed = game_view.build_embed(status_text="🎉 **Match Started!** May the best tactician reach Center Home!")

        if self.message:
            try:
                await self.message.edit(content=None, embed=embed, view=game_view, attachments=[file])
            except Exception as e:
                print(f"[Ludo] Failed to edit lobby into game: {e}")

        # If starting player is AI (unlikely since host is Red, but safe guard)
        await game_view.check_and_run_ai_turn()

    async def on_timeout(self):
        """When 100s timer expires, launches automatically with joined players."""
        if self.host.id in ACTIVE_LUDO_LOBBIES:
            await self.launch_game()


# ─────────────────────────────────────────────────────────────
# LUDO COG SETUP (SLASH COMMAND)
# ─────────────────────────────────────────────────────────────

class Ludo(commands.Cog, name="Ludo"):
    """Interactive multiplayer Ludo board game with 4-player support and zero-latency heuristic AI."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ludo", description="Play a 2 to 4-player game of Ludo Royale with friends or Friday AI!")
    @app_commands.describe(
        mode="Game length: Quick (2 tokens) or Classic (4 tokens)",
        player2="Mention 2nd player to invite",
        player3="Mention 3rd player to invite",
        player4="Mention 4th player to invite",
        add_friday="Include Friday AI in the match"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="⚡ Quick Mode (2 Tokens — Fast & Fun)", value="2"),
        app_commands.Choice(name="🏆 Classic Mode (4 Tokens — Full Experience)", value="4")
    ])
    async def ludo_slash(
        self,
        interaction: discord.Interaction,
        mode: Optional[str] = "2",
        player2: Optional[discord.Member] = None,
        player3: Optional[discord.Member] = None,
        player4: Optional[discord.Member] = None,
        add_friday: Optional[bool] = False
    ):
        try:
            author = interaction.user

            # Check if active game exists
            active_game = ACTIVE_LUDO_GAMES.get(author.id)
            if active_game and not active_game.is_expired():
                return await interaction.response.send_message(
                    "⚠️ You already have an active Ludo match! Finish it or click **Forfeit** before starting a new one.",
                    ephemeral=True
                )

            # Check if active lobby exists
            if author.id in ACTIVE_LUDO_LOBBIES:
                return await interaction.response.send_message(
                    "⚠️ You already have an open Matchmaking Lobby! Start it or cancel before creating another.",
                    ephemeral=True
                )

            await interaction.response.defer()

            num_tokens = int(mode or "2")
            invited_list = [p for p in (player2, player3, player4) if p is not None]

            # If user mentioned the bot itself as one of the players, set add_friday = True
            for p in invited_list:
                if p.id == self.bot.user.id or p.bot:
                    add_friday = True
            invited_list = [p for p in invited_list if not p.bot]

            # If no opponents mentioned and add_friday is False: still create lobby so friends can join or Friday can be added!
            lobby = LudoLobbyView(
                bot=self.bot,
                host=author,
                invited_members=invited_list,
                tokens_per_player=num_tokens,
                add_friday=bool(add_friday)
            )
            ACTIVE_LUDO_LOBBIES[author.id] = lobby

            embed = lobby.build_lobby_embed()

            # Mentions notification for invited members
            content = None
            if invited_list:
                mentions_str = " ".join(p.mention for p in invited_list)
                content = f"👋 {mentions_str} You have been invited to a game of **Ludo Royale** by {author.mention}!"

            msg = await interaction.followup.send(content=content, embed=embed, view=lobby)
            lobby.message = msg

        except Exception as e:
            print(f"[Ludo] Slash command error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Failed to launch Ludo: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ludo(bot))
