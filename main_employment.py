from employment_report.minkabu_forecast import fetch_forecast
from employment_report.bls_actuals import get_actuals
from employment_report.compose_text import compose
from employment_report.post_to_x import post

def main():
    f = fetch_forecast()
    year = "2025"   # GASから渡す or 当月自動化してもOK
    a = get_actuals(year, f["month"])
    text = compose(f["month"], f, a)
    print(text)
    post(text)

if __name__ == "__main__":
    main()
