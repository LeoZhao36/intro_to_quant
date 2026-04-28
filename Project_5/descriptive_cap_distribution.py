# Option 1, Step 1: cap distribution evolution within the bottom-1000 universe
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import plot_setup  # Chinese character rendering, already in Project_5/

DATA = Path(__file__).parent / "data"

# Load and restrict to in-universe rows only
df = pd.read_csv(DATA / "universe_membership.csv", parse_dates=["rebalance_date"])
universe = df[df["in_universe"]].copy()

# Cross-sectional percentiles of circ_mv_yi per rebalance date.
# .quantile() with a list returns a MultiIndex; unstack to get one column per percentile.
percentiles = [0.05, 0.25, 0.50, 0.75, 0.95]
cap_by_date = (
    universe.groupby("rebalance_date")["circ_mv_yi"]
    .quantile(percentiles)
    .unstack()
)
cap_by_date.columns = [f"P{int(p*100)}" for p in percentiles]

# After cap_by_date is built
cv = cap_by_date.std() / cap_by_date.mean()
pct_change = cap_by_date.iloc[-1] / cap_by_date.iloc[0] - 1

print("\nCoefficient of variation (std / mean):")
print(cv.round(3))
print("\nPercentage change first to last date:")
print((pct_change * 100).round(1))

# Inspect the table before plotting
print("First 5 rebalance dates:")
print(cap_by_date.head())
print("\nLast 5 rebalance dates:")
print(cap_by_date.tail())
print("\nOverall summary across all 52 dates:")
print(cap_by_date.describe())

# Plot
fig, ax = plt.subplots(figsize=(12, 6))
for col in cap_by_date.columns:
    ax.plot(cap_by_date.index, cap_by_date[col], label=col, linewidth=1.5)

# Mark the 2024-09-24 PBoC stimulus boundary surfaced in Stage 2
ax.axvline(
    pd.Timestamp("2024-09-24"),
    color="red", linestyle="--", alpha=0.5,
    label="PBoC stimulus (2024-09-24)",
)

ax.set_xlabel("Rebalance date")
ax.set_ylabel("Circulating market cap (亿 RMB)")
ax.set_title("Bottom-1000 universe: cap distribution evolution, 2022-01 to 2026-04")
ax.legend(loc="upper left")
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(DATA / "descriptive_cap_distribution.png", dpi=150)
plt.show()

