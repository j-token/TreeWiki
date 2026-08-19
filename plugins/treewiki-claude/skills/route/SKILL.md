---
name: route
description: Route TreeWiki adoption, query, update, memory, L3 review, and upgrade requests from /treewiki.
---

# TreeWiki router

TreeWiki plugin version: `0.2.0`.

Use the current unfinished conversation request plus `$ARGUMENTS`. Before choosing
a write mode, inspect the nearest `.knowledge/config.yml` and run read-only
`manage upgrade-status --offline --json` with the caller identity when the config
exists. The bundled CLI is at `${CLAUDE_PLUGIN_ROOT}/runtime/knowledge_cli.py`.

Choose exactly one primary mode and emit this internal decision:

```json
{
  "schema": "treewiki.route-decision/v1",
  "mode": "adopt|query|update|remember|review|upgrade",
  "intent_summary": "string",
  "read_only": true,
  "requires_approval": false,
  "confidence": "high|medium|low",
  "blocking_state": null
}
```

Routing precedence:

1. Explicit upgrade, candidate review, or durable-memory intent.
2. Missing config routes to `adopt`; an upgrade-required config redirects writes
   to `upgrade` while reads remain allowed.
3. A candidate ID or `L3_CANDIDATE_CREATED` notice routes to `review`.
4. Documentation maintenance routes to `update`; retrieval routes to `query`.
5. If two modes remain equally plausible, perform only read-only inspection and
   ask the user to choose between two or three concrete interpretations.

Before a mutation, print `TreeWiki mode: <mode> — <reason>`. Then read only the
matching file under `references/`. Never use SessionStart, UserPromptSubmit, or
Stop hooks to capture memory, create candidates, or emit candidate notices.

- `adopt`: [adopt.md](references/adopt.md)
- `query`: [query.md](references/query.md)
- `update`: [update.md](references/update.md)
- `remember`: [remember.md](references/remember.md)
- `review`: [review.md](references/review.md)
- `upgrade`: [upgrade.md](references/upgrade.md)
