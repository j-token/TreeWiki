"""Read-only diagnostics for TreeWiki document ownership, freshness, and duplication."""

from __future__ import annotations

import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from document_composition import (
    composition_limits,
    document_composition_messages,
)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
    return None


def _git_blob(root: Path, revision: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", f"{revision}:{path}"], check=False,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
    )
    return result.stdout.strip() if result.returncode == 0 else None


def build_governance_report(
    root: Path,
    records: Iterable[dict[str, Any]],
    *,
    composition: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    items = list(records)
    if composition is None:
        composition, _ = composition_limits({})
    findings: list[dict[str, Any]] = []
    bodies: dict[str, list[dict[str, Any]]] = {}
    inbound_supersedes: dict[str, list[str]] = {}
    for record in items:
        metadata = record["metadata"]
        document_id = str(metadata.get("id", ""))
        normalized = re.sub(r"\s+", " ", str(record.get("body", ""))).strip().casefold()
        if normalized:
            bodies.setdefault(normalized, []).append(record)
        composition_errors, composition_warnings = document_composition_messages(
            metadata, str(record.get("body", "")), limits=composition
        )
        for severity, messages in (
            ("error", composition_errors),
            ("warning", composition_warnings),
        ):
            for message in messages:
                if not message.startswith("body "):
                    continue
                findings.append({
                    "kind": "document_composition",
                    "severity": severity,
                    "id": document_id,
                    "path": record["path"],
                    "message": message,
                })
        for relation in metadata.get("relations", []) if isinstance(metadata.get("relations"), list) else []:
            if isinstance(relation, dict) and relation.get("type") == "supersedes" and isinstance(relation.get("target"), str):
                inbound_supersedes.setdefault(str(relation["target"]), []).append(document_id)

        governance = metadata.get("governance") if isinstance(metadata.get("governance"), dict) else {}
        checked = _as_date(governance.get("last_source_check"))
        cadence = governance.get("review_cadence_days")
        if checked and isinstance(cadence, int) and not isinstance(cadence, bool):
            age = (date.today() - checked).days
            if age > cadence:
                findings.append({"kind": "overdue", "id": document_id, "path": record["path"], "age_days": age, "cadence_days": cadence})

        context = metadata.get("context") if isinstance(metadata.get("context"), dict) else {}
        commit = context.get("source_commit")
        source_paths = context.get("source_paths")
        if isinstance(commit, str) and isinstance(source_paths, list):
            changed: list[str] = []
            missing: list[str] = []
            for source_path in source_paths:
                if not isinstance(source_path, str):
                    continue
                prior = _git_blob(root, commit, source_path)
                current = _git_blob(root, "HEAD", source_path)
                if current is None:
                    missing.append(source_path)
                elif prior != current:
                    changed.append(source_path)
            if changed or missing:
                findings.append({"kind": "source_stale", "id": document_id, "path": record["path"], "changed_paths": changed, "missing_paths": missing})

    for record in items:
        metadata = record["metadata"]
        document_id = str(metadata.get("id", ""))
        if metadata.get("status") == "deprecated" and not inbound_supersedes.get(document_id):
            findings.append({"kind": "missing_replacement", "id": document_id, "path": record["path"]})

    for group in bodies.values():
        if len(group) < 2:
            continue
        canonical = sorted(group, key=lambda item: str(item["metadata"].get("id")))[0]
        canonical_id = str(canonical["metadata"].get("id"))
        for duplicate in sorted(group, key=lambda item: str(item["metadata"].get("id")))[1:]:
            metadata = duplicate["metadata"]
            governance = metadata.get("governance") if isinstance(metadata.get("governance"), dict) else {}
            if governance.get("duplicate_of") != canonical_id:
                findings.append({"kind": "duplicate_candidate", "id": metadata.get("id"), "path": duplicate["path"], "canonical_id": canonical_id})
    findings.sort(key=lambda item: (str(item.get("kind")), str(item.get("id"))))
    return {
        "schema": "treewiki.governance-report/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(items),
        "finding_count": len(findings),
        "findings": findings,
    }
