# Project 3 Closeout: Correlation, Regression, and the Multi-Testing Problem

**Completed:** 2026-04-21
**Project location:** Phase 2, Project 3 (Correlation and Regression), Sessions 1 through 5
**Status:** Closed. Ready for Project 4 (Hypothesis Testing formalized).

---

## Reference conversations and documents

Each session has a standalone handoff document. This closeout is the master summary and should be read alongside the individual handoffs when detail on any one session is needed.

- `Project_One_Closeout.md` — prior project closeout, still the reference for distributional concepts carried into Project 3
- `2026-04-21 — Project 3 Session 1: Pearson vs Spearman Correlation on Returns` → `Project_Three_Session_One_Handoff.md` *(conversation name to be confirmed from user's records)*
- `2026-04-21 — Project 3 Session 2: Scatter Plots, Trend Lines, and Residual Thinking` → `Project_Three_Session_Two_Handoff.md` *(conversation name to be confirmed)*
- `2026-04-21 — Project 3 Session 3: Hypothesis Testing with statsmodels, HC3 Robust Standard Errors, and the 震元-vs-工商 Sign Flip` → `Project_Three_Session_Three_Handoff.md`
- `2026-04-21 — Project 3 Session 4: Day-to-Day Predictability, the Flat-Chart Trap, and the Gongshang Flow Pattern` → `Project_Three_Session_Four_Handoff.md`
- `2026-04-21 — Project 3 Session 5: Multi-Testing, 100 Random Predictors, and the Test-vs-Target Distinction` → `Project_Three_Session_Five_Handoff.md`

---

## Starting point

Entered Project 3 with the Project 1 distributional vocabulary secured (fat tails, scale vs shape, single-event domination of higher moments, bulk-vs-tails classification of statistical questions) and Project 2's risk-metric toolkit working (rolling volatility, drawdown, Sharpe, Sortino, limit-hit detection). Could measure how stocks moved and how much risk they carried. Had no tools yet for measuring *relationships* between variables, or for judging whether a visible pattern was real or noise.

The gap Project 3 filled: from "describing one stock's behavior" to "testing claims about relationships" to "judging which claims are trustworthy." This is the conceptual spine of quant research.

---

## Project 3 thesis

Every trading strategy reduces to a claim about relationships. "This predicts that." "This moves with that." "Yesterday informs today." Before any of these claims can be trusted, they must pass tests. Project 3 builds the testing toolkit from the ground up: correlation and regression (the measurement tools), residual thinking (the honesty tool), robust standard errors (the don't-be-fooled-by-messy-data tool), autocorrelation with joint testing (the time-series extension), and multi-testing awareness with Bonferroni (the don't-be-fooled-by-many-tests tool).

The through-line: statistical significance is a property of the test procedure, not of reality. Every tool in the project is an answer to a different version of "okay, but how do I know this isn't fooling me?"

The small-cap focus continues from Projects 1 and 2 but shifts emphasis. Project 1 looked at individual stocks and baskets as distributions. Project 3 looks at relationships between variables: volume and returns, past returns and future returns, one stock and another. The 小盘股 microstructure features that matter for distributions (illiquidity, clipping, slow information diffusion) predict specific signatures in these relationships, and Project 3 develops the tools to detect them.

---

## Session-by-session progression

### Session 1: Pearson and Spearman Correlation on Returns

Introduced correlation as the measurement tool for "do these two things move together." Pearson correlation measures linear relationships: +1 is perfect same-direction, 0 is no relationship, −1 is perfect opposite-direction. Spearman (rank) correlation measures any monotonic relationship, not just linear, and is robust to outliers.

Key distinction built: Pearson fails when the relationship is nonlinear or when outliers dominate. Spearman handles both cases. For return data with fat tails, Spearman is often the more honest choice, though Pearson remains the default in most published research because it links cleanly to regression.

The session exercise paired 震元 and 工商 returns to measure how similarly they moved in 2024, and computed a correlation matrix across a 10-stock basket for a visual heatmap. The correlation between returns and volume changes was also computed at the single-stock level, establishing the foundation for the regression work in Session 3.

### Session 2: Scatter Plots, Trend Lines, and Residual Thinking

Extended correlation into visual and quantitative regression. Scatter plot with best-fit line via `np.polyfit`. R-squared as the fraction of variance explained by the predictor. Residuals (actual minus predicted) as the quantity that reveals whether the linear model misses structure.

Central lesson: a small correlation that is nonetheless "real" is still a small correlation. R-squared of 0.03 means the predictor explains 3% of the variance. The other 97% is noise or other factors. In markets, small real relationships can still be economically useful, but they're fragile: small changes in data or regime can flip them.

The residual plot as diagnostic was introduced here. Random-looking residuals suggest the linear model captures the main structure. Patterned residuals (curved shapes, widening variance) indicate the model is missing something. This diagnostic carries forward into every regression from Session 3 onward.

### Session 3: Hypothesis Testing with statsmodels, HC3 Robust Standard Errors, and the 震元-vs-工商 Sign Flip

Moved from scipy-level correlation to statsmodels-level regression with full inferential output. The OLS summary table: coefficient, standard error, t-statistic, p-value, R-squared, confidence intervals. Each piece read as an answer to a specific question.

The critical infrastructure added: **robust standard errors via HC3.** The classical OLS formula for standard errors assumes the noise around the regression line has uniform thickness (homoskedasticity). Financial data violates this routinely because volatility clusters. Under heteroskedasticity, classical standard errors are too small, t-statistics are inflated, p-values look falsely significant. HC3 corrects by computing standard errors that don't assume uniform thickness. For sample sizes around 241 trading days, HC3 is the default among the HC variants because of its finite-sample behavior.

Breusch-Pagan residual diagnostics were introduced alongside HC3 as the test for whether heteroskedasticity is actually present. The pattern: plot residuals, check visually for widening variance, run Breusch-Pagan for a formal verdict, use HC3 regardless because its cost (slightly conservative) is smaller than the risk of missed heteroskedasticity.

The session's substantive finding: regressing next-day return on today's volume for 震元 produced a positive slope under classical standard errors that looked significant, but HC3-corrected inference flipped the verdict to "not distinguishable from zero." The same regression on 工商 produced a negative slope that survived HC3 correction (though with shrunken significance). The sign flip between small-cap and large-cap volume-return slopes became the key hypothesis for Project 5 cross-sectional work: does the direction of the volume-return relationship systematically depend on market cap?

The `fit_with_diagnostics` helper was built in this session to automate the OLS + Breusch-Pagan + HC3 output for any regression.

### Session 4: Day-to-Day Predictability, the Flat-Chart Trap, and the 工商 Flow Pattern

Extended regression's inferential framework to time-series autocorrelation. Autocorrelation is ordinary Pearson correlation applied between a return series and its own lagged self. Lag-k autocorrelation compares today with k days ago. The ACF (autocorrelation function) plots lag-1 through lag-N autocorrelations as bars with a noise band at ±1.96/√N marking the 5% significance threshold per lag.

The central substantive discovery of Session 4: 工商's 2024 returns showed a statistically strong push-pullback pattern that eyeballing the ACF chart completely missed. No single lag's bar stuck far outside the noise band. Positive small bars at lags 2, 4, 7 and negative small bars at lags 10 through 15 each looked unremarkable alone. Ljung-Box, which squares each lag's autocorrelation and sums across lags weighted by sample size, rejected the "all zeros" null decisively at every horizon (p = 0.010 at lag 5, 0.0039 at lag 10, 0.0014 at lag 20).

震元's 2024 returns, by contrast, showed no pattern at any horizon (Ljung-Box p-values 0.18 to 0.38 across horizons). Consistent with three possibilities that couldn't be separated from one stock's data alone: true effect too small to detect at N = 241, no effect at this stock this year, or competing noise drowning the signal.

The mechanism discovery: the 工商 pattern is almost certainly flow-driven, not news-driven. 工商 is a heavy constituent of 沪深300, MSCI China, and other major indices, so it receives coordinated buying waves from ETF rebalancing, index fund flows, and 国家队 activity on predictable timelines. The waves push the price for a few days, then pass, then the price normalizes. 震元 is too small to be on those flow routes, so the pattern is absent.

This inverted the session's opening prediction (slow information diffusion should produce small positive lag-1 in small-caps, nothing in large-caps). Large-caps can be "efficient at processing news" and "predictable from flow" simultaneously. Those are separate channels with different signatures, and the Session 4 data revealed the flow channel where the news channel had been expected.

The methodological habit this session built: **run the joint test (Ljung-Box) before interpreting the ACF shape by eye.** Eyeballing systematically over-weights single large bars and under-weights collections of small same-direction bars, which is the opposite of what the formal test does.

### Session 5: Multi-Testing, 100 Random Predictors, and the Test-vs-Target Distinction

The capstone session. Generalized the multi-testing issue that Ljung-Box had handled in one specific case (many lags in one ACF) into the broader pattern that applies to any factor research involving many tests against returns.

The simulation: 100 random return series (generated via `np.random.normal` with scale matched to 震元's 2024 std) correlated one at a time against 震元's actual returns. Expected false positives at α = 0.05: 5. Observed: exactly 5. Bonferroni correction (p < 0.05/100 = 0.0005) left 0 survivors.

The top 5 "strongest" false discoveries had correlations from 0.146 to 0.168 and p-values from 0.009 to 0.024. Any one would look like a real finding in isolation. All manufactured from pure noise by construction. This is the mechanical demonstration of why published trading strategies overwhelmingly fail out-of-sample: selection bias plus multi-testing inflation plus (often) absent correction.

The reasoning slip that got caught: predicting "few significant results because 震元's own correlation was small." The false-positive rate depends on the test (threshold × number of tests), not on the target. Testing 100 random series against 震元, 工商, London weather, or Apple stock produces the same expected 5 false positives. This is structurally the same class of error as Session 4's volatility-vs-autocorrelation confusion, one level up. Filed as recurring pattern: *before predicting a quantity from a statistical test, identify whether it depends on the test procedure or on the data being tested.*

Bonferroni introduced as "to control FWER at α across m tests, require p < α/m per test." Simple, conservative, works regardless of correlation structure between tests. Non-independence was previewed as the reason Bonferroni over-corrects for real factor sets (which are correlated), leading to smarter methods like Benjamini-Hochberg and Holm that Project 4 will cover.

HC3 was revisited as the companion concept. Both HC3 and Bonferroni are corrections that make claims more honest when default statistical formulas assume cleaner data than actually exists. HC3 handles heteroskedastic noise in one test. Bonferroni handles inflated false-positive rates across many tests. Both enlarge p-values. Both belong in the default quant toolkit and are often needed together.

---

## Consolidated conceptual ground

**Correlation measures relationships, not causes.** +1 is perfect same-direction, 0 is no relationship, −1 is opposite. Pearson measures linear relationships and is sensitive to outliers. Spearman measures any monotonic relationship and is robust. For fat-tailed return data, Spearman is often the more honest choice.

**Regression decomposes a dependent variable into a linear function of predictors plus noise.** The slope is the measurement of interest. The standard error measures how much the slope wobbles across hypothetical realizations of the data. The p-value comes from the slope-to-standard-error ratio. If the standard error is wrong, the p-value is wrong.

**Classical regression formulas assume the noise has uniform thickness across the data range.** Financial data violates this routinely because volatility clusters. HC3 computes honest standard errors without the uniform-thickness assumption. For N around 241, HC3 is the default.

**Autocorrelation is ordinary Pearson correlation applied between a series and its own lagged self.** Every interpretive instinct for correlation carries over. The "auto" is linguistic dressing.

**The ACF noise band at ±1.96/√N marks the per-lag 5% threshold.** Testing 20 lags against this band produces an expected 1 crossing by chance under the null. One bar poking out in isolation is the null prediction, not evidence.

**Ljung-Box tests all lags jointly by squaring each lag's autocorrelation and summing across lags weighted by sample size.** One p-value across the whole horizon. Detects distributed patterns that eyeballing misses.

**Return autocorrelation is tiny even when real.** Published effects sit in 0.02 to 0.05 range. Noise bands at N = 241 are ±0.126. Single-stock single-year tests are underpowered for detecting published effect sizes. Cross-sectional pooling (Project 5) is where the statistical power comes from.

**Flow mechanics can create return autocorrelation in large liquid stocks even when news processing is efficient.** Index inclusion, ETF rebalancing, and national-team buying create mechanical push-pullback cycles. A large-cap can be efficient at news and predictable from flow simultaneously.

**Statistical significance is a property of the test procedure, not of reality.** A p-value below 0.05 says: "under the null, data this extreme occurs at most 5% of the time." It does not say "this finding is real." Running many tests guarantees false positives by arithmetic.

**The 5% threshold is a per-test promise.** Running m tests produces m separate 5% promises. FWER (probability of at least one false positive across the set) grows fast with m. For 100 independent tests at α = 0.05, FWER is approximately 99.4%.

**Bonferroni controls FWER by tightening each threshold to α/m.** Simple, conservative, valid regardless of correlation structure. When tests are correlated (as real factors are), Bonferroni over-corrects: it remains valid but costs statistical power. BH and Holm exploit dependence structure.

**False-positive counts are test properties, not target properties.** Changing what you test against doesn't change the expected false positives. Changing the threshold or the number of tests does.

**HC3 and Bonferroni are paired corrections against default dishonesty.** HC3 addresses non-uniform noise in one test. Bonferroni addresses inflated errors across many tests. Both enlarge p-values. Both are standard in professional quant shops. Bootstrap (Project 4) is a third member of the same family, handling the case where the distribution is fat-tailed and parametric formulas fail.

---

## Technical skills acquired

Production-ready (can do without referencing documentation):

- Compute Pearson and Spearman correlation via `.corr(method='pearson')` and `.corr(method='spearman')`
- Produce a correlation heatmap across a basket via seaborn
- Fit a simple OLS regression via statsmodels with full inferential output
- Apply HC3 robust standard errors via `model.fit(cov_type='HC3')`
- Run Breusch-Pagan residual diagnostics via `het_breuschpagan`
- Compute lag-k autocorrelation manually (two shifted vectors, `np.corrcoef`) and verify via `pd.Series.autocorr(lag=k)`
- Plot ACF via `statsmodels.graphics.tsaplots.plot_acf` with multi-panel layouts
- Run Ljung-Box joint test via `acorr_ljungbox` across multiple horizons
- Generate null-simulation data via `np.random.normal(0, target.std(), N)` for a false-positive-rate experiment
- Apply Bonferroni correction as α/m and count survivors

Working fluency (with light reference):

- Interpret an OLS summary table end to end: coefficient, SE, t-stat, p-value, R-squared, CIs, F-statistic
- Read ACF plots correctly: noise band, per-lag vs joint interpretation, distributed vs concentrated patterns
- Distinguish news-driven from flow-driven autocorrelation by ACF shape (single lag-1 spike vs multi-lag push-pullback)
- Reason about FWER mechanics for independent tests
- Recognize when Bonferroni over-corrects (correlated tests) and when BH/Holm would be preferable
- Classify a statistical question as test-property or target-property before predicting outcomes

Vocabulary now readable in papers without lookup:

- Pearson correlation, Spearman rank correlation, R-squared, residuals, homoskedasticity, heteroskedasticity
- OLS, coefficient, standard error, t-statistic, confidence interval, Breusch-Pagan test
- HC0 through HC4 robust standard errors, White standard errors, cluster-robust standard errors
- Lag, ACF, PACF, Ljung-Box Q-statistic, Bartlett's formula, 95% bands
- Push-pullback, flow-driven AC, bid-ask bounce, short-horizon momentum, medium-horizon reversal
- Multiple testing, multiplicity, look-everywhere effect, FWER, FDR
- Bonferroni correction, Benjamini-Hochberg, Holm-Bonferroni, p-hacking, data mining, selection bias

---

## Codebase now in the project

```
Session_One.ipynb            # Pearson and Spearman correlation on 震元 and 工商 2024 returns
Session_Two.ipynb            # Scatter plots, trend lines, residual diagnostics
Session_Three.ipynb          # OLS regression with HC3, the 震元-vs-工商 volume-return sign flip
Session_Four.ipynb           # ACF, Ljung-Box, 工商 push-pullback discovery
Session_Five.ipynb           # Multi-testing simulation, Bonferroni, HC3 refresher

session3_diagnostics.png     # Regression residual plots for 震元 and 工商
session4_acf_comparison.png  # Two-panel ACF plot
session5_pvalue_histogram.png # p-value distribution across 100 random predictors
```

Reusable helpers written but not yet promoted to a shared module:

- `fit_with_diagnostics(X, y)` from Session 3: OLS + Breusch-Pagan + HC3 in one call, returns summary object
- Manual lag-k autocorrelation verification pattern from Session 4: useful template for any new time-series statistic
- Null-simulation block from Session 5: generate m random predictors matched to target scale, run test, count survivors at multiple thresholds

All three should be lifted to `project3_utils.py` at Project 4 Session 1 open. Deferred rather than done at Session 5 to keep the closeout clean.

Inherited working modules from prior projects:

- `utils.py` (Project 0): `get_stock_data()`, baostock login handling
- `project1_utils.py` (if promoted per Project 1 closeout carry-forward): `load_or_fetch()`, `to_baostock_code()`, `pull_basket()`, `build_returns_matrix()`, `describe_basket()`
- `risk_toolkit.py` (Project 2): `compute_rolling_vol()`, `compute_drawdown()`, `compute_sharpe()`, `compute_sortino()`, `risk_report()`
- `plot_setup.py`: `setup_chinese_font()`

---

## Misconceptions that got corrected

**"Correlation measures causation."** It measures co-movement. Two variables can correlate because one causes the other, because a third drives both, or because they share timing without causal connection. Session 1 grounded this. The volume-return correlation in 工商 measured in Session 3 might be flow-driven, news-driven, or both, and correlation alone can't separate the channels.

**"Small correlations are worthless."** A real correlation of 0.1 means 1% of variance explained. That's small but not zero, and in markets, small stable relationships can produce tradable edges if transaction costs are low enough. Session 2 made this quantitative. The trap isn't "small correlations"; the trap is treating small correlations as large, or ignoring the instability that small correlations often carry.

**"Classical standard errors are always fine."** They assume uniform noise thickness. Financial data violates this routinely because volatility clusters. Classical standard errors under heteroskedasticity are systematically too small, making t-statistics inflated and p-values falsely significant. Session 3 made this concrete with the 震元 volume-return sign flip: the same regression produced significant vs not-significant depending on which standard errors were used.

**"ACF plots can be read by eye."** They can be read by eye for single-lag anomalies. They cannot be read by eye for distributed patterns where many small same-direction bars collectively indicate structure. Session 4's 工商 case was decisive: eyeballing the chart concluded "flat, nothing there," and Ljung-Box rejected the null at every horizon. The lesson: run the joint test first, then interpret the chart with its verdict in mind.

**"Target properties determine test properties."** Session 4 confused volatility (a scale property of data) with autocorrelation (a time-shape property). Session 5 confused a target's correlation magnitude with the test's false-positive rate. Both times the error was the same: reaching for data properties when the relevant quantities were test-procedure properties. The rule, now explicit: when predicting from a statistical test, first ask whether the quantity depends on the test or on the data.

**"Statistical significance means real."** Statistical significance means "unlikely under the null." Those are different statements. With enough tests, some unlikely events happen by arithmetic. Session 5's simulation made this mechanical: 100 random predictors produced exactly 5 "significant" results at α = 0.05, none of them real.

**"The Ljung-Box discovery and the volume-return discovery on 工商 are independent evidence."** Session 4 flagged this explicitly: the volume-return slope from Session 3 and the push-pullback ACF from Session 4 are two views of the same underlying flow dynamic in index-heavy large-caps, not independent findings. Future multi-signal aggregation across sessions needs to pass the independence check before pooling.

---

## Habits explicitly built

**Predict the mechanism, not the outcome.** Prediction before measurement is kept from Project 1, but Project 3 added a check: the prediction should invoke a mechanism that matches the quantity being predicted. If the question is about false-positive rates, the mechanism should invoke threshold × m, not the target's internal properties. Misfits of mechanism to question have been the recurring class of error in Sessions 4 and 5.

**Run the joint test before reading the per-unit chart.** ACF in Session 4 made this concrete. The eye over-weights single big bars and under-weights collections of small same-direction bars. The formal joint test does the opposite. Applies to any multi-lag, multi-factor, or multi-predictor diagnostic plot.

**Robust standard errors by default.** HC3 in Session 3 became the default for any financial regression. The alternative (classical SEs) is systematically dishonest for heteroskedastic data, which financial data almost always is. Cost of using HC3 when unneeded: small conservative bias. Cost of not using HC3 when needed: falsely significant findings.

**Tests-count budget.** Before running any multi-test factor analysis, commit to the factor list and carry m as the Bonferroni divisor. Adding factors later is allowed but the correction must scale. The alternative (testing widely, reporting the winners) is p-hacking in all but name.

**Null-simulation when a test is unfamiliar.** Generating random data matched to real scale, running the test on it, and observing what "no effect" looks like is durable intuition that any formal derivation struggles to match. Session 5 grounded this permanently.

**Test-property vs target-property filter.** Before predicting from a statistical test, classify the quantity. Threshold × m questions are test-property. Effect size, correlation magnitude, R-squared are target-property. Mixing the two is the recurring slip.

**Cross-session independence check.** When two sessions produce findings on the same stock, ask whether they're independent evidence or two views of the same dynamic. Session 4 flagged the Session 3 + Session 4 pattern for 工商. Future work needs to pass this check before pooling findings across sessions as if they were independent tests.

---

## Implications for 小盘股 thesis

Defensible from Project 3 data:

- **震元's 2024 volume-return relationship is not distinguishable from zero under robust inference.** Single-stock single-year test is underpowered to detect the published effect sizes for small-cap volume-return relationships (usually |slope| < 0.005 in standardized units). Cross-sectional pooling across 30+ small-caps in Project 5 is the proper test.
- **工商's 2024 data shows a statistically strong push-pullback pattern in both volume-return (Session 3, slope −0.0034) and return-return autocorrelation (Session 4, Ljung-Box p < 0.002).** Both findings likely reflect the same underlying flow dynamic. Large-caps carry a flow-driven predictability channel that is separate from news-driven predictability and opposite in sign to the slow-information-diffusion prediction for small-caps.
- **The sign of the volume-return relationship may systematically depend on market cap.** 工商 shows negative (high-volume days followed by price mean reversion). 震元 is not distinguishable from zero (possibly positive but underpowered). If a cross-sectional test in Project 5 confirms this, the qualitative sign difference is the cleanest piece of Project 3's finding that could translate into a factor.
- **Both major corrections (HC3 and Bonferroni) will be needed for Project 5 factor work.** Factor tests are one-regression-per-factor-per-stock. Heteroskedasticity applies to each regression. Multi-testing applies across the factor set. Using one without the other leaves obvious holes.
- **Null-simulation is a standard step when evaluating any new factor.** Running the factor test on random data matched to real-return scale establishes the false-positive floor before any real conclusions are drawn.

Not supported by Project 3 data and worth flagging to not carry forward:

- **"Large-caps have more tradeable patterns than small-caps."** Project 3 detected patterns in 工商 that weren't detectable in 震元, but this is about single-stock statistical power, not about absolute predictability. At cross-sectional resolution (Project 5), small-cap patterns may well be more tradeable even if individual stocks are too noisy to resolve.
- **"The slow-information-diffusion mechanism for small-caps is disproved."** Session 4 couldn't detect it. Couldn't detect means the test was underpowered at this sample size, not that the effect is absent. Published small-cap lag-1 autocorrelation is 0.02 to 0.05, and the noise band at N = 241 is ±0.126. A true effect of 0.03 is invisible at this resolution.
- **"The 工商 flow pattern is the mechanism, case closed."** Flow is the most plausible explanation from Session 4's data, but stat-arb positioning, pairs-trade unwinding, and other sources remain live. Discriminating requires either intraday flow data or cross-index comparison across stocks with different flow profiles. Deferred.
- **"Correlations below Bonferroni threshold are useless."** Bonferroni is one correction option and a conservative one. A factor that misses Bonferroni at m = 100 but survives BH or Holm might still be real. A factor that misses all corrections at reasonable m is most likely noise. The verdict depends on the correction chosen and the number of tests committed to up front.

The net Project 3 contribution to the 小盘股 thesis: the toolkit for testing claims, not the claims themselves. Project 3 does not establish that small-caps have exploitable inefficiencies. It establishes that any claim to that effect must survive correlation testing, regression with robust standard errors, autocorrelation analysis, and multi-testing correction. Project 5 will put specific factor claims through that gauntlet. Any that survive are candidates for Project 7's backtester and Project 8's strategy evaluation. Any that don't survive are filtered honestly before they can mislead the strategy.

---

## Open items carried forward

**Session 1 notebook set_index audit.** Carried from Project 1 through all of Project 3. 5-minute check that dates are set as the index in Session 1's data-loading notebook. Confirmed still pending as of Session 5 close. Clear at Project 4 Session 1 open.

**Sortino formula audit on risk_toolkit.py.** Same status. 2-minute check that the denominator is `sqrt(mean(min(r - MAR, 0)**2))` and not `std(returns[returns < 0])`. Clear at Project 4 Session 1 open.

**Helper promotion to project3_utils.py.** Three helpers ready to lift: `fit_with_diagnostics` from Session 3, manual lag-k autocorrelation verification pattern from Session 4, null-simulation block from Session 5. Do at Project 4 Session 1 open.

**Multi-year replication of the 工商 flow pattern.** 2022-2023 data is already cached. A multi-year rerun of Ljung-Box on 工商 would test regime stability. If the pattern persists across years, the flow-driven mechanism becomes more credible. If it's 2024-specific, regime-specific explanations (particular ETF inflow episodes, 国家队 campaigns) become more plausible. Deferred.

**Cross-index comparison for 工商's flow pattern.** A mid-cap outside the main indices with similar market cap would be a natural control. If flow drives the pattern, the control should show no comparable push-pullback structure. Deferred to Project 5 or an earlier side-experiment if time permits.

**Translation of Ljung-Box and Session 3 findings into economic magnitude.** Statistical significance is not economic significance. The 工商 push-pullback produces small per-lag autocorrelation values that translate into small expected per-trade returns. Whether they survive transaction costs is the real question, and it takes concrete form in Project 4's backtester (Project 7 in the master plan).

**Benjamini-Hochberg and Holm-Bonferroni corrections.** Previewed in Session 5, not implemented. Formal coverage in Project 4.

**Bootstrap as the third member of the robust-corrections family.** Previewed in Session 5 as the counterpart to HC3 (one test) and Bonferroni (many tests). Specifically handles fat-tailed distributions where parametric formulas fail. Formal coverage in Project 4.

**Cross-sectional hypothesis from Session 3.** The 震元-vs-工商 volume-return sign flip is the qualitative claim that Project 5 will test properly at cross-sectional resolution. Carry the specific form of the hypothesis forward: "the sign of the volume-return slope systematically depends on market cap, with small-caps tending toward positive (slow information diffusion) and large-caps tending toward negative (flow-driven mean reversion)." Either verdict at cross-sectional resolution feeds directly into factor construction.

**Flow-exhaustion factor preview from Session 4.** "After N consecutive same-direction days in an index-constituent large-cap, fade the move." Flagged as a possible factor, not yet a factor. Needs cross-sectional testing in Project 5 or Project 6.

**Small-cap autocorrelation pooled cross-sectionally.** Published small-cap lag-1 is 0.02 to 0.05. At N = 241 per stock across 30 stocks, the pooled test is much better powered than the single-stock test. Proper test of the slow-information-diffusion story. Deferred to Project 5.

---

## Bridge to Project 4

Project 4 formalizes the hypothesis-testing framework that Project 3 built piecewise. The session-level content expected based on the learning plan:

- Session 1 extends the null-hypothesis concept from Session 5 into a complete mental model using the coin-flip framework. Null hypotheses, p-values as tail probabilities under the null, and the difference between "probability of the data under the null" and "probability of the null given the data" (the latter is what people often want; p-values don't give it).
- Session 2 covers t-tests for comparing two groups, applying the robust-inference habits from Project 3 Session 3 in a new context.
- Session 3 formalizes multi-testing with Bonferroni, Benjamini-Hochberg, and Holm. The Session 5 simulation will feel like a foundational case rather than a preview.
- Session 4 introduces bootstrap methods as the third member of the robust-corrections family. HC3 (one test, messy noise) + Bonferroni (many tests) + bootstrap (non-normal data) covers the three main ways default statistical formulas lie on financial data.

The direct carry-forward: the testable claims from Project 3 (震元-vs-工商 sign flip, 工商 flow pattern, small-cap slow-information story) become the concrete targets for Project 4's formal machinery. Any that survive Project 4's stricter tests are candidates for Project 5's factor work. Any that don't are filtered honestly before they can distort the factor research.

The methodological carry-forward: every Project 4 technique will extend a Project 3 habit. Null simulation extends Session 5. Robust standard errors extend Session 3. Joint testing extends Session 4. Correlation and regression as measurement tools extend Sessions 1 and 2. Project 4 is not a new direction; it's the formalization of what Project 3 built up informally.

The 小盘股 thesis status at Project 3 close: unchanged from the Project 2 closeout version in its claims (small-caps have structural reasons for inefficiency, measurable volatility and tail differences, worse individual-stock tail risk). Upgraded in its testing machinery (now equipped to run the tests properly). No specific factor claims yet. Those start in Project 5 after Project 4 completes the hypothesis-testing toolkit.

---

Project 3 is closed. Suggested conversation name for the next session: `2026-04-22 — Project 4 Session 1: Null Hypotheses, P-values, and the Coin-Flip Framework`.
