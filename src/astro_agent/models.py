from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SimbadRecord:
    object_name: str
    object_type: str | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None
    spectral_type: str | None = None
    gaia_source_id: str | None = None
    gaia_gmag: float | None = None
    gaia_parallax_mas: float | None = None
    gaia_parallax_error_mas: float | None = None
    gaia_distance_pc: float | None = None
    gaia_distance_error_pc: float | None = None
    identifiers: list[str] = field(default_factory=list)
    references: list[dict[str, str | list[str]]] = field(default_factory=list)


@dataclass
class GaiaRecord:
    source_id: str | None = None
    gmag: float | None = None
    parallax_mas: float | None = None
    parallax_error_mas: float | None = None
    distance_pc: float | None = None
    distance_error_pc: float | None = None


@dataclass
class MastRecord:
    tic_ids: list[str] = field(default_factory=list)
    epic_ids: list[str] = field(default_factory=list)
    kic_ids: list[str] = field(default_factory=list)
    mission_observations: dict[str, int] = field(default_factory=dict)
    mission_time_info: dict[str, str] = field(default_factory=dict)
    total_mission_observations: int = 0
    region_radius_deg: float | None = None
    jwst_observations: int = 0
    hst_observations: int = 0


@dataclass
class PlanetRecord:
    planet_name: str
    host_name: str | None = None
    orbital_period_days: float | None = None
    radius_earth: float | None = None
    mass_earth: float | None = None
    semi_major_axis_au: float | None = None
    equilibrium_temp_k: float | None = None
    insolation_flux_earth: float | None = None
    discovery_method: str | None = None
    discovery_year: int | None = None
    discovery_facility: str | None = None


@dataclass
class LiteratureCategorySummary:
    category: str
    count: int = 0
    evidence_by_source: dict[str, int] = field(default_factory=dict)
    sample_references: list[str] = field(default_factory=list)


@dataclass
class LiteratureWorkflow:
    analysis_order: list[str] = field(default_factory=lambda: [
        "keywords",
        "title",
        "abstract",
    ])
    min_obj_freq: int = 0
    total_references: int = 0
    references_analyzed: int = 0
    focus_target: str | None = None
    reference_sources: dict[str, int] = field(default_factory=dict)
    observations: list[LiteratureCategorySummary] = field(default_factory=list)
    research_topics: list[LiteratureCategorySummary] = field(
        default_factory=list)
    overview: str | None = None


@dataclass
class TargetResult:
    target: str
    input_kind: str = "name"
    resolved_target: str | None = None
    target_type: str = "unknown"
    simbad: SimbadRecord | None = None
    gaia: GaiaRecord | None = None
    mast: MastRecord | None = None
    planet: PlanetRecord | None = None
    literature_workflow: LiteratureWorkflow | None = None
    summary: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["query_target"] = payload.pop("target")
        return payload
