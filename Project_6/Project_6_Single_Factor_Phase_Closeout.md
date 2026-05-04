# Project 6 — Single-Factor Phase Closeout

**Phase focus:** Complete the single-factor analysis chunk of Project 6: size, value (EP), momentum (multi-horizon), low volatility (multi-horizon), all run through the same five-layer machinery. Consolidate findings before transitioning to multi-factor analysis in a separate conversation.

**Date range covered:** Sessions 1 through 5 of Project 6, completed 2026-04-28.

**Curriculum position:** Phase 3, Project 6 (Factor Testing). This document closes the single-factor sub-phase. Project 6 continues with multi-factor analysis (separate conversation) before transitioning to Project 7 (Build a Backtester) and Project 8 (Strategy Evaluation & Paper Trading) per the trajectory revised in the Project 5 closeout.

---

## Key takeaways

1. **Single-factor verdict matrix.** Size: noisy null at all five layers. Value (EP): real signal in low-cap tercile, BH-rejected at p=0.015, sector-neutral spread CI excludes zero, regime-concentrated. Momentum: noisy null at all four horizons (12_1, 6_1, 3_1, 1_1) at the headline. Sector neutralization eliminates the small headline effects across horizons. Mom_12_1 high-cap-tercile cell at +1.38%/mo (raw bootstrap p=0.033) marginally interesting but fails BH correction. Low volatility: noisy null at all three horizon headlines, but vol_12_1 high-cap-tercile cell at +1.76%/mo with bootstrap p=0.009, BH-REJECTING at α=0.05. The strongest single cell across the project so far.

2. **Cap-tercile conditioning is the defining structural finding of the phase.** The single-factor literature (LSY, Li-Rao 2022) treats factors as broadly applicable across the universe; in our specific cap stratum they are not. Value lives in the low-cap tercile (BH-rejecting). Low-vol lives in the high-cap tercile (BH-rejecting). Momentum shows weak across-horizon coordination only in the high-cap tercile. The mid-cap tercile is structurally null across all four factors. This pattern emerged consistently and is not predicted by the literature we have read; it must be respected in the multi-factor stage.

3. **The universe-turnover constraint is the binding methodological problem.** Out of 2,925 stocks that ever appeared in the universe across 52 dates, only 6 stocks were continuously in for all 52. The median stock was in for 15 of 52 months. For factors with formation windows, the strict-eligibility filter excluded ~90% of in-universe stocks at typical mid-panel dates. Relaxed-coverage with the 75% threshold and per-factor imputation logic recovered to 30-65% but introduces its own bias for the imputed stocks. The clean fix is a panel rebuild with full return histories for all stocks that ever appeared, with the universe filter applied only at the cross-sectional sort step. Database rebuild is now the highest-priority post-multi-factor item.

4. **Sector neutralization is an essential diagnostic, not just a robustness check.** Pattern across factors: value strengthened sharply under neutralization (-0.51% headline became -0.76% sector-neutral, CI excluded zero). Low-vol slightly strengthened at all horizons (vol_12_1 sign flipped from -0.16% to +0.16%). Momentum collapsed to zero at every horizon (the small headline effects were entirely sector composition). This tells us where each signal lives. Value and low-vol are stock-specific (within-sector ranking matters). Momentum is sector-loaded (within-sector ranking does not matter). For multi-factor combination, knowing the locus of each signal is essential, because two sector-loaded factors will correlate via shared sector rotation regardless of their stated definitions.

5. **IC vs Q1-Q5 disagreement is a non-monotonicity diagnostic.** Encountered first with mom_12_1 (Q1-Q5 negative, IC negative), then again with vol_12_1 (Q1-Q5 negative, IC negative). When the two summary statistics give opposite signs, the cross-section is non-monotonic across quintiles: typically the middle quintiles outperform both extremes (hump shape). IC uses every stock and weights monotonic relationships heavily. Q1-Q5 only the extremes. When they disagree on whether a signal is meaningful, IC has tighter inference (uses more data) and should drive the inference call, with the quintile cumulative plot consulted to interpret the shape.

6. **Multi-horizon sweep methodology proved its worth as a noise-vs-signal heuristic.** For momentum, the four horizons gave Q1-Q5 of +0.10, +0.32, -0.04, +0.04: scattered around zero with no across-horizon coordination. The sign-scatter is itself the noise signature. For low-vol, the three horizons gave +1.76, +1.15, +1.38 at the high-cap tercile: coordinated direction with magnitudes within a narrow band. Cross-horizon coordination distinguished the noise case from the (weakly) coherent case even when only one horizon cleared statistical significance individually. This methodology is now standard for any factor with a formation-window choice.

7. **Imputation logic must respect the math of each factor.** Cross-sectional median imputation is roughly bias-neutral for a cumulative product (momentum) but biases standard deviation downward for stocks needing imputation, because the median sits at the centre of the cross-section by construction and contributes less dispersion than a real observation would. We use median imputation for momentum, and observed-only-via-min_periods for volatility. Same eligibility threshold (75%) across factors, per-factor implementation differs where the math demands. Methodology consistency at the eligibility layer; per-factor implementation respects bias direction.

8. **Predictions-vs-actuals calibration improved across the phase.** Logged predictions before each factor:
   - Size: predicted noisy null, got noisy null. Hit.
   - Value: predicted Q1-Q5 in [-0.3%, +1.0%], got -0.51% (within range), but missed cap-tercile direction (predicted high-cap clean per LSY shell logic, got low-cap clean) and sector-neutralization direction (predicted weakens, got strengthens). Mixed.
   - Momentum: predicted reversal direction (positive Q1-Q5, negative IC). Got noisy null with sign-scatter on Q1-Q5 across horizons but consistently small negative IC. Direction-of-effect partly hit (IC) but partly missed (Q1-Q5); magnitude prediction (small) hit.
   - Low-vol: predicted positive Q1-Q5 / negative IC. Got both directionally, with magnitude weaker than predicted at headline but stronger than predicted at high-cap tercile (segment not explicitly predicted).
   The recurring lesson: direction-of-effect predictions grounded in well-documented mechanisms (lottery preference, value mean-reversion) calibrate well. Magnitude predictions should keep wide ranges. Segment predictions (where in the universe a signal will live) are unreliable without cap-tercile-conditional priors from the literature, which we do not have.

9. **The single most actionable cell across the project is vol_12_1 high-cap.** Q1-Q5 = +1.76%/mo (≈+21% annualized for the long-short), bootstrap p=0.009, BH-rejected. The mechanism (lottery preference for high-volatility stocks in retail-dominated markets, per LSY 2019) is consistent with Chinese A-share microstructure. But this is one cell of one factor in one cap segment. It requires multi-factor corroboration and ideally validation on the rebuilt panel before being trusted as actionable. Cost-adjusted Sharpe analysis is open before any actionability conclusion can be drawn.

10. **The multi-factor question has a concrete starting hypothesis from this phase's findings.** Value lives in the low-cap tercile; low-vol lives in the high-cap tercile. These are operationally complementary: different mechanisms in different parts of the universe. A multi-factor approach that respects cap-tercile conditioning could expose to value in the bottom third and low-vol in the top third, capturing both signals while diversifying across both segments. Whether that is done via composite z-scoring within terciles, factor-mimicking portfolios per tercile, or some other approach is the methodology question for the next chat.

---

## Reference conversations

This document consolidates the single-factor phase of Project 6. The earlier session-by-session closeouts remain canonical for their respective work and are referenced rather than duplicated here.

- **Project 5 closeout** (`Project_Five_Closeout.md`): defined the universe (1000 stocks per date, monthly rebalance by cap rank within liquidity-filtered candidates), built the forward-return panel (52,000 universe rows, 51 forward-return observations × 1000 stocks), identified regime-event dates (雪球 meltdown 2024-01-15, 新国九条 2024-03-15, PBoC stimulus 2024-09-18), produced sw_membership and tradability flags. Also revised the curriculum: original Project 5 (size factor) and Project 6 (multi-factor analysis) merged into unified Project 6 (Factor Testing) covering size, value, momentum, volatility plus multi-factor combination.

- **Project 6 Session 1-2 closeout** (`Project_6_Session_1_2_Closeout.md`): built `hypothesis_testing.py` (seven functions: t-test, two permutation tests, two bootstrap CIs, ACF band, cost-adjusted Sharpe). Promoted from a Project 4 debt of scattered notebook cells. Locked the multi-test correction policy: Holm-Bonferroni across factor headlines, Benjamini-Hochberg within within-factor robustness families. Ran size factor through five layers; logged noisy null with mid-cap-tercile p=0.080 watchlist item. Discovered the volatility-compression-across-regimes finding: Q1-Q5 std dropped from 3.10%/mo pre-stimulus (n=32) to 1.96%/mo post-stimulus (n=19), a 35% compression that implies pooled-sample factor analysis mixes two different signal-to-noise environments.

- **Project 6 Session 3 closeout** (`Project_Six_Session_3_Closeout.md`): refactored size-specific scripts into parametric `factor_utils.py` plus per-factor wrappers. Sourced EP data via Tushare daily_basic. Ran value factor through five layers. Found real signal in low-cap tercile (BH-rejecting at p=0.015), with sector neutralization strengthening rather than weakening the signal, and severe regime concentration in the long-only Q5 leg (-7.18%/yr pre-stimulus over 32 months vs +64.59%/yr post-stimulus over 19 months). Discovered and fixed a NaN-handling bug in `residualise_factor_per_date` that surfaced only when EP's 27.8% NaN rows hit Layer 4.

- **This document**: consolidates findings from all four single-factors (Sessions 1 through 5), surfaces the universe-turnover constraint as the dominant methodological issue, corrects a sign-convention error in the Session 3 closeout's momentum prediction, and bridges to the multi-factor phase.

---

## Starting point (entering Session 4)

Inherited from Session 3:

- Size factor's null result and value's signal in the low-cap tercile.
- Hypothesis-testing toolkit (`hypothesis_testing.py`) and parametric `factor_utils.py` machinery, fully tested through size and value.
- 51-rebalance-date forward-return panel from Project 5.
- EP data sourced from Tushare and merged into the panel.
- Multi-test correction policy locked: Holm-Bonferroni across factor headlines, BH within-factor robustness families.
- Several open items from Session 3: cost-adjusted Sharpe on value's low-cap leg, graduating-out hypothesis test for value's high-cap null, ACF on factor IC time series, B/M robustness check.

The user's directives at the start of Session 4 were: (1) work with existing data without pulling new prices for momentum, (2) favor multi-horizon over single-horizon to test the LSY "any window" reversal claim. Session 5 added the constraint of running multi-factor and database rebuild only AFTER all single-factor analyses are complete.

---

## Phase thesis

If the four factors were tested rigorously on our specific universe and panel, we would expect to recover the broad shape of factor returns documented in the China factor literature: size weak or absent within a small-cap-only universe, value strong and EP-driven, momentum weak or absent at JT-style horizons, low-vol present. The actual results largely match this structure with one striking modification: every factor signal that appears is concentrated in one specific cap tercile, with mid-cap structurally null and value and low-vol living in opposite segments (low-cap and high-cap respectively). The cap-tercile structure was not predicted by the literature; it emerged from the data and is now the most operationally important finding to carry forward.

Secondarily, the universe-turnover-induced coverage problem proved more severe than expected. With monthly universe refresh by cap rank, only a small fraction of stocks ever in the universe were continuously in for the median 13-month formation window required for momentum and long-window volatility tests. This forced relaxed-coverage imputation and is the binding methodological problem to fix before the project can produce a final answer rather than a methodological proof-of-concept. The eventual panel rebuild is now the most consequential methodological investment available to the project.

---

## Progression by factor

### Size (Sessions 1-2)

Headline Q1-Q5: -0.181%/mo, t≈-0.49. IC mean: +0.0153, t≈+1.29. Layer 1 bootstrap CIs: Q1-Q5 [-0.895%, +0.616%], IC [-0.0088, +0.0377]. Both contain zero.

Layer 2 regime split: pre-stimulus -0.260%/mo (n=32, std 3.10%), post-stimulus -0.049%/mo (n=19, std 1.96%). Both regimes consistent with null. Volatility compression across regimes (35% drop) was the most operationally interesting Pass 1 finding: not relevant to the size verdict, but an environmental fact to factor into all subsequent analyses.

Layer 3 tradable filter: -0.160%/mo, near-identical to headline. Drop rate 4.19% (universe-level, factor-independent across all four factors).

Layer 4 sector neutralization: -0.136%/mo, similar to headline. No sector-driven story being masked.

Layer 5 cap-tercile: low p=0.878, mid p=0.080, high p=0.674. Mid-cap p=0.080 logged as watchlist item but fails BH correction (BH threshold for the smallest p in family of 3 is 0.0167).

Verdict: noisy null at all layers. Mid-cap watchlist remains open; consistent with the cross-factor pattern that emerged later (mid-cap is structurally null across all four factors), the p=0.080 may be a chance fluctuation rather than a hidden signal.

Notable methodological detail: log_mcap is never NaN within our universe (the universe is defined by cap rank, so cap is always observed). This made size the cleanest test environment for the parametric machinery; the NaN-handling bug in residualisation only surfaced when EP entered the pipeline.

### Value (EP) (Session 3)

Headline Q1-Q5: -0.513%/mo, t=-1.12. IC mean: +0.0382. Layer 1 bootstrap CIs: Q1-Q5 [-1.177%, +0.269%] (just contains zero), IC [+0.0100, +0.0619] (excludes zero, the first such CI in the project).

Layer 2 regime split: pre-stimulus -0.629%/mo (n=32, contains zero), post-stimulus -0.317%/mo (n=19, contains zero). Both directionally consistent.

Layer 3 tradable filter: -0.510%/mo, headline preserved.

Layer 4 sector neutralization: -0.762%/mo at t=-2.23, CI [-1.296%, -0.263%] (excludes zero). Signal strengthened under neutralization. Mechanism: structurally low-P/E sectors (banks, utilities, real estate) populated Q5 by sector classification rather than by within-sector valuation. In our 2022-2026 sample these sectors performed roughly flat-to-negative, diluting the raw Q5 portfolio. Within-sector value is the real signal.

Layer 5 cap-tercile: low -1.102% (p=0.015, BH-REJECTING at α=0.05), mid -0.334% (p=0.408), high +0.046% (p=0.920).

Long-only analysis: Q5 (cheap leg) in low-cap tercile +1.191%/mo (+15.27%/yr arithmetic), beating universe-equal-weight baseline by +1.87 pp/yr. Volatility drag matters: Q1 (expensive) cumulative -16.67% over 51 months despite arithmetic mean of +0.090%/mo, due to 9.48% monthly std.

Severe regime concentration: Q5 pre-stimulus -0.619%/mo (-7.18%/yr) over 32 months, Q5 post-stimulus +4.240%/mo (+64.59%/yr) over 19 months. Full-sample positive return is entirely the post-stimulus rally.

Verdict: real signal at multiple independent layers (IC excludes zero, sector-neutral excludes zero, low-cap BH-rejects). Operational viability gated on cost-adjusted Sharpe analysis (still open).

### Momentum (Session 4)

Multi-horizon sweep over mom_12_1, mom_6_1, mom_3_1, mom_1_1. Strict-eligibility coverage was 9.7% at mom_12_1 (only 139 of 1000 in-universe stocks per date had continuous 13-month history). Relaxed coverage with 75% threshold and cross-sectional median imputation: 28.8%, 37.4%, 41.9%, 64.9% across the four horizons.

Headlines (Q1-Q5 in %/mo): +0.10, +0.32, -0.04, +0.04. All |t| below 0.7. All bootstrap CIs contain zero.

ICs across horizons: -0.014, -0.006, -0.018, -0.019. All within [-0.05, +0.01], all bootstrap CIs just contain zero.

Sign coordination: Q1-Q5 signs scatter across horizons (+, +, -, +); IC signs all negative but tiny in magnitude. The Q1-Q5 sign-scatter is the noise signature.

Layer 4 sector neutralization at all horizons: spreads stay close to zero (-0.06%, +0.07%, +0.18%, +0.18%). The small headline effects were sector composition (industry-level momentum), not stock-specific. This is the clearest negative finding for individual-stock momentum at any of the four horizons.

Layer 5 cap-tercile: high-cap mom_12_1 cell at +1.38%/mo, bootstrap p=0.033, fails BH (BH threshold 0.0167). All four horizons show positive Q1-Q5 in the high-cap tercile (+1.38, +0.20, +0.54, +0.71). Probability of all four positive under independent fair-coin signs is 1/16 = 6.25%, suggestive but not decisive.

Verdict: no detectable stock-specific momentum effect at any horizon in our universe at this sample size. Weak across-horizon coordination in the high-cap tercile suggests a small reversal effect there (mechanistically consistent with retail overreaction in the largest of our small caps), but this fails formal correction. LSY's "reversal at any window" claim does not show up cleanly in our specific universe stratum, which may reflect selection-bias from the formation-window filter or genuinely different dynamics in our cap segment compared to LSY's broader 2000-2016 sample.

### Low volatility (Session 5)

Multi-horizon sweep over vol_12_1, vol_6_1, vol_3_1. Coverage at 75% min: 30.2%, 38.0%, 41.9%. Imputation handling differs from momentum: pandas `rolling().std()` with `min_periods=ceil(0.75 * lookback)`, no median imputation in the std calculation itself. Median imputation would bias std downward for stocks needing imputation, contaminating the test toward the hypothesis being tested.

Headlines (Q1-Q5 in %/mo): -0.16, +0.17, +0.24. All |t| below 0.5. All bootstrap CIs contain zero.

ICs across horizons: -0.030, -0.022, -0.020. All directionally consistent with low-vol working. All bootstrap CIs just barely contain zero (vol_12_1 IC CI is [-0.065, +0.006], upper edge essentially touching zero).

Sign coordination: vol_12_1 has Q1-Q5 negative but IC negative (the non-monotonicity disagreement, same pattern as mom_12_1). vol_6_1 and vol_3_1 agree directionally with both statistics positive on Q1-Q5 and negative on IC.

Layer 4 sector neutralization at all horizons: spreads slightly strengthen positively. vol_12_1 -0.16% becomes +0.16% (sign flips), vol_6_1 +0.17% becomes +0.23%, vol_3_1 +0.24% becomes +0.33%. Within-sector low-vol signal is slightly stronger than the headline. None of the sector-neutral CIs exclude zero.

Layer 5 cap-tercile: vol_12_1 high-cap at +1.76%/mo, t=+2.12, bootstrap p=0.009, BH-REJECTING at α=0.05. vol_6_1 high-cap p=0.055, vol_3_1 high-cap p=0.070 (both fail BH but are close). All three high-cap cells positive (+1.76, +1.15, +1.38) with magnitudes around +1.4%/mo. Mid-cap and low-cap cells weakly random across horizons.

Layer 2 regime split for vol_12_1: pre-stimulus +0.47%/mo, post-stimulus -0.88%/mo. Sign-flip across regimes consistent with the pre-flagged failure mode that low-vol typically lags in roaring bull markets. vol_6_1 and vol_3_1 show smaller regime differences with same-sign averages.

Verdict: BH-rejected single cell in high-cap tercile at vol_12_1 is the strongest signal across the project. Cross-horizon coordination at high-cap supports the result not being a chance fluke (3 of 3 positive with similar magnitudes), though shorter horizons fall just short of BH significance individually. Mechanism (lottery preference in retail-dominated small caps) is well-documented and consistent with the universe.

---

## Conceptual ground (new in this phase)

**Cap-tercile-conditional factor effects.** Factors do not operate uniformly across the universe even after universe construction is held fixed. Sub-segments by market cap can show very different responses to the same factor sort. This is more than a "size interaction" effect: the qualitative story of each factor changes across cap terciles. Value is real in low-cap, zero in high-cap. Low-vol is real in high-cap, weak elsewhere. Mid-cap is structurally null across our four factors. Cap-tercile conditioning is the diagnostic that revealed all of this; without Layer 5, the headline numbers would have understated each factor's signal because averaging strong tercile with null terciles dilutes the effect.

**Sector neutralization as a "where does the signal live?" diagnostic.** A factor sort can conflate two signals: within-sector ranking and sector composition. Layer 4 strips out sector means before sorting. The headline-vs-neutralized comparison answers: does the factor capture stock-specific information, or sector tilt? For value, the within-sector signal was stronger than the headline (sector composition was diluting it). For momentum, the headline was almost entirely sector composition (within-sector ranking told us nothing). For low-vol, the within-sector signal was slightly stronger. This diagnostic is essential before any multi-factor combination because two factors with sector-loaded signals will have correlated returns (driven by shared sector rotation) regardless of their stated definitions.

**IC vs Q1-Q5 disagreement diagnostic.** When the two summary statistics give opposite signs, the cross-section is non-monotonic across quintiles: middle quintiles outperformed both extremes (hump shape) or extremes outperformed middle (U shape). IC uses every stock and weights monotonic relationships heavily. Q1-Q5 only the extremes. Disagreement is itself diagnostic of non-monotonicity. The quintile cumulative plot is the way to see the shape directly.

**Multi-horizon sweep coordination as a noise-vs-signal heuristic.** For factors with formation-window choices (momentum, low-vol), running multiple horizons simultaneously surfaces whether the signal coordinates across time-scales (real signal signature) or scatters randomly (noise signature). Momentum's sign-scatter for Q1-Q5 was the noise signature. Low-vol's coordinated +, +, + for high-cap tercile was the (weakly) coherent-signal signature. This holds as a heuristic even when no single horizon clears statistical significance.

**Universe-turnover-induced selection bias is the binding constraint on formation-window factors.** With monthly universe refresh, the strict-eligibility filter (stock must be in-universe for all formation-window months) excludes ~90% of stocks at typical mid-panel dates for a 13-month formation window. The excluded stocks are those that recently grew out of the universe (recent winners) or recently entered from above (recent losers). These are exactly the most behaviorally interesting stocks for momentum and reversal tests. The clean fix is at the panel-construction layer: separate "what is stock X's signal at date t?" from "is stock X eligible for the cross-sectional sort at date t?".

**Imputation logic must respect the math of each factor.** Cross-sectional median imputation is roughly bias-neutral for a cumulative product (each missing month gets a typical-return factor in the product). The same imputation biases standard deviation downward, because median is the centre of the cross-section by construction and contributes less dispersion than a real observation would. For momentum, median imputation is appropriate. For volatility, observed-only with min_periods threshold is appropriate. Same eligibility rule (75% min coverage), per-factor implementation respects the math.

**Volatility drag and arithmetic vs geometric returns.** Arithmetic mean of monthly returns is unbiased but does not equal the cumulative return investors actually experience. Geometric mean ≈ arithmetic − (std²)/2. For our highest-volatility quintiles, geometric returns can be substantially lower than arithmetic. Lower-volatility quintiles enjoy a free compounding bonus that does not show up in t-tests on arithmetic means. This affects long-only thesis interpretation: a positive arithmetic mean does not guarantee a positive cumulative return when volatility is high.

**Long-only alpha vs long-short return.** Q1-Q5 spreads are long-short returns that require shorting infrastructure (融券 in A-shares: restricted to certain stocks, expensive at 8-15%/yr borrow cost when available, supply-constrained). For retail traders the practical question is whether the leg you would buy long beats a passive baseline. The long-only result is typically much less impressive than the spread suggests.

**Volatility-compression-across-regimes.** Q1-Q5 std dropped from 3.10%/mo pre-stimulus (n=32) to 1.96%/mo post-stimulus (n=19), a 35% compression. Discovered in Session 1-2 size analysis but applies environmentally to all factors. Implies pooled-sample factor analysis mixes two different signal-to-noise environments. Not a verdict-changing finding for any single factor, but a fact to keep in view when interpreting CIs computed on the pooled sample.

---

## Skills (new code-level patterns)

**Parametric factor analysis pipeline.** `factor_col` parameter throughout `factor_utils.py`; per-factor wrapper scripts with `FACTOR_COL` set at the top. New factor analyses are roughly 100 lines of factor-specific data prep plus a call to the shared layers.

**Per-factor data-prep function pattern.** `add_ep_to_panel` (external Tushare merge), `add_momentum_to_panel` (computed from existing forward returns with median imputation), `add_volatility_to_panel` (computed with min_periods threshold). Each takes a base panel from `load_panel()`, computes the factor column, returns the merged panel.

**Vectorised momentum computation.** Pivot to (date × stock) matrix of forward returns, take log1p so that cumulating becomes a rolling sum, then `rolling(K).sum().shift(S+1)` aligns the formation window end with the rebalance date, and `expm1` converts back to simple cumulative return.

**Vectorised volatility computation.** Pivot to (date × stock) matrix, then `rolling(K, min_periods=ceil(min_coverage*K)).std().shift(S+1)`. The min_periods threshold encodes the coverage rule directly into the rolling computation; no separate masking step required.

**Multi-horizon sweep with cross-horizon table output.** Top-level `HORIZON_CONFIGS` list; `run_one_horizon` function called once per config; `print_cross_horizon_table` formats a single comparison row per horizon at the end; `save_summary_csv` persists for downstream analysis. Pattern is factor-agnostic and could be refactored into `factor_utils.py` post-multi-factor.

**Imputation methodology distinct from eligibility methodology.** Same eligibility threshold (75%) across factors; per-factor implementation differs based on bias direction. Document the rationale in each module's docstring so the choice is auditable.

**Pre-flight math sanity checks.** Workflow established Session 4: short verification snippets (a few lines confirming rolling/shift alignment, NaN handling, etc.) executed on the AI side before handing over the full pipeline; full pipeline runs on user side.

**Bit-for-bit regression testing after refactors.** When `factor_utils.py` changes, re-run `size_analysis.py` and verify outputs match the prior closeout's numbers exactly. Differences in the third decimal place are not acceptable. Use prior closeouts as test fixtures.

---

## Codebase

Current state of `Project_6/`:

```
Project_6/
├── data/
│   ├── universe_membership.csv         (52,000 rows, 1000 stocks × 52 dates)
│   ├── forward_return_panel.csv        (51,000 rows, 51 forward returns × 1000 stocks)
│   ├── sw_membership.csv                (sector mapping, SW L1)
│   ├── sw_classification.csv            (sector code → name)
│   ├── ep_panel.csv                     (271,354 rows, EP/PE/PB from Tushare)
│   ├── momentum_horizons_summary.csv    (4 rows, one per horizon)
│   └── lowvol_horizons_summary.csv      (3 rows, one per horizon)
├── graphs/
│   └── (per-factor cumulative-quintile and IC time-series plots,
│        all factors and horizons)
├── factor_utils.py                       (~640 lines, parametric machinery)
├── hypothesis_testing.py                 (7 functions)
├── size_analysis.py                      (96-line wrapper)
├── value_analysis.py                     (110-line wrapper, calls add_ep_to_panel)
├── source_ep_data.py                     (Tushare EP source)
├── momentum_analysis.py                  (multi-horizon sweep, ~330 lines)
├── lowvol_analysis.py                    (multi-horizon sweep, ~280 lines)
└── verify_imports.py                     (smoke-test for hypothesis_testing imports)
```

Code-cleanliness items (non-blocking):

- `run_one_horizon`, `print_cross_horizon_table`, `save_summary_csv` are duplicated between `momentum_analysis.py` and `lowvol_analysis.py`. Could be pulled into `factor_utils.py`.
- `source_ep_data.py` print statement currently says "Excluded due to E<=0 (CH-3 rule)". Should say "Excluded due to missing or non-positive pe_ttm (Tushare encodes negative earnings as NaN)" because the CH-3 exclusion happens at the data layer rather than at our explicit filter.

---

## Misconceptions corrected

**Sign convention error in the Session 3 closeout's logged momentum prediction.** The Session 3 closeout stated that "negative Q1-Q5 = mean-reversion" for momentum. Under the codebase's actual ascending convention (Q1 = lowest factor value), mean-reversion gives POSITIVE Q1-Q5 (losers Q1 outperform winners Q5), not negative. The user caught this independently from the code. Lesson: verify sign conventions against the codebase, not from memory; closeout predictions should pass through the same sanity check.

**Predicted value premium in high-cap tercile, got it in low-cap.** From Session 3, reaffirmed here as a cross-factor pattern. Reasoning was that high-cap (closer to LSY's universe) would be cleanest while low-cap would be drowned in shell-value contamination. Actual: low-cap was cleanest (BH-rejecting); high-cap was zero. Mechanism: Tushare's pe_ttm=NaN-for-negative-earnings filter at the data layer already excluded shell candidates, so what remained in the low-cap tercile was positive-earnings small caps where mean-reversion mechanics work powerfully. Cross-factor lesson: literature-derived "where the signal lives" predictions are unreliable for our specific universe stratum because data-layer filtering rearranges the cap-segment structure.

**Predicted JT-style continuation or mild reversal at mom_12_1, got noise.** LSY's "reversal at any window" claim does not show up cleanly in our universe at any of the four horizons we tested. Possible explanations: small sample (38 testable dates at mom_12_1), selection bias from the formation-window filter (~90% exclusion at strict-coverage), genuinely different dynamics in our cap-restricted stratum. Cannot distinguish without rebuilt panel. The momentum literature on China is more sample-period-dependent than the value literature; LSY's 2000-2016 window may not generalize to our 2022-2026 window even setting aside the universe-construction differences.

**Predicted low-vol headline strength comparable to value, got cap-conditional concentration instead.** Headline IC -0.030 vs value's headline IC +0.038 (similar magnitude); CIs barely-contains-zero (low-vol) vs excludes-zero (value). But the high-cap tercile cell at +1.76%/mo with bootstrap p=0.009 is more decisive than value's low-cap cell at p=0.015. Lesson: "headline strength" and "best-cell strength" are different measures of factor quality. Value distributes its signal across the cross-section more evenly than low-vol does. Low-vol's signal is more concentrated in one specific segment.

**Mid-cap tercile size effect (p=0.080) hypothesised as possibly real.** No more powerful test was run; the watchlist item carries unchanged. Across the project, mid-cap is structurally null across all four factors. The mid-cap p=0.080 is more likely a chance fluctuation than a hidden signal, given the consistent across-factor mid-cap-null pattern.

---

## Habits built

**State predictions in writing before running the test.** Calibration improves only if predictions are observable and comparable to actuals. Loose verbal predictions are not enough.

**Sanity-check the data before running analysis.** The "0 rows excluded for E<=0" anomaly in Session 3 was caught by stopping to ask "wait, that does not match what we expected" before running the full pipeline on bad data. Pause on anything unexpectedly clean or unexpectedly anomalous; the cost of a 2-minute spot check is much lower than the cost of a wrong-results-driven session.

**Compute absolute returns alongside relative spreads.** Q1-Q5 says nothing about whether the long-only leg makes money. The headline Q1-Q5 is the academic finding; the long-only Q5 (or Q1, depending on factor sign) is the operational reality. Both stories matter and they can be very different.

**Bit-for-bit regression testing after every refactor.** When `factor_utils.py` changes, re-run `size_analysis.py` and verify outputs match the prior closeout's numbers exactly.

**Run regime splits on absolute returns, not just on spreads.** The Q5 absolute-return regime split for value (-7.18%/yr pre vs +64.59%/yr post) was the most operationally important finding from Layer 2 even though the spread regime split was less remarkable.

**Pre-flight math sanity checks before handing over code.** Established Session 4. Short verification snippets run on the AI side; full pipeline runs on user side. The boundary is snippet length and whether real factor data is being processed.

**Multi-horizon sweep before drawing conclusions on factors with formation windows.** A single horizon is not enough; cross-horizon coordination is itself evidence about whether a result is signal or noise.

**Cross-factor pattern matching.** When a new factor's results come in, compare against the same layers from prior factors, not just against the literature. The cap-tercile-structure finding was visible only because we ran the same Layer 5 across all four factors and noticed signals concentrating in different terciles consistently.

---

## Thesis implications

**Value is the only factor with an unambiguous long-only thesis at the headline level.** IC excludes zero; sector-neutral spread excludes zero; low-cap tercile BH-rejects; long-only Q5 alpha of +1.87 pp/yr above universe baseline. Momentum and size produced no defensible thesis. Low-vol's BH-rejected high-cap cell is the second-strongest signal but is one cell of one factor and needs corroboration.

**Cap-tercile conditioning is foundational to how factors operate in our universe.** Multi-factor analysis must respect this structure. Approaches that compute factor exposures globally and combine them globally will likely under-perform approaches that respect the cap-tercile structure (e.g., by computing factor exposures within cap terciles, or by using cap-tercile-conditional weights).

**The mid-cap tercile is a structural dead zone across factors.** Possible interpretations: it is the boundary segment where small-cap dynamics meet larger-cap dynamics with neither dominating; it is an artifact of our specific universe definition; it is just noise. Worth flagging for the multi-factor stage.

**The eventual panel rebuild is now top of the queue post-multi-factor.** Universe-turnover-induced selection bias affects every formation-window factor. Multi-factor analysis on the current panel is informative but not final. The same analysis on the rebuilt panel will be the real answer.

**Cost-adjusted Sharpe analysis is overdue.** Two factors have claimed signals (value low-cap, low-vol high-cap) and we have not yet run the cost arithmetic on either. Until we do, both findings are academic rather than operational.

---

## Open items

1. **Universe panel rebuild.** Pull forward returns for the full set of ~2,925 stocks that ever appeared in the universe, at all 52 dates, regardless of contemporaneous in-universe membership. Apply the universe filter only at the cross-sectional sort step. Estimated work: one Tushare-pulling session for daily prices, plus a panel reconstruction script. Highest priority for the post-multi-factor phase.

2. **Cost-adjusted Sharpe analysis on value (low-cap tercile Q1-Q5 series).** Open since Session 3. Run `cost_adjusted_sharpe` at 30bps, 50bps, 70bps, 100bps round-trip costs. Decision rule: if net Sharpe stays meaningfully positive at 50-70bps, value survives realistic friction.

3. **Cost-adjusted Sharpe analysis on low-vol (high-cap tercile Q1-Q5 series).** Same procedure as value, on the new strongest signal in the project. Should be run alongside value as a paired comparison.

4. **Holm-Bonferroni correction across factor headlines.** Per the locked multi-test correction policy, HB applies to the family of factor headlines. We have applied BH within each factor's Layer 5 cap-tercile family. We have not applied HB across the four factor headlines as a family. Quick calculation: rank the four headline p-values (size, value, momentum-best, low-vol-best) and apply HB.

5. **Mid-cap tercile p=0.080 from size.** Watchlist item from Session 1-2, carried through. May be revisited with the rebuilt panel.

6. **Graduating-out hypothesis test for value's high-cap tercile null.** Open since Session 3. Test: split each quintile into "still in universe at t+1" vs "leaves universe at t+1" and compare forward returns. If leavers earn substantially more than stayers in the high-cap tercile, the graduating-out story is confirmed. Higher priority now that we have the cross-factor cap-tercile structure.

7. **ACF on factor IC time series.** `acf_band` utility built but not yet applied. If any factor's IC series shows significant autocorrelation, the bootstrap CIs we computed (block_size=3) may be optimistic. Apply to value, low-vol, and momentum IC series before multi-factor.

8. **B/M robustness check for value.** Originally planned in Session 3. Lower priority.

9. **Composite value score (EP + B/M + S/P).** Block 3 work. Lower priority than primary multi-factor analysis.

10. **Code refactor: pull `run_one_horizon`, `print_cross_horizon_table`, `save_summary_csv` into `factor_utils.py`.** Currently duplicated between momentum_analysis.py and lowvol_analysis.py. Code-cleanliness, not blocking.

11. **Documentation patch: source_ep_data.py print message.** Should say "Excluded due to missing or non-positive pe_ttm (Tushare encodes negative earnings as NaN)". Patch when next in the file.

---

## Bridge to multi-factor (next phase, separate conversation)

The multi-factor analysis will run in a fresh conversation. The user has indicated the next chat will first define what multi-factor analysis is and what forms it can take, before deciding which methodology to apply. This bridge does not commit to a specific approach; it provides the context the next chat needs to define the question well.

**Range of multi-factor approaches available, each answering a different question.**

*Composite z-score combinations.* Z-score-normalize each factor cross-sectionally per date, average (equal-weighted or with custom weights), sort on the composite. Closest to LSY-style construction. Simple and interpretable. Answers: does a combined sort produce a stronger signal than any single factor alone?

*Factor-mimicking portfolios with correlation matrix.* Construct a long-short portfolio for each factor, examine the correlation matrix of their return time-series. Answers: are the factors capturing distinct signals, or are they correlated and therefore redundant?

*Cross-sectional regression attribution (Fama-MacBeth).* Each month, regress next-month returns on the cross-section of factor exposures. The time-series of regression coefficients gives factor risk premia, with t-stats from the time-series. Standard academic methodology. Answers: which factors have independent predictive power after controlling for the others?

*Multi-factor model construction (CH-3 / CH-4 / Carhart-style).* Build an explicit factor model from our specific factors and test whether it explains anomalies in our universe. Most ambitious; closest to LSY's CH-3. Answers: does our factor combination form a model that prices observed anomalies?

The choice depends on the question. Multiple questions are simultaneously interesting (does combination help? are factors diversifying? which factors have independent power?), so the multi-factor phase may use more than one method.

**Constraints the next chat needs to know going in.**

1. **Cap-tercile structure is foundational.** Value lives in low-cap (BH-rejecting), low-vol in high-cap (BH-rejecting). Momentum and size show nothing or only weak coordination. Any multi-factor approach that ignores this segmentation will likely under-perform something that respects it. One concrete suggestion: run multi-factor combinations within each cap tercile separately, then compare across terciles.

2. **Sample size.** 51 panel dates, with effective testable dates per factor varying from 38 (mom_12_1 strict-coverage) to 51 (size, value). Multi-factor methodologies that require time-series stationarity assumptions or large-sample asymptotics should be applied with caution. Bootstrap-based inference is preferred over asymptotic where available.

3. **The data limitation persists into multi-factor.** Universe-turnover coverage problem from formation-window factors carries over. Whatever multi-factor approach is used should be designed to be re-runnable on the eventually-rebuilt panel without major changes.

4. **The four single-factor signals have very different qualities.** Value: clean, headline-significant. Low-vol: cap-conditional. Momentum and size: noisy nulls. Multi-factor combination should not weight these symmetrically; per-factor confidence (or just dropping factors with no signal) should be considered explicitly.

5. **Open items 2 and 3 (cost-adjusted Sharpe analyses) ideally run alongside multi-factor.** The actionability question is the same for the multi-factor combination as for the single factors; better to do the cost arithmetic on both as a paired comparison.

6. **Methodology consistency vs implementation consistency.** Established in this phase: same eligibility rules across factors, but per-factor implementation respects the math (median imputation for products, observed-only for std). This principle should carry into multi-factor: same combination rule across approaches, but per-method implementation respects the math of each.

**Inputs the multi-factor chat should have access to.**

- This document.
- The per-factor closeouts: Project 5 closeout, Session 1-2 closeout, Session 3 closeout.
- The codebase: `factor_utils.py`, `hypothesis_testing.py`, the per-factor wrappers, the data files.
- The CSV summaries: `momentum_horizons_summary.csv`, `lowvol_horizons_summary.csv`.
- User memory carries the bilingual protocol, plain-language style, prediction-before-running habit, and code-execution workflow (provide code only, user runs locally) automatically across chats.

**The plan after multi-factor.**

Per the user's stated trajectory: complete first-pass multi-factor analysis on the current panel; rebuild the panel with full return histories for all ts_codes that ever appeared; re-run the entire single-factor analysis on the rebuilt panel; re-run multi-factor on the rebuilt panel. The rebuild is the methodological investment that makes every subsequent result more credible. After Project 6 closes, the curriculum continues to Project 7 (Build a Backtester) and Project 8 (Strategy Evaluation & Paper Trading).
