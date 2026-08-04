from __future__ import annotations

import asyncio
import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError

from .auth import current_user, require_admin, require_user
from .schemas import (
    AdminUserCreateRequest,
    AdminUserUpdateRequest,
    ChangePasswordRequest,
    LlmProfileRequest,
    LoginRequest,
)
from .services.workspace_service import (
    SESSION_COOKIE,
    SESSION_TTL_DAYS,
    SessionIdentity,
    workspace,
)


router = APIRouter(prefix="/api")

PROVIDER_PRESETS = [
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "suggested_model": "deepseek-chat",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "suggested_model": "",
    },
    {
        "id": "custom",
        "label": "自定义 OpenAI 兼容接口",
        "base_url": "",
        "suggested_model": "",
    },
]


@router.post("/auth/login")
def login(payload: LoginRequest, response: Response) -> dict:
    try:
        token, identity = workspace.authenticate(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"},
        samesite="lax",
        path="/",
    )
    return {"user": identity.public()}


@router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    _: SessionIdentity = Depends(require_user),
) -> dict:
    workspace.delete_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "logged_out"}


@router.get("/auth/me")
def me(identity: SessionIdentity = Depends(current_user)) -> dict:
    return {"user": identity.public()}


@router.post("/auth/change-password")
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    identity: SessionIdentity = Depends(current_user),
) -> dict:
    if request.headers.get("X-CSRF-Token") != identity.csrf_token:
        raise HTTPException(status_code=403, detail="CSRF 校验失败")
    try:
        workspace.change_password(identity.user_id, payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "password_changed"}


@router.get("/admin/users")
def admin_list_users(_: SessionIdentity = Depends(require_admin)) -> dict:
    return {"users": workspace.list_users()}


@router.post("/admin/users")
def admin_create_user(
    payload: AdminUserCreateRequest,
    _: SessionIdentity = Depends(require_admin),
) -> dict:
    generated_password = None if payload.password else secrets.token_urlsafe(12)
    try:
        user = workspace.create_user(
            payload.username,
            payload.password or generated_password or "",
            role=payload.role,
            must_change_password=payload.must_change_password or bool(generated_password),
        )
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": user, "temporary_password": generated_password}


@router.patch("/admin/users/{user_id}")
def admin_update_user(
    user_id: str,
    payload: AdminUserUpdateRequest,
    identity: SessionIdentity = Depends(require_admin),
) -> dict:
    if user_id == identity.user_id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="不能禁用当前管理员账号")
    try:
        user, temporary = workspace.update_user(
            user_id,
            is_active=payload.is_active,
            reset_password=payload.reset_password,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="用户不存在") from exc
    return {"user": user, "temporary_password": temporary}


@router.get("/admin/migrations")
def admin_migrations(_: SessionIdentity = Depends(require_admin)) -> dict:
    return {"runs": workspace.migration_status()}


@router.get("/plugins/llm/profiles")
def list_llm_profiles(identity: SessionIdentity = Depends(require_user)) -> dict:
    return {
        "presets": PROVIDER_PRESETS,
        "profiles": workspace.list_profiles(identity.user_id),
    }


@router.post("/plugins/llm/profiles")
def create_llm_profile(
    payload: LlmProfileRequest,
    identity: SessionIdentity = Depends(require_user),
) -> dict:
    try:
        profile = workspace.save_profile(identity.user_id, payload.model_dump())
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"profile": profile}


@router.patch("/plugins/llm/profiles/{profile_id}")
def update_llm_profile(
    profile_id: str,
    payload: LlmProfileRequest,
    identity: SessionIdentity = Depends(require_user),
) -> dict:
    try:
        profile = workspace.save_profile(
            identity.user_id, payload.model_dump(), profile_id=profile_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在") from exc
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"profile": profile}


@router.delete("/plugins/llm/profiles/{profile_id}")
def delete_llm_profile(
    profile_id: str,
    identity: SessionIdentity = Depends(require_user),
) -> Response:
    try:
        workspace.delete_profile(identity.user_id, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在") from exc
    return Response(status_code=204)


@router.post("/plugins/llm/profiles/{profile_id}/test")
async def test_llm_profile(
    profile_id: str,
    identity: SessionIdentity = Depends(require_user),
) -> dict:
    try:
        profile = workspace.get_profile_secret(identity.user_id, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型配置不存在或未启用") from exc
    from astro_agent.clients.openai_compatible_client import OpenAICompatibleClient

    client = OpenAICompatibleClient(
        api_key=profile["api_key"], base_url=profile["base_url"],
        model=profile["model"], timeout_sec=profile["timeout_sec"],
    )
    started = time.monotonic()
    try:
        reply = await asyncio.to_thread(client.test_connection)
    except Exception as exc:
        detail = str(exc)
        secret = str(profile.get("api_key") or "")
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
        raise HTTPException(status_code=400, detail=f"连接测试失败：{detail}") from exc
    return {
        "status": "ok",
        "latency_ms": round((time.monotonic() - started) * 1000),
        "reply": reply[:80],
    }


@router.get("/plugins/llm/runs")
def list_llm_runs(
    target: str | None = Query(default=None),
    task_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    identity: SessionIdentity = Depends(require_user),
) -> dict:
    return {
        "runs": workspace.list_llm_runs(
            identity.user_id, target_name=target, task_type=task_type, limit=limit
        )
    }


@router.get("/plugins/llm/runs/{run_id}")
def get_llm_run(
    run_id: str,
    identity: SessionIdentity = Depends(require_user),
) -> dict:
    try:
        return {"run": workspace.get_llm_run(identity.user_id, run_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="运行记录不存在") from exc
