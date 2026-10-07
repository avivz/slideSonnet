import type { LibraryDeckDTO, LibraryDTO } from '@/api/client'

export function deck(label: string, token = label): LibraryDeckDTO {
  const parts = label.split('/')
  const name = parts.at(-1) as string
  const group = parts.slice(0, -1).join('/')
  return {
    token,
    name,
    label,
    group,
    section: group.split('/')[0] ?? '',
    narrated: true,
    url: `/d/${token}`,
  }
}

/** week01 holds one deck, week02 two, plus a lone deck at the root. */
export function library(): LibraryDTO {
  return {
    root: 'course',
    parents: ['~', 'teaching'],
    sections: [
      { title: '', decks: [deck('overview')] },
      { title: 'week01', decks: [deck('week01/intro/intro', 'i')] },
      { title: 'week02', decks: [deck('week02/llm_basics', 'l'), deck('week02/prompting', 'p')] },
    ],
    unnarrated: [{ ...deck('week03/draft', 'd'), narrated: false }],
    truncated: false,
  }
}
