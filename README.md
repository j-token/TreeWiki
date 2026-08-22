# TreeWiki 0.3

[한국어](README.ko.md)

TreeWiki is a plugin for documenting and retrieving project policies and decisions. Managed Markdown keeps only a stable `id` and `type`; titles, summaries, links, backlinks, and citations are derived from the body.

## Plugins

- `plugins/treewiki` is the canonical Agent Plugin and Codex-compatible package.
- `plugins/treewiki-claude` provides the generated Claude Code `/treewiki` route.
- There is no standalone TreeWiki skill distribution.

Install the Agent Plugin from this repository's marketplace, or install the Claude plugin through the Claude marketplace. Both packages are version `0.3.0`.

## Document model

TreeWiki manages `AGENTS.md` maps, `docs/policies/**/*.md`, and `docs/decisions/**/*.md`. Use standard relative Markdown links for navigation and put citations under `## Sources`. Bodies longer than 50 lines receive a warning.

Local document history is appended under `.knowledge/document-history/`. SQLite FTS5/BM25 indexes are recreated automatically under `.knowledge/index/`; external citations are never fetched or cached.

## Development

```powershell
Push-Location plugins/treewiki
npm run check
npm run build:claude
Pop-Location
python -m unittest plugins.treewiki.tests.test_treewiki_v030 -v
```

See the [repository map](AGENTS.md), [policies](docs/policies/AGENTS.md), and [0.3 decision](docs/decisions/treewiki-0.3.md).
