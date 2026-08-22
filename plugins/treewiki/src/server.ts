import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import type { TreeWikiService } from "./service.js";

const workspaceId = z.string().trim().regex(/^workspace-[0-9a-f]{20}$/u);
const readAnnotations = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } as const;
const cacheAnnotations = { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false } as const;

export const SERVER_INSTRUCTIONS = [
  "TreeWiki 0.3 retrieves project maps, policies, and decisions from the current workspace.",
  "The TreeWiki skill passes the host's current workspace path to connect_workspace, then reuses the returned workspaceId.",
  "Use search before read. Search returns locations and link-expanded neighbors; read returns the selected full document.",
  "External source URLs are citations only and must never be fetched by this server.",
].join(" ");

function response(structuredContent: Record<string, unknown>, text: string) {
  return { content: [{ type: "text" as const, text }], structuredContent };
}

export function createTreeWikiServer(service: TreeWikiService): McpServer {
  const server = new McpServer({ name: "treewiki", version: "0.3.0" }, { instructions: SERVER_INSTRUCTIONS });
  server.registerTool("connect_workspace", {
    title: "Connect current TreeWiki workspace",
    description: "Validate and remember the current host workspace path. The TreeWiki skill supplies the path; later tools use only workspaceId.",
    inputSchema: { repository: z.string().trim().min(1) }, annotations: cacheAnnotations,
  }, async ({ repository }) => {
    const result = await service.connect(repository);
    return response(result as unknown as Record<string, unknown>, `Connected TreeWiki workspace ${result.workspace.id}.`);
  });
  server.registerTool("get_status", {
    title: "Get TreeWiki workspace status", description: "Report 0.3 initialization, managed document count, and BM25 index freshness.",
    inputSchema: { workspaceId }, annotations: readAnnotations,
  }, async ({ workspaceId: id }) => response(await service.status(id), "TreeWiki workspace status loaded."));
  server.registerTool("search", {
    title: "Search TreeWiki policies and decisions",
    description: "Run local SQLite BM25 over maps, policies, and decisions. A missing or stale derived index is rebuilt automatically.",
    inputSchema: { workspaceId, query: z.string().trim().min(1).max(500), limit: z.number().int().min(1).max(50).optional() },
    annotations: cacheAnnotations,
  }, async ({ workspaceId: id, query, limit }) => {
    const result = await service.search(id, query, limit);
    const count = Array.isArray(result.results) ? result.results.length : 0;
    return response(result, `${count} TreeWiki search result(s).`);
  });
  server.registerTool("read", {
    title: "Read a TreeWiki document",
    description: "Read one search-selected map, policy, or decision with outgoing links, backlinks, and source citations.",
    inputSchema: { workspaceId, reference: z.string().trim().min(1) }, annotations: readAnnotations,
  }, async ({ workspaceId: id, reference }) => response(await service.read(id, reference), `Loaded TreeWiki document ${reference}.`));
  server.registerTool("get_history", {
    title: "Get local TreeWiki document history",
    description: "Read the append-only local hash-chain history for one stable document ID.",
    inputSchema: { workspaceId, id: z.string().trim().min(1) }, annotations: readAnnotations,
  }, async ({ workspaceId: id, id: documentId }) => response(await service.history(id, documentId), `Loaded local history for ${documentId}.`));
  server.registerTool("validate", {
    title: "Validate TreeWiki documents",
    description: "Validate minimal id/type frontmatter, H1 titles, unique IDs, Markdown links, and the 50-line recommendation.",
    inputSchema: { workspaceId }, annotations: readAnnotations,
  }, async ({ workspaceId: id }) => response(await service.validate(id), "TreeWiki validation completed."));
  return server;
}
