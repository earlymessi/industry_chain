"""外购/外协供应链状态：可编辑库存与供应商发运调度（演示持久化）。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from metaforge.services.assembly_readiness import load_purchased_parts_catalog

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STATE_PATH = _REPO_ROOT / "data" / "integration" / "purchased_supply_state.json"

SUPPLIER_NAMES = [
    "压缩机供应商",
    "电气元件供应商",
    "钣金件供应商",
    "发泡料供应商",
    "门体配件供应商",
    "包装材料供应商",
]

DELIVERY_STATUSES = ("planned", "on_the_way", "arrived")
DELIVERY_PRIORITIES = ("low", "normal", "urgent")


def _default_state() -> Dict[str, Any]:
    catalog = load_purchased_parts_catalog()
    materials: Dict[str, Dict[str, int]] = {}
    for part in catalog.get("parts") or []:
        pid = part.get("id")
        if pid:
            materials[str(pid)] = {"on_hand": int(part.get("safety_stock") or 30)}
    return {"materials": materials, "deliveries": []}


def load_supply_state() -> Dict[str, Any]:
    if not _STATE_PATH.is_file():
        state = _default_state()
        save_supply_state(state)
        return state
    with open(_STATE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data.get("materials"), dict):
        data["materials"] = _default_state()["materials"]
    if not isinstance(data.get("deliveries"), list):
        data["deliveries"] = []
    return data


def save_supply_state(state: Dict[str, Any]) -> Dict[str, Any]:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "materials": state.get("materials") or {},
        "deliveries": state.get("deliveries") or [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return state


def _in_transit_qty(material_id: str, deliveries: List[Dict[str, Any]]) -> int:
    total = 0
    for d in deliveries:
        if d.get("material_id") == material_id and d.get("status") == "on_the_way":
            total += int(d.get("quantity") or 0)
    return total


def _stock_status(on_hand: int, safety_stock: int, in_transit: int) -> str:
    if on_hand <= 0:
        return "缺料"
    if safety_stock > 0 and on_hand < safety_stock * 0.5:
        return "缺料"
    if safety_stock > 0 and on_hand < safety_stock:
        return "紧张"
    if in_transit > 0:
        return "在途"
    return "充足"


def build_supply_chain_status() -> Dict[str, Any]:
    catalog = load_purchased_parts_catalog()
    state = load_supply_state()
    materials_state = state.get("materials") or {}
    deliveries = list(state.get("deliveries") or [])

    in_transit: List[Dict[str, Any]] = []
    critical_shortages: List[Dict[str, Any]] = []
    parts = catalog.get("parts") or []

    for part in parts:
        pid = str(part.get("id") or "")
        if not pid:
            continue
        on_hand = int((materials_state.get(pid) or {}).get("on_hand") or 0)
        safety = int(part.get("safety_stock") or 0)
        transit_qty = _in_transit_qty(pid, deliveries)
        status = _stock_status(on_hand, safety, transit_qty)

        if status in ("缺料", "紧张"):
            critical_shortages.append(
                {
                    "material": pid,
                    "severity": "high" if status == "缺料" else "medium",
                    "message": f"{part.get('name')}库存{status}",
                    "affected_workstation": part.get("workstation") or "",
                }
            )

    for d in deliveries:
        if d.get("status") != "on_the_way":
            continue
        in_transit.append(
            {
                "id": d.get("id"),
                "supplier_name": d.get("supplier_name"),
                "material": d.get("material_id"),
                "quantity": int(d.get("quantity") or 0),
                "estimated_arrival": float(d.get("eta_minutes") or 0),
                "status": "on_the_way",
                "priority": d.get("priority") or "normal",
            }
        )

    delivery_schedule = [
        {
            "scheduled_time": float(d.get("eta_minutes") or 0),
            "supplier_name": d.get("supplier_name"),
            "material": d.get("material_id"),
            "quantity": int(d.get("quantity") or 0),
            "priority": d.get("priority") or "normal",
            "status": d.get("status"),
            "id": d.get("id"),
        }
        for d in deliveries
        if d.get("status") in ("planned", "on_the_way")
    ]

    supplier_performance = [
        {
            "supplier_id": i,
            "name": name,
            "short_name": name.replace("供应商", "")[:6],
            "on_time_rate": 0.92,
            "quality_rate": 0.98,
            "avg_delivery_time": 15,
            "status": "normal",
            "active_deliveries": sum(
                1
                for d in deliveries
                if d.get("supplier_name") == name and d.get("status") == "on_the_way"
            ),
        }
        for i, name in enumerate(SUPPLIER_NAMES)
    ]

    material_overview = []
    for part in parts:
        pid = str(part.get("id") or "")
        on_hand = int((materials_state.get(pid) or {}).get("on_hand") or 0)
        transit_qty = _in_transit_qty(pid, deliveries)
        safety = int(part.get("safety_stock") or 0)
        material_overview.append(
            {
                **part,
                "on_hand": on_hand,
                "in_transit_qty": transit_qty,
                "stock_status": _stock_status(on_hand, safety, transit_qty),
            }
        )

    return {
        "in_transit": in_transit,
        "delivery_schedule": delivery_schedule,
        "critical_shortages": critical_shortages,
        "supplier_performance": supplier_performance,
        "materials_overview": material_overview,
        "deliveries": deliveries,
        "summary": {
            "total_suppliers": len(SUPPLIER_NAMES),
            "active_deliveries": sum(1 for d in deliveries if d.get("status") == "on_the_way"),
            "pending_deliveries": sum(1 for d in deliveries if d.get("status") == "planned"),
            "shortage_alerts": len(critical_shortages),
        },
    }


def get_full_state_view() -> Dict[str, Any]:
    status = build_supply_chain_status()
    return {
        "catalog": load_purchased_parts_catalog(),
        "materials": status["materials_overview"],
        "deliveries": status["deliveries"],
        "suppliers": SUPPLIER_NAMES,
        "summary": status["summary"],
    }


def update_supply_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = load_supply_state()
    catalog_ids = {str(p.get("id")) for p in (load_purchased_parts_catalog().get("parts") or []) if p.get("id")}

    if "materials" in payload and isinstance(payload["materials"], dict):
        merged = dict(state.get("materials") or {})
        for mid, row in payload["materials"].items():
            if mid not in catalog_ids:
                continue
            if isinstance(row, dict) and "on_hand" in row:
                merged[mid] = {"on_hand": max(0, int(row["on_hand"]))}
        state["materials"] = merged

    if "deliveries" in payload and isinstance(payload["deliveries"], list):
        cleaned: List[Dict[str, Any]] = []
        for d in payload["deliveries"]:
            if not isinstance(d, dict):
                continue
            mid = str(d.get("material_id") or "")
            if mid not in catalog_ids:
                continue
            status = d.get("status") or "planned"
            if status not in DELIVERY_STATUSES:
                status = "planned"
            priority = d.get("priority") or "normal"
            if priority not in DELIVERY_PRIORITIES:
                priority = "normal"
            cleaned.append(
                {
                    "id": str(d.get("id") or f"TR{uuid.uuid4().hex[:8]}"),
                    "supplier_name": str(d.get("supplier_name") or SUPPLIER_NAMES[0]),
                    "material_id": mid,
                    "quantity": max(0, int(d.get("quantity") or 0)),
                    "eta_minutes": max(0, int(d.get("eta_minutes") or 0)),
                    "status": status,
                    "priority": priority,
                }
            )
        state["deliveries"] = cleaned

    save_supply_state(state)
    return get_full_state_view()


def simulate_advance_deliveries(*, minutes: int = 30) -> Dict[str, Any]:
    """模拟时间推进：在途且 ETA 已到期的批次到货入库。"""
    state = load_supply_state()
    materials = dict(state.get("materials") or {})
    deliveries = list(state.get("deliveries") or [])
    arrived = 0

    for d in deliveries:
        if d.get("status") != "on_the_way":
            continue
        eta = int(d.get("eta_minutes") or 0)
        if eta > minutes:
            d["eta_minutes"] = eta - minutes
            continue
        qty = int(d.get("quantity") or 0)
        mid = str(d.get("material_id") or "")
        if mid:
            row = materials.get(mid) or {"on_hand": 0}
            row["on_hand"] = int(row.get("on_hand") or 0) + qty
            materials[mid] = row
        d["status"] = "arrived"
        d["eta_minutes"] = 0
        arrived += 1

    state["materials"] = materials
    state["deliveries"] = deliveries
    save_supply_state(state)
    view = get_full_state_view()
    view["simulation"] = {"arrived_batches": arrived, "advanced_minutes": minutes}
    return view


def dispatch_delivery(
    *,
    supplier_name: str,
    material_id: str,
    quantity: int,
    eta_minutes: int = 20,
    priority: str = "normal",
) -> Dict[str, Any]:
    """新建一条供应商发运（模拟外部调度）。"""
    catalog_ids = {str(p.get("id")) for p in (load_purchased_parts_catalog().get("parts") or []) if p.get("id")}
    if material_id not in catalog_ids:
        raise ValueError("未知物料")
    if supplier_name not in SUPPLIER_NAMES:
        raise ValueError("未知供应商")
    if priority not in DELIVERY_PRIORITIES:
        priority = "normal"

    state = load_supply_state()
    deliveries = list(state.get("deliveries") or [])
    deliveries.append(
        {
            "id": f"TR{uuid.uuid4().hex[:8].upper()}",
            "supplier_name": supplier_name,
            "material_id": material_id,
            "quantity": max(1, int(quantity)),
            "eta_minutes": max(1, int(eta_minutes)),
            "status": "on_the_way",
            "priority": priority,
        }
    )
    state["deliveries"] = deliveries
    save_supply_state(state)
    return get_full_state_view()
