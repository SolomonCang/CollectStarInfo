from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .schemas import LightCurveAnalysisRequest, LightCurveArchiveDownloadRequest, LightCurveArchiveSearchRequest, LightCurveDatasetAnalysisRequest, LightCurveDatasetRequest, LiteratureResearchRequest, TargetQueryRequest
from .services.lightcurve_archive_service import LightCurveArchiveService
from .services.lightcurve_fits_service import LightCurveFitsService
from .services.lightcurve_service import analyze_light_curve
from .services.target_service import TargetSearchService

app = FastAPI(
    title="Target Info Search API",
    version="0.1.0",
    description=
    "Interactive API for astronomy target lookup and light-curve analysis.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

target_service = TargetSearchService()
lightcurve_archive_service = LightCurveArchiveService()
lightcurve_fits_service = LightCurveFitsService()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/targets/query")
async def query_target(request: TargetQueryRequest) -> dict:
    return await target_service.query_target(request)


@app.post("/api/literature/research")
async def research_literature(request: LiteratureResearchRequest) -> dict:
    return await target_service.research_literature(request)


@app.post("/api/lightcurves/analyze")
def analyze_lightcurve(request: LightCurveAnalysisRequest) -> dict:
    return analyze_light_curve(request)


@app.post("/api/lightcurves/search")
def search_lightcurves(request: LightCurveArchiveSearchRequest) -> dict:
    return lightcurve_archive_service.search(request)


@app.post("/api/lightcurves/download")
def download_lightcurves(request: LightCurveArchiveDownloadRequest) -> dict:
    result = lightcurve_archive_service.download(request)
    csv_result = lightcurve_fits_service.write_dataset_csv(
        LightCurveDatasetRequest(download_dir=result["download_dir"],
                                 quality_filter=True,
                                 max_points=100000))
    result["csv"] = csv_result
    return result


@app.get("/api/lightcurves/datasets")
def list_lightcurve_datasets(target: str | None = None) -> dict:
    return lightcurve_fits_service.list_datasets(target=target)


@app.post("/api/lightcurves/load")
def load_lightcurve_dataset(request: LightCurveDatasetRequest) -> dict:
    return lightcurve_fits_service.load_dataset(request)


@app.post("/api/lightcurves/analyze-dataset")
def analyze_lightcurve_dataset(
        request: LightCurveDatasetAnalysisRequest) -> dict:
    return lightcurve_fits_service.analyze_dataset(request)
