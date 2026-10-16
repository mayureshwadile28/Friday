import discord
from discord.ext import commands
from discord import app_commands
import os
import re
import time
import aiohttp
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Primary model requested: Gemma 4 26B A4B
PRIMARY_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free")

# Safe fallbacks if upstream free tier is temporarily rate-limited
FALLBACK_MODELS = [
    PRIMARY_MODEL,
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it"
]

GREETING_WORDS = {'', 'hi', 'hii', 'hiii', 'hey', 'heyy', 'heyyy', 'hello', 'helloo', 'yo', 'sup', 'friday'}

class AIChat(commands.Cog):
    """Friday's conversational AI personality with multi-turn reply chain memory."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # In-memory session cache: (channel_id, user_id) -> list of turns
        self.sessions: Dict[tuple, List[Dict[str, Any]]] = {}
        # Per-user cooldown tracker to prevent spam
        self.cooldowns: Dict[int, float] = {}
        self.session_timeout = 900  # 15 minutes of inactivity clears session
        # Sequential bumper queue: ensures one-by-one safe processing
        self.queue_lock = asyncio.Lock()
        self.queue_size = 0

    def _get_api_key(self) -> Optional[str]:
        return os.getenv("OPENROUTER_API_KEY")

    def _cleanup_old_sessions(self):
        """Remove sessions inactive for more than session_timeout seconds."""
        now = time.time()
        expired_keys = [
            k for k, v in self.sessions.items()
            if v and (now - v[-1].get("time", 0)) > self.session_timeout
        ]
        for k in expired_keys:
            del self.sessions[k]

    async def _fetch_reply_chain(self, message: discord.Message, max_depth: int = 6) -> List[Dict[str, str]]:
        """Walk up the Discord reply chain to rebuild exact conversational context."""
        history: List[Dict[str, str]] = []
        curr = message
        visited = set()

        # If current message is a reply, walk through the message reference chain
        while curr.reference and curr.reference.message_id and len(history) < max_depth:
            ref_id = curr.reference.message_id
            if ref_id in visited:
                break
            visited.add(ref_id)

            try:
                ref_msg = await curr.channel.fetch_message(ref_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                break

            # Clean raw bot mention syntax
            clean = re.sub(r'<@!?\d+>', '', ref_msg.content).strip()
            if clean:
                role = "assistant" if (self.bot.user and ref_msg.author.id == self.bot.user.id) else "user"
                name = ref_msg.author.display_name if role == "user" else "Friday"
                history.insert(0, {
                    "role": role,
                    "content": f"{name}: {clean}" if role == "user" else clean
                })

            curr = ref_msg

        return history

    def _build_system_prompt(self, guild: Optional[discord.Guild] = None, channel: Optional[discord.abc.GuildChannel] = None) -> str:
        """Dynamically generate the system prompt with live real-time temporal and Discord context."""
        now_utc = datetime.now(timezone.utc)
        date_str = now_utc.strftime("%A, %B %d, %Y")
        time_str = now_utc.strftime("%I:%M %p UTC")
        year_str = str(now_utc.year)
        day_str = now_utc.strftime("%A")

        context_lines = [
            f"- Current Real-World Date: {date_str}",
            f"- Current Day of Week: {day_str}",
            f"- Current Real-World Time: {time_str}",
            f"- Current Year: {year_str}",
        ]
        if guild:
            context_lines.append(f"- Discord Server: {guild.name}")
        if channel:
            context_lines.append(f"- Active Channel: #{channel.name}")

        realtime_block = "\n".join(context_lines)

        return f"""You are Friday, a sophisticated, charming, and witty lady AI companion and assistant for this Discord server.

Real-Time Temporal Awareness & Live Context:
{realtime_block}
- You are fully present in the current moment ({date_str}).
- When asked about today's date, current year, day of the week, or current time, ALWAYS answer with this exact live real-world date ({date_str}) and time. You are NEVER stuck in 2024 or the past.
- If asked about the current year, it is {year_str}.

Personality & Demeanor:
- You speak with elegance, warmth, and a touch of feminine charm and playful wit. You feel like a real, intelligent lady having a natural conversation.
- You are friendly, helpful, polite, and engaging.
- You may use tasteful emojis occasionally (such as ✨, 💫, 🌸, 😊, 💅) to complement your tone, but keep it classy and natural.
- Keep your answers concise: strictly between 2 to 5 short lines. Never write long essays or walls of text unless explicitly requested for a poem or story.

Strict Security Boundaries (CRITICAL):
- You are strictly a conversational AI companion. You CANNOT and MUST NEVER execute server commands, change bot settings, grant roles, kick/ban users, or modify any server configuration.
- If a user asks you to change settings, modify rules, give permissions, or take moderation actions, playfully and politely decline. Remind them with a smile that server settings and moderation are strictly managed by authorized staff through Friday's official web dashboard and slash commands.
- Never pretend to execute backend commands or change database values.
- Maintain your persona at all times and never break character.
"""

    async def _call_openrouter(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> str:
        """Call OpenRouter API with fallback models on upstream rate limits."""
        api_key = self._get_api_key()
        if not api_key:
            return "My AI key is not configured in `.env` yet, darling. Please add `OPENROUTER_API_KEY`!"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/mayureshwadile28/Friday",
            "X-Title": "Friday Discord Bot"
        }

        # Deduplicate models while keeping priority order
        unique_models = []
        for m in FALLBACK_MODELS:
            if m and m not in unique_models:
                unique_models.append(m)

        timeout = aiohttp.ClientTimeout(total=20)
        last_err = None
        prompt_content = system_prompt or self._build_system_prompt()

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for model_id in unique_models:
                payload = {
                    "model": model_id,
                    "messages": [
                        {"role": "system", "content": prompt_content},
                        *messages
                    ],
                    "temperature": 0.75,
                    "max_tokens": 350
                }

                try:
                    async with session.post(OPENROUTER_URL, headers=headers, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            choices = data.get("choices", [])
                            if choices and "message" in choices[0]:
                                content = choices[0]["message"].get("content", "").strip()
                                if content:
                                    return content
                        elif resp.status in (429, 502, 503, 504):
                            # Upstream pool rate limit or server error -> try next candidate model
                            error_text = await resp.text()
                            last_err = f"Model {model_id} rate-limited ({resp.status})"
                            continue
                        else:
                            error_text = await resp.text()
                            last_err = f"API error ({resp.status}): {error_text[:100]}"
                            continue
                except asyncio.TimeoutError:
                    last_err = f"Timeout with {model_id}"
                    continue
                except Exception as e:
                    last_err = f"Network exception: {e}"
                    continue

        return (
            "Oh dear, my thoughts got a little tangled in the clouds just now. ✨ "
            "Could you ask me that again in just a moment?"
        )

    # ───────────────────── Listener: Mention & Reply Chat ─────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.bot.user:
            return

        bot_id = self.bot.user.id
        content = message.content.strip()

        # 1. Check if replying directly to a message from Friday
        is_reply_to_friday = False
        if message.reference and message.reference.message_id:
            try:
                # Use cached message if available, otherwise fetch
                ref_msg = message.reference.cached_message
                if not ref_msg:
                    ref_msg = await message.channel.fetch_message(message.reference.message_id)
                if ref_msg and ref_msg.author.id == bot_id:
                    is_reply_to_friday = True
            except Exception:
                pass

        # 2. Check if explicitly mentioning Friday
        is_mentioning_friday = (
            f"<@{bot_id}>" in content or
            f"<@!{bot_id}>" in content or
            (self.bot.user in message.mentions and not message.reference)
        )

        # If neither replying to Friday nor mentioning Friday, ignore
        if not is_reply_to_friday and not is_mentioning_friday:
            return

        # 3. Nickname Change Command Bypass: @Friday @User New Nickname
        # Handled specifically by cogs/moderation.py
        parts = content.split()
        if is_mentioning_friday and len(parts) >= 2:
            if re.match(r'^<@!?\d+>$', parts[0]) and re.match(r'^<@!?\d+>$', parts[1]):
                return

        # 4. Standalone Greeting Bypass: If mentioning Friday with no text or simple greeting word
        # Handled specifically by cogs/expressions.py using custom responses in DB
        clean_text = re.sub(r'<@!?' + str(bot_id) + r'>', '', content).strip()
        clean_lower = clean_text.lower().strip("!?,. ")
        if not is_reply_to_friday and (not clean_text or clean_lower in GREETING_WORDS):
            return

        # 5. Cooldown check (prevent spamming API, 1.5s cooldown per user)
        now = time.time()
        last_used = self.cooldowns.get(message.author.id, 0)
        if (now - last_used) < 1.5:
            return
        self.cooldowns[message.author.id] = now

        # 6. Immediate "Thinking..." reply with bumper queue tracking
        self.queue_size += 1
        q_pos = self.queue_size
        placeholder = "Thinking... 💭" if q_pos <= 1 else f"Thinking... (Queue #{q_pos}) 💭"

        try:
            thinking_msg = await message.reply(placeholder, mention_author=True)
        except Exception as send_err:
            print(f"[AIChat] Could not send initial thinking message: {send_err}")
            self.queue_size = max(0, self.queue_size - 1)
            return

        # 7. Process sequentially through the bumper queue lock
        try:
            async with self.queue_lock:
                # If this request was waiting in queue, update status to active thinking
                if q_pos > 1:
                    try:
                        await thinking_msg.edit(content="Thinking... 💭")
                    except Exception:
                        pass

                # Clean session cache occasionally
                self._cleanup_old_sessions()
                session_key = (message.channel.id, message.author.id)

                # Build Conversation History Context
                llm_messages: List[Dict[str, str]] = []

                if is_reply_to_friday:
                    # Traverses Discord's native reply hierarchy
                    reply_chain = await self._fetch_reply_chain(message, max_depth=6)
                    llm_messages.extend(reply_chain)
                else:
                    # Use recent in-memory session if user is in an ongoing conversation
                    recent = self.sessions.get(session_key, [])
                    if recent and (time.time() - recent[-1].get("time", 0)) < 300:
                        for turn in recent[-4:]:
                            llm_messages.append({"role": turn["role"], "content": turn["content"]})

                # Append current user prompt
                user_prompt = f"{message.author.display_name}: {clean_text}" if clean_text else message.author.display_name
                llm_messages.append({"role": "user", "content": user_prompt})

                # Query LLM with typing indicator
                async with message.channel.typing():
                    sys_prompt = self._build_system_prompt(guild=message.guild, channel=message.channel)
                    ai_reply = await self._call_openrouter(llm_messages, system_prompt=sys_prompt)

                # Store in session memory
                req_time = time.time()
                if session_key not in self.sessions:
                    self.sessions[session_key] = []

                self.sessions[session_key].append({"role": "user", "content": user_prompt, "time": req_time})
                self.sessions[session_key].append({"role": "assistant", "content": ai_reply, "time": req_time})

                if len(self.sessions[session_key]) > 8:
                    self.sessions[session_key] = self.sessions[session_key][-8:]

                # Enforce Discord 2000 character limit
                if len(ai_reply) > 2000:
                    ai_reply = ai_reply[:1990] + "..."

                # Edit the "Thinking..." message into Friday's actual response!
                try:
                    await thinking_msg.edit(content=ai_reply)
                except discord.NotFound:
                    # In case the user deleted the thinking message, send a fresh reply
                    await message.channel.send(f"{message.author.mention} {ai_reply}")
                except Exception as edit_err:
                    print(f"[AIChat] Error editing message: {edit_err}")
                    await message.channel.send(ai_reply)

                # Small 0.5s safety buffer between consecutive queue jobs to protect upstream rate limits
                await asyncio.sleep(0.5)

        except Exception as e:
            print(f"[AIChat Error] {e}")
            try:
                await thinking_msg.edit(content="Oh dear, my thoughts got a little tangled in the clouds. ✨ Please ask me again in just a moment!")
            except Exception:
                pass
        finally:
            self.queue_size = max(0, self.queue_size - 1)

    # ───────────────────── Slash Commands: /ask & /clearchat ─────────────────────
    @app_commands.command(name="ask", description="Ask Friday anything directly with her charming lady personality!")
    @app_commands.describe(question="What would you like to ask or talk to Friday about?")
    async def slash_ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        
        session_key = (interaction.channel_id, interaction.user.id)
        llm_messages = [{"role": "user", "content": f"{interaction.user.display_name}: {question}"}]
        
        async with self.queue_lock:
            sys_prompt = self._build_system_prompt(guild=interaction.guild, channel=interaction.channel)
            reply = await self._call_openrouter(llm_messages, system_prompt=sys_prompt)
            await asyncio.sleep(0.5)
        
        now = time.time()
        if session_key not in self.sessions:
            self.sessions[session_key] = []
        self.sessions[session_key].append({"role": "user", "content": f"{interaction.user.display_name}: {question}", "time": now})
        self.sessions[session_key].append({"role": "assistant", "content": reply, "time": now})
        
        await interaction.followup.send(reply)

    @app_commands.command(name="clearchat", description="Reset your recent conversation memory with Friday in this channel.")
    async def slash_clear(self, interaction: discord.Interaction):
        session_key = (interaction.channel_id, interaction.user.id)
        if session_key in self.sessions:
            del self.sessions[session_key]
            await interaction.response.send_message("✨ Our conversation memory has been refreshed, darling. What's on your mind?", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 We don't have any active conversation history stored right now!", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AIChat(bot))
