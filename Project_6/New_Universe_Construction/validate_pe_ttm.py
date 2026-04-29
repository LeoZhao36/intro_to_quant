"""
validate_pe_ttm.py — EP point-in-time validation for daily_basic.

Tushare's daily_basic.pe_ttm is documented to use the trailing 4 quarters
of net profit as of the most recently disclosed earnings report. This
script verifies the actual behaviour around real earnings announcements.

Test logic
----------
For each test case (ts_code, fiscal period):
  1. Look up the actual ann_date from fina_indicator.
  2. Pull daily_basic.pe_ttm for ~10 trading days bracketing ann_date.
  3. Print the trajectory and check: pe_ttm should be flat before
     ann_date, flat after ann_date, with one step at or one trading
     day after ann_date.

Interpretations
---------------
  PASS (step on day AFTER ann_date)
    Point-in-time is clean. Use EP = 1 / pe_ttm directly.

  PASS-WITH-CAVEAT (step ON ann_date)
    One-day staleness. If announcement happens after market close, pe_ttm
    on that day's close already reflects new earnings. For monthly or
    weekly rebalancing this is negligible; documented and accepted.

  FAIL (no step, or step on a non-ann date)
    Tushare may be using a different alignment than expected. Need to
    construct EP manually from fina_indicator.eps and price.

Usage
-----
    python validate_pe_ttm.py
"""

import os
import sys

import pandas as pd

# tushare_client.py lives one directory above Project_6/, alongside .env.
_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

from tushare_setup import pro


# ==========================================================
# Test cases — three stocks across three different periods
# ==========================================================
# Pick large, well-covered names with reliable disclosure timing.
# We discover the ann_date programmatically; period is the only manual input.

TEST_CASES = [
    {"ts_code": "601318.SH", "name": "中国平安",  "period": "20231231"},
    {"ts_code": "600519.SH", "name": "贵州茅台",  "period": "20240331"},
    {"ts_code": "002594.SZ", "name": "比亚迪",     "period": "20240630"},
]

WINDOW_TRADING_DAYS = 5  # +/- around ann_date


def _yyyymmdd(s):
    return s.replace("-", "")


def get_announcement_date(ts_code, period):
    """Earliest ann_date for a (ts_code, end_date) pair from fina_indicator."""
    fi = pro.fina_indicator(
        ts_code=ts_code, period=period,
        fields="ts_code,end_date,ann_date,eps,roe"
    )
    if fi is None or len(fi) == 0:
        raise RuntimeError(f"No fina_indicator row for {ts_code} period {period}")
    fi = fi.sort_values("ann_date")  # earliest = original announcement
    return fi.iloc[0]["ann_date"], fi.iloc[0].get("eps")


def get_window_around(ts_code, ann_date_yyyymmdd, n_each_side):
    """
    Pull daily_basic.pe_ttm for ~n_each_side trading days each side of
    ann_date. We pull a calendar-day window slightly larger than needed
    and then keep the closest n trading days; simpler than fetching the
    trade calendar twice.
    """
    # Buffer of 12 calendar days each side to comfortably cover 5 trading
    # days even with weekends and a holiday.
    ann_dt = pd.Timestamp(
        f"{ann_date_yyyymmdd[:4]}-{ann_date_yyyymmdd[4:6]}-{ann_date_yyyymmdd[6:]}"
    )
    start = (ann_dt - pd.Timedelta(days=12)).strftime("%Y%m%d")
    end   = (ann_dt + pd.Timedelta(days=12)).strftime("%Y%m%d")

    db = pro.daily_basic(
        ts_code=ts_code, start_date=start, end_date=end,
        fields="ts_code,trade_date,close,pe,pe_ttm,pb"
    )
    if db is None or len(db) == 0:
        raise RuntimeError(f"No daily_basic data for {ts_code} in [{start}, {end}]")

    db = db.sort_values("trade_date").reset_index(drop=True)
    return db, ann_dt


def analyze_one_case(case):
    print(f"\n{'='*72}")
    print(f"  {case['name']} ({case['ts_code']}) — period {case['period']}")
    print(f"{'='*72}")

    ann_date, eps = get_announcement_date(case["ts_code"], case["period"])
    print(f"  fina_indicator ann_date:  {ann_date}   (EPS reported: {eps})")

    db, ann_dt = get_window_around(case["ts_code"], ann_date, WINDOW_TRADING_DAYS)

    # Tag pre/post-announcement and print trajectory
    db["trade_dt"] = pd.to_datetime(db["trade_date"])
    db["position"] = db["trade_dt"].apply(
        lambda d: "before" if d < ann_dt else ("on" if d == ann_dt else "after")
    )
    db["pe_ttm_diff"] = db["pe_ttm"].diff()

    print(f"\n  pe_ttm trajectory across the announcement:")
    print(f"  {'date':<12} {'position':>9} {'close':>9} "
          f"{'pe':>9} {'pe_ttm':>9} {'pb':>9} {'Δpe_ttm':>10}")
    print(f"  {'-'*12} {'-'*9} {'-'*9} {'-'*9} {'-'*9} {'-'*9} {'-'*10}")

    for _, r in db.iterrows():
        diff = (f"{r['pe_ttm_diff']:>+10.4f}"
                if pd.notna(r['pe_ttm_diff']) else f"{'(first)':>10}")
        marker = "  <-- ANN" if r["position"] == "on" else ""
        print(f"  {r['trade_date']:<12} {r['position']:>9} "
              f"{r['close']:>9.2f} {r['pe']:>9.2f} {r['pe_ttm']:>9.2f} "
              f"{r['pb']:>9.2f} {diff}{marker}")

    # Diagnostic: where is the largest jump?
    pre = db[db["position"] == "before"]["pe_ttm"].dropna()
    post = db[db["position"] == "after"]["pe_ttm"].dropna()
    on   = db[db["position"] == "on"]["pe_ttm"].dropna()

    if len(pre) == 0 or len(post) == 0:
        print(f"\n  Cannot evaluate (insufficient pre or post data)")
        return

    pre_max_diff  = pre.diff().abs().max()  if len(pre) > 1  else 0
    post_max_diff = post.diff().abs().max() if len(post) > 1 else 0

    last_pre = pre.iloc[-1]
    first_post = post.iloc[0]
    jump_to_post = abs(first_post - last_pre)

    print(f"\n  Stability check:")
    print(f"    max |Δ| within pre-announcement window:    {pre_max_diff:>8.4f}")
    print(f"    max |Δ| within post-announcement window:   {post_max_diff:>8.4f}")
    print(f"    |last_pre - first_post|:                   {jump_to_post:>8.4f}")
    if len(on) > 0:
        on_val = on.iloc[0]
        print(f"    pe_ttm on ann_date itself:                 {on_val:>8.4f}")
        print(f"    |last_pre - on|:                           {abs(on_val - last_pre):>8.4f}")
        print(f"    |on - first_post|:                         {abs(first_post - on_val):>8.4f}")

    if pre_max_diff < 0.05 and post_max_diff < 0.05 and jump_to_post > 0.5:
        verdict = "PASS — clean step at announcement, point-in-time correct"
    elif pre_max_diff > 0.5 or post_max_diff > 0.5:
        verdict = "INVESTIGATE — pe_ttm changes within a steady-state window"
    elif jump_to_post < 0.05:
        verdict = "FAIL — no detectable step at announcement"
    else:
        verdict = "MIXED — small jump; may need wider window or different period"

    print(f"\n  Verdict: {verdict}")


def main():
    print("EP point-in-time validation: daily_basic.pe_ttm vs known ann_dates\n")
    for case in TEST_CASES:
        try:
            analyze_one_case(case)
        except Exception as exc:
            print(f"\nERROR on {case['name']} ({case['ts_code']}): {exc}")

    print(f"\n{'='*72}")
    print("How to read the verdicts")
    print(f"{'='*72}")
    print("All three PASS  -> EP = 1 / pe_ttm is safe to use throughout the rebuild.")
    print("Mixed verdicts  -> probably one-day staleness on report-day-itself.")
    print("                   Acceptable for weekly/monthly rebalancing; documented.")
    print("Any FAIL/INVEST -> construct EP manually from fina_indicator + price.")
    print("                   Adds ~3,500 per-stock pulls but is unambiguous.")


if __name__ == "__main__":
    main()