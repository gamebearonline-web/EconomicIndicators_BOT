# employment_report/minkabu_forecast.py

import requests
from bs4 import BeautifulSoup

URL = "https://fx.minkabu.jp/indicators/US-NFP"

def _pct(x):
    if not x or x == "---":
        return None
    return float(x.replace("%", "").strip())

def _man(x):
    if not x or x == "---":
        return None
    return float(x.replace("万人", "").strip())

def fetch_minkabu_forecast():
    r = requests.get(
        URL,
        headers={
            "User-Agent": "EconomicIndicators_BOT/1.0",
            "Accept-Language": "ja,en;q=0.8",
        },
        timeout=20,
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")

    # 指標テーブル（最初のtableがNFP）
    table = soup.find("table")
    if not table:
        raise RuntimeError("minkabu: table not found")

    rows = table.find_all("tr")
    if len(rows) < 2:
        raise RuntimeError("minkabu: no data rows")

    # 1行目はヘッダ、2行目が最新
    cols = [c.get_text(strip=True) for c in rows[1].find_all("td")]
    if len(cols) < 11:
        raise RuntimeError(f"minkabu: unexpected columns {cols}")

    # 列順（2025-12現在）
    # 0: 発表月
    # 1: 雇用者数(予想)
    # 4: 失業率(予想)
    # 7: 平均時給MoM(予想)
    # 10: 平均時給YoY(予想)
    ym_text = cols[0]  # 2025年11月
    year = int(ym_text[:4])
    month = int(ym_text[5:-1])

    return {
        "ym": f"{year}-{month:02d}",
        "monthLabel": f"{month}月",
        "year": year,
        "month": month,
        "forecast": {
            "nfp_man": _man(cols[1]),
            "unemployment_rate": _pct(cols[4]),
            "ahe_mom": _pct(cols[7]),
            "ahe_yoy": _pct(cols[10]),
        }
    }
