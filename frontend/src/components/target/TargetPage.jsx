import { useState, useEffect } from "react";
import { Activity, BarChart3, BookOpenText, Database, Download, ExternalLink, Orbit, Search } from "lucide-react";
import Metric from "../shared/Metric";
import ErrorBanner from "../shared/ErrorBanner";
import EmptyState from "../shared/EmptyState";

// ── Helpers ─────────────────────────────────────────────────────
function ExternalTextLink({ href, children }) {
  if (!href) return <span>{children}</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-link">
      {children}
      <ExternalLink size={13} />
    </a>
  );
}

function mastIdentifierUrl(kind, identifier) {
  if (!identifier) return "";
  const catalog = kind === "TIC" ? "TIC" : kind;
  return `https://mast.stsci.edu/portal/Mashup/Clients/Mast/Portal.html?searchQuery=${encodeURIComponent(`${catalog} ${identifier}`)}`;
}

function adsUrl(bibcode) {
  return bibcode ? `https://ui.adsabs.harvard.edu/abs/${encodeURIComponent(bibcode)}/abstract` : "";
}

function parseSampleReference(reference) {
  const text = String(reference ?? "");
  const match = text.match(/^([^:\s]+):\s*(.*)$/);
  if (!match) return { bibcode: "", title: text };
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
  if (!references?.length) return <div className="muted-text">No sample references available.</div>;
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
  const [startIndex, setStartIndex] = useState(0);
  const maxStart = Math.max(0, references.length - pageSize);
  const normalizedStart = Math.min(startIndex, maxStart);
  const visibleReferences = references.slice(normalizedStart, normalizedStart + pageSize);

  useEffect(() => { setStartIndex(0); }, [references]);

  if (!references.length) return <div className="muted-text">No SIMBAD references returned.</div>;

  return (
    <div className="reference-browser">
      <div className="reference-slider-row">
        <span>Showing {normalizedStart + 1}-{Math.min(normalizedStart + pageSize, references.length)} of {references.length}</span>
        <input type="range" min="0" max={maxStart} step={pageSize} value={normalizedStart}
          onChange={(e) => setStartIndex(Number(e.target.value))} aria-label="Browse SIMBAD references" />
      </div>
      <div className="reference-pager">
        <button type="button" className="ghost-button" disabled={normalizedStart === 0}
          onClick={() => setStartIndex(Math.max(0, normalizedStart - pageSize))}>Previous</button>
        <button type="button" className="ghost-button" disabled={normalizedStart >= maxStart}
          onClick={() => setStartIndex(Math.min(maxStart, normalizedStart + pageSize))}>Next</button>
      </div>
      <ul className="reference-list">
        {visibleReferences.map((ref) => (
          <li key={ref.bibcode || ref.title}>
            <ExternalTextLink href={adsUrl(ref.bibcode)}>{ref.bibcode || "ADS"}</ExternalTextLink>
            <span>{ref.year || "-"}</span>
            <strong>{ref.title || "Untitled reference"}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

function LiteratureReport({ report, targetName }) {
  if (!report?.report) return null;
  const references = report.report_references ?? [];
  const keywords = report.focus_keywords ?? [];
  const total = report.reference_count_total ?? report.reference_count;
  const afterPrescreen = report.reference_count_after_prescreen;
  const used = report.reference_count_used;

  function handleExportMarkdown() {
    const refLines = references.map((ref) => {
      const bibcode = ref.bibcode || ref.ref_id || "-";
      return `- [${ref.ref_id}] **${bibcode}** (${ref.year || "-"}) ${ref.title || "Untitled"}`;
    }).join("\n");
    const keywordText = keywords.length ? keywords.join(", ") : "无";
    const safeTarget = (targetName || "文献调研").replace(/[\\/:*?"<>|]/g, "_");
    const md = `# ${safeTarget} 文献调研报告\n\n> 生成时间: ${new Date().toLocaleString()}\n\n## 统计\n\n- 总文献数: ${total ?? "-"}\n- 预筛选后: ${afterPrescreen ?? "-"}\n- 送入大模型: ${used ?? "-"}\n\n## 筛选关键词\n\n${keywordText}\n\n## 调研报告\n\n${report.report}\n\n## 参考文献\n\n${refLines}\n`;
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${safeTarget}_文献调研.md`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="literature-result">
      <div className="literature-meta">
        <span>References: {total ?? "-"} total</span>
        {Number.isFinite(afterPrescreen) && <span>{afterPrescreen} after prescreen</span>}
        {Number.isFinite(used) && <span>{used} sent to LLM</span>}
      </div>
      <button type="button" className="ghost-button export-md-button" onClick={handleExportMarkdown}>
        <Download size={15} /> 导出 Markdown
      </button>
      <article className="literature-report">{report.report}</article>
      {references.length > 0 && (
        <div className="report-references">
          <h3>参考文献</h3>
          <ul className="reference-list">
            {references.map((ref) => (
              <li key={ref.ref_id ?? ref.bibcode ?? ref.title}>
                <span>[{ref.ref_id}]</span>
                <ExternalTextLink href={adsUrl(ref.bibcode)}>{ref.bibcode || "ADS"}</ExternalTextLink>
                <span>{ref.year || "-"}</span>
                <strong>{ref.title || "Untitled reference"}</strong>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TargetDeepLinks({ target }) {
  const mast = target.mast ?? {};
  const workflow = target.literature_workflow ?? {};
  const references = target.simbad?.references ?? [];
  const MISSION_ID_MAP = { TESS: ["TIC", mast.tic_ids ?? []], K2: ["EPIC", mast.epic_ids ?? []], Kepler: ["KIC", mast.kic_ids ?? []] };
  const missionEntries = Object.entries(mast.mission_observations ?? {});
  const timeInfo = mast.mission_time_info ?? {};
  const observationCategories = workflow.observations ?? [];
  const topicCategories = workflow.research_topics ?? [];

  return (
    <div className="deep-link-grid">
      <DetailList title="MAST obs" count={mast.total_mission_observations ?? 0}>
        {missionEntries.length ? (
          <table className="mast-mission-table">
            <thead>
              <tr>
                <th>Mission</th>
                <th>Target ID</th>
                <th>Obs</th>
                <th>Coverage</th>
              </tr>
            </thead>
            <tbody>
              {missionEntries.map(([mission, count]) => {
                const idEntry = MISSION_ID_MAP[mission];
                const timeStr = timeInfo[mission] || "";
                return (
                  <tr key={mission}>
                    <td className="mission-name">{mission}</td>
                    <td className="mission-id">
                      {idEntry && idEntry[1].length > 0 ? (
                        idEntry[1].map((identifier) => (
                          <ExternalTextLink key={`${mission}-${identifier}`} href={mastIdentifierUrl(idEntry[0], identifier)}>
                            {idEntry[0]} {identifier}
                          </ExternalTextLink>
                        ))
                      ) : (
                        <span className="muted-text">—</span>
                      )}
                    </td>
                    <td className="mission-count"><strong>{count}</strong></td>
                    <td className="mission-time">{timeStr || <span className="muted-text">—</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="muted-text">No mission coverage returned.</div>
        )}
        <div className="detail-footer">
          <span>Radius: {mast.region_radius_deg ?? "-"} deg</span>
          <ExternalTextLink href="https://mast.stsci.edu/portal/Mashup/Clients/Mast/Portal.html">Open MAST Portal</ExternalTextLink>
        </div>
      </DetailList>

      <DetailList title="References" count={workflow.total_references ?? references.length}>
        <div className="reference-summary">
          <span>Analyzed {workflow.references_analyzed ?? 0}/{workflow.total_references ?? references.length} references</span>
          {workflow.reference_sources && (
            <span>Sources: {Object.entries(workflow.reference_sources).map(([s, c]) => `${s} ${c}`).join(", ")}</span>
          )}
        </div>
        <details className="nested-detail" open>
          <summary>Observation Categories</summary>
          <div className="category-list">
            {observationCategories.length ? observationCategories.map((cat) => (
              <details key={cat.category} className="category-item">
                <summary><span>{cat.category}</span><strong>{cat.count}</strong></summary>
                <SampleReferenceList references={cat.sample_references ?? []} />
              </details>
            )) : <div className="muted-text">No observation categories available.</div>}
          </div>
        </details>
        <details className="nested-detail">
          <summary>Research Topics</summary>
          <div className="category-list">
            {topicCategories.length ? topicCategories.map((cat) => (
              <details key={cat.category} className="category-item">
                <summary><span>{cat.category}</span><strong>{cat.count}</strong></summary>
                <SampleReferenceList references={cat.sample_references ?? []} />
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
  if (!target) return <EmptyState>输入目标名或坐标后，SIMBAD、Gaia、MAST 和文献摘要会显示在这里。</EmptyState>;

  return (
    <>
      <div className="summary-grid">
        <Metric label="Source" value={["results", "warehouse", "postgres-s3"].includes(result.source) ? "已有结果" : "重新检索"} />
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

// ── TargetPage ───────────────────────────────────────────────────
export default function TargetPage({
  error,
  forceRefresh,
  handleLiteratureResearch,
  handleTargetQuery,
  literatureBusy,
  literatureQuestion,
  literatureReport,
  llmProfileId,
  llmProfiles,
  prescreenKeywords,
  references,
  setForceRefresh,
  setLiteratureQuestion,
  setLlmProfileId,
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
          <label>
            大模型配置
            <select value={llmProfileId} onChange={(event) => setLlmProfileId(event.target.value)} disabled={!llmProfiles.length}>
              {!llmProfiles.length ? <option value="">请先在插件中心配置</option> : null}
              {llmProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.model}</option>)}
            </select>
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={forceRefresh} onChange={(event) => setForceRefresh(event.target.checked)} />
            强制重新检索
          </label>
          <button type="submit" disabled={targetBusy}>
            {targetBusy ? "处理中..." : forceRefresh ? "重新检索目标" : "载入/查询目标"}
          </button>
        </form>
      </aside>

      <section className="results-panel">
        <ErrorBanner message={error} />
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
                <input type="checkbox" checked={prescreenKeywords} onChange={(event) => setPrescreenKeywords(event.target.checked)} />
                关键词预筛选
              </label>
              <button type="button" onClick={handleLiteratureResearch} disabled={!references.length || literatureBusy}>
                {literatureBusy ? "调研中..." : `LLM 调研 ${references.length || ""}`}
              </button>
            </div>
          </div>
          {literatureReport?.focus_keywords?.length ? (
            <div className="prescreen-keywords-info">
              <span className="prescreen-label">筛选关键词:</span>
              <div className="keyword-row">
                {literatureReport.focus_keywords.map((kw) => <span key={kw}>{kw}</span>)}
              </div>
            </div>
          ) : null}
          {literatureReport?.report ? (
            <LiteratureReport report={literatureReport} targetName={targetName} />
          ) : (
            <EmptyState>完成目标查询后，可使用当前模型配置对 references 做文献调研。</EmptyState>
          )}
        </div>
      </section>
    </section>
  );
}
