import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from requests_oauthlib import OAuth1

# ========= 設定 =========
FINNHUB_API_KEY = os.environ["FINNHUB_API_KEY"]
STATE_PATH = "bots/finnhub_cpi/state.json"

FINNHUB_URL = "https://finnhub.io/api/v1/calendar/economic"
COUNTRY = "US"

RETRY_SECONDS = 300      # 最大5分
RETRY_INTERVAL = 30      # 30秒おき

# X API
def post_to_x(text: str):
    auth = OAuth1(
        os.environ["X_API_KEY"],
        os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_SECRET"],
    )
    r = requests.post(
        "https://api.x.com/2/tweets",
        json={"text": text},
        auth=auth,
        timeout=30,
    )
    r.raise_for_status()

# ========= state =========
def load_state():
    if not os.path.exists(STATE_PATH):
        return {"posted": []}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def posted(state, key):
    return key in state["posted"]

def mark_posted(state, key):
    state["posted"].append(key)

# ========= Finnhub =========
def fetch_events(start, end):
    params = {
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "token": FINNHUB_API_KEY,
    }
    r = requests.get(FINNHUB_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("economicCalendar", [])

def is_cpi(event):
    name = event.get("event", "").lower()
    return "cpi" in name

def classify(event):
    name = event.get("event", "").lower()
    mom = "mom" in name or "m/m" in name
    yoy = "yoy" in name or "y/y" in name
    core = "core" in name
    return mom, yoy, core

# ========= 投稿文 =========
def build_text(month, blocks):
    lines = [f"🇺🇸消費者物価指数（CPI）（{month}）"]
    for b in blocks:
        lines.append(f"🟢{b['title']}")
        lines.append(f"結果：{b['actual']}%")
        lines.append(f"予想：{b['estimate']}%")
        lines.append(f"前回：{b['prev']}%")
    return "\n".join(lines)

# ========= メイン =========
def main():
    state = load_state()
    now = datetime.now(timezone.utc)

    events = fetch_events(now - timedelta(days=1), now + timedelta(days=1))
    cpi_events = [e for e in events if e.get("country") == COUNTRY and is_cpi(e)]

    if not cpi_events:
        return

    # 発表時刻でグルーピング
    groups = {}
    for e in cpi_events:
        t = e.get("time")
        if not t:
            continue
        groups.setdefault(t, []).append(e)

    for release_time, items in groups.items():
        key = f"CPI_{release_time}"
        if posted(state, key):
            continue

        release_dt = datetime.fromisoformat(release_time.replace("Z", "+00:00"))
        if now < release_dt:
            continue

        # actual が入るまでリトライ
        deadline = now + timedelta(seconds=RETRY_SECONDS)
        while datetime.now(timezone.utc) < deadline:
            ready = True
            for e in items:
                if e.get("actual") is None:
                    ready = False
            if ready:
                break
            time.sleep(RETRY_INTERVAL)

        blocks = []
        for e in items:
            if e.get("actual") is None:
                continue

            mom, yoy, core = classify(e)
            if not (mom or yoy):
                continue

            title = "CPI"
            if core:
                title = "コアCPI"
            title += "（前月比）" if mom else "（前年比）"

            blocks.append({
                "title": title,
                "actual": e["actual"],
                "estimate": e.get("estimate", "—"),
                "prev": e.get("prev", "—"),
            })

        if not blocks:
            continue

        month = release_dt.month
        text = build_text(month, blocks)
        post_to_x(text)

        mark_posted(state, key)
        save_state(state)

if __name__ == "__main__":
    main()

