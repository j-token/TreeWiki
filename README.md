# LMWiki

[English](README.md) | [한국어](README.ko.md)

AI coding agents can add code faster than a team can keep documentation current. LMWiki keeps repository maps, contracts, decisions, runbooks, and validation links in the same Git history as the code.

LMWiki is distributed as two Agent Skills. `lmwiki-builder` creates or migrates the knowledge structure. `lmwiki-steward` handles routine changes after setup.

## What it manages

- `AGENTS.md` files point agents to code areas, active contracts, and validation commands.
- Markdown frontmatter stores stable IDs, document types, status, topics, scope, and typed relationships.
- Controlled vocabulary maps aliases such as `auth` and `login` to one topic key.
- Validation catches duplicate IDs, broken links, invalid lifecycle dependencies, and active contracts without evidence.
- Optional embedding manifests add semantic retrieval without replacing the Markdown source.

## Install

Install both skills with the open [Skills CLI](https://github.com/vercel-labs/skills):

```powershell
npx skills add j-token/lmwiki --skill lmwiki-builder --skill lmwiki-steward
```

For a global Codex installation:

```powershell
npx skills add j-token/lmwiki --skill lmwiki-builder --skill lmwiki-steward -g -a codex -y --copy
```

Each skill can also be installed separately.

```powershell
npx skills add j-token/lmwiki --skill lmwiki-builder
npx skills add j-token/lmwiki --skill lmwiki-steward
```

## Use

Use the builder for a new or existing repository that does not have an LMWiki structure:

```text
Use $lmwiki-builder to initialize this repository and migrate its existing documentation.
```

Use the steward after setup:

```text
Use $lmwiki-steward to update this authentication flow and keep its contracts and runbooks current.
```

| Skill | Work |
| --- | --- |
| `lmwiki-builder` | New setup, existing document migration, incomplete structure repair, embedding policy, and the first index |
| `lmwiki-steward` | Code and document changes, audits, lifecycle updates, relationship repair, and reindexing |

The steward does not create a missing LMWiki structure. It reports that the builder is required.

## Document model

LMWiki uses six document types.

| Type | Purpose |
| --- | --- |
| `map` | Connect code areas to documents and validation entry points |
| `contract` | Record behavior and constraints the system must preserve |
| `decision` | Record a choice, its reason, and replacement history |
| `runbook` | Record operational and recovery procedures |
| `concept` | Explain repository-specific terms and mechanisms |
| `reference` | Hold generated or external reference material |

Each managed Markdown file starts with YAML frontmatter:

```yaml
---
id: CONTRACT-AUTH-001
title: Authentication token contract
type: contract
status: active
authority: normative
topics:
  - authentication
summary: Defines token issue, validation, and expiry behavior.
applies_to:
  - src/auth/**
read_when:
  - changing authentication code
relations:
  - type: verified_by
    target: tests/auth/token.test.ts
reviewed: 2026-08-03
embedding:
  mode: local_only
  content: full
---
```

## Repository layout

The skills create and maintain this layout in a target repository:

```text
AGENTS.md
.knowledge/
└── config.yml
docs/
├── contracts/
├── decisions/
├── runbooks/
├── concepts/
├── references/
└── vocabulary/
    └── topics.yml
```

The root map should reach each major code area within two map links. Local maps add regional details without copying the root rules.

## Optional embeddings

The builder asks once whether the repository should use embeddings. A declined or unanswered choice keeps metadata, vocabulary, path, and relationship search enabled.

Remote document transfer defaults to disabled. Documents marked `local_only` stay local, and documents marked `deny` do not enter the chunk manifest. Markdown remains the source of truth; the vector index can be deleted and rebuilt.

The included index builder creates provider-neutral JSONL chunks. Model selection and vector storage follow the repository's existing stack. The skills do not invent a model ID or switch remote providers after a failure.

## Validate

The scripts require Python and PyYAML. Use `python`, not `python3`.

Create a new structure from this repository checkout:

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki-builder/scripts/bootstrap_lmwiki.py <repository-root> --embedding disabled
```

Validate an existing LMWiki repository:

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki-steward/scripts/validate_knowledge.py <repository-root>
```

Build the chunk manifest when embeddings are enabled:

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki-steward/scripts/build_embedding_index.py <repository-root>
```

## Current limits

- The embedding builder produces chunks and hashes. Repository-specific code still connects those chunks to a model and vector store.
- The default review warning is 180 days. A date warning never archives a document automatically.
- PyYAML is the only Python dependency.

The metadata fields and retrieval thresholds are early defaults. They will change after more repositories expose where the rules are too strict or too loose.
