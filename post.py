import json, os, sys, requests
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from bs4 import BeautifulSoup
from requests_oauthlib import OAuth1

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
FRED_BASE = "https://api.stlouisfed.org/fred"
STATE_PATH = "state.json"
NOWCAST_URL = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"

# --- utils ---
def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def round_half_up(x: float, ndigits: int = 2) -> float:
    q = Decimal("1." + "0" * ndigits)     # 2桁なら 1.00
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))

def pct(new, old):
    return (new / old - 1.0) * 100.0

def month_jp(date_str: str) -> str:
    return f"{int(date_str[5:7])}月"

def dash_or_pct(x):
    return "—" if x is None else f"{x:.2f}％"

# --- FRED ---
def fred_obs(series_id: str, limit: int = 36):
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
    return r.json()["observations"]

def valid_values(obs):
    out = []
    for o in obs:
        v = o.get("value")
        if v not in (None, "", "."):
            out.append((o["date"], float(v)))
    return out

# --- Cleveland Fed Nowcast (HTML table) ---
def fetch_nowcast_tables():
    r = requests.get(NOWCAST_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # このページは本文中に
    # "Inflation, month-over-month percent change" と
    # "Inflation, year-over-year percent change" の表がある :contentReference[oaicite:2]{index=2}
    text = soup.get_text("\n", strip=True)

    # 表をざっくり取得（ページ構造変更に耐えるため “最初の2つの大きい表” を拾う）
    tables = soup.find_all("table")
    if len(tables) < 2:
        raise RuntimeError("Nowcast tables not found (page structure changed?)")
    return tables[0], tables[1]  # だいたい MoM, YoY の順

def table_to_rows(table):
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows

def pick_month_value(rows, target_month_label, col_name):
    # rows[0] is header: ["Month","CPI","Core CPI",...,"Updated"]
    header = rows[0]
    if col_name not in header:
        return None
    idx = header.index(col_name)
    for r in rows[1:]:
        if not r:
            continue
        if r[0] == target_month_label:
            if idx >= len(r):
                return None
            raw = r[idx].strip()
            if raw == "":
                return None
            try:
                return float(raw)
            except:
                return None
    return None

def save_nowcast_for_target_month(state, target_month_label: str):
    mom_table, yoy_table = fetch_nowcast_tables()
    mom_rows = table_to_rows(mom_table)
    yoy_rows = table_to_rows(yoy_table)

    cpi_mom = pick_month_value(mom_rows, target_month_label, "CPI")
    core_mom = pick_month_value(mom_rows, target_month_label, "Core CPI")
    cpi_yoy = pick_month_value(yoy_rows, target_month_label, "CPI")

    # 実績が出た月は空欄になり得る（公式注記）:contentReference[oaicite:3]{index=3}
    cpi_mom = None if cpi_mom is None else round_half_up(cpi_mom, 2)
    core_mom = None if core_mom is None else round_half_up(core_mom, 2)
    cpi_yoy = None if cpi_yoy is None else round_half_up(cpi_yoy, 2)

    state["nowcast"] = {
        "target_month_label": target_month_label,  # 例: "December 2025"
        "cpi_mom": cpi_mom,
        "cpi_yoy": cpi_yoy,
        "core_cpi_mom": core_mom,
        "saved_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Cleveland Fed Inflation Nowcasting",
    }
    return state["nowcast"]

def guess_target_month_label_from_fred():
    # 発表直前に保存する想定：FREDの最新CPI月の「次の月」を狙う
    cpi = valid_values(fred_obs("CPIAUCSL", limit=24))
    latest_date = cpi[0][0]  # "YYYY-MM-01"
    dt = datetime.strptime(latest_date, "%Y-%m-%d")
    # 次月
    y = dt.year + (1 if dt.month == 12 else 0)
    m = 1 if dt.month == 12 else dt.month + 1
    target = datetime(y, m, 1)
    return target.strftime("%B %Y")  # "December 2025"

# --- X post ---
def post_to_x(text: str):
    auth = OAuth1(
        os.environ["X_CONSUMER_KEY"],
        os.environ["X_CONSUMER_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    r = requests.post("https://api.x.com/2/tweets", json={"text": text}, auth=auth, timeout=30)
    r.raise_for_status()
    return r.json()

# --- CPI post composition ---
def build_cpi_text_with_saved_nowcast(state):
    cpi = valid_values(fred_obs("CPIAUCSL", limit=36))
    core = valid_values(fred_obs("CPILFESL", limit=36))

    (d0, v0), (d1, v1), (d2, v2) = cpi[0], cpi[1], cpi[2]
    cpi_mom = round_half_up(pct(v0, v1), 2)
    cpi_mom_prev = round_half_up(pct(v1, v2), 2)

    # YoY
    (_, v12), (_, v13) = cpi[12], cpi[13]
    cpi_yoy = round_half_up(pct(v0, v12), 2)
    cpi_yoy_prev = round_half_up(pct(v1, v13), 2)

    # core mom
    (dc0, cv0), (dc1, cv1), (dc2, cv2) = core[0], core[1], core[2]
    core_mom = round_half_up(pct(cv0, cv1), 2)
    core_mom_prev = round_half_up(pct(cv1, cv2), 2)

    mm = month_jp(d0)

    saved = state.get("nowcast", {})
    fc_cpi_mom = saved.get("cpi_mom")
    fc_cpi_yoy = saved.get("cpi_yoy")
    fc_core_mom = saved.get("core_cpi_mom")
    saved_at = saved.get("saved_at_utc")

    footer = ""
    if saved_at:
        footer = f"\n\n※予想：Cleveland Fed Nowcast（発表前保存 / {saved_at}）"

    text = "\n".join([
        f"🇺🇸消費者物価指数（CPI）（{mm}）",
        "🟢CPI（前月比）",
        f"結果：{cpi_mom:.2f}％",
        f"予想：{dash_or_pct(fc_cpi_mom)}",
        f"前回：{cpi_mom_prev:.2f}％",
        "",
        "🟢CPI（前年比）",
        f"結果：{cpi_yoy:.2f}％",
        f"予想：{dash_or_pct(fc_cpi_yoy)}",
        f"前回：{cpi_yoy_prev:.2f}％",
        "",
        "🟢コアCPI（前月比）",
        f"結果：{core_mom:.2f}％",
        f"予想：{dash_or_pct(fc_core_mom)}",
        f"前回：{core_mom_prev:.2f}％",
    ]) + footer

    return d0, text  # d0 が最新観測日

# --- entrypoints ---
def cmd_save_nowcast():
    state = load_state()
    target_label = guess_target_month_label_from_fred()
    saved = save_nowcast_for_target_month(state, target_label)
    save_state(state)
    print(f"Saved nowcast for {target_label}: {saved}")

def cmd_post_cpi():
    state = load_state()

    # FRED更新判定（CPIAUCSLの最新日付）
    cpi = valid_values(fred_obs("CPIAUCSL", limit=5))
    latest_date = cpi[0][0]
    if state.get("cpi_last_date") == latest_date:
        print("No CPI update; nothing posted.")
        return

    d0, text = build_cpi_text_with_saved_nowcast(state)
    post_to_x(text)

    state["cpi_last_date"] = d0
    save_state(state)
    print("Posted CPI.")

def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python bot.py save_nowcast|post_cpi")
    mode = sys.argv[1].strip()
    if mode == "save_nowcast":
        cmd_save_nowcast()
    elif mode == "post_cpi":
        cmd_post_cpi()
    else:
        raise SystemExit("Unknown mode")

if __name__ == "__main__":
    main()
