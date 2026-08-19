#!/usr/bin/env python
"""Query and manage a TreeWiki repository with ACL-first retrieval."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
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
from memory_policy import (
    CURRENT_CONFIG_VERSION,
    MEMORY_LAYOUT_VERSION,
    MEMORY_SUBJECT_RE,
    MemoryPolicyError,
    approve_l3,
    canonical_digest,
    evidence_digest_for_metadata,
    l3_candidate_groups,
    l3_approval_eligibility,
    plan_memory_layout,
    render_memory_document,
    require_config_v3,
    validate_shared_memory,
)
from upgrade import (
    UpgradeErrorCode,
    UpgradeException,
    apply_upgrade,
    diagnose_upgrade,
    exit_code_for_exception,
    exit_code_for_report,
)
from claude_alias import ClaudeAliasError, apply_alias, plan_alias
from document_history import (
    DocumentHistoryError,
    apply_document_move,
    apply_document_plan,
    apply_verification,
    history_path_for,
    plan_documents,
    plan_document_move,
    plan_verification,
    read_history,
)
from okf_v02 import export_concept


TOKEN_RE = re.compile(r"[\w가-힣-]+", re.UNICODE)
SUBJECT_RE = re.compile(r"^(user|role|agent|team):[^:\s]+$")
def repository_config(root: Path) -> dict[str, Any]:
    path = root / ".knowledge" / "config.yml"
    if not path.exists():
        raise ValueError(".knowledge/config.yml not found; use TreeWiki bootstrap mode")
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
        if memory.get("subject") not in {args.principal, args.team}:
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


def l3_candidates(
    records: list[dict[str, Any]], minimum_sources: int, subject: str | None = None
) -> list[dict[str, Any]]:
    """Expose the canonical claim-group policy without reimplementing it in the CLI."""

    return l3_candidate_groups(records, minimum_sources, subject)


def query_l3_candidates(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve()
    config = repository_config(root)
    subjects = identity_subjects(args)
    records = allowed_records(load_records(root, config), config, subjects, include_inactive=True)
    memory = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    hooks = config.get("hooks") if isinstance(config.get("hooks"), dict) else {}
    l3 = hooks.get("l3") if isinstance(hooks.get("l3"), dict) else {}
    minimum = max(2, int(l3.get("minimum_sources", memory.get("persona_requires_sources", 2))))
    if args.subject is not None and not MEMORY_SUBJECT_RE.fullmatch(args.subject):
        raise ValueError("subject must use user:<id> or team:<id> syntax")
    candidates = l3_candidates(records, minimum, args.subject)
    prepared: list[dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        if item["status"] in {"eligible", "update_eligible", "supersede_eligible"}:
            item["proposal_status"] = "proposed"
        prepared.append(item)
    if args.json:
        print(
            json.dumps(
                {"schema": "treewiki.l3-candidates/v2", "candidates": prepared},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if not candidates:
        print("NO L3 CLAIM GROUPS")
        return 0
    for item in prepared:
        print(
            f"{item['subject']}\t{item['scope']}\tcategory={item['category']}\t"
            f"kind={item['kind']}\t{item['claim_key']}="
            f"{item['claim_value']}\tstatus={item['status']}\t"
            f"evidence={item['evidence_count']}/{item['minimum_sources']}\t"
            f"ids={','.join(item['evidence_ids'])}"
        )
    return 0


def _readable_record_by_id(
    root: Path, config: dict[str, Any], args: argparse.Namespace, document_id: str
) -> dict[str, Any]:
    subjects = identity_subjects(args)
    records = allowed_records(
        load_records(root, config), config, subjects, include_inactive=True
    )
    record = next(
        (item for item in records if item["metadata"].get("id") == document_id), None
    )
    if record is None:
        raise ValueError("document was not found or is not readable by this identity")
    return record


def query_history(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve(strict=True)
    config = repository_config(root)
    record = _readable_record_by_id(root, config, args, args.document_id)
    document = root / record["path"]
    sidecar = history_path_for(document, args.document_id)
    events = read_history(sidecar)
    payload = {
        "schema": "treewiki.document-history-query/v1",
        "document_id": args.document_id,
        "events": events,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    elif not events:
        print("NO DOCUMENT HISTORY")
    else:
        for event in events:
            print(
                f"{event['seq']}\t{event['at']}\t{event['event']}\t"
                f"revision={event['revision']}\tactor={event['actor']}"
            )
    return 0


def query_okf_export(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve(strict=True)
    config = repository_config(root)
    record = _readable_record_by_id(root, config, args, args.document_id)
    document = root / record["path"]
    history = read_history(history_path_for(document, args.document_id))
    concept = export_concept(record["metadata"], record["body"], history)
    payload = {
        "schema": "treewiki.okf-export/v1",
        "document_id": args.document_id,
        "concept": concept,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def print_upgrade_payload(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
        return
    overall = payload.get("overall")
    if isinstance(overall, dict):
        print(f"STATUS {str(overall.get('status', 'unknown')).upper()}")
        print(str(overall.get("summary", "")))
        print(f"PLAN ID {overall.get('plan_id', '')}")
        for component in payload.get("components", []):
            if isinstance(component, dict):
                print(f"  {component.get('id')}\t{component.get('status')}")
        for action in payload.get("actions", []):
            if isinstance(action, dict):
                print(f"ACTION {action.get('stage')}\t{action.get('id')}")
        return
    print(f"STATUS {payload.get('status', 'unknown')}")
    if payload.get("transaction_id"):
        print(f"TRANSACTION {payload['transaction_id']}")
    for action_id in payload.get("completed_actions", []):
                print(f"COMPLETED {action_id}")


def _cli_memory_layout_planner(
    root: Path,
    config: dict[str, Any],
    approved_ids: list[str] | tuple[str, ...],
    *,
    approvals: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Represent an unapproved memory-layout review without inventing mutation actions."""

    if not approved_ids:
        return {
            "schema": "treewiki.memory-layout-plan/v1",
            "approved_ids": [],
            "actions": [],
            "aggregate_lineage_digest": canonical_digest([]),
        }
    return plan_memory_layout(root, config, approved_ids, approvals=approvals)


_MEMORY_APPROVAL_FIELDS = {
    "level",
    "status",
    "subject",
    "scope",
    "kind",
    "claim_key",
    "claim_value",
    "confidence",
    "access",
    "sharing",
    "sensitivity_review",
}
_ACCESS_APPROVAL_FIELDS = {"owner", "team", "grants", "sensitive"}
_SHARING_APPROVAL_FIELDS = {
    "authored_by",
    "shared_by",
    "shared_at",
    "approved_by",
    "approved_at",
    "evidence_digest",
    "source_ref",
    "source_hash",
    "source_machine",
    "work_unit_id",
}


def load_memory_approval_file(value: str | None) -> dict[str, dict[str, Any]]:
    """Load a bounded local approval mapping without reflecting its path or values."""

    if value is None:
        return {}
    supplied = Path(value)
    try:
        if supplied.is_symlink() or not supplied.is_file():
            raise ValueError("--memory-approval-file must be a regular, non-symlink file")
        if supplied.stat().st_size > 1024 * 1024:
            raise ValueError("--memory-approval-file exceeds the 1 MiB limit")
        loaded = yaml.safe_load(supplied.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("--memory-approval-file is unreadable or invalid UTF-8 YAML") from exc
    if not isinstance(loaded, dict):
        raise ValueError("--memory-approval-file must contain an approval mapping")
    if "approvals" in loaded:
        if set(loaded) != {"approvals"} or not isinstance(loaded["approvals"], dict):
            raise ValueError("the approvals wrapper must be the only top-level field")
        loaded = loaded["approvals"]
    result: dict[str, dict[str, Any]] = {}
    for memory_id, overlay in loaded.items():
        if not isinstance(memory_id, str) or not memory_id.strip() or not isinstance(overlay, dict):
            raise ValueError("each memory approval must map one non-empty ID to a mapping")
        if memory_id != memory_id.strip() or memory_id in result:
            raise ValueError("memory approval IDs must be unique and canonical")
        unknown = set(overlay) - _MEMORY_APPROVAL_FIELDS
        if unknown:
            raise ValueError("memory approval contains unsupported overlay fields")
        for field, allowed in (
            ("access", _ACCESS_APPROVAL_FIELDS),
            ("sharing", _SHARING_APPROVAL_FIELDS),
        ):
            nested = overlay.get(field)
            if nested is not None and (
                not isinstance(nested, dict) or bool(set(nested) - allowed)
            ):
                raise ValueError(f"memory approval {field} overlay is invalid")
        review = overlay.get("sensitivity_review")
        if review is not None and (
            not isinstance(review, dict)
            or set(review) != {"decision", "reviewed_by", "reviewed_at", "checks"}
        ):
            raise ValueError("memory sensitivity_review has an invalid schema")
        result[memory_id] = copy.deepcopy(overlay)
    return result


def memory_approvals_for_args(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    approval_file = getattr(args, "memory_approval_file", None)
    approvals = load_memory_approval_file(approval_file)
    approved_ids = list(getattr(args, "approve_memory_id", []) or [])
    if approval_file is not None and set(approvals) != set(approved_ids):
        raise ValueError(
            "--memory-approval-file IDs must exactly match repeated --approve-memory-id values"
        )
    return approvals


def manage_upgrade_status(args: argparse.Namespace) -> int:
    identity_subjects(args)
    approvals = memory_approvals_for_args(args)
    report = diagnose_upgrade(
        args.repository,
        source=args.source,
        check_latest=args.check_latest,
        offline=args.offline,
        stages=args.stage,
        approved_memory_ids=args.approve_memory_id,
        memory_approvals=approvals,
        approve_global_skill=args.approve_global_skill,
        approve_global_hook=args.approve_global_hook,
        memory_layout_planner=_cli_memory_layout_planner,
    )
    print_upgrade_payload(report, args.json)
    return exit_code_for_report(report)


def manage_upgrade(args: argparse.Namespace) -> int:
    identity_subjects(args)
    approvals = memory_approvals_for_args(args)
    result = apply_upgrade(
        args.repository,
        plan_id=args.plan_id,
        apply=args.apply,
        principal=args.principal,
        team=args.team,
        roles=args.role,
        source=args.source,
        check_latest=args.check_latest,
        offline=args.offline,
        stages=args.stage,
        approved_memory_ids=args.approve_memory_id,
        memory_approvals=approvals,
        approve_global_skill=args.approve_global_skill,
        approve_global_hook=args.approve_global_hook,
        memory_layout_planner=_cli_memory_layout_planner,
    )
    print_upgrade_payload(result, args.json)
    return 0 if args.apply else exit_code_for_report(result)


def _require_memory_config_v3(config: dict[str, Any], operation: str) -> None:
    try:
        require_config_v3(config)
    except MemoryPolicyError as exc:
        code = (
            UpgradeErrorCode.INCOMPATIBLE_NEWER
            if exc.code == "INCOMPATIBLE_NEWER"
            else UpgradeErrorCode.BLOCKED
        )
        raise UpgradeException(
            code,
            f"{operation} requires config v{CURRENT_CONFIG_VERSION}/layout "
            f"{MEMORY_LAYOUT_VERSION}: {exc}",
            component="memory_layout",
            recovery=["Run manage upgrade-status, then an approved manage upgrade transaction."],
        ) from exc


def _l3_review_context(
    root: Path, config: dict[str, Any], args: argparse.Namespace
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str, dict[str, Any] | None]:
    subjects = identity_subjects(args)
    records = allowed_records(
        load_records(root, config), config, subjects, include_inactive=True
    )
    by_id = {
        str(record["metadata"].get("id")): record
        for record in records
        if isinstance(record["metadata"].get("id"), str)
    }
    record = by_id.get(args.document_id)
    if record is None:
        raise UpgradeException(
            UpgradeErrorCode.MANAGEMENT_DENIED,
            "L3 document was not found or is not readable by this identity",
            component="l3_candidate_state",
        )
    metadata = record["metadata"]
    memory = metadata.get("memory") if isinstance(metadata.get("memory"), dict) else {}
    if memory.get("level") != "l3" or metadata.get("status") != "proposed":
        raise UpgradeException(
            UpgradeErrorCode.INVALID_INPUT,
            "l3-review requires a proposed L3 document",
            component="l3_candidate_state",
        )
    scope = memory.get("scope")
    access = metadata.get("access") if isinstance(metadata.get("access"), dict) else {}
    defaults = (
        config.get("access_control")
        if isinstance(config.get("access_control"), dict)
        else {}
    )
    if scope in {"personal", "user"}:
        owner = access.get("owner", defaults.get("default_owner"))
        authorized = args.principal == owner
    elif scope in {"team", "repo", "global"}:
        managers = defaults.get("managers", [defaults.get("default_owner")])
        authorized = isinstance(managers, list) and any(value in subjects for value in managers)
    else:
        raise UpgradeException(
            UpgradeErrorCode.INVALID_INPUT,
            "proposed L3 memory.scope must be user, team, repo, or global",
            component="l3_candidate_state",
        )
    if not authorized:
        raise UpgradeException(
            UpgradeErrorCode.MANAGEMENT_DENIED,
            f"{scope} L3 review is not authorized for {args.principal}",
            component="l3_candidate_state",
        )
    eligibility: dict[str, Any] | None = None
    if args.decision in {"approve", "activate", "supersede"}:
        try:
            eligibility = l3_approval_eligibility(metadata, config=config, by_id=by_id)
        except MemoryPolicyError as exc:
            code = (
                UpgradeErrorCode.STALE_PLAN
                if exc.code == "L3_STALE_EVIDENCE"
                else UpgradeErrorCode.BLOCKED
            )
            raise UpgradeException(
                code,
                str(exc),
                component="l3_candidate_state",
            ) from exc
        digest = str(eligibility["candidate_digest"])
    else:
        digest = evidence_digest_for_metadata(metadata, by_id)
    if args.candidate_digest != digest:
        raise UpgradeException(
            UpgradeErrorCode.STALE_PLAN,
            "candidate evidence digest changed before review",
            component="l3_candidate_state",
        )
    return record, by_id, digest, eligibility


def manage_l3_review(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.candidate_digest):
        raise UpgradeException(
            UpgradeErrorCode.INVALID_INPUT,
            "--candidate-digest must be sha256:<64 lowercase hex>",
            component="l3_candidate_state",
        )
    root = Path(args.repository).resolve(strict=True)
    config = repository_config(root)
    _require_memory_config_v3(config, "l3-review")
    record, by_id, digest, eligibility = _l3_review_context(root, config, args)
    transition = "active" if args.decision in {"approve", "activate", "supersede"} else "rejected"
    result: dict[str, Any] = {
        "schema": "treewiki.l3-review/v1",
        "status": "planned",
        "document_id": args.document_id,
        "decision": args.decision,
        "candidate_digest": digest,
        "actor": args.principal,
        "transition": {"from": "proposed", "to": transition},
        "apply": False,
    }
    if eligibility is not None:
        result["candidate_status"] = eligibility["status"]
        result["evidence_ids"] = eligibility["evidence_ids"]
        result["supersedes_ids"] = eligibility.get("supersedes_ids", [])
    result["plan_id"] = canonical_digest(
        {
            "schema": result["schema"],
            "document_id": args.document_id,
            "decision": args.decision,
            "candidate_digest": digest,
            "actor": args.principal,
            "transition": result["transition"],
            "evidence_ids": result.get("evidence_ids", []),
            "supersedes_ids": result.get("supersedes_ids", []),
        }
    )
    if not args.apply:
        print_upgrade_payload(result, args.json)
        return 0
    if not args.plan_id:
        raise UpgradeException(
            UpgradeErrorCode.INVALID_INPUT,
            "--apply requires --plan-id",
            component="l3_candidate_state",
        )
    if args.plan_id != result["plan_id"]:
        raise UpgradeException(
            UpgradeErrorCode.STALE_PLAN,
            "L3 review plan ID changed before apply",
            component="l3_candidate_state",
        )

    approved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    metadata = record["metadata"]
    try:
        if args.decision in {"approve", "activate", "supersede"}:
            updated = approve_l3(
                metadata,
                approver=args.principal,
                approved_at=approved_at,
                config=config,
                by_id=by_id,
            )
        else:
            updated = copy.deepcopy(metadata)
            updated["status"] = "rejected"
            sharing = (
                updated.get("sharing")
                if isinstance(updated.get("sharing"), dict)
                else {}
            )
            updated["sharing"] = sharing
            sharing["approved_by"] = []
            sharing["approved_at"] = None
            sharing["evidence_digest"] = digest
            sharing["reviewed_by"] = args.principal
            sharing["reviewed_at"] = approved_at
            sharing["review_decision"] = "reject"
    except MemoryPolicyError as exc:
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            str(exc),
            component="l3_candidate_state",
        ) from exc

    target = root / record["path"]
    rendered = render_memory_document(updated, record["body"])
    superseded_updates: list[tuple[Path, str, str]] = []
    if args.decision == "supersede":
        supersedes_ids = list((eligibility or {}).get("supersedes_ids", []))
        if not supersedes_ids:
            raise UpgradeException(
                UpgradeErrorCode.BLOCKED,
                "supersede requires a valid supersedes relation to an active L3",
                component="l3_candidate_state",
            )
        for superseded_id in supersedes_ids:
            prior = by_id.get(superseded_id)
            if prior is None:
                raise UpgradeException(
                    UpgradeErrorCode.STALE_PLAN,
                    f"superseded L3 is no longer readable: {superseded_id}",
                    component="l3_candidate_state",
                )
            prior_metadata = copy.deepcopy(prior["metadata"])
            prior_metadata["status"] = "deprecated"
            prior_path = root / prior["path"]
            superseded_updates.append(
                (
                    prior_path,
                    render_memory_document(prior_metadata, prior["body"]),
                    superseded_id,
                )
            )
    transaction_id = "l3-review-" + uuid.uuid4().hex
    backup_root = root / ".knowledge" / "upgrade-backups" / transaction_id
    backup = backup_root / target.name
    before_sha256 = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    after_sha256 = "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    event = {
        "transaction_id": transaction_id,
        "phase": "l3_review",
        "action_id": f"l3-review:{args.document_id}",
        "state": "planned",
        "target": record["path"],
        "backup": backup.relative_to(root).as_posix(),
        "before_sha256": before_sha256,
        "expected_after_sha256": after_sha256,
        "actor": args.principal,
        "candidate_digest": digest,
        "evidence_ids": sorted(distilled_parent_ids(metadata)),
        "decision": args.decision,
    }
    staged_path: Path | None = None
    review_backups: dict[Path, Path] = {}
    try:
        backup_root.mkdir(parents=True, exist_ok=False)
        shutil.copy2(target, backup)
        review_backups[target] = backup
        for prior_path, _, prior_id in superseded_updates:
            prior_backup = backup_root / f"{prior_id}.md"
            shutil.copy2(prior_path, prior_backup)
            review_backups[prior_path] = prior_backup
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=".treewiki-l3-review-",
            delete=False,
        ) as staged:
            staged.write(rendered)
            staged.flush()
            os.fsync(staged.fileno())
            staged_path = Path(staged.name)
        record_path = backup_root / "transaction.jsonl"
        with record_path.open("a", encoding="utf-8", newline="\n") as handle:
            for state in ("planned", "started"):
                line = {**event, "state": state}
                handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            if _l3_review_context(root, config, args)[2] != digest:
                raise UpgradeException(
                    UpgradeErrorCode.STALE_PLAN,
                    "candidate evidence digest changed immediately before apply",
                    component="l3_candidate_state",
                )
            if "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest() != before_sha256:
                raise UpgradeException(
                    UpgradeErrorCode.STALE_PLAN,
                    "L3 document changed immediately before apply",
                    component="l3_candidate_state",
                )
            os.replace(staged_path, target)
            staged_path = None
            if "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest() != after_sha256:
                raise UpgradeException(
                    UpgradeErrorCode.VERIFICATION_FAILED,
                    "L3 review target failed post-apply verification",
                    component="l3_candidate_state",
                )
            for prior_path, prior_rendered, prior_id in superseded_updates:
                prior_before = "sha256:" + hashlib.sha256(prior_path.read_bytes()).hexdigest()
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="\n",
                    dir=prior_path.parent,
                    prefix=".treewiki-l3-supersede-",
                    delete=False,
                ) as prior_stage:
                    prior_stage.write(prior_rendered)
                    prior_stage.flush()
                    os.fsync(prior_stage.fileno())
                    prior_staged_path = Path(prior_stage.name)
                os.replace(prior_staged_path, prior_path)
                prior_after = "sha256:" + hashlib.sha256(prior_rendered.encode("utf-8")).hexdigest()
                if "sha256:" + hashlib.sha256(prior_path.read_bytes()).hexdigest() != prior_after:
                    raise UpgradeException(
                        UpgradeErrorCode.VERIFICATION_FAILED,
                        f"superseded L3 verification failed: {prior_id}",
                        component="l3_candidate_state",
                    )
                line = {
                    **event,
                    "state": "completed",
                    "action_id": f"l3-deprecate:{prior_id}",
                    "target": prior_path.relative_to(root).as_posix(),
                    "before_sha256": prior_before,
                    "expected_after_sha256": prior_after,
                }
                handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            for state in ("completed", "verified"):
                line = {**event, "state": state}
                handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        lifecycle_plan = plan_documents(
            root,
            [target, *(item[0] for item in superseded_updates)],
            actor=args.principal,
            reason=f"L3 review {args.decision}",
        )
        apply_document_plan(root, lifecycle_plan, plan_id=str(lifecycle_plan["plan_id"]))
    except (UpgradeException, DocumentHistoryError):
        for changed_target, changed_backup in review_backups.items():
            if changed_backup.exists():
                shutil.copy2(changed_backup, changed_target)
        raise
    except (OSError, UnicodeError) as exc:
        raise UpgradeException(
            UpgradeErrorCode.APPLY_FAILED,
            f"L3 review apply failed: {exc}",
            component="l3_candidate_state",
            recovery=[f"Restore the reviewed document from {backup.as_posix()}."],
        ) from exc
    finally:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)

    result.update(
        {
            "status": "APPLIED",
            "apply": True,
            "approved_at": approved_at,
            "transaction_id": transaction_id,
            "backup_path": backup_root.as_posix(),
        }
    )
    print_upgrade_payload(result, args.json)
    return 0


def manage_validate(args: argparse.Namespace) -> int:
    script = Path(__file__).with_name("validate_knowledge.py")
    command = [sys.executable, str(script), str(Path(args.repository).resolve())]
    if args.strict_warnings:
        command.append("--strict-warnings")
    return subprocess.run(command, check=False).returncode


def _public_document_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if not key.startswith("_")}


def _managed_selected_documents(
    root: Path, config: dict[str, Any], supplied: list[str] | None
) -> list[Path]:
    managed = {path.resolve(): path for path in managed_documents(root, config)}
    if not supplied:
        return sorted(managed)
    selected: list[Path] = []
    for value in supplied:
        candidate = (root / value).resolve()
        if candidate not in managed:
            raise ValueError(f"--path is not a managed document: {value}")
        selected.append(candidate)
    return sorted(set(selected))


def _validate_created_l3_candidates(
    root: Path,
    config: dict[str, Any],
    args: argparse.Namespace,
    documents: list[Path],
) -> None:
    created_ids = set(args.created_id or [])
    if not created_ids:
        return
    selected = {path.resolve() for path in documents}
    subjects = identity_subjects(args)
    records = allowed_records(
        load_records(root, config), config, subjects, include_inactive=True
    )
    by_id = {
        str(record["metadata"].get("id")): record
        for record in records
        if isinstance(record["metadata"].get("id"), str)
    }
    for document_id in sorted(created_ids):
        record = by_id.get(document_id)
        if record is None or (root / record["path"]).resolve() not in selected:
            raise ValueError(
                f"--created-id is not a selected readable managed document: {document_id}"
            )
        metadata = record["metadata"]
        memory = metadata.get("memory") if isinstance(metadata.get("memory"), dict) else {}
        if metadata.get("status") != "proposed" or memory.get("level") != "l3":
            continue
        errors = validate_shared_memory(
            record["path"], metadata, config, by_id=by_id
        )
        if errors:
            raise UpgradeException(
                UpgradeErrorCode.BLOCKED,
                "invalid L3 candidate: " + "; ".join(errors),
                component="l3_candidate_state",
            )
        try:
            l3_approval_eligibility(metadata, config=config, by_id=by_id)
        except MemoryPolicyError as exc:
            raise UpgradeException(
                UpgradeErrorCode.BLOCKED,
                f"L3 candidate is not eligible: {exc}",
                component="l3_candidate_state",
            ) from exc


def manage_document_finalize(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve(strict=True)
    config = repository_config(root)
    require_repository_manager(root, config, args)
    _require_memory_config_v3(config, "document-finalize")
    documents = _managed_selected_documents(root, config, args.path)
    _validate_created_l3_candidates(root, config, args, documents)
    plan = plan_documents(
        root,
        documents,
        actor=args.principal,
        created_ids=args.created_id,
        reason=args.reason,
    )
    if not args.apply:
        payload = _public_document_plan(plan)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
        else:
            print(f"STATUS {payload['status'].upper()}")
            print(f"PLAN ID {payload['plan_id']}")
            for action in payload["actions"]:
                print(f"ACTION document-history\t{action['document_id']}\t{action['path']}")
        return 0
    if not args.plan_id:
        raise ValueError("--apply requires --plan-id")
    result = apply_document_plan(root, plan, plan_id=args.plan_id)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"STATUS {result['status']}")
        print(f"TRANSACTION {result['transaction_id']}")
        for event in result["events"]:
            print(
                "NOTICE L3_CANDIDATE_CREATED "
                f"id={event['id']} category={event['category']} kind={event['kind']} "
                f"scope={event['scope']} review=\"{event['review']}\""
            )
    return 0


def manage_document_verify(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.source_digest):
        raise ValueError("--source-digest must be sha256:<64 lowercase hex>")
    root = Path(args.repository).resolve(strict=True)
    config = repository_config(root)
    require_repository_manager(root, config, args)
    _require_memory_config_v3(config, "document-verify")
    record = _readable_record_by_id(root, config, args, args.document_id)
    plan = plan_verification(
        root,
        root / record["path"],
        actor=args.principal,
        source_digest=args.source_digest,
        reason=args.reason,
    )
    public = _public_document_plan(plan)
    if not args.apply:
        print(json.dumps(public, ensure_ascii=False, sort_keys=True, indent=2) if args.json else f"PLAN ID {public['plan_id']}")
        return 0
    if not args.plan_id:
        raise ValueError("--apply requires --plan-id")
    result = apply_verification(root, plan, plan_id=args.plan_id)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"STATUS {result['status']}\nTRANSACTION {result['transaction_id']}")
    return 0


def manage_document_move(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve(strict=True)
    config = repository_config(root)
    require_repository_manager(root, config, args)
    _require_memory_config_v3(config, "document-move")
    record = _readable_record_by_id(root, config, args, args.document_id)
    destination = (root / args.to).resolve()
    plan = plan_document_move(root, root / record["path"], destination)
    public = _public_document_plan(plan)
    if not args.apply:
        print(
            json.dumps(public, ensure_ascii=False, sort_keys=True, indent=2)
            if args.json
            else f"PLAN ID {public['plan_id']}\nTARGET {public['target']}"
        )
        return 0
    if not args.plan_id:
        raise ValueError("--apply requires --plan-id")
    result = apply_document_move(root, plan, plan_id=args.plan_id)
    print(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
        if args.json
        else f"STATUS {result['status']}\nTARGET {result['target']}"
    )
    return 0


def manage_setup_claude_alias(args: argparse.Namespace) -> int:
    root = Path(args.repository).resolve(strict=True)
    config_path = root / ".knowledge" / "config.yml"
    if config_path.is_file():
        config = repository_config(root)
        require_repository_manager(root, config, args)
    else:
        identity_subjects(args)
    skill_root = Path(__file__).resolve().parents[1]
    plugin_root = (
        Path(args.plugin_root).resolve()
        if args.plugin_root
        else Path(__file__).resolve().parents[3] / "plugins" / "treewiki-claude"
    )
    plan = plan_alias(
        root,
        scope=args.scope,
        plugin_root=plugin_root,
        alias_source=skill_root / "assets" / "claude-alias" / "SKILL.md",
    )
    public = _public_document_plan(plan)
    if not args.apply:
        print(json.dumps(public, ensure_ascii=False, sort_keys=True, indent=2) if args.json else f"PLAN ID {public['plan_id']}\nTARGET {public['target']}\nSTATE {public['state']}")
        return 0
    if not args.plan_id:
        raise ValueError("--apply requires --plan-id")
    result = apply_alias(plan, plan_id=args.plan_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) if args.json else f"STATUS {result['status']}\nTARGET {result['target']}")
    if result.get("shadow", {}).get("warning"):
        print("WARNING ALIAS_SHADOWED: user /treewiki overrides the project alias")
    return 0


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
    _require_memory_config_v3(config, "memory-finalize")
    documents = _managed_selected_documents(root, config, args.path)
    _validate_created_l3_candidates(root, config, args, documents)
    plan = plan_documents(
        root,
        documents,
        actor=args.principal,
        created_ids=args.created_id,
        reason="memory finalize",
    )
    print("MEMORY FINALIZE lifecycle -> validate -> rebuild derived indexes")
    if not args.apply:
        print(f"PLAN ID {plan['plan_id']}")
        for action in plan["actions"]:
            print(f"ACTION document-history\t{action['document_id']}\t{action['path']}")
        print("DRY-RUN: pass --apply only after the user authorizes memory storage")
        return 0
    if not args.plan_id:
        raise ValueError("--apply requires --plan-id")
    result = apply_document_plan(root, plan, plan_id=args.plan_id)
    for event in result["events"]:
        print(
            "NOTICE L3_CANDIDATE_CREATED "
            f"id={event['id']} category={event['category']} kind={event['kind']} "
            f"scope={event['scope']} review=\"{event['review']}\""
        )
    validation_args = argparse.Namespace(repository=str(root), strict_warnings=False)
    validation_result = manage_validate(validation_args)
    if validation_result:
        return validation_result
    return manage_reindex(args)


def manage_migrate(args: argparse.Namespace) -> int:
    """Keep the v2 command name as a read-only pointer to the safe v3 transaction."""

    root = Path(args.repository).resolve()
    config = repository_config(root)
    require_repository_manager(root, config, args)
    raw_version = config.get("version")
    if not isinstance(raw_version, int) or isinstance(raw_version, bool) or raw_version < 1:
        raise UpgradeException(
            UpgradeErrorCode.INVALID_INPUT,
            ".knowledge/config.yml version must be a positive integer",
            component="repository_config",
        )
    if raw_version > CURRENT_CONFIG_VERSION:
        raise UpgradeException(
            UpgradeErrorCode.INCOMPATIBLE_NEWER,
            f"repository config version {raw_version} is newer than supported version "
            f"{CURRENT_CONFIG_VERSION}",
            component="repository_config",
        )
    print("DEPRECATED: manage migrate no longer performs direct config or skill-copy mutation.")
    if args.apply or args.sync_skill_copy or args.sync_global_skill_copy:
        print("NO CHANGES APPLIED: legacy mutation flags are ignored for safety.")
    identity = f"--principal {args.principal} --team {args.team}"
    print(
        "NEXT: manage upgrade-status "
        f"{root} {identity} --offline, then manage upgrade with its exact --plan-id."
    )
    return 0 if raw_version == CURRENT_CONFIG_VERSION else 2


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

    history_query = queries.add_parser("history")
    history_query.add_argument("repository")
    history_query.add_argument("--id", dest="document_id", required=True)
    history_query.add_argument("--json", action="store_true")
    add_identity_arguments(history_query)
    history_query.set_defaults(handler=query_history)

    okf_export = queries.add_parser("okf-export")
    okf_export.add_argument("repository")
    okf_export.add_argument("--id", dest="document_id", required=True)
    okf_export.add_argument("--json", action="store_true")
    add_identity_arguments(okf_export)
    okf_export.set_defaults(handler=query_okf_export)

    manage = groups.add_parser("manage", help="Validation and explicitly applied mutations")
    managers = manage.add_subparsers(dest="manage_command", required=True)

    validate = managers.add_parser("validate")
    validate.add_argument("repository")
    validate.add_argument("--strict-warnings", action="store_true")
    validate.set_defaults(handler=manage_validate)

    upgrade_status = managers.add_parser("upgrade-status")
    upgrade_status.add_argument("repository")
    upgrade_status.add_argument("--check-latest", action="store_true")
    upgrade_status.add_argument("--source")
    upgrade_status.add_argument("--offline", action="store_true")
    upgrade_status.add_argument("--stage")
    upgrade_status.add_argument("--approve-memory-id", action="append", default=[])
    upgrade_status.add_argument("--memory-approval-file")
    upgrade_status.add_argument("--approve-global-skill", action="store_true")
    upgrade_status.add_argument("--approve-global-hook", action="store_true")
    upgrade_status.add_argument("--json", action="store_true")
    add_identity_arguments(upgrade_status)
    upgrade_status.set_defaults(handler=manage_upgrade_status)

    upgrade_command = managers.add_parser("upgrade")
    upgrade_command.add_argument("repository")
    upgrade_command.add_argument("--plan-id", required=True)
    upgrade_command.add_argument("--stage")
    upgrade_command.add_argument("--approve-memory-id", action="append", default=[])
    upgrade_command.add_argument("--memory-approval-file")
    upgrade_command.add_argument("--approve-global-skill", action="store_true")
    upgrade_command.add_argument("--approve-global-hook", action="store_true")
    upgrade_command.add_argument("--check-latest", action="store_true")
    upgrade_command.add_argument("--source")
    upgrade_command.add_argument("--offline", action="store_true")
    upgrade_command.add_argument("--apply", action="store_true")
    upgrade_command.add_argument("--json", action="store_true")
    add_identity_arguments(upgrade_command)
    upgrade_command.set_defaults(handler=manage_upgrade)

    l3_review = managers.add_parser("l3-review")
    l3_review.add_argument("repository")
    l3_review.add_argument("document_id")
    l3_review.add_argument("--candidate-digest", required=True)
    l3_review.add_argument("--plan-id")
    l3_review.add_argument(
        "--decision",
        required=True,
        choices=("activate", "reject", "supersede", "approve"),
    )
    l3_review.add_argument("--apply", action="store_true")
    l3_review.add_argument("--json", action="store_true")
    add_identity_arguments(l3_review)
    l3_review.set_defaults(handler=manage_l3_review)

    document_finalize = managers.add_parser("document-finalize")
    document_finalize.add_argument("repository")
    document_finalize.add_argument("--path", action="append")
    document_finalize.add_argument("--created-id", action="append", default=[])
    document_finalize.add_argument("--reason", default="document finalize")
    document_finalize.add_argument("--plan-id")
    document_finalize.add_argument("--apply", action="store_true")
    document_finalize.add_argument("--json", action="store_true")
    add_identity_arguments(document_finalize)
    document_finalize.set_defaults(handler=manage_document_finalize)

    document_verify = managers.add_parser("document-verify")
    document_verify.add_argument("repository")
    document_verify.add_argument("document_id")
    document_verify.add_argument("--source-digest", required=True)
    document_verify.add_argument("--reason", default="source verification")
    document_verify.add_argument("--plan-id")
    document_verify.add_argument("--apply", action="store_true")
    document_verify.add_argument("--json", action="store_true")
    add_identity_arguments(document_verify)
    document_verify.set_defaults(handler=manage_document_verify)

    document_move = managers.add_parser("document-move")
    document_move.add_argument("repository")
    document_move.add_argument("document_id")
    document_move.add_argument("--to", required=True)
    document_move.add_argument("--plan-id")
    document_move.add_argument("--apply", action="store_true")
    document_move.add_argument("--json", action="store_true")
    add_identity_arguments(document_move)
    document_move.set_defaults(handler=manage_document_move)

    setup_claude_alias = managers.add_parser("setup-claude-alias")
    setup_claude_alias.add_argument("repository")
    setup_claude_alias.add_argument("--scope", required=True, choices=("user", "project"))
    setup_claude_alias.add_argument("--plugin-root")
    setup_claude_alias.add_argument("--plan-id")
    setup_claude_alias.add_argument("--apply", action="store_true")
    setup_claude_alias.add_argument("--json", action="store_true")
    add_identity_arguments(setup_claude_alias)
    setup_claude_alias.set_defaults(handler=manage_setup_claude_alias)

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
    memory_finalize.add_argument("--path", action="append")
    memory_finalize.add_argument("--created-id", action="append", default=[])
    memory_finalize.add_argument("--plan-id")
    memory_finalize.add_argument("--apply", action="store_true")
    add_identity_arguments(memory_finalize)
    memory_finalize.set_defaults(handler=manage_memory_finalize)

    migrate = managers.add_parser("migrate")
    migrate.add_argument("repository")
    migrate.add_argument("--apply", action="store_true")
    migrate.add_argument(
        "--sync-skill-copy",
        action="store_true",
        help="legacy LMWiki compatibility flag; accepted but never mutates files",
    )
    migrate.add_argument(
        "--sync-global-skill-copy",
        action="store_true",
        help="legacy global LMWiki compatibility flag; accepted but never mutates files",
    )
    migrate.add_argument(
        "--global-skill-target",
        help="legacy LMWiki target hint; accepted but never used for mutation",
    )
    add_identity_arguments(migrate)
    migrate.set_defaults(handler=manage_migrate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except UpgradeException as exc:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {"schema": "treewiki.error/v1", "error": exc.as_error()},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(f"ERROR {exc.code.value}: {exc}", file=sys.stderr)
            for recovery in exc.recovery:
                print(f"RECOVERY {recovery}", file=sys.stderr)
        return exit_code_for_exception(exc)
    except (DocumentHistoryError, ClaudeAliasError) as exc:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {"schema": "treewiki.error/v1", "error": {"code": exc.code, "message": str(exc)}},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(f"ERROR {exc.code}: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        if getattr(args, "manage_command", None) in {
            "upgrade-status",
            "upgrade",
            "l3-review",
            "document-finalize",
            "document-verify",
            "document-move",
            "setup-claude-alias",
        }:
            wrapped = UpgradeException(UpgradeErrorCode.INVALID_INPUT, str(exc))
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"schema": "treewiki.error/v1", "error": wrapped.as_error()},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            else:
                print(f"ERROR {wrapped.code.value}: {wrapped}", file=sys.stderr)
            return exit_code_for_exception(wrapped)
        print(f"ERROR {exc}")
        return 1
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        print(f"ERROR {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
