import { useState } from "react";
import {
  Star,
  ChevronDown,
  ChevronRight,
  Database,
  FileText,
  HardDrive,
  Activity,
  Circle,
  UserCheck,
  MapPin,
  BookOpen,
  Calendar,
  AlertCircle,
  File,
  Table2,
} from "lucide-react";

const TYPE_LABELS = {
  target_result: "目标查询结果",
  lightcurve_dataset: "光变曲线数据集",
};

function formatSize(bytes) {
  if (bytes == null) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function formatDate(iso) {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

export default function StarCard({
  star,
  expanded,
  selected,
  onToggleExpand,
  onToggleSelect,
  onDelete,
  busy,
  canManage = false,
}) {
  const { name, normalized, target_entry, lc_entries, total_size_bytes, entry_count, has_lc, has_target } = star;
  const meta = target_entry?.metadata || {};
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const handleDelete = () => {
    if (showDeleteConfirm) {
      onDelete(normalized);
      setShowDeleteConfirm(false);
    } else {
      setShowDeleteConfirm(true);
    }
  };

  const handleCancelDelete = () => setShowDeleteConfirm(false);

  // Compute unique missions across LC datasets
  const allMissions = new Set();
  let totalPoints = 0;
  lc_entries.forEach((lc) => {
    (lc.metadata?.missions || []).forEach((m) => allMissions.add(m));
    totalPoints += lc.metadata?.point_count || 0;
  });

  return (
    <div className={`dm-star-card${expanded ? " expanded" : ""}${selected ? " selected" : ""}`}>
      {/* ── Card header ── */}
      <div className="dm-star-header" onClick={() => onToggleExpand(normalized)}>
        {canManage ? <input
          type="checkbox"
          className="dm-star-checkbox"
          aria-label={`选择 ${name}`}
          checked={selected}
          onChange={(e) => {
            e.stopPropagation();
            onToggleSelect(normalized);
          }}
          onClick={(e) => e.stopPropagation()}
          disabled={busy}
        /> : null}

        <button
          type="button"
          className="dm-expand-btn"
          aria-label={expanded ? `收起 ${name}` : `展开 ${name}`}
          aria-expanded={expanded}
          onClick={(event) => {
            event.stopPropagation();
            onToggleExpand(normalized);
          }}
        >
          {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
        </button>

        <Star size={18} className="dm-star-icon" />

        <div className="dm-star-name-section">
          <h3 className="dm-star-name">{name}</h3>
          <div className="dm-star-badges">
            {has_target && meta.target_type ? (
              <span className="dm-badge">{meta.target_type}</span>
            ) : null}
            {has_lc ? (
              <span className="dm-badge dm-badge-lc">
                <Activity size={12} />
                {lc_entries.length} 光变数据集
              </span>
            ) : null}
          </div>
        </div>

        <div className="dm-star-stats">
          <span className="dm-stat-chip" title="总数据量">
            <HardDrive size={14} />
            {formatSize(total_size_bytes)}
          </span>
          <span className="dm-stat-chip" title="条目数">
            <Database size={14} />
            {entry_count} 条目
          </span>
        </div>

        {canManage ? <div className="dm-star-actions">
          {showDeleteConfirm ? (
            <>
              <button
                type="button"
                className="danger-button small"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete();
                }}
                disabled={busy}
              >
                确认删除
              </button>
              <button
                type="button"
                className="ghost-button small"
                onClick={(e) => {
                  e.stopPropagation();
                  handleCancelDelete();
                }}
                disabled={busy}
              >
                取消
              </button>
            </>
          ) : (
            <button
              type="button"
              className="danger-button small"
              onClick={(e) => {
                e.stopPropagation();
                handleDelete();
              }}
              disabled={busy}
            >
              删除
            </button>
          )}
        </div> : null}
      </div>

      {/* ── Card body (expanded) ── */}
      {expanded ? (
        <div className="dm-star-body">
          {/* Target info section */}
          {has_target ? (
            <div className="dm-star-section">
              <h4 className="dm-section-title">
                <FileText size={14} />
                目标查询信息
              </h4>
              <div className="dm-star-detail-grid">
                {meta.target_type ? (
                  <div className="dm-detail-item">
                    <span className="dm-detail-label"><UserCheck size={13} /> 类型</span>
                    <span>{meta.target_type}</span>
                  </div>
                ) : null}
                {meta.ra_deg != null ? (
                  <div className="dm-detail-item">
                    <span className="dm-detail-label"><MapPin size={13} /> 坐标</span>
                    <span>
                      {meta.ra_deg.toFixed(4)}° / {meta.dec_deg.toFixed(4)}°
                    </span>
                  </div>
                ) : null}
                {meta.reference_count != null ? (
                  <div className="dm-detail-item">
                    <span className="dm-detail-label"><BookOpen size={13} /> 参考文献</span>
                    <span>{meta.reference_count} 篇</span>
                  </div>
                ) : null}
                {target_entry?.source ? (
                  <div className="dm-detail-item">
                    <span className="dm-detail-label">来源</span>
                    <span>{target_entry.source}</span>
                  </div>
                ) : null}
                {target_entry?.created_at ? (
                  <div className="dm-detail-item">
                    <span className="dm-detail-label"><Calendar size={13} /> 查询时间</span>
                    <span>{formatDate(target_entry.created_at)}</span>
                  </div>
                ) : null}
                <div className="dm-detail-item">
                  <span className="dm-detail-label">文件</span>
                  <code className="dm-path">{target_entry?.file_path || "-"}</code>
                </div>
              </div>
            </div>
          ) : null}

          {/* Lightcurve datasets section */}
          {lc_entries.length > 0 ? (
            <div className="dm-star-section">
              <h4 className="dm-section-title">
                <Activity size={14} />
                光变曲线文件 ({lc_entries.length})
              </h4>
              <div className="dm-lc-table-wrap">
                <table className="dm-lc-table">
                  <thead>
                    <tr>
                      <th>文件名</th>
                      <th>任务</th>
                      <th>数据点</th>
                      <th>时间跨度</th>
                      <th>大小</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lc_entries.map((lc) => {
                      const isFits = lc.type === "lightcurve_file" || lc.metadata?.file_type === "fits";
                      const isCsv = lc.type === "lightcurve_derived" || lc.metadata?.file_type === "csv";
                      const isOldDataset = lc.type === "lightcurve_dataset";
                      const fileName = lc.metadata?.filename || lc.file_path?.split("/").pop() || "-";
                      const obsId = lc.metadata?.obs_id || "";
                      return (
                      <tr key={lc.id}>
                        <td>
                          <div className="dm-file-cell">
                            {isFits ? <File size={14} className="dm-file-icon-fits" /> : null}
                            {isCsv ? <Table2 size={14} className="dm-file-icon-csv" /> : null}
                            {isOldDataset ? <Database size={14} className="dm-file-icon-ds" /> : null}
                            <span className="dm-filename" title={fileName}>{fileName}</span>
                            {obsId ? <span className="dm-obsid">{obsId}</span> : null}
                          </div>
                        </td>
                        <td>
                          <div className="dm-tag-row">
                            {(lc.metadata?.missions || []).map((m) => (
                              <span key={m} className="dm-tag">{m}</span>
                            ))}
                            {!isOldDataset ? (
                              <span className={"dm-tag dm-tag-type" + (isFits ? " dm-tag-fits" : " dm-tag-csv")}>
                                {isFits ? "FITS" : isCsv ? "CSV" : ""}
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td>{lc.metadata?.point_count?.toLocaleString() || "-"}</td>
                        <td>{lc.metadata?.time_span_days != null ? `${lc.metadata.time_span_days} 天` : "-"}</td>
                        <td>{formatSize(lc.size_bytes)}</td>
                        <td>
                          {lc.valid ? (
                            <span className="dm-badge" style={{ background: "var(--success)" }}>正常</span>
                          ) : (
                            <span className="dm-badge dm-badge-warn" title={(lc.metadata?.validation_errors || []).join("; ")}>
                              <AlertCircle size={12} /> 异常
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="dm-star-section">
              <p className="dm-empty-hint">暂未下载光变曲线数据</p>
            </div>
          )}

          {/* No data fallback */}
          {!has_target && lc_entries.length === 0 ? (
            <p className="dm-empty-hint">无关联数据</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
