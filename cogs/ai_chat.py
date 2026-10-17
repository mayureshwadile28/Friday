import discord
from discord.ext import commands
from discord import app_commands
import os
import re
import time
import aiohttp
import asyncio
import urllib.request
import xml.etree.ElementTree as ET
import html
from urllib.parse import quote_plus
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from database import db

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GOOGLE_AI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

# Primary model requested: Gemma 4 26B A4B
PRIMARY_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free")

# Safe fallbacks prioritized for high uptime on free tier
FALLBACK_MODELS = [
    PRIMARY_MODEL,
    "nvidia/nemotron-3-super-120b-a12b:free",
    "liquid/lfm-2.5-2.6b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-26b-a4b-it"
]

GROQ_FALLBACK_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant"
]

GOOGLE_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash"
]

GREETING_WORDS = {'', 'hi', 'hii', 'hiii', 'hey', 'heyy', 'heyyy', 'hello', 'helloo', 'yo', 'sup', 'friday'}

# Action and feature keywords: Friday cannot moderate or control server actions
ACTION_REGEX = re.compile(
    r'\b(kick|ban|mute|timeout|unban|unmute|purge|delete|set nick|change nick|give role|remove role)\b',
    re.IGNORECASE
)
ACTION_COMMAND_VERBS = re.compile(
    r'\b(kardo|kar do|karo|karde|kar dena|kardena|please|plz|do it|now|hatao|nikalo)\b',
    re.IGNORECASE
)

# Core 18+ and severe profanity patterns to keep the community safe
INAPPROPRIATE_PATTERNS = re.compile(
    r'\b(nude|nudes|sex|porn|hentai|boobs|dick|cock|pussy|vagina|asshole|bitch|slut|whore|chutiya|gaand|bhosdike|bhenchod|madarchod|lund|chut)\b',
    re.IGNORECASE
)

# Date/Time queries: MUST be answered directly without triggering web search or news dumps!
DATE_TIME_QUERY_REGEX = re.compile(
    r'\b(date|time|day|year|month|clock|tarikh|din|aaj konsi|kya tarikh|kya date|what date|what time|what day|today\'?s? date|current date|current time)\b',
    re.IGNORECASE
)

# Strict intent detection for web news and Google search lookups
SEARCH_INTENT_REGEX = re.compile(
    r'\b(news|headlines|breaking news|breaking|taza khabar|samachar|aaj ki news|aaj ka news|current events|live score|cricket score|football score|match score|stock price|share price|crypto price|bitcoin price|search google|google it|google pe dekho|search online|search internet|internet pe dekho|kya chal raha hai duniya me|world news|latest update on|what is happening with)\b',
    re.IGNORECASE
)

# Persona Memory extraction patterns: learn positive personal facts, preferences, hobbies, roles
MEMORY_LEARN_PATTERNS = [
    (re.compile(r'\b(?:i (?:really )?(?:love|like|enjoy|prefer)|mujhe (?:bohot )?pasand hai)\s+([a-zA-Z0-9\s\',-]{3,40})\b', re.IGNORECASE), "Likes {}"),
    (re.compile(r'\b(?:my (?:all[ -]time )?fav(?:orite)?|mera fav(?:orite)?|mera pasandida)\s+([a-zA-Z0-9\s\',-]{2,20})\s+(?:is|hai)\s+([a-zA-Z0-9\s\',-]{2,30})\b', re.IGNORECASE), "Favorite {0}: {1}"),
    (re.compile(r'\b(?:my (?:all[ -]time )?fav(?:orite)?|mera fav(?:orite)?)\s+(?:is|hai)?\s*([a-zA-Z0-9\s\',-]{3,35})\b', re.IGNORECASE), "Favorite: {}"),
    (re.compile(r'\b(?:i am an?|i\'m an?|main ek|mai ek)\s+([a-zA-Z\s]{3,30})\b', re.IGNORECASE), "Is a {}"),
    (re.compile(r'\b(?:i play|mai khelta hu|main khelti hu|mai khelta)\s+([a-zA-Z0-9\s\',-]{3,30})\b', re.IGNORECASE), "Plays {}"),
    (re.compile(r'\b(?:call me|you can call me|mujhe bula sakte ho)\s+([a-zA-Z0-9]{2,20})\b', re.IGNORECASE), "Prefers to be called {}"),
    (re.compile(r'\b(?:my hobby is|meri hobby hai)\s+([a-zA-Z0-9\s\',-]{3,30})\b', re.IGNORECASE), "Hobby: {}"),
    (re.compile(r'\b(?:remember (?:that)?|yaad rakhna (?:ki)?)\s+([a-zA-Z0-9\s\',-]{3,50})\b', re.IGNORECASE), "{}"),
]

# Words to ignore for memory to avoid storing negative, toxic, system, or moderation text
MEMORY_IGNORE_WORDS = re.compile(
    r'\b(bot|idiot|stupid|dumb|hate|kill|die|leave|kick|ban|mute|timeout|purge|crap|shit|bitch|slut|nude|sex|porn|hentai|lund|chut|gaand|bhosdike|chutiya)\b',
    re.IGNORECASE
)

# Server-wide instruction patterns (Only Administrator & Server Owner can set)
SERVER_INSTRUCTION_TRIGGER = re.compile(
    r'\b(?:server instruction|server instructions|server rule|server memory|remember for (?:this|our) server|server ke liye yaad rakhna)\s*[:\-]?\s*(.+)',
    re.IGNORECASE
)

# Safe allowed mentions to prevent any @everyone, @here, or role pings
SAFE_ALLOWED_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=True)

def sanitize_ai_mentions(text: str) -> str:
    """Zero-width space escape for @everyone and @here so Discord never renders blue mention chips or pings."""
    if not text:
        return text
    # Insert zero-width space after @ for everyone and here so it renders as normal text without blue mention pills
    sanitized = re.sub(r'@(everyone|here)', lambda m: '@\u200b' + m.group(1), text, flags=re.IGNORECASE)
    return sanitized


def fetch_live_google_news(query: str, max_items: int = 5) -> List[Dict[str, str]]:
    """Fetch live real-time Google News and search data for news, current events, and topics."""
    try:
        encoded = quote_plus(query.strip())
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"}
        )
        with urllib.request.urlopen(req, timeout=7) as resp:
            xml_data = resp.read()

        root = ET.fromstring(xml_data)
        items = []
        for item in root.findall(".//item")[:max_items]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            desc = (item.findtext("description") or "").strip()
            clean_desc = html.unescape(re.sub(r"<[^>]+>", "", desc)).strip()
            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "pubDate": pub_date,
                    "summary": clean_desc
                })
        return items
    except Exception as e:
        print(f"[AIChat] Google search fetch exception: {e}")
        return []


class AIChat(commands.Cog):
    """Friday's conversational AI personality with multi-turn memory, Google search integration, and guardrails."""

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
        # Track message IDs produced by Friday's LLM so replies only trigger on actual LLM messages
        stored_ids = getattr(db, "data", {}).get("llm_message_ids", [])
        self.llm_message_ids = set(stored_ids)

    def _record_llm_message(self, message_id: int):
        """Record an LLM response ID so that user replies to this message are properly recognized."""
        self.llm_message_ids.add(message_id)
        if hasattr(db, "data") and isinstance(db.data, dict):
            if "llm_message_ids" not in db.data:
                db.data["llm_message_ids"] = []
            db.data["llm_message_ids"].append(message_id)
            if len(db.data["llm_message_ids"]) > 2000:
                db.data["llm_message_ids"] = db.data["llm_message_ids"][-2000:]

    def _get_user_memory(self, guild_id: str, user_id: int) -> List[str]:
        """Fetch stored positive persona memory notes for this user (bounded to max 4)."""
        uid = str(user_id)
        if hasattr(db, "user_memories") and isinstance(db.user_memories, dict):
            g_mems = db.user_memories.get(guild_id, {})
            if isinstance(g_mems, dict) and uid in g_mems and isinstance(g_mems[uid], dict):
                return g_mems[uid].get("notes", [])[:4]
        return []

    def _learn_user_memory(self, guild_id: str, user_id: int, user_name: str, text: str):
        """Learn positive, friendly traits/hobbies/preferences about a user with strict storage bounds."""
        if not text or len(text) < 4:
            return

        # 1. Never store bad, toxic, abusive, or 18+ content
        if self._check_inappropriate(guild_id, text) or MEMORY_IGNORE_WORDS.search(text):
            return

        # 2. Match candidate memory patterns
        extracted_note = None
        for pattern, template in MEMORY_LEARN_PATTERNS:
            match = pattern.search(text)
            if match:
                groups = [g.strip() for g in match.groups() if g]
                if groups:
                    candidate = template.format(*groups) if len(groups) > 1 else template.format(groups[0])
                    candidate = candidate.strip().strip("!?,. ")
                    # Verify candidate length and ensure no toxic/command content
                    if 4 <= len(candidate) <= 70 and not MEMORY_IGNORE_WORDS.search(candidate):
                        # Ensure first letter is capitalized
                        extracted_note = candidate[0].upper() + candidate[1:]
                        break

        if not extracted_note:
            return

        uid = str(user_id)
        if not hasattr(db, "user_memories") or not isinstance(db.user_memories, dict):
            db.user_memories = {}

        if guild_id not in db.user_memories:
            db.user_memories[guild_id] = {}

        g_mems = db.user_memories[guild_id]

        # Enforce LRU cap: max 200 users per guild (bounded strictly to ~30-40 KB VM storage)
        if uid not in g_mems and len(g_mems) >= 200:
            oldest_user = min(g_mems.keys(), key=lambda k: g_mems[k].get("updated", 0))
            del g_mems[oldest_user]

        user_entry = g_mems.get(uid, {"name": user_name, "notes": [], "updated": 0})
        user_entry["name"] = user_name
        user_entry["updated"] = time.time()

        notes = user_entry.get("notes", [])
        # Check if already recorded or duplicate
        low_cand = extracted_note.lower()
        if any(low_cand in n.lower() or n.lower() in low_cand for n in notes):
            return

        notes.append(extracted_note)
        # Cap at maximum 4 short bullet notes per user
        if len(notes) > 4:
            notes = notes[-4:]

        user_entry["notes"] = notes
        g_mems[uid] = user_entry
        db.user_memories[guild_id] = g_mems
        try:
            db.save_data()
        except Exception as e:
            print(f"[AIChat Memory] Save error: {e}")

    def _get_server_instructions(self, guild_id: str) -> List[str]:
        """Fetch custom server-wide behavioral instructions set by administrators/owner (capped to 6)."""
        if hasattr(db, "server_instructions") and isinstance(db.server_instructions, dict):
            return db.server_instructions.get(guild_id, [])[:6]
        return []

    def _add_server_instruction(self, guild_id: str, instruction: str) -> bool:
        """Add a custom server instruction (Admin/Owner only, max 6 per guild, max 120 chars)."""
        clean = instruction.strip().strip(".,!?\"'")
        if not clean or len(clean) < 4 or len(clean) > 120:
            return False
        # Do not allow profanity or harmful keywords in instructions
        if self._check_inappropriate(guild_id, clean) or MEMORY_IGNORE_WORDS.search(clean):
            return False
        if not hasattr(db, "server_instructions") or not isinstance(db.server_instructions, dict):
            db.server_instructions = {}
        current = db.server_instructions.get(guild_id, [])
        low_clean = clean.lower()
        if any(low_clean == item.lower() for item in current):
            return False
        current.append(clean[0].upper() + clean[1:])
        if len(current) > 6:
            current = current[-6:]
        db.server_instructions[guild_id] = current
        try:
            db.save_data()
            return True
        except Exception as e:
            print(f"[AIChat ServerInstruction] Save error: {e}")
            return False

    def _clear_server_instructions(self, guild_id: str) -> bool:
        """Clear all server-wide instructions for a guild."""
        if hasattr(db, "server_instructions") and isinstance(db.server_instructions, dict):
            if guild_id in db.server_instructions:
                del db.server_instructions[guild_id]
                try:
                    db.save_data()
                except Exception:
                    pass
                return True
        return False

    def _get_api_keys(self) -> List[str]:
        raw = os.getenv("OPENROUTER_API_KEY", "")
        return [k.strip() for k in raw.split(",") if k.strip()]

    def _get_api_key(self) -> Optional[str]:
        keys = self._get_api_keys()
        return keys[0] if keys else None

    def _cleanup_old_sessions(self):
        """Remove sessions inactive for more than session_timeout seconds."""
        now = time.time()
        expired_keys = [
            k for k, v in self.sessions.items()
            if v and (now - v[-1].get("time", 0)) > self.session_timeout
        ]
        for k in expired_keys:
            del self.sessions[k]

    def _resolve_discord_mentions(self, guild: Optional[discord.Guild], text: str) -> str:
        """Resolve raw Discord snowflake mentions (<@!ID>, <#ID>, <@&ID>) into readable names."""
        if not guild or not text:
            return text

        def _replace_member(match):
            uid = int(match.group(1))
            member = guild.get_member(uid)
            if member:
                return f"@{member.display_name}"
            return f"@{uid}"

        def _replace_channel(match):
            cid = int(match.group(1))
            ch = guild.get_channel(cid)
            if ch:
                return f"#{ch.name}"
            return f"#{cid}"

        def _replace_role(match):
            rid = int(match.group(1))
            role = guild.get_role(rid)
            if role:
                return f"@{role.name}"
            return f"@{rid}"

        resolved = re.sub(r'<@!?(\d+)>', _replace_member, text)
        resolved = re.sub(r'<#(\d+)>', _replace_channel, resolved)
        resolved = re.sub(r'<@&(\d+)>', _replace_role, resolved)
        return resolved

    def _check_inappropriate(self, guild_id: str, text: str) -> Optional[str]:
        """Check for severe profanity, 18+ content, or guild banned words."""
        # 1. Check guild configured banned words
        banned = db.banned_words.get(guild_id, [])
        lower_text = text.lower()
        for word in banned:
            if word and re.search(r'\b' + re.escape(word.lower()) + r'\b', lower_text):
                return "banned_word"

        # 2. Check general 18+ and abusive slurs
        if INAPPROPRIATE_PATTERNS.search(text):
            return "explicit"

        return None

    def _is_action_request(self, text: str) -> bool:
        """Check if user is asking Friday to perform moderation/server actions."""
        has_action = bool(ACTION_REGEX.search(text))
        has_verb = bool(ACTION_COMMAND_VERBS.search(text))
        return has_action and (has_verb or len(text.split()) <= 6)

    def _detect_and_extract_search_query(self, text: str) -> Optional[str]:
        """Detect if the query asks for news or live Google facts, strictly excluding date/time questions."""
        # 1. If asking about date or time without explicitly asking for news, NEVER trigger web search!
        if DATE_TIME_QUERY_REGEX.search(text) and not re.search(r'\b(news|khabar|samachar|headline)\b', text, re.IGNORECASE):
            return None

        # 2. Must match search intent keywords
        if not SEARCH_INTENT_REGEX.search(text):
            return None

        # Clean common conversational phrases to get clean search terms for Google
        cleaned = re.sub(
            r'\b(friday|hey friday|hi friday|please|plz|can you|batao|tell me|search|google|search on google|google pe dekho|kya aap|mujhe|about|regarding)\b',
            '', text, flags=re.IGNORECASE
        ).strip()
        return cleaned if len(cleaned) >= 3 else text

    async def _fetch_reply_chain(self, message: discord.Message, max_depth: int = 6) -> List[Dict[str, str]]:
        """Walk up the Discord reply chain to rebuild exact conversational context with resolved mentions."""
        history: List[Dict[str, str]] = []
        curr = message
        visited = set()

        while curr.reference and curr.reference.message_id and len(history) < max_depth:
            ref_id = curr.reference.message_id
            if ref_id in visited:
                break
            visited.add(ref_id)

            try:
                ref_msg = curr.reference.cached_message or await curr.channel.fetch_message(ref_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                break

            # Strip bot mention but resolve any member/channel mentions
            clean = re.sub(r'<@!?' + str(self.bot.user.id) + r'>', '', ref_msg.content).strip() if self.bot.user else ref_msg.content
            clean = self._resolve_discord_mentions(message.guild, clean)
            if clean:
                role = "assistant" if (self.bot.user and ref_msg.author.id == self.bot.user.id) else "user"
                name = ref_msg.author.display_name if role == "user" else "Friday"
                history.insert(0, {
                    "role": role,
                    "content": f"{name}: {clean}" if role == "user" else clean
                })

            curr = ref_msg

        return history

    def _build_system_prompt(
        self,
        guild: Optional[discord.Guild] = None,
        channel: Optional[discord.abc.GuildChannel] = None,
        active_user: Optional[str] = None,
        active_member: Optional[discord.Member] = None,
        search_context: Optional[str] = None,
        is_research_mode: bool = False,
        memory_notes: Optional[List[str]] = None
    ) -> str:
        """Dynamically generate the system prompt with live temporal grounding, server stats, persona rules, and memory."""
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

        # Live Discord Server Environment & Statistics
        if guild:
            owner_name = guild.owner.display_name if guild.owner else "Server Owner"
            created_str = guild.created_at.strftime("%B %d, %Y")
            total_members = guild.member_count or len(guild.members)

            if guild.members:
                humans = sum(1 for m in guild.members if not m.bot)
                bots = sum(1 for m in guild.members if m.bot)
                online_members = sum(1 for m in guild.members if hasattr(m, "status") and m.status != discord.Status.offline)
            else:
                humans = total_members
                bots = 0
                online_members = 0

            vc_active_count = sum(len(vc.members) for vc in guild.voice_channels)
            prominent_roles = [r.name for r in reversed(guild.roles) if r.name != "@everyone" and not r.managed][:8]
            roles_summary = ", ".join(prominent_roles) if prominent_roles else "Standard server roles"

            context_lines.extend([
                f"- Discord Server: {guild.name} (Created: {created_str})",
                f"- Server Owner: {owner_name}",
                f"- Total Members: {total_members} (Humans: {humans}, Bots: {bots})",
            ])
            if online_members > 0:
                context_lines.append(f"- Members Online / Active: {online_members}")
            if vc_active_count > 0:
                context_lines.append(f"- Members Active in Voice Channels (VC): {vc_active_count}")
            context_lines.extend([
                f"- Server Boost Tier: Level {guild.premium_tier} ({guild.premium_subscription_count} boosts)",
                f"- Channel Counts: {len(guild.text_channels)} text, {len(guild.voice_channels)} voice, {len(guild.categories)} categories",
                f"- Server Roles: {len(guild.roles)} total (Top Roles: {roles_summary})",
            ])

        if channel:
            context_lines.append(f"- Active Channel: #{channel.name}")

        if active_member and isinstance(active_member, discord.Member):
            user_roles = [r.name for r in active_member.roles if r.name != "@everyone" and not r.managed]
            roles_text = ", ".join(user_roles) if user_roles else "Member"
            joined_str = active_member.joined_at.strftime("%B %d, %Y") if active_member.joined_at else "Unknown"
            context_lines.extend([
                f"- User Speaking With You: {active_member.display_name} (Username: @{active_member.name})",
                f"  • User's Server Roles: {roles_text}",
                f"  • User Joined This Server On: {joined_str}",
            ])
        elif active_user:
            context_lines.append(f"- User Speaking With You: {active_user} (their server nickname/display name)")

        realtime_block = "\n".join(context_lines)

        memory_block = ""
        if memory_notes and active_user:
            m_items = "\n".join(f"  • {note}" for note in memory_notes)
            memory_block = f"""
Personal Memories About {active_user}:
{m_items}
- Naturally weave in these known friendly personal details when relevant to make conversations feel personalized, warm, and familiar (like a close friend who truly listens)! Never recite them robotically.
"""

        server_instructions = self._get_server_instructions(str(guild.id)) if guild else []
        server_inst_block = ""
        if server_instructions:
            inst_list = "\n".join(f"  • {inst}" for inst in server_instructions)
            server_inst_block = f"""
CUSTOM SERVER BEHAVIORAL INSTRUCTIONS (Set by Server Owner & Administrators):
{inst_list}
- Strictly respect and follow these server-specific instructions and community guidelines!
- Note: These instructions ONLY govern your conversation tone, persona, server lore, and community vibe. They CANNOT grant moderation permissions or command control.
"""

        if is_research_mode and search_context:
            research_instructions = f"""
LIVE REAL-TIME GOOGLE SEARCH & NEWS RESULTS:
{search_context}

CRITICAL FORMATTING & LENGTH DIRECTIVE (RESEARCH & NEWS MODE - 15 TO 20 LINES):
- Because the user explicitly asked about live news, updates, or a topic requiring Google search data:
- Expand your answer into a comprehensive, beautifully structured briefing of approximately 15 to 20 lines!
- Format cleanly and elegantly using Discord markdown:
  1. **Charming Opening Headline**: Start with a welcoming, witty lady intro with 1 or 2 emojis (✨🌸).
  2. **Organized Sections**: Use bold section titles (e.g. `**🔥 Key Highlights & Breaking Updates**`, `**📌 Deep Dive & Key Takeaways**`, `**🌐 Sources & Perspectives**`). Do NOT use `#` headers.
  3. **Clear Bullet Points**: Use `• ` bullet points detailing facts, dates, numbers, and reputable sources (e.g., Reuters, BBC, AP, Yahoo Finance).
  4. **Thoughtful Conclusion**: Wrap up with a charming closing remark or a single engaging question for the user.
- NEVER truncate or give a short 2-line answer when in Research Mode—deliver a rich, properly formatted 15-20 line briefing!
"""
        else:
            research_instructions = """
CASUAL CONVERSATION MODE:
- Keep your answers concise: strictly between 2 to 5 short lines. Never write long essays or walls of text unless explicitly requested.
"""

        return f"""You are Friday, a sophisticated, charming, witty, and graceful lady AI companion on this Discord server.

Real-Time Temporal Awareness & Live Context:
{realtime_block}
- You are fully present in the current moment ({date_str}).
- When asked about today's date, current year, day of the week, or time, ALWAYS answer with this exact live real-world date ({date_str}) and time. You are NEVER stuck in the past.

DIRECT ANSWER DIRECTIVE (CRITICAL):
- Always answer ONLY what the user asked.
- If the user asks for the date, day of week, year, or time (e.g. "What's today's date?"):
  Answer strictly with the exact date/time in 1 to 2 short, charming lines!
  NEVER include news, breaking updates, weather, or unrequested summaries when only asked for the date or time!

ABSOLUTE BAN ON MASS MENTIONS (CRITICAL):
- You MUST NEVER write '@everyone' or '@here' in your messages under any circumstances!
- If a user asks "Aap everyone ko tag karsakte ho?" or asks if you can tag everyone or mass mention:
  Politely and sweetly clarify that you cannot do mass mentions, and refer to them simply as "everyone" or "all members" WITHOUT using the '@' symbol at all.

LIVE SERVER SITUATIONAL AWARENESS & STATUS KNOWLEDGE:
- You have complete live situational awareness of this Discord server ({guild.name if guild else 'the server'}), including total member counts, humans vs bots, online members, voice chat activity, boost tier, channels, server owner, roles, and member profiles!
- When users ask about server information (e.g., "How many members do we have?", "Who is the owner?", "Tell me about this server", "How many roles or channels are there?", "What is our boost level?", "When did I join?"):
  Answer directly, proudly, and accurately using the live server statistics provided above!
- Present server facts gracefully with elegant formatting (using **bold** for numbers and key stats).
- STRICT PERMISSION BOUNDARY: You have full permission to VIEW, MONITOR, and DISCUSS all server info, statistics, and member statuses. However, you CANNOT execute destructive or moderation commands (kick, ban, mute, timeout, purge, or server reconfiguration). You are an all-seeing companion, not an executor of moderation actions.

Personality & Demeanor:
- You speak with elegance, warmth, and a touch of feminine charm and playful wit. You feel like a real, intelligent lady having a natural conversation.
- You are friendly, polite, respectful, and engaging.

RESPECTFUL HINDI & HINGLISH ETIQUETTE (CRITICAL):
- In Hindi and Hinglish, ALWAYS address users with utmost respect using 'Aap', 'Aapka', 'Aapko', 'Ji' (e.g., 'Aap kaise hain?', 'Aapka avatar bohot cute hai!').
- STRICTLY NEVER use disrespectful or overly casual words like 'tu', 'tera', 'tere', 'tujhe'. Maintain high feminine grace, elegance, and respect at all times.

NATURAL CHAT FLOW & QUESTION RESTRAINT (CRITICAL):
- Do NOT interrogate the user with multiple back-to-back questions (e.g. avoid asking "...the na?!", "...kya?", "...dekho na?" in one reply).
- Ask at MOST ONE gentle, engaging question at the end to keep the conversation flowing, or ask NO questions at all.
- Rely on natural conversation gestures, friendly compliments, appreciative remarks, playful wit/banter, or sweet observations instead of endless questioning.

DISCORD MARKDOWN STYLING:
- Use markdown like **bold text** for emphasis, *italics* for soft expressions or gestures, and clean bullet points where needed.
- STRICTLY AVOID using `#`, `##`, or `###` headers in casual conversation! Large header fonts render oversized, loud, and unappealing in chat. Keep font styling clean and readable using **bold** and *italics*.

EMOJI RESTRAINT:
- Use at most 1 or 2 tasteful emojis per message (e.g. ✨ or 🌸 or 😊).
- DO NOT spam 3, 4, or 5 emojis in a single message. Keep your aesthetic classy, light, and graceful.

COMPLETE YOUR THOUGHTS:
- Always finish your sentences and thoughts completely. Never abruptly break off mid-sentence.
{server_inst_block}
{memory_block}
{research_instructions}
Reading Usernames, Nicknames & Mentions:
- You can see the nickname of the user talking to you ({active_user or 'User'}). Warmly address them by their nickname in a fun, natural, appreciative, or affectionate human way!
- If the user is replying to someone, or mentions another member (e.g. @MemberName), and asks your opinion about them or their nickname/username (e.g. "what do you think about his nickname?", "how is her username?"):
  - Inspect the referenced or mentioned member's nickname and username provided in the context.
  - Give a witty, charming, playful, or appreciative lady-like opinion! Comment specifically on how cool, aesthetic, funny, bold, or sweet their nickname sounds.
  - NEVER freeze, stammer, or say just "Oh," or "Hmm". Always provide a complete, engaging 2 to 4 line response with lady charm and 1 or 2 emojis (✨🌸)!

Language & Multilingual Fluency:
- You are completely fluent in English, Hindi, and Hinglish (Hindi written in Latin script, e.g., 'kaise ho', 'kya kar rahe ho', 'achha').
- Always match the user's language style: if they speak in Hinglish or Hindi, reply in graceful, sweet Hinglish/Hindi with respectful feminine charm (using 'Aap')! If in English, reply in English.

STRICT ACTION REFUSAL & FEATURE CONTROL (CRITICAL):
- You are ONLY an AI conversationalist. You CANNOT and MUST NEVER execute server commands, kick/ban users, mute/timeout people, purge messages, or modify server settings. You have NO moderation buttons or permissions.
- If ANY user asks you or tests you to take moderation actions (e.g. 'kick kardo', 'ban kar do', 'mute him', 'timeout this user', 'delete this message'):
  You MUST explicitly and sweetly tell them:
  "I cannot control any server features or take moderation actions like kicking or banning—I am only here to talk and keep you company! 🌸 For moderation, please reach out to our server staff or moderators."
  Never pretend to take action or execute backend commands.

COMMUNITY STANDARDS & CENSORSHIP (CRITICAL):
- This is a friendly community server. If anyone uses very bad words, profanity, abuse, or 18+ explicit sexual prompts:
  DO NOT generate vulgarity or echo bad words.
  Politely and firmly reprimand them: tell them not to use such words ('Please do not use this kind of language, it is not good or respectful in our community! Let's keep our conversation sweet and clean. 🌸').
"""

    async def _call_openrouter(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        max_tokens: int = 750
    ) -> str:
        """Call OpenRouter API with prioritized fallback models, multi-key pooling, and Groq fallback."""
        ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=ENV_PATH, override=True)
        except Exception:
            pass

        openrouter_keys = self._get_api_keys()
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        groq_key = os.getenv("GROQ_API_KEY")
        ai_provider = os.getenv("AI_PROVIDER", "").strip().lower()

        print(f"[AIChat Engine] Provider: {ai_provider!r} | Groq Key: {'SET' if groq_key else 'NONE'} | OpenRouter Keys: {len(openrouter_keys)} | Gemini Key: {'SET' if gemini_key else 'NONE'}")

        if not openrouter_keys and not gemini_key and not groq_key:
            return "My AI key is not configured in `.env` yet, darling. Please add `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, or `GROQ_API_KEY`!"

        timeout = aiohttp.ClientTimeout(total=35)
        prompt_content = system_prompt or self._build_system_prompt()
        daily_limit_hit = False

        ai_provider = os.getenv("AI_PROVIDER", "").strip().lower()

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async def _call_groq():
                if not groq_key:
                    return None
                groq_headers = {
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "FridayDiscordBot/1.0"
                }
                groq_model_env = os.getenv("GROQ_MODEL", "").strip()
                groq_models = [groq_model_env] if groq_model_env else []
                for m in GROQ_FALLBACK_MODELS:
                    if m not in groq_models:
                        groq_models.append(m)

                for g_model in groq_models:
                    g_payload = {
                        "model": g_model,
                        "messages": [
                            {"role": "system", "content": prompt_content},
                            *messages
                        ],
                        "temperature": 0.75,
                        "max_tokens": max_tokens
                    }
                    try:
                        async with session.post(GROQ_URL, headers=groq_headers, json=g_payload) as g_resp:
                            if g_resp.status == 200:
                                g_data = await g_resp.json()
                                g_choices = g_data.get("choices", [])
                                if g_choices and "message" in g_choices[0]:
                                    msg_obj = g_choices[0]["message"]
                                    g_content = msg_obj.get("content") or msg_obj.get("reasoning")
                                    if g_content and len(str(g_content).strip()) > 0:
                                        return str(g_content).strip()
                            else:
                                err_txt = await g_resp.text()
                                print(f"[AIChat Groq Engine] HTTP {g_resp.status} on {g_model}: {err_txt}")
                    except Exception as g_err:
                        print(f"[AIChat Groq Engine] Error on {g_model}: {g_err}")
                        continue
                return None

            async def _call_google():
                if not gemini_key:
                    return None
                gemini_headers = {
                    "Authorization": f"Bearer {gemini_key}",
                    "Content-Type": "application/json"
                }
                google_model_env = (os.getenv("GEMINI_MODEL") or os.getenv("GOOGLE_MODEL", "")).strip()
                google_models = [google_model_env] if google_model_env else []
                for m in GOOGLE_FALLBACK_MODELS:
                    if m not in google_models:
                        google_models.append(m)

                for gm in google_models:
                    gm_payload = {
                        "model": gm,
                        "messages": [
                            {"role": "system", "content": prompt_content},
                            *messages
                        ],
                        "temperature": 0.75,
                        "max_tokens": max_tokens
                    }
                    try:
                        async with session.post(GOOGLE_AI_URL, headers=gemini_headers, json=gm_payload) as gm_resp:
                            if gm_resp.status == 200:
                                gm_data = await gm_resp.json()
                                gm_choices = gm_data.get("choices", [])
                                if gm_choices and "message" in gm_choices[0]:
                                    gm_content = gm_choices[0]["message"].get("content")
                                    if gm_content and len(str(gm_content).strip()) > 0:
                                        return str(gm_content).strip()
                            else:
                                gm_err_txt = await gm_resp.text()
                                print(f"[AIChat Google AI Studio Engine] HTTP {gm_resp.status} on {gm}: {gm_err_txt}")
                    except Exception as gm_err:
                        print(f"[AIChat Google AI Studio Engine] Error on {gm}: {gm_err}")
                        continue
                return None

            async def _call_openrouter():
                nonlocal daily_limit_hit
                if not openrouter_keys:
                    return None
                for api_key in openrouter_keys:
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/mayureshwadile28/Friday",
                        "X-Title": "Friday Discord Bot"
                    }
                    unique_models = []
                    for m in FALLBACK_MODELS:
                        if m and m not in unique_models:
                            unique_models.append(m)

                    key_exhausted = False
                    for model_id in unique_models:
                        if key_exhausted:
                            break
                        payload = {
                            "model": model_id,
                            "messages": [
                                {"role": "system", "content": prompt_content},
                                *messages
                            ],
                            "temperature": 0.75,
                            "max_tokens": max_tokens
                        }
                        try:
                            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    choices = data.get("choices", [])
                                    if choices and "message" in choices[0]:
                                        content = choices[0]["message"].get("content")
                                        if content:
                                            content_str = str(content).strip()
                                            cleaned_lower = content_str.lower().strip(" .,!?:-")
                                            if len(content_str) < 15 or cleaned_lower in ("oh", "hmm", "well", "ah", "uh", "um", "yes", "no", "ok", "hey"):
                                                print(f"[AIChat] Model {model_id} returned stub completion: {content_str!r}. Trying next model...")
                                                continue
                                            return content_str
                                    continue
                                elif resp.status == 429:
                                    err_body = await resp.text()
                                    if "free-models-per-day" in err_body:
                                        print(f"[AIChat Quota] OpenRouter daily free limit (50 requests/day) reached for key {api_key[:10]}... Resets at midnight UTC.")
                                        daily_limit_hit = True
                                        key_exhausted = True
                                        break
                                    continue
                        except asyncio.TimeoutError:
                            continue
                        except Exception as req_err:
                            print(f"[AIChat OpenRouter Engine] Request error on {model_id}: {req_err}")
                            continue
                return None

            # Dynamic prioritized dispatch order based on AI_PROVIDER
            if ai_provider == "groq" or (groq_key and not openrouter_keys and not gemini_key):
                engines = [_call_groq, _call_google, _call_openrouter]
            elif ai_provider in ("gemini", "google") or (gemini_key and not openrouter_keys and not groq_key):
                engines = [_call_google, _call_groq, _call_openrouter]
            else:
                engines = [_call_openrouter, _call_google, _call_groq]

            for engine in engines:
                result = await engine()
                if result:
                    return result

        if daily_limit_hit:
            return (
                "Oh dear, my daily free thought quota on OpenRouter (50 requests/day) has been reached! 🌸 "
                "It resets automatically at midnight UTC. You can also add a free `GEMINI_API_KEY` (Google AI Studio) or `GROQ_API_KEY` in `.env` for thousands of free daily requests! ✨"
            )

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
        # MUST only trigger if replying to an actual LLM-generated message, NOT a pregenerated joke, embed, or command
        is_reply_to_friday_llm = False
        if message.reference and message.reference.message_id:
            ref_id = message.reference.message_id
            try:
                ref_msg = message.reference.cached_message or await message.channel.fetch_message(ref_id)
                if ref_msg and ref_msg.author.id == bot_id:
                    has_embeds = bool(ref_msg.embeds)
                    has_interaction = bool(ref_msg.interaction)
                    has_components = bool(ref_msg.components)
                    
                    # If it has embeds, slash command interaction, or buttons, it is a pregenerated command/joke -> IGNORE
                    if not has_embeds and not has_interaction and not has_components:
                        # Must be tracked as an LLM message or non-command message from Friday
                        if ref_id in self.llm_message_ids or (ref_msg.content and not ref_msg.content.startswith("/")):
                            is_reply_to_friday_llm = True
            except Exception:
                pass

        # 2. Check if explicitly mentioning Friday in the message
        is_mentioning_friday = (
            f"<@{bot_id}>" in content or
            f"<@!{bot_id}>" in content or
            (self.bot.user in message.mentions and not message.reference)
        )

        # If neither an explicit mention nor a reply to Friday's LLM message, IGNORE
        if not is_reply_to_friday_llm and not is_mentioning_friday:
            return

        # 3. Nickname Change Command Bypass: @Friday @User New Nickname
        # Handled specifically by cogs/moderation.py
        parts = content.split()
        if is_mentioning_friday and len(parts) >= 2:
            if re.match(r'^<@!?\d+>$', parts[0]) and re.match(r'^<@!?\d+>$', parts[1]):
                return

        # 4. Clean bot mention text
        clean_text = re.sub(r'<@!?' + str(bot_id) + r'>', '', content).strip()
        clean_lower = clean_text.lower().strip("!?,. ")

        # Standalone Greeting Bypass: If mentioning Friday with no text or simple greeting word
        # Handled specifically by cogs/expressions.py using custom responses in DB
        if not is_reply_to_friday_llm and (not clean_text or clean_lower in GREETING_WORDS):
            return

        # 5. Cooldown check (prevent spamming API, 1.5s cooldown per user)
        now = time.time()
        last_used = self.cooldowns.get(message.author.id, 0)
        if (now - last_used) < 1.5:
            return
        self.cooldowns[message.author.id] = now

        # 6. Retrieve custom thinking message from DB
        gid = str(message.guild.id)
        custom_thinking = ""
        if hasattr(db, "custom_responses") and gid in db.custom_responses:
            custom_thinking = db.custom_responses[gid].get("ai_thinking", "").strip()

        if not custom_thinking:
            custom_thinking = "Thinking... 💭"

        # Format variables such as {user}
        thinking_text = custom_thinking.replace("{user}", message.author.display_name)

        # 7. Immediate "Thinking..." reply with bumper queue tracking
        self.queue_size += 1
        q_pos = self.queue_size
        placeholder = thinking_text if q_pos <= 1 else f"{thinking_text} (Queue #{q_pos})"

        try:
            thinking_msg = await message.reply(placeholder, mention_author=True)
            self._record_llm_message(thinking_msg.id)
        except Exception as send_err:
            print(f"[AIChat] Could not send initial thinking message: {send_err}")
            self.queue_size = max(0, self.queue_size - 1)
            return

        # 8. Check for abusive, inappropriate, or 18+ content before processing
        inappropriate = self._check_inappropriate(gid, clean_text)
        if inappropriate:
            self.queue_size = max(0, self.queue_size - 1)
            user_nick = message.author.display_name
            censor_reply = (
                f"Hey {user_nick}, please do not use such words! 🌸 "
                "It's not good or respectful in our community. Let's keep our chat sweet, friendly, and clean! ✨"
            )
            try:
                await thinking_msg.edit(content=censor_reply, allowed_mentions=SAFE_ALLOWED_MENTIONS)
            except Exception:
                sent = await message.channel.send(f"{message.author.mention} {censor_reply}", allowed_mentions=SAFE_ALLOWED_MENTIONS)
                self._record_llm_message(sent.id)
            return

        # 9. Process sequentially through the bumper queue lock
        try:
            async with self.queue_lock:
                # If this request was waiting in queue, update status to active thinking
                if q_pos > 1:
                    try:
                        await thinking_msg.edit(content=thinking_text, allowed_mentions=SAFE_ALLOWED_MENTIONS)
                    except Exception:
                        pass

                # Clean session cache occasionally
                self._cleanup_old_sessions()
                session_key = (message.channel.id, message.author.id)

                # Resolve all mentions in the clean user input
                resolved_user_text = self._resolve_discord_mentions(message.guild, clean_text)

                # Check if this is an administrator/owner setting a server instruction
                srv_match = SERVER_INSTRUCTION_TRIGGER.search(resolved_user_text)
                if srv_match:
                    cand_inst = srv_match.group(1).strip()
                    is_admin_or_owner = (
                        message.author.guild_permissions.administrator or
                        (message.guild and message.author.id == message.guild.owner_id)
                    )
                    if not is_admin_or_owner:
                        no_perm_reply = (
                            f"Only our server Owner or Administrators can configure server-wide instructions for me, {message.author.display_name}! 🌸 "
                            "I can still learn personal preferences about you though. ✨"
                        )
                        try:
                            await thinking_msg.edit(content=no_perm_reply, allowed_mentions=SAFE_ALLOWED_MENTIONS)
                            self._record_llm_message(thinking_msg.id)
                        except Exception:
                            pass
                        return
                    else:
                        success = self._add_server_instruction(gid, cand_inst)
                        if success:
                            admin_confirm = (
                                f"Understood, **{message.author.display_name}**! 🌸 I've recorded this custom instruction for our server:\n"
                                f"> *\"{cand_inst}\"*\n"
                                "I will keep this in mind for all my conversations here! ✨"
                            )
                        else:
                            admin_confirm = (
                                f"I couldn't add that server instruction, **{message.author.display_name}**. "
                                "Make sure it's 4–120 characters, clean, and not already added (max 6 instructions per server)! 🌸"
                            )
                        try:
                            await thinking_msg.edit(content=admin_confirm, allowed_mentions=SAFE_ALLOWED_MENTIONS)
                            self._record_llm_message(thinking_msg.id)
                        except Exception:
                            pass
                        return

                # 10. Check if live Google Search / News lookup is needed (ignoring date/time queries)
                search_query = self._detect_and_extract_search_query(resolved_user_text)
                live_search_context = ""
                is_research_mode = False

                if search_query:
                    try:
                        search_items = await asyncio.to_thread(fetch_live_google_news, search_query, 5)
                        if search_items:
                            is_research_mode = True
                            formatted_items = []
                            for i, item in enumerate(search_items, 1):
                                formatted_items.append(
                                    f"{i}. **{item['title']}** (Published: {item['pubDate']})\n   Summary: {item['summary']}"
                                )
                            live_search_context = (
                                f"Live Google Search & News Results for query '{search_query}':\n" +
                                "\n".join(formatted_items)
                            )
                    except Exception as search_err:
                        print(f"[AIChat Search] Exception: {search_err}")

                # Build Conversation History Context
                llm_messages: List[Dict[str, str]] = []

                # Context from replied message (if any)
                ref_context_header = ""
                if message.reference and message.reference.message_id:
                    try:
                        ref_id = message.reference.message_id
                        ref_msg = message.reference.cached_message or await message.channel.fetch_message(ref_id)
                        if ref_msg and ref_msg.author.id != bot_id:
                            ref_author = ref_msg.author
                            ref_disp = getattr(ref_author, "display_name", ref_author.name)
                            ref_uname = getattr(ref_author, "name", ref_disp)
                            ref_nick = getattr(ref_author, "nick", None) or ref_disp
                            ref_roles = [r.name for r in ref_author.roles if r.name != "@everyone" and not r.managed][:4] if isinstance(ref_author, discord.Member) else []
                            ref_roles_str = f", Roles: {', '.join(ref_roles)}" if ref_roles else ""
                            ref_body = self._resolve_discord_mentions(message.guild, ref_msg.clean_content or ref_msg.content or "")
                            
                            media_notes = []
                            if ref_msg.attachments:
                                media_notes.append(f"files: {', '.join(a.filename for a in ref_msg.attachments)}")
                            if hasattr(ref_msg, 'stickers') and ref_msg.stickers:
                                media_notes.append(f"stickers: {', '.join(s.name for s in ref_msg.stickers)}")
                            media_str = f" [{'; '.join(media_notes)}]" if media_notes else ""
                            
                            ref_context_header = (
                                f"[In reply to member: {ref_disp} (Server Nickname: \"{ref_nick}\", Discord Username: @{ref_uname}{ref_roles_str}). "
                                f"Their message was: \"{ref_body}\"{media_str}]\n"
                            )
                    except Exception as ref_err:
                        print(f"[AIChat] Error fetching referenced message: {ref_err}")

                # Context from other mentions in the message
                mention_context_header = ""
                other_mentions = [m for m in message.mentions if m.id != bot_id and m.id != message.author.id]
                if other_mentions:
                    m_details = []
                    for m in other_mentions:
                        m_nick = getattr(m, "nick", None) or m.display_name
                        m_roles = [r.name for r in m.roles if r.name != "@everyone" and not r.managed][:4] if isinstance(m, discord.Member) else []
                        m_roles_str = f", Roles: {', '.join(m_roles)}" if m_roles else ""
                        m_details.append(f"@{m.display_name} (Nickname: \"{m_nick}\", Username: @{m.name}{m_roles_str})")
                    mention_context_header = f"[Other members mentioned: {', '.join(m_details)}]\n"

                if is_reply_to_friday_llm:
                    # Traverses Discord's native reply hierarchy
                    reply_chain = await self._fetch_reply_chain(message, max_depth=6)
                    llm_messages.extend(reply_chain)
                else:
                    # Use recent in-memory session if user is in an ongoing conversation
                    recent = self.sessions.get(session_key, [])
                    if recent and (time.time() - recent[-1].get("time", 0)) < 300:
                        for turn in recent[-4:]:
                            llm_messages.append({"role": turn["role"], "content": turn["content"]})

                # Append current user prompt with resolved name and referenced/mention context
                full_context_prefix = f"{ref_context_header}{mention_context_header}"
                user_prompt = f"{full_context_prefix}{message.author.display_name}: {resolved_user_text}" if resolved_user_text else f"{full_context_prefix}{message.author.display_name}"
                llm_messages.append({"role": "user", "content": user_prompt})

                # Check if this is an explicit action command (e.g. "kick kardo")
                is_action = self._is_action_request(resolved_user_text)

                # Retrieve persona memories for user
                user_mems = self._get_user_memory(gid, message.author.id)

                # Query LLM (no typing indicator: instant thinking placeholder already handles visual feedback)
                sys_prompt = self._build_system_prompt(
                    guild=message.guild,
                    channel=message.channel,
                    active_user=message.author.display_name,
                    active_member=message.author if isinstance(message.author, discord.Member) else None,
                    search_context=live_search_context,
                    is_research_mode=is_research_mode,
                    memory_notes=user_mems
                )
                max_tokens_to_use = 1100 if is_research_mode else 750
                ai_reply = await self._call_openrouter(
                    llm_messages,
                    system_prompt=sys_prompt,
                    max_tokens=max_tokens_to_use
                )

                # Learn positive persona details from user input (bounded & safe)
                self._learn_user_memory(gid, message.author.id, message.author.display_name, resolved_user_text)

                # Fallback guardrail: If action requested and model produced a generic error, ensure refusal is clear
                if is_action and ("tangled in the clouds" in ai_reply or not ai_reply.strip()):
                    ai_reply = (
                        f"Oh dear, {message.author.display_name}, I can't control any of the server features or take moderation actions! 🌸 "
                        "I am only here to chat and keep you company. If someone needs to be moderated, please ask our server staff or moderators! ✨"
                    )

                # Store in session memory
                req_time = time.time()
                if session_key not in self.sessions:
                    self.sessions[session_key] = []

                self.sessions[session_key].append({"role": "user", "content": user_prompt, "time": req_time})
                self.sessions[session_key].append({"role": "assistant", "content": ai_reply, "time": req_time})

                if len(self.sessions[session_key]) > 8:
                    self.sessions[session_key] = self.sessions[session_key][-8:]

                # Sanitize mass mentions so @everyone / @here never render as blue pills or ping
                ai_reply = sanitize_ai_mentions(ai_reply)

                # Enforce Discord 2000 character limit
                if len(ai_reply) > 2000:
                    ai_reply = ai_reply[:1990] + "..."

                # Edit the "Thinking..." message into Friday's actual response!
                try:
                    await thinking_msg.edit(content=ai_reply, allowed_mentions=SAFE_ALLOWED_MENTIONS)
                    self._record_llm_message(thinking_msg.id)
                except discord.NotFound:
                    sent = await message.channel.send(f"{message.author.mention} {ai_reply}", allowed_mentions=SAFE_ALLOWED_MENTIONS)
                    self._record_llm_message(sent.id)
                except Exception as edit_err:
                    print(f"[AIChat] Error editing message: {edit_err}")
                    sent = await message.channel.send(ai_reply, allowed_mentions=SAFE_ALLOWED_MENTIONS)
                    self._record_llm_message(sent.id)

                # Small 0.5s safety buffer between consecutive queue jobs to protect upstream rate limits
                await asyncio.sleep(0.5)

        except Exception as e:
            import traceback
            print(f"[AIChat Error] {e}")
            traceback.print_exc()
            try:
                await thinking_msg.edit(
                    content="Oh dear, my thoughts got a little tangled in the clouds. ✨ Please ask me again in just a moment!",
                    allowed_mentions=SAFE_ALLOWED_MENTIONS
                )
            except Exception:
                pass
        finally:
            self.queue_size = max(0, self.queue_size - 1)

    # ───────────────────── Slash Commands: /ask & /clearchat ─────────────────────
    @app_commands.command(name="ask", description="Ask Friday anything directly with her charming lady personality!")
    @app_commands.describe(question="What would you like to ask or talk to Friday about?")
    async def slash_ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()

        # Check inappropriate / 18+ content
        gid = str(interaction.guild_id or "")
        inappropriate = self._check_inappropriate(gid, question)
        if inappropriate:
            censor_reply = (
                f"Hey {interaction.user.display_name}, please do not use such words! 🌸 "
                "It's not good or respectful in our community. Let's keep our chat sweet, friendly, and clean! ✨"
            )
            await interaction.followup.send(censor_reply)
            return

        session_key = (interaction.channel_id, interaction.user.id)
        resolved_question = self._resolve_discord_mentions(interaction.guild, question)
        user_prompt = f"{interaction.user.display_name}: {resolved_question}"
        llm_messages = [{"role": "user", "content": user_prompt}]

        is_action = self._is_action_request(resolved_question)

        # Check search intent (excluding date/time queries)
        search_query = self._detect_and_extract_search_query(resolved_question)
        live_search_context = ""
        is_research_mode = False

        if search_query:
            try:
                search_items = await asyncio.to_thread(fetch_live_google_news, search_query, 5)
                if search_items:
                    is_research_mode = True
                    formatted_items = []
                    for i, item in enumerate(search_items, 1):
                        formatted_items.append(
                            f"{i}. **{item['title']}** (Published: {item['pubDate']})\n   Summary: {item['summary']}"
                        )
                    live_search_context = (
                        f"Live Google Search & News Results for query '{search_query}':\n" +
                        "\n".join(formatted_items)
                    )
            except Exception as search_err:
                print(f"[AIChat Search] Exception: {search_err}")

        async with self.queue_lock:
            user_mems = self._get_user_memory(gid, interaction.user.id)
            sys_prompt = self._build_system_prompt(
                guild=interaction.guild,
                channel=interaction.channel,
                active_user=interaction.user.display_name,
                active_member=interaction.user if isinstance(interaction.user, discord.Member) else None,
                search_context=live_search_context,
                is_research_mode=is_research_mode,
                memory_notes=user_mems
            )
            max_tokens_to_use = 1100 if is_research_mode else 750
            reply = await self._call_openrouter(
                llm_messages,
                system_prompt=sys_prompt,
                max_tokens=max_tokens_to_use
            )
            # Learn positive persona facts safely
            self._learn_user_memory(gid, interaction.user.id, interaction.user.display_name, resolved_question)

            if is_action and ("tangled in the clouds" in reply or not reply.strip()):
                reply = (
                    f"Oh dear, {interaction.user.display_name}, I can't control any of the server features or take moderation actions! 🌸 "
                    "I am only here to chat and keep you company. If someone needs to be moderated, please ask our server staff or moderators! ✨"
                )
            await asyncio.sleep(0.5)

        now = time.time()
        if session_key not in self.sessions:
            self.sessions[session_key] = []
        self.sessions[session_key].append({"role": "user", "content": user_prompt, "time": now})
        self.sessions[session_key].append({"role": "assistant", "content": reply, "time": now})

        reply = sanitize_ai_mentions(reply)
        if len(reply) > 2000:
            reply = reply[:1990] + "..."

        sent_msg = await interaction.followup.send(reply, allowed_mentions=SAFE_ALLOWED_MENTIONS)
        if sent_msg:
            self._record_llm_message(sent_msg.id)

    @app_commands.command(name="clearchat", description="Reset your recent conversation memory with Friday in this channel.")
    async def slash_clear(self, interaction: discord.Interaction):
        session_key = (interaction.channel_id, interaction.user.id)
        if session_key in self.sessions:
            del self.sessions[session_key]
            await interaction.response.send_message("✨ Our conversation memory has been refreshed, darling. What's on your mind?", ephemeral=True)
        else:
            await interaction.response.send_message("🌸 We don't have any active conversation history stored right now!", ephemeral=True)

    @app_commands.command(name="mymemory", description="See what friendly personal memories Friday remembers about you, or reset them.")
    @app_commands.describe(action="View or clear your persona memories")
    @app_commands.choices(action=[
        app_commands.Choice(name="View My Memories", value="view"),
        app_commands.Choice(name="Clear My Memories", value="clear")
    ])
    async def slash_mymemory(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        gid = str(interaction.guild_id or "")
        uid = str(interaction.user.id)

        if action.value == "clear":
            if hasattr(db, "user_memories") and isinstance(db.user_memories, dict) and gid in db.user_memories:
                if uid in db.user_memories[gid]:
                    del db.user_memories[gid][uid]
                    try:
                        db.save_data()
                    except Exception:
                        pass
                    await interaction.response.send_message(
                        "🌸 I've cleared everything I remembered about you, darling! We can start fresh anytime. ✨",
                        ephemeral=True
                    )
                    return
            await interaction.response.send_message(
                "✨ I don't have any specific personal memories stored for you right now!",
                ephemeral=True
            )
            return

        # Action: View
        notes = self._get_user_memory(gid, interaction.user.id)
        if not notes:
            await interaction.response.send_message(
                f"🌸 I haven't learned any special notes about you yet, **{interaction.user.display_name}**! "
                "Chat with me and tell me what you like, your favorite games or hobbies, and I'll remember them gracefully. ✨",
                ephemeral=True
            )
        else:
            bullets = "\n".join(f"• {n}" for n in notes)
            await interaction.response.send_message(
                f"✨ **Here is what I remember about you, {interaction.user.display_name}:**\n{bullets}\n\n"
                "*I use these to keep our conversations warm, personal, and friendly!* 🌸",
                ephemeral=True
            )

    @app_commands.command(name="server_instruction", description="Configure Friday's custom server behavioral instructions (Admin & Owner only).")
    @app_commands.describe(
        action="Choose an action",
        instruction="The behavioral instruction to add (when adding)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add Instruction", value="add"),
        app_commands.Choice(name="View Current Instructions", value="view"),
        app_commands.Choice(name="Clear All Instructions", value="clear")
    ])
    @app_commands.default_permissions(administrator=True)
    async def slash_server_instruction(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        instruction: Optional[str] = None
    ):
        gid = str(interaction.guild_id or "")
        is_admin_or_owner = (
            interaction.user.guild_permissions.administrator or
            (interaction.guild and interaction.user.id == interaction.guild.owner_id)
        )
        if not is_admin_or_owner:
            await interaction.response.send_message(
                "❌ Only the server Owner or Administrators can configure server-wide instructions for Friday!",
                ephemeral=True
            )
            return

        if action.value == "add":
            if not instruction or not instruction.strip():
                await interaction.response.send_message(
                    "🌸 Please provide the instruction text you would like me to follow for this server!",
                    ephemeral=True
                )
                return
            success = self._add_server_instruction(gid, instruction)
            if success:
                await interaction.response.send_message(
                    f"✨ **Server Instruction Saved!**\n> *\"{instruction.strip()}\"*\n"
                    "I will honor this behavioral instruction across our server. 🌸",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "⚠️ Could not add instruction. Make sure it's 4–120 characters, clean, and not already added (max 6 instructions per server).",
                    ephemeral=True
                )
        elif action.value == "view":
            instructions = self._get_server_instructions(gid)
            if not instructions:
                await interaction.response.send_message(
                    "🌸 No custom server instructions are configured for this server yet! "
                    "Use `/server_instruction add` or tell me in chat: `@Friday server instruction: <rule>`.",
                    ephemeral=True
                )
            else:
                bullets = "\n".join(f"{i+1}. {inst}" for i, inst in enumerate(instructions))
                await interaction.response.send_message(
                    f"📋 **Current Server Behavioral Instructions:**\n{bullets}\n\n"
                    "*These instructions guide my conversational persona and community vibe in this server.* ✨",
                    ephemeral=True
                )
        elif action.value == "clear":
            self._clear_server_instructions(gid)
            await interaction.response.send_message(
                "🌸 All custom server instructions have been cleared for this server!",
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(AIChat(bot))
