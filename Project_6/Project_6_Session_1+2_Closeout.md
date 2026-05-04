# Project 6 — Session 2 Closeout

**Session focus:** Building the statistical toolkit for Project 6, then applying it to test the size factor in our bottom-1000 universe through five robustness layers.

**Date range covered:** Two consecutive working sessions (Session 1 + Session 2 of Project 6, completed back-to-back due to session length).

---

## Key takeaways

1. The thin headline pipeline (Q1−Q5 long-short and Spearman IC) on Project 5's CSVs returned a noisy zero: Q1−Q5 mean −0.181%/month at t≈−0.48, IC mean +0.0153 at t≈1.29. Both indistinguishable from zero by inspection.

2. After five robustness layers (block bootstrap CI, regime split, tradable-only filter, SW L1 sector neutralisation, cap-tercile conditioning with BH correction), all eight tests on size produced 95% CIs containing zero. The mid-cap-tercile result at p=0.080 is the single closest-to-signal observation; under BH correction with family size 3 it does not reject. The honest verdict: no detectable within-universe size effect at conventional thresholds. CI widths of ~1.5pp/month allow effects up to about ±1%/month either way.

3. The wide CIs are an n=51 problem more than a "factor doesn't work" problem. With 51 monthly observations we don't have the power to detect effects smaller than roughly 0.5%/month. This calibrates expectations for value/momentum/low-vol next.

4. Most operationally interesting Pass 1 finding: standard deviation of Q1−Q5 dropped from 3.10%/month pre-stimulus (n=32) to 1.96%/month post-stimulus (n=19). 35% volatility compression. Mean is similar across regimes; volatility is not. This implies any pooled-sample factor analysis is mixing two different signal-to-noise environments.

5. The discrepancy between our negative-and-noisy result and the positive size factor in Liu-Stambaugh-Yuan / CH-3 is structural, not a data error. LSY's universe explicitly excludes the bottom 30% of A-shares; our universe is approximately what they exclude plus the segment immediately above it. "Does size predict returns within the smallest 1000 stocks?" is a fundamentally different question than "does size predict returns across the whole market?" — and the literature's positive answer to the second doesn't carry over to the first.

6. The Project 6 robustness machinery is now reusable. Rerunning all five layers for value/momentum/low-vol is mechanical and costs roughly one session per factor. The work invested in Session 2 amortises across the remaining factor tests.

---

## Reference conversations

This closeout is the canonical session 2 record. Tied to:

- Project 5 closeout (`/mnt/project/Project_Five_Closeout.md`) — defined Session 1 and Session 2 mandates, prescribed the multi-test correction question, set the starting state.
- Project 4 closeout — origin of the seven hypothesis-testing functions promoted into `hypothesis_testing.py`.

---

## Starting point

Session 1 inherited from Project 5:

- `universe_membership.csv` (250,862 rows, 52 dates, 1000 in-universe stocks per date).
- `forward_return_panel.csv` (51,000 rows, 51 dates because last date has no R+1).
- `sw_membership.csv` and `sw_classification.csv` (5,834 stocks mapped to 31 SW L1 sectors, treated as static across our 2022-2026 window because no `out_date` populated).
- Three identified 2024 regime events (雪球 meltdown 2024-01-15, 新国九条 2024-03-15, PBoC stimulus 2024-09-18).
- Universe construction: bottom-1000 by mcap, post liquidity filter, monthly mid-cycle rebalances.

Session 1 also inherited from Project 4 a debt that had been deferred for four sessions: seven hypothesis-testing functions scattered across notebook cells, never lifted into a clean module.

---

## Session thesis

If the seven hypothesis-testing functions were promoted properly and the size factor were tested rigorously, we'd expect to detect either a clear "size matters in this universe" result (validating the Liu-Stambaugh-Yuan literature within our specific subset) or a clear "size doesn't matter at this scale" result (suggesting the published premium is concentrated in the broader market segment our universe excludes). What actually emerged was a third outcome: indeterminate by sample size, with CIs wide enough to admit either answer. This is the most common factor-research outcome in practice and a useful calibration for the rest of Project 6.

---

## Progression

**Pass 1 — function promotion (`hypothesis_testing.py`).** Seven functions rebuilt from spec rather than migrated, organised in four conceptual blocks: two-sample tests (`t_test_two_sample`, `permutation_mean_diff`), correlation test (`permutation_correlation`), bootstrap pair (`bootstrap_ci`, `block_bootstrap_ci`), standalone utilities (`acf_band`, `cost_adjusted_sharpe`). Each with embedded smoke test, numpy-style docstring, ValueError on bad input. Used `np.random.default_rng(seed)` instead of legacy global `np.random.seed`. The block-bootstrap smoke test embedded an explicit AR(1) demonstration: theoretical CI-width inflation factor of √((1+ρ)/(1−ρ)) ≈ 1.73x for ρ=0.5, observed 1.66x on n=1000 simulated draws. The numerical evidence sits in the smoke test for re-inspection later.

**Multi-test correction lock-in.** Holm-Bonferroni for headline factor tests (the family of "does factor F work?" questions across 4-5 factors), Benjamini-Hochberg for within-factor robustness (the per-factor family of 4-6 conditional checks). `acf_band` uses plain Bonferroni internally because it produces a single horizontal threshold for plotting, not a sorted-p-value procedure. Decision recorded in the module docstring of `hypothesis_testing.py`.

**Pass 2 — thin size pipeline (`size_pipeline.py`).** Loaded Project 5 CSVs, computed log_mcap, quintile-sorted per rebalance date, joined forward returns, produced Q1−Q5 long-short and Spearman IC time series, plotted both with regime-event markers. Headline finding: Q1−Q5 mean −0.181%/month, IC mean +0.0153, neither separating from zero by inspection. Cumulative chart showed non-monotonic Q3>Q4>Q5>Q2>Q1 ordering, primarily driven by the post-PBoC-stimulus 2024-2026 sub-period.

**Pass 3 — robustness layers 1, 2, 3 (`size_robustness.py`).**
- Block bootstrap CI (block_size=3, n_boot=5000): Q1−Q5 95% CI [−0.895%, +0.616%], IC 95% CI [−0.0088, +0.0377]. Both contain zero. Formalised what the t-stats already suggested.
- Regime split at 2024-09-18: pre-stimulus mean −0.260% (std 3.10%, n=32, CI [−1.184%, +1.008%]), post-stimulus mean −0.049% (std 1.96%, n=19, CI [−0.950%, +0.865%]). Both still contain zero. The 35% volatility compression post-stimulus emerged as a structural finding.
- Tradable-only filter: 4.19% drop rate (much higher than the 0.5% baseline estimated from the closeout), but symmetric across quintiles; tradable-only mean −0.160% / CI [−0.873%, +0.642%], headline largely preserved.

**Pass 4 — robustness layers 4 and 5 (`size_robustness_pass2.py`).**
- Sector neutralisation (SW L1, static mapping): 0.15% unmapped (negligible), 31 unique sectors, sectors-per-date 28-31. Sector-neutral mean −0.136%, CI [−0.847%, +0.656%]. Sector composition contributed maybe a quarter of the (already-tiny) headline magnitude. Hypothesis "noisy headline masks a real size effect that sectors are obscuring" is rejected.
- Cap-tercile conditioning with BH correction: low p=0.878, mid p=0.080, high p=0.674. None reject after BH. Mid is the closest to a signal in the entire study at any layer; it fails BH (threshold for smallest p is 0.0167) but is interesting enough to log as a watchlist item.

---

## Conceptual ground (new in this session)

**Bootstrap CIs without normality assumptions.** Empirical CDF as a proxy for the true CDF; sampling with replacement to simulate alternative samples; percentile method for CI extraction; why i.i.d. resampling produces too-narrow CIs on serially correlated data; block resampling preserves local autocorrelation up to lag block_size−1; theoretical inflation factor √((1+ρ)/(1−ρ)) for AR(1) variance.

**Family-wise vs false-discovery error rates.** FWER = probability of any false positive in a family; FDR = expected proportion of false positives among rejections. Bonferroni and Holm control FWER; Benjamini-Hochberg controls FDR with strictly more power. Choice depends on whether false positives are uniformly more costly than false negatives (FWER) or roughly equally costly (FDR).

**Sector neutralisation via per-date residualisation.** Regress log_mcap on sector dummies cross-sectionally, sort by residuals. Residuals are mean-zero per date by construction (verified at machine precision: max |mean| = 4.92e-15). The Q1 quintile after residualisation reads "smaller than its sector peers" rather than "small in absolute terms." Tests size after stripping sector composition.

**Cap-tercile conditioning logic.** Splits the universe into low/mid/high cap thirds per date, runs Q1-Q5 within each. Detects whether the size relationship has the same shape across the cap distribution or differs locally. With per-tercile n≈333 stocks the within-tercile cross-sectional sampling noise is larger than the universe-wide cross-section, so within-tercile CIs are typically wider than the headline CI. Useful for diagnosing non-monotonic chart shapes.

**Why our negative size finding doesn't contradict Liu-Stambaugh-Yuan.** LSY excludes the bottom 30% of A-shares (the shell-value-contaminated segment) and tests size on the surviving universe. Our universe is approximately what they exclude plus the band immediately above. The two studies ask different questions of different populations. "Size effect across A-shares" and "size effect within the smallest 1000 stocks" can have different answers without either being wrong.

---

## Skills (new code-level patterns)

- `pd.qcut(s, 5, labels=False, duplicates="drop")` for quintile sorting with safe handling of duplicate edges.
- Per-group residualisation pattern: `df.groupby("rebalance_date")` → `np.linalg.lstsq` → assign residuals back via `idx = group.index.to_numpy()` (the obvious `group.index - df.index[0]` pattern is fragile against non-contiguous indices and the closeout's earlier draft had this bug).
- Reset index before per-group operations that write back: `panel.reset_index(drop=True).copy()` makes downstream index arithmetic predictable.
- BH step-up procedure: sort p-values, find the largest k such that p_(k) ≤ (k/n) × α, reject all p-values up to that rank.
- Module-with-embedded-smoke-test pattern: `if __name__ == "__main__": _smoke_test_all()` so `python module.py` is both an import target and a self-test.

---

## Codebase

Six new files in `Project_6/`:

- `hypothesis_testing.py` (961 lines incl. smoke tests) — seven functions, four conceptual blocks, multi-test correction policy in module docstring.
- `verify_imports.py` — imports each function and runs it on toy data; smoke-test for the module-as-package.
- `size_pipeline.py` — thin headline pipeline; produces `size_quintile_cumulative_returns.png` and `size_ic_time_series.png`.
- `size_robustness.py` — Pass 1 robustness (bootstrap CI, regime split, tradable-only).
- `size_robustness_pass2.py` — Pass 2 robustness (sector neutral, cap tercile + BH correction).
- `data/sw_membership.csv` and `data/sw_classification.csv` — SW L1 sector reference data.

---

## Misconceptions corrected

- **My calibration was wrong.** I anchored on Liu-Stambaugh-Yuan's t≈2.30 on SMB and predicted real-data Q1−Q5 of 0.3-1%/month. The data returned −0.18%/month, well outside my prediction range. The error was conflating "size in the broad A-share market excluding the bottom 30%" with "size within the bottom-1000 specifically." The published positive size factor lives in a different universe than ours; my prediction transferred it as if the universes were equivalent. Surfaced explicitly during the Session 1 results review.

- **Tradable-blocked rate higher than estimated.** Closeout estimated ~0.5% baseline; observed 4.19%. Layer 3 still leaves the headline largely unchanged (symmetric across quintiles), but the higher rate means tradable-blocking is a non-trivial data-quality concern in stress months specifically. Worth event-study analysis if any specific factor result depends on dates near regime events.

- **The cumulative-return chart's non-monotonic Q3>Q4>Q5>Q2>Q1 shape is NOT a sectoral story.** Pre-Pass-2 hypothesis was "middle-quintile leadership is sectoral composition, large-end may include near-graduating stocks." Layer 4 result rejects this: sector neutralisation barely moves the headline. The shape is something else (within-stress dispersion at Q1, possibly universe-boundary effects at Q5, no clean explanation for the middle leadership), and we don't have enough signal to disentangle further.

- **Index-arithmetic bug in residualisation function.** Initial draft used `out_residuals[group.index - df.index[0]] = resid` which silently produces wrong residuals when the input DataFrame has non-contiguous indices (which happens after any pandas filtering). Caught during Pass 2 review before it ran on real data; fixed by `df = panel.reset_index(drop=True).copy()` then `idx = group.index.to_numpy()`. Pattern worth keeping in mind for all future per-group operations that write back into a parent array.

---

## Habits built

- **Reality-check after every layer.** Each robustness layer's output gets a one-line "what does this say" interpretation before moving on. Stops the trap of accumulating numbers without absorbing them.

- **CI sign-AND-width interpretation, not just sign.** "CI contains zero" is necessary but not sufficient; the CI width tells you what the data CAN'T rule out. A CI of [−0.04%, +0.05%] is "we know the effect is tiny"; a CI of [−0.9%, +0.6%] is "we don't know where the effect is." Same verdict, very different epistemic state.

- **Sample-size honesty when interpreting p-values.** A p=0.08 at n=51 is "interesting but not actionable"; the same p at n=500 would be "marginally significant, worth a closer look." Never quote p-values without n in mind.

- **Sub-period volatility check.** Comparing pre/post-event std dev (not just mean) routinely flags regime changes that mean-only analysis misses. The 35% post-stimulus volatility compression is a Session 2 finding that mean-only analysis would have missed entirely.

---

## Thesis implications

- **Size as a primary factor in the bottom-1000 universe is unlikely to provide actionable edge by itself.** The five-layer null result is robust enough to act on as a planning constraint: don't construct a strategy whose primary signal is "smaller is better within the bottom-1000." The mid-tercile p=0.080 is a watchlist item but is not actionable today.

- **Factor combination, not factor isolation, is where edge most likely sits.** This is consistent with the closeout's Block 3 plan (multi-factor work after Block 2 single-factor tests). At our n=51, single-factor effects below ~0.5%/month are undetectable; combinations may produce sharper aggregate signals.

- **Pre/post-stimulus regime is a structural property of our sample.** Any factor result that's pooled across the regime is mixing two volatility environments. Going forward, every factor's result should be reported alongside its pre/post split, not just pooled. This is now a standing requirement, not a per-factor option.

- **The published-literature anchor needs scaling-down for our universe.** Effects reported on broad A-shares or US data are upper bounds for what we should expect in the bottom-1000 specifically. Concretely: when a paper reports SMB t=2.5 in their sample, our same-direction test at n=51 in the bottom-1000 might produce t=0.5-1.5 even if the underlying mechanism is real. We should not reject our findings against literature thresholds without recalibration.

- **Tradable-only filter material at 4.19%, not negligible.** Carry forward as a Block-3 concern when constructing tradable-strategy proxies.

---

## Open items

- **Cap-tercile mid p=0.080 watchlist item.** Re-examine if/when more data accumulates (additional months of forward returns added to Project 5's panel). At n=51 it doesn't reject BH; at n=80 with the same effect size it would.

- **Universe-boundary effect at Q5.** Hypothesis worth testing in a later session: stocks near the upper cap boundary may "graduate out" within a few months of entering Q5; if Q5 is enriched in just-rallied stocks about to leave, that mechanically caps Q5's forward returns. A check would be: condition Q5 on "still in universe at t+1" vs "leaves universe at t+1" and compare forward returns. Not a Block-2 priority; revisit in Block 3.

- **`acf_band` is built but not yet used.** It's in the module ready for the residual-diagnostic work in Block 3 (when we check whether factor IC time series have residual autocorrelation).

- **Regression-diagnostics promotion from Project 3.** Confirmed earlier in this session that `project3_utils.py` only contains the three baostock data helpers. The Project 3 regression diagnostics (residual normality tests, heteroscedasticity tests, etc.) are still inline in Project 3 notebooks. Defer their promotion until Session 3 when sector neutralisation regression diagnostics first need them in production code, not before.

---

## Bridge to next session

**Session 3 focus: value factor.** Same five-layer machinery, applied to value. Factor definition itself is the first decision: B/M, EP, BP, sales/P, cash-flow/P, or a composite. CH-3 used EP not B/M because EP is more robust to negative-equity firms common in the bottom segment of A-shares. Worth replicating CH-3's logic and using EP as the primary measure, with B/M as a robustness check. Need to verify which value-related fields are present in Project 5's panel; if EP isn't pre-computed, decide whether to compute it from earnings-and-price or whether to fall back on B/M.

Session 3 prerequisites:

1. Verify which value-related columns are in `universe_membership.csv` or available via `sw_classification.csv` join. If neither has earnings or book-value data, we'll need to source it (Tushare fields `pe`, `pb`, `ps`, etc., or akshare equivalent). Establish the data path as the first 15 minutes of Session 3.

2. Lock the primary value measure. EP recommended for consistency with CH-3 and for negative-equity robustness; user should weigh in.

3. Refactor the existing five-layer machinery so it accepts a sort_col argument and can be reused without code duplication. The Pass 1 and Pass 2 scripts currently embed `"log_mcap"` and `"log_mcap_resid"` as defaults; making this parametric is a one-session improvement that pays off across the remaining three factors.

Session 3 estimated scope: data sourcing + measure selection + refactor + headline + five layers. Tight for one session; may run over. Realistic to expect "headline + Pass 1" in Session 3, "Pass 2 + verdict" in Session 4. Same shape as size took.

**Predictions for value (calibrated against the size lesson, conservative).** Value in A-shares has stronger empirical support than size in the relevant literature (LSY find a value premium of ~0.8%/month at t>3 in their broader-market sample). For our bottom-1000 sub-universe and 4-year window, expect a real-data Q1−Q5 in the 0.3-1.5%/month range with t in the 0.8-2.0 range. CIs likely to contain zero but to be NARROWER than they were for size if value has structurally less month-to-month variability than size does (an empirical question we'll answer as we go). The mid-tercile result is a possible analogue; if value's direction-of-effect concentrates in one cap tercile, that's a specific parallel to flag.

These predictions are conscious calibration practice, not commitments. We log them now and check them at the end of Session 3.
