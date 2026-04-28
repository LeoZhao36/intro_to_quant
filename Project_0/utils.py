import baostock as bs
import pandas as pd
import os

def get_stock_data(code, start, end, freq='d', adjust='2'):
    """
    Pull daily OHLCV data from baostock for a single stock.
    
    Parameters:
        code:   baostock format, e.g. 'sz.000001'
        start:  'YYYY-MM-DD'
        end:    'YYYY-MM-DD'
        freq:   'd' for daily (default), 'w' for weekly, 'm' for monthly
        adjust: '2' = 前复权 (default), '1' = 后复权, '3' = 不复权
    
    Returns:
        DataFrame with DatetimeIndex and float columns:
        open, high, low, close, volume, amount, turn
    """
    
    if '.' not in code:
        raise ValueError(
            f"Stock code '{code}' missing exchange prefix. "
            f"Use 'sz.000001' or 'sh.600000' format."
        )

    fields = 'date,open,high,low,close,volume,amount,turn'

    bs.login()
    
    rs = bs.query_history_k_data_plus(
        code, fields,
        start_date=start, end_date=end,
        frequency=freq, adjustflag=adjust
    )
    
    rows = []
    while (rs.error_code == '0') and rs.next():
        rows.append(rs.get_row_data())
    bs.logout()
    
    if not rows:
        print(f"Warning: no data returned for {code} ({start} to {end})")
        return pd.DataFrame()
    
    df = pd.DataFrame(rows, columns=rs.fields)
    
    # Convert types — baostock returns everything as strings
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    
    numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    return df



def get_stock_data_cached(code, start, end, freq='d', adjust='2', 
                          data_dir='data'):
    """
    Same as get_stock_data, but checks for a local CSV first.
    Downloads only if the CSV doesn't exist.
    """
    os.makedirs(data_dir, exist_ok=True)
    
    # Build a filename that uniquely identifies this query
    filename = f"{code}_{start}_{end}_{freq}_{adjust}.csv"
    filepath = os.path.join(data_dir, filename)
    
    if os.path.exists(filepath):
        print(f"Loading from cache: {filepath}")
        df = pd.read_csv(filepath, index_col='date', parse_dates=True)
        return df
    
    # Not cached — download
    print(f"Downloading: {code} ({start} to {end})")
    df = get_stock_data(code, start, end, freq, adjust)
    
    if not df.empty:
        df.to_csv(filepath)
        print(f"Saved to cache: {filepath}")
    
    return df

import matplotlib
import matplotlib.pyplot as plt

# Chinese font fix — run once per notebook
matplotlib.rcParams['font.sans-serif'] = [
    'PingFang HK', 'Microsoft YaHei', 'SimHei',
    'WenQuanYi Micro Hei', 'Arial Unicode MS'
]
matplotlib.rcParams['axes.unicode_minus'] = False



def plot_stock(df, title='', ma_window=20, save_path=None):
    """
    Two-panel price+volume chart with optional moving average.
    
    Parameters:
        df:        DataFrame with DatetimeIndex, columns: open, high, low, close, volume
        title:     chart title
        ma_window: moving average window (set to None to skip)
        save_path: if provided, saves the figure to this path
    """
    fig, (ax_price, ax_vol) = plt.subplots(
        2, 1, figsize=(12, 7), sharex=True,
        gridspec_kw={'height_ratios': [3, 1]}
    )
    
    # Price panel
    ax_price.plot(df.index, df['close'], linewidth=1.2, label='收盘价')
    if ma_window and len(df) >= ma_window:
        ma = df['close'].rolling(ma_window).mean()
        ax_price.plot(df.index, ma, linewidth=1, alpha=0.7,
                      label=f'{ma_window}日均线')
    ax_price.set_title(title, fontsize=14)
    ax_price.legend(fontsize=10)
    ax_price.set_ylabel('价格 (元)')
    
    # Volume panel with color coding
    colors = ['green' if c >= o else 'red' 
              for c, o in zip(df['close'], df['open'])]
    ax_vol.bar(df.index, df['volume'], color=colors, alpha=0.6, width=1)
    ax_vol.set_ylabel('成交量')
    
    fig.tight_layout()
    
    if save_path:
        os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    
    plt.show()


def detect_gaps(df, max_gap_days=5):
    """
    Find trading gaps longer than max_gap_days calendar days.
    Normal weekends are 2 days, holidays up to ~7 days (春节).
    Gaps longer than max_gap_days likely indicate 停牌.
    
    Returns a DataFrame of gaps with start date, end date, 
    and gap length in calendar days.
    """
    # Compute calendar days between consecutive trading days
    date_diff = df.index.to_series().diff().dt.days
    
    gaps = date_diff[date_diff > max_gap_days]
    
    if gaps.empty:
        return pd.DataFrame(columns=['resume_date', 'last_trade_date', 'calendar_days'])
    
    result = pd.DataFrame({
        'resume_date': gaps.index,
        'last_trade_date': df.index[df.index.get_indexer(gaps.index) - 1],
        'calendar_days': gaps.values
    })
    
    return result