---
name: treewiki
description: TreeWiki applies repository maps, typed Markdown, governed L0–L3 memory, ACL-first retrieval, local BM25, and approval-based management.
---

# TreeWiki

## 0. Start with retrieval and upgrade awareness

When `.knowledge/config.yml` exists in or above the work path, apply this skill even when `$treewiki` is not named. Before meaningful repository work, read the nearest `AGENTS.md`, configuration, Git state, and run ACL-filtered `query search` for the request. Read returned candidates directly. Separately run `query preferences` for the caller's active Persona and collaboration preferences.

Run read-only `upgrade-status` before a write when the installed release, schema, hook, or copy may be stale. Show its guide; do not apply a migration, reinstall, cleanup, or reindex without approval. GitHub latest-release discovery is opt-in; offline is the default and unknown is not an error.

## 1. Choose a mode

| Situation | Mode | Required reference |
| --- | --- | --- |
| No structure | bootstrap | [adoption](references/adoption-workflow.md) |
| Existing docs or partial structure | adopt / repair | [adoption](references/adoption-workflow.md), [upgrade](references/upgrade-guide.md) |
| Code or documentation change | change | [change](references/change-and-audit.md) |
| Read-only inspection | audit | [change](references/change-and-audit.md) |
| Memory or Persona | memory | [memory](references/memory-and-persona.md), [lifecycle](references/hook-lifecycle.md) |
| Derived index only | reindex | [embedding](references/embedding-retrieval.md) |

Use [command boundaries](references/command-boundaries.md) for every command; use the linked single-depth reference only when relevant.

## 2. Common safety contract

- Markdown/frontmatter is authoritative. ACL filtering occurs before ranking.
- Queries, `manage validate`, and `manage upgrade-status` are read-only. `scaffold`, `generate-context`, `retrieval-gap`, `sync`, `reindex`, `upgrade`, `l3-review`, and `memory-finalize` need their specified authority, an exact plan where supported, user approval, and `--apply`; legacy `migrate` only directs callers to the versioned upgrade flow.
- L0 alone is local and Git-ignored. Approved shared L1–L3 live under `docs/memory/l1`, `l2`, and `l3`; never copy raw L0 text there.
- Capture is explicit. Stop hooks never capture or save memory. Ask at a real completion candidate, then act only after the user's next independent, short confirmation.
- Classify L3 as `knowledge` (`fact`, `information`, `rule`) or `persona` (`preference`). Use type-specific thresholds and agent-declared `supports_claim` convergence, while code verifies exact evidence IDs, independent top-level provenance, work units, ACL, and digest. Create only `proposed`; never activate without a separate explicit review. Read [memory](references/memory-and-persona.md) for thresholds.
- Finalize every managed document through the lifecycle ledger. Share only code-owned lifecycle summaries in Markdown; keep actor, plan, reason, and hash-chain events append-only under ignored `.knowledge/document-history/`. Read [metadata](references/metadata-schema.md) before authoring a managed document.
- Keep managed Markdown atomic: frontmatter does not count toward the body budget, 50 body lines is the target, and 80 lines or about 1,000 tokens is the hard limit. When a document grows, read [composition](references/document-composition.md) and split independent topics behind a directory `AGENTS.md` map; use `composition.size_exception` only with a concrete reason.
- Codex owns the native MCP tool, result, and approval presentation. The MCP server returns concise text plus structured data, while ACL, eligibility, evidence digest, approval, exact plan ID, transaction, and ledger decisions remain in the bundled Python core. Never treat host presentation state as authoritative knowledge state.
- At a completion, commit, push, PR, deployment, or recovery boundary, offer a runbook once per work unit. Create it only after `만들기`/`Create`; initial status is `draft`.
- Do not invent providers, model IDs, or subagent models. For bounded independent research, prefer `luna` when the runtime exposes it for GPT and `sonnet` when it exposes it for Claude; otherwise use that runtime's available default and report the fallback. The root agent verifies each delegated result with paths and command/test evidence. See [agent research](references/agent-research.md).

## 3. Bootstrap and indexes

Only when embedding selection is absent or invalid, ask once whether to enable local embeddings and SQLite BM25. Record explicit yes as local and explicit no as disabled. Never infer no response as disabled; never choose remote processing without permission.

## 4. Commands

```powershell
$env:PYTHONUTF8='1'
python <treewiki-path>/scripts/knowledge_cli.py query search <repository-root> "<request>" --principal user:<id> --team team:<id>
python <treewiki-path>/scripts/knowledge_cli.py query preferences <repository-root> --principal user:<id> --team team:<id>
python <treewiki-path>/scripts/knowledge_cli.py query l3-candidates <repository-root> --principal user:<id> --team team:<id>
python <treewiki-path>/scripts/knowledge_cli.py query history <repository-root> --id <stable-id> --principal user:<id> --team team:<id>
python <treewiki-path>/scripts/knowledge_cli.py query gap-report <repository-root> --status open --principal user:<id> --team team:<id>
python <treewiki-path>/scripts/knowledge_cli.py query governance-report <repository-root> --principal user:<id> --team team:<id>
python <treewiki-path>/scripts/knowledge_cli.py manage scaffold <repository-root> how_to --id <stable-id> --title <title> --output <path> --source-path <path> --principal user:<id> --team team:<id>
python <treewiki-path>/scripts/knowledge_cli.py generate-context <repository-root> --commit <sha> --path <path> --principal user:<id> --team team:<id>
python <treewiki-path>/scripts/knowledge_cli.py manage document-finalize <repository-root> --principal user:<id> --team team:<id>
python <treewiki-path>/scripts/knowledge_cli.py manage document-move <repository-root> <stable-id> --to <new-path> --principal user:<id> --team team:<id>
python <treewiki-path>/scripts/knowledge_cli.py manage validate <repository-root>
```

## 5. Completion

Report changed paths, applied maps/contracts, validation evidence, upgrade state, and glossary impact. If the request is genuinely complete, ask once: `이 작업을 마친 것으로 보고 기억을 저장할까요?` Offer `저장하기` and `계속 작업`; do not create memory in that turn.
