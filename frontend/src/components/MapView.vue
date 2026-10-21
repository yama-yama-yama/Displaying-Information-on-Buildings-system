<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { FoundTarget } from '@/types/api'

const props = defineProps<{
  target?: FoundTarget
  latitude?: number
  longitude?: number
}>()

const DEFAULT_CENTER: L.LatLngExpression = [35.6812, 139.7671]
const DEFAULT_ZOOM = 15

const mapElement = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let currentMarker: L.CircleMarker | null = null
let targetMarker: L.CircleMarker | null = null
let routeLine: L.Polyline | null = null

function currentPosition(): L.LatLngExpression | null {
  if (props.latitude === undefined || props.longitude === undefined) return null
  return [props.latitude, props.longitude]
}

function targetPosition(): L.LatLngExpression | null {
  if (!props.target) return null
  return [props.target.latitude, props.target.longitude]
}

/**
 * 現在地・目的地のマーカーと 2 点を結ぶ補助線を更新する。
 */
function updateLayers() {
  if (!map) return

  const current = currentPosition()
  const target = targetPosition()

  if (current) {
    if (currentMarker) {
      currentMarker.setLatLng(current)
    } else {
      currentMarker = L.circleMarker(current, {
        radius: 8,
        color: '#1565c0',
        fillColor: '#2196f3',
        fillOpacity: 0.9,
        weight: 2,
      })
        .addTo(map)
        .bindPopup('現在地')
    }
  }

  if (target && props.target) {
    const distance = props.target.distance_meters
    const popup = `${props.target.name}${
      distance !== undefined ? `（約 ${Math.round(distance)} m）` : ''
    }`

    if (targetMarker) {
      targetMarker.setLatLng(target)
      targetMarker.setPopupContent(popup)
    } else {
      targetMarker = L.circleMarker(target, {
        radius: 10,
        color: '#c62828',
        fillColor: '#ef5350',
        fillOpacity: 0.9,
        weight: 2,
      })
        .addTo(map)
        .bindPopup(popup)
    }

    if (current) {
      if (routeLine) {
        routeLine.setLatLngs([current, target])
      } else {
        routeLine = L.polyline([current, target], {
          color: '#ef5350',
          dashArray: '6 6',
          weight: 3,
        }).addTo(map)
      }
      map.fitBounds(L.latLngBounds([current, target]), {
        padding: [30, 30],
        maxZoom: 17,
      })
    } else {
      map.setView(target, 16)
    }
  } else if (current) {
    map.setView(current, 16)
    if (routeLine) {
      routeLine.remove()
      routeLine = null
    }
  }
}

onMounted(() => {
  if (!mapElement.value) return

  map = L.map(mapElement.value, { zoomControl: true })
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map)

  map.setView(currentPosition() ?? DEFAULT_CENTER, DEFAULT_ZOOM)
  updateLayers()
})

watch(
  () => [props.latitude, props.longitude, props.target],
  () => updateLayers(),
  { deep: true },
)

onUnmounted(() => {
  map?.remove()
  map = null
  currentMarker = null
  targetMarker = null
  routeLine = null
})
</script>

<template>
  <section class="map-view">
    <h2 class="section-title">周辺マップ</h2>
    <div ref="mapElement" class="map-canvas"></div>
    <p v-if="props.target" class="map-target">
      {{ props.target.name }}
      <span v-if="props.target.distance_meters !== undefined" class="map-distance">
        （約 {{ Math.round(props.target.distance_meters) }} m、{{
          props.target.vector_name ?? ''
        }}）
      </span>
    </p>
  </section>
</template>

<style scoped>
.map-view {
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  padding: 1rem;
}

.section-title {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
  color: var(--color-heading);
}

.map-canvas {
  width: 100%;
  height: 320px;
  min-height: 240px;
  border-radius: 0.5rem;
  /* Leaflet の内部要素がヘッダー等に重ならないようにする */
  z-index: 0;
}

.map-target {
  margin-top: 0.75rem;
  font-size: 1.125rem;
  font-weight: 600;
}

.map-distance {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.875rem;
  font-weight: 400;
  opacity: 0.8;
}
</style>
