/**
 * Skeleton placeholder for charts and cards during loading.
 *
 * Props:
 *  - height: CSS height value (default "280px")
 *  - lines: number of skeleton text lines inside (default 0, card only)
 *  - variant: "chart" | "card" | "text"
 */
export default function Skeleton({ height = "280px", lines = 0, variant = "chart" }) {
  if (variant === "text") {
    return (
      <div className="skeleton-text" style={{ height }}>
        {Array.from({ length: lines || 1 }, (_, i) => (
          <div key={i} className="skeleton-line" style={{ width: `${90 - i * 15}%` }} />
        ))}
      </div>
    );
  }

  return (
    <div className="skeleton-card" style={{ height }}>
      <div className="skeleton-shimmer" />
      {lines > 0 && (
        <div className="skeleton-text" style={{ padding: "1rem" }}>
          {Array.from({ length: lines }, (_, i) => (
            <div key={i} className="skeleton-line" style={{ width: `${85 - i * 12}%` }} />
          ))}
        </div>
      )}
    </div>
  );
}
