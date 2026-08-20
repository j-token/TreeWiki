from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


HISTORY_SCHEMA = "treewiki.document-history/v1"
HISTORY_DIRECTORY = Path(".knowledge/document-history")
PLAN_SCHEMA = "treewiki.document-finalize-plan/v1"
VERIFY_PLAN_SCHEMA = "treewiki.document-verify-plan/v1"
MOVE_PLAN_SCHEMA = "treewiki.document-move-plan/v1"
LIFECYCLE_FIELDS = {
    "created_at",
    "modified_at",
    "verified_at",
    "revision",
    "history_ref",
}
EVENTS = {
    "created",
    "content_changed",
    "metadata_changed",
    "verified",
    "status_changed",
    "migrated",
    "deprecated",
}


class DocumentHistoryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_observed_at(paths: Iterable[Path]) -> str:
    """Return a deterministic observation time for a reproducible dry-run plan."""

    mtimes = [path.stat().st_mtime for path in paths if path.exists()]
    observed = max(mtimes) if mtimes else 0.0
    return datetime.fromtimestamp(observed, timezone.utc).isoformat().replace("+00:00", "Z")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        _plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def parse_document_text(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise DocumentHistoryError("INVALID_DOCUMENT", "document has no YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise DocumentHistoryError("INVALID_DOCUMENT", "document frontmatter is incomplete")
    try:
        loaded = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise DocumentHistoryError("INVALID_DOCUMENT", f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(loaded, dict):
        raise DocumentHistoryError("INVALID_DOCUMENT", "frontmatter must be a mapping")
    body = parts[2]
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    return loaded, body


def parse_document(path: Path) -> tuple[dict[str, Any], str, str]:
    text = path.read_text(encoding="utf-8")
    metadata, body = parse_document_text(text)
    return metadata, body, text


def render_document(metadata: Mapping[str, Any], body: str) -> str:
    frontmatter = yaml.safe_dump(
        _plain(dict(metadata)), allow_unicode=True, sort_keys=False
    ).rstrip()
    normalized_body = body.lstrip("\n")
    separator = "\n\n" if normalized_body else "\n"
    return f"---\n{frontmatter}\n---{separator}{normalized_body}"


def semantic_components(metadata: Mapping[str, Any], body: str) -> dict[str, str]:
    semantic_metadata = {
        key: copy.deepcopy(value)
        for key, value in metadata.items()
        if key not in LIFECYCLE_FIELDS
    }
    metadata_hash = canonical_digest(semantic_metadata)
    body_hash = bytes_digest(body.encode("utf-8"))
    return {
        "metadata_hash": metadata_hash,
        "body_hash": body_hash,
        "semantic_hash": canonical_digest(
            {"metadata_hash": metadata_hash, "body_hash": body_hash}
        ),
    }


def history_ref_for(document_id: str) -> str:
    if not document_id or any(character in document_id for character in "\\/:*?\"<>|"):
        raise DocumentHistoryError("INVALID_DOCUMENT_ID", "document ID cannot name a sidecar")
    return (HISTORY_DIRECTORY / f"{document_id}.jsonl").as_posix()


def history_path_for(root: Path, document_id: str) -> Path:
    return root.resolve() / history_ref_for(document_id)


def read_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DocumentHistoryError(
                "INVALID_HISTORY", f"invalid JSONL at {path.name}:{index}"
            ) from exc
        if not isinstance(event, dict) or event.get("schema") != HISTORY_SCHEMA:
            raise DocumentHistoryError(
                "INVALID_HISTORY", f"invalid history schema at {path.name}:{index}"
            )
        if event.get("seq") != len(events) + 1:
            raise DocumentHistoryError(
                "INVALID_HISTORY", f"non-contiguous history sequence at {path.name}:{index}"
            )
        if event.get("event") not in EVENTS:
            raise DocumentHistoryError(
                "INVALID_HISTORY", f"unknown event at {path.name}:{index}"
            )
        required = {
            "document_id",
            "at",
            "actor",
            "revision",
            "semantic_hash",
            "metadata_hash",
            "body_hash",
            "previous_hash",
            "plan_id",
            "reason",
        }
        if not required.issubset(event):
            raise DocumentHistoryError(
                "INVALID_HISTORY", f"incomplete history event at {path.name}:{index}"
            )
        for key in ("semantic_hash", "metadata_hash", "body_hash", "plan_id"):
            value = event.get(key)
            if (
                not isinstance(value, str)
                or len(value) != 71
                or not value.startswith("sha256:")
                or any(character not in "0123456789abcdef" for character in value[7:])
            ):
                raise DocumentHistoryError(
                    "INVALID_HISTORY", f"invalid {key} at {path.name}:{index}"
                )
        revision = event.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise DocumentHistoryError(
                "INVALID_HISTORY", f"invalid revision at {path.name}:{index}"
            )
        if events:
            previous = events[-1]
            if event.get("document_id") != previous.get("document_id"):
                raise DocumentHistoryError(
                    "INVALID_HISTORY", f"document ID changed at {path.name}:{index}"
                )
            if event.get("previous_hash") != previous.get("semantic_hash"):
                raise DocumentHistoryError(
                    "INVALID_HISTORY", f"broken semantic hash chain at {path.name}:{index}"
                )
            expected_revision = (
                previous["revision"]
                if event.get("event") == "verified"
                else previous["revision"] + 1
            )
            if revision != expected_revision:
                raise DocumentHistoryError(
                    "INVALID_HISTORY", f"invalid revision order at {path.name}:{index}"
                )
            if event.get("event") == "verified" and event.get("semantic_hash") != previous.get("semantic_hash"):
                raise DocumentHistoryError(
                    "INVALID_HISTORY", f"verification changed semantics at {path.name}:{index}"
                )
        elif event.get("previous_hash") is not None:
            raise DocumentHistoryError(
                "INVALID_HISTORY", f"first event has a previous hash at {path.name}:{index}"
            )
        events.append(event)
    return events


def render_history(events: Sequence[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(_plain(dict(event)), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for event in events
    )


def _event(
    *,
    seq: int,
    event: str,
    document_id: str,
    at: str,
    actor: str,
    revision: int,
    components: Mapping[str, str],
    previous_hash: str | None,
    plan_id: str | None,
    reason: str,
    source: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "schema": HISTORY_SCHEMA,
        "seq": seq,
        "event": event,
        "document_id": document_id,
        "at": at,
        "actor": actor,
        "revision": revision,
        "semantic_hash": components["semantic_hash"],
        "metadata_hash": components["metadata_hash"],
        "body_hash": components["body_hash"],
        "previous_hash": previous_hash,
        "plan_id": plan_id,
        "reason": reason,
    }
    if source is not None:
        item["source"] = source
    if status is not None:
        item["status"] = status
    return item


def _git_snapshots(root: Path, document: Path) -> list[dict[str, Any]]:
    try:
        relative = document.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return []
    command = [
        "git",
        "-C",
        str(root),
        "log",
        "--follow",
        "--reverse",
        "--format=%H%x1f%cI%x1f%an",
        "--",
        relative,
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if completed.returncode != 0:
        return []
    snapshots: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) != 3:
            continue
        commit, committed_at, author = parts
        shown = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{relative}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if shown.returncode != 0:
            continue
        try:
            metadata, body = parse_document_text(shown.stdout)
        except DocumentHistoryError:
            continue
        snapshots.append(
            {
                "commit": commit,
                "at": committed_at,
                "actor": f"git:{author}",
                "components": semantic_components(metadata, body),
                "status": metadata.get("status"),
            }
        )
    return snapshots


def _backfilled_history(
    root: Path,
    document: Path,
    document_id: str,
    current_components: Mapping[str, str],
    *,
    actor: str,
    now: str,
    created: bool,
    current_status: str | None,
    lifecycle: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], int, str | None, str | None]:
    shared_revision = lifecycle.get("revision")
    if (
        not created
        and isinstance(shared_revision, int)
        and not isinstance(shared_revision, bool)
        and shared_revision > 0
    ):
        events = [
            _event(
                seq=1,
                event="migrated",
                document_id=document_id,
                at=now,
                actor=actor,
                revision=shared_revision,
                components=current_components,
                previous_hash=None,
                plan_id=None,
                reason="local history initialized from shared lifecycle summary",
                status=current_status,
            )
        ]
        return (
            events,
            shared_revision,
            lifecycle.get("created_at"),
            lifecycle.get("modified_at"),
        )
    snapshots = _git_snapshots(root, document)
    events: list[dict[str, Any]] = []
    previous: str | None = None
    revision = 0
    for snapshot in snapshots:
        components = snapshot["components"]
        if components["semantic_hash"] == previous:
            continue
        revision += 1
        events.append(
            _event(
                seq=len(events) + 1,
                event="created" if revision == 1 else "content_changed",
                document_id=document_id,
                at=str(snapshot["at"]),
                actor=str(snapshot["actor"]),
                revision=revision,
                components=components,
                previous_hash=previous,
                plan_id=None,
                reason="git history backfill",
                source=f"git:{snapshot['commit']}",
                status=(str(snapshot["status"]) if snapshot.get("status") is not None else None),
            )
        )
        previous = components["semantic_hash"]
    if events:
        created_at = str(events[0]["at"])
        modified_at = str(events[-1]["at"])
        if previous != current_components["semantic_hash"]:
            revision += 1
            events.append(
                _event(
                    seq=len(events) + 1,
                    event="content_changed",
                    document_id=document_id,
                    at=now,
                    actor=actor,
                    revision=revision,
                    components=current_components,
                    previous_hash=previous,
                    plan_id=None,
                    reason="working tree differs from latest Git snapshot",
                    status=current_status,
                )
            )
            modified_at = now
        return events, revision, created_at, modified_at
    revision = 1
    if created:
        events.append(
            _event(
                seq=1,
                event="created",
                document_id=document_id,
                at=now,
                actor=actor,
                revision=revision,
                components=current_components,
                previous_hash=None,
                plan_id=None,
                reason="new managed document",
                status=current_status,
            )
        )
        return events, revision, now, now
    events.append(
        _event(
            seq=1,
            event="migrated",
            document_id=document_id,
            at=now,
            actor=actor,
            revision=revision,
            components=current_components,
            previous_hash=None,
            plan_id=None,
            reason="history unavailable; lifecycle dates remain unverified",
            status=current_status,
        )
    )
    return events, revision, None, None


def plan_documents(
    root: Path,
    documents: Iterable[Path],
    *,
    actor: str,
    created_ids: Iterable[str] = (),
    reason: str = "document finalize",
    at: str | None = None,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    supplied_documents = sorted(
        {Path(path).resolve() for path in documents}, key=lambda item: item.as_posix()
    )
    now = at or _stable_observed_at(supplied_documents)
    created = set(created_ids)
    internal_actions: list[dict[str, Any]] = []
    for supplied in supplied_documents:
        try:
            relative = supplied.relative_to(root).as_posix()
        except ValueError as exc:
            raise DocumentHistoryError("PATH_ESCAPE", f"document escapes repository: {supplied}") from exc
        if not supplied.is_file() or supplied.suffix.casefold() != ".md":
            raise DocumentHistoryError("INVALID_DOCUMENT", f"managed Markdown not found: {relative}")
        metadata, body, original = parse_document(supplied)
        document_id = metadata.get("id")
        if not isinstance(document_id, str) or not document_id:
            raise DocumentHistoryError("INVALID_DOCUMENT_ID", f"document has no stable ID: {relative}")
        sidecar = history_path_for(root, document_id)
        legacy_sidecar = supplied.with_name(f"{document_id}.history.jsonl")
        if sidecar.exists() and legacy_sidecar.exists():
            raise DocumentHistoryError(
                "HISTORY_CONFLICT",
                f"both local and legacy history exist for {document_id}",
            )
        history_source = sidecar if sidecar.exists() else legacy_sidecar
        history = read_history(history_source)
        had_history = bool(history)
        components = semantic_components(metadata, body)
        changed = False
        new_events: list[dict[str, Any]] = []
        if not history:
            history, revision, created_at, modified_at = _backfilled_history(
                root,
                supplied,
                document_id,
                components,
                actor=actor,
                now=now,
                created=document_id in created,
                current_status=(
                    str(metadata["status"]) if metadata.get("status") is not None else None
                ),
                lifecycle=metadata,
            )
            metadata["created_at"] = created_at
            metadata["modified_at"] = modified_at
            metadata.setdefault("verified_at", None)
            metadata["revision"] = revision
            metadata["history_ref"] = history_ref_for(document_id)
            new_events = history
            changed = True
        else:
            last = history[-1]
            if last.get("document_id") != document_id:
                raise DocumentHistoryError("INVALID_HISTORY", f"sidecar ID mismatch: {sidecar.name}")
            revision = int(last.get("revision", 0))
            previous_hash = str(last.get("semantic_hash"))
            if previous_hash != components["semantic_hash"]:
                revision += 1
                event_name = "content_changed"
                if last.get("body_hash") == components["body_hash"]:
                    event_name = "metadata_changed"
                    if metadata.get("status") == "deprecated":
                        event_name = "deprecated"
                event = _event(
                    seq=len(history) + 1,
                    event=event_name,
                    document_id=document_id,
                    at=now,
                    actor=actor,
                    revision=revision,
                    components=components,
                    previous_hash=previous_hash,
                    plan_id=None,
                    reason=reason,
                    status=(str(metadata["status"]) if metadata.get("status") is not None else None),
                )
                previous_status = last.get("status")
                current_status = metadata.get("status")
                if previous_status is not None and previous_status != current_status:
                    event["event"] = "deprecated" if current_status == "deprecated" else "status_changed"
                history.append(event)
                new_events.append(event)
                metadata["modified_at"] = now
                changed = True
            lifecycle = {
                "created_at": metadata.get("created_at"),
                "modified_at": metadata.get("modified_at"),
                "verified_at": metadata.get("verified_at"),
                "revision": revision,
                "history_ref": history_ref_for(document_id),
            }
            for key, value in lifecycle.items():
                if metadata.get(key) != value or key not in metadata:
                    metadata[key] = value
                    changed = True
        rendered = render_document(metadata, body)
        history_text = render_history(history)
        if (
            rendered == original
            and sidecar.exists()
            and not legacy_sidecar.exists()
            and history_text == sidecar.read_text(encoding="utf-8")
        ):
            changed = False
        if changed:
            internal_actions.append(
                {
                    "document_id": document_id,
                    "path": relative,
                    "history_path": sidecar.relative_to(root).as_posix(),
                    "before_sha256": bytes_digest(supplied.read_bytes()),
                    "history_before_sha256": (
                        bytes_digest(sidecar.read_bytes()) if sidecar.exists() else "missing"
                    ),
                    "legacy_history_path": (
                        legacy_sidecar.relative_to(root).as_posix()
                        if legacy_sidecar.exists() and legacy_sidecar != sidecar
                        else None
                    ),
                    "legacy_history_sha256": (
                        bytes_digest(legacy_sidecar.read_bytes())
                        if legacy_sidecar.exists() and legacy_sidecar != sidecar
                        else None
                    ),
                    "target_sha256": bytes_digest(rendered.encode("utf-8")),
                    "history_target_sha256": bytes_digest(history_text.encode("utf-8")),
                    "rendered": rendered,
                    "history_text": history_text,
                    "new_events": new_events,
                    "candidate_created": bool(
                        document_id in created
                        and not had_history
                        and metadata.get("status") == "proposed"
                        and isinstance(metadata.get("memory"), Mapping)
                        and metadata["memory"].get("level") == "l3"
                    ),
                    "category": metadata.get("category"),
                    "kind": (
                        metadata.get("kind")
                        or (
                            metadata.get("memory", {}).get("kind")
                            if isinstance(metadata.get("memory"), Mapping)
                            else None
                        )
                    ),
                    "scope": (
                        metadata.get("scope")
                        or (
                            metadata.get("memory", {}).get("scope")
                            if isinstance(metadata.get("memory"), Mapping)
                            else None
                        )
                    ),
                }
            )
    public_actions = [
        {
            key: value
            for key, value in action.items()
            if key not in {"rendered", "history_text", "new_events"}
        }
        for action in internal_actions
    ]
    plan_basis = [
        {
            key: value
            for key, value in action.items()
            if key
            in {
                "document_id",
                "path",
                "history_path",
                "before_sha256",
                "history_before_sha256",
                "legacy_history_path",
                "legacy_history_sha256",
                "target_sha256",
                "candidate_created",
                "category",
                "kind",
                "scope",
            }
        }
        for action in public_actions
    ]
    plan_id = canonical_digest(
        {"schema": PLAN_SCHEMA, "actor": actor, "observed_at": now, "actions": plan_basis}
    )
    for action in internal_actions:
        for event in action["new_events"]:
            event["plan_id"] = plan_id
        existing_path = (
            root / action["legacy_history_path"]
            if action.get("legacy_history_path")
            else root / action["history_path"]
        )
        existing = read_history(existing_path)
        action["history_text"] = render_history([*existing, *action["new_events"]])
        action["history_target_sha256"] = bytes_digest(action["history_text"].encode("utf-8"))
    return {
        "schema": PLAN_SCHEMA,
        "status": "planned" if internal_actions else "current",
        "plan_id": plan_id,
        "actor": actor,
        "actions": [
            {
                key: value
                for key, value in action.items()
                if key not in {"rendered", "history_text", "new_events"}
            }
            for action in internal_actions
        ],
        "_internal_actions": internal_actions,
    }


def apply_document_plan(root: Path, plan: Mapping[str, Any], *, plan_id: str) -> dict[str, Any]:
    if plan_id != plan.get("plan_id"):
        raise DocumentHistoryError("STALE_PLAN", "document plan ID changed")
    root = root.resolve(strict=True)
    transaction_id = "document-finalize-" + uuid.uuid4().hex
    backup_root = root / ".knowledge" / "document-backups" / transaction_id
    backup_root.mkdir(parents=True, exist_ok=False)
    actions = list(plan.get("_internal_actions", []))
    attempted: list[dict[str, Any]] = []
    journal = backup_root / "transaction.jsonl"
    try:
        for action in actions:
            document = root / action["path"]
            sidecar = root / action["history_path"]
            if bytes_digest(document.read_bytes()) != action["before_sha256"]:
                raise DocumentHistoryError("STALE_PLAN", f"document changed: {action['path']}")
            observed_history = bytes_digest(sidecar.read_bytes()) if sidecar.exists() else "missing"
            if observed_history != action["history_before_sha256"]:
                raise DocumentHistoryError("STALE_PLAN", f"history changed: {action['history_path']}")
            legacy = (
                root / action["legacy_history_path"]
                if action.get("legacy_history_path")
                else None
            )
            if legacy is not None and bytes_digest(legacy.read_bytes()) != action["legacy_history_sha256"]:
                raise DocumentHistoryError(
                    "STALE_PLAN", f"legacy history changed: {action['legacy_history_path']}"
                )
            document_backup = backup_root / action["path"]
            history_backup = backup_root / action["history_path"]
            document_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(document, document_backup)
            if sidecar.exists():
                history_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sidecar, history_backup)
            if legacy is not None:
                legacy_backup = backup_root / action["legacy_history_path"]
                legacy_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, legacy_backup)
            attempted.append(action)
            event = {
                "transaction_id": transaction_id,
                "action_id": f"document-finalize:{action['document_id']}",
                "state": "started",
                "path": action["path"],
                "history_path": action["history_path"],
            }
            with journal.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            staged_document: Path | None = None
            staged_history: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", newline="\n", dir=document.parent,
                    prefix=".treewiki-document-", delete=False,
                ) as handle:
                    handle.write(action["rendered"])
                    handle.flush()
                    os.fsync(handle.fileno())
                    staged_document = Path(handle.name)
                sidecar.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", newline="\n", dir=sidecar.parent,
                    prefix=".treewiki-history-", delete=False,
                ) as handle:
                    handle.write(action["history_text"])
                    handle.flush()
                    os.fsync(handle.fileno())
                    staged_history = Path(handle.name)
                os.replace(staged_document, document)
                staged_document = None
                os.replace(staged_history, sidecar)
                staged_history = None
            finally:
                if staged_document is not None:
                    staged_document.unlink(missing_ok=True)
                if staged_history is not None:
                    staged_history.unlink(missing_ok=True)
            if bytes_digest(document.read_bytes()) != action["target_sha256"]:
                raise DocumentHistoryError("VERIFY_FAILED", f"document verification failed: {action['path']}")
            if bytes_digest(sidecar.read_bytes()) != action["history_target_sha256"]:
                raise DocumentHistoryError("VERIFY_FAILED", f"history verification failed: {action['history_path']}")
            if legacy is not None:
                legacy.unlink()
            with journal.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({**event, "state": "verified"}, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
    except Exception:
        for action in reversed(attempted):
            document = root / action["path"]
            sidecar = root / action["history_path"]
            document_backup = backup_root / action["path"]
            history_backup = backup_root / action["history_path"]
            legacy = (
                root / action["legacy_history_path"]
                if action.get("legacy_history_path")
                else None
            )
            if document_backup.exists():
                shutil.copy2(document_backup, document)
            if history_backup.exists():
                shutil.copy2(history_backup, sidecar)
            else:
                sidecar.unlink(missing_ok=True)
            if legacy is not None:
                legacy_backup = backup_root / action["legacy_history_path"]
                if legacy_backup.exists():
                    legacy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(legacy_backup, legacy)
        raise
    notices = [
        {
            "type": "L3_CANDIDATE_CREATED",
            "id": action["document_id"],
            "category": action.get("category") or "knowledge",
            "kind": action.get("kind") or "information",
            "scope": action.get("scope") or "repo",
            "review": f"/treewiki 이 후보를 검토해줘: {action['document_id']}",
        }
        for action in actions
        if action.get("candidate_created")
    ]
    return {
        "schema": "treewiki.document-finalize-result/v1",
        "status": "APPLIED",
        "plan_id": plan_id,
        "transaction_id": transaction_id,
        "completed_ids": [action["document_id"] for action in actions],
        "events": notices,
        "backup_path": backup_root.as_posix(),
    }


def plan_verification(
    root: Path,
    document: Path,
    *,
    actor: str,
    source_digest: str,
    reason: str,
    at: str | None = None,
) -> dict[str, Any]:
    metadata, body, original = parse_document(document)
    document_id = metadata.get("id")
    if not isinstance(document_id, str) or not document_id:
        raise DocumentHistoryError("INVALID_DOCUMENT_ID", "document has no stable ID")
    sidecar = history_path_for(root, document_id)
    now = at or _stable_observed_at([document, sidecar])
    history = read_history(sidecar)
    if not history:
        raise DocumentHistoryError("HISTORY_REQUIRED", "finalize the document before verification")
    components = semantic_components(metadata, body)
    revision = int(history[-1]["revision"])
    metadata["verified_at"] = now
    metadata["revision"] = revision
    metadata["history_ref"] = history_ref_for(document_id)
    event = _event(
        seq=len(history) + 1,
        event="verified",
        document_id=document_id,
        at=now,
        actor=actor,
        revision=revision,
        components=components,
        previous_hash=str(history[-1]["semantic_hash"]),
        plan_id=None,
        reason=reason,
        source=source_digest,
        status=(str(metadata["status"]) if metadata.get("status") is not None else None),
    )
    public = {
        "document_id": document_id,
        "path": document.resolve().relative_to(root.resolve()).as_posix(),
        "history_path": sidecar.resolve().relative_to(root.resolve()).as_posix(),
        "source_digest": source_digest,
        "at": now,
    }
    plan_id = canonical_digest({"schema": VERIFY_PLAN_SCHEMA, "actor": actor, **public})
    event["plan_id"] = plan_id
    return {
        "schema": VERIFY_PLAN_SCHEMA,
        "status": "planned",
        "plan_id": plan_id,
        **public,
        "_document_before": original,
        "_history_before": render_history(history),
        "_document_after": render_document(metadata, body),
        "_history_after": render_history([*history, event]),
    }


def apply_verification(root: Path, plan: Mapping[str, Any], *, plan_id: str) -> dict[str, Any]:
    if plan_id != plan.get("plan_id"):
        raise DocumentHistoryError("STALE_PLAN", "verification plan ID changed")
    document = root / str(plan["path"])
    sidecar = root / str(plan["history_path"])
    if document.read_text(encoding="utf-8") != plan["_document_before"]:
        raise DocumentHistoryError("STALE_PLAN", "document changed before verification")
    if sidecar.read_text(encoding="utf-8") != plan["_history_before"]:
        raise DocumentHistoryError("STALE_PLAN", "history changed before verification")
    transaction = {
        "schema": PLAN_SCHEMA,
        "plan_id": plan_id,
        "_internal_actions": [
            {
                "document_id": plan["document_id"],
                "path": plan["path"],
                "history_path": plan["history_path"],
                "before_sha256": bytes_digest(document.read_bytes()),
                "history_before_sha256": bytes_digest(plan["_history_before"].encode("utf-8")),
                "target_sha256": bytes_digest(plan["_document_after"].encode("utf-8")),
                "history_target_sha256": bytes_digest(plan["_history_after"].encode("utf-8")),
                "rendered": plan["_document_after"],
                "history_text": plan["_history_after"],
                "candidate_created": False,
            }
        ],
    }
    return apply_document_plan(root, transaction, plan_id=plan_id)


def plan_document_move(root: Path, document: Path, destination: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    source = document.resolve(strict=True)
    target = destination.resolve()
    try:
        source_relative = source.relative_to(root).as_posix()
        target_relative = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise DocumentHistoryError("PATH_ESCAPE", "document move must stay inside the repository") from exc
    if source.suffix.casefold() != ".md" or target.suffix.casefold() != ".md":
        raise DocumentHistoryError("INVALID_DOCUMENT", "document move requires Markdown paths")
    metadata, _, _ = parse_document(source)
    document_id = metadata.get("id")
    if not isinstance(document_id, str) or not document_id:
        raise DocumentHistoryError("INVALID_DOCUMENT_ID", "document has no stable ID")
    history = history_path_for(root, document_id)
    if not history.is_file():
        raise DocumentHistoryError("HISTORY_REQUIRED", "finalize the document before moving it")
    if target.exists():
        raise DocumentHistoryError("TARGET_EXISTS", "document destination already exists")
    public = {
        "schema": MOVE_PLAN_SCHEMA,
        "document_id": document_id,
        "source": source_relative,
        "target": target_relative,
        "history_path": history.relative_to(root).as_posix(),
        "document_sha256": bytes_digest(source.read_bytes()),
        "history_sha256": bytes_digest(history.read_bytes()),
    }
    return {**public, "status": "planned", "plan_id": canonical_digest(public)}


def apply_document_move(root: Path, plan: Mapping[str, Any], *, plan_id: str) -> dict[str, Any]:
    if plan_id != plan.get("plan_id"):
        raise DocumentHistoryError("STALE_PLAN", "document move plan ID changed")
    root = root.resolve(strict=True)
    source = root / str(plan["source"])
    history = root / str(plan["history_path"])
    target = root / str(plan["target"])
    if bytes_digest(source.read_bytes()) != plan.get("document_sha256"):
        raise DocumentHistoryError("STALE_PLAN", "document changed before move")
    if bytes_digest(history.read_bytes()) != plan.get("history_sha256"):
        raise DocumentHistoryError("STALE_PLAN", "document history changed before move")
    if target.exists():
        raise DocumentHistoryError("TARGET_EXISTS", "document destination already exists")
    transaction_id = "document-move-" + uuid.uuid4().hex
    backup_root = root / ".knowledge" / "document-backups" / transaction_id
    backup_root.mkdir(parents=True, exist_ok=False)
    document_backup = backup_root / str(plan["source"])
    history_backup = backup_root / str(plan["history_path"])
    document_backup.parent.mkdir(parents=True, exist_ok=True)
    history_backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, document_backup)
    shutil.copy2(history, history_backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    moved_document = False
    try:
        os.replace(source, target)
        moved_document = True
        if bytes_digest(target.read_bytes()) != plan.get("document_sha256"):
            raise DocumentHistoryError("VERIFY_FAILED", "moved document verification failed")
        if bytes_digest(history.read_bytes()) != plan.get("history_sha256"):
            raise DocumentHistoryError("VERIFY_FAILED", "document history verification failed")
    except Exception:
        if moved_document:
            target.unlink(missing_ok=True)
        shutil.copy2(document_backup, source)
        shutil.copy2(history_backup, history)
        raise
    return {
        "schema": "treewiki.document-move-result/v1",
        "status": "APPLIED",
        "plan_id": plan_id,
        "transaction_id": transaction_id,
        "document_id": plan["document_id"],
        "target": plan["target"],
        "history_path": plan["history_path"],
        "backup_path": backup_root.as_posix(),
    }
