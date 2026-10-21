<script setup lang="ts">
import { ref } from 'vue'
import { useGeolocation } from '../composables/useGeolocation'
import { analyzeText, askLlmOnly, toErrorMessage } from '../services/api'
import type { AnalyzeResponse, LlmOnlyResponse } from '../types/api'

const { state: location, startWatching, stopWatching } = useGeolocation()

// Geolocation test
const geoMessage = ref('')
function testGeolocation() {
  if (location.value.latitude !== null && location.value.longitude !== null) {
    geoMessage.value = `緯度: ${location.value.latitude.toFixed(6)}, 経度: ${location.value.longitude.toFixed(6)}, 精度: ${location.value.accuracy?.toFixed(1) ?? '---'} m`
  } else if (location.value.error) {
    geoMessage.value = `エラー: ${location.value.error}`
  } else {
    geoMessage.value = '位置情報を取得中...'
  }
}

// Manual analyze test
const analyzeTextInput = ref('右斜め前にあるスタバは何ですか？')
const analyzeLat = ref<number | null>(35.6812)
const analyzeLon = ref<number | null>(139.7671)
const analyzeResult = ref<AnalyzeResponse | null>(null)
const analyzeError = ref('')
const analyzeLoading = ref(false)

async function runAnalyze() {
  analyzeLoading.value = true
  analyzeError.value = ''
  analyzeResult.value = null
  try {
    analyzeResult.value = await analyzeText({
      text: analyzeTextInput.value,
      method: 'difflib',
      top_k: 10,
    })
  } catch (e) {
    analyzeError.value = toErrorMessage(e, '解析に失敗しました')
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
  llmLoading.value = true
  llmError.value = ''
  llmResult.value = null
  try {
    const prompt = llmContext.value.trim()
      ? `${llmContext.value}\n\n質問: ${llmQuestion.value}`
      : llmQuestion.value
    llmResult.value = await askLlmOnly({ prompt })
  } catch (e) {
    llmError.value = toErrorMessage(e, 'LLM リクエストに失敗しました')
  } finally {
    llmLoading.value = false
  }
}
</script>

<template>
  <div class="debug">
    <h1 class="page-title">デバッグモード</h1>

    <section class="debug-section">
      <h2>1. 位置情報取得機能テスト</h2>
      <div class="button-row">
        <button type="button" @click="startWatching">取得開始</button>
        <button type="button" @click="stopWatching">取得停止</button>
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
textarea {
  padding: 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: 0.375rem;
  background: var(--color-background-soft);
  color: var(--color-text);
  font-size: 1rem;
}

input:focus,
textarea:focus {
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
</style>
