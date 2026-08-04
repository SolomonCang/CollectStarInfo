from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from .services.workspace_service import SESSION_COOKIE, SessionIdentity, workspace


def current_user(request: Request) -> SessionIdentity:
    identity = workspace.get_session(request.cookies.get(SESSION_COOKIE))
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    return identity


def require_user(
    request: Request,
    identity: SessionIdentity = Depends(current_user),
) -> SessionIdentity:
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or not secrets_equal(supplied, identity.csrf_token):
            raise HTTPException(status_code=403, detail="CSRF 校验失败")
    if identity.must_change_password and request.url.path not in {
        "/api/auth/change-password", "/api/auth/logout",
    }:
        raise HTTPException(status_code=403, detail="请先修改临时密码")
    return identity


def require_admin(identity: SessionIdentity = Depends(require_user)) -> SessionIdentity:
    if not identity.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return identity


def secrets_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode(), right.encode())
