import type { DelaySnapshot, MetricCamera } from './api/analysis'

export type DelayField = 'arrival' | 'departure'
export function delayTrainColor(id: string, dark = false) {
  let hash = 0
  for (const c of id) hash = (hash * 31 + c.charCodeAt(0)) >>> 0
  hash = Math.imul(hash ^ (hash >>> 16), 0x45d9f3b) >>> 0
  hash = Math.imul(hash ^ (hash >>> 16), 0x45d9f3b) >>> 0
  hash = (hash ^ (hash >>> 16)) >>> 0
  return 'hsl(' + (hash % 360) + ', 68%, ' + (dark ? 66 : 43) + '%)'
}
export interface DelayPoint3D { x: number; y: number; z: number; seconds: number; rowKey: string; trainId: string; field: DelayField }
export interface DelayTrace3D { trainId: string; lane: number; field: DelayField; pieces: DelayPoint3D[][] }
export function buildDelay3D(data: DelaySnapshot, trainIds: string[], fields: DelayField[], stationIds?: string[] | null) {
  const wanted = new Set(trainIds), groups = new Map<string, DelaySnapshot['cells']>(), rowKeys = new Set<string>()
  for (const cell of data.cells) {
    if (!wanted.has(cell.train_id)) continue
    if (!groups.has(cell.train_id)) groups.set(cell.train_id, [])
    groups.get(cell.train_id)!.push(cell); rowKeys.add(cell.row_key)
  }
  const selectedStations = stationIds == null ? null : new Set(stationIds)
  const stations = data.rows.filter(r => rowKeys.has(r.key) && (!selectedStations || selectedStations.has(r.station_id))), xIndex = new Map(stations.map((r,i)=>[r.key,i]))
  const byTrain = new Map(data.trains.map(t=>[t.id,t]))
  const trains = [...new Set(trainIds)].map(id => byTrain.get(id)).filter((t): t is DelaySnapshot['trains'][number] => !!t)
  const traces: DelayTrace3D[] = []
  let min = 0, max = 0, pointCount = 0
  trains.forEach((train,lane) => {
    const events = [...(groups.get(train.id)||[])].sort((a,b)=>a.visit_seq-b.visit_seq)
    for (const field of new Set(fields)) {
      const pieces: DelayPoint3D[][] = []
      let piece: DelayPoint3D[] = []
      for (const cell of events) {
        const value = cell[field], x = xIndex.get(cell.row_key)
        if (typeof value !== 'number' || !Number.isFinite(value)) {
          if (piece.length) pieces.push(piece)
          piece = []; continue
        }
        // Hidden valid visits are skipped; missing times still break the path.
        if (x === undefined) continue
        piece.push({ x, y: lane, z: value, seconds: value, rowKey: cell.row_key, trainId: train.id, field })
        min = Math.min(min,value); max = Math.max(max,value); pointCount++
      }
      if (piece.length) pieces.push(piece)
      traces.push({ trainId: train.id, lane, field, pieces })
    }
  })
  const padding = Math.max(30,(max-min)*.08)
  return { stations, trains, traces, zMin: min-padding, zMax: max+padding, pointCount }
}
export type DelayScene3D = ReturnType<typeof buildDelay3D>
export function normalizeDelayPoint(scene: DelayScene3D, point: {x:number;y:number;z:number}) {
  return {
    x: scene.stations.length > 1 ? point.x/(scene.stations.length-1)*2-1 : 0,
    y: scene.trains.length > 1 ? point.y/(scene.trains.length-1)*1.7-.85 : 0,
    z: (point.z-scene.zMin)/(scene.zMax-scene.zMin)*1.5-.75,
  }
}
export function projectDelayPoint(point: {x:number;y:number;z:number}, camera: MetricCamera, width: number, height: number) {
  const az = camera.azimuth*Math.PI/180, el = camera.elevation*Math.PI/180
  const horizontal = Math.cos(az)*point.x-Math.sin(az)*point.y
  const along = Math.sin(az)*point.x+Math.cos(az)*point.y
  const vertical = point.z*Math.cos(el)-along*Math.sin(el)
  const depth = point.z*Math.sin(el)+along*Math.cos(el)
  const scale = Math.min(Math.max(20,width-110),Math.max(20,height-110))/3.4*camera.zoom*4/(4-depth)
  return { x:width/2+horizontal*scale, y:height*.49-vertical*scale, depth }
}
export function rotateDelayCamera(camera: MetricCamera, dx:number, dy:number): MetricCamera {
  const azimuth = ((camera.azimuth+dx*.45+180)%360+360)%360-180
  return { ...camera, azimuth, elevation:Math.max(10,Math.min(80,camera.elevation+dy*.3)) }
}
export function zoomDelayCamera(camera: MetricCamera, delta:number): MetricCamera {
  return { ...camera, zoom:Math.max(.6,Math.min(2.5,camera.zoom*Math.exp(-Math.max(-300,Math.min(300,delta))*.0015))) }
}
