import os
from datetime import datetime, timezone
from employment_report.util import retry
from employment_report.minkabu_forecast import fetch_minkabu_forecast
from employment_report.bls_actuals import get_actuals
from employment_report.compose_text import compose
from employment_report.x_post import post_to_x

def _need_values(actual: dict) -> bool:
    keys = ["nfp_man_actual", "ur_actual", "ahe_mom_actual", "ahe_yoy_actual"]
    return all(actual.get(k) is not None for k in keys)

def main():
    fired_at = datetime.now(timezone.utc).isoformat()
    print(f"[employment] start at {fired_at}Z")

    # 1) Forecast from JSON (no web)
    fcwrap = fetch_minkabu_forecast()
    ym = fcwrap["ym"]
    month_label = fcwrap["monthLabel"]
    forecast = fcwrap["forecast"]

    print(f"[employment] forecast ym={ym} month={month_label} forecast={forecast}")

    # 2) Actual from BLS (release直後の反映遅延対策で retry)
    def _fetch_actual():
        a = get_actuals(ym)
        if not _need_values(a):
            raise RuntimeError(f"BLS returned incomplete values: {a}")
        return a

    actual = retry(_fetch_actual, tries=8, sleep_sec=6.0, name="bls_actuals")  # 最大 ~42秒
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
