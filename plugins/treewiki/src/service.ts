import type { PluginRuntimeConfig } from "./config.js";
import { TreeWikiCore } from "./core.js";
import { WorkspaceStore } from "./workspaces.js";

export class TreeWikiService {
  private readonly workspaces: WorkspaceStore;
  constructor(private readonly config: PluginRuntimeConfig) { this.workspaces = new WorkspaceStore(config.dataDirectory); }
  private async core(workspaceId: string): Promise<TreeWikiCore> {
    return new TreeWikiCore(this.config, await this.workspaces.get(workspaceId));
  }
  async connect(repository: string) {
    const workspace = await this.workspaces.connect(repository);
    return { workspace, status: await new TreeWikiCore(this.config, workspace).status() };
  }
  async status(workspaceId: string) { return (await this.core(workspaceId)).status(); }
  async search(workspaceId: string, query: string, limit?: number) { return (await this.core(workspaceId)).search(query, limit); }
  async read(workspaceId: string, reference: string) { return (await this.core(workspaceId)).read(reference); }
  async history(workspaceId: string, id: string) { return (await this.core(workspaceId)).history(id); }
  async validate(workspaceId: string) { return (await this.core(workspaceId)).validate(); }
}
