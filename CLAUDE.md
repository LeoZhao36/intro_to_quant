# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What this repo is

A personal **learning project** for Chinese A-share quantitative finance, not a shipped codebase. The student is a humanities-background learner building quantitative trading skills through a project-based curriculum. The curriculum document is `quant_learning_plan.jsx` at the repo root (a React artifact, not meant to run here).

Work is organized into sequential **Projects** (`Project_0` through `Project_5`), each containing sequential **Sessions** (Jupyter notebooks) plus a per-session `*_Handoff.md` and a `*_Closeout.md` at project end. These markdown files are the primary record of intent and reasoning — read them before modifying a project's code.

Current active project: **Project_5** (small-cap universe construction and size-factor testing).
Current position: Project 5, Session 2 (about to begin).
Project 5 Session 1 closed 2026-04-23.

## Pedagogical rule (read this before any substantive work)

This is a learning project, and the learning depends on the student understanding what is being built and why. Claude Code's role is **execution once concepts are clear**, not concept introduction.

- Before writing code that introduces a new statistical concept, factor definition, backtesting principle, or market mechanism the student has not yet encountered, stop and flag it. Concept introduction happens in the claude.ai chat interface, not here.
- If you find yourself wanting to explain *why* a factor works, *why* a test applies, or *what* a market mechanism means, stop and suggest the student take the question to claude.ai. Return to execution once the conceptual groundwork has been laid there.
- Exceptions: Python syntax, pandas operations, baostock API quirks, matplotlib details, standard library usage, debugging assistance, and other purely technical matters are yours to handle freely. The rule covers financial and statistical concepts, not programming.

The complementary division: **claude.ai chat owns the "what" and "why"; Claude Code owns the "how" and "did it run"**. When the student asks you for execution help after a concept discussion, proceed normally. When they ask you for the concept discussion itself, redirect.

## Session handoff workflow (source of truth)

Session handoffs in `handoffs/` (format: `Project_N_Session_M_Handoff.md`) are the source of truth for "what was decided and why." Before starting any new task, **read the most recent handoff in that directory**. The "Open items carried forward" section tells you what is actually next.

- Do not build infrastructure ahead of the curriculum sequence. If a future session will build something differently, wait for that session. Drift toward premature optimization breaks the curriculum structure.
- Do not create new top-level planning, summary, or architecture documents. The student maintains these manually per session.
- When the student references a prior session, project, or decision, read the corresponding handoff rather than reconstructing from notebook code.

## Thesis state (confirmed Project 5 Session 1, 2026-04-23)

**小盘股 is a universe scope, not a factor.** The raw size premium has been weak out-of-sample globally since Fama-French documented it, and the A-share-specific mechanisms that historically produced a size premium (shell-company speculation, restricted institutional participation) have partly eroded since 2018.

The alpha source in this universe is **retail-driven behavioral effects**, not size itself. Retail dominance is the mechanism; volatility is the amplifier. Factors to be tested in Projects 5 and 6 target retail-specific behaviors:
- Short-term reversal (1-5 day lookback): direct retail overreaction and mean reversion
- Idiosyncratic volatility anomaly: retail lottery-preference bidding up volatile stocks
- Turnover and attention: retail chasing recent performers
- Post-limit-hit behavior: uniquely A-share, microstructure-specific

The size factor test in Project 5 remains valuable as a **calibration exercise** against a known prior (the student expects no marginal size effect within the small-cap universe), not as a discovery exercise.

## Universe definition (locked Project 5 Session 1)

At each rebalance date t:
1. All A-share equities on 上交所 and 深交所 (prefixes `sh.60`, `sh.68`, `sz.00`, `sz.30`)
2. Exclude ST / *ST (`isST == 1`)
3. Exclude 停牌 (`tradestatus == 0`)
4. Exclude 退市整理期 stocks
5. Require trailing-20-day mean daily 成交额 ≥ 3000万 RMB
6. Sort ascending by 流通市值
7. Take bottom 1000 that pass all filters

Sample window: 2022-01-01 to 2026-04-23, **monthly rebalancing** on first trading day of each month (~52 rebalance dates). This window deliberately excludes COVID (2020-2021) as an unusual period, and carries the caveat that it lacks a true liquidity-crisis regime.

## Environment

- Python **3.14.3** in `.venv/` at the repo root. On Windows, activate with `.venv\Scripts\activate` (PowerShell: `.venv\Scripts\Activate.ps1`).
- Dependencies installed ad-hoc, not pinned. Core stack: `baostock`, `pandas`, `numpy`, `matplotlib`, `statsmodels`, `jupyter`. No `requirements.txt` or `pyproject.toml`.
- Shell is bash on Windows — use Unix paths and `/dev/null`, not PowerShell syntax.

## Running things

- **Notebooks:** open `Project_N/Session_*.ipynb` in Jupyter. Each notebook is meant to be executed top-to-bottom within its own project directory so the relative `data/` cache resolves.
- **Scripts:** `cd Project_N && python script.py` (e.g. `cd Project_5 && python build_universe.py`). Scripts write caches to `./data/` relative to CWD, so CWD matters.
- **Smoke tests:** modules with test coverage expose `execute_smoke_tests()` and/or run tests under `if __name__ == "__main__":`. Run with `python Project_N/utils.py` or `python Project_3/risk_toolkit.py`. There is no pytest setup; do not introduce one unless asked.

## Per-project layout convention

Every project is **self-contained and duplicative by design**. Each `Project_N/` has its own `utils.py`, `plot_setup.py`, `data/` cache, and often its own local copy of helpers that exist elsewhere. **Do not refactor common code into a shared top-level package unless the student explicitly asks** — the forward-copying is pedagogical (each project re-derives what it needs, sometimes with a refined definition). The canonical cleaned-up risk toolkit lives at `Project_3/risk_toolkit.py`; earlier projects have messier parallel copies that should not be "unified."

When adding code to a project, prefer extending that project's existing `utils.py` or adding a sibling script inside `Project_N/` rather than reaching across projects.

## Data source: baostock

All market data comes from `baostock`, and its quirks shape most of the code:

- Every query requires `bs.login()` before and `bs.logout()` after. The helpers wrap this in `try/finally`; preserve that pattern.
- **Everything is returned as strings.** Always `pd.to_numeric(..., errors='coerce')` the OHLCV columns and `pd.to_datetime` the date column. Do not trust dtypes coming back from baostock.
- `adjustflag`: `'2'` = 前复权 (forward-adjusted, **default everywhere**), `'1'` = 后复权, `'3'` = unadjusted. Unadjusted prices show fake crashes around splits/dividends — stay on `'2'` unless there is a stated reason.
- `tradestatus == '1'` is normal trading, `== '0'` is suspended (reverse of intuitive).
- Pulling one day across all A-shares (~5000 stocks) takes 15-25 minutes single-threaded. Scripts that do this (`Project_5/build_universe.py`, `liquidity_diagnostic.py`) cache aggressively to `data/<something>_<date>.csv` and short-circuit when the cache exists. Preserve this behavior when editing.
- No batch multi-code queries exist. One API call per stock per date range.
- For large loops (52-date universe construction), use `concurrent.futures.ThreadPoolExecutor` with **8 workers** as the safe default. Above ~16 workers baostock starts throttling and failures offset the gains.

### Caching convention

CSV cache files are keyed by the tuple `(code, start, end, adjust)` — e.g. `sz_000001_2024-01-01_2024-12-31_qfq.csv`. `load_or_fetch()` in `Project_2/utils.py` and `Project_4/utils.py` is the canonical wrapper. Changing the date range produces a **new** file; the cache does not merge partial ranges. This is intentional (good enough for project work, insufficient for production) — do not try to "fix" it.

For multi-date loops (Project 5 Session 2 onward), cache **per-date incrementally** so mid-loop failures do not lose completed work. Write each date's output to disk as soon as it completes, and resume by checking which dates already have cache files on restart.

## A-share domain facts encoded in the code

These numbers and rules are baked into helpers. Honor them when writing new analysis:

- **Trading days per year: 242** (not 252). Used for all annualization: `np.sqrt(242)` for vol, `* 242` for annual mean.
- **Stock code prefixes** (see `to_baostock_code` in `Project_2/utils.py`, `Project_4/utils.py`):
  - `6xxxxx` → `sh.` (Shanghai main / 科创板 `688`)
  - `0xxxxx`, `3xxxxx` → `sz.` (Shenzhen main / 创业板 `300`/`301`)
  - `4xxxxx`, `8xxxxx` → `bj.` (北交所)
- **A-share equity universe filter** (`Project_5/build_universe.py`): keep only prefixes `sh.60`, `sh.68`, `sz.00`, `sz.30`. Everything else (ETFs, B-shares, indexes, 北交所) is excluded.
- **Size measure:** always **流通市值** (free-float market cap), never 总市值. Derived via `流通股本 = volume / (turn / 100)` then `float_mcap = close × 流通股本`. This is the identity used in `Project_5/build_universe.py`.
- **Price-limit (涨跌停) percentages** (`_get_board_limit` in `Project_3/risk_toolkit.py`):
  - 主板: ±10%
  - 创业板 (`300`/`301`), 科创板 (`688`): ±20%
  - 北交所 (`43`/`83`/`87`/`92`): ±30%
  - ST/*ST is NOT inferred from the code — pass `override_limit` when needed.
- **Limit-hit detection is price-based, not return-based.** `detect_limit_hits` reconstructs the exchange's limit price via `_round_half_away(prev_close * (1 ± limit), 2)` ("half away from zero" is the A-share rounding convention). Return-based detection breaks at sub-1元 prices because 分-rounding causes the realized limit return to deviate from the nominal percentage by up to ±1%. Do not revert to return-based detection.
- **Universe-construction pre-filters** (in order): `tradestatus == '1'` (drop 停牌), `isST == '0'`, `volume > 0 and turn > 0`.

## Statistical conventions (from Project 4 closeout)

- Every reported point estimate of a statistic (Sharpe, IC, factor return, correlation) comes with a **bootstrap CI** attached. Point estimates alone are misleading. Use `bootstrap_ci` or `block_bootstrap_ci` from `hypothesis_testing.py`.
- For time-series statistics (daily returns and anything derived from them), use **block bootstrap** with block size 20. Naive bootstrap on correlated data silently gives CIs that are too narrow.
- Multiple testing: **Bonferroni for factor discovery** (false positives very costly); Holm-Bonferroni or Benjamini-Hochberg for robustness checks (specific choice deferred to Project 5 Session 3 opener).
- NaN handling in the risk toolkit is strict: `compute_drawdown`, `compute_sharpe`, `compute_sortino` all `assert returns.notna().all()` and fail loudly. Drop or fill before calling — do not soften these asserts.
- Sortino in `Project_3/risk_toolkit.py` uses the **Sortino-Price 1994 Target Downside Deviation** (`sqrt(mean(min(R - T, 0)^2))` averaged over all days), not "std of downside-only returns." These produce different numbers; do not swap the formula.

## Bilingual conventions

- **Chinese** for market-structure terminology and A-share-specific concepts: 流通市值, 总市值, 换手率, 成交额, ST/*ST, 风险警示板, 退市整理期, 停牌, 涨跌停, 前复权, 后复权, 北交所, 创业板, 科创板.
- **English** for statistical concepts, Python programming, and general quantitative finance theory.
- Code, comments, and variable names in English. Inline comments may include Chinese for market-specific concepts (`# 获取小盘股数据 / Get small-cap data`).
- When plotting, call `setup_chinese_font()` from the project's `plot_setup.py` to ensure Chinese axis labels and titles render correctly. It probes matplotlib for installed CJK fonts (Mac → Windows → Linux candidates) and sets `rcParams['font.sans-serif']` plus `axes.unicode_minus = False`.

## Key reference files

- `handoffs/Project_Five_Session_One_Handoff.md` — current state of Project 5
- `quant_learning_plan.jsx` — overall curriculum scope and session-level breakdown

## Working style for this repo

- Stay within the scope of the current session. Do not preemptively build features for later sessions. The handoff "Open items" section is the forward boundary.
- When completing a significant task, write or extend the current session's handoff with what was done and what remains. Do not create new top-level summary documents.
- If a decision has ambiguity, ask the student before proceeding. The cost of the wrong choice propagates across future sessions because each builds on the last; the cost of one clarifying question is negligible.
