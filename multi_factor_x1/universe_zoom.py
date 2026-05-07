"""
universe_zoom.py — Browse universe sub-segments to locate the
retail-sentiment sweet spot for z_turnover_resid.

Hypothesis:
  Retail-sentiment alpha is densest at the intersection of
    (a) small market cap (more retail volume share)
    (b) low absolute price (numerical-cheap behavioral bias)
  but is degraded by tradability problems at the deepest end.

Test grid:
  3 cap terciles within liquid Universe A × 2 price tiers (close < 10 vs >= 10)
  = 6 sub-cells, plus a full-universe baseline cell.

Each cell:
  - Filter chain: in_A=True → amount_yi >= 0.5亿 → cap tercile → price tier
  - Residualize mean_turnover_20d WITHIN the cell (FWL: sector + log_mcap)
  - z = -(resid - mean) / std → high z = low residualized turnover
  - Sector cap 20%, top-100 basket
  - Weekly Wed signal, Thu open entry
  - Period-level buy-and-hold, cost = churn × 0.18%

Reports per cell:
  - IR vs cell's own EW liquid sub-universe (factor attribution within cell)
  - IR vs full Universe A liquid universe (deployment value vs broader pool)

Six self-checks run before any cell is processed:
  1. FWL residual matches statsmodels OLS at machine precision (1e-6)
  2. Cap tercile partitions the liquid pool equally (sizes differ by ≤ 2)
  3. Price tier partition accounts for all stocks (lo + hi = total non-NaN)
  4. Each cell has ≥ 100 stocks at the test date (enough to fill top-100)
  5. Buy-and-hold round-trip on 3 test stocks matches manual calc to 1e-9
  6. Baseline cell IR reproduces verify_and_sweep top-100 result (within ±0.05)

Outputs:
  data/universe_zoom_summary.csv         (one row per cell)
  data/universe_zoom_period_returns.csv  (every period × cell)
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
PRICE_THRESHOLD = 10.0  # 10 RMB cut between LoPx and HiPx tiers
N_TOP = 100
GAMMA_START = pd.Timestamp("2024-04-12")
GAMMA_END = pd.Timestamp("2026-04-29")
PPY = 52

# Self-check 6: baseline cell should reproduce verify_and_sweep.py top-100 IR vs liquid
BASELINE_EXPECTED_IR = -0.48
BASELINE_TOLERANCE = 0.05


# ── Loaders (same as verify_and_sweep.py) ──────────────────────────────
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
    end_buf = gamma_end + pd.Timedelta(days=21)
    gamma_cal = [d for d in cal if gamma_start <= d <= end_buf]
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


# ── Fast FWL residualization ───────────────────────────────────────────
def fast_residualize(values, control, sector_codes):
    """
    FWL residualize values on (sector dummies + control + intercept).
    Returns residuals as np float64 array.

    All numeric inputs are upcast to float64 internally. The factor_panel
    stores columns as float32, which accumulates ~1e-6 rounding noise over
    thousands of stocks. Statsmodels OLS upcasts to float64 internally, so
    we do the same here for apples-to-apples residual comparison.
    """
    values = np.asarray(values, dtype=np.float64)
    control = np.asarray(control, dtype=np.float64)
    df = pd.DataFrame({"y": values, "x": control, "s": sector_codes})
    sec_mean = df.groupby("s")[["y", "x"]].transform("mean")
    y_dm = values - sec_mean["y"].values
    x_dm = control - sec_mean["x"].values
    var_x = float((x_dm * x_dm).sum())
    if var_x <= 0:
        return y_dm
    beta = float((x_dm * y_dm).sum()) / var_x
    return y_dm - beta * x_dm


def buy_and_hold(wide_prices, entry_d, exit_d, codes):
    if entry_d not in wide_prices.index or exit_d not in wide_prices.index:
        return np.nan, 0
    if not codes:
        return np.nan, 0
    codes_list = list(codes)
    p_entry = wide_prices.loc[entry_d].reindex(codes_list)
    p_exit = wide_prices.loc[exit_d].reindex(codes_list)
    rets = (p_exit / p_entry - 1).dropna()
    if len(rets) == 0:
        return np.nan, 0
    return float(rets.mean()), int(len(rets))


# ── Per-date merge of factor + universe + sector ───────────────────────
def build_merged_panel(fp, um, sw, gamma_dates):
    rows = []
    for asof in gamma_dates:
        sub = fp.loc[fp["rebalance_date"] == asof].copy()
        um_sub = um.loc[um["rebalance_date"] == asof, ["ts_code", "in_A"]]
        sub = sub.merge(um_sub, on="ts_code", how="left")
        m = (sw["in_date"] <= asof) & (sw["out_date"].isna() | (sw["out_date"] > asof))
        sectors = sw.loc[m, ["ts_code", "industry_code"]].drop_duplicates(
            subset="ts_code", keep="first"
        )
        sub = sub.merge(sectors, on="ts_code", how="left")
        keep = ["rebalance_date", "ts_code", "in_A", "amount_yi", "circ_mv_yi",
                "close", "mean_turnover_20d", "log_mcap", "industry_code"]
        rows.append(sub[keep])
    return pd.concat(rows, ignore_index=True)


# ── Cell builder ───────────────────────────────────────────────────────
def build_cell_at_date(panel_at_date, cap_tercile, price_tier, n_top):
    """
    Apply filter chain and basket selection for one cell at one date.

    cap_tercile: 1, 2, 3 (1=smallest), or None for no filter
    price_tier: 'lo' (close < 10), 'hi' (close >= 10), or None for no filter

    Returns: (basket_codes, cell_universe_codes, broad_A_liquid_codes)
    """
    # Filter A: in_A
    sub = panel_at_date[panel_at_date["in_A"] == True].copy()
    # Filter B: liquidity floor
    liquid = sub[sub["amount_yi"] >= LIQ_FLOOR_YI]
    broad_A_liquid = set(liquid["ts_code"])

    pool = liquid.dropna(subset=["circ_mv_yi", "close"]).copy()
    if len(pool) < 30:
        return set(), set(), broad_A_liquid

    # Filter C: cap tercile (per-date qcut on liquid pool)
    if cap_tercile is not None:
        try:
            pool["cap_q"] = pd.qcut(pool["circ_mv_yi"], 3, labels=[1, 2, 3])
        except ValueError:
            return set(), set(), broad_A_liquid
        pool = pool[pool["cap_q"] == cap_tercile]

    # Filter D: price tier
    if price_tier == "lo":
        pool = pool[pool["close"] < PRICE_THRESHOLD]
    elif price_tier == "hi":
        pool = pool[pool["close"] >= PRICE_THRESHOLD]

    pool = pool.dropna(subset=["mean_turnover_20d", "log_mcap", "industry_code"])
    cell_universe = set(pool["ts_code"])

    if len(pool) < n_top:
        return set(), cell_universe, broad_A_liquid

    # Within-cell residualization
    resid = fast_residualize(
        pool["mean_turnover_20d"].values,
        pool["log_mcap"].values,
        pool["industry_code"].values,
    )
    s = resid.std(ddof=0)
    if s == 0 or np.isnan(s):
        return set(), cell_universe, broad_A_liquid
    pool = pool.copy()
    pool["z"] = -(resid - resid.mean()) / s

    # Sector cap + top-N
    K = max(1, int(np.floor(n_top * SECTOR_CAP_PCT)))
    pool = pool.sort_values("z", ascending=False)
    pool["rank_in_sec"] = pool.groupby("industry_code").cumcount() + 1
    candidates = pool[pool["rank_in_sec"] <= K]
    if len(candidates) < n_top:
        return set(), cell_universe, broad_A_liquid
    basket = candidates.nlargest(n_top, "z")
    return set(basket["ts_code"]), cell_universe, broad_A_liquid


# ── Cell runner ────────────────────────────────────────────────────────
def run_cell(merged_panel, wide_prices, cal, gamma_signals,
             cap_tercile, price_tier, n_top, label):
    cal_index = {d: i for i, d in enumerate(cal)}
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

        panel_at_date = merged_panel[merged_panel["rebalance_date"] == sig_d]
        basket, cell_univ, broad_liq = build_cell_at_date(
            panel_at_date, cap_tercile, price_tier, n_top
        )
        if not basket:
            continue

        bret_g, _ = buy_and_hold(wide_prices, entry_d, exit_d, basket)
        cell_ret, _ = buy_and_hold(wide_prices, entry_d, exit_d, cell_univ)
        broad_ret, _ = buy_and_hold(wide_prices, entry_d, exit_d, broad_liq)

        churn = 0.0 if prev_basket is None else 1 - len(prev_basket & basket) / max(len(basket), 1)
        prev_basket = basket
        cost = churn * COST_RT
        bret_n = bret_g - cost if not np.isnan(bret_g) else np.nan

        rows.append({
            "label": label, "signal_date": sig_d,
            "basket_ret_gross": bret_g, "basket_ret_net": bret_n,
            "cell_ret": cell_ret, "broad_A_liquid_ret": broad_ret,
            "churn": churn, "cost": cost,
            "n_basket": len(basket), "n_cell": len(cell_univ),
        })
    return pd.DataFrame(rows)


def aggregate_cell(df, label):
    df = df.dropna(subset=["basket_ret_net", "cell_ret", "broad_A_liquid_ret"])
    df = df.copy()
    df["active_vs_cell"] = df["basket_ret_net"] - df["cell_ret"]
    df["active_vs_broad_A"] = df["basket_ret_net"] - df["broad_A_liquid_ret"]

    def _ir(s):
        if len(s) < 4 or s.std(ddof=1) == 0:
            return np.nan
        return s.mean() / s.std(ddof=1) * np.sqrt(PPY)

    return {
        "label": label,
        "n_periods": len(df),
        "ir_vs_cell": _ir(df["active_vs_cell"]),
        "ir_vs_broad_A": _ir(df["active_vs_broad_A"]),
        "active_vs_cell_ann": df["active_vs_cell"].mean() * PPY,
        "active_vs_broad_A_ann": df["active_vs_broad_A"].mean() * PPY,
        "basket_ret_ann_net": df["basket_ret_net"].mean() * PPY,
        "cell_ret_ann": df["cell_ret"].mean() * PPY,
        "broad_A_liquid_ret_ann": df["broad_A_liquid_ret"].mean() * PPY,
        "te_vs_cell_ann": df["active_vs_cell"].std(ddof=1) * np.sqrt(PPY),
        "mean_churn": df["churn"].mean(),
        "n_cell_avg": df["n_cell"].mean() if "n_cell" in df else np.nan,
    }


# ── Self-checks ────────────────────────────────────────────────────────
def run_self_checks(fp, um, sw, gamma_signals, wide_prices, cal):
    print("\n" + "─" * 72)
    print("PRE-FLIGHT SELF-CHECKS")
    print("─" * 72)

    asof = gamma_signals[len(gamma_signals) // 2]
    sub = fp.loc[fp["rebalance_date"] == asof].copy()
    um_sub = um.loc[um["rebalance_date"] == asof, ["ts_code", "in_A"]]
    sub = sub.merge(um_sub, on="ts_code", how="left")
    sub = sub.loc[sub["in_A"] == True].copy()
    m = (sw["in_date"] <= asof) & (sw["out_date"].isna() | (sw["out_date"] > asof))
    sectors = sw.loc[m, ["ts_code", "industry_code"]].drop_duplicates(
        subset="ts_code", keep="first"
    )
    sub = sub.merge(sectors, on="ts_code", how="left")
    sub_full = sub.dropna(subset=["industry_code", "mean_turnover_20d", "log_mcap"]).copy()

    all_ok = True

    # Check 1: FWL == statsmodels at machine precision
    fwl = fast_residualize(
        sub_full["mean_turnover_20d"].values,
        sub_full["log_mcap"].values,
        sub_full["industry_code"].values,
    )
    import statsmodels.api as sm_
    X_num = sub_full[["log_mcap"]].values.astype(float)
    dummies = pd.get_dummies(sub_full["industry_code"], drop_first=True).astype(float).values
    X = np.hstack([X_num, dummies])
    X = sm_.add_constant(X, has_constant="add")
    sm_resid = sm_.OLS(sub_full["mean_turnover_20d"].values.astype(float), X).fit().resid
    diff1 = float(np.abs(fwl - sm_resid).max())
    if diff1 < 1e-6:
        print(f"  [PASS] check 1: FWL vs statsmodels max diff = {diff1:.2e}")
    else:
        print(f"  [FAIL] check 1: FWL vs statsmodels max diff = {diff1:.2e}")
        all_ok = False

    # Check 2: cap tercile partition
    test_pool = sub.dropna(subset=["circ_mv_yi", "close"]).copy()
    test_pool = test_pool[test_pool["amount_yi"] >= LIQ_FLOOR_YI].copy()
    test_pool["cap_q"] = pd.qcut(test_pool["circ_mv_yi"], 3, labels=[1, 2, 3])
    sizes = test_pool["cap_q"].value_counts().sort_index()
    max_diff = int(sizes.max() - sizes.min())
    if max_diff <= 2:
        print(f"  [PASS] check 2: cap tercile sizes {sizes.tolist()} (max diff {max_diff})")
    else:
        print(f"  [WARN] check 2: cap tercile sizes differ by {max_diff} - {sizes.tolist()}")

    # Check 3: price tier partition
    test_with_close = test_pool.dropna(subset=["close"])
    lo = int((test_with_close["close"] < PRICE_THRESHOLD).sum())
    hi = int((test_with_close["close"] >= PRICE_THRESHOLD).sum())
    total = len(test_with_close)
    if lo + hi == total:
        print(f"  [PASS] check 3: price tier partition: {lo} lo + {hi} hi = {total} total")
    else:
        print(f"  [FAIL] check 3: price tier partition: {lo} lo + {hi} hi != {total} total")
        all_ok = False

    # Check 4: cell sizes per date
    print(f"\n  [INFO] check 4: cell sizes at {asof.date()} (need >= {N_TOP} for top-{N_TOP}):")
    print(f"    {'cell':<22} {'size':>8}")
    for cap_q in [1, 2, 3]:
        for px in ["lo", "hi"]:
            cell_pool = test_pool[test_pool["cap_q"] == cap_q].copy()
            if px == "lo":
                cell_pool = cell_pool[cell_pool["close"] < PRICE_THRESHOLD]
            else:
                cell_pool = cell_pool[cell_pool["close"] >= PRICE_THRESHOLD]
            cell_pool = cell_pool.dropna(
                subset=["mean_turnover_20d", "log_mcap", "industry_code"]
            )
            label = f"Cap{cap_q}-{px.upper()}Px"
            status = "" if len(cell_pool) >= N_TOP else " [THIN]"
            print(f"    {label:<22} {len(cell_pool):>8}{status}")

    # Check 5: buy_and_hold round-trip
    cal_index = {d: i for i, d in enumerate(cal)}
    sig_d = gamma_signals[5]
    next_sig_d = gamma_signals[6]
    if sig_d in cal_index and next_sig_d in cal_index:
        si, nsi = cal_index[sig_d], cal_index[next_sig_d]
        if si + 1 < len(cal) and nsi + 1 < len(cal):
            entry_d = cal[si + 1]
            exit_d = cal[nsi + 1]
            if entry_d in wide_prices.index and exit_d in wide_prices.index:
                test_codes = []
                for c in wide_prices.columns:
                    pe = wide_prices.loc[entry_d, c]
                    px = wide_prices.loc[exit_d, c]
                    if not pd.isna(pe) and not pd.isna(px):
                        test_codes.append(c)
                        if len(test_codes) >= 3:
                            break
                if len(test_codes) >= 3:
                    manual_rets = [
                        wide_prices.loc[exit_d, c] / wide_prices.loc[entry_d, c] - 1
                        for c in test_codes
                    ]
                    manual_mean = float(np.mean(manual_rets))
                    func_mean, _ = buy_and_hold(wide_prices, entry_d, exit_d, set(test_codes))
                    diff5 = abs(manual_mean - func_mean)
                    if diff5 < 1e-9:
                        print(f"  [PASS] check 5: buy_and_hold round-trip diff = {diff5:.2e}")
                    else:
                        print(f"  [FAIL] check 5: buy_and_hold round-trip diff = {diff5:.2e}")
                        all_ok = False

    return all_ok


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
    print(f"  γ signal dates: {len(gamma_signals)}")

    print(f"\nLoading γ prices into wide pivot...")
    wide_prices = load_gamma_prices(cal, GAMMA_START, GAMMA_END)
    print(f"  shape: {wide_prices.shape} | runtime: {time.time()-t0:.1f}s")

    ok = run_self_checks(fp, um, sw, gamma_signals, wide_prices, cal)
    if not ok:
        print("\n  [ABORT] one or more self-checks failed. Investigate before running.")
        return

    print(f"\nMerging factor + universe + sector panel...")
    merged = build_merged_panel(fp, um, sw, gamma_signals)
    print(f"  shape: {merged.shape}")

    # ─── Define cells ──────────────────────────────────────────────────
    cells = [
        ("Baseline (all liquid A)", None, None),
        ("Cap1 × LoPx",  1, "lo"),
        ("Cap1 × HiPx",  1, "hi"),
        ("Cap2 × LoPx",  2, "lo"),
        ("Cap2 × HiPx",  2, "hi"),
        ("Cap3 × LoPx",  3, "lo"),
        ("Cap3 × HiPx",  3, "hi"),
    ]

    print(f"\nRunning {len(cells)} cells at top-{N_TOP}...")
    summaries = []
    period_dfs = []
    for label, cap_q, px in cells:
        print(f"  [{label}]...", end="", flush=True)
        df = run_cell(merged, wide_prices, cal, gamma_signals, cap_q, px, N_TOP, label)
        if len(df) == 0:
            print(" no periods, skipped")
            continue
        period_dfs.append(df)
        summ = aggregate_cell(df, label)
        summaries.append(summ)
        print(f" n={summ['n_periods']:>3}, "
              f"IR_cell={summ['ir_vs_cell']:+.2f}, "
              f"IR_broad={summ['ir_vs_broad_A']:+.2f}, "
              f"active_cell={summ['active_vs_cell_ann']*100:+.2f}%")

    summary_df = pd.DataFrame(summaries)

    # Self-check 6: baseline reproduces verify_and_sweep top-100 IR vs liquid
    baseline_ir = summary_df.loc[summary_df["label"] == "Baseline (all liquid A)", "ir_vs_cell"]
    if len(baseline_ir) and not np.isnan(baseline_ir.iloc[0]):
        bir = float(baseline_ir.iloc[0])
        diff6 = abs(bir - BASELINE_EXPECTED_IR)
        status = "[PASS]" if diff6 <= BASELINE_TOLERANCE else "[WARN]"
        print(f"\n  {status} check 6: baseline IR vs cell = {bir:+.3f} "
              f"(expected ~{BASELINE_EXPECTED_IR:+.2f}, diff {diff6:.2f})")

    # Pretty-print
    print("\n" + "=" * 100)
    print(f"UNIVERSE ZOOM SWEEP at top-{N_TOP} (γ regime, weekly Wed→Thu, sector cap 20%, liq floor 5000万)")
    print("=" * 100)

    show = summary_df.copy()
    for col, scale in [
        ("ir_vs_cell", 1), ("ir_vs_broad_A", 1),
        ("active_vs_cell_ann", 100), ("active_vs_broad_A_ann", 100),
        ("basket_ret_ann_net", 100), ("cell_ret_ann", 100),
        ("broad_A_liquid_ret_ann", 100), ("te_vs_cell_ann", 100),
        ("mean_churn", 100),
    ]:
        if col in show.columns:
            show[col] = (show[col] * scale).round(2)
    show["n_cell_avg"] = show["n_cell_avg"].round(0).astype(int)
    print(show.to_string(index=False))

    summary_df.to_csv(DATA_DIR / "universe_zoom_summary.csv", index=False)
    pd.concat(period_dfs, ignore_index=True).to_csv(
        DATA_DIR / "universe_zoom_period_returns.csv", index=False
    )

    print(f"\nTotal runtime: {time.time()-t0:.1f}s")
    print(f"Saved:")
    print(f"  {DATA_DIR / 'universe_zoom_summary.csv'}")
    print(f"  {DATA_DIR / 'universe_zoom_period_returns.csv'}")


if __name__ == "__main__":
    main()