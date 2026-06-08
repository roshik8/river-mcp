# Tool outputs contract

Every tool returns a single JSON object (a Python `dict`), never plain prose.
On failure a tool returns `{"error": "<message>", "error_type": "<ExceptionClass>"}`
instead of raising, so the agent always receives a structured result.

Coordinate conventions: `row`/`col` are pixel indices (0-based, row 0 = top).
`lon`/`lat` are WGS84 degrees (EPSG:4326). Widths are in metres.

---

## `list_scenes() -> object`
```jsonc
{
  "data_dir": "string",          // absolute path of the sandbox directory
  "count": 1,
  "scenes": [
    {
      "name": "synthetic_river.tif",
      "width_px": 512, "height_px": 512,
      "bands": 4,
      "crs": "EPSG:32633",
      "pixel_size_m": 10.0,
      "bounds": { "left": 0, "bottom": 0, "right": 0, "top": 0 }  // scene CRS units
    }
  ]
}
```

## `compute_water_mask(scene, index="ndwi") -> object`
```jsonc
{
  "scene": "synthetic_river.tif",
  "index": "ndwi",               // "ndwi" | "mndwi"
  "otsu_threshold": -0.5696,     // threshold chosen by Otsu on the index
  "water_fraction": 0.01969,     // fraction of pixels classified as water (0..1)
  "water_pixels": 5161,
  "preview_png": "string|null"   // path to a saved PNG of the mask (null if skipped)
}
```

## `measure_river_width(scene, index="ndwi", max_samples=25) -> object`
```jsonc
{
  "scene": "synthetic_river.tif",
  "index": "ndwi",
  "units": "m",
  "statistics": {
    "n_samples": 321,            // total centerline points measured
    "min_m": 20.0, "median_m": 141.42, "mean_m": 135.68, "max_m": 220.0
  },
  "skeleton_pixels": 321,
  "profile_sample": [            // down-sampled to <= max_samples points
    { "row": 54, "col": 290, "width_m": 205.91, "lon": 13.4218, "lat": 52.5147 }
  ]
}
```

## `detect_obstruction_candidates(scene, index="ndwi", sensitivity=0.5) -> object`
```jsonc
{
  "scene": "synthetic_river.tif",
  "index": "ndwi",
  "note": "candidates for human review; not confirmed obstructions",
  "median_width_m": 141.42,
  "threshold_m": 84.85,          // sensitivity * median_width_m
  "count": 3,
  "candidates": [
    {
      "row": 251, "col": 223,
      "lon": 13.4126, "lat": 52.4968,
      "local_width_m": 20.0,
      "drop_ratio": 0.141,       // local_width_m / median_width_m (lower = stronger)
      "feature_type": "channel_constriction"
    }
  ]
}
```
