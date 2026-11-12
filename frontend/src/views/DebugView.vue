<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import ChatPanel from '../components/ChatPanel.vue'
import { useDeviceHeading } from '../composables/useDeviceHeading'
import { useGeolocation } from '../composables/useGeolocation'
import {
  analyzeText,
  askLlmOnly,
  resolveAudioUrl,
  synthesizeSpeech,
  toErrorMessage,
} from '../services/api'
import type { AnalyzeResponse, AskResponse, LlmOnlyResponse, TtsResponse } from '../types/api'
import type { ChatLogEvent, DebugLogEntry, DebugLogSource } from '../types/debug'

const { state: location, startWatching, stopWatching } = useGeolocation()
const { getFacing } = useDeviceHeading()

// ============================================================================
// デバッグログ
// ============================================================================
const LOG_STORAGE_KEY = 'webprogram-v2-debug-logs'
const MAX_LOG_ENTRIES = 500

const logs = ref<DebugLogEntry[]>([])
let logSequence = 0

function loadLogs() {
  try {
    const raw = localStorage.getItem(LOG_STORAGE_KEY)
    if (!raw) return
    const parsed: unknown = JSON.parse(raw)
    if (Array.isArray(parsed)) logs.value = parsed as DebugLogEntry[]
  } catch {
    // 壊れたデータは無視して空のログから開始する
  }
}

function persistLogs() {
  try {
    localStorage.setItem(LOG_STORAGE_KEY, JSON.stringify(logs.value))
  } catch {
    // ストレージ容量不足などで保存できなくてもデバッグ機能は継続する
  }
}

function addLog(
  source: DebugLogSource,
  event: string,
  message: string,
  extra: { elapsedMs?: number; detail?: unknown } = {},
) {
  const entry: DebugLogEntry = {
    id: `${Date.now()}-${logSequence++}`,
    timestamp: new Date().toISOString(),
    source,
    event,
    message,
    ...(extra.elapsedMs !== undefined ? { elapsedMs: extra.elapsedMs } : {}),
    ...(extra.detail !== undefined ? { detail: extra.detail } : {}),
  }

  logs.value.push(entry)
  if (logs.value.length > MAX_LOG_ENTRIES) {
    logs.value.splice(0, logs.value.length - MAX_LOG_ENTRIES)
  }
  persistLogs()
}

function handleChatLog(event: ChatLogEvent) {
  addLog('chat', event.event, event.message, {
    elapsedMs: event.elapsedMs,
    detail: event.detail,
  })
}

function clearLogs() {
  logs.value = []
  persistLogs()
}

function formatLogTime(timestamp: string): string {
  return new Date(timestamp).toLocaleString('ja-JP', { hour12: false })
}

function downloadLogs() {
  const payload = {
    exportedAt: new Date().toISOString(),
    entries: logs.value,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `debug-logs-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

const lastElapsedMs = computed(() => {
  for (let i = logs.value.length - 1; i >= 0; i -= 1) {
    const entry = logs.value[i]
    if (entry?.elapsedMs !== undefined) return entry.elapsedMs
  }
  return undefined
})

const debugTarget = ref<AskResponse['found_target']>(undefined)

loadLogs()

// Geolocation test
const geoMessage = ref('')
function testGeolocation() {
  if (location.value.latitude !== null && location.value.longitude !== null) {
    geoMessage.value = `緯度: ${location.value.latitude.toFixed(6)}, 経度: ${location.value.longitude.toFixed(6)}, 精度: ${location.value.accuracy?.toFixed(1) ?? '---'} m`
    addLog('geolocation', 'location_read', geoMessage.value, {
      detail: {
        latitude: location.value.latitude,
        longitude: location.value.longitude,
        accuracy: location.value.accuracy,
      },
    })
  } else if (location.value.error) {
    geoMessage.value = `エラー: ${location.value.error}`
    addLog('geolocation', 'location_error', geoMessage.value)
  } else {
    geoMessage.value = '位置情報を取得中...'
    addLog('geolocation', 'location_pending', geoMessage.value)
  }
}

function handleStartWatching() {
  addLog('geolocation', 'watch_start', '位置情報の監視を開始しました')
  startWatching()
}

function handleStopWatching() {
  addLog('geolocation', 'watch_stop', '位置情報の監視を停止しました')
  stopWatching()
}

// Manual analyze test
const analyzeTextInput = ref('右斜め前にあるスタバは何ですか？')
const analyzeLat = ref<number | null>(35.6812)
const analyzeLon = ref<number | null>(139.7671)
const analyzeResult = ref<AnalyzeResponse | null>(null)
const analyzeError = ref('')
const analyzeLoading = ref(false)

async function runAnalyze() {
  const startedAt = performance.now()
  analyzeLoading.value = true
  analyzeError.value = ''
  analyzeResult.value = null
  addLog('analyze', 'request_start', `/api/analyze を実行: ${analyzeTextInput.value}`, {
    detail: { text: analyzeTextInput.value, latitude: analyzeLat.value, longitude: analyzeLon.value },
  })
  try {
    analyzeResult.value = await analyzeText({
      text: analyzeTextInput.value,
      method: 'difflib',
      top_k: 10,
    })
    addLog('analyze', 'request_success', '/api/analyze が完了しました', {
      elapsedMs: Math.round(performance.now() - startedAt),
      detail: analyzeResult.value,
    })
  } catch (e) {
    analyzeError.value = toErrorMessage(e, '解析に失敗しました')
    addLog('analyze', 'request_error', analyzeError.value, {
      elapsedMs: Math.round(performance.now() - startedAt),
      detail: { error: String(e) },
    })
  } finally {
    analyzeLoading.value = false
  }
}

// LLM-only test
const llmQuestion = ref('東京駅の近くにある有名な高層ビルは何ですか？')
const llmContext = ref('ユーザーは東京駅周辺を散策中です。')
const llmResult = ref<LlmOnlyResponse | null>(null)
const llmError = ref('')
const llmLoading = ref(false)

async function runLlmOnly() {
  const startedAt = performance.now()
  llmLoading.value = true
  llmError.value = ''
  llmResult.value = null
  addLog('llm', 'request_start', 'LLM リクエストを送信しました', {
    detail: { question: llmQuestion.value, context: llmContext.value },
  })
  try {
    const prompt = llmContext.value.trim()
      ? `${llmContext.value}\n\n質問: ${llmQuestion.value}`
      : llmQuestion.value
    llmResult.value = await askLlmOnly({ prompt })
    addLog('llm', 'request_success', 'LLM の回答を受信しました', {
      elapsedMs: Math.round(performance.now() - startedAt),
      detail: llmResult.value,
    })
  } catch (e) {
    llmError.value = toErrorMessage(e, 'LLM リクエストに失敗しました')
    addLog('llm', 'request_error', llmError.value, {
      elapsedMs: Math.round(performance.now() - startedAt),
      detail: { error: String(e) },
    })
  } finally {
    llmLoading.value = false
  }
}

// gTTS audio generation / playback test
const ttsText = ref('こんにちは。gTTS の音声再生テストです。')
const ttsLang = ref('ja')
const ttsResult = ref<TtsResponse | null>(null)
const ttsAudioUrl = ref('')
const ttsError = ref('')
const ttsLoading = ref(false)
const ttsAudioRef = ref<HTMLAudioElement | null>(null)

async function runTts() {
  const text = ttsText.value.trim()
  if (!text || ttsLoading.value) return

  const startedAt = performance.now()
  ttsLoading.value = true
  ttsError.value = ''
  ttsResult.value = null
  ttsAudioUrl.value = ''
  addLog('tts', 'request_start', '音声を生成しています', {
    detail: { text, lang: ttsLang.value },
  })
  try {
    const result = await synthesizeSpeech({ text, lang: ttsLang.value })
    ttsResult.value = result
    ttsAudioUrl.value = resolveAudioUrl(result.audio_path) ?? ''
    addLog('tts', 'request_success', '音声の生成が完了しました', {
      elapsedMs: Math.round(performance.now() - startedAt),
      detail: result,
    })
    await nextTick()
    try {
      await ttsAudioRef.value?.play()
      addLog('tts', 'audio_play', '生成した音声を再生しました')
    } catch {
      // 自動再生がブロックされた場合は controls から再生する
      addLog('tts', 'audio_autoplay_blocked', '自動再生がブロックされました')
    }
  } catch (e) {
    ttsError.value = toErrorMessage(e, '音声の生成に失敗しました')
    addLog('tts', 'request_error', ttsError.value, {
      elapsedMs: Math.round(performance.now() - startedAt),
      detail: { error: String(e) },
    })
  } finally {
    ttsLoading.value = false
  }
}
</script>

<template>
  <div class="debug">
    <h1 class="page-title">デバッグモード</h1>

    <section class="debug-section">
      <h2>1. 位置情報取得機能テスト</h2>
      <div class="button-row">
        <button type="button" @click="handleStartWatching">取得開始</button>
        <button type="button" @click="handleStopWatching">取得停止</button>
        <button type="button" @click="testGeolocation">現在値を表示</button>
      </div>
      <p class="result-box">{{ geoMessage || '未実行' }}</p>
      <div class="status-row">
        <span>監視状態: {{ location.isWatching ? 'ON' : 'OFF' }}</span>
        <span>緯度: {{ location.latitude?.toFixed(6) ?? '---' }}</span>
        <span>経度: {{ location.longitude?.toFixed(6) ?? '---' }}</span>
        <span>精度: {{ location.accuracy ? `${Math.round(location.accuracy)} m` : '---' }}</span>
      </div>
    </section>

    <section class="debug-section">
      <h2>2. 緯度経度指定 + /api/analyze 実行テスト</h2>
      <div class="form-row">
        <label>
          緯度
          <input v-model.number="analyzeLat" type="number" step="0.0001" />
        </label>
        <label>
          経度
          <input v-model.number="analyzeLon" type="number" step="0.0001" />
        </label>
      </div>
      <label class="block-label">
        解析テキスト
        <input v-model="analyzeTextInput" type="text" />
      </label>
      <button type="button" :disabled="analyzeLoading" @click="runAnalyze">
        {{ analyzeLoading ? '実行中...' : '/api/analyze を実行' }}
      </button>
      <p v-if="analyzeError" class="error-box">{{ analyzeError }}</p>
      <pre v-if="analyzeResult" class="json-box">{{ JSON.stringify(analyzeResult, null, 2) }}</pre>
    </section>

    <section class="debug-section">
      <h2>3. LLM リクエストのみ実行テスト</h2>
      <label class="block-label">
        質問
        <input v-model="llmQuestion" type="text" />
      </label>
      <label class="block-label">
        追加コンテキスト（表示のみ、未使用）
        <textarea v-model="llmContext" rows="3" />
      </label>
      <button type="button" :disabled="llmLoading" @click="runLlmOnly">
        {{ llmLoading ? '実行中...' : 'LLM リクエストを実行' }}
      </button>
      <p v-if="llmError" class="error-box">{{ llmError }}</p>
      <div v-if="llmResult" class="result-box">
        <strong>回答:</strong>
        <p>{{ llmResult.answer }}</p>
      </div>
    </section>

    <section class="debug-section">
      <h2>4. gTTS 音声生成・再生テスト</h2>
      <label class="block-label">
        読み上げテキスト
        <textarea v-model="ttsText" rows="3" />
      </label>
      <label>
        言語
        <select v-model="ttsLang">
          <option value="ja">日本語 (ja)</option>
          <option value="en">英語 (en)</option>
          <option value="ko">韓国語 (ko)</option>
          <option value="zh-CN">中国語 (zh-CN)</option>
        </select>
      </label>
      <button type="button" :disabled="ttsLoading || !ttsText.trim()" @click="runTts">
        {{ ttsLoading ? '生成中...' : '音声を生成して再生' }}
      </button>
      <p v-if="ttsError" class="error-box">{{ ttsError }}</p>
      <div v-if="ttsResult && ttsAudioUrl" class="result-box audio-result">
        <p>
          <strong>音声 URL:</strong>
          <code>{{ ttsAudioUrl }}</code>
        </p>
        <audio ref="ttsAudioRef" class="tts-audio" :src="ttsAudioUrl" controls></audio>
      </div>
    </section>

    <section class="debug-section">
      <h2>5. ホームの質問機能（デバッグログ付き）</h2>
      <p class="hint">
        ホーム画面と同じ質問・音声入力・回答音声の再生を実行できます。
        処理中のログと経過時間は「6. デバッグログ」に記録されます。
      </p>
      <ChatPanel
        :latitude="location.latitude ?? undefined"
        :longitude="location.longitude ?? undefined"
        :facing="getFacing()"
        @update:target="debugTarget = $event"
        @log="handleChatLog"
      />
      <div v-if="debugTarget" class="result-box">
        <strong>特定した建物:</strong>
        <pre class="json-box">{{ JSON.stringify(debugTarget, null, 2) }}</pre>
      </div>
    </section>

    <section class="debug-section">
      <h2>6. デバッグログ</h2>
      <div class="button-row">
        <button type="button" :disabled="logs.length === 0" @click="downloadLogs">
          JSON をダウンロード
        </button>
        <button
          type="button"
          class="secondary-button"
          :disabled="logs.length === 0"
          @click="clearLogs"
        >
          ログをクリア
        </button>
        <span class="log-summary">
          件数: {{ logs.length }}
          <template v-if="lastElapsedMs !== undefined">
            / 最終処理時間: {{ lastElapsedMs }} ms
          </template>
        </span>
      </div>
      <p class="hint">
        ログはブラウザの localStorage に保存され、再読み込み後も保持されます。
      </p>
      <p v-if="logs.length === 0" class="result-box">まだログはありません。</p>
      <ul v-else class="log-list">
        <li v-for="entry in logs" :key="entry.id" class="log-entry">
          <div class="log-meta">
            <span class="log-time">{{ formatLogTime(entry.timestamp) }}</span>
            <span class="log-source">{{ entry.source }}</span>
            <span class="log-event">{{ entry.event }}</span>
            <span v-if="entry.elapsedMs !== undefined" class="log-elapsed">
              {{ entry.elapsedMs }} ms
            </span>
          </div>
          <p class="log-message">{{ entry.message }}</p>
          <pre v-if="entry.detail !== undefined" class="log-detail">{{
            JSON.stringify(entry.detail, null, 2)
          }}</pre>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.debug {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.page-title {
  font-size: 1.5rem;
  font-weight: 700;
}

.debug-section {
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.debug-section h2 {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--color-heading);
}

.button-row,
.form-row,
.status-row {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  align-items: center;
}

button {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 0.375rem;
  background: hsla(160, 100%, 37%, 1);
  color: white;
  cursor: pointer;
  font-weight: 500;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.875rem;
}

.block-label {
  width: 100%;
}

input,
textarea,
select {
  padding: 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: 0.375rem;
  background: var(--color-background-soft);
  color: var(--color-text);
  font-size: 1rem;
}

input:focus,
textarea:focus,
select:focus {
  outline: none;
  border-color: hsla(160, 100%, 37%, 1);
}

.result-box,
.error-box,
.json-box {
  padding: 0.75rem;
  border-radius: 0.375rem;
  font-size: 0.9375rem;
}

.result-box {
  background: var(--color-background-soft);
}

.error-box {
  background: #ffebee;
  color: #c62828;
}

.json-box {
  background: var(--color-background-mute);
  overflow-x: auto;
  max-height: 400px;
  font-family: monospace;
  font-size: 0.8125rem;
}

.audio-result {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.audio-result code {
  word-break: break-all;
}

.tts-audio {
  width: 100%;
}

.hint {
  font-size: 0.875rem;
  opacity: 0.8;
}

.secondary-button {
  background: var(--color-background-mute);
  color: var(--color-text);
  border: 1px solid var(--color-border);
}

.log-summary {
  font-size: 0.875rem;
  opacity: 0.8;
}

.log-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-height: 480px;
  overflow-y: auto;
}

.log-entry {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: 0.5rem;
  background: var(--color-background-soft);
}

.log-meta {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  align-items: center;
  font-family: monospace;
  font-size: 0.75rem;
}

.log-time {
  opacity: 0.7;
}

.log-source {
  padding: 0 0.375rem;
  border-radius: 999px;
  background: hsla(210, 100%, 50%, 0.15);
  color: hsla(210, 100%, 40%, 1);
}

.log-event {
  font-weight: 600;
}

.log-elapsed {
  margin-left: auto;
  color: hsla(160, 100%, 30%, 1);
}

.log-message {
  margin-top: 0.25rem;
  font-size: 0.875rem;
  white-space: pre-wrap;
}

.log-detail {
  margin-top: 0.375rem;
  padding: 0.5rem;
  background: var(--color-background-mute);
  border-radius: 0.375rem;
  font-family: monospace;
  font-size: 0.75rem;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
