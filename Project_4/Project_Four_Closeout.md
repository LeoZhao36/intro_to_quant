# Project 4 Closeout: Hypothesis Testing

**Completed:** 2026-04-22
**Project location:** Phase 2, Project 4 (Hypothesis Testing), Sessions 1 through 4
**Status:** Closed. Ready for Project 5 (Size Factor).

---

## Reference conversations and documents

Each session has a standalone handoff document and a conversation of its own. This closeout is the master summary and should be read alongside the individual handoffs when detail on any one session is needed.

- `Project 4 Session 1: Null Hypothesis, P-values, and Permutation Tests` → `Project_Four_Session_One_Handoff.md`
- `Project 4 Session 2: Two-Sample t-tests and Cost-Adjusted Sharpe` → `Project_Four_Session_Two_Handoff.md`
- `2026-04-22 — Project 4 Session 3: Multiple Testing and the Bonferroni Correction` → `Project_Four_Session_Three_Handoff.md`
- `2026-04-22 — Project 4 Session 4: Bootstrap and Block Bootstrap` — run in compressed form due to time constraints. This closeout absorbs the session-level summary rather than a separate handoff.

---

## Starting point

I entered Project 4 having finished Project 3 on correlation, regression, and autocorrelation. I could compute Pearson and Spearman correlation, run simple regressions via statsmodels, and read ACF plots to identify autocorrelation at individual lags. I had a working intuition for the difference between statistical and economic significance, a working familiarity with the statsmodels summary output, and an initial encounter with the multiple testing idea from Project 3 Session 5 (the "spurious correlation" simulation exercise).

What I lacked was the machinery to formalize "is this real or noise?" into an answerable question. I could look at a regression coefficient and say "that looks significant" but I could not articulate what the p-value meant, construct a null distribution by hand, or defend a claim that an effect was distinguishable from random variation. The Project 3 autocorrelation findings sat in that ambiguous space: visible patterns, fuzzy about their status.

Project 4 existed to convert that fuzziness into rigor.

---

## Project 4 thesis

Hypothesis testing is not a set of formulas; it is a framework for asking one specific question honestly: how often would this pattern arise if there were no real effect? Every tool in the project (t-test, permutation, Bonferroni, bootstrap) is a variation on that single question, differing in what they assume about the data and what they ultimately report. The project's purpose was to build each tool from its mechanism rather than its formula, accumulate them into a consistent toolkit, and apply that toolkit to my own prior findings with the discipline to accept null results when they appeared.

The deeper thesis: statistical significance is not the same as knowing something is real, and statistical significance is not the same as economic significance. A finding can survive all four tests in the toolkit and still lose money after costs. A finding can fail all four tests and still reflect a real but underpowered signal. The tools are necessary but not sufficient for trading decisions. Project 4 developed the tools; later projects teach what to do with them once a finding clears the statistical bar.

---

## Session-by-session progression

### Session 1: Null Hypothesis, P-values, and Permutation Tests

Built the null-hypothesis framework from scratch using the coin-flip analogy (100 flips, 60 heads, is the coin fair?). The p-value is the answer to "if the null were true, how often would I see data at least this extreme?" Critical distinction established: a p-value of 0.03 does NOT mean there is a 3% chance the null is true; it means the probability of data this extreme UNDER the null is 3%. This is the phrasing error that catches even trained researchers, and I was made to hold the precise wording repeatedly before moving on.

Applied to 平安银行 lag-1 autocorrelation from Project 3 Session 4. The null is "true autocorrelation is zero." Ran a permutation test: shuffle the returns 10,000 times (destroying any real time-ordering), compute lag-1 autocorrelation on each shuffle, count how many shuffles produced a |correlation| at least as large as the observed value. That count divided by 10,000 is the p-value. The observed lag-1 autocorrelation on 平安银行 2024 was small and failed to reject at 0.05.

Standard errors introduced as the 1/√n scaling of noise on averages: the precision of an average improves with the square root of the sample size, not linearly. Doubling the sample size cuts standard error by √2 ≈ 1.41, not by 2. This is why tiny effects become "statistically detectable" at enormous sample sizes that would never be available in practice, and why multi-year intraday backtests can report "significance" on effects that are economically trivial.

The session ended with the realization that the permutation test is distribution-free: it makes no normality assumption, it just asks how often random relabeling produces the observed pattern. This became the template for everything else in the project.

### Session 2: Two-Sample t-tests and Cost-Adjusted Sharpe

Extended the null-hypothesis framework to the two-sample case. Applied to 震元 daily returns split by a binary signal (the specific split is in the Session 2 notebook). Ran both a parametric two-sample t-test (t = 1.34, p = 0.18) and a permutation-based two-sample mean difference test (p = 0.19). Both failed to reject at 0.05, and their close agreement demonstrated the CLT at work: even with fat-tailed daily returns, the sampling distribution of the mean was sufficiently normal-like for the parametric formula to give the same answer as the distribution-free one.

The important lesson of Session 2 was not the null verdict on 震元; it was the distinction between methods that disagree and methods that agree. T-test and permutation gave almost identical p-values because the CLT was delivering on its promise at n = 200+. Had the sample been much smaller or the tails much heavier, the two methods would have diverged, and permutation would have been the more trustworthy of the two. Knowing when to trust which method is the Session 2 skill.

Second major topic: cost-adjusted Sharpe. A raw backtest Sharpe of 0.8 sounds like a real strategy. After transaction costs, stamp tax, slippage, and market impact, the same strategy may produce a net Sharpe below the 中证1000 buy-and-hold benchmark. Cost-adjusted Sharpe is the metric that matters for trade/don't-trade decisions. The session built a helper that computes gross and net Sharpe side by side from a return series and a cost-per-trade parameter. For 小盘股, realistic cost assumptions routinely destroy 30 to 50 percent of raw Sharpe.

The strategic implication: statistical significance and economic significance are separate filters, and in my work to date, the economic filter has bound harder than the statistical one. I have not yet produced a finding whose statistical significance was the binding constraint. Cost adjustment has been.

### Session 3: Multiple Testing and the Bonferroni Correction

Covered in detail in `Project_Four_Session_Three_Handoff.md`. Summary of the content:

The per-test α stays fixed at 0.05 no matter how many tests you run. What grows is the family-wise error rate (FWER), the probability that at least one test in the batch produces a false positive. FWER for n independent tests at per-test α is 1 − (1 − α)ⁿ. Reference points: 5 tests give 23%, 10 give 40%, 20 give 64%, 50 give 92%, 100 give 99.4%. Testing 100 factors at uncorrected α = 0.05 guarantees ~5 "significant" findings even when every null is true.

Bonferroni correction: use α/n as the per-test threshold. For 20 tests at FWER 0.05, require p < 0.0025 per test. Simple rule, two independent justifications (union bound, Taylor approximation), zero assumptions about test correlation structure.

Two prediction misses documented in the handoff, both substantial. My initial intuition for FWER at n = 20 was "under 5%." Correct answer: 64%. My initial intuition for Bonferroni-corrected threshold at n = 20 was p < 0.0001. Correct answer: 0.0025. The magnitude of these misses is the pedagogical content of the session.

Applied Bonferroni to my own work: the reversal-thread family across Sessions 1 and 2 contains 2 formal p-values. α_Bonferroni = 0.025. Neither test clears even the uncorrected 0.05 threshold. The correction confirmed rather than changed the null conclusion. Bonferroni binds when apparent wins exist; it has nothing to strip from a null result.

The broader implicit family of "X differs from Y" claims across Projects 1 to 4 is roughly 30 to 50 tests. α_Bonferroni at that family size ≈ 0.001 to 0.0017. No formal p-value I have produced clears that threshold either. Statistical significance has not been the operative constraint on any conclusion so far; honest null reporting has been.

Connected to Harvey-Liu-Zhu (2016) on the academic finance literature as a field-wide multiple testing disaster: 300+ candidate factors published, no correction applied across the field. Their proposed stricter bar is t > 3 (p < 0.001).

### Session 4: Bootstrap and Block Bootstrap

Run in compressed form. The session completed the Project 4 toolkit with a fourth and final tool: bootstrap confidence intervals.

**The core idea of bootstrap.** You ran an experiment once and got one number. You want to know how much that number would have bounced around if you could have repeated the experiment many times. You can't repeat it, because markets don't rewind. So bootstrap treats your one sample as a mini-copy of the world, draws fresh samples FROM your sample with replacement, computes the statistic on each fresh sample, and uses the spread of those values as the confidence interval. The logic: your sample is the best available estimate of what the true population looks like, so resampling from it mimics the randomness of drawing a fresh sample from reality.

**The gap bootstrap fills.** The t-test gives a CI for means when data is roughly normal. The permutation test gives a p-value against a null but not a CI on the estimate. Bonferroni adjusts thresholds across families. None of them gives a CI for a Sharpe ratio, a maximum drawdown, a correlation, or a rank IC. Bootstrap does, for any statistic, without assuming normality.

**Three illustrative examples were run on 500 fat-tailed simulated daily returns:**

1. **Mean CI: bootstrap matches t-test.** Bootstrap 95% CI [-0.00178, +0.00212], t-test 95% CI [-0.00179, +0.00213]. Agreement within 0.5%. For the mean of a reasonably sized sample, bootstrap adds no information over the t-test. The CLT does the work in both cases.

2. **Sharpe CI: bootstrap reveals shocking uncertainty.** Point estimate Sharpe 0.117. Bootstrap 95% CI [-1.265, +1.459]. Width 2.72. With 500 days of data, you cannot distinguish catastrophic from institutional-grade. This is the single most important output of the session: every Sharpe number in backtests, published papers, and JoinQuant reports carries enormous uncertainty, and almost nobody attaches a CI.

3. **Serial correlation breaks naive bootstrap; block bootstrap fixes it.** On AR(1) returns with lag-1 autocorrelation of +0.36, naive bootstrap gave CI width 0.00399. Block bootstrap with 20-day blocks gave CI width 0.00669, 1.67x wider. Naive bootstrap silently understates uncertainty on correlated data. It looks like it's working. It isn't.

**The block bootstrap mechanism.** Plain bootstrap draws individual observations, which shatters the day-to-day correlation structure. Block bootstrap draws contiguous chunks (20 days each, for daily data), preserving local correlation within chunks. Between chunks, correlation is lost, but between-chunk correlation was weak anyway. The result is honest uncertainty estimation on time-series statistics.

**Three failure modes filed:**
1. Tails get clipped twice. Bootstrap can never invent values more extreme than the original sample's extremes. Combined with 涨跌停 clipping from Project 1, 小盘股 risk estimates accumulate two layers of "measured extreme ≠ true extreme."
2. Serial correlation, as above. Fix: block bootstrap for any time series.
3. Non-stationarity. Bootstrapping across regimes (2015 crash + 2023 calm) gives a CI that describes neither. Bootstrap within a regime, not across.

**Operational rule for all later projects:** every Sharpe ratio, factor IC, backtest metric, or correlation reported from Project 5 onward gets a bootstrap CI attached. Point estimates alone are misleading.

---

## Consolidated conceptual ground

The spine of Project 4, distilled to statements I can defend with specific numbers or reasoning.

**Every hypothesis test asks the same question in different forms: how often would I see data this extreme if there were no real effect?** The t-test answers it using a parametric formula that assumes normality of the sampling distribution. The permutation test answers it by relabeling data thousands of times and counting extremes. Bootstrap inverts the question into a CI on the estimate, but the underlying logic is the same. Knowing these are the same question under different assumptions is the unifying insight of the project.

**The p-value is a conditional probability, not a posterior.** P(data this extreme | null is true) is NOT the same as P(null is true | data). The distinction matters because the first is what the p-value reports, and the second is what people often assume. A p-value of 0.03 does not mean the null has a 3% chance of being true.

**Standard errors scale with 1/√n.** Precision of an average improves with the square root of sample size. This is why large samples can detect tiny effects as "statistically significant" even when those effects are economically trivial, and why the distinction between statistical and economic significance sharpens as sample sizes grow.

**The CLT lets parametric tests work on non-normal data, but only for the mean and only at moderate-to-large n.** Your returns can have fat tails and the t-test is still fine for testing mean differences at n = 200+. For statistics other than the mean (Sharpe, drawdown, correlation), the CLT does not help, which is where bootstrap becomes necessary.

**Per-test error rates compound into family-wise error rates via 1 − (1 − α)ⁿ.** Testing more hypotheses without correction inflates the probability that at least one false positive appears in the batch. At n = 100 tests, FWER is essentially 1. The correction is Bonferroni (α/n per test), which relies on the union bound and requires no independence assumption.

**Bonferroni is about evidential honesty.** A p = 0.04 from a single targeted test carries different weight than a p = 0.04 from a family of 30 tests where you kept the winner. The correction encodes this difference in the threshold itself, so the reader does not need to know the family size to interpret the result.

**The correction cannot manufacture findings from null data.** If no test clears the uncorrected threshold, Bonferroni has nothing to strip. Applying it mechanically to null data is an empty gesture, not wrong but not useful.

**Bootstrap treats the sample as a model of the population.** Resampling with replacement from the sample approximates sampling from the true distribution, justified formally by Glivenko-Cantelli. The approximation tightens as n grows.

**Bootstrap works for any statistic.** Mean, Sharpe, drawdown, correlation, rank IC, whatever. Replace one line of code. This is why it becomes the default CI method from Project 5 forward.

**Bootstrap breaks in three places: tails, serial correlation, regime changes.** The first is structural and has no fix. The second is fixed by block bootstrap. The third is fixed by bootstrapping within a regime rather than across.

**Statistical significance and economic significance are separate filters.** A factor that survives t-test, permutation, Bonferroni, and bootstrap CI can still lose money after costs. A factor that fails statistical filters can still reflect real but underpowered signal. Trading decisions require both filters to clear, not just one.

---

## Technical skills acquired

Production-ready fluency:

- Run a permutation test for any statistic: shuffle labels or returns, recompute statistic, count extremes, divide by iterations.
- Run a two-sample t-test via `scipy.stats.ttest_ind` and interpret t, p, and CI.
- Compute FWER = 1 − (1 − α)ⁿ from first principles using the complement trick.
- Apply Bonferroni correction: divide target FWER by n to get per-test threshold.
- Compute Bonferroni-adjusted ACF confidence band: ±z_(α/n/2)/√N.
- Run a bootstrap CI for the mean, Sharpe ratio, correlation, or any statistic via the vectorized `rng.integers(0, n, size=(n_boot, n))` pattern.
- Run a block bootstrap CI on a time series by sampling contiguous chunks.

Working fluency:

- Distinguish Bonferroni from Šidák, and articulate why Bonferroni is the default when test correlations are unknown.
- Distinguish FWER (Bonferroni's target) from false discovery rate (Benjamini-Hochberg's target). Name only, deferred until it binds.
- Recognize when a research question has produced a family of tests rather than a single test, and count the family honestly.

Vocabulary now readable in papers without lookup:

- Null hypothesis, p-value, Type I error, Type II error, statistical power, effect size.
- Parametric vs non-parametric, distribution-free, permutation test, bootstrap.
- FWER, FDR, Bonferroni, Šidák, Holm-Bonferroni, Benjamini-Hochberg.
- Union bound, Boole's inequality, Glivenko-Cantelli theorem.
- Multiple testing problem, p-hacking, publication bias, replication crisis.
- Harvey-Liu-Zhu t > 3 threshold.
- Block bootstrap, stationary bootstrap, moving block bootstrap.

---

## Codebase

Functions written across Sessions 1 through 4, currently scattered across per-session notebooks:

- `permutation_correlation(x, y, n_iter)` — Session 1, for lag-k autocorrelation and Pearson/Spearman correlation tests.
- `permutation_mean_diff(a, b, n_iter)` — Session 1/2, for two-sample mean difference.
- `t_test_two_sample(a, b)` — Session 2, thin wrapper around `scipy.stats.ttest_ind` that returns t, p, and CI in a dict.
- `cost_adjusted_sharpe(returns, cost_per_trade, turnover)` — Session 2, computes gross and net annualized Sharpe.
- `acf_band(n_obs, n_tests, family_alpha=0.05)` — Session 3, returns Bonferroni-adjusted ACF confidence band half-width.
- `bootstrap_ci(data, statistic, n_boot=10000, ci=0.95, seed=None)` — Session 4, general-purpose bootstrap CI for any 1-D statistic.
- `block_bootstrap_ci(data, statistic, block_size=20, n_boot=5000, ci=0.95, seed=None)` — Session 4, time-series version.

All seven belong in `hypothesis_testing.py` before Project 5 Session 1 begins. The function-promotion task was deferred three consecutive sessions; Session 4 makes it four. It is the first operational task of Project 5.

Data artifacts from Project 4 sessions:

- `data/pa_bank_returns_2024.csv` — Session 1, 平安银行 2024 returns panel with permutation test results appended.
- `data/zhenyuan_two_sample.csv` — Session 2, 震元 daily returns with the binary signal column and group labels.
- Notebooks: `P4_Session_One.ipynb`, `P4_Session_Two.ipynb`, `P4_Session_Three.ipynb`, `P4_Session_Four_Compressed.ipynb`.

---

## Misconceptions corrected

**"A p-value of 0.03 means there's a 3% chance the null is true."** Incorrect. The p-value is a conditional probability in the other direction: P(data this extreme | null is true) = 3%. The posterior on the null requires Bayes' theorem and a prior, neither of which a frequentist p-value provides.

**"If the parametric and distribution-free tests disagree, trust the parametric one because it's more powerful."** Backwards. Disagreement between t-test and permutation usually indicates the t-test's normality assumption is failing. When they agree, the CLT is working. When they disagree, trust permutation.

**"Per-test α grows with the number of tests."** It does not. α stays fixed at whatever you set it. FWER is the compounded quantity, and the confusion comes from anchoring to the per-test rate when the family-level rate is what matters.

**"Bonferroni always changes your conclusions."** Only when apparent wins exist. For null results at the uncorrected threshold, Bonferroni is empty. It binds specifically when findings need to defend themselves against multiplicity, which has not yet happened in my work but will in Project 5.

**"Bootstrap gives a better answer than the t-test."** Not for means with big samples; they agree to within a percent. Bootstrap's value is in the statistics where no analytical CI exists (Sharpe, drawdown, IC), and in its robustness when the t-test's assumptions are shaky.

**"A Sharpe of 0.8 means the strategy is good."** Point estimates on Sharpe have huge uncertainty even at n = 500. The 95% bootstrap CI on a reported Sharpe of 0.8 could easily span 0.2 to 1.4. Only bootstrap reveals this, and without it, the point estimate is misleading.

**"Multiple testing and economic significance are the same kind of filter."** They are not. Multiple testing is a statistical correction: does this survive when you account for all the tests you ran? Economic significance is a cost filter: does this survive when you account for what it costs to trade? A finding can clear one and fail the other. Project 5 will require both.

---

## Habits built or reinforced

**Commit to a numeric prediction before derivation.** Applied throughout Session 3: FWER at n = 20, required per-test α at n = 20, whether Project 3's ACF results survived correction. Two predictions missed badly, and the misses were the pedagogical content. Continue for every new piece of arithmetic.

**Define the null precisely before computing anything.** Every hypothesis test starts with explicit articulation of what "no effect" looks like in the data. The null for autocorrelation is "returns are exchangeable across dates." The null for a mean difference is "the two groups come from the same distribution." Sloppy null statements produce sloppy p-values.

**Use the complement trick for "at least one" probabilities.** P(at least one) = 1 − P(zero) is always cleaner than enumeration. Applied in Session 3 for FWER; applicable to any "some but not all" question.

**Count the family before applying any correction.** Every decision branch is an implicit test. Honest counting is a habit, not a reflex.

**Check whether apparent wins exist before applying a correction.** A correction has nothing to do when all tests are null. Null data plus correction equals null, not "stronger null."

**Separate the arithmetic question from the framing question.** A correct derivation with imprecise language loses most of the pedagogical value. Any time a mechanism gets stated in plain language, the phrasing needs to be as precise as the formula.

**Attach a bootstrap CI to every point estimate from now on.** Operational takeaway from Session 4. Sharpe, IC, factor returns, correlation, anything. Point estimates alone mislead about how much noise surrounds them.

**Default to block bootstrap for time series.** Naive bootstrap on correlated data silently gives CIs that are too narrow. For any statistic computed on returns or other time-series data, reach for block bootstrap with block size around 20 for daily data.

---

## Thesis implications for 小盘股

Defensible from Project 4:

- No evidence for small-cap short-term reversal in my work to date. Session 1 permutation on 平安银行 lag-1 failed to reject. Session 2 two-sample test on 震元 failed to reject at p = 0.18/0.19. Session 3 Bonferroni correction confirmed the null across both. The absence of evidence is real but conditional on my specific tests; it does not prove reversal is absent in the broader universe.
- Statistical significance has not been the binding constraint on any conclusion in Projects 1 to 4. The broader implicit family of ~30 to 50 "X differs from Y" claims has α_Bonferroni ≈ 0.001 to 0.002, and no formal p-value has cleared that threshold. The honest-null-reporting habit has been doing the real work.
- Cost-adjusted Sharpe has been the more binding filter in practice. Session 2 established that realistic 小盘股 transaction costs destroy 30 to 50 percent of raw Sharpe, which routinely pushes borderline strategies below the buy-and-hold benchmark. This is the economic-significance layer that the statistical tests alone do not surface.
- Serial correlation in 小盘股 returns, while small in magnitude, is real and matters for bootstrap. Any future bootstrap CI on a 小盘股 statistic should use block bootstrap by default.

Not supported by Project 4:

- That small-cap reversal or other short-term effects do not exist. Absence of evidence in two low-powered single-stock time-series tests is weak evidence of absence. The cross-sectional approach in Project 5 buys power quickly by pooling across many stocks and may reveal effects that my single-stock tests cannot detect.
- That Bonferroni is the right correction for Projects 5 to 6. Factor families have correlation structure (momentum at 60 days and 90 days are highly correlated), and Bonferroni is strictly conservative under positive correlation. Holm-Bonferroni or Benjamini-Hochberg may be more appropriate. The choice needs to be made explicitly at the start of Project 5.
- That a finding surviving all four statistical filters is tradeable. Project 4 established that statistical significance and economic significance are separate layers. A factor that clears Bonferroni and has a bootstrap CI excluding zero can still fail the cost filter. Projects 5 through 8 will need to combine these filters explicitly.

Net usable result: Project 4 produced a diagnostic toolkit, not a finding. The toolkit converts the large-scale factor exploration coming in Projects 5 and 6 from a p-hacking exercise into a disciplined investigation. Its value appears when it starts binding, which will happen in Project 5 Session 2 or 3 when the first factor candidates with apparent significance need to defend themselves against both multiplicity and transaction costs.

---

## Open items carried forward

**Function promotion into `hypothesis_testing.py`.** Four sessions of deferral. Seven functions need to be lifted from notebook cells into a clean module: `permutation_correlation`, `permutation_mean_diff`, `t_test_two_sample`, `cost_adjusted_sharpe`, `acf_band`, `bootstrap_ci`, `block_bootstrap_ci`. First operational task of Project 5 Session 1.

**Choice of multiple-testing correction for Project 5.** Bonferroni is the conservative default. For factor families with known positive correlation structure (momentum lookbacks, value definitions), Holm-Bonferroni or Benjamini-Hochberg is more appropriate. The choice should be made explicitly at Project 5's start rather than drifting. My preliminary view: Bonferroni for the factor-discovery question (where false positives are very costly), BH for the subsequent robustness checks (where false negatives are equally problematic).

**Deferred basket-level reversal test on 中证1000 2024-2026.** Session 2 planned it, Session 3 diverged from it, Session 4 absorbed the decision into Project 5. The cross-sectional framework in Project 5 answers the reversal question more powerfully than a time-series test on a single basket, so the deferral is pedagogically defensible rather than a loose thread to regret.

**Broader implicit family size audit.** The 30 to 50 figure for implicit tests across Projects 1 to 4 is an estimate, not a count. A formal enumeration of every directional claim in the four projects' handoffs would tighten the Bonferroni threshold from "around 0.001 to 0.002" to a single number. Low priority; defer unless a conclusion from earlier projects becomes operationally important.

**Stationary bootstrap as an alternative to block bootstrap.** Block bootstrap with fixed block size 20 is the default from Session 4. Stationary bootstrap (Politis-Romano 1994) uses random block lengths drawn from a geometric distribution, which smooths out some of the fixed-block artifacts. Worth knowing as an alternative; not a priority unless the fixed-block version produces visibly odd CIs in Project 5.

**FDR methods for large factor families.** Benjamini-Hochberg (BH) controls false discovery rate rather than family-wise error rate. When the family is large (say, 50+ factors) and you expect many true positives mixed with many nulls, BH is more appropriate than Bonferroni, which assumes essentially all nulls are true. Worth preparing for if Project 5 or 6 ends up screening dozens of factor variants.

---

## Bridge to Project 5

Project 5 is the size factor: testing whether smaller A-share stocks earn higher forward returns than larger ones, using quintile sorting and Information Coefficient (IC) as the primary methodology. Every tool built in Project 4 applies there.

**Permutation tests.** The null for factor testing is "the factor has no predictive power," which translates to "the return after high-factor days is exchangeable with the return after low-factor days." Permutation enforces this by shuffling factor-to-return assignments across stocks and dates, giving a distribution-free p-value on the factor's IC.

**T-tests.** Quintile return differences (Q1 minus Q5 return, monthly) produce a time series whose mean is the monthly factor return. Its t-statistic is the standard parametric test for "is this mean distinguishable from zero?" CLT applies because we're testing a mean, and the monthly aggregation smooths the daily tails.

**Bonferroni.** Project 5 Session 1 and 2 together will test size-quantile returns, size IC, size-factor stability across subperiods, size-factor stability across market-cap thresholds, and several robustness variants. The family size lands somewhere between 5 and 15 depending on how the variants are counted. α_Bonferroni at n = 10 is 0.005. The factor will need to clear that, not just the uncorrected 0.05.

**Bootstrap.** Every size-quintile return, every IC, every long-short Sharpe in Project 5 gets a bootstrap CI attached. Block bootstrap by default, block size 20 for daily IC, block size 3 for monthly returns (where monthly observations are close to independent so the block size can be small). This is the operational change from Project 4: point estimates alone are no longer acceptable output.

The Project 1 caveats (survivorship bias, inclusion bias, 涨跌停 clipping) compound with the Project 4 toolkit in Project 5 in ways that matter. A size factor computed on today's index constituents inflates small-cap returns because delisted small stocks are silently missing. Bootstrap CI on a biased estimate is a precise CI around the wrong number. Project 5's first session includes point-in-time membership data as a hard requirement, not an optional refinement.

The first Project 5 Session 1 deliverable will be the function promotion into `hypothesis_testing.py` plus the point-in-time membership pull. The second deliverable, in Session 2, will be the first factor test with the full toolkit applied: quintile sort + IC + bootstrap CI + Bonferroni threshold + cost-adjusted quintile returns. That combination is the Project 4 toolkit in its operational form.

---

Project 4 is closed. Suggested conversation name for the next session: `2026-04-XX — Project 5 Session 1: Size Factor, Point-in-Time Membership, and Function Promotion`.
