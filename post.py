import os
import requests
from requests_oauthlib import OAuth1

FRED_API_KEY = os.environ["FRED_API_KEY"]
FRED_BASE = "https://api.stlouisfed.org/fred"

SERIES = [
  ("CPI", "CPIAUCSL"),
  ("コアCPI", "CPILFESL"),
  ("失業率", "UNRATE"),
  ("非農業部門雇用者数", "PAYEMS"),
]

def fred_latest_and_prev(series_id: str, fetch_limit: int = 20):
    url = f"{FRED_BASE}/series/observations"
    params = dict(
        series_id=series_id,
        api_key=FRED_API_KEY,
        file_type="json",
        sort_order="desc",
        limit=fetch_limit
    )
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    obs = r.json()["observations"]

    vals = []
    for o in obs:
        v = o.get("value")
        if v not in (None, "", "."):
            vals.append((o["date"], v))
        if len(vals) >= 2:
            break

    if len(vals) < 2:
        raise RuntimeError(f"Not enough valid observations for {series_id}")

    (d0, v0), (d1, v1) = vals[0], vals[1]
    return d0, v0, d1, v1

def format_line(label, d0, v0, d1, v1):
    # 例: CPI（2025-11-01）: 314.0（前回 313.2）
    return f"{label}（{d0}）: {v0}（前回 {d1}: {v1}）"

def post_to_x(text: str):
    # X: POST /2/tweets :contentReference[oaicite:8]{index=8}
    auth = OAuth1(
        os.environ["X_API_KEY"],
        os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_SECRET"],
    )
    url = "https://api.x.com/2/tweets"
    r = requests.post(url, json={"text": text}, auth=auth, timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    lines = []
    for label, sid in SERIES:
        d0, v0, d1, v1 = fred_latest_and_prev(sid)
        lines.append(format_line(label, d0, v0, d1, v1))

    body = "【FRED 指標更新】\n" + "\n".join(f"- {ln}" for ln in lines)
    post_to_x(body)

if __name__ == "__main__":
    main()
