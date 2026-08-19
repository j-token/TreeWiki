#!/usr/bin/env python
"""Build a local SQLite FTS5/BM25 index that returns document locations only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR PyYAML is required; install scripts/requirements.txt", file=sys.stderr)
    raise SystemExit(2)

from validate_knowledge import load_yaml, managed_documents, parse_markdown, relative_posix


SCHEMA_VERSION = "1"
WORD_RE = re.compile(r"[0-9A-Za-z_]+|[가-힣]+")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def korean_ngrams(token: str) -> list[str]:
    if len(token) < 2 or not all("가" <= char <= "힣" for char in token):
        return []
    return [f"k{ord(token[index]):04x}{ord(token[index + 1]):04x}" for index in range(len(token) - 1)]


def search_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in WORD_RE.finditer(text or ""):
        token = match.group(0).casefold()
        tokens.append(token)
        tokens.extend(korean_ngrams(token))
    return tokens


def fts_query(terms: Iterable[str]) -> str:
    tokens: list[str] = []
    seen: set[str] = set()
    for term in terms:
        for token in search_tokens(str(term)):
            if token not in seen:
                seen.add(token)
                tokens.append(token)
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)


def vocabulary_text(metadata: dict[str, Any], vocabulary: dict[str, Any]) -> str:
    values: list[str] = []
    for topic in metadata.get("topics", []):
        key = str(topic)
        values.append(key)
        entry = vocabulary.get(key)
        if not isinstance(entry, dict):
            continue
        values.append(str(entry.get("label", "")))
        aliases = entry.get("aliases", [])
        if isinstance(aliases, list):
            values.extend(str(alias) for alias in aliases)
    return " ".join(values)


def assert_fts5(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(text)")
        connection.execute("DROP TABLE temp.fts5_probe")
    except sqlite3.OperationalError as exc:
        raise RuntimeError("Python SQLite was built without FTS5 support") from exc


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE documents (
            doc_id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            status TEXT,
            authority TEXT,
            access_json TEXT NOT NULL,
            relations_json TEXT NOT NULL,
            content_hash TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE documents_fts USING fts5(
            doc_id UNINDEXED,
            path UNINDEXED,
            title,
            summary,
            topics,
            headings,
            body,
            tokenize = 'unicode61 remove_diacritics 0'
        );
        """
    )


def build_database(
    connection: sqlite3.Connection,
    root: Path,
    config: dict[str, Any],
    documents: list[Path],
) -> int:
    vocabulary_path = root / str(config.get("vocabulary_path", "docs/vocabulary/topics.yml"))
    vocabulary = load_yaml(vocabulary_path) if vocabulary_path.exists() else {}
    corpus_hash = hashlib.sha256()
    count = 0

    for path in documents:
        metadata, body = parse_markdown(path)
        doc_id = metadata.get("id")
        if not isinstance(doc_id, str) or not doc_id:
            raise ValueError(f"{relative_posix(path, root)}: id is required for search indexing")
        rel = relative_posix(path, root)
        raw = path.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        corpus_hash.update(f"{rel}\0{content_hash}\n".encode("utf-8"))
        headings = " ".join(HEADING_RE.findall(body))
        access = metadata.get("access") if isinstance(metadata.get("access"), dict) else {}
        relations = metadata.get("relations") if isinstance(metadata.get("relations"), list) else []

        connection.execute(
            """
            INSERT INTO documents(
                doc_id, path, status, authority, access_json, relations_json, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                rel,
                metadata.get("status"),
                metadata.get("authority"),
                json.dumps(access, ensure_ascii=False, separators=(",", ":")),
                json.dumps(relations, ensure_ascii=False, separators=(",", ":")),
                f"sha256:{content_hash}",
            ),
        )
        connection.execute(
            """
            INSERT INTO documents_fts(doc_id, path, title, summary, topics, headings, body)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                rel,
                " ".join(search_tokens(str(metadata.get("title", "")))),
                " ".join(search_tokens(str(metadata.get("summary", "")))),
                " ".join(search_tokens(vocabulary_text(metadata, vocabulary))),
                " ".join(search_tokens(headings)),
                " ".join(search_tokens(body)),
            ),
        )
        count += 1

    values = {
        "schema_version": SCHEMA_VERSION,
        "builder_sha256": "sha256:"
        + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "corpus_hash": f"sha256:{corpus_hash.hexdigest()}",
        "document_count": str(count),
        "result_contract": "locations_only",
        "query_mode": "high_recall",
    }
    connection.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", values.items())
    return count


def search_locations(
    database: Path,
    terms: Iterable[str],
    allowed_ids: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    query = fts_query(terms)
    if not query or not allowed_ids:
        return []
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("CREATE TEMP TABLE allowed_docs(doc_id TEXT PRIMARY KEY)")
        connection.executemany(
            "INSERT INTO allowed_docs(doc_id) VALUES (?)",
            ((doc_id,) for doc_id in sorted(allowed_ids)),
        )
        rows = connection.execute(
            """
            SELECT documents_fts.doc_id, documents_fts.path,
                   bm25(documents_fts, 0.0, 0.0, 8.0, 4.0, 6.0, 3.0, 1.0) AS bm25_score
            FROM documents_fts
            JOIN allowed_docs ON allowed_docs.doc_id = documents_fts.doc_id
            WHERE documents_fts MATCH ?
            ORDER BY bm25_score ASC, documents_fts.path ASC
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    finally:
        connection.close()
    return [
        {"id": row[0], "path": row[1], "bm25_score": float(row[2]), "rank": index + 1}
        for index, row in enumerate(rows)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", nargs="?", default=".")
    parser.add_argument("--output", help="Override SQLite output path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.repository).resolve()
    config_path = root / ".knowledge" / "config.yml"
    if not config_path.exists():
        print("ERROR .knowledge/config.yml not found")
        return 1
    try:
        config = load_yaml(config_path)
        embedding = config.get("embedding") if isinstance(config.get("embedding"), dict) else {}
        retrieval = config.get("retrieval") if isinstance(config.get("retrieval"), dict) else {}
        if not embedding.get("enabled", False):
            print("Embedding is disabled; SQLite BM25 index was not built")
            return 0
        if not retrieval.get("bm25_enabled", True):
            print("SQLite BM25 retrieval is disabled")
            return 0
        documents = managed_documents(root, config)
        configured = str(retrieval.get("bm25_index_path", ".knowledge/index/search.db"))
        if args.output:
            output = Path(args.output).resolve()
        else:
            output = (root / configured).resolve()
            index_root = (root / ".knowledge" / "index").resolve()
            try:
                output.relative_to(index_root)
            except ValueError as exc:
                raise ValueError(
                    "retrieval.bm25_index_path must stay under .knowledge/index/"
                ) from exc

        if args.dry_run:
            connection = sqlite3.connect(":memory:")
            try:
                assert_fts5(connection)
            finally:
                connection.close()
            print(f"Prepared SQLite BM25 plan: {len(documents)} documents")
            print(f"Output: {output}")
            return 0

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(
        prefix=".treewiki-search-", suffix=".db", dir=output.parent, delete=False
        )
        temporary_path = Path(temporary.name)
        temporary.close()
        try:
            connection = sqlite3.connect(temporary_path)
            try:
                assert_fts5(connection)
                create_schema(connection)
                with connection:
                    count = build_database(connection, root, config, documents)
                connection.execute("PRAGMA optimize")
            finally:
                connection.close()
            os.replace(temporary_path, output)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
    except (OSError, UnicodeError, ValueError, RuntimeError, sqlite3.Error, yaml.YAMLError) as exc:
        print(f"ERROR {exc}")
        return 1

    print(f"Built SQLite BM25 index: {count} documents")
    print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
