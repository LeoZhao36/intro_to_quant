# Project 3 Session 1 Handoff: Pearson, Spearman, and Flow-Rotation Correlation

**Completed:** 2026-04-21
**Session location:** Phase 2, Project 3 (Correlation and Regression), Session 1
**Status:** Closed. Ready for Session 2 (Scatter plots, regression lines, R²).

---

## Key takeaways

- **Pearson correlation is Pearson on raw returns; Spearman is Pearson on ranks.** The construction is identical across the two; only the input differs. Ranks downweight extreme-move days and upweight ordinary days, which matters enormously for fat-tailed A-share data where a handful of days dominate the Pearson estimate.
- **Correlation between two stocks decomposes into shared factor exposures plus flow-rotation plus idiosyncratic noise.** Shared exposures include broad market, sector, size, and style layers. Flow rotation (risk-on/risk-off, size rotation, state-vs-private rotation) can push correlation below the shared-factor baseline, sometimes enough to flip it negative.
- **A negative correlation (工商 × 震元 = −0.09) between two A-share stocks in one year is a real measurement of flow rotation, not a mistake.** The mechanism: 工商 is the clean defensive state anchor, 震元 is the clean risk-on small-cap, and capital rotates between these poles rather than buying both.
- **The Pearson-Spearman gap is diagnostic.** P > S: correlation inflated by extreme shared-shock days. P < S: directional agreement masked by magnitude mismatch. P ≈ S: correlation stable across day types. When the gap exceeds about 0.05-0.08, the pair has a story worth understanding before using the number for anything.
- **"Industry" is too coarse as a category for correlation work.** Within banks, joint-stock vs state-owned is a real factor axis worth ~0.25 of correlation (招商 × 平安 = 0.82 vs 招商 × 工商 = 0.54 and 平安 × 工商 = 0.45). Within-sector heterogeneity is a real driver, and factor models break sectors into sub-industries for exactly this reason.
- **Volume signal works in the one small-cap but not the large-caps.** 浙江震元 volume ratio has ρ ≈ +0.12 with next-day return. Large-caps near zero. Consistent with slow information diffusion in low-coverage stocks. Single-stock evidence, not a validated factor; needs universe test in Project 5.
- **Correlation is not stationary.** Regime-dependent flow dynamics can move the same pair between +0.50 (crisis) and −0.10 (rotation-heavy regime) without any change in underlying business characteristics. Every correlation number is window-specific.
- **Statistical significance is not economic significance.** ρ = 0.12 means R² = 0.014, explaining 1.4% of variance. Measurable but not tradeable alone. The economic-significance half of the question is where most published strategies quietly die.

---

## Reference conversations and documents

- Previous closeout: `2026-04-20 — Project 2 Session 5: Basket Rebuild, risk_report Promotion, and the Variance Derivation Chain` → `Project_Two_Closeout.md`
- Project 3 opening conversation (covers numbering-discrepancy resolution, utils.py rewrite, Pearson mechanism probing, three-pair exercise, six-stock matrix, rotation discovery, Pearson vs Spearman, volume-return test): `2026-04-21 — Project 3 Session 1: Pearson, Spearman, and Flow-Rotation Correlation in the Six-Stock Basket` → this document
- Next session: `Project_Three_Session_Two_Handoff.md` (to be created)

---

## Starting point

I entered Session 1 with the full Project 2 toolkit (risk_report, compute_drawdown, rolling volatility, the 涨跌停 price-based detection utility) and the bulk-vs-tails framework. I had used pairwise correlation ρ operationally in the Project 2 Session 5 variance-floor formula σ√[ρ + (1−ρ)/N] but without formally defining Pearson correlation or understanding its four-step construction. I had the decomposition concept informally (stocks share market exposure, sector exposure, and so on) but had never applied it as a working tool.

What I did not have: the explicit four-step Pearson construction, Spearman at all, the Pearson-Spearman gap as a diagnostic tool, any direct experience of correlation structure on A-share data, the flow-rotation term in the correlation decomposition, or the conditional-means verification technique.

---

## Session 1 thesis

Correlation is the foundational tool for measuring relationships between return series, and for A-share data it has specific failure modes that need to be understood before the numbers can be trusted. Build intuition through the four-step construction, see the result on real pairs with real mechanisms, encounter the failure modes (extreme-day weighting, nonlinearity, clipping robustness), learn Spearman as the complementary tool, and end with a concrete application (volume-return signal in 小盘股) that previews factor work.

The session also doubled as a code-cleanup exercise in its opening, fixing two real bugs in Project 2's utils.py before building on top of it.

---

## Progression through the session

### Pre-session: utils.py cleanup and the Sortino audit

Before opening any correlation work, I had flagged that Project 2's utils.py was "too populated and ugly" and wanted a fresh minimal utils.py for Project 3. Reviewing the old file revealed two real bugs rather than aesthetic ugliness: `compute_drawdown` and `detect_limit_hits` each had duplicate definitions at different line numbers, with the later definitions silently overwriting the earlier ones. Any smoke test calling the old signatures would crash at runtime. Separately, `compute_sortino` used the Sortino-Price 1994 definition (target downside deviation averaged over all days) while `risk_report`'s inline Sortino used `.std()` of downside-only returns, which is a different quantity. Two different formulas in the same file producing different numbers on the same data.

Rewrote into three clean files: a minimal `utils.py` with only the three data functions needed for Session 1 (to_baostock_code, get_stock_data, load_or_fetch), a consolidated `risk_toolkit.py` for Project 4+ reference with one canonical Sortino formula (kept Sortino-Price 1994 as the canonical because it is the textbook definition and the alternative is conceptually odd), and a minor improvement to `plot_setup.py` using `warnings.warn` instead of `print`. All smoke tests rewritten to match current signatures and verified to pass. Open item created: verify which Sortino formula actually generated the closeout numbers (ZZ1000 0.80, HS300 1.08) before any future comparison.

### Gate check and priors probing

Skipped the formal Phase 2 gate check on the basis of the Project 2 closeout already documenting the required capabilities. Instead went directly to probing my priors on correlation: what mechanism produces co-movement between two stocks, and what does my trading intuition say about yesterday's returns predicting today's.

On the correlation mechanism, I first said "industry relatedness drives correlation because news circulates in industries." After pushing, I added macro and geopolitical events as channels that can move unrelated stocks together. The formal framing introduced: any two stocks share some common factor exposure (broad market, sector, style) and some idiosyncratic variation; correlation is high to the extent the shared drivers dominate.

On momentum, I initially said I expect yesterday's returns to give information and that I combine volume-price patterns with moving averages. When pressed operationally (stock X closed yesterday +4.5% on elevated volume, what do you expect today?), I flipped to saying I don't think there's much pattern. The inconsistency itself was the informative part: I use momentum tools but articulate a no-edge belief, which is the typical retail pattern. Resolution deferred to Session 4's autocorrelation tool.

### Exercise 1: Three pairs of stocks

Pulled 2024 daily 前复权 data for 招商银行, 平安银行, 贵州茅台, 浙江震元. Computed Pearson correlation manually using the four-step recipe (centre each series, multiply day-by-day, average for covariance, divide by σ product) and verified against pandas `.corr()`. The two methods matched to floating-point precision, which is the point: `.corr()` is doing exactly the four steps I wrote out, nothing more.

Three-pair results:
- 招商 × 平安: ρ = +0.815 (same sector)
- 招商 × 茅台: ρ = +0.565 (different sector, both large-cap)
- 招商 × 震元: ρ = +0.171 (different sector, different size)

### Finding 1: The gap structure told the real story

My prediction was "correlation decreases as industry relatedness decreases." Ranking held, so the prediction was superficially correct, but the gap structure contradicted the mechanism.

Drop from pair 1 to pair 2: 0.25. Drop from pair 2 to pair 3: 0.39. The SECOND drop was bigger than the first. If industry were the dominant driver, almost all of the drop would happen at the industry boundary (between pair 1 and pair 2) with only a small additional drop between pair 2 and pair 3. The data showed the opposite pattern: industry accounts for some of the decline, and something ELSE (the size factor) accounts for an even larger share.

This was the first empirical observation that the correlation decomposition has multiple layers and that each layer contributes measurably. Industry is one layer; size is another; each costs you a specific slice of correlation when two stocks don't share it.

### Exercise 2: The six-stock matrix

Added 工商银行 (a fourth bank, this one a 四大行 state-owned) and 山西汾酒 (a second 白酒 name) to the basket for a 6×6 correlation matrix. Before computing, made a refined prediction: 招商 × 平安 > 招商 × 工商 because joint-stock vs state-owned is itself a factor axis; 茅台 × 汾酒 similar to within-joint-stock-bank correlation because 白酒 is a tight thematic trade and both are flagship premium names.

Both predictions held. Bank-bank pairs:
- 招商 × 平安 (both joint-stock): 0.82
- 招商 × 工商 (joint-stock × state): 0.54
- 平安 × 工商 (joint-stock × state): 0.45

Within-白酒: 茅台 × 汾酒 = 0.82, matching the joint-stock bank pair exactly. 

The "three-bank block" that a naive same-industry prediction would have expected did NOT appear cleanly in the heatmap. What actually appeared was a 2×2 joint-stock block plus 工商 dangling off at medium distance. Sub-industry is a real factor, visible in data, worth roughly 0.25-0.30 of correlation.

### Finding 2: The 工商 × 震元 = −0.09 puzzle and the flow-rotation mechanism

The matrix surfaced one genuinely surprising number: 工商 × 震元 was −0.09. Actively negative. In a universe where all stocks share broad market exposure (HS300 constituents average ρ ≈ 0.35, ZZ1000 average ρ ≈ 0.30 per Project 2 Session 5), negative pairwise correlation is structurally unusual. Both stocks should have a positive floor from shared macro exposure.

Worked out the mechanism through directed questioning rather than being told: 工商 is the cleanest "defensive state anchor" in the basket (四大行, SOE, state backing, dividend-yield franchise); 震元 is the cleanest "risk-on small-cap speculation name." When capital rotates between these poles (defensive flight-to-safety days vs small-cap risk-on days), they move in opposite directions on the same day. The rotation term in the correlation decomposition was large enough to overwhelm the positive broad-market term.

Extended decomposition framework:
**correlation = shared-factor-exposure + flow-rotation + idiosyncratic**

Factor exposure for 工商 × 震元: positive broad-market overlap, no industry overlap, opposite size-factor exposure, opposite state-vs-private exposure. Two negative rotation terms combined exceed the positive broad-market term. Net: slightly negative.

### Finding 3: Conditional-means verification

Before accepting the rotation story, verified the mechanism independently via conditional means on 工商's direction. On days when 工商 rose: 震元's mean return was −0.272%, median −0.317%. On days when 工商 fell: 震元's mean return was +0.221%, median +0.485%. The conditional gap (mean 0.49pp, median 0.80pp) confirms the rotation pattern is real and persistent across typical days, not an artefact of one or two days.

Notable detail: median gap (0.80pp) exceeded mean gap (0.49pp). This tells me the typical rotation pattern is even cleaner than the means suggest, and that a few outlier days (probably macro shocks where everything moved together, including both 工商 and 震元) diluted the mean-based measurement. This was the first time I saw mean-vs-median divergence with a named mechanism rather than just as a general principle.

### Finding 4: Pearson vs Spearman

Learned Spearman as "Pearson on ranks." Same four-step construction, inputs replaced by rank order (1 to N) instead of raw returns. This equalizes every day's weight contribution: the biggest up-day counts exactly as much as the median day.

Before running, made three predictions:
1. 工商 × 震元: Spearman more negative than Pearson (I thought extreme-day co-movement was masking the rotation in Pearson)
2. 招商 × 平安: Pearson ≈ Spearman (shared exposure across all day types)
3. Any pair where Spearman should be LESS negative: I couldn't name one cleanly

**Prediction 1 was wrong.** S − P = +0.002 for 工商 × 震元. No meaningful difference. Pearson was NOT being inflated by outlier shared-move days. The rotation effect is present consistently across the full year, not selectively on typical days. My rotation-masking story was a plausible mechanism that happened not to apply here. Important update: even mechanism-based predictions fail, and the failure is informative (it tells me the rotation is persistent, not concentrated in typical days).

**Prediction 2 was correct.** 招商 × 平安 S − P = −0.045. Small gap.

The actual Pearson-Spearman disagreement patterns in the matrix were:

**白酒 pairs show Pearson > Spearman (gaps of 0.08 to 0.15).** Every pair involving a 白酒 name (except 震元 pairs) showed this. 茅台 × 汾酒 itself: Pearson 0.82, Spearman 0.71. The apparent sector tightness is concentrated in sector-shock days (consumption data prints, 高端消费 policy, earnings). On ordinary days, 白酒 co-movement is weaker than the Pearson headline suggests. This is exactly what Spearman exists to detect.

**工商-bank pairs show Pearson < Spearman.** 平安 × 工商: Pearson 0.45, Spearman 0.53. 招商 × 工商: Pearson 0.54, Spearman 0.58. Directional agreement masked by magnitude mismatch. 工商 moves sharply on SOE-specific days while joint-stock banks respond mildly. Pearson reads this as weak co-movement (small product of centred values); Spearman reads same-direction rank agreement at full weight.

**招商 × 平安 and 工商 × 震元 show Pearson ≈ Spearman.** For one the agreement confirms a robust high correlation, for the other it confirms a robust low correlation. Both are trustworthy as summary numbers.

Diagnostic principle locked in: when |P − S| exceeds about 0.05 to 0.08, the pair has a story. The direction of the gap is itself informative.

### Finding 5: Volume-return signal

Final exercise: test the classic retail intuition that abnormal volume predicts next-day return, with the mechanism of slow information diffusion in low-coverage stocks. Used volume ratio (today's volume / 20-day trailing average) as the normalization, lag the return by one day via `.shift(-1)`, correlate.

Predictions: 震元 largest in magnitude and positive (slow information diffusion); Pearson ≈ Spearman for 震元 (expecting a pervasive effect rather than outlier-driven).

Results:
- 浙江震元: Pearson +0.118, Spearman +0.119. Both predictions correct.
- Large-caps: all weak in magnitude, generally Pearson > Spearman by small amounts.
- 工商银行: Pearson −0.106, Spearman −0.031. Negative (flow-capitulation mechanism on defensive anchor), but concentrated in a few big-volume days rather than pervasive (the P > S gap of 0.075).

The 震元 finding is directionally consistent with the information-diffusion mechanism. Caveats attached explicitly: one stock is not a factor, R² of 0.014 is not tradeable alone, no transaction cost test, implementation timing (close vs open) matters. A proper universe-level test belongs in Project 5 factor methodology.

---

## Conceptual ground consolidated

**Pearson correlation measures linear co-movement between two series, bounded [−1, +1].** The four-step construction: centre each series by subtracting its mean, multiply the centred values day-by-day, average (this is the covariance), divide by the product of the two standard deviations. Memorize the steps, not the formula.

**Pearson weights extreme-move days quadratically.** The formula multiplies centred returns, so a day where both stocks moved ±4% contributes 16 units to the covariance sum while a day where both moved ±1% contributes 1 unit. This is the root cause of Pearson's sensitivity to outliers in fat-tailed data.

**Correlation decomposes into shared-factor-exposure + flow-rotation + idiosyncratic.** Shared factor exposure includes broad market, sector, size, and style layers. Each shared layer contributes positively to correlation. Flow rotation between poles of a common axis (defensive vs risk-on, large vs small, state vs private) contributes negatively and can overwhelm the positive exposure terms in rotation-active regimes.

**Spearman is Pearson on ranks.** The transform is `returns → rank(returns)`, applied to each series independently, then the four-step Pearson recipe runs on the ranked data. Ranks equalize day weights (differences between adjacent ranks are all 1) and are invariant to monotonic transformations. Spearman is partially robust to 涨跌停 clipping because the clipped value still gets the top-or-bottom rank regardless of whether the true move was +10% or +15%.

**The Pearson-Spearman disagreement direction is diagnostic.** Pearson > Spearman: correlation inflated by extreme shared-shock days; typical-day relationship is weaker than the headline. Pearson < Spearman: directional agreement masked by magnitude mismatch; typical-day relationship is stronger than Pearson shows. Pearson ≈ Spearman: correlation stable across day types. Compute both as default. Gap > 0.05-0.08 warrants investigation.

**Correlation is window-specific.** The same pair of stocks can show ρ = −0.10 in a rotation-active regime and ρ = +0.50 in a crisis regime without any change in business fundamentals. Any claim about correlation stability must be tested across regimes. Strategies relying on stable correlations (pairs trading, factor-neutral long-short, risk parity) must re-estimate frequently or accept drift.

**"Industry" is too coarse for serious correlation work.** Sub-industry (joint-stock vs state-owned banks) matters as much as main-industry sometimes. Factor models break sectors into sub-industries for this reason.

**Statistical significance is distinct from economic significance.** ρ = 0.12 means R² = 0.014, which is measurably non-zero but explains only 1.4% of variance. A single-stock correlation this small is not a trading signal; at most it is a hypothesis worth testing across a universe with proper cost analysis.

---

## Technical skills acquired

Production-ready fluency, without reference to documentation:
- Pearson correlation, manually via the four-step recipe and via `.corr(method='pearson')`
- Spearman correlation via `.corr(method='spearman')`
- Correlation matrix on a DataFrame of return series via `.corr()`
- Heatmap with annotated cells via matplotlib imshow plus nested ax.text loop, with vmin/vmax fixed for comparability across figures
- Lagged correlation using `.shift(-1)` to move tomorrow's value onto today's row
- Volume normalization via `volume / volume.rolling(20).mean()`
- Conditional-means verification: split series B by sign of series A, compare means and medians

Working fluency, with light reference:
- Choosing Pearson vs Spearman based on data properties and desired robustness
- Reading block structure in a correlation matrix
- Interpreting Pearson-Spearman gaps as diagnostic signals

Vocabulary I can now use fluently:
- Pearson correlation, Spearman correlation, rank correlation, covariance
- Factor exposure, shared factors, idiosyncratic variation
- Flow rotation, risk-on / risk-off, defensive anchors
- Multi-layer factor decomposition (market, sector, size, style)
- R² as fraction of variance explained, ρ² for simple linear case
- Pearson-Spearman gap as a diagnostic term

---

## Codebase now in the project

```
project_three/
  utils.py                         # Minimal: to_baostock_code, get_stock_data, load_or_fetch
  risk_toolkit.py                  # Reference for Project 4+. Not imported in Session 1.
  plot_setup.py                    # Unchanged pattern; minor improvement using warnings.warn.
  data/
    prices/                        # 6 stocks × 2024 cached
  Session_One.ipynb                # This session's work
```

`Session_One.ipynb` contents:
1. Imports, stock definitions, data loading
2. Manual Pearson computation (4-step recipe on 招商 × 平安)
3. One-liner Pearson on three original pairs with interpretation
4. Six-stock correlation matrix plus annotated heatmap
5. Conditional-means verification on 工商 × 震元
6. Pearson vs Spearman side-by-side (both matrices plus difference matrix)
7. Volume-return correlation test on all six stocks

Nothing promoted to `utils.py` this session. None of the helpers hit the rule-of-three threshold (each appeared in one notebook only). That is the correct call under the discipline established in the utils rewrite.

---

## Misconceptions corrected and what replaced them

**"Industry similarity drives correlation monotonically."** Approximately right for pair rankings but wrong on the gap structure. Size, ownership type, and flow-rotation patterns are each independent forces that can be as large as the industry effect. The correct model is multi-layer factor exposure plus a flow-rotation term, not a single "industry closeness" axis.

**"Same-industry pairs have similar correlations regardless of sub-industry."** Wrong. Within banks, joint-stock vs state-owned is worth about 0.25-0.30 of correlation. Within 白酒 the two premium flagships cluster tightly because the sector itself is a thematic trade, but across banking sub-types the cluster breaks down.

**"Negative correlation between two A-share stocks is unusual and might be a measurement error."** Unusual yes, error no. Negative correlation between a defensive anchor and a risk-on small-cap in a rotation-active regime is a real signal about flow dynamics. Conditional-means verification confirmed the pattern at mechanism level.

**My prediction (wrong): "Spearman should be more negative than Pearson for 工商 × 震元."** I attributed the headline −0.09 to outlier masking by macro-shock days. Data said no: S − P = +0.002. The rotation effect is present consistently on typical days; Pearson wasn't being distorted by extremes. Even a mechanism-based prediction can be wrong, and the failure sharpens the model (rotation is persistent, not concentrated).

**"Spearman is more honest than Pearson for A-share data; prefer Spearman by default."** Too strong. Both measure different things. Spearman is more robust, but when they agree there is no daylight between them. The practical rule is to compute both and use their relationship as a diagnostic, not to dismiss one in favour of the other.

---

## Habits explicitly built

**Decompose before correlating.** Before interpreting any pairwise correlation, mentally decompose the two stocks into their factor exposures (market, sector, size, state/private, style) and consider whether they sit on opposite poles of any active rotation axis. The shared exposures predict the baseline; the opposing exposures predict rotation-driven deviation.

**Compute Pearson and Spearman by default.** When the two agree within 0.05, report either. When they disagree by more than 0.05, understand why before using the number. The gap direction is diagnostic: P > S means outlier-driven, P < S means magnitude-masked directional agreement.

**Conditional-means verification on suspicious correlations.** For any correlation that contradicts a simple mechanism or carries a surprising sign, split by the sign of one variable and compute conditional means and medians of the other. This gives an independent mechanism-level check that does not depend on Pearson's formula.

**Treat every correlation number as regime-specific.** No correlation estimate generalizes across regimes without testing. Flag any claim that rests on correlation stability with the specific regime that produced the measurement.

**Prediction before measurement, with specific mechanism.** Every substantive number in this session followed an explicit prediction tied to a mechanism. When predictions failed (my Spearman rotation-masking hypothesis, my initial industry-monotonic story), the failure updated the model specifically rather than vaguely.

---

## Implications for the 小盘股 thesis

Defensible from Session 1 data (2024, six-stock basket):

- Small-caps in A-shares have structurally lower correlations with large-caps than large-caps have with each other, consistent with size as a distinct factor exposure. 浙江震元's correlations with the five large-caps ranged from −0.09 to +0.29, while within-large-cap correlations ranged from 0.10 to 0.82. The gap is large enough to be a real feature rather than sampling noise.
- Active flow rotation between defensive 权重股 and risk-on small-caps was measurable in 2024 pairwise correlations, reaching negative territory for the cleanest opposing pair. This is exploitable in principle as a hedging relationship, but only in rotation-active regimes.
- The small-cap (震元) showed a positive volume → next-day-return signal that large-caps did not show. Directionally consistent with the slow-information-diffusion hypothesis underlying the 小盘股 thesis. Single-stock evidence, needs universe-level confirmation.

Not supported by Session 1 data, worth flagging to avoid carrying forward:

- "The 工商 × 震元 −0.09 is a stable inverse relationship." It is a 2024 measurement under a specific rotation regime. Could collapse to 0 or flip positive in a different regime.
- "Small-caps generally have a positive volume signal." True of one stock in one year. Needs 30-50 small-caps vs 30-50 large-caps tested against each other with proper statistical methodology.
- "White-liquor-like sectors are good for diversification because within-sector pairs have high correlation on shock days only." Plausible speculation from the Pearson-Spearman gap but not tested. Would need a Spearman-based variance floor calculation to make this concrete.

---

## Open items carried forward

**Sortino formula audit from Project 2 closeout.** Two-minute check: which of the two Sortino formulas produced the reported ZZ1000 0.80 and HS300 1.08 numbers? Required for internal consistency before any future Sortino comparison. Moved forward from the Project 2 open items list; still outstanding.

**Regime-stability test of the 2024 correlation structure.** The current correlation numbers are window-specific. Re-running on 2023 or early-2024-only would test whether 工商 × 震元 stays negative, whether 白酒 pairs remain Pearson > Spearman, whether 震元 volume signal persists. Deferred pending research time; any claim that rests on the 2024 numbers should carry this caveat.

**Universe-level volume signal test.** 震元 single-stock result needs to become a proper factor test: run the volume ratio → next-day return correlation across 30+ small-caps and 30+ large-caps, compare distributions, test for statistically significant difference. Belongs in Project 5 methodology alongside the size factor.

**Spearman-based variance floor.** Project 2 Session 5 used Pearson ρ as the floor input in σ√[ρ + (1−ρ)/N]. For fat-tailed A-share data, Spearman ρ might be the more appropriate input, especially where the Pearson-Spearman gap is large (as in 白酒 pairs). Worth re-deriving with Spearman and comparing the two floors on the Project 2 baskets.

**The 震元 volume signal as a regression rather than a correlation.** Session 2 will re-approach the volume signal as a formal OLS regression with explicit coefficient, intercept, and residuals. Sets up the transition from "describe a relationship" to "fit a model and measure its limitations."

**risk_toolkit.py usage in a real analysis.** The file passes smoke tests but hasn't been imported into an actual workflow yet. Flag if any issues surface when first used.

---

## Bridge to Session 2

Session 2 covers scatter plots with regression lines, residual analysis, and R². The natural extensions from Session 1:

Visual calibration between correlation value and scatter cloud shape. A scatter plot of 招商 × 平安 returns (ρ = 0.82) should show a tight upward-tilted cloud. 工商 × 震元 (ρ = −0.09) should show essentially no visual tilt. The eye-level intuition of what different ρ values "look like" is useful to develop early, because later projects will rely on quickly interpreting scatter plots without computing ρ formally.

R² = ρ² for simple linear regression. This connects correlation to regression explicitly. The 震元 volume signal of ρ = 0.118 becomes R² = 0.014, which matches the "1.4% of variance explained" number cited at session close. Making the algebraic identity concrete through code.

Residual analysis as a model-adequacy check. For a correlation of 0.8, residuals should look random. If they show a trend, curvature, or clustering pattern, the linear model misses something. This is the first tool for detecting when Pearson/linear regression is the wrong frame.

The volume-return relationship is the natural candidate for the first real regression. Instead of just ρ = 0.118, fit next_ret = α + β × vol_ratio + ε, read the coefficient, intercept, p-value, residual plot. This bridges to Session 3 (statsmodels OLS with full output interpretation) and Session 4 (autocorrelation as a special case of lagged regression).

---

Session 1 closed. Suggested conversation name for next session: `2026-04-XX — Project 3 Session 2: Scatter Plots, Regression Lines, and R² on Volume-Return and Cross-Stock Pairs`.
