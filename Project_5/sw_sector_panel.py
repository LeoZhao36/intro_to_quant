# sw_sector_panel.py — interactive 申万 hierarchy panel over time
import pandas as pd
import plotly.express as px
from pathlib import Path

DATA = Path("data")

# 1. Load both inputs
universe = pd.read_csv(
    DATA / "universe_membership.csv",
    parse_dates=["rebalance_date"],
)
sw = pd.read_csv(
    DATA / "sw_membership.csv",
    dtype={"in_date": str, "out_date": str},
)

# 2. Restrict to in-universe rows only (52 dates × 1000 = 52,000 rows)
universe_in = universe[universe["in_universe"]].copy()

# 3. Parse 申万 in_date as datetime for comparison with rebalance_date
sw["in_date_dt"] = pd.to_datetime(sw["in_date"], format="%Y%m%d")

# 4. Left-join: every in-universe row gets its current SW classification (or NaN)
joined = universe_in.merge(
    sw[["ts_code", "l1_name", "l2_name", "l3_name", "in_date_dt"]],
    on="ts_code",
    how="left",
)

# 5. Point-in-time guard: classification only valid if it began on or before rebalance_date
unclass_mask = (
    joined["in_date_dt"].isna()
    | (joined["in_date_dt"] > joined["rebalance_date"])
)
joined.loc[unclass_mask, ["l1_name", "l2_name", "l3_name"]] = "未分类"

# Sanity: how big is the unclassified bucket?
unclass_per_date = joined[joined["l1_name"] == "未分类"].groupby("rebalance_date").size()
print(f"未分类 bucket size per date: "
      f"min={unclass_per_date.min() if len(unclass_per_date) else 0}, "
      f"max={unclass_per_date.max() if len(unclass_per_date) else 0}, "
      f"mean={unclass_per_date.mean():.1f}" if len(unclass_per_date) else "0")
print(f"As share of 1000-stock universe: max={unclass_per_date.max() / 1000:.1%}"
      if len(unclass_per_date) else "")

# 6. Aggregate to (rebalance_date, l1, l2, l3) → stock count
agg = (
    joined.groupby(["rebalance_date", "l1_name", "l2_name", "l3_name"])
    .size()
    .reset_index(name="count")
)
agg["rebalance_date_str"] = agg["rebalance_date"].dt.strftime("%Y-%m-%d")

print(f"\nAggregated to {len(agg)} (date, l1, l2, l3) rows")
print(f"Unique L1 ever appearing: {agg['l1_name'].nunique()}")
print(f"Total stocks per date check (should all be 1000):")
print(agg.groupby("rebalance_date_str")["count"].sum().describe())

# 7. Quick diagnostic: which date has the largest unclassified bucket?
print(f"\n未分类 by rebalance date (top 5):")
print(unclass_per_date.sort_values(ascending=False).head().to_string())

# 8. Build the treemap trace builder. We construct one trace per date.
#    Using px.treemap to build each trace gives us the path / hover handling for free,
#    then we extract .data[0] as the underlying go.Treemap to feed into frames.
import plotly.graph_objects as go
import plotly.express as px

dates = sorted(agg["rebalance_date_str"].unique())

def trace_for_date(date_str):
    sub = agg[agg["rebalance_date_str"] == date_str]
    sub_fig = px.treemap(
        sub,
        path=[px.Constant("Bottom-1000"), "l1_name", "l2_name", "l3_name"],
        values="count",
        color="l1_name",
    )
    sub_fig.update_traces(root_color="lightgray")
    return sub_fig.data[0]

# 9. Initial figure shows the first date; frames carry the rest.
fig = go.Figure(data=[trace_for_date(dates[0])])
fig.frames = [
    go.Frame(data=[trace_for_date(d)], name=d)
    for d in dates
]

# 10. Slider config: each step jumps to one frame.
slider_steps = [
    {
        "args": [
            [d],
            {"frame": {"duration": 300, "redraw": True}, "mode": "immediate"},
        ],
        "label": d,
        "method": "animate",
    }
    for d in dates
]

sliders = [{
    "active": 0,
    "steps": slider_steps,
    "x": 0.1,
    "y": 0,
    "len": 0.9,
    "currentvalue": {"prefix": "Rebalance date: ", "visible": True},
    "pad": {"t": 40, "b": 10},
}]

# 11. Play / Pause buttons.
updatemenus = [{
    "type": "buttons",
    "x": 0,
    "y": 0,
    "direction": "left",
    "showactive": False,
    "buttons": [
        {
            "label": "▶ Play",
            "method": "animate",
            "args": [None, {"frame": {"duration": 700, "redraw": True}, "fromcurrent": True}],
        },
        {
            "label": "⏸ Pause",
            "method": "animate",
            "args": [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}],
        },
    ],
}]

fig.update_layout(
    title="Bottom-1000 universe: 申万 sector composition over 52 monthly rebalances",
    width=1300,
    height=850,
    margin=dict(t=80, l=10, r=10, b=80),
    sliders=sliders,
    updatemenus=updatemenus,
)

# 12. Save as standalone interactive HTML.
out_path = DATA / "sw_sector_panel.html"
fig.write_html(out_path, include_plotlyjs="cdn")
print(f"\nSaved interactive panel to {out_path}")
print(f"Open with: start {out_path}")