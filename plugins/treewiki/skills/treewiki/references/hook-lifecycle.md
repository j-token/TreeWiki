# Memory and runbook lifecycle

Codex Stop means a response ended, not that work ended. A Stop hook never captures, distills, shares, or activates memory.

At a genuine completion candidate, verify that no direct work or user choice remains, then ask once whether to save memory. Only a later independent short confirmation starts: L0 local capture; proposed shared L1 and L2; L3 candidate evaluation; then approved `manage memory-finalize --apply` validation/indexing. New instructions attached to an affirmative response mean continue working, not save.

Memory consent is separate from sharing approval and from runbook consent. At completion, commit, push, PR, deployment, recovery, or another handoff boundary, ask once per work unit whether to create a runbook. Only `Create`/`만들기` creates a `draft`; human verification alone may make it `active`.

Inactive legacy hook files do not authorize activation. Migration must detect duplicate old/new registrations and leave exactly one explicitly approved active registration.
