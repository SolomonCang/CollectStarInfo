import { Orbit } from "lucide-react";

export default function PeriodSearchControls({
  minPeriod,
  maxPeriod,
  samplesPerPeak,
  disabled,
  onMinPeriodChange,
  onMaxPeriodChange,
  onSamplesPerPeakChange,
  onRunSearch,
}) {
  return (
    <div className="panel-section">
      <div className="section-title"><Orbit size={18} /> 周期搜索</div>
      <div className="input-row">
        <label>
          Min period
          <input
            type="number"
            min="0"
            step="0.0001"
            value={minPeriod}
            onChange={(event) => onMinPeriodChange(event.target.value)}
            placeholder="auto"
          />
        </label>
        <label>
          Max period
          <input
            type="number"
            min="0"
            step="0.0001"
            value={maxPeriod}
            onChange={(event) => onMaxPeriodChange(event.target.value)}
            placeholder="auto"
          />
        </label>
      </div>
      <label>
        Samples per peak
        <input
          type="number"
          min="2"
          max="50"
          value={samplesPerPeak}
          onChange={(event) => onSamplesPerPeakChange(event.target.value)}
        />
      </label>
      <button type="button" onClick={onRunSearch} disabled={disabled}>
        {disabled ? "搜索中..." : "运行周期搜索"}
      </button>
    </div>
  );
}
