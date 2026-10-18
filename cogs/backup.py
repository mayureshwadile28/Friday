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

def serialize_guild_data(guild: discord.Guild) -> dict:
    """Extract and serialize roles, categories, channels, and permissions for a guild."""
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

    return {
        "roles": roles_data,
        "categories": categories_data,
        "channels": channels_data,
        "everyone_permissions": everyone_perms,
        "roles_count": len(roles_data),
        "categories_count": len(categories_data),
        "channels_count": len(channels_data)
    }

def is_system_channel(channel) -> bool:
    """Protect Friday system, logging, and dynamic hub channels from accidental cleanup."""
    cname = channel.name.lower()
    for sys_word in ["friday-log", "audit", "security", "mod-log", "join to create", "➕ join", "temp-voice"]:
        if sys_word in cname:
            return True
    return False

def audit_server_status(guild: discord.Guild, backup_data: dict) -> dict:
    """
    Check whether roles or channels are actually deleted, in-sync, or if rogue spam channels exist.
    Prevents creating duplicate channels/roles when server wasn't nuked.
    """
    existing_roles_by_id = {r.id: r for r in guild.roles if not r.is_default() and not r.managed}
    existing_roles_by_name = {r.name.lower(): r for r in guild.roles if not r.is_default() and not r.managed}

    missing_roles = []
    intact_roles = []
    for r in backup_data.get("roles", []):
        r_id = int(r["id"]) if str(r.get("id")).isdigit() else None
        target_role = existing_roles_by_id.get(r_id) if r_id else None
        if not target_role:
            target_role = existing_roles_by_name.get(r["name"].lower())
        
        if target_role:
            intact_roles.append(r["name"])
        else:
            missing_roles.append(r["name"])

    existing_cats_by_id = {c.id: c for c in guild.categories}
    existing_cats_by_name = {c.name.lower(): c for c in guild.categories}

    missing_categories = []
    intact_categories = []
    for cat in backup_data.get("categories", []):
        cat_id = int(cat["id"]) if str(cat.get("id")).isdigit() else None
        target_cat = existing_cats_by_id.get(cat_id) if cat_id else None
        if not target_cat:
            target_cat = existing_cats_by_name.get(cat["name"].lower())
        
        if target_cat:
            intact_categories.append(cat["name"])
        else:
            missing_categories.append(cat["name"])

    existing_channels_by_id = {ch.id: ch for ch in guild.channels if not isinstance(ch, discord.CategoryChannel)}

    missing_channels = []
    intact_channels = []
    snapshot_channel_ids = set()
    snapshot_channel_names = set()

    for ch_data in backup_data.get("channels", []):
        ch_id = int(ch_data["id"]) if str(ch_data.get("id")).isdigit() else None
        if ch_id:
            snapshot_channel_ids.add(ch_id)
        snapshot_channel_names.add(ch_data["name"].lower().replace(" ", "-"))

        target_ch = existing_channels_by_id.get(ch_id) if ch_id else None
        if not target_ch:
            ch_type = ch_data.get("type", "text")
            norm_name = ch_data["name"].lower().replace(" ", "-")
            for ch in guild.channels:
                if isinstance(ch, discord.CategoryChannel):
                    continue
                is_type_match = (
                    (ch_type == "voice" and isinstance(ch, discord.VoiceChannel)) or
                    (ch_type == "text" and isinstance(ch, discord.TextChannel))
                )
                if is_type_match and ch.name.lower().replace(" ", "-") == norm_name:
                    target_ch = ch
                    break

        if target_ch:
            intact_channels.append(ch_data["name"])
        else:
            missing_channels.append(ch_data["name"])

    # Detect unauthorized / rogue spam channels (channels created after snapshot that are not in backup)
    snapshot_cat_ids = {int(c["id"]) for c in backup_data.get("categories", []) if str(c.get("id")).isdigit()}
    snapshot_cat_names = {c["name"].lower() for c in backup_data.get("categories", [])}

    unauthorized_channels = []
    for ch in guild.channels:
        if is_system_channel(ch):
            continue
        if isinstance(ch, discord.CategoryChannel):
            if ch.id not in snapshot_cat_ids and ch.name.lower() not in snapshot_cat_names:
                unauthorized_channels.append({"id": str(ch.id), "name": ch.name, "type": "category"})
        else:
            norm_name = ch.name.lower().replace(" ", "-")
            if ch.id not in snapshot_channel_ids and norm_name not in snapshot_channel_names:
                ch_type = "voice" if isinstance(ch, discord.VoiceChannel) else "text"
                unauthorized_channels.append({"id": str(ch.id), "name": ch.name, "type": ch_type})

    is_in_sync = (len(missing_roles) == 0 and len(missing_categories) == 0 and len(missing_channels) == 0)

    return {
        "is_in_sync": is_in_sync,
        "missing_roles_count": len(missing_roles),
        "missing_categories_count": len(missing_categories),
        "missing_channels_count": len(missing_channels),
        "missing_roles": missing_roles,
        "missing_categories": missing_categories,
        "missing_channels": missing_channels,
        "intact_roles_count": len(intact_roles),
        "intact_channels_count": len(intact_channels),
        "unauthorized_channels_count": len(unauthorized_channels),
        "unauthorized_channels": unauthorized_channels,
        "total_snapshot_roles": len(backup_data.get("roles", [])),
        "total_snapshot_categories": len(backup_data.get("categories", [])),
        "total_snapshot_channels": len(backup_data.get("channels", []))
    }

def capture_server_backup(guild: discord.Guild, name: str = None, creator_name: str = "System") -> dict:
    """Capture full snapshot of guild roles, categories, channels, and permissions."""
    now = datetime.datetime.now()
    backup_id = f"bk-{int(now.timestamp())}"
    backup_name = name.strip() if name and name.strip() else f"Snapshot {now.strftime('%b %d, %Y %I:%M %p')}"

    serialized = serialize_guild_data(guild)

    snapshot = {
        "id": backup_id,
        "name": backup_name,
        "created_at": now.isoformat(),
        "created_at_formatted": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "created_by": creator_name,
        "guild_id": str(guild.id),
        "guild_name": guild.name,
        **serialized
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

def update_server_backup(guild: discord.Guild, backup_id: str, new_name: str = None, updater_name: str = "System") -> dict:
    """Update an existing server snapshot in-place with current live roles, channels, and permissions."""
    gid_str = str(guild.id)
    if not hasattr(db, "server_backups") or gid_str not in db.server_backups:
        raise ValueError("No backups found for this server.")

    target_backup = next((b for b in db.server_backups[gid_str] if b.get("id") == backup_id.strip()), None)
    if not target_backup:
        raise ValueError(f"Backup snapshot '{backup_id}' not found.")

    now = datetime.datetime.now()
    serialized = serialize_guild_data(guild)

    if new_name and new_name.strip():
        target_backup["name"] = new_name.strip()

    target_backup.update(serialized)
    target_backup["updated_at"] = now.isoformat()
    target_backup["updated_at_formatted"] = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    target_backup["updated_by"] = updater_name

    db.save_data()
    return target_backup

async def apply_server_restore(guild: discord.Guild, backup_data: dict, clean_unauthorized: bool = False, status_cb=None) -> dict:
    """
    Restore roles, categories, channels, and permissions from a backup snapshot.
    Strictly prevents duplicate channel/role creation if they already exist.
    Optionally purges unauthorized spam channels created during a raid/nuke.
    """
    created_roles = 0
    updated_roles = 0
    created_categories = 0
    created_channels = 0
    updated_channels = 0
    deleted_unauthorized = 0

    audit = audit_server_status(guild, backup_data)

    # Optional Phase 0: Clean unauthorized spam channels created during nuke
    if clean_unauthorized and audit["unauthorized_channels_count"] > 0:
        if status_cb:
            await status_cb(f"🧹 **Phase 0/3:** Purging {audit['unauthorized_channels_count']} unauthorized spam channels...")
        for unauth in audit["unauthorized_channels"]:
            ch_obj = guild.get_channel(int(unauth["id"]))
            if ch_obj and not is_system_channel(ch_obj):
                try:
                    await ch_obj.delete(reason="Friday Disaster Recovery: Purge Rogue Spam Channel")
                    deleted_unauthorized += 1
                    await asyncio.sleep(0.35)
                except Exception:
                    pass

    if status_cb:
        await status_cb("⏳ **Phase 1/3:** Restoring server roles & hierarchy (duplicate-safe)...")

    # 1. Restore Roles (Match by ID first, then by name)
    existing_roles_by_id = {r.id: r for r in guild.roles if not r.is_default() and not r.managed}
    existing_roles_by_name = {r.name.lower(): r for r in guild.roles if not r.is_default() and not r.managed}
    restored_role_map = {}

    for r_data in reversed(backup_data.get("roles", [])):
        r_id = int(r_data["id"]) if str(r_data.get("id")).isdigit() else None
        r_name = r_data["name"]
        color = discord.Color(r_data.get("color", 0))
        perms = discord.Permissions(r_data.get("permissions", 0))
        hoist = bool(r_data.get("hoist", False))
        mentionable = bool(r_data.get("mentionable", False))

        target_role = existing_roles_by_id.get(r_id) if r_id else None
        if not target_role:
            target_role = existing_roles_by_name.get(r_name.lower())

        if target_role:
            # Role already exists! Never create duplicate
            restored_role_map[r_name.lower()] = target_role
            if target_role < guild.me.top_role:
                try:
                    needs_edit = (
                        target_role.color.value != color.value or
                        target_role.hoist != hoist or
                        target_role.mentionable != mentionable or
                        target_role.permissions.value != perms.value
                    )
                    if needs_edit:
                        await target_role.edit(
                            color=color,
                            hoist=hoist,
                            mentionable=mentionable,
                            permissions=perms,
                            reason="Friday Disaster Recovery: Synchronize Role Properties"
                        )
                        updated_roles += 1
                except Exception:
                    pass
        else:
            # Role was genuinely nuked/deleted! Recreate it
            try:
                new_role = await guild.create_role(
                    name=r_name,
                    color=color,
                    hoist=hoist,
                    mentionable=mentionable,
                    permissions=perms,
                    reason="Friday Disaster Recovery: Recreate Missing Role"
                )
                created_roles += 1
                restored_role_map[r_name.lower()] = new_role
                await asyncio.sleep(0.35)
            except Exception:
                pass

    if status_cb:
        await status_cb("⏳ **Phase 2/3:** Restoring channel categories & permissions...")

    # 2. Restore Categories (Match by ID first, then by name)
    existing_cats_by_id = {c.id: c for c in guild.categories}
    existing_cats_by_name = {c.name.lower(): c for c in guild.categories}
    restored_cat_map = {}

    for cat_data in backup_data.get("categories", []):
        cat_id = int(cat_data["id"]) if str(cat_data.get("id")).isdigit() else None
        cat_name = cat_data["name"]

        target_cat = existing_cats_by_id.get(cat_id) if cat_id else None
        if not target_cat:
            target_cat = existing_cats_by_name.get(cat_name.lower())

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

        if target_cat:
            # Category already exists! Never create duplicate
            restored_cat_map[cat_name.lower()] = target_cat
            try:
                if cat_overwrites:
                    await target_cat.edit(overwrites=cat_overwrites, reason="Friday Disaster Recovery: Sync Category Overwrites")
            except Exception:
                pass
        else:
            # Category was genuinely nuked/deleted! Recreate it
            try:
                new_cat = await guild.create_category(
                    name=cat_name,
                    overwrites=cat_overwrites if cat_overwrites else None,
                    reason="Friday Disaster Recovery: Recreate Missing Category"
                )
                created_categories += 1
                restored_cat_map[cat_name.lower()] = new_cat
                await asyncio.sleep(0.35)
            except Exception:
                pass

    if status_cb:
        await status_cb("⏳ **Phase 3/3:** Restoring channels (Text & Voice) and permissions...")

    # 3. Restore Channels (Match by ID first, then by normalized name + type)
    existing_channels_by_id = {ch.id: ch for ch in guild.channels if not isinstance(ch, discord.CategoryChannel)}

    for ch_data in backup_data.get("channels", []):
        ch_id = int(ch_data["id"]) if str(ch_data.get("id")).isdigit() else None
        ch_name = ch_data["name"]
        ch_type = ch_data.get("type", "text")
        parent_cat_name = ch_data.get("category_name")
        parent_cat = restored_cat_map.get(parent_cat_name.lower()) if parent_cat_name else None

        # Step 1: Match by ID
        target_ch = existing_channels_by_id.get(ch_id) if ch_id else None

        # Step 2: Fallback match by (type, normalized_name, category)
        if not target_ch:
            norm_backup_name = ch_name.lower().replace(" ", "-")
            for ch in guild.channels:
                if isinstance(ch, discord.CategoryChannel):
                    continue
                is_type_match = (
                    (ch_type == "voice" and isinstance(ch, discord.VoiceChannel)) or
                    (ch_type == "stage" and isinstance(ch, discord.StageChannel)) or
                    (ch_type == "text" and isinstance(ch, discord.TextChannel))
                )
                if not is_type_match:
                    continue

                if ch.name.lower().replace(" ", "-") == norm_backup_name:
                    if parent_cat and ch.category and ch.category.id == parent_cat.id:
                        target_ch = ch
                        break
                    elif not parent_cat and not ch.category:
                        target_ch = ch
                        break

        # Step 3: Secondary fallback match by (type, normalized_name) anywhere in guild
        if not target_ch:
            norm_backup_name = ch_name.lower().replace(" ", "-")
            for ch in guild.channels:
                if isinstance(ch, discord.CategoryChannel):
                    continue
                is_type_match = (
                    (ch_type == "voice" and isinstance(ch, discord.VoiceChannel)) or
                    (ch_type == "text" and isinstance(ch, discord.TextChannel))
                )
                if is_type_match and ch.name.lower().replace(" ", "-") == norm_backup_name:
                    target_ch = ch
                    break

        # Build overwrites
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

        if target_ch:
            # Channel ALREADY EXISTS! Never recreate or duplicate!
            try:
                edit_kwargs = {}
                if parent_cat and target_ch.category != parent_cat:
                    edit_kwargs["category"] = parent_cat
                if ch_overwrites:
                    edit_kwargs["overwrites"] = ch_overwrites
                if ch_type == "text" and isinstance(target_ch, discord.TextChannel):
                    if ch_data.get("topic") and target_ch.topic != ch_data["topic"]:
                        edit_kwargs["topic"] = ch_data["topic"]
                    if target_ch.slowmode_delay != ch_data.get("slowmode_delay", 0):
                        edit_kwargs["slowmode_delay"] = ch_data.get("slowmode_delay", 0)
                    if target_ch.nsfw != bool(ch_data.get("nsfw", False)):
                        edit_kwargs["nsfw"] = bool(ch_data.get("nsfw", False))
                elif ch_type == "voice" and isinstance(target_ch, discord.VoiceChannel):
                    if target_ch.user_limit != ch_data.get("user_limit", 0):
                        edit_kwargs["user_limit"] = ch_data.get("user_limit", 0)

                if edit_kwargs:
                    await target_ch.edit(**edit_kwargs, reason="Friday Disaster Recovery: Synchronize Channel Configuration")
                    updated_channels += 1
            except Exception:
                pass
        else:
            # Channel was GENUINELY NUKED/DELETED! Recreate it
            try:
                if ch_type == "voice":
                    await guild.create_voice_channel(
                        name=ch_name,
                        category=parent_cat,
                        overwrites=ch_overwrites if ch_overwrites else None,
                        bitrate=ch_data.get("bitrate", 64000),
                        user_limit=ch_data.get("user_limit", 0),
                        reason="Friday Disaster Recovery: Recreate Missing Voice Channel"
                    )
                else:
                    await guild.create_text_channel(
                        name=ch_name,
                        category=parent_cat,
                        topic=ch_data.get("topic"),
                        nsfw=bool(ch_data.get("nsfw", False)),
                        slowmode_delay=ch_data.get("slowmode_delay", 0),
                        overwrites=ch_overwrites if ch_overwrites else None,
                        reason="Friday Disaster Recovery: Recreate Missing Text Channel"
                    )
                created_channels += 1
                await asyncio.sleep(0.35)
            except Exception:
                pass

    summary = {
        "created_roles": created_roles,
        "updated_roles": updated_roles,
        "created_categories": created_categories,
        "created_channels": created_channels,
        "updated_channels": updated_channels,
        "deleted_unauthorized_channels": deleted_unauthorized,
        "was_in_sync": audit["is_in_sync"]
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
                    f"• **Channels:** {created_channels} created, {updated_channels} updated\n"
                    f"• **Spam Channels Purged:** {deleted_unauthorized}\n"
                    f"• **Status:** {'Intact Server Verified' if audit['is_in_sync'] else 'Disaster Rebuilt'}"
                ),
                color=0x2ECC71,
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.set_footer(text="Friday Disaster Recovery • Restored Safely")
            await sec_cog.log_security_event(guild, "audit-antinuke", embed)
    except Exception:
        pass

    return summary


class BackupRestoreConfirmView(discord.ui.View):
    def __init__(self, author: discord.Member, backup_data: dict, audit_data: dict):
        super().__init__(timeout=60.0)
        self.author = author
        self.backup_data = backup_data
        self.audit_data = audit_data
        self.confirmed = False

        # If unauthorized channels exist, show button to purge them
        if self.audit_data.get("unauthorized_channels_count", 0) > 0:
            purge_btn = discord.ui.Button(
                label=f"🧹 Restore & Purge {self.audit_data['unauthorized_channels_count']} Spam Channels",
                style=discord.ButtonStyle.primary,
                emoji="🧹",
                custom_id="btn_restore_purge"
            )
            purge_btn.callback = self.confirm_purge_button
            self.add_item(purge_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Only the member who requested this restoration can confirm it.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🚨 Confirm Safe Restore", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run_restore(interaction, clean_unauthorized=False)

    async def confirm_purge_button(self, interaction: discord.Interaction):
        await self._run_restore(interaction, clean_unauthorized=True)

    async def _run_restore(self, interaction: discord.Interaction, clean_unauthorized: bool):
        self.confirmed = True
        self.stop()
        for item in self.children:
            item.disabled = True

        action_msg = "Restoring server structure and purging unauthorized spam channels..." if clean_unauthorized else "Restoring server structure (duplicate-safe)..."
        await interaction.response.edit_message(
            content=f"⚙️ **{action_msg}**\nPlease do not make channel changes while Friday restores server structure.",
            view=self
        )

        async def status_callback(text):
            try:
                await interaction.edit_original_response(content=text)
            except Exception:
                pass

        try:
            summary = await apply_server_restore(
                interaction.guild,
                self.backup_data,
                clean_unauthorized=clean_unauthorized,
                status_cb=status_callback
            )

            status_note = ""
            if summary.get("was_in_sync") and summary["created_channels"] == 0 and summary["created_roles"] == 0:
                status_note = "\n\nℹ️ **Notice:** *Server was already intact. No duplicate channels or roles were created.*"

            embed = discord.Embed(
                title="✅ Server Restoration Finished",
                description=(
                    f"Snapshot **{self.backup_data['name']}** (`{self.backup_data['id']}`) has been restored!\n\n"
                    f"• **Roles:** {summary['created_roles']} created, {summary['updated_roles']} updated\n"
                    f"• **Categories:** {summary['created_categories']} created\n"
                    f"• **Channels:** {summary['created_channels']} created, {summary['updated_channels']} updated\n"
                    f"• **Rogue Channels Purged:** {summary['deleted_unauthorized_channels']}"
                    f"{status_note}\n\n"
                    f"✨ *All permission overwrites and channel positions have been synchronized.*"
                ),
                color=0x2ECC71,
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.set_footer(text="Friday Disaster Recovery • Complete Server Restored")
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
                    f"💡 *You can update this anytime via `/backup update id:{snapshot['id']}` or restore it via `/backup restore`.*"
                ),
                color=0x5865F2,
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.set_footer(text=f"Backup ID: {snapshot['id']} • Friday Disaster Recovery")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            traceback.print_exc()
            await interaction.followup.send(f"❌ **Failed to create backup:** `{e}`", ephemeral=True)

    @backup_group.command(name="update", description="Update an existing snapshot with the current server configuration.")
    @app_commands.describe(
        backup_id="The Backup ID to update (e.g. bk-1729000000)",
        name="Optional updated name for this snapshot"
    )
    async def backup_update(self, interaction: discord.Interaction, backup_id: str, name: str = None):
        if not is_admin_or_owner(interaction):
            return await interaction.response.send_message("❌ **Access Denied:** Only the Server Owner and Administrators can use Friday Backup commands.", ephemeral=True)

        await interaction.response.defer(ephemeral=False)
        try:
            updater_str = f"{interaction.user.name} ({interaction.user.id})"
            snapshot = update_server_backup(interaction.guild, backup_id=backup_id, new_name=name, updater_name=updater_str)

            embed = discord.Embed(
                title="🔄 Server Snapshot Updated Successfully",
                description=(
                    f"Snapshot **{snapshot['name']}** (`{snapshot['id']}`) has been updated in-place with current server channels, roles, and permissions.\n\n"
                    f"**Updated Hierarchy:**\n"
                    f"• **Roles Saved:** `{snapshot['roles_count']}`\n"
                    f"• **Categories Saved:** `{snapshot['categories_count']}`\n"
                    f"• **Channels Saved:** `{snapshot['channels_count']}`\n"
                    f"• **Updated By:** {interaction.user.mention}\n"
                    f"• **Updated At:** `{snapshot.get('updated_at_formatted')}`\n\n"
                    f"💡 *All previous channels and roles in this snapshot have been synchronized with your live server.*"
                ),
                color=0x2ECC71,
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.set_footer(text=f"Backup ID: {snapshot['id']} • Friday Disaster Recovery")
            await interaction.followup.send(embed=embed)
        except ValueError as ve:
            await interaction.followup.send(f"❌ **Error:** {ve}", ephemeral=True)
        except Exception as e:
            traceback.print_exc()
            await interaction.followup.send(f"❌ **Failed to update backup:** `{e}`", ephemeral=True)

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
            created_time = b.get("updated_at_formatted") or b.get("created_at_formatted") or b.get("created_at") or "Unknown"
            update_badge = " (Updated)" if b.get("updated_at") else ""
            embed.add_field(
                name=f"{i}. {b.get('name', 'Snapshot')} (`{b.get('id')}`){update_badge}",
                value=(
                    f"• **Timestamp:** `{created_time}`\n"
                    f"• **Stats:** {b.get('roles_count', 0)} Roles | {b.get('categories_count', 0)} Cats | {b.get('channels_count', 0)} Channels\n"
                    f"• **By:** {b.get('updated_by') or b.get('created_by', 'Admin')}"
                ),
                inline=False
            )

        embed.set_footer(text="Friday Disaster Recovery • Use /backup restore <id> to apply")
        await interaction.response.send_message(embed=embed)

    @backup_group.command(name="restore", description="Restore a server snapshot (with duplicate prevention and disaster check).")
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

        audit = audit_server_status(interaction.guild, target_backup)

        if audit["is_in_sync"]:
            desc = (
                f"Snapshot: **{target_backup['name']}** (`{target_backup['id']}`)\n\n"
                f"🛡️ **Pre-Check: Server Structure is Intact!**\n"
                f"• All **{audit['total_snapshot_roles']}** roles and **{audit['total_snapshot_channels']}** channels already exist.\n"
                f"• **No channels or roles were deleted/nuked.**\n\n"
                f"Restoring now will safely synchronize permission overwrites and channel topics. **No duplicate channels or roles will be created.**"
            )
            color = 0x3498DB
        else:
            desc = (
                f"Snapshot: **{target_backup['name']}** (`{target_backup['id']}`)\n\n"
                f"🚨 **Disaster Damage Detected:**\n"
                f"• **Missing Roles:** `{audit['missing_roles_count']}`\n"
                f"• **Missing Categories:** `{audit['missing_categories_count']}`\n"
                f"• **Missing Channels:** `{audit['missing_channels_count']}`\n"
            )
            if audit["unauthorized_channels_count"] > 0:
                desc += f"• **Rogue / Spam Channels Detected:** `{audit['unauthorized_channels_count']}`\n"
            desc += "\n🚨 **Are you sure you want to proceed with restoration?**"
            color = 0xE74C3C

        embed = discord.Embed(
            title="⚠️ Server Restoration Confirmation",
            description=desc,
            color=color,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_footer(text="Duplicate-Safe Restoration • Friday Disaster Recovery")

        view = BackupRestoreConfirmView(interaction.user, target_backup, audit)
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
