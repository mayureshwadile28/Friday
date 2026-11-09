import os
import unicodedata
from PIL import ImageFont

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fonts")
SEGUI_PATH = os.path.join(FONTS_DIR, "seguisym.ttf")

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

    # 4. Fallback to easy_pil / default
    try:
        from easy_pil import Font
        return Font.poppins(variant="bold" if bold else "regular", size=size)
    except Exception:
        return ImageFont.load_default()

def clean_display_name(name: str, max_len: int = 24) -> str:
    """
    Sanitizes names while preserving decorative symbols (e.g. ⊱❀⊰ ♡),
    Asian/CJK characters, and foreign alphabets without stripping them.
    """
    if not name:
        return "Unknown"
    cleaned = "".join(ch for ch in str(name) if unicodedata.category(ch)[0] != 'C' and ch not in "`\\")
    cleaned = cleaned.strip()
    return cleaned[:max_len] if cleaned else "User"

def safe_channel_label(raw_name: str, cid: str = None, max_len: int = 18) -> str:
    """
    Sanitizes channel names into clean printable text while preserving
    decorative symbols and letters without turning into raw IDs or tofu.
    """
    if not raw_name:
        return "deleted-channel" if cid else "channel"
    cleaned = "".join(ch for ch in str(raw_name) if unicodedata.category(ch)[0] != 'C' and ch not in "`*~_<>|\\")
    cleaned = cleaned.strip(" -_#|•·~+=[]{}()<>/")
    if cleaned and len(cleaned) >= 1:
        return cleaned[:max_len]
    return "deleted-channel" if cid else "channel"
