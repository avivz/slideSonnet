// The deck editor's keyboard shortcuts: a key press → what it does, or null
// when it belongs to whatever has focus. Text fields keep their keys; buttons
// and composite widgets (tabs, the pane divider, lists) keep their arrows,
// except inside a region marked `data-slide-keys` (the filmstrip, the player)
// where the arrows are about slides. Space plays and pauses unless a focused
// control presses itself with it; `?` shows the list of shortcuts.
// What each action is called and which keys show for it: ./shortcuts.ts.

export type Action =
  | { kind: 'slide'; delta: 1 | -1 }
  | { kind: 'deck'; delta: 1 | -1 }
  | { kind: 'switcher' }
  | { kind: 'save' }
  | { kind: 'compare' }
  | { kind: 'next-turn' }
  | { kind: 'play' }
  | { kind: 'help' }

export interface KeyPress {
  key: string
  altKey: boolean
  ctrlKey: boolean
  metaKey: boolean
  shiftKey: boolean
  /** The key is held down (auto-repeat). */
  repeat?: boolean
  target: EventTarget | null
}

export interface KeyContext {
  /** A dialog is open: it owns the keyboard. */
  dialogOpen: boolean
  reviewActive: boolean
}

/** Elements whose arrow keys (or all keys) mean something of their own. */
const OWNS_ARROWS =
  'button, a[href], summary, audio, video, [role="tab"], [role="tablist"], [role="separator"], ' +
  '[role="slider"], [role="listbox"], [role="option"], [role="menu"], [role="menuitem"], ' +
  '[role="radiogroup"], [role="radio"], [role="spinbutton"], [role="grid"], [role="tree"]'

/** Elements that do something of their own on Space (a button presses itself). */
const OWNS_SPACE =
  'button, summary, audio, video, [role="button"], [role="tab"], [role="checkbox"], [role="switch"], ' +
  '[role="radio"], [role="option"], [role="menuitem"], [role="slider"], [role="separator"]'

function asElement(target: EventTarget | null): Element | null {
  return target instanceof Element ? target : null
}

/** Typing: a text field, a select, or anything editable. */
export function isTyping(target: EventTarget | null): boolean {
  const el = asElement(target)
  if (el === null) return false
  return (el as HTMLElement).isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
}

function ownsArrows(target: EventTarget | null): boolean {
  const el = asElement(target)
  if (el === null || el.closest('[data-slide-keys]')) return false
  return el.closest(OWNS_ARROWS) !== null
}

function arrow(key: string): 1 | -1 | 0 {
  if (key === 'ArrowLeft' || key === 'ArrowUp') return -1
  if (key === 'ArrowRight' || key === 'ArrowDown') return 1
  return 0
}

export function shortcut(e: KeyPress, ctx: KeyContext): Action | null {
  if (ctx.dialogOpen) return null
  const key = e.key
  const command = e.ctrlKey || e.metaKey
  if (command && key.toLowerCase() === 's') return { kind: 'save' } // anywhere, the field too
  if (command && key.toLowerCase() === 'k') return { kind: 'switcher' }
  if (isTyping(e.target)) return null // Alt+arrows move by word in a text field
  if (e.altKey && !command && !e.shiftKey && (key === 'ArrowLeft' || key === 'ArrowRight')) {
    return { kind: 'deck', delta: key === 'ArrowRight' ? 1 : -1 }
  }
  if (key === '?' && !command && !e.altKey) return { kind: 'help' } // Shift+/ on most layouts
  if (command || e.shiftKey || e.altKey) return null
  if (key === ' ') {
    if (e.repeat || asElement(e.target)?.closest(OWNS_SPACE)) return null
    return { kind: 'play' }
  }
  if (ctx.reviewActive && key.toLowerCase() === 'd') return { kind: 'compare' }
  if (ctx.reviewActive && key.toLowerCase() === 'n') return { kind: 'next-turn' }
  const delta = arrow(key)
  if (delta === 0 || ownsArrows(e.target)) return null
  return { kind: 'slide', delta }
}
