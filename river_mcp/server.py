"""
River satellite MCP server.

Exposes 5 tools over the stdio transport (the transport Claude Desktop / VS Code use):

  1. list_scenes               -- inventory of local GeoTIFF scenes
  2. compute_water_mask        -- NDWI/MNDWI water mask + PNG preview
  3. measure_river_width       -- centerline width profile + statistics
  4. detect_obstruction_candidates -- candidate channel constrictions / blockages
  5. detect_crossings          -- candidate bridges/dams (gap with water on both sides)

Every tool returns a structured dict (JSON), never plain prose.

LOGGING: all logs go to STDERR via the `logging` module. This is mandatory for
stdio servers -- STDOUT carries the JSON-RPC protocol and must not be written to
with print(). Each call logs: tool name, sanitized input params, and status.

Run locally:   python -m river_mcp.server
Inspector:     mcp dev river_mcp/server.py   (or: fastmcp dev river_mcp/server.py)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

import numpy as np

from mcp.server.fastmcp import FastMCP

from river_mcp import analysis, config

# --- logging to STDERR (never stdout in a stdio server) ----------------------
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [river-mcp] %(levelname)s %(message)s",
)
log = logging.getLogger("river-mcp")

mcp = FastMCP("river-sat")


def _log_call(tool: str, params: dict, status: str, extra: str = "") -> None:
    log.info("tool=%s params=%s status=%s %s", tool, json.dumps(params), status, extra)


# --- tool 1 ------------------------------------------------------------------
@mcp.tool()
def list_scenes() -> dict:
    """List satellite GeoTIFF scenes available in the local project data directory.

    Returns metadata for each scene (size, band count, CRS, ground bounds, pixel
    size). Use the returned `name` values as the `scene` argument for other tools.
    """
    import rasterio
    try:
        scenes = []
        for name in config.list_scene_files():
            path = config.resolve_scene(name)
            with rasterio.open(path) as src:
                b = src.bounds
                scenes.append(dict(
                    name=name,
                    width_px=src.width,
                    height_px=src.height,
                    bands=src.count,
                    crs=str(src.crs),
                    pixel_size_m=round(float(abs(src.transform.a)), 3),
                    bounds=dict(left=b.left, bottom=b.bottom, right=b.right, top=b.top),
                ))
        result = dict(data_dir=config.DATA_DIR, count=len(scenes), scenes=scenes)
        _log_call("list_scenes", {}, "success", f"count={len(scenes)}")
        return result
    except Exception as e:  # noqa: BLE001
        _log_call("list_scenes", {}, "error", f"{type(e).__name__}: {e}")
        return dict(error=str(e), error_type=type(e).__name__)


# --- tool 2 ------------------------------------------------------------------
@mcp.tool()
def compute_water_mask(scene: str, index: str = "ndwi") -> dict:
    """Compute a water mask of the main river for a scene, and save a PNG preview.

    Keeps the largest connected water body (the main river) and drops separate ponds
    / wet fields; see analysis.water_mask for caveats (touching towns, wide gaps).

    Args:
        scene: bare filename of a GeoTIFF in the data dir (see list_scenes).
        index: water index to use -- "ndwi" (Green/NIR) or "mndwi" (Green/SWIR).

    Returns water fraction, the Otsu threshold used, scene bounds, and the path to
    a saved PNG preview of the mask.
    """
    params = dict(scene=scene, index=index)
    try:
        path = config.resolve_scene(scene)
        sc = analysis.load_scene(path)
        idx = analysis.water_index(sc, index)
        mask, thr = analysis.water_mask(idx)

        os.makedirs(config.OUTPUTS_DIR, exist_ok=True)
        preview = os.path.abspath(
            os.path.join(config.OUTPUTS_DIR, f"{os.path.splitext(scene)[0]}_{index}_mask.png")
        )
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.imsave(preview, mask.astype(np.uint8), cmap="gray", vmin=0, vmax=1)
            if not os.path.isfile(preview):
                raise RuntimeError("imsave returned no error but the file is missing")
            log.info("preview written: %s (%d bytes)", preview, os.path.getsize(preview))
        except Exception as ie:  # noqa: BLE001
            log.warning("preview generation FAILED, target=%s reason=%s", preview, ie)
            preview = None

        result = dict(
            scene=scene, index=index.lower(),
            otsu_threshold=round(thr, 4),
            water_fraction=round(float(mask.mean()), 5),
            water_pixels=int(mask.sum()),
            output_dir=config.OUTPUTS_DIR,
            preview_png=preview,
        )
        _log_call("compute_water_mask", params, "success",
                  f"water_fraction={result['water_fraction']}")
        return result
    except Exception as e:  # noqa: BLE001
        _log_call("compute_water_mask", params, "error", f"{type(e).__name__}: {e}")
        return dict(error=str(e), error_type=type(e).__name__)


# --- tool 3 ------------------------------------------------------------------
@mcp.tool()
def measure_river_width(scene: str, index: str = "ndwi", max_samples: int = 25) -> dict:
    """Measure the river width profile along its centerline.

    Width is estimated from the distance transform of the water mask sampled along
    the morphological skeleton, converted to metres via the scene's pixel size.
    Operates on the main river (largest connected water body).

    Args:
        scene: bare filename of a GeoTIFF in the data dir.
        index: "ndwi" or "mndwi".
        max_samples: how many evenly-spaced profile points to include in the result
            (the full profile can be thousands of points; this caps the payload).

    Returns width statistics (min/median/mean/max in metres) and a sampled profile.
    """
    params = dict(scene=scene, index=index, max_samples=max_samples)
    try:
        path = config.resolve_scene(scene)
        sc = analysis.load_scene(path)
        idx = analysis.water_index(sc, index)
        mask, _ = analysis.water_mask(idx)
        prof = analysis.width_profile(sc, mask)

        samples = prof["samples"]
        if max_samples and len(samples) > max_samples:
            step = max(1, len(samples) // max_samples)
            samples = samples[::step][:max_samples]

        result = dict(
            scene=scene, index=index.lower(),
            units="m",
            statistics=prof["stats"],
            skeleton_pixels=prof["skeleton_pixels"],
            profile_sample=samples,
        )
        _log_call("measure_river_width", params, "success",
                  f"median_m={prof['stats'].get('median_m')}")
        return result
    except Exception as e:  # noqa: BLE001
        _log_call("measure_river_width", params, "error", f"{type(e).__name__}: {e}")
        return dict(error=str(e), error_type=type(e).__name__)


# --- tool 4 ------------------------------------------------------------------
@mcp.tool()
def detect_obstruction_candidates(scene: str, index: str = "ndwi",
                                  sensitivity: float = 0.5) -> dict:
    """Detect CANDIDATE channel constrictions / blockages along the river.

    A point is flagged when its local width drops below `sensitivity * median width`.
    These are candidates for human review (e.g. possible log jams, debris dams, or
    natural narrows), NOT confirmed obstructions -- 10 m imagery cannot resolve an
    individual log jam (see README). Operates on the main river (largest water body).

    Args:
        scene: bare filename of a GeoTIFF in the data dir.
        index: "ndwi" or "mndwi".
        sensitivity: fraction of median width below which a point is flagged
            (0.5 = flag points narrower than half the median width).

    Returns a list of candidates with pixel and lon/lat coordinates, local width,
    and the drop ratio relative to median width.
    """
    params = dict(scene=scene, index=index, sensitivity=sensitivity)
    try:
        path = config.resolve_scene(scene)
        sc = analysis.load_scene(path)
        idx = analysis.water_index(sc, index)
        mask, _ = analysis.water_mask(idx)
        obs = analysis.obstruction_candidates(sc, mask, sensitivity=sensitivity)

        result = dict(
            scene=scene, index=index.lower(),
            note="candidates for human review; not confirmed obstructions",
            median_width_m=obs["median_width_m"],
            threshold_m=obs.get("threshold_m"),
            count=len(obs["candidates"]),
            candidates=obs["candidates"],
        )
        _log_call("detect_obstruction_candidates", params, "success",
                  f"count={result['count']}")
        return result
    except Exception as e:  # noqa: BLE001
        _log_call("detect_obstruction_candidates", params, "error", f"{type(e).__name__}: {e}")
        return dict(error=str(e), error_type=type(e).__name__)


@mcp.tool()
def detect_crossings(scene: str, index: str = "ndwi", max_gap_px: int = 10) -> dict:
    """Detect candidate bridges / dams / causeways crossing the river.

    Finds gaps that interrupt the water mask but have water on BOTH sides, i.e. the
    river continues past them. Useful when a bridge splits the channel in the mask.
    These are candidates for human review (a wide sandbar or turbid stretch can look
    similar from 10 m imagery), not confirmed structures.

    Args:
        scene: bare filename of a GeoTIFF in the data dir.
        index: "ndwi" or "mndwi".
        max_gap_px: widest gap (in pixels) to treat as a possible crossing
            (10 px = 100 m at Sentinel-2 resolution).

    Returns a list of crossings with pixel and lon/lat coordinates and the gap length.
    """
    params = dict(scene=scene, index=index, max_gap_px=max_gap_px)
    try:
        path = config.resolve_scene(scene)
        sc = analysis.load_scene(path)
        res = analysis.detect_crossings(sc, index, max_gap_px=max_gap_px)
        result = dict(
            scene=scene, index=index.lower(),
            note="possible crossings (bridge/dam); river continues across each",
            count=len(res.get("crossings", [])),
            crossings=res.get("crossings", []),
        )
        _log_call("detect_crossings", params, "success", f"count={result['count']}")
        return result
    except Exception as e:  # noqa: BLE001
        _log_call("detect_crossings", params, "error", f"{type(e).__name__}: {e}")
        return dict(error=str(e), error_type=type(e).__name__)


if __name__ == "__main__":
    log.info("starting river-sat MCP server (stdio); data_dir=%s", config.DATA_DIR)
    mcp.run()