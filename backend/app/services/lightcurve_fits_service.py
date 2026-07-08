from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from astropy.io import fits
from fastapi import HTTPException
import numpy as np

from ..schemas import LightCurveAnalysisRequest, LightCurveDatasetAnalysisRequest, LightCurveDatasetRequest, LightCurvePoint
from .lightcurve_archive_service import DATA_ROOT, PROJECT_ROOT, safe_target_name
from .lightcurve_service import analyze_light_curve

FLUX_CANDIDATES = (
    "PDCSAP_FLUX",
    "SAP_FLUX",
    "KSPSAP_FLUX",
    "DET_FLUX",
    "FLUX",
)


def _resolve_data_path(download_dir: str) -> Path:
    raw_path = Path(download_dir)
    candidate = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
    resolved = candidate.resolve()
    data_root = DATA_ROOT.resolve()
    if resolved != data_root and data_root not in resolved.parents:
        raise HTTPException(
            status_code=400,
            detail="download_dir must be under data/lightcurves")
    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(status_code=404,
                            detail=f"download_dir not found: {download_dir}")
    return resolved


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
                paths.append(Path(local_path))
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
                missions = sorted({rec.get("mission") for rec in records if rec.get("mission")})
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
        if not base.exists():
            return {"datasets": []}
        manifests = sorted(base.rglob("manifest.json"), reverse=True)
        datasets: list[dict[str, Any]] = []
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
            datasets.append({
                "target":
                manifest.get("target"),
                "download_dir":
                download_dir,
                "generated_at":
                manifest.get("generated_at"),
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
        return {"datasets": datasets}

    def _collect_dataset(
        self, request: LightCurveDatasetRequest
    ) -> tuple[Path, list[dict[str, float | None]], list[dict[str, Any]]]:
        download_dir = _resolve_data_path(request.download_dir)
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
        return download_dir, all_points, files

    def load_dataset(self,
                     request: LightCurveDatasetRequest) -> dict[str, Any]:
        download_dir, all_points, files = self._collect_dataset(request)
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
        }

    def write_dataset_csv(self,
                          request: LightCurveDatasetRequest) -> dict[str, Any]:
        download_dir, points, files = self._collect_dataset(request)
        csv_path = download_dir / "lightcurve.csv"

        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=["time", "flux", "flux_error"])
            writer.writeheader()
            writer.writerows(points)

        manifest_path = download_dir / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["csv_path"] = str(csv_path.relative_to(PROJECT_ROOT))
            manifest["csv_point_count"] = len(points)
            manifest["csv_original_point_count"] = len(points)
            manifest_path.write_text(json.dumps(manifest,
                                                ensure_ascii=False,
                                                indent=2),
                                     encoding="utf-8")

        return {
            "download_dir": str(download_dir.relative_to(PROJECT_ROOT)),
            "csv_path": str(csv_path.relative_to(PROJECT_ROOT)),
            "point_count": len(points),
            "original_point_count": len(points),
            "files": files,
        }

    def analyze_dataset(
            self, request: LightCurveDatasetAnalysisRequest) -> dict[str, Any]:
        dataset = self.load_dataset(request)
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
        return analysis
