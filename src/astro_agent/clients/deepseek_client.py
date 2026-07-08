from __future__ import annotations

from dataclasses import asdict
import json
import re

import requests

from ..models import GaiaRecord, LiteratureWorkflow, MastRecord, PlanetRecord, SimbadRecord


class DeepSeekClient:

    _MAX_REFS_FOR_LLM = 180
    _CHUNK_SIZE = 30
    _MAX_CHUNKS = 6
    _MAX_CHUNK_SUMMARY_CHARS = 1200
    _MAX_RESEARCH_REFS = 80

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
        literature_references: list[dict[str, str | list[str]]] | None,
        literature_workflow: LiteratureWorkflow | None,
    ) -> str:
        serialized_workflow = None
        if literature_workflow is not None:
            serialized_workflow = asdict(literature_workflow)

        if literature_references is None:
            literature_references = [] if simbad is None else simbad.references
        compact_refs = self._compact_references(literature_references)

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

    def research_literature(
        self,
        target: str,
        target_type: str,
        references: list[dict[str, str | list[str]]],
        literature_workflow: dict[str, object] | None = None,
        focus_question: str | None = None,
        prescreen_keywords: bool = True,
    ) -> dict[str, object]:
        effective_keywords: list[str] = []
        if prescreen_keywords:
            try:
                focus_keywords = self._generate_focus_keywords(
                    target=target,
                    target_type=target_type,
                    focus_question=focus_question,
                )
            except Exception:
                focus_keywords = self._fallback_focus_keywords(focus_question)
            filtered_references, effective_keywords = self._filter_references_by_keywords(
                references=references,
                keywords=focus_keywords,
            )
            references_for_research = (filtered_references
                                       if filtered_references else references)
        else:
            references_for_research = references
        references_for_research = references_for_research[:self.
                                                          _MAX_RESEARCH_REFS]
        compact_refs = self._number_references(
            self._compact_references(references_for_research))
        payload: dict[str, object] = {
            "target":
            target,
            "target_type":
            target_type,
            "reference_count_total":
            len(references),
            "reference_count_after_prescreen":
            (len(filtered_references)
             if prescreen_keywords else len(references)),
            "focus_keywords":
            effective_keywords,
            "references_used_for_llm":
            compact_refs,
            "literature_workflow":
            literature_workflow,
            "focus_question":
            focus_question or "",
        }

        if len(compact_refs) > self._CHUNK_SIZE:
            chunk_summaries: list[str] = []
            for index, chunk in enumerate(self._chunk_references(compact_refs),
                                          start=1):
                chunk_payload = {
                    "target": target,
                    "chunk_index": index,
                    "references": chunk,
                    "focus_question": focus_question or "",
                }
                chunk_text = self._chat(
                    system_prompt=("你是天体物理文献调研助手。请只根据给定 references 分块做证据提炼，"
                                   "不要编造文献中没有的信息。"),
                    user_prompt=
                    ("请按以下结构用中文压缩当前文献分块：\n"
                     "1) 观测数据/仪器\n2) 目标物理参数或现象\n3) 时间域/活动性结论\n"
                     "4) 仍不清楚的问题\n5) 值得继续追的 ref_id/bibcode 或关键词\n"
                     "涉及具体论文时必须使用方括号编号引用，例如 [3] 或 [2, 5]。"
                     "方括号中只能出现 ref_id 数字，禁止把 bibcode 放入方括号。\n\n"
                     f"数据:\n{json.dumps(chunk_payload, ensure_ascii=False, indent=2)}"
                     ),
                    temperature=0.1,
                )
                chunk_summaries.append(
                    chunk_text[:self._MAX_CHUNK_SUMMARY_CHARS])
            payload["references_used_for_llm"] = []
            payload["chunk_summaries"] = chunk_summaries

        system_prompt = ("你是天体物理文献调研助手，任务是基于目标 references 做可追溯的研究现状分析。"
                         "必须区分已经有文献证据的结论、推测性解释和仍需检索确认的信息；"
                         "不要虚构论文、数值或结论。")
        user_prompt = (
            "请用中文输出结构化文献调研报告，包含：\n"
            "1) 研究主题地图：按主题归纳已有工作\n"
            "2) 观测资料地图：列出涉及的观测方式、任务或仪器\n"
            "3) 关键结论：只写 references 支持的结论\n"
            "4) 与光变曲线/活动性/周期相关的信息\n"
            "5) 缺口与不确定性\n"
            "6) 下一步检索关键词和优先阅读 bibcode\n"
            "如用户给出 focus_question，请优先回答该问题。\n"
            "正文中涉及具体论文时必须使用方括号数字引用，例如 [1] 或 [2, 4]；"
            "引用数字只能来自 references_used_for_llm 或 chunk_summaries 中的 ref_id。"
            "禁止使用 [2022A&A...] 这类 bibcode 方括号引用；bibcode 只能在正文普通文字中出现，"
            "真正引用必须是纯数字方括号。"
            "不要在正文后生成参考文献列表，系统会在报告下方渲染可点击 ADS 参考文献区。\n\n"
            f"数据:\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
        report = self._chat(system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            temperature=0.15)
        report = self._replace_bibcode_citations(report, compact_refs)
        cited_ids = self._extract_cited_ref_ids(report)
        if cited_ids:
            report_references = [
                ref for ref in compact_refs if ref.get("ref_id") in cited_ids
            ]
        else:
            report_references = compact_refs
        return {
            "report":
            report,
            "focus_keywords":
            effective_keywords,
            "reference_count_total":
            len(references),
            "reference_count_after_prescreen":
            (len(filtered_references)
             if prescreen_keywords else len(references)),
            "reference_count_used":
            len(compact_refs),
            "report_references":
            report_references,
        }

    def _generate_focus_keywords(
        self,
        target: str,
        target_type: str,
        focus_question: str | None,
    ) -> list[str]:
        question = (focus_question or "").strip()
        if not question:
            return []
        payload = {
            "target": target,
            "target_type": target_type,
            "focus_question": question,
        }
        text = self._chat(
            system_prompt=("你是天体物理文献检索助手。请把用户的调研重点扩展为用于"
                           "title/abstract/keywords 预筛选的英文关键词和缩写。"),
            user_prompt=(
                "只输出 JSON，不要解释。格式为："
                "{\"keywords\":[\"keyword\", \"synonym\"]}。"
                "关键词应包含任务/仪器缩写、全称、常见模式名和相关主题词，"
                "数量控制在 6 到 16 个。\n\n"
                f"数据:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"),
            temperature=0.0,
        )
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, flags=re.S)
            parsed = json.loads(match.group(0)) if match else {}
        raw_keywords = parsed.get("keywords") if isinstance(parsed,
                                                            dict) else []
        keywords: list[str] = []
        for item in raw_keywords:
            keyword = str(item).strip()
            if keyword and keyword.casefold() not in {
                    existing.casefold()
                    for existing in keywords
            }:
                keywords.append(keyword)
        return keywords[:16]

    @staticmethod
    def _fallback_focus_keywords(focus_question: str | None) -> list[str]:
        question = (focus_question or "").strip()
        if not question:
            return []
        keywords: list[str] = []
        for value in re.findall(r'[A-Za-z][A-Za-z0-9+_.-]{2,}', question):
            if value.casefold() not in {
                    keyword.casefold()
                    for keyword in keywords
            }:
                keywords.append(value)
        return keywords[:8]

    def _filter_references_by_keywords(
        self,
        references: list[dict[str, str | list[str]]],
        keywords: list[str],
    ) -> tuple[list[dict[str, str | list[str]]], list[str]]:
        if not keywords:
            return references, []
        lowered_keywords = [keyword.casefold() for keyword in keywords]
        reference_texts = [
            self._reference_search_text(reference) for reference in references
        ]
        keyword_counts = {
            keyword: sum(1 for text in reference_texts if keyword in text)
            for keyword in lowered_keywords
        }
        max_broad_matches = max(12, min(120, len(references) // 10))
        effective_pairs = [
            (original, lowered)
            for original, lowered in zip(keywords, lowered_keywords)
            if 0 < keyword_counts.get(lowered, 0) <= max_broad_matches
        ]
        if not effective_pairs:
            effective_pairs = [
                (original, lowered)
                for original, lowered in zip(keywords, lowered_keywords)
                if keyword_counts.get(lowered, 0) > 0
            ]

        scored_references: list[tuple[float, int, dict[str,
                                                       str | list[str]]]] = []
        for index, (reference,
                    text) in enumerate(zip(references, reference_texts)):
            score = 0.0
            for _, keyword in effective_pairs:
                if keyword in text:
                    score += 1.0 / max(1, keyword_counts.get(keyword, 1))
            if score > 0:
                scored_references.append((score, index, reference))
        scored_references.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored_references
                ], [keyword for keyword, _ in effective_pairs]

    @staticmethod
    def _reference_search_text(reference: dict[str, str | list[str]]) -> str:
        keyword_values = reference.get("keywords")
        keyword_text = ""
        if isinstance(keyword_values, list):
            keyword_text = " ".join(str(item) for item in keyword_values)
        text = " ".join(
            str(reference.get(key) or "")
            for key in ("bibcode", "year", "journal", "title", "abstract"))
        return f"{text} {keyword_text}".casefold()

    @staticmethod
    def _number_references(
        references: list[dict[str, object]], ) -> list[dict[str, object]]:
        numbered: list[dict[str, object]] = []
        for index, reference in enumerate(references, start=1):
            item = dict(reference)
            item["ref_id"] = index
            numbered.append(item)
        return numbered

    @staticmethod
    def _extract_cited_ref_ids(report: str) -> set[int]:
        cited: set[int] = set()
        for group in re.findall(r'\[([0-9,\s]+)\]', report):
            for value in re.findall(r'\d+', group):
                cited.add(int(value))
        return cited

    @staticmethod
    def _replace_bibcode_citations(
        report: str,
        references: list[dict[str, object]],
    ) -> str:
        bibcode_to_id = {
            str(reference.get("bibcode") or ""): reference.get("ref_id")
            for reference in references
            if reference.get("bibcode") and reference.get("ref_id")
        }

        def replace(match: re.Match[str]) -> str:
            content = match.group(1).strip()
            parts = [part.strip() for part in content.split(",")]
            ref_ids: list[str] = []
            for part in parts:
                ref_id = bibcode_to_id.get(part)
                if ref_id is None:
                    return match.group(0)
                ref_ids.append(str(ref_id))
            return f"[{', '.join(ref_ids)}]"

        return re.sub(r'\[([^\[\]]*[A-Za-z][^\[\]]*)\]', replace, report)

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
