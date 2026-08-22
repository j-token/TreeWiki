import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pluginData = await mkdtemp(resolve(tmpdir(), "treewiki-mcp-smoke-"));
const repository = resolve(pluginData, "repository");
await mkdir(resolve(repository, "docs", "policies"), { recursive: true });
const python = process.env.TREEWIKI_PYTHON || "python";
const initialized = spawnSync(python, [
  resolve(pluginRoot, "skills", "treewiki", "scripts", "treewiki_cli.py"), "init", repository,
], { encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1", PYTHONPATH: resolve(pluginRoot, "vendor") } });
assert.equal(initialized.status, 0, initialized.stderr || initialized.stdout);
await writeFile(resolve(repository, "AGENTS.md"), "---\nid: MAP-SMOKE\ntype: map\n---\n\n# Smoke map\n\n- [Policy](docs/policies/search.md)\n", "utf8");
await writeFile(resolve(repository, "docs", "policies", "search.md"), "---\nid: POLICY-SEARCH\ntype: policy\n---\n\n# Local search\n\nUse local BM25 search.\n", "utf8");

const transport = new StdioClientTransport({
  command: process.execPath,
  args: [resolve(pluginRoot, "dist", "treewiki-mcp.mjs")],
  cwd: pluginRoot,
  env: { ...process.env, PLUGIN_ROOT: pluginRoot, PLUGIN_DATA: pluginData, PYTHONUTF8: "1" },
  stderr: "pipe",
});
const client = new Client({ name: "treewiki-bundle-smoke", version: "0.3.0" }, { capabilities: {} });
try {
  await client.connect(transport);
  const tools = await client.listTools();
  assert.deepEqual(tools.tools.map((tool) => tool.name).sort(), [
    "connect_workspace", "get_history", "get_status", "read", "search", "validate",
  ]);
  const connected = await client.callTool({ name: "connect_workspace", arguments: { repository } });
  const workspaceId = connected.structuredContent.workspace.id;
  const searched = await client.callTool({ name: "search", arguments: { workspaceId, query: "local BM25" } });
  assert.equal(searched.structuredContent.results[0].id, "POLICY-SEARCH");
  const loaded = await client.callTool({ name: "read", arguments: { workspaceId, reference: "POLICY-SEARCH" } });
  assert.match(loaded.structuredContent.body, /local BM25/u);
  console.log("VALID bundled TreeWiki 0.3 workspace/search/read tools");
} finally {
  await client.close().catch(() => undefined);
  await rm(pluginData, { recursive: true, force: true });
}
