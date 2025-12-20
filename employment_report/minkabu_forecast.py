import re, requests
from bs4 import BeautifulSoup

URL = "https://fx.minkabu.jp/indicators/US-NFP"

def _pct(s):
    s = s.strip()
    if s in ("---", ""): return None
    return float(s.replace("%", ""))

def _man(s):
    s = s.strip()
    if s in ("---", ""): return None
    return float(s.replace("万人", ""))

def fetch_forecast():
    r = requests.get(URL, headers={"User-Agent": "EconomicIndicatorsBOT"}, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    text = soup.get_text("\n")

    lines = [l for l in text.split("\n") if re.match(r"\d{4}年\d{1,2}月", l)]
    lines.sort(reverse=True)

    for l in lines:
        t = re.split(r"\s+", l)
        if len(t) < 13: continue

        return {
            "month": re.search(r"(\d{1,2})月", t[0]).group(1),
            "nfp": _man(t[1]),
            "ur": _pct(t[4]),
            "ahe_mom": _pct(t[7]),
            "ahe_yoy": _pct(t[10]),
        }

    raise RuntimeError("Forecast not found")
