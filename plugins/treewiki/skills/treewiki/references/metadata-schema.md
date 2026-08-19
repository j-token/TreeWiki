# Markdown metadata schema

All managed documents require stable `id`, `title`, `type`, `status`, `authority`, `topics`, `summary`, `relations`, and `reviewed`. Maps/contracts/runbooks additionally declare scope and reading conditions. Use `embedding.mode` as `allow`, `local_only`, or `deny`.

Config v4 also requires code-owned lifecycle fields on every managed Markdown document:

```yaml
created_at: <ISO-8601|null>
modified_at: <ISO-8601|null>
verified_at: <ISO-8601|null>
revision: <positive-integer>
history_ref: ./<stable-id>.history.jsonl
```

The co-located JSONL sidecar uses `treewiki.document-history/v1`. Meaningful body or metadata changes increment `revision` and `modified_at`; source verification changes only `verified_at`. `reviewed` remains the human governance review date. Lifecycle fields are excluded from the semantic hash.

Shared L1–L3 documents require:

```yaml
memory:
  level: l1
  subject: user:owner
  claim_key: concise-stable-claim
  confidence: 0.8
authored_by: user:owner
approved_by: user:owner
source_ref: opaque-local-reference
source_hash: sha256:...
source_machine: local-installation-id
```

`source_ref` never reconstructs L0. L3 uses the same fields, starts `proposed`, and needs independent top-level provenance plus explicit approval before `active`. IDs survive renames, moves, translations, and migrations. Use `manage document-move <repo> <ID> --to <path>` and its exact plan ID so the Markdown and stable-ID sidecar move in one transaction.
