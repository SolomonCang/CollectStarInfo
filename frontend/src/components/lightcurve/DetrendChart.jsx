import Plot from "react-plotly.js";
import { BarChart3 } from "lucide-react";
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

export default function DetrendChart({ curve, loading }) {
  if (loading) {
    return (
      <div className="panel-card chart-card">
        <div className="section-title"><BarChart3 size={18} /> 去趋势曲线（归一到中值）</div>
        <Skeleton height="320px" lines={3} />
      </div>
    );
  }

  if (!curve.length) {
    return (
      <div className="panel-card chart-card">
        <div className="section-title"><BarChart3 size={18} /> 去趋势曲线（归一到中值）</div>
        <EmptyState>选择已下载数据集或上传 time/flux 表后可分析。</EmptyState>
      </div>
    );
  }

  const N = curve.length;
  const times = new Array(N);
  const fluxes = new Array(N);
  const segTexts = new Array(N);
  for (let i = 0; i < N; i++) {
    const p = curve[i];
    times[i] = p.time;
    fluxes[i] = p.normalized_flux;
    segTexts[i] = `Seg ${p.segment ?? "-"}`;
  }

  const trace = {
    x: times,
    y: fluxes,
    type: "scattergl",
    mode: "lines",
    line: { color: "#0f766e", width: 1.5 },
    text: segTexts,
    hovertemplate:
      "<b>Time:</b> %{x:.8f}<br><b>Flux:</b> %{y:.6f}<br><b>Segment:</b> %{text}<extra></extra>",
    hoverlabel: {
      bgcolor: "rgba(255,255,255,0.96)",
      bordercolor: "#bccac3",
      font: { size: 13, color: "#14231f" },
    },
  };

  const xMin = times[0];
  const xMax = times[N - 1];

  const layout = {
    xaxis: {
      showgrid: true,
      gridcolor: "#e5e7eb",
      zeroline: false,
      tickformat: ".6s",
      hoverformat: ".8f",
    },
    yaxis: {
      title: { text: "Flux / Median", standoff: 4 },
      showgrid: true,
      gridcolor: "#e5e7eb",
      zeroline: false,
      tickformat: ".3f",
      hoverformat: ".6f",
    },
    margin: { t: 8, r: 50, b: 40, l: 52 },
    shapes: [
      {
        type: "line",
        x0: xMin,
        x1: xMax,
        y0: 1,
        y1: 1,
        line: { color: "#9ca3af", width: 1, dash: "dot" },
      },
    ],
    annotations: [
      {
        x: 1,
        y: 1,
        xref: "paper",
        yref: "y",
        text: "1.0 (median)",
        showarrow: false,
        xanchor: "right",
        font: { size: 11, color: "#9ca3af" },
      },
    ],
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    hovermode: "closest",
    dragmode: "pan",
  };

  const config = {
    displayModeBar: true,
    modeBarButtonsToRemove: MODEBAR_REMOVE,
    modeBarButtonsToAdd: ["drawrect", "eraseshape"],
    displaylogo: false,
    responsive: true,
    scrollZoom: true,
  };

  return (
    <div className="panel-card chart-card">
      <div className="section-title"><BarChart3 size={18} /> 去趋势曲线（归一到中值）</div>
      <div className="chart-frame">
        <Plot
          data={[trace]}
          layout={layout}
          config={config}
          style={{ width: "100%", height: "100%" }}
          useResizeHandler
        />
      </div>
    </div>
  );
}
