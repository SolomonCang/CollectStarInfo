from __future__ import annotations

from typing import Any

from .clients.deepseek_client import DeepSeekClient
from .clients.gaia_client import GaiaClient
from .clients.mast_client import MastClient
from .clients.simbad_client import SimbadClient
from .models import LiteratureCategorySummary, LiteratureWorkflow, TargetResult

_ANALYSIS_ORDER = ("keywords", "title", "abstract")

_OBSERVATION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Optical photometry",
        (
            "photometry",
            "photometric",
            "light curve",
            "lightcurve",
            "optical variability",
            "tess",
            "kepler",
            "k2",
            "superwasp",
            "optical follow-up",
        ),
    ),
    (
        "Optical spectroscopy",
        (
            "spectroscopy",
            "spectroscopic",
            "spectra",
            "spectrum",
            "echelle",
            "radial velocity",
            "radial velocities",
            "h alpha",
            "h{alpha}",
            "line-by-line",
        ),
    ),
    (
        "X-ray and EUV observations",
        (
            "x-ray",
            "xray",
            "xmm",
            "xmm-newton",
            "chandra",
            "rosat",
            "swift",
            "euv",
            "extreme uv",
        ),
    ),
    (
        "Ultraviolet observations",
        (
            "ultraviolet",
            "far-ultraviolet",
            "uv",
            "fuv",
            "hst",
            "hubble",
        ),
    ),
    (
        "Radio observations",
        (
            "radio",
            "continuum: stars",
            "vla",
            "fast observations",
            "millimeter",
            "first survey",
            "radio bursts",
        ),
    ),
    (
        "Gamma-ray observations",
        (
            "gamma-ray",
            "gamma ray",
            "fermi",
            "lat detection",
            "gev",
        ),
    ),
    (
        "Infrared observations",
        (
            "infrared",
            "near-ir",
            "near ir",
            "2mass",
            "j band",
            "k band",
        ),
    ),
    (
        "Astrometry and survey catalog data",
        (
            "astrometry",
            "parallax",
            "proper motion",
            "gaia",
            "catalog",
            "catalogue",
            "survey",
            "census",
        ),
    ),
    (
        "High-resolution imaging and multiplicity",
        (
            "adaptive optics",
            "speckle",
            "coronagraphic",
            "companion",
            "binary",
            "multiplicity",
            "orbit",
            "orbital",
        ),
    ),
)

_RESEARCH_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Stellar flares and activity",
        (
            "flare",
            "superflare",
            "activity",
            "chromospheric",
            "coronal",
        ),
    ),
    (
        "Magnetic fields and starspots",
        (
            "magnetic",
            "dynamo",
            "starspot",
            "spotted",
            "spotting",
            "polarimetric",
        ),
    ),
    (
        "Rotation and activity relation",
        (
            "rotation",
            "rotational",
            "rotator",
            "spin-down",
            "rossby",
            "vsini",
        ),
    ),
    (
        "Binarity and companions",
        (
            "binary",
            "binaries",
            "companion",
            "companions",
            "multiple",
            "multiplicity",
            "orbit",
        ),
    ),
    (
        "High-energy emission",
        (
            "x-ray",
            "gamma-ray",
            "radio burst",
            "non-thermal",
            "hard x-ray",
        ),
    ),
    (
        "Time-domain variability",
        (
            "periodic",
            "variability",
            "variable",
            "light curve",
            "transient",
            "modulation",
        ),
    ),
    (
        "Stellar properties and classification",
        (
            "spectral",
            "nearby star",
            "m dwarf",
            "red dwarf",
            "classification",
            "catalog",
            "census",
        ),
    ),
    (
        "Exoplanets and habitability",
        (
            "exoplanet",
            "planet",
            "habitability",
            "biosignature",
            "planetary",
        ),
    ),
)


class TargetInfoAgent:

    def __init__(
        self,
        gaia_cone_radius_arcsec: float = 5.0,
        mast_radius_deg: float = 0.02,
        simbad_reference_time_range: str = "all",
        literature_min_obj_freq: int = 3,
        deepseek_client: DeepSeekClient | None = None,
    ) -> None:
        self._simbad = SimbadClient(
            reference_time_range=simbad_reference_time_range, )
        self._gaia = GaiaClient(cone_radius_arcsec=gaia_cone_radius_arcsec)
        self._mast = MastClient(region_radius_deg=mast_radius_deg)
        self._literature_min_obj_freq = max(0, int(literature_min_obj_freq))
        self._deepseek = deepseek_client

    @staticmethod
    def _reference_obj_freq(reference: dict[str, Any]) -> int | None:
        value = reference.get("obj_freq")
        if value is None:
            return None

        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _filter_references_for_workflow(
        self,
        references: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self._literature_min_obj_freq <= 0:
            return references

        filtered: list[dict[str, Any]] = []
        for reference in references:
            obj_freq = self._reference_obj_freq(reference)
            if obj_freq is None or obj_freq < self._literature_min_obj_freq:
                continue
            filtered.append(reference)
        return filtered

    @staticmethod
    def _reference_text_by_source(reference: dict[str, Any]) -> dict[str, str]:
        keywords = reference.get("keywords")
        keyword_text = ""
        if isinstance(keywords, list):
            keyword_text = " ; ".join(
                str(item).strip() for item in keywords if str(item).strip())

        return {
            "keywords": keyword_text.lower(),
            "title": str(reference.get("title") or "").lower(),
            "abstract": str(reference.get("abstract") or "").lower(),
        }

    @staticmethod
    def _match_source(
        fields: dict[str, str],
        patterns: tuple[str, ...],
    ) -> str | None:
        for source in _ANALYSIS_ORDER:
            content = fields.get(source, "")
            if content and any(pattern in content for pattern in patterns):
                return source
        return None

    @staticmethod
    def _sample_reference_text(reference: dict[str, Any]) -> str:
        bibcode = str(reference.get("bibcode") or "N/A").strip()
        title = str(reference.get("title") or "").strip()
        if title:
            return f"{bibcode}: {title}"
        return bibcode

    def _summarize_categories(
        self,
        references: list[dict[str, Any]],
        definitions: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> list[LiteratureCategorySummary]:
        summaries: dict[str, LiteratureCategorySummary] = {}
        for reference in references:
            fields = self._reference_text_by_source(reference)
            sample = self._sample_reference_text(reference)
            for category, patterns in definitions:
                source = self._match_source(fields, patterns)
                if source is None:
                    continue
                summary = summaries.get(category)
                if summary is None:
                    summary = LiteratureCategorySummary(category=category)
                    summaries[category] = summary
                summary.count += 1
                summary.evidence_by_source[source] = (
                    summary.evidence_by_source.get(source, 0) + 1)
                if sample not in summary.sample_references and len(
                        summary.sample_references) < 5:
                    summary.sample_references.append(sample)

        return sorted(
            summaries.values(),
            key=lambda item: (-item.count, item.category),
        )

    @staticmethod
    def _compose_workflow_overview(workflow: LiteratureWorkflow) -> str:
        observation_summary = ", ".join(f"{item.category} ({item.count})"
                                        for item in workflow.observations[:5])
        research_summary = ", ".join(f"{item.category} ({item.count})"
                                     for item in workflow.research_topics[:5])

        observation_text = observation_summary or "no clear observation class"
        research_text = research_summary or "no clear research theme"
        filter_text = "without obj_freq filtering"
        if workflow.min_obj_freq > 0:
            filter_text = (
                f"with obj_freq >= {workflow.min_obj_freq} "
                f"({workflow.references_analyzed}/{workflow.total_references} refs kept)"
            )
        return ("Reference workflow prioritizes keywords, then title, then "
                f"abstract {filter_text}. "
                f"Likely observation coverage: {observation_text}. "
                f"Likely research coverage: {research_text}.")

    def _build_literature_workflow(
        self,
        references: list[dict[str, Any]],
    ) -> LiteratureWorkflow | None:
        if not references:
            return None

        filtered_references = self._filter_references_for_workflow(references)
        if not filtered_references:
            filtered_references = references

        observations = self._summarize_categories(filtered_references,
                                                  _OBSERVATION_PATTERNS)
        research_topics = self._summarize_categories(filtered_references,
                                                     _RESEARCH_PATTERNS)

        workflow = LiteratureWorkflow(
            min_obj_freq=self._literature_min_obj_freq,
            total_references=len(references),
            references_analyzed=len(filtered_references),
            observations=observations,
            research_topics=research_topics,
        )
        workflow.overview = self._compose_workflow_overview(workflow)
        return workflow

    def run_target(self, target: str, use_llm: bool = True) -> TargetResult:
        print(f"[target] {target}")
        print("[module] start SIMBAD")
        result = TargetResult(target=target)

        try:
            simbad = self._simbad.query(target)
            result.simbad = simbad
            if simbad is None:
                result.notes.append("SIMBAD query returned no match")
                print("[module] done SIMBAD (no match)")
            else:
                print("[module] done SIMBAD (ok)")
        except Exception as exc:
            result.notes.append(f"SIMBAD query failed: {exc}")
            simbad = None
            print(f"[module] done SIMBAD (failed: {exc})")

        print("[module] start Gaia")
        try:
            gaia = self._gaia.query_with_simbad_priority(simbad)
            result.gaia = gaia
            if gaia is None:
                result.notes.append("Gaia query returned no match")
                print("[module] done Gaia (no match)")
            else:
                print("[module] done Gaia (ok)")
        except Exception as exc:
            result.notes.append(f"Gaia query failed: {exc}")
            gaia = None
            print(f"[module] done Gaia (failed: {exc})")

        print("[module] start MAST")
        try:
            mast = self._mast.query(simbad)
            result.mast = mast
            if mast is None:
                result.notes.append("MAST query returned no match")
                print("[module] done MAST (no match)")
            else:
                print("[module] done MAST (ok)")
        except Exception as exc:
            result.notes.append(f"MAST query failed: {exc}")
            mast = None
            print(f"[module] done MAST (failed: {exc})")

        if simbad is not None:
            print("[module] start LiteratureWorkflow")
            result.literature_workflow = self._build_literature_workflow(
                simbad.references)
            print("[module] done LiteratureWorkflow")
        else:
            print("[module] skip LiteratureWorkflow (no SIMBAD record)")

        if use_llm and self._deepseek is not None:
            print("[module] start DeepSeek")
            try:
                result.summary = self._deepseek.summarize(
                    target,
                    simbad,
                    gaia,
                    mast,
                    result.literature_workflow,
                )
                print("[module] done DeepSeek (ok)")
            except Exception as exc:
                result.notes.append(f"DeepSeek summarize failed: {exc}")
                print(f"[module] done DeepSeek (failed: {exc})")
        elif not use_llm:
            print("[module] skip DeepSeek (disabled by --no-llm)")
        else:
            print("[module] skip DeepSeek (client not configured)")

        print("[target] completed")

        return result

    def run_batch(self,
                  targets: list[str],
                  use_llm: bool = True) -> list[TargetResult]:
        print(f"[batch] start total_targets={len(targets)}")
        results = [
            self.run_target(target, use_llm=use_llm) for target in targets
        ]
        print("[batch] completed")
        return results
