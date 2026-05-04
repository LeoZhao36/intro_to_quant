"""
inspect_three_universes.py — Daily metrics for A/B/C × α/β/γ.

Same architecture as inspect_universes.py but parameterized to the
three-universe / three-window setup. Run after build_three_universes.py
has produced data/universe_membership_three.parquet.

Inputs
------
  data/universe_membership_three.parquet   (build_three_universes.py)
  ../Project_6/data/trading_calendar.csv
  daily_panel/daily_<DATE>.parquet         (per trading day)

Outputs
-------
  data/daily_three_universe_metrics.parquet   long-format daily metrics
  data/three_universe_inspection_summary.csv  per (universe, window) summary
  graphs/three_*.png                          comparison plots

Daily metrics per (trade_date, universe)
----------------------------------------
  n_stocks
  mean_circ_mv_yi, median_circ_mv_yi
  mean_amount_yi, median_amount_yi
  mean_turnover_rate_f, median_turnover_rate_f
  ew_daily_return_pct (universe equal-weighted)
  cs_dispersion_pct
  pct_up
  pct_at_limit_up, pct_at_limit_down

Window aggregation
------------------
For each (universe, window):
  cumulative_return_pct, ann_return_pct, ann_vol_pct, sharpe
  mean_n_stocks, mean_circ_mv_yi, mean_amount_yi, mean_turnover_rate_f
  mean_cs_dispersion_pct, mean_pct_at_limit_up, mean_pct_at_limit_down

Usage
-----
    python inspect_three_universes.py smoke   # 30 days
    python inspect_three_universes.py full
    python inspect_three_universes.py plots   # regen plots from cache
"""

import bisect
import logging
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    A_SHARE_PATTERN,
    AMOUNT_QIANYUAN_TO_YI,
    CIRC_MV_WAN_TO_YI,
    CHINEXT_REGIME_CHANGE,
    DAILY_PANEL_DIR,
    GRAPHS_DIR,
    LIMIT_PROXIMITY,
    LIMIT_PCT_CHINEXT,
    LIMIT_PCT_MAIN,
    LIMIT_PCT_STAR,
    NEW_NINE_ARTICLES_DATE,
    PANEL_END,
    PBOC_STIMULUS_DATE,
    THREE_DAILY_METRICS_PATH,
    THREE_REGIME_LABELS,
    THREE_REGIME_WINDOWS,
    THREE_SUMMARY_TABLE_PATH,
    THREE_UNIVERSE_KEYS,
    THREE_UNIVERSE_LABELS,
    THREE_UNIVERSE_PANEL_PATH,
    TRADING_CALENDAR_PATH,
    TRADING_DAYS_PER_YEAR,
)


ERROR_LOG = Path("data") / "errors_inspect_three.log"
COMPRESSION = "zstd"

_logger = logging.getLogger("inspect_three_universes")
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    Path("data").mkdir(exist_ok=True)
    _handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _logger.addHandler(_handler)


def _log_warn(date: str, msg: str) -> None:
    _logger.warning(f"date={date} | {msg}")


# ─── Membership lookup ─────────────────────────────────────────────────

def _build_membership_lookup(membership: pd.DataFrame) -> tuple:
    """
    Build per-rebalance-date dict of {universe_key: set(ts_codes)}.
    Returns (membership_by_date, sorted_rebalance_date_strings).
    """
    out: dict = {}
    for date_str, group in membership.groupby("rebalance_date"):
        out[date_str] = {}
        for u in THREE_UNIVERSE_KEYS:
            col = f"in_{u.split('_')[0]}"  # in_A / in_B / in_C
            out[date_str][u] = set(group.loc[group[col], "ts_code"])
    sorted_dates = sorted(out.keys())
    return out, sorted_dates


def _membership_as_of(trade_date: pd.Timestamp,
                      membership_by_date: dict,
                      sorted_rebal_strs: list) -> dict | None:
    td_str = trade_date.strftime("%Y-%m-%d")
    idx = bisect.bisect_right(sorted_rebal_strs, td_str) - 1
    if idx < 0:
        return None
    return membership_by_date[sorted_rebal_strs[idx]]


# ─── Limit-hit detection (vectorized) ──────────────────────────────────

def _detect_limits_vectorized(panel: pd.DataFrame,
                               trade_date: pd.Timestamp) -> pd.DataFrame:
    out = panel.copy()
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

    valid = (
        out["close"].notna() & out["pre_close"].notna()
        & (out["pre_close"] > 0)
    )
    out.loc[~valid, "at_limit_up"] = False
    out.loc[~valid, "at_limit_down"] = False
    return out


# ─── Per-day metric computation ────────────────────────────────────────

def _compute_metrics_for_day(
    trade_date: pd.Timestamp,
    panel: pd.DataFrame,
    membership_today: dict,
) -> list:
    date_str = trade_date.strftime("%Y-%m-%d")

    df = panel[panel["ts_code"].str.match(A_SHARE_PATTERN)].copy()
    df = df[df["circ_mv"].notna() & (df["circ_mv"] > 0)]
    df = df[df["close"].notna() & (df["close"] > 0)]
    df = df[df["pre_close"].notna() & (df["pre_close"] > 0)]
    if len(df) == 0:
        _log_warn(date_str, "no valid panel rows")
        return []

    df["daily_return"] = df["close"] / df["pre_close"] - 1
    df["circ_mv_yi"] = df["circ_mv"] * CIRC_MV_WAN_TO_YI
    if "amount" in df.columns:
        df["amount_yi"] = df["amount"] * AMOUNT_QIANYUAN_TO_YI
    else:
        df["amount_yi"] = np.nan

    df = _detect_limits_vectorized(df, trade_date)

    rows = []
    for u in THREE_UNIVERSE_KEYS:
        codes = membership_today.get(u, set())
        sub = df[df["ts_code"].isin(codes)]
        if len(sub) == 0:
            rows.append({
                "trade_date": date_str,
                "universe":   u,
                "n_stocks":   0,
            })
            continue
        ret = sub["daily_return"].dropna()
        m = {
            "trade_date":              date_str,
            "universe":                u,
            "n_stocks":                int(len(sub)),
            "mean_circ_mv_yi":         float(sub["circ_mv_yi"].mean()),
            "median_circ_mv_yi":       float(sub["circ_mv_yi"].median()),
            "mean_amount_yi":          float(sub["amount_yi"].mean()),
            "median_amount_yi":        float(sub["amount_yi"].median()),
            "mean_turnover_rate_f":    (
                float(sub["turnover_rate_f"].mean())
                if "turnover_rate_f" in sub else np.nan
            ),
            "median_turnover_rate_f":  (
                float(sub["turnover_rate_f"].median())
                if "turnover_rate_f" in sub else np.nan
            ),
            "ew_daily_return_pct":     (
                float(ret.mean() * 100) if len(ret) else np.nan
            ),
            "cs_dispersion_pct":       (
                float(ret.std() * 100) if len(ret) >= 2 else np.nan
            ),
            "pct_up":                  (
                float((ret > 0).mean()) if len(ret) else np.nan
            ),
            "pct_at_limit_up":         float(sub["at_limit_up"].mean()),
            "pct_at_limit_down":       float(sub["at_limit_down"].mean()),
        }
        rows.append(m)
    return rows


# ─── Driver: compute daily metrics ─────────────────────────────────────

def compute_daily_metrics(max_days: int | None = None) -> pd.DataFrame:
    print("Loading three-universe membership panel...")
    if not THREE_UNIVERSE_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"{THREE_UNIVERSE_PANEL_PATH} not found. "
            f"Run build_three_universes.py full first."
        )
    membership = pd.read_parquet(THREE_UNIVERSE_PANEL_PATH)
    print(f"  {len(membership):,} membership rows")

    print("Building membership lookup...")
    membership_by_date, sorted_rebal_strs = _build_membership_lookup(membership)
    print(f"  {len(membership_by_date)} rebalance dates")

    if not TRADING_CALENDAR_PATH.exists():
        raise FileNotFoundError(f"{TRADING_CALENDAR_PATH} missing")
    cal = pd.read_csv(TRADING_CALENDAR_PATH)["date"].tolist()
    panel_start_str = sorted_rebal_strs[0]
    panel_end_str = PANEL_END.strftime("%Y-%m-%d")
    cal = [d for d in cal if panel_start_str <= d <= panel_end_str]
    print(f"  trading calendar window: {len(cal)} days "
          f"from {cal[0]} to {cal[-1]}")

    if max_days is not None:
        cal = cal[:max_days]
        print(f"  smoke-limited to first {max_days} trading days")

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

        membership_today = _membership_as_of(td, membership_by_date,
                                              sorted_rebal_strs)
        if membership_today is None:
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

    return pd.DataFrame(all_rows)


# ─── Window aggregation ────────────────────────────────────────────────

def aggregate_by_window(daily: pd.DataFrame) -> pd.DataFrame:
    out_rows = []
    for u in THREE_UNIVERSE_KEYS:
        sub_u = daily[daily["universe"] == u].copy()
        sub_u["trade_date_ts"] = pd.to_datetime(sub_u["trade_date"])
        sub_u = sub_u.sort_values("trade_date_ts")

        for window_key, (wstart, wend) in THREE_REGIME_WINDOWS.items():
            in_window = (
                (sub_u["trade_date_ts"] >= wstart)
                & (sub_u["trade_date_ts"] <= wend)
            )
            sub = sub_u[in_window].copy()
            sub = sub[sub["n_stocks"] > 0]
            n = len(sub)
            if n == 0:
                out_rows.append({
                    "universe": u, "window": window_key,
                    "n_trading_days": 0,
                })
                continue

            r = sub["ew_daily_return_pct"].dropna() / 100.0
            cum_geom = float((1 + r).prod() - 1)
            ann_ret = (1 + cum_geom) ** (TRADING_DAYS_PER_YEAR / max(n, 1)) - 1
            ann_vol = (
                float(r.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
                if len(r) >= 2 else np.nan
            )
            sharpe = ann_ret / ann_vol if ann_vol and ann_vol > 0 else np.nan

            out_rows.append({
                "universe":                  u,
                "window":                    window_key,
                "n_trading_days":            n,
                "cumulative_return_pct":     cum_geom * 100,
                "ann_return_pct":            ann_ret * 100,
                "ann_vol_pct":               ann_vol * 100 if pd.notna(ann_vol) else np.nan,
                "sharpe":                    sharpe,
                "mean_n_stocks":             float(sub["n_stocks"].mean()),
                "mean_circ_mv_yi":           float(sub["mean_circ_mv_yi"].mean()),
                "mean_median_circ_mv_yi":    float(sub["median_circ_mv_yi"].mean()),
                "mean_amount_yi":            float(sub["mean_amount_yi"].mean()),
                "mean_turnover_rate_f":      float(sub["mean_turnover_rate_f"].mean()),
                "mean_cs_dispersion_pct":    float(sub["cs_dispersion_pct"].mean()),
                "mean_pct_at_limit_up":      float(sub["pct_at_limit_up"].mean()) * 100,
                "mean_pct_at_limit_down":    float(sub["pct_at_limit_down"].mean()) * 100,
                "mean_pct_up":               float(sub["pct_up"].mean()) * 100,
            })
    return pd.DataFrame(out_rows)


# ─── Plotting ──────────────────────────────────────────────────────────

# Three-color palette for the three universes; consistent across all plots.
UNIVERSE_COLORS = {
    "A_u6_clean":   "#1f77b4",  # steel blue
    "B_u6_price":   "#2ca02c",  # green
    "C_u6_floored": "#d62728",  # red
}


def _plot_cumulative_returns(daily: pd.DataFrame, save_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(13, 7))
    for u in THREE_UNIVERSE_KEYS:
        sub = daily[daily["universe"] == u].copy()
        sub["trade_date_ts"] = pd.to_datetime(sub["trade_date"])
        sub = sub.sort_values("trade_date_ts")
        sub = sub[sub["n_stocks"] > 0]
        r = sub["ew_daily_return_pct"] / 100.0
        cum = (1 + r.fillna(0)).cumprod()
        ax.plot(sub["trade_date_ts"], cum,
                label=THREE_UNIVERSE_LABELS[u],
                color=UNIVERSE_COLORS[u], linewidth=1.5, alpha=0.9)

    ax.axvline(NEW_NINE_ARTICLES_DATE, color="firebrick", linestyle="--",
               linewidth=1, alpha=0.7)
    ax.axvline(PBOC_STIMULUS_DATE, color="seagreen", linestyle="--",
               linewidth=1, alpha=0.7)
    ymax = ax.get_ylim()[1]
    ax.text(NEW_NINE_ARTICLES_DATE, ymax * 0.98, " 新国九条",
            fontsize=9, color="firebrick", verticalalignment="top")
    ax.text(PBOC_STIMULUS_DATE, ymax * 0.93, " PBoC stimulus",
            fontsize=9, color="seagreen", verticalalignment="top")

    ax.set_title("Cumulative equal-weighted daily return: A vs B vs C")
    ax.set_xlabel("Trade date")
    ax.set_ylabel("Cumulative return (×)")
    ax.legend(loc="upper left", fontsize=10, framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def _plot_metric_time_series(daily: pd.DataFrame, metric_col: str,
                              ylabel: str, title: str,
                              save_path: Path,
                              rolling_window: int = 20) -> None:
    fig, ax = plt.subplots(figsize=(13, 6))
    for u in THREE_UNIVERSE_KEYS:
        sub = daily[daily["universe"] == u].copy()
        sub["trade_date_ts"] = pd.to_datetime(sub["trade_date"])
        sub = sub.sort_values("trade_date_ts")
        sub = sub[sub["n_stocks"] > 0]
        smoothed = sub[metric_col].rolling(rolling_window, min_periods=1).mean()
        ax.plot(sub["trade_date_ts"], smoothed,
                label=THREE_UNIVERSE_LABELS[u],
                color=UNIVERSE_COLORS[u], linewidth=1.4, alpha=0.9)

    ax.axvline(NEW_NINE_ARTICLES_DATE, color="firebrick", linestyle="--",
               linewidth=1, alpha=0.7)
    ax.axvline(PBOC_STIMULUS_DATE, color="seagreen", linestyle="--",
               linewidth=1, alpha=0.7)

    ax.set_title(f"{title} ({rolling_window}-day rolling mean)")
    ax.set_xlabel("Trade date")
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", fontsize=10, framealpha=0.85)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def _plot_window_bars(summary: pd.DataFrame, metric_col: str,
                       ylabel: str, title: str, save_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 6))
    windows = list(THREE_REGIME_WINDOWS.keys())
    width = 0.25
    x = np.arange(len(windows))

    for j, u in enumerate(THREE_UNIVERSE_KEYS):
        vals = [
            float(summary[
                (summary["universe"] == u) & (summary["window"] == w)
            ][metric_col].iloc[0]) if len(summary[
                (summary["universe"] == u) & (summary["window"] == w)
            ]) else np.nan
            for w in windows
        ]
        offset = (j - 1) * width  # j ∈ {0,1,2}, offsets -w/0/+w
        ax.bar(x + offset, vals, width, label=THREE_UNIVERSE_LABELS[u],
               color=UNIVERSE_COLORS[u])
        # Annotate values on top
        for xi, v in zip(x + offset, vals):
            if pd.notna(v):
                ax.text(xi, v, f"{v:.2f}", ha="center",
                        va="bottom" if v >= 0 else "top", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels([THREE_REGIME_LABELS[w] for w in windows],
                       rotation=10, ha="right", fontsize=9)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.legend(loc="best", fontsize=9, framealpha=0.85)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def make_all_plots(daily: pd.DataFrame, summary: pd.DataFrame) -> None:
    print("\nGenerating plots...")
    _plot_cumulative_returns(
        daily, GRAPHS_DIR / "three_cumulative_returns.png"
    )
    _plot_metric_time_series(
        daily, "mean_turnover_rate_f", "% / day",
        "Mean free-float turnover rate: A vs B vs C",
        GRAPHS_DIR / "three_turnover_rate.png", rolling_window=20,
    )
    _plot_metric_time_series(
        daily, "cs_dispersion_pct", "Cross-sectional std (%)",
        "Cross-sectional return dispersion: A vs B vs C",
        GRAPHS_DIR / "three_dispersion.png", rolling_window=20,
    )
    _plot_metric_time_series(
        daily, "pct_at_limit_up", "Fraction at limit-up",
        "Limit-up frequency: A vs B vs C",
        GRAPHS_DIR / "three_limit_up_freq.png", rolling_window=10,
    )
    _plot_metric_time_series(
        daily, "pct_at_limit_down", "Fraction at limit-down",
        "Limit-down frequency: A vs B vs C",
        GRAPHS_DIR / "three_limit_down_freq.png", rolling_window=10,
    )
    _plot_metric_time_series(
        daily, "n_stocks", "n in-universe",
        "Universe size over time: A vs B vs C",
        GRAPHS_DIR / "three_size_over_time.png", rolling_window=5,
    )
    _plot_window_bars(
        summary, "ann_return_pct", "Annualized return (%)",
        "Annualized return: A/B/C × α/β/γ",
        GRAPHS_DIR / "three_window_returns.png",
    )
    _plot_window_bars(
        summary, "sharpe", "Sharpe-like (ann_ret / ann_vol)",
        "Sharpe-like ratio: A/B/C × α/β/γ",
        GRAPHS_DIR / "three_window_sharpe.png",
    )
    _plot_window_bars(
        summary, "mean_turnover_rate_f", "Mean turnover (% / day)",
        "Mean turnover rate: A/B/C × α/β/γ",
        GRAPHS_DIR / "three_window_turnover.png",
    )
    _plot_window_bars(
        summary, "mean_cs_dispersion_pct", "Mean dispersion (%)",
        "Mean cross-sectional dispersion: A/B/C × α/β/γ",
        GRAPHS_DIR / "three_window_dispersion.png",
    )
    print(f"  plots saved to {GRAPHS_DIR}/")


# ─── Reporting ─────────────────────────────────────────────────────────

def print_summary_table(summary: pd.DataFrame) -> None:
    print("\n" + "=" * 110)
    print("THREE-UNIVERSE INSPECTION — REGIME-WINDOW SUMMARY")
    print("=" * 110)

    for window_key in THREE_REGIME_WINDOWS:
        print(f"\n  --- {THREE_REGIME_LABELS[window_key]} ---")
        sub = summary[summary["window"] == window_key].copy()
        sub = sub.set_index("universe").reindex(THREE_UNIVERSE_KEYS)
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
    print("INSPECT THREE UNIVERSES — SMOKE (30 days)")
    print("=" * 60)
    daily = compute_daily_metrics(max_days=30)
    print(f"\nDaily rows: {len(daily):,}")
    if len(daily) == 0:
        return
    print("\nSample (first 9 rows = first 3 days × 3 universes):")
    print(daily.head(9).to_string())
    summary = aggregate_by_window(daily)
    print_summary_table(summary)


def full_run() -> None:
    print("=" * 60)
    print("INSPECT THREE UNIVERSES — FULL")
    print("=" * 60)
    daily = compute_daily_metrics()
    print(f"\nDaily rows: {len(daily):,}")

    print(f"\nSaving daily metrics to {THREE_DAILY_METRICS_PATH}...")
    daily.to_parquet(THREE_DAILY_METRICS_PATH, compression=COMPRESSION,
                     index=False)

    summary = aggregate_by_window(daily)
    print(f"Saving summary to {THREE_SUMMARY_TABLE_PATH}...")
    summary.to_csv(THREE_SUMMARY_TABLE_PATH, index=False)

    print_summary_table(summary)
    make_all_plots(daily, summary)


def plots_only() -> None:
    if not THREE_DAILY_METRICS_PATH.exists():
        print(f"No daily metrics at {THREE_DAILY_METRICS_PATH}. Run `full`.")
        return
    daily = pd.read_parquet(THREE_DAILY_METRICS_PATH)
    summary = aggregate_by_window(daily)
    summary.to_csv(THREE_SUMMARY_TABLE_PATH, index=False)
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
        print("Usage: python inspect_three_universes.py [smoke|full|plots]")
        sys.exit(1)


if __name__ == "__main__":
    main()