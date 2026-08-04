import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { listStars, login, queryTarget, setCsrfToken } from "../src/api.js";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("listStars encodes filters and keeps GET requests simple", async () => {
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ stars: [], total: 0 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const result = await listStars({
    search: "AD Leo",
    source: "MAST/TESS",
    offset: 25,
    limit: 25,
  });

  assert.deepEqual(result, { stars: [], total: 0 });
  assert.equal(
    request.url,
    "/api/catalog/stars?search=AD+Leo&source=MAST%2FTESS&offset=25&limit=25"
  );
  assert.equal(request.options.headers.has("Content-Type"), false);
});

test("queryTarget forwards abort signals and JSON payloads", async () => {
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ target: { query_target: "AD Leo" } }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  const controller = new AbortController();

  await queryTarget(
    { target: "AD Leo", use_llm: false, force_refresh: false },
    { signal: controller.signal }
  );

  assert.equal(request.url, "/api/targets/query");
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.signal, controller.signal);
  assert.equal(request.options.credentials, "include");
  assert.equal(request.options.headers.get("Content-Type"), "application/json");
  assert.deepEqual(JSON.parse(request.options.body), {
    target: "AD Leo",
    use_llm: false,
    force_refresh: false,
  });
});

test("login stores a CSRF token and authenticated writes send it", async () => {
  const values = new Map();
  globalThis.sessionStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ user: { username: "alice", csrf_token: "csrf-1" } }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  await login({ username: "alice", password: "password" });
  await queryTarget({ target: "AD Leo" });
  assert.equal(requests[1].options.headers.get("X-CSRF-Token"), "csrf-1");
  delete globalThis.sessionStorage;
  setCsrfToken("");
});

test("API errors expose FastAPI detail instead of raw response JSON", async () => {
  globalThis.fetch = async () => new Response(
    JSON.stringify({ detail: "Target not found" }),
    {
      status: 404,
      headers: { "Content-Type": "application/json" },
    }
  );

  await assert.rejects(() => queryTarget({ target: "missing" }), (error) => {
    assert.match(error.message, /Target not found/);
    assert.equal(error.status, 404);
    return true;
  });
});
