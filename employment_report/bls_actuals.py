import os
import requests

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_API_KEY = os.getenv("BLS_API_KEY", "")

SERIES_NFP_LEVEL = "CES0000000001"   # Total nonfarm employment (thousands)
SERIES_AHE_LEVEL = "CES0500000003"   # Average hourly earnings (dollars)
SERIES_UR = "LNS14000000"            # Unemployment rate (%)

def _fetch_bls(series_ids: list[str], start_year: int, end_year: int) -> dict:
    payload = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    if BLS_API_KEY:
        payload["registrationkey"] = BLS_API_KEY

    r = requests.post(BLS_URL, json=payload, timeout=25)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API error: {data}")
    return data

def _to_map(series_json: dict) -> dict[str, dict[str, float]]:
    out = {}
    for s in series_json["Results"]["series"]:
        sid = s["seriesID"]
        m = {}
        for item in s.get("data", []):
            period = item.get("period", "")
            if not period.startswith("M"):
                continue
            month = int(period[1:])
            ym = f"{int(item['year']):04d}-{month:02d}"
            try:
                m[ym] = float(item["value"])
            except Exception:
                continue
        out[sid] = m
    return out

def _ym_prev(ym: str) -> str:
    y, m = ym.split("-")
    y = int(y); m = int(m)
    if m == 1:
        return f"{y-1:04d}-12"
    return f"{y:04d}-{m-1:02d}"

def _ym_prev2(ym: str) -> str:
    return _ym_prev(_ym_prev(ym))

def _ym_yoy(ym: str) -> str:
    y, m = ym.split("-")
    return f"{int(y)-1:04d}-{int(m):02d}"

def _pct_change(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None
    return (cur / prev - 1.0) * 100.0

def get_actuals(ym: str) -> dict:
    y = int(ym.split("-")[0])
    start_year = y - 1
    end_year = y

    raw = _fetch_bls(
        [SERIES_NFP_LEVEL, SERIES_AHE_LEVEL, SERIES_UR],
        start_year=start_year,
        end_year=end_year,
    )
    m = _to_map(raw)

    prev = _ym_prev(ym)
    prev2 = _ym_prev2(ym)
    yoy = _ym_yoy(ym)
    yoy_prev = _ym_yoy(prev)

    # NFP：水準(千人) → 差分(千人) → 万人
    nfp = m.get(SERIES_NFP_LEVEL, {})
    nfp_cur = nfp.get(ym)
    nfp_prev = nfp.get(prev)
    nfp_prev2 = nfp.get(prev2)

    nfp_change_man = None
    nfp_change_prev_man = None
    if nfp_cur is not None and nfp_prev is not None:
        nfp_change_man = (nfp_cur - nfp_prev) / 10.0
    if nfp_prev is not None and nfp_prev2 is not None:
        nfp_change_prev_man = (nfp_prev - nfp_prev2) / 10.0

    # AHE：水準($) → MoM% / YoY%
    ahe = m.get(SERIES_AHE_LEVEL, {})
    ahe_cur = ahe.get(ym)
    ahe_prev = ahe.get(prev)
    ahe_prev2 = ahe.get(prev2)
    ahe_yoy_base = ahe.get(yoy)
    ahe_yoy_prev_base = ahe.get(yoy_prev)

    ahe_mom = _pct_change(ahe_cur, ahe_prev)
    ahe_mom_prev = _pct_change(ahe_prev, ahe_prev2)
    ahe_yoy = _pct_change(ahe_cur, ahe_yoy_base)
    ahe_yoy_prev = _pct_change(ahe_prev, ahe_yoy_prev_base)

    # UR：%
    ur = m.get(SERIES_UR, {})
    ur_cur = ur.get(ym)
    ur_prev = ur.get(prev)

    def r1(x): return None if x is None else round(x, 1)

    return {
        "nfp_man_actual": r1(nfp_change_man),
        "nfp_man_prev": r1(nfp_change_prev_man),
        "ahe_mom_actual": r1(ahe_mom),
        "ahe_mom_prev": r1(ahe_mom_prev),
        "ahe_yoy_actual": r1(ahe_yoy),
        "ahe_yoy_prev": r1(ahe_yoy_prev),
        "ur_actual": r1(ur_cur),
        "ur_prev": r1(ur_prev),
    }
