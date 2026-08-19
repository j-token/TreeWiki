# Upgrade guide

TreeWiki 0.1.0 separates a read-only diagnosis from every mutation. The first release retains the prior installation name only as a compatibility shim; remove that shim in 0.2.0 after a TreeWiki install and regression checks succeed.

## Diagnose

Run `upgrade-status` without network access by default. It reports each dimension independently: supported config schema, release/manifest/hash, vendored and global skill copies, hook runner/registration, memory layout, derived indexes, and compatibility artifacts. A newer remote release is checked only when the user explicitly opts in to a GitHub latest-release check. If it cannot be checked, report `unknown`, never an inferred version.

```powershell
$env:PYTHONUTF8='1'
python skills/treewiki/scripts/knowledge_cli.py manage upgrade-status <repository> --principal user:<id> --team team:<id> --offline --json
```

Select the same stages and approvals during status and apply. They are inputs to the plan ID; changing any of them requires a new status run. Global targets are excluded by default. Add `--approve-global-skill` or `--approve-global-hook` only after separately reviewing that exact global target. Use `--stage index` only when the reported index contract or corpus digest is stale.

## Plan, approve, apply

1. Read the generated guide and review the exact affected paths.
2. Run the migration dry run; it must not edit config, copies, hooks, or indexes.
3. Confirm a backup or clean Git recovery point.
4. After user approval, apply only the selected migration stage with `--apply`.
5. Run `manage validate`; rebuild a derived index only with separate approval.

```powershell
# Read-only plan for selected repository stages
python skills/treewiki/scripts/knowledge_cli.py manage upgrade-status <repository> --principal user:<id> --team team:<id> --offline --stage config,skill --json

# Apply exactly the returned plan ID with the same inputs
python skills/treewiki/scripts/knowledge_cli.py manage upgrade <repository> --principal user:<id> --team team:<id> --offline --stage config,skill --plan-id sha256:<digest> --apply --json
```

Legacy private L1–L3 is never shared merely because config is upgraded. Review the status dispositions locally. For every eligible document, repeat `--approve-memory-id <stable-id>` on both commands. If metadata or sensitivity review is required, also supply the same regular, non-symlink UTF-8 YAML with `--memory-approval-file`; the file's exact ID set must equal the repeated ID flags. The approval contents and local path are not reflected in public status output. `private`, `restricted`, secret, device-specific, or third-party data remains blocked until a distinct sensitivity review explicitly clears it.

The index stage computes its contract from the configured SQLite path, query/result modes, builder hash, and the managed-document corpus digest. A current index is skipped. A missing or stale index is rebuilt only in the selected, approved transaction and only under `.knowledge/index/**`.

Never downgrade an unsupported newer config. Never delete an old copy, shim, worktree, private memory, decision, spec, or prompt record as an upgrade side effect. Classify `__pycache__`, `*.pyc`, and indexes as recreatable only after checking their scope. Use `git worktree remove` for registered worktrees.

## Recovery

If a stage fails, keep the status report, transaction journal, `backup_ready` records, and recovery instructions, then rerun diagnosis. Restore the selected stage from Git or the recorded backup only when its hash precondition still matches; do not attempt a blind reverse migration. A partial result remains incomplete until validation and action-specific verification succeed.
