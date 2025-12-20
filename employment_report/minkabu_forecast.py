import re
import requests
from bs4 import BeautifulSoup

URL = "https://fx.minkabu.jp/indicators/US-NFP"

def _parse_pct(s: str):
    t = (s or "").strip().replace(" ", "")
    if t in ("---", "", "N/A"):
        return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)%", t)
    return float(m.group(1)) if m else None

def _parse_man(s: str):
    t = (s or "").strip().replace(" ", "")
    if t in ("---", "", "N/A"):
        return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)万人", t)
    return float(m.group(1)) if m else None

def _parse_month(s: str):
    m = re.search(r"(\d{4})年(\d{1,2})月", s)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2))
    return {
        "ym": f"{year:04d}-{month:02d}",
        "monthLabel": f"{month}月",
        "year": year,
        "month": month,
    }

def fetch_minkabu_forecast() -> dict:
    r = requests.get(
        URL,
        headers={
            "User-Agent": "EconomicIndicators_BOT/1.0 (+https://github.com/gamebearonline-web/EconomicIndicators_BOT)",
            "Accept-Language": "ja,en;q=0.8",
        },
        timeout=25,
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")
    text = soup.get_text("\n", strip=True)

    # "YYYY年MM月 ..." の行を拾う
    lines = [ln.strip() for ln in text.split("\n") if re.match(r"^\d{4}年\d{1,2}月", ln.strip())]

    if not lines:
        raise RuntimeError("minkabu: monthly lines not found (page structure changed?)")

    rows = []
    for ln in lines:
        tokens = re.split(r"\s+", ln)
        # 期待：13トークン以上（CPIの時の表と同型）
        if len(tokens) < 13:
            continue
        m = _parse_month(tokens[0])
        if not m:
            continue

        rows.append({
            **m,
            "nfp_forecast_man": _parse_man(tokens[1]),
            "ur_forecast_pct": _parse_pct(tokens[4]),
            "ahe_mom_forecast_pct": _parse_pct(tokens[7]),
            "ahe_yoy_forecast_pct": _parse_pct(tokens[10]),
            "raw": ln,
        })

    if not rows:
        raise RuntimeError("minkabu: could not parse any valid row")

    # 新しい月が上に来ている想定。念のため ym 降順。
    rows.sort(key=lambda x: x["ym"], reverse=True)

    picked = rows[0]

    return {
        "source": URL,
        "ym": picked["ym"],
        "monthLabel": picked["monthLabel"],
        "year": picked["year"],
        "month": picked["month"],
        "forecast": {
            "nfp_man": picked["nfp_forecast_man"],                  # 万人
            "unemployment_rate": picked["ur_forecast_pct"],         # %
            "ahe_mom": picked["ahe_mom_forecast_pct"],              # %
            "ahe_yoy": picked["ahe_yoy_forecast_pct"],              # %
        },
        "debug": {"raw": picked["raw"]},
    }
