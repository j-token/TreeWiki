"""Append-only, ACL-safe retrieval-gap planning and reporting."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REASONS = {"no_result", "acl_hidden", "stale", "ambiguous"}
STATUSES = {"open", "resolved"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def ledger_path(root: Path, config: dict[str, Any]) -> Path:
    retrieval = config.get("retrieval") if isinstance(config.get("retrieval"), dict) else {}
    relative = str(retrieval.get("gap_ledger_path", ".knowledge/index/retrieval-gaps.jsonl"))
    target = (root / relative).resolve()
    index_root = (root / ".knowledge" / "index").resolve()
    try:
        target.relative_to(index_root)
    except ValueError as exc:
        raise ValueError("retrieval.gap_ledger_path must stay under .knowledge/index/") from exc
    return target


def plan_gap(
    *, query: str, principal: str, team: str, reason: str,
    work_unit: str, status: str = "open", resolution_document_id: str | None = None,
) -> dict[str, Any]:
    normalized = " ".join(query.split())
    if not normalized:
        raise ValueError("retrieval gap query must not be empty")
    if reason not in REASONS:
        raise ValueError(f"retrieval gap reason must be one of {sorted(REASONS)}")
    if status not in STATUSES:
        raise ValueError(f"retrieval gap status must be one of {sorted(STATUSES)}")
    if status == "resolved" and not resolution_document_id:
        raise ValueError("resolved retrieval gaps require resolution_document_id")
    gap_id = _digest({"query": normalized.casefold(), "principal": principal, "team": team, "work_unit": work_unit, "reason": reason})
    event = {
        "schema": "treewiki.retrieval-gap/v1",
        "gap_id": gap_id,
        "query": normalized,
        "principal": principal,
        "team": team,
        "reason": reason,
        "work_unit": work_unit,
        "status": status,
        "resolution_document_id": resolution_document_id,
    }
    plan_id = _digest(event)
    return {**event, "plan_id": plan_id, "status_plan": "planned"}


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid retrieval gap ledger line {line_number}") from exc
        if not isinstance(event, dict) or event.get("schema") != "treewiki.retrieval-gap/v1":
            raise ValueError(f"invalid retrieval gap event line {line_number}")
        events.append(event)
    return events


def append_gap(path: Path, plan: dict[str, Any], *, plan_id: str) -> dict[str, Any]:
    if plan_id != plan.get("plan_id"):
        raise ValueError("retrieval gap plan is stale")
    existing = read_events(path)
    duplicate = next((event for event in reversed(existing) if event.get("plan_id") == plan_id), None)
    if duplicate:
        return {"schema": "treewiki.retrieval-gap-result/v1", "status": "DEDUPED", "event": duplicate}
    event = {key: value for key, value in plan.items() if key != "status_plan"}
    event["recorded_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical(event) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {"schema": "treewiki.retrieval-gap-result/v1", "status": "APPLIED", "event": event}


def folded_report(events: Iterable[dict[str, Any]], *, principal: str | None = None) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        if principal is not None and event.get("principal") != principal:
            continue
        gap_id = str(event.get("gap_id", ""))
        if gap_id:
            latest[gap_id] = event
    return sorted(latest.values(), key=lambda item: (str(item.get("status")), str(item.get("recorded_at", "")), str(item.get("gap_id"))))
