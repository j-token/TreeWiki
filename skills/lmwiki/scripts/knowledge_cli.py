#!/usr/bin/env python
"""Deprecated LMWiki entry point forwarding to the TreeWiki CLI."""

from __future__ import annotations

import hashlib
import runpy
import sys
from pathlib import Path

import yaml


TARGET = "scripts/knowledge_cli.py"
INSTALL_COMMAND = "npx skills add j-token/treewiki --skill treewiki -g -a codex -y --copy"


def canonical_target() -> Path:
    skill_root = Path(__file__).resolve().parents[2] / "treewiki"
    manifest_path = skill_root / "treewiki-release.yml"
    target = skill_root / TARGET
    if not manifest_path.is_file() or not target.is_file():
        raise FileNotFoundError(f"canonical TreeWiki is missing; install it with: {INSTALL_COMMAND}")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("artifacts", {}).get("files", []) if isinstance(manifest, dict) else []
    expected = next(
        (item.get("sha256") for item in files if isinstance(item, dict) and item.get("path") == TARGET),
        None,
    )
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if expected != actual:
        raise ValueError("canonical TreeWiki CLI does not match its embedded manifest")
    return target


def main() -> None:
    print(
        "WARNING $lmwiki is deprecated; use $treewiki. "
        "This compatibility shim is removed in 0.2.0.",
        file=sys.stderr,
    )
    try:
        target = canonical_target()
    except FileNotFoundError as exc:
        print(f"ERROR LEGACY_TARGET_MISSING: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR LEGACY_TARGET_INVALID: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    sys.path.insert(0, str(target.parent))
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
