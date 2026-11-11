"""Scheduletool 只读桥接：读本地结果文件，可选经 WSGI 查询运行状态。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ST_ROOT = _REPO_ROOT / "Scheduletool"
_ST_PKG = _ST_ROOT / "Scheduletool"
_RESULT = _ST_PKG / "result"
_EP_PATH = _RESULT / "EP_text1.npy"
_METRICS_PATH = _RESULT / "metrics.json"
_BATCH_IDS_PATH = _RESULT / "excel" / "last_batch_order_ids.json"


def is_present() -> bool:
    return (_ST_ROOT / "app.py").is_file() and (_ST_PKG / "__init__.py").is_file()


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _ep_count() -> int:
    if not _EP_PATH.is_file():
        return 0
    try:
        import numpy as np

        arr = np.load(_EP_PATH, allow_pickle=True)
        return int(len(arr))
    except Exception:
        return 0


def _file_mtime_iso(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except Exception:
        return None


def status(kdcea_fetcher: Optional[Callable[[], Dict[str, Any]]] = None) -> Dict[str, Any]:
    present = is_present()
    kdcea = {"status": "unknown", "message": ""}
    if kdcea_fetcher:
        try:
            kdcea = kdcea_fetcher()
        except Exception as exc:
            kdcea = {"status": "error", "message": str(exc)}
    return {
        "available": present,
        "root": str(_ST_ROOT),
        "kdcea_status": kdcea.get("status") or "idle",
        "kdcea_message": kdcea.get("message") or "",
    }


def summary(kdcea_fetcher: Optional[Callable[[], Dict[str, Any]]] = None) -> Dict[str, Any]:
    base = status(kdcea_fetcher)
    metrics = _read_json(_METRICS_PATH)
    batch_ids: list = []
    if _BATCH_IDS_PATH.is_file():
        try:
            with open(_BATCH_IDS_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            batch_ids = raw if isinstance(raw, list) else []
        except Exception:
            batch_ids = []

    obj2 = metrics.get("obj2_mean") or metrics.get("obj1_mean") or []
    tc_ref = float(obj2[0]) if len(obj2) > 0 else None
    etpt_ref = float(obj2[1]) if len(obj2) > 1 else None

    pareto_count = _ep_count() or int(metrics.get("final_ep_size") or 0)
    last_run = _file_mtime_iso(_METRICS_PATH) or _file_mtime_iso(_EP_PATH)

    return {
        **base,
        "pareto_solution_count": pareto_count,
        "last_batch_order_count": len(batch_ids),
        "reference_tc": tc_ref,
        "reference_etpt_h": etpt_ref,
        "last_run_at": last_run,
        "has_reference_plan": pareto_count > 0,
    }
