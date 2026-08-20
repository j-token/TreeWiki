# Optional embeddings and retrieval

Markdown/frontmatter is authoritative. Local SQLite BM25 and vector data are recreatable derivatives under `.knowledge/index/`. Use local execution only unless external transmission is explicitly approved; `private`, `restricted`, and `agent` documents never leave the machine.

Retrieve locations only: ACL filter, query expansion, BM25 candidate collection, one-hop relation expansion, then direct source reading. A missing/stale index never authorizes automatic rebuild; use approved `manage reindex --apply`. Do not infer a provider or model ID. GitHub latest-release checks are independent of embeddings and opt-in.

Record retrieval failures in the local append-only `.knowledge/index/retrieval-gaps.jsonl` ledger. Valid reasons are `no_result`, `acl_hidden`, `stale`, and `ambiguous`; resolution appends a new event instead of rewriting history. Deduplicate repeated events within the same work unit. An `acl_hidden` event records only the failure category and request-safe metadata—never a hidden document ID, title, path, excerpt, or body.

Federated retrieval may combine a central standards repository with repository-local overlays only when every binding independently authorizes the same principal and team. Apply ACL before returning candidates from each binding. Divergent copies or stable-ID collisions are explicit conflicts and are never merged automatically.
