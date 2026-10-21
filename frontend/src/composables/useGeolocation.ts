import { onMounted, onUnmounted, ref } from 'vue'

export interface GeolocationState {
  latitude: number | null
  longitude: number | null
  accuracy: number | null
  error: string | null
  isWatching: boolean
}

export function useGeolocation(enableHighAccuracy = true) {
  const state = ref<GeolocationState>({
    latitude: null,
    longitude: null,
    accuracy: null,
    error: null,
    isWatching: false,
  })

  let watchId: number | null = null

  function updatePosition(position: GeolocationPosition) {
    state.value.latitude = position.coords.latitude
    state.value.longitude = position.coords.longitude
    state.value.accuracy = position.coords.accuracy
    state.value.error = null
  }

  function handleError(error: GeolocationPositionError) {
    state.value.error = error.message
  }

  function startWatching() {
    if (!('geolocation' in navigator)) {
      state.value.error = 'Geolocation API が利用できません'
      return
    }

    state.value.isWatching = true
    watchId = navigator.geolocation.watchPosition(updatePosition, handleError, {
      enableHighAccuracy,
      maximumAge: 10000,
      timeout: 10000,
    })
  }

  function stopWatching() {
    if (watchId !== null) {
      navigator.geolocation.clearWatch(watchId)
      watchId = null
    }
    state.value.isWatching = false
  }

  onMounted(() => {
    startWatching()
  })

  onUnmounted(() => {
    stopWatching()
  })

  return {
    state,
    startWatching,
    stopWatching,
  }
}
