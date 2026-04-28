# Session 2 Summary — pandas Filtering, Resampling, Rolling Windows

## Environment
- Same VS Code + ipykernel setup from Session 1
- New notebook for Session 2
- Re-ran baostock data pull at start (no caching yet, that's Session 4)

## What We Did

### .loc[] vs .iloc[]
- `.loc[]` selects by **label** (dates, column names). Slicing is **inclusive on both ends**: `df.loc['2024-04-01':'2024-04-03']` includes April 3rd.
- `.iloc[]` selects by **integer position**. Slicing follows Python convention: **exclusive on the right end**: `df.iloc[0:3]` gives rows 0, 1, 2.
- `.loc[]` is safe around weekends/holidays — it returns whatever trading days exist in the range. `.iloc[]` always returns exactly N rows regardless of dates.
- Use `.loc[]` ~90% of the time with time-series data. `.iloc[]` for "first N rows" or "last row" type operations.

### Boolean Filtering
- Pattern: create a True/False condition, pass it into `df[...]`
- `df[df['close'] > df['open']]` — selects all up days (119 out of 242)
- Combine with `&` (and) or `|` (or). **Each condition must be in parentheses**:
  `df[(df['close'] > df['open']) & (df['volume'] > 100_000_000)]`
- Filter by index properties: `df[df.index.month == 9]` for September data
- Can use rolling calculations as dynamic thresholds (e.g., filter where volume > 20-day average volume)

### .resample() — Changing Frequency
- Groups data by time period and aggregates
- **Must use `.agg()` with correct function per column for OHLCV data**:
```python
weekly = df.resample('W').agg({
    'open': 'first',      # First day's open
    'high': 'max',         # Highest high of the period
    'low': 'min',          # Lowest low of the period
    'close': 'last',       # Last day's close
    'volume': 'sum'        # Total volume
})
```
- Naive `.resample('W').last()` gives wrong values for high/low/open/volume — verified this by comparing outputs
- `'W'` for weekly, `'ME'` for month-end
- 242 daily rows → 53 weekly rows → 13 monthly rows

### .rolling() — Moving Window Calculations
- `df['close'].rolling(20).mean()` computes 20-day moving average
- First 19 rows are NaN (not enough data to fill the window)
- Handle NaN with `df.dropna()` (creates a copy, does not modify original)
- Also computed `df['ma_vol']` — 20-day moving average of volume, used as dynamic filter threshold

### Plotting
- Created weekly close + 4-week MA chart using matplotlib
- Chinese characters in title rendered as boxes — font issue to fix in Session 3

## Key Lessons
- **`.loc[]` includes both endpoints, `.iloc[]` excludes the right end** — different slicing conventions, will cause off-by-one bugs if forgotten.
- **Always use `.agg()` for OHLCV resampling** — naive `.last()` gives wrong high/low/open values. Verified ~2% error on weekly highs.
- **Rolling calculations produce NaN at the start** — first N-1 rows will be NaN. Use `.dropna()` when you need clean data, but keep original intact.
- **Use rolling stats as dynamic thresholds** — comparing volume to its own 20-day MA is more meaningful than comparing to a hardcoded number, because "normal" volume changes over time.

## Observations from the Data
- 119 up days out of 242 total (~49%)
- 73 "big up" days (close > open AND volume > 100M) — high-volume days skew toward up days for 平安银行
- 32 "true down" days (close < open AND volume > 20-day avg) — only 14.3% of trading days
- High-volume up days outnumber high-volume down days ~2:1 for this stock. Rallies attract retail participation; selloffs are often quieter. This asymmetry may differ for 小盘股.

## Packages Used
`baostock`, `pandas`, `matplotlib` (first use)

## Columns Added to df
- `ma_20` — 20-day moving average of close
- `ma_vol` — 20-day moving average of volume

## Next Up
Session 3 — Visualization: subplots (price on top, volume on bottom), matplotlib object-oriented interface (fig, ax), Chinese font fix, multiple stocks on same axes, normalized comparison charts, saving figures to disk.
