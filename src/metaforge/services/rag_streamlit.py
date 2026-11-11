"""随主后端启动 / 停止 RAG Streamlit（供 Hub iframe 嵌入）。"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RAG_ROOT = _REPO_ROOT / "rag" / "langchain-agent"
_VENV_PYTHON = _REPO_ROOT / "metaforge-test-env" / "Scripts" / "python.exe"

_streamlit_proc: Optional[subprocess.Popen] = None


def _rag_python() -> str:
    custom = (os.getenv("RAG_PYTHON") or "").strip()
    if custom and Path(custom).is_file():
        return custom
    if _VENV_PYTHON.is_file():
        return str(_VENV_PYTHON)
    import sys

    return sys.executable


def streamlit_port() -> int:
    return int(os.getenv("RAG_STREAMLIT_PORT", "8501"))


def streamlit_url() -> str:
    host = (os.getenv("RAG_STREAMLIT_HOST") or "127.0.0.1").strip()
    return f"http://{host}:{streamlit_port()}"


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def streamlit_running() -> bool:
    global _streamlit_proc
    if _streamlit_proc is not None and _streamlit_proc.poll() is None:
        return True
    return _port_open("127.0.0.1", streamlit_port())


def start_streamlit() -> bool:
    """启动 Streamlit；若端口已被占用则视为已运行。"""
    global _streamlit_proc
    port = streamlit_port()
    if _port_open("127.0.0.1", port):
        return True
    if os.getenv("RAG_STREAMLIT_AUTOSTART", "1").strip().lower() in {"0", "false", "no"}:
        return False

    app_py = _RAG_ROOT / "app.py"
    if not app_py.is_file():
        return False

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["STREAMLIT_SERVER_HEADLESS"] = "true"

    _streamlit_proc = subprocess.Popen(
        [
            _rag_python(),
            "-m",
            "streamlit",
            "run",
            str(app_py),
            "--server.headless",
            "true",
            "--server.port",
            str(port),
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=str(_RAG_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 45
    while time.time() < deadline:
        if _streamlit_proc.poll() is not None:
            _streamlit_proc = None
            return False
        if _port_open("127.0.0.1", port):
            return True
        time.sleep(0.3)
    return _port_open("127.0.0.1", port)


def stop_streamlit() -> None:
    global _streamlit_proc
    if _streamlit_proc is None:
        return
    try:
        if _streamlit_proc.poll() is None:
            _streamlit_proc.terminate()
            try:
                _streamlit_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _streamlit_proc.kill()
    except Exception:
        pass
    _streamlit_proc = None
