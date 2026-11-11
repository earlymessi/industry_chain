"""RAG langchain-agent 桥接：优先常驻 Worker，状态查询走快速本地路径。"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RAG_ROOT = _REPO_ROOT / "rag" / "langchain-agent"
_CHAT_CLI = _RAG_ROOT / "scripts" / "chat_cli.py"
_CHECK_CLI = _RAG_ROOT / "scripts" / "check_rag.py"
_KB_CLI = _RAG_ROOT / "scripts" / "kb_manage_cli.py"
_KB_DOCS_CLI = _RAG_ROOT / "scripts" / "kb_documents_cli.py"
_REF_PREVIEW_CLI = _RAG_ROOT / "scripts" / "reference_preview_cli.py"
_WORKER_CLI = _RAG_ROOT / "scripts" / "rag_worker.py"
_VENV_PYTHON = _REPO_ROOT / "metaforge-test-env" / "Scripts" / "python.exe"
_MANIFEST = _RAG_ROOT / "storage" / "knowledge_manifest.json"
_CHROMA_DIR = _RAG_ROOT / "storage" / "chroma_db"

_CHROMA_SQLITE = _CHROMA_DIR / "chroma.sqlite3"

_worker_lock = threading.Lock()
_worker_proc: Optional[subprocess.Popen] = None
_worker_ready = False


def _rag_python() -> str:
    custom = (os.getenv("RAG_PYTHON") or "").strip()
    if custom and Path(custom).is_file():
        return custom
    if _VENV_PYTHON.is_file():
        return str(_VENV_PYTHON)
    import sys

    return sys.executable


def _load_rag_dotenv() -> None:
    env_path = _RAG_ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except Exception:
        pass


def _env_configured() -> bool:
    _load_rag_dotenv()
    return bool(
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("LLM_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
    )


def _manifest_doc_count() -> int:
    if not _MANIFEST.is_file():
        return 0
    try:
        data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return 0
        return sum(int(item.get("chunk_count") or 0) for item in data.values() if isinstance(item, dict))
    except Exception:
        return 0


def _chroma_sqlite_count() -> int:
    """不加载 embedding 模型，直接读 Chroma SQLite 中的向量条数。"""
    if not _CHROMA_SQLITE.is_file():
        return 0
    try:
        import sqlite3

        conn = sqlite3.connect(str(_CHROMA_SQLITE), timeout=2)
        try:
            row = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def _indexed_doc_count() -> int:
    manifest_count = _manifest_doc_count()
    if manifest_count > 0:
        return manifest_count
    return _chroma_sqlite_count()


def _fast_status() -> Dict[str, Any]:
    doc_count = _indexed_doc_count()
    env_ok = _env_configured()
    chroma_ok = _CHROMA_DIR.is_dir()
    worker_ok = _worker_ready and _worker_proc is not None and _worker_proc.poll() is None
    return {
        "available": env_ok and doc_count > 0 and chroma_ok,
        "detail": "" if env_ok else "缺少 DEEPSEEK_API_KEY / LLM_API_KEY / DASHSCOPE_API_KEY",
        "root": str(_RAG_ROOT),
        "mode": "fast",
        "python": _rag_python(),
        "doc_count": doc_count,
        "env_ok": env_ok,
        "index_ok": doc_count > 0 and chroma_ok,
        "worker_ready": worker_ok,
    }


def _run_rag_script(script: Path, payload: Dict[str, Any] | None = None, *, timeout: int = 180) -> Dict[str, Any]:
    if not script.is_file():
        raise RuntimeError(f"未找到 RAG 脚本: {script}")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    cmd = [_rag_python(), str(script)]
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload or {}, ensure_ascii=False) if payload is not None else None,
        capture_output=True,
        text=True,
        cwd=str(_RAG_ROOT),
        timeout=timeout,
        encoding="utf-8",
        env=env,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        lines = [ln for ln in err.splitlines() if "LangChainDeprecationWarning" not in ln]
        err = "\n".join(lines).strip()
        raise RuntimeError(err or f"RAG 子进程失败，退出码 {proc.returncode}")
    raw = (proc.stdout or "").strip()
    if not raw:
        return {}
    return json.loads(raw)


def _stop_worker() -> None:
    global _worker_proc, _worker_ready
    if _worker_proc is None:
        _worker_ready = False
        return
    try:
        if _worker_proc.poll() is None:
            _worker_proc.terminate()
            try:
                _worker_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _worker_proc.kill()
    except Exception:
        pass
    _worker_proc = None
    _worker_ready = False


def _start_worker(*, timeout: int = 180) -> subprocess.Popen:
    global _worker_proc, _worker_ready
    _stop_worker()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(
        [_rag_python(), str(_WORKER_CLI)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=str(_RAG_ROOT),
        encoding="utf-8",
        env=env,
        bufsize=1,
    )
    deadline = time.time() + timeout
    ready_line = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("RAG Worker 启动失败: 进程已退出")
        if proc.stdout and not proc.stdout.closed:
            ready_line = proc.stdout.readline()
            if ready_line:
                break
        time.sleep(0.05)
    if not ready_line:
        _stop_worker()
        raise RuntimeError("RAG Worker 启动超时")
    try:
        ready = json.loads(ready_line)
    except json.JSONDecodeError as exc:
        _stop_worker()
        raise RuntimeError(f"RAG Worker 启动响应无效: {ready_line[:200]}") from exc
    if not ready.get("ok"):
        _stop_worker()
        raise RuntimeError(ready.get("error") or "RAG Worker 未就绪")
    _worker_proc = proc
    _worker_ready = True
    return proc


def _ensure_worker(*, timeout: int = 180) -> subprocess.Popen:
    global _worker_proc, _worker_ready
    if _worker_proc is not None and _worker_proc.poll() is None and _worker_ready:
        return _worker_proc
    with _worker_lock:
        if _worker_proc is not None and _worker_proc.poll() is None and _worker_ready:
            return _worker_proc
        return _start_worker(timeout=timeout)


def _worker_request(payload: Dict[str, Any], *, timeout: int = 300) -> Dict[str, Any]:
    with _worker_lock:
        proc = _ensure_worker(timeout=min(timeout, 180))
        assert proc.stdin and proc.stdout
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                _stop_worker()
                raise RuntimeError("RAG Worker 已退出，请重试")
            resp_line = proc.stdout.readline()
            if resp_line:
                data = json.loads(resp_line)
                if data.get("ok") is False and data.get("error"):
                    raise RuntimeError(str(data["error"]))
                return data
            time.sleep(0.02)
        raise RuntimeError("RAG Worker 响应超时")


def warmup() -> Dict[str, Any]:
    _stop_worker()
    try:
        data = _run_rag_script(_CHAT_CLI, {"action": "warmup"}, timeout=180)
        return {
            "ok": bool(data.get("ok")),
            "worker_ready": bool(data.get("worker_ready")),
            "doc_count": int(data.get("doc_count") or 0),
            "message": data.get("message") or "RAG Agent 已预热",
        }
    except Exception as exc:
        return {"ok": False, "worker_ready": False, "message": str(exc)}


def chat(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    normalized = [
        {"role": m["role"], "content": (m.get("content") or "").strip()}
        for m in messages
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    if not normalized:
        raise ValueError("messages 不能为空")
    # 与 Streamlit 一致：独立子进程跑 ReactAgent，并释放 Worker 对 Chroma 的占用。
    _stop_worker()
    data = _run_rag_script(_CHAT_CLI, {"messages": normalized}, timeout=300)
    return {
        "answer": data.get("answer") or "暂无回答",
        "references": data.get("references") or [],
        "raw": data.get("raw") or "",
    }


def status(*, deep: bool = False) -> Dict[str, Any]:
    if not deep:
        return _fast_status()
    check = {"ok": False, "detail": ""}
    kb = {"ok": False, "doc_count": 0, "message": ""}
    try:
        check = _run_rag_script(_CHECK_CLI, timeout=30)
    except Exception as exc:
        check = {"ok": False, "detail": str(exc)}
    try:
        kb = _run_rag_script(_KB_CLI, {"action": "status"}, timeout=60)
    except Exception as exc:
        kb = {"ok": False, "doc_count": 0, "message": str(exc)}
        if not check.get("detail"):
            check["detail"] = str(exc)
    doc_count = int(kb.get("doc_count") or 0)
    env_ok = bool(check.get("ok"))
    index_ok = bool(kb.get("ok")) and doc_count > 0
    detail = (check.get("detail") or kb.get("message") or "").strip()
    return {
        "available": env_ok and (index_ok or doc_count > 0),
        "detail": detail,
        "root": str(_RAG_ROOT),
        "mode": "deep",
        "python": _rag_python(),
        "doc_count": doc_count,
        "env_ok": env_ok,
        "index_ok": index_ok,
        "worker_ready": _worker_ready,
    }


def knowledge_data_dir() -> Path:
    return _RAG_ROOT / "data"


ALLOWED_KB_EXTENSIONS = {".txt", ".pdf", ".docx", ".json"}
MAX_KB_UPLOAD_BYTES = 20 * 1024 * 1024


def _normalize_kb_filename(filename: str) -> str:
    name = Path((filename or "").strip()).name
    if not name or name in {".", ".."}:
        raise ValueError("文件名无效")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_KB_EXTENSIONS:
        allowed = ", ".join(sorted(ext.lstrip(".") for ext in ALLOWED_KB_EXTENSIONS))
        raise ValueError(f"仅支持以下格式: {allowed}")
    return name


def kb_documents(action: str, *, path: str = "", max_chars: int = 8000) -> Dict[str, Any]:
    allowed = {"list", "ingest", "delete", "preview"}
    if action not in allowed:
        raise ValueError(f"不支持的操作: {action}")
    payload: Dict[str, Any] = {"action": action}
    if path:
        payload["path"] = path
    if action == "preview":
        payload["max_chars"] = max_chars
    timeout = 300 if action == "ingest" else 120
    return _run_rag_script(_KB_DOCS_CLI, payload, timeout=timeout)


def preview_kb_document(path: str, *, max_chars: int = 8000) -> Dict[str, Any]:
    rel = (path or "").strip().replace("\\", "/")
    if not rel:
        raise ValueError("path 不能为空")
    return kb_documents("preview", path=rel, max_chars=max_chars)


def list_kb_documents() -> Dict[str, Any]:
    return kb_documents("list")


def ingest_kb_document(path: str) -> Dict[str, Any]:
    rel = (path or "").strip().replace("\\", "/")
    if not rel:
        raise ValueError("path 不能为空")
    return kb_documents("ingest", path=rel)


def delete_kb_document(path: str) -> Dict[str, Any]:
    rel = (path or "").strip().replace("\\", "/")
    if not rel:
        raise ValueError("path 不能为空")
    return kb_documents("delete", path=rel)


def save_kb_upload(filename: str, content: bytes) -> Dict[str, Any]:
    if not content:
        raise ValueError("上传文件为空")
    if len(content) > MAX_KB_UPLOAD_BYTES:
        raise ValueError("单文件大小不能超过 20MB")
    safe_name = _normalize_kb_filename(filename)
    data_dir = knowledge_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    target = (data_dir / safe_name).resolve()
    root = data_dir.resolve()
    if root not in target.parents and target != root:
        raise ValueError("非法保存路径")
    target.write_bytes(content)
    rel = safe_name.replace("\\", "/")
    result = ingest_kb_document(rel)
    result["path"] = rel
    result["name"] = safe_name
    return result


def kb_manage(action: str) -> Dict[str, Any]:
    allowed = {"ingest", "clear", "rebuild", "status"}
    if action not in allowed:
        raise ValueError(f"不支持的操作: {action}")
    if action == "rebuild":
        try:
            _stop_worker()
            return _worker_request({"action": "rebuild"}, timeout=600)
        except Exception:
            _stop_worker()
            return _run_rag_script(_KB_CLI, {"action": action}, timeout=600)
    if action in ("clear", "ingest"):
        _stop_worker()
    timeout = 600 if action == "ingest" else 120
    return _run_rag_script(_KB_CLI, {"action": action}, timeout=timeout)


def reference_preview(reference: str) -> str:
    ref = (reference or "").strip()
    if not ref:
        raise ValueError("reference 不能为空")
    data = _run_rag_script(_REF_PREVIEW_CLI, {"reference": ref}, timeout=60)
    return data.get("preview") or ""
