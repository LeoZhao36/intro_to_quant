# Project 4 Session 2 Handoff: Two-Sample t-Tests and Binary-Signal Splits

**Completed:** 2026-04-22
**Session location:** Phase 2, Project 4 (Hypothesis Testing), Session 2
**Status:** Closed. Ready for Session 3 (basket-level reversal test on 中证1000 full universe).

---

## Glance-back summary

Simple takeaways for when you come back to this later.

- **A two-sample t-test measures one narrow thing: whether the sample means of two independent groups differ by more than the standard error of their difference would predict under noise.** It is blind to everything except the means. Two groups with identical means but wildly different shapes will look the same to this test.

- **"Two-sample" means independent groups, not paired observations.** Pairing is a different test that matches observations (e.g., before/after on the same stock). Strike "pair" from any note that's really about two-sample testing.

- **The standard error is the correct ruler because it measures noise in the exact quantity being tested.** We're comparing two sample means, not individual observations, so individual-return volatility is the wrong ruler. The SE of the difference is, by construction, the standard deviation of the quantity we observed, under random sampling.

- **SE is computable from a single sample because it depends only on noise properties and sample size, not on the true mean.** The sample standard deviation s estimates the population σ well at moderate n because s uses every observation to characterize spread, while the sample mean struggles to resolve tiny signals against large noise floors. Spread is easy to estimate; means are hard.

- **Variances, not standard deviations, combine cleanly across independent groups.** This is why the SE formula for a difference has squared terms added together before the final square root. Working in variance space until the end preserves the correct combination rule.

- **浙江震元 2024 two-sample test produced t = 1.34, parametric p = 0.18, permutation p = 0.19.** Observed gap of 0.61% per day between day-after-down and day-after-up means. Point estimate sign is consistent with short-term reversal; statistical power insufficient to reject zero effect.

- **Parametric and permutation p-values agreed within 0.7 percentage points.** CLT is rescuing the normal approximation at n ≈ 120 per group even with small-cap fat tails. When they agree, use either. When they diverge substantially, trust permutation.

- **Cost-adjusted Sharpe of the implied reversal strategy: ~0.54 annualized, assuming the point estimate holds.** Round-trip transaction costs on a small-cap eat roughly 70% of the gross edge (0.30% cost floor against 0.428% gross per-trade return).

- **The 95% confidence interval for the true effect spans −0.3% to +1.5% per day.** Roughly half of this interval would lose money after costs. Trading on the point estimate is close to a coin flip that your best guess happens to be right.

- **Single-stock time-series testing is structurally underpowered for small effects at small-cap volatility.** The fix is cross-sectional pooling (Project 5), which trades "we know about this stock" for "we know about a population of stocks" and buys statistical power dramatically faster than accumulating more time.

---

## Reference conversations

- `2026-04-22 — Project 4 Session 2: Two-Sample t-Tests, Binary Signal Splits, and 震元 Reversal Test`

(Single conversation covered the full session arc including the basket-test setup that Session 3 will pick up.)

---

## Starting point

Entered Session 2 after Session 1 closed. Session 1 built the null distribution from scratch three ways (fair-coin binomial, sample-mean null on 平安银行, permutation correlation on 平安银行). Had working understanding of p-values as counting exercises, standard errors as 1/√n-scaled noise on averages, and CLT as the reason parametric tests work on non-normal data at moderate n.

Gap: no experience with two-sample comparisons. All Session 1 tests were one-sample or one-correlation. No exposure to the standard error of a difference in means, to Welch's correction for unequal variances, or to the practical calibration of turning a p-value into a cost-adjusted trading decision.

Also entering Session 2 with a specific confusion flagged in my own notes: "two-sample t-test tests whether there is a special relationship between two sets of data." This phrasing conflated the narrow mean-comparison function of the test with a broader (and wrong) claim about detecting relationships. Session 2 needed to resolve this directly before any worked example would make sense.

---

## Session 2 thesis

The two-sample t-test is the template for nearly every candidate trading signal you will ever evaluate. A signal splits observations into two groups (signal on / signal off, or quintile top / quintile bottom); the usable question is always whether those groups' forward-return means differ by more than noise produces. Mastering this one test, with a full understanding of its underlying SE formula and its economic-significance layer, generalizes directly to Project 5's factor IC work and to every single-signal evaluation in the rest of the curriculum.

Session 2 built the test from first principles (motivation, SE derivation, formula breakdown) before any code, applied it to one real small-cap (浙江震元 2024, chosen because the lag-1 autocorrelation story from Session 1 extends naturally into the binary-sign split), and extended into the economic-significance layer that converts p-values into "can I trade this after costs" decisions.

---

## Progression through the session

### Part one: refining the definition

Opened by reviewing my own note that "two-sample t-test tests whether there is a special relationship between two sets of data." Two corrections, both important.

"Pair" got struck from the vocabulary. A two-sample t-test compares independent groups with no matching between observations; a paired t-test (different test entirely) compares before/after on the same unit. I was never going to use the paired version for the factor work we're heading toward. Keeping the vocabulary clean avoids future confusion.

"Special relationship" got replaced with "means differ by more than the standard error would predict." The test does exactly one thing: compare sample means against the noise scale of the difference. It is blind to shape, to tail behavior, to correlation structure, to anything other than the two group averages. This matters because it prevents overclaiming. A rejected null does not mean "I have found a real pattern between the groups." It means "the gap between these two specific sample means is larger than pure coincidence typically produces at this sample size." Narrower, more precise, more honest.

The corrected definition in my notes now reads: "Two-sample t-test. Tests whether the sample means of two independent groups differ by more than noise alone would produce. Uses the standard error of the difference in means as the ruler for what counts as a notable gap. Blind to everything except means: two groups with identical means but wildly different shapes will look the same to this test."

### Part two: why standard error is the ruler

Worked through the "why this ruler" question in a structured way that generalizes to any "why this formula" question I'll meet later.

Started from the general principle that any claim about size is secretly a comparison to something. "The gap is 0.13 percentage points" is not a claim about size until the reference scale is specified. Walked through three candidate rulers and why each fails:

**Absolute threshold** ("any gap > 0.10% is significant") ignores context entirely. The same gap is a detectable pattern in n = 10,000 and pure noise in n = 5.

**Raw data standard deviation** (using σ of individual observations) is wrong scale. The gap is between group *means*, which are far more stable than individual observations because averaging reduces noise. Comparing a mean-gap to individual-observation-σ is like comparing mountain-peak heights to daily weather.

**Standard error of the difference in means** is the principled choice because it is, by construction, the standard deviation of the exact quantity we observed. It scales with sample size (more data shrinks it), scales with underlying noise (noisier data expands it), and matches the thing being measured.

This general principle ("the ruler must match the thing measured") extends to every statistical test. The ruler is always the SE of the test statistic under the null. T-tests, regression coefficients, factor ICs, all follow this pattern.

### Part three: resolving the chicken-and-egg problem

Flagged a natural confusion: the SE formula appears to require knowing the population σ, but if we knew the population we wouldn't need to estimate anything. Resolution was the single most important idea of the day.

Key asymmetry: sample mean x̄ and sample std s converge to their population counterparts at very different rates. The mean is hard to pin down because signal is tiny relative to noise in financial returns (0.1% daily mean against 1.5% daily std). The std is easy to pin down because every observation contributes to characterizing spread, not just a few. With 20 observations you already get a decent read on typical variation; with 20 observations you get essentially no information about the mean.

So when we use s (sample std) as the estimate of σ (population std), we are not cheating. We are exploiting a real asymmetry in how well spread and location estimate from samples. The SE formula depends only on noise properties and sample size, never on the true mean. This is what makes inference from samples to populations possible, and it is the foundation for every subsequent test in the curriculum.

Mentioned Bessel's correction (n − 1 divisor in sample std) in passing. Correction exists because x̄ is estimated from the data, using up one degree of freedom, and the naive n divisor slightly underestimates σ. Invisible at n in the hundreds, matters at n around 10. pandas, scipy, and numpy with `ddof=1` all handle it automatically.

### Part four: the SE formula, broken to atoms

Under the new math protocol (added to memory mid-session), walked through the two-sample SE formula piece by piece. Problem it solves: measuring the wobble in the observed difference in means across hypothetical replays of reality. Formula:

$$\hat{SE}(\bar{x}_A - \bar{x}_B) = \sqrt{\frac{s_A^2}{n_A} + \frac{s_B^2}{n_B}}$$

Each operation justified in plain language:

- **s_A² and s_B²**: we square standard deviations to get variances because variances combine additively under independent sums/differences. Working in variance space until the final step keeps the combination rule correct.
- **Divide by n_A and n_B**: the averaging-reduces-noise effect in variance form. A group of n_A observations produces a mean whose variance is s²/n. Larger n, smaller variance.
- **Add the two terms**: because the two groups are independent. When you subtract their means, the noises do not cancel; they accumulate. Independent variances add. This is the key counterintuitive move: subtraction of means is not noise subtraction.
- **Square root at the end**: convert from variance units (squared percentage points, uninterpretable) back to standard-deviation units (percentage points, directly comparable to the observed gap).

This structure ("define the problem, break to atoms, justify each atom, then recombine") is now the default explanation pattern for any equation in future sessions. Added to memory as a permanent rule.

### Part five: worked example, 浙江震元 2024

Pulled fresh data for 浙江震元 (sh.600114), 2024-01-01 to 2024-12-31. 242 daily observations, 241 non-null returns after `.pct_change()`.

Built the split via a two-column paired DataFrame with `shift(1)`:

- Group up (yesterday positive): n = 121, mean = −0.182% per day, std = 3.323% per day
- Group down (yesterday negative): n = 118, mean = +0.428% per day, std = 3.698% per day

Three immediate reads on the raw numbers before any formal test.

**Direction**: negative autocorrelation. Up days followed by slight decline, down days followed by bounce. Reversal, not momentum. Opposite of the information-diffusion-lag story Project 1 and 3 had suggested. Consistent with overreaction and bid-ask-bounce mechanisms common in small-caps.

**Volatility**: both groups near 3.3%-3.7% daily std, roughly double 平安银行's 1.65%. Small-cap volatility premium showing up in raw form. Annualized roughly 52%-58%.

**Unequal group stds**: down days followed by noticeably more volatile days (3.70% vs 3.32%). Fear regimes more volatile than euphoria regimes, a well-documented asymmetric-volatility pattern. Violates equal-variance assumption, so Welch's test is the right choice.

Hand-computed the standard error of the difference following the formula-breakdown protocol:

- s_A² = 0.03323² = 0.001104; s_B² = 0.03698² = 0.001368
- s_A²/n_A = 0.001104/121 = 9.13e-6; s_B²/n_B = 0.001368/118 = 1.159e-5
- Sum = 2.072e-5
- √ = 0.00455 (0.455% daily SE)

Observed gap: 0.00428 − (−0.00182) = 0.00610 (0.61% per day).

t-statistic by hand: 0.00610 / 0.00455 = 1.34.

**Pre-scipy prediction**: p ≈ 0.18, fail to reject, based on roughly 18% of two-tailed normal tails beyond |z| = 1.34.

**Scipy result** (`ttest_ind(equal_var=False)`): t = 1.3388, p = 0.1819.

Match to hand computation: essentially exact, with trivial differences attributable to Welch's fractional degrees-of-freedom correction.

### Part six: permutation cross-check

Ran permutation test to verify fat tails weren't distorting the parametric result. Shuffled group labels 10,000 times on the pooled set of 239 today-returns, recomputed the difference in means each time, counted fraction at least as extreme as observed.

**Permutation p = 0.1880**. Parametric p = 0.1819. Agreement within 0.7 percentage points.

Concluded: CLT is rescuing the normal approximation at n ≈ 120 per group even with small-cap fat tails. Neither method is better here; they agree, so either can be used. Rule-of-thumb established: when the two agree within 1-2 points, either is fine. When they diverge substantially (say 0.18 vs 0.08), trust permutation and investigate why parametric is misbehaving.

### Part seven: economic significance

This was the layer that converted the statistical result into a usable trading judgment, and it's the most important transferable skill of the session.

Set aside the actual p-value and asked: if the reversal effect were real and the 0.61% gap persisted, would it be tradeable?

Naive strategy: buy at close on down days, sell at close the next day. Mean after-down-day return: 0.428%.

Transaction cost floor for small-caps in A-shares:
- Buy commission 0.025% + sell commission 0.025% = 0.05%
- 印花税 (sell side only) = 0.05%
- Slippage on 浙江震元 (thin small-cap order book): realistic estimate 0.10%-0.30% per side, combined roughly 0.20%

Total round-trip cost floor: ~0.30%. Generous estimate; could be worse.

After-cost per-trade edge: 0.428% − 0.30% = 0.128%.

Distribution of outcomes: this is a 0.128% mean against a 3.70% daily std. Most individual trades lose money (because std >> mean); the edge comes from a small positive bias accumulated over many trades.

Sharpe calculation:
- Gross daily Sharpe: 0.428 / 3.70 = 0.116; annualized ×√242 = 1.81
- Net daily Sharpe: 0.128 / 3.70 = 0.035; annualized ×√242 = 0.54

A Sharpe of 0.54 after costs is mediocre but positive, assuming the effect is real.

But the 95% CI for the true effect spans −0.3% to +1.5% per day. Within that range:

- True effect near the low end: lose money on every trade
- True effect zero: lose the cost floor on every trade (0.30% × ~120 trades/year = ~36% annual bleed)
- True effect at point estimate (0.61%): modest Sharpe of ~0.8 after costs
- True effect at high end: spectacular returns

Probability that the true effect is above the ~0.30% needed to break even after costs: roughly 50%. Trading on the point estimate is a near-coin-flip bet that the best guess happens to be right.

This is the concrete meaning of "statistically insignificant." Not "effect is zero." But "my data cannot distinguish the point estimate from values that would make me lose money." The p-value is not decoration; it is the filter separating "pattern worth trading" from "random arrangement of last year's data that looks promising."

Named three paths forward explicitly:

1. **More data on this stock**: need ~10x the sample (approximately 10 years) to distinguish a 0.3% daily effect from zero. 10 years of 震元 is not a stationary 震元, so this path is partially illusory.
2. **Pool across stocks**: Project 5's approach. 100 stocks × 500 days = 50,000 observations. SE shrinks by √100 = 10x. Real small-cap reversal becomes detectable if it exists. This is the structurally correct fix.
3. **Stronger priors from literature**: the academic literature does support small-cap reversal. A Bayesian framework would accept weaker point-estimate evidence given strong prior. Not taking this path yet but naming it for completeness.

### Part eight: setting up Session 3 (pooling across stocks)

Flagged the conceptual fork hiding inside "run the test on all of 中证1000."

**Question A**: does the 中证1000 basket itself show reversal? (Aggregate to one time series, test that.)

**Question B**: does the average individual stock show reversal? (Test each stock, pool the test statistics.)

**Question C**: how many individual stocks show significant reversal? (Count p-values below threshold, apply multiple-testing correction.)

Chose Question A for Session 3 as the cleanest and most directly relevant to the core "does this effect exist in small-caps" question. Questions B and C remain for later.

Committed to pulling the full 1000-stock universe for the 2024-01-01 to 2026-04-22 window rather than a 50-stock sample. Rationale: the data is reusable for Projects 5 and 6, so the one-time cost of a long pull pays off across the rest of the curriculum. No point sampling now and pulling again later.

Set up the pull with cache-aware logic so a mid-run crash doesn't cost progress. 北交所 stocks (4xxxxx, 8xxxxx codes) filtered out because baostock coverage is inconsistent. Pull currently running; will produce ~950 successful DataFrames stored in `data/prices/`.

---

## Conceptual ground

The spine of Session 2, compressed.

**The two-sample t-test compares sample means of independent groups using the SE of the difference as the ruler.** It is blind to shape, tails, pairing, or any relationship beyond the mean gap. Narrow, precise function. Overclaiming its scope is a common error.

**Welch's version is the right default for financial data.** Unequal variances across groups are the rule in returns, not the exception. Regime differences, volume differences, and fear/greed asymmetries all produce heteroscedastic splits. Welch's correction costs nothing when variances happen to be equal and saves you when they aren't.

**SE combines as √(variance sum), not (std sum).** Independent variances add; standard deviations don't. The squared structure of the formula is not arbitrary; it encodes the correct combination rule for independent noise. Working in variance units preserves this rule until the final square root restores interpretable units.

**SE is computable from sample data alone because spread is easier to estimate than location.** s → σ fast; x̄ → μ slow. This asymmetry underlies all of classical statistics.

**Statistical significance and economic significance are separate filters.** The first asks "is the effect distinguishable from noise?" The second asks "is the effect large enough to survive costs?" A claim that passes the first but not the second is not tradeable. A claim that passes the second but not the first is a coin-flip bet. Both filters must pass.

**Confidence intervals are the information the p-value hides.** A fail-to-reject doesn't mean "the effect is zero." It means "the data is consistent with a range of possible effects, including zero." The CI exposes that range. For 震元 2024, the CI spanned effects that would lose money to effects that would make spectacular money; the single p-value obscures this.

**Single-stock time-series tests are structurally underpowered for small effects.** The math: SE on a single-stock mean scales as σ/√n. For σ around 3% daily (small-cap) and mean effects we care about around 0.1%-0.5% daily, need n in the thousands to reliably distinguish. Thousands of daily observations on a single stock is a decade+, crossing regime boundaries. The structurally correct fix is cross-sectional pooling, which Project 5 implements.

**Parametric and permutation tests converge for moderate n.** At n ≈ 120 per group with fat tails, they agree within 1-2 percentage points. Permutation's advantage emerges at small n, at higher-moment statistics (variance, correlation structure), and at extreme tails. For mean comparisons on daily returns with groups above ~50, either is fine; run permutation as a sanity check on parametric.

---

## Technical skills acquired

Production-ready (no documentation reference needed):

- Build a paired DataFrame from a single return series using `shift(1)` and align by date index
- Split a paired DataFrame into two groups by boolean indexing: `paired.loc[paired['yesterday'] > 0, 'today']`
- Compute group-level descriptive statistics (n, mean, std) from pandas Series
- Hand-compute the standard error of a difference in means from s_A, s_B, n_A, n_B, piece by piece
- Convert hand-computed SE and observed gap to a t-statistic
- Run `scipy.stats.ttest_ind(group_a, group_b, equal_var=False)` and interpret t-stat plus p-value
- Run a label-permutation test: pool observations, shuffle, reassign to groups of preserved sizes, compute null distribution of differences
- Compute two-tailed permutation p-value via `np.mean(np.abs(null_diffs) >= np.abs(observed_diff))`
- Convert a p-value into a rough 95% confidence interval via observed ± 2·SE
- Convert an observed effect into a cost-adjusted per-trade expected return using A-share cost floors (commissions, 印花税, small-cap slippage)
- Compute daily and annualized Sharpe from mean and std, before and after costs

Working fluency (light reference OK):

- Pull full 中证1000 constituent list via `ak.index_stock_cons_csindex(symbol="000852")`
- Filter out 北交所 stocks (codes starting with 4 or 8) before pulling prices
- Build a cache-aware bulk data pull loop that skips already-downloaded stocks on restart
- Choose between the three flavors of cross-sectional pooling (basket-level, stock-averaged, stock-count) based on the research question

Vocabulary internalized:

- Two-sample vs paired t-test
- Welch's t-test vs Student's t-test; equal-variance assumption
- Standard error of a difference in means; variance addition under independence
- Bessel's correction; ddof parameter
- Heteroscedasticity (informally, "unequal variances")
- Cost-adjusted Sharpe; break-even effect size
- Cross-sectional pooling as a power-recovery strategy

---

## Codebase additions

Fresh Project 4 folder structure:

```
project_four/
  data/
    sh600114_2024.csv                       # 浙江震元 2024 daily, fresh pull
    zz1000_all_codes.csv                    # full 中证1000 constituent list in baostock format
    prices/                                 # per-stock cached CSVs (populating from bulk pull)
  utils.py                                  # forwarded from Project 3, unchanged
  Session_Two.ipynb                         # 震元 two-sample test, full worked example
```

Three helpers worth promoting to a new `hypothesis_testing.py` module. Same three flagged in Session 1's handoff plus a new one for Session 2. Still not promoted; remains an open item:

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

def permutation_mean_diff(group_a, group_b, n_perms=10000, seed=42):
    """Null distribution of the difference in means via label shuffling.
    Pools all observations, reassigns to groups of original sizes, recomputes."""
    rng = np.random.default_rng(seed)
    pooled = np.concatenate([group_a, group_b])
    n_a = len(group_a)
    null_diffs = np.empty(n_perms)
    for i in range(n_perms):
        shuffled = rng.permutation(pooled)
        null_diffs[i] = shuffled[n_a:].mean() - shuffled[:n_a].mean()
    return null_diffs

def p_value_two_tailed(null_stats, observed):
    """Fraction of null statistics at least as extreme as observed."""
    return np.mean(np.abs(null_stats) >= np.abs(observed))
```

---

## Misconceptions corrected

**"Two-sample t-test tests for a relationship between two sets of data."** Replaced with the narrower and correct "tests whether the sample means of two independent groups differ by more than noise would produce." The test is blind to anything except means. "Relationship" is broader and wrong.

**"Pair" used casually for two independent groups.** Struck from vocabulary. Pairing is a specific term for matched observations on the same unit. My test has no matching. Two piles, no pairs.

**"Standard deviations add when you combine independent things."** They don't. Variances do. The squared structure of the SE-of-difference formula encodes this correctly; stating the rule in terms of std would give wrong answers. Consciously working in variance space until the final square root is the habit to build.

**"Subtracting two noisy means cancels some of the noise."** It doesn't. Independent noise accumulates under subtraction, not cancels. The two noises are uncorrelated, so when you take the difference you get a number that is doubly vulnerable to luck in either direction, not a number that averaged the luck out.

**"A non-significant p-value means the effect is zero."** No. It means the data is consistent with the null, which is different from proving the null. The 95% CI for 震元's reversal effect spanned −0.3% to +1.5% per day; a p of 0.18 obscures this range.

---

## Reasoning patterns reinforced

**Formula breakdown before application.** Added as a permanent rule to memory mid-session: define the problem the formula solves, break the formula into smallest parts, justify each part in plain language, explain each operation, only then state the conclusion. Applied to the SE-of-difference formula and to the t-statistic. Will be applied to every formula going forward.

**Hand-compute before letting software do it.** For the 震元 test, computed t = 1.34 from first principles before calling scipy. This both confirms the mental model is correct and gives a sanity check on the software output. Scipy's t = 1.3388 matched to within rounding. Habit: when you can hand-compute in three minutes, do so.

**Define-then-predict protocol.** Made a concrete prediction (p ≈ 0.18, fail to reject) before running scipy. Prediction held. This is the calibration habit from Session 1; still running it every session.

**Cross-check with a different method.** Ran permutation after parametric. Agreement within 0.7 points. Both methods being wrong in the same direction is possible but much less likely than either one being wrong alone. Habit: whenever a result matters, verify it with a second method whose assumptions are different.

**Convert statistical to economic significance every time.** A p-value is not a trading decision. The sequence "observed effect → transaction cost floor → per-trade edge after costs → Sharpe after costs → probability the true effect clears the cost threshold given the CI" is now the default reading. Any trading-facing statistical result gets this treatment.

**Name the questions hiding inside a vague request.** "Test this on all of 中证1000" hides three different questions (basket-level, stock-averaged, stock-count) with different interpretations. Before coding, disambiguate. Session 3 will commit to one of them explicitly rather than drifting.

---

## Thesis implications for 小盘股

Defensible from Session 2 data, single-stock:

- 震元 2024 shows a point-estimate reversal pattern of 0.61% per day between day-after-up and day-after-down groups. Direction is consistent with overreaction and bid-ask-bounce mechanisms well-documented in small-caps. Magnitude is economically meaningful if real.
- The test cannot distinguish this from zero at conventional thresholds. p = 0.18. CI spans effects that would lose money to effects that would double capital in a year.
- If the effect were real and persisted, after-cost Sharpe would be ~0.54 annualized, held back substantially by the high cost floor on thin small-caps.

Not supported by Session 2 data:

- That any small-cap reversal pattern exists broadly. One stock's point estimate is not a population claim.
- That the effect, if real, would persist across regimes. 2024 was a specific market environment.
- That the magnitudes observed would survive realistic execution at any non-trivial size. The slippage estimate used in the cost analysis was optimistic for a retail account and would scale up unfavorably for institutional size.

The net usable result: Session 2 produced methodology more than findings. The template (split, SE, t-test, permutation cross-check, CI, cost-adjusted Sharpe) is the transferable asset. Session 3 applies the template to a much larger pool where the power problem is eased, and the findings there will be more interpretable.

---

## Open items carried forward

**Function promotion still pending.** Four helpers should go into `hypothesis_testing.py`. Flagged as open in Session 1, still not done, now with one more helper to add (`permutation_mean_diff`). Promote at Session 3 start before the 1000-stock analysis begins.

**Session 3 will commit to basket-level framing.** The question is explicitly "does the 中证1000 basket return series show day-after reversal?" Questions B (stock-averaged) and C (stock-count) remain for later sessions. Making this commitment explicit prevents mission creep during analysis.

**Survivorship and inclusion bias in the 1000-stock pull.** Today's constituent list is not the 2024 constituent list. Stocks demoted out of the index over the last 2+ years are missing; stocks added during that period are overrepresented. Both biases push measured returns up. For reversal-direction testing the bias is probably small (no obvious reason delisted stocks would have systematically different reversal signs), but for magnitude claims there's a caveat to attach.

**Heterogeneity of variances within the basket.** Daily volatility varies substantially across small-caps (some near 2%, some above 5%). Equal-weighting the basket weights all stocks equally regardless of vol, which has implications for how noise combines at the basket level. Worth thinking about whether a vol-weighted or equal-weighted basket is the right construction for the Session 3 test.

**No parallel 2024-2026 pull for 平安银行 or any large-cap comparator.** Session 3 will be small-cap basket only. If we wanted to compare against a large-cap basket (to test whether reversal is a small-cap phenomenon specifically), we'd need 沪深300 data pulled over the same window. Can be added later or run as a separate session if the small-cap result is interesting.

**Stationarity across the 2024-2026 window.** The window contains the September 2024 stimulus rally, post-stimulus consolidation, and whatever's happened in 2025-2026. Session 3 should run the test on the full window and also on subsamples to check whether the effect is driven by one regime.

---

## Bridge to Session 3

Session 3 runs the same two-sample t-test machinery built today on the 中证1000 basket return series over 2024-2026. The test code is essentially copy-paste from the 震元 example. The analytical depth comes from three extensions.

**Extension one: the noise should be dramatically lower.** A basket of ~950 small-caps has idiosyncratic noise reduced by roughly √950 ≈ 31x relative to a single small-cap. Basket daily std should be in the 1.0%-1.5% range rather than 3.3%-3.7%. With SE this much smaller, even small true effects become detectable. If the basket shows reversal at the 0.05%-0.15% per day range, it might reject at p < 0.05 where 震元's 0.61% did not.

**Extension two: the regime cut from Project 1 applies directly.** Removing the September 2024 stimulus week is a well-established technique from Project 1 Session 4. Running the test with and without the stimulus weeks (and whatever comparable event-driven weeks exist in 2025-2026) isolates the bulk-regime reversal pattern from rally-distorted tails. Session 3 should do this as a matter of course.

**Extension three: economic significance at basket level has different interpretation.** An effect that shows up at the basket level is tradeable via an ETF or basket product, not via individual stock selection. Costs change: basket products have management fees but lower per-trade friction, and liquidity is much better. The cost-adjusted analysis will use different numbers than the single-stock 震元 case.

The data pull is running in parallel as I write this. Session 3 starts as soon as it completes. Primary deliverable: a basket-level two-sample test with full-sample and ex-stimulus variants, cost-adjusted economic significance, and honest documentation of the survivorship and inclusion biases in the constituent list.

If the basket result is significant, Session 4 extends to Question B or C (stock-averaged or stock-count). If the basket result is null, Session 4 goes to a different binary signal (volume-based, not sign-based) before moving to Project 5.

---

Session 2 closed. Suggested conversation name for Session 3: `2026-04-22 — Project 4 Session 3: Basket-Level Reversal Test on 中证1000 (2024-2026)`.
