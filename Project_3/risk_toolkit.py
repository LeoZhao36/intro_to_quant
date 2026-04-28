"""
risk_toolkit.py

Risk metrics for A-share quant work. Clean consolidation of the Project 2
risk functions into a single module with one canonical definition for each
metric.

Functions
---------
compute_drawdown   : cumulative equity, running max, drawdown series
drawdown_details   : peak / trough / recovery dates and durations
compute_sharpe     : annualised Sharpe ratio
compute_sortino    : annualised Sortino ratio (Sortino-Price 1994)
detect_limit_hits  : 涨停/跌停 detection via reconstructed limit prices
risk_report        : combined report dict
print_risk_report  : human-readable output of risk_report

Sortino convention (important)
------------------------------
This module uses the Sortino-Price 1994 Target Downside Deviation:
    TDD = sqrt( mean( min(R_i - T, 0)^2 ) )
averaged over ALL observations, where above-target days contribute zero.
This is distinct from a 'std of downside-only returns' formulation that
centres around the mean of the downside subset rather than around the
target. The two produce different numbers on the same data. If you
have older Sortino values reported from a previous codebase, verify
which formula produced them before comparing.
"""

import numpy as np
import pandas as pd


# ─── Module constants ────────────────────────────────────────

TRADING_DAYS_A_SHARE = 242  # Approximate; varies 242-244 with lunar calendar.
RF_ANNUAL = 0.018            # Illustrative. 1y 国债 yield ~1.5-2% recently.


# ─── Drawdown ────────────────────────────────────────────────

def compute_drawdown(returns):
    """
    Compute cumulative equity, running peak, and drawdown from a returns Series.

    Parameters
    ----------
    returns : pd.Series
        Daily returns. Must not contain NaN; fails loudly if it does.

    Returns
    -------
    pd.DataFrame
        Columns: 'cum' (cumulative equity), 'running_max' (running maximum of
        cum), 'drawdown' ((cum - running_max) / running_max, always <= 0).
        Indexed by the same dates as `returns`.
    """
    assert returns.notna().all(), (
        "compute_drawdown: returns contain NaN. "
        "Check for first-row NaN from pct_change() or suspended-stock gaps. "
        "Drop or fill before calling."
    )
    cum = (1 + returns).cumprod()
    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max
    return pd.DataFrame({
        'cum': cum,
        'running_max': running_max,
        'drawdown': drawdown,
    })


def drawdown_details(returns):
    """
    Summarise the worst drawdown in a returns series.

    Returns
    -------
    dict with keys:
        max_dd                   : minimum value of drawdown (negative number)
        peak_date                : date of equity high preceding max drawdown
        trough_date              : date of max drawdown
        recovery_date            : first date after trough where equity >= prior peak,
                                   or None if not yet recovered
        peak_to_trough_days      : row count from peak to trough
        trough_to_recovery_days  : row count from trough to recovery, or None
        total_underwater_days    : peak_to_trough_days + trough_to_recovery_days, or None
    """
    dd_df = compute_drawdown(returns)
    equity = dd_df['cum']
    drawdown = dd_df['drawdown']

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


# ─── Sharpe ──────────────────────────────────────────────────

def compute_sharpe(returns, rf_annual=0.0, trading_days=TRADING_DAYS_A_SHARE):
    """
    Annualised Sharpe ratio.

        Sharpe = sqrt(T) * (mean(returns) - rf_daily) / std(returns)

    Parameters
    ----------
    returns : pd.Series
        Daily returns. Must not contain NaN.
    rf_annual : float, default 0.0
        Annual risk-free rate as a decimal. 0.02 = 2%/yr.
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


# ─── Sortino ─────────────────────────────────────────────────

def compute_sortino(returns, target_annual=0.0, trading_days=TRADING_DAYS_A_SHARE):
    """
    Annualised Sortino ratio (Sortino-Price 1994 definition).

        Sortino = sqrt(T) * (mean(returns) - target_daily) / TDD

    where
        TDD = sqrt( mean( min(R_i - target_daily, 0)^2 ) )

    averaged over ALL days. Above-target days contribute zero to TDD.

    This is the textbook definition. A distinct 'std of downside-only
    returns' formulation is NOT what this function computes.

    Returns
    -------
    float
        Annualised Sortino ratio. +inf if the series never falls below
        target (TDD = 0). Negative if mean(returns) < target_daily.
    """
    assert returns.notna().all(), (
        "compute_sortino: returns contain NaN. Drop or fill before calling."
    )
    target_daily = target_annual / trading_days
    excess = returns - target_daily
    shortfall_sq = np.minimum(excess, 0) ** 2
    tdd_daily = np.sqrt(shortfall_sq.mean())
    if tdd_daily == 0:
        return np.inf
    return np.sqrt(trading_days) * excess.mean() / tdd_daily


# ─── Limit-hit detection ─────────────────────────────────────

def _round_half_away(x, decimals=2):
    """A-share price rounding convention: half away from zero."""
    factor = 10 ** decimals
    return np.sign(x) * np.floor(np.abs(x) * factor + 0.5) / factor


def _get_board_limit(code):
    """
    Daily price-limit percentage inferred from baostock-format stock code.

    Rules:
      300xxx / 301xxx (创业板):           ±20%
      688xxx (科创板):                    ±20%
      43xxx / 83xxx / 87xxx / 92xxx (北交所): ±30%
      Everything else (主板 SH / SZ):      ±10%

    Does NOT handle ST/*ST. Use override_limit in detect_limit_hits for that.
    主板 ST was ±5% until mid-2025, then ±10%. 创业板/科创板 ST stayed at ±20%.
    """
    bare = code.split('.')[-1] if '.' in code else code
    first_three = bare[:3]
    first_two = bare[:2]

    if first_three in ('300', '301'):
        return 0.20
    if first_three == '688':
        return 0.20
    if first_two in ('43', '83', '87', '92'):
        return 0.30
    return 0.10


def detect_limit_hits(df, code, override_limit=None, price_tolerance=0.005):
    """
    Identify close-at-limit (封板) days via price reconstruction.

    Rebuilds the exchange-computed limit price from previous close and limit
    percentage, then checks whether actual close equals that price. Correct
    at all price levels, including sub-1元 regimes where return-based
    detection breaks down due to 分 rounding making the true limit return
    deviate from the nominal percentage by up to ±1%.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with a 'close' column, sorted by date ascending.
    code : str
        Baostock-format stock code. Used to infer board limit if
        override_limit is None.
    override_limit : float, optional
        Bypasses prefix-based inference. Use for 主板 ST pre-July-2025 (0.05)
        or other special regimes.
    price_tolerance : float, default 0.005
        Half a 分. Effectively exact-match with robustness to float
        arithmetic edge cases.

    Returns
    -------
    pd.DataFrame, same index as df, columns:
        daily_return, board_limit, limit_up_price, limit_down_price,
        limit_up (bool), limit_down (bool), any_limit (bool).

    Notes
    -----
    Measures sealed-limit closes only. Intraday-touched-but-closed-off
    days are NOT flagged. Daily data cannot distinguish these cases.
    """
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


# ─── Combined report ─────────────────────────────────────────

def risk_report(returns, label='', rf_annual=RF_ANNUAL, limits_series=None):
    """
    Full risk report for a daily return series.

    Uses compute_sharpe and compute_sortino from this module, so the values
    match what you'd get calling those functions directly. Sortino is
    Sortino-Price 1994.

    Conventions
    -----------
    ann_return_arith : daily mean * 242. Matches sqrt(242) vol scaling.
    ann_return_geom  : compounded actual path.
    excess_kurtosis  : pandas default, 0 = normal.

    Parameters
    ----------
    returns : pd.Series
        Daily returns. NaN rows are dropped.
    label : str
        Label carried through to the output dict for reporting.
    rf_annual : float
        Annual risk-free rate. Used as both the rf for Sharpe and the
        target for Sortino.
    limits_series : pd.Series, optional
        Boolean series indicating limit-hit days. If provided, limit_hit_count
        and limit_hit_fraction are added to the report.
    """
    returns = returns.dropna()
    n = len(returns)
    if n == 0:
        raise ValueError("risk_report: returns series is empty after dropna.")

    ann_factor = np.sqrt(TRADING_DAYS_A_SHARE)

    total_return = (1 + returns).prod() - 1
    ann_return_arith = returns.mean() * TRADING_DAYS_A_SHARE
    ann_return_geom = (1 + total_return) ** (TRADING_DAYS_A_SHARE / n) - 1
    ann_std = returns.std() * ann_factor

    sharpe = compute_sharpe(returns, rf_annual=rf_annual) if returns.std() > 0 else np.nan
    sortino = compute_sortino(returns, target_annual=rf_annual)

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
    """Pretty-print a risk_report dict."""
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


# ─── Smoke tests ─────────────────────────────────────────────

def _smoke_test_drawdown():
    """Known case: returns = [+0.10, -0.20, +0.15]."""
    returns = pd.Series(
        [0.10, -0.20, 0.15],
        index=pd.date_range('2024-01-02', periods=3, freq='B')
    )
    dd_df = compute_drawdown(returns)

    assert abs(dd_df['cum'].iloc[0] - 1.10) < 1e-9
    assert abs(dd_df['cum'].iloc[1] - 0.88) < 1e-9
    assert abs(dd_df['cum'].iloc[2] - 1.012) < 1e-9
    assert (abs(dd_df['running_max'] - 1.10) < 1e-9).all()
    assert abs(dd_df['drawdown'].iloc[0]) < 1e-9
    assert abs(dd_df['drawdown'].iloc[1] - (-0.20)) < 1e-9
    assert abs(dd_df['drawdown'].iloc[2] - (-0.08)) < 1e-9

    details = drawdown_details(returns)
    assert abs(details['max_dd'] - (-0.20)) < 1e-9
    assert details['trough_date'] == returns.index[1]
    assert details['peak_date'] == returns.index[0]
    assert details['recovery_date'] is None
    assert details['peak_to_trough_days'] == 1

    # NaN guard
    try:
        compute_drawdown(pd.Series([np.nan, 0.05, -0.03]))
        raise RuntimeError("compute_drawdown should have raised on NaN input")
    except AssertionError:
        pass

    print("drawdown smoke test: OK")


def _smoke_test_sharpe():
    """sqrt(T) scaling and rf-invariance of ranking."""
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0.001, 0.01, 2420))

    daily_sharpe_manual = returns.mean() / returns.std()
    annual_sharpe = compute_sharpe(returns, rf_annual=0.0)
    expected = np.sqrt(TRADING_DAYS_A_SHARE) * daily_sharpe_manual
    assert abs(annual_sharpe - expected) < 1e-9, "sqrt(T) scaling wrong"

    better = pd.Series(np.random.normal(0.002, 0.01, 2420))
    s1_rf0 = compute_sharpe(returns, rf_annual=0.0)
    s2_rf0 = compute_sharpe(better, rf_annual=0.0)
    s1_rf2 = compute_sharpe(returns, rf_annual=0.02)
    s2_rf2 = compute_sharpe(better, rf_annual=0.02)
    assert s1_rf0 < s2_rf0 and s1_rf2 < s2_rf2, "rf shift changed ranking"

    try:
        compute_sharpe(pd.Series([np.nan, 0.01, 0.02]))
        raise RuntimeError("should have raised on NaN input")
    except AssertionError:
        pass

    print("sharpe smoke test: OK")


def _smoke_test_sortino():
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0.001, 0.01, 2420))

    sharpe = compute_sharpe(returns, rf_annual=0.0)
    sortino = compute_sortino(returns, target_annual=0.0)
    # For positive-mean symmetric-ish noise, Sortino should exceed Sharpe
    # because TDD (downside-only) is smaller than std (full two-sided).
    assert sortino > sharpe, f"Expected sortino > sharpe, got {sortino} vs {sharpe}"

    # All-positive returns: TDD = 0, Sortino = +inf
    assert np.isinf(compute_sortino(pd.Series([0.01, 0.02, 0.005])))

    # Mostly-downside returns: negative Sortino
    mostly_down = pd.Series([-0.01, -0.02, 0.005, -0.005, -0.01])
    assert compute_sortino(mostly_down) < 0

    try:
        compute_sortino(pd.Series([np.nan, 0.01]))
        raise RuntimeError("should have raised on NaN input")
    except AssertionError:
        pass

    print("sortino smoke test: OK")


def _smoke_test_limit_detection():
    # Board-limit lookup
    assert _get_board_limit('sh.600000') == 0.10
    assert _get_board_limit('sz.000001') == 0.10
    assert _get_board_limit('sz.300348') == 0.20
    assert _get_board_limit('sz.301001') == 0.20
    assert _get_board_limit('sh.688256') == 0.20
    assert _get_board_limit('bj.830809') == 0.30

    # 5-day series with known outcomes:
    #   Day 1: 10.00   base
    #   Day 2: 11.00   +10% (主板 limit-up)
    #   Day 3: 12.10   +10% (limit-up again)
    #   Day 4: 10.89   -10% (limit-down)
    #   Day 5: 10.89    0%
    prices = pd.Series(
        [10.00, 11.00, 12.10, 10.89, 10.89],
        index=pd.date_range('2024-01-01', periods=5, freq='B')
    )
    df_test = pd.DataFrame({'close': prices})

    r = detect_limit_hits(df_test, 'sh.600000')
    assert r['limit_up'].iloc[1], 'Day 2 should be limit-up'
    assert r['limit_up'].iloc[2], 'Day 3 should be limit-up'
    assert r['limit_down'].iloc[3], 'Day 4 should be limit-down'
    assert r['any_limit'].sum() == 3
    assert not r['limit_up'].iloc[0], 'Day 1 forced to non-limit'

    # Same series, 科创板 code: 10% moves are NOT limits there.
    r_kc = detect_limit_hits(df_test, 'sh.688999')
    assert r_kc['any_limit'].sum() == 0, '10% moves on 科创板 are not limits'

    # Low-price crisis test with override_limit=0.05 (pre-July-2025 ST rule).
    # At sub-1 元 levels, 5% of 0.71 = 0.0355, which rounds to 0.04; so the
    # 'clean' -5% return cannot actually be realised and return-based
    # detection fails. Price-based detection catches it.
    crisis_prices = pd.Series(
        [0.71, 0.67, 0.64, 0.61],
        index=pd.date_range('2024-05-01', periods=4, freq='B')
    )
    df_crisis = pd.DataFrame({'close': crisis_prices})
    r_crisis = detect_limit_hits(df_crisis, 'sz.002435', override_limit=0.05)
    n_down = int(r_crisis['limit_down'].sum())
    assert n_down == 3, (
        f'Expected 3 跌停 days in low-price crisis test, got {n_down}. '
        'Price-based detection must catch 分-rounded limit prices.'
    )

    print("limit detection smoke test: OK")


def _smoke_test_risk_report():
    n = 250
    idx = pd.date_range('2024-01-01', periods=n, freq='B')

    constant = pd.Series([0.001] * n, index=idx)
    r = risk_report(constant, 'smoke_constant', rf_annual=0.0)
    assert abs(r['max_drawdown']) < 1e-10, f"expected 0 drawdown, got {r['max_drawdown']}"
    assert abs(r['ann_std']) < 1e-10, f"expected 0 std, got {r['ann_std']}"
    assert r['n_days'] == n

    rng = np.random.default_rng(0)
    noise = pd.Series(rng.normal(0, 0.01, n), index=idx)
    r2 = risk_report(noise, 'smoke_noise')
    assert r2['max_drawdown'] < 0
    assert r2['ann_std'] > 0
    assert r2['dd_days_to_trough'] > 0

    # risk_report Sharpe must match standalone compute_sharpe
    standalone_sharpe = compute_sharpe(noise, rf_annual=RF_ANNUAL)
    assert abs(r2['sharpe'] - standalone_sharpe) < 1e-12, (
        "risk_report sharpe must match standalone compute_sharpe"
    )

    # risk_report Sortino must match standalone compute_sortino
    standalone_sortino = compute_sortino(noise, target_annual=RF_ANNUAL)
    assert abs(r2['sortino'] - standalone_sortino) < 1e-12, (
        "risk_report sortino must match standalone compute_sortino"
    )

    print("risk_report smoke test: OK")


def execute_smoke_tests():
    """Run all smoke tests in this module."""
    _smoke_test_drawdown()
    _smoke_test_sharpe()
    _smoke_test_sortino()
    _smoke_test_limit_detection()
    _smoke_test_risk_report()
    print("All risk_toolkit smoke tests passed.")


if __name__ == "__main__":
    execute_smoke_tests()