# Finnhub CPI Bot

- Data source: Finnhub Economic Calendar (Free)
- Trigger: GitHub Actions (every 5 minutes)
- Post timing: within 5 minutes after release
- Handles:
  - CPI MoM / YoY
  - Core CPI MoM / YoY
  - Same-day release → single post
  - Separate-day release → split posts
