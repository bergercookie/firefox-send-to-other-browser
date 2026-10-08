import { test } from "node:test";
import assert from "node:assert/strict";
import { isSendableUrl, partitionTabs, getSelectedTabs } from "../../extension/lib/sendable.js";

test("isSendableUrl accepts only http(s)", () => {
  assert.ok(isSendableUrl("https://example.com/x"));
  assert.ok(isSendableUrl("http://localhost:3000"));
  for (const u of ["about:config", "moz-extension://a/b.html", "file:///x", "javascript:1", "", undefined, "nope"]) {
    assert.equal(isSendableUrl(u), false, String(u));
  }
});

test("partitionTabs separates, de-duplicates and keeps order", () => {
  const tabs = [
    { id: 1, url: "https://a.example/" },
    { id: 2, url: "about:blank" },
    { id: 3, url: "https://b.example/" },
    { id: 4, url: "https://a.example/" },
  ];
  const { urls, sendableTabs, skipped } = partitionTabs(tabs);
  assert.deepEqual(urls, ["https://a.example/", "https://b.example/"]);
  assert.deepEqual(sendableTabs.map((t) => t.id), [1, 3, 4]);
  assert.deepEqual(skipped.map((t) => t.id), [2]);
});

const fakeTabs = (highlighted) => ({
  queries: [],
  async query(q) {
    this.queries.push(q);
    return highlighted;
  },
});

test("getSelectedTabs uses the highlighted tabs of the current window", async () => {
  const api = fakeTabs([{ id: 1 }, { id: 2 }]);
  assert.deepEqual(await getSelectedTabs(api), [{ id: 1 }, { id: 2 }]);
  assert.deepEqual(api.queries, [{ highlighted: true, currentWindow: true }]);
});

test("getSelectedTabs from the tab menu keeps the selection if the clicked tab is in it", async () => {
  const api = fakeTabs([{ id: 1 }, { id: 2 }]);
  assert.deepEqual(await getSelectedTabs(api, { id: 2, windowId: 9 }), [{ id: 1 }, { id: 2 }]);
  assert.deepEqual(api.queries, [{ highlighted: true, windowId: 9 }]);
});

test("getSelectedTabs from the tab menu falls back to the clicked tab alone", async () => {
  const clicked = { id: 5, windowId: 9 };
  assert.deepEqual(await getSelectedTabs(fakeTabs([{ id: 1 }, { id: 2 }]), clicked), [clicked]);
});
