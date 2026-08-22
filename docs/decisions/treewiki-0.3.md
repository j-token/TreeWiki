---
id: DECISION-TREEWIKI-030-001
type: decision
---

# Redesign TreeWiki 0.3 around policies and decisions

## Context

TreeWiki 0.2 combined ACL retrieval, governed memory, L3 review, adapters, and extensive frontmatter. That made short project rules harder to author and discover.

## Decision

TreeWiki 0.3 manages only maps, policies, and decisions. It derives discovery data from Markdown, uses automatic local BM25, keeps history under `.knowledge`, and ships only as Agent and Claude plugins.

## Consequences

ACL, L0–L3 memory, persona, federation, retrieval gaps, standalone skill installation, and 0.2 migration are removed. Existing 0.2 repositories must be archived and initialized fresh instead of being rewritten automatically.

## Sources

- [Plugin-only policy](../policies/plugin-only.md)
- [Minimal document policy](../policies/minimal-documents.md)
