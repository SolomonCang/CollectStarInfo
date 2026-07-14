from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from ..schemas import LightCurveArchiveDownloadRequest, LightCurveArchiveSearchRequest
from .lightcurve_cache_service import (
    CACHE_SCHEMA_VERSION,
    DATA_ROOT,
    PRODUCT_CACHE_ROOT,
    PROJECT_ROOT,
    SEARCH_CACHE_ROOT,
    atomic_write_json,
    cache_lock,
    file_sha256,
    iter_dataset_dirs,
    read_json,
    stable_hash,
    utc_now,
    validate_dataset_dir,
)

LIGHT_CURVE_SUBGROUPS = {"LC", "LLC", "SLC"}
DEFAULT_MISSIONS = {"TESS", "KEPLER", "K2"}
SEARCH_CACHE_TTL_SECONDS = int(os.getenv("LIGHTCURVE_SEARCH_CACHE_TTL", "0"))


def safe_target_name(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip().rstrip(".")
    return safe if safe not in {"", ".", ".."} else "unknown_target"


def table_value(row: Any, column: str) -> Any:
    if column not in getattr(row, "colnames", []):
        return None
    value = row[column]
    if getattr(value, "mask", False) is True:
        return None
    try:
        if value is None:
            return None
        if hasattr(value, "item"):
            value = value.item()
    except Exception:
        pass
    text = str(value).strip()
    if text in {"", "--", "nan", "None"}:
        return None
    return value


def table_to_records(table: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if table is None:
        return records
    for row in table:
        item: dict[str, Any] = {}
        for column in getattr(table, "colnames", []):
            value = table_value(row, column)
            if value is None:
                item[column] = None
            elif isinstance(value, (str, int, float, bool)):
                item[column] = value
            else:
                item[column] = str(value)
        records.append(item)
    return records


class LightCurveArchiveService:

    def _normalized_missions(self, missions: list[str]) -> set[str]:
        normalized = {
            mission.strip().upper()
            for mission in missions if mission.strip()
        }
        return normalized or DEFAULT_MISSIONS

    def _query_observations(self,
                            request: LightCurveArchiveSearchRequest) -> Any:
        from astropy import units as u
        from astropy.coordinates import SkyCoord
        from astroquery.mast import Observations

        if request.ra_deg is not None and request.dec_deg is not None:
            coordinates = SkyCoord(request.ra_deg,
                                   request.dec_deg,
                                   unit=(u.deg, u.deg))
            return Observations.query_region(coordinates,
                                             radius=request.radius_deg * u.deg)
        return Observations.query_criteria(target_name=request.target)

    def _filter_observations(self, table: Any, missions: set[str]) -> Any:
        if table is None or len(
                table) == 0 or "obs_collection" not in table.colnames:
            return table[:0] if table is not None else table

        mask: list[bool] = []
        for row in table:
            collection = str(table_value(row, "obs_collection") or "").upper()
            dataproduct_type = str(table_value(row, "dataproduct_type")
                                   or "").lower()
            mission_ok = collection in missions
            timeseries_ok = not dataproduct_type or dataproduct_type == "timeseries"
            mask.append(mission_ok and timeseries_ok)
        return table[mask]

    def _product_is_light_curve(self, row: Any, missions: set[str]) -> bool:
        collection = str(table_value(row, "obs_collection") or "").upper()
        subgroup = str(table_value(row, "productSubGroupDescription")
                       or "").upper()
        product_type = str(table_value(row, "productType") or "").upper()
        filename = str(table_value(row, "productFilename") or "").lower()
        description = str(table_value(row, "description") or "").lower()

        if collection not in missions:
            return False
        if product_type and product_type != "SCIENCE":
            return False
        if not filename.endswith((".fits", ".fits.gz")):
            return False
        return subgroup in LIGHT_CURVE_SUBGROUPS or "light curve" in description

    def _light_curve_products(
        self, request: LightCurveArchiveSearchRequest
    ) -> tuple[Any, list[dict[str, Any]]]:
        from astroquery.mast import Observations

        missions = self._normalized_missions(request.missions)
        observations = self._filter_observations(
            self._query_observations(request), missions)
        if observations is None or len(observations) == 0:
            return None, []

        products = Observations.get_product_list(observations)
        if products is None or len(products) == 0:
            return products, []

        mask = [
            self._product_is_light_curve(row, missions) for row in products
        ]
        filtered = products[mask]
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(filtered[:request.max_products]):
            rows.append({
                "index":
                index,
                "mission":
                table_value(row, "obs_collection"),
                "obs_id":
                table_value(row, "obs_id"),
                "product_uri":
                table_value(row, "dataURI") or table_value(row, "product_uri"),
                "filename":
                table_value(row, "productFilename"),
                "subgroup":
                table_value(row, "productSubGroupDescription"),
                "description":
                table_value(row, "description"),
                "size":
                table_value(row, "size"),
            })
        return filtered, rows

    def search(self,
               request: LightCurveArchiveSearchRequest) -> dict[str, Any]:
        cache_key = stable_hash({
            "target":
            request.target.strip().casefold(),
            "ra_deg":
            request.ra_deg,
            "dec_deg":
            request.dec_deg,
            "radius_deg":
            request.radius_deg,
            "missions":
            sorted(self._normalized_missions(request.missions)),
            "max_products":
            request.max_products,
            "schema_version":
            CACHE_SCHEMA_VERSION,
        })
        cache_path = SEARCH_CACHE_ROOT / f"{cache_key}.json"
        cached = read_json(cache_path)
        if (not request.force_refresh and isinstance(cached, dict)
                and isinstance(cached.get("response"), dict)
                and (SEARCH_CACHE_TTL_SECONDS <= 0 or time.time() -
                     cache_path.stat().st_mtime <= SEARCH_CACHE_TTL_SECONDS)):
            response = dict(cached["response"])
            response["cache"] = {
                "hit": True,
                "key": cache_key,
                "created_at": cached.get("created_at"),
                "ttl_seconds": SEARCH_CACHE_TTL_SECONDS,
            }
            return response

        try:
            _, rows = self._light_curve_products(request)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"MAST light-curve search failed: {exc}") from exc

        response = {
            "target": request.target,
            "radius_deg": request.radius_deg,
            "missions": sorted(self._normalized_missions(request.missions)),
            "product_count": len(rows),
            "products": rows,
        }
        atomic_write_json(
            cache_path, {
                "schema_version": CACHE_SCHEMA_VERSION,
                "created_at": utc_now(),
                "response": response,
            })
        response["cache"] = {
            "hit": False,
            "key": cache_key,
            "created_at": utc_now(),
            "ttl_seconds": SEARCH_CACHE_TTL_SECONDS,
        }
        return response

    def _product_uri_set_from_dir(self, dataset_dir: Path) -> set[str]:
        """Read the product URI set from a previously downloaded dataset directory."""
        products_file = dataset_dir / "selected_products.json"
        if not products_file.exists():
            return set()
        try:
            records = json.loads(products_file.read_text(encoding="utf-8"))
            return {
                rec.get("product_uri") or rec.get("dataURI") or ""
                for rec in records
            }
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return set()

    def _find_existing_dataset(
            self, target: str,
            product_uris: set[str]) -> dict[str, Any] | None:
        """Return a validated dataset for this product set, including aliases."""
        dataset_key = stable_hash(sorted(product_uris))
        candidates = sorted(iter_dataset_dirs(), reverse=True)
        for run_dir in candidates:
            manifest = read_json(run_dir / "manifest.json")
            if not isinstance(manifest, dict):
                continue
            same_key = manifest.get("dataset_key") == dataset_key
            if not same_key and self._product_uri_set_from_dir(
                    run_dir) != product_uris:
                continue
            valid, _, manifest = validate_dataset_dir(run_dir)
            if not valid or manifest is None:
                continue
            manifest["last_accessed_at"] = utc_now()
            with cache_lock(f"manifest:{run_dir}"):
                latest = read_json(run_dir / "manifest.json", manifest)
                latest["last_accessed_at"] = manifest["last_accessed_at"]
                atomic_write_json(run_dir / "manifest.json", latest)
                manifest = latest
            return manifest
        return None

    def _cached_product(
            self, product_uri: str) -> tuple[Path, dict[str, Any]] | None:
        product_key = stable_hash(product_uri)
        product_dir = PRODUCT_CACHE_ROOT / product_key
        metadata = read_json(product_dir / "metadata.json")
        if not isinstance(metadata, dict):
            return None
        relative_path = metadata.get("path")
        if not relative_path:
            return None
        path = PROJECT_ROOT / relative_path
        if not path.exists() or not path.is_file():
            return None
        expected_size = metadata.get("size")
        if expected_size is not None and path.stat().st_size != int(
                expected_size):
            return None
        return path, metadata

    def _store_product(
        self,
        product_uri: str,
        selected_record: dict[str, Any],
        source_path: Path,
        *,
        force: bool,
    ) -> tuple[Path, dict[str, Any]]:
        product_key = stable_hash(product_uri)
        with cache_lock(f"product:{product_key}"):
            if not force:
                cached = self._cached_product(product_uri)
                if cached is not None:
                    return cached
            product_dir = PRODUCT_CACHE_ROOT / product_key
            product_dir.mkdir(parents=True, exist_ok=True)
            filename = safe_target_name(source_path.name)
            final_path = product_dir / filename
            temporary_path = product_dir / f".{filename}.{uuid4().hex}.tmp"
            shutil.copy2(source_path, temporary_path)
            os.replace(temporary_path, final_path)
            metadata = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "product_key": product_key,
                "product_uri": product_uri,
                "filename": filename,
                "path": str(final_path.relative_to(PROJECT_ROOT)),
                "size": final_path.stat().st_size,
                "sha256": file_sha256(final_path),
                "cached_at": utc_now(),
                "selected_record": selected_record,
            }
            atomic_write_json(product_dir / "metadata.json", metadata)
            return final_path, metadata

    def _materialize_dataset(
        self,
        request: LightCurveArchiveDownloadRequest,
        products: list[tuple[Path, dict[str, Any]]],
    ) -> dict[str, Any]:
        product_uris = {metadata["product_uri"] for _, metadata in products}
        dataset_key = stable_hash(sorted(product_uris))
        target_root = DATA_ROOT / safe_target_name(request.target)
        target_root.mkdir(parents=True, exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_id = f"{run_id}-{uuid4().hex[:8]}"
        final_dir = target_root / run_id
        staging_dir = target_root / f".partial-{run_id}"
        product_dir = staging_dir / "products"
        product_dir.mkdir(parents=True)
        try:
            selected_records: list[dict[str, Any]] = []
            manifest_records: list[dict[str, Any]] = []
            for index, (cached_path, metadata) in enumerate(products):
                selected_record = metadata.get("selected_record") or {
                    "dataURI": metadata["product_uri"],
                    "productFilename": metadata["filename"],
                    "size": metadata["size"],
                }
                selected_records.append(selected_record)
                linked_name = f"{index:03d}-{safe_target_name(metadata['filename'])}"
                staging_link = product_dir / linked_name
                try:
                    os.link(cached_path, staging_link)
                except OSError:
                    shutil.copy2(cached_path, staging_link)
                final_link = final_dir / "products" / linked_name
                manifest_records.append({
                    "Local Path":
                    str(final_link.relative_to(PROJECT_ROOT)),
                    "Status":
                    "COMPLETE",
                    "size":
                    metadata["size"],
                    "sha256":
                    metadata["sha256"],
                    "product_key":
                    metadata["product_key"],
                    "product_uri":
                    metadata["product_uri"],
                })

            manifest = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "status": "complete",
                "generated_at": utc_now(),
                "last_accessed_at": utc_now(),
                "target": request.target,
                "radius_deg": request.radius_deg,
                "missions":
                sorted(self._normalized_missions(request.missions)),
                "dataset_key": dataset_key,
                "download_dir": str(final_dir.relative_to(PROJECT_ROOT)),
                "selected_count": len(selected_records),
                "manifest": manifest_records,
                "deduplicated": False,
            }
            atomic_write_json(staging_dir / "selected_products.json",
                              selected_records)
            atomic_write_json(staging_dir / "manifest.json", manifest)
            os.replace(staging_dir, final_dir)
            return manifest
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

    def _records_from_product_cache(
            self, product_uris: set[str]
    ) -> list[tuple[Path, dict[str, Any]]] | None:
        products: list[tuple[Path, dict[str, Any]]] = []
        for uri in sorted(product_uris):
            cached = self._cached_product(uri)
            if cached is None:
                return None
            products.append(cached)
        return products

    def download(self,
                 request: LightCurveArchiveDownloadRequest) -> dict[str, Any]:
        from astroquery.mast import Observations

        requested_uris = {uri for uri in request.product_uris if uri}
        if requested_uris:
            dataset_key = stable_hash(sorted(requested_uris))
            with cache_lock(f"dataset:{dataset_key}"):
                if not request.force:
                    existing = self._find_existing_dataset(
                        request.target, requested_uris)
                    if existing is not None:
                        existing["deduplicated"] = True
                        existing["cache"] = {
                            "dataset_hit": True,
                            "product_hits": len(requested_uris)
                        }
                        return existing
                    cached_products = self._records_from_product_cache(
                        requested_uris)
                    if cached_products is not None:
                        result = self._materialize_dataset(
                            request, cached_products)
                        result["cache"] = {
                            "dataset_hit": False,
                            "product_hits": len(cached_products),
                            "product_misses": 0,
                        }
                        return result

        try:
            product_table, rows = self._light_curve_products(request)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"MAST light-curve search failed: {exc}") from exc

        if product_table is None or len(product_table) == 0 or not rows:
            raise HTTPException(
                status_code=404,
                detail="No downloadable light-curve products found")

        selected_mask: list[bool] = []
        selected_count = 0
        for row in product_table:
            product_uri = str(
                table_value(row, "dataURI") or table_value(row, "product_uri")
                or "")
            selected = product_uri in requested_uris if requested_uris else selected_count < request.max_downloads
            selected_mask.append(selected)
            if selected:
                selected_count += 1
        selected_products = product_table[selected_mask]

        if len(selected_products) == 0:
            raise HTTPException(
                status_code=404,
                detail=
                "Selected light-curve products were not found in MAST results")

        selected_uris = {
            str(
                table_value(row, "dataURI") or table_value(row, "product_uri")
                or "")
            for row in selected_products
        }

        selected_records = table_to_records(selected_products)
        dataset_key = stable_hash(sorted(selected_uris))
        with cache_lock(f"dataset:{dataset_key}"):
            if not request.force:
                existing = self._find_existing_dataset(request.target,
                                                       selected_uris)
                if existing is not None:
                    existing["deduplicated"] = True
                    existing["cache"] = {
                        "dataset_hit": True,
                        "product_hits": len(selected_uris)
                    }
                    return existing

            cached_products: dict[str, tuple[Path, dict[str, Any]]] = {}
            missing_indices: list[int] = []
            for index, uri in enumerate(selected_uris):
                cached = None if request.force else self._cached_product(uri)
                if cached is None:
                    missing_indices.append(index)
                else:
                    cached_products[uri] = cached

            staging_download = DATA_ROOT / ".downloads" / f"{dataset_key}-{uuid4().hex}"
            try:
                if missing_indices:
                    uri_to_record = {
                        str(
                            record.get("dataURI") or record.get("product_uri") or ""):
                        record
                        for record in selected_records
                    }
                    missing_mask = []
                    for row in selected_products:
                        uri = str(
                            table_value(row, "dataURI")
                            or table_value(row, "product_uri") or "")
                        missing_mask.append(uri not in cached_products)
                    missing_table = selected_products[missing_mask]
                    manifest_table = Observations.download_products(
                        missing_table,
                        download_dir=str(staging_download),
                        cache=True,
                    )
                    downloaded_paths = [
                        Path(
                            record.get("Local Path")
                            or record.get("local_path") or "")
                        for record in table_to_records(manifest_table) if str(
                            record.get("Status") or record.get("status")
                            or "").upper() in {"", "COMPLETE"}
                    ]
                    for uri in sorted(selected_uris - set(cached_products)):
                        record = uri_to_record[uri]
                        filename = str(record.get("productFilename") or "")
                        source_path = next(
                            (path for path in downloaded_paths
                             if path.exists() and path.name == filename),
                            None,
                        )
                        if source_path is None:
                            raise HTTPException(
                                status_code=502,
                                detail=
                                f"MAST download did not produce {filename or uri}",
                            )
                        cached_products[uri] = self._store_product(
                            uri, record, source_path, force=request.force)

                ordered_products = [
                    cached_products[uri] for uri in sorted(selected_uris)
                ]
                result = self._materialize_dataset(request, ordered_products)
                result["cache"] = {
                    "dataset_hit": False,
                    "product_hits": len(selected_uris) - len(missing_indices),
                    "product_misses": len(missing_indices),
                }
                return result
            finally:
                shutil.rmtree(staging_download, ignore_errors=True)
