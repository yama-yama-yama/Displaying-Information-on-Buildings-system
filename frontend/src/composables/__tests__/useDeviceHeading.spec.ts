import { describe, expect, it } from 'vitest'
import { getDirectionByIndex } from '../useDeviceHeading'

describe('getDirectionByIndex', () => {
  it('8方位を北から時計回りに返す', () => {
    const labels = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => getDirectionByIndex(i).label)
    expect(labels).toEqual(['北', '北東', '東', '南東', '南', '南西', '西', '北西'])
  })

  it('範囲外のインデックスをラップする', () => {
    expect(getDirectionByIndex(8).label).toBe('北')
    expect(getDirectionByIndex(9).label).toBe('北東')
    expect(getDirectionByIndex(-1).label).toBe('北西')
    expect(getDirectionByIndex(-8).label).toBe('北')
  })

  it('value はバックエンド送信用の英字キーになる', () => {
    expect(getDirectionByIndex(0).value).toBe('north')
    expect(getDirectionByIndex(4).value).toBe('south')
    expect(getDirectionByIndex(7).value).toBe('northwest')
  })
})
