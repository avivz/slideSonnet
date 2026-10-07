// The deck editor's state: the server snapshot, and the drafts the browser owns.
//
// Rules (docs/frontend-migration.md, "Editing and conflict rules"):
// - Typing never waits on the network. Edits land in a draft; a valid draft is
//   autosaved after a short pause, one save at a time per deck.
// - A save carries the narration revision it was edited against. The server
//   refuses a stale one (409); the draft is then rebased if its own slide
//   didn't change on disk, or the user is shown both versions if it did.
// - A reload from disk updates clean slides and never touches a dirty draft
//   (B1's real fix): an outside edit to a slide being edited is a conflict with
//   explicit choices, not a silent overwrite of either side. Every such slide
//   is held (never saved) until the user chooses; they are shown one at a time.
// - Answers to requests made before the latest open() belong to another deck
//   (or an older load) and are dropped (`loadEpoch`).
import { defineStore } from 'pinia'
import { computed, reactive, ref, shallowRef } from 'vue'

import {
  api,
  ApiError,
  type ApiClient,
  type Backend,
  type DeckSnapshot,
  type MetaDTO,
  type PageDTO,
} from '@/api/client'
import {
  blockSegments,
  editBlock,
  fingerprint,
  keepKeys,
  syncSilenceFields,
  takeOutsideEdit,
  written,
  type EditBlock,
} from '@/features/editor/narration'

/** How long typing must pause before a draft is saved. */
export const AUTOSAVE_MS = 500

export type SaveState = 'saved' | 'unsaved' | 'saving' | 'conflict' | 'error'
export type FlashKind = 'info' | 'ok' | 'warn' | 'err'

export interface Draft {
  block: EditBlock
  /** Fingerprint of this slide as the server has it (last loaded or acknowledged). */
  baseline: string
  /** Fingerprint of the server's version this draft was reconciled with (moves on a conflict only when resolved). */
  serverFp: string
  /** The narration revision our last acknowledged save of this slide produced. */
  ackRevision: string | null
}

export interface Conflict {
  slideId: string
  /** The user's unsaved version (plain text of the utterances). */
  mine: string
  /** What the file on disk now says. */
  theirs: string
}

export interface SavedEvent {
  slideId: string
  changed: boolean
}

function plainText(block: EditBlock): string {
  return block.middle
    .filter((s) => s.kind === 'speech')
    .map((s) => s.text)
    .join('\n\n')
}

export const useEditorStore = defineStore('editor', () => {
  const client = shallowRef<ApiClient>(api)
  const token = ref<string | null>(null)
  const snapshot = shallowRef<DeckSnapshot | null>(null)
  const meta = shallowRef<MetaDTO | null>(null)
  /** The session's engine pick (never written to the deck); null = the deck default. */
  const engine = ref<Backend | null>(null)
  const index = ref(0)
  const loadError = ref<string | null>(null)
  const drafts = reactive(new Map<string, Draft>())
  /** Slides changed on disk while they had unsaved typing, in the order found. */
  const conflicts = reactive(new Map<string, Conflict>())
  /** The last save failed: shown until a save succeeds or nothing is left unsaved. */
  const saveFailed = ref(false)
  /** Saves sent and not answered yet. */
  const inFlight = ref(0)
  const flashMessage = ref<{ text: string; kind: FlashKind; id: number } | null>(null)
  /** The narration revision the next save must name. */
  const revision = ref('')
  /** Page images by index (filled in as pages render in the background). */
  const images = ref<(string | null)[]>([])
  /** Bumped whenever the narration changed on disk from outside this tab. */
  const externalChanges = ref(0)
  /** Bumped by every open(); other stores compare it too, to drop late answers. */
  const loadEpoch = ref(0)
  /** Revisions this tab's own saves produced (to tell them from outside edits). */
  const ownRevisions = new Set<string>()
  /** Saves of ours answered so far (a snapshot asked for before one may predate it). */
  let acks = 0

  let timer: ReturnType<typeof setTimeout> | null = null
  let saving: Promise<void> = Promise.resolve()
  let flashId = 0
  let refreshing: Promise<void> | null = null
  let refreshAgain = false
  const savedListeners = new Set<(e: SavedEvent) => void>()

  // ---- derived ---------------------------------------------------------------
  const pages = computed<PageDTO[]>(() => snapshot.value?.pages ?? [])
  const page = computed<PageDTO | null>(() => pages.value[index.value] ?? null)
  const currentId = computed(() => page.value?.slide_id ?? '')
  const activeEngine = computed<Backend | null>(() => engine.value ?? snapshot.value?.engine ?? null)
  const errorCount = computed(
    () => snapshot.value?.diagnostics.filter((d) => d.severity === 'error').length ?? 0,
  )
  const diagnosticsHere = computed(
    () => snapshot.value?.diagnostics.filter((d) => d.slide_id === currentId.value) ?? [],
  )
  /** Findings no slide shows: about the whole deck, or about narration whose slide is gone. */
  const deckDiagnostics = computed(() => {
    const onPage = new Set(pages.value.map((p) => p.slide_id))
    return snapshot.value?.diagnostics.filter((d) => d.slide_id == null || !onPage.has(d.slide_id)) ?? []
  })
  const dirtySlides = computed(() =>
    [...drafts.entries()].filter(([, d]) => fingerprint(d.block) !== d.baseline).map(([s]) => s),
  )
  /** The conflict shown now; any others wait their turn. */
  const conflict = computed<Conflict | null>(() => conflicts.values().next().value ?? null)
  const saveState = computed<SaveState>(() => {
    if (conflicts.size > 0) return 'conflict'
    if (inFlight.value > 0) return 'saving'
    if (dirtySlides.value.length === 0) return 'saved'
    return saveFailed.value ? 'error' : 'unsaved'
  })
  const hasUnsaved = computed(
    () => dirtySlides.value.length > 0 || inFlight.value > 0 || conflicts.size > 0,
  )

  // ---- loading -----------------------------------------------------------------
  function serverBlock(snap: DeckSnapshot, slideId: string): EditBlock {
    const pageDto = snap.pages.find((p) => p.slide_id === slideId)
    return editBlock(
      slideId,
      snap.narration[slideId],
      pageDto?.incoming ?? { kind: 'cut', seconds: 0 },
      snap.silence,
    )
  }

  /**
   * Open a deck. Unsaved typing is never dropped: reopening the same deck keeps
   * it, and another deck opens only once it is saved — false when it couldn't
   * be (this deck then stays open), or when a newer open() took over.
   */
  async function open(deckToken: string): Promise<boolean> {
    const same = deckToken === token.value && snapshot.value !== null
    if (!same && token.value !== null && hasUnsaved.value && !(await ensureSaved())) return false
    clearTimer()
    const epoch = ++loadEpoch.value
    loadError.value = null
    if (same) {
      for (const [slideId, d] of drafts) {
        // a clean draft is rebuilt from the file — unless it holds a new line still to type into
        const clean = fingerprint(d.block) === d.baseline && d.block.middle.every(written)
        if (clean && !conflicts.has(slideId)) drafts.delete(slideId)
      }
    } else {
      token.value = deckToken
      snapshot.value = null // never build a draft from the previous deck's snapshot
      images.value = []
      drafts.clear()
      conflicts.clear()
      saveFailed.value = false
      index.value = 0
    }
    try {
      if (meta.value === null) {
        const m = await client.value.meta()
        if (epoch !== loadEpoch.value) return false
        meta.value = m
      }
      const snap = await client.value.snapshot(deckToken, engine.value)
      if (epoch !== loadEpoch.value) return false // a newer open won
      if (same) {
        reconcile(snap)
        const dirty = dirtySlides.value[0]
        if (dirty !== undefined) touch(dirty) // the autosave was waiting on it
      } else {
        snapshot.value = snap
        revision.value = snap.revisions.narration
        images.value = snap.pages.map((p) => p.image_url ?? null)
      }
    } catch (e) {
      if (epoch !== loadEpoch.value) return false
      loadError.value = e instanceof ApiError ? e.message : 'The editor server could not be reached.'
    }
    return true
  }

  /** Refetch the snapshot and reconcile drafts with it (coalesced). */
  async function refresh(): Promise<void> {
    if (refreshing) {
      refreshAgain = true
      return refreshing
    }
    refreshing = (async () => {
      do {
        refreshAgain = false
        if (token.value === null) return
        const epoch = loadEpoch.value
        const asked = engine.value
        const acked = acks
        let snap: DeckSnapshot
        try {
          snap = await client.value.snapshot(token.value, asked)
        } catch (e) {
          // a half-written file on disk: keep the last good snapshot, say why
          if (e instanceof ApiError && epoch === loadEpoch.value) flash(e.message, 'warn')
          return
        }
        if (epoch !== loadEpoch.value) continue // another deck (or load) since: not ours
        if (asked !== engine.value) {
          refreshAgain = true // the engine changed meanwhile: ask again, for the new one
          continue
        }
        // a save of ours landed meanwhile, or is still on its way: this answer may not
        // have it yet, and would read as an outside edit (rolling the slide back, or a
        // conflict with itself) — the save's own refresh brings the file as saved
        if (acks !== acked || inFlight.value > 0) continue
        reconcile(snap)
      } while (refreshAgain)
    })().finally(() => {
      refreshing = null
    })
    return refreshing
  }

  function reconcile(snap: DeckSnapshot): void {
    const newRevision = snap.revisions.narration
    const before = snapshot.value?.revisions.narration
    if (before !== undefined && newRevision !== before && !ownRevisions.has(newRevision)) {
      externalChanges.value++
    }
    // while a render fills in, keep showing what we have — after a recompile too:
    // each slide holds its last picture (by id, as pages may move) until its new
    // one is rendered, so the strip and stage never blank
    const key = (p: { slide_id: string }, i: number): string => p.slide_id || `#${i}` // unmarked: by place
    const shown = new Map((snapshot.value?.pages ?? []).map((p, i) => [key(p, i), images.value[i]]))
    snapshot.value = snap
    images.value = snap.pages.map((p, i) => p.image_url ?? shown.get(key(p, i)) ?? null)
    if (inFlight.value === 0) revision.value = newRevision
    for (const [slideId, draft] of drafts) {
      const theirs = serverBlock(snap, slideId)
      const theirsFp = fingerprint(theirs)
      if (theirsFp === draft.serverFp) {
        conflicts.delete(slideId) // the file is back to what this draft was edited against
        continue
      }
      if (draft.ackRevision !== null && draft.ackRevision === newRevision) {
        draft.serverFp = theirsFp
        draft.baseline = theirsFp // our own save, as the server wrote it
        continue
      }
      if (fingerprint(draft.block) === draft.baseline) {
        draft.block = takeOutsideEdit(draft.block, theirs) // changed elsewhere, nothing typed here: take it
        draft.baseline = theirsFp
        draft.serverFp = theirsFp
        draft.ackRevision = null
        conflicts.delete(slideId)
      } else {
        // both sides changed: hold both until the user chooses (serverFp moves only then)
        conflicts.set(slideId, { slideId, mine: plainText(draft.block), theirs: plainText(theirs) })
      }
    }
    if (index.value >= snap.pages.length) index.value = Math.max(0, snap.pages.length - 1)
  }

  // ---- drafts ---------------------------------------------------------------------
  /** The editable block for `slideId` (created from the snapshot on first use). */
  function draftFor(slideId: string): EditBlock | null {
    const snap = snapshot.value
    if (snap === null || slideId === '') return null
    let draft = drafts.get(slideId)
    if (draft === undefined) {
      const block = serverBlock(snap, slideId)
      const fp = fingerprint(block)
      draft = { block, baseline: fp, serverFp: fp, ackRevision: null }
      drafts.set(slideId, draft)
    }
    return draft.block
  }

  function isDirty(slideId: string): boolean {
    const d = drafts.get(slideId)
    return d !== undefined && fingerprint(d.block) !== d.baseline
  }

  /** Call after any edit to a draft: schedules the autosave. */
  function touch(slideId: string, { immediate = false } = {}): void {
    const d = drafts.get(slideId)
    if (d === undefined || snapshot.value === null) return
    syncSilenceFields(d.block, snapshot.value.silence)
    if (!isDirty(slideId)) return
    clearTimer()
    if (immediate) void flush()
    else timer = setTimeout(() => void flush(), AUTOSAVE_MS)
  }

  function clearTimer(): void {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  /**
   * Save every dirty slide now and wait for the server to acknowledge them.
   * True only when nothing is left unsaved or in conflict: whatever consumes
   * the narration (play, generate, export, review, leaving the deck) stops on false.
   */
  function flush(): Promise<boolean> {
    clearTimer()
    saving = saving.then(async () => {
      for (const slideId of dirtySlides.value) {
        if (conflicts.has(slideId)) continue // never saved over an outside edit
        await saveSlide(slideId)
      }
    })
    return saving.then(() => dirtySlides.value.length === 0 && conflicts.size === 0)
  }

  /** flush(), saying why when something is still unsaved. */
  async function ensureSaved(): Promise<boolean> {
    if (await flush()) return true
    if (conflicts.size > 0) flash('First choose which version of the narration to keep.', 'warn')
    else if (!saveFailed.value) flash('Your latest changes aren’t saved yet — try again in a moment.', 'warn')
    // a failed save already said why, and stays shown as "Not saved"
    return false
  }

  async function saveSlide(slideId: string, retried = false): Promise<void> {
    const draft = drafts.get(slideId)
    if (draft === undefined || token.value === null) return
    const sent = fingerprint(draft.block)
    if (sent === draft.baseline) return
    const epoch = loadEpoch.value
    inFlight.value++
    try {
      const result = await client.value.saveSlide(token.value, slideId, {
        expected_revision: revision.value,
        segments: blockSegments(draft.block),
        transition_in: draft.block.transitionIn,
        transition_out: draft.block.transitionOut,
      })
      inFlight.value--
      if (epoch !== loadEpoch.value) return // another deck is open now
      revision.value = result.revision
      ownRevisions.add(result.revision)
      acks++
      draft.baseline = sent // acknowledges exactly what was sent; newer typing stays dirty
      draft.ackRevision = result.revision
      saveFailed.value = false
      for (const listener of savedListeners) listener({ slideId, changed: result.changed })
      void refresh()
      if (fingerprint(draft.block) !== draft.baseline) touch(slideId)
    } catch (e) {
      inFlight.value--
      if (epoch !== loadEpoch.value) return
      if (e instanceof ApiError && e.code === 'revision_conflict' && !retried) {
        await refresh() // flags a conflict when this very slide changed on disk
        if (!conflicts.has(slideId)) return saveSlide(slideId, true)
        return
      }
      saveFailed.value = true
      flash(e instanceof ApiError ? e.message : 'Saving failed — check that the editor is running.', 'err')
    }
  }

  function onSaved(listener: (e: SavedEvent) => void): () => void {
    savedListeners.add(listener)
    return () => savedListeners.delete(listener)
  }

  /** Resolve the conflict shown: write the user's version over the file, or take the file's. */
  async function resolveConflict(choice: 'mine' | 'theirs'): Promise<void> {
    const c = conflict.value
    if (c === null) return
    const draft = drafts.get(c.slideId)
    if (draft === undefined || snapshot.value === null) {
      conflicts.delete(c.slideId)
      return
    }
    if (choice === 'mine') await refresh() // replace the file's latest version, not an older one
    const theirs = serverBlock(snapshot.value, c.slideId)
    draft.serverFp = fingerprint(theirs)
    draft.ackRevision = null
    conflicts.delete(c.slideId)
    if (choice === 'theirs') {
      draft.block = keepKeys(draft.block, theirs)
      draft.baseline = draft.serverFp
      return
    }
    // keep mine: the file's version is now the baseline we knowingly replace
    draft.baseline = draft.serverFp
    await flush()
  }

  // ---- navigation -----------------------------------------------------------------
  function go(i: number): void {
    const n = pages.value.length
    if (n === 0) return
    const target = Math.max(0, Math.min(i, n - 1))
    if (target === index.value) return
    void flush() // leaving a slide saves it; typing elsewhere never waits
    index.value = target
  }

  function goToSlide(slideId: string): void {
    const i = pages.value.findIndex((p) => p.slide_id === slideId)
    if (i >= 0) go(i)
  }

  /** Refetch page images only (cheap; used while pages render in the background). */
  async function refreshPages(): Promise<void> {
    if (token.value === null) return
    const epoch = loadEpoch.value
    try {
      const fresh = (await client.value.pages(token.value)).images
      // a page not rendered yet keeps the picture it shows
      if (epoch === loadEpoch.value) images.value = fresh.map((url, i) => url ?? images.value[i] ?? null)
    } catch {
      // keep what we have
    }
  }

  /** A picture that failed to load (an old one a recompile deleted): show none until the new one. */
  function imageFailed(url: string): void {
    if (images.value.includes(url)) images.value = images.value.map((u) => (u === url ? null : u))
  }

  async function setEngine(next: Backend | null): Promise<void> {
    engine.value = next
    await refresh()
  }

  // ---- commands (orphans, voices) ---------------------------------------------------
  async function command(body: Parameters<ApiClient['command']>[1]): Promise<boolean> {
    if (token.value === null) return false
    if (!(await ensureSaved())) return false
    const epoch = loadEpoch.value
    try {
      const result = await client.value.command(token.value, { ...body, expected_revision: revision.value })
      if (epoch !== loadEpoch.value) return false
      revision.value = result.revision
      ownRevisions.add(result.revision)
      await refresh()
      return true
    } catch (e) {
      if (epoch !== loadEpoch.value) return false
      if (e instanceof ApiError && e.code === 'revision_conflict') {
        await refresh()
        flash('The narration file changed on disk — look again and retry.', 'warn')
      } else {
        flash(e instanceof ApiError ? e.message : 'That didn’t work — check the editor server.', 'err')
      }
      return false
    }
  }

  // ---- flash line -------------------------------------------------------------------
  function flash(text: string, kind: FlashKind = 'info'): void {
    flashId++
    const id = flashId
    flashMessage.value = { text, kind, id }
    setTimeout(
      () => {
        if (flashMessage.value?.id === id) flashMessage.value = null
      },
      kind === 'warn' || kind === 'err' ? 8000 : 4000,
    )
  }

  return {
    client, token, snapshot, meta, engine, activeEngine, index, loadError, drafts, saveState,
    conflict, conflicts, flashMessage, revision, images, externalChanges, loadEpoch, pages, page,
    currentId, errorCount, diagnosticsHere, deckDiagnostics, dirtySlides, hasUnsaved,
    open, refresh, refreshPages, imageFailed, draftFor, isDirty, touch, flush, ensureSaved, onSaved,
    resolveConflict, go, goToSlide, setEngine, command, flash,
  }
})
