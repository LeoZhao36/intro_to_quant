"""
Sanity-check consolidation from Project 1 + Project 4 notebooks into
utils.py and hypothesis_testing.py.

Run from the repo root with the .venv active:
    python test_consolidation.py

Each block prints OK on pass; any failure raises AssertionError and aborts.
Functions that require baostock network access (get_stock_data, load_or_fetch,
pull_basket) are imported but NOT exercised here.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from scipy import stats

import utils
import hypothesis_testing as ht


# ─── utils.py ──────────────────────────────────────────────

def test_code_conversion():
    assert utils.to_baostock_code("600000") == "sh.600000"
    assert utils.to_baostock_code("000001") == "sz.000001"
    assert utils.to_baostock_code("300750") == "sz.300750"
    assert utils.to_baostock_code("688256") == "sh.688256"
    assert utils.to_baostock_code("830809") == "bj.830809"
    assert utils.to_baostock_code(1) == "sz.000001"
    print("to_baostock_code: OK")


def test_returns_and_annualization():
    prices = pd.Series([100.0, 102.0, 101.0, 103.0])
    s = utils.compute_simple_returns(prices)
    assert np.isnan(s.iloc[0])
    assert abs(s.iloc[1] - 0.02) < 1e-12
    assert abs(s.iloc[2] - (-1.0 / 102.0)) < 1e-12

    lg = utils.compute_log_returns(prices)
    assert abs(lg.iloc[1] - np.log(1.02)) < 1e-12

    ann = utils.annualize_volatility(0.01)
    assert abs(ann - 0.01 * np.sqrt(242)) < 1e-12
    assert abs(utils.annualize_volatility(0.01, 252) - 0.01 * np.sqrt(252)) < 1e-12
    print("returns + annualization: OK")


def _toy_basket(seed=0, n_days=260):
    """Tiny three-stock basket for testing matrix/filter helpers."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n_days)
    out = {}
    for code in ["sh.600001", "sz.000001", "sz.300001"]:
        returns = rng.standard_normal(n_days) * 0.01
        prices = 10.0 * np.cumprod(1 + returns)
        out[code] = pd.DataFrame({"close": prices}, index=dates)
    return out, dates


def test_filter_full_history():
    basket, dates = _toy_basket()
    # Truncate one stock to a late start
    late = basket["sz.300001"]
    basket["sz.300001"] = late.iloc[100:]
    kept, dropped = utils.filter_full_history(basket, min_start=dates[5])
    assert "sz.300001" in dropped
    assert "sh.600001" in kept
    assert len(kept) == 2
    print("filter_full_history: OK")


def test_build_returns_matrix():
    basket, _ = _toy_basket()
    rets = utils.build_returns_matrix(basket)
    assert rets.shape == (260, 3)
    assert set(rets.columns) == set(basket)
    # First row should be all NaN
    assert rets.iloc[0].isna().all()
    # Subsequent rows should be finite
    assert rets.iloc[1:].notna().all().all()
    print("build_returns_matrix: OK")


def test_describe_basket():
    rng = np.random.default_rng(7)
    r = pd.Series(rng.standard_normal(500) * 0.01,
                  index=pd.bdate_range("2023-01-01", periods=500))
    s = utils.describe_basket(r, "toy", verbose=False)
    assert set(s) >= {"n", "mean", "std", "ann_std", "skew", "kurt", "min", "max"}
    assert s["n"] == 500
    assert abs(s["ann_std"] - s["std"] * np.sqrt(242)) < 1e-12
    print("describe_basket: OK")


def test_count_limit_hits():
    # Synthetic: two stocks, one 10% day, one 20% day, one normal
    idx = pd.bdate_range("2023-01-01", periods=5)
    returns = pd.DataFrame(
        {
            "sh.600001": [0.0, 0.10, -0.01, 0.02, 0.03],
            "sz.300001": [0.0, 0.01, 0.20, -0.02, 0.01],
        },
        index=idx,
    )
    counts = utils.count_limit_hits(returns, "toy", verbose=False)
    assert counts["main_board"] == 1, counts
    assert counts["wide_band"] == 1, counts
    assert counts["stock_days"] == 10
    print("count_limit_hits: OK")


# ─── hypothesis_testing.py ─────────────────────────────────

def test_p_value_two_tailed():
    null = np.concatenate([np.linspace(-3, -1, 500), np.linspace(1, 3, 500)])
    # observed = 0 → no null is "more extreme" than 0, so p = 1.0
    assert abs(ht.p_value_two_tailed(null, 0.0) - 1.0) < 1e-12
    # observed = 4 → no null is as extreme → p = 0
    assert ht.p_value_two_tailed(null, 4.0) == 0.0
    print("p_value_two_tailed: OK")


def test_permutation_correlation_reproducible():
    rng = np.random.default_rng(10)
    x = rng.standard_normal(200)
    y = x + 0.3 * rng.standard_normal(200)
    null_a, p_a = ht.permutation_correlation(x, y, n_iter=1000, seed=42)
    null_b, p_b = ht.permutation_correlation(x, y, n_iter=1000, seed=42)
    assert p_a == p_b
    assert np.array_equal(null_a, null_b)
    assert p_a < 0.01
    print("permutation_correlation (reproducible, significant): OK")


def test_permutation_correlation_null():
    rng = np.random.default_rng(11)
    x = rng.standard_normal(200)
    y = rng.standard_normal(200)  # independent
    _, p = ht.permutation_correlation(x, y, n_iter=1000, seed=123)
    assert p > 0.05, f"expected p > 0.05 for independent pair, got {p}"
    print("permutation_correlation (null): OK")


def test_permutation_mean_diff():
    rng = np.random.default_rng(12)
    a = rng.standard_normal(150)
    b = rng.standard_normal(150) + 0.6  # real shift
    _, p_sig = ht.permutation_mean_diff(a, b, n_iter=1000, seed=7)
    assert p_sig < 0.01, f"expected p < 0.01, got {p_sig}"

    c = rng.standard_normal(150)
    _, p_null = ht.permutation_mean_diff(a, c, n_iter=1000, seed=7)
    assert p_null > 0.05
    print("permutation_mean_diff: OK")


def test_t_test_wrappers():
    rng = np.random.default_rng(13)
    a = rng.standard_normal(100)
    b = rng.standard_normal(100) + 0.5

    two = ht.t_test_two_sample(a, b)
    ref_two = stats.ttest_ind(a, b, equal_var=False)
    assert abs(two["t"] - ref_two.statistic) < 1e-10
    assert abs(two["p"] - ref_two.pvalue) < 1e-10
    assert two["ci_lower"] < (a.mean() - b.mean()) < two["ci_upper"]

    one = ht.t_test_one_sample(a, mu=0)
    ref_one = stats.ttest_1samp(a, 0)
    assert abs(one["t"] - ref_one.statistic) < 1e-10

    pair = ht.t_test_paired(a, b)
    ref_pair = stats.ttest_rel(a, b)
    assert abs(pair["t"] - ref_pair.statistic) < 1e-10
    print("t_test_one_sample / two_sample / paired: OK")


def test_bonferroni_and_acf_band():
    assert abs(ht.bonferroni_threshold(0.05, 20) - 0.0025) < 1e-15
    assert abs(ht.bonferroni_threshold(0.01, 10) - 0.001) < 1e-15

    lo, hi = ht.acf_band(n_obs=1000, n_tests=20, family_alpha=0.05)
    assert abs(lo + hi) < 1e-12
    # z_{1 - 0.00125} / sqrt(1000)
    expected = stats.norm.ppf(1 - 0.00125) / np.sqrt(1000)
    assert abs(hi - expected) < 1e-12
    print("bonferroni_threshold + acf_band: OK")


def test_cost_adjusted_sharpe():
    rng = np.random.default_rng(14)
    r = rng.standard_normal(500) * 0.01 + 0.0005

    free = ht.cost_adjusted_sharpe(r, cost_per_trade=0.0, turnover=5.0)
    assert abs(free["gross_sharpe"] - free["net_sharpe"]) < 1e-12
    assert free["daily_cost"] == 0.0

    costly = ht.cost_adjusted_sharpe(r, cost_per_trade=0.003, turnover=5.0)
    assert costly["gross_sharpe"] > costly["net_sharpe"]
    assert abs(costly["daily_cost"] - 0.003 * 5.0 / 242) < 1e-15
    print("cost_adjusted_sharpe: OK")


def test_bootstrap_ci():
    rng = np.random.default_rng(15)
    data = rng.standard_normal(500)
    b = ht.bootstrap_ci(data, n_boot=2000, seed=1)
    assert set(b) == {"estimate", "ci_lower", "ci_upper", "boot_distribution"}
    assert b["ci_lower"] < b["estimate"] < b["ci_upper"]
    # True mean is 0; CI should cover it
    assert b["ci_lower"] < 0 < b["ci_upper"]
    # Custom statistic: standard deviation
    b_std = ht.bootstrap_ci(data, statistic=np.std, n_boot=1000, seed=2)
    assert 0.8 < b_std["estimate"] < 1.2
    print("bootstrap_ci: OK")


def test_block_bootstrap_ci_wider_on_serial_correlation():
    rng = np.random.default_rng(16)
    eps = rng.standard_normal(600)
    ar1 = np.empty(600)
    ar1[0] = eps[0]
    for i in range(1, 600):
        ar1[i] = 0.5 * ar1[i - 1] + eps[i]
    naive = ht.bootstrap_ci(ar1, n_boot=2000, seed=5)
    block = ht.block_bootstrap_ci(ar1, block_size=20, n_boot=2000, seed=5)
    n_w = naive["ci_upper"] - naive["ci_lower"]
    b_w = block["ci_upper"] - block["ci_lower"]
    assert b_w > n_w, (
        f"block bootstrap should be wider than naive on AR(1); got "
        f"naive={n_w:.4f}, block={b_w:.4f}"
    )
    print(f"block_bootstrap_ci (wider on AR(1): naive={n_w:.4f}, block={b_w:.4f}): OK")


def test_permutation_efficiency():
    """Sanity-check that the vectorized permutation is fast enough."""
    rng = np.random.default_rng(17)
    x = rng.standard_normal(250)
    y = rng.standard_normal(250)
    start = time.perf_counter()
    ht.permutation_correlation(x, y, n_iter=10_000, seed=0)
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"permutation_correlation 10k iters took {elapsed:.2f}s"
    print(f"permutation_correlation 10_000 iters on n=250: {elapsed:.2f}s, OK")


# ─── Network-free imports sanity check ─────────────────────

def test_network_functions_import():
    """Functions that hit baostock must be importable but aren't exercised."""
    for name in ("get_stock_data", "load_or_fetch", "pull_basket"):
        assert hasattr(utils, name), f"utils.{name} missing"
        assert callable(getattr(utils, name))
    print("baostock-backed functions are importable (not exercised): OK")


def main():
    print("=== utils.py ===")
    test_code_conversion()
    test_returns_and_annualization()
    test_filter_full_history()
    test_build_returns_matrix()
    test_describe_basket()
    test_count_limit_hits()
    test_network_functions_import()

    print("\n=== hypothesis_testing.py ===")
    test_p_value_two_tailed()
    test_permutation_correlation_reproducible()
    test_permutation_correlation_null()
    test_permutation_mean_diff()
    test_t_test_wrappers()
    test_bonferroni_and_acf_band()
    test_cost_adjusted_sharpe()
    test_bootstrap_ci()
    test_block_bootstrap_ci_wider_on_serial_correlation()
    test_permutation_efficiency()

    print("\nAll consolidation sanity checks passed.")


if __name__ == "__main__":
    main()
