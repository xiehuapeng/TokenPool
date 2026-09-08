import assert from "node:assert/strict";
import test from "node:test";
import { createLatestRequest } from "../src/utils/latestRequest.ts";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function queryState() {
  const state = { loading: false, accepted: [], errors: [] };
  const query = createLatestRequest(
    (loading) => { state.loading = loading; },
    (error) => { state.errors.push(error); },
  );
  return { state, query, accept: (result) => state.accepted.push(result) };
}

test("a slow old refresh cannot overwrite the new filter or page results", async () => {
  const { state, query, accept } = queryState();
  const old = deferred();
  const next = deferred();
  const oldRun = query.run(() => old.promise, accept);
  const newRun = query.run(() => next.promise, accept);
  next.resolve({ page: 2, items: ["new"], total: 51 });
  await newRun;
  assert.equal(state.loading, false);
  old.resolve({ page: 1, items: ["old"], total: 50 });
  await oldRun;
  assert.deepEqual(state.accepted, [{ page: 2, items: ["new"], total: 51 }]);
});

test("an older completion does not clear loading while the latest request is pending", async () => {
  const { state, query, accept } = queryState();
  const old = deferred();
  const next = deferred();
  const oldRun = query.run(() => old.promise, accept);
  const newRun = query.run(() => next.promise, accept);
  old.resolve("old");
  await oldRun;
  assert.equal(state.loading, true);
  assert.deepEqual(state.accepted, []);
  next.resolve("new");
  await newRun;
  assert.equal(state.loading, false);
  assert.deepEqual(state.accepted, ["new"]);
});

test("an obsolete request failure does not show an error or end the current loading state", async () => {
  const { state, query, accept } = queryState();
  const old = deferred();
  const next = deferred();
  const oldRun = query.run(() => old.promise, accept);
  const newRun = query.run(() => next.promise, accept);
  old.reject(new Error("old filter timed out"));
  await oldRun;
  assert.deepEqual(state.errors, []);
  assert.equal(state.loading, true);
  next.resolve("new");
  await newRun;
  assert.deepEqual(state.accepted, ["new"]);
});

test("the latest failure is reported and a late old success cannot replace it", async () => {
  const { state, query, accept } = queryState();
  const old = deferred();
  const next = deferred();
  const oldRun = query.run(() => old.promise, accept);
  const newRun = query.run(() => next.promise, accept);
  const failure = new Error("current request failed");
  next.reject(failure);
  await newRun;
  assert.deepEqual(state.errors, [failure]);
  assert.equal(state.loading, false);
  old.resolve("old");
  await oldRun;
  assert.deepEqual(state.accepted, []);
});

test("closing a detail panel or unmounting invalidates its pending response", async () => {
  const { state, query, accept } = queryState();
  const old = deferred();
  const pending = query.run(() => old.promise, accept);
  query.invalidate();
  assert.equal(state.loading, false);
  old.resolve("closed user's detail");
  await pending;
  assert.deepEqual(state.accepted, []);
  await query.run(async () => "new user's detail", accept);
  assert.deepEqual(state.accepted, ["new user's detail"]);
});

test("statistics and logs track their loading state independently", async () => {
  const stats = queryState();
  const logs = queryState();
  const nextStats = deferred();
  const nextLogs = deferred();
  const statsRun = stats.query.run(() => nextStats.promise, stats.accept);
  const logsRun = logs.query.run(() => nextLogs.promise, logs.accept);
  nextLogs.resolve("logs");
  await logsRun;
  assert.equal(logs.state.loading, false);
  assert.equal(stats.state.loading, true);
  nextStats.resolve("stats");
  await statsRun;
});
