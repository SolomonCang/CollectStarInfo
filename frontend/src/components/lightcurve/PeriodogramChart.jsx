import { useCallback, useMemo, useState } from "react";
import Plot from "react-plotly.js";
import { Activity, RotateCcw } from "lucide-react";
import Skeleton from "../shared/Skeleton";
import EmptyState from "../shared/EmptyState";

const MODEBAR_REMOVE = [
  "lasso2d",
  "select2d",
  "sendDataToCloud",
  "autoScale2d",
  "toggleSpikelines",
  "hoverClosestCartesian",
  "hoverCompareCartesian",
];

function periodSearchStatus(analysis, datasetBusy) {
  if (datasetBusy) return "周期搜索运行中...";
  const count = analysis?.period_search?.periodogram?.length ?? 0;
  if (count) return `LS 频谱已生成：${count} 个采样点，最佳周期 ${analysis?.period_search?.best_period?.toPrecision?.(7) ?? "-"}`;
  if (analysis && !analysis.period_search) return "分析完成，但没有可用周期结果；请检查时间跨度、点数或周期范围。";
  return "运行周期搜索后显示功率谱；点击曲线可把周期送入相位折叠。";
}

export default function PeriodogramChart({
  analysis,
  periodogram,
  datasetBusy,
  onClick,
}) {
  const [plotKey, setPlotKey] = useState(0);

  const handleClick = useCallback((event) => {
    if (!onClick) return;
    const pt = event?.points?.[0];
    if (!pt) return;
    const period = Number.isFinite(pt.customdata) ? pt.customdata : pt.x ? 1 / pt.x : null;
    if (!Number.isFinite(period)) return;
    onClick({ activePayload: [{ payload: { period } }] });
  }, [onClick]);

  const resetZoom = useCallback(() => {
    setPlotKey((k) => k + 1);
  }, []);

  const rawPeriodogram = analysis?.period_search?.periodogram ?? [];

  const { trace, shapes } = useMemo(() => {
    if (!periodogram.length) return { trace: null, shapes: [] };

    const N = periodogram.length;
    const freqs = new Array(N);
    const powers = new Array(N);
    const periods = new Array(N);
    for (let i = 0; i < N; i++) {
      const p = periodogram[i];
      freqs[i] = p.frequency;
      powers[i] = p.power;
      periods[i] = p.period;
    }

    const trace = {
      x: freqs,
      y: powers,
      customdata: periods,
      type: "scattergl",
      mode: "lines",
      line: { color: "#b45309", width: 1.8 },
      hovertemplate:
        "<b>Frequency:</b> %{x:.7f}<br><b>Period:</b> %{customdata:.7f} d<br><b>Power:</b> %{y:.7f}<br><i>点击曲线可送入相位折叠</i><extra></extra>",
      hoverlabel: {
        bgcolor: "rgba(255,255,255,0.96)",
        bordercolor: "#bccac3",
        font: { size: 13, color: "#14231f" },
      },
    };

    const shapes = [];

    // 4σ threshold line
    const threshold = analysis?.period_search?.noise_stats?.threshold_4sigma;
    if (threshold != null) {
      shapes.push({
        type: "line",
        x0: 0,
        x1: 1,
        xref: "paper",
        y0: threshold,
        y1: threshold,
        line: { color: "#6b7280", width: 1, dash: "dash" },
      });
    }

    // Best frequency vertical line
    const bestFreq = analysis?.period_search?.best_frequency;
    if (bestFreq != null) {
      shapes.push({
        type: "line",
        x0: bestFreq,
        x1: bestFreq,
        y0: 0,
        y1: 1,
        yref: "paper",
        line: { color: "#0f766e", width: 1.5, dash: "dot" },
      });
    }

    return { trace, shapes };
  }, [periodogram, analysis?.period_search?.noise_stats?.threshold_4sigma, analysis?.period_search?.best_frequency]);

  const layout = useMemo(() => {
    const annotations = [];

    // 4σ annotation
    const threshold = analysis?.period_search?.noise_stats?.threshold_4sigma;
    if (threshold != null) {
      annotations.push({
        x: 1,
        y: threshold,
        xref: "paper",
        yref: "y",
        text: "4σ",
        showarrow: false,
        xanchor: "right",
        font: { size: 12, color: "#6b7280" },
      });
    }

    // Best frequency annotation
    const bestFreq = analysis?.period_search?.best_frequency;
    if (bestFreq != null) {
      annotations.push({
        x: bestFreq,
        y: 1,
        xref: "x",
        yref: "paper",
        text: "最佳",
        showarrow: false,
        yanchor: "top",
        font: { size: 11, color: "#0f766e" },
      });
    }

    return {
      xaxis: {
        title: { text: "Frequency (1/d)", standoff: 4 },
        showgrid: true,
        gridcolor: "#e5e7eb",
        zeroline: false,
        tickformat: ".4s",
        hoverformat: ".7f",
      },
      yaxis: {
        title: { text: "Power", standoff: 4 },
        showgrid: true,
        gridcolor: "#e5e7eb",
        zeroline: false,
        hoverformat: ".7f",
      },
      margin: { t: 8, r: 50, b: 44, l: 52 },
      shapes,
      annotations,
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      hovermode: "closest",
      dragmode: "pan",
    };
  }, [shapes, analysis?.period_search?.noise_stats?.threshold_4sigma, analysis?.period_search?.best_frequency]);

  const config = {
    displayModeBar: true,
    modeBarButtonsToRemove: MODEBAR_REMOVE,
    displaylogo: false,
    responsive: true,
    scrollZoom: true,
  };

  return (
    <div className="panel-card chart-card">
      <div className="section-title">
        <Activity size={18} /> Lomb-Scargle 频谱
        <button type="button" className="ghost-button zoom-reset-btn" onClick={resetZoom}>
          <RotateCcw size={14} /> 重置
        </button>
      </div>
      <div className="chart-note">{periodSearchStatus(analysis, datasetBusy)}</div>
      {datasetBusy ? (
        <Skeleton height="320px" lines={3} />
      ) : rawPeriodogram.length ? (
        <div className="chart-frame">
          <Plot
            key={plotKey}
            data={trace ? [trace] : []}
            layout={layout}
            config={config}
            style={{ width: "100%", height: "100%" }}
            useResizeHandler
            onClick={handleClick}
          />
        </div>
      ) : (
        <EmptyState>{periodSearchStatus(analysis, datasetBusy)}</EmptyState>
      )}
    </div>
  );
}
