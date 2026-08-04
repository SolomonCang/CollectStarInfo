const API_BASE = import.meta.env?.VITE_API_BASE ?? "";
const CSRF_KEY = "target-info-csrf";

export function setCsrfToken(value) {
  if (typeof sessionStorage === "undefined") return;
  if (value) sessionStorage.setItem(CSRF_KEY, value);
  else sessionStorage.removeItem(CSRF_KEY);
}

async function request(path, options) {
  const headers = new Headers(options?.headers);
  if (options?.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const csrf = typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem(CSRF_KEY);
  if (csrf && !headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", csrf);

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    let message = "";
    if (contentType.includes("application/json")) {
      const payload = await response.json().catch(() => null);
      const detail = payload?.detail ?? payload?.message ?? payload;
      message = typeof detail === "string" ? detail : JSON.stringify(detail);
    } else {
      message = await response.text();
    }
    const error = new Error(message || `Request failed: ${response.status}`);
    error.status = response.status;
    throw error;
  }

  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") ?? "";
  return contentType.includes("application/json")
    ? response.json()
    : response.text();
}

export async function login(payload) {
  const result = await request("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  setCsrfToken(result?.user?.csrf_token);
  return result;
}

export function getCurrentUser() {
  return request("/api/auth/me").then((result) => {
    setCsrfToken(result?.user?.csrf_token);
    return result;
  });
}

export async function logout() {
  try {
    return await request("/api/auth/logout", { method: "POST" });
  } finally {
    setCsrfToken("");
  }
}

export function changePassword(payload) {
  return request("/api/auth/change-password", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function queryTarget(payload, options = {}) {
  return request("/api/targets/query", {
    ...options,
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function researchLiterature(payload, options = {}) {
  return request("/api/literature/research", {
    ...options,
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function analyzeLightCurve(payload) {
  return request("/api/lightcurves/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function searchLightCurves(payload) {
  return request("/api/lightcurves/search", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function downloadLightCurves(payload) {
  return request("/api/lightcurves/download", {
    method: "POST",
    body: JSON.stringify({ ...payload, force: payload.force ?? false }),
  });
}

export function listLightCurveDatasets(target, options) {
  const params = target ? `?target=${encodeURIComponent(target)}` : "";
  return request(`/api/lightcurves/datasets${params}`, options);
}

export function deleteLightCurveDataset(downloadDir) {
  return request("/api/lightcurves/datasets/delete", {
    method: "POST",
    body: JSON.stringify({ download_dir: downloadDir }),
  });
}

export function getLightCurveCacheStats() {
  return request("/api/lightcurves/cache/stats");
}

export function verifyLightCurveCache(payload = {}) {
  return request("/api/lightcurves/cache/verify", {
    method: "POST",
    body: JSON.stringify({ deep: false, repair: false, ...payload }),
  });
}

export function cleanupLightCurveCache(payload) {
  return request("/api/lightcurves/cache/cleanup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function analyzeDownloadedLightCurve(payload) {
  return request("/api/lightcurves/analyze-dataset", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ── Catalog / Data Manager ─────────────────────────────────────

export function getCatalogStats(options) {
  return request("/api/catalog/stats", options);
}

export function listCatalogEntries(payload = {}) {
  return request("/api/catalog/entries", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCatalogEntry(entryId) {
  return request(`/api/catalog/entries/${encodeURIComponent(entryId)}`);
}

export function deleteCatalogEntry(entryId) {
  return request(`/api/catalog/entries/${encodeURIComponent(entryId)}`, {
    method: "DELETE",
  });
}

export function batchDeleteCatalogEntries(entryIds) {
  return request("/api/catalog/entries/batch-delete", {
    method: "POST",
    body: JSON.stringify({ entry_ids: entryIds }),
  });
}

export function rebuildCatalog() {
  return request("/api/catalog/rebuild", {
    method: "POST",
  });
}

export function listStars(params = {}, options) {
  const qs = new URLSearchParams();
  if (params.search) qs.set("search", params.search);
  if (params.source) qs.set("source", params.source);
  if (params.offset != null) qs.set("offset", String(params.offset));
  if (params.limit != null) qs.set("limit", String(params.limit));
  const q = qs.toString();
  return request(`/api/catalog/stars${q ? `?${q}` : ""}`, options);
}

export function deleteStar(starName) {
  return request(`/api/catalog/stars/${encodeURIComponent(starName)}`, {
    method: "DELETE",
  });
}

// ── LLM plugin / account administration ─────────────────────────

export function listLlmProfiles() {
  return request("/api/plugins/llm/profiles");
}

export function createLlmProfile(payload) {
  return request("/api/plugins/llm/profiles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateLlmProfile(profileId, payload) {
  return request(`/api/plugins/llm/profiles/${encodeURIComponent(profileId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteLlmProfile(profileId) {
  return request(`/api/plugins/llm/profiles/${encodeURIComponent(profileId)}`, {
    method: "DELETE",
  });
}

export function testLlmProfile(profileId) {
  return request(`/api/plugins/llm/profiles/${encodeURIComponent(profileId)}/test`, {
    method: "POST",
  });
}

export function listLlmRuns(params = {}) {
  const query = new URLSearchParams();
  if (params.target) query.set("target", params.target);
  if (params.task_type) query.set("task_type", params.task_type);
  if (params.limit) query.set("limit", String(params.limit));
  return request(`/api/plugins/llm/runs${query.size ? `?${query}` : ""}`);
}

export function getLlmRun(runId) {
  return request(`/api/plugins/llm/runs/${encodeURIComponent(runId)}`);
}

export function listUsers() {
  return request("/api/admin/users");
}

export function createUser(payload) {
  return request("/api/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateUser(userId, payload) {
  return request(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function listMigrations() {
  return request("/api/admin/migrations");
}
