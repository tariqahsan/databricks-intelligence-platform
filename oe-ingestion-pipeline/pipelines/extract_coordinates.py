"""
extract_coordinates.py
======================
One-time utility: reads master_dataframe_long.xlsx and writes
router-coordinates.json for the Angular trail map component.

Run from the oe-ingestion-pipeline folder:
    python extract_coordinates.py

Output:
    router-coordinates.json

Copy the output file to your Angular project:
    frontend/src/assets/data/router-coordinates.json

The JSON format matches RouterCoordinates in network-flow.models.ts:
    {
      "UURWMEA110": { "lat": 39.083, "lng": -76.733 },
      "DK_PENTAGON_DC": { "lat": 38.870, "lng": -77.055 },
      ...
    }
"""
import json
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("ERROR: pip install pandas openpyxl")
    sys.exit(1)

XLSX_FILE   = "master_dataframe_long.xlsx"
OUTPUT_FILE = "router-coordinates.json"

# Fort Meade core hub coordinates — hardcoded as authoritative reference
FORT_MEADE_HUBS = {
    "UURWMEA110": { "lat": 39.083, "lng": -76.733 },
    "UURWMEA120": { "lat": 39.083, "lng": -76.733 },
    "UURWMEA440": { "lat": 39.083, "lng": -76.733 },
    "UURWMEA100": { "lat": 39.083, "lng": -76.733 },
}


def extract_coordinates(xlsx_path: str) -> dict:
    print(f"Reading: {xlsx_path}")
    df = pd.read_excel(xlsx_path)

    # Show columns so user can verify
    print(f"Columns found: {list(df.columns)}")

    # Try common column name variants for Router, Latitude, Longitude
    router_col = next(
        (c for c in df.columns if c.strip().lower() in ("router", "node", "router_name", "name")),
        None
    )
    lat_col = next(
        (c for c in df.columns if c.strip().lower() in ("latitude", "lat")),
        None
    )
    lng_col = next(
        (c for c in df.columns if c.strip().lower() in ("longitude", "lng", "lon")),
        None
    )

    if not all([router_col, lat_col, lng_col]):
        print(f"ERROR: Could not find required columns.")
        print(f"  Expected: Router/Node, Latitude/Lat, Longitude/Lng/Lon")
        print(f"  Found:    {list(df.columns)}")
        print(f"\nManually specify column names by editing this script.")
        sys.exit(1)

    print(f"Using columns: router={router_col}, lat={lat_col}, lng={lng_col}")

    # Deduplicate by router name, keep first occurrence
    df = df[[router_col, lat_col, lng_col]].dropna()
    df = df.rename(columns={router_col: "router", lat_col: "lat", lng_col: "lng"})
    df = df.drop_duplicates(subset="router")

    coords = {}
    skipped = 0

    for _, row in df.iterrows():
        router = str(row["router"]).strip()
        try:
            lat = float(row["lat"])
            lng = float(row["lng"])
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                coords[router] = {"lat": round(lat, 6), "lng": round(lng, 6)}
            else:
                skipped += 1
        except (ValueError, TypeError):
            skipped += 1

    # Always include Fort Meade hub coordinates
    coords.update(FORT_MEADE_HUBS)

    print(f"Extracted {len(coords)} router coordinates ({skipped} skipped — invalid values)")
    return coords


def main():
    xlsx = Path(XLSX_FILE)
    if not xlsx.exists():
        print(f"ERROR: {XLSX_FILE} not found in current directory.")
        print(f"Run this script from the oe-ingestion-pipeline folder.")
        sys.exit(1)

    coords = extract_coordinates(str(xlsx))

    out_path = Path(OUTPUT_FILE)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(coords, f, indent=2, ensure_ascii=False)

    print(f"\nWritten: {out_path}  ({out_path.stat().st_size / 1024:.1f} KB)")
    print(f"\nNext step: copy to Angular assets folder:")
    print(f"  frontend/src/assets/data/router-coordinates.json")


if __name__ == "__main__":
    main()
