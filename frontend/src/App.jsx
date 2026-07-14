import { useState, useCallback, useEffect } from "react";
import { useLightCurveState } from "./hooks/useLightCurveState";
import {
  queryTarget,
  researchLiterature,
  searchLightCurves,
  downloadLightCurves,
  listLightCurveDatasets,
  deleteLightCurveDataset,
  getLightCurveCacheStats,
  verifyLightCurveCache,
  cleanupLightCurveCache,
} from "./api";
import TargetPage from "./components/target/TargetPage";
import LightCurvePage from "./components/lightcurve/LightCurvePage";
import "./styles.css";

function targetDisplayName(result, fallback) {
  const t = result?.target;
  return t?.resolved_target || t?.query_target || fallback;
}

export default function App() {
  const [page, setPage] = useState("target");

  // ── Target page state ──
  const [targetName, setTargetName] = useState("AD Leo");
  const [useLlm, setUseLlm] = useState(false);
  const [forceRefresh, setForceRefresh] = useState(false);
  const [targetResult, setTargetResult] = useState(null);
  const [targetBusy, setTargetBusy] = useState(false);
  const [literatureQuestion, setLiteratureQuestion] = useState(
    "重点关注光变曲线、周期、恒星活动和磁场相关研究。"
  );
  const [literatureReport, setLiteratureReport] = useState(null);
  const [literatureBusy, setLiteratureBusy] = useState(false);
  const [prescreenKeywords, setPrescreenKeywords] = useState(true);
  const [targetError, setTargetError] = useState("");

  // ── Light curve state (useReducer) ──
  const lc = useLightCurveState();

  const refreshCacheStats = useCallback(async () => {
    try {
      const stats = await getLightCurveCacheStats();
      lc.dispatch({ type: "SET_CACHE_RESULT", payload: { stats } });
    } catch (caught) {
      lc.dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [lc.dispatch]);

  useEffect(() => {
    refreshCacheStats();
  }, [refreshCacheStats]);

  // ── Shared error ──
  const error = page === "target" ? targetError : lc.error;

  // ── Target query (used by both pages) ──
  const handleTargetQuery = useCallback(async (event) => {
    event?.preventDefault();
    const name = page === "target" ? targetName : lc.targetName;

    if (page === "target") {
      setTargetError("");
      setTargetBusy(true);
    }

    try {
      const result = await queryTarget({
        target: name,
        use_llm: page === "target" ? useLlm : false,
        force_refresh: page === "target" ? forceRefresh : false,
      });

      if (page === "target") {
        setTargetResult(result);
        setLiteratureReport(null);
        setTargetBusy(false);
      } else {
        // Update LC state
        const response = await listLightCurveDatasets(
          targetDisplayName(result, name)
        );
        const datasets = response.datasets ?? [];
        const firstDir = datasets[0]?.download_dir ?? "";

        lc.dispatch({
          type: "TARGET_QUERY_DONE",
          payload: {
            result,
            datasets,
            selectedDir: firstDir,
          },
        });

        // Auto-analyze first dataset
        if (firstDir) {
          lc.handleAnalyzeDownloadedDataset(firstDir);
        }
      }
    } catch (caught) {
      if (page === "target") {
        setTargetError(caught.message);
        setTargetBusy(false);
      } else {
        lc.dispatch({ type: "TARGET_QUERY_ERROR", payload: caught.message });
      }
    }
  }, [page, targetName, lc.targetName, useLlm, forceRefresh, lc]);

  // ── Literature ──
  const handleLiteratureResearch = useCallback(async () => {
    const target = targetResult?.target;
    if (!target) return;
    setTargetError("");
    setLiteratureBusy(true);
    try {
      const response = await researchLiterature({
        target: target.resolved_target || target.query_target || targetName,
        target_type: target.target_type || "unknown",
        references: target.literature_references?.length
          ? target.literature_references
          : target.simbad?.references ?? [],
        literature_workflow: target.literature_workflow ?? null,
        focus_question: literatureQuestion,
        prescreen_keywords: prescreenKeywords,
      });
      setLiteratureReport(response);
    } catch (caught) {
      setTargetError(caught.message);
    } finally {
      setLiteratureBusy(false);
    }
  }, [targetResult, targetName, literatureQuestion, prescreenKeywords]);

  // ── Archive search ──
  const handleArchiveSearch = useCallback(async () => {
    const target = lc.targetResult?.target || targetResult?.target;
    const simbad = target?.simbad;
    const payload = {
      target: target?.resolved_target || target?.query_target || lc.targetName,
      ra_deg: simbad?.ra_deg ?? null,
      dec_deg: simbad?.dec_deg ?? null,
      radius_deg: target?.mast?.region_radius_deg ?? 0.02,
      missions: ["TESS", "Kepler", "K2"],
      max_products: 80,
      force_refresh: lc.forceSearchRefresh,
    };

    lc.dispatch({ type: "SET_ARCHIVE_BUSY" });
    try {
      const response = await searchLightCurves(payload);
      const products = response.products ?? [];
      const selectedUris = products.slice(0, 5).map((p) => p.product_uri).filter(Boolean);
      lc.dispatch({
        type: "SET_ARCHIVE_PRODUCTS",
        payload: { products, selectedUris },
      });
      lc.dispatch({
        type: "SET_CACHE_RESULT",
        payload: {
          message: response.cache?.hit
            ? "已使用本地 MAST 检索缓存。"
            : "已刷新 MAST 检索缓存。",
        },
      });
    } catch (caught) {
      lc.dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [lc.targetResult, targetResult, lc.targetName, lc.forceSearchRefresh, lc.dispatch]);

  // ── Archive download ──
  const handleArchiveDownload = useCallback(async () => {
    const target = lc.targetResult?.target || targetResult?.target;
    const simbad = target?.simbad;
    const payload = {
      target: target?.resolved_target || target?.query_target || lc.targetName,
      ra_deg: simbad?.ra_deg ?? null,
      dec_deg: simbad?.dec_deg ?? null,
      radius_deg: target?.mast?.region_radius_deg ?? 0.02,
      missions: ["TESS", "Kepler", "K2"],
      max_products: 80,
      product_uris: lc.selectedProducts,
      max_downloads: 5,
      force: lc.forceDownload,
    };

    lc.dispatch({ type: "SET_ARCHIVE_BUSY" });
    try {
      const result = await downloadLightCurves(payload);
      const response = await listLightCurveDatasets(
        targetDisplayName(lc.targetResult, lc.targetName)
      );
      const datasets = response.datasets ?? [];
      lc.dispatch({
        type: "SET_DOWNLOAD_RESULT",
        payload: {
          result,
          datasets,
          selectedDir: result.download_dir,
        },
      });
      // Always analyze the selected dataset. A cache hit may point to a
      // different historical dataset than the one currently shown.
      await lc.handleAnalyzeDownloadedDataset(result.download_dir);
      await refreshCacheStats();
    } catch (caught) {
      lc.dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [lc.targetResult, targetResult, lc.targetName, lc.selectedProducts, lc.forceDownload, lc.dispatch, lc.handleAnalyzeDownloadedDataset, refreshCacheStats]);

  const handleCacheVerify = useCallback(async () => {
    lc.dispatch({ type: "SET_CACHE_BUSY" });
    try {
      const result = await verifyLightCurveCache({ deep: false, repair: false });
      const stats = await getLightCurveCacheStats();
      lc.dispatch({
        type: "SET_CACHE_RESULT",
        payload: {
          stats,
          message: `已检查 ${result.checked} 个数据集：${result.valid} 个正常，${result.invalid} 个异常。`,
        },
      });
    } catch (caught) {
      lc.dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [lc.dispatch]);

  const handleCacheCleanup = useCallback(async (dryRun = true) => {
    if (!dryRun && !window.confirm("确认执行缓存清理？命中的历史数据集将被删除。")) return;
    const age = Number(lc.cleanupAgeDays);
    const size = Number(lc.cleanupMaxSizeMb);
    lc.dispatch({ type: "SET_CACHE_BUSY" });
    try {
      const result = await cleanupLightCurveCache({
        max_age_days: Number.isFinite(age) && age > 0 ? age : null,
        max_size_mb: Number.isFinite(size) && size > 0 ? size : null,
        dry_run: dryRun,
        remove_unreferenced_products: true,
      });
      const stats = await getLightCurveCacheStats();
      lc.dispatch({
        type: "SET_CACHE_RESULT",
        payload: {
          stats,
          message: dryRun
            ? `清理预览：${result.datasets.length} 个数据集、${result.unreferenced_products} 个未引用产品。`
            : `清理完成：删除 ${result.datasets.length} 个数据集，释放 ${(result.removed_bytes / 1024 / 1024).toFixed(2)} MB。`,
        },
      });
      if (!dryRun && lc.targetResult) {
        const response = await listLightCurveDatasets(lc.targetDisplayName);
        const datasets = response.datasets ?? [];
        const selectedDir = datasets[0]?.download_dir ?? "";
        lc.dispatch({
          type: "SET_DATASETS",
          payload: { datasets, selectedDir },
        });
        if (selectedDir) await lc.handleAnalyzeDownloadedDataset(selectedDir);
      }
    } catch (caught) {
      lc.dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [lc.cleanupAgeDays, lc.cleanupMaxSizeMb, lc.targetResult, lc.targetDisplayName, lc.dispatch, lc.handleAnalyzeDownloadedDataset]);

  const handleDeleteDataset = useCallback(async (downloadDir) => {
    if (!downloadDir || !window.confirm(`确认删除数据集 ${downloadDir}？`)) return;
    lc.dispatch({ type: "SET_CACHE_BUSY" });
    try {
      await deleteLightCurveDataset(downloadDir);
      const response = await listLightCurveDatasets(lc.targetDisplayName);
      const datasets = response.datasets ?? [];
      const selectedDir = datasets[0]?.download_dir ?? "";
      const stats = await getLightCurveCacheStats();
      lc.dispatch({ type: "SET_DATASETS", payload: { datasets, selectedDir } });
      lc.dispatch({
        type: "SET_CACHE_RESULT",
        payload: { stats, message: "数据集已删除；共享产品将在无引用时由缓存清理回收。" },
      });
      if (selectedDir) await lc.handleAnalyzeDownloadedDataset(selectedDir);
    } catch (caught) {
      lc.dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [lc.targetDisplayName, lc.dispatch, lc.handleAnalyzeDownloadedDataset]);

  // ── References for literature ──
  const targetReferences = targetResult?.target?.literature_references;
  const references = targetReferences?.length
    ? targetReferences
    : (targetResult?.target?.simbad?.references ?? []);

  return (
    <main className="app-shell">
      <section className="workspace-header">
        <div>
          <p className="eyebrow">Interactive astronomy workspace</p>
          <h1>{page === "lightcurves" ? "Light Curve Lab" : "Target Info Search"}</h1>
        </div>
        <div className="page-switcher">
          <button
            type="button"
            className={page === "target" ? "nav-button active" : "nav-button"}
            onClick={() => setPage("target")}
          >
            目标信息
          </button>
          <button
            type="button"
            className={page === "lightcurves" ? "nav-button active" : "nav-button"}
            onClick={() => setPage("lightcurves")}
          >
            光变曲线
          </button>
        </div>
      </section>

      {page === "target" ? (
        <TargetPage
          error={targetError}
          forceRefresh={forceRefresh}
          handleLiteratureResearch={handleLiteratureResearch}
          handleTargetQuery={handleTargetQuery}
          literatureBusy={literatureBusy}
          literatureQuestion={literatureQuestion}
          literatureReport={literatureReport}
          prescreenKeywords={prescreenKeywords}
          references={references}
          setForceRefresh={setForceRefresh}
          setLiteratureQuestion={setLiteratureQuestion}
          setPrescreenKeywords={setPrescreenKeywords}
          setTargetName={setTargetName}
          setUseLlm={setUseLlm}
          targetBusy={targetBusy}
          targetName={targetName}
          targetResult={targetResult}
          useLlm={useLlm}
        />
      ) : (
        <LightCurvePage
          // State
          targetName={lc.targetName}
          targetResult={lc.targetResult}
          targetBusy={lc.targetBusy}
          archiveProducts={lc.archiveProducts}
          selectedProducts={lc.selectedProducts}
          archiveBusy={lc.archiveBusy}
          downloadResult={lc.downloadResult}
          forceDownload={lc.forceDownload}
          forceSearchRefresh={lc.forceSearchRefresh}
          cacheStats={lc.cacheStats}
          cacheBusy={lc.cacheBusy}
          cacheMessage={lc.cacheMessage}
          cleanupAgeDays={lc.cleanupAgeDays}
          cleanupMaxSizeMb={lc.cleanupMaxSizeMb}
          datasets={lc.datasets}
          selectedDatasetDir={lc.selectedDatasetDir}
          datasetBusy={lc.datasetBusy}
          minPeriod={lc.minPeriod}
          maxPeriod={lc.maxPeriod}
          samplesPerPeak={lc.samplesPerPeak}
          polynomialOrder={lc.polynomialOrder}
          gapThreshold={lc.gapThreshold}
          phasePeriodMode={lc.phasePeriodMode}
          phasePeriod={lc.phasePeriod}
          analysis={lc.analysis}
          points={lc.points}
          error={lc.error}
          progressSteps={lc.progressSteps}
          // Derived
          curve={lc.curve}
          periodOptions={lc.periodOptions}
          selectedPhasePeriod={lc.selectedPhasePeriod}
          phaseCurve={lc.phaseCurve}
          phaseBinned={lc.phaseBinned}
          hasTargetCoordinates={lc.hasTargetCoordinates}
          selectedDataset={lc.selectedDataset}
          targetDisplayName={lc.targetDisplayName}
          // Actions
          setTargetName={lc.setTargetName}
          setMinPeriod={lc.setMinPeriod}
          setMaxPeriod={lc.setMaxPeriod}
          setSamplesPerPeak={lc.setSamplesPerPeak}
          setPolynomialOrder={lc.setPolynomialOrder}
          setGapThreshold={lc.setGapThreshold}
          setPhasePeriodMode={lc.setPhasePeriodMode}
          setPhasePeriod={lc.setPhasePeriod}
          setSelectedDatasetDir={lc.setSelectedDatasetDir}
          setForceDownload={lc.setForceDownload}
          setForceSearchRefresh={lc.setForceSearchRefresh}
          setCleanupAgeDays={lc.setCleanupAgeDays}
          setCleanupMaxSizeMb={lc.setCleanupMaxSizeMb}
          toggleProduct={lc.toggleProduct}
          handleSpectrumClick={lc.handleSpectrumClick}
          handleAnalyze={lc.handleAnalyze}
          handleAnalyzeDownloadedDataset={lc.handleAnalyzeDownloadedDataset}
          handleRunPeriodSearch={lc.handleRunPeriodSearch}
          handleFile={lc.handleFile}
          handleTargetQuery={handleTargetQuery}
          handleArchiveSearch={handleArchiveSearch}
          handleArchiveDownload={handleArchiveDownload}
          handleCacheVerify={handleCacheVerify}
          handleCacheCleanup={handleCacheCleanup}
          handleDeleteDataset={handleDeleteDataset}
        />
      )}
    </main>
  );
}
