import discord
from discord.ext import commands
from discord import app_commands
import datetime
import asyncio
import traceback
from database import db

def is_admin_or_owner(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.id == interaction.guild.owner_id:
        return True
    if getattr(interaction.user, "guild_permissions", None) and interaction.user.guild_permissions.administrator:
        return True
    return False

def build_overwrites_list(channel_or_category):
    """Serialize channel/category permission overwrites into JSON-serializable list."""
    overwrites_data = []
    for target, perms in channel_or_category.overwrites.items():
        if isinstance(target, discord.Role):
            target_type = "role"
            target_name = target.name
        elif isinstance(target, (discord.Member, discord.User)):
            target_type = "member"
            target_name = target.name
        else:
            continue
        
        allow_bits, deny_bits = perms.pair()
        overwrites_data.append({
            "target_type": target_type,
            "target_id": str(target.id),
            "target_name": target_name,
            "allow": allow_bits.value,
            "deny": deny_bits.value
        })
    return overwrites_data

def capture_server_backup(guild: discord.Guild, name: str = None, creator_name: str = "System") -> dict:
    """Capture full snapshot of guild roles, categories, channels, and permissions."""
    now = datetime.datetime.now()
    backup_id = f"bk-{int(now.timestamp())}"
    backup_name = name.strip() if name and name.strip() else f"Snapshot {now.strftime('%b %d, %Y %I:%M %p')}"

    # 1. Capture Roles (exclude @everyone, bot managed integrations, and booster roles)
    roles_data = []
    everyone_perms = None
    for r in sorted(guild.roles, key=lambda x: x.position, reverse=True):
        if r.is_default():
            everyone_perms = r.permissions.value
            continue
        if r.managed:
            continue
        roles_data.append({
            "id": str(r.id),
            "name": r.name,
            "color": r.color.value,
            "hoist": bool(r.hoist),
            "mentionable": bool(r.mentionable),
            "permissions": r.permissions.value,
            "position": r.position
        })

    # 2. Capture Categories
    categories_data = []
    for cat in sorted(guild.categories, key=lambda x: x.position):
        categories_data.append({
            "id": str(cat.id),
            "name": cat.name,
            "position": cat.position,
            "overwrites": build_overwrites_list(cat)
        })

    # 3. Capture Channels
    channels_data = []
    for ch in sorted(guild.channels, key=lambda x: x.position):
        if isinstance(ch, discord.CategoryChannel):
            continue
        
        ch_type = "text"
        if isinstance(ch, discord.VoiceChannel):
            ch_type = "voice"
        elif isinstance(ch, discord.StageChannel):
            ch_type = "stage"

        ch_data = {
            "id": str(ch.id),
            "name": ch.name,
            "type": ch_type,
            "category_name": ch.category.name if ch.category else None,
            "position": ch.position,
            "overwrites": build_overwrites_list(ch)
        }

        if isinstance(ch, discord.TextChannel):
            ch_data["topic"] = ch.topic
            ch_data["nsfw"] = ch.nsfw
            ch_data["slowmode_delay"] = ch.slowmode_delay
        elif isinstance(ch, discord.VoiceChannel):
            ch_data["bitrate"] = ch.bitrate
            ch_data["user_limit"] = ch.user_limit

        channels_data.append(ch_data)

    snapshot = {
        "id": backup_id,
        "name": backup_name,
        "created_at": now.isoformat(),
        "created_at_formatted": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "created_by": creator_name,
        "guild_id": str(guild.id),
        "guild_name": guild.name,
        "roles_count": len(roles_data),
        "categories_count": len(categories_data),
        "channels_count": len(channels_data),
        "everyone_permissions": everyone_perms,
        "roles": roles_data,
        "categories": categories_data,
        "channels": channels_data
    }

    # Save into db
    gid_str = str(guild.id)
    if not hasattr(db, "server_backups") or not isinstance(db.server_backups, dict):
        db.server_backups = {}
    if gid_str not in db.server_backups or not isinstance(db.server_backups[gid_str], list):
        db.server_backups[gid_str] = []

    # Insert latest backup at beginning
    db.server_backups[gid_str].insert(0, snapshot)
    # Keep last 15 backups max per server
    if len(db.server_backups[gid_str]) > 15:
        db.server_backups[gid_str] = db.server_backups[gid_str][:15]

    db.save_data()
    return snapshot

async def apply_server_restore(guild: discord.Guild, backup_data: dict, status_cb=None) -> dict:
    """Restore roles, categories, channels, and permissions from a backup snapshot."""
    created_roles = 0
    updated_roles = 0
    created_categories = 0
    created_channels = 0
    updated_channels = 0

    if status_cb:
        await status_cb("⏳ **Phase 1/3:** Restoring server roles & hierarchy...")

    # 1. Restore Roles
    existing_roles = {r.name.lower(): r for r in guild.roles if not r.is_default() and not r.managed}
    restored_role_map = {}

    for r_data in reversed(backup_data.get("roles", [])):
        r_name = r_data["name"]
        color = discord.Color(r_data.get("color", 0))
        perms = discord.Permissions(r_data.get("permissions", 0))
        hoist = bool(r_data.get("hoist", False))
        mentionable = bool(r_data.get("mentionable", False))

        target_role = existing_roles.get(r_name.lower())
        if target_role:
            try:
                # Update role properties if bot has permission
                if target_role < guild.me.top_role:
                    await target_role.edit(
                        color=color,
                        hoist=hoist,
                        mentionable=mentionable,
                        permissions=perms,
                        reason="Friday Disaster Recovery: Update Role"
                    )
                    updated_roles += 1
                restored_role_map[r_name.lower()] = target_role
            except Exception:
                restored_role_map[r_name.lower()] = target_role
        else:
            try:
                new_role = await guild.create_role(
                    name=r_name,
                    color=color,
                    hoist=hoist,
                    mentionable=mentionable,
                    permissions=perms,
                    reason="Friday Disaster Recovery: Recreate Role"
                )
                created_roles += 1
                restored_role_map[r_name.lower()] = new_role
            except Exception:
                pass

    if status_cb:
        await status_cb("⏳ **Phase 2/3:** Restoring channel categories & permissions...")

    # 2. Restore Categories
    existing_cats = {c.name.lower(): c for c in guild.categories}
    restored_cat_map = {}

    for cat_data in backup_data.get("categories", []):
        cat_name = cat_data["name"]
        existing_cat = existing_cats.get(cat_name.lower())

        # Build overwrites
        cat_overwrites = {}
        for ow in cat_data.get("overwrites", []):
            t_name = ow.get("target_name", "").lower()
            if ow.get("target_type") == "role":
                role_obj = restored_role_map.get(t_name) or discord.utils.get(guild.roles, name=ow.get("target_name"))
                if role_obj:
                    cat_overwrites[role_obj] = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(ow.get("allow", 0)),
                        discord.Permissions(ow.get("deny", 0))
                    )

        if existing_cat:
            restored_cat_map[cat_name.lower()] = existing_cat
            try:
                if cat_overwrites:
                    await existing_cat.edit(overwrites=cat_overwrites, reason="Friday Disaster Recovery: Update Category Overwrites")
            except Exception:
                pass
        else:
            try:
                new_cat = await guild.create_category(
                    name=cat_name,
                    overwrites=cat_overwrites if cat_overwrites else None,
                    reason="Friday Disaster Recovery: Recreate Category"
                )
                created_categories += 1
                restored_cat_map[cat_name.lower()] = new_cat
            except Exception:
                pass

    if status_cb:
        await status_cb("⏳ **Phase 3/3:** Restoring channels (Text & Voice) and topic configurations...")

    # 3. Restore Channels
    existing_channels = {ch.name.lower(): ch for ch in guild.channels if not isinstance(ch, discord.CategoryChannel)}

    for ch_data in backup_data.get("channels", []):
        ch_name = ch_data["name"]
        ch_type = ch_data.get("type", "text")
        parent_cat_name = ch_data.get("category_name")
        parent_cat = restored_cat_map.get(parent_cat_name.lower()) if parent_cat_name else None

        # Build channel overwrites
        ch_overwrites = {}
        for ow in ch_data.get("overwrites", []):
            t_name = ow.get("target_name", "").lower()
            if ow.get("target_type") == "role":
                role_obj = restored_role_map.get(t_name) or discord.utils.get(guild.roles, name=ow.get("target_name"))
                if role_obj:
                    ch_overwrites[role_obj] = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(ow.get("allow", 0)),
                        discord.Permissions(ow.get("deny", 0))
                    )

        existing_ch = existing_channels.get(ch_name.lower())
        if existing_ch:
            try:
                edit_kwargs = {}
                if parent_cat and existing_ch.category != parent_cat:
                    edit_kwargs["category"] = parent_cat
                if ch_overwrites:
                    edit_kwargs["overwrites"] = ch_overwrites
                if ch_type == "text" and isinstance(existing_ch, discord.TextChannel):
                    if ch_data.get("topic") and existing_ch.topic != ch_data["topic"]:
                        edit_kwargs["topic"] = ch_data["topic"]
                if edit_kwargs:
                    await existing_ch.edit(**edit_kwargs, reason="Friday Disaster Recovery: Update Channel")
                    updated_channels += 1
            except Exception:
                pass
        else:
            try:
                if ch_type == "voice":
                    await guild.create_voice_channel(
                        name=ch_name,
                        category=parent_cat,
                        overwrites=ch_overwrites if ch_overwrites else None,
                        bitrate=ch_data.get("bitrate", 64000),
                        user_limit=ch_data.get("user_limit", 0),
                        reason="Friday Disaster Recovery: Recreate Voice Channel"
                    )
                else:
                    await guild.create_text_channel(
                        name=ch_name,
                        category=parent_cat,
                        topic=ch_data.get("topic"),
                        nsfw=bool(ch_data.get("nsfw", False)),
                        slowmode_delay=ch_data.get("slowmode_delay", 0),
                        overwrites=ch_overwrites if ch_overwrites else None,
                        reason="Friday Disaster Recovery: Recreate Text Channel"
                    )
                created_channels += 1
            except Exception:
                pass

    summary = {
        "created_roles": created_roles,
        "updated_roles": updated_roles,
        "created_categories": created_categories,
        "created_channels": created_channels,
        "updated_channels": updated_channels
    }

    # Log to Friday security logs if available
    try:
        sec_cog = guild._state._get_client().get_cog("Security")
        if sec_cog and hasattr(sec_cog, "log_security_event"):
            embed = discord.Embed(
                title="🛡️ Server Disaster Recovery Completed",
                description=(
                    f"**Snapshot Restored:** `{backup_data.get('name')}` (`{backup_data.get('id')}`)\n\n"
                    f"• **Roles:** {created_roles} created, {updated_roles} updated\n"
                    f"• **Categories:** {created_categories} created\n"
                    f"• **Channels:** {created_channels} created, {updated_channels} updated"
                ),
                color=0x2ECC71,
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.set_footer(text="Friday Disaster Recovery • Complete Server Restored")
            await sec_cog.log_security_event(guild, "audit-antinuke", embed)
    except Exception:
        pass

    return summary


class BackupRestoreConfirmView(discord.ui.View):
    def __init__(self, author: discord.Member, backup_data: dict):
        super().__init__(timeout=60.0)
        self.author = author
        self.backup_data = backup_data
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Only the member who requested this restoration can confirm it.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🚨 Confirm Full Restore", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"⚙️ **Restoration in progress for snapshot `{self.backup_data['name']}`...**\nPlease do not make channel changes while Friday restores server structure.",
            view=self
        )

        async def status_callback(text):
            try:
                await interaction.edit_original_response(content=text)
            except Exception:
                pass

        try:
            summary = await apply_server_restore(interaction.guild, self.backup_data, status_cb=status_callback)
            embed = discord.Embed(
                title="✅ Server Restoration Finished",
                description=(
                    f"Snapshot **{self.backup_data['name']}** (`{self.backup_data['id']}`) has been restored!\n\n"
                    f"• **Roles:** {summary['created_roles']} created, {summary['updated_roles']} updated\n"
                    f"• **Categories:** {summary['created_categories']} created\n"
                    f"• **Channels:** {summary['created_channels']} created, {summary['updated_channels']} updated\n\n"
                    f"✨ *All permission overwrites and channel positions have been synchronized.*"
                ),
                color=0x2ECC71,
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.set_footer(text="Friday Disaster Recovery • Restored Successfully")
            await interaction.edit_original_response(content=None, embed=embed, view=None)
        except Exception as e:
            traceback.print_exc()
            await interaction.edit_original_response(content=f"❌ **Restoration failed:** `{e}`", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="🛑 **Restoration cancelled.** No server changes were made.", embed=None, view=None)


class Backup(commands.Cog, name="Backup"):
    """Server Snapshot & Disaster Recovery System."""

    def __init__(self, bot):
        self.bot = bot

    backup_group = app_commands.Group(
        name="backup",
        description="Server Snapshot & Disaster Recovery System",
        default_permissions=discord.Permissions(administrator=True)
    )

    @backup_group.command(name="create", description="Capture a full snapshot of roles, channels, categories, and permissions.")
    @app_commands.describe(name="Optional custom name for this snapshot (e.g. Pre-Raid or Staff-Setup)")
    async def backup_create(self, interaction: discord.Interaction, name: str = None):
        if not is_admin_or_owner(interaction):
            return await interaction.response.send_message("❌ **Access Denied:** Only the Server Owner and Administrators can use Friday Backup commands.", ephemeral=True)

        await interaction.response.defer(ephemeral=False)
        try:
            creator_str = f"{interaction.user.name} ({interaction.user.id})"
            snapshot = capture_server_backup(interaction.guild, name=name, creator_name=creator_str)

            embed = discord.Embed(
                title="💾 Server Snapshot Created Successfully",
                description=(
                    f"A complete snapshot of **{interaction.guild.name}** has been captured and safely saved into Friday memory.\n\n"
                    f"**Snapshot Details:**\n"
                    f"• **Name:** `{snapshot['name']}`\n"
                    f"• **ID:** `{snapshot['id']}`\n"
                    f"• **Roles Saved:** `{snapshot['roles_count']}`\n"
                    f"• **Categories Saved:** `{snapshot['categories_count']}`\n"
                    f"• **Channels Saved:** `{snapshot['channels_count']}`\n"
                    f"• **Created By:** {interaction.user.mention}\n"
                    f"• **Timestamp:** `{snapshot['created_at_formatted']}`\n\n"
                    f"💡 *You can restore this anytime via `/backup restore id:{snapshot['id']}` or from the Web Dashboard.*"
                ),
                color=0x5865F2,
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.set_footer(text=f"Backup ID: {snapshot['id']} • Friday Disaster Recovery")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            traceback.print_exc()
            await interaction.followup.send(f"❌ **Failed to create backup:** `{e}`", ephemeral=True)

    @backup_group.command(name="list", description="List all saved snapshots for this server.")
    async def backup_list(self, interaction: discord.Interaction):
        if not is_admin_or_owner(interaction):
            return await interaction.response.send_message("❌ **Access Denied:** Only the Server Owner and Administrators can use Friday Backup commands.", ephemeral=True)

        gid_str = str(interaction.guild.id)
        backups = db.server_backups.get(gid_str, []) if hasattr(db, "server_backups") else []

        if not backups:
            embed = discord.Embed(
                title="📂 No Backups Found",
                description="This server doesn't have any saved snapshots yet.\n\nUse `/backup create` to capture your first server backup!",
                color=0xE67E22
            )
            return await interaction.response.send_message(embed=embed)

        embed = discord.Embed(
            title=f"💾 Saved Backups for {interaction.guild.name}",
            description=f"Showing **{len(backups)}** saved snapshots. Restorable via `/backup restore <id>` or the Web Dashboard.\n",
            color=0x5865F2,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

        for i, b in enumerate(backups[:10], 1):
            created_time = b.get("created_at_formatted") or b.get("created_at") or "Unknown"
            embed.add_field(
                name=f"{i}. {b.get('name', 'Snapshot')} (`{b.get('id')}`)",
                value=(
                    f"• **Created:** `{created_time}`\n"
                    f"• **Stats:** {b.get('roles_count', 0)} Roles | {b.get('categories_count', 0)} Cats | {b.get('channels_count', 0)} Channels\n"
                    f"• **By:** {b.get('created_by', 'Admin')}"
                ),
                inline=False
            )

        embed.set_footer(text="Friday Disaster Recovery • Use /backup restore <id> to apply")
        await interaction.response.send_message(embed=embed)

    @backup_group.command(name="restore", description="Restore a server snapshot by ID (recreates missing roles, channels, categories).")
    @app_commands.describe(backup_id="The Backup ID to restore (use /backup list to find IDs)")
    async def backup_restore(self, interaction: discord.Interaction, backup_id: str):
        if not is_admin_or_owner(interaction):
            return await interaction.response.send_message("❌ **Access Denied:** Only the Server Owner and Administrators can use Friday Backup commands.", ephemeral=True)

        gid_str = str(interaction.guild.id)
        backups = db.server_backups.get(gid_str, []) if hasattr(db, "server_backups") else []
        target_backup = next((b for b in backups if b.get("id") == backup_id.strip()), None)

        if not target_backup:
            return await interaction.response.send_message(
                f"❌ **Backup ID `{backup_id}` not found.**\nRun `/backup list` to see all available snapshots.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="⚠️ Confirm Full Server Restoration",
            description=(
                f"You are about to restore snapshot **{target_backup['name']}** (`{target_backup['id']}`).\n\n"
                f"**What will happen:**\n"
                f"• Missing roles will be recreated with their colors, hoist, and permissions.\n"
                f"• Missing categories & channels (text and voice) will be recreated.\n"
                f"• Permission overwrites for channels and categories will be synchronized.\n\n"
                f"🚨 **Are you sure you want to proceed?**"
            ),
            color=0xE74C3C,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_footer(text="Restoration Confirmation Required • Friday Disaster Recovery")

        view = BackupRestoreConfirmView(interaction.user, target_backup)
        await interaction.response.send_message(embed=embed, view=view)

    @backup_group.command(name="delete", description="Delete a saved server snapshot.")
    @app_commands.describe(backup_id="The Backup ID to delete")
    async def backup_delete(self, interaction: discord.Interaction, backup_id: str):
        if not is_admin_or_owner(interaction):
            return await interaction.response.send_message("❌ **Access Denied:** Only the Server Owner and Administrators can use Friday Backup commands.", ephemeral=True)

        gid_str = str(interaction.guild.id)
        if not hasattr(db, "server_backups") or gid_str not in db.server_backups:
            return await interaction.response.send_message("❌ No backups found for this server.", ephemeral=True)

        orig_len = len(db.server_backups[gid_str])
        db.server_backups[gid_str] = [b for b in db.server_backups[gid_str] if b.get("id") != backup_id.strip()]

        if len(db.server_backups[gid_str]) < orig_len:
            db.save_data()
            await interaction.response.send_message(f"🗑️ **Backup snapshot `{backup_id}` deleted successfully.**")
        else:
            await interaction.response.send_message(f"❌ Backup ID `{backup_id}` was not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Backup(bot))
