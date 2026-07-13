import { Download } from "lucide-react";

export default function ArchivePanel({
  archiveProducts,
  selectedProducts,
  archiveBusy,
  downloadResult,
  forceDownload,
  selectedDataset,
  hasTarget,
  onSearch,
  onDownload,
  onToggleProduct,
  onForceDownloadChange,
}) {
  const checkedSet = new Set(selectedProducts);
  const displayProducts = archiveProducts.slice(0, 12);

  return (
    <div className="panel-section">
      <div className="section-title"><Download size={18} /> 数据来源</div>
      <button type="button" onClick={onSearch} disabled={!hasTarget || archiveBusy}>
        {archiveBusy ? "处理中..." : "检索 MAST 光变曲线"}
      </button>
      <div className="download-actions">
        <button
          type="button"
          onClick={onDownload}
          disabled={!archiveProducts.length || !selectedProducts.length || archiveBusy}
        >
          下载选中产品
        </button>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={forceDownload}
            onChange={(event) => onForceDownloadChange(event.target.checked)}
          />
          强制重新下载
        </label>
      </div>

      <div className="archive-list compact-list">
        {displayProducts.length ? (
          displayProducts.map((product) => (
            <label className="product-row" key={product.product_uri || product.filename}>
              <input
                type="checkbox"
                checked={checkedSet.has(product.product_uri)}
                onChange={() => onToggleProduct(product.product_uri)}
                disabled={!product.product_uri}
              />
              <span>
                <strong>{product.mission || "MAST"}</strong>
                <em>{product.subgroup || "LC"}</em>
                {product.filename || product.obs_id}
              </span>
            </label>
          ))
        ) : (
          <div className="muted-text">载入目标后可检索 TESS、Kepler、K2 的 MAST 光变曲线 FITS 产品。</div>
        )}
      </div>

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
  );
}
