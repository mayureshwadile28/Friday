# Friday Bot - Synchronization & State Rules

This document outlines the strict rules regarding feature state synchronization between the Friday Bot's Discord commands and its Web UI Dashboard.

## 1. Universal Sync Requirement
Whenever a new feature is added, or an existing feature is modified, it **MUST AND SHOULD SYNC** between both sides:
- If a user configures a setting via a Discord Slash Command (e.g., `/ticket handle_role`), this change must instantly reflect in the Web UI when they hit the "Sync State" button or refresh the page.
- If a user configures a setting via the Web UI (e.g., toggling Anti-Nuke), this change must instantly apply to the bot's live behavior in Discord.

## 2. Memory Persistence on Restart
If the bot goes offline and restarts, she must **NEVER** forget her active configurations. 
- All features like Anti-Nuke limits, active Ticket Panels, Channel Privacy settings, and Whitelists must be successfully restored from `friday_memory.json` upon startup.
- The state should be exactly as the user left it prior to the restart.

## 3. Database Architecture
Both the `main.py` (bot engine) and `dashboard/app.py` (Flask server) run in the same process and share the exact same `Database` object instance from `database.py`. 
Therefore, memory is implicitly synchronized in real-time. However, you must always ensure:
- Changes made in the UI trigger `db.save_data()`
- Changes made in Discord commands trigger `db.save_data()`
- UI inputs correctly clear/reset themselves (e.g. `roleSelect.value = data.support_role_id || ''`) so they accurately reflect cleared states instead of keeping old cached values on the frontend.

## 4. Documentation & UI Custom Response Protocol
Whenever a new feature or command suite is added (e.g., Music, Media, Tickets):
1. **Command Reference (`commands_list.txt`):** Immediately update with all new slash commands, syntax, descriptions, and options.
2. **System Documentation (`friday_documentation.md`):** Immediately document the feature architecture, commands, configuration parameters, and backend logic.
3. **UI Custom Responses (`dashboard/static/script.js` & `database.py`):** Add all user-facing bot messages (such as connection greetings, action notices, errors, and success replies) to `CUSTOM_RESPONSES_SCHEMA` with category, descriptive label, and supported template variables (e.g., `{channel}`, `{member}`), and integrate them into the cog so users can customize them directly from the Web Dashboard.

