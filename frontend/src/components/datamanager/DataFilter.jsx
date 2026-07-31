export default function DataFilter({
  source,
  search,
  onFilterChange,
  busy,
}) {
  return (
    <div className="dm-filter-bar">
      <select
        aria-label="按数据来源筛选"
        value={source}
        onChange={(e) => onFilterChange({ source: e.target.value })}
        disabled={busy}
      >
        <option value="">全部来源</option>
        <option value="SIMBAD">SIMBAD+Gaia</option>
        <option value="MAST/TESS">MAST/TESS</option>
        <option value="MAST/Kepler">MAST/Kepler</option>
        <option value="MAST/K2">MAST/K2</option>
      </select>

      <input
        aria-label="搜索星名或来源"
        type="text"
        placeholder="搜索星名、来源..."
        value={search}
        onChange={(e) => onFilterChange({ search: e.target.value })}
        disabled={busy}
        style={{ flex: 1 }}
      />
    </div>
  );
}
