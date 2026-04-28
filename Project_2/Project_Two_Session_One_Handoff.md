# Project 2 Session 1 Handoff: Rolling Volatility, Basket Composition, and Index-Level Comparison

**Completed:** 2026-04-19
**Project location:** Phase 1 (revised numbering: this is Project 2 in the Phase 1 curriculum), Project 2 (Volatility and Risk), Session 1 of 5
**Status:** Closed. Ready for Session 2 (Drawdown).

---

## Starting point

I entered Session 1 having closed Project 1 (Return Distributions) with a full understanding of static descriptive statistics on return series, a working distinction between scale and shape, the bulk-versus-tails classification for deciding when normal-based tools are reliable, and the Project 1 helper functions in a collection of per-session notebooks. I had also flagged several items for forward work: promoting the Project 1 helpers into a reusable utils module, building a limit-hit detection utility, and revisiting the basket construction problem with better awareness of compositional noise.

On data: I had 50 cached stocks from the Project 1 Session 4 baskets plus 平安银行 2024 from earlier sessions. On concepts: I had not encountered rolling statistics, volatility clustering as a named phenomenon, or the distinction between static and time-varying vol estimates.

I started Session 1 by creating a fresh `project2/` folder with the conda environment carried over but no data or code from Project 1. The rebuild was deliberate: I wanted the practice of porting and syncing rather than inheriting silently-broken assumptions.

---

## Work completed

### Utilities port and extension

Built `project2_utils.py` with four helper functions carried over from Project 1 (`to_baostock_code`, `get_stock_data`, `load_or_fetch`, `setup_chinese_font`) plus one new one (`detect_limit_hits`, the utility that was deferred from Project 1 Session 3). Each function was improved rather than copied verbatim. `get_stock_data` now uses `try/finally` around the baostock login so dangling connections do not accumulate on errors. `to_baostock_code` now handles 北交所 codes (4xx and 8xx prefixes), which Project 1 did not cover. `setup_chinese_font` was rewritten to check matplotlib's actual font registry before setting, rather than relying on a silent-failure loop (see Bugs section below). Added a smoke test suite at the bottom of the file that runs on `python project2_utils.py` and verifies the utility functions on specific known-case inputs.

### Fresh data pull

Used AKShare's index constituent interface to sample 5 stocks from 沪深300 and 5 from 中证1000 using random seed 2026. Pulled three years of 前复权 daily OHLCV data (2023-04-17 to 2026-04-17) for each, cached as CSVs under `data/prices/`. Ten stocks total, 727 rows each, dates aligned across all ten (verified by set equality check on the date indexes).

Sample drawn:
- 沪深300: 国泰君安 (sh.601211), 中金公司 (sh.601995), 寒武纪 (sh.688256, 科创板 ±20% limit), 新希望 (sz.000876), 中天科技 (sh.600522, inclusion date 2025-12-15).
- 中证1000: 长亮科技 (sz.300348, 创业板), 京新药业 (sz.002020), 安徽合力 (sh.600761), 华曙高科 (sh.688433, 科创板), 承德露露 (sz.000848).

Four of the ten have the ±20% wider limit (寒武纪, 长亮科技, 华曙高科, and the main-board stocks on ±10%).

### Rolling volatility on a single stock

Computed 20-day rolling std of log returns on 寒武纪 as the first concrete rolling-vol example, selected because its extreme vol makes the regime structure visually obvious. The first non-NaN rolling vol value was 0.0687 on 2023-05-18, corresponding to an annualised 107% vol. This is extreme by any standard and reflects a window containing multiple ±7%-plus days including the April 20 科创板 +20% limit hit.

Plotted a three-panel figure (price, daily log returns, 20-day rolling std) with a secondary y-axis showing annualised units on the rolling std panel. The rolling vol line made three distinct regime events visible: the late-2023 choppy drawdown, the September-October 2024 PBOC stimulus rally through early 2025, and the September 2025 run-up from ~800 to ~1600. Each peak mapped to a specific news event.

### Window-length comparison

Computed and overlaid rolling vol at three window lengths (5, 20, 60 days) on 寒武纪. The visual confirmation of the smoothness-resolution tradeoff: 5-day line is the most jagged with highest peaks (peak 0.148 on a specific outlier day), 60-day line is smoothest and lowest (peak ~0.060 during the same stimulus event), 20-day sits between them. During calm regimes (May-July 2025) all three lines converged near 0.020-0.025. During transitions they diverged most. This agreement-in-stability, divergence-at-transitions pattern is a general property of rolling statistics, not specific to vol.

### Basket-level comparison

Built equal-weighted basket returns from the two 5-stock baskets using `pd.DataFrame(closes).pct_change().mean(axis=1)` (with log returns) and computed 20-day rolling std on each. Plotted both on shared axes. Summary: HS300 basket mean 0.0157 daily (24.38% annualised), ZZ1000 basket mean 0.0179 (27.82% annualised), basket ratio 1.14.

In calm stretches the ZZ1000 basket sat about 1.3-1.5x above the HS300 basket, consistent with my pre-session prediction. During the October 2024 stimulus spike the ratio was about 1.24, close to the calm-regime ratio. During the April-May 2025 spike the ratio was about 1.9. The October 2024 event shows convergence under market-wide stress; the April-May 2025 event shows divergence under what appears to be a sector or factor-specific shock. My prediction that vol converges during stress was therefore partly wrong: it depends on the structural shape of the stress, not on stress per se.

### Composition investigation

Two periods showed HS300 basket vol exceeding ZZ1000 basket vol, violating the size-vol ordering. Initially attributed to "large-cap size" reasoning but that cannot be right because if size alone caused the ordering there would be no exceptions. The real cause: 寒武纪 is in my HS300 basket and its September 2025 vol spike (single-stock daily std 0.058 in the August-October 2025 window, 4x the other four HS300 stocks at 0.013-0.029) dominated the 5-stock basket vol. Verified by computing per-stock std in the window.

Lesson: with 5 stocks per basket, any single stock is 20% of the weight, and a single outlier dominates basket-level statistics. Before reaching for economic mechanisms when a surprising result appears in a small sample, check composition first.

### Index-level cross-check ("just for fun")

At the end of the session, pulled four A-share indexes directly (上证50, 沪深300, 中证1000, 创业板指) as single price series rather than constituent baskets. Computed 20-day rolling vol on each.

Results (annualised mean vol):
- 上证50: 13.96%
- 沪深300: 15.15%
- 中证1000: 22.77%
- 创业板指: 26.16%

Size-vol ordering is clean and monotonic at the index level. 创业板指 sits highest despite overlapping with 中证1000 in average market cap because of sector concentration (tech/biotech/growth): less sector diversification means more co-movement within the index and sharper response to sector-specific news.

Compared to my 5-stock baskets: HS300 basket measured 24.38% annualised vs actual 沪深300 at 15.15% (ratio 1.61, inflated by 寒武纪). ZZ1000 basket measured 27.82% vs actual 中证1000 at 22.77% (ratio 1.22, closer to true). The basket-vs-index gap is compositional noise in numerical form, and it is large.

Also examined peak-to-baseline ratios during the October 2024 stimulus spike. All four indexes spiked roughly 4-6x from baseline. The absolute magnitude of the spike scales with baseline vol but the proportional response is similar, suggesting that market-wide shocks amplify everyone's vol by a similar factor and the differences across indexes come from what baseline is being multiplied.

---

## Concepts consolidated

### Rolling volatility, stated precisely

Rolling std computed on day `t` uses observations from day `t-window+1` to day `t`, assigning the result to day `t`. The first `window-1` values are NaN by construction. The result is a time series that localises the vol estimate in time, not a smoothed version of anything. Static std (one number over a whole period) is the smoothest possible answer, not the other way around. Rolling std reveals the time variation that static std hides.

Window length is a resolution tradeoff. Short windows give high temporal resolution at the cost of noise. Long windows give stability at the cost of blurring the timing of regime transitions. Neither is "more accurate." They answer different questions. 20 days is the industry default because it matches monthly reporting cycles, not for a mathematical reason.

When rolling vols at different window lengths agree, the regime is stable. When they disagree, the regime is transitioning. This is a general diagnostic for rolling statistics, not specific to vol.

### Volatility clustering mechanisms

Four structural causes, all operating simultaneously. Information arrives in clusters, not uniformly: a single big piece of news generates multi-day follow-on flow (revisions, ratings changes, detail releases, position adjustments) that itself causes more vol. Belief updating takes time: market participants disagree on what a shock means and converge gradually, and the gradual convergence plays out in trading. Risk-management mechanics amplify: vol-targeting systems de-leverage when measured vol spikes, the de-leveraging causes more price movement, which raises measured vol, which triggers more de-leveraging. Liquidity provision backs off under stress: market makers widen spreads or withdraw when vol rises, thinner liquidity means each incoming order moves price more, which itself raises realised vol.

Psychology ("emotions take time to digest") is real but small next to these four structural mechanisms. GARCH-family models have survived 40 years because the phenomenon is rooted in structural causes that cannot be arbitraged away.

### Rolling vol responses to shocks: mechanical plus genuine

When a shock happens on day `t`, two things compound to produce elevated rolling vol afterwards. First, the shock enters the rolling window immediately and stays there for `window` days, mechanically inflating std until it drops out. Second, volatility clustering means the days after a shock are genuinely more volatile, so additional extreme observations enter the window. The combined effect produces rolling vol spikes that persist beyond the initial shock and can extend further than the window length itself.

The "lag" framing from moving-average-of-price thinking does not transfer. Rolling std responds immediately on the day of the shock; what looks like lag is the persistence of an elevated reading for the window duration. Resolution is the better framing than lag.

### Composition sensitivity of small baskets

A 5-stock basket assigns 20% weight to each stock. Any single outlier at 20% weight dominates basket-level statistics. With 25 stocks each weight is 4%. With 50 stocks each is 2%. The threshold below which compositional noise dominates economic signal is somewhere around 20-25 stocks for most purposes.

The practical rule: when a surprising result appears in a small sample, check which individual stock is driving the variance before reaching for economic mechanisms. The technique is the same as the single-event audit from Project 1 (Session 4, stimulus-week experiment): identify which handful of observations is carrying the result. Here it is applied across stocks rather than across days.

### Stress events are not all the same shape

Different stress events have different structural shapes. Macro shocks (PBOC stimulus, rate decisions, broad policy) tend to hit all market caps with similar proportional amplification, so baskets converge. Sector-specific or factor-specific shocks affect one market segment more than others and cause baskets to diverge. "Do baskets converge during stress" is not a yes/no question; the answer depends on stress type. File this forward to regime analysis work.

### Index-level analysis versus constituent-basket analysis

The actual index price series (`sh.000300`, `sh.000852`, etc.) gives the cleanest answer to "what is the real vol of this index" because no compositional noise or survivorship bias is introduced by my sampling. Constituent baskets are useful when I need to look at individual-stock contributions, factor exposures, or any question requiring per-stock data. For pure vol or return comparisons at the index level, pull the index itself. Free of sampling noise, free of inclusion bias (the index reweights in real time), roughly one download per index.

---

## Bugs found and fixed

### `setup_chinese_font` silent failure on Windows

The original version tried to set `rcParams["font.sans-serif"]` inside a try/except loop, expecting a raise if the font was unavailable. Matplotlib does not raise when you set a nonexistent font; it silently falls through to the default and fails at render time with warnings. So the loop always succeeded on the first entry ("Heiti SC", a Mac font), never tried the Windows fallbacks, and Chinese characters rendered as boxes.

Fix: check `fm.fontManager.ttflist` (matplotlib's actual registry of installed fonts) before setting, and iterate the candidate list by membership rather than by exception. Added Linux fonts to the candidate list for completeness.

Lesson: Python's loose type system lets functions accept inputs they cannot process and produce no errors. Relying on exceptions-as-validation is fragile; explicit checks are not.

### `detect_limit_hits` silent failure on log-return input

The original version compared the input directly against thresholds like `0.10 - tolerance`, treating the input as simple returns. When I passed log returns, a +20% price move showed up as ln(1.20) = 0.1823 rather than 0.20, which is below 0.198 threshold, so the function failed to flag genuine 20% limit-up days. Specifically, 寒武纪's April 20, 2023 limit-up was returned as `limit_up=False`.

Discovery: tested the function against a known-case limit-up day (April 20, 2023) before using it downstream. This is the testing habit I want to build: any function that flags, filters, or transforms data should be tested against a specific input where the correct output is known.

Fix: added an explicit `return_type` parameter ("log" or "simple", defaulting to "log" to match my pipeline), converted log returns to simple returns internally before thresholding. Also added 北交所 case (±30% limit) for completeness.

Lesson: any function operating on "returns" should declare which scale it expects. The two scales diverge precisely at the large moves where the function's output matters most, so a silent scale mismatch produces wrong answers exactly where correctness matters.

### The broader pattern

Both bugs failed silently. Neither would have been caught by running the function on typical data; both required testing against edge cases. Added a `_smoke_test` function at the bottom of `project2_utils.py` that runs on `python project2_utils.py`. Re-run after any utility change.

---

## Codebase state

```
project2/
├── project2_utils.py          # ported helpers + detect_limit_hits + smoke tests
├── plot_setup.py              # separate file for plot styling (my preference)
├── data/
│   └── prices/                # 10 stock CSVs + 4 index CSVs
└── Session_One.ipynb          # this session's notebook
```

Functions in `project2_utils.py`:
- `to_baostock_code(six_digit)` — format conversion, handles SH/SZ/BJ
- `get_stock_data(code, start, end, adjust='qfq')` — baostock pull with proper cleanup
- `load_or_fetch(code, start, end, cache_dir, adjust)` — caching wrapper
- `detect_limit_hits(returns, codes, tolerance=0.002, return_type='log')` — limit-hit detector
- `setup_chinese_font()` — matplotlib Chinese font setup with Windows/Mac/Linux fallbacks
- `_smoke_test()` — runs all functions against known cases

Functions to build in Session 2 and lift to the utils file:
- `compute_drawdown(returns)` — equity curve, running max, drawdown series
- `compute_max_drawdown(returns)` — scalar max drawdown plus start/end/duration
- `compute_sharpe(returns, rf_daily=0)` — annualised Sharpe
- `compute_sortino(returns, rf_daily=0)` — downside-deviation Sortino
- `risk_report(returns)` — summary dict of all the above

---

## Predictions tested this session

Entry prediction 1: "20-day rolling std would be smoother than static std." Wrong direction. Static is smoothest (one number). Rolling is less smooth, not more. The tradeoff I was reaching for (smooth vs noisy) lives inside the choice of window length, not between static and rolling.

Entry prediction 2: "Volatility clustering comes from psychology / emotions taking time to digest." On the right track but named the weakest mechanism and missed the three stronger structural ones (information clustering, risk-management mechanics, liquidity withdrawal). Psychology exists but sits under the structural causes.

Entry prediction 3: "Small-cap basket rolling vol is higher because the 20-day window captures day-to-day changes that a longer window doesn't." Right conclusion (small-caps are more volatile) but wrong mechanism (window length does not change which asset is more volatile; it changes how responsive the measurement is).

Mid-session prediction: "Baskets converge during stress." Partly wrong. October 2024 stimulus: they converged. April-May 2025: they diverged. Stress-event shape matters, not just presence of stress.

Index-ordering prediction: 上证50 < 沪深300 < 中证1000 < 创业板指 annualised vol, based on size effect plus sector concentration reasoning for 创业板指. Correct. Actual numbers: 13.96%, 15.15%, 22.77%, 26.16%.

---

## Open items carried forward

**Compositional noise in basket construction.** The 5-stock baskets are below the robustness threshold. For Session 4 (the reusable risk toolkit deliverable) I should rebuild baskets at 25-30 stocks each to match Project 1 Session 4's size and avoid compositional noise dominating the results. The 10-stock sample is fine for Sessions 1-3 where I'm building understanding; it is not fine for the deliverable.

**寒武纪 as HS300 outlier.** Single stock driving 20% of HS300 basket vol. For continuity, keep 寒武纪 in the sample through Sessions 2-3 but note any HS300 basket result is inflated. For the Session 4 deliverable, either re-sample at 25 stocks (which will dilute 寒武纪's effect to 4%) or explicitly remove it and document the choice.

**Function library promotion from Project 1.** I still have not lifted the Project 1 helpers into a clean `project1_utils.py`. Arguably this is now obsolete because `project2_utils.py` is the successor and contains improved versions of the same functions. Decision: retire the Project 1 utilities and treat `project2_utils.py` as the live version going forward, since the improvements are non-trivial (try/finally, Windows font support, numeric coercion with errors='coerce').

**Point-in-time index membership.** Still deferred to Project 3. Session 1's exercise used today's constituent list pulled back three years, which contains inclusion bias. For vol analysis the bias is small (volatility is not systematically related to recent inclusion); for return analysis it is large. Not urgent now, critical by Project 3.

**北交所 coverage.** Did not include 北证50 (`bj.899050`) in the index comparison because baostock coverage is known to be spotty. Worth checking in Session 2 or later whether AKShare's `stock_zh_index_daily_em` has cleaner 北交所 data.

**Smoke test discipline.** Added `_smoke_test()` to `project2_utils.py` with four assertions covering `to_baostock_code` and `detect_limit_hits`. When I add drawdown and Sharpe functions in Session 2, extend the smoke test to cover them as well. The discipline is: no new utility function without a known-case test attached.

---

## Bridge to Session 2

Session 2 is drawdown. The prep work is already done: the 10-stock dataset is cached, the basket construction is working, the rolling-window pattern is in hand. Drawdown uses the same infrastructure with a new computation on top.

Conceptual bridge: drawdown is the first tail-dominated metric in the curriculum per the Project 1 closeout classification. Std is bulk-dominated (dominated by the middle of the distribution). Drawdown is defined by the worst path the equity curve actually took, which is dominated by a small number of extreme stretches. Everything I learned in Project 1 about why tail-dominated quantities are fragile (measurement-vs-reality bias under clipping, survivorship and inclusion biases, the dependence of multi-year statistics on a handful of extreme observations) applies directly.

Practical bridge: the 寒武纪 composition issue is likely to show up even more starkly in drawdown. 寒武纪 had a large drawdown in 2025 (roughly 1600 to 1000+, around 35-40% peak-to-trough from visual inspection). In a 5-stock basket this will dominate the basket drawdown. Good opportunity to reinforce the composition-check habit in a new context.

The Session 2 deliverables are drawdown curves for the 10 stocks and both baskets, identification of the worst drawdown periods, and duration analysis (how long from peak to trough to recovery). Session 2 naturally leads into Session 3 (Sharpe and Sortino) because the same equity curve infrastructure supports both.

---

## Personal reflection

*[to be filled in after letting this sit for a day]*

---

Session 1 of Project 2 is closed. Suggested conversation name for next session: `2026-04-XX — Project 2 Session 2: Drawdown, Duration, and the Composition Trap Revisited`.
