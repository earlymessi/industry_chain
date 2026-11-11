"""JSON stdin/stdout worker: CPU/RNG isolation without pausing the runtime."""
from __future__ import annotations

import json
import sys
import time

from .coordinator import schedule, production_rank, route_configuration, choose_scope, Infeasible
from .validator import validate


def solve(snapshot: dict, now: float, budget: float = 12) -> dict:
    started = time.monotonic()
    candidates, failures, seen = [], [], set()
    baseline = None
    searched = 0
    scope = choose_scope(snapshot, now)
    if all(p["status"] == "completed" for p in snapshot["tasks"].values()):
        return {"candidates": [], "baseline": None, "searched": 0, "failures": [], "scope": scope,
                "elapsed_seconds": time.monotonic() - started, "recommended_id": None,
                "message": "全部任务已完成，无需发布调整；主时钟继续，可归档后启用新计划。"}
    if scope["capacity_request"]:
        return {"candidates": [], "baseline": None, "searched": 0, "failures": [], "scope": scope,
                "elapsed_seconds": time.monotonic() - started, "recommended_id": None,
                "message": "影响超出7天执行窗口，已形成4周能力调整请求；需补齐远期供给、班次与需求后重新评估，当前执行继续。"}
    for policy in ["original", "ts", "edd", "spt"]:
        try:
            rank = production_rank(snapshot, now, policy)
        except Exception as exc:
            failures.append({"policy": policy, "message": str(exc)})
            continue
        for assembly_policy in (["original"] if policy == "original" else ["original", "edd", "spt"]):
            for route_policy in (["original"] if policy == "original" else ["original", "edd", "spt"]):
                if policy != "original" and time.monotonic() - started > budget:
                    break
                searched += 1
                try:
                    c = schedule(snapshot, now, policy, rank=rank, routes=route_configuration(snapshot, route_policy), assembly_policy=assembly_policy)
                    c["id"] = f"{policy}-{assembly_policy}-{route_policy}"
                    c["solver"] = {"production": "TS序列＋约束派工" if policy == "ts" else policy.upper(), "assembly": f"确定性{assembly_policy}派工", "delivery": f"固定运输批次的{route_policy}路线修复"}
                    c["validation"] = validate(snapshot, c, now)
                    c["explanation"] = f"按{c['solver']['production']}生成生产顺序，组装以齐套/工位约束衔接，配送按成品就绪与容量计算；只在本次候选范围比较，不宣称全局最优。"
                    if policy == "original":
                        baseline = c
                    signature = tuple((s["task_id"], s["resource_id"], round(s["start_at"], 3), round(s["end_at"], 3)) for s in sorted(c["schedule"], key=lambda x: x["task_id"]))
                    if c["validation"]["passed"] and signature not in seen:
                        candidates.append(c)
                        seen.add(signature)
                except (ValueError, KeyError) as exc:
                    failures.append({"policy": f"{policy}/{assembly_policy}/{route_policy}", "message": str(exc)})
    candidates.sort(key=lambda c: (c["metrics"]["weighted_delay_seconds"], c["metrics"].get('window_penalty_score', 0), c["metrics"]["changed_tasks"], c["metrics"]["finish_at"]))
    return {"candidates": candidates[:3], "baseline": baseline, "searched": searched, "failures": failures, "scope": scope,
            "elapsed_seconds": time.monotonic() - started, "recommended_id": candidates[0]["id"] if candidates else None,
            "message": "候选已按硬约束校验、加权交付延期和计划改动比较；成本未给定。" if candidates else "没有可发布候选，当前可执行任务继续，受限任务等待。"}


if __name__ == "__main__":
    try:
        payload = json.load(sys.stdin)
        json.dump(solve(payload["snapshot"], payload["now"], payload.get("budget", 12)), sys.stdout, ensure_ascii=True, allow_nan=False)
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout, ensure_ascii=True)
