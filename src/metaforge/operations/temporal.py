"""Explicit inter-stage temporal evidence on the same absolute clock."""
from .coherence import CoherenceError

def temporal_report(plan):
    tasks = {t['id']: t for t in plan['tasks']}
    slots = {r['task_id']: r for r in plan['schedule']}
    checks, conflicts = [], []
    def check(ok, target, rule, **facts):
        entry = {'target': target, 'message': rule, **facts}
        (checks if ok else conflicts).append(entry)
    for tid, task in tasks.items():
        row = slots.get(tid)
        check(row is not None, tid, '每项任务都有明确开始与结束')
        if row is None: continue
        for dep in set(task.get('predecessors', []) + row.get('route_predecessors', [])):
            previous = slots.get(dep)
            ready = previous['end_at'] + (task.get('transfer_seconds', 0) if dep in task.get('predecessors', []) else 0) if previous else None
            check(ready is not None and row['start_at'] + 1e-6 >= ready, tid, '前置完成及交接后才能开工', predecessor=dep, ready_at=ready, start_at=row['start_at'])
        if task.get('latest_start_at') is not None:
            check(row['start_at'] <= task['latest_start_at'] + 1e-6, tid, '不擅自推迟已确认的发运时刻', start_at=row['start_at'], deadline_at=task['latest_start_at'])
        if task.get('latest_end_at') is not None:
            check(row['end_at'] <= task['latest_end_at'] + 1e-6, tid, '装车及交接完成不晚于约定时限', end_at=row['end_at'], deadline_at=task['latest_end_at'])
        if task['kind'] == 'transport':
            for line in task.get('inputs', []):
                supply = next((s for s in plan['supplies'] if s['material_id'] == line['material_id'] and s['location'] == line['location']), None)
                if supply:
                    check(row['start_at'] + 1e-6 >= supply['available_at'], tid, '供方备好货后才能装载发运', ready_at=supply['available_at'], start_at=row['start_at'])
        if task['kind'] == 'delivery' and task.get('window_hard', True):
            service = row.get('service_start_at', row['end_at'] - task.get('service_seconds', 0))
            check(task.get('window_start', float('-inf')) - 1e-6 <= service <= task.get('window_end', float('inf')) + 1e-6, tid,
                  '客户服务开始落在确认的收货窗口', service_start_at=service, window_start=task.get('window_start'), window_end=task.get('window_end'))
    if conflicts: raise CoherenceError(conflicts)
    return {'passed': True, 'checks': checks, 'note': '统一绝对时间下校验前置、发运、装车和客户窗口；不通过自动平移承诺消除冲突'}
