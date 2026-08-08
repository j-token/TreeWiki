# Command boundaries

`query search`, `read`, `list`, `graph`, `glossary`, `glossary-candidates`, `preferences`, `l3-candidates`, `upgrade-status`, and `manage validate` are read-only. Apply caller `user`, `team`, optional `role`, and optional `agent` ACL before retrieval.

`manage sync`, `reindex`, `memory-finalize`, and `migrate` require a configured manager, user approval, and `--apply`; default output is a plan. `migrate` never downgrades a newer schema. Syncing a vendored or global skill copy is an explicit migration action and never deletes target files. Latest-release network lookup requires an explicit opt-in flag.

Classify cleanup separately: derived caches may be recreatable, but private memory, specs, decisions, and prompt records are never cache. Check Git status, unmerged commits, and active work before any deletion. Remove registered worktrees with `git worktree remove`; remove legacy shims only after TreeWiki install and regression verification, and not before 0.2.0.
