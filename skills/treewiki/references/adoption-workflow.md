# TreeWiki adoption

Inspect the repository and run read-only upgrade status before changing structure. Preserve existing Markdown IDs, provenance, configuration, ACL metadata, and inactive hooks. Build maps first, then typed documents, vocabulary, validation, and only approved indexes.

For a previous installation, present a plan that separately covers name compatibility, schema migration, installed-skill refresh, hook deduplication, memory-layout migration, and index rebuilding. Dry run first; after approval apply only the selected stages, validate, and retain compatibility shims through 0.1.x. Do not remove legacy files automatically.

Bootstrap asks once about local embeddings. A yes enables local execution and BM25; a no disables it. Remote processing requires separate permission.
