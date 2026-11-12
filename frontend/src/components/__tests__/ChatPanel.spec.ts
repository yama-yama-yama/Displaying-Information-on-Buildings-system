import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  askQuestion: vi.fn(),
  transcribeAudio: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  askQuestion: mocks.askQuestion,
  transcribeAudio: mocks.transcribeAudio,
  resolveAudioUrl: (path?: string) => (path ? `http://localhost:8000${path}` : undefined),
  toErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}))

import ChatPanel from '../ChatPanel.vue'

describe('ChatPanel のデバッグログ', () => {
  beforeEach(() => {
    mocks.askQuestion.mockReset()
    mocks.transcribeAudio.mockReset()
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  })

  it('質問の開始・完了・音声再生を経過時間付きで通知する', async () => {
    mocks.askQuestion.mockResolvedValue({
      question: 'テスト質問',
      answer: 'テスト回答',
      audio_path: '/api/audio/answer_test.mp3',
      analysis: {
        directions: [],
        intent: { intent: 'where', name: '', description: '', matched: '' },
        resolved_entities: [],
        expanded_tags: [],
        feature_keywords: [],
        translated_en: '',
        tokens: [],
      },
      found_target: undefined,
    })

    const wrapper = mount(ChatPanel, {
      props: { latitude: 35.6812, longitude: 139.7671, facing: 'north' },
    })

    await wrapper.find('.question-input').setValue('テスト質問')
    await wrapper.find('.send-button').trigger('click')
    await flushPromises()

    const logs = wrapper.emitted('log')?.map((args) => args[0]) ?? []
    const start = logs.find((entry) => entry.event === 'question_start')
    const success = logs.find((entry) => entry.event === 'question_success')
    const unlock = logs.find((entry) => entry.event === 'audio_unlock')
    const audioPlay = logs.find((entry) => entry.event === 'audio_play')

    expect(unlock).toBeTruthy()
    expect(start).toBeTruthy()
    expect(start.message).toContain('テスト質問')
    expect(start.detail).toMatchObject({
      latitude: 35.6812,
      longitude: 139.7671,
      facing: 'north',
    })
    expect(success).toBeTruthy()
    expect(typeof success.elapsedMs).toBe('number')
    expect(success.elapsedMs).toBeGreaterThanOrEqual(0)
    expect(success.detail.answer).toBe('テスト回答')
    expect(audioPlay).toBeTruthy()
    expect(mocks.askQuestion).toHaveBeenCalledWith({
      question: 'テスト質問',
      latitude: 35.6812,
      longitude: 139.7671,
      facing: 'north',
      generate_audio: true,
    })
  })

  it('質問が失敗した場合はエラーと経過時間を通知する', async () => {
    mocks.askQuestion.mockRejectedValue(new Error('通信エラー'))

    const wrapper = mount(ChatPanel)
    await wrapper.find('.question-input').setValue('失敗する質問')
    await wrapper.find('.send-button').trigger('click')
    await flushPromises()

    const logs = wrapper.emitted('log')?.map((args) => args[0]) ?? []
    const error = logs.find((entry) => entry.event === 'question_error')

    expect(error).toBeTruthy()
    expect(error.message).toBe('通信エラー')
    expect(typeof error.elapsedMs).toBe('number')
  })

  it('マイクボタン押下でも自動再生を許可する', async () => {
    const wrapper = mount(ChatPanel)
    await wrapper.find('.record-button').trigger('click')
    await flushPromises()

    const logs = wrapper.emitted('log')?.map((args) => args[0]) ?? []
    const unlock = logs.find((entry) => entry.event === 'audio_unlock')

    expect(unlock).toBeTruthy()
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled()
  })
})
