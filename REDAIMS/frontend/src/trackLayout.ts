import type { PlotData, PlotPoint, PlotStation, TrackResource } from './api/diagram'
import { project, zoomViewport, type Bounds, type Viewport } from './diagramGeometry'
export interface TrackBand { station: PlotStation; resource: TrackResource; baseY: number; center: number; half: number }
export function visibleTrackStations(data: PlotData, ids: string[], view: Viewport) {
  const resources = new Map(data.track_stations.map(resource => [resource.node_id, resource]))
  return data.axis.stations.filter(station => ids.includes(station.node_id) && data.expanded_stations.includes(station.node_id) &&
    station.y >= view.y0 && station.y <= view.y1 && resources.get(station.node_id)?.can_expand)
    .map(station => ({ station, resource: resources.get(station.node_id)! }))
}
export function trackExtraHeight(stations: { resource: TrackResource }[], gap: number) {
  return stations.reduce((sum, item) => sum + (item.resource.track_count + 1) * gap + 16, 0)
}
export function createTrackLayout(view: Viewport, box: Bounds, reverse: boolean,
  stations: { station: PlotStation; resource: TrackResource }[], gap: number) {
  const baseBox = { ...box, height: Math.max(40, box.height - trackExtraHeight(stations, gap)) }
  const bands: TrackBand[] = stations.map(item => ({ ...item, baseY: project({ seconds: view.x0, y: item.station.y }, view, baseBox, reverse).y,
    center: 0, half: (item.resource.track_count + 1) * gap / 2 + 8 })).sort((a, b) => a.baseY - b.baseY)
  let added = 0
  for (const band of bands) { band.center = band.baseY + added + band.half; added += band.half * 2 }
  return { view, box, baseBox, reverse, bands, gap }
}
export function wheelViewport(layout: TrackLayout, pixel: { x: number; y: number },
  event: Pick<WheelEvent, 'deltaY' | 'ctrlKey' | 'shiftKey'>) {
  if (event.deltaY === 0) return layout.view
  const view = layout.view
  const ax = Math.max(0, Math.min(1, (pixel.x - layout.box.left) / layout.box.width))
  const ay = Math.max(0, Math.min(1, (stationAtPixel(pixel.y, layout) - view.y0) / (view.y1 - view.y0)))
  return zoomViewport(view, event.deltaY > 0 ? 1.15 : 1 / 1.15, ax, ay,
    event.ctrlKey ? 'time' : event.shiftKey ? 'station' : 'both')
}
export type TrackLayout = ReturnType<typeof createTrackLayout>
export function projectOnTracks(point: Pick<PlotPoint, 'seconds' | 'y' | 'track_offset'>, layout: TrackLayout) {
  const pixel = project(point, layout.view, layout.baseBox, layout.reverse)
  let added = 0
  for (const band of layout.bands) {
    if (Math.abs(pixel.y - band.baseY) < 1e-7) {
      return { x: pixel.x, y: band.center + (point.track_offset || 0) * layout.gap }
    }
    if (pixel.y > band.baseY) added += 2 * band.half
  }
  return { x: pixel.x, y: pixel.y + added }
}
// Collapse inserted pixel bands before deriving a zoom anchor in equivalent station units.
export function stationAtPixel(pixelY: number, layout: TrackLayout) {
  let added = 0, baseY = pixelY
  for (const band of layout.bands) {
    const start = band.center - band.half, end = band.center + band.half
    if (pixelY < start) break
    if (pixelY <= end) return band.station.y
    added += band.half * 2
  }
  baseY -= added
  const ratio = (baseY - layout.baseBox.top) / layout.baseBox.height
  return layout.view.y0 + (layout.reverse ? 1 - ratio : ratio) * (layout.view.y1 - layout.view.y0)
}
