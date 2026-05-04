# Project 6 Universe Rebuild — Handoff Document (Finalized)

**Completed:** 2026-04-29
**Status:** Universe rebuild complete. Stages 0-5 architecturally sound. Ready for factor-utility refactor and rebuilt-panel re-runs.

---

## Key takeaways

The universe rebuild fixed three architectural problems with the original Project 6 panel: the 19.9% FMB coverage produced by universe-turnover bias, the ~6% survivorship bypass in the ST filter, and the 20-day liquidity window's vulnerability to single-day volume spikes. The rebuilt panel covers 2019-01-02 to 2026-04-29 with weekly Wednesday rebalances, a 60-day liquidity window, and point-in-time ST filtering via `pro.namechange()`. N=1000 holds on every one of 381 weekly dates with no undersized weeks.

The cap-drift diagnostic confirmed that the late-panel universe cap inflation (~20亿 to ~35亿 mean) is mechanism A: market-wide cap inflation, not parameter-driven drift. The (X=75, Y=3000) tuple is regime-stable and does not need retuning before factor work begins.

The cost-adjusted Sharpe warm-up reproduced the closeout's 0.61 segmented-strategy Sharpe (after correcting for the date-window bug where 51 dates were used instead of the 41 common testable dates). At the assumed cost stack of 0.31% round-trip (印花税 0.05% sell-side + 佣金 0.025% each side + 过户费/监管费/经手费 0.013% round-trip + slippage 0.10% per side), the segmented strategy survives realistic costs at most plausible turnover/slippage combinations; cost-adjustment is not the kill shot for this strategy. Whether anything has alpha is the open question the rebuilt panel will answer.

Stage 5's candidate-history panel is the architectural fix for the universe-turnover bias. Factor pipelines on the new panel read full daily history for every stock that has ever been in the universe, regardless of whether the stock was in-universe on any particular date. Expected coverage rises from 19.9% to 70-80%, with the residual gap reflecting genuine data limitations (IPOs younger than the formation window, long suspensions, mid-window delistings) rather than architectural bias.

---

## Reference conversations

- **Project 5 Closeout** (`Project_Five_Closeout.md`) — the previous universe construction (52 monthly dates, 20-day liquidity window, ~3,500 candidates per date). The rebuild supersedes this for production use but the closeout remains canonical for the methodology that informed it.
- **Project 6 Single-Factor Phase Closeout** (`Project_6_Single_Factor_Phase_Closeout.md`) — established the cap-tercile structural finding (value BH-rejecting in low-cap, low-vol BH-rejecting in high-cap, mid-cap structurally null).
- **Project 6 Multi-Factor Phase Closeout** (`Project_Six_Multi_Factor_Phase_Closeout.md`) — surfaced the universe-turnover problem and the survivorship bypass that motivated this rebuild. Established the pre-stimulus z_size FMB-rejection as the multi-factor finding to carry into the rebuilt panel.
- **This conversation** — the universe rebuild itself, executed as Stages 0 through 5 with one cost-adjustment warm-up at the start.

---

## Starting point

Entered the rebuild from the Project 6 multi-factor phase closeout with three architectural problems on the table and a refactor backlog from prior phases.

The data inputs available at session start: the original 51-date monthly forward-return panel, the original 1,000-stock universe membership panel, the segmented-strategy returns CSV, and the Project 5 codebase (`tushare_build_universe.py`, `liquidity_panel.py`, `forward_return_panel.py`, `universe_membership.py`, `universe_behaviour.py`, `validate_limit_state.py`).

The decisions locked at session start before any code was written: weekly Wednesday rebalances (academic standard, minimizes weekend-news and end-of-week effects), 60-day liquidity window (smooths through transient volume bursts), 2019-01-02 panel start (covers COVID and the small-cap rotation regimes the original panel missed), parquet for the daily panel and CSV/parquet for downstream summaries (10-100x I/O speedup for the data shape we work with), unified daily panel as the single source of truth (eliminates the three-cache pattern Project 5 had).

---

## Session thesis

Rebuild the universe construction from scratch with three architectural fixes (universe-turnover, survivorship, liquidity smoothing) and produce a panel suitable for re-running every Project 6 analysis with adequate statistical power. The rebuild is methodological investment, not factor work. Factor results from the original panel may or may not survive the rebuild; that determination is for the next conversation.

---

## Progression

The session executed in roughly this order, with each step blocking the next.

**Cost-adjusted Sharpe warm-up.** Implemented the cost model on the segmented-strategy returns. Surfaced and fixed a date-window bug (script used all 51 rows of `segmented`; closeout numbers used the 41 common testable dates where every strategy column has a value). Reconciled the closeout's gross Sharpe of 0.61 exactly. Confirmed costs alone do not kill segmented; the bigger problem is the panel architecture.

**Stage 0: unified daily panel pull.** Wrote the per-day pull combining `daily`, `daily_basic`, and `adj_factor`. First version was sequential, took ~9s/day for 5 smoke days. Researched optimization, learned that per-call latency was the bottleneck (not rate limit), implemented `ThreadPoolExecutor` with 6 workers, sliding-window rate limiter at 400/min cap, ZSTD compression, and float32 numeric downcasting. Schema validator strengthened to detect dtype mismatches in cached parquets so old float64+snappy files would correctly invalidate. Full pull completed in ~50 minutes producing ~700 MB across 2,018 daily parquets (versus ~3 GB / ~5 hours with the original snappy+float64 sequential design).

**EP point-in-time validation.** Wrote `validate_pe_ttm.py` to test whether `daily_basic.pe_ttm` updates correctly on earnings announcements. Three test cases: 中国平安 (601318.SH) 2023 annual, 贵州茅台 (600519.SH) 2024 Q1, 比亚迪 (002594.SZ) 2024 mid-year. The script's verdicts came back as MIXED/INVESTIGATE because of unrealistic stability thresholds (`pe_ttm = close / EPS_ttm` jitters with price even when EPS is steady). Manual back-out of implied EPS confirmed clean point-in-time behavior across all three: 中国平安 stepped from 5.20 to 4.70 on the trading day after the announcement; 贵州茅台 stepped across the weekend (announcement on Saturday); 比亚迪 stepped on announcement day. EP = 1 / pe_ttm is safe to use directly.

**Stage 1: weekly candidates with point-in-time names.** Generated 381 Wednesday rebalance dates (rolled forward to next trading day on holidays, deduplicated). First version used current-name ST filter from `stock_basic`; smoke revealed 5.96% NaN-name survivorship (213 stocks per Jan-2019 date). Inspection of the unknown-name pool confirmed these were genuine delistings (000018.SZ 神州长城, 000023.SZ 深天地, 000413.SZ 东旭光电, 000540.SZ 中天金融, etc.) — many of which were ST or *ST in 2019 and were silently bypassing the filter. Pulled `pro.namechange()` (34,256 historical name records covering 6,108 stocks) and rewrote the ST filter to use point-in-time names. Result: 0 truly nameless rows, 78-82 ST/*ST stocks per Jan-2019 date now correctly caught. Total candidate count rose by ~108 stocks per Jan-2019 date because the PIT filter also fixed the inverse error (stocks currently named ST that were healthy in 2019 were being wrongly dropped from historical dates).

**Stage 2: 60-day liquidity panel.** Computed trailing 60-trading-day mean trading amount per (stock, date). Vectorized the rolling window via concat-then-groupby to keep wall time at ~1 minute. Output: 1,825,104 rows across 5,739 unique stocks, 94.6% with full-window coverage, median amount 9,417 万 (~0.94 亿). Suspended-day handling preserved data authenticity: stocks with insufficient trading days get a count column documenting why, NaN where no data exists rather than silent zero-fill.

**Stage 3: hybrid liquidity floor + bottom-1000 selection.** Selected (X=75, Y=3000) tuple after discussing the trade-off (X=80 would match Project 5's continuity; X=75 is slightly more aggressive given the 60-day smoothing has already reduced noise). Added `n_trading_days_observed >= 20` minimum coverage filter (drops stocks suspended for >2/3 of the 60-day window as structurally untradable). Built diagnostic plot showing universe liquidity, market cap distribution, and inter-week turnover. Result: N=1000 on every of 381 dates, 0 undersized, median weekly turnover 6.0%, smallest cap stable around 4-5亿 in early panel rising to ~12-15亿 in late panel.

**Cap-drift diagnostic.** Built and ran the universe-cap-vs-base-cap ratio test. Result: mechanism A confirmed (ratio stable across panel), so the late-panel cap inflation is market-wide and benign rather than parameter-driven. (X=75, Y=3000) does not need retuning before factor work.

**Stage 4: SW2021 sector pull.** Pulled 申万 hierarchy (3 calls) and full L3 membership (~346 calls). Output: `sw_classification.csv` and `sw_membership.csv` (5,834 rows for 5,834 stocks). Discovered the SW data is flat (one record per stock; historical reclassifications not captured). This is a known limitation of `pro.index_member_all` rather than a bug.

**Stage 5: candidate-history panel.** Built the architectural fix for universe-turnover bias. Smoke testing revealed 12.3% of rows had NaN L1 sector for stocks added to SW classification after the panel start (e.g., 000004.SZ added 2021-07-30 had no sector for its 2018-2021 rows). Implemented backward-fill in `sector_as_of`: if a date is before the recorded `in_date`, the earliest known sector is applied. Result: ~99-100% L1 sector coverage. Full panel write produces ~8M rows for ~3,985 candidate stocks across 2,018 trading days.

---

## Conceptual ground established

**The N-T-measurement decomposition of factor analysis power.** N (cross-section size), T (time periods), and measurement quality are three independent levers. Each one requires a different fix: N expansion comes from solving the universe-turnover problem; T expansion comes from extending the panel start date or increasing rebalance frequency; measurement quality comes from data hygiene fixes like PIT names. The rebuild addresses all three.

**The universe-turnover bias mechanism.** Factor signals computed only on in-universe stocks systematically miss the formation-window data of stocks transitioning into the universe. A 12-month vol or momentum window cannot be computed if the stock was not stored in the panel during those 12 months. The fix is to decouple signal computation (full candidate pool history) from cross-sectional sort eligibility (in-universe filter).

**The hybrid floor design.** The percentile gate provides relative-liquidity stability across regimes; the absolute floor catches genuine bottom-end illiquid names that would survive percentile in low-liquidity regimes. Neither alone is sufficient; both together produce a regime-stable filter.

**Point-in-time data hygiene.** `stock_basic` returns current names; `namechange()` returns historical names. `daily_basic.pe_ttm` is naturally point-in-time correct in Tushare. The `in_date <= date < out_date` pattern for sector lookups, with backward-fill fallback for stocks added to a database mid-panel.

**Cost-adjusted Sharpe mechanics.** Drag = turnover × round-trip cost; Sharpe degradation = sqrt(12) × drag / std. Cost adjustment is fatal for marginal strategies and only inconvenient for strong ones, because the std is unchanged by a constant subtraction. The A-share regulatory cost stack is roughly 0.113% per round-trip (印花税 0.05% sell-side + 佣金 0.025% each side + small fees 0.013% round-trip), with slippage adding ~0.10-0.30% per side depending on stock liquidity.

**The pe_ttm = close / EPS_ttm identity.** PE jitters with price even when EPS is steady. A "stability check" on pe_ttm cannot use a fixed threshold; it must back out implied EPS or apply a price-volatility-aware threshold. This was the diagnostic insight that resolved the EP validation script's misleading verdicts.

---

## Skills practiced

Vectorized pandas operations (groupby, rank, merge, rolling). Parquet I/O with pyarrow including schema inspection for cache invalidation. ThreadPoolExecutor concurrency with thread-safe rate limiting. Parametric retry-on-network-error patterns with exponential backoff. Hierarchical caching strategies (per-day, per-rebalance-date, per-stock). Schema validation for cache resumability including dtype-aware detection. Smoke-test-then-full-run discipline with verbose modes for incremental output verification. Bisect-based binary search for trading-calendar lookups. Backward-fill design pattern for handling temporal data gaps. Pure-data-manipulation pipelines (zero API calls in Stages 1, 2, 3, 5).

---

## Codebase as of handoff

```
Project_6/
├── (../tushare_client.py)                       parent dir, Tushare auth
├── (../.env)                                    parent dir, TUSHARE_TOKEN
├── data/
│   ├── trading_calendar.csv                     2,018 trading days 2018-2026
│   ├── stock_basic.csv                          5,511 currently listed names
│   ├── historical_names.csv                     34,256 PIT name records, 6,108 stocks
│   ├── weekly_rebalance_dates.csv               381 Wednesdays 2019-2026
│   ├── liquidity_panel_60d.parquet              1.83M rows, 60-day mean amount
│   ├── universe_membership_X75_Y3000.parquet    1.69M rows, N=1000 × 381 weeks
│   ├── universe_membership_X75_Y3000_diagnostic.png
│   ├── cap_drift_diagnostic.png                 mechanism A confirmed
│   ├── sw_classification.csv                    SW2021 taxonomy
│   ├── sw_membership.csv                        5,834 stock sector records
│   ├── candidate_history_panel.parquet          ~8M rows, factor pipelines read this
│   ├── daily_panel/                             2,018 per-day parquets (~700 MB)
│   ├── candidates_weekly_pit/                   381 per-date PIT candidate parquets
│   └── errors_*.log                             per-stage error logs
├── daily_panel_pull.py                          Stage 0: threading + ZSTD + float32
├── validate_pe_ttm.py                           one-off EP validation
├── stage1_with_pit_names.py                     Stage 1: PIT names via namechange
├── stage2_liquidity_panel.py                    Stage 2: 60-day liquidity
├── stage3_universe_membership.py                Stage 3: hybrid floor + bottom-1000
├── cap_drift_diagnostic.py                      verification (mechanism A confirmed)
├── stage4_sector_classification.py              Stage 4: SW2021 sector pull
├── stage5_candidate_history_panel.py            Stage 5: history panel (the fix)
└── (legacy Project 5 files, do not reference)
```

The legacy Project 5 files (`tushare_build_universe.py`, `liquidity_panel.py`, `forward_return_panel.py`, `universe_membership.py`, `universe_behaviour.py`, `validate_limit_state.py`) remain in the directory but target the old monthly panel and should not be referenced by new factor pipelines.

---

## Misconceptions corrected

**That the previous Stage 1's 6% survivorship rate was negligible.** It was not; many of those stocks were shell-value-contaminated and exactly the kind of names that would have driven the original Project 6's value-in-low-cap result. The PIT fix was the right investment.

**That the EP validation script's MIXED/INVESTIGATE verdicts indicated real point-in-time problems.** They did not. They were artifacts of unrealistic stability thresholds because pe_ttm naturally jitters with daily price moves even when EPS is steady. Manual implied-EPS back-out confirmed clean PIT behavior across all three test cases.

**That the (X=80, Y=1500) tuple from Project 5 should be transplanted.** The new panel has different statistical properties: 60-day vs 20-day window, full 2019-2026 range vs 2022-2026, weekly vs monthly rebalances. Parameters needed re-evaluation against the new distribution.

**That the late-panel cap inflation might be parameter-driven.** The cap-drift diagnostic confirmed it is market-wide cap inflation (mechanism A). The universe maintains its relative size cohort across the panel.

**That my early estimates for full-pull wall time were correct.** I underestimated Tushare's per-call response latency by ~5x (predicted 0.4s/call, actual 2-3s/call). The threading optimization was not in the original plan and was added after the smoke test revealed the gap.

---

## Habits built or reinforced

**Smoke-then-full discipline.** Every pipeline runs smoke first with verbose output; full only after smoke checks pass. This caught the survivorship issue, the EP validation script's threshold problem, and the Stage 5 sector backward-fill bug before any of them could pollute a full run.

**Asking for diagnostics rather than accepting results.** The cap-drift diagnostic and the survivorship investigation both came from noticing something unexpected and asking for a deeper test rather than proceeding past the anomaly.

**Preferring data authenticity over convenience.** "If a stock reports NaN just keep it as is, record its reason for NaN" shaped the design of Stage 2's `n_trading_days_observed` column and Stage 3's exclusion threshold. NaN is information, not a problem to be silently filled.

**Bilingual technical communication.** Chinese for market-specific concepts (印花税, 流通市值, 涨跌停板, 申万, 前复权) and English for statistical and programming concepts.

**Stopping to investigate anomalies before proceeding.** When the smoke output showed unexpected counts (the +108 candidates after PIT, the 12.3% NaN sectors, the cap drift), the right response was to diagnose before continuing rather than rationalize past it.

---

## Thesis implications

The 小盘股 thesis status at universe-rebuild close is unchanged in its claims but conditionally re-opened in its evidence. The Project 6 Multi-Factor closeout established that:

- Value (EP) has the only unambiguous long-only thesis at the headline level among single factors, BH-rejecting in the low-cap tercile.
- Low-vol BH-rejected in one cell (high-cap tercile).
- Cap-tercile structure is foundational: value lives in low-cap, low-vol lives in high-cap, mid-cap structurally null.
- Pre-stimulus z_size FMB-rejected in the multi-factor regression (the standout multi-factor finding).
- The universal regime sign-flip across factors at the 2024-09-24 PBoC stimulus event is the strongest single empirical observation in the project.

All of these results are now provisional pending re-run on the rebuilt panel. The architectural fixes mean the rebuilt panel may amplify the findings (if the original bias was destroying real signal), erase them (if the original bias was creating apparent signal), or leave them substantially unchanged (if the bias was orthogonal). Each outcome is informative.

The cost-adjustment warm-up established that segmented-strategy gross numbers reproduce, so the cost machinery is correctly calibrated. The substantive question of whether anything has alpha after costs remains the primary deliverable of the next phase.

---

## Open items

**From this conversation (rebuild-specific):**

1. The SW2021 sector data is flat (one record per stock). Historical sector reclassifications are not captured. Stage 5 handles this by backward-fill from the earliest known sector. Affects fewer than ~50 stocks in our pool but worth noting for any analysis hinging on sector reclassification timing.

2. Survivorship in delisted-and-not-in-namechange stocks. The PIT fix resolved the ST-bypass for stocks that ARE in the namechange data. Truly delisted stocks absent from both `stock_basic` and `namechange` records are absent from the candidate pool entirely. For backtesting this is acceptable; for hypothetical "would I have bought this delisted stock" analyses the panel cannot speak.

3. Cap-drift diagnostic complete and confirmed mechanism A. No action required.

**Carried forward from Project 6 Multi-Factor closeout:**

4. Cost-adjusted Sharpe analyses for value's low-cap leg and low-vol's high-cap leg. Original closeout open items, never run. Should run on rebuilt panel after factor refactor.

5. Pre-stimulus z_size FMB BH-rejection is the multi-factor finding to test first on the rebuilt panel. If it survives at 70-80% coverage, robust. If not, in-sample artifact.

6. **Code refactor: `cross_sectional_zscore` to `factor_utils.py`.** Currently lives in `composite_value_lowvol_analysis.py`. Used cross-script.

7. **Code refactor: `add_all_factors` to a new `multifactor_utils.py`.** Currently lives in `fama_macbeth.py`. Will be reused by every multi-factor analysis on the rebuilt panel.

8. **Code refactor: FMB engine (`run_one_cross_section`, `fama_macbeth`, `summarise_coefficients`) to shared module.** Same module as add_all_factors.

9. Pre/post-stimulus regime split should be a non-optional layer in every script, given the universal regime sign-flip finding.

10. Multi-test correction policy review. With multi-factor in scope, the family-of-headlines is bigger (single-factor + composite + segmented + FMB). Lock policy before re-running. Original closeout convention: Holm-Bonferroni across factor headlines, BH within within-factor robustness.

11. Cost-adjusted Sharpe for segmented strategy and FMB-implied portfolios. The 0.61 Sharpe is gross. Net of realistic A-share costs the picture changes.

12. FMP correlation matrix as standalone analysis. Was deferred from the multi-factor phase. Cheap to run on the rebuilt panel.

**Carried forward from earlier projects (still pending):**

13. Single-factor open items beyond cost-adjustment: graduating-out hypothesis test for value's high-cap null, ACF on factor IC time series, B/M robustness check.

14. Limit-hit detection utility (deferred from Project 2 Session 1, still useful for backtester in Project 7).

15. Crisis-regime validation of small-cap basket conclusions (Project 2 carry).

---

## Bridge to next session

The next conversation begins with the factor utility refactor. Phase A is the largest code-volume task: port `cross_sectional_zscore`, `add_all_factors`, and the FMB engine to read from `candidate_history_panel.parquet` instead of the old forward-return panel. This is the first 1-2 sessions.

After the refactor, single-factor re-run (Phase B) covers size, value, momentum, low-vol on the rebuilt panel. Three concrete questions to answer:

- Does the cap-tercile structure (value in low-cap, low-vol in high-cap) reproduce?
- Does pre-stimulus z_size FMB-reject at 70-80% coverage?
- What does the FMP correlation matrix show on clean data?

If results reproduce, multi-factor re-run (Phase C) follows: composite, segmented with FMB-implied weights, FMB. Then cost-adjusted Sharpe (Phase D) on whatever cells survive.

If the cap-tercile structure or the z_size finding evaporate, the conclusion is that small-cap A-share factors are noisier than the original panel suggested. That is itself useful information and the rebuild has done its job by surfacing it honestly.

Suggested opening for the next conversation: run `python stage5_candidate_history_panel.py status` to confirm the panel is intact, then begin the `factor_utils.py` refactor. The first session's deliverable is the refactored `cross_sectional_zscore` and `add_all_factors` reading from the new panel, with a smoke test confirming both produce sensible output on the first 5 rebalance dates.

If anything in the universe construction feels unsettled when the next conversation opens, address it before factor work begins. Bias in the universe propagates through every factor result and is not recoverable downstream.

---

## Suggested conversation name

`2026-04-29 — Project 6 Universe Rebuild: Stages 0-5, Cost-Adjustment Warmup, and Architectural Fixes`
