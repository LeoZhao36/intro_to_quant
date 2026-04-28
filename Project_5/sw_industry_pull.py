# sw_industry_pull.py — 申万 2021 hierarchy and membership pull
# Smoke mode: pull taxonomy + one L3 sample, print schema, stop.
# Full mode (added after smoke confirms): pull all 346 L3 memberships.

import argparse
import time
from pathlib import Path

import pandas as pd

from tushare_setup import pro

DATA = Path("data")
SW_CLASSIFICATION_PATH = DATA / "sw_classification.csv"
SW_MEMBERSHIP_PATH = DATA / "sw_membership.csv"


def _retry_on_network_error(fn, max_retries=3, base_wait=2):
    """Exponential backoff: 2s, 4s, 8s. Reused pattern from liquidity_panel.py."""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = base_wait * (2 ** attempt)
            print(f"    Network error ({type(e).__name__}: {e}), retry in {wait}s...")
            time.sleep(wait)


def pull_classification():
    """Pull the SW2021 taxonomy: L1 (~31), L2 (~134), L3 (~346)."""
    if SW_CLASSIFICATION_PATH.exists():
        print(f"Loading cached classification from {SW_CLASSIFICATION_PATH}")
        return pd.read_csv(SW_CLASSIFICATION_PATH)

    print("Pulling SW2021 classification from Tushare...")
    frames = []
    for level in ["L1", "L2", "L3"]:
        df = _retry_on_network_error(
            lambda lv=level: pro.index_classify(level=lv, src="SW2021")
        )
        df["level"] = level
        frames.append(df)
        print(f"  {level}: {len(df)} rows, columns: {list(df.columns)}")
        time.sleep(0.1)

    classification = pd.concat(frames, ignore_index=True)
    classification.to_csv(SW_CLASSIFICATION_PATH, index=False)
    print(f"Saved {len(classification)} rows to {SW_CLASSIFICATION_PATH}")
    return classification


def smoke_one_l3(classification):
    """Pull membership for a single L3 to inspect the schema."""
    l3 = classification[classification["level"] == "L3"]
    if l3.empty:
        raise RuntimeError("No L3 rows in classification — check pull")

    # Pick a 三级 with a meaningful number of members (not a tiny edge case)
    sample_l3 = l3.iloc[10]  # arbitrary mid-list pick
    sample_code = sample_l3["index_code"]
    sample_name = sample_l3.get("industry_name", "<no name>")

    print(f"\nSmoke pull: index_member_all(l3_code='{sample_code}') for '{sample_name}'")
    df = _retry_on_network_error(
        lambda: pro.index_member_all(l3_code=sample_code)
    )

    print(f"  Returned {len(df)} rows")
    print(f"  Columns: {list(df.columns)}")
    print(f"  First 3 rows:")
    print(df.head(3).to_string())

    if "in_date" in df.columns:
        print(f"\n  in_date dtype: {df['in_date'].dtype}, sample: {df['in_date'].iloc[0]}")
    if "out_date" in df.columns:
        non_null_out = df["out_date"].dropna()
        print(f"  out_date: {len(non_null_out)} non-null of {len(df)} rows")
        if not non_null_out.empty:
            print(f"  out_date sample (non-null): {non_null_out.iloc[0]}")

    return df

def pull_full_membership(classification):
    """Pull membership for all L3 categories. ~346 calls, ~70-90s wall time."""
    if SW_MEMBERSHIP_PATH.exists():
        print(f"Loading cached membership from {SW_MEMBERSHIP_PATH}")
        return pd.read_csv(SW_MEMBERSHIP_PATH, dtype={"in_date": str, "out_date": str})

    l3_codes = classification.loc[classification["level"] == "L3", "index_code"].tolist()
    print(f"Pulling membership for {len(l3_codes)} L3 categories...")

    frames = []
    for i, l3_code in enumerate(l3_codes, 1):
        df = _retry_on_network_error(
            lambda code=l3_code: pro.index_member_all(l3_code=code)
        )
        if not df.empty:
            frames.append(df)
        if i % 50 == 0 or i == len(l3_codes):
            so_far = sum(len(f) for f in frames)
            print(f"  Progress: {i}/{len(l3_codes)} L3 codes, {so_far} rows accumulated")
        time.sleep(0.12)  # ~500 calls/min rate limit, comfortable headroom

    membership = pd.concat(frames, ignore_index=True)
    membership.to_csv(SW_MEMBERSHIP_PATH, index=False)
    print(f"\nSaved {len(membership)} rows to {SW_MEMBERSHIP_PATH}")

    # Sanity stats. Tells us whether the pull is usable before we build on it.
    print(f"\nSchema sanity:")
    print(f"  Unique ts_codes: {membership['ts_code'].nunique()}")
    print(f"  Unique L1: {membership['l1_name'].nunique()}, "
          f"L2: {membership['l2_name'].nunique()}, "
          f"L3: {membership['l3_name'].nunique()}")
    out_nonnull = membership["out_date"].notna().sum()
    print(f"  Rows with non-null out_date: {out_nonnull} of {len(membership)} "
          f"({out_nonnull / len(membership):.1%})")
    print(f"  is_new value counts:")
    print(membership["is_new"].value_counts().to_string())

    return membership


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["smoke", "full"], help="smoke = inspect schema; full = bulk pull")
    args = parser.parse_args()

    DATA.mkdir(exist_ok=True)
    classification = pull_classification()

    print("\nClassification level counts:")
    print(classification["level"].value_counts())
    print("\nClassification head:")
    print(classification.head().to_string())

    if args.mode == "smoke":
        smoke_one_l3(classification)
        print("\nSmoke test done. If schema looks right, run with `full` to pull all 346 L3 memberships.")
        return

    # full mode
    membership = pull_full_membership(classification)
    print(f"\nFull pull complete. {len(membership)} membership rows cached.")


if __name__ == "__main__":
    main()