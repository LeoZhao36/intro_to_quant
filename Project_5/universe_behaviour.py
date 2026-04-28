"""
universe_behaviour.py — membership churn and exit categorization.

Analyzes how the bottom-1000 universe rotates between consecutive monthly
rebalances. By symmetry of N=1000 universe size, exits and entries are
equal in count per transition, so we focus on exits and treat entries as
their mirror.

Three exit categories tracked, all derivable from universe_membership.csv:

  A. cap_graduated   — stock cap grew past the bottom-1000 cutoff.
                       (in_universe=False at R+1 with rank_by_mcap > 1000)

  B. lost_liquidity  — cap stayed in bottom-1000 range but failed the
                       hybrid liquidity floor.
                       (in_universe=False at R+1 with rank_by_mcap <= 1000)

  D. structural      — stock no longer in candidates at R+1: delisted,
                       became ST and got filtered, B-share conversion,
                       or other structural removal.

Reads
-----
data/universe_membership.csv  (Stage 3 output, canonical universe)
data/sw_membership.csv        (Stage 4 sector classification, optional)

Writes
------
data/universe_churn_panel.csv          — per (R, R+1) churn statistics
data/universe_churn_diagnostic.png     — main diagnostic, 2 panels
data/universe_churn_by_sector.png      — sector breakdown (if sector data present)
"""

import os

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# Reuse the project's matplotlib Chinese-character setup if present
try:
    import plot_setup  # noqa: F401
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

DATA_DIR          = "data"
UNIVERSE_PATH     = f"{DATA_DIR}/universe_membership.csv"
SECTOR_PATH       = f"{DATA_DIR}/sw_membership.csv"
RETURN_PANEL_PATH = f"{DATA_DIR}/forward_return_panel.csv"

CHURN_PANEL_PATH  = f"{DATA_DIR}/universe_churn_panel.csv"
CHURN_PLOT_PATH   = f"{DATA_DIR}/universe_churn_diagnostic.png"
SECTOR_PLOT_PATH  = f"{DATA_DIR}/universe_churn_by_sector.png"

# Reference dates for the three regime events surfaced in Option 2
REGIME_EVENTS = [
    ("2024-02-05", "雪球 meltdown",   "red"),
    ("2024-04-12", "新国九条",         "darkgreen"),
    ("2024-09-24", "PBoC stimulus",    "darkorange"),
]

# Universe size by construction
N_UNIVERSE = 1000


# ---------------------------------------------------------------------------
# Pass 1: categorize each exit
# ---------------------------------------------------------------------------

def categorize_exits(universe: pd.DataFrame) -> pd.DataFrame:
    """
    For each consecutive (R, R+1) pair, identify exits and categorize them.

    Returns a DataFrame with one row per exit:
        rebalance_date_R, rebalance_date_Rp1, ts_code,
        rank_at_Rp1 (NaN if structural), exit_category
    """
    rebalance_dates = sorted(universe["rebalance_date"].unique())
    pairs = list(zip(rebalance_dates[:-1], rebalance_dates[1:]))

    rows = []
    for R, Rp1 in pairs:
        in_R = set(universe.loc[
            (universe["rebalance_date"] == R) & universe["in_universe"],
            "ts_code"
        ])
        in_Rp1 = set(universe.loc[
            (universe["rebalance_date"] == Rp1) & universe["in_universe"],
            "ts_code"
        ])
        exits = in_R - in_Rp1

        # All R+1 rows for any candidate, indexed for lookup
        rp1_data = (universe[universe["rebalance_date"] == Rp1]
                    .set_index("ts_code"))

        for ts_code in exits:
            if ts_code not in rp1_data.index:
                category = "structural"
                rank_Rp1 = float("nan")
            else:
                rank_Rp1 = rp1_data.at[ts_code, "rank_by_mcap"]
                if pd.notna(rank_Rp1) and rank_Rp1 > N_UNIVERSE:
                    category = "cap_graduated"
                else:
                    category = "lost_liquidity"

            rows.append({
                "rebalance_date_R": R,
                "rebalance_date_Rp1": Rp1,
                "ts_code": ts_code,
                "rank_at_Rp1": rank_Rp1,
                "exit_category": category,
            })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Pass 2: aggregate to per-transition churn panel
# ---------------------------------------------------------------------------

def build_churn_panel(exits: pd.DataFrame) -> pd.DataFrame:
    """Per (R, R+1) pair, count exits by category and compute the churn rate."""
    pivot = (exits
             .groupby(["rebalance_date_R", "rebalance_date_Rp1", "exit_category"])
             .size()
             .unstack(fill_value=0))

    # Ensure all three categories are columns even if a category had zero in
    # the sample — defensive against pivot dropping empty columns.
    for cat in ["cap_graduated", "lost_liquidity", "structural"]:
        if cat not in pivot.columns:
            pivot[cat] = 0

    pivot = pivot[["cap_graduated", "lost_liquidity", "structural"]]
    pivot["total_exits"] = pivot.sum(axis=1)
    pivot["churn_rate"] = pivot["total_exits"] / N_UNIVERSE
    return pivot.reset_index().sort_values("rebalance_date_R")


# ---------------------------------------------------------------------------
# Plot: churn rate over time + decomposition
# ---------------------------------------------------------------------------

def plot_churn(churn: pd.DataFrame, plot_path: str) -> None:
    df = churn.copy()
    df["rebalance_date_R"] = pd.to_datetime(df["rebalance_date_R"])
    df = df.sort_values("rebalance_date_R")

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)

    # Top: total churn rate
    ax1 = axes[0]
    ax1.plot(df["rebalance_date_R"], df["churn_rate"],
             linewidth=2, color="#1f3b73", marker="o", markersize=4)
    ax1.axhline(df["churn_rate"].mean(), color="gray", linestyle=":",
                linewidth=1, label=f"Mean ({df['churn_rate'].mean():.1%})")

    for date_str, label, color in REGIME_EVENTS:
        ax1.axvline(pd.to_datetime(date_str), color=color, linestyle="--",
                    linewidth=1, label=label, alpha=0.7)

    ax1.set_ylabel("Churn rate (exits / 1000)")
    ax1.set_title("Universe churn rate per consecutive rebalance transition")
    ax1.legend(loc="upper left", ncol=2)
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    # Bottom: decomposition by category, stacked area
    ax2 = axes[1]
    ax2.stackplot(
        df["rebalance_date_R"],
        df["cap_graduated"]  / N_UNIVERSE,
        df["lost_liquidity"] / N_UNIVERSE,
        df["structural"]     / N_UNIVERSE,
        labels=["Cap graduated (A)",
                "Lost liquidity (B)",
                "Structural exit (D)"],
        colors=["#4a8fc4", "#e09a4a", "#9c4a8a"],
        alpha=0.85,
    )
    for date_str, _, color in REGIME_EVENTS:
        ax2.axvline(pd.to_datetime(date_str), color=color, linestyle="--",
                    linewidth=1, alpha=0.5)

    ax2.set_ylabel("Share of universe by exit category")
    ax2.set_xlabel("Rebalance date R")
    ax2.set_title("Churn decomposed by exit category")
    ax2.legend(loc="upper left")
    ax2.grid(True, alpha=0.3)
    ax2.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    plt.tight_layout()
    plt.savefig(plot_path, dpi=120)
    plt.close()
    print(f"Wrote churn diagnostic to {plot_path}")


# ---------------------------------------------------------------------------
# Plot: sector breakdown of exits (if sector data available)
# ---------------------------------------------------------------------------

def plot_by_sector(exits: pd.DataFrame, sector_path: str,
                   plot_path: str) -> None:
    if not os.path.exists(sector_path):
        print(f"  {sector_path} not found, skipping sector breakdown")
        return

    sw = pd.read_csv(sector_path)

    # Stage 4 schema: ts_code, l1_code, l1_name, l2_*, l3_*, in_date, out_date.
    # If the column is named differently in your environment, adjust here.
    if "l1_name" not in sw.columns:
        candidates = [c for c in sw.columns if "l1" in c.lower() and "name" in c.lower()]
        if candidates:
            sw = sw.rename(columns={candidates[0]: "l1_name"})
        else:
            print("  l1_name column not found in sw_membership; skipping sector plot")
            return

    sector_map = sw[["ts_code", "l1_name"]].drop_duplicates(subset="ts_code")
    exits_sec = exits.merge(sector_map, on="ts_code", how="left")
    exits_sec["l1_name"] = exits_sec["l1_name"].fillna("未分类")

    sector_cat = (exits_sec
                  .groupby(["l1_name", "exit_category"])
                  .size()
                  .unstack(fill_value=0))
    for cat in ["cap_graduated", "lost_liquidity", "structural"]:
        if cat not in sector_cat.columns:
            sector_cat[cat] = 0
    sector_cat = sector_cat[["cap_graduated", "lost_liquidity", "structural"]]
    sector_cat["total"] = sector_cat.sum(axis=1)

    # Top 15 sectors by total exits
    top = sector_cat.sort_values("total", ascending=True).tail(15)

    fig, ax = plt.subplots(figsize=(12, 8))
    top[["cap_graduated", "lost_liquidity", "structural"]].plot(
        kind="barh", stacked=True, ax=ax,
        color=["#4a8fc4", "#e09a4a", "#9c4a8a"], alpha=0.85,
    )
    ax.set_xlabel("Total exits across 51 transitions")
    ax.set_ylabel("申万 L1 sector")
    ax.set_title("Universe exits by sector and category (full sample)")
    ax.grid(True, alpha=0.3, axis="x")
    plt.tight_layout()
    plt.savefig(plot_path, dpi=120)
    plt.close()
    print(f"Wrote sector breakdown to {plot_path}")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main():
    print("Loading universe membership...")
    universe = pd.read_csv(UNIVERSE_PATH)
    print(f"  {len(universe):,} rows across "
          f"{universe['rebalance_date'].nunique()} dates")

    print("Categorizing exits...")
    exits = categorize_exits(universe)
    n_pairs = exits["rebalance_date_R"].nunique()
    print(f"  {len(exits):,} exits across {n_pairs} transitions")

    print("Building churn panel...")
    churn = build_churn_panel(exits)
    churn.to_csv(CHURN_PANEL_PATH, index=False)
    print(f"  Wrote {CHURN_PANEL_PATH}")

    print("Plotting churn diagnostic...")
    plot_churn(churn, CHURN_PLOT_PATH)

    print("Plotting sector breakdown (if available)...")
    plot_by_sector(exits, SECTOR_PATH, SECTOR_PLOT_PATH)

    # ---- Headline numbers ----
    print("\nHeadline numbers")
    print(f"  Mean churn rate:    {churn['churn_rate'].mean():.1%}")
    print(f"  Median churn rate:  {churn['churn_rate'].median():.1%}")
    print(f"  Min churn rate:     {churn['churn_rate'].min():.1%}  "
          f"(at {churn.loc[churn['churn_rate'].idxmin(), 'rebalance_date_R']})")
    print(f"  Max churn rate:     {churn['churn_rate'].max():.1%}  "
          f"(at {churn.loc[churn['churn_rate'].idxmax(), 'rebalance_date_R']})")
    print()

    cat_totals = churn[["cap_graduated", "lost_liquidity", "structural"]].sum()
    grand_total = cat_totals.sum()
    print(f"  Total exits over 51 transitions: {grand_total:,}")
    for cat, count in cat_totals.items():
        print(f"    {cat:<16}: {count:,} ({count / grand_total:.1%})")

    # Top 5 highest-churn transitions
    top_churn = churn.nlargest(5, "churn_rate")[
        ["rebalance_date_R", "rebalance_date_Rp1", "churn_rate",
         "cap_graduated", "lost_liquidity", "structural"]
    ]
    print(f"\n  Top 5 highest-churn transitions:")
    print(top_churn.to_string(index=False))


if __name__ == "__main__":
    main()