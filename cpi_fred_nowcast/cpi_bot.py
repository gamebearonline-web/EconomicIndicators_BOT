import json
import os
import sys
import requests
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from bs4 import BeautifulSoup
from requests_oauthlib import OAuth1

# ========= Config =========
STATE_PATH = "cpi_fred_nowcast/state.json"

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
FRED_BASE = "https://api.stlouisfed.org/fred"

NOWCAST_URL = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"

# FRED series
SERIES_CPI = "CPIAUCSL"   # CPI (Index 1982-84=100)
SERIES_CORE = "CPILFESL"  # Core CPI (Index)

# ========= Utils =========
def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def round_half_up(x: float, ndigits: int = 2) -> float:
    q = Decimal("1." + "0" * ndigits)
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))

def pct_change(new: float, old: float) -> float:
    return (new / old - 1.0) * 100.0

def fmt_pct(x):
    return "—" if x is None else f"{x:.2f}%"

def month_jp_from_fred_date(date_str: str) -> str:
    # FRED CPI date is YYYY-MM-01; we display "MM月"
    return f"{int(date_str[5:7])}月"

# ========= FRED =========
def fred_observations(series_id: str, limit: int = 36):
    if not FRED_API_KEY:
        raise RuntimeError("FRED_API_KEY is missing.")
    r = requests.get(
        f"{FRED_BASE}/series/observations",
        params={
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        },
        timeout=30,
    )
    r.raise_for_status()
    obs = r.json()["observations"]
    out = []
    for o in obs:
        v = o.get("value")
        if v in (None, "", "."):
            continue
        out.append((o["date"], float(v)))
    return out  # desc

def compute_mom_yoy(series_obs):
    """
    series_obs: [(date, value)] desc
    returns:
      latest_date,
      mom, mom_prev,
      yoy, yoy_prev
    """
    if len(series_obs) < 14:
        raise RuntimeError("Not enough observations to compute MoM/YoY.")

    (d0, v0), (d1, v1), (d2, v2) = series_obs[0], series_obs[1], series_obs[2]
    mom = round_half_up(pct_change(v0, v1), 2)
    mom_prev = round_half_up(pct_change(v1, v2), 2)

    # yoy needs 12 months back
    (d12, v12), (d13, v13) = series_obs[12], series_obs[13]
    yoy = round_half_up(pct_change(v0, v12), 2)
    yoy_prev = round_half_up(pct_change(v1, v13), 2)

    return d0, mom, mom_prev, yoy, yoy_prev

# ========= Cleveland Fed Nowcast scraping =========
def fetch_nowcast_tables():
    r = requests.get(NOWCAST_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 2:
        raise RuntimeError("Nowcast tables not found (page structure changed?)")
    # Usually: first is MoM, second is YoY
    return tables[0], tables[1]

def table_to_rows(table):
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows

def pick_value(rows, month_label: str, col_name: str):
    header = rows[0]
    if col_name not in header:
        return None
    idx = header.index(col_name)
    for r in rows[1:]:
        if not r:
            continue
        if r[0].strip() == month_label:
            if idx >= len(r):
                return None
            raw = (r[idx] or "").strip()
            if raw == "":
                return None
            try:
                return float(raw)
            except Exception:
                return None
    return None

def target_month_label_from_fred_next_month() -> str:
    """
    発表前保存用：FREDの最新CPI月の「次月」をNowcast対象月として推定
    例：FRED最新が 2025-11-01 -> target = December 2025
    """
    cpi_obs = fred_observations(SERIES_CPI, limit=24)
    latest_date = cpi_obs[0][0]
    dt = datetime.strptime(latest_date, "%Y-%m-%d")
    y = dt.year + (1 if dt.month == 12 else 0)
    m = 1 if dt.month == 12 else dt.month + 1
    target = datetime(y, m, 1)
    return target.strftime("%B %Y")

def save_nowcast():
    state = load_state()
    month_label = target_month_label_from_fred_next_month()

    mom_table, yoy_table = fetch_nowcast_tables()
    mom_rows = table_to_rows(mom_table)
    yoy_rows = table_to_rows(yoy_table)

    # Columns on page are typically "CPI" and "Core CPI"
    cpi_mom = pick_value(mom_rows, month_label, "CPI")
    core_mom = pick_value(mom_rows, month_label, "Core CPI")

    cpi_yoy = pick_value(yoy_rows, month_label, "CPI")
    core_yoy = pick_value(yoy_rows, month_label, "Core CPI")

    def r2(x):
        return None if x is None else round_half_up(x, 2)

    state["nowcast"] = {
        "target_month_label": month_label,
        "cpi_mom": r2(cpi_mom),
        "core_mom": r2(core_mom),
        "cpi_yoy": r2(cpi_yoy),
        "core_yoy": r2(core_yoy),
        "saved_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Cleveland Fed Inflation Nowcasting",
    }
    save_state(state)
    print(f"Saved nowcast for {month_label}: {state['nowcast']}")

# ========= X Posting =========
def post_to_x(text: str):
    auth = OAuth1(
        os.environ["X_CONSUMER_KEY"],
        os.environ["X_CONSUMER_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    r = requests.post("https://api.x.com/2/tweets", json={"text": text}, auth=auth, timeout=30)
    r.raise_for_status()

# ====== Text builders ======
def build_text_all(month: str, cpi, core, fc):
    # 280超えは post_cpi() 側で自動分割
    lines = [
        f"🇺🇸消費者物価指数（CPI）（{month}）",
        "🟢CPI（前月比）",
        f"結果：{cpi['mom']:.2f}%",
        f"予想：{fmt_pct(fc.get('cpi_mom'))}",
        f"前回：{cpi['mom_prev']:.2f}%",
        "",
        "🟢コアCPI（前月比）",
        f"結果：{core['mom']:.2f}%",
        f"予想：{fmt_pct(fc.get('core_mom'))}",
        f"前回：{core['mom_prev']:.2f}%",
        "",
        "🟡CPI（前年比）",
        f"結果：{cpi['yoy']:.2f}%",
        f"予想：{fmt_pct(fc.get('cpi_yoy'))}",
        f"前回：{cpi['yoy_prev']:.2f}%",
        "",
        "🟡コアCPI（前年比）",
        f"結果：{core['yoy']:.2f}%",
        f"予想：{fmt_pct(fc.get('core_yoy'))}",
        f"前回：{core['yoy_prev']:.2f}%",
    ]
    return "\n".join(lines).strip()

def build_text_mom(month: str, cpi, core, fc):
    lines = [
        f"🇺🇸消費者物価指数（CPI）（{month}）",
        "🟢CPI（前月比）",
        f"結果：{cpi['mom']:.2f}%",
        f"予想：{fmt_pct(fc.get('cpi_mom'))}",
        f"前回：{cpi['mom_prev']:.2f}%",
        "",
        "🟢コアCPI（前月比）",
        f"結果：{core['mom']:.2f}%",
        f"予想：{fmt_pct(fc.get('core_mom'))}",
        f"前回：{core['mom_prev']:.2f}%",
    ]
    return "\n".join(lines).strip()

def build_text_yoy(month: str, cpi, core, fc):
    lines = [
        f"🇺🇸消費者物価指数（CPI）（{month}）",
        "🟡CPI（前年比）",
        f"結果：{cpi['yoy']:.2f}%",
        f"予想：{fmt_pct(fc.get('cpi_yoy'))}",
        f"前回：{cpi['yoy_prev']:.2f}%",
        "",
        "🟡コアCPI（前年比）",
        f"結果：{core['yoy']:.2f}%",
        f"予想：{fmt_pct(fc.get('core_yoy'))}",
        f"前回：{core['yoy_prev']:.2f}%",
    ]
    return "\n".join(lines).strip()

# ========= Main post logic =========
def post_cpi():
    state = load_state()
    post_type = os.environ.get("POST_TYPE", "ALL").strip().upper()
    force = os.environ.get("FORCE_POST", "0") == "1"

    cpi_obs = fred_observations(SERIES_CPI, limit=36)
    core_obs = fred_observations(SERIES_CORE, limit=36)

    d0, cpi_mom, cpi_mom_prev, cpi_yoy, cpi_yoy_prev = compute_mom_yoy(cpi_obs)
    _,  core_mom, core_mom_prev, core_yoy, core_yoy_prev = compute_mom_yoy(core_obs)

    # 二重投稿防止（ALLのときだけ、FRED更新が無ければスキップ）
    last_posted_date = state.get("fred_cpi_last_date")
    if (not force) and post_type == "ALL" and last_posted_date == d0:
        print("No new CPI release detected (same latest date); skipping.")
        return

    month = month_jp_from_fred_date(d0)

    # 保存済みNowcast（発表後に空欄になる問題の回避）
    fc = state.get("nowcast", {})

    cpi = {"mom": cpi_mom, "mom_prev": cpi_mom_prev, "yoy": cpi_yoy, "yoy_prev": cpi_yoy_prev}
    core = {"mom": core_mom, "mom_prev": core_mom_prev, "yoy": core_yoy, "yoy_prev": core_yoy_prev}

    posted_keys = state.get("posted_keys", [])

    if post_type == "MOM":
        key = f"CPI_MOM_{d0}"
        if (not force) and key in posted_keys:
            print("Already posted MOM; skipping.")
            return

        text = build_text_mom(month, cpi, core, fc)
        post_to_x(text)

        state.setdefault("posted_keys", []).append(key)
        save_state(state)
        print("Posted CPI MOM successfully.")
        return

    if post_type == "YOY":
        key = f"CPI_YOY_{d0}"
        if (not force) and key in posted_keys:
            print("Already posted YOY; skipping.")
            return

        text = build_text_yoy(month, cpi, core, fc)
        post_to_x(text)

        state.setdefault("posted_keys", []).append(key)
        save_state(state)
        print("Posted CPI YOY successfully.")
        return

    # ALL
    key = f"CPI_ALL_{d0}"
    if (not force) and key in posted_keys:
        print("Already posted ALL; skipping.")
        return

    text_all = build_text_all(month, cpi, core, fc)

    # 280字超え対策（安全に分割）
    if len(text_all) > 275:
        text_mom = build_text_mom(month, cpi, core, fc)
        text_yoy = build_text_yoy(month, cpi, core, fc)
        post_to_x(text_mom)
        post_to_x(text_yoy)
    else:
        post_to_x(text_all)

    state.setdefault("posted_keys", []).append(key)
    state["fred_cpi_last_date"] = d0
    save_state(state)
    print("Posted CPI ALL successfully.")

def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python cpi_bot.py save_nowcast|post_cpi")

    cmd = sys.argv[1].strip().lower()
    if cmd == "save_nowcast":
        save_nowcast()
    elif cmd == "post_cpi":
        post_cpi()
    else:
        raise SystemExit("Unknown command")

if __name__ == "__main__":
    main()
