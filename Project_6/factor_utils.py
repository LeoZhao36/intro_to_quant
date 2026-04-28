"""
factor_utils.py

Project 6: shared utilities for factor analysis. Used by per-factor
analysis scripts (size_analysis.py, value_analysis.py, ...) so that
all factors flow through identical machinery.

Replaces the factor-specific logic that previously lived inline in
size_pipeline.py, size_robustness.py, and size_robustness_pass2.py.
Those three scripts had `"log_mcap"` hardcoded throughout. Here the
factor column is a parameter (`factor_col`) passed by the caller.

Contents
--------
Constants
  DATA_DIR, UNIVERSE_PATH, RETURN_PATH, SECTOR_PATH
  REGIME_EVENTS, REGIME_SPLIT_DATE
  SEED, MIN_STOCKS_PER_SECTOR

Data loading
  load_panel()         : merged in-universe panel with log_mcap
  load_sector_map()    : SW L1 sector mapping

Core analysis
  compute_quintile_series(panel, sort_col, return_col)
  compute_ic_series(panel, sort_col, return_col)
  summarise_long_short(qr, label)

Pass 1 robustness
  layer_1_bootstrap_ci(panel, factor_col)
  layer_2_regime_split(panel, factor_col)
  layer_3_tradable_only(panel, factor_col)

Pass 2 robustness
  layer_4_sector_neutral(panel, factor_col)
  layer_5_cap_terciles(panel, factor_col, cap_col)

Helpers
  residualise_factor_per_date(panel, factor_col, sector_col, output_col)
  benjamini_hochberg(p_values, alpha)

Plotting
  plot_cumulative_quintiles(quintile_returns, factor_label, save_path)
  plot_ic_series(ic_series, factor_label, save_path)

Multi-test correction policy (locked at Session 1)
  Holm-Bonferroni for the family of factor headlines (across factors).
  Benjamini-Hochberg for within-factor robustness families. This module
  exposes benjamini_hochberg() and assumes HB will be applied externally
  on the family of factor headlines.

Design notes
  - Layer 5 uses `cap_col` separately from `factor_col` because the
    conditioning question ("does the factor work in low/mid/high cap
    stocks") is always defined on market cap. For size, cap_col ==
    factor_col == 'log_mcap'. For other factors, factor_col is whatever
    is under test ('ep', 'momentum_12_1', ...) while cap_col stays
    'log_mcap'.
  - load_panel() universally adds 'log_mcap' so Layer 5 can use it
    regardless of which factor is being analysed.
"""

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hypothesis_testing import block_bootstrap_ci


# ─── Constants ──────────────────────────────────────────────────────────

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

DATA_DIR = Path("data")
UNIVERSE_PATH = DATA_DIR / "universe_membership.csv"
RETURN_PATH = DATA_DIR / "forward_return_panel.csv"
SECTOR_PATH = DATA_DIR / "sw_membership.csv"

REGIME_EVENTS = {
    "雪球 meltdown": pd.Timestamp("2024-01-15"),
    "新国九条": pd.Timestamp("2024-03-15"),
    "PBoC stimulus": pd.Timestamp("2024-09-18"),
}
REGIME_SPLIT_DATE = pd.Timestamp("2024-09-18")  # PBoC stimulus

SEED = 42
MIN_STOCKS_PER_SECTOR = 5  # collapse smaller sectors into 'other' before regression


# ─── Data loading ───────────────────────────────────────────────────────

def load_panel() -> pd.DataFrame:
    """
    Load Project 5's CSVs and return the merged in-universe panel with
    log_mcap pre-computed.

    log_mcap is added universally because Layer 5 (cap-tercile conditioning)
    always uses log_mcap as the conditioning variable, regardless of which
    factor is being tested.

    Returns
    -------
    DataFrame with columns:
      rebalance_date, ts_code, in_universe, mean_amount_wan, circ_mv_yi,
      rank_by_mcap, log_mcap, forward_return, entry_tradable, exit_tradable.
    """
    universe = pd.read_csv(
        UNIVERSE_PATH,
        parse_dates=["rebalance_date"],
        dtype={"ts_code": str, "in_universe": bool},
    )
    returns = pd.read_csv(
        RETURN_PATH,
        parse_dates=["rebalance_date"],
        dtype={"ts_code": str, "entry_tradable": bool, "exit_tradable": bool},
    )
    universe_in = universe[universe["in_universe"]].copy()
    universe_in["log_mcap"] = np.log(universe_in["circ_mv_yi"])
    panel = universe_in.merge(returns, on=["rebalance_date", "ts_code"], how="left")
    return panel


def load_sector_map() -> Optional[pd.DataFrame]:
    """
    Load the SW L1 sector mapping. Returns a DataFrame with columns
    ts_code, l1_code, l1_name. Returns None if the file is missing.
    """
    if not SECTOR_PATH.exists():
        return None
    df = pd.read_csv(SECTOR_PATH, dtype=str)
    if "ts_code" not in df.columns or "l1_code" not in df.columns:
        print(f"  Warning: sw_membership.csv lacks expected columns. Got: {list(df.columns)}")
        return None
    return df[["ts_code", "l1_code", "l1_name"]].drop_duplicates(subset=["ts_code"])


# ─── Core analysis ──────────────────────────────────────────────────────

def compute_quintile_series(
    panel: pd.DataFrame,
    sort_col: str = "log_mcap",
    return_col: str = "forward_return",
) -> pd.DataFrame:
    """
    Sort `panel` into 5 quintiles per rebalance_date by `sort_col`, then
    compute the mean `return_col` per (date, quintile) cell. Returns a
    wide-format DataFrame indexed by date with columns 0..4.

    Q1 (smallest sort_col) = column 0, Q5 (largest) = column 4.
    duplicates="drop" handles the rare case of identical sort_col values
    at quintile boundaries by collapsing duplicate edges instead of raising.
    """
    df = panel.copy()
    df["quintile"] = (
        df.groupby("rebalance_date")[sort_col]
        .transform(lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
    )
    return (
        df.groupby(["rebalance_date", "quintile"])[return_col]
        .mean()
        .unstack()
    )


def compute_ic_series(
    panel: pd.DataFrame,
    sort_col: str = "log_mcap",
    return_col: str = "forward_return",
) -> pd.Series:
    """Cross-sectional Spearman rank IC per rebalance_date."""
    return (
        panel.dropna(subset=[return_col, sort_col])
        .groupby("rebalance_date")
        .apply(
            lambda g: g[sort_col].corr(g[return_col], method="spearman"),
            include_groups=False,
        )
        .dropna()
    )


def summarise_long_short(qr: pd.DataFrame, label: str) -> dict:
    """
    Compute Q1-Q5 mean, std, t-stat, naive Sharpe; print a one-line
    summary; return a dict with the underlying ls_series for downstream
    bootstrap.
    """
    if 0 not in qr.columns or 4 not in qr.columns:
        return {"label": label, "n": 0}
    ls = (qr[0] - qr[4]).dropna()
    if len(ls) < 2:
        return {"label": label, "n": int(len(ls))}
    mean = float(ls.mean())
    std = float(ls.std())
    t_stat = mean / (std / np.sqrt(len(ls))) if std > 0 else np.nan
    sharpe = mean / std * np.sqrt(12) if std > 0 else np.nan
    summary = {
        "label": label,
        "n": int(len(ls)),
        "mean_monthly": mean,
        "std_monthly": std,
        "t_stat": float(t_stat),
        "naive_sharpe": float(sharpe),
        "ls_series": ls,
    }
    print(
        f"  {label:<40s} n={summary['n']:3d}  "
        f"mean={mean*100:+.3f}%/mo  std={std*100:.3f}%  "
        f"t={t_stat:+.2f}  Sharpe={sharpe:+.2f}"
    )
    return summary


# ─── Pass 1 robustness layers ───────────────────────────────────────────

def layer_1_bootstrap_ci(panel: pd.DataFrame, factor_col: str) -> dict:
    """Layer 1: block bootstrap CI on Q1-Q5 mean and on mean IC."""
    print("\n" + "=" * 72)
    print(f"Layer 1: Block bootstrap CI on {factor_col} (block_size=3, n_boot=5000)")
    print("=" * 72)

    quintiles = compute_quintile_series(panel, sort_col=factor_col)
    ls = (quintiles[0] - quintiles[4]).dropna().values
    ic = compute_ic_series(panel, sort_col=factor_col).values

    ls_boot = block_bootstrap_ci(ls, np.mean, block_size=3, n_boot=5000, seed=SEED)
    ic_boot = block_bootstrap_ci(ic, np.mean, block_size=3, n_boot=5000, seed=SEED)

    print(
        f"  Q1-Q5 mean: {ls_boot['estimate']*100:+.3f}%/mo, "
        f"95% CI [{ls_boot['ci_low']*100:+.3f}%, {ls_boot['ci_high']*100:+.3f}%]"
    )
    print(
        f"  Mean IC:    {ic_boot['estimate']:+.4f},      "
        f"95% CI [{ic_boot['ci_low']:+.4f}, {ic_boot['ci_high']:+.4f}]"
    )
    ls_contains_zero = ls_boot["ci_low"] <= 0 <= ls_boot["ci_high"]
    ic_contains_zero = ic_boot["ci_low"] <= 0 <= ic_boot["ci_high"]
    print(
        f"  Q1-Q5 CI contains zero: {ls_contains_zero}   "
        f"IC CI contains zero: {ic_contains_zero}"
    )
    return {"ls_boot": ls_boot, "ic_boot": ic_boot}


def layer_2_regime_split(panel: pd.DataFrame, factor_col: str) -> dict:
    """Layer 2: split panel at REGIME_SPLIT_DATE and re-run on each sub-period."""
    print("\n" + "=" * 72)
    print(f"Layer 2: Regime split at {REGIME_SPLIT_DATE.date()} (PBoC stimulus)")
    print("=" * 72)

    pre_panel = panel[panel["rebalance_date"] < REGIME_SPLIT_DATE]
    post_panel = panel[panel["rebalance_date"] >= REGIME_SPLIT_DATE]
    print(
        f"  Pre  ({pre_panel['rebalance_date'].min().date()} to "
        f"{pre_panel['rebalance_date'].max().date()}): "
        f"{pre_panel['rebalance_date'].nunique()} dates"
    )
    print(
        f"  Post ({post_panel['rebalance_date'].min().date()} to "
        f"{post_panel['rebalance_date'].max().date()}): "
        f"{post_panel['rebalance_date'].nunique()} dates"
    )
    print()

    out = {}
    for name, p in [("pre-stimulus", pre_panel), ("post-stimulus", post_panel)]:
        quintiles = compute_quintile_series(p, sort_col=factor_col)
        summary = summarise_long_short(quintiles, name)
        if summary.get("n", 0) >= 6:
            boot = block_bootstrap_ci(
                summary["ls_series"].values,
                np.mean, block_size=3, n_boot=5000, seed=SEED,
            )
            print(
                f"    bootstrap 95% CI: "
                f"[{boot['ci_low']*100:+.3f}%, {boot['ci_high']*100:+.3f}%]"
            )
            summary["bootstrap"] = boot
        out[name] = summary
    return out


def layer_3_tradable_only(panel: pd.DataFrame, factor_col: str) -> dict:
    """Layer 3: filter to entry_tradable AND exit_tradable, re-run."""
    print("\n" + "=" * 72)
    print("Layer 3: Tradable-only filter (entry_tradable AND exit_tradable)")
    print("=" * 72)

    n_total = len(panel)
    tradable_mask = panel["entry_tradable"].fillna(False) & panel["exit_tradable"].fillna(False)
    n_tradable = int(tradable_mask.sum())
    n_dropped = n_total - n_tradable
    print(
        f"  Rows: {n_total:,} total, {n_tradable:,} tradable, "
        f"{n_dropped:,} dropped ({n_dropped / n_total * 100:.2f}%)"
    )

    panel_tradable = panel[tradable_mask].copy()
    quintiles = compute_quintile_series(panel_tradable, sort_col=factor_col)
    summary = summarise_long_short(quintiles, "tradable-only Q1-Q5")
    if summary.get("n", 0) >= 6:
        boot = block_bootstrap_ci(
            summary["ls_series"].values,
            np.mean, block_size=3, n_boot=5000, seed=SEED,
        )
        print(
            f"    bootstrap 95% CI: "
            f"[{boot['ci_low']*100:+.3f}%, {boot['ci_high']*100:+.3f}%]"
        )
        summary["bootstrap"] = boot
    return summary


# ─── Pass 2 robustness layers ───────────────────────────────────────────

def residualise_factor_per_date(
    panel: pd.DataFrame,
    factor_col: str,
    sector_col: str,
    output_col: Optional[str] = None,
    min_stocks_per_sector: int = MIN_STOCKS_PER_SECTOR,
) -> pd.DataFrame:
    """
    Per rebalance_date, regress factor_col on sector dummies and add a
    residual column to the returned DataFrame.

    Sectors with fewer than min_stocks_per_sector stocks at a given date
    are collapsed into 'other' before the regression to avoid singular
    dummy matrices.

    Parameters
    ----------
    panel : DataFrame with rebalance_date, factor_col, sector_col.
    factor_col : column name to residualise (e.g. 'log_mcap', 'ep').
    sector_col : column name with sector code (e.g. 'l1_code').
    output_col : name for the residual column. Default: f'{factor_col}_resid'.
    min_stocks_per_sector : sector size threshold for 'other' collapse.

    Returns
    -------
    DataFrame with the residual column appended.
    """
    if output_col is None:
        output_col = f"{factor_col}_resid"

    df = panel.reset_index(drop=True).copy()
    out_residuals = np.full(len(df), np.nan)

    for date, group in df.groupby("rebalance_date"):
        idx = group.index.to_numpy()
        sector_counts = group[sector_col].value_counts()
        small_sectors = sector_counts[sector_counts < min_stocks_per_sector].index
        sectors_clean = group[sector_col].where(
            ~group[sector_col].isin(small_sectors), "other"
        )

        dummies = pd.get_dummies(sectors_clean, drop_first=True, dtype=float)
        if dummies.shape[1] == 0:
            # Only one sector at this date; residual is just demeaned factor.
            y = group[factor_col].values
            resid = y - y.mean()
        else:
            X = np.column_stack([np.ones(len(group)), dummies.values])
            y = group[factor_col].values
            beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
        out_residuals[idx] = resid

    df[output_col] = out_residuals
    return df


def layer_4_sector_neutral(panel: pd.DataFrame, factor_col: str) -> Optional[dict]:
    """
    Layer 4: residualise factor_col on SW L1 sector dummies per date,
    then re-run the Q1-Q5 sort on residuals.

    Asks: does factor_col predict returns AFTER stripping out sector
    composition?
    """
    print("\n" + "=" * 72)
    print(f"Layer 4: Sector neutralisation on {factor_col} (SW L1, static mapping)")
    print("=" * 72)

    sector_map = load_sector_map()
    if sector_map is None:
        print(f"  Sector mapping not found at {SECTOR_PATH}. Skipping Layer 4.")
        print(f"  Place sw_membership.csv in {DATA_DIR}/ to enable.")
        return None

    panel_sec = panel.merge(sector_map, on="ts_code", how="left")
    n_total = len(panel_sec)
    n_unmapped = panel_sec["l1_code"].isna().sum()
    pct_unmapped = n_unmapped / n_total * 100
    print(
        f"  Sector merge: {n_total:,} rows, {n_unmapped:,} unmapped ({pct_unmapped:.2f}%)"
    )

    if pct_unmapped > 5:
        print(
            f"  Warning: {pct_unmapped:.1f}% of rows have no sector mapping. "
            f"Layer 4 results condition on the {100-pct_unmapped:.1f}% that do."
        )
    panel_sec = panel_sec.dropna(subset=["l1_code"]).copy()

    n_unique_sectors = panel_sec["l1_code"].nunique()
    sector_counts_per_date = panel_sec.groupby("rebalance_date")["l1_code"].nunique()
    print(
        f"  Unique sectors in merged panel: {n_unique_sectors}; "
        f"sectors-per-date min/max/median: "
        f"{sector_counts_per_date.min()}/{sector_counts_per_date.max()}/"
        f"{int(sector_counts_per_date.median())}"
    )

    print(f"  Computing sector residuals on {factor_col} per date (this may take ~5-10s)...")
    resid_col = f"{factor_col}_resid"
    panel_resid = residualise_factor_per_date(
        panel_sec, factor_col, "l1_code", output_col=resid_col,
    )

    resid_mean_check = (
        panel_resid.groupby("rebalance_date")[resid_col].mean().abs().max()
    )
    print(f"  Residual sanity: max |mean(resid)| across dates = {resid_mean_check:.2e}")

    quintiles = compute_quintile_series(panel_resid, sort_col=resid_col)
    summary = summarise_long_short(quintiles, f"sector-neutral {factor_col} Q1-Q5")
    if summary.get("n", 0) >= 6:
        boot = block_bootstrap_ci(
            summary["ls_series"].values,
            np.mean, block_size=3, n_boot=5000, seed=SEED,
        )
        print(
            f"    bootstrap 95% CI: "
            f"[{boot['ci_low']*100:+.3f}%, {boot['ci_high']*100:+.3f}%]"
        )
        contains_zero = boot["ci_low"] <= 0 <= boot["ci_high"]
        print(f"    CI contains zero: {contains_zero}")
        summary["bootstrap"] = boot

    return summary


def benjamini_hochberg(p_values: list, alpha: float = 0.05) -> list:
    """
    BH step-up procedure. Returns boolean list aligned with p_values:
    True where the corresponding test should be rejected.
    """
    n = len(p_values)
    if n == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    threshold_index = -1
    for rank, (orig_i, p) in enumerate(indexed, start=1):
        if p <= (rank / n) * alpha:
            threshold_index = rank
    rejected = [False] * n
    if threshold_index > 0:
        for orig_i, p in indexed[:threshold_index]:
            rejected[orig_i] = True
    return rejected


def layer_5_cap_terciles(
    panel: pd.DataFrame,
    factor_col: str,
    cap_col: str = "log_mcap",
) -> dict:
    """
    Layer 5: split universe into low/mid/high cap_col terciles per date,
    run Q1-Q5 on factor_col within each tercile, BH-correct the family.

    Asks: does factor_col behave the same way across the cap distribution,
    or does the relationship differ at different cap levels?

    For size-factor analysis, cap_col == factor_col == 'log_mcap'.
    For other factors, cap_col stays 'log_mcap' (cap is the conditioning
    variable, always defined on market cap) while factor_col is the
    factor under test (e.g. 'ep').
    """
    print("\n" + "=" * 72)
    print(
        f"Layer 5: Cap-tercile conditioning (BH-corrected); "
        f"factor={factor_col}, cap={cap_col}"
    )
    print("=" * 72)

    df = panel.copy()
    df["cap_tercile"] = (
        df.groupby("rebalance_date")[cap_col]
        .transform(
            lambda s: pd.qcut(s, 3, labels=["low", "mid", "high"], duplicates="drop")
        )
    )

    out = {}
    p_values = []
    labels = []

    for tercile_name in ["low", "mid", "high"]:
        sub = df[df["cap_tercile"] == tercile_name].copy()
        quintiles = compute_quintile_series(sub, sort_col=factor_col)
        summary = summarise_long_short(quintiles, f"cap-tercile {tercile_name}")
        if summary.get("n", 0) >= 6:
            boot = block_bootstrap_ci(
                summary["ls_series"].values,
                np.mean, block_size=3, n_boot=5000, seed=SEED,
            )
            null = boot["boot_distribution"] - boot["estimate"]
            p_two = float(np.mean(np.abs(null) >= abs(boot["estimate"])))
            print(
                f"    bootstrap 95% CI: "
                f"[{boot['ci_low']*100:+.3f}%, {boot['ci_high']*100:+.3f}%]   "
                f"bootstrap p-value: {p_two:.3f}"
            )
            summary["bootstrap"] = boot
            summary["p_value"] = p_two
            p_values.append(p_two)
            labels.append(tercile_name)
        out[tercile_name] = summary

    if len(p_values) >= 2:
        rejected = benjamini_hochberg(p_values, alpha=0.05)
        print("\n  BH-adjusted family of cap-tercile tests (alpha = 0.05):")
        for label, p, rej in zip(labels, p_values, rejected):
            verdict = "REJECT H0" if rej else "fail to reject"
            print(f"    {label:<5s}  p={p:.3f}  -> {verdict}")
    return out


# ─── Plotting ───────────────────────────────────────────────────────────

def plot_cumulative_quintiles(
    quintile_returns: pd.DataFrame,
    factor_label: str,
    save_path: Path,
    regime_events: dict = REGIME_EVENTS,
) -> None:
    """Plot cumulative monthly returns by quintile, with regime markers."""
    cum_returns = (1 + quintile_returns.fillna(0)).cumprod()

    fig, ax = plt.subplots(figsize=(11, 5.5))
    colors = plt.cm.RdYlBu_r(np.linspace(0.10, 0.90, 5))
    labels = {0: "Q1 (smallest)", 1: "Q2", 2: "Q3", 3: "Q4", 4: "Q5 (largest)"}

    for q in range(5):
        if q in cum_returns.columns:
            ax.plot(
                cum_returns.index,
                cum_returns[q],
                label=labels[q],
                color=colors[q],
                linewidth=1.6,
            )

    ymax = ax.get_ylim()[1]
    for label, event_date in regime_events.items():
        ax.axvline(event_date, color="grey", linestyle="--", alpha=0.55, linewidth=0.9)
        ax.text(
            event_date, ymax * 0.985, label,
            rotation=90, verticalalignment="top",
            fontsize=8, color="dimgrey",
        )

    ax.set_title(f"Cumulative monthly returns by {factor_label} quintile")
    ax.set_xlabel("Rebalance date")
    ax.set_ylabel("Cumulative return (×)")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_ic_series(
    ic_clean: pd.Series,
    factor_label: str,
    save_path: Path,
    regime_events: dict = REGIME_EVENTS,
) -> None:
    """Plot IC time series with mean line and regime markers."""
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.bar(ic_clean.index, ic_clean.values, width=20, alpha=0.70, color="steelblue")
    ax.axhline(0, color="black", linewidth=0.7)
    ax.axhline(
        ic_clean.mean(),
        color="firebrick", linestyle="--", alpha=0.85,
        label=f"Mean IC = {ic_clean.mean():+.4f}",
    )

    ymax = ax.get_ylim()[1]
    ymin = ax.get_ylim()[0]
    for label, event_date in regime_events.items():
        ax.axvline(event_date, color="grey", linestyle="--", alpha=0.55, linewidth=0.9)
        ax.text(
            event_date,
            ymax * 0.95 if ymax > abs(ymin) else ymin * 0.95,
            label,
            rotation=90,
            verticalalignment="top" if ymax > abs(ymin) else "bottom",
            fontsize=8, color="dimgrey",
        )

    ax.set_title(f"Cross-sectional Spearman IC: {factor_label} vs forward_return")
    ax.set_xlabel("Rebalance date")
    ax.set_ylabel("Spearman rank IC")
    ax.legend(loc="upper right", framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)
