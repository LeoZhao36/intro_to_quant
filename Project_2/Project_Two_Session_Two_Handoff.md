# Project 2 Session 2 Handoff: Drawdown, Duration, and the Composition Trap Revisited

**Completed:** 2026-04-19
**Project location:** Phase 1, Project 2 (Volatility and Risk), Session 2 of 5
**Status:** Closed. Ready for Session 3 (Sharpe Ratio).

This handoff is written by me, the Claude instance that ran Session 2, for the Claude instance that will run Session 3. If you are that next instance: read this before the student's opening message. What follows is what happened, what the student absorbed, what is still soft, and what I learned about how to teach this particular student that you should not have to re-learn.

---

## What the student came in with

Project 1 closed. Session 1 of Project 2 closed. Rolling volatility fluent. The 10-stock dataset (5 HS300, 5 ZZ1000) and 4 index price series cached locally. `project2_utils.py` working with five helper functions plus smoke tests. The 寒武纪 composition issue was flagged in their Session 1 handoff as a known contaminant of their HS300 basket.

Conceptually: they had the bulk-versus-tails framework from Project 1 in hand as a classification rule but had not applied it to a new metric. They had no prior exposure to drawdown as a named concept. Their mental model when the session opened was "drawdown means percentage decline in stock price," which is partial and misses both the peak-based structure and the path-dependence that distinguish drawdown from volatility.

On predictions going in: 寒武纪 would have the worst individual drawdown, ZZ1000 basket would have the worse basket drawdown because small caps crash harder. First was wrong (华曙高科 was worse). Second was wrong in an instructive way (the baskets tied, for reasons worth understanding).

---

## What we did

### Single-stock drawdown walkthrough on 寒武纪

Wrote out the three-line computation (`.cumprod()` for equity, `.cummax()` for running peak, `(equity - peak) / peak` for drawdown) and ran it on 寒武纪. Max drawdown came in at -61.4% on 2024-02-05.

This was the first genuine surprise of the session. The student had expected the 2025 selloff to be the deepest drawdown because the raw price chart made it look catastrophic (1600 down to 1000 in visible yuan terms). The actual worst drawdown was in early 2024, from a much lower price level (280 down to roughly 110). The lesson landed: raw price chart visual impact tracks absolute yuan amounts, not percentage drawdown. The deepest drawdown is the one with the largest peak-to-trough ratio, which can come from a modest-looking episode at a low price level.

I produced a three-panel figure (equity vs running peak, drawdown shaded area, raw price) to make the running peak's flat-or-up-only behavior visible, and to show duration as "the long flat stretch of the running peak line while the blue equity line sits below it." The visual of duration landed before we named it.

### Ten-stock drawdown table

Ran the same computation on all 10 stocks, sorted worst-first. Worst was 华曙高科 at -66.0% on 2024-09-23. Six of ten stocks bottomed on 2024-02-05 or within a week.

### The date-cluster diagnosis

When I asked the student what pattern they saw in the trough_date column, they pointed at the date cluster correctly, then offered "industry shock" as the explanation. I asked them to look at the six stocks (华曙高科 3D printing, 寒武纪 AI chips, 长亮科技 fintech, 京新药业 pharma, 新希望 pork, 中天科技 cables) and notice no industry covers them. They revised to "geopolitics / trade / tech competition," also wrong for the same reason.

I gave them the answer: 2024-02-05 was the bottom of a market-wide margin-call spiral in A-shares, driven by forced liquidations from leverage buildup in late 2023, amplified by 雪球 products hitting knock-in barriers and triggering mechanical selling. The lesson I tried to make stick: synchronised troughs across unrelated sectors and boards are a systemic signature, not an industry signature. Worth checking in Session 3 or 4 that they have retained this by presenting a similar cluster pattern without prompting.

### Basket drawdowns and the composition trap, round two

Wrote `compute_drawdown(returns)` as a reusable function, computed both baskets.

- HS300 basket: -32.6% on 2024-02-05
- ZZ1000 basket: -32.2% on 2024-02-05

Both bottomed the same day. The student's prediction that ZZ1000 would be worse was wrong by a hair in the opposite direction. I walked them through the two-part mechanism that produced the tie: 寒武纪 contaminating the HS300 basket (pulling it 8.5 percentage points below where the real 沪深300 index drew down), and the ZZ1000 individual troughs being spread across more dates (diluting the basket drawdown even though individual magnitudes were larger on average).

Generalised into the synchronisation point: basket drawdown depth is roughly individual magnitude times timing synchronisation. Same pattern as Session 1's basket volatility work, applied to drawdown. This abstraction was received well; they can verbalise it back.

### Internal contradiction in the student's prediction

Before we ran the basket code, the student gave two predictions that contradicted each other. First: ZZ1000 would have the worse drawdown because small caps crash harder. Second: large caps would have the worst drawdown during crashes because of co-movement. Both cannot be true for the same event. I flagged it; they had not noticed.

This is worth you being aware of because I think the pattern is more general in this student than this one incident. Their priors are often fragments of index-level or asset-class folk knowledge ("small caps crash harder," "large caps co-move") that they apply individually without checking whether the fragments compose into a coherent model. When you ask them to predict, they sometimes assemble two priors that individually sound right and collectively contradict each other. Good move is what I did: quote both statements back, ask which they meant, and use the resolution to pull out whether they were reasoning or guessing. Do not let this slide.

### Duration analysis

Wrote `drawdown_details(returns)` returning max_dd, peak_date, trough_date, recovery_date, and three duration fields (peak-to-trough, trough-to-recovery, total underwater).

Key findings:
- Four of ten stocks never recovered within the sample window (新希望, 中金公司, 安徽合力, 承德露露). The first two are over two years underwater and counting.
- 京新药业 took 340 trading days (about 16 months) to recover after its Feb 2024 trough.
- 华曙高科 had a 386-day total underwater period, comprising 289 days of decline plus 97 of recovery.
- HS300 basket underwater 351 days. ZZ1000 basket underwater 295 days. HS300 was worse on duration too.

I used the 京新药业 and 华曙高科 numbers to make the "long grind" failure mode concrete: a year-plus of watching the position decline, the hold-or-cut decision reconstituted every morning, psychological pressure compounding. The student had the depth dimension coming in; duration was new and it landed in the form of specific numbers on specific stocks rather than as an abstract concept. Continue grounding abstract risk dimensions in specific stocks in their own sample rather than idealised examples.

### Index cross-check

Pulled the four cached index price series and ran the same drawdown analysis:

| Index | Max DD | Peak | Trough | Recovery | Underwater |
|---|---|---|---|---|---|
| 上证50 | -19.9% | 2023-04-18 | 2024-01-17 | 2024-09-30 | 353 days |
| 沪深300 | -24.1% | 2023-04-18 | 2024-09-13 | 2024-10-08 | 354 days |
| 中证1000 | -38.6% | 2023-04-18 | 2024-02-05 | 2025-08-13 | 563 days |
| 创业板指 | -37.0% | 2023-04-18 | 2024-09-23 | 2024-10-08 | 354 days |

Clean monotonic size-drawdown ordering at the index level. The size effect the student had predicted exists; it just was not visible in the 5-stock baskets because composition noise dominated. Their prediction was right at the level they could not test with their data, and wrong at the level they could.

Three points I pulled out of this that matter for Session 3:

One, quantified the basket error in both directions. HS300 basket 8.5 pp worse than real 沪深300 (寒武纪 contamination). ZZ1000 basket 6.4 pp better than real 中证1000 (sampling luck). Both errors pointed toward erasing the size effect. Strongest evidence yet that 5-stock baskets are unusable for the Session 4 deliverable and they need to rebuild at 25-30 stocks.

Two, recovery speed diverged by size in a way worth remembering. Large-cap indexes (沪深300, 创业板指) recovered in 6-10 days because they bottomed in September 2024 right before the PBOC stimulus rally. 中证1000 took 366 days because it bottomed in February 2024 from a deeper hole. Small caps worse on both depth and recovery time; compounded effect is roughly 1.6x longer underwater.

Three, all four indexes peaked on 2023-04-18, one trading day after the sample starts. I used this as sample-window sensitivity in its sharpest form and reinforced the habit: always report the window when reporting a drawdown.

---

## How I taught this session and what worked

### The mode shift

Partway through, the student pushed back on the pedagogical approach and asked for a change. The original mode (carried over from how the curriculum document frames tasks) had me asking them to "open your notebook and code X." This does not match their actual state. They can read and run code fluently; they cannot write from memory right now because they have not used Python in three years. Session 1 was tolerable because it was largely porting Project 1 code, but Session 2's new material exposed the gap and they pushed back when it became frustrating.

I reset to: I write complete code cells ready to paste, they run them, they report outputs, I interpret with them. Their thinking effort goes into market logic, prediction, and interpretation. Hands off the keyboard for syntax. The agreement is explicit now and they confirmed it.

This worked. Conceptual density of the drawdown material landed much better after the mode change. Continue in this mode for Session 3. If you find yourself writing "now write a function that..." stop and write the function yourself. If you want them to modify something, show them the modification, do not describe it.

### Grounding abstract concepts in account-level experience

Related flag: the student was also frustrated because abstract concepts (path-dependence, tail-dominance, peak-based measurement) were arriving faster than they could tie to the project's purpose. When they said "I don't even feel connected to the purpose of this project," it was a real signal. I reset with a plain-language 100k → 150k → 90k account-value story, which grounded drawdown in a trader's actual experience before I touched any formal language. That worked. Continue to ground new abstract concepts in concrete "what would this feel like if it happened to your account" scenarios first, and introduce formal vocabulary after the intuition lands.

### What I noticed about their reasoning

Fluent at reasoning from data once they have a concrete table or chart in front of them. Interpretation of the index cross-check table was sharp, fast, and mostly self-driven with me prompting rather than leading. Where they struggle is in the prediction phase before the data arrives. Their priors are folk-fragments of index-level knowledge that do not always cohere and do not survive composition noise. The fix is not to stop making predictions (the habit is valuable) but to calibrate what to predict. I've flagged in Open Items that Session 3 should front-load index-level predictions where their priors might hold, then basket-level predictions where they almost certainly will not.

Self-reports accurately when they lose the thread. Take this as reliable data. When they say "this isn't clicking," they mean it, and the right move is to stop, not to rephrase. The Session 2 mid-session reset was initiated by them and improved the rest of the session substantially.

### What to avoid

Do not send them to implement functions from scratch. Do not introduce more than one genuinely new concept per 15-minute stretch without tying it back to an earlier one. Do not treat being wrong on a prediction as something to move past quickly. Wrong-prediction moments are where the session does most of its teaching, and the student tolerates being wrong well if we slow down and examine why. Moving too fast past a failed prediction loses the lesson.

---

## Concepts consolidated this session

Stated here so you can probe the student in Session 3 without re-teaching them:

**Drawdown is peak-based, not start-based.** Measured as percentage from the running maximum of the equity curve, not from any fixed reference. Student had the start-based version coming in and corrected cleanly.

**Drawdown is path-dependent; volatility is not.** Shuffle returns, vol is unchanged, drawdown changes dramatically. Connects to the Project 1 bulk-versus-tails classification: vol is bulk-dominated, drawdown is tail-dominated and path-dependent.

**Drawdown has two dimensions: depth and duration.** A 30% drawdown recovering in 2 months and a 30% drawdown recovering in 18 months are different risks, not different severities. Total underwater period (peak-to-trough plus trough-to-recovery) is what matches real trader experience.

**Basket drawdown depth depends on both individual magnitudes and synchronisation.** Systemic stress synchronises troughs and concentrates damage. Idiosyncratic stress desynchronises and dilutes damage at the basket level.

**A-share drawdowns cluster around market-wide events.** Six of ten stocks in the sample bottomed on 2024-02-05 because of a market-wide margin-call spiral. Synchronised troughs across unrelated sectors are a systemic signature.

**5-stock baskets are not usable for index-level inference.** Errors can run in either direction and together can erase real effects, as they did here for the size-drawdown relationship.

**Sample window sensitivity for tail metrics.** Max drawdown depends on where the window cuts. The specific 2023-04 to 2026-04 window measures from near a market high at its start; different start dates would produce different numbers. Always report the window.

---

## Predictions made and how they landed

- "Drawdown is the percentage of decline in stock price." Partial, corrected to peak-based during the session.
- "Structural difference from volatility is material-risk vs potential-risk." Imprecise, corrected to path-dependence and tail-dominance.
- "寒武纪 will have the worst individual drawdown." Wrong. 华曙高科 was worse (-66.0% vs -61.4%). Anchored on vivid recent price action; actual worst drawdown came through a longer, less visually dramatic grind.
- "ZZ1000 basket will have the worse basket drawdown." Wrong, baskets tied with HS300 fractionally worse. Right at the index level (-38.6% vs -24.1%), wrong at the 5-stock basket level because of composition noise.
- Internal contradiction: simultaneously predicted ZZ1000 would be worse (small caps crash harder) and that large caps would be worse in crashes (co-movement). I flagged; they had not noticed. Watch for similar contradictions in Session 3.
- "Industry shock" and then "geopolitics" as explanations for the 2024-02-05 trough cluster. Both wrong. Correct answer was market-wide margin-call spiral. Flag for retention check later.
- Duration predictions: not made. Should have been. Front-load this in Session 3.

---

## Codebase state

```
project2/
├── project2_utils.py          # unchanged from Session 1
├── plot_setup.py              # unchanged from Session 1
├── data/
│   └── prices/                # 10 stock CSVs + 4 index CSVs (unchanged)
├── Session_One.ipynb
└── Session_Two.ipynb          # this session's notebook
```

Functions defined in Session_Two.ipynb pending promotion to `project2_utils.py`:

- `compute_drawdown(returns)` returns `(drawdown, equity, running_peak)` as three pandas Series
- `drawdown_details(returns)` returns a dict with max_dd, peak/trough/recovery dates, and three duration fields

Do the promotion at the top of Session 3 before `compute_sharpe` and `compute_sortino` are written, so the utils file has a consistent risk-metric section. Extend `_smoke_test()` at the same time. A useful known case for drawdown: synthetic series `[+0.10, -0.20, +0.15]` produces equity `[1.10, 0.88, 1.012]`, running peak `[1.10, 1.10, 1.10]`, drawdown `[0.0, -0.20, -0.08]`, max_dd -0.20 on day 2.

One gotcha to test for: basket returns built with `pct_change().mean(axis=1)` produce NaN in the first row. If `.dropna()` is skipped, cumprod propagates NaN forward silently and the whole computation is wrong. The utils version of `compute_drawdown` should assert `returns.notna().all()` after any dropna, to surface this as a loud failure rather than a silent one.

---

## Open items carried forward

**Function promotion**: `compute_drawdown` and `drawdown_details` to utils at top of Session 3.

**5-stock basket inadequacy**: confirmed in drawdown analysis as in vol analysis. Session 4 deliverable needs 25-30 stocks per basket. The 10-stock setup remains acceptable for concept sessions.

**寒武纪 as HS300 basket contaminant**: now confirmed to affect both vol and drawdown by roughly similar proportional amounts. Note the pattern for Session 3 Sharpe analysis: 寒武纪 will likely produce a distinct signature, since its skew/kurt profile from Project 1 is known.

**Point-in-time index membership**: still deferred to Project 3.

**Prediction calibration**: the student's priors are index-level; their data is 5-stock-basket-level. For Session 3, front-load index-level predictions (where priors might hold) and put basket-level predictions second, with an explicit warning that composition noise may erase the effect. Not a discipline problem, a prediction-target-selection problem. Make it explicit rather than noting another wrong basket prediction.

**Duration prediction habit**: not practiced in Session 2. Introduce in Session 3 by asking them to predict both the scalar metric (Sharpe value) and its stability (rolling Sharpe variation) before computing.

**Mode-shift protocol**: the student reads and runs code, does not write it from scratch. This is the working agreement. Do not revert.

---

## Bridge to Session 3

Session 3 is Sharpe ratio and Sortino ratio. Infrastructure (equity curves, returns, basket construction) is in hand. Working memory is fresh on drawdown as a tail-dominated path-dependent metric. Setup for Sharpe is to contrast it with what they just did.

Sharpe is bulk-dominated by construction: mean return over standard deviation. Both numerator and denominator are bulk statistics. But the strategies Sharpe is used to evaluate carry tail risk (drawdowns, crashes, regime breaks), and a high Sharpe in a bull market tells you almost nothing about survivability in a bear market. This is the core thing I want Session 3 to land: Sharpe is a bulk metric used to judge tail risks, and the mismatch is the problem.

Sortino is the partial correction: replace std with downside deviation, upside vol stops counting against the strategy. Ask the student to predict before computing: for a stock with positive skew (like 寒武纪 in Project 1's measurements), will Sortino rank it higher or lower than Sharpe does, and why? This is a prediction at the level their priors should actually handle.

One substantive concept to ensure lands in Session 3: annualisation. Daily Sharpe is mean(returns) / std(returns). Annualised Sharpe multiplies by √252 (or more precisely √242 for A-shares, which have fewer trading days than US). The student has not seen this scaling factor derived. The derivation (mean scales linearly with time, std scales with square root, ratio scales with square root of time) is worth doing once, because it is the standard A-share-vs-US-convention tripwire. They should know both conventions and which to use.

Session 3's deliverable: a ranked comparison of Sharpe and Sortino across the 10 stocks plus 2 baskets, plus the extension of `project2_utils.py` with `compute_sharpe` and `compute_sortino` and smoke tests. Session 4 is the full `risk_report` plus the 25-stock basket rebuild.

---

Suggested conversation name for the next session: `2026-04-XX — Project 2 Session 3: Sharpe, Sortino, and What Risk-Adjusted Return Actually Measures`.

Closed by Claude at the end of Session 2. Good luck.
