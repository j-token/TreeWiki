#!/usr/bin/env python
"""Create a non-destructive LMWiki repository skeleton."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR PyYAML is required; install scripts/requirements.txt", file=sys.stderr)
    raise SystemExit(2)


DIRECTORIES = [
    "docs/contracts",
    "docs/decisions",
    "docs/runbooks",
    "docs/concepts",
    "docs/references",
    "docs/vocabulary",
    "docs/memory/l2",
    ".knowledge",
    ".knowledge/index",
    ".knowledge/hooks",
    ".knowledge/hooks/state",
    ".knowledge/private-memory/l0",
    ".knowledge/private-memory/l1",
    ".knowledge/private-memory/l2",
    ".knowledge/private-memory/l3",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", nargs="?", default=".")
    parser.add_argument("--embedding", choices=["disabled", "local", "remote"], required=True)
    parser.add_argument("--remote-content-allowed", action="store_true")
    parser.add_argument("--owner", default="user:owner")
    parser.add_argument("--team", default="team:repository")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.embedding == "remote" and not args.remote_content_allowed:
        print("ERROR remote embedding requires --remote-content-allowed")
        return 1

    root = Path(args.repository).resolve()
    skill_root = Path(__file__).resolve().parents[1]
    assets = skill_root / "assets"
    if not root.exists() or not root.is_dir():
        print(f"ERROR repository directory not found: {root}")
        return 1

    created: list[str] = []
    skipped: list[str] = []

    for relative in DIRECTORIES:
        target = root / relative
        if target.exists():
            continue
        if not args.dry_run:
            target.mkdir(parents=True, exist_ok=True)
        created.append(relative + "/")

    text_files = {
        "AGENTS.md": assets / "AGENTS.md",
        "docs/vocabulary/topics.yml": assets / "topics.yml",
        ".knowledge/purpose.md": assets / "purpose.md",
        ".knowledge/schema.md": assets / "schema.md",
        ".knowledge/private-memory/.gitignore": assets / "private-memory.gitignore",
        ".knowledge/index/.gitignore": assets / "index.gitignore",
        ".knowledge/hooks/state/.gitignore": assets / "hook-state.gitignore",
    }
    for relative, source in text_files.items():
        target = root / relative
        if target.exists():
            skipped.append(relative)
            continue
        content = source.read_text(encoding="utf-8").replace("YYYY-MM-DD", date.today().isoformat())
        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        created.append(relative)

    config_target = root / ".knowledge" / "config.yml"
    if config_target.exists():
        skipped.append(".knowledge/config.yml")
    else:
        with (assets / "config.yml").open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        embedding = config["embedding"]
        embedding["enabled"] = args.embedding != "disabled"
        embedding["execution"] = "none" if args.embedding == "disabled" else args.embedding
        embedding["remote_content_allowed"] = bool(args.remote_content_allowed)
        config["retrieval"]["bm25_enabled"] = args.embedding != "disabled"
        config["access_control"]["default_owner"] = args.owner
        config["access_control"]["default_team"] = args.team
        config["access_control"]["managers"] = [args.owner]
        if not args.dry_run:
            config_target.parent.mkdir(parents=True, exist_ok=True)
            with config_target.open("w", encoding="utf-8", newline="\n") as handle:
                yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)
        created.append(".knowledge/config.yml")

    principals_target = root / ".knowledge" / "principals.yml"
    if principals_target.exists():
        skipped.append(".knowledge/principals.yml")
    else:
        with (assets / "principals.yml").open("r", encoding="utf-8") as handle:
            principals = yaml.safe_load(handle)
        principals["team"] = args.team
        principals["users"] = [args.owner]
        if not args.dry_run:
            with principals_target.open("w", encoding="utf-8", newline="\n") as handle:
                yaml.safe_dump(principals, handle, allow_unicode=True, sort_keys=False)
        created.append(".knowledge/principals.yml")

    mode = "DRY-RUN" if args.dry_run else "CREATED"
    print(f"{mode} {len(created)} paths")
    for path in created:
        print(f"  + {path}")
    print(f"SKIPPED {len(skipped)} existing files")
    for path in skipped:
        print(f"  = {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
