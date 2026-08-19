import { createHash } from "node:crypto";
import { mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

export type BindingAction = "upsert" | "remove";
export type Binding = {
  id: string;
  repository: string;
  principal: string;
  team: string;
  documentBaseUrl?: string;
  createdAt: string;
  modifiedAt: string;
};
export type BindingChangeInput = {
  action: BindingAction;
  repository: string;
  principal: string;
  team: string;
  documentBaseUrl?: string;
};
export type BindingPlan = {
  schema: "treewiki.binding-plan/v1";
  planId: string;
  bindingDigest: string;
  storeDigest: string;
  action: BindingAction;
  binding: Binding;
  impact: string;
  applied: false;
};

type BindingFile = { schema: "treewiki.bindings/v1"; bindings: Binding[] };

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function digest(value: unknown): string {
  return `sha256:${createHash("sha256").update(canonical(value), "utf8").digest("hex")}`;
}

function validateIdentity(principal: string, team: string): void {
  if (!/^user:[^\s:][^\s]*$/u.test(principal)) throw new Error("principal must use user:<subject>");
  if (!/^team:[^\s:][^\s]*$/u.test(team)) throw new Error("team must use team:<subject>");
}

function validateDocumentBaseUrl(value?: string): void {
  if (!value) return;
  const parsed = new URL(value);
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error("documentBaseUrl must use http or https");
}

function bindingId(repository: string, principal: string, team: string): string {
  return `binding-${digest({ repository, principal, team }).slice(7, 27)}`;
}

export class BindingStore {
  private readonly path: string;
  private readonly pending = new Map<string, BindingPlan>();

  constructor(private readonly dataDirectory: string) {
    this.path = resolve(dataDirectory, "bindings.json");
  }

  private async read(): Promise<BindingFile> {
    try {
      const parsed = JSON.parse(await readFile(this.path, "utf8")) as BindingFile;
      if (parsed.schema !== "treewiki.bindings/v1" || !Array.isArray(parsed.bindings)) {
        throw new Error("bindings.json has an unsupported schema");
      }
      return parsed;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        return { schema: "treewiki.bindings/v1", bindings: [] };
      }
      throw new Error(`bindings.json is unreadable; it was not changed: ${(error as Error).message}`);
    }
  }

  async list(): Promise<Binding[]> {
    return [...(await this.read()).bindings].sort((left, right) => left.id.localeCompare(right.id));
  }

  async get(id: string): Promise<Binding> {
    const binding = (await this.list()).find((item) => item.id === id);
    if (!binding) throw new Error(`unknown bindingId: ${id}`);
    return binding;
  }

  async plan(input: BindingChangeInput): Promise<BindingPlan> {
    const repository = resolve(input.repository);
    validateIdentity(input.principal, input.team);
    validateDocumentBaseUrl(input.documentBaseUrl);
    const repositoryStat = await stat(repository).catch(() => null);
    if (!repositoryStat?.isDirectory()) throw new Error(`repository does not exist: ${repository}`);
    const current = await this.read();
    const id = bindingId(repository, input.principal, input.team);
    const existing = current.bindings.find((item) => item.id === id);
    if (input.action === "remove" && !existing) throw new Error(`binding does not exist: ${id}`);
    const now = new Date().toISOString();
    const binding: Binding = {
      id,
      repository,
      principal: input.principal,
      team: input.team,
      ...(input.documentBaseUrl ? { documentBaseUrl: input.documentBaseUrl.replace(/\/$/u, "") } : {}),
      createdAt: existing?.createdAt ?? now,
      modifiedAt: now,
    };
    const bindingDigest = digest(binding);
    const storeDigest = digest(current);
    const planId = digest({ action: input.action, bindingDigest, storeDigest });
    const plan: BindingPlan = {
      schema: "treewiki.binding-plan/v1",
      planId,
      bindingDigest,
      storeDigest,
      action: input.action,
      binding,
      impact: input.action === "remove" ? `Remove ${id}` : `${existing ? "Update" : "Add"} ${id}`,
      applied: false,
    };
    this.pending.set(planId, plan);
    return plan;
  }

  async apply(planId: string, bindingDigest: string): Promise<{ binding: Binding; action: BindingAction; applied: true }> {
    const plan = this.pending.get(planId);
    if (!plan || plan.bindingDigest !== bindingDigest) throw new Error("binding plan or digest is stale or unknown");
    const current = await this.read();
    if (digest(current) !== plan.storeDigest) throw new Error("binding store changed after the plan was created");
    const withoutTarget = current.bindings.filter((item) => item.id !== plan.binding.id);
    const next: BindingFile = {
      schema: "treewiki.bindings/v1",
      bindings: plan.action === "remove" ? withoutTarget : [...withoutTarget, plan.binding],
    };
    await mkdir(this.dataDirectory, { recursive: true });
    const temporary = resolve(this.dataDirectory, `.bindings.${process.pid}.${Date.now()}.tmp`);
    try {
      await writeFile(temporary, `${JSON.stringify(next, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
      JSON.parse(await readFile(temporary, "utf8"));
      await rename(temporary, this.path);
    } finally {
      await rm(temporary, { force: true }).catch(() => undefined);
    }
    this.pending.delete(planId);
    return { binding: plan.binding, action: plan.action, applied: true };
  }
}
