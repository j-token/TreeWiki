#!/usr/bin/env python
"""Transition registered LMWiki Codex hooks to the TreeWiki runner."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR PyYAML is required; install scripts/requirements.txt", file=sys.stderr)
    raise SystemExit(2)


EVENTS = {
    "SessionStart": (10, "TreeWiki 상태 확인"),
    "UserPromptSubmit": (10, "TreeWiki 작업 준비"),
    "Stop": (30, "TreeWiki 완료 상태 확인"),
    "SessionEnd": (3, "TreeWiki 세션 상태 기록"),
}
CANONICAL_MARKER = "treewiki_hook.py"
LEGACY_MARKER = "lmwiki_hook.py"
OWNED_MARKERS = (CANONICAL_MARKER, LEGACY_MARKER)
SETTINGS_SCHEMA = "treewiki.hook-settings/v1"
LEGACY_REMOVAL_RELEASE = "0.2.0"
CONFIG_VERSION = 5
MEMORY_LAYOUT_VERSION = 2


def handler(
    runner: Path,
    timeout: int,
    status_message: str,
) -> dict[str, Any]:
    windows_path = str(runner)
    portable_path = runner.as_posix()
    return {
        "type": "command",
        "command": f'python -X utf8 "{portable_path}"',
        "commandWindows": f'python -X utf8 "{windows_path}"',
        "timeout": timeout,
        "statusMessage": status_message,
    }


def _command_text(value: dict[str, Any]) -> str:
    return "\n".join(
        str(value.get(key, "")) for key in ("command", "commandWindows")
    )


def owned_marker(value: dict[str, Any]) -> str | None:
    command = _command_text(value)
    for marker in OWNED_MARKERS:
        if marker in command:
            return marker
    return None


def validate_hooks(payload: dict[str, Any]) -> None:
    hooks = payload.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("global hooks.json field 'hooks' must be an object")
    for event, groups in hooks.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            raise ValueError(f"global hooks.json event {event!r} must be an array")
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError(
                    f"global hooks.json event {event} group {group_index} must contain a hooks array"
                )
            for hook_index, value in enumerate(group["hooks"]):
                if not isinstance(value, dict):
                    raise ValueError(
                        f"global hooks.json event {event} hook {hook_index} must be an object"
                    )
                if value.get("type") == "command" and not any(
                    isinstance(value.get(key), str) and value.get(key)
                    for key in ("command", "commandWindows")
                ):
                    raise ValueError(
                        f"global hooks.json event {event} command hook {hook_index} has no command"
                    )


def transition_hooks(
    payload: dict[str, Any], runner: Path
) -> tuple[int, int]:
    """Collapse owned old/new handlers to one canonical handler per existing event."""
    validate_hooks(payload)
    hooks = payload.setdefault("hooks", {})
    owned_count = 0
    legacy_count = 0
    for event, groups in hooks.items():
        first_location: tuple[dict[str, Any], int, dict[str, Any]] | None = None
        for group in groups:
            retained: list[dict[str, Any]] = []
            for value in group["hooks"]:
                marker = owned_marker(value)
                if marker is None:
                    retained.append(value)
                    continue
                if first_location is None:
                    first_location = (group, len(retained), value)
                owned_count += 1
                legacy_count += marker == LEGACY_MARKER
            group["hooks"] = retained

        if first_location is None:
            continue
        group, index, previous = first_location
        default_timeout, default_message = EVENTS.get(
            event,
            (
                int(previous.get("timeout", 10)),
                str(previous.get("statusMessage", "TreeWiki hook")),
            ),
        )
        group["hooks"].insert(
            index,
            handler(runner.resolve(), default_timeout, default_message),
        )
    return owned_count, legacy_count


def merge_hook(payload: dict[str, Any], event: str, value: dict[str, Any]) -> None:
    """Compatibility helper: replace owned handlers without enabling a missing event."""
    validate_hooks(payload)
    hooks = payload.setdefault("hooks", {})
    groups = hooks.get(event)
    if groups is None:
        return
    first_location: tuple[dict[str, Any], int] | None = None
    for group in groups:
        retained: list[dict[str, Any]] = []
        for existing in group["hooks"]:
            if owned_marker(existing) is None:
                retained.append(existing)
            elif first_location is None:
                first_location = (group, len(retained))
        group["hooks"] = retained
    if first_location is not None:
        group, index = first_location
        group["hooks"].insert(index, value)


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _validated_fallback(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} fallback_repository must be a non-empty string")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} fallback_repository must be an absolute path: {value}")
    resolved = path.resolve()
    if not (resolved / ".knowledge" / "config.yml").is_file():
        raise ValueError(f"{label} fallback repository is not initialized: {resolved}")
    return resolved


def _load_settings_source(
    canonical_path: Path,
    legacy_path: Path,
) -> tuple[Path | None, Path | None, bool]:
    """Return fallback, migration source, and whether a legacy source was used."""
    if canonical_path.exists():
        payload = _read_object(canonical_path, "TreeWiki hook settings")
        if payload.get("schema") != SETTINGS_SCHEMA:
            raise ValueError(
                f"TreeWiki hook settings schema must be {SETTINGS_SCHEMA!r}"
            )
        fallback = _validated_fallback(
            payload.get("fallback_repository"), "TreeWiki hook settings"
        )
        return fallback, canonical_path, False
    if legacy_path.exists():
        payload = _read_object(legacy_path, "legacy LMWiki hook settings")
        if set(payload) != {"fallback_repository"}:
            raise ValueError(
                "legacy LMWiki hook settings may contain only fallback_repository"
            )
        fallback = _validated_fallback(
            payload.get("fallback_repository"), "legacy LMWiki hook settings"
        )
        return fallback, legacy_path, True
    return None, None, False


def _backup_once(path: Path) -> Path | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    backup = path.with_suffix(path.suffix + ".treewiki-backup")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def _temporary_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".treewiki-tmp")


def _write_atomic(path: Path, content: str) -> None:
    temporary = _temporary_path(path)
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _copy_atomic(source: Path, target: Path) -> None:
    temporary = _temporary_path(target)
    try:
        shutil.copy2(source, temporary)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _authorized_repository(
    repository: Path,
    principal: str,
    team: str,
) -> Path:
    """Validate the repository contract and caller before any global mutation."""
    if not principal.startswith("user:") or len(principal) == len("user:"):
        raise ValueError("principal must use user:<id> syntax")
    if not team.startswith("team:") or len(team) == len("team:"):
        raise ValueError("team must use team:<id> syntax")

    root = repository.resolve()
    config_path = root / ".knowledge" / "config.yml"
    if not root.is_dir() or not config_path.is_file():
        raise ValueError(f"repository is not initialized: {root}")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"repository config is not valid YAML: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("repository config must contain a mapping")
    if config.get("version") != CONFIG_VERSION:
        raise ValueError(
            f"standalone hook transition requires config version {CONFIG_VERSION}"
        )
    memory = config.get("memory")
    if not isinstance(memory, dict):
        raise ValueError("config v5 must contain a memory mapping")
    if memory.get("layout_version") != MEMORY_LAYOUT_VERSION:
        raise ValueError(
            "standalone hook transition requires memory.layout_version 2"
        )
    if memory.get("capture") != "explicit":
        raise ValueError(
            "standalone hook transition requires memory.capture: explicit"
        )
    access = config.get("access_control")
    managers = access.get("managers") if isinstance(access, dict) else None
    subjects = {principal, team}
    if not isinstance(managers, list) or not any(
        isinstance(manager, str) and manager in subjects for manager in managers
    ):
        raise ValueError(f"management denied for {principal} in {root}")
    return root


def install(
    codex_home: Path,
    dry_run: bool = False,
    fallback_repository: Path | None = None,
) -> tuple[Path, Path]:
    source_runner = Path(__file__).with_name(CANONICAL_MARKER)
    if not source_runner.is_file():
        raise ValueError(f"TreeWiki runner not found: {source_runner}")

    hooks_path = codex_home / "hooks.json"
    runner_path = codex_home / "hooks" / CANONICAL_MARKER
    settings_path = codex_home / "hooks" / "treewiki-global.json"
    legacy_settings_path = codex_home / "hooks" / "lmwiki-global.json"

    if fallback_repository is not None:
        fallback_repository = _validated_fallback(
            str(fallback_repository.resolve()), "requested"
        )

    if hooks_path.exists():
        payload = _read_object(hooks_path, "global hooks.json")
    else:
        payload = {"hooks": {}}
    owned_count, legacy_count = transition_hooks(payload, runner_path)

    # A name transition must not activate hooks where no owned handler was registered.
    if owned_count == 0:
        return hooks_path, runner_path

    settings_fallback, settings_source, legacy_settings = _load_settings_source(
        settings_path, legacy_settings_path
    )
    desired_fallback = fallback_repository or settings_fallback
    if legacy_count or legacy_settings:
        print(
            "WARNING legacy LMWiki hook registration detected; migrated to TreeWiki. "
            f"The LMWiki compatibility entry point is removed in {LEGACY_REMOVAL_RELEASE}.",
            file=sys.stderr,
        )

    if dry_run:
        return hooks_path, runner_path

    codex_home.mkdir(parents=True, exist_ok=True)
    runner_path.parent.mkdir(parents=True, exist_ok=True)

    hooks_content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    settings_content = None
    if desired_fallback is not None:
        settings_content = (
            json.dumps(
                {
                    "schema": SETTINGS_SCHEMA,
                    "fallback_repository": str(desired_fallback),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )

    _backup_once(hooks_path)
    _backup_once(runner_path)
    if legacy_settings and settings_source is not None:
        _backup_once(settings_source)
    elif settings_path.exists():
        _backup_once(settings_path)

    _copy_atomic(source_runner, runner_path)
    if settings_content is not None:
        _write_atomic(settings_path, settings_content)
    _write_atomic(hooks_path, hooks_content)
    return hooks_path, runner_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--team", required=True)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--fallback-repository", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--approve-global-hook-apply", action="store_true")
    args = parser.parse_args()
    try:
        repository = _authorized_repository(
            args.repository,
            args.principal,
            args.team,
        )
        if args.fallback_repository is not None:
            requested_fallback = args.fallback_repository.resolve()
            if requested_fallback != repository:
                raise ValueError(
                    "--fallback-repository must match the authorized --repository"
                )
        if args.apply and not args.approve_global_hook_apply:
            raise ValueError(
                "global hook mutation requires --approve-global-hook-apply"
            )
        hooks_path, runner_path = install(
            args.codex_home.resolve(),
            dry_run=not args.apply,
            fallback_repository=repository,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR global TreeWiki hook transition failed: {exc}", file=sys.stderr)
        return 1
    result_mode = "TRANSITIONED" if args.apply else "DRY-RUN"
    print(f"{result_mode} {hooks_path}")
    print(f"{result_mode} {runner_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
