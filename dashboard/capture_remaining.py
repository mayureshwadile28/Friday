import asyncio
import os
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

ARTIFACT_DIR = r"C:\Users\vinod\.gemini\antigravity-ide\brain\63eee4b7-e643-4e5b-b17d-35d76b105296"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel='chrome')
        page = await browser.new_page(viewport={'width': 1400, 'height': 900})
        await page.goto("http://localhost:5000/", wait_until='networkidle')

        await page.click("#guildHeader")
        await page.wait_for_timeout(400)
        await page.click(".dropdown-item")
        await page.wait_for_timeout(1000)

        # Anti-Abuse
        await page.click("a[data-tab='antiabuseSection']")
        await page.wait_for_timeout(800)
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "fixed_antiabuse_view.png"))

        # Reaction Roles
        await page.click("a[data-tab='reactionRolesSection']")
        await page.wait_for_timeout(800)
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "fixed_reactionroles_view.png"))

        # Announcements
        await page.click("a[data-tab='announcementsSection']")
        await page.wait_for_timeout(800)
        await page.screenshot(path=os.path.join(ARTIFACT_DIR, "fixed_announcements_view.png"))

        await browser.close()
        print("Captured antiabuse, reactionroles, and announcements views successfully!")

if __name__ == "__main__":
    asyncio.run(main())
