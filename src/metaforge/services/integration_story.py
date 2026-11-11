"""产业链协同故事：只读聚合多系统状态，驱动 Hub 步骤条与对照卡片。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from metaforge.services.scheduletool_bridge import summary as scheduletool_summary


def _step(status: str, title: str, detail: str = "", link: str = "") -> Dict[str, Any]:
    return {"title": title, "status": status, "detail": detail, "link": link}


def build_story(
    *,
    execution: Optional[Dict[str, Any]] = None,
    readiness: Optional[Dict[str, Any]] = None,
    supply_summary: Optional[Dict[str, Any]] = None,
    purchased_count: int = 0,
    scheduletool: Optional[Dict[str, Any]] = None,
    scheduletool_mounted: bool = False,
) -> Dict[str, Any]:
    ex = execution or {}
    rd = readiness
    st = scheduletool or {}
    ex_status = (ex.get("status") or "idle").lower()

    has_self = bool((rd or {}).get("self_made_parts"))
    has_purchased = purchased_count > 0
    pareto = int(st.get("pareto_solution_count") or 0)
    kdcea = (st.get("kdcea_status") or "idle").lower()
    st_available = bool(st.get("available"))

    # ① 全局产配参考
    if kdcea == "running":
        s1 = _step(
            "process",
            "全局产配参考",
            "Scheduletool 正在 KDCEA 优化（结果仅供决策参考）",
            "/home/supply-chain/dashboard" if scheduletool_mounted else "",
        )
    elif pareto > 0:
        etpt = st.get("reference_etpt_h")
        extra = f"，参考时效约 {etpt:.1f} h" if isinstance(etpt, (int, float)) else ""
        s1 = _step(
            "success",
            "全局产配参考",
            f"已生成 {pareto} 组 Pareto 方案{extra}（不写入厂内排程）",
            "/home/supply-chain/dashboard" if scheduletool_mounted else "",
        )
    elif st_available:
        s1 = _step(
            "wait",
            "全局产配参考",
            "可在供应链调度中录入订单并批量排程，获得全局参考方案",
            "/home/supply-chain/dashboard" if scheduletool_mounted else "",
        )
    else:
        s1 = _step("wait", "全局产配参考", "Scheduletool 模块未挂载")

    # ② 生产加工优化（权威）
    if ex_status == "completed":
        s2 = _step("success", "生产加工优化", "生产车间 MES 整单执行已完成", "/home/production/dashboard")
    elif ex_status in ("running", "paused"):
        s2 = _step("process", "生产加工优化", "生产车间 MES 执行中（厂内加工以此为准）", "/home/production/dashboard")
    else:
        s2 = _step("wait", "生产加工优化", "请在生产车间完成 JSSP 排程与 MES 仿真", "/home/production/dashboard")

    # ③ 自制件就绪
    if has_self:
        units = (rd or {}).get("product_units")
        s3 = _step(
            "success",
            "自制件就绪",
            f"MES 完工已映射组装物料，可组装 {units or '—'} 台",
            "/home/assembly/materials",
        )
    elif ex_status == "completed":
        s3 = _step("process", "自制件就绪", "MES 已完工，等待生成组装就绪记录", "/home/production/dashboard")
    else:
        s3 = _step("wait", "自制件就绪", "待 MES 整单执行完成")

    # ④ 外购齐套
    shortage = int((supply_summary or {}).get("shortage_alerts") or 0)
    in_transit = int((supply_summary or {}).get("active_deliveries") or 0)
    if has_purchased and shortage == 0:
        s4 = _step("success", "外购/外协齐套", "外购件目录已对齐，无高危缺料", "/home/assembly/materials")
    elif has_purchased:
        s4 = _step(
            "process" if shortage else "success",
            "外购/外协齐套",
            f"在途 {in_transit} 批，缺料预警 {shortage} 项",
            "/home/assembly/materials",
        )
    else:
        s4 = _step("wait", "外购/外协齐套", "组装侧查看供应链与物料状态", "/home/assembly/materials")

    # ⑤ 组装优化（权威）
    rd_status = (rd or {}).get("status") or ""
    if rd_status == "consumed":
        s5 = _step("success", "组装 QMIX 评估", "组装批次已评估并消费就绪记录", "/home/assembly/gantt")
    elif rd_status == "ready":
        s5 = _step("process", "组装 QMIX 评估", "齐套就绪，可进行 QMIX 组装评估", "/home/assembly/dashboard")
    else:
        s5 = _step("wait", "组装 QMIX 评估", "待自制件与外购齐套完成后评估", "/home/assembly/dashboard")

    # ⑥ 配送方案对照（只读对照，不写入）
    if pareto > 0 and (rd_status in ("ready", "consumed") or ex_status == "completed"):
        mes_h = (rd or {}).get("mes_makespan_h")
        mes_part = f"厂内 MES makespan {mes_h} h" if mes_h is not None else "厂内 MES 已完工"
        s6 = _step(
            "success",
            "配送方案对照",
            f"{mes_part}；可对照 Scheduletool 车辆甘特（参考层）",
            "/home/supply-chain/dashboard" if scheduletool_mounted else "",
        )
    elif pareto > 0:
        s6 = _step(
            "process",
            "配送方案对照",
            "全局方案已就绪，待厂内生产/组装完成后对照讲解",
            "/home/supply-chain/dashboard" if scheduletool_mounted else "",
        )
    else:
        s6 = _step("wait", "配送方案对照", "先有全局 Pareto 方案，再与厂内结果对照")

    steps = [s1, s2, s3, s4, s5, s6]
    active = 0
    for i, step in enumerate(steps):
        if step["status"] == "success":
            active = i + 1
        elif step["status"] == "process":
            active = i
            break

    narrative = _build_narrative(steps, st, rd, ex)

    compare = {
        "global_reference": {
            "label": "全局参考（Scheduletool）",
            "pareto_solutions": pareto,
            "reference_etpt_h": st.get("reference_etpt_h"),
            "last_batch_orders": st.get("last_batch_order_count") or 0,
            "note": "仅供产业链协同参考",
        },
        "production_authority": {
            "label": "生产加工（权威）",
            "mes_status": ex_status,
            "mes_makespan_h": (rd or {}).get("mes_makespan_h"),
            "plan_name": (rd or {}).get("plan_name") or ex.get("plan_name"),
        },
        "assembly_authority": {
            "label": "组装装配（权威）",
            "readiness_status": rd_status or "none",
            "product_units": (rd or {}).get("product_units"),
            "shortage_alerts": shortage,
        },
    }

    return {
        "title": "冰箱产业链协同故事",
        "subtitle": "全局参考与厂内执行分层：Scheduletool 不驱动 MES/组装排程",
        "narrative": narrative,
        "active_step": active,
        "steps": steps,
        "compare": compare,
    }


def _build_narrative(
    steps: List[Dict[str, Any]],
    st: Dict[str, Any],
    rd: Optional[Dict[str, Any]],
    ex: Dict[str, Any],
) -> str:
    lines = [
        "① 先在供应链调度中看订单与产配 Pareto，建立全局成本—时效参考；",
        "② 再到生产车间做 JSSP 与 MES，以厂内系统为加工优化权威；",
        "③ MES 整单完成后，自制件映射进入组装就绪池；",
        "④ 组装车间核对外购齐套并做 QMIX 评估，以组装系统为装配权威；",
        "⑤ 最后回到 Scheduletool 甘特，对照出厂配送方案，不要求与 MES 数值一致。",
    ]
    if int(st.get("pareto_solution_count") or 0) > 0 and (rd or {}).get("mes_makespan_h") is not None:
        lines.append(
            f"当前对照：参考 ETPT ≈ {st.get('reference_etpt_h')} h，"
            f"实际 MES makespan = {rd.get('mes_makespan_h')} h（粒度不同，仅用于讲解）。"
        )
    return "\n".join(lines)
