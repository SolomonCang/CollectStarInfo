from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from backend.app.paths import PROJECT_ROOT
from backend.app.auth import current_user as target_current_user
from backend.app.main import app
from backend.app.services.workspace_service import (
    SessionIdentity,
    utc_now,
    workspace,
)
from astro_agent.clients.simbad_client import SimbadClient, _find_col


def _bounded_reference_query(
    simbad_client: SimbadClient,
    target: str,
    object_name: str,
) -> list[dict]:
    """Fetch a useful bibliography subset without the unbounded keyword join."""
    candidates = [target]
    if object_name and object_name not in candidates:
        candidates.append(object_name)
    if object_name.upper().startswith("NAME "):
        without_prefix = object_name[5:].strip()
        if without_prefix and without_prefix not in candidates:
            candidates.append(without_prefix)

    for name in candidates:
        escaped = name.replace("'", "''")
        year_filter = ""
        if simbad_client._reference_time_range == "recent10":
            min_year = datetime.now(timezone.utc).year - 9
            year_filter = f' AND "r"."year" >= {min_year}'
        query = (
            'SELECT TOP 100 r.bibcode, "r"."year" AS pub_year, '
            "r.journal, r.title, h.obj_freq AS obj_freq "
            "FROM ident AS i "
            "JOIN has_ref AS h ON i.oidref = h.oidref "
            'JOIN ref AS "r" ON h.oidbibref = "r".oidbib '
            f"WHERE i.id = '{escaped}'"
            f"{year_filter} "
            "ORDER BY obj_freq DESC"
        )
        try:
            table = simbad_client._simbad.query_tap(query, maxrec=100)
        except Exception:
            continue
        if table is None or len(table) == 0:
            continue

        references: list[dict] = []
        for row in table:
            item: dict = {}
            for output_name, column_name in (
                ("bibcode", "bibcode"),
                ("year", "pub_year"),
                ("journal", "journal"),
                ("title", "title"),
                ("obj_freq", "obj_freq"),
            ):
                value = _find_col(row, column_name)
                if value is not None:
                    text = str(value).strip()
                    if text and text != "--":
                        item[output_name] = text
            if item:
                references.append(item)
        if references:
            return references
    return []


SimbadClient._query_references = _bounded_reference_query


RATE_DB = Path(
    os.environ.get(
        "DEEPSEEK_RATE_LIMIT_DB",
        str(PROJECT_ROOT / "data" / "deepseek-rate-limit.db"),
    )
)
RATE_WINDOW_SECONDS = 60
TRUST_MARKER_HEADER = "X-ResearchToolsHub-Authenticated"
PORTAL_USER_ID_HEADER = "X-Portal-User-Id"
PORTAL_USERNAME_HEADER = "X-Portal-Username"
PORTAL_ROLE_HEADER = "X-Portal-Role"
PORTAL_CSRF_HEADER = "X-Portal-Csrf"
PORTAL_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
PORTAL_ROLES = {"superadmin", "admin", "user"}


def _portal_identity(request: Request) -> tuple[int, str, str, str] | None:
    """Read identity headers that Nginx overwrites after auth_request succeeds."""
    if request.headers.get(TRUST_MARKER_HEADER) != "1":
        return None
    raw_user_id = request.headers.get(PORTAL_USER_ID_HEADER, "")
    username = request.headers.get(PORTAL_USERNAME_HEADER, "")
    role = request.headers.get(PORTAL_ROLE_HEADER, "")
    csrf = request.headers.get(PORTAL_CSRF_HEADER, "")
    if (
        not raw_user_id.isascii()
        or not raw_user_id.isdigit()
        or int(raw_user_id) <= 0
        or not PORTAL_USERNAME_RE.fullmatch(username)
        or role not in PORTAL_ROLES
        or len(csrf) < 32
        or len(csrf) > 256
    ):
        return None
    return int(raw_user_id), username.lower(), role, csrf


def _target_user_id(portal_user_id: int, username: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"https://researchtoolshub.local/users/{portal_user_id}/{username}",
        )
    )


def _ensure_target_user(
    portal_user_id: int,
    username: str,
    target_role: str,
) -> str:
    """Provision a passwordless local workspace owner for a portal account."""
    workspace.initialize()
    users = workspace.tables["users"]
    user_id = _target_user_id(portal_user_id, username)
    with workspace.connection() as connection:
        existing = connection.execute(
            sa.select(users).where(users.c.user_id == user_id)
        ).mappings().one_or_none()
        if existing is None:
            username_owner = connection.execute(
                sa.select(users).where(sa.func.lower(users.c.username) == username)
            ).mappings().one_or_none()
            if username_owner is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="查询工具中存在同名的独立账户，请联系管理员完成关联。",
                )
            now = utc_now()
            connection.execute(
                users.insert().values(
                    user_id=user_id,
                    username=username,
                    password_hash=workspace._passwords.hash(
                        secrets.token_urlsafe(48)
                    ),
                    role=target_role,
                    is_active=True,
                    must_change_password=False,
                    created_at=now,
                    updated_at=now,
                )
            )
        elif not existing["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="查询工具工作区已停用，请联系管理员。",
            )
        elif existing["username"].lower() != username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="门户账户与查询工具工作区的身份关联不一致。",
            )
        elif existing["role"] != target_role:
            connection.execute(
                users.update()
                .where(users.c.user_id == user_id)
                .values(role=target_role, updated_at=utc_now())
            )
    return user_id


def portal_current_user(request: Request) -> SessionIdentity:
    portal_identity = _portal_identity(request)
    if portal_identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请从科研科普平台登录后进入查询工具。",
        )
    portal_user_id, username, portal_role, portal_csrf = portal_identity
    target_role = "admin" if portal_role == "superadmin" else "user"
    user_id = _ensure_target_user(portal_user_id, username, target_role)
    scoped_csrf = hashlib.sha256(
        f"collectstarinfo\0{portal_user_id}\0{portal_csrf}".encode()
    ).hexdigest()
    return SessionIdentity(
        user_id=user_id,
        username=username,
        role=target_role,
        must_change_password=False,
        csrf_token=scoped_csrf,
    )


app.dependency_overrides[target_current_user] = portal_current_user


class DeepSeekRateLimitMiddleware(BaseHTTPMiddleware):
    async def _is_deepseek_request(self, request: Request) -> bool:
        if request.method != "POST":
            return False
        if request.url.path == "/api/literature/research":
            return True
        if request.url.path != "/api/targets/query":
            return False
        try:
            payload = json.loads(await request.body())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        return isinstance(payload, dict) and payload.get("use_llm") is True

    @staticmethod
    def _user_id_for_request(request: Request) -> int | None:
        identity = _portal_identity(request)
        return identity[0] if identity is not None else None

    @staticmethod
    def _reserve_query(user_id: int) -> tuple[bool, int, int]:
        RATE_DB.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        with sqlite3.connect(RATE_DB, timeout=5) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS deepseek_rate_limit (
                    user_id INTEGER PRIMARY KEY,
                    last_query_at REAL NOT NULL
                )
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT last_query_at
                FROM deepseek_rate_limit
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row is not None:
                remaining = RATE_WINDOW_SECONDS - (now - float(row[0]))
                if remaining > 0:
                    connection.rollback()
                    retry_after = max(1, math.ceil(remaining))
                    return False, retry_after, math.ceil(float(row[0]) + 60)
            connection.execute(
                """
                INSERT INTO deepseek_rate_limit (user_id, last_query_at)
                VALUES (?, ?)
                ON CONFLICT(user_id)
                DO UPDATE SET last_query_at = excluded.last_query_at
                """,
                (user_id, now),
            )
            connection.commit()
        return True, 0, math.ceil(now + RATE_WINDOW_SECONDS)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not await self._is_deepseek_request(request):
            return await call_next(request)

        user_id = self._user_id_for_request(request)
        if user_id is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "无法确认门户登录用户，请重新登录后再试。"},
            )

        allowed, retry_after, reset_at = self._reserve_query(user_id)
        common_headers = {
            "X-RateLimit-Limit": "1",
            "X-RateLimit-Window": str(RATE_WINDOW_SECONDS),
            "X-RateLimit-Reset": str(reset_at),
        }
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "DeepSeek 查询频率受限：每位用户每分钟只能查询一次，"
                        f"请在 {retry_after} 秒后重试。"
                    )
                },
                headers={
                    **common_headers,
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        for key, value in common_headers.items():
            response.headers[key] = value
        response.headers["X-RateLimit-Remaining"] = "0"
        return response


app.add_middleware(DeepSeekRateLimitMiddleware)
