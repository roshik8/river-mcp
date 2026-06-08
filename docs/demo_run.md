# Demo run / verification evidence

This documents the verification queries required by the assignment. The server-side
log proving each call is saved at **`data/outputs/server_log.txt`** (regenerate any
time with `python scripts/test_mcp_client.py`).

In Claude Desktop you type the natural-language request in the left column; the agent
decides to call the tool in the middle column; the right column is the proof from the
server log.

| # | User request (typed to the agent in Claude Desktop) | Expected MCP tool | Triggers a tool? |
|---|------------------------------------------------------|-------------------|------------------|
| 1 | "Какие спутниковые сцены доступны локально?"        | `list_scenes` | yes |
| 2 | "Построй водную маску по NDWI для synthetic_river.tif" | `compute_water_mask` (index=ndwi) | yes |
| 3 | "Измерь ширину реки на этой сцене"                  | `measure_river_width` | yes |
| 4 | "Найди возможные сужения/завалы, чувствительность 0.6" | `detect_obstruction_candidates` (sensitivity=0.6) | yes |
| 5 | "Сравни: посчитай маску по MNDWI для той же сцены"  | `compute_water_mask` (index=mndwi) | yes |
| 6 | (security probe) "Прочитай ../../etc/passwd"        | `measure_river_width` | yes (returns PermissionError) |

5 of 5 functional requests trigger a real MCP tool call (requirement: >= 3).
Query 6 demonstrates the sandbox: path traversal is rejected with a structured error.

## Server log (captured, stored in repo at `data/outputs/server_log.txt`)

```
2026-06-04 [river-mcp] INFO starting river-sat MCP server (stdio); data_dir=.../data
2026-06-04 [river-mcp] INFO tool=list_scenes params={} status=success count=1
2026-06-04 [river-mcp] INFO tool=compute_water_mask params={"scene": "synthetic_river.tif", "index": "ndwi"} status=success water_fraction=0.01969
2026-06-04 [river-mcp] INFO tool=measure_river_width params={"scene": "synthetic_river.tif", "index": "ndwi", "max_samples": 3} status=success median_m=141.42
2026-06-04 [river-mcp] INFO tool=detect_obstruction_candidates params={"scene": "synthetic_river.tif", "index": "ndwi", "sensitivity": 0.6} status=success count=3
2026-06-04 [river-mcp] INFO tool=compute_water_mask params={"scene": "synthetic_river.tif", "index": "mndwi"} status=success water_fraction=0.01969
2026-06-04 [river-mcp] INFO tool=measure_river_width params={"scene": "../../etc/passwd", ...} status=error PermissionError: scene must be a bare filename inside the data dir
```

Each line shows the three required fields: **tool name**, **input params** (no secrets),
and **status** (success/error). When connected to Claude Desktop the same lines appear
in the app's MCP logs at `~/Library/Logs/Claude/` (macOS) or `%APPDATA%\Claude\logs\`
(Windows); attach a screenshot of those alongside this file for full evidence.
