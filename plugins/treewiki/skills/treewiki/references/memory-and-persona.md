# Memory and Persona

| Level | Content | Canonical location | Sharing |
| --- | --- | --- | --- |
| L0 | Raw conversation and tool evidence | `.knowledge/private-memory/l0/` | local, ignored |
| L1 | One fact, preference, constraint, or event | `docs/memory/l1/` | explicit approval |
| L2 | Project or work context | `docs/memory/l2/` | explicit approval |
| L3 knowledge | Durable fact, synthesis, or rule | `docs/memory/l3/knowledge/` | explicit approval |
| L3 persona | Durable user preference | `docs/memory/l3/persona/` | explicit approval |

L1–L3 must not reproduce L0. They require `authored_by`, `approved_by`, opaque `source_ref`, `source_hash`, `source_machine`, `status`, and a `distilled_from` relation. Git tracking is allowed for approved shared documents, but never means automatic Git mutation. Private/restricted material and secrets are not promoted.

L1 records `memory.kind` as `fact`, `preference`, `conditional-action`, `constraint`, `event`, or `context`. Review reusable preferences and conditional rules after capture.

L3 is proactive but governed. A candidate is one independently approvable claim.

- `fact`: one authoritative/canonical source, or two independent sources.
- `information`: two distinct facts, experiments, or observations supporting one synthesis.
- `rule`: one official contract or explicit user declaration, or two repeated outcomes.
- `preference`: one explicit user declaration, or the same choice in two independent tasks followed by confirmation.

Evidence may declare `memory.supports_claim` so different L1/L2 claims converge on one L3. The agent drafts the synthesis; deterministic code checks the projected claim, exact evidence IDs, distinct work units and top-level provenance, threshold, ACL, and evidence digest. Existing active L3 conflicts require a `supersedes` proposal. Only the approved replacement becomes active; the prior document becomes `deprecated`.
