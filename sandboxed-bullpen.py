#!/usr/bin/env python3
"""Compatibility wrapper for the unified Microsandbox deployer."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    script = Path(__file__).resolve().with_name("deploy-msb.py")
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
