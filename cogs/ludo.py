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
from PIL import Image, ImageDraw, ImageFont
import os
from database import db

def get_bold_font(size: int):
    """Loads clean bold system font across Windows & Linux platforms with fallback."""
    for fn in ["arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf", "calibrib.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(fn, size)
        except Exception:
            try:
                path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", fn)
                if os.path.exists(path):
                    return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

# ─────────────────────────────────────────────────────────────
# BOARD GEOMETRY & TRACK DEFINITIONS (15x15 GRID ON 860x1010 CANVAS)
# ─────────────────────────────────────────────────────────────

CELL_SIZE = 54
BOARD_SIZE = CELL_SIZE * 15  # 810 x 810 px
CANVAS_W = 860
CANVAS_H = 1010
BOARD_X = 25
BOARD_Y = 95

TRACK_COORDS: List[Tuple[int, int]] = []
for r in range(13, 8, -1): TRACK_COORDS.append((r, 6))
for c in range(5, -1, -1): TRACK_COORDS.append((8, c))
TRACK_COORDS.append((7, 0))
for c in range(0, 6): TRACK_COORDS.append((6, c))
for r in range(5, -1, -1): TRACK_COORDS.append((r, 6))
TRACK_COORDS.append((0, 7))
for r in range(0, 6): TRACK_COORDS.append((r, 8))
for c in range(9, 15): TRACK_COORDS.append((6, c))
TRACK_COORDS.append((7, 14))
for c in range(14, 8, -1): TRACK_COORDS.append((8, c))
for r in range(9, 15): TRACK_COORDS.append((r, 8))
TRACK_COORDS.append((14, 7))
TRACK_COORDS.append((14, 6))

SAFE_TRACK_INDICES = {0, 8, 13, 21, 26, 34, 39, 47}

COLOR_TRACK_OFFSET = {
    "red": 0,
    "green": 13,
    "yellow": 26,
    "blue": 39
}

HOME_PATHS = {
    "red": [(13, 7), (12, 7), (11, 7), (10, 7), (9, 7)],
    "green": [(7, 1), (7, 2), (7, 3), (7, 4), (7, 5)],
    "yellow": [(1, 7), (2, 7), (3, 7), (4, 7), (5, 7)],
    "blue": [(7, 13), (7, 12), (7, 11), (7, 10), (7, 9)]
}

HOME_CENTERS = {
    "red": (8.0, 7.0),
    "green": (7.0, 6.0),
    "yellow": (6.0, 7.0),
    "blue": (7.0, 8.0)
}

BASE_SPOTS = {
    "green": [(1.8, 1.8), (1.8, 3.8), (3.8, 1.8), (3.8, 3.8)],
    "yellow": [(1.8, 10.8), (1.8, 12.8), (3.8, 10.8), (3.8, 12.8)],
    "red": [(10.8, 1.8), (10.8, 3.8), (12.8, 1.8), (12.8, 3.8)],
    "blue": [(10.8, 10.8), (10.8, 12.8), (12.8, 10.8), (12.8, 12.8)]
}

COLOR_THEMES = {
    "red": {"name": "Red", "emoji": "🔴", "rgb": (220, 53, 69), "highlight": (255, 75, 90)},
    "green": {"name": "Green", "emoji": "🟢", "rgb": (40, 167, 69), "highlight": (50, 205, 50)},
    "yellow": {"name": "Yellow", "emoji": "🟡", "rgb": (245, 185, 15), "highlight": (255, 215, 0)},
    "blue": {"name": "Blue", "emoji": "🔵", "rgb": (23, 162, 184), "highlight": (0, 210, 255)}
}

COLOR_CLOCKWISE = ["red", "green", "yellow", "blue"]

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

    d.rectangle([BOARD_X, BOARD_Y, BOARD_X + CELL_SIZE * 6, BOARD_Y + CELL_SIZE * 6], fill=c_green)
    d.rectangle([BOARD_X + CELL_SIZE, BOARD_Y + CELL_SIZE, BOARD_X + CELL_SIZE * 5, BOARD_Y + CELL_SIZE * 5], fill=c_white)

    d.rectangle([BOARD_X + CELL_SIZE * 9, BOARD_Y, BOARD_X + BOARD_SIZE, BOARD_Y + CELL_SIZE * 6], fill=c_yellow)
    d.rectangle([BOARD_X + CELL_SIZE * 10, BOARD_Y + CELL_SIZE, BOARD_X + CELL_SIZE * 14, BOARD_Y + CELL_SIZE * 5], fill=c_white)

    d.rectangle([BOARD_X, BOARD_Y + CELL_SIZE * 9, BOARD_X + CELL_SIZE * 6, BOARD_Y + BOARD_SIZE], fill=c_red)
    d.rectangle([BOARD_X + CELL_SIZE, BOARD_Y + CELL_SIZE * 10, BOARD_X + CELL_SIZE * 5, BOARD_Y + CELL_SIZE * 14], fill=c_white)

    d.rectangle([BOARD_X + CELL_SIZE * 9, BOARD_Y + CELL_SIZE * 9, BOARD_X + BOARD_SIZE, BOARD_Y + BOARD_SIZE], fill=c_blue)
    d.rectangle([BOARD_X + CELL_SIZE * 10, BOARD_Y + CELL_SIZE * 10, BOARD_X + CELL_SIZE * 14, BOARD_Y + CELL_SIZE * 14], fill=c_white)

    all_bases = [
        (1.8, 1.8), (1.8, 3.8), (3.8, 1.8), (3.8, 3.8),
        (1.8, 10.8), (1.8, 12.8), (3.8, 10.8), (3.8, 12.8),
        (10.8, 1.8), (10.8, 3.8), (12.8, 1.8), (12.8, 3.8),
        (10.8, 10.8), (10.8, 12.8), (12.8, 10.8), (12.8, 12.8)
    ]
    for r, c in all_bases:
        x = int(BOARD_X + c * CELL_SIZE)
        y = int(BOARD_Y + r * CELL_SIZE)
        d.ellipse([x - 24, y - 23, x + 24, y + 25], fill=(215, 220, 228))
        d.ellipse([x - 24, y - 24, x + 24, y + 24], fill=c_base_slot, outline=c_base_slot_border, width=2)

    for r in range(15):
        for c in range(15):
            in_cross = (6 <= r <= 8) or (6 <= c <= 8)
            in_center = (6 <= r <= 8) and (6 <= c <= 8)
            if in_cross and not in_center:
                x1 = BOARD_X + c * CELL_SIZE
                y1 = BOARD_Y + r * CELL_SIZE
                d.rectangle([x1, y1, x1 + CELL_SIZE, y1 + CELL_SIZE], fill=c_white, outline=c_dark_line, width=1)

    d.rectangle([BOARD_X + 6 * CELL_SIZE, BOARD_Y + 13 * CELL_SIZE, BOARD_X + 7 * CELL_SIZE, BOARD_Y + 14 * CELL_SIZE], fill=c_red, outline=c_dark_line)
    for r in range(9, 14):
        d.rectangle([BOARD_X + 7 * CELL_SIZE, BOARD_Y + r * CELL_SIZE, BOARD_X + 8 * CELL_SIZE, BOARD_Y + (r + 1) * CELL_SIZE], fill=c_red, outline=c_dark_line)

    d.rectangle([BOARD_X + 8 * CELL_SIZE, BOARD_Y + 1 * CELL_SIZE, BOARD_X + 9 * CELL_SIZE, BOARD_Y + 2 * CELL_SIZE], fill=c_yellow, outline=c_dark_line)
    for r in range(1, 6):
        d.rectangle([BOARD_X + 7 * CELL_SIZE, BOARD_Y + r * CELL_SIZE, BOARD_X + 8 * CELL_SIZE, BOARD_Y + (r + 1) * CELL_SIZE], fill=c_yellow, outline=c_dark_line)

    d.rectangle([BOARD_X + 1 * CELL_SIZE, BOARD_Y + 6 * CELL_SIZE, BOARD_X + 2 * CELL_SIZE, BOARD_Y + 7 * CELL_SIZE], fill=c_green, outline=c_dark_line)
    for c in range(1, 6):
        d.rectangle([BOARD_X + c * CELL_SIZE, BOARD_Y + 7 * CELL_SIZE, BOARD_X + (c + 1) * CELL_SIZE, BOARD_Y + 8 * CELL_SIZE], fill=c_green, outline=c_dark_line)

    d.rectangle([BOARD_X + 13 * CELL_SIZE, BOARD_Y + 8 * CELL_SIZE, BOARD_X + 14 * CELL_SIZE, BOARD_Y + 9 * CELL_SIZE], fill=c_blue, outline=c_dark_line)
    for c in range(9, 14):
        d.rectangle([BOARD_X + c * CELL_SIZE, BOARD_Y + 7 * CELL_SIZE, BOARD_X + (c + 1) * CELL_SIZE, BOARD_Y + 8 * CELL_SIZE], fill=c_blue, outline=c_dark_line)

    for r, c in [(8, 2), (2, 6), (6, 12), (12, 8)]:
        x1, y1 = BOARD_X + c * CELL_SIZE, BOARD_Y + r * CELL_SIZE
        x2, y2 = x1 + CELL_SIZE, y1 + CELL_SIZE
        d.rectangle([x1, y1, x2, y2], fill=c_safe, outline=c_dark_line)
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        d.polygon([
            (cx, cy - 15), (cx + 4, cy - 4), (cx + 15, cy - 4), (cx + 6, cy + 4),
            (cx + 10, cy + 15), (cx, cy + 8), (cx - 10, cy + 15), (cx - 6, cy + 4),
            (cx - 15, cy - 4), (cx - 4, cy - 4)
        ], fill=(212, 175, 55))

    cx1, cy1 = BOARD_X + 6 * CELL_SIZE, BOARD_Y + 6 * CELL_SIZE
    cx2, cy2 = BOARD_X + 9 * CELL_SIZE, BOARD_Y + 9 * CELL_SIZE
    mid_x, mid_y = (cx1 + cx2) // 2, (cy1 + cy2) // 2
    d.polygon([(cx1, cy1), (cx1, cy2), (mid_x, mid_y)], fill=c_green, outline=c_dark_line)
    d.polygon([(cx1, cy1), (cx2, cy1), (mid_x, mid_y)], fill=c_yellow, outline=c_dark_line)
    d.polygon([(cx2, cy1), (cx2, cy2), (mid_x, mid_y)], fill=c_blue, outline=c_dark_line)
    d.polygon([(cx1, cy2), (cx2, cy2), (mid_x, mid_y)], fill=c_red, outline=c_dark_line)

    d.rectangle([BOARD_X, BOARD_Y, BOARD_X + BOARD_SIZE - 1, BOARD_Y + BOARD_SIZE - 1], outline=(40, 44, 52), width=3)
    return img

_CACHED_BASE_BOARD = _create_base_board()


def get_token_xy(color: str, token_idx: int, steps: int) -> Tuple[float, float]:
    if steps == -1:
        r, c = BASE_SPOTS[color][token_idx]
        return (BOARD_X + c * CELL_SIZE, BOARD_Y + r * CELL_SIZE)
    if steps == 56:
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
        r, c = HOME_PATHS[color][steps - 51]
        return (BOARD_X + c * CELL_SIZE + CELL_SIZE // 2, BOARD_Y + r * CELL_SIZE + CELL_SIZE // 2)
    track_idx = (COLOR_TRACK_OFFSET[color] + steps) % 52
    r, c = TRACK_COORDS[track_idx]
    return (BOARD_X + c * CELL_SIZE + CELL_SIZE // 2, BOARD_Y + r * CELL_SIZE + CELL_SIZE // 2)


def draw_corner_player_hud(
    draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, color_name: str,
    player_info: Optional[Dict[str, Any]], roll: Optional[int], is_active: bool, align_left: bool = True
):
    if not player_info:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=12, fill=(24, 25, 29), outline=(42, 45, 52), width=1)
        draw.text((x + w // 2 - 40, y + h // 2 - 8), "[ Empty Slot ]", fill=(100, 105, 115), font=get_bold_font(12))
        return

    theme = COLOR_THEMES[color_name]
    draw.rounded_rectangle(
        [x, y, x + w, y + h], radius=12, fill=(30, 32, 38),
        outline=theme["highlight"] if is_active else (52, 55, 63), width=3 if is_active else 1
    )

    if align_left:
        dx, dy = x + 9, y + 9
        tx = x + 76
    else:
        dx, dy = x + w - 65, y + 9
        tx = x + 16

    draw.rounded_rectangle([dx + 2, dy + 2, dx + 58, dy + 58], radius=8, fill=(12, 13, 15))
    draw.rounded_rectangle([dx, dy, dx + 56, dy + 56], radius=8, fill=(255, 255, 255), outline=(210, 215, 220), width=2)

    if roll and 1 <= roll <= 6:
        coords = {
            1: [(28, 28)],
            2: [(15, 15), (41, 41)],
            3: [(15, 15), (28, 28), (41, 41)],
            4: [(15, 15), (15, 41), (41, 15), (41, 41)],
            5: [(15, 15), (15, 41), (28, 28), (41, 15), (41, 41)],
            6: [(15, 15), (15, 28), (15, 41), (41, 15), (41, 28), (41, 41)]
        }
        for px, py in coords[roll]:
            draw.ellipse([dx + px - 5, dy + py - 5, dx + px + 5, dy + py + 5], fill=theme["rgb"])
    else:
        draw.text((dx + 22, dy + 16), "?", fill=(120, 125, 135), font=get_bold_font(18))

    name = player_info["name"][:16]
    home_cnt = sum(1 for p in player_info["tokens"] if p == 56)
    draw.text((tx, y + 14), f"{theme['emoji']} {name}", fill=(255, 255, 255), font=get_bold_font(14))
    if is_active:
        draw.text((tx, y + 38), "👉 YOUR TURN!", fill=(87, 242, 135), font=get_bold_font(12))
    else:
        draw.text((tx, y + 38), f"Score: {home_cnt}/{len(player_info['tokens'])} Home", fill=(160, 165, 175), font=get_bold_font(12))


def render_board_image(
    players: Dict[str, Dict[str, Any]], current_turn: str, last_rolls: Dict[str, Optional[int]],
    tokens_per_player: int, movable_tokens: Optional[List[int]] = None
) -> io.BytesIO:
    canvas = _CACHED_BASE_BOARD.copy()
    draw = ImageDraw.Draw(canvas)

    draw_corner_player_hud(draw, 25, 10, 380, 74, "green", players.get("green"), last_rolls.get("green"), (current_turn == "green"), align_left=True)
    draw_corner_player_hud(draw, 455, 10, 380, 74, "yellow", players.get("yellow"), last_rolls.get("yellow"), (current_turn == "yellow"), align_left=False)
    draw_corner_player_hud(draw, 25, 920, 380, 74, "red", players.get("red"), last_rolls.get("red"), (current_turn == "red"), align_left=True)
    draw_corner_player_hud(draw, 455, 920, 380, 74, "blue", players.get("blue"), last_rolls.get("blue"), (current_turn == "blue"), align_left=False)

    pos_map: Dict[Tuple[int, int], List[Tuple[str, int, float, float, bool]]] = {}
    movable_set = set(movable_tokens or [])

    for col, pdata in players.items():
        for i in range(tokens_per_player):
            x, y = get_token_xy(col, i, pdata["tokens"][i])
            pos_map.setdefault((int(round(x)), int(round(y))), []).append((col, i + 1, x, y, (col == current_turn and i in movable_set)))

    font_single, font_multi_2, font_multi_4 = get_bold_font(14), get_bold_font(11), get_bold_font(9)

    for tokens_on_spot in pos_map.values():
        count = len(tokens_on_spot)
        for idx, (col, num, x, y, is_movable) in enumerate(tokens_on_spot):
            if count == 1:
                token_radius, px, py, in_badge_r, cur_font = 20, int(round(x)), int(round(y)), 11, font_single
            elif count == 2:
                token_radius, px, py, in_badge_r, cur_font = 15, int(round(x + (-13 if idx == 0 else 13))), int(round(y)), 9, font_multi_2
            else:
                ox, oy = [(-11, -11), (11, -11), (-11, 11), (11, 11)][idx % 4]
                token_radius, px, py, in_badge_r, cur_font = 12, int(round(x + ox)), int(round(y + oy)), 7, font_multi_4

            if is_movable:
                ring_r = token_radius + 4
                draw.ellipse([px - ring_r, py - ring_r, px + ring_r, py + ring_r], outline=(87, 242, 135), width=3)

            draw.ellipse([px - token_radius + 1, py - token_radius + 2, px + token_radius + 1, py + token_radius + 2], fill=(0, 0, 0, 160))
            theme = COLOR_THEMES[col]
            rim_color = (255, 255, 255) if col in ("red", "blue") else (30, 30, 30)
            draw.ellipse([px - token_radius, py - token_radius, px + token_radius, py + token_radius], fill=theme["rgb"], outline=rim_color, width=2 if count > 1 else 3)

            shine_w = max(3, token_radius // 2)
            draw.ellipse([px - token_radius + 2, py - token_radius + 2, px - token_radius + 2 + shine_w, py - token_radius + 2 + shine_w], fill=theme["highlight"])
            draw.ellipse([px - in_badge_r, py - in_badge_r, px + in_badge_r, py + in_badge_r], fill=(255, 255, 255), outline=(40, 40, 40), width=1)
            draw.text((px, py), str(num), fill=(20, 20, 20), font=cur_font, anchor="mm")

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", compress_level=1)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────────────────────
# LUDO MULTIPLAYER GAME STATE & DETERMINISTIC HEURISTIC AI
# ─────────────────────────────────────────────────────────────

class LudoGame:
    def __init__(self, players_config: List[Dict[str, Any]], tokens_per_player: int = 4):
        self.tokens_per_player = tokens_per_player
        self.players: Dict[str, Dict[str, Any]] = {}
        self.turn_order: List[str] = []
        self.guild_id: Optional[int] = None
        self.host_id: Optional[int] = None
        self.bet_pot: int = 0
        self.bet_per_player: int = 0
        self.bet_participants: List[int] = []
        self.bounty_awarded: bool = False
        self.pot_awarded: bool = False

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
        return (time.time() - self.last_updated) > 180

    def get_track_index(self, color: str, steps: int) -> int:
        return (COLOR_TRACK_OFFSET[color] + steps) % 52

    def get_legal_moves(self, color: str, roll: int) -> List[int]:
        legal = []
        for i, pos in enumerate(self.players[color]["tokens"]):
            if pos == -1 and roll == 6:
                legal.append(i)
            elif 0 <= pos < 56 and pos + roll <= 56:
                legal.append(i)
        return legal

    def apply_move(self, color: str, token_idx: int, roll: int) -> Dict[str, Any]:
        tokens = self.players[color]["tokens"]
        pos = tokens[token_idx]
        captured_info, reached_home, brought_out = None, False, False

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
                    for opp_col, opp_data in self.players.items():
                        if opp_col != color:
                            for opp_i, opp_pos in enumerate(opp_data["tokens"]):
                                if 0 <= opp_pos <= 50 and self.get_track_index(opp_col, opp_pos) == track_idx:
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
        idx = self.turn_order.index(self.current_turn)
        self.current_turn = self.turn_order[(idx + 1) % len(self.turn_order)]
        self.consecutive_sixes = 0

    def choose_ai_move(self, color: str, roll: int, legal_moves: List[int]) -> int:
        if len(legal_moves) == 1:
            return legal_moves[0]
        tokens = self.players[color]["tokens"]
        best_score, best_token = -9999, legal_moves[0]
        for t_idx in legal_moves:
            pos = tokens[t_idx]
            score = 0
            if pos >= 0 and pos + roll <= 50:
                target_track = (COLOR_TRACK_OFFSET[color] + pos + roll) % 52
                if target_track not in SAFE_TRACK_INDICES:
                    for opp_col, opp_data in self.players.items():
                        if opp_col != color:
                            for opp_pos in opp_data["tokens"]:
                                if 0 <= opp_pos <= 50 and (COLOR_TRACK_OFFSET[opp_col] + opp_pos) % 52 == target_track:
                                    score += 1500
                else:
                    score += 300
            if pos + roll == 56:
                score += 1000
            if pos == -1 and roll == 6:
                score += 500
            score += (pos + roll) * 5
            if score > best_score:
                best_score, best_token = score, t_idx
        return best_token


# ─────────────────────────────────────────────────────────────
# DISCORD INTERACTION UI: BUTTONS & LUDO VIEW
# ─────────────────────────────────────────────────────────────

class LudoRollButton(discord.ui.Button):
    def __init__(self, color_name: str, player_name: str):
        theme = COLOR_THEMES[color_name]
        btn_style = discord.ButtonStyle.danger if color_name == "red" else (
            discord.ButtonStyle.success if color_name == "green" else discord.ButtonStyle.primary
        )
        super().__init__(style=btn_style, label=f"Roll Dice ({theme['name']}: {player_name[:10]}) [45s]", emoji="🎲", row=0)

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_human_roll(interaction)


class LudoTokenSelectButton(discord.ui.Button):
    def __init__(self, token_idx: int, label: str, color_name: str):
        theme = COLOR_THEMES[color_name]
        btn_style = discord.ButtonStyle.danger if color_name == "red" else (
            discord.ButtonStyle.success if color_name == "green" else discord.ButtonStyle.primary
        )
        super().__init__(style=btn_style, label=label, emoji=theme["emoji"], row=0 if token_idx < 2 else 1)
        self.token_idx = token_idx

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_human_token_pick(interaction, self.token_idx)


class LudoForfeitConfirmView(discord.ui.View):
    def __init__(self, main_view: "LudoView", user_id: int):
        super().__init__(timeout=45)
        self.main_view = main_view
        self.user_id = user_id

    @discord.ui.button(label="Yes, Surrender Match", emoji="🏳️", style=discord.ButtonStyle.danger)
    async def confirm_forfeit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ This confirmation is not for you.", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content="🏳️ **You surrendered the match.**", view=None)
        await self.main_view.execute_forfeit(interaction.user)

    @discord.ui.button(label="Cancel, Keep Playing", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def cancel_forfeit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ This confirmation is not for you.", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content="✅ **Forfeit cancelled.** Match continues!", view=None)


class LudoForfeitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.secondary, label="Forfeit", emoji="🏳️", row=2)

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_forfeit(interaction)


class LudoRematchButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.primary, label="Play Rematch", emoji="🔄", row=0)

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_rematch(interaction)


class LudoView(discord.ui.View):
    def __init__(self, game: LudoGame):
        super().__init__(timeout=None)
        self.game = game
        self.channel: Optional[discord.abc.Messageable] = None
        self.message_id: Optional[int] = None
        self.movable_tokens: List[int] = []
        self.turn_timer_task: Optional[asyncio.Task] = None
        self.turn_deadline: float = 0
        self.consecutive_afk: int = 0
        self._lock = asyncio.Lock()
        self.setup_buttons_for_roll()

    def bind_message(self, msg: Optional[discord.Message]):
        """Stores permanent channel + message_id so edits use the bot token and never expire after 15 min."""
        if msg:
            self.message_id = msg.id
            if msg.channel:
                self.channel = msg.channel

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        print(f"[Ludo] View interaction error on {item}: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ An unexpected error occurred while processing your move.", ephemeral=True)
            else:
                await interaction.followup.send("⚠️ An unexpected error occurred while processing your move.", ephemeral=True)
        except Exception:
            pass

    def _cancel_turn_timer(self):
        if self.turn_timer_task and not self.turn_timer_task.done():
            self.turn_timer_task.cancel()
        self.turn_timer_task = None

    def _start_turn_timer(self, stage: str, legal_moves: Optional[List[int]] = None, roll: Optional[int] = None):
        self._cancel_turn_timer()
        if self.game.game_over:
            return
        cur_col = self.game.current_turn
        cur_p = self.game.players.get(cur_col)
        if not cur_p or cur_p.get("is_ai"):
            return
        self.turn_deadline = time.time() + 45
        self.turn_timer_task = asyncio.create_task(self._turn_timeout_worker(cur_col, stage, legal_moves, roll))

    async def _turn_timeout_worker(self, color: str, stage: str, legal_moves: Optional[List[int]], roll: Optional[int]):
        try:
            await asyncio.sleep(45)
            async with self._lock:
                if self.game.game_over or self.game.current_turn != color:
                    return
                cur_p = self.game.players.get(color)
                if not cur_p:
                    return

                self.consecutive_afk += 1
                self.game.last_updated = time.time()

                if self.consecutive_afk >= 16:
                    self.game.game_over = True
                    self.clear_items()
                    self.game.log_history.append("⏰ **Match Abandoned:** All players were AFK for multiple rounds.")
                    if self.game.bet_pot > 0 and not self.game.pot_awarded and self.game.guild_id:
                        try:
                            from cogs.economy import get_economy_db
                            eco_db = get_economy_db()
                            gid = str(self.game.guild_id)
                            for uid in self.game.bet_participants:
                                eco_db.delta_wallet(gid, str(uid), self.game.bet_per_player)
                                eco_db.log_tx(gid, str(uid), "ludo_refund", self.game.bet_per_player, 0, note="Ludo Inactivity Timeout Refund")
                            self.game.log_history.append(f"💰 **Wagers Refunded:** **{self.game.bet_per_player:,} Coins** returned to all participants.")
                            self.game.bet_pot = 0
                        except Exception as ex:
                            print(f"[Ludo] Timeout refund error: {ex}")
                    host_id = self.game.host_id or (list(self.game.players.values())[0]["member"].id if list(self.game.players.values())[0]["member"] else None)
                    if host_id:
                        ACTIVE_LUDO_GAMES.pop(host_id, None)
                    return await self.update_view()

                theme = COLOR_THEMES[color]
                if stage == "roll":
                    self.game.log_history.append(f"⏰ ⏳ {theme['emoji']} **{cur_p['name']}** timed out (45s elapsed)! Turn passed.")
                    self.game.advance_turn()
                    self.setup_buttons_for_roll()
                    await self.update_view()
                    await self.check_and_run_ai_turn()
                elif stage == "pick":
                    if not legal_moves:
                        self.game.advance_turn()
                        self.setup_buttons_for_roll()
                        await self.update_view()
                        await self.check_and_run_ai_turn()
                        return

                    chosen_t = self.game.choose_ai_move(color, roll or 6, legal_moves)
                    ev = self.game.apply_move(color, chosen_t, roll or 6)
                    extra_str = ""
                    if ev["brought_out"]: extra_str = " (brought token onto track! 🚀)"
                    elif ev["reached_home"]: extra_str = " (token reached Home! 🌟)"
                    elif ev["captured"]: extra_str = f" (CAPTURED {ev['captured_name']}! 💥)"

                    self.game.log_history.append(
                        f"⏰ ⏳ {theme['emoji']} **{cur_p['name']}** timed out choosing token (45s)! "
                        f"Auto-moved **Token {chosen_t+1}** by **[ {roll or 6} ]**{extra_str}"
                    )

                    if self.game.game_over:
                        await self.settle_economy()
                        self.setup_buttons_game_over()
                        host_id = self.game.host_id or (list(self.game.players.values())[0]["member"].id if list(self.game.players.values())[0]["member"] else None)
                        if host_id:
                            ACTIVE_LUDO_GAMES.pop(host_id, None)
                        return await self.update_view()

                    if (roll == 6) or ev["captured"]:
                        self.setup_buttons_for_roll()
                        await self.update_view()
                    else:
                        self.game.advance_turn()
                        self.setup_buttons_for_roll()
                        await self.update_view()
                        await self.check_and_run_ai_turn()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Ludo] Error in turn timeout worker: {e}")

    def setup_buttons_for_roll(self):
        self.clear_items()
        self.movable_tokens = []
        cur_col = self.game.current_turn
        cur_p = self.game.players[cur_col]
        self.add_item(LudoRollButton(cur_col, cur_p["name"]))
        self.add_item(LudoForfeitButton())
        if not cur_p.get("is_ai") and not self.game.game_over:
            self._start_turn_timer(stage="roll")

    def setup_buttons_for_token_pick(self, legal_moves: List[int], roll: int):
        self.clear_items()
        self.movable_tokens = legal_moves
        g = self.game
        current_col = g.current_turn
        pdata = g.players[current_col]

        for idx in legal_moves:
            pos = pdata["tokens"][idx]
            if pos == -1:
                label = f"Token {idx+1}: Release Base ➔ Start 🚀"
            elif pos + roll == 56:
                label = f"Token {idx+1}: Enter Center Home! 🌟"
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
            self.add_item(LudoTokenSelectButton(idx, label=label[:80], color_name=current_col))
        self.add_item(LudoForfeitButton())
        if not pdata.get("is_ai") and not g.game_over:
            self._start_turn_timer(stage="pick", legal_moves=legal_moves, roll=roll)

    def setup_buttons_game_over(self):
        self._cancel_turn_timer()
        self.clear_items()
        self.movable_tokens = []
        self.add_item(LudoRematchButton())

    async def settle_economy(self) -> Optional[str]:
        if not self.game.game_over or not self.game.winner:
            return None
        winner_data = self.game.players.get(self.game.winner)
        gid = str(self.game.guild_id or "")
        if not winner_data or not gid:
            return None

        notes = []
        try:
            cfg = getattr(db, "economy_config", {}).get(gid, {})
            if not (cfg.get("enabled", True) and not cfg.get("paused", False)):
                return None
            cur_name = cfg.get("currency_name", "Coins")
            cur_emoji = cfg.get("currency_emoji", "🪙")
            from cogs.economy import get_economy_db
            eco_db = get_economy_db()

            is_winner_human = not winner_data.get("is_ai", False) and winner_data.get("member") is not None
            has_friday_ai = any(p.get("is_ai", False) for p in self.game.players.values())

            if is_winner_human and has_friday_ai and not self.game.bounty_awarded:
                reward = int(cfg.get("ludo_friday_reward", 500))
                if reward > 0:
                    self.game.bounty_awarded = True
                    winner_id = str(winner_data["member"].id)
                    eco_db.get_or_init_user(gid, winner_id)
                    new_w = eco_db.delta_wallet(gid, winner_id, reward)
                    eco_db.log_tx(gid, winner_id, "ludo_friday_win", reward, new_w, note="Defeated Friday AI in Ludo Royale")
                    notes.append(f"🤖 **Friday AI Bounty:** Awarded **+{reward:,} {cur_emoji} {cur_name}** to {winner_data['member'].mention}!")

            if self.game.bet_pot > 0 and not self.game.pot_awarded:
                self.game.pot_awarded = True
                if is_winner_human:
                    winner_id = str(winner_data["member"].id)
                    new_w = eco_db.delta_wallet(gid, winner_id, self.game.bet_pot)
                    eco_db.log_tx(gid, winner_id, "ludo_pot_win", self.game.bet_pot, new_w, note=f"Won Ludo Royale wager pot ({len(self.game.players)} players)")
                    notes.append(f"💰 **Prize Pot:** {winner_data['member'].mention} collected the entire **+{self.game.bet_pot:,} {cur_emoji} {cur_name}** pot!")
                else:
                    notes.append(f"🤖 Friday AI won! The **{self.game.bet_pot:,} {cur_emoji} {cur_name}** pot was captured by Friday Treasury.")
                self.game.bet_pot = 0
        except Exception as ex:
            print(f"[Ludo] Economy settlement error: {ex}")

        if notes:
            msg = "\n".join(notes)
            self.game.log_history.append(msg)
            return msg
        return None

    def build_embed(self, status_text: Optional[str] = None) -> discord.Embed:
        g = self.game
        cur_col = g.current_turn
        cur_p = g.players[cur_col]
        theme = COLOR_THEMES[cur_col]

        title = f"🎲  Ludo Royale • 💰 Pot: {g.bet_pot:,} Coins" if (g.bet_pot > 0 and not g.game_over) else f"🎲  Ludo Royale • {len(g.turn_order)} Players"
        color = discord.Color.from_rgb(*theme["rgb"])

        if g.game_over:
            title = f"🏆  Victory! {g.players[g.winner]['name']} Won the Match!"
            color = discord.Color.green()

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

        if status_text:
            turn_box = status_text
        elif g.game_over:
            turn_box = f"🎉 **Match Concluded!** Winner: **{g.players[g.winner]['name']}**!"
        elif cur_p["is_ai"]:
            turn_box = f"🤖 **CURRENT CHANCE:** {theme['emoji']} **Friday (AI)** is calculating move..."
        elif self.movable_tokens:
            turn_box = f"🎯 **CURRENT CHANCE:** {theme['emoji']} **{cur_p['name']}**\n👉 *Pick a {theme['name']} token button below to move! (⏰ 45s Timer)*"
        else:
            turn_box = f"🎯 **CURRENT CHANCE:** {theme['emoji']} **{cur_p['name']}**\n👉 *Click your {theme['name']} 'Roll Dice' button below! (⏰ 45s Timer)*"

        embed = discord.Embed(
            title=title,
            description=f"{turn_box}\n\n📊 **Live Player Standings:**\n" + "\n".join(standings_lines) + "\n\n📜 **Match Log:**\n" + "\n".join(g.log_history[-3:]),
            color=color,
            timestamp=datetime.now(pytz.utc)
        )
        embed.set_image(url="attachment://ludo_board.png")
        footer_text = f"Friday Ludo Royale • 🏆 Prize Pot: {g.bet_pot:,} Coins • ⏰ 45s AFK Turn Timer" if g.bet_pot > 0 else "Friday Ludo Royale • ⏰ 45s AFK Turn Timer"
        embed.set_footer(text=footer_text)
        return embed

    async def update_view(self, interaction: Optional[discord.Interaction] = None, status_text: Optional[str] = None):
        """Renders board and edits via permanent channel message (bot token) so matches never expire after 15 mins."""
        try:
            buf = await asyncio.to_thread(
                render_board_image,
                self.game.players, self.game.current_turn, self.game.last_rolls,
                self.game.tokens_per_player, self.movable_tokens
            )
            embed = self.build_embed(status_text=status_text)

            if interaction and interaction.message:
                self.bind_message(interaction.message)
            if interaction and interaction.channel and not self.channel:
                self.channel = interaction.channel

            updated = False

            # 1. Primary: Edit via permanent PartialMessage (uses Bot Token — NEVER expires after 15 min)
            if self.channel and self.message_id:
                try:
                    buf.seek(0)
                    partial_msg = self.channel.get_partial_message(self.message_id)
                    await partial_msg.edit(content=None, embed=embed, view=self, attachments=[discord.File(buf, filename="ludo_board.png")])
                    updated = True
                except Exception as e:
                    print(f"[Ludo] PartialMessage edit error: {e}")

            # 2. Fallback: Direct interaction response if not yet updated
            if not updated and interaction:
                try:
                    buf.seek(0)
                    file = discord.File(buf, filename="ludo_board.png")
                    if not interaction.response.is_done():
                        await interaction.response.edit_message(content=None, embed=embed, view=self, attachments=[file])
                    else:
                        msg = await interaction.edit_original_response(content=None, embed=embed, view=self, attachments=[file])
                        self.bind_message(msg)
                    updated = True
                except Exception as ex:
                    print(f"[Ludo] Interaction edit fallback error: {ex}")

            # 3. Last-resort fallback: Send a fresh message in channel
            if not updated and self.channel:
                try:
                    buf.seek(0)
                    msg = await self.channel.send(embed=embed, view=self, file=discord.File(buf, filename="ludo_board.png"))
                    self.bind_message(msg)
                except Exception as e:
                    print(f"[Ludo] Channel send fallback error: {e}")
        except Exception as e:
            print(f"[Ludo] Critical update_view failure: {e}")

    async def handle_human_roll(self, interaction: discord.Interaction):
        try:
            cur_col = self.game.current_turn
            cur_p = self.game.players[cur_col]

            if cur_p.get("is_ai"):
                return await interaction.response.send_message("🤖 It is Friday AI's turn!", ephemeral=True)
            if not cur_p.get("member") or interaction.user.id != cur_p["member"].id:
                return await interaction.response.send_message(f"❌ It is currently {cur_p['name']}'s turn!", ephemeral=True)
            if self.game.game_over:
                return await interaction.response.send_message("🏁 This match has already ended!", ephemeral=True)

            await interaction.response.defer()
            async with self._lock:
                if self.game.game_over or self.game.current_turn != cur_col:
                    return
                self._cancel_turn_timer()
                self.consecutive_afk = 0
                self.game.last_updated = time.time()
                self.bind_message(interaction.message)

                roll = random.randint(1, 6)
                self.game.last_rolls[cur_col] = roll
                theme = COLOR_THEMES[cur_col]
                legal = self.game.get_legal_moves(cur_col, roll)

                self.game.consecutive_sixes = (self.game.consecutive_sixes + 1) if roll == 6 else 0

                if self.game.consecutive_sixes >= 3:
                    self.game.log_history.append(f"⚠️ {theme['emoji']} **{cur_p['name']}** rolled three 6s in a row! Turn forfeited.")
                    self.game.advance_turn()
                    self.setup_buttons_for_roll()
                    await self.update_view(interaction)
                    return await self.check_and_run_ai_turn()

                if not legal:
                    if roll == 6:
                        self.game.log_history.append(f"{theme['emoji']} **{cur_p['name']}** rolled a **[ {roll} ]** (no legal moves, roll again!).")
                        self.setup_buttons_for_roll()
                        await self.update_view(interaction)
                    else:
                        self.game.log_history.append(f"{theme['emoji']} **{cur_p['name']}** rolled a **[ {roll} ]** (no legal moves). Passing turn...")
                        self.game.advance_turn()
                        self.setup_buttons_for_roll()
                        await self.update_view(interaction)
                        return await self.check_and_run_ai_turn()
                    return

                action_text = "Choose which token to release from base or move:" if roll == 6 else "Choose which token to move:"
                self.game.log_history.append(f"{theme['emoji']} **{cur_p['name']}** rolled a **[ {roll} ]**! {action_text}")
                self.setup_buttons_for_token_pick(legal, roll)
                await self.update_view(interaction)
        except Exception as e:
            print(f"[Ludo] Error in handle_human_roll: {e}")
            self.setup_buttons_for_roll()
            await self.update_view(interaction)

    async def handle_human_token_pick(self, interaction: discord.Interaction, token_idx: int):
        try:
            cur_col = self.game.current_turn
            cur_p = self.game.players[cur_col]

            if cur_p.get("is_ai"):
                return await interaction.response.send_message("🤖 It is Friday AI's turn!", ephemeral=True)
            if not cur_p.get("member") or interaction.user.id != cur_p["member"].id:
                return await interaction.response.send_message(f"❌ It is currently {cur_p['name']}'s turn!", ephemeral=True)
            if self.game.game_over:
                return await interaction.response.send_message("🏁 This match has already ended!", ephemeral=True)

            await interaction.response.defer()
            async with self._lock:
                if self.game.game_over or self.game.current_turn != cur_col:
                    return
                self._cancel_turn_timer()
                self.consecutive_afk = 0
                self.game.last_updated = time.time()
                self.bind_message(interaction.message)

                roll = self.game.last_rolls.get(cur_col) or 6
                theme = COLOR_THEMES[cur_col]

                ev = self.game.apply_move(cur_col, token_idx, roll)
                extra_str = ""
                if ev["brought_out"]: extra_str = " (brought token onto track! 🚀)"
                elif ev["reached_home"]: extra_str = " (token reached Home! 🌟)"
                elif ev["captured"]: extra_str = f" (CAPTURED {ev['captured_name']}! 💥)"

                self.game.log_history.append(f"{theme['emoji']} **{cur_p['name']}** moved **Token {token_idx+1}** by **[ {roll} ]** steps{extra_str}")

                if self.game.game_over:
                    await self.settle_economy()
                    self.setup_buttons_game_over()
                    host_id = self.game.host_id or (list(self.game.players.values())[0]["member"].id if list(self.game.players.values())[0]["member"] else None)
                    if host_id:
                        ACTIVE_LUDO_GAMES.pop(host_id, None)
                    return await self.update_view(interaction)

                if roll == 6 or ev["captured"]:
                    self.setup_buttons_for_roll()
                    await self.update_view(interaction)
                else:
                    self.game.advance_turn()
                    self.setup_buttons_for_roll()
                    await self.update_view(interaction)
                    await self.check_and_run_ai_turn()
        except Exception as e:
            print(f"[Ludo] Error in handle_human_token_pick: {e}")
            self.setup_buttons_for_roll()
            await self.update_view(interaction)

    async def check_and_run_ai_turn(self):
        cur_p = self.game.players[self.game.current_turn]
        if cur_p["is_ai"] and not self.game.game_over:
            asyncio.create_task(self.run_ai_turn())

    async def run_ai_turn(self):
        try:
            await asyncio.sleep(1.6)
            async with self._lock:
                if self.game.game_over:
                    return
                cur_col = self.game.current_turn
                cur_p = self.game.players[cur_col]
                if not cur_p["is_ai"]:
                    return

                roll = random.randint(1, 6)
                self.game.last_rolls[cur_col] = roll
                legal = self.game.get_legal_moves(cur_col, roll)

                if not legal:
                    self.game.log_history.append(f"🤖 **{cur_p['name']}** rolled a **[ {roll} ]** (no legal moves).")
                    if roll == 6:
                        await self.update_view()
                        asyncio.create_task(self.run_ai_turn())
                        return
                    self.game.advance_turn()
                    self.setup_buttons_for_roll()
                    await self.update_view()
                    await self.check_and_run_ai_turn()
                    return

                chosen_t = self.game.choose_ai_move(cur_col, roll, legal)
                ev = self.game.apply_move(cur_col, chosen_t, roll)
                extra_str = ""
                if ev["brought_out"]: extra_str = " (brought token out! 🚀)"
                elif ev["reached_home"]: extra_str = " (token entered Home! 🌟)"
                elif ev["captured"]: extra_str = f" (CAPTURED {ev['captured_name']}! 💥)"

                self.game.log_history.append(f"🤖 **{cur_p['name']}** rolled a **[ {roll} ]** & moved **Token {chosen_t+1}**{extra_str}")

                if self.game.game_over:
                    await self.settle_economy()
                    self.setup_buttons_game_over()
                    host_id = self.game.host_id or (list(self.game.players.values())[0]["member"].id if list(self.game.players.values())[0]["member"] else None)
                    if host_id:
                        ACTIVE_LUDO_GAMES.pop(host_id, None)
                    return await self.update_view()

                if roll == 6 or ev["captured"]:
                    await self.update_view()
                    asyncio.create_task(self.run_ai_turn())
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
            if not any(p["member"] and p["member"].id == author.id for p in self.game.players.values()):
                return await interaction.response.send_message("❌ You are not part of this match.", ephemeral=True)
            if self.game.game_over:
                return await interaction.response.send_message("The game is already over.", ephemeral=True)
            await interaction.response.send_message(
                f"⚠️ **Are you sure you want to forfeit and exit the match, {author.mention}?**\nSurrendering will immediately concede victory to your opponents.",
                view=LudoForfeitConfirmView(self, author.id),
                ephemeral=True
            )
        except Exception as e:
            print(f"[Ludo] Error in handle_forfeit: {e}")

    async def execute_forfeit(self, author: discord.User):
        try:
            async with self._lock:
                user_color = next((col for col, p in self.game.players.items() if p["member"] and p["member"].id == author.id), None)
                if not user_color or self.game.game_over:
                    return
                self.game.game_over = True
                idx = self.game.turn_order.index(user_color)
                self.game.winner = self.game.turn_order[(idx + 1) % len(self.game.turn_order)]
                host_id = self.game.host_id or (list(self.game.players.values())[0]["member"].id if list(self.game.players.values())[0]["member"] else None)
                if host_id:
                    ACTIVE_LUDO_GAMES.pop(host_id, None)
                await self.settle_economy()
                self.setup_buttons_game_over()
                self.game.log_history.append(f"🏳️ **{author.display_name}** surrendered the match.")
                await self.update_view()
        except Exception as e:
            print(f"[Ludo] Error in execute_forfeit: {e}")

    async def handle_rematch(self, interaction: discord.Interaction):
        try:
            author = interaction.user
            if not any(p["member"] and p["member"].id == author.id for p in self.game.players.values()):
                return await interaction.response.send_message("❌ Only players from this match can start a rematch.", ephemeral=True)

            await interaction.response.defer()
            new_configs = [
                {"color": col, "member": self.game.players[col]["member"], "name": self.game.players[col]["name"], "is_ai": self.game.players[col]["is_ai"]}
                for col in self.game.turn_order
            ]
            new_game = LudoGame(new_configs, tokens_per_player=self.game.tokens_per_player)
            new_game.guild_id = self.game.guild_id
            host_id = self.game.host_id or author.id
            new_game.host_id = host_id
            new_game.log_history = ["🎲 **Rematch started!** (Friendly mode — start a new game to wager)"]
            ACTIVE_LUDO_GAMES[host_id] = new_game

            new_view = LudoView(new_game)
            new_view.bind_message(interaction.message)
            await new_view.update_view(interaction)
        except Exception as e:
            print(f"[Ludo] Error in handle_rematch: {e}")


# ─────────────────────────────────────────────────────────────
# 100-SECOND MULTIPLAYER MATCHMAKING LOBBY VIEW
# ─────────────────────────────────────────────────────────────

class LudoLobbyView(discord.ui.View):
    def __init__(
        self, bot: commands.Bot, host: discord.Member, invited_members: List[discord.Member],
        tokens_per_player: int = 4, add_friday: bool = False, bet: int = 0, guild_id: Optional[int] = None
    ):
        super().__init__(timeout=100)
        self.bot = bot
        self.host = host
        self.tokens_per_player = tokens_per_player
        self.bet = max(0, int(bet or 0))
        self.guild_id = guild_id
        self.channel: Optional[discord.abc.Messageable] = None
        self.message_id: Optional[int] = None
        self.start_timestamp = int(time.time()) + 100
        self.launching: bool = False

        self.slots: Dict[str, Optional[Dict[str, Any]]] = {
            "red": {"member": host, "name": host.display_name, "is_ai": False, "ready": True},
            "green": None, "yellow": None, "blue": None
        }

        open_colors = ["green", "yellow", "blue"]
        for m in invited_members:
            if open_colors and m.id != host.id:
                self.slots[open_colors.pop(0)] = {"member": m, "name": m.display_name, "is_ai": False, "ready": False}
        if add_friday and open_colors:
            self.slots[open_colors.pop(0)] = {"member": None, "name": "Friday (AI)", "is_ai": True, "ready": True}

        self.setup_lobby_buttons()

    def bind_message(self, msg: Optional[discord.Message]):
        if msg:
            self.message_id = msg.id
            if msg.channel:
                self.channel = msg.channel

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        print(f"[LudoLobby] Interaction error on {item}: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ An unexpected error occurred in the lobby.", ephemeral=True)
            else:
                await interaction.followup.send("⚠️ An unexpected error occurred in the lobby.", ephemeral=True)
        except Exception:
            pass

    def get_active_count(self) -> int:
        return sum(1 for s in self.slots.values() if s is not None and s.get("ready"))

    def setup_lobby_buttons(self):
        self.clear_items()
        btn_join = discord.ui.Button(style=discord.ButtonStyle.success, label="Join Game", emoji="🎮", custom_id="ludo_lobby_join")
        btn_join.callback = self.handle_join
        self.add_item(btn_join)

        btn_ai = discord.ui.Button(style=discord.ButtonStyle.primary, label="Add Friday AI", emoji="🤖", custom_id="ludo_lobby_ai")
        btn_ai.callback = self.handle_add_ai
        self.add_item(btn_ai)

        can_start = self.get_active_count() >= 2
        btn_start = discord.ui.Button(
            style=discord.ButtonStyle.success if can_start else discord.ButtonStyle.secondary,
            label="Start Game Now", emoji="🚀", disabled=not can_start, custom_id="ludo_lobby_start"
        )
        btn_start.callback = self.handle_start_now
        self.add_item(btn_start)

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

        ready_cnt = self.get_active_count()
        ready_humans = sum(1 for s in self.slots.values() if s is not None and s.get("ready") and not s.get("is_ai"))

        wager_str = ""
        if self.bet > 0 and self.guild_id:
            cfg = getattr(db, "economy_config", {}).get(str(self.guild_id), {})
            cur_name, cur_emoji = cfg.get("currency_name", "Coins"), cfg.get("currency_emoji", "🪙")
            wager_str = (
                f"💰 **Wager Stakes:** `{self.bet:,}` {cur_emoji} {cur_name} / human player\n"
                f"🏆 **Current Prize Pot:** `{self.bet * ready_humans:,}` {cur_emoji} {cur_name} ({ready_humans} player{'s' if ready_humans != 1 else ''})\n"
            )

        embed = discord.Embed(
            title="🎲  Ludo Royale Matchmaking Lobby",
            description=(
                f"👑 **Host:** {self.host.mention} · Mode: **Classic 4 Tokens**\n{wager_str}"
                f"⏳ **Starts automatically:** <t:{self.start_timestamp}:R> (100s timer)\n\n"
                f"👥 **Player Rosters ({ready_cnt}/4 Ready):**\n" + "\n".join(lines) +
                "\n\n👉 *Click **Join Game** to grab a seat, or **Add Friday AI** to fill open slots!*"
            ),
            color=0x2dd4bf,
            timestamp=datetime.now(pytz.utc)
        )
        embed.set_footer(text="Friday Ludo • Up to 4 Players Supported")
        return embed

    async def handle_join(self, interaction: discord.Interaction):
        user = interaction.user
        if self.bet > 0 and self.guild_id:
            try:
                from cogs.economy import get_economy_db
                eco_db = get_economy_db()
                gid = str(self.guild_id)
                wallet_bal = eco_db.get_or_init_user(gid, str(user.id)).get("wallet", 0)
                if wallet_bal < self.bet:
                    cur_name = getattr(db, "economy_config", {}).get(gid, {}).get("currency_name", "Coins")
                    return await interaction.response.send_message(
                        f"❌ **Insufficient Wallet Balance!** Requires **{self.bet:,} {cur_name}**, you have **{wallet_bal:,} {cur_name}**.",
                        ephemeral=True
                    )
            except Exception as ex:
                print(f"[Ludo] Join balance check error: {ex}")

        for col, slot in self.slots.items():
            if slot and not slot["is_ai"] and slot["member"].id == user.id:
                if slot["ready"]:
                    return await interaction.response.send_message("✅ You are already ready in the lobby!", ephemeral=True)
                slot["ready"] = True
                self.setup_lobby_buttons()
                if self.get_active_count() == 4:
                    await interaction.response.defer()
                    return await self.launch_game(interaction)
                return await interaction.response.edit_message(embed=self.build_lobby_embed(), view=self)

        open_col = next((c for c in COLOR_CLOCKWISE if self.slots[c] is None), None)
        if not open_col:
            return await interaction.response.send_message("❌ The lobby is already full (4/4 players)!", ephemeral=True)

        self.slots[open_col] = {"member": user, "name": user.display_name, "is_ai": False, "ready": True}
        self.setup_lobby_buttons()
        if self.get_active_count() == 4:
            await interaction.response.defer()
            await self.launch_game(interaction)
        else:
            await interaction.response.edit_message(embed=self.build_lobby_embed(), view=self)

    async def handle_add_ai(self, interaction: discord.Interaction):
        open_col = next((c for c in COLOR_CLOCKWISE if self.slots[c] is None), None)
        if not open_col:
            return await interaction.response.send_message("❌ No open slots remaining for AI!", ephemeral=True)

        self.slots[open_col] = {"member": None, "name": "Friday (AI)", "is_ai": True, "ready": True}
        self.setup_lobby_buttons()
        if self.get_active_count() == 4:
            await interaction.response.defer()
            await self.launch_game(interaction)
        else:
            await interaction.response.edit_message(embed=self.build_lobby_embed(), view=self)

    async def handle_start_now(self, interaction: discord.Interaction):
        if interaction.user.id != self.host.id:
            return await interaction.response.send_message("❌ Only the lobby host can force-start the match!", ephemeral=True)
        if self.get_active_count() < 2:
            return await interaction.response.send_message("⚠️ You need at least 2 players to start!", ephemeral=True)
        if self.launching:
            return await interaction.response.send_message("⏳ Match is already launching, please wait...", ephemeral=True)
        self.bind_message(interaction.message)
        await interaction.response.defer()
        await self.launch_game(interaction)

    async def handle_cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.host.id:
            return await interaction.response.send_message("❌ Only the lobby host can cancel this game.", ephemeral=True)
        ACTIVE_LUDO_LOBBIES.pop(self.host.id, None)
        self.stop()
        await interaction.response.edit_message(content="❌ **Matchmaking Lobby Cancelled by Host.**", embed=None, view=None)

    async def launch_game(self, interaction: Optional[discord.Interaction] = None):
        if self.launching:
            return
        self.launching = True
        ACTIVE_LUDO_LOBBIES.pop(self.host.id, None)
        if interaction and interaction.message:
            self.bind_message(interaction.message)

        active_configs = [
            {"color": col, "member": slot.get("member"), "name": slot.get("name"), "is_ai": slot.get("is_ai", False)}
            for col in COLOR_CLOCKWISE if (slot := self.slots[col]) and slot.get("ready")
        ]
        if len(active_configs) == 1:
            active_configs.append({"color": "yellow", "member": None, "name": "Friday (AI)", "is_ai": True})

        bet_pot, bet_participants = 0, []
        if self.bet > 0 and self.guild_id:
            try:
                from cogs.economy import get_economy_db
                eco_db = get_economy_db()
                gid = str(self.guild_id)
                cur_name = getattr(db, "economy_config", {}).get(gid, {}).get("currency_name", "Coins")
                failed_players = [
                    p["member"].display_name for p in active_configs
                    if not p["is_ai"] and p["member"] and eco_db.get_or_init_user(gid, str(p["member"].id)).get("wallet", 0) < self.bet
                ]
                if failed_players:
                    cancel_msg = f"❌ **Match Cancelled:** Insufficient wallet coins for **{self.bet:,} {cur_name}** wager: {', '.join(failed_players)}"
                    self.launching = False
                    self.stop()
                    if self.channel and self.message_id:
                        await self.channel.get_partial_message(self.message_id).edit(content=cancel_msg, embed=None, view=None)
                    return
                for p in active_configs:
                    if not p["is_ai"] and p["member"]:
                        uid = str(p["member"].id)
                        new_w = eco_db.delta_wallet(gid, uid, -self.bet)
                        eco_db.log_tx(gid, uid, "ludo_escrow", -self.bet, new_w, note=f"Ludo Royale Wager Escrow ({self.bet} coins)")
                        bet_pot += self.bet
                        bet_participants.append(p["member"].id)
            except Exception as ex:
                print(f"[Ludo] Launch escrow error: {ex}")

        game = LudoGame(active_configs, tokens_per_player=self.tokens_per_player)
        game.guild_id = self.guild_id
        game.host_id = self.host.id
        game.bet_pot = bet_pot
        game.bet_per_player = self.bet
        game.bet_participants = bet_participants
        ACTIVE_LUDO_GAMES[self.host.id] = game

        game_view = LudoView(game)
        game_view.channel = self.channel
        game_view.message_id = self.message_id

        try:
            await game_view.update_view(interaction, status_text="🎉 **Match Started!** May the best tactician reach Center Home!")
        finally:
            self.stop()

        await game_view.check_and_run_ai_turn()

    async def on_timeout(self):
        if self.host.id in ACTIVE_LUDO_LOBBIES:
            await self.launch_game()


# ─────────────────────────────────────────────────────────────
# LUDO COG SETUP (SLASH COMMAND)
# ─────────────────────────────────────────────────────────────

class Ludo(commands.Cog, name="Ludo"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ludo", description="Play authentic 4-token Ludo Royale with friends or Friday AI (supports coin wagers)!")
    @app_commands.describe(
        bet="Optional coin wager per human player (winner takes all)",
        player2="Mention 2nd player to invite",
        player3="Mention 3rd player to invite",
        player4="Mention 4th player to invite",
        add_friday="Include Friday AI in the match"
    )
    async def ludo_slash(
        self, interaction: discord.Interaction, bet: Optional[int] = None,
        player2: Optional[discord.Member] = None, player3: Optional[discord.Member] = None,
        player4: Optional[discord.Member] = None, add_friday: Optional[bool] = False
    ):
        try:
            await interaction.response.defer()
            author = interaction.user
            gid = str(interaction.guild_id or "")

            if bet is not None:
                if bet <= 0:
                    return await interaction.followup.send("❌ Wager amount must be greater than 0!", ephemeral=True)
                if gid:
                    cfg = getattr(db, "economy_config", {}).get(gid, {})
                    if cfg.get("paused", False):
                        return await interaction.followup.send("⏸️ The server economy is currently paused.", ephemeral=True)
                    max_bet = int(cfg.get("minigame_max_bet", 50000))
                    cur_name = cfg.get("currency_name", "Coins")
                    if bet > max_bet:
                        return await interaction.followup.send(f"❌ Maximum wager limit is **{max_bet:,} {cur_name}**!", ephemeral=True)
                    from cogs.economy import get_economy_db
                    prof = get_economy_db().get_or_init_user(gid, str(author.id))
                    if prof.get("wallet", 0) < bet:
                        return await interaction.followup.send(f"❌ Insufficient wallet balance (**{prof.get('wallet', 0):,} {cur_name}**).", ephemeral=True)

            active_game = ACTIVE_LUDO_GAMES.get(author.id)
            if active_game and not active_game.is_expired():
                return await interaction.followup.send("⚠️ You already have an active Ludo match! Finish it or click **Forfeit** first.", ephemeral=True)

            if author.id in ACTIVE_LUDO_LOBBIES:
                return await interaction.followup.send("⚠️ You already have an open Matchmaking Lobby!", ephemeral=True)

            invited_list = [p for p in (player2, player3, player4) if p is not None]
            if any(p.id == self.bot.user.id or p.bot for p in invited_list):
                add_friday = True
            invited_list = [p for p in invited_list if not p.bot]

            lobby = LudoLobbyView(
                bot=self.bot, host=author, invited_members=invited_list,
                tokens_per_player=4, add_friday=bool(add_friday), bet=bet or 0, guild_id=interaction.guild_id
            )
            ACTIVE_LUDO_LOBBIES[author.id] = lobby

            content = None
            if invited_list:
                mentions_str = " ".join(p.mention for p in invited_list)
                wager_note = f" with a **{bet:,} Coins** wager" if bet else ""
                content = f"👋 {mentions_str} You have been invited to a game of **Ludo Royale**{wager_note} by {author.mention}!"

            msg = await interaction.followup.send(content=content, embed=lobby.build_lobby_embed(), view=lobby)
            lobby.bind_message(msg)

        except Exception as e:
            print(f"[Ludo] Slash command error: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ Failed to launch Ludo: {e}", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Failed to launch Ludo: {e}", ephemeral=True)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Ludo(bot))