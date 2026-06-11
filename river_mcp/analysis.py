"""
Core geospatial analysis for the river MCP server.

Pure functions, no MCP imports -- so the pipeline can be debugged standalone
(see scripts/run_local_demo.py). Methods used:

  * Water index : NDWI = (Green - NIR) / (Green + NIR)        [McFeeters 1996]
                  MNDWI = (Green - SWIR) / (Green + SWIR)      [Xu 2006, better for
                  turbid / sediment-laden river water]
  * Threshold   : Otsu (skimage.filters.threshold_otsu)
  * Width       : Euclidean distance transform of the water mask sampled along the
                  morphological skeleton (centerline). width = 2 * dist * pixel_size.
  * Obstruction : local minima in the width profile below `sensitivity * median`,
                  i.e. candidate channel constrictions / blockages. NOTE these are
                  CANDIDATES for human review, not confirmed log jams (see README).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform
from scipy import ndimage
from skimage.filters import threshold_otsu
from skimage.morphology import skeletonize

# Band order in the GeoTIFF produced by make_synthetic_scene.py and expected for
# real Sentinel-2 stacks: 1=green, 2=red, 3=nir, 4=swir.
BAND_GREEN, BAND_RED, BAND_NIR, BAND_SWIR = 1, 2, 3, 4


@dataclass
class Scene:
    green: np.ndarray
    nir: np.ndarray
    swir: np.ndarray
    transform: rasterio.Affine
    crs: object
    pixel_size_m: float
    width: int
    height: int


def load_scene(path: str) -> Scene:
    with rasterio.open(path) as src:
        green = src.read(BAND_GREEN).astype(np.float32)
        nir = src.read(BAND_NIR).astype(np.float32)
        swir = src.read(BAND_SWIR).astype(np.float32)
        px = float(abs(src.transform.a))
        return Scene(green, nir, swir, src.transform, src.crs, px, src.width, src.height)


def water_index(scene: Scene, kind: str = "ndwi") -> np.ndarray:
    kind = kind.lower()
    if kind == "ndwi":
        a, b = scene.green, scene.nir
    elif kind == "mndwi":
        a, b = scene.green, scene.swir
    else:
        raise ValueError(f"unknown index '{kind}', use 'ndwi' or 'mndwi'")
    return (a - b) / (a + b + 1e-9)


def water_mask(index: np.ndarray, min_blob_pixels: int = 64):
    """Otsu-threshold the index into a water mask of the MAIN RIVER.

    NaN-safe: Otsu is computed only over finite pixels; NaN is treated as non-water.
    A morphological closing bridges thin gaps (bridges, sandbars, short turbid
    stretches) so the channel does not get severed, then only the SINGLE LARGEST
    connected component is kept -- i.e. the main river. Separate water bodies
    (isolated ponds, distant wet fields) are dropped.

    Caveats: a wide gap the closing cannot bridge may split the river, leaving only
    the larger piece; and a town that physically touches the river stays (it is one
    connected blob with the channel) -- pick an AOI without the town to avoid it,
    since morphology cannot separate spectrally-similar, touching features.
    """
    finite = np.isfinite(index)
    if not finite.any():
        return np.zeros(index.shape, dtype=bool), float("nan")
    thr = float(threshold_otsu(index[finite]))
    binary = (index > thr) & finite
    # Bridge thin gaps so a bridge/sandbar/turbid stretch doesn't sever the channel.
    binary = ndimage.binary_closing(binary, structure=np.ones((3, 3)), iterations=2)
    binary &= finite  # closing must not invent water inside nodata areas
    labels, n = ndimage.label(binary)
    if n == 0:
        return np.zeros(index.shape, dtype=bool), thr
    sizes = ndimage.sum(np.ones_like(labels), labels, index=range(1, n + 1))
    biggest = int(np.argmax(sizes)) + 1  # largest connected component = the river
    if sizes[biggest - 1] < min_blob_pixels:
        return np.zeros(index.shape, dtype=bool), thr
    return labels == biggest, thr


def _to_lonlat(scene: Scene, cols, rows):
    xs, ys = rasterio.transform.xy(scene.transform, rows, cols, offset="center")
    xs = np.atleast_1d(xs)
    ys = np.atleast_1d(ys)
    lon, lat = warp_transform(scene.crs, "EPSG:4326", list(xs), list(ys))
    return np.array(lon), np.array(lat)


def width_profile(scene: Scene, mask: np.ndarray):
    """Return centerline width profile (in metres) ordered along the river."""
    dist_px = ndimage.distance_transform_edt(mask)
    skel = skeletonize(mask)
    rows, cols = np.nonzero(skel)
    if rows.size == 0:
        return dict(samples=[], stats={}, skeleton_pixels=0)

    order = np.argsort(rows)  # river runs roughly top->bottom in the demo scene
    rows, cols = rows[order], cols[order]
    width_m = 2.0 * dist_px[rows, cols] * scene.pixel_size_m

    lon, lat = _to_lonlat(scene, cols, rows)
    samples = [
        dict(row=int(r), col=int(c), width_m=round(float(w), 2),
             lon=round(float(lo), 6), lat=round(float(la), 6))
        for r, c, w, lo, la in zip(rows, cols, width_m, lon, lat)
    ]
    stats = dict(
        n_samples=int(width_m.size),
        min_m=round(float(width_m.min()), 2),
        median_m=round(float(np.median(width_m)), 2),
        mean_m=round(float(width_m.mean()), 2),
        max_m=round(float(width_m.max()), 2),
    )
    return dict(samples=samples, stats=stats, skeleton_pixels=int(rows.size))


def obstruction_candidates(scene: Scene, mask: np.ndarray, sensitivity: float = 0.5,
                           border_margin_px: int = 6, row_gap_px: int = 10):
    """
    Flag centerline points where local width drops below sensitivity * median width.
    Flagged points within `row_gap_px` of each other are clustered into ONE candidate
    (its narrowest point). Points within `border_margin_px` of the image edge are
    skipped (skeleton endpoints there underestimate width). Returns candidates for
    HUMAN REVIEW, not confirmed obstructions (see README).
    """
    prof = width_profile(scene, mask)
    samples = prof["samples"]
    if not samples:
        return dict(candidates=[], median_width_m=None, sensitivity=sensitivity)

    widths = np.array([s["width_m"] for s in samples])
    median = float(np.median(widths))
    threshold = sensitivity * median

    flagged = [
        s for i, s in enumerate(samples)
        if widths[i] < threshold
        and border_margin_px <= s["row"] < scene.height - border_margin_px
        and border_margin_px <= s["col"] < scene.width - border_margin_px
    ]

    candidates = []
    cluster = []

    def flush(group):
        if not group:
            return
        s = min(group, key=lambda t: t["width_m"])
        candidates.append(dict(
            row=s["row"], col=s["col"], lon=s["lon"], lat=s["lat"],
            local_width_m=s["width_m"],
            drop_ratio=round(float(s["width_m"] / median), 3),
            feature_type="channel_constriction",
        ))

    prev_row = None
    for s in flagged:
        if prev_row is not None and abs(s["row"] - prev_row) > row_gap_px:
            flush(cluster)
            cluster = []
        cluster.append(s)
        prev_row = s["row"]
    flush(cluster)

    return dict(
        candidates=candidates,
        median_width_m=round(median, 2),
        threshold_m=round(threshold, 2),
        sensitivity=sensitivity,
    )


def detect_crossings(scene: Scene, kind: str = "ndwi", max_gap_px: int = 10,
                     min_blob_pixels: int = 64):
    """Find gaps that interrupt the channel but have water on BOTH sides.

    Such a gap is a candidate bridge / dam / causeway: the river continues past it,
    but a non-water structure breaks the water mask. Method: threshold to raw water,
    keep water bodies above min size, morphologically bridge gaps up to ~max_gap_px,
    and inspect what got filled -- a filled patch that joins two distinct water bodies
    is reported as a crossing. These are CANDIDATES for human review (a wide turbid
    stretch or sandbar can look the same from 10 m imagery), not confirmed bridges.
    """
    idx = water_index(scene, kind)
    finite = np.isfinite(idx)
    if not finite.any():
        return dict(crossings=[], note="no valid (non-NaN) pixels in scene")
    thr = float(threshold_otsu(idx[finite]))
    raw = (idx > thr) & finite

    rawlab, rn = ndimage.label(raw)
    if rn == 0:
        return dict(crossings=[], threshold=round(thr, 4))
    sizes = ndimage.sum(np.ones_like(rawlab), rawlab, index=range(1, rn + 1))
    keep = np.where(sizes >= min_blob_pixels)[0] + 1
    raw_big = np.isin(rawlab, keep)
    rawlab_big, _ = ndimage.label(raw_big)

    structure = np.ones((3, 3))
    iters = max(1, max_gap_px // 2)
    closed = ndimage.binary_closing(raw_big, structure=structure, iterations=iters) & finite
    filled = closed & ~raw_big

    flab, fn = ndimage.label(filled)
    crossings = []
    for i in range(1, fn + 1):
        comp = flab == i
        if comp.sum() < 2:
            continue
        touching = set(int(x) for x in np.unique(rawlab_big[ndimage.binary_dilation(comp, structure) & raw_big]) if x != 0)
        if len(touching) >= 2:  # the gap connects two separate water bodies => crossing
            rows, cols = np.nonzero(comp)
            r, c = int(round(rows.mean())), int(round(cols.mean()))
            gap_len_px = max(rows.max() - rows.min() + 1, cols.max() - cols.min() + 1)
            lon, lat = _to_lonlat(scene, [c], [r])
            crossings.append(dict(
                row=r, col=c,
                lon=round(float(lon[0]), 6), lat=round(float(lat[0]), 6),
                gap_length_m=round(float(gap_len_px) * scene.pixel_size_m, 1),
                feature_type="possible_crossing",
                note="water present on both sides -- river continues across this gap",
            ))
    return dict(crossings=crossings, threshold=round(thr, 4), max_gap_px=max_gap_px)
