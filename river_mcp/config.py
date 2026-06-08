"""
Configuration and path-safety for the river MCP server.

SECURITY: every tool that touches the filesystem accepts only a bare scene NAME
(e.g. "synthetic_river.tif"), never a path. resolve_scene() joins it with DATA_DIR,
resolves symlinks/.. and verifies the result is still inside DATA_DIR. Anything that
escapes the sandbox raises PermissionError. Outputs (previews) go only to OUTPUTS_DIR.
"""
from __future__ import annotations

import os

# Project root = parent of this package directory.
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Sandbox: the ONLY directory tools are allowed to read scenes from.
DATA_DIR = os.environ.get("RIVER_MCP_DATA_DIR", os.path.join(PROJECT_ROOT, "data"))
DATA_DIR = os.path.realpath(DATA_DIR)

# The ONLY directory tools may write preview images to.
OUTPUTS_DIR = os.path.join(DATA_DIR, "outputs")

ALLOWED_EXTS = {".tif", ".tiff"}


def resolve_scene(name: str) -> str:
    """Map a bare scene name to an absolute path inside DATA_DIR, or raise."""
    if not name or os.path.isabs(name) or os.sep in name or (os.altsep and os.altsep in name):
        raise PermissionError(f"scene must be a bare filename inside the data dir, got: {name!r}")
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise PermissionError(f"unsupported extension {ext!r}; allowed: {sorted(ALLOWED_EXTS)}")
    candidate = os.path.realpath(os.path.join(DATA_DIR, name))
    if os.path.commonpath([candidate, DATA_DIR]) != DATA_DIR:
        raise PermissionError("path traversal blocked: scene escapes the data directory")
    if not os.path.isfile(candidate):
        raise FileNotFoundError(f"scene not found in data dir: {name}")
    return candidate


def list_scene_files() -> list[str]:
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(
        f for f in os.listdir(DATA_DIR)
        if os.path.splitext(f)[1].lower() in ALLOWED_EXTS
        and os.path.isfile(os.path.join(DATA_DIR, f))
    )
