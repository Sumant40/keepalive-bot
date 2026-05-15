import threading
import time
import json
import logging
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ─── Configuration ────────────────────────────────────────────────────────────
SITES = [
    {
        "id": "portfolio",
        "name": "Portfolio Site",
        "url": "https://sumantj.xyz/",
        "type": "portfolio",   # needs multiple refreshes
        "refresh_count": 4,
        "interval_seconds": 300,  # ping every 5 min
    },
    {
        "id": "dashboard",
        "name": "Dashboard App",
        "url": "https://dashboarde.streamlit.app/",
        "type": "streamlit",
        "interval_seconds": 300,
    },
    {
        "id": "foodreview",
        "name": "Food Review NLP",
        "url": "https://foodreviewnlp.streamlit.app/",
        "type": "streamlit",
        "interval_seconds": 300,
    },
    {
        "id": "Pharmacovigilance",
        "name": "Pharmacovigilance App",
        "url": "https://pharmacovigilance.streamlit.app/",
        "type": "streamlit",
        "interval_seconds": 300,
    },
]

# ─── State ────────────────────────────────────────────────────────────────────
site_status = {
    s["id"]: {
        "name": s["name"],
        "url": s["url"],
        "status": "pending",      # pending | alive | sleeping | waking | error
        "last_check": None,
        "last_wake": None,
        "message": "Not checked yet",
        "ping_count": 0,
        "wake_count": 0,
    }
    for s in SITES
}

logs = []   # rolling list of log entries (max 200)
worker_thread = None
worker_lock = threading.Lock()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("keepalive")


def add_log(site_id, message, level="info"):
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "site": site_status[site_id]["name"],
        "message": message,
        "level": level,
    }
    logs.insert(0, entry)
    if len(logs) > 200:
        logs.pop()
    getattr(log, level, log.info)(f"[{entry['site']}] {message}")


# ─── Browser tasks ────────────────────────────────────────────────────────────

def ping_portfolio(page, site):
    """Visit the portfolio site and reload several times to wake it."""
    sid = site["id"]
    url = site["url"]
    refreshes = site.get("refresh_count", 4)

    add_log(sid, f"Visiting {url} …")
    site_status[sid]["status"] = "waking"

    try:
        for i in range(1, refreshes + 1):
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)
            add_log(sid, f"Refresh {i}/{refreshes} done")

        site_status[sid]["status"] = "alive"
        site_status[sid]["message"] = f"Refreshed {refreshes}× successfully"
        site_status[sid]["ping_count"] += 1
        site_status[sid]["last_check"] = datetime.now().strftime("%H:%M:%S")
        add_log(sid, "Portfolio is alive ✓")

    except Exception as e:
        site_status[sid]["status"] = "error"
        site_status[sid]["message"] = str(e)[:120]
        add_log(sid, f"Error: {e}", "error")


def ping_streamlit(page, site):
    """
    Visit a Streamlit app.  If the 'wake-up' button is present, click it.
    Streamlit shows a button like: "Yes, get this app back up!"
    """
    sid = site["id"]
    url = site["url"]

    add_log(sid, f"Visiting {url} …")
    site_status[sid]["status"] = "waking"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=40_000)
        time.sleep(4)  # give SPA a moment to render

        # Streamlit sleeping page has a button with this text (or similar)
        wake_selectors = [
            "button:has-text('Yes, get this app back up!')",
            "button:has-text('get this app back up')",
            "button:has-text('Wake up')",
            "button:has-text('Rerun')",
        ]

        woke = False
        for sel in wake_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3_000):
                    add_log(sid, "App is sleeping — clicking wake button …", "warning")
                    btn.click()
                    time.sleep(5)
                    site_status[sid]["status"] = "alive"
                    site_status[sid]["message"] = "Woken up via button ✓"
                    site_status[sid]["wake_count"] += 1
                    site_status[sid]["last_wake"] = datetime.now().strftime("%H:%M:%S")
                    add_log(sid, "App woken successfully ✓")
                    woke = True
                    break
            except PlaywrightTimeout:
                pass

        if not woke:
            site_status[sid]["status"] = "alive"
            site_status[sid]["message"] = "App appears to be running ✓"
            add_log(sid, "App is already awake ✓")

        site_status[sid]["ping_count"] += 1
        site_status[sid]["last_check"] = datetime.now().strftime("%H:%M:%S")

    except Exception as e:
        site_status[sid]["status"] = "error"
        site_status[sid]["message"] = str(e)[:120]
        add_log(sid, f"Error: {e}", "error")


# ─── Background worker ────────────────────────────────────────────────────────

def worker():
    """Single long-lived Playwright browser that visits sites on schedule."""
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

        # Track when each site was last pinged
        last_pinged = {s["id"]: 0 for s in SITES}

        log.info("Keep-alive worker started.")
        while True:
            now = time.time()
            for site in SITES:
                sid = site["id"]
                if now - last_pinged[sid] >= site["interval_seconds"]:
                    try:
                        if site["type"] == "portfolio":
                            ping_portfolio(page, site)
                        elif site["type"] == "streamlit":
                            ping_streamlit(page, site)
                    except Exception as e:
                        site_status[sid]["status"] = "error"
                        site_status[sid]["message"] = str(e)[:120]
                        add_log(sid, f"Unhandled error: {e}", "error")
                    last_pinged[sid] = time.time()
            time.sleep(10)  # check schedule every 10 s


def visit_site(page, site):
    if site["type"] == "portfolio":
        ping_portfolio(page, site)
    elif site["type"] == "streamlit":
        ping_streamlit(page, site)
    else:
        raise ValueError(f"Unknown site type: {site['type']!r}")


def start_keepalive_worker():
    global worker_thread
    with worker_lock:
        if worker_thread is None or not worker_thread.is_alive():
            worker_thread = threading.Thread(target=worker, daemon=True)
            worker_thread.start()
            log.info("Keep-alive worker started.")
    return worker_thread


def refresh_all_sites():
    def refresh_loop():
        log.info("Manual refresh started.")
        try:
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
                        visit_site(page, site)
                    except Exception as e:
                        add_log(site["id"], f"Manual refresh error: {e}", "error")
                browser.close()
        except Exception as e:
            log.error(f"Manual refresh failed: {e}")
        finally:
            log.info("Manual refresh finished.")

    threading.Thread(target=refresh_loop, daemon=True).start()


# ─── Flask dashboard ──────────────────────────────────────────────────────────

app = Flask(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>KeepAlive Dashboard</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet"/>
  <style>
    :root {
      --bg: #0d0f17;
      --surface: #141824;
      --border: #1e2436;
      --accent: #6c63ff;
      --accent2: #48e5c2;
      --green: #22c55e;
      --yellow: #f59e0b;
      --red: #ef4444;
      --blue: #3b82f6;
      --text: #e2e8f0;
      --muted: #64748b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; min-height: 100vh; }

    /* ── Header ── */
    header {
      background: linear-gradient(135deg, #1a1f35 0%, #0d1220 100%);
      border-bottom: 1px solid var(--border);
      padding: 20px 32px;
      display: flex; align-items: center; justify-content: space-between;
    }
    .logo { display: flex; align-items: center; gap: 12px; }
    .logo-icon {
      width: 44px; height: 44px; border-radius: 12px;
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      display: flex; align-items: center; justify-content: center;
      font-size: 22px;
    }
    h1 { font-size: 1.4rem; font-weight: 700; }
    .subtitle { font-size: .8rem; color: var(--muted); }
    .pulse-dot {
      width: 10px; height: 10px; border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 0 0 rgba(34,197,94,.6);
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%   { box-shadow: 0 0 0 0 rgba(34,197,94,.6); }
      70%  { box-shadow: 0 0 0 10px rgba(34,197,94,0); }
      100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); }
    }
    .header-right { display: flex; align-items: center; gap: 10px; font-size: .85rem; color: var(--muted); }

    /* ── Main ── */
    main { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }

    /* ── Cards ── */
    .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 32px; }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 22px;
      position: relative;
      overflow: hidden;
      transition: transform .2s, box-shadow .2s;
    }
    .card:hover { transform: translateY(-3px); box-shadow: 0 12px 40px rgba(0,0,0,.4); }
    .card::before {
      content: '';
      position: absolute; top: 0; left: 0; right: 0; height: 3px;
      background: linear-gradient(90deg, var(--accent), var(--accent2));
      opacity: 0; transition: opacity .3s;
    }
    .card:hover::before { opacity: 1; }

    .card-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 14px; }
    .site-icon { font-size: 1.6rem; }
    .badge {
      display: inline-flex; align-items: center; gap: 5px;
      padding: 4px 10px; border-radius: 20px; font-size: .72rem; font-weight: 600;
    }
    .badge-alive    { background: rgba(34,197,94,.15);  color: var(--green); }
    .badge-sleeping { background: rgba(245,158,11,.15); color: var(--yellow); }
    .badge-waking   { background: rgba(59,130,246,.15); color: var(--blue); }
    .badge-error    { background: rgba(239,68,68,.15);  color: var(--red); }
    .badge-pending  { background: rgba(100,116,139,.15);color: var(--muted); }
    .badge .dot { width:6px; height:6px; border-radius:50%; background:currentColor; }

    .site-name { font-size: 1rem; font-weight: 600; margin-bottom: 4px; }
    .site-url  { font-size: .75rem; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px; }

    .stats { display: flex; gap: 16px; margin: 14px 0; }
    .stat-box { flex:1; background: rgba(255,255,255,.03); border-radius: 10px; padding: 10px 12px; }
    .stat-val { font-size: 1.4rem; font-weight: 700; color: var(--accent2); }
    .stat-lbl { font-size: .65rem; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }

    .msg { font-size: .78rem; color: var(--muted); border-top: 1px solid var(--border); padding-top: 12px; margin-top: 4px; }

    /* ── Logs ── */
    .log-section h2 { font-size: 1rem; font-weight: 600; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
    .log-box {
      background: #0a0c14;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      max-height: 360px;
      overflow-y: auto;
      font-family: 'Courier New', monospace;
      font-size: .78rem;
    }
    .log-entry { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,.03); }
    .log-entry:last-child { border: none; }
    .log-ts    { color: var(--muted); flex-shrink: 0; }
    .log-site  { color: var(--accent); font-weight: 600; flex-shrink: 0; min-width: 130px; }
    .log-msg   { color: var(--text); }
    .log-info    .log-msg { color: var(--text); }
    .log-warning .log-msg { color: var(--yellow); }
    .log-error   .log-msg { color: var(--red); }
    .refresh-button {
      border: 1px solid rgba(255,255,255,.12);
      background: transparent;
      color: var(--text);
      padding: 10px 16px;
      border-radius: 999px;
      cursor: pointer;
      font-size: .85rem;
      transition: background .2s, transform .2s;
    }
    .refresh-button:hover { background: rgba(255,255,255,.05); transform: translateY(-1px); }
    .refresh-button:disabled { opacity: .45; cursor: not-allowed; }

    /* ── Footer ── */
    footer { text-align: center; padding: 24px; color: var(--muted); font-size: .78rem; border-top: 1px solid var(--border); margin-top: 40px; }

    /* ── Spinner ── */
    @keyframes spin { to { transform: rotate(360deg); } }
    .spin { display: inline-block; animation: spin 1s linear infinite; }
  </style>
</head>
<body>
<header>
  <div class="logo">
    <div class="logo-icon">⚡</div>
    <div>
      <h1>KeepAlive Dashboard</h1>
      <div class="subtitle">Auto-waking your sites 24/7</div>
    </div>
  </div>
  <div class="header-right">
        <button class="refresh-button" id="refresh-button">Refresh now</button>
        <div class="pulse-dot"></div>
        <span id="next-refresh">Refreshing display in 10s…</span>
  <div class="log-section">
    <h2>📋 Activity Log</h2>
    <div class="log-box" id="log-box"></div>
  </div>
</main>

<footer>KeepAlive Bot &nbsp;•&nbsp; Pings every 5 minutes &nbsp;•&nbsp; Built for sumantj.xyz</footer>

<script>
const STATUS_ICON = { alive:'✅', sleeping:'😴', waking:'⚡', error:'❌', pending:'⏳' };
const BADGE_CLASS = { alive:'badge-alive', sleeping:'badge-sleeping', waking:'badge-waking', error:'badge-error', pending:'badge-pending' };
const SITE_ICONS  = { portfolio:'🌐', dashboard:'📊', foodreview:'🍔', Pharmacovigilance:'💊' };

let countdown = 10;

function renderCards(data) {
  const container = document.getElementById('cards-container');
  container.innerHTML = Object.entries(data).map(([id, s]) => `
    <div class="card">
      <div class="card-header">
        <div>
          <div class="site-name">${SITE_ICONS[id] || '🔗'} ${s.name}</div>
          <div class="site-url"><a href="${s.url}" target="_blank" style="color:inherit;text-decoration:none;">${s.url}</a></div>
        </div>
        <span class="badge ${BADGE_CLASS[s.status] || 'badge-pending'}">
          <span class="dot"></span>${s.status.toUpperCase()}
        </span>
      </div>
      <div class="stats">
        <div class="stat-box">
          <div class="stat-val">${s.ping_count}</div>
          <div class="stat-lbl">Total Pings</div>
        </div>
        <div class="stat-box">
          <div class="stat-val">${s.wake_count}</div>
          <div class="stat-lbl">Times Woken</div>
        </div>
        <div class="stat-box">
          <div class="stat-val">${s.last_check || '—'}</div>
          <div class="stat-lbl">Last Check</div>
        </div>
      </div>
      <div class="msg">${s.message}</div>
    </div>
  `).join('');
}

function renderLogs(entries) {
  const box = document.getElementById('log-box');
  if (!entries.length) { box.innerHTML = '<span style="color:#4b5563">No activity yet…</span>'; return; }
  box.innerHTML = entries.map(e => `
    <div class="log-entry log-${e.level}">
      <span class="log-ts">${e.ts}</span>
      <span class="log-site">${e.site}</span>
      <span class="log-msg">${e.message}</span>
    </div>
  `).join('');
}

async function refresh() {
  try {
    const [s, l] = await Promise.all([
      fetch('/api/status').then(r => r.json()),
      fetch('/api/logs').then(r => r.json()),
    ]);
    renderCards(s);
    renderLogs(l);
  } catch(e) { console.error(e); }
}

async function requestRefresh() {
  const button = document.getElementById('refresh-button');
  button.disabled = true;
  const original = button.textContent;
  button.textContent = 'Refreshing…';

  try {
    const res = await fetch('/api/refresh', { method: 'POST' });
    if (!res.ok) throw new Error('Refresh request failed');
  } catch (err) {
    console.error(err);
    alert('Unable to start manual refresh. Check the logs.');
  } finally {
    setTimeout(() => {
      button.disabled = false;
      button.textContent = original;
    }, 5000);
  }
}

document.getElementById('refresh-button').addEventListener('click', requestRefresh);

function tick() {
  countdown--;
  if (countdown <= 0) {
    countdown = 10;
    refresh();
  }
  document.getElementById('next-refresh').textContent = `Refreshing display in ${countdown}s…`;
}

refresh();
setInterval(tick, 1000);
</script>
</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@app.route("/api/status")
def api_status():
    return jsonify(site_status)

@app.route("/api/logs")
def api_logs():
    return jsonify(logs)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    refresh_all_sites()
    return jsonify({"status": "started", "message": "Manual refresh started."}), 202


@app.route("/healthz")
def api_healthz():
    return jsonify({"status": "ok", "message": "KeepAlive service is running."}), 200


@app.before_first_request
def ensure_worker_running():
    start_keepalive_worker()


# ─── Entry point ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    start_keepalive_worker()
    log.info("Dashboard → http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
