# Markdown metadata schema

All managed documents require stable `id`, `title`, `type`, `status`, `authority`, `topics`, `summary`, `relations`, and `reviewed`. Maps/contracts/runbooks additionally declare scope and reading conditions. Use `embedding.mode` as `allow`, `local_only`, or `deny`.

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

`source_ref` never reconstructs L0. L3 uses the same fields, starts `proposed`, and needs independent top-level provenance plus explicit approval before `active`. IDs survive renames, moves, translations, and migrations.
