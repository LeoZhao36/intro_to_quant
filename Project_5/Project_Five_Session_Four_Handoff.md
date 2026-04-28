# Project 5 Session 4 Handoff: Universe Descriptive Analysis (Option 1)

**Completed:** 2026-04-26
**Project location:** Phase 3, Project 5, post-infrastructure descriptive arc
**Status:** Option 1 complete (cap distribution + sector composition). Option 2 (universe-conditional return panel) is the next session, scoped but not started. Option 3 (universe behaviour) follows Option 2 in a third session.

---

## Key takeaways

The bottom-1000 universe drifted asymmetrically over 2022-01 to 2026-04. P5 cap more than doubled (+105%), P95 grew only +30%. The floor of "small-cap" moved up much faster than the ceiling. Eye reads on linear-axis plots do not catch this; coefficient of variation does (P5 CV = 0.34 vs P95 CV = 0.19, P5 nearly 2x more relatively variable).

Sector composition shifted in patterns the static comparison hides. Multiple "growth" sectors (`机械设备`, `电子`) had non-monotonic peak-and-recede trajectories rather than monotonic drift, peaking in mid-to-late 2024 and receding since. Several sectors shrank consistently (`食品饮料` halved, `建筑装饰` -9, `美容护理` halved, banks and 非银金融 essentially exited). Net concentration rose modestly (HHI 0.057 → 0.062, mean 0.065).

The 申万 hierarchy has partial point-in-time correctness. Tushare's `index_member_all` returns each stock's *current* classification with `in_date`, but does not retain historical classifications a stock has left (`out_date` is uniformly null in our pull). The 未分类 bucket (104 at 2022-01-17 → 2 by 2026) absorbs this, and the limitation must be carried forward as a known caveat for sector-conditional factor work in Project 6.

The infrastructure now in place: 申万 hierarchy + membership cached locally, partial point-in-time resolution function applied, two visualizations (interactive treemap + static line chart) saved as reusable diagnostics.

---

## Reference conversations and documents

- `2026-04-26 — Project 5 Session 4: Universe Descriptive Analysis (Option 1)` (this session)
- `Project_Five_Stage_Three_Handoff.md` (predecessor; closes Project 5 infrastructure arc and lists Options 1/2/3 as scoping options)
- `Project_5/inspect_universe.py` (load-and-inspect for `universe_membership.csv`)
- `Project_5/descriptive_cap_distribution.py` (cap percentile evolution + plot)
- `Project_5/sw_industry_pull.py` (申万 hierarchy and membership pull, smoke + full modes)
- `Project_5/sw_sector_panel.py` (interactive Plotly treemap)
- `Project_5/sw_sector_lines.py` (static matplotlib line chart of L1 trajectories)
- `Project_5/data/sw_classification.csv` (511 rows: 31 L1 + 134 L2 + 346 L3)
- `Project_5/data/sw_membership.csv` (5834 rows: ts_code → l1/l2/l3 with in_date)
- `Project_5/data/descriptive_cap_distribution.png`
- `Project_5/data/sw_sector_panel.html`
- `Project_5/data/sw_sector_lines.png`
- Tushare documentation: https://tushare.pro/document/2?doc_id=181 (申万 2021 classification)

---

## Starting point

Entered the session with Project 5 infrastructure closed at Stage 3, `universe_membership.csv` containing 250,862 rows with exactly 1000 stocks flagged `in_universe == True` per rebalance date under the (X=80%, Y=1500万) hybrid floor. The Stage 3 handoff scoped this session as a scoping conversation, not a pre-determined implementation session.

Initial framing in the user's prompt was that "factor testing" was the next step. The handoff actually scoped three options (descriptive analysis, return panel, universe behaviour) and explicitly placed factor testing in Project 6. The session opened with this correction and the user chose "all three options in order, descriptive first," with Option 2 deferred to a follow-up session.

---

## Session thesis

The first descriptive look at a constructed universe is not a "neat thing to know" exercise. It is the diagnostic step that surfaces structural drift, regime sensitivity, and population mixing before any factor sort amplifies them into apparent signals. Three things this session was designed to surface, and did:

1. **Cap drift** — does "small-cap" mean the same thing in 2026 as in 2022? No: the floor doubled in absolute terms.
2. **Sector drift** — has the bottom-1000 changed in composition? Yes, with non-monotonic dynamics that a single before/after comparison would have missed.
3. **Structural exclusions** — what is systematically *not* in the universe? Banks and non-bank financials, by construction. This bounds how we describe Project 6 results: any factor we test is a "non-financial small-cap factor," not a generic small-cap factor.

The methodological theme of the session was scale-versus-shape diagnostics. Linear-axis plots and absolute-magnitude std numbers are systematically misleading when comparing populations on different scales. The coefficient of variation (std/mean) and percentage-change reads correct for scale and surface what visual inspection misses. Same principle as the kurtosis/SD distinction in Project 1 Session 2.

---

## Codebase changes

**New files:**

- `inspect_universe.py` — five-line load-and-inspect of `universe_membership.csv`. Confirmed shape (250,862 × 6), date range, in_universe == 1000 per date invariant.

- `descriptive_cap_distribution.py` — computes P5/P25/P50/P75/P95 of `circ_mv_yi` per rebalance date via `groupby().quantile().unstack()`, plots the five percentiles over time with the 2024-09-24 PBoC stimulus reference line. Output: `data/descriptive_cap_distribution.png`. Pattern worth carrying forward: `groupby(date).quantile([list]).unstack()` is the standard cross-sectional summary idiom and will appear in every Project 6 factor diagnostic.

- `sw_industry_pull.py` — pulls 申万 2021 hierarchy and membership from Tushare. `pro.index_classify(level=...)` for the taxonomy (511 rows total across L1/L2/L3); `pro.index_member_all(l3_code=...)` looped over 346 L3 codes for the membership table (5834 rows). Has smoke and full modes; smoke pulls one L3 first to inspect schema. Network-resilience helper from Stage 2 reused (`_retry_on_network_error`). Cache files at `data/sw_classification.csv` and `data/sw_membership.csv`.

- `sw_sector_panel.py` — interactive Plotly treemap with 52-frame animation slider. Path is `[Bottom-1000, l1_name, l2_name, l3_name]`, sized by stock count, colored by L1. Built using `go.Figure` with frames rather than `px.treemap(animation_frame=...)` because the latter is not supported on hierarchical chart types. Output: `data/sw_sector_panel.html` standalone interactive file (~4.5 MB, opens in any browser).

- `sw_sector_lines.py` — matplotlib companion to the treemap. Plots top-10 L1 sectors by peak count over the 52 dates. Excludes 未分类 from the chart (annotated as a footnote). Output: `data/sw_sector_lines.png`. The treemap shows hierarchy and per-date snapshots; the line chart shows trajectories. They are complementary, not redundant.

**No modifications to prior-stage scripts.** All Stage 1/2/3 code consumed read-only.

**Plotly added to project dependencies.** First use in this project; pure plotting library, no side effects.

---

## Conceptual ground

**Scale-versus-shape, second iteration.** Project 1 Session 2 introduced this in the context of return distributions (SD measures spread, kurtosis measures tail behavior normalized by spread). This session applied it to cross-sectional cap distributions: absolute std of P5 across 52 dates was the smallest in the table (3.12), yet relative std (CV) was the largest (0.34, vs 0.19 for P95). Same trick — small numbers look stable in absolute units while swinging hardest in fractional terms. The CV is the standard fix, with the failure mode noted: undefined near zero, misleading on signed data. For strictly-positive quantities (cap, price, volume), CV is the right tool.

**Counts in a small-cap universe are contrarian to sector strength.** A sector growing in our bottom-1000 count is a sector whose stocks are falling, not rising. Mechanism: rallying stocks cross out of the bottom-1000 (mcap rises above the threshold), slumping stocks cross in. This inverts the naive read of any count-based diagnostic. `电子` peaking at 114 stocks in mid-2024 means small-cap electronics names were getting *cheaper*, not richer. Worth holding in mind for any future count-based analysis.

**Interface shape should match question shape, third iteration.** Stages 1 and 2 built this principle on the Tushare cross-sectional vs per-stock interface choice. Session 4 reinforced it on the 申万 pull: 346 sequential `index_member_all(l3_code=...)` calls is correct (one cross-section per leaf), but a naive per-stock reverse query would have required 5834+ calls. The architectural reflex is now consistent across stages.

**Treemaps and line charts are complements, not substitutes.** The treemap with slider is the right tool for "what does the hierarchy look like at moment X and how does it reorganize over time." The line chart is the right tool for "what was each piece of the hierarchy doing across the full timeline." Either one alone is incomplete. Static line charts catch peak-and-recede patterns that the treemap can show only by careful slider-scrubbing; the treemap shows hierarchical structure that the line chart flattens away.

**Partial point-in-time is honest; pretending to full point-in-time is not.** Tushare's `index_member_all` returns current classification with `in_date`, no `out_date` populated. We can resolve "this stock was in classification C on date R" only when `in_date <= R`. Stocks reclassified after the rebalance date are marked 未分类 rather than guessed. This is the correct response to incomplete data: name the gap, bound its impact, and document the bias. Faking completeness by backfilling current classifications to all historical dates would have introduced silent look-ahead.

---

## Misconceptions corrected

**"`stock_basic.industry` is 申万一级."** Wrong. A community thread on the Tushare GitHub claims this; the actual cache returns 110 categories with names like `全国地产`, `软件服务`, `汽车配件`, `化工原料`, `医疗保健` that do not match 申万 at any level. The cache uses a legacy non-申万 taxonomy (likely an older 同花顺 or Sina-financial scheme). For canonical 申万 we have to use `index_classify` + `index_member_all` directly. The session corrected this by checking actual L1 names against the canonical 2021 hierarchy from Tushare's documentation.

**"申万三级 can be rolled up from the cached `industry` field."** User hypothesis, evidence does not support. The cached field's names do not bridge cleanly to 申万 二级 or 三级 names (e.g., cache has `元器件`, 申万 has `元件`; cache has `化工原料`, 申万 has `化学原料`). The bridging would require a manual mapping table we do not have. Pulling 申万 directly is the right move and was done.

**"`px.treemap(animation_frame=...)` works."** Wrong. Plotly Express animation is supported on flat chart types (scatter, bar, line) but not hierarchical types (treemap, sunburst, icicle). Workaround: build a `go.Figure` with manually-constructed frames and a slider. Documented in the script. Tutor error caught after first run failed; future hierarchical-with-time animations should default to the manual frames pattern.

**"Cap and sector drifted uniformly because the lines look parallel."** Wrong. The user's eye-read of the cap distribution chart was that all five percentile lines drifted up uniformly. The percentage-change calculation showed P5 grew +105% vs P95 +30%, which is the opposite of uniform. Same trick on the sector trajectories — `电子` headline +28 hides the fact that it nearly doubled to 114 by mid-2024 then receded to 85. Static end-to-end comparisons systematically miss non-monotonic dynamics. The fix is always either trajectory plots or careful interim-snapshot comparisons.

**"The 未分类 bucket decline shows real reweighting."** Mostly wrong. The 102-stock decline in 未分类 from 2022-01-17 to 2026-04-15 is the in_date artifact resolving itself, not real sector drift. Stocks classified after their rebalance date were marked unclassified for early dates and become classified later. The real reweighting magnitude is bounded: at most 144 stocks of growth across all growers, of which at least 102 is the artifact, leaving ~42 stocks of genuine drift in the worst case (more in practice because the artifact does not concentrate in one sector). This bound is necessary to prevent overreading the "growth" sectors.

---

## Habits built or reinforced

**Verify before publishing.** The Tushare GitHub thread claiming `stock_basic.industry` is 申万一级 was wrong. The session caught this by cross-checking specific category names against the canonical 2021 hierarchy from Tushare's own documentation page. Source authority is not a substitute for content verification, especially for community-contributed content. Carry-forward: when relying on a single source for a structural claim, run a spot-check against the data the claim is about.

**Smoke-test-then-full pattern.** `sw_industry_pull.py smoke` pulled one L3 first, surfaced the schema (10 columns including denormalized L1/L2/L3 names alongside the leaf), and confirmed the membership table did not require post-hoc joining through the taxonomy. The full pull was then written specifically for the schema that came back. This is the third application of the pattern (Stage 1 used it on `daily_basic`, Stage 2 on `daily`, this session on `index_member_all`). Becomes the default for any new endpoint going forward.

**Diagnostic numbers before plot interpretation.** The treemap rendered, the user observed sector changes, and the response was to extract the underlying L1 counts from the HTML and validate every claim numerically before adding observations. Visual inspection alone systematically misses non-monotonic dynamics and underweights moderate-but-real shrinkers. Pattern: every observation pulled from a chart should be verified against the data it visualizes before being trusted. The numerical verification surfaced patterns the eye missed (`机械设备` peak-recede, `食品饮料` halving).

**Owning errors without over-apologizing.** Two tutor errors this session: (1) claiming `stock_basic.industry` was 申万一级 with 31 categories without verification; (2) using `px.treemap(animation_frame=...)` which is not supported. Both were caught in the next iteration, named clearly in the response, fix delivered. No prolonged apology, no self-abasement, but the error was named and the correction shown. Tutor pattern to maintain.

**Coefficient of variation as the standard scale-corrector for positive data.** Reaches for the right tool automatically now (Project 1 Session 2 introduced this in a different context; Session 4 applied it to cross-sectional caps). Future use: any time we compare variability across groups whose central values differ.

---

## Thesis implications for Project 6

Three concrete implications flow from this session into factor research:

**Sector exposure is not stable across the sample.** A factor tested over 2022-2026 implicitly mixes regimes where `电子` was 6% of the universe with regimes where it was 11%. Any factor that loaded heavily on a single sector would have looked artificially strong in mid-2024 due to position-sizing alone, independent of any factor signal. Project 6 will need either sector-neutral factor construction (residualize the factor on sector dummies) or sector-conditional reporting (factor returns in pre/post stimulus sub-samples), and probably both.

**The universe is structurally non-financial.** Banks have entirely exited the bottom-1000; non-bank financials nearly so. This is permanent, not regime-dependent. All Project 6 results should be described as "non-financial small-cap" findings, not generic small-cap findings.

**Cap-conditional sub-analysis is needed.** P5 (~16亿 by 2026-04) and P95 (~43亿 by 2026-04) within "the same universe" are structurally different populations: different liquidity profiles, different retail/institutional ownership, different sensitivity to single events. Factor sorts inside this universe will likely behave differently across sub-buckets. Project 6 should test factors not just on the bottom-1000 as a single basket but on terciles of the universe by cap, and report results separately. A factor that works on the top tercile (~33-43亿) but not the bottom tercile (~16-25亿) is not a "small-cap factor" — it is a "near-mid-cap factor" misclassified.

---

## Open items carried forward

**Immediate next session: Option 2, universe-conditional return panel.** Six parts in build order:

1. Limit-hit utility in `project1_utils.py`. Board-aware (±10% main, ±20% 创业板/科创板, ±5% ST). Detection: `close == round(prev_close * (1 + limit_pct), 2)` within tolerance. ~25 lines including board classifier.

2. 前复权 price pull via `pro.adj_factor()` cross-sectionally per trading day, not per stock. Architecturally consistent with Stages 1 and 2.

3. Forward return computation: `forward_return = close_qfq[R+1] / close_qfq[R] - 1` for each (R, ts_code) in universe, R+1 = next rebalance date.

4. Tradability flags: apply limit-hit utility on R and R+1, set `entry_tradable` (false if 涨停 or suspended on R) and `exit_tradable` (false if 跌停 or suspended on R+1). Suspension detection: missing row in `daily` cross-section.

5. Delisting handling: drop stocks delisting between R and R+1, flag `delisted_in_window`, log count per date.

6. Diagnostic plot: cross-sectional forward-return distribution per rebalance date with mean and ±2σ bands, stimulus reference line, side bar with `entry_tradable == False` and `exit_tradable == False` rates. The phantom-return rate is the headline number for Project 6.

Architectural budget: ~106 API calls (52+1 unique trading days × 2 endpoints). Wall time under 5 minutes. Practice budget: 3-4 hours including the limit-hit utility build, the design discussions, and the diagnostic interpretation.

Output: `data/forward_return_panel.csv` with columns `(rebalance_date, ts_code, forward_return, days_held, entry_tradable, exit_tradable, delisted_in_window, in_universe)`. This is the file Project 6 will consume.

**Following session: Option 3, universe behaviour.** Membership churn between consecutive rebalances, exits by sector, churn-vs-regime correlation. Reads `universe_membership.csv` plus the panel from Option 2. Should follow Option 2 in a third conversation.

**Resolved by this session (closing items from Stage 3 handoff):**

- Sector composition descriptive analysis: complete. Treemap and line chart artifacts produced.
- Cap composition descriptive analysis: complete. P5/P25/P50/P75/P95 evolution plot produced.
- Point-in-time name resolution carryforward: PARTIAL. The `pro.namechange()` issue is unresolved. The 申万 hierarchy got partial point-in-time resolution via `in_date` (better than nothing, not full). The ST/name resolution problem remains and should land before Project 6 Session 1.

**Still open and deferred to before Project 6 Session 1:**

- Limit-hit detection utility, will be built in next session as part of Option 2.
- `project1_utils.py` consolidation, will be created in next session as the home for the limit-hit utility.
- Point-in-time ST name resolution via `pro.namechange()`. Soft look-ahead in the ST filter.
- Crisis-regime validation. The 2022-2026 sample contains no 2015-H2-style liquidity collapse; conclusions are conditional on the regime of the sample.
- Hierarchical 申万 point-in-time gap. `out_date` is uniformly null in `index_member_all`, so historical reclassifications cannot be recovered. Document as a known limitation; if a sector-neutral factor study in Project 6 needs full point-in-time correctness, consider 中信 industries (`pro.ci_*`) or 东方财富 industries as alternative sources to cross-check.

**Pending commits.** All Session 4 work is uncommitted. Suggested groupings (the user has expressed preference for batched commits at end of session, consistent with Stage 2):

1. `Session 4: descriptive cap distribution analysis` — `inspect_universe.py`, `descriptive_cap_distribution.py`, `data/descriptive_cap_distribution.png`
2. `Session 4: 申万 hierarchy pull and cache` — `sw_industry_pull.py`, `data/sw_classification.csv`, `data/sw_membership.csv`
3. `Session 4: interactive sector treemap and line chart` — `sw_sector_panel.py`, `sw_sector_lines.py`, `data/sw_sector_panel.html`, `data/sw_sector_lines.png`
4. `Session 4: handoff document` — this file at the project root.

The `.csv` cache files are large enough to be worth a `.gitignore` decision: keep in repo (deterministic from API but slow to re-pull, ~70-90s for full membership pull) or exclude (cleaner repo, but anyone reproducing has to re-pull). Recommend keeping `sw_classification.csv` (511 rows, tiny, taxonomy is stable) and `sw_membership.csv` (5834 rows, ~500KB, useful as the project's frozen-in-time reference). The 4.5MB `sw_sector_panel.html` could go either way; recommend keeping for shareability.

---

## Bridge to next session

Open the next conversation with the limit-hit utility. The discussion at end of Session 4 covered why this utility is necessary in plain language (phantom returns from 涨停/跌停 days that no real trader could capture), and the build is scoped at ~25 lines. The natural opening: "Build the limit-hit utility, validate on a known case (e.g., a 2024 stimulus-day winner that hit 涨停), commit, then proceed to the price pull."

The limit-hit utility belongs in `project1_utils.py` (a module that does not yet exist; it will be the consolidation point that closes the helper-function carryforward from Project 1). The function signature should be `limit_state(close, prev_close, ts_code, name) -> Literal["normal", "limit_up", "limit_down"]` with the board classifier as a private helper. ST detection from name prefix (`ST` or `*ST`).

Validation case to use: pick a stock from the universe on a date that is known visually (for instance, find a `entry_tradable == False` candidate in the bottom-1000 around 2024-09-26 to 2024-09-30 when many stimulus-day winners hit 涨停).

After the limit-hit utility lands, proceed through Parts 2-6 of Option 2 in order. Single session if focused; two sessions if the design discussions go deep.

Suggested next conversation name: `2026-04-27 — Project 5 Session 5: Universe-Conditional Return Panel (Option 2)`.

The Option 3 session, in turn, opens once the return panel is in place. Suggested name when that time comes: `2026-04-?? — Project 5 Session 6: Universe Behaviour and Membership Churn (Option 3)`.
