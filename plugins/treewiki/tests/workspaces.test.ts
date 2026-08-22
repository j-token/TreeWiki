import assert from "node:assert/strict";
import { mkdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { mkdtemp } from "node:fs/promises";
import { test } from "node:test";
import { WorkspaceStore } from "../src/workspaces.js";

test("workspace connections are idempotent and isolated", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "treewiki-workspaces-"));
  try {
    const data = resolve(root, "data");
    const first = resolve(root, "first");
    const second = resolve(root, "second");
    await Promise.all([mkdir(first), mkdir(second)]);
    const store = new WorkspaceStore(data);
    const firstConnection = await store.connect(first);
    const same = await store.connect(first);
    const other = await store.connect(second);
    assert.equal(firstConnection.id, same.id);
    assert.notEqual(firstConnection.id, other.id);
    assert.equal((await store.get(other.id)).repository, second);
    await assert.rejects(() => store.get("workspace-00000000000000000000"), /unknown workspace/u);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
