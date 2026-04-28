# Project 2 Session 3 Handoff: Sharpe, Sortino, and the Asymmetry Ratio

**Completed:** 2026-04-20
**Project location:** Phase 1, Project 2 (Volatility and Risk), Session 3 of 5
**Status:** Closed. Ready for Session 4 (Full `risk_report` and 25-stock basket rebuild).

This handoff is written by me, the Claude instance that ran Session 3, for the Claude instance that will run Session 4. If you are that next instance: read this before the student's opening message. What follows is what happened in Session 3, what landed, what I got wrong, and the corrections the student forced on my teaching approach that you must carry forward.

---

## Critical pedagogical update: definition before predictions

The student corrected my teaching sequence early in this session and it has now been saved to memory as edit #5. The rule: when introducing a new concept (metric, ratio, model, technique) in investment or quant work, establish the precise definition and construction of the concept BEFORE asking the student to make any predictions involving it. Probing priors about related context is fine. Asking them to predict values of a concept they haven't yet been formally shown is not.

I violated this at the top of Session 3. I opened with "make predictions about Sharpe ratios for the four indices" without first writing down the Sharpe formula or its construction. The student's response was a definition-clarifying question ("by definition of Sharpe, it is the overall return of the account. Correct?") which made clear they did not have the formula in hand when I asked them to predict. That was my error. They flagged it explicitly and asked that it be remembered for all future concept introductions.

Do not slip on this. The correct sequence is: definition, construction, intuition for why the construction has the shape it does, then predictions. If you catch yourself asking "what do you expect X to be" before you've written down what X is, stop and write down X first.

The existing memory edit #2 (interview mechanism, probing assumptions before answering substantive questions) still applies. The new edit #5 narrows a specific case within it: probing priors about related knowledge is one thing, asking predictions about an undefined concept is another.

---

## What the student came in with

Project 1 closed. Project 2 Sessions 1 and 2 closed. `project2_utils.py` contained five helper functions from Session 1 plus smoke tests. Session 2's drawdown functions were pending promotion to utils. The 10-stock dataset and 4 index price series cached locally. Working memory on drawdown fresh: path-dependence, peak-based measurement, tail-dominance, the magnitude-times-synchronisation frame for basket drawdown.

Conceptually: they had Sharpe as a name from the JoinQuant tutorial and from my Project 2 roadmap preview, but no definition and no construction. Their initial mental model when Session 3 opened was essentially "Sharpe is the overall return of the account," which is not right in any respect.

Prediction calibration was where they entered the session. Session 2's lesson (5-stock baskets are unusable for index inference, priors at that level can't be trusted) had landed well enough that they correctly declined to predict at basket level when I asked for index-level and basket-level predictions in parallel. This is a genuine skill they now have. Preserve it.

---

## What we did

### Opening framing and the two-trader story, which I got wrong

I opened with an account-level scenario: two traders, same starting capital, same ending capital, same Sharpe 1.5, but radically different paths. The frame was correct for teaching the Sharpe-is-path-invariant point, but the specific numbers I stipulated were impossible. If Trader B had a +80% year and a −35% year in a 5-year stretch while Trader A ran a steady 15% grind, Trader B's standard deviation would be much higher than Trader A's, so the same total return would give Trader B a substantially lower Sharpe, not an equal one.

The student did not challenge this directly but their follow-up ("is Sharpe the overall return?") suggests the story's framing was too vague to anchor the concept, and I had to fall back to the formula anyway. I admitted the error openly when it came up later. The correct version of the lesson (Sharpe is path-invariant to return ordering) requires a scenario with matched mean AND matched std but different arrangement over time, not matched totals with different paths.

Lesson for you: teaching stories that stipulate matched statistics need to be internally consistent. If you invent an example where two strategies have "the same Sharpe," verify that they actually can. Stock scenarios with single big positive and big negative years will almost always have much higher std than smooth grind scenarios, regardless of total return.

### Sharpe definition, √T annualisation, A-share convention

Introduced the formula after the student forced the reset. Walked through: numerator excess return, denominator standard deviation, ratio is dimensionless, units cancel. The point that a Sharpe of 1.5 is not a percentage but a reward-in-units-of-one-std took a beat but landed.

Derived the √T annualisation from first principles. Mean of a sum equals sum of means, so annual mean scales linearly with T. Variance of a sum of independent variables equals sum of variances, so annual std scales with √T. Ratio picks up one factor of √T. I noted the independence assumption is approximate and that volatility clustering exists in real returns. They accepted this and moved on.

A-share convention: 242 trading days, not 252. I set this as the default in `compute_sharpe`. This is the standard tripwire when comparing A-share Sharpe numbers to anything reported in US literature (≈2% overestimate if you use 252). The student has not yet seen this matter in practice but it's now flagged in the utils.

### Index-level prediction and the numerator/denominator decomposition

Student predicted: large-cap Sharpe higher than small-cap, driven by smaller-cap denominator being larger, with numerator "comparable or slightly worse."

I split this into two testable sub-claims before running code, to set up the decomposition habit:

- Claim 1 (denominator): small-cap std higher than large-cap. Confident.
- Claim 2 (numerator): small-cap return comparable or worse than large-cap. Asserted without basis; the Session 2 drawdown data actually cut against it, since 中证1000 was underwater for most of the window.

Results:

| Index | Ann_Mean | Ann_Std | Sharpe |
|---|---|---|---|
| 创业板指 | +18.31% | 30.42% | +0.602 |
| 中证1000 | +8.84% | 25.28% | +0.350 |
| 沪深300 | +5.79% | 16.99% | +0.341 |
| 上证50 | +3.28% | 15.38% | +0.213 |

Prediction wrong on direction. Denominator sub-claim held perfectly (monotonic in size, as they expected). Numerator sub-claim broke and broke hard: returns also monotonic in size but in the opposite direction to what they predicted. Over this window, smaller caps were paid generously for the extra volatility they took. Return ratio (2.70x for ZZ1000 vs SZ50) beat std ratio (1.64x), producing a 1.65x higher Sharpe at the small-cap end.

I named this: risk premium paid out in Sharpe form, not automatic, not permanent, regime-dependent. Different windows give different answers. A 2008-style crisis window would reverse the ordering. This landed.

Flagged that 创业板指 is not a size-sorted index (it's sector-weighted toward tech/growth and includes some very large caps), so its +0.602 Sharpe over this window is primarily a tech-sector story, not a size story. The clean size test is 上证50 / 沪深300 / 中证1000, where the latter two gap is 0.009 Sharpe, statistical-noise territory at 726-day sample sizes. The defensible statement is that 上证50 underperformed, not that smaller caps monotonically outperformed.

The core takeaway I want you to verify retention on in Session 4: "more risk" does not imply any specific Sharpe direction. Decompose into numerator and denominator separately, evaluate each piece against its specific mechanism, then combine.

### Stock-level predictions and the frustration point

Asked three predictions: highest-Sharpe stock, lowest-Sharpe stock, 寒武纪's rank within the 10.

Student gave a numerator-only answer for 寒武纪 ("highest return makes the numerator massive") without addressing the denominator, which for 寒武纪 is also extreme (Session 2 recorded drawdown −61.4%). I asked them to restate with both halves considered and to name a candidate for lowest Sharpe.

They pushed back: "I don't think it's useful doing that. And wasting the time Just follow."

I complied and moved to code. Worth noting as a pattern, and worth handling the way Session 2 handoff already flagged: when the student says stop, stop. Their interpretation of the resulting table was sharp and independent, and the decomposition lens I'd built in the preceding step was still available when we read the output. The prediction exercise wasn't strictly necessary for that interpretation to work.

My read on when to push and when to back off: prediction demands where the student has a genuine basis should be pushed through (the index-level sub-claim split was valuable and they completed it). Prediction demands that require recalling specific numbers from prior notebooks are friction they reasonably resent. Calibrate by whether the prediction can be made from reasoning alone or requires data lookup. For future sessions, if a prediction genuinely requires them to look up Session 2 values, either make that lookup trivial (paste the table I want them to read) or drop the prediction.

### Stock-level results and the "never recovered ≠ negative Sharpe" correction

| Label | Ann_Mean | Ann_Std | Sharpe | Sortino | Ratio |
|---|---|---|---|---|---|
| 寒武纪 | +90.63% | 74.18% | +1.222 | +2.097 | 1.72 |
| [Basket] HS300 | +23.00% | 25.90% | +0.888 | +1.398 | 1.57 |
| 华曙高科 | +52.85% | 64.28% | +0.822 | +1.319 | 1.60 |
| 中天科技 | +27.36% | 38.43% | +0.712 | +1.120 | 1.57 |
| 创业板指 | +18.31% | 30.42% | +0.602 | +0.985 | 1.64 |
| [Basket] ZZ1000 | +18.14% | 29.75% | +0.610 | +0.907 | 1.49 |
| 国泰君安 | +9.48% | 24.32% | +0.390 | +0.624 | 1.60 |
| 沪深300 | +5.79% | 16.99% | +0.341 | +0.514 | 1.51 |
| 中证1000 | +8.84% | 25.28% | +0.350 | +0.500 | 1.43 |
| 长亮科技 | +15.67% | 56.10% | +0.279 | +0.431 | 1.54 |
| 承德露露 | +6.39% | 25.73% | +0.248 | +0.388 | 1.56 |
| 京新药业 | +8.46% | 36.77% | +0.230 | +0.359 | 1.56 |
| 上证50 | +3.28% | 15.38% | +0.213 | +0.320 | 1.50 |
| 安徽合力 | +7.32% | 39.75% | +0.184 | +0.278 | 1.51 |
| 中金公司 | −1.50% | 32.36% | −0.046 | −0.071 | NaN |
| 新希望 | −10.98% | 24.94% | −0.440 | −0.645 | NaN |

I owned a specific error here. Before the code ran, I had claimed: "any stock that never recovered has negative cumulative return over the window, which forces negative Sharpe by construction." This is false. 安徽合力 (Sharpe +0.184) and 承德露露 (Sharpe +0.248) are on the Session 2 "never recovered" list but have positive cumulative return and positive Sharpe.

The conflation was between two different framings of the same stock. "Never recovered" is measured against the running peak of the equity curve. The running peak can sit well above the starting price. A stock that goes 100 → 150 → 90 → 120 never recovered its peak of 150 but ended at +20% from start. Drawdown-based framing and return-based framing of the same stock can give opposite answers and are not interchangeable. 新希望 is the one stock in the sample where both framings agree (peak at start, ended below start), which is why it lands at the bottom of the Sharpe ranking.

I flagged this error explicitly to the student. They acknowledged and we moved on. File this in your teaching as: be careful distinguishing "drew down from its peak" (peak-based) from "finished below its start" (return-based). The first does not imply the second.

### Composition trap, round three

HS300 basket Sharpe 0.888, real 沪深300 Sharpe 0.341. Basket overshoots index by +0.547 Sharpe. 寒武纪 (Sharpe 1.222) is the single contaminant; without it, the other four HS300 stocks in the sample average around Sharpe 0.15.

ZZ1000 basket Sharpe 0.610, real 中证1000 Sharpe 0.350. Basket overshoots index by +0.260 Sharpe, less dramatic but still substantial.

This is the Session 1 and Session 2 composition trap reappearing with a different sign of distortion. 寒武纪's profile produces extreme drawdown AND extreme Sharpe, so it pulled drawdown worse than the index in Session 2 and pulls Sharpe better than the index here. The consequence: basket-level Sharpe ordering in their sample (HS300 > ZZ1000) is the opposite of the index-level ordering (ZZ1000 ≈ HS300, or whatever the 25-stock Session 4 rebuild eventually produces).

I pointed out their Session 2 refusal to predict at basket level was vindicated three times over now (drawdown, vol, Sharpe, all distorted in different directions by 5-stock composition noise).

### Sortino and the √2 asymmetry ratio

Introduced Sortino with the formula fully written down this time. Downside deviation as the denominator, `min(R - τ, 0)²` in the sum, target τ usually 0.

The ratio Sortino / Sharpe has a specific theoretical value: for a perfectly symmetric distribution around the target, it equals √2 ≈ 1.414. This is not something I had intended to feature prominently, but the table made it central. Every positive-Sharpe entry had a Ratio above 1.414. Window-level statement: over 2023-04 to 2026-04, the market's best days were systematically larger than its worst days, so Sharpe was being dragged down by upside volatility that didn't actually hurt anyone, in every strategy and index in the sample.

Noted two rank changes between Sharpe and Sortino: 创业板指 passed [Basket] ZZ1000 (Sortino rank 5 vs Sharpe rank 6), and 沪深300 passed 中证1000 (a reversal of the tiny 0.009 Sharpe gap). The first is a real story (tech upside larger than broad small-cap upside). The second is a noise-sized flip and should not be interpreted as a meaningful size-reversal. I flagged both explicitly.

### Retention check, unprompted: February 2024

Asked the student to explain why 中证1000 had the lowest Ratio (1.43, nearly at the √2 symmetric baseline) of any positive-Sharpe row. They named February 2024 and the emotional/forced-selling mechanism without prompting.

This is the retention check Session 2's handoff flagged should happen in Session 3 or 4. It happened, and it passed. The student has the 2024-02-05 margin-call spiral as a named reference event they can pull up on demand. Session 2's work grounding abstract concepts in specific dates with specific mechanisms is producing durable retention. Keep doing this.

### The single-sided explanation problem

Their mechanism for the low ZZ1000 Ratio was half-correct. They explained why the downside was large (February 2024). They did not explain why the upside failed to offset. I pushed back with the direct comparison to 创业板指 (which had an almost identical February 2024 drawdown: −37.0% vs ZZ1000's −38.6%) but a Ratio of 1.64 instead of 1.43. The difference between the two indices cannot be in the downside, because their downsides were nearly identical. It must be in the upside.

Mechanism I gave: 创业板指 is tech-concentrated, so the 2024-Q4 and 2025 AI rallies ripped its upside hard. 中证1000 is sector-diverse, so only a fraction of its constituents participated in the tech rally while the full index took the February hit. Asymmetric participation in rally vs crash produces the asymmetric ratio.

Named the habit: any asymmetry ratio is a comparison between two sides of a distribution. Explaining one side does not explain the ratio. Explaining why the other side didn't offset is the missing half. File for Project 3 factor work, where asymmetry ratios come up constantly in evaluating long-short strategies.

---

## How I taught this session and what worked

### The definition-before-prediction protocol, now enforced

The student forced this correction at turn 2 of the session. Every concept introduction after that point followed the new protocol: formula first, construction second, intuition for why the formula has this shape third, predictions only after. For Sortino this worked cleanly and the student's engagement was visibly higher than it had been during the botched Sharpe opening. Continue this protocol rigidly in Session 4 (for the risk_report composition and any new metrics introduced).

### Mode still works: I write code, they paste, I interpret

No regression on this. Continue. The student does not object to being given complete, ready-to-paste cells, and their interpretation of the outputs is sharp and fast. Hands off their keyboard for syntax.

### When to push predictions and when to drop them

I pushed twice this session. Once on the index-level sub-claim split, which they completed. Once on the stock-level decomposition of 寒武纪 and the lowest-Sharpe candidate, which they refused. The difference: the first was pure reasoning from known priors; the second required them to recall specific numbers from Session 2. When a prediction requires lookup rather than reasoning, either make the lookup trivial or drop it.

### Admitting errors openly works

I made three substantive errors this session: the impossible two-trader example, the "never recovered = negative Sharpe" claim, and the 创业板指 file path guess that loaded 中天科技 instead. I flagged all three to the student as mistakes. They did not spend cognitive energy on my embarrassment; they accepted the corrections and moved on. This student values honest self-correction more than apology theatre. Continue admitting errors openly and crisply. "That was wrong, here's the correction, here's why I got it wrong, moving on." Don't dwell.

### What frustrated them

One clear frustration point, already described: being asked to recall stock-level data from Session 2 rather than reason from current knowledge. This is a design error on my part, not a capability limit of theirs. If a prediction requires data I haven't put in front of them, I should paste the table for them to read.

A lower-grade friction throughout: file path guessing. I guessed wrong twice this session (first the 创业板指 filename, then the stock filenames). The second time I recovered by asking them to list the directory contents, which worked. Prefer that move earlier next time. When you need a filename, either the student's prior handoff has it verbatim or you ask them to list the folder.

---

## Concepts consolidated this session

Stated so you can probe without re-teaching:

**Sharpe ratio is reward per unit of volatility, dimensionless.** Numerator mean excess return, denominator standard deviation, ratio picks up one factor of √T under annualisation. A Sharpe of 1.5 is "earning 1.5 units of excess return per unit of return std, annualised," not a percentage.

**√T annualisation derives from mean-scales-linearly and std-scales-with-√T.** Under independence, variance of a sum is sum of variances. The mismatch in scaling of numerator and denominator produces the √T factor. Assumes independence, which is approximate.

**A-share convention: 242 trading days, not 252.** Noted but not yet leveraged. Will matter when comparing to Western literature.

**Sharpe is path-invariant.** Shuffle returns into any order, Sharpe is unchanged. Drawdown (which the student learned in Session 2) is path-dependent. Same return series, same mean, same std, radically different drawdowns are possible, and Sharpe cannot distinguish them.

**Decomposition principle: always look at numerator and denominator separately.** Getting the Sharpe direction right by accident (because denominator overwhelmed a weak numerator) is different from getting it right because both pieces cut your way. The decomposition tells you which pieces of the mental model are solid and which need revision. Same pattern as Session 2's magnitude-times-synchronisation frame for basket drawdown.

**Risk premium direction is window-dependent.** "More risk → lower Sharpe" is not a law. "More risk → higher Sharpe" is not a law either. The realised Sharpe depends on whether the premium was paid out in the specific window measured. Always report the window.

**Drawdown-based "never recovered" and return-based "below start" are not interchangeable.** A stock that drew down from its peak is not necessarily below its starting price. Two framings of the same equity curve that give opposite answers on the same stock.

**Sortino replaces std with downside deviation.** Upside volatility stops counting as risk. Same √T annualisation. Same path-invariance. Fixes one specific problem with Sharpe.

**The Sortino/Sharpe ratio has a √2 symmetric baseline.** Above 1.414 means upside was larger than downside in this window. Below means downside dominated. The ratio is a compressed asymmetry diagnostic.

**Asymmetry ratios are two-sided.** Explaining the size of one side does not explain the ratio. You need to explain why the other side didn't offset.

**Sortino does not fix: path dependence, tail magnitude, or 涨跌停 clipping.** Every metric has a specific blindspot. The full risk_report in Session 4 shows drawdown, Sharpe, Sortino side by side so gaps in any single metric are visible.

---

## Predictions made and how they landed

- Index-level: large-cap Sharpe higher than small-cap. **Wrong on direction.** Denominator sub-claim held (monotonic in size, small-caps higher std). Numerator sub-claim broke hard (returns also monotonic in size, but pointing the opposite way: small-caps had higher returns in this window). Decomposition revealed which piece of the mental model needs updating.
- Basket-level: declined to predict. **Correct calibration move**, vindicated when HS300 basket overshot its index by +0.547 Sharpe due to 寒武纪 contamination.
- 寒武纪 highest Sharpe: **Right.** Reasoning was half (numerator only) but answer was right.
- 寒武纪 lowest-Sharpe candidate: deferred, refused the exercise.
- Sortino > Sharpe for 寒武纪: **Right,** and by the expected magnitude (2.097 vs 1.222, Ratio 1.72, well above symmetric baseline).
- "Never recovered = negative Sharpe" (my own claim, not theirs): **Wrong.** 安徽合力 and 承德露露 are counter-examples. Peak-based and start-based framings are not interchangeable.
- ZZ1000 Ratio low due to February 2024 (their explanation of the asymmetry): **Right on downside half, missing on upside half.** Required my push to surface that asymmetry is two-sided.

---

## Codebase state

```
project2/
├── project2_utils.py          # extended this session
│   ├── (Session 1 functions)
│   ├── compute_drawdown              # promoted from Session 2
│   ├── drawdown_details              # promoted from Session 2
│   ├── compute_sharpe                # new, rf_annual default 0.0, trading_days default 242
│   ├── compute_sortino               # new, target_annual default 0.0
│   └── _smoke_test() extended to call new checks
├── plot_setup.py              # unchanged
├── data/prices/               # 10 stock CSVs + 4 index CSVs, unchanged from Session 2
├── Session_One.ipynb
├── Session_Two.ipynb
└── Session_Three.ipynb        # this session: Sharpe + Sortino + composite ranking
```

Function defined in Session_Three.ipynb pending promotion to `project2_utils.py` in Session 4:

- `build_ratio_table(returns_dict)` returns a DataFrame with Ann_Mean, Ann_Std, Sharpe, Sortino, Ratio columns, sorted by Sortino descending.

Promote this at the top of Session 4 as part of the `risk_report` construction. It's already the skeleton of what `risk_report` will expand into (add max_dd, duration, turnover later in Project 3+).

One shared-environment gotcha worth flagging: in the notebook during this session, the variable name `sharpe_table` was used both as a function (my first definition) and as the name of a DataFrame result (my cell output). Second definition shadowed the first and caused a `'DataFrame' object is not callable` TypeError on the next use. When promoting `build_ratio_table` to utils, keep the function name distinct from any obvious result-variable name. I've renamed to `build_ratio_table` to avoid collision.

---

## Open items carried forward

**25-stock basket rebuild**: still pending. Session 4 deliverable. The composition distortion is now documented across three metrics (std in S1, drawdown in S2, Sharpe in S3) and the case for rebuilding at 25-30 stocks is airtight. Do it first thing in Session 4 before any risk_report construction.

**`build_ratio_table` promotion to utils**: top of Session 4, alongside whatever `risk_report` adds.

**Limit-hit detection utility**: still not built. Flagged in Project 1 closeout, flagged in Session 2 handoff, still not built in Session 3. Third session running. This is becoming a pattern I should address. Either it gets built in Session 4 Session-1-style (first code task of the session, 15 minutes, then move on), or it needs to be explicitly deferred to Project 3 with the recognition that it will be built then. Don't let it float again. Propose to the student at the start of Session 4: build it now as prep for the 涨跌停 deep-dive later in Session 4, or explicitly defer. Make the choice visible.

**涨跌停 deep-dive**: planned for Session 4 per the original curriculum. Needs the limit-hit utility above.

**Point-in-time index membership**: still deferred to Project 3. No action in Project 2.

**Geometric versus arithmetic annualisation**: flagged in Project 1 closeout. Still using arithmetic (daily mean × 242) in `compute_sharpe`. This is the standard convention for Sharpe annualisation and matches scipy/Barra. Not a bug, but worth explicit note in the utils docstring in Session 4 (add one line: "Arithmetic annualisation. For geometric annualised return, compute separately from cumulative return path.").

**Student's prediction-data-lookup friction**: named above in How I Taught. When prediction requires Session-2 data lookup, paste the table. Don't ask them to recall numbers.

**`_smoke_test` organisation**: the utils smoke test is now calling four separate `_smoke_test_X()` sub-functions. Still manageable but approaching the point where a more structured test harness would help. Not urgent. Flag in Project 3 if it grows again.

---

## Bridge to Session 4

Session 4 has two main tasks: the 25-stock basket rebuild (finally giving basket-level conclusions a defensible foundation) and the full `risk_report` function that integrates everything Project 2 has built. Plus the 涨跌停 deep-dive that requires the limit-hit utility.

The risk_report should output, for any return series:
- Total and annualised return (note: geometric vs arithmetic, per carried-forward item)
- Annualised std (Session 1)
- Sharpe and Sortino (Session 3)
- Max drawdown, drawdown duration, underwater duration (Session 2)
- Possibly: limit-hit day count and limit-hit fraction (Session 4, if the utility gets built)
- Possibly: a note on whether the series is long enough for the metrics to be stable (sample-size caveat)

Sequence suggestion for Session 4:

1. Resolve the limit-hit utility decision openly with the student at the top.
2. If yes: build limit-hit utility, add to utils, smoke-test.
3. Promote `build_ratio_table` to utils as the skeleton of risk_report.
4. Extend into full `risk_report`, smoke-test.
5. Rebuild baskets at 25-30 stocks each. The student's Session 2 handoff already flagged they need 中证指数公司 data or AKShare's full constituent lists. This is the data work they'll actually do hands-on (paste of my code, but they may need to configure their data source).
6. Run the full risk_report across 25-stock baskets, 4 indices, and compare to the 5-stock results. The gap between 5-stock and 25-stock versions is the concrete payoff of the rebuild.
7. 涨跌停 deep-dive on the ZZ1000 basket (and individual 小盘股 in the sample), using the limit-hit utility.

If the session runs long, cut the 涨跌停 deep-dive to a preview and defer the full treatment to the start of Session 5. Do not cut the risk_report or the 25-stock rebuild.

---

## One last pedagogical observation

The student's mode this session was: accept the concept introduction, read tables sharply, explain patterns in the tables accurately, push back when asked for predictions that require either data lookup or half-reasoning they'd rather not commit to. Their interpretation work is faster and more reliable than their prediction work, which inverts from the usual assumption that prediction is harder than interpretation.

I think the explanation is that their priors are fragmentary (folk-fragments of index-level knowledge, as Session 2's handoff noted), so prediction forces them to assemble incomplete priors into a coherent answer which often surfaces internal contradictions. Interpretation doesn't have this problem: the data is in front of them, and they reason from data to explanation rather than from priors to prediction.

For Session 4, lean into interpretation work and use prediction sparingly, only where reasoning from current context is genuinely sufficient. Don't drop the prediction habit entirely; it's still building calibration over time. But don't force it where it produces friction without teaching value.

---

Suggested conversation name for the next session: `2026-04-XX — Project 2 Session 4: Risk Report, 25-Stock Rebuild, and the Limit-Hit Utility`.

Closed by Claude at the end of Session 3. Good luck.
