import json
import tempfile
import unittest
from pathlib import Path

from backend.app.services import catalog_service


class CatalogServiceTestCase(unittest.TestCase):
    def test_rebuild_catalog_includes_existing_results_and_lightcurves(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            results_dir = tmp_path / "results"
            results_dir.mkdir(parents=True)
            (results_dir / "AD Leo.json").write_text(
                json.dumps(
                    {
                        "target": {
                            "resolved_target": "AD Leo",
                            "query_target": "AD Leo",
                            "sources": ["SIMBAD", "Gaia"],
                            "target_type": "Star",
                            "literature_references": [{"id": "1"}],
                            "simbad": {"ra_deg": 1.0, "dec_deg": 2.0},
                        },
                        "generated_at": "2026-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            lightcurve_dir = tmp_path / "data" / "lightcurves" / "AD Leo"
            lightcurve_dir.mkdir(parents=True)
            (lightcurve_dir / "lightcurve.csv").write_text("time\n1\n2\n3\n", encoding="utf-8")

            original_project_root = catalog_service.PROJECT_ROOT
            original_data_root = catalog_service.DATA_ROOT
            original_results_dir = catalog_service.RESULTS_DIR
            original_catalog_path = catalog_service.CATALOG_PATH

            try:
                catalog_service.PROJECT_ROOT = tmp_path
                catalog_service.DATA_ROOT = tmp_path / "data" / "lightcurves"
                catalog_service.RESULTS_DIR = results_dir
                catalog_service.CATALOG_PATH = tmp_path / "catalog.json"
                catalog_service.persistence.upsert_catalog = lambda entries: None
                catalog_service.workspace.catalog_entries = lambda: []

                catalog = catalog_service._rebuild_catalog()
                entries = catalog["entries"]

                self.assertTrue(any(entry["type"] == "target_result" and entry["display_name"] == "AD Leo" for entry in entries))
                self.assertTrue(any(entry["type"] == "lightcurve_derived" and entry["display_name"] == "AD Leo" for entry in entries))
            finally:
                catalog_service.PROJECT_ROOT = original_project_root
                catalog_service.DATA_ROOT = original_data_root
                catalog_service.RESULTS_DIR = original_results_dir
                catalog_service.CATALOG_PATH = original_catalog_path


if __name__ == "__main__":
    unittest.main()
