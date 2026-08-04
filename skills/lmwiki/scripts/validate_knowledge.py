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
ALLOWED_TYPES = {"map", "contract", "decision", "runbook", "concept", "reference", "memory", "persona"}
ALLOWED_STATUSES = {"draft", "active", "deprecated", "archived"}
ALLOWED_AUTHORITIES = {"normative", "informative", "generated"}
ALLOWED_RELATIONS = {
    "derived_from",
    "depends_on",
    "supersedes",
    "verified_by",
    "implemented_by",
    "related_to",
    "distilled_from",
}
DOC_RELATIONS = {"derived_from", "depends_on", "supersedes", "related_to", "distilled_from"}
ALLOWED_MEMORY_LEVELS = {"l0", "l1", "l2", "l3"}
ALLOWED_MEMORY_KINDS = {"fact", "preference", "conditional-action", "constraint", "event", "context"}
ALLOWED_VISIBILITIES = {"private", "team", "restricted", "agent"}
ALLOWED_PERMISSIONS = {"read", "write", "manage"}
SUBJECT_RE = re.compile(r"^(user|role|agent|team):[^:\\s]+$")
LINK_RE = re.compile(r"\[[^]]+\]\(([^)]+)\)")
FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return value


def load_glossary(path: Path) -> list[dict[str, Any]]:
    payload = load_yaml(path)
    terms = payload.get("terms")
    if not isinstance(terms, list):
        raise ValueError("glossary.terms must be an array")
    return terms


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

    glossary_path = root / str(config.get("glossary_path", "docs/vocabulary/glossary.yml"))
    glossary: list[dict[str, Any]] = []
    if glossary_path.exists():
        try:
            glossary = load_glossary(glossary_path)
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{relative_posix(glossary_path, root)}: invalid glossary: {exc}")
    elif documents:
        errors.append(f"{relative_posix(glossary_path, root)}: glossary file not found")

    glossary_terms: dict[str, int] = {}
    for index, entry in enumerate(glossary):
        label = f"glossary terms[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label}: entry must be a mapping")
            continue
        term = entry.get("term")
        description = entry.get("description")
        if not isinstance(term, str) or not term.strip():
            errors.append(f"{label}: term must be a non-empty string")
        else:
            normalized = term.strip().casefold()
            previous = glossary_terms.get(normalized)
            if previous is not None:
                errors.append(
                    f"{label}: duplicate term {term!r} also used by terms[{previous}]"
                )
            else:
                glossary_terms[normalized] = index
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{label}: description must be a non-empty string")

    records: dict[str, tuple[Path, dict[str, Any]]] = {}
    parsed: list[tuple[Path, dict[str, Any], str]] = []
    review_days = int(config.get("review_warning_days", 180))
    memory_config = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    private_memory_path = str(memory_config.get("private_path", ".knowledge/private-memory")).rstrip("/")
    persona_source_minimum = int(memory_config.get("persona_requires_sources", 2))
    memory_capture = memory_config.get("capture", "explicit")
    if memory_capture not in {"disabled", "explicit", "hook"}:
        errors.append(
            ".knowledge/config.yml: memory.capture must be disabled, explicit, or hook"
        )

    hook_config = config.get("hooks") if isinstance(config.get("hooks"), dict) else {}
    hook_enabled = hook_config.get("enabled", False)
    if not isinstance(hook_enabled, bool):
        errors.append(".knowledge/config.yml: hooks.enabled must be a boolean")
    if hook_config.get("execution", "same_thread") not in {"same_thread", "agent"}:
        errors.append(".knowledge/config.yml: hooks.execution must be same_thread or agent")
    hook_stages = hook_config.get("memory_stages", ["l0", "l1", "l2"])
    if (
        not isinstance(hook_stages, list)
        or any(stage not in {"l0", "l1", "l2"} for stage in hook_stages)
        or len(set(hook_stages)) != len(hook_stages)
    ):
        errors.append(
            ".knowledge/config.yml: hooks.memory_stages must contain unique l0, l1, or l2 values"
        )
    l3_hook = hook_config.get("l3") if isinstance(hook_config.get("l3"), dict) else {}
    if not isinstance(l3_hook.get("enabled", True), bool):
        errors.append(".knowledge/config.yml: hooks.l3.enabled must be a boolean")
    l3_minimum = l3_hook.get("minimum_sources", persona_source_minimum)
    if (
        not isinstance(l3_minimum, int)
        or isinstance(l3_minimum, bool)
        or l3_minimum < 2
    ):
        errors.append(".knowledge/config.yml: hooks.l3.minimum_sources must be an integer >= 2")
    runbook_hook = (
        hook_config.get("runbook") if isinstance(hook_config.get("runbook"), dict) else {}
    )
    if not isinstance(runbook_hook.get("enabled", True), bool):
        errors.append(".knowledge/config.yml: hooks.runbook.enabled must be a boolean")
    if runbook_hook.get("require_user_confirmation", True) is not True:
        errors.append(
            ".knowledge/config.yml: hooks.runbook.require_user_confirmation must be true"
        )
    if runbook_hook.get("status", "draft") != "draft":
        errors.append(".knowledge/config.yml: hooks.runbook.status must be draft")
    access_config = (
        config.get("access_control") if isinstance(config.get("access_control"), dict) else {}
    )
    managers = access_config.get("managers", [access_config.get("default_owner", "user:owner")])
    if not isinstance(managers, list) or not managers:
        errors.append(".knowledge/config.yml: access_control.managers must be a non-empty array")
    else:
        for manager in managers:
            if not isinstance(manager, str) or not SUBJECT_RE.match(manager):
                errors.append(
                    f".knowledge/config.yml: invalid access_control manager {manager!r}"
                )

    retrieval = config.get("retrieval") if isinstance(config.get("retrieval"), dict) else {}
    bm25_enabled = retrieval.get("bm25_enabled", True)
    if not isinstance(bm25_enabled, bool):
        errors.append(".knowledge/config.yml: retrieval.bm25_enabled must be a boolean")
    bm25_path = retrieval.get("bm25_index_path", ".knowledge/index/search.db")
    if not isinstance(bm25_path, str) or not bm25_path.strip():
        errors.append(".knowledge/config.yml: retrieval.bm25_index_path must be a non-empty string")
    else:
        normalized_bm25_path = bm25_path.replace("\\", "/")
        path_parts = Path(normalized_bm25_path).parts
        if (
            Path(normalized_bm25_path).is_absolute()
            or ".." in path_parts
            or not normalized_bm25_path.startswith(".knowledge/index/")
        ):
            errors.append(
                ".knowledge/config.yml: retrieval.bm25_index_path must stay under .knowledge/index/"
            )
    candidate_limit = retrieval.get("bm25_candidate_limit", 24)
    result_limit = retrieval.get("bm25_result_limit", 12)
    if (
        not isinstance(candidate_limit, int)
        or isinstance(candidate_limit, bool)
        or not 1 <= candidate_limit <= 1000
    ):
        errors.append(
            ".knowledge/config.yml: retrieval.bm25_candidate_limit must be an integer from 1 to 1000"
        )
    if (
        not isinstance(result_limit, int)
        or isinstance(result_limit, bool)
        or not 1 <= result_limit <= 100
    ):
        errors.append(
            ".knowledge/config.yml: retrieval.bm25_result_limit must be an integer from 1 to 100"
        )
    if (
        isinstance(candidate_limit, int)
        and not isinstance(candidate_limit, bool)
        and isinstance(result_limit, int)
        and not isinstance(result_limit, bool)
        and candidate_limit < result_limit
    ):
        errors.append(
            ".knowledge/config.yml: retrieval.bm25_candidate_limit must be at least bm25_result_limit"
        )
    if retrieval.get("bm25_query_mode", "high_recall") != "high_recall":
        errors.append(".knowledge/config.yml: retrieval.bm25_query_mode must be high_recall")
    if retrieval.get("result_content", "locations_only") != "locations_only":
        errors.append(".knowledge/config.yml: retrieval.result_content must be locations_only")
    graph_hops = retrieval.get("graph_hops", 1)
    if (
        not isinstance(graph_hops, int)
        or isinstance(graph_hops, bool)
        or not 0 <= graph_hops <= 3
    ):
        errors.append(".knowledge/config.yml: retrieval.graph_hops must be an integer from 0 to 3")

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

        glossary_refs = metadata.get("glossary_terms", [])
        if not isinstance(glossary_refs, list) or any(
            not isinstance(term, str) or not term.strip() for term in glossary_refs
        ):
            errors.append(f"{rel}: glossary_terms must be an array of non-empty strings")
        else:
            for term in glossary_refs:
                if term.strip().casefold() not in glossary_terms:
                    warnings.append(f"{rel}: unregistered glossary term {term!r}")

        embedding = metadata.get("embedding", {})
        if embedding is not None and not isinstance(embedding, dict):
            errors.append(f"{rel}: embedding must be a mapping")
        elif isinstance(embedding, dict):
            if embedding.get("mode", "local_only") not in {"allow", "local_only", "deny"}:
                errors.append(f"{rel}: invalid embedding.mode {embedding.get('mode')!r}")
            if embedding.get("content", "full") not in {"full", "summary_only"}:
                errors.append(f"{rel}: invalid embedding.content {embedding.get('content')!r}")

        provenance = metadata.get("provenance")
        if provenance is not None:
            if not isinstance(provenance, list):
                errors.append(f"{rel}: provenance must be an array")
            else:
                for source_index, source in enumerate(provenance):
                    if isinstance(source, str) and source:
                        continue
                    if not isinstance(source, dict):
                        errors.append(f"{rel}: provenance[{source_index}] must be a string or mapping")
                        continue
                    source_path = source.get("source", source.get("path"))
                    if not isinstance(source_path, str) or not source_path:
                        errors.append(f"{rel}: provenance[{source_index}] requires source or path")

        if doc_type in {"memory", "persona"}:
            memory = metadata.get("memory")
            if not isinstance(memory, dict):
                errors.append(f"{rel}: memory must be a mapping for {doc_type}")
            else:
                level = memory.get("level")
                if level not in ALLOWED_MEMORY_LEVELS:
                    errors.append(f"{rel}: invalid memory.level {level!r}")
                if doc_type == "persona" and level != "l3":
                    errors.append(f"{rel}: persona must use memory.level l3")
                confidence = memory.get("confidence")
                if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
                    errors.append(f"{rel}: memory.confidence must be between 0 and 1")
                if not isinstance(memory.get("subject"), str) or not memory.get("subject"):
                    errors.append(f"{rel}: memory.subject must be a non-empty string")
                kind = memory.get("kind")
                if kind is not None and kind not in ALLOWED_MEMORY_KINDS:
                    errors.append(f"{rel}: invalid memory.kind {kind!r}")
                if level == "l1" and kind is None:
                    warnings.append(f"{rel}: l1 memory should declare memory.kind")

        access = metadata.get("access")
        if access is None:
            if doc_type in {"memory", "persona"}:
                errors.append(f"{rel}: access must be a mapping for {doc_type}")
        elif not isinstance(access, dict):
            errors.append(f"{rel}: access must be a mapping")
        else:
            visibility = access.get("visibility")
            if visibility not in ALLOWED_VISIBILITIES:
                errors.append(f"{rel}: invalid access.visibility {visibility!r}")
            owner = access.get("owner")
            team = access.get("team")
            if not isinstance(owner, str) or not owner.startswith("user:") or not SUBJECT_RE.match(owner):
                errors.append(f"{rel}: access.owner must use user:<id> syntax")
            if not isinstance(team, str) or not team.startswith("team:") or not SUBJECT_RE.match(team):
                errors.append(f"{rel}: access.team must use team:<id> syntax")
            grants = access.get("grants", [])
            read_grants: list[str] = []
            if not isinstance(grants, list):
                errors.append(f"{rel}: access.grants must be an array")
            else:
                for grant_index, grant in enumerate(grants):
                    if not isinstance(grant, dict):
                        errors.append(f"{rel}: access.grants[{grant_index}] must be a mapping")
                        continue
                    subject = grant.get("subject")
                    permissions = grant.get("permissions")
                    if not isinstance(subject, str) or not SUBJECT_RE.match(subject):
                        errors.append(f"{rel}: access.grants[{grant_index}].subject is invalid")
                    if not isinstance(permissions, list) or not permissions or any(
                        permission not in ALLOWED_PERMISSIONS for permission in permissions
                    ):
                        errors.append(f"{rel}: access.grants[{grant_index}].permissions is invalid")
                    elif isinstance(subject, str) and "read" in permissions:
                        read_grants.append(subject)
            if visibility == "restricted" and not read_grants:
                errors.append(f"{rel}: restricted access requires at least one read grant")
            if visibility == "agent" and not any(subject.startswith("agent:") for subject in read_grants):
                errors.append(f"{rel}: agent access requires at least one agent:* read grant")
            if visibility in {"private", "restricted"} and not (
                rel == private_memory_path or rel.startswith(private_memory_path + "/")
            ):
                errors.append(
                    f"{rel}: {visibility} document must be stored under {private_memory_path}; "
                    "frontmatter ACL does not restrict Git readers"
                )

    for path, metadata, body in parsed:
        rel = relative_posix(path, root)
        relations = metadata.get("relations", [])
        verified = False
        distilled_from = 0
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
                if relation_type == "distilled_from":
                    distilled_from += 1
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

        memory = metadata.get("memory") if isinstance(metadata.get("memory"), dict) else {}
        level = memory.get("level")
        if metadata.get("type") == "memory" and level in {"l1", "l2", "l3"} and distilled_from < 1:
            errors.append(f"{rel}: {level} memory requires at least one distilled_from relation")
        if metadata.get("type") == "persona" and distilled_from < persona_source_minimum:
            errors.append(
                f"{rel}: persona requires at least {persona_source_minimum} distilled_from relations"
            )

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
