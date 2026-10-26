<script setup lang="ts">
import { computed } from 'vue'
import type { PlotEvent, PlotSeries, PlotStation } from '../api/diagram'
import { comparisonRows } from '../diagramDetails'
import { localTime, timeLabel } from '../diagramGeometry'

const props = defineProps<{ series: PlotSeries[]; stations: PlotStation[]; dateBase: string }>()
const rows = computed(() => comparisonRows(props.series, props.stations))

function usageLabel(event: PlotEvent) {
  const value = event.track_usage
  if (!value) return '未展开'
  if (value.passing) return value.adopted_track == null ? '通过 · 股道未判定（红色三角形）'
    : value.adopted_track + ' · 通过 ' + timeLabel(value.start_seconds!, true)
  if (value.direction === 'unknown') return '方向未定'
  if (value.adopted_track == null) return '无法定位股道'
  const track = value.adopted_track + (value.defaulted ? '（绘图默认）' : '')
  if (value.start_seconds != null && value.end_seconds != null) return value.can_occupy
    ? track + ' · ' + timeLabel(value.start_seconds, true) + ' ～ ' + timeLabel(value.end_seconds, true)
    : track + ' · 占用区间倒置'
  return track + ' · 仅部分进路'
}
</script>

<template>
  <div class="table-wrap diagram-comparison">
    <table aria-label="所选列车时刻对比">
      <thead>
        <tr>
          <th rowspan="2" class="comparison-station" scope="col">车站</th>
          <th v-for="train in series" :key="train.key" colspan="6" scope="colgroup">
            {{ train.train_course_id }} · {{ train.object_type === 'base' ? '基本图' : train.object_name }} · {{ train.train_base_date }}
          </th>
        </tr>
        <tr>
          <template v-for="train in series" :key="train.key">
            <th scope="col">SEQ</th><th scope="col">到达</th><th scope="col">出发</th>
            <th scope="col">股道</th><th scope="col">绘图占用</th><th scope="col">来源</th>
          </template>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.key">
          <th scope="row" class="comparison-station">{{ row.name }}{{ row.repeated ? '（第' + row.visit + '次）' : '' }}</th>
          <template v-for="(event, index) in row.events" :key="series[index].key">
            <template v-if="event">
              <td>{{ event.visit_seq }}</td>
              <td>{{ event.arrival ? localTime(dateBase, event.arrival.seconds).replace('T', ' ') : '空' }}</td>
              <td>{{ event.departure ? localTime(dateBase, event.departure.seconds).replace('T', ' ') : '空' }}</td>
              <td>{{ event.track_code ?? '未记录' }}</td>
              <td>{{ usageLabel(event) }}</td>
              <td>{{ event.source.sheet }} · 源行 {{ event.source.row }}</td>
            </template>
            <td v-else colspan="6" class="muted">{{ row.repeated ? '无对应访问' : '未经过本站' }}</td>
          </template>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.diagram-comparison { max-height: 60vh; margin-top: 12px; }
.diagram-comparison table { width: max-content; min-width: 100%; border-collapse: separate; border-spacing: 0; }
.diagram-comparison th, .diagram-comparison td { white-space: nowrap; }
.diagram-comparison thead { position: sticky; top: 0; z-index: 2; background: var(--surface); }
.comparison-station { position: sticky; left: 0; z-index: 1; background: var(--surface); }
.diagram-comparison thead .comparison-station { z-index: 3; }
</style>
