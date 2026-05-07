"""
Basket inspection for v2 deployable spec.

For the most recent N_RECENT γ-regime rebalances, recompute z_turnover_resid,
apply v2 filters (5000万 RMB liquidity floor, sector cap 20%, top-N=20),
print each basket with stock-level details, and produce
frequency / sector / size / price-floor diagnostics.

Run from multi_factor_x1/ directory:
    python inspect_top20_baskets.py

Saves full per-rebalance basket compositions to data/basket_inspection_top20_full_filtered.csv.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import statsmodels.api as sm

THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"
PROJECT_6_DATA = THIS_DIR.parent / "Project_6" / "data"

# v2 spec
N_TOP = 20
SECTOR_CAP_PCT = 0.20
SECTOR_CAP_K = int(np.floor(N_TOP * SECTOR_CAP_PCT))  # = 4
LIQ_FLOOR_YI = 0.5  # 5000万 RMB rebalance-day amount
GAMMA_START = pd.Timestamp("2024-04-12")
N_RECENT = 10
PRICE_FLOOR_REFERENCE = 3.0  # diagnostic only, not applied as filter (Stage 2 territory)


def load_data():
    fp = pd.read_parquet(DATA_DIR / "factor_panel_a.parquet")
    um = pd.read_parquet(DATA_DIR / "universe_membership_three.parquet")
    sw = pd.read_parquet(DATA_DIR / "sw_l1_membership.parquet")
    nm = pd.read_csv(PROJECT_6_DATA / "historical_names.csv")

    fp["rebalance_date"] = pd.to_datetime(fp["rebalance_date"])
    um["rebalance_date"] = pd.to_datetime(um["rebalance_date"])
    sw["in_date"] = pd.to_datetime(sw["in_date"], format="%Y%m%d", errors="coerce")
    sw["out_date"] = pd.to_datetime(sw["out_date"], format="%Y%m%d", errors="coerce")
    nm["start_date"] = pd.to_datetime(nm["start_date"], errors="coerce")
    nm["end_date"] = pd.to_datetime(nm["end_date"], errors="coerce")

    return fp, um, sw, nm


def pit_industry(sw, asof, ts_codes):
    """Point-in-time SW L1 industry lookup."""
    m = (
        sw["ts_code"].isin(ts_codes)
        & (sw["in_date"] <= asof)
        & (sw["out_date"].isna() | (sw["out_date"] > asof))
    )
    sub = sw.loc[m, ["ts_code", "industry_code", "industry_name"]]
    return sub.drop_duplicates(subset="ts_code", keep="first")


def pit_name(nm, asof, ts_codes):
    """Point-in-time stock-name lookup."""
    m = (
        nm["ts_code"].isin(ts_codes)
        & (nm["start_date"] <= asof)
        & (nm["end_date"].isna() | (nm["end_date"] > asof))
    )
    sub = nm.loc[m, ["ts_code", "name"]]
    return sub.drop_duplicates(subset="ts_code", keep="first")


def residualize_one_date(df, factor_col, numeric_controls, categorical_control):
    """OLS residualize factor on numeric_controls + dummy(categorical_control). Adds 'resid' column."""
    df = df.copy()
    X_num = df[numeric_controls].astype(float).values
    dummies = pd.get_dummies(df[categorical_control], drop_first=True).astype(float).values
    X = np.hstack([X_num, dummies]) if dummies.size else X_num
    X = sm.add_constant(X, has_constant="add")
    y = df[factor_col].astype(float).values
    model = sm.OLS(y, X).fit()
    df["resid"] = model.resid
    return df


def build_basket(fp, um, sw, nm, asof):
    """Apply full v2 pipeline at one rebalance date and return basket + diagnostics."""
    sub = fp.loc[fp["rebalance_date"] == asof].copy()
    um_sub = um.loc[um["rebalance_date"] == asof, ["ts_code", "in_A"]]
    sub = sub.merge(um_sub, on="ts_code", how="left")
    sub = sub.loc[sub["in_A"] == True].copy()

    univA_count = len(sub)
    sub = sub.loc[sub["amount_yi"] >= LIQ_FLOOR_YI].copy()
    post_liq_count = len(sub)

    sectors = pit_industry(sw, asof, sub["ts_code"].tolist())
    sub = sub.merge(sectors, on="ts_code", how="left")
    sub = sub.dropna(subset=["industry_code", "mean_turnover_20d", "log_mcap"]).copy()

    sub = residualize_one_date(
        sub,
        factor_col="mean_turnover_20d",
        numeric_controls=["log_mcap"],
        categorical_control="industry_code",
    )
    resid_std = sub["resid"].std(ddof=0)
    if resid_std == 0 or np.isnan(resid_std):
        sub["z_turnover_resid"] = np.nan
    else:
        sub["z_turnover_resid"] = -(sub["resid"] - sub["resid"].mean()) / resid_std

    # Sector cap: per-sector top-K by z_turnover_resid, then global top-N
    sub = sub.sort_values("z_turnover_resid", ascending=False)
    sub["rank_in_sector"] = sub.groupby("industry_code").cumcount() + 1
    candidates = sub.loc[sub["rank_in_sector"] <= SECTOR_CAP_K].copy()
    basket = candidates.nlargest(N_TOP, "z_turnover_resid").copy()

    names_sub = pit_name(nm, asof, basket["ts_code"].tolist())
    basket = basket.merge(names_sub, on="ts_code", how="left")
    basket["name"] = basket["name"].fillna(basket["ts_code"])
    basket["rebalance_date"] = asof

    out_cols = [
        "rebalance_date", "ts_code", "name", "industry_name",
        "circ_mv_yi", "close", "amount_yi",
        "mean_turnover_20d", "z_turnover_resid",
        "weekly_forward_return",
    ]

    diag = {
        "asof": asof,
        "univA_count": univA_count,
        "post_liq_count": post_liq_count,
        "n_sectors_used": basket["industry_name"].nunique(),
        "max_sector_share": basket["industry_name"].value_counts(normalize=True).max(),
        "n_below_3rmb": int((basket["close"] < PRICE_FLOOR_REFERENCE).sum()),
        "min_close": basket["close"].min(),
        "median_mcap_yi": basket["circ_mv_yi"].median(),
        "min_mcap_yi": basket["circ_mv_yi"].min(),
        "max_mcap_yi": basket["circ_mv_yi"].max(),
        "min_amount_yi": basket["amount_yi"].min(),
        "fwd_ret_mean": basket["weekly_forward_return"].mean(),
    }
    return basket[out_cols].reset_index(drop=True), diag


def main():
    fp, um, sw, nm = load_data()

    all_dates = sorted(fp.loc[fp["rebalance_date"] >= GAMMA_START, "rebalance_date"].unique())
    recent_dates = [pd.Timestamp(d) for d in all_dates[-N_RECENT:]]

    print()
    print("=" * 78)
    print(f"v2 basket inspection: last {N_RECENT} γ-regime rebalances")
    print(f"  spec: top-{N_TOP} by z_turnover_resid, sector cap "
          f"{SECTOR_CAP_PCT*100:.0f}% (max {SECTOR_CAP_K}/sector), "
          f"liquidity floor {LIQ_FLOOR_YI*1e4:.0f}万 RMB")
    print(f"  date range: {recent_dates[0].date()} to {recent_dates[-1].date()}")
    print("=" * 78)

    all_baskets, diagnostics = [], []
    for d in recent_dates:
        basket, diag = build_basket(fp, um, sw, nm, d)
        all_baskets.append(basket)
        diagnostics.append(diag)

        print(f"\n--- Rebalance {d.date()} ---")
        print(f"  Universe A pool: {diag['univA_count']}, after 5000万 floor: {diag['post_liq_count']}")
        print(f"  Sectors used: {diag['n_sectors_used']}, max share: "
              f"{diag['max_sector_share']*100:.0f}%, names < 3 RMB: {diag['n_below_3rmb']}")
        print(f"  mcap range: {diag['min_mcap_yi']:.1f} to {diag['max_mcap_yi']:.1f}亿, "
              f"median {diag['median_mcap_yi']:.1f}亿; "
              f"min basket-day amount: {diag['min_amount_yi']:.2f}亿")
        if pd.notna(diag["fwd_ret_mean"]):
            print(f"  Realised next-week basket return: {diag['fwd_ret_mean']*100:+.2f}%")
        else:
            print(f"  Realised next-week basket return: not yet observed")

        disp = basket[[
            "ts_code", "name", "industry_name", "circ_mv_yi", "close",
            "mean_turnover_20d", "z_turnover_resid", "weekly_forward_return",
        ]].copy()
        disp["circ_mv_yi"] = disp["circ_mv_yi"].round(1)
        disp["close"] = disp["close"].round(2)
        disp["mean_turnover_20d"] = disp["mean_turnover_20d"].round(2)
        disp["z_turnover_resid"] = disp["z_turnover_resid"].round(2)
        disp["weekly_forward_return"] = (disp["weekly_forward_return"] * 100).round(2)
        disp.columns = ["ts_code", "name", "sector", "mcap_yi",
                        "px", "turn20d", "z_resid", "fwd_ret_pct"]
        print(disp.to_string(index=False))

    full = pd.concat(all_baskets, ignore_index=True)

    print()
    print("=" * 78)
    print(f"AGGREGATE DIAGNOSTICS across last {N_RECENT} γ baskets")
    print("=" * 78)

    diag_df = pd.DataFrame(diagnostics)
    diag_show = diag_df.copy()
    diag_show["asof"] = diag_show["asof"].dt.date
    diag_show["max_sector_share"] = (diag_show["max_sector_share"] * 100).round(0).astype(int)
    diag_show["fwd_ret_mean"] = (diag_show["fwd_ret_mean"] * 100).round(2)
    print("\nPer-rebalance summary:")
    print(diag_show.to_string(index=False))

    print(f"\nMean unique sectors per basket: {diag_df['n_sectors_used'].mean():.1f}")
    print(f"Mean max sector share: {(diag_df['max_sector_share'].mean() * 100):.1f}%")
    print(f"Total basket-stock-rebalances below 3 RMB: {diag_df['n_below_3rmb'].sum()}")
    print(f"Lowest single-stock close in any basket: {diag_df['min_close'].min():.2f} RMB")
    print(f"Smallest single-stock mcap in any basket: {diag_df['min_mcap_yi'].min():.1f}亿")

    freq = (full.groupby(["ts_code", "name", "industry_name"])
                 .size().reset_index(name="appearances")
                 .sort_values("appearances", ascending=False))

    print(f"\nNames appearing in 5+ of {N_RECENT} baskets (persistent core):")
    persistent = freq.loc[freq["appearances"] >= 5]
    if len(persistent) > 0:
        print(persistent.to_string(index=False))
    else:
        print("  (none, basket fully rotates within ~5 weeks)")

    print(f"\nNames appearing in 8+ of {N_RECENT} baskets (high stickiness):")
    high = freq.loc[freq["appearances"] >= 8]
    print(high.to_string(index=False) if len(high) > 0 else "  (none)")

    sector_total = full["industry_name"].value_counts()
    sector_pct = (sector_total / sector_total.sum() * 100).round(1)
    print(f"\nSector representation across all {N_RECENT} baskets:")
    print(pd.DataFrame({"count": sector_total, "pct": sector_pct}).to_string())

    out = DATA_DIR / "basket_inspection_top20_full_filtered.csv"
    full.to_csv(out, index=False)
    print(f"\nFull basket compositions saved to: {out}")


if __name__ == "__main__":
    main()