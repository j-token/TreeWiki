#!/usr/bin/env python
"""Internal TreeWiki 0.3 CLI shared by plugin skills and MCP tools."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_script = Path(__file__).resolve()
for _vendor in (_script.parents[3] / "vendor", _script.parents[1] / "vendor"):
    if (_vendor / "yaml").is_dir():
        sys.path.insert(0, str(_vendor))
        break

from treewiki_core import TreeWikiError, document_history, initialize, read, search, status, sync, validate


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "validate", "sync"):
        command = commands.add_parser(name)
        command.add_argument("repository")
    search_command = commands.add_parser("search")
    search_command.add_argument("repository")
    search_command.add_argument("query")
    search_command.add_argument("--limit", type=int)
    read_command = commands.add_parser("read")
    read_command.add_argument("repository")
    read_command.add_argument("reference")
    history_command = commands.add_parser("history")
    history_command.add_argument("repository")
    history_command.add_argument("id")
    return root


def main() -> int:
    args = parser().parse_args()
    repository = Path(args.repository).resolve()
    try:
        if args.command == "init":
            result = initialize(repository)
        elif args.command == "status":
            result = status(repository)
        elif args.command == "search":
            result = search(repository, args.query, args.limit)
        elif args.command == "read":
            result = read(repository, args.reference)
        elif args.command == "history":
            result = {"id": args.id, "events": document_history(repository, args.id)}
        elif args.command == "validate":
            result = validate(repository)
        else:
            result = sync(repository)
        emit(result)
        return 0 if not isinstance(result, dict) or not result.get("errors") else 1
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, TreeWikiError) as exc:
        emit({"error": {"code": "TREEWIKI_ERROR", "message": str(exc)}})
        return 1


if __name__ == "__main__":
    sys.exit(main())
