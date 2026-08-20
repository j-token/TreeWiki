---
id: EXPLANATION-KNOWLEDGE-SYSTEM-001
title: TreeWiki knowledge system automation
type: explanation
status: active
authority: informative
topics:
- technical-writing
summary: Defines how TreeWiki turns work evidence into reviewable, governed knowledge
  without bypassing ACL or explicit approval.
relations:
- type: implemented_by
  target: plugins/treewiki/src/server.ts
- type: implemented_by
  target: skills/treewiki/scripts/code_context.py
- type: implemented_by
  target: skills/treewiki/scripts/retrieval_gaps.py
- type: implemented_by
  target: skills/treewiki/scripts/technical_writing.py
- type: implemented_by
  target: skills/treewiki/scripts/document_composition.py
- type: implemented_by
  target: skills/treewiki/scripts/governance_report.py
- type: verified_by
  target: tests/test_technical_writing.py
- type: verified_by
  target: plugins/treewiki/tests/server.test.ts
reviewed: '2026-08-19'
created_at: '2026-08-19T17:25:41.916432Z'
modified_at: '2026-08-20T11:17:32.580552Z'
verified_at: null
revision: 6
history_ref: .knowledge/document-history/EXPLANATION-KNOWLEDGE-SYSTEM-001.jsonl
technical_writing: true
context:
  audience:
  - human
  - agent
  repository: repo:treewiki
  source_commit: null
  source_paths:
  - plugins/treewiki/src/server.ts
  - skills/treewiki/scripts/code_context.py
  - skills/treewiki/scripts/retrieval_gaps.py
  - skills/treewiki/scripts/technical_writing.py
  - skills/treewiki/scripts/document_composition.py
  - skills/treewiki/scripts/governance_report.py
  symbols: []
  generated: false
  generator: null
governance:
  owner: user:owner
  reviewers:
  - user:owner
  review_cadence_days: 90
  source_of_truth: plugins/treewiki/src/server.ts
  last_source_check: '2026-08-19'
  duplicate_of: null
  retirement_reason: null
  scope: standards
access:
  visibility: team
  owner: user:owner
  team: team:repository
  grants: []
embedding:
  mode: local_only
  content: full
---

# TreeWiki knowledge system automation

## Purpose

Make knowledge creation a lifecycle embedded in normal repository work: capture a local signal, create a draft, validate it, obtain the responsible review, publish it, keep it current, and retire it with a replacement.

## Audience

Repository maintainers, documentation owners, and coding agents integrating the Python CLI or native MCP tools.

## Background

TreeWiki treats shared Markdown lifecycle summaries as a collaboration contract and local append-only ledgers as audit records, filters ACL before ranking, and keeps L3 activation behind an exact plan and evidence digest. The automation layer extends those guarantees instead of introducing a second shared knowledge store.

## Core concepts

- Technical document types define required reader-facing sections. `manage scaffold` creates a governed `draft`; it never activates content.
- Managed bodies target 50 lines; oversize documents split into a directory map and independently governed children, with reviewed exceptions reserved for indivisible material.
- `generate-context` binds an immutable Git commit and selected blobs to a deterministic source digest. Unrelated files do not affect the plan.
- Retrieval failures are local append-only evidence. `plan_retrieval_gap` must precede `record_retrieval_gap`, and the ledger never records hidden document titles or bodies.
- Governance metadata names the owner, reviewers, cadence, source of truth, retirement state, and standards or domain scope.
- Federated search uses approved bindings with identical principal and team identities. Repeated stable IDs are returned as conflicts rather than merged.
- Committee approvals accumulate on proposed L3 knowledge until the configured quorum is met. A vote cannot activate content early.
- Shared Markdown carries lifecycle dates and revision; detailed actor, plan, reason, and hash-chain events stay in ignored `.knowledge/document-history/`.

## Alternatives and tradeoffs

Automatically publishing generated documents would reduce friction but would violate TreeWiki's evidence and approval boundaries. Centralizing every repository would simplify search but could cross ACL and private-memory boundaries. TreeWiki therefore keeps detailed context repository-local, permits explicit same-identity overlays, and automates only through a reviewable draft.

## Sources

- `skills/treewiki/scripts/technical_writing.py`
- `skills/treewiki/scripts/document_composition.py`
- `skills/treewiki/scripts/governance_report.py`
- `skills/treewiki/scripts/code_context.py`
- `skills/treewiki/scripts/retrieval_gaps.py`
- `skills/treewiki/scripts/validate_knowledge.py`
- `plugins/treewiki/src/server.ts`
