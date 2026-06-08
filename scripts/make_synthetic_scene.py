"""
Generate a synthetic Sentinel-2-like GeoTIFF for the river MCP demo.

Why synthetic: real Sentinel-2 / Copernicus tiles cannot be downloaded inside the
sandbox, and committing large real rasters is impractical for a homework repo.
The synthetic scene exercises the FULL analysis pipeline for real (NDWI -> mask ->
width -> obstruction candidates), is deterministic, needs no API keys, and can be
swapped for a real tile (see README "Using real imagery").

Output: data/synthetic_river.tif
  4 float32 bands, reflectance 0..1, in this order:
    band 1 = GREEN  (Sentinel-2 B03)
    band 2 = RED    (Sentinel-2 B04)
    band 3 = NIR    (Sentinel-2 B08)
    band 4 = SWIR   (Sentinel-2 B11)
  CRS = EPSG:32633 (UTM 33N), pixel size = 10 m (matches S-2 10 m bands).
"""
from __future__ import annotations

import os
import numpy as np
import rasterio
from rasterio.transform import from_origin

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(HERE, "..", "data"))
OUT_PATH = os.path.join(DATA_DIR, "synthetic_river.tif")

H, W = 512, 512
PIXEL_SIZE_M = 10.0
# An arbitrary but plausible UTM 33N origin (easting, northing of top-left corner).
ORIGIN_X, ORIGIN_Y = 390000.0, 5820000.0
SEED = 42


def _spectra():
    """Mean reflectance for (green, red, nir, swir) for water and land."""
    water = np.array([0.085, 0.050, 0.020, 0.012], dtype=np.float32)
    land = np.array([0.060, 0.055, 0.340, 0.210], dtype=np.float32)
    return water, land


def build_scene() -> np.ndarray:
    rng = np.random.default_rng(SEED)
    rows = np.arange(H)
    cols = np.arange(W)
    cc, rr = np.meshgrid(cols, rows)  # cc=x index, rr=y index

    # Meandering centerline: x position of channel center as a function of row.
    center_x = (
        W / 2.0
        + 70.0 * np.sin(rows / 70.0)
        + 30.0 * np.sin(rows / 23.0 + 1.3)
    )

    # Half-width of the channel (in pixels) varying gently along the river.
    half_width = 9.0 + 2.5 * np.sin(rows / 90.0 + 0.5)

    # Inject two pinch points (sharp narrowing) -> width-drop obstructions.
    for y0, depth in [(150, 0.62), (360, 0.66)]:
        half_width = half_width - depth * half_width * np.exp(-((rows - y0) ** 2) / (2 * 6.0 ** 2))

    half_width = np.clip(half_width, 1.0, None)

    # Water mask = distance from centerline (per row) < half_width.
    dist_from_center = np.abs(cc - center_x[:, None])
    water = dist_from_center < half_width[:, None]

    # A vegetation bar sitting IN the channel (a debris/log-jam-like blockage).
    veg_bar = (
        (np.abs(rr - 255) < 4)
        & (np.abs(cc - center_x[255]) < half_width[255] + 1)
    )
    water = water & ~veg_bar

    water_s, land_s = _spectra()
    scene = np.empty((4, H, W), dtype=np.float32)
    for b in range(4):
        layer = np.where(water, water_s[b], land_s[b]).astype(np.float32)
        noise = rng.normal(0.0, 0.006, size=(H, W)).astype(np.float32)
        scene[b] = np.clip(layer + noise, 0.0, 1.0)
    return scene


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    scene = build_scene()
    transform = from_origin(ORIGIN_X, ORIGIN_Y, PIXEL_SIZE_M, PIXEL_SIZE_M)
    profile = dict(
        driver="GTiff",
        height=H,
        width=W,
        count=4,
        dtype="float32",
        crs="EPSG:32633",
        transform=transform,
        compress="deflate",
    )
    with rasterio.open(OUT_PATH, "w", **profile) as dst:
        dst.write(scene)
        dst.set_band_description(1, "green_B03")
        dst.set_band_description(2, "red_B04")
        dst.set_band_description(3, "nir_B08")
        dst.set_band_description(4, "swir_B11")
    print(f"Wrote {OUT_PATH}  shape={scene.shape}  crs=EPSG:32633  pixel={PIXEL_SIZE_M} m")


if __name__ == "__main__":
    main()
