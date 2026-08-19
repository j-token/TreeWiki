import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type PluginRuntimeConfig = {
  pluginRoot: string;
  dataDirectory: string;
  python: string;
  runtimeDirectory: string;
  vendorDirectory: string;
  host: string;
  port: number;
};

export function resolvePluginRoot(moduleUrl = import.meta.url): string {
  const fromEnvironment = process.env.PLUGIN_ROOT?.trim();
  if (fromEnvironment) return resolve(fromEnvironment);
  return resolve(dirname(fileURLToPath(moduleUrl)), "..", "..");
}

export function loadConfig(pluginRoot = resolvePluginRoot()): PluginRuntimeConfig {
  const dataDirectory = resolve(
    process.env.PLUGIN_DATA?.trim() ||
      process.env.TREEWIKI_PLUGIN_DATA?.trim() ||
      resolve(pluginRoot, ".treewiki-plugin-data"),
  );
  const runtimeDirectory = resolve(pluginRoot, "skills", "treewiki", "scripts");
  if (!existsSync(resolve(runtimeDirectory, "knowledge_cli.py"))) {
    throw new Error("bundled TreeWiki runtime is missing; rebuild the adapter bundles");
  }
  const port = Number(process.env.PORT ?? "8787");
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("PORT must be an integer from 1 to 65535");
  }
  return {
    pluginRoot,
    dataDirectory,
    python: process.env.TREEWIKI_PYTHON?.trim() || "python",
    runtimeDirectory,
    vendorDirectory: resolve(pluginRoot, "vendor"),
    host: process.env.TREEWIKI_HOST?.trim() || "127.0.0.1",
    port,
  };
}
