import { rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const target = resolve(root, "dist");
if (dirname(target) !== root) throw new Error("refusing to clean outside the plugin root");
await rm(target, { recursive: true, force: true });
