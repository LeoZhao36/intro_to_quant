import pandas as pd

sw = pd.read_csv("data/sw_membership.csv", dtype={"ts_code": str})
for code in ["000004.SZ", "000005.SZ", "000007.SZ", "000010.SZ", "000011.SZ"]:
    rows = sw[sw["ts_code"] == code]
    print(f"{code}: {len(rows)} rows")
    if len(rows) > 0:
        print(rows[["ts_code", "in_date", "out_date", "l1_name"]].to_string())
    print()