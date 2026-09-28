<script setup lang="ts">
defineProps<{ tone?: 'warn' | 'err' }>()
</script>

<template>
  <div class="notice" :class="tone ?? 'warn'" role="status">
    <slot />
  </div>
</template>

<style scoped>
.notice {
  border-radius: var(--radius-card);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  line-height: 1.5;
}
.warn {
  background: var(--warn-fill);
  border: 1px solid rgb(255 200 87 / 30%);
}
.err {
  background: var(--err-fill);
  border: 1px solid rgb(255 107 107 / 35%);
}
</style>
