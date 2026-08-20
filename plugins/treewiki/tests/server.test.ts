import assert from "node:assert/strict";
import { test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createTreeWikiServer, SERVER_INSTRUCTIONS } from "../src/server.js";
import type { TreeWikiService } from "../src/service.js";

const planId = `sha256:${"a".repeat(64)}`;
const bindingDigest = `sha256:${"b".repeat(64)}`;
const candidateDigest = `sha256:${"c".repeat(64)}`;
const statusDigest = `sha256:${"d".repeat(64)}`;
const service = {
  listBindings: async()=>[{id:"binding-test",repository:"C:\\repo",principal:"user:test",team:"team:repo",createdAt:"x",modifiedAt:"x"}],
  planBindingChange: async()=>({impact:"Add binding-test",planId,bindingDigest}), applyBindingChange:async()=>({}),
  overview:async()=>({adopted:true,status:"adopted",documentCount:1,candidateCount:0,upgradeRequired:false}), search:async()=>[], fetch:async()=>({}),
  federatedSearch:async()=>[], fetchWithContext:async()=>({status:"matched",sources:[]}),
  history:async()=>[], candidates:async()=>[], planReview:async()=>({plan_id:planId,candidate_digest:candidateDigest}), applyReview:async()=>({}),
  planRetrievalGap:async()=>({plan_id:planId,gap_id:candidateDigest,reason:"no_result",status:"open"}),
  recordRetrievalGap:async()=>({}), retrievalGaps:async()=>[], governanceReport:async()=>({findings:[]}),
  planUpgrade:async()=>({stage:"index",planId,statusDigest,applyAllowed:true}), applyUpgrade:async()=>({}),
} as unknown as TreeWikiService;

test("MCP exposes reusable native tools without application resources", async()=>{
  assert.match(SERVER_INSTRUCTIONS,/Call list_bindings first/u);
  assert.match(SERVER_INSTRUCTIONS,/separate explicit user confirmation/u);
  assert.match(SERVER_INSTRUCTIONS,/Never automatically apply or retry writes/u);
  const server=createTreeWikiServer(service);
  const client=new Client({name:"treewiki-test",version:"0.2.1"},{capabilities:{}});
  const [ct,st]=InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(st),client.connect(ct)]);
  try{
    const tools=await client.listTools();
    assert.equal(tools.tools.length,18);
    assert.equal(tools.tools.some(tool=>tool.name==="open_treewiki_workbench"),false);
    assert.ok(tools.tools.every(tool=>tool._meta===undefined));
    assert.equal(client.getServerCapabilities()?.resources,undefined);
    assert.match(tools.tools.find(tool=>tool.name==="plan_l3_review")?.description??"",/Stop until the user separately approves/u);
    assert.match(tools.tools.find(tool=>tool.name==="apply_l3_review")?.description??"",/only after separate explicit user approval/u);
    assert.equal(tools.tools.find(tool=>tool.name==="list_bindings")?.annotations?.readOnlyHint,true);
    assert.equal(tools.tools.find(tool=>tool.name==="apply_l3_review")?.annotations?.destructiveHint,true);
    assert.equal(tools.tools.find(tool=>tool.name==="record_retrieval_gap")?.annotations?.destructiveHint,true);
    assert.match(tools.tools.find(tool=>tool.name==="search_federated")?.description??"",/never auto-merged/u);
    const planned=await client.callTool({name:"plan_binding_change",arguments:{
      action:"upsert",repository:"C:\\repo",principal:"user:test",team:"team:repo",
    }});
    const planText=(planned.content as Array<{type:string;text?:string}>).find(item=>item.type==="text");
    assert.ok(planText && "text" in planText);
    assert.match(planText.text ?? "",/Impact: Add binding-test/u);
    assert.match(planText.text ?? "",new RegExp(planId,"u"));
    assert.match(planText.text ?? "",new RegExp(bindingDigest,"u"));

    const reviewPlan=await client.callTool({name:"plan_l3_review",arguments:{bindingId:"binding-test",id:"L3-1",decision:"activate"}});
    const reviewText=(reviewPlan.content as Array<{type:string;text?:string}>).find(item=>item.type==="text")?.text ?? "";
    assert.match(reviewText,/Plan ID: sha256:/u);
    assert.match(reviewText,/Candidate digest: sha256:/u);
    const upgradePlan=await client.callTool({name:"plan_upgrade_stage",arguments:{bindingId:"binding-test",stage:"index"}});
    const upgradeText=(upgradePlan.content as Array<{type:string;text?:string}>).find(item=>item.type==="text")?.text ?? "";
    assert.match(upgradeText,/Status digest: sha256:/u);
    assert.match(upgradeText,/Apply allowed: true/u);

    const bindings=await client.callTool({name:"list_bindings",arguments:{}});
    assert.equal((bindings.structuredContent as {bindings:Array<{id:string}>}).bindings[0].id,"binding-test");
    const overview=await client.callTool({name:"get_treewiki_overview",arguments:{bindingId:"binding-test"}});
    assert.match((overview.content as Array<{type:string;text?:string}>).find(item=>item.type==="text")?.text??"",/adopted: true/u);
    const searched=await client.callTool({name:"search",arguments:{bindingId:"binding-test",query:"history"}});
    assert.deepEqual((searched.structuredContent as {results:unknown[]}).results,[]);
    const gapPlan=await client.callTool({name:"plan_retrieval_gap",arguments:{bindingId:"binding-test",query:"missing",reason:"no_result",workUnit:"work-1"}});
    const gapText=(gapPlan.content as Array<{type:string;text?:string}>).find(item=>item.type==="text")?.text??"";
    assert.match(gapText,/Gap ID: sha256:/u);
  }finally{await client.close();await server.close()}
});
