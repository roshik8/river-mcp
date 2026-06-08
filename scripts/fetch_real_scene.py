"""
Download a REAL Sentinel-2 scene over a river and save it as a 4-band GeoTIFF in
the exact band order the MCP server expects (green, red, nir, swir).

Source: Microsoft Planetary Computer (STAC). No account / API key required -- asset
URLs are signed automatically by the `planetary_computer` package.

Requires the optional download dependencies:
    pip install -r requirements-download.txt

Usage (defaults to a meandering reach of the Oder/Odra river near Frankfurt (Oder)):
    python scripts/fetch_real_scene.py
Custom area / date:
    python scripts/fetch_real_scene.py \
        --bbox 14.50 52.30 14.62 52.40 \
        --date 2023-06-01/2023-09-30 \
        --max-cloud 10 \
        --name oder_river.tif

Get a bbox easily: draw a rectangle at https://bboxfinder.com (it outputs
"minx,miny,maxx,maxy" in WGS84 lon/lat) or in the Copernicus Browser.

NOTE on resolution: Sentinel-2 is 10 m/pixel (B11/SWIR is 20 m, resampled to 10 m
here). Good for river WIDTH; individual log jams are sub-pixel and not resolvable.
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import planetary_computer
import pystac_client
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
# Sentinel-2 L2A asset keys -> output band order required by river_mcp/analysis.py
BAND_KEYS = ["B03", "B04", "B08", "B11"]  # green, red, nir, swir
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data"))

# Sentinel-2 L2A: surface reflectance = (DN - BOA_OFFSET) / 10000 for processing
# baseline >= 04.00. For NDWI/MNDWI (band ratios) the exact scaling is non-critical,
# but we harmonize anyway so values land in a sensible 0..1 range.
SCALE = 10000.0
BOA_OFFSET = 1000.0


def parse_args():
    p = argparse.ArgumentParser(description="Fetch a real Sentinel-2 river scene.")
    p.add_argument("--bbox", nargs=4, type=float,
                   metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"),
                   default=[14.50, 52.30, 14.62, 52.40],
                   help="WGS84 bounding box (lon/lat). Default: Oder near Frankfurt (Oder).")
    p.add_argument("--date", default="2023-06-01/2023-09-30",
                   help="ISO date or range (default: summer 2023).")
    p.add_argument("--max-cloud", type=int, default=10,
                   help="Max scene cloud cover %% (default: 10).")
    p.add_argument("--name", default="oder_river.tif",
                   help="Output filename written into data/ (default: oder_river.tif).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    minlon, minlat, maxlon, maxlat = args.bbox

    catalog = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=args.bbox,
        datetime=args.date,
        query={"eo:cloud_cover": {"lt": args.max_cloud}},
    )
    items = sorted(search.items(), key=lambda it: it.properties.get("eo:cloud_cover", 100))
    if not items:
        raise SystemExit("No matching scenes. Widen --date or raise --max-cloud.")
    item = items[0]
    print(f"Selected {item.id}  cloud={item.properties.get('eo:cloud_cover')}%  "
          f"date={item.properties.get('datetime')}")

    # Open each band, clip to the bbox (in WGS84), and align all bands to the 10 m
    # grid of the green band (resamples 20 m SWIR up to 10 m).
    ref = None
    layers = []
    for key in BAND_KEYS:
        href = item.assets[key].href
        da = rioxarray.open_rasterio(href, masked=True).squeeze("band", drop=True)
        da = da.rio.clip_box(minlon, minlat, maxlon, maxlat, crs="EPSG:4326")
        if ref is None:
            ref = da
        else:
            da = da.rio.reproject_match(ref)
        layers.append(da)
        print(f"  {key}: {da.rio.width}x{da.rio.height}px")

    stack = xr.concat(layers, dim="band")
    stack = stack.assign_coords(band=[1, 2, 3, 4])
    # Harmonize to reflectance (float32). Ratios are robust to this, but keep tidy.
    stack = ((stack - BOA_OFFSET) / SCALE).clip(min=0).astype("float32")

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, args.name)
    stack.rio.to_raster(out_path, compress="deflate")

    # Annotate band descriptions to match the server's expectations.
    import rasterio
    with rasterio.open(out_path, "r+") as dst:
        for i, name in enumerate(["green_B03", "red_B04", "nir_B08", "swir_B11"], start=1):
            dst.set_band_description(i, name)

    print(f"\nWrote {out_path}  bands=green,red,nir,swir  crs={stack.rio.crs}")
    print(f"Now run the MCP tools with scene=\"{args.name}\" (try index=\"mndwi\").")


if __name__ == "__main__":
    main()
