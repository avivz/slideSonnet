// Leaving a deck — for another deck, the library, or back/forward in the
// browser — saves the narration first and stays put when it can't be saved.
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'

import { useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'
import { usePlayerStore } from '@/stores/player'

/** Save, drop the clips only this tab asked for, stop playback; false: stay on this deck. */
export async function leaveDeck(): Promise<boolean> {
  if (!(await useEditorStore().ensureSaved())) return false // the field being typed in must not vanish
  await useGenerationStore().leave()
  usePlayerStore().stop()
  return true
}

/** Guard every way out of the deck page (call from its setup). */
export function useLeaveGuard(): void {
  onBeforeRouteUpdate((to, from) => to.params.token === from.params.token || leaveDeck())
  onBeforeRouteLeave(() => leaveDeck())
}
