from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


ALIAS_PLAN_SCHEMA = "treewiki.claude-alias-plan/v1"
SUPPORTED_SCOPES = {"user", "project"}
EXPECTED_PLUGIN_VERSION = "0.2.0"


class ClaudeAliasError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _plugin_version(plugin_root: Path) -> str:
    manifest = plugin_root / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClaudeAliasError("PLUGIN_NOT_FOUND", f"Claude plugin manifest is unavailable: {manifest}") from exc
    if not isinstance(data, Mapping) or data.get("name") != "treewiki":
        raise ClaudeAliasError("PLUGIN_INVALID", "Claude plugin manifest must use name treewiki")
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ClaudeAliasError("PLUGIN_INVALID", "Claude plugin manifest requires a version")
    if version != EXPECTED_PLUGIN_VERSION:
        raise ClaudeAliasError(
            "PLUGIN_VERSION_MISMATCH",
            "Install or upgrade the TreeWiki Claude plugin to "
            f"{EXPECTED_PLUGIN_VERSION} before installing /treewiki (found {version})",
        )
    return version


def alias_target(repository: Path, scope: str) -> Path:
    if scope not in SUPPORTED_SCOPES:
        raise ClaudeAliasError("SCOPE_REQUIRED", "scope must be user or project")
    if scope == "project":
        return repository.resolve() / ".claude" / "skills" / "treewiki" / "SKILL.md"
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(configured).expanduser() if configured else Path.home() / ".claude"
    return base.resolve() / "skills" / "treewiki" / "SKILL.md"


def shadow_status(repository: Path) -> dict[str, Any]:
    user = alias_target(repository, "user")
    project = alias_target(repository, "project")
    return {
        "user": user.as_posix(),
        "project": project.as_posix(),
        "user_exists": user.is_file(),
        "project_exists": project.is_file(),
        "warning": "ALIAS_SHADOWED" if user.is_file() and project.is_file() else None,
    }


def plan_alias(
    repository: Path,
    *,
    scope: str,
    plugin_root: Path,
    alias_source: Path,
) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    version = _plugin_version(plugin_root.resolve(strict=True))
    try:
        template = alias_source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ClaudeAliasError("ALIAS_SOURCE_MISSING", f"alias source is unavailable: {alias_source}") from exc
    rendered = template.replace("{{TREEWIKI_PLUGIN_VERSION}}", version)
    target = alias_target(repository, scope)
    before = _digest(target.read_bytes()) if target.is_file() else "missing"
    after = _digest(rendered.encode("utf-8"))
    state = "current" if before == after else "install" if before == "missing" else "update"
    public = {
        "schema": ALIAS_PLAN_SCHEMA,
        "scope": scope,
        "target": target.as_posix(),
        "plugin_root": plugin_root.resolve().as_posix(),
        "plugin_version": version,
        "before_sha256": before,
        "target_sha256": after,
        "state": state,
        "shadow": shadow_status(repository),
    }
    plan_id = "sha256:" + hashlib.sha256(
        json.dumps(public, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**public, "plan_id": plan_id, "_rendered": rendered}


def apply_alias(plan: Mapping[str, Any], *, plan_id: str) -> dict[str, Any]:
    if plan_id != plan.get("plan_id"):
        raise ClaudeAliasError("STALE_PLAN", "Claude alias plan ID changed")
    target = Path(str(plan["target"]))
    observed = _digest(target.read_bytes()) if target.is_file() else "missing"
    if observed != plan.get("before_sha256"):
        raise ClaudeAliasError("STALE_PLAN", "Claude alias target changed")
    if plan.get("state") == "current":
        return {**{key: value for key, value in plan.items() if not key.startswith("_")}, "status": "CURRENT"}
    target.parent.mkdir(parents=True, exist_ok=True)
    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=".treewiki-alias-",
            delete=False,
        ) as handle:
            handle.write(str(plan["_rendered"]))
            handle.flush()
            os.fsync(handle.fileno())
            staged = Path(handle.name)
        os.replace(staged, target)
        staged = None
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    if _digest(target.read_bytes()) != plan.get("target_sha256"):
        raise ClaudeAliasError("VERIFY_FAILED", "Claude alias verification failed")
    return {
        **{key: value for key, value in plan.items() if not key.startswith("_")},
        "status": "APPLIED",
    }
