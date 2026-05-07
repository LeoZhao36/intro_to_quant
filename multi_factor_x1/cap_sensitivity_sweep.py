"""
Sector cap sensitivity sweep at top-20 in γ regime.

Tests cap_pct ∈ {0.15, 0.20, 0.25, 0.30, 0.40, 1.00} on z_turnover_resid
+ 5000万 RMB liquidity floor at top-20 long-only, weekly rebalance,
open_t1 forward return, cost = churn × 0.18%.

Reports IR vs liquid benchmark (filter-matched) and IR vs broad benchmark
(in_universe-EW, no filter), plus structural diagnostics: max sector share,
mean unique sectors, persistent-core fraction.

Saves:
    data/cap_sensitivity_summary_top20.csv           (one row per cap)
    data/cap_sensitivity_basket_diagnostics_top20.csv (one row per cap × rebalance)

Run from multi_factor_x1/ directory.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import statsmodels.api as sm

THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"

# Spec
N_TOP = 20
LIQ_FLOOR_YI = 0.5
GAMMA_START = pd.Timestamp("2024-04-12")
GAMMA_END = pd.Timestamp("2026-04-29")
COST_RT = 0.0018
PERIODS_PER_YEAR = 52

CAP_GRID = [0.15, 0.20, 0.25, 0.30, 0.40, 1.00]


def load_data():
    fp = pd.read_parquet(DATA_DIR / "factor_panel_a.parquet")
    um = pd.read_parquet(DATA_DIR / "universe_membership_three.parquet")
    sw = pd.read_parquet(DATA_DIR / "sw_l1_membership.parquet")

    fp["rebalance_date"] = pd.to_datetime(fp["rebalance_date"])
    um["rebalance_date"] = pd.to_datetime(um["rebalance_date"])
    sw["in_date"] = pd.to_datetime(sw["in_date"], format="%Y%m%d", errors="coerce")
    sw["out_date"] = pd.to_datetime(sw["out_date"], format="%Y%m%d", errors="coerce")
    return fp, um, sw


def pit_industry_panel(sw, asof):
    """All (ts_code -> industry_code) mappings valid at asof."""
    m = (sw["in_date"] <= asof) & (sw["out_date"].isna() | (sw["out_date"] > asof))
    return sw.loc[m, ["ts_code", "industry_code", "industry_name"]].drop_duplicates(
        subset="ts_code", keep="first"
    )


def residualize_one_date(df, factor_col, numeric_controls, categorical_control):
    df = df.copy()
    X_num = df[numeric_controls].astype(float).values
    dummies = pd.get_dummies(df[categorical_control], drop_first=True).astype(float).values
    X = np.hstack([X_num, dummies]) if dummies.size else X_num
    X = sm.add_constant(X, has_constant="add")
    y = df[factor_col].astype(float).values
    df["resid"] = sm.OLS(y, X).fit().resid
    return df


def build_one_date_pool(fp, um, sw, asof):
    """Return liquid-pool DataFrame at asof with z_turnover_resid + industry."""
    sub = fp.loc[fp["rebalance_date"] == asof].copy()
    um_sub = um.loc[um["rebalance_date"] == asof, ["ts_code", "in_A"]]
    sub = sub.merge(um_sub, on="ts_code", how="left")
    sub = sub.loc[sub["in_A"] == True].copy()

    broad_pool = sub.copy()
    sub = sub.loc[sub["amount_yi"] >= LIQ_FLOOR_YI].copy()

    sectors = pit_industry_panel(sw, asof)
    sub = sub.merge(sectors, on="ts_code", how="left")
    sub = sub.dropna(subset=["industry_code", "mean_turnover_20d", "log_mcap"]).copy()

    if len(sub) < 30:
        return None, broad_pool

    sub = residualize_one_date(
        sub,
        factor_col="mean_turnover_20d",
        numeric_controls=["log_mcap"],
        categorical_control="industry_code",
    )
    s = sub["resid"].std(ddof=0)
    sub["z_turnover_resid"] = (
        -(sub["resid"] - sub["resid"].mean()) / s if s and not np.isnan(s) else np.nan
    )
    return sub, broad_pool


def apply_cap_and_pick(pool, cap_pct, n_top):
    """Sector cap as per-sector top-K then global top-N. cap_pct=1.0 means no cap."""
    if cap_pct >= 1.0:
        return pool.nlargest(n_top, "z_turnover_resid").copy()

    K = max(1, int(np.floor(n_top * cap_pct)))
    pool = pool.sort_values("z_turnover_resid", ascending=False)
    pool = pool.assign(rank_in_sector=pool.groupby("industry_code").cumcount() + 1)
    candidates = pool.loc[pool["rank_in_sector"] <= K]
    return candidates.nlargest(n_top, "z_turnover_resid").copy()


def compute_churn(prev_codes, cur_codes):
    if not prev_codes:
        return np.nan
    prev_set, cur_set = set(prev_codes), set(cur_codes)
    return 1 - len(prev_set & cur_set) / max(len(cur_set), 1)


def run_one_cap(fp, um, sw, gamma_dates, cap_pct):
    rows = []
    basket_diags = []
    prev_basket_codes = []

    for d in gamma_dates:
        liquid_pool, broad_pool = build_one_date_pool(fp, um, sw, d)

        # Benchmarks at this date
        broad_ret = broad_pool["weekly_forward_return"].mean()
        liquid_ret = (
            liquid_pool["weekly_forward_return"].mean()
            if liquid_pool is not None and len(liquid_pool) > 0
            else np.nan
        )

        if liquid_pool is None or len(liquid_pool) < N_TOP:
            rows.append({
                "rebalance_date": d, "basket_ret_gross": np.nan,
                "broad_ret": broad_ret, "liquid_ret": liquid_ret,
                "churn": np.nan, "n_basket": 0,
            })
            continue

        basket = apply_cap_and_pick(liquid_pool, cap_pct, N_TOP)
        basket_ret_gross = basket["weekly_forward_return"].mean()
        codes = basket["ts_code"].tolist()
        churn = compute_churn(prev_basket_codes, codes)
        prev_basket_codes = codes

        rows.append({
            "rebalance_date": d,
            "basket_ret_gross": basket_ret_gross,
            "broad_ret": broad_ret,
            "liquid_ret": liquid_ret,
            "churn": churn,
            "n_basket": len(basket),
        })

        basket_diags.append({
            "cap_pct": cap_pct,
            "rebalance_date": d,
            "n_unique_sectors": basket["industry_name"].nunique(),
            "max_sector_share": basket["industry_name"].value_counts(normalize=True).max(),
            "median_mcap_yi": basket["circ_mv_yi"].median(),
            "min_mcap_yi": basket["circ_mv_yi"].min(),
            "n_below_3rmb": int((basket["close"] < 3).sum()),
        })

    df = pd.DataFrame(rows)
    df["cost"] = df["churn"].fillna(0) * COST_RT
    df["basket_ret_net"] = df["basket_ret_gross"] - df["cost"]
    df["active_vs_broad_net"] = df["basket_ret_net"] - df["broad_ret"]
    df["active_vs_liquid_net"] = df["basket_ret_net"] - df["liquid_ret"]

    # IR aggregate
    obs = df.dropna(subset=["basket_ret_net"])

    def ir(series):
        s = series.dropna()
        if len(s) < 4 or s.std(ddof=1) == 0:
            return np.nan
        return s.mean() / s.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR)

    summary = {
        "cap_pct": cap_pct,
        "n_obs": len(obs),
        "ir_vs_broad": ir(obs["active_vs_broad_net"]),
        "ir_vs_liquid": ir(obs["active_vs_liquid_net"]),
        "active_vs_broad_ann": obs["active_vs_broad_net"].mean() * PERIODS_PER_YEAR,
        "active_vs_liquid_ann": obs["active_vs_liquid_net"].mean() * PERIODS_PER_YEAR,
        "basket_ret_ann_net": obs["basket_ret_net"].mean() * PERIODS_PER_YEAR,
        "te_vs_liquid_ann": obs["active_vs_liquid_net"].std(ddof=1) * np.sqrt(PERIODS_PER_YEAR),
        "mean_churn": obs["churn"].mean(),
        "mean_cost_ann": obs["cost"].mean() * PERIODS_PER_YEAR,
    }

    diag_df = pd.DataFrame(basket_diags)
    if len(diag_df):
        summary["mean_n_unique_sectors"] = diag_df["n_unique_sectors"].mean()
        summary["mean_max_sector_share"] = diag_df["max_sector_share"].mean()
        summary["mean_median_mcap"] = diag_df["median_mcap_yi"].mean()

    return summary, diag_df


def main():
    fp, um, sw = load_data()

    all_gamma = sorted(
        fp.loc[
            (fp["rebalance_date"] >= GAMMA_START) & (fp["rebalance_date"] <= GAMMA_END),
            "rebalance_date",
        ].unique()
    )
    gamma_dates = [pd.Timestamp(d) for d in all_gamma]
    print(f"γ-regime rebalances: {len(gamma_dates)} ({gamma_dates[0].date()} to {gamma_dates[-1].date()})")

    summaries = []
    all_diags = []
    for cap in CAP_GRID:
        print(f"\n  running cap_pct = {cap:.2f} ...", end="", flush=True)
        summary, diag = run_one_cap(fp, um, sw, gamma_dates, cap)
        summaries.append(summary)
        all_diags.append(diag)
        print(
            f"  IR_liq = {summary['ir_vs_liquid']:+.2f},  "
            f"IR_broad = {summary['ir_vs_broad']:+.2f},  "
            f"active_liq = {summary['active_vs_liquid_ann']*100:+.2f}%,  "
            f"max_sect = {summary.get('mean_max_sector_share', np.nan)*100:.0f}%"
        )

    summary_df = pd.DataFrame(summaries)

    print()
    print("=" * 96)
    print("SECTOR CAP SENSITIVITY at top-20, γ regime, net of 0.18% × churn cost")
    print("=" * 96)
    show = summary_df.copy()
    show["ir_vs_broad"] = show["ir_vs_broad"].round(2)
    show["ir_vs_liquid"] = show["ir_vs_liquid"].round(2)
    show["active_vs_broad_ann"] = (show["active_vs_broad_ann"] * 100).round(2)
    show["active_vs_liquid_ann"] = (show["active_vs_liquid_ann"] * 100).round(2)
    show["basket_ret_ann_net"] = (show["basket_ret_ann_net"] * 100).round(2)
    show["te_vs_liquid_ann"] = (show["te_vs_liquid_ann"] * 100).round(2)
    show["mean_churn"] = (show["mean_churn"] * 100).round(1)
    show["mean_cost_ann"] = (show["mean_cost_ann"] * 100).round(2)
    show["mean_max_sector_share"] = (show["mean_max_sector_share"] * 100).round(1)
    show["mean_median_mcap"] = show["mean_median_mcap"].round(1)
    print(show.to_string(index=False))

    summary_df.to_csv(DATA_DIR / "cap_sensitivity_summary_top20.csv", index=False)
    pd.concat(all_diags, ignore_index=True).to_csv(
        DATA_DIR / "cap_sensitivity_basket_diagnostics_top20.csv", index=False
    )
    print(f"\nSaved to {DATA_DIR / 'cap_sensitivity_summary_top20.csv'}")
    print(f"Saved to {DATA_DIR / 'cap_sensitivity_basket_diagnostics_top20.csv'}")


if __name__ == "__main__":
    main()