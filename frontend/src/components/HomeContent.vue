<script setup lang="ts">
import { computed, ref } from 'vue'
import { useGeolocation } from '../composables/useGeolocation'
import { useDeviceHeading } from '../composables/useDeviceHeading'
import LocationInfo from './LocationInfo.vue'
import HeadingInfo from './HeadingInfo.vue'
import MapView from './MapView.vue'
import ChatPanel from './ChatPanel.vue'
import type { AskResponse } from '../types/api'

const { state: location } = useGeolocation()
const { getFacing } = useDeviceHeading()
const foundTarget = ref<AskResponse['found_target']>(undefined)

const currentLocation = computed(() => ({
  latitude: location.value.latitude ?? undefined,
  longitude: location.value.longitude ?? undefined,
  accuracy: location.value.accuracy ?? undefined,
  error: location.value.error ?? undefined,
}))
</script>

<template>
  <div class="home-content">
    <div class="info-row">
      <LocationInfo v-bind="currentLocation" class="info-half" />
      <HeadingInfo class="info-half" />
    </div>
    <ChatPanel
      :latitude="currentLocation.latitude"
      :longitude="currentLocation.longitude"
      :facing="getFacing()"
      @update:target="foundTarget = $event"
    />
    <MapView
      :target="foundTarget"
      :latitude="currentLocation.latitude"
      :longitude="currentLocation.longitude"
    />
  </div>
</template>

<style scoped>
.home-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.info-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

@media (max-width: 640px) {
  .info-row {
    grid-template-columns: 1fr;
  }
}
</style>
