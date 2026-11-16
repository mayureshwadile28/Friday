import discord
from discord.ext import commands
from discord import app_commands
import random
import math
import asyncio
import time
from typing import Optional, List, Tuple, Union

from database import db
from response_utils import make_box_embed, STATUS_COLORS, STATUS_SYMBOLS
from font_utils import clean_display_name

# Global tracking to prevent users from engaging in multiple games concurrently
ACTIVE_PLAYERS = set()

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
    """Hard AI: Mathematically unbeatable Minimax algorithm with alpha-beta pruning."""
    avail = get_available_spots(board)
    if not avail:
        return None

    # Early-game heuristic shortcut (saves computation)
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
            label="\u200b",
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
        bot: Optional[commands.Bot] = None
    ):
        super().__init__(timeout=90)
        self.player_x = player_x
        self.player_o = player_o
        self.is_ai = is_ai
        self.difficulty = difficulty
        self.bot = bot

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
        ACTIVE_PLAYERS.add(self.player_x.id)
        if not self.is_ai and hasattr(self.player_o, "id"):
            ACTIVE_PLAYERS.add(self.player_o.id)

    def cleanup_active_players(self):
        ACTIVE_PLAYERS.discard(self.player_x.id)
        if hasattr(self.player_o, "id"):
            ACTIVE_PLAYERS.discard(self.player_o.id)

    def build_status_embed(self, status: str = "info", notice: str = None) -> discord.Embed:
        x_name = clean_display_name(self.player_x.display_name, 24)
        o_name = "Friday (AI)" if self.is_ai else clean_display_name(self.player_o.display_name, 24)

        title = f"Tic-Tac-Toe • {'Friday AI' if self.is_ai else 'PvP Challenge'}"

        if self.is_ai:
            desc = (
                f"**Player 1:** {self.player_x.mention} (`✕`)\n"
                f"**Opponent:** **Friday** (`◯`) • Mode: **{self.difficulty}**\n\n"
            )
        else:
            desc = (
                f"**Player 1:** {self.player_x.mention} (`✕`)\n"
                f"**Player 2:** {self.player_o.mention} (`◯`)\n\n"
            )

        if notice:
            desc += notice
        else:
            cur_user = self.player_x if self.current_turn == "X" else self.player_o
            cur_mention = cur_user.mention if hasattr(cur_user, "mention") else "**Friday**"
            desc += f"👉 **Current Turn:** {cur_mention} (`{self.current_turn}`)\n*Click an empty tile on the board below!*"

        embed = make_box_embed(
            title=title,
            description=desc,
            status=status,
            footer="Friday Games • 90s Turn Timer"
        )
        return embed

    async def handle_move(self, interaction: discord.Interaction, index: int, button: TicTacToeTileButton):
        if self.game_over:
            return await interaction.response.defer()

        # 1. Turn and Authorization Verification
        expected_user = self.player_x if self.current_turn == "X" else self.player_o
        if interaction.user.id != expected_user.id:
            # Check if user is a random spectator or the other player
            if interaction.user.id in (self.player_x.id, getattr(self.player_o, "id", None)):
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

        # 2. Apply Human Move
        self.board[index] = self.current_turn
        button.label = "✕" if self.current_turn == "X" else "◯"
        button.style = discord.ButtonStyle.danger if self.current_turn == "X" else discord.ButtonStyle.primary
        button.disabled = True

        # Check for victory or tie
        winner = check_board_winner(self.board)
        if winner:
            return await self.finish_game(interaction, winner)

        # 3. AI Turn (if in PvE mode)
        if self.is_ai:
            self.current_turn = "O"
            # Update UI to show AI thinking
            await interaction.response.edit_message(
                embed=self.build_status_embed(notice="🤖 **Friday is calculating optimal move...**"),
                view=self
            )

            await asyncio.sleep(0.4)

            # Determine AI move based on selected difficulty
            if self.difficulty == "Easy":
                ai_idx = ai_easy_move(self.board, ai_sym="O", human_sym="X")
            elif self.difficulty == "Hard":
                ai_idx = ai_hard_move(self.board, ai_sym="O", human_sym="X")
            else:
                ai_idx = ai_normal_move(self.board, ai_sym="O", human_sym="X")

            if ai_idx is not None:
                self.board[ai_idx] = "O"
                ai_btn = self.buttons[ai_idx]
                ai_btn.label = "◯"
                ai_btn.style = discord.ButtonStyle.primary
                ai_btn.disabled = True

            ai_winner = check_board_winner(self.board)
            if ai_winner:
                return await self.finish_game(None, ai_winner)

            # Switch back to Human
            self.current_turn = "X"
            if self.message:
                await self.message.edit(embed=self.build_status_embed(), view=self)
            return

        # 4. Switch Turns for PvP
        self.current_turn = "O" if self.current_turn == "X" else "X"
        await interaction.response.edit_message(embed=self.build_status_embed(), view=self)

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
        self.remove_item(self.forfeit_btn)
        self.add_item(RematchButton())

        elapsed = int(time.time() - self.start_time)

        if winner == "X":
            notice = f"🏆 **Victory:** {self.player_x.mention} (`✕`) has won the match in {elapsed}s!"
            status = "success"
        elif winner == "O":
            winner_mention = "Friday" if self.is_ai else self.player_o.mention
            notice = f"🏆 **Victory:** {winner_mention} (`◯`) has won the match in {elapsed}s!"
            status = "error" if self.is_ai else "success"
        else:
            notice = f"🤝 **Stalemate!** Both players tied after {elapsed}s of intense play."
            status = "neutral"

        update_game_stats(self.player_x, self.player_o, winner, self.is_ai)

        embed = self.build_status_embed(status=status, notice=notice)

        if interaction and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        elif self.message:
            await self.message.edit(embed=embed, view=self)

        self.stop()

    async def handle_forfeit(self, interaction: discord.Interaction):
        if self.game_over:
            return await interaction.response.defer()

        # Only participating players can forfeit
        if interaction.user.id not in (self.player_x.id, getattr(self.player_o, "id", None)):
            return await interaction.response.send_message("❌ You are not part of this game.", ephemeral=True)

        self.game_over = True
        self.cleanup_active_players()

        for btn in self.buttons:
            btn.disabled = True

        self.remove_item(self.forfeit_btn)
        self.add_item(RematchButton())

        forfeiter = interaction.user
        if forfeiter.id == self.player_x.id:
            winner_user = self.player_o
            winner_sym = "O"
        else:
            winner_user = self.player_x
            winner_sym = "X"

        winner_mention = "Friday" if self.is_ai else winner_user.mention
        notice = f"🏳️ **Forfeit:** {forfeiter.mention} surrendered the match.\n🏆 **Winner by Forfeit:** {winner_mention} (`{winner_sym}`)!"

        update_game_stats(self.player_x, self.player_o, winner_sym, self.is_ai)

        embed = self.build_status_embed(status="warning", notice=notice)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def handle_rematch(self, interaction: discord.Interaction):
        # Only previous participants can request rematch
        if interaction.user.id not in (self.player_x.id, getattr(self.player_o, "id", None)):
            return await interaction.response.send_message("❌ Only match participants can trigger a rematch.", ephemeral=True)

        if interaction.user.id in ACTIVE_PLAYERS or getattr(self.player_o, "id", None) in ACTIVE_PLAYERS:
            return await interaction.response.send_message("⚠️ One of the players is currently in another match.", ephemeral=True)

        # For PvP: swap first turn (X and O) for balanced fairness
        if not self.is_ai:
            new_view = TicTacToeGameView(
                player_x=self.player_o,
                player_o=self.player_x,
                is_ai=False,
                bot=self.bot
            )
        else:
            new_view = TicTacToeGameView(
                player_x=self.player_x,
                player_o=self.player_o,
                is_ai=True,
                difficulty=self.difficulty,
                bot=self.bot
            )

        embed = new_view.build_status_embed(status="info", notice="🔄 **Rematch initiated! Let the games begin!**\n")
        await interaction.response.edit_message(embed=embed, view=new_view)
        new_view.message = interaction.message

    async def on_timeout(self):
        self.cleanup_active_players()
        if not self.game_over:
            self.game_over = True
            for btn in self.buttons:
                btn.disabled = True
            self.remove_item(self.forfeit_btn)
            if self.message:
                try:
                    embed = self.build_status_embed(
                        status="warning",
                        notice="⏰ **Game Abandoned:** Match timed out after 90 seconds of inactivity."
                    )
                    await self.message.edit(embed=embed, view=self)
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────
# PVP CHALLENGE INVITATION VIEW
# ─────────────────────────────────────────────────────────────

class ChallengeInviteView(discord.ui.View):
    def __init__(self, challenger: discord.Member, target: discord.Member, bot: commands.Bot):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.target = target
        self.bot = bot
        self.message: Optional[discord.Message] = None

        ACTIVE_PLAYERS.add(self.challenger.id)
        ACTIVE_PLAYERS.add(self.target.id)

    def cleanup(self):
        ACTIVE_PLAYERS.discard(self.challenger.id)
        ACTIVE_PLAYERS.discard(self.target.id)

    @discord.ui.button(label="Accept Challenge", style=discord.ButtonStyle.success, emoji="⚔️")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            return await interaction.response.send_message(
                f"❌ Only {self.target.mention} can accept this invitation.",
                ephemeral=True
            )

        # Launch Game View
        game_view = TicTacToeGameView(
            player_x=self.challenger,
            player_o=self.target,
            is_ai=False,
            bot=self.bot
        )
        embed = game_view.build_status_embed(
            status="info",
            notice=f"⚔️ **Challenge Accepted!** {self.target.mention} joined the battlefield.\n\n"
        )
        await interaction.response.edit_message(embed=embed, view=game_view)
        game_view.message = interaction.message
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="✕")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            return await interaction.response.send_message(
                f"❌ Only {self.target.mention} can decline this invitation.",
                ephemeral=True
            )

        self.cleanup()
        for item in self.children:
            item.disabled = True

        embed = make_box_embed(
            title="Tic-Tac-Toe • Challenge Declined",
            description=f"❌ {self.target.mention} declined the challenge from {self.challenger.mention}.",
            status="error",
            footer="Friday Games"
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        self.cleanup()
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                embed = make_box_embed(
                    title="Tic-Tac-Toe • Invitation Expired",
                    description=f"⏰ Challenge from {self.challenger.mention} to {self.target.mention} expired (no response within 60s).",
                    status="neutral",
                    footer="Friday Games"
                )
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────
# TIC-TAC-TOE COG SETUP
# ─────────────────────────────────────────────────────────────

class TicTacToe(commands.Cog, name="Games"):
    """Sleek interactive Tic-Tac-Toe (X and O) game against members or Friday AI."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="tictactoe", description="Play Tic-Tac-Toe (X and O) against a friend or Friday AI!")
    @app_commands.describe(
        opponent="Member to challenge (leave blank to play against Friday AI)",
        difficulty="Friday AI difficulty mode (Easy, Normal, Hard)"
    )
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="Easy (Casual & Fun)", value="Easy"),
        app_commands.Choice(name="Normal (Balanced & Smart)", value="Normal"),
        app_commands.Choice(name="Hard (Unbeatable Minimax AI)", value="Hard")
    ])
    async def tictactoe_slash(
        self,
        interaction: discord.Interaction,
        opponent: Optional[discord.Member] = None,
        difficulty: Optional[str] = "Normal"
    ):
        await self._start_game_flow(interaction, opponent, difficulty or "Normal")

    @commands.command(name="tictactoe", aliases=["ttt", "xo", "xando"])
    async def tictactoe_prefix(
        self,
        ctx: commands.Context,
        opponent: Optional[discord.Member] = None,
        difficulty: str = "Normal"
    ):
        """Play Tic-Tac-Toe against a member or Friday AI! Example: !ttt @friend OR !ttt Hard"""
        # If user passed a difficulty string as the first argument instead of member
        if opponent is None and difficulty and difficulty.lower() in ("easy", "normal", "hard"):
            diff_clean = difficulty.capitalize()
        else:
            diff_clean = "Normal"
            if difficulty and difficulty.capitalize() in ("Easy", "Normal", "Hard"):
                diff_clean = difficulty.capitalize()

        await self._start_game_flow(ctx, opponent, diff_clean)

    async def _start_game_flow(
        self,
        ctx_or_interaction: Union[commands.Context, discord.Interaction],
        opponent: Optional[discord.Member],
        difficulty: str
    ):
        author = ctx_or_interaction.author if isinstance(ctx_or_interaction, commands.Context) else ctx_or_interaction.user

        # Guard: Inactive / Already in Match
        if author.id in ACTIVE_PLAYERS:
            msg = "⚠️ You are already participating in an active Tic-Tac-Toe match! Finish it first."
            if isinstance(ctx_or_interaction, discord.Interaction):
                return await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                return await ctx_or_interaction.reply(msg)

        # ─── CASE A: PLAY WITH FRIDAY (PvE) ───
        if opponent is None or opponent.id == self.bot.user.id:
            game_view = TicTacToeGameView(
                player_x=author,
                player_o=self.bot.user,
                is_ai=True,
                difficulty=difficulty,
                bot=self.bot
            )
            embed = game_view.build_status_embed(
                status="info",
                notice=f"🎮 **Match Initialized!** You are playing against **Friday** on **{difficulty}** mode.\n"
            )

            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(embed=embed, view=game_view)
                game_view.message = await ctx_or_interaction.original_response()
            else:
                game_view.message = await ctx_or_interaction.reply(embed=embed, view=game_view)
            return

        # ─── CASE B: CHALLENGE VALIDATION ───
        if opponent.id == author.id:
            msg = "❌ You cannot play against yourself! Invite another member or play against Friday."
            if isinstance(ctx_or_interaction, discord.Interaction):
                return await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                return await ctx_or_interaction.reply(msg)

        if opponent.bot:
            msg = f"❌ {opponent.display_name} is a bot! If you want to play against an AI, challenge Friday directly with `/tictactoe`."
            if isinstance(ctx_or_interaction, discord.Interaction):
                return await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                return await ctx_or_interaction.reply(msg)

        if opponent.id in ACTIVE_PLAYERS:
            msg = f"⚠️ {opponent.mention} is currently in an active match. Please wait until they finish."
            if isinstance(ctx_or_interaction, discord.Interaction):
                return await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            else:
                return await ctx_or_interaction.reply(msg)

        # ─── CASE C: SEND PVP INVITATION ───
        invite_view = ChallengeInviteView(challenger=author, target=opponent, bot=self.bot)
        embed = make_box_embed(
            title="Tic-Tac-Toe • Match Challenge",
            description=(
                f"**{author.mention}** has invited **{opponent.mention}** to an epic game of **X and O**!\n\n"
                f"• **Challenger:** {author.display_name} (`✕`)\n"
                f"• **Opponent:** {opponent.display_name} (`◯`)\n\n"
                f"👉 **{opponent.mention}**, will you accept the duel?"
            ),
            status="info",
            footer="Friday Games • Awaiting response (60s)"
        )

        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(content=f"{opponent.mention}", embed=embed, view=invite_view)
            invite_view.message = await ctx_or_interaction.original_response()
        else:
            invite_view.message = await ctx_or_interaction.reply(content=f"{opponent.mention}", embed=embed, view=invite_view)

    @app_commands.command(name="tictactoe_stats", description="View your or another member's Tic-Tac-Toe match record & stats.")
    @app_commands.describe(member="Member whose stats to view (defaults to you)")
    async def stats_slash(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        await self._display_stats(interaction, target)

    @commands.command(name="tictactoe_stats", aliases=["tttstats", "xostats"])
    async def stats_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """View your or another member's Tic-Tac-Toe record."""
        target = member or ctx.author
        await self._display_stats(ctx, target)

    async def _display_stats(self, ctx_or_interaction: Union[commands.Context, discord.Interaction], target: discord.Member):
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

        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed)
        else:
            await ctx_or_interaction.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicTacToe(bot))
