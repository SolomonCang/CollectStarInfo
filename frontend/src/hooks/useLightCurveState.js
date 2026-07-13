import { useReducer, useCallback, useMemo } from "react";
import { analyzeDownloadedLightCurve, analyzeLightCurve } from "../api";
import { foldCurve, foldCurveBinned, downsampleCurve } from "../utils/foldCurve";

// ── State ────────────────────────────────────────────────────────
const initialState = {
  // Target
  targetName: "AD Leo",
  targetResult: null,
  targetBusy: false,

  // Uploaded points & analysis
  points: [],
  analysis: null,
  datasetBusy: false,

  // Archive (MAST)
  archiveProducts: [],
  selectedProducts: [],
  archiveBusy: false,
  downloadResult: null,
  forceDownload: false,

  // Datasets
  datasets: [],
  selectedDatasetDir: "",

  // Period search params
  minPeriod: "",
  maxPeriod: "",
  samplesPerPeak: "8",

  // Detrend params
  polynomialOrder: "2",
  gapThreshold: "1.0",

  // Phase folding
  phasePeriodMode: "best",
  phasePeriod: "",

  // UI
  error: "",
  progressSteps: [],

  // Periodogram zoom (brush)
  periodogramDomain: null, // [freqMin, freqMax] or null for auto
};

// ── Reducer ──────────────────────────────────────────────────────
function reducer(state, action) {
  switch (action.type) {
    case "SET_TARGET_NAME":
      return { ...state, targetName: action.payload };

    case "TARGET_QUERY_START":
      return { ...state, targetBusy: true, error: "" };

    case "TARGET_QUERY_DONE":
      return {
        ...state,
        targetBusy: false,
        targetResult: action.payload.result,
        datasets: action.payload.datasets ?? state.datasets,
        selectedDatasetDir: action.payload.selectedDir ?? state.selectedDatasetDir,
        archiveProducts: [],
        selectedProducts: [],
        downloadResult: null,
      };

    case "TARGET_QUERY_ERROR":
      return { ...state, targetBusy: false, error: action.payload };

    case "SET_ANALYSIS":
      return { ...state, analysis: action.payload, datasetBusy: false, error: "" };

    case "SET_DATASET_BUSY":
      return { ...state, datasetBusy: true, error: "" };

    case "SET_DATASET_ERROR":
      return { ...state, datasetBusy: false, error: action.payload };

    case "SET_POINTS":
      return { ...state, points: action.payload, analysis: null, phasePeriod: "" };

    case "SET_ARCHIVE_PRODUCTS":
      return {
        ...state,
        archiveBusy: false,
        archiveProducts: action.payload.products,
        selectedProducts: action.payload.selectedUris ?? [],
        error: "",
      };

    case "SET_ARCHIVE_BUSY":
      return { ...state, archiveBusy: true, downloadResult: null, error: "" };

    case "SET_ARCHIVE_ERROR":
      return { ...state, archiveBusy: false, error: action.payload };

    case "SET_DOWNLOAD_RESULT":
      return {
        ...state,
        archiveBusy: false,
        downloadResult: action.payload.result,
        datasets: action.payload.datasets ?? state.datasets,
        selectedDatasetDir: action.payload.selectedDir ?? state.selectedDatasetDir,
        error: "",
      };

    case "SET_DATASETS":
      return {
        ...state,
        datasets: action.payload.datasets,
        selectedDatasetDir: action.payload.selectedDir ?? state.selectedDatasetDir,
      };

    case "SET_SELECTED_DATASET":
      return { ...state, selectedDatasetDir: action.payload };

    case "SET_SELECTED_PRODUCTS":
      return { ...state, selectedProducts: action.payload };

    case "TOGGLE_PRODUCT": {
      const uri = action.payload;
      const next = state.selectedProducts.includes(uri)
        ? state.selectedProducts.filter((u) => u !== uri)
        : [...state.selectedProducts, uri];
      return { ...state, selectedProducts: next };
    }

    case "SET_FORCE_DOWNLOAD":
      return { ...state, forceDownload: action.payload };

    case "SET_MIN_PERIOD":
      return { ...state, minPeriod: action.payload };
    case "SET_MAX_PERIOD":
      return { ...state, maxPeriod: action.payload };
    case "SET_SAMPLES_PER_PEAK":
      return { ...state, samplesPerPeak: action.payload };
    case "SET_POLYNOMIAL_ORDER":
      return { ...state, polynomialOrder: action.payload };
    case "SET_GAP_THRESHOLD":
      return { ...state, gapThreshold: action.payload };

    case "SET_PHASE_PERIOD_MODE":
      return { ...state, phasePeriodMode: action.payload };
    case "SET_PHASE_PERIOD":
      return { ...state, phasePeriod: action.payload, phasePeriodMode: "manual" };

    case "SET_ERROR":
      return { ...state, error: action.payload };

    case "SET_PROGRESS_STEPS":
      return { ...state, progressSteps: action.payload };

    case "SET_PERIODOGRAM_DOMAIN":
      return { ...state, periodogramDomain: action.payload };

    case "RESET_ZOOM":
      return { ...state, periodogramDomain: null };

    default:
      return state;
  }
}

// ── Hook ─────────────────────────────────────────────────────────
export function useLightCurveState() {
  const [state, dispatch] = useReducer(reducer, initialState);

  // ── Derived data (memoized) ──
  const analysisPayload = useMemo(() => {
    const minValue = Number(state.minPeriod);
    const maxValue = Number(state.maxPeriod);
    const order = Math.min(5, Math.max(0, Number(state.polynomialOrder) || 2));
    const gapValue = Number(state.gapThreshold);
    return {
      detrend: {
        enabled: true,
        method: "polynomial",
        polynomial_order: order,
        gap_threshold: Number.isFinite(gapValue) && gapValue > 0 ? gapValue : null,
      },
      period_search: {
        enabled: true,
        min_period: Number.isFinite(minValue) && minValue > 0 ? minValue : null,
        max_period: Number.isFinite(maxValue) && maxValue > 0 ? maxValue : null,
        samples_per_peak: Math.min(50, Math.max(2, Number(state.samplesPerPeak) || 8)),
      },
    };
  }, [state.minPeriod, state.maxPeriod, state.samplesPerPeak, state.polynomialOrder, state.gapThreshold]);

  const periodOptions = useMemo(() => {
    const periodogram = state.analysis?.period_search?.periodogram ?? [];
    const bestPeriod = state.analysis?.period_search?.best_period;
    const ranked = [...periodogram]
      .sort((left, right) => right.power - left.power)
      .slice(0, 6)
      .map((item) => item.period);
    const periods = [bestPeriod, ...ranked].filter((p) => Number.isFinite(p) && p > 0);
    return [...new Set(periods.map((p) => p.toPrecision(10)))].map(Number);
  }, [state.analysis]);

  const curve = useMemo(() => state.analysis?.detrend?.curve ?? [], [state.analysis]);

  const selectedPhasePeriod = useMemo(() => {
    const manual = Number(state.phasePeriod);
    const best = state.analysis?.period_search?.best_period;
    if (state.phasePeriodMode === "manual" && Number.isFinite(manual) && manual > 0) return manual;
    return best;
  }, [state.phasePeriodMode, state.phasePeriod, state.analysis]);

  const phaseCurve = useMemo(() => {
    if (!Number.isFinite(selectedPhasePeriod) || !curve.length) {
      return state.analysis?.period_search?.phase_curve ?? [];
    }
    const folded = foldCurve(curve, selectedPhasePeriod);
    return downsampleCurve(folded, 6000);
  }, [curve, selectedPhasePeriod, state.analysis]);

  const phaseBinned = useMemo(() => {
    if (!Number.isFinite(selectedPhasePeriod) || !curve.length) return [];
    return foldCurveBinned(curve, selectedPhasePeriod);
  }, [curve, selectedPhasePeriod]);

  const hasTargetCoordinates = useMemo(() => {
    return Number.isFinite(state.targetResult?.target?.simbad?.ra_deg)
      && Number.isFinite(state.targetResult?.target?.simbad?.dec_deg);
  }, [state.targetResult]);

  const selectedDataset = useMemo(() => {
    return state.datasets.find((d) => d.download_dir === state.selectedDatasetDir);
  }, [state.datasets, state.selectedDatasetDir]);

  const targetDisplayName = useMemo(() => {
    const t = state.targetResult?.target;
    return t?.resolved_target || t?.query_target || state.targetName;
  }, [state.targetResult, state.targetName]);

  // ── Filtered periodogram for zoom ──
  const filteredPeriodogram = useMemo(() => {
    const raw = state.analysis?.period_search?.periodogram ?? [];
    if (!state.periodogramDomain || !raw.length) return raw;
    const [fMin, fMax] = state.periodogramDomain;
    return raw.filter((p) => p.frequency >= fMin && p.frequency <= fMax);
  }, [state.analysis, state.periodogramDomain]);

  // ── Actions ──
  const setTargetName = useCallback((val) => dispatch({ type: "SET_TARGET_NAME", payload: val }), []);
  const setMinPeriod = useCallback((val) => dispatch({ type: "SET_MIN_PERIOD", payload: val }), []);
  const setMaxPeriod = useCallback((val) => dispatch({ type: "SET_MAX_PERIOD", payload: val }), []);
  const setSamplesPerPeak = useCallback((val) => dispatch({ type: "SET_SAMPLES_PER_PEAK", payload: val }), []);
  const setPolynomialOrder = useCallback((val) => dispatch({ type: "SET_POLYNOMIAL_ORDER", payload: val }), []);
  const setGapThreshold = useCallback((val) => dispatch({ type: "SET_GAP_THRESHOLD", payload: val }), []);
  const setPhasePeriodMode = useCallback((val) => dispatch({ type: "SET_PHASE_PERIOD_MODE", payload: val }), []);
  const setPhasePeriod = useCallback((val) => dispatch({ type: "SET_PHASE_PERIOD", payload: val }), []);
  const setSelectedDatasetDir = useCallback((val) => dispatch({ type: "SET_SELECTED_DATASET", payload: val }), []);
  const setForceDownload = useCallback((val) => dispatch({ type: "SET_FORCE_DOWNLOAD", payload: val }), []);
  const setError = useCallback((val) => dispatch({ type: "SET_ERROR", payload: val }), []);
  const setPeriodogramDomain = useCallback((val) => dispatch({ type: "SET_PERIODOGRAM_DOMAIN", payload: val }), []);
  const resetZoom = useCallback(() => dispatch({ type: "RESET_ZOOM" }), []);

  const setProgressSteps = useCallback((steps) => {
    dispatch({ type: "SET_PROGRESS_STEPS", payload: steps });
  }, []);

  const setPoints = useCallback((parsed) => {
    dispatch({ type: "SET_POINTS", payload: parsed });
  }, []);

  const toggleProduct = useCallback((uri) => {
    dispatch({ type: "TOGGLE_PRODUCT", payload: uri });
  }, []);

  const handleSpectrumClick = useCallback((event) => {
    const period = event?.activePayload?.[0]?.payload?.period;
    if (!Number.isFinite(period)) return;
    dispatch({ type: "SET_PHASE_PERIOD", payload: period.toPrecision(10) });
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (state.points.length < 3) return;
    dispatch({ type: "SET_DATASET_BUSY" });
    setProgressSteps([
      { label: "去趋势与归一化", status: "active" },
      { label: "Lomb-Scargle 周期搜索", status: "pending" },
    ]);
    try {
      const result = await analyzeLightCurve({ points: state.points, ...analysisPayload });
      dispatch({ type: "SET_ANALYSIS", payload: result });
      dispatch({ type: "SET_PHASE_PERIOD_MODE", payload: "best" });
      dispatch({ type: "SET_PHASE_PERIOD", payload: "" });
      setProgressSteps([]);
    } catch (caught) {
      dispatch({ type: "SET_DATASET_ERROR", payload: caught.message });
      setProgressSteps([]);
    }
  }, [state.points, analysisPayload, setProgressSteps]);

  const handleAnalyzeDownloadedDataset = useCallback(async (downloadDir) => {
    const dir = downloadDir || state.selectedDatasetDir || state.downloadResult?.download_dir;
    if (!dir) return;
    dispatch({ type: "SET_DATASET_BUSY" });
    setProgressSteps([
      { label: "读取 FITS / CSV 数据", status: "active" },
      { label: "去趋势与归一化", status: "pending" },
      { label: "Lomb-Scargle 周期搜索", status: "pending" },
    ]);
    try {
      const result = await analyzeDownloadedLightCurve({
        download_dir: dir,
        quality_filter: true,
        max_points: 5000,
        ...analysisPayload,
      });
      dispatch({ type: "SET_ANALYSIS", payload: result });
      dispatch({ type: "SET_PHASE_PERIOD_MODE", payload: "best" });
      dispatch({ type: "SET_PHASE_PERIOD", payload: "" });
      setProgressSteps([]);
    } catch (caught) {
      dispatch({ type: "SET_DATASET_ERROR", payload: caught.message });
      setProgressSteps([]);
    }
  }, [state.selectedDatasetDir, state.downloadResult, analysisPayload, setProgressSteps]);

  const handleRunPeriodSearch = useCallback(async () => {
    if (state.selectedDatasetDir) {
      await handleAnalyzeDownloadedDataset(state.selectedDatasetDir);
      return;
    }
    if (state.points.length >= 3) {
      await handleAnalyze();
      return;
    }
    dispatch({ type: "SET_ERROR", payload: "请先选择已下载数据集，或上传至少三行 time/flux 数据。" });
  }, [state.selectedDatasetDir, state.points.length, handleAnalyzeDownloadedDataset, handleAnalyze]);

  const handleFile = useCallback(async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const { parseCsv } = await import("../utils/parseCsv");
    const text = await file.text();
    const parsed = parseCsv(text);
    dispatch({ type: "SET_POINTS", payload: parsed });
  }, []);

  return {
    // State
    ...state,
    // Derived (memoized)
    analysisPayload,
    periodOptions,
    curve,
    selectedPhasePeriod,
    phaseCurve,
    phaseBinned,
    hasTargetCoordinates,
    selectedDataset,
    targetDisplayName,
    filteredPeriodogram,
    // Actions
    setTargetName,
    setMinPeriod,
    setMaxPeriod,
    setSamplesPerPeak,
    setPolynomialOrder,
    setGapThreshold,
    setPhasePeriodMode,
    setPhasePeriod,
    setSelectedDatasetDir,
    setForceDownload,
    setError,
    setPoints,
    setProgressSteps,
    setPeriodogramDomain,
    resetZoom,
    toggleProduct,
    handleSpectrumClick,
    handleAnalyze,
    handleAnalyzeDownloadedDataset,
    handleRunPeriodSearch,
    handleFile,
    // Raw dispatch for archive actions
    dispatch,
  };
}
