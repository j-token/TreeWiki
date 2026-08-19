#!/usr/bin/env python
"""TreeWiki Codex hook runner with one-release legacy settings support."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR PyYAML is required; install scripts/requirements.txt", file=sys.stderr)
    raise SystemExit(2)


DEFAULT_HOOKS: dict[str, Any] = {
    "enabled": False,
    "execution": "same_thread",
    "memory_stages": ["l0", "l1", "l2"],
    "l3": {"enabled": True, "minimum_sources": 2},
    "runbook": {
        "enabled": True,
        "require_user_confirmation": True,
        "status": "draft",
    },
}

SETTINGS_SCHEMA = "treewiki.hook-settings/v1"
LEGACY_REMOVAL_RELEASE = "0.2.0"


def merge_missing(target: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    merged = dict(target)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
        elif isinstance(value, dict) and isinstance(merged[key], dict):
            merged[key] = merge_missing(merged[key], value)
    return merged


def find_repository(start: str | Path, fallback: str | Path | None = None) -> Path | None:
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".knowledge" / "config.yml").is_file():
            return candidate
    if fallback is not None:
        fallback_path = Path(fallback).resolve()
        if (fallback_path / ".knowledge" / "config.yml").is_file():
            return fallback_path
    return None


def _fallback_from_settings(path: Path, *, legacy: bool) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid hook settings JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"hook settings must contain a JSON object: {path}")
    if legacy:
        if set(payload) != {"fallback_repository"}:
            raise ValueError(
                "legacy LMWiki hook settings may contain only fallback_repository"
            )
    elif payload.get("schema") != SETTINGS_SCHEMA:
        raise ValueError(
            f"TreeWiki hook settings schema must be {SETTINGS_SCHEMA!r}: {path}"
        )
    value = payload.get("fallback_repository")
    if not isinstance(value, str) or not value:
        raise ValueError(f"fallback_repository must be a non-empty string: {path}")
    fallback = Path(value)
    if not fallback.is_absolute():
        raise ValueError(f"fallback_repository must be absolute: {path}")
    resolved = fallback.resolve()
    if not (resolved / ".knowledge" / "config.yml").is_file():
        raise ValueError(f"fallback repository is not initialized: {resolved}")
    return str(resolved)


def global_fallback_repository(settings_directory: Path | None = None) -> str | None:
    directory = settings_directory or Path(__file__).parent
    canonical = directory / "treewiki-global.json"
    legacy = directory / "lmwiki-global.json"
    if canonical.exists():
        return _fallback_from_settings(canonical, legacy=False)
    if legacy.exists():
        print(
            "WARNING legacy LMWiki hook settings are supported for one release; "
            f"migrate to treewiki-global.json before {LEGACY_REMOVAL_RELEASE}.",
            file=sys.stderr,
        )
        return _fallback_from_settings(legacy, legacy=True)
    return None


def load_config(root: Path) -> dict[str, Any]:
    with (root / ".knowledge" / "config.yml").open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise ValueError(".knowledge/config.yml must contain a mapping")
    hooks = config.get("hooks") if isinstance(config.get("hooks"), dict) else {}
    config["hooks"] = merge_missing(hooks, DEFAULT_HOOKS)
    return config


def legacy_memory_hook_detected(config: dict[str, Any]) -> bool:
    memory = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    return memory.get("capture") == "hook"


def safe_key(value: str) -> str:
    prefix = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")[:48] or "session"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def state_path(root: Path, session_id: str) -> Path:
    return root / ".knowledge" / "hooks" / "state" / f"{safe_key(session_id)}.json"


def load_state(root: Path, session_id: str) -> dict[str, Any]:
    path = state_path(root, session_id)
    if not path.exists():
        return {"session_id": session_id, "turns": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"session_id": session_id, "turns": {}}
    return value if isinstance(value, dict) else {"session_id": session_id, "turns": {}}


def save_state(root: Path, session_id: str, state: dict[str, Any]) -> None:
    path = state_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def turn_state(state: dict[str, Any], turn_id: str) -> dict[str, Any]:
    turns = state.setdefault("turns", {})
    if not isinstance(turns, dict):
        turns = {}
        state["turns"] = turns
    value = turns.setdefault(turn_id, {"emitted": [], "skipped": []})
    if not isinstance(value, dict):
        value = {"emitted": [], "skipped": []}
        turns[turn_id] = value
    return value


def continuation(reason: str) -> dict[str, Any]:
    return {"decision": "block", "reason": reason}


def additional_context(event: str, context: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        }
    }


def execution_instruction(hooks: dict[str, Any]) -> str:
    if hooks.get("execution") == "agent":
        return (
            "가능하면 이 후처리만 독립 에이전트에 위임하고 결과를 현재 스레드에서 검증하세요. "
            "에이전트 실행을 지원하지 않으면 현재 스레드에서 수행하세요."
        )
    return "현재 스레드에서 수행하세요."


def runbook_proposal_prompt(root: Path, hooks: dict[str, Any]) -> str:
    status = str(hooks.get("runbook", {}).get("status", "draft"))
    return (
        "[TreeWiki lifecycle hook: runbook proposal review]\n"
        f"저장소: {root}\n{execution_instruction(hooks)}\n"
        "최초 완료 메시지, 사용자 요청, 도구 결과와 변경 파일을 보고 인수인계 경계 신호가 있는지 판단하세요. 신호는 "
        "기능 구현·검증 완료, commit·push 요청 또는 완료, pull request 생성·갱신·병합, 반복 가능한 배포·장애 복구·"
        "데이터 이관의 완료입니다. 신호가 없거나 아직 승인·선택·추가정보를 기다리는 중이면 질문 없이 원래 완료 "
        "메시지를 유지하세요. 신호가 있고 같은 작업 단위에서 아직 묻지 않았다면 사용자에게 정확히 "
        "`이번 작업을 인수인계용 runbook으로 남길까요?`라고 한 번 물으세요. 완료 뒤 commit·push 같은 신호가 "
        "이어져도 같은 작업에는 다시 묻지 마세요. 이 제안 단계에서는 runbook 파일을 만들거나 기존 파일을 갱신하지 "
        f"마세요. 사용자가 `만들기`를 명시적으로 선택한 뒤에만 `{status}` 초안을 작성하고, `건너뛰기`를 선택하면 "
        "새로운 변경이 생기기 전까지 같은 작업으로 다시 묻지 마세요."
    )


def handle_user_prompt(
    root: Path, payload: dict[str, Any], config: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    turn_id = str(payload.get("turn_id", "unknown"))
    current = turn_state(state, turn_id)
    current.setdefault("prompt_hash", hashlib.sha256(str(payload.get("prompt", "")).encode("utf-8")).hexdigest())
    save_state(root, str(payload.get("session_id", "unknown")), state)
    if config["hooks"].get("enabled"):
        legacy_warning = ""
        if legacy_memory_hook_detected(config):
            legacy_warning = (
                " `memory.capture: hook`은 차단된 레거시 설정입니다. manager 승인으로 "
                "`memory.capture: explicit` 전환을 완료하기 전에는 기억 후처리를 실행하지 마세요."
            )
        return additional_context(
            "UserPromptSubmit",
            "TreeWiki 호환 훅이 활성화되어 있습니다. 요청 작업을 정상 수행하세요. "
            "Stop과 SessionEnd는 기억 저장·증류를 시작하지 않습니다. 기억은 스킬이 작업 완료 후보를 판단하고 "
            "사용자가 다음 메시지에서 저장을 확인한 뒤에만 현재 스레드에서 처리하세요. runbook은 사용자가 "
            "만들기를 명시적으로 선택하기 전에는 생성하거나 갱신하지 마세요."
            + legacy_warning,
        )
    return None


def handle_stop(
    root: Path, payload: dict[str, Any], config: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    hooks = config["hooks"]
    if not hooks.get("enabled"):
        return None
    if legacy_memory_hook_detected(config):
        return None
    session_id = str(payload.get("session_id", "unknown"))
    turn_id = str(payload.get("turn_id", "unknown"))
    current = turn_state(state, turn_id)
    emitted = current.setdefault("emitted", [])
    skipped = current.setdefault("skipped", [])
    if not isinstance(emitted, list) or not isinstance(skipped, list):
        current["emitted"], current["skipped"] = [], []
        emitted, skipped = current["emitted"], current["skipped"]

    if "completion_message" not in current:
        current["completion_message"] = str(payload.get("last_assistant_message") or "")

    runbook = hooks.get("runbook") if isinstance(hooks.get("runbook"), dict) else {}
    if runbook.get("enabled") and "runbook_proposal" not in emitted:
        emitted.append("runbook_proposal")
        save_state(root, session_id, state)
        return continuation(runbook_proposal_prompt(root, hooks))

    current["complete"] = True
    save_state(root, session_id, state)
    return None


def handle_session_start(
    root: Path, payload: dict[str, Any], config: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    deferred = state.pop("deferred_runbook_proposal", None)
    if deferred and config["hooks"].get("enabled"):
        save_state(root, str(payload.get("session_id", "unknown")), state)
        return additional_context("SessionStart", runbook_proposal_prompt(root, config["hooks"]))
    return None


def handle_session_end(
    root: Path, payload: dict[str, Any], config: dict[str, Any], state: dict[str, Any]
) -> None:
    hooks = config["hooks"]
    runbook = hooks.get("runbook") if isinstance(hooks.get("runbook"), dict) else {}
    if (
        not hooks.get("enabled")
        or not runbook.get("enabled")
        or legacy_memory_hook_detected(config)
    ):
        return None
    turns = state.get("turns") if isinstance(state.get("turns"), dict) else {}
    incomplete = [value for value in turns.values() if isinstance(value, dict) and not value.get("complete")]
    if incomplete:
        state["deferred_runbook_proposal"] = True
        save_state(root, str(payload.get("session_id", "unknown")), state)
    return None


def process_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    root = find_repository(
        str(payload.get("cwd") or Path.cwd()),
        fallback=global_fallback_repository(),
    )
    if root is None:
        return None
    config = load_config(root)
    event = str(payload.get("hook_event_name", ""))
    if event in {"Stop", "SessionEnd"} and legacy_memory_hook_detected(config):
        print(
            "WARNING LEGACY_MEMORY_HOOK: memory.capture=hook is blocked; Stop and "
            "SessionEnd did not start TreeWiki memory processing. Migrate to "
            "memory.capture=explicit with manager approval.",
            file=sys.stderr,
        )
        return None
    session_id = str(payload.get("session_id", "unknown"))
    state = load_state(root, session_id)
    if event == "UserPromptSubmit":
        return handle_user_prompt(root, payload, config, state)
    if event == "Stop":
        return handle_stop(root, payload, config, state)
    if event == "SessionStart":
        return handle_session_start(root, payload, config, state)
    if event == "SessionEnd":
        handle_session_end(root, payload, config, state)
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be a JSON object")
        output = process_event(payload)
        if output is not None:
            print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR TreeWiki hook failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
