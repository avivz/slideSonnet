import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, ApiError, type ApiClient, type DeckStatsDTO, type LibraryDTO } from '@/api/client'
import { displayGroups } from '@/features/library/library'

/** How many decks' stats are fetched at once (each reads a PDF and a sidecar). */
const STATS_CONCURRENCY = 4

export const useLibraryStore = defineStore('library', () => {
  const client = ref<ApiClient>(api)
  const library = ref<LibraryDTO | null>(null)
  const stats = ref<Record<string, DeckStatsDTO | 'error'>>({})
  const loading = ref(false)
  const error = ref<string | null>(null)
  const query = ref('')

  const groups = computed(() => (library.value ? displayGroups(library.value, query.value) : []))
  /** Every visible deck in on-screen order (keyboard highlight walks this). */
  const visible = computed(() => groups.value.flatMap((g) => g.decks))
  const deckCount = computed(
    () => library.value?.sections.reduce((n, s) => n + s.decks.length, 0) ?? 0,
  )

  async function load(options: { rescan?: boolean } = {}): Promise<void> {
    await fill(() => client.value.library(options))
  }

  /** List decks from another folder (`..` is up); it stays the library's folder. */
  async function moveTo(path: string): Promise<void> {
    await fill(() => client.value.setLibraryRoot(path))
  }

  async function fill(fetchLibrary: () => Promise<LibraryDTO>): Promise<void> {
    loading.value = true
    error.value = null
    try {
      library.value = await fetchLibrary()
      stats.value = {}
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : 'The editor server could not be reached.'
      return
    } finally {
      loading.value = false
    }
    await loadStats()
  }

  /** Fill in each deck's counts after first paint, a few at a time. */
  async function loadStats(): Promise<void> {
    const tokens = library.value?.sections.flatMap((s) => s.decks.map((d) => d.token)) ?? []
    let next = 0
    const worker = async (): Promise<void> => {
      while (next < tokens.length) {
        const token = tokens[next++] as string
        try {
          stats.value[token] = await client.value.deckStats(token)
        } catch {
          stats.value[token] = 'error'
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(STATS_CONCURRENCY, tokens.length) }, worker))
  }

  return { client, library, stats, loading, error, query, groups, visible, deckCount, load, moveTo, loadStats }
})
