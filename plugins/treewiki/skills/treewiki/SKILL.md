---
name: treewiki
description: Document and retrieve project policies and decisions through minimal Markdown, local BM25, links, citations, and local history.
---

# TreeWiki 0.3

TreeWiki manages project maps, policies, and decisions from the installed plugin. Do not look for or install a standalone TreeWiki skill.

## Start

1. Resolve the current repository root from the host workspace.
2. Call `connect_workspace` with that path and retain its `workspaceId` for this work unit.
3. Call `get_status`. If the workspace is uninitialized, use the bundled internal CLI `init`; never overwrite an older schema.
4. Call `search` for the request, then `read` only the selected results.

The bundled fallback CLI is `skills/treewiki/scripts/treewiki_cli.py` relative to the plugin root. It is internal implementation, not a user installation surface.

## Document model

- Manage only `AGENTS.md` maps, `docs/policies/**/*.md`, and `docs/decisions/**/*.md`.
- Frontmatter contains exactly `id` and `type`; types are `map`, `policy`, and `decision`.
- Preserve IDs across edits and moves. Derive the title from the first H1 and the summary from the first prose paragraph.
- Use ordinary relative Markdown links for navigation. Put citations under `## Sources`; never fetch or cache an external citation automatically.
- Prefer bodies no longer than 50 lines. An overage is a warning, not a validation failure.

## Change workflow

- Read the nearest `AGENTS.md` and linked policies or decisions before editing.
- Create policy and decision documents from the bundled templates and link them from the nearest map.
- Update a policy when a durable project rule changes. Add a decision when context, choice, and consequences should remain discoverable.
- Run `validate` after document changes. Resolve errors and review warnings.
- At successful completion, run the internal CLI `sync` automatically. It appends semantic create/update/move/delete events under `.knowledge/document-history/` and refreshes the derived BM25 index.

## Boundaries

- TreeWiki 0.3 has no document ACL, governed memory, persona, L3 review, federation, or 0.2 migration.
- Search may write only the recreatable `.knowledge/index/` cache. `read`, `history`, `status`, and `validate` do not mutate project documents.
- If an existing config is not `treewiki/0.3`, report that a fresh initialization is required and leave it untouched.

## Completion report

Report changed policy, decision, and map paths; validation evidence; history events; index refresh state; and whether any terminology changed.
