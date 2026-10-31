<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { MetricCamera } from '../api/analysis'
import type { DelayPoint3D, DelayScene3D } from '../delay3D'
import { delayTrainColor, normalizeDelayPoint, projectDelayPoint, rotateDelayCamera, zoomDelayCamera } from '../delay3D'
import { defaultMetricCamera } from '../performanceMetrics'
const props = defineProps<{ scene: DelayScene3D; camera: MetricCamera; unit: 'minutes' | 'seconds'; activeTrainId: string }>()
const emit = defineEmits<{ 'update:camera': [camera: MetricCamera]; pick: [row: string, train: string] }>()
const shell = ref<HTMLElement | null>(null), canvas = ref<HTMLCanvasElement | null>(null), hovered = ref<DelayPoint3D | null>(null)
const dragging = ref(false), dense = computed(()=>props.scene.pointCount>16000)
let observer: ResizeObserver | undefined, theme: MutationObserver | undefined, disposed = false, frame = 0
let drag: {id:number;x:number;y:number;camera:MetricCamera;moved:boolean} | null = null
let hits: (DelayPoint3D & {sx:number;sy:number;depth:number;isolated:boolean})[] = []
const unitName = computed(()=>props.unit==='minutes'?'分钟':'秒')
const format = (seconds:number) => (Math.round(seconds/(props.unit==='minutes'?60:1)*100)/100).toLocaleString('zh-CN',{maximumFractionDigits:2})
const description = computed(()=>{
  const hit=hovered.value
  if(!hit)return ''
  const train=props.scene.trains.find(t=>t.id===hit.trainId), station=props.scene.stations.find(s=>s.key===hit.rowKey)
  return [train?.train_course_id, train?.train_base_date, station?.node_name_chn, (hit.field==='arrival'?'到达':'出发')+'偏差 '+format(hit.seconds)+unitName.value].filter(Boolean).join(' · ')
})
function queue() {
  if(disposed||frame)return
  frame=requestAnimationFrame(()=>{frame=0;draw()})
}
function draw() {
  const element=canvas.value, host=shell.value
  if(!element||!host||host.clientWidth<100||disposed)return
  const ctx=element.getContext('2d')
  if(!ctx)return
  const width=host.clientWidth,height=width<600?440:560,ratio=Math.min(window.devicePixelRatio||1,2)
  element.width=Math.round(width*ratio);element.height=Math.round(height*ratio)
  element.style.width=width+'px';element.style.height=height+'px'
  ctx.setTransform(ratio,0,0,ratio,0,0)
  const style=getComputedStyle(host), text=style.getPropertyValue('--text').trim()||'#24364b'
  const border=style.getPropertyValue('--border').trim()||'#dce4ed'
  ctx.fillStyle=style.getPropertyValue('--surface').trim()||'#ffffff';ctx.fillRect(0,0,width,height)
  ctx.font='12px "Microsoft YaHei", sans-serif';ctx.textBaseline='middle'
  const scene=props.scene
  const project=(p:{x:number;y:number;z:number})=>projectDelayPoint(normalizeDelayPoint(scene,p),props.camera,width,height)
  const segment=(a:{x:number;y:number},b:{x:number;y:number},color:string,dash:number[]=[],lineWidth=1)=>{
    ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.strokeStyle=color;ctx.lineWidth=lineWidth;ctx.setLineDash(dash);ctx.stroke()
  }
  const nx=Math.max(0,scene.stations.length-1),ny=Math.max(0,scene.trains.length-1)
  const floor=scene.zMin,roof=scene.zMax
  const labelBoxes:{x:number;y:number;w:number;h:number}[]=[]
  function label(value:string,x:number,y:number,anchor:CanvasTextAlign='center') {
    const w=ctx!.measureText(value).width, left=anchor==='left'?x:anchor==='right'?x-w:x-w/2
    if(left<4||left+w>width-4||y<8||y>height-8)return
    const box={x:left-3,y:y-8,w:w+6,h:16}
    if(labelBoxes.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y))return
    labelBoxes.push(box);ctx!.fillStyle=text;ctx!.textAlign=anchor;ctx!.fillText(value,x,y)
  }
  const ticks=(count:number,limit:number)=>Array.from(new Set(Array.from({length:Math.min(count,limit)},(_,i)=>Math.round(i*(count-1)/Math.max(1,Math.min(count,limit)-1)))))
  // Label the front edges, so station names stay clear of the waterfall surfaces.
  const azimuth=props.camera.azimuth*Math.PI/180
  const frontX=Math.sin(azimuth)>=0?nx:0,frontY=Math.cos(azimuth)>=0?ny:0
  const backX=nx-frontX,backY=ny-frontY
  const outward=(a:{x:number;y:number},b:{x:number;y:number},distance:number)=>{
    const length=Math.hypot(a.x-b.x,a.y-b.y)||1
    return {x:a.x+(a.x-b.x)/length*distance,y:a.y+(a.y-b.y)/length*distance}
  }
  const zBase=[{x:0,y:0},{x:nx,y:0},{x:0,y:ny},{x:nx,y:ny}].reduce((a,b)=>project({...a,z:floor}).x<project({...b,z:floor}).x?a:b)
  const origin=project({x:frontX,y:frontY,z:floor}),xEnd=project({x:backX,y:frontY,z:floor}),yEnd=project({x:frontX,y:backY,z:floor}),zEnd=project({...zBase,z:roof})
  segment(origin,xEnd,text);segment(origin,yEnd,text);segment(project({...zBase,z:floor}),zEnd,text)
  const xName=outward(project({x:nx/2,y:frontY,z:floor}),project({x:nx/2,y:backY,z:floor}),48)
  const yName=outward(project({x:frontX,y:ny/2,z:floor}),project({x:backX,y:ny/2,z:floor}),50)
  // Reserve axis names before packing category and numeric tick labels.
  label('X：车站',xName.x,xName.y);label('Y：车次号',yName.x,yName.y);label('Z：延误（'+unitName.value+'）',zEnd.x,zEnd.y-20)
  // Common categorical axes: no lines or surfaces are drawn between different trains.
  for(const x of ticks(scene.stations.length,7)){
    const a=project({x,y:frontY,z:floor}),b=project({x,y:backY,z:floor})
    segment(a,b,border)
    const station=scene.stations[x]
    const position=outward(a,b,18)
    label(station.node_name_chn+(station.occurrence>1?'#'+station.occurrence:''),position.x,position.y)
  }
  for(const y of ticks(scene.trains.length,9)){
    const a=project({x:frontX,y,z:floor}),b=project({x:backX,y,z:floor})
    segment(a,b,border)
    const train=scene.trains[y],same=scene.trains.filter(t=>t.train_course_id===train.train_course_id).length>1
    const position=outward(a,b,18)
    label(train.train_course_id+(same?' '+train.train_base_date:''),position.x,position.y,position.x<a.x?'right':'left')
  }
  for(let i=0;i<=4;i++){
    const z=floor+(roof-floor)*i/4,a=project({x:backX,y:backY,z}),b=project({x:frontX,y:backY,z}),c=project({x:backX,y:frontY,z})
    const tick=project({...zBase,z})
    segment(a,b,border);segment(a,c,border);label(format(z),tick.x-8,tick.y,'right')
  }
  const zero1=project({x:frontX,y:frontY,z:0}),zero2=project({x:backX,y:frontY,z:0}),zero3=project({x:frontX,y:backY,z:0})
  segment(zero1,zero2,border,[4,4]);segment(zero1,zero3,border,[4,4])
  const dark=document.documentElement.dataset.theme==='dark'
  const colors=new Map(scene.trains.map(t=>[t.id,delayTrainColor(t.id,dark)]))
  type ScreenPoint=ReturnType<typeof projectDelayPoint>
  const commands:{a:ScreenPoint;b:ScreenPoint;floorA:ScreenPoint;floorB:ScreenPoint;from:DelayPoint3D;to:DelayPoint3D;depth:number;fill:boolean}[]=[]
  hits=[]
  const arrivalFillTrains=new Set(scene.traces.filter(t=>t.field==='arrival'&&t.pieces.some(p=>p.length>1)).map(t=>t.trainId))
  for(const trace of scene.traces)for(const piece of trace.pieces){
    const projected=piece.map(point=>{
      const p=project(point)
      if(p.x>=0&&p.x<=width&&p.y>=0&&p.y<=height)hits.push({...point,sx:p.x,sy:p.y,depth:p.depth,isolated:piece.length===1})
      return p
    })
    for(let i=1;i<piece.length;i++){
      const from=piece[i-1],to=piece[i],a=projected[i-1],b=projected[i]
      commands.push({a,b,floorA:project({...from,z:0}),floorB:project({...to,z:0}),from,to,depth:(a.depth+b.depth)/2,fill:!dense.value&&(trace.field==='arrival'||!arrivalFillTrains.has(trace.trainId))})
    }
  }
  commands.sort((a,b)=>a.depth-b.depth)
  function fillPolygon(points:ScreenPoint[],color:string) {
    ctx!.beginPath();points.forEach((p,i)=>i?ctx!.lineTo(p.x,p.y):ctx!.moveTo(p.x,p.y));ctx!.closePath()
    ctx!.fillStyle=color;ctx!.globalAlpha=.2;ctx!.fill();ctx!.globalAlpha=1
  }
  for(const command of commands){
    const color=colors.get(command.from.trainId)!, {a,b,floorA,floorB,from,to}=command
    if(command.fill){
      if(from.z*to.z<0){
        const t=from.z/(from.z-to.z),cross=project({x:from.x+(to.x-from.x)*t,y:from.y,z:0})
        fillPolygon([a,cross,floorA],color);fillPolygon([cross,b,floorB],color)
      }else fillPolygon([a,b,floorB,floorA],color)
    }
    segment(a,b,color,from.field==='departure'?[5,4]:[],from.trainId===props.activeTrainId?2.8:1.5)
  }
  ctx.setLineDash([])
  for(const point of hits)if(hits.length<=5000||point.isolated){
    ctx.beginPath();ctx.arc(point.sx,point.sy,2.3,0,Math.PI*2);ctx.fillStyle=colors.get(point.trainId)!;ctx.fill()
  }
  if(hovered.value){
    const point=hits.find(h=>h.trainId===hovered.value!.trainId&&h.rowKey===hovered.value!.rowKey&&h.field===hovered.value!.field)
    if(point){ctx.beginPath();ctx.arc(point.sx,point.sy,5,0,Math.PI*2);ctx.strokeStyle=text;ctx.lineWidth=2;ctx.stroke()}
  }
}
function hit(x:number,y:number){
  let best:typeof hits[number]|null=null, distance=144
  for(const point of hits){
    const d=(point.sx-x)**2+(point.sy-y)**2
    if(d<distance-1||(Math.abs(d-distance)<1&&point.depth>(best?.depth??-Infinity))){best=point;distance=d}
  }
  return best
}
function pointerDown(event:PointerEvent){
  if(event.button!==0)return
  event.preventDefault();canvas.value?.setPointerCapture(event.pointerId);canvas.value?.focus({preventScroll:true})
  drag={id:event.pointerId,x:event.clientX,y:event.clientY,camera:{...props.camera},moved:false};dragging.value=true
}
function pointerMove(event:PointerEvent){
  if(drag&&drag.id===event.pointerId){
    const dx=event.clientX-drag.x,dy=event.clientY-drag.y
    if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true
    emit('update:camera',rotateDelayCamera(drag.camera,dx,dy));hovered.value=null;return
  }
  const box=canvas.value?.getBoundingClientRect()
  if(box){hovered.value=hit(event.clientX-box.left,event.clientY-box.top);queue()}
}
function pointerUp(event:PointerEvent){
  if(!drag||drag.id!==event.pointerId)return
  if(!drag.moved){const box=canvas.value?.getBoundingClientRect();if(box){const point=hit(event.clientX-box.left,event.clientY-box.top);if(point){hovered.value=point;emit('pick',point.rowKey,point.trainId);queue()}}}
  if(canvas.value?.hasPointerCapture(event.pointerId))canvas.value.releasePointerCapture(event.pointerId)
  drag=null;dragging.value=false
}
function stopDrag(){drag=null;dragging.value=false}
function wheel(event:WheelEvent){emit('update:camera',zoomDelayCamera(props.camera,event.deltaY))}
function reset(){emit('update:camera',defaultMetricCamera())}
function key(event:KeyboardEvent){
  if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){
    event.preventDefault();emit('update:camera',rotateDelayCamera(props.camera,event.key==='ArrowLeft'?-12:event.key==='ArrowRight'?12:0,event.key==='ArrowUp'?-12:event.key==='ArrowDown'?12:0))
  }else if(['+','=','-','Home'].includes(event.key)){
    event.preventDefault();if(event.key==='Home')reset();else emit('update:camera',zoomDelayCamera(props.camera,event.key==='-'?100:-100))
  }
}
function cameraValue(field:keyof MetricCamera,text:string){
  const value=Number(text);if(!Number.isFinite(value))return
  emit('update:camera',{...props.camera,[field]:value})
}
watch(()=>[props.scene,props.camera],()=>{hovered.value=null;queue()},{deep:false})
watch(()=>[props.unit,props.activeTrainId],queue,{deep:false})
onMounted(()=>{
  observer=new ResizeObserver(queue);if(shell.value)observer.observe(shell.value)
  theme=new MutationObserver(queue);theme.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});queue()
})
onUnmounted(()=>{disposed=true;observer?.disconnect();theme?.disconnect();if(frame)cancelAnimationFrame(frame)})
</script>
<template>
  <div class="metric-delay-3d">
    <div class="analysis-controls">
      <label>水平角 {{ Math.round(camera.azimuth) }}°<input type="range" min="-180" max="180" :value="camera.azimuth" @input="cameraValue('azimuth',($event.target as HTMLInputElement).value)" /></label>
      <label>俯仰角 {{ Math.round(camera.elevation) }}°<input type="range" min="10" max="80" :value="camera.elevation" @input="cameraValue('elevation',($event.target as HTMLInputElement).value)" /></label>
      <label>缩放 {{ camera.zoom.toFixed(2) }}×<input type="range" min="0.6" max="2.5" step="0.01" :value="camera.zoom" @input="cameraValue('zoom',($event.target as HTMLInputElement).value)" /></label>
      <button type="button" @click="reset">重置三维视角</button>
    </div>
    <p class="muted">X：车站 · Y：车次号 · Z：延误（{{ unitName }}，负值为提前）。拖动旋转，滚轮缩放；方向键旋转，Home重置。实线为到达，虚线为出发，各列车不相连，缺失时刻断开。</p>
    <div ref="shell" class="metric-delay-3d-stage">
      <canvas ref="canvas" tabindex="0" role="img" aria-label="可旋转的多列车三维到发偏差瀑布图" :class="{'is-dragging':dragging}" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="stopDrag" @lostpointercapture="stopDrag" @pointerleave="hovered=null;queue()" @wheel.prevent="wheel" @dblclick="reset" @keydown="key">三维到发偏差图；可使用角度滑块调整视角。</canvas>
    </div>
    <p class="metric-3d-point-detail" aria-live="polite">{{ description || '指向数据点查看车次、车站、事件及偏差；点击数据点联动热力表明细。' }}</p>
    <small v-if="dense">当前为高密度线框显示，所有选中列车的数据仍参与绘制。</small>
  </div>
</template>
