"""
tushare_fundamentals_fetch.py — Per-stock pulls of income + balancesheet.

User's Tushare token does NOT have *_vip cross-sectional permission, so we
loop per-stock with start_date/end_date filtering on ann_date. One call
per (ts_code, endpoint) over the full γ-relevant window covers all
quarterly reports we'll ever need.

Cache layout:
    data/fina_indicator_raw/income_per_stock/<ts_code>.parquet
    data/fina_indicator_raw/balancesheet_per_stock/<ts_code>.parquet

Convention check (from manual test 2026-05-10 on 000001.SZ):
    n_income_attr_p IS CUMULATIVE within fiscal year:
      2023-Q3 (end 20230930) = 39.6B  (Q1+Q2+Q3 cumulative)
      2023-Q4 (end 20231231) = 46.5B  (full year cumulative)
    Same goes for total_revenue, revenue.
    total_assets is balance-sheet snapshot (point-in-time), not cumulative.

Tushare can return duplicate (ts_code, end_date) rows for amended reports;
we keep the row with the LATEST ann_date — represents the most recent
revision available at any later signal_date.

Usage:
    python tushare_fundamentals_fetch.py status
    python tushare_fundamentals_fetch.py smoke           # 3 stocks × 2 endpoints
    python tushare_fundamentals_fetch.py fetch_universe  # γ-window union universe
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

# tushare_setup.py at repo root. sys.path.append (not insert) per memory
# (May 4 lesson; insert at 0 shadows local modules with stale parents).
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)

from tushare_setup import pro  # noqa: E402

import fr3_config as cfg  # noqa: E402


# ─── Configuration ─────────────────────────────────────────────────────

# γ start is 2024-04-12. Earliest signal_date is end-Apr 2024. To compute
# TTM at 2024-Q1 via "year + same-period diff" we need 2023-Q1, 2023-Q4.
# To be defensive: pull from 2023-01-01 onward (covers 2022-Q4 ann if any
# straggle in early 2023). For balance sheets we want the same: 2023 +.
PULL_START_ANN_DATE = pd.Timestamp("2023-01-01")
PULL_END_ANN_DATE = pd.Timestamp("2026-06-01")

INCOME_DIR = cfg.FINA_INDICATOR_CACHE_DIR / "income_per_stock"
BALANCESHEET_DIR = cfg.FINA_INDICATOR_CACHE_DIR / "balancesheet_per_stock"
INCOME_DIR.mkdir(parents=True, exist_ok=True)
BALANCESHEET_DIR.mkdir(parents=True, exist_ok=True)

ERROR_LOG = cfg.FINA_INDICATOR_CACHE_DIR / "errors_fundamentals.log"

INCOME_FIELDS = (
    "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,"
    "n_income,n_income_attr_p,total_revenue,revenue,operate_profit,total_profit"
)

BALANCESHEET_FIELDS = (
    "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,"
    "total_assets,total_liab,total_hldr_eqy_inc_min_int"
)

# 6 worker threads, per repo precedent (Project_6 daily_panel_pull.py).
N_WORKERS = 6


# ─── Logging ───────────────────────────────────────────────────────────

_logger = logging.getLogger("fr3_fundamentals")
_logger.setLevel(logging.WARNING)
_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_logger.addHandler(_handler)


# ─── Rate limiter ──────────────────────────────────────────────────────

class _RateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self.max = max_per_minute
        self.timestamps: deque = deque()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.time()
                while self.timestamps and now - self.timestamps[0] >= 60:
                    self.timestamps.popleft()
                if len(self.timestamps) < self.max:
                    self.timestamps.append(now)
                    return
                wait = 60 - (now - self.timestamps[0]) + 0.05
            time.sleep(wait)


_rl = _RateLimiter(cfg.TUSHARE_MAX_CALLS_PER_MIN)


def _retry_call(fn, label: str, max_attempts: int = cfg.TUSHARE_MAX_RETRIES):
    delays = [2, 4, 8]
    for attempt in range(max_attempts):
        try:
            _rl.acquire()
            return fn()
        except Exception as exc:
            if attempt == max_attempts - 1:
                raise
            wait = delays[min(attempt, len(delays) - 1)]
            time.sleep(wait)


# ─── Cache helpers ─────────────────────────────────────────────────────

def _income_path(ts_code: str) -> Path:
    return INCOME_DIR / f"{ts_code}.parquet"


def _balancesheet_path(ts_code: str) -> Path:
    return BALANCESHEET_DIR / f"{ts_code}.parquet"


def _is_cached(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        import pyarrow.parquet as pq
        pq.read_schema(path)
        return True
    except Exception:
        return False


# ─── Per-stock pulls ───────────────────────────────────────────────────

def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ts_code"] = df["ts_code"].astype(str)
    df["ann_date"] = pd.to_datetime(df["ann_date"], format="%Y%m%d", errors="coerce")
    df["end_date"] = pd.to_datetime(df["end_date"], format="%Y%m%d", errors="coerce")
    if "f_ann_date" in df.columns:
        df["f_ann_date"] = pd.to_datetime(df["f_ann_date"], format="%Y%m%d", errors="coerce")
    for c in df.columns:
        if c not in {"ts_code", "ann_date", "f_ann_date", "end_date",
                     "report_type", "comp_type"}:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    df = df.dropna(subset=["ann_date", "end_date"])
    # Keep most recent ann_date per (ts_code, end_date) — i.e., latest revision.
    df = df.sort_values("ann_date").drop_duplicates(
        subset=["ts_code", "end_date"], keep="last"
    )
    return df.reset_index(drop=True)


def _fetch_one_income(ts_code: str) -> str:
    path = _income_path(ts_code)
    if _is_cached(path):
        return "cached"
    try:
        df = _retry_call(
            lambda: pro.income(
                ts_code=ts_code,
                start_date=PULL_START_ANN_DATE.strftime("%Y%m%d"),
                end_date=PULL_END_ANN_DATE.strftime("%Y%m%d"),
                fields=INCOME_FIELDS,
            ),
            label=f"income {ts_code}",
        )
    except Exception as exc:
        _logger.warning(f"income {ts_code}: {exc}")
        return "failed"
    if df is None or len(df) == 0:
        # Empty parquet so we don't re-pull every run (write a sentinel)
        empty = pd.DataFrame(
            columns=INCOME_FIELDS.split(",")
        )
        empty.to_parquet(path, compression=cfg.COMPRESSION, index=False)
        return "empty"
    df = _normalize(df)
    df.to_parquet(path, compression=cfg.COMPRESSION, index=False)
    return "pulled"


def _fetch_one_balancesheet(ts_code: str) -> str:
    path = _balancesheet_path(ts_code)
    if _is_cached(path):
        return "cached"
    try:
        df = _retry_call(
            lambda: pro.balancesheet(
                ts_code=ts_code,
                start_date=PULL_START_ANN_DATE.strftime("%Y%m%d"),
                end_date=PULL_END_ANN_DATE.strftime("%Y%m%d"),
                fields=BALANCESHEET_FIELDS,
            ),
            label=f"balancesheet {ts_code}",
        )
    except Exception as exc:
        _logger.warning(f"balancesheet {ts_code}: {exc}")
        return "failed"
    if df is None or len(df) == 0:
        empty = pd.DataFrame(columns=BALANCESHEET_FIELDS.split(","))
        empty.to_parquet(path, compression=cfg.COMPRESSION, index=False)
        return "empty"
    df = _normalize(df)
    df.to_parquet(path, compression=cfg.COMPRESSION, index=False)
    return "pulled"


# ─── Drivers ────────────────────────────────────────────────────────────

def fetch_for_codes(ts_codes: list[str], endpoint: str,
                    verbose: bool = True) -> dict[str, int]:
    """Threaded per-stock fetch. Returns counts dict."""
    if endpoint == "income":
        worker = _fetch_one_income
    elif endpoint == "balancesheet":
        worker = _fetch_one_balancesheet
    else:
        raise ValueError(f"unknown endpoint {endpoint}")

    counts = {"pulled": 0, "cached": 0, "empty": 0, "failed": 0}
    n = len(ts_codes)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futures = {ex.submit(worker, c): c for c in ts_codes}
        for i, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            counts[res] = counts.get(res, 0) + 1
            if verbose and (i % 50 == 0 or i == n):
                mins = (time.time() - t0) / 60
                rate = i / max(mins, 0.001)
                print(f"  [{i:>4}/{n}] {endpoint:<14s} "
                      f"pulled={counts['pulled']} cached={counts['cached']} "
                      f"empty={counts['empty']} failed={counts['failed']} "
                      f"({rate:.0f}/min, {mins:.1f}min)")
    return counts


def smoke_test() -> None:
    print("=" * 60)
    print("SMOKE: 3 stocks × 2 endpoints")
    print("=" * 60)
    test_codes = ["000001.SZ", "600000.SH", "300750.SZ"]
    for endpoint in ("income", "balancesheet"):
        for ts in test_codes:
            t0 = time.time()
            res = (_fetch_one_income(ts) if endpoint == "income"
                   else _fetch_one_balancesheet(ts))
            elapsed = time.time() - t0
            path = _income_path(ts) if endpoint == "income" else _balancesheet_path(ts)
            if path.exists():
                df = pd.read_parquet(path)
                print(f"  {endpoint:<14s} {ts}: {res:<6s} "
                      f"{len(df):>3} reports, "
                      f"end_dates {df['end_date'].min().date() if len(df) else 'none'}.."
                      f"{df['end_date'].max().date() if len(df) else 'none'}, "
                      f"elapsed={elapsed:.1f}s")
            else:
                print(f"  {endpoint:<14s} {ts}: {res}")


def fetch_universe() -> None:
    """
    Compute the γ-window union universe and pull income+balancesheet for
    every member.

    Union = (canonical universe at any γ rebalance) ∪ (CSI300 at any γ snapshot)
            ∪ (a margin of comparator names from CSI300 cache).
    """
    import data_loaders as dl

    cal = dl.load_trading_calendar()
    sigs = dl.monthly_signal_dates(cfg.GAMMA_START, cfg.GAMMA_END, cal)
    # canonical
    canonical_union: set[str] = set()
    for s in sigs:
        canonical_union |= dl.get_canonical_universe_at(s, cal)
    # CSI300 from index_constituents cache
    csi300_union: set[str] = set()
    for path in cfg.INDEX_CONSTITUENTS_DIR.glob("csi300_*.parquet"):
        ymd = path.stem.split("_", 1)[1]  # YYYY-MM
        # Only γ-window snapshots
        try:
            yr, mo = ymd.split("-")
            snap_date = pd.Timestamp(year=int(yr), month=int(mo), day=1) + pd.offsets.MonthEnd(0)
        except Exception:
            continue
        if snap_date < cfg.GAMMA_START - pd.DateOffset(months=1):
            continue
        if snap_date > cfg.GAMMA_END + pd.DateOffset(months=1):
            continue
        df = pd.read_parquet(path)
        csi300_union |= set(df["ts_code"].astype(str))

    union = canonical_union | csi300_union
    # Restrict to A-share pattern (drop 北交所 etc.)
    import re
    pat = re.compile(cfg.A_SHARE_PATTERN)
    union = {c for c in union if pat.match(c)}
    union_sorted = sorted(union)

    print(f"γ-window universe union: {len(union_sorted):,} stocks")
    print(f"  canonical: {len(canonical_union):,}")
    print(f"  CSI300:    {len(csi300_union):,}")
    print(f"  overlap:   {len(canonical_union & csi300_union):,}")

    print(f"\nPULL: income for {len(union_sorted)} stocks")
    counts_i = fetch_for_codes(union_sorted, "income")
    print(f"  → {counts_i}")

    print(f"\nPULL: balancesheet for {len(union_sorted)} stocks")
    counts_b = fetch_for_codes(union_sorted, "balancesheet")
    print(f"  → {counts_b}")


def status() -> None:
    n_income = len(list(INCOME_DIR.glob("*.parquet")))
    n_bs = len(list(BALANCESHEET_DIR.glob("*.parquet")))
    print(f"Cache status:")
    print(f"  income_per_stock:        {n_income:>5} parquets")
    print(f"  balancesheet_per_stock:  {n_bs:>5} parquets")
    if n_income:
        sample = next(INCOME_DIR.glob("*.parquet"))
        df = pd.read_parquet(sample)
        print(f"  sample income {sample.stem}: {len(df)} rows, "
              f"end_dates {df['end_date'].min().date() if len(df) else '—'}..."
              f"{df['end_date'].max().date() if len(df) else '—'}")


# ─── Loaders for downstream ────────────────────────────────────────────

def load_income_panel(ts_codes: list[str] | None = None) -> pd.DataFrame:
    """Concat per-stock income parquets into a single panel."""
    paths = sorted(INCOME_DIR.glob("*.parquet"))
    if ts_codes is not None:
        wanted = set(ts_codes)
        paths = [p for p in paths if p.stem in wanted]
    frames = []
    for p in paths:
        try:
            df = pd.read_parquet(p)
            if len(df) > 0:
                frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=INCOME_FIELDS.split(","))
    out = pd.concat(frames, ignore_index=True)
    return out


def load_balancesheet_panel(ts_codes: list[str] | None = None) -> pd.DataFrame:
    """Concat per-stock balancesheet parquets into a single panel."""
    paths = sorted(BALANCESHEET_DIR.glob("*.parquet"))
    if ts_codes is not None:
        wanted = set(ts_codes)
        paths = [p for p in paths if p.stem in wanted]
    frames = []
    for p in paths:
        try:
            df = pd.read_parquet(p)
            if len(df) > 0:
                frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=BALANCESHEET_FIELDS.split(","))
    out = pd.concat(frames, ignore_index=True)
    return out


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "smoke":
        smoke_test()
    elif mode == "fetch_universe":
        fetch_universe()
    elif mode == "status":
        status()
    else:
        print("Usage: python tushare_fundamentals_fetch.py [smoke|fetch_universe|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
