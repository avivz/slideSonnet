// Typed access to the slideSonnet backend (`/api/v1`). The DTO types are
// generated from the server's OpenAPI schema (`npm run api-types`); nothing in
// here is hand-written guesswork about a response shape.
import type { components } from './schema'

export type Schemas = components['schemas']
export type LibraryDTO = Schemas['LibraryDTO']
export type LibraryDeckDTO = Schemas['LibraryDeckDTO']
export type LibrarySectionDTO = Schemas['LibrarySectionDTO']
export type DeckStatsDTO = Schemas['DeckStatsDTO']
export type DeckSnapshot = Schemas['DeckSnapshot']
export type JobDTO = Schemas['JobDTO']
export type PageDTO = Schemas['PageDTO']
export type BlockDTO = Schemas['BlockDTO']
export type SpeechDTO = Schemas['SpeechDTO']
export type PauseDTO = Schemas['PauseDTO']
export type SegmentDTO = SpeechDTO | PauseDTO
export type TransitionDTO = Schemas['TransitionDTO']
export type DiagnosticDTO = Schemas['DiagnosticDTO']
export type SaveResponse = Schemas['SaveResponse']
export type MetaDTO = Schemas['MetaDTO']
export type EngineVoicesDTO = Schemas['EngineVoicesDTO']
export type PagesDTO = Schemas['PagesDTO']
export type GenerationStatusDTO = Schemas['GenerationStatusDTO']
export type ClipRef = Schemas['ClipRef']
export type Backend = Schemas['EngineVoicesDTO']['engine']
export type ReviewDTO = Schemas['ReviewDTO']
export type ConversationDTO = Schemas['ConversationDTO']
export type ReviewOutcomeDTO = Schemas['ReviewOutcomeDTO']
export type ReviewCommand =
  | Schemas['ReviewMarkSeen']
  | Schemas['ReviewComment']
  | Schemas['ReviewReply']
  | Schemas['ReviewAccept']
  | Schemas['ReviewRetitle']
  | Schemas['ReviewReopen']
  | Schemas['ReviewClear']
  | Schemas['ReviewFileUnrequested']
export type DeckCommand =
  | Schemas['AttachOrphan']
  | Schemas['AppendOrphan']
  | Schemas['DeleteOrphan']
  | Schemas['EditVoices']
export type JobRequest =
  | Schemas['GenerateJob']
  | Schemas['PreviewJob']
  | Schemas['ExportJob']
  | Schemas['RenderPagesJob']
  | Schemas['WarmJob']

export const API_PREFIX = '/api/v1'
export const SESSION_HEADER = 'X-SlideSonnet-Session'

/** An error from the backend: a stable code plus a message fit to show the user. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

type Fetch = typeof fetch

export interface ClientOptions {
  fetch?: Fetch
  base?: string
}

async function toError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } }
    if (body.error?.code) {
      return new ApiError(response.status, body.error.code, body.error.message ?? body.error.code)
    }
  } catch {
    // not a JSON error body (a proxy, a crash page) — fall through
  }
  return new ApiError(response.status, 'http_error', `The editor server answered ${response.status}.`)
}

/**
 * A small fetch wrapper: JSON in and out, stable errors, and the per-process
 * session token on every mutating request (fetched once, refreshed once if the
 * server restarted and no longer recognizes it).
 */
export class ApiClient {
  private readonly fetchImpl: Fetch
  private readonly base: string
  private session: string | null = null

  constructor(options: ClientOptions = {}) {
    this.fetchImpl = options.fetch ?? ((input, init) => fetch(input, init))
    this.base = options.base ?? API_PREFIX
  }

  async get<T>(path: string): Promise<T> {
    const response = await this.fetchImpl(this.base + path, {
      headers: { Accept: 'application/json' },
    })
    if (!response.ok) throw await toError(response)
    return (await response.json()) as T
  }

  async send<T>(method: 'POST' | 'PATCH' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
    let retried = false
    for (;;) {
      const token = await this.sessionToken()
      const response = await this.fetchImpl(this.base + path, {
        method,
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          [SESSION_HEADER]: token,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      if (response.ok) return (await response.json()) as T
      const error = await toError(response)
      if (error.code === 'bad_session' && !retried) {
        retried = true
        this.session = null // the server restarted: fetch a fresh token once
        continue
      }
      throw error
    }
  }

  private async sessionToken(): Promise<string> {
    if (this.session === null) {
      this.session = (await this.get<Schemas['SessionDTO']>('/session')).token
    }
    return this.session
  }

  // ---- endpoints ---------------------------------------------------------
  library(options: { rescan?: boolean } = {}): Promise<LibraryDTO> {
    return this.get(options.rescan ? '/library?rescan=true' : '/library')
  }

  deckStats(token: string): Promise<DeckStatsDTO> {
    return this.get(`/decks/${encodeURIComponent(token)}/stats`)
  }

  job(id: string): Promise<JobDTO> {
    return this.get(`/jobs/${encodeURIComponent(id)}`)
  }

  snapshot(token: string, engine?: string | null): Promise<DeckSnapshot> {
    const q = engine ? `?engine=${encodeURIComponent(engine)}` : ''
    return this.get(`/decks/${encodeURIComponent(token)}${q}`)
  }

  meta(): Promise<MetaDTO> {
    return this.get('/meta')
  }

  pages(token: string): Promise<PagesDTO> {
    return this.get(`/decks/${encodeURIComponent(token)}/pages`)
  }

  engineVoices(engine: string): Promise<EngineVoicesDTO> {
    return this.get(`/engines/${encodeURIComponent(engine)}/voices`)
  }

  exportBlockers(token: string): Promise<string[]> {
    return this.get(`/decks/${encodeURIComponent(token)}/export-blockers`)
  }

  saveSlide(
    token: string,
    slideId: string,
    body: Schemas['SlideEdit'],
  ): Promise<SaveResponse> {
    return this.send('PATCH', `/decks/${encodeURIComponent(token)}/slides/${encodeURIComponent(slideId)}`, body)
  }

  command(token: string, body: DeckCommand): Promise<SaveResponse> {
    return this.send('POST', `/decks/${encodeURIComponent(token)}/commands`, body)
  }

  startJob(token: string, body: JobRequest): Promise<JobDTO> {
    return this.send('POST', `/decks/${encodeURIComponent(token)}/jobs`, body)
  }

  cancelJob(id: string): Promise<JobDTO> {
    return this.send('POST', `/jobs/${encodeURIComponent(id)}/cancel`)
  }

  generation(token: string, engine?: string | null): Promise<GenerationStatusDTO> {
    const q = engine ? `?engine=${encodeURIComponent(engine)}` : ''
    return this.get(`/decks/${encodeURIComponent(token)}/generation${q}`)
  }

  generate(token: string, body: Schemas['GenerateRequest']): Promise<GenerationStatusDTO> {
    return this.send('POST', `/decks/${encodeURIComponent(token)}/generation`, body)
  }

  cancelGeneration(token: string, body: Schemas['CancelGenerationRequest']): Promise<Schemas['CountDTO']> {
    return this.send('POST', `/decks/${encodeURIComponent(token)}/generation/cancel`, body)
  }

  review(token: string): Promise<ReviewDTO> {
    return this.get(`/decks/${encodeURIComponent(token)}/review`)
  }

  reviewCommand(token: string, body: ReviewCommand): Promise<ReviewOutcomeDTO> {
    return this.send('POST', `/decks/${encodeURIComponent(token)}/review/commands`, body)
  }

  focus(token: string, body: Schemas['FocusRequest']): Promise<Schemas['CountDTO']> {
    return this.send('POST', `/decks/${encodeURIComponent(token)}/focus`, body)
  }
}

/** The client the app uses; tests build their own with a fake fetch. */
export const api = new ApiClient()
