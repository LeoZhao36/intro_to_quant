"""
Live progress monitor for the running Stage 1 loop.

Reads data/candidates/ to count completed dates and parses the main
process's stdout log for within-date stock progress. Computes ETA using
the fixed 3.0 stocks/sec measured throughput (no re-estimation — the
rate-limit warmup skews short-horizon numbers).

Usage:
    python monitor_stage1.py           # live, refreshes every 30s
    python monitor_stage1.py --once    # print one line and exit
    python monitor_stage1.py --log PATH  # point at a specific log file
"""

import sys
import re
import time
import argparse
from pathlib import Path

import pandas as pd


DATA_DIR = Path("data")
CANDIDATES_DIR = DATA_DIR / "candidates"
REBALANCE_DATES_CSV = DATA_DIR / "rebalance_dates.csv"

THROUGHPUT = 3.0          # stocks/sec, measured
AVG_STOCKS_PER_DATE = 5100  # used for ETA denominator only


_STAGE1_MARKER = "Stage 1: 52 rebalance dates"


def find_log_file():
    """Best-effort auto-detect of the Stage 1 background-task output file.
    Scans ~/AppData/Local/Temp/claude for .output files containing the
    Stage 1 startup banner, returns the most recently modified match."""
    base = Path.home() / "AppData" / "Local" / "Temp" / "claude"
    if not base.exists():
        return None
    matches = []
    for p in base.glob("**/tasks/*.output"):
        try:
            # read only first few KB; the banner appears near the top
            with p.open("r", encoding="utf-8", errors="replace") as f:
                head = f.read(4096)
        except OSError:
            continue
        if _STAGE1_MARKER in head:
            matches.append(p)
    if not matches:
        return None
    return max(matches, key=lambda f: f.stat().st_mtime)


_PROGRESS_RE = re.compile(r"(\d+)/(\d+)\s+done\s+in")


def parse_within_date_progress(log_path):
    """Return (stocks_done, stocks_total) from the most recent progress
    line in the log, or (None, None) if not found."""
    if not log_path or not log_path.exists():
        return None, None
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    for line in reversed(text.splitlines()):
        m = _PROGRESS_RE.search(line)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def format_hms(seconds):
    if seconds < 0:
        return "?"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def format_elapsed(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_status(dates, log_path, start_wall):
    n_total = len(dates)
    cached = sorted(CANDIDATES_DIR.glob("candidates_*.csv"))
    n_done = len(cached)

    if n_done >= n_total:
        return ("DONE: all 52 dates processed", True)

    n_current = n_done + 1
    cur_date = dates[n_current - 1]

    cur_done, cur_total = parse_within_date_progress(log_path)
    if cur_done is None:
        cur_done, cur_total = 0, AVG_STOCKS_PER_DATE

    overall_done = n_done * AVG_STOCKS_PER_DATE + cur_done
    overall_total = n_total * AVG_STOCKS_PER_DATE
    remaining = max(0, overall_total - overall_done)
    eta_sec = remaining / THROUGHPUT
    elapsed = time.time() - start_wall

    cur_pct = (cur_done / cur_total * 100) if cur_total else 0
    overall_pct = overall_done / overall_total * 100

    status = (
        f"[{format_elapsed(elapsed)} elapsed] "
        f"Date {n_current}/{n_total} ({cur_date}, {n_current/n_total*100:.1f}%) | "
        f"{cur_done}/{cur_total} this date ({cur_pct:.1f}%) | "
        f"overall {overall_done:,}/{overall_total:,} "
        f"({overall_pct:.1f}%) | "
        f"ETA: {format_hms(eta_sec)}"
    )
    return (status, False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=None, help="path to Stage 1 stdout log")
    ap.add_argument("--once", action="store_true",
                    help="print one line and exit")
    ap.add_argument("--interval", type=int, default=30,
                    help="refresh seconds (default 30)")
    args = ap.parse_args()

    if not REBALANCE_DATES_CSV.exists():
        print(f"ERROR: {REBALANCE_DATES_CSV} not found — "
              f"run from Project_5 directory")
        sys.exit(1)
    dates = pd.read_csv(REBALANCE_DATES_CSV)["date"].tolist()

    log_path = Path(args.log) if args.log else find_log_file()
    if log_path:
        print(f"Log file: {log_path}", flush=True)
    else:
        print("Log file: not found (within-date progress will be unavailable)",
              flush=True)

    start_wall = time.time()

    if args.once:
        status, _ = build_status(dates, log_path, start_wall)
        print(status)
        return

    try:
        while True:
            status, done = build_status(dates, log_path, start_wall)
            pad = status.ljust(200)
            sys.stdout.write("\r" + pad)
            sys.stdout.flush()
            if done:
                print()
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
