// Server-Sent Events from `/api/v1/events`: hints to refetch, never state.
//
// Every event carries a sequence number. The browser's EventSource sends the
// last one it saw on reconnect (Last-Event-ID) and the server replays what was
// missed — or sends `resync` when it can't, which is also what this client
// reports when it notices a gap itself. On `resync`, refetch every snapshot and
// active job instead of trusting partial history.

export interface ServerEvent {
  seq: number
  type: string
  deck: string | null
  data: Record<string, unknown>
}

export type EventHandler = (event: ServerEvent) => void

/** The slice of EventSource this client uses (so tests can supply a fake). */
export interface EventSourceLike {
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void
  close(): void
}

export type EventSourceFactory = (url: string) => EventSourceLike

export const EVENT_TYPES = [
  'deck.changed',
  'job.created',
  'job.updated',
  'job.progress',
  'job.finished',
  'generation.changed',
  'generation.failed',
] as const

export class EventStream {
  private source: EventSourceLike | null = null
  private lastSeq: number | null = null
  private readonly handlers = new Map<string, Set<EventHandler>>()
  private readonly resyncHandlers = new Set<() => void>()

  constructor(
    private readonly url = '/api/v1/events',
    private readonly factory: EventSourceFactory = (u) => new EventSource(u),
  ) {}

  on(type: string, handler: EventHandler): () => void {
    let set = this.handlers.get(type)
    if (set === undefined) {
      set = new Set()
      this.handlers.set(type, set)
    }
    set.add(handler)
    return () => set.delete(handler)
  }

  /** Called when events may have been missed: refetch everything you show. */
  onResync(handler: () => void): () => void {
    this.resyncHandlers.add(handler)
    return () => this.resyncHandlers.delete(handler)
  }

  open(): void {
    if (this.source !== null) return
    const source = this.factory(this.url)
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, (message) => this.receive(type, message))
    }
    source.addEventListener('resync', (message) => {
      this.lastSeq = Number(message.lastEventId) || this.lastSeq
      this.resync()
    })
    this.source = source
  }

  close(): void {
    this.source?.close()
    this.source = null
  }

  private receive(type: string, message: MessageEvent<string>): void {
    const seq = Number(message.lastEventId)
    if (this.lastSeq !== null && Number.isFinite(seq) && seq > this.lastSeq + 1) {
      this.lastSeq = seq
      this.resync() // a gap the server didn't flag (e.g. a proxy dropped events)
    } else if (Number.isFinite(seq)) {
      this.lastSeq = seq
    }
    let payload: Record<string, unknown>
    try {
      payload = JSON.parse(message.data) as Record<string, unknown>
    } catch {
      return
    }
    const event: ServerEvent = {
      seq,
      type,
      deck: typeof payload.deck === 'string' ? payload.deck : null,
      data: payload,
    }
    for (const handler of this.handlers.get(type) ?? []) handler(event)
  }

  private resync(): void {
    for (const handler of this.resyncHandlers) handler()
  }
}
