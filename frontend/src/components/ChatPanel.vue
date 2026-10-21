<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import {
  askQuestion,
  resolveAudioUrl,
  toErrorMessage,
  transcribeAudio,
} from "@/services/api";
import { useSpeechRecognition } from "@/composables/useSpeechRecognition";
import type { AskResponse } from "@/types/api";

const props = defineProps<{
  latitude?: number;
  longitude?: number;
  facing?: string;
}>();

const emit = defineEmits<{
  (e: "update:target", target: AskResponse["found_target"]): void;
}>();

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

const question = ref("");
const history = ref<ChatMessage[]>([]);
const isLoading = ref(false);
const errorMessage = ref("");
const audioUrl = ref<string | null>(null);
const audioRef = ref<HTMLAudioElement | null>(null);
const responseArea = ref<HTMLDivElement | null>(null);

async function scrollToBottom() {
  await nextTick();
  const area = responseArea.value;
  if (area) area.scrollTop = area.scrollHeight;
}

// サーバー側で生成した mp3 を自動再生する（ブロックされた場合は controls から再生可能）
async function playAnswerAudio() {
  await nextTick();
  try {
    await audioRef.value?.play();
  } catch {
    // 自動再生がブロックされた場合はユーザー操作に任せる
  }
}

async function submitQuestion() {
  const text = question.value.trim();
  if (!text || isLoading.value) return;

  isLoading.value = true;
  errorMessage.value = "";
  audioUrl.value = null;
  history.value.push({ role: "user", text });
  question.value = "";
  await scrollToBottom();

  try {
    const response = await askQuestion({
      question: text,
      latitude: props.latitude,
      longitude: props.longitude,
      facing: props.facing,
      generate_audio: true,
    });

    history.value.push({ role: "assistant", text: response.answer });
    audioUrl.value = resolveAudioUrl(response.audio_path) ?? null;
    emit("update:target", response.found_target);
    await scrollToBottom();
    await playAnswerAudio();
  } catch (error) {
    errorMessage.value = toErrorMessage(error, "回答の取得に失敗しました");
    await scrollToBottom();
  } finally {
    isLoading.value = false;
  }
}

function clearHistory() {
  history.value = [];
  errorMessage.value = "";
  audioUrl.value = null;
}

// ============================================================================
// 音声入力（方式A: Web Speech API）
// ============================================================================
const speech = useSpeechRecognition({
  lang: "ja-JP",
  onFinalResult: (text) => {
    question.value = text;
    void submitQuestion();
  },
});

watch(speech.error, (value) => {
  if (value) errorMessage.value = value;
});

// ============================================================================
// 音声入力フォールバック（方式B: MediaRecorder → POST /api/transcribe）
// ============================================================================
const mediaRecorder = ref<MediaRecorder | null>(null);
const isFallbackRecording = ref(false);
const isTranscribing = ref(false);
let recordedChunks: Blob[] = [];

const isRecording = computed(
  () => speech.isRecording.value || isFallbackRecording.value,
);
const isBusy = computed(() => isLoading.value || isTranscribing.value);
const voiceUnsupported = computed(() => !speech.isSupported.value);

function canUseMediaRecorder(): boolean {
  return (
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    typeof MediaRecorder !== "undefined"
  );
}

async function startFallbackRecording() {
  if (!canUseMediaRecorder()) {
    errorMessage.value =
      "このブラウザは音声入力に対応していません。テキストで入力してください。";
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    const recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) recordedChunks.push(event.data);
    };
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      void handleRecordedAudio();
    };
    recorder.start();
    mediaRecorder.value = recorder;
    isFallbackRecording.value = true;
  } catch {
    errorMessage.value = "マイクの使用が許可されませんでした";
  }
}

async function handleRecordedAudio() {
  if (recordedChunks.length === 0) {
    errorMessage.value = "音声が録音されませんでした";
    return;
  }

  isTranscribing.value = true;
  errorMessage.value = "";
  try {
    const blob = new Blob(recordedChunks, {
      type: recordedChunks[0]?.type || "audio/webm",
    });
    const result = await transcribeAudio(blob);
    question.value = result.text;
    await submitQuestion();
  } catch (error) {
    errorMessage.value = toErrorMessage(error, "文字起こしに失敗しました");
  } finally {
    isTranscribing.value = false;
    recordedChunks = [];
    mediaRecorder.value = null;
  }
}

function stopRecording() {
  if (speech.isRecording.value) {
    speech.stop();
    return;
  }
  if (mediaRecorder.value && mediaRecorder.value.state !== "inactive") {
    mediaRecorder.value.stop();
  }
  isFallbackRecording.value = false;
}

function toggleRecording() {
  if (isBusy.value) return;
  if (isRecording.value) {
    stopRecording();
  } else if (speech.isSupported.value) {
    speech.start();
  } else {
    void startFallbackRecording();
  }
}

onUnmounted(() => {
  mediaRecorder.value?.stream.getTracks().forEach((track) => track.stop());
});
</script>

<template>
  <section class="chat-panel">
    <div class="panel-header">
      <h2 class="section-title">質問・案内</h2>
      <button
        v-if="history.length > 0"
        type="button"
        class="clear-button"
        :disabled="isBusy"
        @click="clearHistory"
      >
        履歴をクリア
      </button>
    </div>

    <div ref="responseArea" class="response-area">
      <p v-if="history.length === 0 && !isLoading" class="response-placeholder">
        ここに回答が表示されます。
      </p>

      <div
        v-for="(message, index) in history"
        :key="index"
        class="message"
        :class="message.role"
      >
        <span class="message-role">
          {{ message.role === "user" ? "あなた" : "アシスタント" }}
        </span>
        <p class="message-text">{{ message.text }}</p>
      </div>

      <audio
        v-if="audioUrl"
        ref="audioRef"
        class="answer-audio"
        :src="audioUrl"
        controls
        autoplay
      ></audio>

      <p v-if="isLoading" class="response-loading">回答を生成中...</p>
      <p v-if="isTranscribing" class="response-loading">音声を文字起こし中...</p>
      <p v-if="errorMessage" class="response-error">{{ errorMessage }}</p>
    </div>

    <div class="input-area">
      <input
        v-model="question"
        type="text"
        class="question-input"
        placeholder="例: あの建物は何ですか？"
        :disabled="isBusy"
        @keydown.enter="submitQuestion"
      />
      <button
        type="button"
        class="record-button"
        :class="{ recording: isRecording }"
        :disabled="isBusy"
        :aria-label="isRecording ? '録音停止' : '音声入力開始'"
        @click="toggleRecording"
      >
        <span class="record-icon">{{ isRecording ? "■" : "🎙️" }}</span>
      </button>
      <button
        type="button"
        class="send-button"
        :disabled="isBusy"
        @click="submitQuestion"
      >
        送信
      </button>
    </div>

    <p v-if="isRecording" class="voice-status">
      {{
        speech.isRecording.value
          ? speech.interimText.value || "聞き取り中..."
          : "録音中..."
      }}
    </p>
    <p v-else-if="voiceUnsupported" class="voice-hint">
      このブラウザはブラウザ内音声認識に非対応のため、録音をサーバーへ送信して文字起こしします。
    </p>
  </section>
</template>

<style scoped>
.chat-panel {
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.section-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-heading);
}

.clear-button {
  padding: 0.25rem 0.75rem;
  font-size: 0.8125rem;
  border: 1px solid var(--color-border);
  border-radius: 0.375rem;
  background: var(--color-background-soft);
  color: var(--color-text);
  cursor: pointer;
}

.clear-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.response-area {
  min-height: 120px;
  max-height: 420px;
  overflow-y: auto;
  padding: 1rem;
  background: var(--color-background-soft);
  border: 1px solid var(--color-border);
  border-radius: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.message {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
}

.message.user {
  background: hsla(210, 100%, 50%, 0.1);
  align-self: flex-end;
  max-width: 85%;
}

.message.assistant {
  background: var(--color-background-mute);
  align-self: flex-start;
  max-width: 90%;
}

.message-role {
  font-size: 0.75rem;
  opacity: 0.7;
}

.message-text {
  white-space: pre-wrap;
  line-height: 1.6;
}

.response-loading {
  color: var(--color-text);
  opacity: 0.7;
}

.response-error {
  color: #c62828;
}

.response-placeholder {
  color: var(--color-text);
  opacity: 0.7;
}

.answer-audio {
  width: 100%;
  margin-top: 0.25rem;
}

.input-area {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.question-input {
  flex: 1;
  padding: 0.75rem 1rem;
  font-size: 1rem;
  border: 1px solid var(--color-border);
  border-radius: 0.5rem;
  background: var(--color-background);
  color: var(--color-text);
}

.question-input:focus {
  outline: none;
  border-color: hsla(160, 100%, 37%, 1);
}

.question-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.record-button,
.send-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.75rem 1rem;
  font-size: 1rem;
  border: none;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: background-color 0.2s;
}

.record-button {
  width: 3rem;
  height: 3rem;
  background: hsla(160, 100%, 37%, 1);
  color: white;
}

.record-button.recording {
  background: #f44336;
}

.record-button:disabled,
.send-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.record-icon {
  font-size: 1.25rem;
}

.send-button {
  background: hsla(210, 100%, 50%, 1);
  color: white;
  font-weight: 600;
}

.voice-status {
  font-size: 0.875rem;
  color: #c62828;
}

.voice-hint {
  font-size: 0.8125rem;
  color: var(--color-text);
  opacity: 0.7;
}
</style>
