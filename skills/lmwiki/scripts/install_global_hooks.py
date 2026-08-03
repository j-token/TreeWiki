#!/usr/bin/env python
"""Install or update the LMWiki lifecycle hook in the global Codex layer."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


EVENTS = {
    "SessionStart": (10, "LMWiki 후처리 상태 확인"),
    "UserPromptSubmit": (10, "LMWiki 작업 계층 준비"),
    "Stop": (30, "LMWiki 기억 계층 처리"),
    "SessionEnd": (3, "LMWiki 종료 상태 기록"),
}
MARKER = "lmwiki_hook.py"


def handler(runner: Path, timeout: int, status_message: str) -> dict[str, Any]:
    windows_path = str(runner)
    portable_path = runner.as_posix()
    return {
        "type": "command",
        "command": f'python -X utf8 "{portable_path}"',
        "commandWindows": f'python -X utf8 "{windows_path}"',
        "timeout": timeout,
        "statusMessage": status_message,
    }


def merge_hook(payload: dict[str, Any], event: str, value: dict[str, Any]) -> None:
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("global hooks.json field 'hooks' must be an object")
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise ValueError(f"global hooks.json event {event} must be an array")
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        for index, existing in enumerate(group["hooks"]):
            if isinstance(existing, dict) and MARKER in str(existing.get("command", "")):
                group["hooks"][index] = value
                return
    groups.append({"hooks": [value]})


def install(
    codex_home: Path,
    dry_run: bool = False,
    fallback_repository: Path | None = None,
) -> tuple[Path, Path]:
    source_runner = Path(__file__).with_name("lmwiki_hook.py")
    if not source_runner.is_file():
        raise ValueError(f"LMWiki hook runner not found: {source_runner}")
    hooks_path = codex_home / "hooks.json"
    runner_path = codex_home / "hooks" / "lmwiki_hook.py"
    settings_path = codex_home / "hooks" / "lmwiki-global.json"
    if fallback_repository is not None and not (
        fallback_repository / ".knowledge" / "config.yml"
    ).is_file():
        raise ValueError(
            f"fallback repository is not an initialized LMWiki repository: {fallback_repository}"
        )
    if hooks_path.exists():
        loaded = json.loads(hooks_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("global hooks.json must contain a JSON object")
        payload = loaded
    else:
        payload = {"hooks": {}}
    for event, (timeout, status_message) in EVENTS.items():
        merge_hook(payload, event, handler(runner_path.resolve(), timeout, status_message))
    if dry_run:
        return hooks_path, runner_path

    codex_home.mkdir(parents=True, exist_ok=True)
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    if hooks_path.exists() and hooks_path.stat().st_size > 0:
        backup = hooks_path.with_suffix(".json.lmwiki-backup")
        if not backup.exists():
            shutil.copy2(hooks_path, backup)
    shutil.copy2(source_runner, runner_path)
    if fallback_repository is not None:
        settings_path.write_text(
            json.dumps(
                {"fallback_repository": str(fallback_repository.resolve())},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    temporary = hooks_path.with_suffix(".json.lmwiki-tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(hooks_path)
    return hooks_path, runner_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--fallback-repository", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        hooks_path, runner_path = install(
            args.codex_home.resolve(),
            args.dry_run,
            args.fallback_repository.resolve() if args.fallback_repository else None,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR global hook installation failed: {exc}", file=sys.stderr)
        return 1
    mode = "DRY-RUN" if args.dry_run else "INSTALLED"
    print(f"{mode} {hooks_path}")
    print(f"{mode} {runner_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
