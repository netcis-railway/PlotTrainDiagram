<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { DelaySnapshot, MetricDisplay, MetricTimeHeatmap } from '../api/analysis'
import { defaultTimeHeatmap } from '../performanceMetrics'
import { buildTimeHeatmap, formatHeatmapTime, timeHeatmapBucket, timeHeatmapColor, type HeatmapField } from '../timeHeatmap'

const props = defineProps<{ data: DelaySnapshot; state: MetricDisplay }>()
const emit = defineEmits<{ 'update:display': [display: MetricTimeHeatmap] }>()
const display = computed(() => props.state.time_heatmap || defaultTimeHeatmap())
const scene = computed(() => buildTimeHeatmap(props.data,props.state,display.value))
const viewport = ref<HTMLElement | null>(null), canvas = ref<HTMLCanvasElement | null>(null), width = ref(960)
const hovered = ref<{station:number;column:number} | null>(null)
const labelWidth = 126, headerHeight = 52, rowHeight = 32
const layout = computed(() => {
  const cellWidth = Math.max(2,(width.value-labelWidth)/Math.max(1,scene.value.columns))
  return {cellWidth,width:Math.ceil(labelWidth+scene.value.columns*cellWidth),height:headerHeight+scene.value.stations.length*rowHeight}
})
const unit = computed(() => props.state.unit==='seconds'?'秒':'分钟')
const format = (value:number) => (value/(props.state.unit==='seconds'?1:60)).toLocaleString('zh-CN',{maximumFractionDigits:2})
const description = computed(() => {
  const hit = hovered.value, model = scene.value
  if (!hit || !model.stations[hit.station]) return ''
  const bucket = timeHeatmapBucket(model,hit.station,hit.column)
  const start = model.start+hit.column*model.step
  return model.stations[hit.station].node_name_chn+' · ['+formatHeatmapTime(start,true)+' – '+formatHeatmapTime(start+model.step,true)+') · 累计晚点 '+format(bucket?.total||0)+unit.value+' · 有效事件 '+(bucket?.count||0)+' 个（到达 '+(bucket?.arrivalCount||0)+'、出发 '+(bucket?.departureCount||0)+'），晚点事件 '+(bucket?.lateCount||0)+' 个'
})
const gradient = computed(() => 'linear-gradient(to right,'+Array.from({length:5},(_,i)=>timeHeatmapColor(i,4)).join(',')+')')
let observer: ResizeObserver | undefined, theme: MutationObserver | undefined, frame=0, disposed=false, keyboardSelection=false
function queue() {
  if(disposed||frame)return
  frame=requestAnimationFrame(()=>{frame=0;draw()})
}
function interval(value:string) {
  const minutes=Number(value)
  if(minutes===1||minutes===10||minutes===60)emit('update:display',{...display.value,interval_minutes:minutes})
}
function toggle(field:HeatmapField,checked:boolean) {
  const fields=new Set(display.value.fields)
  if(checked)fields.add(field);else fields.delete(field)
  emit('update:display',{...display.value,fields:[...fields]})
}
function draw() {
  const host=viewport.value,element=canvas.value
  if(!host||!element||host.clientWidth<100||disposed)return
  const ctx=element.getContext('2d')
  if(!ctx)return
  const w=host.clientWidth,h=host.clientHeight,ratio=Math.min(window.devicePixelRatio||1,2)
  const sx=host.scrollLeft,sy=host.scrollTop,model=scene.value,cw=layout.value.cellWidth
  element.width=Math.round(w*ratio);element.height=Math.round(h*ratio)
  element.style.width=w+'px';element.style.height=h+'px'
  element.style.transform='translate('+sx+'px,'+sy+'px)'
  ctx.setTransform(ratio,0,0,ratio,0,0)
  const style=getComputedStyle(host),surface=style.getPropertyValue('--surface').trim()||'#ffffff'
  const text=style.getPropertyValue('--text').trim()||'#24364b',border=style.getPropertyValue('--border').trim()||'#dce4ed'
  ctx.fillStyle=surface;ctx.fillRect(0,0,w,h)
  const firstRow=Math.max(0,Math.floor(sy/rowHeight)),lastRow=Math.min(model.stations.length,Math.ceil((sy+h-headerHeight)/rowHeight))
  const firstCol=Math.max(0,Math.floor(sx/cw)),lastCol=Math.min(model.columns,Math.ceil((sx+w-labelWidth)/cw))
  ctx.save();ctx.beginPath();ctx.rect(labelWidth,headerHeight,w-labelWidth,h-headerHeight);ctx.clip()
  ctx.fillStyle=timeHeatmapColor(0,model.max);ctx.fillRect(labelWidth,headerHeight,w-labelWidth,h-headerHeight)
  for(let r=firstRow;r<lastRow;r++) {
    const y=headerHeight+r*rowHeight-sy
    for(let col=firstCol;col<lastCol;col++) {
      const bucket=timeHeatmapBucket(model,r,col)
      if(!bucket?.total)continue
      ctx.fillStyle=timeHeatmapColor(bucket.total,model.max)
      ctx.fillRect(labelWidth+col*cw-sx,y,cw+.25,rowHeight)
    }
    ctx.beginPath();ctx.moveTo(labelWidth,y+rowHeight);ctx.lineTo(w,y+rowHeight)
    ctx.strokeStyle='rgba(255,255,255,0.12)';ctx.lineWidth=1;ctx.stroke()
  }
  if(hovered.value) {
    ctx.strokeStyle='#ffffff';ctx.lineWidth=2
    ctx.strokeRect(labelWidth+hovered.value.column*cw-sx,headerHeight+hovered.value.station*rowHeight-sy,cw,rowHeight)
  }
  ctx.restore()
  ctx.font='12px "Microsoft YaHei", sans-serif';ctx.textBaseline='middle';ctx.fillStyle=text
  ctx.textAlign='right'
  for(let r=firstRow;r<lastRow;r++) {
    let name=model.stations[r].node_name_chn||model.stations[r].node_name
    while(name.length>1&&ctx.measureText(name).width>labelWidth-18)name=name.slice(0,-2)+'…'
    ctx.fillText(name,labelWidth-10,headerHeight+(r+.5)*rowHeight-sy)
  }
  ctx.fillStyle=surface;ctx.fillRect(0,0,w,headerHeight)
  ctx.fillStyle=text;ctx.textAlign='left';ctx.fillText('车站 / 实际时间',8,26)
  const target=90/cw*model.step
  const tickStep=[60,600,1800,3600,7200,10800,14400,21600,43200,86400,172800,604800].find(s=>s>=target)||Math.ceil(target/86400)*86400
  const visibleStart=model.start+firstCol*model.step
  ctx.save();ctx.beginPath();ctx.rect(labelWidth,0,w-labelWidth,headerHeight);ctx.clip()
  for(let t=Math.ceil(visibleStart/tickStep)*tickStep;t<Math.min(model.end,model.start+lastCol*model.step);t+=tickStep) {
    const x=labelWidth+(t-model.start)/model.step*cw-sx
    const stamp=formatHeatmapTime(t,true)
    ctx.fillStyle=text;ctx.textAlign='left';ctx.fillText(stamp.slice(0,10),x+3,15);ctx.fillText(stamp.slice(11),x+3,34)
    ctx.beginPath();ctx.moveTo(x,headerHeight-5);ctx.lineTo(x,headerHeight);ctx.strokeStyle=border;ctx.lineWidth=1;ctx.stroke()
  }
  ctx.restore()
  ctx.beginPath();ctx.moveTo(labelWidth,0);ctx.lineTo(labelWidth,h);ctx.moveTo(0,headerHeight);ctx.lineTo(w,headerHeight)
  ctx.strokeStyle=border;ctx.lineWidth=1;ctx.stroke()
}
function point(event:MouseEvent) {
  keyboardSelection=false
  const host=viewport.value,box=canvas.value?.getBoundingClientRect()
  if(!host||!box)return
  const x=event.clientX-box.left,y=event.clientY-box.top
  const station=Math.floor((y-headerHeight+host.scrollTop)/rowHeight),column=Math.floor((x-labelWidth+host.scrollLeft)/layout.value.cellWidth)
  hovered.value=x>=labelWidth&&y>=headerHeight&&station>=0&&station<scene.value.stations.length&&column>=0&&column<scene.value.columns?{station,column}:null
  queue()
}
function scroll() {if(!keyboardSelection)hovered.value=null;queue()}
function key(event:KeyboardEvent) {
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)||!scene.value.count)return
  event.preventDefault()
  keyboardSelection=true
  const current=hovered.value||{station:0,column:0}
  const station=Math.max(0,Math.min(scene.value.stations.length-1,current.station+(event.key==='ArrowDown'?1:event.key==='ArrowUp'?-1:0)))
  const column=event.key==='Home'?0:event.key==='End'?scene.value.columns-1:Math.max(0,Math.min(scene.value.columns-1,current.column+(event.key==='ArrowRight'?1:event.key==='ArrowLeft'?-1:0)))
  hovered.value={station,column}
  const host=viewport.value
  if(host) {
    const x=column*layout.value.cellWidth,y=station*rowHeight
    if(x<host.scrollLeft)host.scrollLeft=x
    else if(x+layout.value.cellWidth>host.scrollLeft+host.clientWidth-labelWidth)host.scrollLeft=x+layout.value.cellWidth-host.clientWidth+labelWidth
    if(y<host.scrollTop)host.scrollTop=y
    else if(y+rowHeight>host.scrollTop+host.clientHeight-headerHeight)host.scrollTop=y+rowHeight-host.clientHeight+headerHeight
  }
  queue()
}
watch(viewport,(node,old)=>{if(old)observer?.unobserve(old);if(node){observer?.observe(node);width.value=node.clientWidth||960;queue()}})
watch(scene,()=>{hovered.value=null;if(viewport.value){viewport.value.scrollLeft=0;viewport.value.scrollTop=0}void nextTick(queue)})
watch(()=>props.state.unit,queue)
watch(layout,queue)
onMounted(()=>{
  observer=new ResizeObserver(entries=>{const w=entries[0]?.contentRect.width;if(w&&w>=100)width.value=w;queue()})
  if(viewport.value){width.value=viewport.value.clientWidth;observer.observe(viewport.value)}
  theme=new MutationObserver(queue);theme.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});queue()
})
onUnmounted(()=>{disposed=true;observer?.disconnect();theme?.disconnect();if(frame)cancelAnimationFrame(frame)})
</script>
<template>
  <div class="metric-time-heatmap">
    <div class="analysis-controls">
      <label>时间分辨率<select :value="display.interval_minutes" @change="interval(($event.target as HTMLSelectElement).value)"><option :value="1">1分钟</option><option :value="10">10分钟</option><option :value="60">1小时</option></select></label>
      <label class="metric-time-field"><input type="checkbox" :checked="display.fields.includes('arrival')" @change="toggle('arrival',($event.target as HTMLInputElement).checked)" />到达事件</label>
      <label class="metric-time-field"><input type="checkbox" :checked="display.fields.includes('departure')" @change="toggle('departure',($event.target as HTMLInputElement).checked)" />出发事件</label>
    </div>
    <p class="muted">按事件实际发生时间分格，颜色表示该车站、该时间段内正晚点的累计值，提前不抵消。到达和出发同时勾选时，两种事件分别计入；不受晚点阈值及均值零晚点开关影响。沿用统计列车和车站范围，重复经停合并到同一车站行，每站固定32像素。</p>
    <p v-if="!display.fields.length" class="empty-state">请选择到达事件或出发事件。</p>
    <p v-else-if="!scene.count" class="empty-state">{{ scene.missingTime?'此快照缺少可用的事件实际时刻，请点击“重新计算当前已保存数据”后查看时空热力图。':'当前范围没有可按实际时间统计的有效到发事件。' }}</p>
    <template v-else>
      <p class="metric-time-summary">有效事件 {{ scene.count }} 个 · 晚点事件 {{ scene.lateCount }} 个 · 累计晚点 {{ format(scene.total) }}{{ unit }} · {{ scene.stations.length }} 车站 · {{ formatHeatmapTime(scene.start,true) }} – {{ formatHeatmapTime(scene.end,true) }}</p>
      <div ref="viewport" class="metric-time-viewport" :style="{height:Math.min(540,layout.height)+'px'}" @scroll="scroll">
        <div class="metric-time-spacer" :style="{width:layout.width+'px',height:layout.height+'px'}">
          <canvas ref="canvas" tabindex="0" role="img" aria-label="时间与车站的累计晚点热力图，方向键可逐格查看" @pointermove="point" @click="point" @pointerleave="hovered=null;queue()" @keydown="key">按实际时间与车站统计的累计晚点热力图。</canvas>
        </div>
      </div>
      <div class="metric-time-scale"><span>0</span><span class="metric-time-colorbar" :style="{background:gradient}" aria-hidden="true"></span><span>{{ format(scene.max) }}{{ unit }} / 格</span></div>
      <p class="metric-time-detail" aria-live="polite">{{ description || '指向时空格查看累计晚点和事件数。细分时间后可横向滚动，车站较多时可纵向滚动；方向键逐格查看。' }}</p>
      <small v-if="scene.missingTime || scene.excluded">未计入：{{ scene.excluded }} 个无可计算晚点的事件，{{ scene.missingTime }} 个缺少实际时刻的有效事件。</small>
    </template>
  </div>
</template>
