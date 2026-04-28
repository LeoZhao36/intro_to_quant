# Project 1, Session 1 Handoff: Simple vs Log Returns

**Completed:** 2026-04-17
**Project location:** Phase 1, Project 1 (Return Distributions), Session 1 of 5
**Topic:** Computing simple and log returns, observing their behavior on 平安银行 2024 data

---

## What I finished

Reused `get_stock_data()` function from Project 0 to pull 平安银行 (sz.000001) daily OHLCV data for 2024, 前复权 adjusted.

Computed daily simple returns two ways. Manual Python loop (for understanding) and vectorized `df['close'].pct_change()` (for production use). Verified both methods produce identical results via max absolute difference check.

Computed daily log returns using `np.log(close / close.shift(1))`.

Produced the difference plot (simple minus log) across 2024. Confirmed the difference is near zero on quiet days and spikes on big-move days, consistent with the r²/2 approximation.

Identified and analyzed the largest move day. 2024-02-21, simple return +0.0998 (a 涨停 limit-up), log return 0.0951, difference 0.0047. Context: market rally following CSRC leadership change (易会满 → 吴清) on February 7, 2024.

Plotted full-year simple returns as a time series. Identified two major event clusters: February limit-up (leadership change rally) and late September to early October crash pair (September 24 PBOC stimulus rally, then October 8 NDRC disappointment).

## Files now in the project

- `Session_One.ipynb`: working notebook with `get_stock_data()` and return computations.
- `utils.py` (from Project 0): reusable data-loading function.
- `/data/sz000001_with_returns.csv`: 平安银行 2024 daily data with `simple_return`, `log_return`, and `difference` columns appended. Load this at the start of Session 2 instead of re-downloading.

## Key conceptual ground gained

**Why we use returns instead of prices.** Prices are not directly comparable across stocks with different price levels, and prices have trends (non-stationary) that break most statistical methods. Returns normalize across stocks and are close to stationary over reasonable time periods.

**Simple vs log returns, the core distinction.** Simple returns compound multiplicatively across time (must multiply to combine). Log returns translate this multiplicative structure into additive form (can sum to combine). They describe the same event in different units. For small daily moves they are nearly identical. On limit days (±10% or ±20%) they diverge meaningfully, with the gap growing as roughly r²/2.

**Why log returns matter for financial analysis.** Statistics is built on addition. Means, standard deviations, correlations, regressions all depend on combining numbers by adding them together meaningfully. Log returns deliver additivity across time. Simple returns do not. Rule of thumb: use log returns for single-asset time-series analysis, and use simple returns for portfolio construction across assets at a single time point.

**Three stylized facts about returns observed in my own data:**

1. Fat tails: occasional days much bigger than typical.
2. Volatility clustering: big-move days bunch together in time, visible in September and October 2024.
3. Negative skewness: largest negative moves slightly larger and more frequent than largest positive moves, though in 2024 平安银行 the magnitudes were close due to the 涨停 cap on the upside.

**A-share specific: 涨跌停 distortion.** The ±10% price limit truncates measured moves. A limit-up day reports +10% but the true demand pressure might have pushed the price higher. This means measured volatility UNDERSTATES true volatility for limit-hit stocks. Revisit this formally in Project 2, Session 4.

## Open items for next session or later

平安银行 is a large-cap bank, not a 小盘股. The log-vs-simple divergence was visible but modest. Worth re-running the analysis on a volatile 中证1000 stock to see if fat tails and clustering are more pronounced, which my thesis predicts. Could do this at the start of Session 2 as a warm-up.

The October 8, 2024 drop: did 平安银行 close at exactly −10% 跌停, or near it? Confirm using `df['simple_return'].idxmin()` and the exact value.

## State of my understanding

Solid on: what returns are, why finance uses them, the simple vs log distinction, how to compute both in pandas, why log returns enable statistical analysis.

Accepted but not derived: the deeper math of why logarithms specifically turn multiplication into addition (treated as a tool property). This is fine for now and does not block progress.

## Personal reflection

Statistics is about finding commonalities and trends. It is about adding up the smalls to get the big.

> 合抱之木，生于毫末；九层之台，起于累土。
>
> A tree that fills the arms grows from a tiny sprout; a nine-story terrace rises from a heap of earth.

## Ready for Session 2

Session 2 topic: descriptive statistics (mean, median, std, skewness, kurtosis).

Prerequisites met: returns computed and saved, understanding of why means and stds require additive data, real observations from my chart (fat tails, clustering, skewness) that the formal statistics will quantify.
