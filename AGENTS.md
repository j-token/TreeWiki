---
id: MAP-ROOT-001
title: TreeWiki repository maintenance map
type: map
status: active
authority: normative
topics:
- repository-knowledge-management
summary: Maps canonical TreeWiki sources to generated plugin outputs, build order,
  and validation boundaries.
applies_to:
- '**'
read_when:
- Start of repository work
- Before changing the TreeWiki skill, plugin, adapters, release, or governed documentation
relations:
- type: related_to
  target: EXPLANATION-KNOWLEDGE-SYSTEM-001
reviewed: '2026-08-08'
created_at: null
modified_at: '2026-08-20T11:14:16.207231Z'
verified_at: null
revision: 8
history_ref: .knowledge/document-history/MAP-ROOT-001.jsonl
governance:
  owner: user:owner
  reviewers:
  - user:owner
  review_cadence_days: 90
  source_of_truth: AGENTS.md
  last_source_check: '2026-08-20'
  duplicate_of: null
  retirement_reason: null
  scope: standards
embedding:
  mode: local_only
  content: full
---

# TreeWiki repository maintenance map

## Scope

- Canonical skill, Python core, Agent Plugin, Claude adapter, release artifacts, governed documentation, and tests.

## Sources and outputs

- `skills/treewiki/`: canonical skill, Python core, templates, references, and release manifest; edit this copy first.
- `plugins/treewiki/src/`: Agent Plugin stdio and HTTP MCP sources.
- `plugins/treewiki/dist/`, `plugins/treewiki/skills/treewiki/`, and runtime manifests: generated outputs.
- `plugins/treewiki-claude/`: Claude plugin manifest and routing; `runtime/` is generated from the canonical Python core.
- `tests/` and `plugins/treewiki/tests/`: Python contracts and Agent Plugin/MCP regression coverage.
- `docs/references/treewiki-knowledge-system.md` and `docs/vocabulary/`: governed product contract and vocabulary.

## Change flow

- Search governed knowledge and preferences, then read the affected source and tests.
- Change shared skill or Python behavior only under `skills/treewiki/`; do not hand-edit adapter copies.
- Change MCP or HTTP behavior under `plugins/treewiki/src/` and its tests.
- Run the plugin build before computing the release manifest when TypeScript sources change.
- Build the release manifest, then adapter bundles; sync `.agents/skills/treewiki` only through an exact `runtime` upgrade plan.
- Finalize changed managed Markdown through its exact document plan before validation.

## Validation

```powershell
$env:PYTHONUTF8='1'
python -m unittest discover -s tests
Push-Location plugins/treewiki
npm run check
Pop-Location
python skills/treewiki/scripts/build_adapter_bundles.py . --check
python skills/treewiki/scripts/build_release_manifest.py skills/treewiki --check
python skills/treewiki/scripts/knowledge_cli.py manage validate . --strict-warnings
```

## Guardrails

- Preserve unrelated work in the dirty tree and review generated diffs before handoff.
- Never hand-edit generated plugin skill/runtime copies, bundles, or manifests.
- `build_adapter_bundles.py` atomically replaces generated adapter copies; edit and verify the canonical skill first.
- Global skill, Claude alias, hook, migration, and index changes require separately scoped approval.
- Keep managed bodies near 50 lines; split independent topics behind a nearest `AGENTS.md` map.
- Preserve stable IDs and local history ledgers, and report glossary impact on every governed-document change.
- Keep detailed lifecycle ledgers under ignored `.knowledge/document-history/`; Git stores only shared lifecycle summaries.
