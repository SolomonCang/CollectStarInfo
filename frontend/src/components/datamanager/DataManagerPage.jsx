import { useCallback, useEffect, useRef, useState } from "react";
import { Database, HardDrive, RefreshCw, Trash2, Star } from "lucide-react";
import { useDataManagerState } from "../../hooks/useDataManagerState";
import {
  getCatalogStats,
  listStars,
  deleteStar,
  rebuildCatalog,
} from "../../api";
import ErrorBanner from "../shared/ErrorBanner";
import EmptyState from "../shared/EmptyState";
import DataFilter from "./DataFilter";
import StarCard from "./StarCard";

export default function DataManagerPage({ isAdmin = false }) {
  const dm = useDataManagerState();
  const [deletingStar, setDeletingStar] = useState(null);
  const listControllerRef = useRef(null);

  // ── Load ──
  const loadStars = useCallback(async () => {
    listControllerRef.current?.abort();
    const controller = new AbortController();
    listControllerRef.current = controller;
    dm.dispatch({ type: "SET_BUSY" });
    try {
      const [result, stats] = await Promise.all([
        listStars({
          search: dm.search || null,
          source: dm.source || null,
          offset: dm.offset,
          limit: dm.limit,
        }, { signal: controller.signal }),
        getCatalogStats({ signal: controller.signal }),
      ]);
      dm.dispatch({ type: "SET_STARS", payload: result });
      dm.dispatch({ type: "SET_STATS", payload: stats });
    } catch (e) {
      if (e.name === "AbortError") return;
      dm.dispatch({ type: "SET_ERROR", payload: e.message });
    } finally {
      if (listControllerRef.current === controller) {
        listControllerRef.current = null;
      }
    }
  }, [dm.search, dm.source, dm.offset, dm.limit, dm.dispatch]);

  // Use one cancellable loading path so fast filter changes cannot apply stale data.
  useEffect(() => {
    const timer = setTimeout(loadStars, dm.search ? 300 : 0);
    return () => {
      clearTimeout(timer);
      listControllerRef.current?.abort();
    };
  }, [dm.search, loadStars]);

  // ── Actions ──
  const handleBatchDelete = useCallback(async () => {
    if (!dm.selectedStars.length) return;
    if (!window.confirm(`确认删除 ${dm.selectedStars.length} 个星的全部数据？此操作不可撤销。`)) return;
    dm.dispatch({ type: "SET_BUSY" });
    try {
      let totalRemovedMb = 0;
      for (const starName of dm.selectedStars) {
        setDeletingStar(starName);
        const result = await deleteStar(starName);
        totalRemovedMb += result.removed_mb || 0;
      }
      await loadStars();
      dm.dispatch({
        type: "SET_MESSAGE",
        payload: `已删除，释放 ${totalRemovedMb.toFixed(2)} MB。`,
      });
    } catch (e) {
      dm.dispatch({ type: "SET_ERROR", payload: e.message });
    } finally {
      setDeletingStar(null);
    }
  }, [dm.selectedStars, dm.dispatch, loadStars]);

  const handleDeleteSingle = useCallback(async (starName) => {
    dm.dispatch({ type: "SET_BUSY" });
    setDeletingStar(starName);
    try {
      const result = await deleteStar(starName);
      await loadStars();
      dm.dispatch({
        type: "SET_MESSAGE",
        payload: `已删除「${starName}」，释放 ${result.removed_mb} MB。`,
      });
    } catch (e) {
      dm.dispatch({ type: "SET_ERROR", payload: e.message });
    } finally {
      setDeletingStar(null);
    }
  }, [dm.dispatch, loadStars]);

  const handleRebuild = useCallback(async () => {
    dm.dispatch({ type: "SET_BUSY" });
    try {
      const result = await rebuildCatalog();
      await loadStars();
      dm.dispatch({
        type: "SET_MESSAGE",
        payload: `目录已重建：${result.total_entries} 个条目。`,
      });
    } catch (e) {
      dm.dispatch({ type: "SET_ERROR", payload: e.message });
    }
  }, [dm.dispatch, loadStars]);

  // ── Pagination ──
  const totalPages = Math.max(1, Math.ceil(dm.total / dm.limit));
  const currentPage = Math.floor(dm.offset / dm.limit) + 1;

  return (
    <section className="dm-workspace">
      <ErrorBanner message={dm.error} />

      {/* ── Stats bar ── */}
      {dm.stats ? (
        <div className="dm-stats-bar">
          <div className="dm-stat-card">
            <Database size={16} />
            <span>{dm.stats.total_entries} 条目</span>
          </div>
          <div className="dm-stat-card">
            <Star size={16} />
            <span>{dm.total} 颗星</span>
          </div>
          <div className="dm-stat-card">
            <HardDrive size={16} />
            <span>{dm.stats.total_size_mb} MB</span>
          </div>
        </div>
      ) : null}

      {/* ── Toolbar ── */}
      <div className="dm-toolbar">
        <DataFilter
          source={dm.source}
          search={dm.search}
          onFilterChange={dm.setFilter}
          busy={dm.busy}
        />
        <div className="dm-toolbar-actions">
          {isAdmin && dm.selectedStars.length > 0 ? (
            <button
              type="button"
              className="danger-button"
              onClick={handleBatchDelete}
              disabled={dm.busy}
            >
              <Trash2 size={16} />
              删除选中 ({dm.selectedStars.length})
            </button>
          ) : null}
          {isAdmin ? <button
            type="button"
            className="ghost-button"
            onClick={handleRebuild}
            disabled={dm.busy}
          >
            <RefreshCw size={16} />
            重建索引
          </button> : null}
        </div>
      </div>

      {dm.message ? <div className="dm-message" role="status">{dm.message}</div> : null}

      {/* ── Star list ── */}
      <div className="dm-star-list">
        {dm.stars.length > 0 ? (
          dm.stars.map((star) => (
            <StarCard
              key={star.normalized}
              star={star}
              expanded={dm.expandedStar === star.normalized}
              selected={dm.selectedStars.includes(star.normalized)}
              onToggleExpand={dm.toggleExpand}
              onToggleSelect={dm.toggleSelect}
              onDelete={handleDeleteSingle}
              busy={dm.busy && deletingStar === star.normalized}
              canManage={isAdmin}
            />
          ))
        ) : dm.busy ? null : (
          <EmptyState
            icon={<Database size={48} />}
            title="无匹配结果"
            description="尝试调整筛选条件或重建索引。"
          />
        )}
      </div>

      {/* ── Pagination ── */}
      {dm.total > dm.limit ? (
        <div className="dm-pagination">
          <button
            type="button"
            className="ghost-button"
            disabled={dm.offset === 0 || dm.busy}
            onClick={() => dm.setOffset(Math.max(0, dm.offset - dm.limit))}
          >
            上一页
          </button>
          <span>{currentPage} / {totalPages}</span>
          <button
            type="button"
            className="ghost-button"
            disabled={dm.offset + dm.limit >= dm.total || dm.busy}
            onClick={() => dm.setOffset(dm.offset + dm.limit)}
          >
            下一页
          </button>
          <select
            aria-label="每页显示数量"
            value={dm.limit}
            onChange={(e) => dm.setLimit(Number(e.target.value))}
            disabled={dm.busy}
            style={{ width: "auto", marginLeft: 12 }}
          >
            <option value={25}>25/页</option>
            <option value={50}>50/页</option>
            <option value={100}>100/页</option>
          </select>
        </div>
      ) : null}
    </section>
  );
}
