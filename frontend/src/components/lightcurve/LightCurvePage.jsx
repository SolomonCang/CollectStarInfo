import { Database } from "lucide-react";
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

export default function LightCurvePage({
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
  cleanupAgeDays,
  cleanupMaxSizeMb,
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
  setCleanupAgeDays,
  setCleanupMaxSizeMb,
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
}) {
  const searchDisabled = datasetBusy || (!selectedDatasetDir && points.length < 3);

  return (
    <section className="lc-workspace">
      <ErrorBanner message={error} />

      <aside className="control-panel lc-controls">
        <TargetLoader
          targetName={targetName}
          targetBusy={targetBusy}
          onNameChange={setTargetName}
          onSubmit={handleTargetQuery}
        />

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
          cleanupAgeDays={cleanupAgeDays}
          cleanupMaxSizeMb={cleanupMaxSizeMb}
          selectedDataset={selectedDataset}
          hasTarget={!!targetResult && hasTargetCoordinates}
          onSearch={handleArchiveSearch}
          onDownload={handleArchiveDownload}
          onToggleProduct={toggleProduct}
          onForceDownloadChange={setForceDownload}
          onForceSearchRefreshChange={setForceSearchRefresh}
          onCleanupAgeChange={setCleanupAgeDays}
          onCleanupSizeChange={setCleanupMaxSizeMb}
          onCacheVerify={handleCacheVerify}
          onCacheCleanup={handleCacheCleanup}
        />

        <DatasetSelector
          datasets={datasets}
          selectedDir={selectedDatasetDir}
          onSelect={setSelectedDatasetDir}
          onAnalyze={handleAnalyzeDownloadedDataset}
          onFile={handleFile}
          datasetBusy={datasetBusy}
          cacheBusy={cacheBusy}
          onDelete={handleDeleteDataset}
        />

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
      </aside>

      <section className="lc-results">
        {progressSteps.length > 0 && <ProgressSteps steps={progressSteps} />}

        <div className="panel-card target-card">
          <div className="section-title"><Database size={18} /> 数据集状态</div>
          <div className="summary-grid compact-summary">
            <Metric label="Target" value={targetDisplayName} />
            <Metric label="Loaded points" value={analysis?.point_count ?? points.length} />
            <Metric label="Time span (d)" value={analysis?.time_span?.toPrecision?.(7)} />
            <Metric label="Best period (d)" value={analysis?.period_search?.best_period?.toPrecision?.(7)} />
            <Metric label="FAP" value={analysis?.period_search?.false_alarm_probability?.toExponential?.(2)} />
            <Metric
              label="Cache"
              value={analysis?.cache?.analysis_hit ? "analysis hit" : analysis?.cache?.derived_hit ? "curve hit" : "computed"}
            />
          </div>
        </div>

        <div className="analysis-grid">
          <DetrendChart curve={curve} loading={datasetBusy} />
          <PeriodogramChart
            analysis={analysis}
            periodogram={analysis?.period_search?.periodogram ?? []}
            datasetBusy={datasetBusy}
            onClick={handleSpectrumClick}
          />
        </div>

        <div className="analysis-row">
          <PeriodMetrics
            analysis={analysis}
            selectedPhasePeriod={selectedPhasePeriod}
            phasePeriodMode={phasePeriodMode}
            phasePeriod={phasePeriod}
          />
          <PhaseFoldedChart
            phaseCurve={phaseCurve}
            phaseBinned={phaseBinned}
            period={selectedPhasePeriod}
            loading={datasetBusy}
          />
        </div>
      </section>
    </section>
  );
}
