from metaforge.problems.jobshop import Job, Task, JobShopProblem
from metaforge.solvers.tabu_search import TabuSearchSolver
from metaforge.utils.multiobjective_eval import evaluate_sequence_multiobjective
from metaforge.strategy.models import Constraint, SchedulingStrategy
from metaforge.strategy.evaluator import evaluate_candidates


def test_interval_crossing_downtime_and_alternative_finish():
    p = JobShopProblem([Job([Task(0, 4)])])
    p.machines[0].maintenance = [{"start": 2, "end": 3}]
    assert p.get_schedule([0])[0]["start"] == 3
    p = JobShopProblem([Job([Task(0, 4, machine_options=[0, 1], duration_by_machine={0: 4, 1: 1})])])
    p.machines[0].maintenance = [{"start": 2, "end": 3}]
    assert p.get_schedule([0])[0]["machine_id"] == 1


def test_search_and_gantt_agree_with_release_and_initial_ready():
    p = JobShopProblem([Job([Task(0, 4)], arrival_time=10)], initial_machine_ready=[12])
    _, makespan, _ = evaluate_sequence_multiobjective(p, [0], weights={"makespan": 1})
    assert makespan == p.get_schedule([0])[0]["end"] == 16
    assert TabuSearchSolver(p).run()["best_score"] == 16
    assert TabuSearchSolver(JobShopProblem([])).run()["gantt_data"] == []


def test_unverified_hard_constraint_blocks_recommendation():
    strategy = SchedulingStrategy(hard_constraints=[Constraint(type="skill_required", params={"skill": "weld"})])
    result = evaluate_candidates(strategy, [{"schedule_id": "x", "metrics": {"makespan": 1}}])
    assert result["recommended_schedule_id"] is None
    assert result["ranking"][0]["validation_status"] == "unverified"


def test_explicit_precedence_rejected():
    s = SchedulingStrategy(hard_constraints=[Constraint(type="precedence", params={"before": "A", "after": "B"})])
    c = {"schedule_id": "x", "metrics": {"makespan": 8}, "gantt_data": [{"job_id": "A", "start": 5, "end": 8}, {"job_id": "B", "start": 0, "end": 2}]}
    assert evaluate_candidates(s, [c])["recommended_schedule_id"] is None
