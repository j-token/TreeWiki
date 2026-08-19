import type { BindingChangeInput } from "./bindings.js";
import { BindingStore } from "./bindings.js";
import type { PluginRuntimeConfig } from "./config.js";
import { TreeWikiCore, type ReviewDecision } from "./core.js";

export class TreeWikiService {
  readonly bindings: BindingStore;
  constructor(readonly config: PluginRuntimeConfig) { this.bindings = new BindingStore(config.dataDirectory); }
  private async core(bindingId: string): Promise<TreeWikiCore> {
    return new TreeWikiCore(this.config, await this.bindings.get(bindingId));
  }
  listBindings() { return this.bindings.list(); }
  planBindingChange(input: BindingChangeInput) { return this.bindings.plan(input); }
  applyBindingChange(planId: string, bindingDigest: string) { return this.bindings.apply(planId, bindingDigest); }
  async overview(bindingId: string) { return (await this.core(bindingId)).overview(); }
  async search(bindingId: string, query: string) { return (await this.core(bindingId)).search(query); }
  async fetch(bindingId: string, documentId: string) { return (await this.core(bindingId)).fetch(documentId); }
  async history(bindingId: string, documentId: string) { return (await this.core(bindingId)).history(documentId); }
  async candidates(bindingId: string, ids?: string[]) { return (await this.core(bindingId)).listL3Candidates(ids); }
  async planReview(bindingId: string, id: string, decision: ReviewDecision) {
    return (await this.core(bindingId)).planL3Review(id, decision);
  }
  async applyReview(bindingId: string, input: { id: string; decision: ReviewDecision; candidateDigest: string; planId: string }) {
    const core = await this.core(bindingId);
    if ((await core.overview()).upgradeRequired) throw new Error("upgrade is required; L3 writes are disabled until it is complete");
    return core.applyL3Review(input);
  }
  async planUpgrade(bindingId: string, stage: string) { return (await this.core(bindingId)).planUpgradeStage(stage); }
  async applyUpgrade(bindingId: string, stage: string, planId: string, statusDigest: string) {
    return (await this.core(bindingId)).applyUpgradeStage(stage, planId, statusDigest);
  }
}
