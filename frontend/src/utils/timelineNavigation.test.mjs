import test from 'node:test'
import assert from 'node:assert/strict'
import {createRenderer,h} from 'vue'
import {liveTimelineWindow,shiftTimelineWindow,dragTimelineWindow} from './timelineNavigation.js'
import {useTimelinePan} from '../composables/useTimelinePan.js'

const NOW=Date.parse('2026-11-17T10:00:00Z')/1000

test('各粒度以当前时间定位且窗口跨度准确',()=>{
 for(const hours of [4,24,168,672]){
  const range=liveTimelineWindow(NOW,hours)
  assert.ok(range.begin<NOW && range.end>NOW)
  assert.equal(range.end-range.begin,hours*3600)
  const next=liveTimelineWindow(NOW+60,hours)
  assert.equal(next.begin-range.begin,60)
 }
})

test('拖向右边查看过去、拖向左边查看未来，原窗口不被改写',()=>{
 const range=liveTimelineWindow(NOW,4),before={...range}
 assert.equal(dragTimelineWindow(range,200,1000).begin,range.begin-2880)
 assert.equal(dragTimelineWindow(range,-200,1000).begin,range.begin+2880)
 assert.deepEqual(range,before)
 assert.equal(shiftTimelineWindow(range,10*86400).end,range.end+10*86400)
})

function fixture(){
 let pan,range=liveTimelineWindow(NOW,4)
 const changes=[],captures=new Set()
 const target={getBoundingClientRect:()=>({width:1000}),setPointerCapture:id=>captures.add(id),hasPointerCapture:id=>captures.has(id),releasePointerCapture:id=>captures.delete(id)}
 const renderer=createRenderer({createElement:()=>({}),insert(){},remove(){},patchProp(){},createText:()=>({}),createComment:()=>({}),setText(){},setElementText(){},parentNode(){},nextSibling(){}})
 const app=renderer.createApp({setup(){pan=useTimelinePan(()=>range,value=>{changes.push(value);range=value});return ()=>h('div')}})
 app.mount({});pan.element.value=target
 const event=(x,y=100)=>({button:0,isPrimary:true,pointerId:1,clientX:x,clientY:y,currentTarget:target,preventDefault(){}})
 return {pan,changes,captures,event,range:()=>range,dispose:()=>app.unmount()}
}

test('水平拖动以按下时的范围计算，持续拖动不会累加漂移',()=>{
 const f=fixture(),original={...f.range()}
 f.pan.start(f.event(300));assert.equal(f.captures.size,0)
 f.pan.move(f.event(400));f.pan.move(f.event(500))
 assert.equal(f.pan.state.dragging,true)
 assert.deepEqual(f.range(),dragTimelineWindow(original,200,825))
 f.pan.end(f.event(500));assert.equal(f.pan.state.dragging,false);assert.equal(f.captures.size,0)
 f.dispose()
})

test('普通任务点击不捕获指针，拖动后的点击不会误开任务',()=>{
 const f=fixture();let blocked=0
 f.pan.start(f.event(100));f.pan.move(f.event(102));f.pan.end(f.event(102))
 f.pan.suppressClick({detail:1,preventDefault:()=>blocked++,stopPropagation(){}})
 assert.equal(blocked,0);assert.equal(f.changes.length,0)
 f.pan.start(f.event(100));f.pan.move(f.event(160));f.pan.end(f.event(160))
 f.pan.suppressClick({detail:1,preventDefault:()=>blocked++,stopPropagation(){}})
 assert.equal(blocked,1)
 f.pan.start(f.event(100));f.pan.end(f.event(100))
 f.pan.suppressClick({detail:1,preventDefault:()=>blocked++,stopPropagation(){}})
 assert.equal(blocked,1);f.dispose()
})

test('触屏上下滑动和普通滚轮保留纵向滚动，横向滚轮才平移时间',()=>{
 const f=fixture();let prevented=0
 f.pan.start(f.event(100));f.pan.move(f.event(102,140));assert.equal(f.changes.length,0)
 f.pan.wheel({deltaX:0,deltaY:100,shiftKey:false,preventDefault:()=>prevented++})
 assert.equal(f.changes.length,0);assert.equal(prevented,0)
 const old={...f.range()}
 f.pan.wheel({deltaX:100,deltaY:0,preventDefault:()=>prevented++})
 assert.equal(f.changes.length,1);assert.ok(f.range().begin>old.begin);assert.equal(prevented,1)
 f.dispose()
})
