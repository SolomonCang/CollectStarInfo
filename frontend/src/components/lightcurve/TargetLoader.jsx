import { Search } from "lucide-react";

export default function TargetLoader({ targetName, targetBusy, onNameChange, onSubmit }) {
  return (
    <form onSubmit={onSubmit} className="panel-section">
      <div className="section-title"><Search size={18} /> 光变目标</div>
      <label>
        目标名或坐标
        <input value={targetName} onChange={(event) => onNameChange(event.target.value)} />
      </label>
      <button type="submit" disabled={targetBusy}>
        {targetBusy ? "载入中..." : "载入目标与数据集"}
      </button>
    </form>
  );
}
