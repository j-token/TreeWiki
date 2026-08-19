# TreeWiki

[한국어](./README.ko.md)

TreeWiki keeps repository maps, contracts, decisions, runbooks, document history, and governed memory usable by people and coding agents. Version 0.2.1 ships one Python core with thin Agent Plugin, Codex, and Claude Code adapters.

## Release and compatibility

The current TreeWiki release is **0.2.1**. The legacy `LMWiki` shim is removed, while historical IDs and provenance containing that name remain untouched. Config v4 and memory layout v2 add typed L3 knowledge/persona paths and stable-ID document-history sidecars.

Before a mutating operation, run the read-only status check and follow its guide:

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py manage upgrade-status <repository-root> --principal user:<id> --team team:<id> --offline
```

Status compares runtime, config, document history, memory layout, indexes, adapters, Claude alias, and hook state separately. It reports unknown remote release state rather than guessing. Upgrade defaults to dry-run and binds apply to an exact plan ID.

## Install and use

The independent Codex skill remains available for CLI-only use:

```powershell
npx skills add j-token/treewiki --skill treewiki
```

Use `$treewiki` for a repository task. It loads the applicable maps and contracts, reads relevant source documents after ACL-filtered search, and validates changes. For independent research streams such as naming impact, contract discovery, or validation, it may delegate bounded work to subagents; the root agent verifies ACL, evidence, and results.

## Plugin installation

### Claude Code

Add the TreeWiki marketplace and install the plugin from inside Claude Code:

```text
/plugin marketplace add j-token/treewiki
/plugin install treewiki@treewiki-marketplace
```

The plugin's namespaced fallback is `/treewiki:route`. To install the exact `/treewiki` standalone entry point, run the alias installer from a TreeWiki checkout. It defaults to a dry run; inspect the printed plan ID and apply that exact plan only after choosing `user` or `project` scope:

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py manage setup-claude-alias <repository-root> --scope user --plugin-root plugins/treewiki-claude --principal user:<id>
python skills/treewiki/scripts/knowledge_cli.py manage setup-claude-alias <repository-root> --scope user --plugin-root plugins/treewiki-claude --plan-id <PLAN_ID> --apply --principal user:<id>
```

After installation, normal use stays at one command:

```text
/treewiki [natural-language request]
```

Use `--scope project` instead for a repository-local alias. If both scopes exist TreeWiki reports `ALIAS_SHADOWED` and never deletes either copy.

### Codex / Agent Plugin

The default installation is the versioned GitHub marketplace plugin. It follows [Agent Plugins 1.0.0](https://agent-plugins.org/specification); Codex metadata is a thin compatibility adapter over the same portable package.

```powershell
codex plugin marketplace add j-token/treewiki --ref v0.2.1
codex plugin add treewiki@treewiki-marketplace
```

Start a new Codex task and ask it to check TreeWiki for the current repository. Codex uses its native MCP tool, result, and approval surfaces to list bindings, inspect Overview, run ACL Search, read document History, review knowledge/persona L3 candidates, and plan upgrades. Binding changes, L3 decisions, and repository-local upgrades always make a dry-run plan first and apply only after explicit approval with the exact plan ID and digest. Global skills, hooks, and governed-memory upgrades remain chat-guided operations.

The committed stdio MCP, Python core, PyYAML runtime, and skill need neither `npm install` nor `pip install` after installation. Repository tools accept only an approved `bindingId`; callers cannot replace the repository or ACL identity per request. See [`plugins/treewiki/README.md`](plugins/treewiki/README.md).

The optional HTTP transport exposes the same plain MCP tools without a custom App resource. Tunnels and Developer mode are development/deployment concerns documented separately in [`docs/chatgpt-http-development.md`](docs/chatgpt-http-development.md); they are not the Codex installation path.

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
| L3 knowledge | Durable fact, information synthesis, or rule | `docs/memory/l3/knowledge/` after approval | shared and tracked |
| L3 persona | Durable user preference | `docs/memory/l3/persona/` after approval | shared and tracked |

Capture is explicit. A Stop hook never stores memory. When work is genuinely complete, the agent asks whether to save it; only a separate, short confirmation begins L0 capture and proposed L1–L3 processing. Shared documents must carry author, approver, opaque source reference/hash, source-machine identifier, and status. Git tracking never means automatic stage, commit, or push.

TreeWiki supports exact and convergent evidence. Facts need one authoritative source or two independent sources; information needs two converging observations; rules need one official/explicit declaration or two repeated outcomes; preferences need one explicit user declaration or two independent choices followed by confirmation. Automatic processing stops at `proposed`. A successful new candidate emits one `L3_CANDIDATE_CREATED` notice; activation, rejection, and superseding require a separate exact review plan.

## Document model

TreeWiki uses typed Markdown with stable IDs. Managed documents carry `created_at`, `modified_at`, `verified_at`, `revision`, and `history_ref`; the adjacent `<stable-id>.history.jsonl` ledger records semantic changes. Source verification changes `verified_at` without increasing the semantic revision. Markdown/frontmatter and ledgers remain authoritative; indexes are recreatable derivatives.

OKF v0.2 is an import/export compatibility layer, not TreeWiki's native storage schema. Export maps lifecycle timestamps, verification events, evidence sources, and TreeWiki status without discarding the native metadata extension.

## Query, validation, and optional indexes

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py query search <repository-root> "authentication" --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py query preferences <repository-root> --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py query l3-candidates <repository-root> --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py query history <repository-root> --id DOC-ID --principal user:owner --team team:product
python skills/treewiki/scripts/knowledge_cli.py manage document-finalize <repository-root> --principal user:owner
python skills/treewiki/scripts/knowledge_cli.py manage document-move <repository-root> DOC-ID --to docs/new-path.md --principal user:owner
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
