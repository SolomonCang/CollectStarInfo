from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from fastapi import HTTPException

from ..schemas import LightCurveArchiveDownloadRequest, LightCurveArchiveSearchRequest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data" / "lightcurves"
LIGHT_CURVE_SUBGROUPS = {"LC", "LLC", "SLC"}
DEFAULT_MISSIONS = {"TESS", "KEPLER", "K2"}


def safe_target_name(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip()
    return safe or "unknown_target"


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
        try:
            _, rows = self._light_curve_products(request)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"MAST light-curve search failed: {exc}") from exc

        return {
            "target": request.target,
            "radius_deg": request.radius_deg,
            "missions": sorted(self._normalized_missions(request.missions)),
            "product_count": len(rows),
            "products": rows,
        }

    def _product_uri_set_from_dir(self, dataset_dir: Path) -> set[str]:
        """Read the product URI set from a previously downloaded dataset directory."""
        products_file = dataset_dir / "selected_products.json"
        if not products_file.exists():
            return set()
        try:
            records = json.loads(products_file.read_text(encoding="utf-8"))
            return {rec.get("product_uri") or rec.get("dataURI") or "" for rec in records}
        except (json.JSONDecodeError, KeyError):
            return set()

    def _find_existing_dataset(
        self, target: str, product_uris: set[str]
    ) -> dict[str, Any] | None:
        """Return an existing manifest if a dataset with the identical product set exists."""
        target_dir = DATA_ROOT / safe_target_name(target)
        if not target_dir.exists():
            return None
        for run_dir in sorted(target_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            if self._product_uri_set_from_dir(run_dir) == product_uris:
                manifest_path = run_dir / "manifest.json"
                if manifest_path.exists():
                    try:
                        return json.loads(manifest_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        continue
        return None

    def download(self,
                 request: LightCurveArchiveDownloadRequest) -> dict[str, Any]:
        from astroquery.mast import Observations

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

        requested_uris = {uri for uri in request.product_uris if uri}
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
            str(table_value(row, "dataURI") or table_value(row, "product_uri") or "")
            for row in selected_products
        }

        # ── Deduplication ──
        if not request.force:
            existing = self._find_existing_dataset(request.target, selected_uris)
            if existing is not None:
                existing["deduplicated"] = True
                return existing

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target_dir = DATA_ROOT / safe_target_name(request.target) / run_id
        target_dir.mkdir(parents=True, exist_ok=True)

        selected_records = table_to_records(selected_products)
        (target_dir / "selected_products.json").write_text(
            json.dumps(selected_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        manifest_table = Observations.download_products(
            selected_products,
            download_dir=str(target_dir),
            cache=True,
        )
        manifest_records = table_to_records(manifest_table)
        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target": request.target,
            "radius_deg": request.radius_deg,
            "missions": sorted(self._normalized_missions(request.missions)),
            "download_dir": str(target_dir.relative_to(PROJECT_ROOT)),
            "selected_count": len(selected_records),
            "manifest": manifest_records,
            "deduplicated": False,
        }
        (target_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return manifest
