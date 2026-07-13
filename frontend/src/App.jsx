import { useState, useCallback } from "react";
import { useLightCurveState } from "./hooks/useLightCurveState";
import {
  queryTarget,
  researchLiterature,
  searchLightCurves,
  downloadLightCurves,
  listLightCurveDatasets,
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
    } catch (caught) {
      lc.dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [lc.targetResult, targetResult, lc.targetName, lc.dispatch]);

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
      // Auto-analyze if not deduplicated
      if (!result.deduplicated) {
        lc.handleAnalyzeDownloadedDataset(result.download_dir);
      }
    } catch (caught) {
      lc.dispatch({ type: "SET_ARCHIVE_ERROR", payload: caught.message });
    }
  }, [lc.targetResult, targetResult, lc.targetName, lc.selectedProducts, lc.forceDownload, lc.dispatch, lc.handleAnalyzeDownloadedDataset]);

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
          toggleProduct={lc.toggleProduct}
          handleSpectrumClick={lc.handleSpectrumClick}
          handleAnalyze={lc.handleAnalyze}
          handleAnalyzeDownloadedDataset={lc.handleAnalyzeDownloadedDataset}
          handleRunPeriodSearch={lc.handleRunPeriodSearch}
          handleFile={lc.handleFile}
          handleTargetQuery={handleTargetQuery}
          handleArchiveSearch={handleArchiveSearch}
          handleArchiveDownload={handleArchiveDownload}
        />
      )}
    </main>
  );
}
