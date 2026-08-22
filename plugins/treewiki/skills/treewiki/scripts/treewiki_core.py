"""TreeWiki 0.3 policy and decision document core."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

import yaml


SCHEMA = "treewiki/0.3"
HISTORY_SCHEMA = "treewiki.document-history/v2"
INDEX_SCHEMA = "2"
ALLOWED_TYPES = {"map", "policy", "decision"}
ALLOWED_METADATA = {"id", "type"}
DEFAULT_INCLUDES = [
    "AGENTS.md",
    "**/AGENTS.md",
    "docs/policies/*.md",
    "docs/policies/**/*.md",
    "docs/decisions/*.md",
    "docs/decisions/**/*.md",
]
DEFAULT_EXCLUDES = [
    ".agents/**",
    ".knowledge/**",
    ".knowledge-v0.2-archive-*/**",
    "**/node_modules/**",
    "**/dist/**",
    "plugins/**/skills/**/assets/**",
    "plugins/treewiki-claude/runtime/**",
]
FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
WORD_RE = re.compile(r"[0-9A-Za-z_]+|[가-힣]+")


class TreeWikiError(RuntimeError):
    """A user-actionable TreeWiki error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def load_config(root: Path) -> dict[str, Any]:
    path = root / ".knowledge" / "config.yml"
    if not path.is_file():
        raise TreeWikiError("TreeWiki is not initialized; run the internal init command")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise TreeWikiError("unsupported TreeWiki schema; 0.3 requires a fresh initialization")
    return payload


def default_config() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "documents": {"include": DEFAULT_INCLUDES, "exclude": DEFAULT_EXCLUDES},
        "body_line_target": 50,
        "history_path": ".knowledge/document-history",
        "index_path": ".knowledge/index/search.db",
        "search_result_limit": 12,
        "graph_hops": 1,
    }


def initialize(root: Path) -> dict[str, Any]:
    root = root.resolve()
    knowledge = root / ".knowledge"
    config_path = knowledge / "config.yml"
    if config_path.exists():
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(payload, dict) and payload.get("schema") == SCHEMA:
            return {"status": "current", "config": relative_posix(config_path, root)}
        raise TreeWikiError("existing TreeWiki data uses an unsupported schema; archive it before fresh initialization")
    knowledge.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(default_config(), sort_keys=False, allow_unicode=True), encoding="utf-8")
    ignore_path = knowledge / ".gitignore"
    ignore_path.write_text("index/\ndocument-history/\n", encoding="utf-8")
    return {"status": "initialized", "config": relative_posix(config_path, root)}


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) or Path(path).match(pattern) for pattern in patterns)


def managed_paths(root: Path, config: dict[str, Any]) -> list[Path]:
    documents = config.get("documents") if isinstance(config.get("documents"), dict) else {}
    includes = documents.get("include", DEFAULT_INCLUDES)
    excludes = documents.get("exclude", DEFAULT_EXCLUDES)
    if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
        raise TreeWikiError("documents.include must be a string array")
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise TreeWikiError("documents.exclude must be a string array")
    found: dict[str, Path] = {}
    for path in root.rglob("*.md"):
        rel = relative_posix(path, root)
        if matches(rel, includes) and not matches(rel, excludes):
            found[rel] = path
    return [found[key] for key in sorted(found)]


def parse_document(path: Path, root: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    if not match:
        raise TreeWikiError("missing YAML frontmatter")
    metadata = yaml.safe_load(match.group(1)) or {}
    if not isinstance(metadata, dict):
        raise TreeWikiError("frontmatter must be a mapping")
    body = raw[match.end():].strip()
    h1 = H1_RE.search(body)
    title = h1.group(1).strip() if h1 else ""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    summary = ""
    for paragraph in paragraphs:
        if not paragraph.startswith(("#", "-", "*", "```", ">")):
            summary = " ".join(line.strip() for line in paragraph.splitlines())
            break
    return {
        "path": relative_posix(path, root),
        "absolute_path": path.resolve(),
        "raw": raw,
        "metadata": metadata,
        "body": body,
        "id": metadata.get("id"),
        "type": metadata.get("type"),
        "title": title,
        "summary": summary,
        "headings": HEADING_RE.findall(body),
        "links": [{"label": label.strip(), "target": target.strip()} for label, target in LINK_RE.findall(body)],
    }


def load_documents(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in managed_paths(root, config):
        try:
            documents.append(parse_document(path, root))
        except (OSError, UnicodeError, yaml.YAMLError, TreeWikiError) as exc:
            documents.append({"path": relative_posix(path, root), "error": str(exc)})
    return documents


def body_line_count(body: str) -> int:
    return len(body.splitlines())


def internal_target(source: dict[str, Any], target: str, root: Path) -> str | None:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    candidate = (Path(source["absolute_path"]).parent / unquote(parsed.path)).resolve()
    try:
        return relative_posix(candidate, root)
    except ValueError:
        return None


def external_sources(document: dict[str, Any]) -> list[dict[str, str]]:
    lines = document["body"].splitlines()
    in_sources = False
    values: list[dict[str, str]] = []
    for line in lines:
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            in_sources = heading.group(1).strip().casefold() == "sources"
            continue
        if not in_sources:
            continue
        for label, target in LINK_RE.findall(line):
            parsed = urlsplit(target.strip())
            if parsed.scheme in {"http", "https"}:
                values.append({"label": label.strip(), "url": target.strip()})
    return values


def validate(root: Path) -> dict[str, Any]:
    config = load_config(root)
    documents = load_documents(root, config)
    errors: list[str] = []
    warnings: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    by_path = {doc["path"]: doc for doc in documents if "error" not in doc}
    target = int(config.get("body_line_target", 50))
    for document in documents:
        path = document["path"]
        if "error" in document:
            errors.append(f"{path}: {document['error']}")
            continue
        metadata = document["metadata"]
        extra = sorted(set(metadata) - ALLOWED_METADATA)
        if extra:
            errors.append(f"{path}: unsupported frontmatter fields: {', '.join(extra)}")
        doc_id = document["id"]
        if not isinstance(doc_id, str) or not doc_id.strip():
            errors.append(f"{path}: id must be a non-empty string")
        elif doc_id in by_id:
            errors.append(f"{path}: duplicate id {doc_id} also used by {by_id[doc_id]['path']}")
        else:
            by_id[doc_id] = document
        if document["type"] not in ALLOWED_TYPES:
            errors.append(f"{path}: type must be map, policy, or decision")
        if Path(path).name == "AGENTS.md" and document["type"] != "map":
            errors.append(f"{path}: AGENTS.md must use type map")
        if not document["title"]:
            errors.append(f"{path}: body must contain one H1 title")
        lines = body_line_count(document["body"])
        if lines > target:
            warnings.append(f"{path}: body has {lines} lines; consider splitting near {target}")
    for document in by_path.values():
        for link in document["links"]:
            resolved = internal_target(document, link["target"], root)
            if resolved is not None and resolved.endswith(".md") and resolved not in by_path and not (root / resolved).is_file():
                warnings.append(f"{document['path']}: broken Markdown link {link['target']}")
        if document["type"] in {"policy", "decision"} and not document["links"]:
            warnings.append(f"{document['path']}: add a related document or source link when evidence exists")
    return {"schema": SCHEMA, "documents": len(documents), "errors": errors, "warnings": warnings, "valid": not errors}


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


def fts_query(query: str) -> str:
    tokens = list(dict.fromkeys(search_tokens(query)))
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)


def corpus_hash(documents: list[dict[str, Any]]) -> str:
    values = [f"{doc['path']}\0{sha256_text(doc['raw'])}" for doc in documents if "error" not in doc]
    return sha256_text("\n".join(sorted(values)))


def configured_path(root: Path, config: dict[str, Any], key: str, default: str) -> Path:
    path = (root / str(config.get(key, default))).resolve()
    knowledge = (root / ".knowledge").resolve()
    try:
        path.relative_to(knowledge)
    except ValueError as exc:
        raise TreeWikiError(f"{key} must stay under .knowledge") from exc
    return path


def _build_index(database: Path, documents: list[dict[str, Any]], digest: str) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix=".treewiki-index-", suffix=".db", dir=database.parent, delete=False)
    temporary = Path(handle.name)
    handle.close()
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript("""
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE documents (doc_id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, type TEXT NOT NULL, links_json TEXT NOT NULL);
                CREATE VIRTUAL TABLE documents_fts USING fts5(
                    doc_id UNINDEXED, path UNINDEXED, title, summary, headings, link_labels, body,
                    tokenize='unicode61 remove_diacritics 0'
                );
            """)
            for document in documents:
                if "error" in document:
                    continue
                labels = " ".join(link["label"] for link in document["links"])
                connection.execute(
                    "INSERT INTO documents(doc_id,path,type,links_json) VALUES(?,?,?,?)",
                    (document["id"], document["path"], document["type"], canonical_json(document["links"])),
                )
                connection.execute(
                    "INSERT INTO documents_fts(doc_id,path,title,summary,headings,link_labels,body) VALUES(?,?,?,?,?,?,?)",
                    (
                        document["id"], document["path"], " ".join(search_tokens(document["title"])),
                        " ".join(search_tokens(document["summary"])), " ".join(search_tokens(" ".join(document["headings"]))),
                        " ".join(search_tokens(labels)), " ".join(search_tokens(document["body"])),
                    ),
                )
            metadata = {"schema": INDEX_SCHEMA, "corpus_hash": digest, "built_at": utc_now(), "document_count": str(len(documents))}
            connection.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", metadata.items())
            connection.commit()
            connection.execute("PRAGMA optimize")
        finally:
            connection.close()
        os.replace(temporary, database)
    finally:
        if temporary.exists():
            temporary.unlink()


def ensure_index(root: Path, config: dict[str, Any], documents: list[dict[str, Any]]) -> tuple[Path, bool]:
    database = configured_path(root, config, "index_path", ".knowledge/index/search.db")
    digest = corpus_hash(documents)
    fresh = False
    if database.is_file():
        try:
            connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                values = dict(connection.execute("SELECT key,value FROM metadata").fetchall())
                fresh = values.get("schema") == INDEX_SCHEMA and values.get("corpus_hash") == digest
            finally:
                connection.close()
        except sqlite3.Error:
            fresh = False
    if not fresh:
        _build_index(database, documents, digest)
    return database, not fresh


def link_graph(root: Path, documents: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    by_path = {doc["path"]: doc for doc in documents if "error" not in doc}
    outgoing: dict[str, set[str]] = {str(doc["id"]): set() for doc in by_path.values()}
    incoming: dict[str, set[str]] = {str(doc["id"]): set() for doc in by_path.values()}
    for document in by_path.values():
        source_id = str(document["id"])
        for link in document["links"]:
            target_path = internal_target(document, link["target"], root)
            target = by_path.get(target_path or "")
            if target is not None:
                target_id = str(target["id"])
                outgoing[source_id].add(target_id)
                incoming[target_id].add(source_id)
    return outgoing, incoming


def search(root: Path, query: str, limit: int | None = None) -> dict[str, Any]:
    config = load_config(root)
    validation = validate(root)
    if validation["errors"]:
        raise TreeWikiError("managed documents are invalid; run validate for details")
    documents = load_documents(root, config)
    database, rebuilt = ensure_index(root, config, documents)
    expression = fts_query(query)
    if not expression:
        raise TreeWikiError("search query has no searchable terms")
    result_limit = max(1, min(int(limit or config.get("search_result_limit", 12)), 50))
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = connection.execute("""
            SELECT doc_id,path,bm25(documents_fts,0.0,0.0,8.0,4.0,6.0,3.0,1.0) score
            FROM documents_fts WHERE documents_fts MATCH ? ORDER BY score,path LIMIT ?
        """, (expression, result_limit)).fetchall()
    finally:
        connection.close()
    by_id = {str(doc["id"]): doc for doc in documents if "error" not in doc}
    outgoing, incoming = link_graph(root, documents)
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rank, (doc_id, path, score) in enumerate(rows, 1):
        document = by_id[str(doc_id)]
        hits.append({"id": doc_id, "path": path, "title": document["title"], "rank": rank, "score": float(score), "via": None})
        seen.add(str(doc_id))
    if int(config.get("graph_hops", 1)) > 0:
        direct = list(hits)
        for hit in direct:
            for linked in sorted(outgoing.get(str(hit["id"]), set()) | incoming.get(str(hit["id"]), set())):
                if linked in seen or len(hits) >= result_limit:
                    continue
                document = by_id[linked]
                hits.append({"id": linked, "path": document["path"], "title": document["title"], "rank": None, "score": None, "via": hit["id"]})
                seen.add(linked)
    return {"query": query, "index_rebuilt": rebuilt, "results": hits}


def read(root: Path, reference: str) -> dict[str, Any]:
    config = load_config(root)
    documents = load_documents(root, config)
    clean = [doc for doc in documents if "error" not in doc]
    selected = next((doc for doc in clean if doc["id"] == reference or doc["path"] == reference), None)
    if selected is None:
        raise TreeWikiError(f"managed document not found: {reference}")
    outgoing, incoming = link_graph(root, clean)
    return {
        "id": selected["id"], "type": selected["type"], "path": selected["path"], "title": selected["title"],
        "summary": selected["summary"], "body": selected["body"], "outgoing": sorted(outgoing.get(str(selected["id"]), set())),
        "backlinks": sorted(incoming.get(str(selected["id"]), set())), "sources": external_sources(selected),
    }


def history_directory(root: Path, config: dict[str, Any]) -> Path:
    return configured_path(root, config, "history_path", ".knowledge/document-history")


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    previous: str | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("schema") != HISTORY_SCHEMA:
            raise TreeWikiError(f"unsupported history schema in {path.name}:{number}")
        supplied = event.get("event_hash")
        payload = {key: value for key, value in event.items() if key != "event_hash"}
        if event.get("previous_event_hash") != previous or supplied != sha256_text(canonical_json(payload)):
            raise TreeWikiError(f"invalid history hash chain in {path.name}:{number}")
        previous = supplied
        events.append(event)
    return events


def document_history(root: Path, document_id: str) -> list[dict[str, Any]]:
    config = load_config(root)
    return _read_events(history_directory(root, config) / f"{document_id}.jsonl")


def _append_event(path: Path, event: dict[str, Any]) -> dict[str, Any]:
    events = _read_events(path)
    payload = {**event, "previous_event_hash": events[-1]["event_hash"] if events else None}
    payload["event_hash"] = sha256_text(canonical_json(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(payload) + "\n")
    return payload


def sync(root: Path) -> dict[str, Any]:
    config = load_config(root)
    report = validate(root)
    if report["errors"]:
        raise TreeWikiError("managed documents are invalid; run validate before sync")
    documents = [doc for doc in load_documents(root, config) if "error" not in doc]
    directory = history_directory(root, config)
    current = {str(doc["id"]): doc for doc in documents}
    previous: dict[str, dict[str, Any]] = {}
    if directory.is_dir():
        for path in directory.glob("*.jsonl"):
            events = _read_events(path)
            if events:
                previous[str(events[-1]["id"])] = events[-1]
    changed: list[dict[str, Any]] = []
    for doc_id, document in sorted(current.items()):
        semantic_hash = sha256_text(document["body"])
        prior = previous.get(doc_id)
        if prior and prior.get("event") != "deleted" and prior.get("semantic_hash") == semantic_hash and prior.get("path") == document["path"] and prior.get("type") == document["type"]:
            continue
        if prior is None or prior.get("event") == "deleted":
            action = "created"
        elif prior.get("semantic_hash") == semantic_hash and prior.get("path") != document["path"]:
            action = "moved"
        else:
            action = "updated"
        event = {
            "schema": HISTORY_SCHEMA, "id": doc_id, "event": action, "timestamp": utc_now(), "path": document["path"],
            "type": document["type"], "semantic_hash": semantic_hash, "previous_path": prior.get("path") if prior else None,
        }
        changed.append(_append_event(directory / f"{doc_id}.jsonl", event))
    for doc_id, prior in sorted(previous.items()):
        if doc_id in current or prior.get("event") == "deleted":
            continue
        event = {
            "schema": HISTORY_SCHEMA, "id": doc_id, "event": "deleted", "timestamp": utc_now(), "path": prior.get("path"),
            "type": prior.get("type"), "semantic_hash": prior.get("semantic_hash"), "previous_path": prior.get("path"),
        }
        changed.append(_append_event(directory / f"{doc_id}.jsonl", event))
    _, rebuilt = ensure_index(root, config, documents)
    return {"history_events": changed, "index_rebuilt": rebuilt, "documents": len(documents)}


def status(root: Path) -> dict[str, Any]:
    config_path = root / ".knowledge" / "config.yml"
    if not config_path.is_file():
        return {"status": "uninitialized", "schema": None, "documents": 0, "index_fresh": False}
    try:
        config = load_config(root)
    except TreeWikiError as exc:
        return {"status": "unsupported_schema", "schema": None, "documents": 0, "index_fresh": False, "message": str(exc)}
    documents = load_documents(root, config)
    database = configured_path(root, config, "index_path", ".knowledge/index/search.db")
    fresh = False
    if database.is_file():
        try:
            connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                values = dict(connection.execute("SELECT key,value FROM metadata").fetchall())
                fresh = values.get("schema") == INDEX_SCHEMA and values.get("corpus_hash") == corpus_hash(documents)
            finally:
                connection.close()
        except sqlite3.Error:
            pass
    return {"status": "current", "schema": SCHEMA, "documents": len(documents), "index_fresh": fresh}
