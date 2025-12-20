# employment_report/minkabu_forecast.py
import re
import requests
from bs4 import BeautifulSoup

URL = "https://fx.minkabu.jp/indicators/US-NFP"

_RE_ROW = re.compile(
    r"^(?P<year>\d{4})年(?P<month>\d{1,2})月\s+"
    r"(?P<nfp_fc>-?\d+(?:\.\d+)?)万人\s+(?P<nfp_ac>-?\d+(?:\.\d+)?)万人\s+(?P<nfp_pr>-?\d+(?:\.\d+)?|---)万人\s+"
    r"(?P<ur_fc>-?\d+(?:\.\d+)?)%\s+(?P<ur_ac>-?\d+(?:\.\d+)?)%\s+(?P<ur_pr>-?\d+(?:\.\d+)?|---)%\s+"
    r"(?P<ahe_mom_fc>-?\d+(?:\.\d+)?)%\s+(?P<ahe_mom_ac>-?\d+(?:\.\d+)?)%\s+(?P<ahe_mom_pr>-?\d+(?:\.\d+)?|---)%\s+"
    r"(?P<ahe_yoy_fc>-?\d+(?:\.\d+)?)%\s+(?P<ahe_yoy_ac>-?\d+(?:\.\d+)?)%\s+(?P<ahe_yoy_pr>-?\d+(?:\.\d+)?|---)%\s*$"
)

def _f(x: str):
    if x is None:
        return None
    x = x.strip()
    return None if x == "---" else float(x)

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

    # strip=True だと行が潰れることがあるので、stripしない
    raw_text = soup.get_text("\n", strip=False)

    # 行単位で「YYYY年MM月 ...」を拾ってパース
    rows = []
    for ln in raw_text.splitlines():
        line = " ".join(ln.split())  # 連続空白を1つに正規化
        if not re.match(r"^\d{4}年\d{1,2}月", line):
            continue
        m = _RE_ROW.match(line)
        if not m:
            continue

        year = int(m.group("year"))
        month = int(m.group("month"))
        ym = f"{year:04d}-{month:02d}"

        rows.append({
            "ym": ym,
            "year": year,
            "month": month,
            "monthLabel": f"{month}月",
            "forecast": {
                "nfp_man": _f(m.group("nfp_fc")),
                "unemployment_rate": _f(m.group("ur_fc")),
                "ahe_mom": _f(m.group("ahe_mom_fc")),
                "ahe_yoy": _f(m.group("ahe_yoy_fc")),
            },
            # デバッグ用に残す（必要ならrun.pyでprintできる）
            "debug": {"raw_line": line},
        })

    if not rows:
        raise RuntimeError("minkabu: could not parse any valid row (page structure changed?)")

    # 最新月が上にあるが、念のためym降順
    rows.sort(key=lambda x: x["ym"], reverse=True)

    # 「予想」が --- の月が混ざる場合があるので、予想が揃ってる行を優先
    for row in rows:
        fc = row["forecast"]
        if all(fc.get(k) is not None for k in ["nfp_man", "unemployment_rate", "ahe_mom", "ahe_yoy"]):
            return row

    # それでもダメなら最新行を返す（発表直後など）
    return rows[0]
