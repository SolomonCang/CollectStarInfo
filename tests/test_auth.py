from __future__ import annotations

import unittest

from fastapi import HTTPException
from starlette.requests import Request

from backend.app.auth import require_admin, require_user
from backend.app.services.workspace_service import SessionIdentity


def request(method: str, csrf: str | None = None) -> Request:
    headers = [] if csrf is None else [(b"x-csrf-token", csrf.encode())]
    return Request({
        "type": "http",
        "method": method,
        "path": "/api/targets/query",
        "headers": headers,
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1),
        "scheme": "http",
    })


class AuthorizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.user = SessionIdentity("u1", "alice", "user", False, "csrf-secret")
        self.admin = SessionIdentity("a1", "admin", "admin", False, "csrf-admin")

    def test_csrf_is_required_for_writes(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            require_user(request("POST"), self.user)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(require_user(request("POST", "csrf-secret"), self.user), self.user)
        self.assertEqual(require_user(request("GET"), self.user), self.user)

    def test_admin_role_is_required(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            require_admin(self.user)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(require_admin(self.admin), self.admin)


if __name__ == "__main__":
    unittest.main()
