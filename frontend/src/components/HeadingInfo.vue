<script setup lang="ts">
import { computed } from 'vue'
import { useDeviceHeading, getDirectionByIndex } from '../composables/useDeviceHeading'

const { state, CARDINAL_DIRECTIONS, startTracking, setManualFacing, getFacing } = useDeviceHeading()

const headingLabel = computed(() => {
  if (state.value.heading === null) return ''
  return `（${getDirectionByIndex(Math.round(state.value.heading / 45)).label}）`
})

defineExpose({ getFacing })
</script>

<template>
  <section class="heading-info">
    <h2 class="section-title">向いている方向</h2>

    <div v-if="!state.isManual" class="heading-status">
      <span class="heading-value">
        {{ state.heading !== null ? `${Math.round(state.heading)}°` : '---' }}
      </span>
      <span class="heading-label">
        {{ headingLabel }}
      </span>
      <button v-if="!state.isSupported" type="button" class="small-button" @click="startTracking">
        向き取得を開始
      </button>
    </div>

    <div v-if="state.error" class="heading-error">
      {{ state.error }}
    </div>

    <div class="manual-selector">
      <label class="manual-label">
        <input
          v-model="state.isManual"
          type="checkbox"
        />
        手動で向きを指定する
      </label>
      <select
        v-if="state.isManual"
        :value="state.manualFacing"
        class="direction-select"
        @change="setManualFacing(($event.target as HTMLSelectElement).value)"
      >
        <option v-for="dir in CARDINAL_DIRECTIONS" :key="dir.value" :value="dir.value">
          {{ dir.label }}
        </option>
      </select>
    </div>
  </section>
</template>

<style scoped>
.heading-info {
  background: var(--color-background);
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  padding: 1rem;
}

.section-title {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
  color: var(--color-heading);
}

.heading-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.heading-value {
  font-size: 1.25rem;
  font-weight: 700;
}

.heading-label {
  font-size: 0.9375rem;
  color: var(--color-text);
  opacity: 0.8;
}

.heading-error {
  margin-bottom: 0.75rem;
  padding: 0.5rem;
  background: #ffebee;
  color: #c62828;
  border-radius: 0.375rem;
  font-size: 0.875rem;
}

.manual-selector {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.manual-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9375rem;
  cursor: pointer;
}

.direction-select {
  padding: 0.5rem;
  font-size: 1rem;
  border: 1px solid var(--color-border);
  border-radius: 0.375rem;
  background: var(--color-background-soft);
  color: var(--color-text);
}

.small-button {
  padding: 0.375rem 0.75rem;
  font-size: 0.875rem;
  border: none;
  border-radius: 0.375rem;
  background: hsla(160, 100%, 37%, 1);
  color: white;
  cursor: pointer;
}
</style>
