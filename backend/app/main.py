from __future__ import annotations

import os
import socket

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .schemas import LightCurveAnalysisRequest, LightCurveArchiveDownloadRequest, LightCurveArchiveSearchRequest, LightCurveDatasetAnalysisRequest, LightCurveDatasetRequest, LiteratureResearchRequest, TargetQueryRequest
from .services.lightcurve_archive_service import LightCurveArchiveService
from .services.lightcurve_fits_service import LightCurveFitsService
from .services.lightcurve_service import analyze_light_curve
from .services.target_service import TargetSearchService


def _get_lan_ip() -> str | None:
    """获取本机局域网 IP — 遍历网卡找私有地址（192.168.x / 172.16-31.x / 10.x）"""
    import re
    import subprocess as _sp

    def _is_private(ip: str) -> bool:
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        a = int(parts[0])
        b = int(parts[1])
        return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192
                                                           and b == 168)

    for cmd in (["ifconfig"], ["ip", "addr"]):
        try:
            result = _sp.run(cmd, capture_output=True, text=True, timeout=3)
            for ip in re.findall(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout):
                if _is_private(ip):
                    return ip
        except (FileNotFoundError, _sp.TimeoutExpired):
            continue

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip if not ip.startswith("127.") else None
    except OSError:
        return None


def _build_cors_origins() -> list[str]:
    origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    lan_ip = _get_lan_ip()
    if lan_ip:
        origins.append(f"http://{lan_ip}:5173")
        origins.append(f"http://{lan_ip}:8000")
    return origins


app = FastAPI(
    title="Target Info Search API",
    version="0.1.0",
    description=
    "Interactive API for astronomy target lookup and light-curve analysis.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
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


# ---- 静态文件服务：Docker 部署时提供前端 SPA ----
_frontend_dist = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
if os.path.isdir(_frontend_dist):
    app.mount("/",
              StaticFiles(directory=_frontend_dist, html=True),
              name="frontend")
