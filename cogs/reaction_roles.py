import discord
from discord.ext import commands
from discord import app_commands
import re
import asyncio
from typing import Optional, List, Dict, Any, Union
from database import db
from emoji_utils import replace_plain_emojis, format_embed_description


def find_role_for_emoji(panel_roles: dict, emoji: Union[discord.PartialEmoji, discord.Emoji, str]) -> Optional[int]:
    """Universal robust emoji-to-role resolver matching across raw strings, snowflake IDs, names, and Unicode."""
    if not isinstance(panel_roles, dict) or not emoji:
        return None

    e_str = str(emoji).strip()
    e_id = str(getattr(emoji, "id", "") or "")
    e_name = str(getattr(emoji, "name", "") or "").strip(":")

    # 1. Direct match with str(emoji)
    if e_str in panel_roles:
        val = panel_roles[e_str]
        return int(val) if str(val).isdigit() else None

    # 2. Match by custom snowflake ID (highest precision for custom emojis)
    if e_id and e_id != "None":
        if e_id in panel_roles:
            val = panel_roles[e_id]
            return int(val) if str(val).isdigit() else None
        for k, val in panel_roles.items():
            k_str = str(k)
            if k_str == e_id or f":{e_id}>" in k_str or f":{e_id}" in k_str:
                return int(val) if str(val).isdigit() else None

    # 3. Match by emoji name (:name:)
    if e_name:
        if e_name in panel_roles:
            val = panel_roles[e_name]
            return int(val) if str(val).isdigit() else None
        if f":{e_name}:" in panel_roles:
            val = panel_roles[f":{e_name}:"]
            return int(val) if str(val).isdigit() else None
        for k, val in panel_roles.items():
            k_str = str(k).strip(":")
            if k_str.lower() == e_name.lower():
                return int(val) if str(val).isdigit() else None
            m = re.match(r'<a?:([a-zA-Z0-9_]+):[0-9]+>', str(k))
            if m and m.group(1).lower() == e_name.lower():
                return int(val) if str(val).isdigit() else None

    # 4. Unicode match without variation selectors (e.g. \ufe0f)
    clean_u = e_str.replace('\ufe0f', '').strip()
    for k, val in panel_roles.items():
        if str(k).replace('\ufe0f', '').strip() == clean_u:
            return int(val) if str(val).isdigit() else None

    return None


class ReactionRoleSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption], panel_id: str, exclusive: bool = True):
        super().__init__(
            placeholder="Select a role to claim...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"rr_sel:{panel_id}"
        )
        self.panel_id = panel_id
        self.exclusive = exclusive

    async def callback(self, interaction: discord.Interaction):
        # Handled centrally by on_interaction to prevent race conditions and duplicate executions
        pass


class ReactionRoleSelectView(discord.ui.View):
    def __init__(self, options: list[discord.SelectOption], panel_id: str, exclusive: bool = True):
        super().__init__(timeout=None)
        self.panel_id = panel_id
        self.select_item = ReactionRoleSelect(options=options, panel_id=panel_id, exclusive=exclusive)
        self.add_item(self.select_item)


class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._processing = set()

    async def process_role_selection(self, interaction: discord.Interaction, selected_val: Optional[str], panel_id: Optional[str] = None):
        """Unified, 24/7 atomic role assigner for self-role dropdowns.
        Works across bot restarts, missing DB records, and raw component interactions."""
        # Always ensure interaction is acknowledged immediately so Discord never times out
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception as e:
                print(f"[ReactionRoles] Defer warning: {e}", flush=True)

        async def reply(text: str):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(text, ephemeral=True)
                else:
                    await interaction.response.send_message(text, ephemeral=True)
                print(f"[ReactionRoles] Reply delivered: {text}", flush=True)
            except Exception as e:
                print(f"[ReactionRoles] Failed to deliver reply: {e}", flush=True)

        if not selected_val:
            print("[ReactionRoles] Warning: selected_val is empty, aborting.", flush=True)
            return

        print(f"[ReactionRoles] Processing role selection: val='{selected_val}', panel='{panel_id}', user='{interaction.user}'", flush=True)

        try:
            guild = interaction.guild
            member = interaction.user

            if guild and not isinstance(member, discord.Member):
                member = guild.get_member(interaction.user.id)
                if not member:
                    try:
                        member = await guild.fetch_member(interaction.user.id)
                    except Exception:
                        member = None

            if not guild or not isinstance(member, discord.Member):
                await reply("❌ Error: Could not verify server member.")
                return

            msg = interaction.message
            msg_id = str(msg.id) if msg else None
            p_id = str(panel_id) if panel_id else (msg_id or "")

            # Extract all role IDs across database AND message components directly
            all_role_ids = set()

            # 1. From database mappings
            for pid_candidate in (p_id, msg_id):
                if pid_candidate:
                    p_map = getattr(db, "reaction_roles", {}).get(pid_candidate, {})
                    if isinstance(p_map, dict):
                        for r_id in p_map.values():
                            if isinstance(r_id, int):
                                all_role_ids.add(r_id)
                            elif isinstance(r_id, str) and r_id.isdigit():
                                all_role_ids.add(int(r_id))

                    meta = getattr(db, "reaction_roles_meta", {}).get(pid_candidate, {})
                    if isinstance(meta, dict):
                        for opt in meta.get("options", []):
                            val = opt.get("value")
                            if val and str(val).isdigit():
                                all_role_ids.add(int(val))

            # 2. Directly from Discord message components (100% resilient even if DB has no record)
            if msg and hasattr(msg, "components"):
                for comp in msg.components:
                    children = getattr(comp, "children", [comp])
                    for child in children:
                        opts = getattr(child, "options", None)
                        if opts and isinstance(opts, (list, tuple)):
                            for opt in opts:
                                val = getattr(opt, "value", None)
                                if val and str(val).isdigit():
                                    all_role_ids.add(int(val))

            # Determine exclusive mode (default True)
            meta_exclusive = True
            for pid_candidate in (p_id, msg_id):
                if pid_candidate:
                    m = getattr(db, "reaction_roles_meta", {}).get(pid_candidate)
                    if isinstance(m, dict) and "exclusive" in m:
                        meta_exclusive = bool(m.get("exclusive", True))
                        break

            # Case A: Clear / Remove Role
            if selected_val == "clear":
                roles_to_remove = [r for r in member.roles if r.id in all_role_ids]
                if roles_to_remove:
                    try:
                        await member.remove_roles(*roles_to_remove, reason="Reaction Role: Cleared self-role selection")
                        await reply("🗑️ Successfully removed your role from this panel.")
                    except discord.Forbidden:
                        await reply("❌ Friday lacks permission or role hierarchy to modify your roles.")
                    except Exception as e:
                        await reply(f"❌ Error removing role: {e}")
                else:
                    await reply("ℹ️ You do not currently have any roles from this panel.")
                return

            # Case B: Assign Selected Role
            if not str(selected_val).isdigit():
                await reply("❌ Invalid role selection.")
                return

            target_role_id = int(selected_val)
            target_role = guild.get_role(target_role_id)
            if not target_role:
                await reply("❌ Error: The selected role no longer exists on this server.")
                return

            bot_member = guild.me or guild.get_member(self.bot.user.id)
            if bot_member and target_role >= bot_member.top_role:
                await reply(f"❌ Error: Friday's highest role is not high enough to assign **{target_role.name}**. Please move Friday's role higher in Server Settings > Roles.")
                return

            if target_role in member.roles:
                await reply(f"ℹ️ You already have the **@{target_role.name}** role.")
                return

            roles_to_remove = []
            if meta_exclusive:
                for r in member.roles:
                    if r.id in all_role_ids and r.id != target_role_id:
                        if not bot_member or r < bot_member.top_role:
                            roles_to_remove.append(r)

            try:
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason="Reaction Role: Swapped role selection")
                await member.add_roles(target_role, reason="Reaction Role: Claimed role via dropdown")
                await reply(f"✅ Successfully assigned the **@{target_role.name}** role!")
                print(f"[ReactionRoles] Successfully assigned role {target_role.name} ({target_role.id}) to {member.name}", flush=True)
            except discord.Forbidden:
                await reply("❌ Friday lacks permission or role hierarchy to assign this role. Please ensure Friday's role is above the target role.")
            except Exception as e:
                await reply(f"❌ Error modifying roles: {e}")

        except Exception as e:
            import traceback
            print(f"[ReactionRoles] Unexpected error in process_role_selection: {e}", flush=True)
            traceback.print_exc()
            await reply(f"❌ Error processing role selection: {e}")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Global interaction listener: catches any self-role dropdown 24/7 even across restarts."""
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = str(interaction.data.get("custom_id", "") if interaction.data else "")
        if not custom_id.startswith("rr_sel:"):
            return

        print(f"[ReactionRoles] on_interaction received! custom_id='{custom_id}' user='{interaction.user}'", flush=True)

        # Acknowledge immediately within milliseconds to prevent Discord "didn't respond in time" error
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception as e:
                print(f"[ReactionRoles] on_interaction defer warning: {e}", flush=True)

        values = interaction.data.get("values", []) if interaction.data else []
        if not values:
            print("[ReactionRoles] on_interaction values empty!", flush=True)
            return

        selected_val = str(values[0])
        panel_id = custom_id.split("rr_sel:", 1)[1] if "rr_sel:" in custom_id else ""

        await self.process_role_selection(interaction, selected_val, panel_id)

    async def cog_load(self):
        """Restore persistent dropdown views across bot restarts."""
        meta_dict = getattr(db, "reaction_roles_meta", {})
        for msg_id, meta in list(meta_dict.items()):
            if isinstance(meta, dict) and (meta.get("panel_type") == "select" or meta.get("mode") == "select"):
                saved_opts = meta.get("options", [])
                if saved_opts:
                    opts = []
                    for opt_data in saved_opts:
                        emoji_obj = None
                        e_str = opt_data.get("emoji")
                        if e_str:
                            m = re.match(r'<(a?):([a-zA-Z0-9_]+):([0-9]+)>', e_str)
                            if m:
                                emoji_obj = discord.PartialEmoji(name=m.group(2), id=int(m.group(3)), animated=bool(m.group(1)))
                            else:
                                emoji_obj = e_str
                        opts.append(discord.SelectOption(
                            label=opt_data.get("label", "Role")[:100],
                            value=str(opt_data.get("value")),
                            description=opt_data.get("description", "")[:100] or None,
                            emoji=emoji_obj
                        ))
                    if opts:
                        exclusive = meta.get("exclusive", True)
                        self.bot.add_view(ReactionRoleSelectView(options=opts, panel_id=str(msg_id), exclusive=exclusive))

    @app_commands.command(name="reaction_panel", description="Create an interactive role assignment panel (Dropdown or Reactions).")
    @app_commands.describe(
        channel="Where to post the panel", title="Title of the panel", description="Text above the roles",
        role1="First Role to assign", emoji1="Emoji for Role 1",
        role2="Second Role to assign", emoji2="Emoji for Role 2",
        role3="Third Role to assign", emoji3="Emoji for Role 3",
        panel_type="Choose panel interface style (Dropdown menu is recommended and prevents race conditions)",
        exclusive="If True, members can only pick 1 role at a time",
        thumbnail="Select thumbnail icon: No Avatar, Friday's Avatar, or Server Avatar"
    )
    @app_commands.choices(
        panel_type=[
            app_commands.Choice(name="📜 Dropdown Menu (Recommended - Atomic & Fast)", value="select"),
            app_commands.Choice(name="🔘 Classic Reactions", value="reaction")
        ],
        thumbnail=[
            app_commands.Choice(name="🚫 No Avatar", value="none"),
            app_commands.Choice(name="🤖 Friday's Avatar", value="bot"),
            app_commands.Choice(name="🌐 Server Avatar", value="server")
        ]
    )
    @app_commands.default_permissions(manage_roles=True)
    async def reaction_panel(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str,
        role1: discord.Role, emoji1: str, role2: discord.Role = None, emoji2: str = None, role3: discord.Role = None, emoji3: str = None,
        panel_type: app_commands.Choice[str] = None,
        exclusive: bool = True,
        thumbnail: app_commands.Choice[str] = None
    ):
        await interaction.response.defer(ephemeral=True)
        if not (interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id):
            await interaction.followup.send("❌ You need **Manage Roles** or **Administrator** permissions to create a reaction role panel.", ephemeral=True)
            return
        
        bot_role = interaction.guild.me.top_role
        for role in [role1, role2, role3]:
            if role and role >= bot_role:
                await interaction.followup.send(f"❌ Error: My role must be physically higher than {role.name} to assign it.")
                return

        def parse_emoji(input_str):
            if not input_str: return None
            input_str = input_str.strip()
            match = re.match(r'<(a?):([a-zA-Z0-9_]+):([0-9]+)>', input_str)
            if match:
                return discord.PartialEmoji(name=match.group(2), id=int(match.group(3)), animated=bool(match.group(1)))
            clean_name = input_str.strip(':')
            for e in interaction.guild.emojis:
                if e.name == clean_name:
                    return e 
            return input_str

        e1 = parse_emoji(emoji1)
        e2 = parse_emoji(emoji2)
        e3 = parse_emoji(emoji3)

        roles_setup = []
        if role1 and e1: roles_setup.append((role1, e1))
        if role2 and e2: roles_setup.append((role2, e2))
        if role3 and e3: roles_setup.append((role3, e3))
        
        if not roles_setup:
            await interaction.followup.send("❌ Error: You must provide at least one valid role and emoji pair.")
            return

        p_title = replace_plain_emojis(title, self.bot, guild=interaction.guild) if title else None
        p_desc = replace_plain_emojis(description, self.bot, guild=interaction.guild) if description else None
        if p_desc:
            p_desc = format_embed_description(p_desc, target_width=50)

        embed = discord.Embed(title=p_title, description=p_desc, color=discord.Color.teal())

        thumb_val = thumbnail.value if thumbnail else "none"
        if thumb_val == "bot" and self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=str(self.bot.user.display_avatar.url))
        elif thumb_val == "server" and interaction.guild.icon:
            embed.set_thumbnail(url=str(interaction.guild.icon.url))

        panel_text = ""
        for role, emoji in roles_setup:
            panel_text += f"{str(emoji)} ─ {role.mention}\n"
            
        embed.add_field(name="Available Roles", value=panel_text, inline=False)
        is_select_mode = (panel_type.value if panel_type else "select") == "select"
        footer_text = "Select your role from the dropdown menu below!" if is_select_mode else "React below to claim your roles!"
        embed.set_footer(text=footer_text)

        try:
            temp_id = str(discord.utils.time_snowflake(discord.utils.utcnow()))
            if is_select_mode:
                select_options = []
                stored_opts = []
                for role, emoji_obj in roles_setup:
                    opt = discord.SelectOption(
                        label=role.name[:100],
                        value=str(role.id),
                        description="Claim this role"[:100],
                        emoji=emoji_obj if isinstance(emoji_obj, (discord.PartialEmoji, discord.Emoji)) else (emoji_obj if isinstance(emoji_obj, str) and len(emoji_obj) <= 4 else None)
                    )
                    select_options.append(opt)
                    stored_opts.append({
                        "label": role.name[:100],
                        "value": str(role.id),
                        "description": "Claim this role",
                        "emoji": str(emoji_obj)
                    })

                # Clear option
                select_options.append(discord.SelectOption(
                    label="None / Remove Role",
                    value="clear",
                    emoji="❌",
                    description="Clear your self-role selection"
                ))
                stored_opts.append({
                    "label": "None / Remove Role",
                    "value": "clear",
                    "description": "Clear your self-role selection",
                    "emoji": "❌"
                })

                view = ReactionRoleSelectView(options=select_options, panel_id=temp_id, exclusive=exclusive)
                msg = await channel.send(embed=embed, view=view)
                msg_id = str(msg.id)
                view.panel_id = msg_id
                self.bot.add_view(view)

                db.reaction_roles[msg_id] = {str(e): r.id for r, e in roles_setup}
                db.reaction_roles[temp_id] = db.reaction_roles[msg_id]
                meta_payload = {
                    "exclusive": exclusive,
                    "channel_id": str(channel.id),
                    "guild_id": str(interaction.guild.id),
                    "panel_type": "select",
                    "options": stored_opts
                }
                if not hasattr(db, "reaction_roles_meta") or not isinstance(db.reaction_roles_meta, dict):
                    db.reaction_roles_meta = {}
                db.reaction_roles_meta[msg_id] = meta_payload
                db.reaction_roles_meta[temp_id] = meta_payload
                db.data.setdefault("reaction_roles_meta", {})[msg_id] = meta_payload
                db.data.setdefault("reaction_roles_meta", {})[temp_id] = meta_payload
                db.save_data()
                await interaction.followup.send(f"✅ Dropdown Role Panel deployed successfully in {channel.mention}.")
            else:
                msg = await channel.send(embed=embed)
                msg_id = str(msg.id)
                if msg_id not in db.reaction_roles:
                    db.reaction_roles[msg_id] = {}
                
                for role, emoji_obj in roles_setup:
                    await msg.add_reaction(emoji_obj) 
                    db.reaction_roles[msg_id][str(emoji_obj)] = role.id
                    if hasattr(emoji_obj, "id") and emoji_obj.id:
                        db.reaction_roles[msg_id][str(emoji_obj.id)] = role.id
                    if hasattr(emoji_obj, "name") and emoji_obj.name:
                        db.reaction_roles[msg_id][emoji_obj.name] = role.id
                        db.reaction_roles[msg_id][f":{emoji_obj.name}:"] = role.id
                    
                meta_rx = {
                    "exclusive": exclusive,
                    "channel_id": str(channel.id),
                    "guild_id": str(interaction.guild.id),
                    "panel_type": "reaction"
                }
                if not hasattr(db, "reaction_roles_meta") or not isinstance(db.reaction_roles_meta, dict):
                    db.reaction_roles_meta = {}
                db.reaction_roles_meta[msg_id] = meta_rx
                db.data.setdefault("reaction_roles_meta", {})[msg_id] = meta_rx
                db.save_data()
                await interaction.followup.send(f"✅ Reaction panel deployed successfully in {channel.mention}.")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ Error: I lack permissions to send messages or add reactions in that channel.")
        except discord.HTTPException as e:
            if 'msg' in locals(): await msg.delete() 
            await interaction.followup.send(f"❌ Error creating panel: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Handles role assignment for emoji reactions with universal emoji resolution and exclusive deletion."""
        if payload.member and payload.member.bot:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = payload.member or guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        msg_id = str(payload.message_id)

        # Look up panel in db.reaction_roles
        panel_roles = getattr(db, "reaction_roles", {}).get(msg_id)
        if not panel_roles and hasattr(db, "reaction_roles"):
            panel_roles = db.reaction_roles.get(int(payload.message_id))
        
        if not panel_roles or not isinstance(panel_roles, dict):
            return

        role_id = find_role_for_emoji(panel_roles, payload.emoji)
        if not role_id:
            return

        target_role = guild.get_role(role_id)
        if not target_role:
            return

        # Check exclusive mode
        meta = getattr(db, "reaction_roles_meta", {}).get(msg_id, {})
        if not meta and hasattr(db, "reaction_roles_meta"):
            meta = db.reaction_roles_meta.get(int(payload.message_id), {})
        is_exclusive = meta.get("exclusive", True) if isinstance(meta, dict) else True

        # Concurrency guard per member per message
        lock_key = (payload.user_id, payload.message_id)
        if lock_key in self._processing:
            return
        self._processing.add(lock_key)

        try:
            if is_exclusive:
                # 1. Remove any other roles granted by this panel from the member
                roles_to_remove = []
                for other_k, other_r_id in panel_roles.items():
                    if str(other_r_id).isdigit() and int(other_r_id) != target_role.id:
                        other_r = guild.get_role(int(other_r_id))
                        if other_r and other_r in member.roles:
                            roles_to_remove.append(other_r)

                if roles_to_remove:
                    try:
                        await member.remove_roles(*roles_to_remove, reason="Reaction Role: Exclusive role swap")
                    except Exception as e:
                        print(f"[ReactionRoles] Error removing old roles: {e}")

                # 2. CRITICAL: Remove the user's previous reaction emojis from the Discord message
                channel = guild.get_channel(payload.channel_id)
                if channel:
                    try:
                        msg = await channel.fetch_message(payload.message_id)
                        curr_eid = str(getattr(payload.emoji, "id", "") or "")

                        for rxn in msg.reactions:
                            rxn_eid = str(getattr(rxn.emoji, "id", "") or "")
                            
                            is_same = False
                            if curr_eid and rxn_eid and curr_eid == rxn_eid:
                                is_same = True
                            elif not curr_eid and not rxn_eid and str(rxn.emoji) == str(payload.emoji):
                                is_same = True

                            if not is_same:
                                # Only remove if this reaction is part of the panel
                                if find_role_for_emoji(panel_roles, rxn.emoji):
                                    try:
                                        await msg.remove_reaction(rxn.emoji, member)
                                    except Exception:
                                        pass
                    except Exception as e:
                        print(f"[ReactionRoles] Error cleaning exclusive reactions: {e}")

            # Assign target role
            if target_role not in member.roles:
                try:
                    await member.add_roles(target_role, reason="Reaction Role: Claimed role via emoji")
                except discord.Forbidden:
                    print(f"[ReactionRoles] Forbidden assigning role {target_role.name} to {member.name}")
                except Exception as e:
                    print(f"[ReactionRoles] Error assigning role: {e}")
        finally:
            self._processing.discard(lock_key)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Removes the associated role when a member un-reacts from a panel."""
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        msg_id = str(payload.message_id)
        panel_roles = getattr(db, "reaction_roles", {}).get(msg_id)
        if not panel_roles and hasattr(db, "reaction_roles"):
            panel_roles = db.reaction_roles.get(int(payload.message_id))
        
        if not panel_roles or not isinstance(panel_roles, dict):
            return

        role_id = find_role_for_emoji(panel_roles, payload.emoji)
        if not role_id:
            return

        role = guild.get_role(role_id)
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Reaction Role: Removed emoji reaction")
            except Exception as e:
                print(f"[ReactionRoles] Error removing role on reaction remove: {e}")


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
