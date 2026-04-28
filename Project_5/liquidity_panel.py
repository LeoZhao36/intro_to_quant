"""
Project 5 Stage 2: trailing 20-day liquidity panel.

For each of the 52 monthly rebalance dates R, computes the mean of `amount`
(成交额) over the 20 trading days ending at R inclusive, for every stock in
the candidate set on R.

Architecture: pulls cross-sectional `pro.daily()` once per trading day, deduped
across overlapping rebalance windows. Same per-cross-section pattern as
Stage 1.

Window convention: [R-19, R] inclusive. The decision for a rebalance dated R
is committed at end-of-day on R, so R's own amount is observable and used.

Output: data/liquidity_panel.csv with columns
    rebalance_date, ts_code, mean_amount_wan, n_trading_days_observed,
    passes_3000_floor

Stage 2 produces diagnostics. Stage 3 owns the inclusion decision, which is
why the floor flag is a column rather than a filter here.
"""

import sys
import time
from pathlib import Path

import pandas as pd

from tushare_setup import pro

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


# ==========================================================
# Configuration
# ==========================================================

DATA_DIR = Path("data")
CANDIDATES_DIR = DATA_DIR / "candidates"
DAILY_PANELS_DIR = DATA_DIR / "daily_panels"
TRADING_CALENDAR_CACHE = DATA_DIR / "trading_calendar.csv"
REBALANCE_DATES_CSV = DATA_DIR / "rebalance_dates.csv"
LIQUIDITY_PANEL_OUT = DATA_DIR / "liquidity_panel.csv"
DIAGNOSTIC_PLOT_OUT = DATA_DIR / "liquidity_panel_diagnostic.png"

DAILY_PANELS_DIR.mkdir(exist_ok=True)

# Calendar range covers (earliest rebalance - 19 trading days) back through
# (latest rebalance). Buffer on both ends in case rebalance dates shift.
CALENDAR_START = "20211201"
CALENDAR_END = "20260430"

WINDOW_DAYS = 20
LIQUIDITY_FLOOR_WAN = 3000  # 3000万 RMB/day, calibrated in Session 1

# Pacing between API calls. Tushare student tier permits roughly 500/min on
# `daily`. 0.15s leaves headroom and keeps Stage 2 under 5 min wall time.
API_SLEEP_SEC = 0.15


# ==========================================================
# Trading calendar
# ==========================================================

def get_trading_calendar():
    """
    Return a sorted ascending list of YYYY-MM-DD trading dates covering the
    panel range. Cached on first call.
    """
    if TRADING_CALENDAR_CACHE.exists():
        return pd.read_csv(TRADING_CALENDAR_CACHE)["date"].tolist()

    cal = pro.trade_cal(
        exchange="SSE",
        start_date=CALENDAR_START,
        end_date=CALENDAR_END,
        is_open="1",
    )
    dates = sorted(
        f"{s[:4]}-{s[4:6]}-{s[6:]}" for s in cal["cal_date"].tolist()
    )
    pd.DataFrame({"date": dates}).to_csv(TRADING_CALENDAR_CACHE, index=False)
    print(f"  cached {len(dates)} trading days to {TRADING_CALENDAR_CACHE}")
    return dates


# ==========================================================
# Pass 1: build the union of trading days needed across all windows
# ==========================================================

def build_required_trading_days(rebalance_dates, calendar):
    """
    For each rebalance date R, find the 20 trading days [R-19, R] inclusive.
    Return the union as a sorted list. Assumes every R is itself a trading
    day (enforced by Stage 1's build_rebalance_dates).
    """
    cal_index = {d: i for i, d in enumerate(calendar)}
    needed = set()

    for R in rebalance_dates:
        if R not in cal_index:
            raise ValueError(
                f"Rebalance date {R} is not in trading calendar. "
                f"Calendar may need extending or rebalance dates regenerated."
            )
        end_idx = cal_index[R]
        start_idx = end_idx - (WINDOW_DAYS - 1)
        if start_idx < 0:
            raise ValueError(
                f"Rebalance date {R} has only {end_idx + 1} prior trading "
                f"days in calendar; need {WINDOW_DAYS}. Extend CALENDAR_START."
            )
        for d in calendar[start_idx:end_idx + 1]:
            needed.add(d)

    return sorted(needed)


# ==========================================================
# Pass 2: pull and cache per-trading-day amount panels
# ==========================================================

def _yyyymmdd(s):
    return s.replace("-", "")


def pull_daily_panels(trading_days):
    """
    For each trading day, ensure data/daily_panels/daily_<date>.csv exists.
    On the first uncached pull, print magnitude diagnostics so a unit
    mismatch surfaces immediately rather than silently corrupting means.
    """
    n_total = len(trading_days)
    n_cache_hits = 0
    n_pulled = 0
    sanity_check_done = False

    for i, d in enumerate(trading_days, 1):
        path = DAILY_PANELS_DIR / f"daily_{d}.csv"
        if path.exists():
            n_cache_hits += 1
            continue

        df = _retry_on_network_error(
            lambda: pro.daily(
                ts_code="",
                trade_date=_yyyymmdd(d),
                fields="ts_code,trade_date,amount",
            ),
            label=f"daily {d}",
        )
        time.sleep(API_SLEEP_SEC)
        
        if len(df) == 0:
            # Empty result on a calendar trading day is anomalous but should
            # not abort the whole run. Write an empty cache so Pass 3 can
            # load it; n_trading_days_observed will reflect the gap.
            print(f"  [WARN] {d}: empty result from Tushare; writing empty cache")
            pd.DataFrame(columns=["ts_code", "trade_date", "amount"]).to_csv(
                path, index=False
            )
            n_pulled += 1
            continue

        df.to_csv(path, index=False)
        n_pulled += 1

        if not sanity_check_done:
            print(f"\n  [sanity check] amount magnitude on {d} "
                  f"({len(df)} rows):")
            print(f"    min:    {df['amount'].min():>14,.1f}")
            print(f"    median: {df['amount'].median():>14,.1f}")
            print(f"    max:    {df['amount'].max():>14,.1f}")
            print(f"  Tushare returns 千元. A stock turning over 100万 RMB")
            print(f"  shows as ~1,000. If median is ~1,000,000 the unit is")
            print(f"  wrong and the /10 conversion downstream will mislead.\n")
            sanity_check_done = True

        if i % 50 == 0:
            print(f"  [{i}/{n_total}] pulled this run: {n_pulled}, "
                  f"cache hits: {n_cache_hits}")

    print(f"\n  daily panels: {n_cache_hits} cached, {n_pulled} pulled, "
          f"{n_total} total")


# ==========================================================
# Pass 3: aggregate per rebalance date
# ==========================================================

def build_liquidity_panel(rebalance_dates, calendar):
    """
    For each rebalance date R, load the 20 trailing daily panels, filter to
    R's candidate ts_codes, compute trailing-mean amount per stock and a
    diagnostic floor flag. Returns a single DataFrame; does not write.
    """
    cal_index = {d: i for i, d in enumerate(calendar)}
    all_rows = []

    for i, R in enumerate(rebalance_dates, 1):
        candidates = pd.read_csv(
            CANDIDATES_DIR / f"candidates_{R}.csv",
            dtype={"ts_code": str},
        )
        candidate_codes = set(candidates["ts_code"])

        end_idx = cal_index[R]
        start_idx = end_idx - (WINDOW_DAYS - 1)
        window_days = calendar[start_idx:end_idx + 1]

        # Load the 20 daily panels, filter to candidates, concat
        frames = []
        for d in window_days:
            day_df = pd.read_csv(
                DAILY_PANELS_DIR / f"daily_{d}.csv",
                dtype={"ts_code": str},
            )
            day_df = day_df[day_df["ts_code"].isin(candidate_codes)]
            frames.append(day_df)
        window_df = pd.concat(frames, ignore_index=True)

        # Aggregate: mean and observation count per stock.
        # `count` on a non-null `amount` column gives the number of trading
        # days the stock actually traded in the window. Suspended days are
        # absent because Tushare's `daily` omits non-trading rows.
        agg = (
            window_df.groupby("ts_code")["amount"]
            .agg(mean_amount_qian="mean", n_trading_days_observed="count")
            .reset_index()
        )

        # Tushare amount unit is 千元. Target unit is 万元. 1万 = 10千.
        agg["mean_amount_wan"] = agg["mean_amount_qian"] / 10
        agg = agg.drop(columns=["mean_amount_qian"])
        agg["passes_3000_floor"] = agg["mean_amount_wan"] >= LIQUIDITY_FLOOR_WAN
        agg["rebalance_date"] = R

        agg = agg[[
            "rebalance_date", "ts_code", "mean_amount_wan",
            "n_trading_days_observed", "passes_3000_floor",
        ]]
        all_rows.append(agg)

        n_pass = int(agg["passes_3000_floor"].sum())
        n_full = int((agg["n_trading_days_observed"] == WINDOW_DAYS).sum())
        print(f"[{i:>2}/{len(rebalance_dates)}] {R}: {len(agg):>4} stocks, "
              f"{n_full:>4} full-window, {n_pass:>4} pass {LIQUIDITY_FLOOR_WAN}万")

    panel = pd.concat(all_rows, ignore_index=True)
    return panel


# ==========================================================
# Diagnostic plot
# ==========================================================

def plot_diagnostic(panel, output_path=DIAGNOSTIC_PLOT_OUT):
    """
    Two-panel diagnostic for liquidity floor calibration:
      Top:    pass rate over time, to see whether the 3000万 floor's bite
              changes across regimes (stimulus rallies vs. quiet periods).
      Bottom: pooled distribution of mean_amount_wan with the floor marked,
              to see where the floor sits empirically.
    """
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 8))

    # Top: pass rate over time
    pass_rate = (
        panel.groupby("rebalance_date")["passes_3000_floor"].mean() * 100
    )
    axes[0].plot(
        pd.to_datetime(pass_rate.index),
        pass_rate.values,
        marker="o",
        markersize=3,
        linewidth=1,
    )
    axes[0].set_ylabel(f"% of candidates passing {LIQUIDITY_FLOOR_WAN}万 floor")
    axes[0].set_xlabel("Rebalance date")
    axes[0].set_title(
        f"Liquidity floor pass rate over time "
        f"(floor = {LIQUIDITY_FLOOR_WAN}万 RMB/day, trailing 20-day mean)"
    )
    axes[0].grid(True, alpha=0.3)
    axes[0].set_ylim(0, 100)

    # Bottom: pooled distribution, log x-scale
    axes[1].hist(
        panel["mean_amount_wan"].clip(lower=1),  # clip for log scale
        bins=100,
        log=True,
        edgecolor="none",
    )
    axes[1].axvline(
        LIQUIDITY_FLOOR_WAN,
        color="red",
        linestyle="--",
        label=f"{LIQUIDITY_FLOOR_WAN}万 floor",
    )
    axes[1].set_xlabel("Mean trailing-20-day amount (万 RMB)")
    axes[1].set_ylabel("Count (log scale)")
    axes[1].set_xscale("log")
    axes[1].set_title("Distribution of mean amount, all (date, stock) pooled")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    print(f"  plot saved to {output_path}")


# ==========================================================
# Smoke test: single rebalance date
# ==========================================================

def smoke_test(R="2024-12-31"):
    """
    Run the full Stage 2 pipeline for a single rebalance date. Use this to
    verify magnitudes and flow before committing to the full 52-date run.
    """
    print("=" * 60)
    print(f"SMOKE TEST - rebalance date {R}")
    print("=" * 60)

    calendar = get_trading_calendar()
    if R not in calendar:
        print(f"  {R} is not a trading day in the calendar. Aborting.")
        return

    cal_index = {d: i for i, d in enumerate(calendar)}
    end_idx = cal_index[R]
    start_idx = end_idx - (WINDOW_DAYS - 1)
    window_days = calendar[start_idx:end_idx + 1]
    print(f"  window: {window_days[0]} .. {window_days[-1]} "
          f"({len(window_days)} trading days)")

    pull_daily_panels(window_days)
    panel = build_liquidity_panel([R], calendar)

    print(f"\n  liquidity panel for {R}:")
    print(f"    rows: {len(panel)}")
    print(f"    mean_amount_wan summary:")
    print(f"      min:    {panel['mean_amount_wan'].min():>12,.1f}")
    print(f"      median: {panel['mean_amount_wan'].median():>12,.1f}")
    print(f"      max:    {panel['mean_amount_wan'].max():>12,.1f}")
    print(f"    n_trading_days_observed:")
    print(f"      mode: {int(panel['n_trading_days_observed'].mode().iloc[0])}")
    print(f"      <{WINDOW_DAYS}: "
          f"{int((panel['n_trading_days_observed'] < WINDOW_DAYS).sum())} stocks")
    print(f"    passing {LIQUIDITY_FLOOR_WAN}万 floor: "
          f"{int(panel['passes_3000_floor'].sum())} "
          f"({100 * panel['passes_3000_floor'].mean():.1f}%)")
    

# ==========================================================
# Network resilience: retry transient Tushare failures
# ==========================================================

def _retry_on_network_error(fn, max_attempts=4, base_delay=2.0, label=""):
    """
    Call fn() with exponential-backoff retry on transient network errors.
    Tushare runs over plain HTTP and is prone to read timeouts; a ~1000-call
    run has near-certainty of at least one transient failure even when the
    per-call success rate is 99%+. Backoff schedule: 2s, 4s, 8s between
    attempts, then re-raise.
    """
    import requests.exceptions as rex
    transient = (rex.ReadTimeout, rex.ConnectTimeout, rex.ConnectionError)
    for attempt in range(max_attempts):
        try:
            return fn()
        except transient as e:
            if attempt == max_attempts - 1:
                print(f"  [retry] {label}: {type(e).__name__} after "
                      f"{max_attempts} attempts; raising")
                raise
            delay = base_delay * (2 ** attempt)
            print(f"  [retry] {label}: {type(e).__name__}, sleeping "
                  f"{delay:.1f}s (attempt {attempt + 1}/{max_attempts})")
            time.sleep(delay)


# ==========================================================
# Full driver
# ==========================================================

def run_full_stage2():
    t_start = time.time()

    print("Stage 2: trailing 20-day liquidity panel")
    print("=" * 60)

    rebalance_dates = pd.read_csv(REBALANCE_DATES_CSV)["date"].tolist()
    print(f"  rebalance dates: {len(rebalance_dates)} "
          f"(first={rebalance_dates[0]}, last={rebalance_dates[-1]})")

    calendar = get_trading_calendar()
    print(f"  trading calendar: {len(calendar)} days "
          f"(first={calendar[0]}, last={calendar[-1]})")

    # Pass 1
    required_days = build_required_trading_days(rebalance_dates, calendar)
    naive = len(rebalance_dates) * WINDOW_DAYS
    print(f"\n  required trading days: {len(required_days)} "
          f"(naive {naive}, savings from window overlap: {naive - len(required_days)})")

    # Pass 2
    print(f"\nPass 2: pulling daily panels...")
    pull_daily_panels(required_days)

    # Pass 3
    print(f"\nPass 3: building liquidity panel...")
    panel = build_liquidity_panel(rebalance_dates, calendar)
    panel.to_csv(LIQUIDITY_PANEL_OUT, index=False)
    print(f"\n  wrote {len(panel)} rows to {LIQUIDITY_PANEL_OUT}")

    # Diagnostic plot
    print(f"\nDiagnostic plot...")
    plot_diagnostic(panel)

    # Summary
    total_min = (time.time() - t_start) / 60
    pass_pct = 100 * panel["passes_3000_floor"].mean()
    full_pct = 100 * (panel["n_trading_days_observed"] == WINDOW_DAYS).mean()
    print(f"\n{'=' * 60}")
    print(f"Stage 2 complete in {total_min:.1f} min")
    print(f"  (date, stock) rows:           {len(panel):>7,}")
    print(f"  passing {LIQUIDITY_FLOOR_WAN}万 floor:           "
          f"{int(panel['passes_3000_floor'].sum()):>7,} ({pass_pct:.1f}%)")
    print(f"  full {WINDOW_DAYS}-day observation:    "
          f"{int((panel['n_trading_days_observed'] == WINDOW_DAYS).sum()):>7,} "
          f"({full_pct:.1f}%)")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "full":
        run_full_stage2()
    elif mode == "smoke":
        smoke_test()
    else:
        print(f"Unknown mode: {mode}. Use 'smoke' or 'full'.")
        sys.exit(1)