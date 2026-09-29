<script setup lang="ts">
// Shows the question `useConfirm().ask()` is waiting on (one at a time).
import { useConfirm } from '@/stores/confirm'

import AppDialog from './AppDialog.vue'

const confirm = useConfirm()
</script>

<template>
  <AppDialog :open="confirm.shown !== null" :title="confirm.shown?.title ?? ''" @close="confirm.answer(false)">
    <p v-for="line in confirm.shown?.lines ?? []" :key="line" class="line">{{ line }}</p>
    <template #actions>
      <button class="btn quiet" type="button" @click="confirm.answer(false)">Cancel</button>
      <button
        class="btn"
        :class="confirm.shown?.danger ? 'danger' : 'primary'"
        type="button"
        data-testid="confirm-yes"
        autofocus
        @click="confirm.answer(true)"
      >
        {{ confirm.shown?.yes ?? 'OK' }}
      </button>
    </template>
  </AppDialog>
</template>

<style scoped>
.line {
  margin: 0;
}
</style>
