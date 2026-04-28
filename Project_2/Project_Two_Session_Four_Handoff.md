# Project 2 Session 4 Handoff: 涨跌停板 Mechanism, Limit-Hit Utility, ST长康 Case Study

**Completed:** 2026-04-20
**Project location:** Phase 1, Project 2 (Volatility and Risk), Session 4 of 5
**Status:** Closed. Ready for Session 5 (25-stock basket rebuild and full `risk_report` promotion).

This handoff is written by the Claude instance that ran Session 4, for the instance that will run Session 5. Read before the student's opening message.

---

## Scope decision at session open

The handoff from Session 3 proposed packing three things into Session 4: the 涨跌停 deep-dive (the curriculum's stated Session 4 topic), the deferred limit-hit utility, the `build_ratio_table` → `risk_report` promotion, and a 25-stock basket rebuild. Plus a 连续跌停 case study.

I pushed back on that scope at the top of the session. My argument to the student: the curriculum's Session 4 content is the 涨跌停 deep-dive, and using Session 4 primarily to clean up deferred plumbing inverts the curriculum's pedagogical priority. I offered two paths, curriculum-aligned (涨跌停 focus, defer risk_report and rebuild to Session 5) and handoff-aligned (do everything, compress the 涨跌停 work). The student chose curriculum-aligned.

In retrospect this was the right call. The session used most of its budget on the rounding-edge case that broke our first detection utility, which was exactly the kind of deep methodological lesson the 涨跌停 topic was supposed to provide. Had we tried to also rebuild baskets and promote risk_report, the rounding bug would have been papered over instead of taught through.

**For Session 5:** the handoff-aligned agenda is now the plan. 25-stock rebuild first, risk_report promotion second, run across expanded baskets plus indices plus existing single stocks, compare to Session 3's 5-stock results.

---

## What the student came in with

Project 2 Sessions 1-3 closed. `utils.py` (note: named `utils.py`, not `project2_utils.py` as the Session 3 handoff wrote, the student is using a flat module name) contained volatility, drawdown, Sharpe, Sortino helpers plus `_smoke_test_X()` sub-functions called from an aggregator named `execute_smoke_tests()`. The 10-stock dataset and 4 index price series cached locally. Project 1 closeout concepts on bulk-vs-tails and measurement-not-reality still fresh enough that they recognised the A-shares-specific version of measurement-not-reality when it appeared.

Conceptually: they had the 涨跌停板 rule as a named concept from their trading experience and from the Project 1 closeout flagging it as a source of measurement bias. They did not have the current rule set (2025 ST rule change in particular), they had not thought precisely about WHICH direction the cap biases measured risk statistics, and they had no operational code for detecting limit-hit days.

---

## What we did

### Opening: current rule refresh

Web-searched and wrote down the current A-share rules as of April 2026. Key points for the student's reference and for future sessions:

- 主板 ±10%, 创业板 ±20% (since 2020), 科创板 ±20% (since launch 2019), 北交所 ±30% (since 2021-11-15).
- 主板 ST went from ±5% to ±10% mid-2025 (sometime after the 2025-07-04 public comment close on the 征求意见稿). This matters for the student's data window, which spans both regimes. ST长康 in May-July 2024 is firmly in the pre-change ±5% regime.
- 创业板 / 科创板 ST has always been ±20%, those boards never had a differential for ST.
- 新股: 主板, 创业板, 科创板 all unlimited for first 5 days, then normal limit. 北交所 unlimited day 1 only.
- 退市整理期: unlimited day 1, then ±10% for subsequent days.

Student confirmed their recollection broadly aligned with this, flagging nothing wrong.

### Intraday mechanics

Walked through the three scenarios: 封死 (sealed limit, queue visible on Level-1, low volume, stock pinned at close = limit), 开板 (queue breaks, stock trades back below limit, may re-seal later), and 一字板 (open = high = low = close = limit, no intraday variation at all). Student asked specifically whether hitting the limit stops trading. It does not. Price is pinned at the limit but orders continue to route to the queue, and depending on queue dynamics the price can stay pinned or come off.

Counterintuitive consequence I flagged explicitly: on sealed-limit days volume can be LOW, because the queue means most orders don't fill. Reading low volume on a 涨停 day as "quiet day" is exactly backwards. This set up the volume-ratio analysis that became the session's cleanest empirical finding.

### Measurement consequences: the A/B/C framing

The student got the direction of the measurement bias wrong initially. They said the cap widens measured std and fattens measured kurtosis, reasoning that limit-hit days are extreme and add tail mass. This is true if you compare to a sample with no extreme days at all, but it's the wrong comparison for risk assessment.

My first attempt at clarifying this was muddled and the student told me directly it was still ambiguous. The clean framing that worked was three samples side by side:

- **Sample A:** 250 ordinary days, no events. Typical moves 1-2%.
- **Sample B (measured, what you see):** 240 ordinary days plus 10 event days capped at ±10%.
- **Sample C (true, counterfactual, never directly observable):** same 240 ordinary days plus the same 10 events at their true unconstrained sizes (−25%, +22%, etc.).

Two true statements coexist: B's std and kurtosis are BIGGER than A's (the student's observation). B's std and kurtosis are SMALLER than C's (mine). Different reference points, both valid, but only B-vs-C is the question that matters for risk assessment because you are never in Sample A.

The direction that matters for strategy: the cap pulls measured std, absolute skew, and kurtosis toward normal. The cap is a bias-toward-normality machine. This connects directly back to Project 1 Session 3, where the student saw this empirically (the ±10% shelf on the 华升股份 QQ-plot) without having the framing to name the direction.

This A/B/C framing worked immediately. Note for Session 5 and beyond: when the student signals confusion on abstract causal claims, abandon the verbal argument and give them a three-sample or two-scenario setup they can read side by side. Their interpretation skill is strong, their abstract-reasoning skill is rustier. Lean on the strength.

### Limit-hit utility v1 and the frequency table

Built `_get_board_limit` (prefix-based inference of board) and `detect_limit_hits` (return-based tolerance detection, tolerance 0.002). Smoke-tested, ran across the 10-stock sample.

Student made a pre-data prediction: smaller cap → less liquid → caps retained for longer, therefore smaller stocks higher limit frequency. Good mechanism-based reasoning, but wrong for this question. The table showed 寒武纪 (large 科创板 AI name, one of the largest stocks in the sample by end-of-window cap) at the top with 1.38%, and genuinely smaller stocks like 承德露露 at the bottom with 0.14%. Size and liquidity were not driving the ranking.

The correction I named: **for first-day limit-hit frequency, news intensity dominates, not liquidity**. 寒武纪 sat at the centre of the 2024-2025 AI narrative and chip-export-control news cycle, producing repeated sector-wide shocks. 中金公司 (second place) rode stimulus and brokerage-rotation episodes. The frequency question is about how often a single-day shock is large enough to trigger the limit. Liquidity matters for the DURATION of limit events once started (the 连续 story), not the frequency of first-day hits.

This distinction (frequency vs duration, and different causal drivers for each) is important to preserve. File for Phase 3 factor work where the "liquidity premium" question comes up: liquidity's effect on returns is likely more about multi-day recovery patterns and turnover costs than about daily return distribution, at least during non-crisis regimes.

Second unexpected finding in the table: **4.6x asymmetry between limit-ups and limit-downs** (32 vs 7) across the 10 stocks. Much larger than the overall bullish tilt of the window would predict (中证1000 +8.84% annualised is mildly positive, not 4.6x-asymmetric positive). I offered three candidate mechanisms: asymmetric event distribution in this specific window (stimulus, AI, DeepSeek provided repeated upside shocks; downside shocks rarer and more diffuse), asymmetric retail behaviour at the limits (the 涨停板 follow-on strategy concentrates upside moves into full limit-hits, while downside fear produces pre-limit selling that dissipates bearish shocks across 6-8% moves), and survivorship (no failed stocks in the sample, no fraud events, sample is skewed toward stocks that survived the window). Did not investigate which mechanism dominates; flagged as a future question.

Third finding: three stocks (寒武纪, 中金公司, 安徽合力) contribute 19 of 32 limit-ups. Same composition-dominance pattern from Sessions 1-3 reappearing on a different metric. 5-stock baskets remain unusable for population inference, 10-stock totals remain dominated by a few narrative-riders.

### Case selection: ST长康

None of the 10 sample stocks had 连续跌停 episodes long enough to illustrate the liquidity trap. Searched the web for documented 2023-2026 cases. Three candidates surfaced:

- ST长康 (002435.SZ): 40 consecutive 跌停 days May-July 2024, triggered by May 5 evening disclosure of 资金占用 by 长江润发集团 (controlling shareholder). Terminal case, ended in 面值退市.
- *ST威创 (002308.SZ): 34 consecutive 跌停 days summer 2024, prolonged operational deterioration path to 面值退市.
- *ST深天 (000023.SZ): First-ever A-share 市值退市 case, July 2024.

Recommended ST长康 as primary: single clean trigger date, longest documented run, canonical governance-failure-to-delisting path. Data pulled cleanly via baostock despite the stock being delisted, 93 rows through the full window including the terminal 停牌 period.

### The rounding bug and its lesson

First pass on the analysis returned 21 跌停 days with longest run only 6. Headline narrative was 40. Something was off by 2x.

Traced it to the interaction between ST长康's low-price regime and the return-based detection tolerance. At prices below 2元, the rounding of 跌停价 to fen produced measured returns that oscillated between roughly −4% and −6%, too wide for a ±0.002 tolerance. The worked examples I laid out showed this directly: 前收盘 0.71 → 跌停价 round(0.71 × 0.95, 2) = 0.67 → measured return (0.67/0.71) − 1 = −5.63%. Tolerance-based detection at return level rejects anything further than 0.2% from the nominal limit, so it misses this day entirely.

Student ran the diagnostic cell. Result: **0 of 39 low-price 跌停 days flagged by return-based detection, 39 of 39 captured by price-reconstruction**. This was the cleanest "your measurement tool has a systematic bias at exactly the regime where the thing you're measuring matters most" lesson the session could have asked for, and it happened to our own code in real time.

I named the lesson explicitly: this is Session 4's content turning around and biting our own analysis code. The cap produces measurement artifacts, our naive measurement of the cap produces a secondary artifact, and the only way to see either is to compare against an external reference (the news narrative in this case) or to pressure-test the tool at its boundary conditions. File as the general principle: **when you build a measurement tool, the regime you most want to measure is often the regime where naive measurement fails hardest**.

### Utility v2 and the re-run

Rewrote `detect_limit_hits` using price-based detection: reconstruct the exchange-computed limit price from `round_half_away(prev_close × (1 ± limit), 2)`, check equality (with half-fen tolerance for float edge cases) against actual close. Correct at all price levels.

Extended the smoke test with a low-price crisis-regime block using prices pulled directly from the ST长康 data (0.71 → 0.67 → 0.64 → 0.61). Verified the regime produces returns both above and below nominal −5% (caught rounding-up-shrinking-deviation AND rounding-down-expanding-deviation).

### Re-run results: narrative match

With the fixed utility:

- **40 consecutive 跌停 days, May 6 to July 1**, matching the news narrative exactly.
- Cumulative decline from peak 3.25 (pre-disclosure) to last traded 0.37 (July 1): **−88.6%**.
- **Volume ratio of 0.06** (793K shares average on 跌停 days vs 12.7M on normal days). This was 0.13 in the first (buggy) run because misclassified days were dragging the "normal" average down. The true ratio is twice as severe as the first pass suggested.

Sub-lesson on the volume ratio shift: **when classification errors correlate with the quantity being measured, group-comparison averages move in opposite directions and the measured effect is compressed**. File for Project 3 factor research, where misclassification of value / growth / quality bins produces the same pattern.

### Concrete "what it meant to hold this stock" narrative

Walked the student through a 10,000-share position from May 5 through July 1. Key points:

- Each day, sell order placed at limit joins a queue of tens of millions of shares. Volume ratio 0.06 = 94% of orders not filling.
- Paper mark-to-market declines 5% per day compound, reaching −88.6% by day 40.
- Realised loss is not the same as paper loss. The position holder cannot exit, so "drawdown" as Session 2 defined it measures the price trajectory but not the exit-adjusted trajectory.
- Measured max drawdown from `compute_drawdown`: −88.6%. True economic loss to a trapped holder: potentially worse, because the terminal exit price at delisting is typically below the last traded price and because 40 days of locked position has time-cost in addition to mark-loss.

This made the abstract "measurement understates risk" tangible as a single dated event with named numbers. Student engagement visibly higher on this than on the frequency-table interpretation earlier in the session. **For Session 5 and later sessions:** when you can tether an abstract risk concept to a specific dated event with a specific stock and a specific magnitude, do it. The student has now built up a library of these anchor events (2024-02-05 margin spiral, 2024-09-24 stimulus, 2024-02-21 CSRC handover, 2024-05-06 ST长康 disclosure). They remember dates and mechanisms. They use them.

### Three strategic postures on ST-eligible stocks

Closed the case-study section by giving the student three defensible positions on whether to include ST-eligible stocks in their 小盘股 strategy universe:

1. **Exclude entirely.** Safe but loses 困境反转 upside and requires point-in-time ST data.
2. **Include with hard size caps.** Treats total loss as baseline assumption, sizes positions to survive it.
3. **Include with exit rules.** The ST长康 example shows the hard limit of this approach: by the first observable 跌停, no exit window exists. Paper exit rules need to survive the queue-existence test.

Did not push the student to pick. Named the three as live options with trade-offs. This is the kind of strategy decision that can only be made after backtesting in Phase 3-4; the job in Phase 1 is to make sure the student knows the options exist.

### Deliverable: the three-panel plot

Final artefact is a stacked three-panel figure saved to `data/ST_changkang_case.png`:

- Top: price path, 500-series stacked from 3.25 down to 0.37 through the red-shaded May-6-to-July-1 window, 跌停 close days marked as red dots.
- Middle: daily returns as bars, colour-coded (red for 跌停, gray otherwise), with a dashed reference at nominal −5%. The visual transition from gray heterogeneity to red uniform wall is the session's clearest image.
- Bottom: volume on log scale, same red/gray colouring. The two-orders-of-magnitude drop is the most visually decisive evidence of the liquidity trap.

The student observed the middle panel's transition immediately without prompting. I added one observation post-hoc: the price panel's decline is visibly concave because constant-percentage steps produce shrinking absolute steps as the base decreases. A log-scale price axis would render this as a straight line, making the "constant-exponential-decay" character of 连续跌停 geometrically explicit. Noted for future plots.

---

## How I taught this session and what worked

### The A/B/C framing as a rescue move

When the student signalled confusion on the measurement-bias direction, my first response was more verbal argument. It didn't land. The move that worked was collapsing the three distinct comparisons into a three-row table they could read side by side. Their strength is reading tables, not parsing nested verbal claims. **Rule for Session 5:** when abstract reasoning hits friction, immediately reach for a tabular or scenario-based presentation. Don't try to repair a failed verbal explanation with a more elaborate verbal explanation.

### Admitting code errors openly

Three separate code failures this session: the first `override_limit` patch was ambiguous about where the function body ended (student pasted literally, function returned None); my first smoke-test block asserted `returns.min() < -0.055` on synthetic data that didn't produce that; my original return-based detection approach was fundamentally flawed at low prices. I owned all three explicitly.

The third was the most important because the student had followed the intended reasoning correctly and the tool itself was the problem. Framing this as "the session's own content biting our code" rather than "I made a mistake, sorry" turned the debugging into teaching. **For Session 5:** when a bug is teaching material, treat it as teaching material openly. Don't apologise through the lesson; teach the lesson.

### Diff-style patch instructions

The v1 patch failure was instructive. I wrote `def detect_limit_hits(...): """..."""; limit = ...; # rest unchanged`. The student pasted it literally. The function lost its body.

**Rule going forward:** for any function under ~30 lines, paste the whole function when showing a patch. Targeted diffs are fine for longer functions, but the instruction needs to name the exact old lines being replaced, not gesture at "rest unchanged". Saved tokens are not worth paste-replace ambiguity.

### Smoke tests need the expected values hand-computed

The second smoke-test failure was that I wrote an assertion about my own synthetic test data without verifying the data would satisfy the assertion. **Rule going forward:** when writing smoke tests during active debugging, manually walk through the test inputs and compute the expected outputs BEFORE writing the assertions. If the expected output is "some returns below −5.5%", verify by hand that the chosen input prices produce such a return.

### Prediction used sparingly and to good effect

Used two predictions this session, both at moments where reasoning from current knowledge was sufficient (no data lookup required). First: which stock the student expects to have highest limit frequency and why. Second: which group (±10% boards vs ±20% boards) expects higher average frequency. First one they engaged with and got an informative wrong answer (good mechanism, wrong application). Second one they skipped to the data.

This matches the Session 3 handoff's observation that prediction works when it's pure reasoning from priors and fails when it requires data lookup. Kept that discipline this session without incident.

### Definition before predictions

Applied the rule from Session 3's pedagogical correction cleanly this session. Wrote out all the current rules BEFORE asking about causal mechanisms, wrote out the A/B/C comparison framework BEFORE asking about direction. Student did not push back on this at any point, which suggests the rule is now functioning as intended.

---

## Concepts consolidated this session

Stated so Session 5 can probe without re-teaching.

**Current A-share 涨跌停 rules by board, with the mid-2025 ST rule change noted.** 主板 ±10%, 创业板/科创板 ±20%, 北交所 ±30%, 主板 ST was ±5% until mid-2025 and ±10% after. 新股 5-day unlimited exception (1-day for 北交所).

**Three intraday scenarios at the limit: 封死, 开板, 一字板.** Trading does not stop at the limit; price is pinned while orders continue to queue. Sealed-limit days can have LOW volume, not high.

**The A/B/C measurement framing.** Sample A (no events) has the thinnest measured distribution. Sample B (measured, capped) has a wider one than A but a narrower one than C (true, uncapped). Cap bias pulls std, absolute skew, and kurtosis toward normal. The comparison that matters for risk is B vs C, not B vs A.

**First-day limit frequency is driven by news intensity, not liquidity.** Size and liquidity matter for the DURATION of limit events once triggered, not their first-day frequency.

**Price-based limit detection, not return-based.** Reconstruct 跌停价 as `round_half_away(prev_close × 0.95, 2)` and compare closes at price level. Return-based detection with tolerance ±0.002 fails at low prices where fen-rounding produces wider return deviations.

**The liquidity trap in data, concretely: ST长康 had a volume ratio of 0.06 on 跌停 days**. 94% of orders did not fill. Over 40 consecutive trading days.

**Measured max drawdown understates realised loss when exit is not available**. Drawdown from `compute_drawdown` is a mark-to-market trajectory, not an exit-adjusted one. For regimes where the cap plus queue prevents exit, the two diverge.

**When classification errors correlate with the measured quantity, group comparisons are compressed**. The initial buggy detection made the normal-day volume average artificially low, which made the 跌停-to-normal ratio look twice as forgiving as reality.

---

## Predictions made and how they landed

- **Which stock has highest limit frequency, and why.** Student predicted smallest caps, mechanism: low liquidity → cap retained longer. **Wrong on direction.** The largest stocks in the sample (寒武纪, 中金公司) topped the table due to news intensity. Good mechanism, applied to the wrong question. Size and liquidity drive DURATION, not frequency.

- **Expected 跌停 count for ST长康 under v1 utility.** I predicted "high 30s to low 40s with longest run 25-35". **Came in at 21 total with longest run 6.** This mismatch is what triggered the rounding-bug investigation. My ballpark was calibrated to what the rule should produce, not what our buggy code would produce. Useful only as a reference point.

- **Expected 跌停 count under v2 utility.** "~60 跌停 days, longest run in the 30-40 range." **Actual: 40 total in a single unbroken run.** The 60-days prediction overshot because I assumed some pre-May-6 April limit days plus post-July-1 final-day limits. Neither happened, the 40-day run accounts for all 跌停s in the window. Prediction directionally right but quantitatively loose.

- **Which group (±10% vs ±20% boards) has higher average limit frequency.** Not predicted, student skipped.

---

## Codebase state

```
project2/
├── utils.py                    # named utils.py, NOT project2_utils.py
│   ├── (prior functions unchanged)
│   ├── _get_board_limit        # new, prefix-based board inference
│   ├── _round_half_away        # new, A-share fen rounding helper
│   ├── detect_limit_hits       # new v2, price-based detection with override_limit
│   └── _smoke_test_limit_detection  # new, includes low-price crisis check
├── execute_smoke_tests()       # aggregator, calls all sub-tests
├── plot_setup.py               # unchanged
├── data/
│   ├── prices/                 # 10 stock CSVs + 4 index CSVs, unchanged
│   └── ST_changkang_case.png   # new, 3-panel case-study figure
├── Session_One.ipynb
├── Session_Two.ipynb
├── Session_Three.ipynb
└── Session_Four.ipynb          # this session
```

**Utility signatures for Session 5 reference:**

```python
_get_board_limit(code)
    # Returns 0.10 / 0.20 / 0.30 based on baostock-format prefix.
    # Does NOT handle ST (name-level data needed).

_round_half_away(x, decimals=2)
    # A-share price rounding convention. Vectorises over pandas Series.

detect_limit_hits(df, code, override_limit=None, price_tolerance=0.005)
    # Price-based detection. Returns DataFrame with daily_return,
    # board_limit, limit_up_price, limit_down_price, limit_up, limit_down,
    # any_limit. First row forced to non-limit.
```

---

## Open items carried forward

**25-stock basket rebuild.** Now four sessions of debt. Session 5 first order of business. The student has been accumulating evidence across every metric (std, drawdown, Sharpe, Sortino, limit frequency) that 5-stock baskets are unusable for any basket-level inference. Do not let this slip again.

**`build_ratio_table` → `risk_report` promotion.** Session 5 second task. Should integrate: total and annualised return, annualised std, Sharpe, Sortino, max drawdown, drawdown duration, limit-hit count and fraction (now that the utility works), sample-size caveat.

**Date-aware ST regime handling.** The `override_limit` parameter is the v1.5 workaround. A proper v2 would take a DataFrame of ST status by date per stock and apply the correct limit per row. Requires point-in-time ST data we do not have. Defer to Project 3 with point-in-time-everything.

**The 4.6x up/down limit-hit asymmetry.** Flagged but not investigated. Three candidate mechanisms on the table (asymmetric event distribution, asymmetric trader behaviour, survivorship). Not urgent, but worth a dedicated look at some point, probably when you have the 25-stock expanded baskets and a longer sample window.

**Point-in-time index membership.** Still deferred to Project 3.

**Geometric vs arithmetic annualisation.** Still not standardised. Flagged for the Session 5 risk_report docstring.

**Log-scale price panel for 连续跌停 plots.** Not urgent, but for any future plot of a 连续跌停 episode, a log-scale price axis renders the constant-percentage decay as a straight line, which is geometrically the cleanest visualisation. File for the plot style guide.

---

## Bridge to Session 5

Session 5 is the integration session. Two main tasks.

**Task 1: rebuild baskets.** Sample 25-30 stocks each from current 沪深300 and 中证1000 constituent lists via AKShare (`stock_zh_index_spot_sina` or equivalent). Same seed the student used before (42, per their Session 1-3 work) for reproducibility. Pull 前复权 daily data for the full Project 2 window (2023-04-01 to 2026-04-01, or whatever the student's actual window is, verify). Cache the price CSVs. Build equal-weighted daily return series for each basket.

**Task 2: risk_report promotion.** Take `build_ratio_table` (skeleton from Session 3, defined in a notebook cell, not yet in utils) and extend into a full `risk_report(returns_series, label, limits_series=None)` function. Should compute and return everything Project 2 has built: return stats, vol stats, risk-adjusted stats, drawdown stats, optionally limit stats when a limits_series is provided. Add to utils, smoke-test, promote.

Then run risk_report across: 10 individual stocks, 4 indices, 2 expanded baskets. Compare basket-level results to Session 3's 5-stock versions. The gap between 5-stock and 25-stock should be substantial on several metrics (kurtosis, max drawdown, Sharpe) given the composition-dominance pattern Sessions 1-3 documented.

Session 5 will close Project 2. After Session 5, Project 2 closeout document (same format as Project 1 closeout), then Project 3 kickoff.

---

## One pedagogical observation

The student's mode this session was: accept refresher information efficiently, engage with mechanism-based predictions, push back crisply when something was unclear (the measurement-bias direction), and execute diagnostic code without friction when the hypothesis was well-framed. Their diagnostic-execution step on the rounding bug was particularly clean. I proposed the hypothesis ("low-price rounding is breaking tolerance-based detection"), wrote a diagnostic cell that would produce a clear yes/no answer, handed it over. They ran it and pasted 39/39. No intermediate discussion needed, the hypothesis was either right or wrong and the cell settled it.

This is the mode I want to encourage. When I frame a question such that the data can answer it crisply, the student is very fast. When I frame a question that requires them to integrate multiple abstract claims, they slow down and (reasonably) ask for a cleaner framing. Session 5 should lean on the crisp-hypothesis mode for the comparison work (5-stock vs 25-stock basket differences). Run the comparison, let the magnitudes speak, interpret together.

---

Suggested conversation name for the next session: `2026-04-XX — Project 2 Session 5: 25-Stock Basket Rebuild and risk_report Integration`.

Closed by Claude at the end of Session 4. Good luck.
