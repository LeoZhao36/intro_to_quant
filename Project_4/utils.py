import os
import pandas as pd
import baostock as bs


def to_baostock_code(six_digit):
    """
    Convert a 6-digit stock code to baostock's prefixed format.

    Shanghai: codes starting with 6   -> 'sh.XXXXXX'
    Shenzhen: codes starting with 0/3 -> 'sz.XXXXXX'
    Beijing:  codes starting with 4/8 -> 'bj.XXXXXX'

    Examples
    --------
    >>> to_baostock_code("600000")
    'sh.600000'
    >>> to_baostock_code("000001")
    'sz.000001'
    """
    code = str(six_digit).zfill(6)
    first = code[0]
    if first == "6":
        return f"sh.{code}"
    if first in ("0", "3"):
        return f"sz.{code}"
    if first in ("4", "8"):
        return f"bj.{code}"
    raise ValueError(f"Unknown exchange for code {code}")


def get_stock_data(code, start_date, end_date, adjust="qfq"):
    """
    Pull daily OHLCV data from baostock for a single stock.

    Parameters
    ----------
    code : str
        Baostock-formatted code, e.g. 'sh.600000' or 'sz.000001'.
    start_date, end_date : str
        Dates in 'YYYY-MM-DD' format.
    adjust : str
        'qfq' (default, 前复权), 'hfq' (后复权), or 'none'. Unadjusted
        prices will show fake crashes around splits and dividends; default
        to 'qfq' unless you have a specific reason not to.

    Returns
    -------
    pd.DataFrame
        Indexed by datetime. Columns: open, high, low, close, volume,
        amount, pctChg. All numeric columns are floats. NaN for suspended
        days.
    """
    adjust_map = {"qfq": "2", "hfq": "1", "none": "3"}
    if adjust not in adjust_map:
        raise ValueError(f"adjust must be one of {list(adjust_map.keys())}")

    bs.login()
    try:
        rs = bs.query_history_k_data_plus(
            code,
            "date,open,high,low,close,volume,amount,pctChg",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag=adjust_map[adjust],
        )
        if rs.error_code != "0":
            raise RuntimeError(f"baostock error: {rs.error_msg}")

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=rs.fields)
    finally:
        bs.logout()

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pctChg"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_or_fetch(code, start_date, end_date, cache_dir="data/prices", adjust="qfq"):
    """
    Load cached data if the CSV exists, otherwise pull from baostock and cache.

    Cache key is (code, start_date, end_date, adjust). Changing any of these
    produces a new file. Does not merge partial caches. Good enough for
    project work, insufficient for production.
    """
    os.makedirs(cache_dir, exist_ok=True)
    safe_code = code.replace(".", "_")
    filename = f"{safe_code}_{start_date}_{end_date}_{adjust}.csv"
    filepath = os.path.join(cache_dir, filename)

    if os.path.exists(filepath):
        return pd.read_csv(filepath, index_col=0, parse_dates=True)

    df = get_stock_data(code, start_date, end_date, adjust=adjust)
    if not df.empty:
        df.to_csv(filepath)
    return df


# ─── Smoke tests ────────────────────────────────────────────

def _smoke_test():
    """Correctness checks that do not require network access."""
    assert to_baostock_code("600000") == "sh.600000"
    assert to_baostock_code("000001") == "sz.000001"
    assert to_baostock_code("300750") == "sz.300750"
    assert to_baostock_code("688256") == "sh.688256"
    assert to_baostock_code("830809") == "bj.830809"

    # Leading zeros preserved
    assert to_baostock_code(1) == "sz.000001"

    # Unknown prefix should raise
    try:
        to_baostock_code("999999")
        raise RuntimeError("should have raised on unknown exchange prefix")
    except ValueError:
        pass

    print("utils smoke test: OK")


if __name__ == "__main__":
    _smoke_test()