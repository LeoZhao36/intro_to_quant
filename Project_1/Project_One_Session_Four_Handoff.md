# Project 1, Session 4 Handoff: Basket-Level Distribution Comparison

**Completed:** 2026-04-18
**Project location:** Phase 1, Project 1 (Return Distributions), Session 4 of 5
**Topic:** Scaling from single-stock to basket-level analysis. Equal-weighted return series for 沪深300 vs 中证1000 constituent samples. First encounter with inclusion/survivorship bias in practice, with the averaging effect on higher moments, and with how a single policy event can dominate three-year statistics.

---

## What I finished

Started `Session_Four.ipynb` as a fresh notebook with a self-contained setup cell. Pulled constituent lists for 沪深300 and 中证1000 via AKShare (baostock does not have 中证1000 — only 上证50, 沪深300, and 中证500, verified from baostock's own API documentation page). Sampled 25 stocks from each index with a fixed random seed (42) for reproducibility. Saved the samples to CSV so reruns produce identical universes.

Pulled daily 前复权 price data for all 50 stocks across 2022-01-01 to 2024-12-31 using the existing `get_stock_data()` utility, wrapped in a `load_or_fetch()` caching layer so baostock is only hit once per stock. All 50 stocks returned data successfully. Date ranges aligned cleanly (2022-01-04 to 2024-12-31 for full-history stocks, 726 trading days).

Ran a completeness check on row counts. The 沪深300 side was clean — all 25 stocks had the full sample. The 中证1000 side flagged 7 stocks with short histories (row counts between 333 and 619 instead of 726). Diagnosed as late listings rather than suspensions: all 7 were 301xxx (创业板 registration tier) or 688xxx (科创板) codes that IPO'd partway through 2022-2024. This was my first concrete encounter with inclusion bias: stocks qualify for today's 中证1000 partly because of strong post-IPO performance during my sample window.

Applied a `filter_full_history()` cut at 2022-01-15 to enforce constant-composition baskets. Dropped 7 stocks from 中证1000 (all 301xxx/688xxx), zero from 沪深300. Final baskets: 25 large-caps, 17 small-caps. Documented that this filter reduces upward bias from IPO pops but skews the small-cap basket toward older, more established names — a different bias in a different direction.

Built `build_returns_matrix()` to convert the dict-of-DataFrames into a wide panel (dates × stocks) using `pd.DataFrame(close_series).pct_change()`. Internalized that pandas aligns on the date index and fills NaN where a stock did not trade, which is the honest representation of a suspension day. Computed equal-weighted basket returns via `.mean(axis=1)`, which skips NaN per-row by default.

Computed descriptive statistics for both baskets in the full sample. Numbers:
- 沪深300 basket: ann. std 17.86%, skew +1.07, excess kurt 9.92
- 中证1000 basket: ann. std 24.77%, skew +0.05, excess kurt 6.19
- Both baskets' min on 2024-10-09, both max on 2024-09-30

The coincidence of extreme dates pointed to a single dominant event: the September 24, 2024 PBOC/CSRC stimulus package. Sept 30 saw 沪深300 +9.5% and 中证1000 +10.7%, the biggest one-day rallies in years. The Oct 8-9 reversal after Golden Week produced the mins.

Re-ran the descriptive stats excluding the Sept 24 – Oct 10 window (8 trading days, 1.1% of the sample). Results:
- 沪深300 ex-stimulus: ann. std 15.70%, skew +0.02, kurt 2.31
- 中证1000 ex-stimulus: ann. std 22.49%, skew −0.28, kurt 1.73

Eight days moved 沪深300 kurtosis from 2.31 to 9.92 and its skewness from +0.02 to +1.07. This was the headline methodological lesson of the session.

Produced histograms with matched-parameter normal overlays and side-by-side QQ-plots for both baskets. The peak-too-tall / shoulders-too-thin / tails-too-fat pattern from Session 3 was visible at basket level but milder, consistent with the averaging effect compressing kurtosis. The QQ-plots showed 沪深300's upper tail curving away from the reference line more dramatically than 中证1000's, which is the visual signature of why large-cap measured kurtosis came out higher.

Ran a limit-hit diagnostic across individual stocks in the return matrices. 沪深300: 85 main-board hits (±9.95%), 25 wider-band hits (±15%). 中证1000: 170 main-board hits, 22 wider-band hits. The 22 wider-band hits came from 4 stocks in my 中证1000 sample with 创业板/科创板 codes (sz.300573, sh.688300, sz.301018, sz.301015) that IPO'd before the 2022-01-15 cutoff and therefore survived the filter. This corrected Claude's earlier claim that the filter had dropped all 创业板/科创板 stocks — some older ones are in.

Reconciled the apparent contradiction between 192 individual-stock limit-hit days and only 2 basket-level ±10% days. This was the averaging effect made concrete: a single +18% stock in a 17-stock basket contributes ~1.06% to the basket, a perfectly ordinary daily move. Individual-stock tails almost entirely vanish at basket level unless many stocks move together.

## Files now in the project

- `Session_Four.ipynb`: the full working notebook, confirmed to run top-to-bottom in a clean kernel.
- `data/hs300_sample_codes.csv`, `data/zz1000_sample_codes.csv`: the sampled constituent lists, fixed by seed=42.
- `data/prices/`: 50 cached CSVs, one per stock, for 2022-01-01 to 2024-12-31.
- `utils.py`, `plot_setup.py`: unchanged from Session 2-3.
- Session 1-3 notebooks and their cached CSVs still in place.

## Prediction vs reality

Four explicit predictions going in:

1. **Higher std for 中证1000**: HIT. Predicted range 20-28%, got 24.77%. Predicted 15-20% for 沪深300, got 17.86%. Both landed inside the predicted ranges.
2. **Higher kurtosis for 中证1000**: MISS, opposite direction. Predicted 3-8 vs 2-5 for 沪深300. Got 6.19 vs 9.92 full sample, 1.73 vs 2.31 ex-stimulus. Large-cap basket is more fat-tailed on both samples.
3. **More negative skew for 中证1000**: HIT for ex-stimulus (−0.28 vs +0.02), MISS for full sample (+0.05 vs +1.07, both positive because of the Sept 30 upside outlier).
4. **Tight co-movement in extreme dates**: HIT. Both baskets hit their min/max on identical calendar dates, indicating the two baskets are not statistically independent.

The kurtosis failure was the most instructive outcome. Three mechanisms pull against the naive "small-caps have fatter tails" story at the basket level:
- The stimulus day was *relatively* more anomalous for the lower-vol 沪深300 basket (the +9.5% move was ~8 sigmas for 沪深300 but only ~7 sigmas for 中证1000; kurtosis measures extremeness in sigma-units, not raw percent).
- 涨跌停 clipping compresses measured individual small-cap tails before averaging.
- Idiosyncratic small-cap jumps diluted more under averaging than did the common-factor moves that drive large-cap extremes, because small-caps co-move less tightly on big days than large-caps do.

## Key conceptual ground gained

**The averaging effect dilutes tail extremity dramatically.** 192 individual stock-days in the 中证1000 sample had moves of ±9.95% or larger. The basket had exactly 2 days that moved ±10% or more. Portfolio-level tail behavior and single-stock tail behavior are almost separate phenomena. Diversification is a real risk reduction mechanism when stocks are not tightly co-moving; it fails precisely in the crisis regimes where correlations go to 1.

**A single event can dominate three-year statistics.** 8 days out of 725 flipped 沪深300 kurtosis from 2.31 to 9.92 and its skewness from near-zero to +1.07. Higher moments are extremely fragile to their most extreme observations. Any descriptive statistic on three years of data is implicitly a statement about a dozen or fewer tail events, not about 700+ observations. This has direct implications for backtest skepticism: before trusting any Sharpe, kurtosis, or skewness number, drop the single most extreme observation and recompute. If the number changes dramatically, that one observation IS the signal.

**Kurtosis measures tail extremeness in sigma-units, not raw percent.** A +9% day in a calm distribution (low baseline std) contributes more to kurtosis than a +11% day in a wild distribution (high baseline std). This is why my naive "small-caps have higher vol so they must have higher kurtosis" intuition was backwards: a given raw move is less anomalous when the baseline vol is already high.

**Inclusion bias and survivorship bias are distinct mechanisms operating in the same direction.** Survivorship bias: delisted-between-2022-and-today stocks aren't in today's constituent list at all, so the worst performers are missing. Inclusion bias: stocks added to the index during 2022-2024 are in my sample because of strong recent performance, and pulling their return history back to 2022 captures a rally they earned before being in the index. Both biases remove losers and retain winners; both inflate measured returns and thin measured left tails. The effect is worse for the small-cap basket because small-caps delist and rotate more often.

**Basket composition can drift in ways that affect statistics.** My `filter_full_history()` cut at 2022-01-15 dropped 7 stocks (all 301xxx/688xxx), reshaping the 中证1000 basket toward older main-board small-caps. This reduced IPO-pop bias but narrowed the basket to a less representative subset of the true index. The true 中证1000 contains a meaningful fraction of 创业板/科创板 names with ±20% daily limits, and a proper point-in-time analysis would include them.

**涨跌停 clipping at the individual stock level does not translate cleanly to a basket-level shelf.** Session 3 showed the ±10% shelf in 华升股份's QQ-plot. At basket level, averaging dilutes individual limit-hits to fractions of a percent, so no shelf appears in the basket QQ-plot. The distortion still exists — measured small-cap basket kurtosis is biased downward because the individual-stock tails that feed into it have been clipped — but it is invisible in the basket-level visualization.

**The predict-then-measure loop has concrete diagnostic value.** Predictions that held (std, co-movement, ex-stimulus skew) told me my model of the market was right in those dimensions. The kurtosis prediction that failed taught me three things I didn't know before running the experiment: that averaging compresses kurtosis more when stocks are less co-moving, that kurtosis is sigma-unit relative, and that measured kurtosis of a limit-clipped distribution is systematically biased down. A successful prediction would have taught me less.

## Open items for next session or later

**Session 5 (Project 1 closer): formal normality tests.** Apply Shapiro-Wilk and Jarque-Bera to both baskets' returns. Predict the p-values before running. The expected outcome is rejection with p ≈ 0 for essentially any real return series, which raises the methodological question of what hypothesis testing is actually useful for in this context. This bridges to Project 3 (correlation, regression, first real hypothesis tests) and Project 4 (hypothesis testing framework proper).

**Limit-hit detection utility.** Still deferred from Session 3. Should write a helper that takes a returns Series and returns a boolean mask of limit-hit days, handling both ±10% (main board) and ±20% (创业板/科创板) thresholds based on stock code prefix. Every future analysis of small-caps needs this.

**Composition-bias quantification.** Not urgent but interesting: how different would basket statistics look if I re-sampled 25 stocks from 中证1000 with proper point-in-time constituents (including delisted names and proper IPO dates)? Deferred to Phase 3 when factor testing makes point-in-time data essential.

**Geometric vs arithmetic return annualization.** Noted in session: multiplying daily mean by 242 is the arithmetic annualization, not the geometric. For daily means this close to zero the difference is small, but the habit of distinguishing the two matters. Should standardize on one convention going forward.

## State of my understanding

**Solid on:** how to pull and sample from an index constituent list via AKShare, the distinction between survivorship and inclusion bias, constant-composition vs variable-composition basket construction, the mechanics of `pd.DataFrame(close_series).pct_change()` and `.mean(axis=1)` for panel-level return computation, the averaging effect on higher moments, the sensitivity of skewness and kurtosis to single extreme observations, kurtosis as a sigma-unit relative statistic, the distinction between individual-stock and basket-level tail behavior, the visual signature of co-movement in matching extreme dates.

**Newly solid:** predictions about market data should be made with specific numerical ranges, not just directional claims. A prediction that fails in a specific direction with a specific mechanism is more valuable than a prediction that holds. The right first move on any backtest headline number is to drop the most extreme observation(s) and recompute — if the number changes dramatically, that observation IS the signal.

**Accepted but not fully formalized:** how to quantify "this statistic is biased in direction X by mechanism Y" without a formal test. Currently relying on intuition and direction-of-bias arguments. Formalization will come in Project 4 with hypothesis testing and in Project 8 with bootstrap methods.

**Still ahead:** formal normality tests (Session 5), limit-hit utility, rolling volatility and drawdown (Project 2), correlation and regression (Project 3), the full hypothesis-testing framework (Project 4), and everything after.

## Personal reflection

*[to be filled in by me]*

## Meta-note on the predict-first habit

Claude flagged at the end of the session that I had a moment midway where I said "I don't really know how it's actually gonna look like" when asked to predict basket kurtosis and skewness. The right version of that response is "I think X because Y, but I'm not confident" rather than "I don't know." The predict-then-measure loop only produces diagnostic information if I commit to a prediction — diagnosing nothing against nothing teaches nothing. For Session 5 onward, push for a reasoned guess even when uncertain. Reserve "I don't know" for cases where I genuinely have no basis, not cases where thinking hard would produce one.

## Ready for Session 5

**Session 5 topic:** formal normality tests (Shapiro-Wilk, Jarque-Bera) applied to both basket return series, full-sample and ex-stimulus. First explicit encounter with p-values and null hypotheses in the context of real market data. Intended as the Project 1 closer and the intuition bridge to Project 3 (hypothesis testing in regression) and Project 4 (hypothesis testing framework).

**Prerequisites met:** both basket return series exist and are saved in `Session_Four.ipynb`. Visual non-normality has been demonstrated in Sessions 3 and 4 via QQ-plots and histograms with normal overlays. Sample-size intuition ("kurtosis of 0.5 at N=241 might be noise, kurtosis of 10 cannot be") was articulated in Session 3 and is the informal version of what the formal tests quantify.

**Expected duration:** 1-2 hours. Short follow-up session, not a full 1.5-hour working block.

**Suggested starting move:** before running any tests, predict the p-values for both baskets on both tests. Commit to a prediction in numerical form (e.g., "p < 0.001 on Jarque-Bera for both baskets full-sample, p < 0.05 on Shapiro-Wilk for 中证1000 ex-stimulus"). Measure the gap between the prediction and the result.
