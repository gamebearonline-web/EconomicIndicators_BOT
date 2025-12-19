import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from requests_oauthlib import OAuth1

FMP_API_KEY = os.environ["FMP_API_KEY"]
STATE_PATH = "fmp_cpi/state.json"

FMP_URL = "https://financialmodelingprep.com/api/v3/economic_calendar"
COUNTRY = "US"

RETRY_SECONDS = 300      # 最大5分
RETRY_INTERVAL = 30      # 30秒おき

# --------- X ----------
def post_to_x(text: str):
    auth = OAuth1(
        os.environ["X_CONSUMER_KEY"],
        os.environ["X_CONSUMER_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    r = requests.post("https://api.x.com/2/tweets", json={"text": text}, auth=auth, timeout=30)
    r.raise_for_status()

# --------- state ----------
def load_state():
    if not os.path.exists(STATE_PATH):
        return {"posted_keys": []}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def already_posted(state, key: str) -> bool:
    return key in state["posted_keys"]

def mark_posted(state, key: str):
    state["posted_keys"].append(key)

# --------- helpers ----------
def parse_dt(dt_str: str) -> datetime:
    """
    FMP economic_calendar の date は 'YYYY-MM-DD' か 'YYYY-MM-DD HH:MM:SS' のことがある。
    タイムゾーンは明示されない場合があるので、ここでは UTC 扱いに統一（GAS側で発表直後に叩く前提）。
    """
    dt_str = dt_str.strip()
    if len(dt_str) == 10:
        # date only
        return datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    # date time
    try:
        return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        # 予備：ISOっぽい形式
        return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)

def format_pct(v):
    return "—" if v is None or v == "" else f"{v}%"

def month_label_for_release(release_dt: datetime) -> str:
    """
    CPIは通常「翌月に前月分が発表」なので、発表月-1 を対象月として表示。
    例：12月発表 → 11月分
    """
    y, m = release_dt.year, release_dt.month
    if m == 1:
        m = 12
    else:
        m -= 1
    return f"{m}月"

# --------- FMP fetch ----------
def fetch_fmp(from_date: datetime, to_date: datetime):
    params = {
        "from": from_date.strftime("%Y-%m-%d"),
        "to": to_date.strftime("%Y-%m-%d"),
        "apikey": FMP_API_KEY,
    }
    r = requests.get(FMP_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def is_us_cpi_event(e) -> bool:
    if e.get("country") != COUNTRY:
        return False
    name = (e.get("event") or "").lower()
    # CPI関連を広めに拾う
    if "cpi" in name or "consumer price" in name:
        return True
    return False

def classify_cpi(e):
    """
    返り値: (is_core, is_mom, is_yoy)
    """
    name = (e.get("event") or "").lower()
    is_core = "core" in name
    # 表記揺れ吸収
    is_mom = ("mom" in name) or ("m/m" in name) or ("month over month" in name) or ("m-o-m" in name)
    is_yoy = ("yoy" in name) or ("y/y" in name) or ("year over year" in name) or ("y-o-y" in name)
    return is_core, is_mom, is_yoy

def build_block(title: str, actual, estimate, previous):
    return "\n".join([
        f"🟢{title}",
        f"結果：{format_pct(actual)}",
        f"予想：{format_pct(estimate)}",
        f"前回：{format_pct(previous)}",
    ])

def compose_post_same_day(month: str, mom_cpi, yoy_cpi, mom_core, yoy_core) -> str:
    """
    同日発表→1投稿。並びは「わかりやすさ優先」で
    MoM（CPI/コア）→YoY（CPI/コア）。
    ※あなたが提示した並び（CPI MoM + Core YoY など）に合わせたい場合は、ここで順番を入れ替えればOK。
    """
    lines = [f"🇺🇸消費者物価指数（CPI）（{month}）"]

    lines.append(build_block("CPI（前月比）", mom_cpi["actual"], mom_cpi["estimate"], mom_cpi["previous"]))
    lines.append(build_block("コアCPI（前月比）", mom_core["actual"], mom_core["estimate"], mom_core["previous"]))
    lines.append("")  # 空行

    lines.append(build_block("CPI（前年比）", yoy_cpi["actual"], yoy_cpi["estimate"], yoy_cpi["previous"]))
    lines.append(build_block("コアCPI（前年比）", yoy_core["actual"], yoy_core["estimate"], yoy_core["previous"]))

    return "\n".join(lines).strip()

def compose_post_split(month: str, kind: str, cpi_item, core_item) -> str:
    """
    別日発表→2投稿（MoM / YoY で分割）
    """
    if kind == "MoM":
        header = f"🇺🇸消費者物価指数（CPI）（{month}）"
        return "\n".join([
            header,
            build_block("CPI（前月比）", cpi_item["actual"], cpi_item["estimate"], cpi_item["previous"]),
            build_block("コアCPI（前月比）", core_item["actual"], core_item["estimate"], core_item["previous"]),
        ]).strip()

    header = f"🇺🇸消費者物価指数（CPI）（{month}）"
    return "\n".join([
        header,
        build_block("CPI（前年比）", cpi_item["actual"], cpi_item["estimate"], cpi_item["previous"]),
        build_block("コアCPI（前年比）", core_item["actual"], core_item["estimate"], core_item["previous"]),
    ]).strip()

def main():
    state = load_state()
    now = datetime.now(timezone.utc)

    # 発表直後にGASから叩く前提だが、念のため±2日で拾う
    base_from = now - timedelta(days=2)
    base_to = now + timedelta(days=2)

    # リトライ込みで「actualが埋まるまで待つ」ため、fetchを関数化
    def fetch_current():
        data = fetch_fmp(base_from, base_to)
        return [e for e in data if is_us_cpi_event(e)]

    events = fetch_current()
    if not events:
        print("No CPI events found in window.")
        return

    # 発表時刻（date）でグループ化
    groups = {}
    for e in events:
        dt = parse_dt(e["date"])
        key = dt.isoformat()
        groups.setdefault(key, []).append(e)

    # 発表済み（now >= release_dt）のグループだけ処理
    for release_key, items in sorted(groups.items()):
        release_dt = datetime.fromisoformat(release_key)
        if now < release_dt:
            continue

        # この発表時刻グループの中から、CPI/コアの MoM/YoY を拾う
        def extract(items_list):
            out = {"cpi_mom": None, "cpi_yoy": None, "core_mom": None, "core_yoy": None}
            for it in items_list:
                is_core, is_mom, is_yoy = classify_cpi(it)
                payload = {
                    "actual": it.get("actual"),
                    "estimate": it.get("estimate"),
                    "previous": it.get("previous"),
                    "event": it.get("event"),
                }
                if is_core and is_mom:
                    out["core_mom"] = payload
                elif is_core and is_yoy:
                    out["core_yoy"] = payload
                elif (not is_core) and is_mom:
                    out["cpi_mom"] = payload
                elif (not is_core) and is_yoy:
                    out["cpi_yoy"] = payload
            return out

        extracted = extract(items)

        # 「actual が未反映」なら最大5分リトライして更新を待つ
        deadline = datetime.now(timezone.utc) + timedelta(seconds=RETRY_SECONDS)
        while datetime.now(timezone.utc) < deadline:
            # 4つのうち、存在するものは actual が入っているか？
            need_wait = False
            for k, v in extracted.items():
                if v is not None and v.get("actual") is None:
                    need_wait = True
            if not need_wait:
                break

            time.sleep(RETRY_INTERVAL)
            # 再取得して該当release_dtグループを更新
            refreshed = fetch_current()
            refreshed_groups = {}
            for e in refreshed:
                dt = parse_dt(e["date"])
                refreshed_groups.setdefault(dt.isoformat(), []).append(e)
            if release_key in refreshed_groups:
                extracted = extract(refreshed_groups[release_key])

        # 投稿キー（同じ発表時刻で二重投稿しない）
        # 同日1投稿の場合 keyは "CPI_ALL_<release>"
        # 分割の場合 keyは "CPI_MoM_<release>" / "CPI_YoY_<release>"
        month = month_label_for_release(release_dt)

        has_mom_pair = extracted["cpi_mom"] and extracted["core_mom"]
        has_yoy_pair = extracted["cpi_yoy"] and extracted["core_yoy"]

        # 同日発表（同一release_key内に MoMとYoYの両方が揃う）→1投稿
        if has_mom_pair and has_yoy_pair:
            post_key = f"CPI_ALL_{release_key}"
            if already_posted(state, post_key):
                continue

            # actualがどれか欠けている場合は安全のため投稿しない
            if (extracted["cpi_mom"]["actual"] is None or extracted["core_mom"]["actual"] is None or
                extracted["cpi_yoy"]["actual"] is None or extracted["core_yoy"]["actual"] is None):
                print("Actual not ready for ALL; skip.")
                continue

            text = compose_post_same_day(
                month,
                extracted["cpi_mom"], extracted["cpi_yoy"],
                extracted["core_mom"], extracted["core_yoy"]
            )
            post_to_x(text)
            mark_posted(state, post_key)
            save_state(state)
            print("Posted CPI ALL.")
            continue

        # 別日（or 同一release_key内に片方しか無い）→ MoM / YoY でそれぞれ投稿
        if has_mom_pair:
            post_key = f"CPI_MoM_{release_key}"
            if not already_posted(state, post_key):
                if extracted["cpi_mom"]["actual"] is not None and extracted["core_mom"]["actual"] is not None:
                    text = compose_post_split(month, "MoM", extracted["cpi_mom"], extracted["core_mom"])
                    post_to_x(text)
                    mark_posted(state, post_key)
                    save_state(state)
                    print("Posted CPI MoM.")

        if has_yoy_pair:
            post_key = f"CPI_YoY_{release_key}"
            if not already_posted(state, post_key):
                if extracted["cpi_yoy"]["actual"] is not None and extracted["core_yoy"]["actual"] is not None:
                    text = compose_post_split(month, "YoY", extracted["cpi_yoy"], extracted["core_yoy"])
                    post_to_x(text)
                    mark_posted(state, post_key)
                    save_state(state)
                    print("Posted CPI YoY.")

if __name__ == "__main__":
    main()
