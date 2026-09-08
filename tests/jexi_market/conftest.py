# -*- coding: utf-8 -*-
"""Pytest configuration for JEXI Market tests."""

import os
import sys
from pathlib import Path

# Ensure the repo root is on the path so `import jexi_market` works.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Force offline / no-push mode for all tests by default.
os.environ.setdefault("JEXI_LIVE_TRADING_ENABLED", "0")
os.environ.setdefault("JEXI_RESEARCH_BACKEND", "off")
os.environ.setdefault("JEXI_MCP_ENABLED", "0")
os.environ.setdefault("JEXI_MEMORY_DB", ":memory:")
