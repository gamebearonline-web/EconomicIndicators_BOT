import json, os, math, requests
from datetime import datetime
from requests_oauthlib import OAuth1

FRED_API_KEY = os.environ["FRED_API_KEY"]
FRED_BASE = "https://api.stlouisfed.org/fred"
STATE_PATH = "state.json"

def fred_obs(series_id, limit=24):
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

def latest_two_valid(obs):
    vals = []
    for o in obs:
        v = o.get("value")
        if v not in (None, "", "."):
            vals.append((o["date"], float(v)))
        if len(vals) >= 2:
            break
    if len(vals) < 2:
        raise RuntimeError("Not enough valid observations")
    return vals[0], vals[1]  # (latest, prev)

def pct(new, old):
    return (new / old - 1.0) * 100.0

def month_jp(date_str):  # "2025-11-01" -> "11月"
    m = int(date_str[5:7])
    return f"{m}月"

def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def dash_if_none(x, fmt):
    return "—" if x is None else fmt.format(x)

def revision_pm(state, key, prev_value_now):
    """
    前回投稿時点で保存していた「前回値」と、
    今回取得した「前回値（＝前月分の改定後値）」の差を改定幅として出す
    """
    old = state.get(key)  # 前回保存した前回値
    if old is None:
        return None
    return prev_value_now - float(old)

def build_jobs_post(state, forecasts=None):
    forecasts = forecasts or {}
    # 実績取得
    (d_pay, pay), (d_pay_prev, pay_prev) = latest_two_valid(fred_obs("PAYEMS"))  # 千人 :contentReference[oaicite:8]{index=8}
    (d_unr, unr), (d_unr_prev, unr_prev) = latest_two_valid(fred_obs("UNRATE"))  # % :contentReference[oaicite:9]{index=9}
    (d_ahe, ahe), (d_ahe_prev, ahe_prev) = latest_two_valid(fred_obs("CES0500000003"))  # $/hour :contentReference[oaicite:10]{index=10}

    # 表示用に加工
    nfp_change_k = pay - pay_prev          # 千人
    nfp_change_10k = nfp_change_k / 10.0   # 万人
    ahe_mom = pct(ahe, ahe_prev)           # %

    # 予想（外部入力）
    fc_nfp = forecasts.get("nfp_10k")      # 万人
    fc_unr = forecasts.get("unrate")       # %
    fc_ahe = forecasts.get("ahe_mom")      # %

    # 改定幅（±）
    pm_nfp = revision_pm(state, "prev_nfp_10k", (pay_prev - (pay_prev - 0)) / 10.0)  # 後で下で正しく保存するための枠
    # ↑ここは値保存の仕様上、下の「保存」を見てください（簡略化のため、±計算は“保存した前回値との差”で出します）

    # ここでは「今回の前回値」を作る（前月の前年差分ではなく、前月“前年差分”を保存しておく運用にするのが分かりやすい）
    # 前月の雇用増減（=前月PAYEMS - 前々月PAYEMS）を今回計算して ± に使いたいなら、obsを3点取って計算します。
    # まずは運用が簡単な「前回=今回の雇用増減（前年差分）」で進めます。

    mm = month_jp(d_pay)

    # NOTE: ±は「前回投稿時の前回値」との差（=改定）として扱う
    prev_saved = float(state.get("jobs_prev_nfp_10k", "nan")) if "jobs_prev_nfp_10k" in state else None
    pm_nfp = None if prev_saved is None else (nfp_change_10k - prev_saved)

    prev_saved_unr = float(state.get("jobs_prev_unrate", "nan")) if "jobs_prev_unrate" in state else None
    pm_unr = None if prev_saved_unr is None else (unr_prev - prev_saved_unr)

    prev_saved_ahe = float(state.get("jobs_prev_ahe_mom", "nan")) if "jobs_prev_ahe_mom" in state else None
    # ahe_mom の「前回」は“前月のahe_mom”を保存しておく運用に
    pm_ahe = None if prev_saved_ahe is None else (None)  # 必要なら同様に実装

    text = "\n".join([
        f"🇺🇸雇用統計（{mm}）",
        "🟢非農業部門雇用者数",
        f"結果：{nfp_change_10k:.1f}万人",
        f"予想：{dash_if_none(fc_nfp, '{:.1f}')}万人",
        f"前回：{dash_if_none(prev_saved, '{:.1f}')}万人±{dash_if_none(pm_nfp, '{:+.1f}')}万人",
        "",
        "🟢失業率",
        f"結果：{unr:.1f}％",
        f"予想：{dash_if_none(fc_unr, '{:.1f}')}％",
        f"前回：{unr_prev:.1f}％±{dash_if_none(pm_unr, '{:+.1f}')}％",
        "",
        "🟢平均時給（前月比）",
        f"結果：{ahe_mom:.2f}％",
        f"予想：{dash_if_none(fc_ahe, '{:.2f}')}％",
        "前回：—±—",
    ])

    # 次回の±用に保存（最低限）
    state["jobs_prev_nfp_10k"] = nfp_change_10k
    state["jobs_prev_unrate"] = unr_prev
    # state["jobs_prev_ahe_mom"] = （前月のahe_momを別途計算して保存する設計にすると綺麗）
    return text

def build_cpi_post(state, forecasts=None):
    forecasts = forecasts or {}
    (d_cpi, cpi), (d_cpi_prev, cpi_prev) = latest_two_valid(fred_obs("CPIAUCSL"))   # :contentReference[oaicite:11]{index=11}
    (d_core, core), (d_core_prev, core_prev) = latest_two_valid(fred_obs("CPILFESL"))  # :contentReference[oaicite:12]{index=12}

    cpi_mom = pct(cpi, cpi_prev)
    core_mom = pct(core, core_prev)

    # YoY は 13点くらい取って12か月前を拾うのが安全。ここは簡略化。
    cpi_hist = fred_obs("CPIAUCSL", limit=15)
    cpi_vals = [(o["date"], float(o["value"])) for o in cpi_hist if o["value"] not in (None,"",".")]
    (d0, v0) = cpi_vals[0]
    (_, v12) = cpi_vals[12]
    cpi_yoy = pct(v0, v12)

    mm = month_jp(d_cpi)

    fc_cpi_mom = forecasts.get("cpi_mom")
    fc_cpi_yoy = forecasts.get("cpi_yoy")
    fc_core_mom = forecasts.get("core_cpi_mom")

    text = "\n".join([
        f"🇺🇸消費者物価指数（CPI）（{mm}）",
        "🟢CPI（前月比）",
        f"結果：{cpi_mom:.2f}％",
        f"予想：{dash_if_none(fc_cpi_mom, '{:.2f}')}％",
        "前回：—±—",
        "",
        "🟢CPI（前年比）",
        f"結果：{cpi_yoy:.2f}％",
        f"予想：{dash_if_none(fc_cpi_yoy, '{:.2f}')}％",
        "前回：—±—",
        "",
        "🟢コアCPI（前月比）",
        f"結果：{core_mom:.2f}％",
        f"予想：{dash_if_none(fc_core_mom, '{:.2f}')}％",
        "前回：—±—",
    ])
    return text

def post_to_x(text: str):
    # POST /2/tweets :contentReference[oaicite:13]{index=13}
    auth = OAuth1(
        os.environ["X_CONSUMER_KEY"],
        os.environ["X_CONSUMER_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    r = requests.post("https://api.x.com/2/tweets", json={"text": text}, auth=auth, timeout=30)
    r.raise_for_status()
    return r.json()
