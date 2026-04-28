import baostock as bs
import pandas as pd
import numpy as np

def get_stock_data(code, start, end, adjustflag='2'):
    """
    Pull daily OHLCV data from baostock.
    
    code: str, e.g. 'sz.000001'
    start, end: str in 'YYYY-MM-DD' format
    adjustflag: '1' = 后复权, '2' = 前复权, '3' = 不复权
    
    Returns a DataFrame with DatetimeIndex and float-typed OHLCV columns.
    """
    lg = bs.login()
    
    rs = bs.query_history_k_data_plus(
        code,
        "date,code,open,high,low,close,volume,amount",
        start_date=start,
        end_date=end,
        frequency="d",
        adjustflag=adjustflag
    )
    
    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())
    
    df = pd.DataFrame(data_list, columns=rs.fields)
    bs.logout()
    
    # Clean types: baostock returns everything as strings
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date')
    
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    return df