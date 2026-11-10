import { afterEach, describe, expect, it, vi } from 'vitest'
import { resolveAudioUrl, synthesizeSpeech } from '../api'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('synthesizeSpeech', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('POST /api/tts にテキストを送り、音声パスを受け取る', async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ text: 'こんにちは', lang: 'ja', audio_path: '/api/audio/answer_1.mp3' }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await synthesizeSpeech({ text: 'こんにちは', lang: 'ja' })

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/tts',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ text: 'こんにちは', lang: 'ja' }),
      }),
    )
    expect(result.audio_path).toBe('/api/audio/answer_1.mp3')
  })

  it('API が失敗した場合はエラーを投げる', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'boom' }, 502)))

    await expect(synthesizeSpeech({ text: 'こんにちは' })).rejects.toThrow('502')
  })
})

describe('resolveAudioUrl', () => {
  it('相対パスを API の絶対 URL に変換する', () => {
    expect(resolveAudioUrl('/api/audio/answer_1.mp3')).toBe(
      'http://localhost:8000/api/audio/answer_1.mp3',
    )
  })

  it('絶対 URL はそのまま返す', () => {
    expect(resolveAudioUrl('https://example.com/answer.mp3')).toBe(
      'https://example.com/answer.mp3',
    )
  })

  it('未指定の場合は undefined を返す', () => {
    expect(resolveAudioUrl(undefined)).toBeUndefined()
  })
})
