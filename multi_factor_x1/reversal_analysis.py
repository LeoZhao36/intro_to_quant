"""
reversal_analysis.py — short-term reversal factor on Universe A.

Diagnostic question: does past N-day return (sign-flipped) carry
cross-sectional predictive signal for next-week return, separate from
what z_turnover_resid already captures?

Construction
------------
For lookback L trading days with skip-1:
    p_skip = adj_close on (r - 1)            # one day before rebalance
    p_ref  = adj_close on (r - 1 - L)        # L days earlier
    r_past = p_skip / p_ref - 1              # past return over L days
    reversal_raw_<L>d = -r_past              # sign flip: past loser → high
    winsorize at [1%, 99%] per rebalance     # past returns are unbounded;
                                               # turnover wasn't, so this is
                                               # an extra step here
    residualize on controls (per rebalance OLS):
        standalone:  sector_l1 + log_mcap
        orthog:      sector_l1 + log_mcap + z_turnover_resid
                       isolates reversal signal beyond turnover
    z-score residual cross-sectionally → z_reversal_resid_<L>d
                                       or z_reversal_orthog_<L>d
    high z = past loser within sector and size (and turnover, for orthog)
           = LONG side (Q5)

Note on the orthog form
-----------------------
By Frisch-Waugh-Lovell, residualizing reversal_raw on
(sector + log_mcap + z_turnover_resid) in one OLS yields identical
residuals to the two-step procedure (residualize on sector+size, then
regress the residual on z_turnover_resid). One-step form used here for
code clarity.

Modes
-----
    python reversal_analysis.py sweep
        Phase 1 across all (lookback × control_set) combos (default
        L ∈ {3, 5, 10}, control_set ∈ {standalone, orthog} = 6 configs).
        Saves the comparison table and orthogonality diagnostics.
        This is the diagnostic run.

    python reversal_analysis.py phase1 --lookback 5
        Phase 1 for one config (default standalone). Saves a single-config
        summary.

    python reversal_analysis.py both --lookback 5 --orthog
        Phase 1 + Phase 2 for one config. Phase 2 is the daily backtest;
        only run after deciding which config to deploy.

    python reversal_analysis.py phase2 --lookback 5 --start 2024-04-12

Decision discipline
-------------------
- Pick the winning lookback L on the β window (pre-2024-04-12) only.
- Freeze L, then evaluate on γ window (post-2024-04-12) for honest
  out-of-sample. Use --start / --end to slice.
- Compare orthog IC to standalone IC. If orthog IC retains <30% of
  standalone IC, reversal is mostly redundant with turnover and should
  not get a meaningful weight in any combination.

Sign convention
---------------
high z_reversal_resid_<L>d = past loser, conditional on sector + size
                           = LONG side (Q5)
high z_reversal_orthog_<L>d = past loser, conditional on
                              sector + size + residualized turnover
                            = LONG side (Q5)

Prerequisites
-------------
  - data/factor_panel_a.parquet
  - data/sw_l1_membership.parquet (run fetch_sw_industry.py first)
  - daily_panel/daily_<DATE>.parquet for the L-day windows before each
    rebalance and for the Phase 2 backtest range
  - Project_6/data/trading_calendar.csv

Outputs
-------
  Sweep mode:
    data/reversal_sweep_summary.csv
    data/reversal_orthogonality_diagnostics.csv
    graphs/reversal_phase1_sweep.png

  Single-config phase 1:
    data/reversal_phase1_<z_col>.csv

  Single-config phase 2:
    data/reversal_phase2_daily_<z_col>.csv
    data/reversal_phase2_summary_<z_col>.csv
    graphs/reversal_phase2_<z_col>_compare.png

Where <z_col> is e.g. z_reversal_resid_5d or z_reversal_orthog_5d.
"""

import argparse
import logging
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    A_SHARE_PATTERN,
    DAILY_PANEL_DIR,
    GRAPHS_DIR,
    NEW_NINE_ARTICLES_DATE,
    PBOC_STIMULUS_DATE,
    THREE_REGIME_WINDOWS,
    TRADING_CALENDAR_PATH,
    TRADING_DAYS_PER_YEAR,
)
from factor_utils import (
    compute_ic_series,
    compute_quintile_series,
    cross_sectional_zscore,
    residualise_factor_per_date,
    summarise_long_short,
)
from hypothesis_testing import block_bootstrap_ci

# Reuse load_panel_with_sector and add_z_turnover_resid from
# turnover_neutralized.py rather than duplicate. fetch_sw_industry import
# happens transitively through turnover_neutralized, which already has
# the sys.path-ordering fix in place.
from turnover_neutralized import (
    load_panel_with_sector,
    add_z_turnover_resid,
)


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
GRAPHS_DIR.mkdir(exist_ok=True)

FACTOR_PANEL_PATH = DATA_DIR / "factor_panel_a.parquet"
SWEEP_OUT = DATA_DIR / "reversal_sweep_summary.csv"
ORTHOG_DIAG_OUT = DATA_DIR / "reversal_orthogonality_diagnostics.csv"
SWEEP_PLOT_OUT = GRAPHS_DIR / "reversal_phase1_sweep.png"
ERROR_LOG = DATA_DIR / "errors_reversal.log"

# Backtest parameters (must match turnover_analysis / turnover_neutralized
# for fair head-to-head comparison)
N_QUINTILES = 5
WEEKLY_BLOCK_SIZE = 12
DAILY_BLOCK_SIZE = 20
SEED = 42
BOOT_N = 5000

# Lookback sweep
LOOKBACKS_DEFAULT = (3, 5, 10, 15, 20)
SKIP_DAYS = 1  # always 1: anchor on close[r-1], not close[r]

# Friendly aliases for --regime flag → THREE_REGIME_WINDOWS keys
REGIME_KEY_MAP = {
    "alpha": "alpha_all",
    "beta": "beta_pre_NNA",
    "gamma": "gamma_post_NNA",
}

# Winsorization for raw past return (per rebalance, before OLS)
WINSORIZE_LOW = 0.01
WINSORIZE_HIGH = 0.99


_logger = logging.getLogger("reversal_analysis")
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    _h = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _logger.addHandler(_h)


# ═══════════════════════════════════════════════════════════════════════
# Step 1: compute past returns from the daily panel
# ═══════════════════════════════════════════════════════════════════════

def compute_past_returns_panel(
    panel: pd.DataFrame,
    lookbacks: tuple[int, ...],
) -> pd.DataFrame:
    """
    Compute past N-day returns with skip-1 for each (rebalance_date, ts_code).

    For each lookback L:
        adj_close[r-1] / adj_close[r-1-L] - 1

    Reads daily_panel/daily_<DATE>.parquet for the union of all needed
    days (max_lookback + 1 days before each rebalance). Builds a wide
    adj_close panel (date × ts_code), then slices per rebalance.

    Returns
    -------
    DataFrame keyed (rebalance_date, ts_code) with one column per lookback
    named r_past_<L>d. NaN where adj_close is missing on either anchor day.
    """
    rebal_dates = sorted(panel["rebalance_date"].unique())
    cal = pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()
    cal_idx = {d: i for i, d in enumerate(cal)}

    max_L = max(lookbacks)

    # Collect needed trading days: for each rebalance r, days in
    # [r - 1 - max_L, r - 1] inclusive.
    needed_dates: set[str] = set()
    for r in rebal_dates:
        if r not in cal_idx:
            continue
        end_idx = cal_idx[r]
        lo_idx = max(0, end_idx - 1 - max_L)
        hi_idx = end_idx - 1
        if hi_idx < 0:
            continue
        for d in cal[lo_idx : hi_idx + 1]:
            needed_dates.add(d)
    needed_dates_sorted = sorted(needed_dates)

    print(f"\nReading {len(needed_dates_sorted)} trading days of daily "
          f"panels for past-return computation (max lookback "
          f"{max_L} days)...")

    # First pass: read each daily parquet, extract adj_close per A-share.
    all_frames = []
    t0 = time.time()
    for i, d in enumerate(needed_dates_sorted, 1):
        path = DAILY_PANEL_DIR / f"daily_{d}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df = df[df["ts_code"].str.match(A_SHARE_PATTERN)]
        if len(df) == 0:
            continue
        if "close" not in df.columns or "adj_factor" not in df.columns:
            _logger.warning(f"{path}: missing close or adj_factor; skipping")
            continue
        close = pd.to_numeric(df["close"], errors="coerce")
        adjf = pd.to_numeric(df["adj_factor"], errors="coerce")
        adj_close = close * adjf
        sub = pd.DataFrame({
            "ts_code": df["ts_code"].values,
            "adj_close": adj_close.values,
        })
        sub = sub.dropna()
        sub = sub[sub["adj_close"] > 0]
        if len(sub) > 0:
            sub["date"] = d
            all_frames.append(sub)
        if i % 200 == 0 or i == len(needed_dates_sorted):
            print(f"  [{i:>4}/{len(needed_dates_sorted)}] "
                  f"elapsed={time.time()-t0:.1f}s")

    if not all_frames:
        raise RuntimeError(
            "No A-share adjusted closes loaded from daily panels. "
            "Check DAILY_PANEL_DIR and that daily_<DATE>.parquet files exist."
        )

    # Pivot to wide
    print(f"\n  building wide adj_close panel...")
    t0 = time.time()
    long = pd.concat(all_frames, ignore_index=True)
    wide = (
        long
        .pivot(index="date", columns="ts_code", values="adj_close")
        .sort_index()
    )
    print(f"    shape: {wide.shape}  "
          f"({int(wide.notna().sum().sum()):,} non-NaN obs)  "
          f"elapsed: {time.time()-t0:.1f}s")

    # Per rebalance, lookup adj_close on anchor and reference days.
    print(f"\n  computing past returns for L in {list(lookbacks)}...")
    t0 = time.time()
    rows = []
    n_skipped = 0
    for r in rebal_dates:
        if r not in cal_idx:
            n_skipped += 1
            continue
        end_idx = cal_idx[r]
        prev_idx = end_idx - 1
        if prev_idx < 0:
            n_skipped += 1
            continue
        prev_day = cal[prev_idx]
        if prev_day not in wide.index:
            n_skipped += 1
            continue
        end_prices = wide.loc[prev_day]  # Series indexed by ts_code

        per_rebal = pd.DataFrame({
            "rebalance_date": r,
            "ts_code": end_prices.index,
            "_end": end_prices.values,
        })
        for L in lookbacks:
            ref_idx = end_idx - 1 - L
            col = f"r_past_{L}d"
            if ref_idx < 0:
                per_rebal[col] = np.nan
                continue
            ref_day = cal[ref_idx]
            if ref_day not in wide.index:
                per_rebal[col] = np.nan
                continue
            ref_prices = wide.loc[ref_day].reindex(end_prices.index)
            per_rebal[col] = per_rebal["_end"].values / ref_prices.values - 1
        per_rebal = per_rebal.drop(columns=["_end"])
        rows.append(per_rebal)

    if n_skipped > 0:
        print(f"    skipped {n_skipped} rebalance dates "
              f"(missing in calendar or no prior day)")
    out = pd.concat(rows, ignore_index=True)
    print(f"    elapsed: {time.time()-t0:.1f}s, rows: {len(out):,}")

    for L in lookbacks:
        col = f"r_past_{L}d"
        cov = out[col].notna().mean() * 100
        print(f"    {col}: coverage={cov:.1f}%, "
              f"mean={out[col].mean()*100:+.3f}%, "
              f"std={out[col].std()*100:.3f}%, "
              f"p1={out[col].quantile(0.01)*100:+.2f}%, "
              f"p99={out[col].quantile(0.99)*100:+.2f}%")
    return out


# ═══════════════════════════════════════════════════════════════════════
# Step 2: factor construction (one config at a time)
# ═══════════════════════════════════════════════════════════════════════

def _winsorize_per_date(
    panel: pd.DataFrame,
    col: str,
    low: float = WINSORIZE_LOW,
    high: float = WINSORIZE_HIGH,
) -> pd.DataFrame:
    """
    Per-date quantile clip on `col`. Reversal raw is unbounded so a single
    extreme name can distort the OLS fit; clipping at [1%, 99%] per
    rebalance is the simplest defense.
    """
    df = panel.copy()
    def _clip(s: pd.Series) -> pd.Series:
        lo = s.quantile(low)
        hi = s.quantile(high)
        return s.clip(lo, hi)
    df[col] = df.groupby("rebalance_date")[col].transform(_clip)
    return df


def add_z_reversal_resid(
    panel: pd.DataFrame,
    lookback: int,
    orthog_to_turnover: bool,
) -> tuple[pd.DataFrame, str]:
    """
    Build the residualized reversal factor for one (lookback, control_set)
    config. Adds two columns to the panel:
      reversal_resid_<L>d_<set>     OLS residual
      z_reversal_(resid|orthog)_<L>d  cross-sectional z-score of residual

    Returns the augmented panel and the name of the final z-score column
    (the one to sort baskets on).
    """
    set_tag = "orthog" if orthog_to_turnover else "resid"
    raw_col = f"reversal_raw_{lookback}d"
    resid_col = f"reversal_resid_{lookback}d_{set_tag}"
    z_col = f"z_reversal_{set_tag}_{lookback}d"

    if f"r_past_{lookback}d" not in panel.columns:
        raise ValueError(
            f"r_past_{lookback}d not in panel; run "
            f"compute_past_returns_panel first"
        )

    panel = panel.copy()
    # Sign flip: past loser → positive raw signal
    panel[raw_col] = -panel[f"r_past_{lookback}d"]
    # Winsorize the raw past return per date
    panel = _winsorize_per_date(panel, raw_col)

    numeric_controls = ["log_mcap"]
    if orthog_to_turnover:
        if "z_turnover_resid" not in panel.columns:
            raise ValueError(
                "orthog_to_turnover=True requires z_turnover_resid in panel; "
                "run add_z_turnover_resid first."
            )
        numeric_controls.append("z_turnover_resid")

    print(f"\nResidualizing {raw_col} on sector_l1 + "
          f"{' + '.join(numeric_controls)} ...")
    panel = residualise_factor_per_date(
        panel,
        factor_col=raw_col,
        out_col=resid_col,
        numeric_controls=numeric_controls,
        categorical_control="sector_l1",
    )

    # Cross-sectional z-score (mean 0, unit variance per date). High z
    # = positive residual = past loser within controls = LONG side.
    panel = cross_sectional_zscore(
        panel, factor_col=resid_col, out_col=z_col,
    )
    return panel, z_col


# ═══════════════════════════════════════════════════════════════════════
# Step 3: Phase 1 (weekly factor research)
# ═══════════════════════════════════════════════════════════════════════

def run_phase1_for_config(
    panel: pd.DataFrame,
    lookback: int,
    orthog: bool,
    save_csv: Path | None = None,
) -> dict:
    """
    Phase 1 on one config. Returns dict with quintile returns, IC series,
    and bootstrap CIs. Optionally writes a single-config summary CSV.
    """
    panel, z_col = add_z_reversal_resid(panel, lookback, orthog)

    iu = panel[panel["in_universe"]]
    n_with = int(iu[z_col].notna().sum())
    coverage = 100 * n_with / max(len(iu), 1)
    print(f"\n  in_universe rows with {z_col}: "
          f"{n_with:,} of {len(iu):,} ({coverage:.1f}%)")

    # Quintile sort
    print(f"\n  --- Quintile sort on {z_col} ---")
    qr = compute_quintile_series(panel, sort_col=z_col)
    for q in range(N_QUINTILES):
        if q in qr.columns:
            mean = qr[q].mean() * 100
            print(f"    Q{q+1}: {mean:+.3f}%/wk")

    summary = summarise_long_short(qr, f"Q5 - Q1 ({z_col})")

    if summary.get("n", 0) >= 2 * WEEKLY_BLOCK_SIZE:
        boot = block_bootstrap_ci(
            summary["ls_series"].values, np.mean,
            block_size=WEEKLY_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
        )
        print(f"\n  Block bootstrap CI on Q5-Q1 mean "
              f"(block={WEEKLY_BLOCK_SIZE}w):")
        print(f"    estimate: {boot['estimate']*100:+.3f}%/wk")
        print(f"    95% CI:   [{boot['ci_low']*100:+.3f}%, "
              f"{boot['ci_high']*100:+.3f}%]")
        print(f"    excludes zero: "
              f"{(boot['ci_low']>0) or (boot['ci_high']<0)}")
        summary["bootstrap_q5q1"] = boot

    # Cross-sectional Spearman IC
    print(f"\n  --- Cross-sectional Spearman IC ---")
    ic = compute_ic_series(panel, sort_col=z_col)
    if len(ic) > 1 and ic.std() > 0:
        ic_t = float(ic.mean() / (ic.std() / np.sqrt(len(ic))))
    else:
        ic_t = np.nan
    print(f"  IC: n={len(ic)}, mean={ic.mean():+.4f}, std={ic.std():.4f}, "
          f"t={ic_t:+.2f}")
    if len(ic) >= 2 * WEEKLY_BLOCK_SIZE:
        boot_ic = block_bootstrap_ci(
            ic.values, np.mean,
            block_size=WEEKLY_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
        )
        print(f"    95% CI on mean IC: [{boot_ic['ci_low']:+.4f}, "
              f"{boot_ic['ci_high']:+.4f}]")
        summary["bootstrap_ic"] = boot_ic

    summary["lookback"] = lookback
    summary["orthog"] = orthog
    summary["z_col"] = z_col
    summary["coverage_pct"] = coverage
    summary["ic_series"] = ic
    summary["ic_mean"] = float(ic.mean()) if len(ic) else np.nan
    summary["ic_std"] = float(ic.std()) if len(ic) else np.nan
    summary["ic_t"] = ic_t
    summary["quintile_returns"] = qr
    summary["panel"] = panel  # carry forward for downstream use

    if save_csv is not None:
        rows = [{
            "metric": f"Q5_minus_Q1_{z_col}",
            "lookback_d": lookback,
            "orthog": orthog,
            "n_periods": summary.get("n"),
            "mean_pct_wk": summary.get("mean_period", 0) * 100,
            "t_stat": summary.get("t_stat"),
            "naive_sharpe": summary.get("naive_sharpe"),
            "ci_low_pct_wk": summary.get("bootstrap_q5q1", {}).get("ci_low", np.nan) * 100,
            "ci_high_pct_wk": summary.get("bootstrap_q5q1", {}).get("ci_high", np.nan) * 100,
        }, {
            "metric": f"ic_mean_{z_col}",
            "lookback_d": lookback,
            "orthog": orthog,
            "n_periods": int(len(ic)),
            "mean_pct_wk": summary["ic_mean"],
            "t_stat": ic_t,
            "naive_sharpe": np.nan,
            "ci_low_pct_wk": summary.get("bootstrap_ic", {}).get("ci_low", np.nan),
            "ci_high_pct_wk": summary.get("bootstrap_ic", {}).get("ci_high", np.nan),
        }]
        pd.DataFrame(rows).to_csv(save_csv, index=False)
        print(f"\n  Phase 1 single-config summary saved to {save_csv}")

    return summary


def _filter_panel_by_date(
    panel: pd.DataFrame,
    start_date,
    end_date,
) -> pd.DataFrame:
    """
    Filter panel rows by rebalance_date. start_date and end_date may be
    str (YYYY-MM-DD), pd.Timestamp, or None. Both bounds inclusive.
    """
    if start_date is None and end_date is None:
        return panel
    rd = pd.to_datetime(panel["rebalance_date"])
    mask = pd.Series(True, index=panel.index)
    if start_date is not None:
        mask &= (rd >= pd.to_datetime(start_date))
    if end_date is not None:
        mask &= (rd <= pd.to_datetime(end_date))
    return panel[mask].copy()


def build_all_factor_columns(
    panel: pd.DataFrame,
    lookbacks: tuple[int, ...],
) -> pd.DataFrame:
    """
    Build z_turnover_resid plus z_reversal_resid_<L>d and z_reversal_orthog_<L>d
    for every L in lookbacks. Operates on the FULL panel so that downstream
    regime-filtered metrics share identical factor definitions across regimes.

    Cross-sectional residualization is per-date by construction, so building
    on the full panel and then filtering rows by date is mathematically
    identical to filtering first and then residualizing.
    """
    print("\n" + "=" * 76)
    print("BUILDING FACTOR COLUMNS (full panel, once)")
    print("=" * 76)

    print("\nComputing z_turnover_resid (orthog control + diagnostics)...")
    panel = add_z_turnover_resid(panel, with_beta=False)
    iu = panel[panel["in_universe"]]
    cov_turn = iu["z_turnover_resid"].notna().mean() * 100
    print(f"  z_turnover_resid coverage on in_universe: {cov_turn:.1f}%")

    for L in lookbacks:
        for orthog in (False, True):
            print(f"\n  Building z_reversal_"
                  f"{'orthog' if orthog else 'resid'}_{L}d ...")
            panel, _ = add_z_reversal_resid(
                panel, lookback=L, orthog_to_turnover=orthog,
            )
    return panel


def run_phase1_metrics(
    panel: pd.DataFrame,
    lookback: int,
    orthog: bool,
) -> dict:
    """
    Compute Phase 1 metrics on the (potentially filtered) panel. Assumes
    the relevant z_reversal_* and z_turnover_resid columns already exist
    (built by build_all_factor_columns).
    """
    set_tag = "orthog" if orthog else "resid"
    z_col = f"z_reversal_{set_tag}_{lookback}d"
    if z_col not in panel.columns:
        raise ValueError(
            f"{z_col} not in panel. Call build_all_factor_columns first."
        )

    iu = panel[panel["in_universe"]]
    n_with = int(iu[z_col].notna().sum())
    coverage = 100 * n_with / max(len(iu), 1)
    print(f"    in_universe rows with {z_col}: "
          f"{n_with:,} of {len(iu):,} ({coverage:.1f}%)")

    qr = compute_quintile_series(panel, sort_col=z_col)
    summary = summarise_long_short(qr, f"Q5 - Q1 ({z_col})")

    if summary.get("n", 0) >= 2 * WEEKLY_BLOCK_SIZE:
        boot = block_bootstrap_ci(
            summary["ls_series"].values, np.mean,
            block_size=WEEKLY_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
        )
        summary["bootstrap_q5q1"] = boot

    ic = compute_ic_series(panel, sort_col=z_col)
    if len(ic) > 1 and ic.std() > 0:
        ic_t = float(ic.mean() / (ic.std() / np.sqrt(len(ic))))
    else:
        ic_t = np.nan
    if len(ic) >= 2 * WEEKLY_BLOCK_SIZE:
        boot_ic = block_bootstrap_ci(
            ic.values, np.mean,
            block_size=WEEKLY_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
        )
        summary["bootstrap_ic"] = boot_ic

    summary["lookback"] = lookback
    summary["orthog"] = orthog
    summary["z_col"] = z_col
    summary["coverage_pct"] = coverage
    summary["ic_series"] = ic
    summary["ic_mean"] = float(ic.mean()) if len(ic) else np.nan
    summary["ic_std"] = float(ic.std()) if len(ic) else np.nan
    summary["ic_t"] = ic_t
    summary["quintile_returns"] = qr
    return summary


def _orthogonality_diagnostics_for_window(
    panel: pd.DataFrame,
    lookbacks: tuple[int, ...],
    metrics_by_config: dict,
    regime_label: str,
) -> list[dict]:
    """
    Per-regime orthogonality diagnostics. metrics_by_config keyed by
    (regime_label, lookback, orthog) → summary dict.
    """
    diag_rows = []
    for L in lookbacks:
        z_resid = f"z_reversal_resid_{L}d"
        if z_resid not in panel.columns:
            continue
        sub = panel[panel["in_universe"]].dropna(
            subset=[z_resid, "z_turnover_resid"]
        )
        per_date_rho = (
            sub.groupby("rebalance_date")
            .apply(
                lambda g: g[z_resid].corr(
                    g["z_turnover_resid"], method="spearman"
                ),
                include_groups=False,
            )
            .dropna()
        )
        ic_standalone = metrics_by_config.get(
            (regime_label, L, False), {}
        ).get("ic_mean")
        ic_orthog = metrics_by_config.get(
            (regime_label, L, True), {}
        ).get("ic_mean")
        diag_rows.append({
            "regime": regime_label,
            "lookback_d": L,
            "n_dates_for_corr": int(len(per_date_rho)),
            "mean_rank_corr": (
                round(float(per_date_rho.mean()), 4)
                if len(per_date_rho) else np.nan
            ),
            "median_rank_corr": (
                round(float(per_date_rho.median()), 4)
                if len(per_date_rho) else np.nan
            ),
            "std_rank_corr": (
                round(float(per_date_rho.std()), 4)
                if len(per_date_rho) else np.nan
            ),
            "ic_standalone": (
                round(ic_standalone, 5)
                if ic_standalone is not None and not pd.isna(ic_standalone)
                else np.nan
            ),
            "ic_orthog": (
                round(ic_orthog, 5)
                if ic_orthog is not None and not pd.isna(ic_orthog)
                else np.nan
            ),
            "ic_retention_pct": (
                round(100 * ic_orthog / ic_standalone, 1)
                if ic_standalone is not None
                and not pd.isna(ic_standalone)
                and abs(ic_standalone) > 1e-9
                else np.nan
            ),
        })
    return diag_rows


def run_phase1_sweep_multi_regime(
    panel: pd.DataFrame,
    lookbacks: tuple[int, ...] = LOOKBACKS_DEFAULT,
    custom_window: tuple | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Phase 1 sweep across (regime × lookback × control_set).

    Default: iterates THREE_REGIME_WINDOWS from config.py (alpha_all,
    beta_pre_NNA, gamma_post_NNA). If custom_window is provided as
    (start, end, label), runs that single window instead.

    Factor columns are built once on the full panel; each regime is just
    a date-filter on the same residualized values.

    Outputs reversal_sweep_summary.csv and reversal_orthogonality_diagnostics.csv
    with a `regime` column, plus a faceted PNG.
    """
    print("\n" + "=" * 76)
    print(f"PHASE 1 SWEEP (multi-regime)")
    print(f"  lookbacks: {list(lookbacks)}")
    print(f"  control sets: standalone (sector + log_mcap), "
          f"orthog (+ z_turnover_resid)")
    print("=" * 76)

    panel = build_all_factor_columns(panel, lookbacks)

    if custom_window is not None:
        start, end, label = custom_window
        regime_iter = [(label, (start, end))]
    else:
        regime_iter = list(THREE_REGIME_WINDOWS.items())

    rows = []
    diag_rows_all = []
    metrics_by_config: dict = {}

    for regime_label, (start, end) in regime_iter:
        print(f"\n{'═' * 76}")
        print(f"  REGIME: {regime_label}  ({start} → {end})")
        print(f"{'═' * 76}")

        filtered = _filter_panel_by_date(panel, start, end)
        n_rebal = filtered["rebalance_date"].nunique()
        n_iu = int(filtered["in_universe"].sum())
        print(f"  filtered: {len(filtered):,} rows, "
              f"{n_rebal} rebalance dates, "
              f"{n_iu:,} in_universe rows")

        for L in lookbacks:
            for orthog in (False, True):
                print(f"\n  ── L={L}d  "
                      f"control={'orthog' if orthog else 'standalone'} "
                      f"({regime_label}) ──")
                s = run_phase1_metrics(filtered, L, orthog)
                metrics_by_config[(regime_label, L, orthog)] = s
                rows.append({
                    "regime": regime_label,
                    "lookback_d": L,
                    "control_set": "orthog" if orthog else "standalone",
                    "z_col": s["z_col"],
                    "n_periods": s.get("n", 0),
                    "coverage_pct": round(s.get("coverage_pct", np.nan), 2),
                    "q5_minus_q1_pct_wk": round(s.get("mean_period", 0) * 100, 4),
                    "q5_minus_q1_t": (
                        round(s.get("t_stat", np.nan), 3)
                        if not pd.isna(s.get("t_stat", np.nan)) else np.nan
                    ),
                    "q5_minus_q1_ci_low_pct": round(
                        s.get("bootstrap_q5q1", {}).get("ci_low", np.nan) * 100, 4
                    ),
                    "q5_minus_q1_ci_high_pct": round(
                        s.get("bootstrap_q5q1", {}).get("ci_high", np.nan) * 100, 4
                    ),
                    "ic_mean": round(s.get("ic_mean", np.nan), 5),
                    "ic_t": (
                        round(s.get("ic_t", np.nan), 3)
                        if not pd.isna(s.get("ic_t", np.nan)) else np.nan
                    ),
                    "ic_ci_low": round(
                        s.get("bootstrap_ic", {}).get("ci_low", np.nan), 5
                    ),
                    "ic_ci_high": round(
                        s.get("bootstrap_ic", {}).get("ci_high", np.nan), 5
                    ),
                })

        # Orthogonality diagnostics for this regime
        diag_rows_all.extend(
            _orthogonality_diagnostics_for_window(
                filtered, lookbacks, metrics_by_config, regime_label
            )
        )

    sweep_df = pd.DataFrame(rows)
    sweep_df.to_csv(SWEEP_OUT, index=False)
    print(f"\n{'=' * 76}\nSWEEP SUMMARY (multi-regime)\n{'=' * 76}\n")
    print(sweep_df.to_string(index=False))
    print(f"\n  Saved to {SWEEP_OUT}")

    diag_df = pd.DataFrame(diag_rows_all)
    diag_df.to_csv(ORTHOG_DIAG_OUT, index=False)
    print(f"\n{'=' * 76}\nORTHOGONALITY DIAGNOSTICS (multi-regime)")
    print(f"{'=' * 76}\n")
    print(diag_df.to_string(index=False))
    print(f"\n  Saved to {ORTHOG_DIAG_OUT}")

    _plot_sweep_multi_regime(sweep_df, diag_df)

    return sweep_df, diag_df


def _plot_sweep_multi_regime(
    sweep_df: pd.DataFrame,
    diag_df: pd.DataFrame,
) -> None:
    """
    2 rows × N regimes layout. Top row: IC mean ± bootstrap CI by lookback,
    one line per control set. Bottom row: rank correlation and IC retention,
    grouped bars by lookback.
    """
    regimes = list(sweep_df["regime"].unique())
    n = len(regimes)
    fig, axes = plt.subplots(2, n, figsize=(5 * n, 9), sharey="row")
    if n == 1:
        axes = axes.reshape(2, 1)

    for i, regime in enumerate(regimes):
        # Top: IC by L
        ax = axes[0, i]
        sub = sweep_df[sweep_df["regime"] == regime]
        for cs, marker, color in [
            ("standalone", "o", "#1f77b4"),
            ("orthog", "s", "#ff7f0e"),
        ]:
            sub_cs = sub[sub["control_set"] == cs].sort_values("lookback_d")
            if len(sub_cs) == 0:
                continue
            yerr_lo = (sub_cs["ic_mean"] - sub_cs["ic_ci_low"]).values
            yerr_hi = (sub_cs["ic_ci_high"] - sub_cs["ic_mean"]).values
            ax.errorbar(
                sub_cs["lookback_d"], sub_cs["ic_mean"],
                yerr=[yerr_lo, yerr_hi],
                fmt=marker + "-", color=color, label=cs, capsize=4,
            )
        ax.axhline(0, color="black", linewidth=0.5, alpha=0.5)
        ax.set_title(regime)
        if i == 0:
            ax.set_ylabel("Mean Spearman IC")
        ax.set_xlabel("Lookback L (days, skip-1)")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

        # Bottom: orthogonality
        ax = axes[1, i]
        sub_d = diag_df[diag_df["regime"] == regime].sort_values("lookback_d")
        if len(sub_d) > 0:
            ax.bar(
                sub_d["lookback_d"] - 0.7, sub_d["mean_rank_corr"],
                width=1.4, color="#1f77b4",
                label="Mean rank corr",
            )
            ax2 = ax.twinx()
            ax2.bar(
                sub_d["lookback_d"] + 0.7, sub_d["ic_retention_pct"],
                width=1.4, color="#ff7f0e",
                label="IC retention %",
            )
            ax.axhline(0.3, color="red", linewidth=0.6,
                       linestyle=":", alpha=0.6)
            ax.axhline(0.5, color="darkred", linewidth=0.6,
                       linestyle="--", alpha=0.6)
            if i == 0:
                ax.set_ylabel("Mean rank corr (vs z_turnover_resid)")
            if i == n - 1:
                ax2.set_ylabel("IC retention orthog/standalone (%)")
            ax.set_xlabel("Lookback L (days)")
            lines, labels = ax.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax.legend(lines + lines2, labels + labels2,
                      fontsize=8, loc="best")
            ax.grid(alpha=0.3)

    fig.suptitle("Reversal Phase 1 sweep: lookback × control × regime",
                 y=1.00)
    fig.tight_layout()
    fig.savefig(SWEEP_PLOT_OUT, dpi=120)
    plt.close(fig)
    print(f"  multi-regime sweep plot saved to {SWEEP_PLOT_OUT}")


# ═══════════════════════════════════════════════════════════════════════
# Step 4: Phase 2 (T+1 daily backtest, single config)
# ═══════════════════════════════════════════════════════════════════════
#
# Helpers below copied from turnover_neutralized.py rather than imported,
# to avoid reaching into private (underscore-prefixed) names of another
# module. If we end up needing this in a third script, we should refactor
# into a shared backtest_utils module.

def _read_daily_prices(date_str: str) -> pd.DataFrame | None:
    path = DAILY_PANEL_DIR / f"daily_{date_str}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df = df[df["ts_code"].str.match(A_SHARE_PATTERN)]
    keep = ["ts_code", "open", "close", "pre_close", "adj_factor"]
    df = df[[c for c in keep if c in df.columns]].copy()
    for c in ("open", "close", "pre_close", "adj_factor"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close", "adj_factor"])
    df = df[df["close"] > 0]
    df["adj_close"] = df["close"] * df["adj_factor"]
    if "open" in df.columns:
        df["adj_open"] = df["open"] * df["adj_factor"]
    return df.set_index("ts_code")


def _basket_for_date(trade_date, rebal_dates_sorted, baskets):
    import bisect
    idx = bisect.bisect_right(rebal_dates_sorted, trade_date) - 1
    if idx < 0:
        return None
    return baskets[rebal_dates_sorted[idx]]


def _build_baskets_from_z(panel: pd.DataFrame, z_col: str) -> dict:
    """Per-rebalance quintile baskets sorted on z_col."""
    iu = panel[panel["in_universe"]].copy()
    iu = iu.dropna(subset=[z_col])
    iu["quintile"] = iu.groupby("rebalance_date")[z_col].transform(
        lambda s: pd.qcut(s, N_QUINTILES, labels=False, duplicates="drop")
    )
    baskets: dict = {}
    for date, g in iu.groupby("rebalance_date"):
        baskets[date] = {
            "q5": set(g.loc[g["quintile"] == N_QUINTILES - 1, "ts_code"]),
            "q1": set(g.loc[g["quintile"] == 0, "ts_code"]),
            "universe": set(g["ts_code"]),
        }
    return baskets


def run_phase2_for_config(
    panel: pd.DataFrame,
    lookback: int,
    orthog: bool,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """
    T+1 daily backtest for one config. Returns (daily_df, z_col).
    """
    set_tag = "orthog" if orthog else "resid"
    z_col = f"z_reversal_{set_tag}_{lookback}d"

    if z_col not in panel.columns:
        if orthog and "z_turnover_resid" not in panel.columns:
            panel = add_z_turnover_resid(panel, with_beta=False)
        panel, _ = add_z_reversal_resid(panel, lookback, orthog)

    print("\n" + "=" * 76)
    print(f"PHASE 2: T+1 daily backtest on {z_col}")
    print("=" * 76)

    print(f"\nBuilding baskets on {z_col}...")
    baskets = _build_baskets_from_z(panel, z_col)
    rebal_dates_sorted = sorted(baskets.keys())
    print(f"  {len(rebal_dates_sorted)} rebalance dates with valid baskets")
    q5_sizes = [len(baskets[d]["q5"]) for d in rebal_dates_sorted]
    q1_sizes = [len(baskets[d]["q1"]) for d in rebal_dates_sorted]
    print(f"  Q5 size: median {int(np.median(q5_sizes))}, "
          f"min {min(q5_sizes)}, max {max(q5_sizes)}")
    print(f"  Q1 size: median {int(np.median(q1_sizes))}, "
          f"min {min(q1_sizes)}, max {max(q1_sizes)}")

    cal = pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()
    first_idx = cal.index(rebal_dates_sorted[0]) + 1
    last_idx = min(cal.index(rebal_dates_sorted[-1]) + 5, len(cal) - 1)
    trade_dates = cal[first_idx:last_idx + 1]
    if start_date:
        trade_dates = [d for d in trade_dates if d >= start_date]
    if end_date:
        trade_dates = [d for d in trade_dates if d <= end_date]
    if not trade_dates:
        raise RuntimeError("No trade dates after start/end filtering.")
    print(f"\nBacktest range: {trade_dates[0]} to {trade_dates[-1]} "
          f"({len(trade_dates)} trading days)")

    first_day_of_period = {}
    for r in rebal_dates_sorted:
        if r not in cal:
            continue
        ridx = cal.index(r)
        if ridx + 1 < len(cal):
            first_day_of_period[cal[ridx + 1]] = True

    print(f"\nIterating over trading days...")
    rows = []
    n_failed = 0
    t0 = time.time()
    prev_prices = None

    for i, td in enumerate(trade_dates, 1):
        prices = _read_daily_prices(td)
        if prices is None:
            n_failed += 1
            prev_prices = None
            continue
        basket = _basket_for_date(td, rebal_dates_sorted, baskets)
        if basket is None:
            prev_prices = prices
            continue
        is_first = first_day_of_period.get(td, False)

        for strat, members, sign in [
            ("q5_long", basket["q5"], +1),
            ("q1_short", basket["q1"], -1),
            ("universe_ew", basket["universe"], +1),
        ]:
            if not members:
                continue
            present = prices.index.intersection(members)
            if len(present) == 0:
                continue
            sub = prices.loc[present]

            # c2c
            if prev_prices is not None:
                pp = prev_prices.index.intersection(present)
                if len(pp) > 0:
                    p_prev = prev_prices.loc[pp, "adj_close"]
                    p_curr = sub.loc[pp, "adj_close"]
                    ret = (p_curr / p_prev - 1).mean() * sign
                    rows.append({
                        "trade_date": td, "strategy": strat,
                        "convention": "c2c", "daily_return": float(ret),
                        "n_held": int(len(pp)),
                    })

            # open_t1
            if "adj_open" in sub.columns:
                if is_first:
                    valid = sub["adj_open"].notna() & (sub["adj_open"] > 0)
                    if valid.sum() > 0:
                        sv = sub[valid]
                        ret = (sv["adj_close"] / sv["adj_open"] - 1).mean() * sign
                        rows.append({
                            "trade_date": td, "strategy": strat,
                            "convention": "open_t1", "daily_return": float(ret),
                            "n_held": int(valid.sum()),
                        })
                else:
                    if prev_prices is not None:
                        pp = prev_prices.index.intersection(present)
                        if len(pp) > 0:
                            p_prev = prev_prices.loc[pp, "adj_close"]
                            p_curr = sub.loc[pp, "adj_close"]
                            ret = (p_curr / p_prev - 1).mean() * sign
                            rows.append({
                                "trade_date": td, "strategy": strat,
                                "convention": "open_t1", "daily_return": float(ret),
                                "n_held": int(len(pp)),
                            })
        prev_prices = prices

        if i % 200 == 0 or i == len(trade_dates):
            print(f"  [{i:>4}/{len(trade_dates)}] failed={n_failed} "
                  f"rows={len(rows):,} elapsed={time.time()-t0:.1f}s")

    daily = pd.DataFrame(rows)
    pivot = daily.pivot_table(
        index=["trade_date", "convention"], columns="strategy",
        values="daily_return",
    ).reset_index()
    if "q5_long" in pivot.columns and "q1_short" in pivot.columns:
        pivot["long_short"] = 0.5 * pivot["q5_long"] + 0.5 * pivot["q1_short"]
    long_format = pivot.melt(
        id_vars=["trade_date", "convention"],
        value_vars=[c for c in pivot.columns
                    if c not in ("trade_date", "convention")],
        var_name="strategy", value_name="daily_return",
    ).dropna(subset=["daily_return"])

    daily_path = DATA_DIR / f"reversal_phase2_daily_{z_col}.csv"
    long_format.to_csv(daily_path, index=False)
    print(f"\nDaily P&L: {len(long_format):,} rows, saved to {daily_path}")

    return long_format, z_col


def summarise_phase2(daily: pd.DataFrame, z_col: str) -> pd.DataFrame:
    print("\n" + "=" * 76)
    print(f"PHASE 2 SUMMARY: {z_col}")
    print("=" * 76)
    rows = []
    for (strat, conv), g in daily.groupby(["strategy", "convention"]):
        r = g.sort_values("trade_date")["daily_return"].dropna()
        n = len(r)
        if n == 0:
            continue
        cum = (1 + r).cumprod()
        years = n / TRADING_DAYS_PER_YEAR
        ann_ret = cum.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
        std = r.std()
        sharpe = (
            r.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR)
            if std > 0 else np.nan
        )
        running_max = cum.cummax()
        max_dd = (cum / running_max - 1).min()
        hit = (r > 0).mean()

        if n >= 2 * DAILY_BLOCK_SIZE:
            def _sh(a):
                m, s = a.mean(), a.std()
                return m / s * np.sqrt(TRADING_DAYS_PER_YEAR) if s > 0 else np.nan
            boot = block_bootstrap_ci(
                r.values, _sh, block_size=DAILY_BLOCK_SIZE,
                n_boot=BOOT_N, seed=SEED,
            )
            ci_low, ci_high = boot["ci_low"], boot["ci_high"]
        else:
            ci_low = ci_high = np.nan

        rows.append({
            "strategy": strat, "convention": conv, "n_days": n,
            "ann_return_pct": ann_ret * 100,
            "ann_vol_pct": std * np.sqrt(TRADING_DAYS_PER_YEAR) * 100,
            "sharpe": sharpe,
            "sharpe_ci_low": ci_low, "sharpe_ci_high": ci_high,
            "cumulative_return_pct": (cum.iloc[-1] - 1) * 100,
            "max_drawdown_pct": max_dd * 100,
            "hit_rate_pct": hit * 100,
        })

    out = pd.DataFrame(rows).sort_values(["convention", "strategy"])
    print("\n" + out.round(3).to_string(index=False))
    summary_path = DATA_DIR / f"reversal_phase2_summary_{z_col}.csv"
    out.to_csv(summary_path, index=False)
    print(f"\nSaved to {summary_path}")
    return out


# ═══════════════════════════════════════════════════════════════════════
# Comparison plot
# ═══════════════════════════════════════════════════════════════════════

def plot_phase2_comparison(daily: pd.DataFrame, z_col: str) -> None:
    """Overlay reversal Q5 vs turnover-residualized Q5 vs benchmark."""
    turn_path = DATA_DIR / "turnover_neutralized_phase2_daily_pnl.csv"
    if not turn_path.exists():
        print(f"  (skipping comparison plot: {turn_path} not found)")
        return

    turn = pd.read_csv(turn_path)
    turn["daily_return"] = pd.to_numeric(turn["daily_return"], errors="coerce")
    turn["trade_date_ts"] = pd.to_datetime(turn["trade_date"].astype(str))

    daily = daily.copy()
    daily["daily_return"] = pd.to_numeric(daily["daily_return"], errors="coerce")
    daily["trade_date_ts"] = pd.to_datetime(daily["trade_date"].astype(str))

    fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    for ax, conv, title in zip(
        axes, ["c2c", "open_t1"],
        ["Close-to-close", "Open-T+1"],
    ):
        # Reversal Q5
        rsub = daily[
            (daily["convention"] == conv) & (daily["strategy"] == "q5_long")
        ]
        if len(rsub):
            r = rsub.sort_values("trade_date_ts")
            cum = (1 + r["daily_return"].fillna(0)).cumprod()
            ax.plot(r["trade_date_ts"], cum,
                    label=f"Q5 reversal ({z_col})",
                    color="#2ca02c", linewidth=1.5)

        # Turnover-residualized Q5
        tsub = turn[
            (turn["convention"] == conv) & (turn["strategy"] == "q5_long")
        ]
        if len(tsub):
            t = tsub.sort_values("trade_date_ts")
            cum = (1 + t["daily_return"].fillna(0)).cumprod()
            ax.plot(t["trade_date_ts"], cum,
                    label="Q5 turnover (residualized)",
                    color="#ff7f0e", linewidth=1.5)

        # Benchmark
        bsub = turn[
            (turn["convention"] == conv) & (turn["strategy"] == "universe_ew")
        ]
        if len(bsub):
            b = bsub.sort_values("trade_date_ts")
            cum = (1 + b["daily_return"].fillna(0)).cumprod()
            ax.plot(b["trade_date_ts"], cum, label="Universe EW",
                    color="#888888", linewidth=1.2, linestyle="--")

        ax.axvline(NEW_NINE_ARTICLES_DATE, color="firebrick",
                   linestyle="--", alpha=0.4)
        ax.axvline(PBOC_STIMULUS_DATE, color="seagreen",
                   linestyle="--", alpha=0.4)
        ax.set_title(title)
        ax.set_xlabel("Trade date")
        ax.set_ylabel("Cumulative return (×)" if ax == axes[0] else "")
        ax.legend(loc="upper left", fontsize=10)
        ax.grid(alpha=0.3)

    fig.suptitle(f"Reversal vs turnover (residualized) Q5: {z_col}", y=1.00)
    fig.tight_layout()
    out = GRAPHS_DIR / f"reversal_phase2_{z_col}_compare.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"  comparison plot saved to {out}")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Short-term reversal factor analysis on Universe A."
    )
    ap.add_argument("mode", choices=["phase1", "phase2", "both", "sweep"])
    ap.add_argument(
        "--lookback", type=int, default=5,
        help=f"Past-return lookback in trading days (skip-1 applied). "
             f"Sensible values: {list(LOOKBACKS_DEFAULT)}. "
             f"Used in phase1/phase2/both modes; ignored in sweep.",
    )
    ap.add_argument(
        "--orthog", action="store_true",
        help="Use turnover-orthogonal control set "
             "(sector + log_mcap + z_turnover_resid). "
             "Default is standalone (sector + log_mcap).",
    )
    ap.add_argument("--start", type=str, default=None,
                    help="Date filter (YYYY-MM-DD). In sweep mode: defines a "
                         "custom window (overrides --regime). In phase2/both "
                         "mode: filters the backtest range, e.g. 2024-04-12 "
                         "to start at the γ window.")
    ap.add_argument("--end", type=str, default=None,
                    help="Date filter (YYYY-MM-DD). Inclusive upper bound.")
    ap.add_argument(
        "--regime",
        choices=["alpha", "beta", "gamma", "all"],
        default="all",
        help="Sweep mode only. 'all' iterates the three predefined regimes "
             "(alpha = full panel, beta = pre-新国九条, gamma = post-新国九条). "
             "Single-regime values run only that window. Overridden by "
             "--start/--end if either is provided. Default: all.",
    )
    args = ap.parse_args()

    # Setup: panel + sector + past returns
    panel = load_panel_with_sector()
    past = compute_past_returns_panel(panel, lookbacks=LOOKBACKS_DEFAULT)
    panel = panel.merge(past, on=["rebalance_date", "ts_code"], how="left")

    if args.mode == "sweep":
        if args.start is not None or args.end is not None:
            label = (
                f"custom_{args.start or 'open'}_to_{args.end or 'open'}"
            )
            print(f"\n  Running custom window: {args.start} → {args.end} "
                  f"(label: {label})")
            run_phase1_sweep_multi_regime(
                panel, lookbacks=LOOKBACKS_DEFAULT,
                custom_window=(args.start, args.end, label),
            )
        elif args.regime == "all":
            run_phase1_sweep_multi_regime(
                panel, lookbacks=LOOKBACKS_DEFAULT,
            )
        else:
            full_key = REGIME_KEY_MAP[args.regime]
            start, end = THREE_REGIME_WINDOWS[full_key]
            run_phase1_sweep_multi_regime(
                panel, lookbacks=LOOKBACKS_DEFAULT,
                custom_window=(start, end, full_key),
            )
        print("\nDone.")
        return

    # Single-config modes
    if args.orthog and "z_turnover_resid" not in panel.columns:
        panel = add_z_turnover_resid(panel, with_beta=False)

    set_tag = "orthog" if args.orthog else "resid"
    z_col = f"z_reversal_{set_tag}_{args.lookback}d"

    if args.mode in ("phase1", "both"):
        save_csv = DATA_DIR / f"reversal_phase1_{z_col}.csv"
        s = run_phase1_for_config(
            panel, args.lookback, args.orthog, save_csv=save_csv
        )
        panel = s["panel"]

    if args.mode in ("phase2", "both"):
        if z_col not in panel.columns:
            panel, _ = add_z_reversal_resid(
                panel, args.lookback, args.orthog
            )
        daily, z_col_used = run_phase2_for_config(
            panel, args.lookback, args.orthog,
            start_date=args.start, end_date=args.end,
        )
        summarise_phase2(daily, z_col_used)
        plot_phase2_comparison(daily, z_col_used)

    print("\nDone.")


if __name__ == "__main__":
    main()