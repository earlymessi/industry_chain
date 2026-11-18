"""Recompute an isolated baseline with the existing logistics engine (requires OSRM)."""
from pathlib import Path
import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CASE = ROOT / 'data/operations/baselines/fridge-chain-v1'

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--reuse-roads', action='store_true'); args = parser.parse_args()
    directory = CASE / 'zhenjie'; directory.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'zhenjie/customers_day1.csv'
    with source.open(encoding='utf-8-sig', newline='') as stream:
        records = [r for r in csv.DictReader(stream) if int(float(r['cust_id'])) in (36, 38)]
    if len(records) != 2 or sum(float(r['demand']) for r in records) != 5:
        raise ValueError('原客户36/38的需求已变化，请重新确认基线批次')
    for r in records: r.update(product_id='CASE-FRIDGE-01', spec='案例冰箱A型', uom='台')
    with (directory / 'customers_day1.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
    code = (ROOT / 'zhenjie/shili_run2.py').read_bytes()
    (directory / 'solver_source.py').write_bytes(code)
    os.environ['MPLBACKEND'] = 'Agg'
    spec = importlib.util.spec_from_file_location('_baseline_logistics_engine', directory / 'solver_source.py')
    engine = importlib.util.module_from_spec(spec); sys.modules[spec.name] = engine; spec.loader.exec_module(engine)
    road_path = directory / 'road_matrices.json'
    measured = json.loads(road_path.read_text(encoding='utf-8')) if args.reuse_roads and road_path.is_file() else {}
    original = engine.osrm_table_blockwise
    def roads(base, coords, max_coords, timeout, cfg):
        key = json.dumps(coords, separators=(',', ':'))
        if args.reuse_roads and key in measured:
            import numpy as np
            item = measured[key]
            return np.array(item['distance_km']), np.array(item['duration_min'])
        distances, durations = original(base, coords, max_coords, timeout, cfg)
        measured[key] = {'coords': coords, 'distance_km': distances.tolist(), 'duration_min': durations.tolist(), 'provider': base}
        road_path.write_text(json.dumps(measured, ensure_ascii=False), encoding='utf-8')
        return distances, durations
    engine.osrm_table_blockwise = roads
    # Maps are ancillary to this case; use measured matrix for optimization and recorded waypoints for display.
    engine.osrm_route_geometry = lambda *a, **k: None
    from zhenjie.result_versions import capture_inputs, publish, digest
    inputs = capture_inputs(directory)
    cfg = {**engine.CFG, 'T': 1, 'N_DEPOTS': 4, 'K_VEHICLES': 4, 'N_RUNS': 1,
           'N_PARTICLES': 12, 'N_ITERS': 30, 'ALNS_ITERS': 60, 'LAMBDA_LIST': [0.0],
           'W_ROUTE_FIXED': 2000.0, 'OSRM_TIMEOUT': 12, 'OSRM_RETRIES': 1,
           'case_id': 'fridge-chain-v1', 'engine': '原CCDR-PSO + MO-ALNS 独立案例求解',
           'solver_source_sha256': hashlib.sha256(code).hexdigest()}
    captured = {}
    def progress(event):
        if event.get('phase') == 'instance_ready':
            captured.update({name: digest(directory / name) for name in ('solver_source.py', 'road_matrices.json')})
    previous = Path.cwd()
    try:
        os.chdir(directory)
        engine.run_pipeline(cfg_overrides=cfg, on_progress=progress)
        cfg['road_matrix_sha256'] = captured['road_matrices.json']
        for name, expected in captured.items():
            if digest(directory / name) != expected: raise ValueError('求解期间输入附件变化，拒绝发布')
        document = publish(directory, inputs, cfg)
        document['input_artifacts'] = captured
        path = directory / 'operations_result_manifest.json'
        path.write_text(json.dumps(document, ensure_ascii=False, default=str, sort_keys=True), encoding='utf-8')
        print('Baseline logistics published:', document['run_id'])
    finally:
        os.chdir(previous)

if __name__ == '__main__': main()
