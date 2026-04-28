# Project 4 Session 1 Handoff: Null Distributions From First Principles

**Completed:** 2026-04-22
**Session location:** Phase 2, Project 4 (Hypothesis Testing), Session 1
**Status:** Closed. Ready for Session 2 (two-sample t-tests).

---

## Glance-back summary

Simple takeaways for when you come back to this later.

- **A p-value is a counting exercise.** It asks: if nothing real were going on, how often would randomness alone produce something at least this extreme? Today you built that count from scratch by simulation for three different test statistics. Every p-value from every piece of software is an approximation to this.

- **The null distribution's width is set by noise and sample size, not by the effect.** Rule of thumb for the mean: SEM = σ / √n. For correlation: 1/√n. Both are standard errors. They appear everywhere.

- **A 36% annualized return can fail to reject "zero expected return."** 平安银行 2024: observed daily mean 0.15%, SEM 0.11%, t-stat 1.42, p = 0.15. The 36% headline sits inside the noise range that a genuinely zero-mean stock routinely produces over one year at this volatility.

- **Bell curves are emergent, not assumed.** Sum enough independent random things and you get a normal distribution regardless of the underlying shape. Coin flips (binary), uniform draws, exponential draws all produced bell-shaped sums. This is the Central Limit Theorem.

- **Permutation destroys pairing but preserves distributions.** Shuffling today's returns while fixing yesterday's breaks any real relationship but keeps mean, variance, skew, and fat tails intact. Whatever correlation survives the shuffle is coincidence by construction.

- **For n ≈ 240 daily observations, parametric and permutation p-values agree within 1-2 points.** The CLT rescues normal-based tests at this sample size. Permutation's real advantage appears at small n and for higher-moment statistics.

- **Failing to reject is not proving zero.** 平安银行 2024's 95% CI on daily expected return spans roughly -14% to +87% annualized. That's "we don't know," not "it's zero."

- **Annualized numbers are seductive; standard errors are the relevant quantity.** 36% per year sounds like a discovered pattern. The underlying question is whether 241 observations at 1.65% daily vol can distinguish 36% from zero. They can't.

---

## Reference conversations

- `2026-04-22 — Project 4 Scoping: Overlap With Project 3 and Proposed Compressed Path`
- `2026-04-22 — Project 4 Session 1: The Null Distribution From First Principles, Coin-Flip Simulation`
- `2026-04-22 — Project 4 Session 1: Null Distributions, the Central Limit Theorem, and Why Bell Shapes Appear`
- `2026-04-22 — Project 4 Session 1: Enumeration vs Simulation vs Closed-Form, de Moivre, and the Pre-Computer Statistical Workflow`
- `2026-04-22 — Project 4 Session 1 Example 2: Null Distribution for the Sample Mean, Standard Error, and the Normality Assumption`
- `2026-04-22 — Project 4 Session 1 Example 2 Interpretation: Fail-to-Reject, Statistical Power, and Why One Year of 平安银行 Is Not Enough`
- `2026-04-22 — Project 4 Session 1: Permanent Chinese Font Fix Implementation Steps`
- `2026-04-22 — Project 4 Session 1 Example 3: Permutation Test for Lag-1 Autocorrelation of 平安银行 2024`
- `2026-04-22 — Project 4 Session 1 Close: Permutation Test for Autocorrelation, CLT Convergence, and Prediction Calibration on 平安银行 2024`

---

## Starting point

Entered Session 1 after Project 3 closed. Project 3 Session 5 had already met the multiple-testing problem via simulation (100 random predictors against 震元 returns, producing the expected ~5 false positives at α = 0.05). Had working fluency with Pearson and Spearman correlation, regression with HC3 robust standard errors, ACF and Ljung-Box, and Bonferroni as a family-wise correction.

Gap: had never built a null distribution from scratch. Every p-value read during Project 3 came from statsmodels output, trusted without being constructed. No explicit mental model for what the software was doing under the hood.

## Session 1 thesis

A p-value from any software is an approximation, or a direct computation, of a quantity you can build by direct counting: the fraction of "null worlds" in which randomness alone produces something at least as extreme as what you observed. Building it once by simulation, for three different test statistics, creates permanent intuition that carries to every subsequent hypothesis test. Once you've seen the machinery explicitly, the parametric shortcuts in statsmodels and scipy stop being magic.

---

## Walk-through of the three examples

### Example 1: the fair-coin null

**Setup.** Flip a coin 100 times, observe 58 heads. Is the coin unfair?

**Null.** Fair coin, p = 0.5. **Test statistic.** Number of heads. **Null distribution construction.** Simulate 10,000 experiments of 100 flips each, tally heads per experiment.

**Result.** Simulated two-tailed p ≈ 0.13, matches `scipy.stats.binomtest` to within 0.01. 58 heads sits inside the bulk of the null distribution. Not enough to reject.

**Key observations.** The null distribution is bell-shaped even though individual flips are binary (CLT in action). Software and direct counting agree because they compute the same object. Getting below p = 0.05 requires about 60+ heads, which corresponds to roughly 2 standard deviations above the null mean of 50 (std = √(np(1-p)) = 5).

**Historical bridge.** de Moivre's 1733 normal approximation to the binomial. Mean = np = 50, std = √(np(1-p)) = 5. Z-score = (58-50)/5 = 1.6. Table lookup for z = 1.6 gives two-tailed p ≈ 0.11. Pre-computer statisticians did this with one multiplication, one square root, one subtraction, one division, and one table lookup. The normal distribution entered statistics as a computational shortcut for the binomial, not as a free-standing assumption about data.

**Three-way correspondence confirmed via small n = 10.** Enumerate all 2^10 = 1024 arrangements with `itertools.product`. Count arrangements per heads-count. Compare to the binomial coefficient formula C(n, k) / 2^n. Compare to simulation. All three match exactly at n = 10. For n = 100, enumeration fails at 10^30 arrangements but the formula still works. Simulation is the tool of last resort for problems too hard for closed-form, and the tool of first resort for building intuition on easy ones.

### Example 2: the sample-mean null applied to 平安银行 2024

**Setup.** 241 daily returns for 平安银行 2024. Observed mean 0.001504 (0.15% per day), observed std 0.016473 (1.65% per day).

**Null.** True expected daily return is zero. **Test statistic.** Sample mean. **Null distribution construction.** Simulate 10,000 parallel universes, each drawing 241 returns from Normal(0, 0.0165), compute the sample mean, collect.

**Result.** Simulated p = 0.1515. scipy's `ttest_1samp` p = 0.1577. Agreement to within 0.4 percentage points. The small gap reflects real non-normality of 平安银行's returns, which the parametric test ignores and simulation implicitly accommodates. t-stat = 1.42.

**Key interpretation.** The 36% annualized observed return is statistically indistinguishable from a zero-mean stock at this volatility and sample size. A stock with 1.65% daily vol and 241 observations has a standard error on its sample mean of 0.001061. The observed mean sits only 1.42 of those standard errors from zero.

**Ballpark calculation for power.** To detect a 15 bps per day signal at 1.65% vol with a t-stat ≥ 2, you need n ≥ (2σ/mean)² ≈ 482 observations. Roughly two years of daily data, assuming the signal is stationary across regimes. It probably isn't, so the real requirement is larger.

**Pre-simulation sanity check run successfully.** Generated fake data with TRUE mean forced to zero, confirmed the test produced p ≈ 0.97 (non-rejection), verifying the machinery does what was claimed before applying it to real data.

### Example 3: the permutation test for lag-1 autocorrelation of 平安银行 2024

**Setup.** 240 (yesterday, today) pairs from 平安银行 2024 daily returns.

**Null.** No relationship between yesterday and today. **Test statistic.** Pearson correlation. **Null distribution construction.** Shuffle today's returns 10,000 times while keeping yesterday's fixed. Compute correlation of (yesterday, shuffled today) each time. The shuffle destroys the pairing but preserves the return distribution exactly.

**Result.** Observed correlation = -0.0505. Permutation p = 0.4224. Parametric (scipy.pearsonr) p = 0.4362. Agreement to within 1.4 percentage points.

**Diagnostic confirmation.** Null distribution std = 0.0652, theoretical 1/√240 = 0.0645. Near-exact match confirms the null distribution behaves as theory predicts.

**Verdict.** Fail to reject. 平安银行 2024 does not show statistically detectable lag-1 autocorrelation.

**Prediction accuracy.** Direction correct (slight negative), magnitude correct (small), verdict correct (fail to reject). Three for three on a finance-level question. This is the first such call successfully pre-committed in our sessions.

**Mechanism caveats, documented honestly.** The fund-flow-reversal story proposed pre-test is consistent with the data but so are two alternatives: (a) 2024 was range-bound for 平安银行, producing mechanical mean-reversion unrelated to news flow, (b) pure noise, because -0.78 sigma is well inside the luck range for a zero-autocorrelation stock. The test cannot distinguish among these three stories. A confirmed prediction is not proof of the proposed mechanism.

---

## Conceptual ground

**A p-value is the fraction of null worlds in which randomness produces something at least as extreme as what you observed.** Every parametric p-value (t-tests, z-tests, F-tests, chi-squared) approximates this counting exercise. Simulation computes it directly. Parametric methods compute it via closed-form formulas that assume specific distributional shapes.

**The null distribution's width is controlled by noise level and sample size.** For sample means: σ/√n. For correlation under independence: 1/√n. These are standard errors. The shape appears everywhere because it reflects the same idea: averages of independent things have a spread that shrinks as √n.

**Bell shapes are emergent from summing independent random quantities.** The CLT says sums and averages of many independent finite-variance quantities become approximately normal, regardless of the underlying distribution. This is why parametric methods based on normal distributions work even for non-normal data, as long as n is large enough and the test statistic is an average-like quantity. CLT is asymptotic, so fatter tails require larger n before the approximation becomes good. This is the reason Project 3's Session 3 robust SEs mattered for regression inference at modest n.

**Permutation tests make no distributional assumption.** Shuffling destroys pairing while preserving the marginal distributions exactly. Any pattern that survives shuffling is pure coincidence by construction. This works at any sample size and for any distribution shape. The cost: computation time and the requirement that your null hypothesis can be expressed as a statement about pairing or labeling.

**Parametric and permutation p-values converge for moderate n.** At n = 241 daily observations with typical fat tails, they agree within 1-2 percentage points. At n = 30 or for higher-moment statistics like variance ratios, they can diverge substantially and permutation is more trustworthy.

**Failing to reject is not proving the null.** A high p-value means the data is consistent with the null. It does not mean the null is true. The 95% confidence interval (rough rule: observed ± 2·SEM) captures the range of effect sizes consistent with the data. For 平安银行's 2024 mean, this range spans -14% to +87% annualized. That's "we don't know," not "it's zero."

**Statistical significance and economic significance are different questions.** An effect can be statistically significant (t-stat > 2) and too small to trade after costs. An effect can be economically large (36% annualized) and statistically indistinguishable from zero if the noise is larger and the sample is small. Always compute both.

---

## Technical skills acquired

Production-ready:

- Build a null distribution by simulation for any test statistic: generate data under the null repeatedly, compute the statistic each time, collect into an array
- Compute a two-tailed p-value from a simulated null via `np.mean(np.abs(null_stats) >= np.abs(observed))`
- Run `scipy.stats.ttest_1samp` and verify against a simulation-based counterpart
- Run a permutation test for correlation using `np.random.permutation` on one of two paired series, preserving the other
- Diagnose a simulated null distribution via mean and std against theoretical values (mean should be near zero; std should be 1/√n for correlation or σ/√n for sample means)
- Enumerate all arrangements for small n with `itertools.product`, confirming correspondence with closed-form and simulated results
- Write `matplotlibrc` permanently to fix Chinese font rendering without per-notebook setup calls

Vocabulary internalized:

- Null hypothesis, test statistic, null distribution, standard error
- Central Limit Theorem as "emergent bell shape from summing independent things"
- Parametric vs non-parametric test, permutation test, binomial test
- de Moivre-Laplace theorem as the original CLT special case
- Type II error and statistical power (conceptually, via the 2σ/mean power calculation)

---

## Codebase additions

No functions promoted to `utils.py` or `risk_toolkit.py` yet. Three worth promoting at the start of Session 2, most likely into a new `hypothesis_testing.py` module to keep the testing tools separate from data infrastructure and from risk metrics.

```python
def simulate_null_mean(n, sigma, n_sims=10000, seed=42):
    """Null distribution of the sample mean for Normal(0, sigma)."""
    rng = np.random.default_rng(seed)
    return rng.normal(0, sigma, size=(n_sims, n)).mean(axis=1)

def permutation_corr(x, y, n_perms=10000, seed=42):
    """Null distribution of Pearson correlation via shuffling of y."""
    rng = np.random.default_rng(seed)
    null_corrs = np.empty(n_perms)
    for i in range(n_perms):
        null_corrs[i] = np.corrcoef(x, rng.permutation(y))[0, 1]
    return null_corrs

def p_value_two_tailed(null_stats, observed):
    """Fraction of null statistics at least as extreme as observed."""
    return np.mean(np.abs(null_stats) >= np.abs(observed))
```

Project Four folder now contains:

```
project_four/
  data/
    sz000001_with_returns.csv    # 平安银行 2024, pulled fresh today, 242 rows
  utils.py                       # copied forward from Project 3
  risk_toolkit.py                # copied forward from Project 2
  Session_One.ipynb              # three examples + real-data applications
```

**Side fix: permanent Chinese font configuration.** Created `C:\Users\Leo\.matplotlib\matplotlibrc` with two lines:

```
font.sans-serif: Microsoft YaHei, DejaVu Sans
axes.unicode_minus: False
```

`plot_setup.py` is no longer needed for Project 4 onward. Chinese characters and negative-sign labels render correctly in every future matplotlib session without per-notebook setup calls.

---

## Reasoning patterns reinforced

**Predict before measuring, even roughly.** The Example 3 prediction landed on direction, magnitude, and verdict. This is the first finance-level question called correctly by pre-commitment in our sessions. The mechanism proposed (fund-flow reversal in blue chips) was plausible but the data cannot distinguish it from competing stories. This is a separate, important lesson: a confirmed prediction is not proof of the proposed mechanism when the data is also consistent with other stories.

**Check diagnostics against theory.** Example 3's null distribution std (0.0652) vs theoretical (0.0645) is the kind of check that catches code bugs instantly. Habit to build: print expected values alongside observed ones, and flag discrepancies larger than rounding.

**Annualized numbers are seductive.** 36% annualized on 平安银行 2024 sounds like a discovered pattern. The underlying question is whether 241 observations at 1.65% daily vol can distinguish that from zero expected return. The standard error is the relevant quantity, not the headline return.

**Build the sanity check before applying the test.** Example 2 ran on fake zero-mean data first (p = 0.97, correct non-rejection) before touching real data. Without this step, a bug could give a false p-value on real data and the mistake would go undetected. Habit: whenever building a new test, first verify it produces the correct verdict on data where the null is true by construction.

---

## Open items carried forward

**Function promotion.** The three helpers above should go into a new `hypothesis_testing.py` module. Decide at the start of Session 2. Keeps testing tools separate from data-access tools (`utils.py`) and from risk metrics (`risk_toolkit.py`).

**No economic interpretation given for 平安银行 Example 2.** The statistical answer was "fail to reject zero mean." The economic interpretation depends on the evaluation window (is 2024 representative?) and the benchmark choice (zero, risk-free, or index?). The honest answer is "not enough data to conclude anything about expected return from 241 observations." Carry this forward as a reflex for Project 5: any single-factor return claim should be stress-tested with the power calculation (2σ/mean)².

**Session 5 of Project 3 housekeeping items still pending.** The Session 1 notebook `set_index` check and the Sortino formula check in `risk_toolkit.py` were flagged in the Project 3 Session 4 handoff and never explicitly resolved. Probably closed by implicit usage in Project 3 Session 5, but not confirmed in writing. Close at the start of Session 2 or flag as closed if already done.

---

## Bridge to Session 2

Session 2 is the two-sample t-test. The question changes from "is this mean different from zero?" to "are these two groups' means different from each other?" Same null-distribution machinery, applied to a slightly different test statistic (difference in means between groups, instead of a single mean).

The natural application: binary-signal splits. Pick a candidate predictor (high-volume days, post-drop days, a momentum indicator, whatever), split returns into "days with signal on" and "days with signal off," and ask whether the two groups' next-day means differ meaningfully. This is the template for every single-signal evaluation in Project 5, and it's one conceptual step from quintile-return analysis.

Two candidates for Session 2's worked example: the 震元 volume-ratio signal from Project 3 Session 4 (volume ratio vs next-day return), or a small-cap candidate from the Project 1 basket where detectable short-term autocorrelation is more mechanistically plausible than in a large-cap like 平安银行. Choose at Session 2 start.

The Central Limit Theorem and standard error framework established today extends cleanly: the standard error for a difference in means between two independent groups is `sqrt(SEM_A^2 + SEM_B^2)`, which has the same √n-scaling structure. Welch's t-test handles unequal variances. A permutation version (shuffle the group labels) handles non-normality. Both will appear in Session 2.

---

Session 1 closed. Suggested conversation name for Session 2: `2026-04-XX — Project 4 Session 2: Two-Sample t-Tests and Binary-Signal Splits`.
