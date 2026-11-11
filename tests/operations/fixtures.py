"""Small isolated mechanism fixtures, deliberately not a user-facing baseline."""
import json
from pathlib import Path


def prepare_legacy_plan(start_at):
    plan = json.loads(Path(__file__).with_name('legacy_mechanism_fixture.json').read_text(encoding='utf-8'))
    plan['start_at'] = start_at
    for order in plan['orders']:
        order['due_at'] = start_at + order.pop('due_seconds')
    for resource in plan['resources']:
        resource['working_windows'] = [[start_at + a, start_at + b] for a, b in resource.pop('working_offsets')]
    for supply in plan['supplies']:
        supply['available_at'] = start_at + supply.pop('arrival_seconds')
    for task in plan['tasks']:
        task['release_at'] = start_at + task.pop('release_seconds', 0)
        if 'window_offsets' in task:
            a, b = task.pop('window_offsets')
            task['window_start'], task['window_end'] = start_at + a, start_at + b
    return plan
