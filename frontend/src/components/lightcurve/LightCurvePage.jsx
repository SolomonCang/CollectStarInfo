import { useState } from "react";
import {
  ChevronDown,
  Database,
  FolderOpen,
  Play,
  SlidersHorizontal,
  X,
} from "lucide-react";
import Metric from "../shared/Metric";
import ErrorBanner from "../shared/ErrorBanner";
import ProgressSteps from "../shared/ProgressSteps";
import TargetLoader from "./TargetLoader";
import ArchivePanel from "./ArchivePanel";
import DatasetSelector from "./DatasetSelector";
import AnalysisSettings from "./AnalysisSettings";
import PhaseControls from "./PhaseControls";
import DetrendChart from "./DetrendChart";
import PeriodogramChart from "./PeriodogramChart";
import PhaseFoldedChart from "./PhaseFoldedChart";
import PeriodMetrics from "./PeriodMetrics";

export default function LightCurvePage({ workspace, canManage = false }) {
  const [dataPanelOpen, setDataPanelOpen] = useState(false);
  const {
    // State
    targetName,
    targetResult,
    targetBusy,
    archiveProducts,
    selectedProducts,
    archiveBusy,
    downloadResult,
    forceDownload,
    forceSearchRefresh,
    cacheStats,
    cacheBusy,
    cacheMessage,
    datasets,
    selectedDatasetDir,
    datasetBusy,
    minPeriod,
    maxPeriod,
    samplesPerPeak,
    polynomialOrder,
    gapThreshold,
    phasePeriodMode,
    phasePeriod,
    analysis,
    points,
    error,
    progressSteps,
    // Derived
    curve,
    periodOptions,
    selectedPhasePeriod,
    phaseCurve,
    phaseBinned,
    hasTargetCoordinates,
    selectedDataset,
    targetDisplayName,
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
    setForceSearchRefresh,
    toggleProduct,
    handleSpectrumClick,
    handleAnalyze,
    handleAnalyzeDownloadedDataset,
    handleRunPeriodSearch,
    handleFile,
    handleTargetQuery,
    handleArchiveSearch,
    handleArchiveDownload,
    handleCacheVerify,
    handleCacheCleanup,
    handleDeleteDataset,
  } = workspace;
  const searchDisabled = datasetBusy || (!selectedDatasetDir && points.length < 3);
  const loadedPointCount = analysis?.point_count ?? points.length;
  const selectedMission = selectedDataset?.missions?.join(" · ") || "本地 / 自定义";
  const selectedDatasetLabel = selectedDataset
    ? `${selectedMission} · ${selectedDataset.csv_point_count ?? selectedDataset.manifest_entries ?? 0} points`
    : points.length
      ? `已上传文件 · ${points.length} points`
      : "尚未选择数据集";

  return (
    <section className="lc-page">
      <ErrorBanner message={error} />

      <section className="lc-context-bar" aria-label="当前分析上下文">
        <TargetLoader
          targetName={targetName}
          targetBusy={targetBusy}
          onNameChange={setTargetName}
          onSubmit={handleTargetQuery}
          compact
        />

        <div className="lc-context-dataset">
          <span className="lc-context-label">当前数据</span>
          <strong>{selectedDatasetLabel}</strong>
          <span className="lc-context-meta">
            {analysis?.time_span != null ? `${analysis.time_span.toPrecision(6)} 天跨度` : "等待分析"}
          </span>
        </div>

        <div className="lc-context-actions">
          <button
            type="button"
            className="ghost-button"
            aria-expanded={dataPanelOpen}
            aria-controls="lightcurve-data-panel"
            onClick={() => setDataPanelOpen((open) => !open)}
          >
            <FolderOpen size={16} />
            数据与导入
            <ChevronDown className={dataPanelOpen ? "rotated" : ""} size={15} />
          </button>
          <button
            type="button"
            className="lc-primary-action"
            onClick={handleRunPeriodSearch}
            disabled={searchDisabled}
          >
            <Play size={16} />
            {datasetBusy ? "分析中…" : "运行分析"}
          </button>
        </div>
      </section>

      {dataPanelOpen && (
        <section id="lightcurve-data-panel" className="panel-card lc-data-panel">
          <div className="lc-data-panel-header">
            <div>
              <span className="lc-kicker">Data workspace</span>
              <h2>选择、下载或导入数据</h2>
            </div>
            <button
              type="button"
              className="icon-button ghost-button"
              aria-label="关闭数据面板"
              onClick={() => setDataPanelOpen(false)}
            >
              <X size={18} />
            </button>
          </div>
          <div className="lc-data-panel-grid">
            <ArchivePanel
              archiveProducts={archiveProducts}
              selectedProducts={selectedProducts}
              archiveBusy={archiveBusy}
              downloadResult={downloadResult}
              forceDownload={forceDownload}
              forceSearchRefresh={forceSearchRefresh}
              cacheStats={cacheStats}
              cacheBusy={cacheBusy}
              cacheMessage={cacheMessage}
              selectedDataset={selectedDataset}
              hasTarget={!!targetResult && hasTargetCoordinates}
              onSearch={handleArchiveSearch}
              onDownload={handleArchiveDownload}
              onToggleProduct={toggleProduct}
              onForceDownloadChange={setForceDownload}
              onForceSearchRefreshChange={setForceSearchRefresh}
              onCacheVerify={handleCacheVerify}
              onCacheCleanup={canManage ? handleCacheCleanup : null}
            />

            <DatasetSelector
              datasets={datasets}
              selectedDir={selectedDatasetDir}
              onSelect={setSelectedDatasetDir}
              onAnalyze={handleAnalyzeDownloadedDataset}
              onFile={handleFile}
              datasetBusy={datasetBusy}
              cacheBusy={cacheBusy}
              onDelete={canManage ? handleDeleteDataset : null}
            />
          </div>
        </section>
      )}

      {progressSteps.length > 0 && <ProgressSteps steps={progressSteps} />}

      <section className="lc-workspace">
        <aside className="control-panel lc-controls">
          <div className="lc-control-heading">
            <span className="lc-kicker">Analysis controls</span>
            <div className="section-title"><SlidersHorizontal size={18} /> 分析参数</div>
            <p>调整参数后重新运行，图表与周期结果会一起更新。</p>
          </div>

          <AnalysisSettings
            polynomialOrder={polynomialOrder}
            gapThreshold={gapThreshold}
            segmentCount={analysis?.detrend?.segment_count ?? 0}
            onOrderChange={setPolynomialOrder}
            onGapChange={setGapThreshold}
            minPeriod={minPeriod}
            maxPeriod={maxPeriod}
            samplesPerPeak={samplesPerPeak}
            searchDisabled={searchDisabled}
            onMinPeriodChange={setMinPeriod}
            onMaxPeriodChange={setMaxPeriod}
            onSamplesPerPeakChange={setSamplesPerPeak}
            onRunSearch={handleRunPeriodSearch}
          />

          <PhaseControls
            phasePeriodMode={phasePeriodMode}
            phasePeriod={phasePeriod}
            bestPeriod={analysis?.period_search?.best_period}
            periodOptions={periodOptions}
            onModeChange={setPhasePeriodMode}
            onPeriodChange={setPhasePeriod}
            onPeriodSelect={(period) => {
              setPhasePeriod(period.toPrecision(10));
            }}
          />

          <button
            type="button"
            className="lc-sidebar-run"
            onClick={handleRunPeriodSearch}
            disabled={searchDisabled}
          >
            <Play size={16} />
            {datasetBusy ? "正在运行分析…" : "应用参数并运行"}
          </button>
        </aside>

        <section className="lc-results">
          <div className="panel-card lc-result-strip">
            <div className="lc-result-identity">
              <Database size={18} />
              <div>
                <span>当前目标</span>
                <strong>{targetDisplayName}</strong>
              </div>
            </div>
            <Metric label="数据点" value={loadedPointCount} />
            <Metric label="时间跨度 (d)" value={analysis?.time_span?.toPrecision?.(7)} />
            <Metric
              label="计算状态"
              value={analysis?.cache?.analysis_hit ? "分析缓存" : analysis?.cache?.derived_hit ? "曲线缓存" : "实时计算"}
            />
          </div>

          <DetrendChart curve={curve} loading={datasetBusy} />

          <div className="lc-chart-pair">
            <PeriodogramChart
              analysis={analysis}
              periodogram={analysis?.period_search?.periodogram ?? []}
              datasetBusy={datasetBusy}
              onClick={handleSpectrumClick}
            />
            <PhaseFoldedChart
              phaseCurve={phaseCurve}
              phaseBinned={phaseBinned}
              period={selectedPhasePeriod}
              loading={datasetBusy}
            />
          </div>

          <PeriodMetrics
            analysis={analysis}
            selectedPhasePeriod={selectedPhasePeriod}
            phasePeriodMode={phasePeriodMode}
            phasePeriod={phasePeriod}
          />
        </section>
      </section>
    </section>
  );
}
