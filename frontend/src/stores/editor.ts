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
//   explicit choices, not a silent overwrite of either side.
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
  /** Fingerprint of the server's version as last seen in a snapshot. */
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
  const saveState = ref<SaveState>('saved')
  const conflict = ref<Conflict | null>(null)
  const flashMessage = ref<{ text: string; kind: FlashKind; id: number } | null>(null)
  /** The narration revision the next save must name. */
  const revision = ref('')
  /** Page images by index (filled in as pages render in the background). */
  const images = ref<(string | null)[]>([])
  /** Bumped whenever the narration changed on disk from outside this tab. */
  const externalChanges = ref(0)
  /** Revisions this tab's own saves produced (to tell them from outside edits). */
  const ownRevisions = new Set<string>()

  let timer: ReturnType<typeof setTimeout> | null = null
  let saving: Promise<void> = Promise.resolve()
  let inFlight = 0
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
  const dirtySlides = computed(() =>
    [...drafts.entries()].filter(([, d]) => fingerprint(d.block) !== d.baseline).map(([s]) => s),
  )
  const hasUnsaved = computed(
    () => dirtySlides.value.length > 0 || saveState.value === 'saving' || conflict.value !== null,
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

  async function open(deckToken: string): Promise<void> {
    clearTimer()
    token.value = deckToken
    snapshot.value = null // never build a draft from the previous deck's snapshot
    images.value = []
    drafts.clear()
    conflict.value = null
    saveState.value = 'saved'
    loadError.value = null
    index.value = 0
    try {
      if (meta.value === null) meta.value = await client.value.meta()
      const snap = await client.value.snapshot(deckToken, engine.value)
      snapshot.value = snap
      revision.value = snap.revisions.narration
      images.value = snap.pages.map((p) => p.image_url ?? null)
    } catch (e) {
      loadError.value = e instanceof ApiError ? e.message : 'The editor server could not be reached.'
    }
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
        let snap: DeckSnapshot
        try {
          snap = await client.value.snapshot(token.value, engine.value)
        } catch (e) {
          // a half-written file on disk: keep the last good snapshot, say why
          if (e instanceof ApiError) flash(e.message, 'warn')
          return
        }
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
    // while a render fills in, keep showing what we have; a recompiled PDF's old
    // pictures are of another build (and deleted), so they go
    const samePdf = snapshot.value?.revisions.pdf === snap.revisions.pdf
    snapshot.value = snap
    images.value = snap.pages.map((p, i) => p.image_url ?? (samePdf ? images.value[i] : null) ?? null)
    if (inFlight === 0) revision.value = newRevision
    for (const [slideId, draft] of drafts) {
      const theirs = serverBlock(snap, slideId)
      const theirsFp = fingerprint(theirs)
      if (theirsFp === draft.serverFp) continue // this slide didn't change on the server
      draft.serverFp = theirsFp
      if (draft.ackRevision !== null && draft.ackRevision === newRevision) {
        draft.baseline = theirsFp // our own save, as the server wrote it
        continue
      }
      const dirty = fingerprint(draft.block) !== draft.baseline
      if (!dirty) {
        draft.block = keepKeys(draft.block, theirs) // changed elsewhere, nothing typed here: take it
        draft.baseline = theirsFp
        draft.ackRevision = null
      } else if (conflict.value === null) {
        conflict.value = { slideId, mine: plainText(draft.block), theirs: plainText(theirs) }
        saveState.value = 'conflict'
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
    if (!isDirty(slideId)) {
      if (saveState.value === 'unsaved' && dirtySlides.value.length === 0) saveState.value = 'saved'
      return
    }
    if (saveState.value !== 'conflict' && saveState.value !== 'saving') saveState.value = 'unsaved'
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

  /** Save every dirty slide now and wait for the server to acknowledge them. */
  function flush(): Promise<void> {
    clearTimer()
    saving = saving.then(async () => {
      for (const slideId of dirtySlides.value) {
        if (conflict.value?.slideId === slideId) continue
        await saveSlide(slideId)
      }
    })
    return saving
  }

  async function saveSlide(slideId: string, retried = false): Promise<void> {
    const draft = drafts.get(slideId)
    if (draft === undefined || token.value === null) return
    const sent = fingerprint(draft.block)
    if (sent === draft.baseline) return
    saveState.value = 'saving'
    inFlight++
    try {
      const result = await client.value.saveSlide(token.value, slideId, {
        expected_revision: revision.value,
        segments: blockSegments(draft.block),
        transition_in: draft.block.transitionIn,
        transition_out: draft.block.transitionOut,
      })
      revision.value = result.revision
      ownRevisions.add(result.revision)
      draft.baseline = sent // acknowledges exactly what was sent; newer typing stays dirty
      draft.ackRevision = result.revision
      saveState.value = dirtySlides.value.length > 0 ? 'unsaved' : 'saved'
      for (const listener of savedListeners) listener({ slideId, changed: result.changed })
      inFlight--
      void refresh()
      if (fingerprint(draft.block) !== draft.baseline) touch(slideId)
    } catch (e) {
      inFlight--
      if (e instanceof ApiError && e.code === 'revision_conflict' && !retried) {
        await refresh() // flags a conflict when this very slide changed on disk
        if (conflict.value?.slideId !== slideId) return saveSlide(slideId, true)
        return
      }
      saveState.value = 'error'
      flash(e instanceof ApiError ? e.message : 'Saving failed — check that the editor is running.', 'err')
    }
  }

  function onSaved(listener: (e: SavedEvent) => void): () => void {
    savedListeners.add(listener)
    return () => savedListeners.delete(listener)
  }

  /** Resolve a conflict: write the user's version over the file, or take the file's. */
  async function resolveConflict(choice: 'mine' | 'theirs'): Promise<void> {
    const c = conflict.value
    if (c === null) return
    conflict.value = null
    const draft = drafts.get(c.slideId)
    if (draft === undefined || snapshot.value === null) return
    if (choice === 'theirs') {
      draft.block = serverBlock(snapshot.value, c.slideId)
      draft.baseline = fingerprint(draft.block)
      saveState.value = dirtySlides.value.length > 0 ? 'unsaved' : 'saved'
      return
    }
    // keep mine: the file's version is now the baseline we knowingly replace
    draft.baseline = draft.serverFp
    draft.ackRevision = null
    await refresh()
    touch(c.slideId, { immediate: true })
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
    try {
      images.value = (await client.value.pages(token.value)).images
    } catch {
      // keep what we have
    }
  }

  async function setEngine(next: Backend | null): Promise<void> {
    engine.value = next
    await refresh()
  }

  // ---- commands (orphans, voices) ---------------------------------------------------
  async function command(body: Parameters<ApiClient['command']>[1]): Promise<boolean> {
    if (token.value === null) return false
    await flush()
    try {
      const result = await client.value.command(token.value, { ...body, expected_revision: revision.value })
      revision.value = result.revision
      ownRevisions.add(result.revision)
      await refresh()
      return true
    } catch (e) {
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
    conflict, flashMessage, revision, images, externalChanges, pages, page, currentId, errorCount,
    diagnosticsHere, dirtySlides, hasUnsaved,
    open, refresh, refreshPages, draftFor, isDirty, touch, flush, onSaved, resolveConflict, go,
    goToSlide, setEngine, command, flash,
  }
})
