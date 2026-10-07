// `v-tip`: a small tooltip for a control — what it does, its keys as key caps,
// and maybe a line of advice. It shows after a short pause under the pointer
// and at once when the control is tabbed to; it goes when the pointer leaves,
// on Escape, and on a click. One tooltip serves the page, placed above the
// control (below when there's no room) and kept inside the window.
//
// It only describes: the control keeps its own name (its text or aria-label).
// The keys also go on the control as `aria-keyshortcuts`.
import type { Directive } from 'vue'

import './tip.css'

export interface TipContent {
  text: string
  /** Key caps: each entry one press (['Ctrl', 'K']); several are alternatives. */
  keys?: readonly (readonly string[])[]
  /** A line of advice under the text. */
  note?: string
  /** The keys for assistive tech, as `aria-keyshortcuts` spells them ("Control+K"). */
  shortcuts?: string
}
export type TipValue = TipContent | string | null | undefined

export const TIP_DELAY_MS = 300
const GAP = 6 // between the control and the tooltip
const MARGIN = 4 // from the window's edges
const TIP_ID = 'app-tip'

let tipEl: HTMLDivElement | null = null
let owner: HTMLElement | null = null // the control the tooltip is showing for
let pending: HTMLElement | null = null // the control waiting out the hover pause
let timer: ReturnType<typeof setTimeout> | null = null
const contents = new WeakMap<HTMLElement, TipContent | null>()
const cleanups = new WeakMap<HTMLElement, () => void>()

function normalize(value: TipValue): TipContent | null {
  if (!value) return null
  return typeof value === 'string' ? { text: value } : value
}

function tipElement(): HTMLDivElement {
  if (tipEl === null || !tipEl.isConnected) {
    tipEl = document.createElement('div')
    tipEl.id = TIP_ID
    tipEl.className = 'app-tip'
    tipEl.setAttribute('role', 'tooltip')
    document.body.append(tipEl)
  }
  return tipEl
}

function render(tip: HTMLElement, content: TipContent): void {
  const line = document.createElement('div')
  line.className = 'line'
  const text = document.createElement('span')
  text.textContent = content.text
  line.append(text)
  if (content.keys?.length) {
    const keys = document.createElement('span')
    keys.className = 'keys'
    content.keys.forEach((press, i) => {
      if (i > 0) keys.append(' ')
      press.forEach((key, j) => {
        if (j > 0) keys.append('+')
        const kbd = document.createElement('kbd')
        kbd.textContent = key
        keys.append(kbd)
      })
    })
    line.append(keys)
  }
  tip.replaceChildren(line)
  if (content.note) {
    const note = document.createElement('div')
    note.className = 'note'
    note.textContent = content.note
    tip.append(note)
  }
}

/** Above the control, or below it when there's no room above; never off the window. */
function place(tip: HTMLElement, el: HTMLElement): void {
  const r = el.getBoundingClientRect()
  const width = window.innerWidth || document.documentElement.clientWidth
  const above = r.top - tip.offsetHeight - GAP
  const top = above >= MARGIN ? above : r.bottom + GAP
  const centred = r.left + r.width / 2 - tip.offsetWidth / 2
  const left = Math.max(MARGIN, Math.min(centred, width - tip.offsetWidth - MARGIN))
  tip.style.top = `${Math.round(top)}px`
  tip.style.left = `${Math.round(left)}px`
}

function onDocumentKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') hideTip()
}
function onScroll(): void {
  hideTip() // the control moved away from under it
}

function clearPending(): void {
  if (timer !== null) clearTimeout(timer)
  timer = null
  pending = null
}

function showTip(el: HTMLElement): void {
  clearPending()
  const content = contents.get(el)
  if (!content || !el.isConnected) return
  if (owner !== null && owner !== el) hideTip()
  const tip = tipElement()
  render(tip, content)
  tip.classList.add('on')
  place(tip, el)
  if (owner !== el) {
    owner = el
    el.setAttribute('aria-describedby', TIP_ID)
    document.addEventListener('keydown', onDocumentKey, true)
    window.addEventListener('scroll', onScroll, true)
  }
}

/** Put the tooltip away (only if it's `el`'s, when given). */
function hideTip(el?: HTMLElement): void {
  if (el === undefined || pending === el) clearPending()
  if (owner === null || (el !== undefined && owner !== el)) return
  owner.removeAttribute('aria-describedby')
  owner = null
  tipEl?.classList.remove('on')
  document.removeEventListener('keydown', onDocumentKey, true)
  window.removeEventListener('scroll', onScroll, true)
}

// Focus that came from a click or a tap is the pointer's (the hover pause decides
// then); focus that came from the keys shows the tooltip at once. Browsers keep
// the same distinction for :focus-visible.
let pointerLast = false
let modalityWatched = false
function watchModality(): void {
  if (modalityWatched) return
  modalityWatched = true
  document.addEventListener('pointerdown', () => (pointerLast = true), true)
  document.addEventListener('keydown', () => (pointerLast = false), true)
}

function setContent(el: HTMLElement, value: TipValue): void {
  const content = normalize(value)
  contents.set(el, content)
  if (content?.shortcuts) el.setAttribute('aria-keyshortcuts', content.shortcuts)
  else el.removeAttribute('aria-keyshortcuts')
}

export const vTip: Directive<HTMLElement, TipValue> = {
  mounted(el, binding) {
    watchModality()
    setContent(el, binding.value)
    const enter = (event: PointerEvent): void => {
      if (event.pointerType === 'touch' || owner === el) return
      clearPending()
      pending = el
      timer = setTimeout(() => showTip(el), TIP_DELAY_MS)
    }
    const leave = (): void => hideTip(el)
    const focus = (): void => {
      if (!pointerLast) showTip(el)
    }
    const listeners: [string, EventListener][] = [
      ['pointerenter', enter as EventListener],
      ['pointerleave', leave],
      ['focus', focus],
      ['blur', leave],
      ['pointerdown', leave],
      ['click', leave],
    ]
    for (const [type, fn] of listeners) el.addEventListener(type, fn)
    cleanups.set(el, () => {
      for (const [type, fn] of listeners) el.removeEventListener(type, fn)
    })
  },
  updated(el, binding) {
    if (binding.value === binding.oldValue) return
    setContent(el, binding.value)
    if (owner !== el) return
    if (contents.get(el)) showTip(el) // Play became Pause under the pointer: say so
    else hideTip(el)
  },
  beforeUnmount(el) {
    hideTip(el)
    cleanups.get(el)?.()
  },
}
