import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { loadConfig } from "./config.js";
import { createTreeWikiServer } from "./server.js";
import { TreeWikiService } from "./service.js";

const config = loadConfig();
await createTreeWikiServer(new TreeWikiService(config)).connect(new StdioServerTransport());
