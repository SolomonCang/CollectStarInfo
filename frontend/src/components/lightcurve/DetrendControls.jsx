import { BarChart3 } from "lucide-react";

export default function DetrendControls({
  polynomialOrder,
  gapThreshold,
  segmentCount,
  onOrderChange,
  onGapChange,
}) {
  return (
    <div className="panel-section">
      <div className="section-title"><BarChart3 size={18} /> 去趋势</div>
      <div className="input-row">
        <label>
          多项式阶数
          <input
            type="number"
            min="0"
            max="5"
            step="1"
            value={polynomialOrder}
            onChange={(event) => onOrderChange(event.target.value)}
          />
        </label>
        <label>
          分段间隔 (天)
          <input
            type="number"
            min="0"
            step="0.1"
            value={gapThreshold}
            onChange={(event) => onGapChange(event.target.value)}
            placeholder="1.0"
          />
        </label>
      </div>
      <div className="hint-text">
        间隔阈值: 时间间隔超过此天数的数据将分段独立去趋势。设为 0 禁用分段。
      </div>
      {segmentCount > 1 && (
        <div className="segment-info">
          已检测到 {segmentCount} 个数据分段，各段独立去趋势。
        </div>
      )}
    </div>
  );
}
