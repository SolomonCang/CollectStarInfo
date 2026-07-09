import React from "react";
import { createRoot } from "react-dom/client";
import { Activity, BarChart3, BookOpenText, Database, Download, ExternalLink, Orbit, Search } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { analyzeDownloadedLightCurve, analyzeLightCurve, downloadLightCurves, listLightCurveDatasets, queryTarget, researchLiterature, searchLightCurves } from "./api";
import "./styles.css";

function parseCsv(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.split(/,|\s+/).map(Number))
    .filter((columns) => Number.isFinite(columns[0]) && Number.isFinite(columns[1]))
    .map(([time, flux, flux_error]) => ({
      time,
      flux,
      flux_error: Number.isFinite(flux_error) ? flux_error : null,
    }));
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value ?? "-"}</strong>
    </div>
  );
}

function ExternalTextLink({ href, children }) {
  if (!href) {
    return <span>{children}</span>;
  }

  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-link">
      {children}
      <ExternalLink size={13} />
    </a>
  );
}

function mastIdentifierUrl(kind, identifier) {
  if (!identifier) {
    return "";
  }
  const catalog = kind === "TIC" ? "TIC" : kind;
  return `https://mast.stsci.edu/portal/Mashup/Clients/Mast/Portal.html?searchQuery=${encodeURIComponent(`${catalog} ${identifier}`)}`;
}

function adsUrl(bibcode) {
  return bibcode ? `https://ui.adsabs.harvard.edu/abs/${encodeURIComponent(bibcode)}/abstract` : "";
}

function parseSampleReference(reference) {
  const text = String(reference ?? "");
  const match = text.match(/^([^:\s]+):\s*(.*)$/);
  if (!match) {
    return { bibcode: "", title: text };
  }
  return { bibcode: match[1], title: match[2] || text };
}

function DetailList({ title, count, children }) {
  return (
    <details className="detail-group">
      <summary>
        <span>{title}</span>
        <strong>{count ?? "-"}</strong>
      </summary>
      <div className="detail-body">{children}</div>
    </details>
  );
}

function SampleReferenceList({ references }) {
  if (!references?.length) {
    return <div className="muted-text">No sample references available.</div>;
  }

  return (
    <ul className="sample-list">
      {references.map((reference) => {
        const parsed = parseSampleReference(reference);
        return (
          <li key={reference}>
            <ExternalTextLink href={adsUrl(parsed.bibcode)}>{parsed.bibcode || "ADS"}</ExternalTextLink>
            <span>{parsed.title}</span>
          </li>
        );
      })}
    </ul>
  );
}

function ReferenceBrowser({ references }) {
  const pageSize = 20;
  const [startIndex, setStartIndex] = React.useState(0);
  const maxStart = Math.max(0, references.length - pageSize);
  const normalizedStart = Math.min(startIndex, maxStart);
  const visibleReferences = references.slice(normalizedStart, normalizedStart + pageSize);

  React.useEffect(() => {
    setStartIndex(0);
  }, [references]);

  if (!references.length) {
    return <div className="muted-text">No SIMBAD references returned.</div>;
  }

  return (
    <div className="reference-browser">
      <div className="reference-slider-row">
        <span>
          Showing {normalizedStart + 1}-{Math.min(normalizedStart + pageSize, references.length)} of {references.length}
        </span>
        <input
          type="range"
          min="0"
          max={maxStart}
          step={pageSize}
          value={normalizedStart}
          onChange={(event) => setStartIndex(Number(event.target.value))}
          aria-label="Browse SIMBAD references"
        />
      </div>
      <div className="reference-pager">
        <button
          type="button"
          className="ghost-button"
          disabled={normalizedStart === 0}
          onClick={() => setStartIndex(Math.max(0, normalizedStart - pageSize))}
        >
          Previous
        </button>
        <button
          type="button"
          className="ghost-button"
          disabled={normalizedStart >= maxStart}
          onClick={() => setStartIndex(Math.min(maxStart, normalizedStart + pageSize))}
        >
          Next
        </button>
      </div>
      <ul className="reference-list">
        {visibleReferences.map((reference) => (
          <li key={reference.bibcode || reference.title}>
            <ExternalTextLink href={adsUrl(reference.bibcode)}>{reference.bibcode || "ADS"}</ExternalTextLink>
            <span>{reference.year || "-"}</span>
            <strong>{reference.title || "Untitled reference"}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

function LiteratureReport({ report, targetName }) {
  if (!report?.report) {
    return null;
  }
  const references = report.report_references ?? [];
  const keywords = report.focus_keywords ?? [];
  const total = report.reference_count_total ?? report.reference_count;
  const afterPrescreen = report.reference_count_after_prescreen;
  const used = report.reference_count_used;

  function handleExportMarkdown() {
    const refLines = references.map((ref) => {
      const bibcode = ref.bibcode || ref.ref_id || "-";
      const year = ref.year || "-";
      const title = ref.title || "Untitled";
      return `- [${ref.ref_id}] **${bibcode}** (${year}) ${title}`;
    }).join("\n");
    const keywordText = keywords.length ? keywords.join(", ") : "无";
    const safeTarget = (targetName || "文献调研").replace(/[\\/:*?"<>|]/g, "_");
    const md = `# ${safeTarget} 文献调研报告

> 生成时间: ${new Date().toLocaleString()}

## 统计

- 总文献数: ${total ?? "-"}
- 预筛选后: ${afterPrescreen ?? "-"}
- 送入 DeepSeek: ${used ?? "-"}

## 筛选关键词

${keywordText}

## 调研报告

${report.report}

## 参考文献

${refLines}
`;
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${safeTarget}_文献调研.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="literature-result">
      <div className="literature-meta">
        <span>References: {total ?? "-"} total</span>
        {Number.isFinite(afterPrescreen) && <span>{afterPrescreen} after prescreen</span>}
        {Number.isFinite(used) && <span>{used} sent to DeepSeek</span>}
      </div>
      <button type="button" className="ghost-button export-md-button" onClick={handleExportMarkdown}>
        <Download size={15} /> 导出 Markdown
      </button>
      <article className="literature-report">{report.report}</article>
      {references.length ? (
        <div className="report-references">
          <h3>参考文献</h3>
          <ul className="reference-list">
            {references.map((reference) => (
              <li key={reference.ref_id ?? reference.bibcode ?? reference.title}>
                <span>[{reference.ref_id}]</span>
                <ExternalTextLink href={adsUrl(reference.bibcode)}>{reference.bibcode || "ADS"}</ExternalTextLink>
                <span>{reference.year || "-"}</span>
                <strong>{reference.title || "Untitled reference"}</strong>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function TargetDeepLinks({ target }) {
  const mast = target.mast ?? {};
  const workflow = target.literature_workflow ?? {};
  const references = target.simbad?.references ?? [];
  const identifierGroups = [
    ["TIC", mast.tic_ids ?? []],
    ["EPIC", mast.epic_ids ?? []],
    ["KIC", mast.kic_ids ?? []],
  ];
  const missionEntries = Object.entries(mast.mission_observations ?? {});
  const observationCategories = workflow.observations ?? [];
  const topicCategories = workflow.research_topics ?? [];

  return (
    <div className="deep-link-grid">
      <DetailList title="MAST obs" count={mast.total_mission_observations ?? 0}>
        <div className="detail-columns">
          <div>
            <h3>Identifiers</h3>
            {identifierGroups.some(([, ids]) => ids.length) ? (
              <ul className="link-list">
                {identifierGroups.map(([kind, ids]) =>
                  ids.map((identifier) => (
                    <li key={`${kind}-${identifier}`}>
                      <ExternalTextLink href={mastIdentifierUrl(kind, identifier)}>
                        {kind} {identifier}
                      </ExternalTextLink>
                    </li>
                  )),
                )}
              </ul>
            ) : (
              <div className="muted-text">No TIC/EPIC/KIC identifiers in this result.</div>
            )}
          </div>
          <div>
            <h3>Mission Coverage</h3>
            {missionEntries.length ? (
              <ul className="stat-list">
                {missionEntries.map(([mission, count]) => (
                  <li key={mission}>
                    <span>{mission}</span>
                    <strong>{count}</strong>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="muted-text">No mission coverage returned.</div>
            )}
          </div>
        </div>
        <div className="detail-footer">
          <span>Radius: {mast.region_radius_deg ?? "-"} deg</span>
          <ExternalTextLink href="https://mast.stsci.edu/portal/Mashup/Clients/Mast/Portal.html">Open MAST Portal</ExternalTextLink>
        </div>
      </DetailList>

      <DetailList title="References" count={workflow.total_references ?? references.length}>
        <div className="reference-summary">
          <span>Analyzed {workflow.references_analyzed ?? 0}/{workflow.total_references ?? references.length} references</span>
          {workflow.reference_sources && (
            <span>Sources: {Object.entries(workflow.reference_sources).map(([source, count]) => `${source} ${count}`).join(", ")}</span>
          )}
        </div>

        <details className="nested-detail" open>
          <summary>Observation Categories</summary>
          <div className="category-list">
            {observationCategories.length ? observationCategories.map((category) => (
              <details key={category.category} className="category-item">
                <summary>
                  <span>{category.category}</span>
                  <strong>{category.count}</strong>
                </summary>
                <SampleReferenceList references={category.sample_references ?? []} />
              </details>
            )) : <div className="muted-text">No observation categories available.</div>}
          </div>
        </details>

        <details className="nested-detail">
          <summary>Research Topics</summary>
          <div className="category-list">
            {topicCategories.length ? topicCategories.map((category) => (
              <details key={category.category} className="category-item">
                <summary>
                  <span>{category.category}</span>
                  <strong>{category.count}</strong>
                </summary>
                <SampleReferenceList references={category.sample_references ?? []} />
              </details>
            )) : <div className="muted-text">No research topics available.</div>}
          </div>
        </details>

        <details className="nested-detail">
          <summary>SIMBAD References</summary>
          <ReferenceBrowser references={references} />
        </details>
      </DetailList>
    </div>
  );
}

function TargetSummary({ result }) {
  const target = result?.target;
  if (!target) {
    return <div className="empty-state">输入目标名或坐标后，SIMBAD、Gaia、MAST 和文献摘要会显示在这里。</div>;
  }

  return (
    <>
      <div className="summary-grid">
        <Metric label="Source" value={result.source === "results" ? "已有结果" : "重新检索"} />
        <Metric label="Result file" value={result.result_path} />
        <Metric label="Resolved" value={target.resolved_target || target.query_target} />
        <Metric label="Type" value={target.target_type} />
        <Metric label="RA" value={target.simbad?.ra_deg?.toFixed?.(6)} />
        <Metric label="Dec" value={target.simbad?.dec_deg?.toFixed?.(6)} />
        <Metric label="Spectral" value={target.simbad?.spectral_type} />
        <Metric label="Gaia DR3" value={target.gaia?.source_id} />
        <Metric label="G mag" value={target.gaia?.gmag} />
        <Metric label="Distance pc" value={target.gaia?.distance_pc} />
      </div>
      <TargetDeepLinks target={target} />
    </>
  );
}

function targetDisplayName(result, fallback) {
  const target = result?.target;
  return target?.resolved_target || target?.query_target || fallback;
}

function datasetLabel(dataset) {
  const generatedAt = dataset.generated_at ? new Date(dataset.generated_at).toLocaleString() : "unknown time";
  const points = dataset.csv_point_count ? `${dataset.csv_point_count} pts` : `${dataset.manifest_entries ?? 0} files`;
  return `${generatedAt} · ${points} · ${dataset.download_dir}`;
}

function buildPeriodOptions(analysis) {
  const bestPeriod = analysis?.period_search?.best_period;
  const periodogram = analysis?.period_search?.periodogram ?? [];
  const ranked = [...periodogram]
    .sort((left, right) => right.power - left.power)
    .slice(0, 6)
    .map((item) => item.period);
  const periods = [bestPeriod, ...ranked].filter((period) => Number.isFinite(period) && period > 0);
  return [...new Set(periods.map((period) => period.toPrecision(10)))].map(Number);
}

function foldCurve(curve, period) {
  if (!Number.isFinite(period) || period <= 0) {
    return [];
  }
  const singleCycle = curve
    .map((point) => ({
      phase: ((point.time / period) % 1 + 1) % 1,
      flux: point.normalized_flux,
      time: point.time,
    }))
    .filter((point) => Number.isFinite(point.phase) && Number.isFinite(point.flux))
    .sort((left, right) => left.phase - right.phase);
  // Dual-cycle [0, 2] – duplicate with phase shifted by +1
  const dualCycle = [
    ...singleCycle,
    ...singleCycle.map((point) => ({ ...point, phase: point.phase + 1 })),
  ];
  return dualCycle;
}

function foldCurveBinned(curve, period, numBins = 20) {
  if (!Number.isFinite(period) || period <= 0 || !curve.length) {
    return [];
  }
  const bins = Array.from({ length: numBins }, (_, i) => ({
    phase: (i + 0.5) / numBins,
    sum: 0,
    count: 0,
  }));
  for (const point of curve) {
    const phase = ((point.time / period) % 1 + 1) % 1;
    if (!Number.isFinite(phase) || !Number.isFinite(point.normalized_flux)) continue;
    const idx = Math.min(numBins - 1, Math.floor(phase * numBins));
    bins[idx].sum += point.normalized_flux;
    bins[idx].count += 1;
  }
  const singleBin = bins
    .filter((bin) => bin.count > 0)
    .map((bin) => ({ phase: bin.phase, flux: bin.sum / bin.count }));
  // Dual-cycle [0, 2]
  return [
    ...singleBin,
    ...singleBin.map((bin) => ({ phase: bin.phase + 1, flux: bin.flux })),
  ];
}

function spectrumTooltipLabel(frequency) {
  const numericFrequency = Number(frequency);
  if (!Number.isFinite(numericFrequency) || numericFrequency <= 0) {
    return "Frequency: -";
  }
  return `Frequency: ${numericFrequency.toPrecision(7)}  Period: ${(1 / numericFrequency).toPrecision(7)}`;
}

function periodSearchStatus(analysis, datasetBusy) {
  if (datasetBusy) {
    return "周期搜索运行中...";
  }
  const periodogramCount = analysis?.period_search?.periodogram?.length ?? 0;
  if (periodogramCount) {
    return `LS 频谱已生成：${periodogramCount} 个采样点，最佳周期 ${analysis.period_search.best_period?.toPrecision?.(7) ?? "-"}`;
  }
  if (analysis && !analysis.period_search) {
    return "分析完成，但没有可用周期结果；请检查时间跨度、点数或周期范围。";
  }
  return "运行周期搜索后显示功率谱；点击曲线可把周期送入相位折叠。";
}

function TargetPage({
  error,
  forceRefresh,
  handleLiteratureResearch,
  handleTargetQuery,
  literatureBusy,
  literatureQuestion,
  literatureReport,
  prescreenKeywords,
  references,
  setForceRefresh,
  setLiteratureQuestion,
  setPrescreenKeywords,
  setTargetName,
  setUseLlm,
  targetBusy,
  targetName,
  targetResult,
  useLlm,
}) {
  return (
    <section className="tool-grid">
      <aside className="control-panel">
        <form onSubmit={handleTargetQuery} className="panel-section">
          <div className="section-title"><Search size={18} /> 目标查询</div>
          <label>
            目标名或坐标
            <input value={targetName} onChange={(event) => setTargetName(event.target.value)} />
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={useLlm} onChange={(event) => setUseLlm(event.target.checked)} />
            使用 LLM 摘要
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={forceRefresh} onChange={(event) => setForceRefresh(event.target.checked)} />
            强制重新检索
          </label>
          <button type="submit" disabled={targetBusy}>{targetBusy ? "处理中..." : forceRefresh ? "重新检索目标" : "载入/查询目标"}</button>
        </form>
      </aside>

      <section className="results-panel">
        {error && <div className="error-banner">{error}</div>}
        <div className="panel-card target-card">
          <div className="section-title"><Database size={18} /> 目标信息</div>
          <TargetSummary result={targetResult} />
        </div>

        <div className="panel-card literature-card">
          <div className="section-title"><BookOpenText size={18} /> 文献调研</div>
          <div className="literature-controls">
            <label>
              调研重点
              <textarea value={literatureQuestion} onChange={(event) => setLiteratureQuestion(event.target.value)} />
            </label>
            <div className="literature-actions">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={prescreenKeywords}
                  onChange={(event) => setPrescreenKeywords(event.target.checked)}
                />
                关键词预筛选
              </label>
              <button type="button" onClick={handleLiteratureResearch} disabled={!references.length || literatureBusy}>
                {literatureBusy ? "调研中..." : `DeepSeek 调研 ${references.length || ""}`}
              </button>
            </div>
          </div>
          {literatureReport?.focus_keywords?.length ? (
            <div className="prescreen-keywords-info">
              <span className="prescreen-label">筛选关键词:</span>
              <div className="keyword-row">
                {literatureReport.focus_keywords.map((keyword) => <span key={keyword}>{keyword}</span>)}
              </div>
            </div>
          ) : null}
          {literatureReport?.report ? (
            <LiteratureReport report={literatureReport} targetName={targetName} />
          ) : (
            <div className="empty-state">完成目标查询后，可调用 DeepSeek 对该目标 references 做文献调研。</div>
          )}
        </div>
      </section>
    </section>
  );
}

function LightCurvePage({
  analysis,
  archiveBusy,
  archiveProducts,
  curve,
  datasets,
  datasetBusy,
  downloadResult,
  error,
  forceDownload,
  gapThreshold,
  handleAnalyze,
  handleAnalyzeDownloadedDataset,
  handleArchiveDownload,
  handleArchiveSearch,
  handleFile,
  handleRunPeriodSearch,
  handleSpectrumClick,
  handleTargetQuery,
  hasTargetCoordinates,
  maxPeriod,
  minPeriod,
  phaseCurve,
  phasePeriod,
  phasePeriodMode,
  points,
  polynomialOrder,
  samplesPerPeak,
  selectedDataset,
  selectedDatasetDir,
  selectedProducts,
  setForceDownload,
  setGapThreshold,
  setMaxPeriod,
  setMinPeriod,
  setPhasePeriod,
  setPhasePeriodMode,
  setPolynomialOrder,
  setSamplesPerPeak,
  setSelectedDatasetDir,
  setTargetName,
  targetBusy,
  targetName,
  targetResult,
  toggleProduct,
}) {
  const periodogram = analysis?.period_search?.periodogram ?? [];
  const periodOptions = buildPeriodOptions(analysis);
  const selectedManualPeriod = Number(phasePeriod);
  const selectedBestPeriod = analysis?.period_search?.best_period;
  const selectedPhasePeriod = phasePeriodMode === "manual" && Number.isFinite(selectedManualPeriod) && selectedManualPeriod > 0
    ? selectedManualPeriod
    : selectedBestPeriod;

  return (
    <section className="lc-workspace">
      {error && <div className="error-banner">{error}</div>}

      <aside className="control-panel lc-controls">
        <form onSubmit={handleTargetQuery} className="panel-section">
          <div className="section-title"><Search size={18} /> 光变目标</div>
          <label>
            目标名或坐标
            <input value={targetName} onChange={(event) => setTargetName(event.target.value)} />
          </label>
          <button type="submit" disabled={targetBusy}>{targetBusy ? "载入中..." : "载入目标与数据集"}</button>
        </form>

        <div className="panel-section">
          <div className="section-title"><Download size={18} /> 数据来源</div>
          <button type="button" onClick={handleArchiveSearch} disabled={!targetResult || !hasTargetCoordinates || archiveBusy}>
            {archiveBusy ? "处理中..." : "检索 MAST 光变曲线"}
          </button>
          <div className="download-actions">
            <button type="button" onClick={handleArchiveDownload} disabled={!archiveProducts.length || !selectedProducts.size || archiveBusy}>
              下载选中产品
            </button>
            <label className="checkbox-row">
              <input type="checkbox" checked={forceDownload} onChange={(event) => setForceDownload(event.target.checked)} />
              强制重新下载
            </label>
          </div>

          <div className="dataset-section">
            <div className="dataset-section-header">
              <span>已下载数据集</span>
              {datasets.length ? <strong>{datasets.length}</strong> : null}
            </div>
            {datasets.length ? (
              <div className="dataset-cards">
                {datasets.map((dataset) => {
                  const isSelected = dataset.download_dir === selectedDatasetDir;
                  const generatedAt = dataset.generated_at ? new Date(dataset.generated_at).toLocaleString() : "unknown";
                  return (
                    <button
                      type="button"
                      key={dataset.download_dir}
                      className={`dataset-card ${isSelected ? "selected" : ""}`}
                      onClick={() => {
                        setSelectedDatasetDir(dataset.download_dir);
                        handleAnalyzeDownloadedDataset(dataset.download_dir);
                      }}
                    >
                      <div className="dataset-card-top">
                        <span className="dataset-time">{generatedAt}</span>
                        <span className="dataset-points">{dataset.csv_point_count ?? dataset.manifest_entries ?? 0} pts</span>
                      </div>
                      {dataset.missions?.length ? (
                        <div className="dataset-missions">{dataset.missions.join(" · ")}</div>
                      ) : null}
                      {dataset.time_span_days != null ? (
                        <div className="dataset-span">跨度 {dataset.time_span_days} 天</div>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="empty-state compact-empty">载入目标后此处显示已下载数据集。</div>
            )}
          </div>

          <button type="button" onClick={() => handleAnalyzeDownloadedDataset()} disabled={!selectedDatasetDir || datasetBusy}>
            {datasetBusy ? "分析中..." : "分析选中下载数据"}
          </button>
          <label>
            CSV / whitespace: time flux [err]
            <input type="file" accept=".csv,.txt" onChange={handleFile} />
          </label>
          <button type="button" onClick={handleAnalyze} disabled={points.length < 3 || datasetBusy}>分析上传数据 {points.length || ""}</button>
        </div>

        <div className="panel-section">
          <div className="section-title"><BarChart3 size={18} /> 去趋势</div>
          <div className="input-row">
            <label>
              多项式阶数
              <input type="number" min="0" max="5" step="1" value={polynomialOrder} onChange={(event) => setPolynomialOrder(event.target.value)} />
            </label>
            <label>
              分段间隔 (天)
              <input type="number" min="0" step="0.1" value={gapThreshold} onChange={(event) => setGapThreshold(event.target.value)} placeholder="1.0" />
            </label>
          </div>
          <div className="hint-text">
            间隔阈值: 时间间隔超过此天数的数据将分段独立去趋势。设为 0 禁用分段。
          </div>
          {analysis?.detrend?.segment_count > 1 && (
            <div className="segment-info">
              已检测到 {analysis.detrend.segment_count} 个数据分段，各段独立去趋势。
            </div>
          )}
        </div>

        <div className="panel-section">
          <div className="section-title"><Orbit size={18} /> 周期搜索</div>
          <div className="input-row">
            <label>
              Min period
              <input type="number" min="0" step="0.0001" value={minPeriod} onChange={(event) => setMinPeriod(event.target.value)} placeholder="auto" />
            </label>
            <label>
              Max period
              <input type="number" min="0" step="0.0001" value={maxPeriod} onChange={(event) => setMaxPeriod(event.target.value)} placeholder="auto" />
            </label>
          </div>
          <label>
            Samples per peak
            <input type="number" min="2" max="50" value={samplesPerPeak} onChange={(event) => setSamplesPerPeak(event.target.value)} />
          </label>
          <button
            type="button"
            onClick={handleRunPeriodSearch}
            disabled={datasetBusy || (!selectedDatasetDir && points.length < 3)}
          >
            {datasetBusy ? "搜索中..." : "运行周期搜索"}
          </button>
        </div>

        <div className="panel-section">
          <div className="section-title"><Activity size={18} /> 相位周期</div>
          <label>
            周期来源
            <select value={phasePeriodMode} onChange={(event) => setPhasePeriodMode(event.target.value)}>
              <option value="best">最佳周期</option>
              <option value="manual">手动输入</option>
            </select>
          </label>
          <label>
            合并相位周期
            <input
              type="number"
              min="0"
              step="0.000001"
              value={phasePeriod}
              onChange={(event) => {
                setPhasePeriod(event.target.value);
                setPhasePeriodMode("manual");
              }}
              placeholder={analysis?.period_search?.best_period?.toPrecision?.(8) ?? "period"}
            />
          </label>
          {periodOptions.length > 0 && (
            <div className="period-choice-list">
              {periodOptions.map((period) => (
                <button
                  type="button"
                  className="ghost-button"
                  key={period}
                  onClick={() => {
                    setPhasePeriod(period.toPrecision(10));
                    setPhasePeriodMode("manual");
                  }}
                >
                  {period.toPrecision(7)}
                </button>
              ))}
            </div>
          )}
        </div>
      </aside>

      <section className="lc-results">
        <div className="panel-card target-card">
          <div className="section-title"><Database size={18} /> 数据集状态</div>
          <div className="summary-grid compact-summary">
            <Metric label="Target" value={targetDisplayName(targetResult, targetName)} />
            <Metric label="Loaded points" value={analysis?.point_count ?? points.length} />
            <Metric label="Time span" value={analysis?.time_span?.toPrecision?.(7)} />
            <Metric label="Best period" value={analysis?.period_search?.best_period?.toPrecision?.(7)} />
            <Metric label="FAP" value={analysis?.period_search?.false_alarm_probability?.toExponential?.(2)} />
          </div>
        </div>

        <div className="panel-card archive-card">
          <div className="section-title"><Download size={18} /> MAST 产品与本地曲线</div>
          {archiveProducts.length ? (
            <div className="archive-list">
              {archiveProducts.slice(0, 12).map((product) => (
                <label className="product-row" key={product.product_uri || product.filename}>
                  <input
                    type="checkbox"
                    checked={selectedProducts.has(product.product_uri)}
                    onChange={() => toggleProduct(product.product_uri)}
                    disabled={!product.product_uri}
                  />
                  <span>
                    <strong>{product.mission || "MAST"}</strong>
                    <em>{product.subgroup || "LC"}</em>
                    {product.filename || product.obs_id}
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <div className="empty-state compact-empty">载入目标后可检索 TESS、Kepler、K2 的 MAST 光变曲线 FITS 产品。</div>
          )}
          {downloadResult?.download_dir && (
            <div className="download-result">
              {downloadResult.deduplicated ? (
                <span>📋 已存在相同数据集，直接复用：<strong>{downloadResult.download_dir}</strong></span>
              ) : (
                <span>已保存到 <strong>{downloadResult.download_dir}</strong>，manifest 条目 {downloadResult.manifest?.length ?? 0}。</span>
              )}
              {downloadResult.csv?.csv_path && (
                <span>CSV: <strong>{downloadResult.csv.csv_path}</strong>，点数 {downloadResult.csv.point_count}。</span>
              )}
            </div>
          )}
          {selectedDataset && !downloadResult?.download_dir && (
            <div className="download-result">
              已选择 <strong>{selectedDataset.download_dir}</strong>
              {selectedDataset.csv_path && <span>CSV: <strong>{selectedDataset.csv_path}</strong></span>}
            </div>
          )}
        </div>

        <div className="analysis-grid">
          <div className="panel-card chart-card">
            <div className="section-title"><BarChart3 size={18} /> 去趋势与归一化</div>
            {curve.length ? (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={curve} margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} />
                  <YAxis domain={["auto", "auto"]} />
                  <Tooltip />
                  <Line type="monotone" dataKey="normalized_flux" dot={false} stroke="#0f766e" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-state">选择已下载数据集或上传 time/flux 表后可分析。</div>
            )}
          </div>

          <div className="panel-card chart-card">
            <div className="section-title"><Activity size={18} /> Lomb-Scargle 频谱</div>
            <div className="chart-note">{periodSearchStatus(analysis, datasetBusy)}</div>
            {periodogram.length ? (
              <div className="chart-frame" data-testid="ls-periodogram">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={periodogram} onClick={handleSpectrumClick} margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="frequency"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                    />
                    <YAxis dataKey="power" domain={[0, "auto"]} />
                    <Tooltip
                      labelFormatter={spectrumTooltipLabel}
                      formatter={(value, name, item) => [
                        Number(value).toPrecision(7),
                        name === "power" ? `power, period ${item.payload.period.toPrecision(7)}` : name,
                      ]}
                    />
                    {analysis?.period_search?.noise_stats?.threshold_4sigma != null && (
                      <ReferenceLine
                        y={analysis.period_search.noise_stats.threshold_4sigma}
                        stroke="#6b7280"
                        strokeDasharray="6 3"
                        label={{ value: "4σ", position: "right", fill: "#6b7280", fontSize: 12 }}
                      />
                    )}
                    {analysis?.period_search?.best_frequency && (
                      <ReferenceLine
                        x={analysis.period_search.best_frequency}
                        stroke="#0f766e"
                        strokeDasharray="4 4"
                      />
                    )}
                    <Line type="linear" dataKey="power" dot={false} stroke="#b45309" strokeWidth={2} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="empty-state">{periodSearchStatus(analysis, datasetBusy)}</div>
            )}
          </div>
        </div>

        <div className="analysis-row">
          <div className="panel-card">
            <div className="section-title"><Orbit size={18} /> 周期指标</div>
            <Metric label="Best period" value={analysis?.period_search?.best_period?.toPrecision?.(7)} />
            <Metric
              label="Period (hours)"
              value={analysis?.period_search?.best_period ? (analysis.period_search.best_period * 24).toPrecision(6) : "-"}
            />
            <Metric
              label="Period (minutes)"
              value={analysis?.period_search?.best_period ? (analysis.period_search.best_period * 1440).toFixed(2) : "-"}
            />
            <Metric label="Power" value={analysis?.period_search?.power?.toFixed?.(4)} />
            {analysis?.period_search?.noise_stats && (
              <>
                <Metric label="4σ threshold" value={analysis.period_search.noise_stats.threshold_4sigma?.toFixed?.(4)} />
                <Metric label="Noise σ" value={analysis.period_search.noise_stats.sigma?.toFixed?.(4)} />
              </>
            )}
            <Metric
              label="Phase period"
              value={
                phasePeriodMode === "manual" && Number.isFinite(Number(phasePeriod)) && Number(phasePeriod) > 0
                  ? Number(phasePeriod).toPrecision(7)
                  : analysis?.period_search?.best_period?.toPrecision?.(7)
              }
            />
          </div>
          <div className="panel-card phase-card">
            <div className="section-title"><Activity size={18} /> 相位折叠 (2 Cycles)</div>
            {phaseCurve.length ? (
              <ResponsiveContainer width="100%" height={320}>
                <ScatterChart margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="phase" type="number" domain={[0, 2]} tickCount={5} />
                  <YAxis dataKey="flux" domain={["auto", "auto"]} />
                  <Tooltip />
                  {/* 底层: 灰点原始数据 */}
                  <Scatter data={phaseCurve} fill="#9ca3af" fillOpacity={0.35} name="Raw" />
                  {/* 顶层: 红色分箱点+连线 */}
                  {foldCurveBinned(curve, selectedPhasePeriod).length > 0 && (
                    <Scatter
                      data={foldCurveBinned(curve, selectedPhasePeriod)}
                      fill="#ef4444"
                      stroke="#ef4444"
                      strokeWidth={3}
                      fillOpacity={1}
                      name="Binned (20 bins)"
                      shape="circle"
                      legendType="circle"
                    />
                  )}
                </ScatterChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-state">运行周期搜索，或输入一个周期后合并相位。</div>
            )}
          </div>
        </div>
      </section>
    </section>
  );
}

function App() {
  const [page, setPage] = React.useState("target");
  const [targetName, setTargetName] = React.useState("AD Leo");
  const [useLlm, setUseLlm] = React.useState(false);
  const [forceRefresh, setForceRefresh] = React.useState(false);
  const [targetResult, setTargetResult] = React.useState(null);
  const [targetBusy, setTargetBusy] = React.useState(false);
  const [points, setPoints] = React.useState([]);
  const [analysis, setAnalysis] = React.useState(null);
  const [literatureQuestion, setLiteratureQuestion] = React.useState("重点关注光变曲线、周期、恒星活动和磁场相关研究。");
  const [literatureReport, setLiteratureReport] = React.useState(null);
  const [literatureBusy, setLiteratureBusy] = React.useState(false);
  const [prescreenKeywords, setPrescreenKeywords] = React.useState(true);
  const [archiveProducts, setArchiveProducts] = React.useState([]);
  const [selectedProducts, setSelectedProducts] = React.useState(new Set());
  const [archiveBusy, setArchiveBusy] = React.useState(false);
  const [datasetBusy, setDatasetBusy] = React.useState(false);
  const [datasets, setDatasets] = React.useState([]);
  const [selectedDatasetDir, setSelectedDatasetDir] = React.useState("");
  const [downloadResult, setDownloadResult] = React.useState(null);
  const [minPeriod, setMinPeriod] = React.useState("");
  const [maxPeriod, setMaxPeriod] = React.useState("");
  const [samplesPerPeak, setSamplesPerPeak] = React.useState("8");
  const [polynomialOrder, setPolynomialOrder] = React.useState("2");
  const [gapThreshold, setGapThreshold] = React.useState("1.0");
  const [phasePeriodMode, setPhasePeriodMode] = React.useState("best");
  const [phasePeriod, setPhasePeriod] = React.useState("");
  const [forceDownload, setForceDownload] = React.useState(false);
  const [error, setError] = React.useState("");

  async function refreshDatasetsFor(result, preferredDownloadDir = "", autoSelectFirst = false, autoAnalyze = false) {
    const response = await listLightCurveDatasets(targetDisplayName(result, targetName));
    const nextDatasets = response.datasets ?? [];
    setDatasets(nextDatasets);
    let selectedDir = "";
    if (preferredDownloadDir) {
      selectedDir = preferredDownloadDir;
      setSelectedDatasetDir(preferredDownloadDir);
    } else if (autoSelectFirst) {
      selectedDir = nextDatasets[0]?.download_dir ?? "";
      setSelectedDatasetDir(selectedDir);
    } else if (!nextDatasets.some((dataset) => dataset.download_dir === selectedDatasetDir)) {
      selectedDir = nextDatasets[0]?.download_dir ?? "";
      setSelectedDatasetDir(selectedDir);
    }
    if (autoAnalyze && selectedDir) {
      handleAnalyzeDownloadedDataset(selectedDir);
    }
  }

  function analysisPayload() {
    const minValue = Number(minPeriod);
    const maxValue = Number(maxPeriod);
    const order = Math.min(5, Math.max(0, Number(polynomialOrder) || 2));
    const gapValue = Number(gapThreshold);
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
        samples_per_peak: Math.min(50, Math.max(2, Number(samplesPerPeak) || 8)),
      },
    };
  }

  async function handleTargetQuery(event) {
    event.preventDefault();
    setError("");
    setTargetBusy(true);
    try {
      const result = await queryTarget({ target: targetName, use_llm: useLlm, force_refresh: forceRefresh });
      setTargetResult(result);
      setLiteratureReport(null);
      setArchiveProducts([]);
      setSelectedProducts(new Set());
      setDownloadResult(null);
      setDatasets([]);
      setSelectedDatasetDir("");
      await refreshDatasetsFor(result, "", true, true);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setTargetBusy(false);
    }
  }

  function lightCurveArchivePayload() {
    const target = targetResult?.target;
    const simbad = target?.simbad;
    return {
      target: target?.resolved_target || target?.query_target || targetName,
      ra_deg: simbad?.ra_deg ?? null,
      dec_deg: simbad?.dec_deg ?? null,
      radius_deg: target?.mast?.region_radius_deg ?? 0.02,
      missions: ["TESS", "Kepler", "K2"],
      max_products: 80,
    };
  }

  async function handleArchiveSearch() {
    setError("");
    setArchiveBusy(true);
    setDownloadResult(null);
    try {
      const response = await searchLightCurves(lightCurveArchivePayload());
      setArchiveProducts(response.products ?? []);
      setSelectedProducts(new Set((response.products ?? []).slice(0, 5).map((product) => product.product_uri).filter(Boolean)));
    } catch (caught) {
      setError(caught.message);
    } finally {
      setArchiveBusy(false);
    }
  }

  async function handleArchiveDownload() {
    setError("");
    setArchiveBusy(true);
    try {
      const response = await downloadLightCurves({
        ...lightCurveArchivePayload(),
        product_uris: Array.from(selectedProducts),
        max_downloads: 5,
        force: forceDownload,
      });
      setDownloadResult(response);
      setSelectedDatasetDir(response.download_dir);
      await refreshDatasetsFor(targetResult, response.download_dir, false, !response.deduplicated);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setArchiveBusy(false);
    }
  }

  async function handleAnalyzeDownloadedDataset(downloadDir = selectedDatasetDir || downloadResult?.download_dir) {
    if (!downloadDir) return;
    setError("");
    setDatasetBusy(true);
    try {
      const response = await analyzeDownloadedLightCurve({
        download_dir: downloadDir,
        quality_filter: true,
        max_points: 5000,
        ...analysisPayload(),
      });
      setAnalysis(response);
      setPoints([]);
      setPhasePeriodMode("best");
      setPhasePeriod("");
    } catch (caught) {
      setError(caught.message);
    } finally {
      setDatasetBusy(false);
    }
  }

  function toggleProduct(productUri) {
    setSelectedProducts((current) => {
      const next = new Set(current);
      if (next.has(productUri)) {
        next.delete(productUri);
      } else {
        next.add(productUri);
      }
      return next;
    });
  }

  async function handleFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const parsed = parseCsv(text);
    setPoints(parsed);
    setAnalysis(null);
    setPhasePeriod("");
  }

  async function handleAnalyze() {
    setError("");
    try {
      setAnalysis(
        await analyzeLightCurve({
          points,
          ...analysisPayload(),
        }),
      );
      setPhasePeriodMode("best");
      setPhasePeriod("");
    } catch (caught) {
      setError(caught.message);
    }
  }

  async function handleRunPeriodSearch() {
    if (selectedDatasetDir) {
      await handleAnalyzeDownloadedDataset(selectedDatasetDir);
      return;
    }
    if (points.length >= 3) {
      await handleAnalyze();
      return;
    }
    setError("请先选择已下载数据集，或上传至少三行 time/flux 数据。");
  }

  async function handleLiteratureResearch() {
    const target = targetResult?.target;
    if (!target) return;

    setError("");
    setLiteratureBusy(true);
    try {
      const response = await researchLiterature({
        target: target.resolved_target || target.query_target || targetName,
        target_type: target.target_type || "unknown",
        references: target.literature_references?.length ? target.literature_references : (target.simbad?.references ?? []),
        literature_workflow: target.literature_workflow ?? null,
        focus_question: literatureQuestion,
        prescreen_keywords: prescreenKeywords,
      });
      setLiteratureReport(response);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLiteratureBusy(false);
    }
  }

  function handleSpectrumClick(event) {
    const period = event?.activePayload?.[0]?.payload?.period;
    if (!Number.isFinite(period)) return;
    setPhasePeriod(period.toPrecision(10));
    setPhasePeriodMode("manual");
  }

  const curve = analysis?.detrend?.curve ?? [];
  const selectedManualPeriod = Number(phasePeriod);
  const selectedBestPeriod = analysis?.period_search?.best_period;
  const selectedPhasePeriod = phasePeriodMode === "manual" ? selectedManualPeriod : selectedBestPeriod;
  const phaseCurve = Number.isFinite(selectedPhasePeriod) && curve.length
    ? foldCurve(curve, selectedPhasePeriod)
    : analysis?.period_search?.phase_curve ?? [];
  const targetReferences = targetResult?.target?.literature_references;
  const references = targetReferences?.length ? targetReferences : (targetResult?.target?.simbad?.references ?? []);
  const hasTargetCoordinates = Number.isFinite(targetResult?.target?.simbad?.ra_deg) && Number.isFinite(targetResult?.target?.simbad?.dec_deg);
  const selectedDataset = datasets.find((dataset) => dataset.download_dir === selectedDatasetDir);

  return (
    <main className="app-shell">
      <section className="workspace-header">
        <div>
          <p className="eyebrow">Interactive astronomy workspace</p>
          <h1>{page === "lightcurves" ? "Light Curve Lab" : "Target Info Search"}</h1>
        </div>
        <div className="page-switcher">
          <button type="button" className={page === "target" ? "nav-button active" : "nav-button"} onClick={() => setPage("target")}>
            目标信息
          </button>
          <button type="button" className={page === "lightcurves" ? "nav-button active" : "nav-button"} onClick={() => setPage("lightcurves")}>
            光变曲线
          </button>
        </div>
      </section>

      {page === "target" ? (
        <TargetPage
          error={error}
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
          analysis={analysis}
          archiveBusy={archiveBusy}
          archiveProducts={archiveProducts}
          curve={curve}
          datasets={datasets}
          datasetBusy={datasetBusy}
          downloadResult={downloadResult}
          error={error}
          forceDownload={forceDownload}
          gapThreshold={gapThreshold}
          handleAnalyze={handleAnalyze}
          handleAnalyzeDownloadedDataset={handleAnalyzeDownloadedDataset}
          handleArchiveDownload={handleArchiveDownload}
          handleArchiveSearch={handleArchiveSearch}
          handleFile={handleFile}
          handleRunPeriodSearch={handleRunPeriodSearch}
          handleSpectrumClick={handleSpectrumClick}
          handleTargetQuery={handleTargetQuery}
          hasTargetCoordinates={hasTargetCoordinates}
          maxPeriod={maxPeriod}
          minPeriod={minPeriod}
          phaseCurve={phaseCurve}
          phasePeriod={phasePeriod}
          phasePeriodMode={phasePeriodMode}
          points={points}
          polynomialOrder={polynomialOrder}
          samplesPerPeak={samplesPerPeak}
          selectedDataset={selectedDataset}
          selectedDatasetDir={selectedDatasetDir}
          selectedProducts={selectedProducts}
          setForceDownload={setForceDownload}
          setGapThreshold={setGapThreshold}
          setMaxPeriod={setMaxPeriod}
          setMinPeriod={setMinPeriod}
          setPhasePeriod={setPhasePeriod}
          setPhasePeriodMode={setPhasePeriodMode}
          setPolynomialOrder={setPolynomialOrder}
          setSamplesPerPeak={setSamplesPerPeak}
          setSelectedDatasetDir={setSelectedDatasetDir}
          setTargetName={setTargetName}
          targetBusy={targetBusy}
          targetName={targetName}
          targetResult={targetResult}
          toggleProduct={toggleProduct}
        />
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
