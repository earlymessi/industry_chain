"""Small valid populations and a single elite must still produce a full schedule."""
from collections import Counter
import pytest
from metaforge.problems.jobshop import Job, JobShopProblem, Task
from metaforge.solvers.neuroevolution_solver import NeuroevolutionSolver


def problem():
    return JobShopProblem([
        Job([Task(machine_id=0,duration=3,id=0),Task(machine_id=1,duration=2,id=1)],id=0),
        Job([Task(machine_id=1,duration=4,id=0),Task(machine_id=0,duration=2,id=1)],id=1)])


@pytest.mark.parametrize('population,elite',[(4,1),(1,1),(4,2)])
def test_small_population_produces_complete_nonoverlapping_schedule(population,elite):
    p=problem()
    result=NeuroevolutionSolver(p,pop_size=population,elite_size=elite,generations=2,hidden_sizes=[8]).run()
    assert Counter(result['best_solution'])==Counter({0:2,1:2})
    rows=result['gantt_data'];assert len(rows)==4
    assert result['best_score']==max(r['end'] for r in rows)
    for mid in [0,1]:
        slots=sorted((r['start'],r['end']) for r in rows if r['machine_id']==mid)
        assert all(a[1]<=b[0] for a,b in zip(slots,slots[1:]))
    for job in [0,1]:
        slots=sorted((r['operation_id'],r['start'],r['end']) for r in rows if r['job_id']==job)
        assert slots[0][2]<=slots[1][1]


@pytest.mark.parametrize('params',[{'pop_size':0},{'generations':0},{'elite_size':0}])
def test_invalid_search_parameters_have_clear_validation_error(params):
    with pytest.raises(ValueError,match='正整数'):
        NeuroevolutionSolver(problem(),**params)
