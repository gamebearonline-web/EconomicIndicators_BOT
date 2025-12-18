import json
import os
import requests
from requests_oauthlib import OAuth1

FRED_API_KEY = os.environ["FRED_API_KEY"]
FRED_BASE = "https://api.stlouisfed.org/fred"
STATE_PATH = "state.json"

def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

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

def pct(new, old):
    return (new / old - 1.0) * 100.0

def month_jp(date_str: str) -> str:
    m = int(date_str[5:7])
    return f"{m}月"

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

# ---- 雇用統計 ----
def build_jobs_text():
    pay = valid_values(fred_obs("PAYEMS", limit=36))            # レベル（千人）
    unr = valid_values(fred_obs("UNRATE", limit=12))            # %
    ahe = valid_values(fred_obs("CES0500000003", limit=12))     # $/hour

    # PAYEMS：最新2点で前年差分（千人→万人）
    (d0, v0), (d1, v1) = pay[0], pay[1]
    nfp_10k = (v0 - v1) / 10.0

    # UNRATE：結果=最新、前回=1つ前
    (du0, uu0), (du1, uu1) = unr[0], unr[1]

    # 平均時給：前月比%（レベルから計算）
    (da0, aa0), (da1, aa1), (da2, aa2) = ahe[0], ahe[1], ahe[2]
    ahe_mom = pct(aa0, aa1)
    ahe_mom_prev = pct(aa1, aa2)

    mm = month_jp(d0)

    text = "\n".join([
        f"🇺🇸雇用統計（{mm}）",
        "🟢非農業部門雇用者数",
        f"結果：{nfp_10k:.1f}万人",
        "予想：—",
        f"前回：{((v1 - pay[2][1]) / 10.0):.1f}万人",  # 前回月の前年差分
        "",
        "🟢失業率",
        f"結果：{uu0:.1f}％",
        "予想：—",
        f"前回：{uu1:.1f}％",
        "",
        "🟢平均時給（前月比）",
        f"結果：{ahe_mom:.2f}％",
        "予想：—",
        f"前回：{ahe_mom_prev:.2f}％",
    ])
    return d0, text  # d0 を「更新判定用の最新日付」に

# ---- CPI ----
def build_cpi_text():
    cpi = valid_values(fred_obs("CPIAUCSL", limit=36))    # 指数
    core = valid_values(fred_obs("CPILFESL", limit=36))   # 指数

    (d0, v0), (d1, v1), (d2, v2) = cpi[0], cpi[1], cpi[2]
    cpi_mom = pct(v0, v1)
    cpi_mom_prev = pct(v1, v2)

    # YoY（12か月前）
    (_, v12) = cpi[12]
    (_, v13) = cpi[13]
    cpi_yoy = pct(v0, v12)
    cpi_yoy_prev = pct(v1, v13)

    (dc0, cv0), (dc1, cv1), (dc2, cv2) = core[0], core[1], core[2]
    core_mom = pct(cv0, cv1)
    core_mom_prev = pct(cv1, cv2)

    mm = month_jp(d0)

    text = "\n".join([
        f"🇺🇸消費者物価指数（CPI）（{mm}）",
        "🟢CPI（前月比）",
        f"結果：{cpi_mom:.2f}％",
        "予想：—",
        f"前回：{cpi_mom_prev:.2f}％",
        "",
        "🟢CPI（前年比）",
        f"結果：{cpi_yoy:.2f}％",
        "予想：—",
        f"前回：{cpi_yoy_prev:.2f}％",
        "",
        "🟢コアCPI（前月比）",
        f"結果：{core_mom:.2f}％",
        "予想：—",
        f"前回：{core_mom_prev:.2f}％",
    ])
    return d0, text

def main():
    state = load_state()
    posted_any = False

    # 雇用統計：PAYEMSの最新日付で更新判定
    jobs_date, jobs_text = build_jobs_text()
    if state.get("jobs_last_date") != jobs_date:
        post_to_x(jobs_text)
        state["jobs_last_date"] = jobs_date
        posted_any = True

    # CPI：CPIAUCSLの最新日付で更新判定
    cpi_date, cpi_text = build_cpi_text()
    if state.get("cpi_last_date") != cpi_date:
        post_to_x(cpi_text)
        state["cpi_last_date"] = cpi_date
        posted_any = True

    save_state(state)

    if not posted_any:
        print("No updates; nothing posted.")


from decimal import Decimal, ROUND_HALF_UP
from bs4 import BeautifulSoup

NOWCAST_URL = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"

def round_half_up(x: float, ndigits: int = 2) -> float:
    q = Decimal("1." + "0" * ndigits)  # 例: ndigits=2 -> Decimal("1.00")
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))

def cleveland_nowcast_for_month(target_ym: str):
    """
    target_ym: "YYYY-MM"（例: "2025-12"）
    return: (cpi_mom, core_mom, cpi_yoy) いずれも float or None
    """
    r = requests.get(NOWCAST_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    def pick_from_table(table_title_contains: str, col_name: str):
        # ページ内の該当テーブルを探して、target_ym行の指定列を返す（空欄なら None）
        # table_title_contains: "month-over-month" or "year-over-year" のような断片
        headers = soup.find_all(["h2", "h3", "h4", "h5"])
        table = None
        for h in headers:
            if h.get_text(strip=True).lower().find(table_title_contains) >= 0:
                # 次に出てくる table を拾う
                nxt = h.find_next("table")
                if nxt:
                    table = nxt
                    break
        if table is None:
            return None

        # ヘッダー行
        ths = table.find_all("th")
        # テーブル構造が変わった時に壊れにくいよう、行ごとに解析
        rows = table.find_all("tr")
        if not rows:
            return None

        # 1行目がヘッダー想定
        header_cells = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        if col_name not in header_cells:
            return None
        col_idx = header_cells.index(col_name)

        # データ行から "Month" を "December 2025" のように持っているので target_ym と突合
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if not cells:
                continue
            month_text = cells[0]  # "December 2025"
            # "December 2025" -> "2025-12"
            try:
                dt = datetime.strptime(month_text, "%B %Y")
                ym = dt.strftime("%Y-%m")
            except Exception:
                continue

            if ym == target_ym:
                if col_idx >= len(cells):
                    return None
                raw = cells[col_idx]
                if raw == "" or raw is None:
                    return None
                try:
                    return float(raw)
                except Exception:
                    return None
        return None

    # MoMテーブルから CPI / Core CPI
    cpi_mom = pick_from_table("month-over-month", "CPI")
    core_mom = pick_from_table("month-over-month", "Core CPI")

    # YoYテーブルから CPI
    cpi_yoy = pick_from_table("year-over-year", "CPI")

    # 四捨五入（小数点2位）
    cpi_mom = None if cpi_mom is None else round_half_up(cpi_mom, 2)
    core_mom = None if core_mom is None else round_half_up(core_mom, 2)
    cpi_yoy = None if cpi_yoy is None else round_half_up(cpi_yoy, 2)

    return cpi_mom, core_mom, cpi_yoy


if __name__ == "__main__":
    main()
