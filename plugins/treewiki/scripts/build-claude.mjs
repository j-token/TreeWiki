import { createHash } from "node:crypto";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(pluginRoot, "..", "..");
const claudeRoot = resolve(repositoryRoot, "plugins", "treewiki-claude");
const runtime = resolve(claudeRoot, "runtime");
const vendor = resolve(claudeRoot, "vendor");
const route = resolve(claudeRoot, "skills", "route");
for (const target of [runtime, vendor, route]) {
  if (!target.startsWith(`${claudeRoot}\\`) && !target.startsWith(`${claudeRoot}/`)) throw new Error("refusing to replace outside Claude plugin root");
  await rm(target, { recursive: true, force: true });
}
await Promise.all([mkdir(runtime, { recursive: true }), mkdir(route, { recursive: true })]);
const sourceRuntime = resolve(pluginRoot, "skills", "treewiki", "scripts");
const files = ["treewiki_cli.py", "treewiki_core.py"];
const hashes = {};
for (const name of files) {
  const source = resolve(sourceRuntime, name);
  const content = await readFile(source);
  await writeFile(resolve(runtime, name), content);
  hashes[name] = `sha256:${createHash("sha256").update(content).digest("hex")}`;
}
await cp(resolve(pluginRoot, "vendor", "yaml"), resolve(vendor, "yaml"), { recursive: true });
await cp(resolve(pluginRoot, "vendor", "PyYAML-LICENSE"), resolve(vendor, "PyYAML-LICENSE"));
await cp(resolve(pluginRoot, "skills", "treewiki", "assets", "claude-route.md"), resolve(route, "SKILL.md"));
await writeFile(resolve(runtime, "runtime-manifest.json"), `${JSON.stringify({
  schema: "treewiki.adapter-runtime/v2", release_version: "0.3.0", files: hashes,
}, null, 2)}\n`, "utf8");
console.log("Built TreeWiki 0.3 Claude runtime from Agent Plugin sources");
