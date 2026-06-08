"""Run the analysis pipeline standalone (no MCP) for debugging.

Usage:  python scripts/run_local_demo.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from river_mcp import analysis  # noqa: E402

DATA = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "synthetic_river.tif"))


def main() -> None:
    scene = analysis.load_scene(DATA)
    print(f"scene: {scene.width}x{scene.height}px  pixel={scene.pixel_size_m} m  crs={scene.crs}")

    for kind in ("ndwi", "mndwi"):
        idx = analysis.water_index(scene, kind)
        mask, thr = analysis.water_mask(idx)
        prof = analysis.width_profile(scene, mask)
        obs = analysis.obstruction_candidates(scene, mask, sensitivity=0.6)
        print(f"\n=== {kind.upper()} (otsu thr={thr:.3f}) ===")
        print("  water fraction:", round(float(mask.mean()), 4))
        print("  width stats   :", json.dumps(prof["stats"]))
        print(f"  obstruction candidates ({len(obs['candidates'])}):")
        for c in obs["candidates"]:
            print("   ", json.dumps(c))


if __name__ == "__main__":
    main()
