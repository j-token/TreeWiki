import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(pluginRoot, "..", "..");
const paths = [
  "plugins/treewiki/plugin.json",
  "plugins/treewiki/.codex-plugin/plugin.json",
  "plugins/treewiki/package.json",
  "plugins/treewiki/package-lock.json",
  "plugins/treewiki/skills/treewiki/SKILL.md",
  "plugins/treewiki/skills/treewiki/scripts/treewiki_cli.py",
  "plugins/treewiki/skills/treewiki/scripts/treewiki_core.py",
  "plugins/treewiki/dist/treewiki-mcp.mjs",
  "plugins/treewiki-claude/.claude-plugin/plugin.json",
  "plugins/treewiki-claude/skills/route/SKILL.md",
  "plugins/treewiki-claude/runtime/runtime-manifest.json",
];
const files = {};
for (const path of paths) {
  const content = await readFile(resolve(repositoryRoot, path));
  files[path] = `sha256:${createHash("sha256").update(content).digest("hex")}`;
}
const output = resolve(pluginRoot, "release-manifest.json");
await writeFile(output, `${JSON.stringify({ schema: "treewiki.release/v1", version: "0.3.0", files }, null, 2)}\n`, "utf8");
console.log(`Built ${relative(repositoryRoot, output)} for TreeWiki 0.3.0`);
