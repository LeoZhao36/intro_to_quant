# Project 5 Stage 2 Handoff: Trailing 20-day Liquidity Panel

**Completed:** 2026-04-25
**Project location:** Phase 3, Project 5 (Universe Construction), Stage 2
**Status:** Stage 2 complete. Ready for Stage 3 (hybrid floor selection and universe membership).

---

## Key takeaways

The trailing 20-day liquidity panel is built and clean. `data/liquidity_panel.csv` has 250,862 (rebalance_date, ts_code) rows across all 52 monthly rebalance dates, with 99.2% full-window observation. The architectural pattern from Stage 1 carried directly: cross-sectional `pro.daily()` per trading day, deduped across overlapping windows, ~996 calls instead of the naive 5 million.

The diagnostic plot revealed that the fixed 3000万 floor calibrated in Session 1 is regime-dependent in a way that was invisible at single-date resolution. Full-universe pass rate ranges 67% to 99.7% across the panel; bottom-1000 pass rate ranges 38.5% to 98.9%. The 2024-Q3 PBoC stimulus is visible as a step-change in trading liquidity that sustains into 2025-2026.

The right Stage 3 floor is a hybrid: a relative cut for universe-size stability across regimes, plus an absolute backstop for transactability. The pooled liquidity percentiles within the bottom-1000 (P10 = 1,524万, P25 = 2,525万, P50 = 4,535万) provide concrete anchors for the absolute parameter.

---

## Reference conversations and documents

- `2026-04-25 — Project 5 Stage 2: Liquidity Panel and Hybrid Floor Decision` (this session)
- `Project_Five_Stage_One_Handoff.md` (predecessor, Tushare rebuild and mcap correction)
- `Project_5/liquidity_panel.py` (Stage 2 production code; user renamed from initial `stage2_liquidity_panel.py`)
- `Project_5/bottom1000_liquidity_diagnostic.py` (parameterized bottom-N diagnostic)
- `Project_5/data/liquidity_panel.csv` (Stage 2 output)
- `Project_5/data/liquidity_panel_diagnostic.png` (full-universe pass rate over time)
- `Project_5/data/liquidity_panel_bottom1000_diagnostic.png` (bottom-1000 vs full overlay)
- `Project_5/data/daily_panels/` (996 cached per-trading-day amount panels)
- `Project_5/data/trading_calendar.csv` (cached SSE trading calendar 2021-12 to 2026-04)

---

## Starting point

Entered the session with Stage 1 closed at 52 candidate CSVs and the predecessor handoff specifying two pre-Stage-2 housekeeping items: a NaN-name warning to add to `tushare_build_universe.py`, and three stale baostock-era 2022 cache files to delete and re-pull.

The housekeeping went in as two patches to `tushare_build_universe.py` rather than the one in the handoff. The NaN-name warning landed between the A-share filter and the ST filter, so it counts only A-share rows with unresolvable names rather than inflating the count with discarded B-shares. A second patch added schema validation on cache load: a frozenset of expected columns checked via `pd.read_csv(path, nrows=0)` (header-only read), with stale files auto-deleted and re-pulled. The schema validation made the manual `rm` commands from the handoff unnecessary; the driver self-healed the three stale 2022 files on the next `python tushare_build_universe.py full` run.

---

## Stage 2 thesis

Same architectural principle as Stage 1: query shape should match question shape. The naive read of "for each rebalance date R, fetch trailing 20 days of amount for every stock in R's candidate set" suggests 52 × 5,000 × 20 ≈ 5M API calls. Restating the question correctly, "for each trading day in the union of the 52 trailing windows, fetch every stock's amount," gives 996 calls (1,040 naive minus 44 of overlap savings). Per-trading-day cache key captures the natural dedup across rebalance windows.

Stage 2 produces diagnostics, not filters. The `passes_3000_floor` column is a flag, not a cut. The actual inclusion decision lives in Stage 3, which keeps the floor configurable without re-pulling data. This separation made the regime-sensitivity finding usable: Stage 2 produced the panel, the bottom-1000 diagnostic read it from a different angle, and the hybrid-floor decision emerged from the panel without any data re-fetches.

---

## Codebase changes

**New files:**

- `liquidity_panel.py` (Stage 2 driver). Three named passes (`build_required_trading_days`, `pull_daily_panels`, `build_liquidity_panel`) plus diagnostic plot, smoke test, and full driver. Each pass does exactly one thing so failures isolate cleanly. Cache lives in `data/daily_panels/daily_<date>.csv` keyed by trading date. Smoke mode runs the pipeline for a single rebalance date without overwriting full output.

- `bottom1000_liquidity_diagnostic.py`. Parameterized on N (default 1000). Loads `liquidity_panel.csv`, takes bottom-N by circ_mv_yi from each candidate set, left-joins to the panel (stocks missing from panel treated as not passing the floor), produces two-panel plot: pass rate over time with full-universe overlay, plus pooled distribution within bottom-N annotated with floor and quartile lines.

**Modified files:**

- `tushare_build_universe.py`. Two patches: NaN-name warning between A-share and ST filters; cache schema validation via `EXPECTED_CANDIDATE_COLUMNS` frozenset and header-only read. The validation deletes stale files and falls through to pull rather than raising, so the full driver self-heals.

**Network resilience pattern added during the run:**

`liquidity_panel.py` initially had no retry layer because Stage 1's 104 calls had completed clean. The first full Stage 2 run hit a `ReadTimeout` on call ~412 of 996, which is the expected behavior at this call volume (probability of at least one timeout ≈ 1 - (1-p)^N, large for N around 1,000 even at p = 0.1%). The fix: a `_retry_on_network_error` helper with exponential backoff (2s, 4s, 8s) applied to the `pro.daily()` call. The retry layer activated exactly once during the full run on 2023-10-25, recovered on the first backoff. Pattern carries forward to any future batch loop above ~100 calls.

---

## Stage 2 output

`data/liquidity_panel.csv`: 250,862 rows. Columns:

- `rebalance_date` (string, YYYY-MM-DD)
- `ts_code` (string, Tushare format)
- `mean_amount_wan` (float, mean trailing-20-day amount in 万 RMB; window is [R-19, R] inclusive)
- `n_trading_days_observed` (int, days the stock actually traded in the window; suspended days are absent because Tushare's `daily` omits non-trading rows)
- `passes_3000_floor` (boolean diagnostic; not a filter)

Headline numbers:
- 99.2% full-window observation (248,824 of 250,862)
- 87.4% pass at 3000万 across full universe
- Per-rebalance-date stocks range 4,430 (2022-01-17) to 5,008 (2026-04-15)

Diagnostic plots:
- `liquidity_panel_diagnostic.png`: full-universe pass rate over time (top panel) plus pooled distribution with 3000万 floor line (bottom).
- `liquidity_panel_bottom1000_diagnostic.png`: bottom-1000 vs full overlay (top), pooled bottom-1000 distribution with floor and percentile lines (bottom).

Total Stage 2 wall time: 28.2 minutes. Most of that was the ~889 fresh API calls; cached re-runs complete in under a minute.

---

## Conceptual ground

**Cross-sectional query shape is now the reflexive default.** Whenever a future loop iterates per-stock per-date, the first question to ask is whether the data source has a single endpoint that returns the cross-section. If yes, use it. The Stage 1 → Stage 2 carry-forward is that this is not a one-time architectural insight but a class of decision that comes up at every data-access layer.

**Network resilience scales with call count.** At ~100 calls, transient timeouts are improbable enough to ignore. At ~1000, they are nearly certain. Retry-with-exponential-backoff is the standard pattern from this point onward, not optional. The lambda + helper pattern (`_retry_on_network_error(lambda: pro.daily(...))`) keeps the call site readable while wrapping any externally-triggered call.

**A "fixed" rule can be silently regime-dependent.** The 3000万 floor looks like a fixed filter, but the empirical universe it produces shrinks and grows with market liquidity. Universe-size stability and absolute-tradability are two different properties; a single rule cannot guarantee both. This is the conceptual hinge for the hybrid-floor decision in Stage 3.

**Pooled percentiles are the right anchors for setting absolute floors.** P10 = 1,524万 means 10% of bottom-1000 (date, stock) observations trade below that. An absolute floor below P10 is essentially inactive; one above P50 is too aggressive. The defensible range for an absolute backstop is between P10 and P25 in this dataset.

**The 2024-Q3 PBoC stimulus is empirically visible in trading liquidity.** Pass rates step up sharply between September and November 2024 and sustain elevated through 2026. Any factor research that compares pre- and post-stimulus periods needs to account for this regime shift, either through the universe construction (hybrid floor) or through downstream regime conditioning.

---

## Misconceptions corrected

**"95.5% smoke-test pass rate suggests the floor is too loose."** Wrong. The full candidate universe is dominated by mid- and large-caps that trade orders of magnitude above the floor. The floor's actual operating point is the bottom-1000 by market cap, where the bite is materially harder. The 50-80% expectation I gave at smoke-test time was the expected bottom-1000 pass rate misapplied to the full universe. The correction came from the bottom-1000 diagnostic, which showed P25-to-P75 of 56-84%.

**"An orphan candidates_2024-12-31.csv from Session 1's smoke test is harmless."** Wrong. It was being picked up by the bottom-1000 diagnostic's `glob("candidates_*.csv")` pattern, contributing 1,000 unmatched rows (no panel entry for 2024-12-31 because it was not a rebalance date) and producing a misleading 0.0% min pass rate. Output filename patterns are an implicit contract; orphans break the contract silently. Cleanup was one `rm`; the lesson is to keep `data/candidates/` containing only files corresponding to actual rebalance dates.

**"The relative-floor and absolute-floor decisions are separable."** Misleading. They look like two independent design choices but they jointly determine universe size and transactability. The relative cut alone fails on transactability in stress periods; the absolute cut alone fails on regime stability. The hybrid is the only design that can satisfy both, and the parameter pair (X, Y) has to be chosen jointly rather than sequentially.

---

## Habits built or reinforced

**Magnitude sanity checks on first ingest.** The print-min-median-max-on-first-uncached-pull pattern in `pull_daily_panels` caught nothing this run because the unit was correct, but the cost was zero and the value-when-it-fires is large. Pattern carries forward to any new data source.

**Schema validation on cache load.** The `EXPECTED_CANDIDATE_COLUMNS` frozenset check is five lines that eliminated a class of cache-staleness bugs permanently. Apply the same pattern to `liquidity_panel.csv` and `daily_panels/*.csv` consumers in Stage 3.

**Smoke-test-then-full pattern.** Stage 2 ran smoke on 2024-12-31 first, the bottom-1000 diagnostic ran, both passed sanity checks before the full 28-minute run. This becomes the standard for any pipeline whose full execution costs more than a couple of minutes.

**Diagnostic-first, decision-second separation.** Stage 2 deliberately did not bake the floor decision into the panel. The flag `passes_3000_floor` is a diagnostic column, not a filter. This let the bottom-1000 analysis surface a regime-sensitivity issue that would have been invisible if the panel had been pre-filtered. Stage 3 will receive the same treatment: produce universe-membership flags under multiple (X, Y) settings, decide between them empirically.

**Reading actual diagnostic output before forming conclusions.** Initial intuition at Stage 1 was that the 3000万 floor was "doing the right thing" because it produced a sensible-looking single-date result. The bottom-1000 diagnostic across 52 dates corrected this: the floor was doing very different things at different times, and the right floor design is hybrid rather than fixed. The Session 1 calibration was not wrong, just incomplete.

---

## Open items carried forward

**Stage 3 hybrid floor selection (immediate next step).** Three (X, Y) candidates identified:

- (X = 80%, Y = 1,500万): trust the relative rule, Y as backstop only
- (X = 80%, Y = 2,500万): same target size, more aggressive safety net
- (X = 70%, Y = 2,000万): tighter universe with moderate threshold

Stage 3 deliverable: `stage3_universe_membership.py` parameterized on (X, Y), produces `data/universe_membership_X{X}_Y{Y}.csv` with columns (rebalance_date, ts_code, in_universe, mean_amount_wan, circ_mv_yi, rank_by_mcap), plus diagnostic plot showing universe size per rebalance date and inter-date turnover. Run against all three candidates, compare empirically.

**Point-in-time name resolution still deferred.** Current ST filter uses present-day names from `pro.stock_basic(list_status='L')`. NaN-name warning is now in place to surface the rate per date. Proper fix uses `pro.namechange()` to resolve names as-of-date. Should land at Stage 3 or in early Project 6 before factor work begins.

**Liquidity floor regime sensitivity now quantified.** Bottom-1000 pass rate IQR is 56% to 84%, range is 38.5% to 98.9%. The hybrid floor is the response. After Stage 3 lands, this is closed.

**Carryforwards from Project 1 still unresolved:**
- Limit-hit detection utility (deferred from Project 2 Session 1).
- Crisis-regime validation of small-cap basket conclusions.
- `project1_utils.py` consolidation of helper functions.

These do not block Stage 3 but should be addressed before deep factor work in Project 6.

**Pending commits.** All Stage 2 work is uncommitted; user explicitly chose to batch commits at end of session. Suggested groupings:

1. `Stage 1: NaN-name warning and cache schema validation` — patches to `tushare_build_universe.py` plus the resulting full-panel re-pull
2. `Stage 2: liquidity panel build with retry-on-timeout` — `liquidity_panel.py` plus its outputs (`liquidity_panel.csv`, `daily_panels/`, `liquidity_panel_diagnostic.png`)
3. `Stage 2: bottom-1000 diagnostic and regime sensitivity finding` — `bottom1000_liquidity_diagnostic.py` plus its plot output

Commit at the end of the session with the three messages above, in that order.

---

## Bridge to Stage 3

**Design correction noted at session end.** The implementation outline below takes bottom-1000 by mcap first, then applies the hybrid liquidity rule. That ordering reproduces the variable-universe-size problem Stage 2 was meant to address: in a stress regime where many of the 1,000 smallest stocks fail the rule, the universe collapses below 1,000. The corrected ordering reverses this: apply a regime-stable liquidity rule (rank-based by mean amount within the full ~5,000-stock candidate set, with an absolute backstop Y) to the full set first, then take the 1,000 smallest by circ_mv_yi from the survivors. Universe size is then exactly 1,000 every month, every stock passes the liquidity threshold, and the size sort happens last so the universe stays meaningfully small-cap. The trade-off is mild drift in the cap distribution across regimes (slightly larger mean cap in stress periods, slightly smaller in good liquidity) in exchange for stable N, which is the right trade for cross-sectional factor research where statistical power scales with consistent universe size. This corrected shape also aligns with standard practice in Liu-Stambaugh-Yuan and Li-Rao 2022, both of which apply contamination or tradeability filters to the full universe before sorting on size. Stage 3 should encode this corrected order. The original implementation outline below documents the superseded design and is preserved for context.

Stage 3 is the third and final piece of universe-construction infrastructure. It joins Stage 1's per-date candidate sets with Stage 2's liquidity panel, applies the hybrid floor, and produces the universe membership table that every downstream factor study reads.

Implementation outline. The script takes two parameters X and Y. For each rebalance date R: load candidates_R.csv, take the bottom 1000 by circ_mv_yi, left-join to liquidity_panel.csv on (R, ts_code), apply the hybrid rule (rank within bottom-1000 by mean_amount_wan, top X% AND mean_amount_wan ≥ Y), output one row per stock with the membership flag. Concat across dates, write `universe_membership_X{X}_Y{Y}.csv`.

Diagnostic plot. Two panels. Top: universe size per rebalance date (52 points), with horizontal reference lines at the X% target. Bottom: inter-date turnover (% of universe stocks that exit between consecutive rebalance dates). High turnover means the membership boundary is unstable, which is bad for factor research consistency.

Decision criterion. Run all three (X, Y) candidates. The empirical question is which produces the most stable universe size across regimes (small variance around the X% target) without sacrificing turnover stability (low inter-date churn).

Suggested runtime budget: 60 minutes. Stage 3 is mostly orchestration and diagnostic interpretation; the heavy data work is already done.

After Stage 3 lands, Projects 6 onward consume `universe_membership.csv` (the chosen-(X, Y) version, renamed to canonical) as the reference universe for factor research.

Suggested next conversation name: `2026-04-26 — Project 5 Stage 3: Hybrid Floor Selection and Universe Membership`.
