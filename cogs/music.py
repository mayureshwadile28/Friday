import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import yt_dlp
import urllib.request
import urllib.parse
import json
import os
import io
import time
import random
import re
import html
import base64
import colorsys
import warnings
import aiohttp
from typing import Optional, Tuple, List, Dict, Any
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageStat
from database import db
from font_utils import get_unicode_font, clean_display_name
from response_utils import make_box_embed, reply_box

# ─────────────────────────────────────────────────────────────
# Intelligent Autoplay Feature & Mood Classifiers
# ─────────────────────────────────────────────────────────────
AUTOPLAY_MOOD_PATTERNS = {
    "sad": re.compile(r'\b(sad|dard|judai|heartbreak|broken|crying|pain|alone|lonely|emotional|tears|channa mereya|agar tum|adhuri|bekhayali|tum hi ho|let her go|someone like you|all too well|traitor|arcade|drivers license|melancholy|acoustic|duriya|khairiyat)\b', re.IGNORECASE),
    "lofi": re.compile(r'\b(lofi|lo-fi|chill|relax|ambient|sleep|study|aesthetic|slowed|reverb|synthwave|cozy|peaceful|midnight)\b', re.IGNORECASE),
    "romantic": re.compile(r'\b(love|romantic|pyaar|ishq|mohabbat|sanware|humsafar|perfect|golden hour|lover|dandelions|until i found you|pehle bhi main|tum mile|kasam|raataan lambiyan|kesariya)\b', re.IGNORECASE),
    "party": re.compile(r'\b(party|dance|nacho|bhangra|remix|club|club mix|beats|drop|celebration|disco|edm|bass boosted|shaky|tauba tauba)\b', re.IGNORECASE),
    "phonk": re.compile(r'\b(phonk|drift|brazilian phonk|gigachad|workout|gym|rage|montage|speed up|kordhell|dvrst|smoke)\b', re.IGNORECASE),
    "rap": re.compile(r'\b(rap|hip hop|drill|diss|cypher|freestyle|trap|boombap|raftaar|emiway|krishna|mc stan|seedhe maut|krsna)\b', re.IGNORECASE),
    "devotional": re.compile(r'\b(bhajan|aarti|mantra|shree ram|krishna|shiva|hanuman|devotional|chalisa|ram siye ram)\b', re.IGNORECASE)
}

# Native script regular expressions for 100% accurate language detection
HINDI_SCRIPT_RE = re.compile(r'[\u0900-\u097F]')
PUNJABI_SCRIPT_RE = re.compile(r'[\u0A00-\u0A7F]')
KOREAN_SCRIPT_RE = re.compile(r'[\uAC00-\uD7AF]')
JAPANESE_SCRIPT_RE = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]')

KPOP_ARTISTS_RE = re.compile(
    r'\b(bts|blackpink|twice|stray kids|newjeans|txt|enhypen|seventeen|aespa|le sserafim|exo|red velvet|itzy|ateez|kpop|k-pop)\b',
    re.IGNORECASE
)

JAPANESE_ARTISTS_RE = re.compile(
    r'\b(yoasobi|lisa|ado|kenshi yonezu|anime|jpop|j-pop|vocaloid|radwimps|aimer|milet|eve|official hige dandism)\b',
    re.IGNORECASE
)

PUNJABI_ARTISTS_RE = re.compile(
    r'\b(sidhu moose wala|sidhu moosewala|moose wala|moosewala|karan aujla|shubh|diljit dosanjh|diljit|'
    r'ap dhillon|gurinder gill|amrit maan|b praak|jaani|harrdy sandhu|hardy sandhu|jassi gill|'
    r'chani nattan|arjan dhillon|prem dhillon|jordan sandhu|mankirt aulakh)\b',
    re.IGNORECASE
)

INDIAN_ARTISTS_RE = re.compile(
    r'\b(arijit singh|arijit|atif aslam|atif|shreya ghoshal|shreya|jubin nautiyal|jubin|'
    r'sonu nigam|neha kakkar|darshan raval|vishal mishra|pritam|armaan malik|anuv jain|'
    r'prateek kuhad|b praak|jasleen royal|sachin-jigar|sachin jigar|amit trivedi|'
    r'a\.?r\.?\s*rahman|alka yagnik|kumar sanu|udit narayan|kishore kumar|lata mangeshkar|'
    r'mohammed rafi|badshah|honey singh|yo yo honey singh|guru randhawa|'
    r'ayushmann khurrana|lucky ali|papon|asees kaur|goldie sohel|tulsi kumar|dhvani bhanushali|'
    r'palak muchhal|shilpa rao|monali thakur|neeti mohan|sunidhi chauhan|mohit chauhan|'
    r'tanishk bagchi|mithoon|ankit tiwari|akhil sachdeva|stebin ben)\b',
    re.IGNORECASE
)

INDIAN_LABELS_KEYWORDS_RE = re.compile(
    r'\b(bollywood|t-series|tseries|zee music|zeemusic|yrf|speed records|desi music factory|'
    r'geetmp3|white hill|bhangra|sufi|ghazal|qawwali|coke studio|desi)\b',
    re.IGNORECASE
)

HINDI_ROMAN_WORDS_RE = re.compile(
    r'\b(dil|pyaar|pyar|ishq|mohabbat|muhabbat|tere|teri|tera|tujhe|tujhko|tujhse|'
    r'meri|mera|mere|mujhe|mujhko|mujhse|tum|hum|humko|humein|humse|tumko|tumhe|tumhein|tumse|'
    r'apna|apni|apne|zindagi|rabba|rab|khuda|maula|dhol|chitta|nach|kudi|yaar|duniya|jahaan|'
    r'raataan|raat|raatein|raaten|raatan|intezaar|sajna|dhadkan|aashiqui|ashiqui|bewafa|deewana|dewana|deewani|'
    r'banale|chaleya|kesariya|akhiyaan|akhiyan|naina|naino|nazar|lagi|khairiyat|shayari|shayar|'
    r'gaana|geet|hona|hoga|hogi|honge|hota|hoti|hote|suno|kaho|jaane|jana|sath|saath|tu hi|tum hi|mere bina|'
    r'jeena|marjaani|khwab|sapne|sapna|yaad|yaadein|rooh|sukoon|suroor|chahoon|chahun|chahu|chahunga|chahungi|'
    r'phir|bhi|bhee|kya|kyun|kyu|kaise|kaisa|kaisi|kabhi|kisi|raha|rahi|rahe|gaya|gayi|gaye|aaya|aayi|aaye|'
    r'baat|baatein|ankhein|aankhon|lab|saans|saansen|saansein|pal|din|subah|shaam|haseen|khamosh|khamoshi|'
    r'alvida|kahani|afsaana|gham|gam|dard|tasveer|ibadat|dua|sitam|karam|reham|wafa|wafaa|mulaqat|safar|'
    r'manzil|raasta|rasta|musafir|awara|shiddat|kasam|vaada|wada|channa|mereya|hawayein|baarish|muskurane|'
    r'kamleya|satranga|heeriye|kasoor|baarishein|lehanga|yeh|woh|mausam|barsaat)\b',
    re.IGNORECASE
)

PUNJABI_ROMAN_WORDS_RE = re.compile(
    r'\b(punjabi|jatt|munda|kudi|gabru|pind|soorma|gediyan|veham|mittran|yaar|chitta|soch)\b',
    re.IGNORECASE
)

KNOWN_BOLLYWOOD_ARTISTS = [
    "Arijit Singh", "Atif Aslam", "Shreya Ghoshal", "KK", "Mohit Chauhan",
    "Sonu Nigam", "Jubin Nautiyal", "Darshan Raval", "Vishal Mishra",
    "Armaan Malik", "Anuv Jain", "Prateek Kuhad", "B Praak", "Jasleen Royal",
    "Sachin-Jigar", "Shankar Ehsaan Loy", "Amit Trivedi", "A.R. Rahman",
    "Alka Yagnik", "Kumar Sanu", "Udit Narayan", "Kishore Kumar", "Lata Mangeshkar",
    "Mohammed Rafi", "Diljit Dosanjh", "AP Dhillon", "Sidhu Moosewala",
    "Karan Aujla", "Shubh", "Badshah", "Yo Yo Honey Singh", "Neha Kakkar",
    "Sunidhi Chauhan", "Pritam", "Tanishk Bagchi", "Mithoon", "Ankit Tiwari",
    "Akhil Sachdeva", "Stebin Ben", "King", "Guru Randhawa", "Hardy Sandhu",
    "Ayushmann Khurrana", "Lucky Ali", "Shaan", "Javed Ali", "Papon",
    "Asees Kaur", "Goldie Sohel", "Tulsi Kumar", "Dhvani Bhanushali", "Palak Muchhal",
    "Shilpa Rao", "Monali Thakur", "Neeti Mohan", "Prakriti Kakar", "Sukriti Kakar",
    "Jonita Gandhi", "Parampara Tandon", "Sachet Tandon", "Abhay Jodhpurkar",
    "Raghav Chaitanya", "Zack Knight", "Kailash Kher", "Himesh Reshammiya",
    "Meet Bros", "Vishal-Shekhar", "Manan Bhardwaj", "Adnan Sami"
]


# Pure-Python zero-dependency DES tables for JioSaavn CDN URL decryption
_DES_IP = [
    58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4,
    62, 54, 46, 38, 30, 22, 14, 6, 64, 56, 48, 40, 32, 24, 16, 8,
    57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3,
    61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7
]
_DES_FP = [
    40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31,
    38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29,
    36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27,
    34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25
]
_DES_E = [
    32, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9,
    8, 9, 10, 11, 12, 13, 12, 13, 14, 15, 16, 17,
    16, 17, 18, 19, 20, 21, 20, 21, 22, 23, 24, 25,
    24, 25, 26, 27, 28, 29, 28, 29, 30, 31, 32, 1
]
_DES_P = [
    16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10,
    2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25
]
_DES_S = [
    [
        14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7,
        0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8,
        4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0,
        15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13
    ],
    [
        15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10,
        3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5,
        0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15,
        13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9
    ],
    [
        10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8,
        13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1,
        13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7,
        1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12
    ],
    [
        7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15,
        13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9,
        10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4,
        3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14
    ],
    [
        2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9,
        14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6,
        4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14,
        11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3
    ],
    [
        12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11,
        10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8,
        9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6,
        4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13
    ],
    [
        4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1,
        13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6,
        1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2,
        6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12
    ],
    [
        13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7,
        1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2,
        7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8,
        2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11
    ]
]
_DES_PC1 = [
    57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18,
    10, 2, 59, 51, 43, 35, 27, 19, 11, 3, 60, 52, 44, 36,
    63, 55, 47, 39, 31, 23, 15, 7, 62, 54, 46, 38, 30, 22,
    14, 6, 61, 53, 45, 37, 29, 21, 13, 5, 28, 20, 12, 4
]
_DES_PC2 = [
    14, 17, 11, 24, 1, 5, 3, 28, 15, 6, 21, 10,
    23, 19, 12, 4, 26, 8, 16, 7, 27, 20, 13, 2,
    41, 52, 31, 37, 47, 55, 30, 40, 51, 45, 33, 48,
    44, 49, 39, 56, 34, 53, 46, 42, 50, 36, 29, 32
]
_DES_SHIFTS = [1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1]

def _des_permute(block, table):
    return [block[x - 1] for x in table]

def _des_bytes_to_bits(data):
    bits = []
    for b in data:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    return bits

def _des_bits_to_bytes(bits):
    b = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for bit in bits[i:i+8]:
            byte = (byte << 1) | bit
        b.append(byte)
    return bytes(b)

def _des_key_schedule(key_bytes):
    bits = _des_bytes_to_bits(key_bytes)
    perm = _des_permute(bits, _DES_PC1)
    C = perm[:28]
    D = perm[28:]
    subkeys = []
    for s in _DES_SHIFTS:
        C = C[s:] + C[:s]
        D = D[s:] + D[:s]
        subkeys.append(_des_permute(C + D, _DES_PC2))
    return subkeys

def _des_block_decrypt(block_bytes, subkeys):
    bits = _des_permute(_des_bytes_to_bits(block_bytes), _DES_IP)
    L, R = bits[:32], bits[32:]
    for K in reversed(subkeys):
        ER = _des_permute(R, _DES_E)
        xor_res = [a ^ b for a, b in zip(ER, K)]
        sbox_out = []
        for i in range(8):
            chunk = xor_res[i*6:(i+1)*6]
            row = (chunk[0] << 1) | chunk[5]
            col = (chunk[1] << 3) | (chunk[2] << 2) | (chunk[3] << 1) | chunk[4]
            val = _DES_S[i][row * 16 + col]
            for bit_pos in (3, 2, 1, 0):
                sbox_out.append((val >> bit_pos) & 1)
        f_res = _des_permute(sbox_out, _DES_P)
        L, R = R, [a ^ b for a, b in zip(L, f_res)]
    return _des_bits_to_bytes(_des_permute(R + L, _DES_FP))

def decrypt_saavn_url(encrypted_url: str) -> str:
    """Zero-dependency pure-Python DES-ECB decryptor for JioSaavn 320kbps Akamai CDN streaming URLs."""
    try:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            key = b"38346591" * 3
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cipher = Cipher(algorithms.TripleDES(key), modes.ECB())
                decryptor = cipher.decryptor()
                raw = decryptor.update(base64.b64decode(encrypted_url)) + decryptor.finalize()
            pad = raw[-1]
            decrypted = raw[:-pad].decode('utf-8')
            return decrypted.replace('_96.mp4', '_320.mp4').replace('_160.mp4', '_320.mp4')
        except ImportError:
            pass

        data = base64.b64decode(encrypted_url.strip())
        subkeys = _des_key_schedule(b"38346591")
        decrypted = bytearray()
        for i in range(0, len(data), 8):
            block = data[i:i+8]
            decrypted.extend(_des_block_decrypt(block, subkeys))
        pad = decrypted[-1]
        if pad < 8:
            decrypted = decrypted[:-pad]
        url = decrypted.decode('utf-8')
        return url.replace('_96.mp4', '_320.mp4').replace('_160.mp4', '_320.mp4')
    except Exception as e:
        print(f"[Music] Saavn decrypt error: {e}")
        return None


def get_cookie_file():
    """Dynamically locate cookies.txt in bot root, cogs directory, or working directory."""
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookies.txt"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt"),
        os.path.join(os.getcwd(), "cookies.txt")
    ]
    for c in candidates:
        if os.path.isfile(c) and os.path.getsize(c) > 0:
            return c
    return None

COOKIE_FILE = get_cookie_file()
HAS_COOKIES = bool(COOKIE_FILE)

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Sec-Fetch-Mode': 'navigate',
}

YDL_OPTIONS = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best/18/140',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch1',
    'geo_bypass': True,
    'nocheckcertificate': True,
    'http_headers': DEFAULT_HEADERS,
}

def resolve_spotify_url(url: str) -> Optional[dict]:
    """Robust zero-dependency Spotify resolver for tracks, albums, playlists, and shortlinks."""
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = f"https://{clean_url}"

    if "spotify.link" in clean_url or "spoti.fi" in clean_url:
        try:
            req = urllib.request.Request(clean_url, headers=DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                clean_url = resp.geturl()
        except Exception as e:
            print(f"[Music] Spotify shortlink expansion error: {e}")

    m = re.search(r'spotify\.com/(?:intl-[a-z]+/)?(track|playlist|album)/([a-zA-Z0-9]+)', clean_url)
    if not m:
        return None

    item_type, item_id = m.group(1), m.group(2)
    embed_url = f"https://open.spotify.com/embed/{item_type}/{item_id}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9'
    }

    try:
        req = urllib.request.Request(embed_url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as r:
            content = r.read().decode('utf-8', errors='ignore')
            nd = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', content)
            if nd:
                data = json.loads(nd.group(1))
                pp = data.get('props', {}).get('pageProps', {})
                state = pp.get('state', {}).get('data', {}).get('entity', {})

                if item_type == 'track':
                    title = state.get('name') or pp.get('title')
                    artists = [a.get('name') for a in state.get('artists', []) if a.get('name')]
                    artist_str = " ".join(artists) if artists else ""
                    if title and artist_str and artist_str.lower() not in title.lower():
                        search_query = f"{title} {artist_str}".strip()
                    else:
                        search_query = (title or "").strip()
                    return {
                        'type': 'track',
                        'title': title,
                        'artist': artist_str,
                        'search_query': search_query
                    }
                elif item_type in ('playlist', 'album'):
                    container_title = state.get('name') or pp.get('title') or f"Spotify {item_type.title()}"
                    track_list = state.get('trackList', [])
                    resolved_tracks = []
                    for t in track_list:
                        t_name = t.get('title')
                        if not t_name:
                            continue
                        sub = t.get('subtitle', '')
                        q = f"{t_name} {sub}".strip() if (sub and sub.lower() not in t_name.lower()) else t_name
                        resolved_tracks.append({
                            'title': t_name,
                            'artist': sub,
                            'search_query': q,
                            'duration': t.get('duration', 0) // 1000 if t.get('duration') else 0
                        })
                    return {
                        'type': item_type,
                        'title': container_title,
                        'tracks': resolved_tracks
                    }
    except Exception as e:
        print(f"[Music] Spotify embed scraping note: {e}")

    try:
        clean_target = clean_url.split('?')[0]
        oe = f"https://open.spotify.com/oembed?url={urllib.parse.quote(clean_target)}"
        req = urllib.request.Request(oe, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = json.loads(r.read().decode())
            title = raw.get('title', '')
            if title:
                return {
                    'type': item_type,
                    'title': title,
                    'artist': '',
                    'search_query': title
                }
    except Exception as oe_e:
        print(f"[Music] Spotify oEmbed fallback error: {oe_e}")

    return None


# Studio Audiophile DSP & Equalization Profiles (Pure Studio Master Engine)
AUDIO_FILTERS = {
    "studio": {
        "name": "Studio Master (Pure 48kHz High-Fidelity)",
        "emoji": "🎧",
        "description": "Pristine uncompressed 48kHz audio with transparent dynamic range",
        "af": "aresample=48000:resampler=soxr"
    },
    "bassboost": {
        "name": "Bass Boost",
        "emoji": "🔊",
        "description": "Deep sub-bass punch for EDM, Phonk, and Hip-Hop",
        "af": "equalizer=f=60:width_type=h:width=60:g=4,equalizer=f=120:width_type=h:width=80:g=2.5,aresample=48000"
    },
    "vocal": {
        "name": "Vocal / Acoustic",
        "emoji": "🎙️",
        "description": "Enhanced vocal presence and instrument clarity",
        "af": "equalizer=f=3000:width_type=o:width=2.0:g=2.0,aresample=48000"
    },
    "nightcore": {
        "name": "Nightcore",
        "emoji": "🌙",
        "description": "High-energy speedup (1.25x tempo + higher pitch)",
        "af": "asetrate=48000*1.25,aresample=48000"
    },
    "lofi": {
        "name": "Lo-Fi / Warm Chill",
        "emoji": "☕",
        "description": "Warm vintage analog low-pass filter",
        "af": "lowpass=f=3200,equalizer=f=100:width_type=o:width=1.0:g=2.5"
    },
    "treble": {
        "name": "Treble Boost",
        "emoji": "⚡",
        "description": "Crisp high-frequency clarity and vocal sparkle",
        "af": "equalizer=f=8000:width_type=h:width=1000:g=5,equalizer=f=14000:width_type=h:width=2000:g=4,alimiter=limit=0.98:attack=5:release=50"
    },
    "8d": {
        "name": "8D Surround",
        "emoji": "🌐",
        "description": "Rotating spatial binaural 8D surround sound",
        "af": "apulsator=hz=0.125:amount=1"
    },
    "flat": {
        "name": "Flat / Pure Raw",
        "emoji": "🎚️",
        "description": "Untouched original source stream",
        "af": ""
    }
}
EQ_CYCLE = ["studio", "bassboost", "vocal", "nightcore", "lofi", "treble", "8d", "flat"]

def get_ffmpeg_options(filter_key="studio", seek_seconds=0):
    """Builds optimized FFmpeg options with zero-stutter buffer, audio filters, and seek position."""
    before_parts = []
    if seek_seconds > 0:
        before_parts.append(f'-ss {seek_seconds}')
    before_parts.append('-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -thread_queue_size 8192 -nostdin')
    before = ' '.join(before_parts)
    af = AUDIO_FILTERS.get(filter_key, {}).get("af", "")
    if af:
        options = f'-vn -sn -dn -af {af}'
    else:
        options = '-vn -sn -dn'
    return {'before_options': before, 'options': options}

FFMPEG_OPTIONS = get_ffmpeg_options("studio")


class Song:
    def __init__(self, title, url, duration, requester, thumbnail=None, webpage_url=None, is_autoplay=False):
        self.title = title
        self.url = url
        self.webpage_url = webpage_url or url
        self.duration = duration
        self.requester = requester
        self.thumbnail = thumbnail
        self.is_autoplay = is_autoplay


def resolve_user_playlist_name(user_pls: dict, query: str) -> Optional[str]:
    """Resolve a user's playlist name exactly or case-insensitively."""
    if not user_pls or not query:
        return None
    q = query.strip()
    if q in user_pls:
        return q
    q_low = q.lower()
    for k in user_pls.keys():
        if k.lower() == q_low:
            return k
    return None


def add_song_to_playlist(uid: str, playlist_name: str, song: Song) -> tuple[str, int, str]:
    """Save a track to the user's playlist and remember it as their active quick-save playlist."""
    user_pls = db.playlists.setdefault(uid, {})
    canonical = resolve_user_playlist_name(user_pls, playlist_name) or playlist_name.strip()[:40] or "Favorites"
    pl_tracks = user_pls.setdefault(canonical, [])

    db.active_playlists[uid] = canonical
    if any(item.get("url") == song.webpage_url for item in pl_tracks):
        db.save_data()
        return ("duplicate", len(pl_tracks), canonical)
    if len(pl_tracks) >= 150:
        return ("full", len(pl_tracks), canonical)

    pl_tracks.append({
        "title": song.title,
        "url": song.webpage_url,
        "duration": song.duration
    })
    db.save_data()
    return ("added", len(pl_tracks), canonical)


class SaveToPlaylistModal(discord.ui.Modal, title="Name Your Playlist"):
    playlist_name = discord.ui.TextInput(
        label="Playlist Name",
        placeholder="e.g. Chill Vibes, Favorites, Gym, Late Night",
        default="",
        min_length=1,
        max_length=40,
        required=True
    )

    def __init__(self, cog, song: Song):
        super().__init__()
        self.cog = cog
        self.song = song

    async def on_submit(self, interaction: discord.Interaction):
        try:
            name = self.playlist_name.value.strip()[:40]
            if not name:
                return await interaction.response.send_message("◈ Please provide a valid playlist name.", ephemeral=True)
            uid = str(interaction.user.id)
            status, total, canonical = add_song_to_playlist(uid, name, self.song)

            if status == "full":
                return await interaction.response.send_message(
                    f"◈ Playlist **{canonical}** is at maximum capacity (150 tracks).",
                    ephemeral=True
                )
            if status == "duplicate":
                return await interaction.response.send_message(
                    f"◈ **[{self.song.title}]({self.song.webpage_url})** is already in **{canonical}** (`{total}` tracks).",
                    ephemeral=True
                )

            embed = make_box_embed(
                title="Playlist Created & Track Saved",
                description=(
                    f"Saved **[{self.song.title}]({self.song.webpage_url})** into **{canonical}** (`{total}` tracks).\n"
                    f"Next time you click **Save to Playlist**, songs will auto-save directly to **{canonical}**!\n"
                    f"*Play it anytime using `/playlist play`.*"
                ),
                status="success"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"[Playlist Modal Error] {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("◈ An error occurred saving to playlist.", ephemeral=True)
            except Exception:
                pass


class PlaylistSwitchView(discord.ui.View):
    """Ephemeral helper shown on auto-save so the user can switch active playlists or create a new one."""
    def __init__(self, cog, uid: str, user_pls: dict, active_name: str, song: Song):
        super().__init__(timeout=180)
        self.cog = cog
        self.uid = uid
        self.song = song

        opts = []
        for p_name, tracks in list(user_pls.items())[:25]:
            prefix = "◈ " if p_name == active_name else ""
            opts.append(discord.SelectOption(
                label=f"{prefix}{p_name}"[:100],
                value=p_name[:100],
                description=f"{len(tracks)} tracks" + (" (Auto-save target)" if p_name == active_name else ""),
                default=(p_name == active_name)
            ))
        if opts:
            sel = discord.ui.Select(
                placeholder="Switch auto-save playlist...",
                options=opts,
                row=0
            )
            sel.callback = self._on_switch
            self.add_item(sel)

    async def _on_switch(self, interaction: discord.Interaction):
        chosen = interaction.data["values"][0]
        status, total, canonical = add_song_to_playlist(self.uid, chosen, self.song)
        if status == "full":
            msg = f"◈ Switched active playlist to **{canonical}**, but it is full (150 tracks)."
        elif status == "duplicate":
            msg = f"◈ Active playlist switched to **{canonical}** (`{total}` tracks). **[{self.song.title}]({self.song.webpage_url})** is already in it."
        else:
            msg = f"◈ Switched active playlist to **{canonical}** and saved **[{self.song.title}]({self.song.webpage_url})** (`{total}` tracks)!"
        await interaction.response.edit_message(
            embed=make_box_embed(title="Active Playlist Updated", description=msg, status="success"),
            view=PlaylistSwitchView(self.cog, self.uid, db.playlists.get(self.uid, {}), canonical, self.song)
        )

    @discord.ui.button(label="＋ New Playlist", style=discord.ButtonStyle.secondary, row=1)
    async def new_pl_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SaveToPlaylistModal(self.cog, self.song))


def resolve_music_card_background(bg_path: Optional[str]) -> Optional[str]:
    """Robustly resolve custom music wallpaper path across local machine and Linux VM."""
    if not bg_path or not isinstance(bg_path, str):
        return None
    if os.path.exists(bg_path):
        return bg_path
    base = os.path.basename(bg_path)
    cand1 = os.path.join(os.getcwd(), "dashboard", "static", "uploads", "rank_backgrounds", base)
    if os.path.exists(cand1):
        return cand1
    cand2 = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "uploads", "rank_backgrounds", base)
    if os.path.exists(cand2):
        return os.path.abspath(cand2)
    return None


class MusicControlView(discord.ui.View):
    """
    Compact 3-Row Studio Music Controller View.
    Row 0: Shuffle, Pause/Resume, Skip, Loop, Stop (5 core playback controls)
    Row 1: Vol -, Vol +, Queue, Like, Autoplay (5 audio & library controls)
    Row 2: Mastering EQ & Save to Playlist Select Menu
    Automatically binds uploaded SVG-style Application Emojis (m_*) if present,
    falling back to crisp monochrome symbols.
    """
    def __init__(self, cog=None, guild_id: int = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

        # Apply Application Emojis (m_*) if fetched, otherwise use monochrome glyph labels (no emoji slot)
        icon_map = {
            "music_shuffle": ("m_shuffle", "Shuffle", "⇄ Shuffle"),
            "music_pause_resume": ("m_pause", "Pause", "❚❚ Pause"),
            "music_skip": ("m_skip", "Skip", "» Skip"),
            "music_loop": ("m_loop", "Loop", "↻ Loop"),
            "music_stop": ("m_stop", "Stop", "■ Stop"),
            "music_vol_down": ("m_voldown", "Vol -", "− Vol"),
            "music_vol_up": ("m_volup", "Vol +", "+ Vol"),
            "music_queue": ("m_queue", "Queue", "≡ Queue"),
            "music_like": ("m_like", "Like", "♡ Like"),
            "music_autoplay": ("m_autoplay", "Autoplay", "∞ Auto"),
            "music_save_playlist": ("m_save", "Save to Playlist", "＋ Save to Playlist"),
        }
        is_paused = False
        is_loop = False
        is_autoplay = False
        if cog and guild_id:
            try:
                state = cog.get_state(guild_id)
                is_loop = bool(state.get("loop", False))
                is_autoplay = bool(state.get("autoplay", False))
                is_paused = state.get("paused_at") is not None
                guild_obj = cog.bot.get_guild(guild_id) if cog.bot else None
                vc = guild_obj.voice_client if guild_obj else None
                if vc and vc.is_paused():
                    is_paused = True
            except Exception:
                pass

        for child in self.children:
            cid = getattr(child, "custom_id", None)
            if cid in icon_map:
                app_name, clean_lbl, mono_lbl = icon_map[cid]
                if cid == "music_pause_resume" and is_paused:
                    app_name, clean_lbl, mono_lbl = ("m_play", "Resume", "► Resume")
                    child.style = discord.ButtonStyle.success
                elif cid == "music_loop" and is_loop:
                    clean_lbl, mono_lbl = ("Looping", "↻ Looping")
                    child.style = discord.ButtonStyle.primary
                elif cid == "music_autoplay" and is_autoplay:
                    clean_lbl, mono_lbl = ("Auto: ON", "∞ Auto: ON")
                    child.style = discord.ButtonStyle.primary
                app_em = cog.get_ui_emoji(app_name) if cog else None
                child.emoji = app_em
                child.label = clean_lbl if app_em else mono_lbl

    def _get_context(self, interaction: discord.Interaction):
        gid = interaction.guild_id or self.guild_id
        cog = self.cog or (interaction.client.get_cog("Music") if interaction.client else None)
        return gid, cog

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        print(f"[MusicControlView Error on {item}] {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ An error occurred while controlling music playback.", ephemeral=True)
            else:
                await interaction.followup.send("⚠️ An error occurred while controlling music playback.", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="⇄ Shuffle", style=discord.ButtonStyle.secondary, custom_id="music_shuffle", row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            if len(state["queue"]) < 2:
                try:
                    await interaction.followup.send(embed=make_box_embed(title="Queue Notice", description="Add at least 2 songs to the queue to shuffle.", status="info"), ephemeral=True)
                except Exception:
                    pass
                return

            random.shuffle(state["queue"])
            try:
                await interaction.followup.send(embed=make_box_embed(title="Queue Shuffled", description=f"Reordered **{len(state['queue'])}** upcoming tracks in queue.", status="success"), ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            print(f"[Music Button Error: shuffle] {e}")

    @discord.ui.button(label="❚❚ Pause", style=discord.ButtonStyle.secondary, custom_id="music_pause_resume", row=0)
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            gid, cog = self._get_context(interaction)
            vc = interaction.guild.voice_client if interaction.guild else None
            if not vc or not (vc.is_playing() or vc.is_paused()):
                return await interaction.followup.send(
                    embed=make_box_embed(title="Playback Inactive", description="Nothing is currently playing.", status="error"),
                    ephemeral=True
                )

            state = cog.get_state(gid) if cog else None
            if vc.is_paused():
                vc.resume()
                if cog and state:
                    cog.mark_resumed(state)
                app_em = cog.get_ui_emoji("m_pause") if cog else None
                button.emoji = app_em
                button.label = "Pause" if app_em else "❚❚ Pause"
                button.style = discord.ButtonStyle.secondary
            else:
                vc.pause()
                if cog and state:
                    cog.mark_paused(state)
                app_em = cog.get_ui_emoji("m_play") if cog else None
                button.emoji = app_em
                button.label = "Resume" if app_em else "► Resume"
                button.style = discord.ButtonStyle.success

            if cog:
                await cog.refresh_now_playing_card(gid, message=interaction.message, view=self)
            else:
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    pass
        except Exception as e:
            print(f"[Music Button Error: pause] {e}")

    @discord.ui.button(label="» Skip", style=discord.ButtonStyle.secondary, custom_id="music_skip", row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            gid, cog = self._get_context(interaction)
            vc = interaction.guild.voice_client if interaction.guild else None
            if not vc or not (vc.is_playing() or vc.is_paused()):
                return await interaction.followup.send(
                    embed=make_box_embed(title="Playback Inactive", description="Nothing is currently playing.", status="error"),
                    ephemeral=True
                )

            if cog:
                state = cog.get_state(gid)
                state["loop"] = False

            if vc and (vc.is_playing() or vc.is_paused()):
                try:
                    vc.stop()
                except Exception:
                    pass

            msg = cog.get_resp(gid, "music_skipped", "Skipped current track to next in queue!") if cog else "Skipped current track!"
            try:
                await interaction.followup.send(embed=make_box_embed(title="Track Skipped", description=msg, status="success"), ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            print(f"[Music Button Error: skip] {e}")

    @discord.ui.button(label="↻ Loop", style=discord.ButtonStyle.secondary, custom_id="music_loop", row=0)
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            is_loop = not state.get("loop", False)
            state["loop"] = is_loop
            has_em = button.emoji is not None
            button.label = ("Looping" if has_em else "↻ Looping") if is_loop else ("Loop" if has_em else "↻ Loop")
            button.style = discord.ButtonStyle.primary if is_loop else discord.ButtonStyle.secondary
            await cog.refresh_now_playing_card(gid, message=interaction.message, view=self)
        except Exception as e:
            print(f"[Music Button Error: loop] {e}")

    @discord.ui.button(label="■ Stop", style=discord.ButtonStyle.danger, custom_id="music_stop", row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            gid, cog = self._get_context(interaction)
            vc = interaction.guild.voice_client if interaction.guild else None

            if cog:
                state = cog.get_state(gid)
                state["_stopping"] = True
                state["loop"] = False
                state["queue"].clear()
                state["current"] = None
                state["transformer"] = None
                cog.reset_track_timer(state)

            for child in self.children:
                child.disabled = True

            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

            if vc and (vc.is_playing() or vc.is_paused()):
                try:
                    vc.stop()
                except Exception:
                    pass
        except Exception as e:
            print(f"[Music Button Error: stop] {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="− Vol", style=discord.ButtonStyle.secondary, custom_id="music_vol_down", row=1)
    async def vol_down_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            current_vol = state.get("volume", 1.0)
            new_vol = max(0.2, round(current_vol - 0.15, 2))
            state["volume"] = new_vol
            transformer = state.get("transformer")
            if transformer:
                transformer.volume = new_vol
            await cog.refresh_now_playing_card(gid, message=interaction.message, view=self)
            try:
                await interaction.followup.send(embed=make_box_embed(title="Volume Lowered", description=f"Master volume adjusted to **{int(new_vol * 100)}%**.", status="audio"), ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            print(f"[Music Button Error: vol_down] {e}")

    @discord.ui.button(label="+ Vol", style=discord.ButtonStyle.secondary, custom_id="music_vol_up", row=1)
    async def vol_up_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            current_vol = state.get("volume", 1.0)
            new_vol = min(2.0, round(current_vol + 0.15, 2))
            state["volume"] = new_vol
            transformer = state.get("transformer")
            if transformer:
                transformer.volume = new_vol
            await cog.refresh_now_playing_card(gid, message=interaction.message, view=self)
            try:
                await interaction.followup.send(embed=make_box_embed(title="Volume Raised", description=f"Master volume adjusted to **{int(new_vol * 100)}%**.", status="audio"), ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            print(f"[Music Button Error: vol_up] {e}")

    @discord.ui.button(label="≡ Queue", style=discord.ButtonStyle.secondary, custom_id="music_queue", row=1)
    async def queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            current = state.get("current")
            queue = state.get("queue", [])
            if not current and not queue:
                msg = cog.get_resp(gid, "music_queue_empty", "The queue is currently empty.")
                try:
                    await interaction.followup.send(embed=make_box_embed(title="Queue Empty", description=msg, status="info"), ephemeral=True)
                except Exception:
                    pass
                return

            embed = discord.Embed(
                title="◈  Playback Queue",
                color=discord.Color.from_rgb(139, 92, 246)
            )
            if current:
                mins, secs = divmod(current.duration or 0, 60)
                if getattr(current, "is_autoplay", False):
                    req_mention = "Autoplay Discovery"
                else:
                    req_mention = current.requester.mention if (getattr(current, 'requester', None) and hasattr(current.requester, 'mention')) else "DJ"
                embed.add_field(
                    name="▶ Currently Playing",
                    value=f"• **[{current.title}]({current.webpage_url})**\n  ⏱ `{mins:02d}:{secs:02d}` • Requested by: {req_mention}",
                    inline=False
                )
            if queue:
                lines = []
                for idx, s in enumerate(queue[:10], start=1):
                    mins, secs = divmod(s.duration or 0, 60)
                    if getattr(s, "is_autoplay", False):
                        s_req = "Autoplay"
                    else:
                        s_req = s.requester.mention if (getattr(s, 'requester', None) and hasattr(s.requester, 'mention')) else "DJ"
                    lines.append(f"`{idx}.` **[{s.title}]({s.webpage_url})** (`{mins:02d}:{secs:02d}`) — {s_req}")
                if len(queue) > 10:
                    lines.append(f"*... and {len(queue) - 10} more songs in queue*")
                embed.add_field(name="Upcoming in Queue", value="\n".join(lines), inline=False)
            else:
                embed.add_field(name="Upcoming in Queue", value="*No upcoming songs. Use `/play` to add more!*", inline=False)

            embed.set_footer(text=f"Total: {len(queue)} upcoming • Friday Studio Audio Engine")
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            print(f"[Music Button Error: queue] {e}")

    @discord.ui.button(label="♡ Like", style=discord.ButtonStyle.secondary, custom_id="music_like", row=1)
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            current = state.get("current")
            if not current:
                try:
                    await interaction.followup.send(embed=make_box_embed(title="Liked Songs", description="No track currently playing to like.", status="error"), ephemeral=True)
                except Exception:
                    pass
                return

            uid_str = str(interaction.user.id)
            user_likes = db.liked_songs.setdefault(uid_str, [])
            if any(item.get("url") == current.webpage_url for item in user_likes):
                try:
                    await interaction.followup.send(embed=make_box_embed(title="Already Saved", description=f"**[{current.title}]({current.webpage_url})** is already in your Liked Songs! Use `/likes` to view them.", status="info"), ephemeral=True)
                except Exception:
                    pass
                return

            user_likes.append({
                "title": current.title,
                "url": current.webpage_url,
                "duration": current.duration
            })
            db.save_data()
            try:
                await interaction.followup.send(embed=make_box_embed(title="Song Saved", description=f"Saved **[{current.title}]({current.webpage_url})** to your Liked Songs! Use `/likes` to play them anytime.", status="success"), ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            print(f"[Music Button Error: like] {e}")

    @discord.ui.button(label="∞ Auto", style=discord.ButtonStyle.secondary, custom_id="music_autoplay", row=1)
    async def autoplay_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            new_auto = not state.get("autoplay", False)
            state["autoplay"] = new_auto

            has_em = button.emoji is not None
            button.label = ("Auto: ON" if has_em else "∞ Auto: ON") if new_auto else ("Autoplay" if has_em else "∞ Auto")
            button.style = discord.ButtonStyle.primary if new_auto else discord.ButtonStyle.secondary

            await cog.refresh_now_playing_card(gid, message=interaction.message, view=self)

            if new_auto:
                asyncio.create_task(cog.ensure_autoplay_queued(gid))
                msg = "Friday will intelligently pre-fetch and stream similar tracks with matching mood and artist!"
            else:
                state["queue"] = [s for s in state.get("queue", []) if not getattr(s, "is_autoplay", False)]
                msg = "Autoplay has been turned off. Any upcoming autoplay recommendations have been removed from the queue."
            try:
                await interaction.followup.send(
                    embed=make_box_embed(title="Autoplay Mode", description=f"Autoplay is now **{'ENABLED' if new_auto else 'DISABLED'}**.\n{msg}", status="audio"),
                    ephemeral=True
                )
            except Exception:
                pass
        except Exception as e:
            print(f"[Music Button Error: autoplay] {e}")

    @discord.ui.button(label="＋ Save to Playlist", style=discord.ButtonStyle.secondary, custom_id="music_save_playlist", row=2)
    async def save_playlist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            current = state.get("current")
            if not current:
                return await interaction.response.send_message("◈ No track currently playing to save.", ephemeral=True)

            uid = str(interaction.user.id)
            user_pls = db.playlists.get(uid, {})
            if not user_pls:
                return await interaction.response.send_modal(SaveToPlaylistModal(cog, current))

            active_name = resolve_user_playlist_name(user_pls, db.active_playlists.get(uid, "")) or list(user_pls.keys())[-1]
            status, total, canonical = add_song_to_playlist(uid, active_name, current)
            switch_view = PlaylistSwitchView(cog, uid, db.playlists.get(uid, {}), canonical, current)

            if status == "full":
                embed = make_box_embed(
                    title="Playlist Full",
                    description=f"Playlist **{canonical}** has reached the 150-track limit.\nSwitch or create a new playlist below.",
                    status="warning"
                )
            elif status == "duplicate":
                embed = make_box_embed(
                    title="Already in Playlist",
                    description=f"**[{current.title}]({current.webpage_url})** is already saved in **{canonical}** (`{total}` tracks).\nWant to save to a different playlist? Switch below.",
                    status="info"
                )
            else:
                embed = make_box_embed(
                    title="Saved to Playlist",
                    description=f"Auto-saved **[{current.title}]({current.webpage_url})** to **{canonical}** (`{total}` tracks).\n*Use `/playlist play` anytime to play your playlist!*",
                    status="success"
                )
            await interaction.response.send_message(embed=embed, view=switch_view, ephemeral=True)
        except Exception as e:
            print(f"[Music Button Error: save_playlist] {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("◈ Could not save track to playlist.", ephemeral=True)
            except Exception:
                pass

    @discord.ui.select(
        placeholder="◈  Mastering EQ Profiles...",
        custom_id="music_eq_select",
        row=3,
        options=[
            discord.SelectOption(label="◈  EQ: Studio Master", value="studio", description="Crisp 48kHz highs, warm punch, anti-clipping"),
            discord.SelectOption(label="◈  EQ: Bass Boost", value="bassboost", description="Deep sub-bass punch for EDM, Phonk, Hip-Hop"),
            discord.SelectOption(label="◈  EQ: Vocal / Acoustic", value="vocal", description="Enhanced vocal presence and instrument clarity"),
            discord.SelectOption(label="◈  EQ: Nightcore", value="nightcore", description="High-energy speedup (1.25x tempo + higher pitch)"),
            discord.SelectOption(label="◈  EQ: Lo-Fi / Warm Chill", value="lofi", description="Warm vintage analog low-pass filter"),
            discord.SelectOption(label="◈  EQ: Treble Boost", value="treble", description="Crisp high-frequency clarity and vocal sparkle"),
            discord.SelectOption(label="◈  EQ: 8D Surround", value="8d", description="Rotating spatial binaural surround sound"),
            discord.SelectOption(label="◈  EQ: Flat / Pure Raw", value="flat", description="Untouched original audio stream"),
        ]
    )
    async def eq_dropdown(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            gid, cog = self._get_context(interaction)
            if not cog:
                return
            chosen = select.values[0]
            state = cog.get_state(gid)
            current = state.get("current")

            if chosen == "__save_playlist__":
                if not current:
                    return await interaction.response.send_message("❌ No track currently playing to save.", ephemeral=True)
                return await interaction.response.send_modal(SaveToPlaylistModal(cog, current))

            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

            new_eq = chosen
            state["filter"] = new_eq
            profile = AUDIO_FILTERS.get(new_eq, AUDIO_FILTERS["studio"])

            vc = interaction.guild.voice_client if interaction.guild else None

            if vc and (vc.is_playing() or vc.is_paused()) and current:
                vol = state.get("volume", 1.0)
                elapsed = int(cog.get_elapsed_seconds(state, current.duration or 0))
                dur = current.duration or 3600
                ss_pos = max(0, min(elapsed, dur - 2))

                async def _apply_eq_seamless():
                    try:
                        state["_switching_filter"] = True
                        vc.stop()
                        for _ in range(15):
                            if not vc.is_playing() and not vc.is_paused():
                                break
                            await asyncio.sleep(0.04)

                        ffmpeg_opts = cog.get_ffmpeg_options(gid, seek_seconds=ss_pos)
                        raw_source = discord.FFmpegPCMAudio(current.url, **ffmpeg_opts)
                        source = discord.PCMVolumeTransformer(raw_source, volume=vol)
                        state["transformer"] = source
                        cog.reset_track_timer(state, seek_seconds=ss_pos)

                        if vc.ws:
                            try:
                                await vc.ws.speak(discord.SpeakingState.voice)
                            except Exception:
                                pass

                        def after_play(err):
                            if state.get("_switching_filter") or state.get("_stopping"):
                                state["_stopping"] = False
                                return
                            cog.play_next(gid)

                        vc.play(source, after=after_play)

                        np_msg = interaction.message or state.get("np_message")
                        await cog.refresh_now_playing_card(gid, message=np_msg, view=self)
                    except Exception as err:
                        print(f"[Music EQ Switch Error] {err}")
                    finally:
                        state["_switching_filter"] = False

                asyncio.create_task(_apply_eq_seamless())

            try:
                await interaction.followup.send(
                    embed=make_box_embed(
                        title="Equalizer Updated",
                        description=f"Equalizer Profile: **{profile['name']}**\n{profile['description']}\n*Seamless real-time mastering engaged without restarting track.*",
                        status="audio"
                    ),
                    ephemeral=True
                )
            except Exception:
                pass
        except Exception as e:
            print(f"[Music Button Error: eq_select] {e}")


class QueueItemView(discord.ui.View):
    """Action buttons for newly queued tracks: Play Now or Remove from Queue."""
    def __init__(self, cog, guild_id: int, song: Song):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.song = song

        icon_map = {
            "queue_play_now": ("m_play", "Play Now", "► Play Now"),
            "queue_remove": ("m_remove", "Remove from Queue", "✕ Remove from Queue"),
        }
        for child in self.children:
            cid = getattr(child, "custom_id", None)
            if cid in icon_map:
                app_name, clean_lbl, mono_lbl = icon_map[cid]
                app_em = cog.get_ui_emoji(app_name) if cog else None
                child.emoji = app_em
                child.label = clean_lbl if app_em else mono_lbl

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        print(f"[QueueItemView Error on {item}] {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("◈ An error occurred updating the music queue.", ephemeral=True)
            else:
                await interaction.followup.send("◈ An error occurred updating the music queue.", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="► Play Now", style=discord.ButtonStyle.secondary, custom_id="queue_play_now")
    async def play_now_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
        except Exception:
            pass

        try:
            state = self.cog.get_state(self.guild_id)
            vc = interaction.guild.voice_client if interaction.guild else None
            if not vc:
                await interaction.followup.send("◈ Friday is not in a voice channel.", ephemeral=True)
                return

            if self.song in state["queue"]:
                state["queue"].remove(self.song)

            state["queue"].insert(0, self.song)

            if vc.is_playing() or vc.is_paused():
                asyncio.get_event_loop().run_in_executor(None, vc.stop)

            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            await interaction.followup.send(f"► Now playing **{self.song.title}** immediately!", ephemeral=True)
        except Exception as e:
            print(f"[Music Queue Button Error] {e}")

    @discord.ui.button(label="✕ Remove from Queue", style=discord.ButtonStyle.secondary, custom_id="queue_remove")
    async def remove_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
        except Exception:
            pass

        try:
            state = self.cog.get_state(self.guild_id)
            if self.song in state["queue"]:
                state["queue"].remove(self.song)
                for child in self.children:
                    child.disabled = True
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    pass
                await interaction.followup.send(f"✕ Removed **{self.song.title}** from the queue.", ephemeral=True)
            else:
                await interaction.followup.send("◈ This track is already playing or no longer in the queue.", ephemeral=True)
        except Exception as e:
            print(f"[Music Queue Button Error] {e}")


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.states = {}
        self._app_emojis: Dict[str, Any] = {}
        self._app_emojis_loaded = False

    async def cog_load(self):
        try:
            self.bot.add_view(MusicControlView(self))
            print("[Music] ✅ Persistent MusicControlView registered via cog_load.")
        except Exception as e:
            print(f"[Music] Note: Persistent view registration in cog_load: {e}")
        if not self.music_card_updater.is_running():
            self.music_card_updater.start()
        asyncio.create_task(self.load_app_emojis())

    def cog_unload(self):
        if self.music_card_updater.is_running():
            self.music_card_updater.cancel()

    async def load_app_emojis(self):
        """Fetch Application Emojis (m_play, m_pause, etc.) once connected so buttons render crisp vector icons."""
        if self._app_emojis_loaded:
            return
        try:
            await self.bot.wait_until_ready()
            emojis = await self.bot.fetch_application_emojis()
            self._app_emojis = {e.name.lower(): discord.PartialEmoji(name=e.name, id=e.id, animated=e.animated) for e in emojis}
            self._app_emojis_loaded = True
            if self._app_emojis:
                print(f"[Music] 🎨 Loaded {len(self._app_emojis)} Application Emojis for player controls.")
        except Exception as e:
            print(f"[Music] Application Emoji fetch note: {e}")

    def get_ui_emoji(self, app_emoji_name: str, fallback=None):
        return self._app_emojis.get(app_emoji_name.lower(), fallback)

    def get_state(self, guild_id: int):
        if guild_id not in self.states:
            self.states[guild_id] = {
                "queue": [],
                "current": None,
                "channel": None,
                "loop": False,
                "autoplay": False,
                "autoplay_history": [],
                "last_played": None,
                "volume": 1.0,
                "transformer": None,
                "filter": "studio",
                "start_time": 0.0,
                "paused_at": None,
                "paused_total": 0.0,
                "np_message": None,
                "_stopping": False,
                "_switching_filter": False,
                "_updating_card": False,
                "_card_cache": None,
            }
        return self.states[guild_id]

    @staticmethod
    def reset_track_timer(state: dict, seek_seconds: float = 0.0):
        state["start_time"] = time.time() - max(0.0, float(seek_seconds or 0.0))
        state["paused_at"] = None
        state["paused_total"] = 0.0

    @staticmethod
    def mark_paused(state: dict):
        if state.get("paused_at") is None:
            state["paused_at"] = time.time()

    @staticmethod
    def mark_resumed(state: dict):
        pa = state.get("paused_at")
        if pa is not None:
            state["paused_total"] = state.get("paused_total", 0.0) + max(0.0, time.time() - pa)
            state["paused_at"] = None

    @staticmethod
    def get_elapsed_seconds(state: dict, duration: int = 0) -> float:
        st = state.get("start_time", 0.0)
        if not st:
            return 0.0
        ref = state["paused_at"] if state.get("paused_at") is not None else time.time()
        elapsed = max(0.0, ref - st - state.get("paused_total", 0.0))
        if duration and duration > 0:
            elapsed = min(float(duration), elapsed)
        return elapsed

    async def set_voice_channel_status(self, channel: Optional[discord.VoiceChannel], status: str):
        if not channel or not isinstance(channel, discord.VoiceChannel):
            return
        try:
            route = discord.http.Route('PUT', '/channels/{channel_id}/voice-status', channel_id=channel.id)
            clean_status = status[:500]
            await self.bot.http.request(route, json={'status': clean_status, 'emoji_name': None, 'emoji_id': None})
        except Exception:
            pass

    async def clear_voice_channel_status(self, channel: Optional[discord.VoiceChannel]):
        if not channel or not isinstance(channel, discord.VoiceChannel):
            return
        try:
            route = discord.http.Route('PUT', '/channels/{channel_id}/voice-status', channel_id=channel.id)
            await self.bot.http.request(route, json={'status': '', 'emoji_name': None, 'emoji_id': None})
        except Exception:
            pass

    def _detect_language(self, title: str) -> str:
        t = title.lower()
        if HINDI_SCRIPT_RE.search(title):
            return "hindi"
        if PUNJABI_SCRIPT_RE.search(title):
            return "punjabi"
        if KOREAN_SCRIPT_RE.search(title):
            return "kpop"
        if JAPANESE_SCRIPT_RE.search(title):
            return "japanese"
        if KPOP_ARTISTS_RE.search(t):
            return "kpop"
        if JAPANESE_ARTISTS_RE.search(t):
            return "japanese"
        if PUNJABI_ARTISTS_RE.search(t) or PUNJABI_ROMAN_WORDS_RE.search(t):
            return "punjabi"
        if INDIAN_ARTISTS_RE.search(t):
            return "hindi"
        if INDIAN_LABELS_KEYWORDS_RE.search(t):
            if 'punjabi' in t or 'bhangra' in t:
                return "punjabi"
            return "hindi"
        if HINDI_ROMAN_WORDS_RE.search(t):
            return "hindi"
        return "english"

    def _extract_artist_and_title(self, raw_title: str) -> Tuple[Optional[str], str]:
        junk = r'(?i)\b(official|music|video|audio|lyrics|lyric|hd|4k|remastered|song|track|full\s+song|visualizer|feat\.?|ft\.?)\b'

        if "|" in raw_title:
            parts = [p.strip() for p in raw_title.split("|") if p.strip()]
            title_part = re.sub(junk, '', re.sub(r'[\(\[\{].*?[\)\]\}]', '', parts[0])).strip()
            if " - " in title_part:
                title_part = title_part.split(" - ")[0].strip()

            artist_part = None
            for p in parts[1:]:
                m = PUNJABI_ARTISTS_RE.search(p) or INDIAN_ARTISTS_RE.search(p)
                if m:
                    artist_part = m.group(0).title()
                    break
            if not artist_part and len(parts) > 1:
                artist_part = re.sub(junk, '', re.sub(r'[\(\[\{].*?[\)\]\}]', '', parts[-1])).strip()
            return artist_part, title_part

        cleaned = re.sub(r'[\(\[\{].*?[\)\]\}]', '', raw_title).strip()
        cleaned = re.sub(junk, '', cleaned).strip()

        if " - " in cleaned:
            parts = cleaned.split(" - ", 1)
            return parts[0].strip(), parts[1].strip()

        return None, cleaned

    def _detect_song_features(self, title: str) -> Tuple[Optional[str], str, Optional[str]]:
        t = title.lower()
        detected_mood = None
        for mood, pattern in AUTOPLAY_MOOD_PATTERNS.items():
            if pattern.search(t):
                detected_mood = mood
                break
        detected_lang = self._detect_language(title)
        artist, _ = self._extract_artist_and_title(title)
        return detected_mood, detected_lang, artist

    def _flat_search_sync(self, query: str, playlist_end: int = 12) -> list:
        opts = {
            'extract_flat': 'in_playlist',
            'quiet': True,
            'no_warnings': True,
            'playlistend': playlist_end,
            'http_headers': DEFAULT_HEADERS,
            'socket_timeout': 6
        }
        cookie_path = get_cookie_file()
        if cookie_path and os.path.isfile(cookie_path) and os.path.getsize(cookie_path) > 0:
            opts['cookiefile'] = cookie_path
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)
                if not info:
                    return []
                if 'entries' in info:
                    return [e for e in info['entries'] if e]
                return [info]
        except Exception as e:
            print(f"[Music Autoplay Flat Search Error] {e}")
            return []

    async def _find_autoplay_track(self, last_song: Song, guild_id: int) -> Optional[Song]:
        """Uses YouTube Mix Radio (RD playlist) first, then strict Music-only fallback, blocking 18+ & non-music."""
        state = self.get_state(guild_id)
        mood, lang, artist = self._detect_song_features(last_song.title)
        extracted_artist, core_title = self._extract_artist_and_title(last_song.title)
        if not artist and extracted_artist:
            artist = extracted_artist
        if not core_title or len(core_title) < 2:
            core_title = last_song.title

        clean_norm = re.sub(r'[^a-z0-9]', '', core_title.lower())
        history = set(state.get("autoplay_history", []))
        candidates = []

        banned_terms = [
            'how i made', 'how to', 'tutorial', 'making of', 'behind the scenes',
            'interview', 'reaction', 'reacting', 'breakdown', 'vlog', 'review',
            'podcast', 'teaser', 'trailer', 'short film', 'documentary', 'episode',
            'prank', 'challenge', 'roast', 'drama', 'gaming', 'gameplay',
            'tiktok', 'reels', 'highlight', 'twitch', 'stream', 'compilation', 'jukebox',
            'lyrics', 'lyric', 'lyrical', 'animated', 'animation', 'mashup', 'cover',
            'status', 'shorts', 'ringtone', 'karaoke', 'instrumental',
            '18+', 'nsfw', 'explicit', 'uncensored', 'hot video', 'sexy', 'vulgar',
            'leaked', 'bhabhi', 'erotic', 'onlyfans', 'porn', 'xxx', 'adult', 'nude',
            'naked', 'bikini', 'kiss scene', 'bed scene', 'hot scene', 'sensual',
            'bold scene', 'web series', 'ullu', 'kooku', 'softcore', 'hardcore'
        ]

        def _is_valid_entry(entry: dict) -> bool:
            t_name = entry.get("title") or ""
            if not t_name or t_name in history:
                return False
            dur = entry.get("duration") or 0
            # Strict music length: 90s to 8 mins (blocks Shorts, trailers, 1-hour mixes)
            if dur and (dur < 90 or dur > 480):
                return False
            uploader = (entry.get("uploader") or entry.get("channel") or "").lower()
            combined = f"{t_name.lower()} {uploader}"
            if any(bt in combined for bt in banned_terms):
                return False
            cand_norm = re.sub(r'[^a-z0-9]', '', t_name.lower())
            if len(clean_norm) >= 4 and clean_norm in cand_norm:
                return False
            return True

        # 1. Primary: YouTube Native Music Mix Radio (RD<video_id>)
        yt_id_match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', last_song.webpage_url or "")
        if yt_id_match:
            vid_id = yt_id_match.group(1)
            mix_url = f"https://www.youtube.com/watch?v={vid_id}&list=RD{vid_id}"
            try:
                mix_entries = await asyncio.to_thread(self._flat_search_sync, mix_url, 15)
                for entry in mix_entries:
                    if entry.get("id") == vid_id:
                        continue
                    if _is_valid_entry(entry):
                        candidates.append(entry)
            except Exception as mix_err:
                print(f"[Autoplay Mix Error] {mix_err}")

        # 2. Fallback: Targeted Official Audio / Topic Search
        if len(candidates) < 3:
            is_desi = lang in ("hindi", "punjabi")
            queries = []
            if artist:
                queries.append(f"{artist} official audio topic")
            if is_desi:
                queries.append(f"top {lang} {mood or 'hit'} songs official audio")
            else:
                queries.append(f"top {mood or 'pop'} songs official audio topic")

            for q in queries:
                try:
                    results = await asyncio.to_thread(self._flat_search_sync, f"ytsearch10:{q}", 10)
                    for entry in results:
                        if _is_valid_entry(entry):
                            candidates.append(entry)
                    if len(candidates) >= 5:
                        break
                except Exception as search_ex:
                    print(f"[Autoplay Search Error for '{q}'] {search_ex}")

        if not candidates:
            return None

        # 3. Extract & Verify: Must be Music category + Not age-restricted
        candidate_pool = list(candidates[:8])
        random.shuffle(candidate_pool)
        for chosen_entry in candidate_pool:
            vid_id = chosen_entry.get("id")
            track_target = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else (chosen_entry.get("url") or chosen_entry.get("title"))
            try:
                info = await self.extract_audio_info(track_target)
                if not info or not info.get("url"):
                    continue

                if (info.get("age_limit") or 0) > 0:
                    continue

                categories = [c.lower() for c in (info.get("categories") or [])]
                if categories and "music" not in categories:
                    continue

                info_title = (info.get("title") or "").lower()
                info_uploader = (info.get("uploader") or info.get("channel") or "").lower()
                if any(bt in f"{info_title} {info_uploader}" for bt in banned_terms):
                    continue

                return Song(
                    title=info["title"],
                    url=info["url"],
                    webpage_url=info.get("webpage_url", track_target),
                    duration=info.get("duration", 0),
                    requester=self.bot.user,
                    thumbnail=info.get("thumbnail") or chosen_entry.get("thumbnail"),
                    is_autoplay=True
                )
            except Exception as ex:
                print(f"[Autoplay Extract Note] {ex}")
                continue

        return None

    @staticmethod
    def enqueue_user_song(state: dict, song: Song) -> int:
        """Prioritize human-requested tracks ahead of unplayed Autoplay suggestions and return 1-based queue position."""
        state["queue"] = [s for s in state.get("queue", []) if not getattr(s, "is_autoplay", False)]
        state["queue"].append(song)
        return len(state["queue"])

    async def ensure_autoplay_queued(self, guild_id: int):
        """Pre-fetches the next matching autoplay track so the queue is never empty and playback never stalls."""
        state = self.get_state(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not guild or not guild.voice_client or not guild.voice_client.is_connected():
            return
        if not state.get("autoplay") or state.get("_stopping"):
            return
        if state.get("queue") or state.get("_fetching_autoplay"):
            return

        ref_song = state.get("current") or state.get("last_played")
        if not ref_song:
            return

        state["_fetching_autoplay"] = True
        try:
            print(f"[Music Autoplay] Pre-fetching next recommendation for guild {guild_id} based on '{ref_song.title}'...")
            channel = state.get("channel")
            next_song = await self._find_autoplay_track(ref_song, guild_id)
            vc = guild.voice_client
            # If a user queued a song (or stopped/disabled autoplay) while searching, yield to the user's queue!
            if state.get("queue") or not state.get("autoplay") or state.get("_stopping") or not vc or not vc.is_connected():
                return
            if next_song:
                next_song.is_autoplay = True
                state["queue"].append(next_song)
                print(f"[Music Autoplay] Queued next song: '{next_song.title}' (queue length: {len(state['queue'])})")

                if channel:
                    try:
                        n_mood, n_lang, _ = self._detect_song_features(next_song.title)
                        r_mood, _, _ = self._detect_song_features(ref_song.title)
                        disp_mood = n_mood or r_mood
                        disp_lang = n_lang if n_lang != "english" else None
                        desc_parts = []
                        if disp_mood: desc_parts.append(f"mood: **{disp_mood.capitalize()}**")
                        if disp_lang: desc_parts.append(f"lang: **{disp_lang.capitalize()}**")
                        tag = f" ({' • '.join(desc_parts)})" if desc_parts else ""
                        await channel.send(
                            f"📻 **Autoplay:** Up next: **[{next_song.title}](<{next_song.webpage_url}>)**{tag}",
                            suppress_embeds=True
                        )
                    except Exception as ch_err:
                        print(f"[Music Autoplay] Notice send note: {ch_err}")

                if state.get("current") is None or not (vc.is_playing() or vc.is_paused()):
                    self.play_next(guild_id)
            else:
                print(f"[Music Autoplay] No similar tracks found for '{ref_song.title}'.")
                if channel and (state.get("current") is None and vc and not vc.is_playing()):
                    try:
                        await channel.send("📻 **Autoplay:** Reached the end of matching recommendations for this mood.", delete_after=10)
                    except Exception:
                        pass
                if vc and vc.channel and (state.get("current") is None and not vc.is_playing()):
                    await self.clear_voice_channel_status(vc.channel)
        except Exception as e:
            print(f"[Music Autoplay Error in ensure_autoplay_queued] {e}")
        finally:
            state["_fetching_autoplay"] = False

    async def _handle_autoplay(self, guild_id: int, last_song: Song = None):
        if last_song:
            state = self.get_state(guild_id)
            state["last_played"] = last_song
        await self.ensure_autoplay_queued(guild_id)

    def get_ffmpeg_options(self, guild_id: int, seek_seconds: int = 0):
        state = self.get_state(guild_id)
        f_key = state.get("filter", "studio")
        return get_ffmpeg_options(f_key, seek_seconds=seek_seconds)

    def get_resp(self, guild_id: int, key: str, default: str, **kwargs) -> str:
        gid_str = str(guild_id)
        msg = db.custom_responses.get(gid_str, {}).get(key, default)
        for k, v in kwargs.items():
            msg = msg.replace(f"{{{k}}}", str(v))
        return msg

    async def fetch_suggestions(self, query: str):
        if not query or len(query.strip()) < 2:
            return []
        try:
            encoded = urllib.parse.quote(query.strip())
            url = f"https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q={encoded}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            loop = asyncio.get_event_loop()

            def do_fetch():
                with urllib.request.urlopen(req, timeout=1.8) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    return data[1] if len(data) > 1 else []

            suggestions = await loop.run_in_executor(None, do_fetch)
            choices = []
            for s in suggestions[:15]:
                name = s[:100]
                choices.append(app_commands.Choice(name=name, value=name))
            return choices
        except Exception:
            return []

    async def extract_audio_info(self, query: str):
        """Extract high-fidelity stream URL and rich metadata with multi-source cloud fallback."""
        loop = asyncio.get_event_loop()

        def _extract():
            is_url = query.startswith("http://") or query.startswith("https://")
            cookie_path = get_cookie_file()
            format_chain = 'bestaudio[acodec=opus]/bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best'
            active_cookie_path = cookie_path if (cookie_path and os.path.isfile(cookie_path) and os.path.getsize(cookie_path) > 0) else None

            DIRECT_AUDIO_EXTS = ('.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac', '.opus', '.m3u8')
            if is_url and any(query.lower().split('?')[0].endswith(ext) for ext in DIRECT_AUDIO_EXTS):
                clean_name = query.split('/')[-1].split('?')[0]
                return {
                    'title': clean_name or 'Direct Audio Stream',
                    'url': query,
                    'webpage_url': query,
                    'duration': 0,
                    'thumbnail': None,
                    'age_limit': 0,
                    'uploader': '',
                    'channel': '',
                    'categories': ['Music']
                }

            def _extract_saavn(search_text):
                try:
                    clean_query = re.sub(r'\b(song|songs|video|audio|mp3|official track|track)\b', '', search_text, flags=re.IGNORECASE).strip()
                    clean_query = re.sub(r'\bjho\b', 'jo', clean_query, flags=re.IGNORECASE)
                    if not clean_query:
                        clean_query = search_text.strip()

                    url = f"https://www.jiosaavn.com/api.php?__call=search.getResults&_format=json&_marker=0&api_version=4&ctx=web6dot0&q={urllib.parse.quote(clean_query)}&n=10&p=1"
                    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        content = resp.read().decode('utf-8')
                        data = json.loads(content)
                        results = data.get('results', [])
                        if not results:
                            return None

                        stop_words = {'song', 'songs', 'video', 'audio', 'mp3', 'track', 'full', 'official'}
                        q_words = [w.lower() for w in re.findall(r'\w+', search_text) if w.lower() not in stop_words]
                        if not q_words:
                            q_words = [w.lower() for w in re.findall(r'\w+', search_text)]

                        best_candidate = None
                        best_score = -999

                        for item in results:
                            raw_t = item.get('title', '')
                            clean_t = raw_t.replace('&quot;', '"').replace('&#039;', "'").replace('&amp;', '&')
                            sub = item.get('subtitle', '')
                            album = item.get('more_info', {}).get('album', '')
                            full_text = f"{clean_t} {sub} {album}".lower()

                            matched_words = [w for w in q_words if w in full_text]
                            if not matched_words:
                                continue
                            if q_words[0] not in full_text and len(matched_words) < 2:
                                continue

                            score = len(matched_words) * 20
                            penalty_terms = ['different version', 'sad version', 'slowed', 'reverb', 'remix', 'instrumental', 'cover', 'acoustic', 'mashup', 'slap', 'harddope', 'lexmorris']
                            for pt in penalty_terms:
                                if pt in full_text and pt not in search_text.lower():
                                    score -= 45

                            clean_base = re.sub(r'[\(\[].*?[\)\]]', '', clean_t).strip().lower()
                            if clean_base == clean_query.lower():
                                score += 35
                            elif clean_query.lower() in clean_base:
                                score += 15

                            if score > best_score:
                                best_score = score
                                best_candidate = item

                        if not best_candidate or best_score < 55:
                            print(f"[Music] Saavn skipped low-confidence match (score {best_score} < 55) for: '{search_text}'.")
                            return None

                        more = best_candidate.get('more_info', {})
                        enc_url = more.get('encrypted_media_url')
                        if not enc_url:
                            return None

                        stream_url = decrypt_saavn_url(enc_url)
                        if not stream_url:
                            return None

                        raw_title = best_candidate.get('title', 'Unknown Track')
                        clean_title = raw_title.replace('&quot;', '"').replace('&#039;', "'").replace('&amp;', '&')
                        artists = best_candidate.get('subtitle', '')
                        dur = int(more.get('duration', 0))
                        img = best_candidate.get('image', '').replace('150x150', '500x500')
                        perma = best_candidate.get('perma_url', '')

                        print(f"[Music] Saavn resolved match: {clean_title} ({artists}) | Score: {best_score} | 320kbps CDN Stream")
                        return {
                            'title': f"{clean_title} - {artists}" if artists else clean_title,
                            'url': stream_url,
                            'webpage_url': perma or stream_url,
                            'duration': dur,
                            'thumbnail': img,
                            'age_limit': 0,
                            'uploader': artists,
                            'channel': 'JioSaavn',
                            'categories': ['Music']
                        }
                except Exception as saavn_err:
                    print(f"[Music] Saavn extraction error: {saavn_err}")
                    return None

            def _extract_sc(search_text):
                sc_opts = {
                    'format': 'bestaudio/best',
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': DEFAULT_HEADERS,
                }
                with yt_dlp.YoutubeDL(sc_opts) as sc_ydl:
                    info = sc_ydl.extract_info(f"scsearch5:{search_text}", download=False)
                    entries = info.get('entries', []) if info and 'entries' in info else ([info] if info else [])
                    if not entries:
                        return None

                    best_entry = None
                    best_score = -999
                    q_lower = search_text.lower()
                    stop_words = {'song', 'songs', 'video', 'audio', 'mp3', 'track', 'full', 'official'}
                    q_words = [w.lower() for w in re.findall(r'\w+', search_text) if w.lower() not in stop_words]
                    if not q_words:
                        q_words = [w.lower() for w in re.findall(r'\w+', search_text)]

                    for entry in entries:
                        if not entry or not entry.get('url'):
                            continue
                        t = entry.get('title', '').lower()
                        uploader = (entry.get('uploader') or '').lower()
                        dur = entry.get('duration', 0)
                        dur_sec = int(dur / 1000) if dur > 10000 else int(dur)

                        if 0 < dur_sec <= 35:
                            continue
                        score_pen = 50 if (dur_sec > 600 and "hour" not in q_lower) else 0
                        score = sum(20 for w in q_words if w in t) - score_pen
                        if any(w in uploader for w in q_words):
                            score += 25
                        for pt in ['cover', 'remix', 'drill', 'mashup', 'slowed', 'reverb', 'bass boosted']:
                            if pt in t and pt not in q_lower:
                                score -= 30
                        if score > best_score:
                            best_score = score
                            best_entry = entry

                    if best_entry and best_entry.get('url'):
                        dur = best_entry.get('duration', 0)
                        dur_sec = int(dur / 1000) if dur > 10000 else int(dur)
                        print(f"[Music] SoundCloud resolved match: {best_entry.get('title')}")
                        return {
                            'title': best_entry.get('title', 'Unknown Track'),
                            'url': best_entry.get('url'),
                            'webpage_url': best_entry.get('permalink_url', best_entry.get('webpage_url', best_entry.get('url'))),
                            'duration': dur_sec,
                            'thumbnail': best_entry.get('thumbnail'),
                            'age_limit': 0,
                            'uploader': best_entry.get('uploader', ''),
                            'channel': 'SoundCloud',
                            'categories': ['Music']
                        }
                return None

            def _extract_yt(target, use_cookies=False):
                is_search = not (target.startswith("http://") or target.startswith("https://"))
                base_opts = {
                    'format': format_chain,
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'geo_bypass': True,
                    'nocheckcertificate': True,
                    'http_headers': DEFAULT_HEADERS,
                    'socket_timeout': 6
                }
                if use_cookies and active_cookie_path:
                    base_opts['cookiefile'] = active_cookie_path

                if not is_search:
                    with yt_dlp.YoutubeDL(base_opts) as ydl:
                        info = ydl.extract_info(target, download=False)
                        entries = info.get('entries', []) if info and 'entries' in info else ([info] if info else [])
                        if entries and entries[0] and entries[0].get('url'):
                            e = entries[0]
                            return {
                                'title': e.get('title', 'Unknown Track'),
                                'url': e.get('url'),
                                'webpage_url': e.get('webpage_url', target),
                                'duration': e.get('duration', 0),
                                'thumbnail': e.get('thumbnail'),
                                'age_limit': e.get('age_limit', 0),
                                'uploader': e.get('uploader', ''),
                                'channel': e.get('channel', ''),
                                'categories': e.get('categories', []),
                            }
                    return None

                clean_query = target.replace('ytsearch1:', '').replace('ytsearch5:', '').strip()
                try:
                    with yt_dlp.YoutubeDL(base_opts) as ydl_direct:
                        res = ydl_direct.extract_info(f"ytsearch1:{clean_query}", download=False)
                        entries = res.get('entries', []) if res else []
                        if entries and entries[0] and entries[0].get('url'):
                            e = entries[0]
                            if not (e.get('age_limit', 0) and e.get('age_limit') > 0):
                                return {
                                    'title': e.get('title', 'Unknown Track'),
                                    'url': e.get('url'),
                                    'webpage_url': e.get('webpage_url') or f"https://www.youtube.com/watch?v={e.get('id')}",
                                    'duration': e.get('duration', 0),
                                    'thumbnail': e.get('thumbnail'),
                                    'age_limit': e.get('age_limit', 0),
                                    'uploader': e.get('uploader', ''),
                                    'channel': e.get('channel', ''),
                                    'categories': e.get('categories', []),
                                }
                except Exception as direct_err:
                    print(f"[Music] Direct ytsearch1 note for '{clean_query}': {direct_err}")

                flat_opts = {
                    'extract_flat': 'in_playlist',
                    'quiet': True,
                    'no_warnings': True,
                    'noplaylist': True,
                    'http_headers': DEFAULT_HEADERS,
                    'socket_timeout': 5
                }
                if use_cookies and active_cookie_path:
                    flat_opts['cookiefile'] = active_cookie_path

                with yt_dlp.YoutubeDL(flat_opts) as ydl:
                    res = ydl.extract_info(f"ytsearch5:{clean_query}", download=False)
                    entries = res.get('entries', []) if res else []
                    if not entries:
                        return None

                    q_lower = clean_query.lower()
                    q_words = [w for w in re.findall(r'\w+', q_lower) if w not in ('song', 'video', 'audio', 'mp3', 'lyrics')]
                    if not q_words:
                        q_words = re.findall(r'\w+', q_lower)

                    best_score = -999
                    best_id = entries[0].get('id')
                    best_entry = entries[0]

                    for entry in entries:
                        t = (entry.get('title') or '').lower()
                        channel = (entry.get('channel') or entry.get('uploader') or '').lower()
                        score = sum(25 for w in q_words if w in t)
                        score += sum(15 for w in q_words if w in channel)

                        for good in ['official', 'vevo', 'audio', 'video', 'coke studio', 't-series', 'sony', 'zee', 'yrf', 'tips']:
                            if good in t or good in channel:
                                score += 20
                        for bad in ['cover', 'remix', 'slowed', 'reverb', 'parody', 'reaction', 'karaoke', 'instrumental', 'status', 'shorts', 'ringtone', '18+', 'nsfw', 'sexy', 'hot scene', 'hot video', 'erotic', 'uncensored']:
                            if bad in t or bad in channel:
                                score -= 50

                        if score > best_score:
                            best_score = score
                            best_id = entry.get('id')
                            best_entry = entry

                if not best_id:
                    return None

                with yt_dlp.YoutubeDL(base_opts) as ydl_stream:
                    info = ydl_stream.extract_info(f"https://www.youtube.com/watch?v={best_id}", download=False)
                    if info and info.get('url'):
                        return {
                            'title': info.get('title', best_entry.get('title', 'Unknown Track')),
                            'url': info.get('url'),
                            'webpage_url': info.get('webpage_url', f"https://www.youtube.com/watch?v={best_id}"),
                            'duration': info.get('duration', 0),
                            'thumbnail': info.get('thumbnail') or best_entry.get('thumbnail'),
                            'age_limit': info.get('age_limit', 0),
                            'uploader': info.get('uploader', ''),
                            'channel': info.get('channel', ''),
                            'categories': info.get('categories', []),
                        }
                return None

            search_title = query
            is_spotify = is_url and any(s in query.lower() for s in ("spotify.com", "spotify.link", "spoti.fi"))
            if is_spotify:
                sp_data = resolve_spotify_url(query)
                if sp_data and sp_data.get("search_query"):
                    search_title = sp_data["search_query"]
                    print(f"[Music] Spotify resolved metadata: '{search_title}'")
                else:
                    try:
                        clean_u = query.split('?')[0]
                        oe = f"https://open.spotify.com/oembed?url={urllib.parse.quote(clean_u)}"
                        req = urllib.request.Request(oe, headers=DEFAULT_HEADERS)
                        with urllib.request.urlopen(req, timeout=5) as r:
                            raw_title = json.loads(r.read().decode()).get('title', '')
                            if raw_title:
                                search_title = raw_title
                                print(f"[Music] Spotify oEmbed fallback resolved: '{search_title}'")
                    except Exception as oe_err:
                        print(f"[Music] Spotify oEmbed note: {oe_err}")

            search_target = query if (is_url and not is_spotify) else search_title

            if active_cookie_path:
                try:
                    res_cookie = _extract_yt(search_target, use_cookies=True)
                    if res_cookie:
                        print(f"[Music] Resolved via YouTube (authenticated): {res_cookie.get('title')}")
                        return res_cookie
                except Exception as e_cook:
                    print(f"[Music] YouTube cookie extraction note: {e_cook}")

            try:
                yt_res = _extract_yt(search_target, use_cookies=False)
                if yt_res:
                    print(f"[Music] Resolved via YouTube: {yt_res.get('title')}")
                    return yt_res
            except Exception as e1:
                print(f"[Music] YouTube extraction note: {e1}")

            indian_keywords = {
                'arijit', 'shreya', 'kumar', 'singh', 'sonu', 'atif', 'badshah', 'neha', 'kakkar',
                'jubin', 'nautiyal', 'diljit', 'dosanjh', 'sidhu', 'moosewala', 'ap dhillon',
                'bollywood', 'hindi', 'punjabi', 'bhojpuri', 'tamil', 'telugu', 'malayalam',
                'b praak', 'anuv jain', 'prateek kuhad', 'darshan raval', 'armaan malik', 'yo yo honey singh'
            }
            q_lower = search_title.lower()
            is_indian = any(k in q_lower for k in indian_keywords)

            if is_spotify or not is_indian:
                try:
                    sc_res = _extract_sc(search_title)
                    if sc_res:
                        print(f"[Music] Resolved via SoundCloud: {sc_res.get('title')}")
                        return sc_res
                except Exception as e2:
                    print(f"[Music] SoundCloud extraction note: {e2}")

                saavn_res = _extract_saavn(search_title)
                if saavn_res:
                    print(f"[Music] Resolved via JioSaavn: {saavn_res.get('title')}")
                    return saavn_res
            else:
                saavn_res = _extract_saavn(search_title)
                if saavn_res:
                    print(f"[Music] Resolved via JioSaavn: {saavn_res.get('title')}")
                    return saavn_res

                try:
                    sc_res = _extract_sc(search_title)
                    if sc_res:
                        print(f"[Music] Resolved via SoundCloud: {sc_res.get('title')}")
                        return sc_res
                except Exception as e2:
                    print(f"[Music] SoundCloud extraction note: {e2}")

            raise Exception("Could not find an audio stream for this track. Please check the song name or provide a direct audio link.")

        return await loop.run_in_executor(None, _extract)

    @staticmethod
    def _extract_accent_color(img_obj: Optional[Image.Image], fallback: Tuple[int, int, int] = (139, 92, 246)) -> Tuple[int, int, int]:
        """Extract vibrant non-muddy RGB accent from wallpaper or album art."""
        if not img_obj:
            return fallback
        try:
            small = img_obj.convert("RGB").resize((60, 40), Image.Resampling.LANCZOS)
            quantized = small.quantize(colors=12).convert("RGB")
            counts: Dict[Tuple[int, int, int], int] = {}
            for px in quantized.getdata():
                counts[px] = counts.get(px, 0) + 1
            best_color = None
            best_score = -1.0
            for color, count in counts.items():
                r, g, b = color
                h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                if v < 0.25 or (s < 0.15 and v > 0.85):
                    continue
                score = s * (0.5 + v * 0.5) * (count ** 0.5)
                if score > best_score:
                    best_score = score
                    best_color = color
            if best_color:
                r, g, b = best_color
                h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                v = max(v, 0.78)
                s = max(s, 0.50)
                rr, gg, bb = colorsys.hsv_to_rgb(h, s, v)
                return (int(rr * 255), int(gg * 255), int(bb * 255))
        except Exception:
            pass
        return fallback

    async def _fetch_song_thumbnail(self, thumb_url: Optional[str], size: int = 204) -> Image.Image:
        """Fetch, center-crop, and round-mask the track thumbnail; fallback to vinyl emblem."""
        if thumb_url and isinstance(thumb_url, str) and thumb_url.startswith(("http://", "https://")):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(thumb_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            raw = Image.open(io.BytesIO(data)).convert("RGBA")
                            # Center-crop square (removes YouTube 16:9 black letterbox bars nicely)
                            w, h = raw.size
                            side = min(w, h)
                            left = (w - side) // 2
                            top = (h - side) // 2
                            cropped = raw.crop((left, top, left + side, top + side))
                            resized = cropped.resize((size, size), Image.Resampling.LANCZOS)
                            mask = Image.new("L", (size, size), 0)
                            ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=20, fill=255)
                            out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                            out.paste(resized, (0, 0), mask)
                            return out
            except Exception:
                pass

        fallback = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fallback)
        fd.rounded_rectangle((0, 0, size - 1, size - 1), radius=20, fill=(30, 34, 46, 255), outline=(139, 92, 246, 200), width=3)
        fd.ellipse((34, 34, size - 34, size - 34), fill=(18, 20, 28, 255), outline=(139, 92, 246, 160), width=2)
        fd.ellipse((size // 2 - 22, size // 2 - 22, size // 2 + 22, size // 2 + 22), fill=(139, 92, 246, 230))
        fd.ellipse((size // 2 - 7, size // 2 - 7, size // 2 + 7, size // 2 + 7), fill=(18, 20, 28, 255))
        return fallback

    async def _get_music_card_base(self, song: Song, guild_id: Optional[int]) -> Tuple[Image.Image, Tuple[int, int, int], Tuple[int, int, int], float, float, float, bool]:
        """Build or reuse cached blurred/dimmed background + album art so 10s ticks stay <10ms."""
        W, H = 860, 260
        gid_str = str(guild_id) if guild_id else ""
        bg_raw_path = getattr(db, "music_card_backgrounds", {}).get(gid_str) if gid_str else None
        bg_path = resolve_music_card_background(bg_raw_path)
        bg_mtime = os.path.getmtime(bg_path) if bg_path and os.path.exists(bg_path) else 0
        thumb_url = getattr(song, "thumbnail", None) or ""
        cache_key = (gid_str, bg_path or "", bg_mtime, thumb_url)

        state = self.get_state(guild_id) if guild_id else None
        cached = state.get("_card_cache") if state else None
        if cached and cached.get("key") == cache_key:
            return (
                cached["base_img"],
                cached["accent_rgb"],
                cached["text_rgb"],
                cached["h"],
                cached["s"],
                cached["v"],
                cached["has_custom_bg"],
            )

        thumb_size = 204
        thumb_img = await self._fetch_song_thumbnail(thumb_url, size=thumb_size)

        raw_bg = None
        bg_img = None
        container_alpha = 160
        if bg_path:
            try:
                loaded = Image.open(bg_path).convert("RGBA")
                ratio = max(W / loaded.width, H / loaded.height)
                nw, nh = int(loaded.width * ratio), int(loaded.height * ratio)
                resized = loaded.resize((nw, nh), Image.Resampling.LANCZOS)
                cx, cy = (nw - W) // 2, (nh - H) // 2
                raw_bg = resized.crop((cx, cy, cx + W, cy + H))
                blurred = raw_bg.filter(ImageFilter.GaussianBlur(radius=4))

                # Auto-dim bright backgrounds so text & progress bar always stay legible
                mean_lum = ImageStat.Stat(raw_bg.convert("L")).mean[0]
                if mean_lum > 140:
                    dim_factor = max(0.55, 0.85 - ((mean_lum - 140) / 180.0))
                    container_alpha = 62
                elif mean_lum > 95:
                    dim_factor = 0.72
                    container_alpha = 48
                else:
                    dim_factor = 0.86
                    container_alpha = 36
                bg_img = ImageEnhance.Brightness(blurred).enhance(dim_factor)
            except Exception:
                raw_bg = bg_img = None

        has_custom_bg = bg_img is not None
        accent_rgb = self._extract_accent_color(raw_bg if raw_bg else thumb_img)
        ar, ag, ab = accent_rgb
        h_a, s_a, v_a = colorsys.rgb_to_hsv(ar / 255.0, ag / 255.0, ab / 255.0)
        tr, tg, tb = colorsys.hsv_to_rgb(h_a, min(s_a, 0.60), max(v_a, 0.96))
        text_rgb = (int(tr * 255), int(tg * 255), int(tb * 255))

        if not bg_img:
            bg_img = Image.new("RGBA", (W, H), (16, 18, 26, 255))
            d_bg = ImageDraw.Draw(bg_img)
            d_bg.ellipse((-70, -70, 260, 260), fill=(ar, ag, ab, 45))
            d_bg.ellipse((W - 220, H - 200, W + 90, H + 90), fill=(ar // 2, ag // 2, ab, 35))

        # Frosted glass outer frame
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        container_fill = (10, 12, 18, container_alpha) if has_custom_bg else (20, 22, 30, 215)
        od.rounded_rectangle(
            (8, 8, W - 8, H - 8),
            radius=22,
            fill=container_fill,
            outline=(text_rgb[0], text_rgb[1], text_rgb[2], 145) if has_custom_bg else (255, 255, 255, 42),
            width=1
        )
        base_img = Image.alpha_composite(bg_img, overlay)

        # Album art glow ring + paste on left
        ax, ay = 28, 28
        glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        gd.rounded_rectangle((ax - 4, ay - 4, ax + thumb_size + 4, ay + thumb_size + 4), radius=24, outline=(ar, ag, ab, 95), width=6)
        glow_blurred = glow_layer.filter(ImageFilter.GaussianBlur(radius=4))
        base_img = Image.alpha_composite(base_img, glow_blurred)
        base_img.paste(thumb_img, (ax, ay), thumb_img)
        bd = ImageDraw.Draw(base_img)
        bd.rounded_rectangle((ax, ay, ax + thumb_size - 1, ay + thumb_size - 1), radius=20, outline=(text_rgb[0], text_rgb[1], text_rgb[2], 220), width=2)

        if state is not None:
            state["_card_cache"] = {
                "key": cache_key,
                "base_img": base_img,
                "accent_rgb": accent_rgb,
                "text_rgb": text_rgb,
                "h": h_a,
                "s": s_a,
                "v": v_a,
                "has_custom_bg": has_custom_bg,
            }

        return base_img, accent_rgb, text_rgb, h_a, s_a, v_a, has_custom_bg

    @staticmethod
    def _draw_shadow_text(draw: ImageDraw.ImageDraw, pos: Tuple[int, int], text: str, font, fill: Tuple[int, int, int, int], glow_color: Optional[Tuple[int, int, int, int]] = None):
        x, y = pos
        if glow_color:
            draw.text((x, y), text, font=font, fill=glow_color, stroke_width=2, stroke_fill=glow_color)
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 210))
        draw.text((x, y), text, font=font, fill=fill)

    @staticmethod
    def _truncate_text_to_width(text: str, font, max_width: int) -> str:
        if not text:
            return "Unknown Track"
        if font.getbbox(text)[2] - font.getbbox(text)[0] <= max_width:
            return text
        lo, hi = 1, len(text)
        best = text[:1]
        while lo <= hi:
            mid = (lo + hi) // 2
            cand = text[:mid].rstrip() + "…"
            w = font.getbbox(cand)[2] - font.getbbox(cand)[0]
            if w <= max_width:
                best = cand
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    async def generate_music_card(self, song: Song, guild_id: Optional[int] = None) -> discord.File:
        """Render the 860x260 frosted-glass Now Playing card with live progress bar and adaptive colors."""
        W, H = 860, 260
        base_img, accent_rgb, text_rgb, h_a, s_a, v_a, has_custom_bg = await self._get_music_card_base(song, guild_id)
        ar, ag, ab = accent_rgb
        tar, tag, tab = text_rgb

        state = self.get_state(guild_id) if guild_id else {}
        vol = state.get("volume", 1.0)
        f_key = state.get("filter", "studio")
        profile = AUDIO_FILTERS.get(f_key, AUDIO_FILTERS["studio"])
        eq_short = profile["name"].split("(")[0].strip()[:18]
        is_loop = bool(state.get("loop", False))
        is_auto = bool(state.get("autoplay", False))
        is_paused = state.get("paused_at") is not None
        if guild_id and self.bot:
            g_obj = self.bot.get_guild(guild_id)
            vc = g_obj.voice_client if g_obj else None
            if vc and vc.is_paused():
                is_paused = True

        duration = int(getattr(song, "duration", 0) or 0)
        elapsed = int(self.get_elapsed_seconds(state, duration)) if state else 0

        img = base_img.copy()
        draw = ImageDraw.Draw(img)

        font_badge = get_unicode_font(12, bold=True)
        font_title = get_unicode_font(25, bold=True)
        font_sub = get_unicode_font(15, bold=False)
        font_meta = get_unicode_font(13, bold=True)
        font_time = get_unicode_font(14, bold=True)

        tx = 256
        right_edge = W - 28
        content_w = right_edge - tx

        # ── Top Pills (Status + Loop/Autoplay on left, Volume + EQ on right) ──
        status_label = "PAUSED" if is_paused else "NOW PLAYING"
        status_rgb = (245, 158, 11) if is_paused else (tar, tag, tab)
        left_pills = [(status_label, status_rgb)]
        if is_loop:
            left_pills.append(("LOOP", (56, 189, 248)))
        if is_auto:
            left_pills.append(("AUTOPLAY", (168, 85, 247)))

        px = tx
        py = 30
        for p_txt, p_col in left_pills:
            bb = font_badge.getbbox(p_txt)
            pw = (bb[2] - bb[0]) + 20
            cr, cg, cb = p_col
            draw.rounded_rectangle((px, py, px + pw, py + 26), radius=13, fill=(cr, cg, cb, 55), outline=(cr, cg, cb, 215), width=1)
            self._draw_shadow_text(draw, (px + 10, py + 6), p_txt, font_badge, (cr, cg, cb, 255))
            px += pw + 8

        right_pills = [
            (f"VOL {int(vol * 100)}%", (253, 224, 71)),
            (f"EQ: {eq_short.upper()}", (186, 230, 253)),
        ]
        rx = right_edge
        for p_txt, p_col in reversed(right_pills):
            bb = font_badge.getbbox(p_txt)
            pw = (bb[2] - bb[0]) + 20
            rpx = rx - pw
            cr, cg, cb = p_col
            draw.rounded_rectangle((rpx, py, rpx + pw, py + 26), radius=13, fill=(cr, cg, cb, 45), outline=(cr, cg, cb, 190), width=1)
            self._draw_shadow_text(draw, (rpx + 10, py + 6), p_txt, font_badge, (cr, cg, cb, 255))
            rx = rpx - 8

        # ── Track Title & Requester Subtitle ──
        raw_title = clean_display_name(getattr(song, "title", "Unknown Track"), max_len=80)
        title_str = self._truncate_text_to_width(raw_title, font_title, content_w)
        # Adaptive title color: bright crisp white with subtle accent glow
        title_fill = (255, 255, 255, 255)
        self._draw_shadow_text(draw, (tx, 76), title_str, font_title, title_fill, glow_color=(ar, ag, ab, 90))

        if getattr(song, "is_autoplay", False):
            req_name = "Autoplay Discovery"
        else:
            req_obj = getattr(song, "requester", None)
            req_name = f"@{clean_display_name(req_obj.display_name, max_len=20)}" if req_obj and hasattr(req_obj, "display_name") else "DJ"

        sub_str = self._truncate_text_to_width(f"Requested by {req_name}  •  48kHz Studio Master", font_sub, content_w)
        sub_col = (210, 232, 255, 245) if has_custom_bg else (175, 185, 202, 255)
        self._draw_shadow_text(draw, (tx, 116), sub_str, font_sub, sub_col)

        # Queue count hint
        q_len = len(state.get("queue", [])) if state else 0
        q_hint = f"{q_len} track{'s' if q_len != 1 else ''} up next in queue" if q_len > 0 else "No tracks queued after this"
        self._draw_shadow_text(draw, (tx, 144), q_hint, font_meta, (tar, tag, tab, 240))

        # ── Live Progress Bar ──
        bar_x = tx
        bar_y = 182
        bar_w = content_w
        bar_h = 16
        bar_r = bar_h // 2

        track_fill = (10, 14, 24, 175) if has_custom_bg else (30, 34, 46, 230)
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=bar_r, fill=track_fill, outline=(tar, tag, tab, 110), width=1)

        if duration > 0:
            ratio = max(0.0, min(1.0, elapsed / duration))
        else:
            ratio = 1.0

        fill_px = max(bar_h, int(bar_w * ratio)) if ratio > 0 else 0
        if fill_px > 0:
            grad = Image.new("RGBA", (fill_px, bar_h), (0, 0, 0, 0))
            gd = ImageDraw.Draw(grad)
            for i in range(fill_px):
                t = i / max(1, fill_px - 1)
                v_g = min(1.0, v_a + (1.0 - v_a) * t * 0.55)
                s_g = s_a * (1.0 - t * 0.25)
                rr, gg, bb = colorsys.hsv_to_rgb(h_a, s_g, v_g)
                gd.line([(i, 0), (i, bar_h - 1)], fill=(int(rr * 255), int(gg * 255), int(bb * 255), 255))
            mask = Image.new("L", (fill_px, bar_h), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, fill_px - 1, bar_h - 1), radius=bar_r, fill=255)
            grad.putalpha(mask)
            img.paste(grad, (bar_x, bar_y), grad)
            draw = ImageDraw.Draw(img)

            # Luminous playhead dot
            kx = min(bar_x + bar_w - bar_r, bar_x + fill_px)
            ky = bar_y + bar_h // 2
            kr = bar_r + 3
            draw.ellipse((kx - kr, ky - kr, kx + kr, ky + kr), fill=(tar, tag, tab, 235))
            draw.ellipse((kx - bar_r + 1, ky - bar_r + 1, kx + bar_r - 1, ky + bar_r - 1), fill=(255, 255, 255, 255))

        # ── Timestamps ──
        e_m, e_s = divmod(elapsed, 60)
        elapsed_str = f"{e_m:02d}:{e_s:02d}"
        if duration > 0:
            d_m, d_s = divmod(duration, 60)
            dur_str = f"{d_m:02d}:{d_s:02d}"
        else:
            dur_str = "LIVE"

        self._draw_shadow_text(draw, (bar_x, 208), elapsed_str, font_time, (255, 255, 255, 255))
        db_box = font_time.getbbox(dur_str)
        self._draw_shadow_text(draw, (bar_x + bar_w - (db_box[2] - db_box[0]), 208), dur_str, font_time, (tar, tag, tab, 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False, compress_level=1)
        buf.seek(0)
        return discord.File(fp=buf, filename="now_playing.png")

    async def refresh_now_playing_card(self, guild_id: int, message: Optional[discord.Message] = None, view: Optional[discord.ui.View] = None):
        """Re-render and edit the Now Playing card in-place without overlapping uploads."""
        state = self.get_state(guild_id)
        current = state.get("current")
        target_msg = message or state.get("np_message")
        if not current or not target_msg or state.get("_updating_card"):
            return
        state["_updating_card"] = True
        try:
            card_file = await self.generate_music_card(current, guild_id)
            kwargs: Dict[str, Any] = {"attachments": [card_file], "embed": None, "content": None}
            if view is not None:
                kwargs["view"] = view
            await target_msg.edit(**kwargs)
        except discord.NotFound:
            if state.get("np_message") == target_msg:
                state["np_message"] = None
        except Exception as e:
            print(f"[Music Card Refresh] Note for guild {guild_id}: {e}")
        finally:
            state["_updating_card"] = False

    @tasks.loop(seconds=10)
    async def music_card_updater(self):
        """Update active music progress bars every 10 seconds while playing."""
        await self.bot.wait_until_ready()
        for gid, state in list(self.states.items()):
            try:
                if state.get("_stopping") or state.get("_switching_filter") or state.get("_updating_card"):
                    continue
                current = state.get("current")
                np_msg = state.get("np_message")
                if not current or not np_msg:
                    continue
                guild = self.bot.get_guild(gid)
                vc = guild.voice_client if guild else None
                if not vc or not vc.is_connected() or not vc.is_playing() or vc.is_paused():
                    continue
                await self.refresh_now_playing_card(gid, message=np_msg)
            except Exception as e:
                print(f"[Music Updater Loop] Guild {gid} note: {e}")

    def create_now_playing_embed(self, song: Song, volume: float = 1.0, guild_id: int = None) -> discord.Embed:
        mins, secs = divmod(song.duration or 0, 60)
        embed = discord.Embed(
            title="◈  NOW PLAYING",
            color=discord.Color.from_rgb(139, 92, 246)
        )
        profile_name = "Studio Master"
        if guild_id:
            state = self.get_state(guild_id)
            f_key = state.get("filter", "studio")
            profile = AUDIO_FILTERS.get(f_key, AUDIO_FILTERS["studio"])
            profile_name = f"{profile['emoji']} {profile['name']}"

        if getattr(song, "is_autoplay", False):
            req_mention = "📻 Autoplay Discovery"
        else:
            req_mention = song.requester.mention if (getattr(song, "requester", None) and hasattr(song.requester, "mention")) else "DJ"
        embed.description = (
            f"• **[{song.title}]({song.webpage_url})**\n"
            f"• ⏱ **Duration:** `{mins:02d}m {secs:02d}s` — ({req_mention})\n"
            f"• ◈ **Volume:** `{int(volume * 100)}%`  •  **EQ:** `{profile_name}`\n"
            f"• 🎚 **Engine:** `48kHz Studio Master (YouTube High-Fidelity Audio)`"
        )
        if song.thumbnail and isinstance(song.thumbnail, str) and song.thumbnail.startswith(("http://", "https://")):
            if not getattr(song, "is_autoplay", False):
                embed.set_thumbnail(url=song.thumbnail)
        embed.set_footer(text="Friday Studio Audio • 48kHz Stereo Master Engine • Pure High-Fidelity")
        return embed

    def play_next(self, guild_id: int):
        """Thread-safe entry point called from FFmpeg's after_play thread."""
        asyncio.run_coroutine_threadsafe(self._play_next_async(guild_id), self.bot.loop)

    async def _play_next_async(self, guild_id: int):
        state = self.get_state(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not guild or not guild.voice_client or not guild.voice_client.is_connected():
            state["current"] = None
            state["transformer"] = None
            return

        vc = guild.voice_client

        if state.get("_stopping"):
            state["_stopping"] = False
            state["current"] = None
            state["transformer"] = None
            return

        if state.get("loop") and state.get("current"):
            next_song = state["current"]
            print(f"[Music Debug] Loop mode repeating track: {next_song.title}")
        elif state["queue"]:
            next_song = state["queue"].pop(0)
            state["current"] = next_song
        elif state.get("autoplay") and (state.get("last_played") or state.get("current")):
            last_song = state.get("last_played") or state.get("current")
            state["last_played"] = last_song
            state["current"] = None
            state["transformer"] = None
            asyncio.create_task(self.ensure_autoplay_queued(guild_id))
            return
        else:
            state["current"] = None
            state["transformer"] = None
            if vc and vc.channel:
                await self.clear_voice_channel_status(vc.channel)
            return

        def after_play(err):
            if state.get("_switching_filter") or state.get("_stopping"):
                state["_stopping"] = False
                return
            if err:
                print(f"[Music Debug] Track '{next_song.title}' ended with note: {err}")
            self.play_next(guild_id)

        try:
            # Lazily resolve saved playlist / deferred webpage URLs into live audio stream URLs
            if not next_song.url or next_song.url == next_song.webpage_url:
                target_query = next_song.webpage_url or next_song.title
                info = await self.extract_audio_info(target_query)
                if info and info.get("url"):
                    next_song.url = info["url"]
                    if not next_song.thumbnail:
                        next_song.thumbnail = info.get("thumbnail")
                    if not next_song.duration:
                        next_song.duration = info.get("duration", 0)
                    state["_card_cache"] = None

            vol = state.get("volume", 1.0)
            ffmpeg_opts = self.get_ffmpeg_options(guild_id)
            raw_source = discord.FFmpegPCMAudio(next_song.url, **ffmpeg_opts)
            source = discord.PCMVolumeTransformer(raw_source, volume=vol)
            state["transformer"] = source

            if vc.ws:
                try:
                    await vc.ws.speak(discord.SpeakingState.voice)
                except Exception:
                    pass

            if vc.is_playing():
                try:
                    vc.stop()
                except Exception:
                    pass

            self.reset_track_timer(state)
            state["last_played"] = next_song
            history = state.setdefault("autoplay_history", [])
            if next_song.title not in history:
                history.append(next_song.title)
                if len(history) > 50:
                    history.pop(0)

            if vc and vc.channel:
                status_title = f"✦ {next_song.title}"[:48]
                asyncio.create_task(self.set_voice_channel_status(vc.channel, status_title))

            vc.play(source, after=after_play)
            if state.get("autoplay") and not state.get("queue"):
                asyncio.create_task(self.ensure_autoplay_queued(guild_id))

            if state["channel"]:
                view = MusicControlView(self, guild_id)

                old_msg = state.get("np_message")
                if old_msg:
                    try:
                        await old_msg.delete()
                    except Exception:
                        pass

                try:
                    card_file = await self.generate_music_card(next_song, guild_id)
                    msg = await state["channel"].send(file=card_file, view=view)
                    state["np_message"] = msg
                except Exception as e:
                    print(f"[Music] Card render note, using embed fallback: {e}")
                    try:
                        embed = self.create_now_playing_embed(next_song, vol, guild_id)
                        msg = await state["channel"].send(embed=embed, view=view)
                        state["np_message"] = msg
                    except Exception as e2:
                        print(f"[Music] Fallback Now Playing send failed: {e2}")
        except Exception as e:
            print(f"[Music] Playback error on '{next_song.title}': {e}. Attempting stream refresh...")
            if not getattr(next_song, "_refreshed", False):
                next_song._refreshed = True
                try:
                    fresh_info = await self.extract_audio_info(next_song.webpage_url or next_song.title)
                    next_song.url = fresh_info['url']
                    state["queue"].insert(0, next_song)
                except Exception as ref_err:
                    print(f"[Music] Stream refresh failed for '{next_song.title}': {ref_err}")
            self.play_next(guild_id)

    # ───────────────────── Slash Commands ─────────────────────

    async def ensure_voice_connection(self, interaction: discord.Interaction) -> tuple:
        user_voice = interaction.user.voice
        if not user_voice or not user_voice.channel:
            msg = self.get_resp(interaction.guild_id, "music_not_in_vc", "❌ You must be connected to a voice channel first!")
            return None, msg

        channel = user_voice.channel
        bot_member = interaction.guild.me
        perms = channel.permissions_for(bot_member)

        if not perms.connect:
            return None, f"❌ Friday lacks permission to **Connect** to {channel.mention}!"

        warning = None
        if not perms.speak:
            warning = f"⚠️ **Permission Notice**: Friday lacks the **Speak** permission in {channel.mention}! Please grant Friday's role the **Speak** permission in this channel's settings so members can hear music."

        vc = interaction.guild.voice_client

        if vc and not vc.is_connected():
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
            vc = None

        if not vc:
            try:
                vc = await channel.connect(reconnect=True, self_deaf=False)
                await asyncio.sleep(0.4)
            except Exception as e:
                return None, f"❌ Failed to connect to {channel.mention}: {e}"
        elif vc.channel.id != channel.id:
            try:
                await vc.move_to(channel)
                await asyncio.sleep(0.3)
            except Exception as e:
                return None, f"❌ Failed to move to {channel.mention}: {e}"

        if bot_member.voice:
            if bot_member.voice.mute:
                mute_warn = "⚠️ **Server Mute**: Friday is currently **Server-Muted** in this server! An administrator must right-click Friday and uncheck 'Server Mute' for audio to be heard."
                warning = f"{warning}\n{mute_warn}" if warning else mute_warn
            if bot_member.voice.suppress:
                suppress_warn = "⚠️ **Stage Suppression**: Friday is in a Stage channel as an audience listener! Please invite Friday to Speak."
                warning = f"{warning}\n{suppress_warn}" if warning else suppress_warn

        return vc, warning

    @app_commands.command(name="join", description="Make Friday join your current voice channel.")
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            msg = self.get_resp(interaction.guild_id, "music_not_in_vc", "You must be connected to a voice channel first.")
            await reply_box(interaction, msg, title="VOICE CHANNEL REQUIRED", status="warning", ephemeral=True)
            return

        await interaction.response.defer()

        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        already_in_same = (vc and vc.is_connected() and vc.channel.id == channel.id)

        vc, warn = await self.ensure_voice_connection(interaction)
        if not vc:
            await reply_box(interaction, warn or "Could not connect to voice channel.", title="CONNECTION FAILED", status="danger")
            return

        if already_in_same:
            msg = self.get_resp(interaction.guild_id, "music_already_connected", "Already connected to **{channel}**.", channel=channel.name)
        else:
            msg = self.get_resp(interaction.guild_id, "music_connected", "Connected to **{channel}**. Ready to stream high-fidelity audio.", channel=channel.name)

        if warn:
            msg = f"{msg}\n\n{warn}"
        await reply_box(interaction, msg, title="VOICE CONNECTED", status="success")

    @app_commands.command(name="leave", description="Make Friday stop playback and leave the voice channel.")
    async def leave(self, interaction: discord.Interaction):
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        state = self.get_state(interaction.guild.id)
        state["_stopping"] = True
        state["loop"] = False
        state["queue"].clear()
        state["current"] = None
        state["transformer"] = None

        if vc and vc.is_connected():
            if vc.channel:
                await self.clear_voice_channel_status(vc.channel)
            await vc.disconnect()
            msg = self.get_resp(interaction.guild_id, "music_disconnected", "Disconnected from voice channel.")
            await reply_box(interaction, msg, title="VOICE DISCONNECTED", status="info")
        else:
            msg = self.get_resp(interaction.guild_id, "music_bot_not_in_vc", "Friday is not connected to any voice channel.")
            await reply_box(interaction, msg, title="NOT CONNECTED", status="warning")

    @app_commands.command(name="soundtest", description="Play a 2-second studio test chime to verify voice channel audio output.")
    async def soundtest(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await reply_box(interaction, "You must be connected to a voice channel first.", title="VOICE CHANNEL REQUIRED", status="warning", ephemeral=True)
            return

        await interaction.response.defer()
        vc, warn = await self.ensure_voice_connection(interaction)
        if not vc:
            await reply_box(interaction, warn or "Could not connect to voice channel.", title="CONNECTION FAILED", status="danger")
            return

        if warn:
            await interaction.channel.send(warn)

        chime_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chime.mp3")
        if not os.path.exists(chime_path):
            await reply_box(interaction, "Sound test audio asset not found.", title="SOUNDTEST FAILED", status="danger")
            return

        if vc.is_playing() or vc.is_paused():
            vc.stop()

        try:
            if vc.ws:
                try:
                    await vc.ws.speak(discord.SpeakingState.voice)
                except Exception:
                    pass
            source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(chime_path), volume=1.5)
            vc.play(source)
            await reply_box(interaction, "Streaming 2-second studio test chime now.\nIf you hear the audio, voice transmission is 100% operational.", title="STUDIO SOUNDTEST", status="success")
        except Exception as e:
            await reply_box(interaction, f"Sound test streaming error: {e}", title="SOUNDTEST ERROR", status="danger")

    @app_commands.command(name="play", description="Play a song in VC with live search autocomplete.")
    @app_commands.describe(music="Name of the song, artist, or URL to play")
    async def play(self, interaction: discord.Interaction, music: str):
        if not interaction.user.voice or not interaction.user.voice.channel:
            msg = self.get_resp(interaction.guild_id, "music_not_in_vc", "You must join a voice channel first.")
            await reply_box(interaction, msg, title="VOICE CHANNEL REQUIRED", status="warning", ephemeral=True)
            return

        await interaction.response.defer()

        vc, warn = await self.ensure_voice_connection(interaction)
        if not vc:
            await reply_box(interaction, warn or "Could not connect to voice channel.", title="CONNECTION FAILED", status="danger")
            return

        if warn:
            await interaction.channel.send(warn)

        state = self.get_state(interaction.guild.id)
        state["channel"] = interaction.channel
        state["_stopping"] = False
        if not vc.is_playing() and not vc.is_paused() and not state.get("queue"):
            state["loop"] = False

        spotify_batch = None
        if any(s in music.lower() for s in ("spotify.com", "spotify.link", "spoti.fi")):
            sp_res = await asyncio.to_thread(resolve_spotify_url, music)
            if sp_res:
                if sp_res.get("type") in ("playlist", "album") and sp_res.get("tracks"):
                    tracks = sp_res["tracks"]
                    coll_title = sp_res.get("title", "Spotify Collection")
                    coll_type = sp_res.get("type", "playlist").title()
                    await interaction.followup.send(f"📑 Loading **{len(tracks)} tracks** from Spotify {coll_type}: **{coll_title}**...")
                    music = tracks[0]["search_query"]
                    if len(tracks) > 1:
                        spotify_batch = tracks[1:]
                elif sp_res.get("type") == "track" and sp_res.get("search_query"):
                    music = sp_res["search_query"]

        try:
            song_info = await self.extract_audio_info(music)
        except Exception as e:
            await reply_box(
                interaction,
                f"Could not retrieve audio for **{music}**.\n\n`{e}`",
                title="AUDIO RETRIEVAL FAILED",
                status="danger"
            )
            return

        song = Song(
            title=song_info['title'],
            url=song_info['url'],
            webpage_url=song_info['webpage_url'],
            duration=song_info['duration'],
            requester=interaction.user,
            thumbnail=song_info.get('thumbnail')
        )

        if vc.is_playing() or vc.is_paused():
            pos = self.enqueue_user_song(state, song)
            mins, secs = divmod(song.duration or 0, 60)
            embed = discord.Embed(
                title="◈  ADDED TO QUEUE",
                description=f"• **[{song.title}]({song.webpage_url})**\n• ◈ **Position:** `#{pos}`  •  ◷ **Duration:** `{mins:02d}m {secs:02d}s`\n• ◈ **Requested by:** {interaction.user.mention}",
                color=discord.Color.from_rgb(139, 92, 246)
            )
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)
            embed.set_footer(text=f"Queue length: {pos} tracks • Friday High-Fidelity Audio")
            view = QueueItemView(self, interaction.guild.id, song)
            await interaction.followup.send(embed=embed, view=view)
        else:
            state["current"] = song

            def after_play(err):
                if state.get("_switching_filter") or state.get("_stopping"):
                    state["_stopping"] = False
                    return
                print(f"[Music Debug] Track '{song.title}' ended. Error: {err}")
                if err:
                    if state.get("channel"):
                        asyncio.run_coroutine_threadsafe(
                            state["channel"].send(f"⚠️ Audio stream notice: `{err}`"),
                            self.bot.loop
                        )
                self.play_next(interaction.guild.id)

            try:
                vol = state.get("volume", 1.0)
                ffmpeg_opts = self.get_ffmpeg_options(interaction.guild.id)
                raw_source = discord.FFmpegPCMAudio(song.url, **ffmpeg_opts)
                source = discord.PCMVolumeTransformer(raw_source, volume=vol)
                state["transformer"] = source

                if vc.ws:
                    try:
                        await vc.ws.speak(discord.SpeakingState.voice)
                    except Exception:
                        pass

                if vc.is_playing():
                    try:
                        vc.stop()
                    except Exception:
                        pass

                self.reset_track_timer(state)
                state["last_played"] = song
                vc.play(source, after=after_play)
                if state.get("autoplay") and not state.get("queue"):
                    asyncio.create_task(self.ensure_autoplay_queued(interaction.guild.id))

                if vc and vc.channel:
                    status_title = f"♪ {song.title}"[:48]
                    asyncio.create_task(self.set_voice_channel_status(vc.channel, status_title))

                view = MusicControlView(self, interaction.guild.id)
                old_msg = state.get("np_message")
                if old_msg:
                    try:
                        await old_msg.delete()
                    except Exception:
                        pass

                try:
                    card_file = await self.generate_music_card(song, interaction.guild.id)
                    msg = await interaction.followup.send(file=card_file, view=view)
                    state["np_message"] = msg
                except Exception as card_err:
                    print(f"[Music] Card render fallback in /play: {card_err}")
                    embed = self.create_now_playing_embed(song, vol, interaction.guild.id)
                    msg = await interaction.followup.send(embed=embed, view=view)
                    state["np_message"] = msg
            except Exception as e:
                await reply_box(interaction, f"Error initializing audio stream: {e}", title="STREAM ERROR", status="danger")
                self.play_next(interaction.guild.id)

        if spotify_batch:
            asyncio.create_task(self._enqueue_spotify_batch(interaction.guild.id, spotify_batch, interaction.user))

    async def _enqueue_spotify_batch(self, guild_id: int, tracks: list, requester: discord.Member):
        state = self.get_state(guild_id)
        for t in tracks[:50]:
            if state.get("_stopping"):
                break
            try:
                info = await self.extract_audio_info(t["search_query"])
                if info:
                    song = Song(
                        title=info['title'],
                        url=info['url'],
                        webpage_url=info['webpage_url'],
                        duration=info['duration'],
                        requester=requester,
                        thumbnail=info.get('thumbnail')
                    )
                    self.enqueue_user_song(state, song)
                    print(f"[Music] Enqueued Spotify batch track: '{song.title}' (queue: {len(state['queue'])})")
            except Exception as e:
                print(f"[Music] Spotify batch track error for '{t.get('title')}': {e}")
            await asyncio.sleep(0.5)

    @play.autocomplete('music')
    async def play_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.fetch_suggestions(current)

    @app_commands.command(name="skip", description="Skip the currently playing song.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            msg = self.get_resp(interaction.guild_id, "music_nothing_playing", "Nothing is currently playing.")
            await reply_box(interaction, msg, title="PLAYBACK", status="warning", ephemeral=True)
            return

        asyncio.get_event_loop().run_in_executor(None, vc.stop)
        msg = self.get_resp(interaction.guild_id, "music_skipped", "Skipped current track to the next song in queue.")
        await reply_box(interaction, msg, title="TRACK SKIPPED", status="info")

    @app_commands.command(name="shuffle", description="Shuffle all songs in the playback queue.")
    async def shuffle(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild.id)
        if len(state["queue"]) < 2:
            await reply_box(interaction, "At least 2 songs are required in queue to shuffle.", title="QUEUE SHUFFLE", status="warning", ephemeral=True)
            return

        random.shuffle(state["queue"])
        await reply_box(interaction, f"Reordered {len(state['queue'])} upcoming tracks randomly.", title="QUEUE SHUFFLED", status="info")

    @app_commands.command(name="pause", description="Pause current music playback.")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            state = self.get_state(interaction.guild.id)
            self.mark_paused(state)
            await self.refresh_now_playing_card(interaction.guild.id, view=MusicControlView(self, interaction.guild.id))
            msg = self.get_resp(interaction.guild_id, "music_paused", "Music playback paused.")
            await reply_box(interaction, msg, title="PLAYBACK PAUSED", status="info")
        else:
            msg = self.get_resp(interaction.guild_id, "music_nothing_playing", "No active track is currently playing.")
            await reply_box(interaction, msg, title="PLAYBACK", status="warning", ephemeral=True)

    @app_commands.command(name="resume", description="Resume paused music playback.")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            state = self.get_state(interaction.guild.id)
            self.mark_resumed(state)
            await self.refresh_now_playing_card(interaction.guild.id, view=MusicControlView(self, interaction.guild.id))
            msg = self.get_resp(interaction.guild_id, "music_resumed", "Music playback resumed.")
            await reply_box(interaction, msg, title="PLAYBACK RESUMED", status="success")
        else:
            await reply_box(interaction, "Music is not currently paused.", title="PLAYBACK", status="warning", ephemeral=True)

    @app_commands.command(name="volume", description="Adjust playback volume (1% to 200%).")
    @app_commands.describe(percent="Volume percentage between 1 and 200")
    async def volume_cmd(self, interaction: discord.Interaction, percent: int):
        if percent < 1 or percent > 200:
            await reply_box(interaction, "Please specify a volume percentage between 1% and 200%.", title="INVALID VOLUME", status="warning", ephemeral=True)
            return

        state = self.get_state(interaction.guild.id)
        new_vol = round(percent / 100.0, 2)
        state["volume"] = new_vol
        transformer = state.get("transformer")
        if transformer:
            transformer.volume = new_vol
        await self.refresh_now_playing_card(interaction.guild.id)

        await reply_box(interaction, f"Master volume adjusted to **{percent}%**.", title="VOLUME ADJUSTED", status="info")

    @app_commands.command(name="queue", description="View the current music queue.")
    async def queue_cmd(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild.id)
        current = state.get("current")
        queue = state.get("queue", [])

        if not current and not queue:
            msg = self.get_resp(interaction.guild_id, "music_queue_empty", "The playback queue is currently empty.")
            await reply_box(interaction, msg, title="QUEUE EMPTY", status="info", ephemeral=True)
            return

        embed = discord.Embed(
            title="◈  PLAYBACK QUEUE",
            color=discord.Color.from_rgb(139, 92, 246)
        )
        if current:
            mins, secs = divmod(current.duration or 0, 60)
            if getattr(current, "is_autoplay", False):
                cur_req = "📻 Autoplay Discovery"
            else:
                cur_req = current.requester.mention if (getattr(current, "requester", None) and hasattr(current.requester, "mention")) else "DJ"
            embed.add_field(
                name="▶ Current Track",
                value=f"• **[{current.title}]({current.webpage_url})**\n  ⏱ `{mins:02d}m {secs:02d}s` • Requested by: {cur_req}",
                inline=False
            )

        if queue:
            lines = []
            for idx, s in enumerate(queue[:10], start=1):
                mins, secs = divmod(s.duration or 0, 60)
                if getattr(s, "is_autoplay", False):
                    s_req = "📻 Autoplay"
                else:
                    s_req = s.requester.mention if (getattr(s, "requester", None) and hasattr(s.requester, "mention")) else "DJ"
                lines.append(f"`{idx}.` **[{s.title}]({s.webpage_url})** (`{mins:02d}:{secs:02d}`) — {s_req}")
            if len(queue) > 10:
                lines.append(f"*... and {len(queue) - 10} more songs in queue*")
            embed.add_field(name="Upcoming in Queue", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Upcoming in Queue", value="*No upcoming songs. Use `/play` to add more!*", inline=False)

        embed.set_footer(text=f"Total: {len(queue) + (1 if current else 0)} tracks • Friday High-Fidelity Audio")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="likes", description="View your saved liked tracks.")
    async def likes_cmd(self, interaction: discord.Interaction):
        uid_str = str(interaction.user.id)
        user_likes = db.liked_songs.get(uid_str, [])

        if not user_likes:
            await reply_box(interaction, "You have not saved any tracks yet.\nClick the **Like** button on any active player to save songs here.", title="SAVED FAVORITES", status="info", ephemeral=True)
            return

        lines = []
        for idx, item in enumerate(user_likes[:15], start=1):
            dur = item.get("duration", 0)
            mins, secs = divmod(dur or 0, 60)
            lines.append(f"`{idx}.` **[{item['title']}]({item['url']})** (`{mins:02d}:{secs:02d}`)")

        if len(user_likes) > 15:
            lines.append(f"*... and {len(user_likes) - 15} more saved favorites*")

        embed = discord.Embed(
            title=f"◈  {interaction.user.display_name.upper()}'S SAVED FAVORITES",
            description="\n".join(lines),
            color=discord.Color.from_rgb(16, 185, 129)
        )
        embed.set_footer(text=f"Total: {len(user_likes)} favorites • Friday Audio Studio")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="stop", description="Stop music and clear the queue.")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        state = self.get_state(interaction.guild.id)
        state["_stopping"] = True
        state["loop"] = False
        state["queue"].clear()
        state["current"] = None
        state["transformer"] = None

        if vc and (vc.is_playing() or vc.is_paused()):
            if vc.channel:
                await self.clear_voice_channel_status(vc.channel)
            asyncio.get_event_loop().run_in_executor(None, vc.stop)
            msg = self.get_resp(interaction.guild_id, "music_stopped", "Playback stopped and queue cleared.")
            await reply_box(interaction, msg, title="PLAYBACK STOPPED", status="danger")
        else:
            if vc and vc.channel:
                await self.clear_voice_channel_status(vc.channel)
            msg = self.get_resp(interaction.guild_id, "music_nothing_playing", "Nothing was currently playing.")
            await reply_box(interaction, msg, title="PLAYBACK STOPPED", status="info")

    @app_commands.command(name="filter", description="Set audio equalization and mastering profile in real time.")
    @app_commands.describe(preset="Select an audio mastering profile")
    @app_commands.choices(preset=[
        app_commands.Choice(name="🎧 Studio Master (Spotify Premium Tuned)", value="studio"),
        app_commands.Choice(name="🔊 Bass Boost (Punchy Sub-Bass)", value="bassboost"),
        app_commands.Choice(name="🎙️ Vocal / Acoustic Boost", value="vocal"),
        app_commands.Choice(name="🌙 Nightcore (Fast & High Pitch)", value="nightcore"),
        app_commands.Choice(name="☕ Lo-Fi (Warm Analog Chill)", value="lofi"),
        app_commands.Choice(name="🎼 Treble Boost (Crisp Highs)", value="treble"),
        app_commands.Choice(name="🌀 8D Spatial Audio (Surround)", value="8d"),
        app_commands.Choice(name="⚡ Flat / Pure Raw (No EQ)", value="flat"),
    ])
    async def filter_cmd(self, interaction: discord.Interaction, preset: str):
        state = self.get_state(interaction.guild.id)
        state["filter"] = preset
        profile = AUDIO_FILTERS.get(preset, AUDIO_FILTERS["studio"])

        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()) and state.get("current"):
            current = state["current"]
            vol = state.get("volume", 1.0)

            elapsed = int(self.get_elapsed_seconds(state, current.duration or 0))
            ss_pos = max(0, elapsed - 1)

            state["_switching_filter"] = True
            vc.stop()
            state["_switching_filter"] = False

            ffmpeg_opts = self.get_ffmpeg_options(interaction.guild.id, seek_seconds=ss_pos)
            raw_source = discord.FFmpegPCMAudio(current.url, **ffmpeg_opts)
            source = discord.PCMVolumeTransformer(raw_source, volume=vol)
            state["transformer"] = source

            if vc.ws:
                try:
                    asyncio.run_coroutine_threadsafe(vc.ws.speak(discord.SpeakingState.voice), self.bot.loop)
                except Exception:
                    pass

            def after_play(err):
                if state.get("_switching_filter") or state.get("_stopping"):
                    state["_stopping"] = False
                    return
                self.play_next(interaction.guild.id)

            self.reset_track_timer(state, seek_seconds=ss_pos)
            vc.play(source, after=after_play)

            await self.refresh_now_playing_card(interaction.guild.id)

            mins, secs = divmod(ss_pos, 60)
            await reply_box(
                interaction,
                f"DSP mastering switched to **{profile['name']}**.\n\n*{profile['description']}*\n• Resumed in real time at `{mins:02d}:{secs:02d}` without restarting track.",
                title="EQ FILTER APPLIED",
                status="success"
            )
        else:
            await reply_box(
                interaction,
                f"Master profile set to **{profile['name']}**.\n*{profile['description']}*\nWill apply to the next track played.",
                title="EQ FILTER PRESET",
                status="info"
            )

    @app_commands.command(name="autoplay", description="Toggle intelligent music autoplay matching current track mood & language.")
    async def autoplay_cmd(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        new_status = not state.get("autoplay", False)
        state["autoplay"] = new_status

        if new_status:
            asyncio.create_task(self.ensure_autoplay_queued(interaction.guild_id))
            desc = "Friday will intelligently analyze each track's mood, language, and artist to seamlessly pre-fetch and stream matching songs! 🌸"
        else:
            state["queue"] = [s for s in state.get("queue", []) if not getattr(s, "is_autoplay", False)]
            desc = "Autoplay disabled. Playback will stop once the current queue finishes."
        await reply_box(
            interaction,
            desc,
            title=f"AUTOPLAY {'ENABLED' if new_status else 'DISABLED'}",
            status="audio"
        )

    playlist_group = app_commands.Group(name="playlist", description="Manage and play personal music playlists")

    @playlist_group.command(name="add", description="Add a track to your personal playlist (or current playing track if omitted).")
    @app_commands.describe(
        name="Name of your playlist (e.g. Favorites, Gym, Sad Melodies, Bollywood)",
        music="Song title, artist, or URL (optional; if omitted, saves the currently playing song in VC)"
    )
    async def playlist_add(self, interaction: discord.Interaction, name: str, music: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        clean_name = name.strip()[:40]
        if not clean_name:
            return await interaction.followup.send("❌ Please provide a valid playlist name.", ephemeral=True)

        uid = str(interaction.user.id)
        user_pls = db.playlists.setdefault(uid, {})
        existing_name = resolve_user_playlist_name(user_pls, clean_name)
        target_name = existing_name or clean_name
        pl_tracks = user_pls.setdefault(target_name, [])

        if len(pl_tracks) >= 150:
            return await interaction.followup.send(f"◈ Playlist **{target_name}** is at maximum capacity (150 tracks).", ephemeral=True)

        song_to_add = None
        if music:
            try:
                info = await self.extract_audio_info(music)
                song_to_add = {
                    "title": info["title"],
                    "url": info["webpage_url"],
                    "duration": info.get("duration", 0)
                }
            except Exception as e:
                return await interaction.followup.send(f"◈ Could not resolve audio for `{music}`: {e}", ephemeral=True)
        else:
            state = self.get_state(interaction.guild_id)
            current = state.get("current")
            if not current:
                return await interaction.followup.send("◈ No track is currently playing in VC. Please specify a song name or URL: `/playlist add name:<name> music:<song>`.", ephemeral=True)
            song_to_add = {
                "title": current.title,
                "url": current.webpage_url,
                "duration": current.duration
            }

        if any(item.get("url") == song_to_add["url"] for item in pl_tracks):
            return await interaction.followup.send(f"◈ **[{song_to_add['title']}]({song_to_add['url']})** is already inside playlist **{target_name}**.", ephemeral=True)

        pl_tracks.append(song_to_add)
        db.active_playlists[uid] = target_name
        db.save_data()

        embed = make_box_embed(
            title="Playlist Updated",
            description=f"Saved **[{song_to_add['title']}]({song_to_add['url']})** into playlist **{target_name}**!\nTotal tracks in `{target_name}`: **{len(pl_tracks)}**\n*Play it anytime using `/playlist play`.*",
            status="success"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @playlist_group.command(name="play", description="Enqueue all tracks from your personal playlist into the voice channel.")
    @app_commands.describe(name="Name of your saved playlist")
    async def playlist_play(self, interaction: discord.Interaction, name: str):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await reply_box(interaction, "You must join a voice channel first.", title="VOICE CHANNEL REQUIRED", status="warning", ephemeral=True)

        await interaction.response.defer()
        uid = str(interaction.user.id)
        user_pls = db.playlists.get(uid, {})
        canonical = resolve_user_playlist_name(user_pls, name)
        pl_tracks = user_pls.get(canonical) if canonical else None

        if not pl_tracks:
            return await reply_box(interaction, f"Playlist **{name.strip()}** not found or is empty. Use `/playlist list` to see your playlists.", title="PLAYLIST EMPTY", status="error", ephemeral=True)

        vc, warn = await self.ensure_voice_connection(interaction)
        if not vc:
            return await reply_box(interaction, warn or "Could not connect to voice channel.", title="CONNECTION FAILED", status="danger")

        state = self.get_state(interaction.guild_id)
        state["channel"] = interaction.channel
        state["_stopping"] = False

        added = 0
        for item in pl_tracks:
            song = Song(
                title=item["title"],
                url=item["url"],
                webpage_url=item["url"],
                duration=item.get("duration", 0),
                requester=interaction.user
            )
            self.enqueue_user_song(state, song)
            added += 1

        if not vc.is_playing() and not vc.is_paused():
            self.play_next(interaction.guild_id)

        embed = make_box_embed(
            title="Playlist Loaded",
            description=f"Enqueued **{added} tracks** from playlist **{canonical}** into the queue!\nUse `/queue` to view upcoming songs.",
            status="audio"
        )
        await interaction.followup.send(embed=embed)

    @playlist_group.command(name="list", description="List all your saved personal playlists.")
    async def playlist_list(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        user_pls = db.playlists.get(uid, {})

        if not user_pls:
            return await reply_box(interaction, "You haven't created any playlists yet.\nCreate one with `/playlist add name:<name> music:<song>` or click **Save to Playlist** on any player card!", title="NO PLAYLISTS", status="info", ephemeral=True)

        lines = []
        for idx, (p_name, tracks) in enumerate(user_pls.items(), start=1):
            lines.append(f"`{idx}.` ◈ **{p_name}** — `{len(tracks)} songs`")

        embed = discord.Embed(
            title="◈  Your Personal Playlists",
            description="\n".join(lines),
            color=discord.Color.from_rgb(139, 92, 246)
        )
        embed.set_footer(text=f"Total: {len(user_pls)} playlists • Friday Audio Studio")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @playlist_group.command(name="view", description="View songs inside a specific personal playlist.")
    @app_commands.describe(name="Playlist name")
    async def playlist_view(self, interaction: discord.Interaction, name: str):
        uid = str(interaction.user.id)
        user_pls = db.playlists.get(uid, {})
        canonical = resolve_user_playlist_name(user_pls, name)
        tracks = user_pls.get(canonical) if canonical else None

        if not tracks:
            return await reply_box(interaction, f"Playlist **{name.strip()}** does not exist or is empty.", title="PLAYLIST EMPTY", status="error", ephemeral=True)

        lines = []
        for idx, t in enumerate(tracks[:20], start=1):
            dur = t.get("duration", 0)
            mins, secs = divmod(dur, 60)
            time_str = f" (`{mins:02d}:{secs:02d}`)" if dur else ""
            lines.append(f"`{idx}.` **[{t['title']}]({t['url']})**{time_str}")

        if len(tracks) > 20:
            lines.append(f"*... and {len(tracks) - 20} more tracks*")

        embed = discord.Embed(
            title=f"◈  Playlist: {canonical}",
            description="\n".join(lines),
            color=discord.Color.from_rgb(16, 185, 129)
        )
        embed.set_footer(text=f"Total: {len(tracks)} songs • Play with /playlist play")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @playlist_group.command(name="remove", description="Remove a track from a playlist by index.")
    @app_commands.describe(name="Playlist name", track_number="Song number from /playlist view")
    async def playlist_remove(self, interaction: discord.Interaction, name: str, track_number: int):
        uid = str(interaction.user.id)
        user_pls = db.playlists.get(uid, {})
        canonical = resolve_user_playlist_name(user_pls, name)
        tracks = user_pls.get(canonical) if canonical else None

        if not tracks:
            return await reply_box(interaction, f"Playlist **{name.strip()}** does not exist.", title="PLAYLIST NOT FOUND", status="error", ephemeral=True)

        if track_number < 1 or track_number > len(tracks):
            return await reply_box(interaction, f"Invalid track number. Please enter a number between 1 and {len(tracks)}.", title="INVALID INDEX", status="warning", ephemeral=True)

        removed = tracks.pop(track_number - 1)
        db.save_data()
        await reply_box(interaction, f"Removed **{removed['title']}** from playlist **{canonical}**.\nRemaining tracks: **{len(tracks)}**", title="TRACK REMOVED", status="success", ephemeral=True)

    @playlist_group.command(name="delete", description="Delete an entire playlist.")
    @app_commands.describe(name="Playlist name to delete")
    async def playlist_delete(self, interaction: discord.Interaction, name: str):
        uid = str(interaction.user.id)
        user_pls = db.playlists.get(uid, {})
        canonical = resolve_user_playlist_name(user_pls, name)

        if not canonical or canonical not in user_pls:
            return await reply_box(interaction, f"Playlist **{name.strip()}** not found.", title="PLAYLIST NOT FOUND", status="error", ephemeral=True)

        del user_pls[canonical]
        if db.active_playlists.get(uid) == canonical:
            if user_pls:
                db.active_playlists[uid] = list(user_pls.keys())[-1]
            else:
                db.active_playlists.pop(uid, None)
        db.save_data()
        await reply_box(interaction, f"Deleted playlist **{canonical}** permanently.", title="PLAYLIST DELETED", status="success", ephemeral=True)

    async def _playlist_name_autocomplete(self, interaction: discord.Interaction, current: str):
        uid = str(interaction.user.id)
        user_pls = db.playlists.get(uid, {})
        q = (current or "").strip().lower()
        choices = []
        for p_name, tracks in user_pls.items():
            if not q or q in p_name.lower():
                choices.append(app_commands.Choice(
                    name=f"{p_name} ({len(tracks)} tracks)"[:100],
                    value=p_name[:100]
                ))
            if len(choices) >= 25:
                break
        return choices

    @playlist_add.autocomplete('name')
    @playlist_play.autocomplete('name')
    @playlist_view.autocomplete('name')
    @playlist_remove.autocomplete('name')
    @playlist_delete.autocomplete('name')
    async def playlist_name_ac(self, interaction: discord.Interaction, current: str):
        return await self._playlist_name_autocomplete(interaction, current)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        print(f"[Music AppCommandError] {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ An error occurred while executing the music command.", ephemeral=True)
            else:
                await interaction.followup.send("⚠️ An error occurred while executing the music command.", ephemeral=True)
        except Exception:
            pass

async def setup(bot):
    await bot.add_cog(Music(bot))