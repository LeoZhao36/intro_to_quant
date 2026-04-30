"""
factor_utils.py — Core analysis machinery for weekly factor pipelines.

Contains the cross-sectional z-score utility, the per-date Q1-Q5 sort
and IC computation, the five robustness layers (Layer 3 is currently
deferred), sector residualization, BH multi-test correction, and
plotting helpers for cumulative quintile returns and IC time series.

All cadence-dependent constants flow from config.PERIODS_PER_YEAR=52.
Annualization uses sqrt(52). Block bootstrap uses block_size=12 (~quarterly
for weekly returns). Print labels say %/wk.

Architecture
------------
The factor panel produced by factor_panel_builder.py contains every
(rebalance_date, candidate_stock) pair, with in_universe set True/False.
Factor scripts compute signals on the FULL panel (so formation windows
have valid data even for stocks transitioning into the universe), then
filter to in_universe=True at the cross-sectional sort step.

compute_quintile_series() and compute_ic_series() apply the in_universe
filter internally. Callers pass the full panel without pre-filtering.

Layer machinery
---------------
Layer 1: Block bootstrap CI on Q1-Q5 mean and on mean IC.
Layer 2: Multi-candidate regime split. Runs pre/post analysis at each
         entry in config.CANDIDATE_SPLITS and reports all. The "best"
         split date is read off the results, not pre-fixed.
Layer 3: Tradable-only filter. DEFERRED until limit-state detection
         (open item 14) is built. Returns None and prints a notice.
Layer 4: Sector-neutral residualization on l1_name dummies, then re-sort.
Layer 5: Cap-tercile conditioning. BH-corrected family of three tests.

Multi-test correction policy (locked at Project 6 Session 1)
  - Holm-Bonferroni for the family of factor headlines (across factors).
  - Benjamini-Hochberg for within-factor robustness families.

Sign convention helper
----------------------
cross_sectional_zscore() applies winsorization at [1%, 99%] then
standardizes per date. The sign of the score reflects the raw factor's
direction; per-factor scripts apply the +/- sign to align with the
"positive => predicted to outperform" convention before regression.
"""

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hypothesis_testing import block_bootstrap_ci

from config import (
    ANNUAL_FACTOR_SQRT,
    BOOT_BLOCK_SIZE,
    BOOT_N,
    CANDIDATE_SPLITS,
    FACTOR_PANEL_PATH,
    GRAPHS_DIR,
    MIN_STOCKS_PER_SECTOR,
    PERIODS_PER_YEAR,
    REGIME_EVENTS,
    RETURN_LABEL,
    SEED,
)


# Matplotlib Chinese-character rendering. plot_setup.py centralizes this
# but importing here keeps factor_utils.py self-sufficient when called
# from a notebook.
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# ─── Z-score utility ────────────────────────────────────────────────────

def cross_sectional_zscore(
    panel: pd.DataFrame,
    factor_col: str,
    out_col: str,
    date_col: str = "rebalance_date",
    winsorize: bool = True,
    low: float = 0.01,
    high: float = 0.99,
) -> pd.DataFrame:
    """
    Add a per-date cross-sectional z-score column to `panel`.

    For each rebalance_date: optionally winsorize at [low, high] percentiles,
    then standardize to (x - mean) / std using cross-sectional moments,
    ignoring NaNs in the moment computation.

    Stocks with NaN factor_col remain NaN in out_col; the downstream
    quintile sort and IC calculation drop them naturally.

    Note on architecture: z-scoring uses ALL rows at a given date,
    including not-in-universe candidates. This matters for the multifactor
    pipeline where we want a stable cross-sectional reference for stocks
    that may transition in/out of the universe.
    """
    df = panel.copy()

    def _zscore(s: pd.Series) -> pd.Series:
        if winsorize:
            lo = s.quantile(low)
            hi = s.quantile(high)
            s = s.clip(lo, hi)
        mean = s.mean()
        std = s.std()
        if std == 0 or pd.isna(std):
            return pd.Series(np.nan, index=s.index)
        return (s - mean) / std

    df[out_col] = df.groupby(date_col)[factor_col].transform(_zscore)
    return df


# ─── Data loading ───────────────────────────────────────────────────────

def load_factor_panel() -> pd.DataFrame:
    """
    Load the cached factor panel produced by factor_panel_builder.py.
    Returns the full (rebalance_date, ts_code) panel including non-
    in-universe rows. Callers should NOT pre-filter; the layer functions
    apply in_universe filtering internally.
    """
    if not FACTOR_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"{FACTOR_PANEL_PATH} not found. "
            f"Run `python factor_panel_builder.py full` first."
        )
    panel = pd.read_parquet(FACTOR_PANEL_PATH)
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    return panel


# ─── Core analysis ──────────────────────────────────────────────────────

def compute_quintile_series(
    panel: pd.DataFrame,
    sort_col: str,
    return_col: str = "forward_return",
) -> pd.DataFrame:
    """
    Sort in-universe stocks into 5 quintiles per date by sort_col, return
    the mean return_col per (date, quintile). Returns wide DataFrame
    indexed by date with columns 0..4 (Q1..Q5).

    Q1 (smallest sort_col) = column 0, Q5 (largest) = column 4.
    """
    df = panel[panel["in_universe"]].copy()
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
    sort_col: str,
    return_col: str = "forward_return",
) -> pd.Series:
    """Cross-sectional Spearman rank IC per rebalance_date, in-universe only."""
    df = panel[panel["in_universe"]]
    return (
        df.dropna(subset=[return_col, sort_col])
        .groupby("rebalance_date")
        .apply(
            lambda g: g[sort_col].corr(g[return_col], method="spearman"),
            include_groups=False,
        )
        .dropna()
    )


def summarise_long_short(qr: pd.DataFrame, label: str) -> dict:
    """
    Compute Q1-Q5 mean, std, t-stat, naive Sharpe; print one-liner;
    return a dict with the underlying ls_series for downstream bootstrap.
    Annualization uses sqrt(PERIODS_PER_YEAR) per cadence config.
    """
    if 0 not in qr.columns or 4 not in qr.columns:
        return {"label": label, "n": 0}
    ls = (qr[0] - qr[4]).dropna()
    if len(ls) < 2:
        return {"label": label, "n": int(len(ls))}
    mean = float(ls.mean())
    std = float(ls.std())
    t_stat = mean / (std / np.sqrt(len(ls))) if std > 0 else np.nan
    sharpe = mean / std * ANNUAL_FACTOR_SQRT if std > 0 else np.nan
    summary = {
        "label": label,
        "n": int(len(ls)),
        "mean_period": mean,
        "std_period": std,
        "t_stat": float(t_stat),
        "naive_sharpe": float(sharpe),
        "ls_series": ls,
    }
    print(
        f"  {label:<40s} n={summary['n']:3d}  "
        f"mean={mean*100:+.3f}%/{RETURN_LABEL}  "
        f"std={std*100:.3f}%  "
        f"t={t_stat:+.2f}  Sharpe={sharpe:+.2f}"
    )
    return summary


# ─── Pass 1 robustness layers ───────────────────────────────────────────

def layer_1_bootstrap_ci(panel: pd.DataFrame, factor_col: str) -> dict:
    """Layer 1: block bootstrap CI on Q1-Q5 mean and on mean IC."""
    print("\n" + "=" * 72)
    print(f"Layer 1: Block bootstrap CI on {factor_col} "
          f"(block_size={BOOT_BLOCK_SIZE}, n_boot={BOOT_N:,})")
    print("=" * 72)

    quintiles = compute_quintile_series(panel, sort_col=factor_col)
    ls = (quintiles[0] - quintiles[4]).dropna().values
    ic = compute_ic_series(panel, sort_col=factor_col).values

    ls_boot = block_bootstrap_ci(
        ls, np.mean,
        block_size=BOOT_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
    )
    ic_boot = block_bootstrap_ci(
        ic, np.mean,
        block_size=BOOT_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
    )

    print(
        f"  Q1-Q5 mean: {ls_boot['estimate']*100:+.3f}%/{RETURN_LABEL}, "
        f"95% CI [{ls_boot['ci_low']*100:+.3f}%, "
        f"{ls_boot['ci_high']*100:+.3f}%]"
    )
    print(
        f"  Mean IC:    {ic_boot['estimate']:+.4f},      "
        f"95% CI [{ic_boot['ci_low']:+.4f}, {ic_boot['ci_high']:+.4f}]"
    )
    ls_zero = ls_boot["ci_low"] <= 0 <= ls_boot["ci_high"]
    ic_zero = ic_boot["ci_low"] <= 0 <= ic_boot["ci_high"]
    print(
        f"  Q1-Q5 CI contains zero: {ls_zero}   "
        f"IC CI contains zero: {ic_zero}"
    )
    return {"ls_boot": ls_boot, "ic_boot": ic_boot}


def layer_2_regime_split(
    panel: pd.DataFrame,
    factor_col: str,
    candidate_splits: list = None,
) -> dict:
    """
    Layer 2: multi-candidate regime split. For each candidate split date,
    run Q1-Q5 separately on the pre and post sub-panels. Reports all
    candidates so the structurally most informative split can be chosen
    after seeing the data.
    """
    if candidate_splits is None:
        candidate_splits = CANDIDATE_SPLITS

    print("\n" + "=" * 72)
    print(f"Layer 2: Multi-candidate regime split on {factor_col}")
    print(f"  Candidates: {[name for name, _ in candidate_splits]}")
    print("=" * 72)

    out = {}
    for split_name, split_date in candidate_splits:
        print(f"\n  --- Candidate: {split_name} ({split_date.date()}) ---")
        pre = panel[panel["rebalance_date"] < split_date]
        post = panel[panel["rebalance_date"] >= split_date]
        print(
            f"    Pre  ({pre['rebalance_date'].min().date() if len(pre) else 'empty'} to "
            f"{pre['rebalance_date'].max().date() if len(pre) else 'empty'}): "
            f"{pre['rebalance_date'].nunique()} dates"
        )
        print(
            f"    Post ({post['rebalance_date'].min().date() if len(post) else 'empty'} to "
            f"{post['rebalance_date'].max().date() if len(post) else 'empty'}): "
            f"{post['rebalance_date'].nunique()} dates"
        )

        sub_results = {}
        for sub_name, sub_panel in [("pre", pre), ("post", post)]:
            if sub_panel["rebalance_date"].nunique() < 2:
                print(f"    {sub_name}: insufficient dates, skipping.")
                continue
            quintiles = compute_quintile_series(sub_panel, sort_col=factor_col)
            summary = summarise_long_short(quintiles, f"  {split_name} {sub_name}")
            if summary.get("n", 0) >= 2 * BOOT_BLOCK_SIZE:
                boot = block_bootstrap_ci(
                    summary["ls_series"].values, np.mean,
                    block_size=BOOT_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
                )
                print(
                    f"      bootstrap 95% CI: "
                    f"[{boot['ci_low']*100:+.3f}%, "
                    f"{boot['ci_high']*100:+.3f}%]"
                )
                summary["bootstrap"] = boot
            sub_results[sub_name] = summary
        out[split_name] = sub_results
    return out


def layer_3_tradable_only(panel: pd.DataFrame, factor_col: str) -> None:
    """
    Layer 3: tradable-only filter. DEFERRED.

    Requires limit-state detection (涨跌停板 hits) which is open item 14
    in the project backlog. The plan is to wire this up alongside the
    cost-adjustment phase, since the filter and the cost model both
    capture realism layers in the simulated trade.
    """
    print("\n" + "=" * 72)
    print(f"Layer 3: Tradable-only filter — DEFERRED")
    print("=" * 72)
    print(
        "  Requires limit-state detection (涨跌停板) utility; open item 14.\n"
        "  Will be wired up in the cost-adjustment phase, since both layers\n"
        "  encode realism constraints on the simulated trade. Returning None."
    )
    return None


# ─── Pass 2 robustness layers ───────────────────────────────────────────

def residualise_factor_per_date(
    panel: pd.DataFrame,
    factor_col: str,
    sector_col: str = "l1_name",
    output_col: Optional[str] = None,
    min_stocks_per_sector: int = MIN_STOCKS_PER_SECTOR,
) -> pd.DataFrame:
    """
    Per rebalance_date, regress factor_col on sector dummies and add a
    residual column. Used by Layer 4.

    Sectors with fewer than min_stocks_per_sector at a given date get
    collapsed into 'other' to avoid singular dummy matrices in narrow
    cross-sections.

    Rows with NaN in factor_col or sector_col are excluded from the
    regression; their residual entry remains NaN so they drop out of
    the downstream quintile sort.
    """
    if output_col is None:
        output_col = f"{factor_col}_resid"

    df = panel.reset_index(drop=True).copy()
    out_residuals = np.full(len(df), np.nan)

    for date, group in df.groupby("rebalance_date"):
        valid_mask = group[factor_col].notna() & group[sector_col].notna()
        if valid_mask.sum() < 2:
            continue

        valid_group = group[valid_mask]
        valid_idx = valid_group.index.to_numpy()

        sector_counts = valid_group[sector_col].value_counts()
        small_sectors = sector_counts[sector_counts < min_stocks_per_sector].index
        sectors_clean = valid_group[sector_col].where(
            ~valid_group[sector_col].isin(small_sectors), "other"
        )

        dummies = pd.get_dummies(sectors_clean, drop_first=True, dtype=float)
        if dummies.shape[1] == 0:
            # Only one sector among valid rows; residual is demeaned factor.
            y = valid_group[factor_col].values
            resid = y - y.mean()
        else:
            X = np.column_stack([np.ones(len(valid_group)), dummies.values])
            y = valid_group[factor_col].values
            beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
        out_residuals[valid_idx] = resid

    df[output_col] = out_residuals
    return df


def layer_4_sector_neutral(panel: pd.DataFrame, factor_col: str) -> Optional[dict]:
    """
    Layer 4: residualise factor_col on SW L1 sector dummies per date,
    then re-run the Q1-Q5 sort on residuals. Asks: does factor_col
    predict returns AFTER stripping out sector composition?

    Residualization is performed on in-universe rows so the sector means
    reflect the universe being sorted, not the broader candidate pool.
    """
    print("\n" + "=" * 72)
    print(f"Layer 4: Sector neutralisation on {factor_col} (SW L1, PIT)")
    print("=" * 72)

    in_univ = panel[panel["in_universe"]].copy()

    n_total = len(in_univ)
    n_unmapped = int(in_univ["l1_name"].isna().sum())
    pct_unmapped = 100 * n_unmapped / n_total if n_total else 0
    print(
        f"  Sector coverage on in-universe rows: "
        f"{n_total - n_unmapped:,} of {n_total:,} "
        f"({100 - pct_unmapped:.2f}% mapped)"
    )

    if pct_unmapped > 5:
        print(
            f"  Warning: {pct_unmapped:.1f}% unmapped. "
            f"Layer 4 conditions on the {100 - pct_unmapped:.1f}% that are."
        )
    in_univ = in_univ.dropna(subset=["l1_name"]).copy()

    n_unique_sectors = in_univ["l1_name"].nunique()
    sectors_per_date = in_univ.groupby("rebalance_date")["l1_name"].nunique()
    print(
        f"  Unique sectors: {n_unique_sectors}; "
        f"sectors-per-date min/median/max: "
        f"{sectors_per_date.min()}/{int(sectors_per_date.median())}/"
        f"{sectors_per_date.max()}"
    )

    print(f"  Computing per-date residuals on {factor_col}...")
    resid_col = f"{factor_col}_resid"
    in_univ_resid = residualise_factor_per_date(
        in_univ, factor_col, "l1_name", output_col=resid_col,
    )

    resid_mean_check = (
        in_univ_resid.groupby("rebalance_date")[resid_col]
        .mean().abs().max()
    )
    print(f"  Residual sanity: max |mean(resid)| across dates = "
          f"{resid_mean_check:.2e}  (should be ~0 by OLS construction)")

    quintiles = compute_quintile_series(in_univ_resid, sort_col=resid_col)
    summary = summarise_long_short(quintiles, f"sector-neutral {factor_col} Q1-Q5")
    if summary.get("n", 0) >= 2 * BOOT_BLOCK_SIZE:
        boot = block_bootstrap_ci(
            summary["ls_series"].values, np.mean,
            block_size=BOOT_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
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
    True where the corresponding test should be rejected at family-wise
    FDR level alpha.
    """
    n = len(p_values)
    if n == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    threshold_index = -1
    for rank, (_, p) in enumerate(indexed, start=1):
        if p <= (rank / n) * alpha:
            threshold_index = rank
    rejected = [False] * n
    if threshold_index > 0:
        for orig_i, _ in indexed[:threshold_index]:
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
    """
    print("\n" + "=" * 72)
    print(
        f"Layer 5: Cap-tercile conditioning (BH-corrected); "
        f"factor={factor_col}, cap={cap_col}"
    )
    print("=" * 72)

    df = panel[panel["in_universe"]].copy()
    df["cap_tercile"] = (
        df.groupby("rebalance_date")[cap_col]
        .transform(
            lambda s: pd.qcut(s, 3, labels=["low", "mid", "high"],
                              duplicates="drop")
        )
    )
    # Re-stamp in_universe so compute_quintile_series sees True everywhere
    # in the sub-panels (we already filtered above; this prevents the
    # internal re-filter from dropping rows with NaN tercile).
    df = df.dropna(subset=["cap_tercile"]).copy()

    out = {}
    p_values = []
    labels = []

    for tercile_name in ["low", "mid", "high"]:
        sub = df[df["cap_tercile"] == tercile_name].copy()
        quintiles = compute_quintile_series(sub, sort_col=factor_col)
        summary = summarise_long_short(quintiles, f"cap-tercile {tercile_name}")
        if summary.get("n", 0) >= 2 * BOOT_BLOCK_SIZE:
            boot = block_bootstrap_ci(
                summary["ls_series"].values, np.mean,
                block_size=BOOT_BLOCK_SIZE, n_boot=BOOT_N, seed=SEED,
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
    regime_events: dict = None,
) -> None:
    """Plot cumulative weekly returns by quintile, with regime markers."""
    if regime_events is None:
        regime_events = REGIME_EVENTS

    cum_returns = (1 + quintile_returns.fillna(0)).cumprod()

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = plt.cm.RdYlBu_r(np.linspace(0.10, 0.90, 5))
    labels = {0: "Q1 (smallest)", 1: "Q2", 2: "Q3", 3: "Q4", 4: "Q5 (largest)"}

    for q in range(5):
        if q in cum_returns.columns:
            ax.plot(
                cum_returns.index, cum_returns[q],
                label=labels[q], color=colors[q], linewidth=1.5,
            )

    ymax = ax.get_ylim()[1]
    for label, event_date in regime_events.items():
        ax.axvline(event_date, color="grey", linestyle="--",
                   alpha=0.55, linewidth=0.9)
        ax.text(
            event_date, ymax * 0.985, label,
            rotation=90, verticalalignment="top",
            fontsize=8, color="dimgrey",
        )

    ax.set_title(f"Cumulative weekly returns by {factor_label} quintile")
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
    regime_events: dict = None,
) -> None:
    """Plot weekly IC time series with mean line and regime markers."""
    if regime_events is None:
        regime_events = REGIME_EVENTS

    fig, ax = plt.subplots(figsize=(12, 4.5))
    # bar width 5 days ~= one weekly bar; old code used 20 (monthly).
    ax.bar(ic_clean.index, ic_clean.values, width=5, alpha=0.7,
           color="steelblue")
    ax.axhline(0, color="black", linewidth=0.7)
    ax.axhline(
        ic_clean.mean(),
        color="firebrick", linestyle="--", alpha=0.85,
        label=f"Mean IC = {ic_clean.mean():+.4f}",
    )

    ymax = ax.get_ylim()[1]
    ymin = ax.get_ylim()[0]
    for label, event_date in regime_events.items():
        ax.axvline(event_date, color="grey", linestyle="--",
                   alpha=0.55, linewidth=0.9)
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

# ─── Reporting helpers ──────────────────────────────────────────────────

def report_coverage_by_year(
    panel: pd.DataFrame,
    factor_col: str,
    in_universe_only: bool = True,
) -> None:
    """
    Print a per-year coverage table for factor_col.

    Routine diagnostic to surface late-panel coverage drift before reading
    factor results. The motivating example is the EP coverage drift
    surfaced at the end of Phase A (82% in 2019 to 62% in 2026): if a
    factor's late-panel cells are thin, late-panel results are noisier
    than headline counts suggest.
    """
    df = panel[panel["in_universe"]].copy() if in_universe_only else panel.copy()
    if len(df) == 0:
        return
    df["_year"] = df["rebalance_date"].dt.year
    cov = df.groupby("_year")[factor_col].agg(
        n="size",
        n_with=lambda s: int(s.notna().sum()),
    )
    cov["pct"] = (100 * cov["n_with"] / cov["n"]).round(1)

    label = "in-universe" if in_universe_only else "all candidate"
    print(f"\n  {factor_col} coverage by year ({label} rows):")
    print(cov.to_string())


def collect_factor_results(
    factor_name: str,
    headline: dict,
    ic: pd.Series,
    layer_1: dict | None = None,
    layer_2: dict | None = None,
    layer_4: dict | None = None,
    layer_5: dict | None = None,
) -> list:
    """
    Flatten layer outputs into a long-format list of dicts. Each row is
    one (factor, layer, cell) triple with the relevant statistics.

    Caller writes to CSV; cross-factor comparison reads all per-factor
    CSVs and concatenates. Long format keeps the schema flat across
    factors that have different layer-result shapes.
    """
    def pct(x):
        return x * 100 if x is not None else None

    rows = []

    # Headline: Q1-Q5 and IC as separate rows
    rows.append({
        "factor": factor_name, "layer": "headline", "cell": "q1_q5",
        "n": headline.get("n"),
        "mean_pct_wk": pct(headline.get("mean_period")),
        "std_pct_wk": pct(headline.get("std_period")),
        "t_stat": headline.get("t_stat"),
        "sharpe": headline.get("naive_sharpe"),
    })
    if ic is not None and len(ic) > 0:
        rows.append({
            "factor": factor_name, "layer": "headline", "cell": "ic",
            "n": int(len(ic)),
            "ic_mean": float(ic.mean()),
            "ic_std": float(ic.std()),
        })

    # Layer 1: bootstrap CIs on Q1-Q5 and IC
    if layer_1 is not None:
        ls = layer_1.get("ls_boot", {})
        ic_b = layer_1.get("ic_boot", {})
        if ls:
            rows.append({
                "factor": factor_name, "layer": "layer1_bootstrap", "cell": "q1_q5",
                "estimate_pct_wk": pct(ls.get("estimate")),
                "ci_low_pct_wk": pct(ls.get("ci_low")),
                "ci_high_pct_wk": pct(ls.get("ci_high")),
                "ci_contains_zero": (
                    ls.get("ci_low", 0) <= 0 <= ls.get("ci_high", 0)
                ),
            })
        if ic_b:
            rows.append({
                "factor": factor_name, "layer": "layer1_bootstrap", "cell": "ic",
                "estimate": ic_b.get("estimate"),
                "ci_low": ic_b.get("ci_low"),
                "ci_high": ic_b.get("ci_high"),
                "ci_contains_zero": (
                    ic_b.get("ci_low", 0) <= 0 <= ic_b.get("ci_high", 0)
                ),
            })

    # Layer 2: multi-candidate pre/post
    if layer_2 is not None:
        for split_name, splits in layer_2.items():
            for sub_name, sub in splits.items():
                rows.append({
                    "factor": factor_name,
                    "layer": "layer2_regime",
                    "cell": f"{split_name}_{sub_name}",
                    "n": sub.get("n"),
                    "mean_pct_wk": pct(sub.get("mean_period")),
                    "t_stat": sub.get("t_stat"),
                })

    # Layer 4: sector-neutral
    if layer_4 is not None:
        boot = layer_4.get("bootstrap", {}) or {}
        rows.append({
            "factor": factor_name,
            "layer": "layer4_sector_neutral",
            "cell": "q1_q5",
            "n": layer_4.get("n"),
            "mean_pct_wk": pct(layer_4.get("mean_period")),
            "t_stat": layer_4.get("t_stat"),
            "ci_low_pct_wk": pct(boot.get("ci_low")),
            "ci_high_pct_wk": pct(boot.get("ci_high")),
            "ci_contains_zero": (
                boot.get("ci_low", 0) <= 0 <= boot.get("ci_high", 0)
                if boot else None
            ),
        })

    # Layer 5: cap terciles
    if layer_5 is not None:
        for tercile_name in ["low", "mid", "high"]:
            sub = layer_5.get(tercile_name, {})
            if not sub or sub.get("n", 0) == 0:
                continue
            boot = sub.get("bootstrap", {}) or {}
            rows.append({
                "factor": factor_name,
                "layer": "layer5_cap_tercile",
                "cell": tercile_name,
                "n": sub.get("n"),
                "mean_pct_wk": pct(sub.get("mean_period")),
                "t_stat": sub.get("t_stat"),
                "p_value": sub.get("p_value"),
                "ci_low_pct_wk": pct(boot.get("ci_low")),
                "ci_high_pct_wk": pct(boot.get("ci_high")),
            })

    return rows