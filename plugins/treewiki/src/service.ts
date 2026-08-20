import type { BindingChangeInput } from "./bindings.js";
import { BindingStore } from "./bindings.js";
import type { PluginRuntimeConfig } from "./config.js";
import { TreeWikiCore, type RetrievalGapInput, type ReviewDecision } from "./core.js";

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
  private async federation(bindingId: string) {
    const primary = await this.bindings.get(bindingId);
    const overlays = await Promise.all((primary.overlayBindingIds ?? []).map((id) => this.bindings.get(id)));
    if (overlays.some((item) => item.principal !== primary.principal || item.team !== primary.team)) {
      throw new Error("federated bindings no longer share the same ACL identity");
    }
    return [primary, ...overlays];
  }
  async federatedSearch(bindingId: string, query: string) {
    const bindings = await this.federation(bindingId);
    const batches = await Promise.all(bindings.map(async (binding) => ({ binding, hits: await (await this.core(binding.id)).search(query) })));
    const grouped = new Map<string, Array<{bindingId:string;repository:string;title:string;url:string}>>();
    for (const batch of batches) for (const hit of batch.hits) {
      const values = grouped.get(hit.id) ?? [];
      values.push({ bindingId: batch.binding.id, repository: batch.binding.repository, title: hit.title, url: hit.url });
      grouped.set(hit.id, values);
    }
    return [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([id, sources]) => ({
      id,
      title: sources[0]?.title ?? id,
      status: sources.length > 1 ? "conflict" : "matched",
      sources,
    }));
  }
  async fetchWithContext(bindingId: string, documentId: string) {
    const bindings = await this.federation(bindingId);
    const matches: Array<{bindingId:string;repository:string;document:unknown}> = [];
    for (const binding of bindings) {
      const core = await this.core(binding.id);
      const listed = await core.listDocuments();
      if (listed.some((item) => item.id === documentId)) {
        matches.push({ bindingId: binding.id, repository: binding.repository, document: await core.fetch(documentId) });
      }
    }
    if (!matches.length) throw new Error("document was not found through the ACL-approved federation");
    const texts = new Set(matches.map((item) => JSON.stringify(item.document)));
    return { id: documentId, status: texts.size > 1 ? "conflict" : "matched", sources: matches };
  }
  async fetch(bindingId: string, documentId: string) { return (await this.core(bindingId)).fetch(documentId); }
  async history(bindingId: string, documentId: string) { return (await this.core(bindingId)).history(documentId); }
  async planRetrievalGap(bindingId: string, input: RetrievalGapInput) { return (await this.core(bindingId)).planRetrievalGap(input); }
  async recordRetrievalGap(bindingId: string, input: RetrievalGapInput & {planId:string}) { return (await this.core(bindingId)).recordRetrievalGap(input); }
  async retrievalGaps(bindingId: string, status?: "open" | "resolved") { return (await this.core(bindingId)).listRetrievalGaps(status); }
  async governanceReport(bindingId: string) { return (await this.core(bindingId)).governanceReport(); }
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
