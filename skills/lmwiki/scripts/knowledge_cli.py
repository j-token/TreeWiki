#!/usr/bin/env python
"""Query and manage an LMWiki repository with ACL-first retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR PyYAML is required; install scripts/requirements.txt", file=sys.stderr)
    raise SystemExit(2)

from validate_knowledge import (
    load_glossary,
    load_yaml,
    managed_documents,
    parse_markdown,
    relative_posix,
)
from build_search_index import search_locations


TOKEN_RE = re.compile(r"[\w가-힣-]+", re.UNICODE)
SUBJECT_RE = re.compile(r"^(user|role|agent|team):[^:\s]+$")
CURRENT_CONFIG_VERSION = 2
DEFAULT_CONFIG: dict[str, Any] = {
    "version": CURRENT_CONFIG_VERSION,
    "vocabulary_path": "docs/vocabulary/topics.yml",
    "glossary_path": "docs/vocabulary/glossary.yml",
    "memory": {
        "enabled": True,
        "capture": "explicit",
        "shared_path": "docs/memory",
        "private_path": ".knowledge/private-memory",
        "levels": ["l0", "l1", "l2", "l3"],
        "persona_requires_sources": 2,
    },
    "hooks": {
        "enabled": False,
        "execution": "same_thread",
        "memory_stages": ["l0", "l1", "l2"],
        "l3": {"enabled": True, "minimum_sources": 2},
        "runbook": {
            "enabled": True,
            "require_user_confirmation": True,
            "status": "draft",
        },
    },
    "access_control": {
        "default_visibility": "team",
        "default_owner": "user:owner",
        "default_team": "team:repository",
        "managers": ["user:owner"],
        "principal_required": True,
        "policy_enforcement": "cooperative",
    },
    "retrieval": {
        "keyword_enabled": True,
        "graph_hops": 1,
        "max_results": 6,
        "bm25_enabled": True,
        "bm25_index_path": ".knowledge/index/search.db",
        "bm25_candidate_limit": 24,
        "bm25_result_limit": 12,
        "bm25_query_mode": "high_recall",
        "result_content": "locations_only",
    },
}


def merge_missing(target: dict[str, Any], defaults: dict[str, Any], prefix: str = "") -> list[str]:
    added: list[str] = []
    for key, value in defaults.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if key not in target:
            target[key] = value
            added.append(dotted)
        elif isinstance(value, dict) and isinstance(target[key], dict):
            added.extend(merge_missing(target[key], value, dotted))
    return added


def repository_config(root: Path) -> dict[str, Any]:
    path = root / ".knowledge" / "config.yml"
    if not path.exists():
        raise ValueError(".knowledge/config.yml not found; use lmwiki bootstrap mode")
    return load_yaml(path)


def load_records(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in managed_documents(root, config):
        metadata, body = parse_markdown(path)
        records.append(
            {
                "path": relative_posix(path, root),
                "metadata": metadata,
                "body": body,
            }
        )
    return records


def identity_subjects(args: argparse.Namespace) -> set[str]:
    expected = [
        ("principal", args.principal, "user:"),
        ("team", args.team, "team:"),
        ("agent", args.agent, "agent:"),
    ]
    expected.extend(("role", role, "role:") for role in (args.role or []))
    for label, value, prefix in expected:
        if value is not None and (not value.startswith(prefix) or not SUBJECT_RE.match(value)):
            raise ValueError(f"{label} must use {prefix}<id> syntax")
    subjects = {args.principal}
    if args.team:
        subjects.add(args.team)
    if args.agent:
        subjects.add(args.agent)
    subjects.update(args.role or [])
    return subjects


def grant_allows(grant: Any, subjects: set[str], subject_prefix: str | None = None) -> bool:
    if not isinstance(grant, dict) or grant.get("subject") not in subjects:
        return False
    if subject_prefix and not str(grant.get("subject")).startswith(subject_prefix):
        return False
    permissions = grant.get("permissions", [])
    return isinstance(permissions, list) and "read" in permissions


def can_read(metadata: dict[str, Any], config: dict[str, Any], subjects: set[str]) -> bool:
    defaults = config.get("access_control") if isinstance(config.get("access_control"), dict) else {}
    access = metadata.get("access") if isinstance(metadata.get("access"), dict) else {}
    visibility = access.get("visibility", defaults.get("default_visibility", "team"))
    owner = access.get("owner", defaults.get("default_owner", "user:owner"))
    team = access.get("team", defaults.get("default_team", "team:repository"))
    grants = access.get("grants", [])
    if owner in subjects:
        return True
    if visibility == "team":
        return team in subjects
    if visibility == "private":
        return False
    if visibility == "restricted":
        return isinstance(grants, list) and any(grant_allows(grant, subjects) for grant in grants)
    if visibility == "agent":
        return isinstance(grants, list) and any(
            grant_allows(grant, subjects, "agent:") for grant in grants
        )
    return False


def require_repository_manager(
    root: Path, config: dict[str, Any], args: argparse.Namespace
) -> set[str]:
    subjects = identity_subjects(args)
    access = config.get("access_control") if isinstance(config.get("access_control"), dict) else {}
    managers = access.get("managers", [access.get("default_owner", "user:owner")])
    if not isinstance(managers, list) or not any(manager in subjects for manager in managers):
        raise ValueError(f"management denied for {args.principal} in {root}")
    return subjects


def allowed_records(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    subjects: set[str],
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if can_read(record["metadata"], config, subjects)
        and (include_inactive or record["metadata"].get("status") == "active")
    ]


def normalized_terms(text: str) -> set[str]:
    return {term.casefold() for term in TOKEN_RE.findall(text)}


def expand_vocabulary_terms(root: Path, config: dict[str, Any], terms: set[str]) -> set[str]:
    path = root / str(config.get("vocabulary_path", "docs/vocabulary/topics.yml"))
    if not path.exists():
        return terms
    vocabulary = load_yaml(path)
    expanded = set(terms)
    for key, entry in vocabulary.items():
        if not isinstance(entry, dict):
            continue
        values = [str(key), str(entry.get("label", ""))]
        aliases = entry.get("aliases", [])
        if isinstance(aliases, list):
            values.extend(str(alias) for alias in aliases)
        group: set[str] = set()
        for value in values:
            group.update(normalized_terms(value))
        if terms & group:
            expanded.update(group)
    return expanded


def lexical_score(record: dict[str, Any], terms: set[str]) -> float:
    metadata = record["metadata"]
    fields = [
        (str(metadata.get("title", "")), 5.0),
        (str(metadata.get("summary", "")), 3.0),
        (" ".join(str(value) for value in metadata.get("topics", [])), 4.0),
        (" ".join(str(value) for value in metadata.get("read_when", [])), 2.0),
        (record["body"], 1.0),
    ]
    score = 0.0
    for text, weight in fields:
        words = normalized_terms(text)
        score += weight * len(terms & words)
        folded = text.casefold()
        score += 0.25 * weight * sum(1 for term in terms if term in folded and term not in words)
    authority = metadata.get("authority")
    if score and authority == "normative":
        score *= 1.2
    return score


def relation_targets(record: dict[str, Any]) -> set[str]:
    relations = record["metadata"].get("relations", [])
    if not isinstance(relations, list):
        return set()
    return {
        str(relation["target"])
        for relation in relations
        if isinstance(relation, dict) and isinstance(relation.get("target"), str)
    }


def print_records(records: list[dict[str, Any]], as_json: bool) -> None:
    for record in records:
        metadata = record["metadata"]
        item = {
            "id": metadata.get("id"),
            "title": metadata.get("title"),
            "type": metadata.get("type"),
            "status": metadata.get("status"),
            "path": record["path"],
            "summary": metadata.get("summary"),
        }
        if "score" in record:
            item["score"] = round(float(record["score"]), 4)
            item["via"] = record.get("via")
        if as_json:
            print(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        else:
            score = f" score={item['score']}" if "score" in item else ""
            via = f" via={item['via']}" if item.get("via") else ""
            print(f"{item['id']}\t{item['type']}\t{item['path']}{score}{via}\t{item['title']}")


def print_search_locations(records: list[dict[str, Any]], as_json: bool) -> None:
    for record in records:
        item = {
            "path": record["path"],
            "id": record["metadata"].get("id"),
            "rank": record.get("rank"),
            "via": record.get("via"),
            "engine": record.get("engine"),
        }
        if as_json:
            print(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        else:
            details = [f"id={item['id']}", f"engine={item['engine']}"]
            if item["rank"] is not None:
                details.append(f"rank={item['rank']}")
            if item["via"]:
                details.append(f"via={item['via']}")
            print(f"{item['path']}\t" + "\t".join(details))


def query_search(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    subjects = identity_subjects(args)
    records = allowed_records(load_records(root, config), config, subjects, args.include_inactive)
    terms = expand_vocabulary_terms(root, config, normalized_terms(args.query))
    if not terms:
        print("ERROR search query has no searchable terms")
        return 1

    by_id = {
        str(record["metadata"].get("id")): record
        for record in records
        if record["metadata"].get("id")
    }
    retrieval = config.get("retrieval") if isinstance(config.get("retrieval"), dict) else {}
    embedding = config.get("embedding") if isinstance(config.get("embedding"), dict) else {}
    use_bm25 = bool(embedding.get("enabled", False) and retrieval.get("bm25_enabled", True))
    direct: dict[str, dict[str, Any]] = {}
    if use_bm25:
        database = root / str(retrieval.get("bm25_index_path", ".knowledge/index/search.db"))
        if not database.exists():
            print("ERROR SQLite BM25 index not found; run manage reindex with authorized --apply")
            return 1
        result_limit = max(1, int(args.limit or retrieval.get("bm25_result_limit", 12)))
        candidate_limit = max(
            result_limit,
            int(retrieval.get("bm25_candidate_limit", 24)),
        )
        for hit in search_locations(database, terms, set(by_id), candidate_limit):
            doc_id = str(hit["id"])
            record = by_id.get(doc_id)
            if record is None:
                continue
            direct[doc_id] = {
                **record,
                "score": 1.0 / float(hit["rank"]),
                "rank": int(hit["rank"]),
                "via": None,
                "engine": "sqlite-bm25",
            }
    else:
        for record in records:
            score = lexical_score(record, terms)
            doc_id = str(record["metadata"].get("id", ""))
            if score > 0 and doc_id:
                direct[doc_id] = {
                    **record,
                    "score": score,
                    "rank": None,
                    "via": None,
                    "engine": "lexical-fallback",
                }

    adjacency: dict[str, set[str]] = {doc_id: set() for doc_id in by_id}
    for doc_id, record in by_id.items():
        for target in relation_targets(record):
            if target in by_id:
                adjacency[doc_id].add(target)
                adjacency[target].add(doc_id)

    hops = max(0, min(int(args.hops if args.hops is not None else retrieval.get("graph_hops", 1)), 3))
    results = dict(direct)
    frontier = list(direct)
    for hop in range(1, hops + 1):
        next_frontier: list[str] = []
        for source_id in frontier:
            source_score = float(results[source_id]["score"])
            for target in adjacency.get(source_id, set()):
                candidate_score = source_score * 0.5
                existing = results.get(target)
                if existing is None or candidate_score > float(existing["score"]):
                    results[target] = {
                        **by_id[target],
                        "score": candidate_score,
                        "rank": None,
                        "via": source_id,
                        "engine": "relation",
                    }
                    if existing is None:
                        next_frontier.append(target)
        frontier = next_frontier

    default_limit = int(
        retrieval.get("bm25_result_limit", 12)
        if use_bm25
        else retrieval.get("max_results", 6)
    )
    limit = max(1, min(args.limit or default_limit, 100))
    ranked = sorted(results.values(), key=lambda item: (-float(item["score"]), item["path"]))[:limit]
    print_search_locations(ranked, args.json)
    return 0


def query_read(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    records = allowed_records(
        load_records(root, config), config, identity_subjects(args), include_inactive=True
    )
    ref = args.reference.replace("\\", "/")
    for record in records:
        metadata = record["metadata"]
        if ref in {metadata.get("id"), record["path"], record["path"].removesuffix(".md")}:
            print((root / record["path"]).read_text(encoding="utf-8"), end="")
            return 0
    print("NOT FOUND OR DENIED")
    return 3


def query_list(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    records = allowed_records(
        load_records(root, config), config, identity_subjects(args), args.include_inactive
    )
    records.sort(key=lambda item: (str(item["metadata"].get("type")), item["path"]))
    print_records(records, args.json)
    return 0


def query_graph(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    records = allowed_records(
        load_records(root, config), config, identity_subjects(args), args.include_inactive
    )
    by_id = {
        str(record["metadata"].get("id")): record
        for record in records
        if record["metadata"].get("id")
    }
    nodes = [
        {
            "id": doc_id,
            "title": record["metadata"].get("title"),
            "type": record["metadata"].get("type"),
            "path": record["path"],
        }
        for doc_id, record in sorted(by_id.items())
    ]
    edges: list[dict[str, str]] = []
    for source, record in sorted(by_id.items()):
        relations = record["metadata"].get("relations", [])
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            target = relation.get("target")
            if isinstance(target, str) and target in by_id:
                edges.append({"source": source, "target": target, "type": str(relation.get("type"))})
    print(json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2))
    return 0


def query_glossary(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    subjects = identity_subjects(args)
    if not can_read({}, config, subjects):
        print("NOT FOUND OR DENIED")
        return 3

    path = root / str(config.get("glossary_path", "docs/vocabulary/glossary.yml"))
    entries = load_glossary(path)
    query = args.term.strip().casefold() if args.term else ""
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        term = entry.get("term")
        description = entry.get("description")
        if not isinstance(term, str) or not isinstance(description, str):
            continue
        folded_term = term.strip().casefold()
        folded_description = description.casefold()
        if query and query not in folded_term and query not in folded_description:
            continue
        priority = 0 if query and query == folded_term else 1 if query in folded_term else 2
        matches.append((priority, index, {"term": term, "description": description}))

    matches.sort(key=lambda item: (item[0], item[1]))
    if query and not matches:
        print("NOT FOUND")
        return 3
    for _, _, entry in matches:
        if args.json:
            print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"{entry['term']}\t{entry['description']}")
    return 0


def query_glossary_candidates(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    records = allowed_records(load_records(root, config), config, identity_subjects(args), True)
    glossary_path = root / str(config.get("glossary_path", "docs/vocabulary/glossary.yml"))
    registered = {
        str(entry.get("term", "")).strip().casefold()
        for entry in load_glossary(glossary_path)
        if isinstance(entry, dict) and isinstance(entry.get("term"), str)
    }
    selected_paths = {value.replace("\\", "/") for value in (args.path or [])}
    candidates: list[dict[str, str]] = []
    for record in records:
        if selected_paths and record["path"] not in selected_paths:
            continue
        terms = record["metadata"].get("glossary_terms", [])
        if not isinstance(terms, list):
            continue
        for term in terms:
            if not isinstance(term, str) or not term.strip() or term.strip().casefold() in registered:
                continue
            candidates.append({"term": term.strip(), "path": record["path"]})
    if not candidates:
        print("NO UNREGISTERED GLOSSARY TERMS")
        return 0
    for candidate in sorted(candidates, key=lambda item: (item["term"].casefold(), item["path"])):
        if args.json:
            print(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"{candidate['term']}\t{candidate['path']}")
    return 0


def query_preferences(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    records = allowed_records(load_records(root, config), config, identity_subjects(args), False)
    preference_kinds = {"preference", "conditional-action", "constraint"}
    selected: list[dict[str, Any]] = []
    for record in records:
        metadata = record["metadata"]
        memory = metadata.get("memory") if isinstance(metadata.get("memory"), dict) else {}
        if memory.get("subject") != args.principal:
            continue
        if metadata.get("type") == "persona" and memory.get("level") == "l3":
            selected.append(record)
        elif (
            metadata.get("type") == "memory"
            and memory.get("level") == "l1"
            and memory.get("kind") in preference_kinds
        ):
            selected.append(record)
    selected.sort(key=lambda item: (item["metadata"].get("type") != "persona", item["path"]))
    print_records(selected, args.json)
    return 0


def distilled_parent_ids(metadata: dict[str, Any]) -> list[str]:
    relations = metadata.get("relations", [])
    if not isinstance(relations, list):
        return []
    return [
        str(relation["target"])
        for relation in relations
        if isinstance(relation, dict)
        and relation.get("type") == "distilled_from"
        and isinstance(relation.get("target"), str)
    ]


def provenance_keys(record: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> set[str]:
    seen: set[str] = set()

    def visit(current: dict[str, Any]) -> set[str]:
        metadata = current["metadata"]
        doc_id = str(metadata.get("id", ""))
        if doc_id in seen:
            return set()
        seen.add(doc_id)
        parents = [by_id[parent] for parent in distilled_parent_ids(metadata) if parent in by_id]
        if parents:
            roots: set[str] = set()
            for parent in parents:
                roots.update(visit(parent))
            if roots:
                return roots
        provenance = metadata.get("provenance", [])
        if isinstance(provenance, list):
            sources = {source_reference(item) for item in provenance}
            keys = {f"provenance:{source}" for source in sources if source}
            if keys:
                return keys
        return {f"document:{doc_id}"} if doc_id else set()

    return visit(record)


def l3_candidates(
    records: list[dict[str, Any]], minimum_sources: int, subject: str | None = None
) -> dict[str, dict[str, list[str]]]:
    by_id = {
        str(record["metadata"].get("id")): record
        for record in records
        if isinstance(record["metadata"].get("id"), str)
    }
    grouped: dict[str, dict[str, set[str]]] = {}
    covered: dict[str, set[str]] = {}
    for record in records:
        metadata = record["metadata"]
        memory = metadata.get("memory") if isinstance(metadata.get("memory"), dict) else {}
        memory_subject = memory.get("subject")
        doc_id = metadata.get("id")
        if (
            metadata.get("type") == "memory"
            and metadata.get("status") == "active"
            and memory.get("level") in {"l1", "l2"}
            and isinstance(memory_subject, str)
            and isinstance(doc_id, str)
            and (subject is None or memory_subject == subject)
        ):
            group = grouped.setdefault(memory_subject, {"documents": set(), "provenance": set()})
            group["documents"].add(doc_id)
            group["provenance"].update(provenance_keys(record, by_id))

        if (
            metadata.get("type") != "persona"
            or metadata.get("status") != "active"
            or memory.get("level") != "l3"
            or not isinstance(memory_subject, str)
            or (subject is not None and memory_subject != subject)
        ):
            continue
        for target in distilled_parent_ids(metadata):
            if target in by_id:
                covered.setdefault(memory_subject, set()).update(
                    provenance_keys(by_id[target], by_id)
                )

    return {
        memory_subject: {
            "evidence_ids": sorted(group["documents"]),
            "provenance": sorted(group["provenance"]),
        }
        for memory_subject, group in sorted(grouped.items())
        if len(group["provenance"]) >= minimum_sources
        and not group["provenance"].issubset(covered.get(memory_subject, set()))
    }


def query_l3_candidates(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    subjects = identity_subjects(args)
    records = allowed_records(load_records(root, config), config, subjects, include_inactive=True)
    memory = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    hooks = config.get("hooks") if isinstance(config.get("hooks"), dict) else {}
    l3 = hooks.get("l3") if isinstance(hooks.get("l3"), dict) else {}
    minimum = max(2, int(l3.get("minimum_sources", memory.get("persona_requires_sources", 2))))
    candidates = l3_candidates(records, minimum, args.subject)
    if not candidates:
        print("NO ELIGIBLE L3 CANDIDATES")
        return 0
    for memory_subject, evidence in candidates.items():
        item = {
            "subject": memory_subject,
            "minimum_sources": minimum,
            **evidence,
        }
        if args.json:
            print(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        else:
            print(
                f"{memory_subject}\tminimum_sources={minimum}\t"
                f"evidence={','.join(evidence['evidence_ids'])}\t"
                f"provenance={','.join(evidence['provenance'])}"
            )
    return 0


def manage_validate(args: argparse.Namespace) -> int:
    script = Path(__file__).with_name("validate_knowledge.py")
    command = [sys.executable, str(script), str(Path(args.repository).resolve())]
    if args.strict_warnings:
        command.append("--strict-warnings")
    return subprocess.run(command, check=False).returncode


def source_reference(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        value = item.get("source", item.get("path"))
        return value if isinstance(value, str) else None
    return None


def manage_sync(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    require_repository_manager(root, config, args)
    records = load_records(root, config)
    registry_path = root / ".knowledge" / "sources.yml"
    old: dict[str, Any] = {}
    if registry_path.exists():
        loaded = load_yaml(registry_path)
        for item in loaded.get("sources", []):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                old[item["path"]] = item

    current: dict[str, dict[str, Any]] = {}
    for record in records:
        provenance = record["metadata"].get("provenance", [])
        if not isinstance(provenance, list):
            continue
        for item in provenance:
            source = source_reference(item)
            if not source or "://" in source or source.startswith("conversation:"):
                continue
            candidate = (root / source).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                print(f"ERROR source escapes repository: {source}")
                return 1
            entry = current.setdefault(source, {"path": source, "documents": []})
            entry["documents"].append(record["metadata"].get("id"))
            if candidate.is_file():
                digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                entry["sha256"] = f"sha256:{digest}"
                entry["status"] = "present"
            else:
                entry["sha256"] = None
                entry["status"] = "missing"

    counts = {"new": 0, "changed": 0, "missing": 0, "unchanged": 0, "removed": 0}
    for path, entry in current.items():
        if entry["status"] == "missing":
            state = "missing"
        elif path not in old:
            state = "new"
        elif old[path].get("sha256") != entry.get("sha256"):
            state = "changed"
        else:
            state = "unchanged"
        counts[state] += 1
        print(f"{state.upper()} {path} -> {', '.join(str(x) for x in entry['documents'])}")
    for path in sorted(set(old) - set(current)):
        counts["removed"] += 1
        print(f"REMOVED {path}")

    if args.apply:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "sources": [current[key] for key in sorted(current)]}
        with registry_path.open("w", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
        print(f"APPLIED {registry_path}")
    else:
        print("DRY-RUN: pass --apply only after the user authorizes file changes")
    print(" ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


def manage_reindex(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    require_repository_manager(root, config, args)
    scripts = [
        Path(__file__).with_name("build_embedding_index.py"),
        Path(__file__).with_name("build_search_index.py"),
    ]
    if not args.apply:
        print("DRY-RUN: pass --apply only after the user authorizes file changes")
    for script in scripts:
        command = [sys.executable, str(script), str(root)]
        if not args.apply:
            command.append("--dry-run")
        result = subprocess.run(command, check=False)
        if result.returncode:
            return result.returncode
    return 0


def manage_memory_finalize(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    require_repository_manager(root, config, args)
    print("MEMORY FINALIZE validate -> rebuild derived indexes")
    if not args.apply:
        print("DRY-RUN: pass --apply only after the user authorizes memory storage")
        return 0
    validation_args = argparse.Namespace(repository=str(root), strict_warnings=False)
    validation_result = manage_validate(validation_args)
    if validation_result:
        return validation_result
    return manage_reindex(args)


def manage_migrate(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config_path = root / ".knowledge" / "config.yml"
    if not config_path.exists():
        print("ERROR .knowledge/config.yml not found; use lmwiki bootstrap mode")
        return 1
    config = load_yaml(config_path)
    raw_version = config.get("version", 1)
    if not isinstance(raw_version, int) or isinstance(raw_version, bool) or raw_version < 1:
        raise ValueError(".knowledge/config.yml version must be a positive integer")
    if raw_version > CURRENT_CONFIG_VERSION:
        raise ValueError(
            f"repository config version {raw_version} is newer than supported version "
            f"{CURRENT_CONFIG_VERSION}; update the lmwiki skill first"
        )
    added = merge_missing(config, DEFAULT_CONFIG)
    config["version"] = CURRENT_CONFIG_VERSION
    require_repository_manager(root, config, args)
    documents = config.setdefault("documents", {})
    includes = documents.setdefault("include", ["AGENTS.md", "**/AGENTS.md", "docs/**/*.md"])
    private_pattern = ".knowledge/private-memory/**/*.md"
    if isinstance(includes, list) and private_pattern not in includes:
        includes.append(private_pattern)
        added.append("documents.include[private-memory]")
    directories = [
        "docs/memory/l2",
        ".knowledge/hooks",
        ".knowledge/hooks/state",
        ".knowledge/index",
        ".knowledge/private-memory/l0",
        ".knowledge/private-memory/l1",
        ".knowledge/private-memory/l2",
        ".knowledge/private-memory/l3",
    ]
    missing_dirs = [path for path in directories if not (root / path).exists()]
    access = config.get("access_control") if isinstance(config.get("access_control"), dict) else {}
    owner = str(access.get("default_owner", "user:owner"))
    team = str(access.get("default_team", "team:repository"))
    support_files: dict[Path, str] = {
        root / ".knowledge" / "hooks" / "state" / ".gitignore": "*\n!.gitignore\n",
        root / ".knowledge" / "index" / ".gitignore": "*\n!.gitignore\n",
        root / ".knowledge" / "private-memory" / ".gitignore": "*\n!.gitignore\n",
        root / ".knowledge" / "purpose.md": (
            "# LMWiki Purpose\n\n"
            "Preserve repository knowledge and explicitly approved layered memory for later agents.\n"
        ),
        root / ".knowledge" / "schema.md": (
            "# LMWiki Schema\n\n"
            "Use repository document types plus L0–L3 memory, Persona, provenance, and access metadata.\n"
        ),
        root / ".knowledge" / "principals.yml": yaml.safe_dump(
            {"version": 1, "team": team, "users": [owner], "roles": [], "agents": []},
            allow_unicode=True,
            sort_keys=False,
        ),
    }
    missing_files = [path for path in support_files if not path.exists()]
    skill_source = Path(__file__).resolve().parents[1]
    skill_target = root / ".agents" / "skills" / "lmwiki"
    skill_updates: list[tuple[Path, Path]] = []
    global_skill_updates: list[tuple[Path, Path]] = []
    if args.sync_skill_copy:
        for source in sorted(skill_source.rglob("*")):
            if not source.is_file() or "__pycache__" in source.parts or source.suffix == ".pyc":
                continue
            relative = source.relative_to(skill_source)
            target = skill_target / relative
            if not target.exists() or source.read_bytes() != target.read_bytes():
                skill_updates.append((source, target))
    if args.sync_global_skill_copy:
        global_target = (
            Path(args.global_skill_target).expanduser().resolve()
            if args.global_skill_target
            else (Path.home() / ".agents" / "skills" / "lmwiki").resolve()
        )
        if not (
            global_target.name == "lmwiki"
            and global_target.parent.name == "skills"
            and global_target.parent.parent.name == ".agents"
        ):
            raise ValueError("global skill target must end with .agents/skills/lmwiki")
        for source in sorted(skill_source.rglob("*")):
            if not source.is_file() or "__pycache__" in source.parts or source.suffix == ".pyc":
                continue
            target = global_target / source.relative_to(skill_source)
            if not target.exists() or source.read_bytes() != target.read_bytes():
                global_skill_updates.append((source, target))
    print(f"CONFIG VERSION {raw_version} -> {CURRENT_CONFIG_VERSION}")
    print(f"CONFIG KEYS TO ADD {len(added)}")
    for key in added:
        print(f"  + {key}")
    print(f"DIRECTORIES TO CREATE {len(missing_dirs)}")
    for path in missing_dirs:
        print(f"  + {path}/")
    print(f"SUPPORT FILES TO CREATE {len(missing_files)}")
    for path in missing_files:
        print(f"  + {relative_posix(path, root)}")
    print(f"SKILL FILES TO UPDATE {len(skill_updates)}")
    for _, path in skill_updates:
        print(f"  ~ {relative_posix(path, root)}")
    print(f"GLOBAL SKILL FILES TO UPDATE {len(global_skill_updates)}")
    for _, path in global_skill_updates:
        print(f"  ~ {path}")
    if args.sync_skill_copy and (root / "skills-lock.json").exists():
        print("NOTE skills-lock.json is not modified; refresh it with the original skill installer")
    if not args.apply:
        print("DRY-RUN: pass --apply only after the user authorizes file changes")
        return 0
    for path in missing_dirs:
        (root / path).mkdir(parents=True, exist_ok=True)
    for path in missing_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(support_files[path], encoding="utf-8", newline="\n")
    for source, target in skill_updates:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for source, target in global_skill_updates:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    with config_path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)
    print(f"APPLIED migration to config version {CURRENT_CONFIG_VERSION}")
    return 0


def add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--principal", required=True, help="Calling user subject, for example user:j-token")
    parser.add_argument("--team", default="team:repository")
    parser.add_argument("--agent")
    parser.add_argument("--role", action="append", default=[])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    groups = parser.add_subparsers(dest="group", required=True)

    query = groups.add_parser("query", help="Read-only, ACL-filtered commands")
    queries = query.add_subparsers(dest="query_command", required=True)

    search = queries.add_parser("search")
    search.add_argument("repository")
    search.add_argument("query")
    search.add_argument("--limit", type=int)
    search.add_argument("--hops", type=int)
    search.add_argument("--include-inactive", action="store_true")
    search.add_argument("--json", action="store_true")
    add_identity_arguments(search)
    search.set_defaults(handler=query_search)

    read = queries.add_parser("read")
    read.add_argument("repository")
    read.add_argument("reference")
    add_identity_arguments(read)
    read.set_defaults(handler=query_read)

    listing = queries.add_parser("list")
    listing.add_argument("repository")
    listing.add_argument("--include-inactive", action="store_true")
    listing.add_argument("--json", action="store_true")
    add_identity_arguments(listing)
    listing.set_defaults(handler=query_list)

    graph = queries.add_parser("graph")
    graph.add_argument("repository")
    graph.add_argument("--include-inactive", action="store_true")
    add_identity_arguments(graph)
    graph.set_defaults(handler=query_graph)

    glossary = queries.add_parser("glossary")
    glossary.add_argument("repository")
    glossary.add_argument("term", nargs="?")
    glossary.add_argument("--json", action="store_true")
    add_identity_arguments(glossary)
    glossary.set_defaults(handler=query_glossary)

    glossary_candidates_query = queries.add_parser("glossary-candidates")
    glossary_candidates_query.add_argument("repository")
    glossary_candidates_query.add_argument("--path", action="append")
    glossary_candidates_query.add_argument("--json", action="store_true")
    add_identity_arguments(glossary_candidates_query)
    glossary_candidates_query.set_defaults(handler=query_glossary_candidates)

    preferences_query = queries.add_parser("preferences")
    preferences_query.add_argument("repository")
    preferences_query.add_argument("--json", action="store_true")
    add_identity_arguments(preferences_query)
    preferences_query.set_defaults(handler=query_preferences)

    l3_query = queries.add_parser("l3-candidates")
    l3_query.add_argument("repository")
    l3_query.add_argument("--subject")
    l3_query.add_argument("--json", action="store_true")
    add_identity_arguments(l3_query)
    l3_query.set_defaults(handler=query_l3_candidates)

    manage = groups.add_parser("manage", help="Validation and explicitly applied mutations")
    managers = manage.add_subparsers(dest="manage_command", required=True)

    validate = managers.add_parser("validate")
    validate.add_argument("repository")
    validate.add_argument("--strict-warnings", action="store_true")
    validate.set_defaults(handler=manage_validate)

    sync = managers.add_parser("sync")
    sync.add_argument("repository")
    sync.add_argument("--apply", action="store_true")
    add_identity_arguments(sync)
    sync.set_defaults(handler=manage_sync)

    reindex = managers.add_parser("reindex")
    reindex.add_argument("repository")
    reindex.add_argument("--apply", action="store_true")
    add_identity_arguments(reindex)
    reindex.set_defaults(handler=manage_reindex)

    memory_finalize = managers.add_parser("memory-finalize")
    memory_finalize.add_argument("repository")
    memory_finalize.add_argument("--apply", action="store_true")
    add_identity_arguments(memory_finalize)
    memory_finalize.set_defaults(handler=manage_memory_finalize)

    migrate = managers.add_parser("migrate")
    migrate.add_argument("repository")
    migrate.add_argument("--apply", action="store_true")
    migrate.add_argument(
        "--sync-skill-copy",
        action="store_true",
        help="sync this CLI's lmwiki skill into repository .agents/skills/lmwiki",
    )
    migrate.add_argument(
        "--sync-global-skill-copy",
        action="store_true",
        help="sync this CLI's lmwiki skill into ~/.agents/skills/lmwiki",
    )
    migrate.add_argument(
        "--global-skill-target",
        help="override the global target; it must end with .agents/skills/lmwiki",
    )
    add_identity_arguments(migrate)
    migrate.set_defaults(handler=manage_migrate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
