import asyncio
import os
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

ARTIFACT_DIR = r"C:\Users\vinod\.gemini\antigravity-ide\brain\63eee4b7-e643-4e5b-b17d-35d76b105296"

async def main():
    async with async_playwright() as p:
        # Try chrome, then msedge, then default
        browser = None
        for ch in ['chrome', 'msedge']:
            try:
                print(f"Trying launch with channel={ch}...")
                browser = await p.chromium.launch(headless=True, channel=ch)
                print(f"Launched successfully with {ch}!")
                break
            except Exception as e:
                print(f"Failed {ch}: {e}")

        if not browser:
            print("Could not launch browser")
            return

        context = await browser.new_context(viewport={'width': 1400, 'height': 900})
        page = await context.new_page()

        console_errors = []
        page.on('console', lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type in ['error', 'warning'] else None)
        page.on('pageerror', lambda exc: console_errors.append(f"[pageerror] {exc}"))

        print("Navigating to http://localhost:5000/...")
        await page.goto("http://localhost:5000/", wait_until='networkidle')

        # 1. Select Server
        await page.click("#guildHeader")
        await page.wait_for_timeout(500)
        
        # Click first guild item in dropdown list
        first_guild = await page.query_selector(".dropdown-item")
        if first_guild:
            guild_name = await first_guild.text_content()
            print(f"Selecting server: {guild_name.strip()}")
            await first_guild.click()
        else:
            print("No .dropdown-item found, clicking first item by id")
            await page.click("#guildList > div:first-child")

        await page.wait_for_timeout(1500)

        # 2. Screenshot Anti-Nuke
        antinuke_path = os.path.join(ARTIFACT_DIR, "fixed_antinuke_view.png")
        await page.screenshot(path=antinuke_path)
        print(f"Saved Anti-Nuke view to: {antinuke_path}")

        # 3. Test changing Anti-Ban punishment to Timeout
        ban_pun_sel = await page.query_selector("#sec_lim_ban_pun")
        if ban_pun_sel:
            print("Changing Anti-Ban punishment to timeout...")
            await ban_pun_sel.select_option("timeout")
            await page.wait_for_timeout(500)
            
            # Check if tm wrap is visible
            tm_wrap = await page.query_selector("#sec_lim_ban_tm_wrap")
            is_vis = await tm_wrap.is_visible() if tm_wrap else False
            print(f"Anti-Ban TM wrapper visible after selecting timeout: {is_vis}")

            tm_shot_path = os.path.join(ARTIFACT_DIR, "fixed_tm_input_view.png")
            await page.screenshot(path=tm_shot_path)
            print(f"Saved TM input view to: {tm_shot_path}")

        # 4. Click Channel Privacy
        await page.click("a[data-tab='privacySection']")
        await page.wait_for_timeout(800)
        privacy_vis = await (await page.query_selector("#privacySection")).is_visible()
        print(f"Channel Privacy section visible: {privacy_vis}")
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "fixed_privacy_view.png"))

        # 5. Click Leveling System
        await page.click("a[data-tab='levelingSection']")
        await page.wait_for_timeout(800)
        leveling_vis = await (await page.query_selector("#levelingSection")).is_visible()
        print(f"Leveling System section visible: {leveling_vis}")
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "fixed_leveling_view.png"))

        # 6. Click Custom Responses
        await page.click("a[data-tab='responsesSection']")
        await page.wait_for_timeout(800)
        responses_vis = await (await page.query_selector("#responsesSection")).is_visible()
        print(f"Custom Responses section visible: {responses_vis}")
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "fixed_responses_view.png"))

        # 7. Click Ticket System
        await page.click("a[data-tab='ticketsSection']")
        await page.wait_for_timeout(800)
        tickets_vis = await (await page.query_selector("#ticketsSection")).is_visible()
        print(f"Ticket System section visible: {tickets_vis}")
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "fixed_tickets_view.png"))

        print("\nConsole errors / warnings during session:")
        if console_errors:
            for err in console_errors:
                print(" ", err)
        else:
            print("  None! (Zero console errors)")

        await browser.close()
        print("\nDone capturing views successfully!")

if __name__ == "__main__":
    asyncio.run(main())
