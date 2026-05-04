"""
inspect_universes.py — Daily metrics per universe, aggregated by regime.

Pipeline
--------
For each (rebalance_date, universe) we know the set of in-universe stocks
from build_universe_panel. For each TRADING DAY between rebalance_date_t
and rebalance_date_{t+1}, we compute daily metrics over that universe
(taking membership as fixed at rebalance_date_t for the whole holding
week — standard quant convention).

Membership is weekly. Metrics are daily. The metric series is indexed
by trade_date.

Daily metrics (per universe per trade_date)
-------------------------------------------
Composition:
  n_stocks                  count of in-universe stocks with valid daily data
  mean_circ_mv_yi           mean 流通市值 in 亿 RMB
  median_circ_mv_yi         median 流通市值 in 亿 RMB
  mean_total_mv_yi          mean 总市值 in 亿 RMB
  pct_circ_to_total_mean    mean of circ_mv / total_mv (free-float ratio)

Liquidity:
  mean_amount_yi            mean daily 成交额 in 亿 RMB
  median_amount_yi
  mean_turnover_rate_f      mean free-float 换手率 (percent)
  median_turnover_rate_f

Returns and dispersion:
  ew_daily_return_pct       universe equal-weighted daily return, %
  cs_dispersion_pct         cross-sectional std of daily returns within universe, %
  pct_up                    fraction of stocks with positive return

Limit-hit (retail emotion proxy):
  pct_at_limit_up           fraction at limit-up (close ≥ prev_close × (1+lim) × 0.998)
  pct_at_limit_down         fraction at limit-down

Regime windows
--------------
W1 pre-新国九条
W2 新国九条 to PBoC stimulus
W3 post-PBoC stimulus
W4 entire post-新国九条 (W2 ∪ W3)

For each (universe, window) we compute:
  cumulative_geom_return_pct   product over (1+ew_daily_return)−1, in %
  ann_return_pct               geometrically annualized
  ann_vol_pct                  std(daily return) × sqrt(250)
  sharpe                       ann_return / ann_vol (no risk-free subtraction;
                               documenting it as a Sharpe-like ratio)
  mean_*                       averages of the daily metrics over the window
  n_trading_days

Outputs
-------
data/daily_universe_metrics.parquet   long-format daily metrics
data/universe_inspection_summary.csv  the headline comparison table
graphs/universe_*.png                 plots: cumulative returns, turnover,
                                       dispersion, limit-hit frequency

Usage
-----
    python inspect_universes.py smoke   # 30 trading days, all universes
    python inspect_universes.py full    # full panel
    python inspect_universes.py plots   # regenerate plots from cached data
"""

import logging
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd


def _setup_chinese_font():
    """
    Configure matplotlib to render Chinese characters correctly. Tries
    common Mac, Windows, and Linux CJK fonts in order. If none found,
    Chinese characters in plot labels will render as boxes; the rest of
    the plot still works.
    """
    candidates = [
        "Microsoft YaHei", "SimHei", "SimSun",            # Windows
        "Heiti SC", "Songti SC", "PingFang SC",            # macOS
        "Noto Sans CJK SC", "WenQuanYi Zen Hei",           # Linux
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            matplotlib.rcParams["font.sans-serif"] = [font]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return font
    # Fallback: no CJK font; emit a warning silently. Chinese will render
    # as boxes but the plot is still produced.
    matplotlib.rcParams["axes.unicode_minus"] = False
    return None


_setup_chinese_font()

from config import (
    A_SHARE_PATTERN,
    AMOUNT_QIANYUAN_TO_YI,
    CIRC_MV_WAN_TO_YI,
    CHINEXT_REGIME_CHANGE,
    DAILY_METRICS_PATH,
    DAILY_PANEL_DIR,
    GRAPHS_DIR,
    LIMIT_PROXIMITY,
    LIMIT_PCT_CHINEXT,
    LIMIT_PCT_MAIN,
    LIMIT_PCT_STAR,
    NEW_NINE_ARTICLES_DATE,
    PANEL_END,
    PBOC_STIMULUS_DATE,
    REGIME_LABELS,
    REGIME_WINDOWS,
    SUMMARY_TABLE_PATH,
    TRADING_CALENDAR_PATH,
    TRADING_DAYS_PER_YEAR,
    UNIVERSE_KEYS,
    UNIVERSE_LABELS,
    UNIVERSE_PANEL_PATH,
)


ERROR_LOG = Path("data") / "errors_inspect_universes.log"
COMPRESSION = "zstd"

_logger = logging.getLogger("inspect_universes")
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    _handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _logger.addHandler(_handler)


def _log_warn(date: str, msg: str) -> None:
    _logger.warning(f"date={date} | {msg}")


# ─── Membership lookup ─────────────────────────────────────────────────

def _build_membership_lookup(membership: pd.DataFrame,
                             rebalance_dates: list) -> dict:
    """
    Build per-rebalance-date dict of {universe_key: set(ts_codes)}.
    Used to look up "for trading day d, what was the universe at the
    most recent rebalance date <= d."
    """
    out = {}
    for date_str, group in membership.groupby("rebalance_date"):
        out[date_str] = {}
        for u in UNIVERSE_KEYS:
            col = f"in_{u.split('_')[0]}"
            out[date_str][u] = set(group.loc[group[col], "ts_code"])
    return out


def _membership_as_of(trade_date: pd.Timestamp, membership_by_date: dict,
                      sorted_rebal_strs: list) -> dict:
    """
    For trade_date, find the most recent rebalance_date <= trade_date and
    return that date's membership dict.
    """
    import bisect
    td_str = trade_date.strftime("%Y-%m-%d")
    idx = bisect.bisect_right(sorted_rebal_strs, td_str) - 1
    if idx < 0:
        return None
    return membership_by_date[sorted_rebal_strs[idx]]


# ─── Limit-hit detection ───────────────────────────────────────────────

def _exchange_tier(ts_code: str) -> str:
    if ts_code.startswith("688"):
        return "star"
    if ts_code.startswith("300") or ts_code.startswith("301"):
        return "chinext"
    return "main"


def _limit_pct_for(ts_code: str, trade_date: pd.Timestamp) -> float:
    tier = _exchange_tier(ts_code)
    if tier == "star":
        return LIMIT_PCT_STAR
    if tier == "chinext":
        if trade_date < CHINEXT_REGIME_CHANGE:
            return LIMIT_PCT_MAIN
        return LIMIT_PCT_CHINEXT
    return LIMIT_PCT_MAIN


def _detect_limits_vectorized(panel: pd.DataFrame,
                               trade_date: pd.Timestamp) -> pd.DataFrame:
    """
    Vectorized limit-hit detection. Adds at_limit_up / at_limit_down bool
    columns to a copy of panel. Requires close, pre_close columns.

    Note: this gives APPROXIMATE limit detection (uses the standard
    percentage thresholds; doesn't handle ST stocks at ±5% or 北交所
    at ±30%; but those are excluded from our universes anyway).
    """
    out = panel.copy()
    # Determine limit pct per row by exchange tier
    is_star = out["ts_code"].str.startswith("688")
    is_chinext = out["ts_code"].str.startswith(("300", "301"))

    pct = pd.Series(LIMIT_PCT_MAIN, index=out.index, dtype="float32")
    if trade_date >= CHINEXT_REGIME_CHANGE:
        pct = pct.where(~is_chinext, LIMIT_PCT_CHINEXT)
    pct = pct.where(~is_star, LIMIT_PCT_STAR)

    upper = out["pre_close"] * (1 + pct)
    lower = out["pre_close"] * (1 - pct)

    out["at_limit_up"] = out["close"] >= LIMIT_PROXIMITY * upper
    out["at_limit_down"] = out["close"] <= (2 - LIMIT_PROXIMITY) * lower

    # Suppress when pre_close or close missing
    valid = out["close"].notna() & out["pre_close"].notna() & (out["pre_close"] > 0)
    out.loc[~valid, "at_limit_up"] = False
    out.loc[~valid, "at_limit_down"] = False
    return out


# ─── Per-day metric computation ────────────────────────────────────────

def _compute_metrics_for_day(
    trade_date: pd.Timestamp,
    panel: pd.DataFrame,
    membership_today: dict,
) -> list:
    """
    Compute metrics for a single trading day across all seven universes.
    Returns a list of dicts, one per universe.
    """
    date_str = trade_date.strftime("%Y-%m-%d")

    # Filter panel to A-share equities with valid data
    df = panel[panel["ts_code"].str.match(A_SHARE_PATTERN)].copy()
    df = df[df["circ_mv"].notna() & (df["circ_mv"] > 0)]
    df = df[df["close"].notna() & (df["close"] > 0)]
    df = df[df["pre_close"].notna() & (df["pre_close"] > 0)]
    if len(df) == 0:
        _log_warn(date_str, "no valid panel rows")
        return []

    # Daily simple return
    df["daily_return"] = df["close"] / df["pre_close"] - 1

    # Cap conversions
    df["circ_mv_yi"] = df["circ_mv"] * CIRC_MV_WAN_TO_YI
    df["total_mv_yi"] = df["total_mv"] * CIRC_MV_WAN_TO_YI \
        if "total_mv" in df.columns else np.nan
    df["amount_yi"] = df["amount"] * AMOUNT_QIANYUAN_TO_YI \
        if "amount" in df.columns else np.nan

    # Free-float ratio
    if "total_mv" in df.columns:
        df["free_float_ratio"] = (
            df["circ_mv"] / df["total_mv"].replace(0, np.nan)
        )
    else:
        df["free_float_ratio"] = np.nan

    # Limit-hit detection
    df = _detect_limits_vectorized(df, trade_date)

    rows = []
    for u in UNIVERSE_KEYS:
        codes = membership_today.get(u, set())
        sub = df[df["ts_code"].isin(codes)]
        if len(sub) == 0:
            rows.append({
                "trade_date": date_str,
                "universe": u,
                "n_stocks": 0,
            })
            continue

        # Compose metrics
        ret = sub["daily_return"].dropna()
        m = {
            "trade_date":              date_str,
            "universe":                u,
            "n_stocks":                int(len(sub)),
            # Composition
            "mean_circ_mv_yi":         float(sub["circ_mv_yi"].mean()),
            "median_circ_mv_yi":       float(sub["circ_mv_yi"].median()),
            "mean_total_mv_yi":        float(sub["total_mv_yi"].mean()) if "total_mv_yi" in sub else np.nan,
            "mean_free_float_ratio":   float(sub["free_float_ratio"].mean()),
            # Liquidity
            "mean_amount_yi":          float(sub["amount_yi"].mean()) if "amount_yi" in sub else np.nan,
            "median_amount_yi":        float(sub["amount_yi"].median()) if "amount_yi" in sub else np.nan,
            "mean_turnover_rate_f":    (
                float(sub["turnover_rate_f"].mean())
                if "turnover_rate_f" in sub else np.nan
            ),
            "median_turnover_rate_f":  (
                float(sub["turnover_rate_f"].median())
                if "turnover_rate_f" in sub else np.nan
            ),
            # Returns / dispersion
            "ew_daily_return_pct":     float(ret.mean() * 100) if len(ret) else np.nan,
            "cs_dispersion_pct":       float(ret.std() * 100) if len(ret) >= 2 else np.nan,
            "pct_up":                  float((ret > 0).mean()) if len(ret) else np.nan,
            # Limit-hit
            "pct_at_limit_up":         float(sub["at_limit_up"].mean()),
            "pct_at_limit_down":       float(sub["at_limit_down"].mean()),
        }
        rows.append(m)

    return rows


# ─── Driver: compute daily metrics across the panel ────────────────────

def compute_daily_metrics(verbose: bool = False, max_days: int | None = None) -> pd.DataFrame:
    """
    Iterate over every trading day in the panel, compute per-universe
    metrics, return a long-format DataFrame.
    """
    print("Loading universe panel...")
    if not UNIVERSE_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"{UNIVERSE_PANEL_PATH} not found. Run build_universe_panel.py full first."
        )
    membership = pd.read_parquet(UNIVERSE_PANEL_PATH)
    print(f"  {len(membership):,} membership rows")

    print("Building membership lookup...")
    rebal_dates = sorted(membership["rebalance_date"].unique())
    membership_by_date = _build_membership_lookup(membership, rebal_dates)
    print(f"  {len(membership_by_date)} rebalance dates with membership")

    # Trading calendar
    if not TRADING_CALENDAR_PATH.exists():
        raise FileNotFoundError(
            f"{TRADING_CALENDAR_PATH} not found."
        )
    cal = pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()
    # Filter to our panel range
    panel_start_str = rebal_dates[0]
    panel_end_str = PANEL_END.strftime("%Y-%m-%d")
    cal = [d for d in cal if panel_start_str <= d <= panel_end_str]
    print(f"  trading calendar: {len(cal)} days from {cal[0]} to {cal[-1]}")

    if max_days is not None:
        cal = cal[:max_days]
        print(f"  smoke-limited to first {max_days} trading days")

    # Iterate
    all_rows = []
    n_failed = 0
    t0 = time.time()
    for i, date_str in enumerate(cal, 1):
        td = pd.Timestamp(date_str)
        panel_path = DAILY_PANEL_DIR / f"daily_{date_str}.parquet"
        if not panel_path.exists():
            n_failed += 1
            _log_warn(date_str, "daily panel missing")
            continue

        membership_today = _membership_as_of(td, membership_by_date, rebal_dates)
        if membership_today is None:
            _log_warn(date_str, "no rebalance date <= trade_date in membership")
            n_failed += 1
            continue

        panel = pd.read_parquet(panel_path)
        rows = _compute_metrics_for_day(td, panel, membership_today)
        all_rows.extend(rows)

        if i % 100 == 0 or i == len(cal):
            secs = time.time() - t0
            rate = i / max(secs, 0.001)
            print(f"  [{i:>4}/{len(cal)}] failed={n_failed} "
                  f"rows={len(all_rows):,} "
                  f"elapsed={secs:.1f}s rate={rate:.1f} days/s")

    df = pd.DataFrame(all_rows)
    return df


# ─── Window aggregation ────────────────────────────────────────────────

def _classify_window(date_str: str) -> str | None:
    """Classify a trade date into a regime window. Returns key or None."""
    td = pd.Timestamp(date_str)
    out = []
    for window_key, (start, end) in REGIME_WINDOWS.items():
        if start <= td <= end:
            out.append(window_key)
    return out  # may be in multiple (W2 and W4 both cover same dates)


def aggregate_by_window(daily: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate daily metrics into per-(universe, window) summary rows.

    Returns DataFrame with columns:
      universe, window, n_trading_days,
      cumulative_return_pct, ann_return_pct, ann_vol_pct, sharpe,
      mean_n_stocks, mean_*  (all daily means)
    """
    out_rows = []
    for u in UNIVERSE_KEYS:
        sub_u = daily[daily["universe"] == u].copy()
        sub_u["trade_date_ts"] = pd.to_datetime(sub_u["trade_date"])
        sub_u = sub_u.sort_values("trade_date_ts")

        for window_key, (wstart, wend) in REGIME_WINDOWS.items():
            in_window = (sub_u["trade_date_ts"] >= wstart) & (sub_u["trade_date_ts"] <= wend)
            sub = sub_u[in_window].copy()
            sub = sub[sub["n_stocks"] > 0]  # drop empty days (e.g. CSI2000 pre-inception)
            n = len(sub)
            if n == 0:
                # Empty window. Output a row with NaN so the table is rectangular.
                out_rows.append({
                    "universe": u,
                    "window":   window_key,
                    "n_trading_days": 0,
                })
                continue

            # Returns
            r = sub["ew_daily_return_pct"].dropna() / 100.0
            cum_geom = float((1 + r).prod() - 1)
            ann_ret = (1 + cum_geom) ** (TRADING_DAYS_PER_YEAR / max(n, 1)) - 1
            ann_vol = float(r.std() * np.sqrt(TRADING_DAYS_PER_YEAR)) if len(r) >= 2 else np.nan
            sharpe = ann_ret / ann_vol if ann_vol and ann_vol > 0 else np.nan

            row = {
                "universe":                  u,
                "window":                    window_key,
                "n_trading_days":            n,
                "cumulative_return_pct":     cum_geom * 100,
                "ann_return_pct":            ann_ret * 100,
                "ann_vol_pct":               ann_vol * 100 if pd.notna(ann_vol) else np.nan,
                "sharpe":                    sharpe,
                # Means of daily metrics
                "mean_n_stocks":             float(sub["n_stocks"].mean()),
                "mean_circ_mv_yi":           float(sub["mean_circ_mv_yi"].mean()),
                "mean_median_circ_mv_yi":    float(sub["median_circ_mv_yi"].mean()),
                "mean_amount_yi":            float(sub["mean_amount_yi"].mean()),
                "mean_turnover_rate_f":      float(sub["mean_turnover_rate_f"].mean()),
                "mean_cs_dispersion_pct":    float(sub["cs_dispersion_pct"].mean()),
                "mean_pct_at_limit_up":      float(sub["pct_at_limit_up"].mean()) * 100,
                "mean_pct_at_limit_down":    float(sub["pct_at_limit_down"].mean()) * 100,
                "mean_pct_up":               float(sub["pct_up"].mean()) * 100,
            }
            out_rows.append(row)

    return pd.DataFrame(out_rows)


# ─── Plotting ──────────────────────────────────────────────────────────

def _plot_cumulative_returns(daily: pd.DataFrame, save_path: Path) -> None:
    """Cumulative ew daily return per universe over the panel."""
    fig, ax = plt.subplots(figsize=(13, 7))
    colors = plt.cm.tab10(np.linspace(0, 1, len(UNIVERSE_KEYS)))

    for u, c in zip(UNIVERSE_KEYS, colors):
        sub = daily[daily["universe"] == u].copy()
        sub["trade_date_ts"] = pd.to_datetime(sub["trade_date"])
        sub = sub.sort_values("trade_date_ts")
        sub = sub[sub["n_stocks"] > 0]
        r = sub["ew_daily_return_pct"] / 100.0
        cum = (1 + r.fillna(0)).cumprod()
        ax.plot(sub["trade_date_ts"], cum, label=UNIVERSE_LABELS[u],
                color=c, linewidth=1.3, alpha=0.85)

    # Regime markers
    ax.axvline(NEW_NINE_ARTICLES_DATE, color="firebrick", linestyle="--",
               linewidth=1, alpha=0.7)
    ax.axvline(PBOC_STIMULUS_DATE, color="seagreen", linestyle="--",
               linewidth=1, alpha=0.7)
    ymax = ax.get_ylim()[1]
    ax.text(NEW_NINE_ARTICLES_DATE, ymax * 0.98, " 新国九条",
            fontsize=9, color="firebrick", verticalalignment="top")
    ax.text(PBOC_STIMULUS_DATE, ymax * 0.93, " PBoC stimulus",
            fontsize=9, color="seagreen", verticalalignment="top")

    ax.set_title("Cumulative equal-weighted daily return by universe (gross)")
    ax.set_xlabel("Trade date")
    ax.set_ylabel("Cumulative return (×)")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def _plot_metric_time_series(daily: pd.DataFrame, metric_col: str,
                              ylabel: str, title: str,
                              save_path: Path,
                              rolling_window: int = 20) -> None:
    """Generic time-series plot of one metric across universes (rolling-mean smoothed)."""
    fig, ax = plt.subplots(figsize=(13, 6))
    colors = plt.cm.tab10(np.linspace(0, 1, len(UNIVERSE_KEYS)))

    for u, c in zip(UNIVERSE_KEYS, colors):
        sub = daily[daily["universe"] == u].copy()
        sub["trade_date_ts"] = pd.to_datetime(sub["trade_date"])
        sub = sub.sort_values("trade_date_ts")
        sub = sub[sub["n_stocks"] > 0]
        smoothed = sub[metric_col].rolling(rolling_window, min_periods=1).mean()
        ax.plot(sub["trade_date_ts"], smoothed, label=UNIVERSE_LABELS[u],
                color=c, linewidth=1.2, alpha=0.85)

    ax.axvline(NEW_NINE_ARTICLES_DATE, color="firebrick", linestyle="--",
               linewidth=1, alpha=0.7)
    ax.axvline(PBOC_STIMULUS_DATE, color="seagreen", linestyle="--",
               linewidth=1, alpha=0.7)

    ax.set_title(f"{title} ({rolling_window}-day rolling mean)")
    ax.set_xlabel("Trade date")
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def _plot_window_bars(summary: pd.DataFrame, metric_col: str,
                      ylabel: str, title: str, save_path: Path) -> None:
    """Grouped bar chart: one group per window, one bar per universe."""
    fig, ax = plt.subplots(figsize=(13, 6))
    windows = list(REGIME_WINDOWS.keys())
    universes = UNIVERSE_KEYS
    width = 0.11
    x = np.arange(len(windows))

    colors = plt.cm.tab10(np.linspace(0, 1, len(universes)))
    for j, (u, c) in enumerate(zip(universes, colors)):
        vals = [
            float(summary[
                (summary["universe"] == u) & (summary["window"] == w)
            ][metric_col].iloc[0]) if len(summary[
                (summary["universe"] == u) & (summary["window"] == w)
            ]) else np.nan
            for w in windows
        ]
        offset = (j - (len(universes) - 1) / 2) * width
        ax.bar(x + offset, vals, width, label=UNIVERSE_LABELS[u], color=c)

    ax.set_xticks(x)
    ax.set_xticklabels([REGIME_LABELS[w] for w in windows],
                       rotation=10, ha="right", fontsize=9)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.85, ncol=2)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def make_all_plots(daily: pd.DataFrame, summary: pd.DataFrame) -> None:
    """Generate the full plot suite to graphs/."""
    print("\nGenerating plots...")
    _plot_cumulative_returns(
        daily, GRAPHS_DIR / "universe_cumulative_returns.png"
    )
    _plot_metric_time_series(
        daily, "mean_turnover_rate_f", "% / day",
        "Mean free-float turnover rate by universe",
        GRAPHS_DIR / "universe_turnover_rate.png",
        rolling_window=20,
    )
    _plot_metric_time_series(
        daily, "cs_dispersion_pct", "Cross-sectional std (%)",
        "Cross-sectional return dispersion by universe",
        GRAPHS_DIR / "universe_dispersion.png",
        rolling_window=20,
    )
    _plot_metric_time_series(
        daily, "pct_at_limit_up", "Fraction of stocks at limit-up",
        "Limit-up frequency by universe",
        GRAPHS_DIR / "universe_limit_up_freq.png",
        rolling_window=10,
    )
    _plot_metric_time_series(
        daily, "pct_at_limit_down", "Fraction of stocks at limit-down",
        "Limit-down frequency by universe",
        GRAPHS_DIR / "universe_limit_down_freq.png",
        rolling_window=10,
    )
    _plot_metric_time_series(
        daily, "n_stocks", "n in-universe",
        "Universe size over time",
        GRAPHS_DIR / "universe_size_over_time.png",
        rolling_window=5,
    )
    _plot_window_bars(
        summary, "ann_return_pct", "Annualized return (%)",
        "Annualized return per universe per regime window",
        GRAPHS_DIR / "universe_window_returns.png",
    )
    _plot_window_bars(
        summary, "sharpe", "Sharpe-like (ann_ret / ann_vol)",
        "Sharpe-like ratio per universe per regime window",
        GRAPHS_DIR / "universe_window_sharpe.png",
    )
    _plot_window_bars(
        summary, "mean_turnover_rate_f", "Mean turnover rate (% / day)",
        "Mean turnover rate per universe per regime window",
        GRAPHS_DIR / "universe_window_turnover.png",
    )
    print(f"  plots saved to {GRAPHS_DIR}/")


# ─── Reporting ─────────────────────────────────────────────────────────

def print_summary_table(summary: pd.DataFrame) -> None:
    """Print the headline table to stdout."""
    print("\n" + "=" * 110)
    print("UNIVERSE INSPECTION — REGIME-WINDOW SUMMARY")
    print("=" * 110)

    # For each window, print a sub-table sorted by universe
    for window_key in REGIME_WINDOWS:
        print(f"\n  --- {REGIME_LABELS[window_key]} ---")
        sub = summary[summary["window"] == window_key].copy()
        sub = sub.set_index("universe").reindex(UNIVERSE_KEYS)
        cols_to_show = [
            "n_trading_days", "mean_n_stocks",
            "mean_circ_mv_yi", "mean_amount_yi", "mean_turnover_rate_f",
            "cumulative_return_pct", "ann_return_pct", "ann_vol_pct", "sharpe",
            "mean_cs_dispersion_pct",
            "mean_pct_at_limit_up", "mean_pct_at_limit_down",
        ]
        print(sub[cols_to_show].round(2).to_string())


# ─── Main ──────────────────────────────────────────────────────────────

def smoke_test() -> None:
    print("=" * 60)
    print("INSPECT UNIVERSES — SMOKE (30 trading days)")
    print("=" * 60)
    daily = compute_daily_metrics(verbose=True, max_days=30)
    print(f"\nDaily metric rows: {len(daily):,}")
    if len(daily) == 0:
        return
    print("\nSample (first 10 rows):")
    print(daily.head(10).to_string())
    summary = aggregate_by_window(daily)
    print_summary_table(summary)


def full_run() -> None:
    print("=" * 60)
    print("INSPECT UNIVERSES — FULL")
    print("=" * 60)
    daily = compute_daily_metrics(verbose=False)
    print(f"\nDaily metric rows: {len(daily):,}")

    print(f"\nSaving daily metrics to {DAILY_METRICS_PATH}...")
    daily.to_parquet(DAILY_METRICS_PATH, compression=COMPRESSION, index=False)

    summary = aggregate_by_window(daily)
    print(f"\nSaving summary to {SUMMARY_TABLE_PATH}...")
    summary.to_csv(SUMMARY_TABLE_PATH, index=False)

    print_summary_table(summary)
    make_all_plots(daily, summary)


def plots_only() -> None:
    """Regenerate plots from cached daily metrics."""
    if not DAILY_METRICS_PATH.exists():
        print(f"No daily metrics at {DAILY_METRICS_PATH}. Run with `full`.")
        return
    daily = pd.read_parquet(DAILY_METRICS_PATH)
    summary = aggregate_by_window(daily)
    summary.to_csv(SUMMARY_TABLE_PATH, index=False)
    print_summary_table(summary)
    make_all_plots(daily, summary)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode == "smoke":
        smoke_test()
    elif mode == "full":
        full_run()
    elif mode == "plots":
        plots_only()
    else:
        print("Usage: python inspect_universes.py [smoke|full|plots]")
        sys.exit(1)


if __name__ == "__main__":
    main()
