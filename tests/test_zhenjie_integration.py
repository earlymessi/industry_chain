"""车辆路径模块的挂载隔离、产物访问与文件路径回归。"""

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def web():
    previous_cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location("zhenjie_test_main", REPO_ROOT / "tests" / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert os.getcwd() == previous_cwd
    # 不进入 lifespan，不初始化或改写主系统业务数据。
    return TestClient(module.app)


def test_mounted_page_and_cached_results(web):
    status = web.get("/api/integrations/zhenjie/status").json()
    assert status["mounted"], status["detail"]
    entry = web.get("/logistics-vrp", follow_redirects=False)
    assert entry.headers["location"] == "/logistics-vrp/"
    page = web.get("/logistics-vrp/?embed=1&tab=map")
    assert page.status_code == 200
    assert "zhenjie-ready" in page.text
    result = web.get("/logistics-vrp/api/results")
    assert result.status_code == 200
    assert json.loads(result.text)["data"]["summary"]


def test_vrp_run_does_not_hit_production_solver(web):
    # 两个模块都有 /api/run，非法次数必须返回车辆路径模块的校验结果。
    response = web.post("/logistics-vrp/api/run", json={"n_runs": 0})
    assert response.status_code == 400
    assert "error" in response.json()
    assert web.get("/logistics-vrp/api/status").json()["status"] == "idle"


@pytest.mark.parametrize("filename", ["representative_pareto_front.png", "best_stage2_routes_map.html"])
def test_artifacts_support_preview_and_download(web, filename):
    response = web.get(f"/logistics-vrp/api/artifact/{filename}")
    assert response.status_code == 200
    assert web.head(f"/logistics-vrp/api/artifact/{filename}").status_code == 200


@pytest.mark.parametrize("path", ["/app.py", "/shili_run2.py", "/api/artifact/app.py", "/api/artifact/nested/app.py"])
def test_sources_are_not_served_as_static_files(web, path):
    assert web.get(f"/logistics-vrp{path}").status_code == 404


@pytest.mark.parametrize("use_mongo", [False, True])
def test_worker_uses_module_paths_without_changing_cwd(web, monkeypatch, tmp_path, use_mongo):
    from zhenjie import app as vrp

    saved_job = copy.deepcopy(vrp._job)
    original_cwd = os.getcwd()
    captured = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        assert os.getcwd() == str(tmp_path)
        return {
            "rep_run_id": 0, "best_stage2_run_id": 0,
            "outputs": {"run_summary": kwargs["cfg_overrides"]["RUN_SUMMARY_CSV"]},
        }

    monkeypatch.setattr(vrp.engine, "run_pipeline", fake_pipeline)
    class Frame:
        def to_csv(self, path, **kwargs):
            captured['input_csv_path'] = path
    day_frames = [Frame()]
    from zhenjie import result_versions
    monkeypatch.setattr(result_versions, 'capture_inputs', lambda root: {'fixture': 'input-version'})
    monkeypatch.setattr(result_versions, 'publish', lambda root, inputs, config: {'run_id': 'fixture-run', 'inputs': inputs, 'effective_config': config})
    from metaforge.operations import history
    def archive(root, result=None):
        captured['archived_result']=copy.deepcopy(result);return {'id':'saved-fixture'}
    monkeypatch.setattr(history,'archive_delivery',archive)
    monkeypatch.setattr(vrp, "_load_day_frames_from_mongo", lambda: day_frames)
    monkeypatch.setattr(vrp, "_export_mongo_to_csv", lambda: None)
    try:
        os.chdir(tmp_path)
        vrp._run_worker(1, {"N_ITERS": 2}, use_mongo)
        assert vrp._job["status"] == "done", vrp._job["error"]
        assert os.getcwd() == str(tmp_path)
        cfg = captured["cfg_overrides"]
        assert cfg["N_ITERS"] == 2
        for key in ("CSV_PATTERN", *vrp.OUTPUT_PATH_KEYS):
            assert Path(cfg[key]).parent == REPO_ROOT / "zhenjie"
        assert captured["day_frames"] is (day_frames if use_mongo else None)
        assert captured["archived_result"]["publication"]["run_id"]=="fixture-run"
        assert vrp._job["result"]["history_id"]=="saved-fixture"
        assert vrp._job["result"]["outputs"]["run_summary"] == "multi_run_summary.csv"
    finally:
        os.chdir(original_cwd)
        vrp._job.clear()
        vrp._job.update(saved_job)


@pytest.mark.parametrize('key',['chain-demo-normal','chain-demo-supply','chain-demo-transport'])
def test_paired_example_snapshot_is_scoped_and_cannot_modify_original_module(web,key):
    from zhenjie import app as vrp
    original_cfg=copy.deepcopy(vrp.engine.CFG); original_job=copy.deepcopy(vrp._job)
    base='/logistics-vrp/api/'
    data=web.get(base+'results',params={'example':key})
    assert data.status_code==200 and data.json()['data']['summary']
    config=web.get(base+'config',params={'example':key}).json()
    assert config['mongo']['db']==key and config['defaults']['T']==1
    orders=web.get(base+'orders',params={'example':key}).json()['items']
    assert sum(float(r['demand']) for r in orders)==5
    assert web.get(base+'artifact/best_stage2_routes_map.html',params={'example':key}).status_code==200
    assert web.head(base+'artifact/representative_pareto_front.png',params={'example':key}).status_code==200
    assert web.get(base+'artifact/solver_source.py',params={'example':key}).status_code==404
    for path in ['run','stop','orders','orders/import-csv']:
        assert web.post(base+path,params={'example':key},json={'n_runs':1}).status_code==409
    assert vrp.engine.CFG==original_cfg and vrp._job==original_job
    assert web.get(base+'results',params={'example':'../../outside'}).status_code==422


def test_delivery_data_center_can_reuse_all_three_historical_results_without_global_writes(web):
    from metaforge.operations.history import records
    from zhenjie import app as vrp
    original_cfg=copy.deepcopy(vrp.engine.CFG); original_job=copy.deepcopy(vrp._job)
    rows=[r for r in records('delivery') if r.get('test_case')]
    assert [r['name'] for r in rows]==['test1','test2','test3']
    for row in rows:
        query={'record':row['id']}
        result=web.get('/logistics-vrp/api/results',params=query)
        assert result.status_code==200 and result.json()['data']['summary']
        orders=web.get('/logistics-vrp/api/orders',params=query).json()['items']
        assert sum(float(r['demand']) for r in orders)==5
        assert web.get('/logistics-vrp/api/artifact/best_stage2_routes_map.html',params=query).status_code==200
        assert web.post('/logistics-vrp/api/run',params=query,json={'n_runs':1}).status_code==409
    assert vrp.engine.CFG==original_cfg and vrp._job==original_job


@pytest.mark.parametrize('query',[{}, {'example':'chain-demo-normal'}, {'example':'chain-demo-supply'}, {'example':'chain-demo-transport'}])
def test_map_label_bootstrap_waits_for_map_and_keeps_published_files_immutable(web,query):
    import re,subprocess
    from metaforge.operations.baselines import dataset_root
    directory=(dataset_root(query['example'])/'zhenjie') if query else REPO_ROOT/'zhenjie'
    artifact=directory/'best_stage2_routes_map.html'
    before=artifact.read_bytes()
    response=web.get('/logistics-vrp/api/artifact/best_stage2_routes_map.html',params=query)
    assert response.status_code==200 and 'text/html' in response.headers['content-type']
    html=response.text
    code=next(m for m in re.findall(r'<script[^>]*>(.*?)</script>',html,re.S) if 'toggleCustomerLabels_' in m)
    # Execute the early body script before map/feature globals exist, as a browser does.
    js="const vm=require('node:vm');const assert=require('node:assert/strict');const handlers=[];vm.runInNewContext(process.argv[1],{document:{addEventListener:(name,callback)=>{assert.equal(name,'DOMContentLoaded');handlers.push(callback)}}});assert.equal(handlers.length,1);"
    done=subprocess.run(['node','-e',js,code],capture_output=True,text=True)
    assert done.returncode==0,done.stderr
    assert artifact.read_bytes()==before
