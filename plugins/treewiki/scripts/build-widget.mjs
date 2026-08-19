import { copyFile, mkdir, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Script } from "node:vm";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = resolve(root, "web", "src", "workbench.html");
const html = await readFile(source, "utf8");
const inlineScript = html.match(/<script>([\s\S]*?)<\/script>/u)?.[1];
if (!inlineScript) throw new Error("Workbench inline script is missing");
new Script(inlineScript, { filename: "workbench.inline.js" });
await mkdir(resolve(root, "web", "dist"), { recursive: true });
await copyFile(source, resolve(root, "web", "dist", "workbench.html"));
console.log("Built TreeWiki Workbench");
