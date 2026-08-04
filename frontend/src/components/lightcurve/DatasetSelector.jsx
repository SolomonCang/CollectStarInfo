import EmptyState from "../shared/EmptyState";

export default function DatasetSelector({
  datasets,
  selectedDir,
  onSelect,
  onAnalyze,
  onFile,
  datasetBusy,
  cacheBusy,
  onDelete,
}) {
  return (
    <div className="dataset-section">
      <div className="dataset-section-header">
        <span>已下载数据集</span>
        {datasets.length ? <strong>{datasets.length}</strong> : null}
      </div>
      {datasets.length ? (
        <div className="dataset-cards">
          {datasets.map((dataset) => {
            const isSelected = dataset.download_dir === selectedDir;
            const generatedAt = dataset.generated_at ? new Date(dataset.generated_at).toLocaleString() : "unknown";
            return (
              <button
                type="button"
                key={dataset.download_dir}
                className={`dataset-card ${isSelected ? "selected" : ""}`}
                onClick={() => {
                  onSelect(dataset.download_dir);
                  onAnalyze(dataset.download_dir);
                }}
              >
                <div className="dataset-card-top">
                  <span className="dataset-time">{generatedAt}</span>
                  <span className="dataset-points">
                    {dataset.csv_point_count ?? dataset.manifest_entries ?? 0} pts
                  </span>
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
        <EmptyState compact>载入目标后此处显示已下载数据集。</EmptyState>
      )}
      <button
        type="button"
        onClick={() => onAnalyze(selectedDir)}
        disabled={!selectedDir || datasetBusy}
      >
        {datasetBusy ? "分析中..." : "分析选中下载数据"}
      </button>
      {onDelete ? <button
        type="button"
        className="danger-button"
        onClick={() => onDelete(selectedDir)}
        disabled={!selectedDir || datasetBusy || cacheBusy}
      >
        删除选中数据集
      </button> : null}
      <label>
        CSV / whitespace: time flux [err]
        <input type="file" accept=".csv,.txt" onChange={onFile} />
      </label>
      <button
        type="button"
        onClick={onAnalyze}
        disabled={datasetBusy}
      >
        {datasetBusy ? "分析中..." : "分析上传数据"}
      </button>
    </div>
  );
}
