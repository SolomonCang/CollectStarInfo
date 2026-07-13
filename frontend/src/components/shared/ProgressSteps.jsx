/**
 * Displays a multi-step progress indicator for long-running operations.
 *
 * Props:
 *  - steps: Array<{ label: string, status: "pending" | "active" | "done" | "error" }>
 */
const statusIcons = {
  pending: "○",
  active: "◉",
  done: "✓",
  error: "✗",
};

export default function ProgressSteps({ steps }) {
  if (!steps?.length) return null;

  return (
    <div className="progress-steps">
      {steps.map((step, i) => (
        <div key={i} className={`progress-step progress-step--${step.status}`}>
          <span className="progress-icon">{statusIcons[step.status] || "○"}</span>
          <span className="progress-label">{step.label}</span>
          {step.status === "active" && <span className="progress-spinner" />}
        </div>
      ))}
    </div>
  );
}
