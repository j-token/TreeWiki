# Bounded agent research

Use subagents only when work can be independently bounded, such as naming impact, contract discovery, repository search, or validation. Do not delegate a single local edit merely to create parallelism.

The delegation prompt states the exact paths, read/write permission, caller ACL principals, question, acceptance evidence, and concise result format. Prefer runtime-advertised `luna` for GPT providers and `sonnet` for Claude providers; if the provider does not expose that capability, select its runtime-provided default and disclose the fallback. Never invent model identifiers.

The root agent remains accountable: it reads or verifies cited `path:line` evidence, checks ACL scope, resolves conflicts, runs relevant validation, and alone decides what changes are applied.
