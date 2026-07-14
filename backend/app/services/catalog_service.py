"""
Unified data catalog service.

Manages a single ``data/catalog.json`` index that registers every persisted
data item across the project — target results (``results/``) and light-curve
datasets (``data/lightcurves/``).  The catalog is the single source of truth
for the Data Manager page and allows cross-source browsing, multi-select
analysis, and batch operations.

TTL-based expiry is *disabled by default* — data lives until the user
explicitly deletes it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import HTTPException

from .lightcurve_cache_service import (
    DATA_ROOT,
    PROJECT_ROOT,
    atomic_write_json,
    iter_dataset_dirs,
    read_json,
    unique_storage_size,
    utc_now,
    validate_dataset_dir,
)

CATALOG_PATH = DATA_ROOT.parent / "catalog.json"
CATALOG_VERSION = 1

RESULTS_DIR = PROJECT_ROOT / "results"


def _normalize_star_name(name: str) -> str:
    """Normalize a star name for grouping (case-insensitive, whitespace-collapsed)."""
    return " ".join((name or "").strip().lower().split())


# ── helpers ──────────────────────────────────────────────────────────


def _scan_target_results() -> Iterator[dict[str, Any]]:
    """Yield one catalog entry for every valid ``results/*.json`` file."""
    if not RESULTS_DIR.exists():
        return
    for path in sorted(RESULTS_DIR.glob("*.json")):
        if path.is_dir():
            continue
        payload = read_json(path)
        if not isinstance(payload, dict) or not isinstance(payload.get("target"), dict):
            continue
        target = payload["target"]
        display_name = target.get("resolved_target") or target.get("query_target") or path.stem
        size = path.stat().st_size
        created_at = payload.get("generated_at") or datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
        tags: list[str] = []
        ttype = target.get("target_type", "")
        if ttype:
            tags.append(ttype.lower().replace(" ", "-"))
        sources = target.get("sources", [])
        if isinstance(sources, list):
            for s in sources:
                if isinstance(s, str):
                    tags.append(s.lower())

        simbad = target.get("simbad", {}) or {}
        yield {
            "id": f"res_{path.stem}",
            "type": "target_result",
            "display_name": display_name,
            "source": ", ".join(sources) if sources else "SIMBAD+Gaia",
            "file_path": str(path.relative_to(PROJECT_ROOT)),
            "size_bytes": size,
            "created_at": created_at,
            "tags": tags,
            "metadata": {
                "target_type": ttype or None,
                "ra_deg": simbad.get("ra_deg"),
                "dec_deg": simbad.get("dec_deg"),
                "reference_count": len(target.get("literature_references", []) or []),
            },
        }


def _scan_lightcurve_datasets() -> Iterator[dict[str, Any]]:
    """Yield one catalog entry per valid light-curve dataset directory."""
    for dataset_dir in sorted(iter_dataset_dirs()):
        ok, errors, manifest = validate_dataset_dir(dataset_dir)
        if manifest is None:
            manifest = {}
        rel_path = str(dataset_dir.relative_to(PROJECT_ROOT))
        size = unique_storage_size(iter([dataset_dir]))
        created_at = manifest.get("generated_at") or datetime.fromtimestamp(
            dataset_dir.stat().st_mtime, tz=timezone.utc
        ).isoformat()
        entries = manifest.get("manifest", [])
        missions: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            m = entry.get("mission") or entry.get("obs_collection")
            if m and m not in seen:
                missions.append(m)
                seen.add(m)

        point_count = 0
        time_span_days: float | None = None
        csv_info = manifest.get("csv", {})
        if isinstance(csv_info, dict):
            point_count = csv_info.get("point_count", 0)
            time_span_days = csv_info.get("time_span_days")

        dataset_id = manifest.get("dataset_key") or Path(rel_path).name
        tags = ["lightcurve"] + [m.lower() for m in missions]
        products_file = dataset_dir / "selected_products.json"
        products = read_json(products_file, [])
        target_name = ""
        if products:
            target_name = products[0].get("target_name", "") if isinstance(products, list) and products else ""

        yield {
            "id": f"lc_{dataset_id[:24]}",
            "type": "lightcurve_dataset",
            "display_name": target_name or manifest.get("target_name") or dataset_dir.parent.name,
            "source": f"MAST/{'/'.join(missions)}" if missions else "MAST",
            "file_path": rel_path,
            "size_bytes": size,
            "created_at": created_at,
            "tags": tags,
            "valid": ok,
            "metadata": {
                "missions": missions,
                "point_count": point_count,
                "time_span_days": time_span_days,
                "product_count": len(entries),
                "validation_errors": errors if not ok else [],
            },
        }


def _rebuild_catalog() -> dict[str, Any]:
    """Full scan of results/ + data/lightcurves/ → catalog.json."""
    entries: list[dict[str, Any]] = []
    entries.extend(_scan_target_results())
    entries.extend(_scan_lightcurve_datasets())
    catalog: dict[str, Any] = {
        "version": CATALOG_VERSION,
        "updated_at": utc_now(),
        "entries": entries,
    }
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(CATALOG_PATH, catalog)
    return catalog


def _load_catalog() -> dict[str, Any]:
    """Return current catalog, rebuilding if missing or stale."""
    if CATALOG_PATH.exists():
        catalog = read_json(CATALOG_PATH, {})
        if isinstance(catalog, dict) and catalog.get("version") == CATALOG_VERSION:
            return catalog
    return _rebuild_catalog()


# ── service ───────────────────────────────────────────────────────────


class CatalogService:
    """Unified data catalog service."""

    def _ensure_fresh(self) -> dict[str, Any]:
        return _load_catalog()

    def stats(self) -> dict[str, Any]:
        catalog = self._ensure_fresh()
        entries = catalog.get("entries", [])
        total_size = sum(e.get("size_bytes", 0) for e in entries)
        by_type: dict[str, int] = {}
        for e in entries:
            t = e.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "total_entries": len(entries),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "by_type": by_type,
            "updated_at": catalog.get("updated_at"),
        }

    def list_entries(
        self,
        *,
        entry_type: str | None = None,
        source: str | None = None,
        search: str | None = None,
        tags: list[str] | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        catalog = self._ensure_fresh()
        entries = catalog.get("entries", [])

        # filters
        if entry_type:
            entries = [e for e in entries if e.get("type") == entry_type]
        if source:
            entries = [e for e in entries if source.lower() in (e.get("source") or "").lower()]
        if tags:
            tag_set = {t.lower() for t in tags}
            entries = [e for e in entries if tag_set & {t.lower() for t in e.get("tags", [])}]
        if search:
            q = search.lower()
            entries = [
                e
                for e in entries
                if q in (e.get("display_name") or "").lower()
                or q in (e.get("source") or "").lower()
                or any(q in t.lower() for t in e.get("tags", []))
            ]

        total = len(entries)
        page = entries[offset : offset + limit]
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "entries": page,
        }

    def get_entry(self, entry_id: str) -> dict[str, Any]:
        catalog = self._ensure_fresh()
        for entry in catalog.get("entries", []):
            if entry.get("id") == entry_id:
                return entry
        raise HTTPException(status_code=404, detail=f"Entry not found: {entry_id}")

    def delete_entry(self, entry_id: str) -> dict[str, Any]:
        catalog = self._ensure_fresh()
        target_entry = None
        for entry in catalog.get("entries", []):
            if entry.get("id") == entry_id:
                target_entry = entry
                break
        if target_entry is None:
            raise HTTPException(status_code=404, detail=f"Entry not found: {entry_id}")

        file_path = Path(target_entry["file_path"])
        abs_path = file_path if file_path.is_absolute() else PROJECT_ROOT / file_path

        removed_bytes = 0
        if abs_path.exists():
            if abs_path.is_dir():
                import shutil

                removed_bytes = unique_storage_size(iter([abs_path]))
                shutil.rmtree(abs_path)
            else:
                removed_bytes = abs_path.stat().st_size
                abs_path.unlink()

        # also remove extrapar / MD files with same stem for target results
        if target_entry.get("type") == "target_result":
            stem = abs_path.stem
            parent = abs_path.parent
            for extra in parent.glob(f"{stem}*"):
                if extra == abs_path:
                    continue
                try:
                    removed_bytes += extra.stat().st_size
                    extra.unlink()
                except (OSError, FileNotFoundError):
                    pass

        # rebuild catalog
        new_catalog = _rebuild_catalog()
        return {
            "deleted_id": entry_id,
            "display_name": target_entry.get("display_name", entry_id),
            "removed_bytes": removed_bytes,
            "catalog_stats": {
                "total_entries": len(new_catalog.get("entries", [])),
            },
        }

    def batch_delete(self, entry_ids: list[str]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        total_removed = 0
        for eid in entry_ids:
            try:
                r = self.delete_entry(eid)
                results.append({"id": eid, "status": "deleted", "removed_bytes": r["removed_bytes"]})
                total_removed += r["removed_bytes"]
            except HTTPException as exc:
                results.append({"id": eid, "status": "error", "detail": exc.detail})
        catalog = self._ensure_fresh()
        return {
            "results": results,
            "total_removed_bytes": total_removed,
            "total_removed_mb": round(total_removed / 1024 / 1024, 2),
            "catalog_stats": {
                "total_entries": len(catalog.get("entries", [])),
            },
        }

    def list_stars(
        self,
        *,
        search: str | None = None,
        source: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return entries grouped by star name."""
        catalog = self._ensure_fresh()
        entries = catalog.get("entries", [])

        # Group by normalized star name
        groups: dict[str, dict[str, Any]] = {}
        order: list[str] = []  # preserve insertion order
        for entry in entries:
            name = entry.get("display_name", "")
            key = _normalize_star_name(name)
            if not key:
                continue
            if key not in groups:
                groups[key] = {
                    "name": name,
                    "normalized": key,
                    "target_entry": None,
                    "lc_entries": [],
                    "total_size_bytes": 0,
                }
                order.append(key)
            group = groups[key]
            group["total_size_bytes"] += entry.get("size_bytes", 0) or 0
            if entry.get("type") == "target_result":
                if group["target_entry"] is None:  # keep first
                    group["target_entry"] = entry
                else:
                    group["total_size_bytes"] += entry.get("size_bytes", 0) or 0
            elif entry.get("type") == "lightcurve_dataset":
                group["lc_entries"].append(entry)

        # Build star list
        stars: list[dict[str, Any]] = []
        for key in order:
            g = groups[key]
            entry_count = (1 if g["target_entry"] else 0) + len(g["lc_entries"])
            stars.append({
                "name": g["name"],
                "normalized": g["normalized"],
                "target_entry": g["target_entry"],
                "lc_entries": g["lc_entries"],
                "total_size_bytes": g["total_size_bytes"],
                "entry_count": entry_count,
                "has_lc": len(g["lc_entries"]) > 0,
                "has_target": g["target_entry"] is not None,
            })

        # filter: search
        if search:
            q = search.lower()
            stars = [
                s for s in stars
                if q in s["name"].lower()
                or (s["target_entry"] and q in (s["target_entry"].get("source") or "").lower())
                or any(
                    q in e.get("source", "").lower()
                    for e in s["lc_entries"]
                )
                or any(
                    q in t.lower()
                    for e in ([s["target_entry"]] if s["target_entry"] else []) + s["lc_entries"]
                    for t in e.get("tags", [])
                )
            ]

        # filter: source
        if source:
            qs = source.lower()
            stars = [
                s for s in stars
                if (s["target_entry"] and qs in (s["target_entry"].get("source") or "").lower())
                or any(qs in e.get("source", "").lower() for e in s["lc_entries"])
            ]

        total = len(stars)
        page = stars[offset : offset + limit]
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "stars": page,
        }

    def delete_star(self, star_name: str) -> dict[str, Any]:
        """Delete all data entries belonging to a star."""
        import shutil

        catalog = self._ensure_fresh()
        key = _normalize_star_name(star_name)
        entries = catalog.get("entries", [])
        to_delete = [
            e for e in entries
            if _normalize_star_name(e.get("display_name", "")) == key
        ]
        if not to_delete:
            raise HTTPException(status_code=404, detail=f"No data found for star: {star_name}")

        total_removed = 0
        display_name = to_delete[0].get("display_name", star_name)
        deleted_ids: list[str] = []
        for entry in to_delete:
            file_path = Path(entry["file_path"])
            abs_path = file_path if file_path.is_absolute() else PROJECT_ROOT / file_path
            if abs_path.exists():
                if abs_path.is_dir():
                    from .lightcurve_cache_service import unique_storage_size

                    total_removed += unique_storage_size(iter([abs_path]))
                    shutil.rmtree(abs_path)
                else:
                    total_removed += abs_path.stat().st_size
                    abs_path.unlink()
            # For target results, also remove related files
            if entry.get("type") == "target_result":
                stem = abs_path.stem
                parent = abs_path.parent
                for extra in parent.glob(f"{stem}*"):
                    if extra == abs_path:
                        continue
                    try:
                        total_removed += extra.stat().st_size
                        extra.unlink()
                    except (OSError, FileNotFoundError):
                        pass
            deleted_ids.append(entry.get("id", ""))

        new_catalog = _rebuild_catalog()
        return {
            "star_name": display_name,
            "deleted_entry_count": len(deleted_ids),
            "deleted_ids": deleted_ids,
            "removed_bytes": total_removed,
            "removed_mb": round(total_removed / 1024 / 1024, 2),
            "catalog_stats": {
                "total_entries": len(new_catalog.get("entries", [])),
            },
        }

    def rebuild(self) -> dict[str, Any]:
        catalog = _rebuild_catalog()
        return {
            "message": "Catalog rebuilt successfully.",
            "total_entries": len(catalog.get("entries", [])),
            "updated_at": catalog.get("updated_at"),
        }
