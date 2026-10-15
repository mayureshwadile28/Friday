# Project Rules for Friday Discord Bot & Dashboard

## UI & Emoji Standards
1. **Universal Emoji Picker for All Text Editors:**
   - Whenever adding or modifying any text input, title template, message template, or embed field in the UI, **ALWAYS** include an emoji picker button (`😊` or `😊 Server Emojis`) so users can insert server custom emojis (static and animated GIF) as well as standard emojis.
2. **Never Display Raw Emoji Syntax:**
   - In all live Discord preview cards, simulators, rule badges, and lists, **NEVER** display raw emoji strings (like `<a:name:id>`, `<:name:id>`, `:name:`, or raw snowflake IDs like `1557692933199896576`).
   - **ALWAYS** render the actual emoji image (`<img class="discord-custom-emoji" ...>`) using `renderDiscordMarkdown()` or `renderEmojiHtmlOrChar()`.
3. **Clean Input Visuals:**
   - In single-emoji pickers, the button must render the chosen emoji image, and the text input displays the friendly `:name:` while storing the full syntax in `dataset.rawEmoji`.
4. **Button & Aesthetics:**
   - All buttons must use polished, modern dark-mode styling (`.btn-action-primary`, `.btn-action-secondary`). Never leave secondary buttons (like "Send Test Card" or "Refresh List") unstyled.
