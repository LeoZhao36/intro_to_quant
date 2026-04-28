"""
size_pipeline.py

Project 6 Session 1, Task 2: thin size factor pipeline.

Loads Project 5's universe_membership.csv and forward_return_panel.csv,
computes log_mcap quintiles per rebalance date, joins forward returns,
produces Q1-Q5 monthly long-short and monthly Spearman IC, and plots both
with reference lines for the three identified 2024 regime events.

This is the MVP that verifies Project 5's outputs wire correctly into a
factor-testing harness. No robustness layers yet (sector neutralization,
cap conditioning, regime split, tradable-only filter); those come in
Block 2 of Project 6.

Data location assumption: this script reads CSVs from a `data/` folder
relative to wherever it's run from. Adjust DATA_DIR if your project uses
a different layout.

Run from Project_6/ as: `python size_pipeline.py`
"""

# %%  Imports and configuration --------------------------------------------
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Chinese-character matplotlib config for regime event labels.
# If you have plot_setup.py from Project 2, you can replace this with
# `from plot_setup import setup_chinese_font; setup_chinese_font()`.
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# Path to where Project 5 wrote its CSVs. Adjust as needed.
DATA_DIR = Path("data")
UNIVERSE_PATH = DATA_DIR / "universe_membership.csv"
RETURN_PATH = DATA_DIR / "forward_return_panel.csv"

# Three regime events identified in Project 5 Option 2's forward-return panel.
REGIME_EVENTS = {
    "雪球 meltdown": pd.Timestamp("2024-01-15"),
    "新国九条": pd.Timestamp("2024-03-15"),
    "PBoC stimulus": pd.Timestamp("2024-09-18"),
}


# %%  Load the canonical universe and forward returns ----------------------
universe = pd.read_csv(
    UNIVERSE_PATH,
    parse_dates=["rebalance_date"],
    dtype={"ts_code": str, "in_universe": bool},
)
returns = pd.read_csv(
    RETURN_PATH,
    parse_dates=["rebalance_date"],
    dtype={"ts_code": str, "entry_tradable": bool, "exit_tradable": bool},
)

print(f"universe_membership.csv: {len(universe):,} rows")
print(f"forward_return_panel.csv: {len(returns):,} rows")
print(f"in_universe == True:     {universe['in_universe'].sum():,}")
print(f"unique rebalance dates:   {universe['rebalance_date'].nunique()}")


# %%  Filter to in-universe rows and compute log market cap ---------------
universe_in = universe[universe["in_universe"]].copy()
universe_in["log_mcap"] = np.log(universe_in["circ_mv_yi"])

counts_per_date = universe_in.groupby("rebalance_date").size()
print(
    f"\nin-universe stocks per date - min: {counts_per_date.min()}, "
    f"max: {counts_per_date.max()}, median: {int(counts_per_date.median())}"
)


# %%  Quintile sort within each rebalance date ----------------------------
# pd.qcut with labels=False returns 0..4 integer labels.
# Q1 (smallest) = label 0, Q5 (largest) = label 4.
# duplicates="drop" handles the rare case of identical log_mcap values
# at quintile boundaries by collapsing duplicate edges instead of raising.
universe_in["quintile"] = (
    universe_in.groupby("rebalance_date")["log_mcap"]
    .transform(lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
)


# %%  Join forward returns -----------------------------------------------
panel = universe_in.merge(
    returns,
    on=["rebalance_date", "ts_code"],
    how="left",
)
print(f"\nMerged panel: {len(panel):,} rows")
print(f"Rows with non-null forward_return: {panel['forward_return'].notna().sum():,}")


# %%  Per-quintile monthly mean returns ----------------------------------
quintile_returns = (
    panel.groupby(["rebalance_date", "quintile"])["forward_return"]
    .mean()
    .unstack()
)
print(f"\nQuintile mean-return matrix shape: {quintile_returns.shape}")
print("First 3 rows:")
print(quintile_returns.head(3).round(4))


# %%  Q1 - Q5 long-short return time series -------------------------------
long_short = quintile_returns[0] - quintile_returns[4]
ls_clean = long_short.dropna()

print(f"\n--- Q1 - Q5 long-short ---")
print(f"  Months observed:     {len(ls_clean)}")
print(f"  Mean monthly return: {ls_clean.mean():+.4f} ({ls_clean.mean() * 12:+.2%}/yr)")
print(f"  Std monthly return:  {ls_clean.std():.4f}")
print(f"  Months with Q1 > Q5: {(ls_clean > 0).sum()} of {len(ls_clean)}")
print(f"  Naive Sharpe:        {ls_clean.mean() / ls_clean.std() * np.sqrt(12):+.3f}")


# %%  Cross-sectional Spearman rank IC per rebalance date ------------------
ic_series = (
    panel.dropna(subset=["forward_return", "log_mcap"])
    .groupby("rebalance_date")
    .apply(
        lambda g: g["log_mcap"].corr(g["forward_return"], method="spearman"),
        include_groups=False,
    )
)
ic_clean = ic_series.dropna()

print(f"\n--- IC time series (Spearman rank correlation) ---")
print(f"  Months observed:   {len(ic_clean)}")
print(f"  Mean IC:           {ic_clean.mean():+.4f}")
print(f"  Std IC:            {ic_clean.std():.4f}")
print(f"  IC IR (annualised):{ic_clean.mean() / ic_clean.std() * np.sqrt(12):+.3f}")
print(f"  Months IC < 0:     {(ic_clean < 0).sum()} of {len(ic_clean)}")
print(
    "  (IC < 0 means high log_mcap predicts low return; "
    "this is the size-effect direction.)"
)


# %%  Plot 1: cumulative quintile returns ---------------------------------
cum_returns = (1 + quintile_returns.fillna(0)).cumprod()

fig, ax = plt.subplots(figsize=(11, 5.5))
colors = plt.cm.RdYlBu_r(np.linspace(0.10, 0.90, 5))
labels = {0: "Q1 (smallest)", 1: "Q2", 2: "Q3", 3: "Q4", 4: "Q5 (largest)"}

for q in range(5):
    if q in cum_returns.columns:
        ax.plot(
            cum_returns.index,
            cum_returns[q],
            label=labels[q],
            color=colors[q],
            linewidth=1.6,
        )

# Regime event markers
ymax = ax.get_ylim()[1]
for label, event_date in REGIME_EVENTS.items():
    ax.axvline(event_date, color="grey", linestyle="--", alpha=0.55, linewidth=0.9)
    ax.text(
        event_date,
        ymax * 0.985,
        label,
        rotation=90,
        verticalalignment="top",
        fontsize=8,
        color="dimgrey",
    )

ax.set_title("Cumulative monthly returns by log-mcap quintile")
ax.set_xlabel("Rebalance date")
ax.set_ylabel("Cumulative return (×)")
ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("size_quintile_cumulative_returns.png", dpi=120)


# %%  Plot 2: IC time series with mean line and regime markers -----------
fig, ax = plt.subplots(figsize=(11, 4.5))
ax.bar(ic_clean.index, ic_clean.values, width=20, alpha=0.70, color="steelblue")
ax.axhline(0, color="black", linewidth=0.7)
ax.axhline(
    ic_clean.mean(),
    color="firebrick",
    linestyle="--",
    alpha=0.85,
    label=f"Mean IC = {ic_clean.mean():+.4f}",
)

ymax = ax.get_ylim()[1]
ymin = ax.get_ylim()[0]
for label, event_date in REGIME_EVENTS.items():
    ax.axvline(event_date, color="grey", linestyle="--", alpha=0.55, linewidth=0.9)
    ax.text(
        event_date,
        ymax * 0.95 if ymax > abs(ymin) else ymin * 0.95,
        label,
        rotation=90,
        verticalalignment="top" if ymax > abs(ymin) else "bottom",
        fontsize=8,
        color="dimgrey",
    )

ax.set_title("Cross-sectional Spearman IC: log_mcap vs forward_return")
ax.set_xlabel("Rebalance date")
ax.set_ylabel("Spearman rank IC")
ax.legend(loc="upper right", framealpha=0.85)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("size_ic_time_series.png", dpi=120)


# %%  Sanity-check summary -----------------------------------------------
print("\n=== Sanity-check verdict ===")
mean_ls = ls_clean.mean()
mean_ic = ic_clean.mean()

if mean_ls > 0 and mean_ic < 0:
    direction = "small > large (size effect direction)"
elif mean_ls < 0 and mean_ic > 0:
    direction = "large > small (size effect REVERSED)"
else:
    direction = "Q1-Q5 and IC disagree on sign; investigate"

print(f"Q1 - Q5 mean: {mean_ls:+.4f}/month   ({mean_ls * 12:+.2%} annualised)")
print(f"Mean IC:      {mean_ic:+.4f}")
print(f"Direction:    {direction}")
print()
print("Reminders:")
print("  - This is descriptive, not yet tested for significance.")
print("  - No bootstrap CI yet, no Holm-Bonferroni threshold yet.")
print("  - Sector composition not controlled for.")
print("  - Tradable-only filter not applied.")
print("  - 2022-2024 vs 2025-2026 regime split not done.")
print("  - These are Block 2 of Project 6.")

plt.show()