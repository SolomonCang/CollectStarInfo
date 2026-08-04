from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.migrate_to_warehouse import copy_verified, verify_report


class WarehouseMigrationTest(unittest.TestCase):
    def test_copy_is_checksum_verified_deduplicated_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_source = root / "first.fits"
            second_source = root / "second.fits"
            first_source.write_bytes(b"same-scientific-product")
            second_source.write_bytes(b"same-scientific-product")
            first_destination = root / "warehouse" / "one.fits"
            second_destination = root / "warehouse" / "two.fits"
            report = {
                "copied_files": 0, "copied_bytes": 0,
                "deduplicated_files": 0, "skipped_identical": 0,
                "conflicts": [], "files": [],
            }

            self.assertTrue(copy_verified(first_source, first_destination, report))
            self.assertTrue(copy_verified(second_source, second_destination, report))
            self.assertEqual(report["copied_files"], 2)
            self.assertEqual(report["deduplicated_files"], 1)
            self.assertEqual(first_destination.stat().st_ino, second_destination.stat().st_ino)

            persisted = {key: value for key, value in report.items() if not key.startswith("_")}
            report_path = root / "migration.json"
            report_path.write_text(json.dumps(persisted), encoding="utf-8")
            self.assertEqual(verify_report(report_path)["status"], "ok")

            second_destination.write_bytes(b"corrupted")
            self.assertEqual(verify_report(report_path)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
