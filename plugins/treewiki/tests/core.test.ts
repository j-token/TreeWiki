import assert from "node:assert/strict";
import { test } from "node:test";
import { TreeWikiCommandError, TreeWikiCore, type CommandExecutor } from "../src/core.js";
import type { PluginRuntimeConfig } from "../src/config.js";
import type { Workspace } from "../src/workspaces.js";

const config: PluginRuntimeConfig = {
  pluginRoot: "C:\\plugin", dataDirectory: "C:\\data", python: "python",
  runtimeDirectory: "C:\\plugin\\skills\\treewiki\\scripts", vendorDirectory: "C:\\plugin\\vendor",
  host: "127.0.0.1", port: 8787,
};
const workspace: Workspace = {
  id: "workspace-0123456789abcdef0123", repository: "C:\\repo", createdAt: "x", modifiedAt: "x",
};

test("core invokes the bundled internal CLI without ACL arguments", async () => {
  const calls: string[][] = [];
  const executor: CommandExecutor = async (_program, args) => {
    calls.push(args);
    return { stdout: JSON.stringify({ results: [{ id: "POLICY-1" }] }), stderr: "", exitCode: 0 };
  };
  const result = await new TreeWikiCore(config, workspace, executor).search("policy", 4);
  assert.deepEqual(result.results, [{ id: "POLICY-1" }]);
  assert.match(calls[0][0], /treewiki_cli\.py$/u);
  assert.deepEqual(calls[0].slice(1), ["search", "C:\\repo", "policy", "--limit", "4"]);
  assert.equal(calls[0].includes("--principal"), false);
});

test("core surfaces structured CLI errors", async () => {
  const executor: CommandExecutor = async () => ({
    stdout: JSON.stringify({ error: { code: "TREEWIKI_ERROR", message: "fresh initialization required" } }),
    stderr: "", exitCode: 1,
  });
  await assert.rejects(() => new TreeWikiCore(config, workspace, executor).status(), (error: unknown) => {
    assert.ok(error instanceof TreeWikiCommandError);
    assert.match(error.message, /fresh initialization/u);
    return true;
  });
});
