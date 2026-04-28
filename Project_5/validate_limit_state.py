"""
validate_limit_state.py — Real-world validation for limit_state.

Run this once in your local environment after saving project1_utils.py.
It picks a 50-stock sample from the bottom-1000 universe on the stimulus
rebalance date (2024-09-18, the rebalance immediately before the 2024-09-24
PBoC stimulus rally), pulls daily prices for the rebalance window
(2024-09-13 → 2024-10-15), applies limit_state to every (stock, day),
and cross-checks the result against Tushare's pct_chg field.

Cross-check rule:
    If limit_state == "limit_up",   expect pct_chg ≈ +pct (10/20)
    If limit_state == "limit_down", expect pct_chg ≈ −pct (10/20)
    If limit_state == "normal",     expect |pct_chg| < pct − tol

Any disagreement gets printed with full context for inspection.

Sample size of 50 keeps the run under ~30 seconds at Tushare's basic rate.
Run from Project_5/.
"""

import os
import sys
import numpy as np
import pandas as pd

# Project-root relative import. Adjust if project1_utils.py lives elsewhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import limit_state, _classify_board, _LIMIT_PCT
from tushare_client import pro


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

REBALANCE_DATE = "2024-09-18"
WINDOW_START   = "20240913"   # one trading day before R
WINDOW_END     = "20241015"   # R+1
SAMPLE_SIZE    = 50           # stocks to sample from the bottom-1000 universe
RNG_SEED       = 42

UNIVERSE_PATH  = "data/universe_membership.csv"


# ---------------------------------------------------------------------------
# Step 1. Load the universe and sample 50 stocks
# ---------------------------------------------------------------------------

universe = pd.read_csv(UNIVERSE_PATH)
in_univ_R = universe[
    (universe["rebalance_date"] == REBALANCE_DATE) & universe["in_universe"]
]
print(f"Universe on {REBALANCE_DATE}: {len(in_univ_R)} stocks")
assert len(in_univ_R) == 1000, "Expected 1000 stocks in universe per Stage 3"

sample = in_univ_R.sample(n=SAMPLE_SIZE, random_state=RNG_SEED)
sample_codes = sample["ts_code"].tolist()


# ---------------------------------------------------------------------------
# Step 2. Pull names from stock_basic (present-day; consistent with Stage 1)
# ---------------------------------------------------------------------------

basic = pro.stock_basic(list_status="L", fields="ts_code,name")
name_map = dict(zip(basic["ts_code"], basic["name"]))

missing_names = [c for c in sample_codes if c not in name_map]
if missing_names:
    print(f"WARNING: {len(missing_names)} sample stocks have no current name "
          f"(likely delisted): {missing_names[:5]}")


# ---------------------------------------------------------------------------
# Step 3. Pull daily prices for the sample, window [WINDOW_START, WINDOW_END]
# ---------------------------------------------------------------------------
# Cross-sectional per-day pulls would be more architecturally consistent,
# but for 50 stocks × ~22 trading days a per-stock pull is fine and avoids
# hitting other rebalance dates' panels.

frames = []
for ts_code in sample_codes:
    df = pro.daily(ts_code=ts_code, start_date=WINDOW_START, end_date=WINDOW_END)
    if df is not None and len(df) > 0:
        frames.append(df)

prices = pd.concat(frames, ignore_index=True)
prices = prices.sort_values(["ts_code", "trade_date"])
print(f"Pulled {len(prices)} (stock, day) rows across {prices['ts_code'].nunique()} stocks")


# ---------------------------------------------------------------------------
# Step 4. Compute prev_close per stock and apply limit_state
# ---------------------------------------------------------------------------

prices["prev_close"] = prices.groupby("ts_code")["close"].shift(1)

# Drop the first row per stock (no prev_close to compare against)
prices = prices.dropna(subset=["prev_close"]).reset_index(drop=True)

prices["name"] = prices["ts_code"].map(name_map).fillna("")
prices["board"] = prices.apply(
    lambda r: _classify_board(r["ts_code"], r["name"]), axis=1
)
prices["limit_pct"] = prices["board"].map(_LIMIT_PCT)
prices["state"] = prices.apply(
    lambda r: limit_state(r["close"], r["prev_close"], r["ts_code"], r["name"]),
    axis=1
)


# ---------------------------------------------------------------------------
# Step 5. Cross-check against Tushare pct_chg
# ---------------------------------------------------------------------------
# The exchange's published limit is round_half_up(prev*(1±pct), 2). Because
# 2-decimal rounding shifts the limit by up to ±0.005 yuan, the actual
# pct_chg at the limit can fall short of (or overshoot) the nominal
# percentage by up to 0.5/prev_close percentage points. A stock at prev=2
# can hit limit_up with pct_chg as low as 9.75% or as high as 10.25%; a
# stock at prev=20 stays inside ±0.025pp of nominal. Using a fixed 0.05pp
# tolerance produces false alarms on cheap stocks. Make it price-aware.

prices["limit_pp"] = prices["limit_pct"] * 100
prices["tol_pp"] = 0.5 / prices["prev_close"] + 0.05  # 0.05pp epsilon for other noise

prices["expected_state"] = "normal"
prices.loc[prices["pct_chg"] >=  prices["limit_pp"] - prices["tol_pp"], "expected_state"] = "limit_up"
prices.loc[prices["pct_chg"] <= -prices["limit_pp"] + prices["tol_pp"], "expected_state"] = "limit_down"

# Disagreements between our utility and the pct_chg-based check
disagreements = prices[prices["state"] != prices["expected_state"]]


# ---------------------------------------------------------------------------
# Step 6. Report
# ---------------------------------------------------------------------------

state_counts = prices["state"].value_counts()
print(f"\nlimit_state counts across {len(prices)} (stock, day) observations:")
print(state_counts.to_string())

print(f"\nDisagreements with pct_chg cross-check: {len(disagreements)}")
if len(disagreements) == 0:
    print("PASS — limit_state is consistent with Tushare pct_chg on every observation.")
else:
    print("FAIL — inspect the rows below:")
    print(disagreements[
        ["trade_date", "ts_code", "name", "board", "close", "prev_close",
         "pct_chg", "limit_pp", "state", "expected_state"]
    ].to_string(index=False))


# ---------------------------------------------------------------------------
# Step 7. Show a sample of detected limit_up days for eyeball verification
# ---------------------------------------------------------------------------

up_sample = prices[prices["state"] == "limit_up"].head(10)
print(f"\nSample limit_up detections (showing up to 10):")
print(up_sample[
    ["trade_date", "ts_code", "name", "board", "close", "prev_close", "pct_chg", "state"]
].to_string(index=False))