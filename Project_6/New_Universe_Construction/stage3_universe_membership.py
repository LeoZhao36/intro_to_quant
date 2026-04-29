"""
stage3_universe_membership.py — Stage 3 rewrite for the rebuilt panel.

Builds the final point-in-time universe: bottom 1000 by 流通市值 of the
stocks that pass a hybrid liquidity floor on each weekly rebalance date.

Pipeline
--------
  Stage 1 candidate parquets   →  inner join on ts_code  →  bottom-1000 by mcap
  Stage 2 liquidity panel      →  apply hybrid floor:
                                    n_trading_days_observed >= 20
                                    AND mean_amount_wan in top X%
                                    AND mean_amount_wan >= Y万

Selected parameters
-------------------
  X = 75 (keep top 75%, drop bottom 25% by liquidity rank)
  Y = 3000 万 (absolute floor; ~bottom quartile of panel liquidity)
  N_MIN_DAYS = 20 (exclude stocks suspended for >2/3 of the 60-day window)
  UNIVERSE_TARGET_SIZE = 1000

API calls: zero. Pure data manipulation on Stage 1 and Stage 2 outputs.

Output
------
data/universe_membership_X75_Y3000.parquet     full membership panel
data/universe_membership_X75_Y3000_diagnostic.png   3-panel diagnostic plot

The membership panel has one row per (rebalance_date, ts_code) for every
candidate stock at each date, with these columns:

    rebalance_date, ts_code, in_universe, mean_amount_wan, n_trading_days_observed,
    circ_mv_yi, rank_by_mcap

This matches Project 5's universe_membership.csv schema, so downstream
stages (forward returns, factor pipelines) only need a parquet read swap.

Usage
-----
    python stage3_universe_membership.py smoke   # first 5 weekly dates
    python stage3_universe_membership.py full    # all 381 dates + diagnostic plot
    python stage3_universe_membership.py status  # inspect cached output
"""

import logging
import os
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend; safe under any environment
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

# Project's matplotlib Chinese font setup, if present
try:
    import Project_6.New_Universe_Construction.plot_setup as plot_setup  # noqa: F401
except ImportError:
    pass

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


# ==========================================================
# Configuration
# ==========================================================

DATA_DIR = Path("data")
CANDIDATES_DIR = DATA_DIR / "candidates_weekly_pit"
LIQUIDITY_PANEL_PATH = DATA_DIR / "liquidity_panel_60d.parquet"
REBALANCE_DATES_PATH = DATA_DIR / "weekly_rebalance_dates.csv"
ERROR_LOG = DATA_DIR / "errors_stage3_universe.log"

DATA_DIR.mkdir(exist_ok=True)

# Chosen tuple: 75% percentile gate, 3000万 absolute floor.
X_PERCENTILE = 75
Y_FLOOR_WAN = 3000

# Minimum trading-day coverage in the 60-day window. Below this, a stock
# is considered structurally untradable on the rebalance date even if its
# observed-day mean amount is high.
N_MIN_DAYS = 20

# Universe size: smallest-cap N from the liquidity-survivor pool.
UNIVERSE_TARGET_SIZE = 1000

# Output paths embed the parameter tuple for reproducibility and to
# support running multiple tuples side-by-side later if needed.
OUTPUT_PARQUET = DATA_DIR / f"universe_membership_X{X_PERCENTILE}_Y{Y_FLOOR_WAN}.parquet"
OUTPUT_PLOT = DATA_DIR / f"universe_membership_X{X_PERCENTILE}_Y{Y_FLOOR_WAN}_diagnostic.png"

COMPRESSION = "zstd"

EXPECTED_OUTPUT_COLUMNS = [
    "rebalance_date", "ts_code", "in_universe",
    "mean_amount_wan", "n_trading_days_observed",
    "circ_mv_yi", "rank_by_mcap",
]


# ==========================================================
# Error logging
# ==========================================================

_logger = logging.getLogger("stage3_universe")
_logger.setLevel(logging.WARNING)
_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_logger.addHandler(_handler)


def _log_warn(date, msg):
    _logger.warning(f"date={date} | {msg}")


# ==========================================================
# Helpers
# ==========================================================

def get_rebalance_dates():
    if not REBALANCE_DATES_PATH.exists():
        raise FileNotFoundError(
            f"{REBALANCE_DATES_PATH} not found. Run stage1_with_pit_names.py first."
        )
    return pd.read_csv(REBALANCE_DATES_PATH)["date"].tolist()


def load_liquidity_panel():
    if not LIQUIDITY_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"{LIQUIDITY_PANEL_PATH} not found. Run stage2_liquidity_panel.py full first."
        )
    panel = pd.read_parquet(LIQUIDITY_PANEL_PATH)
    print(f"  liquidity panel: {len(panel):,} rows across "
          f"{panel['rebalance_date'].nunique()} dates")
    return panel


def load_candidates_for_date(date):
    """Read Stage 1 PIT candidate parquet for one rebalance date."""
    path = CANDIDATES_DIR / f"cand_{date}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path, columns=["ts_code", "circ_mv_yi"])


# ==========================================================
# Core selection logic
# ==========================================================

def build_universe_for_date(rebalance_date, liquidity_for_date, verbose=False):
    """
    Apply the hybrid liquidity filter and bottom-1000-by-cap selection
    for one rebalance date.

    Returns a DataFrame with one row per candidate (matching Stage 1's
    output for that date), with diagnostic columns added so the file
    also supports near-miss / boundary analysis.
    """
    candidates = load_candidates_for_date(rebalance_date)
    if candidates is None or len(candidates) == 0:
        _log_warn(rebalance_date, "no Stage 1 candidates")
        return None, None

    # Inner-join: only keep stocks that have both candidate (Stage 1) and
    # liquidity (Stage 2) data. Stocks suspended for the entire 60-day
    # window are absent from the liquidity panel and are correctly
    # excluded here.
    merged = candidates.merge(
        liquidity_for_date,
        on="ts_code",
        how="left",  # left so we preserve every candidate for diagnostic columns
    )

    # Apply the hybrid floor only on rows where liquidity data exists.
    # Rows with NaN liquidity (no observed trading in the 60-day window)
    # automatically fail the filter without needing explicit NaN handling.
    has_liq = merged["mean_amount_wan"].notna()
    n_with_liq = int(has_liq.sum())

    # Filter 1: minimum trading-day coverage
    pass_n_days = (merged["n_trading_days_observed"] >= N_MIN_DAYS) & has_liq
    n_pass_days = int(pass_n_days.sum())

    # Filter 2: percentile rank within the n_days-passing pool. The rank
    # is computed only on stocks that pass the n_days filter, because
    # percentile-ranking against suspended stocks would give a misleading
    # picture of relative liquidity.
    threshold_pct = 1.0 - X_PERCENTILE / 100.0  # X=75 -> 0.25
    eligible_pool = merged.loc[pass_n_days].copy()
    eligible_pool["liq_pct_rank"] = eligible_pool["mean_amount_wan"].rank(pct=True)
    pass_percentile_codes = set(
        eligible_pool.loc[eligible_pool["liq_pct_rank"] >= threshold_pct, "ts_code"]
    )

    # Filter 3: absolute floor
    pass_floor_codes = set(
        merged.loc[merged["mean_amount_wan"] >= Y_FLOOR_WAN, "ts_code"]
    )

    # Survivors: pass all three (n_days AND percentile AND floor)
    survivor_codes = (
        set(merged.loc[pass_n_days, "ts_code"])
        & pass_percentile_codes
        & pass_floor_codes
    )
    n_survivors = len(survivor_codes)

    # Bottom-N by mcap from the survivor pool. Sort ascending; head(N)
    # gives the smallest-cap survivors.
    survivors = merged[merged["ts_code"].isin(survivor_codes)].copy()
    survivors_sorted = survivors.sort_values("circ_mv_yi", ascending=True)
    universe = survivors_sorted.head(UNIVERSE_TARGET_SIZE)
    universe_codes = set(universe["ts_code"])

    # Build full output: one row per candidate. Universe membership flagged.
    out = merged[["ts_code", "mean_amount_wan", "n_trading_days_observed",
                  "circ_mv_yi"]].copy()
    out["in_universe"] = out["ts_code"].isin(universe_codes)
    # Rank within candidates by mcap ascending. method='min' gives ties the
    # same (lowest) rank; ranks are 1-indexed.
    out["rank_by_mcap"] = (
        out["circ_mv_yi"].rank(method="min", ascending=True).astype("int32")
    )
    out.insert(0, "rebalance_date", rebalance_date)

    diag = {
        "n_candidates": len(merged),
        "n_with_liq": n_with_liq,
        "n_pass_n_days": n_pass_days,
        "n_survivors": n_survivors,
        "n_universe": len(universe),
    }

    if verbose:
        print(f"  filter chain: candidates={diag['n_candidates']} "
              f"-> with_liq={diag['n_with_liq']} "
              f"-> n_days>={N_MIN_DAYS}: {diag['n_pass_n_days']} "
              f"-> hybrid floor: {diag['n_survivors']} "
              f"-> bottom-{UNIVERSE_TARGET_SIZE}: {diag['n_universe']}")
        if diag['n_survivors'] < UNIVERSE_TARGET_SIZE:
            print(f"  [WARN] survivor pool ({diag['n_survivors']}) is smaller "
                  f"than target universe size ({UNIVERSE_TARGET_SIZE}); "
                  f"universe is undersized")

    return out[EXPECTED_OUTPUT_COLUMNS], diag


# ==========================================================
# Diagnostic plot
# ==========================================================

def plot_diagnostic(membership):
    """
    Three-panel diagnostic showing universe behavior over time.

    Panel 1: liquidity of the universe (mean and median mean_amount_wan
             of universe members), with the Y_FLOOR_WAN reference line.
    Panel 2: market cap distribution of the universe (mean and 95th
             percentile of circ_mv_yi).
    Panel 3: inter-date universe turnover (% of stocks at date_t that
             are no longer in the universe at date_{t+1}).
    """
    universe = membership[membership["in_universe"]].copy()
    universe["rebalance_date"] = pd.to_datetime(universe["rebalance_date"])

    by_date = (
        universe.groupby("rebalance_date")
        .agg(
            n=("ts_code", "size"),
            amount_mean=("mean_amount_wan", "mean"),
            amount_median=("mean_amount_wan", "median"),
            cap_mean=("circ_mv_yi", "mean"),
            cap_p95=("circ_mv_yi", lambda s: s.quantile(0.95)),
        )
        .reset_index()
        .sort_values("rebalance_date")
        .reset_index(drop=True)
    )

    # Inter-date turnover
    universe_by_date = (
        universe.groupby("rebalance_date")["ts_code"].apply(set).to_dict()
    )
    rebalance_dates = by_date["rebalance_date"].tolist()
    turnover_records = []
    for i in range(1, len(rebalance_dates)):
        prev = universe_by_date[rebalance_dates[i - 1]]
        curr = universe_by_date[rebalance_dates[i]]
        if not prev:
            continue
        exited = len(prev - curr)
        turnover_records.append({
            "rebalance_date": rebalance_dates[i],
            "turnover_pct": 100.0 * exited / len(prev),
        })
    turnover = pd.DataFrame(turnover_records)

    # N-constancy sanity check, surfaced in title
    n_values = by_date["n"].unique()
    if len(n_values) == 1:
        n_summary = f"N={int(n_values[0])} for all {len(by_date)} dates"
    else:
        n_summary = (f"N varies: min={int(by_date['n'].min())}, "
                     f"max={int(by_date['n'].max())}, "
                     f"undersized={int((by_date['n'] < UNIVERSE_TARGET_SIZE).sum())}")

    fig, axes = plt.subplots(3, 1, figsize=(13, 11), sharex=True)

    # Panel 1: liquidity
    ax = axes[0]
    ax.plot(by_date["rebalance_date"], by_date["amount_mean"],
            label="Mean", color="C0", linewidth=1.5)
    ax.plot(by_date["rebalance_date"], by_date["amount_median"],
            label="Median", color="C1", linewidth=1.5)
    ax.axhline(Y_FLOOR_WAN, color="red", linestyle="--", linewidth=1,
               label=f"Y = {Y_FLOOR_WAN}万 (absolute floor)")
    ax.set_ylabel("Trading amount (万 RMB)")
    ax.set_title("Universe liquidity over time (60-day trailing mean amount)")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Panel 2: market cap distribution
    ax = axes[1]
    ax.plot(by_date["rebalance_date"], by_date["cap_mean"],
            label="Mean", color="C0", linewidth=1.5)
    ax.plot(by_date["rebalance_date"], by_date["cap_p95"],
            label="95th percentile", color="C2", linewidth=1.5)
    ax.set_ylabel("Circulating market cap (亿 RMB)")
    ax.set_title("Universe market cap distribution over time")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Panel 3: inter-date turnover
    ax = axes[2]
    if not turnover.empty:
        ax.plot(turnover["rebalance_date"], turnover["turnover_pct"],
                color="C3", linewidth=1.0, marker="o", markersize=2.5)
        median_to = turnover["turnover_pct"].median()
        ax.axhline(median_to, color="gray", linestyle=":", linewidth=1,
                   label=f"Median: {median_to:.1f}%")
        ax.legend(loc="best", fontsize=9)
    ax.set_ylabel("Turnover (% exiting per week)")
    ax.set_title("Inter-week universe turnover")
    ax.set_xlabel("Rebalance date")
    ax.grid(True, alpha=0.3)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter())

    fig.suptitle(
        f"Universe membership diagnostic | X={X_PERCENTILE}%, Y={Y_FLOOR_WAN}万, "
        f"n_min_days={N_MIN_DAYS} | {n_summary}",
        fontsize=12, y=0.995,
    )
    fig.tight_layout()
    fig.savefig(OUTPUT_PLOT, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote diagnostic plot -> {OUTPUT_PLOT}")


# ==========================================================
# Drivers
# ==========================================================

def smoke_test():
    print("=" * 60)
    print(f"STAGE 3 SMOKE: universe construction for first 5 weekly dates")
    print(f"  X={X_PERCENTILE}%, Y={Y_FLOOR_WAN}万, n_min_days={N_MIN_DAYS}, "
          f"target N={UNIVERSE_TARGET_SIZE}")
    print("=" * 60)

    panel = load_liquidity_panel()
    rebalance_dates = get_rebalance_dates()
    test_dates = rebalance_dates[:5]

    t0 = time.time()
    for i, date in enumerate(test_dates, 1):
        print(f"[{i}/5] {date}")
        liq = panel[panel["rebalance_date"] == date]
        out, diag = build_universe_for_date(date, liq, verbose=True)
        if out is None:
            print(f"  -> FAILED")
        else:
            universe = out[out["in_universe"]]
            print(f"  -> universe: {len(universe)} stocks, "
                  f"smallest cap {universe['circ_mv_yi'].min():.2f} 亿, "
                  f"largest cap {universe['circ_mv_yi'].max():.2f} 亿, "
                  f"median amount {universe['mean_amount_wan'].median():,.0f} 万")
        print()

    print(f"Smoke done in {time.time() - t0:.1f}s.")


def full_run():
    print(f"STAGE 3 FULL: building universe for all weekly dates")
    print(f"  X={X_PERCENTILE}%, Y={Y_FLOOR_WAN}万, n_min_days={N_MIN_DAYS}, "
          f"target N={UNIVERSE_TARGET_SIZE}")
    print(f"  output -> {OUTPUT_PARQUET}\n")

    panel = load_liquidity_panel()
    rebalance_dates = get_rebalance_dates()

    t0 = time.time()
    frames = []
    diags = []
    n_failed = 0
    n_undersized = 0

    # Pre-group the liquidity panel by date for fast per-date lookup.
    panel_by_date = dict(tuple(panel.groupby("rebalance_date")))

    for i, date in enumerate(rebalance_dates, 1):
        liq = panel_by_date.get(date, pd.DataFrame())
        out, diag = build_universe_for_date(date, liq, verbose=False)
        if out is None:
            n_failed += 1
            continue
        frames.append(out)
        diags.append({"rebalance_date": date, **diag})
        if diag["n_universe"] < UNIVERSE_TARGET_SIZE:
            n_undersized += 1

        if i % 50 == 0 or i == len(rebalance_dates):
            secs = time.time() - t0
            print(f"[{i:>4}/{len(rebalance_dates)}] {date}: "
                  f"ok={len(frames)}, failed={n_failed}, "
                  f"undersized={n_undersized}, elapsed={secs:.1f}s")

    if not frames:
        print("ERROR: no universe panels built.")
        return

    print(f"\nConcatenating {len(frames)} per-date frames...")
    membership = pd.concat(frames, ignore_index=True)
    membership.to_parquet(OUTPUT_PARQUET, compression=COMPRESSION, index=False)

    secs = time.time() - t0
    print(f"\nFull run done in {secs:.1f}s")
    print(f"  total rows:                     {len(membership):,}")
    print(f"  unique dates:                   {membership['rebalance_date'].nunique():,}")
    print(f"  unique stocks (any date):       {membership['ts_code'].nunique():,}")
    print(f"  unique stocks (in universe):    "
          f"{membership.loc[membership['in_universe'], 'ts_code'].nunique():,}")
    print(f"  output -> {OUTPUT_PARQUET}")
    if n_undersized > 0:
        print(f"  [WARN] {n_undersized} dates had survivor pool < {UNIVERSE_TARGET_SIZE}")
        print(f"         (universe is undersized on those dates; see diagnostic plot)")

    # Build diagnostic plot
    print(f"\nBuilding diagnostic plot...")
    plot_diagnostic(membership)


def status():
    if not OUTPUT_PARQUET.exists():
        print(f"No universe panel at {OUTPUT_PARQUET}. Run with `full`.")
        return

    membership = pd.read_parquet(OUTPUT_PARQUET)
    universe = membership[membership["in_universe"]]

    print(f"Universe panel: {OUTPUT_PARQUET}")
    print(f"  total rows:                  {len(membership):,}")
    print(f"  rows in universe:            {len(universe):,}")
    print(f"  unique dates:                {membership['rebalance_date'].nunique():,}")
    print(f"  unique candidates (any date):  {membership['ts_code'].nunique():,}")
    print(f"  unique universe members:     "
          f"{universe['ts_code'].nunique():,}")

    # Per-date universe size
    sizes = universe.groupby("rebalance_date").size()
    print(f"\n  Universe size per date:")
    print(f"    mean:   {sizes.mean():>6.1f}")
    print(f"    median: {int(sizes.median()):>6}")
    print(f"    min:    {int(sizes.min()):>6}  on {sizes.idxmin()}")
    print(f"    max:    {int(sizes.max()):>6}  on {sizes.idxmax()}")
    n_full = int((sizes == UNIVERSE_TARGET_SIZE).sum())
    n_undersized = int((sizes < UNIVERSE_TARGET_SIZE).sum())
    print(f"    full ({UNIVERSE_TARGET_SIZE}):    {n_full:>6}")
    print(f"    undersized:    {n_undersized:>6}")

    print(f"\n  Universe market cap (亿 RMB) summary:")
    print(universe["circ_mv_yi"].describe().to_string())

    print(f"\n  Universe trading amount (万 RMB) summary:")
    print(universe["mean_amount_wan"].describe().to_string())


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_run()
    elif mode == "status":
        status()
    else:
        print(f"Usage: python stage3_universe_membership.py [smoke|full|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()