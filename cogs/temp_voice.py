import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import time
from database import db
from response_utils import make_box_embed, reply_box

class VoiceRenameModal(discord.ui.Modal, title="Rename Voice Room"):
    name_input = discord.ui.TextInput(
        label="New Room Name",
        placeholder="e.g. 🎮 Gaming Lounge",
        min_length=1,
        max_length=60,
        required=True
    )

    def __init__(self, channel: discord.VoiceChannel, cog_ref):
        super().__init__()
        self.channel = channel
        self.cog_ref = cog_ref

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.name_input.value.strip()
        try:
            await self.channel.edit(name=new_name)
            await interaction.response.send_message(
                f"✅ Room renamed to **{discord.utils.escape_markdown(new_name)}**!",
                ephemeral=True
            )
            # Update embed if message exists
            await self.cog_ref.update_panel_embed(self.channel)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Friday lacks permission to rename this voice channel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to rename: {e}", ephemeral=True)

class VoiceLimitModal(discord.ui.Modal, title="Set User Limit"):
    limit_input = discord.ui.TextInput(
        label="User Limit (0 for unlimited, 1-99)",
        placeholder="0",
        min_length=1,
        max_length=2,
        required=True
    )

    def __init__(self, channel: discord.VoiceChannel, cog_ref):
        super().__init__()
        self.channel = channel
        self.cog_ref = cog_ref

    async def on_submit(self, interaction: discord.Interaction):
        val = self.limit_input.value.strip()
        if not val.isdigit():
            await interaction.response.send_message("❌ Please enter a valid number between 0 and 99.", ephemeral=True)
            return
        limit = int(val)
        if limit < 0 or limit > 99:
            await interaction.response.send_message("❌ Limit must be between 0 and 99.", ephemeral=True)
            return
        try:
            await self.channel.edit(user_limit=limit)
            limit_str = "Unlimited" if limit == 0 else f"{limit} users"
            await interaction.response.send_message(f"✅ User limit set to **{limit_str}**!", ephemeral=True)
            await self.cog_ref.update_panel_embed(self.channel)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Friday lacks permission to edit channel user limit.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to update limit: {e}", ephemeral=True)

class KickMemberSelect(discord.ui.Select):
    def __init__(self, channel: discord.VoiceChannel, owner_id: int):
        self.channel = channel
        self.owner_id = owner_id
        options = []
        for m in channel.members:
            if m.id != owner_id and not m.bot:
                options.append(discord.SelectOption(
                    label=m.display_name[:25],
                    value=str(m.id),
                    description=f"@{m.name}"[:50],
                    emoji="👤"
                ))
        if not options:
            options.append(discord.SelectOption(
                label="No kickable members",
                value="none",
                description="Only you or bots are in this room."
            ))
        super().__init__(placeholder="Select a member to disconnect...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "none":
            await interaction.response.send_message("No eligible members to kick.", ephemeral=True)
            return
        member = self.channel.guild.get_member(int(val))
        if not member or member not in self.channel.members:
            await interaction.response.send_message("❌ Member is no longer in this channel.", ephemeral=True)
            return
        try:
            await member.move_to(None, reason=f"Disconnected by room owner ({interaction.user.name})")
            await interaction.response.send_message(f"👞 Disconnected **{member.display_name}** from your room.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Friday lacks `Move Members` permission to disconnect them.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error disconnecting member: {e}", ephemeral=True)

class VoiceKickSelectView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, owner_id: int):
        super().__init__(timeout=60)
        self.add_item(KickMemberSelect(channel, owner_id))

class VoiceControlView(discord.ui.View):
    def __init__(self, cog_ref, channel_id: int, owner_id: int):
        super().__init__(timeout=None)
        self.cog_ref = cog_ref
        self.channel_id = channel_id
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Check if the interaction user is the owner or admin
        channel_data = self.cog_ref.active_channels.get(str(self.channel_id))
        current_owner_id = channel_data.get("owner_id") if channel_data else self.owner_id
        
        # If user is clicking Claim button, allow anyone in the VC
        custom_id = interaction.data.get("custom_id", "")
        if custom_id == "vc_btn_claim":
            return True

        if interaction.user.id == current_owner_id or interaction.user.guild_permissions.administrator:
            return True

        await interaction.response.send_message(
            "🔒 Only the room owner (or an Administrator) can adjust these settings.",
            ephemeral=True
        )
        return False

    @discord.ui.button(label="Lock", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="vc_btn_lock")
    async def lock_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Channel no longer exists.", ephemeral=True)
            return

        channel_data = self.cog_ref.active_channels.get(str(self.channel_id), {})
        is_locked = channel_data.get("locked", False)
        new_locked = not is_locked
        channel_data["locked"] = new_locked

        try:
            # Overwrite connect permission for @everyone
            await channel.set_permissions(interaction.guild.default_role, connect=not new_locked)
            # Ensure owner always has connect permission
            await channel.set_permissions(interaction.user, connect=True)

            button.label = "Unlock" if new_locked else "Lock"
            button.style = discord.ButtonStyle.danger if new_locked else discord.ButtonStyle.secondary
            button.emoji = "🔓" if new_locked else "🔒"

            status_msg = "🔒 Room is now **Locked**! Others cannot join without permission." if new_locked else "🔓 Room is now **Unlocked**! Anyone can join."
            await interaction.response.edit_message(view=self)
            await self.cog_ref.update_panel_embed(channel)
            await interaction.followup.send(status_msg, ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Friday lacks `Manage Channels` permission.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to toggle lock: {e}", ephemeral=True)

    @discord.ui.button(label="Hide", style=discord.ButtonStyle.secondary, emoji="👁️", custom_id="vc_btn_hide")
    async def hide_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Channel no longer exists.", ephemeral=True)
            return

        channel_data = self.cog_ref.active_channels.get(str(self.channel_id), {})
        is_hidden = channel_data.get("hidden", False)
        new_hidden = not is_hidden
        channel_data["hidden"] = new_hidden

        try:
            await channel.set_permissions(interaction.guild.default_role, view_channel=not new_hidden)
            await channel.set_permissions(interaction.user, view_channel=True)

            button.label = "Unhide" if new_hidden else "Hide"
            button.style = discord.ButtonStyle.primary if new_hidden else discord.ButtonStyle.secondary
            button.emoji = "👁️"

            status_msg = "👁️ Room is now **Hidden** from the channel list!" if new_hidden else "👁️ Room is now **Visible** to everyone!"
            await interaction.response.edit_message(view=self)
            await self.cog_ref.update_panel_embed(channel)
            await interaction.followup.send(status_msg, ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Friday lacks `Manage Channels` permission.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to toggle visibility: {e}", ephemeral=True)

    @discord.ui.button(label="User Limit", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="vc_btn_limit")
    async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Channel no longer exists.", ephemeral=True)
            return
        await interaction.response.send_modal(VoiceLimitModal(channel, self.cog_ref))

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="vc_btn_rename")
    async def rename_room(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Channel no longer exists.", ephemeral=True)
            return
        await interaction.response.send_modal(VoiceRenameModal(channel, self.cog_ref))

    @discord.ui.button(label="Kick Member", style=discord.ButtonStyle.secondary, emoji="🚫", custom_id="vc_btn_kick")
    async def kick_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Channel no longer exists.", ephemeral=True)
            return
        channel_data = self.cog_ref.active_channels.get(str(self.channel_id), {})
        owner_id = channel_data.get("owner_id", self.owner_id)
        view = VoiceKickSelectView(channel, owner_id)
        await interaction.response.send_message("Select a member from the dropdown below to disconnect them:", view=view, ephemeral=True)

    @discord.ui.button(label="Claim Room", style=discord.ButtonStyle.success, emoji="👑", custom_id="vc_btn_claim")
    async def claim_room(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Channel no longer exists.", ephemeral=True)
            return

        # Ensure user is inside the channel
        if interaction.user not in channel.members:
            await interaction.response.send_message("❌ You must be inside this voice room to claim it.", ephemeral=True)
            return

        channel_data = self.cog_ref.active_channels.get(str(self.channel_id), {})
        current_owner_id = channel_data.get("owner_id")
        current_owner = channel.guild.get_member(current_owner_id) if current_owner_id else None

        # If current owner is still inside the VC
        if current_owner and current_owner in channel.members and current_owner.id != interaction.user.id:
            await interaction.response.send_message(
                f"❌ The current room owner (**{current_owner.display_name}**) is still active in this room.",
                ephemeral=True
            )
            return

        # Transfer ownership
        channel_data["owner_id"] = interaction.user.id
        self.owner_id = interaction.user.id

        # Grant full room manage permissions to new owner
        try:
            await channel.set_permissions(interaction.user, connect=True, speak=True, stream=True, view_channel=True)
        except Exception:
            pass

        await self.cog_ref.update_panel_embed(channel)
        await interaction.response.send_message(
            f"👑 **{interaction.user.display_name}** has claimed ownership of this voice room!",
            ephemeral=False
        )

class TempVoice(commands.Cog):
    """Temporary Voice Channels (Join-to-Create) with in-chat interactive controls."""

    def __init__(self, bot):
        self.bot = bot
        # active_channels: { "channel_id_str": { "guild_id": str, "owner_id": int, "created_at": float, "locked": bool, "hidden": bool, "panel_msg_id": int } }
        self.active_channels = {}
        self._creation_locks = set()

    def get_guild_config(self, guild_id: int) -> dict:
        return db.temp_voice.get(str(guild_id), {})

    def save_guild_config(self, guild_id: int, config: dict):
        db.temp_voice[str(guild_id)] = config
        db.save_data()

    async def update_panel_embed(self, channel: discord.VoiceChannel):
        """Update or refresh the in-chat control embed for a temp voice room."""
        ch_str = str(channel.id)
        data = self.active_channels.get(ch_str)
        if not data or not data.get("panel_msg_id"):
            return

        try:
            owner = channel.guild.get_member(data.get("owner_id"))
            owner_name = owner.display_name if owner else f"User {data.get('owner_id')}"
            is_locked = data.get("locked", False)
            is_hidden = data.get("hidden", False)
            limit = channel.user_limit
            limit_str = "Unlimited" if limit == 0 else f"{limit} users"

            status_icon = "🔴 Locked" if is_locked else "🟢 Public"
            vis_icon = "🙈 Hidden" if is_hidden else "👁️ Visible"

            embed = discord.Embed(
                title="🔊 Temporary Voice Room Controls",
                description=(
                    f"Welcome to your private voice channel, **{owner_name}**!\n"
                    f"Use the interactive buttons below to manage your room."
                ),
                color=0x5865F2
            )
            embed.add_field(name="👑 Room Owner", value=f"<@{data.get('owner_id')}>", inline=True)
            embed.add_field(name="🔒 Room Access", value=f"{status_icon} • {vis_icon}", inline=True)
            embed.add_field(name="👥 User Limit", value=limit_str, inline=True)
            embed.add_field(
                name="🛠️ Quick Actions",
                value="• **Lock/Unlock**: Prevent strangers from joining\n• **Hide/Unhide**: Toggle visibility on server list\n• **User Limit**: Set max occupants\n• **Rename**: Change room name\n• **Kick**: Disconnect unwanted members\n• **Claim**: Take ownership if owner leaves",
                inline=False
            )
            embed.set_footer(text="Friday Voice Hub • Channel auto-deletes when empty")

            msg = await channel.fetch_message(data["panel_msg_id"])
            if msg:
                await msg.edit(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        guild = member.guild
        cfg = self.get_guild_config(guild.id)
        if not cfg or not cfg.get("enabled", False):
            return

        hub_channel_id = str(cfg.get("hub_channel_id", ""))
        category_id = cfg.get("category_id")

        # 1. Member joined the Hub Channel ("Join-to-Create")
        if after.channel and str(after.channel.id) == hub_channel_id:
            # Concurrency lock per member to avoid multiple channels if spamming
            if member.id in self._creation_locks:
                return
            self._creation_locks.add(member.id)

            try:
                # Determine Category
                target_category = None
                if category_id:
                    target_category = guild.get_channel(int(category_id))
                if not target_category and after.channel.category:
                    target_category = after.channel.category

                # Determine Channel Name
                name_template = cfg.get("default_name") or "🔊 {user}'s Room"
                room_name = name_template.replace("{user}", member.display_name).replace("{username}", member.name)[:80]

                # Default User Limit
                user_limit = int(cfg.get("user_limit", 0))

                # Permissions Overwrite
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        connect=True,
                        speak=True,
                        stream=True,
                        view_channel=True
                    ),
                    member: discord.PermissionOverwrite(
                        connect=True,
                        speak=True,
                        stream=True,
                        view_channel=True,
                        move_members=True,
                        mute_members=True
                    ),
                    guild.me: discord.PermissionOverwrite(
                        connect=True,
                        manage_channels=True,
                        move_members=True,
                        view_channel=True
                    )
                }

                # Create the voice channel
                new_vc = await guild.create_voice_channel(
                    name=room_name,
                    category=target_category,
                    user_limit=user_limit,
                    overwrites=overwrites,
                    reason=f"Friday Voice Hub: Temp room created for {member.name}"
                )

                # Move member into their new room
                try:
                    await member.move_to(new_vc, reason="Moved to temporary voice room")
                except discord.HTTPException:
                    # If user disconnected while creating
                    if len(new_vc.members) == 0:
                        await new_vc.delete(reason="Member disconnected before entering temp VC")
                        return

                # Register active channel
                ch_key = str(new_vc.id)
                self.active_channels[ch_key] = {
                    "guild_id": str(guild.id),
                    "channel_name": room_name,
                    "owner_id": member.id,
                    "created_at": time.time(),
                    "locked": False,
                    "hidden": False,
                    "panel_msg_id": None
                }

                # Send interactive Control Panel inside the voice channel's text chat
                view = VoiceControlView(self, new_vc.id, member.id)
                embed = discord.Embed(
                    title="🔊 Temporary Voice Room Controls",
                    description=(
                        f"Welcome to your private voice channel, **{member.display_name}**!\n"
                        f"Use the interactive buttons below to manage your room."
                    ),
                    color=0x5865F2
                )
                embed.add_field(name="👑 Room Owner", value=member.mention, inline=True)
                embed.add_field(name="🔒 Room Access", value="🟢 Public • 👁️ Visible", inline=True)
                embed.add_field(name="👥 User Limit", value="Unlimited" if user_limit == 0 else f"{user_limit} users", inline=True)
                embed.add_field(
                    name="🛠️ Quick Actions",
                    value="• **Lock/Unlock**: Prevent strangers from joining\n• **Hide/Unhide**: Toggle visibility on server list\n• **User Limit**: Set max occupants\n• **Rename**: Change room name\n• **Kick**: Disconnect unwanted members\n• **Claim**: Take ownership if owner leaves",
                    inline=False
                )
                embed.set_footer(text="Friday Voice Hub • Channel auto-deletes when empty")

                try:
                    msg = await new_vc.send(content=member.mention, embed=embed, view=view)
                    self.active_channels[ch_key]["panel_msg_id"] = msg.id
                except Exception as ex:
                    print(f"⚠️ Could not send Voice Control Panel in {new_vc.name}: {ex}")

            except Exception as e:
                print(f"❌ Error creating temp voice channel in '{guild.name}': {e}")
            finally:
                self._creation_locks.discard(member.id)

        # 2. Member left a temporary voice channel -> check if empty
        if before.channel and str(before.channel.id) in self.active_channels:
            vc = before.channel
            # Wait 2 seconds for brief lag / reconnects
            await asyncio.sleep(2)
            if len(vc.members) == 0:
                try:
                    ch_key = str(vc.id)
                    if ch_key in self.active_channels:
                        del self.active_channels[ch_key]
                    await vc.delete(reason="Friday Voice Hub: Temp channel empty")
                except Exception as ex:
                    print(f"⚠️ Error deleting empty temp VC {vc.id}: {ex}")
            else:
                # If owner left, update panel embed
                ch_key = str(vc.id)
                data = self.active_channels.get(ch_key)
                if data and data.get("owner_id") == member.id:
                    await self.update_panel_embed(vc)

    # ───────────────────── Slash Commands Group ─────────────────────
    voice_group = app_commands.Group(name="voice", description="Manage temporary voice rooms and Voice Hub")

    @voice_group.command(name="setup", description="Configure Temporary Voice Channels (Join-to-Create) for this server")
    @app_commands.describe(
        hub_channel="Voice channel users join to create their temp room",
        category="Category where temp channels will spawn (optional)",
        default_name="Name pattern (use {user} for username)",
        user_limit="Default user limit (0 for unlimited, 1-99)"
    )
    @app_commands.default_permissions(administrator=True)
    async def voice_setup(
        self,
        interaction: discord.Interaction,
        hub_channel: discord.VoiceChannel,
        category: discord.CategoryChannel = None,
        default_name: str = "🔊 {user}'s Room",
        user_limit: int = 0
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only Administrators can configure Voice Hub.", ephemeral=True)
            return

        cfg = {
            "enabled": True,
            "hub_channel_id": str(hub_channel.id),
            "category_id": str(category.id) if category else None,
            "default_name": default_name,
            "user_limit": max(0, min(99, user_limit))
        }
        self.save_guild_config(interaction.guild.id, cfg)

        embed = discord.Embed(
            title="✅ Friday Voice Hub Configured!",
            description="Members can now join the Hub channel to automatically spawn their own private rooms.",
            color=0x10B981
        )
        embed.add_field(name="🎙️ Hub Channel", value=hub_channel.mention, inline=True)
        embed.add_field(name="📁 Category", value=category.mention if category else "Same as Hub", inline=True)
        embed.add_field(name="🏷️ Name Template", value=f"`{default_name}`", inline=True)
        embed.add_field(name="👥 User Limit", value="Unlimited" if user_limit == 0 else f"{user_limit} users", inline=True)
        await interaction.response.send_message(embed=embed)

    @voice_group.command(name="autohub", description="Automatically create a '➕ Join to Create' voice channel & category")
    @app_commands.default_permissions(administrator=True)
    async def voice_autohub(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only Administrators can use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        try:
            # 1. Create or find category
            category = discord.utils.get(guild.categories, name="TEMPORARY CHANNELS")
            if not category:
                category = await guild.create_category("TEMPORARY CHANNELS", reason="Friday Voice Hub Auto-Setup")

            # 2. Create hub channel
            hub_vc = await guild.create_voice_channel(
                name="➕ Join to Create",
                category=category,
                reason="Friday Voice Hub Auto-Setup"
            )

            cfg = {
                "enabled": True,
                "hub_channel_id": str(hub_vc.id),
                "category_id": str(category.id),
                "default_name": "🔊 {user}'s Room",
                "user_limit": 0
            }
            self.save_guild_config(guild.id, cfg)

            embed = discord.Embed(
                title="✨ Voice Hub Created Successfully!",
                description=(
                    f"Created category **{category.name}** and voice channel **{hub_vc.name}**!\n\n"
                    f"👉 Tell members to join {hub_vc.mention} to instantly create their custom room."
                ),
                color=0x10B981
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Friday lacks `Manage Channels` permission to create channels/categories.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Auto-setup failed: {e}", ephemeral=True)

    @voice_group.command(name="status", description="View Voice Hub status and active rooms in this server")
    async def voice_status(self, interaction: discord.Interaction):
        cfg = self.get_guild_config(interaction.guild.id)
        enabled = cfg.get("enabled", False)
        hub_id = cfg.get("hub_channel_id")
        hub_ch = interaction.guild.get_channel(int(hub_id)) if hub_id else None

        active_in_guild = [
            (ch_id, data) for ch_id, data in self.active_channels.items()
            if data.get("guild_id") == str(interaction.guild.id)
        ]

        embed = discord.Embed(
            title="🔊 Voice Hub Status",
            color=0x5865F2 if enabled else 0x94A3B8
        )
        embed.add_field(name="Status", value="🟢 Enabled" if enabled else "🔴 Disabled", inline=True)
        embed.add_field(name="Hub Channel", value=hub_ch.mention if hub_ch else "Not Configured", inline=True)
        embed.add_field(name="Active Rooms", value=str(len(active_in_guild)), inline=True)

        if active_in_guild:
            room_lines = []
            for ch_id, data in active_in_guild[:10]:
                ch = interaction.guild.get_channel(int(ch_id))
                name = ch.name if ch else data.get("channel_name", "Room")
                owner = interaction.guild.get_member(data.get("owner_id"))
                owner_name = owner.display_name if owner else f"User {data.get('owner_id')}"
                cnt = len(ch.members) if ch else 0
                lock = "🔒" if data.get("locked") else "🔓"
                room_lines.append(f"• **{name}** ({lock}) — Owner: `{owner_name}` | Members: **{cnt}**")
            embed.add_field(name="Active Rooms List", value="\n".join(room_lines), inline=False)

        await interaction.response.send_message(embed=embed)

    @voice_group.command(name="lock", description="Lock your current temporary voice room")
    async def voice_lock(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc or str(vc.id) not in self.active_channels:
            await interaction.response.send_message("❌ You are not inside an active temporary voice room.", ephemeral=True)
            return

        data = self.active_channels[str(vc.id)]
        if interaction.user.id != data.get("owner_id") and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only the room owner can lock this room.", ephemeral=True)
            return

        data["locked"] = True
        await vc.set_permissions(interaction.guild.default_role, connect=False)
        await vc.set_permissions(interaction.user, connect=True)
        await self.update_panel_embed(vc)
        await interaction.response.send_message("🔒 Your room is now **Locked**! Others cannot join.", ephemeral=True)

    @voice_group.command(name="unlock", description="Unlock your current temporary voice room")
    async def voice_unlock(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc or str(vc.id) not in self.active_channels:
            await interaction.response.send_message("❌ You are not inside an active temporary voice room.", ephemeral=True)
            return

        data = self.active_channels[str(vc.id)]
        if interaction.user.id != data.get("owner_id") and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only the room owner can unlock this room.", ephemeral=True)
            return

        data["locked"] = False
        await vc.set_permissions(interaction.guild.default_role, connect=True)
        await self.update_panel_embed(vc)
        await interaction.response.send_message("🔓 Your room is now **Unlocked**! Anyone can join.", ephemeral=True)

    @voice_group.command(name="limit", description="Set user limit for your temporary voice room")
    @app_commands.describe(limit="Maximum number of users allowed (0 for unlimited, 1-99)")
    async def voice_limit(self, interaction: discord.Interaction, limit: int):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc or str(vc.id) not in self.active_channels:
            await interaction.response.send_message("❌ You are not inside an active temporary voice room.", ephemeral=True)
            return

        data = self.active_channels[str(vc.id)]
        if interaction.user.id != data.get("owner_id") and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only the room owner can set the limit.", ephemeral=True)
            return

        limit = max(0, min(99, limit))
        await vc.edit(user_limit=limit)
        await self.update_panel_embed(vc)
        lim_str = "Unlimited" if limit == 0 else f"{limit} users"
        await interaction.response.send_message(f"✅ User limit set to **{lim_str}**!", ephemeral=True)

    @voice_group.command(name="name", description="Rename your temporary voice room")
    @app_commands.describe(new_name="New name for the room")
    async def voice_name(self, interaction: discord.Interaction, new_name: str):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc or str(vc.id) not in self.active_channels:
            await interaction.response.send_message("❌ You are not inside an active temporary voice room.", ephemeral=True)
            return

        data = self.active_channels[str(vc.id)]
        if interaction.user.id != data.get("owner_id") and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only the room owner can rename this room.", ephemeral=True)
            return

        new_name = new_name.strip()[:60]
        await vc.edit(name=new_name)
        data["channel_name"] = new_name
        await self.update_panel_embed(vc)
        await interaction.response.send_message(f"✅ Renamed room to **{discord.utils.escape_markdown(new_name)}**!", ephemeral=True)

    @voice_group.command(name="kick", description="Disconnect a member from your temporary voice room")
    @app_commands.describe(member="Member to disconnect")
    async def voice_kick(self, interaction: discord.Interaction, member: discord.Member):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc or str(vc.id) not in self.active_channels:
            await interaction.response.send_message("❌ You are not inside an active temporary voice room.", ephemeral=True)
            return

        data = self.active_channels[str(vc.id)]
        if interaction.user.id != data.get("owner_id") and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only the room owner can kick members.", ephemeral=True)
            return

        if member not in vc.members:
            await interaction.response.send_message(f"❌ **{member.display_name}** is not in this voice channel.", ephemeral=True)
            return

        if member.id == interaction.user.id:
            await interaction.response.send_message("❌ You cannot kick yourself from your own room.", ephemeral=True)
            return

        try:
            await member.move_to(None, reason=f"Disconnected by room owner ({interaction.user.name})")
            await interaction.response.send_message(f"👞 Disconnected **{member.display_name}** from your room.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Friday lacks `Move Members` permission.", ephemeral=True)

    @voice_group.command(name="claim", description="Claim ownership of the room if the owner left")
    async def voice_claim(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc or str(vc.id) not in self.active_channels:
            await interaction.response.send_message("❌ You are not inside an active temporary voice room.", ephemeral=True)
            return

        data = self.active_channels[str(vc.id)]
        current_owner_id = data.get("owner_id")
        current_owner = interaction.guild.get_member(current_owner_id) if current_owner_id else None

        if current_owner and current_owner in vc.members and current_owner.id != interaction.user.id:
            await interaction.response.send_message(
                f"❌ The current room owner (**{current_owner.display_name}**) is still in this room.",
                ephemeral=True
            )
            return

        data["owner_id"] = interaction.user.id
        await vc.set_permissions(interaction.user, connect=True, speak=True, stream=True, view_channel=True)
        await self.update_panel_embed(vc)
        await interaction.response.send_message(f"👑 You have successfully claimed ownership of **{vc.name}**!")

async def setup(bot):
    await bot.add_cog(TempVoice(bot))
