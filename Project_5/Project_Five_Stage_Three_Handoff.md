# Project 5 Stage 3 Handoff: Hybrid Floor Selection and Universe Membership

**Completed:** 2026-04-25
**Project location:** Phase 3, Project 5 (Universe Construction), Stage 3
**Status:** Stage 3 complete. Infrastructure arc of Project 5 closes here (Stages 1-3). Universe is now usable for downstream Project 5 stock research and analysis. Project 6 (factor research) still ahead.

---

## Key takeaways

The hybrid liquidity floor is selected and the canonical universe is built. `data/universe_membership.csv` carries 250,862 rows covering 52 monthly rebalance dates from 2022-01 through 2026-04, with `in_universe == True` for exactly 1000 stocks per date and `False` for the remaining ~3500-4000 candidates that did not make the bottom-1000 cut. The chosen parameters are (X=80%, Y=1500万): top 80% by mean trailing-20-day amount within the full candidate set, AND amount ≥ 1500万 RMB absolute, AND bottom 1000 by `circ_mv_yi` from the survivors.

The decision rested on empirical comparison of three (X, Y) sweeps. Pair (80%, 2500) was nearly indistinguishable from (80%, 1500) in this sample regime (~8 stocks per date difference, virtually none at the bottom-1000 boundary), so the simpler, less-aggressive Y wins. Pair (70%, 2000) was a meaningfully different universe with mean cap ~20% higher and median liquidity ~30% higher, but at the cost of higher turnover (28.1% vs 23.8%) and a less small-cap composition. Y=1500万 also has a clean empirical anchor: it sits at the P10 of Stage 2's bottom-1000 pooled liquidity distribution (1524万), making the absolute floor a principled tail-cut rather than a guess.

The corrected ordering noted at the end of the Stage 2 bridge worked exactly as predicted. Universe size is N=1000 for all 52 dates under all three (X, Y) settings, validating the design. The original "universe size variance across regimes" diagnostic the Stage 2 outline proposed was correctly retired and replaced with a three-panel composition diagnostic (liquidity, market cap, turnover).

The infrastructure arc of Project 5 (Stages 1, 2, 3) closes with this handoff. The universe file is now consumed by all downstream Project 5 work and by Project 6 factor research when that opens.

---

## Reference conversations and documents

- `2026-04-25 — Project 5 Stage 3: Hybrid Floor Selection and Universe Membership` (this session)
- `Project_Five_Stage_Two_Handoff.md` (predecessor; canonical record of Stages 1 and 2; contains the corrected-ordering note that drove Stage 3's design)
- `Project_Five_Stage_One_Handoff.md` (Tushare migration and mcap correction)
- `Project_5/universe_membership.py` (Stage 3 production code)
- `Project_5/data/universe_membership.csv` (canonical universe; copy of `universe_membership_X80_Y1500.csv`)
- `Project_5/data/universe_membership_diagnostic.png` (canonical diagnostic plot)
- `Project_5/data/universe_membership_X{X}_Y{Y}.csv` and corresponding diagnostic PNGs for all three sweep candidates
- Liu-Stambaugh-Yuan 2019 "Size and Value in China" and Li-Rao 2022 in `/mnt/project/` (templates for the small-cap universe definition pattern Stage 3 implements)

---

## Starting point

Entered the session with Stage 2 closed at the bottom-1000 regime-sensitivity finding and the predecessor handoff specifying three (X, Y) sweep candidates plus a corrected ordering note added at session-end: liquidity filter on the full candidate set first, then bottom-1000 by mcap from survivors. Stage 2 was committed (three commits per the handoff's suggested groupings) before Stage 3 began.

The session opened with one design issue worth surfacing before code: the corrected ordering pins universe size at N=1000 by construction, so the Stage 2 outline's two-panel diagnostic (universe size + turnover) was partially obsolete. Universe size is no longer a meaningful comparison metric across (X, Y) settings, so something else has to do that work. Confirmed with the user, the diagnostic was redesigned to three panels (liquidity, market cap, turnover) before code was written.

---

## Stage 3 thesis

The earlier two stages produced data; Stage 3 produces a decision. Stage 1 gave us per-date candidate sets (the universe of stocks meeting basic eligibility). Stage 2 gave us the trailing-20-day liquidity panel (a per-stock-per-date measure of trading activity). Stage 3 joins these and applies the hybrid floor to produce universe membership.

The architectural principle of Stage 3 is composition, not new data work. There are no API calls, no caches to manage, no network resilience to engineer. The script is pure pandas orchestration: load, filter, sort, take, write. Total runtime is under a minute even with the diagnostic plots. This is what well-designed infrastructure looks like at the layer above the data layer: the heavy lifting (Stages 1 and 2) is upstream, and the decision layer is fast and re-runnable.

The design correction noted at end of Stage 2 was the substantive content of Stage 3. The original ordering (bottom-1000 first, then liquidity filter) reproduced the variable-universe-size problem Stage 2 was meant to address. The corrected ordering (liquidity filter on full set first, then bottom-1000 by mcap) makes universe size invariant by construction and isolates the (X, Y) decision to a composition question rather than a size question.

---

## Codebase changes

**New file:**

`universe_membership.py` (Stage 3 driver). Five named passes (`load_inputs`, `build_universe_for_date`, `build_universe_all_dates`, `write_membership`, `plot_diagnostic`) plus a `run_pipeline` orchestrator and a CLI driver. Schema validation on load (frozenset patterns reused from Stage 2) for both `liquidity_panel.csv` and the per-date `candidates_*.csv` files. Cross-checks that panel dates and candidate dates match exactly, raises with a clear message if not.

The core selection logic lives in `build_universe_for_date`. Three substantive design choices are encoded:

1. The liquidity percentile is computed within `panel_R` (the panel restricted to date R), not within `candidates_R`. The base population for a percentile filter has to be the population the filter is reasoning about. `panel_R` represents stocks that actually traded; `candidates_R` includes stocks that may have been suspended for the entire window and have no liquidity to rank.

2. The liquidity-survivor set is then inner-joined with `candidates_R`. The inner-join is the right operator because the universe should be the intersection of "tradable" (per panel) and "eligible" (per Stage 1 filters). A left-join from candidates would include suspended stocks; a left-join from survivors would include ineligible stocks (B-shares, ST, listing-age violations).

3. The output keeps all candidate rows with an `in_universe` flag rather than just universe members. Cost is negligible (~250K rows × 6 cols), value is downstream auditability of the universe boundary (near-miss analysis, cap-rank distribution, etc.).

**No modifications to prior-stage scripts.** Stage 1 and Stage 2 outputs are consumed read-only.

---

## Stage 3 output

`data/universe_membership_X{X}_Y{Y}.csv` for each of the three sweep pairs, plus the canonical `data/universe_membership.csv` (a copy of the chosen X=80, Y=1500 file). Each contains 250,862 rows. Columns:

- `rebalance_date` (string, YYYY-MM-DD)
- `ts_code` (string, Tushare format)
- `in_universe` (boolean; True for the 1000 selected stocks per date, False for the rest of the candidate set)
- `mean_amount_wan` (float, from Stage 2 panel; NaN if stock was absent from panel for date R)
- `circ_mv_yi` (float, from Stage 1 candidates)
- `rank_by_mcap` (int, ascending rank within candidates_R by `circ_mv_yi`; 1 = smallest cap candidate)

Headline numbers per pair, at median across the 52 dates:

- (X=80%, Y=1500): 3927 liquidity survivors, 1000 universe members, 23.8% inter-date turnover
- (X=80%, Y=2500): 3919 liquidity survivors, 1000 universe members, 24.2% inter-date turnover
- (X=70%, Y=2000): 3436 liquidity survivors, 1000 universe members, 28.1% inter-date turnover

Diagnostic plots (`data/universe_membership_X{X}_Y{Y}_diagnostic.png`): three panels each. Top panel is mean and median trading amount of universe members per rebalance date with horizontal reference at Y. Middle panel is mean and 95th percentile `circ_mv_yi`. Bottom panel is inter-date turnover with median annotated.

Total Stage 3 wall time: under a minute for all three sweep candidates. No API calls.

---

## Conceptual ground

**The base population for a percentile filter has to match the population the filter is reasoning about.** Stage 3 computes the liquidity percentile within `panel_R`, not `candidates_R`. The choice of base population is a substantive design decision, not a notation detail. Computing within `candidates_R` would have meant ranking stocks against a population that includes stocks suspended for the entire window with no liquidity to rank. This pattern recurs anywhere a relative threshold is applied; the question "rank within what?" precedes the choice of percentile cutoff.

**Composition-stability is the right diagnostic when size is fixed.** The corrected Stage 3 ordering pins universe size at N=1000 by construction. The empirical question shifts from "which (X, Y) gives stable universe size?" to "which (X, Y) gives the right cap and liquidity composition tradeoff?" This is why the diagnostic plot was redesigned. When a design choice fixes one degree of freedom, the diagnostic for choosing among parameter settings has to move to the remaining degrees of freedom.

**Two-gate filters with inner-join.** Universe construction layered Stage 1's candidate eligibility (A-share, non-ST, listing age, mcap available) and Stage 2's liquidity (relative + absolute) using an inner-join. Each gate catches a distinct failure mode: candidate gate catches non-A-shares, ST stocks, listing-age violations; liquidity gate catches suspended stocks and below-floor trading volume. The pattern generalizes: when filters are independent and we want intersection, inner-join is the operator; if we ever want union (some failures forgivable if others compensate), join semantics change accordingly.

**A near-inert parameter still has design value.** Y=1500 affects ~8 stocks per date out of 3927 survivors in the current sample, virtually none at the bottom-1000 boundary. The relative filter X carries the load. But Y is kept in the design as a stress-regime guard: in a hypothetical 2015-H2-style liquidity collapse where the absolute distribution implodes, the relative filter still admits stocks that are absolutely untradable, and Y is the design's protection against this. Parameters are evaluated on what they protect against, not just on what they currently do.

---

## Misconceptions corrected

**"Bottom-1000 by mcap first, then liquidity filter."** Wrong, and corrected by the Stage 2 bridge before Stage 3 began. This ordering reproduces the variable-universe-size problem because in stress regimes many of the 1000 smallest stocks fail the liquidity rule. The corrected ordering applies the regime-stable liquidity rule to the full ~5000-stock candidate set first, then takes bottom 1000 from survivors. Universe size is then exactly 1000 every month.

**"The relative-floor and absolute-floor decisions are separable."** Misleading. They look like two independent design choices but jointly determine universe size and tradability. The relative cut alone fails on tradability in stress regimes; the absolute cut alone fails on regime stability. The pair (X, Y) has to be chosen jointly rather than sequentially.

**"Y=2500 is meaningfully more aggressive than Y=1500."** Empirically false in the current sample. The two pairs differ by ~8 stocks per date, virtually none at the universe boundary. The intuition that doubling the absolute floor doubles its effect breaks because the relative filter is doing the upstream work; Y only bites on stocks that already cleared the percentile cut and sit below the absolute threshold, which is a small set in most regimes.

**"The original two-panel diagnostic from the Stage 2 outline still works after the ordering correction."** Wrong. Universe size becomes a constant 1000 under corrected ordering, so the size panel becomes a flat line and the "variance around X% target" comparison is undefined. The redesign to three panels (liquidity / cap / turnover) was a forced move, not a stylistic preference.

---

## Habits built or reinforced

**Reading parameter sweeps for empirical structure, not just to pick the best.** The (80%, 1500) vs (80%, 2500) comparison surfaced that Y is near-inert in the current sample. That's a structural finding about the design, not a noise observation. Sweep results are diagnostic of the design space, not just inputs to a selection.

**Schema validation on cache load, applied at every stage.** Stage 2's `EXPECTED_CANDIDATE_COLUMNS` pattern carried directly into Stage 3 as `EXPECTED_LIQUIDITY_PANEL_COLUMNS` and `EXPECTED_CANDIDATE_COLUMNS_MIN`. Five lines per data source eliminate a class of cache-staleness bugs permanently.

**Surfacing design corrections before coding.** The Stage 2 bridge flagged corrected ordering but did not fully spell out the diagnostic-plot consequence. Catching that before code was written saved a write-then-rewrite cycle. Pattern: when implementing a handoff, re-read the bridge and check whether any documented decision has unstated downstream implications.

**Output files that support boundary analysis.** Keeping all candidate rows with an `in_universe` flag rather than just universe members costs little storage and substantial future analytical optionality (near-miss analysis, cap-rank inspection, sensitivity to threshold perturbation without re-running Stage 3).

---

## Open items carried forward

**Immediate next step within Project 5: scope the next session.** The infrastructure arc closes here. The next direction is open and should be scoped at the start of the next session. Categories the universe now enables, not committed to any specific order:

- Cross-sectional descriptive analysis of the universe: cap distribution evolution, sector composition over time, turnover concentration, whether the universe drifts toward any particular sector under stress
- Universe-conditional return panel construction: compute forward returns to next rebalance for each universe member; this is the structural step that bridges to Project 6 factor research and could be done late in Project 5 to validate the universe's behaviour before factor work
- Sub-universe construction: sector-neutral subsets, size-tercile splits within the bottom-1000, regime-conditional subsets (pre/post 2024-Q3 stimulus)
- Liquidity profiling: where universe members sit on liquidity relative to the broader market, dispersion of trading amount within the universe, whether the universe's liquidity profile makes specific position-sizing constraints tractable

The choice of direction depends on whether the next session focuses on understanding the universe in its own right or on accelerating toward Project 6.

**Resolved by Stage 3 (closing items from Stage 2 handoff):**

- Stage 3 hybrid floor selection: chosen as (X=80%, Y=1500万)
- Liquidity floor regime sensitivity: encoded into the hybrid design and quantified in the Stage 3 diagnostic plots

**Still open and deferred (carryforward to Project 6 unless prioritized in next Project 5 session):**

- Point-in-time name resolution via `pro.namechange()`. Current ST filter uses present-day names. The NaN-name warning surfaces unresolvable rows but does not catch stocks renamed historically. Soft look-ahead that biases factor work; should land before Project 6 Session 1.
- NaN-name warning behaviour audit. Inspect what the warning actually fires on across a sample of dates. Confirm it catches real cases (ST-renamed, recently de-listed) rather than only edge-case unresolvable codes.
- `project1_utils.py` consolidation. Helper functions still per-session; lift to a shared module before factor work.
- Limit-hit detection utility. Deferred since Project 1 then Project 2. Handles ±10% main board and ±20% 创业板/科创板. Every factor study using daily returns needs this.
- Crisis-regime validation. The 2022-2026 sample contains no 2015-H2-style liquidity collapse. Conclusions about diversification and factor returns are conditional on the regime of the sample.
- Y absolute floor stress-regime test. Y is near-inert in current sample. Stress test via synthetic data, or wait for natural stress regime.

**Pending commits.** All Stage 3 work is uncommitted. Suggested groupings:

1. `Stage 3: universe membership script and parameter sweep` — `universe_membership.py` plus the three sweep CSVs and three diagnostic PNGs.
2. `Stage 3: select (X=80%, Y=1500万) as canonical small-cap universe` — `universe_membership.csv`, `universe_membership_diagnostic.png`, and this handoff document.

---

## Bridge to next session

The infrastructure arc of Project 5 closes with this handoff. The universe file (`data/universe_membership.csv`) is the canonical reference for everything downstream within Project 5 and into Project 6.

The next session is a scoping conversation rather than a pre-determined implementation session. Three reasonable openings, listed without ordering:

**Universe descriptive analysis.** Open the universe and look at it. Cap distribution histograms, sector composition over time, sector concentration metrics, whether the bottom-1000 drifts toward specific industries under regime change. This is the natural first move if the goal is to understand what was built before using it for factor research. Connects to Brooks Ch1 on descriptive statistics and Tsay Ch1 on time-series properties of returns.

**Universe-conditional return panel.** The structural step that bridges Project 5 infrastructure to Project 6 factor research. Load `universe_membership.csv`, restrict to `in_universe == True` per rebalance date, compute forward returns to the next rebalance for each universe member. Produces the (rebalance_date × ts_code) → forward_return panel that all factor work will run on. Could be done late in Project 5 as a validation step on the universe's behaviour, or kept for Project 6 Session 1.

**Universe behaviour analysis.** Look at how the universe itself moves: turnover patterns by month, what kinds of stocks exit between rebalances, sector composition of exits, whether membership churn correlates with regime variables (volatility, liquidity, index returns). This is closer to the universe-as-object-of-study framing and would surface any pathologies in the construction before factor work amplifies them.

Suggested next conversation name: `2026-04-26 — Project 5 Session [N]: [scope of next session]` (specific scope to be set when the next session opens).
