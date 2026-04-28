"""
One-off concurrency diagnostic. NOT part of the main pipeline.

Tests 4 worker threads with 200ms per-thread pacing on 2024-12-31 to see
whether reduced concurrency + request spacing stabilizes throughput
relative to the 8-worker bursty pattern in universe_construction.py.

Imports helpers from universe_construction.py without modifying it.
"""

import sys
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed

import baostock as bs

from Project_5.archive.universe_construction import (
    get_all_listings,
    filter_a_shares,
    _thread_login,
    _log_error,
)

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


N_DIAG_WORKERS = 4
INTER_QUERY_DELAY = 0.2   # 200ms per-thread pacing
DATE = "2024-12-31"


def _fetch_with_pacing(code, date):
    """Worker variant with a 200ms sleep at the end. Mirrors
    _fetch_single_stock_kdata's behaviour otherwise."""
    fields = "code,close,volume,amount,turn,tradestatus,isST"
    try:
        rs = bs.query_history_k_data_plus(
            code, fields,
            start_date=date, end_date=date,
            frequency="d", adjustflag="2",
        )
        if rs.error_code != "0":
            _log_error("diag", date, code, rs.error_msg)
            return None
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return dict(zip(fields.split(","), rows[0])) if rows else None
    except Exception as e:
        _log_error("diag", date, code, str(e))
        return None
    finally:
        time.sleep(INTER_QUERY_DELAY)


def main():
    print("=" * 60)
    print(f"DIAGNOSTIC — {N_DIAG_WORKERS} workers, "
          f"{int(INTER_QUERY_DELAY*1000)}ms per-thread pacing")
    print("=" * 60)

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"Main login failed: {lg.error_msg}")
    try:
        listings = get_all_listings(DATE)
    finally:
        bs.logout()

    codes = filter_a_shares(listings)["code"].tolist()
    print(f"Testing on {len(codes)} A-share codes")

    # Same timeout policy as the main pipeline
    overall_timeout = max(900.0, len(codes) * 0.2)
    print(f"Pool timeout: {overall_timeout:.0f}s")

    t0 = time.time()
    completions = []  # relative completion times (seconds from t0)
    successes = 0
    done = 0

    pool = ThreadPoolExecutor(max_workers=N_DIAG_WORKERS, initializer=_thread_login)
    try:
        futures = [pool.submit(_fetch_with_pacing, c, DATE) for c in codes]
        try:
            for fut in as_completed(futures, timeout=overall_timeout):
                completions.append(time.time() - t0)
                try:
                    r = fut.result()
                except Exception as e:
                    _log_error("diag", DATE, "?", f"future error: {e}")
                    r = None
                if r is not None:
                    successes += 1
                done += 1
                if done % 200 == 0:
                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed else 0
                    print(f"  {done}/{len(codes)} done in {elapsed:.0f}s "
                          f"(success={successes}, {rate:.2f} stocks/sec)")
        except concurrent.futures.TimeoutError:
            hung = sum(1 for f in futures if not f.done())
            print(f"  WARNING: pool timeout after {overall_timeout:.0f}s; "
                  f"{hung} queries still running")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print("RESULTS")
    print("=" * 60)
    print(f"Wall-clock elapsed:       {elapsed:.1f}s")
    print(f"Stocks fetched (success): {successes}/{len(codes)}")
    print(f"Futures completed:        {done}/{len(codes)}")

    # 60-sec window throughput, skipping first 100 completions
    if len(completions) > 100:
        warmup_end = completions[99]
        post_warmup = [t - warmup_end for t in completions[100:]]
        last = post_warmup[-1]
        print(f"\nThroughput in 60s windows (warmup = first 100 completions):")
        print(f"  Window start (s) | Queries completed | Rate (stocks/sec)")
        print(f"  {'-'*60}")
        rates = []
        w = 0
        while w <= last:
            count = sum(1 for t in post_warmup if w <= t < w + 60)
            # ignore trailing partial windows with fewer than 30s of data
            if last - w >= 30:
                rate = count / 60.0
                rates.append(rate)
                print(f"  {w:>10.0f}       | {count:>10}         | {rate:.2f}")
            w += 60

        if len(rates) >= 2:
            first_half = rates[:len(rates)//2]
            second_half = rates[len(rates)//2:]
            first_mean = sum(first_half) / len(first_half)
            second_mean = sum(second_half) / len(second_half)
            delta = second_mean - first_mean
            print(f"\n  First-half mean rate:  {first_mean:.2f} stocks/sec")
            print(f"  Second-half mean rate: {second_mean:.2f} stocks/sec")
            print(f"  Delta:                 {delta:+.2f} stocks/sec "
                  f"({delta/first_mean*100:+.1f}%)")
            if abs(delta) / first_mean < 0.1:
                print(f"  => HELD STEADY (within ±10% across halves)")
            elif delta < 0:
                print(f"  => DEGRADED over run")
            else:
                print(f"  => IMPROVED over run")
    else:
        print(f"\nNot enough completions ({len(completions)}) to compute "
              f"windowed throughput.")


if __name__ == "__main__":
    main()
