# ChatGPT HTTP development transport

TreeWiki's supported Codex installation uses the bundled stdio MCP server. This document covers only local development and optional remote validation of the same native MCP tools in compatible hosts.

```powershell
Set-Location plugins/treewiki
npm install
npm run build
$env:PLUGIN_DATA='C:\path\to\treewiki-plugin-data'
npm run start:http
```

The endpoint is `http://127.0.0.1:8787/mcp`. A remote host requires an approved HTTPS deployment or secure tunnel and its own authentication controls. Do not expose the development server directly to the public internet. Configure the host's Developer mode with the HTTPS `/mcp` URL and refresh it when tool metadata changes.

Bindings remain server-side under `PLUGIN_DATA`; tools accept `bindingId`, not a repository path or ACL identity. HTTP transport does not weaken the two-step plan and apply checks for binding, L3, or upgrade writes.
