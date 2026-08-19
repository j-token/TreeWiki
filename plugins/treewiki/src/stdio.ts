import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { loadConfig } from "./config.js";
import { createTreeWikiServer } from "./server.js";
import { TreeWikiService } from "./service.js";

const config = loadConfig();
const html = await readFile(resolve(config.pluginRoot, "web", "dist", "workbench.html"), "utf8");
await createTreeWikiServer(new TreeWikiService(config), html).connect(new StdioServerTransport());
