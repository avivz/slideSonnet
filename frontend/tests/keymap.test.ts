// The editor's shortcuts, as a table: which key, pressed where, does what.
import { describe, expect, it } from 'vitest'

import { shortcut, type Action, type KeyPress } from '@/features/editor/keymap'
import { SHORTCUTS, comboKeys } from '@/features/editor/shortcuts'

document.body.innerHTML = `
  <main id="page">
    <textarea id="text"></textarea>
    <div role="tablist"><button id="tab" role="tab">Audio</button></div>
    <div id="split" role="separator" tabindex="0"></div>
    <button id="button">Export</button>
    <nav data-slide-keys><button id="thumb">3</button></nav>
  </main>`
const at = (id: string): Element => document.getElementById(id) as Element

function press(key: string, target: Element, mods: Partial<KeyPress> = {}): KeyPress {
  return { key, target, altKey: false, ctrlKey: false, metaKey: false, shiftKey: false, ...mods }
}

const cases: [string, KeyPress, Action | null, { dialogOpen?: boolean; reviewActive?: boolean }?][] = [
  ['arrows step slides from the page', press('ArrowRight', at('page')), { kind: 'slide', delta: 1 }],
  ['and from a filmstrip thumbnail', press('ArrowUp', at('thumb')), { kind: 'slide', delta: -1 }],
  ['not on a tab', press('ArrowRight', at('tab')), null],
  ['not on the pane divider', press('ArrowDown', at('split')), null],
  ['not on another button', press('ArrowLeft', at('button')), null],
  ['not in a text field', press('ArrowLeft', at('text')), null],
  ['not under a dialog', press('ArrowLeft', at('page')), null, { dialogOpen: true }],
  ['Alt+arrows switch decks', press('ArrowRight', at('button'), { altKey: true }), { kind: 'deck', delta: 1 }],
  ['but move by word in a text field', press('ArrowRight', at('text'), { altKey: true }), null],
  ['Ctrl+S saves, even while typing', press('s', at('text'), { ctrlKey: true }), { kind: 'save' }],
  ['Cmd+K opens the deck switcher', press('k', at('page'), { metaKey: true }), { kind: 'switcher' }],
  ['D compares under review', press('d', at('page')), { kind: 'compare' }, { reviewActive: true }],
  ['N goes to the next your-turn', press('n', at('button')), { kind: 'next-turn' }, { reviewActive: true }],
  ['letters are typed, not shortcuts', press('n', at('text')), null, { reviewActive: true }],
  ['D does nothing outside review', press('d', at('page')), null],
  ['Space plays / pauses from the page', press(' ', at('page')), { kind: 'play' }],
  ['not in a text field', press(' ', at('text')), null],
  ['nor on a focused button: it presses itself', press(' ', at('thumb')), null],
  ['nor on a tab', press(' ', at('tab')), null],
  ['holding Space down toggles once', press(' ', at('page'), { repeat: true }), null],
  ['? shows the shortcuts', press('?', at('button'), { shiftKey: true }), { kind: 'help' }],
  ['but is typed in a text field', press('?', at('text'), { shiftKey: true }), null],
]

describe('editor shortcuts', () => {
  it.each(cases)('%s', (_name, event, action, ctx) => {
    expect(shortcut(event, { dialogOpen: false, reviewActive: false, ...ctx })).toEqual(action)
  })
})

// One table names every shortcut for the list and the tooltips (its type makes it
// cover every action): its keys must be the ones the keymap really handles.
describe('the shortcuts table', () => {
  it('shows each action with keys that do it', () => {
    for (const [kind, entry] of Object.entries(SHORTCUTS)) {
      for (const c of entry.combos) {
        const event = press(c.key, at('page'), { ctrlKey: !!c.ctrl, altKey: !!c.alt, shiftKey: c.key === '?' })
        const action = shortcut(event, { dialogOpen: false, reviewActive: !!entry.review })
        expect(action?.kind, comboKeys(c).join('+')).toBe(kind)
      }
    }
    expect(SHORTCUTS.deck.combos.map(comboKeys)).toEqual([['Alt', '←'], ['Alt', '→']])
    expect(SHORTCUTS.play.combos.map(comboKeys)).toEqual([['Space']])
  })
})
