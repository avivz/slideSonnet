// The tooltip: shows after a pause under the pointer, at once when tabbed to,
// and gets out of the way (pointer leaves, Escape, a click).
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, withDirectives } from 'vue'

import { TIP_DELAY_MS, vTip, type TipContent } from '@/components/tip'

const PLAY: TipContent = { text: 'Play', keys: [['Space']], note: 'Click any line to jump there', shortcuts: 'Space' }

const Host = defineComponent({
  setup() {
    return () => withDirectives(h('button', { 'aria-label': 'Play', 'data-testid': 'b' }), [[vTip, PLAY]])
  },
})

function shown(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[role="tooltip"].on')
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('tooltip', () => {
  it('shows after a pause under the pointer, with its keys, and goes when the pointer leaves', async () => {
    const w = mount(Host, { attachTo: document.body })
    const b = w.get('[data-testid="b"]')
    expect(b.attributes('aria-keyshortcuts')).toBe('Space')
    await b.trigger('pointerenter')
    vi.advanceTimersByTime(TIP_DELAY_MS - 10)
    expect(shown()).toBeNull()
    vi.advanceTimersByTime(10)
    const tip = shown()!
    expect(tip.textContent).toContain('Play')
    expect(tip.textContent).toContain('Click any line to jump there')
    expect([...tip.querySelectorAll('kbd')].map((k) => k.textContent)).toEqual(['Space'])
    expect(b.attributes('aria-describedby')).toBe(tip.id)
    await b.trigger('pointerleave')
    expect(shown()).toBeNull()
    expect(b.attributes('aria-describedby')).toBeUndefined()
    w.unmount()
  })

  it('shows at once when tabbed to; Escape and a click put it away', async () => {
    const w = mount(Host, { attachTo: document.body })
    const b = w.get('[data-testid="b"]')
    ;(b.element as HTMLElement).focus()
    expect(shown()).not.toBeNull()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(shown()).toBeNull()
    ;(b.element as HTMLElement).blur()
    ;(b.element as HTMLElement).focus()
    expect(shown()).not.toBeNull()
    await b.trigger('click')
    expect(shown()).toBeNull()
    w.unmount()
  })

  it('goes below a control at the top of the window, and stays inside it', async () => {
    const w = mount(Host, { attachTo: document.body })
    const b = w.get('[data-testid="b"]')
    b.element.getBoundingClientRect = () => new DOMRect(-20, 2, 30, 28)
    ;(b.element as HTMLElement).focus()
    const tip = shown()!
    expect(parseFloat(tip.style.top)).toBeGreaterThanOrEqual(30) // under the button, not over it
    expect(parseFloat(tip.style.left)).toBeGreaterThanOrEqual(0)
    w.unmount()
  })
})
