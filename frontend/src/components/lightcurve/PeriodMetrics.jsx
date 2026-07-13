import { Orbit } from "lucide-react";
import Metric from "../shared/Metric";

export default function PeriodMetrics({ analysis, selectedPhasePeriod, phasePeriodMode, phasePeriod }) {
  return (
    <div className="panel-card">
      <div className="section-title"><Orbit size={18} /> 周期指标</div>
      <Metric label="Best period (d)" value={analysis?.period_search?.best_period?.toPrecision?.(7)} />
      <Metric
        label="Period (hours)"
        value={analysis?.period_search?.best_period ? (analysis.period_search.best_period * 24).toPrecision(6) : "-"}
      />
      <Metric
        label="Period (minutes)"
        value={analysis?.period_search?.best_period ? (analysis.period_search.best_period * 1440).toFixed(2) : "-"}
      />
      <Metric label="Power" value={analysis?.period_search?.power?.toFixed?.(4)} />
      {analysis?.period_search?.noise_stats && (
        <>
          <Metric label="4σ threshold" value={analysis.period_search.noise_stats.threshold_4sigma?.toFixed?.(4)} />
          <Metric label="Noise σ" value={analysis.period_search.noise_stats.sigma?.toFixed?.(4)} />
        </>
      )}
      <Metric
        label="Phase period (d)"
        value={
          phasePeriodMode === "manual" && Number.isFinite(Number(phasePeriod)) && Number(phasePeriod) > 0
            ? Number(phasePeriod).toPrecision(7)
            : analysis?.period_search?.best_period?.toPrecision?.(7)
        }
      />
      {selectedPhasePeriod && Number.isFinite(selectedPhasePeriod) && (
        <>
          <Metric
            label="Folded period (h)"
            value={(selectedPhasePeriod * 24).toPrecision(6)}
          />
          <Metric
            label="Folded period (min)"
            value={(selectedPhasePeriod * 1440).toFixed(2)}
          />
        </>
      )}
    </div>
  );
}
