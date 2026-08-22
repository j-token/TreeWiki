# TreeWiki Agent Plugin 0.3.0

This directory is the canonical TreeWiki package. It contains the portable Agent Plugin manifest, Codex compatibility metadata, the TreeWiki skill, the Python SQLite/BM25 core, and six native MCP tools.

## MCP tools

- `connect_workspace`
- `get_status`
- `search`
- `read`
- `get_history`
- `validate`

The skill supplies the current repository path once and reuses the returned `workspaceId`. Search may rebuild only the derived `.knowledge/index/` cache. External source URLs remain citations and are not fetched.

## Build

```powershell
npm run check
npm run build:claude
```

The Claude runtime and route skill are generated from this package. Do not publish or maintain `skills/treewiki` as a standalone distribution.
