# Memory and Persona

| Level | Content | Canonical location | Sharing |
| --- | --- | --- | --- |
| L0 | Raw conversation and tool evidence | `.knowledge/private-memory/l0/` | local, ignored |
| L1 | One fact, preference, constraint, or event | `docs/memory/l1/` | explicit approval |
| L2 | Project or work context | `docs/memory/l2/` | explicit approval |
| L3 | Durable Persona or team operating rule | `docs/memory/l3/` | explicit approval |

L1–L3 must not reproduce L0. They require `authored_by`, `approved_by`, opaque `source_ref`, `source_hash`, `source_machine`, `status`, and a `distilled_from` relation. Git tracking is allowed for approved shared documents, but never means automatic Git mutation. Private/restricted material and secrets are not promoted.

L1 records `memory.kind` as `fact`, `preference`, `conditional-action`, `constraint`, `event`, or `context`. Review reusable preferences and conditional rules after capture.

L3 is deliberately proactive but conservative: group by `(subject, claim_key)`, count distinct top-level provenance only, and exclude evidence already covered by an existing L3. One source reports the missing count; two or more sources produce one `proposed` candidate. Do not combine unrelated or conflicting claims. A user or team manager must approve `active`; a single conversation never activates L3.
