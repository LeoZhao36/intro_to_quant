"""
value_analysis.py — Value factor (EP = 1/pe_ttm) on the rebuilt weekly panel.

The standout single-factor finding from the old monthly Project 6 was
value BH-rejecting in the LOW-CAP tercile, not at the headline level.
This rerun is the most diagnostic test of whether the universe rebuild
fundamentally changes the cap-tercile structure: same finding amplifies
(real signal, old bias was destroying part of it), evaporates (old bias
was creating apparent signal in extreme low-cap-value names), or persists
unchanged (old bias was orthogonal). All three outcomes inform Phase C.

The architecture fix has limited direct effect on value at the univariate
level because EP has no formation window — it's read directly from the
contemporaneous pe_ttm. Where the fix matters is FMB (Phase C), where
value's z-score gets used alongside formation-window factors. So expect
the headline value sort here to be roughly comparable to the old
monthly result; large divergence would suggest panel-construction
differences beyond what we'd attributed to the rebuild.

Sign convention
---------------
Factor: EP = 1 / pe_ttm where pe_ttm > 0; NaN otherwise (CH-3 exclusion).
Q1 = LOW EP = expensive stocks.
Q5 = HIGH EP = cheap stocks.

Value premium hypothesis: Q5 > Q1 (cheap outperforms), so Q1-Q5 < 0 / IC > 0.

Reference (old monthly result on 51 months, 2022-2026)
------------------------------------------------------
Headline Q1-Q5: roughly -0.4%/mo (small effect, did NOT BH-reject pooled)
Layer 5: low-cap Q1-Q5 ~ -1.1%/mo, BH-REJECTED
         mid-cap        ~ null
         high-cap       ~ null
Layer 4 (sector-neutral): strengthened versus headline; cheapness in
                           A-shares concentrates in banks, utilities,
                           materials, so removing the sector mean isolates
                           cheap-within-sector signal.

The cap-tercile structural finding is the canonical "value lives in the
small-cap segment" result that survived the original five-layer machinery.

Logged predictions for the rebuilt panel
----------------------------------------
Sample expansion 7.5x and date range expansion to 2019-2026. The 2019
growth rally and the 2020-2021 COVID-era growth dominance are now
included, as is the 2023 reopening-era cyclical rally and the
post-stimulus broad rally. Net effect on headline ambiguous in
magnitude but direction-confident.

  Headline Q1-Q5 (%/wk):     [-0.20, -0.05] / t in [-3.5, -0.8]
                              (weekly equivalent of monthly old -0.4%/mo
                               is roughly -0.10%/wk)
  IC mean:                   [+0.008, +0.030]
  Layer 2 candidate splits:  COVID reopening is the most informative.
                              Pre-reopening (heavy growth rally years)
                              expected weak/null; post-reopening expected
                              strongest as cyclical-cheap stocks rallied.
                              PBoC stimulus split likely shows reduction
                              in differentiation post-stimulus (broad
                              rally washes out value sort).
  Layer 4 (sector-neutral):  STRENGTHENS vs headline. Within-sector
                              cheapness should be a cleaner signal than
                              raw EP because the raw sort is contaminated
                              by sector composition.
  Layer 5 (within-tercile):  THE KEY CELL. If low-cap value still
                              BH-rejects with 380 weeks at -0.20 to
                              -0.40%/wk, the rebuilt panel confirms the
                              structural finding. If low-cap evaporates,
                              the original was likely shell-value-driven
                              and the universe filter is now scrubbing it.
                              Mid and high-cap most likely null.

Highest-confidence prediction: Layer 4 strengthens vs headline.
Lowest-confidence: low-cap Layer 5 magnitude. The rebuilt panel could
plausibly produce anything from -0.50%/wk (amplification) to +0.05%/wk
(evaporation).

Failure modes specific to value
-------------------------------
1. Shell-value contamination per CH-3. Liu-Stambaugh-Yuan 2019 excluded
   the smallest 30% of A-shares from value sorts because shell-buyout
   speculation makes "cheap" small stocks rally for non-fundamental
   reasons. Our universe is the bottom-1000 by cap, which structurally
   overlaps with the LSY-excluded zone. The (X=75, Y=3000万) liquidity
   filter and PIT ST exclusion scrub most of this, but a low-cap value
   rejection should still be read with the shell-value alternative
   hypothesis on the table.

2. Late-panel EP coverage drift. Coverage falls from ~82% in 2019 to
   ~62% in 2026 (Phase A finding). The drift reflects more loss-making
   firms in the universe in late years (Tushare encodes negative TTM as
   NaN). Late-panel quintile sorts use ~620 stocks instead of ~820, so
   each quintile holds ~124 stocks instead of ~164 — still plenty for
   a stable sort but a smaller cross-section to push noise around.
   Watch for divergence between pre-2023 and post-2023 results that
   tracks the coverage drift rather than a substantive regime change.

3. Negative-earnings exclusion creates selection. Stocks with pe_ttm<=0
   are dropped from the value sort (NaN EP), so the cross-section is
   biased toward profitable firms. Loss-making firms could include
   both genuine distress and turnaround opportunities. We can't recover
   either group with this construction; documented and accepted.

4. Reopening-rally interaction with cap-tercile. In 2023 the cheap
   names that rallied hardest were cyclical mid/large names (banks,
   energy, materials). The low-cap value cell's signal in 2023-2024
   could thus be DILUTED, not amplified, by post-reopening dynamics —
   the cyclical cheap rally was concentrated above the low-cap tercile.

Run from Project_6/:
    python Factor_Analysis_Weekly_Universe/value_analysis.py
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

FACTOR_COL = "ep"
FACTOR_LABEL = "earnings yield (E/P)"
OUTPUT_PREFIX = "value"


# ─── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    panel = load_factor_panel()
    print(f"Panel loaded: {len(panel):,} rows, "
          f"{panel['rebalance_date'].nunique()} dates")
    print(f"  in-universe rows: {int(panel['in_universe'].sum()):,}")

    # Coverage diagnostic. EP coverage drifts down across the panel
    # (~82% in 2019 to ~62% in 2026); reading this table first sets
    # context for the regime-split layer below.
    report_coverage_by_year(panel, FACTOR_COL)

    # ── Headline ───────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print(f"Headline (value: {FACTOR_LABEL} quintile sort)")
    print("=" * 72)
    quintiles = compute_quintile_series(panel, sort_col=FACTOR_COL)
    headline = summarise_long_short(quintiles, "headline Q1-Q5")
    ic = compute_ic_series(panel, sort_col=FACTOR_COL)
    print(f"  IC: mean={ic.mean():+.4f}, std={ic.std():.4f}, n={len(ic)}")
    print(f"  (Q1=expensive=low EP, Q5=cheap=high EP. "
          f"Value premium: Q1-Q5 < 0 / IC > 0.)")

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
        factor_name="value",
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
    print("Value-factor analysis complete.")
    print("=" * 72)