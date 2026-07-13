import { BarChart3, Orbit } from "lucide-react";

export default function AnalysisSettings({
  // Detrend
  polynomialOrder,
  gapThreshold,
  segmentCount,
  onOrderChange,
  onGapChange,
  // Period search
  minPeriod,
  maxPeriod,
  samplesPerPeak,
  searchDisabled,
  onMinPeriodChange,
  onMaxPeriodChange,
  onSamplesPerPeakChange,
  onRunSearch,
}) {
  return (
    <div className="panel-section">
      <div className="section-title"><BarChart3 size={16} /> 分析设置</div>

      {/* Detrend row */}
      <div className="analysis-settings-row">
        <div className="analysis-settings-group">
          <span className="analysis-settings-label">去趋势</span>
          <label className="compact-label">
            阶数
            <input
              type="number"
              min="0"
              max="5"
              step="1"
              value={polynomialOrder}
              onChange={(event) => onOrderChange(event.target.value)}
            />
          </label>
          <label className="compact-label">
            分段间隔
            <input
              type="number"
              min="0"
              step="0.1"
              value={gapThreshold}
              onChange={(event) => onGapChange(event.target.value)}
              placeholder="1.0"
            />
            <span className="unit-hint">天</span>
          </label>
        </div>
        {segmentCount > 1 && (
          <div className="segment-info">{segmentCount} 段</div>
        )}
      </div>

      {/* Period search row */}
      <div className="analysis-settings-row">
        <span className="analysis-settings-label">
          <Orbit size={14} /> 周期搜索
        </span>
        <div className="analysis-settings-group">
          <label className="compact-label">
            Min
            <input
              type="number"
              min="0"
              step="0.0001"
              value={minPeriod}
              onChange={(event) => onMinPeriodChange(event.target.value)}
              placeholder="auto"
            />
            <span className="unit-hint">天</span>
          </label>
          <label className="compact-label">
            Max
            <input
              type="number"
              min="0"
              step="0.0001"
              value={maxPeriod}
              onChange={(event) => onMaxPeriodChange(event.target.value)}
              placeholder="auto"
            />
            <span className="unit-hint">天</span>
          </label>
          <label className="compact-label">
            SPP
            <input
              type="number"
              min="2"
              max="50"
              value={samplesPerPeak}
              onChange={(event) => onSamplesPerPeakChange(event.target.value)}
            />
          </label>
        </div>
        <button
          type="button"
          className="compact-run-btn"
          onClick={onRunSearch}
          disabled={searchDisabled}
        >
          {searchDisabled ? "搜索中…" : "运行"}
        </button>
      </div>
    </div>
  );
}
