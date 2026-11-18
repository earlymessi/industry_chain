"""Bind immutable solver input/output versions; legacy artifacts remain unverified."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

MANIFEST = 'operations_result_manifest.json'
OUTPUTS = ('best_stage2_balanced_vehicle_route_sequence.csv', 'best_stage2_balanced_vehicle_timeline.csv')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def capture_inputs(root):
    return {p.name: digest(p) for p in sorted(Path(root).glob('customers_day*.csv'))}

def publish(root, inputs, config):
    root = Path(root)
    if not inputs or inputs != capture_inputs(root):
        raise ValueError('求解期间订单输入发生变化，结果未发布，请重新计算')
    doc = {'schema': 1, 'run_id': uuid4().hex, 'published_at': datetime.now(timezone.utc).isoformat(),
           'inputs': inputs, 'effective_config': config,
           'outputs': {name: digest(root / name) for name in OUTPUTS}}
    temporary = root / (MANIFEST + '.tmp')
    temporary.write_text(json.dumps(doc, ensure_ascii=False, default=str, sort_keys=True), encoding='utf-8')
    temporary.replace(root / MANIFEST)
    return doc

def status(root):
    root = Path(root)
    try:
        doc = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
        verified = doc.get('schema') == 1 and bool(doc.get('inputs')) and doc['inputs'] == capture_inputs(root) and all(
            (root / name).is_file() and digest(root / name) == doc.get('outputs', {}).get(name) for name in OUTPUTS)
        verified = verified and all(Path(name).name == name and (root / name).is_file() and digest(root / name) == expected
                                    for name, expected in doc.get('input_artifacts', {}).items())
        return {**doc, 'verified': verified, 'message': '订单、配置与结果属于同次发布' if verified else '订单或结果已变，需重新计算并发布'}
    except (OSError, ValueError, KeyError, TypeError):
        return {'verified': False, 'message': '旧路线没有输入/结果版本证明，请重新计算一次'}
