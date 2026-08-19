import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import type { TreeWikiService } from "./service.js";
import type { ReviewDecision } from "./core.js";

const id = z.string().trim().min(1).max(300);
const hash = z.string().regex(/^sha256:[0-9a-f]{64}$/u);
const decision = z.enum(["activate", "reject", "supersede"]);
const stage = z.enum(["runtime", "config", "document-history", "memory-layout", "index", "adapters", "claude-alias", "hook"]);
const readAnnotations = { readOnlyHint: true, destructiveHint: false, openWorldHint: false, idempotentHint: true };
const writeAnnotations = { readOnlyHint: false, destructiveHint: true, openWorldHint: false, idempotentHint: false };

type Detail = { label: string; keys: string[] };

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function count(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

function response(value: unknown, text: string, details: Detail[] = []) {
  const data = record(value);
  const lines = details.flatMap(({ label, keys }) => {
    const key = keys.find((candidate) => data[candidate] !== undefined && data[candidate] !== "");
    return key ? [`${label}: ${String(data[key])}`] : [];
  });
  return {
    structuredContent: data,
    content: [{ type: "text" as const, text: [text, ...lines].join("\n") }],
  };
}

const bindingPlanDetails: Detail[] = [
  { label: "Impact", keys: ["impact"] },
  { label: "Plan ID", keys: ["planId", "plan_id"] },
  { label: "Binding digest", keys: ["bindingDigest", "binding_digest"] },
];
const reviewPlanDetails: Detail[] = [
  { label: "Plan ID", keys: ["planId", "plan_id"] },
  { label: "Candidate digest", keys: ["candidateDigest", "candidate_digest"] },
];
const upgradePlanDetails: Detail[] = [
  { label: "Stage", keys: ["stage"] },
  { label: "Plan ID", keys: ["planId", "plan_id"] },
  { label: "Status digest", keys: ["statusDigest", "status_digest"] },
  { label: "Apply allowed", keys: ["applyAllowed", "apply_allowed"] },
  { label: "Blocking reason", keys: ["blockingReason", "blocking_reason"] },
];

export function createTreeWikiServer(service: TreeWikiService): McpServer {
  const server = new McpServer({ name: "treewiki", version: "0.2.1" }, {
    instructions: "Pass only an approved bindingId to repository tools. All writes require an exact dry-run plan and digest, followed by explicit approval.",
  });

  server.registerTool("list_bindings", { title: "List TreeWiki bindings", description: "List approved repository and ACL profiles.", inputSchema: {}, annotations: readAnnotations },
    async () => {
      const bindings = await service.listBindings();
      return response({ bindings }, `${bindings.length} approved TreeWiki binding(s).`);
    });
  server.registerTool("plan_binding_change", {
    title: "Plan TreeWiki binding change", description: "Validate a repository profile and create a non-writing plan.",
    inputSchema: { action: z.enum(["upsert", "remove"]), repository: z.string().trim().min(1), principal: z.string().trim().min(1),
      team: z.string().trim().min(1), documentBaseUrl: z.string().url().optional() }, annotations: readAnnotations,
  }, async (input) => response(await service.planBindingChange(input), "Binding change plan created; it has not been applied.", bindingPlanDetails));
  server.registerTool("apply_binding_change", {
    title: "Apply approved binding change", description: "Apply the exact previously planned binding change.",
    inputSchema: { planId: hash, bindingDigest: hash }, annotations: writeAnnotations,
  }, async ({ planId, bindingDigest }) => response(await service.applyBindingChange(planId, bindingDigest), "Approved binding change applied."));

  server.registerTool("get_treewiki_overview", { title: "Get TreeWiki overview", description: "Inspect adoption, upgrade state, and candidate count.",
    inputSchema: { bindingId: id }, annotations: readAnnotations },
  async ({ bindingId }) => {
    const overview = await service.overview(bindingId);
    return response(overview, `TreeWiki overview: ${String(overview.documentCount ?? 0)} document(s), ${String(overview.candidateCount ?? 0)} L3 candidate(s), upgrade required: ${String(overview.upgradeRequired ?? false)}.`);
  });
  server.registerTool("search", { title: "Search TreeWiki", description: "ACL-filtered knowledge search for one approved binding.",
    inputSchema: { bindingId: id, query: z.string().trim().min(1).max(500) }, annotations: readAnnotations },
  async ({ bindingId, query }) => {
    const results = await service.search(bindingId, query);
    return response({ results }, `${results.length} ACL-approved TreeWiki search result(s).`);
  });
  server.registerTool("fetch", { title: "Fetch TreeWiki document", description: "Read one ACL-approved document.",
    inputSchema: { bindingId: id, documentId: id }, annotations: readAnnotations },
  async ({ bindingId, documentId }) => response(await service.fetch(bindingId, documentId), `Loaded ACL-approved TreeWiki document ${documentId}.`));
  server.registerTool("get_document_history", { title: "Get document history", description: "Read a document revision ledger after ACL checks.",
    inputSchema: { bindingId: id, documentId: id }, annotations: readAnnotations },
  async ({ bindingId, documentId }) => {
    const history = await service.history(bindingId, documentId);
    return response({ history }, `Loaded ${count(history)} history revision(s) for ${documentId}.`);
  });
  server.registerTool("list_l3_candidates", { title: "List L3 candidates", description: "Compare proposed knowledge and persona L3 candidates.",
    inputSchema: { bindingId: id, ids: z.array(id).max(50).optional() }, annotations: readAnnotations },
  async ({ bindingId, ids }) => {
    const candidates = await service.candidates(bindingId, ids);
    return response({ candidates }, `${candidates.length} reviewable TreeWiki L3 candidate(s).`);
  });
  server.registerTool("plan_l3_review", { title: "Plan L3 review", description: "Create a dry-run activate, reject, or supersede plan.",
    inputSchema: { bindingId: id, id, decision }, annotations: readAnnotations },
  async ({ bindingId, id: candidateId, decision: selected }) => response(
    await service.planReview(bindingId, candidateId, selected as ReviewDecision), "L3 review plan created; no document was changed.", reviewPlanDetails));
  server.registerTool("apply_l3_review", { title: "Apply approved L3 review", description: "Apply a candidate decision using its exact digest and plan ID.",
    inputSchema: { bindingId: id, id, decision, candidateDigest: hash, planId: hash }, annotations: writeAnnotations },
  async ({ bindingId, id: candidateId, decision: selected, candidateDigest, planId }) => response(
    await service.applyReview(bindingId, { id: candidateId, decision: selected as ReviewDecision, candidateDigest, planId }), "Approved L3 review applied."));
  server.registerTool("plan_upgrade_stage", { title: "Plan TreeWiki upgrade stage", description: "Inspect one upgrade stage and return an exact plan and status digest without writing.",
    inputSchema: { bindingId: id, stage }, annotations: readAnnotations },
  async ({ bindingId, stage: selected }) => response(
    await service.planUpgrade(bindingId, selected), "Upgrade plan created; no upgrade was applied.", upgradePlanDetails));
  server.registerTool("apply_upgrade_stage", { title: "Apply approved repository-local upgrade", description: "Apply an exact safe repository-local stage. Global skill, hook, and governed-memory stages are refused.",
    inputSchema: { bindingId: id, stage, planId: hash, statusDigest: hash }, annotations: writeAnnotations },
  async ({ bindingId, stage: selected, planId, statusDigest }) => response(
    await service.applyUpgrade(bindingId, selected, planId, statusDigest), "Approved repository-local upgrade stage applied."));

  return server;
}
