import { spawn } from "node:child_process";
import { delimiter, resolve } from "node:path";
import { parse as parseYaml } from "yaml";
import { digest, type Binding } from "./bindings.js";
import type { PluginRuntimeConfig } from "./config.js";

export type CommandResult = { stdout: string; stderr: string; exitCode: number };
export type CommandExecutor = (program: string, args: string[]) => Promise<CommandResult>;
export type SearchHit = { id: string; title: string; url: string };
export type ReviewDecision = "activate" | "reject" | "supersede";
export type L3Candidate = {
  id: string; title: string; summary: string; body: string;
  category: "knowledge" | "persona"; kind: string; scope: string; subject: string;
  evidenceIds: string[]; supersedesIds: string[]; candidateDigest: string;
};

export class TreeWikiCommandError extends Error {
  constructor(message: string, readonly exitCode: number, readonly stderr: string, readonly stdout: string) {
    super(message);
    this.name = "TreeWikiCommandError";
  }
}

export function createCommandExecutor(config: PluginRuntimeConfig): CommandExecutor {
  return (program, args) => new Promise((resolvePromise, reject) => {
    const pythonPath = [config.vendorDirectory, process.env.PYTHONPATH].filter(Boolean).join(delimiter);
    const child = spawn(program, args, {
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: "1", PYTHONPATH: pythonPath },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => (stdout += chunk));
    child.stderr.on("data", (chunk: string) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (code) => resolvePromise({ stdout, stderr, exitCode: code ?? 1 }));
  });
}

export function parseJsonLines<T>(text: string): T[] {
  return text.split(/\r?\n/u).map((line) => line.trim()).filter(Boolean).map((line) => JSON.parse(line) as T);
}

export function parseMarkdownDocument(text: string): { metadata: Record<string, unknown>; body: string } {
  const match = text.replace(/\r\n/g, "\n").match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/u);
  if (!match) throw new Error("TreeWiki document is missing YAML front matter");
  const metadata = parseYaml(match[1]);
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) throw new Error("front matter is not a mapping");
  return { metadata: metadata as Record<string, unknown>, body: match[2].trim() };
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function relationIds(value: unknown, type: string): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => objectValue(item).type === type)
    .map((item) => objectValue(item).target).filter((item): item is string => typeof item === "string").sort();
}
const REPOSITORY_APPLY_STAGES = new Set(["config", "document-history", "adapters", "index"]);

export class TreeWikiCore {
  private readonly executor: CommandExecutor;
  constructor(readonly config: PluginRuntimeConfig, readonly binding: Binding, executor?: CommandExecutor) {
    this.executor = executor ?? createCommandExecutor(config);
  }
  private identityArgs(): string[] { return ["--principal", this.binding.principal, "--team", this.binding.team]; }
  private async run(args: string[], allowed = [0]): Promise<string> {
    const result = await this.executor(this.config.python, [resolve(this.config.runtimeDirectory, "knowledge_cli.py"), ...args]);
    if (!allowed.includes(result.exitCode)) {
      let message = result.stderr.trim() || result.stdout.trim() || "TreeWiki command failed";
      try { message = JSON.parse(result.stderr.trim() || result.stdout.trim())?.error?.message ?? message; } catch { /* text error */ }
      throw new TreeWikiCommandError(message, result.exitCode, result.stderr, result.stdout);
    }
    return result.stdout;
  }
  private documentUrl(id: string, path?: string): string {
    if (!this.binding.documentBaseUrl) return `treewiki://document/${encodeURIComponent(id)}`;
    const suffix = (path || id).split("/").map(encodeURIComponent).join("/");
    return `${this.binding.documentBaseUrl}/${suffix}`;
  }
  async listDocuments(): Promise<Array<Record<string, unknown>>> {
    return parseJsonLines(await this.run(["query", "list", this.binding.repository, "--include-inactive", "--json", ...this.identityArgs()]));
  }
  async readDocument(id: string) {
    return parseMarkdownDocument(await this.run(["query", "read", this.binding.repository, id, ...this.identityArgs()]));
  }
  async search(query: string): Promise<SearchHit[]> {
    const [output, documents] = await Promise.all([
      this.run(["query", "search", this.binding.repository, query, "--limit", "12", "--json", ...this.identityArgs()]),
      this.listDocuments(),
    ]);
    const byId = new Map(documents.map((item) => [String(item.id), item]));
    return parseJsonLines<Record<string, unknown>>(output).map((hit) => {
      const id = String(hit.id); const document = byId.get(id) ?? {};
      return { id, title: String(document.title ?? id), url: this.documentUrl(id, String(hit.path ?? document.path ?? id)) };
    });
  }
  async fetch(id: string) {
    const [{ metadata, body }, documents] = await Promise.all([this.readDocument(id), this.listDocuments()]);
    const listed = documents.find((item) => item.id === id);
    return {
      id, title: String(metadata.title ?? id), text: body,
      url: this.documentUrl(id, typeof listed?.path === "string" ? listed.path : undefined),
      metadata: { type: metadata.type, status: metadata.status, summary: metadata.summary, created_at: metadata.created_at,
        modified_at: metadata.modified_at, verified_at: metadata.verified_at, revision: metadata.revision },
    };
  }
  async history(id: string): Promise<unknown> {
    return JSON.parse(await this.run(["query", "history", this.binding.repository, "--id", id, "--json", ...this.identityArgs()]));
  }
  async listL3Candidates(ids?: string[]): Promise<L3Candidate[]> {
    const selected = new Set(ids ?? []);
    const documents = (await this.listDocuments()).filter((item) => item.status === "proposed" &&
      (item.type === "memory" || item.type === "persona") && (!selected.size || selected.has(String(item.id))));
    const candidates = await Promise.all(documents.map(async (item): Promise<L3Candidate | null> => {
      const id = String(item.id); const { metadata, body } = await this.readDocument(id); const memory = objectValue(metadata.memory);
      if (memory.level !== "l3") return null; const sharing = objectValue(metadata.sharing);
      return { id, title: String(metadata.title ?? id), summary: String(metadata.summary ?? ""), body,
        category: metadata.type === "persona" ? "persona" : "knowledge",
        kind: String(memory.kind ?? (metadata.type === "persona" ? "preference" : "information")),
        scope: String(memory.scope ?? "repo"), subject: String(memory.subject ?? ""),
        evidenceIds: relationIds(metadata.relations, "distilled_from"), supersedesIds: relationIds(metadata.relations, "supersedes"),
        candidateDigest: String(sharing.evidence_digest ?? "") };
    }));
    return candidates.filter((item): item is L3Candidate => item !== null).sort((a, b) => a.id.localeCompare(b.id));
  }
  async overview() {
    const [documents, candidates, upgrade] = await Promise.all([this.listDocuments(), this.listL3Candidates(), this.upgradeStatus()]);
    const overall = objectValue(upgrade.overall);
    return { adopted: documents.length > 0, documentCount: documents.length, candidateCount: candidates.length,
      upgradeRequired: String(overall.status ?? "current") !== "current", upgrade };
  }
  async planL3Review(id: string, decision: ReviewDecision): Promise<Record<string, unknown>> {
    const candidate = (await this.listL3Candidates([id]))[0];
    if (!candidate) throw new Error("L3 candidate was not found or is not reviewable");
    return JSON.parse(await this.run(["manage", "l3-review", this.binding.repository, id, "--candidate-digest", candidate.candidateDigest,
      "--decision", decision, "--json", ...this.identityArgs()]));
  }
  async applyL3Review(input: { id: string; decision: ReviewDecision; candidateDigest: string; planId: string }) {
    return JSON.parse(await this.run(["manage", "l3-review", this.binding.repository, input.id, "--candidate-digest", input.candidateDigest,
      "--decision", input.decision, "--plan-id", input.planId, "--apply", "--json", ...this.identityArgs()]));
  }
  async upgradeStatus(stage?: string): Promise<Record<string, unknown>> {
    const args = ["manage", "upgrade-status", this.binding.repository, "--offline", "--json", ...this.identityArgs()];
    if (stage) args.splice(4, 0, "--stage", stage);
    return JSON.parse(await this.run(args, [0, 2, 3]));
  }
  async planUpgradeStage(stage: string) {
    const report = await this.upgradeStatus(stage); const overall = objectValue(report.overall);
    return { schema: "treewiki.upgrade-plan/v1", stage, planId: String(overall.plan_id ?? ""),
      statusDigest: digest(report), report, applyAllowed: REPOSITORY_APPLY_STAGES.has(stage) && overall.apply_allowed === true,
      blockingReason: REPOSITORY_APPLY_STAGES.has(stage) ? String(overall.blocking_reason ?? "") :
        `${stage} requires chat approval because it may change global skills, hooks, or governed memory.` };
  }
  async applyUpgradeStage(stage: string, planId: string, statusDigest: string) {
    const current = await this.planUpgradeStage(stage);
    if (!current.applyAllowed) throw new Error(current.blockingReason || "this upgrade stage cannot be applied through the native MCP tool");
    if (current.planId !== planId || current.statusDigest !== statusDigest) throw new Error("upgrade plan or status digest is stale");
    return JSON.parse(await this.run(["manage", "upgrade", this.binding.repository, "--stage", stage, "--plan-id", planId,
      "--offline", "--apply", "--json", ...this.identityArgs()], [0, 2]));
  }
}
