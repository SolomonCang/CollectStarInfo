const TYPE_LABELS = {
  target_result: "目标查询结果",
  lightcurve_dataset: "光变曲线数据集",
};

function formatSize(bytes) {
  if (bytes == null) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function DataDetail({ entry, onClose }) {
  if (!entry) return null;

  const meta = entry.metadata || {};

  return (
    <div className="dm-detail-panel">
      <div className="dm-detail-header">
        <h3>{entry.display_name}</h3>
        <button type="button" className="ghost-button dm-detail-close" onClick={onClose}>
          ✕
        </button>
      </div>

      <div className="dm-detail-body">
        <div className="dm-detail-row">
          <span className="dm-detail-label">类型</span>
          <span className="dm-tag">{TYPE_LABELS[entry.type] || entry.type}</span>
        </div>
        <div className="dm-detail-row">
          <span className="dm-detail-label">来源</span>
          <span>{entry.source}</span>
        </div>
        <div className="dm-detail-row">
          <span className="dm-detail-label">大小</span>
          <span>{formatSize(entry.size_bytes)}</span>
        </div>
        <div className="dm-detail-row">
          <span className="dm-detail-label">创建时间</span>
          <span>{entry.created_at ? new Date(entry.created_at).toLocaleString() : "-"}</span>
        </div>
        <div className="dm-detail-row">
          <span className="dm-detail-label">路径</span>
          <code className="dm-path">{entry.file_path}</code>
        </div>

        {entry.tags?.length ? (
          <div className="dm-detail-row">
            <span className="dm-detail-label">标签</span>
            <div className="dm-tag-row">
              {entry.tags.map((t) => (
                <span key={t} className="dm-tag">{t}</span>
              ))}
            </div>
          </div>
        ) : null}

        {entry.type === "target_result" ? (
          <>
            {meta.target_type ? (
              <div className="dm-detail-row">
                <span className="dm-detail-label">目标类型</span>
                <span>{meta.target_type}</span>
              </div>
            ) : null}
            {meta.ra_deg != null ? (
              <div className="dm-detail-row">
                <span className="dm-detail-label">赤经/赤纬</span>
                <span>{meta.ra_deg?.toFixed(4)}°, {meta.dec_deg?.toFixed(4)}°</span>
              </div>
            ) : null}
            {meta.reference_count != null ? (
              <div className="dm-detail-row">
                <span className="dm-detail-label">参考文献</span>
                <span>{meta.reference_count} 篇</span>
              </div>
            ) : null}
          </>
        ) : (
          <>
            {!entry.valid ? (
              <div className="dm-detail-row">
                <span className="dm-detail-label">状态</span>
                <span className="dm-badge dm-badge-warn">验证异常</span>
              </div>
            ) : null}
            {meta.point_count ? (
              <div className="dm-detail-row">
                <span className="dm-detail-label">数据点数</span>
                <span>{meta.point_count.toLocaleString()}</span>
              </div>
            ) : null}
            {meta.time_span_days != null ? (
              <div className="dm-detail-row">
                <span className="dm-detail-label">时间跨度</span>
                <span>{meta.time_span_days} 天</span>
              </div>
            ) : null}
            {meta.product_count ? (
              <div className="dm-detail-row">
                <span className="dm-detail-label">FITS 产品数</span>
                <span>{meta.product_count}</span>
              </div>
            ) : null}
            {meta.missions?.length ? (
              <div className="dm-detail-row">
                <span className="dm-detail-label">任务</span>
                <span>{meta.missions.join(" · ")}</span>
              </div>
            ) : null}
            {meta.validation_errors?.length ? (
              <div className="dm-detail-row">
                <span className="dm-detail-label">验证错误</span>
                <ul className="dm-error-list">
                  {meta.validation_errors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
