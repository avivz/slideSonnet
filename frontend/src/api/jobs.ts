import type { ApiClient, JobDTO } from './client'

const FINISHED = new Set(['succeeded', 'failed', 'cancelled'])

/**
 * Resolve when job `id` has finished (any outcome). Polls with a gentle
 * backoff; `wake()` on the returned handle (e.g. on a `job.finished` event)
 * re-checks at once. Jobs belong to the server, so a dropped event stream only
 * costs a poll interval, never the result.
 */
export function waitForJob(
  client: ApiClient,
  id: string,
  onProgress?: (job: JobDTO) => void,
): { done: Promise<JobDTO>; wake: () => void; abandon: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null
  let delay = 200
  let abandoned = false
  let resolveDone: (job: JobDTO) => void = () => {}
  let rejectDone: (e: unknown) => void = () => {}
  const done = new Promise<JobDTO>((resolve, reject) => {
    resolveDone = resolve
    rejectDone = reject
  })
  const check = async (): Promise<void> => {
    if (abandoned) return
    timer = null
    try {
      const job = await client.job(id)
      if (FINISHED.has(job.status)) {
        resolveDone(job)
        return
      }
      onProgress?.(job)
    } catch (e) {
      rejectDone(e)
      return
    }
    delay = Math.min(1000, delay * 1.5)
    if (!abandoned) timer = setTimeout(() => void check(), delay)
  }
  timer = setTimeout(() => void check(), 50)
  return {
    done,
    wake: () => {
      if (timer !== null) {
        clearTimeout(timer)
        void check()
      }
    },
    abandon: () => {
      abandoned = true
      if (timer !== null) clearTimeout(timer)
    },
  }
}
