#!/usr/bin/env python
"""Pure memory layout, sharing, lineage, and L3-candidate policy helpers.

The module deliberately keeps canonical-target replacement out of the memory
layout migration seam.  ``apply_memory_layout`` writes only to an explicit
staging directory; the upgrade transaction remains responsible for conflict
checks, atomic replacement, recovery records, and config v3 activation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import yaml


CURRENT_CONFIG_VERSION = 4
MEMORY_LAYOUT_VERSION = 2
PRIVATE_MEMORY_PATH = ".knowledge/private-memory"
SHARED_MEMORY_PATH = "docs/memory"
SHARED_LEVELS = {"l1", "l2", "l3"}
SHARED_STATUSES = {"proposed", "active", "superseded", "rejected", "deprecated"}
CLAIM_KINDS = {
    "fact",
    "information",
    "rule",
    "preference",
    "conditional-action",
    "constraint",
}
L3_KINDS = {"fact", "information", "rule", "preference"}
L3_CATEGORIES = {"knowledge", "persona"}

SUBJECT_RE = re.compile(r"^(?:user|role|agent|team):[^:\s]+$")
MEMORY_SUBJECT_RE = re.compile(r"^(?:user|team):[^:\s]+$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SOURCE_REF_RE = re.compile(r"^local-memory:[A-Za-z0-9._~-]+(?::[A-Za-z0-9._~-]+)*$")
SOURCE_MACHINE_RE = re.compile(r"^install:[A-Za-z0-9._~-]+$")
WORK_UNIT_RE = re.compile(r"^work:[A-Za-z0-9._~-]+$")
UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n(?:\r?\n)?|\Z)",
    re.DOTALL,
)

SENSITIVITY_REVIEW_CHECKS = {
    "secrets",
    "third_party_pii",
    "local_paths",
    "device_names",
}


class MemoryPolicyError(ValueError):
    """A stable, machine-readable memory-policy failure."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def _normalize_relative(path: str | Path) -> str:
    raw = str(path).replace("\\", "/")
    candidate = PurePosixPath(raw)
    if not raw or candidate.is_absolute() or ".." in candidate.parts or re.match(r"^[A-Za-z]:", raw):
        raise MemoryPolicyError("INVALID_MEMORY_PATH", f"memory path must be repository-relative: {raw!r}")
    return candidate.as_posix().rstrip("/")


def _memory_paths(config: Mapping[str, Any]) -> tuple[str, str]:
    memory = config.get("memory") if isinstance(config.get("memory"), Mapping) else {}
    private_path = _normalize_relative(str(memory.get("private_path", PRIVATE_MEMORY_PATH)))
    shared_path = _normalize_relative(str(memory.get("shared_path", SHARED_MEMORY_PATH)))
    return private_path, shared_path


def validate_config_v3(config: Mapping[str, Any]) -> list[str]:
    """Return current config/layout errors; name retained for 0.1 API compatibility."""

    errors: list[str] = []
    version = config.get("version")
    if version != CURRENT_CONFIG_VERSION:
        errors.append(f"version must be {CURRENT_CONFIG_VERSION} for memory writes")
    memory = config.get("memory") if isinstance(config.get("memory"), Mapping) else {}
    if memory.get("layout_version") != MEMORY_LAYOUT_VERSION:
        errors.append(f"memory.layout_version must be {MEMORY_LAYOUT_VERSION}")
    l3 = memory.get("l3") if isinstance(memory.get("l3"), Mapping) else {}
    if l3.get("knowledge_path") != "docs/memory/l3/knowledge":
        errors.append("memory.l3.knowledge_path must be docs/memory/l3/knowledge")
    if l3.get("persona_path") != "docs/memory/l3/persona":
        errors.append("memory.l3.persona_path must be docs/memory/l3/persona")
    history = config.get("history") if isinstance(config.get("history"), Mapping) else {}
    if history.get("schema") != 1 or history.get("sidecar") != "stable-id":
        errors.append("history must declare schema: 1 and sidecar: stable-id")
    try:
        private_path, shared_path = _memory_paths(config)
    except MemoryPolicyError as exc:
        errors.append(str(exc))
        return errors
    if private_path != PRIVATE_MEMORY_PATH:
        errors.append(f"memory.private_path must be {PRIVATE_MEMORY_PATH}")
    if shared_path != SHARED_MEMORY_PATH:
        errors.append(f"memory.shared_path must be {SHARED_MEMORY_PATH}")

    documents = config.get("documents") if isinstance(config.get("documents"), Mapping) else {}
    includes = documents.get("include", [])
    if not isinstance(includes, list):
        errors.append("documents.include must be an array")
    else:
        normalized = {str(value).replace("\\", "/") for value in includes}
        if ".knowledge/private-memory/l0/**/*.md" not in normalized:
            errors.append("documents.include must include .knowledge/private-memory/l0/**/*.md")
        if any(
            value in {".knowledge/private-memory/**/*.md", ".knowledge/private-memory/**"}
            for value in normalized
        ):
            errors.append("documents.include must not include private L1-L3 through a broad private-memory glob")
        if not any(value in {"docs/**/*.md", "docs/memory/**/*.md"} for value in normalized):
            errors.append("documents.include must include shared docs/memory documents")
    excludes = documents.get("exclude", [])
    if not isinstance(excludes, list):
        errors.append("documents.exclude must be an array")
    else:
        protected_roots = ("docs/memory", ".knowledge/private-memory/l0")
        for raw in excludes:
            if not isinstance(raw, str):
                errors.append("documents.exclude must contain only strings")
                continue
            pattern = re.sub(r"/+", "/", raw.replace("\\", "/").strip())
            while pattern.startswith("./"):
                pattern = pattern[2:]
            literal_prefix = re.split(r"[\*\?\[]", pattern, maxsplit=1)[0].rstrip("/")
            if any(
                not literal_prefix
                or literal_prefix == root
                or root.startswith(literal_prefix + "/")
                or literal_prefix.startswith(root + "/")
                for root in protected_roots
            ):
                errors.append(
                    f"documents.exclude must not overlap canonical memory path: {pattern}"
                )
    return errors


def require_config_v3(config: Mapping[str, Any]) -> None:
    """Block every memory mutation from old or unknown-newer runtimes."""

    version = config.get("version")
    if isinstance(version, int) and not isinstance(version, bool) and version > CURRENT_CONFIG_VERSION:
        raise MemoryPolicyError(
            "INCOMPATIBLE_NEWER",
            f"config version {version} is newer than supported version {CURRENT_CONFIG_VERSION}",
        )
    errors = validate_config_v3(config)
    if errors:
        raise MemoryPolicyError("CONFIG_UPGRADE_REQUIRED", "; ".join(errors), details={"errors": errors})


def classify_memory_path(path: str | Path, config: Mapping[str, Any] | None = None) -> str | None:
    """Return ``l0``, ``legacy-l1``.., ``shared-l1``.., or ``None``."""

    rel = _normalize_relative(path)
    private_path, shared_path = _memory_paths(config or {})
    for level in ("l0", "l1", "l2", "l3"):
        prefix = f"{private_path}/{level}/"
        if rel.startswith(prefix):
            return level if level == "l0" else f"legacy-{level}"
    for level in sorted(SHARED_LEVELS):
        if rel.startswith(f"{shared_path}/{level}/"):
            return f"shared-{level}"
    return None


def assert_memory_mutation_allowed(
    path: str | Path,
    *,
    approved_targets: Iterable[str | Path] = (),
    config: Mapping[str, Any] | None = None,
) -> str:
    """Enforce the upgrade hard-deny list for one prospective write target."""

    rel = _normalize_relative(path)
    classification = classify_memory_path(rel, config)
    if classification == "l0":
        raise MemoryPolicyError("L0_HARD_DENY", f"L0 is immutable to upgrade operations: {rel}")
    if classification and classification.startswith("legacy-"):
        raise MemoryPolicyError(
            "LEGACY_PRIVATE_MEMORY_HARD_DENY",
            f"legacy private L1-L3 may be read but not mutated: {rel}",
        )
    allowed = {_normalize_relative(value) for value in approved_targets}
    if not classification or not classification.startswith("shared-") or rel not in allowed:
        raise MemoryPolicyError("UNAPPROVED_MEMORY_TARGET", f"memory target was not explicitly approved: {rel}")
    return rel


def validate_approved_ids(
    approved_ids: Iterable[str], available_ids: Iterable[str]
) -> tuple[str, ...]:
    """Validate and canonicalize an exact explicit memory-ID approval list."""

    values = list(approved_ids)
    if not values:
        raise MemoryPolicyError("MEMORY_APPROVAL_REQUIRED", "at least one memory ID must be approved")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise MemoryPolicyError("INVALID_MEMORY_APPROVAL", "approved memory IDs must be non-empty strings")
    normalized = [value.strip() for value in values]
    if len(normalized) != len(set(normalized)):
        raise MemoryPolicyError("DUPLICATE_MEMORY_APPROVAL", "approved memory IDs must be unique")
    available = set(available_ids)
    unknown = sorted(set(normalized) - available)
    if unknown:
        raise MemoryPolicyError(
            "UNKNOWN_MEMORY_APPROVAL",
            f"approved memory IDs were not found: {', '.join(unknown)}",
            details={"unknown_ids": unknown},
        )
    return tuple(sorted(normalized))


def _candidate_token(value: str, *, fallback: str) -> str:
    token = re.sub(r"[^a-z0-9._~-]+", "-", value.lower()).strip("-")
    return token or fallback


def _legacy_review_candidates(
    metadata: Mapping[str, Any], body: str, *, level: str
) -> dict[str, Any]:
    """Return opaque, deterministic review hints without body or path disclosure."""

    doc_id = str(metadata.get("id", "legacy-memory"))
    memory = metadata.get("memory") if isinstance(metadata.get("memory"), Mapping) else {}
    access = metadata.get("access") if isinstance(metadata.get("access"), Mapping) else {}
    visibility = str(access.get("visibility", "unknown"))
    owner = access.get("owner")
    team = access.get("team")
    existing_scope = memory.get("scope")
    if existing_scope == "team" or visibility in {"team", "public"}:
        subject = team if isinstance(team, str) and MEMORY_SUBJECT_RE.match(team) else owner
        scope = "team" if isinstance(subject, str) and subject.startswith("team:") else "personal"
    else:
        subject = owner if isinstance(owner, str) and MEMORY_SUBJECT_RE.match(owner) else team
        scope = "personal" if isinstance(subject, str) and subject.startswith("user:") else "team"
    subject_candidate = subject if isinstance(subject, str) and MEMORY_SUBJECT_RE.match(subject) else None
    # Candidate identifiers are derived from the stable document ID only. Do
    # not expose a per-file or body-derived hash in status output.
    opaque = hashlib.sha256(doc_id.encode("utf-8")).hexdigest()[:16]
    claim_key = memory.get("claim_key")
    claim_value = memory.get("claim_value")
    sharing = metadata.get("sharing") if isinstance(metadata.get("sharing"), Mapping) else {}
    work_unit = sharing.get("work_unit_id")
    return {
        "target_level": level,
        "subject_candidate": subject_candidate,
        "scope_candidate": scope,
        "claim_key_candidate": (
            claim_key
            if isinstance(claim_key, str) and claim_key
            else f"legacy.{_candidate_token(doc_id, fallback=opaque)}"
        ),
        "claim_value_candidate": (
            claim_value
            if isinstance(claim_value, str) and claim_value
            else f"legacy-review:{opaque}"
        ),
        "work_unit_id_candidate": (
            work_unit
            if isinstance(work_unit, str) and WORK_UNIT_RE.match(work_unit)
            else f"work:legacy-{opaque}"
        ),
    }


def _legacy_disposition(
    metadata: Mapping[str, Any],
    body: str,
    *,
    level: str,
    approval: Mapping[str, Any] | None,
    local_l0_ids: Iterable[str],
    allowed_shared_ids: Iterable[str],
    authorized_reviewers: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    candidates = _legacy_review_candidates(metadata, body, level=level)
    access = metadata.get("access") if isinstance(metadata.get("access"), Mapping) else {}
    visibility = str(access.get("visibility", "unknown"))
    reasons: list[str] = []
    is_sensitive = (
        visibility in {"private", "restricted"}
        or metadata.get("sensitive") is True
        or access.get("sensitive") is True
    )
    if is_sensitive:
        review = approval.get("sensitivity_review") if isinstance(approval, Mapping) else None
        reviewer = review.get("reviewed_by") if isinstance(review, Mapping) else None
        checks = review.get("checks") if isinstance(review, Mapping) else None
        valid_review = (
            isinstance(review, Mapping)
            and review.get("decision") == "share"
            and isinstance(reviewer, str)
            and reviewer.startswith("user:")
            and SUBJECT_RE.match(reviewer) is not None
            and reviewer in set(authorized_reviewers)
            and _valid_timestamp(review.get("reviewed_at"))
            and isinstance(checks, list)
            and all(isinstance(check, str) for check in checks)
            and len(checks) == len(set(checks))
            and set(checks) == SENSITIVITY_REVIEW_CHECKS
        )
        if not valid_review:
            reasons.append("sensitive_visibility_review_required")
            return (
                {
                    "id": str(metadata.get("id", "invalid")),
                    "level": level,
                    "visibility": visibility,
                    "disposition": "blocked_sensitive",
                    **candidates,
                    "review_reasons": reasons,
                },
                None,
            )

    effective_approval = dict(approval or {})
    try:
        converted = build_shared_copy(
            metadata,
            body,
            approval=effective_approval,
            local_l0_ids=local_l0_ids,
            allowed_shared_ids=allowed_shared_ids,
        )
    except MemoryPolicyError as exc:
        memory = metadata.get("memory") if isinstance(metadata.get("memory"), Mapping) else {}
        subject = memory.get("subject")
        if not isinstance(subject, str) or not MEMORY_SUBJECT_RE.match(subject):
            reasons.append("subject_confirmation_required")
        if memory.get("kind") in CLAIM_KINDS and (
            not isinstance(memory.get("claim_key"), str)
            or not memory.get("claim_key")
            or not isinstance(memory.get("claim_value"), str)
            or not memory.get("claim_value")
        ):
            reasons.append("claim_confirmation_required")
        sharing = metadata.get("sharing")
        if not isinstance(sharing, Mapping) or not isinstance(
            sharing.get("work_unit_id") if isinstance(sharing, Mapping) else None, str
        ):
            reasons.append("sharing_metadata_confirmation_required")
        if not reasons:
            reasons.append(exc.code.lower())
        return (
            {
                "id": str(metadata.get("id", "invalid")),
                "level": level,
                "visibility": visibility,
                "disposition": "needs_claim_review",
                **candidates,
                "review_reasons": sorted(set(reasons)),
            },
            None,
        )

    return (
        {
            "id": str(metadata.get("id", "invalid")),
            "level": level,
            "visibility": visibility,
            "disposition": "share",
            **candidates,
            "review_reasons": [],
        },
        converted,
    )


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def body_sha256(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(content: str | bytes) -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _metadata(record: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = record.get("metadata")
    return nested if isinstance(nested, Mapping) else record


def _record_body(record: Mapping[str, Any]) -> str:
    value = record.get("body", "")
    return value if isinstance(value, str) else ""


def _distilled_targets(metadata: Mapping[str, Any]) -> list[str]:
    relations = metadata.get("relations")
    if not isinstance(relations, list):
        return []
    return [
        str(item["target"])
        for item in relations
        if isinstance(item, Mapping)
        and item.get("type") == "distilled_from"
        and isinstance(item.get("target"), str)
    ]


def top_level_provenance(
    record: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]
) -> set[str]:
    """Resolve top-level lineage without double-counting L1→L2 derivatives."""

    visiting: set[str] = set()
    memo: dict[str, frozenset[str]] = {}

    def visit(current: Mapping[str, Any]) -> set[str]:
        metadata = _metadata(current)
        doc_id = str(metadata.get("id", ""))
        if doc_id and doc_id in memo:
            return set(memo[doc_id])
        if doc_id and doc_id in visiting:
            return set()
        if doc_id:
            visiting.add(doc_id)
        try:
            parents = [by_id[target] for target in _distilled_targets(metadata) if target in by_id]
            roots: set[str] = set()
            for parent in parents:
                roots.update(visit(parent))
            if not roots:
                sharing = metadata.get("sharing") if isinstance(metadata.get("sharing"), Mapping) else {}
                source_ref = sharing.get("source_ref")
                source_hash = sharing.get("source_hash")
                if isinstance(source_ref, str) and source_ref:
                    roots = {f"{source_ref}|{source_hash if isinstance(source_hash, str) else ''}"}
                else:
                    provenance = metadata.get("provenance")
                    if isinstance(provenance, list):
                        for item in provenance:
                            if isinstance(item, str) and item:
                                roots.add(item)
                            elif isinstance(item, Mapping):
                                source = item.get("source", item.get("path"))
                                if isinstance(source, str) and source:
                                    roots.add(source)
                    if not roots and doc_id:
                        roots = {f"document:{doc_id}"}
            if doc_id:
                memo[doc_id] = frozenset(roots)
            return roots
        finally:
            if doc_id:
                visiting.discard(doc_id)

    return visit(record)


def lineage_equivalence_digest(
    stable_id: str,
    body_hash: str,
    level: str,
    relation_mapping: Sequence[Mapping[str, Any]],
) -> str:
    normalized_relations = sorted(
        (dict(item) for item in relation_mapping),
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
    return canonical_digest(
        {
            "id": stable_id,
            "body_sha256": body_hash,
            "level": level,
            "relation_mapping": normalized_relations,
        }
    )


def evidence_digest_for_metadata(
    metadata: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]] | None = None
) -> str:
    """Digest current evidence without embedding body, path, or machine identity."""

    by_id = by_id or {}
    targets = _distilled_targets(metadata)
    evidence: list[dict[str, Any]] = []
    for target in sorted(targets):
        parent = by_id.get(target)
        if parent is None:
            evidence.append({"id": target, "missing": True})
            continue
        parent_meta = _metadata(parent)
        sharing = parent_meta.get("sharing") if isinstance(parent_meta.get("sharing"), Mapping) else {}
        evidence.append(
            {
                "id": target,
                "source_ref": sharing.get("source_ref"),
                "source_hash": sharing.get("source_hash"),
                "work_unit_id": sharing.get("work_unit_id"),
            }
        )
    if not evidence:
        sharing = metadata.get("sharing") if isinstance(metadata.get("sharing"), Mapping) else {}
        evidence.append(
            {
                "source_ref": sharing.get("source_ref"),
                "source_hash": sharing.get("source_hash"),
                "work_unit_id": sharing.get("work_unit_id"),
            }
        )
    return canonical_digest(evidence)


def _valid_timestamp(value: Any, *, nullable: bool = False) -> bool:
    return value is None if nullable and value is None else isinstance(value, str) and bool(UTC_TIMESTAMP_RE.match(value))


def validate_shared_memory(
    rel_path: str,
    metadata: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """Validate canonical L0/shared placement and the sharing lifecycle contract."""

    errors: list[str] = []
    memory = metadata.get("memory") if isinstance(metadata.get("memory"), Mapping) else {}
    level = memory.get("level")
    classification = classify_memory_path(rel_path, config)
    version = config.get("version")
    if version == CURRENT_CONFIG_VERSION:
        if classification == "l0" and level != "l0":
            errors.append("private l0 path requires memory.level l0")
        if classification and classification.startswith("legacy-"):
            errors.append("current config permits only L0 under memory.private_path")
        if level == "l0" and classification != "l0":
            errors.append("L0 must be stored under .knowledge/private-memory/l0")
        if level in SHARED_LEVELS and classification != f"shared-{level}":
            errors.append(f"{level} must be stored under docs/memory/{level}")
    if not classification or not classification.startswith("shared-"):
        return errors

    if level not in SHARED_LEVELS:
        errors.append("shared memory path requires memory.level l1, l2, or l3")
        return errors
    subject = memory.get("subject")
    if not isinstance(subject, str) or not MEMORY_SUBJECT_RE.match(subject):
        errors.append("shared memory.subject must use user:<id> or team:<id>")
    scope = memory.get("scope")
    allowed_scopes = {"user", "team", "repo", "global"}
    if version != CURRENT_CONFIG_VERSION:
        allowed_scopes.add("personal")
    if scope not in allowed_scopes:
        errors.append("shared memory.scope must be user, team, repo, or global")
    elif isinstance(subject, str):
        if scope in {"personal", "user"} and not subject.startswith("user:"):
            errors.append("personal/user memory.scope requires a user:* subject")
        if scope == "team" and not subject.startswith("team:"):
            errors.append("team memory.scope requires a team:* subject")
    claim_key = memory.get("claim_key")
    claim_value = memory.get("claim_value")
    if (claim_key is None) != (claim_value is None):
        errors.append("memory.claim_key and memory.claim_value must be declared together")
    if memory.get("kind") in CLAIM_KINDS and (
        not isinstance(claim_key, str) or not claim_key or not isinstance(claim_value, str) or not claim_value
    ):
        errors.append("L3-promotable preference/conditional-action/constraint requires claim_key and claim_value")

    if level == "l3" and isinstance(version, int) and version >= 4:
        l3_kind = memory.get("kind")
        category = metadata.get("category", "persona" if l3_kind == "preference" else "knowledge")
        if l3_kind not in L3_KINDS:
            errors.append("L3 memory.kind must be fact, information, rule, or preference")
        if category not in L3_CATEGORIES:
            errors.append("L3 category must be knowledge or persona")
        if l3_kind == "preference" and category != "persona":
            errors.append("L3 preference must use category persona")
        if l3_kind != "preference" and category != "knowledge":
            errors.append("L3 fact/information/rule must use category knowledge")

    status = metadata.get("status")
    if status not in SHARED_STATUSES:
        errors.append(f"shared memory status must be one of {', '.join(sorted(SHARED_STATUSES))}")
    if level in {"l1", "l2"} and status == "proposed":
        errors.append("shared L1/L2 must be approved before being stored; proposed is L3-only")

    sharing = metadata.get("sharing")
    if not isinstance(sharing, Mapping):
        errors.append("shared memory requires a sharing mapping")
        return errors
    authored_by = sharing.get("authored_by")
    if not isinstance(authored_by, str) or not SUBJECT_RE.match(authored_by):
        errors.append("sharing.authored_by must be a valid subject")
    for field in ("shared_by", "approved_by"):
        values = sharing.get(field)
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not SUBJECT_RE.match(value) for value in values
        ):
            errors.append(f"sharing.{field} must be an array of valid subjects")
    shared_by = sharing.get("shared_by")
    if not isinstance(shared_by, list) or not shared_by:
        errors.append("sharing.shared_by must not be empty")
    if not _valid_timestamp(sharing.get("shared_at")):
        errors.append("sharing.shared_at must be an ISO-8601 timestamp with timezone")
    if not isinstance(sharing.get("source_ref"), str) or not SOURCE_REF_RE.match(str(sharing.get("source_ref"))):
        errors.append("sharing.source_ref must be an opaque local-memory:* reference")
    if not isinstance(sharing.get("source_hash"), str) or not SHA256_RE.match(str(sharing.get("source_hash"))):
        errors.append("sharing.source_hash must be sha256:<64 lowercase hex>")
    if not isinstance(sharing.get("source_machine"), str) or not SOURCE_MACHINE_RE.match(str(sharing.get("source_machine"))):
        errors.append("sharing.source_machine must be an opaque install:* identifier")
    if not isinstance(sharing.get("work_unit_id"), str) or not WORK_UNIT_RE.match(str(sharing.get("work_unit_id"))):
        errors.append("sharing.work_unit_id must be an opaque work:* identifier")
    if not isinstance(sharing.get("evidence_digest"), str) or not SHA256_RE.match(str(sharing.get("evidence_digest"))):
        errors.append("sharing.evidence_digest must be sha256:<64 lowercase hex>")

    approved_by = sharing.get("approved_by")
    approved_at = sharing.get("approved_at")
    if level == "l3" and status == "proposed":
        if approved_by != [] or approved_at is not None:
            errors.append("proposed L3 must use approved_by: [] and approved_at: null")
    elif status == "active":
        if not isinstance(approved_by, list) or not approved_by:
            errors.append("active shared memory requires non-empty sharing.approved_by")
        if not _valid_timestamp(approved_at):
            errors.append("active shared memory requires sharing.approved_at")

    if level == "l3" and status == "active":
        access = metadata.get("access") if isinstance(metadata.get("access"), Mapping) else {}
        owner = access.get("owner")
        managers_config = config.get("access_control") if isinstance(config.get("access_control"), Mapping) else {}
        managers = managers_config.get("managers", [])
        approvers = set(approved_by) if isinstance(approved_by, list) else set()
        if scope in {"personal", "user"} and owner not in approvers:
            errors.append("active user L3 must be approved by access.owner")
        if scope in {"team", "repo", "global"} and (
            not isinstance(managers, list) or not approvers.intersection(managers)
        ):
            errors.append("active team/repo/global L3 must be approved by a configured manager")
        if by_id is not None and sharing.get("evidence_digest") != evidence_digest_for_metadata(metadata, by_id):
            errors.append("active L3 sharing.evidence_digest is stale for its current evidence")
    return errors


def _maximum_independent_count(edges: Mapping[str, set[str]]) -> int:
    """Maximum matching: each work unit and provenance root counts at most once."""

    matched: dict[str, str] = {}

    def augment(work: str, seen: set[str]) -> bool:
        for provenance in sorted(edges.get(work, set())):
            if provenance in seen:
                continue
            seen.add(provenance)
            previous = matched.get(provenance)
            if previous is None or augment(previous, seen):
                matched[provenance] = work
                return True
        return False

    count = 0
    for work in sorted(edges):
        if augment(work, set()):
            count += 1
    return count


def _normalized_l3_kind(value: Any) -> str:
    if value == "preference":
        return "preference"
    if value in {"rule", "conditional-action", "constraint"}:
        return "rule"
    if value == "fact":
        return "fact"
    return "information"


def _claim_projection(memory: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """Return category/kind/key/value, honoring an agent-authored convergence projection."""

    projection = memory.get("supports_claim")
    projected = projection if isinstance(projection, Mapping) else memory
    kind = _normalized_l3_kind(projected.get("kind", memory.get("kind")))
    category = str(
        projected.get("category", "persona" if kind == "preference" else "knowledge")
    )
    key = projected.get("claim_key", memory.get("claim_key"))
    value = projected.get("claim_value", memory.get("claim_value"))
    return category, kind, str(key or ""), str(value or "")


def _single_source_qualifier(record: Mapping[str, Any], kind: str) -> str | None:
    metadata = _metadata(record)
    memory = metadata.get("memory") if isinstance(metadata.get("memory"), Mapping) else {}
    sharing = metadata.get("sharing") if isinstance(metadata.get("sharing"), Mapping) else {}
    evidence_mode = memory.get("evidence_mode")
    authored = sharing.get("authored_by")
    explicit_user = evidence_mode == "explicit" and isinstance(authored, str) and authored.startswith("user:")
    authoritative = evidence_mode in {"authoritative", "official", "canonical"} or metadata.get("authority") == "normative"
    if kind == "fact" and authoritative:
        return "authoritative_source"
    if kind == "rule" and (authoritative or explicit_user):
        return "official_or_explicit_rule"
    if kind == "preference" and explicit_user:
        return "explicit_user_preference"
    return None


def _threshold_for_group(
    records: Sequence[Mapping[str, Any]], kind: str, repeated_minimum: int
) -> tuple[int, str]:
    qualifiers = [
        qualifier
        for record in records
        if (qualifier := _single_source_qualifier(record, kind)) is not None
    ]
    if qualifiers:
        return 1, sorted(qualifiers)[0]
    return max(2, repeated_minimum), "independent_evidence"


def _preference_confirmation(records: Sequence[Mapping[str, Any]]) -> bool:
    for record in records:
        metadata = _metadata(record)
        memory = metadata.get("memory") if isinstance(metadata.get("memory"), Mapping) else {}
        confirmed_by = memory.get("confirmed_by")
        if isinstance(confirmed_by, str) and confirmed_by.startswith("user:"):
            return True
    return False


def l3_candidate_groups(
    records: Sequence[Mapping[str, Any]],
    minimum_sources: int = 2,
    subject: str | None = None,
) -> list[dict[str, Any]]:
    """Classify claim groups as insufficient, eligible, conflict, covered, or update."""

    minimum = max(2, int(minimum_sources))
    by_id = {
        str(_metadata(record).get("id")): record
        for record in records
        if isinstance(_metadata(record).get("id"), str)
    }
    grouped: dict[tuple[str, str, str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    values_by_key: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    active_l3: dict[tuple[str, str, str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        metadata = _metadata(record)
        memory = metadata.get("memory") if isinstance(metadata.get("memory"), Mapping) else {}
        category, kind, claim_key, claim_value = _claim_projection(memory)
        key_values = (
            memory.get("subject"),
            memory.get("scope"),
            category,
            kind,
            claim_key,
            claim_value,
        )
        if not all(isinstance(value, str) and value for value in key_values):
            continue
        group_key = tuple(str(value) for value in key_values)
        if subject is not None and group_key[0] != subject:
            continue
        if metadata.get("status") == "active" and memory.get("level") in {"l1", "l2"}:
            grouped[group_key].append(record)
            values_by_key[group_key[:5]].add(group_key[5])
        if metadata.get("status") == "active" and memory.get("level") == "l3":
            active_l3[group_key].append(record)

    results: list[dict[str, Any]] = []
    for group_key in sorted(grouped):
        subject_value, scope, category, kind, claim_key, claim_value = group_key
        group_records = grouped[group_key]
        edges: dict[str, set[str]] = defaultdict(set)
        evidence_ids: list[str] = []
        for record in group_records:
            metadata = _metadata(record)
            sharing = metadata.get("sharing") if isinstance(metadata.get("sharing"), Mapping) else {}
            work_unit = sharing.get("work_unit_id")
            if not isinstance(work_unit, str) or not work_unit:
                continue
            roots = top_level_provenance(record, by_id)
            edges[work_unit].update(roots)
            doc_id = metadata.get("id")
            if isinstance(doc_id, str):
                evidence_ids.append(doc_id)
        evidence_count = _maximum_independent_count(edges)
        required, threshold_reason = _threshold_for_group(group_records, kind, minimum)
        conflict_values = sorted(values_by_key[group_key[:5]])
        if len(conflict_values) > 1:
            status = "conflict"
        elif active_l3.get(group_key):
            covered_ids: set[str] = set()
            for persona in active_l3[group_key]:
                covered_ids.update(_distilled_targets(_metadata(persona)))
            status = "covered" if set(evidence_ids).issubset(covered_ids) else "update_eligible"
        else:
            status = "eligible" if evidence_count >= required else "insufficient_evidence"
            if (
                status == "eligible"
                and kind == "preference"
                and required > 1
                and not _preference_confirmation(group_records)
            ):
                status = "confirmation_required"
        results.append(
            {
                "subject": subject_value,
                "scope": scope,
                "category": category,
                "kind": kind,
                "claim_key": claim_key,
                "claim_value": claim_value,
                "status": status,
                "evidence_count": evidence_count,
                "minimum_sources": required,
                "threshold_reason": threshold_reason,
                "evidence_ids": sorted(set(evidence_ids)),
                "work_unit_ids": sorted(edges),
                "provenance": sorted({item for values in edges.values() for item in values}),
                "conflicting_values": conflict_values if len(conflict_values) > 1 else [],
            }
        )
    return results


def l3_approval_eligibility(
    metadata: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Recompute and validate the exact canonical claim group for one proposal."""

    memory = metadata.get("memory") if isinstance(metadata.get("memory"), Mapping) else {}
    if memory.get("level") != "l3" or metadata.get("status") != "proposed":
        raise MemoryPolicyError("L3_NOT_PROPOSED", "only a proposed L3 may be activated")
    category, kind, claim_key, claim_value = _claim_projection(memory)
    group_key = (
        memory.get("subject"),
        memory.get("scope"),
        category,
        kind,
        claim_key,
        claim_value,
    )
    if not all(isinstance(value, str) and value for value in group_key):
        raise MemoryPolicyError(
            "L3_NOT_ELIGIBLE",
            "proposed L3 requires an exact subject/scope/claim_key/claim_value group",
        )
    hooks = config.get("hooks") if isinstance(config.get("hooks"), Mapping) else {}
    l3_config = hooks.get("l3") if isinstance(hooks.get("l3"), Mapping) else {}
    memory_config = config.get("memory") if isinstance(config.get("memory"), Mapping) else {}
    raw_minimum = l3_config.get(
        "minimum_sources", memory_config.get("persona_requires_sources", 2)
    )
    try:
        minimum = max(2, int(raw_minimum))
    except (TypeError, ValueError) as exc:
        raise MemoryPolicyError(
            "INVALID_L3_POLICY", "L3 minimum_sources must be an integer"
        ) from exc
    groups = l3_candidate_groups(list(by_id.values()), minimum_sources=minimum)
    candidate = next(
        (
            item
            for item in groups
            if tuple(
                item[field]
                for field in (
                    "subject",
                    "scope",
                    "category",
                    "kind",
                    "claim_key",
                    "claim_value",
                )
            )
            == group_key
        ),
        None,
    )
    supersedes_ids = [
        str(item["target"])
        for item in metadata.get("relations", [])
        if isinstance(item, Mapping)
        and item.get("type") == "supersedes"
        and isinstance(item.get("target"), str)
    ] if isinstance(metadata.get("relations"), list) else []
    if candidate is not None and candidate.get("status") == "conflict" and supersedes_ids:
        valid_supersedes = []
        for target in supersedes_ids:
            prior = by_id.get(target)
            prior_meta = _metadata(prior) if isinstance(prior, Mapping) else {}
            prior_memory = prior_meta.get("memory") if isinstance(prior_meta.get("memory"), Mapping) else {}
            prior_category, prior_kind, prior_key, prior_value = _claim_projection(prior_memory)
            if (
                prior_meta.get("status") == "active"
                and prior_memory.get("level") == "l3"
                and prior_memory.get("subject") == group_key[0]
                and prior_memory.get("scope") == group_key[1]
                and (prior_category, prior_kind, prior_key) == group_key[2:5]
                and prior_value != group_key[5]
            ):
                valid_supersedes.append(target)
        if valid_supersedes and set(valid_supersedes) == set(supersedes_ids):
            candidate = {**candidate, "status": "supersede_eligible", "supersedes_ids": sorted(valid_supersedes)}
    if (
        candidate is None
        or candidate.get("status") not in {"eligible", "update_eligible", "supersede_eligible"}
        or int(candidate.get("evidence_count", 0))
        < int(candidate.get("minimum_sources", minimum))
    ):
        status = candidate.get("status") if isinstance(candidate, Mapping) else "insufficient_evidence"
        raise MemoryPolicyError(
            "L3_NOT_ELIGIBLE",
            f"proposed L3 claim group is not eligible: {status}",
            details={"candidate_status": status},
        )
    parent_ids = _distilled_targets(metadata)
    evidence_ids = list(candidate.get("evidence_ids", []))
    if len(parent_ids) != len(set(parent_ids)) or sorted(parent_ids) != sorted(evidence_ids):
        raise MemoryPolicyError(
            "L3_EVIDENCE_MISMATCH",
            "proposed L3 distilled_from IDs do not exactly match canonical evidence IDs",
            details={"expected_evidence_ids": sorted(evidence_ids)},
        )
    for parent_id in evidence_ids:
        parent = by_id.get(parent_id)
        parent_metadata = _metadata(parent) if isinstance(parent, Mapping) else {}
        parent_memory = (
            parent_metadata.get("memory")
            if isinstance(parent_metadata.get("memory"), Mapping)
            else {}
        )
        if (
            parent_metadata.get("status") != "active"
            or parent_memory.get("level") not in {"l1", "l2"}
        ):
            raise MemoryPolicyError(
                "L3_EVIDENCE_MISMATCH",
                "proposed L3 evidence must be active L1/L2 in the canonical projected claim group",
            )
    digest = evidence_digest_for_metadata(metadata, by_id)
    sharing = metadata.get("sharing") if isinstance(metadata.get("sharing"), Mapping) else {}
    if sharing.get("evidence_digest") != digest:
        raise MemoryPolicyError(
            "L3_STALE_EVIDENCE",
            "proposed L3 evidence digest is stale",
            details={"candidate_digest": digest},
        )
    return {**candidate, "candidate_digest": digest}


def _parse_memory_file(path: Path) -> tuple[dict[str, Any], str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise MemoryPolicyError("INVALID_MEMORY_DOCUMENT", f"missing YAML frontmatter: {path.name}")
    metadata = yaml.safe_load(match.group(1)) or {}
    if not isinstance(metadata, dict):
        raise MemoryPolicyError("INVALID_MEMORY_DOCUMENT", f"frontmatter must be a mapping: {path.name}")
    return metadata, text[match.end() :], text


def render_memory_document(metadata: Mapping[str, Any], body: str) -> str:
    frontmatter = yaml.safe_dump(dict(metadata), allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{frontmatter}\n---\n\n{body}"


def build_shared_copy(
    metadata: Mapping[str, Any],
    body: str,
    *,
    approval: Mapping[str, Any],
    local_l0_ids: Iterable[str] = (),
    allowed_shared_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Create one canonical shared metadata copy while preserving ID and body."""

    result = copy.deepcopy(dict(metadata))
    memory = result.get("memory") if isinstance(result.get("memory"), dict) else {}
    result["memory"] = memory
    for field in ("subject", "scope", "claim_key", "claim_value", "kind", "confidence"):
        if field in approval:
            memory[field] = copy.deepcopy(approval[field])
    if memory.get("scope") == "personal":
        memory["scope"] = "user"
    level = str(approval.get("level", memory.get("level", "")))
    if level not in SHARED_LEVELS:
        raise MemoryPolicyError("INVALID_SHARED_LEVEL", f"shared level must be l1, l2, or l3: {level!r}")
    memory["level"] = level
    access = copy.deepcopy(result.get("access")) if isinstance(result.get("access"), dict) else {}
    access_overlay = approval.get("access") if isinstance(approval.get("access"), Mapping) else {}
    access.update(copy.deepcopy(dict(access_overlay)))
    access["visibility"] = "team"
    access.setdefault("grants", [])
    result["access"] = access
    local_l0 = set(local_l0_ids)
    allowed = set(allowed_shared_ids)
    relation_before = copy.deepcopy(result.get("relations", []))
    relation_after: list[dict[str, Any]] = []
    relation_mapping: list[dict[str, Any]] = []
    for relation in relation_before if isinstance(relation_before, list) else []:
        if not isinstance(relation, Mapping):
            continue
        item = dict(relation)
        if item.get("type") != "distilled_from":
            relation_after.append(item)
            relation_mapping.append({"before": item, "after": item, "action": "preserved"})
            continue
        target = item.get("target")
        if target in local_l0:
            relation_mapping.append({"before": item, "after": None, "action": "externalized-local-l0"})
        elif target in allowed:
            relation_after.append(item)
            relation_mapping.append({"before": item, "after": item, "action": "preserved-shared"})
        else:
            relation_mapping.append({"before": item, "after": None, "action": "dropped-unshared"})
    result["relations"] = relation_after

    sharing = copy.deepcopy(result.get("sharing")) if isinstance(result.get("sharing"), dict) else {}
    overlay = approval.get("sharing") if isinstance(approval.get("sharing"), Mapping) else {}
    sharing.update(copy.deepcopy(dict(overlay)))
    result["sharing"] = sharing
    if level == "l3":
        result["status"] = "proposed"
        sharing["approved_by"] = []
        sharing["approved_at"] = None
    else:
        result["status"] = str(approval.get("status", "active"))
    if "evidence_digest" not in sharing:
        sharing["evidence_digest"] = evidence_digest_for_metadata(result)

    doc_id = result.get("id")
    if not isinstance(doc_id, str) or not doc_id:
        raise MemoryPolicyError("INVALID_MEMORY_DOCUMENT", "shared memory requires a stable ID")
    target_config = {
        "version": CURRENT_CONFIG_VERSION,
        "documents": {
            "include": ["docs/**/*.md", ".knowledge/private-memory/l0/**/*.md"]
        },
        "memory": {
            "layout_version": MEMORY_LAYOUT_VERSION,
            "private_path": PRIVATE_MEMORY_PATH,
            "shared_path": SHARED_MEMORY_PATH,
        },
        "access_control": {"managers": list(approval.get("managers", []))},
    }
    policy_errors = validate_shared_memory(
        f"{SHARED_MEMORY_PATH}/{level}/candidate.md", result, target_config
    )
    if policy_errors:
        raise MemoryPolicyError(
            "INCOMPLETE_MEMORY_APPROVAL",
            "; ".join(policy_errors),
            details={"memory_id": doc_id, "errors": policy_errors},
        )
    body_hash = body_sha256(body)
    lineage_digest = lineage_equivalence_digest(doc_id, body_hash, level, relation_mapping)
    return {
        "metadata": result,
        "body": body,
        "body_sha256": body_hash,
        "relation_before": relation_before if isinstance(relation_before, list) else [],
        "relation_after": relation_after,
        "relation_mapping": relation_mapping,
        "lineage_digest": lineage_digest,
    }


def approve_l3(
    metadata: Mapping[str, Any],
    *,
    approver: str,
    approved_at: str,
    config: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return an explicitly approved L3 copy; never mutates the proposal."""

    result = copy.deepcopy(dict(metadata))
    memory = result.get("memory") if isinstance(result.get("memory"), Mapping) else {}
    if memory.get("level") != "l3" or result.get("status") != "proposed":
        raise MemoryPolicyError("L3_NOT_PROPOSED", "only a proposed L3 may be activated")
    if not isinstance(approver, str) or not approver.startswith("user:") or not SUBJECT_RE.match(approver):
        raise MemoryPolicyError("INVALID_L3_APPROVER", "L3 approver must use user:<id>")
    if not _valid_timestamp(approved_at):
        raise MemoryPolicyError("INVALID_L3_APPROVAL_TIME", "approved_at must include a timezone")
    eligibility = l3_approval_eligibility(metadata, config=config, by_id=by_id)
    sharing = result.get("sharing") if isinstance(result.get("sharing"), dict) else {}
    result["sharing"] = sharing
    sharing["approved_by"] = [approver]
    sharing["approved_at"] = approved_at
    sharing["evidence_digest"] = eligibility["candidate_digest"]
    result["status"] = "active"
    errors = validate_shared_memory(
        f"{SHARED_MEMORY_PATH}/l3/candidate.md", result, config, by_id=by_id
    )
    if errors:
        raise MemoryPolicyError(
            "L3_APPROVAL_REJECTED", "; ".join(errors), details={"errors": errors}
        )
    return result


def plan_memory_layout(
    root: Path,
    config: Mapping[str, Any],
    approved_ids: Iterable[str],
    *,
    approvals: Mapping[str, Mapping[str, Any]] | None = None,
    existing_shared_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a deterministic, read-only legacy L1-L3 sharing plan."""

    version = config.get("version")
    if isinstance(version, int) and not isinstance(version, bool) and version > CURRENT_CONFIG_VERSION:
        raise MemoryPolicyError("INCOMPATIBLE_NEWER", f"config version {version} is not supported")
    root = Path(root).resolve()
    private_path, shared_path = _memory_paths(config)
    source_root = root / private_path
    documents: dict[str, dict[str, Any]] = {}
    l0_ids: set[str] = set()
    for path in sorted((source_root / "l0").glob("**/*.md")) if (source_root / "l0").exists() else []:
        metadata, _, _ = _parse_memory_file(path)
        if isinstance(metadata.get("id"), str):
            l0_ids.add(str(metadata["id"]))
    for level in sorted(SHARED_LEVELS):
        level_root = source_root / level
        if not level_root.exists():
            continue
        for path in sorted(level_root.glob("**/*.md")):
            metadata, body, source_text = _parse_memory_file(path)
            doc_id = metadata.get("id")
            if not isinstance(doc_id, str) or not doc_id:
                raise MemoryPolicyError("INVALID_MEMORY_DOCUMENT", f"legacy memory has no stable ID: {path.name}")
            if doc_id in documents:
                raise MemoryPolicyError("DUPLICATE_MEMORY_ID", f"duplicate legacy memory ID: {doc_id}")
            documents[doc_id] = {
                "path": path,
                "metadata": metadata,
                "body": body,
                "source_file_sha256": file_sha256(source_text),
            }
    approved_values = tuple(approved_ids)
    approved = validate_approved_ids(approved_values, documents) if approved_values else ()
    approval_map = approvals or {}
    unknown_approval_metadata = sorted(set(approval_map) - set(documents))
    if unknown_approval_metadata:
        raise MemoryPolicyError(
            "UNKNOWN_MEMORY_APPROVAL",
            f"approval metadata IDs were not found: {', '.join(unknown_approval_metadata)}",
            details={"unknown_ids": unknown_approval_metadata},
        )
    shared_ids = set(existing_shared_ids) | set(documents)
    access_defaults = (
        config.get("access_control")
        if isinstance(config.get("access_control"), Mapping)
        else {}
    )
    configured_managers = {
        value
        for value in access_defaults.get("managers", [])
        if isinstance(value, str) and value.startswith("user:") and SUBJECT_RE.match(value)
    }
    default_owner = access_defaults.get("default_owner")
    if isinstance(default_owner, str) and default_owner.startswith("user:") and SUBJECT_RE.match(default_owner):
        configured_managers.add(default_owner)
    dispositions: list[dict[str, Any]] = []
    eligible_actions: list[dict[str, Any]] = []
    for doc_id in sorted(documents):
        source = documents[doc_id]
        source_memory = (
            source["metadata"].get("memory")
            if isinstance(source["metadata"].get("memory"), Mapping)
            else {}
        )
        source_level = str(source_memory.get("level", ""))
        if source_level not in SHARED_LEVELS:
            source_level = str(source["path"].parent.name)
        source_access = (
            source["metadata"].get("access")
            if isinstance(source["metadata"].get("access"), Mapping)
            else {}
        )
        authorized_reviewers = set(configured_managers)
        source_owner = source_access.get("owner")
        if isinstance(source_owner, str) and source_owner.startswith("user:") and SUBJECT_RE.match(source_owner):
            authorized_reviewers.add(source_owner)
        raw_approval = approval_map.get(doc_id)
        effective_approval = copy.deepcopy(dict(raw_approval)) if isinstance(raw_approval, Mapping) else None
        if effective_approval is not None:
            effective_approval["managers"] = sorted(configured_managers)
        disposition, converted = _legacy_disposition(
            source["metadata"],
            source["body"],
            level=source_level,
            approval=effective_approval,
            local_l0_ids=l0_ids,
            allowed_shared_ids=shared_ids,
            authorized_reviewers=authorized_reviewers,
        )
        dispositions.append(disposition)
        if disposition["disposition"] != "share" or converted is None:
            continue
        level = converted["metadata"]["memory"]["level"]
        target_rel = f"{shared_path}/{level}/{source['path'].name}"
        target = root / target_rel
        rendered = render_memory_document(converted["metadata"], converted["body"])
        expected_hash = file_sha256(rendered)
        if target.exists() and file_sha256(target.read_bytes()) != expected_hash:
            raise MemoryPolicyError(
                "MEMORY_TARGET_CONFLICT",
                f"shared target exists with a different hash for {doc_id}",
                details={"memory_id": doc_id, "target_path": target_rel},
            )
        eligible_actions.append(
            {
                "memory_id": doc_id,
                "source_path": source["path"].relative_to(root).as_posix(),
                "target_path": target_rel,
                "level": level,
                "source_file_sha256": source["source_file_sha256"],
                "body_sha256": converted["body_sha256"],
                "expected_file_sha256": expected_hash,
                "relation_before": converted["relation_before"],
                "relation_after": converted["relation_after"],
                "relation_mapping": converted["relation_mapping"],
                "lineage_digest": converted["lineage_digest"],
                "approval_digest": canonical_digest(raw_approval or {}),
                "metadata": converted["metadata"],
                "body": converted["body"],
                "disposition": "already_present" if target.exists() else "share",
            }
        )
    approval_targets = tuple(
        sorted(item["id"] for item in dispositions if item["disposition"] == "share")
    )
    ineligible = sorted(set(approved) - set(approval_targets))
    if ineligible:
        raise MemoryPolicyError(
            "MEMORY_REVIEW_REQUIRED",
            "approved memory IDs are not in the share disposition set: " + ", ".join(ineligible),
            details={"ineligible_ids": ineligible, "approval_targets": list(approval_targets)},
        )
    actions = [
        action for action in eligible_actions if str(action["memory_id"]) in set(approved)
    ]
    aggregate = canonical_digest(
        [
            {
                "memory_id": action["memory_id"],
                "target_path": action["target_path"],
                "expected_file_sha256": action["expected_file_sha256"],
                "lineage_digest": action["lineage_digest"],
                "approval_digest": action["approval_digest"],
            }
            for action in eligible_actions
        ]
    )
    return {
        "schema": "treewiki.memory-layout-plan/v1",
        "approved_ids": list(approved),
        "approval_targets": list(approval_targets),
        "dispositions": dispositions,
        "actions": actions,
        # Kept local to the upgrade planner. It contains target material but is
        # never emitted in the public disposition inventory.
        "eligible_actions": eligible_actions,
        "aggregate_lineage_digest": aggregate,
    }


def apply_memory_layout(plan: Mapping[str, Any], stage_root: Path) -> list[dict[str, Any]]:
    """Materialize a validated plan under ``stage_root`` only."""

    if plan.get("schema") != "treewiki.memory-layout-plan/v1":
        raise MemoryPolicyError("INVALID_MEMORY_PLAN", "unsupported memory layout plan schema")
    stage_root = Path(stage_root).resolve()
    stage_root.mkdir(parents=True, exist_ok=True)
    staged: list[dict[str, Any]] = []
    actions = plan.get("actions")
    if not isinstance(actions, list):
        raise MemoryPolicyError("INVALID_MEMORY_PLAN", "memory layout plan actions must be an array")
    approved_targets = [action.get("target_path") for action in actions if isinstance(action, Mapping)]
    for action in actions:
        if not isinstance(action, Mapping):
            raise MemoryPolicyError("INVALID_MEMORY_PLAN", "memory layout action must be a mapping")
        target_rel = assert_memory_mutation_allowed(
            str(action.get("target_path", "")), approved_targets=approved_targets
        )
        metadata = action.get("metadata")
        body = action.get("body")
        if not isinstance(metadata, Mapping) or not isinstance(body, str):
            raise MemoryPolicyError("INVALID_MEMORY_PLAN", "memory layout action lacks metadata/body")
        rendered = render_memory_document(metadata, body)
        expected = action.get("expected_file_sha256")
        if file_sha256(rendered) != expected:
            raise MemoryPolicyError("STALE_MEMORY_PLAN", f"rendered content changed for {action.get('memory_id')}")
        staged_path = (stage_root / target_rel).resolve()
        if stage_root not in staged_path.parents:
            raise MemoryPolicyError("INVALID_MEMORY_PATH", "staged target escaped the stage root")
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        if staged_path.exists() and file_sha256(staged_path.read_bytes()) != expected:
            raise MemoryPolicyError("MEMORY_TARGET_CONFLICT", f"staged target differs: {target_rel}")
        staged_path.write_text(rendered, encoding="utf-8", newline="\n")
        staged.append(
            {
                "memory_id": action.get("memory_id"),
                "staged_path": staged_path.relative_to(stage_root).as_posix(),
                "target_path": target_rel,
                "expected_file_sha256": expected,
                "lineage_digest": action.get("lineage_digest"),
            }
        )
    return staged
