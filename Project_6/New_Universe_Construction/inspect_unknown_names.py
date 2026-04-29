"""Diagnose the survivorship-bias warning from Stage 1 smoke."""
import pandas as pd
from pathlib import Path

PANEL_DIR = Path("data/daily_panel")
basic = pd.read_csv("data/stock_basic.csv", dtype={"ts_code": str})
known = set(basic["ts_code"])

# Pattern from Stage 1
import re
ASHARE = re.compile(r"^(60|68)\d{4}\.SH$|^(00|30)\d{4}\.SZ$")

dates = ["2019-01-02", "2019-01-09", "2019-01-16", "2019-01-23", "2019-01-30"]

all_unknown = []
for d in dates:
    df = pd.read_parquet(PANEL_DIR / f"daily_{d}.parquet")
    df = df[df["ts_code"].str.match(ASHARE)]
    unknown = df[~df["ts_code"].isin(known)]
    print(f"{d}: {len(unknown)} unknown of {len(df)} A-share rows")
    all_unknown.append(set(unknown["ts_code"]))

union = set().union(*all_unknown)
intersection = set.intersection(*all_unknown)
print(f"\nUnion across 5 dates:        {len(union)} unique ts_codes")
print(f"Intersection (all 5 dates):  {len(intersection)} ts_codes")
print(f"\nFirst 20 from union:")
for code in sorted(union)[:20]:
    print(f"  {code}")