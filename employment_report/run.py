import os
from datetime import datetime, timezone
from employment_report.util import retry
from employment_report.minkabu_forecast import fetch_minkabu_forecast
from employment_report.bls_actuals import get_actuals
from employment_report.compose_text import compose
from employment_report.x_post import post_to_x

def _need_values(actual: dict) -> bool:
    # 発表直後に null になりがちなものを最低限チェック
    # どれか取れてなければ再試行
    keys = ["nfp_man_actual", "ur_actual", "ahe_mom_actual", "ahe_yoy_actual"]
    return all(actual.get(k) is not None for k in keys)

def main():
    fired_at = datetime.now(timezone.utc).isoformat()
    print(f"[employment] start at {fired_at}Z")

    # 1) Forecast from Minkabu (retry)
    fc = retry(fetch_minkabu_forecast, tries=4, sleep_sec=3.0, name="minkabu_forecast")
    ym = fc["ym"]
    month_label = fc["monthLabel"]
    forecast = fc["forecast"]

    print(f"[employment] ym={ym} month={month_label} forecast={forecast} debug={fc.get('debug')}")

    # 2) Actual/Previous from BLS (release直後の反映遅延があるので retry)
    def _fetch_actual():
        a = get_actuals(ym)
        if not _need_values(a):
            raise RuntimeError(f"BLS returned incomplete values: {a}")
        return a

    actual = retry(_fetch_actual, tries=8, sleep_sec=6.0, name="bls_actuals")  # 最大 ~42秒待つ
    print(f"[employment] actual={actual}")

    # 3) Compose tweet
    text = compose(month_label, forecast, actual)
    print("----- TWEET -----")
    print(text)
    print("-----------------")

    # 4) Post to X
    res = retry(lambda: post_to_x(text), tries=3, sleep_sec=4.0, name="x_post")
    print(f"[employment] posted: {res}")

if __name__ == "__main__":
    main()
