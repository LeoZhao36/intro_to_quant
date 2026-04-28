"""
project2_utils.py

Utilities for Project 2: Volatility and Risk.
Ports over the Project 1 helpers and adds the limit-hit detection
utility that was deferred from Session 3.
"""

import os
import pandas as pd
import numpy as np
import baostock as bs

def to_baostock_code(six_digit):
    """
    Convert a 6-digit stock code to baostock's prefixed format.

    Shanghai: codes starting with 6 → sh.XXXXXX
    Shenzhen: codes starting with 0 or 3 → sz.XXXXXX
    Beijing: codes starting with 4 or 8 → bj.XXXXXX

    >>> to_baostock_code("600000")
    'sh.600000'
    >>> to_baostock_code("000001")
    'sz.000001'
    """
    code = str(six_digit).zfill(6)
    first = code[0]
    if first == "6":
        return f"sh.{code}"
    elif first in ("0", "3"):
        return f"sz.{code}"
    elif first in ("4", "8"):
        return f"bj.{code}"
    else:
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
        '前复权' is the default ('qfq'). Pass 'hfq' for 后复权 or
        'none' for unadjusted. Adjustment type matters: unadjusted
        prices will show fake crashes around splits and dividends.

    Returns
    -------
    pd.DataFrame indexed by datetime, with columns:
        open, high, low, close, volume, amount, pctChg
    All numeric columns are floats. NaN for suspended days.
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
    Load cached data if the file exists, otherwise pull from baostock
    and cache it. Cache key is (code, start, end, adjust).

    Caveat: if you change the date range, you get a new file. This
    wrapper does not merge partial caches. Good enough for project work,
    insufficient for production.
    """
    os.makedirs(cache_dir, exist_ok=True)
    safe_code = code.replace(".", "_")
    filename = f"{safe_code}_{start_date}_{end_date}_{adjust}.csv"
    filepath = os.path.join(cache_dir, filename)

    if os.path.exists(filepath):
        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        return df

    df = get_stock_data(code, start_date, end_date, adjust=adjust)
    if not df.empty:
        df.to_csv(filepath)
    return df


def detect_limit_hits(returns, codes=None, tolerance=0.002, return_type="log"):
    """
    Detect limit-up (涨停) and limit-down (跌停) days.

    Parameters
    ----------
    returns : pd.Series or pd.DataFrame
        Daily returns. Can be log or simple; specify which via `return_type`.
    codes : str, list, or None
        Baostock-formatted codes. Required if returns is a Series
        (pass as str) or DataFrame (pass as list matching columns).
        Used to determine the limit: ±10% main board, ±20% ChiNext/STAR,
        ±30% BSE.
    tolerance : float
        Band around the theoretical limit in simple-return units. 0.002
        means a simple return of +9.8% to +10.0% counts as a limit-up hit.
    return_type : str
        'log' (default) or 'simple'. If 'log', the function converts to
        simple returns internally before applying thresholds.

    Returns
    -------
    If returns is a Series: a DataFrame with columns 'limit_up' and
        'limit_down', boolean, same index as returns.
    If returns is a DataFrame: a dict of such DataFrames keyed by column.
    """
    if return_type not in ("log", "simple"):
        raise ValueError("return_type must be 'log' or 'simple'.")

    def _limit_pct(code):
        """Return the upper limit in simple-return units (0.10, 0.20, or 0.30)."""
        bare = code.split(".")[-1]
        if bare.startswith("300") or bare.startswith("688"):
            return 0.20  # 创业板 / 科创板
        if bare.startswith("4") or bare.startswith("8"):
            return 0.30  # 北交所
        return 0.10  # main board

    def _to_simple(ret_series):
        """Convert to simple returns if input is log returns."""
        if return_type == "log":
            return np.exp(ret_series) - 1
        return ret_series

    def _detect_single(ret_series, code):
        simple_ret = _to_simple(ret_series)
        limit = _limit_pct(code)
        up = simple_ret >= (limit - tolerance)
        down = simple_ret <= -(limit - tolerance)
        return pd.DataFrame(
            {"limit_up": up, "limit_down": down},
            index=ret_series.index,
        )

    if isinstance(returns, pd.Series):
        if not isinstance(codes, str):
            raise ValueError("For a Series, pass codes as a single string.")
        return _detect_single(returns, codes)

    if isinstance(returns, pd.DataFrame):
        if not isinstance(codes, list) or len(codes) != len(returns.columns):
            raise ValueError("For a DataFrame, pass codes as a list matching columns.")
        return {
            col: _detect_single(returns[col], code)
            for col, code in zip(returns.columns, codes)
        }

    raise TypeError("returns must be Series or DataFrame.")


# ----- Drawdown functions (promoted from Session 2) -----

def compute_drawdown(returns):
    """
    Compute drawdown series from a returns Series.

    Parameters
    ----------
    returns : pd.Series
        Daily returns. Must not contain NaN; fails loudly if it does.

    Returns
    -------
    drawdown : pd.Series
        (equity - running_peak) / running_peak. Always <= 0.
    equity : pd.Series
        Cumulative return path, starting at 1.0-step ahead of day 1 value.
    running_peak : pd.Series
        Running maximum of equity. Flat or rising, never falling.
    """
    assert returns.notna().all(), (
        "compute_drawdown: returns contain NaN. "
        "Check for first-row NaN from pct_change() or suspended-stock gaps. "
        "Drop or fill before calling."
    )
    equity = (1 + returns).cumprod()
    running_peak = equity.cummax()
    drawdown = (equity - running_peak) / running_peak
    return drawdown, equity, running_peak


def drawdown_details(returns):
    """
    Summarise the worst drawdown in a returns series.

    Returns a dict with:
        max_dd                    : minimum value of the drawdown series (a negative number)
        peak_date                 : date of the equity high that preceded the max drawdown
        trough_date               : date of the max drawdown itself
        recovery_date             : first date after the trough where equity >= prior peak,
                                    or None if the series has not yet recovered
        peak_to_trough_days       : number of rows between peak and trough
        trough_to_recovery_days   : number of rows between trough and recovery, or None
        total_underwater_days     : peak_to_trough_days + trough_to_recovery_days, or None
    """
    drawdown, equity, running_peak = compute_drawdown(returns)

    trough_date = drawdown.idxmin()
    peak_date = equity.loc[:trough_date].idxmax()
    peak_value = equity.loc[peak_date]

    post_trough = equity.loc[trough_date:]
    above_peak = post_trough[post_trough >= peak_value]
    recovery_date = above_peak.index[0] if len(above_peak) > 0 else None

    peak_idx = equity.index.get_loc(peak_date)
    trough_idx = equity.index.get_loc(trough_date)
    peak_to_trough_days = trough_idx - peak_idx

    if recovery_date is not None:
        recovery_idx = equity.index.get_loc(recovery_date)
        trough_to_recovery_days = recovery_idx - trough_idx
        total_underwater_days = recovery_idx - peak_idx
    else:
        trough_to_recovery_days = None
        total_underwater_days = None

    return {
        'max_dd': drawdown.min(),
        'peak_date': peak_date,
        'trough_date': trough_date,
        'recovery_date': recovery_date,
        'peak_to_trough_days': peak_to_trough_days,
        'trough_to_recovery_days': trough_to_recovery_days,
        'total_underwater_days': total_underwater_days,
    }


# ----- Sharpe ratio -----

TRADING_DAYS_A_SHARE = 242  # approximate; varies 242-244 depending on lunar calendar

def compute_sharpe(returns, rf_annual=0.0, trading_days=TRADING_DAYS_A_SHARE):
    """
    Annualised Sharpe ratio.

    Sharpe_annual = sqrt(T) * (mean(returns) - rf_daily) / std(returns)

    Parameters
    ----------
    returns : pd.Series
        Daily returns. Must not contain NaN.
    rf_annual : float, default 0.0
        Annual risk-free rate in decimal form. 0.02 = 2% per year.
        Default 0.0 gives the raw (no-risk-free-subtracted) Sharpe.
    trading_days : int, default 242
        Trading days per year. 242 for A-shares, 252 for US.

    Returns
    -------
    float
        Annualised Sharpe ratio. Dimensionless.
    """
    assert returns.notna().all(), (
        "compute_sharpe: returns contain NaN. Drop or fill before calling."
    )
    rf_daily = rf_annual / trading_days
    excess = returns - rf_daily
    daily_sharpe = excess.mean() / returns.std()
    return np.sqrt(trading_days) * daily_sharpe


def build_sharpe_table(returns_dict):
    rows = []
    for label, returns in returns_dict.items():
        ann_mean = returns.mean() * TRADING_DAYS_A_SHARE
        ann_std  = returns.std()  * np.sqrt(TRADING_DAYS_A_SHARE)
        sharpe   = compute_sharpe(returns, rf_annual=0.0)
        rows.append({
            'Label':    label,
            'Ann_Mean': ann_mean,
            'Ann_Std':  ann_std,
            'Sharpe':   sharpe,
        })
    return (pd.DataFrame(rows)
              .set_index('Label')
              .sort_values('Sharpe', ascending=False))


def compute_sortino(returns, target_annual=0.0, trading_days=TRADING_DAYS_A_SHARE):
    """
    Annualised Sortino ratio. Same shape as Sharpe, but the denominator is
    downside deviation: sqrt of mean squared shortfall below target,
    averaged over ALL days (above-target days contribute 0).

    Returns np.inf if there are no below-target days (undefined denominator).
    """
    assert returns.notna().all(), (
        "compute_sortino: returns contain NaN. Drop or fill before calling."
    )
    target_daily = target_annual / trading_days
    excess = returns - target_daily
    shortfall_sq = np.minimum(excess, 0) ** 2
    dd_daily = np.sqrt(shortfall_sq.mean())
    if dd_daily == 0:
        return np.inf
    return np.sqrt(trading_days) * excess.mean() / dd_daily


def _get_board_limit(code):
    """
    Daily price-limit percentage from baostock-format stock code.

    Rules:
      - 300xxx / 301xxx (创业板): ±20%
      - 688xxx (科创板): ±20%
      - 43xxx / 83xxx / 87xxx / 92xxx (北交所): ±30%
      - Everything else (主板 SH / SZ): ±10%

    Does NOT handle ST/*ST. 主板 ST was ±5% until mid-2025, then ±10%.
    创业板/科创板 ST stayed at ±20% throughout. Name-level data would
    be needed to detect ST status, not included here.
    """
    prefix_code = code.split('.')[-1] if '.' in code else code
    first_three = prefix_code[:3]
    first_two = prefix_code[:2]

    if first_three in ('300', '301'):
        return 0.20
    if first_three == '688':
        return 0.20
    if first_two in ('43', '83', '87', '92'):
        return 0.30
    return 0.10


def detect_limit_hits(df, code, tolerance=0.002):
    """
    Identify close-at-limit (封板) days for an A-share stock.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with a 'close' column, sorted by date ascending.
    code : str
        baostock-format stock code, e.g. 'sh.600000' or 'sz.300348'.
    tolerance : float, default 0.002
        Absolute tolerance in return-space. Absorbs rounding and 前复权
        dividend-adjustment drift around limit days.

    Returns
    -------
    pd.DataFrame, same index as df, columns:
        daily_return : float, close-to-close simple return
        board_limit  : float, ±% for this stock's board
        limit_up     : bool, close within tolerance of (+board_limit)
        limit_down   : bool, close within tolerance of (-board_limit)
        any_limit    : bool, limit_up OR limit_down

    Notes
    -----
    Measures sealed-limit closes only. Intraday-touched-but-closed-off
    days are NOT flagged. Daily data cannot distinguish these cases.
    First row has NaN return and is forced to non-limit.
    """
    import pandas as pd

    limit = _get_board_limit(code)
    daily_return = df['close'].pct_change()

    out = pd.DataFrame(index=df.index)
    out['daily_return'] = daily_return
    out['board_limit'] = limit
    out['limit_up'] = (daily_return - limit).abs() < tolerance
    out['limit_down'] = (daily_return + limit).abs() < tolerance
    out['any_limit'] = out['limit_up'] | out['limit_down']

    # First row has NaN return; force non-limit.
    first_idx = df.index[0]
    out.loc[first_idx, ['limit_up', 'limit_down', 'any_limit']] = False

    return out


def _round_half_away(x, decimals=2):
    """A-share price rounding convention: half away from zero."""
    import numpy as np
    factor = 10 ** decimals
    return np.sign(x) * np.floor(np.abs(x) * factor + 0.5) / factor


def detect_limit_hits(df, code, override_limit=None, price_tolerance=0.005):
    """
    Identify close-at-limit (封板) days for an A-share stock.

    Price-based detection: reconstructs the exchange-computed limit price
    from previous close and limit percentage, then checks whether the
    actual close equals that price. Correct at all price levels, including
    sub-1-元 crisis regimes where return-based detection breaks down due
    to fen-rounding making the true limit return deviate from the nominal
    percentage by up to ±1%.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with a 'close' column, sorted by date ascending.
    code : str
        baostock-format stock code. Used to infer board limit IF
        override_limit is None.
    override_limit : float, optional
        If provided, bypasses the prefix-based inference. Use for 主板 ST
        pre-July-2025 (0.05) and other special regimes.
    price_tolerance : float, default 0.005
        Half a fen. Effectively exact-match with robustness to float
        arithmetic edge cases.

    Returns
    -------
    pd.DataFrame, same index as df, columns:
        daily_return      : float, close-to-close simple return
        board_limit       : float, ±% for this stock's board
        limit_up_price    : float, reconstructed 涨停价
        limit_down_price  : float, reconstructed 跌停价
        limit_up          : bool
        limit_down        : bool
        any_limit         : bool
    """
    import pandas as pd

    limit = override_limit if override_limit is not None else _get_board_limit(code)
    prev_close = df['close'].shift(1)
    daily_return = df['close'].pct_change()

    limit_up_price = _round_half_away(prev_close * (1 + limit), 2)
    limit_down_price = _round_half_away(prev_close * (1 - limit), 2)

    out = pd.DataFrame(index=df.index)
    out['daily_return'] = daily_return
    out['board_limit'] = limit
    out['limit_up_price'] = limit_up_price
    out['limit_down_price'] = limit_down_price
    out['limit_up'] = (df['close'] - limit_up_price).abs() < price_tolerance
    out['limit_down'] = (df['close'] - limit_down_price).abs() < price_tolerance
    out['any_limit'] = out['limit_up'] | out['limit_down']

    # First row has NaN prev_close; force non-limit.
    first_idx = df.index[0]
    out.loc[first_idx, ['limit_up', 'limit_down', 'any_limit']] = False

    return out


def _smoke_test_limit_detection():
    import pandas as pd

    # Board-limit lookup.
    assert _get_board_limit('sh.600000') == 0.10
    assert _get_board_limit('sh.601211') == 0.10
    assert _get_board_limit('sz.000001') == 0.10
    assert _get_board_limit('sz.002020') == 0.10
    assert _get_board_limit('sz.300348') == 0.20
    assert _get_board_limit('sh.688256') == 0.20
    assert _get_board_limit('bj.830809') == 0.30

    # 5-day synthetic series with known returns:
    #   Day 1: 10.00  base
    #   Day 2: 11.00  +10% (主板 limit-up)
    #   Day 3: 12.10  +10% (limit-up again)
    #   Day 4: 10.89  -10% (limit-down)
    #   Day 5: 10.89   0%
    prices = pd.Series(
        [10.00, 11.00, 12.10, 10.89, 10.89],
        index=pd.date_range('2024-01-01', periods=5, freq='B')
    )
    df_test = pd.DataFrame({'close': prices})

    # Main-board stock: should see 3 limit days.
    r = detect_limit_hits(df_test, 'sh.600000')
    assert r['limit_up'].iloc[1], 'Day 2 should be limit-up'
    assert r['limit_up'].iloc[2], 'Day 3 should be limit-up'
    assert r['limit_down'].iloc[3], 'Day 4 should be limit-down'
    assert r['any_limit'].sum() == 3
    assert not r['limit_up'].iloc[0], 'Day 1 forced to non-limit'

    # Same series, 科创板 code: 10% moves are NOT limits there.
    r_kc = detect_limit_hits(df_test, 'sh.688999')
    assert r_kc['any_limit'].sum() == 0, '10% moves on 科创板 are not limits'

    print('limit detection smoke test: OK')

    crisis_prices = pd.Series(
        [0.71, 0.67, 0.64, 0.61],
        index=pd.date_range('2024-05-01', periods=4, freq='B')
    )
    df_crisis = pd.DataFrame({'close': crisis_prices})
    r_crisis = detect_limit_hits(df_crisis, 'sz.002435', override_limit=0.05)
    n_down_detected = int(r_crisis['limit_down'].sum())
    assert n_down_detected == 3, (
        f'Expected 3 跌停 days in low-price crisis test, got {n_down_detected}. '
        'Price-based detection must catch fen-rounded limit prices.'
    )

    # Verify the daily returns deviate from clean -5% in both directions,
    # demonstrating this test would fail under return-based detection.
    returns = r_crisis['daily_return'].dropna()
    assert returns.max() > -0.045, 'Expected some returns above -4.5% (rounding up)'
    assert returns.min() < -0.055, 'Expected some returns below -5.5% (rounding down)'


def _smoke_test_sortino():
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0.001, 0.01, 2420))

    # For positive-mean returns, Sortino should exceed Sharpe
    sharpe  = compute_sharpe(returns, rf_annual=0.0)
    sortino = compute_sortino(returns, target_annual=0.0)
    assert sortino > sharpe

    # All-positive returns: undefined denominator, Sortino = +inf
    assert np.isinf(compute_sortino(pd.Series([0.01, 0.02, 0.005])))

    # Mostly-downside returns: negative Sortino
    mostly_down = pd.Series([-0.01, -0.02, 0.005, -0.005, -0.01])
    assert compute_sortino(mostly_down) < 0

    # NaN guard
    try:
        compute_sortino(pd.Series([np.nan, 0.01]))
        raise RuntimeError("should have raised on NaN input")
    except AssertionError:
        pass

    print("sortino smoke test passed")


def _smoke_test_sharpe():
    """Verify the sqrt(T) scaling and the rf-invariance of ranking."""
    np.random.seed(42)

    # Test 1: sqrt(T) scaling is correct
    returns = pd.Series(np.random.normal(0.001, 0.01, 2420))
    daily_sharpe_manual = returns.mean() / returns.std()
    annual_sharpe = compute_sharpe(returns, rf_annual=0.0)
    expected = np.sqrt(242) * daily_sharpe_manual
    assert abs(annual_sharpe - expected) < 1e-9, "sqrt(T) scaling wrong"

    # Test 2: changing rf shifts but does not change ranking
    better = pd.Series(np.random.normal(0.002, 0.01, 2420))
    s1_rf0 = compute_sharpe(returns, rf_annual=0.0)
    s2_rf0 = compute_sharpe(better, rf_annual=0.0)
    s1_rf2 = compute_sharpe(returns, rf_annual=0.02)
    s2_rf2 = compute_sharpe(better, rf_annual=0.02)
    assert s1_rf0 < s2_rf0 and s1_rf2 < s2_rf2, "rf shift changed ranking"

    # Test 3: NaN guard
    try:
        compute_sharpe(pd.Series([np.nan, 0.01, 0.02]))
        raise RuntimeError("should have raised on NaN input")
    except AssertionError:
        pass

    print("sharpe smoke test passed")


def _smoke_test_drawdown():
    """Known case: returns = [+0.10, -0.20, +0.15]."""
    returns = pd.Series(
        [0.10, -0.20, 0.15],
        index=pd.date_range('2024-01-02', periods=3, freq='B')
    )
    drawdown, equity, running_peak = compute_drawdown(returns)

    assert abs(equity.iloc[0] - 1.10) < 1e-9
    assert abs(equity.iloc[1] - 0.88) < 1e-9
    assert abs(equity.iloc[2] - 1.012) < 1e-9
    assert (abs(running_peak - 1.10) < 1e-9).all()
    assert abs(drawdown.iloc[0]) < 1e-9
    assert abs(drawdown.iloc[1] - (-0.20)) < 1e-9
    assert abs(drawdown.iloc[2] - (-0.08)) < 1e-9

    details = drawdown_details(returns)
    assert abs(details['max_dd'] - (-0.20)) < 1e-9
    assert details['trough_date'] == returns.index[1]
    assert details['peak_date'] == returns.index[0]
    assert details['recovery_date'] is None  # never recovers in this 3-point series
    assert details['peak_to_trough_days'] == 1

    # NaN guard: should raise
    bad_returns = pd.Series([np.nan, 0.05, -0.03])
    try:
        compute_drawdown(bad_returns)
        raise RuntimeError("compute_drawdown should have raised on NaN input")
    except AssertionError:
        pass  # expected

    print("drawdown smoke test passed")


def execute_smoke_tests():
    # ... existing calls ...
    _smoke_test_drawdown()
    _smoke_test_sharpe()
    _smoke_test_sortino()
    _smoke_test_limit_detection()
    print("All smoke tests passed.")


# ─── SMOKE TESTS ────────────────────────────────────────────
def _smoke_test():
    """Run quick correctness checks. Call manually or on import in dev."""
    # to_baostock_code
    assert to_baostock_code("600000") == "sh.600000"
    assert to_baostock_code("000001") == "sz.000001"
    assert to_baostock_code("300750") == "sz.300750"

    # detect_limit_hits on a known case:
    # 寒武纪 (sh.688256, 科创板, ±20% limit) hit +20% on 2023-04-20.
    # log return was ln(1.20) = 0.1823.
    test_ret = pd.Series([0.1823], index=pd.to_datetime(["2023-04-20"]))
    flags = detect_limit_hits(test_ret, codes="sh.688256", return_type="log")
    assert flags["limit_up"].iloc[0] == True, "Failed to detect 寒武纪 limit-up"
    assert flags["limit_down"].iloc[0] == False

    # Same price move, but on a main-board stock (±10% limit):
    # log return of 0.1823 is way above main-board limit, should still flag
    flags = detect_limit_hits(test_ret, codes="sh.600000", return_type="log")
    assert flags["limit_up"].iloc[0] == True

    # Simple-return input path:
    test_ret_simple = pd.Series([0.20], index=pd.to_datetime(["2023-04-20"]))
    flags = detect_limit_hits(test_ret_simple, codes="sh.688256", return_type="simple")
    assert flags["limit_up"].iloc[0] == True

    print("All smoke tests passed.")


if __name__ == "__main__":
    _smoke_test()


# ─── Project 2 Session 5: risk report module ───────────────

TRADING_DAYS = 242
RF_ANNUAL = 0.018  # illustrative, 1y 国债 yield ~1.5-2%


def compute_drawdown(returns):
    """Return a DataFrame with cumulative equity, running max, and drawdown."""
    cum = (1 + returns).cumprod()
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    return pd.DataFrame({'cum': cum, 'running_max': running_max, 'drawdown': dd})


def risk_report(returns, label='', rf_annual=RF_ANNUAL, limits_series=None):
    """
    Full risk report for a daily return series.

    Conventions:
      - ann_return_arith: daily mean * 242, matches sqrt(242) vol scaling.
      - ann_return_geom: compounded actual path.
      - Excess kurtosis (pandas default), so 0 = normal.
      - Sharpe and Sortino annualised with sqrt(242).
    """
    returns = returns.dropna()
    n = len(returns)
    ann_factor = np.sqrt(TRADING_DAYS)
    rf_daily = rf_annual / TRADING_DAYS
    excess = returns - rf_daily

    total_return = (1 + returns).prod() - 1
    ann_return_arith = returns.mean() * TRADING_DAYS
    ann_return_geom = (1 + total_return) ** (TRADING_DAYS / n) - 1
    ann_std = returns.std() * ann_factor

    sharpe = (excess.mean() / returns.std() * ann_factor) if returns.std() > 0 else np.nan
    downside = returns[returns < rf_daily]
    sortino = (excess.mean() / downside.std() * ann_factor) if (len(downside) > 1 and downside.std() > 0) else np.nan

    dd_df = compute_drawdown(returns)
    max_dd = dd_df['drawdown'].min()
    trough_date = dd_df['drawdown'].idxmin()
    pre_trough = dd_df.loc[:trough_date]
    peak_date = pre_trough['cum'].idxmax()
    dd_days_to_trough = (trough_date - peak_date).days
    recovery = dd_df.loc[trough_date:, 'drawdown']
    recovery_date = recovery[recovery >= 0].index[0] if (recovery >= 0).any() else None
    dd_recovery_days = (recovery_date - trough_date).days if recovery_date is not None else None

    report = {
        'label': label,
        'n_days': n,
        'total_return': total_return,
        'ann_return_arith': ann_return_arith,
        'ann_return_geom': ann_return_geom,
        'ann_std': ann_std,
        'sharpe': sharpe,
        'sortino': sortino,
        'max_drawdown': max_dd,
        'dd_peak_date': peak_date,
        'dd_trough_date': trough_date,
        'dd_days_to_trough': dd_days_to_trough,
        'dd_recovery_days': dd_recovery_days,
        'skewness': returns.skew(),
        'excess_kurtosis': returns.kurtosis(),
    }
    if limits_series is not None:
        aligned = limits_series.reindex(returns.index).fillna(False)
        n_hits = int(aligned.sum())
        report['limit_hit_count'] = n_hits
        report['limit_hit_fraction'] = n_hits / n
    return report


def print_risk_report(report):
    print(f"=== {report['label']} ===")
    print(f"  n_days:              {report['n_days']}")
    print(f"  total_return:        {report['total_return']*100:>7.2f}%")
    print(f"  ann_return (arith):  {report['ann_return_arith']*100:>7.2f}%")
    print(f"  ann_return (geom):   {report['ann_return_geom']*100:>7.2f}%")
    print(f"  ann_std:             {report['ann_std']*100:>7.2f}%")
    print(f"  sharpe (rf={RF_ANNUAL*100:.1f}%):    {report['sharpe']:>7.2f}")
    print(f"  sortino:             {report['sortino']:>7.2f}")
    print(f"  max_drawdown:        {report['max_drawdown']*100:>7.2f}%")
    print(f"  peak -> trough:      {report['dd_days_to_trough']:>3} days  "
          f"({report['dd_peak_date'].date()} -> {report['dd_trough_date'].date()})")
    rec = report['dd_recovery_days']
    print(f"  trough -> recovery:  {rec if rec is not None else 'not recovered'} days")
    print(f"  skewness:            {report['skewness']:>7.2f}")
    print(f"  excess kurtosis:     {report['excess_kurtosis']:>7.2f}")
    if 'limit_hit_count' in report:
        print(f"  limit hits:          {report['limit_hit_count']} "
              f"({report['limit_hit_fraction']*100:.2f}%)")
    print()


def _smoke_test_risk_report():
    """Constant positive returns → max_dd = 0, ann_std = 0. Noise → nonzero drawdown."""
    n = 250
    idx = pd.date_range('2024-01-01', periods=n, freq='B')
    constant = pd.Series([0.001] * n, index=idx)
    r = risk_report(constant, 'smoke_constant')
    assert abs(r['max_drawdown']) < 1e-10, f"expected 0 drawdown, got {r['max_drawdown']}"
    assert abs(r['ann_std']) < 1e-10, f"expected 0 std, got {r['ann_std']}"
    assert r['n_days'] == n

    rng = np.random.default_rng(0)
    noise = pd.Series(rng.normal(0, 0.01, n), index=idx)
    r2 = risk_report(noise, 'smoke_noise')
    assert r2['max_drawdown'] < 0
    assert r2['ann_std'] > 0
    assert r2['dd_days_to_trough'] > 0