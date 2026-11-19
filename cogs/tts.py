import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import re
import tempfile
from typing import Optional, Dict

import sys
import glob

# Ensure user site-packages are accessible even under systemd service environments
for site_candidate in [
    os.path.expanduser("~/.local/lib/python3.12/site-packages"),
    os.path.expanduser("~/.local/lib/python3/site-packages"),
    "/home/maywa554785/.local/lib/python3.12/site-packages",
    "/usr/local/lib/python3.12/dist-packages",
    "/usr/local/lib/python3.12/site-packages",
    *glob.glob("/home/*/.local/lib/python3*/site-packages")
]:
    if os.path.exists(site_candidate) and site_candidate not in sys.path:
        sys.path.insert(0, site_candidate)

def get_edge_tts():
    """Lazily attempts to import edge_tts if it was missing or installed post-startup."""
    global edge_tts, HAS_EDGE_TTS
    if HAS_EDGE_TTS and edge_tts is not None:
        return edge_tts
    try:
        import edge_tts as _et
        edge_tts = _et
        HAS_EDGE_TTS = True
        return edge_tts
    except ImportError:
        for p in glob.glob("/home/*/.local/lib/python3*/site-packages"):
            if os.path.exists(p) and p not in sys.path:
                sys.path.insert(0, p)
        try:
            import edge_tts as _et
            edge_tts = _et
            HAS_EDGE_TTS = True
            return edge_tts
        except ImportError:
            HAS_EDGE_TTS = False
            return None

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    edge_tts = get_edge_tts()
    HAS_EDGE_TTS = (edge_tts is not None)

from database import db
from response_utils import make_box_embed, reply_box

# ─────────────────────────────────────────────────────────────
# Voice Presets (Cute, expressive, and natural AI voices)
# ─────────────────────────────────────────────────────────────
TTS_VOICE_PRESETS = {
    "friday_cute": {
        "name": "Friday Cute (Default)",
        "voice": "en-US-AnaNeural",
        "pitch": "+15Hz",
        "rate": "+4%",
        "badge": "🌸 Cute Anime",
        "desc": "Sweet, adorable, and lively AI companion voice"
    },
    "sweet_assistant": {
        "name": "Sweet Assistant",
        "voice": "en-US-JennyNeural",
        "pitch": "+8Hz",
        "rate": "+2%",
        "badge": "🎀 Sweet & Warm",
        "desc": "Warm, polite, cheerful, and clear companion voice"
    },
    "playful_ava": {
        "name": "Playful Ava",
        "voice": "en-US-AvaNeural",
        "pitch": "+10Hz",
        "rate": "+4%",
        "badge": "💫 Playful",
        "desc": "Energetic, modern, spirited assistant voice"
    },
    "standard_natural": {
        "name": "Standard Natural",
        "voice": "en-US-AriaNeural",
        "pitch": "+0Hz",
        "rate": "+0%",
        "badge": "🎙️ Natural",
        "desc": "Clean, crisp, studio-neutral assistant voice"
    },
    "japanese_nanami": {
        "name": "Japanese Nanami",
        "voice": "ja-JP-NanamiNeural",
        "pitch": "+8Hz",
        "rate": "+0%",
        "badge": "🍵 Japanese Anime",
        "desc": "Cute Japanese anime-style voice"
    }
}

DEFAULT_PRESET_KEY = "friday_cute"


def sanitize_tts_text(text: str, guild: Optional[discord.Guild], max_length: int = 150) -> str:
    """Cleans Discord message text for smooth, natural TTS speech."""
    if not text:
        return ""

    # Ignore command prefixes
    if text.startswith(("!", "/", "$", ".", ",", "?", "-", "~", ";")):
        return ""

    # Replace URLs with "link"
    cleaned = re.sub(r'https?://\S+', 'link', text)

    # Replace user mentions with their display name
    if guild:
        def replace_user(match):
            uid = int(match.group(1))
            mem = guild.get_member(uid)
            return mem.display_name if mem else "someone"
        cleaned = re.sub(r'<@!?(\d+)>', replace_user, cleaned)
        cleaned = re.sub(r'<@&(\d+)>', 'role', cleaned)
        cleaned = re.sub(r'<#(\d+)>', 'channel', cleaned)
    else:
        cleaned = re.sub(r'<@!?\d+>', 'someone', cleaned)
        cleaned = re.sub(r'<@&\d+>', 'role', cleaned)
        cleaned = re.sub(r'<#\d+>', 'channel', cleaned)

    # Replace Discord custom emojis <:name:id> or <a:name:id> with their name
    cleaned = re.sub(r'<a?:([a-zA-Z0-9_]+):[0-9]+>', r' \1 ', cleaned)

    # Strip code blocks and spoilers
    cleaned = re.sub(r'```[\s\S]*?```', 'code block', cleaned)
    cleaned = re.sub(r'`([^`]+)`', r'\1', cleaned)
    cleaned = re.sub(r'\|\|.*?\|\|', 'spoiler', cleaned)

    # Strip markdown bold/italics
    cleaned = re.sub(r'[*_~]', '', cleaned)

    # Collapse excessive whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Truncate to max length with ellipsis
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip() + "..."

    return cleaned


class TTSVoiceSelect(discord.ui.Select):
    def __init__(self, current_key: str):
        options = []
        for key, p in TTS_VOICE_PRESETS.items():
            options.append(discord.SelectOption(
                label=p["name"],
                value=key,
                description=p["desc"][:100],
                emoji=p["badge"][:2],
                default=(key == current_key)
            ))
        super().__init__(
            placeholder="Select a cute voice persona for Friday...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="friday_tts_voice_select"
        )

    async def callback(self, interaction: discord.Interaction):
        chosen_key = self.values[0]
        preset = TTS_VOICE_PRESETS.get(chosen_key, TTS_VOICE_PRESETS[DEFAULT_PRESET_KEY])
        gid = str(interaction.guild_id)

        cfg = db.tts_config.setdefault(gid, {})
        cfg["voice_preset"] = chosen_key
        db.save_data()

        embed = make_box_embed(
            title="TTS VOICE UPDATED",
            description=(
                f"Friday's voice personality has been set to **{preset['name']}** {preset['badge']}!\n\n"
                f"• **Tone:** {preset['desc']}\n"
                f"• **Voice ID:** `{preset['voice']}`\n"
                f"• **Pitch:** `{preset['pitch']}` | **Speed:** `{preset['rate']}`"
            ),
            status="success"
        )
        await interaction.response.edit_message(embed=embed, view=None)


class TTSVoiceSelectView(discord.ui.View):
    def __init__(self, current_key: str):
        super().__init__(timeout=60)
        self.add_item(TTSVoiceSelect(current_key))


class TTSCog(commands.Cog, name="TTS"):
    """Friday Text-to-Speech (TTS) Voice Engine for Discord voice channels."""

    tts_group = app_commands.Group(name="tts", description="Friday Voice Channel Text-to-Speech (TTS) controls")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._queues: Dict[int, asyncio.Queue] = {}
        self._workers: Dict[int, asyncio.Task] = {}
        self._skip_events: Dict[int, asyncio.Event] = {}

    def cog_unload(self):
        for task in self._workers.values():
            if not task.done():
                task.cancel()

    def get_guild_cfg(self, gid: str) -> dict:
        return db.tts_config.setdefault(gid, {
            "enabled": False,
            "voice_preset": DEFAULT_PRESET_KEY,
            "channel_id": None,
            "max_length": 150,
            "announce_author": True,
            "auto_mute_music": True
        })

    def is_music_playing(self, guild: discord.Guild) -> bool:
        """Determines if the Music cog is currently playing a song on the guild's voice client."""
        music_cog = self.bot.get_cog("Music")
        if music_cog:
            try:
                state = music_cog.get_state(guild.id)
                if state.get("current") is not None:
                    return True
            except Exception:
                pass

        vc = guild.voice_client
        if vc and vc.is_playing() and not getattr(vc, "_is_tts_playing", False):
            return True

        return False

    async def _queue_worker(self, guild_id: int):
        """Worker task processing TTS speech items in sequential chronological order."""
        queue = self._queues.setdefault(guild_id, asyncio.Queue())
        skip_event = self._skip_events.setdefault(guild_id, asyncio.Event())

        while True:
            try:
                item = await queue.get()
            except asyncio.CancelledError:
                break

            guild = self.bot.get_guild(guild_id)
            if not guild or not guild.voice_client or not guild.voice_client.is_connected():
                queue.task_done()
                continue

            vc = guild.voice_client

            # Check if Music is playing. If so, drop / suppress TTS to keep music uninterrupted
            cfg = self.get_guild_cfg(str(guild_id))
            if cfg.get("auto_mute_music", True) and self.is_music_playing(guild):
                queue.task_done()
                continue

            # Wait if another non-music sound is playing
            wait_attempts = 0
            while vc.is_playing() and getattr(vc, "_is_tts_playing", False) and wait_attempts < 20:
                await asyncio.sleep(0.5)
                wait_attempts += 1

            if cfg.get("auto_mute_music", True) and self.is_music_playing(guild):
                queue.task_done()
                continue

            temp_path = None
            try:
                preset = TTS_VOICE_PRESETS.get(item["preset_key"], TTS_VOICE_PRESETS[DEFAULT_PRESET_KEY])
                voice = preset["voice"]
                pitch = preset["pitch"]
                rate = preset["rate"]

                # Synthesize via cloud Edge-TTS
                et = get_edge_tts()
                if not et:
                    queue.task_done()
                    continue

                communicate = et.Communicate(
                    text=item["text"],
                    voice=voice,
                    pitch=pitch,
                    rate=rate
                )

                fd, temp_path = tempfile.mkstemp(prefix="friday_tts_", suffix=".mp3")
                os.close(fd)
                await communicate.save(temp_path)

                if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
                    queue.task_done()
                    continue

                skip_event.clear()
                done_event = asyncio.Event()

                def after_play(err):
                    if err:
                        print(f"[TTS Playback Notice] {err}")
                    setattr(vc, "_is_tts_playing", False)
                    self.bot.loop.call_soon_threadsafe(done_event.set)

                source = discord.FFmpegPCMAudio(temp_path)
                setattr(vc, "_is_tts_playing", True)
                vc.play(source, after=after_play)

                # Wait for playback to finish or skip
                done_waiter = asyncio.create_task(done_event.wait())
                skip_waiter = asyncio.create_task(skip_event.wait())
                await asyncio.wait(
                    [done_waiter, skip_waiter],
                    return_when=asyncio.FIRST_COMPLETED
                )

                if skip_waiter.done() and not done_waiter.done():
                    if vc.is_playing():
                        vc.stop()
                    setattr(vc, "_is_tts_playing", False)

                done_waiter.cancel()
                skip_waiter.cancel()

            except Exception as e:
                print(f"[TTS Error in Guild {guild_id}] {e}")
            finally:
                if vc:
                    setattr(vc, "_is_tts_playing", False)
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                queue.task_done()

    def ensure_worker(self, guild_id: int):
        task = self._workers.get(guild_id)
        if task is None or task.done():
            self._workers[guild_id] = asyncio.create_task(self._queue_worker(guild_id))

    # ─────────────────────────────────────────────────────────────
    # Real-Time Message Listener
    # ─────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Monitors chat messages and speaks qualified text in active voice channel."""
        if message.author.bot or not message.guild:
            return

        gid = str(message.guild.id)
        cfg = db.tts_config.get(gid)
        if not cfg or not cfg.get("enabled", False):
            return

        vc = message.guild.voice_client
        if not vc or not vc.is_connected():
            return

        # Channel & Participant Check
        allowed_cid = cfg.get("channel_id")
        if allowed_cid:
            if str(message.channel.id) != str(allowed_cid):
                return
        else:
            # By default: read from the active VC's own text chat OR messages from anyone in Friday's VC
            is_vc_chat = (message.channel.id == vc.channel.id)
            author_in_vc = (getattr(getattr(message.author, "voice", None), "channel", None) == vc.channel)
            if not is_vc_chat and not author_in_vc:
                return

        # Check if Music is playing: completely shut down / suppress TTS
        if cfg.get("auto_mute_music", True) and self.is_music_playing(message.guild):
            return

        max_len = cfg.get("max_length", 150)
        cleaned = sanitize_tts_text(message.content, message.guild, max_length=max_len)
        if not cleaned:
            return

        if cfg.get("announce_author", True):
            # Format: "Name says, Message" (comma provides natural speech cadence)
            speech_text = f"{message.author.display_name} says, {cleaned}"
        else:
            speech_text = cleaned

        preset_key = cfg.get("voice_preset", DEFAULT_PRESET_KEY)
        queue = self._queues.setdefault(message.guild.id, asyncio.Queue())

        # Avoid overwhelming the queue (max 10 pending phrases)
        if queue.qsize() < 10:
            await queue.put({
                "text": speech_text,
                "preset_key": preset_key
            })
            self.ensure_worker(message.guild.id)

    # ─────────────────────────────────────────────────────────────
    # Slash Command: /tts enable
    # ─────────────────────────────────────────────────────────────
    @tts_group.command(name="enable", description="Enable Friday Text-to-Speech (TTS) in your current voice channel.")
    @app_commands.describe(
        channel="Optional text channel to read from (defaults to active VC text chat)",
        voice="Optional cute voice preset"
    )
    @app_commands.choices(voice=[
        app_commands.Choice(name=p["name"], value=k) for k, p in TTS_VOICE_PRESETS.items()
    ])
    async def tts_enable(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        voice: Optional[str] = None
    ):
        if not interaction.guild:
            return

        if not (HAS_EDGE_TTS or get_edge_tts()):
            return await reply_box(
                interaction,
                "⚠️ **edge-tts** library is not installed on the bot VM host.\n\n"
                "Please run on your server:\n"
                "`sudo pip install --upgrade edge-tts --break-system-packages`\n"
                "and then restart Friday:\n"
                "`sudo systemctl restart friday`",
                title="EDGE-TTS MISSING",
                status="warning",
                ephemeral=True
            )

        vc = interaction.guild.voice_client
        author_vc = getattr(interaction.user.voice, "channel", None) if interaction.user.voice else None

        target_vc = None
        if vc and vc.is_connected():
            target_vc = vc.channel
        elif author_vc:
            target_vc = author_vc
        else:
            return await reply_box(
                interaction,
                "Either you must be in a voice channel, or Friday must already be in a voice channel to enable TTS!",
                title="NO VOICE CHANNEL FOUND",
                status="warning",
                ephemeral=True
            )

        await interaction.response.defer()

        # Connect Friday if not already connected
        if not vc:
            try:
                vc = await target_vc.connect()
            except Exception as e:
                return await reply_box(
                    interaction,
                    f"Failed to join voice channel: `{e}`",
                    title="CONNECTION ERROR",
                    status="danger"
                )
        elif author_vc and vc.channel.id != author_vc.id:
            try:
                await vc.move_to(author_vc)
                target_vc = author_vc
            except Exception as e:
                pass

        gid = str(interaction.guild_id)
        cfg = self.get_guild_cfg(gid)
        cfg["enabled"] = True
        if channel:
            cfg["channel_id"] = str(channel.id)
        if voice and voice in TTS_VOICE_PRESETS:
            cfg["voice_preset"] = voice

        db.save_data()
        self.ensure_worker(interaction.guild.id)

        preset = TTS_VOICE_PRESETS.get(cfg.get("voice_preset", DEFAULT_PRESET_KEY), TTS_VOICE_PRESETS[DEFAULT_PRESET_KEY])
        chan_text = f"<#{cfg['channel_id']}>" if cfg.get("channel_id") else "Voice Channel Text Chat"

        desc = (
            f"Friday Voice Assistant is now active in **{target_vc.name}**!\n\n"
            f"• **Voice Style:** {preset['name']} {preset['badge']}\n"
            f"• **Reading Channel:** {chan_text}\n"
            f"• **Music Auto-Mute:** Active (Silences automatically when songs play)\n\n"
            f"💬 *Type your message in chat and Friday will speak it aloud!*"
        )
        await reply_box(interaction, desc, title="FRIDAY TTS ACTIVE", status="success")

    # ─────────────────────────────────────────────────────────────
    # Slash Command: /tts disable
    # ─────────────────────────────────────────────────────────────
    @tts_group.command(name="disable", description="Turn off Friday TTS voice reading in this server.")
    async def tts_disable(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = self.get_guild_cfg(gid)
        cfg["enabled"] = False
        db.save_data()

        # Clear queue and stop speech
        queue = self._queues.get(interaction.guild_id)
        if queue:
            while not queue.empty():
                try:
                    queue.get_nowait()
                    queue.task_done()
                except Exception:
                    pass

        skip_ev = self._skip_events.get(interaction.guild_id)
        if skip_ev:
            skip_ev.set()

        await reply_box(
            interaction,
            "Friday Text-to-Speech has been disabled. She will no longer read chat messages.",
            title="TTS DISABLED",
            status="info"
        )

    # ─────────────────────────────────────────────────────────────
    # Slash Command: /tts join
    # ─────────────────────────────────────────────────────────────
    @tts_group.command(name="join", description="Connect Friday to your current voice channel.")
    async def tts_join(self, interaction: discord.Interaction):
        author_vc = getattr(interaction.user.voice, "channel", None) if interaction.user.voice else None
        if not author_vc:
            return await reply_box(
                interaction,
                "You must be in a voice channel first!",
                title="NOT IN VC",
                status="warning",
                ephemeral=True
            )

        vc = interaction.guild.voice_client
        if not vc:
            await author_vc.connect()
            await reply_box(interaction, f"Connected to **{author_vc.name}**! Use `/tts enable` to turn on speech.", title="VOICE CONNECTED", status="success")
        elif vc.channel.id != author_vc.id:
            await vc.move_to(author_vc)
            await reply_box(interaction, f"Moved to **{author_vc.name}**!", title="VOICE SWITCHED", status="success")
        else:
            await reply_box(interaction, f"Already connected to **{author_vc.name}**!", title="ALREADY CONNECTED", status="info", ephemeral=True)

    # ─────────────────────────────────────────────────────────────
    # Slash Command: /tts leave
    # ─────────────────────────────────────────────────────────────
    @tts_group.command(name="leave", description="Disconnect Friday from voice channel and stop TTS.")
    async def tts_leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return await reply_box(interaction, "Friday is not connected to any voice channel.", title="NOT CONNECTED", status="info", ephemeral=True)

        gid = str(interaction.guild_id)
        cfg = self.get_guild_cfg(gid)
        cfg["enabled"] = False
        db.save_data()

        skip_ev = self._skip_events.get(interaction.guild_id)
        if skip_ev:
            skip_ev.set()

        await vc.disconnect()
        await reply_box(interaction, "Disconnected from voice channel.", title="DISCONNECTED", status="info")

    # ─────────────────────────────────────────────────────────────
    # Slash Command: /tts voice
    # ─────────────────────────────────────────────────────────────
    @tts_group.command(name="voice", description="Choose Friday's TTS voice personality.")
    @app_commands.describe(preset="Select a preset directly or leave blank to open menu")
    @app_commands.choices(preset=[
        app_commands.Choice(name=p["name"], value=k) for k, p in TTS_VOICE_PRESETS.items()
    ])
    async def tts_voice(self, interaction: discord.Interaction, preset: Optional[str] = None):
        gid = str(interaction.guild_id)
        cfg = self.get_guild_cfg(gid)

        if preset and preset in TTS_VOICE_PRESETS:
            cfg["voice_preset"] = preset
            db.save_data()
            p = TTS_VOICE_PRESETS[preset]
            return await reply_box(
                interaction,
                f"Friday's voice personality set to **{p['name']}** {p['badge']}!",
                title="TTS VOICE UPDATED",
                status="success"
            )

        current = cfg.get("voice_preset", DEFAULT_PRESET_KEY)
        embed = make_box_embed(
            title="SELECT FRIDAY TTS VOICE",
            description="Choose your preferred voice personality for Friday's text reading from the menu below:",
            status="info"
        )
        view = TTSVoiceSelectView(current)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ─────────────────────────────────────────────────────────────
    # Slash Command: /tts skip
    # ─────────────────────────────────────────────────────────────
    @tts_group.command(name="skip", description="Skip the currently spoken TTS phrase.")
    async def tts_skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not getattr(vc, "_is_tts_playing", False):
            return await reply_box(interaction, "Friday is not currently speaking any TTS message.", title="NOTHING TO SKIP", status="info", ephemeral=True)

        skip_ev = self._skip_events.get(interaction.guild_id)
        if skip_ev:
            skip_ev.set()

        await reply_box(interaction, "Skipped current TTS message.", title="TTS SKIPPED", status="success")

    # ─────────────────────────────────────────────────────────────
    # Slash Command: /tts status
    # ─────────────────────────────────────────────────────────────
    @tts_group.command(name="status", description="Check Friday's current TTS configuration and voice state.")
    async def tts_status(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = self.get_guild_cfg(gid)
        vc = interaction.guild.voice_client

        preset = TTS_VOICE_PRESETS.get(cfg.get("voice_preset", DEFAULT_PRESET_KEY), TTS_VOICE_PRESETS[DEFAULT_PRESET_KEY])
        vc_name = vc.channel.name if vc and vc.is_connected() else "Not connected"
        status_badge = "🟢 Enabled" if cfg.get("enabled", False) else "🔴 Disabled"
        chan_text = f"<#{cfg['channel_id']}>" if cfg.get("channel_id") else "Any Voice Text Chat"

        desc = (
            f"### Friday Text-to-Speech Engine\n\n"
            f"> • **TTS Status:** `{status_badge}`\n"
            f"> • **Connected VC:** `{vc_name}`\n"
            f"> • **Voice Preset:** **{preset['name']}** {preset['badge']}\n"
            f"> • **Pitch / Speed:** `{preset['pitch']}` / `{preset['rate']}`\n"
            f"> • **Listening Channel:** {chan_text}\n"
            f"> • **Max Phrase Length:** `{cfg.get('max_length', 150)} characters`\n"
            f"> • **Auto-Mute on Music:** `{'Yes (Active)' if cfg.get('auto_mute_music', True) else 'No'}`\n"
        )
        await reply_box(interaction, desc, title="TTS CONFIGURATION", status="info")

    # ─────────────────────────────────────────────────────────────
    # Fast In-Chat Prefix Commands (!tts on, !tts off, !tts join, !tts leave, !tts skip)
    # ─────────────────────────────────────────────────────────────
    @commands.group(name="tts", invoke_without_command=True)
    async def tts_prefix(self, ctx: commands.Context):
        """Prefix helper command."""
        await ctx.send("🔊 Use `!tts on`, `!tts off`, `!tts join`, `!tts leave`, or `/tts enable`.")

    @tts_prefix.command(name="on")
    async def tts_prefix_on(self, ctx: commands.Context):
        if not (HAS_EDGE_TTS or get_edge_tts()):
            return await ctx.send("⚠️ `edge-tts` is not installed on the VM host. Run `sudo pip install --upgrade edge-tts --break-system-packages` and then `sudo systemctl restart friday`.")
        vc = ctx.guild.voice_client
        author_vc = getattr(ctx.author.voice, "channel", None) if ctx.author.voice else None
        target_vc = vc.channel if (vc and vc.is_connected()) else author_vc
        if not target_vc:
            return await ctx.send("❌ Either you or Friday must be in a voice channel first!")
        if not vc:
            await target_vc.connect()
        gid = str(ctx.guild.id)
        cfg = self.get_guild_cfg(gid)
        cfg["enabled"] = True
        db.save_data()
        self.ensure_worker(ctx.guild.id)
        await ctx.send(f"🌸 **Friday TTS is now ON in {target_vc.name}!** Speak in chat and I'll read it aloud.")

    @tts_prefix.command(name="off")
    async def tts_prefix_off(self, ctx: commands.Context):
        gid = str(ctx.guild.id)
        cfg = self.get_guild_cfg(gid)
        cfg["enabled"] = False
        db.save_data()
        skip_ev = self._skip_events.get(ctx.guild.id)
        if skip_ev:
            skip_ev.set()
        await ctx.send("🔇 **Friday TTS is now OFF.**")

    @tts_prefix.command(name="join")
    async def tts_prefix_join(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ You must be in a voice channel first!")
        vc = ctx.guild.voice_client
        if not vc:
            await ctx.author.voice.channel.connect()
        else:
            await vc.move_to(ctx.author.voice.channel)
        await ctx.send(f"🔊 Connected to **{ctx.author.voice.channel.name}**!")

    @tts_prefix.command(name="leave")
    async def tts_prefix_leave(self, ctx: commands.Context):
        vc = ctx.guild.voice_client
        if vc:
            gid = str(ctx.guild.id)
            cfg = self.get_guild_cfg(gid)
            cfg["enabled"] = False
            db.save_data()
            await vc.disconnect()
            await ctx.send("👋 Disconnected from voice.")
        else:
            await ctx.send("I am not connected to voice.")

    @tts_prefix.command(name="skip")
    async def tts_prefix_skip(self, ctx: commands.Context):
        vc = ctx.guild.voice_client
        if vc and getattr(vc, "_is_tts_playing", False):
            skip_ev = self._skip_events.get(ctx.guild.id)
            if skip_ev:
                skip_ev.set()
            await ctx.send("⏭️ Skipped current TTS message.")
        else:
            await ctx.send("Friday is not speaking any TTS message right now.")


async def setup(bot: commands.Bot):
    await bot.add_cog(TTSCog(bot))

