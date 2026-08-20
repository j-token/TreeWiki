import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import type { TreeWikiService } from "./service.js";
import type { ReviewDecision } from "./core.js";

const id = z.string().trim().min(1).max(300);
const hash = z.string().regex(/^sha256:[0-9a-f]{64}$/u);
const decision = z.enum(["activate", "reject", "supersede"]);
const gapReason = z.enum(["no_result", "acl_hidden", "stale", "ambiguous"]);
const gapStatus = z.enum(["open", "resolved"]);
const stage = z.enum(["runtime", "config", "document-history", "memory-layout", "index", "adapters", "claude-alias", "hook"]);
const readAnnotations = { readOnlyHint: true, destructiveHint: false, openWorldHint: false, idempotentHint: true };
const writeAnnotations = { readOnlyHint: false, destructiveHint: true, openWorldHint: false, idempotentHint: false };

export const SERVER_INSTRUCTIONS = [
  "Call list_bindings first, then use the search, fetch, history, review, and upgrade tools for the selected approved binding.",
  "Pass only an approved bindingId to repository tools.",
  "For every write, call the matching plan tool first, present its exact result, and wait for a separate explicit user confirmation of that exact plan and digest before calling apply.",
  "Never automatically apply or retry writes. If a plan is stale, re-plan. If an apply outcome is uncertain, read back current state without retrying the write.",
].join(" ");

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
const gapPlanDetails: Detail[] = [
  { label: "Plan ID", keys: ["plan_id"] },
  { label: "Gap ID", keys: ["gap_id"] },
  { label: "Reason", keys: ["reason"] },
  { label: "Status", keys: ["status"] },
];

export function createTreeWikiServer(service: TreeWikiService): McpServer {
  const server = new McpServer({ name: "treewiki", version: "0.2.1" }, {
    instructions: SERVER_INSTRUCTIONS,
  });

  server.registerTool("list_bindings", { title: "List TreeWiki bindings", description: "List approved repository and ACL profiles.", inputSchema: {}, annotations: readAnnotations },
    async () => {
      const bindings = await service.listBindings();
      return response({ bindings }, `${bindings.length} approved TreeWiki binding(s).`);
    });
  server.registerTool("plan_binding_change", {
    title: "Plan TreeWiki binding change", description: "Validate a repository profile and return a non-writing plan. Stop until the user separately confirms the exact plan and binding digest.",
    inputSchema: { action: z.enum(["upsert", "remove"]), repository: z.string().trim().min(1), principal: z.string().trim().min(1),
      team: z.string().trim().min(1), documentBaseUrl: z.string().url().optional(), overlayBindingIds: z.array(id).max(20).optional() }, annotations: readAnnotations,
  }, async (input) => response(await service.planBindingChange(input), "Binding change plan created; it has not been applied.", bindingPlanDetails));
  server.registerTool("apply_binding_change", {
    title: "Apply approved binding change", description: "Apply the exact previously planned binding change only after separate explicit user approval of its plan ID and binding digest.",
    inputSchema: { planId: hash, bindingDigest: hash }, annotations: writeAnnotations,
  }, async ({ planId, bindingDigest }) => response(await service.applyBindingChange(planId, bindingDigest), "Approved binding change applied."));

  server.registerTool("get_treewiki_overview", { title: "Get TreeWiki overview", description: "Retrieve adoption, upgrade state, and candidate count for an approved binding.",
    inputSchema: { bindingId: id }, annotations: readAnnotations },
  async ({ bindingId }) => {
    const overview = await service.overview(bindingId);
    return response(overview, `TreeWiki overview: adopted: ${String(overview.adopted ?? false)}, ${String(overview.documentCount ?? 0)} document(s), ${String(overview.candidateCount ?? 0)} L3 candidate(s), upgrade required: ${String(overview.upgradeRequired ?? false)}.`);
  });
  server.registerTool("search", { title: "Search TreeWiki", description: "Run ACL-filtered knowledge search for one approved binding.",
    inputSchema: { bindingId: id, query: z.string().trim().min(1).max(500) }, annotations: readAnnotations },
  async ({ bindingId, query }) => {
    const results = await service.search(bindingId, query);
    return response({ results }, `${results.length} ACL-approved TreeWiki search result(s).`);
  });
  server.registerTool("search_federated", { title: "Search federated TreeWiki knowledge", description: "Search a binding and its explicitly approved same-identity overlays. Duplicate stable IDs are returned as conflicts and are never auto-merged.",
    inputSchema: { bindingId: id, query: z.string().trim().min(1).max(500) }, annotations: readAnnotations },
  async ({ bindingId, query }) => {
    const results = await service.federatedSearch(bindingId, query);
    return response({ results }, `${results.length} ACL-approved federated TreeWiki result(s).`);
  });
  server.registerTool("fetch", { title: "Fetch TreeWiki document", description: "Read one ACL-approved document selected from native TreeWiki search results and return it to Codex as structured content.",
    inputSchema: { bindingId: id, documentId: id }, annotations: readAnnotations },
  async ({ bindingId, documentId }) => response(await service.fetch(bindingId, documentId), `Loaded ACL-approved TreeWiki document ${documentId}.`));
  server.registerTool("fetch_with_context", { title: "Fetch federated TreeWiki context", description: "Fetch one stable document ID from an approved binding federation. Divergent copies are returned as an explicit conflict.",
    inputSchema: { bindingId: id, documentId: id }, annotations: readAnnotations },
  async ({ bindingId, documentId }) => response(await service.fetchWithContext(bindingId, documentId), `Loaded federated context for ${documentId}.`));
  server.registerTool("get_document_history", { title: "Get document history", description: "Read a document revision ledger after ACL checks.",
    inputSchema: { bindingId: id, documentId: id }, annotations: readAnnotations },
  async ({ bindingId, documentId }) => {
    const history = await service.history(bindingId, documentId);
    return response({ history }, `Loaded ${count(history)} history revision(s) for ${documentId}.`);
  });
  server.registerTool("plan_retrieval_gap", { title: "Plan retrieval-gap evidence", description: "Plan an append-only, local retrieval-gap event without writing. The event contains no hidden document titles or content.",
    inputSchema: { bindingId: id, query: z.string().trim().min(1).max(500), reason: gapReason, workUnit: id,
      status: gapStatus.optional(), resolutionDocumentId: id.optional() }, annotations: readAnnotations },
  async ({ bindingId, ...input }) => response(await service.planRetrievalGap(bindingId, input), "Retrieval-gap plan created; nothing was recorded.", gapPlanDetails));
  server.registerTool("record_retrieval_gap", { title: "Record approved retrieval-gap evidence", description: "Append the exact retrieval-gap event only after separate approval of its plan ID.",
    inputSchema: { bindingId: id, query: z.string().trim().min(1).max(500), reason: gapReason, workUnit: id,
      status: gapStatus.optional(), resolutionDocumentId: id.optional(), planId: hash }, annotations: writeAnnotations },
  async ({ bindingId, ...input }) => response(await service.recordRetrievalGap(bindingId, input), "Approved retrieval-gap event recorded."));
  server.registerTool("list_retrieval_gaps", { title: "List retrieval gaps", description: "List the calling binding principal's folded retrieval gaps without exposing ACL-hidden documents.",
    inputSchema: { bindingId: id, status: gapStatus.optional() }, annotations: readAnnotations },
  async ({ bindingId, status }) => {
    const gaps = await service.retrievalGaps(bindingId, status);
    return response({ gaps }, `${gaps.length} retrieval gap(s).`);
  });
  server.registerTool("get_governance_report", { title: "Get knowledge governance report", description: "Inspect overdue, stale-source, duplicate, and missing-replacement findings after ACL filtering.",
    inputSchema: { bindingId: id }, annotations: readAnnotations },
  async ({ bindingId }) => response(await service.governanceReport(bindingId), "TreeWiki governance report loaded."));
  server.registerTool("list_l3_candidates", { title: "List L3 candidates", description: "Compare proposed knowledge and persona L3 candidates. Use plan_l3_review before any decision is applied.",
    inputSchema: { bindingId: id, ids: z.array(id).max(50).optional() }, annotations: readAnnotations },
  async ({ bindingId, ids }) => {
    const candidates = await service.candidates(bindingId, ids);
    return response({ candidates }, `${candidates.length} reviewable TreeWiki L3 candidate(s).`);
  });
  server.registerTool("plan_l3_review", { title: "Plan L3 review", description: "Create a dry-run activate, reject, or supersede plan. Stop until the user separately approves the exact plan and candidate digest.",
    inputSchema: { bindingId: id, id, decision }, annotations: readAnnotations },
  async ({ bindingId, id: candidateId, decision: selected }) => response(
    await service.planReview(bindingId, candidateId, selected as ReviewDecision), "L3 review plan created; no document was changed.", reviewPlanDetails));
  server.registerTool("apply_l3_review", { title: "Apply approved L3 review", description: "Apply a candidate decision only after separate explicit user approval, using the exact candidate digest and plan ID returned by plan_l3_review.",
    inputSchema: { bindingId: id, id, decision, candidateDigest: hash, planId: hash }, annotations: writeAnnotations },
  async ({ bindingId, id: candidateId, decision: selected, candidateDigest, planId }) => response(
    await service.applyReview(bindingId, { id: candidateId, decision: selected as ReviewDecision, candidateDigest, planId }), "Approved L3 review applied."));
  server.registerTool("plan_upgrade_stage", { title: "Plan TreeWiki upgrade stage", description: "Inspect one upgrade stage and return an exact non-writing plan and status digest. Stop until the user separately approves that exact plan.",
    inputSchema: { bindingId: id, stage }, annotations: readAnnotations },
  async ({ bindingId, stage: selected }) => response(
    await service.planUpgrade(bindingId, selected), "Upgrade plan created; no upgrade was applied.", upgradePlanDetails));
  server.registerTool("apply_upgrade_stage", { title: "Apply approved repository-local upgrade", description: "After separate explicit user approval, apply the exact safe repository-local plan and status digest. Global skill, hook, and governed-memory stages are refused.",
    inputSchema: { bindingId: id, stage, planId: hash, statusDigest: hash }, annotations: writeAnnotations },
  async ({ bindingId, stage: selected, planId, statusDigest }) => response(
    await service.applyUpgrade(bindingId, selected, planId, statusDigest), "Approved repository-local upgrade stage applied."));

  return server;
}
