import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  synthesizeSpeech: vi.fn(),
}))

vi.mock('../../services/api', () => ({
  analyzeText: vi.fn(),
  askLlmOnly: vi.fn(),
  synthesizeSpeech: mocks.synthesizeSpeech,
  resolveAudioUrl: (path?: string) =>
    path ? `http://localhost:8000${path}` : undefined,
  toErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}))

import DebugView from '../DebugView.vue'

describe('DebugView の gTTS 音声再生テスト', () => {
  beforeEach(() => {
    mocks.synthesizeSpeech.mockReset()
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  })

  it('生成した音声を audio 要素で再生できる状態にする', async () => {
    mocks.synthesizeSpeech.mockResolvedValue({
      text: 'テスト音声',
      lang: 'ja',
      audio_path: '/api/audio/answer_test.mp3',
    })

    const wrapper = mount(DebugView)
    const ttsSection = wrapper.findAll('section')[3]
    await ttsSection.find('textarea').setValue('テスト音声')

    const button = ttsSection
      .findAll('button')
      .find((b) => b.text().includes('音声を生成して再生'))
    expect(button).toBeTruthy()
    await button!.trigger('click')
    await flushPromises()

    expect(mocks.synthesizeSpeech).toHaveBeenCalledWith({
      text: 'テスト音声',
      lang: 'ja',
    })

    const audio = ttsSection.find('audio')
    expect(audio.exists()).toBe(true)
    expect(audio.attributes('src')).toBe(
      'http://localhost:8000/api/audio/answer_test.mp3',
    )
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled()
  })

  it('生成に失敗した場合はエラーメッセージを表示する', async () => {
    mocks.synthesizeSpeech.mockRejectedValue(new Error('音声合成に失敗しました'))

    const wrapper = mount(DebugView)
    const ttsSection = wrapper.findAll('section')[3]
    const button = ttsSection
      .findAll('button')
      .find((b) => b.text().includes('音声を生成して再生'))
    await button!.trigger('click')
    await flushPromises()

    expect(ttsSection.find('.error-box').text()).toContain('音声合成に失敗しました')
    expect(ttsSection.find('audio').exists()).toBe(false)
  })
})
