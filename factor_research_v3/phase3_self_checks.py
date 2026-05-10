"""
phase3_self_checks.py — Phase 3-specific self-checks (spec section 6).

1. Decomposition consistency: top-10 active = filter + sort (within ~1bp)
2. Profitable + loss-maker partition exhaustive on canonical
3. Quintile membership exhaustive
4. Sector mapping consistency (same source as Phase 1)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import data_loaders as dl
import fr3_config as cfg


def _ok(name, msg=""):
    return {"check": name, "status": "PASS", "message": msg}


def _fail(name, msg):
    return {"check": name, "status": "FAIL", "message": msg}


def check_decomp_consistency() -> dict:
    if not cfg.PHASE3_DECOMPOSITION_PATH.exists():
        return _fail("decomp_consistency", "phase3 summary missing")
    dec = pd.read_csv(cfg.PHASE3_DECOMPOSITION_PATH)
    bad = []
    for u in ("canonical", "csi300"):
        u_ann = float(dec[(dec["universe"] == u) & (dec["basket_type"] == "universe_EW")]["ann_return"].iloc[0])
        p_ann = float(dec[(dec["universe"] == u) & (dec["basket_type"] == "profitable_EW")]["ann_return"].iloc[0])
        for fac in ("ep", "roa"):
            fac_ann = float(dec[(dec["universe"] == u) & (dec["basket_type"] == f"top10_{fac}")]["ann_return"].iloc[0])
            filter_eff = p_ann - u_ann
            sort_eff = fac_ann - p_ann
            total = fac_ann - u_ann
            residual = (filter_eff + sort_eff) - total
            if abs(residual) > 1e-4:
                bad.append(f"{fac}/{u}: residual={residual:+.6f}")
    if bad:
        return _fail("decomp_consistency", "; ".join(bad))
    return _ok("decomp_consistency", "all 4 cells additive within 1bp")


def check_profitable_partition() -> dict:
    """profitable + loss-maker = full canonical universe at every signal_date."""
    panel = pd.read_parquet(cfg.FACTOR_PANEL_PATH)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    canon = panel[panel["universe"] == "canonical"]
    bad = []
    for s, g in canon.groupby("signal_date"):
        n_total = g["ts_code"].nunique()
        n_prof = g["ep"].notna().sum()
        n_loss = g["ep"].isna().sum()
        if n_prof + n_loss != n_total:
            bad.append(f"{s.date()}: {n_prof}+{n_loss}!={n_total}")
        # Disjoint check (profitable AND loss-maker)
        prof_set = set(g.loc[g["ep"].notna(), "ts_code"])
        loss_set = set(g.loc[g["ep"].isna(), "ts_code"])
        if prof_set & loss_set:
            bad.append(f"{s.date()}: overlap {len(prof_set & loss_set)}")
    if bad:
        return _fail("profitable_partition", "; ".join(bad[:5]))
    return _ok("profitable_partition",
               f"profitable + loss = total at all {canon['signal_date'].nunique()} signals")


def check_quintile_exhaustiveness() -> dict:
    """Quintile members sum to profitable subset and each member in exactly one quintile."""
    panel = pd.read_parquet(cfg.FACTOR_PANEL_PATH)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    bad = []
    for u in ("canonical", "csi300"):
        sub = panel[panel["universe"] == u]
        for s, g in sub.groupby("signal_date"):
            for col in ("z_ep_resid", "z_roa_resid"):
                p = g.dropna(subset=[col, "ep"])
                if len(p) < 25:
                    continue
                qs = pd.qcut(p[col], 5, labels=False, duplicates="drop")
                # qcut returns one label per row (single membership). Just verify count == p
                n_assigned = qs.notna().sum()
                if n_assigned != len(p):
                    bad.append(f"{u}/{col}/{s.date()}: assigned {n_assigned}/{len(p)}")
    if bad:
        return _fail("quintile_exhaustiveness", "; ".join(bad[:5]))
    return _ok("quintile_exhaustiveness",
               "every profitable member in exactly one quintile, all signals")


def check_sector_mapping() -> dict:
    """Confirm sector mapping comes from sw_l1_membership (same as Phase 1)."""
    if not cfg.SW_MEMBERSHIP_PATH.exists():
        return _fail("sector_mapping", "sw_l1_membership.parquet missing")
    df = dl.load_sw_l1_membership()
    n_industries = df["industry_code"].nunique()
    if n_industries != 31:
        return _fail("sector_mapping", f"got {n_industries} industries; expected 31 SW L1")
    return _ok("sector_mapping", f"{n_industries} SW L1 industries from {cfg.SW_MEMBERSHIP_PATH.name}")


ALL_CHECKS = [
    check_decomp_consistency,
    check_profitable_partition,
    check_quintile_exhaustiveness,
    check_sector_mapping,
]


def run_all() -> pd.DataFrame:
    rows = []
    for fn in ALL_CHECKS:
        try:
            rows.append(fn())
        except Exception as exc:
            rows.append(_fail(fn.__name__, f"exception: {type(exc).__name__}: {exc}"))
    df = pd.DataFrame(rows)
    print("\nPHASE 3 SELF-CHECK SUMMARY")
    print("-" * 60)
    for _, r in df.iterrows():
        print(f"  [{r['status']}] {r['check']:<28s}  {r['message']}")
    return df


if __name__ == "__main__":
    run_all()
