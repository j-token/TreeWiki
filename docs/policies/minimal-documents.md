---
id: POLICY-MINIMAL-DOCS-001
type: policy
---

# Keep managed Markdown minimal

Managed maps, policies, and decisions contain only `id` and `type` in frontmatter. Use an H1 for the title, prose for searchable context, relative Markdown links for navigation, and `## Sources` for citations.

Keep the body within 50 lines when practical. A longer body produces a review warning and should be split only when the topics are independently useful.

Store append-only document history under `.knowledge/document-history/` and the recreatable BM25 index under `.knowledge/index/`.

## Sources

- [TreeWiki 0.3 decision](../decisions/treewiki-0.3.md)
- [Repository map](../../AGENTS.md)
