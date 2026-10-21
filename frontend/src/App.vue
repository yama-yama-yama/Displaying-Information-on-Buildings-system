<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="app-container">
    <header class="app-header">
      <h1 class="app-title">建造物ガイドアシスタント</h1>
      <nav class="app-nav">
        <RouterLink to="/" class="nav-link">ホーム</RouterLink>
        <RouterLink to="/debug" class="nav-link">デバッグ</RouterLink>
      </nav>
    </header>

    <main class="app-main">
      <RouterView />
    </main>

    <footer class="app-footer">
      <small
        >© OpenStreetMap contributors CC BY-SA 2.0
        https://www.openstreetmap.org/copyright/ja</small
      >
    </footer>
  </div>
</template>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--color-background-soft);
  color: var(--color-text);
}

.app-header {
  padding: 1rem;
  background: var(--color-background);
  border-bottom: 1px solid var(--color-border);
  text-align: center;
}

.app-title {
  font-size: 1.25rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.app-nav {
  display: flex;
  justify-content: center;
  gap: 1rem;
}

.nav-link {
  padding: 0.25rem 0.75rem;
  border-radius: 0.375rem;
  color: var(--color-text);
  text-decoration: none;
  font-weight: 500;
}

.nav-link:hover {
  background: var(--color-background-mute);
}

.router-link-active {
  background: hsla(160, 100%, 37%, 1);
  color: white;
}

.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
  max-width: 800px;
  width: 100%;
  margin: 0 auto;
}

.app-footer {
  padding: 0.75rem;
  text-align: center;
  background: var(--color-background);
  border-top: 1px solid var(--color-border);
  color: var(--color-text);
  opacity: 0.7;
}
</style>
