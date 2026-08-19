#!/usr/bin/env python
"""Create a non-destructive TreeWiki repository skeleton."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

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
    "docs/memory/l1",
    "docs/memory/l2",
    "docs/memory/l3",
    "docs/memory/l3/knowledge",
    "docs/memory/l3/persona",
    ".knowledge",
    ".knowledge/index",
    ".knowledge/hooks",
    ".knowledge/hooks/state",
    ".knowledge/private-memory/l0",
]

CONFIG_VERSION = 4
MEMORY_LAYOUT_VERSION = 2
PRIVATE_MEMORY_PATH = ".knowledge/private-memory"
SHARED_MEMORY_PATH = "docs/memory"


def _finalize_initial_documents(root: Path, created_paths: list[str]) -> None:
    from document_history import apply_document_plan, parse_document, plan_documents
    from validate_knowledge import managed_documents

    config = yaml.safe_load((root / ".knowledge" / "config.yml").read_text(encoding="utf-8"))
    documents = managed_documents(root, config)
    created_ids: list[str] = []
    created_set = set(created_paths)
    for document in documents:
        relative = document.relative_to(root).as_posix()
        if relative not in created_set:
            continue
        metadata, _, _ = parse_document(document)
        if isinstance(metadata.get("id"), str):
            created_ids.append(metadata["id"])
    plan = plan_documents(
        root,
        documents,
        actor="agent:treewiki-bootstrap",
        created_ids=created_ids,
        reason="TreeWiki bootstrap",
    )
    apply_document_plan(root, plan, plan_id=str(plan["plan_id"]))


def _existing_config_is_compatible(config_target: Path) -> bool:
    """Reject legacy configs rather than silently assigning them the current layout."""
    try:
        loaded: Any = yaml.safe_load(config_target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        print(f"ERROR cannot read existing .knowledge/config.yml: {exc}", file=sys.stderr)
        return False

    if not isinstance(loaded, dict):
        print("ERROR existing .knowledge/config.yml must contain a mapping", file=sys.stderr)
        return False

    version = loaded.get("version")
    if version != CONFIG_VERSION:
        if isinstance(version, int) and not isinstance(version, bool) and version < CONFIG_VERSION:
            print(
                "UPGRADE REQUIRED: existing .knowledge/config.yml "
                f"uses config version {version}; bootstrap_treewiki.py will not "
                "reinterpret it as the v4 memory layout. Run the approved v4 "
                "upgrade, then run bootstrap again.",
                file=sys.stderr,
            )
        else:
            print(
                "ERROR existing .knowledge/config.yml "
                f"has incompatible config version {version!r}; this bootstrap "
                f"requires version {CONFIG_VERSION}.",
                file=sys.stderr,
            )
        return False

    memory = loaded.get("memory")
    if not isinstance(memory, dict) or any(
        (
            memory.get("layout_version") != MEMORY_LAYOUT_VERSION,
            memory.get("private_path") != PRIVATE_MEMORY_PATH,
            memory.get("shared_path") != SHARED_MEMORY_PATH,
        )
    ):
        print(
            "ERROR existing config version 4 does not declare the required "
            "memory.layout_version 2 private/shared layout; use the approved "
            "upgrade or repair workflow before bootstrapping.",
            file=sys.stderr,
        )
        return False
    return True


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

    config_target = root / ".knowledge" / "config.yml"
    if config_target.exists() and not _existing_config_is_compatible(config_target):
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
        "docs/vocabulary/glossary.yml": assets / "glossary.yml",
        ".knowledge/purpose.md": assets / "purpose.md",
        ".knowledge/schema.md": assets / "schema.md",
        ".knowledge/.gitignore": assets / "knowledge.gitignore",
        ".knowledge/private-memory/.gitignore": assets / "private-memory.gitignore",
        ".knowledge/index/.gitignore": assets / "index.gitignore",
        ".knowledge/hooks/state/.gitignore": assets / "hook-state.gitignore",
        ".agents/skills/.gitignore": assets / "skill-backups.gitignore",
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

    if not args.dry_run:
        _finalize_initial_documents(root, created)

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
