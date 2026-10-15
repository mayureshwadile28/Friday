import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import yt_dlp
import urllib.request
import urllib.parse
import json
import os
import time
import random
import re
import base64
import warnings
from database import db
from response_utils import make_box_embed, reply_box


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
        # First try C-accelerated library if cryptography package is installed
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

        # Standalone pure-Python fallback (requires zero third-party packages, works everywhere)
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

# Studio audio extraction options via yt-dlp with multi-format fallback chain
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

# Studio Audiophile DSP & Equalization Profiles (Spotify Premium Tuned Engine)
AUDIO_FILTERS = {
    "studio": {
        "name": "Studio Master (Spotify Premium)",
        "emoji": "🎧",
        "description": "Crisp 48kHz highs, warm balanced low-end punch, anti-clipping limiter",
        "af": "equalizer=f=64:width_type=o:width=1.5:g=1.5,equalizer=f=12000:width_type=o:width=1.5:g=1.5,alimiter=limit=0.98:attack=5:release=50"
    },
    "bassboost": {
        "name": "Bass Boost",
        "emoji": "🔊",
        "description": "Deep sub-bass punch for EDM, Phonk, and Hip-Hop",
        "af": "equalizer=f=60:width_type=h:width=60:g=6,equalizer=f=120:width_type=h:width=80:g=4,alimiter=limit=0.95:attack=5:release=50"
    },
    "vocal": {
        "name": "Vocal / Acoustic",
        "emoji": "🎙️",
        "description": "Enhanced vocal presence and instrument clarity",
        "af": "equalizer=f=3000:width_type=o:width=2.0:g=3.0,equalizer=f=200:width_type=o:width=1.0:g=-1.5,alimiter=limit=0.98:attack=5:release=50"
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
    before_parts.append('-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -thread_queue_size 8192')
    before = ' '.join(before_parts)
    af = AUDIO_FILTERS.get(filter_key, {}).get("af", "")
    if af:
        options = f'-vn -sn -dn -af {af}'
    else:
        options = '-vn -sn -dn'
    return {'before_options': before, 'options': options}

# Legacy default options fallback
FFMPEG_OPTIONS = get_ffmpeg_options("studio")



class Song:
    def __init__(self, title, url, duration, requester, thumbnail=None, webpage_url=None):
        self.title = title
        self.url = url
        self.webpage_url = webpage_url or url
        self.duration = duration
        self.requester = requester
        self.thumbnail = thumbnail

class MusicControlView(discord.ui.View):
    """
    Studio High-Fidelity Music Controller View.
    Row 0: Pause/Resume, Skip, Shuffle, Loop, Stop (5 buttons)
    Row 1: Queue, Like, Vol -, Vol + (4 buttons)
    Row 2: Equalizer / DSP Mastering Filter Dropdown (Real-time live switch)
    """
    def __init__(self, cog=None, guild_id: int = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    def _get_context(self, interaction: discord.Interaction):
        gid = interaction.guild_id or self.guild_id
        cog = self.cog or (interaction.client.get_cog("Music") if interaction.client else None)
        return gid, cog

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏯️", custom_id="music_pause_resume", row=0)
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            gid, cog = self._get_context(interaction)
            vc = interaction.guild.voice_client if interaction.guild else None
            if not vc or not (vc.is_playing() or vc.is_paused()):
                msg = cog.get_resp(gid, "music_nothing_playing", "Nothing is currently playing.") if cog else "Nothing is currently playing."
                await reply_box(interaction, msg, title="Playback Inactive", status="error", ephemeral=True)
                return

            if vc.is_paused():
                vc.resume()
                button.label = "Pause"
                button.style = discord.ButtonStyle.secondary
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    pass
                msg = cog.get_resp(gid, "music_resumed", "Music resumed.") if cog else "Music resumed."
                await reply_box(interaction, msg, title="Playback Resumed", status="success", ephemeral=True)
            else:
                vc.pause()
                button.label = "Resume"
                button.style = discord.ButtonStyle.success
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    pass
                msg = cog.get_resp(gid, "music_paused", "Music paused.") if cog else "Music paused."
                await reply_box(interaction, msg, title="Playback Paused", status="info", ephemeral=True)
        except Exception as e:
            print(f"[Music Button Error: pause] {e}")
            try:
                await reply_box(interaction, f"Could not toggle pause: `{e}`", title="Command Notice", status="error", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️", custom_id="music_skip", row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            gid, cog = self._get_context(interaction)
            vc = interaction.guild.voice_client if interaction.guild else None
            if not vc or not (vc.is_playing() or vc.is_paused()):
                msg = cog.get_resp(gid, "music_nothing_playing", "Nothing is currently playing.") if cog else "Nothing is currently playing."
                await reply_box(interaction, msg, title="Playback Inactive", status="error", ephemeral=True)
                return

            asyncio.get_event_loop().run_in_executor(None, vc.stop)
            msg = cog.get_resp(gid, "music_skipped", "Skipped current track!") if cog else "Skipped current track!"
            await reply_box(interaction, msg, title="Track Skipped", status="success", ephemeral=True)
        except Exception as e:
            print(f"[Music Button Error: skip] {e}")

    @discord.ui.button(label="Shuffle", style=discord.ButtonStyle.secondary, emoji="🔀", custom_id="music_shuffle", row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            if len(state["queue"]) < 2:
                await reply_box(interaction, "Add at least 2 songs to the queue to shuffle.", title="Queue Notice", status="info", ephemeral=True)
                return

            random.shuffle(state["queue"])
            await reply_box(interaction, f"Reordered **{len(state['queue'])}** upcoming tracks in queue.", title="Queue Shuffled", status="success", ephemeral=True)
        except Exception as e:
            print(f"[Music Button Error: shuffle] {e}")

    @discord.ui.button(label="Loop", style=discord.ButtonStyle.secondary, emoji="🔁", custom_id="music_loop", row=0)
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            is_loop = not state.get("loop", False)
            state["loop"] = is_loop
            if is_loop:
                button.style = discord.ButtonStyle.primary
                button.label = "Looping"
            else:
                button.style = discord.ButtonStyle.secondary
                button.label = "Loop"
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            await reply_box(interaction, f"Track looping is now **{'Enabled' if is_loop else 'Disabled'}**.", title="Loop Mode", status="info", ephemeral=True)
        except Exception as e:
            print(f"[Music Button Error: loop] {e}")

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", custom_id="music_stop", row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            gid, cog = self._get_context(interaction)
            vc = interaction.guild.voice_client if interaction.guild else None
            if cog:
                state = cog.get_state(gid)
                state["queue"].clear()
                state["current"] = None

            if vc and (vc.is_playing() or vc.is_paused()):
                asyncio.get_event_loop().run_in_executor(None, vc.stop)

            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

            msg = cog.get_resp(gid, "music_stopped", "Playback stopped and queue cleared.") if cog else "Playback stopped and queue cleared."
            await reply_box(interaction, msg, title="Playback Stopped", status="warning", ephemeral=True)
        except Exception as e:
            print(f"[Music Button Error: stop] {e}")

    @discord.ui.button(label="Queue", style=discord.ButtonStyle.secondary, emoji="📜", custom_id="music_queue", row=1)
    async def queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            current = state.get("current")
            queue = state.get("queue", [])
            if not current and not queue:
                msg = cog.get_resp(gid, "music_queue_empty", "The queue is currently empty.")
                await reply_box(interaction, msg, title="Queue Empty", status="info", ephemeral=True)
                return

            embed = discord.Embed(
                title="◈  Playback Queue",
                color=discord.Color.from_rgb(139, 92, 246)
            )
            if current:
                mins, secs = divmod(current.duration or 0, 60)
                req_mention = current.requester.mention if hasattr(current.requester, 'mention') else "Someone"
                embed.add_field(
                    name="▶ Currently Playing",
                    value=f"• **[{current.title}]({current.webpage_url})**\n  ⏱ `{mins:02d}:{secs:02d}` • Requested by: {req_mention}",
                    inline=False
                )
            if queue:
                lines = []
                for idx, s in enumerate(queue[:10], start=1):
                    mins, secs = divmod(s.duration or 0, 60)
                    s_req = s.requester.mention if hasattr(s.requester, 'mention') else "Someone"
                    lines.append(f"`{idx}.` **[{s.title}]({s.webpage_url})** (`{mins:02d}:{secs:02d}`) — {s_req}")
                if len(queue) > 10:
                    lines.append(f"*... and {len(queue) - 10} more songs in queue*")
                embed.add_field(name="Upcoming in Queue", value="\n".join(lines), inline=False)
            else:
                embed.add_field(name="Upcoming in Queue", value="*No upcoming songs. Use `/play` to add more!*", inline=False)

            embed.set_footer(text=f"Total: {len(queue)} upcoming • Friday High-Fidelity Audio")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"[Music Button Error: queue] {e}")

    @discord.ui.button(label="Like", style=discord.ButtonStyle.success, emoji="💚", custom_id="music_like", row=1)
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            current = state.get("current")
            if not current:
                await reply_box(interaction, "No track currently playing to like.", title="Liked Songs", status="error", ephemeral=True)
                return

            uid_str = str(interaction.user.id)
            user_likes = db.liked_songs.setdefault(uid_str, [])
            if any(item.get("url") == current.webpage_url for item in user_likes):
                await reply_box(interaction, f"**[{current.title}]({current.webpage_url})** is already in your Liked Songs! Use `/likes` to view them.", title="Already Saved", status="info", ephemeral=True)
                return

            user_likes.append({
                "title": current.title,
                "url": current.webpage_url,
                "duration": current.duration
            })
            db.save_data()
            await reply_box(interaction, f"Saved **[{current.title}]({current.webpage_url})** to your Liked Songs! Use `/likes` to play them anytime.", title="Song Saved", status="success", ephemeral=True)
        except Exception as e:
            print(f"[Music Button Error: like] {e}")

    @discord.ui.button(label="Vol -", style=discord.ButtonStyle.secondary, emoji="🔉", custom_id="music_vol_down", row=1)
    async def vol_down_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
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
            await reply_box(interaction, f"Master volume adjusted to **{int(new_vol * 100)}%**.", title="Volume Lowered", status="audio", ephemeral=True)
        except Exception as e:
            print(f"[Music Button Error: vol_down] {e}")

    @discord.ui.button(label="Vol +", style=discord.ButtonStyle.secondary, emoji="🔊", custom_id="music_vol_up", row=1)
    async def vol_up_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
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
            await reply_box(interaction, f"Master volume adjusted to **{int(new_vol * 100)}%**.", title="Volume Raised", status="audio", ephemeral=True)
        except Exception as e:
            print(f"[Music Button Error: vol_up] {e}")

    @discord.ui.select(
        placeholder="🎛️ Equalizer & DSP Audio Filters...",
        custom_id="music_eq_select",
        row=2,
        options=[
            discord.SelectOption(label="Studio Master (Spotify Premium)", value="studio", description="Crisp 48kHz highs, warm punch, anti-clipping", emoji="🎧"),
            discord.SelectOption(label="Bass Boost", value="bassboost", description="Deep sub-bass punch for EDM, Phonk, Hip-Hop", emoji="🔊"),
            discord.SelectOption(label="Vocal / Acoustic", value="vocal", description="Enhanced vocal presence and instrument clarity", emoji="🎙️"),
            discord.SelectOption(label="Nightcore", value="nightcore", description="High-energy speedup (1.25x tempo + higher pitch)", emoji="🌙"),
            discord.SelectOption(label="Lo-Fi / Warm Chill", value="lofi", description="Warm vintage analog low-pass filter", emoji="☕"),
            discord.SelectOption(label="Treble Boost", value="treble", description="Crisp high-frequency clarity and vocal sparkle", emoji="⚡"),
            discord.SelectOption(label="8D Surround", value="8d", description="Rotating spatial binaural surround sound", emoji="🌐"),
            discord.SelectOption(label="Flat / Pure Raw", value="flat", description="Untouched original audio stream", emoji="🎚️"),
        ]
    )
    async def eq_dropdown(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            gid, cog = self._get_context(interaction)
            if not cog:
                return
            state = cog.get_state(gid)
            new_eq = select.values[0]
            state["filter"] = new_eq
            profile = AUDIO_FILTERS.get(new_eq, AUDIO_FILTERS["studio"])

            vc = interaction.guild.voice_client if interaction.guild else None
            current = state.get("current")

            # Seamless live switch: preserve playback position without restarting track
            if vc and (vc.is_playing() or vc.is_paused()) and current:
                vol = state.get("volume", 1.0)
                elapsed = int(time.time() - state.get("start_time", time.time()))
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
                        state["start_time"] = time.time() - ss_pos

                        if vc.ws:
                            try:
                                await vc.ws.speak(discord.SpeakingState.voice)
                            except Exception:
                                pass

                        def after_play(err):
                            if state.get("_switching_filter"):
                                return
                            cog.play_next(gid)

                        vc.play(source, after=after_play)

                        # Update Now Playing message embed in real-time
                        np_msg = interaction.message or state.get("np_message")
                        if np_msg:
                            updated_embed = cog.create_now_playing_embed(current, vol, gid)
                            await np_msg.edit(embed=updated_embed, view=self)
                    except Exception as err:
                        print(f"[Music EQ Switch Error] {err}")
                    finally:
                        state["_switching_filter"] = False

                asyncio.create_task(_apply_eq_seamless())

            await reply_box(
                interaction,
                description=f"Equalizer Profile: **{profile['emoji']} {profile['name']}**\n{profile['description']}\n*Seamless real-time mastering engaged without restarting track.*",
                title="Equalizer Updated",
                status="audio",
                ephemeral=True
            )
        except Exception as e:
            print(f"[Music Button Error: eq_select] {e}")


class QueueItemView(discord.ui.View):
    """Action buttons for newly queued tracks: Play Now or Remove from Queue."""
    def __init__(self, cog, guild_id: int, song: Song):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.song = song

    @discord.ui.button(label="Play Now", style=discord.ButtonStyle.success, emoji="⚡")
    async def play_now_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            state = self.cog.get_state(self.guild_id)
            vc = interaction.guild.voice_client if interaction.guild else None
            if not vc:
                await interaction.followup.send("❌ Friday is not in a voice channel.", ephemeral=True)
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
            await interaction.followup.send(f"⚡ Now playing **{self.song.title}** immediately!", ephemeral=True)
        except Exception as e:
            print(f"[Music Queue Button Error] {e}")

    @discord.ui.button(label="Remove from Queue", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def remove_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
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
                await interaction.followup.send(f"🗑️ Removed **{self.song.title}** from the queue.", ephemeral=True)
            else:
                await interaction.followup.send("ℹ️ This track is already playing or no longer in the queue.", ephemeral=True)
        except Exception as e:
            print(f"[Music Queue Button Error] {e}")

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Per-guild music state
        self.states = {}
        # Register persistent controller view so buttons never time out across restarts
        try:
            self.bot.add_view(MusicControlView(self))
        except Exception as e:
            print(f"[Music] Note: Persistent view registration: {e}")

    def get_state(self, guild_id: int):
        if guild_id not in self.states:
            self.states[guild_id] = {
                "queue": [],
                "current": None,
                "channel": None,
                "loop": False,
                "volume": 1.0,
                "transformer": None,
                "filter": "studio",
                "start_time": 0.0,
                "np_message": None
            }
        return self.states[guild_id]

    def get_ffmpeg_options(self, guild_id: int, seek_seconds: int = 0):
        state = self.get_state(guild_id)
        f_key = state.get("filter", "studio")
        return get_ffmpeg_options(f_key, seek_seconds=seek_seconds)



    def get_resp(self, guild_id: int, key: str, default: str, **kwargs) -> str:
        """Fetch custom server response from database or fallback to default template."""
        gid_str = str(guild_id)
        msg = db.custom_responses.get(gid_str, {}).get(key, default)
        for k, v in kwargs.items():
            msg = msg.replace(f"{{{k}}}", str(v))
        return msg

    async def fetch_suggestions(self, query: str):
        """Ultra-fast, zero-load YouTube search query autocomplete via Google suggest API (<500ms)."""
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
            format_chain = 'bestaudio[ext=m4a]/bestaudio/best/18/140'

            # Protect master cookies.txt from corruption & strip volatile session tokens
            # (SIDTS, SIDCC, etc.) that cause Google to throw "The page needs to be reloaded" on datacenter IPs
            active_cookie_path = None
            if cookie_path and os.path.isfile(cookie_path) and os.path.getsize(cookie_path) > 0:
                try:
                    EXCLUDED_COOKIES = {
                        "__Secure-1PSIDTS", "__Secure-3PSIDTS", "SIDCC",
                        "__Secure-1PSIDCC", "__Secure-3PSIDCC", "ST-xuwub9"
                    }
                    with open(cookie_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                    clean = []
                    for line in lines:
                        if line.startswith("#"):
                            clean.append(line)
                            continue
                        parts = line.strip().split("\t")
                        if len(parts) >= 7 and parts[5] in EXCLUDED_COOKIES:
                            continue
                        clean.append(line)
                    runtime_path = os.path.join(os.path.dirname(cookie_path), "cookies_runtime.txt")
                    with open(runtime_path, 'w', encoding='utf-8') as out:
                        out.writelines(clean)
                    active_cookie_path = runtime_path
                except Exception as c_err:
                    print(f"[Music] Runtime cookie sanitization note: {c_err}")
                    active_cookie_path = cookie_path

            # Direct audio stream handling (.mp3, .m4a, .wav, .aac, .ogg, .flac, .opus, .m3u8, radio streams)
            DIRECT_AUDIO_EXTS = ('.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac', '.opus', '.m3u8')
            if is_url and any(query.lower().split('?')[0].endswith(ext) for ext in DIRECT_AUDIO_EXTS):
                clean_name = query.split('/')[-1].split('?')[0]
                return {
                    'title': clean_name or 'Direct Audio Stream',
                    'url': query,
                    'webpage_url': query,
                    'duration': 0,
                    'thumbnail': None
                }

            # Dedicated helper for JioSaavn 320kbps CDN stream extraction
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

                        # Require >= 55 score so random covers don't hijack English songs
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
                            'thumbnail': img
                        }
                except Exception as saavn_err:
                    print(f"[Music] Saavn extraction error: {saavn_err}")
                    return None

            # Helper for SoundCloud extraction with browser headers
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
                        score = sum(20 for w in q_words if w in t)
                        for pt in ['cover', 'remix', 'drill', 'mashup', 'slowed', 'reverb', 'bass boosted']:
                            if pt in t and pt not in q_lower:
                                score -= 25
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
                            'thumbnail': best_entry.get('thumbnail')
                        }
                return None

            # Fast official YouTube search and single audio stream extraction
            def _extract_yt(target, use_cookies=False):
                is_search = not (target.startswith("http://") or target.startswith("https://"))
                if not is_search:
                    opts = {
                        'format': format_chain,
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'geo_bypass': True,
                        'nocheckcertificate': True,
                        'http_headers': DEFAULT_HEADERS,
                    }
                    if use_cookies and active_cookie_path:
                        opts['cookiefile'] = active_cookie_path
                    else:
                        opts['extractor_args'] = {'youtube': {'player_client': ['ios', 'android_vr', 'tv_embedded']}}

                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(target, download=False)
                        entries = info.get('entries', []) if info and 'entries' in info else ([info] if info else [])
                        if entries and entries[0] and entries[0].get('url'):
                            e = entries[0]
                            return {
                                'title': e.get('title', 'Unknown Track'),
                                'url': e.get('url'),
                                'webpage_url': e.get('webpage_url', target),
                                'duration': e.get('duration', 0),
                                'thumbnail': e.get('thumbnail')
                            }
                    return None

                # Step 1: Ultra-fast flat metadata query (<2s)
                clean_query = target.replace('ytsearch1:', '').replace('ytsearch5:', '').strip()
                flat_opts = {
                    'extract_flat': 'in_playlist',
                    'quiet': True,
                    'no_warnings': True,
                    'noplaylist': True,
                    'http_headers': DEFAULT_HEADERS,
                }
                if use_cookies and active_cookie_path:
                    flat_opts['cookiefile'] = active_cookie_path

                with yt_dlp.YoutubeDL(flat_opts) as ydl:
                    res = ydl.extract_info(f"ytsearch5:{clean_query}", download=False)
                    entries = res.get('entries', []) if res else []
                    if not entries:
                        return None

                    # Step 2: Relevance & Official release scoring
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
                        for bad in ['cover', 'remix', 'slowed', 'reverb', 'parody', 'reaction', 'karaoke', 'instrumental', 'status', 'shorts', 'ringtone']:
                            if bad in t and bad not in q_lower:
                                score -= 40

                        if score > best_score:
                            best_score = score
                            best_id = entry.get('id')
                            best_entry = entry

                if not best_id:
                    return None

                # Step 3: Extract direct audio stream for the single winning official track
                stream_opts = {
                    'format': format_chain,
                    'quiet': True,
                    'no_warnings': True,
                    'noplaylist': True,
                    'geo_bypass': True,
                    'nocheckcertificate': True,
                    'http_headers': DEFAULT_HEADERS,
                }
                if use_cookies and active_cookie_path:
                    stream_opts['cookiefile'] = active_cookie_path
                else:
                    stream_opts['extractor_args'] = {'youtube': {'player_client': ['ios', 'android_vr', 'tv_embedded']}}

                with yt_dlp.YoutubeDL(stream_opts) as ydl_stream:
                    info = ydl_stream.extract_info(f"https://www.youtube.com/watch?v={best_id}", download=False)
                    if info and info.get('url'):
                        return {
                            'title': info.get('title', best_entry.get('title', 'Unknown Track')),
                            'url': info.get('url'),
                            'webpage_url': info.get('webpage_url', f"https://www.youtube.com/watch?v={best_id}"),
                            'duration': info.get('duration', 0),
                            'thumbnail': info.get('thumbnail') or best_entry.get('thumbnail')
                        }
                return None

            search_title = query
            if is_url:
                if "spotify.com" in query:
                    try:
                        oe = f"https://open.spotify.com/oembed?url={urllib.parse.quote(query)}"
                        req = urllib.request.Request(oe, headers=DEFAULT_HEADERS)
                        with urllib.request.urlopen(req, timeout=5) as r:
                            raw_title = json.loads(r.read().decode()).get('title', '')
                            if raw_title:
                                search_title = raw_title
                    except Exception as sp_err:
                        print(f"[Music] Spotify oEmbed note: {sp_err}")

            search_target = query if (is_url and "spotify.com" not in query) else search_title

            # Tier 1a: If cookies exist, try authenticated YouTube extraction first (fastest on bot hosts)
            if active_cookie_path:
                try:
                    res_cookie = _extract_yt(search_target, use_cookies=True)
                    if res_cookie:
                        return res_cookie
                except Exception as e_cook:
                    print(f"[Music] YouTube cookie extraction note: {e_cook}")

            # Tier 1b: Primary YouTube Extraction (Cookie-less fallback)
            try:
                yt_res = _extract_yt(search_target, use_cookies=False)
                if yt_res:
                    return yt_res
            except Exception as e1:
                print(f"[Music] YouTube extraction note: {e1}")

            # Tier 2: JioSaavn 320kbps CDN (Ultra fast official Indian & global tracks)
            saavn_res = _extract_saavn(search_title)
            if saavn_res:
                return saavn_res

            # Tier 3: SoundCloud search fallback
            try:
                sc_res = _extract_sc(search_title)
                if sc_res:
                    return sc_res
            except Exception as e2:
                print(f"[Music] SoundCloud extraction note: {e2}")

            raise Exception("Could not find an audio stream for this track. Please check the song name or provide a direct audio link.")

        return await loop.run_in_executor(None, _extract)

    def create_now_playing_embed(self, song: Song, volume: float = 1.0, guild_id: int = None) -> discord.Embed:
        """Constructs a sleek, modern Now Playing card inspired by premier music bots."""
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

        embed.description = (
            f"• **[{song.title}]({song.webpage_url})**\n"
            f"• ⏱ **Duration:** `{mins:02d}m {secs:02d}s` — ({song.requester.mention})\n"
            f"• ◈ **Volume:** `{int(volume * 100)}%`  •  **EQ:** `{profile_name}`\n"
            f"• 🎚 **Engine:** `48kHz Studio Master (YouTube High-Fidelity Audio)`"
        )
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        embed.set_footer(text="Friday Studio Audio • 48kHz Stereo Master Engine • Pure High-Fidelity")
        return embed

    def play_next(self, guild_id: int):
        state = self.get_state(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not guild or not guild.voice_client or not guild.voice_client.is_connected():
            state["current"] = None
            state["transformer"] = None
            return

        vc = guild.voice_client

        if state.get("loop") and state.get("current"):
            next_song = state["current"]
        elif state["queue"]:
            next_song = state["queue"].pop(0)
            state["current"] = next_song
        else:
            state["current"] = None
            state["transformer"] = None
            return

        def after_play(err):
            if state.get("_switching_filter"):
                return
            print(f"[Music Debug] Track '{next_song.title}' ended. Error: {err}")
            if err:
                if state.get("channel"):
                    asyncio.run_coroutine_threadsafe(
                        state["channel"].send(f"⚠️ Audio playback notice: `{err}`"),
                        self.bot.loop
                    )
            self.play_next(guild_id)

        try:
            vol = state.get("volume", 1.0)
            ffmpeg_opts = self.get_ffmpeg_options(guild_id)
            raw_source = discord.FFmpegPCMAudio(next_song.url, **ffmpeg_opts)
            source = discord.PCMVolumeTransformer(raw_source, volume=vol)
            state["transformer"] = source

            if vc.ws:
                try:
                    asyncio.run_coroutine_threadsafe(vc.ws.speak(discord.SpeakingState.voice), self.bot.loop)
                except Exception:
                    pass

            state["start_time"] = time.time()
            vc.play(source, after=after_play)

            if state["channel"]:
                embed = self.create_now_playing_embed(next_song, vol, guild_id)
                view = MusicControlView(self, guild_id)
                async def _send_and_track():
                    try:
                        msg = await state["channel"].send(embed=embed, view=view)
                        state["np_message"] = msg
                    except Exception:
                        pass
                asyncio.run_coroutine_threadsafe(_send_and_track(), self.bot.loop)
        except Exception as e:
            print(f"[Music] Error playing {next_song.title}: {e}")
            if state["channel"]:
                asyncio.run_coroutine_threadsafe(
                    state["channel"].send(f"❌ Error playing `{next_song.title}`: {e}"),
                    self.bot.loop
                )
            self.play_next(guild_id)

    # ───────────────────── Slash Commands ─────────────────────

    async def ensure_voice_connection(self, interaction: discord.Interaction) -> tuple:
        """
        Validates voice permissions, ensures clean connection without self-deafening,
        and verifies audio transmit readiness. Returns (vc, warning_or_error_msg).
        """
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

        # Clean up broken/stale voice clients if disconnected
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

        # Check server-mute and stage suppression
        if bot_member.voice:
            if bot_member.voice.mute:
                mute_warn = "⚠️ **Server Mute**: Friday is currently **Server-Muted** in this server! An administrator must right-click Friday and uncheck 'Server Mute' for audio to be heard."
                warning = f"{warning}\n{mute_warn}" if warning else mute_warn
            if bot_member.voice.suppress:
                suppress_warn = "⚠️ **Stage Suppression**: Friday is in a Stage channel as an audience listener! Please invite Friday to Speak."
                warning = f"{warning}\n{suppress_warn}" if warning else suppress_warn

        # Note: Do NOT perform channel.edit(bitrate=...) here.
        # Modifying channel settings during/right after connecting causes Discord
        # to reset the Voice Gateway connection with code 1006 (Abnormal Closure).
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
        state["queue"].clear()
        state["current"] = None
        state["transformer"] = None

        if vc and vc.is_connected():
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
            state["queue"].append(song)
            mins, secs = divmod(song.duration or 0, 60)
            pos = len(state["queue"])
            embed = discord.Embed(
                title="◈  ADDED TO QUEUE",
                description=f"• **[{song.title}]({song.webpage_url})**\n• ◈ **Position:** `#{pos}`  •  ⏱ **Duration:** `{mins:02d}m {secs:02d}s`\n• ◈ **Requested by:** {interaction.user.mention}",
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
                if state.get("_switching_filter"):
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

                state["start_time"] = time.time()
                vc.play(source, after=after_play)
                embed = self.create_now_playing_embed(song, vol, interaction.guild.id)
                view = MusicControlView(self, interaction.guild.id)
                msg = await interaction.followup.send(embed=embed, view=view)
                state["np_message"] = msg
            except Exception as e:
                await reply_box(interaction, f"Error initializing audio stream: {e}", title="STREAM ERROR", status="danger")
                self.play_next(interaction.guild.id)

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
            embed.add_field(
                name="▶ Current Track",
                value=f"• **[{current.title}]({current.webpage_url})**\n  ⏱ `{mins:02d}m {secs:02d}s` • Requested by: {current.requester.mention}",
                inline=False
            )

        if queue:
            lines = []
            for idx, s in enumerate(queue[:10], start=1):
                mins, secs = divmod(s.duration or 0, 60)
                lines.append(f"`{idx}.` **[{s.title}]({s.webpage_url})** (`{mins:02d}:{secs:02d}`) — {s.requester.mention}")
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
        state["queue"].clear()
        state["current"] = None
        state["transformer"] = None

        if vc and (vc.is_playing() or vc.is_paused()):
            asyncio.get_event_loop().run_in_executor(None, vc.stop)
            msg = self.get_resp(interaction.guild_id, "music_stopped", "Playback stopped and queue cleared.")
            await reply_box(interaction, msg, title="PLAYBACK STOPPED", status="danger")
        else:
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

            # Calculate elapsed time for seamless real-time seek
            start_t = state.get("start_time", 0)
            elapsed = int(time.time() - start_t) if start_t else 0
            if elapsed < 0:
                elapsed = 0
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
                if state.get("_switching_filter"):
                    return
                self.play_next(interaction.guild.id)

            state["start_time"] = time.time() - ss_pos
            vc.play(source, after=after_play)

            # Live edit Now Playing embed if available
            np_msg = state.get("np_message")
            if np_msg:
                try:
                    new_embed = self.create_now_playing_embed(current, vol, interaction.guild.id)
                    await np_msg.edit(embed=new_embed)
                except Exception:
                    pass

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

async def setup(bot):
    await bot.add_cog(Music(bot))
