import assert from "node:assert/strict";
import { test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createTreeWikiServer, WORKBENCH_URI } from "../src/server.js";
import type { TreeWikiService } from "../src/service.js";

const service = {
  listBindings: async()=>[{id:"binding-test",repository:"C:\\repo",principal:"user:test",team:"team:repo",createdAt:"x",modifiedAt:"x"}],
  planBindingChange: async()=>({}), applyBindingChange:async()=>({}), overview:async()=>({}), search:async()=>[], fetch:async()=>({}), history:async()=>[], candidates:async()=>[], planReview:async()=>({}), applyReview:async()=>({}), planUpgrade:async()=>({}), applyUpgrade:async()=>({}),
} as unknown as TreeWikiService;

test("MCP initialize, tools, resource, and Workbench render smoke", async()=>{
  const server=createTreeWikiServer(service,"<!doctype html><title>TreeWiki Workbench</title>");
  const client=new Client({name:"treewiki-test",version:"0.2.0"},{capabilities:{}});const [ct,st]=InMemoryTransport.createLinkedPair();await Promise.all([server.connect(st),client.connect(ct)]);
  try{
    const tools=await client.listTools();assert.equal(tools.tools.length,13);assert.ok(tools.tools.some(tool=>tool.name==="open_treewiki_workbench"));
    assert.equal(tools.tools.find(tool=>tool.name==="apply_l3_review")?.annotations?.destructiveHint,true);
    const resource=await client.readResource({uri:WORKBENCH_URI});assert.equal(resource.contents[0].mimeType,"text/html;profile=mcp-app");
    const opened=await client.callTool({name:"open_treewiki_workbench",arguments:{}});assert.equal((opened.structuredContent as {selectedBindingId:string}).selectedBindingId,"binding-test");
    const bindings=await client.callTool({name:"list_bindings",arguments:{}});assert.equal((bindings.structuredContent as {bindings:Array<{id:string}>}).bindings[0].id,"binding-test");
    const searched=await client.callTool({name:"search",arguments:{bindingId:"binding-test",query:"history"}});assert.deepEqual((searched.structuredContent as {results:unknown[]}).results,[]);
  }finally{await client.close();await server.close()}
});
