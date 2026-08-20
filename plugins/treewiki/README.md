# TreeWiki Agent Plugin

This directory is the portable TreeWiki 0.2.1 distribution. `plugin.json` and
`mcp.json` follow Agent Plugins 1.0.0. Codex reads the compatibility metadata in
`.codex-plugin/plugin.json` and its `.mcp.json` bridge; both configurations launch
the same bundled stdio MCP server.

The committed `dist/treewiki-mcp.mjs`, canonical skill, Python core, and vendored
PyYAML runtime allow installation without `npm install` or `pip install`. Codex
uses its standard tool, result, and approval surfaces. `npm run build` is only for
maintainers rebuilding the release.

Optional remote validation uses `npm run start:http`. It is not the default Codex
installation path and still stores bindings beneath `PLUGIN_DATA`.
