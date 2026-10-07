// While a narration field has focus, playback doesn't move the editor away
// (player.editing) and auto-generate skips the line being typed
// (generation.focusedSpeech); a click in a line's words while playing plays on
// from there. Shared by the slide view and the script view.
import { onBeforeUnmount, type Ref } from 'vue'

import { useGenerationStore } from '@/stores/generation'
import { usePlayerStore } from '@/stores/player'

export interface SpeechRef {
  slideId: string
  index: number
}

/**
 * Focus and click handlers for the element `root`: `locate` names the spoken
 * line an element belongs to (null: some other field of the narration).
 */
export function useEditingFocus(
  root: Ref<HTMLElement | null>,
  locate: (el: HTMLElement) => SpeechRef | null,
): {
  onFocusIn: (event: FocusEvent) => void
  onFocusOut: (event: FocusEvent) => void
  onClick: (event: MouseEvent) => void
} {
  const player = usePlayerStore()
  const generation = useGenerationStore()
  let holding = false

  function release(): void {
    if (!holding) return
    holding = false
    generation.focusedSpeech = null
    player.setEditing(false)
  }

  function onFocusIn(event: FocusEvent): void {
    holding = true
    player.setEditing(true)
    generation.focusedSpeech = locate(event.target as HTMLElement)
  }
  function onFocusOut(event: FocusEvent): void {
    const next = event.relatedTarget as Node | null
    if (next && root.value?.contains(next)) return // moving within the narration
    release()
  }
  /** A click in a line's words (not a drag selecting some): playback goes on from the word clicked. */
  function onClick(event: MouseEvent): void {
    const el = event.target
    if (!(el instanceof HTMLTextAreaElement) || el.selectionStart !== el.selectionEnd) return
    const line = locate(el)
    if (line) void player.playFrom(line.slideId, line.index, el.selectionStart)
  }
  onBeforeUnmount(release) // the view went away with a field focused

  return { onFocusIn, onFocusOut, onClick }
}
