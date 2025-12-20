# employment_report/minkabu_forecast.py
import requests

API_URL = "https://fx.minkabu.jp/api/indicator/US-NFP"

def fetch_minkabu_forecast() -> dict:
    r = requests.get(
        API_URL,
        headers={
            "User-Agent": "EconomicIndicators_BOT/1.0",
            "Accept": "application/json",
        },
        timeout=20,
    )
    r.raise_for_status()

    j = r.json()
    rows = j.get("data", [])
    if not rows:
        raise RuntimeError("minkabu api: empty data")

    # 最新月が先頭
    row = rows[0]

    ym = row["date"]            # "2025-11"
    year, month = ym.split("-")
    month = int(month)

    fc = row.get("forecast", {})

    return {
        "ym": ym,
        "year": int(year),
        "month": month,
        "monthLabel": f"{month}月",
        "forecast": {
            "nfp_man": fc.get("employment"),              # 万人
            "unemployment_rate": fc.get("unemployment_rate"),
            "ahe_mom": fc.get("ahe_mom"),
            "ahe_yoy": fc.get("ahe_yoy"),
        }
    }
