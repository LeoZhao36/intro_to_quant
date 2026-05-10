"""
phase3_plots.py — Phase 3 visualization.

  graphs/phase3_decomposition_cumulative.png
    Cumulative net returns over γ for: universe_EW, profitable_EW,
    loss_maker_EW, top10_ep, top10_roa (canonical).

  graphs/phase3_quintile_returns.png
    Cumulative returns by quintile (Q1-Q5) for each (factor, universe).
"""

from __future__ import annotations

import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import data_loaders as dl
import fr3_config as cfg


def _try_chinese_font() -> None:
    """Best-effort Chinese font setup; harmless if no CJK font is installed."""
    candidates = [
        "Microsoft YaHei", "SimHei", "PingFang SC",
        "Noto Sans CJK SC", "Source Han Sans SC", "Arial Unicode MS",
    ]
    import matplotlib.font_manager as fm
    avail = {f.name for f in fm.fontManager.ttflist}
    for c in candidates:
        if c in avail:
            plt.rcParams["font.sans-serif"] = [c]
            plt.rcParams["axes.unicode_minus"] = False
            return


def _basket_period_returns_simple(basket: list[str], entry, exit_):
    if not basket:
        return np.nan
    p_entry = dl.load_daily_open_adj(entry)
    p_exit = dl.load_daily_open_adj(exit_)
    if p_entry is None or p_exit is None:
        return np.nan
    common = p_entry.index.intersection(basket).intersection(p_exit.index)
    if len(common) == 0:
        return np.nan
    return float((p_exit.loc[common] / p_entry.loc[common] - 1).mean())


def _churn(prev: set, cur: set) -> float:
    if not prev:
        return 1.0
    return 1 - len(prev & cur) / max(len(cur), 1)


def _build_basket_period_series(panel: pd.DataFrame, universe: str, key: str
                                ) -> pd.Series:
    """Returns Series indexed by signal_date, value = net return."""
    sub = panel[panel["universe"] == universe]
    rows = []
    prev: set = set()
    for s, g in sub.groupby("signal_date"):
        if g["entry_date"].isna().all():
            continue
        entry = g["entry_date"].iloc[0]
        exit_ = g["exit_date"].iloc[0]
        if pd.isna(entry) or pd.isna(exit_):
            continue
        if key == "universe":
            basket = list(g["ts_code"])
        elif key == "profitable":
            basket = list(g.loc[g["ep"].notna(), "ts_code"])
        elif key == "loss":
            basket = list(g.loc[g["ep"].isna(), "ts_code"])
        else:
            raise ValueError(key)
        gross = _basket_period_returns_simple(basket, entry, exit_)
        if pd.isna(gross):
            continue
        cur = set(basket)
        cost = 2 * _churn(prev, cur) * cfg.COST_RT_HEADLINE
        prev = cur
        rows.append((s, gross - cost))
    return pd.Series(dict(rows)).sort_index()


def plot_decomposition_cumulative() -> None:
    panel = pd.read_parquet(cfg.FACTOR_PANEL_PATH)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    panel["entry_date"] = pd.to_datetime(panel["entry_date"])
    panel["exit_date"] = pd.to_datetime(panel["exit_date"])

    print("  building decomposition series (canonical)...")
    uni = _build_basket_period_series(panel, "canonical", "universe")
    prof = _build_basket_period_series(panel, "canonical", "profitable")
    loss = _build_basket_period_series(panel, "canonical", "loss")

    pr = pd.read_csv(cfg.PHASE2_PERIOD_RETURNS_PATH)
    pr["signal_date"] = pd.to_datetime(pr["signal_date"])
    pr_ep = pr[(pr["factor"] == "ep") & (pr["universe"] == "canonical")
               & (pr["top_n"] == cfg.HEADLINE_TOP_N)
               & (pr["cost_regime"] == "headline")].set_index("signal_date")["basket_return_net"]
    pr_roa = pr[(pr["factor"] == "roa") & (pr["universe"] == "canonical")
                & (pr["top_n"] == cfg.HEADLINE_TOP_N)
                & (pr["cost_regime"] == "headline")].set_index("signal_date")["basket_return_net"]

    fig, ax = plt.subplots(figsize=(11, 6))
    for label, series, kw in [
        ("universe_EW",   uni,  {"linewidth": 2.0, "color": "C0"}),
        ("profitable_EW", prof, {"linewidth": 2.0, "color": "C1"}),
        ("loss_maker_EW", loss, {"linewidth": 2.0, "color": "C3", "linestyle": "--"}),
        ("top10_ep",      pr_ep,  {"linewidth": 1.6, "color": "C2"}),
        ("top10_roa",     pr_roa, {"linewidth": 1.6, "color": "C4"}),
    ]:
        cum = (1 + series).cumprod()
        ax.plot(cum.index, cum.values, label=label, **kw)
    ax.set_title("Phase 3: cumulative net returns on canonical universe (γ regime)")
    ax.set_xlabel("signal_date")
    ax.set_ylabel("cumulative return × (1 = start)")
    ax.axhline(1.0, linestyle=":", color="gray", alpha=0.5)
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = cfg.GRAPHS_DIR / "phase3_decomposition_cumulative.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"  saved: {out}")


def plot_quintile_returns() -> None:
    if not cfg.PHASE3_QUINTILE_PATH.exists():
        print("  quintile summary missing; skipping plot")
        return
    panel = pd.read_parquet(cfg.FACTOR_PANEL_PATH)
    panel["signal_date"] = pd.to_datetime(panel["signal_date"])
    panel["entry_date"] = pd.to_datetime(panel["entry_date"])
    panel["exit_date"] = pd.to_datetime(panel["exit_date"])

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
    for ax, (factor_name, factor_col) in zip(
        axes.flat,
        [("ep", "z_ep_resid"), ("ep", "z_ep_resid"),
         ("roa", "z_roa_resid"), ("roa", "z_roa_resid")],
    ):
        pass

    cells = [
        ("ep",  "canonical", "z_ep_resid",  axes[0, 0]),
        ("ep",  "csi300",    "z_ep_resid",  axes[0, 1]),
        ("roa", "canonical", "z_roa_resid", axes[1, 0]),
        ("roa", "csi300",    "z_roa_resid", axes[1, 1]),
    ]

    print("  building quintile cumulative series...")
    for fac, uni, col, ax in cells:
        sub = panel[panel["universe"] == uni]
        prev_q: dict[int, set] = {q: set() for q in range(5)}
        ts_by_q: dict[int, list[tuple[pd.Timestamp, float]]] = {q: [] for q in range(5)}
        for s, g in sub.groupby("signal_date"):
            if g["entry_date"].isna().all():
                continue
            entry = g["entry_date"].iloc[0]
            exit_ = g["exit_date"].iloc[0]
            if pd.isna(entry) or pd.isna(exit_):
                continue
            p = g.dropna(subset=[col, "ep"])
            if len(p) < 25:
                continue
            qs = pd.qcut(p[col], 5, labels=False, duplicates="drop")
            for q in range(5):
                members = list(p.loc[qs == q, "ts_code"])
                if not members:
                    continue
                gross = _basket_period_returns_simple(members, entry, exit_)
                if pd.isna(gross):
                    continue
                cur = set(members)
                cost = 2 * _churn(prev_q[q], cur) * cfg.COST_RT_HEADLINE
                prev_q[q] = cur
                ts_by_q[q].append((s, gross - cost))

        for q in range(5):
            if not ts_by_q[q]:
                continue
            ser = pd.Series(dict(ts_by_q[q])).sort_index()
            cum = (1 + ser).cumprod()
            ax.plot(cum.index, cum.values, label=f"Q{q+1}",
                    color=plt.cm.viridis(q / 4))

        ax.set_title(f"{fac.upper()} × {uni}")
        ax.axhline(1.0, linestyle=":", color="gray", alpha=0.5)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="best")

    fig.suptitle("Phase 3: cumulative quintile returns within profitable subset (γ regime)",
                 fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = cfg.GRAPHS_DIR / "phase3_quintile_returns.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"  saved: {out}")


def main() -> None:
    _try_chinese_font()
    print("Building Phase 3 plots...")
    plot_decomposition_cumulative()
    plot_quintile_returns()


if __name__ == "__main__":
    main()
