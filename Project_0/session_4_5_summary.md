# Session 4–5 Summary — Reusable Pipeline + Edge Cases

## Environment
- Same VS Code + venv + ipykernel setup from Sessions 1–3
- New notebook: `Session_Four_and_Five.ipynb`
- Created `utils.py` module for reusable functions
- Created `/data` folder for CSV cache, `/charts` folder already existed from Session 3

## What We Built

### Session 4: Reusable Pipeline

#### `get_stock_data(code, start, end, freq, adjust)`
Core data-fetching function. Wraps the entire baostock workflow:
1. Validate input (stock code format check)
2. `bs.login()`
3. `bs.query_history_k_data_plus(...)` with specified parameters
4. Collect rows, build DataFrame
5. Convert all columns from strings to correct dtypes (baostock returns everything as strings)
6. Set date as DatetimeIndex
7. `bs.logout()`

Key design decisions:
- `adjust` defaults to `'2'` (前复权) because that's the correct choice for return calculations. Have to explicitly opt out.
- `pd.to_numeric(col, errors='coerce')` converts unparseable values (empty strings from 停牌, etc.) to NaN instead of crashing.
- `bs.login()` and `bs.logout()` called per function call, not held open. Slightly wasteful for loops, but simple and reliable. If a query crashes mid-session, cleanup still happens.

#### `get_stock_data_cached(code, start, end, freq, adjust, data_dir)`
Wrapper around `get_stock_data` that adds CSV caching:
- Constructs filename from all query parameters: `{code}_{start}_{end}_{freq}_{adjust}.csv`
- If file exists on disk → load with `pd.read_csv(filepath, index_col='date', parse_dates=True)` and return
- If not → download via `get_stock_data`, save to CSV, return
- No partial overlap handling. If the exact query hasn't been cached, re-download. Simplicity over cleverness.

Important: `parse_dates=True` is required when loading CSVs, otherwise dates load as strings and plots break.

#### `plot_stock(df, title, ma_window, save_path)`
Two-panel price+volume chart with optional moving average. Reusable version of the Session 3 chart.
- Uses OO interface (`fig, ax = plt.subplots()`)
- Volume bars color-coded green/red based on close vs open
- `os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)` handles the edge case where save_path has no directory component

#### Module extraction (`utils.py`)
- All three functions plus `detect_gaps` live in `utils.py`
- Notebooks import with `from utils import get_stock_data, get_stock_data_cached, plot_stock, detect_gaps`
- Notebook contains only imports, analysis, and visualization. No function definitions that duplicate the module.

### Session 5: Edge Cases

#### 停牌 (trading suspension) detection
- baostock simply skips suspended dates. No rows exist for suspension days.
- `detect_gaps(df, max_gap_days=5)` finds gaps longer than 5 calendar days between consecutive trading rows. Normal weekends = 2–3 days, holidays up to ~7–9 days (春节/国庆). Anything beyond threshold is likely 停牌.
- Why it matters: the return on the first day back from suspension captures the entire suspension period's accumulated information in a single day. It's real but not comparable to a normal daily return. These will show up as outliers in Project 1 return distributions.
- Edge case: 春节 and 国庆 can exceed 5 calendar days. Threshold of 5 flags them too. Manual inspection or a holiday calendar needed to distinguish. Not worth over-engineering now.

#### 前复权 vs 不复权 comparison
- Plotted both versions of 平安银行 on the same axes. Divergence point = dividend ex-date (除权除息日).
- 前复权 adjusts all historical prices downward retroactively so the return series is continuous across dividend events.
- 不复权 shows actual traded prices at the time. On ex-dividend day, raw price drops by approximately the dividend amount. This creates a fake negative return in `.pct_change()` that isn't a real market move.
- Takeaway: always use 前复权 for return calculations. Using 不复权 introduces artificial price drops at every dividend event.

#### Error handling
- Added input validation at the top of `get_stock_data`: checks for '.' in stock code before opening any baostock connection.
- Design principle: validate inputs BEFORE acquiring resources (network connections, file handles). If validation fails, fail fast and clean. No leaked connections.
- Tested four failure modes: wrong format (ValueError), nonexistent code (empty DataFrame), pre-listing date range (empty DataFrame), flipped dates (empty DataFrame with baostock warning).

## Key Lessons

### Python/Software Engineering
- **Stale imports are the #1 trap when editing `.py` files.** Python caches imports. Editing `utils.py` and re-running `from utils import ...` does NOT reload the file. Must restart kernel or use `importlib.reload(utils)`.
- **Local definitions shadow imports.** If the same function name is defined both in the notebook and in an imported module, the local definition wins. Once you commit to using `utils.py`, delete all inline function definitions from notebooks.
- **`__pycache__/` stores compiled bytecode.** Can become stale. Delete the folder if imports behave unexpectedly after edits.
- **`try/except` for testing multiple failure cases.** A `raise ValueError` kills the entire cell. To test multiple cases that might raise exceptions, wrap each in try/except or put them in separate cells.
- **Validate before acquiring resources.** Input checks go before `bs.login()`, before `open(file)`, before any connection. Otherwise an error leaves resources leaked.

### Market/Data
- **baostock does not cache anything locally.** Every query hits the server. The caching layer is something we build ourselves.
- **All 10 stocks showed the late-September 2024 PBOC stimulus rally.** This is a macro event, not evidence of small-cap alpha. The universal rise in the dataset is a period effect, not a stock-selection effect.
- **厦门银行 (sh.601187) vs 平安银行 (sz.000001)** is a purer test of the size effect than cross-sector comparisons. Same industry, different size. 厦门银行 is noticeably more jagged despite identical macro exposure. Controls for sector, isolates size/liquidity.
- **航天科技 (sz.000901) volume pattern** shows the extreme case of thin liquidity: near-zero volume for weeks, then sudden massive spikes. Measured volatility alternates between deceptively calm and suddenly extreme.
- **悦康药业 (sh.688658) is 科创板** (688 prefix). ±20% daily price limits instead of ±10% for main board. Relevant for 涨跌停 detection logic, which needs board-specific thresholds.

## Stock Universe
11 stocks total (10 from 中证1000 + 平安银行 as large-cap reference):

| Code | Name | Exchange/Board | Sector (rough) |
|------|------|----------------|-----------------|
| sz.000001 | 平安银行 | 深交所主板 | Banking (large-cap reference) |
| sz.300229 | 拓尔思 | 创业板 | Tech/NLP/AI |
| sh.688658 | 悦康药业 | 科创板 | Pharma |
| sh.600597 | 光明乳业 | 上交所主板 | Consumer/Dairy |
| sh.601187 | 厦门银行 | 上交所主板 | Banking (small-cap) |
| sh.601595 | 上海电影 | 上交所主板 | Media/Entertainment |
| sh.601022 | 宁波远洋 | 上交所主板 | Shipping |
| sz.300352 | 北信源 | 创业板 | Cybersecurity |
| sh.600116 | 三峡水利 | 上交所主板 | Utilities/Hydro |
| sz.000901 | 航天科技 | 深交所主板 | Aerospace/Defense |
| sz.002139 | 拓邦股份 | 中小板 | Electronics/IoT |

## Honest Self-Assessment
- **Conceptual understanding: solid.** Can explain what each function does, why design decisions were made, what 前复权 is, why caching matters, what 停牌 does to return series.
- **Technical fluency: not yet independent.** Most code was adapted from provided examples rather than written from scratch. Understand what it does but couldn't reproduce it cold. This is expected at this stage. Project 1 will provide repetition through use.
- **Debugging skills: improved.** Went through a real debugging cycle (stale imports, shadowed function definitions, validation ordering). These are practical lessons that only come from hitting the wall.

## Files
- `utils.py` — reusable functions: `get_stock_data`, `get_stock_data_cached`, `plot_stock`, `detect_gaps`
- `data/` — cached CSVs for all 11 stocks (2024-04-01 to 2025-04-01)
- `charts/` — individual stock charts + normalized comparison chart with gap shading
- `Session_Four_and_Five.ipynb` — working notebook with imports from utils.py

## Open Questions to Revisit
1. **停牌 returns in distributions**: when computing return distributions in Project 1, should suspension-gap returns be excluded, flagged, or kept? They're real price changes but not comparable to normal daily returns. Need a principled decision.
2. **科创板 ±20% limits**: 悦康药业's price limits differ from the other stocks. When testing for 涨跌停 events later, need board-specific thresholds (±10% for main board/中小板, ±20% for 创业板/科创板 post-2020 reform).
3. **Volume scale differences**: 平安银行's volume is in the 1e8 range, 航天科技's is in the 1e7 range with long stretches near zero. Direct volume comparisons across stocks need normalization (e.g., turnover rate rather than raw volume).

## Next Up
**Project 1, Session 1 — Computing Returns**
- Compute simple returns and log returns for the stock universe
- First use of `.pct_change()` and `np.log(close / close.shift(1))`
- Compare simple vs log returns, understand when they diverge (涨停 days)
- Plot returns as a time series, observe volatility clustering visually
- This is where quantitative analysis begins. Everything in Project 0 was infrastructure.
