"""
size_robustness_pass2.py

Project 6 Session 2: Pass 2 robustness layers on the size factor.

Builds on Pass 1's headline + bootstrap + regime + tradable findings:

  4. Sector neutralisation: residualise log_mcap on SW L1 sector dummies
     per rebalance date, repeat the quintile sort on the residuals.
     Tests: does size predict returns AFTER stripping out sector
     composition?

  5. Cap-tercile conditioning: split the bottom-1000 into low/mid/high
     cap terciles per date, run Q1-Q5 within each. Tests: does size
     behave the same way across the universe, or does the relationship
     differ at different cap levels?

For Pass 2 we use Benjamini-Hochberg correction on the family of three
within-cap-tercile tests, per the locked Project 6 policy (HB for the
family of headline-direction tests, BH for within-factor robustness).

Sector data: loads from sw_membership.csv (one row per ts_code, with
l1_code as the SW L1 sector). The membership file has no out_date
populated, so we treat the ts_code -> l1_code mapping as static across
our 2022-2026 sample.

Run from Project_6/ as: `python size_robustness_pass2.py`
"""

# %%  Imports and configuration --------------------------------------------
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hypothesis_testing import block_bootstrap_ci

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

DATA_DIR = Path("data")
UNIVERSE_PATH = DATA_DIR / "universe_membership.csv"
RETURN_PATH = DATA_DIR / "forward_return_panel.csv"
SECTOR_PATH = DATA_DIR / "sw_membership.csv"
SEED = 42

MIN_STOCKS_PER_SECTOR = 5  # collapse smaller sectors into 'other' before regression


# %%  Reuse Pass 1's panel-loading and aggregation logic ------------------
def load_panel() -> pd.DataFrame:
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
    Load the SW L1 sector mapping. Returns a DataFrame with two columns:
    ts_code, l1_code. Returns None if the file is missing.
    """
    if not SECTOR_PATH.exists():
        return None
    df = pd.read_csv(SECTOR_PATH, dtype=str)
    if "ts_code" not in df.columns or "l1_code" not in df.columns:
        print(f"  Warning: sw_membership.csv lacks expected columns. Got: {list(df.columns)}")
        return None
    # Keep one row per ts_code (the file already is, but enforce it).
    return df[["ts_code", "l1_code", "l1_name"]].drop_duplicates(subset=["ts_code"])


def compute_quintile_series(
    panel: pd.DataFrame,
    sort_col: str = "log_mcap",
    return_col: str = "forward_return",
) -> pd.DataFrame:
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


def summarise_long_short(qr: pd.DataFrame, label: str) -> dict:
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
        "label": label, "n": int(len(ls)),
        "mean_monthly": mean, "std_monthly": std,
        "t_stat": float(t_stat), "naive_sharpe": float(sharpe),
        "ls_series": ls,
    }
    print(
        f"  {label:<40s} n={summary['n']:3d}  "
        f"mean={mean*100:+.3f}%/mo  std={std*100:.3f}%  "
        f"t={t_stat:+.2f}  Sharpe={sharpe:+.2f}"
    )
    return summary


# %%  Layer 4: Sector neutralisation -------------------------------------
def residualise_log_mcap_per_date(
    panel: pd.DataFrame,
    sector_col: str,
) -> pd.DataFrame:
    """
    Per rebalance_date, regress log_mcap on sector dummies and add a column
    'log_mcap_resid' containing the residuals. Sectors with fewer than
    MIN_STOCKS_PER_SECTOR stocks at a given date are collapsed into 'other'
    before the regression to avoid singular dummy matrices.
    """
    df = panel.reset_index(drop=True).copy()
    out_residuals = np.full(len(df), np.nan)

    for date, group in df.groupby("rebalance_date"):
        idx = group.index.to_numpy()
        # Collapse small sectors into 'other'
        sector_counts = group[sector_col].value_counts()
        small_sectors = sector_counts[sector_counts < MIN_STOCKS_PER_SECTOR].index
        sectors_clean = group[sector_col].where(
            ~group[sector_col].isin(small_sectors), "other"
        )

        # Build dummy matrix; drop one sector to avoid perfect collinearity
        # with the intercept (the "absorbed" sector becomes the baseline).
        dummies = pd.get_dummies(sectors_clean, drop_first=True, dtype=float)
        if dummies.shape[1] == 0:
            # Only one sector at this date; residual is just demeaned log_mcap
            mcap = group["log_mcap"].values
            resid = mcap - mcap.mean()
        else:
            X = np.column_stack([np.ones(len(group)), dummies.values])
            y = group["log_mcap"].values
            # OLS via lstsq (handles potential rank-deficiency gracefully)
            beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
        out_residuals[idx] = resid

    df["log_mcap_resid"] = out_residuals
    return df


def layer_4_sector_neutral(panel: pd.DataFrame) -> Optional[dict]:
    print("\n" + "=" * 72)
    print("Layer 4: Sector neutralisation (SW L1, static mapping)")
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

    # Drop rows without a sector. If many are unmapped, warn but proceed.
    if pct_unmapped > 5:
        print(
            f"  Warning: {pct_unmapped:.1f}% of rows have no sector mapping. "
            "Layer 4 results condition on the {100-pct_unmapped:.1f}% that do."
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

    print("  Computing sector residuals per date (this may take ~5-10s)...")
    panel_resid = residualise_log_mcap_per_date(panel_sec, "l1_code")

    # Sanity check: residuals should have mean ~0 per date (within rounding)
    resid_mean_check = panel_resid.groupby("rebalance_date")["log_mcap_resid"].mean().abs().max()
    print(f"  Residual sanity: max |mean(resid)| across dates = {resid_mean_check:.2e}")

    quintiles = compute_quintile_series(panel_resid, sort_col="log_mcap_resid")
    summary = summarise_long_short(quintiles, "sector-neutral Q1-Q5")
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


# %%  Layer 5: Cap-tercile conditioning ----------------------------------
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


def layer_5_cap_terciles(panel: pd.DataFrame) -> dict:
    print("\n" + "=" * 72)
    print("Layer 5: Cap-tercile conditioning (BH-corrected)")
    print("=" * 72)

    df = panel.copy()
    df["cap_tercile"] = (
        df.groupby("rebalance_date")["log_mcap"]
        .transform(lambda s: pd.qcut(s, 3, labels=["low", "mid", "high"], duplicates="drop"))
    )

    out = {}
    p_values = []
    labels = []

    for tercile_name in ["low", "mid", "high"]:
        sub = df[df["cap_tercile"] == tercile_name].copy()
        quintiles = compute_quintile_series(sub)
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


# %%  Run Pass 2 ---------------------------------------------------------
if __name__ == "__main__":
    panel = load_panel()
    print(
        f"Panel loaded: {len(panel):,} rows, "
        f"{panel['rebalance_date'].nunique()} dates"
    )

    layer_4 = layer_4_sector_neutral(panel)
    layer_5 = layer_5_cap_terciles(panel)

    print("\n" + "=" * 72)
    print("Pass 2 complete.")
    print("=" * 72)