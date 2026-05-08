"""
dry_pass.py — Single-rebalance end-to-end verification before the full run.

Sequence:
  1. Sub-new filter spot-check on a γ-regime date (with sample stocks).
  2. hk_hold absence-of-data handling check (eligible vs ineligible names).
  3. moneyflow per-day usage confirmation.
  4. Single rebalance: baseline → cap → tradability → RDI → BS → RHI for
     both variants A and B, plus the 3-component marginal-effect run.
  5. RDI/BS correlation matrices.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

import config
from baseline_filter import (
    apply_baseline_filter,
    baseline_step_counts,
    load_daily_panel,
    load_stock_basic,
    load_historical_names,
    _trading_days_since_list,
    load_trading_calendar,
)
from panel_builders import build_cap_rank, build_tradability
from rdi_compute import (
    compute_rdi_for_date,
    compute_rdi_with_smallorder,
    load_hk_hold_for_date,
    load_holdernumber,
    load_fund_aggregate,
    load_moneyflow_window,
)
from bs_compute import prepare_returns_panel, precompute_bs_panels, compute_bs_for_date
from rhi_algorithm import identify_hotspot_universe


GAMMA_DATE = pd.Timestamp("2024-09-25")  # Wednesday, post-PBoC stimulus
PRE2024_DATE = pd.Timestamp("2020-06-10")
PANEL_START_BUFFER = pd.Timestamp("2018-10-01")


def section(name: str) -> None:
    print("\n" + "=" * 70)
    print(name)
    print("=" * 70)


# ═══════════════════════════════════════════════════════════════════════
# 1. Sub-new filter spot check
# ═══════════════════════════════════════════════════════════════════════

def check_subnew(d: pd.Timestamp) -> None:
    section(f"1. Sub-new filter spot-check on {d.date()}")

    counts = baseline_step_counts(d, "A")
    print("Step counts (variant A):")
    for k, v in counts.items():
        print(f"  {k:>20}: {v:>5}")
    drop = counts.get("after_no_STAR", 0) - counts.get("after_no_subnew", 0)
    pct = drop / counts.get("after_no_STAR", 1) * 100
    print(f"  sub-new dropped: {drop} ({pct:.1f}%)  "
          f"[expected for γ regime: ~50-150 names per spec; <10% drop]")

    cal = load_trading_calendar()
    cal_idx = {c: i for i, c in enumerate(cal)}
    basic = load_stock_basic()

    # Show a few specific examples covering edge cases.
    sample_codes = []
    # Old listing (1991): 000001.SZ
    if "000001.SZ" in basic["ts_code"].values:
        sample_codes.append("000001.SZ")
    # Newest IPOs in the daily panel near the rebalance date
    daily = load_daily_panel(d)
    if daily is not None and not daily.empty:
        merged = daily.merge(basic, on="ts_code", how="left")
        merged["list_date"] = merged["list_date"].astype(str)
        recent = merged.dropna(subset=["list_date"]).sort_values(
            "list_date", ascending=False
        ).head(3)
        sample_codes += recent["ts_code"].tolist()

    print(f"\nPer-stock days_since_list at {d.date()}:")
    for tc in sample_codes:
        ld = basic.loc[basic["ts_code"] == tc, "list_date"].iloc[0]
        days = _trading_days_since_list(tc, str(ld), d, cal, cal_idx)
        passes = "PASS" if days >= config.SUBNEW_TRADING_DAYS else "fail"
        print(f"  {tc:>12}  list_date={ld}  days_since={days:>5}  "
              f"sub-new threshold={config.SUBNEW_TRADING_DAYS} → {passes}")


# ═══════════════════════════════════════════════════════════════════════
# 2. hk_hold absence-of-data handling
# ═══════════════════════════════════════════════════════════════════════

def check_hk_hold(d: pd.Timestamp) -> None:
    section(f"2. hk_hold absence-of-data on {d.date()}")

    hk = load_hk_hold_for_date(d)
    print(f"hk_hold rows on {d.date()}: {len(hk)} "
          f"(unique stocks: {hk['ts_code'].nunique()})")
    if not hk.empty:
        print(f"ratio range: [{hk['ratio'].min():.2f}, {hk['ratio'].max():.2f}]  "
              f"mean: {hk['ratio'].mean():.2f}")

    # Pick three stocks: one we expect HIGH foreign holding (贵州茅台
    # 600519.SH), one MEDIUM (000001.SZ 平安银行), one likely INELIGIBLE
    # (a small ChiNext name — pick a 30xxxx code).
    daily = load_daily_panel(d)
    chinext_codes = []
    if daily is not None:
        chinext_mask = daily["ts_code"].str.match(config.CHINEXT_PATTERN)
        chinext_codes = daily[chinext_mask]["ts_code"].sample(2, random_state=42).tolist()

    test_codes = ["600519.SH", "000001.SZ"] + chinext_codes
    print(f"\nPer-stock probe:")
    for tc in test_codes:
        in_panel = tc in hk["ts_code"].values
        if in_panel:
            row = hk[hk["ts_code"] == tc].iloc[0]
            status = f"HAS DATA   ratio={row['ratio']:.2f}%"
        else:
            status = "NO DATA    (treated as ineligible / no signal)"
        print(f"  {tc:>12}: {status}")

    # Coverage stats
    if daily is not None:
        baseline = apply_baseline_filter(d, daily=daily, variant="A")
        baseline_codes = set(baseline["ts_code"])
        hk_codes = set(hk["ts_code"])
        n_with = len(baseline_codes & hk_codes)
        n_total = len(baseline_codes)
        print(f"\nCoverage in post-baseline universe ({n_total} stocks):")
        print(f"  with hk_hold data: {n_with} ({100*n_with/n_total:.1f}%)")
        print(f"  without:           {n_total - n_with} "
              f"({100*(n_total-n_with)/n_total:.1f}%)")
        print(f"  Absence is treated as 'component missing', so RDI_north")
        print(f"  is dropped from that stock's composite (does not zero-fill).")


# ═══════════════════════════════════════════════════════════════════════
# 3. moneyflow per-day window
# ═══════════════════════════════════════════════════════════════════════

def check_moneyflow(d: pd.Timestamp) -> None:
    section(f"3. moneyflow per-day fetch + 20-day rolling window on {d.date()}")

    cal = load_trading_calendar()
    rebal_str = d.strftime("%Y-%m-%d")
    end_idx = cal.index(rebal_str)
    window = cal[max(0, end_idx - config.RDI_SMALLORDER_WINDOW):end_idx]
    print(f"Trailing window: {len(window)} trading days "
          f"[{window[0]} .. {window[-1]}]")

    # Confirm cache exists for those days
    n_cached = sum(
        1 for d_ in window
        if (config.MONEYFLOW_DIR / f"moneyflow_{d_.replace('-','')}.parquet").exists()
    )
    print(f"  cached: {n_cached}/{len(window)} days  "
          f"(per-day cross-section files; one call per trading day)")

    # Sanity: load one to show schema and small-share computation
    sample_path = config.MONEYFLOW_DIR / f"moneyflow_{window[-1].replace('-','')}.parquet"
    sample = pd.read_parquet(sample_path)
    print(f"\n  one-day cross-section ({sample_path.name}):")
    print(f"    rows: {len(sample):,}  columns: {len(sample.columns)}")
    print(f"    fields: {[c for c in sample.columns if c.endswith('amount')]}")

    # Compute small-share for one row
    if "buy_sm_amount" in sample.columns:
        s = sample.iloc[0]
        sm = s["buy_sm_amount"] + s["sell_sm_amount"]
        all_amt = sum(s.get(f"{x}_{y}_amount", 0)
                       for x in ("buy", "sell")
                       for y in ("sm", "md", "lg", "elg"))
        print(f"    sample stock {s['ts_code']}:")
        print(f"      sm_total = {sm:.2f}  all_total = {all_amt:.2f}  "
              f"small_share = {sm/all_amt:.3f}")


# ═══════════════════════════════════════════════════════════════════════
# 4. Single-rebalance end-to-end
# ═══════════════════════════════════════════════════════════════════════

def end_to_end(d: pd.Timestamp) -> None:
    section(f"4. Single-rebalance end-to-end on {d.date()}")

    # Pre-load BS panels for a small window covering the rebalance date.
    print("Preparing returns panel for BS rolling stats...")
    bs_start = d - pd.Timedelta(days=180)  # 60 trading days × ~3 calendar/day
    bs_end = d + pd.Timedelta(days=5)
    prepare_returns_panel(bs_start, bs_end, verbose=False)
    precompute_bs_panels(verbose=False)

    daily = load_daily_panel(d)

    for variant in ("A", "B"):
        print(f"\n--- Variant {variant} ---")
        baseline = apply_baseline_filter(d, daily=daily, variant=variant)
        print(f"  baseline: {len(baseline)} stocks")

        cap = build_cap_rank(d, baseline)
        trade = build_tradability(d, baseline)
        rdi = compute_rdi_for_date(d, baseline)
        bs = compute_bs_for_date(d, baseline)

        n_rdi = rdi["rdi_rank"].notna().sum()
        n_bs = bs["bs_score"].notna().sum()
        n_trade = trade["tradable"].sum()
        print(f"  cap_rank computed: {len(cap)}")
        print(f"  tradable:          {n_trade} ({100*n_trade/len(trade):.1f}%)")
        print(f"  rdi_rank non-NaN:  {n_rdi} ({100*n_rdi/len(baseline):.1f}%)")
        print(f"  bs_score non-NaN:  {n_bs} ({100*n_bs/len(baseline):.1f}%)")
        print(f"  RDI components per stock (mean):")
        print(f"    holders:    {rdi['rdi_holders'].notna().mean()*100:.1f}%")
        print(f"    funds:      {rdi['rdi_funds'].notna().mean()*100:.1f}%")
        print(f"    north:      {rdi['rdi_north'].notna().mean()*100:.1f}%")
        print(f"    smallorder: {rdi['rdi_smallorder'].notna().mean()*100:.1f}%")

        # Assemble RHI input
        df_in = baseline[["ts_code", "board"]].merge(
            cap[["ts_code", "cap_rank"]], on="ts_code", how="left"
        ).merge(
            trade[["ts_code", "tradable"]], on="ts_code", how="left"
        ).merge(
            rdi[["ts_code", "rdi_rank"]], on="ts_code", how="left"
        ).merge(
            bs[["ts_code", "bs_score"]], on="ts_code", how="left"
        )
        df_in["tradable"] = df_in["tradable"].fillna(False).astype(bool)
        n_smooth = (df_in["tradable"]
                     & df_in["rdi_rank"].notna()
                     & df_in["bs_score"].notna()).sum()
        print(f"  RHI smoothing set: {n_smooth} stocks")

        # 4-component RHI
        try:
            res = identify_hotspot_universe(df_in, bandwidth=0.15, target_size=500)
            print(f"  RHI 4-comp: n_in={res.n_in_hotspot}  "
                  f"centroid=({res.centroid[0]:.3f}, {res.centroid[1]:.3f})  "
                  f"n_components={res.n_components}  τ={res.tau:.4f}")
            uni = res.df_with_hotspot[res.df_with_hotspot["in_hotspot"]]
            print(f"    mean_BS in universe: {uni['bs_score'].mean():.3f}  "
                  f"vs out: {res.df_with_hotspot[~res.df_with_hotspot['in_hotspot']]['bs_score'].mean():.3f}")
            board_counts = uni["board"].value_counts().to_dict()
            print(f"    board mix: {board_counts}")
        except Exception as exc:
            print(f"  RHI 4-comp FAIL: {exc!r}")

        # With smallorder (variant A only — marginal-effect diagnostic).
        # Default `res` uses 3-comp RDI; here we compare to a run that
        # additionally folds in RDI_smallorder.
        if variant == "A":
            df_in_so = df_in.copy()
            rdi_so = compute_rdi_with_smallorder(rdi)
            df_in_so["rdi_rank"] = (
                rdi_so.set_index("ts_code")["rdi_rank_alt"]
                .reindex(df_in_so["ts_code"]).values
            )
            try:
                res_so = identify_hotspot_universe(df_in_so, bandwidth=0.15, target_size=500)
                print(f"  RHI 4-comp (with smallorder): "
                      f"n_in={res_so.n_in_hotspot}  "
                      f"centroid=({res_so.centroid[0]:.3f}, {res_so.centroid[1]:.3f})  "
                      f"τ={res_so.tau:.4f}")
                set_def = set(res.df_with_hotspot.loc[res.df_with_hotspot["in_hotspot"], "ts_code"])
                set_so = set(res_so.df_with_hotspot.loc[res_so.df_with_hotspot["in_hotspot"], "ts_code"])
                jacc = len(set_def & set_so) / max(1, len(set_def | set_so))
                d_cap = res_so.centroid[0] - res.centroid[0]
                d_rdi = res_so.centroid[1] - res.centroid[1]
                print(f"  marginal effect of adding smallorder on this date:")
                print(f"    Δcentroid = ({d_cap:+.3f}, {d_rdi:+.3f})")
                print(f"    Δsize = {res_so.n_in_hotspot - res.n_in_hotspot:+d}")
                print(f"    Jaccard(default, with-smallorder) = {jacc:.3f}")
            except Exception as exc:
                print(f"  RHI with-smallorder FAIL: {exc!r}")


# ═══════════════════════════════════════════════════════════════════════
# 5. Component correlations
# ═══════════════════════════════════════════════════════════════════════

def correlations(d: pd.Timestamp) -> None:
    section(f"5. RDI / BS component correlations on {d.date()}")

    daily = load_daily_panel(d)
    baseline = apply_baseline_filter(d, daily=daily, variant="A")
    rdi = compute_rdi_for_date(d, baseline)

    bs_start = d - pd.Timedelta(days=180)
    bs_end = d + pd.Timedelta(days=5)
    prepare_returns_panel(bs_start, bs_end, verbose=False)
    precompute_bs_panels(verbose=False)
    bs = compute_bs_for_date(d, baseline)

    print("RDI component pairwise correlation (Pearson) — single date:")
    rc = rdi[["rdi_holders", "rdi_funds", "rdi_north", "rdi_smallorder"]].corr()
    print(rc.round(3))

    print("\nBS component pairwise correlation (Pearson) — single date:")
    bc = bs[["bs_idiovol", "bs_max", "bs_skew", "bs_lowprice"]].corr()
    print(bc.round(3))


def main():
    print(f"=== UNIVERSE_EXPLORATION DRY-PASS ===")
    print(f"γ-regime sample date: {GAMMA_DATE.date()}\n")

    check_subnew(GAMMA_DATE)
    check_hk_hold(GAMMA_DATE)
    check_moneyflow(GAMMA_DATE)
    end_to_end(GAMMA_DATE)
    correlations(GAMMA_DATE)

    print("\n" + "=" * 70)
    print("DRY-PASS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
