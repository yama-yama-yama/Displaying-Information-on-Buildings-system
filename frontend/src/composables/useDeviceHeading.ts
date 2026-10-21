import { onMounted, onUnmounted, ref } from 'vue'

export interface DeviceHeadingState {
  heading: number | null
  manualFacing: string
  error: string | null
  isSupported: boolean
  isManual: boolean
}

const CARDINAL_DIRECTIONS = [
  { value: 'north', label: '北' },
  { value: 'northeast', label: '北東' },
  { value: 'east', label: '東' },
  { value: 'southeast', label: '南東' },
  { value: 'south', label: '南' },
  { value: 'southwest', label: '南西' },
  { value: 'west', label: '西' },
  { value: 'northwest', label: '北西' },
]

function isIOS(): boolean {
  return /iPad|iPhone|iPod/.test(navigator.userAgent)
}

function isAndroid(): boolean {
  return /Android/.test(navigator.userAgent)
}

export function getDirectionByIndex(index: number) {
  const safeIndex = ((index % 8) + 8) % 8
  return (CARDINAL_DIRECTIONS[safeIndex] ?? CARDINAL_DIRECTIONS[0])!
}

export function useDeviceHeading() {
  const state = ref<DeviceHeadingState>({
    heading: null,
    manualFacing: 'north',
    error: null,
    isSupported: false,
    isManual: false,
  })

  function handleOrientation(event: DeviceOrientationEvent) {
    let heading: number | null = null

    // iOS: webkitCompassHeading
    if ('webkitCompassHeading' in event && typeof event.webkitCompassHeading === 'number') {
      heading = event.webkitCompassHeading
    }
    // Android: deviceorientationabsolute (alpha with compass)
    else if ((event as DeviceOrientationEvent & { absolute: boolean }).absolute && event.alpha !== null) {
      heading = 360 - event.alpha
    }
    // fallback: alpha
    else if (event.alpha !== null) {
      heading = 360 - event.alpha
    }

    if (heading !== null) {
      state.value.heading = (heading + 360) % 360
      state.value.error = null
    }
  }

  async function requestPermission(): Promise<boolean> {
    if (!isIOS()) return true

    const DeviceOrientationEventWithPermission = DeviceOrientationEvent as unknown as {
      requestPermission?: () => Promise<'granted' | 'denied'>
    }

    if (typeof DeviceOrientationEventWithPermission.requestPermission === 'function') {
      try {
        const response = await DeviceOrientationEventWithPermission.requestPermission()
        if (response === 'granted') {
          return true
        }
        state.value.error = '向きセンサーの許可が拒否されました'
        return false
      } catch (e) {
        state.value.error = '向きセンサーの許可取得に失敗しました'
        return false
      }
    }
    return true
  }

  async function startTracking() {
    const granted = await requestPermission()
    if (!granted) {
      state.value.isManual = true
      return
    }

    if (window.DeviceOrientationEvent) {
      // Android では deviceorientationabsolute が推奨
      const eventName = isAndroid() ? 'deviceorientationabsolute' : 'deviceorientation'
      window.addEventListener(eventName as 'deviceorientation', handleOrientation, true)
      state.value.isSupported = true
      state.value.isManual = false
    } else {
      state.value.error = 'デバイス向きセンサーが利用できません'
      state.value.isManual = true
    }
  }

  function stopTracking() {
    const eventName = isAndroid() ? 'deviceorientationabsolute' : 'deviceorientation'
    window.removeEventListener(eventName as 'deviceorientation', handleOrientation, true)
  }

  function setManualFacing(value: string) {
    state.value.manualFacing = value
  }

  /**
   * バックエンドに送信する方角文字列を返す。
   * センサー値がある場合は方位名に変換、手動の場合は手動選択値。
   */
  function getFacing(): string {
    if (!state.value.isManual && state.value.heading !== null) {
      return getDirectionByIndex(Math.round(state.value.heading / 45)).value
    }
    return state.value.manualFacing
  }

  onMounted(() => {
    startTracking()
  })

  onUnmounted(() => {
    stopTracking()
  })

  return {
    state,
    CARDINAL_DIRECTIONS,
    startTracking,
    stopTracking,
    setManualFacing,
    getFacing,
  }
}
