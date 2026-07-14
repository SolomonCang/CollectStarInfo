const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function request(path, options) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.json();
}

export function queryTarget(payload) {
  return request("/api/targets/query", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function researchLiterature(payload) {
  return request("/api/literature/research", {
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

export function listLightCurveDatasets(target) {
  const params = target ? `?target=${encodeURIComponent(target)}` : "";
  return request(`/api/lightcurves/datasets${params}`);
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

export function getCatalogStats() {
  return request("/api/catalog/stats");
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

export function listStars(params = {}) {
  const qs = new URLSearchParams();
  if (params.search) qs.set("search", params.search);
  if (params.source) qs.set("source", params.source);
  if (params.offset != null) qs.set("offset", String(params.offset));
  if (params.limit != null) qs.set("limit", String(params.limit));
  const q = qs.toString();
  return request(`/api/catalog/stars${q ? `?${q}` : ""}`);
}

export function deleteStar(starName) {
  return request(`/api/catalog/stars/${encodeURIComponent(starName)}`, {
    method: "DELETE",
  });
}
