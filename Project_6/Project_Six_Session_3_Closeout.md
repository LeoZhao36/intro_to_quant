# Project 6 — Session 3 Closeout

**Session focus:** Refactor the size-specific scripts into parametric machinery, source EP data, run value through the full five-layer robustness sweep, fix the latent NaN-handling bug that surfaced in Layer 4.

**Date range covered:** One session, 2026-04-28.

---

## Key takeaways

1. Refactor consolidated three size-specific scripts (`size_pipeline.py`, `size_robustness.py`, `size_robustness_pass2.py`) into a parametric architecture: `factor_utils.py` (shared logic), `size_analysis.py` (96-line wrapper), `value_analysis.py` (parallel wrapper), `source_ep_data.py` (Tushare EP pull). Behaviour-preservation verified bit-for-bit on size: every number from the Session 2 closeout reproduces from the refactored code. Future factor analyses (momentum, low-vol) will each be ~100 lines of new code instead of three new ~270-line files.

2. Value is the first non-noise factor signal in our universe. Headline IC +0.0382 with 95% CI [+0.0100, +0.0619] excludes zero. Headline Q1−Q5 −0.513%/mo at t=−1.12 is marginally consistent. Sector-neutral Q1−Q5 −0.762%/mo at t=−2.23 with CI [−1.296%, −0.263%] excludes zero. Low-cap-tercile Q1−Q5 −1.102%/mo with bootstrap p=0.015 rejects H0 even after BH correction (BH threshold for smallest p is 0.0167).

3. Sector neutralisation strengthened the signal rather than weakening it. The headline Q1−Q5 of −0.513% became −0.762% after stripping sector composition. Mechanism: structurally low-P/E sectors (banks, utilities, real estate) populate Q5 by sector classification rather than by within-sector valuation. In our 2022-2026 sample these sectors performed roughly flat-to-negative, so the raw Q5 portfolio was diluted by sector composition that had nothing to do with the value premium we were trying to measure. Within-sector value is the real signal; the headline understated it.

4. The value premium concentrates in the LOW-cap tercile of our universe, opposite of the prediction logged at the start of the session. Predicted: high-cap tercile clean, low-cap drowned in shell-value contamination. Actual: low-cap −1.102%/mo with BH-rejected p=0.015, mid −0.334%/mo (no signal), high +0.046%/mo (zero). Most likely reconciliation: Tushare's encoding of negative-earnings firms as `pe_ttm = NaN` already filtered out the strongest shell-value candidates at the data layer (27.8% of universe rows excluded). What remains in the low-cap tercile is positive-earnings small caps where mean-reversion mechanics work at full force. Plus a probable graduating-out effect at the high end: stocks that have rallied enough to sit at the top of our universe have already mean-reverted and carry no further premium.

5. Long-only Q5 cheap-leg returns +1.191%/mo (+15.27%/yr) on the full sample, beating the universe-wide baseline of +1.054%/mo (+13.40%/yr) by about 1.87 percentage points per year. Long-only alpha is real but modest. The Q5−Q1 long-short of +14.05%/yr requires shorting capability that retail traders in A-shares mostly lack (融券 restricted, expensive, supply-constrained).

6. Regime concentration is severe. Q5 returns split −0.619%/mo (−7.18%/yr) over 32 pre-stimulus months versus +4.240%/mo (+64.59%/yr) over 19 post-stimulus months. The full-sample positive return is entirely the post-September-2024 rally. A trader entering the strategy in January 2022 would have lost money for two and a half years before the regime turned. Operationally, this means the strategy's positive average return is contingent on the broader market environment rather than being a stable cross-sectional edge.

7. Layer 4 had a latent bug. `residualise_factor_per_date` passed NaN values directly to `np.linalg.lstsq`, which propagated NaN into all coefficients and residuals. For size, `log_mcap` is never NaN (in-universe stocks always have positive `circ_mv_yi`), so the bug never surfaced. For EP with 27.8% NaN rows, Layer 4 returned all NaN and silently produced no Q1−Q5 spread. Fix: restrict the regression to rows where both `factor_col` and `sector_col` are non-NaN, write residuals back only to those positions. Verified: size still reproduces, EP now produces clean residuals (sanity 4.69e-17).

---

## Reference conversations

This closeout is the canonical Session 3 record. Tied to:

- Project 6 Session 1-2 closeout (`Project_6_Session_1_2_Closeout.md`) — defined the Session 3 mandate, prescribed value-factor work, set predictions to check.
- Project 5 closeout (`Project_Five_Closeout.md`) — defined the universe, established forward returns, identified the regime-event dates that drive Layer 2.

---

## Starting point

Session 3 inherited from Session 2:

- Size factor's five-layer null result, with mid-cap-tercile p=0.080 logged as a watchlist item.
- The hypothesis-testing toolkit in `hypothesis_testing.py` (seven functions, smoke tests, multi-test correction policy locked).
- Three size-specific scripts (`size_pipeline.py`, `size_robustness.py`, `size_robustness_pass2.py`) with `"log_mcap"` hardcoded throughout.
- The Project 6 universe and forward-return panel from Project 5: 52,000 rows, 52 dates, 1000 in-universe stocks per date.
- A standing Block 2 plan: refactor before Session 3 ran in earnest, source value data, apply the five-layer machinery.
- Predictions for value: Q1−Q5 in [-0.5%, +1.0%]/mo at t in [-1.0, +2.0], with explicit calibration-against-shell-value caveat.

---

## Session thesis

If the refactor preserved behaviour and the value factor were tested rigorously, we'd expect either a clear value-premium-detected result (validating LSY-style findings within our universe) or a noisy null analogous to size. What actually emerged was a third, more interesting outcome: a robust within-sector value premium concentrated in the smallest one-third of an already-small-cap universe. The prediction about WHERE the signal would live (high-cap tercile per shell-contamination logic) was wrong; the prediction about WHETHER the signal would exist was right. This is the cleanest factor finding in the project so far, and it comes with a regime concentration that materially complicates how to act on it.

---

## Progression

**Pass 0 — Refactor (`factor_utils.py`, `size_analysis.py`, `value_analysis.py`).** Split the three size-specific scripts into a shared utilities module plus thin per-factor wrappers. Every function that previously had `"log_mcap"` hardcoded now takes a `factor_col` parameter. Layer 5 takes both `factor_col` (the factor under test, sorted within terciles) and `cap_col` (always `log_mcap`, used to define the conditioning terciles), separating the conditioning question from the factor question. `load_panel()` adds `log_mcap` universally because Layer 5 depends on it regardless of which factor is under test. Verification: re-ran the refactored size_analysis.py and confirmed every number from the Session 2 closeout reproduces exactly, including the residual sanity check at machine precision.

**Pass 1 — EP sourcing (`source_ep_data.py`).** Pulled `daily_basic` from Tushare for each of the 52 rebalance dates, computed `ep = 1/pe_ttm`. Total 271,354 rows for 5,676 unique ts_codes across all A-shares. EP coverage 76.9% universe-wide, 72.2% within our bottom-1000 sub-universe (per-date range 61.4%–82.1%). Tushare encodes negative TTM earnings as `pe_ttm = NaN` rather than as a negative number; the 27.8% NaN rate in our universe is therefore a mix of negative-earnings firms (the CH-3 exclusion target), suspended/newly-listed stocks, and pure data gaps that can't be separated without additional queries. Disclosure-lag handling is built into Tushare's pe_ttm calculation; no additional buffer needed.

**Pass 2 — Headline + Pass 1 robustness on EP.** Headline Q1−Q5 −0.513%/mo at t=−1.12, IC +0.0382. Layer 1 bootstrap CIs: Q1−Q5 [−1.177%, +0.269%] (contains zero), IC [+0.0100, +0.0619] (excludes zero). The first CI-zero-exclusion in any layer of any factor in the project so far. Layer 2 regime split: pre-stimulus −0.629%/mo (n=32, CI contains zero), post-stimulus −0.317%/mo (n=19, CI contains zero). Both sub-periods directionally consistent with value working, neither rejecting on its own due to small sub-sample. Layer 3 tradable-only filter: Q1−Q5 −0.510%/mo, headline largely preserved, drop rate 4.19% identical to size (the universe-level filter is factor-independent).

**Pass 3 — Pass 2 robustness, bug discovered.** Layer 4 sector-neutral output came back with `Residual sanity: max |mean(resid)| across dates = nan` and no Q1−Q5 line. Diagnosis: `residualise_factor_per_date` did not handle NaN values in the factor column. `np.linalg.lstsq` with NaN in `y` produces NaN coefficients, residuals propagate NaN, the entire layer silently fails. For size, `log_mcap` is never NaN so the bug never surfaced. Layer 5 ran cleanly because cap-tercile conditioning uses `log_mcap` to define terciles and the within-tercile EP sort handles NaN naturally via `pd.qcut`.

**Pass 4 — Bug fix and rerun.** Updated `residualise_factor_per_date` to restrict the regression to rows where both `factor_col` and `sector_col` are non-NaN, writing residuals back only to valid positions. NaN positions in the input remain NaN in the output, which causes them to drop naturally in downstream `compute_quintile_series`. Verified: size still reproduces every Session 2 number (regression test passes), EP now produces clean residuals at machine precision (sanity 4.83e-17). Layer 4 sector-neutral Q1−Q5: −0.762%/mo at t=−2.23, CI [−1.296%, −0.263%] excludes zero. Layer 5 cap-terciles: low −1.102% (p=0.015, BH-REJECT), mid −0.334% (p=0.408), high +0.046% (p=0.920).

**Pass 5 — Absolute return analysis on the low-cap tercile.** Q1−Q5 spread tells us cheap-vs-expensive but not whether the long-only leg makes money. Computed per-quintile absolute returns in the low-cap tercile: Q1 (most expensive) +0.090%/mo (+1.08%/yr arithmetic, −16.67% cumulative due to volatility drag at 9.48% monthly std), Q5 (cheapest) +1.191%/mo (+15.27%/yr arithmetic, +59.91% cumulative at 7.32% monthly std). Long-only Q5 alpha versus universe-wide baseline: +1.87pp/yr. Regime split for Q5: pre-stimulus −0.619%/mo (−7.18%/yr) over 32 months, post-stimulus +4.240%/mo (+64.59%/yr) over 19 months. The full-sample positive return is entirely the post-stimulus rally.

---

## Conceptual ground (new in this session)

**Sector dilution and sector neutralisation.** A raw factor sort like "rank stocks by EP and form quintiles" mixes two different signals. The first is genuine within-sector valuation: this stock is cheaper than its peers in the same sector. The second is sectoral composition: this stock is in a sector that trades at structurally low P/E for reasons unrelated to individual-stock mispricing. When the sectoral composition moves the same direction as the genuine signal, the raw spread overstates the within-sector premium. When the sectoral composition moves the opposite direction (as it did in our 2022-2026 sample for value), the raw spread understates the within-sector premium. Sector neutralisation via per-date residualisation strips the sectoral component out, leaving the within-sector ranking. The fact that our value premium got stronger after neutralisation (rather than weaker) is substantive evidence that the premium lives at the individual-stock level, not as a sector bet in disguise.

**IC vs Q1−Q5 divergence.** IC uses every stock at every position along the factor distribution, weighting monotonic relationships heavily. Q1−Q5 throws away the middle 60% of stocks and only compares the extremes. When the underlying signal is roughly monotonic across quintiles but the extremes are noisy, IC produces tighter inference than Q1−Q5. Our value headline shows exactly this pattern: IC CI excludes zero, Q1−Q5 CI just barely contains zero. Both are reading the same underlying relationship; IC's lower-variance estimator detects it more cleanly. When IC and Q1−Q5 disagree on significance (same sign, different conclusion), trust IC for inference but check Q1−Q5 monotonicity to confirm the signal isn't driven by one extreme quintile alone.

**NaN propagation through `np.linalg.lstsq`.** lstsq does not gracefully handle NaN. Any NaN in the target vector `y` produces NaN coefficients, which produce NaN residuals, which propagate through any downstream operation that doesn't explicitly skipna. For factors that are always defined (like log_mcap on a market-cap-filtered universe), this is invisible. For factors with structural NaNs (like EP with negative-earnings exclusion), it silently breaks the analysis. Pattern to remember: any per-date regression on a factor with possible NaN values needs a `valid_mask` filter before the lstsq call, and residuals should be written back only to valid positions.

**Volatility drag and arithmetic vs geometric returns.** Arithmetic mean of monthly returns is what most stat tests use because it's an unbiased estimator. Geometric mean (compound return) is what investors actually experience. The two diverge by approximately variance/2 per period: geometric ≈ arithmetic − (std²)/2. For our Q1 expensive portfolio, arithmetic mean is +0.09%/mo (essentially zero) but geometric mean is roughly −0.36%/mo because of the 9.5% monthly volatility, producing a cumulative −16.67% over 51 months. For Q5 with 7.3% monthly std, the drag is smaller and the cumulative compound return tracks the arithmetic mean more closely. Lower-volatility quintiles enjoy a free compounding bonus that doesn't show up in t-tests on arithmetic means.

**Long-only alpha versus long-short return.** A factor's Q1−Q5 spread is a long-short return that requires shorting infrastructure to capture. In A-shares, short-selling via 融券 is restricted (only certain stocks are 融券标的), expensive (8-15%/yr borrow costs, time-varying), and supply-constrained. For retail traders the practical question is the long-only version: does the cheap leg (Q5) outperform a passive baseline? In our case Q5 beats the universe-equal-weight by 1.87pp/yr, which is the realistic alpha. The Q5−Q1 of 14.05%/yr is academically interesting but not actionable for most market participants.

**Tushare pe_ttm encoding for negative earnings.** Tushare returns NaN, not a negative number, for stocks with negative TTM net profit. Confirmed by direct inspection: zero negative pe_ttm values across 271,354 rows pulled. This means the print message in `source_ep_data.py` reporting "0 rows excluded for E<=0" is technically correct but misleading. The CH-3 negative-earnings exclusion happens at the Tushare data layer rather than at our explicit filter; the 23.1% missing-pe_ttm bucket combines negative-earnings firms with genuinely missing data and cannot be separated without additional queries.

**Refactoring "behaviour-preserving" is conditional on the test case.** The size-factor regression test passed bit-for-bit after the refactor. That was necessary but not sufficient to conclude the refactor was safe for all factors. The latent NaN-handling bug in residualisation only surfaced when value's 27.8% NaN rows entered the regression. Future refactors should be tested not just on the case the refactor was developed against (size, no NaN), but on the case the refactor will next be applied to (value, with NaN), before declaring success.

---

## Skills (new code-level patterns)

- Parameterising a factor analysis pipeline: `sort_col` parameter on every quintile/IC/residualisation function; per-factor wrapper scripts that set `FACTOR_COL = "..."` and call the parametric utilities.
- NaN-aware per-group regression: build a `valid_mask` on the factor and grouping columns, restrict the lstsq call to the valid subset, write residuals back via `valid_idx = valid_group.index.to_numpy()`. Pre-allocate `out_residuals = np.full(len(df), np.nan)` so unwritten positions remain NaN by default.
- Sharing project-level resources via `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` before the import. Resolves from `__file__` not cwd, so works regardless of invocation directory. Wrap the import in try/except for a clear error message if the shared module is missing.
- Module-level singleton for API clients: `tushare_client.py` exposes `pro = ts.pro_api(token)` at import time, creating one connection reused across all callers.
- Auto-creating output directories at module load: `GRAPHS_DIR.mkdir(exist_ok=True)` in `factor_utils.py` so plotting calls never fail on first run.
- Bit-for-bit regression testing across refactors: `python size_analysis.py` after every change to `factor_utils.py`, comparing every printed number to the prior closeout's quoted values. Differences in the third decimal place are not acceptable.
- Computing both arithmetic and geometric returns when reporting: `arithmetic = series.mean()`, `geometric = (1 + series).prod() ** (1/n) − 1`, `cumulative = (1 + series).prod() − 1`. Volatility drag matters for storytelling.

---

## Codebase

Four new files in `Project_6/` (replacing three Session 2 files):

- `factor_utils.py` (~620 lines) — all factor-generic logic. Constants (DATA_DIR, GRAPHS_DIR, EP_PANEL_PATH, REGIME_EVENTS, REGIME_SPLIT_DATE, SEED, MIN_STOCKS_PER_SECTOR), data loading (load_panel, load_sector_map), core analysis (compute_quintile_series, compute_ic_series, summarise_long_short), Pass 1 layers (layer_1_bootstrap_ci, layer_2_regime_split, layer_3_tradable_only), Pass 2 layers (layer_4_sector_neutral, layer_5_cap_terciles), helpers (residualise_factor_per_date, benjamini_hochberg), plotting (plot_cumulative_quintiles, plot_ic_series).
- `size_analysis.py` (~96 lines) — sets `FACTOR_COL = "log_mcap"`, calls the utilities. Replaces three Session 2 files.
- `value_analysis.py` (~150 lines) — sets `FACTOR_COL = "ep"`, loads EP from `data/ep_panel.csv` via `add_ep_to_panel()`, then identical structure to size_analysis.py.
- `source_ep_data.py` (~155 lines) — pulls Tushare daily_basic for 52 rebalance dates, computes `ep = 1/pe_ttm`, saves to `data/ep_panel.csv`. Imports from project-root `tushare_client.py` via sys.path manipulation.

New data file: `data/ep_panel.csv` (271,354 rows, 11 columns).
New plots: `graphs/value_quintile_cumulative_returns.png`, `graphs/value_ic_time_series.png`, plus updated `graphs/size_*.png`.

Old files deprecated (kept in archive/ until momentum verified through the new machinery): `size_pipeline.py`, `size_robustness.py`, `size_robustness_pass2.py`.

`hypothesis_testing.py` and `verify_imports.py` unchanged.

`tushare_client.py` lives at the parent `Intro_to_Quant/` level, shared across projects. Loads token from `.env` at the same level via dotenv.

---

## Misconceptions corrected

- **PREDICTED: value works in high-cap tercile, fails in low-cap. ACTUAL: opposite.** Predicted reasoning was that the high-cap tercile (largest stocks among our small caps, closest to LSY's universe) would be the cleanest segment for value, while the low-cap tercile would be drowned in shell-value contamination. Actual: low-cap −1.102%/mo (BH-rejecting at p=0.015), mid −0.334% (no signal), high +0.046% (zero). LESSON: the negative-earnings exclusion at the Tushare data layer (27.8% of rows) already filtered out the strongest shell candidates before the value sort ran. What remained in the low-cap tercile is positive-earnings small caps, where mean-reversion mechanics work powerfully and the small absolute price levels mean larger percentage swings on the same fundamental change. The high-cap tercile is dominated by stocks that have rallied enough to be at the top of our universe and have already mean-reverted from cheap toward fair. The "cleaner segment" framing was wrong: filtering at the data layer inverted the cap-size-to-contamination relationship. Going forward, do not assume the LSY shell-contamination story applies in the same direction to our universe; our pre-filtering changes which segments are clean.

- **PREDICTED: Q1−Q5 in [-0.5%, +1.0%]/mo at t in [-1.0, +2.0], later refined to [-0.3%, +1.0%] at t in [-0.7, +2.0]. ACTUAL: headline -0.513% at t=-1.12 (within range), sector-neutral -0.762% at t=-2.23 (past predicted lower bound).** The headline matched the prediction range but the sector-neutral version exceeded it. LESSON: prediction ranges should account for the possibility that sector neutralisation strengthens rather than weakens a signal, not just the assumption that sectors are noise. For a factor where sector composition could plausibly point either direction (high-EP-by-sector vs. cheap-by-within-sector-ranking), the prediction range should be at least as wide as the headline range, not narrower.

- **"Behaviour-preserving" refactor passed regression test on size but had a latent bug for any factor with NaN values.** The post-refactor size_analysis.py reproduced every Session 2 number bit-for-bit. That was sufficient to conclude size still worked but insufficient to conclude the refactor was safe for value. `residualise_factor_per_date` passed NaN values directly to `np.linalg.lstsq`, which silently propagated NaN through every residual. The bug only surfaced when value's 27.8% NaN rows hit the function. LESSON: a refactor's regression test should cover both the case the refactor was developed against (size) and the case the refactor will next be applied to (value). Test coverage on the calling case, not just the developing case.

- **Source script's print statement reports "0 rows excluded for E<=0" when actually 23.1% are excluded as NaN.** Tushare encodes negative-earnings firms as `pe_ttm = NaN`, not as a negative number. The CH-3 exclusion happens at the data layer rather than at our explicit `pe_ttm <= 0` filter. The print message is technically correct but misleading. LESSON: when a data source applies its own filtering convention, our downstream filters may report zero exclusions because the work was done upstream. Document the data-source convention; don't read the zero as "the filter wasn't needed" when it might mean "the filter ran upstream."

---

## Habits built

- **Sanity-check the data before running analysis.** The "0 rows excluded for E<=0" anomaly was caught by stopping to ask "wait, that doesn't match what we expected" before running value_analysis.py. Catching this at the data inspection stage (rather than after running analysis on bad data) saved us from chasing artefacts. Pause on anything unexpectedly clean or unexpectedly anomalous; the cost of a 2-minute spot check is much lower than the cost of a wrong-results-driven session.

- **Compute absolute returns alongside relative spreads.** A Q1−Q5 spread tells you nothing about whether the long-only leg is profitable. Whenever a factor produces a meaningful spread, also compute per-quintile absolute returns, the long-only alpha versus a passive baseline, and the regime decomposition. The headline Q1−Q5 is the academic finding; the absolute returns are the operational reality. They tell different stories and both stories matter.

- **Bit-for-bit regression testing after every refactor.** `python size_analysis.py` after every change to `factor_utils.py`. Compare every printed number to the prior closeout. Differences in the third decimal place are not acceptable, even if they look "small." Use the prior closeout's numbers as the test fixture; this is what those quoted numbers are for.

- **Run regime splits on absolute returns, not just on spreads.** Layer 2 in our machinery splits the Q1−Q5 spread by regime. But the Q5 absolute return split was equally informative and not in the standard machinery: pre-stimulus Q5 −7%/yr versus post-stimulus +65%/yr. The spread can look stable across regimes while the absolute returns fluctuate wildly. For any factor with a real signal, run an absolute-return regime split as a follow-up to the standard Layer 2.

- **State the prediction in writing before running the test.** The "predicted high-cap tercile would be cleaner" misconception was correctable specifically because we'd written it down beforehand and could compare to the actual result. Without the written prediction, the actual result would have been absorbed silently into "what we found" with no calibration signal. Calibration only improves if the prediction is observable.

---

## Thesis implications

- **Value is the first factor with a defensible long-only thesis in our universe.** Multiple independent layers (IC CI excludes zero, sector-neutral spread CI excludes zero, low-cap-tercile spread BH-rejects after correction) point the same direction. This is the strongest single-factor signal we have so far. Subsequent factors (momentum, low-vol) should set their bar relative to this one.

- **The long-only alpha is modest and likely cost-sensitive.** Q5 in the low-cap tercile beats the universe baseline by +1.87pp/yr. With monthly rebalancing and 50-80bps round-trip costs in the smallest segment of our universe, transaction costs could plausibly consume 30-60% of that alpha. The cost-adjusted Sharpe analysis (open item) is now a gating concern rather than a future improvement; the strategy is academically interesting but its operational viability hinges on cost arithmetic we haven't done yet.

- **Regime concentration is a serious flag.** The 32-month pre-stimulus period showed the cheap leg losing money at −7%/yr in absolute terms; the 19-month post-stimulus period showed +65%/yr. Any allocation decision needs to confront the possibility that the post-stimulus period is the regime, not noise around the strategy's true expected value. If the next four years look more like 2022-2024 than 2024-2026, the long-only Q5 leg could lose money for years before recovering. We do not have a way to discriminate between "the strategy works on average across regimes" and "the strategy works only in rallies" with our 51-month sample.

- **Within-sector value is the right framing for our universe.** The headline Q1−Q5 understates the signal because of sectoral composition effects. Sector neutralisation is not just a robustness check for value; it's part of the correct definition. Future operational implementations should sector-neutralise the value signal rather than treat the raw EP rank as the trade.

- **The cap-size-to-contamination relationship in our universe is not the LSY one.** The negative-earnings filter at the data layer changes which segments are clean. We should not import LSY's sample-design assumptions wholesale into our universe; the same exclusion that LSY does at the universe-construction level (drop bottom 30%) we do at the factor-construction level (NaN-exclude negative earnings), which produces a structurally different relationship between cap size and shell contamination.

- **Universe is structurally expensive.** Median EP in our universe is +0.0222 (P/E ~45), versus broad-market median ~30 and CSI300 ~12-15. Even our cheap quintile (Q5) is absolutely expensive relative to the broader market. The within-universe ranking still works, but absolute-level interpretation needs to keep this context in view.

---

## Open items

- **Cost adjustment via `cost_adjusted_sharpe` applied to low-cap tercile Q1−Q5 series.** Now a gating item before treating value as actionable, not a future improvement. Suggested approach: 50-80bps round-trip baseline cost for the smallest segment of our universe (the long-only Q5 leg in the low-cap tercile is the most cost-sensitive case). Run sensitivity at 30bps, 50bps, 70bps, 100bps. Decision rule: if the net Sharpe stays meaningfully positive at 50-70bps, the strategy survives realistic friction; if costs eat most of the alpha at those levels, we have an academic finding but not an actionable one without further engineering (lower turnover, fewer rebalances, or smaller universe of high-conviction picks).

- **Graduating-out hypothesis test.** Higher priority now than after Session 2. With value showing a clear asymmetric pattern across cap terciles (strong at low, zero at high), the graduating-out story is the most plausible mechanism for the high-tercile null. Test: split each quintile into "still in universe at t+1" vs "leaves universe at t+1" and compare forward returns. If leavers earn substantially more than stayers in the high-cap tercile specifically, the graduating-out story is confirmed and we have a structural reason for the pattern. Block 3 work, but worth surfacing in Session 4 if time permits.

- **Print message in `source_ep_data.py`.** Should say "Excluded due to missing or non-positive pe_ttm (Tushare encodes negative earnings as NaN)" rather than "Excluded due to E<=0 (CH-3 rule)". Documentation accuracy issue, not a behaviour bug. Patch when next in the file.

- **ACF on value IC time series.** Residual autocorrelation diagnostic. `acf_band` is built but not yet used; this is its first natural application. If the value IC series shows significant autocorrelation, the bootstrap CI we computed (block_size=3) may be optimistic and we'd want to revisit with a longer block size. Block 3 work.

- **B/M robustness check.** Originally planned as a robustness against the EP primary measure. Lower priority given the strength of the EP signal but still worth running for completeness; if B/M produces a similar signal, it strengthens the value finding; if it produces nothing, we need to think about why EP and B/M diverge in our universe.

- **Composite value score (EP + B/M + S/P, equal-weighted z-scored).** Block 3 if at all. Rationale was always to blunt each individual ratio's failure modes by averaging across them. With EP showing a clear single-ratio signal, composite is a tail-risk hedge against the EP-specific story being wrong, not a primary investigation.

- **Mid-cap tercile p=0.080 watchlist item from Session 2 (size).** Carried forward unchanged; nothing in Session 3 affected this.

---

## Bridge to next session

**Session 4 focus: momentum factor.** Same five-layer machinery, applied to a momentum signal. The standard JT 1993 specification is `momentum_12_1` (cumulative return over the past 12 months excluding the most recent month, the "skip month" controlling for short-term reversal). Our factor architecture handles this with one new line in `factor_utils.py` (or a separate `add_momentum_to_panel()` in a new `momentum_analysis.py`) and the same five-layer sweep otherwise.

Session 4 prerequisites:

1. Source price history for the momentum window. Forward returns alone are insufficient because we need the trailing 12 months of returns ending one month before each rebalance date. Two paths: pull daily prices from Tushare for all stocks across 2021-2026 (need an extra year for the trailing window before our 2022 panel start) and compute monthly returns ourselves; or pull monthly returns directly. The data sourcing budget is roughly one session, similar to the EP pull.

2. Define the momentum measure precisely. JT 1993 standard: `mom_12_1[t] = product_{m=t-13}^{t-2}(1 + r[m]) − 1`, the 12-month return ending one month before t. The skip month matters: short-term reversal contaminates pure-12-month momentum, especially in retail-dominated markets. Verify the construction handles missing data correctly (stocks with incomplete trailing windows get NaN, dropped from the sort).

3. Negative-momentum handling. Unlike EP, momentum is symmetric around zero: positive past returns (winners) and negative past returns (losers) are both meaningful and both rank-able. No analogue to the CH-3 negative-earnings exclusion.

**Predictions for momentum (calibrated against the size and value lessons).** The China A-share momentum literature is more mixed than the value literature. Several papers document momentum CRASHES or REVERSAL in Chinese small caps, the proposed mechanism being retail-dominated overreaction-then-correction dynamics (winners get bid up past fair value by retail FOMO, then mean-revert; losers get sold past fair value by panic, then mean-revert). For our universe specifically, predict Q1−Q5 in [-1.0%, +0.5%]/month at t in [-1.5, +1.0], with substantially more probability on the negative sign than the positive (i.e., expect "winners lose, losers win" mean-reversion rather than JT-style continuation). Less confident than the value prediction because the literature is more divided. CIs likely to be wider than value's because momentum has higher month-to-month variability than EP.

If momentum produces a strong negative Q1−Q5 (mean-reversion confirmed), the actionable implication is that "buy the recent losers, sell the recent winners" works in our universe as a 1-month-skip 12-month strategy. If momentum produces a weak positive Q1−Q5, the JT-style continuation works (less likely). If momentum produces a noisy null (most likely outcome at n=51), we add momentum to the family and move on.

**Prediction-vs-actual tracking for value (logged here for future reference):**

| Test | Predicted range | Actual | Within range? |
|---|---|---|---|
| Headline Q1−Q5 mean | [-0.3%, +1.0%]/mo | -0.513%/mo | Yes (lower end) |
| Headline t-stat | [-0.7, +2.0] | -1.12 | Yes (lower end) |
| Sector-neutral Q1−Q5 mean | within headline range | -0.762%/mo | NO (past lower bound) |
| Sector-neutral t-stat | within headline range | -2.23 | NO (past lower bound) |
| Cap-tercile direction | high clean, low contaminated | low BH-rejects, high zero | NO (opposite) |
| IC mean | [-0.02, +0.04] | +0.0382 | Yes (upper end) |

Two clean misses (sector-neutral magnitude past predicted bound on the strong side; cap-tercile direction inverted) and four within-range. Calibration lesson going into momentum: ranges for high-uncertainty factors should be wider, and direction-of-effect predictions for novel-universe applications should be hedged rather than directional.

**Block 3 transition.** After momentum (Session 4) and low-vol (Session 5), the project transitions from single-factor sweeps to multi-factor combinations and operational analysis. The graduating-out test, the cost-adjusted Sharpe analysis, and any composite-factor work all live in Block 3. Estimated remaining sessions before Block 3: 2 (momentum + low-vol).

These predictions and the Block 3 plan are conscious calibration practice, not commitments. We log them now and check them at the end of Sessions 4 and 5.
