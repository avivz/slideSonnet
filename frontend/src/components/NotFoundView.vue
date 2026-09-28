<script setup lang="ts">
import AppWordmark from './AppWordmark.vue'
</script>

<template>
  <main class="not-found">
    <AppWordmark />
    <h1>Nothing here</h1>
    <p>This address isn't a page of the editor. <a href="/">Back to your decks</a>.</p>
  </main>
</template>

<style scoped>
.not-found {
  display: grid;
  justify-items: center;
  gap: var(--space-3);
  padding: 96px var(--space-4);
  text-align: center;
}
h1 {
  margin: var(--space-4) 0 0;
  font-size: var(--text-lg);
  font-weight: 600;
}
p {
  margin: 0;
  color: var(--dim);
}
</style>
