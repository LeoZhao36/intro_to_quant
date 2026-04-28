# Project 4 Session 3 Handoff: Multiple Testing and the Bonferroni Correction

**Completed:** 2026-04-22
**Session location:** Phase 2, Project 4 (Hypothesis Testing), Session 3
**Status:** Closed. Next session is Project 4 Session 4 or the deferred basket-level reversal test; fork explained in Bridge section.

---

## Glance-back summary

Simple takeaways for when you come back to this later.

- **Per-test α stays fixed at 0.05 regardless of how many tests you run. What grows is the family-wise error rate (FWER), the probability that at least one test in the batch produces a false positive.** This is the distinction the entire session turns on.

- **FWER for n independent tests at per-test α is 1 − (1 − α)ⁿ.** Reference points: 5 tests give 23%, 10 give 40%, 20 give 64%, 50 give 92%, 100 give 99.4%. By 100 tests FWER is effectively certainty. Testing 100 factors at uncorrected α = 0.05 guarantees ~5 "significant" findings even when every null is true.

- **Bonferroni correction: use α/n as the per-test threshold. For 20 tests at FWER 0.05, require p < 0.0025 per test.** Simple rule, two independent justifications (union bound, Taylor approximation), zero assumptions about test correlation structure.

- **Budget metaphor: total false-positive budget is α. Split equally among n tests. Each gets α/n.** The union bound guarantees the total cannot exceed budget regardless of how tests correlate.

- **My initial intuition for FWER at n = 20 was "under 5%." The correct answer is 64%.** Gap of roughly 60 percentage points. The natural human read of "5% per test" stays anchored to 5%; the correct calculation compounds the per-test survival probability (0.95) twenty times.

- **My initial intuition for the Bonferroni-corrected threshold at n = 20 was p < 0.0001. Correct answer is 0.0025.** Off by a factor of 25. The 0.0001 magnitude would be right for roughly 500 tests, not 20.

- **The reversal-thread family across Project 4 Sessions 1 and 2 contains 2 formal p-values. α_Bonferroni = 0.025.** Neither test clears even the uncorrected 0.05 threshold (Session 2 震元 test p = 0.18). Correction confirms rather than changes the null conclusion. Bonferroni binds only when apparent wins exist; it has nothing to strip from a null result.

- **A broader implicit family across Projects 1-4 covers roughly 30-50 claims of the form "X differs from Y" or "this is not noise." α_Bonferroni at that family size ≈ 0.001-0.0017.** No formal p-value I have produced clears this threshold either. Statistical significance has not been the operative constraint on any conclusion so far; honest null reporting has been.

- **P-hacking and publication bias turn the academic finance literature into a field-wide multiple testing disaster. Harvey, Liu, and Zhu (2016) document 300+ candidate factors and argue for a stricter t > 3 (p < 0.001) threshold for "real" discovery.** Under the stricter bar, roughly half of published factors fail to replicate.

- **The correction is not an optional cleanup step. It is how you stay honest about what your evidence actually shows.** A p = 0.04 from a targeted single test is different evidence from a p = 0.04 from a family of 30 tests where you kept the winner. Bonferroni is the arithmetic encoding of that honesty.

---

## Reference conversations

- `2026-04-22 — Project 4 Session 3: Multiple Testing and the Bonferroni Correction`

Single conversation covering the full session. No separate reference document needed; the conceptual ground fits in one thread.

---

## Starting point

Entered Session 3 having completed Session 2 earlier the same day. Had working command of the single-test hypothesis-testing machinery: null distributions, p-values as counting exercises, standard errors as 1/√n-scaled noise on averages, CLT as the justification for parametric tests on non-normal data at moderate n, two-sample t-tests as the template for binary-signal splits, permutation tests as a distribution-free cross-check.

Gap: no exposure to the multi-test setting. Every test I had run up to this point was implicitly treated as standalone, with α = 0.05 taken as the universal threshold regardless of how many other tests surrounded it. The concept of a "family" of tests did not exist in my vocabulary, and I had no tool for thinking about how running many tests changes the meaning of any individual p-value.

Also entering with no appreciation for how quickly FWER compounds. My initial prediction for FWER across 20 independent tests was "under 5%," which is the natural but wrong human intuition that treats the whole batch as if it shared the per-test rate.

---

## Session 3 thesis

A p-value is a per-test quantity. Research questions are family-level. The arithmetic that bridges the two is the family-wise error rate formula, and the simplest correction that keeps FWER bounded is Bonferroni. Owning this lesson means being able to count the family correctly, apply the correction mechanically, and articulate why the correction is about evidential honesty rather than statistical bookkeeping.

The operational value of the lesson is not immediate. My current work through Project 4 does not contain enough tests in any single family for the correction to bind. The lesson's payoff comes in Projects 5 and 6, where factor screening will produce 20-50 tests in a single family and the correction will change my conclusions, not just confirm them.

---

## Progression through the session

### Part one: the ACF hook

Opened with a callback to Project 3 Session 4, where I computed the autocorrelation function on a small-cap at lags 1 through 20 and checked which fell outside the 95% confidence band. The band is the visual form of "p < 0.05 per lag." Twenty lags tested; twenty implicit hypothesis tests.

Question posed: if the stock has zero true autocorrelation at every lag, how many of the 20 bars would fall outside the band on average?

My answer: "around at least 1." Direction right, arithmetic fuzzy. Correct answer is exactly 1, on average, because expected count across n independent Bernoulli trials with success probability α is nα = 20 × 0.05 = 1.0.

The correction to my phrasing that mattered more than the number: "on average" is a different quantity from "at least one with what probability." The expected value across many repetitions is 1. The probability that any single run produces at least one false positive is a separate question with a different answer. Separating these two questions was the entire point of the opening.

### Part two: FWER derivation

Asked to commit to a probability range for "at least one false positive in 20 tests" before seeing the math. My answer: under 5%. The reasoning in my head was that per-test α is 5%, so the whole batch should sit around 5% too. This was wrong, and the session needed the number in my hands before showing the derivation so the gap would land.

Derivation walk-through:

Direct enumeration is awkward because "at least one" covers cases from exactly-one to exactly-twenty. The complement trick simplifies: P(at least one) = 1 − P(zero). The event "at least one false positive" and the event "zero false positives" partition the sample space, so their probabilities sum to 1.

P(zero false positives) is tractable. Per-test probability of correctly not rejecting under a true null is 1 − α = 0.95. Tests are assumed independent, so the joint probability that all 20 correctly do not reject is 0.95²⁰.

Formula breakdown of 0.95²⁰:
- 0.95: per-test probability of not producing a false positive.
- Exponent 20: number of tests.
- Raising to the power: correct operation because for independent events, the probability that all of them happen is the product of individual probabilities. Independent means no test's outcome changes the others'. Multiplying is the encoding of that independence.

0.95²⁰ ≈ 0.358. So P(at least one false positive) = 1 − 0.358 = 0.642. About 64%.

My prediction: under 5%. Truth: 64%. Gap of roughly 60 percentage points, larger than any numeric miss so far in the curriculum. The session held the number up deliberately rather than smoothing past it. The miss is the whole pedagogical event.

### Part three: the FWER table

Built the reference table that should flash in my head any time I run multiple tests:

| n tests | FWER at α = 0.05 |
|---|---|
| 1 | 5% |
| 5 | 23% |
| 10 | 40% |
| 20 | 64% |
| 50 | 92% |
| 100 | 99.4% |

At n = 100, FWER is essentially 1. This is the mechanism behind the Harvey-Liu-Zhu claim that the academic finance literature has a field-wide false-positive problem: 300+ factors published over decades, each tested at α = 0.05, no correction for the size of the field-wide family.

### Part four: deriving the corrected per-test α

Target: find the per-test α that produces FWER = 0.05 across 20 tests.

My prediction before derivation: "dramatically shrink... around 0.0001." Magnitude wrong.

Derivation:

1 − (1 − α)²⁰ = 0.05
(1 − α)²⁰ = 0.95
1 − α = 0.95^(1/20) ≈ 0.99744
α ≈ 0.00256

The 20th root makes hand-computation awkward. Bonferroni's rule of α/n = 0.05/20 = 0.0025 is the approximation. The exact value (called the Šidák correction) is 0.00256. The difference is 2%, and Bonferroni is always the stricter (more conservative) of the two.

My 0.0001 would be correct for roughly n = 500 tests. Off by a factor of 25 in the other direction.

### Part five: why α/n works

Two independent justifications, both worth owning.

**Union bound (Boole's inequality).** The probability that at least one of n events happens is at most the sum of their individual probabilities:

P(A₁ ∪ A₂ ∪ ... ∪ Aₙ) ≤ P(A₁) + P(A₂) + ... + P(Aₙ)

This inequality holds for any set of events, with any correlation structure, with no independence assumption. Applied to hypothesis tests: if each test has per-test false-positive probability α, the family-wise probability is at most n × α. Setting per-test α to (target FWER)/n bounds the total at target FWER. The union bound does all the work; independence is not required. This is why Bonferroni is the default correction in settings where test correlations are unknown or hard to specify.

**Taylor approximation.** For small α, (1 − α)ⁿ ≈ 1 − nα. Plugging in: FWER = 1 − (1 − α)ⁿ ≈ 1 − (1 − nα) = nα. Inverting gives α ≈ FWER/n. Bonferroni is the first-order approximation of Šidák. The approximation is tight when α is small, which is always the regime you are in for significance testing. This is why Bonferroni feels wasteful but is actually nearly exact at typical significance levels.

### Part six: the budget metaphor

Total false-positive budget for the investigation is α. The investigation contains n tests. Split the budget equally: each test gets α/n. The union bound guarantees the total error across all tests cannot exceed budget no matter how tests correlate. Equal weighting is a default choice based on "no prior information about which tests are more likely to produce true positives"; weighted Bonferroni exists but requires pre-specifying weights without peeking at the data, which is rarely done in practice.

### Part seven: applying Bonferroni to my own work

The session plan's checkpoint exercise assumed I had significant findings to correct. I caught that my Project 3 Session 4 ACF result was already null at the uncorrected threshold: no lag crossed the 95% band. A stricter Bonferroni threshold has nothing to strip away from a null result. The correct writeup is one sentence: "No lag showed autocorrelation significantly different from zero at the uncorrected 0.05 level, which implies no lag clears the Bonferroni-corrected 0.0025 level either."

Catching this myself mattered. The instinct to apply the correction mechanically even when no findings existed would have been the wrong lesson. Bonferroni binds when apparent wins need to defend themselves; it does not manufacture weaker verdicts from null findings.

The more substantive application was to the cumulative reversal thread across Project 4 Sessions 1 and 2:

- Session 1 permutation-based p-value on 平安银行 lag-1 autocorrelation: 1 formal test.
- Session 2 震元 two-sample test (parametric t = 1.34, p = 0.18; permutation p = 0.19, counted as one test since both methods answer the same question): 1 formal test.

Reversal-thread family size: **2 formal tests**. α_Bonferroni = 0.05/2 = 0.025. Neither test clears even the uncorrected 0.05 threshold. The correction changes nothing about the conclusion. No evidence for small-cap reversal in any work to date.

Broader implicit family across Projects 1-4: every "this looks different from zero," "this kurtosis is high," "this Sharpe clears costs" is an informal hypothesis test. Rough count: 30-50 implicit claims across four projects. Bonferroni at n = 40 is α/40 = 0.00125. No formal p-value I have produced clears this threshold either. Statistical significance has not been the operative constraint on any conclusion, because I have been honest about null results where they appeared.

### Part eight: p-hacking and the publication filter

The academic finance literature is a massive implicit multiple testing problem. Harvey, Liu, and Zhu (2016) estimate 300+ candidate return predictors published across decades. At uncorrected α = 0.05 applied test-by-test, field-wide FWER is essentially 100%, with an expected ~15 "significant" findings by pure chance even under zero true effects.

P-hacking mechanisms (ways the implicit family grows without acknowledgment):
- Trying multiple sample periods.
- Trying multiple definitions of the same factor.
- Trying multiple subsets of the universe.
- Trying multiple functional forms.
- Adding and removing control variables.
- Stopping data collection the moment the result becomes significant.

Each decision is an implicit test. Reporting only the final number hides the family size.

Publication bias (field-wide filter):
- Journals prefer significant results.
- Null results stay in file drawers.
- The published literature is the winners' bracket of all analyses run, not a representative sample.

Even if individual researchers were fully honest about their personal family sizes, the aggregate publication filter produces a field-wide false-positive rate well above nominal 5%.

Harvey-Liu-Zhu's proposed correction: effective threshold for "real" factor discovery should be something like t > 3 or p < 0.001, not the conventional t > 2 or p < 0.05. Under the stricter bar, roughly half of published factors fail to replicate. The replication crisis in finance is a multiple-testing problem at field scale, not a problem of fraud.

### Part nine: when multiple testing shows up in practice

This was the question I asked mid-session, and the answer converts the abstract mechanics into a checklist I can recognize.

Situations I will encounter in Projects 5-8:

**Factor screening (Projects 5-6).** Size, value (P/E and P/B), momentum (multiple lookback windows), volatility, quality (multiple definitions), turnover, liquidity. Easily 15-30 factor tests in a single family, sometimes more with variants. All answering the same underlying question: "which characteristics predict next-period returns in A-share small-caps?"

**Parameter sweeps within a single factor.** Momentum with 20, 60, 120, 250-day lookbacks is four tests, not one. Reporting only the best-performing lookback is implicit p-hacking unless the family is declared.

**Stock universe subsets.** Same factor tested on 小盘股, 沪深300, 中证500, 中证1000, 创业板, 科创板 is a family of 6. Reporting the universe where the factor worked best is a multiple test with the winner kept.

**Time period robustness checks.** Full sample, split halves, with or without specific events (e.g., 2022 COVID distortion), with or without the 2024 stimulus week. Each choice is a test.

**Multi-horizon return tests.** Does this factor predict 1-day returns? 5-day? 20-day? 60-day? Four horizons, same factor.

**The ACF case.** Testing autocorrelation at lags 1 through 20 is 20 tests. Met in Project 3 Session 4.

**Portfolio construction choices.** Equal-weighted, value-weighted, rank-weighted, score-weighted constructions are a family of 4.

Common thread: any time a research question is answered by trying multiple approaches, definitions, subsamples, parameters, or horizons, a family exists. The family size is the count of all approaches tried, not only the ones reported.

### Part ten: why correction is required, not optional

Two layers of answer.

**Layer one: the arithmetic is real and unavoidable.** Running 20 tests at uncorrected α = 0.05 gives 64% FWER. Running 100 gives 99.4%. If I do not correct, I will call noise "signal" at exactly the rate the math predicts. The correction aligns reported confidence with actual confidence. Skipping it does not save work; it just produces inaccurate reported confidence.

**Layer two, which is more important: the correction is about evidential honesty, not statistical bookkeeping.** A p = 0.04 from a targeted single test is genuinely different evidence from a p = 0.04 from a family of 30 tests where the winner was kept. The raw number looks identical. The evidential weight is not. Anyone reading the work needs to know which situation they are looking at, because the appropriate inference is totally different.

Bonferroni converts "evidence from a shotgun approach" into "evidence equivalent to a single targeted shot." Skipping the correction means quietly misrepresenting how easy it was to find the finding. The misrepresentation is about how much shopping I did, which is information a reader needs and which the raw p-value does not carry.

### Part eleven: sharpened takeaway

The one-paragraph version of Session 3, in corrected language:

"The per-test false-positive rate stays fixed at α = 0.05 regardless of how many tests I run. But the probability that at least one test in the family is a false positive, the family-wise error rate, grows fast with n: 23% at 5 tests, 64% at 20, 99% at 100. So as I run more tests without correction, my likelihood of reporting at least one result that is really noise approaches certainty even when every null is true. The Bonferroni correction, α/n per test, forces the family-wise error rate back down to α regardless of how many tests I ran. Without correction, a p of 0.04 from a family of 30 tests is not the same evidence as a p of 0.04 from a single targeted test. With correction, the threshold changes to reflect how much shopping I did, so the reported result carries accurate evidential weight."

---

## Consolidated conceptual ground

Statements I can defend with specific numbers from this session.

**Per-test error rates compound into family-wise error rates via the formula 1 − (1 − α)ⁿ.** The shape of this function matters: it rises fast from small n, flattens as it approaches 1, and is effectively 1 by n = 100. The mechanism is straightforward probability: the joint probability that all n tests correctly do not reject is (1 − α)ⁿ under independence, so the complement is the probability that at least one incorrectly rejects.

**The complement trick is the clean way to compute "at least one" probabilities.** Direct enumeration of "at least one out of n" requires summing many mutually exclusive cases. Computing "zero out of n" is one multiplication. The complement relation P(at least one) = 1 − P(zero) converts the messy computation into a clean one. This trick generalizes far beyond hypothesis testing.

**Independence assumption enters through the multiplication step.** If tests are independent, joint probability that all correctly don't reject is the product of individual probabilities. If tests are correlated, the joint probability is different, generally larger than the product (positively correlated tests tend to succeed or fail together, so "all correctly don't reject" is more likely than if they were independent). Positive correlation means the true FWER is lower than 1 − (1 − α)ⁿ predicts.

**Bonferroni does not require the independence assumption.** It relies on the union bound, which holds for any correlation structure. This is why Bonferroni is always conservative (stricter than strictly necessary) when tests are positively correlated: it controls FWER for the worst-case (independent) structure even though your actual structure produces smaller FWER.

**The Šidák correction is the exact version under independence.** α_Šidák = 1 − (1 − FWER)^(1/n). Bonferroni α = FWER/n is its first-order Taylor approximation. The difference is a few percent at typical n and α. Choose Bonferroni for simplicity and robustness; choose Šidák for exactness under verified independence.

**The correction is a budget allocation, not a punishment.** Total error budget α is split among n tests. This metaphor keeps the arithmetic meaningful rather than mechanical.

**Family size is the count of all tests run in service of a single research question, not the count of tests you report.** Every decision branch (lookback window choice, universe subset choice, time period choice, functional form choice) is an implicit test. Honest family counting is a habit, not a reflex.

**A correction cannot create findings from null data.** If no test clears the uncorrected threshold, Bonferroni has nothing to strip. Applying the correction mechanically to null data is a misunderstanding of what the correction does.

**The correction is about evidential honesty, not statistical bookkeeping.** A p = 0.04 from a single targeted test and a p = 0.04 from a family of 30 tests look identical but carry radically different evidential weight. The correction encodes this difference in the threshold itself, so the reader does not need to know the family size to interpret the result correctly.

---

## Technical skills acquired

Full fluency (no reference needed):

- Compute FWER = 1 − (1 − α)ⁿ from first principles using the complement trick.
- Apply Bonferroni correction: divide target FWER by n to get per-test threshold.
- Recognize when a research question has produced a family of tests rather than a single test.
- Compute the Bonferroni-adjusted ACF confidence band: ±z_(α/n/2)/√N where the critical value shifts from 1.96 at uncorrected 0.05 to 3.02 at Bonferroni-corrected 0.0025 for n = 20.

Working fluency:

- Distinguish Bonferroni from Šidák and explain why Bonferroni is preferred when correlations are unknown.
- Distinguish FWER from false discovery rate (FDR, the target of Benjamini-Hochberg); name only, conceptual mechanism deferred until it binds in later work.

Vocabulary now readable in papers:

- Family-wise error rate (FWER), false discovery rate (FDR), Bonferroni, Šidák, Holm-Bonferroni, Benjamini-Hochberg.
- Union bound, Boole's inequality.
- Multiple testing problem, p-hacking, publication bias, replication crisis, file-drawer problem.
- Harvey-Liu-Zhu threshold (t > 3 proposed factor-discovery bar).

---

## Codebase

No new code written this session. The content was conceptual and arithmetic. The function-promotion task flagged at the end of Sessions 1 and 2 (lifting hypothesis-testing helpers into `hypothesis_testing.py`) remains pending for a third consecutive session.

The ACF-band calculation from Part seven is worth capturing as a helper whenever I next write code:

```python
from scipy.stats import norm

def acf_band(n_obs, n_tests, family_alpha=0.05):
    """Return the (lower, upper) ACF confidence band half-width
    under Bonferroni correction for multiple lag testing.

    n_obs: number of observations in the time series.
    n_tests: number of lags being tested.
    family_alpha: target FWER across the family of lag tests.
    """
    per_test_alpha = family_alpha / n_tests
    z_critical = norm.ppf(1 - per_test_alpha / 2)
    half_width = z_critical / (n_obs ** 0.5)
    return -half_width, half_width
```

One-liner to add to `hypothesis_testing.py` when the function-promotion task is finally done.

---

## Misconceptions corrected

**"Per-test α is the thing that grows with more tests."** It does not. α stays fixed at whatever you set it. FWER is the compounded quantity. This distinction was my sharpened-takeaway moment at the end of the session, and the correction matters because "per-test α amplifies" would suggest you could fix the problem by doing each test more carefully, which is wrong; the fix is at the family level.

**"A false factor" is what the multiple-testing problem produces.** The factor itself is not what is false. The test result mislabeling a null factor as real is what is false. Keeping the language clean prevents the easy slide into "this factor is a false finding" when the factor is just a piece of data and only the inference about it can be wrong.

**"Chances of a false finding add up across tests."** They do not add in any simple way. They compound via 1 − (1 − α)ⁿ, which for small α is approximately nα but deviates from pure addition as α or n grow. Treating the accumulation as additive gives answers that are too high at large n and can exceed 1 in rough calculation, which is nonsense for a probability. The product-of-survival-probabilities formulation is the correct structure.

**"FWER for 20 tests at 0.05 is around 5%."** My prediction, off by 60 percentage points. The human intuition anchors to the per-test rate and does not correctly account for compounding. The fix is to always run the complement calculation explicitly: 0.95 to the power of n, then subtract from 1.

**"The required per-test threshold for FWER = 0.05 across 20 tests is 0.0001."** My prediction, off by a factor of 25. The correct magnitude (0.0025) falls directly out of α/n; the 0.0001 magnitude would be right for ~500 tests, not 20. The fix is to do α/n arithmetic on the spot rather than estimate by feel.

**"Bonferroni always changes your conclusions."** It does not. For null results at the uncorrected threshold, Bonferroni is redundant. It binds specifically when apparent wins need to defend themselves, which is the situation that will appear in Projects 5-6 and has not yet appeared in my work.

**"You do multiple testing correction because it is the rigorous thing to do."** Fine as far as it goes, but the deeper reason is evidential honesty. The correction exists because a p-value from a family of tests carries different evidential weight than a p-value from a single test, and the threshold shift is the arithmetic encoding of that difference. Framing the correction as bookkeeping rather than as honesty understates what it is doing.

---

## Habits reinforced

**Commit to a numeric prediction before derivation.** Applied three times this session (FWER at n = 20; required per-test α; whether my Project 3 Session 4 ACF results survived correction). Two predictions missed badly. The misses were the pedagogical content, not the failures. Run this habit on every new piece of arithmetic.

**Use the complement trick for "at least one" probabilities.** P(at least one) = 1 − P(zero) is always cleaner than enumerating cases. Will apply to any "at least one" question going forward.

**Count the family before applying any correction.** Bonferroni mechanically applied is useless if the family is miscounted. The count should include every decision branch, not just the tests explicitly written up. This is the discipline I will need in Projects 5-6.

**Check whether there are apparent wins before applying the correction.** A correction for multiple testing has nothing to do when all tests are null. Applying the correction to a null result is not wrong, just empty. The conclusion stays the same.

**Separate the arithmetic question from the framing question.** The Session's most important moment was not the FWER derivation but the shift from "chances of a false factor amplify" to "probability of at least one false positive grows, per-test rate stays fixed." The arithmetic was straightforward; the language needed sharpening. Any time a mechanism gets stated in plain language, the phrasing needs to be as precise as the formula.

**Field-level multiple testing is a thing.** The Harvey-Liu-Zhu argument is not just about individual researcher discipline; it is about the structural effect of publication filtering across hundreds of studies. When reading any published factor result, ask: what was the effective field-wide family size, and would this finding clear a t > 3 threshold?

---

## Thesis implications for 小盘股

Defensible from Session 3 data:

- The reversal-thread family across Project 4 Sessions 1 and 2 contains 2 formal tests. α_Bonferroni = 0.025. Neither test clears 0.05. No evidence for small-cap reversal in my work to date, under any correction threshold. The Bonferroni layer does not change the conclusion; it confirms it.
- The broader implicit family of "this is different from that" claims across Projects 1-4 is 30-50 tests. α_Bonferroni at n = 40 is 0.00125. No formal p-value has cleared this threshold. Statistical significance has not been the binding constraint on any conclusion I have drawn, which means the honest-null-reporting habit has been doing the real work.
- When I move to factor screening in Project 5, the family size for the factor-discovery question jumps immediately to 10+. α_Bonferroni ≈ 0.005. Factor p-values that look significant at 0.05 may collapse under correction.

Not supported by Session 3 data:

- That small-cap reversal does not exist. Absence of evidence in a 2-test family with low per-test power is not evidence of absence. The cross-sectional approach in Project 5 buys power quickly and may reveal effects that single-stock time-series testing cannot detect.
- That Bonferroni is the right correction for Projects 5-6. For correlated factor tests (momentum at 60 days and 90 days are very correlated), Bonferroni is strictly conservative; Benjamini-Hochberg or Holm gets closer to the right number. The choice will need to be made explicitly when the correction binds.
- That a p-value surviving Bonferroni means the factor is tradeable. Statistical significance and economic significance are separate layers; Project 4 Session 2 already established that costs destroy most small-cap signals even when they survive testing. Bonferroni is a statistical filter, not a trading filter.

Net usable result: Session 3 produced a diagnostic tool more than a finding. The diagnostic is what converts large-scale factor exploration in Projects 5-6 from a p-hacking exercise into a disciplined investigation. The tool's value appears later; what I have now is the vocabulary and the arithmetic for applying it cleanly.

---

## Open items carried forward

**Function promotion still pending.** Three sessions of deferral now. The helpers from Sessions 1 and 2 plus the ACF-band one-liner from this session should all go into `hypothesis_testing.py`. Growing list: `permutation_correlation`, `permutation_mean_diff`, `t_test_two_sample`, `cost_adjusted_sharpe`, `acf_band`. Promote at the start of whichever session next involves code.

**Broader implicit family size is an estimate, not a count.** The "30-50" figure across Projects 1-4 is rough. A formal audit would enumerate every directional claim in the four projects' handoffs and attach a candidate p-value (explicit or implicit). Defer this audit unless a conclusion from earlier projects becomes operationally important.

**Choice of correction method for Projects 5-6 is unsettled.** Bonferroni is the default, but for factor families with known correlation structure (momentum lookbacks, value definitions), Holm or Benjamini-Hochberg is less conservative and more appropriate. The choice should be made explicitly at the start of Project 5 Session 1 rather than drifting.

**Session 2's deferred basket-level reversal test on 中证1000 over 2024-2026 is still outstanding.** Session 3 diverged from the Session 2 handoff's planned continuation to cover the multiple-testing material. The basket test is either Session 4's content or gets absorbed into Project 5. Decision needed before the next session begins.

**Šidák and Bonferroni overlap in practice but diverge conceptually.** Session 3 covered both and picked Bonferroni as the default. Worth keeping Šidák in the back pocket for cases where independence between tests is verifiable, since it is marginally less conservative and the computation is not much harder.

**Multiple testing and economic significance are separate filters.** Project 4 Session 2 developed the cost-adjusted Sharpe layer; Session 3 developed the Bonferroni layer. A factor that wants to be traded needs to clear both: statistically distinguishable from zero after multiplicity correction, and economically meaningful after transaction costs. Projects 5-6 will need to combine these filters explicitly.

---

## Bridge to next session

The learning plan's Project 4 Session 4 is the optional Bootstrap methods session, which formalizes the permutation tools I have been using informally since Session 1 into a general distribution-free framework. The Session 2 handoff's planned continuation was the basket-level reversal test on 中证1000 over 2024-2026, which never happened because Session 3 took a different direction.

Two reasonable next moves:

**Option A: Session 4 as originally planned (Bootstrap methods).** Builds on the permutation-test machinery from Session 1 into a general-purpose non-parametric tool. Completes the Project 4 toolkit cleanly. After Session 4, move to Project 5. The deferred basket-level reversal test either gets absorbed into Project 5's cross-sectional work or is skipped as pedagogically redundant once the cross-sectional framework is in place.

**Option B: Session 4 as the deferred basket-level reversal test.** Runs the Session 2 plan on 中证1000 2024-2026 data. Closes the reversal thread with a definitive basket-level result (likely null, given Session 2's single-stock null and the broader pattern of no evidence for reversal in my work). Bootstrap methods then either get a separate session or are introduced in Project 5 when they become operationally necessary.

My preference without strong justification: Option A, because Bootstrap is the structurally more important tool (it will appear repeatedly in Projects 5-8) and the basket-level reversal test is likely to add little beyond confirming the null. But the data pull mentioned in the Session 2 handoff may already be complete, in which case Option B becomes cheap to execute and closes a loose thread.

Whichever option is chosen, Project 5 is the next major phase, and Session 3's diagnostic tools become live constraints there.

---

Session 3 closed. Suggested conversation name: `2026-04-22 — Project 4 Session 3: Multiple Testing and the Bonferroni Correction`.
