<script setup lang="ts">
// How a slide's narration changed since the review began, word by word.
defineProps<{ words: string[][]; title?: string }>()
</script>

<template>
  <p class="diff">
    <span class="section-title">{{ title ?? 'Narration changes' }}</span>
    <template v-for="([op, word], i) in words" :key="i">
      <del v-if="op === '-'">{{ word }}</del>
      <ins v-else-if="op === '+'">{{ word }}</ins>
      <span v-else>{{ word }}</span>{{ ' ' }}
    </template>
  </p>
</template>

<style scoped>
.diff {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  background: var(--raised);
  border: 1px solid var(--line);
  border-radius: var(--radius-field);
  font-size: var(--text-md);
  line-height: 1.6;
}
.section-title {
  margin-right: var(--space-2);
}
del {
  color: var(--err);
}
ins {
  color: var(--ok);
  text-decoration: none;
  border-bottom: 1px solid var(--ok);
}
</style>
