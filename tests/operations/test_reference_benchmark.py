"""Independent 216-combination reference from design section 7, not a solver oracle."""
from itertools import permutations

from metaforge.operations.models import new_state
from metaforge.operations.plans import normalize_plan
from metaforge.operations.coordinator import schedule
from metaforge.operations.solve_worker import solve
from metaforge.operations.validator import validate

START = 1_800_000_000.0
PROCESS = {'A': 50, 'B': 10, 'C': 20}
ASSEMBLE = {'A': 10, 'B': 40, 'C': 15}
DUE = {'A': 130, 'B': 150, 'C': 165}
ROAD = {'D|A': 20, 'D|B': 10, 'D|C': 15, 'A|B': 15, 'A|C': 20, 'B|C': 10}
ROAD.update({f'{b}|{a}': v for key, v in list(ROAD.items()) for a, b in [key.split('|')]})


def exact(prod, assembly, route):
    # Independent minute arithmetic, deliberately does not call coordinator/validator.
    ready, cursor = {}, 0
    for order in prod:
        cursor += PROCESS[order]
        ready[order] = cursor + 5
    cursor = 0
    for order in assembly:
        cursor = max(cursor, ready[order]) + ASSEMBLE[order]
    cursor += 5  # One consolidated loading batch.
    late, node = 0, 'D'
    for order in route:
        cursor += ROAD[f'{node}|{order}'] + 5
        late += max(0, cursor - DUE[order])
        node = order
    return late, cursor + ROAD[f'{node}|D']


def reference_plan():
    orders = [{'id': o, 'name': o, 'quantity': 1, 'priority': 1, 'due_at': START + DUE[o] * 60} for o in 'ABC']
    resources = [{'id': rid, 'name': rid, 'kind': kind, 'capacity': 3 if rid == 'V1' else 1, 'location': 'D',
                  'working_windows': [[START, START + 14400]]} for rid, kind in [('M1', 'production'), ('S1', 'assembly'), ('V1', 'vehicle')]]
    def material(o, location):
        return {'material_id': o, 'quantity': 1, 'location': location}
    def task(tid, kind, rid, minutes, **kwargs):
        return {'id': tid, 'name': tid, 'kind': kind, 'quantity': 1, 'duration_mode': 'batch', 'release_at': START,
                'alternatives': [{'resource_id': rid, 'duration_seconds': minutes * 60}], **kwargs}
    tasks = []
    for o in 'ABC':
        tasks.append(task(o + '-P', 'production', 'M1', PROCESS[o], order_id=o, outputs=[material(o + '-PART', 'B')]))
        tasks.append(task(o + '-A', 'assembly', 'S1', ASSEMBLE[o], order_id=o, predecessors=[o + '-P'], transfer_seconds=300,
                          inputs=[material(o + '-PART', 'B')], outputs=[material(o + '-FG', 'B')]))
        tasks.append(task(o + '-D', 'delivery', 'V1', 0, order_id=o, to_node=o, service_seconds=300,
                          window_start=START, window_end=START + 14400, inputs=[material(o + '-FG', '@resource')]))
    tasks.append(task('LOAD', 'loading', 'V1', 5, at_node='D', predecessors=[o + '-A' for o in 'ABC'],
                      inputs=[material(o + '-FG', 'B') for o in 'ABC'], outputs=[material(o + '-FG', '@resource') for o in 'ABC']))
    tasks.append(task('RETURN', 'return', 'V1', 0))
    group = {'id': 'TRIP', 'loading_task': 'LOAD', 'return_task': 'RETURN', 'delivery_tasks': [o + '-D' for o in 'BAC'],
             'depot': 'D', 'vehicle_options': ['V1']}
    return normalize_plan({'id': 'REFERENCE-216', 'name': '三订单穷举对照', 'source': 'standard', 'mode': 'simulation', 'start_at': START,
                           'orders': orders, 'resources': resources, 'tasks': tasks, 'stock': [], 'supplies': [],
                           'route_groups': [group], 'routes': [{**group, 'vehicle_id': 'V1', 'stops': group['delivery_tasks']}],
                           'travel_seconds': {key: value * 60 for key, value in ROAD.items()}})


def test_reference_exact_optimum_and_bounded_solver_gap():
    all_results = [(exact(p, a, r), p, a, r) for p in permutations('ABC') for a in permutations('ABC') for r in permutations('ABC')]
    assert len(all_results) == 216
    best = min(row[0] for row in all_results)
    assert best == (0, 175)
    assert sum(row[0] == best for row in all_results) == 2
    assert exact('ABC', 'ABC', 'BAC') == (50, 200)
    state = new_state(reference_plan(), START)
    original = schedule(state, START)
    assert validate(state, original, START)['passed']
    assert original['metrics']['total_delay_seconds'] == 50 * 60
    state['schedule'], state['routes'] = original['schedule'], original['routes']
    result = solve(state, START, budget=5)
    assert result['candidates']
    chosen = result['candidates'][0]
    assert chosen['validation']['passed']
    assert chosen['metrics']['total_delay_seconds'] == best[0] * 60
    # The online objective prioritizes fewer edits, so earliest return is reported, not asserted as its objective.
    assert chosen['metrics']['finish_at'] >= START + best[1] * 60
