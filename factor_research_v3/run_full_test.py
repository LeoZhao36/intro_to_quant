"""
run_full_test.py — Orchestrate the full v3 Phase 1 run end-to-end.

Phases (in order):
  0. Risk-flags table + runtime estimate (printed at start)
  1. Build CSI300 universe panel (refetch missing γ snapshots if needed)
  2. Fetch income + balancesheet for the union universe
  3. Build PIT TTM panel
  4. Build factor panel (ep, roa, log_total_mv, industry, residualisation,
     fresh open-to-open T+1 forward returns)
  5. Self-check pre-flight battery (gate on CRITICAL checks)
  6. Phase 1 IC analysis
  7. Phase 2 backtest (factors × universes × top_n × cost_regimes)
  8. Flight-to-quality (ROA only)
  9. Pre-committed verdicts → verdicts.txt
 10. Print summary

If any pre-run check materially fails or any phase raises, save
diagnostics and STOP rather than proceed silently. Concise but
informative phase logging throughout.

Usage:
    python run_full_test.py                  # full run
    python run_full_test.py --skip-fetch     # skip fundamentals fetch
    python run_full_test.py --phase=verdicts # run only verdicts
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

import data_loaders as dl
import factor_ep
import fr3_config as cfg


# ─── Logging ──────────────────────────────────────────────────────────

class _Tee:
    """Write to both stdout and a log file."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


def _phase(name: str) -> str:
    bar = "─" * 60
    return f"\n{bar}\n{name}\n{bar}"


# ─── Risk flags ───────────────────────────────────────────────────────

def print_risk_flags() -> dict:
    """Pre-run risk flag table. Returns dict for verdict file."""
    print(_phase("RISK FLAGS"))

    flags: dict = {}

    # 1. Tushare token availability
    try:
        sys.path.append(str(Path(__file__).resolve().parent.parent))
        from tushare_setup import pro  # noqa
        flags["tushare_token"] = "OK"
        print("  [OK]Tushare token loaded")
    except Exception as exc:
        flags["tushare_token"] = f"FAIL: {exc}"
        print(f"  [FAIL]Tushare token: {exc}")

    # 2. Universe parquet exists
    if cfg.PRIMARY_UNIVERSE_PATH.exists():
        df = dl.load_primary_universe()
        n_dates = df["trade_date"].nunique()
        flags["primary_universe"] = f"{n_dates} rebalances"
        print(f"  [OK]Primary universe: {n_dates} weekly rebalances")
    else:
        flags["primary_universe"] = "MISSING"
        print(f"  [FAIL]Primary universe missing: {cfg.PRIMARY_UNIVERSE_PATH}")

    # 3. Daily panel coverage over γ
    cal = dl.load_trading_calendar()
    sigs = dl.monthly_signal_dates(cfg.GAMMA_START, cfg.GAMMA_END, cal)
    flags["gamma_signals"] = len(sigs)
    print(f"  [OK]γ monthly signals: {len(sigs)}")

    # 4. pe_ttm coverage estimate (canonical, last γ signal). Two metrics:
    #    - data-quality coverage: any pe_ttm reading (positive or negative)
    #    - tradable-EP coverage: positive readings only (the actual EP signal)
    last = sigs[-1] if sigs else None
    if last is not None:
        canon = dl.get_canonical_universe_at(last, cal)
        cov = factor_ep.coverage_at(last, canon)
        flags["pe_ttm_data_coverage_canonical_last"] = cov["coverage"]
        flags["pe_ttm_tradable_coverage_canonical_last"] = cov["tradable_coverage"]
        msg = (f"pe_ttm at {last.date()} on canonical: "
               f"data-coverage {cov['coverage']:.1%} "
               f"({cov['n_with_pe_ttm']}/{cov['n_total']}), "
               f"tradable-EP {cov['tradable_coverage']:.1%} "
               f"({cov['n_positive_ep']} pos, {cov['n_negative_ep']} non-pos)")
        if cov["tradable_coverage"] < cfg.PE_TTM_TRADABLE_MIN_CANONICAL:
            print(f"  [WARN] {msg}  (tradable-EP below {cfg.PE_TTM_TRADABLE_MIN_CANONICAL:.0%})")
        else:
            print(f"  [OK] {msg}")

    # 5. CSI300 cache coverage
    if cfg.INDEX_CONSTITUENTS_DIR.exists():
        n_csi = len(list(cfg.INDEX_CONSTITUENTS_DIR.glob("csi300_*.parquet")))
        flags["csi300_snapshots"] = n_csi
        print(f"  [OK]CSI300 snapshots cached: {n_csi}")

    # 6. SW L1 industries cached
    if cfg.SW_MEMBERSHIP_PATH.exists():
        sw = dl.load_sw_l1_membership()
        n_ind = sw["industry_code"].nunique()
        flags["sw_industries"] = n_ind
        print(f"  [OK]SW L1 industries: {n_ind}")
    else:
        flags["sw_industries"] = "MISSING"
        print(f"  [FAIL]SW L1 membership missing: {cfg.SW_MEMBERSHIP_PATH}")

    # 7. Suspension density estimate (rough): sample one γ entry day, count
    # codes in universe with vol == 0
    if last is not None:
        nxt = dl.next_trading_day(last, cal)
        if nxt is not None:
            ep_panel = dl.load_daily_panel(nxt.strftime("%Y-%m-%d"))
            if ep_panel is not None:
                canon = dl.get_canonical_universe_at(last, cal)
                in_panel = ep_panel.reindex([c for c in canon if c in ep_panel.index])
                susp = (in_panel["vol"] == 0).sum() if not in_panel.empty else 0
                rate = susp / max(len(in_panel), 1)
                flags["suspension_density_sample"] = rate
                print(f"  [OK]Suspension density sample at {nxt.date()} (canonical): "
                      f"{susp}/{len(in_panel)} = {rate:.1%}")

    # 8. Estimated runtime
    print(f"\n  ESTIMATED RUNTIME (full run, cold cache):")
    print(f"    fundamentals fetch:    ~10–20 min (1500–2000 stocks × 2 endpoints)")
    print(f"    PIT panel build:       ~2 min")
    print(f"    factor panel build:    ~2–4 min")
    print(f"    Phase 1 IC:            ~30 sec")
    print(f"    Phase 2 backtest:      ~5–10 min (2 factors × 2 unis × 5 N × 2 cost)")
    print(f"    flight-to-quality:     ~30 sec")
    print(f"    self-checks:           ~30 sec")
    print(f"    TOTAL: ~25–40 min cold; ~10 min warm")
    return flags


# ─── Verdicts ─────────────────────────────────────────────────────────

def evaluate_verdicts() -> str:
    """Programmatically evaluate Section 11 thresholds."""
    if not cfg.PHASE2_SUMMARY_PATH.exists():
        return "phase2 summary missing; cannot compute verdicts\n"
    summary = pd.read_csv(cfg.PHASE2_SUMMARY_PATH)
    flight = (pd.read_csv(cfg.FLIGHT_TO_QUALITY_PATH)
              if cfg.FLIGHT_TO_QUALITY_PATH.exists()
              else pd.DataFrame())

    lines = []
    lines.append("=" * 70)
    lines.append("PRE-COMMITTED VERDICTS (Section 11 of CC_SPEC)")
    lines.append("=" * 70)
    lines.append(f"Window: {cfg.GAMMA_START.date()} to {cfg.GAMMA_END.date()}")
    lines.append(f"Headline cell: top_n={cfg.HEADLINE_TOP_N}, "
                 f"universe=canonical, cost=headline ({cfg.COST_RT_HEADLINE:.4%} RT)")
    lines.append("")

    # ── EP verdict ────────────────────────────────────────────────────
    ep_row = summary[
        (summary["factor"] == "ep")
        & (summary["universe"] == "canonical")
        & (summary["top_n"] == cfg.HEADLINE_TOP_N)
        & (summary["cost_regime"] == "headline")
    ]
    if ep_row.empty:
        lines.append("EP VERDICT: AMBIGUOUS — headline cell missing from summary")
    else:
        r = ep_row.iloc[0]
        ir = r["ir_vs_benchmark"]
        ci_low = r["ir_ci_low"]
        ci_high = r["ir_ci_high"]
        thr = cfg.EP_THRESHOLDS
        if (ir >= thr.ir_validated_min) and (ci_low > thr.require_ci_low_above):
            verdict = "VALIDATED"
        elif (ir < thr.ir_falsified_max) and (ci_high < thr.require_ci_high_below):
            verdict = "FALSIFIED"
        else:
            verdict = "AMBIGUOUS"
        lines.append(f"EP VERDICT: {verdict}")
        lines.append(f"  IR vs benchmark (net): {ir:+.3f}")
        lines.append(f"  IR 95% CI:             [{ci_low:+.3f}, {ci_high:+.3f}]")
        lines.append(f"  Thresholds:")
        lines.append(f"    VALIDATED ⇐ IR >= {thr.ir_validated_min:+.2f} AND ci_low > {thr.require_ci_low_above:+.2f}")
        lines.append(f"    FALSIFIED ⇐ IR < {thr.ir_falsified_max:+.2f} AND ci_high < {thr.require_ci_high_below:+.2f}")

    lines.append("")

    # ── ROA verdict ───────────────────────────────────────────────────
    roa_row = summary[
        (summary["factor"] == "roa")
        & (summary["universe"] == "canonical")
        & (summary["top_n"] == cfg.HEADLINE_TOP_N)
        & (summary["cost_regime"] == "headline")
    ]
    if roa_row.empty:
        lines.append("ROA VERDICT: AMBIGUOUS — headline cell missing from summary")
    else:
        r = roa_row.iloc[0]
        bench_dd = abs(r["benchmark_max_dd"]) if pd.notna(r["benchmark_max_dd"]) else np.nan
        basket_dd = abs(r["max_drawdown"]) if pd.notna(r["max_drawdown"]) else np.nan
        bench_sharpe = r["benchmark_sharpe"]
        basket_sharpe = r["sharpe"]
        thr = cfg.ROA_THRESHOLDS
        validated = (
            pd.notna(basket_dd) and pd.notna(bench_dd)
            and basket_dd <= thr.drawdown_validated_ratio * bench_dd
            and pd.notna(basket_sharpe) and pd.notna(bench_sharpe)
            and basket_sharpe >= bench_sharpe + thr.sharpe_min_relative
        )
        falsified = (
            pd.notna(basket_dd) and pd.notna(bench_dd)
            and basket_dd > thr.drawdown_falsified_ratio * bench_dd
        ) or (
            pd.notna(basket_sharpe) and pd.notna(bench_sharpe)
            and basket_sharpe < bench_sharpe + thr.sharpe_min_relative
        )
        if validated:
            verdict = "VALIDATED"
        elif falsified:
            verdict = "FALSIFIED"
        else:
            verdict = "AMBIGUOUS"
        lines.append(f"ROA VERDICT: {verdict}")
        lines.append(f"  basket max_dd:     {basket_dd:.3f}  (sharpe {basket_sharpe:+.3f})")
        lines.append(f"  benchmark max_dd:  {bench_dd:.3f}  (sharpe {bench_sharpe:+.3f})")
        lines.append(f"  Thresholds:")
        lines.append(f"    VALIDATED ⇐ basket_dd <= {thr.drawdown_validated_ratio} × bench_dd "
                     f"AND basket_sharpe >= bench_sharpe")
        lines.append(f"    FALSIFIED ⇐ basket_dd > bench_dd OR basket_sharpe < bench_sharpe")

        # Flight-to-quality companion result
        if not flight.empty:
            ft = flight[(flight["universe"] == "canonical")
                        & (flight["top_n"] == cfg.HEADLINE_TOP_N)]
            if not ft.empty:
                ftr = ft.iloc[0]
                lines.append(f"  Flight-to-quality (ROA × canonical × top10):")
                lines.append(f"    rho={ftr['rho_pearson']:+.3f}, "
                             f"95% CI [{ftr['rho_ci_low']:+.3f}, {ftr['rho_ci_high']:+.3f}]")
                lines.append(f"    interpretation: {ftr['interpretation']}")

    lines.append("")

    # ── CSI300 corroboration (no pre-commit) ───────────────────────────
    lines.append("CSI300 corroboration (mechanism check; no pre-commit):")
    for fac in ("ep", "roa"):
        canon = summary[(summary["factor"] == fac)
                        & (summary["universe"] == "canonical")
                        & (summary["top_n"] == cfg.HEADLINE_TOP_N)
                        & (summary["cost_regime"] == "headline")]
        csi = summary[(summary["factor"] == fac)
                      & (summary["universe"] == "csi300")
                      & (summary["top_n"] == cfg.HEADLINE_TOP_N)
                      & (summary["cost_regime"] == "headline")]
        if not canon.empty and not csi.empty:
            ir_canon = canon["ir_vs_benchmark"].iloc[0]
            ir_csi = csi["ir_vs_benchmark"].iloc[0]
            lines.append(f"  {fac.upper()}: IR canonical={ir_canon:+.2f}, IR CSI300={ir_csi:+.2f}, "
                         f"diff={ir_canon - ir_csi:+.2f} (expected positive if retail mechanism)")

    lines.append("")
    lines.append("Stress regime cells (cost_regime=stress) reported but do NOT affect verdicts.")
    lines.append("=" * 70)

    txt = "\n".join(lines) + "\n"
    cfg.VERDICTS_PATH.write_text(txt, encoding="utf-8")
    print(txt)
    return txt


# ─── Phase runners ────────────────────────────────────────────────────

def _run_phase(label: str, fn: Callable[[], None]) -> None:
    print(_phase(f"[{label}]"))
    t0 = time.time()
    fn()
    print(f"  → {label} done in {time.time()-t0:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch", action="store_true",
                        help="skip fundamentals fetch (use existing cache)")
    parser.add_argument("--phase", default="all",
                        choices=("all", "risk_flags", "csi300", "fetch", "pit",
                                 "factor_panel", "self_check", "phase1",
                                 "phase2", "flight", "verdicts"))
    args = parser.parse_args()

    # Tee stdout to log file
    log_f = open(cfg.RUN_LOG_PATH, "w", encoding="utf-8")
    sys.stdout = _Tee(sys.__stdout__, log_f)

    t_start = time.time()
    print(f"factor_research_v3 — full Phase 1 run")
    print(f"  start: {pd.Timestamp.now()}")
    print(f"  γ window: {cfg.GAMMA_START.date()} .. {cfg.GAMMA_END.date()}")

    # Phase 0: risk flags
    if args.phase in ("all", "risk_flags"):
        print_risk_flags()

    # Phase 1: CSI300
    if args.phase in ("all", "csi300"):
        def _build_csi300():
            from csi300_universe_builder import build_and_save
            build_and_save()
        _run_phase("Phase 1: CSI300 universe", _build_csi300)

    # Phase 2: fundamentals fetch
    if args.phase in ("all", "fetch") and not args.skip_fetch:
        def _fetch():
            from tushare_fundamentals_fetch import fetch_universe
            fetch_universe()
        _run_phase("Phase 2: fundamentals fetch", _fetch)

    # Phase 3: PIT panel
    if args.phase in ("all", "pit"):
        def _build_pit():
            from pit_panel_builder import build_and_save
            build_and_save()
        _run_phase("Phase 3: PIT TTM panel", _build_pit)

    # Phase 4: factor panel
    if args.phase in ("all", "factor_panel"):
        def _build_fp():
            from factor_panel import build_and_save
            build_and_save()
        _run_phase("Phase 4: factor panel", _build_fp)

    # Phase 5: self-checks
    if args.phase in ("all", "self_check"):
        def _self_check():
            from self_checks import run_all
            df = run_all()
            n_fail = (df["status"] == "FAIL").sum()
            n_critical_fail = (
                df[df["check"].isin([
                    "synthetic_recovery", "fwl_precision",
                    "pit_correctness", "ttm_cumulative_verification",
                ])]["status"] == "FAIL"
            ).sum()
            if n_critical_fail > 0:
                raise RuntimeError(
                    f"CRITICAL self-check failure: {n_critical_fail} critical "
                    f"check(s) failed. STOPPING. See {cfg.SELF_CHECK_RESULTS_PATH}."
                )
        _run_phase("Phase 5: self-checks", _self_check)

    # Phase 6: Phase 1 IC
    if args.phase in ("all", "phase1"):
        def _phase1():
            from phase1_ic import run as phase1_run
            phase1_run()
        _run_phase("Phase 6: Phase 1 IC", _phase1)

    # Phase 7: Phase 2 backtest
    if args.phase in ("all", "phase2"):
        def _phase2():
            from phase2_backtest import run as phase2_run
            phase2_run()
        _run_phase("Phase 7: Phase 2 backtest", _phase2)

    # Phase 8: flight-to-quality
    if args.phase in ("all", "flight"):
        def _flight():
            from flight_to_quality import run as ftq_run
            ftq_run()
        _run_phase("Phase 8: flight-to-quality", _flight)

    # Phase 9: verdicts
    if args.phase in ("all", "verdicts"):
        evaluate_verdicts()

    print(_phase("RUN COMPLETE"))
    print(f"  total elapsed: {(time.time()-t_start)/60:.1f} min")
    print(f"  log: {cfg.RUN_LOG_PATH}")
    print(f"  verdicts: {cfg.VERDICTS_PATH}")
    log_f.close()


if __name__ == "__main__":
    main()
