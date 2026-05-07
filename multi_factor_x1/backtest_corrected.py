"""
backtest_corrected.py — Honest period-level buy-and-hold backtester for v2,
plus frequency × entry-day robustness sweep.

Replaces yesterday's daily-rebalance-EW aggregation in top_n_filtered.py
with period-level buy-and-hold. For each rebalance period:
  1. Pick basket at signal date (Wed close) using z_turnover_resid filtered
     by 5000万 RMB liquidity floor and 20% sector cap, top-20.
  2. Enter at signal_date + entry_offset trading days (open).
  3. Hold without intra-period rebalancing.
  4. Exit at next-signal_date + entry_offset trading days (open).
  5. Period gross return = mean over basket of (open[exit] / open[entry] - 1).
  6. Period net return = gross - churn × 0.18%.
  7. Aggregate at period level. IR = mean(active) / std(active) × √(periods_per_year).

Sweep:
  Frequency K ∈ {1 (weekly), 2 (biweekly), 4 (monthly)}.
  Entry day ∈ {thu, fri, mon, tue, wed} = signal-day-offset {1, 2, 3, 4, 5} td.
  All 15 cells in γ regime (2024-04-12 to 2026-04-29).

Universe: A (in_A from universe_membership_three).

Outputs:
  data/backtest_corrected_summary.csv     — one row per (freq, entry_day, K, ppy)
  data/backtest_corrected_period_returns.csv  — every period × cell

Run from multi_factor_x1/.
"""
import bisect
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"
DAILY_PANEL_DIR = THIS_DIR / "daily_panel"

# ── Strategy spec ──────────────────────────────────────────────────────
N_TOP = 20
SECTOR_CAP_PCT = 0.20
SECTOR_CAP_K = max(1, int(np.floor(N_TOP * SECTOR_CAP_PCT)))  # = 4
LIQ_FLOOR_YI = 0.5  # 5000万 RMB
COST_RT = 0.0018
GAMMA_START = pd.Timestamp("2024-04-12")
GAMMA_END = pd.Timestamp("2026-04-29")

# ── Sweep config ───────────────────────────────────────────────────────
FREQUENCIES = {"weekly": 1, "biweekly": 2, "monthly": 4}
ENTRY_OFFSETS = {  # signal at Wed → entry at Wed+offset trading days (open)
    "thu": 1,
    "fri": 2,
    "mon": 3,
    "tue": 4,
    "wed": 5,
}


# ── Loaders ────────────────────────────────────────────────────────────
def load_data():
    fp = pd.read_parquet(DATA_DIR / "factor_panel_a.parquet")
    um = pd.read_parquet(DATA_DIR / "universe_membership_three.parquet")
    sw = pd.read_parquet(DATA_DIR / "sw_l1_membership.parquet")
    fp["rebalance_date"] = pd.to_datetime(fp["rebalance_date"])
    um["rebalance_date"] = pd.to_datetime(um["rebalance_date"])
    sw["in_date"] = pd.to_datetime(sw["in_date"], format="%Y%m%d", errors="coerce")
    sw["out_date"] = pd.to_datetime(sw["out_date"], format="%Y%m%d", errors="coerce")
    return fp, um, sw


def load_calendar():
    """Return sorted list of trading dates from daily panel file listing."""
    files = sorted(DAILY_PANEL_DIR.glob("daily_*.parquet"))
    dates = [pd.Timestamp(f.stem.replace("daily_", "")) for f in files]
    return sorted(set(dates))


@lru_cache(maxsize=None)
def _get_daily_open_prices(date_str: str):
    """Return adj_open as Series indexed by ts_code for one trading day."""
    path = DAILY_PANEL_DIR / f"daily_{date_str}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df["adj_factor"] = pd.to_numeric(df["adj_factor"], errors="coerce")
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df = df.dropna(subset=["adj_factor", "open"])
    df = df[(df["open"] > 0) & (df["adj_factor"] > 0)]
    df["adj_open"] = df["open"] * df["adj_factor"]
    return df.set_index("ts_code")["adj_open"]


# ── Basket construction ────────────────────────────────────────────────
def pit_industry(sw, asof):
    m = (sw["in_date"] <= asof) & (sw["out_date"].isna() | (sw["out_date"] > asof))
    return sw.loc[m, ["ts_code", "industry_code"]].drop_duplicates(
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


def build_basket_and_universes(fp, um, sw, signal_date):
    """At signal_date, return (basket_codes, broad_codes, liquid_codes)."""
    sub = fp.loc[fp["rebalance_date"] == signal_date].copy()
    um_sub = um.loc[um["rebalance_date"] == signal_date, ["ts_code", "in_A"]]
    sub = sub.merge(um_sub, on="ts_code", how="left")
    sub = sub.loc[sub["in_A"] == True].copy()

    broad_codes = set(sub["ts_code"])

    liquid = sub.loc[sub["amount_yi"] >= LIQ_FLOOR_YI].copy()
    liquid_codes = set(liquid["ts_code"])

    sectors = pit_industry(sw, signal_date)
    liquid = liquid.merge(sectors, on="ts_code", how="left")
    liquid = liquid.dropna(
        subset=["industry_code", "mean_turnover_20d", "log_mcap"]
    ).copy()

    if len(liquid) < N_TOP:
        return None, broad_codes, liquid_codes

    liquid = residualize_one_date(
        liquid,
        factor_col="mean_turnover_20d",
        numeric_controls=["log_mcap"],
        categorical_control="industry_code",
    )
    s = liquid["resid"].std(ddof=0)
    if not s or np.isnan(s):
        return None, broad_codes, liquid_codes
    liquid["z_turnover_resid"] = -(liquid["resid"] - liquid["resid"].mean()) / s

    liquid = liquid.sort_values("z_turnover_resid", ascending=False)
    liquid["rank_in_sector"] = liquid.groupby("industry_code").cumcount() + 1
    candidates = liquid.loc[liquid["rank_in_sector"] <= SECTOR_CAP_K]
    basket = candidates.nlargest(N_TOP, "z_turnover_resid")
    return set(basket["ts_code"]), broad_codes, liquid_codes


def buy_and_hold_return(entry_date, exit_date, ts_codes):
    """EW mean of buy-and-hold returns from entry_date open to exit_date open."""
    if not ts_codes:
        return np.nan, 0
    p_entry = _get_daily_open_prices(entry_date.strftime("%Y-%m-%d"))
    p_exit = _get_daily_open_prices(exit_date.strftime("%Y-%m-%d"))
    if p_entry is None or p_exit is None:
        return np.nan, 0
    codes = list(ts_codes)
    common = p_entry.index.intersection(codes).intersection(p_exit.index)
    if len(common) == 0:
        return np.nan, 0
    rets = p_exit.loc[common] / p_entry.loc[common] - 1
    return float(rets.mean()), int(len(common))


# ── Sweep ──────────────────────────────────────────────────────────────
def run_one_config(fp, um, sw, gamma_signals, cal, K, entry_offset):
    """Run one (frequency K, entry_offset) cell. Returns period-level DataFrame."""
    signal_dates = gamma_signals[::K]
    rows = []
    prev_basket = None

    for i in range(len(signal_dates) - 1):
        sig_d = signal_dates[i]
        next_sig_d = signal_dates[i + 1]

        sig_idx = bisect.bisect_left(cal, sig_d)
        next_sig_idx = bisect.bisect_left(cal, next_sig_d)

        if sig_idx >= len(cal) or cal[sig_idx] != sig_d:
            continue
        if next_sig_idx >= len(cal) or cal[next_sig_idx] != next_sig_d:
            continue
        if sig_idx + entry_offset >= len(cal):
            continue
        if next_sig_idx + entry_offset >= len(cal):
            continue

        entry_d = cal[sig_idx + entry_offset]
        exit_d = cal[next_sig_idx + entry_offset]

        basket, broad, liquid = build_basket_and_universes(fp, um, sw, sig_d)
        if basket is None:
            continue

        bret_g, n_b = buy_and_hold_return(entry_d, exit_d, basket)
        broad_ret, n_br = buy_and_hold_return(entry_d, exit_d, broad)
        liq_ret, n_lq = buy_and_hold_return(entry_d, exit_d, liquid)

        if prev_basket is None:
            churn = 0.0
        else:
            churn = 1 - len(prev_basket & basket) / max(len(basket), 1)
        prev_basket = basket

        cost = churn * COST_RT
        bret_n = bret_g - cost if pd.notna(bret_g) else np.nan

        rows.append({
            "signal_date": sig_d,
            "entry_date": entry_d,
            "exit_date": exit_d,
            "basket_ret_gross": bret_g,
            "basket_ret_net": bret_n,
            "broad_ret": broad_ret,
            "liquid_ret": liq_ret,
            "churn": churn,
            "cost": cost,
            "n_basket": n_b,
            "n_broad": n_br,
            "n_liquid": n_lq,
        })

    return pd.DataFrame(rows)


def aggregate(df, periods_per_year):
    df = df.dropna(subset=["basket_ret_net", "broad_ret", "liquid_ret"]).copy()
    df["active_vs_broad"] = df["basket_ret_net"] - df["broad_ret"]
    df["active_vs_liquid"] = df["basket_ret_net"] - df["liquid_ret"]

    def _ir(s):
        if len(s) < 4 or s.std(ddof=1) == 0:
            return np.nan
        return s.mean() / s.std(ddof=1) * np.sqrt(periods_per_year)

    return {
        "n_periods": len(df),
        "ir_vs_broad": _ir(df["active_vs_broad"]),
        "ir_vs_liquid": _ir(df["active_vs_liquid"]),
        "active_vs_broad_ann": df["active_vs_broad"].mean() * periods_per_year,
        "active_vs_liquid_ann": df["active_vs_liquid"].mean() * periods_per_year,
        "basket_ret_ann_net": df["basket_ret_net"].mean() * periods_per_year,
        "basket_ret_ann_gross": df["basket_ret_gross"].mean() * periods_per_year,
        "broad_ret_ann": df["broad_ret"].mean() * periods_per_year,
        "liquid_ret_ann": df["liquid_ret"].mean() * periods_per_year,
        "te_vs_liquid_ann": df["active_vs_liquid"].std(ddof=1) * np.sqrt(periods_per_year),
        "mean_churn": df["churn"].mean(),
        "mean_cost_ann": df["cost"].mean() * periods_per_year,
    }


# ── Pretty pivot tables ────────────────────────────────────────────────
ENTRY_ORDER = list(ENTRY_OFFSETS.keys())
FREQ_ORDER = list(FREQUENCIES.keys())


def print_pivot(summary_df, value_col, label, scale=1.0, fmt="{:+.2f}", suffix=""):
    pivot = summary_df.pivot(index="frequency", columns="entry_day", values=value_col)
    pivot = pivot.reindex(FREQ_ORDER)[ENTRY_ORDER] * scale
    print(f"\n{label}:")
    print(pivot.map(lambda x: fmt.format(x) + suffix if pd.notna(x) else "—").to_string())


# ── Main ───────────────────────────────────────────────────────────────
def main():
    fp, um, sw = load_data()
    cal = load_calendar()
    print(f"Trading calendar: {len(cal)} days "
          f"({cal[0].date()} to {cal[-1].date()})")

    gamma_signals = sorted(
        fp.loc[
            (fp["rebalance_date"] >= GAMMA_START)
            & (fp["rebalance_date"] <= GAMMA_END),
            "rebalance_date",
        ].unique()
    )
    gamma_signals = [pd.Timestamp(d) for d in gamma_signals]
    print(f"γ Wed signal dates: {len(gamma_signals)} "
          f"({gamma_signals[0].date()} to {gamma_signals[-1].date()})")

    summaries, period_dfs = [], []
    for freq_name, K in FREQUENCIES.items():
        ppy = 52 / K
        for entry_name, offset in ENTRY_OFFSETS.items():
            print(f"\n  freq={freq_name} (K={K}), entry={entry_name} (+{offset}td)...",
                  end="", flush=True)
            df = run_one_config(fp, um, sw, gamma_signals, cal, K, offset)
            df["frequency"] = freq_name
            df["entry_day"] = entry_name
            df["K"] = K
            period_dfs.append(df)

            summ = aggregate(df, ppy)
            summ["frequency"] = freq_name
            summ["K"] = K
            summ["entry_day"] = entry_name
            summ["entry_offset_td"] = offset
            summ["periods_per_year"] = ppy
            summaries.append(summ)

            print(f"  n={summ['n_periods']:>3}, "
                  f"IR_liq={summ['ir_vs_liquid']:+.2f}, "
                  f"IR_broad={summ['ir_vs_broad']:+.2f}, "
                  f"active_liq={summ['active_vs_liquid_ann']*100:+.1f}%")

    summary_df = pd.DataFrame(summaries)

    print("\n" + "=" * 100)
    print("CORRECTED PERIOD-LEVEL BACKTEST: top-20 v2 (z_turnover_resid + 20% cap + 5000万 floor)")
    print(f"  γ regime, open-to-open buy-and-hold, no intra-period rebalance,"
          f" cost = churn × {COST_RT*100:.2f}%")
    print("=" * 100)

    print_pivot(summary_df, "ir_vs_liquid",
                "IR vs LIQUID benchmark (factor attribution, primary metric)",
                fmt="{:+.2f}")
    print_pivot(summary_df, "ir_vs_broad",
                "IR vs BROAD benchmark (deployment metric, includes rotation alpha)",
                fmt="{:+.2f}")
    print_pivot(summary_df, "active_vs_liquid_ann",
                "Annualized active vs liquid (%)",
                scale=100, fmt="{:+.2f}", suffix="%")
    print_pivot(summary_df, "basket_ret_ann_net",
                "Annualized basket return, net of cost (%)",
                scale=100, fmt="{:+.2f}", suffix="%")
    print_pivot(summary_df, "liquid_ret_ann",
                "Annualized liquid-benchmark return (%)",
                scale=100, fmt="{:+.2f}", suffix="%")
    print_pivot(summary_df, "te_vs_liquid_ann",
                "Tracking error vs liquid (%)",
                scale=100, fmt="{:.2f}", suffix="%")
    print_pivot(summary_df, "mean_churn",
                "Mean churn per rebalance (%)",
                scale=100, fmt="{:.1f}", suffix="%")

    summary_df.to_csv(DATA_DIR / "backtest_corrected_summary.csv", index=False)
    pd.concat(period_dfs, ignore_index=True).to_csv(
        DATA_DIR / "backtest_corrected_period_returns.csv", index=False
    )
    print(f"\nSaved: {DATA_DIR / 'backtest_corrected_summary.csv'}")
    print(f"Saved: {DATA_DIR / 'backtest_corrected_period_returns.csv'}")


if __name__ == "__main__":
    main()