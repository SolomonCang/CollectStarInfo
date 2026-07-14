from __future__ import annotations

from pydantic import BaseModel, Field


class TargetQueryRequest(BaseModel):
    target: str = Field(min_length=1, description="Target name or coordinates")
    use_llm: bool = False
    force_refresh: bool = False


class LiteratureResearchRequest(BaseModel):
    target: str = Field(min_length=1)
    target_type: str = "unknown"
    references: list[dict] = Field(default_factory=list)
    literature_workflow: dict | None = None
    focus_question: str | None = None
    prescreen_keywords: bool = True


class LightCurveArchiveSearchRequest(BaseModel):
    target: str = Field(min_length=1)
    ra_deg: float | None = None
    dec_deg: float | None = None
    radius_deg: float = Field(default=0.02, gt=0, le=0.5)
    missions: list[str] = Field(
        default_factory=lambda: ["TESS", "Kepler", "K2"])
    max_products: int = Field(default=80, ge=1, le=500)
    force_refresh: bool = Field(
        default=False, description="Bypass the short-lived MAST search cache")


class LightCurveArchiveDownloadRequest(LightCurveArchiveSearchRequest):
    product_uris: list[str] = Field(default_factory=list)
    max_downloads: int = Field(default=10, ge=1, le=100)
    force: bool = Field(default=False, description="Force re-download even if an identical dataset already exists")


class LightCurvePoint(BaseModel):
    time: float
    flux: float
    flux_error: float | None = None


class DetrendOptions(BaseModel):
    enabled: bool = True
    method: str = Field(default="polynomial", pattern="^(none|polynomial)$")
    polynomial_order: int = Field(default=2, ge=0, le=5)
    gap_threshold: float | None = Field(
        default=None,
        ge=0,
        description="Minimum gap in days to split light curve into "
        "independent segments for detrending. None or 0 disables "
        "segmentation. Default 1.0 day works well for TESS/K2 sectors.")


class PeriodSearchOptions(BaseModel):
    enabled: bool = True
    min_period: float | None = Field(default=None, gt=0)
    max_period: float | None = Field(default=None, gt=0)
    samples_per_peak: int = Field(default=8, ge=2, le=50)


class LightCurveDatasetRequest(BaseModel):
    download_dir: str = Field(min_length=1)
    flux_column: str | None = None
    quality_filter: bool = True
    max_points: int = Field(default=5000, ge=100, le=100000)


class LightCurveDatasetAnalysisRequest(LightCurveDatasetRequest):
    detrend: DetrendOptions = Field(default_factory=DetrendOptions)
    period_search: PeriodSearchOptions = Field(
        default_factory=PeriodSearchOptions)


class LightCurveCacheVerifyRequest(BaseModel):
    deep: bool = Field(default=False, description="Verify stored SHA-256 checksums")
    repair: bool = Field(
        default=False, description="Mark invalid manifests so they cannot be reused")


class LightCurveCacheCleanupRequest(BaseModel):
    max_age_days: float | None = Field(default=None, gt=0)
    max_size_mb: float | None = Field(default=None, gt=0)
    dry_run: bool = True
    remove_unreferenced_products: bool = True


class LightCurveDatasetDeleteRequest(BaseModel):
    download_dir: str = Field(min_length=1)


class LightCurveAnalysisRequest(BaseModel):
    points: list[LightCurvePoint] = Field(min_length=3)
    detrend: DetrendOptions = Field(default_factory=DetrendOptions)
    period_search: PeriodSearchOptions = Field(
        default_factory=PeriodSearchOptions)


# ── Catalog / Data Manager ────────────────────────────────────────

class CatalogListRequest(BaseModel):
    entry_type: str | None = Field(default=None, description="Filter: target_result | lightcurve_dataset")
    source: str | None = Field(default=None, description="Filter by source substring")
    search: str | None = Field(default=None, description="Search in display_name, source, tags")
    tags: list[str] = Field(default_factory=list)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class CatalogBatchDeleteRequest(BaseModel):
    entry_ids: list[str] = Field(min_length=1, max_length=200)


class CatalogBatchExportRequest(BaseModel):
    entry_ids: list[str] = Field(min_length=1, max_length=200)
