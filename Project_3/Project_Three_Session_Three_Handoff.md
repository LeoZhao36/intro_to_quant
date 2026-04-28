# Project 3 Session 3 Handoff: Hypothesis Testing with statsmodels, HC3 Robust Standard Errors, and the 震元-vs-工商 Sign Flip

**Completed:** 2026-04-21
**Session location:** Phase 2, Project 3 (Correlation and Regression), Session 3
**Status:** Closed. Ready for Session 4 (autocorrelation of returns, ACF, information-diffusion mechanism on returns directly).

---

## Key takeaways

- **t-statistic, p-value, and 95% confidence interval are three presentations of one underlying fact.** Each asks "where does the point estimate sit relative to the noise band around zero?" in different units. They always agree numerically because they are built from the same pieces. Any OLS summary gives all three; reading any one gives the other two.
- **p-value = Prob(data at least this extreme | null true), not Prob(null true | data).** The semantic precision that trips up most finance writing. A p of 0.207 does not mean "there is a 79% chance the signal is real." It means "if the signal were exactly zero, data this noisy-looking would appear about 21% of the time by chance alone."
- **Classical OLS standard errors assume constant residual variance (homoskedasticity). When that assumption fails, classical SE is wrong and HC3 robust SE is the correction.** The spread between classical and robust SEs measures how assumption-dependent your inference is. Small spread means the assumption did not matter; the result is robust. Large spread means the result depends heavily on the assumption and should be discounted accordingly.
- **震元 volume signal under proper inference: not distinguishable from zero.** Classical p = 0.067 suggested borderline significance. After BP rejection (p = 0.015) of homoskedasticity and HC3 refit, the p-value rose to 0.207 and the 95% CI widened to [-0.002, 0.010], containing zero comfortably. The Session 2 heteroskedasticity ambiguity resolves as: real heteroskedasticity existed, and correcting for it weakens rather than strengthens the signal.
- **The HC3 direction prediction was wrong.** I sketched "HC3 should give smaller SE because Session 2's residual plot showed narrowing at high vol_ratio, which would mean classical SE is conservative." The data rejected that reasoning. HC3 came out larger, not smaller. Calibration lesson: BP rejection tells you classical SE is wrong, but not which direction. Visual narrowing on a sparse tail does not integrate across the full range the way the BP+HC3 formulas do. Commit weaker priors on multi-mechanism questions.
- **震元 and 工商 show opposite signs on the same regression.** 震元 slope +0.0039, 工商 slope -0.0034. This is the most informative finding of the session. It suggests the volume-return relationship is mechanically different in small-caps vs large-caps (slow information diffusion producing positive drift vs flow-driven mean reversion producing negative drift), not a weaker version of the same mechanism. This becomes a specific Project 5 hypothesis worth testing on 30+ stocks per bucket.
- **工商 residuals are effectively homoskedastic (BP p = 0.104); 震元's are not (BP p = 0.015).** Consistent with small-caps having episodic volatility clustering around news catalysts and 涨跌停 events, while large-caps have more stable residual variance from diversified information flow. Generalizes as a Project 5 prediction.
- **The 0.05 to 0.10 p-value band is the single most dangerous zone in empirical finance.** Specification changes, outlier handling, robust SE choice, multiple-testing adjustments, or subsample variation all routinely flip results in this band across the significance threshold. Results in this band are not evidence; they are invitations to replicate. The replication crisis in social science is mostly a catalog of results that came in at p = 0.02 to p = 0.08 and did not hold up.
- **Borderline-significant-but-economically-ambiguous is the structural profile of strategies that look tradeable on paper and die to costs plus sample variance in live deployment.** Both 震元 and 工商 fits sit in this profile in 2024. Neither is ready for any actionable conclusion beyond "candidate for cross-sectional testing in Project 5."

---

## Reference conversations and documents

- Previous session: `2026-04-21 — Project 3 Session 2: Scatter Plots, Regression Lines, R² Identity, and Residual Analysis on the 震元 Volume Signal` → `Project_Three_Session_Two_Handoff.md`
- This session's conversation: `2026-04-21 — Project 3 Session 3: Hypothesis Testing with statsmodels, HC3 Robust Standard Errors, and the 震元-vs-工商 Sign Flip` → this document
- Next session: `Project_Three_Session_Four_Handoff.md` (to be created)

---

## Starting point

I entered Session 3 with slope = 0.0039, R² = 0.015 from Session 2, a partial understanding of what p-values measure (introduced informally in the Session 2 follow-up), no practical experience with statsmodels, and the unresolved question from Session 2 on whether the 震元 residuals were heteroskedastic or whether the apparent narrowing was sample-size artifact. The session's job was to move the 震元 signal through the full inferential pipeline (classical OLS with proper SE, formal residual diagnostics, robust refit) and to arrive at an honest verdict on whether the descriptively-present volume signal is inferentially supported.

---

## Session 3 thesis

Correlation describes, regression fits, inference decides. Session 3 is the inference step. The mechanical content is statsmodels.OLS and its diagnostic output. The conceptual content is the null-hypothesis framework and its three equivalent presentations (t-statistic, p-value, CI). The empirical content is the resolution of the 震元 signal's inferential status and a contrast case in 工商 that tests whether the mechanism story is about the information-diffusion story specifically or about a common underlying dynamic.

---

## Progression through the session

### Opening housekeeping

Two carry-forward audits from Session 2's open list were flagged at the top of the session: the data-loading bug check in Session 1's notebook, and the Sortino formula audit in risk_toolkit.py from Project 2. Both are brief and do not require tutoring. Both deferred for independent completion. Neither worked on during the live session.

### Hypothesis testing vocabulary, intuition before formulas

The core frame: we have one sample of 240ish observations, giving one slope estimate. If we could rerun 2024 with different random luck, we would get different slope estimates each time. The question "is the true slope zero?" cannot be answered from one sample directly. It is answered by asking: if the true slope were zero, how often would pure sampling luck produce an estimate like the one we got?

Five connected concepts:

**Null hypothesis (H₀).** A specific, testable version of "nothing is going on." Set up on purpose so you can try to knock it down. Never proven false; only measured as hard-to-keep-believing.

**Standard error.** How much the slope estimate would vary across hypothetical replays of the sample. Your measure of how precisely one sample pins down the answer. Calculated from the sample itself via a formula that assumes certain things about residual behavior.

**t-statistic (z in large samples or under HC3).** Slope divided by SE. Measures how many noise-widths from zero the estimate sits. Rough calibration: |t| < 1.0 means indistinguishable, |t| ≈ 1.96 means borderline conventional significance, |t| ≈ 2.58 means strong evidence, |t| ≈ 3.3 means very strong evidence.

**p-value.** Two-tailed area under the null distribution beyond |t|. The probability of seeing data at least as extreme as yours if the null were true. Small p means the data is surprising under the null; large p means it is consistent with the null. Never the probability that the null is true.

**Confidence interval.** The range of true-slope values not obviously inconsistent with the data. 95% CI roughly equals slope ± 1.96 × SE. Contains zero iff p > 0.05.

### statsmodels.OLS on 震元, classical fit

Refit the Session 2 regression using `sm.add_constant(x)` and `sm.OLS(y, X).fit()`, read the full `.summary()` output.

```
                 coef    std err          t      P>|t|      [0.025      0.975]
const         -0.0038      0.003     -1.361      0.175      -0.009       0.002
vol_ratio      0.0039      0.002      1.837      0.067      -0.000       0.008
```

The slope matched Session 2's 0.0039 to four decimals, validating that the statsmodels fit is the same underlying OLS as np.polyfit plus richer output. N = 222 reflects 20 observations lost to the rolling-window warmup and 1 to shift(-1).

The three equivalent presentations: t = 1.837, p = 0.067, 95% CI = [-0.000, 0.008] containing zero at its lower bound by a sliver. Borderline suggestive under classical assumptions.

Residual diagnostic block from the same summary:
- Durbin-Watson 2.088: no residual autocorrelation, one assumption cleared.
- Omnibus p ≈ 0, Jarque-Bera p = 1.13e-10: residuals reject normality decisively. Expected given Project 1 Session 5. Moderately bad for inference at small N; mostly absorbed by CLT at N = 222.
- Residual skew -0.009, kurtosis 5.225 (raw, not excess): cross-validated against Session 2's manual calculation. Confirms the bulk-vs-tails finding that the line absorbed the skew but not the kurtosis.

### Breusch-Pagan test on 震元 residuals

```
Breusch-Pagan LM: 5.9262, p: 0.0149
```

Formal rejection of homoskedasticity. The Session 2 narrowing pattern was real structure, not sample-size artifact. BP at N = 222 has enough power to detect variance-predictor relationships that the sparse-tail visual could not confirm on its own. Classical SE formula is wrong, HC3 refit required.

### HC3 robust refit on 震元

```
                 coef    std err          z      P>|z|      [0.025      0.975]
const         -0.0038      0.003     -1.196      0.232      -0.010       0.002
vol_ratio      0.0039      0.003      1.262      0.207      -0.002       0.010
```

The point estimate is unchanged (HC3 does not move the slope). The SE grew from 0.002 to 0.003 (about 50% larger). The t-stat fell from 1.84 to 1.26. The p-value rose from 0.067 to 0.207. The 95% CI widened from [-0.000, 0.008] to [-0.002, 0.010], containing zero comfortably.

Failed pre-fit prediction: I sketched that HC3 should give a smaller SE based on Session 2's visual narrowing at high vol_ratio being read as high-leverage low-variance observations. The data rejected this reasoning. The actual heteroskedasticity pattern is different from the sparse-tail visual; BP and HC3 integrate across the full range in a way that eyeballing cannot. The correction went the opposite direction from my prior.

Calibration consequence: BP rejection tells you classical SE is wrong; it does not tell you which direction the correction goes. Multiple candidate patterns of residual-variance structure can produce BP rejection with opposite HC3 implications. Until the robust refit runs, treat the direction as genuinely uncertain.

### Plain-language consolidation

Mid-session request to restate all statistics concepts in non-technical language. Fifteen concepts walked through: regression setup, slope, R², residuals, the four moments, normal distribution and why returns aren't, null hypothesis, standard error, t-statistic, p-value, confidence interval, classical vs robust SEs, heteroskedasticity, Breusch-Pagan, Durbin-Watson, Jarque-Bera and Omnibus. The consolidation is in the conversation transcript; no separate artifact produced. Worth treating the transcript section itself as the reference document for this vocabulary.

### 工商 large-cap comparison

Ran the same regression on 工商银行 to test whether the information-diffusion mechanism (which should be weak or absent in a heavily institutional, heavily analysed, fast-information-flow large-cap) produces a measurably different result from 震元.

Pre-fit predictions committed:
1. Slope magnitude: lower (mechanism predicts smaller; confounders muddy the direction).
2. Classical p-value: between 0.05 and 0.5, weak.
3. Breusch-Pagan: no heteroskedasticity (large-cap residual variance should be steadier).

Results:
```
工商 Classical:
                 coef    std err          t      P>|t|      [0.025      0.975]
const          0.0051      0.002      2.129      0.034       0.000       0.010
vol_ratio     -0.0034      0.002     -1.555      0.121      -0.008       0.001

Breusch-Pagan LM: 2.6413, p: 0.1041

工商 HC3:
                 coef    std err          z      P>|z|      [0.025      0.975]
const          0.0051      0.002      2.282      0.022       0.001       0.010
vol_ratio     -0.0034      0.002     -1.545      0.122      -0.008       0.001
```

Scoring:
1. Slope magnitude: half-right. Similar magnitude, not meaningfully smaller.
2. p-value between 0.05 and 0.5: hit (0.121).
3. BP homoskedastic: hit on direction (p = 0.104, above 0.10 threshold though marginally). Classical and HC3 SEs are essentially identical, confirming inference is assumption-robust for this pair.

The unexpected finding is the sign flip. 震元 positive slope, 工商 negative slope. This was not in any of the pre-fit predictions and is the most informative outcome of the comparison.

### The sign flip and its mechanism implications

Three candidate mechanisms for large-cap volume → negative next-day return:

**Mean reversion on flow imbalances.** Large-caps are heavily market-made. Volume spikes often reflect directional institutional flows (ETF creation/redemption, sector rotation, macro rebalancing). Market makers absorb part of the flow into inventory at prices that move with the flow, then unwind inventory back to neutral over the following session, which pushes price in the opposite direction. Produces a systematic mean-reversion pattern on volume-spike days.

**Overreaction on sentiment-driven volume.** Large-cap volume in 2024 clustered around policy announcements. Retail-driven sentiment shifts tend to overshoot, and the overshoot corrects over subsequent sessions. If high-volume days in 工商 are disproportionately sentiment-driven rather than information-driven, the next-day correction produces a negative slope on volume ratio.

**Coincidence.** 2024 had a specific rally-correction-rally sequence for Chinese banks tied to policy events. Without multi-year data, the slope could be an accidental artifact of which days happened to be high-volume.

The key implication: the mechanism story is not "same signal, weaker in large-caps." It is "different signals, different mechanisms." If this replicates population-level, it becomes a clean factor-model finding. If it does not, it dissolves as sample coincidence. Either way, the single-pair contrast produces a specific testable Project 5 hypothesis.

### Comparison table

| | 震元 (小盘) | 工商 (大盘) |
|---|---|---|
| Slope | +0.0039 | -0.0034 |
| Classical SE | 0.002 | 0.002 |
| Classical p | 0.067 | 0.121 |
| HC3 SE | 0.003 | 0.002 |
| HC3 p | 0.207 | 0.122 |
| BP p | 0.015 | 0.104 |
| Durbin-Watson | 2.09 | 2.11 |
| R² | 0.015 | 0.011 |
| Residual kurtosis (raw) | 5.2 | 4.3 |

---

## Conceptual ground consolidated

**Hypothesis testing is the shift from descriptive to inferential statistics.** Description asks what your sample looks like. Inference asks what your sample tells you about the world that produced it. The machinery: null hypothesis as target, SE as noise measure, t-statistic as distance from null in noise-widths, p-value and CI as equivalent presentations of how hard the null is to keep believing.

**Every OLS summary contains five fit-quality numbers.** Residuals (per-observation, inspectable), slope (real-unit response), R² (aggregate variance explained), p-value on slope (signal-vs-noise separation), confidence interval on slope (range of plausible true values). Economic significance lives mostly in slope; statistical significance lives in p-value and CI. Both always needed.

**Classical OLS SEs assume homoskedasticity and independence of residuals.** When either assumption fails, the SE formula produces the wrong number, and every downstream inference (t, p, CI) is also wrong. BP tests the first assumption; Durbin-Watson screens the second. HC3 corrects for heteroskedasticity. HAC/Newey-West corrects for both. Cluster-robust SEs handle grouped data (relevant for Phase 3 cross-sectional panel regressions).

**The spread between classical and robust SEs measures assumption dependence.** Agreement = inference is robust, trust the number. Divergence = inference hinges on an assumption that may not hold, discount the result. Applies beyond heteroskedasticity to any robustness check (outlier handling, subsample stability, alternative specifications). The spread is the real information.

**BP rejection does not determine HC3 direction.** The test asks "does residual variance change with the predictor?" Yes or no. It does not ask "in which way does it change, and what does that imply for leverage-weighted SE?" The HC3 formula integrates over the full joint distribution of (leverage, residual variance), which the eye cannot do from a scatter plot. Mechanism reasoning is useful for directional guesses but insufficient for multi-mechanism questions; commit weaker priors in those cases.

**The 0.05-0.10 p-value band is the single most dangerous zone in empirical finance.** Specification changes routinely flip results in this band. The replication crisis documents this across disciplines. Results in this band are invitations to replicate, not evidence of effects.

**statsmodels uses raw kurtosis (3 = normal), unlike pandas which uses excess kurtosis (0 = normal).** Convention varies by library. Check documentation each time. The raw value of 5.225 for 震元 residuals equals the excess value of 2.225 computed manually, matching Session 2.

**Sign matters as much as magnitude in cross-asset regression comparisons.** The 震元-vs-工商 sign flip is more diagnostic than the magnitude comparison would have been. Future cross-asset comparisons should always check sign first, then magnitude.

---

## Technical skills acquired

**Production-ready fluency, without reference:**

- Fit OLS via `sm.add_constant(x)` + `sm.OLS(y, X).fit()` + `.summary()`.
- Read the statsmodels summary in three blocks: overall model fit, coefficients table (coef/SE/t/p/CI), residual diagnostics (DW, JB, skew, kurtosis).
- Run `het_breuschpagan(results.resid, results.model.exog)` and interpret the LM p-value.
- Refit with `fit(cov_type='HC3')` and read the updated SE, z-stat, p-value, and CI.
- Compare classical and HC3 outputs to assess assumption dependence.

**Working fluency, light reference:**

- Distinguish HC0/HC1/HC2/HC3 family (HC3 is modern default for small samples).
- Distinguish HC family (heteroskedasticity only) from HAC/Newey-West (heteroskedasticity + serial correlation) and cluster-robust (grouped data).
- Use Durbin-Watson as a quick screen (1.5-2.5 acceptable range).
- Interpret the Omnibus and Jarque-Bera output as residual-normality checks.
- Recognize the raw-vs-excess kurtosis convention difference across libraries.

**Vocabulary now fluent:**

- Null hypothesis, alternative hypothesis, test statistic, standard error, t-statistic, p-value, confidence interval, significance level, rejection region.
- Heteroskedasticity, homoskedasticity, Breusch-Pagan, White (HC0/HC1), HC2, HC3, sandwich estimator.
- Durbin-Watson, Omnibus test, Jarque-Bera (in regression residual context).
- Classical vs robust SE, assumption robustness, specification sensitivity.

---

## Codebase now in the project

```
project_three/
  utils.py                         # Unchanged
  risk_toolkit.py                  # Unchanged (Sortino audit still pending)
  plot_setup.py                    # Unchanged
  data/
    prices/                        # Same 6-stock 2024 cache; 工商 already cached
  Session_One.ipynb                # Pearson, Spearman, flow-rotation
  Session_Two.ipynb                # Scatter, regression lines, residuals
  Session_Three.ipynb              # This session: statsmodels, BP, HC3, 工商 comparison
```

`Session_Three.ipynb` contents:

1. Imports, data loading for 震元 (with the Session 2 set_index bug fix applied).
2. Classical OLS fit on 震元 via statsmodels, full summary output.
3. Breusch-Pagan test; formal rejection.
4. HC3 refit; SE widening, p-value increase, CI now including zero.
5. Parallel block for 工商: classical fit, BP test, HC3 refit.
6. Comparison table of 震元 vs 工商 across classical/HC3 slopes, SEs, p-values, BP p, DW, R², residual kurtosis.

No helpers promoted to `project3_utils.py` this session. The fit-BP-HC3 sequence was used twice (once per stock) and would reach rule of three if Session 4 does the same for a third pair. At that point it becomes worth writing a `fit_with_diagnostics(y, x)` helper that returns classical results, BP output, and HC3 results in one call.

---

## Misconceptions corrected and what replaced them

**"HC3 should produce smaller SE than classical because Session 2's residual plot showed narrowing at high vol_ratio."** Replaced with: visual narrowing on a sparse tail does not determine the HC3 correction direction. BP and HC3 integrate across the full joint distribution of leverage and residual variance, which the eye cannot do. Multi-mechanism questions deserve weaker priors than single-mechanism ones.

**"p-value of 0.067 is borderline-but-suggestive evidence of a real signal."** Replaced with: a borderline classical p on a fit with rejected homoskedasticity is evidence that the classical formula is wrong, not evidence of a signal. The proper reading after HC3 correction is p = 0.207, which is simply not significant.

**"Small-cap volume signal is stronger than large-cap volume signal."** Replaced with: the two signals have opposite signs. This is a categorical difference in mechanism, not a magnitude difference in the same mechanism. The small-vs-large comparison needs to be reframed as "different mechanisms, test each separately" rather than "same mechanism, test strength."

**"p-value is the probability that the null is true."** The persistent semantic confusion. Replaced with: Prob(data | null true), not Prob(null true | data). Different conditionals, different things. A p of 0.207 is not a 79% confidence that the effect is real.

**"Statistical significance implies the signal is tradeable."** Replaced with: statistical significance tests separation from noise; tradability requires the predicted effect to exceed transaction costs plus implementation slippage at a turnover the strategy demands. Session 2 already surfaced this for 震元 at slope 0.0039; Session 3 reinforces it with the additional observation that inference that collapses under proper SE cannot sustain any economic claim.

---

## Habits explicitly built

**Run classical, BP, and HC3 as a standard three-step package on any regression where inference matters.** Not optional. The classical output is incomplete without the assumption check, and the assumption check is incomplete without the robust refit when the check rejects. Phase 3 factor model regressions will use this pattern routinely.

**Compare classical and robust outputs side by side.** The spread is the information. Agreement means the inference is assumption-robust; divergence means it depends on the assumption and should be discounted. This generalizes to other robustness checks: subsample stability, outlier handling, alternative specifications, multiple-testing adjustments.

**Check sign before magnitude in cross-asset regression comparisons.** Sign differences reflect mechanism differences and deserve attention before magnitude discussion. The 震元-vs-工商 comparison would have been read quite differently if it were scanned only for magnitude.

**Commit weaker priors on multi-mechanism questions.** HC3 direction, signs on new regressions, and heteroskedasticity patterns can go either way depending on which of several candidate mechanisms dominates. The error in the HC3 direction prediction was not a reasoning failure; it was an overconfidence calibration failure. Better prior for this class of question: weakly one-sided with explicit acknowledgment that either direction is live.

**Treat the 0.05-0.10 p-value band as a signal to replicate, not a signal to act.** Any strategy built on a p-value in this range is building on a foundation that will likely shift when specifications change. Flag and defer to out-of-sample or cross-sectional verification.

---

## Implications for the 小盘股 thesis

Defensible from Session 3 data:

- The 震元 volume signal is descriptively real in 2024 but inferentially not supported when properly corrected for heteroskedasticity. Classical p = 0.067, robust p = 0.207, 95% CI contains zero comfortably. Single-stock, single-year evidence is not strong enough to discriminate the signal from noise.
- 震元 residuals exhibit statistically detectable heteroskedasticity (BP p = 0.015); 工商 residuals do not at conventional levels (BP p = 0.104). Consistent with small-cap episodic volatility clustering vs large-cap stable residual variance.
- The sign flip between 震元 (+0.0039) and 工商 (-0.0034) is informative at the mechanism level. Small-cap volume-return slopes may be dominated by slow information diffusion (positive); large-cap volume-return slopes may be dominated by flow mean-reversion or sentiment overshoot (negative). These are different mechanisms with different signs, not a shared mechanism with different strengths.
- 工商's R² of 0.011 and slope of -0.0034 are both smaller in magnitude than 震元's, consistent with large-caps being closer to weak-form efficient on short horizons.
- Neither signal is tradeable at single-stock scale in 2024 by any statistical standard that accounts for costs and realistic execution.

Not supported by Session 3 data:

- "The information-diffusion mechanism is validated for 震元." Consistency with the mechanism is weaker than confirmation; mean-reversion on flow, overreaction on sentiment, limit-dynamics, and year-specific coincidence remain alive as competing explanations.
- "Small-cap volume signal is stronger than large-cap volume signal." Different signs prevent a clean magnitude comparison. The two are not directly comparable on a strength axis.
- "BP rejection on 震元 means the signal is real after correction." BP rejects homoskedasticity, which weakens the inference, not strengthens it. The HC3 p-value rose rather than falling.

Specific Project 5 hypothesis worth carrying forward:

In a cross-sectional regression of next-day returns on abnormal volume, pooled across 30+ stocks and 3+ years, with size-bucket interaction, the slope on abnormal volume should be significantly positive in the small-cap bucket and significantly negative (or significantly less positive) in the large-cap bucket. The mechanism-implied prediction is a qualitative sign difference across size buckets, not a quantitative magnitude difference within one sign.

---

## Open items carried forward

**Data-loading bug audit.** Flagged in Session 2, still pending at Session 3 open, still pending at Session 3 close. 5-minute diagnostic on Session 1's notebook to verify whether the `set_index('date')` call was silently broken or whether cached-data format changed between sessions. Worth clearing at Session 4 open.

**Sortino formula audit from Project 2.** Still pending after four sessions. 2-minute check on `risk_toolkit.py`: confirm Sortino denominator uses `sqrt(mean(min(r - MAR, 0)**2))` rather than `std(returns[returns < 0])`. Clear at Session 4 open.

**Fit-BP-HC3 helper.** Used twice in Session 3 (震元, 工商). Rule of three met on next use. Worth writing as `fit_with_diagnostics(y, x)` returning a dict of classical_results, bp_stat, bp_pvalue, hc3_results when Session 4 reaches for the same pattern.

**Cross-sectional test of volume signal.** Single-pair (震元, 工商) contrast is descriptive, not a population-level claim. Full test belongs in Project 5: regress next-day returns on abnormal volume pooled across 30+ small-caps and 30+ large-caps over 3+ years, interact with size bucket, test whether the small-cap bucket shows significantly positive slope and the large-cap bucket shows significantly non-positive slope.

**Multi-year replication of 震元 pattern.** The 2024-only finding is regime-specific. 2022-2023 data is already cached from Project 1 Session 4; a multi-year rerun is cheap and would test regime stability. Deferred but not gated on Session 4.

**Sign-flip hypothesis formalization.** The 震元-vs-工商 sign flip is the session's most interesting finding. Worth carrying forward as a specific, testable Project 5 prediction rather than a general intuition: "expect qualitative sign difference across size buckets in cross-sectional volume-return regression, mechanism-implied direction positive for small-caps and negative for large-caps."

**Economic significance framing.** Slopes of 0.0039 and -0.0034 translate to 40-80bp per-day predicted returns at moderate volume ratios. Above retail round-trip costs in principle. The question "at what threshold execution does this signal clear costs with a meaningful sample of trades" is deferred to Phase 4's backtester once a validated population-level signal exists to backtest.

---

## Bridge to Session 4

Session 4 is autocorrelation of returns, tested with the ACF framework and formal significance bands. The mechanism link is direct: if small-caps have slow information diffusion, returns themselves should show lag-1, lag-2, or short-horizon positive autocorrelation, detectable in the ACF plot. The volume-return regression of Sessions 2-3 was a proxy test of the same mechanism through a different channel. Session 4 is the direct test.

Technical content: `statsmodels.graphics.tsaplots.plot_acf`, the 95% confidence band around zero autocorrelation, Ljung-Box test as a joint test across multiple lags. The ACF confidence bands are the first-order equivalent of the single-lag t-test the user now has the framework to understand. Ljung-Box is a first encounter with multi-lag joint testing that sets up Project 4's multiple-testing problem.

Empirical content: run ACF on 震元 and 工商 2024 return series. The mechanism-implied prediction is detectable positive lag-1 or lag-2 autocorrelation in 震元 returns, and essentially no autocorrelation in 工商 returns. The same interpretive tensions apply (single-stock single-year is not a population-level test), but Session 4 establishes the framework for the Project 5 cross-sectional test.

Natural close-to-open: Session 3 leaves you with one validated framework (classical + BP + HC3) for single-predictor regression inference, and one open question (does the volume-return relationship survive cross-sectionally, and does the sign-flip pattern hold population-level). Session 4 extends the framework to autocorrelation in time series and gives you a second channel through which to test the information-diffusion mechanism. Project 4 then formalizes hypothesis testing into the full toolkit including multiple-testing correction, and Project 5 applies the whole apparatus cross-sectionally where the statistical power lives.

---

Session 3 closed. Suggested conversation name: `2026-04-21 — Project 3 Session 3: Hypothesis Testing with statsmodels, HC3 Robust Standard Errors, and the 震元-vs-工商 Sign Flip`.
