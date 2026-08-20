# Markdown metadata schema

All managed documents require stable `id`, `title`, `type`, `status`, `authority`, `topics`, `summary`, `relations`, and `reviewed`. Maps/contracts/runbooks additionally declare scope and reading conditions. Use `embedding.mode` as `allow`, `local_only`, or `deny`.

Frontmatter is excluded from the managed-body budget. A document over the hard limit may remain whole only when `composition.size_exception` contains a concrete review reason; otherwise follow [document composition](document-composition.md) and split it behind a directory map.

Technical writing types are `how_to`, `reference`, `explanation`, `tutorial`, `troubleshooting`, and `api_contract`. Their required sections are type-specific and validated from the canonical authoring templates. Generated technical context always starts as `draft` and must not bypass owner review.

Code-linked documents declare reproducible local context:

```yaml
context:
  audience: [human, agent]
  repository: repo:treewiki
  source_commit: <immutable-commit-sha>
  source_paths: [<repository-relative-path>]
  source_digest: sha256:<digest-of-commit-blobs>
  symbols: [<symbol>]
  generated: false
  generator: null
```

General documents declare their maintenance contract:

```yaml
governance:
  owner: user:<id>
  reviewers: [user:<id>]
  review_cadence_days: 90
  source_of_truth: <reference>
  last_source_check: <ISO-8601>
  duplicate_of: null
  retirement_reason: null
  scope: central
  domain: null
```

`scope: central` uses the configured standards committee and `scope: domain` uses the matching domain committee. Committee approvals accumulate as explicit votes until quorum is met. Deprecated documents require a retirement reason and an active replacement linked with `supersedes`; duplicate declarations must resolve to a valid managed document.

Config v5 requires code-owned lifecycle summaries on every managed Markdown document:

```yaml
created_at: <ISO-8601|null>
modified_at: <ISO-8601|null>
verified_at: <ISO-8601|null>
revision: <positive-integer>
history_ref: .knowledge/document-history/<stable-id>.jsonl
```

The referenced local JSONL ledger uses `treewiki.document-history/v1` and is Git-ignored. It records actor, plan, reason, and hash-chain details; Git remains the shared change history. A fresh clone may have no local ledger and still validates. Its first finalize creates a baseline from the shared summary without changing revision or lifecycle dates. Meaningful body or metadata changes increment `revision` and `modified_at`; source verification changes only `verified_at`. `reviewed` remains the human governance review date. Lifecycle fields are excluded from the semantic hash.

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

`source_ref` never reconstructs L0. L3 uses the same fields, starts `proposed`, and needs independent top-level provenance plus explicit approval before `active`. IDs survive renames, moves, translations, and migrations. Use `manage document-move <repo> <ID> --to <path>` and its exact plan ID; the Markdown moves while the stable-ID local ledger path remains unchanged.
