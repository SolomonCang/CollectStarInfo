from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from astropy.table import Table
from fastapi import HTTPException
from starlette.requests import Request

from backend.app import portal
from backend.app.auth import require_user


def request(headers=None, method="GET"):
    return Request({
        "type": "http", "method": method, "path": "/api/catalog/stats",
        "query_string": b"", "scheme": "http",
        "server": ("localhost", 8780), "client": ("127.0.0.1", 1234),
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
    })


class PortalIdentityTest(unittest.TestCase):
    def setUp(self):
        self.headers = {
            portal.TRUST_MARKER_HEADER: "1", portal.PORTAL_USER_ID_HEADER: "17",
            portal.PORTAL_USERNAME_HEADER: "Researcher", portal.PORTAL_ROLE_HEADER: "user",
            portal.PORTAL_CSRF_HEADER: "x" * 64,
        }

    def test_missing_or_malformed_identity_never_provisions_users(self):
        for header in self.headers:
            invalid = dict(self.headers)
            invalid.pop(header)
            with self.subTest(header=header), patch.object(portal, "_ensure_target_user") as create:
                with self.assertRaises(HTTPException) as raised:
                    portal.portal_current_user(request(invalid))
                self.assertEqual(raised.exception.status_code, 401)
                create.assert_not_called()

    def test_roles_identity_and_csrf_remain_compatible(self):
        stable_id = portal._target_user_id(17, "researcher")
        for role, expected in [("superadmin", "admin"), ("admin", "user"), ("user", "user")]:
            with self.subTest(role=role), patch.object(portal, "_ensure_target_user", return_value=stable_id) as create:
                headers = {**self.headers, portal.PORTAL_ROLE_HEADER: role}
                identity = portal.portal_current_user(request(headers))
                create.assert_called_once_with(17, "researcher", expected)
                self.assertEqual(identity.user_id, stable_id)
                csrf = hashlib.sha256(f"collectstarinfo\0{17}\0{'x' * 64}".encode()).hexdigest()
                self.assertEqual(identity.csrf_token, csrf)
                with self.assertRaises(HTTPException):
                    require_user(request(headers, "POST"), identity)
                headers["X-CSRF-Token"] = csrf
                self.assertEqual(require_user(request(headers, "POST"), identity), identity)

    def test_limits_are_per_user_and_survive_another_connection(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(portal, "RATE_DB", Path(temporary) / "rate.db"), \
             patch.object(portal.time, "time", return_value=1000):
            self.assertTrue(portal.DeepSeekRateLimitMiddleware._reserve_query(17)[0])
            self.assertEqual(portal.DeepSeekRateLimitMiddleware._reserve_query(17)[:2], (False, 60))
            self.assertTrue(portal.DeepSeekRateLimitMiddleware._reserve_query(18)[0])
            with patch.object(portal.time, "time", return_value=1061):
                self.assertTrue(portal.DeepSeekRateLimitMiddleware._reserve_query(17)[0])

    def test_bounded_simbad_query_preserves_limit_and_escaping(self):
        client = SimpleNamespace(_reference_time_range="recent10", _simbad=Mock())
        client._simbad.query_tap.return_value = Table({
            "bibcode": ["test-reference"], "pub_year": [2026],
            "journal": ["test"], "title": ["test"], "obj_freq": [1],
        })
        rows = portal._bounded_reference_query(client, "Test's star", "")
        query = client._simbad.query_tap.call_args.args[0]
        self.assertIn("TOP 100", query)
        self.assertIn("Test''s star", query)
        self.assertIn('"r"."year" >=', query)
        self.assertEqual(client._simbad.query_tap.call_args.kwargs["maxrec"], 100)
        self.assertEqual(rows[0]["bibcode"], "test-reference")
