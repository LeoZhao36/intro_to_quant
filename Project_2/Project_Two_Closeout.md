# Project 2 Closeout: Volatility and Risk

**Completed:** 2026-04-20
**Project location:** Phase 1, Project 2 (Volatility and Risk), Sessions 1 through 5
**Status:** Closed. Ready for Project 3 (Factor Models: Size, Value, Momentum).

---

## Key takeaways

- **Variance is the average of squared deviations from the mean.** Every risk metric in Project 2 descends from this one construction. Std is its square root. Sharpe divides mean by it. Drawdown is a path-dependent view of cumulative volatility. The rest is transformation and aggregation.
- **Std scales linearly with data, variance scales quadratically (Var(cX) = c²·Var(X)).** Not an extra rule. Falls directly out of squaring being in the variance definition. The c² is why the diversification rule is σ/√N rather than σ/N; the square root is the undo of c² from dividing by N.
- **Basket variance = σ²·[ρ + (1−ρ)/N].** Correlation (ρ) is the floor no amount of diversification beats. Idiosyncratic risk cancels with N; common market risk does not. HS300 basket floor ≈ σ·√0.35, ZZ1000 ≈ σ·√0.30.
- **A-share measurement biases understate small-cap risk at three levels.** 涨跌停 caps truncate extreme returns. 连续跌停 prevents exit so measured drawdown is a mark-to-market ceiling, not a floor, on true loss. Today's constituent lists carry survivorship and inclusion biases. All three point the same direction.
- **Max drawdown as computed is mark-to-market, not exit-adjusted.** When the queue prevents fills (ST长康: 40 consecutive 跌停 days, volume ratio 0.06 meaning 94% of sell orders didn't fill), realized loss to a trapped position can exceed the measured price trajectory.
- **Sharpe penalizes upside and downside volatility equally.** Sortino fixes this by isolating downside std. For long-only strategies on assets with asymmetric return profiles (negative skew in ZZ1000 this window), Sortino is the more honest risk-adjusted number.
- **Small-N basket statistics are composition-dependent.** Session 3 5-stock HS300 basket concealed 8pp of structural vol gap between HS300 and ZZ1000 because the draw happened to include high-vol outliers. 25-stock revealed the real 10.4pp gap. Different metrics have different convergence rates: std converges fastest, max DD and kurtosis are very sensitive at N ≤ 25.
- **Small caps in this window earned more gross and lost more net.** 2023-04 to 2026-04: ZZ1000 basket +18.4% vs HS300 +15.1%. But Sharpe 0.60 vs 0.76, max DD 35.64% vs 16.42%, recovery 310 days vs 119, skew negative vs positive, kurtosis 6.93 vs 12.56. Higher raw return was more than paid for in volatility, drawdown depth, drawdown duration, and downside asymmetry.

---

## Reference conversations and documents

Each session has a standalone handoff and conversation. This closeout is the master summary.

- `2026-04-19 — Project 2 Session 1: Rolling Volatility`
- `2026-04-19 — Project 2 Session 2: Drawdown` → `Project_Two_Session_Two_Handoff.md`
- `2026-04-19 — Project 2 Session 3: Sharpe, Sortino, and the First Ratio Table` → `Project_Two_Session_Three_Handoff.md`
- `2026-04-20 — Project 2 Session 4: 涨跌停 Mechanism, Limit-Hit Utility, ST长康 Case Study` → `Project_Two_Session_Four_Handoff.md`
- `2026-04-20 — Project 2 Session 5: Basket Rebuild, risk_report Promotion, and the Variance Derivation Chain` (this closeout)

---

## Starting point

I entered Project 2 having closed Project 1 with a working understanding of return distributions, descriptive statistics, fat tails, QQ-plots, and the bulk-vs-tails framework. Project 1 had also taught me the three measurement biases (survivorship, inclusion, 涨跌停 clipping) conceptually. I had `utils.py` with `get_stock_data()` and data cached for 10 individual stocks plus 4 indices over the Project 1 window.

What I did not have: rolling-window calculations, any drawdown mechanics, any risk-adjusted return metric, the limit-hit detection utility (carried from Project 1 Session 3 as a flagged open item), concrete understanding of A-share microstructure at the trading-rules level, or the statistical derivation chain connecting variance to the σ/√N rule. The formulas were names I had heard. They were not things I could construct from first principles.

---

## Project 2 thesis

Every risk metric starts as an intuitive idea, formalizes into a number, and carries measurement baggage: biases, hidden assumptions, failure modes. The project's thesis was to build each metric intuition-first-then-formula-then-code, and to connect each number to the specific ways it can mislead. By the end of the project I should have a reusable toolkit AND a skeptical relationship with what the numbers report.

Small-cap focus runs through every session because the measurement baggage differs between large-caps and small-caps. 涨跌停 clipping, liquidity traps, composition-dependence of basket statistics, and regime-dependent correlation collapse all hit small-caps harder. The same formulas produce different interpretations depending on what the underlying microstructure is doing.

---

## Session-by-session progression

### Session 1: Rolling Volatility

Introduced `.rolling(window).std()` and computed 20-day rolling volatility for individual stocks and indices. Plotted rolling vol alongside returns to make volatility clustering visible: stretches of high vol follow stretches of high vol, quiet periods stay quiet until they don't.

Compared rolling vol for a ZZ1000 name against a HS300 name on the same axes. The ZZ1000 line sat meaningfully higher at baseline AND spiked more aggressively on stress days. Confirmed intuitively the Project 1 closeout's "small caps have higher ordinary-day volatility" claim, now seen as a time-varying line rather than a static annual number.

Discussed window-size choice: shorter windows are more responsive to regime changes but noisier; longer windows are smoother but slower to react. 20 trading days is roughly a month and is the most common choice for daily data. No single right answer.

The limit-hit utility (carried from Project 1 Session 3) was flagged at session open and deferred again. Continued deferring through Sessions 2 and 3.

### Session 2: Drawdown

Derived the drawdown curve from first principles. Start with cumulative returns from daily returns: `(1 + returns).cumprod()`. Take the running maximum: `.cummax()`. Drawdown at each point is `(cum - running_max) / running_max`, which is always ≤ 0. Max drawdown is the minimum of this series. Peak date is the running max up to the trough date; recovery date is the next point where drawdown returns to zero.

Plotted equity curve and drawdown as stacked panels with shared x-axis. Found peak-to-trough durations and trough-to-recovery durations from the date indices. Repeated for multiple stocks and indices, saw the pattern of drawdowns varying widely across the universe.

The session's most important concept: duration matters as much as depth. A 30% drawdown that recovers in two months is a different asset class from a 30% drawdown that takes two years. This came up again in Session 5's basket comparison where the depth ratio (2.2x) was matched by a similar duration ratio (2.6x) for small caps vs large caps.

### Session 3: Sharpe, Sortino, and the First Ratio Table

Derived Sharpe ratio: (mean return − risk-free rate) / std, annualized by √242. Walked through what it measures (reward per unit of total volatility) and what it hides (symmetric treatment of upside and downside, instability across different windows, assumption that volatility is the right risk measure).

Introduced Sortino as the downside-only variant: (mean − rf) / downside_std where downside_std uses only `returns[returns < rf]`. For long-only strategies on assets with asymmetric returns, Sortino is the more honest metric.

Built `build_ratio_table` as a notebook cell (not yet promoted to utils). Sampled 5 stocks from each of HS300 and ZZ1000 constituent lists, constructed equal-weighted baskets, and ran stats for all 10 individual stocks plus 2 baskets plus 4 indices. This table became the baseline for the Session 5 25-stock comparison.

The 5-stock basket choice was expedient and flagged even at the time as insufficient for population inference. Its specific unreliability became clear only in Session 5, when the 25-stock rebuild revealed that the 5-stock HS300 sample had been concealing the real structural volatility difference between HS300 and ZZ1000.

### Session 4: 涨跌停 Mechanism, Limit-Hit Utility, ST长康 Case Study

Three substantive deliverables. First, the current A-share rules by board (主板 ±10%, 创业板/科创板 ±20%, 北交所 ±30%, 主板 ST moved from ±5% to ±10% mid-2025) and intraday mechanics at the limit (封死 / 开板 / 一字板, including the counterintuitive observation that sealed-limit days can have LOW volume because the queue prevents most orders from filling).

Second, the A/B/C measurement framing that resolved my wrong direction on the cap's bias. Sample A: no events. Sample B: observed data with cap. Sample C: counterfactual uncapped data. B is wider than A but narrower than C. Only B-vs-C matters for risk, and it says the cap biases all standard risk metrics TOWARD NORMALITY. Measured std, |skew|, and kurtosis are all understated.

Third, the limit-hit detection utility, with a critical bug-and-fix episode. First pass used return-based detection with a tolerance of ±0.002. Failed at low prices because fen-rounding produced returns outside the tolerance band. Rewrote as price-based detection: reconstruct 跌停价 as `round_half_away(prev_close × 0.95, 2)` and check equality at price level. The bug was instructive because my measurement tool had a systematic bias at exactly the regime (crisis, low prices) where I most wanted to measure.

ST长康 case study: 40 consecutive 跌停 days from May 6 to July 1, 2024, triggered by disclosure of 资金占用 by 长江润发集团. Cumulative decline 3.25 → 0.37 = −88.6%. Volume ratio 0.06 on 跌停 days vs normal days, meaning 94% of sell orders didn't fill. This made "measurement understates risk" concrete: a position holder through this episode could not exit, so measured drawdown is a lower bound on realized loss. The liquidity trap is invisible to price-only metrics.

### Session 5: 25-Stock Basket Rebuild, risk_report Promotion, Variance Derivation Chain

Planned as the integration session. Two planned deliverables became three after I stopped mid-session and asked Claude to teach the math I had been using as black boxes.

Planned deliverables. Rebuilt baskets at 25 stocks per universe (HS300: 25 after filtering, ZZ1000: 22 after one post-window listing was removed) with seed 42 over 2023-04-01 to 2026-04-01. Promoted `build_ratio_table` into a full `risk_report()` function with Sharpe, Sortino, drawdown with peak/trough/recovery dates and durations, skew, excess kurt, optional limit-hit fraction. Smoke-tested and promoted to `utils.py`.

Third deliverable, unplanned. Halfway through I expressed frustration that I could interpret numbers but not construct them. Claude paused the execution work and walked me through the math from the ground up. Deviation from the mean → squared deviation → averaged → variance → linearity of variance for sums of independent variables → quadratic scaling Var(cX) = c²·Var(X) → σ²/N for the mean of N iid → σ·√[ρ + (1−ρ)/N] for correlated baskets. The geometric intuition (length ×c gives area ×c²) made the c² stop being a formula and start being a derivation. The σ/√N rule became something I could rebuild from the variance definition, not something I invoked as a black-box shortcut.

Applied the derivation to prediction 1 ("std gap widens from 5-stock to 25-stock"). The gap did widen: 3.85pp at N=5 → 10.40pp at N=22-25, nearly 3x. But not for the structural reason predicted. Back-fitting individual-stock parameters from the 25-stock observed stds (HS300: σ≈28.5%, ρ≈0.35; ZZ1000: σ≈48.4%, ρ≈0.30) gave a theoretical decay curve. The 5-stock HS300 observation (25.9%) sat 6.15pp ABOVE the curve. The 5-stock draw had included one or two high-vol outliers (likely 寒武纪 at 74.18% individual std, possibly 中金公司 at 32.36%) that inflated the basket. ZZ1000 5-stock and both 25-stock points sat on their curves. The prediction landed directionally correct, but the mechanism was sampling composition bias, not structural economics.

**Prediction scorecard:**

1. Std gap widens (5 to 25 stocks): CORRECT directionally, wrong mechanism.
2. Small caps bigger Sharpe: WRONG. HS300 > ZZ1000 at both resolutions (0.89 vs 0.61 at N=5; 0.76 vs 0.60 at N=25).
3. Small caps bigger max DD: CORRECT. 35.64% vs 16.42% depth, 310 vs 119 days recovery duration.
4. Large caps bigger kurtosis: CORRECT. 12.56 vs 6.93. Consistent with Project 1 Session 4 on independent data.

Three of four correct on direction, one of three correct on mechanism. Honest calibration for future predictions.

---

## Consolidated conceptual ground

**Rolling statistics are local estimates of distributional properties.** A 20-day rolling std estimates the current volatility regime. Shorter windows trade responsiveness for noise; longer windows trade stability for lag. The underlying return distribution's fat tails still apply, so even rolling std is an imperfect measure in the extremes.

**Drawdown is path-dependent.** It measures the worst mark-to-market stretch in the data, not just the worst single day. Two strategies with identical annual return and std can have very different drawdowns because drawdown depends on the ORDER of returns, not just their distribution. Duration (peak-to-trough, trough-to-recovery) adds a second dimension: a deep drawdown that recovers fast is a different experience from a shallow drawdown that takes years.

**Sharpe ratio is symmetric.** It penalizes upside volatility as much as downside, because it uses total std in the denominator. For assets with asymmetric return profiles (negative skew in ZZ1000 this window, positive skew in HS300), Sharpe understates the risk-adjusted appeal of the positively-skewed asset. Sortino uses downside-only std and fixes this asymmetry.

**Annualization conventions matter.** Daily std scales to annual via √242 (arithmetic, matching the standard Sharpe formula). Daily mean × 242 is arithmetic annualized return, matched to ann_std for volatility-scaled comparisons; it understates compounded growth. Geometric annualized return (1 + total)^(242/N) − 1 captures compounding but doesn't match the arithmetic std-scaling. Use arithmetic for risk-adjusted metric comparison, geometric for cumulative wealth reporting. `risk_report` outputs both.

**涨跌停 biases measurement toward normality.** The cap truncates extreme returns. Measured std, |skew|, and kurtosis are all understated relative to the uncapped counterfactual. The bias is worst where it matters most: crisis regimes and small-cap stocks where limit hits are frequent.

**Drawdown computed from prices is a ceiling on true loss, not a floor.** When 连续跌停 prevents exit (queue dynamics mean fills don't occur), realized loss to a trapped holder can be worse than the measured price trajectory. Liquidity is part of risk and is invisible to price-only metrics. ST长康 is the canonical illustration: 40 days locked, 94% of orders unfilled, the exit simply did not exist during the worst stretch.

**Variance is the average of squared deviations from the mean.** Every risk metric I use descends from this one definition. Std is √variance. Sharpe is mean/std. Drawdown is a path-dependent view of cumulative volatility but uses the variance foundation indirectly.

**Var(cX) = c²·Var(X).** This is not an extra rule. It follows directly from squaring being in the variance definition. When all deviations scale by c, their squared deviations scale by c². The average of scaled squared deviations is c² times the original variance. Std accordingly scales linearly with c (take the square root of both sides). Geometrically: doubling a length quadruples the area.

**Var(sum of N iid) = N·σ², Var(average of N iid) = σ²/N.** Sum's variance grows linearly. Division by N (to get the mean) multiplies variance by 1/N² (the c² rule). Net: σ²/N for the mean's variance, σ/√N for its std. This runs through all of inferential statistics and all of diversification theory.

**Basket variance = σ²·[ρ + (1−ρ)/N].** Stocks have a common market component with average pairwise correlation ρ. The ρ part stays (shared risk, unbeatable by diversification). The (1−ρ)/N part shrinks as idiosyncratic fluctuations cancel on averaging. Floor as N → ∞ is σ√ρ. Higher individual σ AND lower ρ both push the floor down; but for small caps, the higher individual σ dominates, so their floor sits higher than large caps' floor despite their lower correlation.

**Composition bias in small-N samples.** A single N-stock basket is one draw from the population of possible N-stock baskets. At small N, individual draws can land far from the population average for any metric, especially kurtosis, max drawdown, and Sharpe. Std converges faster than the others but still not instantly. The Session 5 demonstration was specific: my 5-stock HS300 basket hid 8pp of structural vol difference; the 25-stock basket revealed it.

**Different metrics have different composition-sensitivity tiers.** Std converges quickly at N ≥ 20. Pairwise correlation stabilizes fast. Kurtosis and max drawdown are highly composition-sensitive at N ≤ 25. Sharpe sits in between because it uses both a noisy mean and a less-noisy std. For Phase 3 factor work this means: IC (computed over the whole universe) is robust, quintile-mean return (depends on small groups) is noisy, and max-drawdown-of-a-quintile-strategy is very noisy. Metric choice should follow the question being asked.

---

## Technical skills acquired

Production-ready fluency (can do without documentation):

- Rolling statistics: `.rolling(window).mean()`, `.rolling(window).std()`, picking windows
- Cumulative returns: `(1 + returns).cumprod()` and its relationship to log-returns via summation
- Drawdown construction: `.cummax()` then `(cum − running_max) / running_max`
- Peak/trough/recovery dates via `.idxmin()` and slice-based logic
- Sharpe from scratch: `(excess_mean / std) * sqrt(242)`
- Sortino: same structure but with `returns[returns < rf]` for the denominator
- Skewness and kurtosis via `.skew()` and `.kurtosis()` with the excess convention

Working fluency (can do with light reference):

- `risk_report()` as one-call consolidation of all the above
- Price-based limit-hit detection with A-share fen-rounding
- Index constituent sampling from AKShare with reproducible seeds
- Back-fitting implied σ_indiv and ρ from observed basket std at known N using another N as anchor
- 2-panel stacked plots (equity + drawdown) with event annotations
- Parameter sensitivity via side-by-side recomputation with and without specific dates (stimulus week excluded vs included)

New vocabulary I can use in context:

- Rolling window, lookback period, volatility clustering
- Running maximum, peak-to-trough, trough-to-recovery, mark-to-market
- Sharpe, Sortino, excess return, risk-free rate, annualization
- Arithmetic vs geometric annualization
- 封死, 开板, 一字板
- Price-based vs return-based detection, fen-rounding, point-in-time
- Composition bias, small-N effect, convergence rate
- Variance decomposition, σ/√N rule, ρ floor, irreducible correlated risk
- Idiosyncratic component, common component

---

## Codebase now in the project

```
project2/
├── utils.py
│   ├── get_stock_data                    (Project 0)
│   ├── [rolling vol + Sharpe + Sortino helpers from Sessions 1-3]
│   ├── _get_board_limit                  (Session 4, board inference from prefix)
│   ├── _round_half_away                  (Session 4, A-share fen rounding)
│   ├── detect_limit_hits                 (Session 4 v2, price-based detection)
│   ├── compute_drawdown                  (Session 5, returns DataFrame)
│   ├── risk_report                       (Session 5, full metric consolidation)
│   ├── print_risk_report                 (Session 5, formatted output)
│   └── _smoke_test_*                     (per-function sanity checks)
├── execute_smoke_tests()                 (aggregator calling all sub-tests)
├── plot_setup.py                         (unchanged, Chinese font setup)
├── data/
│   ├── prices/                           (10 original + 47 basket stock CSVs, 4 indices)
│   ├── hs300_sample_codes_25.csv         (Session 5)
│   ├── zz1000_sample_codes_25.csv        (Session 5)
│   ├── basket_returns_hs300_25stock.csv  (Session 5)
│   ├── basket_returns_zz1000_25stock.csv (Session 5)
│   ├── basket_component_returns_*.csv    (Session 5, wide-format per-stock returns)
│   ├── ST_changkang_case.png             (Session 4, 3-panel case study figure)
│   └── basket_comparison_equity_drawdown.png (Session 5, 2-panel comparison)
├── Session_One.ipynb
├── Session_Two.ipynb
├── Session_Three.ipynb
├── Session_Four.ipynb
└── Session_Five.ipynb
```

Reusable functions ready for Project 3: `risk_report` (drop-in for any return series), `compute_drawdown` (returns a full DataFrame useful for plotting), limit detection pair (`detect_limit_hits` + `_get_board_limit` + `_round_half_away`), and the basket construction helpers (`sample_constituents`, `load_or_fetch`, `pull_basket`, `build_basket_returns`).

---

## Misconceptions corrected during Project 2

**"Rolling std removes the volatility clustering problem."** Rolling std ESTIMATES current volatility but does not remove clustering; it makes clustering visible. The estimate itself is noisy and still subject to fat-tail effects.

**"Sharpe ratio is a universal risk-adjusted return metric."** It is one specific metric with one specific assumption (symmetric volatility). For assets with asymmetric return profiles, Sortino is more honest. For path-dependent risks (drawdown duration, recovery time), neither captures what matters. Calmar (return / max DD) and Sortino are practitioner alternatives, each with their own blind spots. Use the metric that matches the question.

**"涨跌停 caps widen measured volatility by adding extreme days."** Reversed direction at session open in Session 4. Compared to a sample with no extreme events, the cap's days ARE extreme. But compared to what actually happened in the uncapped counterfactual, the cap UNDERSTATES. The A/B/C framing fixed this: only B-vs-C matters for risk, and it runs in the direction opposite to the initial intuition.

**"Max drawdown is the worst possible loss."** Max drawdown is the worst loss IN MY DATA on a MARK-TO-MARKET basis. Realized loss for a trapped holder during 连续跌停 can be worse. Future data can be worse than past data (survivorship applied to risk metrics). Max DD is a lower bound on experienced risk, not an upper bound on possible risk.

**"If I can see all four moments I understand the distribution."** Moments describe a distribution parametrically only if it is nearly normal. Real return distributions aren't. The moments I compute are dominated by a handful of extreme observations, and a single event can flip skew direction or double kurtosis. Moments are starting points, not conclusions.

**"I can't make predictions because each sample is case-specific."** The strong skeptical position I briefly held mid-Session 5. Reversed: samples differ from populations in known ways, with known rates of convergence by metric. Different metrics have different composition-sensitivity. Prediction is meaningful with calibrated error bars; "meaningless" is the mode that makes quant trading impossible in principle, which is not what my experience says.

**"I just need the formulas to use the formulas."** Corrected mid-Session 5 by the variance derivation chain. Using formulas without being able to reconstruct them leaves me dependent on memory and unable to notice when I'm misapplying them. The chain from deviation to σ/√N to σ√[ρ + (1−ρ)/N] is now something I can rebuild. That reconstruction skill is what separates following a recipe from doing analysis.

---

## Habits explicitly built during Project 2

**Definition before predictions.** From Session 3 onward, when Claude introduces a new metric, the definition and construction come before any request to predict values. Predictions about a concept I haven't been shown are guessing-flavored and teach nothing. Probing priors about related phenomena (what I expect the causal mechanism to be) is fine and still happens pre-definition.

**A/B/C or tabular reframing when verbal arguments stall.** From Session 4: when Claude's verbal explanation of the cap's measurement-bias direction didn't land, collapsing the three cases into a labeled side-by-side table resolved it immediately. Rule: don't repair a failed verbal explanation with a more elaborate verbal explanation. Switch modality. My strength is reading structured comparisons, not parsing nested verbal claims.

**Whole-function pasting for code patches.** From Session 4's override_limit patch failure: "rest unchanged" gestures waste more time than repasting. Any function under ~30 lines should be pasted whole when showing a patch. The clarity is worth the tokens.

**Smoke tests with hand-verified expected values.** From Session 4's second smoke-test failure: an assertion against synthetic data I haven't hand-verified is as likely to be a wrong assertion as a correct one. Walk through the test inputs and compute the expected output by hand BEFORE writing the `assert` line.

**Crisp hypothesis + diagnostic cell for debugging.** From Session 4's rounding bug: propose a specific testable hypothesis, have Claude write a diagnostic cell that produces a clear yes/no answer, run it. Faster than discussion when the data can settle the question.

**Single-event audit.** Reinforced from Project 1 and applied throughout Project 2 (especially Session 5's stimulus-week experiment): before trusting a multi-year statistic, remove the most extreme observations and recompute. If the number changes dramatically, the statistic is really a statement about those observations.

**Direction check.** After any directional claim ("A is larger than B"), verify against the specific numbers before moving on. Session 5 caught Claude in a direction slip mid-chat ("the gap widens" when structural math says it should narrow); I was carrying forward a loose intuition. The correction required data.

**Ask for the derivation when the formula feels opaque.** New in Session 5. I had been using Var(cX) = c²·Var(X) and σ/√N for three sessions without being able to construct them. When I noticed this, I stopped the session and asked. The cost was 30 minutes of session time; the return was permanent ownership of the derivation. Worth doing again whenever a formula feels like a black box.

---

## Implications for the 小盘股 thesis, honest version

Defensible from Project 2 data (2023-04 to 2026-04, 25-stock HS300 and 22-stock ZZ1000 baskets):

- Small-caps have meaningfully higher ordinary-day volatility than large-caps. Annualized std gap at basket level is 10.4pp (27.9% vs 17.5%). This is not a small difference. Position sizing and volatility scaling must account for it.
- Small-caps draw down 2x deeper in crisis regimes (35.64% vs 16.42%). The specific evidence is the 2024-01-22 to 2024-02-05 stretch where small caps continued falling for two weeks after large caps had bottomed.
- Small-caps take much longer to recover. 310 vs 119 days. A 小盘股 strategy must tolerate year-plus underwater stretches, or have specific mechanisms for exiting before the crisis.
- Small-caps show negative skew (−0.27) while large-caps show positive skew (+0.26) in this window. Asymmetric downside is a structural feature of this sample, not just a computed number.
- Small-caps had worse risk-adjusted return in this window despite higher raw return. Sharpe 0.60 vs 0.76, Sortino 0.80 vs 1.08. The higher gross was more than paid for.
- Measurement understates small-cap true risk via 涨跌停 clipping (making tail moves look capped at ±10%), 连续跌停 liquidity traps (making exit unavailable during the worst stretches), and survivorship/inclusion biases in today's constituent lists. The gap between measured and true risk is a floor on how conservative position sizing needs to be.

Not supported by Project 2 data, worth NOT carrying forward:

- "Small-caps are the better risk-adjusted play in all regimes." Not true in this window; wasn't true in 2024-H1 in particular. Any structural-underpricing claim requires regime specification.
- "The 2024-09 stimulus rally closed the gap between HS300 and ZZ1000." It compressed the gap temporarily. Both baskets ended near the same cumulative return, but via completely different paths. The policy event was a story about one month, not a structural feature of the relationship.
- "25-stock baskets are unbiased samples of the population." Better than 5-stock, but not unbiased. Inclusion bias (today's constituent list) and point-in-time data issues still apply.
- "Correlation stays stable across regimes." Not tested. Historically, correlations collapse UPWARD in crises (everything moves together on the way down). My window contained one mild crisis but not a true correlation-collapse regime. Any conclusion that rests on stable correlations should be re-tested against 2015 or any future stress period.

Net usable thesis after Project 2: small-caps in A-shares carry structurally higher volatility, deeper drawdowns, longer recoveries, and (in this window) negative skew; they delivered higher gross return but worse risk-adjusted return in this sample; measurement understates their risk at the crisis edge. Trading them profitably requires either (a) a factor edge that overcomes the structural disadvantages net of transaction costs, or (b) a regime-timing overlay that captures upside while avoiding the specific drawdown patterns. Phase 3 tests whether factor-based approaches produce such an edge.

---

## Open items carried forward

**The 4.6x up/down limit-hit asymmetry.** Session 4 found limit-ups outnumbered limit-downs 32 to 7 across the 10-stock sample. Three candidate mechanisms on the table (asymmetric event distribution, asymmetric retail behavior at the limits with 涨停板 follow-on strategies concentrating upside moves, survivorship in today's stock list) but not investigated. Revisit with the expanded 47-stock basket and a longer window, probably in Project 3.

**Point-in-time constituent membership.** Still deferred. My basket samples use today's index lists, which introduces inclusion bias (stocks added during the window are in the sample because they rallied into the index) and survivorship bias (stocks delisted during the window are missing). Project 3 factor testing requires proper point-in-time data to avoid look-ahead bias. Research time needed on data source selection.

**Date-aware ST regime handling.** The `override_limit` parameter in `detect_limit_hits` handles single-regime overrides only, not date-specific regime changes (主板 ST moved from ±5% to ±10% mid-2025). A proper v3 would take a DataFrame of ST status by date per stock and apply the correct limit per row. Deferred to Project 3 when point-in-time infrastructure exists.

**Geometric vs arithmetic annualization convention in plots.** `risk_report` outputs both; the docstring explains when to use each. Not yet standardized in plots and tables. Worth locking down before Project 3 to avoid inconsistency across reports.

**Log-scale price axes for 连续跌停 plots.** Constant-percentage decay renders as a straight line on log scale. My ST长康 plot used linear scale and the concavity misrepresents the "constant 5% per day" character of the episode. File for the plot style guide; apply for any future 连续跌停 visualization.

**Crisis-regime validation of basket conclusions.** My 2023-04 to 2026-04 window contains one moderate drawdown (2024-01-22) and one major rally (2024-09-24). Not enough regime variety to claim basket-level conclusions generalize. A re-run including 2015-H2 or the next true stress period would test whether the "basket diversification benefit" claim holds when correlations collapse upward. Deferred indefinitely; flagged any time a conclusion rests on this window alone.

**Walk-forward / out-of-sample mindset.** Not yet embedded in the codebase. Project 4 will formalize this properly. Mentally should already be the default for any strategy backtest; the framing "my full-sample backtest is optimistic about live performance" should precede every factor evaluation from Project 3 onward.

**End-of-window drawdown.** Both baskets show a sharp 10-15% pullback in the last ~6-8 weeks of my sample (2026-02 onward). The data cuts off before the trough is necessarily found. This is live-ish information for whatever is happening in the A-share market right now. For Project 3 purposes I treat it as "window ends mid-drawdown" and note as a caveat on the metrics. For any future paper-trading decision, the 2026 early-year trajectory matters.

---

## Bridge to Project 3

Project 3 opens factor work. First project is the size factor, which is the direct testable version of the 小盘股 thesis. Project 3 uses every tool from Project 2:

**Quintile sorting** is basket construction stratified by factor value. I built equal-weighted baskets in Sessions 3 and 5. Project 3 Session 1 builds size-quintile baskets the same way, just with sort-before-bucket rather than random sampling. The composition-dependence lesson from Session 5 applies immediately: quintile portfolios at N ≤ 25 are noisy draws, especially for extreme quintiles (smallest and largest).

**risk_report** applies to quintile portfolios as-is. Project 3's quintile-return analysis is risk_report applied to Q1 returns, Q5 returns, and Q1-minus-Q5 long-short returns, tracked over time. The function I just promoted does exactly what's needed.

**IC (Information Coefficient)** is the cross-sectional rank correlation between factor value at time t and stock returns at time t+1. Uses the correlation tools from Project 1 Session 4 applied cross-sectionally rather than across time. IC is robust where quintile-return is noisy because it averages over the whole universe on each date, not just over 5-stock buckets.

**Point-in-time data becomes mandatory.** Any factor testing that uses today's market cap to sort historical stocks introduces look-ahead bias. Project 3 Session 1's first task is sourcing proper point-in-time market cap data. This may take one session just for data plumbing.

**Variance decomposition informs factor portfolio construction.** A multi-factor model combining size, value, momentum will work well only if the factors have low pairwise correlation (low ρ across factor return series). The σ√ρ floor concept applies to factor portfolios exactly as to stock portfolios.

The math chain from Project 2 Session 5 (deviation → variance → Var(cX) = c²·Var(X) → σ/√N → σ√[ρ + (1−ρ)/N]) is the full statistical machinery needed for Project 3. Nothing new will be derived from scratch; Project 3 applies the existing machinery to a new domain.

---

## Personal reflection

*[to be filled in after letting this sit for a day]*

---

Project 2 is closed.

Suggested conversation name for Project 3 opening session: `2026-04-XX — Project 3 Session 1: Size Factor, Point-in-Time Data, and Quintile Sorting`.
