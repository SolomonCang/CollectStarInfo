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
