import { describe, expect, it } from 'vitest'

import { EventStream, type EventSourceLike, type ServerEvent } from '@/api/events'

class FakeSource implements EventSourceLike {
  closed = false
  private listeners = new Map<string, ((e: MessageEvent<string>) => void)[]>()
  addEventListener(type: string, listener: (e: MessageEvent<string>) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }
  close(): void {
    this.closed = true
  }
  emit(type: string, seq: number, data: unknown): void {
    const event = new MessageEvent<string>(type, { data: JSON.stringify(data), lastEventId: String(seq) })
    for (const l of this.listeners.get(type) ?? []) l(event)
  }
}

function setup() {
  const source = new FakeSource()
  const stream = new EventStream('/events', () => source)
  const got: ServerEvent[] = []
  let resyncs = 0
  stream.on('deck.changed', (e) => got.push(e))
  stream.onResync(() => resyncs++)
  stream.open()
  return { source, stream, got, resyncs: () => resyncs }
}

describe('EventStream', () => {
  it('delivers typed events with their deck and sequence', () => {
    const { source, got } = setup()
    source.emit('deck.changed', 1, { type: 'deck.changed', deck: 'abc', narration: 'r1' })
    expect(got).toEqual([{ seq: 1, type: 'deck.changed', deck: 'abc', data: expect.objectContaining({ narration: 'r1' }) }])
  })

  it('asks for a resync on a server resync or a sequence gap', () => {
    const { source, resyncs } = setup()
    source.emit('deck.changed', 1, {})
    source.emit('deck.changed', 2, {})
    expect(resyncs()).toBe(0)
    source.emit('deck.changed', 5, {}) // 3 and 4 never arrived
    expect(resyncs()).toBe(1)
    source.emit('resync', 9, {})
    expect(resyncs()).toBe(2)
  })

  it('stops listening when closed', () => {
    const { source, stream } = setup()
    stream.close()
    expect(source.closed).toBe(true)
  })
})
