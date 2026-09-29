// The deck editor's keyboard shortcuts: a key press → what it does, or null
// when it belongs to whatever has focus. Text fields keep their keys; buttons
// and composite widgets (tabs, the pane divider, lists) keep their arrows,
// except inside a region marked `data-slide-keys` (the filmstrip, the player)
// where the arrows are about slides.

export type Action =
  | { kind: 'slide'; delta: 1 | -1 }
  | { kind: 'deck'; delta: 1 | -1 }
  | { kind: 'switcher' }
  | { kind: 'save' }
  | { kind: 'compare' }
  | { kind: 'next-turn' }

export interface KeyPress {
  key: string
  altKey: boolean
  ctrlKey: boolean
  metaKey: boolean
  shiftKey: boolean
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
  if (command || e.shiftKey || e.altKey) return null
  if (ctx.reviewActive && key.toLowerCase() === 'd') return { kind: 'compare' }
  if (ctx.reviewActive && key.toLowerCase() === 'n') return { kind: 'next-turn' }
  const delta = arrow(key)
  if (delta === 0 || ownsArrows(e.target)) return null
  return { kind: 'slide', delta }
}
