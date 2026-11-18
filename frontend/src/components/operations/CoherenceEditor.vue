<template>
  <div class="coherence-editor">
    <p class="hint">核对BOM，将自制、外购与运输对应。人工映射需确认。</p>
    <div class="grid"><el-input v-model="cfg.assembly_bom.product_id" placeholder="成品编码" /><el-input v-model="cfg.assembly_bom.spec" placeholder="成品规格" /><el-input v-model="cfg.assembly_bom.revision" placeholder="BOM版本" /><el-input v-model="cfg.assembly_bom.assembly_site" placeholder="组装厂/收货地点标识" /></div>
    <el-button size="small" class="spaced" @click="seed">生成BOM草稿</el-button>
    <el-button size="small" @click="cfg.assembly_bom.lines.push({id: uid(), material_id:'',spec:'',uom:'件',per_unit:1,process_id:0})">补充需求</el-button>
    <el-table :data="cfg.assembly_bom.lines" size="small" max-height="250">
      <el-table-column label="物料编码" min-width="150"><template #default="{row}"><el-input v-model="row.material_id" size="small" /></template></el-table-column>
      <el-table-column label="规格" width="115"><template #default="{row}"><el-input v-model="row.spec" size="small" /></template></el-table-column>
      <el-table-column label="单位" width="70"><template #default="{row}"><el-input v-model="row.uom" size="small" /></template></el-table-column>
      <el-table-column label="每台需求" width="115"><template #default="{row}"><el-input-number v-model="row.per_unit" :min="0.001" size="small" controls-position="right" /></template></el-table-column>
      <el-table-column label="消耗工序" width="135"><template #default="{row}"><el-select v-model="row.process_id" size="small"><el-option v-for="p in catalog.processes" :key="p.id" :value="p.id" :label="p.name" /></el-select></template></el-table-column>
      <el-table-column width="65"><template #default="{row}"><el-button link type="danger" @click="cfg.assembly_bom.lines = cfg.assembly_bom.lines.filter(l=>l.id!==row.id)">删除</el-button></template></el-table-column>
    </el-table>
    <h4>供给对应关系</h4>
    <el-table :data="bindings" size="small" max-height="280">
      <el-table-column label="来源" min-width="190"><template #default="{row}">{{row.kind==='factory'?'自有工厂':'外购'}} · {{row.data.name}}</template></el-table-column>
      <el-table-column label="BOM需求" min-width="170"><template #default="{row}"><el-select v-model="row.data.bom_line_id" size="small" @change="bind(row)"><el-option v-for="l in cfg.assembly_bom.lines" :key="l.id" :value="l.id" :label="`${l.material_id} / ${l.spec} / ${l.uom}`" /></el-select></template></el-table-column>
      <el-table-column label="工厂 / 供应商" min-width="155"><template #default="{row}"><el-input v-if="row.kind==='factory'" v-model="row.data.factory_id" size="small" /><el-input v-else v-model="row.data.supplier_id" size="small" /></template></el-table-column>
      <el-table-column label="已核对" width="110"><template #default="{row}"><el-checkbox v-model="row.data.mapping_confirmed" /></template></el-table-column>
    </el-table>
    <el-collapse class="spaced"><el-collapse-item title="采购与到货" name="po">
      <el-button size="small" @click="addPurchase">新增采购单</el-button>
      <div v-for="po in cfg.procurement_orders" :key="po.id" class="purchase">
        <div class="grid"><el-input v-model="po.id" placeholder="采购单号" /><el-select v-model="po.material_id" placeholder="所购外购物料" @change="fillPurchase(po)"><el-option v-for="r in cfg.purchased.filter(r=>r.enabled)" :key="r.material_id" :value="r.material_id" :label="r.name" /></el-select><el-input v-model="po.supplier_id" placeholder="供应商标识" /><el-input-number v-model="po.quantity" :min="0.001" controls-position="right" /></div>
        <div class="grid"><el-input v-model="po.spec" placeholder="采购规格" /><el-input v-model="po.uom" placeholder="单位" /><el-input v-model="po.origin_site" placeholder="供应商发货地点" /><el-input v-model="po.delivery_site" placeholder="采购收货地点" /></div>
        <label>供应商备货就绪（北京时间） <input class="date-input" type="datetime-local" :value="local(po.ready_at)" @input="po.ready_at = parse($event.target.value)" /></label><el-button link type="danger" @click="cfg.procurement_orders=cfg.procurement_orders.filter(r=>r!==po)">删除采购单</el-button>
      </div>
      <div v-for="s in supplies" :key="s.id" class="supply-link"><span>{{s.name}} · {{s.quantity}} {{s.material_id}}</span><el-select v-model="cfg.procurement_links[s.id]" placeholder="必须选择对应采购单"><el-option v-for="po in cfg.procurement_orders" :key="po.id" :value="po.id" :label="po.id" /></el-select></div>
      <p class="hint">未来到货需关联采购单，运输完成后入库。</p>
    </el-collapse-item></el-collapse>
    <h4>入厂运输</h4>
    <el-button size="small" @click="addTrip">新增运输明细</el-button>
    <p class="hint">合装请用相同车次、车辆和时刻；载荷合计不能超容量。</p>
    <div v-for="t in cfg.inbound_shipments" :key="t.id" class="trip">
      <div class="grid"><el-select v-model="t.source_id" placeholder="关联工厂产出 / 采购到货" @change="fillTrip(t)"><el-option v-for="s in sources" :key="s.id" :value="s.id" :label="s.name" /></el-select><el-input v-model="t.trip_group" placeholder="车次标识（合车用同一标识）" /><el-input v-model="t.vehicle_id" placeholder="车辆标识" /><el-input v-model="t.material_id" placeholder="物料编码" /></div>
      <div class="grid"><el-input v-model="t.from_site" placeholder="起点" /><el-input v-model="t.to_site" placeholder="终点" /><el-input v-model="t.spec" placeholder="规格" /><el-input v-model="t.uom" placeholder="物料单位" /></div>
      <div class="grid"><label>运输物料数量<el-input-number v-model="t.quantity" :min="0.001" controls-position="right" /></label><label>折算载荷<el-input-number v-model="t.load_units" :min="0.001" controls-position="right" /></label><label>车辆容量<el-input-number v-model="t.capacity" :min="0.001" controls-position="right" /></label><el-input v-model="t.capacity_uom" placeholder="运力单位（如kg或标准箱）" /></div>
      <div class="grid"><label>发运（北京时间）<input class="date-input" type="datetime-local" :value="local(t.ship_at)" @input="t.ship_at=parse($event.target.value);updateArrival(t)" /></label><label>装载分钟<el-input-number v-model="t.loading_minutes" :min="0" controls-position="right" @change="updateArrival(t)" /></label><label>行驶分钟<el-input-number v-model="t.travel_minutes" :min="0.001" controls-position="right" @change="updateArrival(t)" /></label><label>卸货分钟<el-input-number v-model="t.unloading_minutes" :min="0" controls-position="right" @change="updateArrival(t)" /></label></div>
      <span class="hint">预计送达：{{local(t.arrival_at).replace('T',' ') || '待填写发运与耗时'}}</span><el-button link type="danger" @click="cfg.inbound_shipments=cfg.inbound_shipments.filter(r=>r!==t)">删除运输明细</el-button>
    </div>
    <div v-if="cfg.delivery_mode==='saved'" class="purchase"><h4>成品配送</h4><div class="grid"><el-input v-model="cfg.dispatch_product_id" placeholder="配送成品编码" /><el-input v-model="cfg.dispatch_spec" placeholder="成品规格" /><el-input v-model="cfg.dispatch_uom" placeholder="成品单位" /><el-input v-model="cfg.dispatch_depot_id" placeholder="组装成品仓对应原路线仓库编号" /></div><p class="hint">{{route?.publication?.message || '选择路线后核对来源版本'}}。未验证的旧路线需重新计算。</p></div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
const props=defineProps({config:Object,catalog:Object,route:Object})
const cfg=computed(()=>props.config)
const uid=()=>globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
const local=v=>v?new Date((typeof v==='number'?v*1000:new Date(v).getTime())+8*3600000).toISOString().slice(0,16):''
const parse=v=>v?new Date(`${v}+08:00`).toISOString():''
const bindings=computed(()=>[...cfg.value.parts.filter(r=>r.enabled).map(data=>({kind:'factory',data})),...cfg.value.purchased.filter(r=>r.enabled).map(data=>({kind:'purchase',data}))])
const supplies=computed(()=>[...(props.catalog.supply?.state?.deliveries||[]).filter(d=>['planned','on_the_way'].includes(d.status)).map(d=>({...d,id:`chain:supply:${d.id}`,name:d.supplier_name})),...cfg.value.additional_supplies.map(d=>({...d,id:`chain:manual-supply:${d.id}`}))])
const sources=computed(()=>[...cfg.value.parts.filter(r=>r.enabled).map(r=>({id:r.order_id,name:r.name,material_id:r.business_material_id,spec:r.spec,uom:r.uom,from_site:r.factory_id,quantity:Number(r.per_unit)*cfg.value.units})),...supplies.value.map(s=>{const po=cfg.value.procurement_orders.find(p=>p.id===cfg.value.procurement_links[s.id]);return {...s,material_id:po?.material_id||s.material_id,spec:po?.spec,uom:po?.uom,from_site:po?.origin_site}})])
function bind(row){const l=cfg.value.assembly_bom.lines.find(l=>l.id===row.data.bom_line_id);if(l)Object.assign(row.data,{business_material_id:l.material_id,spec:l.spec,uom:l.uom,mapping_confirmed:false})}
function seed(){if(cfg.value.assembly_bom.lines.length)return;for(const row of bindings.value){const r=row.data;const l={id:uid(),material_id:row.kind==='purchase'?r.material_id:(r.business_source?.output_material_id||r.name),spec:r.business_source?.spec||'标准案例规格（需核对）',uom:r.business_source?.uom||'件',per_unit:r.per_unit,process_id:r.process_id};cfg.value.assembly_bom.lines.push(l);r.bom_line_id=l.id;bind(row)}cfg.value.dispatch_product_id=cfg.value.assembly_bom.product_id;cfg.value.dispatch_spec=cfg.value.assembly_bom.spec;cfg.value.dispatch_uom=cfg.value.assembly_bom.uom}
function addPurchase(){cfg.value.procurement_orders.push({id:`PO-${uid().slice(0,8)}`,material_id:'',supplier_id:'',quantity:null,spec:'',uom:'件',origin_site:'',delivery_site:cfg.value.assembly_bom.assembly_site,ready_at:''})}
function fillPurchase(po){const r=cfg.value.purchased.find(r=>r.material_id===po.material_id);if(r)Object.assign(po,{supplier_id:r.supplier_id,spec:r.spec,uom:r.uom})}
function addTrip(){cfg.value.inbound_shipments.push({id:uid(),trip_group:'',source_id:'',vehicle_id:'',material_id:'',spec:'',uom:'件',from_site:'',to_site:cfg.value.assembly_bom.assembly_site,quantity:null,load_units:null,capacity:null,capacity_uom:'标准箱',ship_at:'',loading_minutes:0,travel_minutes:null,unloading_minutes:0})}
function fillTrip(t){const s=sources.value.find(s=>s.id===t.source_id);if(s)Object.assign(t,{from_site:s.from_site,to_site:cfg.value.assembly_bom.assembly_site,material_id:s.material_id,spec:s.spec,uom:s.uom,quantity:s.quantity})}
function updateArrival(t){if(!t.ship_at||!t.travel_minutes)return;t.arrival_at=new Date(new Date(t.ship_at).getTime()+[t.loading_minutes,t.travel_minutes,t.unloading_minutes].reduce((a,v)=>a+Number(v||0),0)*60000).toISOString();if(t.source_id.startsWith('chain:manual-supply:')){const d=cfg.value.additional_supplies.find(d=>`chain:manual-supply:${d.id}`===t.source_id);if(d)d.available_at=t.arrival_at}else if(t.source_id.startsWith('chain:supply:'))cfg.value.arrival_overrides[t.source_id.slice('chain:supply:'.length)]=t.arrival_at}
</script>
<style scoped>
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:9px 0}.spaced{margin-top:15px}.hint{font-size:12px;line-height:1.7;color:#7c8da3}.purchase,.trip{border:1px solid #e3eaf3;background:#f8fafc;border-radius:7px;padding:12px;margin:12px 0}.supply-link{display:flex;gap:14px;align-items:center;margin:10px 0;font-size:12px}.date-input{box-sizing:border-box;width:100%;border:1px solid #dce3ed;border-radius:5px;height:32px;padding:4px 7px}.grid label{font-size:11px;color:#75859b}.grid label>*{display:block;margin-top:5px}:deep(.el-input-number){width:100%;max-width:145px}h4{color:#537198;font-size:13px;font-weight:500;margin:17px 0 8px}@media(max-width:750px){.grid{grid-template-columns:1fr 1fr}}
</style>
