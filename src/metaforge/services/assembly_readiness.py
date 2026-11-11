"""组装就绪衔接：生产 MES 完工 → 自制件映射 → assembly_readiness 集合。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MAPPING_PATH = _REPO_ROOT / "data" / "integration" / "job_to_assembly_parts.json"
_PURCHASED_PATH = _REPO_ROOT / "data" / "integration" / "purchased_assembly_parts.json"

_mapping_cache: Optional[Dict[str, Any]] = None
_purchased_cache: Optional[Dict[str, Any]] = None


def load_mapping_catalog() -> Dict[str, Any]:
    global _mapping_cache
    if _mapping_cache is not None:
        return _mapping_cache
    if not _MAPPING_PATH.is_file():
        _mapping_cache = {"rules": [], "fallback": {"parts": [], "workstation": ""}, "max_product_units": 8}
        return _mapping_cache
    with open(_MAPPING_PATH, encoding="utf-8") as f:
        _mapping_cache = json.load(f)
    return _mapping_cache


def load_purchased_parts_catalog() -> Dict[str, Any]:
    global _purchased_cache
    if _purchased_cache is not None:
        return _purchased_cache
    if not _PURCHASED_PATH.is_file():
        _purchased_cache = {"parts": []}
        return _purchased_cache
    with open(_PURCHASED_PATH, encoding="utf-8") as f:
        _purchased_cache = json.load(f)
    return _purchased_cache


def _match_rule(text: str, catalog: Dict[str, Any]) -> Dict[str, Any]:
    lowered = (text or "").lower()
    for rule in catalog.get("rules") or []:
        for kw in rule.get("keywords") or []:
            if kw.lower() in lowered:
                return rule
    return catalog.get("fallback") or {}


def _job_match_text(job: Dict[str, Any]) -> str:
    name = str(job.get("name") or "")
    if name.strip():
        return name
    tasks = job.get("tasks") or []
    if tasks:
        last = tasks[-1]
        if isinstance(last, dict):
            return str(last.get("name") or last.get("machine") or "")
        return str(last)
    return ""


def map_jobs_to_self_made_parts(
    jobs: List[Dict[str, Any]],
    *,
    product_units: int,
) -> List[Dict[str, Any]]:
    catalog = load_mapping_catalog()
    out: List[Dict[str, Any]] = []
    for idx, job in enumerate(jobs):
        if not isinstance(job, dict):
            continue
        rule = _match_rule(_job_match_text(job), catalog)
        qty = int(job.get("quantity") or product_units or 1)
        for part in rule.get("parts") or []:
            out.append(
                {
                    "job_name": str(job.get("name") or f"工件-{idx + 1}"),
                    "job_index": idx,
                    "mapped_part_id": part.get("id") or "parts_buffer",
                    "mapped_part_name": part.get("name") or part.get("id") or "零件",
                    "mapped_workstation": rule.get("workstation") or "—",
                    "quantity": qty,
                    "source": "production_mes",
                }
            )
    return out


def compute_product_units(jobs: List[Dict[str, Any]], catalog: Optional[Dict[str, Any]] = None) -> int:
    cat = catalog or load_mapping_catalog()
    cap = int(cat.get("max_product_units") or 8)
    if not jobs:
        return min(1, cap)
    explicit = [
        int(j.get("quantity"))
        for j in jobs
        if isinstance(j, dict) and j.get("quantity") is not None
    ]
    base = max(explicit) if explicit else len(jobs)
    return max(1, min(cap, base))


def _serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    if "_id" in out:
        out["id"] = str(out.pop("_id"))
    else:
        out.pop("_id", None)
    return out


async def generate_readiness_from_execution(
    execution_coll,
    orders_coll,
    readiness_coll,
    *,
    plan_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    from bson import ObjectId

    from metaforge.services.production_execution import execution_is_completed, maybe_complete_execution

    doc = await execution_coll.find_one({"_id": "active"})
    if not doc:
        return None, "无 MES 执行记录"
    doc = await maybe_complete_execution(execution_coll, doc)
    if not execution_is_completed(doc):
        return None, "MES 尚未整单执行完毕"
    pid = plan_id or doc.get("plan_id")
    if not pid:
        return None, "缺少 plan_id"
    if doc.get("readiness_id") and str(doc.get("plan_id")) == str(pid):
        existing = await readiness_coll.find_one({"_id": ObjectId(doc["readiness_id"])})
        if existing:
            return _serialize_doc(existing), None

    try:
        oid = ObjectId(pid)
    except Exception:
        return None, "plan_id 无效"

    order = await orders_coll.find_one({"_id": oid})
    if not order:
        return None, "计划不存在"

    jobs = list(doc.get("jobs_snapshot") or order.get("jobs") or [])
    catalog = load_mapping_catalog()
    product_units = compute_product_units(jobs, catalog)
    self_made = map_jobs_to_self_made_parts(jobs, product_units=product_units)
    now = datetime.now(timezone.utc).isoformat()

    await readiness_coll.delete_many({"plan_id": str(pid), "status": "ready"})

    record = {
        "plan_id": str(pid),
        "plan_name": order.get("plan_name") or doc.get("plan_name") or "未命名计划",
        "mes_completed_at": doc.get("completed_at_wall") or now,
        "mes_makespan_h": float(doc.get("makespan") or 0),
        "product_units": product_units,
        "self_made_parts": self_made,
        "purchased_parts": list(load_purchased_parts_catalog().get("parts") or []),
        "purchased_parts_ref": "masa-qmix/supply-chain",
        "kitting_status": "self_made_ready",
        "status": "ready",
        "consumed_at": None,
        "created_at": now,
    }
    ins = await readiness_coll.insert_one(record)
    rid = str(ins.inserted_id)
    await execution_coll.update_one(
        {"_id": "active"},
        {"$set": {"readiness_id": rid, "readiness_generated_at": now}},
    )
    record["_id"] = ins.inserted_id
    return _serialize_doc(record), None


async def try_auto_generate_readiness(execution_coll, orders_coll, readiness_coll) -> None:
    try:
        await generate_readiness_from_execution(execution_coll, orders_coll, readiness_coll)
    except Exception as exc:
        print(f"[WARN] assembly_readiness auto-generate: {exc}")


async def get_latest_ready(readiness_coll) -> Optional[Dict[str, Any]]:
    doc = await readiness_coll.find_one({"status": "ready"}, sort=[("created_at", -1)])
    return _serialize_doc(doc) if doc else None


async def get_last_record(readiness_coll) -> Optional[Dict[str, Any]]:
    doc = await readiness_coll.find_one({}, sort=[("created_at", -1)])
    return _serialize_doc(doc) if doc else None


async def get_readiness_by_id(readiness_coll, readiness_id: str) -> Optional[Dict[str, Any]]:
    from bson import ObjectId

    try:
        oid = ObjectId(readiness_id)
    except Exception:
        return None
    doc = await readiness_coll.find_one({"_id": oid})
    return _serialize_doc(doc) if doc else None


async def consume_readiness(readiness_coll, readiness_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    from bson import ObjectId

    try:
        oid = ObjectId(readiness_id)
    except Exception:
        return None, "readiness_id 无效"
    doc = await readiness_coll.find_one({"_id": oid})
    if not doc:
        return None, "记录不存在"
    if doc.get("status") == "consumed":
        return _serialize_doc(doc), None
    now = datetime.now(timezone.utc).isoformat()
    await readiness_coll.update_one(
        {"_id": oid},
        {"$set": {"status": "consumed", "consumed_at": now}},
    )
    doc["status"] = "consumed"
    doc["consumed_at"] = now
    return _serialize_doc(doc), None
