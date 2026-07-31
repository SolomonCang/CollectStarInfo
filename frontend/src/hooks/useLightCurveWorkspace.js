import { useCallback, useEffect, useRef } from "react";
import {
  cleanupLightCurveCache,
  deleteLightCurveDataset,
  downloadLightCurves,
  getLightCurveCacheStats,
  listLightCurveDatasets,
  queryTarget,
  searchLightCurves,
  verifyLightCurveCache,
} from "../api";
import { useLightCurveState } from "./useLightCurveState";

function resolvedTargetName(result, fallback) {
  const target = result?.target;
  return target?.resolved_target || target?.query_target || fallback;
}

export function useLightCurveWorkspace({ active = false } = {}) {
  const state = useLightCurveState();
  const queryControllerRef = useRef(null);
  const {
    dispatch,
    forceDownload,
    forceSearchRefresh,
    handleAnalyzeDownloadedDataset,
    selectedProducts,
    targetDisplayName,
    targetName,
    targetResult,
  } = state;

  const refreshCacheStats = useCallback(async () => {
    try {
      const stats = await getLightCurveCacheStats();
      dispatch({ type: "SET_CACHE_RESULT", payload: { stats } });
    } catch (caught) {
      dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [dispatch]);

  useEffect(() => {
    if (active) refreshCacheStats();
  }, [active, refreshCacheStats]);

  useEffect(() => () => queryControllerRef.current?.abort(), []);

  const handleTargetQuery = useCallback(async (event) => {
    event?.preventDefault();
    queryControllerRef.current?.abort();
    const controller = new AbortController();
    queryControllerRef.current = controller;
    dispatch({ type: "TARGET_QUERY_START" });

    try {
      const result = await queryTarget({
        target: targetName,
        use_llm: false,
        force_refresh: false,
      }, { signal: controller.signal });
      const response = await listLightCurveDatasets(
        resolvedTargetName(result, targetName),
        { signal: controller.signal }
      );
      const datasets = response.datasets ?? [];
      const firstDir = datasets[0]?.download_dir ?? "";

      dispatch({
        type: "TARGET_QUERY_DONE",
        payload: { result, datasets, selectedDir: firstDir },
      });
      if (firstDir) await handleAnalyzeDownloadedDataset(firstDir);
    } catch (caught) {
      if (caught.name !== "AbortError") {
        dispatch({ type: "TARGET_QUERY_ERROR", payload: caught.message });
      }
    } finally {
      if (queryControllerRef.current === controller) {
        queryControllerRef.current = null;
      }
    }
  }, [dispatch, handleAnalyzeDownloadedDataset, targetName]);

  const handleArchiveSearch = useCallback(async () => {
    const target = targetResult?.target;
    const simbad = target?.simbad;
    const payload = {
      target: target?.resolved_target || target?.query_target || targetName,
      ra_deg: simbad?.ra_deg ?? null,
      dec_deg: simbad?.dec_deg ?? null,
      radius_deg: target?.mast?.region_radius_deg ?? 0.02,
      missions: ["TESS", "Kepler", "K2"],
      max_products: 80,
      force_refresh: forceSearchRefresh,
    };

    dispatch({ type: "SET_ARCHIVE_BUSY" });
    try {
      const response = await searchLightCurves(payload);
      const products = response.products ?? [];
      const selectedUris = products
        .slice(0, 5)
        .map((product) => product.product_uri)
        .filter(Boolean);
      dispatch({
        type: "SET_ARCHIVE_PRODUCTS",
        payload: { products, selectedUris },
      });
      dispatch({
        type: "SET_CACHE_RESULT",
        payload: {
          message: response.cache?.hit
            ? "已使用本地 MAST 检索缓存。"
            : "已刷新 MAST 检索缓存。",
        },
      });
    } catch (caught) {
      dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [dispatch, forceSearchRefresh, targetName, targetResult]);

  const handleArchiveDownload = useCallback(async () => {
    const target = targetResult?.target;
    const simbad = target?.simbad;
    const payload = {
      target: target?.resolved_target || target?.query_target || targetName,
      ra_deg: simbad?.ra_deg ?? null,
      dec_deg: simbad?.dec_deg ?? null,
      radius_deg: target?.mast?.region_radius_deg ?? 0.02,
      missions: ["TESS", "Kepler", "K2"],
      max_products: 80,
      product_uris: selectedProducts,
      max_downloads: 5,
      force: forceDownload,
    };

    dispatch({ type: "SET_ARCHIVE_BUSY" });
    try {
      const result = await downloadLightCurves(payload);
      const response = await listLightCurveDatasets(
        resolvedTargetName(targetResult, targetName)
      );
      const datasets = response.datasets ?? [];
      dispatch({
        type: "SET_DOWNLOAD_RESULT",
        payload: {
          result,
          datasets,
          selectedDir: result.download_dir,
        },
      });
      await handleAnalyzeDownloadedDataset(result.download_dir);
      await refreshCacheStats();
    } catch (caught) {
      dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [
    dispatch,
    forceDownload,
    handleAnalyzeDownloadedDataset,
    refreshCacheStats,
    selectedProducts,
    targetName,
    targetResult,
  ]);

  const handleCacheVerify = useCallback(async () => {
    dispatch({ type: "SET_CACHE_BUSY" });
    try {
      const result = await verifyLightCurveCache({ deep: false, repair: false });
      const stats = await getLightCurveCacheStats();
      dispatch({
        type: "SET_CACHE_RESULT",
        payload: {
          stats,
          message: `已检查 ${result.checked} 个数据集：${result.valid} 个正常，${result.invalid} 个异常。`,
        },
      });
    } catch (caught) {
      dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [dispatch]);

  const handleCacheCleanup = useCallback(async (dryRun = true) => {
    if (!dryRun && !window.confirm("确认执行缓存清理？未引用的产品和过期临时文件将被删除。")) {
      return;
    }
    dispatch({ type: "SET_CACHE_BUSY" });
    try {
      const result = await cleanupLightCurveCache({
        max_age_days: null,
        max_size_mb: null,
        dry_run: dryRun,
        remove_unreferenced_products: true,
      });
      const stats = await getLightCurveCacheStats();
      dispatch({
        type: "SET_CACHE_RESULT",
        payload: {
          stats,
          message: dryRun
            ? `清理预览：${result.unreferenced_products} 个未引用产品、${result.stale_partial_directories} 个过期临时目录。`
            : `清理完成：释放 ${(result.removed_bytes / 1024 / 1024).toFixed(2)} MB。`,
        },
      });
      if (!dryRun && targetResult) {
        const response = await listLightCurveDatasets(targetDisplayName);
        const datasets = response.datasets ?? [];
        const selectedDir = datasets[0]?.download_dir ?? "";
        dispatch({
          type: "SET_DATASETS",
          payload: { datasets, selectedDir },
        });
        if (selectedDir) await handleAnalyzeDownloadedDataset(selectedDir);
      }
    } catch (caught) {
      dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [
    dispatch,
    handleAnalyzeDownloadedDataset,
    targetDisplayName,
    targetResult,
  ]);

  const handleDeleteDataset = useCallback(async (downloadDir) => {
    if (!downloadDir || !window.confirm(`确认删除数据集 ${downloadDir}？`)) return;
    dispatch({ type: "SET_CACHE_BUSY" });
    try {
      await deleteLightCurveDataset(downloadDir);
      const response = await listLightCurveDatasets(targetDisplayName);
      const datasets = response.datasets ?? [];
      const selectedDir = datasets[0]?.download_dir ?? "";
      const stats = await getLightCurveCacheStats();
      dispatch({ type: "SET_DATASETS", payload: { datasets, selectedDir } });
      dispatch({
        type: "SET_CACHE_RESULT",
        payload: {
          stats,
          message: "数据集已删除；共享产品将在无引用时由缓存清理回收。",
        },
      });
      if (selectedDir) await handleAnalyzeDownloadedDataset(selectedDir);
    } catch (caught) {
      dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [
    dispatch,
    handleAnalyzeDownloadedDataset,
    targetDisplayName,
  ]);

  return {
    ...state,
    handleArchiveDownload,
    handleArchiveSearch,
    handleCacheCleanup,
    handleCacheVerify,
    handleDeleteDataset,
    handleTargetQuery,
  };
}
