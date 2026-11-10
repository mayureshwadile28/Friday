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
    Replaces known Asian/unicode punctuation with clean equivalents and filters out
    rare unmapped script glyphs (like Balinese flourishes) so FreeType NEVER renders tofu boxes.
    """
    if not text:
        return ""
    cmap = get_supported_codepoints()
    if not cmap:
        return str(text)

    out = []
    for ch in str(text):
        o = ord(ch)
        if o in PUNCT_MAP:
            out.append(PUNCT_MAP[o])
            continue
        if o in cmap:
            out.append(ch)
            continue
        # Try NFKD decomposition (e.g. mathematical bold/script -> standard letters)
        decomp = unicodedata.normalize('NFKD', ch)
        if decomp and decomp != ch:
            for d in decomp:
                if ord(d) in cmap:
                    out.append(d)
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
    """
    if not raw_name:
        return "deleted-channel" if cid else "channel"
    cleaned = sanitize_for_font(raw_name)
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch)[0] != 'C' and ch not in "`*~_<>|\\")
    cleaned = cleaned.strip(" -_#|•·~+=[]{}()<>/")
    if cleaned and len(cleaned) >= 1:
        return cleaned[:max_len]
    return "deleted-channel" if cid else "channel"
