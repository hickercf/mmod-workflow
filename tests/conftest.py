# -*- coding: utf-8 -*-
"""pytest bootstrap: keep all temp files inside the workspace (sandbox-safe)."""

from __future__ import annotations

import tempfile
from pathlib import Path

_workspace_root = Path(__file__).resolve().parent
_temp_root = _workspace_root / "tmp" / "pytest-root"
_temp_root.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(_temp_root)
