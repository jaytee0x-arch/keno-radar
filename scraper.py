import asyncio
import os
import pandas as pd
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ==============================================================================
# CONFIGURATION
# ==============================================================================
URL = "https://www.kenousa.com/games/GVR/Green/draws.php"
GAMES_FILE = "games.csv"
PAGES_TO_COLLECT = 2    # 2 pages x 10 games = 20 games (we only need 15)


# ==============================================================================
# CORE: Extract all game rows currently visible on the page
# ==============================================================================
async def extract_visible_games(page) -> list:
    games = []
    try:
        game_nums = await page.locator("div.game-num").all()
        game_dates = await page.locator("div.game-date").all()
        game_draws = await page.locator("div.game-draw").all()

        print(f"[Extract] Found {len(game_nums)} games on this page.")
        count = min(len(game_nums), len(game_dates), len(game_draws))

        for i in range(count):
            game_id = (await game_nums[i].inner_text()).strip()
            timestamp = (await game_dates[i].inner_text()).strip()
            raw_numbers = (await game_draws[i].inner_text()).strip()
            numbers = "-".join(raw_numbers.split())

            if game_id.isdigit() and numbers:
                games.append({
                    "Game ID": game_id,
                    "Timestamp": timestamp,
                    "Numbers": numbers,
                })
    except Exception as e:
        print(f"[Extract] Error: {e}")
    return games


# ==============================================================================
# CORE: Click the back "10" button (index 2 in the fixed button order)
# ==============================================================================
async def click_back_10(page) -> bool:
    try:
        first_before = (await page.locator("div.game-num").first.inner_text()).strip()

        back_button = page.locator("button.game-change").nth(2)
        if await back_button.count() == 0:
            return False

        cls = await back_button.get_attribute("class") or ""
        if "disabled" in cls:
            print("[Nav] Back button disabled. At oldest available data.")
            return False

        await back_button.click()

        for _ in range(15):
            await asyncio.sleep(1)
            try:
                first_after = (await page.locator("div.game-num").first.inner_text()).strip()
                if first_after != first_before:
                    print(f"[Nav] Page changed. First Game ID now: {first_after}")
                    return True
            except:
                pass

        return False
    except Exception as e:
        print(f"[Nav] Error: {e}")
        return False


# ==============================================================================
# MAIN SCRAPER
# ==============================================================================
async def run_scraper():
    all_collected = []
    seen_ids = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        try:
            print(f"[Browser] Navigating to {URL}")
            await page.goto(URL, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(10)

            try:
                await page.wait_for_selector("div.game-num", timeout=20000)
                print("[Setup] Page ready.")
            except PlaywrightTimeout:
                print("[Error] Game data never appeared.")
                return

            for page_num in range(1, PAGES_TO_COLLECT + 1):
                print(f"\n[Loop] Scraping page {page_num} of {PAGES_TO_COLLECT}")
                page_games = await extract_visible_games(page)

                for game in page_games:
                    if game["Game ID"] not in seen_ids:
                        seen_ids.add(game["Game ID"])
                        all_collected.append(game)

                if page_num < PAGES_TO_COLLECT:
                    success = await click_back_10(page)
                    if not success:
                        print("[Loop] Could not navigate back. Stopping.")
                        break
                    await asyncio.sleep(2)

        except Exception as e:
            print(f"[Fatal] {e}")
        finally:
            await browser.close()

    if all_collected:
        df = pd.DataFrame(all_collected)
        df["Game ID"] = df["Game ID"].astype(int)
        df = df.sort_values("Game ID", ascending=True).tail(15).reset_index(drop=True)
        df.to_csv(GAMES_FILE, index=False)
        print(f"\n[Scraper] Saved {len(df)} most recent games to {GAMES_FILE}.")
    else:
        print("[Scraper] No games collected.")


if __name__ == "__main__":
    asyncio.run(run_scraper())
