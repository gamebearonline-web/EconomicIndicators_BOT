import os, requests

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
KEY = os.getenv("BLS_API_KEY")

SERIES = {
    "nfp": "CES0000000001",      # 千人
    "ahe": "CES0500000003",      # $
    "ur":  "LNS14000000"         # %
}

def fetch(series, start, end):
    payload = {
        "seriesid": list(series.values()),
        "startyear": start,
        "endyear": end,
        "registrationkey": KEY
    }
    r = requests.post(BLS_URL, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()["Results"]["series"]

def get_actuals(year, month):
    y = int(year)
    m = int(month)
    ym = f"{y}-{m:02d}"
    prev = f"{y}-{m-1:02d}" if m > 1 else f"{y-1}-12"
    prev2 = f"{y}-{m-2:02d}" if m > 2 else f"{y-1}-{12-(2-m):02d}"

    data = fetch(SERIES, y-1, y)

    d = {s["seriesID"]: {f'{i["year"]}-{i["period"][1:]}': float(i["value"])
         for i in s["data"] if i["period"].startswith("M")}
         for s in data}

    # NFP: 差分 → 万人
    nfp = (d[SERIES["nfp"]][ym] - d[SERIES["nfp"]][prev]) / 10
    nfp_prev = (d[SERIES["nfp"]][prev] - d[SERIES["nfp"]][prev2]) / 10

    # AHE
    ahe = d[SERIES["ahe"]]
    ahe_mom = (ahe[ym] / ahe[prev] - 1) * 100
    ahe_mom_prev = (ahe[prev] / ahe[prev2] - 1) * 100
    ahe_yoy = (ahe[ym] / ahe[f"{y-1}-{m:02d}"] - 1) * 100
    ahe_yoy_prev = (ahe[prev] / ahe[f"{y-1}-{m-1:02d}"] - 1) * 100

    # UR
    ur = d[SERIES["ur"]][ym]
    ur_prev = d[SERIES["ur"]][prev]

    return {
        "nfp": round(nfp,1), "nfp_prev": round(nfp_prev,1),
        "ahe_mom": round(ahe_mom,1), "ahe_mom_prev": round(ahe_mom_prev,1),
        "ahe_yoy": round(ahe_yoy,1), "ahe_yoy_prev": round(ahe_yoy_prev,1),
        "ur": round(ur,1), "ur_prev": round(ur_prev,1)
    }
