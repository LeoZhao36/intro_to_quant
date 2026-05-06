# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A personal **learning project** for Chinese A-share quantitative finance, not a shipped codebase. The student is a humanities-background learner building quantitative trading skills through a project-based curriculum. The curriculum document is `quant_learning_plan.jsx` at the repo root (a React artifact, not meant to run here).

Work is organized into sequential **Projects** (`Project_0` through `Project_6`), each containing sequential **Sessions** (Jupyter notebooks, or scripts from Project 5 onward) plus per-stage / per-session `*_Handoff.md` files and one `*_Closeout.md` at project end. **These markdown files are the primary record of intent and reasoning — read them before modifying a project's code.**

**Active workspace:** `multi_factor_x1/` at the repo root. This is a post-Project-6 workspace for universe redesign and reversal/turnover factor research; it is not numbered as a Project because it cuts across several factor questions opened by the Project 6 closeout. Recent commit history (turnover construction → turnover-neutralized analysis → reversal analysis → turnover/reversal combination + filters) lives entirely in this folder.

**Curriculum status (revised 2026-04-26 in `Project_5/Project_Five_Closeout.md`):** Phase 3 was reorganized. Original "Project 5: Size Factor" + "Project 6: Multi-Factor" merged into:
- Project 5 = **Universe Construction** (closed 2026-04-26)
- Project 6 = **Factor Testing** — size, value, momentum, low-vol, multi-factor, cost-adjusted (closed; see `Project_6/Project_6_Comprehensive_Closeout.md`)
- Phase 4 (Project 7 Backtester, Project 8 Strategy Evaluation) unchanged.

## Pedagogical rule (read this before any substantive work)

This is a learning project, and the learning depends on the student understanding what is being built and why. Claude Code's role is **execution once concepts are clear**, not concept introduction.

- Before writing code that introduces a new statistical concept, factor definition, backtesting principle, or market mechanism the student has not yet encountered, stop and flag it. Concept introduction happens in the claude.ai chat interface, not here.
- If you find yourself wanting to explain *why* a factor works, *why* a test applies, or *what* a market mechanism means, stop and suggest the student take the question to claude.ai. Return to execution once the conceptual groundwork has been laid there.
- Exceptions: Python syntax, pandas operations, Tushare/baostock API quirks, matplotlib details, standard library usage, debugging assistance, and other purely technical matters are yours to handle freely. The rule covers financial and statistical concepts, not programming.

The complementary division: **claude.ai chat owns the "what" and "why"; Claude Code owns the "how" and "did it run"**. When the student asks you for execution help after a concept discussion, proceed normally. When they ask you for the concept discussion itself, redirect.

## Session handoff workflow (source of truth)

Handoffs and closeouts are the source of truth for "what was decided and why." They live **inside each project directory** (no top-level `handoffs/` folder), e.g. `Project_5/Project_Five_Stage_Three_Handoff.md`, `Project_6/Project_6_Universe_Rebuild_Handoff_Final.md`, `Project_6/Project_6_Comprehensive_Closeout.md`. Before starting any task in a project, read the most recent handoff or closeout in that project's directory.

For `multi_factor_x1/`, there is no handoff document — orient by reading `multi_factor_x1/config.py` (shared constants) and the most recent commit messages, then the script that the current task touches.

- Do not build infrastructure ahead of the curriculum sequence. If a future session will build something differently, wait for that session.
- Do not create new top-level planning, summary, or architecture documents. The student maintains these manually per session.
- When the student references a prior session, project, or decision, read the corresponding handoff rather than reconstructing from notebook code.

## Thesis state

**小盘股 is a universe scope, not a factor.** This was the Project 5 framing and Project 6 confirmed it empirically: log market cap does not predict forward returns within the bottom-1000 liquid A-share universe (headline Q1−Q5 t≈0.39, CI containing zero on the rebuilt 380-week panel).

**Project 6 empirical results (post-closeout, 2026-04-30):**
- **Size**: clean null within the universe.
- **Value (EP)**: strongest single signal. Headline t=−2.83, IC +0.0317, sector-neutral t=−5.04. Concentrates in low-cap and mid-cap terciles.
- **Short-horizon momentum (mom_4_1, ~1-month formation)**: universal-cap signal. Q1−Q5 +0.528%/wk at t=+4.84, all three cap terciles BH-reject. Mechanism = retail overreaction-then-correction at ~1-month horizon.
- **Low-vol**: IC-significant but Q1−Q5 null.
- **FMB**: only `z_mom` survives multivariate. `z_value` evaporates because the value premium lives in the cheapest tail (Q5), not linearly across EP.
- **Cost-adjusted reality**: at realistic retail costs (0.32% RT, 2% limit-down penalty), mom_only Sharpe falls 1.11 → 0.84, segmented composite ≈ baseline. **The only durable tradable edge is a regime gate** — exit to cash when 12-week trailing universe Sharpe > +1.5 annualized adds ~+0.4 Sharpe across all panels including passive baseline.

**Current `multi_factor_x1/` framing**: with size as confirmed null and momentum/value as the established positives, the open questions are (a) does the universe definition itself bias these results — hence the seven-universe inspection (U1–U7) and three-universe pipeline (A/B/C) in `multi_factor_x1/`; (b) do retail-microstructure factors (raw turnover, short-horizon reversal, turnover-neutralized reversal) survive the same robustness machinery on a redesigned universe.

## Universe definitions

**Project 6 canonical (`Project_6/data/universe_membership_X75_Y3000.parquet`):** at each weekly Wednesday rebalance:
1. A-share equity, prefixes `60.SH`, `68.SH`, `00.SZ`, `30.SZ` (excludes 北交所, B-shares, ETFs, indexes)
2. Exclude ST / *ST (point-in-time via `pro.namechange()`)
3. Exclude 退市 / 退市整理期
4. **60-day** trailing mean daily 成交额 floor: top 75% percentile **AND** absolute ≥ 3000万 RMB **AND** ≥ 20 observed days in the 60-day window
5. Sort ascending by 流通市值, take bottom 1000

Sample window: 2019-01-09 to 2026-04-29, weekly Wednesday rebalance, 381 dates. This is the canonical file consumed by every Project 6 downstream analysis.

**`multi_factor_x1/` seven-universe inspection** (`multi_factor_x1/config.py: UNIVERSE_KEYS`): U1=all eligible A-share, U2=Project 6 universe, U3=中证1000, U4=中证2000 (post 2023-08-11), U5=U3∪U4, U6=outside CSI300∪CSI500, U7=U6 + same 75/3000/20 floor as U2.

**`multi_factor_x1/` three-universe pipeline** (post-decision, `THREE_UNIVERSE_KEYS`): A=U6 clean (sub-new excluded, no floor), B=A+price floor ≥ 1.5元 (defends against 面值退市), C=A+relaxed liquidity floor (default `LiquidityFloorParams(pct=0.40, abs=2000万, days=20)`).

Sub-new IPO exclusion threshold: **120 trading days** since listing (≈ 6 months).

## Environment

- Python **3.14.3** in `.venv/` at the repo root. On Windows, activate with `.venv\Scripts\activate` (PowerShell: `.venv\Scripts\Activate.ps1`).
- Dependencies installed ad-hoc, not pinned. Core stack: `tushare`, `baostock`, `pandas`, `numpy`, `pyarrow`, `matplotlib`, `statsmodels`, `jupyter`, `python-dotenv`. No `requirements.txt` or `pyproject.toml`.
- Shell is bash on Windows — use Unix paths and `/dev/null`, not PowerShell syntax (PowerShell is also available via the dedicated tool).
- `.env` at repo root holds `TUSHARE_TOKEN` (gitignored). The token is loaded via `dotenv` by `Project_5/tushare_client.py`, which walks up from its location to find the `.env` and exposes a module-level `pro = ts.pro_api(...)` singleton.

## Running things

- **Notebooks (Projects 0–4):** open `Project_N/Session_*.ipynb` in Jupyter. Each notebook is meant to be executed top-to-bottom within its own project directory so the relative `data/` cache resolves.
- **Scripts (Project 5, 6, multi_factor_x1):** all paths in these scripts are relative; **CWD must be the script's own directory**. Examples:
  - `cd Project_5 && python tushare_build_universe.py`
  - `cd Project_6/Factor_Analysis_Weekly_Universe && python factor_panel_builder.py`
  - `cd multi_factor_x1 && python build_universe_panel.py`
  Scripts in `multi_factor_x1/` import `config.py` from the same directory and read parquet caches under `data/` and `daily_panel/` relative to CWD; `multi_factor_x1/config.py` also reads Project 6 outputs via `../Project_6/data/...` so running from anywhere else breaks the relative paths.
- **Smoke tests:** modules with test coverage expose `execute_smoke_tests()` and/or run tests under `if __name__ == "__main__":`. Run with `python Project_N/utils.py` or `python Project_3/risk_toolkit.py`. There is no pytest setup; do not introduce one unless asked.

## Per-project layout convention

Every project is **self-contained and duplicative by design**. Each `Project_N/` (and `multi_factor_x1/`) has its own `config.py` or `utils.py`, often its own `plot_setup.py`, its own `data/` cache, and often its own local copy of `hypothesis_testing.py` or `factor_utils.py`. **Do not refactor common code into a shared top-level package unless the student explicitly asks** — the forward-copying is pedagogical (each project re-derives what it needs, sometimes with a refined definition).

Notable canonical-but-still-local copies:
- Cleaned-up risk toolkit: `Project_3/risk_toolkit.py`
- Hypothesis testing module (promoted from Project 4 notebooks during Project 6 Phase A): `Project_6/Factor_Analysis_Weekly_Universe/hypothesis_testing.py`; `multi_factor_x1/hypothesis_testing.py` is a trimmed port.
- Parametric factor framework: `Project_6/Factor_Analysis_Weekly_Universe/factor_utils.py` + thin per-factor scripts (`size_analysis.py`, `value_analysis.py`, `momentum_analysis.py`, `lowvol_analysis.py`, `composite_segmented.py`).
- Universe construction stages: `Project_6/New_Universe_Construction/stage{1..5}_*.py`.

When adding code, prefer extending the active workspace's existing files over reaching across projects.

## Data sources: Tushare Pro (current) and baostock (legacy)

**Tushare Pro** has been the canonical data source since Project 5 Stage 1 (2026-04-25). Project 5 switched after baostock projected to ~24 hours of runtime over 52 monthly rebalances; Tushare's cross-sectional `daily_basic` endpoint reduced the same job to ~2.8 minutes (500× speedup). Use Tushare for any new data work.

**Tushare conventions:**
- Authenticate via `from tushare_client import pro` (in `Project_5/`) or `from config import ...` paths in `multi_factor_x1/`. The `pro` singleton handles auth on first import.
- Cross-sectional endpoints (`pro.daily_basic`, `pro.daily`, `pro.adj_factor`, `pro.stk_limit`, `pro.namechange`, `pro.index_weight`) accept `trade_date='YYYYMMDD'` and return the full A-share cross-section in one call. Always prefer cross-sectional over per-stock loops.
- Rate limits exist; high-volume loops use threaded concurrency (Project 6 daily panel pull: ~50 minutes for 2,018 daily parquets) and a `_retry_on_network_error` decorator (defined in `Project_5/liquidity_panel.py`) for occasional `ReadTimeout`.
- **Adjusted prices via the adj_factor route, not via baostock-style `adjustflag`.** Compute forward-adjusted ratios as `(close[t+1] × adj_factor[t+1]) / (close[t] × adj_factor[t]) - 1`; the `latest_adj_factor` cancels.
- **Tradability flags come from `pro.stk_limit`**, not from a computed limit price. Do not reintroduce the abandoned `_round_half_up` limit-price reconstruction from Project 5 Session 5.
- Tushare returns `amount` in **千元** (thousands of yuan). Convert to 万元 by ×0.1, to 亿元 by ×1e-5. `circ_mv` is in 万元; ×1e-4 to get 亿元. Constants in `multi_factor_x1/config.py`: `AMOUNT_QIANYUAN_TO_WAN`, `AMOUNT_QIANYUAN_TO_YI`, `CIRC_MV_WAN_TO_YI`.

**baostock conventions** (still relevant for Projects 0–4 code):
- Every query requires `bs.login()` before and `bs.logout()` after. The helpers wrap this in `try/finally`; preserve that pattern.
- Everything returned as strings. Always `pd.to_numeric(..., errors='coerce')` OHLCV and `pd.to_datetime` the date column.
- `adjustflag`: `'2'` = 前复权 (default), `'1'` = 后复权, `'3'` = unadjusted. Stay on `'2'` unless stated otherwise.
- `tradestatus == '1'` is normal trading, `'0'` is suspended (reverse of intuitive).
- For threaded baostock loops, log in **once per worker thread**, not once per task — see the auto-memory note `feedback_baostock_threading.md`. 8 workers is the safe default.

### Caching convention

- **Tushare scripts (Project 5+, multi_factor_x1):** parquet keyed by date, e.g. `multi_factor_x1/daily_panel/daily_2024-09-25.parquet`. One file per trade_date. Resume by checking which dates already have a cache file. Validate row-count or last-date on load (per auto-memory `feedback_cache_validation.md`) — mid-write failures otherwise produce silently biased downstream results.
- **baostock scripts (Projects 0–4):** CSV keyed by `(code, start, end, adjust)` — e.g. `sz_000001_2024-01-01_2024-12-31_qfq.csv`. `load_or_fetch()` in `Project_2/utils.py` and `Project_4/utils.py` is the canonical wrapper. Changing the date range produces a new file; the cache does not merge partial ranges. Do not "fix" this.

## A-share domain facts encoded in the code

These numbers and rules are baked into helpers. Honor them when writing new analysis:

- **Trading days per year:** **242** in Projects 0–5 (`np.sqrt(242)` for vol, `* 242` for annual mean). **250** in Project 6 and `multi_factor_x1` (`config.TRADING_DAYS_PER_YEAR = 250`, weekly periodicity uses `PERIODS_PER_YEAR = 52`). Use whichever the surrounding project uses; do not unify.
- **Stock code prefixes:**
  - `60xxxx`, `68xxxx` → 上交所 (主板 / 科创板). In Tushare format: `XXXXXX.SH`. In baostock: `sh.XXXXXX`.
  - `00xxxx`, `30xxxx`, `301xxx` → 深交所 (主板 / 创业板). Tushare: `XXXXXX.SZ`. Baostock: `sz.XXXXXX`.
  - `8xxxxx`, `4xxxxx`, `92xxxx` → 北交所. **Excluded from every universe** (BSE has ±30% limits, ¥500k retail suitability, cannot be assumed retail-tradable).
- **A-share equity universe filter** (`multi_factor_x1/config.A_SHARE_PATTERN = r"^(60|68)\d{4}\.SH$|^(00|30)\d{4}\.SZ$"`, also `Project_5/tushare_build_universe.py`): keep only `60.SH`, `68.SH`, `00.SZ`, `30.SZ`. Everything else excluded.
- **Size measure:** always **流通市值** (free-float market cap), never 总市值. From Tushare: `circ_mv` field on `daily_basic` (in 万元). The earlier baostock-derived identity `流通股本 = volume / (turn / 100)` then `float_mcap = close × 流通股本` was found in Project 5 Stage 1 to combine adjusted prices with current shares (median 0.7% error, tails > 200% on stocks with recent corporate actions); **prefer Tushare `circ_mv` over the derivation**.
- **Price-limit (涨跌停) percentages** (`_get_board_limit` in `Project_3/risk_toolkit.py`; `multi_factor_x1/config.py: LIMIT_PCT_*`):
  - 主板: ±10%
  - 创业板 (`300`/`301`), 科创板 (`688`): ±20%
  - 北交所: ±30%
  - ST/*ST: ±5% on Main, **rises to ±10% on 2026-07-06** per CSRC.
  - **创业板 ±20% effective 2020-08-24** (`config.CHINEXT_REGIME_CHANGE`); pre-this date it was ±10%. Code that spans this boundary must condition on date.
- **Limit-hit detection:** for **new code, prefer `pro.stk_limit()`** (exchange-published limit prices) and the `LIMIT_PROXIMITY = 0.998` proximity threshold (`multi_factor_x1/config.py`). The legacy `detect_limit_hits` in `Project_3/risk_toolkit.py` reconstructs limit prices via `_round_half_away(prev_close * (1 ± limit), 2)` (A-share 四舍五入); it is correct and price-based (not return-based — return-based detection breaks at sub-1元 prices), but `stk_limit` is now the source of truth. Do not revert to return-based detection in either case.
- **Universe-construction pre-filters:** drop 停牌 (`tradestatus == '1'` keeps), drop ST / *ST, require positive volume and turnover.
- **Regime breakpoints baked into `multi_factor_x1/config.py`:**
  - `NEW_NINE_ARTICLES_DATE = 2024-04-12` — State Council 新国九条 high-quality capital-markets opinion. Regime break for delisting rules.
  - `PBOC_STIMULUS_DATE = 2024-09-24` — PBoC + SLF stock-support facility press conference. Regime break for liquidity / risk-on flows.
  - Earlier 雪球 meltdown reference window: 2024-01-15 → 2024-02-19 (visible in Project 5 forward-return panel as mean −27.9%).

## Statistical conventions

- Every reported point estimate of a statistic (Sharpe, IC, factor return, correlation) comes with a **bootstrap CI** attached. Point estimates alone are misleading. Use `bootstrap_ci` or `block_bootstrap_ci` from the appropriate `hypothesis_testing.py`.
- For time-series statistics, use **block bootstrap**. Block size is cadence-dependent: **20 for daily** returns, **12 for weekly** (one trading quarter). The Project 6 / multi_factor_x1 default is `BOOT_BLOCK_SIZE = 12, BOOT_N = 10000`. Naive bootstrap on autocorrelated data silently gives CIs that are too narrow.
- **Multi-test correction policy (locked in Project 6):** **Holm-Bonferroni** for the family of headline factor tests; **Benjamini-Hochberg** for within-factor robustness sweeps (cap terciles, regime splits, sector neutralisation). Per-test CIs are computed in `hypothesis_testing.py`; family-wise correction happens in the downstream analysis script.
- NaN handling in the risk toolkit is strict: `compute_drawdown`, `compute_sharpe`, `compute_sortino` all `assert returns.notna().all()` and fail loudly. Drop or fill before calling — do not soften these asserts.
- Sortino in `Project_3/risk_toolkit.py` uses the **Sortino-Price 1994 Target Downside Deviation** (`sqrt(mean(min(R - T, 0)^2))` averaged over all days), not "std of downside-only returns." These produce different numbers; do not swap the formula.
- **Sign convention for z-scores in factor scripts:** z-scores returned from `cross_sectional_zscore` keep the sign of the raw factor. Sign-flip to align with "high z = predicted to outperform" must be done explicitly by the caller (e.g. `z_turnover = -z_turn_raw` because high turnover predicts low return). See `multi_factor_x1/factor_utils.py` docstring.

## Bilingual conventions

- **Chinese** for market-structure terminology and A-share-specific concepts: 流通市值, 总市值, 换手率, 成交额, ST/*ST, 风险警示板, 退市整理期, 面值退市, 停牌, 涨跌停, 前复权, 后复权, 北交所, 创业板, 科创板, 雪球, 新国九条.
- **English** for statistical concepts, Python programming, and general quantitative finance theory.
- Code, comments, and variable names in English. Inline comments may include Chinese for market-specific concepts (`# 获取小盘股数据 / Get small-cap data`).
- When plotting, call `setup_chinese_font()` from the project's `plot_setup.py` to ensure Chinese axis labels and titles render correctly. It probes matplotlib for installed CJK fonts (Mac → Windows → Linux candidates) and sets `rcParams['font.sans-serif']` plus `axes.unicode_minus = False`.

## Key reference files

- `multi_factor_x1/config.py` — current shared constants: paths, regime windows, seven-universe + three-universe definitions, liquidity-floor parameters, A-share constants.
- `Project_6/Project_6_Comprehensive_Closeout.md` — full empirical record of the factor-testing project; the canonical "what did we learn" document.
- `Project_6/Project_6_Universe_Rebuild_Handoff_Final.md` — five-stage rebuild that produced `universe_membership_X75_Y3000.parquet`.
- `Project_5/Project_Five_Closeout.md` — universe-construction infrastructure, mcap correction story, Tushare adoption rationale.
- `quant_learning_plan.jsx` — original curriculum scope (now superseded for Phase 3 by the Project 5 closeout's revised trajectory).

## Working style for this repo

- Stay within the scope of the current task. Do not preemptively build features for later sessions or projects. The most recent handoff or closeout is the forward boundary.
- When completing a significant task, write or extend the current session's handoff with what was done and what remains. Do not create new top-level summary documents.
- If a decision has ambiguity, ask the student before proceeding. The cost of the wrong choice propagates across future sessions because each builds on the last; the cost of one clarifying question is negligible.
