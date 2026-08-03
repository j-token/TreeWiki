#!/usr/bin/env python
"""Validate AGENTS.md maps and managed Markdown knowledge documents."""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR PyYAML is required; install scripts/requirements.txt", file=sys.stderr)
    raise SystemExit(2)


DEFAULT_INCLUDES = ["AGENTS.md", "**/AGENTS.md", "docs/**/*.md"]
REQUIRED_FIELDS = {
    "id",
    "title",
    "type",
    "status",
    "authority",
    "topics",
    "summary",
    "relations",
    "reviewed",
}
SCOPED_TYPES = {"map", "contract", "runbook"}
ALLOWED_TYPES = {"map", "contract", "decision", "runbook", "concept", "reference"}
ALLOWED_STATUSES = {"draft", "active", "deprecated", "archived"}
ALLOWED_AUTHORITIES = {"normative", "informative", "generated"}
ALLOWED_RELATIONS = {
    "derived_from",
    "depends_on",
    "supersedes",
    "verified_by",
    "implemented_by",
    "related_to",
}
DOC_RELATIONS = {"derived_from", "depends_on", "supersedes", "related_to"}
LINK_RE = re.compile(r"\[[^]]+\]\(([^)]+)\)")
FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return value


def parse_markdown(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("missing YAML frontmatter")
    metadata = yaml.safe_load(match.group(1)) or {}
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter must be a mapping")
    return metadata, text[match.end() :]


def relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) or Path(path).match(pattern) for pattern in patterns)


def managed_documents(root: Path, config: dict[str, Any]) -> list[Path]:
    documents = config.get("documents") if isinstance(config.get("documents"), dict) else {}
    includes = documents.get("include", DEFAULT_INCLUDES)
    excludes = documents.get("exclude", [])
    if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
        raise ValueError("documents.include must be a string array")
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise ValueError("documents.exclude must be a string array")

    found: set[Path] = set()
    for pattern in includes:
        found.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(
        path for path in found if not matches_any(relative_posix(path, root), excludes)
    )


def resolve_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def path_exists(root: Path, target: str) -> bool:
    if target.startswith("command:"):
        return True
    if any(char in target for char in "*?["):
        return any(root.glob(target))
    return (root / target).exists()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", nargs="?", default=".")
    parser.add_argument("--strict-warnings", action="store_true")
    args = parser.parse_args()

    root = Path(args.repository).resolve()
    config_path = root / ".knowledge" / "config.yml"
    errors: list[str] = []
    warnings: list[str] = []

    try:
        config = load_yaml(config_path) if config_path.exists() else {}
        documents = managed_documents(root, config)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR configuration: {exc}")
        return 1

    vocabulary_path = root / str(config.get("vocabulary_path", "docs/vocabulary/topics.yml"))
    vocabulary: dict[str, Any] = {}
    if vocabulary_path.exists():
        try:
            vocabulary = load_yaml(vocabulary_path)
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{relative_posix(vocabulary_path, root)}: invalid vocabulary: {exc}")
    elif documents:
        errors.append(f"{relative_posix(vocabulary_path, root)}: vocabulary file not found")

    alias_owner: dict[str, str] = {}
    for topic, entry in vocabulary.items():
        if not isinstance(entry, dict):
            errors.append(f"vocabulary topic {topic}: entry must be a mapping")
            continue
        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list):
            errors.append(f"vocabulary topic {topic}: aliases must be an array")
            continue
        for alias in aliases:
            normalized = str(alias).strip().casefold()
            previous = alias_owner.get(normalized)
            if previous and previous != topic:
                errors.append(f"vocabulary alias {alias!r}: shared by {previous} and {topic}")
            alias_owner[normalized] = str(topic)

    records: dict[str, tuple[Path, dict[str, Any]]] = {}
    parsed: list[tuple[Path, dict[str, Any], str]] = []
    review_days = int(config.get("review_warning_days", 180))

    for path in documents:
        rel = relative_posix(path, root)
        try:
            metadata, body = parse_markdown(path)
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{rel}: {exc}")
            continue

        parsed.append((path, metadata, body))
        missing = sorted(REQUIRED_FIELDS - metadata.keys())
        if missing:
            errors.append(f"{rel}: missing fields: {', '.join(missing)}")

        doc_id = metadata.get("id")
        if not isinstance(doc_id, str) or not doc_id.strip():
            errors.append(f"{rel}: id must be a non-empty string")
        elif doc_id in records:
            errors.append(
                f"{rel}: duplicate id {doc_id} also used by {relative_posix(records[doc_id][0], root)}"
            )
        else:
            records[doc_id] = (path, metadata)

        doc_type = metadata.get("type")
        if doc_type not in ALLOWED_TYPES:
            errors.append(f"{rel}: invalid type {doc_type!r}")
        if metadata.get("status") not in ALLOWED_STATUSES:
            errors.append(f"{rel}: invalid status {metadata.get('status')!r}")
        if metadata.get("authority") not in ALLOWED_AUTHORITIES:
            errors.append(f"{rel}: invalid authority {metadata.get('authority')!r}")
        if path.name == "AGENTS.md" and doc_type != "map":
            errors.append(f"{rel}: AGENTS.md must use type map")

        topics = metadata.get("topics")
        if not isinstance(topics, list) or not topics:
            errors.append(f"{rel}: topics must be a non-empty array")
        else:
            for topic in topics:
                if topic not in vocabulary:
                    errors.append(f"{rel}: unknown controlled topic {topic!r}")

        if doc_type in SCOPED_TYPES:
            for field in ("applies_to", "read_when"):
                value = metadata.get(field)
                if not isinstance(value, list) or not value:
                    errors.append(f"{rel}: {field} must be a non-empty array for {doc_type}")

        relations = metadata.get("relations")
        if not isinstance(relations, list):
            errors.append(f"{rel}: relations must be an array")

        reviewed = resolve_date(metadata.get("reviewed"))
        if not reviewed:
            errors.append(f"{rel}: reviewed must be an ISO date")
        elif metadata.get("status") == "active" and (date.today() - reviewed).days > review_days:
            warnings.append(f"{rel}: active document was reviewed more than {review_days} days ago")

        summary = metadata.get("summary")
        if isinstance(summary, str) and len(re.findall(r"[.!?](?:\s|$)", summary)) > 2:
            warnings.append(f"{rel}: summary appears longer than two sentences")

        embedding = metadata.get("embedding", {})
        if embedding is not None and not isinstance(embedding, dict):
            errors.append(f"{rel}: embedding must be a mapping")
        elif isinstance(embedding, dict):
            if embedding.get("mode", "local_only") not in {"allow", "local_only", "deny"}:
                errors.append(f"{rel}: invalid embedding.mode {embedding.get('mode')!r}")
            if embedding.get("content", "full") not in {"full", "summary_only"}:
                errors.append(f"{rel}: invalid embedding.content {embedding.get('content')!r}")

    for path, metadata, body in parsed:
        rel = relative_posix(path, root)
        relations = metadata.get("relations", [])
        verified = False
        if isinstance(relations, list):
            for index, relation in enumerate(relations):
                if not isinstance(relation, dict):
                    errors.append(f"{rel}: relations[{index}] must be a mapping")
                    continue
                relation_type = relation.get("type")
                target = relation.get("target")
                if relation_type not in ALLOWED_RELATIONS:
                    errors.append(f"{rel}: invalid relation type {relation_type!r}")
                    continue
                if not isinstance(target, str) or not target:
                    errors.append(f"{rel}: relation {relation_type} requires a target")
                    continue
                if relation_type == "verified_by":
                    verified = True
                if relation_type in DOC_RELATIONS and target not in records:
                    errors.append(f"{rel}: relation target document {target!r} not found")
                elif relation_type not in DOC_RELATIONS and not path_exists(root, target):
                    errors.append(f"{rel}: relation target path {target!r} not found")

                if relation_type == "depends_on" and target in records:
                    target_status = records[target][1].get("status")
                    if metadata.get("status") == "active" and target_status != "active":
                        errors.append(f"{rel}: active document depends on {target} with status {target_status}")

        if metadata.get("type") == "contract" and metadata.get("status") == "active" and not verified:
            errors.append(f"{rel}: active contract requires at least one verified_by relation")

        if path.name == "AGENTS.md":
            for raw_target in LINK_RE.findall(body):
                target = raw_target.strip().strip("<>").split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                if not (path.parent / target).resolve().exists():
                    errors.append(f"{rel}: broken local link {raw_target!r}")

    for message in errors:
        print(f"ERROR {message}")
    for message in warnings:
        print(f"WARN  {message}")

    print(f"Validated {len(documents)} documents: {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors or (args.strict_warnings and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
