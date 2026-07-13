import {
  CartesianGrid,
  ErrorBar,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity } from "lucide-react";
import Skeleton from "../shared/Skeleton";
import EmptyState from "../shared/EmptyState";

export default function PhaseFoldedChart({ phaseCurve, phaseBinned, period, loading }) {
  const hasBinned = phaseBinned.length > 0;

  // Build error bar data from binned
  const binnedWithErrors = phaseBinned.map((bin) => ({
    ...bin,
    errorY: bin.std || 0,
    errorY0: 0,
  }));

  return (
    <div className="panel-card phase-card">
      <div className="section-title"><Activity size={18} /> 相位折叠 (2 Cycles)</div>
      {loading ? (
        <Skeleton height="320px" lines={3} />
      ) : phaseCurve.length ? (
        <ResponsiveContainer width="100%" height={320}>
          <ScatterChart margin={{ top: 10, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="phase" type="number" domain={[0, 2]} tickCount={5} />
            <YAxis dataKey="flux" domain={["auto", "auto"]} />
            <Tooltip
              labelFormatter={(label) => `Phase: ${Number(label).toFixed(4)}`}
              formatter={(value, name) => [Number(value).toPrecision(6), name]}
            />
            {/* Phase reference lines */}
            <ReferenceLine x={0.5} stroke="#9ca3af" strokeDasharray="3 3" strokeOpacity={0.4} />
            <ReferenceLine x={1.0} stroke="#9ca3af" strokeDasharray="3 3" strokeOpacity={0.4} />
            <ReferenceLine x={1.5} stroke="#9ca3af" strokeDasharray="3 3" strokeOpacity={0.4} />
            {/* Raw scatter */}
            <Scatter data={phaseCurve} fill="#9ca3af" fillOpacity={0.3} name="Raw" />
            {/* Binned overlay with error bars */}
            {hasBinned && (
              <>
                <Scatter
                  data={phaseBinned}
                  fill="#ef4444"
                  stroke="#ef4444"
                  strokeWidth={0}
                  fillOpacity={1}
                  name="Binned (20 bins)"
                  shape="circle"
                  legendType="circle"
                >
                  {binnedWithErrors.some((d) => d.std > 0) && (
                    <ErrorBar dataKey="errorY" direction="y" stroke="#ef4444" strokeWidth={1.5} width={4} />
                  )}
                </Scatter>
                {/* Connect binned points with a line for visual cue */}
                <Line
                  data={phaseBinned}
                  dataKey="flux"
                  stroke="#ef4444"
                  strokeWidth={2.5}
                  dot={false}
                  isAnimationActive={false}
                  connectNulls
                />
              </>
            )}
          </ScatterChart>
        </ResponsiveContainer>
      ) : (
        <EmptyState>运行周期搜索，或输入一个周期后合并相位。</EmptyState>
      )}
      {period && Number.isFinite(period) && (
        <div className="chart-note">折叠周期: {Number(period).toPrecision(8)} 天</div>
      )}
    </div>
  );
}
