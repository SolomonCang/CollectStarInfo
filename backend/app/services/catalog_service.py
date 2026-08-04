"""Database-backed shared scientific data catalog.

SQLite/PostgreSQL workspace tables are authoritative.  A read-only
``warehouse/manifests/catalog.json`` export is refreshed for legacy readers;
the Data Manager queries the relational view directly.

TTL-based expiry is *disabled by default* — data lives until the user
explicitly deletes it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import HTTPException

from .lightcurve_cache_service import (
    CACHE_ROOT,
    DATA_ROOT,
    PROJECT_ROOT,
    atomic_write_json,
    iter_dataset_dirs,
    read_json,
    unique_storage_size,
    utc_now,
    validate_dataset_dir,
)
from .persistence_service import persistence
from .workspace_service import MANIFEST_ROOT, WAREHOUSE_ROOT, workspace

CATALOG_PATH = MANIFEST_ROOT / "catalog.json"
CATALOG_VERSION = 1

RESULTS_DIR = PROJECT_ROOT / "results"


def _normalize_star_name(name: str) -> str:
    """Normalize a star name for grouping (case-insensitive, whitespace-collapsed)."""
    return " ".join((name or "").strip().lower().split())


def _resolve_catalog_path(value: str) -> Path:
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else PROJECT_ROOT / candidate).resolve()
    allowed_roots = [WAREHOUSE_ROOT.resolve(), PROJECT_ROOT.resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail="目录条目路径不在允许的共享数据根目录内")
    return resolved


# ── helpers ──────────────────────────────────────────────────────────


def _scan_target_results() -> Iterator[dict[str, Any]]:
    """Yield one catalog entry for every valid ``results/*.json`` file."""
    if not RESULTS_DIR.exists():
        return
    for path in sorted(RESULTS_DIR.glob("*.json")):
        if path.is_dir():
            continue
        payload = read_json(path)
        if not isinstance(payload, dict) or not isinstance(
                payload.get("target"), dict):
            continue
        target = payload["target"]
        display_name = target.get("resolved_target") or target.get(
            "query_target") or path.stem
        size = path.stat().st_size
        created_at = payload.get("generated_at") or datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc).isoformat()
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
                "target_type":
                ttype or None,
                "ra_deg":
                simbad.get("ra_deg"),
                "dec_deg":
                simbad.get("dec_deg"),
                "reference_count":
                len(target.get("literature_references", []) or []),
                "persistence_target_key":
                target.get("query_target") or display_name,
            },
        }


def _file_hash(path: str) -> str:
    """Short stable hash for a file path string."""
    return hashlib.sha256(path.encode()).hexdigest()[:16]


def _iter_lightcurve_roots() -> list[Path]:
    roots: list[Path] = []
    for root in (DATA_ROOT, PROJECT_ROOT / "data" / "lightcurves"):
        if not root:
            continue
        resolved = root.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _find_manifest_for_file(file_path: Path) -> dict[str, Any]:
    """Walk up from file_path to find the nearest manifest.json."""
    current = file_path.parent
    for _ in range(10):
        manifest = read_json(current / "manifest.json")
        if isinstance(manifest, dict):
            return manifest
        if current.parent == current or any(current == root for root in _iter_lightcurve_roots()):
            break
        current = current.parent
    return {}


def _guess_mission_from_path(file_path: Path) -> str:
    """Guess mission from FITS file path (e.g., .../TESS/...)."""
    parts = {p.upper() for p in file_path.parts}
    for mission in ("TESS", "KEPLER", "K2"):
        if mission in parts:
            return mission
    # Try from filename
    name = file_path.name.lower()
    if "tess" in name:
        return "TESS"
    if "kepler" in name:
        return "KEPLER"
    if "k2" in name:
        return "K2"
    return ""


def _read_fits_metadata(fits_path: Path) -> dict[str, Any]:
    """Read basic metadata from a FITS lightcurve file.

    Returns point_count, time_span_days, obs_id without loading full data.
    """
    result: dict[str, Any] = {
        "point_count": 0,
        "time_span_days": None,
        "obs_id": "",
    }
    try:
        from astropy.io import fits as astropy_fits
        import numpy as np

        with astropy_fits.open(fits_path, memmap=False) as hdul:
            for hdu in hdul:
                data = getattr(hdu, "data", None)
                cols = getattr(data, "columns", None) if data is not None else None
                names = [] if cols is None else [c.upper() for c in cols.names]
                if "TIME" not in names:
                    continue
                time_col = data["TIME"]
                if len(time_col) > 0:
                    result["point_count"] = int(len(time_col))
                    span = float(np.nanmax(time_col) - np.nanmin(time_col))
                    if np.isfinite(span):
                        result["time_span_days"] = round(span, 2)
                break
            # Read obs_id from primary header
            if len(hdul) > 0:
                header = hdul[0].header
                result["obs_id"] = str(header.get("OBSID", header.get("OBS_ID", "")))
    except Exception:
        pass
    return result


def _scan_lightcurve_files() -> Iterator[dict[str, Any]]:
    """Yield one catalog entry per unique lightcurve FITS or derived CSV file.

    Scans the shared lightcurve roots (warehouse objects and legacy data/lightcurves),
    deduplicates by inode, and produces file-level entries similar to how MAST presents
    individual observations.
    """
    roots = [root for root in _iter_lightcurve_roots() if root.exists()]
    if not roots:
        return

    seen_inodes: set[tuple[int, int]] = set()

    for root in roots:
        if not root.exists():
            continue
        for star_dir in sorted(root.iterdir()):
            if not star_dir.is_dir():
                continue
            if star_dir.name.startswith(".") or star_dir.name.startswith("_"):
                continue

            star_name = star_dir.name

            # ── FITS files ──
            fits_paths: list[Path] = []
            for pattern in ("*.fits", "*.fits.gz"):
                fits_paths.extend(star_dir.rglob(pattern))

            for fits_path in sorted(fits_paths):
                if not fits_path.is_file():
                    continue
                try:
                    stat = fits_path.stat()
                    inode_key = (stat.st_dev, stat.st_ino)
                    if inode_key in seen_inodes:
                        continue  # hardlink duplicate
                    seen_inodes.add(inode_key)
                except OSError:
                    continue

                manifest = _find_manifest_for_file(fits_path)
                mission = _guess_mission_from_path(fits_path)
                fits_meta = _read_fits_metadata(fits_path)

                rel_path = str(fits_path.relative_to(PROJECT_ROOT))

                yield {
                    "id": f"fits_{_file_hash(rel_path)}",
                    "type": "lightcurve_file",
                    "display_name": star_name,
                    "source": f"MAST/{mission}" if mission else "MAST",
                    "file_path": rel_path,
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc).isoformat(),
                    "tags": ["lightcurve"]
                    + ([mission.lower()] if mission else []),
                    "valid": fits_meta["point_count"] > 0,
                    "metadata": {
                        "missions": [mission] if mission else [],
                        "point_count": fits_meta["point_count"],
                        "time_span_days": fits_meta["time_span_days"],
                        "filename": fits_path.name,
                        "obs_id": fits_meta.get("obs_id", ""),
                        "file_type": "fits",
                    },
                }

            # ── Derived CSV files ──
            csv_paths: list[Path] = list(star_dir.rglob("lightcurve.csv"))
            for csv_path in sorted(csv_paths):
                if not csv_path.is_file():
                    continue
                try:
                    stat = csv_path.stat()
                    inode_key = (stat.st_dev, stat.st_ino)
                    if inode_key in seen_inodes:
                        continue
                    seen_inodes.add(inode_key)
                except OSError:
                    continue

                manifest = _find_manifest_for_file(csv_path)
                missions: list[str] = manifest.get("missions", [])

                point_count = 0
                time_span_days: float | None = None
                try:
                    times: list[float] = []
                    with csv_path.open("r", encoding="utf-8") as handle:
                        reader = csv.DictReader(handle)
                        for row in reader:
                            try:
                                t = float(row.get("time") or 0)
                                times.append(t)
                            except (ValueError, TypeError):
                                continue
                    if times:
                        point_count = len(times)
                        time_span_days = round(max(times) - min(times), 2)
                except Exception:
                    pass

                rel_path = str(csv_path.relative_to(PROJECT_ROOT))

                yield {
                    "id": f"csv_{_file_hash(rel_path)}",
                    "type": "lightcurve_derived",
                    "display_name": star_name,
                    "source": f"MAST/{'/'.join(missions)}" if missions else "MAST",
                    "file_path": rel_path,
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc).isoformat(),
                    "tags": ["lightcurve", "derived"]
                    + [m.lower() for m in missions],
                    "valid": True,
                    "metadata": {
                        "missions": missions,
                        "point_count": point_count,
                        "time_span_days": time_span_days,
                        "filename": csv_path.name,
                        "file_type": "csv",
                    },
                }


def _merge_catalog_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge relational workspace entries with existing filesystem-backed data."""
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_entry(entry: dict[str, Any]) -> None:
        key = (
            str(entry.get("type", "")),
            str(entry.get("display_name", "")),
            str(entry.get("file_path", "")),
        )
        if key in seen:
            return
        seen.add(key)
        merged.append(entry)

    for entry in entries:
        add_entry(entry)
    for entry in _scan_target_results():
        add_entry(entry)
    for entry in _scan_lightcurve_files():
        add_entry(entry)
    return merged


def _rebuild_catalog() -> dict[str, Any]:
    """Export the authoritative relational catalog for legacy readers."""
    entries = _merge_catalog_entries(workspace.catalog_entries())
    persistence.upsert_catalog(entries)
    catalog: dict[str, Any] = {
        "version": CATALOG_VERSION,
        "updated_at": utc_now(),
        "entries": entries,
    }
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(CATALOG_PATH, catalog)
    return catalog


def _load_catalog() -> dict[str, Any]:
    """Return a fresh database-backed view of the shared catalog."""
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
            entries = [
                e for e in entries
                if source.lower() in (e.get("source") or "").lower()
            ]
        if tags:
            tag_set = {t.lower() for t in tags}
            entries = [
                e for e in entries
                if tag_set & {t.lower()
                              for t in e.get("tags", [])}
            ]
        if search:
            q = search.lower()
            entries = [
                e for e in entries
                if q in (e.get("display_name") or "").lower() or q in (
                    e.get("source") or "").lower() or any(
                        q in t.lower() for t in e.get("tags", []))
            ]

        total = len(entries)
        page = entries[offset:offset + limit]
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
        raise HTTPException(status_code=404,
                            detail=f"Entry not found: {entry_id}")

    def delete_entry(self, entry_id: str) -> dict[str, Any]:
        catalog = self._ensure_fresh()
        target_entry = None
        for entry in catalog.get("entries", []):
            if entry.get("id") == entry_id:
                target_entry = entry
                break
        if target_entry is None:
            raise HTTPException(status_code=404,
                                detail=f"Entry not found: {entry_id}")

        abs_path = _resolve_catalog_path(target_entry["file_path"])

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

        if target_entry.get("type") == "target_result":
            removed_bytes = max(
                removed_bytes,
                workspace.delete_target(target_entry.get("display_name", "")),
            )
            removed_bytes = max(
                removed_bytes,
                persistence.delete_target(
                    target_entry.get("metadata", {}).get(
                        "persistence_target_key"
                    )
                    or target_entry.get("display_name", "")
                )
                or 0,
            )
        else:
            workspace.unregister_dataset(
                target_entry.get("metadata", {}).get("download_dir")
                or target_entry.get("file_path", "")
            )
            removed_bytes = max(
                removed_bytes,
                persistence.delete_dataset_object(
                    target_entry.get("file_path", "")
                )
                or 0,
            )
        persistence.delete_catalog_entry(entry_id)

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
                results.append({
                    "id": eid,
                    "status": "deleted",
                    "removed_bytes": r["removed_bytes"]
                })
                total_removed += r["removed_bytes"]
            except HTTPException as exc:
                results.append({
                    "id": eid,
                    "status": "error",
                    "detail": exc.detail
                })
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
            etype = entry.get("type", "")
            if etype == "target_result":
                if group["target_entry"] is None:  # keep first
                    group["target_entry"] = entry
                else:
                    group["total_size_bytes"] += entry.get("size_bytes",
                                                           0) or 0
            elif etype in ("lightcurve_file", "lightcurve_derived", "lightcurve_dataset"):
                group["lc_entries"].append(entry)

        # Build star list
        stars: list[dict[str, Any]] = []
        for key in order:
            g = groups[key]
            entry_count = (1 if g["target_entry"] else 0) + len(
                g["lc_entries"])
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
                if q in s["name"].lower() or (s["target_entry"] and q in (
                    s["target_entry"].get("source") or "").lower()) or any(
                        q in e.get("source", "").lower()
                        for e in s["lc_entries"])
                or any(q in t.lower() for e in
                       ([s["target_entry"]] if s["target_entry"] else []) +
                       s["lc_entries"] for t in e.get("tags", []))
            ]

        # filter: source
        if source:
            qs = source.lower()
            stars = [
                s for s in stars
                if (s["target_entry"] and qs in
                    (s["target_entry"].get("source") or "").lower()) or any(
                        qs in e.get("source", "").lower()
                        for e in s["lc_entries"])
            ]

        total = len(stars)
        page = stars[offset:offset + limit]
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
            raise HTTPException(status_code=404,
                                detail=f"No data found for star: {star_name}")

        total_removed = 0
        display_name = to_delete[0].get("display_name", star_name)
        deleted_ids: list[str] = []
        for entry in to_delete:
            abs_path = _resolve_catalog_path(entry["file_path"])
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
            if entry.get("type") == "target_result":
                total_removed = max(
                    total_removed,
                    persistence.delete_target(
                        entry.get("metadata", {}).get(
                            "persistence_target_key"
                        )
                        or display_name
                    )
                    or 0,
                )
            else:
                workspace.unregister_dataset(
                    entry.get("metadata", {}).get("download_dir")
                    or entry.get("file_path", "")
                )
                total_removed += (
                    persistence.delete_dataset_object(
                        entry.get("file_path", "")
                    )
                    or 0
                )
            persistence.delete_catalog_entry(entry.get("id", ""))

        total_removed = max(total_removed, workspace.delete_target(display_name))

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
