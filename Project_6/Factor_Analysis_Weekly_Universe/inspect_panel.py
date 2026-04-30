"""
inspect_panel.py — Lightweight CLI for inspecting factor_panel_weekly.parquet.

Parquet is binary so you can't grep it. This wraps the most common
"what's in there" questions in a few flags so you don't have to write
a fresh pandas snippet each time.

Usage
-----
    python inspect_panel.py                       # full diagnostic (default)
    python inspect_panel.py --stock 000001.SZ     # one stock's history
    python inspect_panel.py --date 2024-09-25     # one date's cross-section
    python inspect_panel.py --sample 20           # random 20 rows
    python inspect_panel.py --year 2024           # year-summary moments
    python inspect_panel.py --csv head500.csv     # export top 500 rows to CSV
    python inspect_panel.py --csv 2024_data.csv --year 2024   # combine

The diagnostic mode reproduces the same shape/coverage/sanity stats the
factor_panel_builder.py status mode prints, plus year-by-year EP coverage
and forward-return moments — useful for catching late-panel drift before
running factor analyses.

Run from Project_6/.
"""

import argparse
import sys

import numpy as np
import pandas as pd

from config import FACTOR_PANEL_PATH


def load_or_die() -> pd.DataFrame:
    if not FACTOR_PANEL_PATH.exists():
        print(f"ERROR: {FACTOR_PANEL_PATH} not found.")
        print(f"  Run `python factor_panel_builder.py full` first.")
        sys.exit(1)
    panel = pd.read_parquet(FACTOR_PANEL_PATH)
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])
    return panel


def diagnostic(panel: pd.DataFrame) -> None:
    """Full panel diagnostic — shape, coverage, year-summaries."""
    print("=" * 60)
    print(f"Panel: {FACTOR_PANEL_PATH}")
    print("=" * 60)
    print(f"  rows:           {len(panel):,}")
    print(f"  unique stocks:  {panel['ts_code'].nunique():,}")
    print(f"  unique dates:   {panel['rebalance_date'].nunique()}")
    print(f"  date range:     {panel['rebalance_date'].min().date()} to "
          f"{panel['rebalance_date'].max().date()}")
    print(f"  in_universe:    {int(panel['in_universe'].sum()):,}")

    print(f"\n  Field coverage (all rows):")
    for col in ["close", "adj_close", "log_mcap", "ep", "pe_ttm",
                "l1_name", "forward_return"]:
        cov = panel[col].notna().mean() * 100
        print(f"    {col:<18s} {cov:>5.1f}%")

    iu = panel[panel["in_universe"]]

    print(f"\n  In-universe count per date:")
    iu_per_date = iu.groupby("rebalance_date").size()
    print(f"    min={iu_per_date.min()}, "
          f"median={int(iu_per_date.median())}, "
          f"max={iu_per_date.max()}")
    n_off = int((iu_per_date != 1000).sum())
    print(f"    dates != 1000: {n_off}")

    print(f"\n  EP coverage by year (in-universe only):")
    iu_year = iu.copy()
    iu_year["year"] = iu_year["rebalance_date"].dt.year
    ep_year = iu_year.groupby("year")["ep"].agg(
        n="size",
        n_with_ep=lambda s: int(s.notna().sum()),
    )
    ep_year["pct"] = 100 * ep_year["n_with_ep"] / ep_year["n"]
    print(ep_year.round(1).to_string())

    print(f"\n  Forward-return by year (in-universe, annualized):")
    fr = iu_year.dropna(subset=["forward_return"])
    yr = fr.groupby("year")["forward_return"].agg(["count", "mean", "std"])
    yr["mean_pct_wk"] = (yr["mean"] * 100).round(2)
    yr["std_pct_wk"] = (yr["std"] * 100).round(2)
    yr["ann_mean_pct"] = (yr["mean"] * 52 * 100).round(2)
    yr["ann_vol_pct"] = (yr["std"] * np.sqrt(52) * 100).round(2)
    print(yr[["count", "mean_pct_wk", "std_pct_wk",
              "ann_mean_pct", "ann_vol_pct"]].to_string())

    print(f"\n  Universe-EW weekly returns (one number per week):")
    ew = fr.groupby("rebalance_date")["forward_return"].mean()
    print(f"    n weeks:        {len(ew)}")
    print(f"    mean %/wk:      {ew.mean()*100:+.3f}")
    print(f"    std %/wk:       {ew.std()*100:.3f}")
    print(f"    ann mean:       {ew.mean()*52*100:+.2f}%")
    print(f"    ann vol:        {ew.std()*np.sqrt(52)*100:.2f}%")
    print(f"    Sharpe (gross): {ew.mean()/ew.std()*np.sqrt(52):+.3f}")

    print(f"\n  Tail diagnostic (in-universe forward returns):")
    fr_iu = iu.dropna(subset=["forward_return"])["forward_return"]
    print(f"    min: {fr_iu.min()*100:.2f}%, max: {fr_iu.max()*100:.2f}%")
    print(f"    |return| > 30%/wk: {int((fr_iu.abs() > 0.30).sum()):,} "
          f"({(fr_iu.abs() > 0.30).mean()*100:.3f}% of in-universe)")


def show_stock(panel: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    sub = panel[panel["ts_code"] == ts_code].sort_values("rebalance_date")
    if len(sub) == 0:
        print(f"No rows found for ts_code={ts_code}")
        return sub
    print(f"=== {ts_code} ===")
    print(f"  total rows:       {len(sub)}")
    print(f"  in-universe rows: {int(sub['in_universe'].sum())}")
    print(f"  date range:       {sub['rebalance_date'].min().date()} to "
          f"{sub['rebalance_date'].max().date()}")
    print(f"  L1 sector(s):     {sub['l1_name'].dropna().unique().tolist()}")
    print(f"\nFirst 5 rows:")
    print(_show_cols(sub).head().to_string(index=False))
    print(f"\nLast 5 rows:")
    print(_show_cols(sub).tail().to_string(index=False))
    return sub


def show_date(panel: pd.DataFrame, date: str) -> pd.DataFrame:
    target = pd.to_datetime(date)
    sub = panel[panel["rebalance_date"] == target]
    if len(sub) == 0:
        print(f"No rows on rebalance_date={date}.")
        print(f"  Nearest dates: "
              f"{panel.loc[panel['rebalance_date'].sub(target).abs().nsmallest(5).index, 'rebalance_date'].dt.date.tolist()}")
        return sub
    iu = sub[sub["in_universe"]]
    print(f"=== {date} cross-section ===")
    print(f"  total candidate rows: {len(sub)}")
    print(f"  in-universe rows:     {len(iu)}")
    print(f"  log_mcap range (in-univ): "
          f"{iu['log_mcap'].min():.2f} to {iu['log_mcap'].max():.2f}")
    print(f"  ep available (in-univ):   "
          f"{int(iu['ep'].notna().sum())} of {len(iu)}")
    print(f"\nIn-universe sample (sorted by log_mcap descending):")
    print(_show_cols(iu.sort_values("log_mcap", ascending=False))
          .head(10).to_string(index=False))
    return sub


def show_sample(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    sub = panel.sample(n=n, random_state=0)
    print(f"=== Random sample of {n} rows (seed=0) ===")
    print(_show_cols(sub).to_string(index=False))
    return sub


def show_year(panel: pd.DataFrame, year: int) -> pd.DataFrame:
    sub = panel[panel["rebalance_date"].dt.year == year]
    if len(sub) == 0:
        print(f"No rows in year={year}.")
        return sub
    print(f"=== Year {year} summary ===")
    iu = sub[sub["in_universe"]]
    print(f"  rows:             {len(sub):,}")
    print(f"  in-universe rows: {len(iu):,}")
    print(f"  unique dates:     {sub['rebalance_date'].nunique()}")
    print(f"  ep coverage (in-univ): "
          f"{int(iu['ep'].notna().sum()):,} of {len(iu):,} "
          f"({100*iu['ep'].notna().mean():.1f}%)")
    fr = iu.dropna(subset=["forward_return"])
    if len(fr) > 0:
        print(f"  forward_return moments (in-univ):")
        print(f"    mean: {fr['forward_return'].mean()*100:+.3f}%/wk "
              f"(ann ~{fr['forward_return'].mean()*52*100:+.1f}%)")
        print(f"    std:  {fr['forward_return'].std()*100:.3f}%/wk")
    return sub


def _show_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Subset to the columns we usually want when peeking."""
    cols = ["rebalance_date", "ts_code", "in_universe", "close",
            "adj_close", "circ_mv_yi", "log_mcap", "ep", "pe_ttm",
            "l1_name", "forward_return"]
    return df[[c for c in cols if c in df.columns]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stock", type=str,
                    help="ts_code to show (e.g., 000001.SZ)")
    ap.add_argument("--date", type=str,
                    help="rebalance_date to show (YYYY-MM-DD)")
    ap.add_argument("--year", type=int,
                    help="year to summarise")
    ap.add_argument("--sample", type=int,
                    help="show N random rows")
    ap.add_argument("--csv", type=str,
                    help="export selected rows to CSV (combine with other flags)")
    args = ap.parse_args()

    panel = load_or_die()

    sub = None
    if args.stock:
        sub = show_stock(panel, args.stock)
    elif args.date:
        sub = show_date(panel, args.date)
    elif args.year:
        sub = show_year(panel, args.year)
    elif args.sample:
        sub = show_sample(panel, args.sample)
    else:
        diagnostic(panel)

    if args.csv and sub is not None and len(sub) > 0:
        sub.to_csv(args.csv, index=False)
        print(f"\nWrote {len(sub):,} rows to {args.csv}")
    elif args.csv and sub is None:
        print(f"\n--csv requires --stock, --date, --year, or --sample.")


if __name__ == "__main__":
    main()