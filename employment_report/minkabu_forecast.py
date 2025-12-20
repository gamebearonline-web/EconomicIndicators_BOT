# employment_report/minkabu_forecast.py
import json
from pathlib import Path

DATA_FILE = Path("data/employment_forecast_latest.json")

def fetch_minkabu_forecast() -> dict:
    if not DATA_FILE.exists():
        raise RuntimeError(f"forecast json not found: {DATA_FILE}")

    with DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # 最低限のバリデーション
    if "ym" not in data or "forecast" not in data:
        raise RuntimeError("forecast json invalid: missing 'ym' or 'forecast'")

    fc = data["forecast"]
    required = ["ahe_mom", "ahe_yoy", "nfp_man", "unemployment_rate"]
    for k in required:
        if k not in fc:
            raise RuntimeError(f"forecast json invalid: missing forecast.{k}")

    # monthLabel が無い場合の保険
    if "monthLabel" not in data:
        month = int(data["ym"].split("-")[1])
        data["monthLabel"] = f"{month}月"

    return data
