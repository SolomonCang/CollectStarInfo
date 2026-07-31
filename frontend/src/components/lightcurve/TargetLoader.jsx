import { Search } from "lucide-react";

export default function TargetLoader({ targetName, targetBusy, onNameChange, onSubmit, compact = false }) {
  return (
    <form onSubmit={onSubmit} className={compact ? "lc-target-loader compact" : "panel-section"}>
      <div className="lc-target-label">
        <Search size={17} />
        <span>
          <small>目标</small>
          目标名或坐标
        </span>
      </div>
      <label className="lc-target-input">
        <input value={targetName} onChange={(event) => onNameChange(event.target.value)} />
      </label>
      <button type="submit" disabled={targetBusy}>
        {targetBusy ? "载入中…" : "载入"}
      </button>
    </form>
  );
}
