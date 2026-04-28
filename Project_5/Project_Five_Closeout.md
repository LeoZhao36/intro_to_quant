# Project 5 Closeout & Curriculum Revision: Universe Construction → Unified Factor Testing

**Completed:** 2026-04-26
**Project location:** Phase 3, Project 5 (Universe Construction)
**Status:** Closed. Curriculum re-scoped: original Project 5 (Size Factor) and original Project 6 (Multi-Factor Analysis) merge into a unified **Project 6: Factor Testing** that covers size, value, momentum, and volatility on the constructed universe.

---

## Executive summary

Project 5 was originally scoped in `quant_learning_plan.jsx` as "Your First Factor, Size" across 5-6 sessions: pull market cap, quintile sort, compute IC, discuss the size premium, run turnover analysis. What we actually built is a different project: **the universe-construction infrastructure that the original Project 5 plan needed but didn't budget for.** Five stages plus three descriptive options, taking three weeks of work, producing point-in-time correct membership data, a forward return panel with tradability flags, and a documented churn analysis.

Net result: the foundation we built is substantially better than the original plan called for, at the cost of postponing the actual factor test. The size-factor work itself, plus value, momentum, and volatility, are all still ahead.

The curriculum revision: rather than do "Project 5.5: Size" followed by "Project 6: Multi-Factor", fold all factor testing into a unified Project 6 that develops the testing framework on size first (because size is simplest), then applies the same framework to value, momentum, and volatility in succession. The Project 5 carry-forwards (sector neutralization, cap-conditional sub-analysis, regime sensitivity, tradable-only conditional reporting) apply to all factors and are encoded once at the project level.

---

## Curriculum trajectory: where we were, where we are, where we're going

**Original plan (from `quant_learning_plan.jsx`):**

| Phase | Project | Title | Sessions |
|---|---|---|---|
| 3 | Project 5 | Your First Factor, Size | 5-6 |
| 3 | Project 6 | Multi-Factor Analysis | 5-6 |
| 4 | Project 7 | Build a Backtester | 6-8 |
| 4 | Project 8 | Strategy Evaluation & Paper Trading | 4-6 |

**What actually happened:**

Project 5 became universe construction infrastructure (Stages 1-3 + Options 1-3, ~3 weeks of work). The actual factor research the original plan called for in Project 5 was never started.

**Revised trajectory:**

| Phase | Project | Title | Sessions |
|---|---|---|---|
| 3 | Project 5 | **Universe Construction** (complete) | Done |
| 3 | Project 6 | **Factor Testing** (unified: size, value, momentum, volatility) | 8-12 |
| 4 | Project 7 | Build a Backtester | 6-8 |
| 4 | Project 8 | Strategy Evaluation & Paper Trading | 4-6 |

The numbering of Projects 7 and 8 stays the same. Only Phase 3 reorganizes.

**Why fold size into Project 6 rather than do it as a separate project.** Three reasons. First, applying the full Project 4 toolkit to one factor takes more sessions than the original plan allotted, and the toolkit is the same across factors, so it's more efficient to develop the framework once and apply it four times. Second, the Project 5 carry-forwards (sector neutralization, cap-conditional sub-analysis, regime sensitivity, tradable-only reporting) need to apply to all four factors uniformly, which is easier in one project. Third, multi-factor combination work (correlation matrix, composite scoring) has to come after each factor is individually tested, so doing all of them under one project keeps that downstream work natural.

---

## What Project 5 actually built: stage-by-stage retrospective

### Stage 1: Tushare rebuild and mcap correction (2026-04-25)

**The architectural shift.** Started Project 5 expecting to extend a baostock pipeline that worked fine on a single date but projected to ~24 hours of runtime over 52 monthly rebalances with 8-thread concurrency. The diagnosis was not a tuning problem but an architectural mismatch: baostock's interface is shaped around per-stock-time-series queries, but the question being asked was per-date-cross-section. Switched to Tushare Pro's `daily_basic` endpoint, which returns the entire A-share universe for one date in a single call. **500x speedup** (24 hours → 2.8 minutes), achieved by changing the data source rather than tuning the loop.

**The mcap correction discovery.** Cross-source diagnostic surfaced a methodological bug in Session 1's mcap derivation. The old formula was `close × volume / (turn / 100)` using forward-adjusted prices but current share counts. Combined adjusted prices with current shares produces a number that is neither the historical mcap nor the current mcap. Median impact ~0.7% but tails of 200%+ disagreement on stocks with recent corporate actions (BYD, etc.). Tushare's `circ_mv` reports market cap directly from exchange records, sidestepping the issue.

**Key habits built or reinforced.** Smoke-test-then-full pattern (one stock first, then 52 dates). Hypothesis enumeration before drilling into data. Cross-source validation as the standard for any new data dependency. `_retry_on_network_error` helper added to handle Tushare's occasional `ReadTimeout` at high call volumes.

**Output.** 52 candidates_*.csv files in `data/candidates/`, one per monthly rebalance date from 2022-01-17 through 2026-04-15. Filter chain stable across all dates: ~4-5% drop for non-equity codes (北交所, B-shares, ETFs, indexes), 3-4% for ST and risk-warned stocks.

### Stage 2: Trailing 20-day liquidity panel (2026-04-25)

**Same architectural principle, larger application.** 996 unique trading days across the 52 trailing-20-day windows. Naive read suggested 5M API calls; restated correctly as 996 cross-sectional pulls. ~28 minutes wall time including a single retry on call ~412.

**The regime-sensitivity finding.** The Session 1 calibration of "3000万 RMB/day liquidity floor" was correct on its single date but did not generalize. Full-universe pass rate ranged 67% to 99.7% across the panel; bottom-1000 pass rate 38.5% to 98.9%. The fix was a **hybrid floor**: rank-based (top X% by liquidity) for regime-stable size, plus an absolute backstop (≥ Y RMB/day) for transactability. Pooled bottom-1000 percentiles (P10 = 1,524万, P25 = 2,525万, P50 = 4,535万) provided the anchors for the absolute parameter.

**Key habits built.** Diagnostic-first, decision-second separation (Stage 2 produced `passes_3000_floor` as a flag, not a filter). Schema validation on cache load. Smoke-test-then-full pattern formalized.

**Output.** `data/liquidity_panel.csv` (250,862 rows) plus `data/daily_panels/*.csv` (996 cached per-trading-day amount panels, **trimmed columns, see Codebase note**).

### Stage 3: Hybrid floor selection and universe membership (2026-04-25)

**Pure orchestration, no data work.** Stage 3 is the decision layer. Loaded the candidate sets and the liquidity panel, applied the hybrid rule under three (X, Y) candidates, picked one, wrote the canonical universe.

**The corrected ordering.** Original implementation outline (bottom-1000 by mcap first, then liquidity filter) reproduced the variable-universe-size problem Stage 2 was meant to address. Corrected ordering (liquidity filter on full set first, then bottom-1000 by mcap) makes universe size invariant by construction. Aligns with standard practice in Liu-Stambaugh-Yuan (2019) and Li-Rao (2022).

**Selected parameters.** (X=80%, Y=1500万). Empirical comparison of three sweeps showed (80, 2500) was nearly indistinguishable from (80, 1500) in this regime, so the simpler less-aggressive Y won. Y=1500万 has a clean empirical anchor: it sits at the P10 of Stage 2's pooled liquidity distribution.

**Output.** `data/universe_membership.csv` (250,862 rows): one row per (rebalance_date, ts_code) for every candidate, with `in_universe` boolean (True for exactly 1000 stocks per date), `circ_mv_yi`, `mean_amount_wan`, `rank_by_mcap`. **This is the canonical universe file consumed by every downstream Project 5 analysis and by Project 6.**

### Option 1: Universe descriptive analysis (2026-04-26, Session 4)

**Cap distribution evolution.** The bottom-1000 universe drifted asymmetrically over the sample. P5 cap grew +105%, P95 only +30%. The floor of "small-cap" moved up much faster than the ceiling. Eye-reads on linear-axis plots miss this; coefficient of variation (P5 CV = 0.34 vs P95 CV = 0.19) catches it. Same scale-vs-shape principle as Project 1 Session 2's kurtosis/SD distinction.

**Sector composition.** Multiple "growth" sectors (机械设备, 电子) had non-monotonic peak-and-recede trajectories rather than monotonic drift. Several sectors shrank consistently (食品饮料 halved, 建筑装饰 -9, 美容护理 halved). Banks and 非银金融 essentially exited. Net concentration rose modestly (HHI 0.057 → 0.062).

**The 申万 hierarchy carry-forward.** Tushare's `index_member_all` returns each stock's *current* classification with `in_date`, but does not retain historical classifications a stock has left (`out_date` uniformly null). Partial point-in-time only. The 未分类 bucket absorbs the gap. **This is a documented limitation that affects sector-neutral factor work in Project 6.**

**Output.** `data/sw_classification.csv` (511 rows: 31 L1 + 134 L2 + 346 L3), `data/sw_membership.csv` (5834 rows), interactive Plotly treemap, static line chart.

### Option 2: Universe-conditional return panel (2026-04-26, Session 5)

**The big course-correction.** Started by building a limit-hit utility from `prev_close × pct + rounding` (per Session 4 bridge). Caught a real bug, Python's banker's rounding produced wrong limit prices on cases like `round(8.45 * 1.10, 2) = 9.29` when the exchange uses 四舍五入 to give 9.30, and fixed it with a `Decimal`-based `_round_half_up`. Then realised Tushare exposes the exchange's official limit prices directly via `pro.stk_limit()`, which makes the entire computed-limit utility unnecessary. **Course-corrected to use `stk_limit` as the source of truth.** The lesson worth keeping: when designing infrastructure, the first question is "what's the most authoritative source?" not "how do I compute this from raw inputs?"

**The 前复权 forward return formula.** `forward_return = (close[R+1] × adj_factor[R+1]) / (close[R] × adj_factor[R]) - 1`. The latest_adj_factor that would normally appear in qfq computation cancels in the ratio, so we only need adj_factor at R and R+1. Total return including dividend reinvestment effects.

**Tradability flags from `stk_limit`.**
- `entry_tradable = present in daily_R AND close_R != up_limit_R` (涨停 blocks entry)
- `exit_tradable = present in daily_R+1 AND close_R+1 != down_limit_R+1` (跌停 blocks exit)

The asymmetry reflects queue mechanics. At 涨停, late-arriving buyers can't fill because they're queued behind sellers who have withdrawn. At 跌停, the reverse for sellers.

**The three regime events visible in the panel.**
1. **雪球 meltdown**, Feb 2024: R=2024-01-15 → R+1=2024-02-19 has mean return −27.9%, std 10.6% (lowest std-to-mean ratio of any pair, consistent with correlated forced selling on snowball-related small-caps).
2. **新国九条**, Apr 2024: R=2024-03-15 → R+1=2024-04-15 has exit_blocked rate 10.3% (vs ~0.5% baseline) because 跌停 hit small-caps the day after the new delisting standards announcement.
3. **PBoC stimulus**, Sep-Oct 2024: R=2024-09-18 → R+1=2024-10-15 mean return +25.7%, but phantom rates stayed low because the rally peaked between rebalance dates rather than on them.

**Headline metrics.**
- 99.77% of forward returns computed (50,883 of 51,000)
- 97.69% with both legs tradable (entry AND exit)
- Median entry_blocked ~1.4%, median exit_blocked ~0.5%
- The 117 missing returns all have `exit_tradable == False`, concentrated in April-May rebalance dates (the annual delisting cycle following annual reports)

**Output.** `data/forward_return_panel.csv` (51,000 rows: rebalance_date, ts_code, forward_return, entry_tradable, exit_tradable). **This is the file Project 6 consumes for every factor's forward-return measurement.**

### Option 3: Universe behaviour and churn (2026-04-26, Session 5)

**Three exit categories per (R, R+1) pair.**
- **A. cap_graduated**: stock cap grew past the bottom-1000 cutoff. Universe rejects it for being too big. "Good exit."
- **B. lost_liquidity**: cap stayed in bottom-1000 range but failed the hybrid liquidity floor. Slow fade.
- **D. structural**: stock no longer in the candidate pool (delisted, became ST, B-share conversion, etc.).

**Headline numbers.**
- Mean churn 23.8% (matches Stage 3's projection exactly, validating the hybrid floor design)
- Range 19.3% (2022-12-15) to 30.2% (2025-10-15)
- Cap_graduated 50.7%, lost_liquidity 48.4%, structural 1.0%
- 117 structural exits = 117 NaN forward returns (cross-validation between Options 2 and 3)

**Two findings I had not predicted that the data forced me to update.**

*Churn is regime-stable through the 2024 events.* The 雪球 meltdown, 国九条, and stimulus rally show clearly in the return panel but **not** in churn. Mechanism: for churn to spike, you need *differential* cross-sectional movement that crosses the rank-1000 boundary. A broadly-correlated selloff or rally that moves everything in similar proportion preserves the rank ordering. The universe construction (rank-based liquidity + bottom-1000 cap) gives stable size by design and, as a side-effect, stable composition turnover rate.

*The 2025-2026 churn elevation is real but unexplained.* Mean churn rose from ~24% baseline to often >27% in 2025. None of the known regime events explains this. Possible drivers: post-stimulus mid-cap stocks dropping back into small-cap territory and competing at the boundary; rising sector rotation activity; idiosyncratic noise. **Flagged for Project 6 to monitor; if it persists, factor robustness requires comparing 2022-2024 against 2025-2026 sub-samples.**

**Sectoral pattern.** Sectors split into two groups depending on which exit channel dominates. The "growth-and-graduate" group (医药生物, 电子, 计算机, 汽车, 电力设备, 通信) leans toward cap_graduated exits, small-caps either grow into mid-cap territory or stay tradable. The "fade-out" group (建筑装饰, 轻工制造, 环保, 纺织服饰, 食品饮料) leans toward lost_liquidity exits, old-economy small-caps not graduating, just trading less and falling below the floor. **This connects directly to Stage 4's finding that 食品饮料 halved in universe representation: the mechanism is liquidity attrition, not cap graduation.**

**Output.** `data/universe_churn_panel.csv` (51 rows), churn diagnostic plot, sector breakdown plot.

---

## Reference conversations and documents

Each stage has a standalone handoff document and a conversation of its own. This closeout is the master summary.

- `Project_Five_Stage_One_Handoff.md`: Tushare rebuild and mcap correction
- `Project_Five_Stage_Two_Handoff.md`: Trailing 20-day liquidity panel
- `Project_Five_Stage_Three_Handoff.md`: Hybrid floor and universe membership
- `Project_Five_Session_Four_Handoff.md`: Option 1, descriptive analysis
- `2026-04-26 — Project 5 Session 5: Universe-conditional return panel and behaviour` (this session, covers Options 2 and 3 plus the curriculum revision conversation)

Reference texts kept in `/mnt/project/`:
- Liu-Stambaugh-Yuan 2019 "Size and Value in China" (CH-3 model)
- Li-Rao 2022 "Evaluating Asset Pricing Models" (CH-4_R model)
- Brooks *Econometrics for Finance* (regression, CLRM, GARCH)
- Tsay *Financial Time Series* (ARMA, volatility, multivariate)
- ESL (shrinkage, trees, boosting, SVM, CV)
- Wasserman *All of Nonparametric Statistics* (bootstrap, density estimation)

---

## Codebase state at end of Project 5

### In `Project_5/`

```
Project_5/
├── tushare_client.py: auth wrapper, exposes `pro` singleton
├── tushare_build_universe.py: Stage 1 driver
├── liquidity_panel.py: Stage 2 driver, _retry_on_network_error helper
├── bottom1000_liquidity_diagnostic.py
├── universe_membership.py: Stage 3 driver
├── inspect_universe.py: Session 4 utility
├── descriptive_cap_distribution.py: Option 1
├── sw_industry_pull.py: Option 1
├── sw_sector_panel.py: Option 1 (Plotly treemap)
├── sw_sector_lines.py: Option 1 (matplotlib trajectories)
├── forward_return_panel.py: Option 2
├── universe_behaviour.py: Option 3
├── _archive_baostock_pipeline/: deprecated
└── data/
    ├── universe_membership.csv: CANONICAL universe
    ├── universe_membership_X{X}_Y{Y}.csv: three sweep candidates
    ├── liquidity_panel.csv: Stage 2 panel
    ├── forward_return_panel.csv: Option 2 deliverable
    ├── universe_churn_panel.csv: Option 3 deliverable
    ├── sw_classification.csv: 申万 hierarchy
    ├── sw_membership.csv: 申万 stock-level mapping
    ├── candidates/*.csv: 52 files, Stage 1 outputs
    ├── daily_panels/*.csv: Stage 2 cache, ~996 files, TRIMMED COLUMNS
    ├── daily_panels_full/*.csv: Option 2 cache, 52 files, FULL COLUMNS
    ├── adj_factor_panels/*.csv: Option 2 cache, 52 files
    ├── stk_limit_panels/*.csv: Option 2 cache, 52 files
    └── *.png, *.html: diagnostic plots
```

**Cache duplication note.** `daily_panels/` (Stage 2) only has the columns Stage 2 needed, missing `close`. `daily_panels_full/` (Option 2) has all columns. Project 6 should use `daily_panels_full/` for any close-price work; `daily_panels/` is fine for amount-only work but treat as legacy.

### From earlier projects (separate per-project directories)

**Project 2 (`Project_2/utils.py`).** The original `utils.py` for the project. Contents: `get_stock_data` (Project 0), rolling vol/Sharpe/Sortino helpers, `_get_board_limit`, `_round_half_away`, `detect_limit_hits`, `compute_drawdown`, `risk_report`, `print_risk_report`, plus per-function smoke tests and `execute_smoke_tests` aggregator. Also has `plot_setup.py` for matplotlib Chinese font setup.

**Project 3 (`Project_3/`).** `project3_utils.py`: should contain `fit_with_diagnostics`, manual lag-k autocorrelation verification pattern, null-simulation block. **Status: function promotion was deferred at end of Project 3 and again at start of Project 4. Need to verify it actually happened.**

**Project 4 (`Project_4/`).** Seven functions still scattered across notebooks: `permutation_correlation`, `permutation_mean_diff`, `t_test_two_sample`, `cost_adjusted_sharpe`, `acf_band`, `bootstrap_ci`, `block_bootstrap_ci`. **Function promotion into `hypothesis_testing.py` was deferred four times and is still pending.** It was supposed to be the first operational task of Project 5 Session 1; Project 5 went a different direction so this never happened. **This is the first operational task of Project 6 Session 1.**

### At project root

- `utils.py`: currently empty (cleaned up at end of Project 5 Session 5 after the limit-hit utility was abandoned in favour of `stk_limit`)
- `.env`: `TUSHARE_TOKEN` (gitignored)
- `.gitignore`

---

## Key conceptual carry-forwards from Project 5

These are findings from Project 5 that **change how Project 6 should be structured.** Not optional refinements; design constraints.

### 1. Sector exposure is not stable across the sample

A factor tested over 2022-2026 implicitly mixes regimes where 电子 was 6% of the universe with regimes where it was 11%. Any factor that loaded heavily on a single sector would have looked artificially strong in mid-2024 due to position-sizing alone, independent of any factor signal. **Project 6 must report both raw and sector-neutralized factor results** (residualize the factor on L1 sector dummies before sorting) **or, at minimum, sector-conditional results** (factor returns broken down by sector, or in pre/post-stimulus sub-samples). Probably both for the headline factors.

### 2. The universe is structurally non-financial

Banks have entirely exited the bottom-1000; non-bank financials nearly so. This is permanent, not regime-dependent. **All Project 6 results should be described as "non-financial small-cap" findings, not generic small-cap findings.** A claim about "the size factor in Chinese small-caps" implicitly excludes banks; this should be made explicit in any Project 6 writeup.

### 3. Cap-conditional sub-analysis is needed

P5 (~16亿 by 2026-04) and P95 (~43亿 by 2026-04) within "the same universe" are structurally different populations: different liquidity profiles, different retail/institutional ownership. Factor sorts inside this universe will likely behave differently across cap sub-buckets. **Project 6 should test factors not just on the bottom-1000 as a single basket but on terciles by cap, and report results separately.** A factor that works on the top tercile (~33-43亿) but not the bottom tercile (~16-25亿) is a "near-mid-cap factor", not a "small-cap factor."

### 4. Tradable-only conditional reporting is required

Phantom-return rate is ~2% baseline, ~10% in worst-case events (2024-04 国九条 month). **Every Project 6 factor result reports two numbers: unconditional and tradable-only.** The unconditional uses all forward returns in the universe; the tradable-only restricts to rows where `entry_tradable AND exit_tradable`. The gap between the two is the cost of limit-board friction. For most months it's small; for the three identified 2024 events it can move the headline factor return materially.

### 5. Regime sensitivity testing using identifiable events

The three regime events (雪球, 国九条, stimulus) are visible in the return panel and need to be either excluded from baseline tests or analysed separately. Treating them as ordinary observations would wash out structural breaks. **Project 6 should report factor performance with and without each event in the sample, plus a 2022-2024 vs 2025-2026 split given the unexplained 2025 churn elevation.**

### 6. Universe stability is high enough for monthly-rebalanced factor research

23.8% mean churn means 76.2% month-over-month population stability. Factor signals computed at R apply to a population that's mostly the same at R+1. Cross-month statistical work is not being washed out by universe rotation alone. **This is a strength, not a constraint.** If churn were 50%+, the factor return would be heavily diluted by universe rotation; at 24%, the factor signal is what dominates.

### 7. Sectoral biases exist in the exit channel

"Growth-and-graduate" sectors (tech, healthcare, modern industrials) graduate stocks via cap rise. "Fade-out" sectors (construction, food, textiles, consumer) lose stocks via liquidity attrition. **A factor that loads heavily on either group is also implicitly loading on the exit-channel mix of that group**, which has implications for portfolio turnover and trading costs.

---

## Carry-forwards from Projects 1-4

These are tools and habits already built that Project 6 will use.

### From Project 1 (Return Distributions)

- 涨跌停 wall as a measurement bias → addressed in Project 5 Option 2 via `stk_limit`-based tradability flags
- Survivorship bias awareness → addressed in Project 5 Stages 1-3 via point-in-time universe construction
- Scale-vs-shape distinction → applied throughout Project 5 (CV in Stage 4, kurtosis vs SD in factor work)
- Bulk-vs-tails framework for distributional questions

### From Project 2 (Volatility and Risk)

Reusable functions in `Project_2/utils.py`: `risk_report` (drop-in for any return series), `compute_drawdown` (returns full DataFrame for plotting), `detect_limit_hits` plus helpers, basket construction helpers. **Not all of these will move to a new home in Project 6, they live in Project 2's `utils.py` and can be imported as needed.**

Conceptual carries: the σ√[ρ + (1−ρ)/N] floor for diversification (basket variance never goes below σ²·ρ no matter how many stocks). Sortino preferred over Sharpe for asymmetric returns. Max drawdown is mark-to-market; realised loss for trapped holders during 连续跌停 can be worse. The walk-forward / out-of-sample mindset.

### From Project 3 (Correlation and Regression)

`Project_3/project3_utils.py` (status to verify): `fit_with_diagnostics` for OLS + Breusch-Pagan + HC3 in one call. Manual lag-k autocorrelation verification pattern. Null-simulation block.

Conceptual carries:
- **Pearson vs Spearman correlation.** Pearson for linear, Spearman for any monotonic relationship and robust to outliers. **For factor IC, Spearman (rank IC) is the default** because returns have fat tails and rank order is what matters for sorting.
- **HC3 robust standard errors.** Default for any financial regression. Classical OLS standard errors under heteroskedasticity are systematically too small.
- **Joint testing before per-unit reading.** ACF eyeballing miss; Ljung-Box catches. Same principle applies to factor IC over time: don't read individual monthly ICs, run the joint test.

Substantive carry-forward: the **震元-vs-工商 sign flip**. Volume-return slope appeared to be positive for the small-cap and negative for the large-cap. Single-stock single-year tests were underpowered. Cross-sectional pooling in Project 6 buys the power. The form of the hypothesis: "the sign of the volume-return relationship systematically depends on market cap, with small-caps tending toward positive (slow information diffusion) and large-caps tending toward negative (flow-driven mean reversion)." If a Project 6 cross-sectional factor confirms this, it's a candidate factor (volume-return slope as a signal).

Substantive carry-forward: the **flow-exhaustion factor preview**. "After N consecutive same-direction days in an index-constituent large-cap, fade the move." Possibly a factor to test in Project 6, though our universe excludes large-caps so the test would be of small-cap autocorrelation rather than large-cap flow exhaustion.

### From Project 4 (Hypothesis Testing)

Seven functions still scattered across Project 4 notebooks; these need to be promoted into `hypothesis_testing.py` as the first operational task of Project 6 Session 1:

- `permutation_correlation(x, y, n_iter)`: Session 1
- `permutation_mean_diff(a, b, n_iter)`: Session 1/2
- `t_test_two_sample(a, b)`: Session 2 (wrapper around `scipy.stats.ttest_ind` returning t, p, CI)
- `cost_adjusted_sharpe(returns, cost_per_trade, turnover)`: Session 2
- `acf_band(n_obs, n_tests, family_alpha=0.05)`: Session 3 (Bonferroni-adjusted ACF band half-width)
- `bootstrap_ci(data, statistic, n_boot=10000, ci=0.95, seed=None)`: Session 4
- `block_bootstrap_ci(data, statistic, block_size=20, n_boot=5000, ci=0.95, seed=None)`: Session 4

Operational rules from Project 4:

- **Bootstrap CI on every estimate.** Sharpe, IC, factor return, correlation. Block bootstrap with block size 20 for daily data, block size 3 for monthly returns.
- **Bonferroni at α/n threshold.** Family size 5-15 per factor depending on robustness variants counted, so threshold lands at α=0.005 to α=0.01.
- **HC3 robust standard errors for any regression.** Already a default from Project 3.
- **Distinction maintained between statistical significance and economic significance.** A factor surviving all four statistical filters can still fail the cost filter. Project 6 must combine both.
- **Honest null reporting.** When factors don't clear thresholds, report so. Bonferroni cannot manufacture findings from null data.

---

## Open items and deferred caveats

### Soft look-aheads in Project 5

- **Point-in-time ST name resolution via `pro.namechange()`.** Stage 1 used present-day names from `pro.stock_basic(list_status='L')` to filter ST. ~0.04% NaN-name rate per date due to delisted stocks. The proper fix uses `pro.namechange()` to resolve names as-of-date. Deferred. **Recommendation: tackle in Project 6 if a factor result is sensitive to ST exclusion; otherwise leave as documented bias.**
- **Hierarchical 申万 point-in-time.** `pro.index_member_all` returns current classification only with `in_date`; `out_date` uniformly null in our pull. Partial point-in-time only. The 未分类 bucket absorbs reclassifications. **Bounds the precision of sector-neutral factor work.** Alternatives if this becomes binding: 中信 industries (`pro.ci_*`) or 东方财富 industries as cross-checks.

### Function promotions still pending

- **`hypothesis_testing.py`**: seven Project 4 functions. **First operational task of Project 6 Session 1.**
- **`project3_utils.py`**: three Project 3 helpers, status to verify at Project 6 open.

### Known limitations of the sample

- **Crisis-regime validation absent.** 2022-01 to 2026-04 contains the 2024-02 雪球 meltdown (one moderate stress event) but no 2015-H2-style sustained liquidity collapse. Conclusions are conditional on the regime of this sample. **A claim that "this factor works in small-caps" cannot be defended through a true crisis without crisis-regime data, which we don't have.**
- **2025-2026 churn elevation unexplained.** Real but mechanism unidentified. Project 6 should monitor whether factor results differ across 2022-2024 and 2025-2026 sub-samples.

### Other

- **Cache duplication** between `daily_panels/` (trimmed) and `daily_panels_full/` (complete). Architectural cleanup deferred. Project 6 should use `daily_panels_full/`.
- **Stage 2's `daily_panels/` was an architectural smell** that produced this duplication: caches optimized for one consumer (Stage 2's amount-based liquidity panel) are fragile when reused by another. Lesson worth keeping: caches should store the full primary output, not the consumer's needed subset.

---

## Project 6: Factor Testing: design

### Goal

Test whether size, value, momentum, and volatility factors predict future returns within the bottom-1000 small-cap universe, using the full Project 4 statistical toolkit, and producing factor results that account for sectoral biases, cap subspaces, regime sensitivity, and tradability constraints.

### What "factor testing" means concretely

For each factor F:

1. **Compute F per (rebalance_date, ts_code)** using point-in-time data only. Universe membership filter applied at this stage.
2. **Quintile sort** within universe at each rebalance date. Q1 (lowest F value) through Q5 (highest).
3. **Cross-sectional Spearman rank IC** between F and forward_return per rebalance date. Time series of 51 ICs.
4. **Q1−Q5 long-short return time series** (51 monthly observations).
5. **Bootstrap CI** on mean Q1−Q5 return (block size 3, since monthly returns are close to independent).
6. **Bonferroni threshold** at α/n with n = 5 to 15 depending on robustness variants tested. Default n = 10, threshold 0.005.
7. **Sector neutralization**: residualize factor F on L1 sector dummies before sorting; report both raw and neutralized.
8. **Cap-conditional sub-analysis**: split universe into terciles by `circ_mv_yi`; report factor results within each tercile.
9. **Regime sensitivity**: compute factor results for 2022-01 to 2024-12 and 2025-01 to 2026-04 separately; flag any sub-sample disagreement.
10. **Tradable-only vs unconditional**: every result reported in both forms. Gap is the limit-board friction cost.

### Factors to test

- **Size**: log of `circ_mv_yi` (already in `universe_membership.csv`). Within-universe size factor: measures whether smallest-of-small outperforms largest-of-small. Testable hypothesis: yes, modestly, consistent with Liu-Stambaugh-Yuan (2019) after their shell-value adjustment.
- **Value**: E/P (inverse of P/E from Tushare `daily_basic`), B/M (inverse of P/B). Liu-Stambaugh-Yuan and Li-Rao both use E/P over B/M for China; we should use E/P as primary. **Data work: pull `daily_basic` cross-sectionally per rebalance date** (already partially cached from Stage 1 since `daily_basic` was the source for `circ_mv` and other valuation fields).
- **Momentum**: past 12-month cumulative return excluding the most recent month (the standard "12-1" momentum). **Data work: requires past returns, not just forward returns.** Either compute from cached daily prices or pull additional daily history.
- **Volatility (low-vol anomaly)**: rolling 60-day std of daily returns at each rebalance date. **Data work: requires daily return history.** Same data source as momentum.

The data work for momentum and volatility is non-trivial; both require ~60 trading days of pre-rebalance price history per stock per rebalance, which is ~52 × 60 = 3120 stock-days per stock, or roughly 60 cross-sectional `pro.daily()` pulls per rebalance date covering the trailing window. **Architecturally consistent with Stage 2's pattern**: cross-sectional per trading day, dedup across overlapping windows.

### Suggested session map

This is a sketch, not a contract. Sessions expand and contract as understanding develops.

**Block 1, Foundation and size MVP.**
- **Session 1**: `hypothesis_testing.py` promotion (the function-promotion debt from Project 4). Verify `Project_3/project3_utils.py` exists. Quick smoke test loading `universe_membership.csv` and `forward_return_panel.csv`. Build the size factor end-to-end as a thin pipeline: `np.log(circ_mv_yi)` per stock per rebalance, quintile sort, IC time series, Q1−Q5 long-short return. No robustness checks yet: just verify the infrastructure produces reasonable numbers.
- **Session 2**: Apply Project 4 toolkit to size. Bootstrap CI on Q1−Q5 mean return. Bootstrap CI on mean IC. T-test on Q1−Q5. Bonferroni threshold at family size = 5. First real verdict on size factor.

**Block 2, Robustness on size.**
- **Session 3**: Sector neutralization. Pull `sw_membership.csv`. Build `residualize_factor` helper. Compare raw vs neutralized factor results. Cap-conditional sub-analysis (terciles by `circ_mv_yi`). Document whether size factor works uniformly across sub-buckets.
- **Session 4**: Regime sensitivity (2022-2024 vs 2025-2026). Tradable-only vs unconditional comparison. Cost-adjusted Q1−Q5 returns using `cost_adjusted_sharpe` from Project 4. Project 6 size-factor "complete" verdict.

**Block 3, Other factors using the same framework.**
- **Session 5**: Value factor. Pull `daily_basic` for E/P and B/M cross-sectionally per rebalance. Build value factor end-to-end. Apply same Block 1 + Block 2 framework. Verdict.
- **Session 6**: Momentum factor. Pull daily history sufficient for trailing 12-month returns. Build factor. Apply framework. Verdict.
- **Session 7**: Low-volatility factor. Reuse momentum's daily history. Build factor (rolling 60-day std). Apply framework. Verdict.

**Block 4, Multi-factor questions.**
- **Session 8**: Factor correlation matrix across the four factors and across robustness variants. Redundancy testing. Are momentum and volatility telling us the same thing? Is size after sector-neutralization different from raw size?
- **Session 9**: Composite scoring. Z-score normalization, equal-weight composite, IC-weighted composite. Test whether composite outperforms individual factors. Discuss factor crowding and regime decay.

**Block 5, Closeout.**
- **Session 10**: Project 6 closeout. Inventory of factors that survived, factors that didn't, factors with caveats. Bridge to Project 7 (backtester). The closeout document itself becomes the input spec for Project 7's first session.

Total: 8-10 sessions, possibly 12 if data work for momentum/volatility expands or if any factor's robustness check surfaces a substantive finding worth pursuing.

### Choice of multiple-testing correction

Bonferroni is the conservative default. **Recommendation from Project 4 closeout**: Bonferroni for the factor-discovery question (false positives are expensive), Benjamini-Hochberg for subsequent robustness checks (false negatives are equally problematic at that stage). Holm-Bonferroni is also defensible as a less-conservative alternative to Bonferroni for the discovery question. **Lock the choice at Project 6 Session 1 explicitly rather than letting it drift.**

### What "good" looks like for each factor

Following Liu-Stambaugh-Yuan and Li-Rao 2022 as benchmarks:

- **Size in China after CH-3 adjustment**: published t-statistic on SMB ≈ 2.30. The factor is real, modestly. We expect to see a positive Q1−Q5 in our universe.
- **Value in China**: published t on VMG (E/P-based) ≈ 4.50, stronger than size. Value factor should clear thresholds more clearly than size if the published results generalize.
- **Momentum in China**: weaker than in US, sometimes negative depending on universe and lookback. Expect a contested result; possibly a small reversal at the small-cap end (slow information diffusion creates short-term momentum within stocks but cross-sectionally...): this is exactly the kind of question Project 6 is designed to answer.
- **Low-vol anomaly**: well-established in US and Europe, mixed in China. Worth testing.

These are loose anchors. Our universe is more restricted than the benchmark papers' (bottom-1000 only, non-financial), so direct number comparison isn't valid; the qualitative direction of effects is the relevant comparison.

---

## Bridge to Project 6 Session 1

**The first conversation should open with two operational tasks before any factor work.**

### Task 1: Function promotion into `hypothesis_testing.py`

This is the four-times-deferred carry-forward from Project 4. Seven functions to lift from Project 4 notebooks into a clean module. Build a smoke test for each. Verify imports work from `Project_6/`. **This is the operational task of Project 6 Session 1, not optional.**

### Task 2: Verify input availability and build a thin size pipeline

Load `universe_membership.csv` and `forward_return_panel.csv`. Verify both contain the expected number of rows (250,862 and 51,000 respectively). Verify `in_universe` boolean works correctly.

Build the simplest possible size factor:
```python
universe_in = universe[universe["in_universe"]]
universe_in["log_mcap"] = np.log(universe_in["circ_mv_yi"])

# Per rebalance date, quintile-sort by log_mcap
universe_in["quintile"] = (
    universe_in.groupby("rebalance_date")["log_mcap"]
    .transform(lambda s: pd.qcut(s, 5, labels=False))
)

# Join forward_return
panel = universe_in.merge(forward_returns, on=["rebalance_date", "ts_code"])

# Q1−Q5 monthly time series
quintile_returns = (
    panel.groupby(["rebalance_date", "quintile"])["forward_return"]
    .mean()
    .unstack()
)
long_short = quintile_returns[0] - quintile_returns[4]  # Q1 − Q5

# Cross-sectional rank IC per rebalance
ic_series = (
    panel.groupby("rebalance_date")
    .apply(lambda g: g["log_mcap"].corr(g["forward_return"], method="spearman"))
)
```

Plot Q1 through Q5 cumulative return curves and the IC time series with stress-event reference lines. **Sanity-check: does Q1 (smallest stocks within universe) outperform Q5 (largest stocks within universe)?** If yes, the size premium exists in our small-cap universe even after the bottom-1000 restriction. If no or unclear, the size factor either doesn't work at this resolution or needs the robustness layers from Block 2.

### What the next conversation should know without being told

- The universe is the bottom-1000 small-cap A-share universe across 52 monthly rebalance dates from 2022-01-17 to 2026-04-15.
- The universe is structurally non-financial (banks excluded by the cap-bottom selection mechanism).
- Forward returns and tradability flags are pre-computed in `forward_return_panel.csv`. Use these; don't re-derive from raw prices.
- Sector classifications are in `sw_membership.csv` with the partial point-in-time correctness caveat.
- Three regime events to test factors against: 雪球 (2024-02-05), 新国九条 (2024-04-12), PBoC stimulus (2024-09-24).
- 2025-2026 has elevated churn (~27% baseline vs ~24% in 2022-2024); regime sensitivity should test 2022-2024 vs 2025-2026.
- Tradability flags are `entry_tradable` and `exit_tradable`. Every factor result reports unconditional and tradable-only versions.
- Bootstrap with block size 3 for monthly data, 20 for daily.
- Bonferroni threshold at family size 5-15 → α=0.005 to 0.01 per test. Lock the choice explicitly at Session 1.
- Tushare credentials in `.env` at project root. Token already authorized for `daily`, `daily_basic`, `stock_basic`, `trade_cal`, `index_classify`, `index_member_all`, `adj_factor`, `stk_limit`. Probably also authorized for `pro_bar` and `namechange` though not yet tested.

### Suggested first conversation name

`2026-04-XX — Project 6 Session 1: Function Promotion and the First Size Factor on the Constructed Universe`

The "XX" gets replaced with the actual date when the conversation opens. The convention follows Project 4 closeout's bridge: open with the first operational task as the conversation title.

---

## Net 小盘股 thesis status at end of Project 5

**Defensible from Projects 1-5 combined:**

- Small-caps in A-shares have systematic differences from large-caps in distribution (Project 1: positive skew in 中证1000, fatter tails), in volatility (Project 2: ZZ1000 basket Sharpe 0.60 vs HS300 0.76 in 2023-2026), in microstructure (涨跌停 wall biases small-cap risk measurement downward), and in liquidity (Project 5: 24% monthly churn at the bottom-1000, with sectoral variation in exit channels).
- Single-stock single-year tests for small-cap predictability are systematically underpowered. The cross-sectional pooling in Project 6 is the proper test.
- The universe construction itself is regime-stable: hybrid liquidity floor + bottom-1000 cap selection produces invariant size and stable composition turnover even through identifiable regime stress.

**Not yet defensible (will be addressed in Project 6):**

- Whether smaller stocks within the bottom-1000 universe outperform larger ones (the size factor's verdict in our specific universe).
- Whether value, momentum, or low-vol factors work in this universe.
- Whether any of these factors survive the full Project 4 toolkit at Bonferroni thresholds.
- Whether cost-adjusted returns leave anything on the table.

The 小盘股 thesis is the spine of the curriculum and Project 6 is where it gets its first proper test.

---

Project 5 is closed.

Suggested conversation name for Project 6 Session 1: `2026-04-XX — Project 6 Session 1: Function Promotion and the First Size Factor on the Constructed Universe`.
