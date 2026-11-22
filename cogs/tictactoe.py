import discord
from discord.ext import commands
from discord import app_commands
import random
import math
import asyncio
import time
from datetime import datetime
import pytz
from typing import Optional, List, Tuple, Union

from database import db
from response_utils import make_box_embed, STATUS_COLORS, STATUS_SYMBOLS
from font_utils import clean_display_name

# Global tracking to prevent users from engaging in multiple games concurrently
# Maps user_id -> timestamp so stale/abandoned locks automatically expire after 120s
ACTIVE_PLAYERS = {}

def is_player_active(user_id: int) -> bool:
    ts = ACTIVE_PLAYERS.get(user_id)
    if not ts:
        return False
    if time.time() - ts > 120:
        ACTIVE_PLAYERS.pop(user_id, None)
        return False
    return True

def set_player_active(user_id: int):
    ACTIVE_PLAYERS[user_id] = time.time()

def clear_player_active(user_id: int):
    ACTIVE_PLAYERS.pop(user_id, None)

WIN_COMBOS = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),  # Rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),  # Columns
    (0, 4, 8), (2, 4, 6)              # Diagonals
]

# ─────────────────────────────────────────────────────────────
# AI LOGIC ENGINE (0 TOKENS, <2MS EXECUTION)
# ─────────────────────────────────────────────────────────────

def check_board_winner(board: List[Optional[str]]) -> Optional[str]:
    """Returns 'X', 'O', 'Tie', or None."""
    for a, b, c in WIN_COMBOS:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    if all(spot is not None for spot in board):
        return "Tie"
    return None

def get_winning_triplet(board: List[Optional[str]]) -> Optional[Tuple[int, int, int]]:
    """Returns the index triplet (a, b, c) of the winning line, or None."""
    for a, b, c in WIN_COMBOS:
        if board[a] and board[a] == board[b] == board[c]:
            return (a, b, c)
    return None

def get_available_spots(board: List[Optional[str]]) -> List[int]:
    return [i for i, spot in enumerate(board) if spot is None]

def ai_easy_move(board: List[Optional[str]], ai_sym: str = "O", human_sym: str = "X") -> Optional[int]:
    """Easy AI: 75% purely random moves, 25% instant win check."""
    avail = get_available_spots(board)
    if not avail:
        return None
    if random.random() < 0.25:
        for m in avail:
            board[m] = ai_sym
            if check_board_winner(board) == ai_sym:
                board[m] = None
                return m
            board[m] = None
    return random.choice(avail)

def ai_normal_move(board: List[Optional[str]], ai_sym: str = "O", human_sym: str = "X") -> Optional[int]:
    """Normal AI: Smart heuristic with intentional human-like fallibility."""
    avail = get_available_spots(board)
    if not avail:
        return None

    # 1. Take immediate win if possible
    for m in avail:
        board[m] = ai_sym
        if check_board_winner(board) == ai_sym:
            board[m] = None
            return m
        board[m] = None

    # 2. Block human win (80% awareness, 20% blunder)
    for m in avail:
        board[m] = human_sym
        if check_board_winner(board) == human_sym:
            board[m] = None
            if random.random() < 0.80:
                return m
        board[m] = None

    # 3. Take Center if open
    if 4 in avail and random.random() < 0.65:
        return 4

    # 4. Take Corners
    corners = [i for i in [0, 2, 6, 8] if i in avail]
    if corners and random.random() < 0.70:
        return random.choice(corners)

    return random.choice(avail)

def _minimax(board: List[Optional[str]], depth: int, is_max: bool, alpha: float, beta: float, ai_sym: str, human_sym: str) -> int:
    winner = check_board_winner(board)
    if winner == ai_sym:
        return 10 - depth
    if winner == human_sym:
        return depth - 10
    if winner == "Tie":
        return 0

    if is_max:
        max_eval = -math.inf
        for i in range(9):
            if board[i] is None:
                board[i] = ai_sym
                ev = _minimax(board, depth + 1, False, alpha, beta, ai_sym, human_sym)
                board[i] = None
                max_eval = max(max_eval, ev)
                alpha = max(alpha, ev)
                if beta <= alpha:
                    break
        return int(max_eval)
    else:
        min_eval = math.inf
        for i in range(9):
            if board[i] is None:
                board[i] = human_sym
                ev = _minimax(board, depth + 1, True, alpha, beta, ai_sym, human_sym)
                board[i] = None
                min_eval = min(min_eval, ev)
                beta = min(beta, ev)
                if beta <= alpha:
                    break
        return int(min_eval)

def ai_hard_move(board: List[Optional[str]], ai_sym: str = "O", human_sym: str = "X") -> Optional[int]:
    """Hard AI: Formidable & competitive AI playing optimal Minimax ~52% of the time,
    with a ~48% chance to play tactical smart heuristics so attentive human players can outplay and win."""
    avail = get_available_spots(board)
    if not avail:
        return None

    # Give skilled human players a fair 48% window to outsmart Friday and claim the Hard Mode bounty
    if random.random() < 0.48:
        return ai_normal_move(board, ai_sym=ai_sym, human_sym=human_sym)

    # Early-game heuristic shortcut (saves computation and guarantees <1ms execution)
    if len(avail) >= 9:
        return 4
    if len(avail) == 8 and 4 in avail:
        return 4
    if len(avail) == 8 and 4 not in avail:
        return 0

    best_score = -math.inf
    best_move = None
    for m in avail:
        board[m] = ai_sym
        score = _minimax(board, 0, False, -math.inf, math.inf, ai_sym, human_sym)
        board[m] = None
        if score > best_score:
            best_score = score
            best_move = m
    return best_move


# ─────────────────────────────────────────────────────────────
# DATABASE STATS HELPERS
# ─────────────────────────────────────────────────────────────

def get_player_stats(user_id: int) -> dict:
    if not hasattr(db, "tictactoe_stats") or not isinstance(db.tictactoe_stats, dict):
        db.tictactoe_stats = {}
    return db.tictactoe_stats.setdefault(str(user_id), {
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "games_played": 0,
        "vs_ai_wins": 0,
        "vs_ai_losses": 0,
        "vs_ai_ties": 0,
        "vs_pvp_wins": 0,
        "vs_pvp_losses": 0,
        "vs_pvp_ties": 0
    })

def update_game_stats(player_x: discord.Member, player_o: Union[discord.Member, discord.ClientUser], winner: Optional[str], is_ai: bool):
    try:
        if is_ai:
            x_stats = get_player_stats(player_x.id)
            x_stats["games_played"] += 1
            if winner == "X":
                x_stats["wins"] += 1
                x_stats["vs_ai_wins"] += 1
            elif winner == "O":
                x_stats["losses"] += 1
                x_stats["vs_ai_losses"] += 1
            elif winner == "Tie":
                x_stats["ties"] += 1
                x_stats["vs_ai_ties"] += 1
        else:
            x_stats = get_player_stats(player_x.id)
            o_stats = get_player_stats(player_o.id)
            x_stats["games_played"] += 1
            o_stats["games_played"] += 1

            if winner == "X":
                x_stats["wins"] += 1
                x_stats["vs_pvp_wins"] += 1
                o_stats["losses"] += 1
                o_stats["vs_pvp_losses"] += 1
            elif winner == "O":
                o_stats["wins"] += 1
                o_stats["vs_pvp_wins"] += 1
                x_stats["losses"] += 1
                x_stats["vs_pvp_losses"] += 1
            elif winner == "Tie":
                x_stats["ties"] += 1
                x_stats["vs_pvp_ties"] += 1
                o_stats["ties"] += 1
                o_stats["vs_pvp_ties"] += 1

        db.save_data()
    except Exception as e:
        print(f"[TicTacToe] Error saving stats: {e}")


# ─────────────────────────────────────────────────────────────
# DISCORD UI INTERACTION: 3x3 BUTTON GRID & GAME VIEW
# ─────────────────────────────────────────────────────────────

class TicTacToeTileButton(discord.ui.Button):
    def __init__(self, x: int, y: int, index: int):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="·",
            row=y
        )
        self.x = x
        self.y = y
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeGameView = self.view
        await view.handle_move(interaction, self.index, self)


class ForfeitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Forfeit",
            emoji="🏳️",
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeGameView = self.view
        await view.handle_forfeit(interaction)


class RematchButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="Play Rematch",
            emoji="🔄",
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeGameView = self.view
        await view.handle_rematch(interaction)


class TicTacToeGameView(discord.ui.View):
    def __init__(
        self,
        player_x: discord.Member,
        player_o: Union[discord.Member, discord.ClientUser],
        is_ai: bool = False,
        difficulty: str = "Normal",
        bot: Optional[commands.Bot] = None,
        guild_id: Optional[int] = None,
        bet_pot: int = 0,
        bet_per_player: int = 0
    ):
        super().__init__(timeout=90)
        self.player_x = player_x
        self.player_o = player_o
        self.is_ai = is_ai
        self.difficulty = difficulty
        self.bot = bot
        self.guild_id = guild_id
        self.bet_pot = bet_pot
        self.bet_per_player = bet_per_player

        self.board: List[Optional[str]] = [None] * 9
        self.current_turn = "X"
        self.game_over = False
        self.message: Optional[discord.Message] = None
        self.start_time = time.time()
        self.buttons: List[TicTacToeTileButton] = []

        # Populate the 3x3 button grid
        for i in range(9):
            x_pos = i % 3
            y_pos = i // 3
            btn = TicTacToeTileButton(x=x_pos, y=y_pos, index=i)
            self.buttons.append(btn)
            self.add_item(btn)

        # Add Forfeit button in row 3
        self.forfeit_btn = ForfeitButton()
        self.add_item(self.forfeit_btn)

        # Register players in active pool
        set_player_active(self.player_x.id)
        if not self.is_ai and hasattr(self.player_o, "id"):
            set_player_active(self.player_o.id)

    def cleanup_active_players(self):
        clear_player_active(self.player_x.id)
        if hasattr(self.player_o, "id"):
            clear_player_active(self.player_o.id)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        print(f"[TicTacToe] View interaction error on {item}: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ An unexpected error occurred while processing your move.", ephemeral=True)
            else:
                await interaction.followup.send("⚠️ An unexpected error occurred while processing your move.", ephemeral=True)
        except Exception:
            pass

    def build_status_embed(self, status: str = "info", notice: str = None) -> discord.Embed:
        colors = {
            "info": 0x5865F2,     # Blurple
            "success": 0x57F287,  # Emerald Green
            "error": 0xED4245,    # Coral Red
            "warning": 0xFEE75C,  # Amber Gold
            "neutral": 0x95A5A6   # Soft Gray
        }
        color = colors.get(status.lower(), 0x5865F2)

        title = f"🎮  Tic-Tac-Toe • {'Friday AI' if self.is_ai else 'PvP Challenge'}"

        # Fetch Player Stats for Live Scoreboard
        x_stats = get_player_stats(self.player_x.id)
        p1_name = getattr(self.player_x, "display_name", "Player 1")

        if self.is_ai:
            p2_name = "Friday (AI)"
            p2_line = f"• ⭕ **Friday (AI):** `{self.difficulty} Mode`"
            matchup_str = f"❌ {self.player_x.mention} vs ⭕ **Friday** (`{self.difficulty}`)"
        else:
            p2_name = getattr(self.player_o, "display_name", "Player 2")
            o_stats = get_player_stats(self.player_o.id) if hasattr(self.player_o, "id") else None
            p2_stats_str = f"`{o_stats['wins']}W · {o_stats['losses']}L · {o_stats['ties']}T`" if o_stats else "`N/A`"
            p2_line = f"• ⭕ **{p2_name}:** {p2_stats_str}"
            matchup_str = f"❌ {self.player_x.mention} vs ⭕ {getattr(self.player_o, 'mention', '**Player 2**')}"

        scoreboard_str = (
            f"📊 **Scoreboard & Records:**\n"
            f"• ❌ **{p1_name}:** `{x_stats['wins']}W · {x_stats['losses']}L · {x_stats['ties']}T`\n"
            f"{p2_line}"
        )

        # Economy Wager & Hard Mode Bounty Indicators
        gid_str = str(self.guild_id or (self.player_x.guild.id if hasattr(self.player_x, "guild") and self.player_x.guild else ""))
        cfg = getattr(db, "economy_config", {}).get(gid_str, {})
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")
        if self.bet_pot > 0:
            scoreboard_str += f"\n💰 **Wager Pot in Escrow:** **{self.bet_pot:,} {cur_emoji} {cur_name}** ({self.bet_per_player:,} from each)"
        elif self.is_ai and self.difficulty == "Hard":
            bounty = int(cfg.get("tictactoe_hard_reward", 500))
            if bounty > 0:
                scoreboard_str += f"\n🏆 **Hard Mode Bounty:** Beat Friday AI to win **+{bounty:,} {cur_emoji} {cur_name}**!"

        cur_user = self.player_x if self.current_turn == "X" else self.player_o
        cur_mention = cur_user.mention if hasattr(cur_user, "mention") else "**Friday**"
        cur_sym = "❌" if self.current_turn == "X" else "⭕"

        if not self.game_over:
            turn_indicator = (
                f"🎯 **CURRENT CHANCE:** {cur_sym} {cur_mention}\n"
                f"👉 *Click an empty tile on the grid below to place your {cur_sym}!*"
            )
            desc_parts = [
                f"👥 **Matchup:** {matchup_str}",
                scoreboard_str,
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ]
            if notice:
                desc_parts.append(notice)
            desc_parts.append(turn_indicator)
            desc = "\n\n".join(desc_parts)
        else:
            # End of Match Score Card
            elapsed = int(time.time() - self.start_time)
            score_card = (
                f"📋 **MATCH SCORE CARD**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{notice or 'Match concluded.'}\n"
                f"• **Duration:** `{elapsed}s`\n\n"
                f"{scoreboard_str}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👉 *Click **Play Rematch** below to play another round!*"
            )
            desc = f"👥 **Matchup:** {matchup_str}\n\n{score_card}"

        embed = discord.Embed(
            title=title,
            description=desc,
            color=color,
            timestamp=datetime.now(pytz.utc)
        )
        embed.set_footer(text="Friday Games • 90s Turn Timer")
        return embed

    async def handle_move(self, interaction: discord.Interaction, index: int, button: TicTacToeTileButton):
        try:
            if self.game_over:
                return await interaction.response.defer()

            # Keep message reference updated
            if interaction.message:
                self.message = interaction.message

            # 1. Turn and Authorization Verification
            expected_user = self.player_x if self.current_turn == "X" else self.player_o
            if interaction.user.id != expected_user.id:
                if interaction.user.id in (getattr(self.player_x, "id", None), getattr(self.player_o, "id", None)):
                    return await interaction.response.send_message(
                        f"⏳ It is not your turn! Please wait for {expected_user.mention} to play (`{self.current_turn}`).",
                        ephemeral=True
                    )
                else:
                    return await interaction.response.send_message(
                        "🚫 You are not participating in this game! Start your own with `/tictactoe`.",
                        ephemeral=True
                    )

            if self.board[index] is not None:
                return await interaction.response.defer()

            # 2. Apply Move for Current Player
            move_symbol = self.current_turn
            self.board[index] = move_symbol
            button.label = "❌" if move_symbol == "X" else "⭕"
            button.style = discord.ButtonStyle.danger if move_symbol == "X" else discord.ButtonStyle.primary
            button.disabled = True

            # Check for victory or tie
            winner = check_board_winner(self.board)
            if winner:
                return await self.finish_game(interaction, winner)

            # 3. AI Turn (if in PvE mode)
            if self.is_ai:
                ai_sym = "O" if move_symbol == "X" else "X"
                human_sym = move_symbol
                if self.difficulty == "Easy":
                    ai_idx = ai_easy_move(self.board, ai_sym=ai_sym, human_sym=human_sym)
                elif self.difficulty == "Hard":
                    ai_idx = ai_hard_move(self.board, ai_sym=ai_sym, human_sym=human_sym)
                else:
                    ai_idx = ai_normal_move(self.board, ai_sym=ai_sym, human_sym=human_sym)

                if ai_idx is not None:
                    self.board[ai_idx] = ai_sym
                    ai_btn = self.buttons[ai_idx]
                    ai_btn.label = "❌" if ai_sym == "X" else "⭕"
                    ai_btn.style = discord.ButtonStyle.danger if ai_sym == "X" else discord.ButtonStyle.primary
                    ai_btn.disabled = True

                ai_winner = check_board_winner(self.board)
                if ai_winner:
                    return await self.finish_game(interaction, ai_winner)

                # Turn returns to Human
                self.current_turn = human_sym
                embed = self.build_status_embed()
                return await interaction.response.edit_message(embed=embed, view=self)

            # 4. Switch Turns for PvP
            self.current_turn = "O" if self.current_turn == "X" else "X"
            embed = self.build_status_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            print(f"[TicTacToe] Error in handle_move: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ An error occurred while processing your move.", ephemeral=True)

    async def finish_game(self, interaction: Optional[discord.Interaction], winner: str):
        self.game_over = True
        self.cleanup_active_players()

        # Highlight the winning triplet in vibrant emerald success style
        winning_line = get_winning_triplet(self.board)
        if winning_line:
            for idx in winning_line:
                self.buttons[idx].style = discord.ButtonStyle.success

        # Disable all board buttons
        for btn in self.buttons:
            btn.disabled = True

        # Remove forfeit button, add rematch button
        if hasattr(self, "forfeit_btn") and self.forfeit_btn in self.children:
            self.remove_item(self.forfeit_btn)
        self.add_item(RematchButton())

        # Extend timeout for rematch decision (2 minutes)
        self.timeout = 120

        elapsed = int(time.time() - self.start_time)

        if winner == "X":
            notice = f"🏆 **Victory:** {self.player_x.mention} (❌) has won the match in {elapsed}s!"
            status = "success"
        elif winner == "O":
            winner_mention = "Friday" if self.is_ai else self.player_o.mention
            notice = f"🏆 **Victory:** {winner_mention} (⭕) has won the match in {elapsed}s!"
            status = "error" if self.is_ai else "success"
        else:
            notice = f"🤝 **Stalemate!** Both players tied after {elapsed}s of intense play."
            status = "neutral"

        # Economy Settlement (Hard Mode Bounty & High-Stakes Pot)
        gid = str(self.guild_id or (self.player_x.guild.id if hasattr(self.player_x, "guild") and self.player_x.guild else ""))
        if gid:
            cfg = getattr(db, "economy_config", {}).get(gid, {})
            eco_enabled = cfg.get("enabled", True) and not cfg.get("paused", False)
            cur_name = cfg.get("currency_name", "Coins")
            cur_emoji = cfg.get("currency_emoji", "🪙")

            if eco_enabled:
                try:
                    from cogs.economy import get_economy_db
                    eco_db = get_economy_db()

                    # 1. Hard Mode AI Bounty
                    if self.is_ai and self.difficulty == "Hard":
                        human_user = self.player_x if getattr(self.player_o, "id", 0) == getattr(self.bot.user, "id", 0) else self.player_o
                        human_sym = "X" if human_user.id == self.player_x.id else "O"
                        if winner == human_sym:
                            reward = int(cfg.get("tictactoe_hard_reward", 500))
                            if reward > 0:
                                eco_db.get_or_init_user(gid, str(human_user.id))
                                new_w = eco_db.delta_wallet(gid, str(human_user.id), reward)
                                eco_db.log_tx(gid, str(human_user.id), "tictactoe_hard_win", reward, new_w, note="Defeated Friday AI on Hard Mode")
                                notice += f"\n💰 **Hard Mode Bounty:** Awarded **+{reward:,} {cur_emoji} {cur_name}** into cash wallet!"

                    # 2. PvP Bet Pot Payout / Refund
                    elif self.bet_pot > 0:
                        if winner in ("X", "O"):
                            win_user = self.player_x if winner == "X" else self.player_o
                            lose_user = self.player_o if winner == "X" else self.player_x
                            new_w = eco_db.delta_wallet(gid, str(win_user.id), self.bet_pot)
                            eco_db.log_tx(gid, str(win_user.id), "tictactoe_pot_win", self.bet_pot, new_w, related_uid=str(lose_user.id), note="Won Tic-Tac-Toe Wager Pot")
                            notice += f"\n💰 **High-Stakes Payout:** {win_user.mention} claimed the entire **+{self.bet_pot:,} {cur_emoji} {cur_name}** prize pot!"
                            self.bet_pot = 0
                        elif winner == "Tie":
                            eco_db.delta_wallet(gid, str(self.player_x.id), self.bet_per_player)
                            eco_db.delta_wallet(gid, str(self.player_o.id), self.bet_per_player)
                            eco_db.log_tx(gid, str(self.player_x.id), "tictactoe_refund", self.bet_per_player, 0, note="Tic-Tac-Toe Tie Refund")
                            eco_db.log_tx(gid, str(self.player_o.id), "tictactoe_refund", self.bet_per_player, 0, note="Tic-Tac-Toe Tie Refund")
                            notice += f"\n🤝 **Wager Refunded:** **{self.bet_per_player:,} {cur_emoji} {cur_name}** returned to both players."
                            self.bet_pot = 0
                except Exception as ex:
                    print(f"[TicTacToe] Economy settlement error: {ex}")

        update_game_stats(self.player_x, self.player_o, winner, self.is_ai)

        embed = self.build_status_embed(status=status, notice=notice)

        if interaction and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        elif self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass

    async def handle_forfeit(self, interaction: discord.Interaction):
        try:
            if self.game_over:
                return await interaction.response.defer()

            if interaction.message:
                self.message = interaction.message

            allowed_ids = [self.player_x.id]
            if hasattr(self.player_o, "id"):
                allowed_ids.append(self.player_o.id)

            if interaction.user.id not in allowed_ids:
                return await interaction.response.send_message("❌ You are not part of this game.", ephemeral=True)

            self.game_over = True
            self.cleanup_active_players()

            for btn in self.buttons:
                btn.disabled = True

            if hasattr(self, "forfeit_btn") and self.forfeit_btn in self.children:
                self.remove_item(self.forfeit_btn)
            self.add_item(RematchButton())
            self.timeout = 120

            forfeiter = interaction.user
            if forfeiter.id == self.player_x.id:
                winner_user = self.player_o
                winner_sym = "⭕"
                winner_db = "O"
            else:
                winner_user = self.player_x
                winner_sym = "❌"
                winner_db = "X"

            winner_mention = "Friday" if self.is_ai else winner_user.mention
            notice = f"🏳️ **Forfeit:** {forfeiter.mention} surrendered the match.\n🏆 **Winner by Forfeit:** {winner_mention} ({winner_sym})!"

            if self.bet_pot > 0 and not self.is_ai:
                gid = str(self.guild_id or (self.player_x.guild.id if hasattr(self.player_x, "guild") and self.player_x.guild else ""))
                if gid:
                    try:
                        from cogs.economy import get_economy_db
                        eco_db = get_economy_db()
                        cfg = getattr(db, "economy_config", {}).get(gid, {})
                        cur_name = cfg.get("currency_name", "Coins")
                        cur_emoji = cfg.get("currency_emoji", "🪙")
                        new_w = eco_db.delta_wallet(gid, str(winner_user.id), self.bet_pot)
                        eco_db.log_tx(gid, str(winner_user.id), "tictactoe_pot_win", self.bet_pot, new_w, related_uid=str(forfeiter.id), note="Won Tic-Tac-Toe via Forfeit")
                        notice += f"\n💰 **Prize Claimed:** {winner_user.mention} collected the **{self.bet_pot:,} {cur_emoji} {cur_name}** pot!"
                        self.bet_pot = 0
                    except Exception as ex:
                        print(f"[TicTacToe] Forfeit economy error: {ex}")

            update_game_stats(self.player_x, self.player_o, winner_db, self.is_ai)

            embed = self.build_status_embed(status="warning", notice=notice)
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            print(f"[TicTacToe] Error in handle_forfeit: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Error handling forfeit.", ephemeral=True)

    async def handle_rematch(self, interaction: discord.Interaction):
        try:
            allowed_ids = []
            if hasattr(self.player_x, "id"):
                allowed_ids.append(self.player_x.id)
            if hasattr(self.player_o, "id"):
                allowed_ids.append(self.player_o.id)

            if interaction.user.id not in allowed_ids:
                return await interaction.response.send_message("❌ Only match participants can trigger a rematch.", ephemeral=True)

            # Clear any stale lock before initializing rematch
            self.cleanup_active_players()
            self.stop()

            # The participant who clicked 'Play Rematch' is ready at their keyboard and gets First Turn (Player 1, 'X')!
            rematch_initiator = interaction.user

            bot_obj = self.bot or getattr(interaction.client, "user", None)
            bot_user = getattr(self.bot, "user", None) or interaction.client.user

            if self.is_ai:
                # In PvE: Human is always Player 1 ('X'), Friday is Player 2 ('O')
                new_view = TicTacToeGameView(
                    player_x=rematch_initiator,
                    player_o=bot_user,
                    is_ai=True,
                    difficulty=self.difficulty,
                    bot=self.bot or interaction.client
                )
            else:
                # In PvP: The player who clicked Rematch plays as Player 1 ('X') and starts first!
                other_player = self.player_o if rematch_initiator.id == self.player_x.id else self.player_x
                new_view = TicTacToeGameView(
                    player_x=rematch_initiator,
                    player_o=other_player,
                    is_ai=False,
                    bot=self.bot or interaction.client
                )

            embed = new_view.build_status_embed(
                status="info",
                notice=f"🔄 **Rematch initiated by {rematch_initiator.mention}!**"
            )
            await interaction.response.edit_message(embed=embed, view=new_view)
            new_view.message = interaction.message
        except Exception as e:
            print(f"[TicTacToe] Error in handle_rematch: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Could not start rematch. Please start a new game with `/tictactoe`.", ephemeral=True)

    async def on_timeout(self):
        self.cleanup_active_players()
        if not self.game_over:
            self.game_over = True
            for btn in self.buttons:
                btn.disabled = True
            if hasattr(self, "forfeit_btn") and self.forfeit_btn in self.children:
                self.remove_item(self.forfeit_btn)
            self.add_item(RematchButton())

            cur_user = self.player_x if self.current_turn == "X" else self.player_o
            cur_name = getattr(cur_user, "display_name", "Friday")
            notice = f"⏰ **Game Timed Out:** Match concluded due to 90s inactivity on {cur_name}'s turn."

            if self.bet_pot > 0:
                gid = str(self.guild_id or (self.player_x.guild.id if hasattr(self.player_x, "guild") and self.player_x.guild else ""))
                if gid:
                    try:
                        from cogs.economy import get_economy_db
                        eco_db = get_economy_db()
                        cfg = getattr(db, "economy_config", {}).get(gid, {})
                        cur_name = cfg.get("currency_name", "Coins")
                        cur_emoji = cfg.get("currency_emoji", "🪙")
                        eco_db.delta_wallet(gid, str(self.player_x.id), self.bet_per_player)
                        if hasattr(self.player_o, "id"):
                            eco_db.delta_wallet(gid, str(self.player_o.id), self.bet_per_player)
                        eco_db.log_tx(gid, str(self.player_x.id), "tictactoe_refund", self.bet_per_player, 0, note="Tic-Tac-Toe Inactivity Refund")
                        if hasattr(self.player_o, "id"):
                            eco_db.log_tx(gid, str(self.player_o.id), "tictactoe_refund", self.bet_per_player, 0, note="Tic-Tac-Toe Inactivity Refund")
                        notice += f"\n🤝 **Wager Refunded:** Inactive match refunded **{self.bet_per_player:,} {cur_emoji} {cur_name}** to players."
                        self.bet_pot = 0
                    except Exception as ex:
                        print(f"[TicTacToe] Timeout refund error: {ex}")

            if self.message:
                try:
                    embed = self.build_status_embed(
                        status="warning",
                        notice=notice
                    )
                    await self.message.edit(embed=embed, view=self)
                except Exception:
                    pass
        else:
            # Rematch window expired: disable rematch button
            for item in self.children:
                item.disabled = True
            if self.message:
                try:
                    await self.message.edit(view=self)
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────
# PVP CHALLENGE INVITATION VIEW
# ─────────────────────────────────────────────────────────────

class ChallengeInviteView(discord.ui.View):
    def __init__(
        self,
        challenger: Union[discord.Member, discord.User],
        target: Union[discord.Member, discord.User],
        bot: commands.Bot,
        first_turn: str = "challenger",
        bet: int = 0,
        guild_id: Optional[int] = None
    ):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.target = target
        self.bot = bot
        self.first_turn = first_turn
        self.bet = bet
        self.guild_id = guild_id
        self.message: Optional[discord.Message] = None

        set_player_active(self.challenger.id)
        set_player_active(self.target.id)

    def cleanup(self):
        clear_player_active(self.challenger.id)
        clear_player_active(self.target.id)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        print(f"[TicTacToeInvite] Interaction error on {item}: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ An unexpected error occurred with the challenge invite.", ephemeral=True)
            else:
                await interaction.followup.send("⚠️ An unexpected error occurred with the challenge invite.", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="Accept Challenge", style=discord.ButtonStyle.success, emoji="⚔️")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.user.id != self.target.id:
                return await interaction.response.send_message(
                    f"❌ Only {self.target.mention} can accept this invitation.",
                    ephemeral=True
                )

            # If wager is set, verify cash balances and lock escrow
            bet_pot = 0
            bet_per_player = 0
            cur_name = "Coins"
            cur_emoji = "🪙"
            if self.bet > 0:
                gid = str(self.guild_id or (self.challenger.guild.id if hasattr(self.challenger, "guild") else ""))
                if gid:
                    from cogs.economy import get_economy_db
                    eco_db = get_economy_db()
                    cfg = getattr(db, "economy_config", {}).get(gid, {})
                    cur_name = cfg.get("currency_name", "Coins")
                    cur_emoji = cfg.get("currency_emoji", "🪙")

                    p1_prof = eco_db.get_or_init_user(gid, str(self.challenger.id))
                    p2_prof = eco_db.get_or_init_user(gid, str(self.target.id))

                    if p1_prof["wallet"] < self.bet:
                        self.cleanup()
                        return await interaction.response.send_message(
                            f"❌ {self.challenger.mention} no longer has enough {cur_name} in their wallet ({p1_prof['wallet']:,} / {self.bet:,})!",
                            ephemeral=True
                        )
                    if p2_prof["wallet"] < self.bet:
                        self.cleanup()
                        return await interaction.response.send_message(
                            f"❌ You do not have enough {cur_name} in your cash wallet to accept this wager ({p2_prof['wallet']:,} / {self.bet:,})!",
                            ephemeral=True
                        )

                    # Deduct from both into escrow
                    eco_db.delta_wallet(gid, str(self.challenger.id), -self.bet)
                    eco_db.delta_wallet(gid, str(self.target.id), -self.bet)
                    eco_db.log_tx(gid, str(self.challenger.id), "tictactoe_escrow", -self.bet, p1_prof["wallet"] - self.bet, related_uid=str(self.target.id), note="Tic-Tac-Toe Wager Escrow")
                    eco_db.log_tx(gid, str(self.target.id), "tictactoe_escrow", -self.bet, p2_prof["wallet"] - self.bet, related_uid=str(self.challenger.id), note="Tic-Tac-Toe Wager Escrow")

                    bet_pot = self.bet * 2
                    bet_per_player = self.bet

            # Decide who is Player 1 (X, goes first)
            toss_notice = ""
            if self.first_turn == "random":
                p1 = random.choice([self.challenger, self.target])
                p2 = self.target if p1.id == self.challenger.id else self.challenger
                toss_notice = f"🪙 **Coin Toss:** {p1.mention} won the toss and gets the first move (❌)!"
            elif self.first_turn == "opponent":
                p1 = self.target
                p2 = self.challenger
            else:
                p1 = self.challenger
                p2 = self.target

            # Launch Game View
            game_view = TicTacToeGameView(
                player_x=p1,
                player_o=p2,
                is_ai=False,
                bot=self.bot or interaction.client,
                guild_id=self.guild_id,
                bet_pot=bet_pot,
                bet_per_player=bet_per_player
            )
            notice_lines = [f"⚔️ **Challenge Accepted!** {self.target.mention} joined the battlefield."]
            if bet_pot > 0:
                notice_lines.append(f"💰 **High-Stakes Wager Active:** **{bet_pot:,} {cur_emoji} {cur_name}** prize pot locked in escrow!")
            if toss_notice:
                notice_lines.append(toss_notice)
                notice_lines.append(toss_notice)

            embed = game_view.build_status_embed(
                status="info",
                notice="\n".join(notice_lines)
            )
            await interaction.response.edit_message(embed=embed, view=game_view)
            game_view.message = interaction.message
            self.stop()
        except Exception as e:
            print(f"[TicTacToe] Error accepting challenge: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Error accepting challenge.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.user.id != self.target.id:
                return await interaction.response.send_message(
                    f"❌ Only {self.target.mention} can decline this invitation.",
                    ephemeral=True
                )

            self.cleanup()
            for item in self.children:
                item.disabled = True

            embed = discord.Embed(
                title="🎮  Tic-Tac-Toe • Challenge Declined",
                description=f"❌ {self.target.mention} declined the challenge from {self.challenger.mention}.",
                color=0xED4245,
                timestamp=datetime.now(pytz.utc)
            )
            embed.set_footer(text="Friday Games")
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
        except Exception as e:
            print(f"[TicTacToe] Error declining challenge: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Error declining challenge.", ephemeral=True)

    async def on_timeout(self):
        self.cleanup()
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                embed = discord.Embed(
                    title="🎮  Tic-Tac-Toe • Invitation Expired",
                    description=f"⏰ Challenge from {self.challenger.mention} to {self.target.mention} expired (no response within 60s).",
                    color=0x95A5A6,
                    timestamp=datetime.now(pytz.utc)
                )
                embed.set_footer(text="Friday Games")
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────
# TIC-TAC-TOE COG SETUP (SLASH COMMANDS ONLY)
# ─────────────────────────────────────────────────────────────

class TicTacToe(commands.Cog, name="Games"):
    """Sleek interactive Tic-Tac-Toe (X and O) game against members or Friday AI."""

    ttt_group = app_commands.Group(name="tictactoe", description="Tic-Tac-Toe minigame and player statistics")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @ttt_group.command(name="play", description="Play Tic-Tac-Toe (X and O) against a friend or Friday AI!")
    @app_commands.describe(
        opponent="Member to challenge (leave blank to play against Friday AI)",
        difficulty="Friday AI difficulty mode (Easy, Normal, Hard)",
        first_turn="Who plays first as 'X' (You, Opponent, or Random coin toss)",
        bet="Optional coin wager (each player contributes this amount to the winner pot)"
    )
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="Easy (Casual & Fun)", value="Easy"),
        app_commands.Choice(name="Normal (Balanced & Smart)", value="Normal"),
        app_commands.Choice(name="Hard (Challenging & Rewarding)", value="Hard")
    ])
    @app_commands.choices(first_turn=[
        app_commands.Choice(name="You (Challenger goes first)", value="challenger"),
        app_commands.Choice(name="Opponent (Opponent / Friday goes first)", value="opponent"),
        app_commands.Choice(name="🎲 Random (Coin toss decides who goes first)", value="random")
    ])
    async def tictactoe_slash(
        self,
        interaction: discord.Interaction,
        opponent: Optional[Union[discord.Member, discord.User]] = None,
        difficulty: Optional[str] = "Normal",
        first_turn: Optional[str] = "challenger",
        bet: Optional[int] = None
    ):
        try:
            await self._start_game_flow(interaction, opponent, difficulty or "Normal", first_turn or "challenger", bet)
        except Exception as e:
            print(f"[TicTacToe] Slash command error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Failed to start game: {e}", ephemeral=True)

    async def _start_game_flow(
        self,
        interaction: discord.Interaction,
        opponent: Optional[Union[discord.Member, discord.User]],
        difficulty: str,
        first_turn: str = "challenger",
        bet: Optional[int] = None
    ):
        author = interaction.user

        # Guard: Inactive / Already in Match
        if is_player_active(author.id):
            return await interaction.response.send_message(
                "⚠️ You are already participating in an active Tic-Tac-Toe match! Finish it first.",
                ephemeral=True
            )

        gid = str(interaction.guild_id or (interaction.guild.id if interaction.guild else ""))
        cfg = getattr(db, "economy_config", {}).get(gid, {})
        cur_name = cfg.get("currency_name", "Coins")
        cur_emoji = cfg.get("currency_emoji", "🪙")

        # ─── CASE A: PLAY WITH FRIDAY (PvE) ───
        if opponent is None or opponent.id == self.bot.user.id:
            if bet and bet > 0:
                hard_bounty = int(cfg.get("tictactoe_hard_reward", 500))
                return await interaction.response.send_message(
                    f"💡 You cannot wager coins against Friday AI directly.\n"
                    f"Beat Friday on **Hard Mode** to claim the **+{hard_bounty:,} {cur_emoji} {cur_name}** bounty!\n"
                    f"To place wagers with friends, invite another member (e.g. `/tictactoe play opponent:@Member bet:500`).",
                    ephemeral=True
                )

            toss_notice = ""
            if first_turn == "random":
                ai_first = random.choice([True, False])
                if ai_first:
                    p1, p2 = self.bot.user, author
                    toss_notice = "🪙 **Coin Toss:** Friday won the toss and gets the first move (❌)!"
                else:
                    p1, p2 = author, self.bot.user
                    toss_notice = f"🪙 **Coin Toss:** {author.mention} won the toss and gets the first move (❌)!"
            elif first_turn == "opponent":
                p1, p2 = self.bot.user, author
            else:
                p1, p2 = author, self.bot.user

            game_view = TicTacToeGameView(
                player_x=p1,
                player_o=p2,
                is_ai=True,
                difficulty=difficulty,
                bot=self.bot,
                guild_id=interaction.guild_id
            )

            # If Friday is Player 1, Friday makes its opening move immediately!
            if p1.id == self.bot.user.id:
                opening_move = 4  # Take center
                game_view.board[opening_move] = "X"
                game_view.buttons[opening_move].label = "❌"
                game_view.buttons[opening_move].style = discord.ButtonStyle.danger
                game_view.buttons[opening_move].disabled = True
                game_view.current_turn = "O"

            notice_lines = [f"🎮 **Match Initialized!** Playing against **Friday** on **{difficulty}** mode."]
            if difficulty == "Hard":
                bounty = int(cfg.get("tictactoe_hard_reward", 500))
                if bounty > 0:
                    notice_lines.append(f"🏆 **Hard Mode Bounty:** Beat Friday AI to win **+{bounty:,} {cur_emoji} {cur_name}**!")
            if toss_notice:
                notice_lines.append(toss_notice)

            embed = game_view.build_status_embed(
                status="info",
                notice="\n".join(notice_lines)
            )

            await interaction.response.send_message(embed=embed, view=game_view)
            game_view.message = await interaction.original_response()
            return

        # Resolve to guild member if resolved as User
        if interaction.guild and not isinstance(opponent, discord.Member):
            opponent = interaction.guild.get_member(opponent.id) or opponent

        # ─── CASE B: CHALLENGE VALIDATION ───
        if opponent.id == author.id:
            return await interaction.response.send_message(
                "❌ You cannot play against yourself! Invite another member or play against Friday.",
                ephemeral=True
            )

        if opponent.bot:
            return await interaction.response.send_message(
                f"❌ {opponent.display_name} is a bot! If you want to play against an AI, challenge Friday directly with `/tictactoe`.",
                ephemeral=True
            )

        if is_player_active(opponent.id):
            return await interaction.response.send_message(
                f"⚠️ {opponent.mention} is currently in an active match. Please wait until they finish.",
                ephemeral=True
            )

        # Wager pre-flight validation
        if bet and bet > 0:
            if cfg.get("paused", False):
                return await interaction.response.send_message("⚠️ The server economy is currently paused by administrators.", ephemeral=True)
            if bet < 10:
                return await interaction.response.send_message("❌ Minimum wager is 10 coins.", ephemeral=True)
            max_b = int(cfg.get("minigame_max_bet", 50000))
            if max_b > 0 and bet > max_b:
                return await interaction.response.send_message(f"❌ Maximum wager allowed is {max_b:,} {cur_name}.", ephemeral=True)

            from cogs.economy import get_economy_db
            eco_db = get_economy_db()
            p1_prof = eco_db.get_or_init_user(gid, str(author.id))
            p2_prof = eco_db.get_or_init_user(gid, str(opponent.id))

            if p1_prof["wallet"] < bet:
                return await interaction.response.send_message(
                    f"❌ You do not have enough {cur_name} in your cash wallet for this wager!\nYour Wallet: **{p1_prof['wallet']:,} {cur_emoji} {cur_name}** · Required: **{bet:,} {cur_name}**.",
                    ephemeral=True
                )
            if p2_prof["wallet"] < bet:
                return await interaction.response.send_message(
                    f"❌ {opponent.display_name} does not have enough {cur_name} in their cash wallet for this wager!\nTheir Wallet: **{p2_prof['wallet']:,} {cur_emoji} {cur_name}** · Required: **{bet:,} {cur_name}**.",
                    ephemeral=True
                )

        # ─── CASE C: SEND PVP INVITATION ───
        invite_view = ChallengeInviteView(
            challenger=author,
            target=opponent,
            bot=self.bot,
            first_turn=first_turn,
            bet=bet or 0,
            guild_id=interaction.guild_id
        )

        turn_pref_str = f"{author.display_name} (❌)"
        if first_turn == "opponent":
            turn_pref_str = f"{opponent.display_name} (❌)"
        elif first_turn == "random":
            turn_pref_str = "🎲 Coin toss will decide"

        wager_text = ""
        if bet and bet > 0:
            wager_text = (
                f"\n\n💰 **HIGH-STAKES WAGER PROPOSAL:**\n"
                f"• **Wager:** **{bet:,} {cur_emoji} {cur_name}** from each player\n"
                f"• **Winner Prize Pot:** **{bet * 2:,} {cur_emoji} {cur_name}** *(Winner takes all!)*\n"
                f"• Cash wallets will be escrowed upon accepting.\n"
            )

        embed = discord.Embed(
            title="🎮  Tic-Tac-Toe • High-Stakes Duel" if (bet and bet > 0) else "🎮  Tic-Tac-Toe • Match Challenge",
            description=(
                f"**{author.mention}** has invited **{opponent.mention}** to an epic game of **X and O**!\n\n"
                f"• **Challenger:** {author.display_name} (❌)\n"
                f"• **Opponent:** {opponent.display_name} (⭕)\n"
                f"• **First Move:** {turn_pref_str}"
                f"{wager_text}\n"
                f"👉 **{opponent.mention}**, will you accept the duel?"
            ),
            color=0xF1C40F if (bet and bet > 0) else 0x5865F2,
            timestamp=datetime.now(pytz.utc)
        )
        embed.set_footer(text=f"Friday Games • {cur_name} Protected • 60s to accept" if (bet and bet > 0) else "Friday Games • Awaiting response (60s)")

        await interaction.response.send_message(content=f"{opponent.mention}", embed=embed, view=invite_view)
        invite_view.message = await interaction.original_response()

    @ttt_group.command(name="stats", description="View your or another member's Tic-Tac-Toe match record & stats.")
    @app_commands.describe(member="Member whose stats to view (defaults to you)")
    async def stats_slash(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        await self._display_stats(interaction, target)

    async def _display_stats(self, interaction: discord.Interaction, target: discord.Member):
        stats = get_player_stats(target.id)
        played = stats.get("games_played", 0)
        wins = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        ties = stats.get("ties", 0)

        win_rate = f"{(wins / played * 100):.1f}%" if played > 0 else "0.0%"

        ai_wins = stats.get("vs_ai_wins", 0)
        ai_losses = stats.get("vs_ai_losses", 0)
        ai_ties = stats.get("vs_ai_ties", 0)

        pvp_wins = stats.get("vs_pvp_wins", 0)
        pvp_losses = stats.get("vs_pvp_losses", 0)
        pvp_ties = stats.get("vs_pvp_ties", 0)

        fields = [
            {"name": "Overall Record", "value": f"🏆 **{wins}** Wins • ✕ **{losses}** Losses • 🤝 **{ties}** Draws", "inline": False},
            {"name": "Win Rate", "value": f"📊 **{win_rate}** ({played} total matches)", "inline": True},
            {"name": "vs Friday (AI)", "value": f"✓ **{ai_wins}**W - **{ai_losses}**L - **{ai_ties}**D", "inline": True},
            {"name": "vs Players (PvP)", "value": f"⚔️ **{pvp_wins}**W - **{pvp_losses}**L - **{pvp_ties}**D", "inline": True}
        ]

        embed = make_box_embed(
            title=f"Tic-Tac-Toe Career Record • {clean_display_name(target.display_name, 24)}",
            description=f"Match performance analysis and career statistics for {target.mention}:",
            status="info",
            fields=fields,
            footer="Friday Games"
        )
        if target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicTacToe(bot))
