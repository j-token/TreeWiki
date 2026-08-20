from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, TypedDict

import yaml

try:
    from document_history import (
        history_path_for,
        history_ref_for,
        parse_document_text,
        read_history,
        semantic_components,
    )
except ImportError:  # pragma: no cover - package-style import
    from .document_history import (
        history_path_for,
        history_ref_for,
        parse_document_text,
        read_history,
        semantic_components,
    )

try:
    from install_treewiki_hooks import (
        CANONICAL_MARKER as HOOK_CANONICAL_MARKER,
        LEGACY_MARKER as HOOK_LEGACY_MARKER,
        _load_settings_source as _load_hook_settings_source,
        owned_marker as _owned_hook_marker,
        transition_hooks as _transition_owned_hooks,
        validate_hooks as _validate_hook_payload,
    )
except ImportError:  # pragma: no cover - package-style import
    from .install_treewiki_hooks import (
        CANONICAL_MARKER as HOOK_CANONICAL_MARKER,
        LEGACY_MARKER as HOOK_LEGACY_MARKER,
        _load_settings_source as _load_hook_settings_source,
        owned_marker as _owned_hook_marker,
        transition_hooks as _transition_owned_hooks,
        validate_hooks as _validate_hook_payload,
    )

try:
    from release_manifest import (
        MANIFEST_FILENAME,
        ArtifactProblem,
        ManifestErrorCode,
        ManifestValidationError,
        ReleaseManifest,
        canonical_json,
        compare_semver,
        load_manifest,
        manifest_digest,
        parse_manifest,
        sha256_file,
        verify_payload,
    )
except ImportError:  # pragma: no cover - package-style import
    from .release_manifest import (
        MANIFEST_FILENAME,
        ArtifactProblem,
        ManifestErrorCode,
        ManifestValidationError,
        ReleaseManifest,
        canonical_json,
        compare_semver,
        load_manifest,
        manifest_digest,
        parse_manifest,
        sha256_file,
        verify_payload,
    )


STATUS_SCHEMA = "treewiki.upgrade-status/v1"
TARGET_CONFIG_VERSION = 5
MEMORY_LAYOUT_VERSION = 2
STAGE_ORDER = (
    "memory-layout",
    "document-history",
    "config",
    "runtime",
    "adapters",
    "claude-alias",
    "hook",
    "index",
)
COMPONENT_IDS = (
    "repository_config",
    "executing_skill",
    "repository_skill_copy",
    "global_skill_copy",
    "codex_hook",
    "codex_hook_settings",
    "search_index",
    "legacy_sources",
    "memory_layout",
    "l3_candidate_state",
    "protected_knowledge",
    "document_history",
    "adapters",
    "claude_alias",
)
CONFIG_PATH = Path(".knowledge/config.yml")
CONFIG_EXCLUDES = (
    "lmwiki/**/assets/AGENTS.md",
    "treewiki/**/assets/AGENTS.md",
    "skills/**/assets/AGENTS.md",
    ".knowledge/upgrade-backups/**",
    ".knowledge/document-backups/**",
    ".knowledge/document-history/**",
)
PRIVATE_L0_PATTERN = ".knowledge/private-memory/l0/**/*.md"
INDEX_SCHEMA_VERSION = "1"
INDEX_RESULT_CONTRACT = "locations_only"
INDEX_QUERY_MODE = "high_recall"


class ComponentStatus(str, Enum):
    CURRENT = "current"
    UPGRADE_REQUIRED = "upgrade_required"
    LEGACY_DETECTED = "legacy_detected"
    DISABLED = "disabled"
    MISSING = "missing"
    UNKNOWN = "unknown"
    INVALID = "invalid"
    INCOMPATIBLE_NEWER = "incompatible_newer"
    CONFLICT = "conflict"


class OverallStatus(str, Enum):
    CURRENT = "current"
    GUIDANCE_REQUIRED = "guidance_required"
    UPGRADE_REQUIRED = "upgrade_required"
    BLOCKED = "blocked"


class AuthorityKind(str, Enum):
    EMBEDDED = "embedded"
    OFFICIAL = "official"
    LOCAL_OVERRIDE = "local_override"


class AuthorityAvailability(str, Enum):
    AVAILABLE = "available"
    UNKNOWN = "unknown"


class UpgradeErrorCode(str, Enum):
    CURRENT = "CURRENT"
    APPLIED = "APPLIED"
    UPGRADE_REQUIRED = "UPGRADE_REQUIRED"
    GUIDANCE_REQUIRED = "GUIDANCE_REQUIRED"
    INCOMPATIBLE_NEWER = "INCOMPATIBLE_NEWER"
    BLOCKED = "BLOCKED"
    MEMORY_TARGET_CONFLICT = "MEMORY_TARGET_CONFLICT"
    LEGACY_MEMORY_HOOK = "LEGACY_MEMORY_HOOK"
    INVALID_INPUT = "INVALID_INPUT"
    MANAGEMENT_DENIED = "MANAGEMENT_DENIED"
    SOURCE_INVALID = "SOURCE_INVALID"
    IO_FAILURE = "IO_FAILURE"
    STALE_PLAN = "STALE_PLAN"
    APPLY_FAILED = "APPLY_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class UpgradeExitCode(IntEnum):
    SUCCESS = 0
    DIAGNOSTIC = 2
    BLOCKED = 3
    INVALID_INPUT = 4
    SOURCE_FAILURE = 5
    STALE_PLAN = 6
    APPLY_FAILED = 7
    VERIFICATION_FAILED = 8


class UpgradeError(TypedDict, total=False):
    code: str
    message: str
    component: str
    path: str
    recovery: list[str]


class UpgradeException(RuntimeError):
    def __init__(
        self,
        code: UpgradeErrorCode,
        message: str,
        *,
        component: str | None = None,
        path: str | None = None,
        recovery: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.component = component
        self.path = path
        self.recovery = list(recovery)

    def as_error(self) -> UpgradeError:
        error: UpgradeError = {"code": self.code.value, "message": str(self)}
        if self.component:
            error["component"] = self.component
        if self.path:
            error["path"] = self.path
        if self.recovery:
            error["recovery"] = list(self.recovery)
        return error


LatestFetcher = Callable[[], tuple[Mapping[str, Any] | ReleaseManifest, str]]
FaultInjector = Callable[[str, Mapping[str, Any]], None]
MemoryLayoutPlanner = Callable[..., Mapping[str, Any]]
MemoryLayoutApplier = Callable[[Mapping[str, Any], Path], Sequence[Mapping[str, Any]]]


def validate_source_options(
    *, check_latest: bool = False, source: str | Path | None = None, offline: bool = False
) -> None:
    if check_latest and source is not None:
        raise UpgradeException(
            UpgradeErrorCode.INVALID_INPUT,
            "--check-latest and --source cannot be used together",
        )
    if offline and check_latest:
        raise UpgradeException(
            UpgradeErrorCode.INVALID_INPUT,
            "--offline and --check-latest cannot be used together",
        )


def normalize_stages(stages: str | Iterable[str] | None) -> tuple[str, ...]:
    if stages is None:
        return STAGE_ORDER
    values = stages.split(",") if isinstance(stages, str) else list(stages)
    normalized = tuple(
        dict.fromkeys(
            "runtime" if value.strip() == "skill" else value.strip()
            for value in values
            if value.strip()
        )
    )
    unknown = sorted(set(normalized) - set(STAGE_ORDER))
    if unknown:
        raise UpgradeException(
            UpgradeErrorCode.INVALID_INPUT,
            "unknown upgrade stage(s): " + ", ".join(unknown),
        )
    return tuple(stage for stage in STAGE_ORDER if stage in normalized)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _hash_file_or_missing(path: Path) -> str:
    return "sha256:" + sha256_file(path) if path.is_file() else "missing"


def _normalize_sha256(value: str, *, field: str) -> str:
    digest = value[7:] if value.startswith("sha256:") else value
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            f"{field} must be a lowercase SHA-256 digest",
            component="memory_layout",
        )
    return "sha256:" + digest


def _yaml_bytes(value: Mapping[str, Any]) -> bytes:
    return yaml.safe_dump(
        dict(value), allow_unicode=True, sort_keys=False
    ).encode("utf-8")


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise UpgradeException(
            UpgradeErrorCode.IO_FAILURE,
            f"cannot read YAML {path}: {exc}",
            path=path.as_posix(),
        ) from exc
    if not isinstance(loaded, Mapping):
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            f"YAML root must be a mapping: {path}",
            path=path.as_posix(),
        )
    return copy.deepcopy(dict(loaded))


def migrate_config_v5(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return the deterministic v5 target while preserving unknown keys."""
    target = copy.deepcopy(dict(config))
    raw_version = target.get("version")
    if not isinstance(raw_version, int) or isinstance(raw_version, bool) or raw_version < 1:
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            ".knowledge/config.yml version must be a positive integer",
            component="repository_config",
        )
    if raw_version > TARGET_CONFIG_VERSION:
        raise UpgradeException(
            UpgradeErrorCode.INCOMPATIBLE_NEWER,
            f"repository config version {raw_version} is newer than supported version "
            f"{TARGET_CONFIG_VERSION}",
            component="repository_config",
        )
    target["version"] = TARGET_CONFIG_VERSION

    memory = target.setdefault("memory", {})
    if not isinstance(memory, dict):
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            "memory config must be a mapping",
            component="repository_config",
        )
    memory["layout_version"] = MEMORY_LAYOUT_VERSION
    memory["private_path"] = ".knowledge/private-memory"
    memory["shared_path"] = "docs/memory"
    memory["l3"] = {
        "knowledge_path": "docs/memory/l3/knowledge",
        "persona_path": "docs/memory/l3/persona",
    }
    if memory.get("capture") == "hook":
        # Selecting/applying the config stage is the manager's explicit transition
        # away from the prohibited legacy Stop-hook memory flow.
        memory["capture"] = "explicit"

    documents = target.setdefault("documents", {})
    if not isinstance(documents, dict):
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            "documents config must be a mapping",
            component="repository_config",
        )
    includes = documents.setdefault("include", [])
    excludes = documents.setdefault("exclude", [])
    if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            "documents.include must be a string list",
            component="repository_config",
        )
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            "documents.exclude must be a string list",
            component="repository_config",
        )
    def is_supported_private_include(value: str) -> bool:
        normalized = value.replace("\\", "/")
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        normalized = normalized.removeprefix("./")
        private_root = ".knowledge/private-memory"
        if normalized == private_root or normalized.startswith(private_root + "/"):
            # Config v3 permits only the canonical L0 include. All other private
            # includes can accidentally make approved L1-L3 migration sources
            # part of the managed/shared corpus.
            return normalized.startswith(private_root + "/l0/")
        return True

    documents["include"] = [item for item in includes if is_supported_private_include(item)]
    if PRIVATE_L0_PATTERN not in documents["include"]:
        documents["include"].append(PRIVATE_L0_PATTERN)
    for rule in CONFIG_EXCLUDES:
        if rule not in excludes:
            excludes.append(rule)
    target["history"] = {
        "schema": 1,
        "storage": "local",
        "path": ".knowledge/document-history",
        "enforce": True,
    }
    return target


def migrate_config_v4(config: Mapping[str, Any]) -> dict[str, Any]:
    """Deprecated import name for the current config migration."""

    return migrate_config_v5(config)


def migrate_config_v3(config: Mapping[str, Any]) -> dict[str, Any]:
    """Deprecated 0.1 import name for the current config migration."""

    return migrate_config_v5(config)


def _document_id(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ""
    try:
        metadata = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return ""
    return str(metadata.get("id", "")) if isinstance(metadata, Mapping) else ""


def _aggregate_inventory(paths: Iterable[Path], root: Path, *, include_ids: bool) -> dict[str, Any]:
    entries: list[dict[str, str]] = []
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        item = {"path": relative, "sha256": _hash_file_or_missing(path)}
        if include_ids:
            item["id"] = _document_id(path)
        entries.append(item)
    return {"count": len(entries), "digest": _sha256_bytes(canonical_json(entries))}


def protected_knowledge_inventory(repository: str | Path) -> dict[str, Any]:
    root = Path(repository).resolve(strict=True)
    l0_root = root / ".knowledge" / "private-memory" / "l0"
    l0_paths = list(l0_root.rglob("*.md")) if l0_root.is_dir() else []
    docs_root = root / "docs"
    managed = list(docs_root.rglob("*.md")) if docs_root.is_dir() else []
    # Only aggregate values leave this function; no body or per-file path is reported.
    return {
        "l0": _aggregate_inventory(l0_paths, root, include_ids=False),
        "managed": _aggregate_inventory(managed, root, include_ids=True),
    }


def _load_managed_documents() -> Callable[[Path, dict[str, Any]], list[Path]]:
    """Load the canonical corpus selector without duplicating its glob semantics."""
    for module_name in ("validate_knowledge", ".validate_knowledge"):
        try:
            if module_name.startswith("."):
                if not __package__:
                    continue
                module = importlib.import_module(module_name, __package__)
            else:
                module = importlib.import_module(module_name)
            function = getattr(module, "managed_documents", None)
            if callable(function):
                return function
        except ModuleNotFoundError as exc:
            missing = module_name.lstrip(".")
            if exc.name not in {missing, f"{__package__}.{missing}" if __package__ else missing}:
                raise
    raise UpgradeException(
        UpgradeErrorCode.SOURCE_INVALID,
        "validate_knowledge.py is unavailable for index contract calculation",
        component="search_index",
    )


def _index_target(repository: Path, config: Mapping[str, Any]) -> Path:
    retrieval = config.get("retrieval")
    configured = (
        retrieval.get("bm25_index_path", ".knowledge/index/search.db")
        if isinstance(retrieval, Mapping)
        else ".knowledge/index/search.db"
    )
    if not isinstance(configured, str) or not configured.strip():
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            "retrieval.bm25_index_path must be a non-empty string",
            component="search_index",
        )
    lexical = repository / Path(configured)
    allowed = (repository / ".knowledge" / "index").resolve(strict=False)
    target = lexical.resolve(strict=False)
    try:
        target.relative_to(allowed)
    except ValueError as exc:
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            "retrieval.bm25_index_path must stay under .knowledge/index/",
            component="search_index",
        ) from exc
    current = repository
    try:
        relative_parts = lexical.relative_to(repository).parts
    except ValueError as exc:  # pragma: no cover - guarded by the containment check
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            "index target is outside the repository",
            component="search_index",
        ) from exc
    for part in relative_parts:
        current = current / part
        if not current.exists():
            continue
        is_reparse = current.is_symlink()
        try:
            is_reparse = is_reparse or bool(current.stat().st_file_attributes & 0x400)
        except (AttributeError, OSError):
            pass
        if is_reparse:
            raise UpgradeException(
                UpgradeErrorCode.BLOCKED,
                f"index target uses a symlink or reparse point: {current}",
                component="search_index",
            )
    return target


def _expected_index_contract(
    repository: Path,
    config: Mapping[str, Any],
    *,
    builder_sha256: str,
    planned_files: Mapping[str, str] | None = None,
) -> dict[str, str]:
    try:
        documents = _load_managed_documents()(repository, dict(config))
        corpus_entries: dict[str, str] = {}
        for path in documents:
            relative = path.relative_to(repository).as_posix()
            raw = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            corpus_entries[relative] = digest
        for relative, digest in (planned_files or {}).items():
            corpus_entries[str(relative)] = str(digest).removeprefix("sha256:")
        corpus = hashlib.sha256()
        for relative in sorted(corpus_entries):
            corpus.update(
                f"{relative}\0{corpus_entries[relative]}\n".encode("utf-8")
            )
    except UpgradeException:
        raise
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            f"cannot calculate the search-index corpus: {exc}",
            component="search_index",
        ) from exc
    retrieval = config.get("retrieval")
    retrieval = retrieval if isinstance(retrieval, Mapping) else {}
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "builder_sha256": builder_sha256,
        "corpus_hash": "sha256:" + corpus.hexdigest(),
        "document_count": str(len(corpus_entries)),
        "result_contract": str(
            retrieval.get("result_content", INDEX_RESULT_CONTRACT)
        ),
        "query_mode": str(retrieval.get("bm25_query_mode", INDEX_QUERY_MODE)),
    }


def _index_contract_digest(contract: Mapping[str, str]) -> str:
    return _sha256_bytes(canonical_json(dict(contract)))


def _read_index_contract(path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    try:
        uri = path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        try:
            rows = connection.execute("SELECT key, value FROM metadata").fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return None
    metadata = {str(key): str(value) for key, value in rows}
    required = {
        "schema_version",
        "builder_sha256",
        "corpus_hash",
        "document_count",
        "result_contract",
        "query_mode",
    }
    if not required.issubset(metadata):
        return None
    return {key: metadata[key] for key in sorted(required)}


def _component(component_id: str, status: ComponentStatus, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"id": component_id, "status": status.value}
    result.update(details)
    return result


def _problem_dict(problem: ArtifactProblem) -> dict[str, Any]:
    result = {"code": problem.code.value, "path": problem.path, "message": problem.message}
    if problem.expected:
        result["expected"] = problem.expected
    if problem.observed:
        result["observed"] = problem.observed
    return result


def _inspect_skill(
    skill_root: Path, manifest: ReleaseManifest, *, missing_status: ComponentStatus
) -> tuple[ComponentStatus, list[dict[str, Any]]]:
    if not skill_root.is_dir():
        return missing_status, []
    problems = verify_payload(manifest, skill_root, require_complete=True)
    return (
        (ComponentStatus.CURRENT if not problems else ComponentStatus.UPGRADE_REQUIRED),
        [_problem_dict(problem) for problem in problems],
    )


def _default_latest_fetcher(repository: str) -> tuple[Mapping[str, Any], str]:
    api = f"https://api.github.com/repos/{repository}/releases/latest"
    request = urllib.request.Request(
        api,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "treewiki-upgrade/0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        release = json.loads(response.read().decode("utf-8"))
    if not isinstance(release, Mapping):
        raise ValueError("GitHub latest release response is not an object")
    tag = release.get("tag_name")
    assets = release.get("assets")
    if not isinstance(tag, str) or not isinstance(assets, list):
        raise ValueError("GitHub latest release response is missing tag/assets")
    asset_url = next(
        (
            item.get("browser_download_url")
            for item in assets
            if isinstance(item, Mapping) and item.get("name") == MANIFEST_FILENAME
        ),
        None,
    )
    if not isinstance(asset_url, str):
        raise ValueError(f"release asset {MANIFEST_FILENAME} is missing")
    asset_request = urllib.request.Request(
        asset_url, headers={"User-Agent": "treewiki-upgrade/0.1"}
    )
    with urllib.request.urlopen(asset_request, timeout=10) as response:
        loaded = yaml.safe_load(response.read().decode("utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("official manifest root is not a mapping")
    return loaded, tag


def _resolve_authority(
    embedded_path: Path,
    *,
    source: str | Path | None,
    check_latest: bool,
    offline: bool,
    latest_fetcher: LatestFetcher | None,
) -> tuple[
    ReleaseManifest,
    ReleaseManifest,
    AuthorityKind,
    AuthorityAvailability,
    Path | None,
    list[UpgradeError],
]:
    validate_source_options(check_latest=check_latest, source=source, offline=offline)
    try:
        embedded = load_manifest(embedded_path)
    except ManifestValidationError as exc:
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            str(exc),
            component="executing_skill",
            path=str(embedded_path),
        ) from exc
    errors: list[UpgradeError] = []
    if source is not None:
        source_path = Path(source).expanduser()
        try:
            source_path = source_path.resolve(strict=True)
            local = load_manifest(source_path)
            problems = verify_payload(local, source_path.parent, require_complete=True)
        except (OSError, ManifestValidationError) as exc:
            raise UpgradeException(
                UpgradeErrorCode.SOURCE_INVALID,
                f"invalid local manifest source: {exc}",
                component="executing_skill",
                path=str(source_path),
            ) from exc
        if problems:
            raise UpgradeException(
                UpgradeErrorCode.SOURCE_INVALID,
                problems[0].message,
                component="executing_skill",
                path=problems[0].path,
            )
        return (
            embedded,
            local,
            AuthorityKind.LOCAL_OVERRIDE,
            AuthorityAvailability.AVAILABLE,
            source_path.parent,
            errors,
        )
    if check_latest:
        try:
            fetched, tag = (
                latest_fetcher()
                if latest_fetcher is not None
                else _default_latest_fetcher(embedded.repository)
            )
            official = fetched if isinstance(fetched, ReleaseManifest) else parse_manifest(fetched)
            if tag != official.source_ref:
                raise ValueError(
                    f"official tag {tag!r} does not match source_ref {official.source_ref!r}"
                )
            if official.repository != embedded.repository:
                raise ValueError("official manifest repository does not match embedded authority")
            local_root = embedded_path.parent if manifest_digest(official) == manifest_digest(embedded) else None
            return (
                embedded,
                official,
                AuthorityKind.OFFICIAL,
                AuthorityAvailability.AVAILABLE,
                local_root,
                errors,
            )
        except Exception as exc:  # Network absence is a normal guidance result.
            errors.append(
                UpgradeError(
                    code=UpgradeErrorCode.GUIDANCE_REQUIRED.value,
                    message=f"official latest manifest is unavailable: {exc}",
                    component="executing_skill",
                )
            )
            return (
                embedded,
                embedded,
                AuthorityKind.OFFICIAL,
                AuthorityAvailability.UNKNOWN,
                embedded_path.parent,
                errors,
            )
    return (
        embedded,
        embedded,
        AuthorityKind.EMBEDDED,
        AuthorityAvailability.AVAILABLE,
        embedded_path.parent,
        errors,
    )


def _canonical_plan_id(
    actions: Sequence[Mapping[str, Any]],
    *,
    digest: str,
    config_version: int | None,
    protected: Mapping[str, Any],
    approval_targets: Sequence[str],
    relation_mapping: Sequence[Mapping[str, Any]],
    approve_global_skill: bool,
    approve_global_hook: bool,
) -> str:
    plan_input = {
        "actions": sorted(
            [dict(action) for action in actions],
            key=lambda action: (str(action.get("stage")), str(action.get("id"))),
        ),
        "manifest_digest": digest,
        "config_version": config_version,
        "protected_knowledge": dict(protected),
        "memory_approval_targets": sorted(set(approval_targets)),
        "relation_mapping": sorted(
            [dict(item) for item in relation_mapping],
            key=lambda item: canonical_json(item),
        ),
        "approvals": {
            "global_skill": approve_global_skill,
            "global_hook": approve_global_hook,
        },
    }
    return _sha256_bytes(canonical_json(plan_input))


def _derive_overall(components: Sequence[Mapping[str, Any]], authority_unknown: bool) -> OverallStatus:
    blocking = any(
        str(component.get("status"))
        in {ComponentStatus.INVALID.value, ComponentStatus.INCOMPATIBLE_NEWER.value}
        or (
            str(component.get("status")) == ComponentStatus.CONFLICT.value
            and not bool(component.get("resolvable"))
        )
        for component in components
    )
    states = {str(component.get("status")) for component in components}
    if blocking:
        return OverallStatus.BLOCKED
    if states & {ComponentStatus.UPGRADE_REQUIRED.value, ComponentStatus.LEGACY_DETECTED.value}:
        return OverallStatus.UPGRADE_REQUIRED
    if authority_unknown or states & {ComponentStatus.UNKNOWN.value, ComponentStatus.MISSING.value}:
        return OverallStatus.GUIDANCE_REQUIRED
    return OverallStatus.CURRENT


def _read_json_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            f"{label} is not valid UTF-8 JSON: {exc}",
            component="codex_hook",
            path=path.as_posix(),
        ) from exc
    if not isinstance(value, Mapping):
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            f"{label} must contain a JSON object",
            component="codex_hook",
            path=path.as_posix(),
        )
    return copy.deepcopy(dict(value))


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _ensure_ignore_bytes(path: Path, required_lines: str | Sequence[str]) -> bytes:
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise UpgradeException(
                UpgradeErrorCode.IO_FAILURE,
                f"cannot read Git ignore prerequisite {path}: {exc}",
                path=path.as_posix(),
            ) from exc
    else:
        text = ""
    required = [required_lines] if isinstance(required_lines, str) else list(required_lines)
    lines = text.splitlines()
    for required_line in required:
        if required_line not in lines:
            if text and not text.endswith(("\n", "\r")):
                text += "\n"
            text += required_line + "\n"
            lines.append(required_line)
    return text.encode("utf-8")


def _upgrade_ignore_actions(repository: Path, stage: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for action_id, target, line in (
        (
            "ensure_upgrade_backup_ignore",
            repository / ".knowledge" / ".gitignore",
            ("/upgrade-backups/", "/document-history/"),
        ),
        (
            "ensure_repository_skill_backup_ignore",
            repository / ".agents" / "skills" / ".gitignore",
            "/.treewiki-backups/",
        ),
    ):
        target_bytes = _ensure_ignore_bytes(target, line)
        if _hash_file_or_missing(target) == _sha256_bytes(target_bytes):
            continue
        actions.append(
            {
                "id": action_id,
                "stage": stage,
                "kind": "safety_prerequisite",
                "target": target.as_posix(),
                "target_content": target_bytes.decode("utf-8"),
                "observed_sha256": _hash_file_or_missing(target),
                "target_sha256": _sha256_bytes(target_bytes),
            }
        )
    return actions


def _hook_inventory(payload: Mapping[str, Any]) -> dict[str, Any]:
    owned = 0
    legacy = 0
    canonical = 0
    duplicate_events: list[str] = []
    ambiguous: list[str] = []
    hooks = payload.get("hooks", {})
    for event, groups in hooks.items():
        event_owned = 0
        for group in groups:
            for value in group["hooks"]:
                marker = _owned_hook_marker(value)
                if marker is not None:
                    owned += 1
                    event_owned += 1
                    legacy += marker == HOOK_LEGACY_MARKER
                    canonical += marker == HOOK_CANONICAL_MARKER
                    continue
                command = "\n".join(
                    str(value.get(key, "")) for key in ("command", "commandWindows")
                ).casefold()
                if "lmwiki" in command or "treewiki" in command:
                    ambiguous.append(str(event))
        if event_owned > 1:
            duplicate_events.append(str(event))
    return {
        "owned_count": owned,
        "legacy_count": legacy,
        "canonical_count": canonical,
        "duplicate_events": sorted(duplicate_events),
        "ambiguous_events": sorted(set(ambiguous)),
    }


def _diagnose_hooks(
    *,
    config: Mapping[str, Any] | None,
    target_config: Mapping[str, Any] | None,
    selected_stages: Sequence[str],
    executing_root: Path,
    codex_home: str | Path | None,
    approve_global_hook: bool,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[UpgradeError],
    list[str],
    list[dict[str, Any]],
]:
    home = (
        Path(codex_home).expanduser().resolve(strict=False)
        if codex_home is not None
        else (Path.home() / ".codex").resolve(strict=False)
    )
    hooks_path = home / "hooks.json"
    runner_path = home / "hooks" / HOOK_CANONICAL_MARKER
    settings_path = home / "hooks" / "treewiki-global.json"
    legacy_settings_path = home / "hooks" / "lmwiki-global.json"
    source_runner = executing_root / "scripts" / HOOK_CANONICAL_MARKER
    hooks_enabled = bool(
        config
        and isinstance(config.get("hooks"), Mapping)
        and config["hooks"].get("enabled")
    )
    capture = (
        config.get("memory", {}).get("capture")
        if config and isinstance(config.get("memory"), Mapping)
        else None
    )
    capture_transition_approved = capture != "hook" or (
        "config" in selected_stages
        and target_config is not None
        and isinstance(target_config.get("memory"), Mapping)
        and target_config["memory"].get("capture") == "explicit"
    )
    errors: list[UpgradeError] = []
    actions: list[dict[str, Any]] = []
    guidance: list[str] = []
    cleanup: list[dict[str, Any]] = []

    try:
        payload = _read_json_mapping(hooks_path, "global hooks.json") if hooks_path.exists() else {"hooks": {}}
        try:
            _validate_hook_payload(payload)
        except ValueError as exc:
            raise UpgradeException(
                UpgradeErrorCode.SOURCE_INVALID,
                str(exc),
                component="codex_hook",
                path=hooks_path.as_posix(),
            ) from exc
        inventory = _hook_inventory(payload)
        if inventory["ambiguous_events"]:
            raise UpgradeException(
                UpgradeErrorCode.BLOCKED,
                "TreeWiki/LMWiki-like command has no recognized owned marker",
                component="codex_hook",
                path=hooks_path.as_posix(),
            )
    except UpgradeException as exc:
        errors.append(exc.as_error())
        return (
            _component("codex_hook", ComponentStatus.INVALID),
            _component("codex_hook_settings", ComponentStatus.UNKNOWN),
            [],
            errors,
            guidance,
            cleanup,
        )

    owned_count = int(inventory["owned_count"])
    legacy_count = int(inventory["legacy_count"])
    duplicate_events = list(inventory["duplicate_events"])
    transition_payload = copy.deepcopy(payload)
    if owned_count:
        _transition_owned_hooks(transition_payload, runner_path)
    registration_changed = transition_payload != payload
    runner_current = bool(
        source_runner.is_file()
        and runner_path.is_file()
        and _hash_file_or_missing(source_runner) == _hash_file_or_missing(runner_path)
    )

    settings_status = ComponentStatus.DISABLED if not owned_count else ComponentStatus.MISSING
    settings_target_bytes: bytes | None = None
    settings_source: Path | None = None
    try:
        fallback, settings_source, used_legacy = _load_hook_settings_source(
            settings_path, legacy_settings_path
        )
        if settings_path.exists():
            settings_status = ComponentStatus.CURRENT
            if legacy_settings_path.exists():
                cleanup.append(
                    {"component": "codex_hook_settings", "path": legacy_settings_path.as_posix(), "deletes": []}
                )
        elif used_legacy and settings_source is not None and fallback is not None:
            settings_status = ComponentStatus.LEGACY_DETECTED
            settings_target_bytes = _json_bytes(
                {
                    "schema": "treewiki.hook-settings/v1",
                    "fallback_repository": str(fallback),
                }
            )
        elif owned_count:
            settings_status = ComponentStatus.MISSING
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(
            UpgradeError(
                code=UpgradeErrorCode.SOURCE_INVALID.value,
                message=str(exc),
                component="codex_hook_settings",
                path=(settings_path if settings_path.exists() else legacy_settings_path).as_posix(),
            )
        )
        settings_status = ComponentStatus.INVALID

    if duplicate_events:
        hook_status = ComponentStatus.CONFLICT
    elif capture == "hook" or legacy_count:
        hook_status = ComponentStatus.LEGACY_DETECTED
    elif owned_count and (registration_changed or not runner_current):
        hook_status = ComponentStatus.UPGRADE_REQUIRED
    elif owned_count:
        hook_status = ComponentStatus.CURRENT
    else:
        hook_status = ComponentStatus.DISABLED if not hooks_enabled else ComponentStatus.MISSING

    if capture == "hook":
        guidance.append(
            "Legacy memory.capture=hook requires the config stage to approve capture=explicit before hook migration."
        )
    if owned_count and "hook" not in selected_stages:
        guidance.append("Select --stage hook to inspect global Codex hook targets.")
    elif owned_count and not approve_global_hook:
        guidance.append(
            "Re-run with --approve-global-hook to authorize mutation of global Codex hook targets."
        )

    can_plan = (
        owned_count > 0
        and "hook" in selected_stages
        and approve_global_hook
        and capture_transition_approved
        and not errors
    )
    if can_plan:
        guidance.append(
            "The global-hook approval authorizes mutation of existing owned registrations under the global Codex home."
        )
        if not source_runner.is_file():
            errors.append(
                UpgradeError(
                    code=UpgradeErrorCode.SOURCE_INVALID.value,
                    message="TreeWiki hook runner is missing from the executing skill",
                    component="codex_hook",
                    path=source_runner.as_posix(),
                )
            )
            hook_status = ComponentStatus.INVALID
        else:
            source_hash = _hash_file_or_missing(source_runner)
            if not runner_current:
                actions.append(
                    {
                        "id": "install_treewiki_hook_runner",
                        "stage": "hook",
                        "kind": "atomic_file_replace",
                        "target": runner_path.as_posix(),
                        "source": source_runner.as_posix(),
                        "source_sha256": source_hash,
                        "observed_sha256": _hash_file_or_missing(runner_path),
                        "target_sha256": source_hash,
                    }
                )
            if settings_target_bytes is not None and settings_source is not None:
                actions.append(
                    {
                        "id": "migrate_treewiki_hook_settings",
                        "stage": "hook",
                        "kind": "atomic_file_replace",
                        "target": settings_path.as_posix(),
                        "source": settings_source.as_posix(),
                        "source_sha256": _hash_file_or_missing(settings_source),
                        "target_content": settings_target_bytes.decode("utf-8"),
                        "observed_sha256": _hash_file_or_missing(settings_path),
                        "target_sha256": _sha256_bytes(settings_target_bytes),
                    }
                )
            if registration_changed:
                target_bytes = _json_bytes(transition_payload)
                actions.append(
                    {
                        "id": "transition_codex_hook_registration",
                        "stage": "hook",
                        "kind": "atomic_file_replace",
                        "target": hooks_path.as_posix(),
                        "target_content": target_bytes.decode("utf-8"),
                        "observed_sha256": _hash_file_or_missing(hooks_path),
                        "target_sha256": _sha256_bytes(target_bytes),
                    }
                )

    return (
        _component(
            "codex_hook",
            hook_status,
            resolvable=bool(duplicate_events and can_plan and not errors),
            hooks_enabled=hooks_enabled,
            capture=capture,
            **inventory,
        ),
        _component("codex_hook_settings", settings_status),
        actions,
        errors,
        guidance,
        cleanup,
    )


def _load_memory_policy() -> Any | None:
    """Load memory_policy lazily so the two modules never circular-import at import time."""
    for module_name in ("memory_policy", ".memory_policy"):
        try:
            if module_name.startswith("."):
                package = __package__
                if not package:
                    continue
                return importlib.import_module(module_name, package)
            return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            missing = module_name.lstrip(".")
            if exc.name not in {missing, f"{__package__}.{missing}" if __package__ else missing}:
                raise
    return None


def _memory_source_inventory(repository: Path) -> list[dict[str, str]]:
    """Return safe legacy-memory metadata; never expose source paths or bodies."""
    result: list[dict[str, str]] = []
    private_root = repository / ".knowledge" / "private-memory"
    for level in ("l1", "l2", "l3"):
        level_root = private_root / level
        if not level_root.is_dir():
            continue
        for path in sorted(level_root.rglob("*.md"), key=lambda item: item.as_posix()):
            if not path.is_file():
                continue
            document_id = _document_id(path)
            visibility = "unknown"
            try:
                text = path.read_text(encoding="utf-8")
                parts = text.split("---", 2)
                metadata = yaml.safe_load(parts[1]) if len(parts) == 3 else None
                if isinstance(metadata, Mapping):
                    access = metadata.get("access")
                    if isinstance(access, Mapping) and isinstance(access.get("visibility"), str):
                        visibility = str(access["visibility"])
            except (OSError, UnicodeError, yaml.YAMLError):
                pass
            result.append(
                {"id": document_id or "invalid", "level": level, "visibility": visibility}
            )
    return result


def _resolve_memory_target(repository: Path, value: str, level: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            "memory-layout target escapes the repository",
            component="memory_layout",
        )
    repository = repository.resolve(strict=True)
    lexical_target = repository / relative
    lexical_allowed = repository / "docs" / "memory" / level
    try:
        lexical_target.relative_to(lexical_allowed)
    except ValueError as exc:
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            "memory-layout target is outside the canonical shared-memory level",
            component="memory_layout",
        ) from exc

    def is_link_or_reparse(path: Path) -> bool:
        if path.is_symlink():
            return True
        try:
            return bool(path.stat().st_file_attributes & 0x400)
        except (AttributeError, OSError):
            return False

    current = repository / "docs"
    for part in ("memory", level, *relative.parts[3:]):
        if current.exists() and is_link_or_reparse(current):
            raise UpgradeException(
                UpgradeErrorCode.BLOCKED,
                f"memory-layout path uses a symlink or reparse point: {current}",
                component="memory_layout",
            )
        current = current / part
    if current.exists() and is_link_or_reparse(current):
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            f"memory-layout target uses a symlink or reparse point: {current}",
            component="memory_layout",
        )

    target = lexical_target.resolve(strict=False)
    allowed = lexical_allowed.resolve(strict=False)
    try:
        target.relative_to(allowed)
    except ValueError as exc:
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            "memory-layout target is outside the approved shared-memory level",
            component="memory_layout",
        ) from exc
    private_root = (repository / ".knowledge" / "private-memory").resolve(strict=False)
    try:
        target.relative_to(private_root)
    except ValueError:
        pass
    else:
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            "shared memory target resolves into private memory",
            component="memory_layout",
        )
    return target


def _plan_memory_layout(
    repository: Path,
    config: Mapping[str, Any],
    approved_memory_ids: Sequence[str],
    *,
    approvals: Mapping[str, Mapping[str, Any]] | None,
    planner: MemoryLayoutPlanner | None,
) -> tuple[Mapping[str, Any] | None, list[dict[str, Any]]]:
    policy = _load_memory_policy()
    plan_function = planner or (getattr(policy, "plan_memory_layout", None) if policy else None)
    if plan_function is None:
        if approved_memory_ids:
            raise UpgradeException(
                UpgradeErrorCode.BLOCKED,
                "memory-layout approval was provided but memory_policy is unavailable",
                component="memory_layout",
            )
        return None, []
    try:
        raw_plan = plan_function(
            repository,
            config,
            approved_memory_ids,
            approvals=approvals,
        )
        # The CLI's compatibility seam historically returned an empty shell
        # when no IDs were approved. Enrich that read-only shell with the real
        # policy inventory so status can expose safe dispositions and a stable
        # approval target set without changing the public CLI arguments.
        if (
            planner is not None
            and not approved_memory_ids
            and isinstance(raw_plan, Mapping)
            and "dispositions" not in raw_plan
            and policy is not None
            and callable(getattr(policy, "plan_memory_layout", None))
        ):
            raw_plan = policy.plan_memory_layout(
                repository,
                config,
                approved_memory_ids,
                approvals=approvals,
            )
    except Exception as exc:
        code = str(getattr(exc, "code", ""))
        mapped = (
            UpgradeErrorCode.MEMORY_TARGET_CONFLICT
            if code in {"MEMORY_TARGET_CONFLICT", "TARGET_CONFLICT"}
            else UpgradeErrorCode.BLOCKED
        )
        raise UpgradeException(mapped, str(exc), component="memory_layout") from exc
    if not isinstance(raw_plan, Mapping):
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            "memory_policy returned an invalid plan",
            component="memory_layout",
        )
    raw_actions = raw_plan.get("eligible_actions", raw_plan.get("actions", []))
    if not isinstance(raw_actions, list):
        raise UpgradeException(
            UpgradeErrorCode.SOURCE_INVALID,
            "memory_policy actions must be a list",
            component="memory_layout",
        )
    public_actions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_actions:
        if not isinstance(item, Mapping):
            raise UpgradeException(
                UpgradeErrorCode.SOURCE_INVALID,
                "memory_policy action must be a mapping",
                component="memory_layout",
            )
        memory_id = str(item.get("memory_id", ""))
        level = str(item.get("level", ""))
        if not memory_id or memory_id in seen_ids or level not in {"l1", "l2", "l3"}:
            raise UpgradeException(
                UpgradeErrorCode.SOURCE_INVALID,
                "memory_policy returned an invalid or duplicate memory ID/level",
                component="memory_layout",
            )
        seen_ids.add(memory_id)
        target = _resolve_memory_target(repository, str(item.get("target_path", "")), level)
        expected = _normalize_sha256(
            str(item.get("expected_file_sha256", "")), field="expected_file_sha256"
        )
        observed = _hash_file_or_missing(target)
        if observed != "missing" and observed != expected:
            raise UpgradeException(
                UpgradeErrorCode.MEMORY_TARGET_CONFLICT,
                f"shared memory target conflicts for {memory_id}",
                component="memory_layout",
            )
        if observed == expected:
            continue
        body_sha = _normalize_sha256(
            str(item.get("body_sha256", "")), field="body_sha256"
        )
        lineage = _normalize_sha256(
            str(item.get("lineage_digest", "")), field="lineage_digest"
        )
        public_actions.append(
            {
                "id": f"share_memory:{memory_id}",
                "stage": "memory-layout",
                "kind": "atomic_create",
                "memory_id": memory_id,
                "level": level,
                "target": target.as_posix(),
                "observed_sha256": observed,
                "target_sha256": expected,
                "body_sha256": body_sha,
                "lineage_digest": lineage,
                "relation_before": copy.deepcopy(item.get("relation_before", [])),
                "relation_after": copy.deepcopy(item.get("relation_after", [])),
            }
        )
    approved = set(approved_memory_ids)
    planned = {str(action["memory_id"]) for action in public_actions}
    raw_approved = {str(value) for value in raw_plan.get("approved_ids", [])}
    if raw_approved != approved:
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            "memory_policy approval set does not exactly match --approve-memory-id",
            component="memory_layout",
        )
    approval_targets = {
        str(value) for value in raw_plan.get("approval_targets", raw_plan.get("approved_ids", []))
    }
    if not approved.issubset(approval_targets):
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            "--approve-memory-id contains a document outside the share disposition set",
            component="memory_layout",
        )
    if not planned.issubset(approval_targets):
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED,
            "memory-layout eligible action set differs from approval targets",
            component="memory_layout",
        )
    normalized_plan = dict(raw_plan)
    aggregate = str(raw_plan.get("aggregate_lineage_digest", ""))
    if public_actions or aggregate:
        normalized_plan["aggregate_lineage_digest"] = _normalize_sha256(
            aggregate, field="aggregate_lineage_digest"
        )
    return normalized_plan, public_actions


def _adapter_repository_root(root: Path, executing_root: Path) -> Path:
    """Prefer repository-owned adapter sources over an installed skill's parent."""

    if (root / "plugins" / "treewiki" / "plugin.json").is_file():
        return root
    return executing_root.parents[1]


def diagnose_upgrade(
    repository: str | Path,
    *,
    skill_root: str | Path | None = None,
    source: str | Path | None = None,
    check_latest: bool = False,
    offline: bool = False,
    stages: str | Iterable[str] | None = None,
    approved_memory_ids: Sequence[str] = (),
    memory_approvals: Mapping[str, Mapping[str, Any]] | None = None,
    relation_mapping: Sequence[Mapping[str, Any]] = (),
    repository_skill_root: str | Path | None = None,
    global_skill_root: str | Path | None = None,
    approve_global_skill: bool = False,
    approve_global_hook: bool = False,
    codex_home: str | Path | None = None,
    latest_fetcher: LatestFetcher | None = None,
    memory_layout_planner: MemoryLayoutPlanner | None = None,
) -> dict[str, Any]:
    """Build a deterministic, read-only status and upgrade plan."""
    selected_stages = normalize_stages(stages)
    try:
        root = Path(repository).resolve(strict=True)
    except OSError as exc:
        raise UpgradeException(
            UpgradeErrorCode.IO_FAILURE, f"repository is unavailable: {exc}", path=str(repository)
        ) from exc
    if not root.is_dir():
        raise UpgradeException(
            UpgradeErrorCode.INVALID_INPUT, "repository must be a directory", path=str(root)
        )
    executing_root = (
        Path(skill_root).resolve(strict=True)
        if skill_root is not None
        else Path(__file__).resolve().parents[1]
    )
    embedded_path = executing_root / MANIFEST_FILENAME
    embedded, target, authority_kind, authority_availability, payload_root, errors = _resolve_authority(
        embedded_path,
        source=source,
        check_latest=check_latest,
        offline=offline,
        latest_fetcher=latest_fetcher,
    )
    target_digest = manifest_digest(target)

    components: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    guidance = {"dry_run": [], "apply": [], "verify": []}
    cleanup_candidates: list[dict[str, Any]] = []
    if selected_stages:
        actions.extend(_upgrade_ignore_actions(root, selected_stages[0]))

    config_path = root / CONFIG_PATH
    config: dict[str, Any] | None = None
    config_version: int | None = None
    target_config: dict[str, Any] | None = None
    if not config_path.is_file():
        components.append(_component("repository_config", ComponentStatus.MISSING))
        errors.append(
            UpgradeError(
                code=UpgradeErrorCode.BLOCKED.value,
                message="repository config is missing",
                component="repository_config",
                path=CONFIG_PATH.as_posix(),
            )
        )
    else:
        try:
            config = _read_yaml_mapping(config_path)
            raw_version = config.get("version")
            if not isinstance(raw_version, int) or isinstance(raw_version, bool):
                raise UpgradeException(
                    UpgradeErrorCode.SOURCE_INVALID, "config version must be an integer"
                )
            config_version = raw_version
            if raw_version > target.config_schema.maximum:
                components.append(
                    _component(
                        "repository_config",
                        ComponentStatus.INCOMPATIBLE_NEWER,
                        observed_version=raw_version,
                        supported_min=target.config_schema.minimum,
                        supported_max=target.config_schema.maximum,
                    )
                )
            elif raw_version < target.config_schema.minimum:
                components.append(
                    _component(
                        "repository_config",
                        ComponentStatus.INVALID,
                        observed_version=raw_version,
                        supported_min=target.config_schema.minimum,
                        supported_max=target.config_schema.maximum,
                    )
                )
            else:
                target_config = migrate_config_v5(config)
                config_changed = target_config != config
                components.append(
                    _component(
                        "repository_config",
                        ComponentStatus.UPGRADE_REQUIRED if config_changed else ComponentStatus.CURRENT,
                        observed_version=raw_version,
                        target_version=TARGET_CONFIG_VERSION,
                        supported_min=target.config_schema.minimum,
                        supported_max=target.config_schema.maximum,
                    )
                )
                if config_changed and "config" in selected_stages:
                    target_bytes = _yaml_bytes(target_config)
                    actions.append(
                        {
                            "id": "migrate_repository_config_v5",
                            "stage": "config",
                            "kind": "atomic_replace",
                            "target": config_path.as_posix(),
                            "observed_sha256": _hash_file_or_missing(config_path),
                            "target_sha256": _sha256_bytes(target_bytes),
                        }
                    )
        except UpgradeException as exc:
            status = (
                ComponentStatus.INCOMPATIBLE_NEWER
                if exc.code == UpgradeErrorCode.INCOMPATIBLE_NEWER
                else ComponentStatus.INVALID
            )
            components.append(_component("repository_config", status))
            errors.append(exc.as_error())

    executing_problems = verify_payload(embedded, executing_root, require_complete=True)
    components.append(
        _component(
            "executing_skill",
            ComponentStatus.CURRENT if not executing_problems else ComponentStatus.UPGRADE_REQUIRED,
            release=str(embedded.release),
            problems=[_problem_dict(problem) for problem in executing_problems],
        )
    )

    repository_copy = (
        Path(repository_skill_root).resolve()
        if repository_skill_root is not None
        else root / ".agents" / "skills" / "treewiki"
    )
    repo_status, repo_problems = _inspect_skill(
        repository_copy, target, missing_status=ComponentStatus.MISSING
    )
    components.append(
        _component("repository_skill_copy", repo_status, problems=repo_problems)
    )
    if (
        payload_root is not None
        and "runtime" in selected_stages
        and repo_status != ComponentStatus.CURRENT
    ):
        actions.append(
            {
                "id": "copy_repository_treewiki_skill",
                "stage": "runtime",
                "kind": "atomic_directory_replace",
                "target": repository_copy.as_posix(),
                "source": payload_root.as_posix(),
                "observed_sha256": _directory_digest(repository_copy),
                "target_sha256": _directory_digest(payload_root),
            }
        )

    global_copy = (
        Path(global_skill_root).expanduser().resolve()
        if global_skill_root is not None
        else Path.home() / ".agents" / "skills" / "treewiki"
    )
    global_status, global_problems = _inspect_skill(
        global_copy, target, missing_status=ComponentStatus.MISSING
    )
    components.append(
        _component("global_skill_copy", global_status, problems=global_problems)
    )
    if (
        payload_root is not None
        and "runtime" in selected_stages
        and global_status != ComponentStatus.CURRENT
        and approve_global_skill
    ):
        actions.append(
            {
                "id": "copy_global_treewiki_skill",
                "stage": "runtime",
                "kind": "atomic_directory_replace",
                "target": global_copy.as_posix(),
                "source": payload_root.as_posix(),
                "observed_sha256": _directory_digest(global_copy),
                "target_sha256": _directory_digest(payload_root),
            }
        )
    elif global_status != ComponentStatus.CURRENT and "runtime" in selected_stages:
        guidance["apply"].append(
            "Global TreeWiki skill copy differs; re-run with --approve-global-skill to authorize that target."
        )

    (
        hook_component,
        hook_settings_component,
        hook_actions,
        hook_errors,
        hook_guidance,
        hook_cleanup,
    ) = _diagnose_hooks(
        config=config,
        target_config=target_config,
        selected_stages=selected_stages,
        executing_root=executing_root,
        codex_home=codex_home,
        approve_global_hook=approve_global_hook,
    )
    components.extend((hook_component, hook_settings_component))
    actions.extend(hook_actions)
    errors.extend(hook_errors)
    guidance["apply"].extend(hook_guidance)
    cleanup_candidates.extend(hook_cleanup)

    legacy_candidates = [
        root / ".agents" / "skills" / "lmwiki",
        root / "skills" / "lmwiki-builder",
        root / "skills" / "lmwiki-steward",
    ]
    existing_legacy = sum(path.exists() for path in legacy_candidates)
    components.append(
        _component(
            "legacy_sources",
            ComponentStatus.LEGACY_DETECTED if existing_legacy else ComponentStatus.CURRENT,
            count=existing_legacy,
        )
    )
    if existing_legacy:
        cleanup_candidates.append(
            {"component": "legacy_sources", "count": existing_legacy, "deletes": []}
        )

    legacy_memory = _memory_source_inventory(root)
    legacy_memory_count = len(legacy_memory)
    memory_config_current = bool(
        config
        and config_version == TARGET_CONFIG_VERSION
        and isinstance(config.get("memory"), Mapping)
        and config["memory"].get("layout_version") == MEMORY_LAYOUT_VERSION
        and config["memory"].get("private_path") == ".knowledge/private-memory"
        and config["memory"].get("shared_path") == "docs/memory"
    )
    memory_plan: Mapping[str, Any] | None = None
    memory_actions: list[dict[str, Any]] = []
    memory_error: UpgradeException | None = None
    if "memory-layout" in selected_stages:
        try:
            memory_plan, memory_actions = _plan_memory_layout(
                root,
                config or {},
                approved_memory_ids,
                approvals=memory_approvals,
                planner=memory_layout_planner,
            )
            actions.extend(memory_actions)
        except UpgradeException as exc:
            memory_error = exc
            errors.append(exc.as_error())
    memory_dispositions = (
        copy.deepcopy(memory_plan.get("dispositions", []))
        if memory_plan is not None and isinstance(memory_plan.get("dispositions", []), list)
        else []
    )
    approval_targets = (
        sorted(
            {
                str(value)
                for value in memory_plan.get(
                    "approval_targets", memory_plan.get("approved_ids", [])
                )
            }
        )
        if memory_plan is not None
        else []
    )
    unresolved_memory = [
        item
        for item in memory_dispositions
        if isinstance(item, Mapping) and item.get("disposition") != "share"
    ]
    if legacy_memory_count and not approval_targets:
        # An explicit config-stage apply may preserve every non-shareable item
        # in the ignored legacy root while adopting the v3 canonical layout.
        # This does not approve or copy any memory document.
        guidance["apply"].append(
            "A config-only apply preserves blocked/review legacy memory in place; it does not share it."
        )
    if legacy_memory_count and set(approved_memory_ids) != set(approval_targets):
        guidance["dry_run"].append(
            "Review memory-layout dispositions and enumerate the exact approval_targets values."
        )
    if unresolved_memory:
        guidance["dry_run"].append(
            "Resolve blocked_sensitive and needs_claim_review metadata before those documents can be shared."
        )
    memory_status = (
        ComponentStatus.CONFLICT
        if memory_error and memory_error.code == UpgradeErrorCode.MEMORY_TARGET_CONFLICT
        else ComponentStatus.INVALID
        if memory_error
        else ComponentStatus.UPGRADE_REQUIRED
        if legacy_memory_count or not memory_config_current
        else ComponentStatus.CURRENT
    )
    memory_details: dict[str, Any] = {
        "legacy_private_memory_count": legacy_memory_count,
        "legacy_private_memory": legacy_memory,
        "approved_ids": sorted(set(approved_memory_ids)),
        "approval_targets": approval_targets,
        "dispositions": memory_dispositions,
    }
    if memory_plan is not None:
        memory_details["aggregate_lineage_digest"] = str(
            memory_plan.get("aggregate_lineage_digest", "")
        )
    components.append(_component("memory_layout", memory_status, **memory_details))
    components.append(_component("l3_candidate_state", ComponentStatus.CURRENT))

    history_config = target_config if target_config is not None else config
    missing_history: list[str] = []
    if isinstance(history_config, Mapping):
        try:
            history_documents = _load_managed_documents()(root, dict(history_config))
            for document in history_documents:
                try:
                    text = document.read_text(encoding="utf-8")
                    if not text.startswith("---"):
                        missing_history.append(document.relative_to(root).as_posix())
                        continue
                    metadata, body = parse_document_text(text)
                    if not isinstance(metadata, Mapping) or not isinstance(metadata.get("id"), str):
                        missing_history.append(document.relative_to(root).as_posix())
                        continue
                    document_id = str(metadata["id"])
                    sidecar = history_path_for(root, document_id)
                    legacy_sidecar = document.with_name(f"{document_id}.history.jsonl")
                    events = read_history(sidecar)
                    required = {"created_at", "modified_at", "verified_at", "revision", "history_ref"}
                    if (
                        not required.issubset(metadata)
                        or metadata.get("history_ref") != history_ref_for(document_id)
                        or legacy_sidecar.exists()
                    ):
                        missing_history.append(document.relative_to(root).as_posix())
                        continue
                    if events and events[-1].get("semantic_hash") != semantic_components(metadata, body)["semantic_hash"]:
                        missing_history.append(document.relative_to(root).as_posix())
                except (OSError, UnicodeError, ValueError, yaml.YAMLError):
                    missing_history.append(document.relative_to(root).as_posix())
        except (OSError, ValueError):
            missing_history = ["<inventory-unavailable>"]
    components.append(
        _component(
            "document_history",
            ComponentStatus.UPGRADE_REQUIRED if missing_history else ComponentStatus.CURRENT,
            schema=1,
            missing_count=len(missing_history),
            missing_paths=missing_history,
        )
    )
    if missing_history:
        guidance["apply"].append(
            "Run manage document-finalize as a dry-run, then apply its exact plan ID to backfill document-history."
        )

    repository_root = _adapter_repository_root(root, executing_root)
    release_runtime = embedded.to_dict().get("runtime")
    expected_core_hash = (
        release_runtime.get("core_hash") if isinstance(release_runtime, Mapping) else None
    )

    def inspect_adapter(
        plugin_root: Path, manifest_path: Path, expected_name: str
    ) -> tuple[ComponentStatus, str | None, str | None]:
        try:
            plugin_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            runtime_data = json.loads(
                (plugin_root / "runtime" / "runtime-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            version = (
                str(plugin_data.get("version"))
                if isinstance(plugin_data, Mapping) and plugin_data.get("version")
                else None
            )
            adapter_core_hash = (
                str(runtime_data.get("core_hash"))
                if isinstance(runtime_data, Mapping) and runtime_data.get("core_hash")
                else None
            )
            runtime_files = (
                runtime_data.get("files") if isinstance(runtime_data, Mapping) else None
            )
            runtime_files_current = isinstance(runtime_files, Mapping) and all(
                _hash_file_or_missing(plugin_root / "runtime" / str(name))
                == str(digest)
                for name, digest in runtime_files.items()
            )
            current = (
                plugin_data.get("name") == expected_name
                and version == str(embedded.release)
                and runtime_data.get("release_version") == str(embedded.release)
                and adapter_core_hash == expected_core_hash
                and runtime_files_current
            )
            return (
                ComponentStatus.CURRENT if current else ComponentStatus.UPGRADE_REQUIRED,
                version,
                adapter_core_hash,
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ComponentStatus.MISSING, None, None

    installed_agent_context = (repository_root / "plugin.json").is_file()
    claude_root = repository_root / "plugins" / "treewiki-claude"
    if installed_agent_context:
        claude_status, claude_version, claude_core_hash = (
            ComponentStatus.UNKNOWN,
            None,
            None,
        )
    else:
        claude_status, claude_version, claude_core_hash = inspect_adapter(
            claude_root, claude_root / ".claude-plugin" / "plugin.json", "treewiki"
        )
    agent_root = (
        repository_root
        if installed_agent_context
        else repository_root / "plugins" / "treewiki"
    )
    agent_version: str | None = None
    agent_core_hash: str | None = None
    portable_manifest_status = ComponentStatus.MISSING
    mcp_config_status = ComponentStatus.MISSING
    codex_manifest_status = ComponentStatus.MISSING
    marketplace_status = ComponentStatus.MISSING
    bundle_status = ComponentStatus.MISSING
    try:
        portable = json.loads((agent_root / "plugin.json").read_text(encoding="utf-8"))
        mcp_config = json.loads((agent_root / "mcp.json").read_text(encoding="utf-8"))
        codex_manifest = json.loads(
            (agent_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        marketplace_path = repository_root / ".agents" / "plugins" / "marketplace.json"
        marketplace = (
            json.loads(marketplace_path.read_text(encoding="utf-8"))
            if marketplace_path.is_file()
            else None
        )
        runtime_data = json.loads(
            (agent_root / "runtime-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        agent_version = str(portable.get("version"))
        agent_core_hash = str(runtime_data.get("core_hash"))
        portable_manifest_status = (
            ComponentStatus.CURRENT
            if portable.get("$schema")
            == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
            and portable.get("name") == "treewiki"
            and agent_version == str(embedded.release)
            else ComponentStatus.UPGRADE_REQUIRED
        )
        server = (
            mcp_config.get("mcpServers", {}).get("treewiki", {})
            if isinstance(mcp_config, Mapping)
            else {}
        )
        mcp_config_status = (
            ComponentStatus.CURRENT
            if mcp_config.get("$schema")
            == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
            and server.get("type") == "stdio"
            and server.get("command") == "node"
            and "${PLUGIN_ROOT}/dist/treewiki-mcp.mjs" in server.get("args", [])
            else ComponentStatus.UPGRADE_REQUIRED
        )
        codex_manifest_status = (
            ComponentStatus.CURRENT
            if codex_manifest.get("name") == "treewiki"
            and codex_manifest.get("version") == str(embedded.release)
            and codex_manifest.get("mcpServers") == "./.mcp.json"
            else ComponentStatus.UPGRADE_REQUIRED
        )
        marketplace_status = (
            ComponentStatus.UNKNOWN
            if marketplace is None and installed_agent_context
            else
            ComponentStatus.CURRENT
            if isinstance(marketplace, Mapping)
            and marketplace.get("name") == "treewiki-marketplace"
            and any(
                item.get("name") == "treewiki"
                and item.get("source", {}).get("path") == "./plugins/treewiki"
                for item in marketplace.get("plugins", [])
                if isinstance(item, Mapping)
            )
            else ComponentStatus.UPGRADE_REQUIRED
        )
        adapters = embedded.to_dict().get("adapters", {})
        expected_agent = adapters.get("codex", {}) if isinstance(adapters, Mapping) else {}
        bundle_status = (
            ComponentStatus.CURRENT
            if _hash_file_or_missing(agent_root / "dist" / "treewiki-mcp.mjs")
            == expected_agent.get("bundle_hash")
            else ComponentStatus.UPGRADE_REQUIRED
        )
        runtime_files = runtime_data.get("files", {})
        runtime_files_current = isinstance(runtime_files, Mapping) and all(
            _hash_file_or_missing(agent_root / "skills" / "treewiki" / "scripts" / str(name))
            == str(digest)
            for name, digest in runtime_files.items()
        )
        agent_status = (
            ComponentStatus.CURRENT
            if all(
                status == ComponentStatus.CURRENT
                for status in (
                    portable_manifest_status,
                    mcp_config_status,
                    codex_manifest_status,
                    bundle_status,
                )
            )
            and marketplace_status in {ComponentStatus.CURRENT, ComponentStatus.UNKNOWN}
            and agent_core_hash == expected_core_hash
            and runtime_files_current
            else ComponentStatus.UPGRADE_REQUIRED
        )
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, TypeError):
        agent_status = ComponentStatus.MISSING
    adapter_status = (
        agent_status
        if installed_agent_context
        else ComponentStatus.CURRENT
        if claude_status == agent_status == ComponentStatus.CURRENT
        else ComponentStatus.MISSING
        if claude_status == agent_status == ComponentStatus.MISSING
        else ComponentStatus.UPGRADE_REQUIRED
    )
    components.append(
        _component(
            "adapters",
            adapter_status,
            claude_plugin_version=claude_version,
            claude_status=claude_status.value,
            claude_core_hash=claude_core_hash,
            agent_plugin_version=agent_version,
            agent_plugin_status=agent_status.value,
            agent_plugin_core_hash=agent_core_hash,
            portable_manifest_status=portable_manifest_status.value,
            mcp_config_status=mcp_config_status.value,
            codex_manifest_status=codex_manifest_status.value,
            marketplace_status=marketplace_status.value,
            bundle_status=bundle_status.value,
        )
    )

    claude_base = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser()
    user_alias = claude_base / "skills" / "treewiki" / "SKILL.md"
    project_alias = root / ".claude" / "skills" / "treewiki" / "SKILL.md"
    alias_paths = [path for path in (user_alias, project_alias) if path.is_file()]
    alias_version_marker = f"Expected TreeWiki plugin version: `{embedded.release}`."
    try:
        alias_version_current = (
            all(alias_version_marker in path.read_text(encoding="utf-8") for path in alias_paths)
            if alias_paths
            else False
        )
    except (OSError, UnicodeError):
        alias_version_current = False
    alias_status = (
        ComponentStatus.CONFLICT
        if len(alias_paths) > 1
        else ComponentStatus.CURRENT
        if alias_paths and alias_version_current
        else ComponentStatus.UPGRADE_REQUIRED
        if alias_paths
        else ComponentStatus.MISSING
    )
    components.append(
        _component(
            "claude_alias",
            alias_status,
            installed=[path.as_posix() for path in alias_paths],
            warning="ALIAS_SHADOWED" if len(alias_paths) > 1 else None,
        )
    )

    effective_index_config = (
        target_config
        if target_config is not None
        and any(action.get("id") == "migrate_repository_config_v5" for action in actions)
        else config
    )
    retrieval = (
        effective_index_config.get("retrieval")
        if isinstance(effective_index_config, Mapping)
        else None
    )
    embedding = (
        effective_index_config.get("embedding")
        if isinstance(effective_index_config, Mapping)
        else None
    )
    index_enabled = bool(
        isinstance(retrieval, Mapping)
        and retrieval.get("bm25_enabled")
        and isinstance(embedding, Mapping)
        and embedding.get("enabled")
    )
    if not index_enabled:
        components.append(_component("search_index", ComponentStatus.DISABLED))
    else:
        try:
            index_path = _index_target(root, effective_index_config or {})
            builder = executing_root / "scripts" / "build_search_index.py"
            if not builder.is_file():
                raise UpgradeException(
                    UpgradeErrorCode.SOURCE_INVALID,
                    "build_search_index.py is unavailable for index contract calculation",
                    component="search_index",
                )
            builder_sha256 = _hash_file_or_missing(builder)
            planned_files = {
                Path(str(action["target"])).relative_to(root).as_posix(): str(
                    action["target_sha256"]
                )
                for action in memory_actions
            }
            expected_contract = _expected_index_contract(
                root,
                effective_index_config or {},
                builder_sha256=builder_sha256,
                planned_files=planned_files,
            )
            observed_contract = _read_index_contract(index_path)
            index_status = (
                ComponentStatus.MISSING
                if not index_path.is_file()
                else ComponentStatus.CURRENT
                if observed_contract == expected_contract
                else ComponentStatus.UPGRADE_REQUIRED
            )
            components.append(
                _component(
                    "search_index",
                    index_status,
                    expected_contract_digest=_index_contract_digest(expected_contract),
                    observed_contract_digest=(
                        _index_contract_digest(observed_contract)
                        if observed_contract is not None
                        else "unavailable"
                    ),
                )
            )
            if index_status != ComponentStatus.CURRENT and "index" in selected_stages:
                actions.append(
                    {
                        "id": "rebuild_search_index",
                        "stage": "index",
                        "kind": "rebuild_index",
                        "target": index_path.as_posix(),
                        "source": builder.as_posix(),
                        "source_sha256": builder_sha256,
                        "observed_sha256": _hash_file_or_missing(index_path),
                        "target_sha256": _index_contract_digest(expected_contract),
                        "expected_contract": expected_contract,
                    }
                )
        except UpgradeException as exc:
            components.append(_component("search_index", ComponentStatus.INVALID))
            errors.append(exc.as_error())

    protected = protected_knowledge_inventory(root)
    protected["memory_layout"] = {
        "lineage_digest": str(
            memory_plan.get("aggregate_lineage_digest", "")
            if memory_plan is not None
            else ""
        ),
        "approval_targets": approval_targets,
    }
    components.append(
        _component(
            "protected_knowledge",
            ComponentStatus.CURRENT,
            l0_count=protected["l0"]["count"],
            l0_digest=protected["l0"]["digest"],
            managed_count=protected["managed"]["count"],
            managed_digest=protected["managed"]["digest"],
        )
    )

    official_newer = (
        authority_kind == AuthorityKind.OFFICIAL
        and authority_availability == AuthorityAvailability.AVAILABLE
        and compare_semver(target.release, embedded.release) > 0
    )
    if official_newer:
        guidance["apply"].append(target.distribution.install_command)
        # An official manifest is metadata, never an executable/copyable payload.
        actions = [action for action in actions if action.get("stage") != "runtime"]

    plan_id = _canonical_plan_id(
        actions,
        digest=target_digest,
        config_version=config_version,
        protected=protected,
        approval_targets=approval_targets,
        relation_mapping=relation_mapping,
        approve_global_skill=approve_global_skill,
        approve_global_hook=approve_global_hook,
    )
    overall_status = _derive_overall(
        components, authority_availability == AuthorityAvailability.UNKNOWN
    )
    if actions and overall_status in {
        OverallStatus.CURRENT,
        OverallStatus.GUIDANCE_REQUIRED,
    }:
        overall_status = OverallStatus.UPGRADE_REQUIRED
    legacy_hook_requires_config = bool(
        "hook" in selected_stages
        and "config" not in selected_stages
        and hook_component.get("capture") == "hook"
    )
    apply_allowed = (
        overall_status != OverallStatus.BLOCKED
        and authority_availability == AuthorityAvailability.AVAILABLE
        and not official_newer
        and not executing_problems
        and not legacy_hook_requires_config
        and (bool(actions) or overall_status == OverallStatus.CURRENT)
        and (
            not legacy_memory_count
            or set(approved_memory_ids) == set(approval_targets)
        )
    )
    if actions:
        guidance["dry_run"].append("Re-run the same stages with this plan_id before --apply.")
    guidance["verify"].append("Run TreeWiki validation after every applied transaction.")

    summary = {
        OverallStatus.CURRENT: "TreeWiki release and repository configuration are current.",
        OverallStatus.GUIDANCE_REQUIRED: "Some optional or remote state is unknown; read-only work may continue.",
        OverallStatus.UPGRADE_REQUIRED: "A supported TreeWiki upgrade or legacy cleanup is available.",
        OverallStatus.BLOCKED: "A compatibility or integrity error blocks mutation.",
    }[overall_status]
    repository_config_status = next(
        (
            str(component["status"])
            for component in components
            if component.get("id") == "repository_config"
        ),
        ComponentStatus.UNKNOWN.value,
    )
    return {
        "schema": STATUS_SCHEMA,
        "product": {
            "cli_release": str(embedded.release),
            "manifest_digest": target_digest,
        },
        "authority": {
            "kind": authority_kind.value,
            "availability": authority_availability.value,
            "release": str(target.release),
        },
        "repository": {
            "path": root.as_posix(),
            "config": {
                "observed_version": config_version,
                "target_version": target.config_schema.current,
                "supported_min": target.config_schema.minimum,
                "supported_max": target.config_schema.maximum,
                "status": repository_config_status,
            },
        },
        "overall": {
            "status": overall_status.value,
            "can_continue_read_only": True,
            "apply_allowed": apply_allowed,
            "plan_id": plan_id,
            "summary": summary,
        },
        "components": components,
        "actions": sorted(
            actions,
            key=lambda action: (STAGE_ORDER.index(str(action["stage"])), str(action["id"])),
        ),
        "cleanup_candidates": cleanup_candidates,
        "guidance": guidance,
        "errors": errors,
        "deletes": [],
    }


def _directory_digest(path: Path) -> str:
    if not path.is_dir():
        return "missing"
    entries: list[dict[str, str]] = []
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc":
            entries.append(
                {"path": item.relative_to(path).as_posix(), "sha256": _hash_file_or_missing(item)}
            )
    return _sha256_bytes(canonical_json(entries))


def is_repository_manager(
    config: Mapping[str, Any],
    principal: str,
    *,
    team: str | None = None,
    roles: Sequence[str] = (),
) -> bool:
    subjects = {principal, *roles}
    if team:
        subjects.add(team)
    access = config.get("access_control")
    if not isinstance(access, Mapping):
        return False
    managers = access.get("managers", [access.get("default_owner")])
    return isinstance(managers, list) and any(manager in subjects for manager in managers)


def require_repository_manager(
    repository: str | Path,
    principal: str,
    *,
    team: str | None = None,
    roles: Sequence[str] = (),
) -> None:
    root = Path(repository).resolve(strict=True)
    config = _read_yaml_mapping(root / CONFIG_PATH)
    if not is_repository_manager(config, principal, team=team, roles=roles):
        raise UpgradeException(
            UpgradeErrorCode.MANAGEMENT_DENIED,
            f"management denied for {principal}",
            component="repository_config",
        )


def _record_event(handle: Any, event: Mapping[str, Any]) -> None:
    handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _copy_payload(source: Path, target: Path) -> None:
    def ignored(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name == "__pycache__" or name.endswith(".pyc")}

    shutil.copytree(source, target, ignore=ignored)


def _atomic_replace_bytes(target: Path, content: bytes, *, prefix: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staged_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=prefix, delete=False
        ) as staged:
            staged.write(content)
            staged.flush()
            os.fsync(staged.fileno())
            staged_path = Path(staged.name)
        os.replace(staged_path, target)
        staged_path = None
        try:
            directory_fd = os.open(target.parent, os.O_RDONLY)
        except (AttributeError, OSError):
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if staged_path is not None and staged_path.exists():
            staged_path.unlink()


def _markdown_hashes(root: Path, base: Path) -> dict[str, str]:
    if not base.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): _hash_file_or_missing(path)
        for path in sorted(base.rglob("*.md"), key=lambda item: item.as_posix())
        if path.is_file()
    }


def _parse_markdown_identity(path: Path) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UpgradeException(
            UpgradeErrorCode.VERIFICATION_FAILED,
            f"cannot read applied memory document: {exc}",
            component="protected_knowledge",
            path=path.as_posix(),
        ) from exc
    if not text.startswith("---"):
        raise UpgradeException(
            UpgradeErrorCode.VERIFICATION_FAILED,
            "applied memory document has no frontmatter",
            component="protected_knowledge",
            path=path.as_posix(),
        )
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise UpgradeException(
            UpgradeErrorCode.VERIFICATION_FAILED,
            "applied memory document frontmatter is malformed",
            component="protected_knowledge",
            path=path.as_posix(),
        )
    try:
        metadata = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise UpgradeException(
            UpgradeErrorCode.VERIFICATION_FAILED,
            f"applied memory frontmatter is invalid: {exc}",
            component="protected_knowledge",
            path=path.as_posix(),
        ) from exc
    if not isinstance(metadata, Mapping):
        raise UpgradeException(
            UpgradeErrorCode.VERIFICATION_FAILED,
            "applied memory frontmatter must be a mapping",
            component="protected_knowledge",
            path=path.as_posix(),
        )
    body = parts[2]
    if body.startswith("\r\n\r\n"):
        body = body[4:]
    elif body.startswith("\n\n"):
        body = body[2:]
    elif body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    return str(metadata.get("id", "")), body


def _verify_protected_invariants(
    root: Path,
    *,
    l0_before: Mapping[str, str],
    docs_before: Mapping[str, str],
    memory_actions: Sequence[Mapping[str, Any]],
    relation_mapping: Sequence[Mapping[str, Any]],
) -> None:
    l0_after = _markdown_hashes(root, root / ".knowledge" / "private-memory" / "l0")
    if dict(l0_before) != l0_after:
        raise UpgradeException(
            UpgradeErrorCode.VERIFICATION_FAILED,
            "L0 inventory changed during upgrade",
            component="protected_knowledge",
        )
    docs_after = _markdown_hashes(root, root / "docs")
    if not memory_actions:
        if dict(docs_before) != docs_after:
            raise UpgradeException(
                UpgradeErrorCode.VERIFICATION_FAILED,
                "managed document inventory changed outside memory-layout",
                component="protected_knowledge",
            )
        return

    planned_by_relative: dict[str, Mapping[str, Any]] = {}
    for action in memory_actions:
        target = Path(str(action["target"])).resolve(strict=False)
        planned_by_relative[target.relative_to(root).as_posix()] = action
    expected_paths = set(docs_before) | set(planned_by_relative)
    if set(docs_after) != expected_paths:
        raise UpgradeException(
            UpgradeErrorCode.VERIFICATION_FAILED,
            "memory-layout changed the docs path set outside approved targets",
            component="protected_knowledge",
        )
    for relative, before_hash in docs_before.items():
        if docs_after.get(relative) != before_hash:
            raise UpgradeException(
                UpgradeErrorCode.VERIFICATION_FAILED,
                f"pre-existing managed document changed: {relative}",
                component="protected_knowledge",
            )

    policy = _load_memory_policy()
    lineage_function = getattr(policy, "lineage_equivalence_digest", None) if policy else None
    for relative, action in planned_by_relative.items():
        target = root / relative
        if docs_after.get(relative) != action["target_sha256"]:
            raise UpgradeException(
                UpgradeErrorCode.VERIFICATION_FAILED,
                f"planned memory file hash changed: {relative}",
                component="protected_knowledge",
            )
        document_id, body = _parse_markdown_identity(target)
        if document_id != str(action["memory_id"]):
            raise UpgradeException(
                UpgradeErrorCode.VERIFICATION_FAILED,
                f"planned memory ID mismatch: {relative}",
                component="protected_knowledge",
            )
        body_hash = _sha256_bytes(body.encode("utf-8"))
        if body_hash != action["body_sha256"]:
            raise UpgradeException(
                UpgradeErrorCode.VERIFICATION_FAILED,
                f"planned memory body hash mismatch: {relative}",
                component="protected_knowledge",
            )
        if not callable(lineage_function):
            raise UpgradeException(
                UpgradeErrorCode.VERIFICATION_FAILED,
                "memory lineage verifier is unavailable",
                component="protected_knowledge",
            )
        lineage = lineage_function(
            document_id, body_hash, str(action["level"]), relation_mapping
        )
        if lineage != action["lineage_digest"]:
            raise UpgradeException(
                UpgradeErrorCode.VERIFICATION_FAILED,
                f"planned memory lineage mismatch: {relative}",
                component="protected_knowledge",
            )


def _validate_repository_after_config(root: Path) -> None:
    script = Path(__file__).with_name("validate_knowledge.py")
    if not script.is_file():
        raise UpgradeException(
            UpgradeErrorCode.VERIFICATION_FAILED,
            "validate_knowledge.py is unavailable after config migration",
            component="repository_config",
        )
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(script), str(root)],
            cwd=root,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpgradeException(
            UpgradeErrorCode.VERIFICATION_FAILED,
            f"TreeWiki validation could not run: {exc}",
            component="repository_config",
        ) from exc
    if completed.returncode != 0:
        output = (completed.stdout + "\n" + completed.stderr).strip()
        raise UpgradeException(
            UpgradeErrorCode.VERIFICATION_FAILED,
            "TreeWiki validation failed after config migration: " + output[-2000:],
            component="repository_config",
        )


def _run_index_builder(
    repository: Path,
    builder: Path,
    *,
    output: Path | None = None,
    dry_run: bool = False,
) -> None:
    command = [sys.executable, "-X", "utf8", str(builder), str(repository)]
    if dry_run:
        command.append("--dry-run")
    elif output is not None:
        command.extend(("--output", str(output)))
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            command,
            cwd=repository,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpgradeException(
            UpgradeErrorCode.APPLY_FAILED,
            f"search-index builder could not run: {exc}",
            component="search_index",
        ) from exc
    if completed.returncode != 0:
        output_text = (completed.stdout + "\n" + completed.stderr).strip()
        raise UpgradeException(
            UpgradeErrorCode.APPLY_FAILED,
            "search-index builder failed: " + output_text[-2000:],
            component="search_index",
        )


def _intended_backup_path(
    action: Mapping[str, Any], backup_root: Path, transaction_id: str
) -> str:
    action_id = str(action["id"])
    target = Path(str(action["target"]))
    if action_id == "migrate_repository_config_v5":
        return (backup_root / "config.yml").as_posix()
    if action_id in {"copy_repository_treewiki_skill", "copy_global_treewiki_skill"}:
        return (target.parent / ".treewiki-backups" / transaction_id / action_id).as_posix()
    if action.get("stage") == "hook":
        hook_backup_root = (
            target.parent / "hooks" / ".treewiki-backups"
            if target.name == "hooks.json"
            else target.parent / ".treewiki-backups"
        )
        return (
            hook_backup_root
            / transaction_id
            / (action_id + target.suffix)
        ).as_posix()
    if action_id == "rebuild_search_index":
        return (backup_root / "index" / target.name).as_posix()
    return ""


def _fault(fault_injector: FaultInjector | None, phase: str, action: Mapping[str, Any]) -> None:
    if fault_injector is not None:
        fault_injector(phase, action)


def apply_upgrade(
    repository: str | Path,
    *,
    plan_id: str,
    apply: bool = False,
    principal: str | None = None,
    team: str | None = None,
    roles: Sequence[str] = (),
    skill_root: str | Path | None = None,
    source: str | Path | None = None,
    check_latest: bool = False,
    offline: bool = False,
    stages: str | Iterable[str] | None = None,
    approved_memory_ids: Sequence[str] = (),
    memory_approvals: Mapping[str, Mapping[str, Any]] | None = None,
    relation_mapping: Sequence[Mapping[str, Any]] = (),
    repository_skill_root: str | Path | None = None,
    global_skill_root: str | Path | None = None,
    approve_global_skill: bool = False,
    approve_global_hook: bool = False,
    codex_home: str | Path | None = None,
    latest_fetcher: LatestFetcher | None = None,
    fault_injector: FaultInjector | None = None,
    memory_layout_planner: MemoryLayoutPlanner | None = None,
    memory_layout_applier: MemoryLayoutApplier | None = None,
) -> dict[str, Any]:
    """Recompute a plan and optionally apply its supported actions transactionally."""
    root = Path(repository).resolve(strict=True)
    if principal is None:
        raise UpgradeException(
            UpgradeErrorCode.MANAGEMENT_DENIED,
            "upgrade requires an explicit repository principal",
            component="repository_config",
        )
    require_repository_manager(root, principal, team=team, roles=roles)
    report = diagnose_upgrade(
        root,
        skill_root=skill_root,
        source=source,
        check_latest=check_latest,
        offline=offline,
        stages=stages,
        approved_memory_ids=approved_memory_ids,
        memory_approvals=memory_approvals,
        relation_mapping=relation_mapping,
        repository_skill_root=repository_skill_root,
        global_skill_root=global_skill_root,
        approve_global_skill=approve_global_skill,
        approve_global_hook=approve_global_hook,
        codex_home=codex_home,
        latest_fetcher=latest_fetcher,
        memory_layout_planner=memory_layout_planner,
    )
    current_plan = report["overall"]["plan_id"]
    if plan_id != current_plan:
        raise UpgradeException(
            UpgradeErrorCode.STALE_PLAN,
            f"plan_id changed: expected {plan_id}, current {current_plan}",
        )
    if not apply:
        return report
    if not report["overall"]["apply_allowed"]:
        raise UpgradeException(
            UpgradeErrorCode.BLOCKED, "this plan is not allowed to mutate files"
        )

    memory_action_ids = {
        str(action["memory_id"])
        for action in report["actions"]
        if "memory_id" in action
    }
    raw_memory_plan: Mapping[str, Any] | None = None
    selected_memory_applier = memory_layout_applier
    if memory_action_ids:
        config_for_memory = _read_yaml_mapping(root / CONFIG_PATH)
        raw_memory_plan, public_memory_actions = _plan_memory_layout(
            root,
            config_for_memory,
            approved_memory_ids,
            approvals=memory_approvals,
            planner=memory_layout_planner,
        )
        if {
            str(action["memory_id"]) for action in public_memory_actions
        } != memory_action_ids:
            raise UpgradeException(
                UpgradeErrorCode.STALE_PLAN,
                "memory-layout action set changed before apply",
                component="memory_layout",
            )
        if selected_memory_applier is None:
            policy = _load_memory_policy()
            selected_memory_applier = (
                getattr(policy, "apply_memory_layout", None) if policy else None
            )
        if selected_memory_applier is None:
            raise UpgradeException(
                UpgradeErrorCode.BLOCKED,
                "memory_policy apply seam is unavailable",
                component="memory_layout",
            )

    l0_before = _markdown_hashes(root, root / ".knowledge" / "private-memory" / "l0")
    docs_before = _markdown_hashes(root, root / "docs")
    prerequisite_actions = [
        action for action in report["actions"] if action.get("kind") == "safety_prerequisite"
    ]
    prerequisite_completed: list[str] = []
    try:
        for action in prerequisite_actions:
            target = Path(str(action["target"]))
            if _hash_file_or_missing(target) != action["observed_sha256"]:
                raise UpgradeException(
                    UpgradeErrorCode.STALE_PLAN,
                    f"Git ignore prerequisite changed after plan validation: {target}",
                )
            content = str(action["target_content"]).encode("utf-8")
            if _sha256_bytes(content) != action["target_sha256"]:
                raise UpgradeException(
                    UpgradeErrorCode.STALE_PLAN,
                    f"Git ignore prerequisite target changed: {target}",
                )
            _fault(fault_injector, "prerequisite", action)
            _atomic_replace_bytes(target, content, prefix=".treewiki-ignore-")
            if _hash_file_or_missing(target) != action["target_sha256"]:
                raise UpgradeException(
                    UpgradeErrorCode.VERIFICATION_FAILED,
                    f"Git ignore prerequisite verification failed: {target}",
                )
            prerequisite_completed.append(str(action["id"]))
    except UpgradeException:
        raise
    except Exception as exc:
        raise UpgradeException(
            UpgradeErrorCode.APPLY_FAILED,
            f"Git ignore prerequisite failed before transaction creation: {exc}",
        ) from exc

    transaction_id = "upgrade-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    backup_root = root / ".knowledge" / "upgrade-backups" / transaction_id
    try:
        backup_root.mkdir(parents=True, exist_ok=False)
        record_path = backup_root / "transaction.jsonl"
        record_handle = record_path.open("a", encoding="utf-8", newline="\n")
    except OSError as exc:
        raise UpgradeException(
            UpgradeErrorCode.APPLY_FAILED,
            f"cannot create transaction backup: {exc}",
            path=backup_root.as_posix(),
        ) from exc

    completed: list[str] = []
    pending = [str(action["id"]) for action in report["actions"]]
    recovery: list[str] = []
    staged_memory: dict[str, Mapping[str, Any]] = {}
    try:
        with record_handle:
            for action in report["actions"]:
                event_base = {
                    "transaction_id": transaction_id,
                    "phase": "apply",
                    "action_id": action["id"],
                    "target": action["target"],
                    "before_sha256": action["observed_sha256"],
                    "expected_after_sha256": action["target_sha256"],
                    "backup": _intended_backup_path(action, backup_root, transaction_id),
                }
                _record_event(record_handle, {**event_base, "state": "planned"})
            for action in prerequisite_actions:
                event_base = {
                    "transaction_id": transaction_id,
                    "phase": "prerequisite",
                    "action_id": action["id"],
                    "target": action["target"],
                    "before_sha256": action["observed_sha256"],
                    "expected_after_sha256": action["target_sha256"],
                    "backup": "",
                }
                _record_event(record_handle, {**event_base, "state": "started"})
                _record_event(record_handle, {**event_base, "state": "completed"})
                completed.append(str(action["id"]))
                pending.remove(str(action["id"]))
            if raw_memory_plan is not None and selected_memory_applier is not None:
                memory_stage_root = backup_root / "memory-staging"
                memory_stage_root.mkdir(parents=True, exist_ok=False)
                try:
                    staged_results = selected_memory_applier(raw_memory_plan, memory_stage_root)
                except Exception as exc:
                    for action in report["actions"]:
                        if "memory_id" in action:
                            _record_event(
                                record_handle,
                                {
                                    "transaction_id": transaction_id,
                                    "phase": "stage",
                                    "action_id": action["id"],
                                    "state": "failed",
                                    "error": type(exc).__name__,
                                },
                            )
                    raise UpgradeException(
                        UpgradeErrorCode.APPLY_FAILED,
                        f"memory-layout staging failed: {exc}",
                        component="memory_layout",
                    ) from exc
                if not isinstance(staged_results, Sequence):
                    raise UpgradeException(
                        UpgradeErrorCode.APPLY_FAILED,
                        "memory_policy returned invalid staged results",
                        component="memory_layout",
                    )
                for staged in staged_results:
                    if not isinstance(staged, Mapping):
                        raise UpgradeException(
                            UpgradeErrorCode.APPLY_FAILED,
                            "memory_policy staged result must be a mapping",
                            component="memory_layout",
                        )
                    memory_id = str(staged.get("memory_id", ""))
                    staged_candidate = Path(str(staged.get("staged_path", "")))
                    if not staged_candidate.is_absolute():
                        staged_candidate = memory_stage_root / staged_candidate
                    staged_path = staged_candidate.resolve(strict=True)
                    try:
                        staged_path.relative_to(memory_stage_root.resolve(strict=True))
                    except ValueError as exc:
                        raise UpgradeException(
                            UpgradeErrorCode.BLOCKED,
                            "memory_policy staged a file outside transaction staging",
                            component="memory_layout",
                        ) from exc
                    expected = _normalize_sha256(
                        str(staged.get("expected_file_sha256", "")),
                        field="expected_file_sha256",
                    )
                    if _hash_file_or_missing(staged_path) != expected:
                        raise UpgradeException(
                            UpgradeErrorCode.VERIFICATION_FAILED,
                            f"staged shared memory hash mismatch for {memory_id}",
                            component="memory_layout",
                        )
                    staged_memory[memory_id] = dict(staged)
                if set(staged_memory) != memory_action_ids:
                    raise UpgradeException(
                        UpgradeErrorCode.STALE_PLAN,
                        "memory_policy staged action set differs from the approved plan",
                        component="memory_layout",
                    )
                memory_map = {
                    "transaction_id": transaction_id,
                    "plan_id": plan_id,
                    "aggregate_lineage_digest": raw_memory_plan.get(
                        "aggregate_lineage_digest", ""
                    ),
                    "actions": [
                        {
                            key: action.get(key)
                            for key in (
                                "memory_id",
                                "target",
                                "target_sha256",
                                "lineage_digest",
                                "relation_before",
                                "relation_after",
                            )
                        }
                        for action in report["actions"]
                        if "memory_id" in action
                    ],
                }
                memory_map_path = backup_root / "memory-map.json"
                with memory_map_path.open("w", encoding="utf-8", newline="\n") as handle:
                    json.dump(memory_map, handle, ensure_ascii=False, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            for action in report["actions"]:
                if str(action["id"]) in prerequisite_completed:
                    continue
                event_base = {
                    "transaction_id": transaction_id,
                    "phase": "apply",
                    "action_id": action["id"],
                    "target": action["target"],
                    "before_sha256": action["observed_sha256"],
                    "expected_after_sha256": action["target_sha256"],
                    "backup": _intended_backup_path(action, backup_root, transaction_id),
                }
                _record_event(record_handle, {**event_base, "state": "started"})
                try:
                    _fault(fault_injector, "started", action)
                    if "memory_id" in action:
                        memory_id = str(action["memory_id"])
                        staged = staged_memory[memory_id]
                        staged_candidate = Path(str(staged["staged_path"]))
                        if not staged_candidate.is_absolute():
                            staged_candidate = memory_stage_root / staged_candidate
                        staged_path = staged_candidate.resolve(strict=True)
                        target = Path(str(action["target"]))
                        if _hash_file_or_missing(target) != action["observed_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.STALE_PLAN,
                                f"shared memory target changed for {memory_id}",
                                component="memory_layout",
                            )
                        if target.exists():
                            raise UpgradeException(
                                UpgradeErrorCode.MEMORY_TARGET_CONFLICT,
                                f"shared memory target appeared for {memory_id}",
                                component="memory_layout",
                            )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        expected_hex = str(action["target_sha256"]).removeprefix("sha256:")
                        quoted_target = str(target).replace("'", "''")
                        recovery.append(
                            "if ((Get-FileHash -Algorithm SHA256 -LiteralPath "
                            f"'{quoted_target}').Hash.ToLower() -eq '{expected_hex}') "
                            f"{{ Remove-Item -LiteralPath '{quoted_target}' }}"
                        )
                        _record_event(record_handle, {**event_base, "state": "backup_ready"})
                        _fault(fault_injector, "stage", action)
                        _fault(fault_injector, "replace", action)
                        os.replace(staged_path, target)
                        if _hash_file_or_missing(target) != action["target_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.VERIFICATION_FAILED,
                                f"shared memory target verification failed for {memory_id}",
                                component="memory_layout",
                            )
                    elif action["id"] == "migrate_repository_config_v5":
                        target = Path(str(action["target"]))
                        if _hash_file_or_missing(target) != action["observed_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.STALE_PLAN,
                                "config changed after plan validation",
                            )
                        current = _read_yaml_mapping(target)
                        target_config = migrate_config_v5(current)
                        target_bytes = _yaml_bytes(target_config)
                        if _sha256_bytes(target_bytes) != action["target_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.STALE_PLAN,
                                "config target changed during apply",
                        )
                        backup = backup_root / "config.yml"
                        _fault(fault_injector, "backup", action)
                        shutil.copy2(target, backup)
                        event_base["backup"] = backup.as_posix()
                        expected_hex = str(action["target_sha256"]).removeprefix("sha256:")
                        quoted_target = str(target).replace("'", "''")
                        quoted_backup = str(backup).replace("'", "''")
                        recovery.append(
                            "if ((Get-FileHash -Algorithm SHA256 -LiteralPath "
                            f"'{quoted_target}').Hash.ToLower() -eq '{expected_hex}') "
                            f"{{ Copy-Item -LiteralPath '{quoted_backup}' -Destination "
                            f"'{quoted_target}' -Force }}"
                        )
                        _record_event(record_handle, {**event_base, "state": "backup_ready"})
                        _fault(fault_injector, "replace", action)
                        _atomic_replace_bytes(target, target_bytes, prefix=".treewiki-config-")
                    elif action["id"] in {
                        "copy_repository_treewiki_skill",
                        "copy_global_treewiki_skill",
                    }:
                        source_root = Path(str(action["source"])).resolve(strict=True)
                        target = Path(str(action["target"]))
                        if _directory_digest(target) != action["observed_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.STALE_PLAN,
                                f"skill target changed after plan validation: {target}",
                            )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        staged_path = Path(
                            tempfile.mkdtemp(prefix=".treewiki-stage-", dir=target.parent)
                        )
                        shutil.rmtree(staged_path)
                        _copy_payload(source_root, staged_path)
                        staged_manifest = load_manifest(staged_path / MANIFEST_FILENAME)
                        staged_problems = verify_payload(
                            staged_manifest, staged_path, require_complete=True
                        )
                        if staged_problems or _directory_digest(staged_path) != action["target_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.VERIFICATION_FAILED,
                                "staged skill payload failed manifest verification",
                                component=str(action["id"]),
                            )
                        _fault(fault_injector, "stage", action)
                        action_backup_root = (
                            target.parent / ".treewiki-backups" / transaction_id
                        )
                        action_backup_root.mkdir(parents=True, exist_ok=True)
                        backup = action_backup_root / str(action["id"])
                        if target.exists():
                            _fault(fault_injector, "backup", action)
                            shutil.move(str(target), str(backup))
                            recovery.append(
                                f"Move-Item -LiteralPath '{backup}' -Destination '{target}'"
                            )
                        else:
                            quoted_target = str(target).replace("'", "''")
                            recovery.append(
                                f"Remove-Item -Recurse -LiteralPath '{quoted_target}'"
                            )
                        event_base["backup"] = backup.as_posix() if backup.exists() else ""
                        _record_event(record_handle, {**event_base, "state": "backup_ready"})
                        _fault(fault_injector, "replace", action)
                        os.replace(staged_path, target)
                        if _directory_digest(target) != action["target_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.VERIFICATION_FAILED,
                                f"installed skill payload failed verification: {target}",
                                component=str(action["id"]),
                            )
                    elif action["id"] == "rebuild_search_index":
                        target = Path(str(action["target"]))
                        builder = Path(str(action["source"])).resolve(strict=True)
                        if _hash_file_or_missing(target) != action["observed_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.STALE_PLAN,
                                "search index changed after plan validation",
                                component="search_index",
                            )
                        if _hash_file_or_missing(builder) != action["source_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.STALE_PLAN,
                                "search-index builder changed after plan validation",
                                component="search_index",
                            )
                        current_config = _read_yaml_mapping(root / CONFIG_PATH)
                        expected_contract = _expected_index_contract(
                            root,
                            current_config,
                            builder_sha256=str(action["source_sha256"]),
                        )
                        if _index_contract_digest(expected_contract) != action["target_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.STALE_PLAN,
                                "search-index contract or corpus changed after plan validation",
                                component="search_index",
                            )
                        if expected_contract != action.get("expected_contract"):
                            raise UpgradeException(
                                UpgradeErrorCode.STALE_PLAN,
                                "planned search-index contract changed before apply",
                                component="search_index",
                            )
                        try:
                            _validate_repository_after_config(root)
                        except Exception as exc:
                            error_code = (
                                exc.code.value
                                if isinstance(exc, UpgradeException)
                                else UpgradeErrorCode.VERIFICATION_FAILED.value
                            )
                            _record_event(
                                record_handle,
                                {
                                    "transaction_id": transaction_id,
                                    "phase": "verify",
                                    "action_id": "pre_index_repository_validation",
                                    "state": "failed",
                                    "error_code": error_code,
                                    "error_type": type(exc).__name__,
                                    "recovery": list(recovery),
                                },
                            )
                            if isinstance(exc, UpgradeException):
                                raise
                            raise UpgradeException(
                                UpgradeErrorCode.VERIFICATION_FAILED,
                                f"repository validation failed before index rebuild: {exc}",
                                component="search_index",
                                recovery=recovery,
                            ) from exc
                        _fault(fault_injector, "dry_run", action)
                        _run_index_builder(root, builder, dry_run=True)
                        staging_root = backup_root / "index-staging"
                        staging_root.mkdir(parents=True, exist_ok=True)
                        staged_path = staging_root / target.name
                        _fault(fault_injector, "stage", action)
                        _run_index_builder(root, builder, output=staged_path)
                        if _read_index_contract(staged_path) != expected_contract:
                            raise UpgradeException(
                                UpgradeErrorCode.VERIFICATION_FAILED,
                                "staged search index does not match the planned contract",
                                component="search_index",
                            )
                        backup = Path(
                            _intended_backup_path(action, backup_root, transaction_id)
                        )
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists():
                            _fault(fault_injector, "backup", action)
                            shutil.copy2(target, backup)
                            quoted_backup = str(backup).replace("'", "''")
                            quoted_target = str(target).replace("'", "''")
                            recovery.append(
                                f"Copy-Item -LiteralPath '{quoted_backup}' -Destination '{quoted_target}' -Force"
                            )
                            event_base["backup"] = backup.as_posix()
                        else:
                            quoted_target = str(target).replace("'", "''")
                            recovery.append(f"Remove-Item -LiteralPath '{quoted_target}'")
                            event_base["backup"] = ""
                        _record_event(record_handle, {**event_base, "state": "backup_ready"})
                        target.parent.mkdir(parents=True, exist_ok=True)
                        _fault(fault_injector, "replace", action)
                        os.replace(staged_path, target)
                        if _read_index_contract(target) != expected_contract:
                            raise UpgradeException(
                                UpgradeErrorCode.VERIFICATION_FAILED,
                                "applied search index does not match the planned contract",
                                component="search_index",
                            )
                    elif action.get("stage") == "hook":
                        target = Path(str(action["target"]))
                        if _hash_file_or_missing(target) != action["observed_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.STALE_PLAN,
                                f"hook target changed after plan validation: {target}",
                                component="codex_hook",
                            )
                        source_path: Path | None = None
                        if "source" in action:
                            source_path = Path(str(action["source"])).resolve(strict=True)
                            if _hash_file_or_missing(source_path) != action.get("source_sha256"):
                                raise UpgradeException(
                                    UpgradeErrorCode.STALE_PLAN,
                                    f"hook source changed after plan validation: {source_path}",
                                    component="codex_hook",
                                )
                        if "target_content" in action:
                            target_bytes = str(action["target_content"]).encode("utf-8")
                        elif source_path is not None:
                            target_bytes = source_path.read_bytes()
                        else:  # pragma: no cover - guarded by the planner
                            raise UpgradeException(
                                UpgradeErrorCode.APPLY_FAILED,
                                f"hook action has no source content: {action['id']}",
                            )
                        if _sha256_bytes(target_bytes) != action["target_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.STALE_PLAN,
                                f"hook target content changed: {target}",
                                component="codex_hook",
                            )
                        backup = Path(_intended_backup_path(action, backup_root, transaction_id))
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists():
                            _fault(fault_injector, "backup", action)
                            shutil.copy2(target, backup)
                            quoted_backup = str(backup).replace("'", "''")
                            quoted_target = str(target).replace("'", "''")
                            recovery.append(
                                f"Copy-Item -LiteralPath '{quoted_backup}' -Destination '{quoted_target}' -Force"
                            )
                            event_base["backup"] = backup.as_posix()
                        else:
                            quoted_target = str(target).replace("'", "''")
                            recovery.append(f"Remove-Item -LiteralPath '{quoted_target}'")
                            event_base["backup"] = ""
                        _record_event(record_handle, {**event_base, "state": "backup_ready"})
                        _fault(fault_injector, "replace", action)
                        _atomic_replace_bytes(target, target_bytes, prefix=".treewiki-hook-")
                        if _hash_file_or_missing(target) != action["target_sha256"]:
                            raise UpgradeException(
                                UpgradeErrorCode.VERIFICATION_FAILED,
                                f"hook target verification failed: {target}",
                                component="codex_hook",
                            )
                    else:
                        raise UpgradeException(
                            UpgradeErrorCode.APPLY_FAILED,
                            f"unsupported action: {action['id']}",
                        )
                    _fault(fault_injector, "completed", action)
                    _record_event(record_handle, {**event_base, "state": "completed"})
                    completed.append(str(action["id"]))
                    pending.remove(str(action["id"]))
                except Exception as exc:
                    _record_event(
                        record_handle,
                        {**event_base, "state": "failed", "error": type(exc).__name__},
                    )
                    if isinstance(exc, UpgradeException):
                        raise
                    raise UpgradeException(
                        UpgradeErrorCode.APPLY_FAILED,
                        f"action {action['id']} failed: {exc}",
                        recovery=recovery,
                    ) from exc

            verification_action_id = "post_apply_verification"
            try:
                for action in report["actions"]:
                    if str(action["id"]) in completed:
                        verification_action_id = str(action["id"])
                        _fault(fault_injector, "verify", action)
                verification_action_id = "protected_knowledge"
                _verify_protected_invariants(
                    root,
                    l0_before=l0_before,
                    docs_before=docs_before,
                    memory_actions=[
                        action for action in report["actions"] if "memory_id" in action
                    ],
                    relation_mapping=relation_mapping,
                )
                if "migrate_repository_config_v5" in completed:
                    verification_action_id = "repository_validation"
                    _validate_repository_after_config(root)
                verification_action_id = "upgrade_rediagnosis"
                verified = diagnose_upgrade(
                    root,
                    skill_root=skill_root,
                    source=source,
                    check_latest=check_latest,
                    offline=offline,
                    stages=stages,
                    approved_memory_ids=approved_memory_ids,
                    memory_approvals=memory_approvals,
                    relation_mapping=relation_mapping,
                    repository_skill_root=repository_skill_root,
                    global_skill_root=global_skill_root,
                    approve_global_skill=approve_global_skill,
                    approve_global_hook=approve_global_hook,
                    codex_home=codex_home,
                    latest_fetcher=latest_fetcher,
                    memory_layout_planner=memory_layout_planner,
                )
                remaining_ids = {str(action["id"]) for action in verified["actions"]}
                failed_ids = sorted(set(completed) & remaining_ids)
                if failed_ids:
                    verification_action_id = ",".join(failed_ids)
                    raise UpgradeException(
                        UpgradeErrorCode.VERIFICATION_FAILED,
                        "verification still requires applied actions: "
                        + ", ".join(failed_ids),
                        recovery=recovery,
                    )
                for action_id in completed:
                    _record_event(
                        record_handle,
                        {
                            "transaction_id": transaction_id,
                            "phase": "verify",
                            "action_id": action_id,
                            "state": "verified",
                        },
                    )
            except Exception as exc:
                error_code = (
                    exc.code.value
                    if isinstance(exc, UpgradeException)
                    else UpgradeErrorCode.VERIFICATION_FAILED.value
                )
                _record_event(
                    record_handle,
                    {
                        "transaction_id": transaction_id,
                        "phase": "verify",
                        "action_id": verification_action_id,
                        "state": "failed",
                        "error_code": error_code,
                        "error_type": type(exc).__name__,
                        "recovery": list(recovery),
                    },
                )
                if isinstance(exc, UpgradeException):
                    raise
                raise UpgradeException(
                    UpgradeErrorCode.VERIFICATION_FAILED,
                    f"post-apply verification failed: {exc}",
                    recovery=recovery,
                ) from exc
    except UpgradeException:
        raise
    except OSError as exc:
        raise UpgradeException(
            UpgradeErrorCode.APPLY_FAILED,
            f"transaction failed: {exc}",
            recovery=recovery,
        ) from exc

    return {
        "schema": "treewiki.upgrade-result/v1",
        "status": UpgradeErrorCode.APPLIED.value,
        "transaction_id": transaction_id,
        "plan_id": plan_id,
        "completed_actions": completed,
        "pending_actions": pending,
        "backup_path": backup_root.as_posix(),
        "recovery": recovery,
        "deletes": [],
    }


def exit_code_for_report(report: Mapping[str, Any]) -> int:
    status = str(report.get("overall", {}).get("status", ""))
    if status == OverallStatus.CURRENT.value:
        return int(UpgradeExitCode.SUCCESS)
    if status in {OverallStatus.GUIDANCE_REQUIRED.value, OverallStatus.UPGRADE_REQUIRED.value}:
        return int(UpgradeExitCode.DIAGNOSTIC)
    return int(UpgradeExitCode.BLOCKED)


def exit_code_for_exception(exc: UpgradeException) -> int:
    if exc.code in {UpgradeErrorCode.INVALID_INPUT, UpgradeErrorCode.MANAGEMENT_DENIED}:
        return int(UpgradeExitCode.INVALID_INPUT)
    if exc.code in {UpgradeErrorCode.SOURCE_INVALID, UpgradeErrorCode.IO_FAILURE}:
        return int(UpgradeExitCode.SOURCE_FAILURE)
    if exc.code == UpgradeErrorCode.STALE_PLAN:
        return int(UpgradeExitCode.STALE_PLAN)
    if exc.code == UpgradeErrorCode.APPLY_FAILED:
        return int(UpgradeExitCode.APPLY_FAILED)
    if exc.code == UpgradeErrorCode.VERIFICATION_FAILED:
        return int(UpgradeExitCode.VERIFICATION_FAILED)
    if exc.code in {
        UpgradeErrorCode.INCOMPATIBLE_NEWER,
        UpgradeErrorCode.BLOCKED,
        UpgradeErrorCode.MEMORY_TARGET_CONFLICT,
        UpgradeErrorCode.LEGACY_MEMORY_HOOK,
    }:
        return int(UpgradeExitCode.BLOCKED)
    return int(UpgradeExitCode.SUCCESS)


# Public integration names used by knowledge_cli.py.
upgrade_status = diagnose_upgrade
upgrade = apply_upgrade
