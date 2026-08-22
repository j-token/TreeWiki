import assert from "node:assert/strict";
import { test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createTreeWikiServer, SERVER_INSTRUCTIONS } from "../src/server.js";
import type { TreeWikiService } from "../src/service.js";

const workspaceId = "workspace-0123456789abcdef0123";
const service = {
  connect: async () => ({ workspace: { id: workspaceId, repository: "C:\\repo" }, status: { status: "current" } }),
  status: async () => ({ status: "current", documents: 2, index_fresh: true }),
  search: async () => ({ query: "policy", results: [{ id: "POLICY-1" }] }),
  read: async () => ({ id: "POLICY-1", body: "# Policy" }),
  history: async () => ({ id: "POLICY-1", events: [] }),
  validate: async () => ({ valid: true, errors: [], warnings: [] }),
} as unknown as TreeWikiService;

test("MCP exposes exactly the six 0.3 workspace tools", async () => {
  assert.match(SERVER_INSTRUCTIONS, /current workspace/u);
  assert.match(SERVER_INSTRUCTIONS, /never be fetched/u);
  const server = createTreeWikiServer(service);
  const client = new Client({ name: "treewiki-test", version: "0.3.0" }, { capabilities: {} });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  try {
    const tools = await client.listTools();
    assert.deepEqual(tools.tools.map((tool) => tool.name).sort(), [
      "connect_workspace", "get_history", "get_status", "read", "search", "validate",
    ]);
    assert.equal(tools.tools.find((tool) => tool.name === "search")?.annotations?.readOnlyHint, false);
    assert.equal(tools.tools.find((tool) => tool.name === "read")?.annotations?.readOnlyHint, true);
    const connected = await client.callTool({ name: "connect_workspace", arguments: { repository: "C:\\repo" } });
    assert.equal((connected.structuredContent as { workspace: { id: string } }).workspace.id, workspaceId);
    const searched = await client.callTool({ name: "search", arguments: { workspaceId, query: "policy" } });
    assert.equal((searched.structuredContent as { results: unknown[] }).results.length, 1);
  } finally {
    await client.close(); await server.close();
  }
});
