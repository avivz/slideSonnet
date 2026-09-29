// Clip generation for the open deck: the server's per-deck queue seen from
// this tab, plus the tab's own "Auto-generate as I edit" behavior.
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { ApiError, type ClipRef, type GenerationStatusDTO } from '@/api/client'
import { useEditorStore } from '@/stores/editor'

/** Auto-generate waits this long after a slide's last save (the text is settling). */
export const AUTO_BUILD_MS = 2500

/** Asks the user before spending credits; resolves true only on an explicit yes. */
export type PaidConfirm = (count: number, engine: string, action: string) => Promise<boolean>

export const useGenerationStore = defineStore('generation', () => {
  const editor = useEditorStore()
  const status = ref<GenerationStatusDTO | null>(null)
  /** This tab, as the owner of the clips it asks for. */
  const owner = `tab-${Math.random().toString(36).slice(2, 10)}`
  const autoBuild = ref(false) // opt-in every session
  const singleSlideTransitions = ref(false)
  /** The utterance being typed in right now (auto-generate skips it). */
  const focusedSpeech = ref<{ slideId: string; index: number } | null>(null)
  let confirmPaid: PaidConfirm = async () => false
  const timers = new Map<string, ReturnType<typeof setTimeout>>()

  const engineInfo = computed(() =>
    editor.snapshot?.engines.find((e) => e.name === editor.activeEngine) ?? null,
  )
  const paid = computed(() => engineInfo.value?.paid ?? false)
  const realtime = computed(() => engineInfo.value?.realtime ?? true)
  const inflight = computed(
    () => new Set((status.value?.inflight ?? []).map((c) => `${c.slide_id}#${c.speech_index}`)),
  )
  const busy = computed(() => {
    const s = status.value
    return s !== null && (s.running !== null || s.done < s.total)
  })

  function setConfirm(fn: PaidConfirm): void {
    confirmPaid = fn
  }

  /** Still the deck and engine a request was made for (else its answer is dropped). */
  function asOf(): () => boolean {
    const epoch = editor.loadEpoch
    const engine = editor.activeEngine
    return () => epoch === editor.loadEpoch && engine === editor.activeEngine
  }

  // another deck: its queue and its pending auto-generates aren't this one's
  watch(
    () => editor.loadEpoch,
    () => {
      status.value = null
      focusedSpeech.value = null
      for (const t of timers.values()) clearTimeout(t)
      timers.clear()
    },
    { flush: 'sync' },
  )

  async function refresh(): Promise<void> {
    if (editor.token === null) return
    const current = asOf()
    try {
      const s = await editor.client.generation(editor.token, editor.activeEngine)
      if (current()) status.value = s
    } catch {
      // the server is restarting: the next event refreshes
    }
  }

  /** Queue clips (all missing when `targets` is null); asks first on a paid engine. */
  async function enqueue(
    targets: ClipRef[] | null,
    { force = false, action = 'Generate', allowPaid = false } = {},
  ): Promise<number> {
    if (editor.token === null) return 0
    if (!(await editor.ensureSaved())) return 0 // the server reads the narration from disk
    const current = asOf()
    try {
      const s = await editor.client.generate(editor.token, {
        targets, force, engine: editor.activeEngine, allow_paid: allowPaid, owner,
      })
      if (!current()) return 0
      status.value = s
      return s.queued ?? 0
    } catch (e) {
      if (!current()) return 0
      if (e instanceof ApiError && e.code === 'paid_confirmation_required' && !allowPaid) {
        const count = targets === null ? (editor.snapshot?.missing_audio ?? 0) : targets.length
        if (await confirmPaid(count, editor.activeEngine ?? '', action)) {
          return enqueue(targets, { force, action, allowPaid: true })
        }
        return 0
      }
      editor.flash(e instanceof ApiError ? e.message : 'Generation could not start.', 'err')
      return 0
    }
  }

  async function cancelAll(): Promise<number> {
    if (editor.token === null) return 0
    const r = await editor.client.cancelGeneration(editor.token, { engine: editor.activeEngine })
    await refresh()
    return r.count
  }

  /** Leaving the deck: drop the clips only this tab asked for. */
  async function leave(): Promise<void> {
    if (editor.token === null) return
    for (const t of timers.values()) clearTimeout(t)
    timers.clear()
    try {
      await editor.client.cancelGeneration(editor.token, { owner })
    } catch {
      // best effort: the server may already be gone
    }
  }

  async function focus(slideId: string): Promise<void> {
    if (editor.token === null) return
    try {
      await editor.client.focus(editor.token, { slide_id: slideId, engine: editor.activeEngine })
    } catch {
      // a priority hint only
    }
  }

  // ---- auto-generate ----------------------------------------------------------
  const autoBuildAllowed = computed(() => !paid.value) // a paid engine would bill every save

  function uncached(slideId?: string, exclude?: { slideId: string; index: number } | null): ClipRef[] {
    const out: ClipRef[] = []
    for (const page of editor.snapshot?.pages ?? []) {
      if (slideId !== undefined && page.slide_id !== slideId) continue
      for (const [index, clip] of (page.clips ?? []).entries()) {
        const skip = exclude && exclude.slideId === page.slide_id && exclude.index === index
        if (!clip.cached && !skip) out.push({ slide_id: page.slide_id, speech_index: index })
      }
    }
    return out
  }

  function scheduleAutoBuild(slideId: string): void {
    if (!autoBuild.value || !autoBuildAllowed.value) return
    const existing = timers.get(slideId)
    if (existing) clearTimeout(existing)
    timers.set(
      slideId,
      setTimeout(async () => {
        timers.delete(slideId)
        if (!autoBuild.value || !autoBuildAllowed.value) return
        await editor.refresh()
        const targets = uncached(slideId, focusedSpeech.value)
        if (targets.length) await enqueue(targets)
      }, AUTO_BUILD_MS),
    )
  }

  /** Turning auto-generate on fills in every missing clip except the open slide's. */
  async function setAutoBuild(on: boolean): Promise<void> {
    autoBuild.value = on && autoBuildAllowed.value
    if (!autoBuild.value) return
    const targets = uncached().filter((c) => c.slide_id !== editor.currentId)
    if (targets.length) await enqueue(targets)
  }

  /** After an outside change, fill in what it left without audio. */
  async function sweep(): Promise<void> {
    if (!autoBuild.value || !autoBuildAllowed.value) return
    const targets = uncached().filter((c) => c.slide_id !== editor.currentId)
    if (targets.length) await enqueue(targets)
  }

  editor.onSaved(({ slideId, changed }) => {
    if (changed) scheduleAutoBuild(slideId)
  })

  return {
    status, owner, autoBuild, singleSlideTransitions, focusedSpeech, paid, realtime, inflight,
    busy, autoBuildAllowed,
    setConfirm, refresh, enqueue, cancelAll, leave, focus, uncached, setAutoBuild, sweep,
  }
})
