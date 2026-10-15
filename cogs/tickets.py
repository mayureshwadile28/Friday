import discord
from discord.ext import commands
from discord import app_commands
import io
import chat_exporter
import re
from database import db
from emoji_utils import replace_plain_emojis, parse_btn


# ----------------- TICKET VIEWS -----------------

class TicketActiveView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close_btn")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = str(interaction.guild.id)
        msg_closing = db.custom_responses.get(gid, {}).get("ticket_closing_msg", "Closing ticket in 5 seconds...")
        await interaction.response.send_message(msg_closing, ephemeral=False)
        cid = str(interaction.channel.id)
        
        # Check transcription
        settings = db.tickets.get(gid, {})
        active_ticket = settings.get("active_tickets", {}).get(cid)
        if active_ticket:
            panel_id = active_ticket.get("panel_message_id")
            panel_settings = settings.get("panels", {}).get(str(panel_id), {})
            
            if panel_settings.get("transcription", False):
                transcript_channel_id = panel_settings.get("transcript_channel_id")
                transcript_category_id = panel_settings.get("transcript_category_id")
                try:
                    transcript = await chat_exporter.export(interaction.channel)
                    transcript_file = discord.File(io.BytesIO(transcript.encode()), filename=f"transcript-{interaction.channel.name}.html")
                    
                    log_channel = None
                    if transcript_channel_id:
                        log_channel = interaction.guild.get_channel(int(transcript_channel_id))
                        
                    if not log_channel and transcript_category_id:
                        log_cat = interaction.guild.get_channel(int(transcript_category_id))
                        if log_cat and isinstance(log_cat, discord.CategoryChannel):
                            # find or create a log channel
                            log_channel = discord.utils.get(log_cat.text_channels, name="ticket-transcripts")
                            if not log_channel:
                                log_channel = await log_cat.create_text_channel("ticket-transcripts")
                    
                    if not log_channel:
                        # Fallback to server audit logs if available
                        audit_log_id = db.server_logs.get(gid, {}).get("audit-antinuke") or db.server_logs.get(gid, {}).get("audit-abuse")
                        if audit_log_id:
                            log_channel = interaction.guild.get_channel(int(audit_log_id))
                            
                    if log_channel:
                        owner_id = active_ticket.get("owner_id")
                        owner = interaction.guild.get_member(owner_id)
                        owner_text = owner.mention if owner else f"<@{owner_id}>"
                        
                        created_ts = int(interaction.channel.created_at.timestamp())
                        closed_ts = int(discord.utils.utcnow().timestamp())
                        
                        await log_channel.send(
                            f"📜 **Ticket Transcript Archive** for `{interaction.channel.name}`\n"
                            f"**Opened by:** {owner_text}\n"
                            f"**Closed by:** {interaction.user.mention}\n"
                            f"**Created:** <t:{created_ts}:F>\n"
                            f"**Closed:** <t:{closed_ts}:F>",
                            file=transcript_file
                        )
                except Exception as e:
                    print(f"Transcript error: {e}")
            
            # Clean up active ticket
            del settings["active_tickets"][cid]
            db.save_data()

        import asyncio
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason="Ticket closed.")
        except Exception:
            pass

class TicketPanelView(discord.ui.View):
    def __init__(self, bot, panel_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.panel_id = panel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        gid = str(interaction.guild.id)
        settings = db.tickets.get(gid, {})
        panel_settings = settings.get("panels", {}).get(str(self.panel_id))
        
        if not panel_settings:
            await interaction.response.send_message("This ticket panel is no longer active or properly configured.", ephemeral=True)
            return False
            
        custom_id = interaction.data.get("custom_id")
        button_name = custom_id.split("ticket_btn_")[1]
        
        # Check if user already has an open ticket for this panel
        active_tickets = settings.get("active_tickets", {})
        for cid, t in active_tickets.items():
            if t.get("owner_id") == interaction.user.id and t.get("panel_message_id") == self.panel_id:
                existing_chan = interaction.guild.get_channel(int(cid))
                if existing_chan:
                    tpl_open = db.custom_responses.get(gid, {}).get("ticket_already_open", "You already have an open ticket! {channel}")
                    await interaction.response.send_message(tpl_open.replace("{channel}", existing_chan.mention), ephemeral=True)
                    return False

        category_id = panel_settings.get("category_id")
        category = interaction.guild.get_channel(category_id) if category_id else None

        # Counter
        counter = settings.get("ticket_counter", 0) + 1
        settings["ticket_counter"] = counter

        label, _ = parse_btn(button_name)
        safe_name = re.sub(r'[^a-zA-Z0-9]+', '-', label.lower()).strip('-')
        if not safe_name: safe_name = "ticket"
        ticket_name = f"ticket-{counter:03d}-{safe_name}"
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False)
        }
        
        if not panel_settings.get("private", True):
            overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)

        overwrites[interaction.user] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        overwrites[interaction.guild.me] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)

        support_role_id = settings.get("support_role_id")
        support_role = None
        if support_role_id:
            support_role = interaction.guild.get_role(support_role_id)
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ack_tpl = db.custom_responses.get(gid, {}).get("ticket_created_ack", "Creating your ticket...")
        await interaction.response.send_message(ack_tpl, ephemeral=True)

        try:
            ticket_channel = await interaction.guild.create_text_channel(
                name=ticket_name,
                category=category,
                overwrites=overwrites,
                reason=f"Ticket created by {interaction.user}"
            )
            
            # Save active ticket
            if "active_tickets" not in settings:
                settings["active_tickets"] = {}
            settings["active_tickets"][str(ticket_channel.id)] = {
                "owner_id": interaction.user.id,
                "panel_message_id": self.panel_id
            }
            db.save_data()

            welcome_tpl = db.custom_responses.get(gid, {}).get("ticket_welcome_msg", "Welcome {member}!\n\nPlease describe your issue. Support will be with you shortly.")
            welcome_text = welcome_tpl.replace("{member}", interaction.user.mention)

            embed = discord.Embed(
                title=f"Ticket: {label}",
                description=welcome_text,
                color=0x2dd4bf
            )

            
            mentions = [interaction.user.mention]
            if support_role:
                mentions.append(support_role.mention)
                
            await ticket_channel.send(
                content=" ".join(mentions),
                embed=embed,
                view=TicketActiveView(self.bot)
            )

            succ_tpl = db.custom_responses.get(gid, {}).get("ticket_created_success", "Ticket created: {channel}")
            await interaction.edit_original_response(content=succ_tpl.replace("{channel}", ticket_channel.mention))

        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Error creating ticket: {e}")
        return True


# ----------------- COG -----------------

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.restore_views())

    async def restore_views(self):
        await self.bot.wait_until_ready()
        # We restore the generic close ticket view. Panel buttons require panel_id, 
        # so we will dynamically construct them during on_ready or just use persistent views if possible.
        # For simplicity, TicketActiveView has no dynamic init args, so we can add it.
        self.bot.add_view(TicketActiveView(self.bot))
        
        # Restore panels
        for gid_str, data in db.tickets.items():
            panels = data.get("panels", {})
            for pid_str, pdata in panels.items():
                panel_id = int(pid_str)
                view = TicketPanelView(self.bot, panel_id)
                
                # Re-add buttons
                guild = self.bot.get_guild(int(gid_str))
                for i, btn_name in enumerate(pdata.get("buttons", [])):
                    label, emoji = parse_btn(btn_name, bot=self.bot, guild=guild)
                    btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"ticket_btn_{btn_name}", emoji=emoji)
                    view.add_item(btn)
                self.bot.add_view(view, message_id=panel_id)

    ticket_group = app_commands.Group(name="ticket", description="Ticket system commands", default_permissions=discord.Permissions(administrator=True))

    @app_commands.command(name="create_ticket_panel", description="Create a ticket panel")
    @app_commands.default_permissions(administrator=True)
    async def create_ticket_panel(self, interaction: discord.Interaction, 
                           channel: discord.TextChannel,
                           title: str,
                           description: str,
                           button1: str,
                           category: discord.CategoryChannel,
                           button2: str = None,
                           button3: str = None,
                           button4: str = None,
                           private: bool = True,
                           transcription: bool = True,
                           transcript_category: discord.CategoryChannel = None):
        
        await interaction.response.defer(ephemeral=True)

        embed_title = replace_plain_emojis(title, self.bot, guild=interaction.guild)
        embed_desc = replace_plain_emojis(description, self.bot, guild=interaction.guild)
        embed = discord.Embed(title=embed_title, description=embed_desc, color=0x2dd4bf)
        
        buttons = [button1]
        if button2: buttons.append(button2)
        if button3: buttons.append(button3)
        if button4: buttons.append(button4)
        
        view = discord.ui.View(timeout=None)
        for b in buttons:
            label, emoji = parse_btn(b, bot=self.bot, guild=interaction.guild)
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"ticket_btn_{b}", emoji=emoji)
            view.add_item(btn)

        try:
            msg = await channel.send(embed=embed, view=view)
            
            gid = str(interaction.guild.id)
            if gid not in db.tickets:
                db.tickets[gid] = {"panels": {}, "active_tickets": {}, "ticket_counter": 0}
            if "panels" not in db.tickets[gid]:
                db.tickets[gid]["panels"] = {}
                
            db.tickets[gid]["panels"][str(msg.id)] = {
                "channel_id": channel.id,
                "title": title,
                "description": description,
                "buttons": buttons,
                "category_id": category.id,
                "private": private,
                "transcription": transcription,
                "transcript_category_id": transcript_category.id if transcript_category else None
            }
            db.tickets[gid]["config"] = db.tickets[gid]["panels"][str(msg.id)]
            db.save_data()
            
            # Now we must attach the proper TicketPanelView instead of generic view
            # So the buttons work
            actual_view = TicketPanelView(self.bot, msg.id)
            for b in buttons:
                label, emoji = parse_btn(b, bot=self.bot, guild=interaction.guild)
                actual_view.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"ticket_btn_{b}", emoji=emoji))
            await msg.edit(view=actual_view)
            
            await interaction.followup.send(f"✅ Ticket panel created in {channel.mention}.")
            
            if not db.tickets[gid].get("support_role_id"):
                await interaction.followup.send("⚠️ **Note:** You haven't set a support role yet. Use `/ticket handle_role` so the bot knows who to ping when a ticket is opened!", ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")

    @ticket_group.command(name="handle_role", description="Set the staff role that manages tickets")
    async def handle_role(self, interaction: discord.Interaction, role: discord.Role):
        gid = str(interaction.guild.id)
        if gid not in db.tickets:
            db.tickets[gid] = {"panels": {}, "active_tickets": {}, "ticket_counter": 0}
        db.tickets[gid]["support_role_id"] = role.id
        db.save_data()
        embed = discord.Embed(
            title="✔ Support Role Set",
            description=f"Ticket support role set to {role.mention}.",
            color=0x2b2d31
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket_group.command(name="add", description="Add a user to the current ticket")
    async def add_user(self, interaction: discord.Interaction, user: discord.Member):
        gid = str(interaction.guild.id)
        cid = str(interaction.channel.id)
        if cid not in db.tickets.get(gid, {}).get("active_tickets", {}):
            embed = discord.Embed(
                title="✖ Invalid Channel",
                description="This command can only be used inside an active ticket channel.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        try:
            await interaction.channel.set_permissions(user, read_messages=True, send_messages=True, attach_files=True)
            embed = discord.Embed(
                title="✔ User Added",
                description=f"Added {user.mention} to the ticket.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            embed = discord.Embed(
                title="✖ Error",
                description=str(e),
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket_group.command(name="remove", description="Remove a user from the current ticket")
    async def remove_user(self, interaction: discord.Interaction, user: discord.Member):
        gid = str(interaction.guild.id)
        cid = str(interaction.channel.id)
        if cid not in db.tickets.get(gid, {}).get("active_tickets", {}):
            embed = discord.Embed(
                title="✖ Invalid Channel",
                description="This command can only be used inside an active ticket channel.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        try:
            await interaction.channel.set_permissions(user, read_messages=False)
            embed = discord.Embed(
                title="✔ User Removed",
                description=f"Removed {user.mention} from the ticket.",
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            embed = discord.Embed(
                title="✖ Error",
                description=str(e),
                color=0x2b2d31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
