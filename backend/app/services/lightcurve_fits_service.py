from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from astropy.io import fits
from fastapi import HTTPException
import numpy as np

from ..schemas import LightCurveAnalysisRequest, LightCurveDatasetAnalysisRequest, LightCurveDatasetRequest, LightCurvePoint
from .lightcurve_archive_service import safe_target_name
from .lightcurve_cache_service import (
    ANALYSIS_CACHE_ROOT,
    CACHE_SCHEMA_VERSION,
    DATA_ROOT,
    DERIVED_CACHE_ROOT,
    PROJECT_ROOT,
    atomic_write_json,
    cache_lock,
    read_json,
    resolve_data_path,
    stable_hash,
    unique_storage_size,
    utc_now,
    validate_dataset_dir,
)
from .lightcurve_service import analyze_light_curve
from .persistence_service import persistence

FLUX_CANDIDATES = (
    "PDCSAP_FLUX",
    "SAP_FLUX",
    "KSPSAP_FLUX",
    "DET_FLUX",
    "FLUX",
)
DERIVED_CACHE_VERSION = 1
ANALYSIS_CACHE_VERSION = 1


def _resolve_data_path(download_dir: str) -> Path:
    return resolve_data_path(download_dir)


def _manifest_paths(download_dir: Path) -> list[Path]:
    manifest_path = download_dir / "manifest.json"
    paths: list[Path] = []
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest.get("manifest", []):
            local_path = item.get("Local Path") or item.get("local_path")
            status = str(item.get("Status") or item.get("status")
                         or "").upper()
            if local_path and status in {"", "COMPLETE"}:
                path = Path(local_path)
                paths.append(path if path.is_absolute() else PROJECT_ROOT / path)
    if not paths:
        paths.extend(download_dir.rglob("*.fits"))
        paths.extend(download_dir.rglob("*.fits.gz"))
    return [path for path in paths if path.exists()]


def _choose_flux_column(columns: list[str], requested: str | None) -> str:
    normalized = {column.upper(): column for column in columns}
    if requested:
        requested_upper = requested.upper()
        if requested_upper not in normalized:
            raise HTTPException(status_code=400,
                                detail=f"Flux column not found: {requested}")
        return normalized[requested_upper]
    for candidate in FLUX_CANDIDATES:
        if candidate in normalized:
            return normalized[candidate]
    raise HTTPException(status_code=400,
                        detail="No supported flux column found in FITS table")


def _error_column(columns: list[str], flux_column: str) -> str | None:
    normalized = {column.upper(): column for column in columns}
    for candidate in (f"{flux_column}_ERR",
                      flux_column.replace("FLUX", "FLUX_ERR"), "FLUX_ERR"):
        if candidate.upper() in normalized:
            return normalized[candidate.upper()]
    return None


def _read_fits_points(
    path: Path, request: LightCurveDatasetRequest
) -> tuple[list[dict[str, float | None]], dict[str, Any]]:
    with fits.open(path, memmap=False) as hdul:
        table_hdu = None
        for hdu in hdul:
            data = getattr(hdu, "data", None)
            columns = getattr(data, "columns", None)
            names = [] if columns is None else list(columns.names)
            if "TIME" in {name.upper() for name in names}:
                table_hdu = hdu
                break
        if table_hdu is None or table_hdu.data is None:
            return [], {
                "path": str(path),
                "point_count": 0,
                "skip_reason": "no TIME table"
            }

        data = table_hdu.data
        columns = list(data.columns.names)
        normalized = {column.upper(): column for column in columns}
        time_column = normalized["TIME"]
        flux_column = _choose_flux_column(columns, request.flux_column)
        error_column = _error_column(columns, flux_column)
        quality_column = normalized.get("QUALITY")

        time = np.asarray(data[time_column], dtype=float)
        flux = np.asarray(data[flux_column], dtype=float)
        mask = np.isfinite(time) & np.isfinite(flux)
        if request.quality_filter and quality_column is not None:
            quality = np.asarray(data[quality_column])
            mask = mask & (quality == 0)

        errors: np.ndarray | None = None
        if error_column is not None:
            errors = np.asarray(data[error_column], dtype=float)
            mask = mask & np.isfinite(errors)

        time = time[mask]
        flux = flux[mask]
        errors = None if errors is None else errors[mask]
        order = np.argsort(time)
        time = time[order]
        flux = flux[order]
        errors = None if errors is None else errors[order]

        points = [{
            "time":
            float(time[index]),
            "flux":
            float(flux[index]),
            "flux_error":
            None if errors is None else float(errors[index]),
        } for index in range(len(time))]

        metadata = {
            "path": str(path.relative_to(PROJECT_ROOT)),
            "point_count": len(points),
            "flux_column": flux_column,
            "error_column": error_column,
            "quality_filter": request.quality_filter
            and quality_column is not None,
            "mission": table_hdu.header.get("TELESCOP"),
            "object": table_hdu.header.get("OBJECT"),
        }
        return points, metadata


class LightCurveFitsService:

    def _record_cache_usage(
        self,
        download_dir: Path,
        *,
        source_fingerprint: str,
        processing_key: str | None = None,
        analysis_key: str | None = None,
    ) -> None:
        manifest_path = download_dir / "manifest.json"
        if not manifest_path.exists():
            return
        with cache_lock(f"manifest:{download_dir}"):
            manifest = read_json(manifest_path, {})
            if not isinstance(manifest, dict):
                return
            manifest["source_fingerprint"] = source_fingerprint
            manifest["last_accessed_at"] = utc_now()
            if processing_key:
                keys = set(manifest.get("derived_processing_keys", []))
                keys.add(processing_key)
                manifest["derived_processing_keys"] = sorted(keys)
            if analysis_key:
                keys = set(manifest.get("analysis_keys", []))
                keys.add(analysis_key)
                manifest["analysis_keys"] = sorted(keys)
            atomic_write_json(manifest_path, manifest)

    def _dataset_fingerprint(self, download_dir: Path) -> str:
        manifest = read_json(download_dir / "manifest.json", {})
        if manifest.get("dataset_key"):
            products = [
                {
                    "uri": item.get("product_uri"),
                    "sha256": item.get("sha256"),
                    "size": item.get("size") or item.get("Size"),
                }
                for item in manifest.get("manifest", [])
            ]
            return stable_hash({
                "dataset_key": manifest["dataset_key"],
                "products": products,
            })
        legacy = []
        for path in _manifest_paths(download_dir):
            stat = path.stat()
            legacy.append({
                "path": str(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            })
        return stable_hash(legacy)

    def _processing_key(
        self, download_dir: Path, request: LightCurveDatasetRequest
    ) -> tuple[str, str]:
        fingerprint = self._dataset_fingerprint(download_dir)
        key = stable_hash({
            "source": fingerprint,
            "flux_column": request.flux_column,
            "quality_filter": request.quality_filter,
            "version": DERIVED_CACHE_VERSION,
        })
        return fingerprint, key

    def _load_derived_cache(
        self, cache_path: Path, metadata_path: Path
    ) -> tuple[list[dict[str, float | None]], list[dict[str, Any]]] | None:
        metadata = read_json(metadata_path)
        if not cache_path.exists() or not isinstance(metadata, dict):
            return None
        try:
            with np.load(cache_path, allow_pickle=False) as arrays:
                times = arrays["time"]
                fluxes = arrays["flux"]
                errors = arrays["flux_error"]
            points = [
                {
                    "time": float(time),
                    "flux": float(flux),
                    "flux_error": None if np.isnan(error) else float(error),
                }
                for time, flux, error in zip(times, fluxes, errors)
            ]
            return points, metadata.get("files", [])
        except (OSError, ValueError, KeyError):
            return None

    def _write_derived_cache(
        self,
        cache_path: Path,
        metadata_path: Path,
        points: list[dict[str, float | None]],
        files: list[dict[str, Any]],
        source_fingerprint: str,
        processing_key: str,
    ) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{cache_path.name}.", suffix=".tmp", dir=cache_path.parent
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                np.savez_compressed(
                    handle,
                    time=np.asarray([point["time"] for point in points]),
                    flux=np.asarray([point["flux"] for point in points]),
                    flux_error=np.asarray([
                        np.nan if point["flux_error"] is None else point["flux_error"]
                        for point in points
                    ]),
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, cache_path)
        finally:
            Path(temporary_name).unlink(missing_ok=True)
        atomic_write_json(metadata_path, {
            "schema_version": CACHE_SCHEMA_VERSION,
            "cache_version": DERIVED_CACHE_VERSION,
            "source_fingerprint": source_fingerprint,
            "processing_key": processing_key,
            "created_at": utc_now(),
            "point_count": len(points),
            "files": files,
        })

    def _dataset_extra_info(self, download_dir: str) -> dict[str, Any]:
        """Extract extra summary information from a dataset directory."""
        info: dict[str, Any] = {
            "missions": [],
            "time_min": None,
            "time_max": None,
            "time_span_days": None,
        }
        dir_path = _resolve_data_path(download_dir)

        # Missions from selected_products.json
        products_file = dir_path / "selected_products.json"
        if products_file.exists():
            try:
                records = json.loads(products_file.read_text(encoding="utf-8"))
                missions = sorted({
                    rec.get("mission") or rec.get("obs_collection")
                    for rec in records
                    if rec.get("mission") or rec.get("obs_collection")
                })
                info["missions"] = missions
            except (json.JSONDecodeError, KeyError):
                pass

        # Time span from CSV
        csv_path = dir_path / "lightcurve.csv"
        if not csv_path.exists():
            # Check manifest for csv_path
            manifest_path = dir_path / "manifest.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    alt_csv = manifest.get("csv_path")
                    if alt_csv:
                        csv_path = PROJECT_ROOT / alt_csv
                except json.JSONDecodeError:
                    pass

        if csv_path.exists():
            try:
                times = []
                with csv_path.open("r", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    for row in reader:
                        try:
                            t = float(row.get("time") or 0)
                            times.append(t)
                        except (ValueError, TypeError):
                            continue
                if times:
                    info["time_min"] = min(times)
                    info["time_max"] = max(times)
                    info["time_span_days"] = round(max(times) - min(times), 2)
            except Exception:
                pass

        return info

    def list_datasets(self, target: str | None = None) -> dict[str, Any]:
        base = DATA_ROOT / safe_target_name(target) if target else DATA_ROOT
        manifests = sorted(base.rglob("manifest.json"), reverse=True) if base.exists() else []
        datasets: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for manifest_path in manifests:
            try:
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            download_dir = (
                manifest.get("download_dir")
                or str(manifest_path.parent.relative_to(PROJECT_ROOT))
            )
            extra = self._dataset_extra_info(download_dir)
            valid, validation_errors, _ = validate_dataset_dir(manifest_path.parent)
            datasets.append({
                "target":
                manifest.get("target"),
                "download_dir":
                download_dir,
                "generated_at":
                manifest.get("generated_at"),
                "last_accessed_at":
                manifest.get("last_accessed_at"),
                "dataset_key":
                manifest.get("dataset_key"),
                "status":
                manifest.get("status") or ("complete" if valid else "invalid"),
                "valid":
                valid,
                "validation_errors":
                validation_errors,
                "size_bytes":
                unique_storage_size(iter([manifest_path.parent])),
                "selected_count":
                manifest.get("selected_count"),
                "manifest_entries":
                len(manifest.get("manifest", [])),
                "csv_path":
                manifest.get("csv_path"),
                "csv_exists":
                bool(manifest.get("csv_path")) and
                (PROJECT_ROOT / manifest["csv_path"]).exists(),
                "csv_point_count":
                manifest.get("csv_point_count"),
                "missions":
                extra["missions"],
                "time_min":
                extra["time_min"],
                "time_max":
                extra["time_max"],
                "time_span_days":
                extra["time_span_days"],
            })
            if manifest.get("dataset_key"):
                seen_keys.add(str(manifest["dataset_key"]))

        for row in persistence.list_datasets(target):
            manifest = row.get("manifest") or {}
            dataset_key = str(row.get("dataset_key") or "")
            if dataset_key in seen_keys:
                continue
            datasets.append({
                "target": row.get("target_name"),
                "download_dir": row.get("download_dir"),
                "generated_at": manifest.get("generated_at"),
                "last_accessed_at": manifest.get("last_accessed_at"),
                "dataset_key": dataset_key,
                "status": manifest.get("status", "complete"),
                "valid": True,
                "validation_errors": [],
                "size_bytes": int(row.get("size_bytes") or 0),
                "selected_count": manifest.get("selected_count"),
                "manifest_entries": len(manifest.get("manifest", [])),
                "csv_path": manifest.get("csv_path"),
                "csv_exists": bool(manifest.get("csv_path")),
                "csv_point_count": manifest.get("csv_point_count"),
                "missions": manifest.get("missions", []),
                "time_min": None,
                "time_max": None,
                "time_span_days": None,
                "storage": "postgres-s3",
            })
        return {"datasets": datasets}

    def _collect_dataset(
        self, request: LightCurveDatasetRequest
    ) -> tuple[Path, list[dict[str, float | None]], list[dict[str, Any]], dict[str, Any]]:
        download_dir = _resolve_data_path(request.download_dir)
        source_fingerprint, processing_key = self._processing_key(download_dir, request)
        cache_dir = DERIVED_CACHE_ROOT / source_fingerprint
        cache_path = cache_dir / f"{processing_key}.npz"
        metadata_path = cache_dir / f"{processing_key}.json"
        with cache_lock(f"derived:{processing_key}"):
            cached = self._load_derived_cache(cache_path, metadata_path)
            if cached is not None:
                points, files = cached
                self._record_cache_usage(
                    download_dir,
                    source_fingerprint=source_fingerprint,
                    processing_key=processing_key,
                )
                return download_dir, points, files, {
                    "derived_hit": True,
                    "source_fingerprint": source_fingerprint,
                    "processing_key": processing_key,
                }

        fits_paths = _manifest_paths(download_dir)
        if not fits_paths:
            raise HTTPException(status_code=404,
                                detail="No FITS files found in dataset")

        all_points: list[dict[str, float | None]] = []
        files: list[dict[str, Any]] = []
        for path in fits_paths:
            points, metadata = _read_fits_points(path, request)
            files.append(metadata)
            all_points.extend(points)

        if len(all_points) < 3:
            raise HTTPException(
                status_code=400,
                detail="Dataset has fewer than three usable light-curve points"
            )

        all_points.sort(key=lambda item: float(item["time"] or 0.0))
        with cache_lock(f"derived:{processing_key}"):
            self._write_derived_cache(
                cache_path,
                metadata_path,
                all_points,
                files,
                source_fingerprint,
                processing_key,
            )
        self._record_cache_usage(
            download_dir,
            source_fingerprint=source_fingerprint,
            processing_key=processing_key,
        )
        return download_dir, all_points, files, {
            "derived_hit": False,
            "source_fingerprint": source_fingerprint,
            "processing_key": processing_key,
        }

    def load_dataset(self,
                     request: LightCurveDatasetRequest) -> dict[str, Any]:
        download_dir, all_points, files, cache_info = self._collect_dataset(request)
        original_count = len(all_points)
        if original_count > request.max_points:
            indices = np.linspace(0,
                                  original_count - 1,
                                  request.max_points,
                                  dtype=int)
            all_points = [all_points[int(index)] for index in indices]

        return {
            "download_dir": str(download_dir.relative_to(PROJECT_ROOT)),
            "point_count": len(all_points),
            "original_point_count": original_count,
            "files": files,
            "points": all_points,
            "cache": cache_info,
        }

    def write_dataset_csv(self,
                          request: LightCurveDatasetRequest) -> dict[str, Any]:
        download_dir, points, files, cache_info = self._collect_dataset(request)
        csv_path = download_dir / "lightcurve.csv"

        manifest_path = download_dir / "manifest.json"
        manifest = read_json(manifest_path, {})
        if (
            csv_path.exists()
            and manifest.get("csv_processing_key") == cache_info["processing_key"]
        ):
            return {
                "download_dir": str(download_dir.relative_to(PROJECT_ROOT)),
                "csv_path": str(csv_path.relative_to(PROJECT_ROOT)),
                "point_count": manifest.get("csv_point_count", len(points)),
                "original_point_count": manifest.get("csv_original_point_count", len(points)),
                "files": files,
                "cache": {**cache_info, "csv_hit": True},
            }

        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{csv_path.name}.", suffix=".tmp", dir=csv_path.parent
        )
        temporary_csv = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=["time", "flux", "flux_error"])
                writer.writeheader()
                writer.writerows(points)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_csv, csv_path)
        finally:
            temporary_csv.unlink(missing_ok=True)

        if manifest_path.exists():
            with cache_lock(f"manifest:{download_dir}"):
                manifest = read_json(manifest_path, {})
                manifest["csv_path"] = str(csv_path.relative_to(PROJECT_ROOT))
                manifest["csv_point_count"] = len(points)
                manifest["csv_original_point_count"] = len(points)
                manifest["csv_processing_key"] = cache_info["processing_key"]
                manifest["csv_generated_at"] = utc_now()
                atomic_write_json(manifest_path, manifest)
                persistence.save_dataset(download_dir, manifest)

        return {
            "download_dir": str(download_dir.relative_to(PROJECT_ROOT)),
            "csv_path": str(csv_path.relative_to(PROJECT_ROOT)),
            "point_count": len(points),
            "original_point_count": len(points),
            "files": files,
            "cache": {**cache_info, "csv_hit": False},
        }

    def analyze_dataset(
            self, request: LightCurveDatasetAnalysisRequest) -> dict[str, Any]:
        dataset = self.load_dataset(request)
        request_payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
        analysis_key = stable_hash({
            "source_fingerprint": dataset["cache"]["source_fingerprint"],
            "processing_key": dataset["cache"]["processing_key"],
            "max_points": request.max_points,
            "detrend": request_payload["detrend"],
            "period_search": request_payload["period_search"],
            "version": ANALYSIS_CACHE_VERSION,
        })
        analysis_path = ANALYSIS_CACHE_ROOT / f"{analysis_key}.json"
        cached_analysis = read_json(analysis_path)
        if isinstance(cached_analysis, dict):
            self._record_cache_usage(
                _resolve_data_path(request.download_dir),
                source_fingerprint=dataset["cache"]["source_fingerprint"],
                analysis_key=analysis_key,
            )
            cached_analysis["cache"] = {
                **dataset["cache"],
                "analysis_hit": True,
                "analysis_key": analysis_key,
            }
            return cached_analysis

        points = [LightCurvePoint(**point) for point in dataset["points"]]
        analysis = analyze_light_curve(
            LightCurveAnalysisRequest(
                points=points,
                detrend=request.detrend,
                period_search=request.period_search,
            ))
        analysis["dataset"] = {
            "download_dir": dataset["download_dir"],
            "point_count": dataset["point_count"],
            "original_point_count": dataset["original_point_count"],
            "files": dataset["files"],
        }
        analysis["cache"] = {
            **dataset["cache"],
            "analysis_hit": False,
            "analysis_key": analysis_key,
        }
        with cache_lock(f"analysis:{analysis_key}"):
            existing = read_json(analysis_path)
            if isinstance(existing, dict):
                existing["cache"] = {
                    **dataset["cache"],
                    "analysis_hit": True,
                    "analysis_key": analysis_key,
                }
                return existing
            atomic_write_json(analysis_path, analysis)
        self._record_cache_usage(
            _resolve_data_path(request.download_dir),
            source_fingerprint=dataset["cache"]["source_fingerprint"],
            analysis_key=analysis_key,
        )
        return analysis
