import discord
from discord.ext import commands
import os, sys
from dotenv import load_dotenv

# Ensure unbuffered / line-buffered output so journalctl and logs appear immediately
try:
    sys.stdout.reconfigure(line_buffering=True, encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(line_buffering=True, encoding='utf-8', errors='replace')
except Exception:
    pass

# Ensure safe UTF-8 output and 1ms high-precision timer on Windows
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

# Auto-install missing packages on cloud container startup if needed
for import_name, pkg_name in [("easy_pil", "easy-pil"), ("yt_dlp", "yt-dlp"), ("PIL", "Pillow"), ("pyjokes", "pyjokes"), ("chat_exporter", "chat-exporter")]:
    try:
        __import__(import_name)
    except ImportError:
        import subprocess
        print(f"📦 Auto-installing missing dependency '{pkg_name}'...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])
            print(f"✅ Successfully installed '{pkg_name}'!")
        except Exception as e:
            print(f"⚠️ Failed to auto-install {pkg_name}: {e}")

# Always ensure yt-dlp is updated to latest release on startup (fixes YouTube signature & cipher rotations)
try:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"], check=False)
except Exception:
    pass

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
intents.presences = True
intents.moderation = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

def configure_command_dm_restrictions(tree):
    """
    Restricts all commands to guilds except /avatar and /vip.
    Setting guild_only=True sends dm_permission: False in Discord's API sync payload,
    which instructs Discord clients to completely hide them in Direct Messages.
    """
    for cmd in tree.get_commands():
        if cmd.name in ("avatar", "vip"):
            cmd.guild_only = False
        else:
            try:
                cmd.guild_only = True
            except Exception:
                pass

@bot.tree.interaction_check
async def dm_interaction_guard(interaction: discord.Interaction) -> bool:
    """Blocks any server commands from executing in Direct Messages (only avatar/vip allowed)."""
    if interaction.guild is None:
        cmd_name = interaction.command.name if interaction.command else ""
        if cmd_name not in ("avatar", "vip"):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "🔒 This command is only available inside servers, not in Direct Messages.",
                    ephemeral=True
                )
            return False
    return True

@bot.event
async def on_ready():
    print(f'System online: {bot.user.name} is connected to Discord!')
    
    # Auto-sync root music.py into cogs/music.py if user dropped it into root folder
    root_music = os.path.join(os.path.dirname(__file__), "music.py")
    cog_music = os.path.join(os.path.dirname(__file__), "cogs", "music.py")
    if os.path.exists(root_music) and os.path.exists(cog_music):
        try:
            import shutil
            if os.path.getmtime(root_music) > os.path.getmtime(cog_music):
                shutil.copy2(root_music, cog_music)
                print("🔄 Auto-synced updated music.py from root into cogs/music.py!")
        except Exception:
            pass

    # Load all cogs
    cogs_list = [
        "cogs.moderation",
        "cogs.security",
        "cogs.anti_abuse",
        "cogs.leveling",
        "cogs.reaction_roles",
        "cogs.expressions",
        "cogs.privacy",
        "cogs.utility",
        "cogs.announcements",
        "cogs.tickets",
        "cogs.media",
        "cogs.music",
        "cogs.afk",
        "cogs.welcomer",
        "cogs.ai_chat",
        "cogs.temp_voice",
        "cogs.backup",
        "cogs.giveaways",
        "cogs.birthdays",
        "cogs.applications",
        "cogs.activity",
        "cogs.invite_tracker",
        "cogs.booster_perks",
        "cogs.court",
        "cogs.tictactoe",
        "cogs.ludo",
        "cogs.economy",
        "cogs.tts"
    ]
    for cog in cogs_list:
        try:
            await bot.load_extension(cog)
            print(f"Loaded {cog}")
        except Exception as e:
            print(f"Failed to load {cog}: {e}")

    # Clean online presence (removes streaming card from profile)
    try:
        await bot.change_presence(status=discord.Status.online, activity=None)
    except Exception as e:
        print(f"Presence warning: {e}")
            
    # Auto-sync security audit channels across all connected guilds on startup/restart
    sec_cog = bot.get_cog("Security")
    if sec_cog:
        for g in bot.guilds:
            try:
                cnt = await sec_cog.auto_sync_security_channels(g)
                print(f"🛡️ Auto-synced {cnt} security channels in '{g.name}'")
            except Exception as e:
                print(f"⚠️ Security sync warning for '{g.name}': {e}")

    # Sync commands globally and purge duplicate guild commands
    try:
        configure_command_dm_restrictions(bot.tree)
        # Purge guild-level duplicate overrides so Discord only keeps the clean global command list
        for g in bot.guilds:
            try:
                bot.tree.clear_commands(guild=g)
                await bot.tree.sync(guild=g)
            except Exception as e:
                pass
        synced_global = await bot.tree.sync()
        print(f"✅ One clean list: {len(synced_global)} global slash commands registered (all duplicate guild commands cleared).")
    except Exception as e:
        print(f"Global sync warning: {e}")

@bot.command(name="sync")
async def force_sync_commands(ctx: commands.Context):
    """Admin command to force-sync slash commands cleanly without duplicates."""
    # Check permissions with clear error response instead of silent drop
    is_admin = False
    if ctx.guild and ctx.author.id == ctx.guild.owner_id:
        is_admin = True
    elif await bot.is_owner(ctx.author):
        is_admin = True
    elif getattr(ctx.author, "guild_permissions", None) and (ctx.author.guild_permissions.administrator or ctx.author.guild_permissions.manage_guild):
        is_admin = True

    if not is_admin:
        return await ctx.send("❌ You need **Administrator** or **Server Owner** permissions to sync slash commands.")

    msg = await ctx.send("⏳ Registering and syncing all slash commands cleanly without duplicates...")
    try:
        # If cogs.economy somehow wasn't loaded, dynamically load it now
        if not bot.get_cog("Economy"):
            try:
                await bot.load_extension("cogs.economy")
                print("⚡ Dynamically loaded cogs.economy during sync command.")
            except Exception as ce:
                print(f"⚠️ Error loading cogs.economy: {ce}")
                await ctx.send(f"⚠️ Note on `cogs.economy`: `{ce}`")

        if not bot.get_cog("TTS"):
            try:
                await bot.load_extension("cogs.tts")
                print("⚡ Dynamically loaded cogs.tts during sync command.")
            except Exception as te:
                print(f"⚠️ Error loading cogs.tts: {te}")

        configure_command_dm_restrictions(bot.tree)
        # Clear legacy guild duplicates from this server
        bot.tree.clear_commands(guild=ctx.guild)
        await bot.tree.sync(guild=ctx.guild)
        # Global sync
        synced = await bot.tree.sync()
        
        eco_cmds = [c.name for c in synced if c.name in ("balance", "wallet", "work", "daily", "shop", "buy", "rob", "pay", "deposit", "withdraw", "coinflip")]
        await msg.edit(content=(
            f"✅ **{len(synced)} slash commands** synced cleanly without duplicates!\n"
            f"🪙 **Economy commands online ({len(eco_cmds)}):** `/{'`, `/'.join(eco_cmds[:8])}`...\n"
            f"⚡ *All commands are live! If not visible in your slash menu, press `Ctrl + R` in Discord to refresh your client.*"
        ))
    except Exception as e:
        await msg.edit(content=f"❌ Failed to sync slash commands: `{e}`")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"⚠️ Command error on '{getattr(ctx.message, 'content', '')}': {error}")

import threading

def run_dashboard(bot_instance_ref):
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), 'dashboard'))
    try:
        from dashboard.app import app, set_bot_instance
        set_bot_instance(bot_instance_ref)
        port = int(os.environ.get("PORT") or os.environ.get("SERVER_PORT") or 5000)
        print(f"\n🤖 Friday Dashboard running on port {port} (http://0.0.0.0:{port})\n")
        import logging
        app.run(host="0.0.0.0", port=port, use_reloader=False)
    except Exception as e:
        import traceback
        print(f"\n❌ [Dashboard Error] Failed to start web dashboard: {e}\n")
        traceback.print_exc()

if __name__ == "__main__":
    if TOKEN:
        dashboard_thread = threading.Thread(target=run_dashboard, args=(bot,), daemon=True)
        dashboard_thread.start()
        bot.run(TOKEN)
    else:
        print("ERROR: DISCORD_TOKEN missing in .env")
