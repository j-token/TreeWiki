import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { test } from "node:test";
import { BindingStore } from "../src/bindings.js";

async function fixture() {
  const root = await mkdtemp(resolve(tmpdir(), "treewiki-bindings-"));
  const repository = resolve(root, "repo"); const data = resolve(root, "data"); await mkdir(repository);
  return { root, repository, data, store: new BindingStore(data) };
}

test("binding change is a two-step atomic operation", async () => {
  const f = await fixture();
  try {
    const plan = await f.store.plan({ action: "upsert", repository: f.repository, principal: "user:test", team: "team:repo" });
    assert.deepEqual(await f.store.list(), []);
    await assert.rejects(() => f.store.apply(plan.planId, `sha256:${"0".repeat(64)}`), /stale or unknown/u);
    const applied = await f.store.apply(plan.planId, plan.bindingDigest);
    assert.equal(applied.applied, true); assert.equal((await f.store.list())[0].principal, "user:test");
    const secondRepository = resolve(f.root, "repo-two"); await mkdir(secondRepository);
    const second = await f.store.plan({ action: "upsert", repository: secondRepository, principal: "user:test", team: "team:repo" });
    await f.store.apply(second.planId, second.bindingDigest);
    assert.equal((await f.store.list()).length, 2);
    const stale = await f.store.plan({ action: "remove", repository: f.repository, principal: "user:test", team: "team:repo" });
    const update = await f.store.plan({ action: "upsert", repository: secondRepository, principal: "user:test", team: "team:repo", documentBaseUrl: "https://example.test/docs" });
    await f.store.apply(update.planId, update.bindingDigest);
    await assert.rejects(() => f.store.apply(stale.planId, stale.bindingDigest), /changed after the plan/u);
  } finally { await rm(f.root, { recursive: true, force: true }); }
});

test("corrupt settings are reported and never overwritten", async () => {
  const f = await fixture();
  try {
    await mkdir(f.data); await writeFile(resolve(f.data, "bindings.json"), "{broken", "utf8");
    await assert.rejects(() => f.store.list(), /was not changed/u);
    assert.equal(await readFile(resolve(f.data, "bindings.json"), "utf8"), "{broken");
  } finally { await rm(f.root, { recursive: true, force: true }); }
});

test("repository and ACL identities are validated before planning", async () => {
  const f = await fixture();
  try {
    await assert.rejects(() => f.store.plan({ action: "upsert", repository: f.repository, principal: "admin", team: "team:repo" }), /principal/u);
    await assert.rejects(() => f.store.plan({ action: "upsert", repository: resolve(f.root, "missing"), principal: "user:test", team: "team:repo" }), /does not exist/u);
  } finally { await rm(f.root, { recursive: true, force: true }); }
});
