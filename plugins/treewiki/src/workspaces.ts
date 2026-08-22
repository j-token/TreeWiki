import { createHash } from "node:crypto";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

export type Workspace = { id: string; repository: string; createdAt: string; modifiedAt: string };
type StorePayload = { version: 1; workspaces: Workspace[] };

function workspaceId(repository: string): string {
  return `workspace-${createHash("sha256").update(repository).digest("hex").slice(0, 20)}`;
}

export class WorkspaceStore {
  private readonly path: string;
  constructor(dataDirectory: string) { this.path = resolve(dataDirectory, "workspaces.json"); }

  private async load(): Promise<StorePayload> {
    try {
      const payload = JSON.parse(await readFile(this.path, "utf8")) as StorePayload;
      if (payload.version !== 1 || !Array.isArray(payload.workspaces)) throw new Error("invalid workspace store");
      return payload;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return { version: 1, workspaces: [] };
      throw error;
    }
  }

  private async save(payload: StorePayload): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true });
    await writeFile(this.path, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  }

  async connect(repositoryInput: string): Promise<Workspace> {
    const repository = resolve(repositoryInput);
    const repositoryStat = await stat(repository).catch(() => null);
    if (!repositoryStat?.isDirectory()) throw new Error(`workspace does not exist: ${repository}`);
    const payload = await this.load();
    const now = new Date().toISOString();
    const id = workspaceId(repository);
    const existing = payload.workspaces.find((item) => item.id === id);
    const workspace: Workspace = existing
      ? { ...existing, repository, modifiedAt: now }
      : { id, repository, createdAt: now, modifiedAt: now };
    payload.workspaces = [...payload.workspaces.filter((item) => item.id !== id), workspace]
      .sort((left, right) => left.repository.localeCompare(right.repository));
    await this.save(payload);
    return workspace;
  }

  async get(id: string): Promise<Workspace> {
    const workspace = (await this.load()).workspaces.find((item) => item.id === id);
    if (!workspace) throw new Error(`unknown workspace: ${id}`);
    const workspaceStat = await stat(workspace.repository).catch(() => null);
    if (!workspaceStat?.isDirectory()) throw new Error(`workspace no longer exists: ${workspace.repository}`);
    return workspace;
  }
}
