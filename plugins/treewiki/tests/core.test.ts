import assert from "node:assert/strict";
import { test } from "node:test";
import { parseJsonLines, parseMarkdownDocument, TreeWikiCore, type CommandExecutor } from "../src/core.js";
import type { Binding } from "../src/bindings.js";
import type { PluginRuntimeConfig } from "../src/config.js";

const config: PluginRuntimeConfig = { pluginRoot: "C:\\plugin", dataDirectory: "C:\\data", python: "python", runtimeDirectory: "C:\\runtime", vendorDirectory: "C:\\vendor", host: "127.0.0.1", port: 8787 };
const binding: Binding = { id: "binding-test", repository: "C:\\repo", principal: "user:test", team: "team:repo", createdAt: "2026-01-01T00:00:00Z", modifiedAt: "2026-01-01T00:00:00Z" };

test("UTF-8 JSONL and Markdown are parsed", () => {
  assert.deepEqual(parseJsonLines<{id:string}>('{"id":"기억-1"}\n'), [{ id: "기억-1" }]);
  assert.equal(parseMarkdownDocument("---\nid: M1\ntitle: 테스트\n---\n본문\n").body, "본문");
});

test("L3 apply forwards only the approved binding identity and exact plan", async () => {
  const calls:string[][]=[]; const executor:CommandExecutor=async(_program,args)=>{calls.push(args);return {exitCode:0,stderr:"",stdout:"{}"}};
  const core=new TreeWikiCore(config,binding,executor);const digest=`sha256:${"a".repeat(64)}`;const planId=`sha256:${"b".repeat(64)}`;
  await core.applyL3Review({id:"MEMORY-L3-1",decision:"activate",candidateDigest:digest,planId});
  assert.deepEqual(calls[0].slice(-4),["--principal","user:test","--team","team:repo"]);
  assert.ok(calls[0].includes(planId)); assert.ok(calls[0].includes(digest));
});

test("global and memory upgrade stages are never applyable through native MCP tools", async () => {
  const executor:CommandExecutor=async()=>({exitCode:2,stderr:"",stdout:JSON.stringify({overall:{status:"upgrade_required",plan_id:`sha256:${"c".repeat(64)}`,apply_allowed:true}})});
  const core=new TreeWikiCore(config,binding,executor);
  const runtime=await core.planUpgradeStage("runtime");
  assert.equal(runtime.schema,"treewiki.upgrade-plan/v1");
  assert.equal(runtime.applyAllowed,false);
  assert.equal((await core.planUpgradeStage("memory-layout")).applyAllowed,false);
});
