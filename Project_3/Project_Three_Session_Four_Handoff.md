# Project 3 Session 4 Handoff: Does Yesterday Predict Today? The ACF, Ljung-Box, and the Gongshang Flow Discovery

**Completed:** 2026-04-21
**Session location:** Phase 2, Project 3 (Correlation and Regression), Session 4
**Status:** Closed. Ready for Session 5 (spurious correlation and the multi-testing problem, optional) or direct to Project 4 (formal hypothesis testing framework) if skipping the optional session.

---

## Key takeaways

- **"Does yesterday tell me anything about today?" is the whole idea behind autocorrelation.** Take a return series, line up each day with the day before, check whether there's a relationship. The math is ordinary Pearson correlation; the "auto" just means we're comparing a series with its own past rather than with something else.
- **"Lag" is jargon for "number of days in the past."** Lag-1 is yesterday. Lag-5 is five days ago. The ACF (autocorrelation function) plot runs the same question repeatedly, once at each lag, and shows the results as bars.
- **The ACF has a shaded "noise zone" at roughly ±1.96/√N.** For N = 241 the band is ±0.126. Any bar inside the band is consistent with "nothing is going on at this lag." Any bar outside it has crossed a threshold that pure chance would cross roughly 1 in 20 times.
- **Testing 20 lags one at a time produces about 1 false crossing by pure chance even on a completely random series.** Reading "one bar poked out" as evidence of structure is exactly the kind of error the multiple-testing problem creates.
- **Ljung-Box rolls all tested lags into a single joint check.** It squares each lag's autocorrelation and sums them weighted by sample size. One p-value across the whole horizon. This detects patterns where many small same-direction effects add up, which per-lag eyeballing systematically misses.
- **震元 showed no detectable pattern.** Lag-1 was −0.005. Ljung-Box p-values at horizons 5, 10, 20 were 0.38, 0.18, 0.24. Nothing to see.
- **工商 showed a real pattern that eyeballing would have dismissed.** Lag-1 was −0.060. Ljung-Box rejected hard at every horizon: 0.010, 0.0039, 0.0014. The chart had positive tilts at days 2, 4, 7 and negative tilts at days 10 through 15. No single bar looked striking; collectively they were decisive.
- **The 工商 shape is "push, then pullback" over about 3 weeks.** A few days of continuation, then two weeks of gradual reversal.
- **The most likely mechanism is coordinated flow from index funds, ETFs, and 国家队, not news diffusion.** Tour-bus analogy: 工商 is big enough and widely-held enough that scheduled big-money flows buy and sell it in waves. The waves push the price for a few days then pass. 震元 isn't on those routes, so no wave pattern.
- **The prediction (small positive for 震元, zero for 工商) was wrong in an informative way.** Predicted on the slow-information story. Reality showed the opposite pattern driven by a different mechanism (flow). The miss surfaced a mechanism that wasn't on the radar.
- **"Looks flat by eye" is not evidence of "nothing here."** Eyeballing weights single big bars heavily and ignores collections of small bars, which is the opposite of what the formal test does. Rule: run Ljung-Box before interpreting the ACF shape.
- **Session 3 (volume-return in 工商) and Session 4 (return-return AC in 工商) are two windows onto the same underlying flow dynamic, not independent evidence.** Do not double-count.

---

## Reference conversations and documents

- Previous session: `2026-04-21 — Project 3 Session 3: Hypothesis Testing with statsmodels, HC3 Robust Standard Errors, and the 震元-vs-工商 Sign Flip` → `Project_Three_Session_Three_Handoff.md`
- This session's conversation: `2026-04-21 — Project 3 Session 4: Day-to-Day Predictability, the Flat-Chart Trap, and the Gongshang Flow Pattern` → this document
- Next session: `Project_Three_Session_Five_Handoff.md` (if Route A), or `Project_Four_Session_One_Handoff.md` (if Route B)

---

## Starting point

Entered Session 4 with solid regression inference from Session 3 (classical OLS, Breusch-Pagan residual diagnostics, HC3 robust standard errors) and an honest verdict that the single-stock single-year volume-return signal in 震元 is not distinguishable from zero after robust correction. Also carrying a deferred cross-sectional hypothesis for Project 5: qualitative sign difference between small-cap and large-cap volume-return slopes. No practical experience yet with time-series autocorrelation. The session's job was to open a second channel for testing the slow-information-diffusion story (return-to-return predictability instead of volume-to-return) and to introduce the multi-lag joint-test framework that Ljung-Box embodies.

---

## Session 4 thesis

If small companies really do process information more slowly than large ones, that lag should show up in returns themselves. Yesterday's news effect would trickle into today's price, detectable as a small positive relationship between yesterday and today. This is the most direct test of the slow-information story. Session 4 introduces the vocabulary and machinery for running it (autocorrelation, lag, ACF, noise zone, Ljung-Box) and applies them to 震元 and 工商 in 2024.

The deeper lesson the session turned out to deliver: the expected pattern wasn't there, but a different pattern was. What looks like failure of one mechanism can be the signature of another. Eye-first interpretation missed it; the formal joint test caught it.

---

## Progression through the session

### Opening: the concept re-explained in plain language

The first explanation of autocorrelation was too formula-first. I opened with Pearson correlation syntax, moved to a mathematical definition, and asked for a prediction before the concept had grounded. The pushback was correct: committing to a prediction without understanding what lag-1 meant wasn't going to produce useful calibration.

The reframe worked. Autocorrelation is one question: does knowing yesterday help me guess today? Three everyday examples ground the three possible answers.

**London weather.** If today is cold, tomorrow is probably also cold. Cold days cluster, warm days cluster. Yesterday helps predict today. Positive autocorrelation.

**Coin flips.** If today's flip is heads, does that help predict tomorrow? No. Each flip is independent. Yesterday is useless. Zero autocorrelation.

**Dieting overcorrection.** If I overate yesterday, I'll probably eat less today to compensate. Big followed by small, small followed by big, the series keeps flipping direction. Negative autocorrelation.

"Lag" is just the number of steps back. Lag-1 is yesterday, lag-5 is five days ago. The ACF is the same question posed at many lags, plotted as bars side by side.

### Prediction, first attempt

First-pass prediction: "震元 will probably have zero lag-1 because we saw how volatile it was. 工商 might have small negative lag-1 due to corrections." Two confusions were layered in this.

The first was using volatility (how bumpy a series is) as evidence for autocorrelation (whether there's a time pattern). Those are independent properties. A series can be very bumpy and highly patterned, or very bumpy and random, or calm and patterned. This is the same scale-versus-shape distinction from Project 1 Session 2 (where std and kurtosis were mathematically independent), now one level up into the time domain.

The second was confusing the volume-return slope from Session 3 (−0.0034 for 工商, which involves volume) with return-return autocorrelation (which doesn't). Different quantities. A stock can have negative volume-return slope and zero return-return AC simultaneously without contradiction.

### Prediction, second attempt

Reanchored on the mechanism: "Small-caps might have small positive lag-1 from slow information diffusion. Large-caps probably no pattern because they're well-traded and information spreads fast." This is the mechanism-implied prediction. Wrong in the end, but for an interesting reason.

### Piece 1: sanity checks on the loaded data

Both stocks returned N = 241 observations. 2024 had 242 trading days and the diff calculation consumed one. 震元 std 0.0274, 工商 std 0.0128, ratio 2.1x. Consistent with the size-bucket volatility gap from Project 1.

### Piece 2: lag-1 autocorrelation manually and via pandas

Computed two ways, results agreed exactly.

震元 lag-1 = −0.0050
工商 lag-1 = −0.0596
Noise zone at N = 241: ±0.126

Both point estimates sit inside the noise zone. Formally, neither rejects "true AC is zero" at the 5% level on lag-1 alone. But the point estimates aren't symmetric. 震元 is essentially at zero in both sign and magnitude. 工商 is small-negative, about one standard error from zero, not enough to be significant alone but not clean zero either.

### Piece 3: the ACF plots and my interpretation error

Both plots look flat at first glance. 震元 has one bar (lag-7) reaching about −0.18, the only bar extending outside the band. 工商 has more bars flirting with the band: positive at lags 2, 4, 7; negative at 10, 12, 14, 17; with the clearest crossings at lag-4 (+) and lag-10 (−).

My interpretation of these plots was wrong. I told you: "expect about 1 false crossing per stock by chance when testing 20 lags, you got 1 or 2 per stock, both consistent with random noise, nothing to see." That read was eye-first and missed the collective structure in the 工商 plot. Ljung-Box came next and overturned it.

### Piece 4: Ljung-Box and the actual finding

震元 Ljung-Box: p = 0.38 (lag 5), 0.18 (lag 10), 0.24 (lag 20). All large. No rejection at any horizon. 震元 is consistent with pure noise.

工商 Ljung-Box: p = 0.010 (lag 5), 0.0039 (lag 10), 0.0014 (lag 20). All small, and tightening as the horizon lengthens. Strong rejection of the "all zeros" null at every horizon.

This was the moment the session's conclusion inverted. The small-cap was flat. The large-cap was patterned. The opposite of the mechanism-implied prediction.

### Mechanism unpacking: why 工商, why not 震元

Ljung-Box detects weak but consistent autocorrelation spread across many lags even when no single lag looks striking. It squares each lag's AC and sums across lags, so twenty lags each at ±0.08 contribute more total signal than one lag at ±0.15 alone. Looking at the 工商 chart with that arithmetic in mind, the pattern becomes visible: positive tilt at short lags (2, 4, 7), negative tilt at medium lags (10-15). This shape is push-then-pullback. Short-horizon momentum followed by medium-horizon reversal.

Three candidate mechanisms, evaluated.

**Bid-ask bounce** (closing price alternating between bid and ask on alternate days) is quantitatively ruled out. The approximate contribution is (spread/2)² / variance. For 工商 at typical 1-tick spread and 2024 volatility, that's about −0.004, two orders of magnitude smaller than the observed effect.

**Index and ETF flow cycles** are the most plausible explanation. 工商 is a heavy 沪深300, MSCI China, and CSI 300 ETF constituent. It receives coordinated buying pressure on scheduled timelines. The waves push the price, the waves pass, the price normalizes. This mechanism produces push-pullback patterns specifically in widely-held index stocks. 国家队 buying adds to this: when the national team is active in the index, its purchases hit the same stocks in sequences lasting several days.

**Stat-arb and pairs-trading positioning** is also plausible. Large liquid stocks like 工商 are the primary instruments for systematic short-horizon strategies that build and unwind positions over days to weeks. These leave AC footprints. Not separately distinguishable from flow dynamics in our data.

震元 is too small and too illiquid to receive either mechanism's flow. No ETF holds it at meaningful size. No stat-arb fund trades it at scale because the slippage eats the edge. So the structure visible in 工商 is absent in 震元, consistent with both flow and positioning stories.

The original slow-news mechanism for 震元 is not disproved; it's just too small to detect in 241 observations on one stock. Empirical literature puts small-cap lag-1 AC in the 0.02 to 0.05 range, and the noise band at N = 241 is ±0.126. A true effect of 0.03 produces point estimates ranging from −0.03 to +0.09 purely from sampling variation. A single realization of −0.005 is entirely consistent with a true effect of +0.03 that's below the noise floor.

### Cross-session consistency check

Session 3 found that in 工商, high-volume days were followed by slight price reversals. Session 4 found that 工商 has a push-pullback shape across 20 days. These two findings are not independent. They're two views of the same underlying flow-and-reversal dynamic in index stocks. Flag for the record: do not double-count as separate evidence for the same mechanism when later analysis pools findings across sessions.

---

## Consolidated conceptual ground

The spine of Session 4 in plain language, defensible with specific data from today's notebook.

**Autocorrelation is ordinary Pearson correlation applied between a series and its own lagged self.** Every interpretive instinct for correlation carries over. +1 is perfect same-direction relationship, 0 is no relationship, −1 is perfect opposite-direction relationship. The "auto" prefix is linguistic dressing; the underlying math is the correlation you already know from Session 1.

**Lag is the number of time steps between "then" and "now."** Lag-1 compares today with yesterday. Lag-5 compares today with five days ago. The ACF is the same question posed at many lags, plotted as bars.

**The noise zone on the ACF (the shaded band) is the sampling distribution of the autocorrelation estimator under the null "true AC is zero."** For large samples it sits at roughly ±1.96/√N. Bars inside the band are consistent with "nothing happening at this lag." Bars outside cross a threshold that pure chance would cross roughly 1 time in 20.

**Testing 20 lags one at a time at the 5% level produces an expected 1 false crossing under a completely random series.** This is the multiple-testing problem in miniature. A single bar poking outside the band, in isolation, is not evidence. Roughly one crossing in a 20-lag plot is the null prediction, not a signal.

**Ljung-Box rolls all tested lags into a single joint test.** The statistic squares each lag's AC and sums across lags weighted by sample size. One p-value across the whole horizon. This detects patterns where many small effects point the same way, which per-lag eyeballing systematically misses.

**Return autocorrelation is tiny even when it's real.** Published effects sit in the 0.02 to 0.05 range. Noise bands at realistic sample sizes are ±0.10 to ±0.13. So true effects are usually below the per-lag detection threshold. This is why joint tests (Ljung-Box) and cross-sectional pooling (Project 5) matter. They accumulate weak evidence across lags or across stocks to lift real signals above the noise floor.

**Flow mechanics can create return autocorrelation in large liquid stocks even when news processing is efficient.** Index inclusion, ETF rebalancing, and national-team buying create push-pullback cycles mechanically unrelated to news. A large-cap can be "efficient at processing news" and "predictable from flow" simultaneously. These are separate channels.

**Small-caps' absence of detectable AC at single-stock single-year resolution doesn't disprove the slow-news mechanism.** It means either: the effect is too small relative to sample size, competing noise drowns it out at the single-stock level, or the mechanism operates at a horizon or in a regime this sample didn't capture. Cross-sectional pooling in Project 5 is where the statistical power to detect small effects will come from.

**Eye-first interpretation of ACF charts is unreliable.** Patterns spread across many small same-direction bars look flat to the eye but show up in joint tests. Rule: run Ljung-Box before interpreting the ACF shape, not after.

---

## Technical skills acquired

Production-ready (can do without referencing documentation):

- Compute lag-k autocorrelation manually by aligning two shifted vectors and applying `np.corrcoef`
- Verify manual computation against `pandas.Series.autocorr(lag=k)` as a sanity check
- Compute the 95% noise band for any sample size via ±1.96/√N
- Plot ACF using `statsmodels.graphics.tsaplots.plot_acf(series, lags=20, ax=ax)` with multi-panel layouts
- Run joint test using `statsmodels.stats.diagnostic.acorr_ljungbox(series, lags=[5, 10, 20], return_df=True)` and read the multi-horizon output

Working fluency (with light reference):

- Reason about bid-ask bounce contribution to lag-1 AC via approximate formula and typical spread assumptions
- Distinguish news-driven from flow-driven AC patterns by shape (fast decay from a single large lag-1 spike vs push-pullback across short and medium lags)
- Translate a joint-test p-value into an economic statement about whether structure exists

Vocabulary now readable in papers without lookup:

- Lag, ACF, autocorrelation coefficient, Ljung-Box, Q-statistic, 95% bands, Bartlett's formula
- Push-pullback dynamics, flow-driven AC, bid-ask bounce, short-horizon momentum, medium-horizon reversal

---

## Codebase now in the project

```
Session_Four.ipynb           # Autocorrelation and Ljung-Box on 震元 and 工商 2024 returns
session4_acf_comparison.png  # Two-panel ACF plot saved for reference
```

No new reusable helpers were added. The session used existing `load_or_fetch` (Project 1 `utils.py`) and `setup_chinese_font` (`plot_setup.py`) without extending them. Sessions to date have built up enough one-off helpers that a promotion pass to `project1_utils.py` or a new `project3_utils.py` is overdue. Worth doing at Session 5 or Project 4 opening rather than letting the debt grow further.

---

## Misconceptions corrected

**"Bumpy stocks have zero autocorrelation; calm stocks have predictable autocorrelation."** Confused scale with time-shape. Volatility and autocorrelation are mathematically independent. Any combination is possible: high volatility with high AC, high volatility with zero AC, low volatility with high AC, low volatility with zero AC. The version of this confusion from Project 1 (confusing std with kurtosis) has now recurred one level up.

**"The volume-return slope and the return-return autocorrelation are versions of the same thing."** They're not. Volume-return predictability is a conditional relationship that requires a second variable. Return autocorrelation is an unconditional relationship within the return series alone. A stock can have one without the other, or opposite signs on the two, without contradiction.

**"If both ACF charts look flat by eye, there's nothing there."** This one I (Claude) committed in the session, not the user. Ljung-Box detects patterns eye-level reading misses. The eye weights single large bars heavily and ignores collections of small bars; the formal test does the opposite.

**"Zero autocorrelation in a small-cap disproves slow information diffusion."** It disproves a specific effect size in a specific sample. It doesn't disprove the mechanism. Noise bands at N = 241 are wide enough to hide published effect sizes easily. Absence of evidence is not evidence of absence at this sample size.

**"The sign-flip story from volume-return (Session 3) should transfer to return-return AC (Session 4)."** It didn't, because the mechanisms are different. Volume-return tested slow-information-vs-flow-mean-reversion through one channel. Return-return AC tested the same-or-different through another. Large-caps showed structure in both cases but through different mechanisms: Session 3's volume-return slope was about flow-driven mean reversion, Session 4's ACF is about flow-driven push-pullback. The sign-flip is not a general claim; it's specific to the volume-return channel.

---

## Habits built in Session 4

**Formal-test-before-chart-interpretation.** The Ljung-Box run must precede any "this ACF looks flat" interpretation, not follow it. Eye-reads of ACF plots systematically miss distributed patterns. Rule for future work: run the joint test first, then interpret the chart with its verdict in mind.

**Cross-session dynamic check.** When two sessions produce findings on the same stock, ask whether the findings are independent evidence or two views of the same dynamic. Session 3's volume-return and Session 4's return-return findings on 工商 are the same underlying flow dynamic viewed twice. Future cross-session comparisons should open with "are these two findings independent, or are they probing the same mechanism through different channels?"

**Prediction reasoning audit before prediction commitment.** When a prediction feels quick to commit to, examine what the reasoning is actually resting on. The first-pass Session 4 prediction rested on two confusions (scale-vs-shape and volume-vs-return-AC). Catching them before running code would have saved a step. Rule: when asked for a prediction, spend one sentence on "my reasoning is X based on Y," and check that Y is relevant to what's being predicted.

**Language as diagnostic.** If I can't explain a concept in plain English without reaching for the jargon, I probably don't understand it well enough to predict anything useful from it. Jargon is the cover under which vague reasoning hides. Plain-language reformulation is a test of whether the mental model is concrete.

---

## Implications for the 小盘股 thesis

Defensible from Session 4 data:

- 震元's 2024 returns show no detectable day-to-day predictability at any horizon from lag-1 to lag-20. This is consistent with "true effect too small to detect at this sample size," "no effect at this stock this year," or "competing noise drowns the signal." We cannot discriminate among these from one stock alone.
- 工商's 2024 returns show a statistically strong push-pullback pattern: positive short-lag AC (2-7 days), negative medium-lag AC (10-15 days), Ljung-Box rejection at the 1% level across multiple horizons.
- The most likely mechanism for the 工商 pattern is coordinated flow from index funds, ETFs, and 国家队, producing multi-day buying waves followed by partial reversals. Bid-ask bounce is quantitatively ruled out. Stat-arb and pairs-trade positioning is also plausible but not separately testable from this data.
- Large-caps can be "efficient at processing news" and "predictable from flow" at the same time. Those are separate channels with different signatures.

Not supported by Session 4 data:

- "Small-caps have no slow-information-diffusion effect." The test is underpowered at N = 241 on one stock. Absence of detection is not absence of effect.
- "Large-caps have more tradeable patterns than small-caps." The 工商 pattern may not survive transaction costs on a real strategy. Magnitude at each lag is small (inside the noise zone per-lag, only detectable jointly). Translating to dollars requires the cost model in Project 4 Session 7.
- "The flow mechanism is the only explanation for the 工商 pattern." Stat-arb positioning and other sources remain live. Discriminating among them requires either intraday flow data (not available at our data level) or cross-sectional comparison across indices with different flow profiles (available in Project 5).

Specific Project 5 hypotheses worth carrying forward:

1. Flow-driven push-pullback AC should be stronger in heavily-indexed large-caps than in similarly-sized non-index large-caps. If mid-cap stocks with comparable market cap but different index-inclusion status can be identified, this becomes testable.
2. The 3-week push-pullback horizon suggests a "flow exhaustion" factor: after N consecutive same-direction days in an index-constituent large-cap, fade the move. Requires backtest to validate. Flagged as a possible factor, not yet a factor.
3. Small-cap autocorrelation should become detectable when pooled cross-sectionally across 30+ stocks. Published small-cap lag-1 AC is 0.02 to 0.05. At N = 241 per stock across 30 stocks, effective sample size for a pooled test is much larger and the noise band correspondingly tighter. This is the proper test of the slow-information story.

---

## Open items carried forward

**Data-loading bug audit on Session 1's notebook.** Flagged at Session 2, pending through Sessions 3 and 4. 5-minute `set_index('date')` verification. Clear at Session 5 open.

**Sortino formula audit on `risk_toolkit.py`.** Flagged at Session 2, pending through Sessions 3 and 4. 2-minute check that the denominator is `sqrt(mean(min(r - MAR, 0)**2))` and not `std(returns[returns < 0])`. Clear at Session 5 open.

**Helper promotion to `project3_utils.py`.** Several session-specific helpers (`fit_with_diagnostics` from Session 3, the manual-AC verification pattern from Session 4) should be lifted into a shared module before Project 5 or Project 4. Deferred.

**Multi-year replication of the 工商 flow pattern.** The push-pullback finding is 2024-only. 2022-2023 data is already cached. A multi-year rerun would test regime stability. If the pattern persists across years, it's more likely to be the persistent flow-driven mechanism. If it's 2024-specific, regime-specific explanations (particular ETF inflows, particular 国家队 campaigns) become more plausible.

**Cross-index comparison.** 工商's pattern is consistent with flow from index inclusion. A mid-cap outside the main indices with similar market cap would be a natural control. Deferred to Project 5 or a side-experiment before.

**Translation of the Ljung-Box finding into economic magnitude.** "Statistically strong pattern" for 工商 hasn't been translated into dollar-per-trade yet. Follow-up exercise: for each flagged lag (2, 4, 7 positive; 10-15 negative), what does the AC magnitude translate to in expected return conditional on yesterday's sign? Takes concrete form in Project 4's backtester.

**Session 5 scope decision.** The original Session 5 was "spurious correlation and multi-testing awareness." The Ljung-Box encounter today partially covered this territory. Decision point at next session open: compressed Session 5 focused on what Ljung-Box didn't cover (simulated false positives via random data, Bonferroni correction preview), or skip to Project 4.

---

## Bridge to next session

Two routes forward.

**Route A: Session 5 (spurious correlation and the multi-testing problem).** The ACF noise-band interpretation today touched the surface: 20 lags tested at the 5% level produces about 1 false crossing by chance under a random null. Ljung-Box solved the specific problem for the specific case of time-series lags. But the broader issue, which applies to any factor research involving testing many predictors against returns, deserves explicit treatment. Session 5 as originally planned: generate 100 random return series, regress against real returns, count how many come up "significant" by chance, experience the multi-testing problem viscerally. The payoff is not new machinery (Ljung-Box already handled the lag case) but reusable awareness that will matter immediately in Project 5 when testing 5+ factors cross-sectionally.

**Route B: Jump to Project 4 (hypothesis testing formalized).** Project 4 extends the t-test and bootstrap machinery to general contexts, introduces Bonferroni correction formally, and prepares the toolkit for Project 5's cross-sectional factor testing. The lesson Session 5 would have embedded informally (multi-testing awareness) is formalized properly in Project 4. If routing through Project 4 first, today's Ljung-Box encounter serves as a concrete example of joint testing that makes the Bonferroni framework land faster.

Recommendation: Route A for the visceral simulation experience, which tends to stick better than the formal derivation. Route B if session budget is tight. Both routes converge by Project 5 Session 1.

---

Session 4 closed. Suggested conversation name (already used for this chat): `2026-04-21 — Project 3 Session 4: Day-to-Day Predictability, the Flat-Chart Trap, and the Gongshang Flow Pattern`.
