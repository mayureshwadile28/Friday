import re
import discord

def replace_plain_emojis(text: str, bot=None, guild_id=None, guild=None) -> str:
    """
    Scans text for plain :emoji_name: patterns and resolves them to full Discord
    custom emoji format (<:name:id> or <a:name:id>), prioritizing the current guild's emojis.
    Leaves standard unicode emojis and already-formatted <a?:name:id> untouched.
    """
    if not text:
        return text

    emojis = []
    if guild and hasattr(guild, 'emojis'):
        emojis.extend(guild.emojis)
    elif guild_id and bot:
        try:
            target_g = bot.get_guild(int(guild_id))
            if target_g:
                emojis.extend(target_g.emojis)
        except Exception:
            pass

    if bot and hasattr(bot, 'emojis'):
        for e in bot.emojis:
            if e not in emojis:
                emojis.append(e)

    if not emojis:
        return text

    emoji_dict = {e.name.lower(): str(e) for e in emojis if getattr(e, 'available', True)}
    pattern = re.compile(r'(<a?:[a-zA-Z0-9_]+:\d+>)|:([a-zA-Z0-9_]+):')

    def repl(m):
        if m.group(1):
            return m.group(1)
        name = m.group(2).lower()
        if name in emoji_dict:
            return emoji_dict[name]
        return m.group(0)

    return pattern.sub(repl, text)


def resolve_single_emoji(emoji_str: str, bot=None, guild_id=None, guild=None):
    """
    Resolves an emoji string into a valid Discord emoji parameter:
    - If custom emoji string (<a?:name:id>), returns discord.PartialEmoji.from_str()
    - If :name: string, resolves from available emojis to discord.PartialEmoji
    - If unicode emoji (e.g. 💬, 🎁, 🛡️, 🔒), returns the unicode str
    - Returns None if empty or invalid
    """
    if not emoji_str:
        return None
    emoji_str = str(emoji_str).strip()
    if not emoji_str:
        return None

    # 1. Custom emoji syntax <a:name:id> or <:name:id>
    if re.match(r'^<a?:[a-zA-Z0-9_]+:[0-9]+>$', emoji_str):
        try:
            return discord.PartialEmoji.from_str(emoji_str)
        except Exception:
            return None

    # 2. Colon syntax :name:
    colon_match = re.match(r'^:([a-zA-Z0-9_]+):$', emoji_str)
    if colon_match:
        name = colon_match.group(1).lower()
        emojis = []
        if guild:
            emojis.extend(guild.emojis)
        elif guild_id and bot:
            try:
                g = bot.get_guild(int(guild_id))
                if g: emojis.extend(g.emojis)
            except Exception:
                pass
        if bot and hasattr(bot, 'emojis'):
            for e in bot.emojis:
                if e not in emojis: emojis.append(e)

        for e in emojis:
            if getattr(e, 'available', True) and e.name.lower() == name:
                return discord.PartialEmoji(name=e.name, id=e.id, animated=bool(e.animated))
        return None

    # 3. Unicode emoji
    return emoji_str


def parse_btn(text: str, bot=None, guild_id=None, guild=None):
    """
    Robustly parses button configuration text into (label, emoji).
    Handles:
    - '<a:dil_flyheart:1558131409028124872> General Support'
    - '💬 General Support:dil_flyheart:' (strips default unicode emoji, places custom emoji at front)
    - ':pkd_marooo: Giveaway Claim'
    - '💬 General Support'
    - 'General Support'
    Returns:
    (clean_label: str, emoji_obj: discord.PartialEmoji | str | None)
    """
    if not text:
        return "Support", None

    raw = str(text).strip()

    custom_match = re.search(r'(<a?:[a-zA-Z0-9_]+:[0-9]+>)', raw)
    colon_match = re.search(r':([a-zA-Z0-9_]+):', raw)

    emoji_raw = None
    cleaned = raw

    if custom_match:
        emoji_raw = custom_match.group(1)
        cleaned = cleaned.replace(emoji_raw, '').strip()
    elif colon_match:
        emoji_raw = f":{colon_match.group(1)}:"
        cleaned = cleaned.replace(emoji_raw, '').strip()

    # If a custom emoji was detected, strip any leftover leading/trailing standard unicode emojis
    if emoji_raw:
        cleaned = re.sub(r'^[^\w\s\d<:]{1,4}\s*', '', cleaned).strip()
        cleaned = re.sub(r'\s*[^\w\s\d<:]{1,4}$', '', cleaned).strip()
    else:
        # Check if text starts with a unicode emoji
        leading_unicode = re.search(r'^([^\w\s\d<:]{1,4})\s*', cleaned)
        if leading_unicode:
            emoji_raw = leading_unicode.group(1).strip()
            cleaned = cleaned[leading_unicode.end():].strip()
        else:
            # Check if text ends with a unicode emoji
            trailing_unicode = re.search(r'\s*([^\w\s\d<:]{1,4})$', cleaned)
            if trailing_unicode:
                emoji_raw = trailing_unicode.group(1).strip()
                cleaned = cleaned[:trailing_unicode.start()].strip()

    # Remove any leftover colons or orphan text
    cleaned = re.sub(r':([a-zA-Z0-9_]+):', '', cleaned).strip()
    label = cleaned if cleaned else "Support"

    # Resolve the raw emoji string into a discord PartialEmoji or unicode string
    resolved_emoji = resolve_single_emoji(emoji_raw, bot=bot, guild_id=guild_id, guild=guild)

    return label, resolved_emoji


def clean_embed_title(title: str) -> str:
    """
    Strips leading markdown heading indicators (#, ##, ###, -#) from embed titles
    since Discord's embed title field does not support markdown headers and displays
    the literal character instead. Also normalizes whitespace.
    """
    if not title:
        return ""
    cleaned = re.sub(r'^\s*(?:#+|-#)\s*', '', str(title)).strip()
    return cleaned


def normalize_discord_markdown(text: str) -> str:
    """
    Ensures markdown headings and subtext have a space after the symbol
    so Discord's client parses them as actual headers/subtext rather than literal text.
    E.g. '#Heading' -> '# Heading', '-#Subtext' -> '-# Subtext'.
    """
    if not text:
        return text
    lines = str(text).replace('\r\n', '\n').replace('\r', '\n').split('\n')
    out = []
    for line in lines:
        line = re.sub(r'^(#{1,3})([^\s#].*)$', r'\1 \2', line)
        line = re.sub(r'^(-#)([^\s].*)$', r'\1 \2', line)
        out.append(line)
    return '\n'.join(out)


def format_embed_description(desc: str, target_width: int = 50) -> str:
    """
    Formats embed description so long unbroken lines are cleanly wrapped at word boundaries,
    preventing Discord desktop client from stretching the embed awkwardly wide.
    Preserves markdown headers, quotes (╰, >), bullets, and indentation.
    """
    if not desc:
        return desc
    lines = str(desc).replace('\r\n', '\n').replace('\r', '\n').split('\n')
    formatted = []
    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) <= target_width or stripped.startswith('```'):
            formatted.append(line)
            continue

        prefix = ''
        m = re.match(r'^([╰>\-•*]\s*)', stripped)
        if m:
            prefix = m.group(1)
            stripped = stripped[len(prefix):].strip()

        words = stripped.split(' ')
        indent = '  ' if prefix else ''
        cur = prefix
        for w in words:
            if not w:
                continue
            test_line = (cur + ' ' + w) if (cur and cur.strip() and not cur.endswith(' ') and cur != indent) else (cur + w)
            if len(test_line) > target_width and cur.strip() != prefix.strip():
                formatted.append(cur)
                cur = indent + w
            else:
                cur = test_line
        if cur:
            formatted.append(cur)
    return '\n'.join(formatted)


