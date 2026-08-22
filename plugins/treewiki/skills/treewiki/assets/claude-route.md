---
name: route
description: Search and document project policies and decisions from /treewiki using local BM25, links, citations, and local history.
---

# TreeWiki 0.3 for Claude Code

Use the current repository root and the internal CLI at `${CLAUDE_PLUGIN_ROOT}/runtime/treewiki_cli.py`.

## Start

1. Run `status <repository-root>`.
2. If uninitialized, run `init <repository-root>` only when adopting TreeWiki is part of the request. Never overwrite an older schema.
3. Run `search <repository-root> <request>` before reading or editing.
4. Run `read <repository-root> <id-or-path>` for selected results only.

## Documents

- Manage `AGENTS.md` maps, `docs/policies/**/*.md`, and `docs/decisions/**/*.md`.
- Frontmatter contains exactly `id` and `type`; preserve IDs across edits and moves.
- Use relative Markdown links for progressive discovery and `## Sources` for citations.
- Prefer bodies at or below 50 lines; an overage is only a warning.

## Changes

- Read the nearest map and linked policies or decisions before editing.
- Use `map`, `policy`, or `decision`; title with one H1.
- Run `validate` after changes and resolve all errors.
- At successful completion, run `sync` automatically to append local history and refresh BM25.

TreeWiki 0.3 has no ACL, governed memory, persona, L3 review, federation, standalone skill installation, or 0.2 migration. External citation URLs are links only; do not fetch them automatically.
