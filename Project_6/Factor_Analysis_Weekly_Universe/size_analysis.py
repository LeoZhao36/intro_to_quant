"""
size_analysis.py — Size factor (log market cap) on the rebuilt weekly panel.

Structurally the smallest of the four single-factor reruns: log_mcap
has no formation window, so there is no burn-in and 100% coverage at
every date. This makes it a good first port of the new infrastructure;
if the cap-tercile and Layer 4 machinery work here, they work for the
factors with formation windows too.

Sign convention
---------------
Q1 = LOW log_mcap = smallest stocks.
Q5 = HIGH log_mcap = largest stocks.

Size premium hypothesis (Banz 1981 / academic consensus):
    Q1 > Q5 (small outperforms), so Q1-Q5 > 0 / IC < 0.

Within our universe, expected to be muted because the universe is
already filtered to the bottom-1000 by cap. The "small stocks
outperform" effect is partially exhausted at the universe level.

Reference (old monthly result on 51 months, 2022-2026)
------------------------------------------------------
Headline Q1-Q5: -0.181%/mo (small slightly UNDER-performed)
IC mean:        +0.0153 (positive => bigger stocks did marginally better
                 within the universe)
Layer 5: low p=0.878, mid p=0.080, high p=0.674

Mid-cap p of 0.080 was the only hint of structure within terciles,
suggestive but didn't BH-reject. The old null was the headline finding.

Logged predictions for the rebuilt panel (record before reading output)
-----------------------------------------------------------------------
Sample size has expanded ~7.5x (380 weeks vs 51 months) and the date
range now includes 2019 small-cap rally and post-2024 stimulus rally.
Net effect on headline ambiguous.

  Headline Q1-Q5 (in %/wk):  [-0.05, +0.10] / t in [-1.5, +2.5]
  IC mean:                   [-0.005, +0.005] (effectively zero)
  Layer 2 candidate splits:  pre-COVID likely shows small outperformance
                              (+0.05 to +0.15%/wk); post-PBoC similarly
                              if the small-cap reversal extended into
                              the within-universe small/large structure.
                              COVID-window (2020-01-23 to 2022-12-07)
                              expected flat or muddled.
  Layer 4 (sector-neutral):  approximately matches headline; size has
                              little sector concentration in our universe.
  Layer 5 (within-tercile):  for size, factor_col == cap_col, so the
                              within-tercile sort asks about non-linearity
                              in the size-return relationship. Old result's
                              mid-cap p=0.080 may not survive the larger
                              sample. Most cells expected to BH-fail.

Highest-confidence prediction: IC near zero in absolute terms.
Lowest-confidence: the magnitude and sign of the headline Q1-Q5.

Failure modes
-------------
1. Size within an already-bottom-1000 universe is a narrow conditional.
   The "small-cap premium" research finding usually compares small to
   large across the WHOLE market; we are sub-sampling the small-cap
   bucket. A null here doesn't refute size as a factor; it refutes
   size as a within-small-cap factor.
2. Cap drift: universe mean cap rose from ~20亿 in 2019 to ~36亿 in 2026
   (mechanism A confirmed). Within-period quintile sorts use the date's
   local distribution, but cumulative-return plots compare baskets of
   structurally different absolute sizes across time. Read the plot
   carefully: a "Q1 wins" line over 7 years means small-relative-to-its-
   own-period stocks won, not "stocks that were small in 2019 won".
3. Layer 5 is a non-linearity check, not an independent factor test:
   factor_col == cap_col means "does cap predict within cap buckets?"
   A within-tercile rejection means the size-return relationship is
   non-monotonic, which is interpretively different from "size predicts
   in tercile X but not Y" for a non-cap factor.

Run from Project_6/:
    python Factor_Analysis_Weekly_Universe/size_analysis.py
"""

import pandas as pd

from config import DATA_DIR, GRAPHS_DIR
from factor_utils import (
    load_factor_panel,
    compute_quintile_series,
    compute_ic_series,
    summarise_long_short,
    layer_1_bootstrap_ci,
    layer_2_regime_split,
    layer_3_tradable_only,
    layer_4_sector_neutral,
    layer_5_cap_terciles,
    plot_cumulative_quintiles,
    plot_ic_series,
    report_coverage_by_year,
    collect_factor_results,
)


# ─── Factor configuration ──────────────────────────────────────────────

FACTOR_COL = "log_mcap"
FACTOR_LABEL = "log market cap"
OUTPUT_PREFIX = "size"


# ─── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    panel = load_factor_panel()
    print(f"Panel loaded: {len(panel):,} rows, "
          f"{panel['rebalance_date'].nunique()} dates")
    print(f"  in-universe rows: {int(panel['in_universe'].sum()):,}")

    # Coverage diagnostic. Routine for every factor; size is trivially
    # 100% but the call documents the discipline.
    report_coverage_by_year(panel, FACTOR_COL)

    # ── Headline ───────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print(f"Headline (size: {FACTOR_LABEL} quintile sort)")
    print("=" * 72)
    quintiles = compute_quintile_series(panel, sort_col=FACTOR_COL)
    headline = summarise_long_short(quintiles, "headline Q1-Q5")
    ic = compute_ic_series(panel, sort_col=FACTOR_COL)
    print(f"  IC: mean={ic.mean():+.4f}, std={ic.std():.4f}, n={len(ic)}")
    print(f"  (Q1=smallest, Q5=largest. Size premium: Q1-Q5 > 0 / IC < 0.)")

    # ── Plots ──────────────────────────────────────────────────────────
    plot_cumulative_quintiles(
        quintiles, FACTOR_LABEL,
        save_path=GRAPHS_DIR / f"{OUTPUT_PREFIX}_quintile_cumulative_returns.png",
    )
    plot_ic_series(
        ic, FACTOR_LABEL,
        save_path=GRAPHS_DIR / f"{OUTPUT_PREFIX}_ic_time_series.png",
    )

    # ── Robustness layers ──────────────────────────────────────────────
    layer_1 = layer_1_bootstrap_ci(panel, factor_col=FACTOR_COL)
    layer_2 = layer_2_regime_split(panel, factor_col=FACTOR_COL)
    layer_3 = layer_3_tradable_only(panel, factor_col=FACTOR_COL)  # DEFERRED
    layer_4 = layer_4_sector_neutral(panel, factor_col=FACTOR_COL)
    layer_5 = layer_5_cap_terciles(
        panel, factor_col=FACTOR_COL, cap_col="log_mcap",
    )

    # ── Save structured results ────────────────────────────────────────
    rows = collect_factor_results(
        factor_name="size",
        headline=headline,
        ic=ic,
        layer_1=layer_1,
        layer_2=layer_2,
        layer_4=layer_4,
        layer_5=layer_5,
    )
    out_path = DATA_DIR / f"single_factor_{OUTPUT_PREFIX}_results.csv"
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"\nResults saved to: {out_path}")

    print("\n" + "=" * 72)
    print("Size-factor analysis complete.")
    print("=" * 72)