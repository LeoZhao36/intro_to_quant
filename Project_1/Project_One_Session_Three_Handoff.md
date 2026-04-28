# Project 1, Session 3 Handoff: Visualizing Distributions Against a Reference

**Completed:** 2026-04-17
**Project location:** Phase 1, Project 1 (Return Distributions), Session 3 of 5
**Topic:** Histograms with normal overlays, QQ-plots, side-by-side visual diagnostics. The bell curve as a testable reference rather than a default assumption. First encounter with 涨跌停板 measurement distortion in small-cap data.

---

## What I finished

Started Session_Three.ipynb as a fresh notebook. Built a setup cell that reloads 平安银行 2024 data from scratch (imports, data pull, returns, font setup) so the notebook runs top-to-bottom in a clean kernel. Established the habit: every notebook from now on should be self-contained and reproducible.

Simulated a genuine normal distribution using np.random.normal with parameters matched exactly to 平安银行's 2024 returns (μ = 0.0015, σ = 0.0165, N = 241). Plotted real and simulated data side by side on identical axes. This was the first time I had a concrete reference for "what a bell curve shaped like my data would actually look like," rather than a vague mental picture. Predicted the difference would be obvious and easy to spot.

Discovered the difference is not where I expected it. I thought fat tails would announce themselves at the extremes. In the visual, what jumped out first was the center: the real data had a peak of ~50 observations in the tallest bin, the simulated normal had ~19. The shoulders (the region between roughly ±1σ and ±2σ) were thick on the normal and thin on the real data. The tails had only a few observations, which were visually easy to miss as single bars.

Internalized the full scale-vs-shape statement. Fat tails do not just mean "more extremes." They mean that mass has been redistributed: taken out of the shoulders and moved to both the center (more concentration on quiet days) and the extremes (a few shock days). Normal distributions spread mass smoothly across the shoulders. Fat-tailed distributions peak and spike. Same variance, different architecture.

Noticed that the simulated normal had skew = 0.305 and kurt = 0.665, not exactly zero. This is sampling noise at N = 241. A single draw will not produce a perfect bell curve, and any kurtosis measurement on a small sample has a noise band around it. A measured kurt of 0.5 on a real stock cannot prove non-normality, because random normal draws routinely produce that. A kurt of 10.7 can, because no random normal sample of that size would plausibly produce it. This gap between "noisy enough to be random" and "too extreme to be random" is what formal hypothesis tests will quantify later in Project 4. Noted and deferred.

Built a QQ-plot for 平安银行 2024 using scipy.stats.probplot. The plot compares each real observation against where the bell curve would have predicted it, point by point. Middle of the plot from about x = -1.5 to x = +1.5: dots sit on the reference line. Ordinary days behave as the bell curve predicts. Both corners curve sharply away. The February 21 +9.98% rally sits at roughly (2.8, 0.10) when the line would have predicted around +4-5% at that quantile. The biggest loss of the year sits at (-2.8, -0.095) well below the line. The bell curve underestimates the magnitude of rare days by orders of magnitude, not small amounts.

Reframed what this means operationally. Standard finance tools (Sharpe ratio, VaR, option pricing, standard position sizing) assume bell-curved returns. The QQ-plot shows, visually and specifically, where that assumption breaks: not in the middle, at the edges. The edges are where real money is made and lost. A claim like "-5% would be a three-sigma event, roughly once every 740 days" is bell-curve math. 平安银行 produced a -9.5% day in a single calendar year of 241 trading days. The bell-curve math is not just slightly wrong at the edges. It is wrong by factors of hundreds.

Ran the same QQ-plot on 华升股份 (the small-cap from Session 2) side by side with 平安银行. Prediction going in: 华升股份 should hug the reference line more closely given its lower kurtosis, even though its std is 2.5× higher. The middle of the 华升股份 plot did confirm this. But the extreme edges did not look like random noise pulling away from a line. They looked like a flat shelf. Dots piled up at exactly +0.10 and exactly -0.10, horizontal, not curving.

Identified the shelf as the ±10% 涨跌停板 rule. When a stock hits the daily price limit, the return freezes at exactly ±10.00%. The measurement does not reflect what the stock wanted to do, only what the rules allowed. 华升股份's measured kurtosis of 0.6 is therefore an underestimate. The true tails are chopped off before they can appear in the data.

Generalized the lesson for the 小盘股 thesis. Every standard risk metric computed on A-share data is subject to ceiling-floor distortion: measured std underestimates true std, measured kurtosis underestimates true kurtosis, measured max drawdown can be wrong because 连续跌停 means you cannot actually exit during the worst stretch. 小盘股 hit the limit far more often than 大盘股, so the distortion is systematically worse for exactly the stocks I am most interested in. Any future risk analysis of small-caps needs to carry a flag: "this number is biased by the price limit rule, and the true number is larger."

Closed the session with a histogram-with-normal-overlay plot. The same diagnostic as the QQ-plot in a different visual language: blue bars for the real density, a red bell curve drawn at matched μ and σ for the reference. The peak-over, shoulders-under, extremes-over pattern was visible cleanly and confirmed everything the QQ-plot said.

## Files now in the project

- `Session_Three.ipynb`: the full working notebook with self-contained setup cell, real vs simulated normal comparison, QQ-plot for 平安银行, side-by-side QQ-plots for 平安银行 vs 华升股份, histogram with normal overlay.
- All Session 2 files remain unchanged: `utils.py`, `plot_setup.py`, `data/sz000001_with_returns.csv`.

## Key conceptual ground gained

**The bell curve as a testable hypothesis, not an assumption.** Before this session, "平安银行 has fat tails" was a claim backed by a number (kurt = 10.67) and a vague mental picture. Now there is a concrete reference: a genuine sample drawn from a normal distribution with matched parameters, sitting next to the real data. The gap between the two is where the bell curve story fails. This is the general move underneath all of statistical inference: take a story about how data should behave, make it concrete, and measure the gap. Every test I will learn later is a more formal version of this same move.

**Scale and shape are independent, and the formal proof is visible.** Two distributions with identical mean and std can look radically different. The simulated normal and the real 平安银行 data share μ = 0.0015 and σ ≈ 0.016. They look nothing alike. Scale tells you the total budget of variability; shape tells you how that budget is distributed across quiet days, moderate days, and extreme days. A stock can be "calm" (low std) and still deliver regular shocks (high kurt). A stock can be "wild" (high std) and still have no true outliers (low kurt). These are different kinds of risk and require different management.

**The QQ-plot as a point-by-point accuracy check.** A single summary number like kurtosis compresses the entire distribution into one digit. The QQ-plot does the opposite: it plots every observation individually against its predicted value under the null story. This means I can now point at specific dots and say "this day broke the bell curve story" or "this day fit it." The diagnostic is surgical, not summary. When an observation sits on the line, the bell curve predicted it correctly in quantile terms. When it curves away, the gap is the bell curve's error at that point.

**Why QQ-plots are superior to histograms for tail diagnosis.** Histograms bin the data, and by definition the tails contain few observations. A single extreme day shows up as a bar of height 1 at the edge of the histogram, visually easy to miss. The QQ-plot never aggregates. Every point gets its own coordinate pair. The tails are fully resolved, not smoothed or averaged.

**Sampling noise at small N and what it implies for testing.** N = 241 is small. A random normal sample at that size can produce skew in the ±0.5 range and kurtosis in the ±0.5 range just by chance. So a measured kurtosis of 0.5 on a real stock is not evidence of anything. A measured kurtosis of 10 is. The threshold between "consistent with normal" and "incompatible with normal" depends on sample size. This is the sample-size intuition underlying every hypothesis test I will eventually meet, and Project 4 will turn it into a formal procedure.

**涨跌停板 as a measurement distortion, not just a trading inconvenience.** This was the unplanned discovery of the session. I had known the ±10% rule existed (it was mentioned in the Phase 1 project description). I had not connected it to my statistical measurements. The 华升股份 QQ-plot showed a shelf, not a curve, at both extremes, which is the visual signature of a hard ceiling clipping the true distribution. Implication: any kurtosis, std, or drawdown measurement on a limit-hitting stock is a lower bound on the true value, not an estimate of it. The distortion is worst for exactly the 小盘股 class I care most about, because those are the stocks that hit the limit most often.

**Every risk metric is a statement about a specific distribution.** Sharpe ratios, Value-at-Risk, option pricing, standard position-sizing rules all assume returns are approximately bell-curved. The QQ-plot demonstrates that this assumption is broken specifically at the tails, which is where these tools are supposed to protect you. A Sharpe ratio that looks clean on a fat-tailed stock is still underestimating the true tail risk. This is not a rhetorical caution. It is a visible, measurable fact about the data.

## Open items for next session or later

Session 4 is the proper Project 1 deliverable: the 20-30 stock basket comparison of 中证1000 constituents vs 沪深300 constituents. Everything in Session 3 was demonstrated on single stocks (平安银行 alone, then 平安银行 vs 华升股份). The next session expands to population-level comparisons. The visual tools built in Session 3 (QQ-plots, histogram-with-overlay) will be used again on the aggregated basket returns.

涨跌停板 detection as a dedicated utility. I should write a helper function that flags limit-hit days in any return series, because every future analysis of small-caps will need to account for them. Probably: input a returns Series, output a boolean mask of days where |return| ≥ 0.0995 (close enough to the limit to count, with a small tolerance for measurement precision). Deferred but explicitly flagged.

Formal normality tests (Shapiro-Wilk, Jarque-Bera) deferred again to Project 3 where they appear in the full hypothesis-testing frame. Session 3 has given me the visual intuition that they formalize. No loss.

The sampling noise question ("how extreme does a measured kurtosis need to be before I can say it is not bell curve noise?") is the natural lead-in to hypothesis testing in Project 4. Session 3 has set up the question but not answered it.

## State of my understanding

Solid on: the bell curve as a reference rather than a default, the scale-vs-shape distinction seen visually, QQ-plot reading (middle fits, corners curve away from or pile up against the line), histogram-with-overlay, the general idea that fat tails redistribute mass from the shoulders to both the center and the extremes, the small-sample noise caveat on kurtosis and skewness.

Newly solid: the 涨跌停板 creates measurement distortion, not just trading friction. All standard risk metrics on limit-hitting stocks are biased, and the bias is systematically worse for small-caps than for large-caps.

Accepted but not formalized: why exactly the QQ-plot uses "theoretical quantiles" in units of standard deviations. I am reading the x-axis correctly (distance from mean in σ units), but I have not derived why this is the correct normalization or why it makes QQ-plots comparable across datasets. Acceptable for now.

Still ahead: 20-30 stock basket comparisons (Session 4), the optional formal normality tests (Session 5 or Project 3), a utility function for limit-hit detection, the full hypothesis testing frame (Project 4).

## Personal reflection

*[to be filled in by me]*

## Ready for Session 4

**Session 4 topic:** the proper Project 1 deliverable. Equal-weighted return series for 中证1000 vs 沪深300 baskets, 20-30 stocks each. Summary statistics table, side-by-side histograms, QQ-plots on the basket returns. A written conclusion in the notebook answering whether 小盘股 returns are meaningfully fatter-tailed than 大盘股 returns at the population level.

**Prerequisites met:** returns computation, descriptive statistics, z-scoring, sample design awareness, bell curve as reference, QQ-plot reading, histogram-with-overlay, price limit awareness. The visual and numerical toolkit is complete for the basket comparison. The main work ahead is scaling up cleanly and not letting sample design errors creep in.
