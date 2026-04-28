# Session 1 Summary — Local Data Pipeline

## Environment
- VS Code with `.ipynb` notebooks (installed `ipykernel`)
- Virtual environment, no Anaconda needed

## What We Did
- Installed and used `baostock` to pull daily 日K线 data for 平安银行 (sz.000001)
- baostock requires `bs.login()` / `bs.logout()` around every query
- Loaded results into a pandas DataFrame
- Cleaned data: `pd.to_numeric()` for price/volume columns (baostock returns everything as strings), `pd.to_datetime()` for dates, `set_index('date')` for DatetimeIndex
- Used `adjustflag="2"` for 前复权 (forward-adjusted prices)
- Sliced by date with `df.loc['2024-07']`
- Added a computed column: `df['range'] = df['high'] - df['low']`
- Used `.max()`, `.idxmax()`, `.sort_values()`, `.head()`, `.count()`
- Pulled both 2024 and 2025 data into separate DataFrames (`df` and `df_2025`)

## Key Lessons
- **Always check `df.dtypes` after loading** — baostock returns everything as strings. If you forget to convert, arithmetic silently fails or produces garbage.
- **Weekends/holidays create gaps** — "20-day" means 20 trading days, not 20 calendar days.
- **Think in columns, not loops** — pandas operates on whole columns at once. `df['high'] - df['low']` subtracts every row simultaneously. No `for` loop needed.
- **Volatility is not constant** — 2024 had a big range cluster around the September PBOC stimulus rally (top range: 1.01). 2025 was calmer with no clustering (top range: 0.54). This foreshadows volatility clustering in Project 2.

## Packages Installed
`baostock`, `pandas`, `ipykernel`

## Code Pattern: Pull and Clean Data
```python
import baostock as bs
import pandas as pd

lg = bs.login()

rs = bs.query_history_k_data_plus(
    "sz.000001",
    "date,open,high,low,close,volume",
    start_date="2024-04-01",
    end_date="2025-04-01",
    frequency="d",
    adjustflag="2"        # 前复权
)

data_list = []
while (rs.error_code == '0') and rs.next():
    data_list.append(rs.get_row_data())

df = pd.DataFrame(data_list, columns=rs.fields)

bs.logout()

# Clean
for col in ['open', 'high', 'low', 'close', 'volume']:
    df[col] = pd.to_numeric(df[col])
df['date'] = pd.to_datetime(df['date'])
df = df.set_index('date')
```

## Next Up
Session 2 — pandas fundamentals: `.loc[]`/`.iloc[]` filtering, `.resample()` for daily-to-weekly conversion, `.rolling()` for moving averages, `.dropna()`, `.fillna()`.
