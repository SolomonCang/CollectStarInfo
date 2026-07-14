from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astropy.io import fits
import numpy as np

from backend.app.schemas import (
    DetrendOptions,
    LightCurveArchiveDownloadRequest,
    LightCurveArchiveSearchRequest,
    LightCurveDatasetAnalysisRequest,
    LightCurveDatasetRequest,
    PeriodSearchOptions,
)
from backend.app.services import lightcurve_cache_service as cache_module
from backend.app.services import lightcurve_archive_service as archive_module
from backend.app.services import lightcurve_fits_service as fits_module


class LightCurveCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temporary.name).resolve()
        self.data_root = self.project_root / "data" / "lightcurves"
        self.cache_root = self.data_root / "_cache"
        self.dataset_dir = self.data_root / "Test Star" / "run-1"
        self.dataset_dir.mkdir(parents=True)

        self.originals = {}
        replacements = {
            cache_module: {
                "PROJECT_ROOT": self.project_root,
                "DATA_ROOT": self.data_root,
                "CACHE_ROOT": self.cache_root,
                "SEARCH_CACHE_ROOT": self.cache_root / "search",
                "PRODUCT_CACHE_ROOT": self.cache_root / "products",
                "DERIVED_CACHE_ROOT": self.cache_root / "derived",
                "ANALYSIS_CACHE_ROOT": self.cache_root / "analysis",
                "LOCK_ROOT": self.cache_root / "locks",
            },
            fits_module: {
                "PROJECT_ROOT": self.project_root,
                "DATA_ROOT": self.data_root,
                "DERIVED_CACHE_ROOT": self.cache_root / "derived",
                "ANALYSIS_CACHE_ROOT": self.cache_root / "analysis",
            },
            archive_module: {
                "PROJECT_ROOT": self.project_root,
                "DATA_ROOT": self.data_root,
                "SEARCH_CACHE_ROOT": self.cache_root / "search",
                "PRODUCT_CACHE_ROOT": self.cache_root / "products",
            },
        }
        for module, values in replacements.items():
            self.originals[module] = {name: getattr(module, name) for name in values}
            for name, value in values.items():
                setattr(module, name, value)

        self.fits_path = self.dataset_dir / "test-lc.fits"
        time = np.linspace(0.0, 20.0, 240)
        flux = 1.0 + 0.02 * np.sin(2 * np.pi * time / 2.5)
        columns = fits.ColDefs([
            fits.Column(name="TIME", format="D", array=time),
            fits.Column(name="PDCSAP_FLUX", format="D", array=flux),
            fits.Column(name="PDCSAP_FLUX_ERR", format="D", array=np.full_like(time, 0.001)),
            fits.Column(name="QUALITY", format="J", array=np.zeros_like(time, dtype=np.int32)),
        ])
        fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU.from_columns(columns)]).writeto(self.fits_path)
        selected = [{
            "dataURI": "mast:TESS/product/test-lc.fits",
            "productFilename": "test-lc.fits",
            "obs_collection": "TESS",
        }]
        cache_module.atomic_write_json(self.dataset_dir / "selected_products.json", selected)
        cache_module.atomic_write_json(self.dataset_dir / "manifest.json", {
            "generated_at": cache_module.utc_now(),
            "target": "Test Star",
            "download_dir": str(self.dataset_dir.relative_to(self.project_root)),
            "selected_count": 1,
            "manifest": [{
                "Local Path": str(self.fits_path.relative_to(self.project_root)),
                "Status": "COMPLETE",
            }],
        })

    def tearDown(self) -> None:
        for module, values in self.originals.items():
            for name, value in values.items():
                setattr(module, name, value)
        self.temporary.cleanup()

    def test_legacy_manifest_is_valid_and_listed(self) -> None:
        valid, errors, _ = cache_module.validate_dataset_dir(self.dataset_dir)
        self.assertTrue(valid, errors)
        datasets = fits_module.LightCurveFitsService().list_datasets("Test Star")["datasets"]
        self.assertEqual(len(datasets), 1)
        self.assertTrue(datasets[0]["valid"])
        self.assertEqual(datasets[0]["missions"], ["TESS"])

    def test_derived_and_csv_cache_hit(self) -> None:
        service = fits_module.LightCurveFitsService()
        request = LightCurveDatasetRequest(
            download_dir=str(self.dataset_dir.relative_to(self.project_root)),
            max_points=1000,
        )
        first = service.load_dataset(request)
        second = service.load_dataset(request)
        self.assertFalse(first["cache"]["derived_hit"])
        self.assertTrue(second["cache"]["derived_hit"])
        self.assertEqual(first["original_point_count"], 240)

        first_csv = service.write_dataset_csv(request)
        second_csv = service.write_dataset_csv(request)
        self.assertFalse(first_csv["cache"]["csv_hit"])
        self.assertTrue(second_csv["cache"]["csv_hit"])

    def test_analysis_cache_key_includes_parameters(self) -> None:
        service = fits_module.LightCurveFitsService()
        request = LightCurveDatasetAnalysisRequest(
            download_dir=str(self.dataset_dir.relative_to(self.project_root)),
            max_points=240,
            detrend=DetrendOptions(polynomial_order=1),
            period_search=PeriodSearchOptions(
                min_period=1.0, max_period=5.0, samples_per_peak=4
            ),
        )
        first = service.analyze_dataset(request)
        second = service.analyze_dataset(request)
        self.assertFalse(first["cache"]["analysis_hit"])
        self.assertTrue(second["cache"]["analysis_hit"])
        self.assertEqual(first["cache"]["analysis_key"], second["cache"]["analysis_key"])

        changed = request.model_copy(
            update={"detrend": DetrendOptions(polynomial_order=2)}
        )
        third = service.analyze_dataset(changed)
        self.assertFalse(third["cache"]["analysis_hit"])
        self.assertNotEqual(first["cache"]["analysis_key"], third["cache"]["analysis_key"])

    def test_atomic_json_never_leaves_temporary_file(self) -> None:
        path = self.data_root / "atomic.json"
        cache_module.atomic_write_json(path, {"value": 1})
        self.assertEqual(json.loads(path.read_text()), {"value": 1})
        self.assertEqual(list(path.parent.glob(".atomic.json.*.tmp")), [])

    def test_product_cache_materializes_and_deduplicates_dataset(self) -> None:
        service = archive_module.LightCurveArchiveService()
        uri = "mast:TESS/product/cached-test-lc.fits"
        record = {
            "dataURI": uri,
            "productFilename": "test-lc.fits",
            "obs_collection": "TESS",
        }
        service._store_product(uri, record, self.fits_path, force=False)
        request = LightCurveArchiveDownloadRequest(
            target="Alias Star", product_uris=[uri]
        )
        manifest = service.download(request)
        self.assertEqual(manifest["cache"]["product_hits"], 1)
        self.assertEqual(manifest["cache"]["product_misses"], 0)
        dataset_dir = self.project_root / manifest["download_dir"]
        valid, errors, _ = cache_module.validate_dataset_dir(dataset_dir, deep=True)
        self.assertTrue(valid, errors)
        existing = service._find_existing_dataset("Another Alias", {uri})
        self.assertEqual(existing["dataset_key"], manifest["dataset_key"])
        repeated = service.download(request)
        self.assertTrue(repeated["deduplicated"])
        self.assertTrue(repeated["cache"]["dataset_hit"])

    def test_search_cache_avoids_second_archive_query(self) -> None:
        service = archive_module.LightCurveArchiveService()
        request = LightCurveArchiveSearchRequest(target="Test Star")
        products = [{"product_uri": "mast:TESS/product/test.fits"}]
        with patch.object(service, "_light_curve_products", return_value=(None, products)) as query:
            first = service.search(request)
            second = service.search(request)
        self.assertFalse(first["cache"]["hit"])
        self.assertTrue(second["cache"]["hit"])
        self.assertEqual(query.call_count, 1)

    def test_cleanup_previews_and_removes_orphan_cache_layers(self) -> None:
        product = self.cache_root / "products" / "orphan-product"
        derived = self.cache_root / "derived" / "orphan-derived"
        analysis = self.cache_root / "analysis" / "orphan-analysis.json"
        search = self.cache_root / "search" / "expired.json"
        product.mkdir(parents=True)
        derived.mkdir(parents=True)
        analysis.parent.mkdir(parents=True)
        search.parent.mkdir(parents=True)
        (product / "file.fits").write_bytes(b"fits")
        (derived / "curve.npz").write_bytes(b"curve")
        analysis.write_text("{}")
        search.write_text("{}")
        os.utime(search, (0, 0))

        service = cache_module.LightCurveCacheService()
        preview = service.cleanup(
            max_age_days=None,
            max_size_mb=None,
            dry_run=True,
            remove_unreferenced_products=True,
        )
        self.assertEqual(preview["unreferenced_products"], 1)
        self.assertEqual(preview["unreferenced_derived"], 1)
        self.assertEqual(preview["unreferenced_analysis"], 1)
        self.assertEqual(preview["expired_search_entries"], 1)
        self.assertTrue(product.exists())

        service.cleanup(
            max_age_days=None,
            max_size_mb=None,
            dry_run=False,
            remove_unreferenced_products=True,
        )
        self.assertFalse(product.exists())
        self.assertFalse(derived.exists())
        self.assertFalse(analysis.exists())
        self.assertFalse(search.exists())


if __name__ == "__main__":
    unittest.main()
