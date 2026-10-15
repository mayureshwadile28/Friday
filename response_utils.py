import discord
import re
import datetime

# Clean minimalist geometric / monochrome status symbols
STATUS_SYMBOLS = {
    "success": "✓",
    "error": "✕",
    "warning": "▲",
    "info": "◈",
    "security": "⬡",
    "audio": "♫",
    "neutral": "•"
}

# Modern Discord palette
STATUS_COLORS = {
    "success": discord.Color.from_rgb(16, 185, 129),   # Emerald 500
    "error": discord.Color.from_rgb(239, 68, 68),      # Crimson 500
    "warning": discord.Color.from_rgb(245, 158, 11),   # Amber 500
    "info": discord.Color.from_rgb(99, 102, 241),      # Indigo / Blurple 500
    "security": discord.Color.from_rgb(139, 92, 246),  # Violet 500
    "audio": discord.Color.from_rgb(168, 85, 247),     # Purple 500
    "neutral": discord.Color.from_rgb(43, 45, 49)      # Sleek Dark Slate
}

# Regex to strip cartoon standard emojis
LEGACY_EMOJIS_PATTERN = re.compile(
    r'[\U0001f300-\U0001f5ff\U0001f600-\U0001f64f\U0001f680-\U0001f6ff\U0001f700-\U0001f77f'
    r'\U0001f780-\U0001f7ff\U0001f800-\U0001f8ff\U0001f900-\U0001f9ff\U0001fa00-\U0001fa6f'
    r'\U0001fa70-\U0001faff\U00002702-\U000027b0\U000024c2-\U0001f251\U00002600-\U000026ff]+'
)

def strip_legacy_emojis(text: str) -> str:
    """Removes standard cartoon unicode emojis to maintain a clean, monochrome aesthetic."""
    if not text:
        return ""
    # Preserve custom discord emojis <:name:id> and <a:name:id>
    parts = []
    last_end = 0
    for match in re.finditer(r'<a?:[a-zA-Z0-9_]+:[0-9]+>', text):
        pre = text[last_end:match.start()]
        cleaned_pre = LEGACY_EMOJIS_PATTERN.sub('', pre)
        parts.append(cleaned_pre)
        parts.append(match.group(0))
        last_end = match.end()
    rest = text[last_end:]
    parts.append(LEGACY_EMOJIS_PATTERN.sub('', rest))
    cleaned = "".join(parts)
    # Clean up excess spaces or dangling prefixes
    cleaned = re.sub(r'^[ \t\r\f\v:\-–—\.]+', '', cleaned)
    return cleaned.strip()

def make_box_embed(
    title: str = None,
    description: str = "",
    status: str = "info",
    footer: str = "Friday",
    fields: list = None
) -> discord.Embed:
    """
    Constructs a sleek, modern box-formatted Discord Embed card
    using clean monochrome symbols and rich Discord styling.
    """
    color = STATUS_COLORS.get(status.lower(), STATUS_COLORS["info"])
    symbol = STATUS_SYMBOLS.get(status.lower(), "◈")
    
    clean_desc = strip_legacy_emojis(description) if description else ""
    
    # Format Title with clean geometric symbol
    full_title = None
    if title:
        clean_title = strip_legacy_emojis(title)
        full_title = f"{symbol}  {clean_title}"
    elif status == "error":
        full_title = f"{symbol}  Action Failed"
    elif status == "success":
        full_title = f"{symbol}  Action Executed"
    elif status == "warning":
        full_title = f"{symbol}  Notice"
        
    embed = discord.Embed(
        title=full_title,
        description=clean_desc,
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    
    if fields:
        for f in fields:
            name = f.get("name", "")
            val = f.get("value", "")
            inline = f.get("inline", False)
            embed.add_field(name=strip_legacy_emojis(name), value=strip_legacy_emojis(val), inline=inline)
            
    if footer:
        embed.set_footer(text=footer)
    return embed

async def reply_box(
    interaction: discord.Interaction,
    description: str,
    title: str = None,
    status: str = "info",
    ephemeral: bool = False,
    view: discord.ui.View = None,
    fields: list = None
):
    """
    Unified helper to respond to Discord interactions with a polished Box Embed.
    Seamlessly handles deferred, completed, and initial interaction states.
    """
    embed = make_box_embed(title=title, description=description, status=status, fields=fields)
    
    try:
        if not interaction.response.is_done():
            if view:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        else:
            if view:
                await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral)
            else:
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)
    except Exception as e:
        print(f"[reply_box Error] {e}")
