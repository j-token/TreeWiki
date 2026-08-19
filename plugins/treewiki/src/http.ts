import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import express from "express";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { loadConfig } from "./config.js";
import { createTreeWikiServer } from "./server.js";
import { TreeWikiService } from "./service.js";

const config = loadConfig();
const service = new TreeWikiService(config);
const html = await readFile(resolve(config.pluginRoot, "web", "dist", "workbench.html"), "utf8");
const app = createMcpExpressApp({ host: config.host });
app.use(express.json({ limit: "1mb" }));
app.get("/health", (_request, response) => response.json({ status: "ok", product: "treewiki", version: "0.2.0" }));
app.all("/mcp", async (request, response) => {
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  response.on("close", () => void transport.close());
  await createTreeWikiServer(service, html).connect(transport);
  await transport.handleRequest(request, response, request.body);
});
app.listen(config.port, config.host, () => console.log(`TreeWiki HTTP MCP: http://${config.host}:${config.port}/mcp`));
