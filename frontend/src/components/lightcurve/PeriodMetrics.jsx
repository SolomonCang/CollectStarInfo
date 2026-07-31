import { Orbit } from "lucide-react";
import Metric from "../shared/Metric";

export default function PeriodMetrics({ analysis, selectedPhasePeriod, phasePeriodMode, phasePeriod }) {
  const bestPeriod = analysis?.period_search?.best_period;
  const displayPhasePeriod =
    phasePeriodMode === "manual" && Number.isFinite(Number(phasePeriod)) && Number(phasePeriod) > 0
      ? Number(phasePeriod)
      : bestPeriod;

  return (
    <div className="panel-card period-metrics-card">
      <div className="period-metrics-heading">
        <div className="section-title"><Orbit size={18} /> 周期结果</div>
        <span>频谱与相位折叠的关键读数</span>
      </div>
      <div className="period-metrics-grid">
        <div className="metric period-primary-metric">
          <span>Best period</span>
          <strong>{bestPeriod?.toPrecision?.(7) ?? "-"}</strong>
          {bestPeriod ? (
            <small>{(bestPeriod * 24).toPrecision(6)} h · {(bestPeriod * 1440).toFixed(2)} min</small>
          ) : null}
        </div>
        <Metric label="Power" value={analysis?.period_search?.power?.toFixed?.(4)} />
        <Metric
          label="FAP"
          value={analysis?.period_search?.false_alarm_probability?.toExponential?.(2)}
        />
        {analysis?.period_search?.noise_stats && (
          <>
            <Metric label="4σ threshold" value={analysis.period_search.noise_stats.threshold_4sigma?.toFixed?.(4)} />
            <Metric label="Noise σ" value={analysis.period_search.noise_stats.sigma?.toFixed?.(4)} />
          </>
        )}
        <div className="metric">
          <span>Phase period</span>
          <strong>{displayPhasePeriod?.toPrecision?.(7) ?? "-"}</strong>
          {selectedPhasePeriod && Number.isFinite(selectedPhasePeriod) ? (
            <small>{(selectedPhasePeriod * 24).toPrecision(6)} h</small>
          ) : null}
        </div>
      </div>
    </div>
  );
}
