// "Press ? for shortcuts", by the player: shown the first few times the editor
// opens in this browser, and never again once dismissed or once ? was used.
// The count lives in localStorage — a convenience: without it the hint simply
// shows until put away.
import { ref, type InjectionKey, type Ref } from 'vue'

export const HINT_OPENS = 3
const KEY = 'ss.shortcutHint' // opens so far, or 'done'

export interface ShortcutHint {
  shown: Ref<boolean>
  /** The editor opened: count it, and show the hint if it's still among the first few. */
  opened: () => void
  /** Dismissed, or the shortcuts were found: hide it for good. */
  done: () => void
}

export const SHORTCUT_HINT: InjectionKey<ShortcutHint> = Symbol('shortcut-hint')

export function createShortcutHint(): ShortcutHint {
  const shown = ref(false)
  function opened(): void {
    let seen: string | null = null
    try {
      seen = localStorage.getItem(KEY)
    } catch {
      // nothing kept: show it
    }
    if (seen === 'done') return
    const count = Number(seen ?? 0) || 0
    if (count >= HINT_OPENS) return
    shown.value = true
    try {
      localStorage.setItem(KEY, String(count + 1))
    } catch {
      // nothing kept
    }
  }
  function done(): void {
    shown.value = false
    try {
      localStorage.setItem(KEY, 'done')
    } catch {
      // nothing kept: it's gone for this visit
    }
  }
  return { shown, opened, done }
}
