# Project 3 Session 2 Handoff: Scatter Plots, Regression Lines, R² Identity, and Residual Analysis on the 震元 Volume Signal

**Completed:** 2026-04-21
**Session location:** Phase 2, Project 3 (Correlation and Regression), Session 2
**Status:** Closed. Ready for Session 3 (Simple linear regression with statsmodels, p-values, formal OLS output).

---

## Key takeaways

- **R² = ρ² for simple linear regression.** Verified numerically to four decimals on all three pairs. Two independently defined quantities converge on the same number because for one-predictor regression, the line's explanatory power is mathematically equivalent to the squared correlation. This identity breaks the moment a second predictor enters (multiple regression in Phase 3).
- **Slope carries information ρ does not.** slope = ρ × (σ_y / σ_x). ρ is the unitless screening statistic; slope is the real-unit hedge ratio. Two pairs with identical ρ can have different slopes if their variance ratios differ. 工商 × 震元 has ρ = −0.088 but slope = −0.187 because 震元's daily vol is roughly twice 工商's.
- **The eye stops detecting tilt around |ρ| ≈ 0.3.** Below that threshold, scatter plots look like shapeless blobs even when the correlation is statistically real. ρ = 0.123 sits below this eye-threshold, which is one reason the 震元 volume signal needs formal tools rather than eyeball interpretation.
- **R² and residuals are different levels of aggregation, not competing metrics.** Residuals are the per-observation raw material (one per day). R² is the aggregate summary computed from them (one per fit). Two regressions with identical R² can show completely different residual patterns. R² for summary, residuals for diagnosis.
- **A small-R² signal can still do real work on higher moments.** The 震元 residual skew dropped from +0.117 to −0.009 even though R² was only 1.5%. When the signal lives in the tails rather than the bulk (high-volume days → positive next-day returns), a low-R² line can absorb most of the asymmetry. "Weak by R²" is not "useless for all purposes."
- **Linear regression is a bulk-fitting tool and cannot thin fat tails.** Residual kurtosis barely moved (2.30 vs 2.25). Extreme days survive the regression essentially untouched. Strategies depending on tail behavior need different tools, which is where Phase 4 ends up.
- **Economic significance is distinct from statistical significance.** At vol_ratio = 3, the 震元 regression predicts +0.8% next-day return, above retail round-trip costs. But R² = 0.015 means per-trade residual noise is ≈ 2.6%, essentially unchanged from y's unconditional std. Edge lives only in expectation across many trades. This is the structural profile of strategies that look tradeable on paper and quietly die to costs plus sample variance in live deployment.
- **Interview mechanism recalibrated.** User gave direct feedback mid-session that probing should happen for substantive or non-obvious intuitions but not for routine applications of understood concepts. Memory updated. Default bias moved from "over-probe to be thorough" to "under-probe and trust the user to ask if they need scaffolding." This applies to every future session.

---

## Reference conversations and documents

- Previous session: `2026-04-21 — Project 3 Session 1: Pearson, Spearman, and Flow-Rotation Correlation in the Six-Stock Basket` → `Project_Three_Session_One_Handoff.md`
- This session's conversation: `2026-04-21 — Project 3 Session 2: Scatter Plots, Regression Lines, R² Identity, and Residual Analysis on the 震元 Volume Signal` → this document
- Next session: `Project_Three_Session_Three_Handoff.md` (to be created)

---

## Starting point

I entered Session 2 with the correlation toolkit from Session 1 (Pearson, Spearman, the gap as diagnostic, flow-rotation as a mechanism, conditional-means verification) and one loose thread: the 震元 volume ratio → next-day return relationship at ρ = +0.118, flagged as descriptively real but not tradeable at single-stock scale. The session's job was to move that thread from "correlation number" to "fitted model with inspectable residuals and an explicit variance-explained fraction," while also building the broader regression toolkit that factor models in Phase 3 depend on.

What I did not have going in: any practical experience fitting regression lines in Python, no distinction between slope as hedge ratio and ρ as screening statistic, no formal definition of R², no residual plots as a diagnostic tool, and only informal exposure to the idea that R² and residuals describe different things.

---

## Session 2 thesis

Correlation describes a relationship; regression fits a model to it. The step between them is where factor thinking starts. Session 2's structure: build visual intuition for what different ρ values look like as scatter plots (calibration), fit explicit regression lines and verify the R² = ρ² identity numerically (machinery), then inspect residuals to see what the fit did and did not do (diagnosis). The 震元 volume signal ran as the through-line because it was the session's one economically relevant application and the natural target for every tool introduced.

---

## Progression through the session

### Meta: interview mechanism recalibration

Early in the session I probed visual-calibration priors in more depth than warranted for a well-understood concept (scatter plot shape at different ρ values). User gave direct feedback: probe for genuinely non-obvious intuitions, skip probing for routine applications. Memory was updated mid-session (edit #2 now reads, in part, "Default to moving fast when uncertain; user prefers under-probing to over-probing"). This is a calibration point for every future session, not a one-off fix.

### Exercise 1: visual calibration of three pairs

Made A/B predictions before running code. Binary shape call plus direction:

- **招商 × 平安 (ρ = +0.813): A, upward tilt.** Confirmed. The bottom-left crash-day dot at roughly (−0.08, −0.10) and the top-right rally cluster both sit along the tilt rather than perpendicular to it, which is why the Session 1 Pearson-Spearman gap on this pair was small (0.045). Outliers reinforcing the correlation rather than distorting it.
- **震元 vol × next-day ret (ρ = +0.123): B, blob.** Confirmed at the aggregate level, with one important detail the blob-prediction missed: the left 80% of the mass (vol_ratio 0.5 to 2) was symmetric around zero; the right 20% (vol_ratio 3+) skewed upward. The ρ was not driven by uniform tilt across the cloud but by asymmetry in the right tail. This prefigures the residual-skew finding in Exercise 3.
- **工商 × 震元 (ρ = −0.088): B, essentially flat with faint downward lean.** Confirmed. No visual tilt at |ρ| < 0.1.

Calibration outcome locked in: tilt becomes visually detectable around |ρ| ≈ 0.3. Below that threshold, scatter plots look like noise regardless of whether the correlation is statistically real. The 震元 signal sits below this eye-threshold, which is the mechanical reason it needs formal tools. Small-ρ signals are not "small" because the eye cannot see them; they are structurally signals that emerge only at large sample size.

### Exercise 2: regression lines and the R² = ρ² identity

Fit each pair with `np.polyfit(x, y, 1)`, extracted slope and intercept, computed R² from the definition (1 − SS_res/SS_tot) and ρ² from the correlation, compared numerically.

| Pair | ρ | ρ² | R² | slope | intercept |
|---|---|---|---|---|---|
| 招商 × 平安 | 0.813 | 0.6610 | 0.6610 | 0.8561 | −0.00007 |
| 震元 vol signal | 0.123 | 0.0151 | 0.0151 | 0.0039 | −0.00377 |
| 工商 × 震元 | −0.088 | 0.0077 | 0.0077 | −0.1871 | −0.00058 |

Identity held to four decimal places on every pair. The math is not magic: for simple linear regression, R² is mechanically the squared correlation because both numbers are alternative expressions of the same quantity (how much of Y's variance the line absorbs when fitted to X).

Slope carried information ρ did not:

- 招商 × 平安 slope 0.856 ≈ ρ 0.813 because σ_招商 ≈ σ_平安 (two similar-sized joint-stock banks).
- 工商 × 震元 slope −0.187 vs ρ −0.088, ratio 2.13. Matches 震元 daily vol being roughly twice 工商's. slope = ρ × (σ_y / σ_x) verified implicitly through the variance-ratio check.
- 震元 volume slope 0.0039 per unit of volume ratio. Economically: vol_ratio = 2 predicts +0.4% next-day return, vol_ratio = 3 predicts +0.8%. Above retail round-trip costs of 20-30 bps. Intercept of −0.00377 also matters: at neutral volume (vol_ratio = 1), expected next-day return is slightly negative, which is a mean-reversion-at-zero-abnormal-volume signature.

### Exercise 3: residual analysis on the 震元 volume signal

Computed residuals as y − (slope·x + intercept). Plotted residuals vs x and residuals over time. Computed distributional moments of residuals and compared to moments of y.

Key numbers:

- Residual mean: 0.000000 (zero by OLS construction).
- Residual std: 0.02602 vs y std 0.02622. Ratio 0.9924.
- √(1 − 0.0151) = 0.9924. Identity verified: **residual std = y_std × √(1 − R²)**.
- Residual skew: −0.009 vs y skew +0.117.
- Residual kurtosis: 2.30 vs y kurtosis 2.25.

Three readings:

**The line absorbed essentially no variance.** Residual std barely below y std. At R² = 1.5%, this is definitional. The "1.5% variance explained" is the small gap between 2.622% and 2.602%.

**The line did absorb the skew.** Y had a small positive skew from the right-tail cluster (high-volume days → positive returns). The regression line learned this feature and subtracted it out. Residuals are symmetric. Important conclusion: a low-R² regression can still do real work on higher moments when the signal sits in the tails rather than the bulk. This contradicts a naive reading of "R² = 0.015 means the model did almost nothing." It did almost nothing for per-day prediction (std unchanged), but it cleanly extracted the mean-shift associated with high-volume days.

**The line did not touch the kurtosis.** Fat tails survived. This is a general property of linear regression: it fits the bulk, not the extremes. A single line passing near the origin is physically incapable of thinning ±3σ days, which are the observations dominating kurtosis. Carry-forward for Phase 4: metrics sensitive to tail behavior (VaR, drawdown, Sortino) cannot be fixed by adding linear predictors. Different tools are needed.

### Heteroskedasticity flag: sample-size artifact, not model failure

The residuals-vs-volume-ratio panel appeared to narrow at high volume ratios, which would have been heteroskedasticity (line predicting loud days better than quiet days, reverse of what was warned about originally). Closer look: ~200 observations at vol_ratio ≤ 1.5, only ~25 at vol_ratio ≥ 2. Fewer samples produces a smaller observed max residual without any change in underlying variance. The apparent narrowing is primarily a sampling effect.

Practical consequence: with 240 observations on a one-year sample, heteroskedasticity cannot be confidently detected or rejected on this signal in either direction. A proper test needs bin-based residual std computation with enough points in each bin, which 2024 data alone cannot provide. Deferred to Session 3 with statsmodels' formal Breusch-Pagan test (and a multi-year sample if the test ends up power-limited).

### Follow-up: variance, R², residual, and p-value conceptual cleanup

After Exercise 3, requested clarification on how variance, R², residual, and p-value relate as separate concepts. Key resolutions:

**Variance vs residual.** Variance is a dispersion measure applied to a series. Residuals are a derived series. A residual series has its own variance, which sits at the heart of R² arithmetic: total variance = explained variance + residual variance, R² = explained / total.

**R² vs residual as fit measures.** Not competing. Residual is per-observation (240 numbers), R² is aggregate (1 number computed from them). R² compresses information for summary; residuals preserve information for diagnosis. Both always needed: R² for overall score, residual plots for where the model fits and where it fails.

**p-value (preview for Session 3).** Probability of seeing a measured effect at least as extreme if the null hypothesis of no relationship were true. Small p = effect hard to produce by chance. Critical distinction that trips up most finance writing: p is Prob(data | null true), NOT Prob(null true | data). Different conditional. p-value tests signal-vs-noise separation, does not test economic magnitude. A significant p with a tiny slope is real-but-untradeable. Formal treatment and statsmodels output arrive in Session 3.

**The five fit-quality numbers.** Residuals (per-day errors, inspectable). ρ (strength + direction, unitless). Slope (response magnitude in real units, hedge ratio). R² (aggregate variance explained, 0 to 1). p-value (signal-vs-noise separation). No single one is complete. Full picture needs at least residual inspection + slope + R² + p together.

---

## Conceptual ground consolidated

**Regression line is the best straight line through a scatter cloud.** "Best" means minimizing the sum of squared vertical residuals (ordinary least squares). Three primitives: slope (β), intercept (α), residual (ε). Every factor model in Phase 3 decomposes stock returns as r = α + β₁·factor₁ + ... + β_k·factor_k + ε. The k = 1 case is what Session 2 covered.

**slope = ρ × (σ_y / σ_x).** Decomposition worth memorizing. Interprets ρ as the scale-free screening number and slope as the scale-aware hedge/response number. Two pairs with the same ρ can have different slopes; two pairs with the same slope can have different ρ. Using slope where ρ is appropriate (or vice versa) is a common source of confusion.

**R² = 1 − (SS_residual / SS_total) = fraction of Y's variance the line explains.** Range 0 to 1. Zero means the line is useless (predicting Ȳ does equally well). One means the line is perfect. Identity for simple linear regression: R² = ρ². Identity breaks in multiple regression (R² always ≥ highest single-predictor ρ²).

**Residual std = y_std × √(1 − R²).** When R² is tiny, residual std ≈ y_std and the line did essentially nothing for variance reduction. When R² is large, residual std shrinks toward zero and the line absorbed most of y's variability.

**R² is aggregate summary, residuals are per-observation diagnostic.** Different levels of information. Two fits with identical R² can have structurally different residual patterns (one random, one with curvature, one with time clusters). Inspect residuals always; R² alone cannot distinguish these cases.

**A small R² does not mean the line is useless for all purposes.** The 震元 case showed a line with R² = 0.015 cleanly absorbing the right-tail skew of y while barely touching its variance. Signals concentrated in tails are real but invisible to R² the way the eye is blind to tilt at |ρ| < 0.3. R² reads bulk fit; residual moments can reveal what the line did to higher-order features.

**Linear regression fits the bulk, not the tails.** Residual kurtosis barely moves under linear regression. Fat-tail behavior survives any number of linear predictors. Strategies depending on tail behavior need different tools.

**Economic significance ≠ statistical significance.** Economic: does the slope in real units produce a predicted move that exceeds transaction costs? Statistical: is the slope distinguishable from zero given sampling noise? The two are independent dimensions. Significant-but-uneconomic is the typical profile of most published factor effects and the structural cause of backtest-to-live decay.

**p-value measures Prob(data | null), not Prob(null | data).** Common confusion. A p of 0.03 means "if the null were true, data this extreme happens 3% of the time." It does not mean "there is a 97% chance the effect is real." Session 3 treats this formally.

---

## Technical skills acquired

**Production-ready fluency, without reference to documentation:**

- Fit OLS line via `np.polyfit(x, y, 1)`; returns (slope, intercept) in that order.
- Compute R² from definition: `1 - ((y - y_pred)**2).sum() / ((y - y.mean())**2).sum()`.
- Compute residuals as `y - (slope*x + intercept)` and verify their mean ≈ 0 by construction.
- Plot residuals vs predictor and residuals vs time as a diagnostic pair.
- Verify residual std = y_std × √(1 − R²) as sanity check on fit output.
- Side-by-side scatter panel with consistent styling and regression lines overlaid.

**Working fluency, with light reference:**

- Reading scatter plot tilt to estimate ρ magnitude without computing (|ρ| ≥ 0.3 visual threshold).
- Using slope = ρ × (σ_y / σ_x) as a cross-check between returned slope and computed correlation.
- Interpreting residual skew and kurtosis changes vs y's own moments to diagnose what the line did and did not do.
- Recognizing sample-size artifacts in residual plots (apparent narrowing at sparse x-regions).

**Vocabulary now fluent:**

- Regression line, slope (β), intercept (α), residual (ε).
- Ordinary least squares (OLS).
- R², coefficient of determination, variance explained, variance unexplained.
- SS_residual, SS_total, SS_explained.
- Heteroskedasticity (introduced; formal test deferred to Session 3).
- p-value, null hypothesis (introduced informally; formal in Session 3).

---

## Codebase now in the project

```
project_three/
  utils.py                         # Unchanged from Session 1
  risk_toolkit.py                  # Unchanged
  plot_setup.py                    # Unchanged
  data/
    prices/                        # Same 6-stock 2024 cache
  Session_One.ipynb                # Previous session
  Session_Two.ipynb                # This session
```

`Session_Two.ipynb` contents:

1. Imports, data loading (with the `set_index('date')` bug fix noted below).
2. Three-panel scatter plot for visual calibration.
3. Regression lines added to the same panels with annotated ρ, ρ², R², slope, intercept.
4. Printed results table comparing ρ² and R² across the three pairs.
5. Residual analysis on the 震元 volume signal: residuals vs x, residuals over time, distributional moments comparison.

**Data loading bug surfaced this session.** Session 1 code used `df.set_index('date')` in the returns panel construction, but the DataFrames returned by `load_or_fetch` already have `date` as index. This raised a KeyError on first run of Session 2. Fix: drop the `set_index('date')` call and use the index directly (`df['close'].pct_change()`). Worth a brief check at Session 3 opening to confirm whether Session 1's notebook had the same bug silently or whether something in the cached-data format shifted between sessions.

Nothing promoted to `utils.py` this session. The fit-and-plot pattern appeared three times in Exercise 2 but was factored inline as a single helper. Could be promoted to `project3_utils.py` if Session 3 or 4 needs it a third time. Rule of three threshold not yet met.

---

## Misconceptions corrected and what replaced them

**"R² and residuals are two different measures of fit quality; trade one for the other."** Replaced with: R² is the aggregate summary computed FROM the residuals. Different levels of information. R² for score, residuals for diagnosis. Not substitutes.

**"A regression with small R² did almost nothing to the data."** Partially right for variance, wrong for higher moments. The 震元 case showed a line with R² = 1.5% absorbed nearly all the skew in y while leaving std essentially untouched. Signals concentrated in the tails are real but R²-invisible.

**"The apparent narrowing of residuals at high volume ratio means the model fits better at high volumes."** Sample-size artifact, not real heteroskedasticity. 200 observations at vol_ratio ≤ 1.5 vs 25 at vol_ratio ≥ 2 cannot support a residual-variance comparison either way. General habit: before interpreting a visual pattern in the tails, count the observations that produced it.

---

## Habits explicitly built

**Verify identities numerically.** R² = ρ² is a textbook fact. Recomputing both from independent definitions on real data and seeing them agree to four decimal places is more convincing than accepting the formula, and it surfaces bugs when the identity fails.

**Check slope in real units, not just ρ.** Every regression fit ends with: what does the slope mean in dollar or percent terms? This is where economic vs statistical significance becomes concrete. ρ = 0.12 means nothing tradeable on its own; slope = 0.004 per vol-ratio unit is compared directly to transaction costs.

**Inspect residuals for structure before trusting R².** Two fits with identical R² can have completely different residual patterns. The diagnostic plots (residual vs predictor, residual vs time, residual std vs y std, residual higher moments) test whether the linear assumption itself is appropriate, which R² does not test.

**Distinguish bulk fit from tail behavior.** Linear regression fits the bulk. Residual kurtosis barely changes under linear fitting. Any metric dominated by the tails (VaR, drawdown, ruin probability) cannot be fixed by more linear predictors.

**Before interpreting a pattern, count the observations producing it.** The 震元 residual plot appeared to show heteroskedasticity until a sample-count made clear the right-side narrowing was sparse-sample artifact. This habit generalizes: any visual pattern at the tails of a scatter or residual plot needs a count-check before interpretation.

**Commit to predictions, record outcomes, update the model.** Session 2's visual-calibration predictions all held at the A/B level, but surfaced one refinement: the blob-shaped scatter at ρ = 0.12 had asymmetric right-tail behavior the A/B call missed. The prediction was right at the aggregate level and wrong about an important feature. Failures at this granularity are where the model actually learns.

---

## Implications for the 小盘股 thesis

**Defensible from Session 2 data:**

- The 震元 volume signal at R² = 0.015 sits in the normal range for real A-share small-cap return predictors. Not broken, not tradeable at single-stock scale. The slope of 0.0039 per unit volume ratio is economically meaningful (predicts +0.4% at vol_ratio = 2, +0.8% at vol_ratio = 3), above typical retail round-trip costs.
- The signal lives in the right tail of the volume distribution (high-volume days), not uniformly across all volume levels. A regression line correctly absorbed the associated skew. Practical consequence: a threshold-based filter on vol_ratio > some cutoff may be closer to the usable signal than a linear regression across the full range.
- Linear regression alone cannot capture the tail-concentrated nature of the signal well. Quintile or threshold-based methods (Project 5 methodology) are likely to extract more of the effect.

**Not supported by Session 2 data:**

- "The volume signal works uniformly across the volume-ratio range." The right-tail skew absorption showed the signal is tail-concentrated, not uniform.
- "Residual heteroskedasticity on the 震元 fit means the linear model is wrong at high volumes." The apparent narrowing is a sample-size artifact at 2024's sample size. Cannot be interpreted as model failure. Deferred to Session 3 with formal tests and potentially multi-year data.
- "R² = 0.015 means the signal is too weak to matter." R² is a bulk metric. The signal's mean-shift for high-volume days (reflected in residual skew absorption) can be economically meaningful even at low R² when combined with threshold-based execution.

---

## Open items carried forward

**Data-loading bug audit.** The `set_index('date')` pattern raised KeyError in Session 2 despite working in Session 1. Five-minute diagnostic at Session 3 opening to confirm what changed and update Session 1's notebook for consistency.

**p-value for the 震元 volume slope.** Session 2 gave slope (0.0039) and R² (0.015) but did not attach a p-value. Session 3's statsmodels output delivers this directly. The p-value on the slope is the proper test of "is this signal distinguishable from zero given 240 observations and fat-tailed data?"

**Heteroskedasticity formal test (Breusch-Pagan).** Flagged as sample-size-limited in Session 2. Session 3 runs the formal test with statsmodels. If the test comes back underpowered, deferred further to multi-year sample.

**Residual autocorrelation formal test.** Residuals over time looked un-clustered visually, but eyeballing is a weak test. Session 4's autocorrelation work applies directly to regression residuals, not just raw returns.

**Sortino formula audit from Project 2.** Still pending from two sessions back. Two-minute check, unrelated to Session 2 work but carried forward in the open items list.

**Universe-level volume signal test.** Single-stock result (震元) is descriptive, not a validated factor. Belongs in Project 5 methodology: run volume-ratio → next-day return regression across 30+ small-caps and 30+ large-caps, compare slope distributions, test whether the effect is statistically distinguishable across the size axis.

**Regime stability of Session 1 and 2 results.** All numbers are 2024-specific. Project 2's work was 2022-2024; Session 1 and 2 are 2024 only. A 2022-2023 re-run would test whether the 震元 volume signal is stable, whether the slope decomposition behaves similarly, whether the R² = 0.015 magnitude is regime-dependent.

**Fit-and-plot helper promotion.** The Exercise 2 pattern appeared three times inline but was not promoted to a helper. If Session 3 or 4 uses it a third time, promote to `project3_utils.py` under the rule of three.

---

## Bridge to Session 3

Session 3 redoes everything from Session 2 using `statsmodels.OLS` instead of `np.polyfit`. The mechanical output is the same (slope, intercept, R²); the additional output is what Session 3 is about: standard errors, t-statistics, p-values, confidence intervals, F-statistic, and formal residual tests (Breusch-Pagan for heteroskedasticity, Durbin-Watson for autocorrelation, Jarque-Bera for normality).

The 震元 volume signal is the natural target. The question Session 3 answers: given 240 observations and slope = 0.0039, is this slope statistically distinguishable from zero? What is its 95% confidence interval? Does the interval exclude zero cleanly, barely, or not at all? These numbers determine whether "R² = 0.015 with visible right-tail asymmetry" is evidence worth acting on for universe-scale testing or noise worth discarding.

Session 3 also introduces the vocabulary of hypothesis testing that Project 4 builds on directly: null hypothesis, test statistic, p-value, significance level, type I and type II error. The step from "I fit a line" to "I tested a claim" is the step from descriptive statistics to inferential statistics, which is the larger Phase 2 arc.

One specific setup: Session 3's Breusch-Pagan test for heteroskedasticity will either resolve the Session 2 sample-size ambiguity or confirm the test is underpowered, which itself is a useful diagnosis.

---

## Personal reflection

*[to be filled in after letting this sit for a day]*

---

Session 2 closed. Suggested conversation name: `2026-04-21 — Project 3 Session 2: Scatter Plots, Regression Lines, R² Identity, and Residual Analysis on the 震元 Volume Signal`.
