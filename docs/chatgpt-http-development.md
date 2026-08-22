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

Workspace connections remain server-side under `PLUGIN_DATA`. Call `connect_workspace` once with the host's current repository, then pass only its `workspaceId` to status, search, read, history, and validation tools. Search may refresh the local derived index; the HTTP server never fetches external citation URLs.
