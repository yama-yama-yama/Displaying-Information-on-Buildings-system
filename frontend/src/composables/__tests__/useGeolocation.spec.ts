import { mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useGeolocation, type GeolocationState } from '../useGeolocation'

function mountComposable() {
  let state!: ReturnType<typeof useGeolocation>['state']
  let api!: ReturnType<typeof useGeolocation>
  const Comp = defineComponent({
    setup() {
      api = useGeolocation()
      state = api.state
      return () => null
    },
  })
  return { wrapper: mount(Comp), state, api }
}

describe('useGeolocation', () => {
  const clearWatch = vi.fn()

  beforeEach(() => {
    clearWatch.mockReset()
  })

  afterEach(() => {
    // @ts-expect-error テスト用に差し替えたプロパティを後始末する
    delete navigator.geolocation
  })

  it('マウント時に位置情報の監視を開始し、座標を state に反映する', async () => {
    const watchPosition = vi.fn((success: PositionCallback) => {
      success({
        coords: { latitude: 35.6812, longitude: 139.7671, accuracy: 12 },
      } as GeolocationPosition)
      return 42
    })
    Object.defineProperty(navigator, 'geolocation', {
      value: { watchPosition, clearWatch },
      configurable: true,
    })

    const { wrapper, state } = mountComposable()
    await nextTick()

    expect(watchPosition).toHaveBeenCalledOnce()
    const stateValue: GeolocationState = state.value
    expect(stateValue.latitude).toBe(35.6812)
    expect(stateValue.longitude).toBe(139.7671)
    expect(stateValue.accuracy).toBe(12)
    expect(stateValue.error).toBeNull()
    expect(stateValue.isWatching).toBe(true)

    wrapper.unmount()
    expect(clearWatch).toHaveBeenCalledWith(42)
  })

  it('位置情報取得エラーを state.error に格納する', async () => {
    const watchPosition = vi.fn((_success: PositionCallback, error: PositionErrorCallback) => {
      error({ message: '位置情報が許可されていません' } as GeolocationPositionError)
      return 1
    })
    Object.defineProperty(navigator, 'geolocation', {
      value: { watchPosition, clearWatch },
      configurable: true,
    })

    const { wrapper, state } = mountComposable()
    await nextTick()

    expect(state.value.error).toBe('位置情報が許可されていません')
    wrapper.unmount()
  })
})
