"""
size_robustness.py

Project 6 Session 2: robustness layers on the size factor.

Adds five robustness checks on top of the thin pipeline from Session 1:

  Pass 1 (this script's first three sections):
    1. Block bootstrap CI on Q1-Q5 mean and on mean IC.
    2. Regime split at the PBoC stimulus date (2024-09-18).
    3. Tradable-only filter (entry_tradable AND exit_tradable).

  Pass 2 (sections four and five):
    4. Sector neutralisation: residualise log_mcap on L1 sector dummies
       per rebalance date, repeat the quintile sort on residuals.
    5. Cap-tercile conditioning: split the bottom-1000 into low/mid/high
       cap terciles, run Q1-Q5 within each.

Multi-test correction: Holm-Bonferroni on the family of 5 robustness
findings as a separate question from the single headline test. (Per the
locked Project 6 policy: HB for headlines, BH for within-factor
robustness; here the 5 layers ARE the robustness family for size, so BH
would also be defensible. We use HB here for consistency with the
headline-test convention since each layer asks a yes/no question.)

Run from Project_6/ as: `python size_robustness.py`
"""

# %%  Imports and configuration --------------------------------------------
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hypothesis_testing import block_bootstrap_ci

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

DATA_DIR = Path("data")
UNIVERSE_PATH = DATA_DIR / "universe_membership.csv"
RETURN_PATH = DATA_DIR / "forward_return_panel.csv"

REGIME_SPLIT_DATE = pd.Timestamp("2024-09-18")  # PBoC stimulus
SEED = 42  # for bootstrap reproducibility


# %%  Load data and build the merged panel --------------------------------
def load_panel() -> pd.DataFrame:
    """Load and merge Project 5 CSVs, keep only in-universe rows, add log_mcap."""
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


# %%  Per-quintile aggregation as a reusable function ---------------------
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
    """
    df = panel.copy()
    df["quintile"] = (
        df.groupby("rebalance_date")[sort_col]
        .transform(lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
    )
    quintile_returns = (
        df.groupby(["rebalance_date", "quintile"])[return_col]
        .mean()
        .unstack()
    )
    return quintile_returns


def summarise_long_short(
    quintile_returns: pd.DataFrame,
    label: str,
) -> dict:
    """Compute Q1-Q5 mean, std, t-stat, naive Sharpe; print a one-line summary."""
    if 0 not in quintile_returns.columns or 4 not in quintile_returns.columns:
        return {"label": label, "n": 0}
    ls = (quintile_returns[0] - quintile_returns[4]).dropna()
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
        f"  {label:<35s} n={summary['n']:3d}  "
        f"mean={mean*100:+.3f}%/mo  std={std*100:.3f}%  "
        f"t={t_stat:+.2f}  Sharpe={sharpe:+.2f}"
    )
    return summary


def compute_ic_series(panel: pd.DataFrame, sort_col: str = "log_mcap") -> pd.Series:
    """Cross-sectional Spearman rank IC per rebalance_date."""
    return (
        panel.dropna(subset=["forward_return", sort_col])
        .groupby("rebalance_date")
        .apply(
            lambda g: g[sort_col].corr(g["forward_return"], method="spearman"),
            include_groups=False,
        )
        .dropna()
    )


# %%  Layer 1: Block bootstrap CI on the headline ------------------------
def layer_1_bootstrap_ci(panel: pd.DataFrame) -> dict:
    print("\n" + "=" * 72)
    print("Layer 1: Block bootstrap CI (block_size=3, n_boot=5000)")
    print("=" * 72)

    quintiles = compute_quintile_series(panel)
    ls = (quintiles[0] - quintiles[4]).dropna().values
    ic = compute_ic_series(panel).values

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


# %%  Layer 2: Regime split ----------------------------------------------
def layer_2_regime_split(panel: pd.DataFrame) -> dict:
    print("\n" + "=" * 72)
    print(
        f"Layer 2: Regime split at {REGIME_SPLIT_DATE.date()} (PBoC stimulus)"
    )
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
        quintiles = compute_quintile_series(p)
        summary = summarise_long_short(quintiles, name)
        # Bootstrap CI on each sub-period mean. block_size=3 still, but n is
        # smaller so CIs will be wider; report and don't over-interpret.
        if summary.get("n", 0) >= 6:  # need n >= 2 * block_size
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


# %%  Layer 3: Tradable-only filter --------------------------------------
def layer_3_tradable_only(panel: pd.DataFrame) -> dict:
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
    quintiles = compute_quintile_series(panel_tradable)
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


# %%  Run Pass 1 ---------------------------------------------------------
if __name__ == "__main__":
    panel = load_panel()
    print(f"Panel loaded: {len(panel):,} rows, {panel['rebalance_date'].nunique()} dates")

    # Headline (re-run for context) ---------------------------------------
    print("\n" + "=" * 72)
    print("Headline (Session 1 baseline, re-run)")
    print("=" * 72)
    quintiles = compute_quintile_series(panel)
    headline = summarise_long_short(quintiles, "headline Q1-Q5")
    headline_ic = compute_ic_series(panel)
    print(f"  IC: mean={headline_ic.mean():+.4f}, std={headline_ic.std():.4f}, n={len(headline_ic)}")

    layer_1 = layer_1_bootstrap_ci(panel)
    layer_2 = layer_2_regime_split(panel)
    layer_3 = layer_3_tradable_only(panel)

    print("\n" + "=" * 72)
    print("Pass 1 complete. Run size_robustness_pass2.py for sector neutralisation")
    print("and cap-tercile conditioning.")
    print("=" * 72)