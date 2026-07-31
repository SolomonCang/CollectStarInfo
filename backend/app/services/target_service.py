from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

from fastapi import HTTPException

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

    def _build_agent(self, use_llm: bool) -> Any:
        from astro_agent.agent import TargetInfoAgent
        from astro_agent.clients.deepseek_client import DeepSeekClient

        deepseek_client = None
        if use_llm and self._settings.deepseek_api_key:
            deepseek_client = DeepSeekClient(
                api_key=self._settings.deepseek_api_key,
                base_url=self._settings.deepseek_base_url,
                model=self._settings.deepseek_model,
                timeout_sec=self._settings.timeout_sec,
            )

        return TargetInfoAgent(
            gaia_cone_radius_arcsec=self._settings.
            default_gaia_cone_radius_arcsec,
            mast_radius_deg=self._settings.default_mast_radius_deg,
            simbad_reference_time_range=self._settings.
            default_simbad_reference_time_range,
            literature_min_obj_freq=self._settings.
            default_literature_min_obj_freq,
            deepseek_client=deepseek_client,
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
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / f"{safe_target_filename(target)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        remote_path = persistence.save_target(target, payload)
        # Trigger a catalog rebuild so the new entry is visible immediately
        self._sync_catalog()
        return remote_path or str(path.relative_to(PROJECT_ROOT))

    def _sync_catalog(self) -> None:
        """Rebuild the unified catalog after writing new data."""
        try:
            from .catalog_service import _rebuild_catalog
            _rebuild_catalog()
        except Exception:
            pass  # catalog sync is best-effort; never fail the main request

    async def query_target(self, request: TargetQueryRequest) -> dict:
        target = request.target.strip()
        if not request.force_refresh:
            existing = self._load_existing_result(target)
            if existing is not None:
                return existing

        agent = self._build_agent(use_llm=request.use_llm)
        result = await asyncio.to_thread(agent.run_target, target,
                                         request.use_llm)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target": result.to_dict(),
            "source": "fresh",
        }
        payload["result_path"] = self._write_result(target, payload)
        return payload

    async def research_literature(self,
                                  request: LiteratureResearchRequest) -> dict:
        if not self._settings.deepseek_api_key:
            raise HTTPException(
                status_code=400,
                detail=
                "DeepSeek API key is not configured. Put it in DSAPI.key.",
            )

        from astro_agent.clients.deepseek_client import DeepSeekClient

        client = DeepSeekClient(
            api_key=self._settings.deepseek_api_key,
            base_url=self._settings.deepseek_base_url,
            model=self._settings.deepseek_model,
            timeout_sec=self._settings.timeout_sec,
        )
        research_result = await asyncio.to_thread(
            client.research_literature,
            request.target.strip(),
            request.target_type,
            request.references,
            request.literature_workflow,
            request.focus_question,
            request.prescreen_keywords,
        )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target": request.target.strip(),
            "reference_count": len(request.references),
            **research_result,
        }
