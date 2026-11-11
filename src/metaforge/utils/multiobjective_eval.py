from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from metaforge.utils.metrics import compute_composite_score, compute_schedule_metrics


def evaluate_sequence_multiobjective(problem: Any, sequence: List[int], *, weights: Optional[Dict[str, float]] = None, resource_config: Optional[Dict[str, Any]] = None) -> Tuple[float, float, Dict[str, Any]]:
    """Search and displayed results use the same decoder and metric definitions."""
    metrics = compute_schedule_metrics(problem.get_schedule(sequence), problem, resource_config=resource_config)
    return float(compute_composite_score(metrics, weights=weights)), float(metrics["makespan"]), metrics
