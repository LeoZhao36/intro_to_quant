"""
stage4_sector_classification.py — Stage 4: 申万 SW2021 sector pull.

Pulls the 申万 (Shenwan Hongyuan) SW2021 hierarchy and full L3 membership
in one shot. Used by future factor pipelines for sector-neutral construction.

Two endpoints:
  - pro.index_classify(level='L1'/'L2'/'L3', src='SW2021')
    Returns the SW2021 taxonomy: ~31 L1 sectors, ~134 L2, ~346 L3 sub-industries.

  - pro.index_member_all(l3_code=<l3_code>)
    For each L3 code, returns the historical membership rows with
    in_date / out_date for each constituent stock.

API calls
---------
  3 calls for the classification + ~346 calls for L3 memberships = ~349 total.
  At basic-tier rate, roughly 70-90 seconds wall time.

Output
------
data/sw_classification.csv    L1/L2/L3 taxonomy
data/sw_membership.csv        full membership: ts_code, l1_*, l2_*, l3_*,
                              in_date, out_date

Note on point-in-time use
-------------------------
Each membership row has an in_date and (sometimes) out_date. To get a
stock's L1 sector AS OF a given date, filter to rows where:
    in_date <= date AND (out_date IS NULL OR out_date > date)

A stock can be reclassified between L3 sub-industries; the L1 above it
generally remains stable. For sector-neutral factor construction, the
L1 mapping at the rebalance date is what matters. A helper for this
lookup will be built in the candidate-history panel script that consumes
this data.

Usage
-----
    python stage4_sector_classification.py smoke   # taxonomy + 1 L3 sample
    python stage4_sector_classification.py full    # taxonomy + all L3 memberships
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

from tushare_setup import pro

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass


DATA_DIR = Path("data")
SW_CLASSIFICATION_PATH = DATA_DIR / "sw_classification.csv"
SW_MEMBERSHIP_PATH = DATA_DIR / "sw_membership.csv"
ERROR_LOG = DATA_DIR / "errors_stage4_sector.log"

DATA_DIR.mkdir(exist_ok=True)


_logger = logging.getLogger("stage4_sector")
_logger.setLevel(logging.WARNING)
_handler = logging.FileHandler(ERROR_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_logger.addHandler(_handler)


def _retry_on_network_error(fn, max_retries=4, base_wait=2):
    delays = [2, 4, 8]
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            wait = delays[min(attempt, len(delays) - 1)]
            print(f"    Network error ({type(exc).__name__}: {exc}), "
                  f"retry in {wait}s...")
            time.sleep(wait)


def pull_classification():
    """Pull L1/L2/L3 taxonomy. Cached on first run."""
    if SW_CLASSIFICATION_PATH.exists():
        print(f"Loading cached classification from {SW_CLASSIFICATION_PATH}")
        return pd.read_csv(SW_CLASSIFICATION_PATH)

    print("Pulling SW2021 classification from Tushare (3 calls)...")
    frames = []
    for level in ["L1", "L2", "L3"]:
        df = _retry_on_network_error(
            lambda lv=level: pro.index_classify(level=lv, src="SW2021")
        )
        df["level"] = level
        frames.append(df)
        print(f"  {level}: {len(df)} rows")
        time.sleep(0.15)

    classification = pd.concat(frames, ignore_index=True)
    classification.to_csv(SW_CLASSIFICATION_PATH, index=False)
    print(f"Saved classification -> {SW_CLASSIFICATION_PATH}")
    return classification


def pull_full_membership(classification):
    """Pull membership for all L3 codes."""
    if SW_MEMBERSHIP_PATH.exists():
        print(f"Loading cached membership from {SW_MEMBERSHIP_PATH}")
        return pd.read_csv(
            SW_MEMBERSHIP_PATH,
            dtype={"ts_code": str, "in_date": str, "out_date": str}
        )

    l3_codes = classification.loc[
        classification["level"] == "L3", "index_code"
    ].tolist()
    print(f"Pulling membership for {len(l3_codes)} L3 codes...")
    print(f"  (estimated ~70-90s at basic tier rate)")

    frames = []
    t0 = time.time()
    for i, l3_code in enumerate(l3_codes, 1):
        df = _retry_on_network_error(
            lambda code=l3_code: pro.index_member_all(l3_code=code)
        )
        if df is not None and len(df) > 0:
            frames.append(df)
        if i % 50 == 0 or i == len(l3_codes):
            so_far = sum(len(f) for f in frames)
            secs = time.time() - t0
            print(f"  [{i}/{len(l3_codes)}] rows accumulated: {so_far:,}, "
                  f"elapsed: {secs:.1f}s")
        time.sleep(0.12)  # ~500/min headroom

    membership = pd.concat(frames, ignore_index=True)
    membership.to_csv(SW_MEMBERSHIP_PATH, index=False)
    print(f"\nSaved {len(membership):,} membership rows -> {SW_MEMBERSHIP_PATH}")

    # Sanity stats
    print(f"\nSanity stats:")
    print(f"  unique ts_codes:    {membership['ts_code'].nunique():,}")
    print(f"  unique L1 sectors:  {membership['l1_name'].nunique()}")
    print(f"  unique L2 sectors:  {membership['l2_name'].nunique()}")
    print(f"  unique L3 sectors:  {membership['l3_name'].nunique()}")
    out_nonnull = membership["out_date"].notna().sum()
    print(f"  rows with non-null out_date: {out_nonnull:,} of {len(membership):,} "
          f"({100*out_nonnull/len(membership):.1f}%)")

    return membership


def smoke_one_l3(classification):
    """Pull membership for one L3 code as a schema check."""
    l3 = classification[classification["level"] == "L3"]
    sample = l3.iloc[10]  # arbitrary mid-list pick
    sample_code = sample["index_code"]
    sample_name = sample.get("industry_name", "<no name>")

    print(f"\nSmoke pull: index_member_all('{sample_code}') -> '{sample_name}'")
    df = _retry_on_network_error(lambda: pro.index_member_all(l3_code=sample_code))
    print(f"  Returned {len(df)} membership rows")
    print(f"  Columns: {list(df.columns)}")
    print(f"  First 3 rows:")
    print(df.head(3).to_string())
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["smoke", "full"])
    args = parser.parse_args()

    classification = pull_classification()
    print(f"\nLevel counts:")
    print(classification["level"].value_counts())

    if args.mode == "smoke":
        smoke_one_l3(classification)
        print("\nSmoke done. If schema looks right, run with `full`.")
        return

    membership = pull_full_membership(classification)
    print(f"\nStage 4 complete: {len(membership):,} membership rows cached.")


if __name__ == "__main__":
    main()