# Access control

Represent principals as `user:*`, `team:*`, `role:*`, and `agent:*`; filter allowed documents before ranking, graph expansion, preferences, or L3 candidate counting. `private` and `restricted` metadata does not replace repository access controls and stays outside shared tracking when its content is private.

Shared L1–L3 documents require explicit approval metadata. Do not expose L0 text through source references, hashes, diagnostics, or external release checks.
