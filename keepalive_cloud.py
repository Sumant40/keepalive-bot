"""
Keep-alive script for GitHub Actions.
Visits each site, wakes sleeping Streamlit apps, and refreshes the portfolio site.
"""
import time
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SITES = [
    {
        "id": "portfolio",
        "name": "Portfolio Site",
        "url": "https://sumantj.xyz/",
        "type": "portfolio",
        "refresh_count": 4,
    },
    {
        "id": "dashboard",
        "name": "Dashboard App",
        "url": "https://dashboarde.streamlit.app/",
        "type": "streamlit",
    },
    {
        "id": "foodreview",
        "name": "Food Review NLP",
        "url": "https://foodreviewnlp.streamlit.app/",
        "type": "streamlit",
    },
]

WAKE_SELECTORS = [
    "button:has-text('Yes, get this app back up!')",
    "button:has-text('get this app back up')",
    "button:has-text('Wake up')",
    "button:has-text('Rerun')",
]

def log(name, msg):
    print(f"[{name}] {msg}", flush=True)

def ping_portfolio(page, site):
    name = site["name"]
    refreshes = site.get("refresh_count", 4)
    log(name, f"Visiting {site['url']} ...")
    for i in range(1, refreshes + 1):
        page.goto(site["url"], wait_until="domcontentloaded", timeout=30_000)
        time.sleep(2)
        log(name, f"Refresh {i}/{refreshes} done")
    log(name, "Portfolio alive ✓")

def ping_streamlit(page, site):
    name = site["name"]
    log(name, f"Visiting {site['url']} ...")
    page.goto(site["url"], wait_until="domcontentloaded", timeout=40_000)
    time.sleep(5)  # wait for SPA render

    for sel in WAKE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=3_000):
                log(name, "App sleeping — clicking wake button ...")
                btn.click()
                time.sleep(6)
                log(name, "App woken ✓")
                return
        except PlaywrightTimeout:
            pass

    log(name, "App already awake ✓")

def main():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        for site in SITES:
            try:
                if site["type"] == "portfolio":
                    ping_portfolio(page, site)
                elif site["type"] == "streamlit":
                    ping_streamlit(page, site)
            except Exception as e:
                msg = f"ERROR: {e}"
                log(site["name"], msg)
                errors.append(msg)

        browser.close()

    if errors:
        print("\nSome sites had errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\nAll sites pinged successfully ✓")

if __name__ == "__main__":
    main()
