"""
rhi_algorithm.py — Retail Hotspot Identification.

Algorithm (per spec §5):
  1. Restrict to tradable stocks for the smoothing step.
  2. 100×100 grid over [0,1]² in (cap_rank, rdi_rank).
  3. Nadaraya-Watson kernel regression: ρ(grid) = Σ w_i × bs_i / Σ w_i,
     w_i = exp(-||(cap_i, rdi_i) - grid|| ² / 2h²).
  4. Interpolate ρ to every stock via RegularGridInterpolator.
  5. Threshold τ at the percentile where ~target_size tradable stocks
     have rho_at_stock > τ.
  6. Connected-component analysis (scipy.ndimage.label) on the grid mask
     ρ > τ. Choose the component with the highest mean ρ.
  7. Stock is in the universe iff its (cap_rank, rdi_rank) grid cell is
     in the chosen component AND it is tradable.

Self-checks (run via `python rhi_algorithm.py`):
  - Synthetic recovery: 4000 stocks uniform in [0,1]², BS hotspot at
    (0.7, 0.8); recovered centroid distance < 0.10, BS ratio in/out > 3×,
    universe size within 20% of target. Per spec §5.4.
  - FWL precision: residualise a small panel with known beta via
    factor_utils.residualise_factor_per_date (after float64 upcast) and
    compare to statsmodels OLS. Max residual diff must be < 1e-9. Per
    May-7 handover hard rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import pandas as pd
import scipy.ndimage
from scipy.interpolate import RegularGridInterpolator

import config


@dataclass
class HotspotResult:
    df_with_hotspot: pd.DataFrame  # input + rho_at_stock + in_hotspot
    rho_grid: np.ndarray            # shape (grid_n, grid_n)
    final_mask: np.ndarray          # bool, shape (grid_n, grid_n)
    tau: float                      # threshold used
    n_components: int
    centroid: tuple[float, float]   # (cap_rank, rdi_rank) of universe members
    n_in_hotspot: int


def identify_hotspot_universe(
    df_t: pd.DataFrame,
    bandwidth: float = config.RHI_DEFAULT_BANDWIDTH,
    target_size: int = config.RHI_TARGET_SIZE,
    grid_n: int = config.RHI_GRID_N,
) -> HotspotResult:
    """
    df_t: must have columns ts_code, cap_rank, rdi_rank, bs_score, tradable.
    Stocks where rdi_rank or bs_score is NaN are dropped from the smoothing
    set but kept for the final stock-level membership lookup (they will get
    rho_at_stock = 0 effectively).

    Returns a HotspotResult.
    """
    required = {"ts_code", "cap_rank", "rdi_rank", "bs_score", "tradable"}
    missing = required - set(df_t.columns)
    if missing:
        raise ValueError(f"identify_hotspot_universe: missing cols {missing}")

    df_t = df_t.copy()

    # Smoothing set: tradable AND has all of (cap_rank, rdi_rank, bs_score).
    smooth_mask = (
        df_t["tradable"].astype(bool)
        & df_t["cap_rank"].notna()
        & df_t["rdi_rank"].notna()
        & df_t["bs_score"].notna()
    )
    smooth = df_t[smooth_mask]
    if len(smooth) < 50:
        raise RuntimeError(
            f"identify_hotspot_universe: only {len(smooth)} tradable stocks "
            f"with full RDI/BS coverage; cannot smooth."
        )

    cap = smooth["cap_rank"].values.astype(np.float64)
    rdi = smooth["rdi_rank"].values.astype(np.float64)
    bs = smooth["bs_score"].values.astype(np.float64)

    gx = np.linspace(0.0, 1.0, grid_n)  # cap axis
    gy = np.linspace(0.0, 1.0, grid_n)  # rdi axis
    GX, GY = np.meshgrid(gx, gy, indexing="xy")  # shapes (grid_n, grid_n)

    # Vectorized NW kernel regression.
    # For each grid point, compute weighted mean of bs.
    # Memory: (grid_n^2, n_stocks) intermediate. For 10000 grid pts × 5000
    # stocks × 8 bytes ≈ 400MB. Chunk over grid rows to keep peak low.
    h = float(bandwidth)
    inv_2h2 = 1.0 / (2.0 * h * h)
    rho = np.zeros((grid_n, grid_n), dtype=np.float64)

    # Process one grid row at a time
    chunk_size = 10
    for start in range(0, grid_n, chunk_size):
        end = min(start + chunk_size, grid_n)
        gy_chunk = gy[start:end]                       # (chunk,)
        # dx: shape (chunk, grid_n, n_stocks)
        dx = gx[None, :, None] - cap[None, None, :]    # (1, grid_n, n)
        dy = gy_chunk[:, None, None] - rdi[None, None, :]  # (chunk, 1, n)
        d2 = dx * dx + dy * dy                         # (chunk, grid_n, n)
        w = np.exp(-d2 * inv_2h2)
        sw = w.sum(axis=2)
        wb = (w * bs[None, None, :]).sum(axis=2)
        with np.errstate(invalid="ignore", divide="ignore"):
            rho[start:end, :] = np.where(sw > 1e-10, wb / sw, 0.0)

    # Interpolate rho to every stock (incl. non-tradable for diagnostics).
    interp = RegularGridInterpolator(
        (gy, gx), rho, bounds_error=False, fill_value=0.0,
    )
    rho_at_stock = np.full(len(df_t), np.nan, dtype=np.float64)
    has_coord = df_t["cap_rank"].notna() & df_t["rdi_rank"].notna()
    pts = np.column_stack([
        df_t.loc[has_coord, "rdi_rank"].astype(np.float64).values,  # y axis
        df_t.loc[has_coord, "cap_rank"].astype(np.float64).values,  # x axis
    ])
    rho_at_stock[has_coord.values] = interp(pts)
    df_t["rho_at_stock"] = rho_at_stock

    # Threshold tau so ~target_size tradable stocks lie above it.
    tradable_with_rho = df_t.loc[
        df_t["tradable"].astype(bool) & df_t["rho_at_stock"].notna(),
        "rho_at_stock",
    ]
    if len(tradable_with_rho) == 0:
        raise RuntimeError(
            "identify_hotspot_universe: no tradable stocks with rho_at_stock"
        )
    target = min(target_size, len(tradable_with_rho))
    pct = 100.0 * (1.0 - target / len(tradable_with_rho))
    tau = float(np.percentile(tradable_with_rho.values, pct))

    # Connected-component analysis on the grid mask.
    mask = rho > tau
    labeled, n_components = scipy.ndimage.label(mask)
    if n_components == 0:
        raise RuntimeError("identify_hotspot_universe: no components above tau")

    component_means = np.array([
        rho[labeled == k].mean() for k in range(1, n_components + 1)
    ])
    best_idx = int(np.argmax(component_means)) + 1
    final_mask = (labeled == best_idx)

    # Stock-level: in_hotspot iff its (cap_rank, rdi_rank) cell is in
    # final_mask AND tradable.
    xi = np.clip(
        (df_t["cap_rank"].fillna(-1).values * (grid_n - 1)).astype(int),
        -1, grid_n - 1,
    )
    yi = np.clip(
        (df_t["rdi_rank"].fillna(-1).values * (grid_n - 1)).astype(int),
        -1, grid_n - 1,
    )
    cell_in_mask = np.full(len(df_t), False)
    valid = (xi >= 0) & (yi >= 0)
    cell_in_mask[valid] = final_mask[yi[valid], xi[valid]]
    df_t["in_hotspot"] = cell_in_mask & df_t["tradable"].astype(bool)

    in_uni = df_t[df_t["in_hotspot"]]
    if len(in_uni) > 0:
        centroid = (
            float(in_uni["cap_rank"].mean()),
            float(in_uni["rdi_rank"].mean()),
        )
    else:
        centroid = (float("nan"), float("nan"))

    return HotspotResult(
        df_with_hotspot=df_t,
        rho_grid=rho,
        final_mask=final_mask,
        tau=tau,
        n_components=n_components,
        centroid=centroid,
        n_in_hotspot=int(df_t["in_hotspot"].sum()),
    )


# ═══════════════════════════════════════════════════════════════════════
# Self-checks
# ═══════════════════════════════════════════════════════════════════════

def synthetic_recovery_test(
    bandwidth: float = config.RHI_DEFAULT_BANDWIDTH,
    n_stocks: int = 4000,
    truth_centroid: tuple[float, float] = (0.7, 0.8),
    seed: int = 42,
) -> dict:
    """
    Generate synthetic stocks with a known BS hotspot, run RHI, verify:
      - recovered centroid within 0.10 of truth
      - BS ratio in/out > 3
      - universe size within 20% of target_size
    """
    rng = np.random.default_rng(seed)
    cap = rng.uniform(0, 1, n_stocks)
    rdi = rng.uniform(0, 1, n_stocks)

    # Truth BS = unit-amplitude Gaussian at centroid, σ=0.15 (matches default
    # bandwidth so the recovered region has the right scale). Background is
    # noise around 0; we do NOT add a uniform baseline because the spec asks
    # for in/out BS ratio > 3 and a 0.2 baseline mathematically caps the
    # ratio below 3 once the hotspot disk covers ~12.5% of the plane.
    cx, cy = truth_centroid
    d2 = (cap - cx) ** 2 + (rdi - cy) ** 2
    bs_true = np.exp(-d2 / (2 * 0.15 ** 2))
    bs_obs = bs_true + rng.normal(0, 0.03, n_stocks)
    bs_obs = np.clip(bs_obs, 0, 1)

    df = pd.DataFrame({
        "ts_code": [f"SYN{i:05d}" for i in range(n_stocks)],
        "cap_rank": cap,
        "rdi_rank": rdi,
        "bs_score": bs_obs,
        "tradable": True,
    })

    res = identify_hotspot_universe(df, bandwidth=bandwidth, target_size=500)

    in_mask = res.df_with_hotspot["in_hotspot"]
    n_in = int(in_mask.sum())
    bs_in = res.df_with_hotspot.loc[in_mask, "bs_score"].mean()
    bs_out = res.df_with_hotspot.loc[~in_mask, "bs_score"].mean()
    ratio = bs_in / bs_out if bs_out > 0 else float("inf")

    centroid = res.centroid
    centroid_dist = float(np.hypot(centroid[0] - cx, centroid[1] - cy))
    size_ok = abs(n_in - 500) / 500 < 0.20

    pass_centroid = centroid_dist < 0.10
    pass_ratio = ratio > 3.0
    pass_size = size_ok

    return {
        "centroid_recovered": centroid,
        "centroid_truth": (cx, cy),
        "centroid_dist": centroid_dist,
        "bs_in": float(bs_in),
        "bs_out": float(bs_out),
        "bs_ratio": float(ratio),
        "n_in": n_in,
        "target": 500,
        "n_components_found": res.n_components,
        "tau": res.tau,
        "passed": bool(pass_centroid and pass_ratio and pass_size),
        "pass_centroid": bool(pass_centroid),
        "pass_ratio": bool(pass_ratio),
        "pass_size": bool(pass_size),
    }


def fwl_precision_test() -> dict:
    """
    Synthesize a small panel with known beta. Residualise via
    factor_utils.residualise_factor_per_date (which casts inputs to float64
    via .astype(float)). Compare residuals to statsmodels OLS. Max abs diff
    must be < 1e-9. Per May-7 handover.
    """
    import statsmodels.api as sm
    from factor_utils import residualise_factor_per_date

    rng = np.random.default_rng(123)
    n_dates = 5
    n_stocks_per_date = 800
    rows = []
    for d in range(n_dates):
        log_mcap = rng.uniform(0, 3, n_stocks_per_date)
        beta = rng.uniform(-0.5, 1.5, n_stocks_per_date)
        sector = rng.choice(["S1", "S2", "S3", "S4", "S5"], n_stocks_per_date)
        true_betas = {"factor": 0.0, "log_mcap": 1.3, "beta": -0.7}
        sector_offset = {
            "S1": 0.0, "S2": 0.4, "S3": -0.3, "S4": 0.7, "S5": -0.5,
        }
        sec_off = np.array([sector_offset[s] for s in sector])
        factor = (
            true_betas["log_mcap"] * log_mcap
            + true_betas["beta"] * beta
            + sec_off
            + rng.normal(0, 0.5, n_stocks_per_date)
        )
        # Cast to float32 to mimic the production-data dtype hazard.
        factor_f32 = factor.astype(np.float32)
        log_mcap_f32 = log_mcap.astype(np.float32)
        beta_f32 = beta.astype(np.float32)

        df_d = pd.DataFrame({
            "rebalance_date": f"2024-01-{d+1:02d}",
            "ts_code": [f"T{i:04d}" for i in range(n_stocks_per_date)],
            "factor": factor_f32,
            "log_mcap": log_mcap_f32,
            "beta": beta_f32,
            "sector": sector,
        })
        rows.append(df_d)
    panel = pd.concat(rows, ignore_index=True)

    # Run our residualizer
    out = residualise_factor_per_date(
        panel, "factor", "factor_resid",
        numeric_controls=("log_mcap", "beta"),
        categorical_control="sector",
        date_col="rebalance_date",
    )

    # Compare to statsmodels OLS per date
    max_diff = 0.0
    for d, group in out.groupby("rebalance_date"):
        valid = group.dropna(subset=["factor_resid"])
        y = valid["factor"].astype(np.float64).values
        Xc = valid[["log_mcap", "beta"]].astype(np.float64)
        sec_dummies = pd.get_dummies(valid["sector"], drop_first=True).astype(np.float64)
        X = pd.concat([Xc, sec_dummies], axis=1).values
        X = sm.add_constant(X)
        mod = sm.OLS(y, X).fit()
        ref_resid = mod.resid
        our_resid = valid["factor_resid"].astype(np.float64).values
        diff = np.max(np.abs(our_resid - ref_resid))
        if diff > max_diff:
            max_diff = diff

    return {
        "max_resid_diff": float(max_diff),
        "tolerance": 1e-9,
        "passed": bool(max_diff < 1e-9),
    }


def main():
    print("=== RHI self-checks ===\n")

    print("1. FWL precision test")
    fwl = fwl_precision_test()
    status = "PASS" if fwl["passed"] else "FAIL"
    print(f"   [{status}] max_resid_diff={fwl['max_resid_diff']:.2e}  "
          f"tolerance={fwl['tolerance']:.0e}")

    print("\n2. Synthetic recovery test (h=0.15)")
    syn = synthetic_recovery_test(bandwidth=0.15)
    status = "PASS" if syn["passed"] else "FAIL"
    print(f"   [{status}] truth={syn['centroid_truth']}  "
          f"recovered={tuple(round(c, 3) for c in syn['centroid_recovered'])}  "
          f"dist={syn['centroid_dist']:.3f}")
    print(f"   bs_in={syn['bs_in']:.3f}  bs_out={syn['bs_out']:.3f}  "
          f"ratio={syn['bs_ratio']:.2f}×")
    print(f"   n_in={syn['n_in']}/{syn['target']}  "
          f"n_components={syn['n_components_found']}  tau={syn['tau']:.4f}")
    print(f"   pass_centroid={syn['pass_centroid']}  "
          f"pass_ratio={syn['pass_ratio']}  pass_size={syn['pass_size']}")

    print("\n3. Bandwidth sensitivity on synthetic data")
    for h in (0.10, 0.15, 0.25):
        s = synthetic_recovery_test(bandwidth=h)
        print(f"   h={h}: dist={s['centroid_dist']:.3f}  "
              f"ratio={s['bs_ratio']:.2f}×  n_in={s['n_in']}")

    if not (fwl["passed"] and syn["passed"]):
        print("\n*** SELF-CHECK FAILED ***")
        raise SystemExit(1)
    print("\n*** ALL SELF-CHECKS PASSED ***")


if __name__ == "__main__":
    main()
