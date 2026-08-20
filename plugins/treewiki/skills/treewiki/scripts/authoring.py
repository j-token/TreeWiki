"""Plan and atomically create new managed TreeWiki documents."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from document_history import apply_document_plan, history_path_for, plan_documents


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def plan_new_document(root: Path, target: Path, content: str, document_id: str, *, kind: str) -> dict[str, Any]:
    resolved_root = root.resolve(strict=True)
    resolved_target = target.resolve()
    try:
        relative = resolved_target.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError("document target must stay inside the repository") from exc
    if resolved_target.exists():
        raise ValueError(f"document already exists: {relative}")
    content_digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    public = {
        "schema": "treewiki.new-document-plan/v1",
        "kind": kind,
        "document_id": document_id,
        "path": relative,
        "content_digest": content_digest,
    }
    return {**public, "plan_id": _digest(public), "status": "planned", "_content": content}


def apply_new_document(root: Path, plan: dict[str, Any], *, actor: str, plan_id: str) -> dict[str, Any]:
    if plan_id != plan.get("plan_id"):
        raise ValueError("new document plan is stale")
    target = root.resolve() / str(plan["path"])
    if target.exists():
        raise ValueError(f"document already exists: {plan['path']}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staged_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=target.parent,
            prefix=".treewiki-author-", delete=False,
        ) as staged:
            staged.write(str(plan["_content"]))
            staged.flush()
            os.fsync(staged.fileno())
            staged_path = Path(staged.name)
        os.replace(staged_path, target)
        staged_path = None
        lifecycle = plan_documents(
            root.resolve(), [target], actor=actor,
            created_ids=[str(plan["document_id"])], reason=str(plan["kind"]),
        )
        applied = apply_document_plan(root.resolve(), lifecycle, plan_id=str(lifecycle["plan_id"]))
    except Exception:
        target.unlink(missing_ok=True)
        history_path_for(root, str(plan["document_id"])).unlink(missing_ok=True)
        raise
    finally:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
    return {
        "schema": "treewiki.new-document-result/v1",
        "status": "APPLIED",
        "plan_id": plan_id,
        "path": str(plan["path"]),
        "document_id": str(plan["document_id"]),
        "lifecycle": applied,
    }
