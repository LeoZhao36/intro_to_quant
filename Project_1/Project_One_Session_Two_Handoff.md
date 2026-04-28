# Project 1, Session 2 Handoff: Descriptive Statistics & Distribution Shape

**Completed:** 2026-04-17
**Project location:** Phase 1, Project 1 (Return Distributions), Session 2 of 5
**Topic:** Mean, median, std, skewness, kurtosis. Scale vs shape. Sample design and outlier sensitivity.

---

## What I finished

Reloaded 平安银行 (sz.000001) 2024 data with 前复权 adjustment into the new Project 1 data folder. Recomputed simple and log returns. Saved to `data/sz000001_with_returns.csv`.

Computed the full set of descriptive statistics on 平安银行 2024 returns. Mean 0.0015, median 0.0, std 0.0165, skewness 0.858, excess kurtosis 10.67. Interpreted mean > median as a signal of positive skew, which refined my Session 1 tentative observation of negative skew. The 2024 sample is dominated by a few extreme upside days, not downside ones.

Verified the cumulative 2024 return of 39.09% by comparing 前复权 and 不复权 data for the same stock. Confirmed the gap is driven by dividend effects being retroactively baked into forward-adjusted prices. Raw price appreciation was ~28%, dividends contributed another ~10%, and compounding gives ~39% total.

Ran an outlier sensitivity test. Removed the 5 most extreme days from 平安银行 2024 and re-computed all stats. Kurtosis collapsed by 91% (10.67 to 0.98), mean fell 53%, std 25%, skew 42%. The pattern matches the power-weighting in each formula: higher-power statistics are more fragile to extreme observations.

Built a 6-stock comparison table, 3 大盘 vs 3 小盘. The first attempt mislabeled mid-caps (光明乳业, 三峡水利, 拓邦股份, all 100-200亿 RMB) as 小盘股 and produced a counterintuitive result where "small" looked calmer than "large". Diagnosed the issue by verifying market caps externally, not by defending the result.

Second attempt with truly small caps (浙江震元, 华升股份, 通业科技, all in the 20-50亿 range). Std gap flipped correctly (小盘 2.4× higher than 大盘, as expected). But kurtosis gap went the "wrong" way (小盘 lower). Initially counterintuitive, resolved once I understood that kurtosis measures shape, not scale.

Built a 2×2 histogram plot comparing 平安银行 and 华升股份 in raw units (top row) and z-scored units (bottom row). The visualization makes the scale-vs-shape distinction concrete. 平安银行 has a peaky center with fat tails. 华升股份 has a broad base with no fat tails. Both describe real risk, just different risk.

Fixed matplotlib Chinese font rendering for good by creating `plot_setup.py`. Automatic platform detection, falls back gracefully, set once per notebook.

## Files now in the project

- `Session_Two.ipynb`: working notebook with all descriptive statistics work, the outlier sensitivity experiment, the 6-stock comparison table, and the z-scored histogram comparison.
- `data/sz000001_with_returns.csv`: 平安银行 2024 daily data with simple_return, log_return, and difference columns, freshly saved inside the Project 1 folder.
- `plot_setup.py`: reusable Chinese font configuration module. Call `setup_chinese_font()` once per notebook.
- `utils.py`: `get_stock_data()` from Project 0, unchanged, still working.

## Key conceptual ground gained

**The four descriptive statistics as power-weighted summaries.** Mean weights observations by magnitude¹. Standard deviation weights by magnitude² (via variance). Skewness by magnitude³. Kurtosis by magnitude⁴. Higher powers make the statistic more sensitive to extreme observations. This is not a quirk but a mathematical certainty, and the trimming experiment made it visible: kurtosis collapsed 91% when 2% of the days were removed, because the removed days were 4th-powered in the formula.

**Why mean vs median diverges.** Median is the middle-ranked observation, insensitive to magnitude. Mean is an average, sensitive to magnitude. The two differ when the distribution is asymmetric. Mean > median means positive skew (a few large positive outliers pull the average up). This is mechanically true regardless of the stock's liquidity or reputation.

**Why variance uses squaring.** To summarize spread you need to turn signed deviations into positive quantities. Absolute value works in principle but breaks calculus and the additivity-under-independence property that underlies every limit theorem. Squaring gives cleaner math and amplifies extremes proportionally. A 5% deviation contributes 25 times more than a 1% deviation, not 5 times more. Standard deviation is variance returned to return units via square root, purely for human readability.

**前复权 vs 不复权 and what cumulative return really means.** 前复权 bakes past dividend payments into historical prices, retroactively subtracting dividends from pre-dividend prices. A 前复权 cumulative return therefore includes both price appreciation AND dividend yield. 平安银行's 39% in 2024 was roughly 28% price appreciation plus ~10% dividends, compounded. Use 前复权 for statistical work. Use 不复权 when matching actual trading prices on specific dates.

**Scale vs shape: the single most important distinction of this session.** Standard deviation measures scale (how wide is the distribution). Kurtosis measures shape (how does the tail compare to the body, normalized by that same scale). These are independent properties. A stock with std = 0.042 (华升股份) can have kurtosis 0.6, meaning all days look similar, the distribution is just spread wide. A stock with std = 0.016 (平安银行) can have kurtosis 10.7, meaning most days are tiny but rare days are enormous in relative terms. Both types of distribution exist and each requires different risk management. Chronically volatile stocks price risk into std; rare-event stocks hide risk in the tails.

**Sample design matters more than analytics.** The first 小盘股 comparison failed because my small-cap picks were actually 100-200亿 mid-caps. The mechanisms I wanted to test (retail dominance, thin liquidity, slow information diffusion) only activate below ~50亿 market cap. Fixing the sample produced the expected std result. The investigation that surfaced the sampling error was more valuable than the corrected result itself. A number from a wrong sample is worse than no number, because it feels like evidence.

**Outlier sensitivity as a research reflex.** Whenever I see a good-looking statistic, ask "which days drove this?" Run a trim test. If 2% of the days explain 60% of a statistic, that statistic is fragile and cannot be extrapolated. This reflex generalizes to every backtest, Sharpe ratio, and factor IC I will encounter.

**A-share specific.** 平安银行's high kurtosis in 2024 was driven by roughly 5 specific days, most visibly the February 21 CSRC leadership rally (+9.98%, hitting 涨停) and the September-October stimulus cluster. These were policy shocks, not market-wide crashes. Policy-driven kurtosis is characteristic of Chinese large-caps where regulatory reversals are the dominant tail risk, distinct from the earnings-miss or crisis-driven kurtosis typical of US large-caps.

## Open items for next session or later

Session 3 will build QQ-plots, which show tail deviation from normality more precisely than histograms. My histograms already show the fat-tail phenomenon qualitatively but not with any ordering against theoretical tails.

The proper Project 1 deliverable (Session 4) calls for 20-30 stocks per basket, not 3. My current 3-per-group comparison is illustrative, not defensible as a population-level finding. The kurtosis direction in particular is sensitive to individual stock selection. A proper basket is the next real milestone.

Formal normality tests (Shapiro-Wilk, Jarque-Bera) deferred to Project 3 where they will appear in the proper hypothesis testing context. No information loss. Visual evidence from the histogram and the kurtosis of 10.7 are already inconsistent with normality.

Could run the same 6-stock comparison on 2022 or 2023 to see whether the scale-vs-shape pattern is stable across years or specific to 2024 policy conditions. Worth doing before drawing broader conclusions.

## State of my understanding

Solid on: the four descriptive statistics, their power-based weighting and consequent fragility to outliers, the scale-vs-shape distinction, z-score normalization as a tool for cross-stock shape comparison, 前复权 mechanics, the importance of sample design, the "which days drove this?" reflex.

Accepted but not yet formalized: exactly why higher-power moments mathematically weight extremes more. I understand this intuitively via the 1⁴ vs 5⁴ = 625 example but have not derived the general statement. Acceptable for now, will be formalized in Project 3.

Still ahead: QQ-plots, formal hypothesis testing, bootstrap methods, proper 20-30 stock comparison baskets, normality testing in its natural context.

## Personal reflection

*[to be filled in by me]*

## Ready for Session 3

**Session 3 topic:** visualizing distributions properly (histograms with normal overlays, KDE plots, QQ-plots, side-by-side 小盘 vs 大盘 comparison with a cleaner visual).

**Prerequisites met:** returns computed and saved, descriptive statistics understood, z-scoring built and used, matplotlib Chinese font fixed permanently. The histograms built at the end of this session will be formalized and extended with normal overlays and proper tail diagnostics.
