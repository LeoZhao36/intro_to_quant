"""
Stage 3: Hybrid floor selection and universe membership.

Joins Stage 1's per-date candidate sets with Stage 2's liquidity panel,
applies a hybrid liquidity floor (top X% by mean trailing-20-day amount
within the full candidate set, AND >= Y in 万 RMB absolute), then takes
the bottom 1000 by circ_mv_yi from the survivors.

Produces one membership CSV and one three-panel diagnostic PNG per (X, Y) pair.

Run:
    python universe_membership.py              # all three default candidates
    python universe_membership.py 80 1500      # single (X, Y) pair
"""

import os
import sys
from glob import glob

import pandas as pd
import matplotlib.pyplot as plt

import plot_setup  # noqa: F401  registers Chinese fonts on import

# ---------------------------------------------------------------------------
# Paths and constants

DATA_DIR = "data"
CANDIDATES_DIR = os.path.join(DATA_DIR, "candidates")
LIQUIDITY_PANEL_PATH = os.path.join(DATA_DIR, "liquidity_panel.csv")

UNIVERSE_TARGET_SIZE = 1000

# (X in percent, Y in 万 RMB). Three candidates from Stage 2 handoff.
DEFAULT_CANDIDATE_PAIRS = [(80, 1500), (80, 2500), (70, 2000)]

EXPECTED_LIQUIDITY_PANEL_COLUMNS = frozenset({
    "rebalance_date", "ts_code", "mean_amount_wan",
    "n_trading_days_observed", "passes_3000_floor",
})

# Stage 1's candidate CSVs may carry extra columns (name, industry, etc.);
# only require the minimum set Stage 3 actually uses.
EXPECTED_CANDIDATE_COLUMNS_MIN = frozenset({"ts_code", "circ_mv_yi"})


# ---------------------------------------------------------------------------
# I/O and validation

def _validate_columns(df, expected, source):
    """Raise with a clear message if any expected column is missing."""
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"{source} missing expected columns: {sorted(missing)}")


def load_inputs():
    """Load liquidity panel and per-date candidate CSVs. Schema-validate both."""
    print(f"Loading liquidity panel from {LIQUIDITY_PANEL_PATH}")
    header = pd.read_csv(LIQUIDITY_PANEL_PATH, nrows=0)
    _validate_columns(header, EXPECTED_LIQUIDITY_PANEL_COLUMNS, "liquidity_panel.csv")
    panel = pd.read_csv(
        LIQUIDITY_PANEL_PATH,
        dtype={"ts_code": str, "rebalance_date": str},
    )
    print(f"  loaded {len(panel):,} rows across {panel['rebalance_date'].nunique()} dates")

    print(f"Loading candidate CSVs from {CANDIDATES_DIR}/")
    paths = sorted(glob(os.path.join(CANDIDATES_DIR, "candidates_*.csv")))
    if not paths:
        raise FileNotFoundError(f"No candidate CSVs found in {CANDIDATES_DIR}/")

    candidates_by_date = {}
    for path in paths:
        rebalance_date = os.path.basename(path).replace("candidates_", "").replace(".csv", "")
        header = pd.read_csv(path, nrows=0)
        _validate_columns(header, EXPECTED_CANDIDATE_COLUMNS_MIN, path)
        candidates_by_date[rebalance_date] = pd.read_csv(path, dtype={"ts_code": str})
    print(f"  loaded {len(candidates_by_date)} candidate sets")

    # Cross-check: panel dates and candidate dates must match exactly.
    panel_dates = set(panel["rebalance_date"].unique())
    candidate_dates = set(candidates_by_date.keys())
    if panel_dates != candidate_dates:
        only_panel = panel_dates - candidate_dates
        only_cand = candidate_dates - panel_dates
        msg = "Panel and candidate dates do not match."
        if only_panel:
            msg += f" Only in panel: {sorted(only_panel)}."
        if only_cand:
            msg += f" Only in candidates: {sorted(only_cand)}."
        raise ValueError(msg)

    return panel, candidates_by_date


# ---------------------------------------------------------------------------
# Core selection logic

def build_universe_for_date(candidates_R, panel_R, X, Y):
    """
    Apply the hybrid liquidity filter to the full candidate set, then take
    bottom-N by circ_mv_yi from survivors.

    Args:
        candidates_R: candidate set for rebalance date R (Stage 1 output).
        panel_R: liquidity panel rows for date R (Stage 2 output, this date only).
        X: liquidity percentile cutoff in percent. X=80 keeps the top 80%.
        Y: absolute liquidity floor in 万 RMB.

    Returns:
        out: one row per stock in candidates_R with columns
             ts_code, in_universe, mean_amount_wan, circ_mv_yi, rank_by_mcap.
        diag: dict with intermediate counts.
    """
    # Defensive: drop candidates with NaN mcap (shouldn't happen post-Stage-1
    # mcap correction, but a NaN here would silently corrupt the rank).
    candidates_R = candidates_R.dropna(subset=["circ_mv_yi"]).copy()

    threshold_pct = 1.0 - X / 100.0  # X=80 -> 0.20

    # Liquidity percentile is computed within the panel for date R, i.e. among
    # stocks that actually traded in the trailing-20-day window. Stocks suspended
    # for the entire window are absent from the panel and therefore implicitly
    # fail the liquidity filter (which is the right behaviour: they are not
    # tradable).
    panel_R = panel_R.copy()
    panel_R["liq_pct_rank"] = panel_R["mean_amount_wan"].rank(pct=True)
    survivors = panel_R[
        (panel_R["liq_pct_rank"] >= threshold_pct)
        & (panel_R["mean_amount_wan"] >= Y)
    ][["ts_code", "mean_amount_wan"]]

    # Inner-join restricts to stocks that pass BOTH gates: liquidity (from
    # panel) AND Stage 1's candidate filters (A-share, non-ST, listing age,
    # mcap available). Anything in panel but not in candidates_R is correctly
    # discarded here.
    eligible = candidates_R.merge(survivors, on="ts_code", how="inner")

    # Bottom-N by market cap, ascending.
    eligible_sorted = eligible.sort_values("circ_mv_yi", ascending=True)
    universe = eligible_sorted.head(UNIVERSE_TARGET_SIZE)
    universe_codes = set(universe["ts_code"])

    # Build full output: one row per candidate (not just universe members),
    # so the file also supports near-miss / boundary analysis.
    out = candidates_R[["ts_code", "circ_mv_yi"]].copy()
    out = out.merge(
        panel_R[["ts_code", "mean_amount_wan"]],
        on="ts_code",
        how="left",  # left-join so stocks absent from panel still appear with NaN
    )
    out["in_universe"] = out["ts_code"].isin(universe_codes)
    # Rank within candidates_R by mcap ascending: 1 = smallest cap candidate.
    # method="min" gives ties the same (lowest) rank; ranks are 1-indexed.
    out["rank_by_mcap"] = (
        out["circ_mv_yi"].rank(method="min", ascending=True).astype(int)
    )

    diag = {
        "n_in_panel": len(panel_R),
        "n_passed_filter": len(survivors),
        "n_eligible": len(eligible),
        "n_universe": len(universe),
    }
    return out, diag


def build_universe_all_dates(panel, candidates_by_date, X, Y):
    """Per-date pipeline across all rebalance dates, concatenated."""
    rows = []
    diag_rows = []
    for rebalance_date in sorted(candidates_by_date.keys()):
        candidates_R = candidates_by_date[rebalance_date]
        panel_R = panel[panel["rebalance_date"] == rebalance_date]
        out, diag = build_universe_for_date(candidates_R, panel_R, X, Y)
        out.insert(0, "rebalance_date", rebalance_date)
        rows.append(out)
        diag_rows.append({"rebalance_date": rebalance_date, **diag})

    membership = pd.concat(rows, ignore_index=True)
    diagnostics = pd.DataFrame(diag_rows)
    return membership, diagnostics


def write_membership(membership, X, Y):
    """Write membership CSV with columns ordered per the handoff spec."""
    path = os.path.join(DATA_DIR, f"universe_membership_X{X}_Y{Y}.csv")
    cols = ["rebalance_date", "ts_code", "in_universe",
            "mean_amount_wan", "circ_mv_yi", "rank_by_mcap"]
    membership[cols].to_csv(path, index=False)
    print(f"  wrote {path} ({len(membership):,} rows)")
    return path


# ---------------------------------------------------------------------------
# Diagnostic plot

def plot_diagnostic(membership, X, Y, output_path):
    """Three-panel diagnostic: liquidity, market cap, turnover."""
    universe = membership[membership["in_universe"]].copy()
    universe["rebalance_date"] = pd.to_datetime(universe["rebalance_date"])

    # Per-date aggregates.
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

    # Inter-date turnover: % of date_t universe members not present at date_{t+1}.
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

    # N-constancy sanity check, surfaced in title.
    n_values = by_date["n"].unique()
    if len(n_values) == 1:
        n_summary = f"N={int(n_values[0])} for all {len(by_date)} dates"
    else:
        n_summary = (f"N varies: min={int(by_date['n'].min())}, "
                     f"max={int(by_date['n'].max())}, "
                     f"undersized={int((by_date['n'] < UNIVERSE_TARGET_SIZE).sum())}")

    fig, axes = plt.subplots(3, 1, figsize=(11, 11), sharex=True)

    # Panel 1: liquidity of universe over time, with absolute floor reference.
    ax = axes[0]
    ax.plot(by_date["rebalance_date"], by_date["amount_mean"],
            label="Mean", color="C0", linewidth=1.5)
    ax.plot(by_date["rebalance_date"], by_date["amount_median"],
            label="Median", color="C1", linewidth=1.5)
    ax.axhline(Y, color="red", linestyle="--", linewidth=1,
               label=f"Y = {Y}万 (absolute floor)")
    ax.set_ylabel("Trading amount (万 RMB)")
    ax.set_title("Universe liquidity over time")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Panel 2: market-cap distribution of universe (stress-period drift).
    ax = axes[1]
    ax.plot(by_date["rebalance_date"], by_date["cap_mean"],
            label="Mean", color="C0", linewidth=1.5)
    ax.plot(by_date["rebalance_date"], by_date["cap_p95"],
            label="95th percentile", color="C2", linewidth=1.5)
    ax.set_ylabel("Circulating market cap (亿 RMB)")
    ax.set_title("Universe market cap distribution over time")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Panel 3: inter-date turnover.
    ax = axes[2]
    if not turnover.empty:
        ax.plot(turnover["rebalance_date"], turnover["turnover_pct"],
                color="C3", linewidth=1.5, marker="o", markersize=3)
        median_to = turnover["turnover_pct"].median()
        ax.axhline(median_to, color="gray", linestyle=":", linewidth=1,
                   label=f"Median: {median_to:.1f}%")
        ax.legend(loc="best", fontsize=9)
    ax.set_ylabel("Turnover (% exiting)")
    ax.set_title("Inter-date universe turnover")
    ax.set_xlabel("Rebalance date")
    ax.grid(True, alpha=0.3)

    fig.suptitle(
        f"Universe membership diagnostic | X={X}%, Y={Y}万 | {n_summary}",
        fontsize=12, y=0.995,
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {output_path}")


# ---------------------------------------------------------------------------
# Driver

def run_pipeline(panel, candidates_by_date, X, Y):
    """End-to-end pipeline for one (X, Y) pair."""
    print(f"\n--- (X={X}%, Y={Y}万) ---")
    membership, diagnostics = build_universe_all_dates(panel, candidates_by_date, X, Y)

    sizes = diagnostics["n_universe"]
    if sizes.nunique() == 1:
        print(f"  universe size: {int(sizes.iloc[0])} for all {len(diagnostics)} dates")
    else:
        undersized = int((sizes < UNIVERSE_TARGET_SIZE).sum())
        print(f"  universe size: min={int(sizes.min())}, max={int(sizes.max())}, "
              f"undersized dates={undersized}")

    print(f"  median liquidity-survivor count: {int(diagnostics['n_passed_filter'].median())}")
    print(f"  median eligible count: {int(diagnostics['n_eligible'].median())}")

    csv_path = write_membership(membership, X, Y)
    plot_path = csv_path.replace(".csv", "_diagnostic.png")
    plot_diagnostic(membership, X, Y, plot_path)


def main():
    panel, candidates_by_date = load_inputs()

    if len(sys.argv) == 3:
        X = int(sys.argv[1])
        Y = int(sys.argv[2])
        run_pipeline(panel, candidates_by_date, X, Y)
    elif len(sys.argv) == 1:
        for X, Y in DEFAULT_CANDIDATE_PAIRS:
            run_pipeline(panel, candidates_by_date, X, Y)
    else:
        print("Usage: python universe_membership.py [X Y]")
        print("  X in percent (e.g., 80), Y in 万 RMB (e.g., 1500)")
        sys.exit(1)


if __name__ == "__main__":
    main()