from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

from fastapi import HTTPException

from ..services.workspace_service import SessionIdentity, workspace
from ..schemas import TargetQueryRequest
from ..schemas import LiteratureResearchRequest
from .persistence_service import persistence

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
from astro_agent.config import load_settings  # noqa: E402

RESULTS_DIR = PROJECT_ROOT / "results"


def safe_target_filename(target: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", target).strip()
    return safe or "unknown_target"


class TargetSearchService:

    def __init__(self) -> None:
        self._settings = load_settings()

    def _build_agent(self) -> Any:
        from astro_agent.agent import TargetInfoAgent

        return TargetInfoAgent(
            gaia_cone_radius_arcsec=self._settings.
            default_gaia_cone_radius_arcsec,
            mast_radius_deg=self._settings.default_mast_radius_deg,
            simbad_reference_time_range=self._settings.
            default_simbad_reference_time_range,
            literature_min_obj_freq=self._settings.
            default_literature_min_obj_freq,
            deepseek_client=None,
        )

    def _candidate_result_paths(self, target: str) -> list[Path]:
        safe_name = safe_target_filename(target)
        paths = [RESULTS_DIR / f"{safe_name}.json"]
        normalized_target = target.strip().casefold()
        if RESULTS_DIR.exists():
            for path in RESULTS_DIR.glob("*.json"):
                if path in paths:
                    continue
                if path.stem.casefold() == normalized_target:
                    paths.append(path)
        return paths

    def _load_existing_result(self, target: str) -> dict | None:
        stored = workspace.load_target(target)
        if stored is not None:
            return stored
        remote = persistence.load_target(target)
        if remote is not None:
            remote["source"] = "postgres-s3"
            return remote
        for path in self._candidate_result_paths(target):
            if not path.exists() or path.is_dir():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(payload, dict) and isinstance(
                    payload.get("target"), dict):
                payload["source"] = "results"
                payload["result_path"] = str(path.relative_to(PROJECT_ROOT))
                return payload
        return None

    def _write_result(self, target: str, payload: dict) -> str:
        path = workspace.save_target(target, payload, source=payload.get("source", "fresh"))
        persistence.save_target(target, payload)
        # Trigger a catalog rebuild so the new entry is visible immediately
        self._sync_catalog()
        return path

    def _sync_catalog(self) -> None:
        """Rebuild the unified catalog after writing new data."""
        try:
            from .catalog_service import _rebuild_catalog
            _rebuild_catalog()
        except Exception:
            pass  # catalog sync is best-effort; never fail the main request

    def _user_client(self, identity: SessionIdentity, profile_id: str | None) -> tuple[Any, dict[str, Any]]:
        try:
            profile = workspace.get_profile_secret(identity.user_id, profile_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=400,
                detail="尚未配置可用的大模型接口，请先前往插件中心添加配置。",
            ) from exc
        from astro_agent.clients.openai_compatible_client import OpenAICompatibleClient

        return OpenAICompatibleClient(
            api_key=profile["api_key"], base_url=profile["base_url"],
            model=profile["model"], timeout_sec=profile["timeout_sec"],
        ), profile

    @staticmethod
    def _safe_llm_error(error: Exception, profile: dict[str, Any]) -> str:
        message = str(error)
        secret = str(profile.get("api_key") or "")
        return message.replace(secret, "[REDACTED]") if secret else message

    @staticmethod
    def _summary_arguments(target: dict[str, Any]) -> tuple[Any, ...]:
        from astro_agent.models import (
            GaiaRecord, LiteratureCategorySummary, LiteratureWorkflow,
            MastRecord, PlanetRecord, SimbadRecord,
        )

        def construct(cls: Any, value: Any) -> Any:
            if not isinstance(value, dict):
                return None
            allowed = cls.__dataclass_fields__.keys()
            return cls(**{key: item for key, item in value.items() if key in allowed})

        workflow_data = target.get("literature_workflow")
        workflow = None
        if isinstance(workflow_data, dict):
            workflow_values = dict(workflow_data)
            workflow_values["observations"] = [
                construct(LiteratureCategorySummary, item)
                for item in workflow_values.get("observations", []) if isinstance(item, dict)
            ]
            workflow_values["research_topics"] = [
                construct(LiteratureCategorySummary, item)
                for item in workflow_values.get("research_topics", []) if isinstance(item, dict)
            ]
            workflow = construct(LiteratureWorkflow, workflow_values)
        simbad = construct(SimbadRecord, target.get("simbad"))
        references = target.get("literature_references") or (
            simbad.references if simbad is not None else []
        )
        return (
            target.get("resolved_target") or target.get("query_target") or "unknown",
            target.get("target_type") or "unknown",
            simbad,
            construct(GaiaRecord, target.get("gaia")),
            construct(MastRecord, target.get("mast")),
            construct(PlanetRecord, target.get("planet")),
            references,
            workflow,
        )

    async def _add_private_summary(
        self, payload: dict[str, Any], request: TargetQueryRequest,
        identity: SessionIdentity,
    ) -> dict[str, Any]:
        target = payload.get("target") or {}
        try:
            client, profile = self._user_client(identity, request.llm_profile_id)
        except HTTPException as exc:
            payload["llm_error"] = exc.detail
            return payload
        target_name = target.get("resolved_target") or target.get("query_target") or request.target
        run_id = workspace.start_llm_run(
            identity.user_id, target_name, "target_summary", profile,
            {
                "target": request.target,
                "source": payload.get("source"),
                "target_snapshot": target,
            },
        )
        try:
            summary = await asyncio.to_thread(client.summarize, *self._summary_arguments(target))
            target["summary"] = summary
            run = workspace.finish_llm_run(
                identity.user_id, run_id,
                {"summary": summary, "target": target_name},
            )
            payload["llm_run_id"] = run_id
            payload["llm_profile"] = run["profile"]
        except Exception as exc:
            error = self._safe_llm_error(exc, profile)
            workspace.finish_llm_run(identity.user_id, run_id, error=error)
            payload["llm_run_id"] = run_id
            payload["llm_error"] = f"大模型总结失败：{error}"
        return payload

    @staticmethod
    def _overlay_latest_private_summary(
        payload: dict[str, Any], identity: SessionIdentity,
    ) -> dict[str, Any]:
        target = payload.get("target") or {}
        target_name = target.get("resolved_target") or target.get("query_target")
        if not target_name:
            return payload
        runs = workspace.list_llm_runs(
            identity.user_id,
            target_name=str(target_name),
            task_type="target_summary",
            limit=20,
        )
        for item in runs:
            if item.get("status") != "complete":
                continue
            detail = workspace.get_llm_run(identity.user_id, item["id"])
            result = detail.get("result") or {}
            if result.get("summary"):
                target["summary"] = result["summary"]
                payload["llm_run_id"] = item["id"]
                payload["llm_profile"] = item.get("profile")
                break
        return payload

    async def query_target(
        self, request: TargetQueryRequest, identity: SessionIdentity,
    ) -> dict:
        target = request.target.strip()
        if not request.force_refresh:
            existing = self._load_existing_result(target)
            if existing is not None:
                payload = json.loads(json.dumps(existing, ensure_ascii=False))
                if isinstance(payload.get("target"), dict):
                    payload["target"]["summary"] = None
                if request.use_llm:
                    return await self._add_private_summary(payload, request, identity)
                return self._overlay_latest_private_summary(payload, identity)

        agent = self._build_agent()
        result = await asyncio.to_thread(agent.run_target, target, False)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target": result.to_dict(),
            "source": "fresh",
        }
        payload["result_path"] = self._write_result(target, payload)
        if request.use_llm:
            return await self._add_private_summary(payload, request, identity)
        return self._overlay_latest_private_summary(payload, identity)

    async def research_literature(
        self, request: LiteratureResearchRequest, identity: SessionIdentity,
    ) -> dict:
        client, profile = self._user_client(identity, request.llm_profile_id)
        run_id = workspace.start_llm_run(
            identity.user_id, request.target.strip(), "literature_research", profile,
            request.model_dump(),
        )
        try:
            research_result = await asyncio.to_thread(
                client.research_literature,
                request.target.strip(), request.target_type, request.references,
                request.literature_workflow, request.focus_question,
                request.prescreen_keywords,
            )
        except Exception as exc:
            error = self._safe_llm_error(exc, profile)
            workspace.finish_llm_run(identity.user_id, run_id, error=error)
            raise HTTPException(status_code=502, detail=f"大模型文献调研失败：{error}") from exc
        response = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target": request.target.strip(),
            "reference_count": len(request.references),
            "llm_run_id": run_id,
            **research_result,
        }
        workspace.finish_llm_run(identity.user_id, run_id, response)
        return response
