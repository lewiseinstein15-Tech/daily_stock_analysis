#!/usr/bin/env python3
"""Export the safe, read-only Jexi OS MCP tool manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.agent.mcp_manifest import build_default_mcp_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="jexi-mcp-manifest.json")
    args = parser.parse_args()
    manifest = build_default_mcp_manifest()
    output = Path(args.output)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(manifest['tools'])} read-only MCP tool descriptors to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
