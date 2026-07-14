const TYPE_LABELS = {
  target_result: "目标查询",
  lightcurve_dataset: "光变数据",
};

function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString();
}

export default function DataList({
  entries,
  selectedIds,
  onToggleSelect,
  onSelectAll,
  onViewDetail,
  busy,
}) {
  const allSelected = entries.length > 0 && selectedIds.length === entries.length;

  return (
    <div className="dm-data-list">
      <div className="dm-list-header">
        <label className="checkbox-row dm-select-all">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={onSelectAll}
            disabled={busy}
          />
          <span>{selectedIds.length ? `已选 ${selectedIds.length}` : "全选"}</span>
        </label>
      </div>

      <div className="dm-list-body">
        {entries.map((entry) => {
          const isSelected = selectedIds.includes(entry.id);
          return (
            <div
              key={entry.id}
              className={`dm-list-item ${isSelected ? "selected" : ""}`}
              onClick={() => onViewDetail(entry)}
            >
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => onToggleSelect(entry.id)}
                onClick={(e) => e.stopPropagation()}
                disabled={busy}
              />
              <div className="dm-item-body">
                <div className="dm-item-name">
                  {entry.type === "lightcurve_dataset" && !entry.valid && (
                    <span className="dm-badge dm-badge-warn" title="验证异常">⚠</span>
                  )}
                  {entry.display_name}
                </div>
                <div className="dm-item-meta">
                  <span className="dm-tag">{TYPE_LABELS[entry.type] || entry.type}</span>
                  <span className="dm-tag">{entry.source}</span>
                  {entry.metadata?.missions?.length ? (
                    <span className="dm-tag">{entry.metadata.missions.join(" · ")}</span>
                  ) : null}
                </div>
              </div>
              <div className="dm-item-stats">
                <span className="dm-stat">{formatSize(entry.size_bytes)}</span>
                <span className="dm-stat dm-stat-date">{formatDate(entry.created_at)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
