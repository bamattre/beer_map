"""
Build data/beer_awards.csv: Great American Beer Festival medals, 1987 onward.

  * 1987-2020 come from the Tidy Tuesday dataset (2020-10-20).
  * 2021 onward are parsed from the official winners-list PDFs in raw/.

Run this only when raw/ changes (e.g. a new year's PDF is added):

    pip install pandas pdfplumber
    python update_data.py

beer_map.py then reads the combined CSV; it never touches the PDFs.
"""

import re
from pathlib import Path

import pandas as pd
import pdfplumber

ROOT = Path(__file__).parent
RAW_DIR = ROOT / "raw"
OUT_FILE = ROOT / "data" / "beer_awards.csv"
TIDYTUESDAY_URL = (
    "https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/"
    "data/2020/2020-10-20/beer_awards.csv"
)
COLUMNS = ["medal", "beer_name", "brewery", "city", "state", "category", "year"]

# The PDFs are two columns on a 612pt-wide page; the right column starts
# at x = 306-315 in every file, so the page is split at its midpoint.
COLUMN_SPLIT = 300

US_STATES = set(
    "AK AL AR AZ CA CO CT DC DE FL GA HI IA ID IL IN KS KY LA MA MD ME MI MN "
    "MO MS MT NC ND NE NH NJ NM NV NY OH OK OR PA RI SC SD TN TX UT VA VT WA "
    "WI WV WY".split()
)

# "Category 12: Name - 34 Entries"; the special competitions at the end
# sometimes drop the "Category N:" prefix.
CATEGORY_RE = re.compile(
    r"^(?:Category:?\s*\d*\s*:\s*)?(?P<name>.+?)\s+-\s+[\d,]+\s+Entries$", re.I
)
MEDAL_RE = re.compile(r"^(?P<medal>Gold|Silver|Bronze):\s*(?P<text>.*)$")
YEAR_RE = re.compile(r"(\d{4}) WINNERS LIST")
# Pieces of the page title / footer, which the column split cuts in half.
JUNK_RE = re.compile(
    r"GreatAmericanBeerFestival|#gabf|WINNERS LIST|NNERS LIST|^\d{4} WIN$|^\d+$"
)
# The list ends with brewery-of-the-year awards, which aren't beer medals.
END_RE = re.compile(r"Brewery of the year", re.I)
# Occasionally two medals share a line ("..., WA Bronze: Next Beer, ...").
MID_MEDAL_RE = re.compile(r"\s+(?=(?:Gold|Silver|Bronze):)")

# Entries the PDFs get wrong, keyed by (year, beer_name).
MANUAL_FIXES = {
    # 2022 PDF omits city/state; the same pub is listed as Portland, OR in 2024.
    (2022, "Hachimitsu Mai"): {
        "brewery": "Deschutes Brewery - Portland Brewery & Public House",
        "city": "Portland", "state": "OR",
    },
    # 2025 PDF garbles this name ("O.B." overlaps "CA" from the next line).
    (2025, "O .BC.A Brown"): {
        "beer_name": "O.B. Brown",
        "brewery": "Canyon Lakes Golf Course & Brewery",
        "city": "San Ramon", "state": "CA",
    },
}

# Special competitions that aren't regular style categories.
SKIP_CATEGORY_RE = re.compile(r"Pro-Am|Collab|Cider", re.I)


def pdf_lines(path: Path) -> tuple[int, list[str]]:
    """Return the competition year and the text lines in reading order:
    left column then right column, page by page."""
    lines = []
    with pdfplumber.open(path) as pdf:
        # The title spans both columns, so read it from the whole page.
        match = YEAR_RE.search(pdf.pages[0].extract_text() or "")
        year = int(match.group(1)) if match else None
        for page in pdf.pages:
            halves = [
                page.crop((0, 0, COLUMN_SPLIT, page.height)),
                page.crop((COLUMN_SPLIT, 0, page.width, page.height)),
            ]
            for half in halves:
                text = half.extract_text() or ""
                for line in text.splitlines():
                    line = line.strip()
                    if END_RE.search(line):
                        line = END_RE.split(line)[0]
                        line = re.sub(r"\d{4}\s*$", "", line).strip()
                        if line and not JUNK_RE.search(line):
                            lines.append(line)
                        return year, lines
                    if not line or JUNK_RE.search(line):
                        continue
                    lines.extend(MID_MEDAL_RE.split(line))
    if year is None:  # pragma: no cover
        raise ValueError(f"No 'YYYY WINNERS LIST' heading found in {path.name}")
    return year, lines


def split_entry(text: str) -> dict:
    """'Beer, Brewery, City, ST' -> fields.

    Beer names sometimes contain commas ("Berry, Berry, Quite Contrary"), so
    the brewery is taken as the last part before the city and everything
    before it is the beer name. State and city (what the map uses) are
    always the last two parts.
    """
    parts = [p.strip() for p in text.split(",")]
    parts = [p for p in parts if p]
    if len(parts) < 4 or parts[-1] not in US_STATES:
        # Malformed in the PDF itself (e.g. city/state missing). Keep the raw
        # text so it can be reported and fixed in MANUAL_FIXES.
        return {"beer_name": parts[0], "brewery": ", ".join(parts[1:]),
                "city": None, "state": None, "raw": text}
    state, city = parts[-1], parts[-2]
    brewery = parts[-3]
    beer = ", ".join(parts[:-3])
    return {"beer_name": beer, "brewery": brewery.lstrip("- ").strip(),
            "city": city, "state": state, "raw": text}


def parse_pdf(path: Path) -> pd.DataFrame:
    year, lines = pdf_lines(path)
    rows, category, current, header = [], None, None, None

    def flush():
        if current is not None:
            rows.append({**current, **split_entry(current.pop("text"))})

    for line in lines:
        # Long category names wrap; gather the header until "Entries".
        if header is not None:
            header += " " + line
            if "Entries" not in line:
                continue
            line, header = header, None
        elif line.startswith("Category") and "Entries" not in line:
            flush(); current = None
            header = line
            continue
        cat = CATEGORY_RE.match(line)
        med = MEDAL_RE.match(line)
        if cat:
            flush(); current = None
            category = cat.group("name").strip()
        elif med:
            flush()
            current = {"medal": med.group("medal"), "category": category,
                       "year": year, "text": med.group("text")}
        elif current is not None:
            # A wrapped line belongs to the entry above it.
            current["text"] += " " + line
        # Anything else (headings, footers before the first entry) is ignored.
    flush()
    df = pd.DataFrame(rows)
    for (fix_year, beer), fields in MANUAL_FIXES.items():
        hit = (df["year"] == fix_year) & (df["beer_name"] == beer)
        for col, value in fields.items():
            df.loc[hit, col] = value
    return df[~df["category"].str.contains(SKIP_CATEGORY_RE)]


def main() -> None:
    old = pd.read_csv(TIDYTUESDAY_URL)
    new = pd.concat(
        [parse_pdf(p) for p in sorted(RAW_DIR.glob("*.pdf"))], ignore_index=True
    )

    # Sanity checks: every entry should have a US state, and every category
    # should have one gold, one silver and one bronze (ties are possible, so
    # only report, don't fail).
    bad_state = new[~new["state"].isin(US_STATES)]
    if len(bad_state):
        print("Entries without a recognised state:")
        print(bad_state.to_string())
    per_cat = new.groupby(["year", "category"])["medal"].count()
    odd = per_cat[per_cat != 3]
    if len(odd):
        print("Categories without exactly 3 medals (check for ties/no award):")
        print(odd.to_string())

    if set(new["year"]) & set(old["year"]):
        raise ValueError("PDF years overlap the Tidy Tuesday years")

    combined = pd.concat([old, new[COLUMNS]], ignore_index=True)
    OUT_FILE.parent.mkdir(exist_ok=True)
    combined.to_csv(OUT_FILE, index=False)

    print(new.groupby("year").size().rename("medals parsed").to_string())
    print(f"Wrote {len(combined)} rows ({combined.year.min()}-"
          f"{combined.year.max()}) to {OUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
