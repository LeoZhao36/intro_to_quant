"""
self_checks.py — Eight pre-flight checks before the production sweep.

Each check returns a dict {check_id, status, details, value}. Status is one
of "PASS", "WARN", "FAIL". Aggregated into volume_reversal_self_checks.csv.

Run as: `python self_checks.py` to perform all checks and write the CSV.
The orchestrator (run_full_sweep.py) calls run_all() and aborts on any FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

import fr_config
from data_loaders import (
    load_universe_dict,
    load_daily_panel_long,
    attach_sector,
    universe_full_panel,
)
from factor_utils import cross_sectional_zscore, residualise_factor_per_date
from factor_volume_reversal import build_factor_panel


def _result(check_id, status, details, value=None):
    return {"check_id": check_id, "status": status,
            "details": details, "value": value}


# ─── 1. Synthetic recovery ─────────────────────────────────────────────

def check_synthetic_recovery(seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    n_dates, n_stocks = 100, 200
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="W-WED")
    tickers = [f"SYN{i:04d}.SZ" for i in range(n_stocks)]

    rows = []
    for d in dates:
        # Inject true factor with cross-sectional IC ≈ +0.10
        true = rng.normal(size=n_stocks)
        noise = rng.normal(size=n_stocks)
        score = true + 0.0   # the "factor"
        fwd = 0.10 * true + np.sqrt(1 - 0.10**2) * noise
        for i, tk in enumerate(tickers):
            rows.append({
                "rebalance_date": d, "ts_code": tk,
                "score": float(score[i]),
                "forward": float(fwd[i]),
                "log_mcap": float(rng.normal()),
                "industry_name": f"sec{i % 10}",
                "in_universe": True,
            })
    panel = pd.DataFrame(rows)

    # Run pipeline: residualise → z-score → IC
    panel = residualise_factor_per_date(
        panel, "score", "resid",
        numeric_controls=["log_mcap"],
        categorical_control="industry_name",
        min_obs=50,
    )
    panel = cross_sectional_zscore(panel, "resid", "z",
                                    date_col="rebalance_date",
                                    winsorize=True, low=0.01, high=0.99)
    ic_per_date = (
        panel.dropna(subset=["z", "forward"])
        .groupby("rebalance_date")
        .apply(lambda g: g["z"].corr(g["forward"], method="spearman"),
               include_groups=False)
    )
    ic_mean = float(ic_per_date.mean())
    ok = ic_mean >= fr_config.SELFCHECK_SYNTHETIC_MIN_IC
    return _result(
        "1_synthetic_recovery",
        "PASS" if ok else "FAIL",
        f"recovered IC mean={ic_mean:+.4f} over {len(ic_per_date)} dates "
        f"(threshold ≥ {fr_config.SELFCHECK_SYNTHETIC_MIN_IC})",
        ic_mean,
    )


# ─── 2. FWL precision (residualise vs statsmodels OLS) ────────────────

def check_fwl_precision(panel_with_score: pd.DataFrame,
                         sample_date: pd.Timestamp) -> dict:
    """
    Compare residuals from residualise_factor_per_date against direct OLS
    via numpy.linalg.lstsq with manually-built design matrix. With float64,
    these should be identical to numerical precision.
    """
    df = panel_with_score[
        panel_with_score["rebalance_date"] == sample_date
    ].copy()
    df = df.dropna(subset=["score_ts_5", "log_mcap", "industry_name"])
    if len(df) < 50:
        return _result("2_fwl_precision", "FAIL",
                       f"too few rows on {sample_date.date()}", None)

    y = df["score_ts_5"].values.astype(np.float64)
    log_mcap = df["log_mcap"].values.astype(np.float64).reshape(-1, 1)
    dummies = pd.get_dummies(df["industry_name"], drop_first=True
                             ).values.astype(np.float64)
    X = np.hstack([np.ones((len(df), 1)), log_mcap, dummies])

    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    direct_resid = y - X @ beta

    # Now from residualise_factor_per_date
    rebuilt = residualise_factor_per_date(
        df.copy(), "score_ts_5", "resid_check",
        numeric_controls=["log_mcap"],
        categorical_control="industry_name",
        min_obs=50,
    )
    helper_resid = rebuilt["resid_check"].values.astype(np.float64)

    max_abs_diff = float(np.max(np.abs(direct_resid - helper_resid)))
    ok = max_abs_diff <= fr_config.SELFCHECK_FWL_TOL
    return _result(
        "2_fwl_precision",
        "PASS" if ok else "FAIL",
        f"max|residual diff| = {max_abs_diff:.3e} on {sample_date.date()} "
        f"(threshold ≤ {fr_config.SELFCHECK_FWL_TOL:.0e}, n={len(df)})",
        max_abs_diff,
    )


# ─── 3. Universe loader sanity ─────────────────────────────────────────

def check_universe_loader_sanity() -> dict:
    full = universe_full_panel()
    in_uni = full[full["in_hotspot"]]
    n_dates_total = full["trade_date"].nunique()

    gamma = in_uni[in_uni["trade_date"] >= fr_config.GAMMA_START_DATE]
    sizes = gamma.groupby("trade_date")["ts_code"].size()
    boards = set(in_uni["board"].unique())

    cond_dates = n_dates_total >= 380
    cond_size = abs(sizes.mean() - 495) <= 30 and sizes.std() < 30
    cond_board = boards.issubset({"Main_SZ", "Main_SH"})

    msg = (f"total dates={n_dates_total}, γ dates={len(sizes)}, "
           f"γ size mean={sizes.mean():.0f}±{sizes.std():.0f}, "
           f"boards={sorted(boards)}")
    ok = cond_dates and cond_size and cond_board
    return _result(
        "3_universe_loader_sanity",
        "PASS" if ok else "FAIL",
        msg,
        float(sizes.mean()),
    )


# ─── 4. Look-ahead alignment ───────────────────────────────────────────

def check_lookahead_alignment(daily_long: pd.DataFrame,
                               sample_date: pd.Timestamp,
                               sample_ticker: str,
                               L: int = 5,
                               baseline: int = 60) -> dict:
    """
    Verify the L-window ends at t and the baseline ends strictly before.
    """
    sub = daily_long[daily_long["ts_code"] == sample_ticker].sort_values(
        "trade_date"
    )
    sub = sub.reset_index(drop=True)
    if sample_date not in sub["trade_date"].values:
        return _result("4_lookahead_alignment", "FAIL",
                        f"sample ticker {sample_ticker} has no data on "
                        f"{sample_date.date()}", None)
    t_idx = sub.index[sub["trade_date"] == sample_date][0]

    L_window = list(range(t_idx - L + 1, t_idx + 1))      # [t-L+1, t]
    baseline_window = list(range(t_idx - baseline - L + 1, t_idx - L + 1))

    L_dates = sub.loc[L_window, "trade_date"].tolist()
    base_dates = sub.loc[baseline_window, "trade_date"].tolist()

    no_overlap = max(base_dates) < min(L_dates)
    L_ends_at_t = max(L_dates) == sample_date
    base_ends_before = max(base_dates) < sample_date

    msg = (f"ticker={sample_ticker} t={sample_date.date()} "
           f"L_window=[{L_dates[0].date()}..{L_dates[-1].date()}] "
           f"baseline=[{base_dates[0].date()}..{base_dates[-1].date()}] "
           f"no_overlap={no_overlap}, L_ends_at_t={L_ends_at_t}, "
           f"base_ends_before={base_ends_before}")
    ok = no_overlap and L_ends_at_t and base_ends_before
    return _result(
        "4_lookahead_alignment",
        "PASS" if ok else "FAIL",
        msg, None,
    )


# ─── 5. Volume rank distribution ───────────────────────────────────────

def check_vol_rank_distribution(panel: pd.DataFrame, L: int = 5) -> dict:
    """
    ts rank: roughly uniform on [0,1] with mild winsor clustering at endpoints.
    cs rank: exactly uniform per date by construction.
    """
    ts = panel[f"vol_rank_ts_{L}"].dropna().values
    cs = panel[f"vol_rank_cs_{L}"].dropna().values
    if len(ts) < 100 or len(cs) < 100:
        return _result("5_vol_rank_distribution", "FAIL",
                        f"too few obs (ts={len(ts)}, cs={len(cs)})", None)

    bins = 20
    ts_hist, _ = np.histogram(ts, bins=bins, range=(0, 1))
    expected = len(ts) / bins
    max_dev_ts = ts_hist.max() / expected

    # Per-date KS for cs
    ks_pvals = []
    for d, g in panel.groupby("rebalance_date"):
        v = g[f"vol_rank_cs_{L}"].dropna().values
        if len(v) < 30:
            continue
        # Uniform[0,1] KS test
        ks = sps.kstest(v, "uniform")
        ks_pvals.append(ks.pvalue)
    median_p = float(np.median(ks_pvals)) if ks_pvals else np.nan

    cond_ts = max_dev_ts <= 4.0   # mild winsor clustering at endpoints allowed
    cond_cs = median_p > 0.1
    msg = (f"ts max_bin/expected={max_dev_ts:.2f}; "
           f"cs per-date KS median p={median_p:.3f} (n={len(ks_pvals)})")
    ok = cond_ts and cond_cs
    return _result(
        "5_vol_rank_distribution",
        "PASS" if ok else "WARN",
        msg, max_dev_ts,
    )


# ─── 6. Forward-return convention ──────────────────────────────────────

def check_forward_return_convention(panel: pd.DataFrame,
                                     daily_long: pd.DataFrame,
                                     L: int = 5) -> dict:
    """
    For one (L, rank_type) cell, IC against panel's weekly_forward_return
    AND a freshly-computed open-to-open T+1 return. Mean |gap| ≤ 0.005.
    """
    # Build open-adjusted wide
    long = daily_long.copy()
    long["adj_open"] = long["open"] * long["adj_factor"]
    open_w = long.pivot(index="trade_date", columns="ts_code",
                         values="adj_open").sort_index()

    rebs = sorted(panel["rebalance_date"].unique())
    # For each rebalance Wednesday t, fresh open-to-open weekly forward:
    #   entry = next trading day after t (typically Thursday)
    #   exit  = next trading day after t+7 (typically Thursday)
    fresh = []
    trading_dates = open_w.index
    for t in rebs:
        # next trading day after t
        after_t = trading_dates[trading_dates > t]
        if len(after_t) < 6:
            continue
        entry = after_t[0]
        # exit = the trading day at position +5 from entry (5 trading days =
        # one trading week; matches the weekly cadence)
        # but spec says next Thursday; equivalent within ε on weekly cadence.
        # Use entry's index + 5 trading days as exit:
        idx_entry = trading_dates.get_loc(entry)
        if idx_entry + 5 >= len(trading_dates):
            continue
        exit = trading_dates[idx_entry + 5]
        ret = open_w.loc[exit] / open_w.loc[entry] - 1.0
        sub = pd.DataFrame({
            "rebalance_date": t, "ts_code": ret.index,
            "fresh_fwd": ret.values,
        })
        fresh.append(sub)
    fresh = pd.concat(fresh, ignore_index=True)

    z_col = f"z_volrev_{L}_ts"
    sub = panel[["rebalance_date", "ts_code", z_col,
                  "weekly_forward_return"]].dropna()
    sub = sub.merge(fresh, on=["rebalance_date", "ts_code"], how="inner")
    sub = sub.dropna(subset=["fresh_fwd"])

    ic_panel = (
        sub.groupby("rebalance_date")
        .apply(lambda g: g[z_col].corr(g["weekly_forward_return"],
                                       method="spearman"),
                include_groups=False)
    )
    ic_fresh = (
        sub.groupby("rebalance_date")
        .apply(lambda g: g[z_col].corr(g["fresh_fwd"], method="spearman"),
                include_groups=False)
    )
    aligned = pd.concat([ic_panel.rename("p"), ic_fresh.rename("f")],
                         axis=1).dropna()
    mean_abs_gap = float((aligned["p"] - aligned["f"]).abs().mean())
    ok = mean_abs_gap <= fr_config.SELFCHECK_FORWARD_RETURN_GAP_TOL
    return _result(
        "6_forward_return_convention",
        "PASS" if ok else "WARN",
        f"mean |IC_panel - IC_fresh_oo_T+1| = {mean_abs_gap:.4f} over "
        f"{len(aligned)} dates (threshold ≤ "
        f"{fr_config.SELFCHECK_FORWARD_RETURN_GAP_TOL})",
        mean_abs_gap,
    )


# ─── 7. Coverage ───────────────────────────────────────────────────────

def check_coverage(panel: pd.DataFrame,
                    universe_dict: dict[pd.Timestamp, set[str]],
                    L: int = 5) -> dict:
    cols_required = [f"ret_L_{L}", f"vol_rank_ts_{L}", "log_mcap",
                     "industry_name", "weekly_forward_return"]
    valid = panel.dropna(subset=cols_required)
    n_valid = len(valid)
    n_total = sum(len(v) for v in universe_dict.values())
    coverage = n_valid / n_total if n_total else 0.0

    # Per-date retention
    per_date_kept = valid.groupby("rebalance_date").size()
    per_date_universe = {d: len(v) for d, v in universe_dict.items()}
    per_date_retention = per_date_kept / pd.Series(per_date_universe)
    bottom = per_date_retention.sort_values().head(5)
    bottom_str = "; ".join(f"{d.date()}={r:.2f}"
                            for d, r in bottom.items())

    ok = coverage >= fr_config.SELFCHECK_COVERAGE_MIN
    return _result(
        "7_coverage",
        "PASS" if ok else "WARN",
        f"coverage={coverage:.3f} ({n_valid:,}/{n_total:,}); "
        f"weakest 5 dates: {bottom_str}",
        coverage,
    )


# ─── 8. Period-level basket-return landmark (headline cell) ───────────

def check_period_landmark(panel: pd.DataFrame,
                           daily_long: pd.DataFrame,
                           universe_dict: dict[pd.Timestamp, set[str]],
                           L: int = None, N: int = None,
                           rank_type: str = None) -> dict:
    """
    Quick period-level annualized return for the headline cell, using the
    correct buy-and-hold mechanics. Documentation only; no pass/fail logic.
    """
    L = L or fr_config.HEADLINE_L
    N = N or fr_config.HEADLINE_N
    rank_type = rank_type or fr_config.HEADLINE_RANK
    z_col = f"z_volrev_{L}_{rank_type}"

    long = daily_long.copy()
    long["adj_open"] = long["open"] * long["adj_factor"]
    open_w = long.pivot(index="trade_date", columns="ts_code",
                         values="adj_open").sort_index()

    rebs = sorted(panel["rebalance_date"].unique())
    period_rets = []
    for i, t in enumerate(rebs):
        u = universe_dict.get(t, set())
        if not u:
            continue
        sub = panel[(panel["rebalance_date"] == t) &
                    (panel["ts_code"].isin(u))].dropna(subset=[z_col])
        if len(sub) < N:
            continue
        top_n = sub.nlargest(N, z_col)["ts_code"].tolist()
        # Entry = next trading day after t; exit = entry + 5
        idx = open_w.index.searchsorted(t, side="right")
        if idx + 5 >= len(open_w.index):
            continue
        entry = open_w.index[idx]
        exit = open_w.index[idx + 5]
        entry_p = open_w.loc[entry, top_n].dropna()
        exit_p = open_w.loc[exit, top_n].dropna()
        common = entry_p.index.intersection(exit_p.index)
        if len(common) < N // 2:
            continue
        ret = (exit_p[common] / entry_p[common] - 1.0).mean()
        period_rets.append(ret)
    period_rets = np.array(period_rets)
    if len(period_rets) < 10:
        return _result("8_period_landmark", "FAIL",
                       f"only {len(period_rets)} valid periods", None)

    ann_gross = float(period_rets.mean() * fr_config.PERIODS_PER_YEAR)
    ann_vol = float(period_rets.std() * np.sqrt(fr_config.PERIODS_PER_YEAR))
    sharpe = ann_gross / ann_vol if ann_vol > 0 else np.nan
    return _result(
        "8_period_landmark",
        "PASS",
        f"headline (L={L}, N={N}, {rank_type}) period-level: "
        f"ann_gross={ann_gross:+.3f}, ann_vol={ann_vol:.3f}, "
        f"naive_sharpe={sharpe:+.2f} over {len(period_rets)} periods",
        ann_gross,
    )


# ─── Orchestrator ──────────────────────────────────────────────────────

def run_all(panel: pd.DataFrame,
            universe_dict: dict[pd.Timestamp, set[str]],
            daily_long: pd.DataFrame) -> pd.DataFrame:
    """Run all eight checks; write CSV; return the result frame."""
    results = []

    # 1
    results.append(check_synthetic_recovery())

    # 3
    results.append(check_universe_loader_sanity())

    # 2 — pick a γ date that has full panel coverage
    rebs = sorted(panel["rebalance_date"].unique())
    sample_date = rebs[len(rebs) // 2]   # middle of γ
    results.append(check_fwl_precision(panel, sample_date))

    # 4 — pick a sample stock that has data on sample_date
    daily_on_date = daily_long[daily_long["trade_date"] == sample_date]
    if len(daily_on_date) > 0:
        sample_ticker = daily_on_date["ts_code"].iloc[0]
        results.append(check_lookahead_alignment(daily_long, sample_date,
                                                  sample_ticker))
    else:
        results.append(_result("4_lookahead_alignment", "FAIL",
                                f"no daily data on {sample_date.date()}",
                                None))

    # 5
    results.append(check_vol_rank_distribution(panel))

    # 6
    results.append(check_forward_return_convention(panel, daily_long))

    # 7
    results.append(check_coverage(panel, universe_dict))

    # 8
    results.append(check_period_landmark(panel, daily_long, universe_dict))

    df = pd.DataFrame(results)
    df = df.sort_values("check_id").reset_index(drop=True)

    fr_config.DATA_OUT.mkdir(parents=True, exist_ok=True)
    out = fr_config.DATA_OUT / "volume_reversal_self_checks.csv"
    df.to_csv(out, index=False)
    print(f"\n  → wrote {out}")
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    import sys
    print("Loading universe + daily panel + factor panel...")
    udict = load_universe_dict(gamma_only=True)
    g_dates = sorted(udict.keys())
    end = max(g_dates)
    start = min(g_dates) - pd.Timedelta(days=120)
    print(f"  daily window: {start.date()} .. {end.date()}")
    dp = load_daily_panel_long(start, end)

    fpa = pd.read_parquet(fr_config.FACTOR_PANEL_A)
    fpa["rebalance_date"] = pd.to_datetime(fpa["rebalance_date"])
    fpa = fpa[fpa["rebalance_date"].isin(g_dates)]
    fpa = attach_sector(fpa)

    panel = build_factor_panel(g_dates, udict, dp, fpa, verbose=True)
    df = run_all(panel, udict, dp)

    if (df["status"] == "FAIL").any():
        print("\nFAIL: one or more checks failed; aborting.")
        sys.exit(1)
    print("\nAll self-checks passed (or warned).")
