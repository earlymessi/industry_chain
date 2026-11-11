"""purchased_supply 状态与调度测试。"""

from metaforge.services.purchased_supply import (
    build_supply_chain_status,
    dispatch_delivery,
    load_supply_state,
    simulate_advance_deliveries,
    update_supply_state,
)


def test_build_supply_chain_status_has_overview():
    status = build_supply_chain_status()
    assert status["summary"]["total_suppliers"] == 6
    overview = status.get("materials_overview") or []
    assert len(overview) >= 8
    assert all("on_hand" in row and "stock_status" in row for row in overview)


def test_update_on_hand_persists():
    state = load_supply_state()
    mid = "compressor"
    update_supply_state({"materials": {mid: {"on_hand": 99}}})
    status = build_supply_chain_status()
    row = next(r for r in status["materials_overview"] if r["id"] == mid)
    assert row["on_hand"] == 99
    # restore if needed - not critical for test isolation if file committed


def test_dispatch_delivery_adds_in_transit():
    before = sum(1 for d in load_supply_state().get("deliveries") or [] if d.get("status") == "on_the_way")
    view = dispatch_delivery(
        supplier_name="压缩机供应商",
        material_id="compressor",
        quantity=5,
        eta_minutes=10,
    )
    after = sum(1 for d in view.get("deliveries") or [] if d.get("status") == "on_the_way")
    assert after >= before + 1


def test_simulate_advance_reduces_eta_or_arrives():
    update_supply_state(
        {
            "deliveries": [
                {
                    "id": "TEST_ARRIVE",
                    "supplier_name": "压缩机供应商",
                    "material_id": "compressor",
                    "quantity": 3,
                    "eta_minutes": 5,
                    "status": "on_the_way",
                    "priority": "normal",
                }
            ]
        }
    )
    result = simulate_advance_deliveries(minutes=30)
    d = next((x for x in result["deliveries"] if x.get("id") == "TEST_ARRIVE"), None)
    assert d is not None
    assert d["status"] == "arrived"
