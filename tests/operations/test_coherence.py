import copy
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metaforge.operations.api import create_router
from metaforge.operations.chain import build_chain
from metaforge.operations.coherence import CoherenceError
from metaforge.operations.models import new_state
from metaforge.operations.runtime import advance
from metaforge.operations.service import OperationsService
from metaforge.operations.store import MemoryStore
from .test_chain import NOW, native, config, supplies
from .fixtures import prepare_legacy_plan


def contract(c):
    c = copy.deepcopy(c)
    c.update(coherence_version=1, assembly_bom={'product_id':'FRIDGE-A','spec':'型号A','uom':'台','revision':'BOM-1','assembly_site':'A',
        'lines':[{'id':'SELF','material_id':'PART-A','spec':'规格A','uom':'件','per_unit':1,'process_id':0}]}, procurement_orders=[], procurement_links={}, inbound_shipments=[])
    c['parts'][0].update(bom_line_id='SELF',business_material_id='PART-A',spec='规格A',uom='件',factory_id='A',mapping_confirmed=True)
    return c


def trip(c, source_id, origin='F1', material='PART-A', quantity=2, **extra):
    value={'id':'TRIP1','source_id':source_id,'from_site':origin,'to_site':'A','material_id':material,'spec':'规格A','uom':'件',
        'quantity':quantity,'load_units':2,'capacity':5,'capacity_uom':'箱','vehicle_id':'T1',
        'ship_at':NOW+1200,'loading_minutes':5,'travel_minutes':20,'unloading_minutes':5}
    value.update(extra); c['inbound_shipments'].append(value)
    return value


def test_local_bom_contract_and_remote_factory_transport_execute_without_teleport():
    base=native(); c=contract(config(base)); c['parts'][0]['factory_id']='F1'; trip(c,c['parts'][0]['order_id'])
    p=build_chain(base,c,supplies())
    assert p['business_validation']['passed'] and p['business_validation']['inbound_tasks']==['inbound:TRIP1']
    rows={r['task_id']:r for r in p['schedule']}
    assert rows['chain:transfer']['start_at']>=rows['inbound:TRIP1']['end_at']
    state,_=advance(new_state(p,NOW),rows['inbound:TRIP1']['start_at']+60)
    assert state['tasks']['inbound:TRIP1']['status']=='running'
    assert state['inventory'].get('receiving:'+c['parts'][0]['order_id']+'|self:'+c['parts'][0]['order_id'],0)==0
    state,_=advance(state,max(r['end_at'] for r in p['schedule'])+1)
    assert state['status']=='idle' and state['inventory']['warehouse|chain:finished']==2


@pytest.mark.parametrize('change,reason',[
    ('missing_bom','缺项/多配'),('wrong_spec','spec与BOM'),('wrong_unit','uom与BOM'),('unconfirmed','明确确认'),
    ('no_transport','明确运输'),('wrong_destination','起讫地点'),('wrong_material','运输物料'),('over_capacity','超过车辆容量'),
    ('early_arrival','到货时间'),('early_departure','无可行安排')])
def test_conflicting_stories_are_rejected(change,reason):
    base=native(); c=contract(config(base)); c['parts'][0]['factory_id']='F1'; t=trip(c,c['parts'][0]['order_id'])
    if change=='missing_bom': c['assembly_bom']['lines'].append({'id':'MISSING','material_id':'B','spec':'B','uom':'件','per_unit':1,'process_id':3})
    if change=='wrong_spec': c['parts'][0]['spec']='B'
    if change=='wrong_unit': c['parts'][0]['uom']='套'
    if change=='unconfirmed': c['parts'][0]['mapping_confirmed']=False
    if change=='no_transport': c['inbound_shipments']=[]
    if change=='wrong_destination': t['to_site']='B'
    if change=='wrong_material': t['material_id']='WRONG'
    if change=='over_capacity': t['load_units']=10
    if change=='early_arrival': t['arrival_at']=t['ship_at']+1
    if change=='early_departure': t['ship_at']=NOW+1
    with pytest.raises(ValueError,match=reason): build_chain(base,c,supplies())


def purchasing(c):
    c['assembly_bom']['lines'].append({'id':'BUY','material_id':'compressor','spec':'规格S','uom':'件','per_unit':1,'process_id':3})
    c['purchased']=[{'material_id':'compressor','per_unit':1,'process_id':3,'supplier_id':'S','business_material_id':'compressor',
        'bom_line_id':'BUY','spec':'规格S','uom':'件','mapping_confirmed':True}]
    c['additional_supplies']=[{'id':'D','material_id':'compressor','quantity':2,'available_at':NOW+3000,'purchase_order_id':'PO1'}]
    c['procurement_orders']=[{'id':'PO1','supplier_id':'S','material_id':'compressor','spec':'规格S','uom':'件','quantity':2,
        'origin_site':'SUPPLIER','delivery_site':'A','ready_at':NOW+100}]
    trip(c,'chain:manual-supply:D','SUPPLIER','compressor',ship_at=NOW+1200,spec='规格S')
    return c


def test_purchase_goods_only_arrive_after_linked_transport_and_po_is_not_double_spent():
    base=native(); c=purchasing(contract(config(base)))
    p=build_chain(base,c,supplies(0))
    incoming=p['supplies'][0]
    assert incoming['available_at']==NOW+100 and incoming['location'].startswith('source:')
    final,_=advance(new_state(p,NOW),max(s['end_at'] for s in p['schedule'])+1)
    assert final['status']=='idle'
    c['additional_supplies'].append({'id':'D2','material_id':'compressor','quantity':2,'available_at':NOW+3000,'purchase_order_id':'PO1'})
    trip(c,'chain:manual-supply:D2','SUPPLIER','compressor',id='TRIP2',spec='规格S',vehicle_id='T2')
    with pytest.raises(CoherenceError,match='重复计入或分配超额'): build_chain(base,c,supplies(0))


@pytest.mark.parametrize('field,value,reason',[('supplier_id','OTHER','supplier_id'),('spec','OTHER','spec'),('delivery_site','B','收货地点'),('ready_at',NOW+9000,'尚未备好货')])
def test_procurement_identity_and_ready_date_must_match(field,value,reason):
    base=native(); c=purchasing(contract(config(base))); c['procurement_orders'][0][field]=value
    with pytest.raises(CoherenceError,match=reason): build_chain(base,c,supplies(0))


def test_reload_clears_run_changes_keeps_history_and_starts_a_new_real_time_round():
    clock=[NOW]; store=MemoryStore(); service=OperationsService(store,clock=lambda:clock[0],tick_seconds=.01)
    @asynccontextmanager
    async def lifespan(app):
        await service.start(); yield; await service.stop()
    app=FastAPI(lifespan=lifespan);app.include_router(create_router(service,standard_factory=prepare_legacy_plan))
    with TestClient(app) as client:
        assert client.post('/api/operations-tools/plans/activate',json={}).status_code==200
        old=client.get('/api/operations-tools/current').json()['instance']; rid=old['resources'][0]['id']
        clock[0]+=15
        assert client.post('/api/operations-tools/events',json={'run_id':old['run_id'],'type':'resource_unavailable','target_id':rid,'data':{}}).status_code==200
        response=client.post('/api/operations-tools/cases/reload',json={'run_id':old['run_id'],'confirmed':True,'request_id':'reload-once'})
        assert response.status_code==200,response.text
        new=client.get('/api/operations-tools/current').json()['instance']
        assert new['run_id']!=old['run_id'] and new['plan']['start_at']>=clock[0]
        assert all(r['available'] for r in new['resources']) and all(t['work_seconds']==0 for t in new['tasks'])
        assert new['event_seq']==0 and new['received_supplies']==[] and 'case_seed' not in new
        assert old['run_id'] in store.archives
        history=client.get('/api/operations-tools/cases/archives/'+old['run_id']+'/history').json()
        assert any(e['type']=='resource_unavailable' for e in history['events'])
        assert client.get('/api/operations-tools/cases/archives').json()['runs'][0]['run_id']==old['run_id']
        assert client.post('/api/operations-tools/cases/reload',json={'run_id':old['run_id'],'confirmed':True,'request_id':'reload-once'}).status_code==200
        assert client.get('/api/operations-tools/current').json()['instance']['run_id']==new['run_id']
        assert client.post('/api/operations-tools/cases/reload',json={'run_id':old['run_id'],'confirmed':True}).status_code==409


def test_logistics_publication_rejects_changed_inputs_and_cannot_publish_a_race(tmp_path):
    from zhenjie.result_versions import capture_inputs, publish, status
    for name in ('customers_day1.csv','best_stage2_balanced_vehicle_route_sequence.csv','best_stage2_balanced_vehicle_timeline.csv'):
        (tmp_path/name).write_text('fixture1',encoding='utf-8')
    original=capture_inputs(tmp_path)
    publish(tmp_path,original,{'VEHICLE_CAP':12,'N_ITERS':10})
    assert status(tmp_path)['verified']
    (tmp_path/'customers_day1.csv').write_text('new order version',encoding='utf-8')
    assert not status(tmp_path)['verified']
    with pytest.raises(ValueError,match='求解期间订单输入发生变化'):
        publish(tmp_path,original,{'VEHICLE_CAP':12})


def test_multi_factory_loader_preserves_devices_and_rejects_cloned_device_identity():
    import asyncio
    from metaforge.operations.distributed import load_production_sources
    base=native()
    async def loader(selection,start):
        p=copy.deepcopy(base); suffix=selection['plan_id']
        for order in p['orders']:
            old=order['id']; order['id']=old+suffix; order['completion_task_ids']=[t+suffix for t in order['completion_task_ids']]
        for task in p['tasks']:
            task['id']+=suffix; task['order_id']+=suffix; task['predecessors']=[t+suffix for t in task['predecessors']]
        for row in p['schedule']:row['task_id']+=suffix
        return p
    c={'production_sources':[{'plan_id':'one','factory_id':'F1'},{'plan_id':'two','factory_id':'F2'}]}
    with pytest.raises(ValueError,match='不复制物理设备'):
        asyncio.run(load_production_sources(c,loader,NOW))


def test_device_cannot_be_assigned_to_a_different_declared_factory_than_native_order():
    base=native();base['orders'][0]['business_source']={'factory_id':'REAL-F'}
    c=contract(config(base));c['parts'][0]['factory_id']='A'
    with pytest.raises(CoherenceError,match='工厂与原生产工单归属'):
        build_chain(base,c,supplies())


def test_two_materials_can_share_a_single_trip_and_total_payload_is_checked():
    from .test_source_alignment import tiny_doc, MACHINES
    from metaforge.operations.sources import production_plan
    from metaforge.operations.plans import normalize_plan
    doc=tiny_doc(); second=copy.deepcopy(doc['jobs'][0]);second['name']='第二部件';doc['jobs'].append(second)
    original=copy.deepcopy(doc['schedule_results']['ts']['gantt_data'])
    for row in original:
        row['job_name']=second['name'];row['start']+=10;row['end']+=10
    doc['schedule_results']['ts']['gantt_data']+=original
    base=normalize_plan(production_plan(doc,MACHINES,[],NOW,solver='ts',time_unit='minutes'))
    c=contract(config(base));c['parts'][0]['factory_id']='F1'
    order=base['orders'][1]
    c['assembly_bom']['lines'].append({'id':'SELF2','material_id':'PART-B','spec':'规格B','uom':'件','per_unit':1,'process_id':0})
    c['parts'].append({'order_id':order['id'],'produced_quantity':2,'per_unit':1,'process_id':0,'bom_line_id':'SELF2',
        'business_material_id':'PART-B','spec':'规格B','uom':'件','factory_id':'F1','mapping_confirmed':True})
    trip(c,c['parts'][0]['order_id'],trip_group='GROUP')
    trip(c,order['id'],id='TRIP2',trip_group='GROUP',material='PART-B',spec='规格B')
    plan=build_chain(base,c,supplies())
    transports=[t for t in plan['tasks'] if t['kind']=='transport']
    assert len(transports)==1 and len(transports[0]['inputs'])==2 and transports[0]['quantity']==4
    final,_=advance(new_state(plan,NOW),max(r['end_at'] for r in plan['schedule'])+1)
    assert final['status']=='idle'
    c['inbound_shipments'][1]['load_units']=4
    with pytest.raises(CoherenceError,match='合车后的折算载荷超过'):build_chain(base,c,supplies())


def test_two_factories_and_external_procurement_form_one_valid_delivery_chain():
    import asyncio
    from bson import ObjectId
    from metaforge.operations.distributed import load_production_sources
    from metaforge.operations.sources import production_plan
    from metaforge.operations.chain_sources import route_source
    from .test_source_alignment import tiny_doc, MACHINES
    doc1=tiny_doc();doc1['jobs'][0]['quantity']=5;doc1['factory_id']='F1'
    doc1['jobs'][0].update(output_material_id='PART-A',spec='规格A',unit='件')
    for t in doc1['jobs'][0]['tasks']:t['machine_options']=[t['machine_id']]
    doc2=copy.deepcopy(doc1);doc2['_id']=ObjectId('000000000000000000000099');doc2['factory_id']='F2';doc2['jobs'][0]['name']='部件B'
    doc2['jobs'][0].update(output_material_id='PART-B',spec='规格B')
    for t in doc2['jobs'][0]['tasks']:t['machine_id']=4;t['machine_options']=[4]
    for r in doc2['schedule_results']['ts']['gantt_data']:r['machine_id']=4;r['job_name']='部件B'
    docs={str(d['_id']):d for d in (doc1,doc2)}
    async def loader(s,start):return production_plan(docs[s['plan_id']],MACHINES,[],start,solver='ts',time_unit='minutes')
    selections=[{'plan_id':str(doc1['_id']),'factory_id':'F1'},{'plan_id':str(doc2['_id']),'factory_id':'F2'}]
    base=asyncio.run(load_production_sources({'production_sources':selections},loader,NOW))
    c=contract(config(base));c['units']=5;c['parts'][0]['factory_id']='F1'
    c['parts'][0]['produced_quantity']=5
    c['parts'].append({'order_id':base['orders'][1]['id'],'produced_quantity':5,'per_unit':1,'process_id':0,'bom_line_id':'SELF2',
        'business_material_id':'PART-B','spec':'规格B','uom':'件','factory_id':'F2','mapping_confirmed':True})
    c['assembly_bom']['lines'].append({'id':'SELF2','material_id':'PART-B','spec':'规格B','uom':'件','per_unit':1,'process_id':0})
    purchasing(c)
    c['additional_supplies'][0]['quantity']=5;c['procurement_orders'][0]['quantity']=5
    c['inbound_shipments'][0].update(quantity=5,load_units=5,vehicle_id='SUPPLIER-TRUCK')
    trip(c,c['parts'][0]['order_id'],origin='F1',quantity=5,id='FACTORY1',vehicle_id='F1-TRUCK',load_units=5)
    trip(c,c['parts'][1]['order_id'],origin='F2',material='PART-B',quantity=5,id='FACTORY2',vehicle_id='F2-TRUCK',spec='规格B',load_units=5)
    from .test_chain import delivery_config
    route=route_source('Stage2_Balanced:1:0');route['publication']={'verified':True,'run_id':'fixture-published','effective_config':{'VEHICLE_CAP':12}}
    delivery_config(c,route,NOW);c.update(dispatch_product_id='FRIDGE-A',dispatch_spec='型号A',dispatch_uom='台',dispatch_depot_id='3')
    plan=build_chain(base,c,supplies(0),logistics=route)
    assert plan['business_validation']['passed'] and len(plan['business_validation']['inbound_tasks'])==3
    final,_=advance(new_state(plan,NOW),max(s['end_at'] for s in plan['schedule'])+1)
    assert final['status']=='idle' and all(t['status']=='completed' for t in final['tasks'].values())
    assert final['inventory']['warehouse|chain:finished']==0
    for customer in route['customers']: customer['product_id']='WRONG-PRODUCT'
    with pytest.raises(CoherenceError,match='原订单product_id'): build_chain(base,c,supplies(0),logistics=route)


def test_same_truck_cannot_jump_from_supplier_receipt_to_another_factory():
    base=native();c=purchasing(contract(config(base)));c['parts'][0]['factory_id']='F1'
    trip(c,c['parts'][0]['order_id'],origin='F1',id='SECOND',ship_at=NOW+6000)
    with pytest.raises(ValueError,match='车辆前后地点'):
        build_chain(base,c,supplies(0))
