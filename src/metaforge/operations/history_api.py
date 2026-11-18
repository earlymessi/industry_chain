from __future__ import annotations
import asyncio, copy
from fastapi import Body, HTTPException
from .history import records, read_record, assembly_result
from .chain_sources import process_catalog, supply_source
from .baselines import dataset_root
from .cases import rebase_case
from .models import timestamp

def attach(router, service, build):
    @router.get('/data-center/{module}')
    async def catalog(module:str):
        try: return {'records':await asyncio.to_thread(records,module)}
        except ValueError as exc: raise HTTPException(422,str(exc))

    @router.get('/data-center/{module}/{key}')
    async def detail(module:str,key:str):
        try:
            record=await asyncio.to_thread(read_record,module,key)
            payload=record['payload']
            if module=='assembly':
                selected=next((i+1 for i,reason in enumerate(payload.get('compatibility',[])) if not reason),1)
                record['selected_episode']=selected
                record['assembly']=assembly_result(key,selected) if payload['episodes'] else None
                record['processes']=process_catalog()
                record['definition']=payload.get('definition')
                config=payload.get('chain_config')
                record['supply']=supply_source(dataset_root(config['source_dataset'])) if config else None
                record['compatible']=bool(payload['episodes']) and any(not reason for reason in payload.get('compatibility',['']))
            return record
        except (ValueError,KeyError,OSError) as exc: raise HTTPException(422,str(exc))

    @router.post('/data-center/{module}/{key}/prepare')
    async def prepare(module:str,key:str,body:dict=Body(default={})):
        try:
            record=read_record(module,key)
            config=copy.deepcopy(record['payload'].get('chain_config'))
            if not config: raise ValueError('此结果尚未关联全链路，请在计划配置中选择生产、组装和配送来源')
            start=timestamp(body['start_at']) if body.get('start_at') else service.clock()+900
            if start<service.clock()+5: raise ValueError('执行起点须晚于当前时刻')
            config=rebase_case({'mode':'simulation','start_at':config['start_at'],'chain_config':config},start)['chain_config']
            config['confirmed']=True
            plan,_=await build(config)
            config['confirmed']=False
            return {'config':config,'summary':plan['chain_summary'],'task_count':len(plan['tasks'])}
        except (ValueError,KeyError,TypeError,OSError) as exc: raise HTTPException(422,str(exc))
