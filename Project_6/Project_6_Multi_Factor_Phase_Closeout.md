# Project 6 — Multi-Factor Phase Closeout

**Phase focus:** Complete the multi-factor analysis chunk of Project 6. Three approaches run on the same panel: composite z-score (does combining help?), segmented long-only strategy (do factor signals translate to tradable alpha?), Fama-MacBeth cross-sectional regression (does each factor have independent predictive power?). Consolidate findings before transitioning to the panel rebuild.

**Date range covered:** Multi-factor sub-phase of Project 6, completed 2026-04-29.

**Curriculum position:** Phase 3, Project 6 (Factor Testing). This document closes the multi-factor sub-phase and Project 6 as a whole on the current panel. Project 6 will be re-run after the panel rebuild. Curriculum then continues to Project 7 (Build a Backtester) and Project 8 (Strategy Evaluation & Paper Trading).

---

## Key takeaways

1. **Pre-stimulus z_size in FMB is the only BH-rejecting cell across the entire multi-factor phase.** +0.532%/mo, t=+1.85, bootstrap p=0.039, 19 dates. Single-factor work concluded size was a noisy null. FMB controlling for value, low-vol, and momentum surfaces a size premium that single-factor missed because single-factor sorts did not strip out the contribution of the other three factors. Reconciliation: in single-factor land, size's signal was being absorbed by overlap with other factors (z_size correlates +0.285 with z_mom and -0.055 with z_lowvol). FMB's multivariate framing isolates size's marginal power. Worth flagging as the standout finding to re-test on the rebuilt panel.

2. **Pre vs post-stimulus regime sign-flip is universal across all four factors.** z_size: +0.53→-0.31. z_lowvol: +0.26→-0.26. z_value: +0.15→-0.10. z_mom: -0.28→+0.23. Pooled FMB averages these opposing signs to near-zero coefficients, which is the mechanism behind the headline null result. Operational implication: pooled-sample factor estimates in our universe average two contradictory regimes. Any strategy built on pooled estimates is approximating a 50/50 mixture of two opposite worlds, neither of which the strategy is designed to capture.

3. **Composite z-score combination dilutes rather than amplifies in our universe.** Across three horizons (vol_12_1, vol_6_1, vol_3_1), the equal-weighted z_value+z_lowvol composite was weaker than the dominant single-factor in each cap tercile. Low-cap composite -0.72%/mo vs value alone -1.10% (BH-rejecting in single-factor). High-cap composite -1.42%/mo vs lowvol alone -1.76% (BH-rejecting in single-factor). The pattern is consistent across horizons. Mechanism: in low-cap, z_lowvol contributes noise (low-vol's signal is concentrated in high-cap, not low-cap), and in high-cap, z_value contributes noise (value's signal is concentrated in low-cap). Equal-weighting noise into signal dilutes signal.

4. **The +0.404 z_lowvol vs z_mom cross-sectional correlation is the structural insight that justifies multivariate methods over univariate.** Mechanism: stocks that have moved a lot recently (winners or losers) tend to be high-volatility. With our sign convention (z_lowvol = -z(vol), z_mom = -z(mom_12_1)), "low-vol" and "recent loser" overlap structurally. FMB redistributes credit between these two correlated factors. Single-factor sorts attribute the entire effect to whichever factor is being sorted. The high-cap z_lowvol single-factor BH-rejection at p=0.009 became z_lowvol coefficient +0.45 (t=+1.09) in the high-cap FMB, with z_mom absorbing some of what z_lowvol previously got credit for. Either method is valid; they answer different questions.

5. **Long-only deployment of the cap-segmented hypothesis produced no alpha against baseline.** Segmented strategy (50% value Q5 in low-cap + 50% lowvol Q1 in high-cap) returned +1.443%/mo vs baseline +1.484%/mo. Alpha -0.041%/mo, t=-0.09, CI [-0.75, +0.61]. Every variant tested (segmented, single-factor legs, full-universe quintiles, full-universe composite) had alpha CI containing zero. Three mechanisms drove this: the universe is already a small-cap selection (baseline already captures the size premium implicit in our universe construction), regime moves dominated factor moves over the 41-month panel, and the BH-rejecting single-factor results were Q1-Q5 spreads that lose roughly half their magnitude when the short leg is removed.

6. **The cross-sectional regression R-squared in FMB at 0.046 mean / 0.029 median is normal for monthly cross-sectional return regressions.** Even with four factors of varying single-factor strength, our four factors collectively explain ~5% of cross-sectional return variance at the average date. The remaining 95% is idiosyncratic noise plus omitted factors. This is roughly consistent with academic FMB results in published equity factor work; the headline null in our coefficients is not because R² was unusually low but because coefficient time-series were noisy across our 38 testable dates.

7. **Sector neutralisation in pooled FMB barely moved any coefficient.** Headline vs sector-neutral coefficients differed by less than ±0.10%/mo for all four factors. Different from single-factor work, where momentum's effect collapsed entirely under neutralisation. Reconciliation: in single-factor, neutralisation was the only mechanism stripping sector composition from the sort, and it found that momentum was almost entirely sector composition. In FMB, including all four factors as joint regressors absorbs most of the sector overlap before residualisation gets a chance to. The two methods are complementary but capture overlapping information.

8. **Coverage compounding is the binding constraint at every layer of multi-factor work.** Composite (two factors): 21-30% coverage depending on vol horizon. FMB (four factors): 19.9% coverage, 38 testable dates. The intersection of multiple factors' eligibility-filtered observations shrinks as more factors are added. The single-factor closeout flagged the universe-turnover problem; multi-factor analysis amplifies it. Panel rebuild is the structural fix; relaxed coverage thresholds and shorter formation windows are partial workarounds at the cost of noisier individual factor estimates.

9. **Predictions vs actuals calibration this phase: directionally informed, magnitude-overconfident.** Composite: predicted "-0.50% to -1.00%/mo Q1-Q5 headline." Got -0.32% to -0.45% across horizons. Magnitude over-predicted by ~50%. Segmented: predicted "+0.4 to +1.0%/mo alpha vs baseline." Got -0.04%/mo. Direction wrong; alpha did not exist at all. The mechanism predicted (cap-tercile complementarity) was correct in single-factor land but did not translate to long-only against a cap-filtered baseline. FMB: predicted "z_value +0.30 to +0.70, t in [+1.5, +3.0]." Got +0.027, t=+0.13. Magnitude wildly off. Did not predict pre-stimulus z_size as the BH-rejecting cell; this was the surprise of the analysis. The recurring lesson: predictions made before knowing the regime structure of the data systematically over-estimate single-period coefficients on a panel where two regimes pull in opposite directions. Pre-and-post predictions, made separately, would have calibrated better.

10. **The multi-factor question has been answered as completely as this panel allows.** The four standard methods have been considered, three run (composite, segmented, FMB; FMP correlation matrix subsumed into the FMB diagnostic). Each gave a coherent answer. Composite tells us combination dilutes in our universe. Segmented tells us long-only deployment does not generate alpha. FMB tells us the only multivariate-significant cell is pre-stimulus z_size, and that the four factors collectively do not produce reliable independent premia in pooled inference. Further refinements on this panel (alternative weightings, additional factors, different formation windows) would be parameter-fiddling on noisy data. The panel rebuild is the clean methodological investment that makes any of these results trustworthy enough to act on.

---

## Reference conversations

This document consolidates the multi-factor sub-phase of Project 6. The single-factor closeout and Project 5 closeout remain canonical for their respective work and are referenced rather than duplicated here.

- **Project 5 closeout** (`Project_Five_Closeout.md`): defined the universe (1000 stocks per date, monthly rebalance by cap rank within liquidity-filtered candidates), built the forward-return panel, identified regime-event dates including 2024-09-18 PBoC stimulus.

- **Project 6 single-factor closeout** (`Project_6_Single_Factor_Phase_Closeout.md`): consolidated single-factor analysis of size, value, momentum, low-vol. Established the cap-tercile structural finding (value in low-cap BH-rejecting, low-vol in high-cap BH-rejecting, mid-cap structurally null). Established the universe-turnover problem as the binding methodological constraint. Set the multi-factor starting hypothesis: value and low-vol are operationally complementary across cap segments.

- **This document**: consolidates findings from the multi-factor sub-phase. Three analyses (composite, segmented, FMB) on the panel from Project 5, with single-factor signals from the single-factor closeout. Closes Project 6 on the current panel.

---

## Starting point (entering multi-factor phase)

Inherited from single-factor closeout:

- Hypothesis-testing toolkit (`hypothesis_testing.py`) and parametric `factor_utils.py` machinery, fully tested through size, value, momentum, low-vol.
- 51-rebalance-date forward-return panel from Project 5.
- EP data sourced from Tushare, merged into the panel.
- vol_K_S and mom_K_S helpers in `lowvol_analysis.py` and `momentum_analysis.py`, importable.
- Multi-test correction policy: Holm-Bonferroni across factor headlines, Benjamini-Hochberg within within-factor robustness families.
- Cap-tercile operational hypothesis from single-factor: value lives in low-cap, low-vol lives in high-cap, mid-cap structurally null.

User directives at start of this phase: define multi-factor analysis as a family of methods first, decide which to apply second. Equal weighting was the choice for the composite. Long-only was the choice for segmented (per 融券 constraint reasoning). All four factors were included for FMB despite size and momentum being noisy nulls in single-factor, to test "does FMB redistribute credit in ways single-factor missed?"

---

## Phase thesis

If multi-factor methods were applied to our four factors on our panel, the cap-tercile-conditional structure from single-factor should translate into a tradable strategy: combine value and low-vol within their strong segments, deploy long-only, capture an aggregate alpha. The actual results contradict this expectation. The composite dilutes the dominant single-factor in each tercile rather than amplifying it. The segmented strategy produces no alpha against baseline. FMB pooled is null on every coefficient.

The honest summary is that the single-factor BH rejections were structurally real (the underlying signals exist) but operationally fragile in our universe at our panel length. They are Q1-Q5 spreads, which lose half their magnitude when the short leg is removed. The universe is already a cap-filtered selection, so the baseline against which alpha is measured already absorbs the size premium implicit in our construction. The 41-month panel spans two distinct factor regimes whose contradictions average to near-zero in pooled inference.

The single positive finding is the pre-stimulus z_size FMB coefficient, which was the multi-factor analysis surfacing a result that single-factor sorts had missed. This is the strongest case the phase produced for FMB-style multivariate methods being non-substitutable with single-factor analysis: they answer different questions, and at least one of them surfaced a finding the other did not.

---

## Progression by analysis

### Composite z-score

Built `composite_value_lowvol_analysis.py` with cross-sectional z-scoring (winsorized at [1%, 99%] per date, then standardised), sign-aligned to "positive = expected to outperform" direction (z_value=+z(ep), z_lowvol=-z(vol)), equal-weighted sum.

Ran across three horizons. Coverage: 21.0% (vol_12_1), 27.3% (vol_6_1), 30.4% (vol_3_1). Cross-sectional correlation z_value vs z_lowvol per date: +0.227, +0.190, +0.145 respectively, declining as vol horizon shortens.

Headline Q1-Q5 across horizons: -0.317%, -0.445%, -0.194%/mo. CI contains zero in all three. IC across horizons: +0.040, +0.040, +0.034. CI excludes zero in all three (lower bound just above zero). The IC was the only statistic that meaningfully cleared inference. Sector-neutral spread was directionally consistent (-0.45 to -0.49%/mo) with substantially tightened std (3.39% to 3.56% vs 4.06%-5.20% headline) but still contained zero.

Layer 5 cap-tercile within the composite: low-cap -0.72/-0.40/+0.60%/mo across horizons (sign-unstable), high-cap -1.42/-0.90/-1.07%/mo (sign-coordinated negative, none BH-rejecting). The composite within each tercile was consistently weaker than the dominant single-factor in that tercile.

Verdict: combination did not amplify. The +0.227 cross-correlation was below the multicollinearity-trouble threshold but high enough that the composite was partially redundant universe-wide. In each cap segment, the off-segment factor contributed noise that diluted the dominant signal.

### Segmented strategy

Built `segmented_strategy.py` with seven long-only portfolios: segmented (50% value-Q5 in low-cap + 50% lowvol-Q1 in high-cap), each leg alone, value-full and lowvol-full quintiles, composite-full Q5, baseline (universe-equal-weight).

Common testable dates: 41. Stock counts per portfolio: segmented 74, baseline 998. Alpha against baseline computed per portfolio with bootstrap CI.

Every alpha CI contained zero. Segmented alpha -0.041%/mo, t=-0.09. The largest negative alpha (lowvol_full at -0.434%/mo, t=-1.25) was directionally toward "underperform baseline" but not significantly so.

Regime split: every strategy was negative pre-stimulus and positive post-stimulus, with magnitudes (-0.7 to -1.0%/mo pre, +3.5 to +4.4%/mo post) that dwarfed inter-strategy differences. Segmented Sharpe was 0.61, between the two legs (value_low_leg 0.71, lowvol_high_leg 0.50). No diversification benefit beyond simple averaging, implying the two legs were positively correlated month-to-month rather than offsetting.

Verdict: long-only deployment did not generate alpha. The mechanism was clear from the regime split. The panel's returns were ~95% regime-driven, factor-driven differentiation was lost in that signal, and the long-only versions of the BH-rejecting single-factor spreads captured at most half of the underlying spread by removing the short leg.

### Fama-MacBeth

Built `fama_macbeth.py` running cross-sectional regression of forward_return on z_value, z_lowvol, z_size (= -z(log_mcap)), z_mom (= -z(mom_12_1)) per date. Time-series of 38 sets of coefficients summarised with bootstrap CI on each.

Coverage: 19.9%, 38 testable dates after burn-in (median 272 stocks per regression). Cross-sectional correlation matrix:

| | z_value | z_lowvol | z_size | z_mom |
|---|---|---|---|---|
| z_value | 1.000 | +0.232 | +0.013 | +0.040 |
| z_lowvol | +0.232 | 1.000 | -0.055 | +0.404 |
| z_size | +0.013 | -0.055 | 1.000 | +0.285 |
| z_mom | +0.040 | +0.404 | +0.285 | 1.000 |

Max off-diagonal +0.404 (z_lowvol vs z_mom). Below 0.7 multicollinearity-trouble threshold. R-squared mean 0.046, median 0.029, std 0.048: normal range for monthly cross-sectional return regressions.

Headline pooled coefficients: z_value +0.027 (t=+0.13), z_lowvol +0.001 (t=+0.00), z_size +0.111 (t=+0.52), z_mom -0.027 (t=-0.12). All null. Intercept +1.475%/mo, t=+0.97 (close to baseline mean).

Layer 2 regime split was the most informative robustness check. Pre-stimulus (19 dates): z_size +0.532%/mo, t=+1.85, bootstrap p=0.039, BH-rejecting at α=0.05 within the family of four factors. The only such cell across the multi-factor phase. Post-stimulus (19 dates): intercept +4.499%/mo, t=+2.25, bootstrap p=0.002 (the regime moved everything together regardless of factor). Pre vs post coefficient signs reversed for every factor.

Layer 3 tradable-only filter: barely changed anything (drop rate 4.19%, the universe-level rate seen across all factors).

Layer 4 sector neutralisation: coefficients moved within ±0.10%/mo of headline; no verdict changes. Different from single-factor where neutralisation was a major diagnostic. The multivariate FMB framework already absorbs sector overlap through the cross-factor controls.

Layer 5 cap-tercile (z_size dropped due to collinearity with conditioning): no tercile produced a BH-rejecting coefficient. Largest absolute coefficient was high-cap z_lowvol at +0.45 (t=+1.09); single-factor low-vol BH-rejected at high-cap p=0.009. The reconciliation: FMB redistributed credit from z_lowvol to z_mom in high-cap (z_mom coefficient +0.242, t=+1.00 in high-cap), reflecting the +0.404 lowvol-mom correlation.

Verdict: pooled null with a regime-conditional finding (pre-stimulus z_size). The factors do not produce reliable pooled premia, but pre-stimulus z_size is the strongest single piece of evidence the multi-factor phase produced and was missed by single-factor analysis.

---

## Conceptual ground (new in this phase)

**Multi-factor analysis as a family of four distinct questions.** Composite z-score asks "does combining help?" FMP correlation asks "are the factors saying the same thing?" Fama-MacBeth asks "which factors have independent predictive power after controlling for the others?" Asset-pricing-model construction asks "does our combination explain anomalies?" The methods are not interchangeable. They answer different questions and can give different verdicts on the same data without contradiction. Confusion in the literature often comes from treating "multi-factor" as a single thing.

**Cross-sectional z-scoring as the prerequisite for combination.** Without z-scoring, "combine" is undefined when factors are in different units (EP ratio, vol stdev, log market cap, cumulative return). Z-scoring per date strips the unit and re-expresses each value as "standard deviations from cross-sectional mean." Sign convention is encoded at the z-score stage so that "positive = expected to outperform" for every factor. The composite is then a simple sum.

**Sign-convention discipline.** Wrong signs survive every statistical test (a sign-flipped composite still has zero mean and unit-ish std and looks fine numerically). The defense is documentation: state the sign convention in every script, anchor each sign in single-factor empirical findings (not literature priors), and verify by checking that the dominant single-factor's direction matches the composite's intended "good" direction.

**Composite-within-tercile vs dominant-single-factor-in-tercile as the combination-value test.** When multi-factor combination is supposed to amplify a known signal, the test is whether the composite within a strong segment beats the dominant single-factor within that segment. If it doesn't, the off-segment factor is contributing noise rather than complementary signal. This is more diagnostic than the headline composite Q1-Q5, which can be inflated or deflated by averaging across heterogeneous segments.

**Long-only alpha vs long-short spread dilution.** Q1-Q5 spreads are net of long and short legs. The long-only version captures the long leg only. If the spread is symmetric (Q5 outperforms by X, Q1 underperforms by X), the long-only version captures roughly half the spread. With our panel where single-factor BH-rejecting spreads are 1-2%/mo, the implied long-only alpha is 0.5-1%/mo, which is below the noise floor at 41-month panel length. This is structurally different from "factors don't work in our universe." The factors work as spreads, just not as long-only alphas at this sample size.

**Universe baseline absorption.** Our universe is constructed by cap rank (1000 smallest liquid stocks per date). The baseline (universe-equal-weight) already captures the size premium implicit in this construction. Strategies that attempt to add value via further size-related signals are competing against a baseline that has already taken much of the available size premium. This is the practical version of "the factor is real but the alpha is small once the appropriate baseline is chosen."

**FMB credit redistribution under correlated factors.** When two factors have correlation +0.404, single-factor sorts attribute the entire effect of each sort to the factor being sorted. FMB attributes the marginal effect after controlling for the other. The high-cap z_lowvol single-factor result became weaker in FMB because z_mom absorbed some of it. Both methods are valid; they answer different questions. Single-factor: "does this factor predict?" FMB: "does this factor predict, after controlling for the others?"

**Regime-conditional factor premia and the pooled-sample averaging problem.** Our four factors all reverse sign across the PBoC stimulus regime break. Pooled inference averages two contradictory regimes and gets near-zero coefficients. Regime-split inference recovers the pre-stimulus z_size BH-rejection that pooled missed. Implication: any method that estimates a single average coefficient across regimes systematically under-estimates regime-conditional effects. Multi-period strategies should either condition on regime or be tested per-regime as standard.

**Cross-sectional R-squared norms in equity factor regressions.** Mean 0.046, median 0.029, std 0.048 in our FMB. Roughly consistent with published academic FMB results in equity factor work. Cross-sectional return predictability is genuinely low; even sophisticated factor models rarely exceed 0.10 mean R-squared. A null FMB coefficient is not evidence that the model is mis-specified. It is evidence that the factor's marginal effect is below the noise floor at the panel's sample size.

**Multicollinearity threshold heuristics.** Below 0.5 cross-correlation, multivariate regression coefficients are stable and interpretable. 0.5-0.7, coefficients become noisier but remain interpretable. Above 0.7, coefficients become unstable, and one factor's coefficient may absorb the other's effect spuriously. Our worst correlation (+0.404) is in the safe zone but high enough that FMB's redistribution of credit between z_lowvol and z_mom is real.

---

## Skills (new code-level patterns)

**Cross-sectional z-score utility with optional winsorization.** `cross_sectional_zscore(panel, factor_col, out_col, winsorize=True, low=0.01, high=0.99)`. Per-date groupby with transform; winsorize-then-standardise pattern. Lives in `composite_value_lowvol_analysis.py`. Should be promoted to `factor_utils.py` post-rebuild.

**Sign-aligned composite construction pattern.** Build z-scores in the raw direction of each factor (z_ep, z_vol, z_logmcap, z_mom_raw), then sign-align in named columns (z_value, z_lowvol, z_size, z_mom). Composite is the simple sum. Documented sign convention in module docstring, anchored in single-factor empirical findings rather than literature priors.

**Long-only portfolio return computation per rebalance.** `long_only_return(panel, mask)`: equal-weighted forward-return mean across stocks where mask is True. Lives in `segmented_strategy.py`. Generic pattern for any long-only strategy: define mask via factor quintile / tercile / composite criterion, apply long_only_return, get a per-date return Series ready for plotting and inference.

**Alpha computation against a defined baseline with bootstrap CI.** Subtract baseline return from strategy return per date, summarise the difference series with `block_bootstrap_ci`. Standard pattern for testing alpha. Reusable for any pair of strategies (segmented vs composite, value_leg vs value_full, etc.).

**Per-date cross-sectional regression with NaN-safe least-squares.** `run_one_cross_section(df_date, factor_cols)`: drop NaN-containing rows on (factor_cols + return), fit `np.linalg.lstsq` with intercept, return coefficient dict. Skip dates with insufficient degrees of freedom. Pattern reusable for any cross-sectional regression beyond FMB.

**FMB time-series inference with bootstrap-on-coefficients.** Each factor's coefficient is a 38-element series across dates. Mean is the estimated premium, t-stat is mean/(std/sqrt(n)), bootstrap CI is from `block_bootstrap_ci` on the coefficient series. Mirrors single-factor's bootstrap-on-Q1Q5 pattern at the meta level.

**Layer-parallel design across analysis types.** Headline → Layer 2 (regime) → Layer 3 (tradable) → Layer 4 (sector-neutral) → Layer 5 (cap-tercile) is now applied uniformly to single-factor sorts, multi-factor composites, AND FMB regressions. The layers ask the same robustness questions across all analysis types; what changes is the underlying statistic being layered. This consistency is a feature: results across analysis types can be compared layer-by-layer.

**Pandas iterrows dtype-upcast gotcha.** `iterrows()` upcasts every column to a single Series dtype, so integer columns become floats and `:>7d` format codes fail. Cast explicitly with `int(row['col'])` when formatting integers from iterrows. Encountered and fixed in `print_summary_table`.

---

## Codebase

Current state of `Project_6/`:

```
Project_6/
├── data/
│   ├── universe_membership.csv
│   ├── forward_return_panel.csv
│   ├── sw_membership.csv
│   ├── ep_panel.csv
│   ├── momentum_horizons_summary.csv
│   ├── lowvol_horizons_summary.csv
│   ├── segmented_metrics.csv                  (new)
│   ├── segmented_returns.csv                  (new)
│   ├── fama_macbeth_coefficients.csv          (new)
│   └── fama_macbeth_summary.csv               (new)
├── graphs/
│   ├── (single-factor outputs from prior phase)
│   ├── composite_v_lv_quintile_cumulative_returns.png  (new)
│   ├── composite_v_lv_ic_time_series.png               (new)
│   ├── segmented_cumulative_returns.png                (new)
│   └── fama_macbeth_coefficients.png                   (new)
├── factor_utils.py
├── hypothesis_testing.py
├── source_ep_data.py
├── size_analysis.py
├── value_analysis.py
├── momentum_analysis.py
├── lowvol_analysis.py
├── composite_value_lowvol_analysis.py         (new)
├── segmented_strategy.py                      (new)
└── fama_macbeth.py                            (new)
```

Three new analysis scripts. Each follows the per-factor module pattern: imports from `factor_utils`, defines configuration constants at top, implements analysis-specific functions, runs the layered pipeline in `__main__`. Composite reuses single-factor data prep (`add_ep_to_panel`, `add_volatility_to_panel`). FMB reuses composite's `cross_sectional_zscore`. Segmented reuses both. Module reuse pattern: per-factor data prep stays in per-factor modules; cross-factor utilities (z-score, FMB engine) live in their first-use scripts and should be promoted to `factor_utils.py` on the next refactor pass.

---

## Misconceptions corrected

**"More factors in a composite always improves the signal."** Predicted before composite ran: combining two BH-rejecting single factors should produce stronger combined results than either alone. Actual: composite within each cap tercile was weaker than the dominant single-factor in that tercile. Mechanism: in our universe, the off-segment factor is genuinely noise within the tercile, not weak signal. Equal-weighting noise into signal dilutes signal. Correction: combination only amplifies when the constituent factors carry complementary information across the same observations. Segregated signals (each factor working in a different segment) are better deployed segregated than combined.

**"Long-only deployment of a BH-rejecting spread should produce roughly half the spread as alpha."** Predicted: segmented strategy alpha +0.4 to +1.0%/mo. Actual: -0.04%/mo, t=-0.09. The half-the-spread heuristic ignores baseline absorption. Our universe is already a cap-filtered selection, so the universe-equal-weight baseline already captures the size premium that an unrestricted-universe baseline (e.g., CSI 300) would not. Long-only alpha against an already-cap-filtered baseline is structurally smaller than against a market-cap-weighted baseline. Correction: alpha estimation requires a baseline that is constructed independently of the strategy's signal. Using a baseline that shares the strategy's selection biases produces under-estimated alpha.

**"Pooled FMB is the natural headline; layered FMB is robustness."** Predicted: headline FMB would surface significant value and low-vol premia consistent with single-factor BH-rejections. Actual: every headline coefficient is null; the BH-rejecting cell appears only in pre-stimulus regime split. Mechanism: regime sign-flip across all four factors averages to near-zero in pooled inference. The "headline pooled, robustness layered" framing presumes regime-stable factor behaviour. On a regime-fractured panel like ours, the layers are headline and the pooled is the artifact. Correction: in regime-fractured environments, the regime-conditional layer is the primary inference and the pooled is the diagnostic, not the reverse.

---

## Habits explicitly built

**Three-question framework before picking a multi-factor method.** "Does combining help?" → composite z-score. "Are factors saying the same thing?" → FMP correlation matrix. "Which factor has independent power?" → Fama-MacBeth. "Does the combination explain anomalies?" → asset-pricing-model construction. Every multi-factor task should explicitly identify which question it is answering before the method is chosen.

**Coverage-correlation-sanity diagnostic suite before reading layered results.** Three diagnostics run before any inference: complete-cases coverage (do we have enough data?), cross-sectional correlation matrix (multicollinearity check), per-date z-score moments (sign convention and standardisation correct?). Established in composite, carried into FMB. Failed checks invalidate the inference downstream; running them first prevents over-interpreting noise.

**Cross-horizon coordination as multi-factor-level signal-vs-noise heuristic.** Originally established in single-factor (multiple lookback windows for momentum and low-vol). Applied this phase to the composite by running three lookback choices for low-vol and comparing. Coordinated direction across horizons = signal. Sign-scattered = noise. Same heuristic, applied at the next level up.

**Compare composite-within-tercile vs single-factor-within-tercile.** The combination-value test. If the composite isn't beating the dominant single-factor within each strong segment, combination isn't doing operational work. Check this before drawing positive conclusions about a multi-factor approach.

**Long-only as the operational test, given 融券 constraints in A-shares.** Q1-Q5 spreads are tradable in principle but the short leg requires margin shorting infrastructure that is restricted, expensive, and supply-constrained in A-shares. For retail strategies, long-only is the relevant deployment, and alpha is measured against a baseline appropriate to the universe's construction.

**Regime-conditional reading as default, not robustness.** For any 41-month panel that spans the PBoC stimulus break, pooled inference averages contradictory regimes. The regime split is primary; pooled is a summary statistic that may or may not reflect the underlying structure.

**Sign convention documented at the variable level, not just the verdict level.** Every z-score column has its sign documented at construction (z_value = +z(ep), z_lowvol = -z(vol)). Sign mistakes propagate silently through every test. Naming the sign explicitly at the construction step is the only reliable defense.

**Predict before running, even on layered analyses.** Logged predictions in each script's docstring before running. This phase the predictions were systematically over-confident on magnitude and missed the regime-conditional finding (pre-stimulus z_size). Calibration data for future predictions: dial back magnitude expectations on regime-fractured panels, predict per-regime separately rather than pooled.

---

## Thesis implications

The 小盘股 trading thesis at the start of Project 6: small-cap A-shares contain exploitable inefficiencies that systematic factor analysis can surface and translate into a tradable edge.

The phase's contribution to this thesis:

The factors are real but conditional. Value lives in low-cap. Low-vol lives in high-cap. Size has a marginal premium pre-stimulus that single-factor missed. These are documented, repeatable, multi-method-robust results within the bounds of our 41-month panel.

The factors are not directly tradable in long-only form on this panel. The Q1-Q5 spreads exist; the long-only halves of them, deployed against a small-cap-baseline, produce no detectable alpha. The mechanism is well-understood: half-the-spread, baseline-absorption, regime-domination.

The cap-tercile structure is the operational finding worth carrying forward. Even if long-only deployment did not produce alpha at this sample size, the structural fact that value works in low-cap and low-vol works in high-cap is real. On a longer panel with more regime cycles, this structure becomes more reliable to act on. On the rebuilt panel, it is the primary hypothesis to re-test.

The honest summary for the thesis: small-cap A-share factor analysis at this sample size, on this panel, on this universe construction, does not produce a tradable long-only edge. The factors do produce structural signals consistent with the thesis. Whether those signals can be translated into deployable strategies requires either (a) infrastructure for long-short execution that retail A-share traders typically lack, (b) longer panels with more regime cycles to average out the pre/post-stimulus discontinuity, or (c) richer factor sets that capture currently-omitted predictability.

The thesis is not refuted; the deployment path from the thesis to a strategy on this panel is. The panel rebuild is the highest-priority next investment.

---

## Open items carried forward

1. **Single-factor open items remain.** Cost-adjusted Sharpe analyses for value's low-cap leg and low-vol's high-cap leg. Graduating-out hypothesis test for value's high-cap null. ACF on factor IC time series. B/M robustness check. None has been touched this phase.

2. **Pre-stimulus z_size FMB BH-rejection is the multi-factor finding to carry into the rebuild.** First test on the rebuilt panel: does pre-stimulus z_size still BH-reject in FMB? If yes, robust. If no, in-sample artifact.

3. **Code refactor: pull `cross_sectional_zscore` into `factor_utils.py`.** Currently lives in `composite_value_lowvol_analysis.py`. Used by `fama_macbeth.py` via cross-script import. Should be promoted before the next analysis script that needs it.

4. **Code refactor: pull `add_all_factors` into a shared multi-factor utility module.** Currently lives in `fama_macbeth.py`. Will be reused by every multi-factor analysis on the rebuilt panel. Logical home: a `multifactor_utils.py` parallel to `factor_utils.py`, or extension of the latter.

5. **Code refactor: pull FMB engine (`run_one_cross_section`, `fama_macbeth`, `summarise_coefficients`) into a shared module.** Currently lives in `fama_macbeth.py`. The same engine will be needed for every cross-sectional regression on the rebuilt panel.

6. **Documentation: pre/post-stimulus regime split should be a layer in every script.** Currently the layer is implemented in factor_utils but not always run. After the panel rebuild, the regime split should be a non-optional layer for every analysis given the universal regime sign-flip finding.

7. **Multi-test correction policy review.** Holm-Bonferroni for headlines, BH for within-factor robustness. With multi-factor analyses now in scope, the family-of-headlines is bigger (single-factor headlines + composite headlines + segmented alphas + FMB coefficients). Whether to apply Holm-Bonferroni across all of these or treat each analysis type as a separate family is a methodological choice to lock before re-running on the rebuilt panel.

8. **Cost-adjusted Sharpe for segmented and FMB-implied portfolios.** The 0.61 Sharpe on segmented is gross. Net of transaction costs (~0.1%/round-trip per trade in A-shares) and assuming monthly rebalance with ~30% portfolio turnover, the net Sharpe drops meaningfully. Quantify before any actionability conclusion.

9. **FMP correlation matrix as standalone analysis.** Subsumed into FMB's correlation diagnostic this phase but never run as the explicit "are these factors saying the same thing?" test on factor-mimicking-portfolio return series rather than cross-sectional exposures. Cheap to run, deferred to the rebuilt panel as part of the standard suite.

---

## Bridge to next phase (panel rebuild)

The panel rebuild is the highest-priority structural fix. The current panel applies the universe filter at the panel-construction step, so a stock that is in-universe at date t but not at date t-12 has no formation window data. This is what produces the universe-turnover problem and the 19.9-30% coverage rates we have been working with. The rebuild separates "what is stock X's signal at date t?" from "is stock X eligible for the cross-sectional sort at date t?" by maintaining full return histories for every ts_code that ever appeared in any month's universe, applying the universe filter only at the cross-sectional sort step.

**Specific changes from rebuild expected to flow into multi-factor results:**

Coverage will rise substantially. Composite coverage from ~21% to ~70-80%. FMB coverage from ~20% to ~60-70%. Per-date stock counts for FMB regressions from ~270 to ~600-700.

Statistical power will rise correspondingly. With 600+ stocks per regression, the cross-sectional R² may rise (more degrees of freedom, less noise per coefficient estimate). With more testable dates if the panel period is also extended, time-series inference on coefficients tightens.

The pre-stimulus z_size finding is the cleanest test of the rebuild's value. If z_size remains BH-rejecting on the rebuilt panel, the finding is robust. If it does not, the finding was an artifact of the universe-turnover-induced sample selection bias.

The cap-tercile operational finding (value in low-cap, low-vol in high-cap) is the second test. Rebuilt-panel single-factor analysis should reproduce this structure. If it does, the multi-factor segmented strategy should be re-run on the rebuild and may show alpha that the current panel could not surface.

**Plan after rebuild:**

1. Single-factor re-run on rebuilt panel (size, value, momentum, low-vol). Same 5-layer machinery. Compare verdicts to current panel; document which findings were universe-turnover artifacts.

2. Multi-factor re-run on rebuilt panel: composite, segmented, FMB. Same scripts with `MIN_COVERAGE` and panel path possibly adjusted.

3. New: FMP correlation matrix as an explicit standalone analysis. Cheap to run, was deferred this phase to focus on segmented and FMB. Should be the explicit Question-2 answer on the rebuilt panel.

4. New: segmented strategy with per-tercile FMB-implied weights instead of equal weights. The pre-stimulus z_size finding suggests size has marginal predictive power that the equal-weighted segmented strategy does not exploit; FMB-weighted segmented might. Premature on the current panel; cleaner on the rebuild.

5. Cost-adjusted Sharpe analysis on every BH-rejecting cell, single-factor and multi-factor. Now overdue.

After the rebuilt-panel re-runs, Project 6 closes properly and the curriculum proceeds to Project 7 (Build a Backtester) and Project 8 (Strategy Evaluation & Paper Trading). Project 7 will be the natural home for any actionable strategy that survives both the rebuild and the cost-adjustment.
