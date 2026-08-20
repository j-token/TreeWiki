---
id: MAP-ROOT-001
title: Repository knowledge map
type: map
status: active
authority: normative
topics:
  - repository-knowledge-management
summary: Connects repository areas to TreeWiki contracts and validation entry points.
applies_to:
  - "**"
read_when:
  - Start of repository work
relations: []
reviewed: 2026-08-08
created_at: 2026-08-08T00:00:00Z
modified_at: 2026-08-08T00:00:00Z
verified_at: null
revision: 1
history_ref: .knowledge/document-history/MAP-ROOT-001.jsonl
governance:
  owner: user:owner
  reviewers:
    - user:owner
  review_cadence_days: 90
  source_of_truth: skills/treewiki/assets/AGENTS.md
  last_source_check: YYYY-MM-DD
  duplicate_of: null
  retirement_reason: null
  scope: standards
embedding:
  mode: local_only
  content: full
---

# Repository knowledge map

## Scope

- Entire repository.

## Entry points

- Product and business map: `docs/AGENTS.md`
- TreeWiki skill source: `treewiki/skills/treewiki/`
- Glossary: `docs/vocabulary/glossary.yml`

## Validation

```powershell
$env:PYTHONUTF8='1'
python treewiki/skills/treewiki/scripts/knowledge_cli.py manage validate .
```

## Change rules

- Search and read applicable maps/contracts before changing managed knowledge.
- Run `query preferences` separately from request search.
- Keep managed bodies near 50 lines; split independent topics into a folder with a nearest `AGENTS.md` map before exceeding the configured hard limit.
- L0 is local-only; approved L1–L3 use shared `docs/memory/l1`–`l3` paths.
- Stop hooks never save memory. Ask at completion and process only the next independent confirmation.
- Review glossary impact and report add, description update, or no change.
