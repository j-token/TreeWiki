# LMWiki

[English](README.md) | [한국어](README.ko.md)

AI coding agents can add code faster than a team can keep documentation current. LMWiki keeps repository maps, contracts, decisions, runbooks, layered memory, personas, and validation links connected to the code.

LMWiki is distributed as one Agent Skill. `$lmwiki` selects a bootstrap, adoption, change, audit, memory, or reindex mode from the repository state and the request. Detailed rules are loaded only when that mode needs them.

During the first LMWiki setup, the skill asks once whether to enable embeddings and the local SQLite BM25 location index. It stores the answer in `.knowledge/config.yml`; later runs reuse it without asking again.

## What it manages

- `AGENTS.md` files point agents to code areas, active contracts, and validation commands.
- Markdown frontmatter stores stable IDs, document types, status, topics, scope, and typed relationships.
- Controlled vocabulary maps aliases such as `auth` and `login` to one topic key.
- The glossary maps repository-specific terms to descriptions so people and AI agents name the same thing consistently.
- Validation catches duplicate IDs, broken links, invalid lifecycle dependencies, and active contracts without evidence.
- Stop hooks emit L0 raw capture, L1 facts, and L2 work scenes in order.
- L3 is emitted only after code checks the evidence threshold for a durable persona.
- At completion, commit, push, or pull-request boundaries, the agent asks once per work unit whether to create a runbook and drafts one only after the user opts in.
- User, team, role, and agent policies filter retrieval before ranking.
- Read-only `query` commands are separate from mutation-capable `manage` commands.
- When embeddings are enabled, a local SQLite FTS5/BM25 index finds a broad set of related document locations without replacing the Markdown source.

## Install

Install the skill with the open [Skills CLI](https://github.com/vercel-labs/skills):

```powershell
npx skills add j-token/lmwiki --skill lmwiki
```

Install the global Codex hook once from the installed skill or this checkout:

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki/scripts/install_global_hooks.py --fallback-repository C:\path\to\central-wiki
```

For a global Codex installation:

```powershell
npx skills add j-token/lmwiki --skill lmwiki -g -a codex -y --copy
```

## Use

Use the skill for initial setup:

```text
Use $lmwiki to initialize this repository and migrate its existing documentation.
```

Use the same skill for an existing repository change:

```text
Use $lmwiki to update this authentication flow and keep its contracts and runbooks current.
```

The root `SKILL.md` contains mode selection and shared safety boundaries. Adoption, access control, metadata, memory, lifecycle, and embedding details stay in direct references and are loaded only when relevant.

## Document model

LMWiki uses eight document types.

| Type | Purpose |
| --- | --- |
| `map` | Connect code areas to documents and validation entry points |
| `contract` | Record behavior and constraints the system must preserve |
| `decision` | Record a choice, its reason, and replacement history |
| `runbook` | Record operational and recovery procedures |
| `concept` | Explain repository-specific terms and mechanisms |
| `reference` | Hold generated or external reference material |
| `memory` | Store L0–L2 conversation and working memory |
| `persona` | Store L3 durable collaboration preferences backed by multiple sources |

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

Memory documents also declare their level and access policy:

```yaml
memory:
  level: l2
  subject: project:repository
  confidence: 0.8
access:
  visibility: team
  owner: user:owner
  team: team:repository
  grants:
    - subject: agent:lmwiki
      permissions: [read]
```

## Repository layout

The skill creates and maintains this layout in a target repository:

```text
AGENTS.md
.knowledge/
├── config.yml
├── purpose.md
├── schema.md
├── principals.yml
├── index/
│   └── .gitignore
├── hooks/
│   └── state/
│       └── .gitignore
└── private-memory/
    ├── l0/
    ├── l1/
    ├── l2/
    └── l3/
docs/
├── contracts/
├── decisions/
├── runbooks/
├── concepts/
├── references/
├── memory/
│   └── l2/
└── vocabulary/
    ├── topics.yml
    └── glossary.yml
```

The root map should reach each major code area within two map links. Local maps add regional details without copying the root rules.

## Memory and access

- L0 preserves raw conversation evidence.
- L1 stores one fact, preference, constraint, or event.
- L2 restores a project or task scenario.
- L3 stores a persona only after at least two independent L1 or L2 sources support it.

Memory capture defaults to `hook`. A Codex `Stop` hook emits L0→L1→L2 in order. Code emits the L3 review only after finding at least two active L1/L2 sources for the same subject. The final stage reviews completion, commit, push, and pull-request signals. When a signal exists, the agent asks once per work unit whether to keep a runbook and creates a `draft` only after the user opts in.

Private and restricted memory stays under the Git-ignored `.knowledge/private-memory/` path. Frontmatter ACLs control cooperative agent retrieval; they do not prevent a person with repository access from reading tracked files.

The installer writes the hook definition and runner once to global Codex paths `~/.codex/hooks.json` and `~/.codex/hooks/lmwiki_hook.py`. It uses the nearest repository with `.knowledge/config.yml`, or the central wiki selected during installation when the current task has no local LMWiki repository. Review and trust the global hook with `/hooks` in Codex before it can run. Set `hooks.execution` to `same_thread` or `agent`; agent mode requests delegation first and falls back to the current thread when the runtime cannot delegate.

## Query and manage

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki/scripts/knowledge_cli.py query search <repository-root> "authentication" --principal user:owner --team team:repository
python skills/lmwiki/scripts/knowledge_cli.py query glossary <repository-root> "workspace" --principal user:owner --team team:repository
python skills/lmwiki/scripts/knowledge_cli.py query graph <repository-root> --principal user:owner --team team:repository
```

`query search`, `read`, `list`, `graph`, and `glossary` never write files. `query glossary` lists all entries when the term is omitted, or matches against terms and descriptions when it is provided. `manage validate` is also read-only and checks missing terms, missing descriptions, and duplicate terms. `manage sync`, `reindex`, and `migrate` require a subject listed in `access_control.managers`; they also require `--apply` before mutating repository state.

Search deliberately favors recall over a short, precise answer. With embeddings enabled it expands vocabulary aliases, prefixes, and Korean bigrams, retrieves up to 24 BM25 candidates, follows one relation hop, and returns up to 12 locations. Each result contains only `path`, `id`, `rank`, `via`, and `engine`; the LLM must use `query read` to inspect a selected document.

## Optional embeddings

During initial setup, LMWiki waits for an explicit yes or no before creating the structure. A yes enables local embeddings and SQLite BM25 by default. A no disables both while retaining metadata, vocabulary, keyword, path, and relationship retrieval. The answer is stored in `.knowledge/config.yml`, so later invocations do not ask again.

Remote document transfer defaults to disabled. Documents marked `local_only` stay local, and documents marked `deny` do not enter the chunk manifest. Markdown remains the source of truth; the vector index can be deleted and rebuilt.

The included index scripts create provider-neutral JSONL chunks and a local SQLite FTS5/BM25 database. The database is enabled only with embeddings, is ignored by Git, and can be deleted and rebuilt. ACL-allowed document IDs are selected before BM25 ranking. Model selection and vector storage follow the repository's existing stack. LMWiki does not invent a model ID or switch remote providers after a failure.

## Validate

The scripts require Python and PyYAML. Use `python`, not `python3`.

Create a new structure from this repository checkout:

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki/scripts/bootstrap_lmwiki.py <repository-root> --embedding local
```

Use `--embedding disabled` when the initial answer is no.

Validate an existing LMWiki repository:

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki/scripts/validate_knowledge.py <repository-root>
```

Build the chunk manifest and SQLite search index when embeddings are enabled:

```powershell
$env:PYTHONUTF8='1'
python skills/lmwiki/scripts/build_embedding_index.py <repository-root>
python skills/lmwiki/scripts/build_search_index.py <repository-root>
```

## Current limits

- The embedding builder produces chunks and hashes. Repository-specific code still connects those chunks to a model and vector store.
- SQLite retrieval depends on Python's bundled SQLite having FTS5 support. It returns candidate locations, not snippets or generated answers.
- The default review warning is 180 days. A date warning never archives a document automatically.
- PyYAML is the only Python dependency.
- Git-hosted ACL metadata cannot provide confidentiality to people who can read the repository; private storage or an authenticated external backend is required for enforcement.

The metadata fields and retrieval thresholds are early defaults. They will change after more repositories expose where the rules are too strict or too loose.
