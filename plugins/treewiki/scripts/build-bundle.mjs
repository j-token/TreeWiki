import { build } from "esbuild";
import { readFile, writeFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = resolve(root, "dist", "treewiki-mcp.mjs");
await build({ entryPoints: [resolve(root, "src", "stdio.ts")], outfile: output,
  bundle: true, platform: "node", format: "esm", target: "node18", sourcemap: false, minify: false,
  banner: { js: "#!/usr/bin/env node\nimport { createRequire as __treewikiCreateRequire } from 'node:module'; const require = __treewikiCreateRequire(import.meta.url);" } });
const bundled = await readFile(output, "utf8");
await writeFile(output, `${bundled.split(/\r?\n/u).map((line) => line.trimEnd()).join("\n").trimEnd()}\n`, "utf8");
console.log("Bundled dependency-free TreeWiki stdio MCP");
