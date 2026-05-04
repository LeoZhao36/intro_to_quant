# Project 6 — Comprehensive Closeout

**Project focus:** Build a properly architected factor-research pipeline for the bottom-1000 liquid A-share universe, run the full single-factor and multi-factor analysis with statistical rigour, and answer the binding question: *do these factors produce tradable alpha after realistic costs?*

**Date range covered:** Project 6 began with Sessions 1-2 in early 2026 (size factor), continued through Sessions 3-5 (value, momentum, low-vol), surfaced architectural problems in the multi-factor phase that triggered the universe rebuild (2026-04-29), then re-ran every analysis on the rebuilt panel through Phase D (2026-04-30). Total: roughly ten working sessions across the project life.

---

## Top-line finding

**Within the bottom-1000 liquid A-share universe, the only tradable edge after realistic retail costs is a regime-gating mechanism (sit out high-Sharpe-trailing-window weeks). Active factor strategies based on momentum, value, and low-volatility produce gross alpha but lose most of it to turnover-driven trading costs. The "best" cost-adjusted strategy is gated-baseline (Sharpe ~0.84) which is essentially equivalent to the more elaborate gated-segmented composite (Sharpe ~0.85).**

This is a substantively negative result for the active-factor thesis at retail-friction levels, with a modest positive result for the gating mechanic itself. Both findings are worth carrying forward.

---

## Key takeaways

1. **The universe rebuild was the most important methodological investment in the project.** The original Project 5 panel had three architectural flaws: universe-turnover bias (factor signals computed only on in-universe stocks systematically miss formation-window data), survivorship bypass (~6% of rows escaped the ST filter), and a 20-day liquidity window vulnerable to single-day volume spikes. The rebuild produced a clean 381-week panel covering 2019-01-02 to 2026-04-29 with a 60-day liquidity window, point-in-time ST filtering, and a candidate-history architecture that decouples signal computation from sort eligibility. Coverage rose from 19.9% in the original FMB to 75-80% in the rebuilt panel.

2. **Size is a clean null in the bottom-1000 universe.** Both the original 51-month panel and the rebuilt 380-week panel converged on the same answer: log market cap does not predict forward returns within the universe. Headline Q1−Q5 of +0.029%/wk at t=+0.39 with bootstrap CI clearly containing zero. The literature's "size premium" lives in the bottom-30% of A-shares that LSY exclude and we include, not within an already-small-cap universe sorted on relative size.

3. **Value (EP) is the strongest single-factor signal in the project.** The rebuilt panel produced headline t=−2.83 with Q1−Q5 −0.206%/wk, IC +0.0317 with CI excluding zero. Sector-neutral version strengthened to t=−5.04, confirming within-sector cheapness as the genuine mechanism. Both low-cap and mid-cap terciles BH-rejected (the original monthly panel only saw the low-cap rejection because of insufficient power). The value premium is real, persistent across regimes, and concentrates in the bottom two-thirds of the universe by cap.

4. **Short-horizon momentum (mom_4_1, ~1-month formation) is the universal-cap factor.** Headline Q1-Q5 +0.528%/wk at t=+4.84, IC −0.0558. All three cap terciles BH-rejected at p=0.000 with nearly identical effect sizes (+0.48, +0.51, +0.54). The strongest single-factor signal in the project. Long-horizon momentum (mom_12_4, mom_26_4, mom_52_4) was a clean null. The mechanism is retail overreaction-then-correction: recent losers mean-revert at ~1-month horizon.

5. **Low-volatility produces an IC-significant-but-Q1-Q5-null pattern.** IC mean −0.0241 with CI excluding zero across all three horizons (vol_52_4, vol_26_4, vol_13_4), but Q1−Q5 long-short was always insignificant. The signal exists monotonically across the volatility distribution but the extreme quintiles cancel out. The original monthly panel's BH-rejection in the high-cap tercile evaporated entirely with more data (p=0.154), confirming it as a small-sample artifact.

6. **FMB confirmed only z_mom as a multivariate signal.** With four sign-aligned factors (z_value, z_lowvol, z_size, z_mom) the headline FMB rejected only z_mom (t=+4.70, CI excluding zero) and marginally z_lowvol (t=+1.77, CI just barely excluding zero). z_value evaporated to t=+1.00 in multivariate despite its strong single-factor signal — the value premium lives in the cheapest tail (Q5 only), not linearly across the EP distribution, so a regression coefficient picks up almost nothing. z_size confirmed null. The original Project 6 multi-factor finding (pre-stimulus z_size BH-rejection) was a small-sample artifact that did not survive the rebuilt panel.

7. **The stimulus gate is the only non-trivial economic finding for tradable alpha.** A 12-week trailing-Sharpe trigger > +1.5 annualized that exits to cash adds ~+0.4 Sharpe across all six tested strategy panels, including the passive baseline. Gate-on baseline at Sharpe 0.84 essentially matches gate-on segmented at Sharpe 0.85. The mechanism is regime detection: weeks where universe-wide trailing Sharpe is already elevated tend to be followed by mean reversion not continuation. Sitting out 30% of weeks captures that.

8. **Cost adjustment kills mom_only and reduces segmented to baseline-equivalent.** mom_4_1 with gross Sharpe 1.11 falls to net Sharpe 0.84 at realistic retail cost (0.32% RT, 2% limit-down penalty). At aggressive cost (0.92% RT) it falls further to 0.34. Under stress (10% penalty + 0.92% RT), mom posts -7%/yr return with -77% drawdown. The strategy's gross alpha is paid as turnover cost; what looks like a strategy is mostly an execution-cost arbitrage that retail can't win.

9. **Daily-formation momentum drill-down confirmed the cost ceiling.** Tested mom_5d_0d, mom_5d_1d, mom_10d_1d, mom_20d_1d at the same weekly rebalance cadence. Shorter horizons capture more reversal signal in gross terms but turnover scales with signal speed (79% weekly for 5d, 47% for 20d). Net Sharpe at headline cost: mom_5d falls to 0.10, mom_10d to 0.25, mom_20d_1d to 0.52. The mom_20d_1d result reproduces mom_4_1 exactly. The skip parameter (skip=0 vs skip=1) made essentially no difference in our universe, confirming that bid-ask bounce is not material at our liquidity level.

10. **The most operationally simple strategy is also the most defensible.** "Hold the universe equal-weighted, exit to cash when 12-week trailing Sharpe runs above +1.5 annualized" produces Sharpe 0.84 net of headline cost without requiring factor selection, cap-tercile sorting, or z-score machinery. The marginal improvement from gated-segmented over gated-baseline is approximately 0.01 Sharpe, which is below the threshold of operational complexity worth introducing.

---

## Reference conversations

This closeout is the canonical Project 6 record. Tied to:

- **Project 6 Session 1-2 Closeout** (`Project_6_Session_1_2_Closeout.md`) — first refactor of size scripts, hypothesis-testing module promoted, size factor's five-layer null result on the original panel.
- **Project 6 Session 3 Closeout** (`Project_Six_Session_3_Closeout.md`) — refactor to `factor_utils.py` parametric architecture, EP sourcing, value factor's cap-tercile structural finding on the original panel.
- **Project 6 Single-Factor Phase Closeout** (`Project_6_Single_Factor_Phase_Closeout.md`) — momentum and low-vol single-factor sweeps that closed Block 2 on the original panel, surfaced the cap-tercile asymmetry.
- **Project 6 Multi-Factor Phase Closeout** (`Project_Six_Multi_Factor_Phase_Closeout.md`) — Fama-MacBeth and segmented strategy on the original panel, surfaced the universe-turnover problem (19.9% FMB coverage), motivated the rebuild.
- **Project 6 Universe Rebuild Handoff** (`Project_6_Universe_Rebuild_Handoff_Final.md`) — full rebuild execution covering Stages 0-5 (daily panel, weekly candidates, liquidity panel, universe membership, sector classification, candidate-history panel).

---

## Starting point

Project 6 inherited from Project 5: a monthly 51-date 1000-stock universe panel for 2022-2026, the seven hypothesis-testing functions scattered across Project 4 notebooks, the SW2021 sector classification, and three regime-event dates (雪球 2024-01-15, 新国九条 2024-03-15, PBoC stimulus 2024-09-18). The mandate was to apply rigorous factor testing to size, value, momentum, low-vol within this universe, with multi-test correction policies locked from the start.

Project 6 inherited two structural problems that didn't surface until Block 3 (multi-factor): the original Project 5 panel had universe-turnover bias and a survivorship bypass in the ST filter. These cost ~75% of the available statistical power for FMB analysis (19.9% coverage versus the 75-80% the rebuilt panel achieves) and partially confounded several single-factor results.

---

## Project thesis

If the bottom-1000 liquid A-share universe contains exploitable factor signals that survive realistic transaction costs, the five-layer robustness machinery applied across four factors (size, value, momentum, low-vol) plus multivariate FMB plus cost-adjusted strategy testing should detect them. What actually emerged across the project: factor signals exist in cross-section (momentum strongly, value clearly, low-volatility weakly), but only the weakest of execution-cost models leaves any of them with positive net Sharpe versus a passive baseline; the only durable economic finding is a regime-detection mechanism that any strategy can adopt and that needs no factor-selection machinery to extract.

---

## Progression

The project moved through four phases. Phase A and B are roughly Sessions 1-5 on the original panel; the universe rebuild and Phase C-D are entirely on the rebuilt panel.

**Phase A — Tooling and refactor (Sessions 1-3).** Promoted seven hypothesis-testing functions into `hypothesis_testing.py` with embedded smoke tests and the multi-test correction policy locked (Holm-Bonferroni for cross-factor families, Benjamini-Hochberg for within-factor robustness). Refactored the original three-script size architecture into a parametric `factor_utils.py` plus thin per-factor wrappers. Added EP sourcing (`source_ep_data.py`) via Tushare daily_basic. Verified bit-for-bit behavior preservation between old and new size code.

**Phase B — Single-factor sweeps on the original panel (Sessions 2-5).** Ran size, value, momentum, low-vol through the five-layer machinery (block bootstrap CI, regime split, tradable-only filter, sector neutralisation, cap-tercile conditioning with BH correction). Headline findings: size null, value BH-rejecting in low-cap, momentum noisy, low-vol BH-rejecting in high-cap. The cap-tercile asymmetry between value (low-cap) and low-vol (high-cap) became the canonical structural finding of Block 2.

**Phase C — Multi-factor on original panel (Session 6).** Ran Fama-MacBeth with sign-aligned z-scores and built composite/segmented strategies. FMB surfaced two unexpected results: (a) the headline z_size coefficient was a near-null but pre-stimulus z_size BH-rejected, suggesting size mattered in early regime but not late; (b) FMB coverage was only 19.9%, a structural problem with the panel rather than the analysis. The segmented strategy (value-low-cap + lowvol-high-cap legs) reproduced the cap-asymmetry finding at portfolio level. Cost-adjusted Sharpe analysis suggested costs were not the kill shot for segmented at the original-panel level. The 19.9% coverage problem motivated the universe rebuild.

**Universe rebuild (2026-04-29).** Executed Stages 0-5: unified daily panel pull (~50 minutes for 2,018 daily parquets via threaded Tushare with rate-limited concurrency), weekly Wednesday rebalance dates with point-in-time names from `pro.namechange()` (eliminating the 5.96% NaN-name survivorship), 60-day trailing liquidity panel, hybrid (X=75%, Y=3000万) liquidity floor producing N=1000 on every of 381 dates, SW2021 sector classification, and the candidate-history panel that decouples signal computation from sort eligibility.

**Phase A2 — Refactor for the rebuilt panel.** Wrote `config.py` with cadence-aware constants (PERIODS_PER_YEAR=52, BOOT_BLOCK_SIZE=12, BOOT_N=10000), `factor_panel_builder.py` to assemble the rebalance-frequency factor panel from Stage 5 outputs, refactored `factor_utils.py` for weekly cadence and multi-candidate Layer 2 regime splits (COVID lockdown, COVID reopening, PBoC stimulus). Forward returns recomputed from `(adj_close[t+1] / adj_close[t] - 1)` with consecutive-rebalance validation that invalidates suspension-gap rows.

**Phase B2 — Single-factor reruns on the rebuilt panel (Sessions 7-8).** Re-ran size, value, momentum, low-vol with 7.5x more data and 75-80% coverage. Findings already summarized in key takeaways. The momentum analysis added a multi-horizon sweep (mom_52_4, mom_26_4, mom_13_4, mom_4_1) which surfaced mom_4_1 as the only horizon with detectable signal, contradicting the JT-1993 long-horizon momentum thesis but consistent with retail-overreaction theory in Chinese markets.

**Phase C2 — Multi-factor on the rebuilt panel (Session 9).** Fama-MacBeth confirmed z_mom as the dominant multivariate signal (t=+4.70). z_value evaporated despite strong single-factor signal because the linear FMB doesn't pick up tail-localized non-linear signal. z_size's multifactor coefficient confirmed null (t=-0.85), closing the open question from the original panel's pre-stimulus z_size finding as small-sample artifact. Headline cross-sectional R² was 0.034, in line with the 0.03-0.08 range that Fama-French five-factor tops out at on US data.

**Phase D — Cost-adjusted strategy testing and daily drill-down (Session 10).** Built six strategy panels (baseline, mom_only, segmented × {gate off, gate on}). Designed and ran the limit-state filter for buy-side limit-up rejection. Applied limit-down sell penalties at 1%, 2%, 3%, 10% (sensitivity grid) and round-trip costs at 0.32% (realistic) and 0.92% (aggressive). Mom_only's gross Sharpe of 1.11 fell to 0.84 at headline cost and to 0.34 at aggressive cost. Segmented matched mom net but with lower drawdown. Gate-on baseline matched gate-on segmented at headline. Daily-formation momentum drill-down (mom_5d, mom_10d, mom_20d) confirmed shorter formation windows are catastrophically more expensive due to turnover scaling.

---

## Conceptual ground established (across phases)

**The N-T-measurement decomposition of factor analysis power.** Cross-section size N, time periods T, and measurement quality are independent levers each requiring different fixes. The rebuild addressed all three: N expanded via universe-turnover decoupling (~75-80% coverage vs 19.9%), T expanded via weekly rebalances on the 2019-2026 panel (380 testable weeks vs 51 monthly), measurement quality via PIT name filtering and unified daily panel.

**Universe-turnover bias mechanism.** Factor signals computed only on in-universe stocks systematically miss formation-window data of stocks transitioning into the universe. A 12-month vol or momentum window cannot be computed if the stock was not stored in the panel during those 12 months. The fix: separate the candidate-history panel (full daily price/fundamental data for every stock that has ever been in-universe) from the in-universe filter (applied only at the cross-sectional sort step).

**The hybrid liquidity floor design.** Percentile gate (X=75%) provides relative-liquidity stability across regimes; absolute floor (Y=3000万) catches genuinely illiquid bottom-end names that survive percentile in low-liquidity regimes. Neither alone is sufficient; both together produce a regime-stable filter.

**Sector dilution and within-sector signals.** A raw factor sort mixes within-sector signal with sectoral composition. When sectoral composition moves opposite the genuine signal (as for value in our 2022-2026 sample where structurally low-P/E sectors performed flat-to-negative), the raw spread understates the within-sector premium. Sector neutralisation strips the sectoral component out. The fact that value's premium got stronger after neutralisation (rather than weaker) is substantive evidence that the premium lives at the individual-stock level, not as a sector bet in disguise.

**IC vs Q1-Q5 divergence.** IC uses every stock at every position along the factor distribution, weighting monotonic relationships heavily. Q1-Q5 throws away the middle 60% and only compares extremes. When the underlying signal is roughly monotonic but extremes are noisy, IC produces tighter inference. Value's headline showed exactly this pattern (IC CI excluded zero before Q1-Q5 did). Conversely, when a signal is tail-localized (cheapest 20% only, like A-share value at the deep end of the EP distribution), Q1-Q5 captures it but linear FMB doesn't.

**Tail-localized vs linear signals.** Value's signal is non-linear: it lives in the cheapest 20% of stocks, not smoothly across the EP distribution. Quintile sorts capture this. Linear FMB regression doesn't, because the regression coefficient measures average sensitivity per unit z-score, and Q1-Q4 are roughly indistinguishable. This is why z_value's FMB t-stat collapsed to +1.00 despite the strong Q5 signal. Practical lesson: factors with tail-localized signals should be traded via Q5 isolation, not via linear factor exposure.

**The skip parameter is a US-1990s artifact.** The bid-ask bounce mechanism that motivates skip=1 in JT-1993 momentum literature is small-spreads-1990s-US-specific. In our universe with its tighter spreads (~0.05-0.10% on liquid small-caps) and 0.01 RMB minimum tick, the bounce contributes ~1-2% of the signal magnitude in worst case. Drill-down confirmed empirically: skip=0 and skip=1 daily-formation momentum produce essentially identical Sharpes (0.108 vs 0.078 net). For Chinese A-share work, drop the skip parameter going forward.

**Turnover is the binding constraint, not signal quality.** Phase D and the daily drill-down both reach this conclusion through different paths. At realistic retail cost levels (0.32% RT), short-horizon strategies cannot survive their own turnover regardless of how strong the gross signal is. Future strategy work in this universe should start from "what's my turnover budget at my cost level" and build signal selection from that constraint, not the other way around. The arithmetic: turnover × round-trip-cost must be less than gross signal alpha.

**Limit-state mechanics and execution friction.** Chinese A-shares have ±10% (Main Board), ±20% (ChiNext post-2020, STAR), ±5% (ST), ±30% (Beijing) daily limits. Stocks at limit-up on a buy date can be filled at the limit but only with queue contention. Stocks at limit-down on a sell date face thin sell-side order books and may produce partial fills. The buy-side filter handles unbuyability cleanly (no foresight). The limit-down sell penalty handles stuck-exit slippage by recording what happened (no foresight either). Realistic penalty calibration is 1-3%; 10% is a stress test that demonstrates the strategies' tail fragility but isn't an operational forecast.

**Gross-vs-net Sharpe degradation patterns.** A strategy's gross Sharpe is the academic finding; the gross-to-net degradation rate measures its operational viability. Mom_4_1 degrades from gross 1.11 to net 0.84 (24% loss) at realistic costs; segmented degrades from 1.08 to 0.85 (21% loss). Baseline gated degrades from 0.91 to 0.84 (8% loss). The strategies that hold longer (segmented, baseline) lose less to costs, even though they share the same underlying mechanism (gate). This is a structural advantage of slower strategies that doesn't show in gross numbers.

**Regime detection as an alpha source.** The 12-week trailing-Sharpe gate adds ~+0.4 Sharpe across all six tested panels, including the passive baseline. The gate captures a real economic mechanism: weeks where universe-wide trailing Sharpe runs above +1.5 are followed by mean reversion (broad-rally-then-correction). This is alpha that doesn't require factor selection, cap-tercile sorting, or any z-score machinery. The simplest version of the strategy (gate-on baseline) is both the cleanest and most operationally tractable.

---

## Skills (code-level patterns)

- Per-stock cross-sectional z-scoring with optional winsorization at [1%, 99%]: applied uniformly to ep, log_mcap, vol_K_S, mom_K_S before any multivariate aggregation.
- NaN-aware per-group regression: build valid_mask before lstsq, pre-allocate `out_residuals = np.full(len(df), np.nan)`, write residuals back via `valid_idx = valid_group.index.to_numpy()`. Surfaces NaN bugs early.
- Block bootstrap with cadence-aware block size: weekly cadence uses block_size=12 (~quarterly), monthly used 3 (~quarterly). Preserves serial correlation in the time-series of factor returns.
- Multi-candidate Layer 2 (regime split) reporting all candidates rather than pre-committing to one. Lets the data inform the choice rather than the choice contaminating the data.
- Universe-turnover decoupling: candidate-history panel for signals (full daily history per stock), universe-membership flag for sort eligibility. Separate the data architecture from the strategy logic.
- Forward-return validation against consecutive rebalances: drop suspension-gap rows that would otherwise paper-over a 2-week return as a 1-week return. Eliminates a subtle bias in mean-reversion factors.
- Limit-state detection with exchange-aware percentages: 10% for Main Board, 20% for ChiNext post-2020 / STAR, 5% for ST. Date-aware regime change for ChiNext (2020-08-24 transition).
- Buy-side filter only (Option A in the limit-state design discussion) plus limit-down sell penalty (Option B). No foresight in either; the buy-side decision uses week-t close, the sell-side penalty is applied to recorded losses.
- Turnover measurement from holdings: |new - old| / 2 / mean_size. Empirical, not assumed. Per-strategy turnover is a function of the cap-tercile structure and Q5 quintile size, both of which the strategy chooses.
- Gate-with-cash modeling: `apply_gate(returns, gate)` sets returns to zero on gated weeks. Re-entry on first non-gated week. No cash interest assumption (zero return) for conservatism.
- Stimulus gate construction: 12-week trailing Sharpe of baseline shifted by 1 (so week t's gate uses information up to week t-1, no foresight). Threshold > +1.5 annualized triggers cash hold.
- Sensitivity grids for cost analysis: 4 penalty levels × 2 cost levels = 8 net Sharpes per strategy, plotted as heatmaps to surface where the cliff lives.
- Bit-for-bit regression testing across refactors: `python size_analysis.py` after every change to `factor_utils.py`, comparing every printed number to the prior closeout. Differences in the third decimal place are not acceptable.

---

## Codebase

The Project 6 codebase organizes into three distinct layers, with the universe-rebuild artifacts forming the foundation and analysis-layer scripts consuming from them.

**Stage scripts (universe construction, in `New_Universe_Construction/`).** `daily_panel_pull.py` (unified Tushare pull with threaded concurrency, ~50min wall time), `stage1_weekly_candidates.py` (PIT names via `pro.namechange()`, 381 Wednesday rebalances), `stage2_liquidity_panel.py` (60-day trailing mean amount), `stage3_universe_membership.py` (X=75% Y=3000万 hybrid floor), `stage4_sector_classification.py` (SW2021 hierarchy + L3 membership), `stage5_candidate_history_panel.py` (8M-row candidate history with PIT sectors). Plus diagnostic scripts: `cap_drift_diagnostic.py`, `inspect_unknown_names.py`, `validate_pe_ttm.py`.

**Analysis scripts (factor analysis, in `Factor_Analysis_Weekly_Universe/`).** `config.py` (cadence-aware constants), `factor_panel_builder.py` (rebalance-frequency factor panel), `factor_utils.py` (~700 lines, all factor-generic logic: cross_sectional_zscore, compute_quintile_series, compute_ic_series, summarise_long_short, all five layers, plotting helpers), `multifactor_utils.py` (add_all_factors, fama_macbeth, summarise_coefficients), `inspect_panel.py` (CLI for parquet inspection).

**Per-factor scripts.** `size_analysis.py`, `value_analysis.py`, `momentum_analysis.py` (multi-horizon sweep), `lowvol_analysis.py` (multi-horizon sweep), `fama_macbeth.py` (FMB engine and headline + 3 layers), `composite_segmented.py` (six-panel strategy comparison with stimulus gate), `cost_adjusted_analysis.py` (limit-state filter + penalty + cost grid), `daily_momentum_drilldown.py` (Phase D drill-down on daily-formation momentum), `limit_state_filter.py` (per-day limit-state classification).

**Shared modules (in `Intro_to_Quant/` parent).** `tushare_setup.py` (singleton API client), `hypothesis_testing.py` (block_bootstrap_ci, t_test_two_sample, permutation_correlation, etc., with embedded smoke tests).

**Data files.** `data/factor_panel_weekly.parquet` (1.2M rows, 14 columns, 35 MB), `data/limit_state_panel.parquet` (~9M rows, 6 columns), `data/candidate_history_panel.parquet` (8M rows from Stage 5, 220 MB), `data/universe_membership_X75_Y3000.parquet` (1.7M rows from Stage 3), per-factor results CSVs (`single_factor_<name>_results.csv`, `cost_adjusted_metrics.csv`).

**Plots.** Cumulative-return charts per factor, IC time-series, cumulative six-panel comparisons (gross, headline net, stress net), sensitivity heatmaps for the penalty × cost grid, gate diagnostic plot showing trailing Sharpe and gated weeks.

---

## Misconceptions corrected

**The original Project 5 panel was "good enough" for multi-factor work.** It wasn't. The 19.9% FMB coverage from universe-turnover bias and the ~6% survivorship bypass produced a panel that statistical methods alone couldn't fix. The rebuild was the correct response. Lesson: when a multi-stage analysis has unexpected result patterns (multi-factor coverage 4x lower than expected, signal disappearing in some cells), suspect the data architecture before suspecting the methods.

**Pre-stimulus z_size BH-rejection in the original panel was real.** It wasn't. With 7.5x more data and 4x better coverage, pre-stimulus z_size t-stat went from BH-rejecting to t=-0.82 (fail to reject). Small-sample artifact. Lesson: at n<100 dates with ~30% coverage, BH rejections at the cap-tercile or regime level are at the edge of detectability and should be replicated on a larger panel before being trusted as findings.

**Long-horizon momentum follows the JT-1993 12-month formation model.** It doesn't, in our universe. The four-horizon sweep (mom_52_4, mom_26_4, mom_13_4, mom_4_1) showed mom_4_1 as the only horizon with detectable signal (universal BH-rejection, t=+4.84), while mom_52_4 / mom_26_4 / mom_13_4 were clean nulls. The mechanism is short-horizon retail overreaction reversal, not long-horizon information diffusion. The "any window" claim in LSY 2019 about Chinese markets favoring reversal at all horizons is more accurate than the JT-1993 continuation thesis at our universe scale.

**Low-vol works in the high-cap tercile.** It doesn't on the rebuilt panel. The original monthly's BH-rejection (t=+1.93 in the high-cap cell) came down to p=0.154 with the rebuilt sample. Genuinely a small-sample artifact. The lowvol signal exists (IC CI excludes zero) but is monotonic-not-tail and doesn't translate to a tradable Q1-Q5 long-short.

**Gross Sharpe of 1.11 means mom_4_1 is a tradable strategy.** It isn't, at retail cost levels. 47% weekly turnover at 0.32% RT cost is 0.15%/wk drag, ~7.7%/yr. The gross 0.47%/wk excess over baseline gets eaten almost entirely. The strategy's gross alpha pays for execution friction; net to a retail trader, it produces essentially baseline returns. Operational viability requires either lower costs (institutional access to ~0.05% RT) or lower turnover (longer formation windows that we tested and found inferior in gross terms).

**The composite/segmented strategy was supposed to add diversification.** It did at the cost level (segmented turnover 31% vs mom 47% means lower cost drag), but not at the signal level. The value-leg and lowvol-leg added zero gross alpha to mom; they only added cost-savings via lower turnover. The lesson: factor diversification within a portfolio is most valuable when factors have different time-series correlation patterns (so they reduce total volatility), not when they have different cap-tercile structures. Our segmented design assumed cap-tercile diversification matters; in practice, the time-series correlation of the three legs was high enough that diversification gains were small.

**Skip=1 in mom_K_1 formation is bid-ask-bounce protection that we should respect.** It is, in 1990s US markets. In our universe, drill-down showed skip=0 and skip=1 produce essentially identical signals, because A-share spreads are tight enough that bounce contributes <2% of the signal magnitude. Drop the skip going forward.

---

## Habits built

- **CI sign AND width interpretation, not just sign.** A CI of [-0.04%, +0.05%] is "we know the effect is tiny"; a CI of [-0.9%, +0.6%] is "we don't know where the effect is." Same null verdict, very different epistemic state. Affects how aggressively we should commit to or rule out the factor.

- **Sample-size honesty when interpreting p-values.** A p=0.08 at n=51 is "interesting but not actionable"; the same p at n=500 would be "marginally significant, worth a closer look." Never quote p-values without n in mind.

- **Sub-period volatility check.** Comparing pre/post-event std dev (not just mean) routinely flags regime changes that mean-only analysis misses. The 35% post-stimulus volatility compression on the original panel was a structural finding that mean-only analysis missed.

- **Reality-check after every layer.** Each robustness layer's output gets a one-line "what does this say" interpretation before moving on. Stops the trap of accumulating numbers without absorbing them.

- **Compute absolute returns alongside relative spreads.** A Q1-Q5 spread tells you nothing about whether the long-only leg is profitable. For any factor with a real signal, compute per-quintile absolute returns, the long-only alpha versus a passive baseline, and the regime decomposition. Different stories, both matter.

- **State the prediction in writing before running the test.** Calibration only improves if the prediction is observable. The "predicted high-cap tercile would be cleaner for value" misconception was correctable specifically because it was written down beforehand.

- **Sanity-check the data before running analysis.** The "0 rows excluded for E<=0" anomaly (Tushare encodes negative TTM as NaN) was caught at data inspection rather than after running on bad data. Pause on anything unexpectedly clean or anomalous.

- **Bit-for-bit regression testing after refactors.** Compare every printed number to the prior closeout. Differences in the third decimal place are not acceptable, even if they look small.

- **Multi-candidate decision-making.** When choosing among comparable analytical configurations (regime split candidates, cost levels, penalty levels), run all and report all rather than pre-committing to one. The data informs the choice; the choice doesn't bias the data.

- **Cost-adjusted reporting as the final step before declaring tradability.** Gross Sharpe is the academic finding; net Sharpe is the operational reality. They tell different stories. Don't confuse them.

- **Distinguish ambiguous nulls from clean nulls.** A "null" with CI [-0.05%, +0.10%]/wk is a clean null (we know the effect is small). A "null" with CI [-0.50%, +0.50%]/wk is ambiguous (we don't have power to detect anything in that range). Both fail to reject H0; only the first is informative.

---

## Thesis implications

**For the bottom-1000 A-share universe specifically:**

- Active factor strategies based on momentum, value, and low-volatility produce gross alpha that mostly evaporates at realistic retail costs.
- The strongest gross signal (mom_4_1, gross Sharpe 1.11) becomes Sharpe 0.84 at headline cost, essentially equivalent to gated baseline (Sharpe 0.84). The implementation effort for active factor selection is not paid back at retail cost levels.
- The simplest tradable edge is the regime-detection gate. Sit out high-trailing-Sharpe weeks; otherwise hold the universe equal-weighted. Sharpe 0.84 net of headline cost.
- The cap-tercile asymmetry (value in low-mid cap, lowvol in high-cap) confirmed in single-factor work but did not produce additional alpha at the strategy level.
- The literature's "size premium" does not apply within an already-small-cap universe. We do not need to model size as an active factor.

**For factor-research methodology:**

- Universe-construction architecture matters as much as factor methodology. The single highest-leverage methodological decision in Project 6 was the rebuild, which delivered 7.5x more data and 4x better coverage. Method improvements without architecture improvements would have left us at 19.9% coverage.
- Cost-adjusted Sharpe is the binding metric, not gross Sharpe. Strategies that look great in gross numbers may be uneconomic at realistic costs; strategies that look mediocre in gross may dominate because of low turnover. Net is the operational reality.
- Multi-candidate analysis (regime splits, cost levels, penalty levels, formation horizons) reveals more than single-point estimates. Run all reasonable configurations and report all; the data tells you which configuration is "real."
- Tail-localized signals (like value's Q5 effect) require quintile-sort analysis, not linear regression. FMB will undercount these. Choose the analytical method to match the signal's distributional shape.

**For Chinese small-cap retail trading specifically:**

- At realistic retail cost levels (~0.32% round-trip for liquid small-caps), high-turnover strategies are not viable. Weekly rebalancing on 4-week formation produces ~50%/wk turnover and ~8%/yr cost drag, which exceeds typical factor alpha.
- The skip parameter in momentum factor construction is a US-1990s artifact. Drop it for Chinese A-share work.
- Limit-state friction matters at the tail. 1.5% of in-universe rows hit limit-up on any given week, 0.8% hit limit-down. Most of the time these don't bite. In stress scenarios (panic weeks, broad sell-offs), the fraction can climb to 5-10% and translate to substantial drag on any active strategy.
- The stimulus gate is an asymmetric strategy. Most of its value comes from sitting out a small number of high-Sharpe weeks (~30% of the panel). The remaining 70% of weeks, gating contributes little. This asymmetry is good (low operational cost) and bad (sample-size sensitivity in evaluating its long-run value).

---

## Open items

- **Out-of-sample validation.** The 2019-2026 panel is what we have. The cleanest discipline is to hold out 2024-09 onward (post-stimulus) as test and refit on 2019-2024. Because we observed the post-stimulus regime in the in-sample data, all our findings are technically in-sample model selection. An OOS test would either confirm the gated-strategy Sharpe of ~0.84 or reveal it as a regime-specific artifact. High priority for a future project.

- **Gate parameter sensitivity.** We picked lookback=12 weeks and threshold=+1.5 ann from intuition. Sensitivity grid (lookback ∈ {8, 12, 16, 20}, threshold ∈ {+1.0, +1.5, +2.0}) would test whether the +0.4 Sharpe boost is robust across reasonable specifications or whether we inadvertently optimized in-sample. Quick to run, high value-per-effort.

- **Layer 3 tradable-only filter.** Deferred throughout the project. The cost-adjustment phase implicitly addresses execution realism via the limit-state filter, but Layer 3 was always meant to surface the difference between "factors as cross-sectional rank" and "factors as tradable rank." Worth running once the limit-state filter machinery is in place; cheap addition to the existing factor scripts.

- **Limit-state filter ST detection.** Currently relies on a name regex against the daily panel's `name` field if available. A more rigorous version would use Tushare's `pro.namechange()` history (already pulled for Stage 1) to determine whether each (stock, date) pair was officially ST that day. Eliminates the residual edge-case where a stock changed ST status mid-week and the daily panel snapshot caught only one side.

- **Carry-over modeling for stuck exits.** Phase D's limit-down sell penalty (Option B) treats stuck exits as a cost on returns. The more realistic Option C carries unsold positions forward to the next rebalance. This breaks weekly rebalancing into path-dependent positions, complicates the strategy abstraction, and changes the math substantially. Worth implementing only if backtesting realism becomes critical (e.g., for paper-trading validation).

- **Net-of-cost FMB.** The current FMB is gross. Strategy comparison happens at the portfolio level (composite/segmented), not at the regression coefficient level. A net-of-cost FMB version would show how much each factor's coefficient survives realistic friction, parallel to how Phase D handles strategy comparison. Not currently planned but valuable for academic clarity.

- **EP coverage drift across the panel.** EP coverage falls from ~82% in 2019 to ~62% in 2026. Likely reflects more loss-making firms entering the universe in late years. Not a methodological problem (NaN drops out cleanly) but it does mean late-panel value cells have ~25% smaller cross-section. Worth noting in any future work that emphasizes late-panel results.

- **Daily-rebalance momentum (Version B).** Phase D's drill-down was Version A (daily formation, weekly rebalance). Version B (daily rebalance, daily formation) was deferred. It would extract more reversal signal but at much higher turnover (likely 5x weekly costs). The cost arithmetic almost certainly kills it but worth measuring once for completeness.

- **Beijing Exchange exclusion.** Stage 1's regex (`^(60|68)\d{4}\.SH$|^(00|30)\d{4}\.SZ$`) excludes Beijing Exchange stocks (8xxxxx). Beijing has ±30% daily limits and a different trader profile (institution-only). Including BSE stocks would be a substantive expansion of the universe and might find different factor structures. Out of scope for Project 6 but worth flagging.

- **Composite alpha attribution.** We never decomposed the segmented strategy's alpha into "value-leg contribution + lowvol-leg contribution + mom-leg contribution + cross-leg interactions." The fact that segmented added little net alpha vs mom_only suggests value/lowvol legs are nearly redundant, but the formal attribution analysis was never done.

---

## Bridge to next project

Project 6 closed a loop: we asked whether the bottom-1000 liquid A-share universe contains tradable factor alpha, and answered honestly that within the limits of cost realism and architectural rigour, the active-factor thesis is weak and the regime-gating thesis is the only durable finding. The next project should pick up from one of two directions:

**Direction A: Deepen the gate mechanism.** The stimulus gate added more value than any factor strategy. A new project focused entirely on regime detection — what features predict universe-wide forward Sharpe, what's the correct gate formulation, how to size positions during regime transitions — would build on Project 6's strongest finding. Inputs: the 380-week factor panel, the universe-EW baseline returns, plus broader macro indicators (interbank rate, FX, bond yields, news sentiment) that we haven't yet incorporated. Roughly 4-6 sessions of work.

**Direction B: Extend universe and re-test factor structure.** The bottom-1000 universe's factor structure is what we now know. Extending to the bottom-2000 (with appropriate liquidity adjustments) or to the broader market (CSI300 + CSI500 + CSI1000) might surface different relationships, particularly for size (which the literature claims works at broader-market scale). The infrastructure built in Project 6 (stages 0-5) generalizes; the analytical machinery generalizes. Estimated: 3-5 sessions of universe construction work, then Phase B/C/D again.

**Direction C: Out-of-sample test of the existing strategy.** The most rigorous next step. Hold 2024-09 to present as test, refit on 2019-2024, see what survives. If gated-baseline Sharpe drops from 0.84 to ~0.40 OOS, the in-sample finding was regime-specific. If it holds at ~0.80, we have a real edge. 1-2 sessions, very high informational value, low risk of negative finding.

**Direction D: Pivot to intra-day or higher-frequency analysis.** Project 6 worked exclusively at weekly cadence. The factor patterns we found (especially short-horizon mom reversal) suggest sub-weekly signal might exist. This direction requires substantially different infrastructure (intraday data, lower-latency execution model, much tighter cost analysis) and is essentially a new project rather than an extension.

I'd lean toward Direction C as the immediate next step (1-2 sessions, high informational density, settles the OOS question) before deciding between A, B, or D for the longer-term direction. Direction A is the most natural extension of Project 6's findings and the highest probability of producing a real strategy. Direction B is the most ambitious but also the most likely to surface negative results that close interesting questions. Direction D is the most novel.

The honest practitioner reading of Project 6's overall outcome: we have a defensible, cost-adjusted, factor-analyzed conclusion that the active strategies we tested do not beat passive-with-gate at retail-friction levels. This is a substantively negative result for active factor work in this universe, but a substantively positive result for the gating mechanism. Both findings deserve to be carried forward into whatever comes next.

---

## Appendix: Key numerical results (rebuilt panel)

### Single-factor headlines (380 weeks, ~370 testable)

| Factor | Q1-Q5 %/wk | t | IC | IC CI | Layer 4 t | BH cap-tercile |
|---|---|---|---|---|---|---|
| size | +0.029 | +0.39 | +0.0061 | [-0.0041, +0.0146] | -0.26 | none |
| value (EP) | -0.206 | -2.83 | +0.0317 | [+0.0227, +0.0407] | -5.04 | low + mid |
| mom_4_1 | +0.528 | +4.84 | -0.0558 | [-0.0687, -0.0419] | +5.27 | all three |
| vol_52_4 | +0.080 | +0.84 | -0.0241 | [-0.0347, -0.0139] | +1.80 | none |

### FMB headline (337 testable dates)

| Term | t-stat | Bootstrap p | CI excludes zero |
|---|---|---|---|
| z_value | +1.00 | 0.379 | No |
| z_lowvol | +1.77 | 0.056 | Yes (just barely) |
| z_size | -0.85 | 0.485 | No |
| z_mom | +4.70 | 0.000 | Yes |

### Strategy Sharpes (gross-filtered, Phase D headline net, stress net)

| Strategy | Gross | Headline net | Stress net |
|---|---|---|---|
| baseline (gate off) | 0.53 | 0.47 | 0.29 |
| baseline (gate on) | 0.91 | 0.84 | 0.63 |
| mom_only (gate off) | 0.73 | 0.47 | -0.05 |
| mom_only (gate on) | 1.13 | 0.84 | 0.24 |
| segmented (gate off) | 0.74 | 0.53 | 0.12 |
| segmented (gate on) | 1.08 | 0.85 | 0.37 |

Headline net: penalty=2%, cost=0.32% RT realistic.
Stress net: penalty=10%, cost=0.92% RT aggressive.

### Daily drill-down (mom horizons, headline net Sharpe)

| Horizon | Turnover | Gross Sh | Headline Net Sh | Stress Net Sh |
|---|---|---|---|---|
| baseline (gate off) | 7% | 0.53 | 0.47 | 0.29 |
| mom_5d_0d (gate off) | 79% | 0.52 | 0.11 | -0.69 |
| mom_5d_1d (gate off) | 79% | 0.50 | 0.08 | -0.74 |
| mom_10d_1d (gate off) | 60% | 0.57 | 0.25 | -0.39 |
| mom_20d_1d (gate off) | 47% | 0.78 | 0.52 | +0.02 |
| mom_20d_1d (gate on) | 47% | 1.13 | 0.85 | +0.27 |

Confirms that shorter formation horizons cost more than they earn at retail friction; mom_20d_1d ≈ mom_4_1 (both gross 0.73-0.78).

---

*Project 6 closed: 2026-04-30. Total elapsed: ~10 sessions, ~40-60 working hours. Architectural rebuild + four factors + multivariate FMB + cost-adjusted strategy + daily drill-down. Codebase ~3000 lines. Dataset 35 MB (factor panel) + 220 MB (candidate history) + 50 MB (ancillary).*
