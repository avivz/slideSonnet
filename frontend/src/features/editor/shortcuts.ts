// The editor's keyboard shortcuts as people see them: the one table behind the
// shortcuts list (the ? button) and the keys shown in tooltips. Its keys are the
// ones ./keymap.ts handles (a test holds the two together), and its type makes
// it name every action the keymap has.
import type { TipContent } from '@/components/tip'

import type { Action } from './keymap'

/** One key press, as the keymap sees it (`key` is KeyboardEvent.key). */
export interface Combo {
  key: string
  ctrl?: boolean
  alt?: boolean
}

export interface Shortcut {
  /** The keys that do it: one press, or a pair such as ← and →. */
  combos: readonly Combo[]
  /** As the list says it. */
  what: string
  /** Only while reviewing changes. */
  review?: boolean
}

export const SHORTCUTS: Record<Action['kind'], Shortcut> = {
  play: { combos: [{ key: ' ' }], what: 'play / pause' },
  slide: { combos: [{ key: 'ArrowLeft' }, { key: 'ArrowRight' }], what: 'previous / next slide' },
  deck: {
    combos: [{ key: 'ArrowLeft', alt: true }, { key: 'ArrowRight', alt: true }],
    what: 'previous / next deck',
  },
  switcher: { combos: [{ key: 'k', ctrl: true }], what: 'switch deck' },
  save: { combos: [{ key: 's', ctrl: true }], what: 'save now (it also saves as you type)' },
  help: { combos: [{ key: '?' }], what: 'show or hide this list' },
  compare: { combos: [{ key: 'd' }], what: 'before only / side by side', review: true },
  'next-turn': { combos: [{ key: 'n' }], what: 'next slide waiting for you', review: true },
}

const KEY_NAMES: Record<string, string> = { ' ': 'Space', ArrowLeft: '←', ArrowRight: '→' }

/** The keys of one press, as written on the keyboard: ['Ctrl', 'K']. */
export function comboKeys(c: Combo): string[] {
  const key = KEY_NAMES[c.key] ?? (c.key.length === 1 ? c.key.toUpperCase() : c.key)
  return [...(c.ctrl ? ['Ctrl'] : []), ...(c.alt ? ['Alt'] : []), key]
}

/** One press as `aria-keyshortcuts` spells it: "Control+K", "Alt+ArrowLeft", "Space". */
function ariaKeys(c: Combo): string {
  const key = c.key === ' ' ? 'Space' : c.key.length === 1 ? c.key.toUpperCase() : c.key
  return [...(c.ctrl ? ['Control'] : []), ...(c.alt ? ['Alt'] : []), key].join('+')
}

/**
 * A tooltip for a control that has a shortcut: what it does, and its keys —
 * all of the action's, or only one (`which`: 0 for ←, 1 for →).
 */
export function shortcutTip(kind: Action['kind'], text: string, which?: number, note?: string): TipContent {
  const combos = SHORTCUTS[kind].combos
  const picked = which === undefined ? combos : combos.slice(which, which + 1)
  return { text, keys: picked.map(comboKeys), shortcuts: picked.map(ariaKeys).join(' '), ...(note ? { note } : {}) }
}
