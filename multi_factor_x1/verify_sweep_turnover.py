"""
verify_and_sweep.py — Comprehensive verification + concentration + quintile
sweep on the corrected period-level buy-and-hold engine.

Sections:
  1. Load data + pre-load all γ adj_open prices into wide pivot DataFrame
  2. Verify FWL fast residualization matches statsmodels at one date
  3. Pre-compute z_turnover_resid for every γ Wed using fast FWL
  4. Phase 1 IC verification: Spearman corr at each γ date, both against
     panel's weekly_forward_return AND against open-to-open recomputed
  5. Phase 2 concentration sweep: N ∈ {20, 50, 100, 200, 500, 700} at the
     canonical (weekly Wed signal, Thu open entry, sector cap 20%, liq floor)
  6. Phase 2 quintile sweep at top-20: source from Q5/Q4/Q3/Q2/Q1 of the
     residualized-z distribution

Speed approach:
  - One pivot table holds all γ open prices in memory (≈20MB)
  - FWL residualization is ~50x faster than statsmodels OLS with sector dummies
  - Universe + basket lookups are vectorized via wide pivot

Outputs (data/):
  verify_phase1_ic_gamma.csv
  verify_concentration_sweep.csv
  verify_quintile_sweep.csv
  factor_panel_a_gamma_resid.parquet
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"
DAILY_PANEL_DIR = THIS_DIR / "daily_panel"

# ── Spec ───────────────────────────────────────────────────────────────
LIQ_FLOOR_YI = 0.5
COST_RT = 0.0018
SECTOR_CAP_PCT = 0.20
GAMMA_START = pd.Timestamp("2024-04-12")
GAMMA_END = pd.Timestamp("2026-04-29")
PPY = 52  # weekly canonical


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
    files = sorted(DAILY_PANEL_DIR.glob("daily_*.parquet"))
    return sorted(set(pd.Timestamp(f.stem.replace("daily_", "")) for f in files))


def load_gamma_prices(cal, gamma_start, gamma_end):
    """Single pivot of adj_open: rows=trade_date, cols=ts_code."""
    end_with_buffer = gamma_end + pd.Timedelta(days=21)
    gamma_cal = [d for d in cal if gamma_start <= d <= end_with_buffer]
    frames = []
    for d in gamma_cal:
        path = DAILY_PANEL_DIR / f"daily_{d.strftime('%Y-%m-%d')}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["ts_code", "open", "adj_factor"])
        df["adj_factor"] = pd.to_numeric(df["adj_factor"], errors="coerce")
        df["open"] = pd.to_numeric(df["open"], errors="coerce")
        df = df.dropna(subset=["adj_factor", "open"])
        df = df[(df["open"] > 0) & (df["adj_factor"] > 0)]
        df["adj_open"] = df["open"] * df["adj_factor"]
        df["trade_date"] = d
        frames.append(df[["trade_date", "ts_code", "adj_open"]])
    long = pd.concat(frames, ignore_index=True)
    wide = long.pivot_table(
        index="trade_date", columns="ts_code", values="adj_open", aggfunc="first"
    )
    return wide.sort_index()


# ── Fast residualization (FWL) ─────────────────────────────────────────
def fast_residualize(values, control, sector_codes):
    """
    FWL residualize values on (sector dummies + control + intercept).
    Returns residuals as np array.

    Mathematically equivalent to OLS(values ~ C(sector) + control + 1).resid
    by Frisch-Waugh-Lovell theorem. The constant gets absorbed in the
    within-sector demeaning step.
    """
    df = pd.DataFrame({"y": values, "x": control, "s": sector_codes})
    sec_mean = df.groupby("s")[["y", "x"]].transform("mean")
    y_dm = df["y"].values - sec_mean["y"].values
    x_dm = df["x"].values - sec_mean["x"].values
    var_x = float((x_dm * x_dm).sum())
    if var_x <= 0:
        return y_dm
    beta = float((x_dm * y_dm).sum()) / var_x
    return y_dm - beta * x_dm


def verify_fwl(fp, um, sw, asof):
    """Sanity check: FWL residual == statsmodels OLS residual."""
    sub = fp.loc[fp["rebalance_date"] == asof].copy()
    um_sub = um.loc[um["rebalance_date"] == asof, ["ts_code", "in_A"]]
    sub = sub.merge(um_sub, on="ts_code", how="left")
    sub = sub.loc[sub["in_A"] == True].copy()
    m = (sw["in_date"] <= asof) & (sw["out_date"].isna() | (sw["out_date"] > asof))
    sectors = sw.loc[m, ["ts_code", "industry_code"]].drop_duplicates(
        subset="ts_code", keep="first"
    )
    sub = sub.merge(sectors, on="ts_code", how="left")
    sub = sub.dropna(subset=["industry_code", "mean_turnover_20d", "log_mcap"])

    fwl = fast_residualize(
        sub["mean_turnover_20d"].values,
        sub["log_mcap"].values,
        sub["industry_code"].values,
    )

    import statsmodels.api as sm_
    X_num = sub[["log_mcap"]].values.astype(float)
    dummies = pd.get_dummies(sub["industry_code"], drop_first=True).astype(float).values
    X = np.hstack([X_num, dummies])
    X = sm_.add_constant(X, has_constant="add")
    sm_resid = sm_.OLS(sub["mean_turnover_20d"].values.astype(float), X).fit().resid

    return float(np.abs(fwl - sm_resid).max()), len(sub)


# ── Precompute z_turnover_resid for all γ rebalance dates ──────────────
def precompute_resid(fp, um, sw, gamma_dates):
    rows = []
    for asof in gamma_dates:
        sub = fp.loc[fp["rebalance_date"] == asof].copy()
        um_sub = um.loc[um["rebalance_date"] == asof, ["ts_code", "in_A"]]
        sub = sub.merge(um_sub, on="ts_code", how="left")
        sub = sub.loc[sub["in_A"] == True].copy()

        m = (sw["in_date"] <= asof) & (sw["out_date"].isna() | (sw["out_date"] > asof))
        sectors = sw.loc[m, ["ts_code", "industry_code"]].drop_duplicates(
            subset="ts_code", keep="first"
        )
        sub = sub.merge(sectors, on="ts_code", how="left")
        sub_resid = sub.dropna(subset=["industry_code", "mean_turnover_20d", "log_mcap"]).copy()

        if len(sub_resid) < 100:
            continue

        resid = fast_residualize(
            sub_resid["mean_turnover_20d"].values,
            sub_resid["log_mcap"].values,
            sub_resid["industry_code"].values,
        )
        s = resid.std(ddof=0)
        if s == 0 or np.isnan(s):
            continue
        sub_resid["z_turnover_resid"] = -(resid - resid.mean()) / s

        # Re-merge to keep all in_A stocks (z_turnover_resid is NaN for those without sector/factor)
        merged = sub.merge(
            sub_resid[["ts_code", "z_turnover_resid"]], on="ts_code", how="left"
        )
        keep_cols = [
            "rebalance_date", "ts_code", "z_turnover_resid", "amount_yi",
            "industry_code", "weekly_forward_return", "in_A",
        ]
        # Note: industry_code from sub merge above
        for c in keep_cols:
            if c not in merged.columns:
                merged[c] = np.nan
        rows.append(merged[keep_cols])

    return pd.concat(rows, ignore_index=True)


# ── Phase 1 IC verification ────────────────────────────────────────────
def compute_phase1_ic(panel_resid, wide_prices, cal):
    cal_index = {d: i for i, d in enumerate(cal)}
    rows = []
    for sig_d, group in panel_resid.groupby("rebalance_date"):
        if sig_d not in cal_index:
            continue
        si = cal_index[sig_d]
        if si + 6 >= len(cal):
            continue
        entry_d = cal[si + 1]
        exit_d = cal[si + 6]

        # IC vs panel's weekly_forward_return
        sub = group.dropna(subset=["z_turnover_resid", "weekly_forward_return"])
        if len(sub) >= 100:
            ic_panel = sub["z_turnover_resid"].rank().corr(
                sub["weekly_forward_return"].rank()
            )
            n_panel = len(sub)
        else:
            ic_panel, n_panel = np.nan, len(sub)

        # IC vs my open-to-open T+1 forward
        if entry_d in wide_prices.index and exit_d in wide_prices.index:
            ts_codes = group["ts_code"].tolist()
            p_entry = wide_prices.loc[entry_d].reindex(ts_codes)
            p_exit = wide_prices.loc[exit_d].reindex(ts_codes)
            fwd = (p_exit / p_entry - 1)
            df_ic = pd.DataFrame({
                "z": group.set_index("ts_code")["z_turnover_resid"].reindex(ts_codes).values,
                "fwd": fwd.values,
            }).dropna()
            if len(df_ic) >= 100:
                ic_o2o = df_ic["z"].rank().corr(df_ic["fwd"].rank())
                n_o2o = len(df_ic)
            else:
                ic_o2o, n_o2o = np.nan, len(df_ic)
        else:
            ic_o2o, n_o2o = np.nan, 0

        rows.append({
            "date": sig_d,
            "ic_panel": ic_panel, "n_panel": n_panel,
            "ic_o2o": ic_o2o, "n_o2o": n_o2o,
        })
    return pd.DataFrame(rows)


# ── Basket builder (handles concentration N + optional quintile) ───────
def build_basket(date_panel, n_top, sector_cap_pct, liq_floor_yi, quintile=None):
    """
    Build a basket from one date's stock panel.

    quintile: None for full pool, 1..5 where 5 = highest z (most silent).
    """
    sub = date_panel[date_panel["amount_yi"] >= liq_floor_yi].copy()
    sub = sub.dropna(subset=["z_turnover_resid", "industry_code"])
    if len(sub) < n_top:
        return set()

    if quintile is not None:
        try:
            sub["q"] = pd.qcut(sub["z_turnover_resid"], 5, labels=False, duplicates="drop")
        except ValueError:
            return set()
        # qcut: 0 = lowest z (most active = Q1), 4 = highest z (most silent = Q5)
        target = quintile - 1
        sub = sub[sub["q"] == target]
        if len(sub) < n_top:
            return set()

    if sector_cap_pct is not None:
        K = max(1, int(np.floor(n_top * sector_cap_pct)))
        sub = sub.sort_values("z_turnover_resid", ascending=False)
        sub["rank_in_sector"] = sub.groupby("industry_code").cumcount() + 1
        sub = sub[sub["rank_in_sector"] <= K]
        if len(sub) < n_top:
            return set()

    basket = sub.nlargest(n_top, "z_turnover_resid")
    return set(basket["ts_code"])


def buy_and_hold(wide_prices, entry_d, exit_d, codes):
    if entry_d not in wide_prices.index or exit_d not in wide_prices.index:
        return np.nan, 0
    codes_list = list(codes)
    p_entry = wide_prices.loc[entry_d].reindex(codes_list)
    p_exit = wide_prices.loc[exit_d].reindex(codes_list)
    rets = (p_exit / p_entry - 1).dropna()
    if len(rets) == 0:
        return np.nan, 0
    return float(rets.mean()), int(len(rets))


# ── Sweeps ─────────────────────────────────────────────────────────────
def precompute_universes(panel_resid, gamma_signals):
    """Per-date broad and liquid sets. broad = all in_A. liquid = in_A + amt floor."""
    broad_per_date, liquid_per_date = {}, {}
    for d, g in panel_resid.groupby("rebalance_date"):
        broad_per_date[d] = set(g["ts_code"])
        liquid_per_date[d] = set(g[g["amount_yi"] >= LIQ_FLOOR_YI]["ts_code"])
    return broad_per_date, liquid_per_date


def run_one_sweep(panel_resid, wide_prices, cal, gamma_signals, broad_per_date,
                  liquid_per_date, build_kwargs_list, label_key):
    """
    Generic sweep: for each config in build_kwargs_list, run a backtest.
    build_kwargs_list: list of dicts to pass to build_basket. Each dict must
    include `n_top`. label_key is the dict key whose value distinguishes cells.
    """
    cal_index = {d: i for i, d in enumerate(cal)}
    summaries = []
    for cfg in build_kwargs_list:
        rows = []
        prev_basket = None
        for i in range(len(gamma_signals) - 1):
            sig_d = gamma_signals[i]
            next_sig_d = gamma_signals[i + 1]
            if sig_d not in cal_index or next_sig_d not in cal_index:
                continue
            si, nsi = cal_index[sig_d], cal_index[next_sig_d]
            if si + 1 >= len(cal) or nsi + 1 >= len(cal):
                continue
            entry_d = cal[si + 1]
            exit_d = cal[nsi + 1]

            date_panel = panel_resid[panel_resid["rebalance_date"] == sig_d]
            basket = build_basket(date_panel, **cfg)
            if not basket:
                continue

            broad = broad_per_date.get(sig_d, set())
            liquid = liquid_per_date.get(sig_d, set())

            bret_g, _ = buy_and_hold(wide_prices, entry_d, exit_d, basket)
            broad_ret, _ = buy_and_hold(wide_prices, entry_d, exit_d, broad)
            liq_ret, _ = buy_and_hold(wide_prices, entry_d, exit_d, liquid)

            churn = 0.0 if prev_basket is None else 1 - len(prev_basket & basket) / max(len(basket), 1)
            prev_basket = basket
            cost = churn * COST_RT
            bret_n = bret_g - cost if not np.isnan(bret_g) else np.nan

            rows.append({
                "signal_date": sig_d, label_key: cfg.get(label_key),
                "basket_ret_gross": bret_g, "basket_ret_net": bret_n,
                "broad_ret": broad_ret, "liquid_ret": liq_ret,
                "churn": churn, "cost": cost, "n_basket": len(basket),
            })

        df = pd.DataFrame(rows)
        df = df.dropna(subset=["basket_ret_net", "broad_ret", "liquid_ret"])
        df["active_vs_broad"] = df["basket_ret_net"] - df["broad_ret"]
        df["active_vs_liquid"] = df["basket_ret_net"] - df["liquid_ret"]

        def _ir(s):
            if len(s) < 4 or s.std(ddof=1) == 0:
                return np.nan
            return s.mean() / s.std(ddof=1) * np.sqrt(PPY)

        summary = {
            label_key: cfg.get(label_key),
            "n_periods": len(df),
            "ir_vs_broad": _ir(df["active_vs_broad"]),
            "ir_vs_liquid": _ir(df["active_vs_liquid"]),
            "active_vs_broad_ann": df["active_vs_broad"].mean() * PPY,
            "active_vs_liquid_ann": df["active_vs_liquid"].mean() * PPY,
            "basket_ret_ann_net": df["basket_ret_net"].mean() * PPY,
            "broad_ret_ann": df["broad_ret"].mean() * PPY,
            "liquid_ret_ann": df["liquid_ret"].mean() * PPY,
            "te_vs_liquid_ann": df["active_vs_liquid"].std(ddof=1) * np.sqrt(PPY),
            "mean_churn": df["churn"].mean(),
        }
        # Carry through any other config keys for context
        for k, v in cfg.items():
            if k not in summary:
                summary[k] = v
        summaries.append(summary)
    return pd.DataFrame(summaries)


# ── Pretty printing ────────────────────────────────────────────────────
def show_summary(df, key, drop_cols=()):
    show = df.copy()
    for col, scale in [
        ("ir_vs_broad", 1), ("ir_vs_liquid", 1),
        ("active_vs_broad_ann", 100), ("active_vs_liquid_ann", 100),
        ("basket_ret_ann_net", 100), ("broad_ret_ann", 100), ("liquid_ret_ann", 100),
        ("te_vs_liquid_ann", 100), ("mean_churn", 100),
    ]:
        if col in show.columns:
            show[col] = (show[col] * scale).round(2)
    show = show.drop(columns=list(drop_cols), errors="ignore")
    print(show.to_string(index=False))


# ── Main ───────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print("Loading data...")
    fp, um, sw = load_data()
    cal = load_calendar()
    print(f"  factor_panel: {fp.shape}, calendar: {len(cal)} days")

    gamma_signals = sorted(
        fp.loc[
            (fp["rebalance_date"] >= GAMMA_START)
            & (fp["rebalance_date"] <= GAMMA_END),
            "rebalance_date",
        ].unique()
    )
    gamma_signals = [pd.Timestamp(d) for d in gamma_signals]
    print(f"  γ signals: {len(gamma_signals)} ({gamma_signals[0].date()} to {gamma_signals[-1].date()})")

    print(f"\nLoading γ prices into wide pivot...")
    wide_prices = load_gamma_prices(cal, GAMMA_START, GAMMA_END)
    print(f"  shape: {wide_prices.shape} | runtime: {time.time()-t0:.1f}s")

    print(f"\nVerifying FWL == statsmodels OLS at one date...")
    max_diff, n = verify_fwl(fp, um, sw, gamma_signals[0])
    if max_diff < 1e-6:
        print(f"  PASS: max |residual diff| = {max_diff:.2e} (n={n} stocks)")
    else:
        print(f"  WARNING: max |residual diff| = {max_diff:.2e}, FWL may have a bug. Investigate.")

    print(f"\nPre-computing z_turnover_resid for {len(gamma_signals)} γ dates...")
    t1 = time.time()
    panel_resid = precompute_resid(fp, um, sw, gamma_signals)
    print(f"  done. shape: {panel_resid.shape} | runtime: {time.time()-t1:.1f}s")

    broad_per_date, liquid_per_date = precompute_universes(panel_resid, gamma_signals)

    # ─── Phase 1 IC ────────────────────────────────────────────────────
    print(f"\n{'='*78}")
    print("PHASE 1 IC VERIFICATION (γ regime, weekly Wed signal)")
    print('='*78)
    ic_df = compute_phase1_ic(panel_resid, wide_prices, cal)

    for col, label in [
        ("ic_panel", "IC vs panel weekly_forward_return"),
        ("ic_o2o", "IC vs my open-to-open T+1 forward return"),
    ]:
        ic_clean = ic_df[col].dropna()
        if len(ic_clean) == 0:
            print(f"  {label}: no valid observations")
            continue
        m = ic_clean.mean()
        s = ic_clean.std(ddof=1)
        n = len(ic_clean)
        t = m / (s / np.sqrt(n)) if s > 0 else np.nan
        ci_lo, ci_hi = m - 1.96 * s / np.sqrt(n), m + 1.96 * s / np.sqrt(n)
        sign_pct = (ic_clean > 0).mean() * 100
        print(f"  {label}:")
        print(f"    mean={m:+.4f}, std={s:.4f}, t={t:+.2f}, "
              f"95% CI=[{ci_lo:+.4f}, {ci_hi:+.4f}], n_dates={n}, positive_dates={sign_pct:.0f}%")

    # ─── Phase 2 concentration sweep ───────────────────────────────────
    print(f"\n{'='*78}")
    print("PHASE 2 CONCENTRATION SWEEP")
    print("  config: weekly Wed → Thu open entry, sector cap 20%, liq floor 5000万 RMB, γ regime")
    print('='*78)
    n_values = [20, 50, 100, 200, 500, 700]
    cfgs = [{"n_top": n, "sector_cap_pct": SECTOR_CAP_PCT, "liq_floor_yi": LIQ_FLOOR_YI}
            for n in n_values]
    conc_summary = run_one_sweep(
        panel_resid, wide_prices, cal, gamma_signals,
        broad_per_date, liquid_per_date, cfgs, label_key="n_top",
    )
    show_summary(conc_summary, "n_top",
                 drop_cols=("sector_cap_pct", "liq_floor_yi"))

    # ─── Phase 2 quintile sweep ────────────────────────────────────────
    print(f"\n{'='*78}")
    print("PHASE 2 QUINTILE SWEEP")
    print("  top-20, sector cap 20%, liq floor 5000万 RMB, γ regime")
    print("  Q5 = highest z (most silent), Q1 = lowest z (most active)")
    print('='*78)
    cfgs_q = [{"n_top": 20, "sector_cap_pct": SECTOR_CAP_PCT,
               "liq_floor_yi": LIQ_FLOOR_YI, "quintile": q}
              for q in [5, 4, 3, 2, 1]]
    quint_summary = run_one_sweep(
        panel_resid, wide_prices, cal, gamma_signals,
        broad_per_date, liquid_per_date, cfgs_q, label_key="quintile",
    )
    show_summary(quint_summary, "quintile",
                 drop_cols=("n_top", "sector_cap_pct", "liq_floor_yi"))

    # ─── Save ──────────────────────────────────────────────────────────
    ic_df.to_csv(DATA_DIR / "verify_phase1_ic_gamma.csv", index=False)
    conc_summary.to_csv(DATA_DIR / "verify_concentration_sweep.csv", index=False)
    quint_summary.to_csv(DATA_DIR / "verify_quintile_sweep.csv", index=False)
    panel_resid.to_parquet(DATA_DIR / "factor_panel_a_gamma_resid.parquet")

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")
    print(f"Saved:")
    print(f"  {DATA_DIR / 'verify_phase1_ic_gamma.csv'}")
    print(f"  {DATA_DIR / 'verify_concentration_sweep.csv'}")
    print(f"  {DATA_DIR / 'verify_quintile_sweep.csv'}")
    print(f"  {DATA_DIR / 'factor_panel_a_gamma_resid.parquet'}")


if __name__ == "__main__":
    main()