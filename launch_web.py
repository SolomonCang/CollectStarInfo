from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
BACKEND_APP = "backend.app.main:app"


def get_lan_ip() -> str | None:
    """获取本机局域网 IP — 遍历网卡找私有地址（192.168.x / 172.16-31.x / 10.x）"""
    import re
    import socket

    def _is_private(ip: str) -> bool:
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        a = int(parts[0])
        b = int(parts[1])
        return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192
                                                           and b == 168)

    # 优先用 ifconfig / ip addr 解析
    for cmd in (["ifconfig"], ["ip", "addr"]):
        try:
            result = subprocess.run(cmd,
                                    capture_output=True,
                                    text=True,
                                    timeout=3)
            for ip in re.findall(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout):
                if _is_private(ip):
                    return ip
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    # 兜底: UDP 连接到公网 DNS 获取默认路由网卡 IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip if not ip.startswith("127.") else None
    except OSError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=
        "Start the Target Info Search backend and frontend, then open the web UI."
    )
    parser.add_argument("--docker",
                        action="store_true",
                        help="Use Docker Compose instead of local dev mode")
    parser.add_argument("--backend-host", default="0.0.0.0")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-host", default="0.0.0.0")
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--no-open",
                        action="store_true",
                        help="Do not open the browser automatically")
    parser.add_argument("--install-frontend",
                        action="store_true",
                        help="Run npm install before starting the frontend")
    return parser


def project_python() -> str:
    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def require_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"Required executable not found: {name}")
    return executable


def stream_output(process: subprocess.Popen[str], label: str) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        print(f"[{label}] {line}", end="")


def start_process(command: list[str], cwd: Path, env: dict[str, str],
                  label: str) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    thread = threading.Thread(target=stream_output,
                              args=(process, label),
                              daemon=True)
    thread.start()
    return process


def wait_for_url(url: str, label: str, timeout_sec: int = 60) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    print(f"[{label}] ready: {url}")
                    return
        except (URLError, ConnectionResetError, ConnectionRefusedError,
                TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {label}: {url}")


def terminate(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()


def maybe_install_frontend(npm: str, install_frontend: bool) -> None:
    node_modules = FRONTEND_DIR / "node_modules"
    if node_modules.exists() and not install_frontend:
        return
    print("[frontend] installing dependencies with npm install")
    subprocess.run([npm, "install"], cwd=str(FRONTEND_DIR), check=True)


def stop_docker_services() -> None:
    """关闭已有的 Docker Compose 服务，释放端口"""
    compose_file = ROOT / "docker-compose.yml"
    if not compose_file.exists():
        return
    docker = shutil.which("docker")
    if docker is None:
        return
    # 检查是否有运行的容器
    result = subprocess.run(
        [docker, "compose", "-f",
         str(compose_file), "ps", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True)
    if result.stdout.strip():
        print("[docker] stopping existing services ...")
        subprocess.run([docker, "compose", "-f",
                        str(compose_file), "down"],
                       cwd=str(ROOT),
                       check=False)
        print("[docker] previous services stopped")


def kill_port_process(port: int) -> None:
    """强制释放指定端口（杀掉占用进程）"""
    import platform
    system = platform.system()
    try:
        if system == "Darwin" or system == "Linux":
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5
            )
            pids = result.stdout.strip().split()
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    print(f"[port] killed pid {pid} on port {port}")
                except (ProcessLookupError, PermissionError):
                    pass
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def run_docker_mode(port: int, open_browser: bool) -> int:
    """Docker Compose 模式：构建镜像、启动容器、等待就绪"""
    docker = require_executable("docker")
    compose_file = ROOT / "docker-compose.yml"

    # 1. 先停止旧服务
    stop_docker_services()

    # 2. 如果前端未构建，先构建
    dist_dir = FRONTEND_DIR / "dist"
    if not dist_dir.exists():
        print("[docker] building frontend ...")
        npm = require_executable("npm")
        subprocess.run([npm, "run", "build"],
                       cwd=str(FRONTEND_DIR),
                       check=True)

    # 3. 构建并启动
    print("[docker] building image ...")
    subprocess.run([docker, "compose", "-f",
                    str(compose_file), "build"],
                   cwd=str(ROOT),
                   check=True)

    print("[docker] starting container ...")
    subprocess.run([docker, "compose", "-f",
                    str(compose_file), "up", "-d"],
                   cwd=str(ROOT),
                   check=True)

    # 4. 等待就绪
    backend_url = f"http://127.0.0.1:{port}"
    wait_for_url(f"{backend_url}/api/health", "docker")

    print(f"[docker] open: {backend_url}")
    if open_browser:
        webbrowser.open(backend_url)

    print(
        "[docker] service is running. Press Ctrl+C to stop (container stays in background)."
    )
    print(f"[docker] 手动停止: docker compose down")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[docker] container is still running in background.")
        print(f"[docker] 手动停止: cd {ROOT} && docker compose down")
        return 0

    return 0


def main() -> int:
    args = build_parser().parse_args()

    # ---- 启动前先释放端口 ----
    stop_docker_services()
    kill_port_process(args.backend_port)
    kill_port_process(args.frontend_port)

    # ---- Docker 模式 ----
    if args.docker:
        open_browser = not args.no_open
        return run_docker_mode(args.backend_port, open_browser)

    # ---- 本地开发模式 ----
    npm = require_executable("npm")
    maybe_install_frontend(npm, args.install_frontend)

    backend_url = f"http://{args.backend_host}:{args.backend_port}"
    frontend_url = f"http://{args.frontend_host}:{args.frontend_port}"

    # 健康检查始终用 127.0.0.1，因为 0.0.0.0 只能绑定不能连接
    check_backend_url = f"http://127.0.0.1:{args.backend_port}"
    check_frontend_url = f"http://127.0.0.1:{args.frontend_port}"

    env = os.environ.copy()
    # VITE_API_BASE: 内网访问时用 LAN IP，本机访问用 localhost
    api_base = check_backend_url
    if args.backend_host == "0.0.0.0":
        lan_ip = get_lan_ip()
        if lan_ip:
            api_base = f"http://{lan_ip}:{args.backend_port}"
            print(f"[web] LAN IP detected: {lan_ip}")

    frontend_env = env | {"VITE_API_BASE": api_base}

    processes: list[subprocess.Popen[str]] = []
    try:
        backend = start_process(
            [
                project_python(),
                "-m",
                "uvicorn",
                BACKEND_APP,
                "--host",
                args.backend_host,
                "--port",
                str(args.backend_port),
            ],
            cwd=ROOT,
            env=env,
            label="backend",
        )
        frontend = start_process(
            [
                npm, "run", "dev", "--", "--host", args.frontend_host,
                "--port",
                str(args.frontend_port)
            ],
            cwd=FRONTEND_DIR,
            env=frontend_env,
            label="frontend",
        )
        processes.extend([backend, frontend])

        wait_for_url(f"{check_backend_url}/api/health", "backend")
        wait_for_url(check_frontend_url, "frontend")

        print(f"[web] open: {check_frontend_url}")
        if not args.no_open:
            webbrowser.open(check_frontend_url)

        print("[web] services are running. Press Ctrl+C to stop.")
        while all(process.poll() is None for process in processes):
            time.sleep(1)

        for process in processes:
            if process.returncode not in (None, 0):
                return process.returncode
        return 0
    except KeyboardInterrupt:
        print("\n[web] stopping services")
        return 0
    finally:
        terminate(processes)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    raise SystemExit(main())
