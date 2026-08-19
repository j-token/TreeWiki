import { registerAppResource, registerAppTool, RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import type { TreeWikiService } from "./service.js";
import type { ReviewDecision } from "./core.js";

export const WORKBENCH_URI = "ui://treewiki/workbench-v1.html";
const id = z.string().trim().min(1).max(300);
const hash = z.string().regex(/^sha256:[0-9a-f]{64}$/u);
const decision = z.enum(["activate", "reject", "supersede"]);
const stage = z.enum(["runtime", "config", "document-history", "memory-layout", "index", "adapters", "claude-alias", "hook"]);
const readAnnotations = { readOnlyHint: true, destructiveHint: false, openWorldHint: false, idempotentHint: true };
const writeAnnotations = { readOnlyHint: false, destructiveHint: true, openWorldHint: false, idempotentHint: false };
const uiMeta = { ui: { visibility: ["model", "app"] }, "openai/widgetAccessible": true };
function response(value: unknown, text: string) { return { structuredContent: value as Record<string, unknown>, content: [{ type: "text" as const, text }] }; }

export function createTreeWikiServer(service: TreeWikiService, workbenchHtml: string): McpServer {
  const server = new McpServer({ name: "treewiki", version: "0.2.0" }, {
    instructions: "Pass only an approved bindingId to repository tools. All writes require an exact dry-run plan and digest, followed by explicit approval.",
  });

  server.registerTool("list_bindings", { title: "List TreeWiki bindings", description: "List approved repository and ACL profiles.", inputSchema: {}, annotations: readAnnotations },
    async () => response({ bindings: await service.listBindings() }, "Approved TreeWiki bindings."));
  server.registerTool("plan_binding_change", {
    title: "Plan TreeWiki binding change", description: "Validate a repository profile and create a non-writing plan.",
    inputSchema: { action: z.enum(["upsert", "remove"]), repository: z.string().trim().min(1), principal: z.string().trim().min(1),
      team: z.string().trim().min(1), documentBaseUrl: z.string().url().optional() }, annotations: readAnnotations, _meta: uiMeta,
  }, async (input) => response(await service.planBindingChange(input), "Binding change plan created; it has not been applied."));
  server.registerTool("apply_binding_change", {
    title: "Apply approved binding change", description: "Apply the exact previously planned binding change.",
    inputSchema: { planId: hash, bindingDigest: hash }, annotations: writeAnnotations, _meta: uiMeta,
  }, async ({ planId, bindingDigest }) => response(await service.applyBindingChange(planId, bindingDigest), "Approved binding change applied."));

  server.registerTool("get_treewiki_overview", { title: "Get TreeWiki overview", description: "Inspect adoption, upgrade state, and candidate count.",
    inputSchema: { bindingId: id }, annotations: readAnnotations, _meta: uiMeta },
  async ({ bindingId }) => response(await service.overview(bindingId), "TreeWiki overview loaded."));
  server.registerTool("search", { title: "Search TreeWiki", description: "ACL-filtered knowledge search for one approved binding.",
    inputSchema: { bindingId: id, query: z.string().trim().min(1).max(500) }, annotations: readAnnotations, _meta: uiMeta },
  async ({ bindingId, query }) => response({ results: await service.search(bindingId, query) }, "TreeWiki search results."));
  server.registerTool("fetch", { title: "Fetch TreeWiki document", description: "Read one ACL-approved document.",
    inputSchema: { bindingId: id, documentId: id }, annotations: readAnnotations, _meta: uiMeta },
  async ({ bindingId, documentId }) => response(await service.fetch(bindingId, documentId), `Loaded ${documentId}.`));
  server.registerTool("get_document_history", { title: "Get document history", description: "Read a document revision ledger after ACL checks.",
    inputSchema: { bindingId: id, documentId: id }, annotations: readAnnotations, _meta: uiMeta },
  async ({ bindingId, documentId }) => response({ history: await service.history(bindingId, documentId) }, `Loaded history for ${documentId}.`));
  server.registerTool("list_l3_candidates", { title: "List L3 candidates", description: "Compare proposed knowledge and persona L3 candidates.",
    inputSchema: { bindingId: id, ids: z.array(id).max(50).optional() }, annotations: readAnnotations, _meta: uiMeta },
  async ({ bindingId, ids }) => response({ candidates: await service.candidates(bindingId, ids) }, "TreeWiki L3 candidates loaded."));
  server.registerTool("plan_l3_review", { title: "Plan L3 review", description: "Create a dry-run activate, reject, or supersede plan.",
    inputSchema: { bindingId: id, id, decision }, annotations: readAnnotations, _meta: uiMeta },
  async ({ bindingId, id: candidateId, decision: selected }) => response(await service.planReview(bindingId, candidateId, selected as ReviewDecision), "L3 review plan created; no document was changed."));
  server.registerTool("apply_l3_review", { title: "Apply approved L3 review", description: "Apply a candidate decision using its exact digest and plan ID.",
    inputSchema: { bindingId: id, id, decision, candidateDigest: hash, planId: hash }, annotations: writeAnnotations, _meta: uiMeta },
  async ({ bindingId, id: candidateId, decision: selected, candidateDigest, planId }) => response(
    await service.applyReview(bindingId, { id: candidateId, decision: selected as ReviewDecision, candidateDigest, planId }), "Approved L3 review applied."));
  server.registerTool("plan_upgrade_stage", { title: "Plan TreeWiki upgrade stage", description: "Inspect one upgrade stage and return an exact plan and status digest without writing.",
    inputSchema: { bindingId: id, stage }, annotations: readAnnotations, _meta: uiMeta },
  async ({ bindingId, stage: selected }) => response(await service.planUpgrade(bindingId, selected), "Upgrade plan created; no upgrade was applied."));
  server.registerTool("apply_upgrade_stage", { title: "Apply approved repository-local upgrade", description: "Apply an exact safe repository-local stage. Global skill, hook, and governed-memory stages are refused.",
    inputSchema: { bindingId: id, stage, planId: hash, statusDigest: hash }, annotations: writeAnnotations, _meta: uiMeta },
  async ({ bindingId, stage: selected, planId, statusDigest }) => response(await service.applyUpgrade(bindingId, selected, planId, statusDigest), "Approved repository-local upgrade stage applied."));

  registerAppTool(server, "open_treewiki_workbench", {
    title: "Open TreeWiki Workbench", description: "Open the complete TreeWiki governance UI for approved repository profiles.", inputSchema: {}, annotations: readAnnotations,
    _meta: { ui: { resourceUri: WORKBENCH_URI, visibility: ["model"] }, "openai/outputTemplate": WORKBENCH_URI,
      "openai/toolInvocation/invoking": "Opening TreeWiki Workbench…", "openai/toolInvocation/invoked": "TreeWiki Workbench opened." },
  }, async () => {
    const bindings = await service.listBindings();
    return response({ bindings, selectedBindingId: bindings[0]?.id ?? null }, bindings.length ? "TreeWiki Workbench is ready." : "Open setup to approve a repository binding.");
  });
  registerAppResource(server, "TreeWiki Workbench", WORKBENCH_URI, {}, async () => ({ contents: [{
    uri: WORKBENCH_URI, mimeType: RESOURCE_MIME_TYPE, text: workbenchHtml,
    _meta: { ui: { prefersBorder: false, csp: { connectDomains: [], resourceDomains: [] } },
      "openai/widgetDescription": "TreeWiki repository setup, ACL search, document history, L3 review, and safe upgrade workbench.",
      "openai/widgetPrefersBorder": false },
  }] }));
  return server;
}
