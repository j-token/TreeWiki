"""Deterministic local Git-to-TreeWiki code-context draft generation."""

from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import yaml

from authoring import apply_new_document, plan_new_document
from document_history import history_ref_for


SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Git command failed")
    return result.stdout


def resolve_commit(root: Path, commit: str) -> str:
    resolved = _git(root, "rev-parse", "--verify", f"{commit}^{{commit}}").strip().casefold()
    if not SHA_RE.match(resolved):
        raise ValueError("Git did not return a full commit SHA")
    return resolved


def changed_paths(root: Path, commit: str) -> list[str]:
    output = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit)
    return sorted({line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()})


def _validated_paths(root: Path, commit: str, supplied: Iterable[str] | None) -> list[str]:
    paths = sorted({value.replace("\\", "/").lstrip("./") for value in (supplied or changed_paths(root, commit)) if value.strip()})
    if not paths:
        raise ValueError("no changed or supplied paths were found")
    for value in paths:
        candidate = (root / value).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"source path escapes repository: {value}") from exc
        check = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{commit}:{value}"],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if check.returncode:
            raise ValueError(f"source path does not exist at commit {commit[:12]}: {value}")
    return paths


def source_digest(root: Path, commit: str, paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    digest.update((commit + "\n").encode("ascii"))
    for value in sorted(paths):
        blob = _git(root, "rev-parse", f"{commit}:{value}").strip()
        digest.update(f"{value}\0{blob}\n".encode("utf-8"))
    return "sha256:" + digest.hexdigest()


def build_context_plan(
    root: Path, *, commit: str, paths: Iterable[str] | None, symbols: Iterable[str],
    owner: str, team: str, output: str | None = None,
) -> dict[str, Any]:
    full_commit = resolve_commit(root, commit)
    selected = _validated_paths(root, full_commit, paths)
    digest = source_digest(root, full_commit, selected)
    short = full_commit[:12]
    document_id = f"CODE-CONTEXT-{short.upper()}"
    relative = output or f"docs/references/code-context-{short}.md"
    today = date.today().isoformat()
    metadata = {
        "id": document_id,
        "title": f"Code context for {short}",
        "type": "reference",
        "status": "draft",
        "authority": "generated",
        "topics": ["code-context"],
        "summary": f"Generated local code context for commit {short}.",
        "relations": [{"type": "implemented_by", "target": value} for value in selected],
        "reviewed": today,
        "created_at": None,
        "modified_at": None,
        "verified_at": None,
        "revision": 1,
        "history_ref": history_ref_for(document_id),
        "technical_writing": True,
        "context": {
            "audience": ["human", "agent"],
            "repository": f"repo:{root.name.casefold()}",
            "source_commit": full_commit,
            "source_paths": selected,
            "symbols": sorted(set(symbols)),
            "source_digest": digest,
            "generated": True,
            "generator": "treewiki-code-context/v1",
        },
        "governance": {
            "owner": owner,
            "reviewers": [owner],
            "review_cadence_days": 90,
            "source_of_truth": f"git:{full_commit}",
            "last_source_check": today,
            "duplicate_of": None,
            "retirement_reason": None,
            "scope": "domain",
            "domain": root.name.casefold(),
        },
        "access": {"visibility": "team", "owner": owner, "team": team, "grants": []},
        "embedding": {"mode": "local_only", "content": "full"},
    }
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    path_lines = "\n".join(f"- `{value}`" for value in selected)
    symbol_lines = "\n".join(f"- `{value}`" for value in sorted(set(symbols))) or "- None declared"
    body = (
        f"# Code context for {short}\n\n"
        "## Purpose\n\nProvide a reviewable draft that binds code changes to repository knowledge.\n\n"
        "## Audience\n\nRepository maintainers and coding agents.\n\n"
        f"## Source paths\n\n{path_lines}\n\n"
        f"## Symbols\n\n{symbol_lines}\n\n"
        "## Inputs and outputs\n\nInput is the immutable Git commit and selected blobs; output is this draft context.\n\n"
        "## Constraints\n\nThe generator does not infer intent. A human owner must review the draft before activation.\n\n"
        "## Examples\n\nUse the listed paths and symbols as retrieval anchors.\n\n"
        f"## Sources\n\n- Commit `{full_commit}`\n- Source digest `{digest}`\n"
    )
    content = f"---\n{frontmatter}\n---\n\n{body}"
    return plan_new_document(root, root / relative, content, document_id, kind="generate code context")


def apply_context_plan(root: Path, plan: dict[str, Any], *, actor: str, plan_id: str) -> dict[str, Any]:
    return apply_new_document(root, plan, actor=actor, plan_id=plan_id)
