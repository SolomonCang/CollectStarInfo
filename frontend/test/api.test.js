import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { listStars, queryTarget } from "../src/api.js";

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
  assert.equal(request.options.headers.get("Content-Type"), "application/json");
  assert.deepEqual(JSON.parse(request.options.body), {
    target: "AD Leo",
    use_llm: false,
    force_refresh: false,
  });
});

test("API errors expose FastAPI detail instead of raw response JSON", async () => {
  globalThis.fetch = async () => new Response(
    JSON.stringify({ detail: "Target not found" }),
    {
      status: 404,
      headers: { "Content-Type": "application/json" },
    }
  );

  await assert.rejects(
    () => queryTarget({ target: "missing" }),
    /Target not found/
  );
});
