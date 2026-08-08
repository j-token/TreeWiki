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
- L0 is local-only; approved L1–L3 use shared `docs/memory/l1`–`l3` paths.
- Stop hooks never save memory. Ask at completion and process only the next independent confirmation.
- Review glossary impact and report add, description update, or no change.
