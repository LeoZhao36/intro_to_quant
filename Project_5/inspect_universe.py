# inspect_universe.py — Option 1, Step 0: load and look
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent  / "data"  # adjust if needed for your layout

# Load the canonical universe membership file
df = pd.read_csv(DATA / "universe_membership.csv", parse_dates=["rebalance_date"])

# Basic shape and column inventory
print(f"Shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(f"Date range: {df['rebalance_date'].min()} to {df['rebalance_date'].max()}")
print(f"N unique rebalance dates: {df['rebalance_date'].nunique()}")
print(f"N unique ts_codes: {df['ts_code'].nunique()}")

# How many in-universe per date (should be 1000 every date by construction)
in_univ_counts = df.groupby("rebalance_date")["in_universe"].sum()
print(f"\nin_universe count per date: min={in_univ_counts.min()}, "
      f"max={in_univ_counts.max()}, all-equal-to-1000? "
      f"{(in_univ_counts == 1000).all()}")

# Quick look at the first few rows of an in-universe slice
sample = df[df["in_universe"] & (df["rebalance_date"] == df["rebalance_date"].max())]
print(f"\nSample (latest rebalance date, first 5 in-universe rows):")
print(sample.head())

# inspect_stock_basic — quick sanity check before sector analysis
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent / "data"
basic = pd.read_csv(DATA / "stock_basic.csv")

print(f"Shape: {basic.shape}")
print(f"Columns: {list(basic.columns)}")
print(f"\nFirst 3 rows:")
print(basic.head(3))

if "industry" in basic.columns:
    print(f"\nIndustry NaN rate: {basic['industry'].isna().mean():.2%}")
    print(f"\nUnique industries: {basic['industry'].nunique()}")
    print(f"\nTop 10 industries by stock count:")
    print(basic["industry"].value_counts().head(10))