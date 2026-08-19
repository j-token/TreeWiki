# Optional embeddings and retrieval

Markdown/frontmatter is authoritative. Local SQLite BM25 and vector data are recreatable derivatives under `.knowledge/index/`. Use local execution only unless external transmission is explicitly approved; `private`, `restricted`, and `agent` documents never leave the machine.

Retrieve locations only: ACL filter, query expansion, BM25 candidate collection, one-hop relation expansion, then direct source reading. A missing/stale index never authorizes automatic rebuild; use approved `manage reindex --apply`. Do not infer a provider or model ID. GitHub latest-release checks are independent of embeddings and opt-in.
