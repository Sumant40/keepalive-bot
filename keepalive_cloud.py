"""
Keep-alive script for GitHub Actions.
Visits each site, wakes sleeping Streamlit apps, and refreshes the portfolio site.
Exits with code 1 if any site fails after retries — the workflow catches this.
"""
import time
import sys
from dataclasses import dataclass, field
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SITES = [
    {
        "id": "portfolio",
        "name": "Portfolio Site",
        "url": "https://sumantj.xyz/",
        "type": "portfolio",
        "refresh_count": 8,
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

MAX_RETRIES = 2
RETRY_DELAY = 10  # seconds between retries


@dataclass
class SiteResult:
    name: str
    url: str
    success: bool
    attempts: int
    error: str = ""
    detail: str = ""


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


def visit_site(page, site):
    """Dispatch to the right handler based on site type."""
    if site["type"] == "portfolio":
        ping_portfolio(page, site)
    elif site["type"] == "streamlit":
        ping_streamlit(page, site)
    else:
        raise ValueError(f"Unknown site type: {site['type']!r}")


def visit_with_retries(page, site) -> SiteResult:
    """Try visiting a site up to MAX_RETRIES+1 times. Returns a SiteResult."""
    name = site["name"]
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            if attempt > 1:
                log(name, f"Retry {attempt - 1}/{MAX_RETRIES} after {RETRY_DELAY}s ...")
                time.sleep(RETRY_DELAY)

            visit_site(page, site)
            return SiteResult(
                name=name,
                url=site["url"],
                success=True,
                attempts=attempt,
            )

        except PlaywrightTimeout as e:
            last_error = f"Timeout: {e}"
            log(name, f"[attempt {attempt}] Timed out — {e}")

        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            log(name, f"[attempt {attempt}] Error — {e}")

    return SiteResult(
        name=name,
        url=site["url"],
        success=False,
        attempts=MAX_RETRIES + 1,
        error=last_error,
    )


def print_summary(results: list[SiteResult]):
    """Print a structured summary table that's easy to read in GitHub Actions logs."""
    print("\n" + "=" * 60, flush=True)
    print("SUMMARY", flush=True)
    print("=" * 60, flush=True)

    passed = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    for r in passed:
        attempts_note = f" (attempt {r.attempts})" if r.attempts > 1 else ""
        print(f"  ✓  {r.name}{attempts_note}", flush=True)

    for r in failed:
        print(f"  ✗  {r.name}", flush=True)
        print(f"       URL:    {r.url}", flush=True)
        print(f"       Error:  {r.error}", flush=True)

    print("=" * 60, flush=True)
    print(f"  {len(passed)}/{len(results)} sites OK", flush=True)
    if failed:
        print(f"  {len(failed)} failed: {', '.join(r.name for r in failed)}", flush=True)
    print("=" * 60, flush=True)


def main():
    results: list[SiteResult] = []

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
            result = visit_with_retries(page, site)
            results.append(result)

        browser.close()

    print_summary(results)

    failed = [r for r in results if not r.success]
    if failed:
        # Exit 1 so the workflow step fails and you get notified
        sys.exit(1)


if __name__ == "__main__":
    main()