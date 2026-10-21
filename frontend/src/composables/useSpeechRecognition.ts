import { onUnmounted, ref } from 'vue'

/**
 * Web Speech API (webkitSpeechRecognition / SpeechRecognition) を
 * ブラウザ差異を吸収して扱うための最小限の型定義。
 */
interface SpeechRecognitionAlternativeLike {
  transcript: string
}

interface SpeechRecognitionResultLike {
  readonly length: number
  isFinal: boolean
  [index: number]: SpeechRecognitionAlternativeLike
}

interface SpeechRecognitionResultListLike {
  readonly length: number
  [index: number]: SpeechRecognitionResultLike
}

interface SpeechRecognitionEventLike {
  resultIndex: number
  results: SpeechRecognitionResultListLike
}

interface SpeechRecognitionErrorEventLike {
  error: string
}

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  start(): void
  stop(): void
  abort(): void
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

export function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

const ERROR_MESSAGES: Record<string, string> = {
  'not-allowed': 'マイクの使用が許可されていません',
  'service-not-allowed': '音声認識サービスが利用できません',
  'audio-capture': 'マイクが見つかりません',
  'no-speech': '音声を認識できませんでした。もう一度お試しください',
  network: 'ネットワークエラーにより音声認識に失敗しました',
}

export interface UseSpeechRecognitionOptions {
  lang?: string
  /** 最終的な認識結果が確定したときに呼ばれる。 */
  onFinalResult?: (text: string) => void
}

/**
 * Web Speech API による音声入力 composable。
 *
 * 対応していないブラウザでは `isSupported` が false になるため、
 * 呼び出し側で録音アップロード（`/api/transcribe`）へフォールバックする。
 */
export function useSpeechRecognition(options: UseSpeechRecognitionOptions = {}) {
  const ctor = getSpeechRecognitionCtor()

  const isSupported = ref(ctor !== null)
  const isRecording = ref(false)
  const error = ref<string | null>(null)
  const interimText = ref('')

  let recognition: SpeechRecognitionLike | null = null
  let finalText = ''

  function start() {
    if (!ctor || isRecording.value) return

    error.value = null
    interimText.value = ''
    finalText = ''
    recognition = new ctor()
    recognition.lang = options.lang ?? 'ja-JP'
    recognition.continuous = false
    recognition.interimResults = true

    recognition.onresult = (event) => {
      let interim = ''
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i]
        if (!result) continue
        const transcript = result[0]?.transcript ?? ''
        if (result.isFinal) {
          finalText += transcript
        } else {
          interim += transcript
        }
      }
      interimText.value = interim
    }

    recognition.onerror = (event) => {
      const message = ERROR_MESSAGES[event.error] ?? `音声認識エラー: ${event.error}`
      error.value = message || null
    }

    recognition.onend = () => {
      isRecording.value = false
      interimText.value = ''
      const text = finalText.trim()
      if (text) {
        options.onFinalResult?.(text)
      }
      recognition = null
    }

    isRecording.value = true
    recognition.start()
  }

  function stop() {
    if (recognition) {
      recognition.stop()
    }
    isRecording.value = false
  }

  onUnmounted(() => {
    recognition?.abort()
    recognition = null
  })

  return {
    isSupported,
    isRecording,
    error,
    interimText,
    start,
    stop,
  }
}
