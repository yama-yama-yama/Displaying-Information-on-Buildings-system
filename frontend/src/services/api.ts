import type {
  AnalyzeRequest,
  AnalyzeResponse,
  AskRequest,
  AskResponse,
  LlmOnlyRequest,
  LlmOnlyResponse,
} from '@/types/api'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  })

  if (!response.ok) {
    const errorText = await response.text().catch(() => 'Unknown error')
    throw new Error(`API error ${response.status}: ${errorText}`)
  }

  return response.json() as Promise<T>
}

export async function analyzeText(request: AnalyzeRequest): Promise<AnalyzeResponse> {
  return fetchJson<AnalyzeResponse>(`${API_BASE_URL}/api/analyze`, {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export async function askQuestion(request: AskRequest): Promise<AskResponse> {
  return fetchJson<AskResponse>(`${API_BASE_URL}/api/ask`, {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export async function askLlmOnly(request: LlmOnlyRequest): Promise<LlmOnlyResponse> {
  return fetchJson<LlmOnlyResponse>(`${API_BASE_URL}/api/ask-llm-only`, {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export interface TranscribeResponse {
  text: string
  language: string
}

/**
 * 録音した音声ファイルを文字起こしする（Web Speech API 非対応ブラウザ向けフォールバック）。
 */
export async function transcribeAudio(
  blob: Blob,
  filename = 'voice.webm',
): Promise<TranscribeResponse> {
  const formData = new FormData()
  formData.append('file', blob, filename)

  // Content-Type はブラウザに boundary 付きで設定させるため指定しない
  const response = await fetch(`${API_BASE_URL}/api/transcribe`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    const errorText = await response.text().catch(() => 'Unknown error')
    throw new Error(`API error ${response.status}: ${errorText}`)
  }

  return response.json() as Promise<TranscribeResponse>
}

/**
 * バックエンドが返す相対パス（/api/audio/xxx.mp3）を再生可能な絶対 URL に変換する。
 */
export function resolveAudioUrl(audioPath?: string): string | undefined {
  if (!audioPath) return undefined
  if (/^https?:\/\//i.test(audioPath)) return audioPath
  return `${API_BASE_URL}${audioPath}`
}

/**
 * 例外をユーザー向けの日本語メッセージに変換する。
 * ネットワーク切断やタイムアウトなどの文言をアプリ内で統一するために使う。
 */
export function toErrorMessage(error: unknown, fallback = '通信に失敗しました'): string {
  if (error instanceof Error) {
    if (error.name === 'AbortError') return '通信がキャンセルされました'
    if (error instanceof TypeError) {
      return 'サーバーに接続できませんでした。ネットワーク接続を確認してください'
    }
    return error.message || fallback
  }
  return fallback
}

export async function healthCheck(): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(`${API_BASE_URL}/api/health`)
}
