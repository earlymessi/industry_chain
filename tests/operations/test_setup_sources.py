"""Regression checks for native identity resolution and selectable QMIX results."""
import copy
import pytest
from metaforge.operations.sources import production_plan, gantt_job_rows, assembly_definitions
from metaforge.operations.chain_sources import assembly_catalog, mapped_assembly_rows
from .test_source_alignment import tiny_doc, MACHINES, NOW


def duplicate_doc(*, appended=False):
    doc = tiny_doc()
    base = doc['jobs'][0]
    base['name'] = '急单'; base['priority'] = 10
    second = copy.deepcopy(base); second['priority'] = 100; second['due_date'] = 20
    doc['jobs'].append(second)
    rows = doc['schedule_results']['ts']['gantt_data']
    for r in rows:
        r.update(job_name='急单', job_id=0 if appended else 1, priority=10)
    more = copy.deepcopy(rows)
    for r in more:
        r.update(job_id=1 if appended else 0, priority=100, start=r['start'] + 10, end=r['end'] + 10)
    doc['schedule_results']['ts']['gantt_data'] = more[::-1] + rows[::-1]
    return doc


@pytest.mark.parametrize('appended', [False, True])
def test_duplicate_display_names_resolve_sorted_prefix_or_inserted_solver_ids(appended):
    doc = duplicate_doc(appended=appended)
    plan = production_plan(doc, MACHINES, [], NOW, solver='ts')
    assert len(plan['orders']) == 2
    assert len({o['id'] for o in plan['orders']}) == 2
    assert len({o['name'] for o in plan['orders']}) == 2
    assert [s['start_at'] for s in plan['schedule']] == [NOW + n * 3600 for n in [1, 3, 11, 13]]
    assert plan['orders'][1]['due_at'] == NOW + 20 * 3600
    assert [t['source_ref']['solver_job_id'] for t in plan['tasks'][:2]] == [0 if appended else 1] * 2


def test_duplicate_names_without_native_ids_are_rejected_instead_of_guessing():
    doc = duplicate_doc()
    for row in doc['schedule_results']['ts']['gantt_data']: row.pop('job_id')
    with pytest.raises(ValueError, match='甘特缺少job_id'):
        production_plan(doc, MACHINES, [], NOW, solver='ts')


def test_missing_display_names_can_use_complete_native_index_mapping():
    doc = tiny_doc(); doc['jobs'][0]['name'] = ''
    for r in doc['schedule_results']['ts']['gantt_data']: r.pop('job_name'); r['job_id'] = 0
    plan = production_plan(doc, MACHINES, [], NOW, solver='ts')
    assert plan['orders'][0]['name'] == '工单1'
    assert len(plan['tasks']) == 2


def test_ambiguous_foreign_ids_are_not_matched_by_duplicate_name():
    doc = duplicate_doc()
    for r in doc['schedule_results']['ts']['gantt_data']: r['job_id'] += 100
    with pytest.raises(ValueError, match='不会按同名顺序猜测'):
        production_plan(doc, MACHINES, [], NOW, solver='ts')


def test_zero_business_id_is_retained_and_duplicate_ids_rejected():
    doc = tiny_doc(); doc['jobs'][0]['job_id'] = 0
    assert production_plan(doc, MACHINES, [], NOW, solver='ts')['orders'][0]['id'].endswith(':job:0')
    doc = duplicate_doc(); doc['jobs'][0]['job_id'] = 1
    with pytest.raises(ValueError, match='job_id重复'):
        production_plan(doc, MACHINES, [], NOW, solver='ts')


def valid_assembly_rows(units):
    rows, time = [], 0
    for unit in range(units):
        for pid, d in assembly_definitions().items():
            rows.append([time, d.standard_time, d.workstation_ids[0], unit, pid])
            time += d.standard_time
    return rows


def test_assembly_picker_checks_same_model_as_import_and_keeps_reason():
    valid = valid_assembly_rows(6)
    invalid = copy.deepcopy(valid); invalid[1][2] = invalid[0][2]; invalid[1].pop()
    def reader(path):
        if path == '/api/evaluation/6': return {'ok': True, 'has_schedule': True, 'episode_count': 3}
        if path.endswith('/gantt/1'): return {'ok': True, 'data': valid}
        if path.endswith('/gantt/2'): return {'ok': True, 'data': invalid}
        if path.endswith('/gantt/3'): return {'ok': True, 'data': valid[:-1]}
        return {'ok': True, 'has_schedule': False}
    rows = [r for r in assembly_catalog(reader)['results'] if not r.get('case_id') and not r.get('record_id')]
    assert [r['compatible'] for r in rows] == [True, False, False]
    assert '9工序' in rows[1]['reason']
    assert '全部9道工序' in rows[2]['reason']
    assert len(mapped_assembly_rows(valid, 6)) == 54


@pytest.mark.parametrize('change,reason', [('precedence','工艺前置'), ('overlap','工位重叠'), ('nonfinite','有限')])
def test_picker_rejects_precedence_capacity_and_nonfinite_data(change, reason):
    rows = valid_assembly_rows(6)
    if change == 'precedence': rows[1][0] = 0
    if change == 'overlap':
        duration = sum(d.standard_time for d in assembly_definitions().values())
        for row in rows[9:18]: row[0] -= duration
    if change == 'nonfinite': rows[0][1] = float('nan')
    with pytest.raises(ValueError, match=reason): mapped_assembly_rows(rows, 6)
