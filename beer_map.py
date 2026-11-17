"""
Great American Beers: interactive tile map of the most awarded beer style by state.

Python / Altair port of beer_map_R.R (Great American Beer Festival medals).
It reads data/beer_awards.csv, which update_data.py builds from the Tidy
Tuesday 2020-10-20 dataset plus the winner-list PDFs in raw/. Run it with:

    pip install altair pandas
    python beer_map.py

It writes docs/index.html, a single self-contained page (data embedded) that can
be opened locally or served with GitHub Pages (Settings > Pages > /docs).
"""

import re
from pathlib import Path

import altair as alt
import pandas as pd

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "beer_awards.csv"
OUT_FILE = ROOT / "docs" / "index.html"

BG = "#242F40"
GOLD = "#EBAA31"
FONT = "Bahnschrift, 'Segoe UI', Helvetica, Arial, sans-serif"

# Style groups, checked in order (same rules as the R case_when).
STYLE_RULES = [
    ("Lager/Pilsner/Bock", "Lager|Pilsener|Pilsners|Bock"),
    ("IPA", r"India Pale Ale|\bIPA\b"),
    ("Pale/Amber Ale", "Pale Ale|Amber Ale"),
    ("Porter/Stout/Rye/Barrel Aged",
     "Porter|Stout|Rye|Scottish-Style Ale|Schwarzbier|Barrel-Aged"),
    ("Belgian Style", "Belgian-|Belgo"),
    ("Brown Ale", "Brown Ale"),
    ("Red Ale", "Red Ale"),
    ("Wheat Beer", "Wheat Beer|Wheat Ale|Witbier"),
    ("Sour", "Sour"),
]

# Legend order and beer (SRM-inspired) colors, matching the R figure.
STYLE_COLORS = {
    "Lager/Pilsner/Bock": "#F6D281",
    "IPA": "#EBAA31",
    "Pale/Amber Ale": "#CF7200",
    "Belgian Style": "#88522B",
    "Wheat Beer": "#A63C00",
    "Sour": "#8AA000",
    "Red Ale": "#5B0000",
    "Brown Ale": "#4B0002",
    "Porter/Stout/Rye/Barrel Aged": "#0E0001",
    "Something Else": "#4D5E31",
    "None": "#A9A9A9",
}

# Square tile grid (column, row), similar to the statebins layout.
GRID = {
    "AK": (0, 0), "ME": (11, 0),
    "VT": (10, 1), "NH": (11, 1),
    "WA": (1, 2), "ID": (2, 2), "MT": (3, 2), "ND": (4, 2), "MN": (5, 2),
    "IL": (6, 2), "WI": (7, 2), "MI": (8, 2), "NY": (9, 2), "RI": (10, 2),
    "MA": (11, 2),
    "OR": (1, 3), "NV": (2, 3), "WY": (3, 3), "SD": (4, 3), "IA": (5, 3),
    "IN": (6, 3), "OH": (7, 3), "PA": (8, 3), "NJ": (9, 3), "CT": (10, 3),
    "CA": (1, 4), "UT": (2, 4), "CO": (3, 4), "NE": (4, 4), "MO": (5, 4),
    "KY": (6, 4), "WV": (7, 4), "VA": (8, 4), "MD": (9, 4), "DE": (10, 4),
    "AZ": (2, 5), "NM": (3, 5), "KS": (4, 5), "AR": (5, 5), "TN": (6, 5),
    "NC": (7, 5), "SC": (8, 5), "DC": (9, 5),
    "OK": (4, 6), "LA": (5, 6), "MS": (6, 6), "AL": (7, 6), "GA": (8, 6),
    "HI": (0, 7), "TX": (4, 7), "FL": (9, 7),
}


def classify(category: str) -> str:
    for style, pattern in STYLE_RULES:
        if re.search(pattern, category):
            return style
    return "Something Else"


def load_awards() -> pd.DataFrame:
    beer = pd.read_csv(DATA_FILE)
    beer["state"] = beer["state"].str.upper()
    style_map = {c: classify(c) for c in beer["category"].unique()}
    beer["style"] = beer["category"].map(style_map)
    return beer


def top_style_by_state(beer: pd.DataFrame) -> pd.DataFrame:
    """One row per state: its most awarded category, plus medal totals."""
    counts = (
        beer.groupby(["state", "category", "style"]).size()
        .reset_index(name="n")
        # ties broken alphabetically by category, as in the R code
        .sort_values(["state", "n", "category"], ascending=[True, False, True])
    )
    top = counts.groupby("state").head(1)

    medals = (
        beer.pivot_table(index="state", columns="medal", values="beer_name",
                         aggfunc="count", fill_value=0)
        .reindex(columns=["Gold", "Silver", "Bronze"], fill_value=0)
        .reset_index()
    )
    medals["total"] = medals[["Gold", "Silver", "Bronze"]].sum(axis=1)
    top = top.merge(medals, on="state")

    # Every grid state gets a tile; states with no awards (WV) get "None".
    grid = pd.DataFrame(
        [(s, c, r) for s, (c, r) in GRID.items()], columns=["state", "col", "row"]
    )
    tiles = grid.merge(top, on="state", how="left")
    tiles["style"] = tiles["style"].fillna("None")
    tiles["category"] = tiles["category"].fillna("No medals")
    for col in ["n", "Gold", "Silver", "Bronze", "total"]:
        tiles[col] = tiles[col].fillna(0).astype(int)
    # Dark text on light beers, light text on dark beers.
    light = {"Lager/Pilsner/Bock", "IPA", "None"}
    tiles["label_color"] = tiles["style"].map(lambda s: BG if s in light else "white")
    return tiles


def style_counts(beer: pd.DataFrame) -> pd.DataFrame:
    """Awards per state and style, for the linked bar chart."""
    return beer.groupby(["state", "style"]).size().reset_index(name="n")


def build_chart(tiles: pd.DataFrame, counts: pd.DataFrame,
                years: str) -> alt.Chart:
    present = set(tiles["style"])
    domain = [s for s in STYLE_COLORS if s in present]
    color = alt.Color(
        "style:N",
        scale=alt.Scale(domain=domain, range=[STYLE_COLORS[s] for s in domain]),
        legend=alt.Legend(title=None, orient="bottom", columns=3,
                          symbolType="square", symbolSize=200, labelLimit=250),
    )

    pick = alt.selection_point(fields=["state"], name="pick")

    tile_size = 52
    x = alt.X("col:O", axis=None)
    y = alt.Y("row:O", axis=None)

    base = alt.Chart(tiles).encode(x=x, y=y)
    squares = base.mark_rect(
        cornerRadius=6, stroke=BG, strokeWidth=3, cursor="pointer"
    ).encode(
        color=color,
        opacity=alt.condition(pick, alt.value(1), alt.value(0.3)),
        tooltip=[
            alt.Tooltip("state:N", title="State"),
            alt.Tooltip("style:N", title="Top style group"),
            alt.Tooltip("category:N", title="Most awarded category"),
            alt.Tooltip("n:Q", title="Medals in that category"),
            alt.Tooltip("total:Q", title="Total medals"),
            alt.Tooltip("Gold:Q"),
            alt.Tooltip("Silver:Q"),
            alt.Tooltip("Bronze:Q"),
        ],
    ).add_params(pick)
    labels = base.mark_text(fontSize=13, fontWeight="bold", font=FONT).encode(
        text="state:N",
        color=alt.Color("label_color:N", scale=None),
    )
    tile_map = (squares + labels).properties(
        width=tile_size * 12, height=tile_size * 8
    )

    bars = (
        alt.Chart(counts)
        .transform_filter(pick)
        .transform_aggregate(n="sum(n)", groupby=["style"])
        .mark_bar(cornerRadiusEnd=4, stroke="#ffffff33")
        .encode(
            y=alt.Y("style:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=220)),
            x=alt.X("n:Q", title="Medals awarded"),
            color=alt.Color("style:N",
                            scale=alt.Scale(domain=list(STYLE_COLORS),
                                            range=list(STYLE_COLORS.values())),
                            legend=None),
            tooltip=[alt.Tooltip("style:N", title="Style group"),
                     alt.Tooltip("n:Q", title="Medals")],
        )
        .properties(
            width=320, height=tile_size * 8 - 40,
            title=alt.Title(
                "Medals by style group",
                subtitle="All states, or the states you click",
                anchor="start", color=GOLD, subtitleColor="#c9d1dc",
            ),
        )
    )

    return (
        alt.hconcat(tile_map, bars, spacing=40)
        .resolve_scale(color="independent")
        .properties(
            title=alt.Title(
                "Great American Beers",
                subtitle=[
                    "Most awarded beer style by state at the Great American "
                    f"Beer Festival, {years}.",
                    "Hover a state for details. Click to filter the bar chart "
                    "(shift-click for several, double-click to reset).",
                ],
                fontSize=30, color=GOLD, subtitleColor="white",
                subtitleFontSize=13, anchor="middle", offset=16,
            ),
            padding=24,
        )
        .configure(background=BG, font=FONT)
        .configure_view(stroke=None)
        .configure_axis(labelColor="white", titleColor="white",
                        gridColor="#ffffff22", domainColor="#ffffff55",
                        tickColor="#ffffff55", labelFontSize=12)
        .configure_legend(labelColor="white", labelFontSize=12)
    )


def main() -> None:
    beer = load_awards()
    tiles = top_style_by_state(beer)
    years = f"{beer['year'].min()}-{beer['year'].max()}"
    chart = build_chart(tiles, style_counts(beer), years)
    OUT_FILE.parent.mkdir(exist_ok=True)
    chart.save(OUT_FILE)
    print(f"Wrote {OUT_FILE}")
    print(tiles[["state", "style", "category", "n"]].to_string(index=False))


if __name__ == "__main__":
    main()
