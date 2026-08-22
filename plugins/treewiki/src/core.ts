import { spawn } from "node:child_process";
import { delimiter, resolve } from "node:path";
import type { PluginRuntimeConfig } from "./config.js";
import type { Workspace } from "./workspaces.js";

export type CommandResult = { stdout: string; stderr: string; exitCode: number };
export type CommandExecutor = (program: string, args: string[]) => Promise<CommandResult>;

export class TreeWikiCommandError extends Error {
  constructor(message: string, readonly exitCode: number, readonly stdout: string) {
    super(message); this.name = "TreeWikiCommandError";
  }
}

export function createCommandExecutor(config: PluginRuntimeConfig): CommandExecutor {
  return (program, args) => new Promise((resolvePromise, reject) => {
    const pythonPath = [config.runtimeDirectory, config.vendorDirectory, process.env.PYTHONPATH].filter(Boolean).join(delimiter);
    const child = spawn(program, args, {
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: "1", PYTHONPATH: pythonPath },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = ""; let stderr = "";
    child.stdout.setEncoding("utf8"); child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => (stdout += chunk));
    child.stderr.on("data", (chunk: string) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (code) => resolvePromise({ stdout, stderr, exitCode: code ?? 1 }));
  });
}

export class TreeWikiCore {
  private readonly executor: CommandExecutor;
  constructor(readonly config: PluginRuntimeConfig, readonly workspace: Workspace, executor?: CommandExecutor) {
    this.executor = executor ?? createCommandExecutor(config);
  }

  private async run(command: string, args: string[] = []): Promise<Record<string, unknown>> {
    const result = await this.executor(this.config.python, [
      resolve(this.config.runtimeDirectory, "treewiki_cli.py"), command, this.workspace.repository, ...args,
    ]);
    let payload: Record<string, unknown> | undefined;
    try { payload = JSON.parse(result.stdout.trim()) as Record<string, unknown>; } catch { /* handled below */ }
    if (result.exitCode !== 0 || !payload) {
      const error = payload?.error as { message?: string } | undefined;
      const message = error?.message ?? (result.stderr.trim() || result.stdout.trim() || "TreeWiki command failed");
      throw new TreeWikiCommandError(message, result.exitCode, result.stdout);
    }
    return payload;
  }

  status() { return this.run("status"); }
  search(query: string, limit?: number) { return this.run("search", [query, ...(limit ? ["--limit", String(limit)] : [])]); }
  read(reference: string) { return this.run("read", [reference]); }
  history(id: string) { return this.run("history", [id]); }
  validate() { return this.run("validate"); }
}
