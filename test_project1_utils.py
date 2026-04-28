"""
test_utils.py — Synthetic unit tests for limit_state.

These tests exercise the function's logic without any network calls.
They cover:
  - Each of the 7 board × ST classes returns the right percentage.
  - Limit-up, limit-down, and normal are correctly distinguished.
  - The board classifier reads code prefix correctly.
  - Float rounding tolerance behaves at the 分 boundary.
  - ValueError is raised on unrecognised codes.

Real-world validation against actual exchange-tape prices is a separate
script (validate_limit_state.py) that the user runs in their environment
where Tushare credentials are configured.
"""

from utils import limit_state, _classify_board, _LIMIT_PCT


def expect(label, condition):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    assert condition, f"Test failed: {label}"


def _try_classify(code):
    """Helper: returns True iff _classify_board raises ValueError on `code`."""
    try:
        _classify_board(code, "")
        return False
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# 1. Board classifier — prefix routing
# ---------------------------------------------------------------------------
print("Board classifier")

expect("60xxxxx.SH normal -> main_normal",
       _classify_board("600519.SH", "贵州茅台") == "main_normal")
expect("00xxxxx.SZ normal -> main_normal",
       _classify_board("000001.SZ", "平安银行") == "main_normal")
expect("60xxxxx.SH ST     -> main_st",
       _classify_board("600519.SH", "ST茅台") == "main_st")
expect("60xxxxx.SH *ST    -> main_st",
       _classify_board("600289.SH", "*ST信通") == "main_st")
expect("30xxxx.SZ normal  -> chinext_normal",
       _classify_board("300750.SZ", "宁德时代") == "chinext_normal")
expect("30xxxx.SZ ST      -> chinext_st",
       _classify_board("300204.SZ", "ST舒泰") == "chinext_st")
expect("688xxx.SH normal  -> star_normal",
       _classify_board("688981.SH", "中芯国际") == "star_normal")
expect("688xxx.SH ST      -> star_st",
       _classify_board("688123.SH", "*ST逸飞") == "star_st")
expect("8xxxxx.BJ         -> bse",
       _classify_board("830799.BJ", "成大生物") == "bse")
expect("Unrecognised code raises ValueError",
       _try_classify("999999.XX"))


# ---------------------------------------------------------------------------
# 2. Limit detection — main board normal (10%)
# ---------------------------------------------------------------------------
print("\n主板 normal (±10%)")

# prev=10.00, up_limit=11.00, down_limit=9.00
expect("close=11.00 -> limit_up",
       limit_state(11.00, 10.00, "600519.SH", "贵州茅台") == "limit_up")
expect("close=9.00  -> limit_down",
       limit_state(9.00, 10.00, "600519.SH", "贵州茅台") == "limit_down")
expect("close=10.50 -> normal",
       limit_state(10.50, 10.00, "600519.SH", "贵州茅台") == "normal")
expect("close=10.99 -> normal (just under limit_up)",
       limit_state(10.99, 10.00, "600519.SH", "贵州茅台") == "normal")
expect("close=11.01 -> normal (above limit_up by 1分)",
       limit_state(11.01, 10.00, "600519.SH", "贵州茅台") == "normal")


# ---------------------------------------------------------------------------
# 3. Limit detection — main board ST (5%)
# ---------------------------------------------------------------------------
print("\n主板 ST (±5%)")

# prev=10.00, up_limit=10.50, down_limit=9.50
expect("ST close=10.50 -> limit_up",
       limit_state(10.50, 10.00, "600289.SH", "*ST信通") == "limit_up")
expect("ST close=9.50  -> limit_down",
       limit_state(9.50, 10.00, "600289.SH", "*ST信通") == "limit_down")
expect("ST close=10.40 -> normal",
       limit_state(10.40, 10.00, "600289.SH", "*ST信通") == "normal")
expect("Same prices, normal name -> NOT limit_up at 10.50",
       limit_state(10.50, 10.00, "600289.SH", "信通电子") == "normal")


# ---------------------------------------------------------------------------
# 4. Limit detection — ChiNext (20%)
# ---------------------------------------------------------------------------
print("\n创业板 (±20%)")

# prev=10.00, up_limit=12.00, down_limit=8.00
expect("ChiNext close=12.00 -> limit_up",
       limit_state(12.00, 10.00, "300750.SZ", "宁德时代") == "limit_up")
expect("ChiNext close=8.00  -> limit_down",
       limit_state(8.00, 10.00, "300750.SZ", "宁德时代") == "limit_down")
expect("ChiNext close=11.00 -> normal (NOT a 主板 limit)",
       limit_state(11.00, 10.00, "300750.SZ", "宁德时代") == "normal")
expect("ChiNext ST same 20% limit",
       limit_state(12.00, 10.00, "300204.SZ", "ST舒泰") == "limit_up")


# ---------------------------------------------------------------------------
# 5. Limit detection — STAR (20%)
# ---------------------------------------------------------------------------
print("\n科创板 (±20%)")

# prev=50.00, up_limit=60.00, down_limit=40.00
expect("STAR close=60.00 -> limit_up",
       limit_state(60.00, 50.00, "688981.SH", "中芯国际") == "limit_up")
expect("STAR close=40.00 -> limit_down",
       limit_state(40.00, 50.00, "688981.SH", "中芯国际") == "limit_down")


# ---------------------------------------------------------------------------
# 6. Rounding edge cases
# ---------------------------------------------------------------------------
print("\nRounding & tolerance edges")

# prev=3.33, main normal: up_limit = round(3.33*1.10, 2) = round(3.663, 2) = 3.66
expect("prev=3.33, close=3.66 -> limit_up (rounds down)",
       limit_state(3.66, 3.33, "600519.SH", "贵州茅台") == "limit_up")
expect("prev=3.33, close=3.67 -> normal",
       limit_state(3.67, 3.33, "600519.SH", "贵州茅台") == "normal")

# Float-representation safety: a value that prints 11.00 but stores as 10.9999...
expect("Float-fuzz close=10.9999999 -> limit_up",
       limit_state(10.9999999, 10.00, "600519.SH", "贵州茅台") == "limit_up")
expect("Float-fuzz close=11.0000001 -> limit_up",
       limit_state(11.0000001, 10.00, "600519.SH", "贵州茅台") == "limit_up")

# prev=2.50, ST main: up_limit = round(2.50*1.05, 2) = round(2.625, 2) = 2.63
# Banker's rounding in Python 3: round(2.625, 2) = 2.62. But float repr of 2.625
# is actually 2.62499...95, so round gives 2.62. The exchange uses 'round half
# up' arithmetic, but in practice 1分-precision prices avoid this case for
# most stocks. We document the corner case; it does not affect the test below.
# Use prev=4.00 to keep the test deterministic: 4.00*1.05 = 4.20.
expect("ST prev=4.00, close=4.20 -> limit_up",
       limit_state(4.20, 4.00, "600289.SH", "*ST信通") == "limit_up")

# Regression test for the banker's-rounding bug found in real-world validation.
# prev=8.45, 8.45*1.10 = 9.295. Python's round(9.295, 2) returns 9.29 (banker's
# rounding combined with float drift). The exchange uses 四舍五入 and gives 9.30.
# A real case: 603196.SH closed at 9.30 on 2024-09-25 with prev_close 8.45.
expect("Half-up rounding: prev=8.45, close=9.30 -> limit_up (was bug)",
       limit_state(9.30, 8.45, "603196.SH", "璞源材料") == "limit_up")
expect("Half-up rounding: prev=8.45, close=9.29 -> normal (below true ceiling)",
       limit_state(9.29, 8.45, "603196.SH", "璞源材料") == "normal")


# ---------------------------------------------------------------------------
# 7. 北交所 (out of universe but supported)
# ---------------------------------------------------------------------------
print("\n北交所 (±30%)")

# prev=10.00, up_limit=13.00, down_limit=7.00
expect("BSE close=13.00 -> limit_up",
       limit_state(13.00, 10.00, "830799.BJ", "成大生物") == "limit_up")
expect("BSE close=7.00  -> limit_down",
       limit_state(7.00, 10.00, "830799.BJ", "成大生物") == "limit_down")


# ---------------------------------------------------------------------------
# 8. Limit table integrity check
# ---------------------------------------------------------------------------
print("\nLimit table integrity")
expected_keys = {
    "main_normal", "main_st",
    "chinext_normal", "chinext_st",
    "star_normal", "star_st",
    "bse",
}
expect("All 7 board classes covered", set(_LIMIT_PCT.keys()) == expected_keys)
expect("Main normal = 10%", _LIMIT_PCT["main_normal"] == 0.10)
expect("Main ST = 5%",      _LIMIT_PCT["main_st"]     == 0.05)
expect("ChiNext = 20%",     _LIMIT_PCT["chinext_normal"] == 0.20)
expect("STAR = 20%",        _LIMIT_PCT["star_normal"]    == 0.20)
expect("BSE = 30%",         _LIMIT_PCT["bse"]            == 0.30)


print("\nAll tests passed.")