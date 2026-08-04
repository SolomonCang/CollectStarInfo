from __future__ import annotations

import unittest

from fastapi import HTTPException

from backend.app.services.catalog_service import _resolve_catalog_path


class CatalogPathSecurityTest(unittest.TestCase):
    def test_catalog_paths_cannot_escape_warehouse(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _resolve_catalog_path("../../outside-target-info")
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
