import os
from datetime import datetime
from employment_report.x_post import post_to_x

def main():
    msg = os.getenv("EMP_TEST_MESSAGE", "").strip()
    if not msg:
        # デフォルト文言（スパムっぽくならないよう短く）
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        msg = f"【BOTテスト】雇用統計ワークフロー疎通OK ({ts})"

    res = post_to_x(msg)
    print(res)

if __name__ == "__main__":
    main()
