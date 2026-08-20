# Document composition

Count only the Markdown body after YAML frontmatter. The default target is 50 physical lines. More than 50 lines produces a review warning; more than 80 lines or about 1,000 tokens is invalid unless a reviewer records a concrete exception.

## Split structure

Split only at an independently retrievable topic, normally an H2 section that can answer its own question. Create a topic directory with a nearest `AGENTS.md` map and keep one overview plus focused child documents:

```text
docs/authentication/
├─ AGENTS.md
├─ overview.md
├─ token-lifecycle.md
└─ error-handling.md
```

The map declares `scope`, `read_when`, entry points, and validation. Every child keeps independent `id`, `type`, `topics`, `summary`, governance, ACL, lifecycle fields, and history. Use `derived_from` when content was extracted from another managed document and `related_to` for a semantic link. Do not invent an unsupported `part_of` relation.

Preserve the original document ID on `overview.md`; move it with `manage document-move` while its stable-ID local ledger remains at the same path. Add new IDs only for genuinely new child documents. Keep the overview concise and link every child from the directory map so one graph hop can recover the local set.

## Exception

Keep a long code sample, API matrix, or indivisible contract together only when splitting would damage reviewability. Record the reason only on the exceptional document:

```yaml
composition:
  size_exception: API compatibility matrix must be reviewed as one unit.
```

Do not add exception metadata to documents within the target. Configuration may override `documents.composition.body_line_target`, `body_line_hard_limit`, and `body_token_hard_limit`; the hard line limit must not be lower than the target.
