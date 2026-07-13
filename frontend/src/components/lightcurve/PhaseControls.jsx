import { Activity } from "lucide-react";

export default function PhaseControls({
  phasePeriodMode,
  phasePeriod,
  bestPeriod,
  periodOptions,
  onModeChange,
  onPeriodChange,
  onPeriodSelect,
}) {
  return (
    <div className="panel-section">
      <div className="section-title"><Activity size={18} /> 相位周期</div>
      <label>
        周期来源
        <select value={phasePeriodMode} onChange={(event) => onModeChange(event.target.value)}>
          <option value="best">最佳周期</option>
          <option value="manual">手动输入</option>
        </select>
      </label>
      <label>
        合并相位周期 (天)
        <input
          type="number"
          min="0"
          step="0.000001"
          value={phasePeriod}
          onChange={(event) => onPeriodChange(event.target.value)}
          placeholder={bestPeriod?.toPrecision?.(8) ?? "period"}
        />
      </label>
      {periodOptions.length > 0 && (
        <div className="period-choice-list">
          {periodOptions.map((period) => (
            <button
              type="button"
              className="ghost-button"
              key={period}
              onClick={() => onPeriodSelect(period)}
            >
              {period.toPrecision(7)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
