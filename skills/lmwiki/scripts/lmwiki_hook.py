#!/usr/bin/env python
"""Drive LMWiki memory and runbook stages from Codex lifecycle hooks."""

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
    "enabled": True,
    "execution": "same_thread",
    "memory_stages": ["l0", "l1", "l2"],
    "l3": {"enabled": True, "minimum_sources": 2},
    "runbook": {
        "enabled": True,
        "require_user_confirmation": True,
        "status": "draft",
    },
}


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


def global_fallback_repository() -> str | None:
    path = Path(__file__).with_name("lmwiki-global.json")
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    value = payload.get("fallback_repository") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


def load_config(root: Path) -> dict[str, Any]:
    with (root / ".knowledge" / "config.yml").open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise ValueError(".knowledge/config.yml must contain a mapping")
    hooks = config.get("hooks") if isinstance(config.get("hooks"), dict) else {}
    config["hooks"] = merge_missing(hooks, DEFAULT_HOOKS)
    return config


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


def layer_prompt(level: str, root: Path, payload: dict[str, Any], hooks: dict[str, Any]) -> str:
    session_id = str(payload.get("session_id", "unknown"))
    turn_id = str(payload.get("turn_id", "unknown"))
    common = (
        f"[LMWiki lifecycle hook: {level.upper()}]\n"
        f"기억 저장소: {root}\n작업 경로: {payload.get('cwd', '')}\n세션: {session_id}\n턴: {turn_id}\n"
        f"{execution_instruction(hooks)} 사용자에게 질문하지 말고, 민감정보와 제3자 개인정보는 저장하지 마세요. "
        "이 단계의 후처리가 끝나기 전에는 최종 답변을 반복하지 마세요.\n"
    )
    if level == "l0":
        return common + (
            "현재 턴의 사용자 원문과 작업 근거를 `.knowledge/private-memory/l0/` 아래 새 memory 문서로 캡처하세요. "
            "원문은 수정하지 말고 provenance에 `conversation:<session-id>#<turn-id>`를 남기며 "
            "embedding.mode는 `deny`, visibility는 `private`로 두세요. 저장할 수 없는 내용뿐이면 파일을 만들지 마세요."
        )
    if level == "l1":
        return common + (
            "방금 캡처한 L0에서 장기적으로 다시 쓸 가치가 있는 사실·선호·제약·사건을 원자 단위 L1으로 증류하세요. "
            "각 문서는 L0 ID를 `distilled_from`으로 연결하고 근거와 무효화 조건을 남기세요. "
            "새로운 원자가 없으면 중복 문서를 만들지 마세요."
        )
    return common + (
        "현재 작업을 재개할 때 복원해야 하는 프로젝트·업무 장면이 있으면 L1을 묶어 L2로 증류하세요. "
        "L2는 근거 L1 ID를 `distilled_from`으로 연결하고 적용 조건과 관련 코드·문서를 기록하세요. "
        "개인 맥락은 private 경로에 두고, 사용자가 공유를 명시한 경우에만 `docs/memory/l2/`를 사용하세요."
    )


def parse_frontmatter(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    try:
        value = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return None
    return value if isinstance(value, dict) else None


def memory_documents(root: Path) -> list[dict[str, Any]]:
    paths: list[Path] = []
    for base in (root / ".knowledge" / "private-memory", root / "docs" / "memory"):
        if base.exists():
            paths.extend(base.rglob("*.md"))
    records: list[dict[str, Any]] = []
    for path in paths:
        metadata = parse_frontmatter(path)
        if metadata is not None:
            records.append(metadata)
    return records


def l3_candidates(root: Path, minimum_sources: int) -> dict[str, list[str]]:
    grouped: dict[str, set[str]] = {}
    covered: dict[str, set[str]] = {}
    records = memory_documents(root)
    for metadata in records:
        memory = metadata.get("memory") if isinstance(metadata.get("memory"), dict) else {}
        if (
            metadata.get("type") != "memory"
            or metadata.get("status") != "active"
            or memory.get("level") not in {"l1", "l2"}
        ):
            continue
        subject = memory.get("subject")
        doc_id = metadata.get("id")
        if isinstance(subject, str) and isinstance(doc_id, str):
            grouped.setdefault(subject, set()).add(doc_id)
    for metadata in records:
        memory = metadata.get("memory") if isinstance(metadata.get("memory"), dict) else {}
        if (
            metadata.get("type") != "persona"
            or metadata.get("status") != "active"
            or memory.get("level") != "l3"
        ):
            continue
        subject = memory.get("subject")
        relations = metadata.get("relations")
        if not isinstance(subject, str) or not isinstance(relations, list):
            continue
        for relation in relations:
            if (
                isinstance(relation, dict)
                and relation.get("type") == "distilled_from"
                and isinstance(relation.get("target"), str)
            ):
                covered.setdefault(subject, set()).add(str(relation["target"]))
    return {
        subject: sorted(doc_ids)
        for subject, doc_ids in grouped.items()
        if len(doc_ids) >= minimum_sources and not doc_ids.issubset(covered.get(subject, set()))
    }


def l3_prompt(
    root: Path, candidates: dict[str, list[str]], hooks: dict[str, Any]
) -> str:
    evidence = "\n".join(
        f"- {subject}: {', '.join(doc_ids)}" for subject, doc_ids in sorted(candidates.items())
    )
    return (
        "[LMWiki lifecycle hook: L3 eligibility passed]\n"
        f"저장소: {root}\n{execution_instruction(hooks)}\n"
        "프로그램이 같은 subject에서 활성 L1/L2 근거의 최소 개수를 확인했습니다. 아래 근거가 정말 서로 독립된 "
        "대화·작업에서 반복된 안정적 협업 선호인지 검토하세요. 독립성이 확인될 때만 private L3 Persona를 "
        "만들거나 갱신하고, 모든 근거 ID를 `distilled_from`으로 연결하세요. 단일 사건이거나 서로 파생된 같은 "
        "근거라면 Persona를 만들지 마세요.\n"
        f"후보:\n{evidence}"
    )


def runbook_proposal_prompt(root: Path, hooks: dict[str, Any]) -> str:
    status = str(hooks.get("runbook", {}).get("status", "draft"))
    return (
        "[LMWiki lifecycle hook: runbook proposal review]\n"
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
        return additional_context(
            "UserPromptSubmit",
            "LMWiki 생명주기 훅이 활성화되어 있습니다. 요청 작업을 정상 수행하세요. L0–L3와 runbook 생성 여부 제안 검토는 Stop에서 발화됩니다. runbook은 사용자가 만들기를 명시적으로 선택하기 전에는 생성하거나 갱신하지 마세요.",
        )
    return None


def handle_stop(
    root: Path, payload: dict[str, Any], config: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    hooks = config["hooks"]
    if not hooks.get("enabled"):
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

    memory = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    stages = hooks.get("memory_stages", [])
    if memory.get("enabled", True) and memory.get("capture") == "hook" and isinstance(stages, list):
        for level in ("l0", "l1", "l2"):
            if level in stages and level not in emitted:
                emitted.append(level)
                save_state(root, session_id, state)
                return continuation(layer_prompt(level, root, payload, hooks))

    l3 = hooks.get("l3") if isinstance(hooks.get("l3"), dict) else {}
    if l3.get("enabled") and "l3" not in emitted and "l3" not in skipped:
        minimum = max(2, int(l3.get("minimum_sources", memory.get("persona_requires_sources", 2))))
        candidates = l3_candidates(root, minimum)
        if candidates:
            emitted.append("l3")
            save_state(root, session_id, state)
            return continuation(l3_prompt(root, candidates, hooks))
        skipped.append("l3:no-eligible-subject")

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
    if not hooks.get("enabled") or not runbook.get("enabled"):
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
    session_id = str(payload.get("session_id", "unknown"))
    state = load_state(root, session_id)
    event = str(payload.get("hook_event_name", ""))
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
        print(f"ERROR LMWiki hook failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
