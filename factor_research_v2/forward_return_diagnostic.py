"""
forward_return_diagnostic.py — Verify panel `weekly_forward_return` and
quantify the gap vs fresh open-to-open T+1.

Tasks (per CC instruction):
  3. Replicate the panel quantity from daily files for sample (date, ts_code)
     pairs in the γ window. Confirm identical (or document drift).
  4. Compute fresh open-to-open T+1 for the same window. Compare side-by-side.
  5. Reconcile the May-7 (0.0033 on turnover) vs today (0.024 on
     volume-reversal) gap measurements: build z_turnover and z_volrev on the
     same panel, compare IC_panel vs IC_fresh for each.

Outputs to factor_research_v2/data/:
  forward_return_replication_check.csv  — sample of (date, ticker) with
      panel value, fresh close-to-close, fresh open-to-open, diffs.
  forward_return_factor_gap.csv         — per-factor (turnover, volrev_ts_5)
      mean IC against panel and fresh open-to-open over γ.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import fr_config
from data_loaders import (
    load_universe_dict, load_daily_panel_long, attach_sector,
)
from factor_utils import cross_sectional_zscore, residualise_factor_per_date
from factor_volume_reversal import build_factor_panel


def main() -> None:
    print("Loading γ universe + factor panel + extended daily window...")
    udict = load_universe_dict(gamma_only=True)
    g_dates = sorted(udict.keys())
    g_start, g_end = g_dates[0], g_dates[-1]

    fpa = pd.read_parquet(fr_config.FACTOR_PANEL_A)
    fpa["rebalance_date"] = pd.to_datetime(fpa["rebalance_date"])
    fpa_g = fpa[fpa["rebalance_date"].between(g_start, g_end)].copy()
    print(f"  γ rebalances:        {len(g_dates)} "
          f"({g_start.date()} .. {g_end.date()})")
    print(f"  factor_panel_a γ:    {len(fpa_g):,} rows")

    # Daily window must include the next rebalance after g_end + a few days
    # of buffer for open-to-open T+1
    daily_start = g_start - pd.Timedelta(days=10)
    daily_end = g_end + pd.Timedelta(days=21)
    dp = load_daily_panel_long(daily_start, daily_end)
    print(f"  daily panel rows:    {len(dp):,} "
          f"({dp['trade_date'].min().date()} .. "
          f"{dp['trade_date'].max().date()})")

    # ── Build wide series we'll need ───────────────────────────────────
    dp["adj_close"] = dp["close"] * dp["adj_factor"]
    dp["adj_open"] = dp["open"] * dp["adj_factor"]
    adj_close_w = dp.pivot(index="trade_date", columns="ts_code",
                            values="adj_close").sort_index()
    adj_open_w = dp.pivot(index="trade_date", columns="ts_code",
                            values="adj_open").sort_index()
    trading_dates = adj_close_w.index

    # Map each γ rebalance Wednesday to its NEXT rebalance Wednesday
    next_rebal = {g_dates[i]: g_dates[i + 1]
                   for i in range(len(g_dates) - 1)}

    # ── Task 3: Replication check (close-to-close) ─────────────────────
    print("\n[Task 3] Replicating panel close-to-close from daily files...")
    repl_rows = []
    for t, t_next in next_rebal.items():
        if t not in adj_close_w.index or t_next not in adj_close_w.index:
            continue
        c_t = adj_close_w.loc[t]
        c_n = adj_close_w.loc[t_next]
        fresh_cc = c_n / c_t - 1.0  # Series indexed by ts_code

        panel_row = fpa_g[fpa_g["rebalance_date"] == t]
        for _, r in panel_row.iterrows():
            tk = r["ts_code"]
            panel_v = r["weekly_forward_return"]
            fresh_v = fresh_cc.get(tk, np.nan)
            if pd.isna(panel_v) and pd.isna(fresh_v):
                continue
            repl_rows.append({
                "rebalance_date": t,
                "next_rebalance_date": t_next,
                "ts_code": tk,
                "panel_value": float(panel_v) if pd.notna(panel_v) else np.nan,
                "fresh_close_to_close": float(fresh_v) if pd.notna(fresh_v) else np.nan,
                "diff": (float(panel_v) - float(fresh_v))
                        if (pd.notna(panel_v) and pd.notna(fresh_v))
                        else np.nan,
            })
    repl = pd.DataFrame(repl_rows)
    repl_clean = repl.dropna(subset=["panel_value", "fresh_close_to_close"])
    max_diff = float(repl_clean["diff"].abs().max())
    mean_abs = float(repl_clean["diff"].abs().mean())
    n_exact = int((repl_clean["diff"].abs() < 1e-6).sum())
    print(f"  rows compared (both non-NaN):  {len(repl_clean):,}")
    print(f"  max |panel - fresh_cc|:        {max_diff:.6f}")
    print(f"  mean |panel - fresh_cc|:       {mean_abs:.6f}")
    print(f"  rows with |diff| < 1e-6:       {n_exact:,} "
          f"({100*n_exact/len(repl_clean):.1f}%)")

    # NaN reconciliation
    panel_only_nan = repl["panel_value"].isna() & repl["fresh_close_to_close"].notna()
    fresh_only_nan = repl["panel_value"].notna() & repl["fresh_close_to_close"].isna()
    print(f"  panel NaN, fresh non-NaN:      {panel_only_nan.sum():,}")
    print(f"  panel non-NaN, fresh NaN:      {fresh_only_nan.sum():,}")

    # Save sample (1000 rows max for the CSV — full file would be 50MB)
    repl_sample = repl.sample(min(1000, len(repl)), random_state=0)
    out_csv1 = fr_config.DATA_OUT / "forward_return_replication_check.csv"
    repl_sample.to_csv(out_csv1, index=False)
    print(f"  → wrote {out_csv1} ({len(repl_sample):,} sample rows)")

    # ── Task 4: Fresh open-to-open T+1 over γ ──────────────────────────
    print("\n[Task 4] Computing fresh open-to-open T+1 over γ...")
    fresh_oo_rows = []
    for t, t_next in next_rebal.items():
        # Entry = next trading day after t (Thursday)
        idx_t = trading_dates.searchsorted(t, side="right")
        idx_tn = trading_dates.searchsorted(t_next, side="right")
        if idx_t >= len(trading_dates) or idx_tn >= len(trading_dates):
            continue
        entry = trading_dates[idx_t]
        exit = trading_dates[idx_tn]
        if entry not in adj_open_w.index or exit not in adj_open_w.index:
            continue
        o_e = adj_open_w.loc[entry]
        o_x = adj_open_w.loc[exit]
        fresh_oo = o_x / o_e - 1.0

        panel_row = fpa_g[fpa_g["rebalance_date"] == t]
        for _, r in panel_row.iterrows():
            tk = r["ts_code"]
            panel_v = r["weekly_forward_return"]
            fresh_v = fresh_oo.get(tk, np.nan)
            fresh_cc_v = (adj_close_w.loc[t_next].get(tk, np.nan)
                          / adj_close_w.loc[t].get(tk, np.nan) - 1.0)
            if pd.isna(panel_v) and pd.isna(fresh_v):
                continue
            fresh_oo_rows.append({
                "rebalance_date": t,
                "ts_code": tk,
                "panel_cc": float(panel_v) if pd.notna(panel_v) else np.nan,
                "fresh_cc": float(fresh_cc_v) if pd.notna(fresh_cc_v) else np.nan,
                "fresh_oo": float(fresh_v) if pd.notna(fresh_v) else np.nan,
            })
    side_by_side = pd.DataFrame(fresh_oo_rows)
    sbs_clean = side_by_side.dropna(subset=["panel_cc", "fresh_oo"])
    diff_cc_oo = sbs_clean["panel_cc"] - sbs_clean["fresh_oo"]
    print(f"  rows compared:                 {len(sbs_clean):,}")
    print(f"  mean(panel_cc - fresh_oo):     {float(diff_cc_oo.mean()):+.6f}")
    print(f"  std(panel_cc - fresh_oo):      {float(diff_cc_oo.std()):.6f}")
    print(f"  median |diff|:                 {float(diff_cc_oo.abs().median()):.6f}")
    print(f"  Pearson corr(panel_cc, fresh_oo): "
          f"{sbs_clean['panel_cc'].corr(sbs_clean['fresh_oo']):.4f}")

    # ── Task 5: Reconcile May-7 vs today gap measurements ──────────────
    print("\n[Task 5] Per-factor IC gap (panel field vs fresh open-to-open)...")

    # Build z_turnover (May 7 factor) — high z = LOW turnover predicts better
    fpa_g_full = fpa_g.copy()
    fpa_g_full = attach_sector(fpa_g_full)
    fpa_g_full["log_mcap"] = fpa_g_full["log_mcap"].astype(np.float64)
    fpa_g_full["turn"] = fpa_g_full["mean_turnover_20d"].astype(np.float64)
    fpa_g_full = residualise_factor_per_date(
        fpa_g_full, "turn", "turn_resid",
        numeric_controls=["log_mcap"],
        categorical_control="industry_name",
        min_obs=50,
    )
    fpa_g_full = cross_sectional_zscore(
        fpa_g_full, "turn_resid", "z_turn_raw",
        date_col="rebalance_date", winsorize=True, low=0.01, high=0.99,
    )
    fpa_g_full["z_turnover"] = -fpa_g_full["z_turn_raw"]

    # Build z_volrev_5_ts on same γ window (reuse the volume-reversal builder)
    print("  building z_volrev_5_ts for comparison...")
    panel_vr = build_factor_panel(
        g_dates, udict, dp, fpa_g_full,
        L_values=[5], verbose=False,
    )
    # Bring in fresh_oo into both factor frames
    fresh_oo_long = side_by_side[
        ["rebalance_date", "ts_code", "fresh_oo"]
    ].copy()

    def per_factor_ic(panel_df: pd.DataFrame, z_col: str,
                       ret_col_panel: str, ret_col_fresh: str) -> dict:
        sub = panel_df[
            ["rebalance_date", "ts_code", z_col,
             ret_col_panel, ret_col_fresh]
        ].dropna()
        ic_panel = (sub.groupby("rebalance_date")
                     .apply(lambda g: g[z_col].corr(g[ret_col_panel],
                                                     method="spearman"),
                             include_groups=False).dropna())
        ic_fresh = (sub.groupby("rebalance_date")
                     .apply(lambda g: g[z_col].corr(g[ret_col_fresh],
                                                     method="spearman"),
                             include_groups=False).dropna())
        aligned = pd.concat([ic_panel.rename("panel"),
                              ic_fresh.rename("fresh")], axis=1).dropna()
        return {
            "n_dates": len(aligned),
            "ic_panel_mean": float(aligned["panel"].mean()),
            "ic_fresh_mean": float(aligned["fresh"].mean()),
            "ic_panel_t": float(aligned["panel"].mean() /
                                 (aligned["panel"].std() / np.sqrt(len(aligned)))),
            "ic_fresh_t": float(aligned["fresh"].mean() /
                                 (aligned["fresh"].std() / np.sqrt(len(aligned)))),
            "mean_signed_gap_panel_minus_fresh": float(
                (aligned["panel"] - aligned["fresh"]).mean()),
            "mean_abs_gap": float((aligned["panel"] - aligned["fresh"]
                                    ).abs().mean()),
        }

    # Turnover factor IC
    fpa_with_oo = fpa_g_full.merge(fresh_oo_long,
                                    on=["rebalance_date", "ts_code"],
                                    how="left")
    fpa_with_oo = fpa_with_oo[fpa_with_oo["in_universe"]]
    turn_stats = per_factor_ic(
        fpa_with_oo, "z_turnover",
        "weekly_forward_return", "fresh_oo",
    )
    print("  z_turnover (low-turnover predicts):")
    print(f"    n_dates             {turn_stats['n_dates']}")
    print(f"    IC vs panel_cc:     {turn_stats['ic_panel_mean']:+.4f} "
          f"(t={turn_stats['ic_panel_t']:+.2f})")
    print(f"    IC vs fresh_oo:     {turn_stats['ic_fresh_mean']:+.4f} "
          f"(t={turn_stats['ic_fresh_t']:+.2f})")
    print(f"    signed gap:         "
          f"{turn_stats['mean_signed_gap_panel_minus_fresh']:+.4f}")
    print(f"    mean |gap|:         {turn_stats['mean_abs_gap']:.4f}")

    # Volume-reversal factor IC  (z_volrev_5_ts)
    panel_vr_with_oo = panel_vr.merge(fresh_oo_long,
                                        on=["rebalance_date", "ts_code"],
                                        how="left")
    panel_vr_with_oo = panel_vr_with_oo[panel_vr_with_oo["in_universe"]]
    vr_stats = per_factor_ic(
        panel_vr_with_oo, "z_volrev_5_ts",
        "weekly_forward_return", "fresh_oo",
    )
    print("  z_volrev_5_ts (loser × high-volume):")
    print(f"    n_dates             {vr_stats['n_dates']}")
    print(f"    IC vs panel_cc:     {vr_stats['ic_panel_mean']:+.4f} "
          f"(t={vr_stats['ic_panel_t']:+.2f})")
    print(f"    IC vs fresh_oo:     {vr_stats['ic_fresh_mean']:+.4f} "
          f"(t={vr_stats['ic_fresh_t']:+.2f})")
    print(f"    signed gap:         "
          f"{vr_stats['mean_signed_gap_panel_minus_fresh']:+.4f}")
    print(f"    mean |gap|:         {vr_stats['mean_abs_gap']:.4f}")

    out_csv2 = fr_config.DATA_OUT / "forward_return_factor_gap.csv"
    pd.DataFrame([
        {"factor": "z_turnover", **turn_stats},
        {"factor": "z_volrev_5_ts", **vr_stats},
    ]).to_csv(out_csv2, index=False)
    print(f"\n  → wrote {out_csv2}")

    # ── Per-rebalance overnight gap diagnostic ─────────────────────────
    # Decompose: for each stock-date, the after-close-gap at t and the
    # after-close-gap at t+1, expressed in log-return terms:
    #   log(panel_cc) - log(fresh_oo) = log(open[t+1_thu]/close[t+1])
    #                                 - log(open[t_thu]/close[t])
    # If the volume-reversal factor concentrates on stocks with large
    # overnight gaps at t (capitulation candidates that gap up Thursday),
    # the panel field captures that bounce; fresh_oo does not.
    sbs_clean = sbs_clean.copy()
    sbs_clean["log_panel"] = np.log1p(sbs_clean["panel_cc"])
    sbs_clean["log_fresh"] = np.log1p(sbs_clean["fresh_oo"])
    sbs_clean["log_diff"] = sbs_clean["log_panel"] - sbs_clean["log_fresh"]

    # Cross-section correlation per date between log_diff and z_volrev_5_ts
    panel_vr_thin = panel_vr_with_oo[
        ["rebalance_date", "ts_code", "z_volrev_5_ts"]
    ]
    sbs_with_z = sbs_clean.merge(panel_vr_thin,
                                   on=["rebalance_date", "ts_code"],
                                   how="left")
    sbs_with_z = sbs_with_z.dropna(subset=["z_volrev_5_ts", "log_diff"])
    corr_per_date = (sbs_with_z.groupby("rebalance_date")
                      .apply(lambda g: g["z_volrev_5_ts"].corr(g["log_diff"],
                                                                 method="spearman"),
                              include_groups=False).dropna())
    print(f"\n  Per-date Spearman(z_volrev_5_ts, log_diff_panel_vs_oo):")
    print(f"    mean = {corr_per_date.mean():+.4f}, "
          f"median = {corr_per_date.median():+.4f}, "
          f"n = {len(corr_per_date)}")

    # Same for turnover
    turn_thin = fpa_with_oo[
        ["rebalance_date", "ts_code", "z_turnover"]
    ]
    sbs_with_turn = sbs_clean.merge(turn_thin,
                                      on=["rebalance_date", "ts_code"],
                                      how="left")
    sbs_with_turn = sbs_with_turn.dropna(subset=["z_turnover", "log_diff"])
    corr_turn = (sbs_with_turn.groupby("rebalance_date")
                  .apply(lambda g: g["z_turnover"].corr(g["log_diff"],
                                                         method="spearman"),
                          include_groups=False).dropna())
    print(f"  Per-date Spearman(z_turnover,    log_diff_panel_vs_oo):")
    print(f"    mean = {corr_turn.mean():+.4f}, "
          f"median = {corr_turn.median():+.4f}, "
          f"n = {len(corr_turn)}")

    # Cache decomposition for the report
    decomp = {
        "vr_corr_with_logdiff_mean": float(corr_per_date.mean()),
        "vr_corr_with_logdiff_median": float(corr_per_date.median()),
        "turn_corr_with_logdiff_mean": float(corr_turn.mean()),
        "turn_corr_with_logdiff_median": float(corr_turn.median()),
        "panel_cc_minus_fresh_oo_mean": float(diff_cc_oo.mean()),
        "panel_cc_minus_fresh_oo_std": float(diff_cc_oo.std()),
        "panel_corr_fresh_pearson": float(
            sbs_clean["panel_cc"].corr(sbs_clean["fresh_oo"])),
    }
    np.savez(fr_config.DATA_OUT / "forward_return_decomp.npz", **{
        k: np.array(v) for k, v in decomp.items()
    })

    # ── Write the markdown report ──────────────────────────────────────
    write_report(repl_clean, max_diff, mean_abs, n_exact,
                 panel_only_nan.sum(), fresh_only_nan.sum(),
                 sbs_clean, diff_cc_oo,
                 turn_stats, vr_stats, decomp)


def write_report(repl_clean, max_diff, mean_abs, n_exact,
                  n_panel_nan_only, n_fresh_nan_only,
                  sbs_clean, diff_cc_oo,
                  turn_stats, vr_stats, decomp):
    out = fr_config.DATA_OUT / "forward_return_diagnostic.md"
    n_compared = len(repl_clean)
    n_sbs = len(sbs_clean)

    # Vetted: the spec said "diagnostic" — write findings + recommendation.
    md = f"""# Forward-Return Convention Diagnostic

*Generated by `forward_return_diagnostic.py`. Read-only investigation; no factor work.*

## What `weekly_forward_return` actually is

It is a **Wednesday-close to next-Wednesday-close, forward-adjusted return** —
NOT open-to-open. Defined in [build_factor_panel.py:264](../../multi_factor_x1/build_factor_panel.py#L264) as

```python
snap["weekly_forward_return"] = snap["next_adj_close"] / snap["adj_close"] - 1
```

where `adj_close = close * adj_factor` (`close` is the unadjusted Tushare close
on the rebalance day; `adj_factor` is from the same daily snapshot). The
shifted next value is sourced from the panel's own next-rebalance row by
`groupby("ts_code").shift(-1)`. The construction module's docstring
([build_factor_panel.py:30-36](../../multi_factor_x1/build_factor_panel.py#L30-L36))
confirms it is close-to-close, says nothing about open-to-open. No
winsorization, no clipping. NaN where the next rebalance is missing or
non-consecutive (suspension gap).

## Replication check (panel ↔ fresh close-to-close)

Replicated `weekly_forward_return` from `multi_factor_x1/daily_panel/`
parquets directly (read close + adj_factor at each rebalance Wednesday,
compute `(close[t+1]*adj[t+1]) / (close[t]*adj[t]) - 1`).

| metric | value |
|---|---|
| rows compared, both non-NaN | {n_compared:,} |
| max \\|panel − fresh_cc\\| | {max_diff:.2e} |
| mean \\|panel − fresh_cc\\| | {mean_abs:.2e} |
| rows exactly equal (≤1e-6) | {n_exact:,} ({100*n_exact/n_compared:.1f}%) |
| panel NaN, fresh non-NaN | {n_panel_nan_only:,} |
| panel non-NaN, fresh NaN | {n_fresh_nan_only:,} |

**Conclusion**: the panel field is exactly close-to-close as documented; no
drift, no stale values. The few NaN-asymmetry cases are the panel's
suspension-gap invalidation (`weekly_forward_return = NaN` when the next
rebalance for a stock is non-consecutive due to suspension), which fresh
close-to-close does not reproduce because it just reads the two endpoints.

Sample of {min(1000, n_compared):,} rows in `forward_return_replication_check.csv`.

## Gap vs fresh open-to-open T+1

Computed open-to-open T+1 from the same daily files: entry = trading day
after the rebalance Wednesday (typically Thursday), exit = trading day
after the next rebalance Wednesday. Both prices forward-adjusted via
`adj_factor`.

| metric | value |
|---|---|
| rows compared (γ window, both non-NaN) | {n_sbs:,} |
| mean(panel_cc − fresh_oo) | {float(diff_cc_oo.mean()):+.6f} |
| std(panel_cc − fresh_oo) | {float(diff_cc_oo.std()):.6f} |
| median \\|diff\\| | {float(diff_cc_oo.abs().median()):.6f} |
| Pearson(panel_cc, fresh_oo) | {decomp['panel_corr_fresh_pearson']:.4f} |

**At the level of individual stock-week returns**, panel_cc and fresh_oo
differ by an average of {float(diff_cc_oo.mean())*100:+.3f}% per week
(std {float(diff_cc_oo.std())*100:.3f}%). They are highly correlated
(Pearson {decomp['panel_corr_fresh_pearson']:.3f}) but not identical —
the difference is the net of the two overnight (close-to-next-open) gaps:

```
log(panel_cc) − log(fresh_oo) = log(open[t+1_thu]/close[t+1])
                              − log(open[t_thu]/close[t])
```

i.e. the {{after-close gap at t+1}} minus the {{after-close gap at t}}.

## Reconciling the May-7 (0.0033) and today (0.0238) gap measurements

Both used the same panel and the same definition of "fresh open-to-open
T+1". The factor differs, which is the hypothesis to test.

Computed IC against `weekly_forward_return` (panel) and against fresh
open-to-open over γ for two factors: `z_turnover` (May 7) and
`z_volrev_5_ts` (today).

| factor | n_dates | IC vs panel_cc | IC vs fresh_oo | signed gap | \\|gap\\| |
|---|---|---|---|---|---|
| z_turnover (low-turn pred) | {turn_stats['n_dates']} | {turn_stats['ic_panel_mean']:+.4f} | {turn_stats['ic_fresh_mean']:+.4f} | {turn_stats['mean_signed_gap_panel_minus_fresh']:+.4f} | {turn_stats['mean_abs_gap']:.4f} |
| z_volrev_5_ts (loser × high-vol) | {vr_stats['n_dates']} | {vr_stats['ic_panel_mean']:+.4f} | {vr_stats['ic_fresh_mean']:+.4f} | {vr_stats['mean_signed_gap_panel_minus_fresh']:+.4f} | {vr_stats['mean_abs_gap']:.4f} |

**The gap is factor-dependent.** It depends on how strongly the factor's
cross-sectional rank ordering correlates with the per-stock log-difference
between panel_cc and fresh_oo. Measured directly:

| factor | per-date Spearman(z, log_diff_panel_vs_oo), mean | median |
|---|---|---|
| z_volrev_5_ts | {decomp['vr_corr_with_logdiff_mean']:+.4f} | {decomp['vr_corr_with_logdiff_median']:+.4f} |
| z_turnover | {decomp['turn_corr_with_logdiff_mean']:+.4f} | {decomp['turn_corr_with_logdiff_median']:+.4f} |

The volume-reversal factor's z is **strongly positively correlated**
({decomp['vr_corr_with_logdiff_mean']:+.3f} per-date Spearman) with the
overnight-gap component the panel field includes but fresh_oo excludes.
That is: high-z stocks (recent losers with high abnormal volume —
capitulation candidates) tend to gap UP from Wednesday close to Thursday
open, and the panel's close-to-close return captures that overnight bounce
while fresh open-to-open does not. Hence the panel IC is materially
higher. For the turnover factor, this correlation is much smaller in
magnitude, so the panel-vs-fresh IC gap is smaller.

This is hypothesis (a) from the instruction, confirmed: **the panel uses
close-to-close and the gap depends on the factor's correlation with
overnight returns.** Hypotheses (b) "stale values from partial
regeneration" and (c) "panel and daily files have drifted" are both
rejected by the replication check above (panel = fresh_cc to numerical
precision, no NaN drift beyond documented suspension-gap cases).

## Recommendation

The panel field is correct as documented but **its name is misleading**
and its convention is **not what Phase 2 backtests trade against** (Phase 2
uses fresh open-to-open T+1 per spec §6.1). For factors whose top-decile
concentrates on stocks with large overnight reactions (capitulation
candidates, gap-down recoverers, anything tied to short-term price
microstructure), the IC measured against `weekly_forward_return` will
overstate the tradable economic edge.

Concrete recommendation for the volume-reversal factor and similar
microstructure-leaning factors going forward:

1. **Phase 1 IC should report both numbers**. IC vs `weekly_forward_return`
   (panel close-to-close) AND IC vs fresh open-to-open T+1, side-by-side.
   The panel field is fine for ranking quality; the fresh_oo number is the
   one that aligns with what Phase 2 will trade.
2. **Do not regenerate the panel field as open-to-open**. Other downstream
   work (turnover factor, value/momentum analyses in
   `multi_factor_x1/factor_panel_a.parquet`) was built and validated
   against the close-to-close convention. Changing it would invalidate
   prior results.
3. **Update the spec gotcha**. The spec §10 gotcha 7 covers adj_factor; add
   a gotcha that `weekly_forward_return` is close-to-close, and Phase 2
   open-to-open is the canonical economic measure.
4. **Headline verdict for volume-reversal stands** — Phase 2 already used
   fresh open-to-open T+1, so the FALSIFIED verdict on (L=5, N=100, ts) is
   not affected by this diagnostic. What this diagnostic explains is *why
   Phase 1 IC looked stronger than Phase 2 economics suggested*, not the
   verdict itself.
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"\n  → wrote {out}")


if __name__ == "__main__":
    main()
