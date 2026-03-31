from __future__ import annotations

from dataclasses import asdict
import json

import requests

from ..models import GaiaRecord, LiteratureWorkflow, MastRecord, PlanetRecord, SimbadRecord


class DeepSeekClient:

    _MAX_REFS_FOR_LLM = 180
    _CHUNK_SIZE = 30
    _MAX_CHUNKS = 6
    _MAX_CHUNK_SUMMARY_CHARS = 1200

    def __init__(self,
                 api_key: str,
                 base_url: str,
                 model: str,
                 timeout_sec: int = 45) -> None:
        self._api_key = api_key
        self._endpoint = f"{base_url}/chat/completions"
        self._model = model
        self._timeout_sec = timeout_sec

    def summarize(
        self,
        target: str,
        target_type: str,
        simbad: SimbadRecord | None,
        gaia: GaiaRecord | None,
        mast: MastRecord | None,
        planet: PlanetRecord | None,
        literature_workflow: LiteratureWorkflow | None,
    ) -> str:
        serialized_workflow = None
        if literature_workflow is not None:
            serialized_workflow = asdict(literature_workflow)

        compact_refs = self._compact_references([] if simbad is
                                                None else simbad.references)

        # Use map-reduce when references are large to avoid oversized request payloads.
        if len(compact_refs) > self._CHUNK_SIZE:
            try:
                return self._summarize_chunked(
                    target=target,
                    target_type=target_type,
                    simbad=simbad,
                    gaia=gaia,
                    mast=mast,
                    planet=planet,
                    literature_workflow=serialized_workflow,
                    compact_refs=compact_refs,
                )
            except Exception:
                # Fall back to single-shot path when chunked path fails.
                pass

        payload = self._build_payload(
            target=target,
            target_type=target_type,
            simbad=simbad,
            gaia=gaia,
            mast=mast,
            planet=planet,
            literature_workflow=serialized_workflow,
            references_for_llm=compact_refs,
        )

        return self._summarize_single_shot(payload)

    def _summarize_chunked(
        self,
        target: str,
        target_type: str,
        simbad: SimbadRecord | None,
        gaia: GaiaRecord | None,
        mast: MastRecord | None,
        planet: PlanetRecord | None,
        literature_workflow: dict[str, object] | None,
        compact_refs: list[dict[str, object]],
    ) -> str:
        chunks = self._chunk_references(compact_refs)
        chunk_notes: list[str] = []

        for index, chunk in enumerate(chunks, start=1):
            chunk_payload = {
                "target": target,
                "chunk_index": index,
                "chunk_total": len(chunks),
                "references": chunk,
            }
            system_prompt = ("你是天体物理研究助手。"
                             "请根据当前文献分块提炼关键信息，突出观测手段、研究主题、"
                             "物理结论、局限与不确定性。输出紧凑中文要点。")
            user_prompt = (
                "请基于以下 references 分块数据提炼要点。"
                "输出 5 行：\n"
                "1) 主要观测手段\n"
                "2) 主要研究主题\n"
                "3) 关键物理结论\n"
                "4) 局限/不确定性\n"
                "5) 建议后续检索关键词\n"
                "每行尽量简洁。\n\n"
                f"数据:\n{json.dumps(chunk_payload, ensure_ascii=False, indent=2)}"
            )
            chunk_text = self._chat(system_prompt=system_prompt,
                                    user_prompt=user_prompt,
                                    temperature=0.1)
            chunk_notes.append(chunk_text[:self._MAX_CHUNK_SUMMARY_CHARS])

        final_payload = self._build_payload(
            target=target,
            target_type=target_type,
            simbad=simbad,
            gaia=gaia,
            mast=mast,
            planet=planet,
            literature_workflow=literature_workflow,
            references_for_llm=[],
        )
        final_payload["chunk_summaries"] = chunk_notes
        final_payload["chunk_count"] = len(chunks)

        return self._summarize_single_shot(final_payload)

    def _summarize_single_shot(self, payload: dict[str, object]) -> str:
        system_prompt = (
            "你是天体物理研究助手。请根据给定数据库结果给出简明科研归纳，"
            "重点包括：目标识别、光谱型、距离和视差可信度、"
            "MAST观测覆盖（TIC/EPIC/KIC、mission总覆盖、JWST/HST）、"
            "以及基于references的文献工作流分析（先看keywords，再看title，最后看abstract），"
            "总结该目标已做过哪些观测、已开展哪些研究。"
            "和可能的观测价值。"
            "如果信息不足，明确说明不确定性。")

        user_prompt = (
            "请用中文输出，分成五段：\n"
            "1) 目标概况\n2) 关键物理量\n3) 已有观测工作\n4) 已有研究主题与局限\n5) 建议的后续检索/观测\n\n"
            f"数据:\n{json.dumps(payload, ensure_ascii=False, indent=2)}")

        return self._chat(system_prompt=system_prompt,
                          user_prompt=user_prompt,
                          temperature=0.2)

    def _chat(self, system_prompt: str, user_prompt: str,
              temperature: float) -> str:
        resp = requests.post(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model":
                self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    },
                ],
                "temperature":
                temperature,
            },
            timeout=self._timeout_sec,
        )
        if not resp.ok:
            body = resp.text.strip()
            body = body[:800] if body else "<empty>"
            raise RuntimeError(f"DeepSeek HTTP {resp.status_code}: {body}")

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("DeepSeek response has no choices")

        content = choices[0].get("message", {}).get("content")
        if not content:
            raise RuntimeError("DeepSeek response has empty content")
        return str(content).strip()

    def _build_payload(
        self,
        target: str,
        target_type: str,
        simbad: SimbadRecord | None,
        gaia: GaiaRecord | None,
        mast: MastRecord | None,
        planet: PlanetRecord | None,
        literature_workflow: dict[str, object] | None,
        references_for_llm: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "target":
            target,
            "target_type":
            target_type,
            "simbad":
            self._compact_simbad_payload(
                simbad=simbad,
                references_for_llm=references_for_llm,
            ),
            "gaia":
            None if gaia is None else asdict(gaia),
            "mast":
            None if mast is None else asdict(mast),
            "planet":
            None if planet is None else asdict(planet),
            "literature_workflow":
            literature_workflow,
        }

    def _chunk_references(
        self,
        references: list[dict[str, object]],
    ) -> list[list[dict[str, object]]]:
        capped = references[:self._CHUNK_SIZE * self._MAX_CHUNKS]
        return [
            capped[i:i + self._CHUNK_SIZE]
            for i in range(0, len(capped), self._CHUNK_SIZE)
        ]

    def _compact_references(
        self,
        references: list[dict[str, str | list[str]]],
    ) -> list[dict[str, object]]:
        compact_refs: list[dict[str, object]] = []
        for ref in references[:self._MAX_REFS_FOR_LLM]:
            keywords = ref.get("keywords")
            if isinstance(keywords, list):
                compact_keywords = [
                    str(item).strip() for item in keywords[:8]
                    if str(item).strip()
                ]
            else:
                compact_keywords = []

            abstract = str(ref.get("abstract") or "").strip()
            compact_refs.append({
                "bibcode":
                str(ref.get("bibcode") or "").strip(),
                "year":
                str(ref.get("year") or "").strip(),
                "journal":
                str(ref.get("journal") or "").strip(),
                "title":
                str(ref.get("title") or "").strip()[:300],
                "keywords":
                compact_keywords,
                "abstract_excerpt":
                abstract[:500],
            })

        return compact_refs

    @staticmethod
    def _compact_simbad_payload(
        simbad: SimbadRecord | None,
        references_for_llm: list[dict[str, object]],
    ) -> dict[str, object] | None:
        if simbad is None:
            return None

        return {
            "object_name": simbad.object_name,
            "object_type": simbad.object_type,
            "ra_deg": simbad.ra_deg,
            "dec_deg": simbad.dec_deg,
            "spectral_type": simbad.spectral_type,
            "identifiers": simbad.identifiers[:30],
            "references_count_total": len(simbad.references),
            "references_used_for_llm": references_for_llm,
        }
