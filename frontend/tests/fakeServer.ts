// An in-memory stand-in for the editor API: enough of /api/v1 for store and
// component tests (snapshots, revision-checked saves, commands, jobs).
import {
  ApiClient,
  ApiError,
  type BlockDTO,
  type DeckSnapshot,
  type GenerationStatusDTO,
  type MetaDTO,
} from '@/api/client'

export const META: MetaDTO = {
  transitions: [
    { key: 'cut', label: 'Cut', options: [] },
    { key: 'fade', label: 'Fade', options: [] },
    { key: 'wipe', label: 'Wipe', options: [['Left', 'wipeleft'], ['Right', 'wiperight']] },
  ],
  aliases: { crossfade: 'fade' },
  engines: [
    { name: 'inworld', paid: true, realtime: true, installed: true },
    { name: 'kokoro', paid: false, realtime: true, installed: true },
  ],
}

export function speech(text: string): BlockDTO['segments'][number] {
  return { kind: 'speech', text, voice: null, pace: null, direction: null }
}

export class FakeServer {
  rev = 1
  narration: Record<string, BlockDTO> = {}
  pages = ['a', 'b', 'c']
  pdfRev = 'p'
  /** Page images on disk (false: a fresh render hasn't produced them yet). */
  imagesRendered = true
  saves: { slideId: string; body: unknown }[] = []
  /** Hold every save until release() — to test typing during an in-flight save. */
  hold: (() => void)[] = []
  holding = false
  /** Hold every save's answer (it is written already) until release(). */
  holdingAnswers = false
  cached: Record<string, boolean[]> = {}
  /** Engine that bills: generation / preview / export refuse without allow_paid. */
  paid = false
  generated: { targets: unknown; force: boolean; allow_paid: boolean }[] = []
  jobs: { kind: string; body: Record<string, unknown> }[] = []
  commands: Record<string, unknown>[] = []
  blockers: string[] = []

  constructor(texts: Record<string, string> = { a: 'Hello.', b: 'World.' }) {
    for (const [id, text] of Object.entries(texts)) this.setText(id, text)
  }

  setText(id: string, text: string): void {
    this.narration[id] = {
      slide_id: id,
      segments: [speech(text)],
      transition_in: { kind: 'cut', seconds: 0 },
      transition_out: { kind: 'cut', seconds: 0 },
    }
  }

  /** Someone else edits the file on disk. */
  externalEdit(id: string, text: string): void {
    this.setText(id, text)
    this.rev++
  }

  get revision(): string {
    return `r${this.rev}`
  }

  snapshot(): DeckSnapshot {
    return {
      token: 'tok', name: 'deck', label: 'week1/deck',
      revisions: { narration: this.revision, pdf: this.pdfRev, config: 'c', review: 'x' },
      engine: 'kokoro', engines: META.engines,
      pages: this.pages.map((id, index) => ({
        index, slide_id: id, status: this.narration[id] ? 'ready' : 'empty', image_url: this.imagesRendered ? `/img/${this.pdfRev}/${id}.png` : null,
        incoming: { kind: 'cut', seconds: 0 },
        audio: { speech: this.narration[id] ? 1 : 0, cached: (this.cached[id] ?? []).filter(Boolean).length },
        clips: (this.narration[id]?.segments ?? []).filter((s) => s.kind === 'speech')
          .map((_, i) => ({ cached: this.cached[id]?.[i] ?? false, seconds: null, bytes: null })),
      })),
      narration: structuredClone(this.narration),
      orphans: [], duplicates: {}, diagnostics: [],
      voices: { map: {}, default_voice: null, names: [], resolved: {} },
      missing_audio: 0,
      silence: { start: 0.3, end: 0.6 }, engine_warm: true, neighbours: { prev: null, next: null },
      aspect: 16 / 9,
    } as DeckSnapshot
  }

  client(): ApiClient {
    const c = new ApiClient({ fetch: async () => new Response('{}') })
    c.meta = async () => META
    c.snapshot = async () => this.snapshot()
    c.saveSlide = async (_t, slideId, body) => {
      if (this.holding) await new Promise<void>((resolve) => this.hold.push(resolve))
      if (body.expected_revision !== this.revision) {
        throw new ApiError(409, 'revision_conflict', 'The narration file changed.')
      }
      this.saves.push({ slideId, body })
      this.narration[slideId] = JSON.parse(JSON.stringify({ // plain data, as over the wire
        slide_id: slideId, segments: body.segments,
        transition_in: body.transition_in ?? { kind: 'cut', seconds: 0 },
        transition_out: body.transition_out ?? { kind: 'cut', seconds: 0 },
      }))
      this.rev++
      const revision = this.revision
      if (this.holdingAnswers) await new Promise<void>((resolve) => this.hold.push(resolve))
      return { changed: true, revision }
    }
    c.generation = async () => ({ ...this.status() })
    c.focus = async () => ({ count: 1 })
    c.cancelGeneration = async () => ({ count: 0 })
    c.generate = async (_t, body) => {
      if (this.paid && !body.allow_paid) {
        throw new ApiError(403, 'paid_confirmation_required', 'This will spend credits.')
      }
      this.generated.push({ targets: body.targets ?? null, force: body.force ?? false, allow_paid: body.allow_paid ?? false })
      return { ...this.status(Array.isArray(body.targets) ? body.targets.length : 3) }
    }
    c.exportBlockers = async () => this.blockers
    c.startJob = async (_t, body) => {
      const b = body as unknown as Record<string, unknown>
      // like the server: a paid engine needs permission only when clips are missing
      const slides = b.kind === 'preview' && b.slide_id ? [String(b.slide_id)] : Object.keys(this.narration)
      const missing = slides.some((id) => (this.cached[id] ?? [false]).some((c) => !c))
      if (this.paid && missing && b.kind !== 'render_pages' && b.kind !== 'warm' && !b.allow_paid) {
        throw new ApiError(403, 'paid_confirmation_required', 'This will spend credits.')
      }
      this.jobs.push({ kind: String(b.kind), body: b })
      return { id: `job-${this.jobs.length}`, kind: b.kind, deck: 'tok', status: 'queued', inputs: {},
        progress: { phase: '', done: 0, total: 0, label: '' }, result: null, error: null,
        created_at: 0, started_at: null, finished_at: null } as never
    }
    c.job = async (id) => ({ id, kind: 'export', deck: 'tok', status: 'succeeded', inputs: {},
      progress: { phase: '', done: 0, total: 0, label: '' },
      result: { video: '/course/videos/deck.draft.mp4', duration: 3, draft: true }, error: null,
      created_at: 0, started_at: 0, finished_at: 0 }) as never
    c.command = async (_t, body) => {
      if (body.expected_revision !== this.revision) {
        throw new ApiError(409, 'revision_conflict', 'The narration file changed.')
      }
      this.commands.push(body as unknown as Record<string, unknown>)
      this.rev++
      return { changed: true, revision: this.revision }
    }
    c.engineVoices = async (engine) => ({ engine: engine as 'kokoro', voices: engine === 'kokoro' ? ['am_echo', 'af_bella'] : [], default: engine === 'kokoro' ? 'am_echo' : null })
    c.pages = async () => ({ images: this.pages.map((id) => (this.imagesRendered ? `/img/${this.pdfRev}/${id}.png` : null)) })
    return c
  }

  private status(queued = 0): GenerationStatusDTO {
    return { engine: 'kokoro', done: 0, total: 0, running: null, inflight: [], queued }
  }

  release(): void {
    this.holding = false
    this.holdingAnswers = false
    for (const resolve of this.hold.splice(0)) resolve()
  }
}
