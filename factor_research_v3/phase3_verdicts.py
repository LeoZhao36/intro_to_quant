"""
phase3_verdicts.py — Pre-committed scenario verdict.

Per CC_SPEC_factor_research_v3_phase2.md section 5:

  A  iff filter_effect_canonical < -3 pp annual
  C  iff filter_effect_canonical > +3 pp annual
  B  iff |filter_effect_canonical| <= 3pp AND sort_effect_ep_canonical < -5pp
  MIXED otherwise

Reads phase3_decomposition_summary.csv, evaluates against
fr3_config.PHASE3_FILTER_THRESHOLD_PP / PHASE3_SORT_THRESHOLD_PP.
Saves human-readable verdict to phase3_verdicts.txt.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import fr3_config as cfg


def evaluate() -> str:
    if not cfg.PHASE3_DECOMPOSITION_PATH.exists():
        return "phase3 decomposition missing; run phase3_decomposition.py first\n"
    dec = pd.read_csv(cfg.PHASE3_DECOMPOSITION_PATH)

    def _ann(universe, basket):
        rows = dec[(dec["universe"] == universe) & (dec["basket_type"] == basket)]
        return float(rows["ann_return"].iloc[0]) if not rows.empty else np.nan

    canon_uni = _ann("canonical", "universe_EW")
    canon_prof = _ann("canonical", "profitable_EW")
    canon_loss = _ann("canonical", "loss_maker_EW")
    canon_ep = _ann("canonical", "top10_ep")
    canon_roa = _ann("canonical", "top10_roa")
    csi_uni = _ann("csi300", "universe_EW")
    csi_prof = _ann("csi300", "profitable_EW")
    csi_ep = _ann("csi300", "top10_ep")
    csi_roa = _ann("csi300", "top10_roa")

    canon_filter = canon_prof - canon_uni
    canon_sort_ep = canon_ep - canon_prof
    canon_sort_roa = canon_roa - canon_prof
    csi_filter = csi_prof - csi_uni
    csi_sort_ep = csi_ep - csi_prof
    csi_sort_roa = csi_roa - csi_prof

    F = cfg.PHASE3_FILTER_THRESHOLD_PP
    S = cfg.PHASE3_SORT_THRESHOLD_PP

    if canon_filter < -F:
        scenario = "A"
        triggered = f"filter_effect_canonical = {canon_filter:+.3f} < -{F:.2f}"
        interpretation = (
            "FILTER IS THE HEADWIND. The profitable subset of the canonical universe\n"
            "underperformed the full universe-EW (loss-makers outperformed). Any\n"
            "profit-themed factor will fail in the γ regime on this universe.\n"
            "  Implication: shelve profit-themed factors for now; reconsider when\n"
            "    the regime turns. Loss-maker outperformance often reflects\n"
            "    speculative/distressed name rallies (新国九条 risk-on) and tends\n"
            "    not to persist."
        )
    elif canon_filter > F:
        scenario = "C"
        triggered = f"filter_effect_canonical = {canon_filter:+.3f} > +{F:.2f}"
        interpretation = (
            "FILTER IS A TAILWIND. Profitable names outperformed the universe.\n"
            "Unusual finding given the EP/ROA top-10 underperformance.\n"
            "  Implication: investigate; the headline IR negativity is then\n"
            "    entirely from sort, not filter."
        )
    elif abs(canon_filter) <= F and canon_sort_ep < -S:
        scenario = "B"
        triggered = (f"|filter| = {canon_filter:+.3f} ≤ {F:.2f} AND "
                     f"sort_ep = {canon_sort_ep:+.3f} < -{S:.2f}")
        interpretation = (
            "FILTER NEUTRAL, SORT BROKEN. The EP/ROA sort within the profitable\n"
            "subset is what underperforms — not the filter. Likely sector\n"
            "concentration or factor-sign inversion at top-10 concentration.\n"
            "  Implication: investigate sector-level attribution before deciding;\n"
            "    consider industry-neutral residualisation or larger top_n."
        )
    else:
        scenario = "MIXED"
        triggered = (f"filter = {canon_filter:+.3f} (neither <-{F:.2f} nor >+{F:.2f}); "
                     f"sort_ep = {canon_sort_ep:+.3f} (not <-{S:.2f})")
        interpretation = (
            "MIXED. Both filter and sort are meaningful but neither dominant.\n"
            "  Implication: the failure is a compound of small headwinds; no\n"
            "    single fix likely to recover the factor. Consider whether the\n"
            "    γ regime is just unfavorable to both effects together."
        )

    lines = []
    lines.append("=" * 70)
    lines.append("PHASE 3 SCENARIO VERDICT (filter-vs-sort decomposition)")
    lines.append("=" * 70)
    lines.append(f"Window: {cfg.GAMMA_START.date()} to {cfg.GAMMA_END.date()}, "
                 f"monthly cadence, headline cost ({cfg.COST_RT_HEADLINE:.4%} RT)")
    lines.append("")
    lines.append(f"SCENARIO: {scenario}")
    lines.append(f"  triggered by: {triggered}")
    lines.append(f"  thresholds: filter ±{F:.2f}, sort -{S:.2f}")
    lines.append("")
    lines.append("INTERPRETATION:")
    lines.append("  " + interpretation.replace("\n", "\n  "))
    lines.append("")
    lines.append("DECOMPOSITION TABLE")
    lines.append("-" * 70)
    lines.append(f"{'CANONICAL':<24s} {'ann_return':>12s}")
    lines.append("-" * 70)
    lines.append(f"  universe_EW            {canon_uni:>+12.3f}")
    lines.append(f"  profitable_EW          {canon_prof:>+12.3f}")
    lines.append(f"  loss_maker_EW          {canon_loss:>+12.3f}")
    lines.append(f"  top10_ep               {canon_ep:>+12.3f}")
    lines.append(f"  top10_roa              {canon_roa:>+12.3f}")
    lines.append(f"  filter_effect          {canon_filter:>+12.3f}  (profitable - universe)")
    lines.append(f"  sort_effect_ep         {canon_sort_ep:>+12.3f}  (top10_ep - profitable)")
    lines.append(f"  sort_effect_roa        {canon_sort_roa:>+12.3f}  (top10_roa - profitable)")
    lines.append("")
    lines.append(f"{'CSI300':<24s} {'ann_return':>12s}")
    lines.append("-" * 70)
    lines.append(f"  universe_EW            {csi_uni:>+12.3f}")
    lines.append(f"  profitable_EW          {csi_prof:>+12.3f}")
    lines.append(f"  top10_ep               {csi_ep:>+12.3f}")
    lines.append(f"  top10_roa              {csi_roa:>+12.3f}")
    lines.append(f"  filter_effect          {csi_filter:>+12.3f}")
    lines.append(f"  sort_effect_ep         {csi_sort_ep:>+12.3f}")
    lines.append(f"  sort_effect_roa        {csi_sort_roa:>+12.3f}")
    lines.append("")

    # Sector decomposition (canonical only)
    if cfg.PHASE3_SECTOR_AGG_PATH.exists():
        sec = pd.read_csv(cfg.PHASE3_SECTOR_AGG_PATH)
        lines.append("SECTOR DECOMPOSITION (canonical, top-10, headline)")
        lines.append("-" * 70)
        for _, r in sec.iterrows():
            lines.append(f"  {r['factor'].upper():<5s}: "
                         f"active={r['ann_active_vs_universe']:+.3f}  "
                         f"= filter {r['ann_filter_effect']:+.3f}"
                         f" + sector_tilt {r['ann_sector_tilt_effect']:+.3f}"
                         f" + selection {r['ann_selection_effect']:+.3f}")
        lines.append("")

    # Quintile spreads
    if cfg.PHASE3_QUINTILE_PATH.exists():
        qs = pd.read_csv(cfg.PHASE3_QUINTILE_PATH)
        spreads = qs[qs["quintile"] == "Q5-Q1"]
        if not spreads.empty:
            lines.append("QUINTILE SORT Q5-Q1 SPREADS (within profitable subset)")
            lines.append("-" * 70)
            for _, r in spreads.iterrows():
                lines.append(f"  {r['factor'].upper():<5s} × {r['universe']:<10s}: "
                             f"Q5-Q1 ann={r['ann_return']:+.3f}, "
                             f"sharpe={r['sharpe']:+.2f}  "
                             f"({r['n_periods']} periods)")
            lines.append("")
    lines.append("=" * 70)
    txt = "\n".join(lines) + "\n"
    cfg.PHASE3_VERDICTS_PATH.write_text(txt, encoding="utf-8")
    print(txt)
    return txt


def main() -> None:
    evaluate()


if __name__ == "__main__":
    main()
