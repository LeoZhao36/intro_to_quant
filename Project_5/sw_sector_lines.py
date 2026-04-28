# sw_sector_lines.py — line chart companion to the treemap panel
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import plot_setup  # Chinese character rendering

DATA = Path("data")

# Same load/join logic as sw_sector_panel.py
universe = pd.read_csv(DATA / "universe_membership.csv", parse_dates=["rebalance_date"])
sw = pd.read_csv(DATA / "sw_membership.csv", dtype={"in_date": str, "out_date": str})

universe_in = universe[universe["in_universe"]].copy()
sw["in_date_dt"] = pd.to_datetime(sw["in_date"], format="%Y%m%d")

joined = universe_in.merge(
    sw[["ts_code", "l1_name", "in_date_dt"]],
    on="ts_code", how="left",
)
unclass_mask = joined["in_date_dt"].isna() | (joined["in_date_dt"] > joined["rebalance_date"])
joined.loc[unclass_mask, "l1_name"] = "未分类"

# Per-date L1 counts
counts = joined.groupby(["rebalance_date", "l1_name"]).size().unstack(fill_value=0)

# Pick top N L1s by peak count, excluding the artifact bucket
TOP_N = 10
plot_l1s = (
    counts.drop(columns=["未分类"], errors="ignore")
    .max()
    .sort_values(ascending=False)
    .head(TOP_N)
    .index.tolist()
)

# Plot
fig, ax = plt.subplots(figsize=(13, 7))
for l1 in plot_l1s:
    ax.plot(counts.index, counts[l1], label=l1, linewidth=1.6, marker="o", markersize=3)

# Stimulus reference line
ax.axvline(pd.Timestamp("2024-09-24"), color="red", linestyle="--", alpha=0.4,
           label="PBoC stimulus (2024-09-24)")

ax.set_xlabel("Rebalance date")
ax.set_ylabel("Number of bottom-1000 stocks")
ax.set_title(f"申万一级 sector trajectories in the bottom-1000 universe "
             f"(top {TOP_N} by peak count)")
ax.legend(loc="upper left", ncol=2, fontsize=9)
ax.grid(True, alpha=0.3)

unclass_max = counts["未分类"].max() if "未分类" in counts.columns else 0
fig.text(0.5, 0.02,
    f"Note: 未分类 excluded from plot ({unclass_max} at 2022-01, ≈2 by 2024-09; "
    f"in_date artifact, not real drift).",
    ha="center", fontsize=9, style="italic", color="gray")

plt.tight_layout(rect=[0, 0.03, 1, 1])
plt.savefig(DATA / "sw_sector_lines.png", dpi=150)
plt.show()