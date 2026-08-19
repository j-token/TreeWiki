import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pluginData = await mkdtemp(resolve(tmpdir(), "treewiki-mcp-smoke-"));
const repository = resolve(pluginData, "repository");
await mkdir(repository);
const python = process.env.TREEWIKI_PYTHON || "python";
const bootstrapped = spawnSync(python, [
  resolve(pluginRoot, "skills", "treewiki", "scripts", "bootstrap_treewiki.py"),
  repository, "--embedding", "disabled", "--owner", "user:test", "--team", "team:repo",
], { encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1", PYTHONPATH: resolve(pluginRoot, "vendor") } });
assert.equal(bootstrapped.status, 0, bootstrapped.stderr || bootstrapped.stdout);
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [resolve(pluginRoot, "dist", "treewiki-mcp.mjs")],
  cwd: pluginRoot,
  env: { ...process.env, PLUGIN_ROOT: pluginRoot, PLUGIN_DATA: pluginData, PYTHONUTF8: "1" },
  stderr: "pipe",
});
const client = new Client({ name: "treewiki-bundle-smoke", version: "0.2.1" }, { capabilities: {} });
try {
  await client.connect(transport);
  const tools = await client.listTools();
  assert.equal(tools.tools.length, 12);
  assert.equal(tools.tools.some((tool) => tool.name === "open_treewiki_workbench"), false);
  assert.ok(tools.tools.every((tool) => tool._meta === undefined));
  assert.equal(tools.tools.find((tool) => tool.name === "list_bindings")?.annotations?.readOnlyHint, true);
  assert.equal(tools.tools.find((tool) => tool.name === "apply_binding_change")?.annotations?.destructiveHint, true);
  await assert.rejects(client.readResource({ uri: "ui://treewiki/workbench-v1.html" }));
  const plan = await client.callTool({ name: "plan_binding_change", arguments: {
    action: "upsert", repository, principal: "user:test", team: "team:repo",
  } });
  const planned = plan.structuredContent;
  const planText = plan.content.find((item) => item.type === "text");
  assert.match(planText?.text || "", /Impact:/u);
  assert.match(planText?.text || "", /Plan ID: sha256:/u);
  assert.match(planText?.text || "", /Binding digest: sha256:/u);
  assert.equal((await client.callTool({ name: "list_bindings", arguments: {} })).structuredContent.bindings.length, 0);
  await client.callTool({ name: "apply_binding_change", arguments: { planId: planned.planId, bindingDigest: planned.bindingDigest } });
  const bindings = (await client.callTool({ name: "list_bindings", arguments: {} })).structuredContent.bindings;
  assert.equal(bindings.length, 1);
  const searched = await client.callTool({ name: "search", arguments: { bindingId: bindings[0].id, query: "repository" } });
  assert.ok(Array.isArray(searched.structuredContent.results));
  console.log("VALID bundled stdio MCP native tools/binding/search");
} finally {
  await client.close().catch(() => undefined);
  await rm(pluginData, { recursive: true, force: true });
}
