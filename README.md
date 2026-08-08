# TreeWiki

TreeWiki keeps repository maps, contracts, decisions, runbooks, and governed memory usable by people and coding agents. It is distributed as one Agent Skill: `$treewiki`.

## Release and compatibility

The first TreeWiki release is **0.1.0**. It introduces the TreeWiki name, read-only upgrade diagnosis, explicit memory sharing boundaries, and the upgrade guide. The legacy `LMWiki` name is a compatibility-only alias for existing installs during 0.1.x; its shim is removed in **0.2.0**. Historical IDs and provenance containing that name are never rewritten.

Before a mutating operation, run the read-only status check and follow its guide:

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py manage upgrade-status <repository-root> --principal user:<id> --team team:<id> --offline
```

Status compares config schema, skill release and manifest/hash, vendored/global copies, hook registration, migration needs, indexes, and compatibility shims separately. It reports unknown remote release state rather than guessing. `--apply` is always separate, requires user approval, and does not delete legacy files automatically.

## Install and use

```powershell
npx skills add j-token/treewiki --skill treewiki
```

Use `$treewiki` for a repository task. It loads the applicable maps and contracts, reads relevant source documents after ACL-filtered search, and validates changes. For independent research streams such as naming impact, contract discovery, or validation, it may delegate bounded work to subagents; the root agent verifies ACL, evidence, and results.

```text
Use $treewiki to adopt this repository and preserve its existing documentation.
Use $treewiki to update this authentication flow and its related contracts.
```

## Memory and sharing

| Level | Purpose | Location | Git policy |
| --- | --- | --- | --- |
| L0 | Raw conversation and tool evidence | `.knowledge/private-memory/l0/` | local and ignored |
| L1 | Atomic fact, preference, constraint, or event | `docs/memory/l1/` after approval | shared and tracked |
| L2 | Reusable project or work context | `docs/memory/l2/` after approval | shared and tracked |
| L3 | Durable team rule or Persona | `docs/memory/l3/` after approval | shared and tracked |

Capture is explicit. A Stop hook never stores memory. When work is genuinely complete, the agent asks whether to save it; only a separate, short confirmation begins L0 capture and proposed L1–L3 processing. Shared documents must carry author, approver, opaque source reference/hash, source-machine identifier, and status. Git tracking never means automatic stage, commit, or push.

TreeWiki actively proposes an L3 candidate once two or more independent top-level provenance sources and work units support the same `(subject, scope, claim_key, claim_value)`. It reports missing evidence when only one exists, never merges unrelated or conflicting claims, and creates L3 as `proposed`; an explicit user or team-manager approval is required for `active`.

## Document model

TreeWiki uses typed Markdown with stable IDs: `map`, `contract`, `decision`, `runbook`, `concept`, `reference`, `memory`, and `persona`. `AGENTS.md` maps an area to its contracts and validation entry points. Markdown/frontmatter remains authoritative; indexes are recreatable derivatives.

## Query, validation, and optional indexes

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py query search <repository-root> "authentication" --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py query preferences <repository-root> --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py query l3-candidates <repository-root> --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py manage validate <repository-root>
```

Initial setup asks once whether to enable local embeddings and SQLite BM25. No document is sent externally without explicit permission. GitHub latest-release checks are opt-in and default to offline/unknown.

## Upgrade guide

1. Run `upgrade-status`; inspect every reported reason and the generated guide.
2. Run the migration dry run. It lists config, skill copy, hook, and index actions independently.
3. Approve only the required `--apply` action; make a backup or use Git first.
4. Run `manage validate`, then regenerate approved derived indexes if requested.
5. Remove a compatibility shim only after a TreeWiki install and regression checks succeed. Delete caches only when the guide classifies them as recreatable; remove worktrees with `git worktree remove`, never by deleting their directories.

See [`skills/treewiki/SKILL.md`](skills/treewiki/SKILL.md) and its references for the normative workflow.
