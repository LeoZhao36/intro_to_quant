# Session 3 Summary — Visualization with matplotlib

## Environment
- Same VS Code + venv + ipykernel setup from Sessions 1 and 2
- New notebook for Session 3
- Re-used cleaned `df` (平安银行) from Session 2, added second stock `df_small` (拓尔思, sz.300229) for comparison
- Same date range for both stocks: 2024-04-01 to 2025-04-01, 242 trading days each, fully aligned

## What We Did

### matplotlib Object-Oriented Interface
- `plt.plot(...)` is the "pyplot" shorthand. It works for throwaway plots but relies on implicit global state ("the current figure"), which becomes ambiguous with multiple subplots.
- OO interface makes the target explicit: `fig, ax = plt.subplots()` creates a figure and returns handles to both. Plotting methods are called on the specific axes: `ax.plot(...)`, `ax.set_title(...)`.
- Hierarchy to internalize: **one figure (canvas) → one or more axes (plot areas) → every plotting method belongs to an axes object**.

### Chinese Font Configuration
- Default matplotlib fonts cannot render Chinese characters. They show as tofu boxes.
- Fix at top of notebook:
```python
matplotlib.rcParams['font.sans-serif'] = [
    'PingFang HK', 'Microsoft YaHei', 'SimHei',
    'WenQuanYi Micro Hei', 'Arial Unicode MS'
]
matplotlib.rcParams['axes.unicode_minus'] = False
```
- The font list is tried in order until one is found. `unicode_minus = False` prevents negative signs from rendering as boxes (some Chinese fonts lack the Unicode minus glyph).

### Two-Panel Price + Volume Chart
- Financial convention: price on top (larger), volume on bottom (smaller), shared x-axis.
- Key pattern:
```python
fig, (ax_price, ax_vol) = plt.subplots(
    2, 1, figsize=(12, 7), sharex=True,
    gridspec_kw={'height_ratios': [3, 1]}
)
```
- `sharex=True` binds x-axes together so date labels only appear on bottom and zoom stays synchronized.
- `height_ratios=[3, 1]` makes price panel 3x taller than volume panel (industry standard, price carries more info per pixel).
- Multiple `ax.plot()` calls add lines to the same axes. `label=` arguments feed into `ax.legend()` automatically.
- `fig.tight_layout()` removes awkward whitespace between panels.

### Volume Bar Color-Coding
- Built colors per bar via list comprehension:
```python
colors = ['green' if c >= o else 'red'
          for c, o in zip(df['close'], df['open'])]
ax_vol.bar(df.index, df['volume'], color=colors, alpha=0.6)
```
- Makes volume-direction asymmetry (up-day vs down-day participation) visible at a glance.

### Normalization for Cross-Stock Comparison
- **Problem**: raw price levels are arbitrary. A stock at 100 moving to 110 and a stock at 10 moving to 11 are the same percent move, but a naive line chart shows one as +10 units and the other as +1 unit. Eye reads absolute differences, not percent moves.
- **Fix**: normalize both series to the same starting value (100):
```python
df['close_norm'] = df['close'] / df['close'].iloc[0] * 100
```
- Day 1 becomes 100 for every stock. Every subsequent value shows cumulative percent change. 110 = +10%, 95 = −5%. Both stocks now on the same scale, eye reads returns directly.
- Added `ax.axhline(100, ...)` as reference line for "starting point", making positive/negative cumulative return visible instantly.

### Saving Figures to Disk
- Pattern:
```python
import os
os.makedirs('charts', exist_ok=True)
fig.savefig('charts/filename.png', dpi=150, bbox_inches='tight')
```
- `savefig()` does NOT create parent directories. Must create folder first with `os.makedirs(exist_ok=True)`.
- `dpi=150` is the sweet spot (default 100 is grainy on modern screens, 300 only for print).
- `bbox_inches='tight'` trims whitespace around the figure.

## Key Lessons
- **Use the OO interface (`fig, ax = plt.subplots()`) from the start**, not `plt.plot()`. Saves confusion when subplots appear.
- **The `Chinese font + unicode_minus` fix is a one-time header** that should live at the top of every notebook that produces charts.
- **Normalize before comparing stocks visually**. Raw prices are misleading because they encode arbitrary price levels, not returns.
- **`savefig()` does not create folders**. Always `os.makedirs(path, exist_ok=True)` first.
- **Tracebacks show library file paths (from `.venv\site-packages\...`), not working directory**. Use `os.getcwd()` if you need to know where your notebook is actually running.
- **N-day moving averages lag by roughly N/2 days during trends**. Not a quirk, a built-in property. Shorter window = more responsive but noisier. Longer = smoother but more lag. No free lunch. Any MA-crossover signal is buying into an established trend, not catching its start.

## What the Charts Revealed (平安银行 vs 拓尔思 comparison)

Saw four distinct market phenomena in a single normalized comparison chart, before having formal tools to test any of them. Noted now so I can revisit when each gets formalized later:

### 1. Volatility scaling with size
拓尔思 (small-cap) far more jagged than 平安银行 (large-cap) throughout the entire period. Mechanisms stacked on top of each other:
- Float/liquidity: smaller float = each trade has larger price impact
- Holder base: retail-dominated vs institution-dominated (fast money vs slow money)
- Information environment: less analyst coverage = repricing happens in larger discrete jumps when info arrives

Both stocks ended positive, but paths were completely different shapes. Will meet formally in **Project 2** (rolling volatility) and **Project 5** (size factor).

### 2. Regime-dependent decoupling
April to September 2024: 平安银行 drifted sideways (~95-110), 拓尔思 declined steadily from 100 to ~70. Same market, same macro, opposite directions for five months.
- Mechanism: risk-off regime. Money flows from speculative growth (small-cap tech) to perceived safety (large-cap financial/SOE).
- 平安银行 = "park money" destination. 拓尔思 = "risk-on" bet.
- Lesson: factor strategies are regime-dependent. A size factor strategy would have been hammered April-September 2024 regardless of whether the factor is "real". Will meet formally in **Phase 4**.

### 3. Beta amplification
Late September / early October 2024 PBOC stimulus rally: both stocks spiked upward together, but 拓尔思 spiked more violently.
- Small-caps don't just move more, they move more *in the direction the market is already going*.
- This is why small-caps post enormous gains in bull years and enormous drawdowns in bear years.
- Will meet formally in **Project 6** when testing factor correlations.

### 4. Idiosyncratic thematic speculation
Early 2025: 拓尔思 had a second parabolic move from ~115 to ~180 (roughly 55% in a few weeks). 平安银行 flat during this period.
- Not macro-driven. Stock/theme-specific.
- 拓尔思 is NLP/AI-adjacent. Coincides with DeepSeek release (January 2025) triggering mass re-rating of Chinese AI-adjacent small-caps.
- Mechanism: small-caps are speculatively bid-up more easily because float is small and "story" isn't constrained by quarterly fundamentals. Narrative can move them before any revenue shows up.
- This is a source of alpha absent from large-caps, and a reason factor models built only on fundamentals will miss what moves 小盘股.

## Packages Used
`matplotlib` (primary), `pandas`, `baostock`, `os` (for folder creation)

## Files Saved
- `charts/pingan_vs_tuosi_comparison.png` — normalized cumulative return comparison
- `charts/pingan_price_volume.png` — two-panel price + volume chart with 20-day MA and colored volume bars

## Dataset Extended
- Added `df_small`: 拓尔思 (sz.300229), same date range as `df`, 242 rows aligned
- 拓尔思 and 平安银行 kept as working pair for Project 1 return distributions — the visual volatility difference should show up as fat-tails in the distribution analysis

## Open Questions to Revisit
1. **Volume-direction asymmetry for small-caps**: 平安银行 showed ~2:1 high-volume up-days vs down-days (Session 2 finding). Hypothesis is this might invert for 小盘股 due to panic selling into thin order books. Test when loading more small-caps in Project 1.
2. **拓尔思 early-2025 parabolic move**: was it really DeepSeek-driven? Check by pulling data for other Chinese AI-adjacent small-caps (e.g., 科大讯飞 sz.002230, 昆仑万维 sz.300418) for same window. If they moved similarly, confirms thematic rotation.
3. **MA window optimization**: 20-day MA may lag too much for small-cap trends that are shorter than large-cap trends. What window length captures 小盘股 trends without excessive noise? Revisit in Project 6 momentum factor work.
4. **Regime detection**: the April-September 2024 risk-off period was visible in hindsight. Is there a leading indicator that would have flagged it in real time? Phase 4 question.

## Next Up
Session 4 — Building the reusable pipeline. Take code from Sessions 1-3 and turn it into reusable functions:
- `get_stock_data(code, start, end)` — handles baostock login/logout, query, cleaning, returns clean DataFrame
- `plot_stock(df, title)` — produces standard price+volume chart
- CSV caching: if file for stock+date range exists locally, load from disk instead of re-downloading
- Create `/data` folder for CSVs, `/charts` folder already exists
- Pull data for 10 stocks from 中证1000, cache them, generate charts in a loop
- Mostly software engineering, no new market concepts

Goal: one function call pulls or loads data for any stock. One function call plots it. 10+ stocks cached locally as the working dataset for Phase 1.
