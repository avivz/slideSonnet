import { describe, expect, it, vi } from 'vitest'

import { ApiClient, ApiError, SESSION_HEADER } from '@/api/client'

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('ApiClient', () => {
  it('maps error bodies to ApiError with the stable code', async () => {
    const fetch = vi.fn(async () => json(404, { error: { code: 'unknown_deck', message: 'No such deck.' } }))
    const client = new ApiClient({ fetch })
    await expect(client.snapshot('x')).rejects.toMatchObject({ status: 404, code: 'unknown_deck', message: 'No such deck.' })
  })

  it('reports a non-JSON failure without inventing a code', async () => {
    const client = new ApiClient({ fetch: async () => new Response('<html>', { status: 502 }) })
    const error = await client.library().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('http_error')
  })

  it('sends the session token on mutations and refreshes it once after a restart', async () => {
    const tokens = ['old', 'new']
    const seen: string[] = []
    const fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith('/session')) return json(200, { token: tokens.shift() })
      const token = new Headers(init?.headers).get(SESSION_HEADER) ?? ''
      seen.push(token)
      return token === 'new'
        ? json(200, { changed: true, revision: 'r2' })
        : json(403, { error: { code: 'bad_session', message: 'expired' } })
    })
    const client = new ApiClient({ fetch })
    await expect(client.send('PATCH', '/decks/t/slides/a', {})).resolves.toEqual({ changed: true, revision: 'r2' })
    expect(seen).toEqual(['old', 'new'])
  })
})
