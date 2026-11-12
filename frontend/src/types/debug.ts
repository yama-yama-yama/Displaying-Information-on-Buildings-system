export type DebugLogSource =
  | 'chat'
  | 'analyze'
  | 'llm'
  | 'tts'
  | 'geolocation'
  | 'system'

export interface ChatLogEvent {
  event: string
  message: string
  elapsedMs?: number
  detail?: unknown
}

export interface DebugLogEntry {
  id: string
  timestamp: string
  source: DebugLogSource
  event: string
  message: string
  elapsedMs?: number
  detail?: unknown
}
