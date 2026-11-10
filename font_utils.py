import os
import struct
import unicodedata
from PIL import ImageFont

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fonts")
SEGUI_PATH = os.path.join(FONTS_DIR, "seguisym.ttf")

# Punctuation / symbol replacements for characters not in Segoe UI Symbol
PUNCT_MAP = {
    0x30fb: '•',  # Katakana middle dot (・) -> bullet (•)
    0xff61: '.',  # Halfwidth ideographic full stop (｡) -> dot (.)
    0x3002: '.',  # Ideographic full stop (。) -> dot (.)
    0x301c: '~',  # Wave dash (〜) -> tilde (~)
    0xff5e: '~',  # Fullwidth tilde (～) -> tilde (~)
    0x2027: '•',  # Hyphenation point (‧) -> bullet (•)
    0x2219: '•',  # Bullet operator (∙) -> bullet (•)
    0x3001: ',',  # Ideographic comma (、) -> comma (,)
    0xff0c: ',',  # Fullwidth comma (，) -> comma (,)
    0x300c: '"',  # Corner bracket (「) -> quote (")
    0x300d: '"',  # Corner bracket (」) -> quote (")
    0x300e: '"',  # White corner bracket (『) -> quote (")
    0x300f: '"',  # White corner bracket (』) -> quote (")
}

# Homoglyph & aesthetic script transliteration mapping
# Converts Cyrillic, Greek, Small Caps, Cherokee, and mathematical styles to clean ASCII
HOMOGLYPH_MAP = {
    # Cyrillic lowercase homoglyphs
    0x0430: 'a', 0x0431: 'b', 0x0432: 'v', 0x0433: 'g', 0x0434: 'd', 0x0435: 'e', 0x0451: 'e',
    0x0436: 'zh', 0x0437: 'z', 0x0438: 'i', 0x0439: 'y', 0x043a: 'k', 0x043b: 'l', 0x043c: 'm',
    0x043d: 'n', 0x043e: 'o', 0x043f: 'p', 0x0440: 'r', 0x0441: 's', 0x0442: 't', 0x0443: 'u',
    0x0444: 'f', 0x0445: 'h', 0x0446: 'ts', 0x0447: 'ch', 0x0448: 'sh', 0x0449: 'sh',
    0x044a: '', 0x044b: 'y', 0x044c: '', 0x044d: 'e', 0x044e: 'yu', 0x044f: 'ya',
    0x0461: 'w',  # Cyrillic omega (common in owo Discord channel names)
    0x0475: 'v',  # Cyrillic izhitsa
    # Cyrillic uppercase homoglyphs
    0x0410: 'A', 0x0411: 'B', 0x0412: 'V', 0x0413: 'G', 0x0414: 'D', 0x0415: 'E', 0x0401: 'E',
    0x041a: 'K', 0x041c: 'M', 0x041d: 'H', 0x041e: 'O', 0x0420: 'P', 0x0421: 'C', 0x0422: 'T',
    0x0423: 'Y', 0x0425: 'X',
    # Greek lowercase homoglyphs
    0x03b1: 'a', 0x03b2: 'b', 0x03b3: 'g', 0x03b4: 'd', 0x03b5: 'e', 0x03b6: 'z', 0x03b7: 'h',
    0x03b8: 'th', 0x03b9: 'i', 0x03ba: 'k', 0x03bb: 'l', 0x03bc: 'm', 0x03bd: 'n', 0x03be: 'x',
    0x03bf: 'o', 0x03c0: 'p', 0x03c1: 'r', 0x03c2: 's', 0x03c3: 's', 0x03c4: 't', 0x03c5: 'u',
    0x03c6: 'ph', 0x03c7: 'ch', 0x03c8: 'ps', 0x03c9: 'w',  # Greek omega
    # Small Caps
    0x1d00: 'A', 0x1d01: 'B', 0x1d04: 'C', 0x1d05: 'D', 0x1d07: 'E', 0x1d0a: 'J', 0x1d0b: 'K',
    0x1d0c: 'L', 0x1d0d: 'M', 0x1d0e: 'N', 0x1d0f: 'o', 0x1d18: 'P', 0x1d19: 'R', 0x1d1b: 'T',
    0x1d1c: 'u', 0x1d20: 'v', 0x1d21: 'w', 0x1d22: 'z',
    # Mathematical / Script styles
    0x1d4b1: 'V', 0x1d4cb: 'v', 0x1d4c1: 'l', 0x1d4c4: 'O', 0x1d4cc: 'w', 0x2134: 'o',
    0x1d45c: 'o', 0x1d464: 'w', 0x1d4f8: 'o', 0x1d500: 'w',
    # Cherokee & Phonetic
    0x13a0: 'D', 0x13a1: 'R', 0x13a2: 'T', 0x13aa: 'A', 0x13ab: 'M', 0x13ac: 'H', 0x13b3: 'W', 0x13b4: 'o',
    0x1d52: 'o', 0x02b7: 'w',
    # Aesthetic flourishes / symbols
    0x1f300: '🌀', 0x1f365: '🍥', 0x22c6: '⋆', 0x02da: '˚', 0xff61: '.', 0x2605: '★', 0x2728: '✨'
}

_SUPPORTED_CMAP = None

def get_ttf_cmap(font_path: str) -> set:
    """Extracts all supported unicode codepoints directly from TTF cmap table in pure Python."""
    if not os.path.exists(font_path):
        return set()
    try:
        with open(font_path, 'rb') as f:
            data = f.read()
        num_tables = struct.unpack('>H', data[4:6])[0]
        cmap_offset = None
        for i in range(num_tables):
            entry = data[12 + i*16 : 12 + (i+1)*16]
            if entry[0:4] == b'cmap':
                cmap_offset = struct.unpack('>I', entry[8:12])[0]
                break
        if not cmap_offset:
            return set()
        num_subtables = struct.unpack('>H', data[cmap_offset+2:cmap_offset+4])[0]
        supported = set()
        for i in range(num_subtables):
            sub_record = data[cmap_offset + 4 + i*8 : cmap_offset + 4 + (i+1)*8]
            platform_id, enc_id, sub_offset = struct.unpack('>HHI', sub_record)
            table_start = cmap_offset + sub_offset
            format_num = struct.unpack('>H', data[table_start:table_start+2])[0]
            if format_num == 4:
                seg_count_x2 = struct.unpack('>H', data[table_start+6:table_start+8])[0]
                seg_count = seg_count_x2 // 2
                end_codes = struct.unpack(f'>{seg_count}H', data[table_start+14:table_start+14+seg_count*2])
                start_codes = struct.unpack(f'>{seg_count}H', data[table_start+16+seg_count*2:table_start+16+seg_count*4])
                for s, e in zip(start_codes, end_codes):
                    if s != 0xFFFF:
                        for cp in range(s, e + 1):
                            supported.add(cp)
            elif format_num == 12:
                num_groups = struct.unpack('>I', data[table_start+12:table_start+16])[0]
                pos = table_start + 16
                for _ in range(num_groups):
                    start_char, end_char, _ = struct.unpack('>III', data[pos:pos+12])
                    for cp in range(start_char, end_char + 1):
                        supported.add(cp)
                    pos += 12
        return supported
    except Exception:
        return set()

def get_supported_codepoints() -> set:
    global _SUPPORTED_CMAP
    if _SUPPORTED_CMAP is None:
        _SUPPORTED_CMAP = get_ttf_cmap(SEGUI_PATH)
    return _SUPPORTED_CMAP

def sanitize_for_font(text: str) -> str:
    """
    Sanitizes string against the font's actual glyph cmap.
    Replaces homoglyphs (Cyrillic, Greek, Small Caps, Stylized Latin) with standard ASCII equivalents,
    maps known unicode punctuation to clean equivalents, and filters out rare unmapped script glyphs
    so FreeType NEVER renders tofu boxes while ensuring channel words (like 'owo') are NEVER lost.
    """
    if not text:
        return ""

    # 1. First transliterate known stylized homoglyphs and punctuation
    trans_chars = []
    for ch in str(text):
        o = ord(ch)
        if o in HOMOGLYPH_MAP:
            trans_chars.append(HOMOGLYPH_MAP[o])
        elif o in PUNCT_MAP:
            trans_chars.append(PUNCT_MAP[o])
        else:
            trans_chars.append(ch)
    trans_text = "".join(trans_chars)

    cmap = get_supported_codepoints()
    if not cmap:
        return trans_text

    out = []
    for ch in trans_text:
        o = ord(ch)
        if o in cmap:
            out.append(ch)
            continue
        # Try NFKD decomposition (e.g. mathematical bold/script -> standard letters)
        decomp = unicodedata.normalize('NFKD', ch)
        if decomp and decomp != ch:
            for d in decomp:
                if ord(d) in cmap:
                    out.append(d)
                elif ord(d) in HOMOGLYPH_MAP:
                    mapped = HOMOGLYPH_MAP[ord(d)]
                    for m in mapped:
                        if ord(m) in cmap:
                            out.append(m)
        # Skip unsupported characters to prevent .notdef tofu box
    return "".join(out)

def get_unicode_font(size: int, bold: bool = False):
    """
    Returns a TrueType font capable of rendering Unicode symbols,
    florets (❀), decorative arrows (⊱ ⊰), hearts (♡), and foreign glyphs.
    """
    # 1. Bundled universal symbol font (Segoe UI Symbol)
    if os.path.exists(SEGUI_PATH):
        try:
            return ImageFont.truetype(SEGUI_PATH, size)
        except Exception:
            pass

    # 2. Linux / Ubuntu system fonts
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
    ]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass

    # 3. Windows system fonts
    for p in [
        "C:/Windows/Fonts/seguisym.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf"
    ]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass

    # 4. Fallback to default
    return ImageFont.load_default()

def clean_display_name(name: str, max_len: int = 24) -> str:
    """
    Sanitizes names while preserving decorative symbols (e.g. ⊱❀⊰ ♡),
    Asian/CJK characters, and foreign alphabets without stripping them or causing tofu.
    """
    if not name:
        return "Unknown"
    cleaned = sanitize_for_font(name)
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch)[0] != 'C' and ch not in "`\\")
    cleaned = cleaned.strip()
    return cleaned[:max_len] if cleaned else "User"

def safe_channel_label(raw_name: str, cid: str = None, max_len: int = 18) -> str:
    """
    Sanitizes channel names into clean printable text while preserving
    decorative symbols and letters without turning into raw IDs or tofu.
    Guarantees alphanumeric names (e.g. 'owo') are always preserved even if
    stylized symbols surrounding them cannot be rendered.
    """
    if not raw_name:
        return "deleted-channel" if cid else "channel"
    cleaned = sanitize_for_font(raw_name)
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch)[0] != 'C' and ch not in "`~_<>|\\")
    cleaned = cleaned.strip(" -_#|•·~+=[]{}()<>/")

    # If sanitization left no alphanumeric characters but the raw name had them, recover ASCII/transliterated words
    if not any(c.isalnum() for c in cleaned):
        trans = "".join(HOMOGLYPH_MAP.get(ord(c), c) for c in raw_name)
        recovered = "".join(c for c in trans if c.isalnum() or c in " -_#")
        recovered = recovered.strip(" -_#")
        if recovered:
            cleaned = f"{recovered} {cleaned}".strip() if cleaned else recovered

    if cleaned and len(cleaned) >= 1:
        return cleaned[:max_len]
    return "deleted-channel" if cid else "channel"
