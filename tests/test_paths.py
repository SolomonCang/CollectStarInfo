from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from backend.app import main
from backend.app.services import catalog_service


class StartupPathsTest(unittest.IsolatedAsyncioTestCase):
    async def test_startup_only_creates_directories_inside_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "project"
            root.mkdir()
            with patch.object(main, "PROJECT_ROOT", root), \
                 patch.object(main, "WAREHOUSE_ROOT", root / "warehouse"), \
                 patch.object(main.workspace, "initialize"), \
                 patch.object(main.persistence, "initialize"), \
                 patch.object(main, "_sync_catalog"):
                await main._ensure_data_dirs()
            self.assertTrue((root / "results").is_dir())
            self.assertTrue((root / "warehouse/objects/lightcurves").is_dir())
            self.assertFalse((parent / "results").exists())


class CatalogAliasTest(unittest.TestCase):
    def test_scanner_accepts_symlink_alias_without_losing_path_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            real = parent / "real"
            alias = parent / "alias"
            real.mkdir()
            alias.symlink_to(real, target_is_directory=True)
            curve = real / "data/lightcurves/Test Star/lightcurve.csv"
            curve.parent.mkdir(parents=True)
            curve.write_text("time,flux\n1,1\n2,1\n")
            outside = parent / "outside.csv"
            outside.write_text("private")
            with patch.object(catalog_service, "PROJECT_ROOT", alias), \
                 patch.object(catalog_service, "DATA_ROOT", alias / "data/lightcurves"), \
                 patch.object(catalog_service, "WAREHOUSE_ROOT", alias / "warehouse"):
                entries = list(catalog_service._scan_lightcurve_files())
                self.assertEqual(entries[0]["file_path"], "data/lightcurves/Test Star/lightcurve.csv")
                self.assertEqual(catalog_service._resolve_catalog_path(entries[0]["file_path"]), curve)
                with self.assertRaises(HTTPException) as raised:
                    catalog_service._resolve_catalog_path(str(outside))
                self.assertEqual(raised.exception.status_code, 400)
