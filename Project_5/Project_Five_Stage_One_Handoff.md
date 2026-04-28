# Project 5 Stage 1 Handoff: Tushare Rebuild and Mcap Correction

**Completed:** 2026-04-25
**Project location:** Phase 3, Project 5 (Universe Construction), Stage 1 rebuild
**Status:** Stage 1 complete on Tushare. Ready for Stage 2 (trailing 20-day liquidity filter).

---

## Reference conversations and documents

- `2026-04-25 — Project 5 Stage 1: Tushare Rebuild and Mcap Methodology Correction` (this session)
- `Project_Five_Session_One_Handoff.md` (predecessor, baostock single-date prototype on 2024-12-31)
- `Project_5/tushare_build_universe.py` (production Stage 1 code)
- `Project_5/tushare_client.py` (Tushare Pro auth wrapper)
- `Project_5/data/candidates/candidates_*.csv` (Stage 1 output, 52 monthly snapshots)
- `Project_5/_archive_baostock_pipeline/` (deprecated baostock infrastructure preserved for reference)
- `data/diagnose_mcap_disagreement.py` (cross-source diagnostic script)

---

## Starting point

Entered the session with Project 5 Session 1 closed: a working baostock pipeline that produced a single-date universe for 2024-12-31 in 15-25 minutes, plus a 20-day liquidity diagnostic that calibrated a 3000万 RMB/day floor for the bottom-1000 universe. Session 2 had begun extending to 52 monthly dates with 8-thread baostock concurrency, projecting roughly 24 hours of total runtime. That projection turned the pipeline from "slow but acceptable" into "iteration-blocking," which is what triggered the rebuild.

The Tushare Pro student-tier account had just been approved with sufficient 积分 for daily, daily_basic, stock_basic, and trade_cal. No prior Project 5 code used Tushare; baostock had been the sole data source.

The session also covered first-time setup of credential management and version control: `.env` for the Tushare token, project-root `.gitignore`, and a private GitHub repository with a regular commit habit established at natural milestones.

---

## Stage 1 thesis

The runtime was a symptom, not the disease. Architectural diagnosis: baostock's interface is shaped around per-stock-time-series queries, but Project 5's question is per-date-cross-section. Mismatched interface shape produces both the slow runtime and a more subtle methodological problem (see Misconceptions below). Tushare Pro's `daily_basic` endpoint returns the entire A-share universe for one date in a single call, matching the question shape directly. Switching data sources also forced an explicit verification that the new numbers match the old ones, which surfaced a methodological issue in the old derivation that had not been visible before.

---

## Codebase changes

New files created this session:

- `Project_5/tushare_client.py`: thin auth wrapper that loads `TUSHARE_TOKEN` from project-root `.env` and exposes a module-level `pro` singleton. Imported by every Tushare-using script.
- `Project_5/tushare_build_universe.py`: replaces baostock's threaded fetch with two Tushare calls per date (`daily_basic` for valuation/cap fields plus `daily` for OHLCV). Includes smoke test, full-pipeline driver, rebalance date generation via `pro.trade_cal()`.
- Project-root `.env` and `.gitignore`. The token is gitignored, verified with `git check-ignore -v .env`.

Archived (moved to `Project_5/_archive_baostock_pipeline/`):

- `diag_concurrency.py`: was tuning baostock thread counts and pacing.
- `monitor_stage1.py`: was the live ETA monitor for the 24-hour run.

Untouched (Session 1 artifacts, still valid as historical record):

- `build_universe.py`: Session 1 single-date prototype.
- `liquidity_diagnostic.py`: liquidity floor calibration.
- `plot_mcap_distribution.py`: distribution plots.
- `data/kdata_2024-12-31.csv`: frozen Session 1 cache, still readable by the analysis files above.

Repository: private GitHub repo set up, four commits during the session at natural checkpoints (env setup, code rewrite before run, after Stage 1 completion, after diagnostic findings).

---

## Stage 1 output

52 candidate CSV files in `Project_5/data/candidates/`, one per monthly rebalance date from 2022-01-17 through 2026-04-15. Each file contains every A-share equity tradeable on that date with columns: `ts_code, name, close, vol, amount, turnover_rate, pe, pe_ttm, pb, ps, total_share, float_share, total_mv, circ_mv, circ_mv_yi`.

Universe size grows from 4410 stocks (Jan 2022) to 5008 (Apr 2026), tracking genuine A-share listing growth over the period. Filter chain stable across all dates: roughly 4-5% drop for non-equity codes (北交所, B-shares, ETFs, indexes), 3-4% for ST and risk-warned stocks, 0% for the volume/mcap edge-case filter (Tushare's `daily` endpoint already excludes suspended stocks).

Total runtime: 2.8 minutes for the full 52-date pipeline, vs the ~24-hour projection under baostock. Roughly 500x speedup, achieved by the architectural shift, not by tuning concurrency.

---

## Conceptual ground

**Interface shape should match question shape.** The takeaway to carry into every future infrastructure decision. When you find yourself writing a loop iterating over N entities to ask the same question of each, stop and ask whether the data source has a single endpoint that answers the question across the whole universe at once. If yes, use that endpoint. If no, the right move is usually to find a different data source rather than to optimize the loop. The 500x speedup came from fixing this mismatch, not from clever code.

**Adjustment-aware market cap.** Stock prices in China are reported two ways. 不复权 (unadjusted) is the actual exchange-tape price on the day. 前复权 (forward-adjusted) is that price retroactively rescaled to account for stock splits, dividends, and share issuances that happened later, so a price chart looks smooth across corporate actions. Adjusted prices are correct for return computation. Unadjusted prices are correct for market cap on a specific date. Combining adjusted prices with current share counts produces a methodologically inconsistent number that is neither the historical mcap nor the present mcap. Tushare's `circ_mv` field reports market cap directly from exchange records, sidestepping the issue.

**Fast iteration changes the research that's possible.** A 2.8-minute Stage 1 means re-running with a different ST rule, adding a new column, or extending the date range backward becomes a "try and see" decision instead of a "decide whether it's worth a day" gating decision. This is not a marginal improvement; it changes which questions are practical.

---

## Misconceptions corrected

**"baostock and Tushare are interchangeable as long as we filter the same way."** Wrong. The Session 1 pipeline derived 流通市值 as `close × volume / (turn / 100)` using forward-adjusted prices but current share counts. This produced correct numbers for stocks with no recent corporate actions but very wrong numbers for stocks like BYD (002594) that had recent stock splits or large dividends. Cross-source diagnostic on 2024-12-31 showed median disagreement of 0.7% but a tail with 200%+ disagreements concentrated on stocks with recent corporate actions. The new pipeline uses Tushare's directly-reported `circ_mv`, which avoids the issue.

**"The mcap derivation problem only affects extreme outliers."** Partially true. Median impact is small (under 1%), but the bottom-1000 universe in Session 1 was constructed by sorting on the affected number, so boundary cases near the cutoff may have been incorrectly included or excluded. The 3000万 RMB liquidity floor itself is unaffected because it uses 成交额 (directly reported), not derived mcap.

**"Predicting the cause of a disagreement before running the diagnostic is unnecessary."** The session deliberately ran a hypothesis-prediction step before opening the diagnostic output. The prediction (low-turnover stocks dominate the disagreement due to rounding amplification in the baostock formula) was wrong. The actual mechanism (adjusted vs unadjusted prices) was a different category of problem entirely. Without the prediction, the visible "low-turnover stocks have more disagreement" pattern in the bucket table would have been pattern-matched into the wrong conclusion. The discipline of writing predictions before looking at output saved a wrong diagnosis.

---

## Habits built or reinforced

**Verification before action on infrastructure changes.** When swapping data sources, the first move was a smoke test against the existing trusted output, not a celebration of the new one being faster. The smoke test surfaced the adjustment issue that would otherwise have propagated silently into all downstream factor work.

**Hypothesis enumeration before drilling into data.** Before running the disagreement diagnostic, four candidate mechanisms were written down (free-float definition, rounding amplification, corporate action timing, structural specials). The bucket table and worst-offender table were chosen specifically to distinguish these, not to "see what's interesting in the data."

**Architectural hygiene over local optimization.** The session resisted the path of optimizing baostock further (more threads, better pacing, smarter caching) in favor of stepping back to the underlying interface mismatch. The user's pushback against creating "parallel new files" alongside the existing universe_construction.py was the right instinct and was incorporated into the actual edit plan.

**Commit discipline at natural boundaries.** Multiple commits during the session, each capturing a stable checkpoint with a meaningful message. This discipline becomes the recovery path if a future change breaks something. Tutor should continue prompting for commits at natural boundaries in subsequent sessions.

**Read existing code before proposing changes.** Initial sessions in this rebuild proposed creating new files alongside existing ones; user pushback led to actually reading the existing scripts (`universe_construction.py`, `liquidity_diagnostic.py`, `monitor_stage1.py`) before deciding what to keep, edit, or archive. The right modification turned out to be smaller and more surgical than the initial proposal.

---

## Open items carried forward

**Stale baostock cache cleanup (do this first in next session).** The first three `candidates_2022-*.csv` files (Jan, Feb, Mar 2022) are leftover artifacts from the abandoned baostock Stage 2 attempt. They have a 9-column baostock schema rather than the 20-column Tushare schema. The Stage 1 driver loaded them as cache hits without detecting the mismatch. The fix is one terminal sequence:

```bash
cd Project_5
rm data/candidates/candidates_2022-01-17.csv
rm data/candidates/candidates_2022-02-15.csv
rm data/candidates/candidates_2022-03-15.csv
python tushare_build_universe.py full
```

The driver will skip the 49 already-good files and re-pull only the three. Verify the column count matches before doing any Stage 2 work.

**Point-in-time name resolution.** Current ST filter uses the `name` field from `pro.stock_basic(list_status='L')`, which gives present-day names. This means: stocks delisted between rebalance date and today have NaN names and bypass the filter (~0.04% of universe per date, observed in 2024-12-16 spot-check), and stocks that were ST on the rebalance date but are normal now would incorrectly pass the filter. Bias is small but real. Proper fix uses `pro.namechange()` to resolve names as-of date. Deferred to Stage 3 (final universe construction). Add a logged warning to Stage 1's driver in the next session so the count of unknown-name rows is visible per date going forward.

**Liquidity floor calibration validity across the panel.** The 3000万 RMB/day floor was calibrated on the 2024-12-16 cross-section in Session 1's `liquidity_diagnostic.py`. The 2022-2026 sample includes regimes with materially different liquidity profiles (the late-2024 stimulus rally, periods of low retail activity). Stage 2 should examine whether the floor is robust across the full date range, whether it should be re-calibrated per regime, or whether a relative threshold (e.g., bottom 50% of universe by liquidity) would be more defensible than a fixed 3000万 number.

**Mcap correction implications for Session 1 outputs.** Session 1 produced `data/universe_bottom1000_2024-12-31.csv` using the now-known-incorrect derivation. The downstream Session 1 analyses (`liquidity_diagnostic.py`, `plot_mcap_distribution.py`) read this file and are not invalidated, but their boundary conclusions about exactly which stocks fell into the bottom 1000 are not reliable. Stage 3 should regenerate the bottom-1000 universe using the corrected pipeline and document any membership changes.

**Carryforwards from Project 1 still unresolved:**
- Limit-hit detection utility (deferred from Project 2 Session 1, still not built).
- Crisis-regime validation of small-cap basket conclusions.
- `project1_utils.py` consolidation of helper functions.

These do not block Stage 2 but should be addressed before deep factor work in Project 6.

---

## Bridge to Stage 2

Stage 2 applies a trailing 20-day liquidity filter to each candidate set, using the 3000万 RMB/day floor as a starting hypothesis. The architectural pattern from Stage 1 carries forward directly: pull cross-sectionally per trading day, never per stock per date.

For each of the 52 rebalance dates, Stage 2 needs the trailing 20 trading days of `amount` (成交额) for every stock in that date's candidate set. Naively this would be 52 × 20 × ~5000 ≈ 5 million API calls. Architecturally correct: 52 × 20 = 1040 cross-sectional `pro.daily()` calls, each returning all stocks for one trading day. At Tushare's basic rate limit (~500 calls/min), Stage 2 should complete in 3-5 minutes wall time.

Implementation notes for the next session:

1. The 1040-call set has minimal overlap between adjacent rebalance windows (monthly rebalance ≈ 22 trading days apart, 20-day trailing window). Per-trading-day caching on disk avoids re-pulling on partial reruns. Cache key should be the trading date, not the rebalance date.

2. Output schema: one row per (rebalance_date, ts_code) with columns `mean_amount_wan` (mean 成交额 over the trailing 20 days, in 万 RMB), `n_trading_days_observed` (some stocks suspend mid-window), and `passes_3000_floor` (boolean diagnostic).

3. The 3000万 floor decision belongs at Stage 3, not Stage 2. Stage 2 produces the diagnostic numbers; Stage 3 makes the inclusion decision. This separation lets Stage 3 experiment with alternative floors without re-pulling data.

4. Add the NaN-name warning to `tushare_build_universe.py` first thing in the next session, before any Stage 2 work, so the survivorship bias remains visible on every run.

5. Clean up the three stale baostock-era cached files before doing anything else.

Stage 2 deliverable: a `stage2_liquidity_panel.py` script that reads the candidate CSVs, fetches per-day amount panels, computes trailing 20-day mean amount per (date, ts_code), writes `data/liquidity_panel.csv`, and produces a diagnostic plot showing the liquidity-floor distribution across the panel (analog to Session 1's `liquidity_diagnostic_2024-12-31.png` but extended to all 52 dates).

Suggested runtime budget for Stage 2: 90 minutes. Most of that is on understanding the trailing-window mechanics and inspecting the diagnostic plot, not on the API calls themselves.

After Stage 2, Stage 3 (final universe construction) is the third and final piece of universe-building infrastructure. It joins Stage 1's candidate sets with Stage 2's liquidity panel, applies the floor and the bottom-1000 sort, and outputs `data/universe_membership.csv` with columns `(date, ts_code, in_universe, circ_mv_yi, mean_amount_wan, rank_by_mcap)`. This is the file every downstream factor research session in Projects 6 onward will read.

Suggested name for the next conversation: `2026-04-26 — Project 5 Stage 2: Trailing 20-day Liquidity Panel`.
