import pandas as pd
p = pd.read_parquet("data/factor_panel_a.parquet")
print("shape:", p.shape)
print("index:", p.index.names, "| index dtype:", p.index.dtype if not isinstance(p.index, pd.MultiIndex) else [p.index.get_level_values(i).dtype for i in range(p.index.nlevels)])
print("columns:", list(p.columns))
print("dtypes:")
print(p.dtypes)
print("\nhead:")
print(p.head(3))