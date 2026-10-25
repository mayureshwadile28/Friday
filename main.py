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
intents.moderation = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

def configure_command_dm_restrictions(tree):
    """
    Restricts all commands to guilds except /avatar and /avtar.
    Setting guild_only=True sends dm_permission: False in Discord's API sync payload,
    which instructs Discord clients to completely hide them in Direct Messages.
    """
    for cmd in tree.get_commands():
        if cmd.name in ("avatar", "avtar"):
            cmd.guild_only = False
        else:
            try:
                cmd.guild_only = True
            except Exception:
                pass

@bot.tree.interaction_check
async def dm_interaction_guard(interaction: discord.Interaction) -> bool:
    """Blocks any server commands from executing in Direct Messages (only avatar/avtar allowed)."""
    if interaction.guild is None:
        cmd_name = interaction.command.name if interaction.command else ""
        if cmd_name not in ("avatar", "avtar"):
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
        "cogs.backup"
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

    # 1. Clean up guild-level duplicates so commands appear only ONCE
    for g in bot.guilds:
        try:
            bot.tree.clear_commands(guild=g)
            await bot.tree.sync(guild=g)
            print(f"🧹 Cleaned guild command duplicates in '{g.name}'")
        except Exception as e:
            print(f"Duplicate cleanup note for '{g.name}': {e}")

    # 2. Register one clean global command list with DM restrictions applied
    try:
        configure_command_dm_restrictions(bot.tree)
        synced_global = await bot.tree.sync()
        print(f"✅ One clean list: {len(synced_global)} global slash commands registered (DM restrictions active: only /avatar visible in DMs).")
    except Exception as e:
        print(f"Global sync warning: {e}")

@bot.command(name='sync')
@commands.has_permissions(administrator=True)
async def prefix_sync(ctx):
    """Admin command: Type !sync in any channel to remove duplicates and sync commands."""
    msg = await ctx.send("🧹 Cleaning duplicates and syncing slash commands...")
    try:
        # Clear guild-level duplicate commands
        bot.tree.clear_commands(guild=ctx.guild)
        await bot.tree.sync(guild=ctx.guild)
        # Sync clean global commands with DM restrictions
        configure_command_dm_restrictions(bot.tree)
        synced = await bot.tree.sync()
        await msg.edit(content=f"✅ **Duplicates Removed!** {len(synced)} unique slash commands active. Press `Ctrl+R` on Discord to refresh!")
    except Exception as e:
        await msg.edit(content=f"❌ Sync failed: {e}")

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
