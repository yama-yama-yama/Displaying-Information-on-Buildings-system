<script setup lang="ts">
const props = defineProps<{
  latitude?: number
  longitude?: number
  accuracy?: number
  error?: string
}>()
</script>

<template>
  <section class="location-info">
    <h2 class="section-title">現在位置</h2>
    <p v-if="props.error" class="location-error">
      {{ props.error }}
    </p>
    <div class="location-grid">
      <div class="location-item">
        <span class="location-label">緯度</span>
        <span class="location-value">{{ props.latitude?.toFixed(6) ?? '---' }}</span>
      </div>
      <div class="location-item">
        <span class="location-label">経度</span>
        <span class="location-value">{{ props.longitude?.toFixed(6) ?? '---' }}</span>
      </div>
      <div class="location-item">
        <span class="location-label">精度</span>
        <span class="location-value">{{ props.accuracy ? `${Math.round(props.accuracy)} m` : '---' }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.location-info {
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

.location-error {
  margin-bottom: 0.75rem;
  padding: 0.5rem;
  background: #ffebee;
  color: #c62828;
  border-radius: 0.375rem;
  font-size: 0.875rem;
}

.location-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.5rem;
}

.location-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.location-label {
  font-size: 0.75rem;
  color: var(--color-text);
  opacity: 0.7;
}

.location-value {
  font-size: 0.9375rem;
  font-weight: 500;
}
</style>
