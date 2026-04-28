"""
forward_return_panel.py — universe-conditional forward return panel.

Builds a per-(rebalance_date, ts_code) panel of forward returns and tradability
flags, restricted to in-universe stocks. This is the file Project 6 factor
research will consume.

Architecture
------------
Three passes, following Stage 2's established pattern:

1. Determine unique rebalance dates from universe_membership.csv (52 dates).
2. Ensure daily, adj_factor, and stk_limit panels are cached cross-sectionally
   per date. Pull from Tushare with retry-on-network-error if not cached.
3. Build the forward return panel by iterating consecutive (R, R+1) pairs.

We maintain our own daily panel cache (data/daily_panels_full/) rather than
reusing Stage 2's data/daily_panels/, because Stage 2 trimmed the cached
columns down to what the liquidity panel needed and dropped `close`. The
architectural lesson: caches optimized for one consumer are fragile when
reused by another. Disk cost of the duplication is negligible (~15 MB).

Forward return formula. Total return including dividend reinvestment, using
Tushare's adj_factor convention (adjusts for both 派息 and 送股/转股):

    forward_return = (close[R+1] * adj_factor[R+1]) /
                     (close[R]   * adj_factor[R])    -  1

The latest_adj_factor that would normally appear in qfq computation cancels
in the ratio, so we never need to define a "latest" reference date.

Tradability flags use Tushare's stk_limit endpoint, which returns the
exchange's published upper and lower limit prices for each stock-day.
This is more authoritative than computing limits from prev_close + board
class, and sidesteps the rounding rule mismatch between Python and the
exchange entirely.

    entry_tradable = present in daily_R   AND close_R   != up_limit_R
    exit_tradable  = present in daily_R+1 AND close_R+1 != down_limit_R+1

The asymmetry (涨停 blocks entry, 跌停 blocks exit) reflects queue mechanics:
at 涨停, buyers queue against withdrawn sellers, so late-arriving buyers
cannot get fills. At 跌停, the reverse for sellers.

Outputs
-------
data/forward_return_panel.csv           — production output
data/adj_factor_panels/adj_<date>.csv   — per-date adj_factor cache
data/stk_limit_panels/lim_<date>.csv    — per-date stk_limit cache

Usage
-----
    python forward_return_panel.py smoke   # first 2 (R, R+1) pairs only
    python forward_return_panel.py full    # all 51 pairs
"""

import os
import sys
import time
from typing import Callable

import pandas as pd
import matplotlib.pyplot as plt

from tushare_setup import pro


# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

DATA_DIR        = "data"
UNIVERSE_PATH   = f"{DATA_DIR}/universe_membership.csv"
DAILY_CACHE_DIR = f"{DATA_DIR}/daily_panels_full"       # our own, not Stage 2's
ADJ_CACHE_DIR   = f"{DATA_DIR}/adj_factor_panels"       # new
LIMIT_CACHE_DIR = f"{DATA_DIR}/stk_limit_panels"        # new

OUTPUT_PATH       = f"{DATA_DIR}/forward_return_panel.csv"
SMOKE_OUTPUT_PATH = f"{DATA_DIR}/forward_return_panel_smoke.csv"
PLOT_PATH         = f"{DATA_DIR}/forward_return_panel_diagnostic.png"

# Tolerance for matching close to limit price. Both are 2-decimal floats from
# Tushare, so half-a-分 absorbs any floating-point representation noise.
LIMIT_TOL = 0.005

STIMULUS_DATE = "2024-09-24"  # PBoC stimulus reference for diagnostic plot


# ---------------------------------------------------------------------------
# Network resilience (local copy of Stage 2 helper for now)
# ---------------------------------------------------------------------------

def _retry_on_network_error(fn: Callable, *args, max_attempts: int = 4, **kwargs):
    """
    Call fn(*args, **kwargs) with exponential backoff on transient errors.
    Mirrors Stage 2's helper. ReadTimeout and similar should be transient at
    this call volume; persistent errors after 4 attempts re-raise.
    """
    delays = [2, 4, 8]
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if attempt == max_attempts - 1:
                raise
            delay = delays[min(attempt, len(delays) - 1)]
            print(f"    retry attempt {attempt + 1} after error: {exc}")
            time.sleep(delay)


# ---------------------------------------------------------------------------
# Date format helpers
# ---------------------------------------------------------------------------

def date_to_yyyymmdd(date_str: str) -> str:
    """'2024-09-18' -> '20240918'."""
    return date_str.replace("-", "")


# ---------------------------------------------------------------------------
# Pass 2: ensure cached panels for adj_factor and stk_limit
# ---------------------------------------------------------------------------

def ensure_adj_factor_cached(rebalance_date: str) -> pd.DataFrame:
    """Read adj_factor for one date from cache, pulling and caching if absent."""
    path = f"{ADJ_CACHE_DIR}/adj_{rebalance_date}.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    os.makedirs(ADJ_CACHE_DIR, exist_ok=True)
    td = date_to_yyyymmdd(rebalance_date)
    df = _retry_on_network_error(pro.adj_factor, trade_date=td)
    df.to_csv(path, index=False)
    return df


def ensure_stk_limit_cached(rebalance_date: str) -> pd.DataFrame:
    """Read stk_limit for one date from cache, pulling and caching if absent."""
    path = f"{LIMIT_CACHE_DIR}/lim_{rebalance_date}.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    os.makedirs(LIMIT_CACHE_DIR, exist_ok=True)
    td = date_to_yyyymmdd(rebalance_date)
    df = _retry_on_network_error(pro.stk_limit, trade_date=td)
    df.to_csv(path, index=False)
    return df


def ensure_daily_cached(rebalance_date: str) -> pd.DataFrame:
    """
    Read daily for one date from our own cache, pulling and caching if absent.
    Stores the full pro.daily() output (all columns) so any future consumer
    can use any field without re-pulling.
    """
    path = f"{DAILY_CACHE_DIR}/daily_{rebalance_date}.csv"
    if os.path.exists(path):
        return pd.read_csv(path)
    os.makedirs(DAILY_CACHE_DIR, exist_ok=True)
    td = date_to_yyyymmdd(rebalance_date)
    df = _retry_on_network_error(pro.daily, trade_date=td)
    df.to_csv(path, index=False)
    return df


def ensure_all_panels_cached(rebalance_dates: list) -> None:
    """Pull daily, adj_factor, and stk_limit for any uncached dates."""
    print(f"\nPass 2: ensuring panels cached for {len(rebalance_dates)} dates")
    n_pulled = {"daily": 0, "adj": 0, "lim": 0}
    for i, d in enumerate(rebalance_dates, start=1):
        for kind, path_fn, ensure_fn in (
            ("daily", lambda x: f"{DAILY_CACHE_DIR}/daily_{x}.csv", ensure_daily_cached),
            ("adj",   lambda x: f"{ADJ_CACHE_DIR}/adj_{x}.csv",     ensure_adj_factor_cached),
            ("lim",   lambda x: f"{LIMIT_CACHE_DIR}/lim_{x}.csv",   ensure_stk_limit_cached),
        ):
            was_cached = os.path.exists(path_fn(d))
            ensure_fn(d)
            if not was_cached:
                n_pulled[kind] += 1
        if i % 10 == 0 or i == len(rebalance_dates):
            print(f"  [{i}/{len(rebalance_dates)}] {d} done. "
                  f"Pulled so far: daily={n_pulled['daily']}, "
                  f"adj={n_pulled['adj']}, lim={n_pulled['lim']}")
    print(f"  Total fresh pulls: daily={n_pulled['daily']}, "
          f"adj={n_pulled['adj']}, lim={n_pulled['lim']}")


# ---------------------------------------------------------------------------
# Per-date snapshot: merge the three sources into one frame
# ---------------------------------------------------------------------------

def build_snapshot(rebalance_date: str) -> pd.DataFrame:
    """
    Return a DataFrame indexed on ts_code with columns:
        close, adj_factor, up_limit, down_limit
    All three sources joined for a single rebalance date.
    """
    daily = ensure_daily_cached(rebalance_date)[["ts_code", "close"]]
    adj   = ensure_adj_factor_cached(rebalance_date)[["ts_code", "adj_factor"]]
    lim   = ensure_stk_limit_cached(rebalance_date)[["ts_code", "up_limit", "down_limit"]]

    snap = (daily
            .merge(adj, on="ts_code", how="left")
            .merge(lim, on="ts_code", how="left"))
    return snap.set_index("ts_code")


# ---------------------------------------------------------------------------
# Pass 3: build the forward return panel one (R, R+1) pair at a time
# ---------------------------------------------------------------------------

def compute_pair_returns(R: str, Rp1: str, universe_codes: list) -> pd.DataFrame:
    """
    Compute forward returns and tradability flags for one (R, R+1) pair,
    restricted to the in-universe stocks at R.
    """
    snap_R   = build_snapshot(R)
    snap_Rp1 = build_snapshot(Rp1)

    # Reindex onto the universe at R; missing values become NaN
    df = pd.DataFrame(index=pd.Index(universe_codes, name="ts_code"))
    df["close_R"]         = snap_R["close"].reindex(df.index)
    df["adj_R"]           = snap_R["adj_factor"].reindex(df.index)
    df["up_limit_R"]      = snap_R["up_limit"].reindex(df.index)
    df["close_Rp1"]       = snap_Rp1["close"].reindex(df.index)
    df["adj_Rp1"]         = snap_Rp1["adj_factor"].reindex(df.index)
    df["down_limit_Rp1"]  = snap_Rp1["down_limit"].reindex(df.index)

    # Forward return — total return after corporate-action adjustment.
    # NaN if either close or adj_factor is missing on either date.
    df["forward_return"] = (
        (df["close_Rp1"] * df["adj_Rp1"]) /
        (df["close_R"]   * df["adj_R"])
        - 1
    )

    # Entry tradable: stock traded on R AND not at upper limit.
    # If up_limit is NaN (shouldn't happen for active A-shares but be safe),
    # treat as no-constraint rather than blocking — the conservative choice
    # would distort the universe in the other direction.
    present_R = df["close_R"].notna()
    not_up_R  = ((df["close_R"] - df["up_limit_R"]).abs() >= LIMIT_TOL) | df["up_limit_R"].isna()
    df["entry_tradable"] = present_R & not_up_R

    # Exit tradable: same logic on the down side at R+1.
    present_Rp1 = df["close_Rp1"].notna()
    not_dn_Rp1  = ((df["close_Rp1"] - df["down_limit_Rp1"]).abs() >= LIMIT_TOL) | df["down_limit_Rp1"].isna()
    df["exit_tradable"] = present_Rp1 & not_dn_Rp1

    df["rebalance_date"] = R
    df = df.reset_index()
    return df[["rebalance_date", "ts_code", "forward_return",
               "entry_tradable", "exit_tradable"]]


def build_panel(smoke: bool = False) -> pd.DataFrame:
    """Orchestrate Passes 1-3 and return the assembled panel."""
    # ---- Pass 1: load universe and determine rebalance dates ----
    print("Pass 1: loading universe and determining rebalance dates")
    universe = pd.read_csv(UNIVERSE_PATH)
    universe = universe[universe["in_universe"] == True]
    rebalance_dates = sorted(universe["rebalance_date"].unique())
    print(f"  {len(universe):,} in-universe rows across {len(rebalance_dates)} dates")

    # ---- Pass 2: ensure adj and limit panels cached ----
    ensure_all_panels_cached(rebalance_dates)

    # ---- Pass 3: build pair returns ----
    pairs = list(zip(rebalance_dates[:-1], rebalance_dates[1:]))
    if smoke:
        pairs = pairs[:2]
        print(f"\nSMOKE MODE: building panel for {len(pairs)} pairs only")
    else:
        print(f"\nPass 3: building panel for {len(pairs)} (R, R+1) pairs")

    frames = []
    for i, (R, Rp1) in enumerate(pairs, start=1):
        codes = universe[universe["rebalance_date"] == R]["ts_code"].tolist()
        frame = compute_pair_returns(R, Rp1, codes)
        frames.append(frame)
        n_ret = frame["forward_return"].notna().sum()
        n_ent = frame["entry_tradable"].sum()
        n_ext = frame["exit_tradable"].sum()
        print(f"  [{i}/{len(pairs)}] {R} -> {Rp1}: "
              f"returns_computed={n_ret}, entry_tradable={n_ent}, exit_tradable={n_ext}")

    panel = pd.concat(frames, ignore_index=True)
    return panel


def write_panel(panel: pd.DataFrame, smoke: bool) -> str:
    out = SMOKE_OUTPUT_PATH if smoke else OUTPUT_PATH
    panel.to_csv(out, index=False)
    print(f"\nWrote {len(panel):,} rows to {out}")
    return out


# ---------------------------------------------------------------------------
# Diagnostic plot
# ---------------------------------------------------------------------------

def plot_diagnostic(panel: pd.DataFrame, output_path: str = PLOT_PATH) -> None:
    """
    Two-row diagnostic. Top: forward_return cross-sectional summary per
    rebalance date — mean and ±2σ bands. Bottom: tradability rates per
    rebalance date — share of stocks where entry or exit was blocked.
    Stimulus reference line on both panels.
    """
    # Aggregate per rebalance date
    agg = (panel
           .groupby("rebalance_date")
           .agg(mean_ret=("forward_return", "mean"),
                std_ret=("forward_return", "std"),
                entry_blocked_rate=("entry_tradable", lambda s: 1 - s.mean()),
                exit_blocked_rate=("exit_tradable",  lambda s: 1 - s.mean()))
           .reset_index())
    agg["rebalance_date"] = pd.to_datetime(agg["rebalance_date"])
    agg = agg.sort_values("rebalance_date")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # --- Top: return distribution ---
    ax1.fill_between(agg["rebalance_date"],
                     agg["mean_ret"] - 2 * agg["std_ret"],
                     agg["mean_ret"] + 2 * agg["std_ret"],
                     alpha=0.2, label="±2σ")
    ax1.plot(agg["rebalance_date"], agg["mean_ret"],
             linewidth=2, label="Cross-sectional mean")
    ax1.axhline(0, color="black", linewidth=0.5)
    ax1.axvline(pd.to_datetime(STIMULUS_DATE), color="red", linestyle="--",
                linewidth=1, label="2024-09 stimulus")
    ax1.set_ylabel("Forward return (R → R+1)")
    ax1.set_title("Universe-conditional forward return distribution per rebalance date")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)

    # --- Bottom: tradability rates ---
    ax2.plot(agg["rebalance_date"], agg["entry_blocked_rate"],
             linewidth=2, label="entry_tradable == False (涨停 + suspended)")
    ax2.plot(agg["rebalance_date"], agg["exit_blocked_rate"],
             linewidth=2, label="exit_tradable == False  (跌停 + suspended)")
    ax2.axvline(pd.to_datetime(STIMULUS_DATE), color="red", linestyle="--", linewidth=1)
    ax2.set_ylabel("Blocked share of universe")
    ax2.set_xlabel("Rebalance date")
    ax2.set_title("Phantom-return rate: share of universe that cannot transact at close")
    ax2.legend(loc="upper left")
    ax2.grid(True, alpha=0.3)
    ax2.yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))

    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    print(f"Wrote diagnostic plot to {output_path}")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if mode not in {"smoke", "full"}:
        print(f"Usage: python {sys.argv[0]} [smoke|full]")
        sys.exit(1)
    smoke = (mode == "smoke")

    panel = build_panel(smoke=smoke)
    out_path = write_panel(panel, smoke=smoke)
    plot_diagnostic(panel,
                    output_path=PLOT_PATH if not smoke
                    else f"{DATA_DIR}/forward_return_panel_smoke_diagnostic.png")

    # Headline numbers
    print("\nHeadline numbers")
    print(f"  Total rows:              {len(panel):,}")
    print(f"  Forward returns computed: {panel['forward_return'].notna().sum():,} "
          f"({panel['forward_return'].notna().mean():.1%})")
    print(f"  Entry tradable rate:      {panel['entry_tradable'].mean():.1%}")
    print(f"  Exit tradable rate:       {panel['exit_tradable'].mean():.1%}")
    print(f"  Both tradable rate:       "
          f"{(panel['entry_tradable'] & panel['exit_tradable']).mean():.1%}")


if __name__ == "__main__":
    main()