def _pct(x):
    return "—" if x is None else f"{x:.1f}%"

def _man(x):
    return "—" if x is None else f"{x:.1f}万人"

def compose(month_label: str, forecast: dict, actual: dict) -> str:
    return (
f"🇺🇸雇用統計（{month_label}）\n"
f"🟢平均時給（前月比）\n"
f"結果：{_pct(actual.get('ahe_mom_actual'))}\n"
f"予想：{_pct(forecast.get('ahe_mom'))}\n"
f"前回：{_pct(actual.get('ahe_mom_prev'))}\n\n"
f"🟢平均時給（前年比）\n"
f"結果：{_pct(actual.get('ahe_yoy_actual'))}\n"
f"予想：{_pct(forecast.get('ahe_yoy'))}\n"
f"前回：{_pct(actual.get('ahe_yoy_prev'))}\n\n"
f"🟢非農業部門雇用者数\n"
f"結果：{_man(actual.get('nfp_man_actual'))}\n"
f"予想：{_man(forecast.get('nfp_man'))}\n"
f"前回：{_man(actual.get('nfp_man_prev'))}\n\n"
f"🟢失業率\n"
f"結果：{_pct(actual.get('ur_actual'))}\n"
f"予想：{_pct(forecast.get('unemployment_rate'))}\n"
f"前回：{_pct(actual.get('ur_prev'))}"
    )
