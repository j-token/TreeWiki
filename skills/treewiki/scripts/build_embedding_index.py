#!/usr/bin/env python
"""Build a provider-neutral JSONL chunk manifest for optional embedding retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR PyYAML is required; install scripts/requirements.txt", file=sys.stderr)
    raise SystemExit(2)

from validate_knowledge import load_yaml, managed_documents, parse_markdown, relative_posix


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
SLUG_RE = re.compile(r"[^a-z0-9가-힣]+")


def normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def slug(value: str) -> str:
    result = SLUG_RE.sub("-", value.casefold()).strip("-")
    return result[:80] or "root"


def heading_sections(body: str, fallback_title: str) -> list[tuple[list[str], str]]:
    stack: list[str] = [fallback_title]
    current_path = stack.copy()
    current_lines: list[str] = []
    sections: list[tuple[list[str], str]] = []

    def flush() -> None:
        content = normalize("\n".join(current_lines))
        if content:
            sections.append((current_path.copy(), content))

    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if not match:
            current_lines.append(line)
            continue
        flush()
        current_lines.clear()
        level = len(match.group(1))
        title = match.group(2).strip()
        if level == 1:
            stack = [title]
        else:
            stack = stack[:level - 1]
            while len(stack) < level - 1:
                stack.append(fallback_title)
            stack.append(title)
        current_path = stack.copy()
    flush()
    return sections


def split_long_text(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    max_chars = max_tokens * 4
    overlap_chars = overlap_tokens * 4
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = text.rfind("\n\n", start + max_chars // 2, end)
            if boundary > start:
                end = boundary
        chunk = normalize(text[start:end])
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap_chars)
    return chunks


def read_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[str(record["chunk_id"])] = record
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", nargs="?", default=".")
    parser.add_argument("--output", help="Override JSONL output path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.repository).resolve()
    config_path = root / ".knowledge" / "config.yml"
    if not config_path.exists():
        print("ERROR .knowledge/config.yml not found")
        return 1

    try:
        config = load_yaml(config_path)
        embedding_config = config.get("embedding", {})
        if not isinstance(embedding_config, dict):
            raise ValueError("embedding configuration must be a mapping")
        if not embedding_config.get("enabled", False):
            print("Embedding is disabled; no index was built")
            return 0
        documents = managed_documents(root, config)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR configuration: {exc}")
        return 1

    execution = str(embedding_config.get("execution", "local"))
    remote_allowed = bool(embedding_config.get("remote_content_allowed", False))
    if execution == "remote" and not remote_allowed:
        print("ERROR remote execution requires remote_content_allowed: true")
        return 1

    max_tokens = int(embedding_config.get("chunk_max_tokens", 1000))
    overlap_tokens = int(embedding_config.get("chunk_overlap_tokens", 120))
    if max_tokens <= 0 or overlap_tokens < 0 or overlap_tokens >= max_tokens:
        print("ERROR invalid chunk token settings")
        return 1

    configured_output = str(embedding_config.get("index_path", ".knowledge/index/"))
    output = Path(args.output).resolve() if args.output else root / configured_output / "chunks.jsonl"
    existing = read_existing(output)
    generated: dict[str, dict[str, Any]] = {}
    skipped = 0

    for path in documents:
        try:
            metadata, body = parse_markdown(path)
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            print(f"ERROR {relative_posix(path, root)}: {exc}")
            return 1
        if metadata.get("status") != "active":
            skipped += 1
            continue

        policy = metadata.get("embedding") or {}
        if not isinstance(policy, dict):
            print(f"ERROR {relative_posix(path, root)}: embedding must be a mapping")
            return 1
        mode = policy.get("mode", "local_only")
        if mode == "deny" or (execution == "remote" and mode != "allow"):
            skipped += 1
            continue
        access = metadata.get("access") if isinstance(metadata.get("access"), dict) else {}
        visibility = access.get("visibility", "team")
        if execution == "remote" and visibility in {"private", "restricted", "agent"}:
            skipped += 1
            continue

        title = str(metadata.get("title", path.stem))
        if policy.get("content", "full") == "summary_only":
            summary_parts = [title, str(metadata.get("summary", ""))]
            summary_parts.extend(str(item) for item in metadata.get("topics", []))
            summary_parts.extend(str(item) for item in metadata.get("read_when", []))
            sections = [([title], normalize("\n".join(summary_parts)))]
        else:
            sections = heading_sections(body, title)

        ordinal = 0
        for heading_path, section_text in sections:
            contextual_text = normalize(" > ".join(heading_path) + "\n\n" + section_text)
            for chunk_text in split_long_text(contextual_text, max_tokens, overlap_tokens):
                ordinal += 1
                chunk_id = f"{metadata.get('id')}#{slug('-'.join(heading_path))}#{ordinal:04d}"
                content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
                generated[chunk_id] = {
                    "chunk_id": chunk_id,
                    "document_id": metadata.get("id"),
                    "source_path": relative_posix(path, root),
                    "heading_path": heading_path,
                    "ordinal": ordinal,
                    "text": chunk_text,
                    "content_hash": f"sha256:{content_hash}",
                    "type": metadata.get("type"),
                    "status": metadata.get("status"),
                    "authority": metadata.get("authority"),
                    "topics": metadata.get("topics", []),
                    "applies_to": metadata.get("applies_to", []),
                    "reviewed": str(metadata.get("reviewed", "")),
                    "embedding_mode": mode,
                    "visibility": visibility,
                    "owner": access.get("owner"),
                    "team": access.get("team"),
                }

    reused = sum(
        1
        for chunk_id, record in generated.items()
        if chunk_id in existing and existing[chunk_id].get("content_hash") == record["content_hash"]
    )
    changed = len(generated) - reused
    removed = len(set(existing) - set(generated))

    if not args.dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        serialized = "".join(
            json.dumps(generated[key], ensure_ascii=False, separators=(",", ":")) + "\n"
            for key in sorted(generated)
        )
        current = output.read_text(encoding="utf-8") if output.exists() else None
        if current != serialized:
            output.write_text(serialized, encoding="utf-8", newline="\n")

    print(
        f"Prepared {len(generated)} chunks: {reused} reused, {changed} new/changed, "
        f"{removed} removed, {skipped} documents skipped"
    )
    print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
