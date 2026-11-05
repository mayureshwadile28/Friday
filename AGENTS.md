# Project Rules for Friday Discord Bot & Dashboard

## UI & Emoji Standards
1. **Universal Emoji Picker for All Text Editors:**
   - Whenever adding or modifying any text input, title template, message template, or embed field in the UI, **ALWAYS** include an emoji picker button (`😊` or `😊 Server Emojis`) so users can insert server custom emojis (static and animated GIF) as well as standard emojis.
2. **Never Display Raw Emoji Syntax:**
   - In all live Discord preview cards, simulators, rule badges, and lists, **NEVER** display raw emoji strings (like `<a:name:id>`, `<:name:id>`, `:name:`, or raw snowflake IDs like `1557692933199896576`).
   - **ALWAYS** render the actual emoji image (`<img class="discord-custom-emoji" ...>`) using `renderDiscordMarkdown()` or `renderEmojiHtmlOrChar()`.
3. **Visual Emoji Rendering in All Inputs & Pickers (NEVER Show Raw Names or Syntax):**
   - For all emoji picker fields and configuration cards, the UI must render the **actual visual emoji (animated GIF, PNG image, or Unicode symbol)** directly on screen, NEVER the raw syntax (`<a:name:id>`) and NEVER plain text names (`:name:`).
   - In single-emoji pickers, the button/tile must render the chosen emoji image (`renderEmojiHtmlOrChar(val, size)`), and any associated input must be attached to `attachRichEmojiEditor()` or visually display the rendered emoji image so users and staff instantly see the real icon without any confusion.
   - Raw emoji syntax must only be stored behind the scenes in `dataset.rawEmoji` and the underlying input value for backend synchronization.
4. **Button & Aesthetics:**
   - All buttons must use polished, modern dark-mode styling (`.btn-action-primary`, `.btn-action-secondary`). Never leave secondary buttons (like "Send Test Card" or "Refresh List") unstyled.
