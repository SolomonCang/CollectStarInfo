#!/usr/bin/env python3
"""Start the production entry point on a temporary port with disposable data."""
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.request import urlopen


def main():
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temporary, socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        env = dict(os.environ, PYTHONPATH=str(repo),
                   WAREHOUSE_ROOT=temporary + "/warehouse",
                   WORKSPACE_DATABASE_URL="sqlite:///" + temporary + "/warehouse/db/target_info.sqlite",
                   PERSISTENCE_BACKEND="sqlite-warehouse", DEEPSEEK_API_KEY_FILE="/dev/null",
                   DEEPSEEK_RATE_LIMIT_DB=temporary + "/rate.db", XDG_CACHE_HOME=temporary + "/cache")
        process = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "backend.app.portal:app", "--host", "127.0.0.1",
            "--port", str(port), "--no-access-log",
        ], cwd=temporary, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            base = f"http://127.0.0.1:{port}"
            subprocess.run([sys.executable, str(repo / "scripts/check-health.py"),
                            "--url", base + "/api/health"], check=True)
            for path in ["/api/auth/me", "/api/catalog/stats"]:
                try:
                    urlopen(base + path, timeout=5)
                except HTTPError as error:
                    assert error.code == 401, (path, error.code)
                else:
                    raise RuntimeError("Protected endpoint accepted an unauthenticated request")
            with urlopen(base + "/", timeout=5) as response:
                html = response.read().decode()
            assets = re.findall(r'(?:src|href)="([^"]+\.(?:js|css))"', html)
            assert assets, "Frontend has no static assets"
            for asset in assets:
                with urlopen(base + asset.removeprefix("/apps/stars"), timeout=5) as response:
                    assert response.status == 200
            print("Native runtime smoke: health, static assets and authentication boundaries ok")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
