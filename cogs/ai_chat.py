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
        search_context: Optional[str] = None,
        is_research_mode: bool = False,
        memory_notes: Optional[List[str]] = None
    ) -> str:
        """Dynamically generate the system prompt with live temporal grounding, research data, persona rules, and memory."""
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
        if active_user:
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
        """Call OpenRouter API with prioritized fallback models on upstream rate limits or empty responses."""
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

        timeout = aiohttp.ClientTimeout(total=40)
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
                                    # Discard stubs (< 15 characters or single interjections like "oh", "hmm", "well", etc.)
                                    if len(content_str) < 15 or cleaned_lower in ("oh", "hmm", "well", "ah", "uh", "um", "yes", "no", "ok", "hey"):
                                        print(f"[AIChat] Model {model_id} returned stub/incomplete completion: {content_str!r}. Trying next model...")
                                        continue
                                    return content_str
                            # If content was empty or None (e.g. reasoning model hit token limit), try next model
                            continue
                        elif resp.status in (429, 502, 503, 504):
                            # Upstream pool rate limit or server error -> try next candidate model
                            continue
                        else:
                            continue
                except asyncio.TimeoutError:
                    continue
                except Exception:
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
                await thinking_msg.edit(content=censor_reply)
            except Exception:
                sent = await message.channel.send(f"{message.author.mention} {censor_reply}")
                self._record_llm_message(sent.id)
            return

        # 9. Process sequentially through the bumper queue lock
        try:
            async with self.queue_lock:
                # If this request was waiting in queue, update status to active thinking
                if q_pos > 1:
                    try:
                        await thinking_msg.edit(content=thinking_text)
                    except Exception:
                        pass

                # Clean session cache occasionally
                self._cleanup_old_sessions()
                session_key = (message.channel.id, message.author.id)

                # Resolve all mentions in the clean user input
                resolved_user_text = self._resolve_discord_mentions(message.guild, clean_text)

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
                            ref_body = self._resolve_discord_mentions(message.guild, ref_msg.clean_content or ref_msg.content or "")
                            
                            media_notes = []
                            if ref_msg.attachments:
                                media_notes.append(f"files: {', '.join(a.filename for a in ref_msg.attachments)}")
                            if hasattr(ref_msg, 'stickers') and ref_msg.stickers:
                                media_notes.append(f"stickers: {', '.join(s.name for s in ref_msg.stickers)}")
                            media_str = f" [{'; '.join(media_notes)}]" if media_notes else ""
                            
                            ref_context_header = (
                                f"[In reply to member: {ref_disp} (Server Nickname: \"{ref_nick}\", Discord Username: @{ref_uname}). "
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
                        m_details.append(f"@{m.display_name} (Nickname: \"{m_nick}\", Username: @{m.name})")
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

                # Enforce Discord 2000 character limit
                if len(ai_reply) > 2000:
                    ai_reply = ai_reply[:1990] + "..."

                # Edit the "Thinking..." message into Friday's actual response!
                try:
                    await thinking_msg.edit(content=ai_reply)
                    self._record_llm_message(thinking_msg.id)
                except discord.NotFound:
                    sent = await message.channel.send(f"{message.author.mention} {ai_reply}")
                    self._record_llm_message(sent.id)
                except Exception as edit_err:
                    print(f"[AIChat] Error editing message: {edit_err}")
                    sent = await message.channel.send(ai_reply)
                    self._record_llm_message(sent.id)

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

        if len(reply) > 2000:
            reply = reply[:1990] + "..."

        sent_msg = await interaction.followup.send(reply)
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

async def setup(bot: commands.Bot):
    await bot.add_cog(AIChat(bot))
