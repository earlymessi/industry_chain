"""assembly_readiness 映射与单位计算测试。"""

from metaforge.services.assembly_readiness import (
    compute_product_units,
    load_mapping_catalog,
    load_purchased_parts_catalog,
    map_jobs_to_self_made_parts,
)


def test_map_job_name_metal_panel():
    jobs = [{"name": "钣金外框-01", "quantity": 8, "tasks": []}]
    parts = map_jobs_to_self_made_parts(jobs, product_units=8)
    ids = {p["mapped_part_id"] for p in parts}
    assert "metal_panel" in ids
    assert "door_frame" in ids
    assert parts[0]["mapped_workstation"] == "钣金成型"


def test_map_refrigerator_job_names():
    jobs = [
        {"name": "订单104-门体加强筋"},
        {"name": "订单102-门体铰链"},
        {"name": "订单101-压缩机底座"},
        {"name": "订单110-电控盒组件"},
    ]
    parts = map_jobs_to_self_made_parts(jobs, product_units=8)
    by_job = {}
    for p in parts:
        by_job.setdefault(p["job_name"], []).append(p)
    assert by_job["订单104-门体加强筋"][0]["mapped_workstation"] == "钣金成型"
    assert any(p["mapped_part_id"] == "hinge_set" for p in by_job["订单102-门体铰链"])
    assert any(p["mapped_part_id"] == "compressor_mount" for p in by_job["订单101-压缩机底座"])
    assert by_job["订单110-电控盒组件"][0]["mapped_workstation"] == "电气元件装配"


def test_map_job_fallback():
    jobs = [{"name": "未知工件-A", "tasks": [{"name": "铣削"}]}]
    parts = map_jobs_to_self_made_parts(jobs, product_units=4)
    assert parts[0]["mapped_part_id"] == "parts_buffer"


def test_compute_product_units_caps_at_max():
    catalog = load_mapping_catalog()
    jobs = [{"name": "a", "quantity": 20}, {"name": "b", "quantity": 3}]
    units = compute_product_units(jobs, catalog)
    assert units == catalog.get("max_product_units", 8)


def test_compute_product_units_from_job_count():
    catalog = load_mapping_catalog()
    jobs = [{"name": "钣金1"}, {"name": "内胆2"}, {"name": "发泡3"}]
    units = compute_product_units(jobs, catalog)
    assert units == 3


def test_purchased_parts_catalog():
    catalog = load_purchased_parts_catalog()
    parts = catalog.get("parts") or []
    assert len(parts) >= 8
    assert any(p.get("category") in ("外购", "外协") for p in parts)
